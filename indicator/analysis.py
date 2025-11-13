"""
AI股票分析模块 - 使用DeepSeek进行股票技术分析
基于agent/log.txt中的指标分析模式，提供短线分析、建仓建议和买卖点
"""
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from agent.deepseek import DeepSeekAPI

# 缓存配置
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'analysis_cache')
CACHE_EXPIRE_HOURS = 24  # 缓存过期时间（小时）

def ensure_cache_dir():
    """确保缓存目录存在"""
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_file_path(symbol: str) -> str:
    """获取缓存文件路径"""
    return os.path.join(CACHE_DIR, f"{symbol}_analysis.json")

def calculate_data_hash(symbol: str, daily_data: pd.DataFrame, hourly_data: pd.DataFrame) -> str:
    """计算数据哈希值，用于检测数据是否变化"""
    # 使用最新的价格和指标数据计算哈希
    latest_daily = {
        'price': float(daily_data['Close'].iloc[-1].item()) if not daily_data.empty else 0,
        'volume': int(daily_data['Volume'].iloc[-1].item()) if not daily_data.empty else 0,
    }
    
    latest_hourly = {}
    if hourly_data is not None and not hourly_data.empty:
        latest_hourly = {
            'price': float(hourly_data['Close'].iloc[-1].item()),
            'date': hourly_data.index[-1].strftime('%Y-%m-%d %H:%M')
        }
    
    data_str = f"{symbol}_{json.dumps(latest_daily, sort_keys=True)}_{json.dumps(latest_hourly, sort_keys=True)}"
    return hashlib.md5(data_str.encode()).hexdigest()

def load_analysis_cache(symbol: str) -> Optional[Dict]:
    """加载分析缓存"""
    try:
        cache_file = get_cache_file_path(symbol)
        if not os.path.exists(cache_file):
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # 检查缓存是否过期
        cache_time = datetime.fromisoformat(cache_data['timestamp'])
        if datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRE_HOURS):
            return None
        return cache_data
    
    except Exception as e:
        print(f"⚠️ 加载 {symbol} 分析缓存失败: {e}")
        return None

def save_analysis_cache(symbol: str, data_hash: str, analysis_result: str):
    """保存分析缓存"""
    try:
        ensure_cache_dir()
        cache_data = {
            'symbol': symbol,
            'data_hash': data_hash,
            'analysis': analysis_result,
            'timestamp': datetime.now().isoformat(),
            'cache_expire_hours': CACHE_EXPIRE_HOURS
        }
        
        cache_file = get_cache_file_path(symbol)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    except Exception as e:
        print(f"⚠️ 保存 {symbol} 分析缓存失败: {e}")

def clean_expired_cache():
    """清理过期的缓存文件"""
    try:
        ensure_cache_dir()
        current_time = datetime.now()
        cleaned_count = 0
        
        for filename in os.listdir(CACHE_DIR):
            if filename.endswith('_analysis.json'):
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    cache_time = datetime.fromisoformat(cache_data['timestamp'])
                    if current_time - cache_time > timedelta(hours=CACHE_EXPIRE_HOURS):
                        os.remove(file_path)
                        cleaned_count += 1
                        print(f"🗑️ 清理过期缓存: {filename}")
                
                except Exception as e:
                    print(f"⚠️ 清理缓存文件失败 {filename}: {e}")
        
        if cleaned_count > 0:
            print(f"✅ 已清理 {cleaned_count} 个过期缓存文件")
    
    except Exception as e:
        print(f"⚠️ 清理缓存目录失败: {e}")

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


def get_stock_data(symbol: str, period_days: int = 250) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    获取股票数据（日K线和小时级数据）
    
    Args:
        symbol: 股票代码
        period_days: 获取数据的天数
        
    Returns:
        tuple: (日K线数据, 小时级数据)
    """
    # 获取日K线数据
    daily_data = yf.download(symbol, period=f"{period_days}d", interval="1d", auto_adjust=True, progress=False)
    
    # 获取小时级数据（最近30天）
    hourly_data = yf.download(symbol, period="30d", interval="1h", auto_adjust=True, progress=False)
    
    return daily_data, hourly_data


def call_deepseek_api_US(prompt: str) -> str:
    deepseek = DeepSeekAPI(
        system_prompt = """你是一位专业的股票技术分析师。
        用户通过成交量、RSI、MACD情况筛选出了一些短线操作机会。
        用户通常会在信号触发后的夜盘/盘前买入，并在下一个盘中时段卖出。特殊情况下，用户会额外持有2-3天。
        用户对于此类投机仓位不会超过5%，风险在可控范围内。
        你的任务是基于用户提供的数据，判断该短线操作机会的成功率，并给出买入/卖出、止盈/止损的价格区间。
        并提醒用户：什么情况下可以继续看涨并继续持有？或是当日卖出止盈？
        """, 
        model_type = "deepseek-reasoner"
    )
    return deepseek(prompt)

def call_deepseek_api_HKA(prompt: str) -> str:
    deepseek = DeepSeekAPI(
        system_prompt = """你是一位专业的股票技术分析师。
        用户通过成交量、RSI、MACD情况筛选出了一些短线操作机会。
        用户通常会在信号触发后的第二天买入，并在下一天卖出。特殊情况下，用户会额外持有2-3天。
        用户对于此类投机仓位不会超过5%，风险在可控范围内。
        你的任务是基于用户提供的数据，判断该短线操作机会的成功率，并给出买入/卖出、止盈/止损的价格区间。
        并提醒用户：什么情况下可以继续看涨并继续持有？或是当日卖出止盈？
        """, 
        model_type = "deepseek-reasoner"
    )
    return deepseek(prompt)

def call_deepseek_api(prompt: str, market: str = "US") -> str:
    """
    调用DeepSeek API分析股票
    
    Args:
        prompt: AI分析提示词
        market: 市场类型（"US"或"HKA"）
        
    Returns:
        str: AI分析结果
    """
    if market == "US":
        return call_deepseek_api_US(prompt)
    elif market == "HKA":
        return call_deepseek_api_HKA(prompt)
    else:
        raise ValueError(f"Invalid market: {market}. Must be 'US' or 'HKA'")


def refine_ai_analysis(ai_output: str, market: str = "US") -> dict:
    """
    将AI分析结果再喂给AI进行提炼，提取关键信息
    
    Args:
        ai_output: AI的原始分析结果
        market: 市场类型（"US"或"HKA"）
        
    Returns:
        dict: 包含提炼后的信息，格式为 {
            'max_buy_price': float or None,  # 最高买入价
            'win_rate': float or None,  # 胜率（0-1之间）
            'refined_text': str  # 提炼后的文本
        }
    """
    # 构建提炼提示词
    refine_prompt = f"""
请从以下股票分析报告中，提炼出最关键的信息，并以简洁的格式输出：

{ai_output}

请提取以下信息：
1. **最高买入价**：从分析中找出建议的最高买入价格（如果有多个价格区间，取上限）
2. **预估胜率**：从分析中找出预估的短线胜率（如果是百分比，转换为0-1之间的小数）

请以以下格式输出（每行一个）：
最高买入价: [价格]
预估胜率: [0-1之间的小数]

然后简要总结关键信息（不超过3句话）。
"""
    
    # 调用简易AI进行提炼（使用chat模型，更快更便宜）
    try:
        deepseek = DeepSeekAPI(
            system_prompt="你是一个信息提炼助手，擅长从长文本中提取关键信息。",
            model_type="deepseek-chat"  # 使用chat模型，更快
        )
        refined_output = deepseek(refine_prompt)
        
        # 解析提炼后的信息
        import re
        max_buy_price = None
        win_rate = None
        
        # 提取最高买入价 - 更精确的正则表达式
        price_patterns = [
            r'最高买入价[：:]\s*\$?([\d.]+)',  # 最高买入价: $123.45 或 最高买入价: 123.45
            r'买入价[：:]\s*\$?([\d.]+)',     # 买入价: $123.45
            r'最高.*?([\d.]+)\s*[元美元]',     # 最高123.45元
            r'建议.*?([\d.]+)\s*[元美元]',     # 建议123.45元
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    price = float(match.group(1))
                    if max_buy_price is None or price > max_buy_price:
                        max_buy_price = price
                except:
                    pass
        
        # 提取胜率 - 更精确的正则表达式
        rate_patterns = [
            r'胜率[：:]\s*([\d.]+)\s*%',      # 胜率: 65%
            r'胜率[：:]\s*([\d.]+)\s*$',      # 胜率: 0.65
            r'成功率[：:]\s*([\d.]+)\s*%',    # 成功率: 65%
            r'预估胜率[：:]\s*([\d.]+)\s*%',  # 预估胜率: 65%
            r'([\d.]+)\s*%.*?胜',             # 65%胜率
        ]
        
        for pattern in rate_patterns:
            match = re.search(pattern, refined_output, re.IGNORECASE)
            if match:
                try:
                    rate = float(match.group(1))
                    # 如果是百分比形式（>1），转换为小数
                    if rate > 1:
                        rate = rate / 100
                    # 确保在0-1之间
                    if 0 <= rate <= 1:
                        win_rate = rate
                        break
                except:
                    pass
        
        # 如果没有找到百分比形式，尝试找小数形式
        if win_rate is None:
            decimal_match = re.search(r'胜率[：:]\s*([01]\.\d+)', refined_output, re.IGNORECASE)
            if decimal_match:
                try:
                    win_rate = float(decimal_match.group(1))
                except:
                    pass
        
        return {
            'max_buy_price': max_buy_price,
            'win_rate': win_rate,
            'refined_text': refined_output
        }
    except Exception as e:
        print(f"⚠️  AI提炼失败: {e}")
        return {
            'max_buy_price': None,
            'win_rate': None,
            'refined_text': ''
        }

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
    recent_prices = daily_data['Close'].iloc[:, 0].tail(24).tolist()
    recent_volumes = daily_data['Volume'].iloc[:, 0].tail(24).tolist()
    
    daily_tail_long = 24
    hourly_tail_long = 24
    
    # 获取日线技术指标的24个数据点
    daily_rsi_7_series = daily_indicators['rsi_7'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_rsi_14_series = daily_indicators['rsi_14'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_macd_dif_series = daily_indicators['macd_dif'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_macd_dea_series = daily_indicators['macd_dea'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_macd_series = daily_indicators['macd'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_ema_20_series = daily_indicators['ema_20'].iloc[:, 0].tail(daily_tail_long).tolist()
    daily_ema_50_series = daily_indicators['ema_50'].iloc[:, 0].tail(daily_tail_long).tolist()
    
    # 获取小时级技术指标的24个数据点
    hourly_rsi_7_series = []
    hourly_macd_series = []
    hourly_ema_20_series = []
    
    if hourly_data is not None and not hourly_data.empty and hourly_indicators:
        hourly_rsi_7_series = hourly_indicators['rsi_7'].iloc[:, 0].tail(hourly_tail_long).tolist()
        hourly_macd_series = hourly_indicators['macd'].iloc[:, 0].tail(hourly_tail_long).tolist()
        hourly_ema_20_series = hourly_indicators['ema_20'].iloc[:, 0].tail(hourly_tail_long).tolist()
    
    # 格式化数值显示
    def format_value(value, format_str=".2f"):
        if value is None:
            return 'N/A'
        return f"{value:{format_str}}"
    
    def format_series(series, format_str=".2f"):
        """格式化数据序列"""
        if not series:
            return 'N/A'
        return [f"{v:{format_str}}" if v is not None and not pd.isna(v) else 'N/A' for v in series]
    
    analysis_text = f"""
股票代码: {symbol}
当前价格: ${current_price:.2f}
当前成交量: {current_volume:,}

=== 日线技术指标 ===
RSI(7) 最近{daily_tail_long}天: {format_series(daily_rsi_7_series)}
RSI(14) 最近{daily_tail_long}天: {format_series(daily_rsi_14_series)}
MACD DIF 最近{daily_tail_long}天: {format_series(daily_macd_dif_series)}
MACD DEA 最近{daily_tail_long}天: {format_series(daily_macd_dea_series)}
MACD 最近{daily_tail_long}天: {format_series(daily_macd_series)}
EMA(20) 最近{daily_tail_long}天: {format_series(daily_ema_20_series)}
EMA(50) 最近{daily_tail_long}天: {format_series(daily_ema_50_series)}
ATR(14): {format_value(latest_daily['atr_14'])}
成交量比率: {format_value(latest_daily['volume_ratio'])} （最后1日成交量 / 过去20日平均成交量）

=== 小时级技术指标 ===
当前价格: ${latest_hourly['price']:.2f}
RSI(7) 最近{hourly_tail_long}小时: {format_series(hourly_rsi_7_series)}
MACD 最近{hourly_tail_long}小时: {format_series(hourly_macd_series)}
EMA(20) 最近{hourly_tail_long}小时: {format_series(hourly_ema_20_series)}

=== 最近价格趋势 ===
最近{daily_tail_long}天收盘价: {[f"${p:.2f}" for p in recent_prices]}
最近{daily_tail_long}天成交量: {[f"{v:,}" for v in recent_volumes]}

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

def get_time_info(symbol: str) -> str:
    if symbol.endswith(".HK") or symbol.endswith(".SS") or symbol.endswith(".SZ"):
        now_hk = datetime.now(pytz.timezone('Asia/Hong_Kong'))
        time_info = f"""
        === 当前港A股交易时间 ===
        {now_hk.strftime('%Y-%m-%d %H:%M:%S')} {now_hk.tzname()} {now_hk.strftime('%A')}
        """
    else:
        now_et = datetime.now(pytz.timezone('US/Eastern'))
        time_info = f"""
        === 当前美股交易时间 ===
        {now_et.strftime('%Y-%m-%d %H:%M:%S')} {now_et.tzname()} {now_et.strftime('%A')}
        """
    return time_info

def get_stock_type(symbol: str) -> str:
    if symbol.endswith(".HK") or symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return "港A股"
    else:
        return "美股"

def analyze_stock_with_ai(symbol: str, period_days: int = 250, market: str = None) -> str:
    """
    使用AI分析股票，提供短线分析、建仓建议和买卖点
    
    Args:
        symbol: 股票代码
        period_days: 分析数据的天数
        market: 市场类型（"US"或"HKA"），None则自动识别
        
    Returns:
        str: AI分析结果
    """
    # 自动识别市场类型
    if market is None:
        if symbol.endswith('.HK') or symbol.endswith('.SS') or symbol.endswith('.SZ'):
            market = "HKA"
        else:
            market = "US"
    
    # 1. 获取股票数据
    daily_data, hourly_data = get_stock_data(symbol, period_days)
    
    if daily_data is None or daily_data.empty:
        return f"❌ 无法获取 {symbol} 的股票数据"
    
    # print(f"✅ 成功获取 {symbol} 数据: 日线{len(daily_data)}条, 小时线{len(hourly_data) if hourly_data is not None else 0}条")
    
    # 2. 计算数据哈希值
    data_hash = calculate_data_hash(symbol, daily_data, hourly_data)
    
    # 3. 检查缓存
    cache_data = load_analysis_cache(symbol)
    if cache_data and cache_data.get('data_hash') == data_hash:
        # print(f"🚀 {symbol} 使用缓存结果，跳过AI分析")
        return cache_data['analysis']
    
    # 2. 计算技术指标
    daily_indicators = calculate_technical_indicators(daily_data)
    hourly_indicators = calculate_technical_indicators(hourly_data) if hourly_data is not None and not hourly_data.empty else {}
    
    # 3. 格式化分析数据
    analysis_data = format_analysis_data(symbol, daily_data, hourly_data, daily_indicators, hourly_indicators)
    
    # 4. 获取当前美股时间信息
    now_utc = datetime.utcnow()
    # 转换为美东时间（美股交易时间）- 正确处理夏令时
    et_tz = pytz.timezone('US/Eastern')
    now_et = now_utc.replace(tzinfo=pytz.UTC).astimezone(et_tz)
    
    time_info = get_time_info(symbol)
    stock_type = get_stock_type(symbol)

    # 5. 构建AI分析提示词（根据市场类型）
    if market == "HKA":
        # 港A股市场的prompt
        market_instruction = """
请用专业、简洁的语言进行分析，重点关注技术指标的信号强度和可靠性。
注意港A股市场特点：交易时间为上午9:30-12:00，下午13:00-16:00（港股），请充分考虑市场时间和流动性特点。
"""
    else:
        # 美股市场的prompt
        market_instruction = """
请用专业、简洁的语言进行分析，重点关注技术指标的信号强度和可靠性，并充分考虑当前时间因素对美股交易的影响。
接口允许的话，你也可以适当检索一些新闻、政策、事件并分析其对美股交易的影响。
"""
    
    prompt = f"""
你是一位专业的股票技术分析师，请基于以下技术指标数据和当前市场时间，对{stock_type} {symbol} 进行深度分析：

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
   - 具体买入价格区间和时间
   - 具体卖出价格区间和时间
   - 止损位建议
   - 止盈位建议
   - 给出预估的短线胜率

4. **风险提示**：
   - 主要风险因素
   - 注意事项

{market_instruction}
"""
    
    # 5. 调用DeepSeek API（传入市场类型）
    ai_checkpoint = call_deepseek_api(prompt, market=market)

    # 6. 保存缓存
    save_analysis_cache(symbol, data_hash, ai_checkpoint)
    
    return ai_checkpoint


def main(symbol):
    """
    主函数 - 示例用法
    """
    result = analyze_stock_with_ai(symbol)  # 使用agent/deepseek.py中的DeepSeekAPI
    print(f"\n=== {symbol} AI分析结果 ===")
    print(result)


if __name__ == "__main__":
    
    import argparse
    
    # 获取命令行参数
    parser = argparse.ArgumentParser(description='股票分析')
    parser.add_argument('symbol', type=str, help='股票代码')
    args = parser.parse_args()
    symbol = args.symbol
    main(symbol)
