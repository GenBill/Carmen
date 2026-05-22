import traceback
from datetime import datetime

from a_share_rebound_alert import maybe_record_high_build_alert
from scan_ai_common import MIN_POSITION_BUILD_SCORE, OPEN_DROP_FILTER_PCT, is_buy_blocked_by_open_gap


def process_ai_task(
    symbol,
    market,
    bot_notifier,
    price,
    score,
    backtest_str,
    rsi,
    volume_ratio,
    bowl_score=None,
    volume_ma_info=None,
    turnover_rate=None,
    turnover_warning=None,
    signal_id=None,
    rsi_prev=None,
    dif=None,
    dea=None,
    dif_dea_slope=None,
    open_for_gap_filter=None,
    opening_uncertain=False,
    open_gap_filter_enabled=None,
    stock_cn_name=None,
    alert_date=None,
):
    """
    后台执行统一 AI 链路 build_or_load_ai_result，返回完整 ai result dict（单对象，非二元组）。
    开盘价跌幅闸门在所有量能闸门之后执行；仅 A 股 akshare 今开可信时启用。
    """
    try:
        from analysis import build_or_load_ai_result, empty_refined_info
        from telegram_notifier import append_signal_audit

        append_signal_audit({'event':'ai_started','symbol':symbol,'signal_id':signal_id,'market':market})

        position_build_score = (volume_ma_info or {}).get('position_build_score', 0)
        has_recent_golden_cross = (volume_ma_info or {}).get('has_recent_golden_cross', False)
        if volume_ma_info and (
            not has_recent_golden_cross or float(position_build_score or 0) < MIN_POSITION_BUILD_SCORE
        ):
            print(
                f"⏭️  {symbol} position_build_score={position_build_score}，不满足「建仓评分>={MIN_POSITION_BUILD_SCORE:g}」或近7日无量能金叉，跳过后台AI分析与通知"
            )
            append_signal_audit({'event':'ai_gate_blocked','symbol':symbol,'signal_id':signal_id,'position_build_score':position_build_score,'has_recent_golden_cross':has_recent_golden_cross})
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

        if open_gap_filter_enabled is None:
            upper_symbol = str(symbol or '').upper()
            open_gap_filter_enabled = upper_symbol.endswith('.SS') or upper_symbol.endswith('.SZ')

        if open_gap_filter_enabled and is_buy_blocked_by_open_gap(price, open_for_gap_filter):
            print(
                f"⏭️  {symbol} 当前价较开盘价跌幅≥{OPEN_DROP_FILTER_PCT:g}%，跳过后台AI分析与通知"
            )
            append_signal_audit({'event':'ai_gate_blocked','symbol':symbol,'signal_id':signal_id,'reason':'open_gap'})
            return {
                'symbol': symbol,
                'market': market,
                'status': 'skipped',
                'error': 'open_gap_filter',
                'full_analysis': '',
                'summary_analysis': '',
                'refine_analysis': '',
                'refined_info': empty_refined_info(),
            }

        result = build_or_load_ai_result(symbol, market=market)
        append_signal_audit({'event':'ai_completed','symbol':symbol,'signal_id':signal_id,'status':result.get('status')})
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

        if bot_notifier and result.get('status') == 'completed':
            sent_ok = bot_notifier.send_buy_signal(
                signal_id=signal_id,
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
                rsi_prev=rsi_prev,
                dif=dif,
                dea=dea,
                dif_dea_slope=dif_dea_slope,
                stock_cn_name=stock_cn_name,
                opening_uncertain=opening_uncertain,
            )
            if sent_ok:
                try:
                    maybe_record_high_build_alert(
                        symbol=symbol,
                        alert_date=alert_date,
                        position_build_score=float(position_build_score or 0),
                        stock_cn_name=stock_cn_name,
                    )
                except Exception as e:
                    print(f"⚠️ {symbol} 高建仓队列入队失败: {e}")

        return result

    except Exception as e:
        try:
            from telegram_notifier import append_signal_audit
            append_signal_audit({'event':'ai_failed','symbol':symbol,'signal_id':signal_id,'error':str(e)})
        except Exception:
            pass
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
