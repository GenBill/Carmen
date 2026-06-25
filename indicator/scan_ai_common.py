"""
扫描阶段是否启动后台 AI 的共用规则（美股 / A股 / 港股一致）。
闸门：近7日量能金叉 + 建仓评分>=9.0；与回测置信度组合见 buy_signal_ok。
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, NamedTuple, Optional, Tuple

MIN_POSITION_BUILD_SCORE = 9.0
OPEN_DROP_FILTER_PCT = 4.0
OPEN_PRICE_VERIFY_TOLERANCE_PCT = 1.0

_A_SHARE_TODAY_OPEN_CACHE: Optional[Dict[str, float]] = None
_A_SHARE_TODAY_OPEN_CACHE_DATE: Optional[date] = None


def _fetch_a_share_today_open_map_once() -> Dict[str, float]:
    """拉取 A 股今开字典（进程内按自然日缓存；当日首次触发后全日复用）。"""
    global _A_SHARE_TODAY_OPEN_CACHE, _A_SHARE_TODAY_OPEN_CACHE_DATE
    today = date.today()
    if _A_SHARE_TODAY_OPEN_CACHE is not None and _A_SHARE_TODAY_OPEN_CACHE_DATE == today:
        return _A_SHARE_TODAY_OPEN_CACHE
    result = _fetch_a_share_today_open_map_impl()
    _A_SHARE_TODAY_OPEN_CACHE = result
    _A_SHARE_TODAY_OPEN_CACHE_DATE = today
    return result


def _fetch_a_share_today_open_map_impl() -> Dict[str, float]:
    """实际拉取 A 股今开字典。"""
    try:
        import akshare as ak

        spot = ak.stock_zh_a_spot()
    except Exception:
        return {}
    if spot is None or spot.empty:
        return {}
    code_col = "代码"
    open_col = "今开"
    if code_col not in spot.columns or open_col not in spot.columns:
        return {}
    import pandas as pd

    tmp = spot[[code_col, open_col]].copy()
    tmp[code_col] = (
        tmp[code_col]
        .astype(str)
        .str.extract(r"(\d{6})", expand=False)
    )
    result: Dict[str, float] = {}
    for _, row in tmp.iterrows():
        code = str(row[code_col]).strip()
        if not code or len(code) != 6:
            continue
        try:
            v = float(row[open_col])
        except Exception:
            continue
        if not math.isfinite(v) or v <= 0:
            continue
        result[code] = v
    return result


def fetch_a_share_today_open_map() -> Dict[str, float]:
    """获取 A 股今开字典（进程内按自然日缓存）。保留对外接口。"""
    return _fetch_a_share_today_open_map_once()


class OpeningPriceContext(NamedTuple):
    """开盘价上下文。

    - A 股：akshare/东财「今开」可信，启用开盘跌幅闸门，不展示不确定性警告。
    - HK/美股：yfinance open 仅提示可能不准，不用于拦截。
    """

    open_for_filter: Optional[float]
    opening_uncertain: bool
    open_drop_filter_enabled: bool


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


def resolve_opening_price_context_for_filter(
    symbol: str,
    stock_data: Dict[str, Any],
    a_share_today_open_map: Optional[Dict[str, float]] = None,
) -> OpeningPriceContext:
    """
    A 股：优先使用传入的 akshare 今开字典；无不准确警告，启用闸门。
    未提供今开字典：当日首次触发时自动拉全市场一次，进程内当日复用，失败则不启用闸门。
    HK/美股：yfinance open 可能不准，只展示不确定性警告，不做拦截。
    """
    open_chart = _finite_positive_open(stock_data.get('open'))
    upper = (symbol or '').upper()
    if upper.endswith('.SS') or upper.endswith('.SZ'):
        code = symbol.split('.')[0]
        ak_open: Optional[float] = None
        if isinstance(a_share_today_open_map, dict):
            ak_open = a_share_today_open_map.get(code)
        else:
            # 自动从缓存获取
            cache_map = _fetch_a_share_today_open_map_once()
            ak_open = cache_map.get(code)
        ak_open = _finite_positive_open(ak_open)
        if ak_open is None:
            return OpeningPriceContext(open_chart, False, False)
        return OpeningPriceContext(ak_open, False, True)
    return OpeningPriceContext(open_chart, True, False)


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


def duanxian_tuo_gate_ok(duanxian_tuo_info: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    短线是银 价托/量托闸门。
    Returns:
        (gate_ok, summary)
    """
    info = duanxian_tuo_info or {}
    ok = bool(info.get('gate_ok') or info.get('price_tuo_ok') or info.get('volume_tuo_ok'))
    summary = str(info.get('summary') or '无')
    return ok, summary


def should_submit_scan_ai(
    score_buy: float,
    confidence: float,
    volume_ma_info: Optional[Dict[str, Any]],
    duanxian_tuo_info: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, bool, float, bool]:
    """
    Returns:
        (submit_background_ai, signal_ok, position_build_score, has_recent_golden_cross)
    """
    sig = buy_signal_ok(score_buy, confidence)
    volume_gate_ok, pbs, gcx = volume_ma_ai_gate_ok(volume_ma_info)
    tuo_gate_ok, _ = duanxian_tuo_gate_ok(duanxian_tuo_info)
    return (sig and (volume_gate_ok or tuo_gate_ok)), sig, pbs, gcx


def skip_gate_log_suffix(
    position_build_score: float,
    has_recent_golden_cross: bool,
    duanxian_tuo_info: Optional[Dict[str, Any]] = None,
) -> str:
    """与量能闸门不满足时打印的说明（三市场共用文案）。"""
    _, tuo_summary = duanxian_tuo_gate_ok(duanxian_tuo_info)
    return (
        f"position_build_score={position_build_score}，不满足「建仓评分>={MIN_POSITION_BUILD_SCORE:g}」"
        f"或近7日无量能金叉（当前金叉={has_recent_golden_cross}），且短线是银托形态={tuo_summary}，跳过后台AI分析"
    )
