import html
from collections import Counter, defaultdict

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
    "是这一支从诞生算起长到第几个月，所以一条链是往右上角斜着长的，每个气泡都写当月的名字。"
    "**连线根据成员重合建立，颜色才表示超额涨跌**——上个月的簇和这个月的簇"
    "成员重合过半优先续成同一条链，所以一路杀跌的链照样能串成好几个月。"
    "红 = 超额为负，绿 = 为正。一条长红链的意思是「这批票被当成一伙一起被卖」，"
    "不是「这批票在涨」，链继续生长也不等于上涨。"
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
    f"≥ {params.get('continue_overlap')} 优先续接同一条链，"
    f"未续接但 ≥ {params.get('branch_overlap')} 就另建一条链并连上父节点——"
    f"一个父节点连出多个孩子才叫成员分叉。"
    f"连续 {params.get('death_months')} 个月超额中位非正，旧规则停止续接。"
    f"数据止于 {doc.get('sep_last_date')}，构建于 {doc.get('generated_at')}。"
)
n_status = Counter(n.get("theme_status") or "not_reviewed" for n in nodes)
st.caption(
    f"**名字怎么来的**：{n_status['supported']} 个节点的共同原因已用当月新闻逐条核对，"
    f"显示正式名称。判过但查不到共同原因、或组里存在多个原因该拆开的 "
    f"{n_status['unknown'] + n_status['mixed']} 个，显示「共同原因待确认」。"
    f"其余 {n_status['not_reviewed']} 个还没判读，沿用按当期成员业务归纳的旧名，"
    "短链退回行业与代表票。**待确认不等于分类错了**——本地新闻库有整月空缺"
    "（2025-08/09、2026-03 一条都没有），那些月份判不了。"
    "名字说明共同原因，不是涨跌预测或交易信号。逐月依据看下方「命名依据」。"
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
c4.metric("当月停止续接", len(died))

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
    """优先用后端判读后的 theme_title，没有则按行业与代表票回退。

    `theme_title` 由后端 theme_review.py 决定：判出共同原因的用正式名称，判过但没
    结论的显示「共同原因待确认」，没判过的沿用 theme_names.json 的旧名。老后端不返回
    这个字段时退回 theme_name。

    行业分类给不出横跨行业的名字——2020-03 那个 ZM/TDOC/ZS 的簇行业众数是
    「Electronic Gaming & Multimedia 16%」，纯凑数。占比写出来是让人自己判断这个名
    靠不靠谱：「Healthcare Plans 88%」可信，16% 就该看票。
    """
    if n.get("theme_title"):
        return n["theme_title"]
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
            symbol=[
                "circle-open" if n["month"] == last_month
                else "x" if n["node_id"] not in has_child
                else "circle"
                for n in shoot
            ],
            line=dict(width=0.5, color="rgba(0,0,0,0.55)"),
        ), **hover(shoot)))

def wrap_name(s: str, width: int = 8) -> str:
    """每 width 个原文字符折一行。分段各自转义再拼 <br>，别先转义再切——
    那样 &amp; 会被从中间切断，页面上冒出半个 HTML 实体。"""
    return "<br>".join(html.escape(s[i:i + width]) for i in range(0, len(s), width))


# 每个气泡都写名字，包括中间节点和只活一个月的。同名的月份也逐月重复写，不去重。
# 密集处会互相压住，靠缩放看——原来靠碰撞检测跳过，结果放大也不会恢复，等于把名字藏了。
fig.add_trace(go.Scatter(
    x=[xy[n["node_id"]][0] for n in draw], y=[xy[n["node_id"]][1] for n in draw],
    mode="text", text=[wrap_name(cluster_name(n)) for n in draw],
    textposition="bottom center", hoverinfo="skip", showlegend=False, cliponaxis=False,
    textfont=dict(size=13, color="rgba(230,230,230,0.92)")))

step = max(1, len(mshow) // 40)
hstep = 1 if x_max <= 14 else 2
fig.update_layout(
    height=fig_h, dragmode="pan", hovermode="closest",
    margin=dict(l=10, r=240, t=70, b=50),
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
    "**× = 未连出后继**，可能是匹配时选了别的父节点，也可能未达到连接条件，"
    "不代表投资失败。**空心圆 = 样本最后一个月**，尚无下月数据。"
    "每个气泡下面都写当月的名字，密集处会互相压住，滚轮放大能看清，不会被省略。"
    "并排的两条斜线各自是一条链，不是分叉；但当前图每个节点只画一个父节点，"
    "合流呈现不完整，别只靠位置就断定两条线互不相关。"
)

st.subheader("单条链的成员进出")
# 只要这条链有任一节点落在显示窗口里就能选，不要求出生月份在窗口内，也不要求活过两个月：
# 判读过的 3991、4001 所在的链都只有一个节点，卡掉就没法查它们的依据。
opts = sorted([v for v in vines if any(n["month"] in midx for n in by_vine[v["vine_id"]])],
              key=lambda v: (-v["n_nodes"], v["born_month"]))
if not opts:
    st.info("这个窗口里一个簇都没有，把左边窗口调长。")
else:
    def vine_label(v: dict) -> str:
        """中途改过名的链显示「首名 → 末名」，没改过只显示一次。

        只看后端给的 theme_title 变没变。回退名（行业 + 代表票）里代表票每月都在换，
        拿它比就到处都是「Steel 36%｜SHW/SNAP/PPG → Steel 36%｜TXN/SNAP/NUE」这种
        又长又没信息的标签。
        """
        seq = by_vine[v["vine_id"]]
        label = cluster_name(seq[0])
        if seq[0].get("theme_title") != seq[-1].get("theme_title"):
            label = f"{label} → {cluster_name(seq[-1])}"
        return f'{label}（{v["born_month"]} 起 {v["n_nodes"]} 个月）'

    pick = st.selectbox("选一条链", opts, format_func=vine_label)
    seq = by_vine[pick["vine_id"]]
    rows, prev = [], set()
    for n in seq:
        cur = set(n["members"])
        rows.append({"月份": n["month"],
                     "主题": cluster_name(n),
                     "新进": ", ".join(sorted(cur - prev)) if prev else ", ".join(sorted(cur)),
                     "退出": ", ".join(sorted(prev - cur)),
                     "留存": ", ".join(sorted(cur & prev))})
        prev = cur
    left, right = st.columns([3, 2])
    left.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    right.line_chart(pd.DataFrame({"超额中位": [n["excess_median"] for n in seq]},
                                  index=[n["month"] for n in seq]))
    if pick.get("died_month"):
        reason = {"no_successor": "下个月没有满足条件的后继簇",
                  "excess_negative": "连续两个月超额中位非正"}.get(
                      pick["death_reason"], pick["death_reason"])
        st.caption(f"旧规则在 {pick['died_month']} 对这条链停止续接：{reason}。"
                   f"峰值超额中位 {pick['peak_excess_median']:.1%}。")
    else:
        st.caption(f"这条链到 {last_month} 还在续接。峰值超额中位 {pick['peak_excess_median']:.1%}。")

    st.markdown("**命名依据**")
    mpick = st.selectbox("看哪个月", [n["month"] for n in seq],
                         index=len(seq) - 1, key="review_month")
    node = next(n for n in seq if n["month"] == mpick)
    status = node.get("theme_status") or "not_reviewed"
    rv = node.get("theme_review") or {}
    if status == "config_error":
        st.info("命名依据暂不可用：后端读判读配置失败。")
    elif not rv:
        st.info(f"{mpick} 这个节点还没做共同原因判读，名字沿用按成员业务归纳的旧名。"
                "本地新闻库有整月空缺的月份判不了，不是分类有问题。")
    else:
        head = {"supported": "有共同逻辑", "mixed": "混合待拆",
                "unknown": "共同原因待确认"}[status]
        st.markdown(f"**{head}**　{cluster_name(node)}")
        st.markdown(rv.get("reason") or "—")
        if rv.get("inherit_from_parent"):
            st.caption("这个月沿用了上个月同一条链的结论，不是重新找到的原因。")
        for w in rv.get("weak_members") or []:
            st.caption(f"不符合的成员 {w.get('ticker')}"
                       f"（贴合度 {w.get('corr')}）：{w.get('note')}")
        if rv.get("sources"):
            st.markdown("来源（日期都不晚于本节点月份）：")
            for s in rv["sources"]:
                st.markdown(f"- {s.get('date')}　`{s.get('source')}`　"
                            f"{s.get('title')} → {s.get('claim')}")
        for g in rv.get("split_proposal") or []:
            st.markdown(f"拆分建议「{g.get('name')}」（{len(g.get('members') or [])} 只）："
                        f"{g.get('reason')}")
            st.caption(", ".join(g.get("members") or []))
        if rv.get("split_proposal"):
            st.caption("建议里没列到的成员算未归类，不代表它们属于其中任何一组。"
                       "拆分建议只是研究结果，没有改成员和连线。")
        if rv.get("notes"):
            st.caption(f"备注：{rv['notes']}")

st.subheader(f"{last_month} 的合格簇")
cur_nodes = sorted([n for n in nodes if n["month"] == last_month],
                   key=lambda n: -n["excess_median"])
st.dataframe(pd.DataFrame([{
    "主题": cluster_name(n), "行业构成": mix_line(n), "成员数": n["n"],
    "簇内相关": n["internal_corr"], "超额中位%": round(n["excess_median"] * 100, 1),
    "代表": ", ".join(n.get("biggest") or []), "领跑": ", ".join(n["leaders"]),
    "已活月数": height[n["node_id"]] + 1,
} for n in cur_nodes]), use_container_width=True, hide_index=True,
    column_config={"超额中位%": st.column_config.NumberColumn(format="%.1f"),
                   "簇内相关": st.column_config.NumberColumn(format="%.2f")})
