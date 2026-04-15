import streamlit as st
import pandas as pd
import plotly.express as px

from api_client import fetch_macro_radar

st.set_page_config(page_title="宏观全景雷达", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
    .insight-section { margin-top: 10px; font-size: 14px; color: #ddd; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    .logic-text { color: #aaa; font-style: italic; margin-left: 5px; }
    .key-point { font-weight: bold; color: #fff; }
</style>
""", unsafe_allow_html=True)

st.title("🔭 宏观全景雷达 (Macro Panoramic Radar)")
st.caption("双维监控：横轴【估值 Z-Score】，纵轴【相对强度 RS】。")

# --- 侧边栏缓存控制 ---
with st.sidebar:
    if st.button("🔄 强制刷新雷达数据"):
        fetch_macro_radar.clear()
        st.rerun()

# --- 从后端 API 获取数据（后端自拉 yfinance，TTL=4h）---
with st.spinner("🔭 正在从后端加载雷达数据..."):
    _radar = fetch_macro_radar()

if not _radar.get("success") or not _radar.get("metrics"):
    st.warning("⚠️ 雷达数据暂不可用，请检查后端连接或稍后刷新。")
    st.stop()

df_metrics   = pd.DataFrame(_radar["metrics"])
benchmark_mom = float(_radar.get("spy_mom20", 0.0))
_insights     = _radar.get("insights", {})

# --- 归因文字渲染（保留本页 HTML 格式，使用后端文字内容拼装）---
def _render_insight_html(group_name: str, df_group: pd.DataFrame, plain_text: str) -> str:
    df_sorted = df_group.sort_values("相对强度", ascending=False)
    leaders   = df_sorted.head(3)
    laggards  = df_sorted.tail(3)
    leader_html  = " ".join([f"<span class='tag-bull'>{r['名称']}</span>" for _, r in leaders.iterrows()])
    laggard_html = " ".join([f"<span class='tag-bear'>{r['名称']}</span>" for _, r in laggards.iterrows()])
    parts = plain_text.split(" | ") if plain_text else []
    analysis_text     = parts[1] if len(parts) > 1 else "数据特征不明显，维持中性观察。"
    macro_implication = parts[2].replace("宏观含义: ", "") if len(parts) > 2 else "暂无明确宏观指向。"
    return f"""
<div class='insight-box'>
<div class='insight-title'>🧠 深度归因 (Deep Insight): {group_name.split(':')[0]}</div>
<div style='display:flex; gap:24px; align-items:center; margin-bottom:10px; flex-wrap:wrap'>
<div>🚀 领涨: {leader_html}</div>
<div>🥀 领跌: {laggard_html}</div>
</div>
<div class='insight-section'>
<span class='key-point'>🧐 现象解读:</span> {analysis_text}
</div>
<div class='insight-section' style='margin-top:5px'>
<span class='key-point'>🌍 宏观启示:</span> <span class='logic-text'>{macro_implication}</span>
</div>
</div>
"""

# --- 侧边栏筛选 ---
with st.sidebar:
    st.header("资产筛选")
    st.metric("基准 (SPY) 20日涨跌", f"{benchmark_mom:.2f}%")
    all_groups = df_metrics["组别"].unique().tolist() if not df_metrics.empty else []
    default_groups = [g for g in ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"] if g in all_groups]
    selected_groups = st.multiselect("显示资产组别：", all_groups, default=default_groups)

if df_metrics.empty:
    st.warning("暂无数据")
    st.stop()

df_plot = df_metrics[df_metrics["组别"].isin(selected_groups)] if selected_groups else df_metrics

fig = px.scatter(
    df_plot, x="Z-Score", y="相对强度", color="相对强度", text="名称",
    hover_data={"代码": True, "趋势结构": True, "Z-Score": ":.2f", "相对强度": ":.2f", "名称": False, "相对强度": False},
    color_continuous_scale="RdYlGn", range_color=[-10, 10]
)

fig.add_hline(y=0, line_dash="dash", line_color="#FFFFFF", opacity=0.5)
fig.add_vline(x=0, line_dash="dash", line_color="#FFFFFF", opacity=0.3)
fig.update_traces(textposition="top center", marker=dict(size=10, opacity=0.9))

fig.add_annotation(x=2,  y=5,  text="领涨/拥挤\n(减仓)",  showarrow=False, font=dict(color="#E74C3C", size=10))
fig.add_annotation(x=-2, y=-5, text="滞涨/弱势\n(观察)",  showarrow=False, font=dict(color="#3498DB", size=10))
fig.add_annotation(x=-2, y=5,  text="抗跌/启动\n(加仓)",  showarrow=False, font=dict(color="#2ECC71", size=10))
fig.add_annotation(x=2,  y=-5, text="补跌/崩盘\n(离场)",  showarrow=False, font=dict(color="#E67E22", size=10))

fig.update_layout(
    height=600, plot_bgcolor="#111111", paper_bgcolor="#111111",
    font=dict(color="#ddd"),
    xaxis_title="便宜 (低 Z-Score) <---> 昂贵",
    yaxis_title="弱于大盘 <---> 强于大盘",
)
st.plotly_chart(fig, use_container_width=True)

for group in selected_groups:
    df_sub = df_metrics[df_metrics["组别"] == group]
    plain  = _insights.get(group, "")
    st.markdown(_render_insight_html(group, df_sub, plain), unsafe_allow_html=True)

st.markdown("### 📋 详细数据表 (Trend Structure)")

def color_structure(val):
    if "长牛" in val: return "color: #2ECC71; font-weight: bold"
    if "熊市" in val: return "color: #E74C3C"
    if "反弹" in val: return "color: #F1C40F"
    return "color: #aaa"

st.dataframe(
    df_plot.sort_values("相对强度", ascending=False).style.map(
        color_structure, subset=["趋势结构"]
    ).format({"Z-Score": "{:.2f}", "相对强度": "{:.2f}", "L/VL": "{:.2f}"}),
    use_container_width=True, hide_index=True
)
