"""
扫描阶段是否启动后台 AI 的共用规则（美股 / A股 / 港股一致）。
副闸门：建仓评分>=8.0 OR 完整托（价托/量托确认）OR 左侧托（价托/量托预确认）。
与回测置信度组合见 buy_signal_ok。
"""
from __future__ import annotations

import math
from datetime import date
from dataclasses import dataclass
from typing import Any, Dict, Literal, NamedTuple, Optional, Tuple

MIN_POSITION_BUILD_SCORE = 8.0
IMMINENT_CROSS_WEIGHT = 0.5
TUO_ACTUAL_CROSS_THRESHOLD = 3
TUO_WEIGHTED_SCORE_THRESHOLD = 2.0
# 与 get_stock_price._calculate_duanxian_tuo_info 价托 spread 阈值一致（0.04 * 1.5 → 6%）
PRICE_TUO_IMMINENT_SPREAD_PCT_THRESHOLD = 6.0
SideTuoKind = Literal['实', '虚']
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

    if has_buy_prob:
        return f"({buy_success}/{buy_total})", confidence
    if not rsi_signal_active:
        return '(0/0)', confidence
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


def _side_actual_count(tuo_side: Dict[str, Any]) -> int:
    if 'actual_cross_count' in tuo_side:
        return int(tuo_side.get('actual_cross_count') or 0)
    return len(tuo_side.get('crosses') or [])


def _side_weighted_score(tuo_side: Dict[str, Any]) -> float:
    if 'weighted_cross_score' in tuo_side:
        return float(tuo_side.get('weighted_cross_score') or 0)
    actual = _side_actual_count(tuo_side)
    imminent = len(tuo_side.get('imminent_crosses') or [])
    return actual + imminent * IMMINENT_CROSS_WEIGHT


def _side_imminent_structure_ok(tuo_side: Dict[str, Any], *, is_volume: bool) -> bool:
    """与 _calculate_duanxian_tuo_info 中 *_tuo_imminent_ok 的结构前置一致。"""
    if not tuo_side.get('bear_recent'):
        return False
    if tuo_side.get('converged_recent'):
        return True
    if is_volume:
        return False
    spread_pct = tuo_side.get('spread_pct')
    return spread_pct is not None and float(spread_pct) <= PRICE_TUO_IMMINENT_SPREAD_PCT_THRESHOLD


def classify_side_tuo_kind(
    tuo_side: Optional[Dict[str, Any]],
    *,
    tuo_ok: bool = False,
    tuo_imminent_ok: bool = False,
    is_volume: bool = False,
) -> Optional[SideTuoKind]:
    """
    实托 / 虚托判定；优先读 _calculate_duanxian_tuo_info 写入的 *_tuo_ok 标志。
    无标志时回退：空头排列 + 收敛 + 多头排列（实托）及对应预判结构（虚托），再叠交叉阈值。
    """
    if tuo_ok:
        return '实'
    if tuo_imminent_ok:
        return '虚'

    side = tuo_side or {}
    actual = _side_actual_count(side)
    weighted = _side_weighted_score(side)
    if (
        side.get('bear_recent')
        and side.get('converged_recent')
        and side.get('current_order')
        and actual >= TUO_ACTUAL_CROSS_THRESHOLD
    ):
        return '实'
    if (
        1 <= actual < TUO_ACTUAL_CROSS_THRESHOLD
        and weighted >= TUO_WEIGHTED_SCORE_THRESHOLD
        and _side_imminent_structure_ok(side, is_volume=is_volume)
    ):
        return '虚'
    return None


def side_has_tuo(tuo_side: Optional[Dict[str, Any]]) -> bool:
    return classify_side_tuo_kind(tuo_side) is not None


def overall_tuo_header_tag(
    price_kind: Optional[SideTuoKind],
    volume_kind: Optional[SideTuoKind],
) -> str:
    """任一侧实托 → 实托；两侧皆虚托 → 虚托；否则无。"""
    kinds = [kind for kind in (price_kind, volume_kind) if kind is not None]
    if not kinds:
        return '无'
    if '实' in kinds:
        return '实托'
    return '虚托'


def evaluate_tuo_kind_labels(
    duanxian_tuo_info: Optional[Dict[str, Any]],
) -> tuple[Optional[SideTuoKind], Optional[SideTuoKind], str]:
    info = duanxian_tuo_info or {}
    price_kind = classify_side_tuo_kind(
        info.get('price_tuo'),
        tuo_ok=bool(info.get('price_tuo_ok')),
        tuo_imminent_ok=bool(info.get('price_tuo_imminent_ok')),
        is_volume=False,
    )
    volume_kind = classify_side_tuo_kind(
        info.get('volume_tuo'),
        tuo_ok=bool(info.get('volume_tuo_ok')),
        tuo_imminent_ok=bool(info.get('volume_tuo_imminent_ok')),
        is_volume=True,
    )
    return price_kind, volume_kind, overall_tuo_header_tag(price_kind, volume_kind)


def tuo_type_label(
    duanxian_tuo_info: Optional[Dict[str, Any]],
    *,
    left_tuo_candidate: bool = False,
) -> Optional[str]:
    """整体虚托/实托；与 classify_side_tuo_kind / *_tuo_ok 同一套逻辑。"""
    del left_tuo_candidate
    _, _, header = evaluate_tuo_kind_labels(duanxian_tuo_info)
    return None if header == '无' else header


def _cross_pair_key(name: str) -> tuple[int, int]:
    text = str(name).replace('即将', '').replace('MA', '')
    if '上穿' not in text:
        return (999, 999)
    short, long = text.split('上穿', 1)
    return int(short.strip()), int(long.strip())


def _fmt_tuo_cross_pair(name: str, *, imminent: bool) -> str:
    """实交叉 5x10，预判/虚交叉 5·10。"""
    text = str(name).strip().replace('即将', '').replace('MA', '')
    if '上穿' not in text:
        return text
    short, long = text.split('上穿', 1)
    sep = '·' if imminent else 'x'
    return f'{short.strip()}{sep}{long.strip()}'


def _side_cross_tokens(tuo_side: Dict[str, Any]) -> list[str]:
    """按 MA 对数字排序；同对仅保留实交叉。"""
    crosses = tuo_side.get('crosses') or []
    imminent = tuo_side.get('imminent_crosses') or []
    by_key: dict[tuple[int, int], str] = {}
    for cross in crosses:
        by_key[_cross_pair_key(cross)] = _fmt_tuo_cross_pair(cross, imminent=False)
    for cross in imminent:
        key = _cross_pair_key(cross)
        if key not in by_key:
            by_key[key] = _fmt_tuo_cross_pair(cross, imminent=True)
    return [by_key[key] for key in sorted(by_key.keys())]


def _side_tuo_line(tuo_side: Dict[str, Any], *, label: str) -> Optional[str]:
    tokens = _side_cross_tokens(tuo_side)
    if not tokens:
        return None
    return f'{label}: {"/".join(tokens)}'


def _duanxian_tuo_side_lines(
    duanxian_tuo_info: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str], Optional[SideTuoKind], Optional[SideTuoKind], str]:
    info = duanxian_tuo_info or {}
    price_kind, volume_kind, header = evaluate_tuo_kind_labels(info)
    price_line = _side_tuo_line(info.get('price_tuo') or {}, label='价托') if price_kind else None
    volume_line = _side_tuo_line(info.get('volume_tuo') or {}, label='量托') if volume_kind else None
    return price_line, volume_line, price_kind, volume_kind, header


def format_duanxian_tuo_display(
    duanxian_tuo_info: Optional[Dict[str, Any]],
    *,
    include_header: bool = True,
) -> str:
    """价/量两行；首行 tag 由 *_tuo_ok / 结构+交叉判定，与闸门一致。"""
    info = duanxian_tuo_info or {}
    if not info:
        return '无'

    price_line, volume_line, _, _, header = _duanxian_tuo_side_lines(info)
    if header == '无':
        return '无'

    lines: list[str] = []
    if include_header:
        lines.append(f'短线是银托形态 · {header}')
    if price_line:
        lines.append(f'  {price_line}')
    if volume_line:
        lines.append(f'  {volume_line}')
    return '\n'.join(lines)


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
    price_kind, volume_kind, _ = evaluate_tuo_kind_labels(info)
    confirmed_ok = price_kind == '实' or volume_kind == '实'
    imminent_ok = price_kind == '虚' or volume_kind == '虚'
    tuo_gate_ok = confirmed_ok or imminent_ok
    secondary_gate_ok = bool(volume_gate_ok or tuo_gate_ok)
    pass_via_imminent_only = bool(imminent_ok and not confirmed_ok and not volume_gate_ok)
    confirmed_parts = []
    if price_kind == '实':
        confirmed_parts.append('价托确认')
    if volume_kind == '实':
        confirmed_parts.append('量托确认')
    confirmed_summary = ' / '.join(confirmed_parts) if confirmed_parts else '无'
    imminent_parts = []
    if price_kind == '虚':
        imminent_parts.append('价托预确认')
    if volume_kind == '虚':
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
        _, _, header_tag = evaluate_tuo_kind_labels((stock_data or {}).get('duanxian_tuo_info'))
        stock_data['_duanxian_tuo_display_text'] = gates.display_text
        stock_data['_duanxian_tuo_pass_via_imminent'] = bool(
            mark_imminent_pass and gates.pass_via_imminent_only
        )
        stock_data['_duanxian_tuo_pass_tag'] = (
            header_tag
            if mark_imminent_pass and header_tag in ('实托', '虚托')
            else None
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
