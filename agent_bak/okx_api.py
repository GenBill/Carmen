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
        })
        
        # 初始化合约交易配置
        self._setup_futures_config()
        
        # 支持的永续合约交易对
        self.symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'DOGE/USDT:USDT', 'XRP/USDT:USDT']
        
        # 仓位信息
        self.positions = {}
    
    def _setup_futures_config(self):
        """设置合约交易配置"""
        try:
            # 设置保证金模式为全仓模式
            self.exchange.set_margin_mode('cross', 'USDT')  # 全仓模式
            print("设置保证金模式为全仓模式")
            
            # 设置持仓模式为单向持仓
            self.exchange.set_position_mode(False)  # False表示单向持仓
            print("设置持仓模式为单向持仓")
            
            # 为所有交易对设置杠杆
            for symbol in self.symbols:
                try:
                    self.exchange.set_leverage(10, symbol)  # 设置10倍杠杆
                    print(f"设置 {symbol} 杠杆为10倍")
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
            
            # 获取K线数据
            df = self.get_ohlcv_data(symbol)
            if df is None:
                continue
            
            # 计算指标
            df = self.calculate_indicators(df)
            if df.empty:
                continue
            
            # 获取最新数据
            latest = df.iloc[-1]
            
            # 获取资金费率和持仓量
            try:
                funding_rate = self.exchange.fetch_funding_rate(symbol)
                open_interest = self.exchange.fetch_open_interest(symbol)
            except:
                funding_rate = {'fundingRate': 0}
                open_interest = {'openInterestAmount': 0}
            
            market_data[coin] = {
                'current_price': current_price,
                'ema20': latest['ema20'],
                'macd': latest['macd'],
                'rsi_7': latest['rsi_7'],
                'rsi_14': latest['rsi_14'],
                'atr_14': latest['atr_14'],
                'atr_3': latest['atr_3'],
                'funding_rate': funding_rate.get('fundingRate', 0),
                'open_interest': open_interest.get('openInterestAmount', 0),
                'volume': latest['volume'],
                'price_series': df['close'].tail(10).tolist(),
                'ema_series': df['ema20'].tail(10).tolist(),
                'macd_series': df['macd'].tail(10).tolist(),
                'rsi_series': df['rsi_7'].tail(10).tolist(),
                'rsi_14_series': df['rsi_14'].tail(10).tolist()
            }
        
        return market_data
    
    def get_account_info(self):
        """获取账户信息"""
        try:
            balance = self.exchange.fetch_balance()
            return {
                'total_usdt': balance.get('USDT', {}).get('total', 0),
                'free_usdt': balance.get('USDT', {}).get('free', 0),
                'used_usdt': balance.get('USDT', {}).get('used', 0)
            }
        except Exception as e:
            print(f"获取账户信息失败: {e}")
            return None
    
    def place_order(self, symbol, side, amount, price=None, order_type='market', leverage=10):
        """下单（永续合约）"""
        try:
            # 杠杆已在初始化时设置，这里不需要重复设置
            # 验证参数
            if amount <= 0:
                raise ValueError(f"交易数量必须大于0: {amount}")
            
            if order_type == 'market':
                order = self.exchange.create_market_order(symbol, side, amount)
            else:
                if price is None or price <= 0:
                    raise ValueError(f"限价单必须指定有效价格: {price}")
                order = self.exchange.create_limit_order(symbol, side, amount, price)
            
            if order and 'id' in order:
                print(f"订单创建成功: {symbol} {side} {amount} - 订单ID: {order['id']}")
                return order
            else:
                print(f"订单创建失败: 返回数据无效")
                return None
                
        except Exception as e:
            print(f"下单失败 {symbol} {side} {amount}: {e}")
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
            # 获取当前持仓
            positions = self.exchange.fetch_positions()
            
            # 查找指定交易对的持仓
            target_position = None
            for pos in positions:
                if pos['symbol'] == symbol and pos['contracts'] > 0:
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
            
            # 平仓数量
            close_amount = abs(target_position['contracts'])
            
            print(f"平仓 {symbol}: {close_side} {close_amount}")
            
            # 执行平仓订单
            order = self.place_order(symbol, close_side, close_amount)
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
