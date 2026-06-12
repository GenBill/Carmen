import pandas as pd
import os
import warnings

# 抑制openpyxl的样式警告
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


def exclude_st_stocks(df: pd.DataFrame) -> pd.DataFrame:
    """过滤掉 ST 及退市整理/已退市股票。"""
    if 'Name' not in df.columns:
        return df

    name_series = (
        df['Name']
        .fillna('')
        .astype(str)
        .str.replace(' ', '', regex=False)
        .str.replace('\u3000', '', regex=False)
        .str.upper()
    )
    invalid_mask = name_series.str.startswith(('ST', '*ST', 'S*ST', '退市'))
    return df[~invalid_mask].copy()


def _read_sse_stock_file(file_path: str) -> pd.DataFrame:
    """读取上交所下载的 TSV 股票列表。"""
    try:
        return pd.read_csv(file_path, sep='\t', encoding='gb18030', dtype=str)
    except Exception:
        return pd.read_csv(file_path, sep='\t', encoding='gbk', dtype=str)


def process_sh_stock():
    """处理上海证券交易所股票数据，包含主板 + 科创板。"""
    file_paths = [
        'stocks_list/cache/SH_stock_list.csv',
        # stockType=8: 科创板。保留独立文件，避免上交所 stockType=1 口径变化时漏掉 688/689。
        'stocks_list/cache/SH_star_stock_list.csv',
    ]

    frames = []
    for file_path in file_paths:
        if not os.path.exists(file_path):
            continue
        frames.append(_read_sse_stock_file(file_path))

    if not frames:
        raise FileNotFoundError('未找到上交所股票列表缓存')

    df = pd.concat(frames, ignore_index=True)

    # 清理列名空格
    df.columns = df.columns.str.strip()

    # 提取A股代码和证券简称
    # 目标列: '公司代码', '公司简称'
    if '公司代码' in df.columns:
        result = df[['公司代码', '公司简称']].copy()
    else:
        # 如果列名不对，尝试使用索引（第1列和第2列）
        result = df.iloc[:, [0, 1]].copy()

    result.columns = ['Symbol', 'Name']

    # 过滤掉空值
    result = result.dropna()

    # 清理数据空格
    result['Symbol'] = result['Symbol'].str.strip()
    result['Name'] = result['Name'].str.strip()

    # 确保代码是6位
    result['Symbol'] = result['Symbol'].str.zfill(6)

    # 添加.SS后缀（上海）
    result['Symbol'] = result['Symbol'] + '.SS'
    result = result.drop_duplicates(subset=['Symbol'], keep='first')
    return exclude_st_stocks(result)


def process_sz_stock():
    """处理深圳证券交易所股票数据"""
    file_path = 'stocks_list/cache/SZ_stock_list.xlsx'
    df = pd.read_excel(file_path, engine='openpyxl')
    
    # 提取A股代码和A股简称
    result = df[['A股代码', 'A股简称']].copy()
    result.columns = ['Symbol', 'Name']
    
    # 过滤掉空值，并将股票代码转换为字符串并补齐6位
    result = result.dropna()
    result['Symbol'] = result['Symbol'].astype(int).astype(str).str.zfill(6)
    
    # 添加.SZ后缀（深圳）
    result['Symbol'] = result['Symbol'] + '.SZ'
    return exclude_st_stocks(result)


def update_a_csv_cache():
    """主函数：整合上海和深圳数据并输出CSV"""
    print("正在读取上海证券交易所股票列表...")
    try:
        sh_df = process_sh_stock()
        print(f"读取到 {len(sh_df)} 只上海股票")
        
        print("正在读取深圳证券交易所股票列表...")
        sz_df = process_sz_stock()
        print(f"读取到 {len(sz_df)} 只深圳股票")
        
        # 合并两个数据集
        combined_df = pd.concat([sh_df, sz_df], ignore_index=True)
        print(f"共 {len(combined_df)} 只股票")
        
        # 保存为CSV
        output_file = 'stocks_list/cache/china_screener_A.csv'
        combined_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"结果已保存到: {output_file}")
        return True
    except Exception as e:
        print(f"❌ 转换A股数据失败: {e}")
        return False

def get_china_a_stock_list():
    path = 'stocks_list/cache/china_screener_A.csv'
    try:
        df = pd.read_csv(path)
        return df['Symbol'].tolist()
    except FileNotFoundError:
        return []

if __name__ == '__main__':

    update_a_csv_cache()
    # print(get_china_a_stock_list())

    # import yfinance as yf
    # def get_historical_data(symbol):
    #     try:
    #         stock = yf.Ticker(symbol)
    #         historical_data = stock.history(period="30d", timeout=15)
    #         print(historical_data)
    #         return historical_data
    #     except Exception as e:
    #         print(f"Error: {symbol} {e}")
    #         return None
    
    # get_historical_data("000001.SZ")
    # get_historical_data("600000.SS")
    # get_historical_data("09988.HK")
    # get_historical_data("TSLA")
