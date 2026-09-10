from collections import defaultdict

import numpy as np
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
    "y 轴不是主题编号，是这一支从诞生那个月算起长到第几个月，名字写在链的末端。"
    "**链只看成员重合、不看涨跌**——上个月的簇和这个月的簇成员重合过半就算同一条链续上了，"
    "所以「云软件杀跌」这种从头跌到尾的（2026-01~05 超额 −23% 一路走到 −15%）照样能串成 5 个月的链。"
    "颜色才是涨跌：红 = 超额为负，绿 = 为正。一条长红链的意思是「这批票被当成一伙一起被卖」，"
    "不是「这批票在涨」。"
)

WINDOWS = {"最近 3 年": 36, "最近 5 年": 60, "最近 10 年": 120, "全部": None}

with st.sidebar:
    win_name = st.selectbox("显示窗口", list(WINDOWS), index=0)
    named_only = st.checkbox(
        "只看起了名的链", value=True,
        help="没起名的都是只活 1~2 个月的簇，占近三年画出的点三成。它们跟长链挤在同一格里"
             "被碰撞算法推得东倒西歪，连线就绞成麻花，去掉后图能清爽不少。")
    min_label_month = st.slider("长到第 N 个月才写名字", min_value=2, max_value=12, value=4)
    bubble_px = st.slider("最大气泡直径（像素）", min_value=8, max_value=40, value=18)
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
st.caption(
    "**名字怎么来的**：活过 3 个月的 391 条链是人看着成员票起的中文名（存后端 "
    "`theme_names.json`），像「疫情居家软件」「AI 数据中心产业链」「大选行情：加密与金融科技」——"
    "这类横跨行业的叙事，行业分类给不出来（2020-03 那个 ZM/TDOC/ZS 的簇，行业众数是"
    "「Electronic Gaming & Multimedia」）。剩下只活 1~2 个月的簇没起名，退回「行业 占比｜代表票」，"
    "占比低于 25% 就直接显示涨得最猛的三只。鼠标悬停能看到完整行业构成，自己判断名靠不靠谱。"
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

def cluster_name(n: dict) -> str:
    """优先用人起的叙事名，没有才退回行业，行业也不够格就用涨得最猛的三只。

    叙事名存在后端 theme_names.json，只给活过 3 个月的链起，覆盖约一半节点。
    行业分类给不出「疫情居家软件」这种名字——2020-03 那个簇的行业众数是
    「Electronic Gaming & Multimedia 16%」，纯凑数。占比写出来是让人自己判断
    这个名靠不靠谱：「Healthcare Plans 88%」可信，16% 就该看票。
    """
    if n.get("theme_name"):
        return n["theme_name"]
    mix = n.get("industry_mix") or []
    if mix and mix[0]["share"] >= 0.25:
        return f'{mix[0]["name"]} {mix[0]["share"]:.0%}｜{"/".join(n.get("biggest") or n["leaders"])}'
    return "/".join(n["leaders"])


def mix_line(n: dict) -> str:
    """hover 里的行业构成：只数 + 相对母体的富集倍数。"""
    return " / ".join(f'{m["name"]} {m["n"]}只'
                      + (f'（{m["lift"]:.1f}倍）' if m.get("lift") else "")
                      for m in (n.get("industry_mix") or [])[:3]) or "—"


span = WINDOWS[win_name]
mshow = months if span is None else months[-span:]
midx = {m: i for i, m in enumerate(mshow)}
draw = [n for n in nodes_by_month if n["month"] in midx]
if named_only:
    draw = [n for n in draw if n.get("theme_name")]
if not draw:
    st.warning("这个窗口里没有合格簇（若勾了「只看起了名的链」，试着取消）。")
    st.stop()

shoot = [n for n in draw if height[n["node_id"]] > 0 or n["node_id"] in has_child]
shoot_ids = {n["node_id"] for n in shoot}
oneshot = [n for n in draw if n["node_id"] not in shoot_ids]

top_h = max(height[n["node_id"]] for n in draw)
fig_h = max(460, min(1200, 28 * (top_h + 1) + 150))
max_n = max(n["n"] for n in draw)
dot_px = {n["node_id"]: 5.0 + (bubble_px - 5.0) * (n["n"] / max_n) ** 0.5 for n in shoot}
dot_px.update({n["node_id"]: 4.0 for n in oneshot})

px_x = 760.0 / (len(mshow) + 1.5)
px_y = (fig_h - 40.0) / (top_h + 1.2)

rng = np.random.default_rng(0)
by_col = defaultdict(list)
for n in draw:
    by_col[midx[n["month"]]].append(n)
xy: dict[int, tuple[float, float]] = {}
for mi, g in by_col.items():
    tx = np.full(len(g), float(mi))
    ty = np.array([float(height[n["node_id"]]) for n in g])
    r = np.array([dot_px[n["node_id"]] / 2.0 for n in g])
    x = tx + rng.uniform(-0.06, 0.06, len(g))
    y = ty + rng.uniform(-0.06, 0.06, len(g))
    for _ in range(80):
        dx = (x[:, None] - x[None, :]) * px_x
        dy = (y[:, None] - y[None, :]) * px_y
        d = np.hypot(dx, dy)
        np.fill_diagonal(d, np.inf)
        push = (r[:, None] + r[None, :]) * 1.12 - d
        if not (push > 0).any():
            break
        push = np.where(push > 0, push, 0.0) * 0.5
        safe = np.where(np.isfinite(d) & (d > 1e-9), d, 1.0)
        x += (push * dx / safe).sum(axis=1) / px_x * 0.6 + (tx - x) * 0.04
        y += (push * dy / safe).sum(axis=1) / px_y * 0.6 + (ty - y) * 0.04
        np.clip(x, tx - 0.40, tx + 0.40, out=x)
        np.clip(y, ty - 0.45, ty + 0.45, out=y)
    for i, n in enumerate(g):
        xy[n["node_id"]] = (float(x[i]), float(y[i]))

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
                     n["excess_median"], height[n["node_id"]] + 1, mix_line(n),
                     "/".join(n.get("biggest") or []), "/".join(n["leaders"])] for n in ns],
        hovertemplate=("%{customdata[0]}<br>%{customdata[1]}　第 %{customdata[5]} 个月<br>"
                       "成员 %{customdata[2]} 只 ｜ 簇内相关 %{customdata[3]:.2f}<br>"
                       "超额中位 %{customdata[4]:.1%}<br>行业 %{customdata[6]}<br>"
                       "代表 %{customdata[7]} ｜ 领跑 %{customdata[8]}<extra></extra>"),
    )


if oneshot:
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in oneshot], y=[xy[n["node_id"]][1] for n in oneshot],
        mode="markers", showlegend=False,
        marker=dict(size=[dot_px[n["node_id"]] for n in oneshot],
                    color="rgba(150,150,150,0.4)"), **hover(oneshot)))

if shoot:
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in shoot], y=[xy[n["node_id"]][1] for n in shoot],
        mode="markers", showlegend=False, opacity=0.88,
        marker=dict(
            size=[dot_px[n["node_id"]] for n in shoot],
            color=[n["excess_median"] for n in shoot], coloraxis="coloraxis",
            symbol=["x" if n["node_id"] not in has_child else "circle" for n in shoot],
            line=dict(width=0.5, color="rgba(0,0,0,0.55)"),
        ), **hover(shoot)))

tops = [n for n in shoot
        if n["node_id"] not in has_child and height[n["node_id"]] + 1 >= min_label_month]
tops.sort(key=lambda n: (not n.get("theme_name"), -height[n["node_id"]]))
kept, boxes = [], []
for n in tops:
    x0, y0 = xy[n["node_id"]]
    label = cluster_name(n)
    w = sum(11 if ord(c) > 0x2E80 else 6.4 for c in label) + 10
    lo, hi, yy = x0 * px_x + 6, x0 * px_x + 6 + w, y0 * px_y
    if any(abs(yy - b[2]) < 13 and lo < b[1] and b[0] < hi for b in boxes):
        continue
    boxes.append((lo, hi, yy))
    kept.append(n)
if kept:
    fig.add_trace(go.Scatter(
        x=[xy[n["node_id"]][0] for n in kept], y=[xy[n["node_id"]][1] for n in kept],
        mode="text", text=[cluster_name(n) for n in kept], hoverinfo="skip", showlegend=False,
        textposition="middle right", textfont=dict(size=11, color="rgba(230,230,230,0.92)")))

step = max(1, len(mshow) // 24)
ystep = 1 if top_h <= 14 else 2
fig.update_layout(
    height=fig_h, dragmode="pan", hovermode="closest",
    margin=dict(l=10, r=240, t=30, b=10),
    coloraxis=dict(colorscale="RdYlGn", cmin=-0.3, cmax=0.3,
                   colorbar=dict(title="超额中位", tickformat=".0%")),
    xaxis=dict(title="", showgrid=True, gridcolor="rgba(128,128,128,0.15)",
               tickmode="array", tickvals=list(range(0, len(mshow), step)),
               ticktext=[mshow[i][:7] for i in range(0, len(mshow), step)],
               range=[-1, len(mshow) + 1.5]),
    yaxis=dict(title="长到第几个月", showgrid=True, gridcolor="rgba(128,128,128,0.12)",
               tickmode="array", tickvals=list(range(0, top_h + 1, ystep)),
               ticktext=[f"第 {i + 1} 月" for i in range(0, top_h + 1, ystep)],
               range=[-0.6, top_h + 0.6]),
)
st.plotly_chart(fig, use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False})
st.caption(
    "**滚轮缩放、按住拖动**，双击回到全图。挤在一起的气泡会互相推开：横向不出所在月份 ±0.4，"
    "纵向不出所属月龄 ±0.45，所以时间轴对得上，上下位置是晃动过的。"
    "每支从最底下一行（诞生那个月）起步，下个月还找得到成员重合 ≥ 20% 的后继就斜着往上长一格，"
    "找不到就停在原地。点越大成员越多，越绿这 63 天超额越高；"
    "斜线连着的是同一支，从旧簇裂出来的新簇接着父节点继续往上长，不回底行；"
    "× = 这一支到此为止，下个月再没有成员对得上的后继。"
    "名字写在每支顶端，互相压住的自动省略——放大就都出来了。"
    "线绞成麻花是因为同一个格子（同月同月龄）能挤十来条互不相干的链，"
    "碰撞算法把它们推开后连线就交叉了，不是分叉——近三年真正的分叉只有 12 处。"
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
    "主题": n.get("theme_name") or "—", "行业构成": mix_line(n), "成员数": n["n"],
    "簇内相关": n["internal_corr"], "超额中位%": round(n["excess_median"] * 100, 1),
    "代表": ", ".join(n.get("biggest") or []), "领跑": ", ".join(n["leaders"]),
    "已活月数": height[n["node_id"]] + 1,
} for n in cur_nodes]), use_container_width=True, hide_index=True,
    column_config={"超额中位%": st.column_config.NumberColumn(format="%.1f"),
                   "簇内相关": st.column_config.NumberColumn(format="%.2f")})
