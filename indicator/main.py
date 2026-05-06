import sys
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import warnings
warnings.filterwarnings('ignore', message='.*gzip.*content-length.*')

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(7897)

from stocks_list.get_all_stock import get_stock_list, append_manual_exclude_symbols
from get_stock_price import get_stock_data, get_stock_data_offline, batch_download_stocks
from indicators import carmen_indicator, silver_indicator, vegas_indicator, backtest_carmen_indicator
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
from scan_ai_common import should_submit_scan_ai, skip_gate_log_suffix

import time
import signal
import traceback
from concurrent.futures import ThreadPoolExecutor

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
        qq_notifier = TelegramNotifier(bot_token=telegram_bot_token, chat_id=telegram_chat_id)
    elif enable_qq_notify and qq_key and qq_number:
        qq_notifier = QQNotifier(key=qq_key, qq=qq_number)
    else:
        qq_notifier = None

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

    # 轮询每支股票
    alert_count = 0
    failed_count = 0
    stocks_data_for_html = []

    if offline_mode:
        get_stock_data_func = get_stock_data_offline
    else:
        get_stock_data_func = get_stock_data

    for symbol in stock_symbols:
        try:
            stock_data = get_stock_data_func(
                symbol, 
                rsi_period=rsi_period,
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
                avg_volume_days=avg_volume_days,
                use_cache=use_cache,
                cache_minutes=actual_cache_minutes
            )

            if stock_data:
                # 检查成交量过滤条件
                if should_filter_stock(symbol, stock_data):
                    failed_count += 1
                    continue

                # 计算Carmen指标
                score_carmen = carmen_indicator(stock_data)
                score_vegas = vegas_indicator(stock_data)
                score_silver = silver_indicator(stock_data)
                score = [score_carmen[0] * score_vegas[0] * score_silver, score_carmen[1] * score_vegas[1]]
                # 碗口指标已临时停用，跳过计算以节省算力
                # bowl_score = bowl_rebound_indicator(stock_data)
                bowl_score = None

                # 进行回测
                backtest_result = None
                backtest_str = ''
                confidence = 0.0
                if score[0] >= 2.0 or score[1] >= 2.0:
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
                        if backtest_result:
                            buy_success, buy_total = 0, 0
                            if 'buy_prob' in backtest_result:
                                buy_success, buy_total = backtest_result['buy_prob']
                            
                            backtest_str = f"({buy_success}/{buy_total})"
                            if buy_total > 0 and buy_total > 2:
                                confidence = (buy_success-1) / buy_total
                            else:
                                confidence = 0.0
                            
                            volume_ma_info = stock_data.get('volume_ma_info') or {}
                            submit_ai, signal_ok, position_build_score, has_recent_golden_cross = should_submit_scan_ai(
                                score[0], confidence, volume_ma_info
                            )
                            if submit_ai:
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None
                                print(f"🤖 {symbol} 触发信号，后台启动AI分析...")
                                if not qq_notifier:
                                    print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
                                future = executor.submit(
                                    process_ai_task,
                                    symbol,
                                    'US',
                                    qq_notifier,
                                    price,
                                    score[0],
                                    backtest_str,
                                    rsi,
                                    volume_ratio,
                                    bowl_score,
                                    stock_data.get('volume_ma_info'),
                                )
                                stock_data['_ai_future'] = future
                            elif signal_ok:
                                print(f"⏭️  {symbol} {skip_gate_log_suffix(position_build_score, has_recent_golden_cross)}")
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
                    if score[0] >= 2.0:
                        alert_count += 1

                    # 仅在非盘中时收集数据用于HTML生成
                    if (not is_open):
                        # 收集数据用于HTML生成
                        price = stock_data.get('close', 0)
                        open_price = stock_data.get('open', 0)
                        estimated_volume = stock_data.get('estimated_volume', 0)
                        avg_volume = stock_data.get('avg_volume', 1)
                        
                        change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0
                        volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else 0
                        volume_ma_info = stock_data.get('volume_ma_info') or {}
                        position_build_score = volume_ma_info.get('position_build_score', 0)
                        has_recent_golden_cross = volume_ma_info.get('has_recent_golden_cross', False)
                        if volume_ma_info and (not has_recent_golden_cross or position_build_score < 6):
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
                    res = fut.result()
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
                if stock.get('score_buy', 0) >= 2.0 and stock.get('confidence', 0) >= 0.5
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

    executor.shutdown(wait=True)


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
    print(f"⚡ 盘中监控: 市场开启期间每 60 秒扫描一次自选股")
    
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