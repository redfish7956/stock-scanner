import streamlit as st
import pandas as pd
import numpy as np
import os
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

# 校正為台灣時間的檔案時間顯示
def get_file_time_str(filepath):
    if os.path.exists(filepath):
        mtime = os.path.getmtime(filepath)
        tz_taiwan = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(mtime, tz=tz_taiwan)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return "無資料"

# ==========================================
# 2. 資料讀取與預處理引擎
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
        if df.empty: return pd.DataFrame()
            
        df['日期'] = pd.to_datetime(df['日期'])
        
        if '成交量' in df.columns: df['成交量(張)'] = df['成交量'] / 1000
        if '主力淨買超' in df.columns: df['主力淨買超(張)'] = df['主力淨買超'] / 1000
        for col in ['外資買賣超', '投信買賣超', '自營商買賣超']:
            if col in df.columns: df[f'{col}(張)'] = df[col] / 1000
            
        return df.sort_values(['代號', '日期'], ascending=[True, False]).reset_index(drop=True)
    except: return pd.DataFrame()

df = load_data(get_file_mtime())
if df.empty: st.stop()

# ==========================================
# 2.1 指定日期設定 (時光機)
# ==========================================
st.sidebar.header("📊 條件篩選器")
st.sidebar.markdown(f"**最後更新：** {get_file_time_str('tw_stock_data.csv')}")
st.sidebar.markdown("### 📅 資料時間控制")
use_specific_date = st.sidebar.checkbox("啟用指定日期回溯")
available_dates = sorted(df['日期'].dt.strftime('%Y-%m-%d').unique(), reverse=True)
target_date = pd.to_datetime(st.sidebar.selectbox("選擇指定日期", available_dates)) if use_specific_date else df['日期'].max()

latest_date_str = target_date.strftime('%Y/%m/%d')
latest_df = df[df['日期'] == target_date].copy()

# ==========================================
# 2.5 財報資料加載
# ==========================================
def load_mops_data():
    try:
        m_df = pd.read_csv('mops_financial_history_8Q_ALL_DATA.csv', dtype={'公司代號': str})
        m_df['年度'] = pd.to_numeric(m_df['年度'], errors='coerce')
        return m_df
    except: return pd.DataFrame()

mops_df = load_mops_data()
if not mops_df.empty:
    mops_latest = mops_df.sort_values(by=['年度', '季度'], ascending=[False, False]).drop_duplicates(subset=['公司代號'], keep='first')
    mops_latest['最新EPS'] = mops_latest['EPS'].astype(str) + " (" + mops_latest['年度'].astype(str) + "_" + mops_latest['季度'] + ")"
    latest_df = latest_df.merge(mops_latest[['公司代號', '最新EPS']], left_on='代號', right_on='公司代號', how='left')
    latest_df['最新EPS'] = latest_df['最新EPS'].fillna("-")
else: latest_df['最新EPS'] = "-"

# ==========================================
# 3. 欄位數據加工
# ==========================================
latest_df['昨日收盤價'] = latest_df['收盤價'] - latest_df['漲跌幅']
latest_df['漲跌百分比'] = (latest_df['漲跌幅'] / latest_df['昨日收盤價'].replace(0, np.nan)) * 100
latest_df['漲跌幅(%)'] = latest_df.apply(lambda row: f"{'+' if row['漲跌幅']>0 else ''}{row['漲跌幅']:.2f} ({'+' if row['漲跌百分比']>0 else ''}{row['漲跌百分比']:.2f}%)" if pd.notna(row['漲跌幅']) else "-", axis=1)

# ==========================================
# 4. 側邊欄篩選條件
# ==========================================
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF", value=False)
use_cond_no_pref = st.sidebar.checkbox("🚫 排除特別股", value=False)
use_cond7 = st.sidebar.checkbox("🔍 搜尋特定股票")
cond7_keyword = st.sidebar.text_input("輸入關鍵字", disabled=not use_cond7, key='c7_kw')

st.sidebar.markdown("---")
cond1 = st.sidebar.checkbox("1. 連續 N 日成交量 >= M 張")
c1_d, c1_v = st.sidebar.columns(2)
c1_d = c1_d.number_input("連續日數", value=5, disabled=not cond1, key='c1_d')
c1_v = c1_v.number_input("張數", value=500, step=100, disabled=not cond1, key='c1_v')

cond2 = st.sidebar.checkbox("2. 成交量 > 前 N 日均量 M 倍")
c2_d, c2_m = st.sidebar.columns(2)
c2_d = c2_d.number_input("前 N 日", value=5, disabled=not cond2, key='c2_d')
c2_m = c2_m.number_input("倍數", value=2.0, step=0.5, disabled=not cond2, key='c2_m')

cond3 = st.sidebar.checkbox("3. 本益比 <= N 倍")
cond3_pe = st.sidebar.number_input("上限", value=15.0, disabled=not cond3, key='c3_pe')

cond4 = st.sidebar.checkbox("4. 收盤價創 N 日新高")
cond4_d = st.sidebar.number_input("日數", value=20, disabled=not cond4, key='c4_d')

cond5 = st.sidebar.checkbox("5. 連續 N 季 EPS >= M")
c5_q, c5_e = st.sidebar.columns(2)
c5_q = c5_q.number_input("季數", value=4, disabled=not cond5, key='c5_q')
c5_e = c5_e.number_input("EPS", value=1.0, disabled=not cond5, key='c5_e')

cond6 = st.sidebar.checkbox("6. 主力買超創 N 日新高")
cond6_d = st.sidebar.number_input("日數", value=5, disabled=not cond6, key='c6_d')

# ==========================================
# 5. 核心篩選引擎
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_cols = {}

if any([use_cond_no_etf, use_cond_no_pref, use_cond7, cond1, cond2, cond3, cond4, cond5, cond6]):
    if use_cond_no_etf: valid_stocks = valid_stocks.intersection(set(latest_df[~latest_df['代號'].str.match(r'^(00|01|02)')]['代號']))
    if use_cond_no_pref: valid_stocks = valid_stocks.intersection(set(latest_df[~latest_df['代號'].str.contains(r'[a-zA-Z]')]['代號']))
    if use_cond7 and cond7_keyword: valid_stocks = valid_stocks.intersection(set(latest_df[latest_df['代號'].str.contains(cond7_keyword) | latest_df['名稱'].str.contains(cond7_keyword)]['代號']))
    
    hist_df = df[df['日期'] <= target_date]
    
    if cond1:
        min_vols = hist_df.groupby('代號')['成交量(張)'].head(c1_d).groupby(df['代號']).min()
        valid_stocks = valid_stocks.intersection(set(min_vols[min_vols >= c1_v].index))
    if cond2:
        today_vol = hist_df.groupby('代號')['成交量(張)'].first()
        past_mean = hist_df.groupby('代號')['成交量(張)'].apply(lambda x: x.iloc[1:c2_d+1].mean())
        valid_stocks = valid_stocks.intersection(set(today_vol[today_vol > (past_mean * c2_m)].index))
        dynamic_cols['前N日均量倍數'] = (today_vol / past_mean).round(2)
    if cond3: valid_stocks = valid_stocks.intersection(set(latest_df[(latest_df['本益比'] <= cond3_pe) & (latest_df['本益比'] > 0)]['代號']))
    if cond4:
        today_close = hist_df.groupby('代號')['收盤價'].first()
        max_closes = hist_df.groupby('代號')['收盤價'].head(cond4_d).groupby(df['代號']).max()
        valid_stocks = valid_stocks.intersection(set(today_close[today_close >= max_closes].index))
    if cond6:
        today_inst = hist_df.groupby('代號')['主力淨買超(張)'].first()
        max_inst = hist_df.groupby('代號')['主力淨買超(張)'].head(cond6_d).groupby(df['代號']).max()
        valid_stocks = valid_stocks.intersection(set(today_inst[today_inst >= max_inst].index))

# ==========================================
# 6. 右側顯示儀表板與表格
# ==========================================
col_title, col_date = st.columns([3, 1])
with col_title: st.title("台股量化篩選系統")
with col_date: st.markdown(f"<h4 style='text-align: right; color: #666;'>觀測日：{latest_date_str}</h4>", unsafe_allow_html=True)

# 頂部儀表板
if '漲跌幅' in latest_df.columns:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🔥 上漲家數", f"{len(latest_df[latest_df['漲跌幅'] > 0])} 家")
    m2.metric("🧊 下跌家數", f"{len(latest_df[latest_df['漲跌幅'] < 0])} 家")
    
    # 大盤數據 (請檢查 CSV 是否有 '0000' 代號，或更改為你使用的大盤代號)
    market_idx = latest_df[latest_df['代號'] == '0000']
    if not market_idx.empty:
        m3.metric("大盤收盤", f"{market_idx['收盤價'].values[0]:,.0f}")
        m4.metric("大盤漲跌", f"{market_idx['漲跌幅'].values[0]:,.2f}")
    else:
        m3.metric("大盤收盤", "無資料")
        m4.metric("大盤漲跌", "-")

st.markdown("---")

result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
if cond2 and '前N日均量倍數' in dynamic_cols: result_df['前N日均量倍數'] = result_df['代號'].map(dynamic_cols['前N日均量倍數'])

final_cols = ['代號', '名稱', '開盤價', '最高價', '最低價', '收盤價', '漲跌幅(%)', '成交量(張)', '最新EPS', '本益比', '主力淨買超(張)', '外資買賣超(張)', '投信買賣超(張)', '自營商買賣超(張)']
if cond2: final_cols.insert(10, '前N日均量倍數')
final_display_df = result_df[[c for c in final_cols if c in result_df.columns]]

st.write(f"### 篩選結果：共 {len(final_display_df)} 檔符合條件")
st.dataframe(final_display_df, use_container_width=True, hide_index=True)
