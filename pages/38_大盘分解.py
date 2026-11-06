"""大盘分解：S&P 500 按 GICS 行业 / 硬科技·软件·互联网 / Sharadar 细分行业拆开，看谁在涨、谁在跌、各自给大盘贡献多少。
数据和计算在后端 /api/v1/spx_breakdown（valuation-radar/scripts/spx_breakdown.py），本页只画图。
"""

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_ff_history, fetch_spx_breakdown

st.set_page_config(page_title="大盘分解", layout="wide", page_icon="🧩")

UP = ["#0b6b3a", "#2e9d5b", "#7cc48f"]
DOWN = ["#f08a5d", "#d9442b", "#8e1b10"]
GRAY = "#b8b8b8"
SPX = "#3b9eff"
PALETTE = ["#d9442b", "#3b6fd6", "#0b6b3a", "#7b4fc9", "#e08a00", "#00a3a3", "#c2417f", "#6b6b6b"]
PERIODS = {"今年以来": "ytd", "本月": "mtd", "近 1 周": "1w", "近 1 月": "1m", "近 3 月": "3m", "近 1 年": "1y"}
GROUPINGS = {"GICS 11 个行业": "sector", "硬科技 / 软件 / 互联网": "theme", "Sharadar 细分行业": "industry"}
TOP_BARS = 10


def render_history() -> None:
    d = fetch_ff_history()
    if not d.get("success"):
        st.error(f"后端没返回数据：{d.get('error')}")
        return
    st.caption(f"Ken French 数据库，CRSP 全美股（纽交所 + 美交所 + 纳斯达克），数据到 {d['asof']}。"
               "行业按 SIC 代码固定清单切：「商业设备(科技)」1926 年装的是 IBM 制表机、NCR 收银机、RCA 收音机，"
               "标签固定住的是产品，不是「时代前沿」；1960 年前的 SIC 是 CRSP 事后回填。")
    cn, color, fcn, fcolor = d["ind_cn"], d["ind_color"], d["fac_cn"], d["fac_color"]
    inds, facs, decs = list(d["weights"]), list(d["factor_decade"]), d["decades"]

    fig = go.Figure()
    for k in inds:
        fig.add_scatter(x=d["years"], y=d["weights"][k], name=cn[k], stackgroup="w", mode="lines",
                        line=dict(width=0.3, color=color[k]), fillcolor=color[k],
                        hovertemplate="%{x} " + cn[k] + " %{y:.1f}%<extra></extra>")
    for y in d["era_lines"]:
        fig.add_vline(x=y, line_dash="dot", line_color="white", line_width=0.8)
    fig.update_layout(height=480, title="12 行业市值占比（年末）", yaxis=dict(range=[0, 100], title="%"),
                      hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("看红色：科技 1926–1990 年一直 5–10%，2000 年 25%，2025 年 42%；黑色能源 1980 年顶到 25%，现在只剩 3% 左右。")

    fig = go.Figure()
    for k in inds:
        fig.add_bar(x=decs, y=d["contrib"][k], name=cn[k], marker_color=color[k],
                    hovertemplate="%{x} " + cn[k] + " %{y:+.1f}<extra></extra>")
    top = [sum(max(d["contrib"][k][i] or 0, 0) for k in inds) + 0.8 for i in range(len(decs))]
    fig.add_scatter(x=decs, y=top, mode="text",
                    text=[f"{v:.1f}%" for v in d["contrib_total"]], showlegend=False, hoverinfo="skip")
    low = min(sum(min(d["contrib"][k][i] or 0, 0) for k in inds) for i in range(len(decs)))
    fig.update_layout(barmode="relative", height=480, title="每个十年大盘算术年均收益由谁贡献（权重 × 行业收益，百分点）",
                      yaxis_range=[low - 1, max(top) + 1.5], margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("1950s 制造 + 能源 + 化工拉；1970s 能源一家最大；2000s 科技电信把别人涨的吃掉；"
               "2020s 科技占一半以上，历史上没有哪个行业占过这么大。")
    st.dataframe(pd.DataFrame([{"十年": k, **{n: f"{cn[i]} {v:.0f}%" for n, (i, v) in zip(["第一", "第二", "第三"], d["top3"][k])}}
                               for k in decs]), hide_index=True, width="stretch")

    fig = go.Figure()
    for k in facs:
        fig.add_bar(x=decs, y=d["factor_decade"][k], name=fcn[k], marker_color=fcolor[k])
    fig.update_layout(barmode="group", height=420, title="每个十年因子年化溢价（多空组合；盈利质量 / 保守扩张 1963 年起）",
                      yaxis_title="%", margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    fig = go.Figure()
    for k in facs:
        fig.add_scatter(x=d["factor_cum"]["dates"], y=d["factor_cum"][k], name=fcn[k],
                        line=dict(color=fcolor[k], width=1.4))
    for y in d["era_lines"]:
        fig.add_vline(x=f"{y}-01-01", line_dash="dot", line_color="gray", line_width=0.6)
    fig.add_hline(y=0, line_color="gray", line_width=1)
    fig.update_layout(height=480, title="因子累计对数收益 1926–今（向上 = 这个风格在赢）", hovermode="x unified",
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("「股票超额」= 大盘减 1 个月国债，2010 年代利率≈0 所以和大盘重合；1970s 大盘 6.1、现金 6.3，拿股票十年白忙。"
               "2010 年以来只有股票超额在赚，其他因子年化都在 ±3% 以内：在股票里就赢了，股票内部怎么挑都没多少额外回报。"
               "之前每个十年都至少有一个因子年化超过 5%。")
    fd = d["factor_decade"]
    tbl = pd.DataFrame({"十年": decs, "大盘": d["mkt_decade"], "现金": d["rf_decade"], **{fcn[k]: fd[k] for k in facs}})
    st.dataframe(tbl, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%+.1f") for c in tbl.columns[1:]})

    st.subheader("动量：多空 vs 只做多")
    mp = {p["label"]: p for p in d["mom_periods"]}
    st.caption("多空动量的大亏几乎全在空头：崩盘后输家组暴力反弹（2009 年输家组 "
               f"{mp['2009']['lo']:+.0f}%）。只买赢家把那条尾巴砍掉，代价是反弹年跑输大盘。"
               f"2010 年代只做多只比大盘多 {mp['2010-2019']['excess']:.1f} 个点，比 1945–2008 的 "
               f"{mp['1945-2008']['excess']:.1f} 差远了；2020 年以来又拉开到 {mp['2020-今']['excess']:.1f} 个点。")
    pct = lambda f: {c: st.column_config.NumberColumn(format=f) for c in ["大盘", "只买赢家", "只买输家", "赢家-大盘", "赢家组", "输家组"]}
    c1, c2 = st.columns(2)
    c1.dataframe(pd.DataFrame(d["mom_periods"]).rename(columns={"label": "时段", "mkt": "大盘", "hi": "只买赢家",
                                                                "lo": "只买输家", "excess": "赢家-大盘"}),
                 hide_index=True, width="stretch", column_config=pct("%+.1f%%"))
    c2.dataframe(pd.DataFrame(d["mom_yearly"]).rename(columns={"year": "年", "mkt": "大盘", "hi": "赢家组", "lo": "输家组"}),
                 hide_index=True, width="stretch", column_config={"年": st.column_config.NumberColumn(format="%d"),
                                                                  **pct("%+.0f%%")})


st.title("🧩 大盘分解")
view = st.radio("看什么", ["今天的 S&P 500", "百年风格（1926 年起）"], horizontal=True, label_visibility="collapsed")
if view != "今天的 S&P 500":
    render_history()
    st.stop()
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
