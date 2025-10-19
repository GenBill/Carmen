#!/usr/bin/env python3
"""
AI自动交易系统快速设置脚本
帮助用户快速配置API密钥和系统参数
"""

import os
import sys

def create_token_file(token_type):
    """创建API密钥文件"""
    filename = f"{token_type}.token"
    
    if os.path.exists(filename):
        print(f"⚠️  {filename} 文件已存在")
        overwrite = input("是否覆盖？(y/n): ").lower()
        if overwrite != 'y':
            return
    
    print(f"请输入您的{token_type.upper()} API密钥:")
    token = input().strip()
    
    if token:
        with open(filename, 'w') as f:
            f.write(token)
        print(f"✅ {filename} 文件创建成功")
        
        # 设置文件权限
        os.chmod(filename, 0o600)
    else:
        print("❌ 密钥不能为空")

def setup_environment():
    """设置环境变量"""
    print("\n=== OKX API环境变量设置 ===")
    print("请设置以下环境变量（可以在 ~/.bashrc 或 ~/.zshrc 中添加）:")
    print()
    
    api_key = input("OKX API Key: ").strip()
    secret_key = input("OKX Secret Key: ").strip()
    passphrase = input("OKX Passphrase: ").strip()
    
    if api_key and secret_key and passphrase:
        env_commands = f"""
# OKX API配置
export OKX_API_KEY='{api_key}'
export OKX_SECRET_KEY='{secret_key}'
export OKX_PASSPHRASE='{passphrase}'
export OKX_SANDBOX='true'  # 测试模式，生产环境设为false
"""
        
        print("\n请将以下内容添加到您的shell配置文件中:")
        print(env_commands)
        
        # 询问是否自动设置
        auto_setup = input("是否自动设置环境变量到当前会话？(y/n): ").lower()
        if auto_setup == 'y':
            os.environ['OKX_API_KEY'] = api_key
            os.environ['OKX_SECRET_KEY'] = secret_key
            os.environ['OKX_PASSPHRASE'] = passphrase
            os.environ['OKX_SANDBOX'] = 'true'
            print("✅ 环境变量已设置到当前会话")
    else:
        print("❌ 请提供完整的API配置")

def create_config_file():
    """创建配置文件"""
    print("\n=== 创建配置文件 ===")
    
    config_content = '''import os
from config import TradingConfig

# 自定义配置
config = TradingConfig(
    # 基本配置
    max_leverage=15,
    max_risk_per_trade=0.05,  # 5%风险
    trading_interval_minutes=3,
    max_positions=6,
    
    # 生产环境设置
    okx_sandbox=False,  # 设为True使用沙盒环境
    
    # 日志设置
    log_level="INFO"
)
'''
    
    with open('config.py', 'w') as f:
        f.write(config_content)
    
    print("✅ config.py 配置文件已创建")

def main():
    """主设置流程"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                AI自动交易系统快速设置                        ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # 检查Python环境
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        sys.exit(1)
    
    # 安装依赖
    print("=== 安装依赖包 ===")
    install_deps = input("是否安装依赖包？(y/n): ").lower()
    if install_deps == 'y':
        os.system("pip3 install -r requirements.txt")
    
    # 创建API密钥文件
    print("\n=== API密钥配置 ===")
    create_token_file("deepseek")
    create_token_file("okx")
    
    # 设置环境变量
    setup_environment()
    
    # 创建配置文件
    create_config_file()
    
    print("\n=== 设置完成 ===")
    print("✅ 基本配置已完成")
    print()
    print("下一步:")
    print("1. 运行 'python3 test_system.py' 测试系统功能")
    print("2. 运行 './start_trading.sh' 启动交易系统")
    print("3. 查看 README.md 了解详细使用方法")
    print()
    print("⚠️  重要提醒:")
    print("- 建议先在测试环境中验证策略效果")
    print("- 使用小资金进行测试")
    print("- 定期检查交易日志和风险指标")

if __name__ == "__main__":
    main()
