import streamlit as st
import pandas as pd
import numpy as np
import os
import requests
from datetime import datetime, timezone, timedelta

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

# 💡 【時區校正】：強制將伺服器 UTC 時間轉換為台灣時間 (UTC+8)
def get_file_time_str(filepath):
    if os.path.exists(filepath):
        mtime = os.path.getmtime(filepath)
        tz_taiwan = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone(tz_taiwan)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return "尚未建立或找不到檔案"

# ==========================================
# 2. 資料讀取與預處理引擎 (含五大資料庫擴充)
# ==========================================
def get_file_mtime():
    return os.path.getmtime('tw_stock_data.csv') if os.path.exists('tw_stock_data.csv') else 0

@st.cache_data(ttl=3600)
def load_data(mtime):
    try:
        df = pd.read_csv('tw_stock_data.csv', dtype={'代號': str})
        if os.path.exists('industry_mapping.csv'):
            mapping_df = pd.read_csv('industry_mapping.csv', dtype={'代號': str})
            df = df.merge(mapping_df, on='代號', how='left')
        
        if df.empty:
            st.error("CSV 目前無資料，可能背景正在更新，請稍後重整。")
            return pd.DataFrame()
            
        df['日期'] = pd.to_datetime(df['日期'])
        
        # 🛡️ 確保所有數值欄位被正確解析為 Float 格式，防堵字串比對 Bug
        numeric_cols = ['收盤價', '開盤價', '最高價', '最低價', '漲跌幅', '成交量', '本益比', '主力淨買超', '外資買賣超', '投信買賣超', '自營商買賣超']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('--', ''), errors='coerce')
        
        if '成交量' in df.columns: df['成交量(張)'] = df['成交量'] / 1000
        if '主力淨買超' in df.columns: df['主力淨買超(張)'] = df['主力淨買超'] / 1000
        for col in ['外資買賣超', '投信買賣超', '自營商買賣超']:
            if col in df.columns: df[f'{col}(張)'] = df[col] / 1000
            
        df = df.sort_values(['代號', '日期'], ascending=[True, False]).reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"資料讀取失敗。錯誤: {e}")
        return pd.DataFrame()

# 💡 擴充加載其餘核心數據庫
@st.cache_data(ttl=3600)
def load_supplementary_files():
    index_df = pd.read_csv('tw_index_data.csv') if os.path.exists('tw_index_data.csv') else pd.DataFrame()
    info_df = pd.read_csv('tw_stock_info.csv', dtype={'代號': str}) if os.path.exists('tw_stock_info.csv') else pd.DataFrame()
    warning_df = pd.read_csv('tw_warning_data.csv', dtype={'代號': str}) if os.path.exists('tw_warning_data.csv') else pd.DataFrame()
    daytrade_df = pd.read_csv('tw_daytrade_data.csv', dtype={'代號': str}) if os.path.exists('tw_daytrade_data.csv') else pd.DataFrame()
    
    if not index_df.empty: index_df['日期'] = pd.to_datetime(index_df['日期'])
    if not warning_df.empty: warning_df['日期'] = pd.to_datetime(warning_df['日期'])
    if not daytrade_df.empty: daytrade_df['日期'] = pd.to_datetime(daytrade_df['日期'])
    
    return index_df, info_df, warning_df, daytrade_df

df = load_data(get_file_mtime())
index_df, info_df, warning_df, daytrade_df = load_supplementary_files()

if df.empty:
    st.stop()

# ==========================================
# 2.1 📅 時光機：決定系統當下觀測的「目標日期」
# ==========================================
st.sidebar.header("📊 條件篩選器")

st.sidebar.markdown("### 📅 資料日期設定")
use_specific_date = st.sidebar.checkbox("啟用指定日期回溯", help="若今日資料尚未齊全，可勾選此項回溯查看過去日期的篩選結果。")

# 取得所有可用日期，由新到舊排序
available_dates = sorted(df['日期'].dt.strftime('%Y-%m-%d').unique(), reverse=True)

if use_specific_date:
    selected_date_str = st.sidebar.selectbox("選擇指定日期", available_dates)
    target_date = pd.to_datetime(selected_date_str)
else:
    target_date = df['日期'].max()

latest_date_str = target_date.strftime('%Y/%m/%d')
latest_df = df[df['日期'] == target_date].copy()

st.sidebar.markdown("---")

# ==========================================
# 2.5 讀取並合併 EPS 財報數據
# ==========================================
def get_mops_mtime():
    return os.path.getmtime('mops_financial_history_8Q_ALL_DATA.csv') if os.path.exists('mops_financial_history_8Q_ALL_DATA.csv') else 0

@st.cache_data(ttl=3600)
def load_mops_data(mtime):
    try:
        m_df = pd.read_csv('mops_financial_history_8Q_ALL_DATA.csv', dtype={'公司代號': str})
        if not m_df.empty: m_df['年度'] = pd.to_numeric(m_df['年度'], errors='coerce')
        return m_df
    except: return pd.DataFrame()

mops_df = load_mops_data(get_mops_mtime())

if not mops_df.empty:
    mops_sorted = mops_df.sort_values(by=['年度', '季度'], ascending=[False, False])
    mops_latest = mops_sorted.drop_duplicates(subset=['公司代號'], keep='first').copy()
    mops_latest['最新EPS'] = mops_latest['EPS'].astype(str) + " (" + mops_latest['年度'].astype(str) + "_" + mops_latest['季度'] + ")"
    latest_df = latest_df.merge(mops_latest[['公司代號', '最新EPS']], left_on='代號', right_on='公司代號', how='left')
    latest_df.drop(columns=['公司代號'], inplace=True, errors='ignore')
    latest_df['最新EPS'] = latest_df['最新EPS'].fillna("-")
else:
    latest_df['最新EPS'] = "-"

# ==========================================
# 3. 欄位數據加工
# ==========================================
if '收盤價' in latest_df.columns and '漲跌幅' in latest_df.columns:
    latest_df['昨日收盤價'] = latest_df['收盤價'] - latest_df['漲跌幅']
    latest_df['昨日收盤價'] = latest_df['昨日收盤價'].replace(0, np.nan)
    latest_df['漲跌百分比'] = (latest_df['漲跌幅'] / latest_df['昨日收盤價']) * 100

    def format_change(row):
        diff, pct = row['漲跌幅'], row['漲跌百分比']
        if pd.isna(diff) or pd.isna(pct): return "-"
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.2f} ({sign}{pct:.2f}%)"

    latest_df['漲跌幅(%)'] = latest_df.apply(format_change, axis=1)

# ==========================================
# 4. 左側邊欄 (Sidebar) - 條件篩選器
# ==========================================
# 【區塊一】基礎與全域篩選區
use_cond_no_etf
