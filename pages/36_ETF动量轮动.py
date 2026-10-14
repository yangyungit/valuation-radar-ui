"""ETF 动量轮动（3 仓）：10 只资产类 ETF，月末收盘站上 10 月均线才进候选，按 12 月收益取前 3。

信号、净值、统计全在后端 etf_tsmom.py，这页只负责展示。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_etf_tsmom
from gold_leader_viz import render_equity_chart

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
    "**定位**：防守底仓，不是进攻仓。回测 2007-03→2026-09 CAGR 9.0% / 最大回撤 −21.7%（SPY 11.0% / −50.8%），"
    "CAGR 输 SPY 约 2 个点，回撤只有 SPY 四成多。\n\n"
    "**三条警告**：① round32 预注册判据三条都是擦线过（全程 CAGR 只比门槛多 1 个点）；"
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
    "SPY": ("#3498DB", 1.5),
}
series = {k: pd.Series(nav[k], index=dates, dtype="float64") for k in STYLE}

SLOTS = [("slot1", "第1强", "#2ECC71"), ("slot2", "第2强", "#E74C3C"), ("slot3", "第3强", "#9B59B6")]
st.markdown("#### 净值（2007-03 = 1）")
render_equity_chart(dates, nav, [
    ("V4", f"V4 合成 {series['V4'].iloc[-1]:.2f}", STYLE["V4"][0], True, None, 2.5),
    ("SPY", f"SPY {series['SPY'].iloc[-1]:.2f}", STYLE["SPY"][0], True, None, 1.5),
    *[(k, f"{name}仓", color, True, None, 1) for k, name, color in SLOTS if k in nav],
], "etf_nav")
st.caption("黄线 = 3 仓合成净值。细线 = 按 12 月涨幅排第 1/2/3 的那一仓单独的净值（没排上的月份拿现金），"
           "每条细线是一仓的收益，不是 1/3 仓位的收益。")

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

st.markdown(f"#### 逐月持仓（共 {n_switch} 次换仓 / {n_months} 个月）")
fig_h = go.Figure(go.Heatmap(z=z, x=months, y=ylabels, zmin=0, zmax=1,
                             colorscale=[[0, "#f2f2f2"], [1, "#d62728"]], showscale=False,
                             xgap=1, ygap=1))
fig_h.update_layout(height=360, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed"))
st.plotly_chart(fig_h, width="stretch")

# ---- 分段统计 ----
st.markdown("#### 分段统计")
st.caption(
    "**V4** = 本页策略（站上 10 月均线的里挑 12 月涨幅前 3 只，各 1/3）。"
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
