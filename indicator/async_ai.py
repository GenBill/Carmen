import traceback


def process_ai_task(
    symbol,
    market,
    qq_notifier,
    price,
    score,
    backtest_str,
    rsi,
    volume_ratio,
    bowl_score=None,
    volume_ma_info=None,
    turnover_rate=None,
    turnover_warning=None,
):
    """
    后台执行统一 AI 链路 build_or_load_ai_result，返回完整 ai result dict（单对象，非二元组）。
    """
    try:
        from analysis import build_or_load_ai_result, empty_refined_info

        position_build_score = (volume_ma_info or {}).get('position_build_score', 0)
        has_recent_golden_cross = (volume_ma_info or {}).get('has_recent_golden_cross', False)
        if volume_ma_info and (not has_recent_golden_cross or position_build_score < 6):
            print(
                f"⏭️  {symbol} position_build_score={position_build_score}，不满足「建仓评分>=6」或近7日无量能金叉，跳过后台AI分析与通知"
            )
            return {
                'symbol': symbol,
                'market': market,
                'status': 'skipped',
                'error': 'volume_ma_gate',
                'full_analysis': '',
                'summary_analysis': '',
                'refine_analysis': '',
                'refined_info': empty_refined_info(),
            }

        result = build_or_load_ai_result(symbol, market=market)
        if result.get('symbol') != symbol:
            print(f"⚠️ {symbol} AI 结果 symbol 不匹配(result={result.get('symbol')})，丢弃")
            return {
                'symbol': symbol,
                'market': market,
                'status': 'failed',
                'error': 'symbol_mismatch',
                'full_analysis': '',
                'summary_analysis': '',
                'refine_analysis': '',
                'refined_info': empty_refined_info(),
            }

        refined_info = result.get('refined_info')
        if not isinstance(refined_info, dict):
            refined_info = empty_refined_info()
        result['refined_info'] = refined_info

        if qq_notifier and result.get('status') == 'completed':
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
                refined_text=(result.get('refine_analysis') or '').strip() or None,
                bowl_score=bowl_score,
                volume_ma_info=volume_ma_info,
                turnover_rate=turnover_rate,
                turnover_warning=turnover_warning,
            )

        return result

    except Exception as e:
        print(f"⚠️ {symbol} 后台AI任务失败: {e}")
        traceback.print_exc()
        try:
            from analysis import empty_refined_info

            return {
                'symbol': symbol,
                'market': market,
                'status': 'failed',
                'error': str(e),
                'full_analysis': '',
                'summary_analysis': '',
                'refine_analysis': '',
                'refined_info': empty_refined_info(),
            }
        except Exception:
            return {'symbol': symbol, 'status': 'failed', 'error': str(e)}
