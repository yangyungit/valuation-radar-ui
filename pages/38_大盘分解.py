"""大盘分解：S&P 500 按 11 个 GICS 行业拆开，看谁在涨、谁在跌、各自给大盘贡献多少。
数据和计算在后端 /api/v1/spx_breakdown（valuation-radar/scripts/spx_breakdown.py），本页只画图。
"""

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_spx_breakdown

st.set_page_config(page_title="大盘分解", layout="wide", page_icon="🧩")

UP = ["#0b6b3a", "#2e9d5b", "#7cc48f"]
DOWN = ["#f08a5d", "#d9442b", "#8e1b10"]
GRAY = "#b8b8b8"
SPX = "#3b9eff"
PERIODS = {"今年以来": "ytd", "本月": "mtd", "近 1 周": "1w", "近 1 月": "1m", "近 3 月": "3m", "近 1 年": "1y"}

st.title("🧩 大盘分解")
st.caption("S&P 500 按 11 个 GICS 行业拆开：行业归属取自 11 只 SPDR 行业 ETF 持仓，权重取自 SPY 持仓，不含分红。"
           "「贡献」= 这个行业让大盘涨跌了几个百分点，各行业贡献加起来等于合成指数涨跌。")

c1, c2 = st.columns([3, 1])
pick = c1.radio("时间段", list(PERIODS) + ["自选起点"], horizontal=True)
if pick == "自选起点":
    base = fetch_spx_breakdown("ytd")
    if not base.get("success"):
        st.error(f"后端没返回数据：{base.get('error')}")
        st.stop()
    lo, hi = date.fromisoformat(base["first_date"]), date.fromisoformat(base["end"])
    d = fetch_spx_breakdown(start=str(c2.date_input("起点（这天收盘 = 0）", value=hi.replace(day=1),
                                                     min_value=lo, max_value=hi)))
else:
    d = fetch_spx_breakdown(PERIODS[pick])
if not d.get("success"):
    st.error(f"后端没返回数据：{d.get('error')}")
    st.stop()

name = d["sectors"]
dates = pd.to_datetime(d["dates"])
ret = pd.Series(d["ret"]).sort_values(ascending=False)
con = pd.Series(d["contrib"])
w0 = d["w0"]
syn, spx = d["lines"]["ALL"][-1], d["spx"][-1]

m1, m2, m3, m4 = st.columns(4)
m1.metric("S&P 500 实际", f"{spx:+.2f}%")
m2.metric("合成指数", f"{syn:+.2f}%", f"误差 {syn - spx:+.2f} 个百分点", delta_color="off")
m3.metric("涨最多", f"{name[ret.index[0]]} {ret.iloc[0]:+.1f}%")
m4.metric("跌最多", f"{name[ret.index[-1]]} {ret.iloc[-1]:+.1f}%")
st.caption(f"{d['start']} 收盘 → {d['end']} 收盘；持仓表日期 {d['asof']}。"
           "误差超过 1 个百分点说明起点太早（流通股数按最新持仓固定，没算回购增发）或被剔除的股票影响大，行业数字要打折看。")

col = dict(zip(ret.index, UP + [GRAY] * (len(ret) - 6) + DOWN))
fig = go.Figure()
for k in ret.index[::-1]:
    hi_ = col[k] != GRAY
    fig.add_scatter(x=dates, y=d["lines"][k], name=f"{name[k]} {ret[k]:+.1f}%",
                    line=dict(color=col[k], width=2.2 if hi_ else 1), hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}%")
fig.add_scatter(x=dates, y=d["spx"], name=f"S&P 500 {spx:+.1f}%", line=dict(color=SPX, width=3.5),
                hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}%")
fig.add_hline(y=0, line_color="gray", line_width=1)
fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="%", hovermode="x unified",
                  title="各行业累计涨跌（蓝线 S&P 500，涨最多 3 个绿色、跌最多 3 个红色）",
                  legend=dict(traceorder="reversed"))
st.plotly_chart(fig, width="stretch")


def bars(s: pd.Series, title: str, fmt: str) -> go.Figure:
    f = go.Figure(go.Bar(x=s.values, y=[f"{name[k]}（占 {w0[k]:.0f}%）" for k in s.index], orientation="h",
                         text=[fmt.format(v) for v in s.values], textposition="outside", cliponaxis=False,
                         marker_color=["#2e8b57" if v > 0 else "#c0392b" for v in s.values]))
    lo_, hi_ = min(s.min(), 0), max(s.max(), 0)
    pad = (hi_ - lo_) * 0.25
    f.update_layout(height=430, margin=dict(l=10, r=40, t=40, b=10), title=title,
                    xaxis_range=[lo_ - (pad if lo_ < 0 else 0), hi_ + (pad if hi_ > 0 else 0)])
    return f


b1, b2 = st.columns(2)
b1.plotly_chart(bars(ret[::-1], f"行业涨跌（虚线 = 合成指数 {syn:+.1f}%）", "{:+.1f}%")
                .add_vline(x=syn, line_dash="dash", line_color=SPX), width="stretch")
b2.plotly_chart(bars(con.sort_values(), "对大盘的贡献（个百分点）", "{:+.2f}"), width="stretch")

st.subheader("每个行业是谁在拉、谁在拖")
fmt = lambda xs: "，".join(f"{x['ticker']} {x['ret']:+.0f}%" for x in xs)
st.dataframe(pd.DataFrame([{"行业": name[k], "涨跌": ret[k], "贡献": con[k],
                            "拉动最多": fmt(d["leaders"][k]["pull"]), "拖累最多": fmt(d["leaders"][k]["drag"])}
                           for k in ret.index]),
             hide_index=True, width="stretch", column_config={
                 "涨跌": st.column_config.NumberColumn(format="%+.1f%%"),
                 "贡献": st.column_config.NumberColumn("贡献（个百分点）", format="%+.2f")})

with st.expander("全部个股明细"):
    stocks = pd.DataFrame(d["stocks"])
    stocks["行业"] = stocks.pop("sec").map(name)
    pick_sec = st.multiselect("行业", list(name.values()))
    if pick_sec:
        stocks = stocks[stocks.行业.isin(pick_sec)]
    st.dataframe(stocks.sort_values("contrib"), hide_index=True, width="stretch", column_config={
        "ret": st.column_config.NumberColumn("涨跌", format="%+.1f%%"),
        "contrib": st.column_config.NumberColumn("贡献（个百分点）", format="%+.3f")})
