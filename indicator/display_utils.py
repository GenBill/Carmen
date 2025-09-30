"""
终端颜色和显示工具
"""

# ANSI颜色代码
class Colors:
    RED = '\033[91m'      # 红色（下跌）
    GREEN = '\033[92m'    # 绿色（上涨）
    YELLOW = '\033[93m'   # 黄色（警告）
    BLUE = '\033[94m'     # 蓝色
    MAGENTA = '\033[95m'  # 品红
    CYAN = '\033[96m'     # 青色
    WHITE = '\033[97m'    # 白色
    BOLD = '\033[1m'      # 粗体
    RESET = '\033[0m'     # 重置


def format_price_change(current_price, open_price):
    """
    格式化价格变化（红涨绿跌）- 固定显示宽度22字符
    
    Args:
        current_price: 当前价格
        open_price: 开盘价
        
    Returns:
        str: 格式化后的字符串（固定显示宽度）
    """
    if current_price is None or open_price is None or open_price == 0:
        return f"${current_price:.2f}".ljust(22) if current_price else "N/A".ljust(22)
    
    change = current_price - open_price
    change_pct = (change / open_price) * 100
    
    # 根据涨跌选择颜色
    if change_pct > 0:
        if change_pct > 0.2:
            color = Colors.RED
        else:
            color = Colors.WHITE
        sign = '+'
    elif change_pct < 0:
        if change_pct < -0.2:
            color = Colors.GREEN
        else:
            color = Colors.WHITE
        sign = '-'
        change_pct = abs(change_pct)
    else:
        color = Colors.WHITE
        sign = ' '
    
    # 格式化价格和涨幅
    price_str = f"${current_price:>7.2f}"
    pct_str = f"{sign}{change_pct:>5.2f}%"
    
    # 返回固定宽度：价格(9字符) + 空格 + 彩色涨幅(7字符显示) = 17字符显示 + 颜色代码
    return f"{price_str} {color}{pct_str}{Colors.RESET}"


def format_volume_ratio(estimated_volume, avg_volume):
    """
    格式化成交量比率 - 固定显示宽度7字符
    
    Args:
        estimated_volume: 估算成交量
        avg_volume: 平均成交量
        
    Returns:
        str: 格式化后的字符串（固定显示宽度）
    """
    if not estimated_volume or not avg_volume or avg_volume == 0:
        return "N/A".ljust(7)
    
    ratio = (estimated_volume / avg_volume) * 100
    
    # 根据量比选择颜色
    if ratio >= 160:  # 爆量
        color = Colors.RED + Colors.BOLD
    elif ratio >= 120:  # 放量
        color = Colors.RED
    elif ratio <= 80:  # 缩量
        color = Colors.GREEN
    else:  # 正常
        color = Colors.WHITE
    
    # 固定宽度：7字符显示（含%）
    ratio_str = f"{ratio:>6.1f}%"
    return f"{color}{ratio_str}{Colors.RESET}"


def format_rsi_trend(rsi_prev, rsi_current):
    """
    格式化RSI趋势（前日->当日）- 固定显示宽度15字符
    
    Args:
        rsi_prev: 前一日RSI
        rsi_current: 当日RSI
        
    Returns:
        str: 格式化后的字符串（固定显示宽度）
    """
    if rsi_prev is None or rsi_current is None:
        return "N/A".ljust(15)
    
    change = rsi_current - rsi_prev
    
    # 根据趋势选择颜色和箭头
    if change > 2:
        arrow = '↑'
        color = Colors.RED
    elif change < -2:
        arrow = '↓'
        color = Colors.GREEN
    else:
        arrow = '→'
        color = Colors.WHITE
    
    # 固定宽度：5.1f + 空格 + 箭头 + 空格 + 5.1f = 15字符显示
    prev_str = f"{rsi_prev:>5.1f}"
    curr_str = f"{rsi_current:>5.1f}"
    return f"{prev_str} {color}{arrow}{Colors.RESET}{curr_str}"


def format_macd_info(dif, dea, dif_dea_slope):
    """
    格式化MACD信息
    
    Args:
        dif: DIF值
        dea: DEA值
        dif_dea_slope: DIF-DEA斜率
        
    Returns:
        str: 格式化后的字符串
    """
    if dif is None or dea is None:
        return "N/A"
    
    # DIF颜色
    dif_color = Colors.RED if dif > 0 else Colors.GREEN
    
    # DEA颜色
    dea_color = Colors.RED if dea > 0 else Colors.GREEN
    
    dif_dea_slope = round(dif_dea_slope, 2)
    # 斜率颜色和符号
    if dif_dea_slope != None:
        if dif_dea_slope > 0:
            slope_color = Colors.RED
            slope_sign = '+'
        elif dif_dea_slope < 0:
            slope_color = Colors.GREEN
            slope_sign = ''
        else:
            slope_color = Colors.WHITE
            slope_sign = ''
        slope_str = f"{slope_color}{slope_sign}{dif_dea_slope:.2f}{Colors.RESET}"
    else:
        slope_str = "N/A"
    
    return f"DIF:{dif_color}{dif:>6.2f}{Colors.RESET} DEA:{dea_color}{dea:>6.2f}{Colors.RESET} 斜率: {slope_str}"


def is_data_valid(stock_data):
    """
    检查股票数据是否有效（关键指标不能为None或0）
    
    Args:
        stock_data: 股票数据字典
        
    Returns:
        bool: True表示数据有效
    """
    # 检查关键指标
    required_fields = ['close', 'open', 'rsi', 'rsi_prev', 'dif', 'dea', 'avg_volume', 'estimated_volume']
    
    for field in required_fields:
        value = stock_data.get(field)
        if value is None:
            return False
        # 检查成交量相关字段不为0
        if field in ['avg_volume', 'estimated_volume'] and value == 0:
            return False
    
    return True


def print_stock_info(stock_data, score):
    """
    打印单个股票的信息（简化版）
    只打印有效数据，跳过N/A
    
    Args:
        stock_data: 股票数据字典
        score: Carmen指标分数 [买入分数, 卖出分数]
        
    Returns:
        bool: True表示已打印，False表示数据无效已跳过
    """
    # 检查数据有效性
    if not is_data_valid(stock_data):
        return False
    
    symbol = stock_data['symbol']
    
    # 价格和涨幅
    price_info = format_price_change(stock_data.get('close'), stock_data.get('open'))
    
    # 成交量比率
    volume_ratio = format_volume_ratio(
        stock_data.get('estimated_volume'), 
        stock_data.get('avg_volume')
    )
    
    # RSI趋势
    rsi_trend = format_rsi_trend(
        stock_data.get('rsi_prev'),
        stock_data.get('rsi')
    )
    
    # MACD信息
    macd_info = format_macd_info(
        stock_data.get('dif'),
        stock_data.get('dea'),
        stock_data.get('dif_dea_slope')
    )
    
    # 信号指示
    signal = ""
    if score[0] >= 3:
        signal = f"{Colors.RED}{Colors.BOLD}[买入信号]{Colors.RESET}"
    elif score[1] >= 3:
        signal = f"{Colors.GREEN}{Colors.BOLD}[卖出信号]{Colors.RESET}"
    
    # 打印信息（所有字段固定宽度对齐）
    print(f"{symbol:6s} | {price_info} | 量比:{volume_ratio} | RSI8: {rsi_trend} | {macd_info} {signal}")
    return True


def print_header():
    """打印表头"""
    print(f"\n{'='*120}")
    print(f"{'股票':^5}|{'价格涨跌幅':^13}|{'量比':^12}|{'RSI8(前->今)':^18}|{'MACD指标':^34}|{'信号':^16}")
    print(f"{'='*120}")
