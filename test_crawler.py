import os
import re
import pandas as pd
import requests
import tw_crawler
import time

print("【追加寫入測試】驗證 GitHub Actions 讀取舊檔 + 寫入新檔能力...")

CSV_PATH = 'tw_stock_data.csv'
# 🎯 測試目標：強迫抓取上禮拜的這五天
TARGET_DATES = ['2026-06-29', '2026-06-30', '2026-07-01', '2026-07-02', '2026-07-03']

session = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# ==========================================
# 關鍵測試點：讀取剛才 GitHub 產生的舊 CSV
# ==========================================
df_existing = pd.DataFrame()
existing_dates = set()

if os.path.exists(CSV_PATH):
    df_existing = pd.read_csv(CSV_PATH, dtype={'代號': str})
    existing_dates = set(df_existing['日期'].unique())
    print(f"✅ 成功讀取雲端舊檔！目前檔案內已包含的日期：{existing_dates}")
else:
    print("⚠️ 找不到舊檔，將建立新檔 (這不該發生，如果出現代表讀取失敗)。")

# 篩選出還沒抓過的日子
valid_dates = [d for d in TARGET_DATES if d not in existing_dates]

if not valid_dates:
    print("✨ 這些日期都已經在 CSV 裡囉！")
    exit(0)

new_data_frames = []

for date_str in valid_dates:
    print(f"\n🎬 處理 {date_str}...")
    api_date_twse = date_str.replace('-', '')
    tpex_api_date = date_str.replace('-', '/')
    
    try:
        # --- 上市行情 ---
        try:
            df_twse = tw_crawler.twse_crawler(date_str)
        except:
            df_twse = pd.DataFrame()
            
        if df_twse is None or df_twse.empty:
            print("   ⚠️ 啟動 TWSE 官方 API 備用救援...")
            res_fb = session.get(f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={api_date_twse}&type=ALL", headers=headers).json()
            target_data, target_fields = [], []
            for i in range(1, 20):
                if f'fields{i}' in res_fb and f'data{i}' in res_fb:
                    if '證券代號' in res_fb[f'fields{i}']:
                        target_fields = res_fb[f'fields{i}']
                        target_data = res_fb[f'data{i}']
                        break
            df_twse = pd.DataFrame(target_data, columns=target_fields)
            df_twse = df_twse.rename(columns={'證券代號': '代號', '證券名稱': '名稱', '收盤價': '收盤價', '漲跌價差': '漲跌幅', '成交股數': '成交量'})
        else:
            df_twse = df_twse.rename(columns={'Date': '日期', 'SecurityCode': '代號', 'StockName': '名稱', 'ClosingPrice': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'})
            
        df_twse['代號'] = df_twse['代號'].astype(str).str.strip()
        
        # --- 簡易化測試：為了加速驗證寫入能力，這版測試先跳過三大法人與本益比，只留基礎收盤價 ---
        df_twse['主力淨買超'] = None
        df_twse['本益比'] = None
        df_twse['市場別'] = '上市'

        # --- 上櫃行情 ---
        try:
            df_tpex = tw_crawler.tpex_crawler(date_str)
        except:
            df_tpex = pd.DataFrame()
            
        if df_tpex is None or df_tpex.empty:
            print("   ⚠️ 啟動 TPEx 官方 API 備用救援...")
            res_fb = session.post('https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes', data={'date': tpex_api_date, 'response': 'json'}, headers=headers).json()
            tables = res_fb.get('tables', [])
            target_data, target_fields = [], []
            for t in tables:
                if 'fields' in t and '代號' in t['fields']:
                    target_fields = t['fields']
                    target_data = t['data']
                    break
            df_tpex = pd.DataFrame(target_data, columns=target_fields)
            df_tpex = df_tpex.rename(columns={'收盤': '收盤價', '漲跌': '漲跌幅', '成交股數': '成交量'})
        else:
            df_tpex = df_tpex.rename(columns={'Date': '日期', 'Code': '代號', 'Name': '名稱', 'Close': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'})
            
        df_tpex['代號'] = df_tpex['代號'].astype(str).str.strip()
        df_tpex['主力淨買超'] = None
        df_tpex['本益比'] = None
        df_tpex['市場別'] = '上櫃'

        # --- 合併與過濾 ---
        df_today = pd.concat([df_twse, df_tpex], ignore_index=True)
        df_today['日期'] = date_str
        df_today['代號'] = df_today['代號'].astype(str).str.strip()

        cond_stock = df_today['代號'].str.len() <= 5
        cond_fund = df_today['代號'].str.match(r'^(00|01|02)')
        df_today = df_today[cond_stock | cond_fund].copy()

        for col in ['收盤價', '成交量', '本益比', '主力淨買超']:
            df_today[col] = pd.to_numeric(df_today[col].astype(str).str.replace(',', ''), errors='coerce')
        
        new_data_frames.append(df_today[['日期', '代號', '名稱', '市場別', '收盤價', '漲跌幅', '成交量', '本益比', '主力淨買超']])
        print(f" ⚡ 處理完成: 保留 {len(df_today)} 筆核心標的")

    except Exception as e:
        print(f" ⚠️ 處理失敗: {e}")
        
    time.sleep(2) # 禮貌延遲

# ==========================================
# 關鍵寫入點：與舊資料合併並覆蓋存檔
# ==========================================
if new_data_frames:
    df_all = pd.concat([df_existing] + new_data_frames, ignore_index=True)
    df_all = df_all.sort_values(by=['日期', '代號'], ascending=[False, True])
    df_all.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"\n🎉 寫入成功！CSV 現在包含了 7/6 以及 6/29~7/3，共計 {len(df_all)} 筆資料。")
