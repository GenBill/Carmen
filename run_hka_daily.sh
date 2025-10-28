#!/bin/bash
# 港A股每日扫描脚本
# 在北京时间18:00运行港A股扫描

cd "$(dirname "$0")"

# 运行港A股扫描脚本
python indicator/main_hka.py

