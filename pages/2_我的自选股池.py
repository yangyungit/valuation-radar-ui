import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import numpy as np

# --- 架构师注释: 自选股池 v13.41 (极简 UI 降噪版 - 云端全解耦) ---
# 移除了数据漏斗表格中的“核心叙事”长文本列，提升信噪比。
# 彻底剥离本地 JSON 与算力，100% 依赖云端微服务。

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_funnel_scores

# 动态向云端 API 请求核心机密数据
core_data = fetch_core_data()

# 将 JSON 数据解包为全局变量供页面渲染
TIC_MAP = core_data.get("TIC_MAP", {})
ASSET_CN_DB = core_data.get("ASSET_CN_DB", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})
MACRO_TAGS_MAP = core_data.get("MACRO_TAGS_MAP", {})
SECTOR_MAP = core_data.get("SECTOR_MAP", {})
DEEP_INSIGHTS = core_data.get("DEEP_INSIGHTS", {})
NARRATIVE_THEMES_HEAT = core_data.get("NARRATIVE_THEMES_HEAT", {})
STOCK_NARRATIVE_MAP = core_data.get("STOCK_NARRATIVE_MAP", {})

st.set_page_config(page_title="超级自选雷达", layout="wide", page_icon="♟️")

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
# 🎛️ 侧边栏 UI 与 动态热度抓取
# ==========================================
with st.sidebar:
    st.header("🎯 战术筛选台")
    selected_groups_list = st.multiselect("📂 选择战术分组:", list(ALL_GROUPS.keys()), default=list(MACRO_GROUPS_DEF.keys())[0])
    
    st.markdown("---")
    st.header("🎛️ 宏观叙事方向盘")
    st.caption("为宏观事件赋分，底层关联个股将继承该叙事加成。")
    
    # 直接继承云端字典作为初始值
    df_heat = pd.DataFrame(list(NARRATIVE_THEMES_HEAT.items()), columns=["宏观主线/叙事", "热度(0-10)"])
    edited_heat_df = st.data_editor(
        df_heat, 
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "宏观主线/叙事": st.column_config.TextColumn("宏观主线/叙事", disabled=False),
            "热度(0-10)": st.column_config.NumberColumn("热度(0-10)", min_value=0.0, max_value=10.0, step=0.5)
        }
    )
    
    # 架构师重构：废弃无用的本地保存按钮，直接将表格里的最新数据打包成字典
    dynamic_theme_heat = dict(zip(edited_heat_df["宏观主线/叙事"], edited_heat_df["热度(0-10)"]))

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
    """获取格式化的公司名片与深度逻辑"""
    group_info = ASSET_CN_DB.get(ticker, "")
    base_name = TIC_MAP.get(ticker, ticker)
    
    summary = DEEP_INSIGHTS.get(
        ticker, 
        "💡 **【主理人批注】** 暂未录入该标的深度逻辑。<br><br>建议结合系统给出的**宏观剧本属性**与右侧的 **量化雷达** 盲评其动能与性价比进行右侧交易。"
    )
    
    return {"name": base_name, "summary": f"**{group_info}**\n\n{summary}"}

# ==========================================
# 核心渲染逻辑
# ==========================================
if not df_prices.empty:
    # 极简调用：将公开行情、股票池、前台修改的热度参数发送给后厨，换回打分表
    df_all, spy_mom = fetch_funnel_scores(df_prices, full_ticker_list, meta_data, dynamic_theme_heat)
    
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