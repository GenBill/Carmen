#!/usr/bin/env python3
"""
状态管理功能测试脚本
"""

import sys
import os
from datetime import datetime

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from state_manager import StateManager

def test_state_manager():
    """测试状态管理器功能"""
    print("测试状态管理器...")
    
    # 创建状态管理器
    state_mgr = StateManager("test_state.json")
    
    # 测试基本功能
    print(f"起始时间: {state_mgr.get_start_time()}")
    print(f"起始资金: ${state_mgr.get_initial_account_value():,.2f}")
    print(f"调用次数: {state_mgr.get_invocation_count()}")
    
    # 增加调用次数
    state_mgr.increment_invocation_count()
    print(f"增加后调用次数: {state_mgr.get_invocation_count()}")
    
    # 添加交易记录
    trade_info = {
        "coin": "BTC",
        "action": "buy",
        "quantity": 0.1,
        "price": 50000,
        "pnl": 500,
        "success": True
    }
    state_mgr.add_trade_record(trade_info)
    print("添加交易记录成功")
    
    # 显示性能摘要
    summary = state_mgr.get_performance_summary()
    print("\n性能摘要:")
    print(f"总PnL: ${summary['total_pnl']:,.2f}")
    print(f"总交易次数: {summary['total_trades']}")
    print(f"胜率: {summary['win_rate']:.2%}")
    
    # 测试重置功能
    state_mgr.reset_state(20000)
    print(f"\n重置后起始资金: ${state_mgr.get_initial_account_value():,.2f}")
    
    # 清理测试文件
    if os.path.exists("test_state.json"):
        os.remove("test_state.json")
        print("清理测试文件完成")
    
    print("✅ 状态管理器测试通过")

if __name__ == "__main__":
    test_state_manager()
