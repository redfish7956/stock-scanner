import requests
import pandas as pd
import os

print("【系統啟動】台股基本資料爬蟲 (Info Crawler v1.0 - 靜態資料建立)...")

INFO_CSV_PATH = 'tw_stock_info.csv'

# ==========================================
# 1. 抓取上市 (TWSE) 基本資料
# ==========================================
print("⏳ 正在抓取上市 (TWSE) 公司基本資料...")
twse_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
try:
    res_twse = requests.get(twse_url, timeout=15).json()
    df_twse = pd.DataFrame(res_twse)
    
    # 篩選並重新命名需要的欄位
    df_twse = df_twse[['公司代號', '公司名稱', '產業別', '實收資本額', '已發行普通股數或TDR原股發行股數']]
    df_twse = df_twse.rename(columns={
        '公司代號': '代號',
        '公司名稱': '名稱',
        '已發行普通股數或TDR原股發行股數': '發行股數'
    })
    df_twse['市場別'] = '上市'
    print(f"  ✅ 上市抓取成功: 共 {len(df_twse)} 筆")
except Exception as e:
    print(f"  ❌ 上市抓取失敗: {e}")
    df_twse = pd.DataFrame()

# ==========================================
# 2. 抓取上櫃 (TPEx) 基本資料
# ==========================================
print("\n⏳ 正在抓取上櫃 (TPEx) 公司基本資料...")
tpex_url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
try:
    res_tpex = requests.get(tpex_url, timeout=15).json()
    df_tpex = pd.DataFrame(res_tpex)
    
    # 篩選並重新命名需要的欄位
    df_tpex = df_tpex[['公司代號', '公司名稱', '產業別', '實收資本額', '已發行普通股數或TDR原股發行股數']]
    df_tpex = df_tpex.rename(columns={
        '公司代號': '代號',
        '公司名稱': '名稱',
        '已發行普通股數或TDR原股發行股數': '發行股數'
    })
    df_tpex['市場別'] = '上櫃'
    print(f"  ✅ 上櫃抓取成功: 共 {len(df_tpex)} 筆")
except Exception as e:
    print(f"  ❌ 上櫃抓取失敗: {e}")
    df_tpex = pd.DataFrame()

# ==========================================
# 3. 合併與資料清洗
# ==========================================
if not df_twse.empty or not df_tpex.empty:
    df_all = pd.concat([df_twse, df_tpex], ignore_index=True)
    
    # 清洗：去除代號前後空白
    df_all['代號'] = df_all['代號'].astype(str).str.strip()
    
    # 清洗：將資本額與股數轉為乾淨的數值
    for col in ['實收資本額', '發行股數']:
        df_all[col] = pd.to_numeric(df_all[col].astype(str).str.replace(',', ''), errors='coerce')
    
    # 白名單過濾：只保留普通股 (4碼)、ETF (00開頭) 等
    cond_stock = df_all['代號'].str.len() <= 5
    cond_fund = df_all['代號'].str.match(r'^(00|01|02)')
    df_all = df_all[cond_stock | cond_fund].copy()

    # 排序並輸出
    df_all = df_all.sort_values(by=['代號'])
    df_all.to_csv(INFO_CSV_PATH, index=False, encoding='utf-8-sig')
    
    print(f"\n🎉 執行完成！基本資料已儲存至: {INFO_CSV_PATH}")
    print(f"總共收錄了 {len(df_all)} 檔標的之身分證資料。")
else:
    print("\n❌ 抓取失敗，無任何資料被合併。")
