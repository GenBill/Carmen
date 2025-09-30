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
    proxies = None # 保持为 None，因为浏览器可以直接访问

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        # 使用 session 对象发出请求
        response = session.get(url, timeout=30, headers=headers, proxies=proxies)
        response.raise_for_status() # 如果请求失败则抛出异常

        # 将文本数据读入 pandas DataFrame
        # 使用 io.StringIO 来处理文本数据流
        # skipfooter=1 跳过文件末尾的时间戳行
        # engine='python' 是因为 skipfooter 在 C engine 中可能不支持
        # 注意：移除了 on_bad_lines='skip'，因为我们只处理一个已知格式的文件
        df = pd.read_csv(StringIO(response.text), sep='|', skipfooter=1, engine='python')

        # 检查必需的列是否存在
        if 'Test Issue' not in df.columns or 'Symbol' not in df.columns:
             print(f"错误：文件 {url} 缺少必需的列 ('Test Issue' 或 'Symbol')。")
             return []

        # 过滤掉测试股票 (Test Issue 列为 'N')
        df_filtered = df[df['Test Issue'] == 'N']

        # 过滤掉 ETF 股票 (ETF 列不为空)
        df_filtered = df_filtered[df_filtered['ETF'] == 'N']

        # 提取股票代码列，并确保它们是字符串
        # 先使用 dropna() 移除 NaN 值，然后转换为字符串列表
        valid_symbols = df_filtered['Symbol'].dropna().tolist()
        symbols.extend([str(s) for s in valid_symbols])
        print(f"已处理 NASDAQ 上市股票 {len(df_filtered)} 只 (移除了 NaN 后得到 {len(valid_symbols)} 个有效代码)。")

        # 去重并排序
        unique_symbols = sorted(list(set(symbols)))
        print(f"获取完成。总共找到 {len(unique_symbols)} 只唯一的 NASDAQ 股票代码。")

        # 将代码保存到文件
        try:
            # 更新保存的文件名
            with open("nasdaq_stock_symbols.txt", "w") as f:
                for symbol in unique_symbols:
                    f.write(symbol + "\n")
            print("\n所有 NASDAQ 股票代码已保存到 nasdaq_stock_symbols.txt")
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
    

def get_nasdaq_stock_symbols_from_file(path: str="nasdaq_stock_symbols.txt"):
    with open(path, "r") as f:
        return f.readlines()

def get_stock_list(path: str = ''):
    if path is not '':
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
