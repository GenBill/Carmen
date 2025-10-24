import pandas as pd
import requests
from io import StringIO


def get_nasdaq_stock_symbols():
    """
    从纳斯达克网站获取在 NASDAQ 交易所上市的股票代码列表。

    Returns:
        list: 包含 NASDAQ 股票代码的列表，如果获取失败则返回空列表。
              返回的代码已去重并确保为字符串。
    """
    symbols = []
    url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"

    print("正在从纳斯达克网站下载 NASDAQ 股票列表...")

    # 创建一个 Session 对象
    session = requests.Session()
    # 告诉 Session 不要信任环境变量中的代理设置
    session.trust_env = False

    # !! 重要：如果你的网络需要代理，请取消注释并修改下面的代理设置 !!
    # proxies = {
    #   'http': 'http://your_proxy_address:port',
    #   'https': 'http://your_proxy_address:port',
    # }
    # proxies = {
    #    'http': 'http://user:password@your_proxy_address:port',
    #    'https': 'http://user:password@your_proxy_address:port',
    # }
    proxies = None  # 保持为 None，因为浏览器可以直接访问

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }
        # 使用 session 对象发出请求
        response = session.get(url, timeout=30, headers=headers, proxies=proxies)
        response.raise_for_status()  # 如果请求失败则抛出异常

        # 将文本数据读入 pandas DataFrame
        # 使用 io.StringIO 来处理文本数据流
        # skipfooter=1 跳过文件末尾的时间戳行
        # engine='python' 是因为 skipfooter 在 C engine 中可能不支持
        # 注意：移除了 on_bad_lines='skip'，因为我们只处理一个已知格式的文件
        df = pd.read_csv(
            StringIO(response.text), sep="|", skipfooter=1, engine="python"
        )

        # 检查必需的列是否存在
        if "Test Issue" not in df.columns or "Symbol" not in df.columns:
            print(f"错误：文件 {url} 缺少必需的列 ('Test Issue' 或 'Symbol')。")
            return get_nasdaq_stock_symbols_from_file()

        # 过滤掉测试股票 (Test Issue 列为 'N')
        df_filtered = df[df["Test Issue"] == "N"]

        # 过滤掉 ETF 股票 (ETF 列不为空)
        df_filtered = df_filtered[df_filtered["ETF"] == "N"]

        # 提取股票代码列，并确保它们是字符串
        # 先使用 dropna() 移除 NaN 值，然后转换为字符串列表
        all_symbols = df_filtered["Symbol"].dropna().tolist()
        all_symbols = [str(s) for s in all_symbols]

        # 过滤特殊证券（权证、单位、优先股等）
        valid_symbols = [s for s in all_symbols if is_valid_common_stock(s)]
        symbols.extend(valid_symbols)

        filtered_count = len(all_symbols) - len(valid_symbols)
        print(
            f"已处理 NASDAQ 上市股票 {len(df_filtered)} 只 -> 过滤特殊证券 {filtered_count} 个 -> 保留 {len(valid_symbols)} 只普通股"
        )

        # 去重并排序
        unique_symbols = sorted(list(set(symbols)))
        print(f"获取完成。总共找到 {len(unique_symbols)} 只唯一的 NASDAQ 普通股代码。")

        # 将代码保存到文件（保存过滤后的普通股）
        try:
            # 更新保存的文件名
            with open("nasdaq_stock_symbols.txt", "w") as f:
                for symbol in unique_symbols:
                    f.write(symbol + "\n")
            print("\n所有 NASDAQ 普通股代码已保存到 nasdaq_stock_symbols.txt")
        except IOError as e:
            print(f"\n错误：无法将代码写入文件。 {e}")

        return unique_symbols

    except requests.exceptions.ProxyError as e:
        print(f"错误：连接代理服务器失败。请检查脚本中的代理设置或系统网络环境。 {e}")
        return get_nasdaq_stock_symbols_from_file()

    except requests.exceptions.RequestException as e:
        print(f"错误：无法从 {url} 下载数据。 {e}")
        return get_nasdaq_stock_symbols_from_file()

    except pd.errors.ParserError as e:
        print(f"错误：解析文件 {url} 时出错。文件格式可能已更改。 {e}")
        return get_nasdaq_stock_symbols_from_file()

    except pd.errors.EmptyDataError:
        print(f"警告：从 {url} 下载的数据为空或无法解析。")
        return get_nasdaq_stock_symbols_from_file()

    except Exception as e:
        print(f"错误：处理来自 {url} 的数据时出错。 {e}")
        return get_nasdaq_stock_symbols_from_file()


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

    # 排除特殊后缀：
    # W - 权证 (Warrants)
    # U - 单位 (Units)
    # R - 权利 (Rights)
    # P - 优先股 (Preferred)
    # 注意：纳斯达克规则是只有5个字符的股票代码，第5个字符才是特殊后缀
    # 例如：AAPLW(5字符)是权证，但AAPL(4字符)、APP(3字符)、SERV(4字符)都是正常股票
    special_suffixes = ["W", "U", "R", "P", "V"]

    # 只检查5字符代码的最后一个字符
    if len(symbol) == 5:
        for suffix in special_suffixes:
            if symbol.endswith(suffix):
                return False

    # 排除过长的代码（通常普通股是1-5个字母）
    if len(symbol) > 5:
        return False

    return True


def get_nasdaq_stock_symbols_from_file(path: str = "nasdaq_stock_symbols.txt"):
    """从文件读取股票列表并过滤"""
    symbols = []
    with open(path, "r") as f:
        for line in f:
            symbol = line.strip()
            if is_valid_common_stock(symbol):
                symbols.append(symbol)

    print(
        f"从文件读取: 原始{sum(1 for _ in open(path))}个 -> 过滤后{len(symbols)}个普通股"
    )
    return symbols


def get_stock_list(path: str = ""):
    if path != "":
        return get_nasdaq_stock_symbols_from_file(path)
    else:
        return get_nasdaq_stock_symbols()


if __name__ == "__main__":
    # 调用更新后的函数
    nasdaq_symbols = get_nasdaq_stock_symbols()

    if nasdaq_symbols:
        print("\n部分 NASDAQ 股票代码示例:")
        # 打印前 20 个和最后 10 个作为示例
        print(nasdaq_symbols[:20])
        print("...")
        print(nasdaq_symbols[-10:])

    else:
        print("\n未能获取 NASDAQ 股票代码。")
