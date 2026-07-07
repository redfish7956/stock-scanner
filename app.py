import streamlit as st
import pandas as pd
import numpy as np
import os

# ==========================================
# 1. 頁面與基本設定
# ==========================================
st.set_page_config(page_title="台股量化篩選系統", layout="wide")

# 隱藏 Streamlit 預設的右上角選單與浮水印，保持介面專業俐落
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
        
        # 🚀 單位轉換：在源頭將「股」除以 1000 轉換為「張」，並重新命名欄位
        if '成交量' in df.columns:
            df['成交量(張)'] = df['成交量'] / 1000
        if '主力淨買超' in df.columns:
            df['主力淨買超(張)'] = df['主力淨買超'] / 1000
            
        # 確保資料依據 代號 與 日期(新到舊) 排序，有利於 N 日計算
        df = df.sort_values(['代號', '日期'], ascending=[True, False]).reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"資料讀取失敗，請確認 CSV 檔案路徑與狀態。錯誤: {e}")
        return pd.DataFrame()

df = load_data()

if df.empty:
    st.stop()

# 取得最新交易日
latest_date = df['日期'].max()
latest_date_str = latest_date.strftime('%Y/%m/%d')

# 建立最新一日的資料表，做為最終顯示的基底
latest_df = df[df['日期'] == latest_date].copy()

# ==========================================
# 3. 欄位數據加工 (漲跌幅百分比計算)
# ==========================================
# 爬蟲存的「漲跌幅」實際上是「漲跌價差」(數值)。昨日收盤價 = 今日收盤價 - 漲跌價差
latest_df['昨日收盤價'] = latest_df['收盤價'] - latest_df['漲跌幅']
# 避免除以零的錯誤
latest_df['昨日收盤價'] = latest_df['昨日收盤價'].replace(0, np.nan)
latest_df['漲跌百分比'] = (latest_df['漲跌幅'] / latest_df['昨日收盤價']) * 100

# 格式化顯示字串，例如 "+60 (+4.56%)" 或 "-40 (-2.56%)"
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

# 🚀 新增：排除 ETF 條件
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF (00開頭)", value=False, help="邏輯：剔除代號為 00、01、02 開頭的 ETF 與基金標的。")
st.sidebar.markdown("---")

# 條件 1: 連續 N 日成交量 >= M 張 (🚀 加入 disabled 鎖定外觀)
use_cond1 = st.sidebar.checkbox("1. 連續 N 日成交量 >= M 張", help="邏輯：由最新交易日往前推算 N 日，每一天的成交量皆大於或等於設定的張數。")
col1, col2 = st.sidebar.columns(2)
cond1_days = col1.number_input("連續日數 (N)", min_value=1, value=5, step=1, disabled=not use_cond1, key='c1_d')
cond1_vol = col2.number_input("最低張數 (M)", min_value=0, value=500, step=100, disabled=not use_cond1, key='c1_v')

# 條件 2: 成交量 > 前 N 日均量的 M 倍
use_cond2 = st.sidebar.checkbox("2. 成交量 > 前 N 日均量的 M 倍", help="邏輯：今日成交量 > (前 N 日的總成交量 / N) * M 倍。注意：前 N 日不包含今日。")
col1, col2 = st.sidebar.columns(2)
cond2_days = col1.number_input("前 N 日均量", min_value=1, value=5, step=1, disabled=not use_cond2, key='c2_d')
cond2_multi = col2.number_input("突破倍數 (M)", min_value=1.0, value=2.0, step=0.5, disabled=not use_cond2, key='c2_m')

# 條件 3: 本益比 <= N 倍
use_cond3 = st.sidebar.checkbox("3. 本益比 <= N 倍", help="邏輯：今日最新本益比小於或等於 N 倍，且排除本益比為負數（虧損）的公司。")
cond3_pe = st.sidebar.number_input("本益比上限 (N)", min_value=0.0, value=15.0, step=1.0, disabled=not use_cond3, key='c3_pe')

# 條件 4: 收盤價創 N 日新高
use_cond4 = st.sidebar.checkbox("4. 收盤價創 N 日新高", help="邏輯：今日收盤價為包含今日在內，過去 N 個交易日中的最高價。")
cond4_days = st.sidebar.number_input("創高日數 (N)", min_value=2, value=20, step=1, disabled=not use_cond4, key='c4_d')

# 條件 5: 連續 N 季單季 EPS >= M 元 (佔位符)
use_cond5 = st.sidebar.checkbox("5. 連續 N 季單季 EPS >= M 元 (未啟用)", help="邏輯：未來擴充項目。待 EPS 爬蟲建立並匯入新 CSV 後將啟用連動。")
col1, col2 = st.sidebar.columns(2)
cond5_q = col1.number_input("連續季數 (N)", min_value=1, value=4, step=1, disabled=not use_cond5, key='c5_q')
cond5_eps = col2.number_input("最低 EPS (M)", min_value=0.0, value=1.0, step=0.1, disabled=not use_cond5, key='c5_e')

# 條件 6: 主力買超張數創 N 日新高
use_cond6 = st.sidebar.checkbox("6. 主力買超創 N 日新高", help="邏輯：今日三大法人買賣超總和(張)，為包含今日在內，過去 N 個交易日中的最高數值。")
cond6_days = st.sidebar.number_input("創高日數 (N)", min_value=2, value=5, step=1, disabled=not use_cond6, key='c6_d')


# ==========================================
# 5. 核心篩選引擎 (向量化運算)
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

# 將「排除 ETF」也納入是否啟動篩選的判斷中
has_active_conditions = any([use_cond_no_etf, use_cond1, use_cond2, use_cond3, use_cond4, use_cond5, use_cond6])

if has_active_conditions:
    
    # 🚀 執行排除 ETF
    if use_cond_no_etf:
        pass_stocks = latest_df[~latest_df['代號'].str.match(r'^(00|01|02)')]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond1:
        # 🚀 運算基底改為「成交量(張)」
        min_vol_N_days = df.groupby('代號')['成交量(張)'].head(cond1_days).groupby(df['代號']).min()
        pass_stocks = min_vol_N_days[min_vol_N_days >= cond1_vol].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond2:
        # 🚀 運算基底改為「成交量(張)」
        today_vol = df.groupby('代號')['成交量(張)'].nth(0)
        past_N_mean = df.groupby('代號')['成交量(張)'].apply(lambda x: x.iloc[1:cond2_days+1].mean())
        
        cond_met = today_vol > (past_N_mean * cond2_multi)
        pass_stocks = cond_met[cond_met].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))
        
        multiples = (today_vol / past_N_mean.replace(0, np.nan)).round(2)
        dynamic_columns['前N日均量倍數'] = multiples

    if use_cond3:
        pass_stocks = latest_df[(latest_df['本益比'] <= cond3_pe) & (latest_df['本益比'] > 0)]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond4:
        today_close = df.groupby('代號')['收盤價'].nth(0)
        max_N_close = df.groupby('代號')['收盤價'].head(cond4_days).groupby(df['代號']).max()
        pass_stocks = today_close[today_close >= max_N_close].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond5:
        st.sidebar.info("EPS 篩選模組建置中，本條件目前不影響篩選結果。")

    if use_cond6:
        # 🚀 運算基底改為「主力淨買超(張)」
        today_inst = df.groupby('代號')['主力淨買超(張)'].nth(0)
        max_N_inst = df.groupby('代號')['主力淨買超(張)'].head(cond6_days).groupby(df['代號']).max()
        pass_stocks = today_inst[today_inst >= max_N_inst].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

# ==========================================
# 6. 右側主畫面 (Main Area)
# ==========================================
col_title, col_date = st.columns([3, 1])
with col_title:
    st.title("台股量化篩選系統")
with col_date:
    st.markdown(f"<h4 style='text-align: right; color: #666;'>資料更新日期：{latest_date_str}</h4>", unsafe_allow_html=True)

st.markdown("---")

if not has_active_conditions:
    st.info("👈 請於左側面板勾選篩選條件以顯示股票數據。")
else:
    result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
    
    if use_cond2 and '前N日均量倍數' in dynamic_columns:
        result_df = result_df.merge(dynamic_columns['前N日均量倍數'], on='代號', how='left')

    # 🚀 欄位名稱更新為帶有「(張)」的名稱
    base_columns = ['代號', '名稱', '市場別', '收盤價', '漲跌幅(%)', '成交量(張)', '本益比', '主力淨買超(張)']
    if use_cond2:
        base_columns.insert(6, '前N日均量倍數') 
        
    final_display_df = result_df[base_columns]

    st.write(f"### 篩選結果：共 {len(final_display_df)} 檔符合條件")
    
    if not final_display_df.empty:
        # 🚀 新增：千分位數值格式化設定
        format_dict = {
            '收盤價': '{:,.2f}',
            '成交量(張)': '{:,.0f}',
            '主力淨買超(張)': '{:,.0f}',
            '本益比': '{:,.2f}',
            '前N日均量倍數': '{:,.2f}'
        }
        active_format_dict = {k: v for k, v in format_dict.items() if k in final_display_df.columns}
        
        # 使用 Pandas Styler 進行千分位渲染
        styled_df = final_display_df.style.format(active_format_dict, na_rep="-")
        
        # 顯示格式化後的表格
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        csv_data = final_display_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(
            label="📥 下載篩選結果 (CSV)",
            data=csv_data,
            file_name=f"stock_screen_{latest_date_str.replace('/','')}.csv",
            mime='text/csv'
        )
    else:
        st.warning("無符合上述所有條件之股票。")
