import os
import requests
import time
import pandas as pd
from pathlib import Path
import json
import sys
import random
import importlib

def download_file_generic(url, filename, headers=None, verify=True):
    """通用文件下载函数"""
    print(f"📥 正在下载 {filename.name}...")
    try:
        response = requests.get(url, headers=headers, timeout=60, verify=verify)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            f.write(response.content)
        print(f"✅ 下载完成: {filename.name}")
        return True
    except Exception as e:
        print(f"❌ 下载失败 {filename.name}: {e}")
        return False

def download_file(exchange, filename):
    # Nasdaq Screener API
    # 注意：download=true 参数虽然存在，但 API 实际上返回的是 JSON 格式的数据
    url = f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&exchange={exchange}&download=true"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }
    
    print(f"📥 正在下载 {exchange} 股票列表...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # 尝试解析 JSON
        try:
            data = response.json()
            if data and 'data' in data and data['data'] and 'rows' in data['data']:
                rows = data['data']['rows']
                df = pd.DataFrame(rows)
                
                # API 返回的列名通常是 camelCase 或小写，需要重命名以匹配我们代码中使用的格式
                # 现有代码期望的列名: Symbol, Name, Sector, ETF (可能没有ETF列，而是通过Sector判断)
                
                # 映射 API 字段到 CSV 列名
                rename_map = {
                    'symbol': 'Symbol',
                    'name': 'Name',
                    'lastsale': 'Last Sale',
                    'netchange': 'Net Change',
                    'pctchange': '% Change',
                    'marketCap': 'Market Cap',
                    'country': 'Country',
                    'ipoyear': 'IPO Year',
                    'volume': 'Volume',
                    'sector': 'Sector',
                    'industry': 'Industry'
                }
                
                # 重命名存在的列
                df = df.rename(columns=rename_map)
                
                # 确保包含所有必要的列（如果 API 没返回，填空）
                # 关键列: Symbol, Sector
                if 'Symbol' not in df.columns:
                    print(f"❌ 错误: API 返回数据中缺少 Symbol 列")
                    return
                
                # 保存 CSV
                df.to_csv(filename, index=False)
                print(f"✅ 已保存 {len(df)} 条记录到 {filename}")
                return
                
            else:
                print(f"⚠️  API 响应格式不符合预期 (缺少 data.rows)")
                # 打印部分响应以便调试
                print(str(data)[:200])
                
        except json.JSONDecodeError:
            # 如果不是 JSON，假设是直接的 CSV 内容（虽然不太可能）
            print(f"⚠️  响应不是 JSON，尝试直接保存...")
            with open(filename, 'wb') as f:
                f.write(response.content)
            print(f"✅ 已直接保存内容到 {filename}")

    except Exception as e:
        print(f"❌ 下载 {exchange} 失败: {e}")

def update_stock_lists_cache():
    """更新股票列表缓存文件"""
    # 确保目录存在
    script_dir = Path(__file__).parent
    cache_dir = script_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    exchanges = [
        ("NASDAQ", "nasdaq_screener_NSDQ.csv"),
        ("NYSE", "nasdaq_screener_NYSE.csv"),
        ("AMEX", "nasdaq_screener_AMEX.csv")
    ]
    
    print(f"🚀 开始检查/更新股票列表缓存...")
    print(f"📂 缓存目录: {cache_dir}")
    
    for exchange, filename in exchanges:
        filepath = cache_dir / filename
        download_file(exchange, filepath)
        # 礼貌间隔，避免触发反爬限制
        time.sleep(2)
    
    # --- 更新中国市场股票 (A股/港股) ---
    print("\n🚀 开始更新中国市场(A股/港股)列表...")
    
    # HK (香港) - 使用中文版文件名 ListOfSecurities_c.xlsx
    hk_url = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
    hk_file = cache_dir / "HK_stock_list.xlsx"
    download_file_generic(hk_url, hk_file, headers={'User-Agent': 'Mozilla/5.0'})
    
    # SH (上海主板 + 科创板)
    # Referer 是必须的；stockType=8 为科创板，单独缓存后在 get_China_A_stock.py 合并。
    sse_headers = {'Referer': 'http://www.sse.com.cn/', 'User-Agent': 'Mozilla/5.0'}
    sh_url = "http://query.sse.com.cn/security/stock/downloadStockListFile.do?csrcCode=&stockCode=&areaName=&stockType=1"
    sh_file = cache_dir / "SH_stock_list.csv"
    download_file_generic(sh_url, sh_file, headers=sse_headers)

    sh_star_url = "http://query.sse.com.cn/security/stock/downloadStockListFile.do?csrcCode=&stockCode=&areaName=&stockType=8"
    sh_star_file = cache_dir / "SH_star_stock_list.csv"
    download_file_generic(sh_star_url, sh_star_file, headers=sse_headers)
    
    # SZ (深圳)
    rand_val = random.random()
    sz_url = f"http://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1&random={rand_val}"
    sz_file = cache_dir / "SZ_stock_list.xlsx"
    download_file_generic(sz_url, sz_file, headers={'User-Agent': 'Mozilla/5.0'})
    
    # 调用转换脚本转换为 CSV
    print("\n🔄 正在转换中国市场数据为CSV...")
    try:
        # 动态导入转换模块
        # 将当前脚本所在目录加入 path 以便导入同级模块
        if str(script_dir) not in sys.path:
            sys.path.append(str(script_dir))
            
        # 尝试导入 (注意：模块名区分大小写)
        try:
            import get_China_HK_stock
            import get_China_A_stock
            
            # 重新加载以确保获取最新代码
            importlib.reload(get_China_HK_stock)
            importlib.reload(get_China_A_stock)
            
            # 执行转换
            print("--- 转换港股 ---")
            get_China_HK_stock.update_hk_csv_cache()
            
            print("--- 转换A股 ---")
            get_China_A_stock.update_a_csv_cache()
            
        except ImportError as e:
            print(f"❌ 无法导入转换脚本 (请确保 get_China_HK_stock.py 和 get_China_A_stock.py 在同一目录下): {e}")
            
    except Exception as e:
        print(f"❌ 转换过程出错: {e}")
        
    print(f"\n✨ 所有股票列表更新完成！")

if __name__ == "__main__":
    update_stock_lists_cache()

