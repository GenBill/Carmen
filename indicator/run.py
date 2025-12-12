import sys
import signal
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(7897)

from main import run_scheduler
from get_stock_price import clear_cache

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
    
    USE_CACHE = True         # 是否使用缓存
    CACHE_MINUTES = 60       # 缓存有效期（分钟）
    OFFLINE_MODE = False     # 是否离线模式
    INTRADAY_USE_ALL_STOCKS = True  # 盘中时段是否使用全股票列表
    
    # GitHub Pages 配置
    ENABLE_GITHUB_PAGES = True   # 是否启用GitHub Pages自动推送
    GITHUB_BRANCH = 'gh-pages'   # GitHub Pages分支名
    
    # QQ推送配置
    ENABLE_QQ_NOTIFY = True      # 是否启用QQ推送
    
    # 启动时清空旧缓存
    CLEAR_CACHE_ON_START = False  # 设为True可清空启动时的缓存
    
    if CLEAR_CACHE_ON_START:
        print("🗑️  清空旧缓存...")
        clear_cache(clear_files=True)
    
    # 设置信号处理，优雅退出
    def signal_handler(sig, frame):
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # 调用 main.py 中重构后的调度器
        run_scheduler(
            stock_path=stock_path,
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
            enable_qq_notify=ENABLE_QQ_NOTIFY
        )
    except KeyboardInterrupt:
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)