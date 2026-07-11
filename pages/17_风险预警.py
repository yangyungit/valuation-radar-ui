"""风险预警 · 流动性/风险偏好条带

把几个「风险偏好温度计」摆在同一条时间轴上，每个指标一条红/绿条带，
月线跌破自己的均线（月 MA）就标红，自己看哪些破位了。

- 标普 SPY 跌破月 MA10：大盘趋势总闸（月频，纯前端 yfinance）。
- 危险条带（GBDT）：从「科技龙头」页整块复制，红=清仓/橙=减半，依赖后端 API。
- 其余（BTC、HYG÷LQD、ARKK÷SPY、SMH÷SPY）：月频 MA4 交叉，纯前端 yfinance。
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from _yf_session import new_yf_session

st.set_page_config(page_title="风险预警", layout="wide")

st.title("⚠️ 风险预警 · 流动性 / 风险偏好条带")
st.caption(
    "从上到下：**标普 SPY 跌破月 MA10**（大盘趋势总闸）→ **危险条带 GBDT**（后端清仓/减半信号）→ "
    "**风险偏好内部**（BTC、HYG÷LQD、ARKK÷SPY、SMH÷SPY，跌破自己月 MA4 = 🔴）。绿 = 安全，"
    "哪些破位了自己看，结合自己的判断操作。"
)

with st.expander("📖 每个指标是什么、公式怎么算（点开）", expanded=False):
    st.markdown(
        """
| 指标 | 含义 | 公式 | 破红条件 |
|---|---|---|---|
| **标普 SPY（月MA10）** | 大盘趋势总闸。SPY 月末收盘跌破自己 10 个月均线 = 大盘中期转弱、risk-off，最宏观的一道闸 | `SPY月末收盘` | `SPY < MA10(SPY)` |
| **BTC** | 加密资产是全市场风险偏好的最前沿，退潮先从这里开始 | `月末收盘价` | `BTC < MA4(BTC)` |
| **HYG÷LQD**（信用利差） | HYG=高收益垃圾债，LQD=投资级债。比值下行 = 垃圾债跑输投资级 = 信用利差走阔 = 钱在往安全资产躲。比 BTC 更纯净地反映风险偏好 | `HYG月末收盘 ÷ LQD月末收盘` | `比值 < MA4(比值)` |
| **ARKK÷SPY**（高 beta 科技 RS） | ARKK=高成长/高 beta 科技篮子。相对 SPY 的强度下行 = 高风险科技开始跑输大盘 = 资金撤离激进仓位 | `ARKK月末收盘 ÷ SPY月末收盘` | `比值 < MA4(比值)` |
| **SMH÷SPY**（半导体 RS） | SMH=半导体 ETF，全球周期与 AI 资本开支的领先指标。相对 SPY 走弱 = 半导体动能退潮 | `SMH月末收盘 ÷ SPY月末收盘` | `比值 < MA4(比值)` |

**MA 交叉通用算法**：日线拉取 → resample 到月末收盘 → 算 N 个月滚动均线 `MA_N`。当月收盘（或比值）< MA_N → 该月标红；MA 未成形的头 N-1 个月记 ⚪（数据不足）。

**危险条带（GBDT）** 是另一套机制，非 MA 交叉：与「科技龙头」页同源，取后端 GBDT 日频信号——
- 🔴 **红**：GBDT 日频卖出信号触发日 + 后 20 个交易日 → 清仓（月中触发即空仓，不等月末）。
- 🟠 **橙**：旧闸门 `chaos_share > 0.40` 的月份 → 减仓一半；与红重叠时红（清仓）优先。
"""
    )

_MA_WIN = 4  # 月 MA4（默认）


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def _monthly_close(ticker: str, years: int = 15) -> pd.Series:
    """日线拉取后 resample 到月末收盘。失败返回空 Series。"""
    try:
        h = yf.Ticker(ticker, session=new_yf_session()).history(
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


def _red_mask(s: pd.Series, direction: str, win: int = _MA_WIN) -> pd.Series:
    """月线 vs MA_win → 红布尔（float 1/0，MA 未成形的头 win-1 月为 NaN 不算）。"""
    s = s.dropna()
    if s.empty:
        return pd.Series(dtype=float)
    ma = s.rolling(win).mean()
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


def _build_ribbon(tracks: list, x_lo, x_hi, key: str):
    """多轨红/绿条带图。tracks=[(label, red_mask, desc)]，i=0 在最上。"""
    n = len(tracks)
    fig = go.Figure()
    for i, (_label, mask, _desc) in enumerate(tracks):
        _yb = n - 1 - i
        _y0, _y1 = _yb + 0.12, _yb + 0.88
        fig.add_shape(
            type="rect", xref="x", yref="y",
            x0=x_lo, x1=x_hi, y0=_y0, y1=_y1,
            fillcolor="rgba(46,204,113,0.12)", line_width=0, layer="below",
        )
        for _s0, _s1 in _segs(mask):
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=_s0, x1=_s1, y0=_y0, y1=_y1,
                fillcolor="rgba(231,76,60,0.60)", line_width=0, layer="below",
            )
    fig.add_trace(go.Scatter(
        x=[x_lo, x_hi], y=[0, n], mode="markers",
        marker=dict(opacity=0), showlegend=False, hoverinfo="skip",
    ))
    fig.update_layout(
        height=60 + n * 48,
        margin=dict(l=110, r=20, t=10, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"), showlegend=False,
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.06)",
            range=[x_lo, x_hi], tickformat="%Y", dtick="M12",
            ticks="outside", tickfont=dict(size=11, color="#999"),
        ),
        yaxis=dict(
            range=[0, n], showgrid=False, zeroline=False,
            tickmode="array",
            tickvals=[n - 1 - i + 0.5 for i in range(n)],
            ticktext=[t[0] for t in tracks],
            tickfont=dict(size=12, color="#ddd"),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


with st.spinner("📊 拉取各指标月线..."):
    btc = _monthly_close("BTC-USD")
    hyg = _monthly_close("HYG")
    lqd = _monthly_close("LQD")
    arkk = _monthly_close("ARKK")
    smh = _monthly_close("SMH")
    spy = _monthly_close("SPY")

# (显示名, 月线 series, 方向, MA 窗口, 说明)。direction=below → 跌破 MA 红
INDICATORS = [
    ("标普SPY(MA10)", spy, "below", 10, "大盘趋势总闸"),
    ("BTC", btc, "below", 4, "加密风险偏好退潮"),
    ("HYG÷LQD", _ratio(hyg, lqd), "below", 4, "信用利差走阔"),
    ("ARKK÷SPY", _ratio(arkk, spy), "below", 4, "高 beta 科技跑输"),
    ("SMH÷SPY", _ratio(smh, spy), "below", 4, "半导体动能退潮"),
]

reds = {name: _red_mask(s, d, w) for name, s, d, w, _ in INDICATORS}
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
for name, _, _, _, _ in INDICATORS:
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

# ── 第 1 条：标普 SPY 跌破月 MA10（大盘趋势总闸，最上面）
_spy_name = "标普SPY(MA10)"
if _avail[_spy_name]:
    st.markdown("#### 🅢 标普 SPY · 月 MA10 趋势闸")
    _build_ribbon(
        [(_spy_name, reds[_spy_name], "大盘趋势总闸")],
        _x_lo, _x_hi, key="risk_spy_ribbon",
    )

# ── 第 2 条：危险区域时间条带（从「科技龙头」页复制，依赖后端 GBDT 信号）
# 红 = GBDT 日频卖出信号后 20 交易日 → 清仓；橙 = 旧闸门 chaos_share>0.40 月 → 减仓一半
_DANGER_FWD_DAYS = 20
_danger_full = None
_danger_half = None
_cal = None
try:
    from api_client import (
        get_global_data,
        fetch_current_regime,
        compute_macro_regime_api,
    )

    with st.spinner("📊 加载危险区域条带（后端 GBDT）..."):
        df_prices = get_global_data(["SPY"], years=10)
        _current_regime = fetch_current_regime()
        _chain_regime = compute_macro_regime_api(z_window=750)

    if df_prices is not None and not df_prices.empty:
        _cal = pd.DatetimeIndex(df_prices.index).sort_values()
        _danger_full = pd.Series(False, index=_cal)
        _danger_half = pd.Series(False, index=_cal)

        # (1) GBDT 每个触发日 + 后 N 个交易日 → 清仓（纯日频，月中触发即空仓）
        _dz_trig_raw = (_chain_regime or {}).get("horsemen_daily_chaos_trigger", {}) or {}
        _dz_trig_dates = pd.to_datetime(
            [k for k, v in _dz_trig_raw.items() if v], errors="coerce"
        ).dropna()
        for _td in _dz_trig_dates:
            _pos = int(_cal.searchsorted(_td))
            if _pos < len(_cal):
                _danger_full.iloc[_pos:_pos + _DANGER_FWD_DAYS + 1] = True

        # (2) 旧闸门 chaos_share>0.40 月 → 减仓一半（月频概念）
        _dz_hmp = (
            ((_chain_regime or {}).get("data", {}) or {}).get("horsemen_monthly_probs", {})
            or (_current_regime or {}).get("horsemen_monthly_probs", {})
            or {}
        )
        _dz_recs = []
        for _m_str, _probs in _dz_hmp.items():
            if not isinstance(_probs, dict):
                continue
            try:
                _m_ts = pd.Timestamp(str(_m_str) + "-01")
            except Exception:
                continue
            _dz_recs.append((
                _m_ts,
                float(_probs.get("chaos_share", 0.0) or 0.0) > 0.40,
            ))
        if _dz_recs:
            _dz_mdf = (
                pd.DataFrame(_dz_recs, columns=["date", "old_gate"])
                .set_index("date").sort_index()
            )
            _danger_half = (
                _dz_mdf["old_gate"].reindex(_cal, method="ffill").fillna(False).astype(bool)
            )
        _danger_half = _danger_half & ~_danger_full
except Exception:
    _danger_full = None
    _danger_half = None
    _cal = None

if _danger_full is not None and _cal is not None and bool((_danger_full | _danger_half).any()):
    st.markdown(
        "#### ⚠️ 危险区域条带 "
        "<span style='font-size:13px; color:#888; font-weight:normal;'>"
        "(红 = GBDT 清仓：卖出信号后 20 交易日；橙 = 旧闸门 chaos_share&gt;0.40 月，减仓一半)</span>",
        unsafe_allow_html=True,
    )

    def _bool_segs(s: pd.Series) -> list:
        _flip = s.ne(s.shift()).cumsum()
        return [
            (_grp.index[0], _grp.index[-1])
            for _gid, _grp in s.groupby(_flip)
            if bool(_grp.iloc[0])
        ]

    # 条带占上半部(y 0.42~1)，下半部留给逐段日期标注
    _BAND_Y0 = 0.42
    _rib = go.Figure()
    _rib.add_shape(
        type="rect", xref="x", yref="paper",
        x0=_cal[0], x1=_cal[-1], y0=_BAND_Y0, y1=1,
        fillcolor="rgba(46,204,113,0.10)", line_width=0, layer="below",
    )
    for _seg_list, _fill, _txt_color in [
        (_bool_segs(_danger_half), "rgba(230,126,34,0.55)", "#E67E22"),
        (_bool_segs(_danger_full), "rgba(231,76,60,0.55)", "#E67E73"),
    ]:
        for _s0, _s1 in _seg_list:
            _rib.add_shape(
                type="rect", xref="x", yref="paper",
                x0=_s0, x1=_s1, y0=_BAND_Y0, y1=1,
                fillcolor=_fill, line_width=0, layer="below",
            )
            _rib.add_annotation(
                x=_s0, y=_BAND_Y0 - 0.06, xref="x", yref="paper",
                text=_s0.strftime("%y/%m/%d"),
                showarrow=False, textangle=45,
                xanchor="right", yanchor="top",
                font=dict(size=9, color=_txt_color),
            )
            _rib.add_annotation(
                x=_s1, y=_BAND_Y0 - 0.06, xref="x", yref="paper",
                text=_s1.strftime("%y/%m/%d"),
                showarrow=False, textangle=45,
                xanchor="left", yanchor="top",
                font=dict(size=9, color=_txt_color),
            )
    _rib.add_trace(go.Scatter(
        x=[_cal[0], _cal[-1]], y=[0.5, 0.5], mode="markers",
        marker=dict(opacity=0), showlegend=False, hoverinfo="skip",
    ))
    _rib.update_layout(
        height=130,
        margin=dict(l=20, r=20, t=10, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"),
        showlegend=False,
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.06)",
            range=[_cal[0], _cal[-1]],
            tickformat="%Y", dtick="M12",
            showticklabels=True, ticks="outside",
            tickfont=dict(size=11, color="#999"),
        ),
        yaxis=dict(visible=False, range=[0, 1]),
    )
    st.plotly_chart(_rib, use_container_width=True, key="risk_danger_ribbon")

    if bool(_danger_full.iloc[-1]):
        _dz_status_txt = "<span style='color:#E74C3C; font-weight:bold;'>清仓区（GBDT）</span>"
    elif bool(_danger_half.iloc[-1]):
        _dz_status_txt = "<span style='color:#E67E22; font-weight:bold;'>减仓区（旧闸门）</span>"
    else:
        _dz_status_txt = "<span style='color:#2ECC71; font-weight:bold;'>安全</span>"
    _dz_full_1y = int(_danger_full.iloc[-252:].sum())
    _dz_half_1y = int(_danger_half.iloc[-252:].sum())
    st.caption(
        f"当前：{_dz_status_txt} · 近一年 红(清仓) {_dz_full_1y} 天 / 橙(减半) {_dz_half_1y} 天 / "
        f"共 {min(len(_danger_full), 252)} 天 · 绿=安全",
        unsafe_allow_html=True,
    )
else:
    st.info("危险条带暂不可用（后端 GBDT 信号未拉到，其余条带不受影响）。")

# ── 第 3 条起：风险偏好内部（BTC / HYG÷LQD / ARKK÷SPY / SMH÷SPY）
st.markdown("#### 🌡️ 风险偏好内部（月 MA4 交叉）")
_rest = [(name, reds[name], desc) for name, _, _, _, desc in INDICATORS
         if name != _spy_name and _avail[name]]
if _rest:
    _build_ribbon(_rest, _x_lo, _x_hi, key="risk_ribbons")

st.caption(
    "读法：红段 = 该指标当月破位（跌破自己的 MA），绿段 = 安全。"
    "各指标独立看，破位了没、结合自己的判断操作。"
)
