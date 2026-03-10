"""
A股市场扫描主程序
专用于A股市场扫描，每天北京时间11:35、14:30和15:10运行
"""

import sys
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import warnings
warnings.filterwarnings('ignore', message='.*gzip.*content-length.*')

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(7897)

from get_stock_price import get_stock_data, batch_download_stocks
from stocks_list.get_all_stock import get_stock_list
from indicators import carmen_indicator, silver_indicator, vegas_indicator, backtest_carmen_indicator
from bowl_filter import bowl_rebound_indicator
from display_utils import print_stock_info, print_header, get_output_buffer, capture_output, clear_output_buffer
from volume_filter import get_volume_filter, should_filter_stock
from html_generator import generate_html_report, prepare_report_data
from git_publisher import GitPublisher
from alert_system import add_to_watchlist, print_watchlist_summary
from qq_notifier import QQNotifier, load_qq_token
from telegram_notifier import TelegramNotifier, load_telegram_token
from scheduler import MarketScheduler
from concurrent.futures import ThreadPoolExecutor
from async_ai import process_ai_task

import time
import pytz
from datetime import datetime
import sys
import traceback

def get_stock_list_from_csv(stock_path: str):
    """
    从CSV文件获取股票列表
    
    Args:
        stock_path: 股票列表CSV文件路径
        
    Returns:
        list: 股票代码列表
    """
    try:
        import pandas as pd
        df = pd.read_csv(stock_path)
        
        # 从Symbol列提取股票代码
        if 'Symbol' in df.columns:
            symbols = df['Symbol'].dropna().tolist()
            names = df['Name'].dropna().tolist() if 'Name' in df.columns else []
            return symbols, names
        else:
            print(f"⚠️ CSV文件中没有找到Symbol列")
            return [], []
    except Exception as e:
        print(f"⚠️ 读取股票列表失败: {e}")
        return [], []

def main_a(stock_path: str = 'stocks_list/cache/china_screener_A.csv', 
             rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
             avg_volume_days=8, enable_github_pages=True, github_branch='gh-pages',
             enable_qq_notify=False, qq_key='', qq_number='',
             enable_telegram_notify=False, telegram_bot_token='', telegram_chat_id=''):
    """
    A股市场扫描主函数
    
    Args:
        stock_path: A股列表文件路径
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        enable_github_pages: 是否启用GitHub Pages自动推送，默认True
        github_branch: GitHub Pages分支名，默认gh-pages
        enable_qq_notify: 是否启用QQ推送，默认False
        qq_key: Qmsg酱的KEY，在Qmsg酱官网登录后，在控制台可以获取KEY
        qq_number: 接收消息的QQ号
        enable_telegram_notify: 是否启用Telegram推送，默认False（可替代QQ）
        telegram_bot_token: Telegram Bot API Token
        telegram_chat_id: 接收消息的 Chat ID
    """
    
    # 初始化Git推送器
    git_publisher = GitPublisher(gh_pages_dir=github_branch, force_push=True) if enable_github_pages else None
    
    # 初始化消息推送器：优先 Telegram，否则 QQ
    if enable_telegram_notify and telegram_bot_token and telegram_chat_id:
        qq_notifier = TelegramNotifier(bot_token=telegram_bot_token, chat_id=telegram_chat_id)
    elif enable_qq_notify and qq_key and qq_number:
        qq_notifier = QQNotifier(key=qq_key, qq=qq_number)
    else:
        qq_notifier = None
    
    # 初始化线程池（限制并发数，避免API速率限制）
    executor = ThreadPoolExecutor(max_workers=3)
    
    # 清空输出缓冲区
    clear_output_buffer()
    
    # 获取当前时间（北京时间）
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now_beijing = datetime.now(beijing_tz)
    current_time_str = now_beijing.strftime('%Y-%m-%d %H:%M:%S')
    
    # 获取A股列表
    stock_symbols, stock_names = get_stock_list_from_csv(stock_path)
    stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
    
    # 获取自选股列表（用于显示判断）
    # 注意：这里我们仍然可以加载HKA的自选股，或者新建一个A股自选列表。暂时复用HKA。
    watchlist_stocks = set(get_stock_list('my_stock_symbols_HKA.txt'))
    
    # 限制扫描数量
    max_stocks = 0  
    if len(stock_symbols) > max_stocks and max_stocks > 0:
        print(f"⚠️ 股票数量过多({len(stock_symbols)}只)，限制为前{max_stocks}只")
        stock_symbols = stock_symbols[:max_stocks]
    
    # 打印状态栏
    print(f"\n{'='*120}")
    capture_output(f"⏰ A股市场扫描 | {current_time_str} CST")
    capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | A股市场")
    
    flush_output()
    
    # 打印表头
    print_header()
    flush_output()

    # 批量下载股票数据（多线程加速）
    batch_download_stocks(
        stock_symbols, 
        use_cache=True, 
        cache_minutes=20,
        batch_size=50,
        period="1y"
    )
    flush_output()
    
    # 扫描股票
    alert_count = 0
    failed_count = 0
    stocks_data_for_html = []

    for symbol in stock_symbols:
        try:
            # 跳过明显无法获取的数据
            if not symbol or '.' not in symbol:
                failed_count += 1
                continue
            
            stock_data = get_stock_data(
                symbol, 
                rsi_period=rsi_period,
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
                avg_volume_days=avg_volume_days,
                use_cache=True,
                cache_minutes=20
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
                # 碗口形态标记（不过滤，仅在输出中标注）
                bowl_score = bowl_rebound_indicator(stock_data)
                
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
                            
                            # 发送QQ推送（使用后台线程，不阻塞扫描）
                            if qq_notifier and (score[0] >= 3.0 or (confidence >= 0.5 and score[0] >= 2.0)):
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None
                                
                                print(f"🤖 {symbol} 触发信号，后台启动AI分析...")
                                
                                # 提交后台任务
                                future = executor.submit(
                                    process_ai_task,
                                    symbol, "HKA", qq_notifier,
                                    price, score[0], backtest_str, rsi, volume_ratio, bowl_score
                                )
                                
                                # 将Future保存到stock_data
                                stock_data['_ai_future'] = future

                            elif qq_notifier and (symbol in watchlist_stocks) and score[1] >= 2.0:
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None
                                
                                # 卖出果断，别分析了，直接发送！
                                qq_notifier.send_sell_signal(
                                    symbol=symbol,
                                    price=price,
                                    score=score[1],
                                    backtest_str=backtest_str, 
                                    rsi=rsi,
                                    volume_ratio=volume_ratio,
                                )
                    
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
                    
                    # 收集数据用于HTML生成
                    price = stock_data.get('close', 0)
                    open_price = stock_data.get('open', 0)
                    estimated_volume = stock_data.get('estimated_volume', 0)
                    avg_volume = stock_data.get('avg_volume', 1)
                    
                    change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0
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
                        'confidence': confidence,
                        'is_watchlist': False,
                        # 保存Future供后续获取结果
                        '_ai_future': stock_data.get('_ai_future'),
                        '_ai_analysis': None,
                        '_refined_info': {}
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
    capture_output(f"{'='*120}")
    
    # 显示统计
    success_count = len(stock_symbols) - failed_count
    capture_output(f"⚠️ 本轮查询: 成功 {success_count} | 失败 {failed_count}")
    capture_output(f"🔔 本次扫描发现 {alert_count} 个信号！")
    print_watchlist_summary()

    # 显示成交量过滤器状态
    volume_filter = get_volume_filter()
    blacklist_summary = volume_filter.get_blacklist_summary()
    capture_output(f"\n{blacklist_summary}")
    
    # 保存黑名单（如果有新增）
    volume_filter.save_blacklist()
    
    # 等待所有后台AI任务完成并回填数据
    pending_ai_stocks = [s for s in stocks_data_for_html if s.get('_ai_future')]
    if pending_ai_stocks:
        print(f"\n⏳ 等待 {len(pending_ai_stocks)} 个后台AI任务完成...")
        for stock in pending_ai_stocks:
            try:
                future = stock.get('_ai_future')
                symbol = stock['symbol']
                # 获取结果（如果未完成会阻塞等待）
                ai_analysis, refined_info = future.result()
                
                # 回填数据
                stock['_ai_analysis'] = ai_analysis
                stock['_refined_info'] = refined_info
                
                print(f"✅ {symbol} 后台AI分析完成")
            except Exception as e:
                print(f"⚠️ 获取 {stock.get('symbol')} AI结果失败: {e}")
    
    # 关闭线程池
    executor.shutdown(wait=True)
    
    # 生成HTML报告并推送到GitHub Pages
    if git_publisher and stocks_data_for_html:
        try:
            terminal_output = get_output_buffer()
            
            # 筛选买入评分>=2.0 且 胜率>=0.5 的股票，复用已有的AI分析结果
            buy_signal_stocks = [
                stock for stock in stocks_data_for_html 
                if stock.get('score_buy', 0) >= 2.0 and stock.get('confidence', 0) >= 0.5
            ]
            ai_analysis_results = []
            
            if buy_signal_stocks:
                print(f"\n🔍 发现 {len(buy_signal_stocks)} 只买入信号股票，准备AI分析结果...")
                from analysis import analyze_stock_with_ai
                
                for stock in buy_signal_stocks:
                    symbol = stock['symbol']
                    try:
                        # 优先复用QQ推送时已保存的原始AI分析结果（避免重复API调用）
                        # 注意：网页端使用原始分析结果，不使用refine版本
                        cached_analysis = stock.get('_ai_analysis')
                        
                        if cached_analysis:
                            # 使用缓存的原始分析结果（与QQ推送同源）
                            analysis_result = cached_analysis
                            print(f"✅ {symbol} 复用已有AI原始分析结果")
                        else:
                            # 没有缓存，需要新调用API
                            print(f"🆕 {symbol} 无缓存，调用AI分析...")
                            analysis_result = analyze_stock_with_ai(symbol, market="HKA")
                        
                        ai_analysis_results.append({
                            'symbol': symbol,
                            'analysis': analysis_result,
                            'score_buy': stock.get('score_buy', 0),
                            'price': stock.get('price', 0)
                        })
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
                    'status': 'A股市场扫描',
                    'current_time': current_time_str,
                    'mode': 'A股市场模式'
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
            output_file = 'docs/index_a.html'
            content_changed = generate_html_report(report_data, output_file, market_type="A")
            
            if content_changed:
                if git_publisher.publish(): 
                    pages_url = git_publisher.get_pages_url()
                    if pages_url:
                        print(f"🌐 访问A股页面: {pages_url}index_a.html")
                else: 
                    print("⚠️  推送失败，请检查Git配置")
            else:
                print("ℹ️  HTML内容无变化，跳过推送")
                
        except Exception as e:
            print(f"⚠️  生成HTML或推送时出错: {e}")
            traceback.print_exc()


def flush_output():
    """强制刷新所有输出缓冲区"""
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    
    # 配置参数
    stock_pathA = 'stocks_list/cache/china_screener_A.csv'  # A股列表文件路径
    
    # 技术指标参数（与美股保持一致）
    RSI_PERIOD = 8
    MACD_FAST = 8
    MACD_SLOW = 17
    MACD_SIGNAL = 9
    AVG_VOLUME_DAYS = 8
    
    # GitHub Pages 配置
    ENABLE_GITHUB_PAGES = True
    GITHUB_BRANCH = 'gh-pages'
    
    # 消息推送配置（二选一，Telegram 优先）
    ENABLE_QQ_NOTIFY = False
    ENABLE_TELEGRAM_NOTIFY = True
    try:
        TELEGRAM_TOKEN, TELEGRAM_CHAT_ID = load_telegram_token()
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  无法加载Telegram token: {e}")
        print("⚠️  Telegram推送功能已禁用")
        ENABLE_TELEGRAM_NOTIFY = False
        TELEGRAM_TOKEN = ''
        TELEGRAM_CHAT_ID = ''
    try:
        QQ_KEY, QQ_NUMBER = load_qq_token()
    except (FileNotFoundError, ValueError) as e:
        QQ_KEY, QQ_NUMBER = '', ''
    
    # 初始化调度器
    # A股运行节点: 11:35(午休), 14:30(收盘前30分钟), 15:10(收盘)
    scheduler = MarketScheduler(
        market='A',
        run_nodes_cfg=[
            {'hour': 11, 'minute': 00},
            {'hour': 11, 'minute': 35},
            {'hour': 14, 'minute': 30},
            {'hour': 15, 'minute': 10}
        ]
    )

    while True:
        try:
            if scheduler.check_should_run():
                main_a(
                    stock_path=stock_pathA,
                    rsi_period=RSI_PERIOD,
                    macd_fast=MACD_FAST,
                    macd_slow=MACD_SLOW,
                    macd_signal=MACD_SIGNAL,
                    avg_volume_days=AVG_VOLUME_DAYS,
                    enable_github_pages=ENABLE_GITHUB_PAGES,
                    github_branch=GITHUB_BRANCH,
                    enable_qq_notify=ENABLE_QQ_NOTIFY,
                    qq_key=QQ_KEY,
                    qq_number=QQ_NUMBER,
                    enable_telegram_notify=ENABLE_TELEGRAM_NOTIFY,
                    telegram_bot_token=TELEGRAM_TOKEN,
                    telegram_chat_id=TELEGRAM_CHAT_ID
                )

        except KeyboardInterrupt:
            print("\n⚠️  终止运行")
            break
        except Exception as e:
            print(f'❌ 程序运行失败: {e}')
            traceback.print_exc()

        # 每 10 分钟检查一次
        time.sleep(600)
