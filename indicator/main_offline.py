import sys
sys.path.append('..')
import signal

from main import main

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
    OFFLINE_MODE = True      # 是否离线模式
    
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
            offline_mode=OFFLINE_MODE
        )
    except KeyboardInterrupt:
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)
