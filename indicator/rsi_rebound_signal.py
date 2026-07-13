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


# --- RSI + Bullish Pin Bar（适中 B）+ 下影量门 ---

RSI_PIN_LOOKBACK_BARS = 3
RSI_PIN_SHADOW_DAY_RATIO = 0.40
RSI_PIN_SHADOW_AVG5_MULT = 0.60
RSI_PIN_AVG_VOLUME_DAYS = 5


def latest_daily_ohlc(stock_data: dict) -> Optional[Tuple[float, float, float, float]]:
    """返回最近一根日 K 的 Open, High, Low, Close。"""
    hist = (stock_data or {}).get('hist')
    if hist is None or getattr(hist, 'empty', True):
        return None
    need = {'Open', 'High', 'Low', 'Close'}
    if not need.issubset(set(hist.columns)) or len(hist) < 1:
        return None
    row = hist.iloc[-1]
    try:
        o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (o, h, l, c)):
        return None
    return o, h, l, c


def is_bullish_pin_bar_moderate(stock_data: dict) -> Tuple[bool, str]:
    """
    适中 Bullish Pin Bar：
    下影 >= 实体*2；上影 <= range/3；收盘在区间上 1/3；允许小阴锤。
    """
    ohlc = latest_daily_ohlc(stock_data)
    if ohlc is None:
        return False, '日K OHLC无效'
    open_, high, low, close = ohlc
    bar_range = high - low
    if bar_range <= 0:
        return False, '日K振幅为0'
    body = abs(close - open_)
    lower_shadow = min(open_, close) - low
    upper_shadow = high - max(open_, close)
    if lower_shadow < body * 2.0:
        return False, f'下影不足(下影={lower_shadow:.4f}, 实体={body:.4f})'
    if upper_shadow > bar_range / 3.0:
        return False, f'上影过长(上影={upper_shadow:.4f}, range={bar_range:.4f})'
    if close < low + bar_range * (2.0 / 3.0):
        return False, f'收盘未在区间上1/3(close={close:.4f})'
    return True, 'Bullish Pin Bar(适中)'


def had_rsi_oversold_in_lookback(
    stock_data: dict,
    threshold: float,
    lookback_bars: int = RSI_PIN_LOOKBACK_BARS,
    rsi_period: int = 8,
) -> Tuple[bool, str]:
    """近 lookback_bars 根日 K 是否曾出现 RSI < threshold。"""
    hist = (stock_data or {}).get('hist')
    if hist is None or getattr(hist, 'empty', True) or 'Close' not in hist.columns:
        return False, '无日K收盘价，无法计算近端RSI'
    if len(hist) < max(int(lookback_bars), 1):
        return False, f'日K不足{lookback_bars}根'

    from get_stock_price import calculate_rsi

    rsi_series = calculate_rsi(hist['Close'], period=int(rsi_period), return_series=True)
    if rsi_series is None or getattr(rsi_series, 'empty', True):
        return False, 'RSI序列无效'
    window = rsi_series.iloc[-int(lookback_bars):]
    for raw in window.tolist():
        rsi = finite_rsi(raw)
        if rsi is not None and rsi < float(threshold):
            return True, f'近{lookback_bars}日曾RSI超跌(最低<{threshold:g})'
    return False, f'近{lookback_bars}日RSI均未<{threshold:g}'


def avg_daily_volume_exclude_today(stock_data: dict, days: int = RSI_PIN_AVG_VOLUME_DAYS) -> Optional[float]:
    hist = (stock_data or {}).get('hist')
    if hist is None or getattr(hist, 'empty', True) or 'Volume' not in hist.columns:
        return None
    if len(hist) < days + 1:
        return None
    window = hist['Volume'].iloc[-(days + 1):-1].astype(float)
    vals = [_finite_float(v) for v in window.tolist()]
    vals = [v for v in vals if v is not None and v > 0]
    if len(vals) < days:
        return None
    return float(sum(vals) / len(vals))


def shadow_price_zone(stock_data: dict) -> Optional[Tuple[float, float]]:
    """下影价位段 [low, min(open, close)]。"""
    ohlc = latest_daily_ohlc(stock_data)
    if ohlc is None:
        return None
    open_, _high, low, close = ohlc
    top = min(open_, close)
    if top < low:
        return None
    return float(low), float(top)


def _bar_overlaps_zone(bar_low: float, bar_high: float, zone_low: float, zone_high: float) -> bool:
    return bar_low <= zone_high and bar_high >= zone_low


def compute_shadow_volume_from_5m(
    stock_data: dict,
    hist_5m,
) -> Tuple[Optional[float], Optional[float], str]:
    """
    用当日 5m K 统计下影段成交量与全日 5m 总量。
    返回 (shadow_vol, day_vol, reason)。
    """
    zone = shadow_price_zone(stock_data)
    if zone is None:
        return None, None, '下影价位段无效'
    zone_low, zone_high = zone

    if hist_5m is None or getattr(hist_5m, 'empty', True):
        return None, None, '5m数据为空'
    need = {'High', 'Low', 'Volume'}
    if not need.issubset(set(hist_5m.columns)):
        return None, None, '5m缺少High/Low/Volume'

    trade_date = (stock_data or {}).get('date')
    day_bars = hist_5m
    if trade_date is not None:
        try:
            idx_dates = day_bars.index.tz_localize(None) if getattr(day_bars.index, 'tz', None) is not None else day_bars.index
            day_str = str(trade_date)[:10]
            mask = idx_dates.strftime('%Y-%m-%d') == day_str
            day_bars = day_bars.loc[mask]
        except Exception:
            pass

    if day_bars is None or getattr(day_bars, 'empty', True):
        return None, None, '无与日K对齐的当日5m'

    shadow_vol = 0.0
    day_vol = 0.0
    for _, row in day_bars.iterrows():
        vol = _finite_float(row.get('Volume'))
        lo = _finite_float(row.get('Low'))
        hi = _finite_float(row.get('High'))
        if vol is None or vol < 0 or lo is None or hi is None:
            continue
        day_vol += vol
        if _bar_overlaps_zone(lo, hi, zone_low, zone_high):
            shadow_vol += vol

    if day_vol <= 0:
        return None, None, '当日5m成交量为0'
    return shadow_vol, day_vol, 'ok'


def evaluate_rsi_pin_bar_prefilter(
    stock_data: dict,
    threshold: float,
    *,
    lookback_bars: int = RSI_PIN_LOOKBACK_BARS,
    rsi_period: int = 8,
) -> Tuple[bool, str]:
    """阶段1：近端 RSI 超跌 + 当日 Pin Bar 形态（不拉 5m）。"""
    rsi_ok, rsi_reason = had_rsi_oversold_in_lookback(
        stock_data, threshold, lookback_bars=lookback_bars, rsi_period=rsi_period,
    )
    if not rsi_ok:
        return False, rsi_reason
    pin_ok, pin_reason = is_bullish_pin_bar_moderate(stock_data)
    if not pin_ok:
        return False, pin_reason
    return True, f'{rsi_reason}；{pin_reason}'


def evaluate_rsi_pin_bar_shadow_volume(
    stock_data: dict,
    hist_5m,
    *,
    day_ratio: float = RSI_PIN_SHADOW_DAY_RATIO,
    avg5_mult: float = RSI_PIN_SHADOW_AVG5_MULT,
    avg_days: int = RSI_PIN_AVG_VOLUME_DAYS,
) -> Tuple[bool, str, dict]:
    """
    阶段2：下影量门
    shadow_vol >= day_vol * day_ratio  OR  shadow_vol >= avg_vol_5d * avg5_mult
    """
    info: dict = {
        'shadow_vol': None,
        'day_vol': None,
        'avg_vol_5d': None,
        'day_ratio': float(day_ratio),
        'avg5_mult': float(avg5_mult),
        'passed_day_ratio': False,
        'passed_avg5': False,
        'passed': False,
        'reason': '',
    }
    shadow_vol, day_vol, reason = compute_shadow_volume_from_5m(stock_data, hist_5m)
    if shadow_vol is None or day_vol is None:
        info['reason'] = reason
        return False, reason, info

    avg_vol_5d = avg_daily_volume_exclude_today(stock_data, days=avg_days)
    info.update({
        'shadow_vol': shadow_vol,
        'day_vol': day_vol,
        'avg_vol_5d': avg_vol_5d,
    })

    passed_day = shadow_vol >= day_vol * float(day_ratio)
    passed_avg = avg_vol_5d is not None and shadow_vol >= avg_vol_5d * float(avg5_mult)
    info['passed_day_ratio'] = passed_day
    info['passed_avg5'] = bool(passed_avg)

    if passed_day or passed_avg:
        info['passed'] = True
        parts = []
        if passed_day:
            parts.append(f'下影/日量={shadow_vol / day_vol:.2f}>={day_ratio:g}')
        if passed_avg:
            parts.append(f'下影/5日均量={shadow_vol / avg_vol_5d:.2f}>={avg5_mult:g}')
        info['reason'] = '下影量门通过：' + '；'.join(parts)
        return True, info['reason'], info

    avg_txt = f'{avg_vol_5d:.0f}' if avg_vol_5d is not None else 'N/A'
    info['reason'] = (
        f'下影量门未过(shadow={shadow_vol:.0f}, day={day_vol:.0f}, '
        f'ratio={shadow_vol / day_vol:.2f}, avg5d={avg_txt})'
    )
    return False, info['reason'], info

