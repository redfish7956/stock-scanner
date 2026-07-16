import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from datetime import datetime, timedelta
import re
import os

print("【系統啟動】台股個股當沖明細爬蟲 (DayTrade Crawler v3.2 - 上帝日曆強固版)...")

# ==========================================
# 1. 檔案路徑與核心參數設定
# ==========================================
DAYTRADE_CSV_PATH = 'tw_daytrade_data.csv'
TARGET_TRADING_DAYS = 150  # 🎯 儲存與回測黃金天數：150 個真實交易日
MAX_DAILY_RETRIES = 5

# ==========================================
# 2. 建立強固的 Session 連線機制
# ==========================================
session = requests.Session()
retry_strategy = Retry(total=5, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=3)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/150.0.0.0',
    'Accept': 'application/json, text/javascript, */*; q=0.01'
}

# ==========================================
# 3. 歷史資料盤點 (讀取已擁有的交易日)
# ==========================================
df_existing = pd.DataFrame()
existing_dates = set()

if os.path.exists(DAYTRADE_CSV_PATH):
    try:
        df_existing = pd.read_csv(DAYTRADE_CSV_PATH, dtype={'代號': str})
        existing_dates = set(df_existing['日期'].unique())
        print(f"📊 讀取當沖歷史資料，目前已累積 {len(existing_dates)} 個交易日。")
    except Exception as e:
        print(f"⚠️ 讀取 CSV 錯誤 ({e})，將建立新檔案。")

# ==========================================
# 4. 同步「上帝視角官方日曆」 (自動排除颱風、國定假日、週末)
# ==========================================
print("📅 正在同步台灣證交所官方開盤日曆...")
master_trading_dates = []
current_date = datetime.now()

# 往前推算 9 個月，確保在扣除所有假期後，依然能湊足 150 個真實交易日
for _ in range(9):
    api_month = current_date.strftime("%Y%m01")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={api_month}&response=json"
    
    try:
        res = session.get(url, headers=headers, timeout=15).json()
        if res.get('stat') == 'OK' and 'data' in res:
            for row in res['data']:
                parts = row[0].split('/')
                g_year = int(parts[0]) + 1911
                g_date = f"{g_year}-{parts[1]}-{parts[2]}"
                master_trading_dates.append(g_date)
    except Exception as e:
        print(f"  ⚠️ 同步月度日曆暫時失敗 ({e})，跳過。")
        
    current_date = current_date.replace(day=1) - timedelta(days=1)
    time.sleep(1.5)

# 整理與排序日曆
master_trading_dates = sorted(list(set(master_trading_dates)))
expected_days = master_trading_dates[-TARGET_TRADING_DAYS:]

# 比對出真正需要抓取 (缺漏) 的日期
valid_dates = []
for date_str in expected_days:
    if date_str not in existing_dates:
        valid_dates.append(datetime.strptime(date_str, "%Y-%m-%d"))

# 從最近的日期往前倒著補，能最快拿到最新數據
valid_dates.reverse()

if not valid_dates:
    print("✨ 當沖資料庫已是最新狀態，無缺漏！自動化排程順利打卡下班。")
    exit(0)

print(f"🎯 盤點完畢！系統判定需要補抓 {len(valid_dates)} 個真實交易日的當沖數據。")

# ==========================================
# 5. 主程式迴圈 (微觀重試與精準採集)
# ==========================================
new_frames = []

for count, dt in enumerate(valid_dates, 1):
    date_str = dt.strftime("%Y-%m-%d")
    twse_date = dt.strftime("%Y%m%d")      
    tpex_date = dt.strftime("%Y/%m/%d")    
    
    print(f"\n🎬 處理 [{count}/{len(valid_dates)}] {date_str} 當沖個股數據...")
    daily_frames = []

    for attempt in range(1, MAX_DAILY_RETRIES + 1):
        try:
            # --- [A] 證交所 (上市) 抓取 ---
            twse_url = f"https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date={twse_date}&selectType=All&response=json"
            res_twse = session.get(twse_url, headers=headers, timeout=12).json()

            twse_success = False
            if 'tables' in res_twse and len(res_twse['tables']) > 1:
                dt_table = res_twse['tables'][1]
                df_twse = pd.DataFrame(dt_table['data'], columns=dt_table['fields'])
                df_twse = df_twse[['證券代號', '證券名稱', '當日沖銷交易成交股數', '當日沖銷交易買進成交金額', '當日沖銷交易賣出成交金額']]
                df_twse = df_twse.rename(columns={'證券代號': '代號', '證券名稱': '名稱'})
                df_twse['市場別'] = '上市'
                daily_frames.append(df_twse)
                twse_success = True

            # --- [B] 櫃買中心 (上櫃) 抓取 ---
            tpex_url = "https://www.tpex.org.tw/www/zh-tw/intraday/stat"
            tpex_payload = {'type': 'Daily', 'date': tpex_date, 'response': 'json'}
            res_tpex = session.post(tpex_url, data=tpex_payload, headers=headers, timeout=12).json()

            tpex_success = False
            if 'tables' in res_tpex and len(res_tpex['tables']) > 1:
                dt_table = res_tpex['tables'][1]
                df_tpex = pd.DataFrame(dt_table['data'], columns=dt_table['fields'])
                df_tpex = df_tpex[['證券代號', '證券名稱', '當日沖銷交易成交股數', '當日沖銷交易買進成交金額', '當日沖銷交易賣出成交金額']]
                df_tpex = df_tpex.rename(columns={'證券代號': '代號', '證券名稱': '名稱'})
                df_tpex['市場別'] = '上櫃'
                daily_frames.append(df_tpex)
                tpex_success = True

            # --- [C] 整合單日數據 ---
            if twse_success or tpex_success:
                df_today = pd.concat(daily_frames, ignore_index=True)
                df_today.insert(0, '日期', date_str)

                # 數值清洗，移除逗號並轉為數值
                for col in ['當日沖銷交易成交股數', '當日沖銷交易買進成交金額', '當日沖銷交易賣出成交金額']:
                    df_today[col] = pd.to_numeric(df_today[col].astype(str).str.replace(',', ''), errors='coerce')

                new_frames.append(df_today)
                print(f"  ⚡ 第 {attempt} 次嘗試成功！當日共計收錄 {len(df_today)} 筆個股當沖明細。")
                time.sleep(4) # 當沖資料量較大，延遲 4 秒溫柔對待交易所
                break
            else:
                raise Exception("API 未回傳預期的當沖表格 (此日期可能無交易資料)")

        except Exception as e:
            if attempt < MAX_DAILY_RETRIES:
                sleep_sec = 10 * attempt
                print(f"  ⚠️ 第 {attempt} 次嘗試失敗 ({e})。等待 {sleep_sec} 秒後重試...")
                time.sleep(sleep_sec)
            else:
                print(f"  ❌ 本日抓取放棄：已達最大重試次數。詳細錯誤: {str(e)}")

# ==========================================
# 6. 合併資料與 150 天滾動自動瘦身
# ==========================================
if new_frames:
    df_all = pd.concat([df_existing] + new_frames, ignore_index=True)
    
    df_all['代號'] = df_all['代號'].astype(str).str.strip()
    df_all = df_all.drop_duplicates(subset=['日期', '代號'], keep='last')
    
    # 過濾掉權證，只保留股票與 ETF
    cond_stock = df_all['代號'].str.len() <= 5
    cond_fund = df_all['代號'].str.match(r'^(00|01|02)')
    df_all = df_all[cond_stock | cond_fund].copy()
    
    df_all = df_all.sort_values(by=['日期', '代號'], ascending=[False, True])

    # 🧹 啟動 150 天滾動自動瘦身
    unique_dates = sorted(df_all['日期'].unique(), reverse=True)
    if len(unique_dates) > TARGET_TRADING_DAYS:
        cutoff_date = unique_dates[TARGET_TRADING_DAYS - 1]
        df_all = df_all[df_all['日期'] >= cutoff_date].copy()
        print(f" 🧹 觸發自動瘦身：已清除 {cutoff_date} 之前的歷史當沖資料，保持資料庫為黃金 150 日！")

    df_all.to_csv(DAYTRADE_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"\n🎉 執行完成！當沖 CSV 已更新至: {DAYTRADE_CSV_PATH} (目前收錄 {len(df_all['日期'].unique())} 天資料)")
else:
    print("\n❌ 抓取結束，無新資料更新。")
