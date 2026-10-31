"""大盘分解：S&P 500 按 GICS 行业 / 硬科技·软件·互联网 / Sharadar 细分行业拆开，看谁在涨、谁在跌、各自给大盘贡献多少。
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
PALETTE = ["#d9442b", "#3b6fd6", "#0b6b3a", "#7b4fc9", "#e08a00", "#00a3a3", "#c2417f", "#6b6b6b"]
PERIODS = {"今年以来": "ytd", "本月": "mtd", "近 1 周": "1w", "近 1 月": "1m", "近 3 月": "3m", "近 1 年": "1y"}
GROUPINGS = {"GICS 11 个行业": "sector", "硬科技 / 软件 / 互联网": "theme", "Sharadar 细分行业": "industry"}
TOP_BARS = 10

st.title("🧩 大盘分解")
st.caption("S&P 500 拆成几组：GICS 行业归属取自 11 只 SPDR 行业 ETF 持仓，细分行业取自 Sharadar，权重取自 SPY 持仓，不含分红。"
           "「贡献」= 这一组让大盘涨跌了几个百分点，各组贡献加起来等于合成指数涨跌。")

grouping = GROUPINGS[st.radio("分组方式", list(GROUPINGS), horizontal=True)]
c1, c2 = st.columns([3, 1])
pick = c1.radio("时间段", list(PERIODS) + ["自选起点"], horizontal=True)
if pick == "自选起点":
    base = fetch_spx_breakdown("ytd")
    if not base.get("success"):
        st.error(f"后端没返回数据：{base.get('error')}")
        st.stop()
    lo, hi = date.fromisoformat(base["first_date"]), date.fromisoformat(base["end"])
    d = fetch_spx_breakdown(start=str(c2.date_input("起点（这天收盘 = 0）", value=hi.replace(day=1),
                                                     min_value=lo, max_value=hi)), grouping=grouping)
else:
    d = fetch_spx_breakdown(PERIODS[pick], grouping=grouping)
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

if d.get("note"):
    st.caption(d["note"])

cs = con.sort_values()
picked = st.multiselect("只画这几条线（不选 = 全部画；细分行业不选 = 贡献最大、最小各 3 个）", list(ret.index),
                        format_func=lambda k: name[k])
show = [k for k in ret.index if k in (picked or (ret.index if grouping != "industry"
                                                  else [*cs.index[:3], *cs.index[-3:]]))]
if picked:
    col = dict(zip(show, PALETTE * (len(show) // len(PALETTE) + 1)))
    title = "累计涨跌（蓝线 S&P 500）"
else:
    col = dict(zip(show, UP + [GRAY] * (len(show) - 6) + DOWN))
    title = "累计涨跌（蓝线 S&P 500，涨最多 3 个绿色、跌最多 3 个红色）"
fig = go.Figure()
for k in show[::-1]:
    hi_ = col[k] != GRAY
    fig.add_scatter(x=dates, y=d["lines"][k], name=f"{name[k]} {ret[k]:+.1f}%",
                    line=dict(color=col[k], width=2.2 if hi_ else 1), hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}%")
fig.add_scatter(x=dates, y=d["spx"], name=f"S&P 500 {spx:+.1f}%", line=dict(color=SPX, width=3.5),
                hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}%")
fig.add_hline(y=0, line_color="gray", line_width=1)
fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="%", hovermode="x unified",
                  title=title, legend=dict(traceorder="reversed"))
st.plotly_chart(fig, width="stretch")


def bars(s: pd.Series, title: str, fmt: str) -> go.Figure:
    f = go.Figure(go.Bar(x=s.values, y=[f"{name[k]}（占 {w0[k]:.0f}%）" for k in s.index], orientation="h",
                         text=[fmt.format(v) for v in s.values], textposition="outside", cliponaxis=False,
                         marker_color=["#2e8b57" if v > 0 else "#c0392b" for v in s.values]))
    lo_, hi_ = min(s.min(), 0), max(s.max(), 0)
    pad = (hi_ - lo_) * 0.25
    f.update_layout(height=max(430, 26 * len(s) + 80), margin=dict(l=10, r=40, t=40, b=10), title=title,
                    xaxis_range=[lo_ - (pad if lo_ < 0 else 0), hi_ + (pad if hi_ > 0 else 0)])
    return f


keys = ret.index if len(ret) <= 2 * TOP_BARS else [*cs.index[:TOP_BARS], *cs.index[-TOP_BARS:]]
sub = "" if len(keys) == len(ret) else f"，只列贡献最大、最小各 {TOP_BARS} 个"
b1, b2 = st.columns(2)
b1.plotly_chart(bars(ret[ret.index.isin(keys)][::-1], f"涨跌（虚线 = 合成指数 {syn:+.1f}%{sub}）", "{:+.1f}%")
                .add_vline(x=syn, line_dash="dash", line_color=SPX), width="stretch")
b2.plotly_chart(bars(cs[cs.index.isin(keys)], f"对大盘的贡献（个百分点{sub}）", "{:+.2f}"), width="stretch")

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
