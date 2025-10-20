from datetime import datetime


def build_system_prompt():
    """构建系统提示词"""
    return """You are a professional cryptocurrency trading AI, specializing in PERPETUAL FUTURES trading of BTC, ETH, SOL, BNB, DOGE, and XRP on OKX exchange using CROSS MARGIN (full account sharing) mode.

Trading Rules:

- Only trade the specified 6 cryptocurrencies: BTC, ETH, SOL, BNB, DOGE, XRP
- Use PERPETUAL FUTURES contracts (not spot trading)
- Use leveraged trading with FIXED 10x leverage for ALL trades
- Every BUY/SELL trade must specify both TAKE_PROFIT and STOP_LOSS prices in the output format
- Set invalidation conditions (e.g., price breaking below a key level)
- For small accounts (<1000 USDT), prioritize low-risk trades and consider minimum order sizes.
- Position management: You can hold MULTIPLE positions across different coins. For each coin, decide independently: BUY (open long), SELL (open short), HOLD (keep if exists), or CLOSE (close if exists).
- Always check current positions before making trading decisions. Consider the current PnL, leverage, and risk of existing positions.
- Trading threshold: Only trades with confidence >= 75% will be executed. Lower confidence trades will be ignored for safety.

Technical Analysis Key Points:

- EMA20: Trend direction
- MACD: Momentum changes
- RSI: Overbought/oversold conditions
- ATR: Volatility
- Funding rate: Market sentiment (important for perpetual futures)

Notes:

- Output decisions for each coin separately
- If no action needed for a coin, output HOLD or omit
- All trades use FIXED 10x leverage - do not specify leverage in decisions
- Ensure all numbers are accurate and error-free
- Consider current position holdings and funding rates
- Remember this is PERPETUAL FUTURES trading in CROSS MARGIN mode
- Use CLOSE to explicitly close an existing position without opening a new one."""


def build_trading_prompt(
    market_data, state_manager, account_info, positions, start_time, invocation_count
):
    """构建交易提示词"""
    current_time = datetime.now()
    elapsed_minutes = (current_time - start_time).total_seconds() / 60

    prompt = f"""It has been {elapsed_minutes:.0f} minutes since you started trading. The current time is {current_time} and you've been invoked {invocation_count} times. Below, we are providing you with a variety of state data, price data, and predictive signals so you can discover alpha. Below that is your current account information, value, performance, positions, etc.

ALL OF THE PRICE OR SIGNAL DATA BELOW IS ORDERED: OLDEST → NEWEST

Timeframes note: Unless stated otherwise in a section title, intraday series are provided at 3‑minute intervals. If a coin uses a different interval, it is explicitly stated in that coin's section.

{_format_market_data(market_data)}
{_format_account_info(state_manager, account_info, positions)}


CHAIN OF THOUGHT: 
Please analyze the market data and provide your trading decisions. Consider:
1. Current market conditions and technical indicators
2. Your existing positions and their performance:
   - Check if you have any open positions
   - Analyze the PnL and risk of existing positions
   - Consider whether to close existing positions or hold them
3. Risk management and position sizing
4. Market sentiment and funding rates
5. Portfolio leverage and total exposure

After your analysis, provide your trading decisions in the following format:

▶TRADING_DECISIONS
For each coin you want to trade, output:
COIN
SIGNAL (BUY/SELL/HOLD/CLOSE)
CONFIDENCE%
QUANTITY: amount
TAKE_PROFIT: price (for BUY/SELL only)
STOP_LOSS: price (for BUY/SELL only)

Example: 
```
▶TRADING_DECISIONS
BTC
BUY
CONFIDENCE: 85%
QUANTITY: 0.1
TAKE_PROFIT: 50000
STOP_LOSS: 45000

ETH
HOLD
CONFIDENCE: 70%
```

If holding or closing, just output the signal and confidence.
All trades automatically use 10x leverage - do not specify leverage.
For BUY/SELL trades, you MUST specify both TAKE_PROFIT and STOP_LOSS prices.

IMPORTANT: Your output will be parsed by Python and then executed through OKX Futures API:
- BUY signals will call okx.place_order(symbol, "buy", quantity, "market", leverage=10)
- SELL signals will call okx.place_order(symbol, "sell", quantity, "market", leverage=10)  
- CLOSE signals will call okx.close_position(symbol)
- TAKE_PROFIT and STOP_LOSS values will be monitored every 30 seconds and automatically trigger okx.close_position() when price targets are hit
- Only trades with confidence >= GATE will be executed. If your confidence is below GATE, the trade will be ignored for safety reasons. Be honest about your confidence level.

OKX Futures API Details:
- Trading pairs: BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT, BNB/USDT:USDT, DOGE/USDT:USDT, XRP/USDT:USDT
- Order types: market orders for immediate execution
- Leverage: Fixed 10x for all positions
- Margin mode: Cross margin (full account sharing)
- Position management: Multiple positions allowed across different coins

"""
    return prompt


def _format_market_data(market_data):
    """格式化市场数据为提示词格式"""
    prompt = "CURRENT MARKET STATE FOR ALL COINS\n"

    for coin, data in market_data.items():
        prompt += f"\nALL {coin} DATA\n"
        prompt += f"current_price = {data['current_price']}, "
        prompt += f"current_ema20 = {data['ema20']:.3f}, "
        prompt += f"current_macd = {data['macd']:.3f}, "
        prompt += f"current_rsi (7 period) = {data['rsi_7']:.3f}\n"

        prompt += f"\nIn addition, here is the latest {coin} open interest and funding rate for perps (the instrument you are trading):\n\n"
        prompt += f"Open Interest: Latest: {data['open_interest']} Average: {data['open_interest']}\n\n"
        prompt += f"Funding Rate: {data['funding_rate']}\n\n"

        prompt += "Intraday series (by minute, oldest → latest):\n\n"
        prompt += f"Mid prices: {data['price_series']}\n\n"
        prompt += f"EMA indicators (20‑period): {data['ema_series']}\n\n"
        prompt += f"MACD indicators: {data['macd_series']}\n\n"
        prompt += f"RSI indicators (7‑Period): {data['rsi_series']}\n\n"
        prompt += f"RSI indicators (14‑Period): {data['rsi_14_series']}\n\n"

        prompt += "Longer‑term context (4‑hour timeframe):\n\n"
        prompt += f"20‑Period EMA: {data['ema20']:.3f} vs. 50‑Period EMA: {data['ema20']:.3f}\n\n"
        prompt += f"3‑Period ATR: {data['atr_3']:.3f} vs. 14‑Period ATR: {data['atr_14']:.3f}\n\n"
        prompt += f"Current Volume: {data['volume']:.3f} vs. Average Volume: {data['volume']:.3f}\n\n"
        prompt += f"MACD indicators: {data['macd_series']}\n\n"
        prompt += f"RSI indicators (14‑Period): {data['rsi_14_series']}\n\n"

    return prompt


def _format_account_info(state_manager, account_info, positions):
    """格式化账户信息"""
    prompt = "\nHERE IS YOUR ACCOUNT INFORMATION & PERFORMANCE\n"

    # 计算总收益率（基于起始资金）
    initial_value = state_manager.get_initial_account_value()
    current_value = account_info["total_usdt"]
    total_return_pct = (
        ((current_value - initial_value) / initial_value) * 100
        if initial_value > 0
        else 0
    )

    # 新：计算Sharpe Ratio（简化版，使用历史PnL）
    # 假设 state_manager 有 get_pnl_history() 返回每日PnL列表
    pnl_history = state_manager.get_pnl_history()  # 需要在 state_manager 中实现
    if pnl_history and len(pnl_history) > 1:
        returns = [(pnl / initial_value) for pnl in pnl_history]  # 日回报率
        avg_return = sum(returns) / len(returns)
        std_dev = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
        risk_free_rate = 0.0  # 假设无风险率为0
        sharpe_ratio = (avg_return - risk_free_rate) / std_dev if std_dev > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    prompt += f"Current Total Return (percent): {total_return_pct:.2f}%\n\n"
    prompt += f"Available Cash: {account_info['free_usdt']:.2f}\n\n"
    prompt += f"Current Account Value: {current_value:.2f}\n\n"

    if positions:
        prompt += "Current live positions & performance:\n"
        total_position_value = 0
        total_unrealized_pnl = 0

        for coin, pos in positions.items():
            # 计算仓位详细信息
            position_value = pos.get(
                "position_value", abs(pos["size"]) * pos["current_price"]
            )
            margin_used = pos.get(
                "margin_used",
                position_value / pos["leverage"] if pos["leverage"] > 0 else 0,
            )
            pnl_percentage = (
                (pos["unrealized_pnl"] / (abs(pos["size"]) * pos["entry_price"])) * 100
                if pos["size"] != 0 and pos["entry_price"] != 0
                else 0
            )

            total_position_value += position_value
            total_unrealized_pnl += pos["unrealized_pnl"]

            prompt += f"\n{coin} Position Details:\n"
            prompt += f"  Symbol: {pos.get('symbol', f'{coin}/USDT:USDT')}\n"
            prompt += f"  Side: {pos['side']}\n"
            prompt += f"  Size: {pos['size']}\n"
            prompt += f"  Entry Price: {pos['entry_price']:.4f}\n"
            prompt += f"  Current Price: {pos['current_price']:.4f}\n"
            prompt += (
                f"  Mark Price: {pos.get('mark_price', pos['current_price']):.4f}\n"
            )
            prompt += f"  Leverage: {pos['leverage']}x\n"
            prompt += f"  Position Value: ${position_value:.2f}\n"
            prompt += f"  Margin Used: ${margin_used:.2f}\n"
            prompt += f"  Unrealized PnL: ${pos['unrealized_pnl']:.2f} ({pnl_percentage:.2f}%)\n"
            prompt += f"  Liquidation Price: {pos.get('liquidation_price', 'N/A')}\n"
            prompt += f"  Percentage: {pos.get('percentage', 0):.2f}%\n"
            prompt += f"  Timestamp: {pos.get('timestamp', 'N/A')}\n"

        # 添加总体仓位统计
        prompt += f"\nPortfolio Summary:\n"
        prompt += f"  Total Position Value: ${total_position_value:.2f}\n"
        prompt += f"  Total Unrealized PnL: ${total_unrealized_pnl:.2f}\n"
        prompt += f"  Number of Positions: {len(positions)}\n"
        prompt += f"  Portfolio Leverage: {total_position_value / current_value:.2f}x\n"
    else:
        prompt += "Current live positions: None\n"
        prompt += "You have no open positions. You can open new positions.\n"

    prompt += f"\nSharpe Ratio: {sharpe_ratio:.2f}\n\n"

    return prompt
