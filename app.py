import streamlit as st
import pandas as pd
import numpy as np
import os

# ==========================================
# 1. 頁面與基本設定
# ==========================================
st.set_page_config(page_title="台股量化篩選系統", layout="wide")

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# ==========================================
# 2. 資料讀取與預處理引擎 (快取機制)
# ==========================================
@st.cache_data(ttl=3600)
def load_data():
    try:
        if not os.path.exists('tw_stock_data.csv') or os.path.getsize('tw_stock_data.csv') == 0:
            st.error("CSV 檔案目前為空或不存在，可能是背景正在更新資料，請稍後重新整理。")
            return pd.DataFrame()
            
        df = pd.read_csv('tw_stock_data.csv', dtype={'代號': str})
        df['日期'] = pd.to_datetime(df['日期'])
        
        if '成交量' in df.columns:
            df['成交量(張)'] = df['成交量'] / 1000
        if '主力淨買超' in df.columns:
            df['主力淨買超(張)'] = df['主力淨買超'] / 1000
            
        df = df.sort_values(['代號', '日期'], ascending=[True, False]).reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"資料讀取失敗，請確認 CSV 檔案路徑與狀態。錯誤: {e}")
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.stop()

latest_date = df['日期'].max()
latest_date_str = latest_date.strftime('%Y/%m/%d')
latest_df = df[df['日期'] == latest_date].copy()

# ==========================================
# 3. 欄位數據加工 (漲跌幅百分比計算)
# ==========================================
latest_df['昨日收盤價'] = latest_df['收盤價'] - latest_df['漲跌幅']
latest_df['昨日收盤價'] = latest_df['昨日收盤價'].replace(0, np.nan)
latest_df['漲跌百分比'] = (latest_df['漲跌幅'] / latest_df['昨日收盤價']) * 100

def format_change(row):
    diff = row['漲跌幅']
    pct = row['漲跌百分比']
    if pd.isna(diff) or pd.isna(pct):
        return "-"
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.2f} ({sign}{pct:.2f}%)"

latest_df['漲跌幅(%)'] = latest_df.apply(format_change, axis=1)

# ==========================================
# 4. 左側邊欄 (Sidebar) - 條件篩選器
# ==========================================
st.sidebar.header("📊 條件篩選器")

# --- 基礎濾網 ---
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF (00開頭)", value=False, help="邏輯：剔除代號為 00、01、02 開頭的 ETF 與基金標的。")
use_cond_no_pref = st.sidebar.checkbox("🚫 排除特別股 (含字母)", value=False, help="邏輯：剔除代號中含有英文字母的特別股或憑證 (如 2881A)。")
st.sidebar.markdown("---")

# --- 進階條件 ---
use_cond1 = st.sidebar.checkbox("1. 連續 N 日成交量 >= M 張", help="邏輯：由最新交易日往前推算 N 日（包含今日），這 N 天的「每日」成交量皆大於或等於設定張數。")
col1, col2 = st.sidebar.columns(2)
cond1_days = col1.number_input("連續日數 (N)", min_value=1, value=5, step=1, disabled=not use_cond1, key='c1_d')
cond1_vol = col2.number_input("最低張數 (M)", min_value=0, value=500, step=100, disabled=not use_cond1, key='c1_v')

use_cond2 = st.sidebar.checkbox("2. 成交量 > 前 N 日均量的 M 倍", help="邏輯：今日成交量 > (前 N 日總成交量 / N) * M 倍。注意：均量計算「不包含」今日，以避免今日爆量拉高均值。")
col1, col2 = st.sidebar.columns(2)
cond2_days = col1.number_input("前 N 日均量", min_value=1, value=5, step=1, disabled=not use_cond2, key='c2_d')
cond2_multi = col2.number_input("突破倍數 (M)", min_value=1.0, value=2.0, step=0.5, disabled=not use_cond2, key='c2_m')

use_cond3 = st.sidebar.checkbox("3. 本益比 <= N 倍", help="邏輯：今日最新本益比 <= N 倍，且強制排除本益比為負數或 0（虧損）的公司。")
cond3_pe = st.sidebar.number_input("本益比上限 (N)", min_value=0.0, value=15.0, step=1.0, disabled=not use_cond3, key='c3_pe')

use_cond4 = st.sidebar.checkbox("4. 收盤價創 N 日新高", help="邏輯：今日收盤價 >= 過去 N 個交易日（包含今日）的最高價。即使今日平盤但仍是區間最高，亦符合條件。")
cond4_days = st.sidebar.number_input("創高日數 (N)", min_value=2, value=20, step=1, disabled=not use_cond4, key='c4_d')

use_cond5 = st.sidebar.checkbox("5. 連續 N 季單季 EPS >= M 元 (未啟用)", help="邏輯：未來擴充項目。待 EPS 爬蟲建立並匯入新 CSV 後將啟用連動。")
col1, col2 = st.sidebar.columns(2)
cond5_q = col1.number_input("連續季數 (N)", min_value=1, value=4, step=1, disabled=not
