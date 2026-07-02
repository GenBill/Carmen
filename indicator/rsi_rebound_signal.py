"""RSI 超卖 / 反弹拐头双轨信号（A 股、美股共用逻辑）。"""
from __future__ import annotations

import math
from typing import Callable, Optional, Tuple


def finite_rsi(raw) -> Optional[float]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        rsi = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rsi):
        return None
    return rsi


def _finite_float(raw) -> Optional[float]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def is_rsi_oversold_today(stock_data: dict, threshold: float) -> bool:
    """当日 RSI 严格小于阈值。"""
    rsi = finite_rsi((stock_data or {}).get('rsi'))
    return rsi is not None and rsi < float(threshold)


def is_rsi_oversold_prev(stock_data: dict, threshold: float) -> bool:
    """前一日 RSI 严格小于阈值。"""
    rsi_prev = finite_rsi((stock_data or {}).get('rsi_prev'))
    return rsi_prev is not None and rsi_prev < float(threshold)


def rsi_turning_ok(stock_data: dict) -> Tuple[bool, str]:
    """止跌拐头：RSI 上行且收盘不续跌。"""
    rsi = finite_rsi((stock_data or {}).get('rsi'))
    rsi_prev = finite_rsi((stock_data or {}).get('rsi_prev'))
    if rsi is None or rsi_prev is None:
        return False, 'RSI前值无效，无法确认拐头'
    if rsi <= rsi_prev:
        return False, f'RSI仍在走弱({rsi_prev:.2f}->{rsi:.2f})'

    hist = (stock_data or {}).get('hist')
    if hist is not None and not getattr(hist, 'empty', True) and 'Close' in hist and len(hist) >= 2:
        close = hist['Close'].astype(float)
        latest = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        if math.isfinite(latest) and math.isfinite(prev) and latest < prev:
            return False, f'价格仍创新低/继续下跌({prev:.2f}->{latest:.2f})'

    return True, 'RSI与价格已止跌拐头'


def evaluate_macd_turn_positive(stock_data: dict) -> Tuple[bool, str]:
    """
    MACD 即将转正：与 carmen 评分中 macd_state_strict[0] 一致。
    """
    from indicators import _macd_dif_buy_fade_extrap_reversal, is_macd_buy_imminent

    if is_macd_buy_imminent(stock_data):
        if _macd_dif_buy_fade_extrap_reversal((stock_data or {}).get('macd_dif_tail') or []):
            return True, 'MACD DIF连跌反包，即将转正'
        dif = _finite_float((stock_data or {}).get('dif'))
        dea = _finite_float((stock_data or {}).get('dea'))
        slope = _finite_float((stock_data or {}).get('dif_dea_slope'))
        if dif is not None and dea is not None and slope is not None:
            if dif < dea:
                return True, f'MACD即将金叉(DIF={dif:.2f} < DEA={dea:.2f}, 斜率={slope:.2f})'
            return True, f'MACD刚金叉(DIF={dif:.2f} ≥ DEA={dea:.2f}, 斜率={slope:.2f})'
        return True, 'MACD即将转正'

    dif = _finite_float((stock_data or {}).get('dif'))
    dea = _finite_float((stock_data or {}).get('dea'))
    slope = _finite_float((stock_data or {}).get('dif_dea_slope'))
    if dif is None or dea is None or slope is None:
        return False, 'MACD数据无效，无法确认即将转正'
    if slope <= 0:
        return False, f'MACD斜率非正(DIF-DEA斜率={slope:.2f})，未即将转正'
    return False, f'MACD未即将转正(DIF={dif:.2f}, DEA={dea:.2f}, 斜率={slope:.2f})'


def evaluate_rsi_rebound_setup(
    stock_data: dict,
    threshold: float,
    volatility_ok_fn: Callable[[dict], Tuple[bool, str, dict]],
) -> Tuple[bool, str, dict]:
    """
    前一日超卖 + 当日拐头 + 6 个月波动弹性合格。
    不要求当日 RSI 仍低于阈值。
    """
    if not is_rsi_oversold_prev(stock_data, threshold):
        return False, '前一日RSI未超卖', {}

    turn_ok, turn_reason = rsi_turning_ok(stock_data)
    if not turn_ok:
        return False, turn_reason, {}

    vol_ok, vol_reason, vol_info = volatility_ok_fn(stock_data)
    if not vol_ok:
        return False, vol_reason, vol_info

    return True, f'{turn_reason}；{vol_reason}', vol_info


def select_top_rsi_oversold_candidates(candidates, limit: int = 3):
    """超卖轨：RSI 越低越优先。"""
    if not candidates or limit <= 0:
        return []
    return sorted(
        candidates,
        key=lambda x: float(x.get('rsi') if x.get('rsi') is not None else 999.0),
    )[:limit]
