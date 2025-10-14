#!/bin/bash

# 快速查看meta.json信息的脚本

META_FILE="docs/meta.json"

if [ ! -f "$META_FILE" ]; then
    echo "❌ meta.json 文件不存在: $META_FILE"
    exit 1
fi

echo "============================================================"
echo "  Carmen Stock Scanner - Meta 信息查看"
echo "============================================================"
echo ""

# 检查jq是否安装
if command -v jq &> /dev/null; then
    # 使用jq格式化输出
    echo "📊 基本信息:"
    echo "  最后更新: $(cat $META_FILE | jq -r '.last_update_readable')"
    echo "  市场状态: $(cat $META_FILE | jq -r '.market_status')"
    echo "  更新时间: $(cat $META_FILE | jq -r '.update_time')"
    echo "  扫描模式: $(cat $META_FILE | jq -r '.mode')"
    echo ""
    
    echo "📈 统计数据:"
    echo "  扫描总数: $(cat $META_FILE | jq -r '.stats.total_scanned')"
    echo "  成功数量: $(cat $META_FILE | jq -r '.stats.success_count')"
    echo "  交易信号: $(cat $META_FILE | jq -r '.stats.signal_count')"
    echo "  黑名单数: $(cat $META_FILE | jq -r '.stats.blacklist_count')"
    echo "  显示股票: $(cat $META_FILE | jq -r '.stats.stocks_displayed')"
    echo ""
    
    echo "⚙️  配置参数:"
    echo "  RSI 周期: $(cat $META_FILE | jq -r '.config.rsi_period')"
    echo "  MACD参数: $(cat $META_FILE | jq -r '.config.macd_params')"
    echo ""
    
    echo "🔍 技术信息:"
    echo "  内容哈希: $(cat $META_FILE | jq -r '.content_hash')"
    echo "  文件大小: $(cat $META_FILE | jq -r '.html_file_size') 字节"
    echo "  总更新数: $(cat $META_FILE | jq -r '.total_updates')"
    echo ""
    
    echo "📜 更新历史 (最近5条):"
    cat $META_FILE | jq -r '.update_history[-5:] | reverse | .[] | "  [\(.timestamp_readable)] \(.market_status) | 股票:\(.stocks_count) 信号:\(.signals)"'
    echo ""
    
else
    # 没有jq，使用python
    python3 << 'PYEOF'
import json
import sys

with open('docs/meta.json', 'r', encoding='utf-8') as f:
    meta = json.load(f)

print("📊 基本信息:")
print(f"  最后更新: {meta.get('last_update_readable', 'N/A')}")
print(f"  市场状态: {meta.get('market_status', 'N/A')}")
print(f"  更新时间: {meta.get('update_time', 'N/A')}")
print(f"  扫描模式: {meta.get('mode', 'N/A')}")
print()

stats = meta.get('stats', {})
print("📈 统计数据:")
print(f"  扫描总数: {stats.get('total_scanned', 0)}")
print(f"  成功数量: {stats.get('success_count', 0)}")
print(f"  交易信号: {stats.get('signal_count', 0)}")
print(f"  黑名单数: {stats.get('blacklist_count', 0)}")
print(f"  显示股票: {stats.get('stocks_displayed', 0)}")
print()

config = meta.get('config', {})
print("⚙️  配置参数:")
print(f"  RSI 周期: {config.get('rsi_period', 8)}")
print(f"  MACD参数: {config.get('macd_params', 'N/A')}")
print()

print("🔍 技术信息:")
print(f"  内容哈希: {meta.get('content_hash', 'N/A')}")
print(f"  文件大小: {meta.get('html_file_size', 0)} 字节")
print(f"  总更新数: {meta.get('total_updates', 0)}")
print()

history = meta.get('update_history', [])
if history:
    print("📜 更新历史 (最近5条):")
    for record in reversed(history[-5:]):
        print(f"  [{record.get('timestamp_readable', 'N/A')}] {record.get('market_status', 'N/A')} | 股票:{record.get('stocks_count', 0)} 信号:{record.get('signals', 0)}")
    print()
PYEOF
fi

echo "============================================================"
echo ""
echo "💡 提示:"
echo "  - 完整内容: cat docs/meta.json | python -m json.tool"
echo "  - 监控更新: watch -n 10 ./show_meta.sh"
echo ""

