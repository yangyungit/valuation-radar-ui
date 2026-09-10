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
    "纵轴是时间，越往上越近，每支的起点就落在它诞生那个月；横轴不是主题编号，"
    "是这一支从诞生算起长到第几个月，所以一条链是往右上角斜着长的，名字写在链的末端。"
    "**链只看成员重合、不看涨跌**——上个月的簇和这个月的簇成员重合过半就算同一条链续上了，"
    "所以「云软件杀跌」这种从头跌到尾的（2026-01~05 超额 −23% 一路走到 −15%）照样能串成 5 个月的链。"
    "颜色才是涨跌：红 = 超额为负，绿 = 为正。一条长红链的意思是「这批票被当成一伙一起被卖」，"
    "不是「这批票在涨」。"
)

WINDOWS = {"最近 3 年": 36, "最近 5 年": 60, "最近 10 年": 120, "全部": None}

with st.sidebar:
    win_name = st.selectbox("显示窗口", list(WINDOWS), index=0)
    min_chain = st.slider(
        "链至少活 N 个月才画", min_value=1, max_value=12, value=4,
        help="按整条链的寿命过滤，不是按单个点。调到 1 = 全画（含只冒一个月就散的簇）。"
             "短链扎堆在底部两三行，被碰撞算法推得东倒西歪，连线绞成麻花。"
             "最近 3 年：≥3 个月有 22 条链，≥4 个月只剩 7 条。")
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

# 链的寿命 = 这条链爬到的最大月龄。不用后端的 chain_len（那是整棵树的节点数，
# 分叉的链会虚高：3 个节点可能只有 2 个月高）。按全历史算，跨窗口边界的长链不误伤。
chain_h: dict[str, int] = {}
for n in nodes_by_month:
    k = n.get("chain_key")
    chain_h[k] = max(chain_h.get(k, 0), height[n["node_id"]] + 1)

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
draw = [n for n in draw if chain_h.get(n.get("chain_key"), 1) >= min_chain]
if not draw:
    st.warning(f"这个窗口里没有活过 {min_chain} 个月的链，把左边滑块调小。")
    st.stop()

shoot = [n for n in draw if height[n["node_id"]] > 0 or n["node_id"] in has_child]
shoot_ids = {n["node_id"] for n in shoot}
oneshot = [n for n in draw if n["node_id"] not in shoot_ids]

top_h = max(height[n["node_id"]] for n in draw)
fig_h = max(520, min(1800, 26 * len(mshow) + 140))
max_n = max(n["n"] for n in draw)
dot_px = {n["node_id"]: 5.0 + (bubble_px - 5.0) * (n["n"] / max_n) ** 0.5 for n in shoot}
dot_px.update({n["node_id"]: 4.0 for n in oneshot})

# 横轴初始只铺到 95% 的链够用的宽度：近三年（链 ≥4 个月）最长那条活了 29 个月，
# 但 95 分位只有 11，按 29 铺会把 25 条链里的大半挤在左边三分之一。超出的拖动可见。
vis_h: dict[str, int] = {}
for n in draw:
    k = n.get("chain_key")
    vis_h[k] = max(vis_h.get(k, 0), height[n["node_id"]])
x_max = min(top_h, max(7, int(np.percentile(list(vis_h.values()), 95))))

px_x = 760.0 / (x_max + 2.2)
px_y = (fig_h - 40.0) / (len(mshow) + 1.2)

# 位置是受力解出来的，横纵都不锁格子：只有起点那个球钉在自己的日期上，后面的球
# 受四条约束——跟父节点之间一根定长的杆（一根 = 一个月，数杆数就知道活了几个月）、
# 在父节点的右上方、被前一根杆的延长线拉着（不然密集处会折成锯齿）、跟别的球互斥。
# 链往哪个方向舒展随它，纵向只留 0.02 的回拉，免得整条链飘到几年以外。
idx = {n["node_id"]: i for i, n in enumerate(draw)}
X = np.array([float(height[n["node_id"]]) for n in draw]) * px_x
Y = np.array([float(midx[n["month"]]) for n in draw]) * px_y
X0, Y0 = X.copy(), Y.copy()
R = np.array([dot_px[n["node_id"]] / 2.0 for n in draw])
X += np.random.default_rng(0).uniform(-0.1, 0.1, len(draw)) * px_x

ei = np.array([idx[n["node_id"]] for n in draw if n.get("parent_node_id") in idx], dtype=int)
ej = np.array([idx[n["parent_node_id"]] for n in draw if n.get("parent_node_id") in idx], dtype=int)
# 爷爷-父亲-孩子三连：孩子被拉向前一根杆的延长线，链才是平滑弧线不是锯齿
par = {n["node_id"]: n.get("parent_node_id") for n in draw}
tri = [(idx[k], idx[par[k]], idx[par[par[k]]]) for k in idx
       if par.get(k) in idx and par.get(par.get(k)) in idx]
ti, tj, tk = (np.array(a, dtype=int) for a in zip(*tri)) if tri else (np.empty(0, int),) * 3
is_root = np.ones(len(draw), dtype=bool)
is_root[ei] = False
rod = float(np.hypot(px_x, px_y))
pull_y = np.where(is_root, 0.5, 0.02)   # 起点钉在自己的日期上，后面的只轻轻拽
pull_x = np.where(is_root, 0.05, 0.0)   # 横向只轻轻拽一下：同月出生的几条链起点
                                        # 坐标一模一样，横向钉死就必然压在一起

for it in range(260):
    # 球能上下飘了，就不能再按「所属月份」分组比避让——隔五个月的两个球可能飘到
    # 同一高度。每 10 轮按当前纵坐标重新分桶，桶高取最大气泡直径的 1.5 倍，
    # 只跟同桶和上邻桶比：两球够近到会重叠，纵距必然小于桶高，不会漏。
    if it % 10 == 0:
        bin_h = 3.0 * R.max()
        buckets = defaultdict(list)
        for i, bi in enumerate(np.floor(Y / bin_h).astype(int)):
            buckets[bi].append(i)
        bands = [np.array(buckets[k] + buckets.get(k + 1, []), dtype=int)
                 for k in sorted(buckets)]
        bands = [b for b in bands if len(b) > 1]
    fx, fy = np.zeros(len(draw)), np.zeros(len(draw))
    for b in bands:
        dx = X[b][:, None] - X[b][None, :]
        dy = Y[b][:, None] - Y[b][None, :]
        d = np.hypot(dx, dy)
        np.fill_diagonal(d, np.inf)
        push = np.where(d < (R[b][:, None] + R[b][None, :]) * 1.5,
                        (R[b][:, None] + R[b][None, :]) * 1.5 - d, 0.0)
        safe = np.where(d > 1e-6, d, 1.0)      # 完全重合的靠 X 的初始扰动分开
        np.add.at(fx, b, (push * dx / safe).sum(axis=1) * 0.5)
        np.add.at(fy, b, (push * dy / safe).sum(axis=1) * 0.5)
    ex, ey = X[ei] - X[ej], Y[ei] - Y[ej]
    ed = np.maximum(np.hypot(ex, ey), 1e-6)
    stretch = (ed - rod) / ed * 0.5             # 杆拉回定长，两端各分一半
    np.add.at(fx, ei, -stretch * ex)
    np.add.at(fx, ej, stretch * ex)
    np.add.at(fy, ei, -stretch * ey)
    np.add.at(fy, ej, stretch * ey)
    np.add.at(fx, ti, (2 * X[tj] - X[tk] - X[ti]) * 0.25)
    np.add.at(fy, ti, (2 * Y[tj] - Y[tk] - Y[ti]) * 0.25)
    gapy = np.maximum(0.30 * px_y - (Y[ei] - Y[ej]), 0.0)   # 孩子在父节点上方
    gapx = np.maximum(0.30 * px_x - (X[ei] - X[ej]), 0.0)   # 也在父节点右边
    np.add.at(fy, ei, gapy * 0.5)
    np.add.at(fy, ej, -gapy * 0.5)
    np.add.at(fx, ei, gapx * 0.5)
    np.add.at(fx, ej, -gapx * 0.5)
    X += fx * 0.45 + (X0 - X) * pull_x
    Y += fy * 0.45 + (Y0 - Y) * pull_y
    np.clip(X, X0 - 5.0 * px_x, X0 + 5.0 * px_x, out=X)     # 只防解飞掉
    np.clip(Y, Y0 - 5.0 * px_y, Y0 + 5.0 * px_y, out=Y)

xy = {k: (float(X[i] / px_x), float(Y[i] / px_y)) for k, i in idx.items()}
drift = max(abs(xy[n["node_id"]][1] - midx[n["month"]]) for n in draw)

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

tops = [n for n in shoot if n["node_id"] not in has_child]
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

step = max(1, len(mshow) // 40)
hstep = 1 if x_max <= 14 else 2
fig.update_layout(
    height=fig_h, dragmode="pan", hovermode="closest",
    margin=dict(l=10, r=240, t=30, b=10),
    coloraxis=dict(colorscale="RdYlGn", cmin=-0.3, cmax=0.3,
                   colorbar=dict(title="超额中位", tickformat=".0%")),
    xaxis=dict(title="长到第几个月（大致）", showgrid=True, gridcolor="rgba(128,128,128,0.12)",
               tickmode="array", tickvals=list(range(0, top_h + 1, hstep)),
               ticktext=[f"第 {i + 1} 月" for i in range(0, top_h + 1, hstep)],
               range=[-1.0, x_max + 1.2]),
    yaxis=dict(title="", showgrid=True, gridcolor="rgba(128,128,128,0.15)",
               tickmode="array", tickvals=list(range(0, len(mshow), step)),
               ticktext=[mshow[i] for i in range(0, len(mshow), step)],
               range=[-1, len(mshow) + 1.5], automargin=True),
)
st.plotly_chart(fig, use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False})
st.caption(
    "**滚轮缩放、按住拖动**，双击回到初始视野。"
    "气泡不锁在格子上，位置是算出来的：**只有每支的起点钉在自己的日期上**，"
    "后面的球为了互相让开可以随便飘，靠杆认亲——相连两个球之间是一根定长的杆，"
    f"一根 = 一个月，数杆数就知道活了几个月。这个窗口里飘得最远的球偏了 {drift:.1f} 个月，"
    "所以后半段对着纵轴读日期只能读个大概，准确月份和月龄看悬停。"
    f"横轴初始只铺到第 {x_max + 1} 月（95% 的链都活不过这里），"
    f"最长那条活了 {top_h + 1} 个月，往右拖能看完。"
    "每支从自己诞生那个月起步，下个月还找得到成员重合 ≥ 20% 的后继就往右上接一根杆，"
    "找不到就停在原地。点越大成员越多，越绿这 63 天超额越高；"
    "杆连着的是同一支，从旧簇裂出来的新簇接着父节点继续往右上长；"
    "× = 这一支到此为止，下个月再没有成员对得上的后继。"
    "名字写在每支末端，互相压住的自动省略——放大就都出来了。"
    "并排的两条斜线是两条互不相干的链，不是分叉——近三年真正的分叉只有 12 处。"
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
