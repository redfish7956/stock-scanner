import streamlit as st
import pandas as pd
import numpy as np
import os
import requests  # 新增：用於呼叫 GitHub API

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
# 2. 資料讀取與預處理引擎 (強制同步版)
# ==========================================
# 偵測檔案修改時間，確保快取會隨著檔案更新而重讀
def get_file_mtime():
    return os.path.getmtime('tw_stock_data.csv') if os.path.exists('tw_stock_data.csv') else 0

@st.cache_data(ttl=3600)
def load_data(mtime):
    try:
        df = pd.read_csv('tw_stock_data.csv', dtype={'代號': str})
        
        # --- 新增：載入產業別映射 ---
        if os.path.exists('industry_mapping.csv'):
            mapping_df = pd.read_csv('industry_mapping.csv', dtype={'代號': str})
            df = df.merge(mapping_df, on='代號', how='left')
        
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

# 呼叫時傳入 get_file_mtime()
df = load_data(get_file_mtime())

if df.empty:
    st.stop()

latest_date = df['日期'].max()
latest_date_str = latest_date.strftime('%Y/%m/%d')
latest_df = df[df['日期'] == latest_date].copy()

# ==========================================
# [新增] 2.5 讀取並合併 EPS 財報數據
# ==========================================
def get_mops_mtime():
    return os.path.getmtime('mops_financial_history_8Q_ALL_DATA.csv') if os.path.exists('mops_financial_history_8Q_ALL_DATA.csv') else 0

@st.cache_data(ttl=3600)
def load_mops_data(mtime):
    try:
        m_df = pd.read_csv('mops_financial_history_8Q_ALL_DATA.csv', dtype={'公司代號': str})
        if not m_df.empty:
            m_df['年度'] = pd.to_numeric(m_df['年度'], errors='coerce')
        return m_df
    except Exception:
        return pd.DataFrame()

mops_df = load_mops_data(get_mops_mtime())

if not mops_df.empty:
    # 確保以年度與季度降序排列 (找出最新的一筆)
    mops_sorted = mops_df.sort_values(by=['年度', '季度'], ascending=[False, False])
    mops_latest = mops_sorted.drop_duplicates(subset=['公司代號'], keep='first').copy()
    
    # 組合面具字串，例如：4.8 (114_Q4)
    mops_latest['最新EPS'] = mops_latest['EPS'].astype(str) + " (" + mops_latest['年度'].astype(str) + "_" + mops_latest['季度'] + ")"
    
    # 合併回 latest_df 主表
    latest_df = latest_df.merge(mops_latest[['公司代號', '最新EPS']], left_on='代號', right_on='公司代號', how='left')
    latest_df.drop(columns=['公司代號'], inplace=True, errors='ignore')
    latest_df['最新EPS'] = latest_df['最新EPS'].fillna("-")
else:
    latest_df['最新EPS'] = "-"

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

# [修改] 移除(未啟用)，正式上線
use_cond5 = st.sidebar.checkbox(
    "5. 連續 N 季 EPS >= M", 
    help="聯動財報資料庫，篩選連續數季皆達標之公司。"
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

# [新增] 第 7 項篩選條件：精確搜尋
use_cond7 = st.sidebar.checkbox(
    "7. 搜尋特定股票", 
    help="輸入股票代號或名稱進行精確篩選。"
)
cond7_keyword = st.sidebar.text_input(
    "輸入代號或名稱關鍵字", 
    disabled=not use_cond7, key='c7_kw'
)

# [新增] 手動觸發 GitHub 爬蟲按鈕
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 系統管理")
if st.sidebar.button("🚀 手動強制更新財報", type="primary"):
    try:
        # 請確認這裡的帳號與專案名稱是否正確
        GITHUB_USER = "redfish7956"
        REPO_NAME = "stock-scanner"
        GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]

        url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/mops_updater.yml/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        res = requests.post(url, headers=headers, json={"ref": "main"})
        
        if res.status_code == 204:
            st.sidebar.success("✅ 成功觸發！雲端機器人已出動更新財報。")
        else:
            st.sidebar.error(f"❌ 觸發失敗 ({res.status_code})")
    except Exception as e:
        st.sidebar.error(f"❌ 錯誤: 找不到 GITHUB_TOKEN 或設定異常。")

# ==========================================
# 5. 核心篩選引擎
# ==========================================
valid_stocks = set(latest_df['代號'].tolist())
dynamic_columns = {} 

cond_list = [
    use_cond_no_etf, 
    use_cond_no_pref, 
    use_cond1, 
    use_cond2, 
    use_cond3, 
    use_cond4, 
    use_cond5, 
    use_cond6,
    use_cond7  # 新增
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

    # [修改] 正式啟動 EPS 篩選邏輯
    if use_cond5:
        if not mops_df.empty:
            # 確保按時間最新到最舊排序
            mops_sorted_cond = mops_df.sort_values(by=['公司代號', '年度', '季度'], ascending=[True, False, False])
            
            def check_eps(g):
                if len(g) < cond5_q: return False
                return (g.head(cond5_q)['EPS'] >= cond5_eps).all()
            
            valid_eps_companies = mops_sorted_cond.groupby('公司代號').filter(check_eps)['公司代號'].unique()
            valid_stocks = valid_stocks.intersection(set(valid_eps_companies))
        else:
            st.warning("⚠️ 財報資料庫未載入，無法執行 EPS 篩選。")

    if use_cond6:
        today_inst = df.groupby('代號')['主力淨買超(張)'].first()
        max_inst = df.groupby('代號')['主力淨買超(張)'].head(cond6_days)
        max_inst = max_inst.groupby(df['代號']).max()
        
        pass_stocks = today_inst[today_inst >= max_inst].index
        valid_stocks = valid_stocks.intersection(set(pass_stocks))

    # [新增] 搜尋條件邏輯
    if use_cond7:
        if cond7_keyword:
            mask = latest_df['代號'].str.contains(cond7_keyword, na=False) | latest_df['名稱'].str.contains(cond7_keyword, na=False)
            pass_stocks = latest_df[mask]['代號']
            valid_stocks = valid_stocks.intersection(set(pass_stocks))
        else:
            valid_stocks = set() # 若有勾選但沒輸入關鍵字，回傳空表

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

    # [修改] 插入 '最新EPS' 欄位至顯示列表中
    base_columns = [
        '代號', '名稱', '產業別', '市場別', '收盤價', 
        '漲跌幅(%)', '成交量(張)', '最新EPS', '本益比', '主力淨買超(張)'
    ]
    
    if use_cond2:
        base_columns.insert(8, '前N日均量倍數') # 調整位置，讓倍數在EPS之後
        
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
        if use_cond1 or use_cond2: cols_to_color.append('成交量(張)')
        if use_cond2: cols_to_color.append('前N日均量倍數')
        if use_cond4: cols_to_color.append('收盤價')
        if use_cond5: cols_to_color.append('最新EPS') # 補上這行：啟動 EPS 篩選時標示藍字
        if use_cond6: cols_to_color.append('主力淨買超(張)')
        
        def color_blue(val):
            return 'color: #2196F3; font-weight: bold;'
            
        styled_df = final_display_df.style.format(active_format_dict, na_rep="-")
        
        if cols_to_color:
            styled_df = styled_df.map(color_blue, subset=cols_to_color)

        st.markdown(
            "<p style='font-size: 14px; color: #888;'>💡 提示：點選表格左側核取方塊可展開診斷明細。</p>", 
            unsafe_allow_html=True
        )

        try:
            event = st.dataframe(
                styled_df, 
                use_container_width=True, 
                hide_index=True, 
                on_select="rerun", 
                selection_mode="single-row"
            )
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
                st.success(f"**✅ 條件 4：收盤價創 {cond4_days} 日新高**")
                st.write(f"🔹 今日收盤：`{today_c:.2f}` (區間最高: `{max_c:.2f}`)")

            # [新增] EPS 診斷明細
            if use_cond5:
                if not mops_df.empty:
                    comp_eps = mops_df[mops_df['公司代號'] == sel_code].sort_values(by=['年度', '季度'], ascending=[False, False]).head(cond5_q)
                    eps_list = comp_eps['EPS'].tolist()
                    eps_str = ", ".join([f"{v:.2f}" for v in eps_list])
                    st.success(f"**✅ 條件 5：連續 {cond5_q} 季 EPS >= {cond5_eps}**")
                    st.write(f"🔹 近 {cond5_q} 季 EPS 明細：`{eps_str}`")

            if use_cond6:
                today_i = stock_hist.iloc[0]['主力淨買超(張)']
                past_inst = stock_hist['主力淨買超(張)'].head(cond6_days).tolist()
                max_i = max(past_inst)
                st.success(f"**✅ 條件 6：主力買超創 {cond6_days} 日新高**")
                st.write(f"🔹 今日買超：`{int(today_i):,} 張` (區間最高: `{int(max_i):,} 張`)")
                
            # [新增] 搜尋條件診斷明細
            if use_cond7:
                st.success(f"**✅ 條件 7：搜尋符合關鍵字 `{cond7_keyword}`**")

        st.markdown("---")
        
        csv_data = final_display_df.to_csv(
            index=False, 
            encoding='utf-8-sig'
        ).encode('utf-8-sig')
        
        st.download_button(
            label="📥 下載篩選結果 (CSV)", 
            data=csv_data, 
            file_name=f"stock_screen_{latest_date_str.replace('/','')}.csv", 
            mime='text/csv'
        )
    else:
        st.warning("無符合條件之股票。")
