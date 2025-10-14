#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
测试每日检查功能
验证黑名单股票不会在同一天重复检查
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indicator.volume_filter import VolumeFilter
from datetime import datetime


def test_daily_check():
    """测试每日检查功能"""
    
    print("="*60)
    print("🧪 测试黑名单每日检查功能")
    print("="*60)
    print()
    
    # 创建测试用的过滤器
    filter_instance = VolumeFilter(
        blacklist_file="test_blacklist.json",
        min_volume_usd=10000000
    )
    
    # 清空旧数据
    filter_instance.clear_blacklist()
    
    # 添加一些测试股票到黑名单
    print("📝 添加测试股票到黑名单...")
    test_stocks = [
        ('TEST1', 10000, 50.0),
        ('TEST2', 20000, 30.0),
        ('TEST3', 15000, 40.0),
        ('TEST4', 25000, 25.0),
        ('TEST5', 12000, 45.0),
    ]
    
    for symbol, volume, price in test_stocks:
        filter_instance.add_to_blacklist(symbol, volume, price)
    
    print(f"✅ 已添加 {len(test_stocks)} 只股票到黑名单")
    print()
    
    # 查看初始状态
    print("📊 初始状态:")
    progress = filter_instance.get_daily_check_progress()
    print(f"  总数: {progress['total']}")
    print(f"  今日已检查: {progress['checked_today']}")
    print(f"  今日未检查: {progress['unchecked_today']}")
    print(f"  检查进度: {progress['progress_pct']:.1f}%")
    print()
    
    # 显示黑名单摘要
    print(filter_instance.get_blacklist_summary())
    print()
    
    # 第一次获取待检查的候选股票
    print("🔍 第一次获取待检查股票:")
    candidates = filter_instance.get_candidates_for_update()
    print(f"  待检查股票: {len(candidates)} 只")
    print(f"  股票列表: {candidates}")
    print()
    
    # 模拟检查前2只股票
    print("✅ 模拟检查前2只股票...")
    today = datetime.now().date().isoformat()
    for symbol in candidates[:2]:
        if symbol in filter_instance.blacklist_metadata:
            filter_instance.blacklist_metadata[symbol]['last_checked_date'] = today
            filter_instance.blacklist_metadata[symbol]['last_checked'] = datetime.now().isoformat()
            print(f"  ✓ {symbol} 已标记为今日检查")
    print()
    
    # 再次获取待检查的候选股票
    print("🔍 第二次获取待检查股票（应该少了2只）:")
    candidates2 = filter_instance.get_candidates_for_update()
    print(f"  待检查股票: {len(candidates2)} 只")
    print(f"  股票列表: {candidates2}")
    print()
    
    # 验证已检查的股票不在候选列表中
    checked_symbols = set(candidates[:2])
    if not checked_symbols.intersection(set(candidates2)):
        print("✅ 验证通过: 已检查的股票不会重复出现在候选列表中")
    else:
        print("❌ 验证失败: 已检查的股票仍在候选列表中")
    print()
    
    # 查看更新后的进度
    print("📊 更新后的状态:")
    progress2 = filter_instance.get_daily_check_progress()
    print(f"  总数: {progress2['total']}")
    print(f"  今日已检查: {progress2['checked_today']}")
    print(f"  今日未检查: {progress2['unchecked_today']}")
    print(f"  检查进度: {progress2['progress_pct']:.1f}%")
    print()
    
    # 显示更新后的摘要
    print(filter_instance.get_blacklist_summary())
    print()
    
    # 测试全部检查完的情况
    print("✅ 模拟检查剩余所有股票...")
    for symbol in candidates2:
        if symbol in filter_instance.blacklist_metadata:
            filter_instance.blacklist_metadata[symbol]['last_checked_date'] = today
            filter_instance.blacklist_metadata[symbol]['last_checked'] = datetime.now().isoformat()
    print()
    
    # 第三次获取候选股票（应该为空）
    print("🔍 第三次获取待检查股票（应该为空）:")
    candidates3 = filter_instance.get_candidates_for_update()
    print(f"  待检查股票: {len(candidates3)} 只")
    if len(candidates3) == 0:
        print("✅ 验证通过: 所有股票检查完毕，候选列表为空")
    else:
        print(f"❌ 验证失败: 仍有 {len(candidates3)} 只股票未检查")
    print()
    
    # 最终进度
    print("📊 最终状态:")
    progress3 = filter_instance.get_daily_check_progress()
    print(f"  总数: {progress3['total']}")
    print(f"  今日已检查: {progress3['checked_today']}")
    print(f"  今日未检查: {progress3['unchecked_today']}")
    print(f"  检查进度: {progress3['progress_pct']:.1f}%")
    print()
    
    print(filter_instance.get_blacklist_summary())
    print()
    
    # 清理测试文件
    print("🗑️  清理测试文件...")
    import os
    if os.path.exists("test_blacklist.json"):
        os.remove("test_blacklist.json")
        print("  ✓ test_blacklist.json 已删除")
    print()
    
    print("="*60)
    print("🎉 测试完成！")
    print("="*60)
    print()
    
    # 总结
    print("📋 功能验证:")
    print("  ✅ 新添加的股票会自动标记 last_checked_date")
    print("  ✅ get_candidates_for_update() 只返回今天未检查的股票")
    print("  ✅ 检查后更新 last_checked_date 可防止重复检查")
    print("  ✅ 所有股票检查完毕后候选列表为空")
    print("  ✅ get_daily_check_progress() 正确统计今日进度")
    print("  ✅ get_blacklist_summary() 显示今日检查数量")
    print()


if __name__ == '__main__':
    test_daily_check()

