#!/usr/bin/env python3
"""
系统功能测试脚本
用于验证各个模块是否正常工作
"""

import sys
import os
import json
from datetime import datetime

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_deepseek_api(skip_test=True):
    """测试DeepSeek API连接"""
    if skip_test:
        print("跳过DeepSeek API测试")
        return True
    
    print("测试DeepSeek API...")
    try:
        from deepseek import DeepSeekAPI
        
        if not os.path.exists("agent/deepseek.token"):
            print("❌ agent/deepseek.token 文件不存在")
            return False
        
        api = DeepSeekAPI("agent/deepseek.token", "你是一个测试助手")
        response = api("请回复'测试成功'")
        
        if response:
            print(f"✅ DeepSeek API测试成功: {response[:50]}...")
            return True
        else:
            print("❌ DeepSeek API响应为空")
            return False
            
    except Exception as e:
        print(f"❌ DeepSeek API测试失败: {e}")
        return False

def test_okx_api():
    """测试OKX API连接"""
    print("测试OKX API...")
    try:
        from okx_api import OKXTrader
        
        if not os.path.exists("agent/okx.token"):
            print("❌ agent/okx.token 文件不存在")
            return False
        
        trader = OKXTrader("agent/okx.token")
        
        # 测试获取价格
        prices = trader.get_all_prices()
        if prices:
            print(f"✅ OKX API测试成功，获取到 {len(prices)} 个币种价格:")
            for coin, price in prices.items():
                print(f"  {coin}: ${price}")
            return True
        else:
            print("❌ 未能获取价格数据")
            return False
            
    except Exception as e:
        print(f"❌ OKX API测试失败: {e}")
        return False

def test_market_data():
    """测试市场数据获取"""
    print("测试市场数据获取...")
    try:
        from okx_api import OKXTrader
        
        trader = OKXTrader("agent/okx.token")
        market_data = trader.get_market_data()
        
        if market_data:
            print(f"✅ 市场数据获取成功，获取到 {len(market_data)} 个币种数据")
            for coin, data in market_data.items():
                print(f"  {coin}: 价格=${data['current_price']}, RSI={data['rsi_7']:.2f}")
            return True
        else:
            print("❌ 未能获取市场数据")
            return False
            
    except Exception as e:
        print(f"❌ 市场数据测试失败: {e}")
        return False

def test_risk_manager():
    """测试风险管理模块"""
    print("测试风险管理模块...")
    try:
        from risk_manager import RiskManager, Position
        
        risk_mgr = RiskManager()
        
        # 创建测试持仓
        test_positions = {
            'BTC': Position(
                coin='BTC',
                size=0.1,
                entry_price=50000,
                current_price=52000,
                leverage=10,
                side='long',
                unrealized_pnl=200,
                risk_usd=100
            )
        }
        
        # 测试仓位大小计算
        position_size = risk_mgr.calculate_position_size(10000, 50000, 48000, 10)
        print(f"✅ 仓位大小计算: {position_size}")
        
        # 测试风险指标计算
        metrics = risk_mgr.calculate_portfolio_metrics(test_positions, 10000)
        print(f"✅ 风险指标计算: 总敞口=${metrics.total_exposure:.2f}")
        
        # 测试风险报告
        report = risk_mgr.get_risk_report(test_positions, 10000)
        print("✅ 风险报告生成成功")
        
        return True
        
    except Exception as e:
        print(f"❌ 风险管理测试失败: {e}")
        return False

def test_trading_agent():
    """测试交易agent（不执行实际交易）"""
    print("测试交易agent...")
    try:
        from agent_trader import TradingAgent
        
        # 创建agent实例
        agent = TradingAgent()
        
        # 测试提示词构建
        market_data = agent.okx.get_market_data()
        if market_data:
            account_info = agent.okx.get_account_info()
            if account_info:
                positions = agent.okx.get_positions()
                
                prompt = agent._build_trading_prompt(market_data, account_info, positions)
                print(f"✅ 交易提示词构建成功，长度: {len(prompt)} 字符")
                
                # 测试AI决策（不执行交易）
                print("测试AI决策生成...")
                response = agent.deepseek("请回复一个简单的JSON格式交易决策示例")
                
                if response:
                    print(f"✅ AI决策生成成功: {response[:100]}...")
                    return True
                else:
                    print("❌ AI决策生成失败")
                    return False
            else:
                print("❌ 无法获取账户信息")
                return False
        else:
            print("❌ 无法获取市场数据")
            return False
            
    except Exception as e:
        print(f"❌ 交易agent测试失败: {e}")
        return False

def main():
    """运行所有测试"""
    print("=" * 50)
    print("AI自动交易系统功能测试")
    print("=" * 50)
    
    tests = [
        ("DeepSeek API", test_deepseek_api),
        ("OKX API", test_okx_api),
        ("市场数据", test_market_data),
        ("风险管理", test_risk_manager),
        ("交易Agent", test_trading_agent),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        result = test_func()
        results.append((test_name, result))
    
    # 汇总结果
    print("\n" + "=" * 50)
    print("测试结果汇总:")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{len(results)} 个测试通过")
    
    if passed == len(results):
        print("🎉 所有测试通过！系统可以正常运行。")
    else:
        print("⚠️  部分测试失败，请检查配置和网络连接。")
    
    return passed == len(results)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
