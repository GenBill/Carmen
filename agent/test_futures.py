#!/usr/bin/env python3
"""
永续合约交易测试脚本
验证OKX永续合约配置是否正确
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from okx_api import OKXTrader

def test_futures_trading():
    """测试永续合约交易功能"""
    print("测试永续合约交易配置...")
    
    try:
        # 创建OKX交易器
        trader = OKXTrader("okx.token")
        
        print("✅ OKX交易器创建成功")
        print(f"支持的交易对: {trader.symbols}")
        
        # 测试获取永续合约价格
        print("\n测试获取永续合约价格...")
        for symbol in trader.symbols[:2]:  # 只测试前两个
            price = trader.get_current_price(symbol)
            if price:
                print(f"✅ {symbol}: ${price}")
            else:
                print(f"❌ {symbol}: 获取价格失败")
        
        # 测试获取市场数据
        print("\n测试获取市场数据...")
        market_data = trader.get_market_data()
        if market_data:
            print(f"✅ 获取到 {len(market_data)} 个币种的市场数据")
            for coin, data in list(market_data.items())[:2]:
                print(f"  {coin}: 价格=${data['current_price']}, RSI={data['rsi_7']:.2f}")
        else:
            print("❌ 获取市场数据失败")
        
        # 测试获取持仓
        print("\n测试获取持仓...")
        positions = trader.get_positions()
        print(f"当前持仓数量: {len(positions)}")
        for coin, pos in positions.items():
            print(f"  {coin}: {pos['side']} {pos['size']} @ {pos['entry_price']}")
        
        # 测试获取账户信息
        print("\n测试获取账户信息...")
        account_info = trader.get_account_info()
        if account_info:
            print(f"✅ 账户信息: 总价值=${account_info['total_usdt']:,.2f}, 可用=${account_info['free_usdt']:,.2f}")
        else:
            print("❌ 获取账户信息失败")
        
        print("\n✅ 永续合约交易配置测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_futures_trading()
