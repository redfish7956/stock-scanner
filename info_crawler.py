import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
from datetime import datetime # ⏳ 新增時間模組

print("【系統啟動】台股基本資料爬蟲 (Info Crawler v1.4 - 時間戳記版)...")

INFO_CSV_PATH = 'tw_stock_info.csv'
headers = {'User-Agent': 'Mozilla/5.0'}

# 🛡️ 建立強固的網路連線 Session
session = requests.Session()
retry_strategy = Retry(total=3, status_forcelist=[429, 500, 502, 503, 504], backoff_factor=2)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

# 💡 台股產業別翻譯字典
INDUSTRY_MAP = {
    '01': '水泥工業', '02': '食品工業', '03': '塑膠工業', '04': '紡織纖維',
    '05': '電機機械', '06': '電器電纜', '07': '化學工業', '08': '玻璃陶瓷',
    '09': '造紙工業', '10': '鋼鐵工業', '11': '橡膠工業', '12': '汽車工業',
    '14': '建材營造', '15': '航運業', '16': '觀光餐旅', '17': '金融保險',
    '18': '貿易百貨', '19': '綜合', '20': '其他', '21': '化學工業',
    '22': '生技醫療業', '23': '油電燃氣業', '24': '半導體業', '25': '電腦及週邊',
    '26': '光電業', '27': '通信網路業', '28': '電子零組件', '29': '電子通路業',
    '30': '資訊服務業', '31': '其他電子業', '32': '文化創意業', '33': '農業科技業',
    '34': '電子商務業', '35': '綠能環保', '36': '數位雲端', '37': '運動休閒',
    '38': '居家生活'
}

def process_api_data(url, market_name):
    print(f"⏳ 正在抓取{market_name}公司基本資料...")
    MAX_RETRIES = 3
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = session.get(url, headers=headers, timeout=20)
            res.raise_for_status()
            df = pd.DataFrame(res.json())
            
            # 💡 精準對位：依照 X 光機顯示的實際欄位填寫
            col_mapping = {
                '公司代號': '代號', 'SecuritiesCompanyCode': '代號',
                '公司名稱': '名稱', 'CompanyName': '名稱',
                '產業別': '產業別', 'SecuritiesIndustryCode': '產業別',
                '實收資本額': '實收資本額', 'Paidin.Capital.NTDollars': '實收資本額',
                '已發行普通股數或TDR原股發行股數': '發行股數', 'IssueShares': '發行股數'
            }
            
            df = df.rename(columns=col_mapping)
            
            # 嚴格選取需要的 5 個核心欄位
            target_cols = ['代號', '名稱', '產業別', '實收資本額', '發行股數']
            existing_cols = [c for c in target_cols if c in df.columns]
            df = df[existing_cols]
            
            # 💡 翻譯產業別代碼
            if '產業別' in df.columns:
                df['產業別'] = df['產業別'].map(INDUSTRY_MAP).fillna(df['產業別'])
                
            df['市場別'] = market_name
            print(f"  ✅ {market_name}抓取成功: 共 {len(df)} 筆")
            return df
            
        except Exception as e:
            print(f"  ⚠️ 第 {attempt} 次嘗試失敗 ({type(e).__name__})，等待重試...")
            time.sleep(3)
            
    print(f"  ❌ {market_name}已達最大重試次數，抓取放棄。")
    return pd.DataFrame()

# ==========================================
# 1. 執行雙市場抓取
# ==========================================
df_twse = process_api_data("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "上市")
time.sleep(2)
df_tpex = process_api_data("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "上櫃")

# ==========================================
# 2. 合併與資料清洗
# ==========================================
if not df_twse.empty or not df_tpex.empty:
    df_all = pd.concat([df_twse, df_tpex], ignore_index=True)
    
    df_all['代號'] = df_all['代號'].astype(str).str.strip()
    
    for col in ['實收資本額', '發行股數']:
        if col in df_all.columns:
            df_all[col] = pd.to_numeric(df_all[col].astype(str).str.replace(',', ''), errors='coerce')
    
    # 排除權證與特殊雜訊
    cond_stock = df_all['代號'].str.len() <= 5
    cond_fund = df_all['代號'].str.match(r'^(00|01|02)')
    df_all = df_all[cond_stock | cond_fund].copy()

    # ⏳ 新增更新日期
    today_str = datetime.now().strftime("%Y-%m-%d")
    df_all['更新日期'] = today_str

    # 📏 黃金比例排版 (自訂欄位順序)
    final_cols = ['代號', '更新日期', '名稱', '市場別', '產業別', '實收資本額', '發行股數']
    # 確保只取 df 裡確實有的欄位，避免報錯
    final_cols = [c for c in final_cols if c in df_all.columns]
    df_all = df_all[final_cols]

    # 排序並輸出
    df_all = df_all.sort_values(by=['代號'])
    df_all.to_csv(INFO_CSV_PATH, index=False, encoding='utf-8-sig')
    
    print(f"\n🎉 執行完成！基本資料已儲存至: {INFO_CSV_PATH}")
    print(f"總共收錄了 {len(df_all)} 檔標的之身分證資料。")
else:
    print("\n❌ 抓取失敗，無任何資料被合併。")
