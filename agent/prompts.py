from datetime import datetime


def build_system_prompt():
    """构建系统提示词"""
    return """You are a professional cryptocurrency trading AI, specializing in PERPETUAL FUTURES trading of BTC, ETH, SOL, BNB, DOGE, and XRP on OKX exchange using CROSS MARGIN (full account sharing) mode.

Trading Rules:

- Only trade the specified 6 cryptocurrencies: BTC, ETH, SOL, BNB, DOGE, XRP
- Use 10x leverage PERPETUAL FUTURES contracts for ALL trades.
- For small accounts (<1000 USDT), consider minimum order sizes.
- Position management: You can hold MULTIPLE positions across different coins. For each coin, decide independently: BUY (open long), SELL (open short), HOLD (keep if exists), or CLOSE (close if exists).
- When opening positions (BUY or SELL), specify the position size using a percentage of the account balance (e.g., 5% of total equity), rather than fixed coins or numerical amounts.
- Always check current positions before making trading decisions. Consider the current PnL, leverage, and risk of existing positions.
- Trading threshold: Only trades with confidence >= GATE will be executed. Lower confidence trades will be ignored for safety.

Technical Analysis Key Points:

Multi-Timeframe Analysis:
- 3-minute data: For precise entry/exit timing and short-term signals
- 15-minute data: For trend confirmation and medium-term direction

Key Indicators:
- EMA20: Trend direction (compare 3m vs 15m for trend alignment)
- MACD: Momentum changes (cross-timeframe confirmation)
- RSI: Overbought/oversold conditions (both 7 and 14 periods)
- ATR: Volatility (compare 3m vs 15m for volatility trends)
- Funding rate: Market sentiment (important for perpetual futures)

Trading Strategy:
- Use 15-minute data to confirm trend direction
- Use 3-minute data for precise entry/exit timing
- Look for alignment between timeframes for higher confidence trades
- Consider divergence between 3m and 15m indicators as warning signals

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

Timeframes note: The system provides data at two timeframes:
- 3-minute intervals: For short-term trading signals and precise entry/exit timing
- 15-minute intervals: For medium-term trend analysis and trend confirmation

Unless stated otherwise, intraday series are provided at 3‑minute intervals. 15-minute data is explicitly labeled with "_15m" suffix.

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
After your analysis, provide your trading decisions in the following exact format. Output only the decisions under the header—nothing else.

▶TRADING_DECISIONS
[For each coin: COIN_SYMBOL on a new line]
SIGNAL (BUY / SELL / HOLD / CLOSE / CLOSE&SELL / CLOSE&BUY)
CONFIDENCE: XX%  [Always include; e.g., CONFIDENCE: 85%]
POSITION_SIZE: XX%  [For BUY/SELL/CLOSE&SELL/CLOSE&BUY only: percentage of total equity used as margin, e.g., POSITION_SIZE: 10%]
ENTRY_PRICE: XXXXX  [For BUY/SELL/CLOSE&SELL/CLOSE&BUY only: exact price for LIMIT order, e.g., ENTRY_PRICE: 48888]
TAKE_PROFIT: XXXXX  [For BUY/SELL/CLOSE&SELL/CLOSE&BUY only: exact price for TAKE PROFIT, e.g., TAKE_PROFIT: 50000]
STOP_LOSS: XXXXX  [For BUY/SELL/CLOSE&SELL/CLOSE&BUY only: exact price for STOP LOSS, e.g., STOP_LOSS: 45000]

- Omit POSITION_SIZE and ENTRY_PRICE for HOLD or CLOSE.
- CLOSE&SELL: Close current long position and open new short position immediately
- CLOSE&BUY: Close current short position and open new long position immediately
- Only include coins with decisions (HOLD if no action but monitoring).
- All trades use fixed 10x leverage—do not mention it.

Example:
```
▶TRADING_DECISIONS
BTC
CLOSE&SELL
CONFIDENCE: 85%
POSITION_SIZE: 10%
ENTRY_PRICE: 47500
TAKE_PROFIT: 45000
STOP_LOSS: 50000

ETH
HOLD
CONFIDENCE: 70%
```

QUANTITY Calculation (for Python parsing):
QUANTITY = (POSITION_SIZE / 100) * TOTAL_EQUITY * LEVERAGE / ENTRY_PRICE
- POSITION_SIZE: Decimal percentage (e.g., 10 for 10%).
- TOTAL_EQUITY: Current account equity in USDT.
- LEVERAGE: Fixed at 10.
- ENTRY_PRICE: Coin price in USDT.

IMPORTANT: This output will be parsed by Python and executed via OKX Futures API in CROSS MARGIN mode:
- BUY: okx.place_order(symbol="COIN-USDT-SWAP", side="buy", sz=QUANTITY, px=ENTRY_PRICE, ordType="limit", lever=10)
- SELL: okx.place_order(symbol="COIN-USDT-SWAP", side="sell", sz=QUANTITY, px=ENTRY_PRICE, ordType="limit", lever=10)
- CLOSE: okx.close_position(symbol="COIN-USDT-SWAP")
- TAKE_PROFIT values (but no STOP_LOSS) will be monitored every 30 seconds and automatically trigger okx.close_position() when price targets are hit
- Only signals with CONFIDENCE >= 75% will execute. Output honestly but expect ignore for safety—do not force trades.

RISK CONSTRAINTS (READ CAREFULLY):
- When deciding POSITION_SIZE (%), ensure: POSITION_SIZE + CURRENT_TOTAL_POSITION_SIZE + 5% <= 80% of total equity (TOTAL_EQUITY).
  - CURRENT_TOTAL_POSITION_SIZE: Sum of all existing positions' margin percentages.
  - If violated, reduce POSITION_SIZE or output HOLD.

"""
    return prompt


def _format_market_data(market_data):
    """格式化市场数据为提示词格式"""
    prompt = "CURRENT MARKET STATE FOR ALL COINS\n"

    for coin, data in market_data.items():
        prompt += f"\nALL {coin} DATA\n"
        prompt += f"current_price = {data['current_price']}\n"

        prompt += f"\nIn addition, here is the latest {coin} open interest and funding rate for perps (the instrument you are trading):\n\n"
        prompt += f"Open Interest: Latest: {data['open_interest']}\n\n"
        prompt += f"Funding Rate: {data['funding_rate']}\n\n"

        # 3分钟数据
        prompt += f"\n3-MINUTE TIMEFRAME DATA:\n"
        prompt += f"current_ema20_3m = {data['ema20_3m']:.3f}, "
        prompt += f"current_macd_3m = {data['macd_3m']:.3f}, "
        prompt += f"current_rsi_7_3m = {data['rsi_7_3m']:.3f}, "
        prompt += f"current_rsi_14_3m = {data['rsi_14_3m']:.3f}\n"

        # 3分钟序列数据
        prompt += "3-MINUTE SERIES (oldest → latest):\n\n"
        prompt += f"Mid prices (3m): {data['price_series_3m']}\n\n"
        prompt += f"EMA indicators (20‑period, 3m): {data['ema_series_3m']}\n\n"
        prompt += f"MACD indicators (3m): {data['macd_series_3m']}\n\n"
        prompt += f"RSI indicators (7‑Period, 3m): {data['rsi_series_3m']}\n\n"
        prompt += f"RSI indicators (14‑Period, 3m): {data['rsi_14_series_3m']}\n\n"

        # 15分钟数据
        prompt += f"\n15-MINUTE TIMEFRAME DATA:\n"
        prompt += f"current_ema20_15m = {data['ema20_15m']:.3f}, "
        prompt += f"current_macd_15m = {data['macd_15m']:.3f}, "
        prompt += f"current_rsi_7_15m = {data['rsi_7_15m']:.3f}, "
        prompt += f"current_rsi_14_15m = {data['rsi_14_15m']:.3f}\n"

        # 15分钟序列数据
        prompt += "15-MINUTE SERIES (oldest → latest):\n\n"
        prompt += f"Mid prices (15m): {data['price_series_15m']}\n\n"
        prompt += f"EMA indicators (20‑period, 15m): {data['ema_series_15m']}\n\n"
        prompt += f"MACD indicators (15m): {data['macd_series_15m']}\n\n"
        prompt += f"RSI indicators (7‑Period, 15m): {data['rsi_series_15m']}\n\n"
        prompt += f"RSI indicators (14‑Period, 15m): {data['rsi_14_series_15m']}\n\n"

        # 6小时数据
        prompt += f"\n6-HOUR TIMEFRAME DATA:\n"
        prompt += f"current_ema20_6h = {data['ema20_6h']:.3f}, "
        prompt += f"current_macd_6h = {data['macd_6h']:.3f}, "
        prompt += f"current_rsi_7_6h = {data['rsi_7_6h']:.3f}, "
        prompt += f"current_rsi_14_6h = {data['rsi_14_6h']:.3f}\n"

        # 6小时序列数据
        prompt += "6-HOUR SERIES (oldest → latest):\n\n"
        prompt += f"Mid prices (6h): {data['price_series_6h']}\n\n"
        prompt += f"EMA indicators (20‑period, 6h): {data['ema_series_6h']}\n\n"
        prompt += f"MACD indicators (6h): {data['macd_series_6h']}\n\n"
        prompt += f"RSI indicators (7‑Period, 6h): {data['rsi_series_6h']}\n\n"
        prompt += f"RSI indicators (14‑Period, 6h): {data['rsi_14_series_6h']}\n\n"

        # 周线数据
        prompt += f"\nWEEKLY TIMEFRAME DATA:\n"
        prompt += f"current_ema20_wk = {data['ema20_wk']:.3f}, "
        prompt += f"current_macd_wk = {data['macd_wk']:.3f}, "
        prompt += f"current_rsi_7_wk = {data['rsi_7_wk']:.3f}, "
        prompt += f"current_rsi_14_wk = {data['rsi_14_wk']:.3f}\n"

        # 周线序列数据
        prompt += "WEEKLY SERIES (oldest → latest):\n\n"
        prompt += f"Mid prices (wk): {data['price_series_wk']}\n\n"
        prompt += f"EMA indicators (20‑period, wk): {data['ema_series_wk']}\n\n"
        prompt += f"MACD indicators (wk): {data['macd_series_wk']}\n\n"
        prompt += f"RSI indicators (7‑Period, wk): {data['rsi_series_wk']}\n\n"
        prompt += f"RSI indicators (14‑Period, wk): {data['rsi_14_series_wk']}\n\n"

        # 技术指标对比分析
        prompt += "TIMEFRAME COMPARISON ANALYSIS:\n\n"
        prompt += (
            f"3m vs 15m EMA20: {data['ema20_3m']:.3f} vs {data['ema20_15m']:.3f}\n\n"
        )
        prompt += f"3m vs 15m MACD: {data['macd_3m']:.3f} vs {data['macd_15m']:.3f}\n\n"
        prompt += (
            f"3m vs 15m RSI(7): {data['rsi_7_3m']:.3f} vs {data['rsi_7_15m']:.3f}\n\n"
        )
        prompt += f"3m vs 15m RSI(14): {data['rsi_14_3m']:.3f} vs {data['rsi_14_15m']:.3f}\n\n"

        prompt += f"3‑Period ATR (3m): {data['atr_3_3m']:.3f} vs 14‑Period ATR (3m): {data['atr_14_3m']:.3f}\n\n"
        prompt += f"3‑Period ATR (15m): {data['atr_3_15m']:.3f} vs 14‑Period ATR (15m): {data['atr_14_15m']:.3f}\n\n"
        prompt += f"Current Volume (3m): {data['volume_3m']:.3f} vs Current Volume (15m): {data['volume_15m']:.3f}\n\n"

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
