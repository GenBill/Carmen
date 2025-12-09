import time
import os
import pickle
import yfinance as yf
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta

# 长期数据缓存目录（5年历史数据，1天有效期）
LONGTERM_CACHE_DIR = os.path.join(os.path.dirname(__file__), '.cache_5y')


def _get_expected_latest_trading_date_for_symbol(symbol):
    """
    根据股票代码判断市场，计算预期的最新交易日
    
    Args:
        symbol: 股票代码 (如 AAPL, 0700.HK, 000001.SZ)
    
    Returns:
        date: 预期的最新交易日日期
    """
    # 根据后缀判断市场和时区
    if '.HK' in symbol or '.SZ' in symbol or '.SS' in symbol:
        # 港股/A股：使用北京时间
        tz = pytz.timezone('Asia/Shanghai')
        market_close_hour = 15  # 15:00 收盘
    else:
        # 美股：使用美东时间
        tz = pytz.timezone('America/New_York')
        market_close_hour = 16  # 16:00 收盘
    
    now = datetime.now(tz)
    current_date = now.date()
    is_weekday = now.weekday() < 5
    
    if is_weekday and now.hour >= market_close_hour:
        # 交易日已收盘 → 数据应该是今天
        return current_date
    else:
        # 盘前或周末 → 数据应该是上一个交易日
        check_date = current_date - timedelta(days=1)
        while check_date.weekday() >= 5:  # 跳过周末
            check_date -= timedelta(days=1)
        return check_date


def _load_longterm_cache(symbol):
    """
    加载长期数据缓存（智能检查：文件24小时内有效 + 数据日期必须是最新交易日）
    """
    cache_path = os.path.join(LONGTERM_CACHE_DIR, f"{symbol}.pkl")
    if os.path.exists(cache_path):
        file_mtime = os.path.getmtime(cache_path)
        if time.time() - file_mtime < 86400:  # 24小时内的文件
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                
                # 【关键修复】检查数据日期是否是最新交易日
                if data is not None and not data.empty:
                    last_data_date = data.index[-1]
                    if hasattr(last_data_date, 'date'):
                        last_data_date = last_data_date.date()
                    elif hasattr(last_data_date, 'to_pydatetime'):
                        last_data_date = last_data_date.to_pydatetime().date()
                    
                    expected_date = _get_expected_latest_trading_date_for_symbol(symbol)
                    
                    if last_data_date >= expected_date:
                        return data
                    # 数据日期不是最新交易日，返回 None 强制刷新
                    return None
            except:
                pass
    return None


def _save_longterm_cache(symbol, data):
    """保存长期数据缓存"""
    os.makedirs(LONGTERM_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(LONGTERM_CACHE_DIR, f"{symbol}.pkl")
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump(data, f)
    except:
        pass

def carmen_indicator(stock_data):
    """
    Carmen 综合指标评分系统
    
    Args:
        stock_data: 包含股票数据的字典
        
    Returns:
        list: [买入分数, 卖出分数]
    """
    if not stock_data:
        return [0, 0]
    
    # state[0] Buy, state[1] Sell
    volume_minmax = [0.6, 2.0]
    rsi_minmax = [35, 65]
    rsi_delta = 5

    # 涨跌 Flag，过滤掉爆量下跌的垃圾股
    # red_flag = stock_data.get('close', 0) > stock_data.get('open', 0)

    # Volume 爆量买入，缩量卖出
    volume_state = [False, False]
    volume_state_scale = [0.0, 0.0]
    if stock_data.get('estimated_volume') and stock_data.get('avg_volume') and stock_data['avg_volume'] > 0:
        volume_scale = stock_data['estimated_volume'] / stock_data['avg_volume']
        volume_state = [volume_scale >= volume_minmax[1], volume_scale <= volume_minmax[0]]
        volume_state_scale = [volume_scale / volume_minmax[1], volume_scale / volume_minmax[0]]
    
    # RSI 超卖买入，超买卖出
    rsi_state = [False, False]
    if stock_data['rsi'] != None:
        rsi_state = [stock_data['rsi'] <= rsi_minmax[0], stock_data['rsi'] >= rsi_minmax[1]]
    
    # RSI 反转买入/卖出
    rsi_prev_state = [False, False]
    if stock_data['rsi'] != None and stock_data['rsi_prev'] != None:
        rsi_prev_state = [
            stock_data['rsi_prev'] + rsi_delta < stock_data['rsi']
            and stock_data['rsi_prev'] <= rsi_minmax[0],  # 反转上涨
            stock_data['rsi_prev'] - rsi_delta > stock_data['rsi']
            and stock_data['rsi_prev'] >= rsi_minmax[1],  # 反转下跌
        ]
    
    # MACD 金叉买入，死叉卖出
    macd_state_strict = [False, False]
    if (stock_data['dif'] != None and stock_data['dif_dea_slope'] != None and stock_data['dea'] != None):
        macd_state_strict[0] = (
            stock_data['dif'] > 0
            and stock_data['dif_dea_slope'] > 0
            and stock_data['dif'] < stock_data['dea']
            and stock_data['dif'] + 2*stock_data['dif_dea_slope'] > stock_data['dea']
        )
        macd_state_strict[1] = (
            stock_data['dif'] < 0
            and stock_data['dif_dea_slope'] < 0
            and stock_data['dif'] < stock_data['dea']
            and stock_data['dif'] + 2*stock_data['dif_dea_slope'] < stock_data['dea']
        )
    
    macd_state_easy = [False, False]
    if (stock_data['dif'] != None and stock_data['dif_dea_slope'] != None and stock_data['dea'] != None):
        macd_state_easy[0] = (
            stock_data['dif'] > 0
            and stock_data['dif_dea_slope'] > 0
            and stock_data['dif'] + 2*stock_data['dif_dea_slope'] > stock_data['dea']
        )
        macd_state_easy[1] = (
            stock_data['dif'] < 0
            and stock_data['dif_dea_slope'] < 0
            and stock_data['dif'] + 2*stock_data['dif_dea_slope'] < stock_data['dea']
        )


    score = [0, 0]
    vol_flag, rsi_flag, macd_flag = [0, 0], [0, 0], [0, 0]

    if volume_state[0]: 
        score[0] += 1
        vol_flag[0] = 1
        if volume_state_scale[0] > 1.5: score[0] += 0.2
        if volume_state_scale[0] > 2.0: score[0] += 0.2
    
    if volume_state[1]: 
        score[1] += 1
        vol_flag[1] = 1
        if volume_state_scale[1] < 0.66: score[1] += 0.2
        if volume_state_scale[1] < 0.33: score[1] += 0.2

    if rsi_state[0] or rsi_prev_state[0]: 
        score[0] += 1.0
        rsi_flag[0] = 1
    if rsi_state[1] or rsi_prev_state[1]: 
        score[1] += 1.0
        rsi_flag[1] = 1
    
    if rsi_state[0] and rsi_prev_state[0]: score[0] += 0.6
    if rsi_state[1] and rsi_prev_state[1]: score[1] += 0.6
    if rsi_state[0] and macd_state_easy[0]: score[0] += 0.4
    if rsi_state[1] and macd_state_easy[1]: score[1] += 0.4

    if macd_state_strict[0]: score[0] += 1.0
    if macd_state_strict[1]: score[1] += 1.0
    if macd_state_strict[0] and macd_state_easy[0]: macd_flag[0] = 1
    if macd_state_easy[0]: score[0] += 0.4
    if macd_state_easy[1]: score[1] += 0.4
    if macd_state_strict[1] and macd_state_easy[1]: macd_flag[1] = 1

    # if not red_flag: score[0] = 0.0
    if vol_flag[0]+rsi_flag[0]+macd_flag[0] < 2.0: score[0] = 0.0
    if vol_flag[1]+rsi_flag[1]+macd_flag[1] < 2.0: score[1] = 0.0
    return score

def vegas_indicator(stock_data):
    """
    Vegas 综合指标评分系统
    基于12 EMA vs 144 EMA和收盘价位置的趋势判断
    
    Args:
        stock_data: 包含股票数据的字典
        
    Returns:
        list: [买入分数, 卖出分数]
    """
    if not stock_data:
        return [0, 0]
    
    # 检查必要的数据是否存在
    ema_12 = stock_data.get('ema_12')
    ema_144 = stock_data.get('ema_144')
    close_price = stock_data.get('close')
    
    if ema_12 is None or ema_144 is None or close_price is None:
        return [0, 0]

    score = [0.0, 0.0]  # [买入分数, 卖出分数]
    
    # 1. 12 EMA > 144 EMA 且 收盘 > 144 EMA - 强势牛市
    if ema_12 > ema_144 and close_price > ema_144:
        score[0] = 1.0  # 强势买入信号
    # 2. 12 EMA < 144 EMA 且 收盘 < 144 EMA - 强势熊市  
    if ema_12 < ema_144 and close_price < ema_144:
        score[1] = 1.0  # 强势卖出信号
    
    return score


def _calculate_historical_indicators(historical_data, rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8):
    """
    计算历史数据的技术指标（优化版本）
    
    Args:
        historical_data: 历史数据DataFrame
        rsi_period: RSI周期
        macd_fast: MACD快线周期
        macd_slow: MACD慢线周期
        macd_signal: MACD信号线周期
        avg_volume_days: 平均成交量天数
        
    Returns:
        dict: 包含所有技术指标的字典
    """
    
    
    # 计算RSI
    delta = historical_data['Close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi_series = 100 - (100 / (1 + rs))
    
    # 计算MACD
    exp1 = historical_data['Close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = historical_data['Close'].ewm(span=macd_slow, adjust=False).mean()
    dif_series = exp1 - exp2
    dea_series = dif_series.ewm(span=macd_signal, adjust=False).mean()
    
    # 计算MACD斜率
    dif_dea_slope_series = dif_series.diff() - dea_series.diff()
    
    # 计算成交量比率
    volume_series = historical_data['Volume']
    avg_volume_series = volume_series.rolling(window=avg_volume_days, min_periods=1).mean()
    
    return {
        'rsi': rsi_series,
        'dif': dif_series,
        'dea': dea_series,
        'dif_dea_slope': dif_dea_slope_series,
        'volume': volume_series,
        'avg_volume': avg_volume_series,
        'close': historical_data['Close']
    }


def _get_historical_data_with_cache(symbol):
    """
    获取历史数据（智能缓存策略）
    
    解决缓存矛盾：
    - 实时指标：需要最新1-2天数据（短期缓存）
    - 回测分析：需要2-5年历史数据（长期缓存）
    
    Args:
        symbol: 股票代码
        
    Returns:
        DataFrame: 历史数据，失败返回None
    """
    
    try:
        # 检查长期数据缓存（1天内有效）
        longterm_cached = _load_longterm_cache(symbol)
        if longterm_cached is not None and not longterm_cached.empty:
            return longterm_cached

        # 缓存不可用，下载新的历史数据
        # print(f"📥 下载 {symbol} 历史数据 (5年, 目标>1000天)...")

        max_retries = 3
        base_delay = 0.5
        historical_data = pd.DataFrame()
        
        for attempt in range(max_retries):
            try:
                # 使用 yf.download 替代 stock.history，支持 progress=False 直接屏蔽输出
                # auto_adjust=False 保持与 stock.history() 默认行为一致
                historical_data = yf.download(symbol, period="5y", progress=False, auto_adjust=False)
                
                if not historical_data.empty:
                    break
                elif attempt == max_retries - 1:
                    # 最后一次尝试仍为空，不抛异常，让后面逻辑处理
                    pass
                else:
                    # 空数据重试
                    raise ValueError("Empty data returned")
                    
            except Exception as api_error:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    # print(f"⚠️ {symbol} 下载历史数据失败 (尝试 {attempt + 1}/{max_retries}): {api_error}，{delay}秒后重试...")
                    time.sleep(delay)
                else:
                    print(f"❌ {symbol} 下载历史数据最终失败: {api_error}")
        
        # 处理可能的双层列索引（单只股票时 yf.download 可能返回多层索引）
        if not historical_data.empty and isinstance(historical_data.columns, pd.MultiIndex):
            historical_data.columns = historical_data.columns.droplevel(1)
        
        if not historical_data.empty:
            # 保存到长期缓存
            _save_longterm_cache(symbol, historical_data)
            return historical_data
        
        print(f"❌ {symbol} 无法获取历史数据")
        return None
        
    except Exception as e:
        print(f"❌ 获取 {symbol} 历史数据失败: {e}")
        return None


def backtest_carmen_indicator(symbol, score, stock_data, historical_data=None, gate=2.0,
                             rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8):
    """
    对Carmen指标进行回测，统计相似点第二天第三天连续上涨概率（优化版本）
    
    Args:
        symbol: 股票代码
        score: 当前Carmen指标分数 [买入分数, 卖出分数]
        stock_data: 当前股票数据
        historical_data: 历史数据DataFrame，如果为None则自动获取
        gate: 回测阈值，默认2.0
        rsi_period: RSI周期，默认8
        macd_fast: MACD快线周期，默认8
        macd_slow: MACD慢线周期，默认17
        macd_signal: MACD信号线周期，默认9
        avg_volume_days: 平均成交量天数，默认8
        
    Returns:
        dict: 包含回测结果的字典，格式为 {'buy_prob': (成功次数, 总次数), 'sell_prob': (成功次数, 总次数)}
              如果未找到相似点或未进行回测，返回None
    """
    # 只有当score >= gate时才进行回测
    if score[0] < gate and score[1] < gate:
        return None
    
    # 获取历史数据
    if historical_data is None:
        historical_data = _get_historical_data_with_cache(symbol)
        if historical_data is None:
            return None
    
    # 需要足够的历史数据
    if len(historical_data) < 50:
        return None
    
    try:
        # 计算历史技术指标
        indicators = _calculate_historical_indicators(
            historical_data, rsi_period, macd_fast, macd_slow, macd_signal, avg_volume_days
        )
        
        # 统计相似点和成功情况
        buy_similar_count = 0
        sell_similar_count = 0
        buy_success_count = 0
        sell_success_count = 0
        
        # 批量处理历史数据
        
        for i in range(max(14, macd_slow + macd_signal), len(historical_data) - 3):
            # 构建历史股票数据
            hist_stock_data = {
                'estimated_volume': indicators['volume'].iloc[i],
                'avg_volume': indicators['avg_volume'].iloc[i],
                'rsi': indicators['rsi'].iloc[i] if not pd.isna(indicators['rsi'].iloc[i]) else None,
                'rsi_prev': indicators['rsi'].iloc[i-1] if i > 0 and not pd.isna(indicators['rsi'].iloc[i-1]) else None,
                'dif': indicators['dif'].iloc[i] if not pd.isna(indicators['dif'].iloc[i]) else None,
                'dea': indicators['dea'].iloc[i] if not pd.isna(indicators['dea'].iloc[i]) else None,
                'dif_dea_slope': indicators['dif_dea_slope'].iloc[i] if not pd.isna(indicators['dif_dea_slope'].iloc[i]) else None,
                'close': indicators['close'].iloc[i]
            }
            
            # 计算历史Carmen指标
            hist_score = carmen_indicator(hist_stock_data)
            
            # 检查是否是相似点
            is_buy_similar = (hist_score[0] >= gate)
            is_sell_similar = (hist_score[1] >= gate)
            
            if is_buy_similar or is_sell_similar:
                
                day1_close = historical_data['Close'].iloc[i]
                day2_close = historical_data['Close'].iloc[i+1]
                day3_close = historical_data['Close'].iloc[i+2]
                
                if is_buy_similar:
                    is_success = (day2_close > day1_close or day3_close > day1_close)
                    buy_similar_count += 1
                    if is_success:
                        buy_success_count += 1
                
                if is_sell_similar:
                    is_success = (day2_close < day1_close or day3_close < day1_close)
                    sell_similar_count += 1
                    if is_success:
                        sell_success_count += 1
        
        # 构建结果
        result = {}
        if buy_similar_count > 0:
            result['buy_prob'] = (buy_success_count, buy_similar_count)
        if sell_similar_count > 0:
            result['sell_prob'] = (sell_success_count, sell_similar_count)
        
        return result if result else None
        
    except Exception as e:
        print(f"回测 {symbol} 时出错: {e}")
        return None