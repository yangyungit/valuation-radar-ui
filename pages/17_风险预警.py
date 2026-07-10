"""风险预警 · 流动性/风险偏好条带

把几个「风险偏好温度计」摆在同一条时间轴上，每个指标一条红/绿条带，
月线跌破（或涨破）自己的 4 月均线（月 MA4）就标红，自己看哪些破位了。

纯前端自取数（yfinance 月线），不依赖后端。
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from _yf_session import YF_SESSION

st.set_page_config(page_title="风险预警", layout="wide")

st.title("⚠️ 风险预警 · 流动性 / 风险偏好条带")
st.caption(
    "每条 = 一个风险偏好温度计，月线信号：**风险资产类**（BTC、HYG÷LQD、ARKK÷SPY、"
    "SMH÷SPY）**跌破**自己的 4 月均线（月 MA4）= 🔴 风险偏好退潮；**美元 DXY 涨破** MA4 "
    "= 🔴（美元走强 = 全球流动性收紧，方向相反）。绿 = 安全。哪些破位了自己看，结合自己的判断操作。"
)

_MA_WIN = 4  # 月 MA4


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def _monthly_close(ticker: str, years: int = 15) -> pd.Series:
    """日线拉取后 resample 到月末收盘。失败返回空 Series。"""
    try:
        h = yf.Ticker(ticker, session=YF_SESSION).history(
            period=f"{years}y", auto_adjust=True,
        )
    except Exception:
        return pd.Series(dtype=float)
    if h is None or h.empty or "Close" not in h:
        return pd.Series(dtype=float)
    s = pd.to_numeric(h["Close"], errors="coerce").dropna()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx
    return s.resample("ME").last().dropna()


def _ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    df = pd.concat([a, b], axis=1, sort=True).dropna()
    if df.empty:
        return pd.Series(dtype=float)
    return df.iloc[:, 0] / df.iloc[:, 1]


def _red_mask(s: pd.Series, direction: str) -> pd.Series:
    """月线 vs MA4 → 红布尔（float 1/0，MA 未成形的头 3 月为 NaN 不算）。"""
    s = s.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    ma = s.rolling(_MA_WIN).mean()
    red = (s < ma) if direction == "below" else (s > ma)
    return red.astype(float).where(ma.notna())


def _segs(mask: pd.Series) -> list:
    """红布尔 Series → 连续红段 [(月首日, 月末日)]，矩形填满整月宽度。"""
    m = (mask == 1).fillna(False)
    if not bool(m.any()):
        return []
    flip = m.ne(m.shift()).cumsum()
    out = []
    for _gid, grp in m.groupby(flip):
        if bool(grp.iloc[0]):
            d0, d1 = grp.index[0], grp.index[-1]
            out.append((d0.replace(day=1), d1))
    return out


with st.spinner("📊 拉取各指标月线..."):
    btc = _monthly_close("BTC-USD")
    hyg = _monthly_close("HYG")
    lqd = _monthly_close("LQD")
    arkk = _monthly_close("ARKK")
    smh = _monthly_close("SMH")
    spy = _monthly_close("SPY")
    dxy = _monthly_close("DX-Y.NYB")

# (显示名, 月线 series, 方向, 说明)。direction=below → 跌破 MA4 红；above → 涨破红
INDICATORS = [
    ("BTC", btc, "below", "加密风险偏好退潮"),
    ("HYG÷LQD", _ratio(hyg, lqd), "below", "信用利差走阔"),
    ("ARKK÷SPY", _ratio(arkk, spy), "below", "高 beta 科技跑输"),
    ("SMH÷SPY", _ratio(smh, spy), "below", "半导体动能退潮"),
    ("美元 DXY", dxy, "above", "美元走强 · 流动性收紧"),
]

reds = {name: _red_mask(s, d) for name, s, d, _ in INDICATORS}
_avail = {name: (not r.empty) for name, r in reds.items()}
if not any(_avail.values()):
    st.error("⚠️ 所有指标月线都没拉到（yfinance 可能被限流），稍后点侧栏刷新重试。")
    st.stop()

_missing = [name for name, ok in _avail.items() if not ok]
if _missing:
    st.warning(f"⚠️ 以下指标未拉到，已跳过：{', '.join(_missing)}")

red_df = pd.DataFrame({name: reds[name] for name in reds if _avail[name]}).sort_index()

with st.sidebar:
    if st.button("🔄 强制刷新（清月线缓存）"):
        _monthly_close.clear()
        st.rerun()

_win = st.radio("时间跨度", ["5Y", "10Y", "全部"], index=1, horizontal=True, key="risk_win")
_x_hi = red_df.index.max()
if _win == "全部":
    _x_lo = red_df.index.min()
else:
    _x_lo = _x_hi - pd.DateOffset(years=int(_win[:-1]))
    _x_lo = max(_x_lo, red_df.index.min())

# ── 当前状态卡
_last = red_df.index[-1]
_cur_bits = []
for name, _, _, _ in INDICATORS:
    if not _avail[name]:
        continue
    v = reds[name].reindex(red_df.index).iloc[-1]
    dot = "🔴" if v == 1 else ("🟢" if v == 0 else "⚪")
    _cur_bits.append(f"{name} {dot}")
st.markdown(
    f"#### 当前（{_last.strftime('%Y-%m')}，当月未走完）　"
    "<span style='font-size:13px;color:#888;'>各指标破位状态：</span>",
    unsafe_allow_html=True,
)
st.caption("　".join(_cur_bits) + "　（🔴破位/退潮 · 🟢安全 · ⚪数据不足）")

# ── 多轨条带图（各指标一条，共享时间轴）
_tracks = [(name, reds[name], desc) for name, _, _, desc in INDICATORS if _avail[name]]
_n = len(_tracks)

fig = go.Figure()
for i, (label, mask, _desc) in enumerate(_tracks):
    _yb = _n - 1 - i                     # i=0 在最上
    _y0, _y1 = _yb + 0.12, _yb + 0.88
    fig.add_shape(
        type="rect", xref="x", yref="y",
        x0=_x_lo, x1=_x_hi, y0=_y0, y1=_y1,
        fillcolor="rgba(46,204,113,0.12)", line_width=0, layer="below",
    )
    for _s0, _s1 in _segs(mask):
        fig.add_shape(
            type="rect", xref="x", yref="y",
            x0=_s0, x1=_s1, y0=_y0, y1=_y1,
            fillcolor="rgba(231,76,60,0.60)", line_width=0, layer="below",
        )

# 透明散点撑起坐标范围（shape 本身不建立坐标轴）
fig.add_trace(go.Scatter(
    x=[_x_lo, _x_hi], y=[0, _n], mode="markers",
    marker=dict(opacity=0), showlegend=False, hoverinfo="skip",
))
fig.update_layout(
    height=90 + _n * 48,
    margin=dict(l=110, r=20, t=10, b=28),
    plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
    font=dict(color="#ddd"), showlegend=False,
    xaxis=dict(
        showgrid=True, gridcolor="rgba(255,255,255,0.06)",
        range=[_x_lo, _x_hi], tickformat="%Y", dtick="M12",
        ticks="outside", tickfont=dict(size=11, color="#999"),
    ),
    yaxis=dict(
        range=[0, _n], showgrid=False, zeroline=False,
        tickmode="array",
        tickvals=[_n - 1 - i + 0.5 for i in range(_n)],
        ticktext=[t[0] for t in _tracks],
        tickfont=dict(size=12, color="#ddd"),
    ),
)
st.plotly_chart(fig, use_container_width=True, key="risk_ribbons")

st.caption(
    "读法：红段 = 该指标当月破位（风险资产跌破 MA4 / 美元涨破 MA4），绿段 = 安全。"
    "各指标独立看，破位了没、结合自己的判断操作。"
)
