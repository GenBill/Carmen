"""
AI股票分析模块 - 使用DeepSeek进行股票技术分析
基于agent/log.txt中的指标分析模式，提供短线分析、建仓建议和买卖点
"""

import yfinance as yf
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from agent.deepseek import DeepSeekAPI

def calculate_technical_indicators(data: pd.DataFrame) -> Dict:
    """
    计算技术指标
    
    Args:
        data: 包含OHLCV数据的DataFrame
        
    Returns:
        dict: 包含各种技术指标的字典
    """
    indicators = {}
    
    # RSI计算
    def calculate_rsi(prices, period=14):
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    # MACD计算
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif, dea, macd
    
    # EMA计算
    def calculate_ema(prices, period):
        return prices.ewm(span=period, adjust=False).mean()
    
    # ATR计算
    def calculate_atr(high, low, close, period=14):
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        return true_range.rolling(period).mean()
    
    # 计算各种指标
    indicators['rsi_7'] = calculate_rsi(data['Close'], 7)
    indicators['rsi_14'] = calculate_rsi(data['Close'], 14)
    
    dif, dea, macd = calculate_macd(data['Close'])
    indicators['macd_dif'] = dif
    indicators['macd_dea'] = dea
    indicators['macd'] = macd
    
    indicators['ema_20'] = calculate_ema(data['Close'], 20)
    indicators['ema_50'] = calculate_ema(data['Close'], 50)
    indicators['ema_12'] = calculate_ema(data['Close'], 12)
    indicators['ema_144'] = calculate_ema(data['Close'], 144)
    
    indicators['atr_3'] = calculate_atr(data['High'], data['Low'], data['Close'], 3)
    indicators['atr_14'] = calculate_atr(data['High'], data['Low'], data['Close'], 14)
    
    # 成交量指标
    indicators['volume_avg'] = data['Volume'].rolling(20).mean()
    indicators['volume_ratio'] = data['Volume'] / indicators['volume_avg']
    
    return indicators


def get_stock_data(symbol: str, period_days: int = 30) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    获取股票数据（日K线和小时级数据）
    
    Args:
        symbol: 股票代码
        period_days: 获取数据的天数
        
    Returns:
        tuple: (日K线数据, 小时级数据)
    """
    # 获取日K线数据
    daily_data = yf.download(symbol, period=f"{period_days}d", interval="1d")
    
    # 获取小时级数据（最近7天）
    hourly_data = yf.download(symbol, period="7d", interval="1h")
    
    return daily_data, hourly_data


def call_deepseek_api(prompt: str) -> str:
    """
    调用DeepSeek API
    
    Args:
        prompt: 输入提示词
        
    Returns:
        str: API响应内容
    """
    deepseek = DeepSeekAPI(
        system_prompt = "你是一位专业的股票技术分析师.", 
        model_type = "deepseek-reasoner"
    )
    return deepseek(prompt)


def safe_get_value(series, default=None):
    """
    安全地从pandas Series获取最后一个值
    
    Args:
        series: pandas Series
        default: 默认值
        
    Returns:
        标量值或默认值
    """
    if series is None or len(series) == 0:
        return default
    
    value = series.iloc[-1]
    
    # 确保返回标量值
    if hasattr(value, 'item'):
        value = value.item()
    
    # 检查是否为NaN
    if pd.isna(value):
        return default
    
    return value


def format_analysis_data(symbol: str, daily_data: pd.DataFrame, hourly_data: pd.DataFrame, 
                        daily_indicators: Dict, hourly_indicators: Dict) -> str:
    """
    格式化分析数据为DeepSeek可理解的格式
    
    Args:
        symbol: 股票代码
        daily_data: 日K线数据
        hourly_data: 小时级数据
        daily_indicators: 日线技术指标
        hourly_indicators: 小时级技术指标
        
    Returns:
        str: 格式化的分析数据
    """
    # 获取当前价格和成交量（确保是标量）
    current_price = float(daily_data['Close'].iloc[-1].item())
    current_volume = int(daily_data['Volume'].iloc[-1].item())
    
    # 获取日线指标值（确保都是标量）
    latest_daily = {
        'price': current_price,
        'volume': current_volume,
        'rsi_7': safe_get_value(daily_indicators['rsi_7']),
        'rsi_14': safe_get_value(daily_indicators['rsi_14']),
        'macd_dif': safe_get_value(daily_indicators['macd_dif']),
        'macd_dea': safe_get_value(daily_indicators['macd_dea']),
        'macd': safe_get_value(daily_indicators['macd']),
        'ema_20': safe_get_value(daily_indicators['ema_20']),
        'ema_50': safe_get_value(daily_indicators['ema_50']),
        'atr_14': safe_get_value(daily_indicators['atr_14']),
        'volume_ratio': safe_get_value(daily_indicators['volume_ratio']),
    }
    
    # 获取小时级数据
    if hourly_data is not None and not hourly_data.empty and hourly_indicators:
        latest_hourly = {
            'price': float(hourly_data['Close'].iloc[-1].item()),
            'rsi_7': safe_get_value(hourly_indicators['rsi_7']),
            'macd': safe_get_value(hourly_indicators['macd']),
            'ema_20': safe_get_value(hourly_indicators['ema_20']),
        }
    else:
        latest_hourly = {
            'price': current_price,
            'rsi_7': None,
            'macd': None,
            'ema_20': None,
        }
    
    # 获取最近的价格序列（确保是列表）
    recent_prices = [float(x) for x in daily_data['Close'].tail(14).values]
    recent_volumes = [int(x) for x in daily_data['Volume'].tail(14).values]
    
    # 格式化数值显示
    def format_value(value, format_str=".2f"):
        if value is None:
            return 'N/A'
        return f"{value:{format_str}}"
    
    analysis_text = f"""
股票代码: {symbol}
当前价格: ${current_price:.2f}
当前成交量: {current_volume:,}

=== 日线技术指标 ===
RSI(7): {format_value(latest_daily['rsi_7'])}
RSI(14): {format_value(latest_daily['rsi_14'])}
MACD DIF: {format_value(latest_daily['macd_dif'])}
MACD DEA: {format_value(latest_daily['macd_dea'])}
MACD: {format_value(latest_daily['macd'])}
EMA(20): {format_value(latest_daily['ema_20'])}
EMA(50): {format_value(latest_daily['ema_50'])}
ATR(14): {format_value(latest_daily['atr_14'])}
成交量比率: {format_value(latest_daily['volume_ratio'])}

=== 小时级技术指标 ===
当前价格: ${latest_hourly['price']:.2f}
RSI(7): {format_value(latest_hourly['rsi_7'])}
MACD: {format_value(latest_hourly['macd'])}
EMA(20): {format_value(latest_hourly['ema_20'])}

=== 最近价格趋势 ===
最近14天收盘价: {[f"${p:.2f}" for p in recent_prices]}
最近14天成交量: {[f"{v:,}" for v in recent_volumes]}

=== 趋势分析 ===
"""
    
    # 添加趋势分析
    if len(recent_prices) >= 5:
        price_change = (recent_prices[-1] - recent_prices[-5]) / recent_prices[-5] * 100
        analysis_text += f"5日价格变化: {price_change:+.2f}%\n"
    
    if latest_daily['ema_20'] is not None and latest_daily['ema_50'] is not None:
        if latest_daily['ema_20'] > latest_daily['ema_50']:
            analysis_text += "EMA(20) > EMA(50): 短期趋势向上\n"
        else:
            analysis_text += "EMA(20) < EMA(50): 短期趋势向下\n"
    
    if latest_daily['rsi_7'] is not None:
        if latest_daily['rsi_7'] > 70:
            analysis_text += "RSI(7) > 70: 可能超买\n"
        elif latest_daily['rsi_7'] < 30:
            analysis_text += "RSI(7) < 30: 可能超卖\n"
        else:
            analysis_text += "RSI(7) 在正常区间\n"
    
    if latest_daily['macd'] is not None:
        if latest_daily['macd'] > 0:
            analysis_text += "MACD > 0: 多头信号\n"
        else:
            analysis_text += "MACD < 0: 空头信号\n"
    
    return analysis_text


def analyze_stock_with_ai(symbol: str, period_days: int = 30) -> str:
    """
    使用AI分析股票，提供短线分析、建仓建议和买卖点
    
    Args:
        symbol: 股票代码
        period_days: 分析数据的天数
        
    Returns:
        str: AI分析结果
    """
    print(f"🔍 开始分析股票: {symbol}")
    
    # 1. 获取股票数据
    daily_data, hourly_data = get_stock_data(symbol, period_days)
    
    if daily_data is None or daily_data.empty:
        return f"❌ 无法获取 {symbol} 的股票数据"
    
    print(f"✅ 成功获取 {symbol} 数据: 日线{len(daily_data)}条, 小时线{len(hourly_data) if hourly_data is not None else 0}条")
    
    # 2. 计算技术指标
    print("📊 计算技术指标...")
    daily_indicators = calculate_technical_indicators(daily_data)
    hourly_indicators = calculate_technical_indicators(hourly_data) if hourly_data is not None and not hourly_data.empty else {}
    print("✅ 技术指标计算完成")
    
    # 3. 格式化分析数据
    print("📝 格式化分析数据...")
    analysis_data = format_analysis_data(symbol, daily_data, hourly_data, daily_indicators, hourly_indicators)
    print("✅ 数据格式化完成")
    
    # 4. 获取当前时间信息
    now_utc = datetime.utcnow()
    # 转换为美东时间（美股交易时间）
    from datetime import timezone, timedelta
    et_tz = timezone(timedelta(hours=-5))  # 美东标准时间 (EST)
    now_et = now_utc.astimezone(et_tz)
    
    # 格式化时间信息
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_cn = weekday_names[now_et.weekday()]
    
    time_info = f"""
=== 当前市场时间信息 ===
UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC
美东时间: {now_et.strftime('%Y-%m-%d %H:%M:%S')} ET
当前时间: {weekday_cn} ({now_et.strftime('%A')})
"""

    # 5. 构建AI分析提示词
    prompt = f"""
你是一位专业的股票技术分析师，请基于以下技术指标数据和当前市场时间，对美股进行深度分析：

{time_info}

{analysis_data}

请提供以下分析内容：

1. **短线技术分析**：
   - 当前技术面强弱评估
   - 主要技术指标解读
   - 短期趋势判断
   - 结合当前时间（周几、交易时段）的技术面分析

2. **建仓建议**：
   - 是否适合建仓（买入/卖出/观望）
   - 建仓时机建议（考虑当前是周几，是否接近周末等）
   - 风险等级评估

3. **买卖点建议**：
   - 具体买入价格区间
   - 具体卖出价格区间
   - 止损位建议
   - 止盈位建议

4. **时间因素考虑**：
   - 当前时间对美股交易的影响
   - 周几对市场情绪和流动性的影响
   - 是否接近周末或重要时间节点的建议

5. **风险提示**：
   - 主要风险因素
   - 注意事项

请用专业、简洁的语言进行分析，重点关注技术指标的信号强度和可靠性，并充分考虑当前时间因素对美股交易的影响。
"""
    
    # 5. 调用DeepSeek API
    print(f"🤖 调用DeepSeek AI进行分析...")
    ai_response = call_deepseek_api(prompt)
    
    return ai_response


def main(symbol):
    """
    主函数 - 示例用法
    """
    result = analyze_stock_with_ai(symbol)  # 使用agent/deepseek.py中的DeepSeekAPI
    print(f"\n=== {symbol} AI分析结果 ===")
    print(result)


if __name__ == "__main__":
    
    main('SERV')
