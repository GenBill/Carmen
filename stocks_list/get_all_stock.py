import pandas as pd
import os
import time
from typing import List, Set
from .get_China_A_stock import get_china_a_stock_list
from .get_China_HK_stock import get_china_hk_stock_list
from .update_stock_lists import update_stock_lists_cache

def get_us_stock_list_from_files() -> List[str]:
    """
    从本地下载的CSV文件读取全美股票列表，包括 NASDAQ、NYSE 和 AMEX。
    假设文件已下载到 stock_cache/ 目录下。
    """
    files = [
        "stocks_list/cache/nasdaq_screener_NSDQ.csv",
        "stocks_list/cache/nasdaq_screener_NYSE.csv",
        "stocks_list/cache/nasdaq_screener_AMEX.csv",
    ]

    # 自动检查并更新股票列表
    should_update = False
    max_age_seconds = 7 * 24 * 3600  # 7天过期
    
    for file in files:
        if not os.path.exists(file):
            print(f"⚠️ 股票列表文件缺失: {file}")
            should_update = True
            break
        else:
            # 检查修改时间
            try:
                mtime = os.path.getmtime(file)
                age = time.time() - mtime
                if age > max_age_seconds:
                    print(f"⚠️ 股票列表文件已过期 ({int(age/3600/24)}天): {file}")
                    should_update = True
                    break
            except OSError:
                should_update = True
                break
    
    if should_update:
        try:
            print("🔄 正在自动更新股票列表...")
            update_stock_lists_cache()
        except Exception as e:
            print(f"❌ 自动更新股票列表失败: {e}")
            # 继续尝试读取现有文件

    all_tickers: Set[str] = set()
    for file in files:
        try:
            df = pd.read_csv(file)

            if "Sector" in df.columns:
                df = df[df["Sector"] != "Exchange Traded Fund"]  # 排除 ETF
            tickers = set(df["Symbol"].dropna().str.strip().tolist())

            # 过滤掉无效符号（如 ^, ~ 等测试符号）
            invalid_chars = ['^', '~', '/']
            valid_tickers = {
                ticker
                for ticker in tickers
                if ticker and len(ticker) <= 5 
                and not any(char in ticker for char in invalid_chars)
                and is_valid_common_stock(ticker)
            }

            all_tickers.update(valid_tickers)
            print(f"Loaded {len(valid_tickers)} tickers from {file}")

        except Exception as e:
            print(f"Error reading {file}: {e}")

    return sorted(list(all_tickers))

def get_simple_stock_symbols_from_file(path: str="my_stock_symbols.txt"):
    """从文件读取股票列表并过滤"""
    symbols = []
    with open(path, "r") as f:
        for line in f:
            symbol = line.strip()
            if is_valid_common_stock(symbol):
                symbols.append(symbol)
    return symbols

def is_valid_common_stock(symbol: str) -> bool:
    """
    判断是否是有效的普通股票代码
    过滤掉权证、单位、优先股等特殊证券
    
    Args:
        symbol: 股票代码
        
    Returns:
        bool: True表示是普通股票
    """
    symbol = symbol.strip().upper()
    # 排除空代码
    if not symbol or len(symbol) < 1:
        return False

    if '.HK' in symbol:
        return len(symbol) == 4+3
    
    elif '.SS' in symbol:
        return len(symbol) == 6+3
    
    elif '.SH' in symbol:
        return len(symbol) == 6+3
    
    # 纯美股的情况
    else: 

        # 排除特殊后缀：
        # W - 权证 (Warrants)
        # U - 单位 (Units)
        # R - 权利 (Rights)  
        # P - 优先股 (Preferred)
        # 注意：纳斯达克规则是只有5个字符的股票代码，第5个字符才是特殊后缀
        # 例如：AAPLW(5字符)是权证，但AAPL(4字符)、APP(3字符)、SERV(4字符)都是正常股票
        special_suffixes = ['W', 'U', 'R', 'P', 'V', 'L', 'Z']
        
        # 只检查5字符代码的最后一个字符
        if len(symbol) == 5:
            for suffix in special_suffixes:
                if symbol.endswith(suffix):
                    return False
        
        # 排除过长的代码（通常普通股是1-5个字母）
        if len(symbol) > 5:
            return False
        
        return True


def get_stock_list(path: str = '', mode: str = 'US') -> List[str]:
    """
    获取全美股票列表，包括 NASDAQ、NYSE 和 AMEX。
    """
    if path != '':
        return get_simple_stock_symbols_from_file(path)
    elif mode == 'US':
        return get_us_stock_list_from_files()
    elif mode == 'HK':
        return get_china_hk_stock_list()
    elif mode == 'A':
        return get_china_a_stock_list()
    elif mode == 'HK+A':
        return get_china_hk_stock_list() + get_china_a_stock_list()
    else:
        raise ValueError(f"Invalid mode: {mode}")


if __name__ == "__main__":
    stocks = get_stock_list()
    print(f"\nTotal unique stocks: {len(stocks)}")
    print(f"Contains U: {'U' in stocks}")
    print(f"Contains SONY: {'SONY' in stocks}")
    # 可选：打印前10个以验证
    print(f"First 10 tickers: {stocks[:10]}")
