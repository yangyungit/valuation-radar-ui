import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
import pandas_datareader.data as web

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_macro_scores, fetch_funnel_scores

core_data = fetch_core_data()

# 解包页面需要的字典
TIC_MAP = core_data.get("TIC_MAP", {})

@st.cache_data(ttl=3600*4)
def get_clock_fred_data():
    """从 FRED 拉取宏观官方数据 (与 1_宏观定调.py 保持 SSOT 对齐)"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650 + 400)
    try:
        df_fred = web.DataReader(['CPILFESL', 'BAMLH0A0HYM2'], 'fred', start_date, end_date)
        if df_fred.index.tz is not None:
            df_fred.index = df_fred.index.tz_localize(None)
        result = pd.DataFrame(index=df_fred.index)
        if 'CPILFESL' in df_fred.columns:
            result['Core_CPI_YoY'] = df_fred['CPILFESL'].pct_change(12) * 100
        if 'BAMLH0A0HYM2' in df_fred.columns:
            result['HY_Spread'] = df_fred['BAMLH0A0HYM2']
        result = result.dropna(how='all').resample('D').ffill()
        return result
    except Exception:
        return pd.DataFrame(columns=['Core_CPI_YoY', 'HY_Spread'])

st.set_page_config(page_title="Moltbot 首席投资官中枢", layout="wide", page_icon="🏦")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新拉取全系统数据"):
        st.cache_data.clear()
        st.success("全局缓存已清除！")
        st.rerun()

st.markdown("""
<style>
    .metric-value { font-size: 32px; font-weight: bold; }
    p, li, div[data-testid="stCaptionContainer"] { font-size: 16px !important; line-height: 1.6 !important; }
    [data-testid="stDataFrame"] { font-size: 15px !important; }
    
    .formula-box { background-color: #1a1a1a; border-left: 4px solid #3498DB; padding: 18px; margin-top: 10px; margin-bottom: 15px; font-size: 16px; color: #eee; line-height: 1.6; }
    .hedge-box { background-color: rgba(46, 204, 113, 0.1); border-left: 4px solid #2ECC71; padding: 20px; font-size: 16px; color: #eee; margin-top: 5px; height: 100%; border-radius: 6px; line-height: 1.7; }
    .alpha-box { background-color: rgba(241, 196, 15, 0.1); border-left: 4px solid #F1C40F; padding: 20px; font-size: 16px; color: #eee; margin-top: 5px; height: 100%; border-radius: 6px; line-height: 1.7; }
    .log-item { margin-bottom: 15px; font-size: 16px; line-height: 1.7; color: #fff; padding-bottom: 15px; border-bottom: 1px dashed #555; }
</style>
""", unsafe_allow_html=True)

st.title("🏦 首席投资官中枢 (CIO Dashboard)")
st.caption("基于全局数据的全自动化配置组合：宏观概率分配 ➡️ 板块动量优选 ➡️ 龙头市值加权 ➡️ 净值回测")

# ==========================================
# 🧱 块级强覆盖区 (Page 6)：修复标的池缺失、数据源深度与板块映射
# ==========================================
# 解包所有的云端字典，特别是用户自选股(USER_GROUPS_DEF)和板块映射(SECTOR_MAP)
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})
SECTOR_MAP = core_data.get("SECTOR_MAP", {})
NARRATIVE_THEMES_HEAT = core_data.get("NARRATIVE_THEMES_HEAT", {})

MACRO_ASSETS = ["XLY", "XLP", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "XLK", "DBC"]

# 架构师级修复1：把主理人所有的自选股（A-E组）和宏观池全部加进来！否则漏斗无股可选！
all_pool_tickers = []
for lst in USER_GROUPS_DEF.values(): all_pool_tickers.extend(lst)
all_pool_tickers = list(set([t.strip().upper() for t in all_pool_tickers]))

UNIVERSAL_TICKERS = list(set(MACRO_ASSETS + all_pool_tickers + list(TIC_MAP.keys())))
UNIVERSAL_TICKERS.sort() 

with st.spinner("⏳ 正在调用中央引擎进行全系推演 (SSOT)..."):
    # 架构师级修复2：强制拉取 4 年数据对齐 Page 1！
    df = get_global_data(UNIVERSAL_TICKERS, years=4)
    meta_info = get_stock_metadata(all_pool_tickers)

if df.empty or len(df) < 750:
    st.warning("⚠️ 数据拉取失败或数据长度不足，无法启动配置引擎。")
    st.stop()

# ==========================================
# 🧠 强制同步 1_宏观定调.py 的三引擎计算逻辑，避免概率偏差 (SSOT)
# ==========================================
df_fred_clock = get_clock_fred_data()
_fred_ok = not df_fred_clock.empty
z_window = 750

def _zscore(series, window=z_window):
    mu = series.rolling(window=window).mean()
    sigma = series.rolling(window=window).std()
    return (series - mu) / sigma.where(sigma > 0)

z_consumer = _zscore((df['XLY'] / df['XLP'].replace(0, np.nan)).rolling(20).mean()) if 'XLY' in df and 'XLP' in df else pd.Series(0, index=df.index)
z_industrial = _zscore((df['XLI'] / df['XLU'].replace(0, np.nan)).rolling(20).mean()) if 'XLI' in df and 'XLU' in df else pd.Series(0, index=df.index)

if _fred_ok and 'HY_Spread' in df_fred_clock.columns:
    _hy_raw = df_fred_clock['HY_Spread'].reindex(df.index).ffill().rolling(20).mean()
    z_credit = _zscore(_hy_raw) * -1
else:
    _hy_raw = (df['HYG'] / df['IEF'].replace(0, np.nan)).rolling(20).mean() if 'HYG' in df and 'IEF' in df else pd.Series(0, index=df.index)
    z_credit = _zscore(_hy_raw)

growth_z = pd.DataFrame({'Z_consumer': z_consumer, 'Z_industrial': z_industrial, 'Z_credit': z_credit}).mean(axis=1)

z_tips = _zscore((df['TIP'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()) if 'TIP' in df and 'IEF' in df else pd.Series(0, index=df.index)
z_commodity = _zscore((df['DBC'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()) if 'DBC' in df and 'IEF' in df else pd.Series(0, index=df.index)

_infl_components = {'Z_tips': z_tips, 'Z_commodity': z_commodity}
if _fred_ok and 'Core_CPI_YoY' in df_fred_clock.columns:
    _cpi_raw = df_fred_clock['Core_CPI_YoY'].reindex(df.index).ffill()
    _infl_components['Z_cpi'] = _zscore(_cpi_raw)

inflation_z = pd.DataFrame(_infl_components).mean(axis=1)

df_z = pd.DataFrame({'Growth': growth_z, 'Inflation': inflation_z}).dropna()
curr_clock_g = float(df_z['Growth'].iloc[-1]) if not df_z.empty else 0.0
curr_clock_i = float(df_z['Inflation'].iloc[-1]) if not df_z.empty else 0.0

raw_probs, clock_regime = fetch_macro_scores(df, curr_clock_g, curr_clock_i)
df_scores, _ = fetch_funnel_scores(df, all_pool_tickers, meta_info, NARRATIVE_THEMES_HEAT, macro_scores=raw_probs)

REGIME_CN_MAP = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}

REGIME_NARRATIVE = {
    "软着陆": "享受经济复苏与流动性宽松的双重红利，充当组合的进攻矛。",
    "再通胀": "捕捉经济过热时期的需求扩张与大宗商品价格飙升带来的利润爆炸。",
    "滞胀": "作为终极避险资产，对冲法币信用贬值与经济停滞带来的杀估值风险。",
    "衰退": "充当无视周期的盈利安全垫，抵御大盘系统性下行的毁灭性冲击。"
}

active_regimes = {k: v for k, v in raw_probs.items() if v >= 0.60}
alloc_total = sum(active_regimes.values())
normalized_regime_weights = {k: v/alloc_total for k, v in active_regimes.items()} if alloc_total > 0 else {}

# ==========================================
# 💧 Water-Pouring Allocation Engine (正交性全天候配置)
# ==========================================
TIER_CAPS = {"A": 0.20, "B": 0.15, "C": 0.10, "D": 0.05}

step1_logs = []
portfolio = []

for regime_en, regime_cn in REGIME_CN_MAP.items():
    raw_w = raw_probs.get(regime_en, 0)
    is_active = regime_en in active_regimes
    norm_w = normalized_regime_weights.get(regime_en, 0)
    step1_logs.append({
        "宏观剧本": regime_cn,
        "原始信号强度": f"{raw_w*100:.0f}%",
        "激活状态": "✅ 纳入" if is_active else "❌ 剔除(<60%)",
        "归一化资金池": f"{norm_w*100:.1f}%"
    })

if not df_scores.empty and normalized_regime_weights:
    df_scores['Sector'] = df_scores.apply(lambda row: SECTOR_MAP.get(row['代码'], row.get('板块', '综合/未知')) if pd.isna(row.get('板块')) or row.get('板块') in ["未知", "", None] else row.get('板块'), axis=1)
    df_scores['Regime'] = df_scores['宏观属性']
    df_scores['Score']  = df_scores['Molt评分']
    df_scores['Ticker'] = df_scores['代码']
    df_qualified = df_scores[~df_scores['状态'].str.contains("🌋|❄️|⚠️")].copy() if '状态' in df_scores.columns else df_scores.copy()

    for regime_en, pool_weight in normalized_regime_weights.items():
        regime_cn = REGIME_CN_MAP.get(regime_en, regime_en)
        pool_remaining = pool_weight

        regime_stocks = df_qualified[
            (df_qualified['Regime'] == regime_en) &
            (df_qualified['Score'] >= 60)
        ].sort_values('Score', ascending=False).head(3)

        for _, row in regime_stocks.iterrows():
            if pool_remaining <= 0.001:
                break
            tier = str(row['Tier']) if 'Tier' in row.index and pd.notna(row['Tier']) else 'D'
            cap = TIER_CAPS.get(tier, 0.03)
            alloc = min(cap, pool_remaining)
            pool_remaining -= alloc

            ticker = row['Ticker']
            cn_name = TIC_MAP.get(ticker, ticker)
            molt = round(row['Score'], 1)
            attribution = (
                f"触发 {tier} 组 {cap*100:.0f}% 顶格上限"
                if alloc >= cap - 0.001
                else f"填满{regime_cn}池剩余 {alloc*100:.1f}% 额度"
            )
            portfolio.append({
                "宏观剧本池": regime_cn, "所属阵型": tier, "代码": ticker, "名称": cn_name,
                "Molt评分": molt, "分配仓位": round(alloc * 100, 2),
                "白盒归因": attribution, "所属板块": row['Sector']
            })

        if pool_remaining > 0.001:
            portfolio.append({
                "宏观剧本池": regime_cn, "所属阵型": "现金", "代码": "BIL", "名称": "极短债/现金等价物",
                "Molt评分": 0.0, "分配仓位": round(pool_remaining * 100, 2),
                "白盒归因": f"{regime_cn}池标的耗尽，剩余 {pool_remaining*100:.1f}% 强制转仓 BIL",
                "所属板块": "现金"
            })

df_portfolio = pd.DataFrame(portfolio)

st.header("1️⃣ 宏观市场定调 (Macro Climate)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟢 软着陆信号强度", f"{raw_probs['Soft']*100:.0f}%")
c2.metric("🔥 再通胀信号强度", f"{raw_probs['Hot']*100:.0f}%")
c3.metric("🟡 滞胀信号强度", f"{raw_probs['Stag']*100:.0f}%")
c4.metric("🔴 衰退信号强度", f"{raw_probs['Rec']*100:.0f}%")

dom_regime = max(raw_probs, key=raw_probs.get)
active_cn = [REGIME_CN_MAP.get(k, k) for k in active_regimes]
if active_cn:
    st.success(f"**CIO 洞察:** 信号强度 ≥ 60% 的存活剧本：**{'、'.join(active_cn)}**。配置引擎已对其概率归一化，切分独立资金池并执行注水填仓。")
else:
    st.warning("**CIO 洞察:** 当前宏观信号极度混乱，所有剧本胜率均不足 60%，建议保持现金观望。")

st.markdown("---")
st.header("2️⃣ 智能仓位生成引擎 (Allocation Engine)")

if not df_portfolio.empty:
    st.markdown("#### 🛠️ 步骤 1: 宏观剧本归一化 — 资金池切分 (Top-Down)")
    st.caption("踢除原始信号强度 < 60% 的废弃剧本，对剩余高胜率剧本概率归一化，使其总和等于 100%，每个剧本获得对应的独立资金池容量。")
    st.dataframe(pd.DataFrame(step1_logs), use_container_width=True, hide_index=True)

    st.markdown("#### 💧 步骤 2–3: 注水填仓算法 (Water-Pouring Allocation)")
    st.caption("以 Molt 评分从高到低依次注水，每笔仓位严格受 ABCD 阵型顶格上限约束 (A≤20% / B≤15% / C≤10% / D≤5%)。单池最多截取 Top 3 动量标的，剩余额度强制转仓 BIL 现金等价物。")

    col_chart, col_table = st.columns([1, 1.5])
    with col_chart:
        fig = px.pie(df_portfolio, values='分配仓位', names='代码',
                     hover_data=['名称', '所属板块', '宏观剧本池'],
                     hole=0.4, title="🎯 实战资金分配比例图",
                     color_discrete_sequence=px.colors.qualitative.Bold)
        fig.update_traces(textposition='inside', textinfo='percent+label', textfont_size=15)
        fig.update_layout(plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd', size=15), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        display_cols = ["宏观剧本池", "所属阵型", "代码", "Molt评分", "分配仓位", "白盒归因"]
        st.dataframe(
            df_portfolio[display_cols].sort_values(by="分配仓位", ascending=False),
            column_config={"分配仓位": st.column_config.NumberColumn("分配仓位 ▼", format="%.2f%%")},
            use_container_width=True, hide_index=True
        )
        
    st.markdown("---")
    
    st.markdown("#### 📈 步骤 4: 策略净值回测与收益归因 (1-Year Performance & Attribution)")
    st.caption("系统自动回滚过去252个交易日，计算当前组合的历史净值曲线，并向您白盒化拆解超额收益的来源与对冲抗跌的效果。")
    
    if 'SPY' in df.columns:
        df_1y = df.iloc[-252:].copy()
        df_1y['BIL'] = 100.0
        df_1y['CASH'] = 100.0

        # Aggregate duplicate tickers (same ticker may appear in multiple regime pools)
        df_bt = df_portfolio.groupby('代码')['分配仓位'].sum().reset_index()
        sel_tickers = df_bt['代码'].tolist()
        weights = (df_bt['分配仓位'] / 100.0).values

        daily_rets = df_1y[sel_tickers].pct_change().fillna(0)
        port_daily_ret = (daily_rets * weights).sum(axis=1)
        port_nav = (1 + port_daily_ret).cumprod() * 100
        
        spy_daily_ret = df_1y['SPY'].pct_change().fillna(0)
        spy_nav = (1 + spy_daily_ret).cumprod() * 100
        
        port_1y_ret = (port_nav.iloc[-1] / 100 - 1) * 100
        spy_1y_ret = (spy_nav.iloc[-1] / 100 - 1) * 100
        
        roll_max = port_nav.cummax()
        max_dd = ((port_nav / roll_max - 1) * 100).min()
        
        worst_dd = 0.0
        worst_ticker = ""
        for t in sel_tickers:
            if t in ("CASH", "BIL"): continue
            t_nav = (1 + daily_rets[t]).cumprod() * 100
            min_t_dd = ((t_nav / t_nav.cummax() - 1) * 100).min()
            if min_t_dd < worst_dd:
                worst_dd, worst_ticker = min_t_dd, t
        
        worst_name = TIC_MAP.get(worst_ticker, worst_ticker) if worst_ticker else "无"
        hedge_buffer = abs(worst_dd - max_dd)
        
        ind_1y_rets = (df_1y[sel_tickers].iloc[-1] / df_1y[sel_tickers].iloc[0] - 1) * 100
        contributions = ind_1y_rets * weights
        
        best_ticker = contributions.idxmax()
        best_contrib = contributions.max()
        best_abs_ret = ind_1y_rets[best_ticker]
        
        best_info = next((item for item in portfolio if item["代码"] == best_ticker), {"名称": best_ticker, "宏观剧本池": "—", "分配仓位": 0.0})
        best_name, best_regime, best_weight = best_info["名称"], best_info["宏观剧本池"], best_info["分配仓位"]
        
        c_r1, c_r2, c_r3, c_r4 = st.columns(4)
        c_r1.metric("组合近一年收益 (Portfolio)", f"{port_1y_ret:.1f}%", delta=f"{port_1y_ret - spy_1y_ret:.1f}% 超额收益")
        c_r2.metric("标普500基准 (SPY)", f"{spy_1y_ret:.1f}%")
        c_r3.metric("组合最大回撤 (Max DD)", f"{max_dd:.1f}%", delta="多剧本防御护城河", delta_color="off")
        c_r4.metric(f"单票极端回撤 ({worst_name})", f"{worst_dd:.1f}%", delta=f"避开单边暴跌缓冲 {hedge_buffer:.1f}%", delta_color="normal")
        
        fig_nav = go.Figure()
        fig_nav.add_trace(go.Scatter(x=df_1y.index, y=port_nav, mode='lines', name='Moltbot 动态组合 (Portfolio)', line=dict(color='#2ECC71', width=3)))
        fig_nav.add_trace(go.Scatter(x=df_1y.index, y=spy_nav, mode='lines', name='标普500基准 (SPY)', line=dict(color='#95A5A6', width=2, dash='dot')))
        fig_nav.update_layout(height=400, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd', size=14), margin=dict(l=20, r=20, t=20, b=20), yaxis_title="资产净值 (Base=100)", legend=dict(orientation="h", y=1.05, x=0.01))
        st.plotly_chart(fig_nav, use_container_width=True)
        
        c_alpha, c_hedge = st.columns(2)
        
        with c_alpha:
            if best_ticker == "CASH":
                alpha_text = "过去一年市场表现极差，没有任何强势资产。组合的绝对收益主要依靠【避险现金】在动荡中的安全留存。"
            elif port_1y_ret > spy_1y_ret:
                alpha_text = f"组合成功斩获 <b>{port_1y_ret - spy_1y_ret:.1f}%</b> 的超额收益，其核心引擎来自于【{best_regime}】剧本下的尖刀资产 —— <span style='color:#F1C40F'><b>{best_name} ({best_ticker})</b></span>。该标的在过去一年狂飙 <b>{best_abs_ret:.1f}%</b>，凭借 <b>{best_weight:.1f}%</b> 的底仓权重，单枪匹马为总组合贡献了 <b>{best_contrib:.1f}%</b> 的绝对净值增量！"
            else:
                alpha_text = f"过去一年组合防御属性较重，暂未跑赢大盘。但【{best_regime}】剧本下的 <span style='color:#F1C40F'><b>{best_name} ({best_ticker})</b></span> 依然逆势大涨 <b>{best_abs_ret:.1f}%</b>，单骑救主为组合贡献了 <b>{best_contrib:.1f}%</b> 的净值增量。"
                
            st.markdown(f"""
            <div class='alpha-box'>
            <h4 style='color:#F1C40F; margin-top:0px;'>👑 超额收益归因 (Alpha Source)</h4>
            {alpha_text}
            </div>
            """, unsafe_allow_html=True)

        with c_hedge:
            regimes_str = " + ".join(sorted(set(item['宏观剧本'] for item in step1_logs if "✅" in item['激活状态'])))
            st.markdown(f"""
            <div class='hedge-box'>
            <h4 style='color:#2ECC71; margin-top:0px;'>🛡️ 对冲保护归因 (Hedge Protection)</h4>
            如果盲目满仓押注单一主线（如遇黑天鹅，类似于成分股中跌幅最惨的 <span style='color:#E74C3C'><b>{worst_name}</b></span>），账户将面临高达 <span style='color:#E74C3C'><b>{worst_dd:.1f}%</b></span> 的毁灭性回撤。<br><br>
            而通过系统生成的<b>【{regimes_str}】</b>杠铃配置（包括现金留存保护），我们成功将整体回撤死死压缩在 <b>{max_dd:.1f}%</b>，为您强行抵御了 <b>{hedge_buffer:.1f}%</b> 的极端市场冲击。
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ 当前无符合条件的标的，建议空仓保护资本。")