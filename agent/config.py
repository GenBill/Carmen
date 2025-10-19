import os
from dataclasses import dataclass

@dataclass
class TradingConfig:
    """交易配置类"""
    
    # API配置
    deepseek_token_path: str = "agent/deepseek.token"
    okx_token_path: str = "agent/okx.token"
    
    # OKX API配置（需要从环境变量或配置文件读取）
    okx_api_key: str = ""
    okx_secret_key: str = ""
    okx_passphrase: str = ""
    okx_sandbox: bool = True  # 生产环境设为False
    
    # 交易参数
    supported_coins: list = None
    max_leverage: int = 15
    max_risk_per_trade: float = 0.05  # 单笔交易最大风险比例
    trading_interval_minutes: int = 3
    
    # 风险管理
    max_positions: int = 6  # 最大同时持仓数
    stop_loss_pct: float = 0.02  # 默认止损百分比
    take_profit_pct: float = 0.04  # 默认止盈百分比
    
    # 日志配置
    log_level: str = "INFO"
    log_file: str = "trading_log.txt"
    
    def __post_init__(self):
        if self.supported_coins is None:
            self.supported_coins = ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP']
        
        # 从环境变量读取OKX配置
        self.okx_api_key = os.getenv('OKX_API_KEY', self.okx_api_key)
        self.okx_secret_key = os.getenv('OKX_SECRET_KEY', self.okx_secret_key)
        self.okx_passphrase = os.getenv('OKX_PASSPHRASE', self.okx_passphrase)
        
        # 从环境变量读取是否使用沙盒
        sandbox_env = os.getenv('OKX_SANDBOX', 'true').lower()
        self.okx_sandbox = sandbox_env in ['true', '1', 'yes']

# 默认配置实例
default_config = TradingConfig()
