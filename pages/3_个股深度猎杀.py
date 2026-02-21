import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta

# --- 架构师注释: 个股深度猎杀 v13.9 ---
# 1. 同步接入 MACRO_TAGS_MAP 实现多重宏观分组穿透映射。

try:
    from my_stock_pool import TIC_MAP, ASSET_CN_DB, REGIME_MAP, USER_GROUPS_DEF, MACRO_TAGS_MAP
except ImportError:
    st.error("⚠️ 配置文件缺失，请检查项目结构。")
    st.stop()

st.set_page_config(page_title="个股深度猎杀", layout="wide", page_icon="🎯")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！正在重新拉取最新数据...")
        st.rerun()

st.markdown("""
<style>
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 12px; margin-top: 10px; margin-bottom: 10px; font-size: 13px; color: #ccc; }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Layer 3: 个股深度猎杀 (Deep Dive)")
st.caption("核心逻辑：接收 Page 2 晋级标的 ➡️ 筹码结构(POC)精准打击 ➡️ 寻找绝佳盈亏比入场点")

@st.cache_data(ttl=3600*4)
def get_current_macro_regime():
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*4)
        df_clock = yf.download(['XLY', 'XLP', 'TIP', 'IEF'], start=start_date, end=end_date, progress=False)['Close'].ffill()
        df_calc = pd.DataFrame(index=df_clock.index)
        df_calc['Growth_Raw'] = df_clock['XLY'] / df_clock['XLP']
        df_calc['Inflation_Raw'] = df_clock['TIP'] / df_clock['IEF']
        df_calc['Growth_Smooth'] = df_calc['Growth_Raw'].rolling(20).mean()
        df_calc['Inflation_Smooth'] = df_calc['Inflation_Raw'].rolling(20).mean()
        df_z = pd.DataFrame(index=df_calc.index)
        for col, raw in [('Growth', 'Growth_Smooth'), ('Inflation', 'Inflation_Smooth')]:
            roll_mean = df_calc[raw].rolling(window=750).mean()
            roll_std = df_calc[raw].rolling(window=750).std()
            df_z[col] = (df_calc[raw] - roll_mean) / roll_std
        df_z = df_z.dropna()
        if len(df_z) == 0: return "Soft"
        g, i = float(df_z['Growth'].iloc[-1]), float(df_z['Inflation'].iloc[-1])
        if g > 0 and i > 0: return "Hot"
        elif g > 0 and i < 0: return "Soft"
        elif g < 0 and i < 0: return "Rec"
        elif g < 0 and i > 0: return "Stag"
        return "Soft"
    except: return "Soft"

# [核心修复] 使用多标签映射池
MACRO_GROUPS_DEF = {
    "E: 宏观软着陆 (Soft)": MACRO_TAGS_MAP.get("Soft", []),
    "F: 宏观滞胀 (Stag)": MACRO_TAGS_MAP.get("Stag", []),
    "G: 宏观衰退 (Rec)": MACRO_TAGS_MAP.get("Rec", []),
    "H: 宏观再通胀 (Hot)": MACRO_TAGS_MAP.get("Hot", [])
}
ALL_GROUPS = {**USER_GROUPS_DEF, **MACRO_GROUPS_DEF}

current_regime_code = get_current_macro_regime()
regime_mapping = {"Soft": "E: 宏观软着陆 (Soft)", "Stag": "F: 宏观滞胀 (Stag)", "Rec": "G: 宏观衰退 (Rec)", "Hot": "H: 宏观再通胀 (Hot)"}
default_macro_group = regime_mapping.get(current_regime_code, "E: 宏观软着陆 (Soft)")

all_default_tickers = []
for lst in USER_GROUPS_DEF.values(): all_default_tickers.extend(lst)
for t in REGIME_MAP.keys(): all_default_tickers.append(t)
full_ticker_list = list(set([t.strip().upper() for t in all_default_tickers]))

@st.cache_data(ttl=3600*4)
def get_global_data(tickers):
    if not tickers: return pd.DataFrame()
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=400)
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']
        data = data[data.index.dayofweek < 5]
        return data.ffill()
    except: return pd.DataFrame()

def run_funnel_scan(df_prices):
    qualified = []
    for t in df_prices.columns:
        try:
            s = df_prices[t].dropna()
            if len(s) < 200: continue
            
            curr = float(s.iloc[-1])
            ma20 = float(s.rolling(20).mean().iloc[-1])
            ma60 = float(s.rolling(60).mean().iloc[-1])
            ma200 = float(s.rolling(200).mean().iloc[-1])
            
            status = "震荡"
            if curr > ma20 > ma60 > ma200: status = "🔥 主升浪"
            elif curr < ma60: status = "❄️ 弱势/破位"
            elif curr > ma200: status = "📈 多头趋势"
            
            if curr <= ma60: continue 

            daily_ret = s.pct_change().dropna()
            down_ret = daily_ret[daily_ret < 0]
            if len(down_ret) > 0 and down_ret.std() != 0:
                down_std = down_ret.std() * np.sqrt(252)
                sortino = (daily_ret.mean() * 252) / down_std
            else: sortino = 0.0
            if pd.isna(sortino) or np.isinf(sortino): sortino = 0.0
            
            high_120 = float(s.rolling(120).max().iloc[-1])
            risk = curr - ma60
            reward = high_120 - curr
            rr = reward / risk if risk > 0 else 0.0
            if pd.isna(rr) or np.isinf(rr): rr = 0.0
            
            score = 0
            if "主升" in status: score += 40
            elif "多头" in status: score += 20
            score += min(max(sortino, 0), 3) * 13.3 
            score += min(max(rr, 0), 3) * 6.6       
            
            if score >= 60:
                cn_name = TIC_MAP.get(t, t)
                qualified.append({
                    "label": f"{t} ({cn_name}) | 分数: {score:.1f}", 
                    "ticker": t, "score": score
                })
        except: continue
    qualified.sort(key=lambda x: x['score'], reverse=True)
    return qualified

with st.sidebar:
    st.header("🎯 猎杀目标选择")
    selected_groups_list = st.multiselect(
        "📂 锁定战术分组 (与 Page 2 同步):", 
        list(ALL_GROUPS.keys()), default=[default_macro_group]
    )
    
    target_tickers_subset = []
    for g in selected_groups_list: target_tickers_subset.extend(ALL_GROUPS.get(g, []))
    target_tickers_subset = list(set(target_tickers_subset))
    
    with st.spinner("同步全局资产与多重标签过滤..."):
        raw_data = get_global_data(full_ticker_list)
        if not raw_data.empty and target_tickers_subset:
            valid_tickers = [t for t in target_tickers_subset if t in raw_data.columns]
            df_subset = raw_data[valid_tickers]
            candidates = run_funnel_scan(df_subset)
        else: candidates = []

    if candidates:
        selected_label = st.selectbox("🏆 Page 2 晋级池映射:", [c['label'] for c in candidates])
        auto_ticker = selected_label.split(" ")[0]
    else:
        auto_ticker = ""
        if len(selected_groups_list) == 0: st.warning("请在上方选择战术分组！")
        else: st.warning("该分组下当前无 Molt 分数 ≥ 60 的强多头标的。")

    st.markdown("---")
    st.caption("手动越权查询:")
    manual_ticker = st.text_input("🔍 输入自定义代码:", "").upper()
    target_ticker = manual_ticker if manual_ticker else auto_ticker
    
    st.markdown("""
    <div class='formula-box'>
    <b>⚙️ 算法对齐说明:</b><br>
    此系统已物理隔离周末时间轴，完美复刻 Page 2 的 252日均线法则。分数与排名将做到 100% 同步。
    </div>
    """, unsafe_allow_html=True)

if target_ticker:
    try:
        stock = yf.Ticker(target_ticker)
        hist = stock.history(period="1y")
        try: info = stock.info or {}
        except: info = {}
            
        if hist.empty:
            st.warning(f"无法获取 {target_ticker} 的历史数据。")
            st.stop()
            
        hist = hist.dropna(subset=['Close'])
        curr_price = float(hist['Close'].iloc[-1])
        cn_name = TIC_MAP.get(target_ticker, target_ticker)
        
        st.header(f"📊 {target_ticker} ({cn_name}) 战术分析板")
        with st.expander(f"🏢 核心宏观逻辑推演", expanded=True):
            if target_ticker in ASSET_CN_DB: st.info(f"**【战略基调】** {ASSET_CN_DB[target_ticker]}")
            else: st.warning(f"**【系统简介】** {info.get('longBusinessSummary', '暂无描述。')}")

        price_bins = pd.cut(hist['Close'], bins=60)
        vol_profile = hist.groupby(price_bins, observed=True)['Volume'].sum()
        max_vol_bin = vol_profile.idxmax()
        poc_price = float((max_vol_bin.left + max_vol_bin.right) / 2)
        dist_poc = float((curr_price / poc_price - 1) * 100)
        
        ma60 = float(hist['Close'].rolling(60).mean().iloc[-1])
        resistance = float(hist['High'].tail(120).max())
        
        if curr_price > max(poc_price, ma60): support_level = max(poc_price, ma60)
        else: support_level = min(float(hist['Low'].tail(20).min()), ma60)
            
        risk_dist = curr_price - support_level
        rr = (resistance - curr_price) / risk_dist if risk_dist > 0 else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("当前价格", f"${curr_price:.2f}")
        c2.metric("筹码核心 (POC)", f"${poc_price:.2f}", delta=f"{dist_poc:.1f}% 偏离")
        c3.metric("图表阻力盈亏比 (R:R)", f"{rr:.2f}", delta="具备操作价值" if rr > 2 else "风险收益不对等")
        fcf = info.get('freeCashflow')
        c4.metric("自由现金流 (FCF)", f"${fcf/1e9:.1f}B" if fcf and fcf > 0 else "N/A")

        col_main, col_side = st.columns([3, 1])
        with col_main:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name="Price"))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Close'].rolling(60).mean(), line=dict(color='orange', width=1.5), name="MA60"))
            fig.add_hline(y=poc_price, line_dash="dash", line_color="cyan", annotation_text="POC (绝对成本区)", annotation_position="top left")
            fig.add_hline(y=resistance, line_color="#E74C3C", annotation_text="Target (阻力目标)", annotation_position="top left")
            fig.add_hline(y=support_level, line_color="#2ECC71", annotation_text="Stop (防守底线)", annotation_position="bottom left")
            fig.update_layout(height=500, margin=dict(t=30, l=10, r=10, b=10), template="plotly_dark", xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig, use_container_width=True)
            
        with col_side:
            st.markdown("### 📝 战术裁决")
            if dist_poc > 5: st.success("🟢 获利盘主导，上方抛压极轻。适合顺势持有。")
            elif dist_poc < -5: st.error("🔴 处于套牢区下方，需警惕解套抛压。")
            else: st.warning("🟡 处于核心成本区，若缩量回踩则是绝佳狙击点。")
            
            st.markdown(f"**🎯 第一目标:** `${resistance:.2f}`")
            st.markdown(f"**🛡️ 极限防守:** `${support_level:.2f}`")
            st.markdown("<div class='formula-box'><b>注意:</b> 这里的图表盈亏比测算基于绝对价格图形，与 Page 2 中海选模型的趋势盈亏比算法分离。</div>", unsafe_allow_html=True)
    except Exception as e:
        st.error(f"分析模块遭遇异常中止: {e}")