
import sys
import signal
sys.path.append('..')
from main import main
from qq_notifier import load_qq_token

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
    
    # QQ推送配置
    ENABLE_QQ_NOTIFY = True      # 是否启用QQ推送
    # 从token文件读取QQ配置
    try:
        QQ_KEY, QQ_NUMBER = load_qq_token()
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  无法加载QQ token: {e}")
        print("⚠️  QQ推送功能已禁用")
        ENABLE_QQ_NOTIFY = False
        QQ_KEY = ''
        QQ_NUMBER = ''
    
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
            github_branch=GITHUB_BRANCH,
            enable_qq_notify=ENABLE_QQ_NOTIFY,
            qq_key=QQ_KEY,
            qq_number=QQ_NUMBER
        )
    
    except KeyboardInterrupt:
        print('\n\n👋 程序已被用户中断，正在退出...')
        sys.exit(0)

