import math

import pandas as pd

from main import (
    US_RSI_REBOUND_THRESHOLD,
    _is_us_rsi_oversold_candidate,
    _select_top_us_rsi_rebound_candidates,
    _should_submit_us_regular_ai_after_rsi_queue,
    _us_rsi_rebound_volatility_ok,
)


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


def test_us_rsi_threshold_is_24():
    assert US_RSI_REBOUND_THRESHOLD == 24.0
    assert _is_us_rsi_oversold_candidate({"rsi": 23.99}) is True
    assert _is_us_rsi_oversold_candidate({"rsi": 24.0}) is False
    assert _is_us_rsi_oversold_candidate({"rsi": None}) is False
    assert _is_us_rsi_oversold_candidate({"rsi": math.nan}) is False


def test_us_rsi_volatility_blocks_weak_rebound():
    ok, reason, info = _us_rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=2.0, down_pct=5.0),
    })

    assert ok is False
    assert "反弹弹性不足" in reason
    assert info["avg_up_pct"] == 2.0


def test_us_positive_elasticity_score_prefers_upside_bias():
    ok_pos, _, pos = _us_rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=2.0),
    })
    ok_balanced, _, balanced = _us_rsi_rebound_volatility_ok({
        "hist": _hist_from_ohlc(up_pct=4.0, down_pct=4.0),
    })

    assert ok_pos is True
    assert ok_balanced is True
    assert pos["rebound_elasticity_score"] > balanced["rebound_elasticity_score"]


def test_select_top_us_rsi_rebound_candidates_limits_to_top3():
    candidates = [
        {"symbol": "A", "rebound_elasticity_score": 10.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "B", "rebound_elasticity_score": 15.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "C", "rebound_elasticity_score": 12.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
        {"symbol": "D", "rebound_elasticity_score": 20.0, "rsi_rebound_volatility": {"up_down_ratio": 1.0}},
    ]

    selected = _select_top_us_rsi_rebound_candidates(candidates, limit=3)

    assert [x["symbol"] for x in selected] == ["D", "B", "C"]


def test_us_rsi_signal_that_is_not_enqueued_does_not_fallback_to_regular_ai():
    assert _should_submit_us_regular_ai_after_rsi_queue(True, False) is False
    assert _should_submit_us_regular_ai_after_rsi_queue(True, True) is False
    assert _should_submit_us_regular_ai_after_rsi_queue(False, False) is True
