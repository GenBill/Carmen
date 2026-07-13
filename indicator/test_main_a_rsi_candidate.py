import math
from datetime import datetime

import pandas as pd
import pytz

from main_a import (
    A_SHARE_RSI_BOTTOM_ALERTS_ENABLED,
    _a_share_rsi_pin_bar_scan_allowed,
    _a_share_scan_signal_ok,
    _a_share_should_submit_scan_ai,
    _is_rsi_oversold_candidate,
    _rsi_rebound_volatility_ok,
    _select_top_rsi_rebound_candidates,
    _should_submit_regular_ai_after_rsi_queue,
)
from rsi_rebound_signal import (
    evaluate_rsi_pin_bar_shadow_volume,
    is_bullish_pin_bar_moderate,
)
from telegram_notifier import format_signal_snapshot


def test_a_share_rsi_bottom_alerts_disabled():
    assert A_SHARE_RSI_BOTTOM_ALERTS_ENABLED is False


def test_a_share_pin_bar_time_gate_blocked_when_disabled():
    tz = pytz.timezone("Asia/Shanghai")
    assert _a_share_rsi_pin_bar_scan_allowed(tz.localize(datetime(2026, 7, 13, 15, 59))) is False
    assert _a_share_rsi_pin_bar_scan_allowed(tz.localize(datetime(2026, 7, 13, 16, 0))) is False


def test_rsi_pin_bar_setup_flag_gated_by_alerts_enabled():
    # A 股关闭 RSI+Pin Bar 时，候选判定恒为 False
    assert _is_rsi_oversold_candidate({"rsi": 17.9}) is False
    assert _is_rsi_oversold_candidate({"_rsi_pin_bar_setup": True}) is False
    assert _is_rsi_oversold_candidate({"rsi": 18.0}) is False
    assert _is_rsi_oversold_candidate({"rsi": None}) is False
    assert _is_rsi_oversold_candidate({"rsi": math.nan}) is False


def test_a_share_regular_gate_still_blocks_low_score_without_tuo():
    submit_ai, signal_ok, position_build_score, has_recent_golden_cross = _a_share_should_submit_scan_ai(
        score_buy=0.0,
        confidence=0.0,
        volume_ma_info={"position_build_score": 3.0, "has_recent_golden_cross": False},
        duanxian_tuo_info={"gate_ok": False},
        rsi_signal_active=True,
    )

    assert signal_ok is False
    assert submit_ai is False
    assert position_build_score == 3.0
    assert has_recent_golden_cross is False


def test_normal_candidate_still_requires_existing_followup_gate():
    submit_ai, signal_ok, position_build_score, has_recent_golden_cross = _a_share_should_submit_scan_ai(
        score_buy=3.0,
        confidence=0.0,
        volume_ma_info={"position_build_score": 3.0, "has_recent_golden_cross": False},
        duanxian_tuo_info={"gate_ok": False},
        rsi_signal_active=False,
    )

    assert signal_ok is True
    assert submit_ai is False
    assert position_build_score == 3.0
    assert has_recent_golden_cross is False


def _hist_from_ohlc(open_price=100.0, up_pct=4.0, down_pct=2.0, n=60):
    rows = []
    for _ in range(n):
        rows.append({
            "Open": open_price,
            "High": open_price * (1 + up_pct / 100.0),
            "Low": open_price * (1 - down_pct / 100.0),
            "Close": open_price,
        })
    return pd.DataFrame(rows)


def test_rsi_volatility_passes_balanced_positive_elasticity():
    ok, reason, info = _rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=2.0),
    })

    assert ok is True
    assert "平均+4.00%/-2.00%" in reason
    assert info["avg_up_pct"] == 4.0
    assert info["avg_down_pct"] == 2.0
    assert info["up_down_ratio"] == 2.0


def test_select_top_rsi_rebound_candidates_limits_to_top3():
    candidates = [
        {"symbol": "A", "rebound_elasticity_score": 10.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "B", "rebound_elasticity_score": 15.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "C", "rebound_elasticity_score": 12.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "D", "rebound_elasticity_score": 20.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
    ]

    selected = _select_top_rsi_rebound_candidates(candidates, limit=3)
    assert [x["symbol"] for x in selected] == ["D", "B", "C"]

    all_selected = _select_top_rsi_rebound_candidates(candidates, limit=0)
    assert [x["symbol"] for x in all_selected] == ["D", "B", "C", "A"]


def test_rsi_signal_that_is_not_enqueued_does_not_fallback_to_regular_ai():
    assert _should_submit_regular_ai_after_rsi_queue(True, False) is False
    assert _should_submit_regular_ai_after_rsi_queue(True, True) is False
    assert _should_submit_regular_ai_after_rsi_queue(False, False) is True


def test_bullish_pin_bar_moderate_and_shadow_or_gate():
    hist = pd.DataFrame([
        {"Open": 10.0, "High": 10.2, "Low": 9.0, "Close": 10.1, "Volume": 1_000_000}
    ] * 10)
    stock = {"hist": hist, "date": "2026-07-13"}
    ok, reason = is_bullish_pin_bar_moderate(stock)
    assert ok is True
    assert "Pin Bar" in reason

    # 5m bars mostly in lower shadow zone; day ratio passes
    idx = pd.date_range("2026-07-13 09:30", periods=4, freq="5min")
    hist_5m = pd.DataFrame(
        {
            "Open": [9.1, 9.2, 9.3, 10.0],
            "High": [9.3, 9.4, 9.5, 10.2],
            "Low": [9.0, 9.05, 9.1, 9.8],
            "Close": [9.2, 9.3, 9.4, 10.1],
            "Volume": [400_000, 400_000, 400_000, 100_000],
        },
        index=idx,
    )
    vol_ok, vol_reason, info = evaluate_rsi_pin_bar_shadow_volume(stock, hist_5m)
    assert vol_ok is True
    assert info["passed_day_ratio"] is True


def test_rsi_rebound_telegram_title_and_elasticity_line():
    msg = format_signal_snapshot(
        title="📉RSI超跌+Pin Bar",
        symbol="300515.SZ",
        price=13.05,
        score=0.0,
        backtest_text="(RSI18)",
        rsi_prev=16.0,
        rsi=17.5,
        rsi_rebound_volatility={
            "rebound_elasticity_score": 12.34,
            "avg_up_pct": 4.0,
            "avg_down_pct": 2.0,
            "up_down_ratio": 2.0,
        },
        now_text="2026-06-30 09:40",
    )

    assert msg.splitlines()[0] == "📉RSI超跌+Pin Bar"
    assert "弹性评分: 12.3 | 6个月平均 +4.0%/-2.0% | 上下比 2.00" in msg
