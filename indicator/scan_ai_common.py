"""
扫描阶段是否启动后台 AI 的共用规则（美股 / A股 / 港股一致）。
副闸门：建仓评分>=8.0 OR 完整托（价托/量托确认）OR 左侧托（价托/量托预确认）。
与回测置信度组合见 buy_signal_ok。
"""
from __future__ import annotations

import math
from datetime import date
from dataclasses import dataclass
from typing import Any, Dict, NamedTuple, Optional, Tuple

MIN_POSITION_BUILD_SCORE = 8.0
IMMINENT_CROSS_WEIGHT = 0.5
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


def tuo_type_label(
    duanxian_tuo_info: Optional[Dict[str, Any]],
    *,
    left_tuo_candidate: bool = False,
) -> Optional[str]:
    """虚托 = 仅预确认；实托 = 价托/量托已确认。"""
    info = duanxian_tuo_info or {}
    if info.get('price_tuo_ok') or info.get('volume_tuo_ok'):
        return '实托'
    if left_tuo_candidate or info.get('price_tuo_imminent_ok') or info.get('volume_tuo_imminent_ok'):
        return '虚托'
    return None


def build_scan_backtest_str(
    backtest_result: Optional[Dict[str, Any]],
    *,
    rsi_signal_active: bool = False,
    rsi_threshold: Optional[float] = None,
    tuo_signal_active: bool = False,
    duanxian_tuo_info: Optional[Dict[str, Any]] = None,
    left_tuo_candidate: bool = False,
) -> Tuple[str, float]:
    """
    构建扫描阶段 backtest_str 与 confidence。
    托形态（非 RSI）：始终跑回测并展示 (成功/总数)；回测 confidence 不参与托链路准入。
    RSI 不走虚托/实托后缀。
    """
    confidence = 0.0
    if rsi_signal_active and rsi_threshold is not None:
        return f"(RSI{rsi_threshold:g})", confidence

    buy_success, buy_total = 0, 0
    has_buy_prob = bool(backtest_result and 'buy_prob' in backtest_result)
    if has_buy_prob:
        buy_success, buy_total = backtest_result['buy_prob']
        if buy_total > 2:
            confidence = (buy_success - 1) / buy_total

    tuo_label: Optional[str] = None
    if tuo_signal_active and not rsi_signal_active:
        tuo_label = tuo_type_label(
            duanxian_tuo_info,
            left_tuo_candidate=left_tuo_candidate,
        )

    if tuo_label:
        if has_buy_prob:
            return f"({buy_success}/{buy_total} {tuo_label})", confidence
        return f"({tuo_label})", confidence

    if has_buy_prob:
        return f"({buy_success}/{buy_total})", confidence
    return '', confidence


def scan_buy_signal_ok(
    score_buy: float,
    confidence: float,
    *,
    tuo_signal_active: bool = False,
) -> bool:
    """托形态（非 RSI）：CARMEN 初筛 score>=2 即可，回测 confidence 不作准入阈值。"""
    if tuo_signal_active and score_buy >= 2.0:
        return True
    return buy_signal_ok(score_buy, confidence)


def scan_post_backtest_pipeline_active(
    backtest_result: Optional[Dict[str, Any]],
    *,
    rsi_signal_active: bool = False,
    tuo_signal_active: bool = False,
    carmen_candidate: bool = False,
) -> bool:
    if rsi_signal_active:
        return True
    if backtest_result is not None:
        return True
    if tuo_signal_active and carmen_candidate:
        return True
    return False


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
    建仓强度闸门。
    Returns:
        (gate_ok, position_build_score, has_recent_golden_cross)
        has_recent_golden_cross 仅作审计/日志，不参与放行。
    """
    info = volume_ma_info or {}
    pbs = float(info.get('position_build_score', 0) or 0)
    gcx = bool(info.get('has_recent_golden_cross', False))
    return (pbs >= MIN_POSITION_BUILD_SCORE), pbs, gcx


def _fmt_tuo_cross_labels(names) -> str:
    return '/'.join(
        str(x).replace('上穿', 'x').replace('即将', '~')
        for x in (names or [])
    )


def _side_tuo_display(
    tuo_side: Dict[str, Any],
    *,
    confirmed_ok: bool,
    imminent_ok: bool,
    label: str,
) -> Optional[str]:
    crosses = tuo_side.get('crosses') or []
    imminent = tuo_side.get('imminent_crosses') or []
    weighted = tuo_side.get('weighted_cross_score')
    parts: list[str] = []
    if confirmed_ok:
        if crosses:
            parts.append(f'实✓({_fmt_tuo_cross_labels(crosses)})')
        else:
            parts.append('实✓')
    elif crosses:
        parts.append(f'实({_fmt_tuo_cross_labels(crosses)})')
    if imminent_ok:
        imm_labels = list(imminent)
        if not confirmed_ok and crosses:
            imm_labels = list(crosses) + list(imminent)
        if imm_labels:
            parts.append(f'预({_fmt_tuo_cross_labels(imm_labels)})')
    elif imminent:
        parts.append(f'预({_fmt_tuo_cross_labels(imminent)})')
    if weighted is not None and parts:
        parts.append(f'分{weighted:g}')
    if not parts:
        return None
    return f'{label}[{" ".join(parts)}]'


def format_duanxian_tuo_display(duanxian_tuo_info: Optional[Dict[str, Any]]) -> str:
    """价/量实托与预判托合并展示（单次计算结果，供消息/footer 共用）。"""
    info = duanxian_tuo_info or {}
    if not info:
        return '无'
    price_seg = _side_tuo_display(
        info.get('price_tuo') or {},
        confirmed_ok=bool(info.get('price_tuo_ok')),
        imminent_ok=bool(info.get('price_tuo_imminent_ok')),
        label='价托',
    )
    volume_seg = _side_tuo_display(
        info.get('volume_tuo') or {},
        confirmed_ok=bool(info.get('volume_tuo_ok')),
        imminent_ok=bool(info.get('volume_tuo_imminent_ok')),
        label='量托',
    )
    segments = [seg for seg in (price_seg, volume_seg) if seg]
    if segments:
        return '；'.join(segments)
    return str(info.get('summary') or '无')


@dataclass(frozen=True)
class DuanxianTuoGateResult:
    confirmed_ok: bool
    imminent_ok: bool
    volume_gate_ok: bool
    secondary_gate_ok: bool
    pass_via_imminent_only: bool
    confirmed_summary: str
    imminent_summary: str
    display_text: str


def evaluate_duanxian_tuo_gates(
    volume_ma_info: Optional[Dict[str, Any]],
    duanxian_tuo_info: Optional[Dict[str, Any]],
) -> DuanxianTuoGateResult:
    """
    合并评估：建仓强度 / 完整托 / 左侧托（预判），并生成统一展示文案。
    """
    info = duanxian_tuo_info or {}
    volume_gate_ok, _, _ = volume_ma_ai_gate_ok(volume_ma_info)
    confirmed_ok = bool(info.get('gate_ok') or info.get('price_tuo_ok') or info.get('volume_tuo_ok'))
    price_imminent = bool(info.get('price_tuo_imminent_ok'))
    volume_imminent = bool(info.get('volume_tuo_imminent_ok'))
    imminent_ok = price_imminent or volume_imminent
    secondary_gate_ok = bool(volume_gate_ok or confirmed_ok or imminent_ok)
    pass_via_imminent_only = bool(imminent_ok and not confirmed_ok and not volume_gate_ok)
    confirmed_summary = str(info.get('summary') or '无') if confirmed_ok else '无'
    imminent_parts = []
    if price_imminent:
        imminent_parts.append('价托预确认')
    if volume_imminent:
        imminent_parts.append('量托预确认')
    imminent_summary = ' / '.join(imminent_parts) if imminent_parts else '无'
    return DuanxianTuoGateResult(
        confirmed_ok=confirmed_ok,
        imminent_ok=imminent_ok,
        volume_gate_ok=volume_gate_ok,
        secondary_gate_ok=secondary_gate_ok,
        pass_via_imminent_only=pass_via_imminent_only,
        confirmed_summary=confirmed_summary,
        imminent_summary=imminent_summary,
        display_text=format_duanxian_tuo_display(info),
    )


def apply_duanxian_tuo_gate_metadata(
    stock_data: Optional[Dict[str, Any]],
    volume_ma_info: Optional[Dict[str, Any]] = None,
    *,
    mark_imminent_pass: bool = False,
) -> DuanxianTuoGateResult:
    """写入 stock_data 托形态展示/预判 tag 缓存字段。"""
    gates = evaluate_duanxian_tuo_gates(
        volume_ma_info if volume_ma_info is not None else (stock_data or {}).get('volume_ma_info'),
        (stock_data or {}).get('duanxian_tuo_info'),
    )
    if stock_data is not None:
        stock_data['_duanxian_tuo_display_text'] = gates.display_text
        stock_data['_duanxian_tuo_pass_via_imminent'] = bool(
            mark_imminent_pass and gates.pass_via_imminent_only
        )
        stock_data['_duanxian_tuo_pass_tag'] = (
            '虚托' if mark_imminent_pass and gates.pass_via_imminent_only else None
        )
        stock_data['_duanxian_left_tuo_candidate'] = gates.imminent_ok
    return gates


def duanxian_tuo_gate_ok(duanxian_tuo_info: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """完整托（价托/量托确认）。"""
    gates = evaluate_duanxian_tuo_gates(None, duanxian_tuo_info)
    return gates.confirmed_ok, gates.confirmed_summary if gates.confirmed_ok else '无'


def duanxian_left_tuo_gate_ok(
    volume_ma_info: Optional[Dict[str, Any]],
    duanxian_tuo_info: Optional[Dict[str, Any]],
) -> Tuple[bool, str]:
    """左侧托：价托预确认 OR 量托预确认。"""
    gates = evaluate_duanxian_tuo_gates(volume_ma_info, duanxian_tuo_info)
    return gates.imminent_ok, gates.imminent_summary if gates.imminent_ok else '无'


def should_submit_scan_ai(
    score_buy: float,
    confidence: float,
    volume_ma_info: Optional[Dict[str, Any]],
    duanxian_tuo_info: Optional[Dict[str, Any]] = None,
    *,
    tuo_signal_active: bool = False,
) -> Tuple[bool, bool, float, bool]:
    """
    Returns:
        (submit_background_ai, signal_ok, position_build_score, has_recent_golden_cross)
    """
    sig = scan_buy_signal_ok(
        score_buy,
        confidence,
        tuo_signal_active=tuo_signal_active,
    )
    volume_gate_ok, pbs, gcx = volume_ma_ai_gate_ok(volume_ma_info)
    tuo_gates = evaluate_duanxian_tuo_gates(volume_ma_info, duanxian_tuo_info)
    return (sig and tuo_gates.secondary_gate_ok), sig, pbs, gcx


def skip_gate_log_suffix(
    position_build_score: float,
    has_recent_golden_cross: bool,
    duanxian_tuo_info: Optional[Dict[str, Any]] = None,
) -> str:
    """与量能闸门不满足时打印的说明（三市场共用文案）。"""
    tuo_gates = evaluate_duanxian_tuo_gates(None, duanxian_tuo_info)
    return (
        f"position_build_score={position_build_score}，不满足「建仓评分>={MIN_POSITION_BUILD_SCORE:g}」"
        f"、完整托、或左侧托预确认（{tuo_gates.display_text}），跳过后台AI分析"
    )
