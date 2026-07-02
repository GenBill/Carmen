import numpy as np
import pandas as pd

from get_stock_price import (
    _calculate_detail_fields_from_hist,
    _calculate_fast_scan_indicators_from_hist,
    _calculate_indicators_from_hist,
    enrich_stock_data_detail,
)


def _sample_hist(n=120):
    idx = pd.date_range('2025-01-01', periods=n, freq='B')
    close = 100 + np.linspace(0, 5, n)
    return pd.DataFrame({
        'Open': close - 0.5,
        'High': close + 1.0,
        'Low': close - 1.0,
        'Close': close,
        'Volume': np.full(n, 1_000_000.0),
    }, index=idx)


def test_full_path_matches_fast_core_plus_detail():
    hist = _sample_hist()
    symbol = '000001.SZ'
    full = _calculate_indicators_from_hist(
        hist, symbol, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8, volume_lut=None,
    )
    fast = _calculate_fast_scan_indicators_from_hist(
        hist, symbol, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8, volume_lut=None,
    )
    detail = _calculate_detail_fields_from_hist(hist, symbol, fast.get('estimated_volume'))

    assert full is not None and fast is not None and detail is not None
    for key in ('rsi', 'rsi_prev', 'dif', 'dea', 'dif_dea_slope', 'ema_5', 'ema_60', 'weekly_dif'):
        assert full.get(key) == fast.get(key)
    for key in ('volume_ma5', 'volume_ma10', 'volume_ma30', 'volume_ma60', 'volume_ma_info', 'duanxian_tuo_info'):
        assert full.get(key) == detail.get(key)


def test_enrich_preserves_core_and_adds_detail():
    hist = _sample_hist()
    symbol = 'AAPL'
    fast = _calculate_fast_scan_indicators_from_hist(
        hist, symbol, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8, volume_lut=None,
    )
    core_snapshot = {k: fast.get(k) for k in ('rsi', 'dif', 'dea', 'ema_5', 'macd_dif_tail')}

    enriched = enrich_stock_data_detail(fast, avg_volume_days=8)
    assert enriched is fast
    assert enriched.get('_fast_scan') is None
    assert enriched.get('volume_ma_info') is not None
    assert enriched.get('duanxian_tuo_info') is not None
    for key, value in core_snapshot.items():
        assert enriched.get(key) == value
