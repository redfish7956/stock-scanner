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
# 2. 資料讀取與預處理引擎
# ==========================================
@st.cache_data(ttl=3600)
def load_data():
    try:
        if not os.path.exists('tw_stock_data.csv') or os.path.getsize('tw_stock_data.csv') == 0:
            st.error("CSV 檔案目前為空，可能是背景正在更新資料，請稍後重新整理。")
            return pd.DataFrame()
            
        df = pd.read_csv('tw_stock_data.csv', dtype={'代號': str})
        df['日期'] = pd.to_datetime(df['日期'])
        
        if '成交量' in df.columns:
            df['成交量(張)'] = df['成交量'] / 1000
        if '主力淨買超' in df.columns:
            df['主力淨買超(張)'] = df['主力淨買超'] / 1000
            
        df = df.sort_values(
            ['代號', '日期'], 
            ascending=[True, False]
        ).reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"資料讀取失敗。錯誤: {e}")
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.stop()

latest_date = df['日期'].max()
latest_date_str = latest_date.strftime('%Y/%m/%d')
latest_df = df[df['日期'] == latest_date].copy()

# ==========================================
# 3. 欄位數據加工
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
use_cond_no_etf = st.sidebar.checkbox(
    "🚫 排除 ETF (00開頭)", 
    value=False, 
    help="邏輯：剔除代號為 00、01、02 開頭的 ETF 與基金標的。"
)
use_cond_no_pref = st.sidebar.checkbox(
    "🚫 排除特別股 (含字母)", 
    value=False, 
    help="邏輯：剔除代號中含有英文字母的特別股或憑證。"
)
st.sidebar.markdown("---")

# --- 進階條件 ---
use_cond1 = st.sidebar.checkbox(
    "1. 連續 N 日成交量 >= M 張", 
    help="邏輯：過去 N 天（含今日）每天成交量 >= 設定張數。"
)
col1, col2 = st.sidebar.columns(2)
cond1_days = col1.number_input(
    "連續日數", min_value=1, value=5, 
    disabled=not use_cond1, key='c1_d'
)
cond1_vol = col2.number_input(
    "最低張數", min_value=0, value=500, step=100, 
    disabled=not use_cond1, key='c1_v'
)

use_cond2 = st.sidebar.checkbox(
    "2. 成交量 > 前 N 日均量的 M 倍", 
    help="邏輯：今日成交量 > (前 N 日均量) * M 倍。不含今日。"
)
col1, col2 = st.sidebar.columns(2)
cond2_days = col1.number_input(
    "前 N 日", min_value=1, value=5, 
    disabled=not use_cond2, key='c2_d'
)
cond2_multi = col2.number_input(
    "突破倍數", min_value=1.0, value=2.0, step=0.5, 
    disabled=not use_cond2, key='c2_m'
)

use_cond3 = st.sidebar.checkbox(
    "3. 本益比 <= N 倍", 
    help="邏輯：今日最新本益比 <= N，且排除虧損公司。"
)
cond3_pe = st.sidebar.number_input(
    "本益比上限", min_value=0.0, value=15
