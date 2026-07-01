import math

import pandas as pd

from main_a import (
    RSI_REBOUND_THRESHOLD,
    _a_share_scan_signal_ok,
    _a_share_should_submit_scan_ai,
    _rsi_rebound_volatility_ok,
    _rsi_rebound_setup_ok,
    _select_top_rsi_rebound_candidates,
    _is_rsi_oversold_candidate,
)
from telegram_notifier import format_signal_snapshot


def test_rsi_below_18_is_oversold_candidate():
    assert _is_rsi_oversold_candidate({"rsi": 17.9}) is True
    assert _a_share_scan_signal_ok(0.0, 0.0, True) is True


def test_rsi_18_none_or_nan_is_not_oversold_candidate():
    assert _is_rsi_oversold_candidate({"rsi": 18.0}) is False
    assert _is_rsi_oversold_candidate({"rsi": None}) is False
    assert _is_rsi_oversold_candidate({"rsi": math.nan}) is False


def test_rsi_candidate_bypasses_volume_or_tuo_gate():
    submit_ai, signal_ok, position_build_score, has_recent_golden_cross = _a_share_should_submit_scan_ai(
        score_buy=0.0,
        confidence=0.0,
        volume_ma_info={"position_build_score": 3.0, "has_recent_golden_cross": False},
        duanxian_tuo_info={"gate_ok": False},
        rsi_oversold_candidate=True,
    )

    assert signal_ok is True
    assert submit_ai is True
    assert position_build_score == 3.0
    assert has_recent_golden_cross is False


def test_normal_candidate_still_requires_existing_followup_gate():
    submit_ai, signal_ok, position_build_score, has_recent_golden_cross = _a_share_should_submit_scan_ai(
        score_buy=3.0,
        confidence=0.0,
        volume_ma_info={"position_build_score": 3.0, "has_recent_golden_cross": False},
        duanxian_tuo_info={"gate_ok": False},
        rsi_oversold_candidate=False,
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


def test_rsi_volatility_allows_strong_two_way_elasticity():
    ok, reason, info = _rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=4.0),
    })

    assert ok is True
    assert "平均+4.00%/-4.00%" in reason
    assert info["up_down_ratio"] == 1.0


def test_rsi_volatility_blocks_down_only_weak_rebound():
    ok, reason, info = _rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=2.0, down_pct=5.0),
    })

    assert ok is False
    assert "反弹弹性不足" in reason
    assert info["avg_up_pct"] == 2.0


def test_positive_elasticity_score_prefers_upside_bias():
    ok_pos, _, pos = _rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=2.0),
    })
    ok_balanced, _, balanced = _rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=4.0),
    })

    assert ok_pos is True
    assert ok_balanced is True
    assert pos["rebound_elasticity_score"] > balanced["rebound_elasticity_score"]


def test_select_top_rsi_rebound_candidates_limits_to_top3():
    candidates = [
        {"symbol": "A", "rebound_elasticity_score": 10.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "B", "rebound_elasticity_score": 15.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "C", "rebound_elasticity_score": 12.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "D", "rebound_elasticity_score": 20.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
    ]

    selected = _select_top_rsi_rebound_candidates(candidates, limit=3)

    assert [x["symbol"] for x in selected] == ["D", "B", "C"]


def test_rsi_rebound_telegram_title_and_elasticity_line():
    msg = format_signal_snapshot(
        title="📈反弹抄底信号",
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

    assert msg.splitlines()[0] == "📈反弹抄底信号"
    assert "弹性评分: 12.3 | 6个月平均 +4.0%/-2.0% | 上下比 2.00" in msg
