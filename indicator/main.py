
import sys
sys.path.append('..')
from get_stock_list import get_stock_list
from get_stock_price import get_stock_data
from indicators import carmen_indicator
from market_hours import is_market_open, get_market_status, get_cache_expiry_for_premarket
from alert_system import add_to_watchlist, print_watchlist_summary
from display_utils import print_stock_info, print_header

import time
import signal

def main(stock_path: str = '', rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
         avg_volume_days=8, poll_interval=10, use_cache=True, cache_minutes=5):
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
    """
    while True:
        # 获取市场状态
        market_status = get_market_status()
        is_open = market_status['is_open']
        
        # 根据市场状态决定股票列表和缓存策略
        if is_open:
            # 盘中：查询自选股，使用短缓存
            stock_symbols = get_stock_list(stock_path)
            actual_cache_minutes = cache_minutes
            mode = "盘中模式"
        else:
            # 盘前/盘后：查询全部nasdaq股票，使用长缓存（到开盘）
            stock_symbols = get_stock_list('')  # 空路径=获取全nasdaq
            actual_cache_minutes = get_cache_expiry_for_premarket()
            mode = "盘前/盘后模式"
        
        # 清理股票代码
        stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
        
        # 打印状态栏
        print(f"\n{'='*120}")
        print(f"{market_status['message']} | {mode} | {market_status['current_time_et']}")
        print(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | 缓存{actual_cache_minutes}分钟")
        
        # 打印表头
        print_header()
        
        # 轮询每支股票
        alert_count = 0
        failed_count = 0
        
        for symbol in stock_symbols:
            try:
                stock_data = get_stock_data(
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
                    # 计算Carmen指标
                    score = carmen_indicator(stock_data)
                    
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
                    if not print_stock_info(stock_data, score):
                        failed_count += 1  # 数据无效，计入失败
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
        print(f"{'='*120}")
        
        # 显示统计
        success_count = len(stock_symbols) - failed_count
        print(f"⚠️  本轮查询: 成功 {success_count} | 失败 {failed_count}")
        
        # 显示今日关注清单
        print(f"\n🔔 本次扫描发现 {alert_count} 个新信号！")
        print_watchlist_summary()
        
        # 等待下次轮询（支持Ctrl+C中断）
        print(f"\n等待 {poll_interval} 秒后进行下一次查询... (按 Ctrl+C 退出)")
        print(f"{'='*120}\n")
        
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
    
    # 配置参数
    stock_path = 'my_stock_symbols.txt'  # 股票列表文件路径
    
    # 技术指标参数（可自定义）
    RSI_PERIOD = 8          # RSI 周期
    MACD_FAST = 8           # MACD 快线
    MACD_SLOW = 17          # MACD 慢线  
    MACD_SIGNAL = 9         # MACD 信号线
    AVG_VOLUME_DAYS = 8     # 平均成交量天数
    
    POLL_INTERVAL = 120      # 轮询间隔（秒）
    USE_CACHE = True         # 是否使用缓存
    CACHE_MINUTES = 10       # 缓存有效期（分钟）
    
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
            cache_minutes=CACHE_MINUTES
        )
    except KeyboardInterrupt:
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)
