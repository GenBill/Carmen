
import sys
sys.path.append('..')
from get_stock_list import get_stock_list
from get_stock_price import get_stock_data, get_stock_data_offline
from indicators import carmen_indicator, vegas_indicator, backtest_carmen_indicator
from market_hours import get_market_status, get_cache_expiry_for_premarket
from alert_system import add_to_watchlist, print_watchlist_summary
from display_utils import print_stock_info, print_header, get_output_buffer, capture_output, clear_output_buffer
from volume_filter import get_volume_filter, filter_low_volume_stocks, should_filter_stock
from html_generator import generate_html_report, prepare_report_data
from git_publisher import GitPublisher

import time
import signal

# 强制刷新输出缓冲区，解决重定向时的缓冲问题
def flush_output():
    """强制刷新所有输出缓冲区"""
    sys.stdout.flush()
    sys.stderr.flush()

def main(stock_path: str='', rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
         avg_volume_days=8, poll_interval=10, use_cache=True, cache_minutes=5, offline_mode=False,
         intraday_use_all_stocks=False, enable_github_pages=True, github_branch='gh-pages'):
    """
    主循环函数，轮询股票数据（双模式：盘中/盘前盘后）
    
    Args:
        stock_path: 股票列表文件路径，空字符串则从纳斯达克获取
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        poll_interval: 轮询间隔（秒），默认 10
        use_cache: 是否使用缓存
        cache_minutes: 缓存有效期（分钟）
        offline_mode: 是否离线模式
        intraday_use_all_stocks: 盘中时段是否使用全股票列表，默认False（使用自选股）
        enable_github_pages: 是否启用GitHub Pages自动推送，默认True
        github_branch: GitHub Pages分支名，默认gh-pages
    """
    
    # 初始化Git推送器
    git_publisher = GitPublisher(gh_pages_dir=github_branch) if enable_github_pages else None
    
    # 状态跟踪变量
    last_market_status = None
    last_data_cache = None
    last_refresh_time = None  # 追踪上次数据刷新时间
    while True:
        # 获取市场状态
        market_status = get_market_status()
        is_open = market_status['is_open']
        
        # 检查市场状态是否发生变化
        status_changed = (last_market_status is None or 
                         last_market_status['message'] != market_status['message'] or
                         last_market_status['is_open'] != market_status['is_open'])
        
        # 检查缓存是否过期
        cache_expired = False
        if last_refresh_time is not None and last_data_cache is not None:
            current_cache_minutes = last_data_cache.get('cache_minutes', cache_minutes)
            elapsed_minutes = (time.time() - last_refresh_time) / 60
            cache_expired = elapsed_minutes >= current_cache_minutes
        
        # 每日黑名单更新（只在首次运行时执行）
        if last_data_cache is None and (not is_open):
            volume_filter_instance = get_volume_filter()
            volume_filter_instance.daily_update_blacklist(get_stock_data)
        
        # 在状态变化、首次运行或缓存过期时重新获取数据
        if status_changed or last_data_cache is None or cache_expired:
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
            watchlist_stocks = set(get_stock_list(stock_path))

            # 应用成交量过滤器，移除黑名单中的股票
            stock_symbols = filter_low_volume_stocks(stock_symbols)
            stock_symbols.extend([s for s in watchlist_stocks if s not in stock_symbols])
            
            if (not intraday_use_all_stocks) and is_open:
                stock_symbols = watchlist_stocks
            
            # 打印状态栏
            print(f"\n{'='*120}")
            capture_output(f"{market_status['message']} | {mode} | {market_status['current_time_et']}")
            capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | 缓存{actual_cache_minutes}分钟")
            
            if status_changed:
                capture_output("🔄 市场状态变化，重新获取数据...")
            elif cache_expired:
                capture_output("🔄 缓存已过期，重新获取数据...")
            
            flush_output()  # 强制刷新输出
            
            # 打印表头
            print_header()
            flush_output()  # 强制刷新输出
            
            # 轮询每支股票
            alert_count = 0
            failed_count = 0
            stocks_data_for_html = []  # 收集股票数据用于生成HTML

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
                        # 检查成交量过滤条件，如果成交量过低则加入黑名单
                        if should_filter_stock(symbol, stock_data):
                            failed_count += 1  # 被成交量过滤器过滤，计入失败
                            continue  # 跳过后续处理
                        
                        # 计算Carmen指标
                        score_carmen = carmen_indicator(stock_data)
                        score_vegas = vegas_indicator(stock_data)
                        score = [score_carmen[0] * score_vegas[0], score_carmen[1] * score_vegas[1]]
                        
                        # 进行回测
                        backtest_result = None
                        backtest_str = ''
                        if score[0] >= 2.4 or score[1] >= 2.4:
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
                                    backtest_str = f"({backtest_result.get('buy_count', 0)}/{backtest_result.get('total_days', 0)})"
                            except Exception as e:
                                # 回测失败不影响主流程
                                pass
                        
                        # 检查报警条件
                        if score[0] >= 3:
                            # 买入信号
                            if add_to_watchlist(symbol, 'BUY', score, stock_data):
                                alert_count += 1
                        elif score[1] >= 3:
                            # 卖出信号
                            if add_to_watchlist(symbol, 'SELL', score, stock_data):
                                alert_count += 1
                        
                        # 打印股票信息（简化版，自动跳过无效数据）
                        is_watchlist = symbol in watchlist_stocks
                        print_success = print_stock_info(stock_data, score, is_watchlist, backtest_result)
                        
                        if not print_success:
                            failed_count += 1  # 数据无效，计入失败
                        else:
                            # 收集数据用于HTML生成（只收集有效数据）
                            # 使用正确的字段名
                            price = stock_data.get('close', 0)
                            open_price = stock_data.get('open', 0)
                            estimated_volume = stock_data.get('estimated_volume', 0)
                            avg_volume = stock_data.get('avg_volume', 1)
                            
                            # 计算涨跌幅
                            change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0
                            
                            # 计算量比（使用estimated_volume）
                            volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else 0
                            
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
                                'is_watchlist': is_watchlist
                            })
                        
                        flush_output()  # 每处理一只股票后刷新输出
                    else:
                        failed_count += 1
                        
                except KeyboardInterrupt:
                    print("\n\n⚠️  用户中断程序...")
                    raise
                except Exception as e:
                    failed_count += 1
                    print(f"⚠️  处理 {symbol} 时出错: {e}")
                    continue  # 继续处理下一个股票
            
            # 打印分隔线
            capture_output(f"{'='*120}")
            
            # 显示统计
            success_count = len(stock_symbols) - failed_count
            capture_output(f"⚠️  本轮查询: 成功 {success_count} | 失败 {failed_count}")
            
            # 显示今日关注清单
            capture_output("")
            capture_output(f"🔔 本次扫描发现 {alert_count} 个新信号！")
            print_watchlist_summary()
            
            # 显示成交量过滤器状态
            volume_filter = get_volume_filter()
            blacklist_summary = volume_filter.get_blacklist_summary()
            capture_output(f"\n{blacklist_summary}")
            
            # 保存黑名单（如果有新增）
            volume_filter.save_blacklist()
            
            # 生成HTML报告并推送到GitHub Pages（仅盘前/盘后，避免盘中频繁推送）
            if git_publisher and stocks_data_for_html and (not is_open):
            # if git_publisher and stocks_data_for_html:
                try:
                    # 获取终端输出缓冲区
                    terminal_output = get_output_buffer()
                    
                    # 筛选买入评分>=2.4的股票并运行AI分析
                    buy_signal_stocks = [stock for stock in stocks_data_for_html if stock.get('score_buy', 0) >= 2.4]
                    ai_analysis_results = []
                    
                    if buy_signal_stocks:
                        print(f"\n🔍 发现 {len(buy_signal_stocks)} 只买入信号股票，开始AI分析...")
                        from analysis import analyze_stock_with_ai
                        
                        for stock in buy_signal_stocks:
                            symbol = stock['symbol']
                            print(f"🤖 正在分析 {symbol}...")
                            try:
                                # 运行AI分析
                                analysis_result = analyze_stock_with_ai(symbol)
                                ai_analysis_results.append({
                                    'symbol': symbol,
                                    'analysis': analysis_result,
                                    'score_buy': stock.get('score_buy', 0),
                                    'price': stock.get('price', 0)
                                })
                                print(f"✅ {symbol} 分析完成")
                            except Exception as e:
                                print(f"⚠️ {symbol} 分析失败: {e}")
                                ai_analysis_results.append({
                                    'symbol': symbol,
                                    'analysis': f"分析失败: {str(e)}",
                                    'score_buy': stock.get('score_buy', 0),
                                    'price': stock.get('price', 0)
                                })
                    
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
                            'blacklist_filtered': len(volume_filter.blacklist)
                        },
                        blacklist_info={
                            'summary': blacklist_summary
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
                    
                    # 生成HTML（会自动检测内容是否变化）
                    # print(f"\n{'='*60}")
                    # print("📄 正在生成HTML报告...")
                    content_changed = generate_html_report(report_data)
                    
                    if content_changed:
                        # print("✅ HTML报告已生成（内容有更新）")
                        
                        # 自动推送到GitHub
                        # print("🚀 检测到内容变化，准备推送到GitHub Pages...")
                        if git_publisher.publish(): 
                            pages_url = git_publisher.get_pages_url()
                            if pages_url:
                                print(f"🌐 访问您的页面: {pages_url}")
                        else: 
                            print("⚠️  推送失败，请检查Git配置")
                    else:
                        print("ℹ️  HTML内容无变化，跳过推送")
                    # print(f"{'='*60}\n")
                    
                except Exception as e:
                    print(f"⚠️  生成HTML或推送时出错: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 缓存当前状态和数据
            last_data_cache = {
                'market_status': market_status,
                'stock_symbols': stock_symbols,
                'mode': mode,
                'cache_minutes': actual_cache_minutes,
                'watchlist_stocks': watchlist_stocks
            }
            
            # 更新刷新时间
            last_refresh_time = time.time()
        else:
            # 状态未变化，使用缓存的数据
            stock_symbols = last_data_cache['stock_symbols']
            mode = last_data_cache['mode']
            actual_cache_minutes = last_data_cache['cache_minutes']
            watchlist_stocks = last_data_cache['watchlist_stocks']
        
        # 更新上次状态
        last_market_status = market_status
        
        # 只在刷新数据后才显示等待信息
        if status_changed or last_data_cache is None or cache_expired:
            print(f"\n等待 {poll_interval} 秒后进行下一次查询... (按 Ctrl+C 退出)")
            print(f"{'='*120}\n")
            flush_output()  # 轮询结束前刷新输出
        
        try:
            # 将长时间sleep分割，以便快速响应中断
            remaining = poll_interval
            while remaining > 0:
                sleep_time = min(1, remaining)  # 每次最多sleep 1秒
                time.sleep(sleep_time)
                remaining -= sleep_time
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断程序...")
            raise



if __name__ == "__main__":
    
    # 设置无缓冲输出，解决重定向时的缓冲问题
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    
    # 配置参数
    stock_path = 'my_stock_symbols.txt'  # 股票列表文件路径
    
    # 技术指标参数（可自定义）
    RSI_PERIOD = 8          # RSI 周期
    MACD_FAST = 8           # MACD 快线
    MACD_SLOW = 17          # MACD 慢线  
    MACD_SIGNAL = 9         # MACD 信号线
    AVG_VOLUME_DAYS = 8     # 平均成交量天数
    
    POLL_INTERVAL = 600      # 轮询间隔（秒）
    USE_CACHE = True         # 是否使用缓存
    CACHE_MINUTES = 20       # 缓存有效期（分钟）
    OFFLINE_MODE = False     # 是否离线模式
    INTRADAY_USE_ALL_STOCKS = False  # 盘中时段是否使用全股票列表
    
    # GitHub Pages 配置
    ENABLE_GITHUB_PAGES = True   # 是否启用GitHub Pages自动推送
    GITHUB_BRANCH = 'gh-pages'   # GitHub Pages分支名
    
    # 启动时清空旧缓存（可选，确保使用最新验证逻辑）
    CLEAR_CACHE_ON_START = False  # 设为True可清空启动时的缓存
    
    if CLEAR_CACHE_ON_START:
        from get_stock_price import clear_cache
        print("🗑️  清空旧缓存...")
        clear_cache(clear_files=True)
    
    # 设置信号处理，优雅退出
    def signal_handler(sig, frame):
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        main(
            stock_path=stock_path,
            rsi_period=RSI_PERIOD,
            macd_fast=MACD_FAST,
            macd_slow=MACD_SLOW,
            macd_signal=MACD_SIGNAL,
            avg_volume_days=AVG_VOLUME_DAYS,
            poll_interval=POLL_INTERVAL,
            use_cache=USE_CACHE,
            cache_minutes=CACHE_MINUTES,
            offline_mode=OFFLINE_MODE,
            intraday_use_all_stocks=INTRADAY_USE_ALL_STOCKS,
            enable_github_pages=ENABLE_GITHUB_PAGES,
            github_branch=GITHUB_BRANCH
        )
    except KeyboardInterrupt:
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)
