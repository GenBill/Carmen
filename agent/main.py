import logging
from agent_trader import TradingAgent


def main():
    # 设置日志
    logging.basicConfig(level=logging.INFO)

    # 初始化交易agent
    agent = TradingAgent()

    # 开始交易（间隔3分钟）
    agent.start_trading(interval_minutes=2)


if __name__ == "__main__":
    main()
