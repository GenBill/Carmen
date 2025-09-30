import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz
import os
import pickle
from pathlib import Path

# 缓存目录
CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

# 全局内存缓存：{symbol: (timestamp, hist_data)}
# 同时支持本地文件缓存，避免程序重启后重新获取数据
_DATA_CACHE = {}

# 盘中成交量估算LUT表（美东时间）
# 键：交易时间（小时:分钟），值：预期该时间点的成交量占全天成交量的比例
INTRADAY_VOLUME_LUT = {
    '09:30': 0.08,   # 开盘30分钟，快速启动
    '10:00': 0.25,   # 开盘1小时，约占1/3
    '10:30': 0.32,
    '11:00': 0.37,
    '11:30': 0.41,
    '12:00': 0.45,   # 中午前低谷
    '12:30': 0.48,
    '13:00': 0.52,
    '13:30': 0.56,
    '14:00': 0.60,   # 中间平稳
    '14:30': 0.68,
    '15:00': 0.78,   # 尾盘开始加速
    '15:30': 0.90,
    '16:00': 1.00,   # 收盘，约占尾盘1/3
}

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


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """
    计算 MACD 指标
    
    Args:
        prices: 价格序列（pandas Series）
        fast: 快线周期，默认 12
        slow: 慢线周期，默认 26
        signal: 信号线周期，默认 9
        
    Returns:
        dict: 包含 dif(macd), dea(signal), histogram, dif_slope 的字典
    """
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    dif = exp1 - exp2  # DIF线（快线-慢线）
    dea = dif.ewm(span=signal, adjust=False).mean()  # DEA线（DIF的信号线）
    histogram = dif - dea
    
    # 计算DIF斜率（当日DIF - 前一日DIF）
    dif_slope = None
    if len(dif) >= 2 and not pd.isna(dif.iloc[-1]) and not pd.isna(dif.iloc[-2]):
        dif_slope = round(dif.iloc[-1] - dif.iloc[-2], 2)
    
    return {
        'dif': round(dif.iloc[-1], 2) if not pd.isna(dif.iloc[-1]) else None,
        'dea': round(dea.iloc[-1], 2) if not pd.isna(dea.iloc[-1]) else None,
        'histogram': round(histogram.iloc[-1], 2) if not pd.isna(histogram.iloc[-1]) else None,
        'dif_slope': dif_slope
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


def estimate_full_day_volume(current_volume, trading_date_timestamp, volume_lut=None):
    """
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
    
    # 检查是否在交易时间内（9:30-16:00）
    current_hour = current_et_time.hour
    current_minute = current_et_time.minute
    current_time_minutes = current_hour * 60 + current_minute
    
    market_open = 9 * 60 + 30   # 9:30
    market_close = 16 * 60       # 16:00
    
    if current_time_minutes < market_open or current_time_minutes >= market_close:
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
        
    Returns:
        dict: 包含所有数据的字典，失败返回 None
    """
    try:
        # 检查缓存（先内存，后文件）
        now = datetime.now()
        cache_key = symbol
        hist = None
        cache_source = None
        
        # 1. 检查内存缓存
        if use_cache and cache_key in _DATA_CACHE:
            cached_time, cached_hist = _DATA_CACHE[cache_key]
            cache_age = (now - cached_time).total_seconds() / 60  # 转换为分钟
            
            if cache_age < cache_minutes:
                hist = cached_hist
                cache_source = "内存"
        
        # 2. 如果内存缓存失效，检查文件缓存
        if hist is None and use_cache:
            file_cache = _load_cache_from_file(symbol)
            if file_cache:
                cached_time, cached_hist = file_cache
                cache_age = (now - cached_time).total_seconds() / 60
                
                if cache_age < cache_minutes:
                    hist = cached_hist
                    cache_source = "文件"
                    # 加载到内存缓存
                    _DATA_CACHE[cache_key] = (cached_time, cached_hist)
        
        # 3. 如果没有缓存或缓存过期，从API获取
        if hist is None:
            stock = yf.Ticker(symbol)
            
            # 获取足够的历史数据以计算技术指标
            # 数据越多，EMA越稳定。API调用次数与数据长度无关，所以尽可能多获取
            # EMA需要足够的warmup期才能稳定，建议至少(慢线+信号线)*5 或 100天以上
            # 对于MACD(8,17,9)：(17+9)*5 = 130天
            # 对于MACD(12,26,9)：(26+9)*5 = 175天
            # 使用1y获取约250天数据，精度最佳且API消耗不变
            hist = stock.history(period="1y")
            cache_source = "API"
            
            # 更新缓存（内存+文件）
            if use_cache and not hist.empty:
                _DATA_CACHE[cache_key] = (now, hist)
                _save_cache_to_file(symbol, now, hist)
                # print(f"更新缓存: {symbol} (内存+文件)")
        
        # 显示缓存来源（调试用）
        # if cache_source:
        #     print(f"{symbol}: 数据来源 {cache_source}")
        
        if hist.empty or len(hist) < avg_volume_days + 1:
            return None
        
        # 获取最后一个交易日数据（当日或最近交易日）
        last_trading_day = hist.iloc[-1]
        trading_date_timestamp = hist.index[-1]  # 保留完整时间戳
        trading_date = trading_date_timestamp.strftime('%Y-%m-%d')
        
        # 计算过去 N 日平均成交量（明确排除当日，即最后一个交易日）
        # 例如：如果avg_volume_days=8，则计算倒数第2到倒数第9天（共8天）的平均成交量
        if len(hist) >= avg_volume_days + 1:
            avg_volume = hist.iloc[-(avg_volume_days+1):-1]['Volume'].mean()
        else:
            # 如果数据不足，使用所有可用的历史数据（排除当日）
            avg_volume = hist.iloc[:-1]['Volume'].mean()
        
        # 当日成交量（最后一个交易日）
        current_volume = last_trading_day['Volume']
        
        # 估算全天成交量（只在确认是当日盘中数据时才估算）
        estimated_volume = estimate_full_day_volume(current_volume, trading_date_timestamp, volume_lut=volume_lut)
        
        # 计算 RSI（获取完整序列以便提取前一日数据）
        rsi_series = calculate_rsi(hist['Close'], period=rsi_period, return_series=True)
        rsi = rsi_series.iloc[-1] if not pd.isna(rsi_series.iloc[-1]) else None
        rsi_prev = None
        if len(rsi_series) >= 2 and not pd.isna(rsi_series.iloc[-2]):
            rsi_prev = rsi_series.iloc[-2]
        
        # 计算 MACD
        macd_data = calculate_macd(hist['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
        
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
            'dif_slope': macd_data['dif_slope']
        }
    except Exception as e:
        print(f"获取 {symbol} 数据时出错: {e}")
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
                'data_points': len(hist) if hist is not None else 0
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
                    'data_points': len(hist) if hist is not None else 0
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
