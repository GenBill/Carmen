import json
from datetime import date, datetime

import pytz
import sector_rotation as sr
from scan_signal_eval import ScanSignalState

BEIJING = pytz.timezone("Asia/Shanghai")


def _scan_state(
    *,
    score_buy: float = 0.0,
    score_sell: float = 0.0,
    pre_candidate: bool = True,
    rsi_oversold_today: bool = False,
    rsi_rebound_setup: bool = False,
    rsi_pin_bar_pre: bool = False,
    rsi_pin_bar_setup: bool = False,
) -> ScanSignalState:
    return ScanSignalState(
        score=[score_buy, score_sell],
        rsi_oversold_today=rsi_oversold_today,
        rsi_rebound_setup=rsi_rebound_setup,
        rsi_pin_bar_pre=rsi_pin_bar_pre,
        rsi_pin_bar_setup=rsi_pin_bar_setup,
        rsi_signal_active=rsi_oversold_today or rsi_rebound_setup or rsi_pin_bar_setup,
        tuo_signal_active=False,
        carmen_candidate=score_buy >= 2.0 or score_sell >= 2.0,
        pre_candidate=pre_candidate,
        rsi_rebound_volatility={},
        rsi_rebound_block_reason=None,
    )


def _patch_market_files(monkeypatch, market: str, tmp_path, signals_name: str, state_name: str):
    monkeypatch.setitem(sr.MARKET_CONFIGS[market], "signals_file", tmp_path / signals_name)
    monkeypatch.setitem(sr.MARKET_CONFIGS[market], "state_file", tmp_path / state_name)


def test_record_pre_candidate_dedup_same_day(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "A", tmp_path, "a.json", "a_state.json")
    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: _bj(2026, 7, 3, 12, 0))

    state = _scan_state(score_buy=2.5, rsi_oversold_today=True)
    sr.record_pre_candidate("A", "600000.SS", {}, state, {"600000.SS": "浦发银行"})
    sr.record_pre_candidate("A", "600000.SS", {}, state, {"600000.SS": "浦发银行"})

    items = sr.load_daily_signals("A", date(2026, 7, 3))
    assert len(items) == 1
    assert items[0]["scan_count"] == 2
    assert "carmen_buy" in items[0]["signal_types"]


def test_record_pre_candidate_buckets_by_day(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "A", tmp_path, "a.json", "a_state.json")
    days = iter([_bj(2026, 7, 3, 12, 0), _bj(2026, 7, 4, 12, 0)])
    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: next(days))

    state = _scan_state(score_buy=3.0)
    sr.record_pre_candidate("A", "000001.SZ", {}, state, {"000001.SZ": "平安银行"})
    sr.record_pre_candidate("A", "600000.SS", {}, state, {"600000.SS": "浦发银行"})

    assert len(sr.load_daily_signals("A", date(2026, 7, 3))) == 1
    assert len(sr.load_daily_signals("A", date(2026, 7, 4))) == 1


def test_filter_signals_for_report_keeps_buy_and_rebound_only():
    raw = [
        {"symbol": "600352.SS", "name": "浙江龙盛", "signal_types": ["carmen_sell"]},
        {"symbol": "600000.SS", "name": "浦发银行", "signal_types": ["carmen_buy", "rsi_oversold"]},
        {"symbol": "000001.SZ", "name": "平安银行", "signal_types": ["rsi_rebound"]},
    ]
    filtered = sr.filter_signals_for_report("A", raw)

    assert len(filtered) == 2
    assert filtered[0]["code"] == "000001"
    assert filtered[1]["code"] == "600000"


def test_should_run_sector_rotation_report_idempotent(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "A", tmp_path, "a.json", "a_state.json")
    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: _bj(2026, 7, 3, 12, 0))
    monkeypatch.setattr(
        sr,
        "session_date_for_market",
        lambda market, when=None: date(2026, 7, 3),
    )

    assert sr.should_run_sector_rotation_report("A", date(2026, 7, 5)) is False

    sr.record_pre_candidate(
        "A",
        "600000.SS",
        {},
        _scan_state(score_buy=2.2),
        {"600000.SS": "浦发银行"},
    )
    assert sr.should_run_sector_rotation_report("A", date(2026, 7, 3)) is True

    sr.mark_report_success("A", date(2026, 7, 3), 1)
    assert sr.should_run_sector_rotation_report("A", date(2026, 7, 3)) is False
    assert sr.should_run_sector_rotation_report("A", date(2026, 7, 3), force=True) is True


def test_should_not_run_for_weekend_report_day_with_signals(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "A", tmp_path, "a.json", "a_state.json")
    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: _bj(2026, 7, 5, 12, 0))

    sr.record_pre_candidate(
        "A",
        "600000.SS",
        {},
        _scan_state(score_buy=2.2),
        {"600000.SS": "浦发银行"},
    )

    assert len(sr.load_daily_signals("A", date(2026, 7, 5))) == 1
    assert sr.should_run_sector_rotation_report("A", date(2026, 7, 5)) is False


def test_post_close_window_uses_beijing_now(monkeypatch):
    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: _bj(2026, 7, 3, 16, 29))
    assert sr.is_post_close_scan("A") is True

    monkeypatch.setattr(sr, "_beijing_now", lambda when=None: _bj(2026, 7, 3, 16, 30))
    assert sr.is_post_close_scan("A") is False


def test_openclaw_cmd_skips_model_by_default(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = '{"reply":"ok"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.delenv("CARMEN_SECTOR_ROTATION_OPENCLAW_MODEL", raising=False)
    monkeypatch.setattr(sr.subprocess, "run", fake_run)

    assert sr._call_openclaw_sector_rotation("A", "prompt", 1) == "ok"
    assert "--model" not in captured["cmd"]


def test_filter_signals_hk_and_us():
    hk_raw = [{"symbol": "0700.HK", "name": "腾讯控股", "signal_types": ["carmen_buy"]}]
    us_raw = [{"symbol": "NVDA", "name": "", "signal_types": ["carmen_buy", "rsi_rebound"]}]
    assert sr.filter_signals_for_report("HK", hk_raw)[0]["code"] == "0700"
    assert sr.filter_signals_for_report("US", us_raw)[0]["code"] == "NVDA"


def test_build_sector_rotation_title_and_template():
    title = sr.build_sector_rotation_title("A", "2026-07-03")
    assert title == "📊 板块轮动分析 · 🇨🇳 A股 · 2026-07-03"
    template = sr.build_sector_rotation_body_template("A", "2026-07-03")
    assert template.startswith(title)
    assert "Cluster 1：" in template
    assert "边缘信号：" in template
    assert "重点观察方向：" in template


def test_has_b_or_above_rotation_parses_cluster_grades():
    high = (
        "📊 板块轮动分析 · 🇨🇳 A股 · 2026-07-03\n"
        "结论：有轮动\n"
        "Cluster 1：半导体，优先级 B\n"
        "判断：多只联动\n"
        "边缘信号：无\n"
    )
    low = (
        "📊 板块轮动分析 · 🇺🇸 美股 · 2026-07-03\n"
        "结论：偏弱\n"
        "Cluster 1：消费电子，优先级 C\n"
        "判断：仅主题联想\n"
        "Cluster 2：小盘成长，优先级 D\n"
        "边缘信号：NVDA\n"
    )
    empty = "📊 板块轮动分析 · 🇭🇰 港股 · 2026-07-03\n结论：无有效 cluster\n边缘信号：0700\n"
    assert sr.extract_cluster_priorities(high) == ["B"]
    assert sr.has_b_or_above_rotation(high) is True
    assert sr.extract_cluster_priorities(low) == ["C", "D"]
    assert sr.has_b_or_above_rotation(low) is False
    assert sr.extract_cluster_priorities(empty) == []
    assert sr.has_b_or_above_rotation(empty) is False
    assert sr.has_b_or_above_rotation("Cluster 1：AI，优先级 S") is True
    assert sr.has_b_or_above_rotation("Cluster 1：AI，优先级 A") is True


def test_build_sector_rotation_prompt_minimal_payload(monkeypatch):
    monkeypatch.setattr(sr, "load_telegram_token", lambda token_path=None: ("token", "123"))
    signals = [
        {"code": "600000", "name": "浦发银行", "signal_types": ["carmen_buy"]},
    ]
    prompt = sr.build_sector_rotation_prompt("A", "2026-07-03", signals, "token", "123")

    assert "📊 板块轮动分析 · 🇨🇳 A股 · 2026-07-03" in prompt
    payload = prompt.split("\n\n", 1)[1]
    data = json.loads(payload)
    assert data["startup_signals"] == signals
    assert "body_template" in data["telegram_output"]
    assert data["telegram_output"]["also_send_via_bot_api"] is False
    assert "Cluster 1：" in data["telegram_output"]["body_template"]


def _bj(y, m, d, hh, mm):
    return BEIJING.localize(datetime(y, m, d, hh, mm))


def test_us_session_date_uses_beijing_calendar_day():
    assert sr.session_date_for_market("US", _bj(2026, 7, 3, 16, 0)) == date(2026, 7, 3)
    assert sr.session_date_for_market("US", _bj(2026, 7, 3, 10, 0)) == date(2026, 7, 3)
    assert sr.session_date_for_market("A", _bj(2026, 7, 3, 16, 0)) == date(2026, 7, 3)


def test_us_record_and_report_share_session_key(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "US", tmp_path, "us.json", "us_state.json")
    when = _bj(2026, 7, 3, 16, 0)
    monkeypatch.setattr(sr, "_beijing_now", lambda w=None: when)

    state = _scan_state(score_buy=2.5)
    sr.record_pre_candidate("US", "NVDA", {}, state)
    day = sr.session_date_for_market("US")
    assert day == date(2026, 7, 3)
    assert len(sr.load_daily_signals("US", day)) == 1
    assert sr.should_run_sector_rotation_report("US", day) is True


def test_run_daily_skips_send_when_no_b_or_above(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "HK", tmp_path, "hk.json", "hk_state.json")
    when = _bj(2026, 7, 3, 17, 0)
    monkeypatch.setattr(sr, "_beijing_now", lambda w=None: when)
    monkeypatch.setattr(sr, "session_date_for_market", lambda market, w=None: date(2026, 7, 3))
    monkeypatch.setattr(sr, "load_telegram_token", lambda token_path=None: ("token", "123"))
    monkeypatch.setattr(sr, "_openclaw_timeout", lambda: 1)
    monkeypatch.setattr(
        sr,
        "_call_openclaw_sector_rotation",
        lambda market, prompt, timeout: (
            "BEGIN_TELEGRAM_MESSAGE\n"
            "📊 板块轮动分析 · 🇭🇰 港股 · 2026-07-03\n"
            "结论：偏弱\n"
            "Cluster 1：互联网，优先级 C\n"
            "判断：联动不足\n"
            "边缘信号：0700\n"
            "END_TELEGRAM_MESSAGE"
        ),
    )
    sent = {"called": False}
    monkeypatch.setattr(sr, "send_telegram_html", lambda message: sent.__setitem__("called", True))
    monkeypatch.setattr(sr, "append_signal_audit", lambda payload: None)

    sr.record_pre_candidate(
        "HK",
        "0700.HK",
        {},
        _scan_state(score_buy=2.2),
        {"0700.HK": "腾讯控股"},
    )
    assert sr.run_daily_sector_rotation_report("HK") is False
    assert sent["called"] is False
    assert sr.should_run_sector_rotation_report("HK", date(2026, 7, 3)) is False
    assert sr._load_state("HK").get("status") == "skipped"


def test_run_daily_sends_when_has_b_or_above(tmp_path, monkeypatch):
    _patch_market_files(monkeypatch, "US", tmp_path, "us.json", "us_state.json")
    when = _bj(2026, 7, 3, 10, 0)
    monkeypatch.setattr(sr, "_beijing_now", lambda w=None: when)
    monkeypatch.setattr(sr, "session_date_for_market", lambda market, w=None: date(2026, 7, 3))
    monkeypatch.setattr(sr, "load_telegram_token", lambda token_path=None: ("token", "123"))
    monkeypatch.setattr(sr, "_openclaw_timeout", lambda: 1)
    monkeypatch.setattr(
        sr,
        "_call_openclaw_sector_rotation",
        lambda market, prompt, timeout: (
            "BEGIN_TELEGRAM_MESSAGE\n"
            "📊 板块轮动分析 · 🇺🇸 美股 · 2026-07-03\n"
            "结论：有轮动\n"
            "Cluster 1：半导体，优先级 B\n"
            "判断：多只联动\n"
            "边缘信号：无\n"
            "END_TELEGRAM_MESSAGE"
        ),
    )
    sent = {"body": None}
    monkeypatch.setattr(sr, "send_telegram_html", lambda message: sent.__setitem__("body", message))
    monkeypatch.setattr(sr, "append_signal_audit", lambda payload: None)

    sr.record_pre_candidate("US", "NVDA", {}, _scan_state(score_buy=2.5))
    assert sr.run_daily_sector_rotation_report("US") is True
    assert sent["body"] is not None
    assert "优先级 B" in sent["body"]
    assert sr._load_state("US").get("status") == "sent"
