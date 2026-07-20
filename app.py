import streamlit as st
import pandas as pd
import numpy as np
import os
import requests
import re
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

# 💡 擴充加載其餘核心數據庫，並修正大盤欄位名稱
@st.cache_data(ttl=3600)
def load_supplementary_files():
    index_df = pd.read_csv('tw_index_data.csv') if os.path.exists('tw_index_data.csv') else pd.DataFrame()
    if not index_df.empty: 
        index_df['日期'] = pd.to_datetime(index_df['日期'])
        # 強制標準化大盤欄位名稱，防堵 KeyError
        index_df = index_df.rename(columns={'收盤價': '指數收盤價', '漲跌點數': '大盤漲跌幅'})
        
    info_df = pd.read_csv('tw_stock_info.csv', dtype={'代號': str}) if os.path.exists('tw_stock_info.csv') else pd.DataFrame()
    warning_df = pd.read_csv('tw_warning_data.csv', dtype={'代號': str}) if os.path.exists('tw_warning_data.csv') else pd.DataFrame()
    daytrade_df = pd.read_csv('tw_daytrade_data.csv', dtype={'代號': str}) if os.path.exists('tw_daytrade_data.csv') else pd.DataFrame()
    
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
use_cond_no_etf = st.sidebar.checkbox("🚫 排除 ETF (00開頭)", value=False, help="剔除代號為 00、01、02 開頭標的。")
use_cond_no_pref = st.sidebar.checkbox("🚫 排除特別股 (含字母)", value=False, help="剔除代號含有英文字母的標的。")
use_cond7 = st.sidebar.checkbox("🔍 搜尋特定股票", help="輸入股票代號或名稱進行精確篩選。")
cond7_keyword = st.sidebar.text_input("輸入代號或名稱關鍵字", disabled=not use_cond7, key='c7_kw')

st.sidebar.markdown("---")

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
# 系統效能與進階運算設定
# ==========================================
st.sidebar.markdown("---")
st.sidebar.markdown("### ⚡ 進階運算設定")
use_disposal_calc = st.sidebar.checkbox("🚨 啟動【處置預判】引擎 (較耗能)", value=False, help="開啟此引擎進行歷史注意紀錄比對與精確的法規臨界點推演。")

# ==========================================
# 系統管理 (GitHub 雙按鈕)
# ==========================================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 系統管理")

time_price = get_file_time_str('tw_stock_data.csv')
time_mops = get_file_time_str('mops_financial_history_8Q_ALL_DATA.csv')
time_warn = get_file_time_str('tw_warning_data.csv')

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
# 5. 核心篩選引擎 (時光機子集保護)
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

cond_list = [use_cond_no_etf, use_cond_no_pref, use_cond7, use_cond1, use_cond2, use_cond3, use_cond4, use_cond5, use_cond6]
has_active_conditions = any(cond_list)

# 建立以目標觀測日期為頂點的歷史數據集
hist_df = df[df['日期'] <= target_date].copy()
all_trading_days = sorted(df['日期'].dt.to_pydatetime().tolist())
all_trading_days = sorted(list(set(all_trading_days)))

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
# 💡 處置預判核心大腦與日期演算引擎 (全新推演模擬架構)
# ==========================================
def parse_disposal_text(raw_text):
    """解析原始資料，提取處置分盤分鐘與營業日數"""
    info = {'分盤': '未知', '營業日數': 10, '期間字串': ''}
    if pd.isna(raw_text): return info
    raw_text = str(raw_text)
    
    m_time = re.search(r'每([^分]+)分鐘撮合', raw_text)
    if m_time:
        t_str = m_time.group(1)
        mapping = {'五': 5, '十': 10, '二十': 20, '二十五': 25, '四十五': 45, '六十': 60, '九十': 90}
        info['分盤'] = f"{mapping.get(t_str, t_str)}分鐘"
        
    m_days = re.search(r'([十]+[二]?)個營業日', raw_text)
    if m_days:
        info['營業日數'] = 12 if '十二' in m_days.group(1) else 10
        
    m_period = re.search(r'自民國.+?日起至.+?日', raw_text)
    if m_period:
        info['期間字串'] = m_period.group(0)
        
    return info

def get_future_date_str(current_idx, days_ahead, trading_days_list):
    """取得未來 N 個營業日的 M/D 格式"""
    target_idx = current_idx + days_ahead
    if target_idx < len(trading_days_list):
        return trading_days_list[target_idx].strftime('%m/%d')
    else:
        dt = trading_days_list[-1]
        rem = target_idx - (len(trading_days_list) - 1)
        while rem > 0:
            dt += timedelta(days=1)
            if dt.weekday() < 5: rem -= 1
        return dt.strftime('%m/%d')

def compute_disposal_risk(row, target_dt, warn_df, trading_days_list):
    code = row['代號']
    if warn_df.empty or target_dt not in trading_days_list:
        return "🟩 狀態正常", 99, {}
        
    t_idx = trading_days_list.index(target_dt)
    stock_warns = warn_df[(warn_df['代號'] == code) & (warn_df['日期'] <= target_dt)]
    
    # 1. 檢查是否正在處置中
    disp_history = stock_warns[stock_warns['狀態'] == '處置'].sort_values('日期', ascending=False)
    if not disp_history.empty:
        latest_disp = disp_history.iloc[0]
        disp_dt = latest_disp['日期'].to_pydatetime()
        
        if disp_dt in trading_days_list:
            disp_idx = trading_days_list.index(disp_dt)
            parsed_info = parse_disposal_text(latest_disp['原始資料'])
            
            # 處置通常是宣告日的「次一營業日」開始
            start_idx = disp_idx + 1
            end_idx = disp_idx + parsed_info['營業日數']
            
            if start_idx <= t_idx <= end_idx:
                return f"🛑 處置中 ({parsed_info['分盤']})", -1, {
                    'status': 'disposal',
                    'info': parsed_info,
                    'rem_days': end_idx - t_idx
                }

    # 將歷史注意日期轉換為 index，大幅提升運算效能與準確度
    warn_dates = set(stock_warns[stock_warns['狀態'] == '注意']['日期'].dt.to_pydatetime())
    warn_indices = set(trading_days_list.index(d) for d in warn_dates if d in trading_days_list)
    
    # 計算截至當下 (t_idx) 的真實次數
    c3 = 0
    for i in range(t_idx, max(-1, t_idx-3), -1):
        if i in warn_indices: c3 += 1
        else: break
        
    c10 = sum(1 for i in range(t_idx, max(-1, t_idx-10), -1) if i in warn_indices)
    c30 = sum(1 for i in range(t_idx, max(-1, t_idx-30), -1) if i in warn_indices)
    
    # 💡 絕對過濾：如果目前完全沒有任何注意紀錄，這檔股票就不可能在短期內處置
    if c3 == 0 and c10 == 0 and c30 == 0:
        return "🟩 狀態正常", 99, {'c3': 0, 'c10': 0, 'c30': 0}

    # 判斷是否今日收盤後已滿足處置條件 (準備明日處置)
    if c3 >= 3 or c10 >= 6 or c30 >= 12:
        return "🚨 明日進入處置", 0, {'status': 'triggered', 'c3': c3, 'c10': c10, 'c30': c30}
        
    # 💡 核心修正：未來日曆推演模擬 (Sliding Window Forward Simulation)
    # 我們只預測未來 1~3 天 (超過 3 天的預測沒有實質風控意義)
    min_days_to_trigger = 99
    
    for future_days in range(1, 4):
        sim_t_idx = t_idx + future_days
        
        # 模擬連續 3 日：(原本連續次數 + 假設未來連續天數)
        sim_c3 = c3 + future_days
        
        # 模擬 10 日視窗：視窗會跟著平移！(新的視窗起點 = 模擬日 - 9)
        hist_start_10 = sim_t_idx - 9
        # 計算落在「新視窗內」的『歷史』注意次數 (未過期的)
        valid_hist_10 = sum(1 for i in range(t_idx, max(-1, hist_start_10-1), -1) if i in warn_indices)
        # 加上假設未來每天都注意的次數
        sim_c10 = valid_hist_10 + future_days
        
        # 模擬 30 日視窗：
        hist_start_30 = sim_t_idx - 29
        valid_hist_30 = sum(1 for i in range(t_idx, max(-1, hist_start_30-1), -1) if i in warn_indices)
        sim_c30 = valid_hist_30 + future_days
        
        # 在這一天是否達標？
        if sim_c3 >= 3 or sim_c10 >= 6 or sim_c30 >= 12:
            min_days_to_trigger = future_days
            break
            
    details = {'status': 'warning', 'c3': c3, 'c10': c10, 'c30': c30, 'req_min': min_days_to_trigger}
    
    if min_days_to_trigger == 1:
        return "⚠️ 明日若注意即達處置", 1, details
    elif min_days_to_trigger <= 3:
        future_date = get_future_date_str(t_idx, min_days_to_trigger, trading_days_list)
        return f"⚠️ 最快 {min_days_to_trigger} 日後({future_date})達標", min_days_to_trigger, details
    elif c3 > 0 or c10 >= 2 or c30 >= 4:
        return "🟨 警戒狀態 (持續監控中)", 99, details
    else:
        return "🟩 狀態正常", 99, details

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

    st.markdown("##### 📈 市場熱度與大盤總覽")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🔥 上漲家數", f"{up_count} 家", f"含漲停 {limit_up} 家")
    m2.metric("🧊 下跌家數", f"{down_count} 家", f"含跌停 {limit_down} 家", delta_color="inverse")
    m3.metric("⚖️ 平盤家數", f"{flat_count} 家", delta_color="off")
    m4.metric("💰 總成交量", f"{total_vol / 10000:,.1f} 萬張", delta_color="off")
    
    if not index_df.empty:
        idx_match = index_df[(index_df['日期'] == target_date) & (index_df['市場別'] == '上市')]
        if not idx_match.empty:
            mclose = idx_match['指數收盤價'].values[0]
            mchange = idx_match['大盤漲跌幅'].values[0]
            sign = "+" if mchange > 0 else ""
            m5.metric("📊 加權指數", f"{mclose:,.2f}")
            m6.metric("📉 大盤漲跌", f"{sign}{mchange:,.2f}", delta_color="normal" if mchange >= 0 else "inverse")
        else:
            m5.metric("📊 加權指數", "無資料")
            m6.metric("📉 大盤漲跌", "-")
    else:
        m5.metric("📊 加權指數", f"{latest_df['收盤價'].mean():,.2f} (均值)")
        m6.metric("📉 大盤漲跌", "-")

st.markdown("---")

if not has_active_conditions:
    st.info("👈 請於左側面板勾選篩選條件以顯示股票數據。")
else:
    result_df = latest_df[latest_df['代號'].isin(valid_stocks)].copy()
    
    if use_cond2 and '前N日均量倍數' in dynamic_columns:
        result_df['前N日均量倍數'] = result_df['代號'].map(dynamic_columns['前N日均量倍數'])

    # 💡 【效能開關判斷】：只有勾選啟動處置預判，才會執行龐大運算
    risk_dict = {}
    if use_disposal_calc:
        risk_results = result_df.apply(lambda r: compute_disposal_risk(r, target_date.to_pydatetime(), warning_df, all_trading_days), axis=1)
        result_df['🚨 處置風控預警'] = [res[0] for res in risk_results]
        result_df['risk_score'] = [res[1] for res in risk_results]
        for idx, row in result_df.iterrows():
            risk_dict[row['代號']] = risk_results[idx][2] # 暫存 details 以供下方診斷區使用
            
        result_df = result_df.sort_values(by=['risk_score', '代號'], ascending=[True, True])
    else:
        result_df = result_df.sort_values(by=['代號'], ascending=[True])

    # 動態產生基礎欄位
    base_columns = ['代號', '名稱']
    if use_disposal_calc:
        base_columns.append('🚨 處置風控預警')
    base_columns.extend(['產業別', '市場別', '開盤價', '最高價', '最低價', '收盤價', '漲跌幅(%)', '成交量(張)', '最新EPS', '本益比', '主力淨買超(張)', '外資買賣超(張)', '投信買賣超(張)', '自營商買賣超(張)'])
    
    if use_cond2: 
        try:
            idx = base_columns.index('成交量(張)')
            base_columns.insert(idx + 1, '前N日均量倍數')
        except:
            base_columns.append('前N日均量倍數')
        
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
            st.markdown(f"#### 🔍 【{sel_code} {sel_name}】深度中樞診斷面板")
            
            tab_filter, tab_disposal = st.tabs(["📈 量化條件診斷", "🚨 處置防護線與注意紀錄追蹤"])
            
            stock_hist = df[(df['代號'] == sel_code) & (df['日期'] <= target_date)].head(30)
            
            with tab_filter:
                if use_cond7:
                    st.success(f"**✅ 條件：搜尋符合關鍵字 `{cond7_keyword}`**")

                if use_cond1:
                    vol_hist = stock_hist['成交量(張)'].head(cond1_days).tolist()
                    vol_str = ", ".join([f"{int(v):,}" if pd.notna(v) else "-" for v in vol_hist])
                    st.success(f"**✅ 條件 1：連續 {cond1_days} 日成交量 >= {cond1_vol} 張**")
                    st.write(f"🔹 過去 {cond1_days} 日明細：`{vol_str}`")
                    
                if use_cond2:
                    today_v = stock_hist.iloc[0]['成交量(張)']
                    past_vols = stock_hist['成交量(張)'].iloc[1:cond2_days+1].tolist()
                    avg_v = sum(past_vols) / len(past_vols) if past_vols else 0
                    multi = today_v / avg_v if avg_v > 0 else 0
                    vol_str = ", ".join([f"{int(v):,}" if pd.notna(v) else "-" for v in past_vols])
                    st.success(f"**✅ 條件 2：成交量 > 前 {cond2_days} 日均量的 {cond2_multi} 倍**")
                    st.write(f"🔹 今日量：`{int(today_v):,} 張`")
                    st.write(f"🔹 前 {cond2_days} 日明細：`{vol_str}`")
                    st.write(f"🔹 均量：`{int(avg_v):,} 張` ➡️ 突破：`{multi:.2f} 倍`")
                    
                if use_cond4 or True:
                    today_c = stock_hist.iloc[0]['收盤價']
                    past_closes = stock_hist['收盤價'].head(cond4_days).tolist()
                    max_c = max(past_closes)
                    c_str = ", ".join([f"{v:.2f}" if pd.notna(v) else "-" for v in past_closes])
                    st.success(f"**📊 條件 4 追蹤：收盤價與近 {cond4_days} 日價格視窗明細**")
                    st.write(f"🔹 今日收盤：`{today_c:.2f}` (區間最高點: `{max_c:.2f}`)")
                    st.write(f"🔹 區間滾動價格序列：`{c_str}`")

                if use_cond5:
                    if not mops_df.empty:
                        comp_eps = mops_df[mops_df['公司代號'] == sel_code].sort_values(by=['年度', '季度'], ascending=[False, False]).head(cond5_q)
                        eps_list = comp_eps['EPS'].tolist()
                        eps_str = ", ".join([f"{v:.2f}" for v in eps_list])
                        st.success(f"**✅ 條件 5：連續 {cond5_q} 季 EPS >= {cond5_eps}**")
                        st.write(f"🔹 近 {cond5_q} 季 EPS 明細：`{eps_str}`")

                # 💡 防護 int(NaN) 報錯
                if use_cond6 or True:
                    today_i = stock_hist.iloc[0]['主力淨買超(張)'] if '主力淨買超(張)' in stock_hist.columns else 0
                    past_inst = stock_hist['主力淨買超(張)'].head(cond6_days).tolist() if '主力淨買超(張)' in stock_hist.columns else []
                    max_i = max(past_inst) if past_inst else 0
                    i_str = ", ".join([f"{int(v):,}" if pd.notna(v) else "-" for v in past_inst])
                    st.success(f"**📊 條件 6 追蹤：主力買超與近 {cond6_days} 日籌碼明細**")
                    st.write(f"🔹 今日主力：`{int(today_i) if pd.notna(today_i) else 0:,} 張` (區間最大值: `{int(max_i) if pd.notna(max_i) else 0:,} 張`)")
                    st.write(f"🔹 區間滾動籌碼序列：`{i_str}`")
                    
            with tab_disposal:
                if not use_disposal_calc:
                    st.info("⚠️ 您目前已關閉處置預判引擎。請先至左側面板【⚡ 進階運算設定】勾選啟動，以解鎖詳細注意紀錄推演報告。")
                else:
                    st.write("##### 🛡️ 交易所監視指標狀態")
                    
                    details = risk_dict.get(sel_code, {})
                    d_status = details.get('status', '')
                    
                    if d_status == 'disposal':
                        info = details.get('info', {})
                        st.error(f"**🛑 此標的目前正在處置中！**")
                        st.write(f"🔹 **處置區間**：`{info.get('期間字串', '未知')}`")
                        st.write(f"🔹 **處置級距**：`{info.get('分盤', '未知')}` (共 {info.get('營業日數', 10)} 個營業日)")
                    else:
                        st.write("**1. 歷史公布注意訊號追蹤 (截至觀測日)：**")
                        if not warning_df.empty:
                            past_warns = warning_df[(warning_df['代號'] == sel_code) & (warning_df['日期'] <= target_date) & (warning_df['狀態'] == '注意')].head(12)
                            if not past_warns.empty:
                                w_dates = past_warns['日期'].dt.strftime('%m/%d').tolist()
                                st.warning(f"⚠️ 該股近期已累積注意紀錄。最新注意日期：`{', '.join(w_dates)}`")
                            else:
                                st.info("🟩 該股最近 30 個營業日無任何公告注意記錄，背景乾淨。")
                                
                        st.write("**2. 處置法規計數器：**")
                        col_a, col_b, col_c = st.columns(3)
                        col_a.metric("連續注意天數", f"{details.get('c3', 0)} 天", "滿3天即處置", delta_color="inverse")
                        col_b.metric("近10日注意次數", f"{details.get('c10', 0)} 次", "滿6次即處置", delta_color="inverse")
                        col_c.metric("近30日注意次數", f"{details.get('c30', 0)} 次", "滿12次即處置", delta_color="inverse")

        st.markdown("---")
        csv_data = final_display_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button(label="📥 下載篩選結果 (CSV)", data=csv_data, file_name=f"stock_screen_{latest_date_str.replace('/','')}.csv", mime='text/csv')
    else:
        st.warning("無符合條件之股票。")
