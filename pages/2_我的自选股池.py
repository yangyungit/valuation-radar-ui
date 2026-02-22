import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import numpy as np

# --- 架构师注释: 自选股池 v13.41 (极简 UI 降噪版 - 云端全解耦) ---
# 移除了数据漏斗表格中的“核心叙事”长文本列，提升信噪比。
# 彻底剥离本地 JSON 与算力，100% 依赖云端微服务。

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_funnel_scores, fetch_macro_scores

# 动态向云端 API 请求核心机密数据
core_data = fetch_core_data()

# 将 JSON 数据解包为全局变量供页面渲染
TIC_MAP = core_data.get("TIC_MAP", {})
ASSET_CN_DB = core_data.get("ASSET_CN_DB", {})
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
all_default_tickers = []
for lst in USER_GROUPS_DEF.values(): all_default_tickers.extend(lst)
full_ticker_list = list(set([t.strip().upper() for t in all_default_tickers]))

# ==========================================
# 🎛️ 侧边栏 UI 与 动态热度抓取
# ==========================================
with st.sidebar:
    st.header("🎯 资产分级雷达")
    tier_options = {
        "A": "A级 (压舱石/防守)",
        "B": "B级 (大猩猩/基石)",
        "C": "C级 (时代之王/主升)",
        "D": "D级 (预备队/异动)"
    }
    selected_tiers = st.multiselect("📂 选择要查看的分级池:", list(tier_options.keys()), default=["C", "D"], format_func=lambda x: tier_options[x])
    
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
    raw_probs, clock_regime = fetch_macro_scores(df_prices)

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
    # 极简调用：将公开行情、股票池、前台修改的热度参数及宏观打分发送给后厨，换回分级打分表
    df_all, spy_mom = fetch_funnel_scores(df_prices, full_ticker_list, meta_data, dynamic_theme_heat, macro_scores=raw_probs)
    
    if not df_all.empty:
        df_all["相对强度"] = df_all["相对强度"].astype(float)
        df_all["Z-Score"] = df_all["Z-Score"].astype(float)

        if len(selected_tiers) == 0 or 'Tier' not in df_all.columns:
            df_display = pd.DataFrame(columns=df_all.columns)
        else:
            df_display = df_all[df_all['Tier'].isin(selected_tiers)]
        
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
        <h4 style='color:#3498DB; margin-top:0px; margin-bottom:15px;'>⚙️ V14 动态分拣与独立排名引擎（ABCD 全景看板）</h4>
        <b>1. 🛡️ A级 (压舱石)：</b> 屏蔽短期动能，只看历史最大回撤、长周期索提诺与股息/市值防守。<br>
        <b>2. 🦍 B级 (核心基石)：</b> 关注市值网络效应、长线多头排列与索提诺比率。<br>
        <b>3. 🚀 C级 (时代之王)：</b> 核心看宏观共振（必须匹配当前第一剧本）、中期主升浪动能与叙事热度。<br>
        <b>4. 🔥 D级 (预备队)：</b> 纯粹的右侧动量投机，看重短期爆发力与盈亏比。<br><br>
        <span style='color:#E74C3C;'>🛑 <b>防抖动与降级机制：</b>系统在后端内存中记录了股票的连续达标天数。只有连续 3 天满足条件才能升级/入选，一旦破位立刻打入冷宫！</span>
        </div>
        """, unsafe_allow_html=True)
        
        if not df_display.empty:
            funnel_df = df_display.sort_values("Molt评分", ascending=False)
            
            # 区分晋级与淘汰
            if '状态' in funnel_df.columns:
                qualified_df = funnel_df[~funnel_df['状态'].str.contains("🌋|❄️|⚠️")]
                eliminated_df = funnel_df[funnel_df['状态'].str.contains("🌋|❄️|⚠️")]
            else:
                qualified_df = funnel_df
                eliminated_df = pd.DataFrame()

            st.subheader("📊 ABCD 动态全景看板 (晋级区)")
            col_a, col_b, col_c, col_d = st.columns(4)
            
            def render_tier(col, title, tier, df, display_cols):
                with col:
                    st.markdown(f"**{title}**")
                    tier_df = df[df['Tier'] == tier] if 'Tier' in df.columns else pd.DataFrame()
                    if not tier_df.empty:
                        # 确保要显示的列在数据中存在
                        cols_to_show = [c for c in display_cols if c in tier_df.columns]
                        st.dataframe(tier_df, use_container_width=True, hide_index=True, column_order=cols_to_show)
                    else:
                        st.info("暂无资产")

            # 针对不同评级，展示其最核心的量化得分项
            cols_a = ["代码", "名称", "板块", "Molt评分", "最大回撤", "索提诺(40分)", "状态"]
            cols_b = ["代码", "名称", "板块", "Molt评分", "索提诺(40分)", "状态"]
            cols_c = ["代码", "名称", "宏观属性", "Molt评分", "核心叙事", "状态"]
            cols_d = ["代码", "名称", "板块", "Molt评分", "相对强度", "盈亏比(20分)", "状态"]

            render_tier(col_a, "🛡️ A级 (压舱石)", "A", qualified_df, cols_a)
            render_tier(col_b, "🦍 B级 (核心基石)", "B", qualified_df, cols_b)
            render_tier(col_c, "🚀 C级 (时代之王)", "C", qualified_df, cols_c)
            render_tier(col_d, "🔥 D级 (预备队)", "D", qualified_df, cols_d)

            st.markdown("---")
            st.subheader("🗑️ 淘汰/观察区")
            cols_elim = ["代码", "名称", "板块", "Tier", "淘汰死因", "Molt评分", "状态"]
            if not eliminated_df.empty: 
                st.dataframe(
                    eliminated_df.sort_values("Molt评分", ascending=False), 
                    use_container_width=True, hide_index=True, column_order=cols_elim
                )
            else: 
                st.write("暂无淘汰资产")
else: st.info("⏳ 正在初始化数据...")