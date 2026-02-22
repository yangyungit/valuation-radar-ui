import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_macro_scores, fetch_funnel_scores

core_data = fetch_core_data()

# 解包页面需要的字典
TIC_MAP = core_data.get("TIC_MAP", {})

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

MACRO_ASSETS = ["XLY", "XLP", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "XLK"]

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

raw_probs, clock_regime = fetch_macro_scores(df)
df_scores, _ = fetch_funnel_scores(df, all_pool_tickers, meta_info, NARRATIVE_THEMES_HEAT, macro_scores=raw_probs)

REGIME_CN_MAP = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}

REGIME_NARRATIVE = {
    "软着陆": "享受经济复苏与流动性宽松的双重红利，充当组合的进攻矛。",
    "再通胀": "捕捉经济过热时期的需求扩张与大宗商品价格飙升带来的利润爆炸。",
    "滞胀": "作为终极避险资产，对冲法币信用贬值与经济停滞带来的杀估值风险。",
    "衰退": "充当无视周期的盈利安全垫，抵御大盘系统性下行的毁灭性冲击。"
}

active_regimes = {k: v for k, v in raw_probs.items() if v >= 0.4}
alloc_total = sum(active_regimes.values())
normalized_regime_weights = {k: v/alloc_total for k, v in active_regimes.items()} if alloc_total > 0 else {}

step1_logs = []
step2_logs = []
portfolio = []
reasoning_logs = [] 

if not df_scores.empty and normalized_regime_weights:
    # 架构师级修复3：强制挂载中文板块！如果云端没返回，就用 SECTOR_MAP 兜底！
    df_scores['Sector'] = df_scores.apply(lambda row: SECTOR_MAP.get(row['代码'], row.get('板块', '综合/未知')) if pd.isna(row.get('板块')) or row.get('板块') in ["未知", "", None] else row.get('板块'), axis=1)       
    df_scores['Regime'] = df_scores['宏观属性']   
    df_scores['Score']  = df_scores['Molt评分']   
    df_scores['Ticker'] = df_scores['代码']       
    df_scores['MCAP']   = df_scores['代码'].map(lambda x: meta_info.get(x, {}).get('mcap', 1e9))
    
    # V14：淘汰死因包含特定关键词的标的被剔除
    df_qualified = df_scores[~df_scores['状态'].str.contains("🌋|❄️|⚠️")].copy() if '状态' in df_scores.columns else df_scores.copy()
# ==========================================
# 🧱 V14 宏观降维打击与分级精排
# ==========================================
    dom_regime = max(raw_probs, key=raw_probs.get) if raw_probs else "Soft"
    dom_regime_cn = REGIME_CN_MAP.get(dom_regime, dom_regime)

    ALLOCATION_MAP = {
        "Soft": {"A": 0.10, "B": 0.20, "C": 0.50, "D": 0.20}, # 复苏期(软着陆)：C占主导，进攻
        "Hot":  {"A": 0.05, "B": 0.25, "C": 0.40, "D": 0.30}, # 再通胀：C和D主导，极度进攻
        "Stag": {"A": 0.40, "B": 0.40, "C": 0.15, "D": 0.05}, # 滞胀：A和B主导，防御+抗通胀
        "Rec":  {"A": 0.70, "B": 0.20, "C": 0.10, "D": 0.00}  # 衰退：A占绝对主导，极度防守
    }
    
    tier_weights = ALLOCATION_MAP.get(dom_regime, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    
    step1_logs.append({
        "当前主导宏观剧本": dom_regime_cn, 
        "剧本确信度": f"{raw_probs.get(dom_regime, 0)*100:.0f}%", 
        "资金天平 (A:B:C:D)": f"{tier_weights['A']*100:.0f}% : {tier_weights['B']*100:.0f}% : {tier_weights['C']*100:.0f}% : {tier_weights['D']*100:.0f}%"
    })
    
    for tier, weight in tier_weights.items():
        if weight <= 0: continue
        
        tier_stocks = df_qualified[df_qualified['Tier'] == tier].copy() if 'Tier' in df_qualified.columns else pd.DataFrame()
        
        if tier_stocks.empty: 
            step2_logs.append({"归属剧本": dom_regime_cn, "突围板块": f"{tier}级防守", "板块最高动量(Molt)": 0.0})
            alloc_pct = weight * 100
            portfolio.append({
                "宏观剧本": dom_regime_cn, "所属板块": "现金/短债", "标的代码": "CASH",
                "名称": f"{tier}级避险现金", "市值规模": 1e12, 
                "Molt评分": 0.0, "配置仓位": alloc_pct 
            })
            narrative = f"🛑 <b>风控归因 [{tier}级空仓现金]：</b> 当前【{dom_regime_cn}】剧本为 {tier} 级资产分配了 {alloc_pct:.0f}% 仓位，但在执行底层漏斗扫描时，发现该级别的所有候选资产均已触发估值熔断或动量破位。系统拒绝高位接盘，强制截留为现金防守。"
            reasoning_logs.append(narrative)
            continue
            
        # V14：直接取该 Tier 得分最高的前两名
        top_stocks = tier_stocks.sort_values('Score', ascending=False).head(2)
        top_names = [f"{row['Ticker']}({row['Score']:.1f})" for _, row in top_stocks.iterrows()]
        step2_logs.append({"归属剧本": dom_regime_cn, "突围板块": f"{tier} 级精选", "板块最高动量(Molt)": round(top_stocks['Score'].max(), 1)})
        
        total_mcap = top_stocks['MCAP'].sum()
        
        for _, row in top_stocks.iterrows():
            stock_weight = weight * (row['MCAP'] / total_mcap) if total_mcap > 0 else weight / len(top_stocks)
            ticker = row['Ticker']
            cn_name = TIC_MAP.get(ticker, ticker)
            molt = round(row['Score'], 1)
            alloc_pct = stock_weight * 100
            
            portfolio.append({
                "宏观剧本": dom_regime_cn, "所属板块": row['Sector'], "标的代码": ticker,
                "名称": cn_name, "市值规模": row['MCAP'], 
                "Molt评分": molt, "配置仓位": alloc_pct 
            })
            
            narrative = f"🎯 <b>选股归因 [{ticker} {cn_name}] ({tier}级)：</b> 系统在【{dom_regime_cn}】宏观水温下，为 {tier} 级生态位注入资金。该标的凭借 <b>{molt} 分</b> 的同级最高评分脱颖而出，成功斩获 <b>{alloc_pct:.1f}%</b> 的实战仓位。"
            reasoning_logs.append(narrative)

df_portfolio = pd.DataFrame(portfolio)
if not df_portfolio.empty:
    df_portfolio['配置仓位'] = (df_portfolio['配置仓位'] / df_portfolio['配置仓位'].sum()) * 100
    reasoning_logs_sorted = [log for _, log in sorted(zip(df_portfolio['配置仓位'], reasoning_logs), reverse=True)]

st.header("1️⃣ 宏观市场定调 (Macro Climate)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟢 软着陆信号强度", f"{raw_probs['Soft']*100:.0f}%")
c2.metric("🔥 再通胀信号强度", f"{raw_probs['Hot']*100:.0f}%")
c3.metric("🟡 滞胀信号强度", f"{raw_probs['Stag']*100:.0f}%")
c4.metric("🔴 衰退信号强度", f"{raw_probs['Rec']*100:.0f}%")

dom_regime = max(raw_probs, key=raw_probs.get)
if raw_probs[dom_regime] >= 0.4:
    st.success(f"**CIO 洞察:** 当前系统检测到 **{REGIME_CN_MAP.get(dom_regime)}** 特征最显著。资产配置引擎已自动将信号强度 ≥ 40% 的剧本投入下列推演引擎。")
else:
    st.warning("**CIO 洞察:** 当前宏观信号极度混乱，所有剧本胜率均不足 40%，建议保持现金观望。")

st.markdown("---")
st.header("2️⃣ 智能仓位生成引擎 (Allocation Engine)")

if not df_portfolio.empty:
    st.markdown("#### 🛠️ 步骤 1: 宏观剧本归一化 (Top-Down)")
    st.caption("剔除弱势剧本，将剩余高胜率剧本的概率重新按比例分配，决定大类的资金池底仓权重。")
    st.dataframe(pd.DataFrame(step1_logs), use_container_width=True, hide_index=True, 
                 column_config={"分配底仓权重": st.column_config.NumberColumn(format="%.1f%%")})
    
    st.markdown("#### 🛠️ 步骤 2: 细分板块突围 (Sector Scan)")
    st.caption("在入选剧本对应的晋级区 (Molt≥60) 股票中，提取出资金动量最强的 Top 2 细分行业。（注：若某剧本全军覆没，将强转现金防守）")
    st.dataframe(pd.DataFrame(step2_logs), use_container_width=True, hide_index=True)

    st.markdown("#### 🎯 步骤 3: 最终推荐配置 (Bottom-Up 龙头加权)")
    st.caption("在突围行业中，选取分数最高的 Top 2 个股，依据其市值大小 (Market Cap) 瓜分该行业的资金比例。")
    
    col_chart, col_table = st.columns([1, 1.5])
    with col_chart:
        fig = px.pie(df_portfolio, values='配置仓位', names='标的代码', color='宏观剧本', hover_data=['名称', '所属板块'], hole=0.4, title="🎯 实战资金分配比例图")
        fig.update_traces(textposition='inside', textinfo='percent+label', textfont_size=15)
        fig.update_layout(plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd', size=15), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        
    with col_table:
        st.dataframe(
            df_portfolio.drop(columns=['市值规模']).sort_values(by="配置仓位", ascending=False), 
            column_config={"配置仓位": st.column_config.NumberColumn("配置仓位 ▼", format="%.1f%%", help="点击表头可重新排序")},
            use_container_width=True, hide_index=True
        )
        
    with st.expander("🧠 查看 AI 选股归因深度推演录 (AI Reasoning Logs)", expanded=True):
        for log in reasoning_logs_sorted:
            st.markdown(f"<div class='log-item'>{log}</div>", unsafe_allow_html=True)
        
    st.markdown("---")
    
    st.markdown("#### 📈 步骤 4: 策略净值回测与收益归因 (1-Year Performance & Attribution)")
    st.caption("系统自动回滚过去252个交易日，计算当前组合的历史净值曲线，并向您白盒化拆解超额收益的来源与对冲抗跌的效果。")
    
    if 'SPY' in df.columns:
        df_1y = df.iloc[-252:].copy()
        df_1y['CASH'] = 100.0 
        
        sel_tickers = df_portfolio['标的代码'].tolist()
        weights = (df_portfolio['配置仓位'] / 100.0).values
        
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
            if t == "CASH": continue 
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
        
        best_info = next(item for item in portfolio if item["标的代码"] == best_ticker)
        best_name, best_regime, best_weight = best_info["名称"], best_info["宏观剧本"], best_info["配置仓位"]
        
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
            regimes_str = " + ".join(list(set(item['当前主导宏观剧本'] for item in step1_logs)))
            st.markdown(f"""
            <div class='hedge-box'>
            <h4 style='color:#2ECC71; margin-top:0px;'>🛡️ 对冲保护归因 (Hedge Protection)</h4>
            如果盲目满仓押注单一主线（如遇黑天鹅，类似于成分股中跌幅最惨的 <span style='color:#E74C3C'><b>{worst_name}</b></span>），账户将面临高达 <span style='color:#E74C3C'><b>{worst_dd:.1f}%</b></span> 的毁灭性回撤。<br><br>
            而通过系统生成的<b>【{regimes_str}】</b>杠铃配置（包括现金留存保护），我们成功将整体回撤死死压缩在 <b>{max_dd:.1f}%</b>，为您强行抵御了 <b>{hedge_buffer:.1f}%</b> 的极端市场冲击。
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ 当前无符合条件的标的，建议空仓保护资本。")