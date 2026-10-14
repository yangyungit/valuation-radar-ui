"""ETF 动量轮动（3 仓 + 排名缓冲）：10 只资产类 ETF，月末收盘站上 10 月均线才进候选，按 12 月收益取前 3；
已持有的只要还在前 6 名就不换。

信号、净值、统计全在后端 etf_tsmom.py，这页只负责展示。
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_etf_tsmom
from gold_leader_viz import render_equity_chart, render_slot_segment_returns, render_time_window_slider

st.set_page_config(page_title="ETF轮动 3仓", layout="wide")

st.title("🧭 ETF 动量轮动（3 仓）")

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_etf_tsmom.clear()
        st.rerun()

st.caption(
    "**规则**：10 只资产类 ETF（美股 SPY/QQQ/IWM、海外 EFA/EEM、美债 TLT/IEF、黄金 GLD、地产 VNQ、商品 DBC），"
    "每月末收盘高于自己 10 个月均线的才进候选，候选里按 12 个月总收益取前 3 只、各 1/3，下月第一个交易日换仓；"
    "候选不足 3 只的空槽拿 3 个月国债。单边成本 10bps。\n\n"
    "**排名缓冲**（2026-10-14 加）：已持有的只要还站在均线上且排名不低于第 6，就不换；空出来的槽才按排名补。"
    "没加缓冲时第 2、3、4 名来回互换全变成实打实的换仓，235 个月里 132 个月有动作；加了之后 65 个月，"
    "换手 2.66→1.27/年，CAGR 9.0→9.2、回撤 −21.7→−21.4。缓冲 1 到 7 换手单调下降、CAGR 一直在 9±1，不是挑参数挑出来的。"
    "顺带一提：缩到 2 仓 / 1 仓是反方向，换手反而升到 3.4 / 3.8，回撤 −27% / −33%。\n\n"
    "**定位**：防守底仓，不是进攻仓。回测 2007-03→2026-09 CAGR 9.2% / 最大回撤 −21.4%（SPY 11.0% / −50.8%），"
    "CAGR 输 SPY 约 2 个点，回撤只有 SPY 四成多。\n\n"
    "**三条警告**：① round32 预注册判据三条都是擦线过（全程 CAGR 只比门槛多 1 个点），而且缓冲不在预注册里，是事后加的；"
    "同表 V1 均线等权 Calmar 0.70 更高但 CAGR 只有 6.3%。"
    "② 最大回撤出在 2008-06→10，当时 1/3 仓位压在 DBC（商品下半年腰斩），集中 3 只的代价是回撤比 10 只等权深一倍。"
    "③ EEM 跟踪 MSCI 新兴市场，2018 年起含少量中国 A 股。"
)

res = fetch_etf_tsmom()
if not res.get("success"):
    st.error(f"⚠️ 数据暂不可用：{res.get('error', '未知错误')}")
    st.stop()

cur, pv = res["current"], res.get("preview")
table = res["table"]
tickers = [r["ticker"] for r in table]


def _fmt_hold(holdings: list) -> str:
    s = " / ".join(holdings)
    return s + " + 现金" if len(holdings) < 3 else s


c1, c2, c3 = st.columns(3)
c1.metric(f"本月持有（{cur['month']}）", _fmt_hold(cur["holdings"]))
if pv is None:
    c2.metric("预览下月持仓", "本月已走完，见左")
else:
    if pv["add"] or pv["drop"]:
        delta = f"换入 {'、'.join(pv['add']) or '无'}，换出 {'、'.join(pv['drop']) or '无'}"
    else:
        delta = "不变"
    c2.metric(f"按 {pv['asof']} 收盘预览 {pv['month']}", _fmt_hold(pv["holdings"]), delta=delta, delta_color="off")
c3.metric("数据截至", res["asof"], help=f"{res['price_note']}；现金：{res['cash_source']}")

# ---- 信号表 ----
st.markdown(f"#### 信号表（{res['signal_month']} 月末）")


def _pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def _num(v):
    return "—" if v is None else f"{v:,.2f}"


def _rank(v):
    return "—" if v is None else str(int(v))


def _ok(v):
    return "—" if v is None else ("✓" if v else "✗")


rows = []
for r in table:
    row = {
        "ETF": f"{r['name']} {r['ticker']}",
        "月末收盘": _num(r["close"]),
        "MA10": _num(r["ma10"]),
        "站上均线": _ok(r["above_ma"]),
        "12M收益": _pct(r["mom12"]),
        "排名": _rank(r["rank"]),
        "本月持有": "✓" if r["held"] else "",
    }
    if pv is not None:
        row["预览·站上均线"] = _ok(r["pv_above_ma"])
        row["预览·12M"] = _pct(r["pv_mom12"])
        row["预览·排名"] = _rank(r["pv_rank"])
    rows.append(row)
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---- 净值 + 回撤 ----
nav = res["nav"]
dates = pd.to_datetime(nav["dates"])
STYLE = {
    "V4": ("#F1C40F", 2.5),
    "SPY": ("rgba(170,178,189,0.75)", 1.5),
}
series = {k: pd.Series(nav[k], index=dates, dtype="float64") for k in STYLE}

SLOTS = [("slot1", "槽A", "#2ECC71"), ("slot2", "槽B", "#E74C3C"), ("slot3", "槽C", "#3498DB")]
st.markdown("#### 净值（2007-03 = 1）")
win_lo, win_hi = render_time_window_slider(dates, "etf")
render_equity_chart(dates, nav, [
    ("V4", f"V4 合成 {series['V4'].iloc[-1]:.2f}", STYLE["V4"][0], True, None, 2.5),
    ("SPY", f"SPY {series['SPY'].iloc[-1]:.2f}", STYLE["SPY"][0], True, None, 1.5),
    *[(k, name, color, True, None, 1) for k, name, color in SLOTS if k in nav],
], "etf_nav", win_lo, win_hi)
st.caption("黄线 = 3 仓合成净值。细线 = 三个仓位各自的净值：一只 ETF 买入后一直占同一个槽，卖出时换入者接它的槽，"
           "槽空着的月份拿现金。每条细线是该仓 100% 的收益，不是 1/3 仓位的收益。")

def _nav_kpi(s: pd.Series) -> dict:
    """月度净值的 CAGR / MaxDD / Calmar / Sortino / logR²（口径同 32 页统计卡，月频按 √12 年化）。"""
    years = (len(s) - 1) / 12
    cagr = (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1
    max_dd = (s / s.cummax() - 1).min()
    neg = s.pct_change().dropna()
    neg = neg[neg < 0]
    log_nav = np.log(s.values)
    x = np.arange(len(log_nav))
    resid = log_nav - np.polyval(np.polyfit(x, log_nav, 1), x)
    return {
        "cum": s.iloc[-1] / s.iloc[0] - 1, "cagr": cagr, "max_dd": max_dd, "calmar": cagr / abs(max_dd),
        "sortino": cagr / (neg.std() * 12 ** 0.5),
        "r2": 1 - (resid ** 2).sum() / ((log_nav - log_nav.mean()) ** 2).sum(),
    }


_k, _k_spy = _nav_kpi(series["V4"]), _nav_kpi(series["SPY"])
_turnover = res["stats"]["全程"]["V4"]["换手/年"]
_held = [set(h["holdings"]) for h in res["holdings_history"]]
_n_switch = sum(1 for a, b in zip(_held, _held[1:]) if a != b)
st.markdown("##### 统计卡（V4 合成，全程）")
for _row in (
    [("总收益", f"{_k['cum'] * 100:.0f}%"), ("CAGR", f"{_k['cagr'] * 100:.1f}%"),
     ("MaxDD", f"{_k['max_dd'] * 100:.1f}%"), ("Calmar", f"{_k['calmar']:.2f}"),
     ("CAGR 超额 vs SPY", f"{(_k['cagr'] - _k_spy['cagr']) * 100:+.1f}%")],
    [("换仓次数", f"{_n_switch}"), ("年化换手", f"{_turnover:.2f}"),
     ("Sortino", f"{_k['sortino']:.2f}"), ("logR²", f"{_k['r2']:.2f}")],
):
    for _col, (_label, _val) in zip(st.columns(len(_row)), _row):
        _col.metric(_label, _val)
st.caption(f"SPY 对照：总收益 {_k_spy['cum'] * 100:.0f}% / CAGR {_k_spy['cagr'] * 100:.1f}% / "
           f"MaxDD {_k_spy['max_dd'] * 100:.1f}% / Calmar {_k_spy['calmar']:.2f} / "
           f"Sortino {_k_spy['sortino']:.2f} / logR² {_k_spy['r2']:.2f}。统计按全程算，不跟随时间窗口滑块。")

st.markdown("#### 仓位接力")
if not render_slot_segment_returns(
    [{"slot": i, "equity": nav[k]} for i, (k, _, _) in enumerate(SLOTS) if k in nav],
    res.get("slot_timeline") or [], dates, nav["SPY"], "etf", win_lo, win_hi,
):
    st.caption("后端暂未返回仓位明细，请重启后端。")

fig_dd = go.Figure()
for k, (color, width) in STYLE.items():
    s = series[k]
    dd = s / s.cummax() - 1
    fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values, name=k, line=dict(color=color, width=width)))
fig_dd.update_layout(title="回撤", yaxis_tickformat=".0%", height=220, template="plotly_dark",
                     margin=dict(t=40, b=10), hovermode="x unified")
st.plotly_chart(fig_dd, width="stretch")

# ---- 持仓条带 ----
hist = res["holdings_history"]
months = [h["month"] for h in hist]
held_sets = [set(h["holdings"]) for h in hist]
n_months = len(hist)
n_switch = sum(1 for a, b in zip(held_sets, held_sets[1:]) if a != b)

z, ylabels = [], []
for t in tickers:
    flags = [1 if t in s else 0 for s in held_sets]
    z.append(flags)
    ylabels.append(f"{t} {sum(flags) / n_months * 100:.0f}%")

with st.expander(f"逐月持仓（共 {n_switch} 次换仓 / {n_months} 个月）"):
    fig_h = go.Figure(go.Heatmap(z=z, x=months, y=ylabels, zmin=0, zmax=1,
                                 colorscale=[[0, "#1f2329"], [1, "#d62728"]], showscale=False,
                                 xgap=1, ygap=1))
    fig_h.update_layout(height=360, margin=dict(t=10, b=10), template="plotly_dark",
                        yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_h, width="stretch")

# ---- 分段统计 ----
st.markdown("#### 分段统计")
st.caption(
    "**V4** = 本页策略（站上 10 月均线的里挑 12 月涨幅前 3 只，各 1/3，已持有的在前 6 名内不换）。"
    "**60/40** = 60% SPY + 40% IEF（7-10 年美债），固定不动，华尔街最经典的股债组合，"
    "用来回答「轮动值不值得折腾，还是直接买 60/40 就行」。"
    "**V1** = 10 只里每只站上 10 月均线的各放 1/10，不排名、不限数量，没站上的那份拿现金。"
    "**SPY** = 100% 标普 500。"
)
tabs = st.tabs(["全程", "前半 2007-2016", "后半 2017-至今"])
for tab, seg in zip(tabs, ["全程", "前半 2007-2016", "后半 2017-至今"]):
    with tab:
        st.dataframe(pd.DataFrame(res["stats"][seg]).T, width="stretch")

# ---- 换仓记录 ----
with st.expander("换仓记录（最近 36 个月）"):
    log = []
    for i in range(max(1, n_months - 36), n_months):
        prev, now = held_sets[i - 1], held_sets[i]
        if prev == now:
            continue
        log.append({
            "生效月": months[i],
            "换入": "、".join(t for t in tickers if t in now - prev) or "—",
            "换出": "、".join(t for t in tickers if t in prev - now) or "—",
            "持仓": " / ".join(hist[i]["holdings"]),
        })
    st.dataframe(pd.DataFrame(log[::-1]), hide_index=True, width="stretch")
