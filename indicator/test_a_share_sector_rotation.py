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
) -> ScanSignalState:
    return ScanSignalState(
        score=[score_buy, score_sell],
        rsi_oversold_today=rsi_oversold_today,
        rsi_rebound_setup=rsi_rebound_setup,
        rsi_signal_active=rsi_oversold_today or rsi_rebound_setup,
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
