import pandas as pd

from rsi_rebound_signal import (
    evaluate_rsi_rebound_setup,
    is_rsi_oversold_prev,
    is_rsi_oversold_today,
    rsi_turning_ok,
)


def _hist_from_ohlc(open_price=100.0, up_pct=4.0, down_pct=2.0, n=60, close_price=None):
    rows = []
    for i in range(n):
        close = close_price if close_price is not None else open_price
        rows.append({
            "Open": open_price,
            "High": open_price * (1 + up_pct / 100.0),
            "Low": open_price * (1 - down_pct / 100.0),
            "Close": close if i == n - 1 else open_price,
        })
    return pd.DataFrame(rows)


def _vol_ok(_stock_data):
    return True, "ok", {"rebound_elasticity_score": 10.0}


def test_oversold_today_does_not_require_turning():
    stock = {"rsi": 17.0, "rsi_prev": 18.0, "hist": _hist_from_ohlc(close_price=99.0)}
    assert is_rsi_oversold_today(stock, 18.0) is True
    ok, _, _ = evaluate_rsi_rebound_setup(stock, 18.0, _vol_ok)
    assert ok is False


def test_rebound_setup_allows_today_rsi_above_threshold():
    stock = {
        "rsi": 22.0,
        "rsi_prev": 16.0,
        "hist": _hist_from_ohlc(close_price=101.0),
    }
    assert is_rsi_oversold_today(stock, 18.0) is False
    assert is_rsi_oversold_prev(stock, 18.0) is True
    ok, _, _ = evaluate_rsi_rebound_setup(stock, 18.0, _vol_ok)
    assert ok is True


def test_rebound_setup_requires_prev_oversold_and_turning():
    stock = {
        "rsi": 17.0,
        "rsi_prev": 20.0,
        "hist": _hist_from_ohlc(close_price=99.0),
    }
    ok, reason, _ = evaluate_rsi_rebound_setup(stock, 18.0, _vol_ok)
    assert ok is False
    assert "前一日RSI未超卖" in reason
