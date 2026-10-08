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

st.caption(
    f"回购 FCF 优质池（每年按财报重建 40 只）里，复权价距 252 日高点回撤 ≥{threshold:.0f}% 时，"
    f"次日收盘买入、持有 {hold_days} 个交易日。回撤收窄到 {rearm:.0f}% 以内才重新计数。"
    f"回撤 {watch:.0f}–{threshold:.0f}% 只标观察区，不算信号。"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("当年池", f"{pool_year} · {len(members)} 只")
c2.metric("持有期内信号", len(active))
c3.metric("观察区", sum(1 for m in members if m["status"] == "观察区"))
c4.metric("数据截至", res["as_of"])

# ---- 持有期内的信号 ----
st.subheader("持有期内的信号")
if not active:
    st.info("当前没有持有期内的信号")
else:
    df = pd.DataFrame(active)
    df["entry_date"] = df["entry_date"].fillna("下一交易日")
    df = df[["ticker", "name", "sector", "signal_date", "entry_date",
             "dd_at_signal", "x_to_date", "days_left"]]
    df.columns = ["代码", "名称", "行业", "信号日", "买入日",
                  "信号时回撤%", "买入至今超额 SPY%", "剩余持有交易日"]
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
for label, key in ((f"信号（回撤≥{threshold:.0f}%）", "signal"), ("对照（池内每月买）", "baseline")):
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
    edf = pd.DataFrame(events)[["ticker", "name", "signal_date", "dd_at_signal", "x63", "x126", "x252"]]
    edf.columns = ["代码", "名称", "信号日", "信号时回撤%", "63 日超额%", "126 日超额%", "252 日超额%"]
    st.dataframe(edf, hide_index=True, use_container_width=True)

st.caption(
    "注意：10 年信号集中在 2020、2022 两次大跌，独立的大跌只有四五次，样本小。"
    "平均值被少数暴涨票拉高，看中位数更稳。没测止损。池子含较多金融股。"
    "基本面是否恶化（错杀还是真变坏）这页不判断，买之前自己看财报。"
)
