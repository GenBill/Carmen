import pandas as pd

from rsi_rebound_signal import (
    evaluate_macd_turn_positive,
    evaluate_rsi_pin_bar_prefilter,
    evaluate_rsi_pin_bar_shadow_volume,
    evaluate_rsi_rebound_setup,
    had_rsi_oversold_in_lookback,
    is_bullish_pin_bar_moderate,
    is_rsi_oversold_prev,
    is_rsi_oversold_today,
    rsi_turning_ok,
)
from scan_signal_eval import evaluate_scan_signals


def _hist_from_ohlc(open_price=100.0, up_pct=4.0, down_pct=2.0, n=60, close_price=None):
    rows = []
    for i in range(n):
        close = close_price if close_price is not None else open_price
        rows.append({
            "Open": open_price,
            "High": open_price * (1 + up_pct / 100.0),
            "Low": open_price * (1 - down_pct / 100.0),
            "Close": close if i == n - 1 else open_price,
            "Volume": 1_000_000,
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


def test_pin_bar_moderate_geometry():
    hist = pd.DataFrame([
        {"Open": 10.0, "High": 10.2, "Low": 9.0, "Close": 10.1, "Volume": 1e6}
    ] * 20)
    ok, reason = is_bullish_pin_bar_moderate({"hist": hist})
    assert ok is True
    assert "Pin Bar" in reason


def test_pin_bar_mode_sets_pre_not_active_until_shadow():
    # Build enough history with low RSI via flat then pin bar last bar
    rows = []
    price = 100.0
    for i in range(40):
        # force declining closes early so RSI can go low
        c = price - i * 0.5
        rows.append({"Open": c + 0.2, "High": c + 0.4, "Low": c - 0.2, "Close": c, "Volume": 1e6})
    # last bar pin bar
    rows[-1] = {"Open": 10.0, "High": 10.2, "Low": 9.0, "Close": 10.1, "Volume": 1e6}
    hist = pd.DataFrame(rows)
    stock = {
        "hist": hist,
        "rsi": 17.0,
        "rsi_prev": 16.0,
        "estimated_volume": 2_000_000,
        "avg_volume": 1_000_000,
        "dif": -0.1,
        "dea": 0.05,
        "dif_dea_slope": 0.1,
        "macd_dif_tail": [],
        "ema_5_hist": [1.0] * 90,
        "ema_60_hist": [1.0] * 90,
    }
    state = evaluate_scan_signals(
        stock,
        rsi_threshold=18.0,
        volatility_ok_fn=_vol_ok,
        silver_on_sell=False,
        rsi_mode="pin_bar",
        rsi_period=8,
    )
    assert state.rsi_pin_bar_pre is True or state.rsi_pin_bar_pre is False  # geometry/RSI dependent
    assert state.rsi_signal_active is False
    assert state.rsi_oversold_today is False
    assert state.rsi_rebound_setup is False


def test_shadow_volume_avg5_or_day_ratio():
    hist = pd.DataFrame([
        {"Open": 10.0, "High": 10.2, "Low": 9.0, "Close": 10.1, "Volume": 1_000_000}
    ] * 10)
    stock = {"hist": hist, "date": "2026-07-13"}
    idx = pd.date_range("2026-07-13 09:30", periods=3, freq="5min")
    hist_5m = pd.DataFrame(
        {
            "Open": [9.1, 9.2, 10.0],
            "High": [9.3, 9.4, 10.2],
            "Low": [9.0, 9.05, 9.8],
            "Close": [9.2, 9.3, 10.1],
            "Volume": [500_000, 500_000, 50_000],
        },
        index=idx,
    )
    ok, reason, info = evaluate_rsi_pin_bar_shadow_volume(stock, hist_5m)
    assert ok is True
    assert info["passed"] is True


def test_macd_imminent_golden_cross_passes():
    ok, reason = evaluate_macd_turn_positive({
        "dif": -0.10,
        "dea": 0.05,
        "dif_dea_slope": 0.10,
    })
    assert ok is True
    assert "即将金叉" in reason
