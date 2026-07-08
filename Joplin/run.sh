# 导出模式 A（默认写入 Joplin/temp.md）
python scripts/average_down_calc.py -p 238 -f 10000 -mode A

# 导出模式 B
python scripts/average_down_calc.py -p 238 -f 10000 -mode B

# 指定标题（生成「GLW 加仓计划」）
python scripts/average_down_calc.py -p 238 -f 10000 -mode B -n GLW

# 自定义输出路径
python scripts/average_down_calc.py -p 238 -f 10000 -mode A -o Joplin/GLW.md