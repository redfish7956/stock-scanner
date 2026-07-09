import requests
import pandas as pd
import time
from io import StringIO
import os
import sys
from datetime import datetime

def get_sliding_window_quarters():
    """
    時間導航儀：根據今天日期，推算當前最可能公佈財報的 2 個季度。
    """
    now = datetime.now()
    year_roc = now.year - 1911
    month = now.month
    
    # 台股財報死線：Q1(5/15), Q2(8/14), Q3(11/14), Q4年報(隔年3/31)
    if month in [1, 2, 3]:
        return [(year_roc - 1, 3), (year_roc - 1, 4)]
    elif month in [4, 5]:
        return [(year_roc - 1, 4), (year_roc, 1)]
    elif month in [6, 7, 8]:
        return [(year_roc, 1), (year_roc, 2)]
    elif month in [9, 10, 11]:
        return [(year_roc, 2), (year_roc, 3)]
    else: # 12月
        return [(year_roc, 3), (year_roc, 4)]

def fetch_mops_with_curl(year, quarter):
    """
    使用 cURL 破解邏輯抓取指定季度的上市/上櫃資料
    """
    url = 'https://mopsov.twse.com.tw/mops/web/ajax_t163sb04'
    
    # 🔐 【安全機制】從 GitHub Secrets 動態讀取 Cookie，不寫死在程式碼裡
    mops_cookie = os.getenv('MOPS_COOKIE', '')
    if not mops_cookie:
        print("⚠️ 警告：找不到 MOPS_COOKIE 環境變數，可能會被伺服器阻擋！")

    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie': mops_cookie,
        'Origin': 'https://mopsov.twse.com.tw',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    }

    quarter_dfs = []
    markets = {'sii': '上市', 'otc': '上櫃'}
    
    for market_code, market_name in markets.items():
        data = {
            'encodeURIComponent': '1', 'step': '1', 'firstin': '1', 'off': '1',
            'isQuery': 'Y', 'TYPEK': market_code,
            'year': str(year), 'season': str(quarter).zfill(2) 
        }

        try:
            response = requests.post(url, headers=headers, data=data, timeout=20)
            response.encoding = 'utf8'
            
            # 偵測是否被軟性封鎖
            if "查詢過於頻繁" in response.text:
                print(f"  🛑 遭伺服器阻擋 ({market_name})，休眠後跳過...")
                time.sleep(5)
                continue

            dfs = pd.read_html(StringIO(response.text))
            market_industry_dfs = []
            
            for df in dfs:
                if len(df) > 3:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = ['_'.join([str(c) for c in col if 'Unnamed' not in str(c)]).strip() for col in df.columns]
                    df.columns = [str(c).replace(' ', '').replace('\n', '') for c in df.columns]
                    
                    id_col = next((c for c in df.columns if '代號' in c or '代碼' in c), None)
                    
                    if not id_col:
                        for i in range(min(3, len(df))):
                            row_vals = [str(v).replace(' ', '').replace('\n', '') for v in df.iloc[i].values]
                            if any('代號' in v or '代碼' in v for v in row_vals):
                                df.columns = row_vals
                                id_col = next(v for v in row_vals if '代號' in v or '代碼' in v)
                                df = df.iloc[i+1:].reset_index(drop=True)
                                break

                    if id_col:
                        valid_df = df[df[id_col].astype(str).str.strip().str.isnumeric()].copy()
                        if not valid_df.empty:
                            valid_df.rename(columns={id_col: '公司代號'}, inplace=True)
                            market_industry_dfs.append(valid_df)
            
            if market_industry_dfs:
                target_df = pd.concat(market_industry_dfs, ignore_index=True)
                target_df['年度'] = year
                target_df['季度'] = f"Q{quarter}"
                target_df['市場別'] = market_name
                quarter_dfs.append(target_df)
                print(f"  ✅ 成功取得 {year} Q{quarter} - {market_name}，共 {len(target_df)} 筆")
            else:
                print(f"  ⚠️ 警告：{year} Q{quarter} - {market_name} 未找到數據 (可能尚未公佈)。")
                
        except ValueError:
            print(f"  ⚠️ 警告：該季度無表格 (可能尚未公佈)")
        except Exception as e:
            print(f"  ❌ 錯誤：抓取 {year} Q{quarter} - {market_name} 發生異常: {e}")
            
        time.sleep(3)
        
    if quarter_dfs:
        return pd.concat(quarter_dfs, ignore_index=True)
    return pd.DataFrame()


def clean_and_calculate_metrics(df):
    """
    清洗數值欄位並維持全欄位保留
    """
    if df.empty: return df
        
    df.columns = [str(c).replace(" ", "").replace("\n", "") for c in df.columns]
    
    rename_map = {}
    for col in df.columns:
        if col in ['公司代號', '年度', '季度', '市場別']: continue
        if '公司名稱' in col and '公司名稱' not in rename_map.values(): rename_map[col] = '公司名稱'
        elif '營業收入' in col and '營業收入' not in rename_map.values(): rename_map[col] = '營業收入'
        elif '營業毛利' in col and '率' not in col and '營業毛利' not in rename_map.values(): rename_map[col] = '營業毛利'
        elif ('每股盈餘' in col or 'EPS' in col) and 'EPS' not in rename_map.values(): rename_map[col] = 'EPS'
            
    df.rename(columns=rename_map, inplace=True)
    
    metadata_cols = ['公司代號', '公司名稱', '年度', '季度', '市場別']
    value_cols = [c for c in df.columns if c not in metadata_cols]
    
    for col in value_cols:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace(',', '')
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    if '營業收入' in df.columns and '營業毛利' in df.columns:
        df['營業毛利率(%)'] = df.apply(
            lambda row: round((row['營業毛利'] / row['營業收入'] * 100), 2) if row['營業收入'] != 0 else 0, axis=1
        )
        
    front_cols = [c for c in metadata_cols if c in df.columns] + \
                 [c for c in ['營業收入', '營業毛利', '營業毛利率(%)', 'EPS'] if c in df.columns]
    other_cols = [c for c in df.columns if c not in front_cols]
    
    return df[front_cols + other_cols]


if __name__ == "__main__":
    CSV_FILENAME = 'mops_financial_history_8Q_ALL_DATA.csv'
    
    print("🚀 [Phase 2 自動化] 開始執行每日財報更新排程...")
    
    # 1. 啟動時間導航儀，取得目標季度
    target_quarters = get_sliding_window_quarters()
    print(f"📅 根據當前月份，鎖定追蹤之季度為: {target_quarters}")
    
    # 2. 抓取與清洗新資料
    new_data_list = []
    for yr, qtr in target_quarters:
        raw_df = fetch_mops_with_curl(yr, qtr)
        processed_df = clean_and_calculate_metrics(raw_df)
        if not processed_df.empty:
            new_data_list.append(processed_df)
            
    if not new_data_list:
        print("😴 今日鎖定之季度皆無任何有效數據，結束程式。")
        sys.exit()
        
    df_new = pd.concat(new_data_list, ignore_index=True)
    df_new.fillna(0, inplace=True)
    
    # 3. 🛡️ 企業級 Upsert 覆核取代邏輯
    if os.path.exists(CSV_FILENAME):
        print(f"🔍 讀取歷史資料庫進行合併與取代作業...")
        df_master = pd.read_csv(CSV_FILENAME)
        
        # 將舊資料與今天剛抓到的新資料疊加
        df_combined = pd.concat([df_master, df_new], ignore_index=True)
        
        # 【核心魔法】用 Primary Key 進行去重複，保留最新的一筆 (解決更正報表問題)
        df_combined.drop_duplicates(subset=['年度', '季度', '公司代號'], keep='last', inplace=True)
    else:
        print(f"⚠️ 找不到歷史資料庫，將直接建立新檔案。")
        df_combined = df_new

    # 排序讓資料美觀
    df_combined.sort_values(by=['年度', '季度', '公司代號'], ascending=[False, False, True], inplace=True)
    
    # 4. 存檔 (交給 Git 決定是否有實質異動)
    df_combined.to_csv(CSV_FILENAME, index=False, encoding='utf-8-sig')
    
    print(f"✅ 資料庫合併完成！總筆數: {len(df_combined)} 筆。等待 GitHub Actions 判斷是否推送。")
