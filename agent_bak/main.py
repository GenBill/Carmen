#!/usr/bin/env python3
"""
AI自动交易系统主程序
基于DeepSeek API和OKX交易所的加密货币自动交易agent
"""

import sys
import os
import argparse
import logging
from datetime import datetime

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agent_trader import TradingAgent
from config import TradingConfig
from risk_manager import RiskManager

def setup_logging(log_level="INFO", log_file="trading_log.txt"):
    """设置日志系统"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def check_api_keys(config):
    """检查API密钥配置"""
    issues = []
    
    # 检查DeepSeek token
    if not os.path.exists(config.deepseek_token_path):
        issues.append(f"DeepSeek token文件不存在: {config.deepseek_token_path}")
    
    # 检查OKX token
    if not os.path.exists(config.okx_token_path):
        issues.append(f"OKX token文件不存在: {config.okx_token_path}")
    
    # OKX API从文件读取，不需要检查环境变量
    return issues

def print_banner():
    """打印启动横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    AI自动交易系统                            ║
║              基于DeepSeek API + OKX交易所                    ║
║                                                              ║
║  支持的币种: BTC, ETH, SOL, BNB, DOGE, XRP                   ║
║  交易模式: 杠杆交易 (最大15倍)                               ║
║  AI模型: DeepSeek Chat                                       ║
║  交易所: OKX                                                 ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI自动交易系统')
    parser.add_argument('--config', type=str, default='config.py', help='配置文件路径')
    parser.add_argument('--interval', type=int, default=3, help='交易间隔(分钟)')
    parser.add_argument('--log-level', type=str, default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='日志级别')
    parser.add_argument('--test-mode', action='store_true', help='测试模式（不执行实际交易）')
    parser.add_argument('--dry-run', action='store_true', help='干跑模式（只分析不交易）')
    parser.add_argument('--enable-prompt-log', action='store_true', default=True, help='启用prompt日志记录')
    parser.add_argument('--disable-prompt-log', action='store_true', help='禁用prompt日志记录')
    parser.add_argument('--initial-value', type=float, help='设置起始账户价值')
    parser.add_argument('--reset-state', action='store_true', help='重置系统状态')
    parser.add_argument('--show-performance', action='store_true', help='显示性能摘要后退出')
    
    args = parser.parse_args()
    
    # 打印启动横幅
    print_banner()
    
    # 加载配置
    config = TradingConfig()
    config.trading_interval_minutes = args.interval
    config.log_level = args.log_level
    
    # 设置日志
    setup_logging(config.log_level, config.log_file)
    logger = logging.getLogger(__name__)
    
    # 检查API配置
    issues = check_api_keys(config)
    if issues:
        logger.error("配置检查失败:")
        for issue in issues:
            logger.error(f"  - {issue}")
        
        logger.error("\n请确保:")
        logger.error("1. agent/deepseek.token 文件存在且包含有效的API密钥")
        logger.error("2. agent/okx.token 文件存在且包含有效的API密钥")
        logger.error("3. 设置了OKX API的环境变量:")
        logger.error("   export OKX_API_KEY='your_api_key'")
        logger.error("   export OKX_SECRET_KEY='your_secret_key'")
        logger.error("   export OKX_PASSPHRASE='your_passphrase'")
        
        sys.exit(1)
    
    try:
        # 确定prompt日志开关
        enable_prompt_log = args.enable_prompt_log and not args.disable_prompt_log
        
        # 处理状态管理相关选项
        if args.reset_state:
            logger.info("重置系统状态...")
            from state_manager import StateManager
            state_mgr = StateManager()
            state_mgr.reset_state(args.initial_value)
            logger.info("系统状态已重置")
            if args.initial_value:
                logger.info(f"起始资金设置为: ${args.initial_value:,.2f}")
        
        if args.show_performance:
            logger.info("显示性能摘要...")
            from state_manager import StateManager
            state_mgr = StateManager()
            summary = state_mgr.get_performance_summary()
            
            print("\n" + "=" * 60)
            print("交易性能摘要")
            print("=" * 60)
            print(f"起始时间: {summary['start_time']}")
            print(f"起始资金: ${summary['initial_value']:,.2f}")
            print(f"当前PnL: ${summary['total_pnl']:,.2f}")
            print(f"总收益率: {summary['total_return_pct']:.2f}%")
            print(f"总交易次数: {summary['total_trades']}")
            print(f"成功交易: {summary['successful_trades']}")
            print(f"失败交易: {summary['failed_trades']}")
            print(f"胜率: {summary['win_rate']:.2%}")
            print(f"最大回撤: ${summary['max_drawdown']:,.2f}")
            print(f"最佳交易: ${summary['best_trade']:,.2f}")
            print(f"最差交易: ${summary['worst_trade']:,.2f}")
            print(f"会话次数: {summary['session_count']}")
            print(f"总调用次数: {summary['invocation_count']}")
            print(f"运行时间: {summary['elapsed_time']}")
            print("=" * 60)
            return
        
        # 初始化交易agent
        logger.info("初始化交易agent...")
        agent = TradingAgent(
            deepseek_token_path=config.deepseek_token_path,
            okx_token_path=config.okx_token_path,
            enable_prompt_log=enable_prompt_log
        )
        
        # 设置起始资金（如果指定）
        if args.initial_value and not args.reset_state:
            logger.info(f"设置起始资金: ${args.initial_value:,.2f}")
            agent.state_manager.set_initial_account_value(args.initial_value)
        
        # 设置测试模式
        if args.test_mode:
            logger.info("运行在测试模式")
            agent.okx.exchange.sandbox = True
        
        if args.dry_run:
            logger.info("运行在干跑模式 - 只分析不执行交易")
            # 可以在这里修改agent的行为
        
        # 显示配置信息
        logger.info(f"交易间隔: {config.trading_interval_minutes} 分钟")
        logger.info(f"支持币种: {', '.join(config.supported_coins)}")
        logger.info(f"最大杠杆: {config.max_leverage}x")
        logger.info(f"最大风险比例: {config.max_risk_per_trade:.1%}")
        logger.info(f"最大持仓数: {config.max_positions}")
        logger.info(f"Prompt日志: {'启用' if enable_prompt_log else '禁用'}")
        
        # 开始交易
        logger.info("开始自动交易...")
        agent.start_trading(interval_minutes=config.trading_interval_minutes)
        
    except KeyboardInterrupt:
        logger.info("收到停止信号，程序退出")
    except Exception as e:
        logger.error(f"程序运行异常: {e}")
        raise

if __name__ == "__main__":
    main()
