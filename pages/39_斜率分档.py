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
    cap_months = int(st.number_input("跟涨不跟跌看近几个月", value=12, min_value=1, max_value=120, step=1))
    if st.button("🔄 强制刷新"):
        fetch_trend_slope.clear()
        fetch_trend_slope_detail.clear()
        st.rerun()

if not edge_a < edge_b:
    st.error("A/B 边界必须小于 B/C 边界")
    st.stop()
d = fetch_trend_slope(scope, extra, price, edge_a, edge_b, cap_months)
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

st.markdown("### 斜率 × 水下痛苦值")
basis = st.radio("口径", [f"统一近 10 年（{d['window_start']} 起）", "各自平稳段"], horizontal=True)
win = basis.startswith("统一")
xk, yk, mk, uk = ("ulcer10", "slope10", "martin10", "uw10") if win else ("ulcer", "slope", "martin", "uw")
pts = df[df[xk].notna() & df[yk].notna()]
fig_sc = go.Figure(go.Scatter(
    x=pts[xk], y=pts[yk], mode="markers+text", text=pts["ticker"], textposition="top right",
    textfont=dict(size=9, color="#aaa"),
    marker=dict(size=9, line=dict(width=0.5, color="#222"),
                **(dict(color=[TIER_COLOR[t] for t in pts["tier"]]) if win else
                   dict(color=pts["years"], colorscale="Viridis", reversescale=True,
                        colorbar=dict(title="段长(年)")))),
    customdata=pts[[mk, uk, "start", "years"]].to_numpy(),
    hovertemplate="%{text}<br>斜率 %{y}% · Ulcer %{x}<br>Martin %{customdata[0]} · 最长水下 %{customdata[1]} 年"
                  "<br>段 %{customdata[2]} 起 %{customdata[3]} 年<extra></extra>",
))
xmax = float(pts[xk].max()) * 1.05
ymax = min(float(pts[yk].max()) * 1.1, 80)
for m in (1, 2, 4):
    fig_sc.add_trace(go.Scatter(x=[0, xmax], y=[0, m * xmax], mode="lines", hoverinfo="skip",
                                line=dict(color="#666", dash="dash", width=1), showlegend=False))
    xa = min(xmax, ymax / m) * 0.92
    fig_sc.add_annotation(x=xa, y=xa * m, text=f"Martin={m}", showarrow=False,
                          font=dict(color="#888", size=10), xanchor="left")
for key, color in (("SPY", "#3b9eff"), ("QQQ", "#a56cf0")):
    b = bench.get(key)
    if b and b.get(xk) is not None:
        fig_sc.add_trace(go.Scatter(x=[b[xk]], y=[b[yk]], mode="markers+text", text=[key],
                                    textposition="bottom center", showlegend=False,
                                    marker=dict(symbol="star", size=15, color=color)))
fig_sc.update_layout(height=600, xaxis=dict(title="Ulcer（水下痛苦值，越左越舒服）", range=[0, xmax]),
                     yaxis=dict(title="年化斜率 %", range=[0, ymax]),
                     showlegend=False, margin=dict(l=40, r=20, t=20, b=40))
st.plotly_chart(fig_sc, width="stretch")
st.caption("左上角 = 涨得快、拿着不痛苦。虚线是 Martin（斜率 ÷ Ulcer）等值线，越陡越好。"
           + ("统一窗口下所有票考同一张卷子，上市不满 10 年或已退市的不画；颜色 = 分档。" if win else
              "各自平稳段口径下颜色浅 = 段短，多半是还没赶上 2008 / 2020 这类大跌，Martin 偏高不全是真本事。"))

st.markdown("### 体验感：又直又匀")
rk, ck = ("r210", "conc10") if win else ("r2", "conc")
f1, f2 = st.columns(2)
r2_min = f1.number_input("R² 至少", value=0.95, step=0.01, format="%.2f")
conc_max = f2.number_input("月度收益集中度至多", value=1.30, step=0.05, format="%.2f")
CONC_CAP = 4.0   # 集中度 > 4 基本是十年没怎么涨、分母接近 0 的票（FISV 158、CMCSA 78），画上去把横轴压扁
pts2 = df[df[rk].notna() & df[ck].notna() & (df[rk] > 0) & (df[ck] <= CONC_CAP)]
good = pts2[(pts2[rk] >= r2_min) & (pts2[ck] <= conc_max)].sort_values(ck)
fig_ex = go.Figure()
fig_ex.add_shape(type="rect", x0=0, x1=conc_max, y0=r2_min, y1=1.0, line=dict(width=0),
                 fillcolor="rgba(79,195,232,0.12)", layer="below")
fig_ex.add_trace(go.Scatter(
    x=pts2[ck], y=pts2[rk], mode="markers+text", text=pts2["ticker"], textposition="top right",
    textfont=dict(size=9, color="#aaa"),
    marker=dict(size=9, line=dict(width=0.5, color="#222"),
                color=["#4fc3e8" if t in set(good["ticker"]) else "#666" for t in pts2["ticker"]]),
    customdata=pts2[[yk, xk]].to_numpy(),
    hovertemplate="%{text}<br>R² %{y} · 集中度 %{x}<br>斜率 %{customdata[0]}% · Ulcer %{customdata[1]}<extra></extra>",
))
for key, color in (("SPY", "#3b9eff"), ("QQQ", "#a56cf0")):
    b = bench.get(key)
    if b and b.get(ck) is not None:
        fig_ex.add_trace(go.Scatter(x=[b[ck]], y=[b[rk]], mode="markers+text", text=[key],
                                    textposition="bottom center", showlegend=False,
                                    marker=dict(symbol="star", size=15, color=color)))
fig_ex.update_layout(height=520, showlegend=False, margin=dict(l=40, r=20, t=20, b=40),
                     xaxis=dict(title="月度收益集中度（涨幅最大的 20% 月份贡献几成总涨幅，越左越匀速）"),
                     yaxis=dict(title="logR²（越高越像一条直线）", range=[max(0.5, float(pts2[rk].min()) - 0.02), 1.0]))
st.plotly_chart(fig_ex, width="stretch")
st.caption("R² 量「像不像直线」，集中度量「涨幅是不是靠几个月猛拉」。两个都好 = 左上角蓝色区域。"
           "集中度 1.0 = 总涨幅刚好全来自最好的 20% 月份，1.5 = 其余 80% 月份合计倒亏了一半。"
           f"集中度 > {CONC_CAP:.0f} 的不画（总涨幅接近 0，比值没意义）。"
           + ("统一 10 年窗口，上市不满 10 年或已退市的不画。" if win else
              "各自平稳段口径下 R² 天然 ≥ 0.90（挑段时就按这个选的），区分度主要看集中度。"))
if len(good):
    st.markdown(f"**通过筛选 {len(good)} 只**（按集中度从匀到跳）：" + "、".join(
        f"{r.ticker} {getattr(r, rk):.2f}/{getattr(r, ck):.2f}" for r in good.itertuples()))
else:
    st.info("没有票同时过两条线，放宽一点试试")

st.markdown(f"### 近期跟涨不跟跌（近 {d['cap_months']} 个月，参照 {d['cap_ref']}）")
g1, g2, g3 = st.columns(3)
up_min = g1.number_input("上行捕获至少", value=80.0, step=10.0)
gap_min = g2.number_input("上行 − 下行 至少", value=30.0, step=10.0)
off_max = g3.number_input("离窗口内高点最多跌 %", value=15.0, step=5.0)
pc = df[df["up_cap"].notna() & df["dn_cap"].notna()].copy()
pc["gap"] = pc["up_cap"] - pc["dn_cap"]
asym = pc[(pc["up_cap"] >= up_min) & (pc["gap"] >= gap_min) & (pc["off_high"] >= -off_max)] \
    .sort_values("gap", ascending=False)
fig_cp = go.Figure()
lo = min(0.0, float(pc["dn_cap"].min()) * 1.05)
hi = max(float(pc["dn_cap"].max()), float(pc["up_cap"].max())) * 1.05
fig_cp.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", hoverinfo="skip", showlegend=False,
                            line=dict(color="#666", dash="dash", width=1)))
fig_cp.add_trace(go.Scatter(
    x=pc["dn_cap"], y=pc["up_cap"], mode="markers+text", text=pc["ticker"], textposition="top right",
    textfont=dict(size=9, color="#aaa"),
    marker=dict(size=9, line=dict(width=0.5, color="#222"),
                color=["#4fc3e8" if t in set(asym["ticker"]) else "#666" for t in pc["ticker"]]),
    customdata=pc[["off_high", "tier", "slope"]].to_numpy(),
    hovertemplate="%{text}<br>上行 %{y} · 下行 %{x}<br>离近期高点 %{customdata[0]}%"
                  "<br>档 %{customdata[1]} · 斜率 %{customdata[2]}%<extra></extra>",
))
for key, color in (("SPY", "#3b9eff"), ("QQQ", "#a56cf0")):
    b = bench.get(key)
    if b and b.get("up_cap") is not None:
        fig_cp.add_trace(go.Scatter(x=[b["dn_cap"]], y=[b["up_cap"]], mode="markers+text", text=[key],
                                    textposition="bottom center", showlegend=False,
                                    marker=dict(symbol="star", size=15, color=color)))
fig_cp.update_layout(height=560, showlegend=False, margin=dict(l=40, r=20, t=20, b=40),
                     xaxis=dict(title=f"下行捕获（{d['cap_ref']} 跌的日子它跟着跌几成）", range=[lo, hi]),
                     yaxis=dict(title=f"上行捕获（{d['cap_ref']} 涨的日子它跟着涨几成）", range=[lo, hi]))
st.plotly_chart(fig_cp, width="stretch")
st.caption(f"{d['cap_start']} 起的日收益。左上角 = 涨跟得多、跌跟得少；对角线上 = 只是 {d['cap_ref']} 的缩放版；"
           "横轴为负 = 大盘跌它反而涨（脱钩）。捕获率是整段平均，会把「刚崩过」平均掉，所以第三个条件卡离近期高点的跌幅。"
           "蓝色 = 三个条件都过。")
if len(asym):
    st.markdown(f"**跟涨不跟跌 {len(asym)} 只**（按上行 − 下行从大到小）：" + "、".join(
        f"{r.ticker} {r.up_cap:.0f}/{r.dn_cap:.0f}·离高 {r.off_high:.0f}%" for r in asym.itertuples()))
else:
    st.info("没有票同时过三条线，放宽一点试试")

tbl = df.copy()
tbl["name"] = tbl["name"] + tbl["is_tech"].map({True: "（科技）", False: ""}) \
    + tbl["active"].map({True: "", False: "（已退市）"})
tbl = tbl.sort_values("slope", ascending=False, na_position="last")
tbl = tbl[["ticker", "name", "sector", "tier", "slope", "start", "years", "r2", "conc", "mdd", "calmar", "ulcer", "martin", "uw",
           "slope10", "r210", "conc10", "ulcer10", "martin10", "uw10", "up_cap", "dn_cap", "off_high", "in_pool"]]
tbl.columns = ["代码", "名称", "行业", "档", "年化斜率%", "段起点", "段长(年)", "R²", "月收益集中度",
               "段内最大回撤%", "Calmar", "Ulcer", "Martin", "最长水下(年)",
               "10年斜率%", "10年R²", "10年月收益集中度", "10年Ulcer", "10年Martin", "10年最长水下(年)",
               "上行捕获", "下行捕获", "离近期高点%", "在池"]
st.dataframe(tbl, hide_index=True, width="stretch")
st.caption("回撤都按日线、从段起点算到最新。Calmar = 年化斜率 ÷ 最大回撤，只看最惨一天；"
           "Ulcer = 每天离前高跌幅的均方根（水下多深、泡多久），Martin = 年化斜率 ÷ Ulcer，受单次大跌影响小。"
           "段越长越容易撞上 2008 / 2020，长段两个比值都偏低，Calmar 更明显。"
           f"最长水下 = 最久一次低于前高熬了几年（还没回到前高的也算）。月收益集中度见上一节。"
           f"「10年」几列统一用 {d['window_start']} 到数据末日同一段时间算，斜率同法拟合但不挑段，跨票比较看这几列。"
           f"上行 / 下行捕获和离高点跌幅按近 {d['cap_months']} 个月日线算，见上一节。")

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
