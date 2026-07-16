import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from datetime import datetime, timedelta
import re
import os

print("【系統啟動】獨立大盤指數爬蟲 (Index Crawler v3.0 - 正式上線版)...")

# ==========================================
# 1. 檔案路徑設定
# ==========================================
INDEX_CSV_PATH = 'tw_index_data.csv'

# ==========================================
# 2. 設定通用參數
# ==========================================
session = requests.Session()
retry_strategy = Retry(total=5, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=3)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/150.0.0.0',
    'Accept': 'application/json, text/javascript, */*; q=0.01'
}

MAX_DAILY_RETRIES = 5
TARGET_TRADING_DAYS = 120

# ==========================================
# 3. 歷史資料盤點 (決定要補抓哪些日期)
# ==========================================
df_existing = pd.DataFrame()
existing_dates = set()

if os.path.exists(INDEX_CSV_PATH):
    try:
        df_existing = pd.read_csv(INDEX_CSV_PATH)
        existing_dates = set(df_existing['日期'].unique())
        print(f"📊 讀取大盤歷史資料，目前已累積 {len(existing_dates)} 個交易日。")
    except Exception as e:
        print(f"⚠️ 讀取 CSV 錯誤 ({e})，將建立新檔案。")

print("📅 正在同步台灣證交所官方開盤日曆...")
master_trading_dates = []
current_date = datetime.now()

# 往前抓 7 個月的官方交易日 (建立基準日曆)
for _ in range(7):
    api_month = current_date.strftime("%Y%m01")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={api_month}&response=json"
    try:
        res = session.get(url, headers=headers).json()
        if res.get('stat') == 'OK' and 'data' in res:
            for row in res['data']:
                parts = row[0].split('/')
                g_year = int(parts[0]) + 1911
                master_trading_dates.append(f"{g_year}-{parts[1]}-{parts[2]}")
    except:
        pass 
    current_date = current_date.replace(day=1) - timedelta(days=1)
    time.sleep(1)

master_trading_dates = sorted(list(set(master_trading_dates)))
expected_days = master_trading_dates[-TARGET_TRADING_DAYS:]

# 找出缺漏的日期
valid_dates = [datetime.strptime(d, "%Y-%m-%d") for d in expected_days if d not in existing_dates]
valid_dates.reverse()

if not valid_dates:
    print("✨ 大盤資料庫已是最新狀態，無缺漏！自動化排程順利打卡下班。")
    exit(0)

# ==========================================
# 4. 輔助函式
# ==========================================
def clean_num(x):
    if pd.isna(x) or x == '' or x == '--': return None
    x = str(x).replace(',', '').strip()
    x = re.sub(r'<[^>]+>', '', x)
    try: return float(x)
    except: return None 

# ==========================================
# 5. 主程式迴圈 (極速抓取大盤)
# ==========================================
new_index_frames = []

for count, dt in enumerate(valid_dates, 1):
    date_str = dt.strftime("%Y-%m-%d")
    twse_date = dt.strftime("%Y%m%d")
    tpex_date = dt.strftime("%Y/%m/%d")
    
    print(f"\n🎬 處理 [{count}/{len(valid_dates)}] {date_str} 大盤指數...")

    for attempt in range(1, MAX_DAILY_RETRIES + 1):
        try:
            daily_data = []

            # --- A. 抓取上市大盤 (加權指數) ---
            twse_url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={twse_date}&type=IND"
            res_twse = session.get(twse_url, headers=headers, timeout=10).json()
            
            twse_success = False
            if 'tables' in res_twse:
                for table in res_twse['tables']:
                    if 'data' in table:
                        for row in table['data']:
                            if row[0].strip() == '發行量加權股價指數':
                                close_price = clean_num(row[1])
                                change = clean_num(row[3])
                                if '-' in str(row[2]): change = -abs(change)
                                
                                daily_data.append({
                                    '日期': date_str, 
                                    '市場別': '上市', 
                                    '指數名稱': '加權指數', 
                                    '收盤價': close_price, 
                                    '漲跌點數': change
                                })
                                twse_success = True
                                break
                    if twse_success: break
            
            # --- B. 抓取上櫃大盤 (櫃買指數) ---
            tpex_url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/indexSummary"
            res_tpex = session.post(tpex_url, data={'date': tpex_date, 'response': 'json'}, headers=headers, timeout=10).json()
            
            tpex_success = False
            if 'tables' in res_tpex:
                for table in res_tpex['tables']:
                    if 'data' in table:
                        for row in table['data']:
                            if row[0].strip() == '櫃買指數':
                                close_price = clean_num(row[1])
                                change = clean_num(row[2])
                                
                                daily_data.append({
                                    '日期': date_str, 
                                    '市場別': '上櫃', 
                                    '指數名稱': '櫃買指數', 
                                    '收盤價': close_price, 
                                    '漲跌點數': change
                                })
                                tpex_success = True
                                break
                    if tpex_success: break

            # --- C. 合併單日紀錄 ---
            if daily_data:
                df_today = pd.DataFrame(daily_data)
                new_index_frames.append(df_today)
                print(f" ⚡ 第 {attempt} 次嘗試成功！加權/櫃買指數已收錄。")
                time.sleep(2) # 抓大盤不用停太久，2秒足矣
                break
            else:
                # 若兩個都沒抓到，代表可能是假日或無交易
                raise Exception("API 未回傳預期的大盤欄位 (可能非交易日)")

        except Exception as e:
            if attempt < MAX_DAILY_RETRIES:
                sleep_sec = 5 * attempt
                print(f"   ⚠️ 第 {attempt} 次抓取失敗 ({e})。等待 {sleep_sec} 秒後重試...")
                time.sleep(sleep_sec)
            else:
                print(f"   ❌ 放棄本日抓取：已達最大重試次數。詳細錯誤: {str(e)}")

# ==========================================
# 6. 最終輸出 (寫入 CSV + 滾動視窗清理)
# ==========================================
if new_index_frames:
    df_all = pd.concat([df_existing] + new_index_frames, ignore_index=True)
    
    # 確保不會有重複的天數，並按日期降序排列
    df_all = df_all.drop_duplicates(subset=['日期', '市場別'], keep='last')
    df_all = df_all.sort_values(by=['日期', '市場別'], ascending=[False, True])

    # --- 🧹 啟動滾動視窗自動瘦身 ---
    MAX_KEEP_DAYS = 300  
    
    unique_dates = sorted(df_all['日期'].unique(), reverse=True) 
    if len(unique_dates) > MAX_KEEP_DAYS:
        cutoff_date = unique_dates[MAX_KEEP_DAYS - 1]
        df_all = df_all[df_all['日期'] >= cutoff_date].copy()
        print(f" 🧹 觸發自動瘦身：已清除 {cutoff_date} 之前的歷史大盤資料！")

    df_all.to_csv(INDEX_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"\n🎉 執行完成！大盤 CSV 已精準更新至: {INDEX_CSV_PATH} (目前收錄 {len(df_all['日期'].unique())} 天資料)")
