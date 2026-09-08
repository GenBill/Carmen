"""Wyckoff market-structure heuristics for Carmen.

The Wyckoff method is interpretive. This module keeps the rules explicit and
bounded so output can be audited, tested, and calibrated with Carmen history.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


MIN_BARS = 90
RANGE_WINDOW = 60
TREND_LOOKBACK = 120
EVENT_WINDOW = 8


@dataclass(frozen=True)
class WyckoffResult:
    phase: str
    bias: str
    confidence: float
    range_position: Optional[float]
    support: Optional[float]
    resistance: Optional[float]
    volume_ratio: Optional[float]
    atr_pct: Optional[float]
    signals: List[str]
    note: str

    def as_dict(self) -> Dict:
        return {
            "phase": self.phase,
            "bias": self.bias,
            "confidence": self.confidence,
            "range_position": self.range_position,
            "support": self.support,
            "resistance": self.resistance,
            "volume_ratio": self.volume_ratio,
            "atr_pct": self.atr_pct,
            "signals": list(self.signals),
            "note": self.note,
        }


def _safe_float(value) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_hist(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or getattr(hist, "empty", True):
        return pd.DataFrame()
    if isinstance(hist.columns, pd.MultiIndex):
        hist = hist.copy()
        hist.columns = hist.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in hist.columns]
    if missing:
        return pd.DataFrame()
    out = hist[required].copy()
    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["High", "Low", "Close"])
    out = out[out["Close"] > 0]
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    return out


def _atr_pct(hist: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = hist["Close"].shift(1)
    tr = pd.concat(
        [
            hist["High"] - hist["Low"],
            (hist["High"] - prev_close).abs(),
            (hist["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean() / hist["Close"].replace(0, np.nan)


def _pct_change(start: float, end: float) -> float:
    if start <= 0:
        return 0.0
    return end / start - 1.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def analyze_wyckoff(stock_data: Dict) -> Dict:
    """Return a non-trading Wyckoff phase reference for a stock_data payload."""
    hist = _normalize_hist((stock_data or {}).get("hist"))
    if len(hist) < MIN_BARS:
        return WyckoffResult(
            phase="Unknown",
            bias="Neutral",
            confidence=0.0,
            range_position=None,
            support=None,
            resistance=None,
            volume_ratio=None,
            atr_pct=None,
            signals=[],
            note=f"历史K线不足，至少需要{MIN_BARS}根",
        ).as_dict()

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]
    last_close = float(close.iloc[-1])

    range_hist = hist.tail(RANGE_WINDOW)
    support = float(range_hist["Low"].min())
    resistance = float(range_hist["High"].max())
    width = max(resistance - support, last_close * 0.01)
    range_position = _clamp((last_close - support) / width, 0.0, 1.0)

    atr_series = _atr_pct(hist)
    atr_now = _safe_float(atr_series.iloc[-1])
    atr_median = _safe_float(atr_series.tail(TREND_LOOKBACK).median())
    atr_compressed = bool(atr_now is not None and atr_median and atr_now <= atr_median * 0.9)

    vol_ma = volume.rolling(20, min_periods=10).mean()
    vol_base = _safe_float(vol_ma.iloc[-2] if len(vol_ma) > 1 else vol_ma.iloc[-1]) or 0.0
    volume_ratio = float(volume.iloc[-1] / vol_base) if vol_base > 0 else None

    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    ma20_now = _safe_float(ma20.iloc[-1])
    ma60_now = _safe_float(ma60.iloc[-1])
    ma20_prev = _safe_float(ma20.iloc[-21]) if len(ma20) > 21 else None
    ma60_prev = _safe_float(ma60.iloc[-21]) if len(ma60) > 21 else None
    ma_bull = bool(ma20_now and ma60_now and ma20_now > ma60_now and last_close > ma20_now)
    ma_bear = bool(ma20_now and ma60_now and ma20_now < ma60_now and last_close < ma20_now)
    ma20_slope = _pct_change(ma20_prev, ma20_now) if ma20_prev and ma20_now else 0.0
    ma60_slope = _pct_change(ma60_prev, ma60_now) if ma60_prev and ma60_now else 0.0

    trend_ref = close.tail(TREND_LOOKBACK)
    prior_start = float(trend_ref.iloc[0])
    pre_range_idx = max(0, len(close) - RANGE_WINDOW - 1)
    pre_range_close = float(close.iloc[pre_range_idx])
    prior_change = _pct_change(prior_start, pre_range_close)
    recent_change = _pct_change(float(close.iloc[-21]), last_close) if len(close) > 21 else 0.0

    recent = hist.tail(EVENT_WINDOW)
    prev_range = hist.iloc[-(RANGE_WINDOW + EVENT_WINDOW):-EVENT_WINDOW]
    if len(prev_range) >= 20:
        prev_support = float(prev_range["Low"].min())
        prev_resistance = float(prev_range["High"].max())
    else:
        prev_support = support
        prev_resistance = resistance

    tolerance = max((atr_now or 0.02) * 0.6, 0.01)
    spring = bool(
        (recent["Low"] < prev_support * (1 - tolerance)).any()
        and last_close > prev_support
        and range_position < 0.45
    )
    upthrust = bool(
        (recent["High"] > prev_resistance * (1 + tolerance)).any()
        and last_close < prev_resistance
        and range_position > 0.55
    )
    breakout = bool(last_close > prev_resistance * (1 + tolerance * 0.5))
    breakdown = bool(last_close < prev_support * (1 - tolerance * 0.5))
    high_volume = bool(volume_ratio is not None and volume_ratio >= 1.25)

    in_range = bool(not breakout and not breakdown and 0.08 <= range_position <= 0.92)
    range_width_pct = width / last_close
    range_quality = bool(in_range and range_width_pct <= 0.45 and (atr_compressed or range_width_pct <= 0.30))

    signals: List[str] = []
    if prior_change <= -0.18:
        signals.append("前置下跌")
    if prior_change >= 0.25:
        signals.append("前置上涨")
    if atr_compressed:
        signals.append("波动收缩")
    if high_volume:
        signals.append("放量")
    if spring:
        signals.append("Spring")
    if upthrust:
        signals.append("UTAD")
    if breakout:
        signals.append("突破区间")
    if breakdown:
        signals.append("跌破区间")

    phase = "Unknown"
    bias = "Neutral"
    confidence = 0.35
    note = "结构不清晰，仅供参考"

    if spring:
        phase, bias, confidence = "C", "Accumulation watch", 0.62
        note = "疑似 Spring：跌破区间后收回，等待测试/SOS"
    elif upthrust:
        phase, bias, confidence = "C", "Distribution risk", 0.62
        note = "疑似 UTAD：突破区间后回落，警惕派发"
    elif breakout and high_volume and (prior_change <= -0.08 or range_quality):
        phase, bias, confidence = "D", "Bullish confirmation", 0.68
        note = "疑似 SOS：放量突破建仓区间"
    elif breakdown and high_volume and (prior_change >= 0.12 or range_quality):
        phase, bias, confidence = "D", "Bearish confirmation", 0.68
        note = "疑似 SOW：放量跌破派发区间"
    elif ma_bull and recent_change >= 0.08 and ma20_slope > 0:
        phase, bias, confidence = "E", "Markup", 0.65
        note = "趋势展开：价格位于多头均线结构上方"
    elif ma_bear and recent_change <= -0.08 and ma20_slope < 0:
        phase, bias, confidence = "E", "Markdown", 0.65
        note = "趋势展开：价格位于空头均线结构下方"
    elif range_quality and prior_change <= -0.12:
        phase, bias, confidence = "B", "Accumulation", 0.58
        note = "下跌后横盘且波动收缩，偏建仓区间"
    elif range_quality and prior_change >= 0.18:
        phase, bias, confidence = "B", "Distribution", 0.58
        note = "上涨后横盘且波动收缩，偏派发区间"
    elif prior_change <= -0.18 and recent_change >= 0.03 and range_position < 0.65:
        phase, bias, confidence = "A", "Stopping action", 0.5
        note = "下跌动能初步停止，仍需区间确认"
    elif prior_change >= 0.25 and recent_change <= -0.03 and range_position > 0.35:
        phase, bias, confidence = "A", "Potential distribution", 0.5
        note = "上涨动能初步停止，观察是否进入派发"

    if phase in {"B", "D"} and high_volume:
        confidence += 0.08
    if phase != "Unknown" and atr_compressed:
        confidence += 0.05
    if phase != "Unknown" and (abs(ma20_slope) + abs(ma60_slope)) > 0.04:
        confidence += 0.03

    return WyckoffResult(
        phase=phase,
        bias=bias,
        confidence=round(_clamp(confidence, 0.0, 0.9), 2),
        range_position=round(range_position, 2),
        support=round(support, 2),
        resistance=round(resistance, 2),
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
        atr_pct=round(float(atr_now) * 100, 2) if atr_now is not None else None,
        signals=signals[:6],
        note=note,
    ).as_dict()


def format_wyckoff_report(symbol: str, stock_data: Dict, telegram_html: bool = True) -> str:
    info = analyze_wyckoff(stock_data)
    display_symbol = symbol.split(".")[0] if symbol.upper().endswith((".SZ", ".SS", ".HK")) else symbol
    if telegram_html:
        display_symbol = f"<code>{display_symbol}</code>"

    def esc(value) -> str:
        import html

        text = str(value)
        return html.escape(text) if telegram_html else text

    range_pos = info.get("range_position")
    range_pos_text = f"{float(range_pos) * 100:.0f}%" if isinstance(range_pos, (int, float)) else "N/A"
    volume_ratio = info.get("volume_ratio")
    volume_text = f"{float(volume_ratio):.2f}x" if isinstance(volume_ratio, (int, float)) else "N/A"
    atr = info.get("atr_pct")
    atr_text = f"{float(atr):.2f}%" if isinstance(atr, (int, float)) else "N/A"
    signals = info.get("signals") or []
    signals_text = " / ".join(str(x) for x in signals) if signals else "无"

    return "\n".join(
        [
            "🧭 Wyckoff 阶段参考",
            f"股票: {display_symbol}",
            f"日期: {esc(stock_data.get('date') or 'N/A')}",
            f"阶段: {esc(info.get('phase') or 'Unknown')} | 倾向: {esc(info.get('bias') or 'Neutral')} | 置信度: {float(info.get('confidence') or 0):.2f}",
            f"区间位置: {range_pos_text} | 支撑: {info.get('support') or 'N/A'} | 压力: {info.get('resistance') or 'N/A'}",
            f"量能: {volume_text} | ATR: {atr_text}",
            f"结构信号: {esc(signals_text)}",
            f"说明: {esc(info.get('note') or '')}",
        ]
    )
