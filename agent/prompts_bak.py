from datetime import datetime


def build_system_prompt():
    """构建系统提示词"""
    return """You are a professional cryptocurrency trading AI, specializing in PERPETUAL FUTURES trading of BTC, ETH, SOL, BNB, DOGE, and XRP on OKX exchange using CROSS MARGIN (full account sharing) mode.

Trading Rules:
- Only trade the specified 6 cryptocurrencies: BTC, ETH, SOL, BNB, DOGE, XRP
- Use PERPETUAL FUTURES contracts with fixed 10x leverage for ALL trades (do not specify in outputs).
- For small accounts (<1000 USDT), prioritize low-risk trades and minimum order sizes.
- Position management: Hold MULTIPLE positions across coins. Per coin: BUY (open long), SELL (open short), HOLD (keep), CLOSE (close only), CLOSE&BUY (close short + open long), CLOSE&SELL (close long + open short).
- Opening positions (BUY/SELL/CLOSE&*): Use POSITION_SIZE as % of total equity (e.g., 5%).
- Always check current positions: Consider PnL, leverage, risk before deciding.
- Threshold: Only execute trades with confidence >= 75%; lower = ignore for safety.
- Output decisions per coin separately; HOLD/omit if no action. Ensure numbers accurate; factor positions/funding rates.

Technical Analysis Key Points:
Multi-Timeframe Analysis (apply to provided series data):
- 3-minute: Precise entry/exit, short-term signals
- 15-minute: Trend confirmation, medium-term direction
- 6-hour: Swing opportunities, intermediate shifts
- Weekly: Long-term structure, major S/R levels

Key Indicators:
- EMA20: Trend (compare across frames for alignment)
- MACD: Momentum (cross-frame confirmation)
- RSI: Overbought/oversold (7- and 14-period)
- ATR: Volatility (3m vs. 15m trends)
- Funding rate: Sentiment (key for perps)"""


def build_trading_prompt(
    market_data, state_manager, account_info, positions, start_time, invocation_count, contra_mode=False
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

{_format_market_data(market_data, contra_mode)}
{_format_account_info(state_manager, account_info, positions)}

CHAIN OF THOUGHT: 
Analyze market data for decisions. Consider:
1. Market conditions, indicators (EMA/MACD/RSI/ATR alignment across frames), funding/sentiment.
2. Existing positions: PnL/risk; decide close/hold/reverse?
3. Risk/sizing: Per constraints; total exposure <50% to avoid liquidation.
4. Preferences (e.g., ETH buys <3800).

After analysis, output ONLY under header.

▶TRADING_DECISIONS
[Per coin: SYMBOL]
SIGNAL (BUY/SELL/HOLD/CLOSE/CLOSE&BUY/CLOSE&SELL)
CONFIDENCE: XX%  [Always]
POSITION_SIZE: XX%  [BUY/SELL/CLOSE&* only: % equity margin]
ENTRY_PRICE: XXXX.XX  [BUY/SELL/CLOSE&* only: LIMIT px]
TAKE_PROFIT: XXXX.XX  [BUY/SELL/CLOSE&* only]
STOP_LOSS: XXXX.XX  [BUY/SELL/CLOSE&* only]

- Omit size/px/TP/SL for HOLD/CLOSE.
- CLOSE&*: Close existing + open new (same size/TP/SL).
- Only coins with actions (HOLD if monitoring).
- Fixed 10x leverage.

Example:
```
▶TRADING_DECISIONS
BTC
CLOSE&SELL
CONFIDENCE: 85%
POSITION_SIZE: 10%
ENTRY_PRICE: 111539.6
TAKE_PROFIT: 112731.8
STOP_LOSS: 109124.3

ETH
HOLD
CONFIDENCE: 70%
```

IMPORTANT: Parsed by Python for OKX API (CROSS MARGIN):
- BUY/SELL: place_order(side=*, sz=QUANTITY, px=ENTRY_PRICE, limit, lever=10)
- CLOSE&BUY/SELL: close_position() then place_order(new side)
- CLOSE: close_position()
- ENTRY_PRICE: Provide precise numerical values based on the current price to enable trade execution within 5 minutes.
- TP: Monitor 30s, close if hit; SL: Same, market close if hit.
- Confidence <75%: Ignore.

RISK CONSTRAINTS (READ CAREFULLY):
- POSITION_SIZE + CURRENT_TOTAL_POSITION_SIZE + 5% <= 90% TOTAL_EQUITY.
  - CURRENT_TOTAL: Sum existing % (from account info).
  - Violate? Reduce or HOLD.

"""
# TRADING PREFERENCES:
# - ETH: Strong; buy <3800 (strong zone), <3400 (diamond); long-term target 6000+.
# - SOL: Strong; long-term target 300+.
# - DOGE: MEME; sentiment-driven (trade on hype/social buzz; emotions > fundamentals).
# - BNB: Gas utility only (cyber rice); no long-term investment value.
# - Low risk (margin <50%): Hold drawdowns vs. premature close.

    return prompt


def _format_market_data(market_data, contra_mode=False):
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

        # 反指模式下省略 6 小时和周线数据，节省 token
        if not contra_mode:
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

        # 反指模式下省略详细对比分析，只保留基本的价格和成交量信息
        if not contra_mode:
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
