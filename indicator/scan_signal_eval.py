"""共享 fast scan 阶段的 CARMEN + RSI 信号评估。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from indicators import carmen_indicator, silver_indicator, vegas_indicator
from rsi_rebound_signal import evaluate_rsi_rebound_setup, is_rsi_oversold_today
from scan_ai_common import apply_duanxian_tuo_gate_metadata, evaluate_duanxian_tuo_gates


@dataclass
class ScanSignalState:
    score: list[float]
    rsi_oversold_today: bool
    rsi_rebound_setup: bool
    rsi_signal_active: bool
    tuo_signal_active: bool
    carmen_candidate: bool
    pre_candidate: bool
    rsi_rebound_volatility: dict
    rsi_rebound_block_reason: Optional[str]


@dataclass
class TuoSignalState:
    tuo_signal_active: bool
    left_tuo_signal_active: bool
    confirmed_tuo_active: bool


def evaluate_tuo_signals(stock_data: dict, *, carmen_candidate: bool) -> TuoSignalState:
    """
    enrich/detail 完成后二次评估托形态。
    必须先有 carmen_candidate（score[0]>=2.0 或 score[1]>=2.0），且需完整 volume_ma_info。
    """
    inactive = TuoSignalState(False, False, False)
    if not carmen_candidate:
        stock_data['_duanxian_left_tuo_candidate'] = False
        stock_data['_duanxian_tuo_candidate'] = False
        stock_data['_duanxian_tuo_display_text'] = None
        stock_data['_duanxian_tuo_pass_tag'] = None
        stock_data['_duanxian_tuo_pass_via_imminent'] = False
        return inactive

    volume_ma_info = stock_data.get('volume_ma_info')
    duanxian_tuo_info = stock_data.get('duanxian_tuo_info')
    if not volume_ma_info or not duanxian_tuo_info:
        stock_data['_duanxian_left_tuo_candidate'] = False
        stock_data['_duanxian_tuo_candidate'] = False
        stock_data['_duanxian_tuo_display_text'] = None
        stock_data['_duanxian_tuo_pass_tag'] = None
        stock_data['_duanxian_tuo_pass_via_imminent'] = False
        return inactive

    gates = apply_duanxian_tuo_gate_metadata(stock_data, volume_ma_info)
    tuo_signal_active = bool(gates.confirmed_ok or gates.imminent_ok)
    stock_data['_duanxian_tuo_candidate'] = tuo_signal_active
    return TuoSignalState(
        tuo_signal_active=tuo_signal_active,
        left_tuo_signal_active=gates.imminent_ok,
        confirmed_tuo_active=gates.confirmed_ok,
    )


def evaluate_scan_signals(
    stock_data: dict,
    *,
    rsi_threshold: Optional[float] = None,
    volatility_ok_fn: Optional[Callable[[dict], Tuple[bool, str, dict]]] = None,
    carmen_gate: float = 2.0,
    silver_on_sell: bool = True,
) -> ScanSignalState:
    """
    一次完成 CARMEN 综合分与 RSI 超卖/反弹判定，并写入 stock_data 缓存字段。
    rsi_threshold / volatility_ok_fn 均为 None 时跳过 RSI 轨（如港股）。
    托形态在 enrich 后由 evaluate_tuo_signals 二次评估。
    """
    score_carmen = carmen_indicator(stock_data)
    score_vegas = vegas_indicator(stock_data)
    score_silver = silver_indicator(stock_data)
    score = [
        score_carmen[0] * score_vegas[0] * score_silver,
        score_carmen[1] * score_vegas[1] * (score_silver if silver_on_sell else 1.0),
    ]

    rsi_oversold_today = False
    rsi_rebound_setup = False
    rsi_signal_active = False
    rsi_vol_info: dict = {}
    rsi_rebound_block_reason: Optional[str] = None

    if rsi_threshold is not None and volatility_ok_fn is not None:
        rsi_oversold_today = is_rsi_oversold_today(stock_data, rsi_threshold)
        rsi_rebound_setup, rsi_rebound_setup_reason, rsi_vol_info = evaluate_rsi_rebound_setup(
            stock_data,
            rsi_threshold,
            volatility_ok_fn,
        )
        if rsi_vol_info:
            stock_data['_rsi_rebound_volatility'] = rsi_vol_info
        elif rsi_rebound_setup_reason and not rsi_oversold_today:
            rsi_rebound_block_reason = rsi_rebound_setup_reason
            stock_data['_rsi_rebound_block_reason'] = rsi_rebound_setup_reason
        if rsi_oversold_today and not rsi_vol_info:
            _, _, oversold_vol = volatility_ok_fn(stock_data)
            if oversold_vol:
                rsi_vol_info = oversold_vol
                stock_data['_rsi_rebound_volatility'] = oversold_vol
        rsi_signal_active = rsi_oversold_today or rsi_rebound_setup

    carmen_candidate = score[0] >= carmen_gate or score[1] >= carmen_gate
    pre_candidate = carmen_candidate or rsi_signal_active

    stock_data['_rsi_oversold_today'] = rsi_oversold_today
    stock_data['_rsi_rebound_setup'] = rsi_rebound_setup
    stock_data['_rsi_oversold_candidate'] = rsi_signal_active
    stock_data['_duanxian_tuo_candidate'] = False
    stock_data['_duanxian_left_tuo_candidate'] = False

    return ScanSignalState(
        score=score,
        rsi_oversold_today=rsi_oversold_today,
        rsi_rebound_setup=rsi_rebound_setup,
        rsi_signal_active=rsi_signal_active,
        tuo_signal_active=False,
        carmen_candidate=carmen_candidate,
        pre_candidate=pre_candidate,
        rsi_rebound_volatility=rsi_vol_info,
        rsi_rebound_block_reason=rsi_rebound_block_reason,
    )
