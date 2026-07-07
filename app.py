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
            
        df = df.sort_values(['代號', '日期'], ascending=[True, False]).reset_index(drop=True)
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
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF (00開頭)", value=False, help="邏輯：剔除代號為 00、01、02 開頭的 ETF 與基金標的。")
use_cond_no_pref = st.sidebar.checkbox("🚫 排除特別股 (含字母)", value=False, help="邏輯：剔除代號中含有英文字母的特別股或憑證。")
st.sidebar.markdown("---")

# --- 進階條件 ---
use_cond1 = st.sidebar.checkbox("1. 連續 N 日成交量 >= M 張", help="邏輯：過去 N 天（含今日）每天成交量 >= 設定張數。")
col1, col2 = st.sidebar.columns(2)
cond1_days = col1.number_input("連續日數", min_value=1, value=5, disabled=not use_cond1, key='c1_d')
cond1_vol = col2.number_input("最低張數", min_value=0, value=500, step=100, disabled=not use_cond1, key='c1_v')

use_cond2 = st.sidebar.checkbox("2. 成交量 > 前 N 日均量的 M 倍", help="邏輯：今日成交量 > (前 N 日均量) * M 倍。不含今日。")
col1, col2 = st.sidebar.columns(2)
cond2_days = col1.number_input("前 N 日", min_value=1, value=5, disabled=not use_cond2, key='c2_d')
cond2_multi = col2.number_input("突破倍數", min_value=1.0, value=2.0, step=0.5, disabled=not use_cond2, key='c2_m')

use_cond3 = st.sidebar.checkbox("3. 本益比 <= N 倍", help="邏輯：今日最新本益比 <= N，且排除虧損公司。")
cond3_pe = st.sidebar.number_input("本益比上限", min_value=0.0, value=15.0, disabled=not use_cond3, key='c3_pe')

use_cond4 = st.sidebar.checkbox("4. 收盤價創 N 日新高", help="邏輯：今日收盤價 >= 過去 N 天（含今日）的最高價。")
cond4_days = st.sidebar.number_input("創高日數", min_value=2, value=20, disabled=not use_cond4, key='c4_d')

use_cond5 = st.sidebar.checkbox("5. 連續 N 季單季 EPS >= M (未啟用)", help="建置中：待 EPS 爬蟲匯入後連動。")
col1, col2 = st.sidebar.columns(2)
cond5_q = col1.number_input("連續季數", min_value=1, value=4, disabled=not use_cond5, key='c5_q')
cond5_eps = col2.number_input("最低 EPS", min_value=0.0, value=1.0, disabled=not use_cond5, key='c5_e')

use_cond6 = st.sidebar.checkbox("6. 主力買超創 N 日新高", help="邏輯：今日主力買超 >= 過去 N 天（含今日）最大值。")
cond6_days = st.sidebar.number_input("創高日數", min_value=2, value=5, disabled=not use_cond6, key='c6_d')

# ==========================================
# 5. 核心篩選引擎
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

has_active_conditions = any([use_cond_no_etf, use_cond_no_pref, use_cond1, use_cond2, use_cond3, use_cond4, use_cond5, use_cond6])

if has_active_conditions:
    
    if use_cond_no_etf:
        pass_stocks = latest_df[~latest_df['代號'].str.match(r'^(00|01|02)')]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond_no_pref:
        pass_stocks = latest_df[~latest_df['代號'].str.contains(r'[a-zA-Z]', regex=True, na=False)]['代號']
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond1:
        min_vol_N_days = df.groupby('代號')['成交量(張)'].head(cond1_days).groupby(df['代號']).min()
        pass_stocks = min_vol_N_days[min_vol_N_days >= cond1_vol].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond2:
        today_vol = df.groupby('代號')['成交量(張)'].first()
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
        today_close = df.groupby('代號')['收盤價'].first()
        max_N_close = df.groupby('代號')['收盤價'].head(cond4_days).groupby(df['代號']).max()
        pass_stocks = today_close[today_close >= max_N_close].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    if use_cond5:
        st.sidebar.info("EPS 篩選模組建置中。")

    if use_cond6:
        today_inst = df.groupby('代號')['主力淨買超(張)'].first()
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
    st.markdown(f"<h4 style='text-align: right; color: #666;'>更新日：{latest_date_str}</h4>", unsafe_allow_html=True)

st.markdown("---")

if not has_active_conditions:
    st.info("👈 請於左側面板勾選篩選條件以顯示股票數據。")
else:
    result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
    
    if use_cond2 and '前N日均量倍數' in dynamic_columns:
        result_df['前N日均量倍數'] = result_df['代號'].map(dynamic_columns['前N日均量倍數'])

    base_columns = ['代號', '名稱', '市場別', '收盤價', '漲跌幅(%)', '成交量(張)', '本益比', '主力淨買超(張)']
    
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
        active_format_dict = {k: v for k, v in format_dict.items() if k in final_display_df.columns}
        
        cols_to_color = []
        if use_cond1 or use_cond2: cols_to_color.append('成交量(張)')
        if use_cond2: cols_to_color.append('前N日均量倍數')
        if use_cond4: cols_to_color.append('收盤價')
        if use_cond6: cols_to_color.append('主力淨買超(張)')
        
        def color_blue(val):
            return 'color: #2196F3; font-weight: bold;'
            
        styled_df = final_display_df.style.format(active_format_dict, na_rep="-")
        if cols_to_color:
            styled_df = styled_df.map(color_blue, subset=cols_to_color)

        st.markdown("<p style='font-size: 14px; color: #888;'>💡 提示：點擊表格左側選取列，可於下方展開診斷明細。</p>", unsafe_allow_html=True)

        try:
            event = st.dataframe(styled_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            selected_rows = event.selection.rows
        except TypeError:
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            selected_rows = []

        # ==========================================
        # 7. 個股深度診斷展開區
        # ==========================================
        if selected_rows:
            selected_idx = selected_rows[0]
            sel_code = final_display_df.iloc[selected_idx]['代號']
            sel_name = final_display_df.iloc[selected_idx]['名稱']
            
            st.markdown("---")
            st.markdown(f"#### 🔍 【{sel_code} {sel_name}】條件診斷明細")
            
            stock_hist = df[df['代號'] == sel_code].head(30)
            
            if use_cond1:
                vol_hist = stock_hist['成交量(張)'].head(cond1_days).tolist()
                vol_str = ", ".join([f"{int(v):,}" for v in vol_hist])
                st.success(f"**✅ 條件 1：連續 {cond1_days} 日成交量 >= {cond1_vol} 張**")
                st.write(f"🔹 過去 {cond1_days} 日明細：`{vol_str}` (最小值: `{int(min(vol_hist)):,}`)")
                
            if use_cond2:
                today_v = stock_hist.iloc[0]['成交量(張)']
                past_vols = stock_hist['成交量(張)'].iloc[1:cond2_days+1].tolist()
                avg_v = sum(past_vols) / len(past_vols) if past_vols else 0
                multi = today_v / avg_v if avg_v > 0 else 0
                vol_str = ", ".join([f"{int(v):,}" for v in past_vols])
                st.success(f"**✅ 條件 2：成交量 > 前 {cond2_days} 日均量的 {cond2_multi} 倍**")
                st.write(f"🔹 今日量：`{int(today_v):,} 張`")
                st.write(f"🔹 前 {cond2_days} 日明細：`{vol_str}`")
                st.write(f"🔹 前均量：`{int(avg_v):,} 張` ➡️ 突破：`{multi:.2f} 倍`")
                
            if use_cond4:
                today_c = stock_hist.iloc[0]['收盤價']
                past_closes = stock_hist['收盤價'].head(cond4_days).tolist()
                max_
