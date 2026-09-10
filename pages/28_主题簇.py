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

with st.sidebar:
    start_year = st.number_input("起始年份", min_value=1998, max_value=2026, value=2016, step=1)
    min_life = st.slider("只看存活 ≥ N 个月的藤", min_value=1, max_value=12, value=3)
    if st.button("🔄 强制刷新数据"):
        fetch_theme_clusters.clear()
        st.rerun()

doc = fetch_theme_clusters(start=f"{int(start_year)}-01")
if not doc.get("success"):
    st.error(f"主题簇数据取不到：{doc.get('error')}")
    st.stop()

nodes, vines = doc.get("nodes", []), doc.get("vines", [])
if not nodes:
    st.warning("该起始年份之后没有合格簇。")
    st.stop()

params = doc.get("params", {})
st.caption(
    f"口径：每月最后一个交易日回看 {params.get('window_days')} 个交易日，母体取窗口内日成交额中位数前 "
    f"{params.get('universe_top')} 且末日收盘价 ≥ ${params.get('min_price')} 的票；日超额扣 SPY 后算相关，"
    f"层次聚类切 {params.get('k_clusters')} 簇，成员数 {params.get('min_members')}~{params.get('max_members')} "
    f"且簇内平均相关 ≥ {params.get('min_internal_corr')} 才算合格。成员重合度（Jaccard）"
    f"≥ {params.get('continue_overlap')} 算同一条藤延续，"
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
vine_of = {v["vine_id"]: v for v in vines}

alive = {n["vine_id"] for n in nodes if n["month"] == last_month}
born = [v for v in vines if v["born_month"] == last_month]
died = [v for v in vines if v.get("died_month") == last_month]
c1, c2, c3, c4 = st.columns(4)
c1.metric("最新月份", last_month)
c2.metric("当月活着的藤", len(alive))
c3.metric("当月新生", len(born))
c4.metric("当月死亡", len(died))

show = sorted([v for v in vines if v["n_nodes"] >= min_life],
              key=lambda v: (v["born_month"], v["vine_id"]))
if not show:
    st.warning(f"没有存活 ≥ {min_life} 个月的藤，把左边的门槛调低。")
    st.stop()
slot = {v["vine_id"]: i for i, v in enumerate(show)}
pos = {n["node_id"]: (n["month"], slot[n["vine_id"]])
       for v in show for n in by_vine[v["vine_id"]]}

fig = go.Figure()
bx, by = [], []
for v in show:
    first = by_vine[v["vine_id"]][0]
    p = pos.get(first.get("parent_node_id"))
    if p:
        bx += [p[0], first["month"], None]
        by += [p[1], slot[v["vine_id"]], None]
if bx:
    fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", hoverinfo="skip",
                             line=dict(color="rgba(150,150,150,0.45)", width=1),
                             name="分叉", showlegend=False))

size_ref = 2.0 * float(params.get("max_members", 60)) / (20.0 ** 2)
for v in show:
    ns = by_vine[v["vine_id"]]
    dead_last = v.get("died_month") == ns[-1]["month"]
    fig.add_trace(go.Scatter(
        x=[n["month"] for n in ns], y=[slot[v["vine_id"]]] * len(ns),
        mode="lines+markers", name=v["label"], showlegend=False,
        line=dict(color="rgba(120,120,120,0.7)", width=1),
        marker=dict(
            size=[n["n"] for n in ns], sizemode="area", sizeref=size_ref, sizemin=4,
            color=[n["excess_median"] for n in ns], coloraxis="coloraxis",
            symbol=["x" if (dead_last and i == len(ns) - 1) else "circle"
                    for i in range(len(ns))],
            line=dict(width=0.5, color="rgba(0,0,0,0.5)"),
        ),
        customdata=[[v["label"], n["n"], n["internal_corr"], n["excess_median"],
                     ", ".join(n["leaders"])] for n in ns],
        hovertemplate=("%{customdata[0]}<br>%{x}<br>成员 %{customdata[1]} 只 ｜ "
                       "簇内相关 %{customdata[2]:.2f}<br>超额中位 %{customdata[3]:.1%}"
                       "<br>领跑 %{customdata[4]}<extra></extra>"),
    ))

fig.update_layout(
    height=max(420, min(1600, 22 * len(show) + 160)),
    margin=dict(l=10, r=10, t=30, b=10),
    coloraxis=dict(colorscale="RdYlGn", cmin=-0.3, cmax=0.3,
                   colorbar=dict(title="超额中位", tickformat=".0%")),
    xaxis=dict(title="", type="category", showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
    yaxis=dict(title="藤（按出生月份排）", showticklabels=False, showgrid=False),
)
st.plotly_chart(fig, use_container_width=True)
st.caption("点越大 = 簇里票越多，越绿 = 这 63 天超额越高；灰细线 = 从上月那条藤分叉出来；× = 这条藤在这里死了。")

st.subheader("单条藤的成员进出")
opts = sorted(show, key=lambda v: (-v["n_nodes"], v["born_month"]))
pick = st.selectbox("选一条藤", opts,
                    format_func=lambda v: f'{v["label"]}（{v["born_month"]} 起 {v["n_nodes"]} 个月）')
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
    st.caption(f"这条藤死在 {pick['died_month']}：{reason}。峰值超额中位 {pick['peak_excess_median']:.1%}。")
else:
    st.caption(f"这条藤到 {last_month} 还活着。峰值超额中位 {pick['peak_excess_median']:.1%}。")

st.subheader(f"{last_month} 的合格簇")
cur_nodes = sorted([n for n in nodes if n["month"] == last_month],
                   key=lambda n: -n["excess_median"])
st.dataframe(pd.DataFrame([{
    "行业": n["top_industry"], "行业数": n["n_industries"], "成员数": n["n"],
    "簇内相关": n["internal_corr"], "超额中位%": round(n["excess_median"] * 100, 1),
    "领跑": ", ".join(n["leaders"]),
    "藤": vine_of[n["vine_id"]]["label"] if n["vine_id"] in vine_of else "",
    "已活月数": vine_of[n["vine_id"]]["n_nodes"] if n["vine_id"] in vine_of else 0,
} for n in cur_nodes]), use_container_width=True, hide_index=True,
    column_config={"超额中位%": st.column_config.NumberColumn(format="%.1f"),
                   "簇内相关": st.column_config.NumberColumn(format="%.2f")})
