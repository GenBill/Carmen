"""
AI自动交易系统配置示例
复制此文件为 config.py 并根据需要修改配置
"""

import os
from config import TradingConfig

# 创建自定义配置
custom_config = TradingConfig(
    # API配置
    deepseek_token_path="agent/deepseek.token",
    okx_token_path="agent/okx.token",
    
    # OKX API配置（建议使用环境变量）
    okx_api_key=os.getenv('OKX_API_KEY', ''),
    okx_secret_key=os.getenv('OKX_SECRET_KEY', ''),
    okx_passphrase=os.getenv('OKX_PASSPHRASE', ''),
    okx_sandbox=True,  # 生产环境设为False
    
    # 交易参数
    supported_coins=['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP'],
    max_leverage=15,
    max_risk_per_trade=0.05,  # 单笔交易最大风险比例5%
    trading_interval_minutes=3,  # 交易决策间隔3分钟
    
    # 风险管理
    max_positions=6,  # 最大同时持仓数
    stop_loss_pct=0.02,  # 默认止损百分比2%
    take_profit_pct=0.04,  # 默认止盈百分比4%
    
    # 日志配置
    log_level="INFO",
    log_file="trading_log.txt"
)

# 高级配置示例
advanced_config = TradingConfig(
    # 更保守的交易设置
    max_leverage=10,
    max_risk_per_trade=0.03,  # 降低风险到3%
    trading_interval_minutes=5,  # 增加决策间隔
    
    # 更严格的风险控制
    max_positions=4,
    stop_loss_pct=0.015,  # 更紧的止损
    take_profit_pct=0.03,  # 更小的止盈目标
    
    # 详细日志
    log_level="DEBUG"
)

# 激进配置示例（不推荐新手使用）
aggressive_config = TradingConfig(
    # 高风险设置
    max_leverage=15,
    max_risk_per_trade=0.08,  # 高风险8%
    trading_interval_minutes=1,  # 频繁交易
    
    # 宽松的风险控制
    max_positions=8,
    stop_loss_pct=0.03,
    take_profit_pct=0.06,
    
    # 生产环境
    okx_sandbox=False
)

# 选择配置
# 将下面的配置名称改为你想要的配置
selected_config = custom_config

# 导出配置
config = selected_config

# 配置说明
"""
配置参数说明：

1. API配置
   - deepseek_token_path: DeepSeek API密钥文件路径
   - okx_token_path: OKX API密钥文件路径
   - okx_*: OKX API相关配置，建议使用环境变量

2. 交易参数
   - supported_coins: 支持的交易币种列表
   - max_leverage: 最大杠杆倍数
   - max_risk_per_trade: 单笔交易最大风险比例
   - trading_interval_minutes: 交易决策间隔（分钟）

3. 风险管理
   - max_positions: 最大同时持仓数
   - stop_loss_pct: 默认止损百分比
   - take_profit_pct: 默认止盈百分比

4. 日志配置
   - log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
   - log_file: 日志文件名

建议配置策略：
- 新手：使用custom_config，保守设置
- 有经验：使用advanced_config，平衡风险收益
- 专业：使用aggressive_config，高风险高收益（需谨慎）
"""
