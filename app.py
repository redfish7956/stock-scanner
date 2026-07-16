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
        
        if df.empty:
            st.error("CSV 目前無資料，可能背景正在更新，請稍後重整。")
            return pd.DataFrame()
            
        df['日期'] = pd.to_datetime(df['日期'])
        
        # 💡 【防呆強化】：確保所有數值欄位被正確解析為 Float 格式，防堵字串比對 Bug
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

df = load_data(get_file_mtime())

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
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF (00開頭)", value=False, help="剔除代號為 00、01、02 開頭標的。")
use_cond_no_pref = st.sidebar.checkbox("🚫 排除特別股 (含字母)", value=False, help="剔除代號含有英文字母的標的。")
use_cond7 = st.sidebar.checkbox("🔍 搜尋特定股票", help="輸入股票代號或名稱進行精確篩選。")
cond7_keyword = st.sidebar.text_input("輸入代號或名稱關鍵字", disabled=not use_cond7, key='c7_kw')

st.sidebar.markdown("---")

# 【區塊二】量化條件篩選區
use_cond1 = st.sidebar.checkbox("1. 連續 N 日成交量 >= M 張", help="過去 N 天（含今日）每天成交量 >= 設定張數。")
col1, col2 = st.sidebar.columns(2)
cond1_days = col1.number_input("連續日數", min_value=1, value=5, disabled=not use_cond1, key='c1_d')
cond1_vol = col2.number_input("最低張數", min_value=0, value=500, step=100, disabled=not use_cond1, key='c1_v')

use_cond2 = st.sidebar.checkbox("2. 成交量 > 前 N 日均量 M 倍", help="今日成交量 > (前 N 日均量) * M 倍。不含今日。")
col1, col2 = st.sidebar.columns(2)
cond2_days = col1.number_input("前 N 日", min_value=1, value=5, disabled=not use_cond2, key='c2_d')
cond2_multi = col2.number_input("突破倍數", min_value=1.0, value=2.0, step=0.5, disabled=not use_cond2, key='c2_m')

use_cond3 = st.sidebar.checkbox("3. 本益比 <= N 倍", help="今日最新本益比 <= N，且排除虧損公司。")
cond3_pe = st.sidebar.number_input("本益比上限", min_value=0.0, value=15.0, disabled=not use_cond3, key='c3_pe')

use_cond4 = st.sidebar.checkbox("4. 收盤價創 N 日新高", help="今日收盤價 >= 過去 N 天（含今日）的最高價。")
cond4_days = st.sidebar.number_input("創高日數", min_value=2, value=20, disabled=not use_cond4, key='c4_d')

use_cond5 = st.sidebar.checkbox("5. 連續 N 季 EPS >= M", help="聯動財報資料庫，篩選連續數季皆達標之公司。")
col1, col2 = st.sidebar.columns(2)
cond5_q = col1.number_input("連續季數", min_value=1, value=4, disabled=not use_cond5, key='c5_q')
cond5_eps = col2.number_input("最低 EPS", min_value=0.0, value=1.0, disabled=not use_cond5, key='c5_e')

use_cond6 = st.sidebar.checkbox("6. 主力買超創 N 日新高", help="今日主力買超 >= 過去 N 天（含今日）最大值。")
cond6_days = st.sidebar.number_input("創高日數", min_value=2, value=5, disabled=not use_cond6, key='c6_d')

# ==========================================
# 系統管理 (GitHub 雙按鈕 + 懸浮時間戳)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 系統管理")

# 取得三個系統檔案的最後更新時間 (已校正為台灣時間)
time_price = get_file_time_str('tw_stock_data.csv')
time_mops = get_file_time_str('mops_financial_history_8Q_ALL_DATA.csv')
time_warn = get_file_time_str('tw_warning_data.csv')

# 按鈕 1：每日價量
help_price = f"更新每日的股價、價量、本益比及三大法人等資料。\n\n🕒 檔案最後修改：{time_price}"
if st.sidebar.button("📊 手動更新每日價量", type="primary", help=help_price):
    try:
        GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
        url = "https://api.github.com/repos/redfish7956/stock-scanner/actions/workflows/daily_crawler.yml/dispatches"
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
        res = requests.post(url, headers=headers, json={"ref": "main"})
        if res.status_code == 204: st.sidebar.success("✅ 成功觸發！雲端機器人已出動更新「每日價量」。")
        else: st.sidebar.error(f"❌ 觸發失敗 ({res.status_code})")
    except: st.sidebar.error("❌ 錯誤: 找不到 GITHUB_TOKEN。")

# 按鈕 2：季財報
help_mops = f"更新各上市櫃公司的 EPS、營業毛利等財務數據。\n\n🕒 檔案最後修改：{time_mops}"
if st.sidebar.button("🚀 手動更新季財報", type="primary", help=help_mops):
    try:
        GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
        url = "https://api.github.com/repos/redfish7956/stock-scanner/actions/workflows/mops_updater.yml/dispatches"
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
        res = requests.post(url, headers=headers, json={"ref": "main"})
        if res.status_code == 204: st.sidebar.success("✅ 成功觸發！雲端機器人已出動更新「季財報」。")
        else: st.sidebar.error(f"❌ 觸發失敗 ({res.status_code})")
    except: st.sidebar.error("❌ 錯誤: 找不到 GITHUB_TOKEN。")

# 按鈕 3：注意與處置股
help_warn = f"更新過去 120 天的注意與處置股歷史紀錄。\n\n🕒 檔案最後修改：{time_warn}"
if st.sidebar.button("🚨 手動更新處置名單", type="primary", help=help_warn):
    try:
        GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
        url = "https://api.github.com/repos/redfish7956/stock-scanner/actions/workflows/warning_crawler.yml/dispatches"
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
        res = requests.post(url, headers=headers, json={"ref": "main"})
        if res.status_code == 204: st.sidebar.success("✅ 成功觸發！雲端機器人已出動更新「注意與處置名單」。")
        else: st.sidebar.error(f"❌ 觸發失敗 ({res.status_code})")
    except: st.sidebar.error("❌ 錯誤: 找不到 GITHUB_TOKEN。")

# ==========================================
# 5. 核心篩選引擎
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

cond_list = [use_cond_no_etf, use_cond_no_pref, use_cond7, use_cond1, use_cond2, use_cond3, use_cond4, use_cond5, use_cond6]
has_active_conditions = any(cond_list)

if has_active_conditions:
    if use_cond_no_etf:
        mask = ~latest_df['代號'].str.match(r'^(00|01|02)')
        valid_stocks = valid_stocks.intersection(set(latest_df[mask]['代號']))

    if use_cond_no_pref:
        mask = ~latest_df['代號'].str.contains(r'[a-zA-Z]', regex=True, na=False)
        valid_stocks = valid_stocks.intersection(set(latest_df[mask]['代號']))

    if use_cond7:
        if cond7_keyword:
            mask = latest_df['代號'].str.contains(cond7_keyword, na=False) | latest_df['名稱'].str.contains(cond7_keyword, na=False)
            valid_stocks = valid_stocks.intersection(set(latest_df[mask]['代號']))
        else:
            valid_stocks = set() 

    # 💡 【時光機修復核心】：建立以目標觀測日期（target_date）為頂點的歷史數據集，解決 N 日邏輯與時光機脫節的問題
    hist_df = df[df['日期'] <= target_date].copy()

    if use_cond1:
        min_vols = hist_df.groupby('代號')['成交量(張)'].head(cond1_days).groupby(hist_df['代號']).min()
        valid_stocks = valid_stocks.intersection(set(min_vols[min_vols >= cond1_vol].index))

    if use_cond2:
        today_vol = hist_df.groupby('代號')['成交量(張)'].first()
        past_N_mean = hist_df.groupby('代號')['成交量(張)'].apply(lambda x: x.iloc[1:cond2_days+1].mean())
        cond_met = today_vol > (past_N_mean * cond2_multi)
        valid_stocks = valid_stocks.intersection(set(cond_met[cond_met].index))
        dynamic_columns['前N日均量倍數'] = (today_vol / past_N_mean.replace(0, np.nan)).round(2)

    if use_cond3:
        mask = (latest_df['本益比'] <= cond3_pe) & (latest_df['本益比'] > 0)
        valid_stocks = valid_stocks.intersection(set(latest_df[mask]['代號']))

    # 💡 【條件 4 完全修復】：基於 hist_df 進行分組 head 取創高 N 日新高
    if use_cond4:
        today_close = hist_df.groupby('代號')['收盤價'].first()
        max_closes = hist_df.groupby('代號')['收盤價'].head(cond4_days).groupby(hist_df['代號']).max()
        valid_stocks = valid_stocks.intersection(set(today_close[today_close >= max_closes].index))

    if use_cond5:
        if not mops_df.empty:
            mops_sorted_cond = mops_df.sort_values(by=['公司代號', '年度', '季度'], ascending=[True, False, False])
            def check_eps(g):
                if len(g) < cond5_q: return False
                return (g.head(cond5_q)['EPS'] >= cond5_eps).all()
            valid_eps_companies = mops_sorted_cond.groupby('公司代號').filter(check_eps)['公司代號'].unique()
            valid_stocks = valid_stocks.intersection(set(valid_eps_companies))
        else:
            st.warning("⚠️ 財報資料庫未載入，無法執行 EPS 篩選。")

    if use_cond6:
        today_inst = hist_df.groupby('代號')['主力淨買超(張)'].first()
        max_inst = hist_df.groupby('代號')['主力淨買超(張)'].head(cond6_days).groupby(hist_df['代號']).max()
        valid_stocks = valid_stocks.intersection(set(today_inst[today_inst >= max_inst].index))

# ==========================================
# 6. 右側主畫面 (Main Area)
# ==========================================
col_title, col_date = st.columns([3, 1])
with col_title:
    st.title("台股量化篩選系統")
with col_date:
    st.markdown(f"<h4 style='text-align: right; color: #666;'>觀測日：{latest_date_str}</h4>", unsafe_allow_html=True)

# 📈 大盤與市場寬度儀表板
if '漲跌百分比' in latest_df.columns:
    up_count = len(latest_df[latest_df['漲跌幅'] > 0])
    down_count = len(latest_df[latest_df['漲跌幅'] < 0])
    limit_up = len(latest_df[latest_df['漲跌百分比'] >= 9.5])
    limit_down = len(latest_df[latest_df['漲跌百分比'] <= -9.5])
    flat_count = len(latest_df) - up_count - down_count
    total_vol = latest_df['成交量(張)'].sum() if '成交量(張)' in latest_df.columns else 0

    # 💡 【加強】：尋找大盤指標（優先尋找 0000 / t00 / IX0001 / 加權指數 程式碼），找不到則動態計算均值趨勢
    market_idx = latest_df[latest_df['代號'].isin(['0000', 't00', 'IX0001', '加權指數'])]

    st.markdown("##### 📈 市場熱度與大盤總覽")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🔥 上漲家數", f"{up_count} 家", f"含漲停 {limit_up} 家")
    m2.metric("🧊 下跌家數", f"{down_count} 家", f"含跌停 {limit_down} 家", delta_color="inverse")
    m3.metric("⚖️ 平盤家數", f"{flat_count} 家", delta_color="off")
    m4.metric("💰 總成交量", f"{total_vol / 10000:,.1f} 萬張", delta_color="off")
    
    if not market_idx.empty:
        mclose = market_idx['收盤價'].values[0]
        mchange = market_idx['漲跌幅'].values[0]
        m_prev = mclose - mchange
        mpct = (mchange / m_prev) * 100 if m_prev != 0 else 0
        sign = "+" if mchange > 0 else ""
        m5.metric("📊 大盤收盤", f"{mclose:,.2f}")
        m6.metric("📉 大盤漲跌", f"{sign}{mchange:,.2f}", f"{sign}{mpct:.2f}%", delta_color="normal" if mchange >= 0 else "inverse")
    else:
        avg_close = latest_df['收盤價'].mean()
        avg_change = latest_df['漲跌幅'].mean()
        avg_prev = avg_close - avg_change
        avg_pct = (avg_change / avg_prev) * 100 if avg_prev != 0 else 0
        sign = "+" if avg_change > 0 else ""
        m5.metric("📊 大盤收盤", f"{avg_close:,.2f} (均值)")
        m6.metric("📉 大盤漲跌", f"{sign}{avg_change:,.2f}", f"{sign}{avg_pct:.2f}%", delta_color="normal" if avg_change >= 0 else "inverse")

st.markdown("---")

if not has_active_conditions:
    st.info("👈 請於左側面板勾選篩選條件以顯示股票數據。")
else:
    result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
    
    if use_cond2 and '前N日均量倍數' in dynamic_columns:
        result_df['前N日均量倍數'] = result_df['代號'].map(dynamic_columns['前N日均量倍數'])

    base_columns = [
        '代號', '名稱', '產業別', '市場別', 
        '開盤價', '最高價', '最低價', '收盤價', '漲跌幅(%)', 
        '成交量(張)', '最新EPS', '本益比', 
        '主力淨買超(張)', '外資買賣超(張)', '投信買賣超(張)', '自營商買賣超(張)'
    ]
    
    if use_cond2: base_columns.insert(10, '前N日均量倍數') 
        
    base_columns = [c for c in base_columns if c in result_df.columns]
    final_display_df = result_df[base_columns]

    st.write(f"### 篩選結果：共 {len(final_display_df)} 檔符合條件")
    
    if not final_display_df.empty:
        format_dict = {
            '開盤價': '{:,.2f}', '最高價': '{:,.2f}', '最低價': '{:,.2f}', '收盤價': '{:,.2f}',
            '成交量(張)': '{:,.0f}', '主力淨買超(張)': '{:,.0f}',
            '外資買賣超(張)': '{:,.0f}', '投信買賣超(張)': '{:,.0f}', '自營商買賣超(張)': '{:,.0f}',
            '本益比': '{:,.2f}', '前N日均量倍數': '{:,.2f}'
        }
        active_format_dict = {k: v for k, v in format_dict.items() if k in final_display_df.columns}
        
        cols_to_color = []
        if use_cond1 or use_cond2: cols_to_color.append('成交量(張)')
        if use_cond2: cols_to_color.append('前N日均量倍數')
        if use_cond4: cols_to_color.append('收盤價')
        if use_cond5: cols_to_color.append('最新EPS') 
        if use_cond6: cols_to_color.append('主力淨買超(張)')
        
        def color_blue(val): return 'color: #2196F3; font-weight: bold;'
            
        styled_df = final_display_df.style.format(active_format_dict, na_rep="-")
        if cols_to_color: styled_df = styled_df.map(color_blue, subset=cols_to_color)

        st.markdown("<p style='font-size: 14px; color: #888;'>💡 提示：點選表格左側核取方塊可展開診斷明細。</p>", unsafe_allow_html=True)

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
            
            # 從歷史庫中抓取該股票在「目標日期」及以前的 30 天數據
            stock_hist = df[(df['代號'] == sel_code) & (df['日期'] <= target_date)].head(30)
            
            if use_cond7:
                st.success(f"**✅ 條件：搜尋符合關鍵字 `{cond7_keyword}`**")

            if use_cond1:
                vol_hist = stock_hist['成交量(張)'].head(cond1_days).tolist()
                vol_str = ", ".join([f"{int(v):,}" for v in vol_hist])
                st.success(f"**✅ 條件 1：連續 {cond1_days} 日成交量 >= {cond1_vol} 張**")
                st.write(f"🔹 過去 {cond1_days} 日明細：`{vol_str}` (最小: `{int(min(vol_hist)):,}`)")
                
            if use_cond2:
                today_v = stock_hist.iloc[0]['成交量(張)']
                past_vols = stock_hist['成交量(張)'].iloc[1:cond2_days+1].tolist()
                avg_v = sum(past_vols) / len(past_vols) if past_vols else 0
                multi = today_v / avg_v if avg_v > 0 else 0
                vol_str = ", ".join([f"{int(v):,}" for v in past_vols])
                st.success(f"**✅ 條件 2：成交量 > 前 {cond2_days} 日均量的 {cond2_multi} 倍**")
                st.write(f"🔹 今日量：`{int(today_v):,} 張`")
                st.write(f"🔹 前 {cond2_days} 日明細：`{vol_str}`")
                st.write(f"🔹 均量：`{int(avg_v):,} 張` ➡️ 突破：`{multi:.2f} 倍`")
                
            if use_cond4:
                today_c = stock_hist.iloc[0]['收盤價']
                past_closes = stock_hist['收盤價'].head(cond4_days).tolist()
                max_c = max(past_closes)
                c_str = ", ".join([f"{v:.2f}" for v in past_closes])
                st.success(f"**✅ 條件 4：收盤價創 {cond4_days} 日新高**")
                st.write(f"🔹 今日收盤：`{today_c:.2f}` (區間最高: `{max_c:.2f}`)")
                st.write(f"🔹 過去 {cond4_days} 日明細：`{c_str}`")

            if use_cond5:
                if not mops_df.empty:
                    comp_eps = mops_df[mops_df['公司代號'] == sel_code].sort_values(by=['年度', '季度'], ascending=[False, False]).head(cond5_q)
                    eps_list = comp_eps['EPS'].tolist()
                    eps_str = ", ".join([f"{v:.2f}" for v in eps_list])
                    st.success(f"**✅ 條件 5：連續 {cond5_q} 季 EPS >= {cond5_eps}**")
                    st.write(f"🔹 近 {cond5_q} 季 EPS 明細：`{eps_str}`")

            if use_cond6:
                today_i = stock_hist.iloc[0]['主力淨買超(張)'] if '主力淨買超(張)' in stock_hist.columns else 0
                past_inst = stock_hist['主力淨買超(張)'].head(cond6_days).tolist() if '主力淨買超(張)' in stock_hist.columns else []
                max_i = max(past_inst) if past_inst else 0
                i_str = ", ".join([f"{int(v):,}" for v in past_inst])
                st.success(f"**✅ 條件 6：主力買超創 {cond6_days} 日新高**")
                st.write(f"🔹 今日買超：`{int(today_i):,} 張` (區間最高: `{int(max_i):,} 張`)")
                st.write(f"🔹 過去 {cond6_days} 日明細：`{i_str}`")

        st.markdown("---")
        csv_data = final_display_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(label="📥 下載篩選結果 (CSV)", data=csv_data, file_name=f"stock_screen_{latest_date_str.replace('/','')}.csv", mime='text/csv')
    else:
        st.warning("無符合條件之股票。")
