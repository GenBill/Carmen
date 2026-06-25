"""
A-share stock-character veto filter.

Runs after Carmen standard buy signal (A) and before position-build / tuo gates
(B/C).  The filter is deliberately conservative: missing data does not veto,
but clear low-liquidity, choppy, or pump-and-fade behavior does.
"""
from __future__ import annotations

from typing import Any, Dict, List

import math
import pandas as pd


MIN_AVG_AMOUNT_20_A_HK = 80_000_000.0
MIN_AVG_AMOUNT_60_A_HK = 50_000_000.0
MIN_AVG_AMOUNT_20_US = 10_000_000.0
MIN_AVG_AMOUNT_60_US = 5_000_000.0
ONE_YEAR_LOOKBACK = 240


def _market_amount_thresholds(symbol: str):
    upper = (symbol or "").upper()
    if upper.endswith(".SZ") or upper.endswith(".SS"):
        return MIN_AVG_AMOUNT_20_A_HK, MIN_AVG_AMOUNT_60_A_HK, "CNY"
    if upper.endswith(".HK"):
        return MIN_AVG_AMOUNT_20_A_HK, MIN_AVG_AMOUNT_60_A_HK, "HKD"
    return MIN_AVG_AMOUNT_20_US, MIN_AVG_AMOUNT_60_US, "USD"


def _cross_count(a: pd.Series, b: pd.Series, window: int) -> int:
    pair = pd.DataFrame({"a": a, "b": b}).dropna().tail(window + 1)
    if len(pair) < 2:
        return 0
    diff = pair["a"] - pair["b"]
    sign = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    sign = sign.mask(sign == 0, other=float("nan")).ffill().bfill().fillna(0).astype("int8")
    return int((sign != sign.shift(1)).sum() - 1)


def _pct_change(a: float, b: float) -> float:
    if not b or not math.isfinite(float(b)):
        return 0.0
    return float(a) / float(b) - 1.0


def evaluate_stock_character(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return:
        {
          passed: bool,
          reasons: [str],
          metrics: {...},
        }
    """
    hist = stock_data.get("hist") if isinstance(stock_data, dict) else None
    if hist is None or getattr(hist, "empty", True) or len(hist) < 80:
        return {
            "passed": True,
            "reasons": [],
            "status": "数据缺失",
            "score": None,
            "warning": "股性数据不足，未执行一票否决",
            "metrics": {"data_points": 0 if hist is None else len(hist), "data_insufficient": True},
        }

    data = hist.copy()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(set(data.columns)):
        return {
            "passed": True,
            "reasons": [],
            "status": "数据缺失",
            "score": None,
            "warning": "股性字段缺失，未执行一票否决",
            "metrics": {"missing_columns": sorted(required - set(data.columns))},
        }

    for col in required:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if len(data) < 80:
        return {
            "passed": True,
            "reasons": [],
            "status": "数据缺失",
            "score": None,
            "warning": "股性有效样本不足，未执行一票否决",
            "metrics": {"data_points": len(data), "data_insufficient": True},
        }

    close = data["Close"]
    open_ = data["Open"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"].clip(lower=0)
    amount = close * volume
    pct = close.pct_change()
    intraday_pct = close / open_.replace(0, pd.NA) - 1.0

    ma5 = close.rolling(5, min_periods=5).mean()
    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    vma20 = volume.rolling(20, min_periods=20).mean()

    symbol = str(stock_data.get("symbol") or "")
    min_amount_20, min_amount_60, amount_currency = _market_amount_thresholds(symbol)

    reasons: List[str] = []
    metrics: Dict[str, Any] = {}

    avg_amount_20 = float(amount.tail(20).mean())
    avg_amount_60 = float(amount.tail(60).mean())
    metrics["amount_currency"] = amount_currency
    metrics["avg_amount_20"] = round(avg_amount_20, 2)
    metrics["avg_amount_60"] = round(avg_amount_60, 2)
    # Backward-compatible keys for existing renderers; values are local currency, not always CNY.
    metrics["avg_amount_20_yuan"] = round(avg_amount_20, 2)
    metrics["avg_amount_60_yuan"] = round(avg_amount_60, 2)
    metrics["min_avg_amount_20"] = min_amount_20
    metrics["min_avg_amount_60"] = min_amount_60
    if avg_amount_20 < min_amount_20 and avg_amount_60 < min_amount_60:
        reasons.append(
            f"流动性弱({amount_currency}): 20日均额{avg_amount_20/1e8:.2f}亿, 60日均额{avg_amount_60/1e8:.2f}亿"
        )

    year_window = min(ONE_YEAR_LOOKBACK, len(data))
    recent_pct_60 = pct.tail(60)
    recent_intraday_pct_60 = intraday_pct.tail(60)
    year_pct = pct.tail(year_window)
    year_intraday_pct = intraday_pct.tail(year_window)
    year_vma20 = vma20.tail(year_window)

    day_range = (high - low).replace(0, pd.NA)
    upper_shadow = (high - close.where(close >= open_, open_)) / day_range
    upper_exhaust = ((high / close.replace(0, pd.NA) - 1.0) >= 0.04) & (upper_shadow >= 0.45)
    upper_20 = int(upper_exhaust.tail(20).fillna(False).sum())
    upper_60 = int(upper_exhaust.tail(60).fillna(False).sum())
    upper_1y = int(upper_exhaust.tail(year_window).fillna(False).sum())
    metrics["upper_shadow_exhaust_20"] = upper_20
    metrics["upper_shadow_exhaust_60"] = upper_60
    metrics["upper_shadow_exhaust_1y"] = upper_1y
    metrics["upper_shadow_exhaust_1y_rate_pct"] = round(upper_1y / year_window * 100, 2)
    if upper_20 >= 5 or upper_60 >= 10 or upper_1y / year_window >= 0.16:
        reasons.append(f"冲高回落多: 近20日{upper_20}次, 近60日{upper_60}次, 近1年{upper_1y}次")

    prior_20_high = high.shift(1).rolling(20, min_periods=20).max()
    false_breakout = (high >= prior_20_high * 1.02) & (close <= prior_20_high)
    false_breakout_60 = int(false_breakout.tail(60).fillna(False).sum())
    false_breakout_1y = int(false_breakout.tail(year_window).fillna(False).sum())
    metrics["false_breakout_60"] = false_breakout_60
    metrics["false_breakout_1y"] = false_breakout_1y
    if false_breakout_60 >= 4 or false_breakout_1y >= 10:
        reasons.append(f"假突破多: 近60日{false_breakout_60}次, 近1年{false_breakout_1y}次")

    large_down_60_series = (recent_pct_60 <= -0.05) | (recent_intraday_pct_60 <= -0.05)
    large_down_1y_series = (year_pct <= -0.05) | (year_intraday_pct <= -0.05)
    large_down_20 = int(large_down_60_series.tail(20).fillna(False).sum())
    large_down_60 = int(large_down_60_series.fillna(False).sum())
    large_down_1y = int(large_down_1y_series.fillna(False).sum())
    metrics["large_down_20"] = large_down_20
    metrics["large_down_60"] = large_down_60
    metrics["large_down_1y"] = large_down_1y
    # Growth/semiconductor stocks naturally have large down days.  Treat this
    # as a volatility penalty only, not as a hard veto.

    bearish_volume = (
        (year_pct <= -0.03)
        & (volume.tail(year_window) >= year_vma20 * 1.5)
    )
    bearish_volume_60 = int(bearish_volume.tail(60).fillna(False).sum())
    bearish_volume_1y = int(bearish_volume.fillna(False).sum())
    metrics["bearish_volume_60"] = bearish_volume_60
    metrics["bearish_volume_1y"] = bearish_volume_1y
    if bearish_volume_60 >= 4 or bearish_volume_1y >= 10:
        reasons.append(f"放量阴线多: 近60日{bearish_volume_60}次, 近1年{bearish_volume_1y}次")

    cross_total = (
        _cross_count(ma5, ma10, year_window)
        + _cross_count(ma5, ma20, year_window)
        + _cross_count(ma10, ma20, year_window)
    )
    ma20_slope_20 = _pct_change(float(ma20.iloc[-1]), float(ma20.iloc[-21])) if pd.notna(ma20.iloc[-21]) else 0.0
    ma60_slope_20 = _pct_change(float(ma60.iloc[-1]), float(ma60.iloc[-21])) if pd.notna(ma60.iloc[-21]) else 0.0
    metrics["ma_cross_count_1y"] = cross_total
    metrics["ma20_slope_20d_pct"] = round(ma20_slope_20 * 100, 2)
    metrics["ma60_slope_20d_pct"] = round(ma60_slope_20 * 100, 2)
    if cross_total >= 28 and abs(ma20_slope_20) < 0.01 and abs(ma60_slope_20) < 0.01:
        reasons.append(f"均线缠绕: 近1年5/10/20交叉{cross_total}次且20/60日线走平")

    last_close = float(close.iloc[-1])
    last_ma20 = float(ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else None
    last_ma60 = float(ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else None
    metrics["close"] = round(last_close, 3)
    metrics["ma20"] = round(last_ma20, 3) if last_ma20 is not None else None
    metrics["ma60"] = round(last_ma60, 3) if last_ma60 is not None else None
    if (
        last_ma20 is not None
        and last_ma60 is not None
        and ma20_slope_20 <= -0.015
        and ma60_slope_20 <= -0.01
        and last_close < last_ma20
    ):
        reasons.append("趋势底座弱: MA20/MA60 同向下且收盘低于 MA20")

    score = 100.0
    if avg_amount_20 < min_amount_20 and avg_amount_60 < min_amount_60:
        score -= 30.0
    score -= min(25.0, upper_1y / max(year_window, 1) * 120.0)
    score -= min(20.0, false_breakout_1y * 2.5)
    score -= min(8.0, large_down_1y * 0.6)
    score -= min(15.0, bearish_volume_1y * 2.0)
    score -= min(15.0, cross_total / 3.0)
    if ma20_slope_20 <= -0.015 and ma60_slope_20 <= -0.01:
        score -= 10.0
    score = max(0.0, round(score, 1))
    if score >= 75:
        status = "好"
    elif score >= 55:
        status = "一般"
    else:
        status = "差"

    return {
        "passed": len(reasons) == 0,
        "reasons": reasons,
        "status": status,
        "score": score,
        "warning": None,
        "metrics": metrics,
    }


def stock_character_passed(stock_data: Dict[str, Any]) -> bool:
    return bool(evaluate_stock_character(stock_data).get("passed", True))
