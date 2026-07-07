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
        df = pd.read_csv('tw_stock_data.csv', dtype={'代號': str})
        
        if df.empty:
            st.error("CSV 目前無資料，可能背景正在更新，請稍後重整。")
            return pd.DataFrame()
            
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
        
    except pd.errors.EmptyDataError:
        st.error("CSV 為空 (0 KB)，GitHub 正在寫入資料，請稍後重整。")
        return pd.DataFrame()
    except FileNotFoundError:
        st.error("系統找不到 CSV 檔案，請確認 GitHub 是否存在。")
        return pd.DataFrame()
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

use_cond_no_etf = st.sidebar.checkbox(
    "🚫 排除 ETF (00開頭)", 
    value=False, 
    help="剔除代號為 00、01、02 開頭標的。"
)
use_cond_no_pref = st.sidebar.checkbox(
    "🚫 排除特別股 (含字母)", 
    value=False, 
    help="剔除代號含有英文字母的標的。"
)
st.sidebar.markdown("---")

use_cond1 = st.sidebar.checkbox(
    "1. 連續 N 日成交量 >= M 張", 
    help="過去 N 天（含今日）每天成交量 >= 設定張數。"
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
    "2. 成交量 > 前 N 日均量 M 倍", 
    help="今日成交量 > (前 N 日均量) * M 倍。不含今日。"
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
    help="今日最新本益比 <= N，且排除虧損公司。"
)
cond3_pe = st.sidebar.number_input(
    "本益比上限", min_value=0.0, value=15.0, 
    disabled=not use_cond3, key='c3_pe'
)

use_cond4 = st.sidebar.checkbox(
    "4. 收盤價創 N 日新高", 
    help="今日收盤價 >= 過去 N 天（含今日）的最高價。"
)
cond4_days = st.sidebar.number_input(
    "創高日數", min_value=2, value=20, 
    disabled=not use_cond4, key='c4_d'
)

use_cond5 = st.sidebar.checkbox(
    "5. 連續 N 季 EPS >= M (未啟用)", 
    help="建置中：待 EPS 爬蟲匯入後連動。"
)
col1, col2 = st.sidebar.columns(2)
cond5_q = col1.number_input(
    "連續季數", min_value=1, value=4, 
    disabled=not use_cond5, key='c5_q'
)
cond5_eps = col2.number_input(
    "最低 EPS", min_value=0.0, value=1.0, 
    disabled=not use_cond5, key='c5_e'
)

use_cond6 = st.sidebar.checkbox(
    "6. 主力買超創 N 日新高", 
    help="今日主力買超 >= 過去 N 天（含今日）最大值。"
)
cond6_days = st.sidebar.number_input(
    "創高日數", min_value=2, value=5, 
    disabled=not use_cond6, key='c6_d'
)

# ==========================================
# 5. 核心篩選引擎
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

# 將條件清單獨立出來，絕對不會因為太長被切斷
cond_list = [
    use_cond_no_etf, 
    use_cond_no_pref, 
    use_cond1, 
    use_cond2, 
    use_cond3, 
    use_cond4, 
    use_cond5, 
    use_cond6
]
has_active_conditions = any(cond_list)

if has_active_conditions:
    
    if use_cond_no_etf:
        mask = ~latest_df['代號'].str.match(r'^(00|01|02)')
        pass_stocks = latest_df[mask]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond_no_pref:
        mask = ~latest_df['代號'].str.contains(r'[a-zA-Z]', regex=True, na=False)
        pass_stocks = latest_df[mask]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond1:
        min_vols = df.groupby('代號')['成交量(張)'].head(cond1_days)
        min_vols = min_vols.groupby(df['代號']).min()
        pass_stocks = min_vols[min_vols >= cond1_vol].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond2:
        today_vol = df.groupby('代號')['成交量(張)'].first()
        
        def calc_mean(x):
            return x.iloc[1:cond2_days+1].mean()
            
        past_N_mean = df.groupby('代號')['成交量(張)'].apply(calc_mean)
        cond_met = today_vol > (past_N_mean * cond2_multi)
        pass_stocks = cond_met[cond_met].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))
        
        multiples = (today_vol / past_N_mean.replace(0, np.nan)).round(2)
        dynamic_columns['前N日均量倍數'] = multiples

    if use_cond3:
        mask = (latest_df['本益比'] <= cond3_pe) & (latest_df['本益比'] > 0)
        pass_stocks = latest_df[mask]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond4:
        today_close = df.groupby('代號')['收盤價'].first()
        max_closes = df.groupby('代號')['收盤價'].head(cond4_days)
        max_closes = max_closes.groupby(df['代號']).max()
        
        pass_stocks = today_close[today_close >= max_closes].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond5:
        st.sidebar.info("EPS 篩選模組建置中。")

    if use_cond6:
        today_inst = df.groupby('代號')['主力淨買超(張)'].first()
        max_inst = df.groupby('代號')['主力淨買超(張)'].head(cond6_days)
        max_inst = max_inst.groupby(df['代號']).max()
        
        pass_stocks = today_inst[today_inst >= max_inst].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

# ==========================================
# 6. 右側主畫面 (Main Area)
# ==========================================
col_title, col_date = st.columns([3, 1])
with col_title:
    st.title("台股量化篩選系統")
with col_date:
    st.markdown(
        f"<h4 style='text-align: right; color: #666;'>更新日：{latest_date_str}</h4>", 
        unsafe_allow_html=True
    )

st.markdown("---")

if not has_active_conditions:
    st.info("👈 請於左側面板勾選篩選條件以顯示股票數據。")
else:
    result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
    
    if use_cond2 and '前N日均量倍數' in dynamic_columns:
        result_df['前N日均量倍數'] = result_df['代號'].map(dynamic_columns['前N日均量倍數'])

    base_columns = [
        '代號', '名稱', '市場別', '收盤價', 
        '漲跌幅(%)', '成交量(張)', '本益比', '主力淨買超(張)'
    ]
    
    if use_cond2:
        base_columns.insert(6, '前N日均量倍數') 
        
    final_display_df = result_df[base_columns]

    st.write(f"### 篩選結果：共 {len(final_display_df)} 檔符合條件")
    
    if not final_display_df.empty:
        format_dict = {
            '收盤價': '{:,.2f}',
            '成交量(張)': '{:,.0f}',
            '主力淨買超(張)': '{:,.0f}',
            '本益比': '{:,.2f}',
            '前N日均量倍數': '{:,.2f}'
        }
        
        active_format_dict = {
            k: v for k, v in format_dict.items() 
            if k in final_display_df.columns
        }
        
        cols_to_color = []
        if use_
