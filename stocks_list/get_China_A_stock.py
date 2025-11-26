import pandas as pd
import os
import warnings

# 抑制openpyxl的样式警告
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


def process_sh_stock():
    """处理上海证券交易所股票数据"""
    file_path = 'stocks_list/cache/SH_stock_list.csv'
    
    # SH 文件实际上是制表符分隔的文本文件 (TSV)，编码为 GB18030
    try:
        # 使用 read_csv 读取
        df = pd.read_csv(file_path, sep='\t', encoding='gb18030', dtype=str)
    except Exception:
        # 备用尝试
        df = pd.read_csv(file_path, sep='\t', encoding='gbk', dtype=str)
    
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
    
    return result


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
    
    return result


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
