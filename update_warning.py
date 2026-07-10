import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from datetime import datetime, timedelta
import os
import logging
import re
import sys

logging.getLogger("urllib3").setLevel(logging.ERROR)

print("【Phase 2 自動化】正在更新台股「注意與處置」歷史記分板...")

# ==========================================
# 1. 設定存檔路徑 (GitHub 環境根目錄)
# ==========================================
WARNING_CSV = 'tw_warning_data.csv'

# ==========================================
# 2. 建立高穩定度 Session
# ==========================================
session = requests.Session()
retry_strategy = Retry(total=3, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)
headers = {'User-Agent': 'Mozilla/5.0'}

# ==========================================
# 3. 設定區間 (每日更新，回溯 30 天以策安全)
# ==========================================
# 設定抓取過去 30 天，確保即便有長假或伺服器漏抓，也能無縫補齊
today = datetime.now()
start_dt = today - timedelta(days=30)

twse_start = start_dt.strftime("%Y%m%d")
twse_end = today.strftime("%Y%m%d")

tpex_start = start_dt.strftime("%Y/%m/%d")
tpex_end = today.strftime("%Y/%m/%d")

print(f"🔍 鎖定抓取區間：{start_dt.strftime('%Y-%m-%d')} 至 {today.strftime('%Y-%m-%d')}")

# ==========================================
# 4. 建立統一規格化與智慧解析模組
# ==========================================

def normalize_date(d_str):
    d_str = str(d_str).strip()
    match = re.match(r'^(\d{3})[/\.](\d{2})[/\.](\d{2})$', d_str)
    if match: return f"{int(match.group(1))+1911}-{match.group(2)}-{match.group(3)}"
    match = re.match(r'^(\d{4})(\d{2})(\d{2})$', d_str)
    if match: return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.match(r'^(\d{4})[/\.](\d{2})[/\.](\d{2})$', d_str)
    if match: return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return d_str

def get_table_data(res):
    if 'data' in res and isinstance(res['data'], list): return res['data']
    if 'tables' in res:
        for tbl in res['tables']:
            if tbl.get('data'): return tbl['data']
    if 'aaData' in res: return res['aaData']
    return []

all_warning_data = []

def process_and_append(raw_data, market, status):
    for row in raw_data:
        if not isinstance(row, list) or len(row) < 3:
            continue
            
        clean_row = [re.sub(r'<[^>]+>', '', str(x)).strip().replace('\r', '').replace('\n', ' ') for x in row]
        
        date_str = ""
        code = ""
        name = ""
        code_idx = -1
        
        for i, val in enumerate(clean_row):
            if not date_str and re.match(r'^\d{3,4}[/.]?\d{2}[/.]?\d{2}$', val):
                date_str = val
            elif not code and re.match(r'^[0-9][0-9A-Za-z]{3,5}$', val):
                code = val
                code_idx = i
                
        if not date_str or not code:
            continue
            
        if code_idx != -1 and code_idx + 1 < len(clean_row):
            name = clean_row[code_idx + 1]
            
        raw_text = " | ".join([x for x in clean_row if x])
        
        all_warning_data.append({
            '日期': normalize_date(date_str), 
            '市場別': market, 
            '代號': code,
            '名稱': name, 
            '狀態': status, 
            '原始資料': raw_text
        })

# ==========================================
# 5. 核心抓取 (加入強固型重試機制)
# ==========================================
MAX_RETRIES = 3
RETRY_DELAY = 5

def fetch_data_with_retry(market, status, url, method='get', payload=None):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if method == 'get':
                res = session.get(url, headers=headers, timeout=20).json()
            else:
                res = session.post(url, headers=headers, data=payload, timeout=20).json()
            
            process_and_append(get_table_data(res), market, status)
            print(f"  ✅ [{market} - {status}] 抓取成功！")
            return
            
        except Exception as e:
            print(f"  ⚠️ 第 {attempt}/{MAX_RETRIES} 次嘗試失敗 ({market}-{status})，原因: {e}")
            if attempt < MAX_RETRIES:
                print(f"    -> 休息 {RETRY_DELAY} 秒後重試...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ❌ [{market} - {status}] 連續失敗，放棄本次抓取。")

print("⚡ 正在打包 [上市 - 注意股] 區間資料...")
url_twse_warn = f"https://www.twse.com.tw/rwd/zh/announcement/notice?querytype=1&startDate={twse_start}&endDate={twse_end}&response=json"
fetch_data_with_retry('上市', '注意', url_twse_warn, method='get')
time.sleep(2)

print("⚡ 正在打包 [上市 - 處置股] 區間資料...")
url_twse_disp = f"https://www.twse.com.tw/rwd/zh/announcement/punish?querytype=3&startDate={twse_start}&endDate={twse_end}&response=json"
fetch_data_with_retry('上市', '處置', url_twse_disp, method='get')
time.sleep(2)

print("⚡ 正在打包 [上櫃 - 注意股] 區間資料...")
url_tpex_warn = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"
payload_tpex_warn = {'startDate': tpex_start, 'endDate': tpex_end, 'type': 'all', 'response': 'json'}
fetch_data_with_retry('上櫃', '注意', url_tpex_warn, method='post', payload=payload_tpex_warn)
time.sleep(2)

print("⚡ 正在打包 [上櫃 - 處置股] 區間資料...")
url_tpex_disp = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"
payload_tpex_disp = {'startDate': tpex_start, 'endDate': tpex_end, 'type': 'all', 'response': 'json'}
fetch_data_with_retry('上櫃', '處置', url_tpex_disp, method='post', payload=payload_tpex_disp)

# ==========================================
# 6. 存檔與合併 (Pandas 魔法排版)
# ==========================================
if all_warning_data:
    df_new = pd.DataFrame(all_warning_data)
    
    if os.path.exists(WARNING_CSV):
        try:
            df_ex = pd.read_csv(WARNING_CSV, dtype={'代號': str})
            df_final = pd.concat([df_ex, df_new], ignore_index=True)
            print("🔍 成功讀取現有資料庫，執行合併與去重...")
        except:
            df_final = df_new
    else:
        df_final = df_new
        
    # 去重與強制排序，確保新資料不覆蓋舊資料且井然有序
    df_final = df_final.drop_duplicates(subset=['日期', '代號', '狀態'], keep='last')
    df_final.sort_values(by=['日期', '代號'], ascending=[False, True], inplace=True)
    
    df_final.to_csv(WARNING_CSV, index=False, encoding='utf-8-sig')
    print(f"\n🎉 記分板更新完成！總資料庫累計: {len(df_final)} 筆。等待 GitHub 判斷異動。")
else:
    print("\n😴 這段期間沒有抓到任何注意/處置資料。")
