"""斜率分档：带鱼池每只票找「平稳一直涨的那段」，log 价拟合直线，斜率 = 复合年化，按斜率分 A/B/C。
算法在后端 /api/v1/macro/trend_slope（valuation-radar/scripts/trend_slope.py），本页只画图。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_trend_slope, fetch_trend_slope_detail

st.set_page_config(page_title="斜率分档", layout="wide", page_icon="📐")

TIER_COLOR = {"A": "#4fc3e8", "B": "#5cb85c", "C": "#f39c12", "-": "#777"}   # 同 page 33 SLEEVE_COLORS
SCOPES = {"历史并集 162 只（含退市）": "union", "当年生效池 40 只": "current"}
PRICES = {"股息扣 10% 税后再投": "net", "不含股息（和 TradingView 价格图一致）": "close"}

st.title("📐 斜率分档")
st.caption("带鱼池每只票只取「平稳一直涨的那段」（起点到最新一周、至少 3 年），log 价对时间拟合直线，"
           "斜率换算成复合年化（股息按扣 10% 税再投算）。A = 慢（≈ 大盘水平）、B = 中（≈ 纳指级）、C = 快（三年翻倍级）。"
           "段的起点由机器按「又直又长」挑：取最高 R²，在差不超过 0.01 的起点里挑最早的；最高 R² 不到 0.90 判无平稳段。"
           "机器挑的起点可能比肉眼早（WM 机器 2007-09、肉眼 2012-09），斜率差别小（16.1% vs 17.6%），分档不受影响；下方详情图可手填起点对比。")

with st.sidebar:
    scope = SCOPES[st.radio("池子", list(SCOPES))]
    extra = st.text_input("额外代码（逗号分隔）", placeholder="AAPL, ISRG, MNST")
    price = PRICES[st.radio("价格", list(PRICES))]
    edge_a = st.number_input("A / B 边界（年化 %）", value=15.0, step=1.0)
    edge_b = st.number_input("B / C 边界（年化 %）", value=25.0, step=1.0)
    if st.button("🔄 强制刷新"):
        fetch_trend_slope.clear()
        fetch_trend_slope_detail.clear()
        st.rerun()

if not edge_a < edge_b:
    st.error("A/B 边界必须小于 B/C 边界")
    st.stop()
d = fetch_trend_slope(scope, extra, price, edge_a, edge_b)
if not d.get("success"):
    st.error(f"后端没返回数据：{d.get('error')}")
    st.stop()

df = pd.DataFrame(d["rows"])
has = df[df["slope"].notna()]
none = df[df["slope"].isna()]
bench = d["bench"]

m1, m2, m3, m4, m5 = st.columns(5)
for col, t in zip((m1, m2, m3), ("A", "B", "C")):
    col.metric(f"{t} 档", f"{int((has['tier'] == t).sum())} 只")
m4.metric("无平稳段", f"{len(none)} 只")
m5.metric("SPY / QQQ 同法", f"{bench['SPY']['slope'] if bench.get('SPY') else '-'}% / {bench['QQQ']['slope'] if bench.get('QQQ') else '-'}%")
st.caption(f"池 {d['pool_year']} 年生效 · 数据截至 {d['asof']}（本地 Sharadar）· {d['rule']}")

asc = has.sort_values("slope")
fig_bar = go.Figure(go.Bar(
    orientation="h", x=asc["slope"], y=asc["ticker"],
    marker=dict(color=[TIER_COLOR[t] for t in asc["tier"]],
                opacity=[1.0 if a else 0.45 for a in asc["active"]]),
    text=[f"{r.slope}% · {r.start[:7]} 起 {r.years}y" for r in asc.itertuples()],
    textposition="outside", cliponaxis=False,
))
for x in (edge_a, edge_b):
    fig_bar.add_vline(x=x, line=dict(color="#888", dash="dash", width=1))
for key, color in (("SPY", "#3b9eff"), ("QQQ", "#a56cf0")):
    b = bench.get(key)
    if b and b.get("slope") is not None:
        fig_bar.add_vline(x=b["slope"], line=dict(color=color, dash="dot", width=1.5),
                          annotation_text=f"{key} {b['slope']}%", annotation_position="top")
fig_bar.update_layout(height=max(400, 22 * len(has)), xaxis_title="平稳段年化斜率 %",
                      margin=dict(l=40, r=120, t=40, b=40), showlegend=False)
st.plotly_chart(fig_bar, width="stretch")

tbl = df.copy()
tbl["name"] = tbl["name"] + tbl["is_tech"].map({True: "（科技）", False: ""}) \
    + tbl["active"].map({True: "", False: "（已退市）"})
tbl = tbl.sort_values("slope", ascending=False, na_position="last")
tbl = tbl[["ticker", "name", "sector", "tier", "slope", "start", "years", "r2", "mdd", "calmar", "in_pool"]]
tbl.columns = ["代码", "名称", "行业", "档", "年化斜率%", "段起点", "段长(年)", "R²", "段内最大回撤%", "Calmar", "在池"]
st.dataframe(tbl, hide_index=True, width="stretch")
st.caption("Calmar = 年化斜率 ÷ 段内最大回撤（日线，从段起点到最新）。段越长越容易撞上 2008 / 2020 这类大跌，长段的 Calmar 天然偏低。")

st.markdown("### 单票详情")
c1, c2 = st.columns([1, 1])
pick = c1.selectbox("代码", list(df["ticker"]))
manual = c2.text_input("手填起点（YYYY-MM-DD，留空只看机器段）", placeholder="2012-09-01")
dd = fetch_trend_slope_detail(pick, price, manual.strip() or None)
if not dd.get("success"):
    st.error(f"后端没返回数据：{dd.get('error')}")
    st.stop()
fig = go.Figure()
fig.add_trace(go.Scatter(x=dd["dates"], y=dd["close"], name=pick, line=dict(color="#ccc", width=1)))
for key, color, label in (("auto", "#f39c12", "机器段"), ("manual", "#4fc3e8", "手填起点")):
    seg = dd.get(key)
    if seg:
        fig.add_trace(go.Scatter(x=seg["dates"], y=seg["values"], mode="lines",
                                 name=f"{label} {seg['start'][:7]} 起 · {seg['slope']}%/年 · R² {seg['r2']}",
                                 line=dict(color=color, width=2, dash="dash" if key == "manual" else "solid")))
fig.update_layout(yaxis_type="log", height=480, legend=dict(orientation="h", y=1.08),
                  margin=dict(l=40, r=20, t=40, b=40))
st.plotly_chart(fig, width="stretch")
if manual.strip() and not dd.get("manual"):
    st.caption("手填起点离现在不足 3 年，没拟合")
