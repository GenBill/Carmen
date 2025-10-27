import pandas as pd
from typing import List, Set
from get_China_A_stock import get_china_a_stock_list
from get_China_HK_stock import get_china_hk_stock_list

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
                if ticker and len(ticker) <= 5 and not any(char in ticker for char in invalid_chars)
            }

            all_tickers.update(valid_tickers)
            print(f"Loaded {len(valid_tickers)} tickers from {file}")

        except Exception as e:
            print(f"Error reading {file}: {e}")

    return sorted(list(all_tickers))

def get_nasdaq_stock_symbols_from_file(path: str="us_stock_symbols.txt"):
    """从文件读取股票列表并过滤"""
    symbols = []
    with open(path, "r") as f:
        for line in f:
            symbol = line.strip()
            if is_valid_common_stock(symbol):
                symbols.append(symbol)
    
    print(f"从文件读取: 原始{sum(1 for _ in open(path))}个 -> 过滤后{len(symbols)}个普通股")
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

    # 排除过长的代码（通常普通股是1-4个字母）
    if len(symbol) >= 5:
        return False

    return True


def get_stock_list(path: str = '', mode: str = 'US') -> List[str]:
    """
    获取全美股票列表，包括 NASDAQ、NYSE 和 AMEX。
    """
    if path != '':
        return get_nasdaq_stock_symbols_from_file(path)
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
