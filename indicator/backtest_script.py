#!/usr/bin/env python3
"""
独立回测脚本 - 直接指定股票进行回测
使用方法: python backtest_script.py AAPL
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from get_stock_price import get_stock_data
from indicators import carmen_indicator, vegas_indicator, backtest_carmen_indicator
from display_utils import Colors

def main():
    if len(sys.argv) != 2:
        print("使用方法: python backtest_script.py <股票代码>")
        print("示例: python backtest_script.py AAPL")
        sys.exit(1)
    
    symbol = sys.argv[1].upper()
    print(f"\n🔍 正在回测 {symbol}...")
    
    # 获取当前股票数据
    stock_data = get_stock_data(symbol)
    if not stock_data:
        print(f"❌ 无法获取 {symbol} 数据")
        sys.exit(1)
    
    # 计算指标
    score_carmen = carmen_indicator(stock_data)
    score_vegas = vegas_indicator(stock_data)
    score = [score_carmen[0] * score_vegas[0], score_carmen[1] * score_vegas[1]]
    
    print(f"📊 当前指标: Buy {score[0]:.1f} vs Sell {score[1]:.1f}")
    
    # 进行回测（使用2.4作为阈值）
    backtest_result = backtest_carmen_indicator(symbol, [3.0, 3.0], stock_data, gate=2.4)
    
    if backtest_result:
        print(f"\n📈 回测结果:")
        if 'buy_prob' in backtest_result:
            buy_success, buy_total = backtest_result['buy_prob']
            print(f"🟢 买入信号: {buy_success}/{buy_total} ({buy_success/buy_total*100:.1f}%)")
        if 'sell_prob' in backtest_result:
            sell_success, sell_total = backtest_result['sell_prob']
            print(f"🔴 卖出信号: {sell_success}/{sell_total} ({sell_success/sell_total*100:.1f}%)")
    else:
        print("❌ 未找到相似的历史信号点")

if __name__ == "__main__":
    main()
