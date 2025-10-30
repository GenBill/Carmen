"""
港A股市场扫描主程序
专用于港股和A股市场扫描，每天北京时间18:00运行一次
"""

import sys
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from get_stock_price import get_stock_data
from stocks_list.get_all_stock import get_stock_list
from indicators import carmen_indicator, vegas_indicator, backtest_carmen_indicator
from display_utils import print_stock_info, print_header, get_output_buffer, capture_output, clear_output_buffer
from volume_filter import get_volume_filter, should_filter_stock
from html_generator import generate_html_report, prepare_report_data
from git_publisher import GitPublisher
from alert_system import add_to_watchlist, print_watchlist_summary

import time
import pytz
from datetime import datetime
import sys

def get_hka_stock_list(stock_path: str = 'stocks_list/cache/china_screener_HK.csv'):
    """
    从CSV文件获取港股/A股列表
    
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
            names = df['Name'].dropna().tolist()
            return symbols, names
        else:
            print(f"⚠️ CSV文件中没有找到Symbol列")
            return [], []
    except Exception as e:
        print(f"⚠️ 读取股票列表失败: {e}")
        return [], []

def main_hka(stock_pathHK: str = 'stocks_list/cache/china_screener_HK.csv', 
             stock_pathA: str = 'stocks_list/cache/china_screener_A.csv',
             rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
             avg_volume_days=8, enable_github_pages=True, github_branch='gh-pages'):
    """
    港A股市场扫描主函数
    
    Args:
        stock_path: 港股列表文件路径
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        enable_github_pages: 是否启用GitHub Pages自动推送，默认True
        github_branch: GitHub Pages分支名，默认gh-pages
    """
    
    # 初始化Git推送器
    git_publisher = GitPublisher(gh_pages_dir=github_branch, force_push=True) if enable_github_pages else None
    
    # 清空输出缓冲区
    clear_output_buffer()
    
    # 获取当前时间（北京/香港时间）
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now_beijing = datetime.now(beijing_tz)
    current_time_str = now_beijing.strftime('%Y-%m-%d %H:%M:%S')
    
    # 获取港股/A股列表
    # stock_pathHK = 'stocks_list/cache/china_screener_HK.csv'
    # stock_pathA = 'stocks_list/cache/china_screener_A.csv'

    stock_symbols_A, stock_names_A = get_hka_stock_list(stock_pathA)
    stock_symbols_HK, stock_names_HK = get_hka_stock_list(stock_pathHK)
    stock_symbols = stock_symbols_A + stock_symbols_HK
    stock_names = stock_names_A + stock_names_HK
    stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
    
    filtered_symbols = []
    for s in stock_symbols:
        filtered_symbols.append(s)
    
    stock_symbols = filtered_symbols

    # 获取自选股列表（用于显示判断）
    watchlist_stocks = set(get_stock_list('my_stock_symbols_HKA.txt'))
    
    # 限制扫描数量（避免扫描过多股票）
    max_stocks = 0  # 港股数据获取较慢，减少扫描数量
    if len(stock_symbols) > max_stocks and max_stocks > 0:
        print(f"⚠️ 股票数量过多({len(stock_symbols)}只)，限制为前{max_stocks}只")
        stock_symbols = stock_symbols[:max_stocks]
    
    # 打印状态栏
    print(f"\n{'='*120}")
    capture_output(f"⏰ 港A股市场扫描 | {current_time_str} CST")
    capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | 港A股市场")
    
    flush_output()
    
    # 打印表头
    print_header()
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
                cache_minutes=120
            )
            
            if stock_data:
                # 检查成交量过滤条件
                if should_filter_stock(symbol, stock_data):
                    failed_count += 1
                    continue
                
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
                        pass
                
                # 打印股票信息
                is_watchlist = symbol in watchlist_stocks
                print_success = print_stock_info(stock_data, score, is_watchlist, backtest_result)
                
                if not print_success:
                    failed_count += 1
                else:
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
                        'is_watchlist': False
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
    capture_output(f"⚠️  本轮查询: 成功 {success_count} | 失败 {failed_count}")
    capture_output(f"🔔 本次扫描发现 {alert_count} 个信号！")
    print_watchlist_summary()
    
    # 生成HTML报告并推送到GitHub Pages
    if git_publisher and stocks_data_for_html:
        try:
            terminal_output = get_output_buffer()
            
            # 筛选买入评分>=2.4的股票并运行AI分析（港A股）
            buy_signal_stocks = [stock for stock in stocks_data_for_html if stock.get('score_buy', 0) >= 2.4]
            ai_analysis_results = []
            
            if buy_signal_stocks:
                print(f"\n🔍 发现 {len(buy_signal_stocks)} 只买入信号股票，开始AI分析...")
                from analysis import analyze_stock_with_ai
                
                for stock in buy_signal_stocks:
                    symbol = stock['symbol']
                    print(f"🤖 正在分析 {symbol}...")
                    try:
                        # 运行AI分析（自动识别为港A股市场）
                        analysis_result = analyze_stock_with_ai(symbol, market="HKA")
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
                    'status': '港A股市场扫描',
                    'current_time': current_time_str,
                    'mode': '港A股市场模式'
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
            # 注意：这里使用不同的文件名，以便与美股区分
            output_file = 'docs/index_hka.html'
            content_changed = generate_html_report(report_data, output_file, is_hka_market=True)
            
            if content_changed:
                if git_publisher.publish(): 
                    pages_url = git_publisher.get_pages_url()
                    if pages_url:
                        print(f"🌐 访问港A股页面: {pages_url}index_hka.html")
                else: 
                    print("⚠️  推送失败，请检查Git配置")
            else:
                print("ℹ️  HTML内容无变化，跳过推送")
                
        except Exception as e:
            print(f"⚠️  生成HTML或推送时出错: {e}")
            import traceback
            traceback.print_exc()


def flush_output():
    """强制刷新所有输出缓冲区"""
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    
    # 配置参数
    stock_pathHK = 'stocks_list/cache/china_screener_HK.csv'  # 港股列表文件路径
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
    
    try:
        main_hka(
            stock_pathHK=stock_pathHK,
            stock_pathA=stock_pathA,
            rsi_period=RSI_PERIOD,
            macd_fast=MACD_FAST,
            macd_slow=MACD_SLOW,
            macd_signal=MACD_SIGNAL,
            avg_volume_days=AVG_VOLUME_DAYS,
            enable_github_pages=ENABLE_GITHUB_PAGES,
            github_branch=GITHUB_BRANCH
        )
    except Exception as e:
        print(f'❌ 程序运行失败: {e}')
        import traceback
        traceback.print_exc()

