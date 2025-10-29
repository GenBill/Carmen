#!/bin/bash
# 港A股每日扫描脚本
# 在北京时间18:00运行港A股扫描

cd "$(dirname "$0")"

# 初始化conda环境（crontab执行时需要）
source ~/miniconda3/etc/profile.d/conda.sh
conda activate Quant

# 运行港A股扫描脚本
python indicator/main_hka.py

