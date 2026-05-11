"""
扫描阶段是否启动后台 AI 的共用规则（美股 / A股 / 港股一致）。
闸门：近7日量能金叉 + 建仓评分>=7.0；与回测置信度组合见 buy_signal_ok。
"""
from __future__ import annotations

import math
from typing import Any, Dict, NamedTuple, Optional, Tuple

MIN_POSITION_BUILD_SCORE = 7.0
OPEN_DROP_FILTER_PCT = 2.0
OPEN_PRICE_VERIFY_TOLERANCE_PCT = 1.0


class OpeningPriceContext(NamedTuple):
    """开盘价用于跌幅闸门时的权威值与 Telegram 是否展示不确定性警告。"""

    open_for_filter: Optional[float]
    opening_uncertain: bool


def buy_signal_ok(score_buy: float, confidence: float) -> bool:
    return score_buy >= 3.0 or (confidence >= 0.5 and score_buy >= 2.0)


def _finite_positive_open(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def resolve_opening_price_context_for_filter(symbol: str, stock_data: Dict[str, Any]) -> OpeningPriceContext:
    """
    A 股：用东财/akshare「今开」与 K 线 open 比对，相对误差 ≤1% 视为校验通过，闸门以 akshare 今开为准。
    未取得今开或比对失败：opening_uncertain=True，闸门仍优先用可达的权威 open（A 股优先 ak 今开）。
    HK/美股：无二次校验渠道，一律 opening_uncertain=True，闸门用行情 open。
    """
    open_chart = _finite_positive_open(stock_data.get('open'))
    upper = (symbol or '').upper()
    if upper.endswith('.SS') or upper.endswith('.SZ'):
        code = symbol.split('.')[0]
        ak_open: Optional[float] = None
        try:
            from agent.deepseek import fetch_a_share_today_open_from_ak

            ak_open = fetch_a_share_today_open_from_ak(code)
        except Exception:
            ak_open = None
        ak_open = _finite_positive_open(ak_open)
        if ak_open is None:
            return OpeningPriceContext(open_chart, True)
        if open_chart is None:
            return OpeningPriceContext(ak_open, True)
        rel_pct = abs(ak_open - open_chart) / ak_open * 100.0
        if rel_pct <= OPEN_PRICE_VERIFY_TOLERANCE_PCT:
            return OpeningPriceContext(ak_open, False)
        return OpeningPriceContext(ak_open, True)
    return OpeningPriceContext(open_chart, True)


def is_buy_blocked_by_open_gap(
    price: Optional[float],
    open_price: Optional[float],
    pct: float = OPEN_DROP_FILTER_PCT,
) -> bool:
    """现价相对开盘价跌幅 >= pct% 时返回 True（不进买入链路）；无效 open 时不拦截。"""
    if open_price is None or float(open_price) <= 0:
        return False
    if price is None:
        return False
    return float(price) <= float(open_price) * (1 - pct / 100.0)


def volume_ma_ai_gate_ok(volume_ma_info: Optional[Dict[str, Any]]) -> Tuple[bool, float, bool]:
    """
    统一量能闸门（与 A 股一致；港股已对齐）。
    Returns:
        (gate_ok, position_build_score, has_recent_golden_cross)
    """
    info = volume_ma_info or {}
    pbs = float(info.get('position_build_score', 0) or 0)
    gcx = bool(info.get('has_recent_golden_cross', False))
    return (gcx and pbs >= MIN_POSITION_BUILD_SCORE), pbs, gcx


def should_submit_scan_ai(
    score_buy: float,
    confidence: float,
    volume_ma_info: Optional[Dict[str, Any]],
) -> Tuple[bool, bool, float, bool]:
    """
    Returns:
        (submit_background_ai, signal_ok, position_build_score, has_recent_golden_cross)
    """
    sig = buy_signal_ok(score_buy, confidence)
    gate_ok, pbs, gcx = volume_ma_ai_gate_ok(volume_ma_info)
    return (sig and gate_ok), sig, pbs, gcx


def skip_gate_log_suffix(position_build_score: float, has_recent_golden_cross: bool) -> str:
    """与量能闸门不满足时打印的说明（三市场共用文案）。"""
    return (
        f"position_build_score={position_build_score}，不满足「建仓评分>={MIN_POSITION_BUILD_SCORE:g}」"
        f"或近7日无量能金叉（当前金叉={has_recent_golden_cross}），跳过后台AI分析"
    )
