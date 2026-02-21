import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import numpy as np
import json
import os

# --- 架构师注释: 自选股池 v13.41 (极简 UI 降噪版) ---
# 移除了数据漏斗表格中的“核心叙事”长文本列，提升信噪比。
# 叙事详情仅在选中的“深度归因”卡片中展示，表格仅保留纯粹的分数。

try:
    from core_engine import get_global_data, get_stock_metadata
    from my_stock_pool import TIC_MAP, ASSET_CN_DB, REGIME_MAP, USER_GROUPS_DEF, MACRO_TAGS_MAP, SECTOR_MAP
except ImportError:
    st.error("⚠️ 配置文件缺失，请检查项目结构。")
    st.stop()

st.set_page_config(page_title="超级自选雷达", layout="wide", page_icon="♟️")

# ==========================================
# 🗄️ 叙事热度持久化管理 (按主题)
# ==========================================
THEME_FILE = "theme_heat.json"

def load_theme_heat():
    if os.path.exists(THEME_FILE):
        with open(THEME_FILE, 'r') as f:
            return json.load(f)
    else:
        try:
            from my_stock_pool import NARRATIVE_THEMES_HEAT
            default_heat = NARRATIVE_THEMES_HEAT
        except:
            default_heat = {"⚪ 常规轮动(独立逻辑)": 3.0} 
        with open(THEME_FILE, 'w') as f:
            json.dump(default_heat, f)
        return default_heat

def save_theme_heat(data):
    with open(THEME_FILE, 'w') as f:
        json.dump(data, f)

current_theme_heat = load_theme_heat()

# ==========================================
# 基础定义
# ==========================================
MACRO_GROUPS_DEF = {
    "🟢 [剧本] 软着陆 (Soft)": MACRO_TAGS_MAP.get("Soft", []),
    "🔥 [剧本] 再通胀 (Hot)": MACRO_TAGS_MAP.get("Hot", []),
    "🟡 [剧本] 滞胀 (Stag)": MACRO_TAGS_MAP.get("Stag", []),
    "🔴 [剧本] 衰退 (Rec)": MACRO_TAGS_MAP.get("Rec", [])
}
ALL_GROUPS = {**USER_GROUPS_DEF, **MACRO_GROUPS_DEF}

all_default_tickers = []
for lst in USER_GROUPS_DEF.values(): all_default_tickers.extend(lst)
for t in REGIME_MAP.keys(): all_default_tickers.append(t)
full_ticker_list = list(set([t.strip().upper() for t in all_default_tickers]))

# ==========================================
# 🎛️ 侧边栏 UI
# ==========================================
with st.sidebar:
    st.header("🎯 战术筛选台")
    selected_groups_list = st.multiselect("📂 选择战术分组:", list(ALL_GROUPS.keys()), default=list(MACRO_GROUPS_DEF.keys())[0])
    
    st.markdown("---")
    st.header("🎛️ 宏观叙事方向盘")
    st.caption("为宏观事件赋分，底层关联个股将继承该叙事加成。")
    
    df_heat = pd.DataFrame(list(current_theme_heat.items()), columns=["宏观主线/叙事", "热度(0-10)"])
    edited_heat_df = st.data_editor(
        df_heat, 
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "宏观主线/叙事": st.column_config.TextColumn("宏观主线/叙事", disabled=False),
            "热度(0-10)": st.column_config.NumberColumn("热度(0-10)", min_value=0.0, max_value=10.0, step=0.5)
        }
    )
    
    if st.button("💾 保存叙事变动", use_container_width=True):
        new_heat_dict = dict(zip(edited_heat_df["宏观主线/叙事"], edited_heat_df["热度(0-10)"]))
        save_theme_heat(new_heat_dict)
        st.success("✅ 叙事热度已更新！")
        st.rerun()

    st.markdown("---")
    st.header("🛠️ 系统底层维护")
    if st.button("🔄 清理缓存并重新下载行情"):
        st.cache_data.clear()
        st.success("行情缓存已清除！")
        st.rerun()

st.markdown("""
<style>
    .formula-box { background-color: #1a1a1a; border-left: 4px solid #3498DB; padding: 18px; margin-top: 10px; margin-bottom: 20px; font-size: 15px; color: #eee; line-height: 1.7; border-radius: 4px; }
    .action-guide { background-color: rgba(231, 76, 60, 0.1); border-left: 4px solid #E74C3C; padding: 15px; margin-top: 5px; margin-bottom: 20px; font-size: 15px; color: #eee; border-radius: 4px; }
    [data-testid="stDataFrame"] { font-size: 14px !important; }
</style>
""", unsafe_allow_html=True)

st.title("♟️ 宏观对冲战术板 (Tactical Watchlist)")
st.caption("全景雷达 ➡️ **逻辑归因 (F10)** ➡️ **量化漏斗 (赛马机制与风控熔断)**")

with st.spinner("⏳ 正在同步中央厨房数据与计算引擎..."):
    df_prices = get_global_data(full_ticker_list, years=4)
    meta_data = get_stock_metadata(full_ticker_list)

def get_company_profile(ticker):
    try:
        from my_stock_pool import DEEP_INSIGHTS
    except ImportError:
        DEEP_INSIGHTS = {}

    group_info = ASSET_CN_DB.get(ticker, "")
    base_name = TIC_MAP.get(ticker, ticker)
    
    summary = DEEP_INSIGHTS.get(
        ticker, 
        "💡 **【主理人批注】** 暂未录入该标的深度逻辑。<br><br>建议结合系统给出的**宏观剧本属性**与右侧的 **量化雷达** 盲评其动能与性价比进行右侧交易。"
    )
    
    return {"name": base_name, "summary": f"**{group_info}**\n\n{summary}"}

def calculate_metrics(df_prices, tickers, meta_data, theme_heat_dict):
    try:
        from my_stock_pool import STOCK_NARRATIVE_MAP
    except ImportError:
        STOCK_NARRATIVE_MAP = {}
        
    try:
        spy_ts = df_prices['SPY'].dropna()
        spy_mom20 = (float(spy_ts.iloc[-1]) / float(spy_ts.iloc[-21]) - 1) * 100
    except: spy_mom20 = 0.0

    metrics = []
    for t in tickers:
        if t not in df_prices.columns: continue
        try:
            s = df_prices[t].dropna()
            if len(s) < 250: continue
            
            curr = float(s.iloc[-1])
            ma20 = float(s.rolling(20).mean().iloc[-1])
            ma60 = float(s.rolling(60).mean().iloc[-1])
            ma200 = float(s.rolling(200).mean().iloc[-1])
            ma250 = float(s.rolling(250).mean().iloc[-1])
            std250 = float(s.rolling(250).std().iloc[-1])
            
            ma60_support = ma60 * 0.97
            status = "🔥 主升浪" if curr > ma20 > ma60 > ma200 else ("❄️ 破位" if curr < ma60_support else "📈 多头")
            mom20 = (curr / float(s.iloc[-21]) - 1) * 100
            rs = mom20 - spy_mom20
            z_score = (curr - ma250) / std250 if std250 != 0 else 0.0
            
            daily_ret = s.pct_change().dropna()
            down_ret = daily_ret[daily_ret<0]
            sortino = (daily_ret.mean() * 252) / (down_ret.std() * np.sqrt(252)) if len(down_ret)>0 and down_ret.std()!=0 else 0.0
            if pd.isna(sortino) or np.isinf(sortino): sortino = 0.0
            
            roll_max = s.rolling(252, min_periods=1).max()
            max_dd = (s / roll_max - 1.0).min()

            risk = max(curr - ma60_support, curr * 0.03)
            rr = (float(s.rolling(120).max().iloc[-1]) - curr) / risk if risk > 0 else 0.0
            if pd.isna(rr) or np.isinf(rr): rr = 0.0
            
            mcap = meta_data.get(t, {}).get("mcap", 1e10)
            if mcap is None or mcap < 1e9: mcap = 1e9
            
            log_mc = np.log10(mcap)
            size_bonus = min(max((log_mc - 9) / 3.5 * 10, 0), 10)
            
            if "主升" in status:
                score_mom = 20.0 + size_bonus 
            elif "多头" in status:
                score_mom = 10.0 + (size_bonus * 0.5) 
            else:
                score_mom = 0.0
                
            score_sortino = min(max(sortino, 0), 3) * 13.33 
            score_rr = min(max(rr, 0), 3) * 6.66            
            
            stock_theme = STOCK_NARRATIVE_MAP.get(t, "⚪ 常规轮动(独立逻辑)")
            score_narrative = float(theme_heat_dict.get(stock_theme, 3.0)) 
            
            score = score_mom + score_sortino + score_rr + score_narrative
            
            threshold = 80.0
            bias_250_pct = (curr / ma250 - 1) * 100 if ma250 > 0 else 0.0
            
            if bias_250_pct > threshold:
                score -= 20
                status = "🌋 严重泡沫 (熔断)"
                elimination_reason = f"触发年线熔断(-20分)"
            elif curr < ma60_support:  
                elimination_reason = "动量破位(失守防守底线)"
            elif sortino < 1.0:
                elimination_reason = "历史抗跌差(Sortino低)"
            elif rr < 0.5:
                elimination_reason = "入场性价比差(盈亏比偏低)"
            else:
                elimination_reason = "综合得分不及格(总分<60)"
            
            cn_name = TIC_MAP.get(t, t)
            metrics.append({
                "代码": t, "名称": cn_name, 
                "板块": SECTOR_MAP.get(t, "-"),
                "显示标签": f"{cn_name}", 
                "现价": curr, "状态": status, "相对强度": rs, "Z-Score": z_score,
                "宏观属性": REGIME_MAP.get(t, "Other"), "Molt评分": round(score, 1),
                "核心叙事": stock_theme,  # 仍然保留在数据中供顶部深度归因面板使用
                "叙事(10分)": round(score_narrative, 1),
                "动能(30分)": round(score_mom, 1),
                "索提诺(40分)": round(score_sortino, 1),
                "盈亏比(20分)": round(score_rr, 1),
                "最大回撤": f"{max_dd*100:.1f}%", 
                "年线乖离": f"{bias_250_pct:.1f}%", 
                "Raw_Bias": bias_250_pct, "淘汰死因": elimination_reason
            })
        except: continue
        
    return pd.DataFrame(metrics), spy_mom20

if not df_prices.empty:
    df_all, spy_mom = calculate_metrics(df_prices, full_ticker_list, meta_data, current_theme_heat)
    if not df_all.empty:
        df_all["相对强度"] = df_all["相对强度"].astype(float)
        df_all["Z-Score"] = df_all["Z-Score"].astype(float)

        if len(selected_groups_list) == 0:
            df_display = pd.DataFrame(columns=df_all.columns)
        else:
            target_tickers_subset = []
            for g in selected_groups_list: 
                target_tickers_subset.extend(ALL_GROUPS.get(g, []))
            target_tickers_subset = list(set(target_tickers_subset))
            df_display = df_all[df_all['代码'].isin(target_tickers_subset)]
        
        st.subheader(f"📡 战术雷达 (SPY 基准: {spy_mom:.1f}%)")
        if not df_display.empty:
            fig = px.scatter(
                df_display, x="Z-Score", y="相对强度", color="相对强度", text="显示标签", 
                hover_data=["代码", "状态", "板块", "核心叙事", "Molt评分"], 
                color_continuous_scale="RdYlGn", range_color=[-10, 10]
            )
            fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            fig.add_vline(x=0, line_dash="dash", line_color="white", opacity=0.3)
            fig.update_layout(height=550, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd', size=14))
            fig.update_traces(textposition='top center', marker=dict(size=14), textfont=dict(size=14))
            st.plotly_chart(fig, use_container_width=True)
        else: st.info("⚠️ 当前未选择任何标签，或所选标签下无数据。")

        st.markdown("---")
        st.header("💡 核心逻辑归因 (Deep Insight)")
        df_display['Select_Label'] = df_display['代码'] + " | " + df_display['名称']
        select_box_options = df_display['Select_Label'].unique() if not df_display.empty else []
        selected_label = st.selectbox("👉 选中标的查看资料:", select_box_options)
        
        if selected_label:
            selected_ticker = selected_label.split(" | ")[0]
            row = df_display[df_display['代码'] == selected_ticker].iloc[0]
            regime = row['宏观属性']
            profile = get_company_profile(selected_ticker)
            
            if regime == "Soft": adaptation = "🟢 适配软着陆"
            elif regime == "Hot": adaptation = "🔥 适配再通胀"
            elif regime == "Stag": adaptation = "🟡 适配滞胀"
            elif regime == "Rec": adaptation = "🔴 适配衰退"
            else: adaptation = "⚪ 中性/独立"
                
            c_info, c_logic = st.columns([2, 3])
            with c_info:
                st.markdown(f"#### 🏢 {profile['name']} ({selected_ticker})")
                st.info(f"**【主营业务与深度研报】**\n\n{profile['summary']}")
            with c_logic:
                st.markdown(f"#### 🧠 交易逻辑 (含叙事加成)")
                st.metric("核心主属性", adaptation)
                status_color = "green" if "主升" in row['状态'] else "red" if "破位" in row['状态'] or "熔断" in row['状态'] else "orange"
                st.markdown(f":{status_color}[**当前状态: {row['状态']}**]")
                st.write(f"客观板块: **{row['板块']}** | 总评分: **{row['Molt评分']}** | RS: **{row['相对强度']:.1f}**")
                st.caption(f"🔥 当前标的受主观叙事【{row['核心叙事']}】赋能，获得加成：**{row['叙事(10分)']} / 10**")

        st.markdown("---")
        st.header("🌪️ 量化漏斗筛选 (Quantitative Funnel)")
        
        st.markdown("""
        <div class='formula-box'>
        <h4 style='color:#3498DB; margin-top:0px; margin-bottom:15px;'>⚙️ 漏斗核心法则 (Molt Score = 100)：30-40-20-10 叙事霸权模型</h4>
        <b>1. 📈 第一维度：市值穿透动能 (满分 30分) —— 大象起舞 (质量×速度)</b><br>
        <span style='color:#bbb;'>
        · 🔥 <b>主升浪 (最高 30分)</b>：基础分 20分 + 市值对数附加分 (最高 10分)。体量越大的巨无霸爆发的确定性越强，资金推力得分越高。<br>
        · ❄️ <b>破位 (0分)</b>：跌破 60日均线支撑位超 3%。防线彻底失守，动量清零。<br>
        </span><br>
        <b>2. 🛡️ 第二维度：索提诺比率 Sortino (满分 40分) —— 偏长周期防守</b><br>
        <span style='color:#bbb;'>向历史深处拉取长达 4 年的数据，严厉惩罚下行波动。赋予最核心防御权重，只过滤护城河标的。</span><br><br>
        <b>3. ⚖️ 第三维度：图表盈亏比 R:R (满分 20分) —— 平衡安全边际</b><br>
        <span style='color:#bbb;'>以过去半年最高点为阻力，以 60 日均线为底线，确保在不过分惩罚创新高资产的前提下防盲目追尾。</span><br><br>
        <b>4. 🔥 第四维度：主线事件驱动 (满分 10分) —— <span style='color:#F1C40F'>主理人动态调控</span></b><br>
        <span style='color:#bbb;'>请在左侧【宏观叙事方向盘】中调节当前全球宏观事件的热度。个股将通过底层字典自动绑定并继承对应事件的分数！</span><br><br>
        <b style='color:#E74C3C;'>🛑 全域年线乖离熔断机制 (防泡沫追高)</b><br>
        <span style='color:#E74C3C;'>如果当前价格距离 250 日均线向上偏离超过 <b>80%</b>，直接扣减 20 分踢入淘汰区！</span>
        </div>
        """, unsafe_allow_html=True)
        
        if not df_display.empty:
            funnel_df = df_display.sort_values("Molt评分", ascending=False)
            
            # 【UI降噪】：从晋级区和淘汰区表格的列显示顺序中，剔除占位过大的“核心叙事”列
            cols_order_qualified = ["代码", "名称", "板块", "Molt评分", "状态", "叙事(10分)", "动能(30分)", "索提诺(40分)", "盈亏比(20分)", "最大回撤"]
            cols_order_eliminated = ["代码", "名称", "板块", "淘汰死因", "Molt评分", "状态", "叙事(10分)", "动能(30分)", "索提诺(40分)", "盈亏比(20分)"]
            
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("🏆 晋级区 (Score > 60)")
                qualified_df = funnel_df[funnel_df['Molt评分'] >= 60]
                if not qualified_df.empty: 
                    st.dataframe(
                        qualified_df, 
                        use_container_width=True, hide_index=True, column_order=cols_order_qualified
                    )
                else: st.write("暂无达标资产")
            with c2:
                st.subheader("🗑️ 淘汰/观察区")
                eliminated_df = funnel_df[funnel_df['Molt评分'] < 60]
                eliminated_df = eliminated_df.sort_values("Molt评分", ascending=False)
                if not eliminated_df.empty: 
                    st.dataframe(
                        eliminated_df, 
                        use_container_width=True, hide_index=True, column_order=cols_order_eliminated
                    )
                else: st.write("暂无淘汰资产")
else: st.info("⏳ 正在初始化数据...")