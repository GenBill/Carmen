import numpy as np
import pandas as pd

from get_stock_price import (
    _calculate_detail_fields_from_hist,
    _calculate_duanxian_tuo_info,
    _calculate_fast_scan_indicators_from_hist,
    _calculate_indicators_from_hist,
    enrich_stock_data_detail,
)
from scan_ai_common import (
    IMMINENT_CROSS_WEIGHT,
    MIN_POSITION_BUILD_SCORE,
    apply_duanxian_tuo_gate_metadata,
    build_scan_backtest_str,
    duanxian_left_tuo_gate_ok,
    evaluate_duanxian_tuo_gates,
    format_duanxian_tuo_display,
    scan_buy_signal_ok,
    tuo_type_label,
    volume_ma_ai_gate_ok,
)
from scan_signal_eval import evaluate_tuo_signals


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
    for key in ('rsi', 'rsi_prev', 'dif', 'dea', 'dif_dea_slope', 'ema_12', 'ema_144', 'weekly_dif'):
        assert full.get(key) == fast.get(key)
    for key in ('volume_ma5', 'volume_ma10', 'volume_ma30', 'volume_ma60', 'volume_ma_info', 'duanxian_tuo_info'):
        assert full.get(key) == detail.get(key)


def test_fast_scan_defers_volume_and_tuo_to_detail():
    hist = _sample_hist()
    symbol = 'AAPL'
    fast = _calculate_fast_scan_indicators_from_hist(
        hist, symbol, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8, volume_lut=None,
    )

    assert fast is not None
    assert fast.get('volume_ma_info') is None
    assert fast.get('duanxian_tuo_info') is None


def test_enrich_preserves_core_and_adds_detail():
    hist = _sample_hist()
    symbol = 'AAPL'
    fast = _calculate_fast_scan_indicators_from_hist(
        hist, symbol, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8, volume_lut=None,
    )
    core_snapshot = {k: fast.get(k) for k in ('rsi', 'dif', 'dea', 'macd_dif_tail', 'ema_12')}

    enriched = enrich_stock_data_detail(fast, avg_volume_days=8)
    assert enriched is fast
    assert enriched.get('_fast_scan') is None
    assert enriched.get('volume_ma_info') is not None
    assert enriched.get('duanxian_tuo_info') is not None
    assert 'has_recent_golden_cross' in enriched['volume_ma_info']
    for key, value in core_snapshot.items():
        assert enriched.get(key) == value


def test_volume_ma_ai_gate_ok_uses_position_build_score_only():
    ok, pbs, gcx = volume_ma_ai_gate_ok(
        {'position_build_score': MIN_POSITION_BUILD_SCORE, 'has_recent_golden_cross': False},
    )
    assert ok is True
    assert pbs == MIN_POSITION_BUILD_SCORE
    assert gcx is False

    ok_gcx_only, _, gcx_only = volume_ma_ai_gate_ok(
        {'position_build_score': 3.0, 'has_recent_golden_cross': True},
    )
    assert ok_gcx_only is False
    assert gcx_only is True


def test_duanxian_tuo_imminent_detects_pre_confirmation():
    idx = pd.date_range('2026-05-20', periods=35, freq='B')
    closes = [
        17.33, 17.06, 17.13, 16.95, 16.49, 15.91, 16.14, 15.85, 16.21,
        15.70, 15.39, 15.18, 18.22, 19.68, 19.72, 19.36, 19.33, 19.54,
        18.85, 20.49, 19.95, 20.69, 20.09, 19.92, 19.13, 17.96, 17.68,
        16.80, 16.50, 18.00, 17.82, 18.16, 18.93, 20.36, 22.03,
    ]
    volumes = [
        1221703, 2508400, 2115800, 1658700, 1944100, 2275685, 1588629,
        2735100, 1792697, 1713800, 1275961, 1066400, 9635569, 17288792,
        8007688, 5464361, 5399300, 4930110, 5854210, 8874450, 4700500,
        7266987, 4535976, 3575826, 4190604, 4747300, 4323458, 3488354,
        2424600, 6420182, 4798300, 2989100, 8256502, 12249390, 13783932,
    ]
    hist = pd.DataFrame({
        'Open': closes,
        'High': closes,
        'Low': closes,
        'Close': closes,
        'Volume': volumes,
    }, index=idx)

    pre_hist = hist.iloc[:-1]
    pre = _calculate_duanxian_tuo_info(pre_hist, closes[-2])
    left_ok, left_summary = duanxian_left_tuo_gate_ok(None, pre)
    confirmed = _calculate_duanxian_tuo_info(hist, closes[-1])

    price_tuo = pre['price_tuo']
    volume_tuo = pre['volume_tuo']
    assert price_tuo['weighted_cross_score'] == (
        price_tuo['actual_cross_count'] + price_tuo['imminent_cross_count'] * IMMINENT_CROSS_WEIGHT
    )
    assert volume_tuo['weighted_cross_score'] == (
        volume_tuo['actual_cross_count'] + volume_tuo['imminent_cross_count'] * IMMINENT_CROSS_WEIGHT
    )
    assert pre['gate_ok'] is False
    assert pre['price_tuo_imminent_ok'] is False
    assert pre['volume_tuo_imminent_ok'] is True
    assert pre['summary'] == '量托预确认'
    assert left_ok is True
    assert left_summary == '量托预确认'
    assert confirmed['volume_tuo_ok'] is True
    assert confirmed['summary'] == '价托预确认 / 量托确认'


def test_left_tuo_passes_on_price_or_volume_imminent_flag():
    vol_only, summary = duanxian_left_tuo_gate_ok(None, {
        'volume_tuo_imminent_ok': True,
        'price_tuo_imminent_ok': False,
    })
    assert vol_only is True
    assert summary == '量托预确认'

    price_only, summary = duanxian_left_tuo_gate_ok(None, {
        'volume_tuo_imminent_ok': False,
        'price_tuo_imminent_ok': True,
    })
    assert price_only is True
    assert summary == '价托预确认'

    both, summary = duanxian_left_tuo_gate_ok(None, {
        'volume_tuo_imminent_ok': True,
        'price_tuo_imminent_ok': True,
    })
    assert both is True
    assert summary == '价托预确认 / 量托预确认'

    none, summary = duanxian_left_tuo_gate_ok(None, {
        'volume_tuo_imminent_ok': False,
        'price_tuo_imminent_ok': False,
        'summary': '无',
    })
    assert none is False
    assert summary == '无'


def test_evaluate_tuo_signals_inactive_without_carmen_or_detail():
    stock = {
        'duanxian_tuo_info': {'gate_ok': True, 'summary': '价托确认'},
        'volume_ma_info': {'position_build_score': 9.0},
    }
    state = evaluate_tuo_signals(stock, carmen_candidate=False)
    assert state.tuo_signal_active is False
    assert stock.get('_duanxian_tuo_candidate') is False

    fast_only = {'duanxian_tuo_info': None, 'volume_ma_info': None}
    state = evaluate_tuo_signals(fast_only, carmen_candidate=True)
    assert state.tuo_signal_active is False


def test_format_duanxian_tuo_display_shows_confirmed_and_imminent():
    info = {
        'price_tuo_ok': True,
        'price_tuo_imminent_ok': False,
        'volume_tuo_ok': False,
        'volume_tuo_imminent_ok': True,
        'price_tuo': {
            'crosses': ['5上穿10', '10上穿20'],
            'imminent_crosses': [],
            'weighted_cross_score': 3.0,
        },
        'volume_tuo': {
            'crosses': ['5上穿10'],
            'imminent_crosses': ['10即将上穿20'],
            'weighted_cross_score': 1.5,
        },
    }
    text = format_duanxian_tuo_display(info)
    lines = text.splitlines()
    assert lines[0] == '短线是银托形态 · 实托'
    assert lines[1] == '  价托: 5x10/10x20'
    assert lines[2] == '  量托: 5x10/10·20'
    assert '分' not in text


def test_format_duanxian_tuo_display_virtual_side_mixed_cross_types():
    info = {
        'price_tuo_ok': False,
        'price_tuo_imminent_ok': True,
        'volume_tuo_ok': False,
        'volume_tuo_imminent_ok': True,
        'price_tuo': {
            'crosses': ['5上穿10'],
            'imminent_crosses': ['5即将上穿10', '5上穿20'],
            'weighted_cross_score': 2.0,
        },
        'volume_tuo': {
            'crosses': ['5上穿10', '5上穿20', '10上穿20'],
            'imminent_crosses': ['10即将上穿20'],
            'weighted_cross_score': 3.0,
        },
    }
    text = format_duanxian_tuo_display(info)
    lines = text.splitlines()
    assert lines[0] == '短线是银托形态 · 虚托'
    assert '5x10' in lines[1]
    assert '5·10' in lines[1] or '5x20' in lines[1]
    assert '5x10/5x20/10x20' in lines[2] or '10·20' in lines[2]
    assert '价实' not in text
    assert '量实' not in text


def test_apply_duanxian_tuo_gate_metadata_marks_imminent_pass_tag():
    stock = {
        'duanxian_tuo_info': {
            'price_tuo_ok': False,
            'volume_tuo_ok': False,
            'price_tuo_imminent_ok': True,
            'volume_tuo_imminent_ok': False,
            'price_tuo': {'crosses': [], 'imminent_crosses': ['MA5即将上穿MA10']},
            'volume_tuo': {'crosses': [], 'imminent_crosses': []},
        },
        'volume_ma_info': {'position_build_score': 3.0},
    }
    gates = apply_duanxian_tuo_gate_metadata(stock, mark_imminent_pass=True)
    assert gates.pass_via_imminent_only is True
    assert stock.get('_duanxian_tuo_pass_tag') == '虚托'

    apply_duanxian_tuo_gate_metadata(stock, mark_imminent_pass=False)
    assert stock.get('_duanxian_tuo_pass_tag') is None


def test_evaluate_duanxian_tuo_gates_merged_secondary_gate():
    low_build = {'position_build_score': 3.0}
    imminent_only = {
        'price_tuo_imminent_ok': True,
        'volume_tuo_imminent_ok': False,
    }
    gates = evaluate_duanxian_tuo_gates(low_build, imminent_only)
    assert gates.volume_gate_ok is False
    assert gates.confirmed_ok is False
    assert gates.imminent_ok is True
    assert gates.secondary_gate_ok is True
    assert gates.pass_via_imminent_only is True


def test_build_scan_backtest_str_tuo_with_backtest_and_no_rsi():
    backtest_str, confidence = build_scan_backtest_str(
        {'buy_prob': (3, 8)},
        tuo_signal_active=True,
        duanxian_tuo_info={'price_tuo_imminent_ok': True, 'price_tuo_ok': False},
    )
    assert backtest_str == '(3/8)'
    assert confidence == (3 - 1) / 8

    backtest_str2, _ = build_scan_backtest_str(
        {'buy_prob': (5, 10)},
        tuo_signal_active=True,
        duanxian_tuo_info={'price_tuo_ok': True},
    )
    assert backtest_str2 == '(5/10)'


def test_build_scan_backtest_str_rsi_never_uses_tuo_label():
    backtest_str, _ = build_scan_backtest_str(
        {'buy_prob': (2, 5)},
        rsi_signal_active=True,
        rsi_threshold=18,
        tuo_signal_active=True,
        duanxian_tuo_info={'price_tuo_imminent_ok': True},
    )
    assert backtest_str == '(RSI18)'


def test_scan_buy_signal_ok_tuo_skips_confidence_gate():
    assert scan_buy_signal_ok(2.5, 0.0, tuo_signal_active=True) is True
    assert scan_buy_signal_ok(1.5, 0.9, tuo_signal_active=True) is False
    assert scan_buy_signal_ok(2.5, 0.0, tuo_signal_active=False) is False


def test_tuo_type_label():
    assert tuo_type_label({'price_tuo_ok': True}) == '实托'
    assert tuo_type_label({'volume_tuo_ok': True, 'price_tuo_imminent_ok': True}) == '实托'
    assert tuo_type_label({'price_tuo_imminent_ok': True}) == '虚托'
    assert tuo_type_label({'price_tuo_imminent_ok': False, 'volume_tuo_imminent_ok': False}) is None
