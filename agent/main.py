import logging
from agent_trader import TradingAgent


def main():
    # 设置日志
    logging.basicConfig(level=logging.INFO)

    # ============ 超级反指模式开关 ============
    # True: AI 的所有决策将被反转执行（BUY→SELL, SELL→BUY）
    # False: 正常模式，按 AI 决策执行
    CONTRA_MODE = False
    # =========================================
    
    # ============ 自动止盈止损监控开关 ============
    # True: 启用自动止盈止损监控（包括价格止盈和收益率止盈）
    # False: 关闭所有自动止盈止损功能
    ENABLE_AUTO_TP_SL = True
    # =========================================
    
    # ============ 收益率自动止盈开关 ============
    # True: 启用收益率 ≥ 1% 自动止盈
    # False: 关闭收益率自动止盈（只保留价格止盈）
    # 注意：只有当 ENABLE_AUTO_TP_SL = True 时才生效
    ENABLE_PROFIT_RATE_TP = False
    # =========================================

    # 初始化交易agent
    agent = TradingAgent(
        contra_mode=CONTRA_MODE,
        enable_auto_tp_sl=ENABLE_AUTO_TP_SL,
        enable_profit_rate_tp=ENABLE_PROFIT_RATE_TP,
    )

    # 开始交易（间隔2分钟）
    agent.start_trading(interval_minutes=2)


if __name__ == "__main__":
    main()
