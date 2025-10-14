#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
GitHub Pages 功能测试脚本
用于验证HTML生成和Git推送功能
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicator.html_generator import generate_html_report, prepare_report_data, calculate_content_hash
from indicator.git_publisher import GitPublisher


def test_html_generation():
    """测试HTML生成功能"""
    print("\n" + "="*60)
    print("🧪 测试 1: HTML 生成功能")
    print("="*60)
    
    # 模拟股票数据
    mock_stocks = [
        {
            'symbol': 'AAPL',
            'price': 150.25,
            'change_pct': 2.5,
            'volume_ratio': 120.5,
            'rsi_prev': 45.2,
            'rsi_current': 52.3,
            'dif': 1.25,
            'dea': 1.10,
            'macd_slope': 0.15,
            'score_buy': 3.2,
            'score_sell': 1.5,
            'backtest_str': '(5/10)',
            'is_watchlist': True
        },
        {
            'symbol': 'TSLA',
            'price': 245.80,
            'change_pct': -1.2,
            'volume_ratio': 95.3,
            'rsi_prev': 62.1,
            'rsi_current': 58.4,
            'dif': -0.85,
            'dea': -0.60,
            'macd_slope': -0.25,
            'score_buy': 1.8,
            'score_sell': 3.5,
            'backtest_str': '',
            'is_watchlist': False
        }
    ]
    
    # 准备报告数据
    report_data = prepare_report_data(
        stocks_data=mock_stocks,
        market_info={
            'status': '⏰ 盘前时段',
            'current_time': '2025-10-14 09:30:00 EDT',
            'mode': '盘前/盘后模式'
        },
        stats={
            'total_scanned': 100,
            'success_count': 95,
            'signal_count': 5,
            'blacklist_filtered': 50
        },
        blacklist_info={
            'summary': '📋 黑名单摘要: 2000 只股票 | 最近7天新增: 25 | 平均成交金额: $1,500,000'
        },
        config={
            'rsi_period': 8,
            'macd_fast': 8,
            'macd_slow': 17,
            'macd_signal': 9
        }
    )
    
    # 生成HTML
    print("📝 生成测试HTML报告...")
    test_output = 'docs/test_index.html'
    
    try:
        content_changed = generate_html_report(report_data, test_output)
        
        if os.path.exists(test_output):
            file_size = os.path.getsize(test_output)
            print(f"✅ HTML文件生成成功")
            print(f"   文件路径: {test_output}")
            print(f"   文件大小: {file_size} 字节")
            print(f"   内容变化: {'是' if content_changed else '否'}")
            
            # 计算哈希
            hash_value = calculate_content_hash(report_data)
            print(f"   内容哈希: {hash_value}")
            
            # 再次生成，测试哈希检测
            print("\n📝 再次生成（测试哈希检测）...")
            content_changed_2 = generate_html_report(report_data, test_output)
            print(f"   第二次生成 - 内容变化: {'是' if content_changed_2 else '否'}")
            
            if not content_changed_2:
                print("✅ 哈希检测正常工作（相同内容不重复生成）")
            
            return True
        else:
            print("❌ HTML文件未生成")
            return False
            
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_git_publisher():
    """测试Git推送功能"""
    print("\n" + "="*60)
    print("🧪 测试 2: Git 推送器检查")
    print("="*60)
    
    try:
        publisher = GitPublisher()
        
        # 检查Git环境
        print("\n📋 环境检查:")
        print(f"   仓库路径: {publisher.repo_path}")
        print(f"   目标分支: {publisher.branch}")
        print(f"   HTML文件: {publisher.html_file}")
        
        # Git可用性
        if publisher.check_git_available():
            print("   ✅ Git可用")
        else:
            print("   ❌ Git不可用")
            return False
        
        # 仓库检查
        if publisher.check_repo_exists():
            print("   ✅ Git仓库存在")
        else:
            print("   ❌ 不在Git仓库中")
            return False
        
        # 获取Pages URL
        url = publisher.get_pages_url()
        if url:
            print(f"   🌐 GitHub Pages URL: {url}")
        else:
            print("   ⚠️  无法确定GitHub Pages URL")
        
        # 检查分支
        print(f"\n🔍 检查 {publisher.branch} 分支...")
        success, output = publisher._run_command(['git', 'branch', '-a'])
        if success:
            branches = output.strip().split('\n')
            has_local = any(publisher.branch in b for b in branches if not 'remotes/' in b)
            has_remote = any(f'remotes/origin/{publisher.branch}' in b for b in branches)
            
            if has_local:
                print(f"   ✅ 本地 {publisher.branch} 分支存在")
            else:
                print(f"   ⚠️  本地 {publisher.branch} 分支不存在")
            
            if has_remote:
                print(f"   ✅ 远程 {publisher.branch} 分支存在")
            else:
                print(f"   ⚠️  远程 {publisher.branch} 分支不存在")
            
            if not has_local and not has_remote:
                print(f"\n   💡 提示: 运行以下命令初始化分支:")
                print(f"      ./setup_github_pages.sh")
        
        print("\n✅ Git推送器配置正确")
        return True
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration():
    """集成测试：生成HTML并模拟推送检查"""
    print("\n" + "="*60)
    print("🧪 测试 3: 集成测试")
    print("="*60)
    
    # 先生成测试HTML
    print("\n📝 生成测试HTML...")
    
    # 使用真实的docs/index.html路径
    test_output = 'docs/index.html'
    
    # 模拟数据
    mock_stocks = [
        {
            'symbol': 'TEST',
            'price': 100.0,
            'change_pct': 1.0,
            'volume_ratio': 100.0,
            'rsi_prev': 50.0,
            'rsi_current': 55.0,
            'dif': 1.0,
            'dea': 0.5,
            'macd_slope': 0.1,
            'score_buy': 2.5,
            'score_sell': 1.0,
            'backtest_str': '',
            'is_watchlist': False
        }
    ]
    
    report_data = prepare_report_data(
        stocks_data=mock_stocks,
        market_info={
            'status': '🧪 测试模式',
            'current_time': '2025-10-14 12:00:00 EDT',
            'mode': '测试'
        },
        stats={
            'total_scanned': 1,
            'success_count': 1,
            'signal_count': 0,
            'blacklist_filtered': 0
        },
        blacklist_info={
            'summary': '测试数据'
        },
        config={
            'rsi_period': 8,
            'macd_fast': 8,
            'macd_slow': 17,
            'macd_signal': 9
        }
    )
    
    try:
        generate_html_report(report_data, test_output)
        
        if not os.path.exists(test_output):
            print(f"❌ HTML文件未生成: {test_output}")
            return False
        
        print(f"✅ HTML文件已生成: {test_output}")
        
        # 检查推送器
        print("\n🔍 检查推送器配置...")
        publisher = GitPublisher(html_file=test_output)
        
        if not publisher.check_git_available() or not publisher.check_repo_exists():
            print("⚠️  Git环境未就绪，跳过推送测试")
            return True
        
        print("\n💡 推送功能已就绪")
        print("   要测试实际推送，请运行: python main.py")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("  Carmen Stock Scanner - GitHub Pages 功能测试")
    print("="*60)
    
    results = []
    
    # 测试1: HTML生成
    results.append(("HTML生成", test_html_generation()))
    
    # 测试2: Git推送器
    results.append(("Git推送器", test_git_publisher()))
    
    # 测试3: 集成测试
    results.append(("集成测试", test_integration()))
    
    # 汇总结果
    print("\n" + "="*60)
    print("  测试结果汇总")
    print("="*60)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name:20s} {status}")
    
    all_passed = all(r[1] for r in results)
    
    print("="*60)
    if all_passed:
        print("🎉 所有测试通过！")
        print("\n下一步:")
        print("1. 运行 ./setup_github_pages.sh 初始化gh-pages分支")
        print("2. 在GitHub设置中启用Pages")
        print("3. 运行 python indicator/main.py 开始扫描")
    else:
        print("⚠️  部分测试失败，请检查配置")
    print("="*60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

