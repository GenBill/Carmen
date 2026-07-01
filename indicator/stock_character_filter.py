"""
A-share stock-character auxiliary filter.

Runs after Carmen standard buy signal (A) and before position-build / tuo gates
(B/C).  The filter is deliberately conservative: missing data does not block.
Stock character only blocks when the score is low and auxiliary veto items are hit.
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
AUXILIARY_BLOCK_SCORE_THRESHOLD = 55.0


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


def _structure_break(
    close: pd.Series,
    low: pd.Series,
    ma20: pd.Series,
) -> pd.Series:
    """
    Pullback that holds trend support is normal (esp. after multi-day rallies).
    Only treat spike/fade as bad when price closes below structure.

    Uses both medium-term (MA20 / 10-day low) and short-term rally support
    (5-day low / 3-day close cluster) so parabolic growers are not under-penalized.
    """
    buffer = 0.995
    support_low_10 = low.shift(1).rolling(10, min_periods=10).min()
    support_low_5 = low.shift(1).rolling(5, min_periods=5).min()
    support_close_3 = close.shift(1).rolling(3, min_periods=3).min()
    ma20_break = ma20.notna() & (close < ma20)
    swing_low_break = close < (support_low_10 * buffer)
    rally_low_break = close < (support_low_5 * buffer)
    close_cluster_break = close < (support_close_3 * buffer)
    return ma20_break | swing_low_break | rally_low_break | close_cluster_break


def _post_spike_sustained_bleed(
    close: pd.Series,
    high: pd.Series,
    open_: pd.Series,
    pct: pd.Series,
    *,
    lookahead: int = 8,
    recovery_ratio: float = 0.995,
    min_consec_down: int = 3,
    min_down_pct: float = -0.01,
    min_cum_bleed: float = 0.06,
) -> pd.Series:
    """
    After a spike day, mild one-day pullbacks are fine only if price recovers soon.
    Flag sustained post-spike bleed (+6 -2 -2 -2...) that never reclaims spike close.
    """
    n = len(close)
    confirmed = pd.Series(False, index=close.index)
    if n == 0:
        return confirmed

    open_safe = open_.replace(0, pd.NA)
    prior_close_safe = close.shift(1).replace(0, pd.NA)
    intraday_spike = (high / open_safe - 1.0 >= 0.04) | (high / prior_close_safe - 1.0 >= 0.05)
    spike_day = (pct >= 0.05) | intraday_spike

    for i in spike_day.fillna(False).to_numpy().nonzero()[0]:
        spike_close = float(close.iloc[i])
        if not math.isfinite(spike_close) or spike_close <= 0:
            continue

        consec = 0
        down_days = 0
        cum_low = spike_close
        confirm_idx = None

        for j in range(i + 1, min(i + lookahead + 1, n)):
            day_close = float(close.iloc[j])
            if not math.isfinite(day_close):
                continue

            if day_close >= spike_close * recovery_ratio:
                confirm_idx = None
                break

            cum_low = min(cum_low, day_close)
            day_pct = pct.iloc[j]
            if pd.notna(day_pct) and float(day_pct) <= min_down_pct:
                down_days += 1
                consec += 1
            else:
                consec = 0

            cum_bleed = 1.0 - cum_low / spike_close
            if (consec >= min_consec_down and cum_bleed >= min_cum_bleed) or (
                down_days >= 2 and cum_bleed >= min_cum_bleed
            ):
                confirm_idx = j
                break

        if confirm_idx is not None:
            confirmed.iloc[confirm_idx] = True

    return confirmed


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
            "warning": "股性数据不足，仅作通过处理",
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
            "warning": "股性字段缺失，仅作通过处理",
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
            "warning": "股性有效样本不足，仅作通过处理",
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

    veto_reasons: List[str] = []
    risk_reasons: List[str] = []
    metrics: Dict[str, Any] = {}

    avg_amount_20_hist = float(amount.tail(20).mean())
    avg_amount_60 = float(amount.tail(60).mean())
    estimated_volume = stock_data.get("estimated_volume")
    current_price = stock_data.get("close", close.iloc[-1])
    current_amount = None
    try:
        if estimated_volume is not None and current_price is not None:
            current_amount_value = float(estimated_volume) * float(current_price)
            if math.isfinite(current_amount_value) and current_amount_value > 0:
                current_amount = current_amount_value
    except (TypeError, ValueError):
        current_amount = None
    # Stock character is historical quality.  A single intraday volume burst must
    # not turn an illiquid 20-day average into a passing one.
    avg_amount_20 = avg_amount_20_hist

    metrics["amount_currency"] = amount_currency
    metrics["avg_amount_20"] = round(avg_amount_20, 2)
    metrics["avg_amount_20_hist"] = round(avg_amount_20_hist, 2)
    metrics["current_est_amount"] = round(current_amount, 2) if current_amount is not None else None
    metrics["avg_amount_60"] = round(avg_amount_60, 2)
    # Backward-compatible keys for existing renderers; values are local currency, not always CNY.
    metrics["avg_amount_20_yuan"] = round(avg_amount_20, 2)
    metrics["avg_amount_20_hist_yuan"] = round(avg_amount_20_hist, 2)
    metrics["avg_amount_60_yuan"] = round(avg_amount_60, 2)
    metrics["min_avg_amount_20"] = min_amount_20
    metrics["min_avg_amount_60"] = min_amount_60
    if avg_amount_20 < min_amount_20:
        veto_reasons.append(
            f"流动性弱({amount_currency}): 20日均额{avg_amount_20/1e8:.2f}亿, 60日均额{avg_amount_60/1e8:.2f}亿"
        )
    elif avg_amount_60 < min_amount_60:
        risk_reasons.append(
            f"中期流动性偏弱({amount_currency}): 20日均额{avg_amount_20/1e8:.2f}亿, 60日均额{avg_amount_60/1e8:.2f}亿"
        )

    year_window = min(ONE_YEAR_LOOKBACK, len(data))
    recent_pct_60 = pct.tail(60)
    recent_intraday_pct_60 = intraday_pct.tail(60)
    year_pct = pct.tail(year_window)
    year_intraday_pct = intraday_pct.tail(year_window)
    year_vma20 = vma20.tail(year_window)

    day_range = (high - low).replace(0, pd.NA)
    upper_shadow = (high - close.where(close >= open_, open_)) / day_range
    prior_close = close.shift(1)
    open_safe = open_.replace(0, pd.NA)
    close_safe = close.replace(0, pd.NA)
    prior_close_safe = prior_close.replace(0, pd.NA)
    structure_break = _structure_break(close, low, ma20)

    # 1-day wonder: spike then fail, but ONLY when structure breaks.
    # Long upper shadows after multi-day rallies that hold MA20 / swing lows are normal.
    intraday_spike = (high / open_safe - 1.0 >= 0.04) | (high / prior_close_safe - 1.0 >= 0.05)
    same_day_fade_signal = (
        (close <= open_)
        | ((high / close_safe - 1.0 >= 0.04) & (upper_shadow >= 0.45))
        | ((high / open_safe - 1.0 >= 0.05) & (close / open_safe - 1.0 <= 0.01))
    )
    spike_same_day_fade = intraday_spike & same_day_fade_signal & structure_break

    # Post-spike: +6 -2.5 +4 reclaim = OK; +6 -2 -2 -2 -2 never reclaim = scam.
    post_spike_bleed = _post_spike_sustained_bleed(close, high, open_, pct)
    pump_fade = spike_same_day_fade | post_spike_bleed

    pump_fade_20 = int(pump_fade.tail(20).fillna(False).sum())
    pump_fade_60 = int(pump_fade.tail(60).fillna(False).sum())
    pump_fade_1y = int(pump_fade.tail(year_window).fillna(False).sum())
    pump_same_20 = int(spike_same_day_fade.tail(20).fillna(False).sum())
    pump_same_60 = int(spike_same_day_fade.tail(60).fillna(False).sum())
    pump_same_1y = int(spike_same_day_fade.tail(year_window).fillna(False).sum())
    pump_next_20 = int(post_spike_bleed.tail(20).fillna(False).sum())
    pump_next_60 = int(post_spike_bleed.tail(60).fillna(False).sum())
    pump_next_1y = int(post_spike_bleed.tail(year_window).fillna(False).sum())

    metrics["pump_fade_20"] = pump_fade_20
    metrics["pump_fade_60"] = pump_fade_60
    metrics["pump_fade_1y"] = pump_fade_1y
    metrics["pump_fade_same_day_20"] = pump_same_20
    metrics["pump_fade_same_day_60"] = pump_same_60
    metrics["pump_fade_same_day_1y"] = pump_same_1y
    metrics["pump_fade_next_day_20"] = pump_next_20
    metrics["pump_fade_next_day_60"] = pump_next_60
    metrics["pump_fade_next_day_1y"] = pump_next_1y
    metrics["pump_fade_1y_rate_pct"] = round(pump_fade_1y / year_window * 100, 2)
    # Backward-compatible keys for existing renderers.
    metrics["upper_shadow_exhaust_20"] = pump_fade_20
    metrics["upper_shadow_exhaust_60"] = pump_fade_60
    metrics["upper_shadow_exhaust_1y"] = pump_fade_1y
    metrics["upper_shadow_exhaust_1y_rate_pct"] = metrics["pump_fade_1y_rate_pct"]
    if pump_fade_20 >= 3 or pump_fade_60 >= 6 or pump_fade_1y / year_window >= 0.08:
        veto_reasons.append(
            f"1日游冲高回落(破位): 近20日{pump_fade_20}次(当日{pump_same_20}/阴跌未收回{pump_next_20}), "
            f"近60日{pump_fade_60}次(当日{pump_same_60}/阴跌未收回{pump_next_60}), "
            f"近1年{pump_fade_1y}次(当日{pump_same_1y}/阴跌未收回{pump_next_1y})"
        )

    prior_20_high = high.shift(1).rolling(20, min_periods=20).max()
    false_breakout = (high >= prior_20_high * 1.02) & (close <= prior_20_high)
    false_breakout_60 = int(false_breakout.tail(60).fillna(False).sum())
    false_breakout_1y = int(false_breakout.tail(year_window).fillna(False).sum())
    metrics["false_breakout_60"] = false_breakout_60
    metrics["false_breakout_1y"] = false_breakout_1y
    if false_breakout_60 >= 4 or false_breakout_1y >= 10:
        risk_reasons.append(f"假突破多: 近60日{false_breakout_60}次, 近1年{false_breakout_1y}次")

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
        risk_reasons.append(f"放量阴线多: 近60日{bearish_volume_60}次, 近1年{bearish_volume_1y}次")

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
        risk_reasons.append(f"均线缠绕: 近1年5/10/20交叉{cross_total}次且20/60日线走平")

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
        risk_reasons.append("趋势底座弱: MA20/MA60 同向下且收盘低于 MA20")

    score = 100.0
    if avg_amount_20 < min_amount_20:
        score -= 30.0
    elif avg_amount_60 < min_amount_60:
        score -= 12.0
    score -= min(25.0, pump_fade_1y / max(year_window, 1) * 120.0)
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

    auxiliary_blocked = score < AUXILIARY_BLOCK_SCORE_THRESHOLD and bool(veto_reasons)

    return {
        "passed": not auxiliary_blocked,
        "auxiliary_blocked": auxiliary_blocked,
        "reasons": veto_reasons,
        "veto_reasons": veto_reasons,
        "risk_reasons": risk_reasons,
        "status": status,
        "score": score,
        "warning": None,
        "metrics": metrics,
    }


def stock_character_passed(stock_data: Dict[str, Any]) -> bool:
    return bool(evaluate_stock_character(stock_data).get("passed", True))
