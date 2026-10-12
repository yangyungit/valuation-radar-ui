"""BTC VMD 信号：日线拆 VMD，第 5、4 / 3 / 2 层的实时拐点分别标在 4 小时 / 日线 / 周线 K 线上。

拆层、每天重拆、信号判定、统计和回测全在后端 crypto/vmd_cta.py，这页只负责展示。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from api_client import fetch_crypto_vmd_cta, fetch_crypto_vmd_cycle

st.set_page_config(page_title="BTC VMD 信号", layout="wide", page_icon="₿")

CHART_LABEL = {"4h": "4H", "1d": "1D", "1w": "1W"}
UP, DOWN = "#26a69a", "#ef5350"

st.title("₿ BTC VMD 信号")

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_crypto_vmd_cta.clear()
        fetch_crypto_vmd_cycle.clear()
        st.rerun()

res = fetch_crypto_vmd_cta()
if not res.get("success"):
    st.error(f"⚠️ 后端拿不到 VMD 信号：{res.get('error', '未知错误')}")
    st.stop()
if res["klines_stale"]:
    st.warning(f"K 线拉取失败，显示的是缓存，截至 {res['klines_as_of']} UTC")

pct = lambda v: "" if v is None else f"{v:+.1%}"
share = lambda v: "" if v is None else f"{v:.0%}"

for col, lay in zip(st.columns(len(res["layers"])), res["layers"]):
    s = lay["state"]
    label = f"{CHART_LABEL[lay['chart']]} · {lay['name']}（约 {lay['period']} 天）"
    if s["since"] is None:
        col.metric(label, s["side"], "还没有信号", "off")
    else:
        col.metric(label, s["side"], f"{s['since'][5:]} 起 · 第 {s['days']} 天",
                   "normal" if s["side"] == "多" else "inverse")


def _x(chart: str, d: str) -> pd.Timestamp:
    """信号日 → K 线上的位置：4h 标在次日 00:00 那根（收盘后才知道），周 K 标在当周周一开盘那根。"""
    t = pd.Timestamp(d)
    if chart == "4h":
        return t + pd.Timedelta(days=1)
    if chart == "1w":
        return t - pd.Timedelta(days=t.weekday())
    return t


def _big_up_spans(rt: list[dict], th: float = 0.03) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """大势实时值从最低点回升超过 th 算转向上，从最高点回落超过 th 算转向下；周日收盘才算出来，从次日开始染。
    不用每次拆出来的末端 7 天斜率：VMD 末端最不准，那个斜率每周在零附近来回翻。"""
    spans, start, up, ext = [], None, False, rt[0]["big"]
    for r in rt[1:]:
        v = r["big"]
        ext = max(ext, v) if up else min(ext, v)
        if abs(v - ext) <= th:
            continue
        up, ext = not up, v
        d = pd.Timestamp(r["date"]) + pd.Timedelta(days=1)
        if up:
            start = d
        else:
            spans.append((start, d))
            start = None
    if start is not None:
        spans.append((start, pd.Timestamp.max))
    return spans


def _cta_chart(lay: dict, kl: dict, big_up: list | None) -> go.Figure:
    chart = lay["chart"]
    t = pd.to_datetime(kl["t"])
    bars = pd.DataFrame({"c": kl["c"]}, index=t)
    t0, t1 = t[0], t[-1]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Scatter(x=t, y=bars["c"], mode="lines", name="BTCUSDT",
                             line=dict(color="#4a9eff", width=1.5)), 1, 1)

    sig = lay["signals"]
    for x0, x1 in big_up or []:
        x0, x1 = max(x0, t0), min(x1, t1)
        if x0 < x1:
            fig.add_vrect(x0=x0, x1=x1, fillcolor="rgba(150,150,150,0.15)", line_width=0, row=1, col=1)

    def pts(items: list[dict], kind: str, factor: float) -> tuple[list, list]:
        xs, ys = [], []
        for s in items:
            if s["kind"] != kind:
                continue
            x = _x(chart, s["date"])
            if x in bars.index:
                xs.append(x)
                ys.append(bars.at[x, "c"] * factor)
        return xs, ys

    for kind, sym, color, text, pos, f in (("低点", "triangle-up", UP, "多", "bottom center", 0.97),
                                           ("高点", "triangle-down", DOWN, "空", "top center", 1.03)):
        xs, ys = pts(sig, kind, f)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", name=text,
                                 marker=dict(symbol=sym, size=12, color=color),
                                 text=[text] * len(xs), textposition=pos,
                                 textfont=dict(color=color)), 1, 1)
    wx, wy = [], []
    for kind, f in (("低点", 0.985), ("高点", 1.015)):
        xs, ys = pts(lay["weak"], kind, f)
        wx += xs
        wy += ys
    fig.add_trace(go.Scatter(x=wx, y=wy, mode="markers", name="非信号",
                             marker=dict(symbol="circle", size=5, color="#999")), 1, 1)

    rt = pd.Series(lay["realtime"]["value"], index=pd.to_datetime(lay["realtime"]["dates"]))
    rt = rt[rt.index >= t0.normalize()]
    fig.add_trace(go.Scatter(x=rt.index, y=rt.values, line=dict(color="#e67e22", width=1.2),
                             name=f"{lay['name']}（每天当时看到的）"), 2, 1)
    if lay["key"] == "l5":
        gaps = pd.to_datetime([s["date"] for s in sig]).to_series().diff().dt.days.dropna()
        lo, mid, hi = (pd.Timedelta(days=d) for d in gaps.quantile([0.1, 0.5, 0.9]).round())
        # 斜率变号那天才出信号，橙线拐点在前一天
        turns = [(pd.Timestamp(s["date"]) - pd.Timedelta(days=1), s["kind"]) for s in sig]
        turns = [(d, k) for d, k in turns if d >= t0.normalize()]

        def vline(x, color, dash):
            fig.add_shape(type="line", xref="x", yref="y2 domain", x0=x, x1=x, y0=0, y1=1,
                          line=dict(color=color, width=1, dash=dash), opacity=0.7)

        for i, (d, k) in enumerate(turns):
            vline(d, DOWN if k == "高点" else UP, "dash")
            if i:
                prev = turns[i - 1][0]
                fig.add_annotation(x=prev + (d - prev) / 2, y=1, xref="x", yref="y2 domain", yanchor="top",
                                   text=str((d - prev).days), showarrow=False, font=dict(size=10, color="#aaa"))
        if turns:
            d, k = turns[-1]
            color = UP if k == "高点" else DOWN
            fig.add_shape(type="rect", xref="x", yref="y2 domain", x0=d + lo, x1=d + hi, y0=0, y1=1,
                          fillcolor=color, opacity=0.12, line_width=0)
            vline(d + mid, color, "dot")
            fig.add_annotation(x=d + mid, y=1, xref="x", yref="y2 domain", yanchor="top",
                               text=f"预计 {(d + mid):%m-%d}", showarrow=False, font=dict(size=10, color=color))

    fig.update_yaxes(title_text="BTC", type="linear" if chart == "4h" else "log", gridcolor="#222", row=1, col=1)
    fig.update_yaxes(title_text="log 偏离", gridcolor="#222", zeroline=True, zerolinecolor="#555", row=2, col=1)
    xfmt = "%Y-%m-%d %H:%M" if chart == "4h" else "%Y-%m-%d"
    fig.update_traces(hovertemplate=f"%{{x|{xfmt}}}<br>%{{y:,.3~f}}<extra>%{{fullData.name}}</extra>")
    fig.update_traces(hovertemplate=f"%{{x|{xfmt}}}<br>$%{{y:,.0f}}<extra>%{{fullData.name}}</extra>",
                      row=1, col=1)
    # plotly 的 across 竖线只跨「用同一根 x 轴」的子图，所以两行都挂到 x 上
    fig.update_traces(xaxis="x")
    fig.update_xaxes(gridcolor="#222", hoverformat=xfmt)
    fig.update_xaxes(anchor="y2", matches=None, showticklabels=True,
                     showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikedash="dot", spikecolor="#888", row=1, col=1)
    fig.update_layout(
        title=f"{CHART_LABEL[chart]} · {lay['name']}（约 {lay['period']} 天一轮） · 斜率看 {lay['slope_days']} 天",
        height=620, xaxis_rangeslider_visible=False, margin=dict(l=60, r=20, t=70, b=30),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a", font=dict(color="#ccc"),
        hovermode="closest", spikedistance=-1, xaxis2_visible=False,
        legend=dict(orientation="h", y=1.04, x=0))
    return fig


vmd = fetch_crypto_vmd_cycle()
big_up = _big_up_spans(vmd["realtime"]) if vmd.get("success") else None
for lay in res["layers"]:
    a, b = lay["fwd"]
    st.plotly_chart(_cta_chart(lay, res["klines"][lay["chart"]], big_up), width="stretch")
    st.dataframe(pd.DataFrame([{
        "信号": g["group"], "次数": g["n"],
        f"{a} 天中位收益": pct(g["median_a"]), f"{a} 天上涨比例": share(g["up_a"]),
        f"{b} 天中位收益": pct(g["median_b"]), f"{b} 天上涨比例": share(g["up_b"]),
    } for g in lay["stats"]]), hide_index=True, width="stretch")
    bt = lay["backtest"]
    st.dataframe(pd.DataFrame([{
        "起点": bt["start"], "策略年化": pct(bt["cagr"]), "策略最大回撤": pct(bt["mdd"]),
        "在场时间": share(bt["exposure"]), "开仓次数": bt["trades"],
        "持有 BTC 年化": pct(bt["hold_cagr"]), "持有 BTC 最大回撤": pct(bt["hold_mdd"]),
    }]), hide_index=True, width="stretch")
    with st.expander("最近 10 个信号"):
        st.dataframe(pd.DataFrame([{
            "日期": s["date"], "信号": s["kind"], "价格": f"${s['price']:,.0f}",
            f"{a} 天后": "未满" if s["ret_a"] is None else pct(s["ret_a"]),
            f"{b} 天后": "未满" if s["ret_b"] is None else pct(s["ret_b"]),
        } for s in reversed(lay["signals"][-10:])]), hide_index=True, width="stretch")

st.caption(
    "四层都是用 BTC 日收盘价（CoinMetrics，2011 起）减掉幂律趋势后拆 VMD 8 层得到的，取第 5、4、3、2 层"
    "（约 19 / 38 / 99 / 265 天一轮），第 5、4 层都配 4 小时图。从 2014-11 起**每天只用当天以前的数据重拆一次**，"
    "记下这一层在「当天」的值，下方橙线就是它。信号看橙线自身的斜率（19、38 天层看 1 天、99 天层看 3 天、265 天层看 7 天），"
    "橙线走平拐头、斜率由负转正且在零线下记「多」，"
    "由正转负且在零线上记「空」，多空必须交替，被筛掉的翻转画成灰点。"
    "第 5 层下方橙线图上，虚线是橙线实际拐点（红峰绿谷），中间数字是相邻拐点隔了几天；"
    "最近一个拐点后面的淡色底是下一个拐点的预计时间，点线是历史间隔中位数、淡色底是 80% 的间隔范围，"
    "只说明按节奏差不多该到了，不保证会出。灰底是大势向上的区间：每周日只用当时数据重拆一次记下大势当天的值，"
    "从最低点回升超过 0.03 就从次日起染灰，从最高点回落超过 0.03 就结束。"
    "信号日期按 UTC 日，4 小时图上标在信号日次日 00:00 UTC 那根。"
    "回测只做多、空头拿现金、信号后再晚一天进出、单边手续费 0.1%。"
    "VMD 末端最不准，拐点会滞后、会有假信号；page31 原来的小势拐点没跑赢随便买，"
    "这里的回测表就是看第 3、4、5 层是不是更好。"
    f"只作参考，不进 D 策略规则；数据截至 {res['as_of']}。"
)

st.divider()
st.subheader("VMD 四层拆解")
if not vmd.get("success"):
    st.warning(f"⚠️ VMD 不可用：{vmd.get('error', '未知错误')}")
else:
    vs = vmd["stats"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("1 年后外推", f"${vmd['fut'][-1]:,.0f}", f"现价 ${vmd['price'][-1]:,.0f}", "off")
    if vs.get("n"):
        k2.metric("历次重测方向命中", f"{vs['hit']:.0%}", f"已走完 {vs['n']} 次", "off")
        k3.metric("误差中位数", f"{vs['median_err']:.0%}")
        k4.metric("最差一次", f"差 {vs['worst_ratio']:.1f} 倍")

    vd, vf = pd.to_datetime(vmd["dates"]), pd.to_datetime(vmd["fut_dates"])
    rt = pd.DataFrame(vmd["realtime"])
    rt["date"] = pd.to_datetime(rt["date"])
    big_p, small_p, l3_p, l4_p = vmd["periods"]
    vfig = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                         row_heights=[0.36, 0.16, 0.16, 0.16, 0.16],
                         subplot_titles=("价格 = 趋势 × 大势 × 小势", f"大势（约 {big_p} 天一轮）",
                                         f"小势（约 {small_p} 天一轮）", f"第 3 层（约 {l3_p} 天一轮）",
                                         f"第 4 层（约 {l4_p} 天一轮）"))
    vfig.add_trace(go.Scatter(x=vd, y=vmd["price"], name="BTC 价格", line=dict(color="#ddd", width=1)), 1, 1)
    vfig.add_trace(go.Scatter(x=vd.append(vf), y=vmd["trend"] + vmd["fut_trend"], name="幂律趋势",
                              line=dict(color="#4fc3e8", width=1.2, dash="dot")), 1, 1)
    vfig.add_trace(go.Scatter(x=vd, y=vmd["fitted"], name="趋势 + 大势 + 小势（用了全部历史）",
                              line=dict(color="#f39c12", width=1.4)), 1, 1)
    vfig.add_trace(go.Scatter(x=vf, y=vmd["fut"], name="当前外推 1 年",
                              line=dict(color="#e74c3c", width=2, dash="dash")), 1, 1)
    vfig.add_trace(go.Scatter(x=rt["date"], y=rt["big"], name="大势（每周当时看到的）",
                              line=dict(color="#9b59b6", width=1.6)), 2, 1)
    vfig.add_trace(go.Scatter(x=vf, y=vmd["fut_big"], showlegend=False,
                              line=dict(color="#9b59b6", width=1.6, dash="dash")), 2, 1)
    vfig.add_trace(go.Scatter(x=rt["date"], y=rt["small"], name="小势（每周当时看到的）",
                              line=dict(color="#1abc9c", width=1.2)), 3, 1)
    lay_rt = {l["key"]: l["realtime"] for l in res["layers"]}
    for key, row, color in (("l3", 4, "#3498db"), ("l4", 5, "#e67e22")):
        vfig.add_trace(go.Scatter(x=pd.to_datetime(lay_rt[key]["dates"]), y=lay_rt[key]["value"],
                                  name=f"第 {key[1]} 层（每天当时看到的）", showlegend=False,
                                  line=dict(color=color, width=1)), row, 1)
    vfig.update_traces(hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.3~f}<extra>%{fullData.name}</extra>")
    vfig.update_traces(hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>%{fullData.name}</extra>", row=1, col=1)
    # plotly 的 across 竖线只跨「用同一根 x 轴」的子图，所以所有行都挂到 x 上
    vfig.update_traces(xaxis="x")
    vfig.update_yaxes(title_text="BTC（对数）", type="log", row=1, col=1)
    vfig.update_yaxes(title_text="log 偏离", row=2, col=1)
    vfig.update_yaxes(title_text="log 偏离", row=3, col=1)
    vfig.update_yaxes(title_text="log 偏离", row=4, col=1)
    vfig.update_yaxes(title_text="log 偏离", row=5, col=1)
    vfig.update_yaxes(gridcolor="#222", zeroline=True, zerolinecolor="#555")
    vfig.update_xaxes(gridcolor="#222", hoverformat="%Y-%m-%d")
    vfig.update_xaxes(anchor="y5", matches=None, showticklabels=True,
                      showspikes=True, spikemode="across", spikesnap="cursor",
                      spikethickness=1, spikedash="dot", spikecolor="#888", row=1, col=1)
    vfig.update_layout(height=1200, margin=dict(l=60, r=20, t=50, b=30),
                       plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                       font=dict(color="#ccc"), hovermode="closest", spikedistance=-1,
                       xaxis2_visible=False, xaxis3_visible=False, xaxis4_visible=False,
                       xaxis5_visible=False,
                       legend=dict(orientation="h", y=1.05, x=0))
    st.plotly_chart(vfig, width="stretch")

    st.caption(
        f"做法：和上面同一条幂律趋势，剩下的波动用 VMD 拆 {vmd['k']} 层，取最慢两层：大势约 {big_p} 天、"
        f"小势约 {small_p} 天一轮，合起来占波动的九成以上。两层各按自己的频率拟合正弦外推 {vmd['horizon']} 天，"
        "加回趋势就是红色虚线。第 3、4 层合计约占波动 2.5%，只画出来看，不进外推。价格图里的橙线是用全部历史拆的，顶底看着准是因为看到了后面的走势，不能当信号。"
        "紫线（大势）和绿线（小势）是实时版：2014 年起每周只用当时已有数据重拆一次，记下「当天」的值，事后不会被改；"
        "第 3、4 层同样是实时版，和上方信号图的橙线是同一份数据（每天重拆一次）。"
        "VMD 末端最不准，当时看到的值和事后曲线差很多，所以拐点滞后、假信号多。紫色虚线外推接在最新一次拆解后面。"
        f"只作参考证据，不改 D 策略的买卖规则；不受左侧时间窗影响，数据截至 {vmd['as_of']}。"
    )
