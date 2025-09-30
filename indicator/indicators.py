

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
    volume_minmax = [0.8, 1.6]
    rsi_minmax = [35, 65]
    rsi_delta = 5

    # Volume 爆量买入，缩量卖出
    volume_scale = stock_data['estimated_volume'] / stock_data['avg_volume']
    volume_state = [volume_scale >= volume_minmax[1], volume_scale <= volume_minmax[0]]
    
    # RSI8 超卖买入，超买卖出
    rsi_state = [False, False]
    if stock_data['rsi'] is not None:
        rsi_state = [stock_data['rsi'] <= rsi_minmax[0], stock_data['rsi'] >= rsi_minmax[1]]
    
    # RSI8 反转买入/卖出
    rsi_prev_state = [False, False]
    if stock_data['rsi'] is not None and stock_data['rsi_prev'] is not None:
        rsi_prev_state = [
            stock_data['rsi_prev'] + rsi_delta < stock_data['rsi'],  # 反转上涨
            stock_data['rsi_prev'] - rsi_delta > stock_data['rsi'],  # 反转下跌
        ]
    
    # MACD 金叉买入，死叉卖出
    macd_state = [False, False]
    if (stock_data['dif'] is not None and stock_data['dif_slope'] is not None 
        and stock_data['dea'] is not None):
        macd_state[0] = (stock_data['dif'] > 0 and stock_data['dif_slope'] > 0 
                        and stock_data['dif'] + stock_data['dif_slope'] > stock_data['dea'])
        macd_state[1] = (stock_data['dif'] < 0 and stock_data['dif_slope'] < 0 
                        and stock_data['dif'] + stock_data['dif_slope'] < stock_data['dea'])

    score = [0, 0]

    if volume_state[0]: score[0] += 1
    if volume_state[1]: score[1] += 1

    if rsi_state[0]: score[0] += 1
    if rsi_state[1]: score[1] += 1
    
    if rsi_prev_state[0]: score[0] += 1
    if rsi_prev_state[1]: score[1] += 1

    if macd_state[0]: score[0] += 1
    if macd_state[1]: score[1] += 1
    
    return score
