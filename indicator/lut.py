
from datetime import datetime, timedelta
import math

def interpolate_volume_lut(lut):
    """
    将给定的锚点LUT使用线性插值扩展到每1分钟一个时间点。
    
    Args:
        lut (dict): 键为'HH:MM'时间字符串，值为累计占比（0到1）。
    
    Returns:
        dict: 扩展后的LUT，键为'HH:MM'，值为插值后的累计占比。
    """
    # 解析锚点并转换为分钟数（从9:30开始）
    base_time = datetime.strptime('09:30', '%H:%M')
    anchors = []
    for time_str, value in sorted(lut.items()):
        time_obj = datetime.strptime(time_str, '%H:%M')
        minutes = int((time_obj - base_time).total_seconds() / 60)
        anchors.append((minutes, value))
    
    # 总交易时间：390分钟（9:30到16:00）
    total_minutes = 390
    interpolated = {}
    
    # 添加起始点（如果没有09:30）
    if anchors[0][0] != 0:
        anchors.insert(0, (0, 0.0))  # 假设开盘前为0
    
    # 添加结束点（16:00）
    if anchors[-1][0] != total_minutes:
        anchors.append((total_minutes, 1.0))
    
    # 线性插值
    for i in range(len(anchors) - 1):
        start_min, start_val = anchors[i]
        end_min, end_val = anchors[i + 1]
        duration = end_min - start_min
        
        for min_offset in range(duration + 1):
            current_min = start_min + min_offset
            if current_min > total_minutes:
                break
                
            # 线性插值：val = start_val + (end_val - start_val) * (offset / duration)
            frac = min_offset / duration if duration > 0 else 0
            val = start_val + (end_val - start_val) * frac
            
            # 转换回时间字符串
            current_time = base_time + timedelta(minutes=current_min)
            time_str = current_time.strftime('%H:%M')
            
            interpolated[time_str] = round(val, 4)  # 四舍五入到4位小数
    
    return interpolated

# 盘中成交量估算LUT表（美东时间）
# 键：交易时间（小时:分钟），值：预期该时间点的成交量占全天成交量的比例
_INTRADAY_VOLUME_LUT = {
    '09:30': 0.05,   # 开盘快速启动
    '10:00': 0.25, 
    '10:30': 0.32,   # 开盘1小时，约占1/3
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

_INTRADAY_VOLUME_LUT_HK = {
    '09:30': 0.05, 
    '10:00': 0.20, 
    '10:30': 0.40, 
    '11:00': 0.45, 
    '11:30': 0.50,
    '12:00': 0.65,
    '12:30': 0.65,
    '13:00': 0.65,
    '13:30': 0.70,
    '14:00': 0.75,
    '14:30': 0.80,
    '15:00': 0.85,
    '15:30': 0.90,
    '16:00': 1.00,
}

_INTRADAY_VOLUME_LUT_A = {
    '09:30': 0.05, 
    '10:00': 0.20, 
    '10:30': 0.40, 
    '11:00': 0.50, 
    '11:30': 0.65,
    '12:00': 0.65,
    '12:30': 0.65,
    '13:00': 0.65,
    '13:30': 0.80,
    '14:00': 0.85,
    '14:30': 0.90,
    '15:00': 1.00,
    '15:30': 1.00,
    '16:00': 1.00,
}

INTRADAY_VOLUME_LUT = interpolate_volume_lut(_INTRADAY_VOLUME_LUT)
INTRADAY_VOLUME_HK = interpolate_volume_lut(_INTRADAY_VOLUME_LUT_HK)
INTRADAY_VOLUME_A = interpolate_volume_lut(_INTRADAY_VOLUME_LUT_A)
