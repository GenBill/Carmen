"""
扫描阶段是否启动后台 AI 的共用规则（美股 / A股 / 港股一致）。
闸门：近7日量能金叉 + 建仓评分>=6；与回测置信度组合见 buy_signal_ok。
"""
from typing import Any, Dict, Optional, Tuple


def buy_signal_ok(score_buy: float, confidence: float) -> bool:
    return score_buy >= 3.0 or (confidence >= 0.5 and score_buy >= 2.0)


def volume_ma_ai_gate_ok(volume_ma_info: Optional[Dict[str, Any]]) -> Tuple[bool, int, bool]:
    """
    统一量能闸门（与 A 股一致；港股已对齐）。
    Returns:
        (gate_ok, position_build_score, has_recent_golden_cross)
    """
    info = volume_ma_info or {}
    pbs = int(info.get('position_build_score', 0) or 0)
    gcx = bool(info.get('has_recent_golden_cross', False))
    return (gcx and pbs >= 6), pbs, gcx


def should_submit_scan_ai(
    score_buy: float,
    confidence: float,
    volume_ma_info: Optional[Dict[str, Any]],
) -> Tuple[bool, bool, int, bool]:
    """
    Returns:
        (submit_background_ai, signal_ok, position_build_score, has_recent_golden_cross)
    """
    sig = buy_signal_ok(score_buy, confidence)
    gate_ok, pbs, gcx = volume_ma_ai_gate_ok(volume_ma_info)
    return (sig and gate_ok), sig, pbs, gcx


def skip_gate_log_suffix(position_build_score: int, has_recent_golden_cross: bool) -> str:
    """与量能闸门不满足时打印的说明（三市场共用文案）。"""
    return (
        f"position_build_score={position_build_score}，不满足「建仓评分>=6」"
        f"或近7日无量能金叉（当前金叉={has_recent_golden_cross}），跳过后台AI分析"
    )
