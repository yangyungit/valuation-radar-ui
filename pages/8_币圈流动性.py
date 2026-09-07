"""币圈流动性：美联储净流动性 vs BTC。

净流动性 = 美联储总资产(WALCL) − 财政部一般账户(WTREGEN) − 隔夜逆回购(RRPONTSYD)。
和 pages/1_宏观定调.py 的流动性图同一个公式、同一批 FRED 序列，区别是这页把对手方
从 SPY 换成加密资产，并且强制把滚动相关性画出来——净流动性和 BTC 的吻合度分时期
差别极大（2020-21 高度同步，2022 缩表后水平值反向），只看双轴图会看出假信号。
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests as _requests
import streamlit as st
from plotly.subplots import make_subplots

from api_client import fetch_close_series

st.set_page_config(page_title="币圈流动性", layout="wide", page_icon="💧")

# WALCL / WTREGEN 单位是百万美元，除 1000 换成十亿；RRPONTSYD 本身就是十亿。
FRED_SERIES = ("WALCL", "WTREGEN", "RRPONTSYD")

BENCHMARKS = {
    "BTC-USD": "比特币",
    "ETH-USD": "以太坊",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    "SPY": "标普500",
    "QQQ": "纳指100",
}


def _get_fred_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("FRED_API_KEY", "")
        except Exception:
            pass
    return key or ""


def _fetch_fred_series(series_id: str, start_date, api_key: str) -> pd.Series:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date.strftime("%Y-%m-%d"),
    }
    r = _requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    dates, values = [], []
    for obs in r.json().get("observations", []):
        # FRED 缺失值是 "."，两个字段都解析成功才 append，否则索引和值会错位。
        try:
            d = pd.Timestamp(obs["date"])
            v = float(obs["value"])
        except (ValueError, KeyError):
            continue
        dates.append(d)
        values.append(v)
    return pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id)


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def load_net_liquidity(years: int, api_key: str) -> tuple:
    """返回 (日频 DataFrame[fed/tga/rrp/net]，各序列最后更新日期 dict)。

    Fed 资产和 TGA 是周三频，RRP 是日频。统一 reindex 到日历日再 ffill，所以两次
    周报之间净流动性只跟着 RRP 动。
    """
    start = datetime.now() - timedelta(days=int(365.25 * years) + 30)
    raw = {}
    for sid in FRED_SERIES:
        try:
            s = _fetch_fred_series(sid, start, api_key)
            if not s.empty:
                raw[sid] = s
        except Exception:
            pass
    if len(raw) < 3:
        return pd.DataFrame(), {}

    asof = {sid: raw[sid].index.max() for sid in raw}
    idx = pd.date_range(max(s.index.min() for s in raw.values()),
                        max(s.index.max() for s in raw.values()), freq="D")
    df = pd.DataFrame(index=idx)
    df["fed"] = raw["WALCL"].reindex(idx).ffill() / 1000.0
    df["tga"] = raw["WTREGEN"].reindex(idx).ffill() / 1000.0
    df["rrp"] = raw["RRPONTSYD"].reindex(idx).ffill()
    df["net"] = df["fed"] - df["tga"] - df["rrp"]
    return df.dropna(), asof


with st.sidebar:
    st.header("🛠️ 维护")
    if st.button("🔄 清除本页缓存"):
        load_net_liquidity.clear()
        fetch_close_series.clear()
        st.rerun()
    st.markdown("---")
    _k = _get_fred_key()
    if _k:
        st.success(f"FRED Key 已就位（...{_k[-4:]}）")
    else:
        st.error("未检测到 FRED_API_KEY")

st.title("💧 币圈流动性")
st.caption("净流动性 = 美联储总资产 − 财政部账户(TGA) − 隔夜逆回购(RRP)。"
           "市场上真正能买风险资产的钱。")

api_key = _get_fred_key()
if not api_key:
    st.error("拿不到 FRED_API_KEY。放进环境变量，或写进 `.streamlit/secrets.toml`。")
    st.stop()

c1, c2, c3, c4 = st.columns([1.4, 1, 1.3, 1.3])
with c1:
    labels = [f"{t}  |  {cn}" for t, cn in BENCHMARKS.items()]
    picked = st.selectbox("对比标的", labels)
    ticker = picked.split("  |  ")[0].strip()
with c2:
    years = st.selectbox("回看年数", [2, 3, 5, 10], index=2)
with c3:
    chg_win = st.slider("变化窗口（周）", 4, 26, 13,
                        help="算「净流动性变化」和「价格涨幅」用的回看周数。水平值容易被共同趋势带偏，变化率才是有信号的口径。")
with c4:
    roll_win = st.slider("滚动相关窗口（周）", 26, 156, 52, step=13,
                         help="下方相关性曲线的样本长度。52 周 = 一年。")

with st.spinner("拉 FRED 数据…"):
    liq, asof = load_net_liquidity(years, api_key)
if liq.empty:
    st.error("FRED 三个序列没拉全（WALCL / WTREGEN / RRPONTSYD），检查 Key 或网络。")
    st.stop()

px = fetch_close_series(ticker, years)
if px.empty:
    st.error(f"拿不到 {ticker} 的价格。")
    st.stop()

df = liq.join(px.rename("price"), how="inner").dropna()
df = df[df.index >= df.index.max() - pd.Timedelta(days=int(365.25 * years))]
if len(df) < 120:
    st.error("重叠数据不足，换个更长的回看年数。")
    st.stop()

last = df.iloc[-1]
net_t = last["net"] / 1000.0
prev = df["net"].asof(df.index[-1] - pd.Timedelta(weeks=chg_win))
delta_b = last["net"] - prev if pd.notna(prev) else np.nan

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("净流动性", f"{net_t:.2f} 万亿",
          f"{delta_b:+,.0f}B / {chg_win}周" if pd.notna(delta_b) else None)
m2.metric("美联储总资产", f"{last['fed'] / 1000.0:.2f} 万亿",
          help=f"WALCL，最新 {asof['WALCL'].date()}")
m3.metric("财政部账户 TGA", f"{last['tga']:,.0f}B",
          help=f"WTREGEN，最新 {asof['WTREGEN'].date()}。TGA 涨 = 财政部从市场抽钱")
m4.metric("隔夜逆回购 RRP", f"{last['rrp']:,.0f}B",
          help=f"RRPONTSYD，最新 {asof['RRPONTSYD'].date()}。RRP 涨 = 钱趴在美联储不出来")
m5.metric(f"{BENCHMARKS[ticker]}", f"{last['price']:,.0f}",
          f"{df['price'].iloc[-1] / df['price'].asof(df.index[-1] - pd.Timedelta(weeks=chg_win)) - 1:+.1%} / {chg_win}周")

if last["rrp"] < 50:
    st.info(f"RRP 已经基本归零（{last['rrp']:,.1f}B，2022 年峰值超过 2.5 万亿）。"
            "第三项现在没有信息量，公式实际退化成「美联储总资产 − TGA」。")

# ---- 周频重采样：FRED 本来就是周报，日频算相关性等于在放大 ffill 的噪音 ----
w = df.resample("W-FRI").last().dropna()
net_chg = w["net"].diff(chg_win)
px_chg = w["price"].pct_change(chg_win, fill_method=None)
roll_corr = net_chg.rolling(roll_win).corr(px_chg)

corr_level = w["net"].corr(np.log(w["price"]))
corr_chg = net_chg.corr(px_chg)

fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32],
    vertical_spacing=0.05,
    specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
)
x = df.index.to_pydatetime()
fig.add_trace(go.Scatter(x=x, y=df["net"] / 1000.0, name="净流动性（左轴，万亿）",
                         fill="tozeroy", line=dict(color="#2ecc71", width=1.6),
                         fillcolor="rgba(46,204,113,0.14)"),
              row=1, col=1, secondary_y=False)
fig.add_trace(go.Scatter(x=x, y=df["price"], name=f"{BENCHMARKS[ticker]}（右轴，对数）",
                         line=dict(color="#f5a623", width=2)),
              row=1, col=1, secondary_y=True)

xw = w.index.to_pydatetime()
fig.add_trace(go.Scatter(x=xw, y=roll_corr, name=f"{roll_win}周滚动相关",
                         line=dict(color="#4da3ff", width=2)), row=2, col=1)
fig.add_hline(y=0, line=dict(color="#666", width=1, dash="dot"), row=2, col=1)
fig.add_hrect(y0=0.5, y1=1.0, fillcolor="rgba(46,204,113,0.10)", line_width=0, row=2, col=1)
fig.add_hrect(y0=-1.0, y1=-0.5, fillcolor="rgba(231,76,60,0.10)", line_width=0, row=2, col=1)

fig.update_layout(
    height=720, plot_bgcolor="#111", paper_bgcolor="#111",
    font=dict(color="#ddd", size=13),
    legend=dict(orientation="h", y=1.05, x=0),
    margin=dict(l=60, r=60, t=40, b=40), hovermode="x unified",
)
fig.update_yaxes(title_text="净流动性（万亿美元）", gridcolor="#222",
                 row=1, col=1, secondary_y=False)
fig.update_yaxes(title_text=f"{BENCHMARKS[ticker]} 价格", type="log",
                 showgrid=False, row=1, col=1, secondary_y=True)
fig.update_yaxes(title_text="相关系数", range=[-1.05, 1.05], gridcolor="#222", row=2, col=1)
fig.update_xaxes(gridcolor="#222", row=1, col=1)
fig.update_xaxes(gridcolor="#222", row=2, col=1)
st.plotly_chart(fig, width="stretch")

k1, k2 = st.columns(2)
k1.metric(f"水平值相关（净流动性 vs log 价格，近 {years} 年）", f"{corr_level:+.2f}",
          help="两条线一起长期向上就会很高，多半是共同趋势造成的假象，别当信号用。")
k2.metric(f"变化率相关（{chg_win} 周环比）", f"{corr_chg:+.2f}",
          help="去掉趋势后的真实同步程度。这个才是判断「流动性驱动」是否成立的口径。")

st.markdown("---")
st.subheader("三个分项谁在推动")
fig2 = make_subplots(specs=[[{"secondary_y": True}]])
fig2.add_trace(go.Scatter(x=x, y=df["fed"] / 1000.0, name="美联储总资产（左轴，万亿）",
                          line=dict(color="#9b59b6", width=2)), secondary_y=False)
fig2.add_trace(go.Scatter(x=x, y=df["tga"], name="TGA（右轴，十亿）",
                          line=dict(color="#e74c3c", width=1.8)), secondary_y=True)
fig2.add_trace(go.Scatter(x=x, y=df["rrp"], name="RRP（右轴，十亿）",
                          line=dict(color="#3498db", width=1.8)), secondary_y=True)
fig2.update_layout(
    height=380, plot_bgcolor="#111", paper_bgcolor="#111",
    font=dict(color="#ddd", size=13),
    legend=dict(orientation="h", y=1.12, x=0),
    margin=dict(l=60, r=60, t=30, b=40), hovermode="x unified",
)
fig2.update_yaxes(title_text="万亿美元", gridcolor="#222", secondary_y=False)
fig2.update_yaxes(title_text="十亿美元", showgrid=False, secondary_y=True)
fig2.update_xaxes(gridcolor="#222")
st.plotly_chart(fig2, width="stretch")

with st.expander("这页怎么读 / 数据口径"):
    st.markdown(f"""
**公式**：净流动性 = 美联储总资产 − 财政部账户 − 隔夜逆回购。
美联储印的钱有两个去处会被"锁住"——躺在财政部账户里（TGA），或者被货币基金塞回美联储吃利息（RRP）。
减掉这两块，剩下的才是能追风险资产的钱。

**FRED 序列**（对应 TradingView 的 USCBBS / WDTGCAL / RRPONTSYD）

| 项 | FRED 代码 | 频率 | 原始单位 |
|---|---|---|---|
| 美联储总资产 | `WALCL` | 周三 | 百万美元 |
| 财政部账户 | `WTREGEN` | 周三 | 百万美元 |
| 隔夜逆回购 | `RRPONTSYD` | 每日 | 十亿美元 |

前两项是周报，日频曲线是往后填平的；两次周报之间只有 RRP 在动。

**别把水平值相关当信号**：2020-21 放水期净流动性和 BTC 一起往上冲，水平值相关性能到 +0.7 以上，
但那是两条趋势线的巧合。2022 缩表开始后，同样口径变成负相关（BTC 涨、净流动性跌）。
所以主图下面强制放了滚动相关，看清楚当下到底还同不同步。

**当前口径下**：近 {years} 年水平值相关 {corr_level:+.2f}，{chg_win} 周变化率相关 {corr_chg:+.2f}。

**缓存**：FRED 数据缓存 4 小时，价格缓存 4 小时。左侧可手动清。
""")
