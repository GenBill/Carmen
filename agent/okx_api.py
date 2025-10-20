import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import json

class OKXTrader:
    def __init__(self, api_key_path="agent/okx.token"):
        """初始化OKX交易接口"""
        # 加载API密钥
        with open(api_key_path, "r") as file:
            lines = file.readlines()
            self.api_key = lines[0].strip()
            self.secret = lines[1].strip()
            self.password = lines[2].strip()
        
        # 初始化OKX交易所连接
        self.exchange = ccxt.okx({
            'proxies': {'http': 'http://127.0.0.1:7897', 'https': 'http://127.0.0.1:7897'},
            'apiKey': self.api_key, 
            'secret': self.secret, 
            'password': self.password, 
            'sandbox': False,  # 生产环境设为False
            # 'sandbox': True,  # 使用沙盒环境进行测试
            'enableRateLimit': True, 
            'options': {
                'defaultType': 'swap'  # 永续合约
                # 'defaultType': 'future'  # 交割合约
            }
        })
        
        # 预加载市场，确保symbol有效
        self.exchange.load_markets()
        
        # 支持的永续合约交易对
        self.symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'DOGE/USDT:USDT', 'XRP/USDT:USDT']
        
        # 初始化合约交易配置
        self._setup_futures_config()
        
        # 仓位信息
        self.positions = {}
    
    def _ensure_symbol_settings(self, symbol: str, leverage: int = 10):
        """幂等地确保指定合约为全仓与目标杠杆。"""
        try:
            # 持仓模式（单向）
            try:
                self.exchange.set_position_mode(False)
            except Exception:
                pass

            # 先尝试在设置保证金模式时携带杠杆
            try:
                self.exchange.set_margin_mode('cross', symbol, {'lever': leverage})
            except Exception:
                # 回退：显式设置杠杆并指定marginMode
                try:
                    self.exchange.set_leverage(leverage, symbol, {'marginMode': 'cross'})
                except Exception:
                    pass
        except Exception:
            # 忽略设置失败以避免打断下单流程，由交易所校验最终参数
            pass

    def _setup_futures_config(self):
        """设置合约交易配置"""
        try:
            # 若存在未完成订单或持仓，跳过初始化阶段的模式设置，避免59000错误
            try:
                open_orders = []
                try:
                    open_orders = self.exchange.fetch_open_orders()
                except Exception:
                    open_orders = []
                positions = []
                try:
                    positions = self.exchange.fetch_positions()
                except Exception:
                    positions = []

                if (open_orders and len(open_orders) > 0) or any(p.get('contracts', 0) for p in positions):
                    print("检测到未完成订单或持仓，跳过初始化的持仓/保证金模式设置")
                    return
            except Exception:
                # 查询失败时不中断，继续尝试设置
                pass

            # 设置持仓模式为单向持仓（容错59000）
            try:
                self.exchange.set_position_mode(False)  # False表示单向持仓
                print("设置持仓模式为单向持仓")
            except Exception as e:
                msg = str(e)
                if '59000' in msg:
                    print("设置持仓模式失败(59000)：存在挂单/持仓/机器人，略过")
                else:
                    raise
            
            # 为所有交易对设置杠杆
            for symbol in self.symbols:
                try:
                    # 为每个合约设置保证金模式为全仓，并传入默认杠杆
                    try:
                        self.exchange.set_margin_mode('cross', symbol, {'lever': 10})
                    except Exception as e:
                        print(f"直接设置保证金模式失败，尝试回退方式: {symbol} - {e}")
                        # 某些版本需先明确设置杠杆并携带marginMode
                        try:
                            self.exchange.set_leverage(10, symbol, {'marginMode': 'cross'})
                        except Exception as ee:
                            # 对59000容错：有挂单/持仓时会被拒绝
                            if '59000' in str(ee):
                                print(f"{symbol} 杠杆/保证金设置被拒绝(59000)，可能存在挂单/持仓，略过")
                            else:
                                print(f"回退设置杠杆失败: {symbol} - {ee}")
                    print(f"设置 {symbol} 保证金模式为全仓")

                    # 再设置杠杆，确保最终生效
                    try:
                        self.exchange.set_leverage(10, symbol, {'marginMode': 'cross'})  # 设置10倍杠杆
                        print(f"设置 {symbol} 杠杆为10倍")
                    except Exception as e3:
                        if '59000' in str(e3):
                            print(f"{symbol} 设置杠杆被拒绝(59000)，可能存在挂单/持仓，略过")
                        else:
                            raise
                except Exception as e:
                    print(f"设置 {symbol} 杠杆失败: {e}")
                    
        except Exception as e:
            print(f"设置合约交易配置失败: {e}")
            raise
        
    def get_current_price(self, symbol):
        """获取当前价格"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            print(f"获取价格失败 {symbol}: {e}")
            return None
    
    def get_all_prices(self):
        """获取所有支持币种的当前价格"""
        prices = {}
        for symbol in self.symbols:
            price = self.get_current_price(symbol)
            if price:
                coin = symbol.replace('/USDT', '')
                prices[coin] = price
        return prices
    
    def get_ohlcv_data(self, symbol, timeframe='3m', limit=100):
        """获取K线数据"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"获取K线数据失败 {symbol}: {e}")
            return None
    
    def calculate_indicators(self, df):
        """计算技术指标"""
        if df is None or len(df) < 20:
            return {}
        
        # 计算EMA20
        df['ema20'] = df['close'].ewm(span=20).mean()
        
        # 计算MACD
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # 计算RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
        rs = gain / loss
        df['rsi_7'] = 100 - (100 / (1 + rs))
        
        gain_14 = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss_14 = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs_14 = gain_14 / loss_14
        df['rsi_14'] = 100 - (100 / (1 + rs_14))
        
        # 计算ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr_14'] = true_range.rolling(14).mean()
        df['atr_3'] = true_range.rolling(3).mean()
        
        return df
    
    def get_market_data(self):
        """获取完整的市场数据"""
        market_data = {}
        
        for symbol in self.symbols:
            coin = symbol.replace('/USDT', '')
            
            # 获取当前价格
            current_price = self.get_current_price(symbol)
            if not current_price:
                continue
            
            # 获取3分钟K线数据（短期）
            df_3m = self.get_ohlcv_data(symbol, timeframe='3m', limit=100)
            if df_3m is None:
                continue
            
            # 获取15分钟K线数据
            df_15m = self.get_ohlcv_data(symbol, timeframe='15m', limit=100)
            if df_15m is None:
                continue
            
            # 计算3分钟指标
            df_3m = self.calculate_indicators(df_3m)
            if df_3m.empty:
                continue
            
            # 计算15分钟指标
            df_15m = self.calculate_indicators(df_15m)
            if df_15m.empty:
                continue
            
            # 获取最新数据
            latest_3m = df_3m.iloc[-1]
            latest_15m = df_15m.iloc[-1]
            
            # 获取资金费率和持仓量
            try:
                funding_rate = self.exchange.fetch_funding_rate(symbol)
                open_interest = self.exchange.fetch_open_interest(symbol)
            except:
                funding_rate = {'fundingRate': 0}
                open_interest = {'openInterestAmount': 0}
            
            market_data[coin] = {
                'current_price': current_price,
                # 3分钟数据
                'ema20_3m': latest_3m['ema20'],
                'macd_3m': latest_3m['macd'],
                'rsi_7_3m': latest_3m['rsi_7'],
                'rsi_14_3m': latest_3m['rsi_14'],
                'atr_14_3m': latest_3m['atr_14'],
                'atr_3_3m': latest_3m['atr_3'],
                'volume_3m': latest_3m['volume'],
                'price_series_3m': df_3m['close'].tail(10).tolist(),
                'ema_series_3m': df_3m['ema20'].tail(10).tolist(),
                'macd_series_3m': df_3m['macd'].tail(10).tolist(),
                'rsi_series_3m': df_3m['rsi_7'].tail(10).tolist(),
                'rsi_14_series_3m': df_3m['rsi_14'].tail(10).tolist(),
                # 15分钟数据
                'ema20_15m': latest_15m['ema20'],
                'macd_15m': latest_15m['macd'],
                'rsi_7_15m': latest_15m['rsi_7'],
                'rsi_14_15m': latest_15m['rsi_14'],
                'atr_14_15m': latest_15m['atr_14'],
                'atr_3_15m': latest_15m['atr_3'],
                'volume_15m': latest_15m['volume'],
                'price_series_15m': df_15m['close'].tail(10).tolist(),
                'ema_series_15m': df_15m['ema20'].tail(10).tolist(),
                'macd_series_15m': df_15m['macd'].tail(10).tolist(),
                'rsi_series_15m': df_15m['rsi_7'].tail(10).tolist(),
                'rsi_14_series_15m': df_15m['rsi_14'].tail(10).tolist(),
                # 市场数据
                'funding_rate': funding_rate.get('fundingRate', 0),
                'open_interest': open_interest.get('openInterestAmount', 0),
            }
        
        return market_data
    
    def get_account_info(self):
        """获取账户信息"""
        try:
            # 优先读取合约账户余额
            try:
                balance = self.exchange.fetch_balance({'type': 'swap'})
            except Exception:
                balance = self.exchange.fetch_balance()
            return {
                'total_usdt': balance.get('USDT', {}).get('total', 0),
                'free_usdt': balance.get('USDT', {}).get('free', 0),
                'used_usdt': balance.get('USDT', {}).get('used', 0)
            }
        except Exception as e:
            print(f"获取账户信息失败: {e}")
            return None
    
    def place_order(self, symbol, side, coins_amount, price=None, order_type='market', leverage=10):
        """下单（永续合约）"""
        try:
            # 杠杆已在初始化时设置，这里不需要重复设置
            # 验证参数
            if coins_amount <= 0:
                raise ValueError(f"交易数量必须大于0: {coins_amount}")

            # 下单前确保该symbol的保证金模式与杠杆生效（幂等）
            self._ensure_symbol_settings(symbol, leverage)

            # 将币数量转换为OKX要求的张数
            contract_size = self.exchange.market(symbol)['contractSize']
            contracts_amount = coins_amount / contract_size
            contracts_amount = float(self.exchange.amount_to_precision(symbol, contracts_amount))

            if order_type == 'market':
                order = self.exchange.create_market_order(symbol, side, contracts_amount)
            else:
                if price is None or price <= 0:
                    raise ValueError(f"限价单必须指定有效价格: {price}")
                order = self.exchange.create_limit_order(symbol, side, contracts_amount, price)
            
            if order and 'id' in order:
                print(f"订单创建成功: {symbol} {side} {coins_amount} - 订单ID: {order['id']}")
                return order
            else:
                print(f"订单创建失败: 返回数据无效")
                return None
                
        except Exception as e:
            print(f"下单失败 {symbol} {side} {coins_amount}: {e}")
            return None
    
    def get_positions(self):
        """获取当前持仓"""
        try:
            positions = self.exchange.fetch_positions()
            active_positions = {}
            
            print(f"获取到 {len(positions)} 个合约仓位信息")
            
            for pos in positions:
                # 只处理有持仓的合约
                if pos['contracts'] > 0:
                    symbol = pos['symbol']
                    coin = symbol.replace('/USDT:USDT', '').replace('/USDT', '')
                    
                    # 计算更多仓位信息
                    position_value = abs(pos['contracts']) * pos['markPrice']
                    margin_used = position_value / pos['leverage'] if pos['leverage'] > 0 else 0
                    
                    active_positions[coin] = {
                        'symbol': symbol,
                        'size': pos['contracts'],
                        'entry_price': pos['entryPrice'],
                        'current_price': pos['markPrice'],
                        'mark_price': pos['markPrice'],
                        'unrealized_pnl': pos['unrealizedPnl'],
                        'leverage': pos['leverage'],
                        'side': pos['side'],
                        'position_value': position_value,
                        'margin_used': margin_used,
                        'liquidation_price': pos.get('liquidationPrice', 0),
                        'percentage': pos.get('percentage', 0),
                        'timestamp': pos.get('timestamp', 0)
                    }
                    
                    print(f"持仓: {coin} - {pos['side']} {abs(pos['contracts'])} @ {pos['entryPrice']} "
                          f"(当前: {pos['markPrice']}, PnL: {pos['unrealizedPnl']:.2f})")
            
            if not active_positions:
                print("当前没有活跃持仓")
            
            return active_positions
        except Exception as e:
            print(f"获取持仓失败: {e}")
            return {}
    
    def close_position(self, symbol):
        """平仓"""
        try:
            # 获取当前持仓 - 实时获取最新持仓信息
            positions = self.exchange.fetch_positions()
            
            # 查找指定交易对的持仓
            target_position = None
            for pos in positions:
                if pos['symbol'] == symbol and abs(pos['contracts']) > 0:
                    target_position = pos
                    break
            
            if not target_position:
                print(f"没有找到 {symbol} 的持仓")
                return None
            
            # 确定平仓方向
            if target_position['side'] == 'long':
                close_side = 'sell'
            else:
                close_side = 'buy'
            
            # 获取合约信息
            market_info = self.exchange.market(symbol)
            contract_size = market_info['contractSize']
            
            # 计算精确的平仓数量
            contracts_amount = abs(target_position['contracts'])
            
            # 使用交易所的精度要求
            contracts_amount = float(self.exchange.amount_to_precision(symbol, contracts_amount))
            
            # 检查最小交易量
            min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)
            if contracts_amount < min_amount:
                print(f"平仓数量 {contracts_amount} 小于最小交易量 {min_amount}，使用最小交易量")
                contracts_amount = min_amount
            
            # 转换为币数量
            coins_amount = contracts_amount * contract_size
            
            print(f"平仓 {symbol}: {close_side} {coins_amount} (合约数: {contracts_amount})")
            print(f"原始持仓: {target_position['contracts']}, 当前价格: {target_position.get('markPrice', 'N/A')}")

            # 执行平仓订单 - 使用市价单确保完全平仓
            order = self.place_order(symbol, close_side, coins_amount, order_type='market')
            
            # 验证平仓结果
            if order:
                print(f"平仓订单已提交: {order.get('id', 'N/A')}")
                # 等待一小段时间后验证持仓是否已清零
                time.sleep(0.2)
                try:
                    updated_positions = self.exchange.fetch_positions()
                    remaining_position = None
                    for pos in updated_positions:
                        if pos['symbol'] == symbol and abs(pos['contracts']) > 0:
                            remaining_position = pos
                            break
                    
                    if remaining_position:
                        print(f"⚠️ 警告: 平仓后仍有残留仓位 {symbol}: {remaining_position['contracts']}")
                        # 可以在这里添加重试逻辑
                    else:
                        print(f"✅ 确认: {symbol} 已完全平仓")
                except Exception as verify_e:
                    print(f"验证平仓结果时出错: {verify_e}")
            
            return order
            
        except Exception as e:
            print(f"平仓失败 {symbol}: {e}")
            return None
    
    def close_all_positions(self):
        """平仓所有持仓"""
        try:
            positions = self.exchange.fetch_positions()
            closed_positions = []
            
            for pos in positions:
                if pos['contracts'] > 0:
                    symbol = pos['symbol']
                    coin = symbol.replace('/USDT:USDT', '').replace('/USDT', '')
                    
                    print(f"平仓 {coin} ({symbol})")
                    close_result = self.close_position(symbol)
                    
                    if close_result:
                        closed_positions.append({
                            'coin': coin,
                            'symbol': symbol,
                            'order_id': close_result.get('id'),
                            'success': True
                        })
                        print(f"成功平仓 {coin}")
                    else:
                        closed_positions.append({
                            'coin': coin,
                            'symbol': symbol,
                            'order_id': None,
                            'success': False
                        })
                        print(f"平仓失败 {coin}")
            
            return closed_positions
            
        except Exception as e:
            print(f"平仓所有持仓失败: {e}")
            return []


if __name__ == "__main__":

    trader = OKXTrader()
    trader.get_all_prices()

    trader.get_account_info()
    trader.get_positions()

    trader.place_order('ETH/USDT:USDT', 'buy', 0.001, order_type='market')
    trader.close_position('ETH/USDT:USDT')
    # trader.close_all_positions()

