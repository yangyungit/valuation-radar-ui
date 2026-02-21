import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_macro_scores, fetch_funnel_scores

core_data = fetch_core_data()

# 解包页面需要的字典
TIC_MAP = core_data.get("TIC_MAP", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})

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

MACRO_ASSETS = ["XLY", "XLP", "TIP", "IEF", "TLT", "SHY", "HYG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "VLUE", "MTUM", "XLK"]
all_pool_tickers = list(REGIME_MAP.keys())
FULL_TICKERS = list(set(MACRO_ASSETS + all_pool_tickers))

with st.spinner("⏳ 正在调用中央引擎进行全系推演..."):
    df = get_global_data(FULL_TICKERS)

if df.empty or len(df) < 750:
    st.warning("⚠️ 数据拉取失败或数据长度不足，无法启动配置引擎。")
    st.stop()

raw_probs, clock_regime = fetch_macro_scores(df)
df_scores, _ = fetch_funnel_scores(df, all_pool_tickers, {}, {})

REGIME_CN_MAP = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
SECTOR_CN_MAP = {
    "Technology": "科技", "Industrials": "工业", "Financial Services": "金融服务", 
    "Healthcare": "医疗保健", "Consumer Cyclical": "可选消费", "Consumer Defensive": "必选消费", 
    "Utilities": "公用事业", "Energy": "能源", "Real Estate": "房地产", 
    "Basic Materials": "基础材料", "Communication Services": "通讯服务", 
    "ETF/宏观资产": "ETF/宏观资产", "未知": "未知"
}

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
    meta_info = get_stock_metadata(all_pool_tickers)
    
    # 【架构师修复】：不仅要映射 Sector，必须补回 MCAP（市值）映射！
    df_scores['Sector'] = df_scores['Ticker'].map(lambda x: SECTOR_CN_MAP.get(meta_info.get(x, {}).get('sector', '未知'), '未知'))
    df_scores['MCAP'] = df_scores['Ticker'].map(lambda x: meta_info.get(x, {}).get('mcap', 1e9))
    
    df_qualified = df_scores[df_scores['Score'] >= 60] 
    
    for regime, r_weight in normalized_regime_weights.items():
        regime_cn = REGIME_CN_MAP.get(regime, regime)
        step1_logs.append({"入选剧本": regime_cn, "原始胜率": f"{raw_probs[regime]*100:.0f}%", "分配底仓权重": r_weight * 100})
        
        regime_stocks = df_qualified[df_qualified['Regime'] == regime].copy()
        
        if regime_stocks.empty: 
            step2_logs.append({"归属剧本": regime_cn, "突围板块": "🛡️ 现金防守", "板块最高动量(Molt)": 0.0})
            alloc_pct = r_weight * 100
            portfolio.append({
                "宏观剧本": regime_cn, "所属板块": "现金/短债", "标的代码": "CASH",
                "名称": "避险现金", "市值规模": 1e12, 
                "Molt评分": 0.0, "配置仓位": alloc_pct 
            })
            narrative = f"🛑 <b>风控归因 [CASH 避险现金]：</b> 系统虽以 {raw_probs[regime]*100:.0f}% 的确信度确认了<b>【{regime_cn}】</b>风险，但在执行底层漏斗扫描时，发现该剧本下的候选资产均已触发【🌋估值熔断】或动量破位。基于严格的资管风控法则，系统拒绝高位接盘，强制将这笔 <b>{alloc_pct:.1f}%</b> 的仓位截留为现金防守。<b>战略意义：</b>保留子弹，规避高位泡沫破裂带来的回撤，等待均值回归后捡拾带血筹码。"
            reasoning_logs.append(narrative)
            continue
            
        sector_scores = regime_stocks.groupby('Sector')['Score'].max().sort_values(ascending=False)
        top_2_sectors = sector_scores.head(2).index.tolist()
        
        for sector in top_2_sectors:
            step2_logs.append({"归属剧本": regime_cn, "突围板块": sector, "板块最高动量(Molt)": round(sector_scores[sector], 1)})
            
            sector_weight = r_weight / len(top_2_sectors)
            sector_stocks = regime_stocks[regime_stocks['Sector'] == sector].sort_values('Score', ascending=False).head(2)
            total_mcap = sector_stocks['MCAP'].sum()
            
            all_comp_df = df_scores[(df_scores['Regime'] == regime) & (df_scores['Sector'] == sector)].sort_values('Score', ascending=False)
            comp_list = all_comp_df['Ticker'].tolist()
            
            for _, row in sector_stocks.iterrows():
                stock_weight = sector_weight * (row['MCAP'] / total_mcap) if total_mcap > 0 else sector_weight / len(sector_stocks)
                ticker = row['Ticker']
                cn_name = TIC_MAP.get(ticker, ticker)
                molt = round(row['Score'], 1)
                alloc_pct = stock_weight * 100
                
                portfolio.append({
                    "宏观剧本": regime_cn, "所属板块": sector, "标的代码": ticker,
                    "名称": cn_name, "市值规模": row['MCAP'], 
                    "Molt评分": molt, "配置仓位": alloc_pct 
                })
                
                try:
                    my_idx = comp_list.index(ticker)
                    defeated_list = comp_list[my_idx+1:]
                except:
                    defeated_list = []
                    my_idx = 0
                    
                if defeated_list:
                    d_names = [f"{p} {TIC_MAP.get(p, p)}" for p in defeated_list[:2]]
                    d_str = "、".join(d_names)
                    if len(defeated_list) > 2: d_str += " 等"
                    defeat_text = f"击败了同生态位的 <span style='color:#95A5A6'><b>[{d_str}]</b></span> 竞争者"
                elif my_idx > 0:
                    boss = comp_list[0]
                    defeat_text = f"紧随龙头 <span style='color:#F1C40F'><b>[{boss} {TIC_MAP.get(boss, boss)}]</b></span> 携手突围"
                else:
                    defeat_text = "作为该生态位下唯一达标的稀缺标的，一枝独秀"
                
                narrative = f"🎯 <b>选股归因 [{ticker} {cn_name}]：</b> 系统以 {raw_probs[regime]*100:.0f}% 的高确信度确认了<b>【{regime_cn}】</b>风险，并在华尔街数据库中锁定该环境下动能最强的<b>【{sector}】</b>板块。在内部量化赛马中，该标的凭借 <b>{molt} 分</b> 的强悍多头均线与极佳的抗跌索提诺比率脱颖而出，{defeat_text}，成功斩获 <b>{alloc_pct:.1f}%</b> 的实战仓位。<b>战略意义：</b>{REGIME_NARRATIVE.get(regime_cn, '增强组合护城河')}。"
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
            regimes_str = " + ".join(list(set(item['入选剧本'] for item in step1_logs)))
            st.markdown(f"""
            <div class='hedge-box'>
            <h4 style='color:#2ECC71; margin-top:0px;'>🛡️ 对冲保护归因 (Hedge Protection)</h4>
            如果盲目满仓押注单一主线（如遇黑天鹅，类似于成分股中跌幅最惨的 <span style='color:#E74C3C'><b>{worst_name}</b></span>），账户将面临高达 <span style='color:#E74C3C'><b>{worst_dd:.1f}%</b></span> 的毁灭性回撤。<br><br>
            而通过系统生成的<b>【{regimes_str}】</b>杠铃配置（包括现金留存保护），我们成功将整体回撤死死压缩在 <b>{max_dd:.1f}%</b>，为您强行抵御了 <b>{hedge_buffer:.1f}%</b> 的极端市场冲击。
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ 当前无符合条件的标的，建议空仓保护资本。")