"""优质股深跌：回购 FCF 年度池成员距 252 日高点回撤 ≥40% 时，次日买入、持有 252 个交易日。

回测依据：10 年 74 次信号，持有 252 日相对 SPY 平均 +25.1%、中位 +20.3%、胜率 61%；
对照组（池内每月末无条件买）平均 +1.0%、中位 −1.7%、胜率 47%。
信号和统计全在后端 macro_engine.compute_quality_deep_drawdown，这页只负责展示。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_quality_deep_drawdown

st.set_page_config(page_title="优质股深跌", layout="wide", page_icon="📉")

st.title("📉 优质股深跌")

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_quality_deep_drawdown.clear()
        st.rerun()

res = fetch_quality_deep_drawdown()
if not res.get("success"):
    st.error(f"⚠️ 后端拿不到数据：{res.get('error')}")
    st.stop()

threshold, rearm, watch = res["threshold"], res["rearm"], res["watch"]
hold_days, pool_year = res["hold_days"], res["pool_year"]
members, active, events = res["members"], res["active"], res["events"]
pf = res["portfolio"]
shock_th, n_slots = res["earn_shock_th"], res["slots"]

st.caption(
    f"回购 FCF 优质池（每年按财报重建 40 只）里，复权价距 252 日高点回撤 ≥{threshold:.0f}% 时，"
    f"次日收盘买入、持有 {hold_days} 个交易日。回撤收窄到 {rearm:.0f}% 以内才重新计数。"
    f"回撤 {watch:.0f}–{threshold:.0f}% 只标观察区，不算信号。"
    f"组合按 {n_slots} 个仓位跑：回撤期间某次财报日（含次日）单日跑输 SPY 超 {shock_th:.0f}% 的信号跳过，"
    "其余先到先得、满仓跳过、持满即卖，空仓位放 SPY。"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("当年池", f"{pool_year} · {len(members)} 只")
c2.metric("持有期内信号", len(active))
c3.metric("观察区", sum(1 for m in members if m["status"] == "观察区"))
c4.metric("数据截至", res["as_of"])

# ---- 2 仓位策略 ----
st.subheader(f"{n_slots} 仓位策略")
k = pf["kpi"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("策略年化", f"{k['filtered']['cagr']:.1f}%", f"SPY {k['spy']['cagr']:.1f}%")
c2.metric("最大回撤", f"{k['filtered']['mdd']:.1f}%", f"SPY {k['spy']['mdd']:.1f}%", delta_color="off")
c3.metric("买入次数 / 跑赢 SPY", f"{k['filtered']['n_buys']} / {k['filtered']['n_win']}")
c4.metric("不过滤对照年化", f"{k['raw']['cagr']:.1f}%", f"回撤 {k['raw']['mdd']:.1f}%", delta_color="off")

nav_fig = go.Figure()
nav_fig.add_trace(go.Scatter(x=pf["dates"], y=pf["nav"], mode="lines",
                             name=f"加财报日暴跌过滤 {k['filtered']['multiple']:.0f} 倍",
                             line=dict(color="#c0392b", width=2)))
nav_fig.add_trace(go.Scatter(x=pf["dates"], y=pf["nav_raw"], mode="lines", name="不过滤对照",
                             line=dict(color="#e59866", dash="dash")))
nav_fig.add_trace(go.Scatter(x=pf["dates"], y=pf["spy"], mode="lines", name="SPY",
                             line=dict(color="#7f8c8d")))
nav_fig.update_layout(height=420, yaxis_type="log", hovermode="x unified",
                      margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(nav_fig, use_container_width=True)

x_range = [pf["dates"][0], pf["dates"][-1]]
relay = go.Figure()
for t in pf["trades"]:
    y = 1 if t["slot"] == 1 else 0
    x1 = pf["dates"][-1] if t["open"] else t["exit_date"]
    relay.add_shape(type="rect", x0=t["entry_date"], x1=x1, y0=y - 0.4, y1=y + 0.4,
                    fillcolor="#27ae60" if t["excess"] > 0 else "#e74c3c",
                    opacity=0.8, line_width=0)
    mid = pd.Timestamp(t["entry_date"]) + (pd.Timestamp(x1) - pd.Timestamp(t["entry_date"])) / 2
    relay.add_annotation(x=mid, y=y, showarrow=False, font=dict(size=10),
                         text=f"{'持有中 ' if t['open'] else ''}{t['ticker']}<br>{t['excess']:+.0f}%")
relay.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(type="date", range=x_range),
                    yaxis=dict(tickvals=[1, 0], ticktext=["仓位 1", "仓位 2"], range=[-0.6, 1.6]))
st.plotly_chart(relay, use_container_width=True)
st.caption("色块 = 持仓期，空白 = 这半仓放在 SPY；数字 = 持有期间相对 SPY 的超额")

ydf = pd.DataFrame(pf["yearly"])
ydf.columns = ["年份", "策略%", "不过滤%", "SPY%"]
st.dataframe(ydf, hide_index=True, use_container_width=True)

with st.expander("全部交易"):
    tdf = pd.DataFrame(pf["trades"])[["slot", "ticker", "name", "entry_date", "exit_date", "excess"]]
    tdf["exit_date"] = tdf["exit_date"].fillna("持有中")
    tdf.columns = ["仓位", "代码", "名称", "买入日", "卖出日", "超额 SPY%"]
    st.dataframe(tdf, hide_index=True, use_container_width=True)

# ---- 持有期内的信号 ----
st.subheader("持有期内的信号")
if not active:
    st.info("当前没有持有期内的信号")
else:
    df = pd.DataFrame(active)
    df["entry_date"] = df["entry_date"].fillna("下一交易日")
    df = df[["ticker", "status", "name", "sector", "signal_date", "entry_date",
             "dd_at_signal", "earn_shock", "x_to_date", "days_left"]]
    df.columns = ["代码", "组合状态", "名称", "行业", "信号日", "买入日",
                  "信号时回撤%", "回撤期财报日最大单日跌幅 vs SPY%", "买入至今超额 SPY%", "剩余持有交易日"]
    st.dataframe(df, hide_index=True, use_container_width=True)

# ---- 当年池回撤排行 ----
st.subheader(f"{pool_year} 池回撤排行")
mdf = pd.DataFrame(members)[["ticker", "name", "sector", "dd", "high_date", "status"]]
mdf.columns = ["代码", "名称", "行业", "距高点回撤%", "高点日", "状态"]
ROW_COLOR = {"信号中": "background-color: rgba(231,76,60,0.25)",
             "观察区": "background-color: rgba(243,156,18,0.20)"}
styled = (
    mdf.style
    .apply(lambda r: [ROW_COLOR.get(r["状态"], "")] * len(r), axis=1)
    .format({"距高点回撤%": "{:+.1f}"})
)
st.dataframe(styled, hide_index=True, use_container_width=True)

# ---- 回测依据 ----
st.subheader("回测依据")
stats = res["stats"]


def _fmt(v, f):
    return "" if v is None else f.format(v)


rows = []
for label, key in ((f"全部信号（回撤≥{threshold:.0f}%）", "signal"),
                   ("无财报日暴跌（保留）", "clean"),
                   (f"有财报日暴跌 >{shock_th:.0f}%（跳过）", "shock"),
                   ("对照（池内每月买）", "baseline")):
    row = {"": label}
    for h in ("63", "126", "252"):
        s = stats[key][h]
        row[f"{h} 日"] = (f"平均 {_fmt(s['mean'], '{:+.1f}%')} / 中位 {_fmt(s['median'], '{:+.1f}%')}"
                         f" / 胜率 {_fmt(s['win'], '{:.0f}%')} / n={s['n']}")
    rows.append(row)
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

by_year = res["events_by_year"]
fig = go.Figure(go.Bar(x=list(by_year.keys()), y=list(by_year.values())))
fig.update_layout(title="每年信号次数", height=260, margin=dict(l=10, r=10, t=40, b=10))
st.plotly_chart(fig, use_container_width=True)

with st.expander("历史全部信号"):
    edf = pd.DataFrame(events)[["ticker", "name", "signal_date", "dd_at_signal", "earn_shock",
                                "skipped", "x63", "x126", "x252"]]
    edf["skipped"] = edf["skipped"].map(lambda v: "跳过" if v else "")
    edf.columns = ["代码", "名称", "信号日", "信号时回撤%", "财报日最大跌幅%", "过滤",
                   "63 日超额%", "126 日超额%", "252 日超额%"]
    st.dataframe(edf, hide_index=True, use_container_width=True)

st.caption(
    "注意：10 年信号集中在 2020、2022 两次大跌，组合只买了十几次，样本小。"
    f"财报日暴跌 {shock_th:.0f}% 这条过滤和阈值都是看完历史数据后定的，组合年化一定偏乐观；"
    "阈值 10%–15% 之间年化会在 37%–45% 跳，只说明过滤方向稳、幅度不稳。"
    "没测止损。持有期间季报恶化提前卖测过，反而更差，不用。"
)
