import logging
from agent_trader import TradingAgent


def main():
    # 设置日志
    logging.basicConfig(level=logging.INFO)

    # ============ 超级反指模式开关 ============
    # True: AI 的所有决策将被反转执行（BUY→SELL, SELL→BUY）
    # False: 正常模式，按 AI 决策执行
    CONTRA_MODE = True
    # =========================================

    # 初始化交易agent
    agent = TradingAgent(contra_mode=CONTRA_MODE)

    # 开始交易（间隔2分钟）
    agent.start_trading(interval_minutes=2)


if __name__ == "__main__":
    main()
