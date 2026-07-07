import os
import re
import pandas as pd
import requests
import tw_crawler

print("【測試啟動】開始執行單日 (2026-07-06) 寫入測試...")

CSV_PATH = 'tw_stock_data.csv'
date_str = '2026-07-06'
api_date_twse = '20260706'
tpex_api_date = '2026/07/06'

session = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 讀取現有 CSV (若有的話)
if os.path.exists(CSV_PATH):
    df_existing = pd.read_csv(CSV_PATH, dtype={'代號': str})
else:
    df_existing = pd.DataFrame()

try:
    # --- 上市行情 ---
    df_twse = tw_crawler.twse_crawler(date_str)
    df_twse = df_twse.rename(columns={'Date': '日期', 'SecurityCode': '代號', 'StockName': '名稱', 'ClosingPrice': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'})
    df_twse['代號'] = df_twse['代號'].astype(str).str.strip()
    
    res_insti = session.get(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={api_date_twse}&selectType=ALL&response=json", headers=headers).json()
    insti_data = res_insti.get('data', [])
    df_insti = pd.DataFrame(insti_data, columns=res_insti.get('fields', []))[['證券代號', '三大法人買賣超股數']].rename(columns={'證券代號':'代號', '三大法人買賣超股數':'主力淨買超'}) if insti_data else pd.DataFrame(columns=['代號', '主力淨買超'])
    
    res_pe = session.get(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={api_date_twse}&selectType=ALL&response=json", headers=headers).json()
    pe_data = res_pe.get('data', [])
    df_pe = pd.DataFrame(pe_data, columns=res_pe.get('fields', []))[['證券代號', '本益比']].rename(columns={'證券代號':'代號'}) if pe_data else pd.DataFrame(columns=['代號', '本益比'])
    
    df_twse = df_twse.merge(df_insti, on='代號', how='left').merge(df_pe, on='代號', how='left')
    df_twse['市場別'] = '上市'

    # --- 上櫃行情 ---
    df_tpex = tw_crawler.tpex_crawler(date_str)
    df_tpex = df_tpex.rename(columns={'Date': '日期', 'Code': '代號', 'Name': '名稱', 'Close': '收盤價', 'Change': '漲跌幅', 'TradeVolume': '成交量'})
    df_tpex['代號'] = df_tpex['代號'].astype(str).str.strip()
    
    res_tpex_insti = session.post('https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade', data={'type': 'Daily', 'sect': 'AL', 'date': tpex_api_date, 'response': 'json'}, headers=headers).json()
    tpex_insti_tables = res_tpex_insti.get('tables', [])
    df_tpex_insti = pd.DataFrame(tpex_insti_tables[0]['data'], columns=tpex_insti_tables[0]['fields'])[['代號', '三大法人買賣超股數合計']].rename(columns={'三大法人買賣超股數合計':'主力淨買超'}) if tpex_insti_tables and tpex_insti_tables[0].get('data') else pd.DataFrame(columns=['代號', '主力淨買超'])
    
    res_tpex_pe = session.post('https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate', data={'date': tpex_api_date, 'cate': '', 'response': 'json'}, headers=headers).json()
    tpex_pe_tables = res_tpex_pe.get('tables', [])
    df_tpex_pe = pd.DataFrame(tpex_pe_tables[0]['data'], columns=tpex_pe_tables[0]['fields'])[['股票代號', '本益比']].rename(columns={'股票代號':'代號'}) if tpex_pe_tables and tpex_pe_tables[0].get('data') else pd.DataFrame(columns=['代號', '本益比'])
    
    df_tpex = df_tpex.merge(df_tpex_insti, on='代號', how='left').merge(df_tpex_pe, on='代號', how='left')
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
    
    df_final = df_today[['日期', '代號', '名稱', '市場別', '收盤價', '漲跌幅', '成交量', '本益比', '主力淨買超']]
    
    # 與歷史合併並存檔
    df_all = pd.concat([df_existing, df_final], ignore_index=True)
    df_all = df_all.sort_values(by=['日期', '代號'], ascending=[False, True])
    df_all.to_csv(CSV_PATH, index=False, encoding='utf-8-sig')
    
    print(f"🎉 單日爬取成功！資料已成功導出，共計 {len(df_final)} 筆核心股票標的。")

except Exception as e:
    print(f"❌ 測試執行失敗，原因: {e}")
