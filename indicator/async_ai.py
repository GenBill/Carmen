import traceback

def process_ai_task(symbol, market, qq_notifier, price, score, backtest_str, rsi, volume_ratio):
    """
    后台执行AI分析并发送通知
    """
    try:
        from analysis import analyze_stock_with_ai, refine_ai_analysis
        
        # 1. 执行AI分析
        ai_analysis = analyze_stock_with_ai(symbol, market=market)
        
        # 2. 提炼信息
        refined_info = refine_ai_analysis(ai_analysis, market=market)
        
        # 3. 发送QQ通知
        if qq_notifier:
            qq_notifier.send_buy_signal(
                symbol=symbol,
                price=price,
                score=score,
                backtest_str=backtest_str,
                rsi=rsi,
                volume_ratio=volume_ratio,
                min_buy_price=refined_info.get('min_buy_price'),
                max_buy_price=refined_info.get('max_buy_price'),
                buy_time=refined_info.get('buy_time'),
                target_price=refined_info.get('target_price'),
                stop_loss=refined_info.get('stop_loss'),
                ai_win_rate=refined_info.get('win_rate'),
                refined_text=refined_info.get('refined_text')
            )
            
        return ai_analysis, refined_info
        
    except Exception as e:
        print(f"⚠️ {symbol} 后台AI任务失败: {e}")
        # traceback.print_exc()
        return None, {}

