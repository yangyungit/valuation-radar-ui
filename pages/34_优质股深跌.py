"""优质股深跌：回购 FCF 年度池成员距 252 日高点回撤 ≥40% 时，次日买入、持有 252 个交易日。

回测依据：10 年 74 次信号，持有 252 日相对 SPY 平均 +25.1%、中位 +20.3%、胜率 61%；
对照组（池内每月末无条件买）平均 +1.0%、中位 −1.7%、胜率 47%。
信号和统计全在后端 macro_engine.compute_quality_deep_drawdown，这页只负责展示。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import holdings_viz as hv
from api_client import fetch_quality_deep_drawdown
from cn_names import cn_name_map
from gold_leader_viz import norm_series, render_equity_chart, render_time_window_slider

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
dates = pd.to_datetime(pf["dates"])
win_lo, win_hi = render_time_window_slider(dates, "qdd")

st.markdown("##### 组合收益（起点归一为 1）")
eq = {"nav": pf["nav"], "spy": pf["spy"]}
eq.update({f"slot{i}": s for i, s in enumerate(pf["slot_nav"])})
render_equity_chart(dates, eq, [
    ("nav", "优质股深跌（加财报日暴跌过滤）", "#E74C3C", True),
    ("spy", "SPY", "#3498DB", True),
    ("slot0", "仓位 1", "rgba(231,76,60,0.55)", False, "dot"),
    ("slot1", "仓位 2", "rgba(170,178,189,0.75)", False, "dot"),
], "qdd_eq", win_lo, win_hi)
st.caption("每个仓位各占一半资金，开始后不再平衡，组合 = 两仓之和。仓位虚线默认隐藏，点图例打开。")

st.markdown("##### 统计卡")
s, ss = pf["stats"], pf["spy_stats"]
r2 = hv.compute_nav_kpi(norm_series(pf["nav"], dates).resample("W").last()).get("r2", float("nan"))
for row in (
    [("总收益", f"{s['cum_return'] * 100:.0f}%"),
     ("CAGR", f"{s['cagr'] * 100:.1f}%"),
     ("MaxDD", f"{s['max_dd'] * 100:.1f}%"),
     ("Calmar", f"{s['calmar']:.2f}"),
     ("超额 vs SPY", f"{s['excess_vs_spy'] * 100:.0f}%")],
    [("买入次数 / 跑赢 SPY", f"{s['n_buys']} / {s['n_win']}"),
     ("单笔平均超额", f"{s['avg_excess']:+.1f}%"),
     ("放 SPY 时间占比", f"{s['spy_share'] * 100:.0f}%"),
     ("Sortino", f"{s['sortino']:.2f}"),
     ("logR²", f"{r2:.2f}")],
):
    for col, (label, val) in zip(st.columns(len(row)), row):
        col.metric(label, val)
st.caption(
    f"SPY 同期：总收益 {ss['cum_return'] * 100:.0f}%｜CAGR {ss['cagr'] * 100:.1f}%｜"
    f"MaxDD {ss['max_dd'] * 100:.1f}%｜Calmar {ss['calmar']:.2f}｜Sortino {ss['sortino']:.2f}。"
    "统计按整个回测期算，不跟随时间窗口滑块；单笔平均超额 = 每笔持有期间相对 SPY 的超额取平均。"
)

st.markdown("##### 仓位分段收益")
spy_s = norm_series(pf["spy"], dates)
spy_s = spy_s[(spy_s.index >= win_lo) & (spy_s.index <= win_hi)]
lo_d, hi_d = win_lo.strftime("%Y-%m-%d"), win_hi.strftime("%Y-%m-%d")
for k, slot_vals in enumerate(pf["slot_nav"]):
    slot_s = norm_series(slot_vals, dates)
    slot_s = slot_s[(slot_s.index >= win_lo) & (slot_s.index <= win_hi)]
    segs, cur = [], pf["dates"][0]
    for t in (t for t in pf["trades"] if t["slot"] == k + 1):
        end = t["exit_date"] or pf["dates"][-1]
        segs += [("SPY", cur, t["entry_date"]), (t["ticker"], t["entry_date"], end)]
        cur = end
    segs.append(("SPY", cur, pf["dates"][-1]))
    segs = [(tk, max(a, lo_d), min(b, hi_d)) for tk, a, b in segs if b > a and b >= lo_d and a <= hi_d]
    names = cn_name_map(tk for tk, _, _ in segs)
    names["SPY"] = "空仓"
    fig = hv.build_stitched_fig(
        segs, f"仓位 {k + 1} 接力 持仓段", pd.DataFrame({"Close": spy_s}),
        {tk: pd.DataFrame({"Close": slot_s}) for tk, _, _ in segs}, names, names,
        name_style="cn_ticker",
    )
    st.plotly_chart(fig, use_container_width=True, key=f"qdd_slot_{k}")
st.caption("每段 = 一笔持仓（持满 252 个交易日即卖），「空仓(SPY)」段 = 这半仓没信号时拿着 SPY。")

ydf = pd.DataFrame(pf["yearly"])
ydf.columns = ["年份", "策略%", "SPY%"]
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
