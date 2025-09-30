from datetime import datetime, time
import pytz


def is_market_open():
    """
    判断美股市场是否开盘
    
    Returns:
        bool: True表示开盘中，False表示休市
    """
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    
    # 检查是否是周末
    if now_et.weekday() >= 5:  # 5=周六, 6=周日
        return False
    
    # 美股交易时间: 9:30 - 16:00 (美东时间)
    market_open = time(9, 30)
    market_close = time(16, 0)
    current_time = now_et.time()
    
    return market_open <= current_time < market_close


def get_market_status():
    """
    获取市场状态信息
    
    Returns:
        dict: 包含市场状态的详细信息
    """
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    
    is_open = is_market_open()
    
    status = {
        'is_open': is_open,
        'current_time_et': now_et.strftime('%Y-%m-%d %H:%M:%S %Z'),
        'day_of_week': now_et.strftime('%A'),
        'is_weekend': now_et.weekday() >= 5
    }
    
    if is_open:
        status['message'] = '🟢 美股盘中'
    elif now_et.weekday() >= 5:
        status['message'] = '⏸️  周末休市'
    else:
        current_time = now_et.time()
        if current_time < time(9, 30):
            status['message'] = '⏰ 盘前时段'
        else:
            status['message'] = '🌙 盘后时段'
    
    return status


def get_cache_expiry_for_premarket():
    """
    计算盘前/盘后缓存的过期时间（到当日开盘）
    
    Returns:
        int: 缓存有效期（分钟）
    """
    et_tz = pytz.timezone('America/New_York')
    now_et = datetime.now(et_tz)
    
    # 计算到下一个开盘时间的分钟数
    if now_et.weekday() >= 5:  # 周末
        # 到下周一9:30
        days_until_monday = 7 - now_et.weekday()
        target_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        target_time = target_time + pytz.timedelta(days=days_until_monday)
    else:
        current_time = now_et.time()
        if current_time < time(9, 30):
            # 今天盘前，到今天9:30
            target_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        else:
            # 盘后，到明天9:30
            target_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            target_time = target_time + pytz.timedelta(days=1)
    
    diff = target_time - now_et
    minutes = int(diff.total_seconds() / 60)
    
    return max(minutes, 60)  # 至少60分钟
