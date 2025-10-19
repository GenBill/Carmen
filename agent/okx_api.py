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
        
        # 支持的交易对
        self.symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT', 'XRP/USDT']
        
        # 仓位信息
        self.positions = {}
        
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
    
    def place_order(self, symbol, side, amount, price=None, order_type='market'):
        """下单"""
        try:
            if order_type == 'market':
                order = self.exchange.create_market_order(symbol, side, amount)
            else:
                order = self.exchange.create_limit_order(symbol, side, amount, price)
            
            return order
        except Exception as e:
            print(f"下单失败 {symbol} {side} {amount}: {e}")
            return None
    
    def get_positions(self):
        """获取当前持仓"""
        try:
            positions = self.exchange.fetch_positions()
            active_positions = {}
            
            for pos in positions:
                if pos['contracts'] > 0:
                    symbol = pos['symbol']
                    coin = symbol.replace('/USDT:USDT', '').replace('/USDT', '')
                    active_positions[coin] = {
                        'size': pos['contracts'],
                        'entry_price': pos['entryPrice'],
                        'current_price': pos['markPrice'],
                        'unrealized_pnl': pos['unrealizedPnl'],
                        'leverage': pos['leverage'],
                        'side': pos['side']
                    }
            
            return active_positions
        except Exception as e:
            print(f"获取持仓失败: {e}")
            return {}
    
    def close_position(self, symbol):
        """平仓"""
        try:
            positions = self.get_positions()
            coin = symbol.replace('/USDT', '')
            
            if coin in positions:
                pos = positions[coin]
                side = 'sell' if pos['side'] == 'long' else 'buy'
                amount = abs(pos['size'])
                
                order = self.place_order(symbol, side, amount)
                return order
        except Exception as e:
            print(f"平仓失败 {symbol}: {e}")
            return None
