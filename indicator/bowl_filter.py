import pandas as pd
import numpy as np

def EMA(series, n):
    return series.ewm(span=n, adjust=False).mean()

def MA(series, n):
    return series.rolling(window=n).mean()

def bowl_rebound_indicator(stock_data):
    """
    碗口反弹策略 - 严格复刻 a-share-quant-selector 原版逻辑
    """
    # 1. 提取历史数据
    hist = stock_data.get('hist')
    if hist is None or len(hist) < 114:
        return 0.0

    # 数据预处理：原仓库通常使用倒序或正序，我们这里确保按时间升序处理以符合 rolling/ewm 计算
    df = hist.copy()
    if df.index[0] > df.index[-1]:
        df = df.iloc[::-1]

    # 定义基础序列 (小写对齐代码习惯)
    close = df['Close']
    open_p = df['Open']
    volume = df['Volume']
    high = df['High']
    low = df['Low']

    # --- 参数定义 (对齐 strategy/bowl_rebound.py 默认值) ---
    params = {
        'N': 4,              # 成交量倍数 (注意：README写2.4但代码里默认是4)
        'M': 15,             # 回溯天数
        'CAP': 400000000,    # 流通市值>40亿 (我们暂缺实时市值，默认为True或跳过)
        'J_VAL': 30,         # J值上限 (README写0但代码默认30)
        'duokong_pct': 3,    
        'short_pct': 2,      
        'M1': 14, 'M2': 28, 'M3': 57, 'M4': 114 # 多空线周期
    }

    # --- 指标计算 (完全对齐 utils/technical.py) ---
    
    # 1. 知行双线
    short_term_trend = EMA(EMA(close, 10), 10)
    bull_bear_line = (MA(close, params['M1']) + MA(close, params['M2']) + 
                      MA(close, params['M3']) + MA(close, params['M4'])) / 4
    
    # 2. KDJ (9, 3, 3) - 严格平滑法计算
    low_9 = low.rolling(window=9).min()
    high_9 = high.rolling(window=9).max()
    rsv = (close - low_9) / (high_9 - low_9) * 100
    # KDJ 采用 ewm alpha=1/3 (com=2)
    K = rsv.ewm(com=2, adjust=False).mean()
    D = K.ewm(com=2, adjust=False).mean()
    J = 3 * K - 2 * D

    # 3. 关键K线判断 (key_candle)
    vol_ratio = volume / volume.shift(1)
    vol_surge = vol_ratio >= params['N']
    positive_candle = close > open_p
    # 暂无 market_cap 字段时忽略市值过滤，或设为 True
    key_candle = vol_surge & positive_candle

    # --- 选股逻辑 (select_stocks) ---
    
    # 获取最新值
    L_close = close.iloc[-1]
    L_short = short_term_trend.iloc[-1]
    L_long = bull_bear_line.iloc[-1]
    L_J = J.iloc[-1]
    
    # 条件1：上升趋势 (trend_above)
    trend_above = L_short > L_long
    if not trend_above:
        return 0.0
    
    # 条件2：J值低位 (j_low)
    if L_J > params['J_VAL']:
        return 0.0
    
    # 条件3：异动条件 (abnormal) - M天内存在关键K线
    abnormal = key_candle.iloc[-params['M']:].any()
    if not abnormal:
        return 0.0

    # 条件4：分类标记位置 (必须满足其一)
    # 优先级1: 回落碗中
    fall_in_bowl = (L_close >= L_long) & (L_close <= L_short)
    
    # 优先级2: 靠近多空线
    dk_p = params['duokong_pct'] / 100
    near_duokong = (L_close >= L_long * (1 - dk_p)) & (L_close <= L_long * (1 + dk_p))
    
    # 优先级3: 靠近短期趋势线
    st_p = params['short_pct'] / 100
    near_short_trend = (L_close >= L_short * (1 - st_p)) & (L_close <= L_short * (1 + st_p))

    # 汇总评分
    score = 0.0
    if trend_above and abnormal and (L_J <= params['J_VAL']):
        if fall_in_bowl:
            score = 1.0  # 完美入碗
        elif near_duokong:
            score = 0.8  # 支撑位
        elif near_short_trend:
            score = 0.7  # 趋势位
            
    return round(score, 2)
