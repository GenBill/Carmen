"""共享 fast scan 阶段的 CARMEN + RSI 信号评估。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from indicators import carmen_indicator, silver_indicator, vegas_indicator
from rsi_rebound_signal import evaluate_rsi_rebound_setup, is_rsi_oversold_today


@dataclass
class ScanSignalState:
    score: list[float]
    rsi_oversold_today: bool
    rsi_rebound_setup: bool
    rsi_signal_active: bool
    carmen_candidate: bool
    pre_candidate: bool
    rsi_rebound_volatility: dict
    rsi_rebound_block_reason: Optional[str]


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

    return ScanSignalState(
        score=score,
        rsi_oversold_today=rsi_oversold_today,
        rsi_rebound_setup=rsi_rebound_setup,
        rsi_signal_active=rsi_signal_active,
        carmen_candidate=carmen_candidate,
        pre_candidate=pre_candidate,
        rsi_rebound_volatility=rsi_vol_info,
        rsi_rebound_block_reason=rsi_rebound_block_reason,
    )
