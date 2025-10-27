import pandas as pd
import os
import warnings

# 抑制openpyxl的样式警告
warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


def fullwidth_to_halfwidth(text):
    """将全角字符转换为半角字符"""
    if pd.isna(text):
        return text
    
    result = []
    for char in text:
        # 全角字母转半角
        if '\uff21' <= char <= '\uff3a':  # 全角大写字母 A-Z
            result.append(chr(ord(char) - 0xFEE0))
        elif '\uff41' <= char <= '\uff5a':  # 全角小写字母 a-z
            result.append(chr(ord(char) - 0xFEE0))
        elif '\uff10' <= char <= '\uff19':  # 全角数字 0-9
            result.append(chr(ord(char) - 0xFEE0))
        elif char == '\uff0d':  # 全角连字符 -
            result.append('-')
        elif char == '\uff08':  # 全角左括号 (
            result.append('(')
        elif char == '\uff09':  # 全角右括号 )
            result.append(')')
        else:
            result.append(char)
    return ''.join(result)


def process_hk_stock():
    """处理香港交易所股票数据"""
    file_path = 'stocks_list/cache/HK_stock_list.xlsx'
    
    # 读取Excel文件，跳过前两行标题，使用第3行作为列名
    df = pd.read_excel(file_path, engine='openpyxl', header=None)
    
    # 使用第3行（索引为2）作为列名
    df.columns = df.iloc[2]
    
    # 从第4行开始读取数据（索引从3开始）
    df = df.iloc[3:].reset_index(drop=True)
    
    # 筛选出股本，过滤掉债券、衍生品等其他分类
    df = df[df['分類'] == '股本'].copy()
    
    # 提取股份代號和股份名稱
    result = df[['股份代號', '股份名稱']].copy()
    result.columns = ['Symbol', 'Name']
    
    # 过滤掉空值
    result = result.dropna()
    
    # 将股票代码转换为字符串并补齐5位（港股代码为5位）
    result['Symbol'] = result['Symbol'].astype(str).str.zfill(5)
    
    # 添加.HK后缀（香港）
    result['Symbol'] = result['Symbol'] + '.HK'
    
    # 将Name字段中的全角字符转换为半角
    result['Name'] = result['Name'].apply(fullwidth_to_halfwidth)
    
    return result


def main():
    """主函数：处理港股数据并输出CSV"""
    print("正在读取香港交易所股票列表...")
    hk_df = process_hk_stock()
    print(f"读取到 {len(hk_df)} 只港股")
    
    # 保存为CSV
    output_file = 'stocks_list/cache/china_screener_HK.csv'
    hk_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"结果已保存到: {output_file}")
    
    # 显示前几行
    print("\n前10行数据预览：")
    print(hk_df.head(10))

def get_china_hk_stock_list():
    path = 'stocks_list/cache/china_screener_HK.csv'
    df = pd.read_csv(path)
    return df['Symbol'].tolist()

if __name__ == '__main__':
    
    main()
    # print(get_china_hk_stock_list())
