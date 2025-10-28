#!/bin/bash
# 设置港A股每日扫描定时任务
# 每天北京时间18:00自动运行港A股扫描

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_HKA_SCRIPT="$SCRIPT_DIR/run_hka_daily.sh"

echo "=============================================="
echo "港A股每日扫描调度设置"
echo "=============================================="
echo ""

# 检查run_hka_daily.sh是否存在
if [ ! -f "$RUN_HKA_SCRIPT" ]; then
    echo "❌ 错误：找不到 run_hka_daily.sh 文件"
    exit 1
fi

# 确保脚本有执行权限
chmod +x "$RUN_HKA_SCRIPT"
chmod +x "$SCRIPT_DIR/indicator/main_hka.py"

echo "📋 将添加以下crontab任务："
echo "   0 18 * * * $RUN_HKA_SCRIPT"
echo ""
echo "该任务将在每天北京时间18:00运行港A股扫描"
echo ""

# 检查是否已经存在该任务
existing_cron=$(crontab -l 2>/dev/null | grep "run_hka_daily.sh")
if [ ! -z "$existing_cron" ]; then
    echo "⚠️  检测到已存在的定时任务："
    echo "$existing_cron"
    echo ""
    read -p "是否要覆盖现有任务？(y/n): " answer
    if [ "$answer" != "y" ]; then
        echo "❌ 已取消"
        exit 0
    fi
    
    # 删除旧的任务
    crontab -l 2>/dev/null | grep -v "run_hka_daily.sh" | crontab -
fi

# 添加新的crontab任务
(crontab -l 2>/dev/null; echo "0 12 * * * $RUN_HKA_SCRIPT >> $SCRIPT_DIR/logs/hka_scan.log 2>&1") | crontab -
(crontab -l 2>/dev/null; echo "0 18 * * * $RUN_HKA_SCRIPT >> $SCRIPT_DIR/logs/hka_scan.log 2>&1") | crontab -

echo "✅ 定时任务已添加！"
echo ""
echo "📅 任务详情："
echo "   - 运行时间：每天北京时间18:00"
echo "   - 运行脚本：$RUN_HKA_SCRIPT"
echo "   - 日志文件：$SCRIPT_DIR/logs/hka_scan.log"
echo ""
echo "📝 查看当前crontab任务："
echo "   crontab -l"
echo ""
echo "📝 删除crontab任务："
echo "   crontab -e"
echo "   # 然后删除包含 run_hka_daily.sh 的行"
echo ""

# 创建日志目录
mkdir -p "$SCRIPT_DIR/logs"
echo "✅ 日志目录已创建：$SCRIPT_DIR/logs"

