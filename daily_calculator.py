import pandas as pd
import os
from datetime import datetime
import re

# ==========================================
# 1. 設定檔案路徑與常數 (請依據您的爬蟲產出檔名修改)
# ==========================================
WARNING_CSV = 'tw_warning_data.csv'  # 注意股公告原始檔
PRICE_CSV = 'tw_stock_data.csv'      # 每日價量與基本面原始檔
MASTER_CSV = 'tw_disposal_master.csv'# 我們要產出的歷史日誌主檔

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

# ==========================================
# 2. 核心邏輯 A：中文翻譯機 (解析違規款項)
# ==========================================
def parse_warning_rule(reason_text):
    """
    將證交所的長篇中文理由，轉換為法規款項。
    """
    if pd.isna(reason_text):
        return ""
    
    rules = []
    text = str(reason_text)
    
    # 第 1 款：漲跌幅異常
    if "累積收盤價" in text and ("漲幅" in text or "跌幅" in text):
        rules.append("1")
    # 第 4 款：週轉率異常
    if "週轉率" in text:
        rules.append("4")
    # 第 6 款：本益比及股價淨值比異常
    if "本益比" in text or "股價淨值比" in text:
        rules.append("6")
    # 其他款項可依此類推繼續往下加...
    
    return ",".join(rules)

# ==========================================
# 3. 核心邏輯 B：法規煞車皮 (豁免除外條款)
# ==========================================
def check_exemption(row):
    """
    攔截像 3163 這類急拉飆股的假警報。
    如果符合豁免條件，回傳 True 與 豁免原因。
    """
    # 檢查 1：收盤價未滿 5 元不罰 (以第1款、第4款等常見規定為例)
    if pd.notna(row.get('收盤價')) and row['收盤價'] < 5.0:
        return True, "收盤價未滿 5 元"
    
    # 檢查 2：本益比檢核 (假設本益比為負，或在安全區間內豁免)
    # 注意：需確保有抓到本益比資料，否則跳過此檢查
    if pd.notna(row.get('本益比')):
        if row['本益比'] < 0:
             return True, "本益比為負"
             
    # 若都不符合豁免條件，則乖乖受罰
    return False, ""

# ==========================================
# 4. 主程式執行流
# ==========================================
def main():
    print(f"[{TODAY_STR}] 開始執行台股處置狀態結算作業...")

    # --- 步驟一：讀取今日原始資料 ---
    try:
        df_warning = pd.read_csv(WARNING_CSV)
        df_price = pd.read_csv(PRICE_CSV)
    except FileNotFoundError as e:
        print(f"錯誤：找不到原始資料檔 - {e}")
        return

    # --- 步驟二：資料合併 (Join) ---
    # 假設兩張表都有 '代號' 這個欄位
    df_today = pd.merge(df_warning, df_price, on='代號', how='left')
    
    # 建立今天要寫入 CSV 的空 DataFrame，確保欄位規格一致
    records = []

    for index, row in df_today.iterrows():
        # 1. 執行翻譯機
        trigger_rules = parse_warning_rule(row.get('公告原因', ''))
        
        # 2. 執行煞車皮
        is_exempt, exempt_reason = check_exemption(row)
        
        # 3. 動態計算當日週轉率 (確保我們有底層數據可以稽核)
        # 假設有 '成交量' 與 '發行股數' 欄位
        turnover_rate = None
        if pd.notna(row.get('成交量')) and pd.notna(row.get('發行股數')) and row['發行股數'] > 0:
            turnover_rate = round((row['成交量'] / row['發行股數']) * 100, 2)

        # 整理成標準格式的 Row
        record = {
            '日期': TODAY_STR,
            '代號': row['代號'],
            '名稱': row.get('名稱', ''),
            '當日收盤價': row.get('收盤價', None),
            '當日本益比': row.get('本益比', None),
            '當日週轉率': turnover_rate,
            '注意狀態_當日是否列入': True if trigger_rules else False,
            '注意狀態_觸發款項': trigger_rules,
            '注意狀態_除外豁免': is_exempt,
            '注意狀態_豁免原因': exempt_reason,
            # 這裡先預留狀態機欄位，下一步我們再把「天數累加」跟「處置區間」邏輯補上
            '計數器_近10日注意次數': 1 if not is_exempt else 0, 
            '處置狀態_是否處置中': False, 
            '處置狀態_剩餘天數': 0
        }
        records.append(record)

    df_result = pd.DataFrame(records)

    # --- 步驟三：寫入歷史日誌 (Master CSV) ---
    if os.path.exists(MASTER_CSV):
        # 檔案存在，使用 append 模式加在最下面 (不寫入表頭)
        df_result.to_csv(MASTER_CSV, mode='a', header=False, index=False, encoding='utf-8-sig')
        print(f"成功將 {len(df_result)} 筆紀錄新增至 {MASTER_CSV}")
    else:
        # 檔案不存在，建立新檔案 (寫入表頭)
        df_result.to_csv(MASTER_CSV, mode='w', header=True, index=False, encoding='utf-8-sig')
        print(f"建立全新預測主檔 {MASTER_CSV}，並寫入 {len(df_result)} 筆紀錄")

if __name__ == "__main__":
    main()
