
import sys
sys.path.append('..')
from get_stock_list import get_stock_list
from get_stock_price import get_stock_data, get_cache_stats
from indicators import carmen_indicator

import time

def main(stock_path: str = '', rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
         avg_volume_days=8, poll_interval=10, use_cache=True, cache_minutes=5):
    """
    主循环函数，轮询股票数据
    
    Args:
        stock_path: 股票列表文件路径，空字符串则从纳斯达克获取
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        poll_interval: 轮询间隔（秒），默认 10
    """
    while True:
        # 获取股票列表
        stock_symbols = get_stock_list(stock_path)
        
        # 清理股票代码（去除换行符等）
        stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
        
        print(f"\n{'='*120}")
        print(f"开始查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | {avg_volume_days}日平均成交量")
        print(f"{'='*120}\n")
        
        # 轮询每支股票
        for symbol in stock_symbols:
            stock_data = get_stock_data(
                symbol, 
                rsi_period=rsi_period,
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
                avg_volume_days=avg_volume_days,
                use_cache=use_cache,
                cache_minutes=cache_minutes
            )

            my_score = carmen_indicator(stock_data)
            print(f"Carmen Indicator Score: {my_score}")
            
            if stock_data:
                # 格式化成交量显示
                vol_str = f"{stock_data['volume']:,}" if stock_data['volume'] else "N/A"
                est_vol_str = f"{stock_data['estimated_volume']:,}" if stock_data['estimated_volume'] else "N/A"
                avg_vol_str = f"{stock_data['avg_volume']:,}" if stock_data['avg_volume'] else "N/A"
                
                # 格式化技术指标显示
                rsi_str = f"{stock_data['rsi']:.2f}" if stock_data['rsi'] else "N/A"
                rsi_prev_str = f"{stock_data['rsi_prev']:.2f}" if stock_data['rsi_prev'] else "N/A"
                dif_str = f"{stock_data['dif']:.2f}" if stock_data['dif'] else "N/A"
                dea_str = f"{stock_data['dea']:.2f}" if stock_data['dea'] else "N/A"
                hist_str = f"{stock_data['macd_histogram']:.2f}" if stock_data['macd_histogram'] else "N/A"
                dif_slope_str = f"{stock_data['dif_slope']:+.2f}" if stock_data['dif_slope'] is not None else "N/A"
                
                print(f"{stock_data['symbol']:6s} | {stock_data['date']} | "
                      f"开: ${stock_data['open']:>8.2f} | 收: ${stock_data['close']:>8.2f} | "
                      f"当日量: {vol_str:>15s} | 估算量: {est_vol_str:>15s} | 均量: {avg_vol_str:>15s}")
                print(f"       | RSI{rsi_period}: {rsi_str:>6s} | RSI前日: {rsi_prev_str:>6s} | "
                      f"DIF: {dif_str:>7s} | DEA: {dea_str:>7s} | Hist: {hist_str:>7s} | DIF斜率: {dif_slope_str:>7s}\n")
            else:
                print(f"{symbol:6s} | 无法获取数据\n")
        
        print(f"{'='*120}")
        
        # 显示缓存统计
        cache_stats = get_cache_stats()
        if cache_stats['symbols']:
            print(f"缓存状态: {cache_stats['memory_cached']} 内存 | {cache_stats['file_cached']} 文件")
            for s in cache_stats['symbols']:
                sources_str = " + ".join([
                    f"{src['type']}({src['age_minutes']:.1f}分钟, {src['data_points']}天)" 
                    for src in s['sources']
                ])
                print(f"  - {s['symbol']}: {sources_str}")
        
        print(f"等待 {poll_interval} 秒后进行下一次查询...")
        print(f"{'='*120}\n")
        time.sleep(poll_interval)

        # exit()  # 调试用退出



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
    CACHE_MINUTES = 5        # 缓存有效期（分钟）
    
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
