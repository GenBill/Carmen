import sys
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import warnings
warnings.filterwarnings('ignore', message='.*gzip.*content-length.*')

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(7897)

from stocks_list.get_all_stock import get_stock_list, append_manual_exclude_symbols
from get_stock_price import get_stock_data, get_stock_data_offline, batch_download_stocks, enrich_stock_data_detail
from indicators import backtest_carmen_indicator
from bowl_filter import bowl_rebound_indicator
from market_hours import get_market_status, get_cache_expiry_for_premarket
from alert_system import add_to_watchlist, print_watchlist_summary
from display_utils import print_stock_info, print_header, get_output_buffer, capture_output, clear_output_buffer
from volume_filter import get_volume_filter, filter_low_volume_stocks, should_filter_stock
from html_generator import generate_html_report, prepare_report_data
from git_publisher import GitPublisher
from qq_notifier import QQNotifier, load_qq_token
from telegram_notifier import TelegramNotifier, load_telegram_token
from scheduler import MarketScheduler
from async_ai import process_ai_task
from stock_character_filter import evaluate_stock_character
from scan_signal_eval import evaluate_scan_signals
from sector_rotation import maybe_run_daily_sector_rotation_report, record_pre_candidate
from rsi_rebound_signal import (
    evaluate_macd_turn_positive,
)
from scan_ai_common import (
    OPEN_DROP_FILTER_PCT,
    MIN_POSITION_BUILD_SCORE,
    duanxian_tuo_gate_ok,
    is_buy_blocked_by_open_gap,
    resolve_opening_price_context_for_filter,
    should_submit_scan_ai,
    skip_gate_log_suffix,
)

import time
import signal
import traceback
import math
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

US_RSI_REBOUND_THRESHOLD = 24.0
US_RSI_REBOUND_LOOKBACK_DAYS = 126
US_RSI_REBOUND_MIN_AVG_UP_PCT = 3.0
US_RSI_REBOUND_MIN_AVG_DOWN_PCT = 1.5
US_RSI_REBOUND_MIN_AVG_RANGE_PCT = 5.0
US_RSI_REBOUND_MIN_UP_DOWN_RATIO = 0.75
US_RSI_REBOUND_TOP_N = 3
FAST_SCAN_WORKERS = max(1, int(os.getenv("CARMEN_US_FAST_SCAN_WORKERS", os.getenv("CARMEN_FAST_SCAN_WORKERS", "4")) or 4))
AI_FUTURE_TIMEOUT_SEC = float(os.getenv("CARMEN_AI_FUTURE_TIMEOUT_SEC", "180") or 180)


def _is_us_rsi_oversold_candidate(stock_data: dict) -> bool:
    from rsi_rebound_signal import is_rsi_oversold_today
    return is_rsi_oversold_today(stock_data, US_RSI_REBOUND_THRESHOLD)


def _build_us_signal_id(symbol: str, stock_data: dict, score_buy: float, kind: str = '') -> str:
    date = stock_data.get('date', 'unknown')
    close = stock_data.get('close', 0)
    base = f"{symbol}|{date}|{close:.2f}|{score_buy:.2f}|{kind}"
    digest = hashlib.md5(base.encode('utf-8')).hexdigest()[:8]
    tag = kind or 'buy'
    return f"{symbol}|{date}|{tag}|{digest}"


def _us_rsi_rebound_elasticity_score(
    avg_up_pct: float,
    avg_down_pct: float,
    avg_range_pct: float,
    up_down_ratio: float,
) -> float:
    positive_bias = max(float(avg_up_pct) - float(avg_down_pct), 0.0)
    return (
        float(avg_up_pct) * 2.0
        + float(avg_range_pct)
        + min(float(up_down_ratio), 2.0) * 2.0
        + positive_bias
    )


def _select_top_us_rsi_rebound_candidates(candidates, limit: int = US_RSI_REBOUND_TOP_N):
    if not candidates or limit <= 0:
        return []
    return sorted(
        candidates,
        key=lambda x: (
            float(x.get('rebound_elasticity_score') or 0.0),
            float((x.get('rsi_rebound_volatility') or {}).get('up_down_ratio') or 0.0),
        ),
        reverse=True,
    )[:limit]


def _us_rsi_candidate_volatility_info(stock_data: dict) -> dict:
    rsi_vol = (
        (stock_data or {}).get('rsi_rebound_volatility')
        or (stock_data or {}).get('_rsi_rebound_volatility')
    )
    if isinstance(rsi_vol, dict) and rsi_vol.get('rebound_elasticity_score') is not None:
        return rsi_vol

    _, _, rsi_vol = _us_rsi_rebound_volatility_ok(stock_data)
    if rsi_vol:
        stock_data['_rsi_rebound_volatility'] = rsi_vol
    return rsi_vol or {}


def _format_us_rsi_candidate_elasticity(item: dict) -> str:
    rsi_vol = item.get('rsi_rebound_volatility') or {}
    return (
        f"弹性评分={float(item.get('rebound_elasticity_score') or 0):.1f}，"
        f"6个月平均+{float(rsi_vol.get('avg_up_pct') or 0):.1f}%/"
        f"-{float(rsi_vol.get('avg_down_pct') or 0):.1f}%，"
        f"上下比={float(rsi_vol.get('up_down_ratio') or 0):.2f}"
    )


def _should_submit_us_regular_ai_after_rsi_queue(rsi_signal_active: bool, rsi_enqueued: bool) -> bool:
    return (not rsi_signal_active) and (not rsi_enqueued)


def _us_rsi_rebound_volatility_ok(stock_data: dict) -> tuple[bool, str, dict]:
    info = {
        'lookback_days': US_RSI_REBOUND_LOOKBACK_DAYS,
        'avg_up_pct': None,
        'avg_down_pct': None,
        'avg_range_pct': None,
        'up_down_ratio': None,
        'rebound_elasticity_score': None,
        'passed': False,
        'reason': '',
    }
    hist = (stock_data or {}).get('hist')
    required_cols = {'Open', 'High', 'Low'}
    if hist is None or getattr(hist, 'empty', True) or not required_cols.issubset(set(hist.columns)):
        info['reason'] = '无历史OHLC数据'
        return False, info['reason'], info

    window = hist.tail(US_RSI_REBOUND_LOOKBACK_DAYS).copy()
    if len(window) < 40:
        info['reason'] = f'6个月波动样本不足({len(window)}/40)'
        return False, info['reason'], info

    open_ = window['Open'].astype(float)
    high = window['High'].astype(float)
    low = window['Low'].astype(float)
    valid = open_.gt(0) & high.gt(0) & low.gt(0)
    if int(valid.sum()) < 40:
        info['reason'] = f'有效OHLC样本不足({int(valid.sum())}/40)'
        return False, info['reason'], info

    open_ = open_[valid]
    high = high[valid]
    low = low[valid]
    up_pct = ((high - open_) / open_ * 100.0).clip(lower=0)
    down_pct = ((open_ - low) / open_ * 100.0).clip(lower=0)
    avg_up_pct = float(up_pct.mean())
    avg_down_pct = float(down_pct.mean())
    avg_range_pct = avg_up_pct + avg_down_pct
    up_down_ratio = avg_up_pct / max(avg_down_pct, 1e-9)
    rebound_elasticity_score = _us_rsi_rebound_elasticity_score(
        avg_up_pct,
        avg_down_pct,
        avg_range_pct,
        up_down_ratio,
    )
    info.update({
        'avg_up_pct': avg_up_pct,
        'avg_down_pct': avg_down_pct,
        'avg_range_pct': avg_range_pct,
        'up_down_ratio': up_down_ratio,
        'rebound_elasticity_score': rebound_elasticity_score,
    })

    if avg_up_pct < US_RSI_REBOUND_MIN_AVG_UP_PCT:
        info['reason'] = f'反弹弹性不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_down_pct < US_RSI_REBOUND_MIN_AVG_DOWN_PCT:
        info['reason'] = f'波动不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_range_pct < US_RSI_REBOUND_MIN_AVG_RANGE_PCT:
        info['reason'] = f'总振幅不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if up_down_ratio < US_RSI_REBOUND_MIN_UP_DOWN_RATIO:
        info['reason'] = f'单边下跌强、反弹弱(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info

    info['passed'] = True
    info['reason'] = (
        f'6个月弹性合格(评分={rebound_elasticity_score:.1f}, '
        f'平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%, 上下比={up_down_ratio:.2f})'
    )
    return True, info['reason'], info


def flush_output():
    """强制刷新所有输出缓冲区"""
    sys.stdout.flush()
    sys.stderr.flush()

def main_us(stock_path: str='', rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
         avg_volume_days=8, use_cache=True, cache_minutes=5, offline_mode=False, 
         intraday_use_all_stocks=False, enable_github_pages=True, github_branch='gh-pages',
         enable_qq_notify=False, qq_key='', qq_number='',
         enable_telegram_notify=False, telegram_bot_token='', telegram_chat_id=''):
    """
    美股市场扫描主函数
    
    Args:
        stock_path: 股票列表文件路径，空字符串则从纳斯达克获取
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        use_cache: 是否使用缓存
        cache_minutes: 缓存有效期（分钟）
        offline_mode: 是否离线模式
        intraday_use_all_stocks: 盘中时段是否使用全股票列表，默认False（使用自选股）
        enable_github_pages: 是否启用GitHub Pages自动推送，默认True
        github_branch: GitHub Pages分支名，默认gh-pages
        enable_qq_notify: 是否启用QQ推送，默认False
        qq_key: Qmsg酱的KEY
        qq_number: 接收消息的QQ号
        enable_telegram_notify: 是否启用Telegram推送，默认False（可替代QQ）
        telegram_bot_token: Telegram Bot API Token
        telegram_chat_id: 接收消息的 Chat ID
    """
    
    # 初始化Git推送器
    git_publisher = GitPublisher(gh_pages_dir=github_branch, force_push=True) if enable_github_pages else None
    
    # 初始化消息推送器：优先 Telegram，否则 QQ（两者接口兼容）
    if enable_telegram_notify and telegram_bot_token and telegram_chat_id:
        bot_notifier = TelegramNotifier(bot_token=telegram_bot_token, chat_id=telegram_chat_id)
    elif enable_qq_notify and qq_key and qq_number:
        bot_notifier = QQNotifier(key=qq_key, qq=qq_number)
    else:
        bot_notifier = None

    executor = ThreadPoolExecutor(max_workers=3)

    # 获取市场状态
    market_status = get_market_status()
    is_open = market_status['is_open']
    
    # 每日黑名单更新（如果在非交易时间运行，且不是离线模式）
    if (not is_open) and (not offline_mode):
        try:
            volume_filter_instance = get_volume_filter()
            volume_filter_instance.daily_update_blacklist(get_stock_data)
            pass 
        except Exception as e:
            print(f"⚠️ 黑名单更新失败: {e}")

    # 清空输出缓冲区，开始新一轮扫描
    clear_output_buffer()

    # 根据市场状态决定股票列表和缓存策略
    if is_open and not offline_mode:
        # 盘中：根据开关决定使用自选股还是全股票列表
        if intraday_use_all_stocks:
            stock_symbols = get_stock_list('')  # 空路径=获取全nasdaq
            mode = "盘中模式(全股票)"
        else:
            stock_symbols = get_stock_list(stock_path)  # 使用自选股
            mode = "盘中模式(自选股)"
        actual_cache_minutes = cache_minutes
    else:
        # 盘前/盘后：查询全部nasdaq股票，使用长缓存（到开盘）
        stock_symbols = get_stock_list('')  # 空路径=获取全nasdaq
        actual_cache_minutes = get_cache_expiry_for_premarket()
        mode = "盘前/盘后模式"

    # 清理股票代码
    stock_symbols = [s.strip() for s in stock_symbols if s.strip()]

    # 获取自选股列表（用于显示判断）
    # 注意：如果 stock_path 是空，get_stock_list('') 返回的是全列表。
    # 我们通常假设有一个明确的自选股文件用于标记
    watchlist_path = stock_path if stock_path else 'my_stock_symbols.txt'
    watchlist_stocks = set(get_stock_list(watchlist_path))

    # 应用成交量过滤器，移除黑名单中的股票
    stock_symbols = filter_low_volume_stocks(stock_symbols)
    # 确保自选股在列表中
    stock_symbols.extend([s for s in watchlist_stocks if s not in stock_symbols])

    if (not intraday_use_all_stocks) and is_open and not offline_mode:
        # 盘中如果不使用全股票，则只扫描自选股
        stock_symbols = list(watchlist_stocks)

    # 打印状态栏
    print(f"\n{'='*120}")
    capture_output(f"{market_status['message']} | {mode} | {market_status['current_time_et']}")
    capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | 缓存{actual_cache_minutes}分钟")
    
    flush_output()

    # 打印表头
    print_header()
    flush_output()

    # 批量下载股票数据（多线程加速）
    if not offline_mode:
        batch_result = batch_download_stocks(
            stock_symbols, 
            use_cache=use_cache, 
            cache_minutes=actual_cache_minutes,
            batch_size=50,
            period="1y"
        )
        missing_delisted = sorted(set(batch_result.get('missing_delisted', [])))
        if missing_delisted:
            added = append_manual_exclude_symbols(missing_delisted)
            if added:
                capture_output(f"🚫 已将 {added} 只疑似退市/无历史数据股票加入永久排除列表")
        flush_output()

    fast_scan_results = {}
    fast_scan_symbols = [s for s in stock_symbols if s]

    def load_fast_scan(symbol: str):
        data = get_stock_data_offline(
            symbol,
            rsi_period=rsi_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            avg_volume_days=avg_volume_days,
            use_cache=True,
            cache_minutes=actual_cache_minutes,
            fast_scan=True,
        )
        return symbol, data

    if fast_scan_symbols:
        workers = min(FAST_SCAN_WORKERS, len(fast_scan_symbols))
        with ThreadPoolExecutor(max_workers=workers) as scan_executor:
            futures = {scan_executor.submit(load_fast_scan, symbol): symbol for symbol in fast_scan_symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result_symbol, data = future.result()
                    fast_scan_results[result_symbol] = data
                except Exception as e:
                    fast_scan_results[symbol] = None
                    print(f"⚠️  {symbol} fast_scan离线初筛失败: {e}")

    # 轮询每支股票
    alert_count = 0
    failed_count = 0
    stocks_data_for_html = []
    us_rsi_rebound_candidates = []
    us_rsi_oversold_candidates = []

    for symbol in stock_symbols:
        try:
            stock_data = fast_scan_results.get(symbol)

            if stock_data:
                # 检查成交量过滤条件
                if should_filter_stock(symbol, stock_data):
                    failed_count += 1
                    continue

                scan_state = evaluate_scan_signals(
                    stock_data,
                    rsi_threshold=US_RSI_REBOUND_THRESHOLD,
                    volatility_ok_fn=_us_rsi_rebound_volatility_ok,
                    silver_on_sell=False,
                )
                score = scan_state.score
                rsi_oversold_today = scan_state.rsi_oversold_today
                rsi_rebound_setup = scan_state.rsi_rebound_setup
                rsi_signal_active = scan_state.rsi_signal_active
                pre_candidate = scan_state.pre_candidate
                if pre_candidate:
                    record_pre_candidate("US", symbol, stock_data, scan_state)
                # 碗口指标已临时停用，跳过计算以节省算力
                # bowl_score = bowl_rebound_indicator(stock_data)
                bowl_score = None
                if pre_candidate:
                    enriched = enrich_stock_data_detail(stock_data, avg_volume_days=avg_volume_days)
                    if not enriched:
                        full_stock_data = get_stock_data_offline(
                            symbol,
                            rsi_period=rsi_period,
                            macd_fast=macd_fast,
                            macd_slow=macd_slow,
                            macd_signal=macd_signal,
                            avg_volume_days=avg_volume_days,
                            use_cache=True,
                            cache_minutes=actual_cache_minutes,
                            fast_scan=False,
                        )
                        if full_stock_data:
                            stock_data = full_stock_data
                            scan_state = evaluate_scan_signals(
                                stock_data,
                                rsi_threshold=US_RSI_REBOUND_THRESHOLD,
                                volatility_ok_fn=_us_rsi_rebound_volatility_ok,
                                silver_on_sell=False,
                            )
                            score = scan_state.score
                            rsi_oversold_today = scan_state.rsi_oversold_today
                            rsi_rebound_setup = scan_state.rsi_rebound_setup
                            rsi_signal_active = scan_state.rsi_signal_active
                            pre_candidate = scan_state.pre_candidate
                        else:
                            pre_candidate = False

                # 进行回测
                backtest_result = None
                backtest_str = ''
                confidence = 0.0
                ai_launched = False
                if pre_candidate:
                    try:
                        backtest_result = backtest_carmen_indicator(
                            symbol, score, stock_data, 
                            gate=2.0, 
                            rsi_period=rsi_period, 
                            macd_fast=macd_fast, 
                            macd_slow=macd_slow, 
                            macd_signal=macd_signal, 
                            avg_volume_days=avg_volume_days
                        )

                        if backtest_result or rsi_signal_active:
                            buy_success, buy_total = 0, 0
                            if backtest_result and 'buy_prob' in backtest_result:
                                buy_success, buy_total = backtest_result['buy_prob']
                            
                            backtest_str = f"({buy_success}/{buy_total})"
                            if buy_total > 0 and buy_total > 2:
                                confidence = (buy_success-1) / buy_total
                            else:
                                confidence = 0.0

                            if rsi_signal_active:
                                backtest_str = f"(RSI{US_RSI_REBOUND_THRESHOLD:g})"
                            
                            volume_ma_info = stock_data.get('volume_ma_info') or {}
                            duanxian_tuo_info = stock_data.get('duanxian_tuo_info') or {}
                            if rsi_signal_active:
                                signal_ok = True
                                submit_ai = True
                                position_build_score = float(volume_ma_info.get('position_build_score', 0) or 0)
                                has_recent_golden_cross = bool(volume_ma_info.get('has_recent_golden_cross', False))
                                gate_blocked = False
                            else:
                                submit_ai_vol, signal_ok, position_build_score, has_recent_golden_cross = (
                                    should_submit_scan_ai(score[0], confidence, volume_ma_info, duanxian_tuo_info)
                                )
                                submit_ai = submit_ai_vol
                                gate_blocked = signal_ok and not submit_ai_vol

                            if signal_ok:
                                stock_character_info = evaluate_stock_character(stock_data)
                                stock_data['stock_character_info'] = stock_character_info
                                if not stock_character_info.get('passed', True):
                                    reasons = '；'.join(stock_character_info.get('reasons') or ['股性辅助否决'])
                                    print(f"⏭️  {symbol} 股性辅助否决：{reasons}")
                                    if rsi_signal_active:
                                        stock_data['_rsi_rebound_block_reason'] = f'股性辅助否决：{reasons}'
                                        continue
                                    submit_ai = False

                            opening_ctx = None
                            if submit_ai:
                                opening_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                                price_chk = stock_data.get('close', 0)
                                if (
                                    not rsi_signal_active
                                    and opening_ctx.open_drop_filter_enabled
                                    and is_buy_blocked_by_open_gap(price_chk, opening_ctx.open_for_filter)
                                ):
                                    submit_ai = False
                                    print(
                                        f"⏭️  {symbol} 当前价较开盘价跌幅≥{OPEN_DROP_FILTER_PCT:g}%，跳过买入/后台分析"
                                    )

                            if submit_ai and opening_ctx is not None:
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None
                                base_payload = {
                                    'symbol': symbol,
                                    'market': 'US',
                                    'bot_notifier': bot_notifier,
                                    'price': price,
                                    'score': score[0],
                                    'backtest_str': backtest_str,
                                    'rsi': rsi,
                                    'volume_ratio': volume_ratio,
                                    'bowl_score': bowl_score,
                                    'volume_ma_info': stock_data.get('volume_ma_info'),
                                    'duanxian_tuo_info': stock_data.get('duanxian_tuo_info'),
                                    'rsi_prev': stock_data.get('rsi_prev'),
                                    'dif': stock_data.get('dif'),
                                    'dea': stock_data.get('dea'),
                                    'dif_dea_slope': stock_data.get('dif_dea_slope'),
                                    'open_for_gap_filter': opening_ctx.open_for_filter,
                                    'opening_uncertain': opening_ctx.opening_uncertain,
                                    'open_gap_filter_enabled': opening_ctx.open_drop_filter_enabled,
                                    'stock_character_info': stock_data.get('stock_character_info'),
                                }
                                rsi_enqueued = False
                                macd_ok, macd_reason = evaluate_macd_turn_positive(stock_data)
                                if rsi_oversold_today:
                                    if macd_ok:
                                        rsi_vol = _us_rsi_candidate_volatility_info(stock_data)
                                        rebound_score = float(rsi_vol.get('rebound_elasticity_score') or 0.0)
                                        oversold_payload = {
                                            **base_payload,
                                            'signal_id': _build_us_signal_id(symbol, stock_data, score[0], 'rsi_oversold'),
                                            'signal_title': "📉RSI超卖信号",
                                            'rsi_rebound_volatility': rsi_vol,
                                        }
                                        stock_data['rebound_elasticity_score'] = rebound_score
                                        stock_data['rsi_rebound_volatility'] = rsi_vol
                                        us_rsi_oversold_candidates.append({
                                            'symbol': symbol,
                                            'stock_data': stock_data,
                                            'ai_payload': oversold_payload,
                                            'rsi': rsi,
                                            'signal_label': 'US RSI超卖',
                                            'rebound_elasticity_score': rebound_score,
                                            'rsi_rebound_volatility': rsi_vol,
                                        })
                                        print(
                                            f"🧺 {symbol} US RSI超卖候选入队："
                                            f"RSI={float(rsi or 0):.1f}，{_format_us_rsi_candidate_elasticity(us_rsi_oversold_candidates[-1])}，{macd_reason}"
                                        )
                                        rsi_enqueued = True
                                    else:
                                        print(f"⏭️  {symbol} US RSI超卖未入候选池：{macd_reason}")
                                if rsi_rebound_setup:
                                    if macd_ok:
                                        rsi_vol = stock_data.get('_rsi_rebound_volatility') or {}
                                        rebound_score = float(rsi_vol.get('rebound_elasticity_score') or 0.0)
                                        rebound_payload = {
                                            **base_payload,
                                            'signal_id': _build_us_signal_id(symbol, stock_data, score[0], 'rsi_rebound'),
                                            'signal_title': "📈反弹抄底信号",
                                            'rsi_rebound_volatility': rsi_vol,
                                        }
                                        stock_data['rebound_elasticity_score'] = rebound_score
                                        stock_data['rsi_rebound_volatility'] = rsi_vol
                                        us_rsi_rebound_candidates.append({
                                            'symbol': symbol,
                                            'stock_data': stock_data,
                                            'ai_payload': rebound_payload,
                                            'signal_label': 'US RSI反弹',
                                            'rebound_elasticity_score': rebound_score,
                                            'rsi_rebound_volatility': rsi_vol,
                                        })
                                        print(
                                            f"🧺 {symbol} US RSI反弹候选入队：弹性评分={rebound_score:.1f}，"
                                            f"6个月平均+{float(rsi_vol.get('avg_up_pct') or 0):.1f}%/"
                                            f"-{float(rsi_vol.get('avg_down_pct') or 0):.1f}%，{macd_reason}"
                                        )
                                        rsi_enqueued = True
                                    else:
                                        print(f"⏭️  {symbol} US RSI反弹未入候选池：{macd_reason}")
                                if _should_submit_us_regular_ai_after_rsi_queue(rsi_signal_active, rsi_enqueued):
                                    ai_payload = {
                                        **base_payload,
                                        'signal_id': _build_us_signal_id(symbol, stock_data, score[0]),
                                    }
                                    print(f"🤖 {symbol} 触发信号，后台启动AI分析...")
                                    if not bot_notifier:
                                        print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
                                    future = executor.submit(process_ai_task, **ai_payload)
                                    stock_data['_ai_future'] = future
                                    ai_launched = True
                            elif gate_blocked:
                                print(f"⏭️  {symbol} {skip_gate_log_suffix(position_build_score, has_recent_golden_cross, stock_data.get('duanxian_tuo_info'))}")
                            elif (symbol in watchlist_stocks) and score[1] >= 2.0:
                                # 按需求关闭自选股卖出信号推送：保留内部评分，但不发Telegram/QQ
                                pass
                    
                    except Exception as e:
                        print(f"⚠️  处理 {symbol} 回测时出错:")
                        traceback.print_exc()

                # 打印股票信息
                is_watchlist = symbol in watchlist_stocks
                print_success = print_stock_info(stock_data, score, is_watchlist, backtest_result, bowl_score=bowl_score)
                
                if not print_success:
                    failed_count += 1
                else:
                    # 统计信号 (无论盘中盘后都统计，以便CLI显示)
                    if score[0] >= 2.0 or rsi_signal_active:
                        alert_count += 1

                    # 仅在非盘中时收集数据用于HTML生成
                    if (not is_open):
                        if not pre_candidate:
                            flush_output()
                            continue

                        # 收集数据用于HTML生成
                        price = stock_data.get('close', 0)
                        open_price = stock_data.get('open', 0)
                        estimated_volume = stock_data.get('estimated_volume', 0)
                        avg_volume = stock_data.get('avg_volume', 1)
                        
                        change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0
                        volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else 0
                        volume_ma_info = stock_data.get('volume_ma_info') or {}
                        duanxian_tuo_info = stock_data.get('duanxian_tuo_info') or {}
                        stock_character_info = stock_data.get('stock_character_info')
                        if stock_character_info is None:
                            stock_character_info = evaluate_stock_character(stock_data)
                            stock_data['stock_character_info'] = stock_character_info
                        if not stock_character_info.get('passed', True):
                            continue
                        if not rsi_signal_active:
                            position_build_score = volume_ma_info.get('position_build_score', 0)
                            has_recent_golden_cross = volume_ma_info.get('has_recent_golden_cross', False)
                            volume_gate_ok = bool(has_recent_golden_cross) and float(position_build_score or 0) >= MIN_POSITION_BUILD_SCORE
                            tuo_gate_ok, _ = duanxian_tuo_gate_ok(duanxian_tuo_info)
                            if volume_ma_info and not (volume_gate_ok or tuo_gate_ok):
                                continue
                        op_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                        if (
                            not rsi_signal_active
                            and op_ctx.open_drop_filter_enabled
                            and is_buy_blocked_by_open_gap(price, op_ctx.open_for_filter)
                        ):
                            continue
                        
                        stocks_data_for_html.append({
                            'symbol': symbol,
                            'price': price,
                            'change_pct': change_pct,
                            'volume_ratio': volume_ratio,
                            'rsi_prev': stock_data.get('rsi_prev', 0),
                            'rsi_current': stock_data.get('rsi', 0),
                            'dif': stock_data.get('dif', 0),
                            'dea': stock_data.get('dea', 0),
                            'dif_dea_slope': stock_data.get('dif_dea_slope', 0),
                            'score_buy': score[0],
                            'score_sell': score[1],
                            'backtest_str': backtest_str,
                            'confidence': confidence,
                            'is_watchlist': is_watchlist,
                            '_ai_future': stock_data.get('_ai_future'),
                            '_ai_result': None,
                            '_ai_launched': ai_launched,
                            'volume_ma_info': volume_ma_info,
                            'duanxian_tuo_info': duanxian_tuo_info,
                            'stock_character_info': stock_character_info,
                            '_rsi_oversold_candidate': rsi_signal_active,
                            '_rsi_oversold_today': rsi_oversold_today,
                            '_rsi_rebound_setup': rsi_rebound_setup,
                            'rsi_rebound_volatility': stock_data.get('rsi_rebound_volatility') or stock_data.get('_rsi_rebound_volatility'),
                            'rebound_elasticity_score': stock_data.get('rebound_elasticity_score'),
                        })
                
                flush_output()
            else:
                failed_count += 1
                
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断程序...")
            raise
        except Exception as e:
            failed_count += 1
            print(f"⚠️  处理 {symbol} 时出错: {e}")
            continue

    row_by_symbol = {row.get('symbol'): row for row in stocks_data_for_html}

    all_us_rsi_candidates = us_rsi_oversold_candidates + us_rsi_rebound_candidates
    if all_us_rsi_candidates:
        selected_us_rsi_candidates = _select_top_us_rsi_rebound_candidates(
            all_us_rsi_candidates,
            US_RSI_REBOUND_TOP_N,
        )
        selected_candidate_ids = {id(item) for item in selected_us_rsi_candidates}
        print(
            f"\n📊 US RSI超卖/反弹抄底候选 {len(all_us_rsi_candidates)} 只，"
            f"按弹性评分选 Top{min(US_RSI_REBOUND_TOP_N, len(selected_us_rsi_candidates))} 播报"
        )
        for item in selected_us_rsi_candidates:
            symbol = item.get('symbol')
            stock_data = item.get('stock_data') or {}
            payload = item.get('ai_payload') or {}
            signal_label = item.get('signal_label') or 'US RSI候选'
            print(
                f"🤖 {symbol} {signal_label}Top候选，后台启动AI分析："
                f"{_format_us_rsi_candidate_elasticity(item)}"
            )
            if not bot_notifier:
                print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
            future = executor.submit(process_ai_task, **payload)
            stock_data['_ai_future'] = future
            stock_data['_ai_launched'] = True
            row = row_by_symbol.get(symbol)
            if row is not None:
                row['_ai_future'] = future
                row['_ai_launched'] = True
        for item in all_us_rsi_candidates:
            if id(item) in selected_candidate_ids:
                continue
            symbol = item.get('symbol')
            signal_label = item.get('signal_label') or 'US RSI候选'
            print(
                f"⏭️  {symbol} {signal_label}候选未入Top{US_RSI_REBOUND_TOP_N}，本轮不播报："
                f"{_format_us_rsi_candidate_elasticity(item)}"
            )

    # 打印分隔线
    capture_output(f"{ '='*120}")
    
    # 显示统计
    success_count = len(stock_symbols) - failed_count
    capture_output(f"⚠️ 本轮查询: 成功 {success_count} | 失败 {failed_count}")
    capture_output(f"🔔 本次扫描发现 {alert_count} 个信号！")
    print_watchlist_summary()

    # 盘前/盘后：先等待扫描阶段提交的 AI 任务（不依赖是否推送 Git）
    if (not is_open) and stocks_data_for_html:
        pending_ai = [s for s in stocks_data_for_html if s.get('_ai_future')]
        if pending_ai:
            print(f"\n⏳ 等待 {len(pending_ai)} 个后台AI任务完成（美股HTML）...")
            for stock in pending_ai:
                sym = stock['symbol']
                try:
                    fut = stock['_ai_future']
                    res = fut.result(timeout=AI_FUTURE_TIMEOUT_SEC)
                    if isinstance(res, dict) and res.get('symbol') == sym:
                        stock['_ai_result'] = res
                    else:
                        print(f"⚠️ {sym} 异步AI结果symbol不一致，已丢弃")
                        stock['_ai_result'] = None
                except Exception as e:
                    print(f"⚠️ {sym} 获取后台AI结果失败: {e}")
                    stock['_ai_result'] = None

    # 生成HTML报告并推送到GitHub Pages
    if (not is_open) and git_publisher and stocks_data_for_html:
        try:
            terminal_output = get_output_buffer()

            from analysis import build_ai_analysis_results_for_html

            buy_signal_stocks = [
                stock
                for stock in stocks_data_for_html
                if (stock.get('score_buy', 0) >= 2.0 and stock.get('confidence', 0) >= 0.5)
                or (stock.get('_rsi_oversold_candidate') and stock.get('_ai_launched'))
            ]
            ai_analysis_results = []
            if buy_signal_stocks:
                print(f"\n🔍 发现 {len(buy_signal_stocks)} 只买入信号股票，组装AI展示数据（仅缓存/任务结果）...")
                ai_analysis_results = build_ai_analysis_results_for_html(buy_signal_stocks)

            # 准备报告数据
            report_data = prepare_report_data(
                stocks_data=stocks_data_for_html,
                market_info={
                    'status': market_status['message'],
                    'current_time': market_status['current_time_et'],
                    'mode': mode
                },
                stats={
                    'total_scanned': len(stock_symbols),
                    'success_count': success_count,
                    'signal_count': alert_count,
                    'blacklist_filtered': 0
                },
                blacklist_info={
                    'summary': ''
                },
                config={
                    'rsi_period': rsi_period,
                    'macd_fast': macd_fast,
                    'macd_slow': macd_slow,
                    'macd_signal': macd_signal
                },
                terminal_output=terminal_output,
                ai_analysis_results=ai_analysis_results
            )
            
            # 生成HTML
            output_file = 'docs/index.html'
            content_changed = generate_html_report(report_data, output_file)
            
            if content_changed:
                if git_publisher.publish(): 
                    pages_url = git_publisher.get_pages_url()
                    if pages_url:
                        print(f"🌐 访问美股页面: {pages_url}")
                else: 
                    print("⚠️  推送失败，请检查Git配置")
            else:
                print("ℹ️  HTML内容无变化，跳过推送")
                
        except Exception as e:
            print(f"⚠️  生成HTML或推送时出错: {e}")
            traceback.print_exc()

    try:
        maybe_run_daily_sector_rotation_report("US", bot_notifier)
    except Exception as e:
        print(f"⚠️  美股板块轮动报告触发失败: {e}")
        traceback.print_exc()

    executor.shutdown(wait=False, cancel_futures=True)


def run_scheduler(stock_path='my_stock_symbols.txt', 
                  rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, avg_volume_days=8,
                  use_cache=True, cache_minutes=5, 
                  offline_mode=False, intraday_use_all_stocks=False,
                  enable_github_pages=True, github_branch='gh-pages',
                  enable_qq_notify=True, qq_key='', qq_number='',
                  enable_telegram_notify=False, telegram_bot_token='', telegram_chat_id=''):
    """
    运行美股扫描调度器 (混合模式)
    """
    
    # 如果开启QQ通知但没提供key/number，尝试加载
    if enable_qq_notify and (not qq_key or not qq_number):
        try:
            loaded_key, loaded_number = load_qq_token()
            qq_key = qq_key or loaded_key
            qq_number = qq_number or loaded_number
        except (FileNotFoundError, ValueError) as e:
            print(f"⚠️  无法加载QQ token: {e}")
            print("⚠️  QQ推送功能已禁用")
            enable_qq_notify = False
            qq_key = ''
            qq_number = ''
    # 如果开启Telegram通知但没提供token/chat_id，尝试加载
    if enable_telegram_notify and (not telegram_bot_token or not telegram_chat_id):
        try:
            loaded_token, loaded_chat_id = load_telegram_token()
            telegram_bot_token = telegram_bot_token or loaded_token
            telegram_chat_id = telegram_chat_id or loaded_chat_id
        except (FileNotFoundError, ValueError) as e:
            print(f"⚠️  无法加载Telegram token: {e}")
            print("⚠️  Telegram推送功能已禁用")
            enable_telegram_notify = False
            telegram_bot_token = ''
            telegram_chat_id = ''

    # 美股运行节点 (ET): 
    # 08:00 (盘前 - 全市场扫描)
    # 16:05 (收盘 - 全市场扫描)
    # 注意：盘中时段 (09:30-16:00) 将由主循环自动检测并持续运行，不再依赖调度器定点
    scheduler = MarketScheduler(
        market='US',
        run_nodes_cfg=[
            {'hour': 8, 'minute': 0},
            {'hour': 16, 'minute': 10}
        ]
    )

    print("🚀 美股扫描程序已启动 (Hybrid Mode)")
    print(f"⏰ 定点扫描 (盘前/盘后): {scheduler.run_nodes_cfg}")
    print(f"⚡ 盘中监控: 市场开启期间每 600 秒扫描一次自选股")
    
    while True:
        try:
            # 获取当前市场状态
            market_status = get_market_status()
            is_open = market_status['is_open']
            
            should_run = False
            
            if is_open:
                # 盘中模式：持续运行 (亚实时监控)
                should_run = True
            else:
                # 盘前/盘后模式：仅在特定时间点运行
                if scheduler.check_should_run():
                    should_run = True

            if should_run:
                main_us(
                    stock_path=stock_path,
                    rsi_period=rsi_period,
                    macd_fast=macd_fast,
                    macd_slow=macd_slow,
                    macd_signal=macd_signal,
                    avg_volume_days=avg_volume_days,
                    use_cache=use_cache,
                    cache_minutes=cache_minutes,
                    offline_mode=offline_mode,
                    intraday_use_all_stocks=intraday_use_all_stocks,
                    enable_github_pages=enable_github_pages,
                    github_branch=github_branch,
                    enable_qq_notify=enable_qq_notify,
                    qq_key=qq_key,
                    qq_number=qq_number,
                    enable_telegram_notify=enable_telegram_notify,
                    telegram_bot_token=telegram_bot_token,
                    telegram_chat_id=telegram_chat_id
                )
            
            # 基础轮询间隔
            time.sleep(600)
            
        except KeyboardInterrupt:
            print("\n⚠️  终止运行")
            break
        except Exception as e:
            print(f'❌ 程序运行失败: {e}')
            traceback.print_exc()
            time.sleep(600)


if __name__ == "__main__":
    
    # 配置参数
    STOCK_PATH = 'my_stock_symbols.txt'  # 自选股文件
    
    # 技术指标参数
    RSI_PERIOD = 8
    MACD_FAST = 8
    MACD_SLOW = 17
    MACD_SIGNAL = 9
    AVG_VOLUME_DAYS = 8
    
    # 缓存配置
    USE_CACHE = True
    CACHE_MINUTES = 60
    
    # 模式配置
    OFFLINE_MODE = False        # 是否离线模式
    INTRADAY_USE_ALL_STOCKS = False # 盘中是否使用全股票列表（默认False，只扫自选股）
    
    # GitHub Pages 配置
    ENABLE_GITHUB_PAGES = True
    GITHUB_BRANCH = 'gh-pages'
    
    # 消息推送配置（二选一，Telegram 优先）
    ENABLE_QQ_NOTIFY = False     # 是否启用QQ推送（已被腾讯限制）
    ENABLE_TELEGRAM_NOTIFY = True  # 是否启用Telegram推送（推荐）

    run_scheduler(
        stock_path=STOCK_PATH,
        rsi_period=RSI_PERIOD,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
        avg_volume_days=AVG_VOLUME_DAYS,
        use_cache=USE_CACHE,
        cache_minutes=CACHE_MINUTES,
        offline_mode=OFFLINE_MODE,
        intraday_use_all_stocks=INTRADAY_USE_ALL_STOCKS,
        enable_github_pages=ENABLE_GITHUB_PAGES,
        github_branch=GITHUB_BRANCH,
        enable_qq_notify=ENABLE_QQ_NOTIFY,
        enable_telegram_notify=ENABLE_TELEGRAM_NOTIFY
    )
