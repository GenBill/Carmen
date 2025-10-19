#!/bin/bash

# AI自动交易系统启动脚本

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    AI自动交易系统                             ║"
echo "║              基于DeepSeek API + OKX交易所                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装Python3"
    exit 1
fi

# 检查依赖包
echo "检查依赖包..."
python3 -c "import ccxt, pandas, numpy, openai" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装依赖包..."
    pip3 install -r requirements.txt
fi

# 检查API密钥文件
echo "检查API密钥配置..."

if [ ! -f "agent/deepseek.token" ]; then
    echo "❌ agent/deepseek.token 文件不存在"
    echo "请创建该文件并放入您的DeepSeek API密钥"
    exit 1
fi

if [ ! -f "agent/okx.token" ]; then
    echo "❌ agent/okx.token 文件不存在"
    echo "请创建该文件并放入您的OKX API密钥"
    exit 1
fi

# 检查环境变量
if [ -z "$OKX_API_KEY" ] || [ -z "$OKX_SECRET_KEY" ] || [ -z "$OKX_PASSPHRASE" ]; then
    echo "⚠️  OKX API环境变量未设置"
    echo "请设置以下环境变量："
    echo "export OKX_API_KEY='your_api_key'"
    echo "export OKX_SECRET_KEY='your_secret_key'"
    echo "export OKX_PASSPHRASE='your_passphrase'"
    echo ""
    echo "是否继续运行测试模式？(y/n)"
    read -r response
    if [[ "$response" != "y" && "$response" != "Y" ]]; then
        exit 1
    fi
fi

# 运行系统测试
echo "运行系统功能测试..."
python3 test_system.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 系统测试通过！"
    echo ""
    echo "选择运行模式："
    echo "1) 正常交易模式"
    echo "2) 测试模式（沙盒环境）"
    echo "3) 干跑模式（只分析不交易）"
    echo "4) 干跑模式 + 详细Prompt日志"
    echo "5) 显示性能摘要"
    echo "6) 重置系统状态"
    echo "7) 退出"
    echo ""
    read -p "请选择 (1-7): " choice
    
    case $choice in
        1)
            echo "启动正常交易模式..."
            python3 main.py
            ;;
        2)
            echo "启动测试模式..."
            python3 main.py --test-mode
            ;;
        3)
            echo "启动干跑模式..."
            python3 main.py --dry-run
            ;;
        4)
            echo "启动干跑模式 + 详细Prompt日志..."
            python3 main.py --dry-run --enable-prompt-log
            ;;
        5)
            echo "显示性能摘要..."
            python3 main.py --show-performance
            ;;
        6)
            echo "重置系统状态..."
            read -p "请输入起始资金金额（留空使用默认10000）: " initial_value
            if [ -z "$initial_value" ]; then
                python3 main.py --reset-state
            else
                python3 main.py --reset-state --initial-value $initial_value
            fi
            ;;
        7)
            echo "退出"
            exit 0
            ;;
        *)
            echo "无效选择，退出"
            exit 1
            ;;
    esac
else
    echo "❌ 系统测试失败，请检查配置"
    exit 1
fi
