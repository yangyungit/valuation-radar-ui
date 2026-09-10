from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_theme_clusters

st.set_page_config(page_title="主题簇", layout="wide")

st.title("🌿 主题簇演化")
st.caption(
    "这是观察工具，不是买入信号。已实测：热簇里的领跑者后 63 日超额中位 −2.14%、"
    "胜率 45%（n=22031），比随便买一只流动股（中位 −1.03%、胜率 47%）还差。"
    "这页用来看市场当下按什么在分组，不用来选股。"
)
st.caption(
    "y 轴不是主题编号，是这一支从诞生那个月算起长到第几个月。要求成员原样延续（重合 ≥ 50%）的话，"
    "87% 的簇活不过一个月；但把成员换掉一半的分叉也算接着长，最长一支能连 29 个月——"
    "2022-08 到 2024-12 的中概股，从 PDD/FUTU 一路到 BABA/JD/XPEV/NIO，首尾还有 11 只票重合。"
)

WINDOWS = {"最近 3 年": 36, "最近 5 年": 60, "最近 10 年": 120, "全部": None}

with st.sidebar:
    win_name = st.selectbox("显示窗口", list(WINDOWS), index=0)
    min_label_month = st.slider("长到第 N 个月才写名字", min_value=2, max_value=12, value=4)
    if st.button("🔄 强制刷新数据"):
        fetch_theme_clusters.clear()
        st.rerun()

doc = fetch_theme_clusters(start="1998-01")
if not doc.get("success"):
    st.error(f"主题簇数据取不到：{doc.get('error')}")
    st.stop()

nodes, vines = doc.get("nodes", []), doc.get("vines", [])
if not nodes:
    st.warning("没有合格簇。")
    st.stop()

params = doc.get("params", {})
st.caption(
    f"口径：每月最后一个交易日回看 {params.get('window_days')} 个交易日，母体取窗口内日成交额中位数前 "
    f"{params.get('universe_top')} 且末日收盘价 ≥ ${params.get('min_price')} 的票；日超额扣 SPY 后算相关，"
    f"层次聚类切 {params.get('k_clusters')} 簇，成员数 {params.get('min_members')}~{params.get('max_members')} "
    f"且簇内平均相关 ≥ {params.get('min_internal_corr')} 才算合格。成员重合度（Jaccard）"
    f"≥ {params.get('continue_overlap')} 算同一条链延续，"
    f"{params.get('branch_overlap')}~{params.get('continue_overlap')} 算分叉，"
    f"连续 {params.get('death_months')} 个月超额中位 ≤ 0 或当月没有后继就算死。"
    f"数据止于 {doc.get('sep_last_date')}，构建于 {doc.get('generated_at')}。"
)

by_vine: dict[int, list] = defaultdict(list)
for n in nodes:
    by_vine[n["vine_id"]].append(n)
for v in by_vine.values():
    v.sort(key=lambda n: n["month"])

months = doc.get("months", [])
last_month = months[-1]

alive = {n["vine_id"] for n in nodes if n["month"] == last_month}
born = [v for v in vines if v["born_month"] == last_month]
died = [v for v in vines if v.get("died_month") == last_month]
c1, c2, c3, c4 = st.columns(4)
c1.metric("最新月份", last_month)
c2.metric("当月活着的链", len(alive))
c3.metric("当月新生", len(born))
c4.metric("当月死亡", len(died))

nodes_by_month = sorted(nodes, key=lambda n: n["month"])
height: dict[int, int] = {}
for n in nodes_by_month:
    p = n.get("parent_node_id")
    height[n["node_id"]] = height[p] + 1 if p in height else 0
has_child = {n["parent_node_id"] for n in nodes if n.get("parent_node_id")}
died_at = {(v["vine_id"], v["died_month"]) for v in vines if v.get("died_month")}


def cluster_name(n: dict) -> str:
    """名字只用领跑三只（这是事实）；行业只在簇确实集中时才加前缀。

    top_industry 是众数，而中位簇 12 只票横跨 8 个行业，直接当名字会编出
    「Insurance Brokers = NEM/FDS/CIEN」这种。
    """
    lead = "/".join(n["leaders"])
    return f'{n["top_industry"]}｜{lead}' if n["n_industries"] <= max(2, n["n"] * 0.3) else lead


span = WINDOWS[win_name]
mshow = months if span is None else months[-span:]
midx = {m: i for i, m in enumerate(mshow)}
draw = [n for n in nodes_by_month if n["month"] in midx]
if not draw:
    st.warning("这个窗口里没有合格簇。")
    st.stop()

bucket = defaultdict(list)
for n in draw:
    bucket[(midx[n["month"]], height[n["node_id"]])].append(n)
xy: dict[int, tuple[float, int]] = {}
for (mi, h), g in bucket.items():
    g.sort(key=lambda n: -n["excess_median"])
    k = len(g)
    for i, n in enumerate(g):
        xy[n["node_id"]] = (mi + (0.0 if k == 1 else (i / (k - 1) - 0.5) * 0.7), h)

shoot = [n for n in draw if height[n["node_id"]] > 0 or n["node_id"] in has_child]
shoot_ids = {n["node_id"] for n in shoot}
oneshot = [n for n in draw if n["node_id"] not in shoot_ids]

fig = go.Figure()
lx, ly = [], []
for n in draw:
    p = n.get("parent_node_id")
    if p in xy:
        lx += [xy[p][0], xy[n["node_id"]][0], None]
        ly += [xy[p][1], xy[n["node_id"]][1], None]
if lx:
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", hoverinfo="skip", showlegend=False,
                             line=dict(color="rgba(150,150,150,0.5)", width=1.2)))


def hover(ns: list[dict]) -> dict:
    return dict(
        customdata=[[cluster_name(n), n["month"], n["n"], n["internal_corr"],
                     n["excess_median"], height[n["node_id"]] + 1] for n in ns],
        hovertemplate=("%{customdata[0]}<br>%{customdata[1]}　第 %{customdata[5]} 个月<br>"
                       "成员 %{customdata[2]} 只 ｜ 簇内相关 %{customdata[3]:.2f}<br>"
                       "超额中位 %{customdata[4]:.1%}<extra></extra>"),
    )


if oneshot:
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in oneshot], y=[0] * len(oneshot),
        mode="markers", showlegend=False,
        marker=dict(size=5, color="rgba(140,140,140,0.35)"), **hover(oneshot)))

if shoot:
    size_ref = 2.0 * max(n["n"] for n in shoot) / (34.0 ** 2)
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in shoot], y=[height[n["node_id"]] for n in shoot],
        mode="markers", showlegend=False,
        marker=dict(
            size=[n["n"] for n in shoot], sizemode="area", sizeref=size_ref, sizemin=8,
            color=[n["excess_median"] for n in shoot], coloraxis="coloraxis",
            symbol=["x" if (n["vine_id"], n["month"]) in died_at else "circle" for n in shoot],
            line=dict(width=0.5, color="rgba(0,0,0,0.5)"),
        ), **hover(shoot)))

tops = [n for n in shoot
        if n["node_id"] not in has_child and height[n["node_id"]] + 1 >= min_label_month]
if tops:
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in tops], y=[height[n["node_id"]] for n in tops],
        mode="text", text=[cluster_name(n) for n in tops], hoverinfo="skip", showlegend=False,
        textposition="middle right", textfont=dict(size=11, color="rgba(220,220,220,0.9)")))

top_h = max(height[n["node_id"]] for n in draw)
step = max(1, len(mshow) // 24)
ystep = 1 if top_h <= 14 else 2
fig.update_layout(
    height=max(460, min(1200, 28 * (top_h + 1) + 150)),
    margin=dict(l=10, r=180, t=30, b=10),
    coloraxis=dict(colorscale="RdYlGn", cmin=-0.3, cmax=0.3,
                   colorbar=dict(title="超额中位", tickformat=".0%")),
    xaxis=dict(title="", showgrid=True, gridcolor="rgba(128,128,128,0.15)",
               tickmode="array", tickvals=list(range(0, len(mshow), step)),
               ticktext=[mshow[i][:7] for i in range(0, len(mshow), step)],
               range=[-1, len(mshow) + 0.5]),
    yaxis=dict(title="长到第几个月", showgrid=True, gridcolor="rgba(128,128,128,0.12)",
               tickmode="array", tickvals=list(range(0, top_h + 1, ystep)),
               ticktext=[f"第 {i + 1} 月" for i in range(0, top_h + 1, ystep)],
               range=[-0.6, top_h + 0.6]),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "每支从最底下一行（诞生那个月）起步，下个月还找得到成员重合 ≥ 20% 的后继就斜着往上长一格，"
    "找不到就停在原地。灰色小点 = 冒出来一个月就散了、没有后继的簇（近三年 135 个）；"
    "大气泡 = 长上去了的，点越大成员越多、越绿这 63 天超额越高；"
    "斜线连着的是同一支，从旧簇裂出来的新簇接着父节点继续往上长，不回底行；"
    "× = 原来的口径判它死在这里。名字写在每支的顶端，只写领跑三只票。"
)

st.subheader("单条链的成员进出")
opts = sorted([v for v in vines if v["n_nodes"] >= 2 and by_vine[v["vine_id"]][0]["month"] in midx],
              key=lambda v: (-v["n_nodes"], v["born_month"]))
if not opts:
    st.info("这个窗口里没有活过两个月的簇，把左边窗口调长。")
    st.stop()
pick = st.selectbox(
    "选一条链", opts,
    format_func=lambda v: f'{cluster_name(by_vine[v["vine_id"]][0])}'
                          f'（{v["born_month"]} 起 {v["n_nodes"]} 个月）')
seq = by_vine[pick["vine_id"]]
rows, prev = [], set()
for n in seq:
    cur = set(n["members"])
    rows.append({"月份": n["month"],
                 "新进": ", ".join(sorted(cur - prev)) if prev else ", ".join(sorted(cur)),
                 "退出": ", ".join(sorted(prev - cur)),
                 "留存": ", ".join(sorted(cur & prev))})
    prev = cur
left, right = st.columns([3, 2])
left.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
right.line_chart(pd.DataFrame({"超额中位": [n["excess_median"] for n in seq]},
                              index=[n["month"] for n in seq]))
if pick.get("died_month"):
    reason = {"no_successor": "下个月没有重合度够高的后继簇",
              "excess_negative": "连续两个月超额中位 ≤ 0"}.get(pick["death_reason"], pick["death_reason"])
    st.caption(f"这条链死在 {pick['died_month']}：{reason}。峰值超额中位 {pick['peak_excess_median']:.1%}。")
else:
    st.caption(f"这条链到 {last_month} 还活着。峰值超额中位 {pick['peak_excess_median']:.1%}。")

st.subheader(f"{last_month} 的合格簇")
cur_nodes = sorted([n for n in nodes if n["month"] == last_month],
                   key=lambda n: -n["excess_median"])
st.dataframe(pd.DataFrame([{
    "行业": n["top_industry"], "行业数": n["n_industries"], "成员数": n["n"],
    "簇内相关": n["internal_corr"], "超额中位%": round(n["excess_median"] * 100, 1),
    "领跑": ", ".join(n["leaders"]),
    "已活月数": height[n["node_id"]] + 1,
} for n in cur_nodes]), use_container_width=True, hide_index=True,
    column_config={"超额中位%": st.column_config.NumberColumn(format="%.1f"),
                   "簇内相关": st.column_config.NumberColumn(format="%.2f")})
