

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
    volume_minmax = [0.75, 1.5]
    rsi_minmax = [32, 68]
    rsi_delta = 5

    # Volume 爆量买入，缩量卖出
    volume_state = [False, False]
    if stock_data.get('estimated_volume') and stock_data.get('avg_volume') and stock_data['avg_volume'] > 0:
        volume_scale = stock_data['estimated_volume'] / stock_data['avg_volume']
        volume_state = [volume_scale >= volume_minmax[1], volume_scale <= volume_minmax[0]]
    
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

    if volume_state[0]: score[0] += 1
    if volume_state[1]: score[1] += 1

    if rsi_state[0] or rsi_prev_state[0]: score[0] += 1.0
    if rsi_state[1] or rsi_prev_state[1]: score[1] += 1.0
    if rsi_state[0] and rsi_prev_state[0]: score[0] += 0.6
    if rsi_state[1] and rsi_prev_state[1]: score[1] += 0.6

    if macd_state_strict[0]: score[0] += 1.0
    if macd_state_strict[1]: score[1] += 1.0
    if macd_state_easy[0]: score[0] += 0.4
    if macd_state_easy[1]: score[1] += 0.4
    
    return score
