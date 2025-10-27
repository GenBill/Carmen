import pandas as pd
import os
import warnings

# 抑制openpyxl的样式警告
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


def process_sh_stock():
    """处理上海证券交易所股票数据"""
    file_path = 'stocks_list/cache/SH_stock_list.xls'
    df = pd.read_excel(file_path, engine='xlrd')
    
    # 提取A股代码和证券简称
    result = df[['A股代码', '证券简称']].copy()
    result.columns = ['Symbol', 'Name']
    
    # 过滤掉空值，并将股票代码转换为字符串并补齐6位
    result = result.dropna()
    result['Symbol'] = result['Symbol'].astype(int).astype(str).str.zfill(6)
    
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


def main():
    """主函数：整合上海和深圳数据并输出CSV"""
    print("正在读取上海证券交易所股票列表...")
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
    
    # 显示前几行
    print("\n前10行数据预览：")
    print(combined_df.head(10))

def get_china_a_stock_list():
    path = 'stocks_list/cache/china_screener_A.csv'
    df = pd.read_csv(path)
    return df['Symbol'].tolist()

if __name__ == '__main__':

    main()
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
