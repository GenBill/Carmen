import pandas as pd

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
        })
    return pd.DataFrame(rows)


def _vol_ok(_stock_data):
    return True, "ok", {"rebound_elasticity_score": 10.0}


def test_evaluate_scan_signals_marks_oversold_and_caches_volatility():
    stock = {
        "rsi": 17.0,
        "rsi_prev": 18.0,
        "hist": _hist_from_ohlc(close_price=99.0),
        "estimated_volume": 2_000_000,
        "avg_volume": 1_000_000,
        "dif": -0.1,
        "dea": 0.05,
        "dif_dea_slope": 0.1,
        "macd_dif_tail": [],
        "ema_5_hist": [1.0] * 90,
        "ema_60_hist": [1.0] * 90,
    }
    state = evaluate_scan_signals(stock, rsi_threshold=18.0, volatility_ok_fn=_vol_ok, silver_on_sell=False)

    assert state.rsi_oversold_today is True
    assert state.rsi_signal_active is True
    assert state.pre_candidate is True
    assert stock.get('_rsi_rebound_volatility', {}).get('rebound_elasticity_score') == 10.0


def test_evaluate_scan_signals_without_rsi_skips_rsi_track():
    stock = {
        "rsi": 50.0,
        "rsi_prev": 48.0,
        "estimated_volume": 2_000_000,
        "avg_volume": 1_000_000,
        "dif": 0.1,
        "dea": 0.05,
        "dif_dea_slope": 0.1,
        "macd_dif_tail": [],
        "ema_5_hist": [1.0] * 90,
        "ema_60_hist": [1.0] * 90,
    }
    state = evaluate_scan_signals(stock, silver_on_sell=False)

    assert state.rsi_oversold_today is False
    assert state.rsi_signal_active is False
