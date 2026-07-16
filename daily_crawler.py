import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from datetime import datetime, timedelta
import re
import os
import tw_crawler

print("【系統啟動】正在初始化 全台股日線地基 (PRO 究極版 v2.5 - OHL與法人全武裝版)...")

# ==========================================
# 1. 檔案路徑設定 (GitHub 同層目錄相對路徑)
# ==========================================
CSV_PATH = 'tw_stock_data.csv'

# ==========================================
# 2. 設定通用參數
# ==========================================
session = requests.Session()
retry_strategy = Retry(total=5, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=3)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.twse.com.tw/zh/trading/historical/bwibbu-day.html',
    'Accept': 'application/json, text/javascript, */*; q=0.01'
}
cookies = {
    'JSESSIONID': '0D1931F8D72170AC48D5576AE800DB08',
    '_ga': 'GA1.1.161170101.1783322213',
    '_ga_J2HVMN6FVP': 'GS2.1.s1783322213$o1$g1$t1783322453$j32$l0$h0'
}

MAX_DAILY_RETRIES = 5

# ==========================================
# 3. 歷史資料盤點 (確保最近 120 個真實交易日完整)
# ==========================================
df_existing = pd.DataFrame()
existing_dates = set()

if os.path.exists(CSV_PATH):
    try:
        df_existing = pd.read_csv(CSV_PATH, dtype={'代號': str})
        existing_dates = set(df_existing['日期'].unique())
        print(f"📊 讀取歷史資料，目前已累積 {len(existing_dates)} 個交易日。")
    except Exception as e:
        print(f"⚠️ 讀取 CSV 錯誤 ({e})，將建立新檔案。")

TARGET_TRADING_DAYS = 120
valid_dates = []

print("📅 正在同步台灣證交所官方開盤日曆 (精準排除颱風、假日)...")
master_trading_dates = []
current_date = datetime.now()

for _ in range(7):
    api_month = current_date.strftime("%Y%m01")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={api_month}&response=json"
    
    try:
        res = session.get(url, headers=headers, cookies=cookies).json()
        if res.get('stat') == 'OK' and 'data' in res:
            for row in res['data']:
                parts = row[0].split('/')
                g_year = int(parts[0]) + 1911
                g_date = f"{g_year}-{parts[1]}-{parts[2]}"
                master_trading_dates.append(g_date)
    except Exception as e:
        pass 
    
    current_date = current_date.replace(day=1) - timedelta(days=1)
    time.sleep(1)

master_trading_dates = sorted(list(set(master_trading_dates)))
expected_days = master_trading_dates[-TARGET_TRADING_DAYS:]

for date_str in expected_days:
    if date_str not in existing_dates:
        valid_dates.append(datetime.strptime(date_str, "%Y-%m-%d"))

valid_dates.reverse()

if not valid_dates:
    print("✨ 資料庫已是最新狀態，無缺漏！自動化排程順利打卡下班。")
    exit(0)

# ==========================================
# 4. 輔助函式
# ==========================================
def clean_num(x):
    x = str(x).replace(',', '').strip()
    x = re.sub(r'<[^>]+>', '', x)
    try: return float(x)
    except: return None 

# ==========================================
# 5. 主程式迴圈 (微觀重試機制)
# ==========================================
new_data_frames = []

for count, dt in enumerate(valid_dates, 1):
    date_str = dt.strftime("%Y-%m-%d")
    api_date_twse = dt.strftime("%Y%m%d")
    api_date_str = dt.strftime("%Y-%m-%d")
    tpex_api_date = dt.strftime("%Y/%m/%d")
    
    print(f"\n🎬 處理 [{count}/{len(valid_dates)}] {date_str}...")

    for attempt in range(1, MAX_DAILY_RETRIES + 1):
        try:
            # --- A. 上市邏輯 ---
            try:
                df_twse = tw_crawler.twse_crawler(api_date_str)
            except:
                df_twse = pd.DataFrame()

            if df_twse is None or df_twse.empty:
                print("   ⚠️ 偵測到套件解析異常，啟動 TWSE 官方 API 備用救援...")
                res_fb = session.get(f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={api_date_twse}&type=ALL", headers=headers, cookies=cookies).json()
                target_data, target_fields = [], []
                for i in range(1, 20):
                    if f'fields{i}' in res_fb and f'data{i}' in res_fb:
                        if '證券代號' in res_fb[f'fields{i}']:
                            # 🛡️ 修復點：移除了這行結尾不該存在的冒號！
                            target_fields = res_fb[f'fields{i}']
                            target_data = res_fb[f'data{i}']
                            break
                if not target_data:
                    raise Exception("上市 (TWSE) 官方備用 API 回傳為空 (可能被擋 IP)")
                
                df_twse = pd.DataFrame(target_data, columns=target_fields)
                df_twse = df_twse.rename(columns={'證券代號': '代號', '證券名稱': '名稱', '開盤價': '開盤價', '最高價': '最高價', '最低價': '最低價', '收盤價': '收盤價', '漲跌價差': '漲跌幅', '成交股數': '成交量'})
            else:
                df_twse = df_twse.rename(columns={
                    'Date': '日期', 'SecurityCode': '代號', 'StockName': '名稱', 
                    'OpeningPrice': '開盤價', 'HighestPrice': '最高價', 'LowestPrice': '最低價', 
                    'ClosingPrice': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'
                })
                
            df_twse['代號'] = df_twse['代號'].astype(str).str.strip()
            
            # 上市三大法人拆解
            res_insti = session.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={api_date_twse}&selectType=ALL&response=json", headers=headers, cookies=cookies).json()
            insti_data = res_insti.get('data', [])
            if insti_data:
                tmp_fields = res_insti.get('fields', [])
                tmp_df = pd.DataFrame(insti_data, columns=tmp_fields)
                
                col_map = {'證券代號': '代號', '三大法人買賣超股數': '主力淨買超'}
                if '外資及陸資買賣超股數' in tmp_fields: col_map['外資及陸資買賣超股數'] = '外資買賣超'
                elif '外陸資買賣超股數(不含外資自營商)' in tmp_fields: col_map['外陸資買賣超股數(不含外資自營商)'] = '外資買賣超'
                if '投信買賣超股數' in tmp_fields: col_map['投信買賣超股數'] = '投信買賣超'
                if '自營商買賣超股數' in tmp_fields: col_map['自營商買賣超股數'] = '自營商買賣超'
                
                df_insti = tmp_df[list(col_map.keys())].rename(columns=col_map)
                for c in ['外資買賣超', '投信買賣超', '自營商買賣超']:
                    if c not in df_insti.columns: df_insti[c] = '0'
            else:
                df_insti = pd.DataFrame(columns=['代號', '主力淨買超', '外資買賣超', '投信買賣超', '自營商買賣超'])
            
            # 上市本益比
            res_pe = session.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={api_date_twse}&selectType=ALL&response=json", headers=headers, cookies=cookies).json()
            pe_data = res_pe.get('data', [])
            if pe_data:
                df_pe = pd.DataFrame(pe_data, columns=res_pe.get('fields', []))[['證券代號', '本益比']].rename(columns={'證券代號': '代號'})
            else:
                df_pe = pd.DataFrame(columns=['代號', '本益比'])
            
            df_twse = df_twse.merge(df_insti, on='代號', how='left').merge(df_pe, on='代號', how='left')
            df_twse['市場別'] = '上市'

            # --- B. 上櫃邏輯 ---
            try:
                df_tpex = tw_crawler.tpex_crawler(api_date_str)
            except:
                df_tpex = pd.DataFrame()

            if df_tpex is None or df_tpex.empty:
                print("   ⚠️ 偵測到套件解析異常，啟動 TPEx 官方 API 備用救援...")
                res_fb = session.post('https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes', data={'date': tpex_api_date, 'response': 'json'}, headers=headers).json()
                tables = res_fb.get('tables', [])
                target_data, target_fields = [], []
                for t in tables:
                    if 'fields' in t and '代號' in t['fields']:
                        target_fields = t['fields']
                        target_data = t['data']
                        break
                if not target_data:
                    raise Exception("上櫃 (TPEx) 官方備用 API 回傳為空 (可能被擋 IP)")
                    
                df_tpex = pd.DataFrame(target_data, columns=target_fields)
                df_tpex = df_tpex.rename(columns={'開盤': '開盤價', '最高': '最高價', '最低': '最低價', '收盤': '收盤價', '漲跌': '漲跌幅', '成交股數': '成交量'})
            else:
                df_tpex = df_tpex.rename(columns={'Date': '日期', 'Code': '代號', 'Name': '名稱', 'Open': '開盤價', 'High': '最高價', 'Low': '最低價', 'Close': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'})
                
            df_tpex['代號'] = df_tpex['代號'].astype(str).str.strip()
            
            # 上櫃三大法人拆解 (強制使用 Index 硬核定位)
            res_tpex_insti = session.post('https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade', data={'type': 'Daily', 'sect': 'AL', 'date': tpex_api_date, 'response': 'json'}).json()
            tpex_insti_tables = res_tpex_insti.get('tables', [])
            
            extracted_tpex_insti = []
            if tpex_insti_tables and tpex_insti_tables[0].get('data'):
                for row in tpex_insti_tables[0]['data']:
                    try:
                        if len(row) >= 24:
                            extracted_tpex_insti.append({
                                '代號': row[0],
                                '外資買賣超': row[10],
                                '投信買賣超': row[13],
                                '自營商買賣超': row[22],
                                '主力淨買超': row[23]
                            })
                    except:
                        continue
                        
            if extracted_tpex_insti:
                df_tpex_insti = pd.DataFrame(extracted_tpex_insti)
            else:
                df_tpex_insti = pd.DataFrame(columns=['代號', '主力淨買超', '外資買賣超', '投信買賣超', '自營商買賣超'])
            
            # 上櫃本益比
            res_tpex_pe = session.post('https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate', data={'date': tpex_api_date, 'cate': '', 'response': 'json'}).json()
            tpex_pe_tables = res_tpex_pe.get('tables', [])
            if tpex_pe_tables and tpex_pe_tables[0].get('data'):
                df_tpex_pe = pd.DataFrame(tpex_pe_tables[0]['data'], columns=tpex_pe_tables[0]['fields'])[['股票代號', '本益比']].rename(columns={'股票代號': '代號'})
            else:
                df_tpex_pe = pd.DataFrame(columns=['代號', '本益比'])
            
            df_tpex = df_tpex.merge(df_tpex_insti, on='代號', how='left').merge(df_tpex_pe, on='代號', how='left')
            df_tpex['市場別'] = '上櫃'

            # --- C. 合併整理 ---
            df_today = pd.concat([df_twse, df_tpex], ignore_index=True)
            df_today['日期'] = date_str
            df_today['代號'] = df_today['代號'].astype(str).str.strip()

            cond_stock = df_today['代號'].str.len() <= 5
            cond_fund = df_today['代號'].str.match(r'^(00|01|02)')
            df_today = df_today[cond_stock | cond_fund].copy()

            # 洗淨數值
            for col in ['開盤價', '最高價', '最低價', '收盤價', '成交量', '本益比', '主力淨買超', '外資買賣超', '投信買賣超', '自營商買賣超']:
                if col in df_today.columns:
                    df_today[col] = pd.to_numeric(df_today[col].astype(str).str.replace(',', '').str.replace('--', ''), errors='coerce')
            
            for c in ['開盤價', '最高價', '最低價', '外資買賣超', '投信買賣超', '自營商買賣超']:
                if c not in df_today.columns: df_today[c] = None

            new_data_frames.append(df_today[['日期', '代號', '名稱', '市場別', '開盤價', '最高價', '最低價', '收盤價', '漲跌幅', '成交量', '本益比', '主力淨買超', '外資買賣超', '投信買賣超', '自營商買賣超']])
            print(f" ⚡ 第 {attempt} 次嘗試成功！保留 {len(df_today)} 筆核心標的")
            
            time.sleep(3) 
            break 

        except Exception as e:
            if attempt < MAX_DAILY_RETRIES:
                sleep_sec = 15 * attempt
                print(f"   ⚠️ 第 {attempt} 次抓取失敗 ({type(e).__name__})。系統深呼吸，等待 {sleep_sec} 秒後重試...")
                time.sleep(sleep_sec)
            else:
                print(f"   ❌ 放棄本日抓取：已達最大重試次數 {MAX_DAILY_RETRIES} 次。詳細錯誤: {str(e)}")

# ==========================================
# 6. 最終輸出 (寫入CSV + 滾動視窗清理)
# ==========================================
if new_data_frames:
    df_all = pd.concat([df_existing] + new_data_frames, ignore_index=True)
    df_all = df_all.sort_values(by=['日期', '代號'], ascending=[False, True])

    # --- 🧹 啟動滾動視窗自動瘦身 ---
    MAX_KEEP_DAYS = 300  
    
    unique_dates = sorted(df_all['日期'].unique(), reverse=True) 
    if len(unique_dates) > MAX_KEEP_DAYS:
        cutoff_date = unique_dates[MAX_KEEP_DAYS - 1]
        df_all = df_all[df_all['日期'] >= cutoff_date].copy()
        print(f" 🧹 觸發自動瘦身：已清除 {cutoff_date} 之前的歷史資料，保持系統輕量化！")

    df_all.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"\n🎉 執行完成！CSV 已精準更新至: {CSV_PATH} (目前收錄 {len(df_all['日期'].unique())} 天資料)")
