import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz
import os
import pickle
from pathlib import Path
import time

from lut import INTRADAY_VOLUME_LUT, INTRADAY_VOLUME_HK, INTRADAY_VOLUME_A

# 缓存目录
CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

# 全局内存缓存：{symbol: (timestamp, hist_data)}
# 同时支持本地文件缓存，避免程序重启后重新获取数据
_DATA_CACHE = {}

# 损坏的股票代码列表（多次失败后不再尝试）
broken_stock_symbols = []
try:
    broken_symbols_file = Path(__file__).parent.parent / 'broken_stock_symbols.txt'
    if broken_symbols_file.exists():
        with open(broken_symbols_file, 'r') as f:
            broken_stock_symbols = [line.strip() for line in f if line.strip()]
except:
    broken_stock_symbols = []

def calculate_rsi(prices, period=14, return_series=False):
    """
    计算 RSI 指标（使用 Wilder's Smoothing 方法，与富途等主流平台一致）
    
    Args:
        prices: 价格序列（pandas Series）
        period: RSI 周期，默认 14
        return_series: 是否返回整个序列，默认 False（只返回最后一个值）
        
    Returns:
        float 或 Series: RSI 值或整个 RSI 序列
    """
    # 计算价格变动
    delta = prices.diff()
    
    # 分离上涨和下跌
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # 使用 Wilder's Smoothing（威尔德平滑法）
    # 这等同于 EMA，alpha = 1/period
    # pandas ewm 参数：alpha = 1/period，adjust=False 表示使用递归计算
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    # 计算 RS 和 RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    if return_series:
        return rsi
    else:
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else None


def calculate_ema(prices, period, return_series=False):
    """
    计算 EMA (指数移动平均线)
    
    Args:
        prices: 价格序列（pandas Series）
        period: EMA 周期
        return_series: 是否返回整个序列，默认 False（只返回最后一个值）
        
    Returns:
        float 或 Series: EMA 值或整个 EMA 序列
    """
    ema = prices.ewm(span=period, adjust=False).mean()
    
    if return_series:
        return ema
    else:
        return ema.iloc[-1] if not pd.isna(ema.iloc[-1]) else None


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """
    计算 MACD 指标
    
    Args:
        prices: 价格序列（pandas Series）
        fast: 快线周期，默认 12
        slow: 慢线周期，默认 26
        signal: 信号线周期，默认 9
        
    Returns:
        dict: 包含 dif(macd), dea(signal), histogram, dif_dea_slope 的字典
    """
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    dif = exp1 - exp2  # DIF线（快线-慢线）
    dea = dif.ewm(span=signal, adjust=False).mean()  # DEA线（DIF的信号线）
    histogram = dif - dea
    
    # 计算DIF斜率（当日DIF - 前一日DIF）
    dif_slope, dea_slope, dif_dea_slope = None, None, None
    if len(dif) >= 2 and not pd.isna(dif.iloc[-1]) and not pd.isna(dif.iloc[-2]):
        dif_slope = dif.iloc[-1] - dif.iloc[-2]
    if len(dea) >= 2 and not pd.isna(dea.iloc[-1]) and not pd.isna(dea.iloc[-2]):
        dea_slope = dea.iloc[-1] - dea.iloc[-2]
    if dif_slope != None and dea_slope != None:
        dif_dea_slope = round(dif_slope - dea_slope, 2)
    
    return {
        'dif': round(dif.iloc[-1], 2) if not pd.isna(dif.iloc[-1]) else None,
        'dea': round(dea.iloc[-1], 2) if not pd.isna(dea.iloc[-1]) else None,
        'histogram': round(histogram.iloc[-1], 2) if not pd.isna(histogram.iloc[-1]) else None,
        'dif_dea_slope': dif_dea_slope
    }


def is_intraday_data(trading_date_timestamp):
    """
    判断交易日数据是否是当日盘中数据
    
    Args:
        trading_date_timestamp: 交易日的时间戳（pandas Timestamp，带时区）
        
    Returns:
        tuple: (is_today, current_et_time) - 是否是今天的数据，当前美东时间
    """
    et_tz = pytz.timezone('America/New_York')
    
    # 将交易日时间戳转换为美东时间
    if trading_date_timestamp.tzinfo is None:
        # 如果没有时区信息，假设是UTC
        trading_date_et = trading_date_timestamp.tz_localize('UTC').tz_convert(et_tz)
    else:
        trading_date_et = trading_date_timestamp.tz_convert(et_tz)
    
    # 获取当前美东时间
    current_et = datetime.now(et_tz)
    
    # 提取日期部分进行比较
    trading_date_str = trading_date_et.strftime('%Y-%m-%d')
    current_date_str = current_et.strftime('%Y-%m-%d')
    
    is_today = (trading_date_str == current_date_str)
    
    return is_today, current_et

def is_market_time(current_et_time):
    """
    检查当前ET时间是否在美股交易时间内（9:30-16:00 ET，全年固定）。
    
    Args:
        current_et_time (datetime): 已转换为ET的datetime对象（无时区或带ET时区）。
    
    Returns:
        bool: 是否在交易时间内。
    """
    # 美股交易时间固定为ET 9:30-16:00（不含周末/假期，此函数仅查时间）
    current_time_minutes = current_et_time.hour * 60 + current_et_time.minute
    market_open = 9 * 60 + 30
    market_close = 16 * 60
    
    return market_open <= current_time_minutes < market_close  # 注意：收盘不含16:00本身，若需含可改<=

def estimate_full_day_volume_hka(current_volume, trading_date_timestamp, volume_lut=None, lunch_volume_multiplier=1.667):
    """
    港股/A股成交量估算（专用函数）
    港股交易时间：早盘 9:30-12:00 CST，午盘 13:00-16:00 CST
    午休时间：12:00-13:00 CST
    
    Args:
        current_volume: 当前成交量
        trading_date_timestamp: 交易日的时间戳（pandas Timestamp）
        volume_lut: 成交量LUT表，None则使用默认表
        lunch_volume_multiplier: 午休期间早盘成交量的倍率（默认1.667）
        
    Returns:
        int: 估算的全天成交量
    """
    # 使用北京/香港时区（CST/HKT，UTC+8）
    cst_tz = pytz.timezone('Asia/Shanghai')
    
    # 将交易日时间戳转换为北京时间
    if trading_date_timestamp.tzinfo is None:
        trading_date_cst = trading_date_timestamp.tz_localize('UTC').tz_convert(cst_tz)
    else:
        trading_date_cst = trading_date_timestamp.tz_convert(cst_tz)
    
    # 获取当前北京时间
    current_cst = datetime.now(cst_tz)
    
    # 提取日期部分进行比较
    trading_date_str = trading_date_cst.strftime('%Y-%m-%d')
    current_date_str = current_cst.strftime('%Y-%m-%d')
    
    is_today = (trading_date_str == current_date_str)
    
    if not is_today:
        # 不是今天的数据，直接返回原值（这是已收盘的完整数据）
        return current_volume
    
    # 获取当前时间（CST）
    current_time_minutes = current_cst.hour * 60 + current_cst.minute
    
    # 港股交易时间段（CST，北京时间）
    # 早盘：9:30-12:00（150分钟）
    # 午休：12:00-13:00（60分钟）
    # 午盘：13:00-16:00（180分钟）
    # 收盘后：16:00-次日9:30
    
    market_open_am = 9 * 60 + 30  # 9:30 CST
    market_close_am = 12 * 60      # 12:00 CST
    lunch_break_start = 12 * 60    # 12:00 CST
    lunch_break_end = 13 * 60      # 13:00 CST
    market_open_pm = 13 * 60       # 13:00 CST
    market_close_pm = 16 * 60      # 16:00 CST
    
    # 判断当前时间
    # 注意：脚本仅在午休时间和收盘后运行
    if lunch_break_start <= current_time_minutes < lunch_break_end:
        # 午休时段（12:00-13:00 CST）：早盘成交量 × 固定倍率
        estimated_volume = int(current_volume * lunch_volume_multiplier)
        return estimated_volume
    elif current_time_minutes >= market_close_pm:
        # 收盘后（16:00 CST之后）：直接使用当前成交量（已是全天成交量）
        return current_volume
    else:
        # 交易时段（理论上不会到达这里，因为脚本不在此时运行）
        # 但如果意外调用，使用LUT估算
        if volume_lut is None:
            volume_lut = INTRADAY_VOLUME_HK
        
        current_time_str = current_cst.strftime('%H:%M')
        
        # 查找最接近的时间点
        time_keys = sorted(volume_lut.keys())
        selected_ratio = None
        
        for time_key in time_keys:
            if current_time_str <= time_key:
                selected_ratio = volume_lut[time_key]
                break
        
        # 如果当前时间超过最后一个时间点，使用1.0
        if selected_ratio is None:
            selected_ratio = 1.0
        
        # 估算全天成交量
        if selected_ratio > 0:
            estimated_volume = int(current_volume / selected_ratio)
            return estimated_volume
        else:
            return current_volume


def estimate_full_day_volume(current_volume, trading_date_timestamp, volume_lut=None):
    """
    美股成交量估算（原有函数）
    根据盘中当前时间和成交量估算全天成交量
    只在确认是当日盘中数据时才估算，否则返回原值
    
    Args:
        current_volume: 当前成交量
        trading_date_timestamp: 交易日的时间戳（pandas Timestamp）
        volume_lut: 成交量LUT表，None则使用默认表
        
    Returns:
        int: 估算的全天成交量，如果不是盘中数据则返回原值
    """
    # 判断是否是当日盘中数据
    is_today, current_et_time = is_intraday_data(trading_date_timestamp)
    
    if not is_today:
        # 不是今天的数据，直接返回原值（这是已收盘的完整数据）
        return current_volume
    
    if not is_market_time(current_et_time):
        # 不在交易时间内，返回原值
        return current_volume
    
    # 在盘中，进行估算
    if volume_lut is None:
        volume_lut = INTRADAY_VOLUME_LUT
    
    current_time_str = current_et_time.strftime('%H:%M')
    
    # 查找最接近的时间点
    time_keys = sorted(volume_lut.keys())
    selected_ratio = None
    
    for time_key in time_keys:
        if current_time_str <= time_key:
            selected_ratio = volume_lut[time_key]
            break
    
    # 如果当前时间超过最后一个时间点，使用1.0
    if selected_ratio is None:
        selected_ratio = 1.0
    
    # 避免除以0
    if selected_ratio > 0:
        estimated_volume = int(current_volume / selected_ratio)
        return estimated_volume
    else:
        return current_volume


def _get_cache_file_path(symbol: str) -> Path:
    """获取缓存文件路径"""
    return CACHE_DIR / f"{symbol}.pkl"


def _load_cache_from_file(symbol: str):
    """从本地文件加载缓存"""
    cache_file = _get_cache_file_path(symbol)
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                cached_time, hist_data = pickle.load(f)
                return cached_time, hist_data
        except Exception as e:
            print(f"加载缓存文件失败 {symbol}: {e}")
            return None
    return None


def _save_cache_to_file(symbol: str, cached_time, hist_data):
    """保存缓存到本地文件"""
    cache_file = _get_cache_file_path(symbol)
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump((cached_time, hist_data), f)
    except Exception as e:
        print(f"保存缓存文件失败 {symbol}: {e}")


def _get_expected_latest_trading_date(current_et):
    """
    计算预期的最新交易日日期（不含节假日，仅排除周末）
    
    Args:
        current_et: 美东当前时间 (datetime with timezone)
    
    Returns:
        date: 预期的最新交易日日期
    """
    current_date = current_et.date()
    current_hour_minute = current_et.hour * 60 + current_et.minute
    
    # 美股收盘时间 16:00 (使用实际收盘时间，不是缓冲时间)
    market_close_time = 16 * 60  # 16:00
    is_weekday = current_et.weekday() < 5  # 周一到周五
    
    if is_weekday and current_hour_minute >= market_close_time:
        # 交易日已收盘 → 数据应该是今天
        return current_date
    else:
        # 盘前 或 周末 → 数据应该是上一个交易日
        # 回溯找到上一个交易日
        check_date = current_date - timedelta(days=1)
        while check_date.weekday() >= 5:  # 跳过周末
            check_date -= timedelta(days=1)
        return check_date


def _is_cache_valid_smart(cached_time, cached_hist, cache_minutes, ignore_expiry=False):
    """
    智能缓存有效性检查（基于数据最新日期和市场状态）
    
    核心思想：
    - 股票价格只在盘中变化
    - 缓存应该基于"数据的最新交易日"而不是"缓存保存时间"
    
    Args:
        cached_time: 缓存保存时间
        cached_hist: 缓存的历史数据
        cache_minutes: 缓存有效期（分钟）
        ignore_expiry: 是否忽略过期（离线模式）
        
    Returns:
        bool: 缓存是否有效
    """
    if ignore_expiry:
        return True
    
    now = datetime.now()
    et_tz = pytz.timezone('America/New_York')
    
    # 将缓存时间转换为美东时间
    if cached_time.tzinfo is None:
        cached_time_et = pytz.utc.localize(cached_time).astimezone(et_tz)
    else:
        cached_time_et = cached_time.astimezone(et_tz)
    
    current_et = datetime.now(et_tz)
    
    # 判断缓存保存时间是否在盘中（9:30-16:30 ET，含盘后30分钟缓冲期）
    cached_hour_minute = cached_time_et.hour * 60 + cached_time_et.minute
    market_open = 9 * 60 + 30   # 9:30
    market_close = 16 * 60 + 30  # 16:30（盘后30分钟缓冲，因API有5-10分钟延迟）
    was_cached_during_market = market_open <= cached_hour_minute < market_close
    
    # 如果缓存时间戳在盘中，使用传统的时间判断（短缓存）
    if was_cached_during_market:
        cache_age_minutes = (now - cached_time).total_seconds() / 60
        return cache_age_minutes < cache_minutes
    
    # 如果缓存时间戳不在盘中（盘前/盘后/周末），检查数据的最新日期
    if cached_hist is None or cached_hist.empty:
        return False
    
    # 获取缓存数据的最后交易日
    last_data_date = cached_hist.index[-1]
    if last_data_date.tzinfo is None:
        last_data_date_et = pytz.utc.localize(last_data_date).astimezone(et_tz)
    else:
        last_data_date_et = last_data_date.astimezone(et_tz)
    
    # 判断当前是否在盘中（含盘后30分钟缓冲期）
    current_hour_minute = current_et.hour * 60 + current_et.minute
    is_market_open_now = (market_open <= current_hour_minute < market_close and 
                          current_et.weekday() < 5)
    
    if is_market_open_now:
        # 当前在盘中，需要实时数据
        # 检查数据是否是今天的，且缓存不超过指定时间
        current_date = current_et.date()
        last_data_only_date = last_data_date_et.date()
        
        if last_data_only_date >= current_date:
            # 数据是今天的，检查缓存年龄
            cache_age_minutes = (now - cached_time).total_seconds() / 60
            return cache_age_minutes < cache_minutes
        else:
            # 数据不是今天的，需要刷新
            return False
    else:
        # 当前不在盘中（盘前/盘后/周末），需要最新交易日数据
        last_data_only_date = last_data_date_et.date()
        expected_date = _get_expected_latest_trading_date(current_et)
        
        # 【关键修复】必须先检查数据日期是否是最新交易日
        if last_data_only_date < expected_date:
            # 数据不是最新交易日，缓存无效，必须刷新
            return False
        
        # 数据是最新交易日的，再检查缓存年龄
        cache_age_minutes = (now - cached_time).total_seconds() / 60
        return cache_age_minutes < cache_minutes


def _load_from_cache(symbol: str, cache_minutes=5, ignore_expiry=False):
    """
    从缓存加载数据（公共函数）
    
    Args:
        symbol: 股票代码
        cache_minutes: 缓存有效期（分钟）
        ignore_expiry: 是否忽略过期时间（离线模式用）
        
    Returns:
        tuple: (hist_data, cache_source) 或 (None, None)
    """
    now = datetime.now()
    cache_key = symbol
    
    # 1. 检查内存缓存
    if cache_key in _DATA_CACHE:
        cached_time, cached_hist = _DATA_CACHE[cache_key]
        
        if _is_cache_valid_smart(cached_time, cached_hist, cache_minutes, ignore_expiry):
            return cached_hist, "内存"
    
    # 2. 检查文件缓存
    file_cache = _load_cache_from_file(symbol)
    if file_cache:
        cached_time, cached_hist = file_cache
        
        if _is_cache_valid_smart(cached_time, cached_hist, cache_minutes, ignore_expiry):
            # 加载到内存缓存
            _DATA_CACHE[cache_key] = (cached_time, cached_hist)
            return cached_hist, "文件"
    
    return None, None


def _calculate_indicators_from_hist(hist, symbol, rsi_period, macd_fast, macd_slow, 
                                    macd_signal, avg_volume_days, volume_lut):
    """
    从历史数据计算所有指标（公共计算逻辑）
    
    Args:
        hist: 历史数据DataFrame
        symbol: 股票代码
        其他参数: 技术指标参数
        
    Returns:
        dict: 包含所有计算结果的字典
    """
    if hist.empty or len(hist) < avg_volume_days + 1:
        return None
    
    # 获取最后一个交易日数据（当日或最近交易日）
    last_trading_day = hist.iloc[-1]
    
    # 检查关键数据有效性
    if pd.isna(last_trading_day['Close']):
        return None

    trading_date_timestamp = hist.index[-1]
    trading_date = trading_date_timestamp.strftime('%Y-%m-%d')
    
    # 计算过去 N 日平均成交量（明确排除当日，即最后一个交易日）
    if len(hist) >= avg_volume_days + 1:
        avg_volume = hist.iloc[-(avg_volume_days+1):-1]['Volume'].mean()
    else:
        avg_volume = hist.iloc[:-1]['Volume'].mean()
    
    if pd.isna(avg_volume):
        avg_volume = 0

    # 当日成交量
    current_volume = last_trading_day['Volume']
    if pd.isna(current_volume):
        current_volume = 0
    
    # 判断是港股/A股还是美股
    is_hk_stock = symbol.endswith('.HK')
    is_a_stock = symbol.endswith('.SS') or symbol.endswith('.SZ')
    
    # 估算全天成交量（只在确认是当日盘中数据时才估算）
    if is_hk_stock:
        estimated_volume = estimate_full_day_volume_hka(current_volume, trading_date_timestamp, volume_lut=INTRADAY_VOLUME_HK)
    elif is_a_stock:
        estimated_volume = estimate_full_day_volume_hka(current_volume, trading_date_timestamp, volume_lut=INTRADAY_VOLUME_A)
    else:
        estimated_volume = estimate_full_day_volume(current_volume, trading_date_timestamp, volume_lut=volume_lut)
    
    # 计算 RSI（获取完整序列以便提取前一日数据）
    rsi_series = calculate_rsi(hist['Close'], period=rsi_period, return_series=True)
    rsi = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else None
    rsi_prev = None
    if len(rsi_series) >= 2 and not pd.isna(rsi_series.iloc[-2]):
        rsi_prev = rsi_series.iloc[-2]
    
    # 计算 MACD
    macd_data = calculate_macd(hist['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    
    # 计算 EMA 指标（获取完整序列以便提取前一日数据）
    ema_12_series = calculate_ema(hist['Close'], period=12, return_series=True)
    ema_144_series = calculate_ema(hist['Close'], period=144, return_series=True)
    
    ema_12 = ema_12_series.iloc[-1] if not pd.isna(ema_12_series.iloc[-1]) else None
    ema_144 = ema_144_series.iloc[-1] if not pd.isna(ema_144_series.iloc[-1]) else None
    
    # 获取前一日 EMA 数据
    ema_12_prev = None
    ema_144_prev = None
    if len(ema_12_series) >= 2 and not pd.isna(ema_12_series.iloc[-2]):
        ema_12_prev = ema_12_series.iloc[-2]
    if len(ema_144_series) >= 2 and not pd.isna(ema_144_series.iloc[-2]):
        ema_144_prev = ema_144_series.iloc[-2]
    
    return {
        'symbol': symbol,
        'date': trading_date,
        'open': round(last_trading_day['Open'], 2),
        'close': round(last_trading_day['Close'], 2),
        'volume': int(current_volume),
        'estimated_volume': estimated_volume,
        'avg_volume': int(avg_volume),
        'rsi': round(rsi, 2) if rsi else None,
        'rsi_prev': round(rsi_prev, 2) if rsi_prev else None,
        'dif': macd_data['dif'],
        'dea': macd_data['dea'],
        'macd_histogram': macd_data['histogram'],
        'dif_dea_slope': macd_data['dif_dea_slope'],
        'ema_12': round(ema_12, 2) if ema_12 else None,
        'ema_144': round(ema_144, 2) if ema_144 else None,
        'ema_12_prev': round(ema_12_prev, 2) if ema_12_prev else None,
        'ema_144_prev': round(ema_144_prev, 2) if ema_144_prev else None
    }


def get_stock_data_offline(symbol: str, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, 
                           avg_volume_days=8, volume_lut=None, use_cache=True, cache_minutes=5):
    """
    离线模式：仅从缓存读取数据，不调用API（忽略缓存过期时间）
    
    Args:
        symbol: 股票代码
        rsi_period: RSI 周期，默认 14
        macd_fast: MACD 快线周期，默认 12
        macd_slow: MACD 慢线周期，默认 26
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        volume_lut: 自定义成交量估算LUT表，None则使用默认表
        use_cache: 是否使用缓存（离线模式固定为True）
        cache_minutes: 忽略（离线模式不检查过期）
        
    Returns:
        dict: 包含所有数据的字典，缓存不存在返回 None
    """
    try:
        # 从缓存加载（忽略过期时间）
        hist, cache_source = _load_from_cache(symbol, cache_minutes=0, ignore_expiry=True)
        
        if hist is None:
            # 离线模式下缓存不存在则返回None
            return None
        
        # 使用历史数据计算指标（公共计算逻辑）
        return _calculate_indicators_from_hist(
            hist, symbol, rsi_period, macd_fast, macd_slow,
            macd_signal, avg_volume_days, volume_lut
        )
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"⚠️  离线模式获取 {symbol} 数据时出错: {e}")
        return None


def batch_download_stocks(symbols: list, use_cache=True, cache_minutes=5, batch_size=50, period="1y"):
    """
    批量下载股票数据（使用 yfinance 的多线程加速）

    Args:
        symbols: 股票代码列表
        use_cache: 是否使用缓存，默认 True
        cache_minutes: 缓存有效期（分钟），默认 5分钟
        batch_size: 每批下载的股票数量，默认 50
        period: 下载数据的时间周期，默认 "1y"

    Returns:
        None
    """
    if not symbols:
        return

    # 过滤掉损坏的股票代码
    valid_symbols = [s for s in symbols if s not in broken_stock_symbols]
    if not valid_symbols:
        return

    # 检查缓存，只下载没有有效缓存的股票
    symbols_to_download = []
    for symbol in valid_symbols:
        if use_cache:
            hist, _ = _load_from_cache(symbol, cache_minutes, ignore_expiry=False)
            if hist is None:
                symbols_to_download.append(symbol)
        else:
            symbols_to_download.append(symbol)

    if not symbols_to_download:
        # print("✅ 所有股票缓存均有效，无需重新下载")
        return
    # if use_cache:
    #     print(f"📂 缓存目录: {CACHE_DIR.resolve()}")

    # 分批下载，避免单次请求过多
    total_batches = (len(symbols_to_download) + batch_size - 1) // batch_size
    try:
        from tqdm import tqdm
        batch_iter = tqdm(
            range(0, len(symbols_to_download), batch_size),
            desc="📥 批量下载股票数据",
            total=total_batches,
            unit="batch"
        )
    except ImportError:
        # 如果没有安装 tqdm，使用普通 range
        batch_iter = range(0, len(symbols_to_download), batch_size)

    for i in batch_iter:
        batch = symbols_to_download[i:i + batch_size]
        if not batch:
            continue

        try:
            # 使用 yf.download 批量下载，自动多线程加速
            # 必须指定 group_by='ticker' 才能使 Ticker 作为第一层索引，方便按股票切分
            hist_batch = yf.download(batch, period=period, progress=False, auto_adjust=False, threads=True, group_by='ticker')

            if hist_batch.empty:
                print(f"⚠️  批量下载返回空数据，批次: {i//batch_size + 1}")
                continue

            # 处理返回的数据格式
            # yf.download 返回格式：
            # - 单只股票：可能返回单层索引或 MultiIndex（取决于版本）
            # - 多只股票：返回 MultiIndex (ticker, column)
            if isinstance(hist_batch.columns, pd.MultiIndex):
                # MultiIndex：按 ticker 拆分
                # 获取所有 ticker（第一层索引）
                tickers_in_data = hist_batch.columns.get_level_values(0).unique().tolist()
                for symbol in batch:
                    if symbol in tickers_in_data:
                        try:
                            hist = hist_batch[symbol].copy()
                            if not hist.empty:
                                # 更新缓存
                                # 确保格式对齐：(timestamp, dataframe)
                                if use_cache:
                                    now = datetime.now()
                                    _DATA_CACHE[symbol] = (now, hist)
                                    _save_cache_to_file(symbol, now, hist)
                        except Exception as e:
                            print(f"⚠️  处理 {symbol} 数据时出错: {e}")
                            continue
            else:
                # 单层索引：只有一只股票的情况
                if len(batch) == 1:
                    symbol = batch[0]
                    if not hist_batch.empty:
                        if use_cache:
                            now = datetime.now()
                            _DATA_CACHE[symbol] = (now, hist_batch)
                            _save_cache_to_file(symbol, now, hist_batch)
                else:
                    # 多只股票但返回单层索引（异常情况，可能所有股票都下载失败）
                    print(f"⚠️  批量下载返回异常格式，批次大小: {len(batch)}")

            # 避免过于频繁的API调用
            if i + batch_size < len(symbols_to_download):
                time.sleep(0.01)

        except Exception as e:
            print(f"⚠️  批量下载失败 (批次 {i//batch_size + 1}): {e}")
            continue
    return


def get_stock_data(symbol: str, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, 
                   avg_volume_days=8, volume_lut=None, use_cache=True, cache_minutes=5):
    """
    获取股票的全面数据，包括价格、成交量和技术指标
    
    Args:
        symbol: 股票代码
        rsi_period: RSI 周期，默认 14
        macd_fast: MACD 快线周期，默认 12
        macd_slow: MACD 慢线周期，默认 26
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        volume_lut: 自定义成交量估算LUT表，None则使用默认表
        use_cache: 是否使用本地缓存，默认 True
        cache_minutes: 缓存有效期（分钟），默认 5分钟
        offline_mode: 是否离线模式，默认 False
        
    Returns:
        dict: 包含所有数据的字典，失败返回 None
    """
    try:
        # 1. 尝试从缓存加载（使用公共函数）
        hist, cache_source = _load_from_cache(symbol, cache_minutes, ignore_expiry=False) if use_cache else (None, None)
        
        # 2. 如果没有缓存或缓存过期，从API获取（带指数退避重试）
        if hist is None:
            # 避免过于频繁的API调用
            time.sleep(0.01)
            
            max_retries = 3   # 减少重试次数
            base_delay = 0.5  # 调整基础延迟
            
            for attempt in range(max_retries):

                if symbol in broken_stock_symbols:
                    return None
                
                try:
                    # 获取足够的历史数据以计算技术指标
                    # 数据越多，EMA越稳定。API调用次数与数据长度无关，所以尽可能多获取
                    # EMA需要足够的warmup期才能稳定，建议至少(慢线+信号线)*5 或 100天以上
                    # 对于MACD(8,17,9)：(17+9)*5 = 130天
                    # 对于MACD(12,26,9)：(26+9)*5 = 175天
                    # 使用1y获取约250天数据，精度最佳且API消耗不变
                    # 使用 yf.download 替代 stock.history，支持 progress=False 直接屏蔽输出
                    # auto_adjust=False 保持与 stock.history() 默认行为一致
                    hist = yf.download(symbol, period="1y", progress=False, auto_adjust=False)
                    
                    # 处理可能的双层列索引（单只股票时 yf.download 可能返回多层索引）
                    if not hist.empty and isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = hist.columns.droplevel(1)
                    
                    if not hist.empty:
                        cache_source = "API"
                        # 更新缓存（内存+文件）
                        if use_cache:
                            now = datetime.now()
                            _DATA_CACHE[symbol] = (now, hist)
                            _save_cache_to_file(symbol, now, hist)
                        break  # 成功获取，跳出重试循环
                    else:
                        raise Exception("返回空数据")
                        
                except Exception as api_error:
                    if attempt < max_retries - 1:
                        # 指数退避
                        delay = base_delay * (2 ** attempt)
                        print(f"⚠️  {symbol} API调用失败 (尝试 {attempt + 1}/{max_retries}): {api_error}")
                        time.sleep(delay)
                    else:
                        print(f"❌ {symbol} API调用最终失败 (已重试{max_retries}次): {api_error}")
                        return None
        
        # 3. 使用历史数据计算指标（公共计算逻辑）
        return _calculate_indicators_from_hist(
            hist, symbol, rsi_period, macd_fast, macd_slow,
            macd_signal, avg_volume_days, volume_lut
        )
    
    except KeyboardInterrupt:
        # 允许用户中断
        raise
    except Exception as e:
        print(f"⚠️  获取 {symbol} 数据时出错: {e}")
        return None


def get_previous_trading_day_prices(symbol: str):
    """
    获取指定股票上一个交易日的开盘价和收盘价（保留向后兼容）
    
    Args:
        symbol: 股票代码
        
    Returns:
        dict: 包含 symbol, date, open, close 的字典，失败返回 None
    """
    data = get_stock_data(symbol)
    if data:
        return {
            'symbol': data['symbol'],
            'date': data['date'],
            'open': data['open'],
            'close': data['close']
        }
    return None


def get_cache_stats():
    """
    获取缓存统计信息（内存+文件）
    
    Returns:
        dict: 包含缓存统计的字典
    """
    now = datetime.now()
    stats = {
        'memory_cached': len(_DATA_CACHE),
        'file_cached': 0,
        'symbols': []
    }
    
    # 统计所有缓存（内存+文件）
    all_symbols = set()
    
    # 1. 内存缓存
    for symbol in _DATA_CACHE.keys():
        all_symbols.add(symbol)
    
    # 2. 文件缓存
    for cache_file in CACHE_DIR.glob("*.pkl"):
        symbol = cache_file.stem
        all_symbols.add(symbol)
        stats['file_cached'] += 1
    
    # 收集详细信息
    for symbol in sorted(all_symbols):
        info = {'symbol': symbol, 'sources': []}
        
        # 检查内存缓存
        if symbol in _DATA_CACHE:
            cached_time, hist = _DATA_CACHE[symbol]
            age_minutes = (now - cached_time).total_seconds() / 60
            info['sources'].append({
                'type': '内存',
                'age_minutes': age_minutes,
                'data_points': len(hist) if hist != None else 0
            })
        
        # 检查文件缓存
        cache_file = _get_cache_file_path(symbol)
        if cache_file.exists():
            file_cache = _load_cache_from_file(symbol)
            if file_cache:
                cached_time, hist = file_cache
                age_minutes = (now - cached_time).total_seconds() / 60
                info['sources'].append({
                    'type': '文件',
                    'age_minutes': age_minutes,
                    'data_points': len(hist) if hist != None else 0
                })
        
        if info['sources']:
            stats['symbols'].append(info)
    
    return stats


def clear_cache(clear_files=True):
    """
    清空所有缓存
    
    Args:
        clear_files: 是否同时清空本地缓存文件，默认 True
    """
    global _DATA_CACHE
    _DATA_CACHE = {}
    
    if clear_files:
        # 删除所有缓存文件
        for cache_file in CACHE_DIR.glob("*.pkl"):
            try:
                cache_file.unlink()
            except Exception as e:
                print(f"删除缓存文件失败 {cache_file}: {e}")
        print("已清空所有缓存（内存+文件）")
    else:
        print("已清空内存缓存")
