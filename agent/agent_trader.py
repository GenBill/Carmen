import json
import time
from datetime import datetime
from deepseek import DeepSeekAPI
from okx_api import OKXTrader
from state_manager import StateManager
import logging

class TradingAgent:
    def __init__(self, deepseek_token_path="agent/deepseek.token", okx_token_path="agent/okx.token", enable_prompt_log=True):
        """初始化交易agent"""
        self.okx = OKXTrader(okx_token_path)
        
        # 构建系统提示词
        system_prompt = self._build_system_prompt()
        self.deepseek = DeepSeekAPI(deepseek_token_path, system_prompt)
        
        # 设置日志
        logging.basicConfig(
            filename='trading_log.txt',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Prompt日志开关
        self.enable_prompt_log = enable_prompt_log
        if self.enable_prompt_log:
            self.prompt_logger = logging.getLogger('prompt_logger')
            self.prompt_logger.setLevel(logging.INFO)
            # 创建专门的prompt日志文件处理器
            prompt_handler = logging.FileHandler('prompt_log.txt', encoding='utf-8')
            prompt_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
            self.prompt_logger.addHandler(prompt_handler)
        
        # 状态管理器
        self.state_manager = StateManager()
        
        # 交易统计（从状态管理器获取）
        self.start_time = self.state_manager.get_start_time()
        self.invocation_count = self.state_manager.get_invocation_count()
        
        # 显示状态信息
        self.logger.info(f"系统状态: 会话 {self.state_manager.get_session_count()}, 调用次数 {self.invocation_count}")
        self.logger.info(f"起始时间: {self.start_time}")
        self.logger.info(f"起始资金: ${self.state_manager.get_initial_account_value():,.2f}")
        
    def _build_system_prompt(self):
        """构建系统提示词"""
        return """You are a professional cryptocurrency trading AI, specializing in trading BTC, ETH, SOL, BNB, DOGE, and XRP.
Trading Rules:

Only trade the specified 6 cryptocurrencies: BTC, ETH, SOL, BNB, DOGE, XRP
Use leveraged trading, with a maximum leverage of 15x
Every trade must set a take-profit target and stop-loss price
Set invalidation conditions (e.g., price breaking below a key level)
Risk control: Single trade risk must not exceed 5% of total capital
Position management: Diversify investments, do not concentrate on a single cryptocurrency

Technical Analysis Key Points:

EMA20: Trend direction
MACD: Momentum changes
RSI: Overbought/oversold conditions
ATR: Volatility
Funding rate: Market sentiment

Notes:

Only output cryptocurrencies with trading signals
If there are no clear trading opportunities, output "HOLD" or omit that cryptocurrency
Ensure all numbers are accurate and error-free
Consider current position holdings"""

    def _format_market_data(self, market_data):
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

    def _format_account_info(self, account_info, positions):
        """格式化账户信息"""
        prompt = "\nHERE IS YOUR ACCOUNT INFORMATION & PERFORMANCE\n"
        
        # 计算总收益率（基于起始资金）
        initial_value = self.state_manager.get_initial_account_value()
        current_value = account_info['total_usdt']
        total_return_pct = ((current_value - initial_value) / initial_value) * 100 if initial_value > 0 else 0
        
        prompt += f"Current Total Return (percent): {total_return_pct:.2f}%\n\n"
        prompt += f"Available Cash: {account_info['free_usdt']:.2f}\n\n"
        prompt += f"Current Account Value: {current_value:.2f}\n\n"
        
        if positions:
            prompt += "Current live positions & performance: "
            position_strs = []
            for coin, pos in positions.items():
                pos_str = f"{{'symbol': '{coin}', 'quantity': {pos['size']}, "
                pos_str += f"'entry_price': {pos['entry_price']}, "
                pos_str += f"'current_price': {pos['current_price']}, "
                pos_str += f"'liquidation_price': {pos.get('liquidation_price', 0)}, "
                pos_str += f"'unrealized_pnl': {pos['unrealized_pnl']}, "
                pos_str += f"'leverage': {pos['leverage']}, "
                pos_str += f"'exit_plan': {{'profit_target': {pos.get('profit_target', 0)}, 'stop_loss': {pos.get('stop_loss', 0)}, 'invalidation_condition': '{pos.get('invalidation_condition', 'None')}'}}, "
                pos_str += f"'confidence': {pos.get('confidence', 0.5)}, "
                pos_str += f"'risk_usd': {pos.get('risk_usd', 0)}, "
                pos_str += f"'sl_oid': {pos.get('sl_oid', -1)}, "
                pos_str += f"'tp_oid': {pos.get('tp_oid', -1)}, "
                pos_str += f"'wait_for_fill': False, "
                pos_str += f"'entry_oid': {pos.get('entry_oid', -1)}, "
                pos_str += f"'notional_usd': {pos.get('notional_usd', 0)}}}"
                position_strs.append(pos_str)
            prompt += " ".join(position_strs) + "\n\n"
        
        prompt += "Sharpe Ratio: 0.019\n\n"
        
        return prompt

    def _build_trading_prompt(self, market_data, account_info, positions):
        """构建完整的交易提示词"""
        # 更新调用次数
        self.state_manager.increment_invocation_count()
        self.invocation_count = self.state_manager.get_invocation_count()
        
        current_time = datetime.now()
        elapsed_minutes = (current_time - self.start_time).total_seconds() / 60
        
        prompt = f"""It has been {elapsed_minutes:.0f} minutes since you started trading. The current time is {current_time} and you've been invoked {self.invocation_count} times. Below, we are providing you with a variety of state data, price data, and predictive signals so you can discover alpha. Below that is your current account information, value, performance, positions, etc.

ALL OF THE PRICE OR SIGNAL DATA BELOW IS ORDERED: OLDEST → NEWEST

Timeframes note: Unless stated otherwise in a section title, intraday series are provided at 3‑minute intervals. If a coin uses a different interval, it is explicitly stated in that coin's section.

{self._format_market_data(market_data)}
{self._format_account_info(account_info, positions)}

▶
CHAIN_OF_THOUGHT
Please analyze the market data and provide your trading decisions. Consider:
1. Current market conditions and technical indicators
2. Your existing positions and their exit plans
3. Risk management and position sizing
4. Market sentiment and funding rates

After your analysis, provide your trading decisions in the following format:

▶
TRADING_DECISIONS
For each coin you want to trade, output:
COIN
SIGNAL (BUY/SELL/HOLD)
CONFIDENCE%
QUANTITY: amount

If holding, just output the signal and confidence."""

        return prompt

    def _parse_trading_decisions(self, response):
        """解析AI的交易决策"""
        try:
            decisions = {}
            lines = response.split('\n')
            
            # 查找TRADING_DECISIONS部分
            in_decisions = False
            current_coin = None
            
            for line in lines:
                line = line.strip()
                
                if line == "TRADING_DECISIONS":
                    in_decisions = True
                    continue
                
                if in_decisions:
                    # 跳过空行和分隔符
                    if not line or line.startswith('▶'):
                        continue
                    
                    # 检查是否是币种名称
                    if line in ['BTC', 'ETH', 'SOL', 'BNB', 'DOGE', 'XRP']:
                        current_coin = line
                        continue
                    
                    # 检查是否是交易信号
                    if current_coin and line in ['BUY', 'SELL', 'HOLD']:
                        decisions[current_coin] = {
                            'signal': line,
                            'confidence': 0.5,  # 默认信心度
                            'quantity': 0  # 默认数量
                        }
                        continue
                    
                    # 解析信心度
                    if current_coin and line.endswith('%'):
                        try:
                            confidence = float(line.replace('%', '')) / 100
                            if current_coin in decisions:
                                decisions[current_coin]['confidence'] = confidence
                        except:
                            pass
                        continue
                    
                    # 解析数量
                    if current_coin and line.startswith('QUANTITY:'):
                        try:
                            quantity = float(line.replace('QUANTITY:', '').strip())
                            if current_coin in decisions:
                                decisions[current_coin]['quantity'] = quantity
                        except:
                            pass
                        continue
            
            return decisions
            
        except Exception as e:
            self.logger.error(f"解析交易决策失败: {e}")
            self.logger.error(f"AI响应: {response}")
            return {}

    def execute_trading_decisions(self, decisions):
        """执行交易决策"""
        executed_trades = []
        
        for coin, decision in decisions.items():
            try:
                signal = decision.get('signal')
                confidence = decision.get('confidence', 0.5)
                quantity = decision.get('quantity', 0)
                coin_symbol = f"{coin}/USDT"
                
                if signal == 'BUY':
                    # 执行买入
                    if quantity > 0 and confidence >= 0.75:
                        order = self.okx.place_order(
                            coin_symbol, 'buy', quantity, 
                            order_type='market'
                        )
                        if order:
                            trade_record = {
                                'coin': coin,
                                'action': 'buy',
                                'quantity': quantity,
                                'confidence': confidence,
                                'order_id': order['id'],
                                'success': True,
                                'pnl': 0.0  # 买入时PnL为0
                            }
                            executed_trades.append(trade_record)
                            self.state_manager.add_trade_record(trade_record)
                            self.logger.info(f"买入 {coin} {quantity} (信心度: {confidence:.1%})")
                
                elif signal == 'SELL':
                    # 执行卖出
                    if quantity > 0 and confidence >= 0.75:
                        order = self.okx.place_order(
                            coin_symbol, 'sell', quantity,
                            order_type='market'
                        )
                        if order:
                            trade_record = {
                                'coin': coin,
                                'action': 'sell',
                                'quantity': quantity,
                                'confidence': confidence,
                                'order_id': order['id'],
                                'success': True,
                                'pnl': 0.0  # 卖出时PnL为0
                            }
                            executed_trades.append(trade_record)
                            self.state_manager.add_trade_record(trade_record)
                            self.logger.info(f"卖出 {coin} {quantity} (信心度: {confidence:.1%})")
                
                elif signal == 'HOLD':
                    # 持有，记录决策
                    executed_trades.append({
                        'coin': coin,
                        'action': 'hold',
                        'confidence': confidence
                    })
                    self.logger.info(f"持有 {coin} (信心度: {confidence:.1%})")
                    
            except Exception as e:
                self.logger.error(f"执行交易失败 {coin}: {e}")
        
        return executed_trades

    def show_performance_summary(self):
        """显示性能摘要"""
        summary = self.state_manager.get_performance_summary()
        
        self.logger.info("=" * 60)
        self.logger.info("交易性能摘要")
        self.logger.info("=" * 60)
        self.logger.info(f"起始时间: {summary['start_time']}")
        self.logger.info(f"起始资金: ${summary['initial_value']:,.2f}")
        self.logger.info(f"当前PnL: ${summary['total_pnl']:,.2f}")
        self.logger.info(f"总收益率: {summary['total_return_pct']:.2f}%")
        self.logger.info(f"总交易次数: {summary['total_trades']}")
        self.logger.info(f"成功交易: {summary['successful_trades']}")
        self.logger.info(f"失败交易: {summary['failed_trades']}")
        self.logger.info(f"胜率: {summary['win_rate']:.2%}")
        self.logger.info(f"最大回撤: ${summary['max_drawdown']:,.2f}")
        self.logger.info(f"最佳交易: ${summary['best_trade']:,.2f}")
        self.logger.info(f"最差交易: ${summary['worst_trade']:,.2f}")
        self.logger.info(f"会话次数: {summary['session_count']}")
        self.logger.info(f"总调用次数: {summary['invocation_count']}")
        self.logger.info(f"运行时间: {summary['elapsed_time']}")
        self.logger.info("=" * 60)

    def run_trading_cycle(self):
        """运行一个完整的交易周期"""
        try:
            # 获取市场数据
            market_data = self.okx.get_market_data()
            if not market_data:
                self.logger.error("获取市场数据失败")
                return
            
            # 获取账户信息
            account_info = self.okx.get_account_info()
            if not account_info:
                self.logger.error("获取账户信息失败")
                return
            
            # 获取当前持仓
            positions = self.okx.get_positions()
            
            # 构建提示词
            prompt = self._build_trading_prompt(market_data, account_info, positions)
            
            # 记录prompt到专门的日志文件
            if self.enable_prompt_log:
                self.prompt_logger.info("=" * 80)
                self.prompt_logger.info(f"第 {self.invocation_count} 次交易决策 - {datetime.now()}")
                self.prompt_logger.info("=" * 80)
                self.prompt_logger.info("INPUT PROMPT:")
                self.prompt_logger.info(prompt)
                self.prompt_logger.info("=" * 80)
            
            # 获取AI决策
            self.logger.info(f"调用DeepSeek API进行交易决策...")
            response = self.deepseek.single_call(prompt)
            
            # 记录AI响应到专门的日志文件
            if self.enable_prompt_log:
                self.prompt_logger.info("AI RESPONSE:")
                self.prompt_logger.info(response)
                self.prompt_logger.info("=" * 80)
            
            # 解析决策
            decisions = self._parse_trading_decisions(response)
            
            if decisions:
                # 执行交易
                executed_trades = self.execute_trading_decisions(decisions)
                self.logger.info(f"交易周期完成，执行了 {len(executed_trades)} 个决策")
                return executed_trades
            else:
                self.logger.info("AI没有给出交易决策")
                return []
                
        except Exception as e:
            self.logger.error(f"交易周期执行失败: {e}")
            return []

    def start_trading(self, interval_minutes=1):
        """开始自动交易"""
        self.logger.info("开始自动交易...")
        
        # 显示性能摘要
        self.show_performance_summary()
        
        # 开始新会话
        self.state_manager.start_new_session()
        
        while True:
            try:
                self.logger.info(f"开始第 {self.invocation_count + 1} 次交易决策...")
                trades = self.run_trading_cycle()
                
                # 每10次交易显示一次性能摘要
                if self.invocation_count % 10 == 0:
                    self.show_performance_summary()
                
                # 等待下次执行
                time.sleep(interval_minutes * 60)
                
            except KeyboardInterrupt:
                self.logger.info("收到停止信号，结束交易")
                # 显示最终性能摘要
                self.show_performance_summary()
                break
            except Exception as e:
                self.logger.error(f"交易循环异常: {e}")
                time.sleep(60)  # 出错时等待1分钟再继续

if __name__ == "__main__":
    agent = TradingAgent()
    agent.start_trading()
