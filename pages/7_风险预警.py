"""风险预警 · 流动性/风险偏好条带

把几个「风险偏好温度计」摆在同一条时间轴上，每个指标一条红/绿条带，
月线跌破自己的均线（月 MA）就标红，自己看哪些破位了。

- 标普 SPY 跌破月 MA10：大盘趋势总闸（月频，纯前端 yfinance）。
- 熊市闸门（SPY 日线 MA100）：与「科技龙头」页同源，橙=减半，依赖后端 API。
- GBDT 急跌/慢跌概率：后端 horsemen_daily_*，SPY 日线上标出触发日，仅参考。
- 其余（BTC 月 MA10，HYG÷LQD、ARKK÷SPY、SMH÷SPY 月 MA24）：月频 MA 交叉，纯前端 yfinance。
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
import yfinance as yf
from _yf_session import new_yf_session

st.set_page_config(page_title="风险预警", layout="wide")

st.title("⚠️ 风险预警 · 流动性 / 风险偏好条带")
st.caption(
    "从上到下：**标普 SPY 跌破月 MA10**（大盘趋势总闸）→ **熊市闸门（SPY 日线 MA100）**（后端减半信号）→ "
    "**风险偏好内部**（BTC 跌破自己月 MA10，HYG÷LQD、ARKK÷SPY、SMH÷SPY 跌破自己月 MA24 = 🔴）→ "
    "**防守腿池宽度**（page 8 带鱼池非科技，宽度 <40% 报警）。绿 = 安全，"
    "哪些破位了自己看，结合自己的判断操作。"
)

with st.expander("📖 每个指标是什么、公式怎么算（点开）", expanded=False):
    st.markdown(
        """
| 指标 | 含义 | 公式 | 破红条件 |
|---|---|---|---|
| **标普 SPY（月MA10）** | 大盘趋势总闸。SPY 月末收盘跌破自己 10 个月均线 = 大盘中期转弱、risk-off，最宏观的一道闸 | `SPY月末收盘` | `SPY < MA10(SPY)` |
| **BTC** | 加密资产是全市场风险偏好的最前沿，退潮先从这里开始 | `月末收盘价` | `BTC < MA10(BTC)` |
| **HYG÷LQD**（信用利差） | HYG=高收益垃圾债，LQD=投资级债。比值下行 = 垃圾债跑输投资级 = 信用利差走阔 = 钱在往安全资产躲。比 BTC 更纯净地反映风险偏好 | `HYG月末收盘 ÷ LQD月末收盘` | `比值 < MA24(比值)` |
| **ARKK÷SPY**（高 beta 科技 RS） | ARKK=高成长/高 beta 科技篮子。相对 SPY 的强度下行 = 高风险科技开始跑输大盘 = 资金撤离激进仓位 | `ARKK月末收盘 ÷ SPY月末收盘` | `比值 < MA24(比值)` |
| **SMH÷SPY**（半导体 RS） | SMH=半导体 ETF，全球周期与 AI 资本开支的领先指标。相对 SPY 走弱 = 半导体动能退潮 | `SMH月末收盘 ÷ SPY月末收盘` | `比值 < MA24(比值)` |
| **防守池宽度** | page 8（FCF%单仓）带鱼池非科技成员中，月末收盘在自身通道上方的占比。单票破线是噪声，全池同破 = 系统性下跌 | `收盘 > MA6×(1−0.25·σ12) 的成员数 ÷ 有效成员数` | `宽度 < 40%`（回到 ≥50% 才解除，滞回） |

**MA 交叉通用算法**：日线拉取 → resample 到月末收盘 → 算 N 个月滚动均线 `MA_N`。当月收盘（或比值）< MA_N → 该月标红；MA 未成形的头 N-1 个月记 ⚪（数据不足）。

**熊市闸门（SPY 日线 MA100）** 与「科技龙头」页同源，后端算：
- 🟠 **橙**：SPY 日收盘连续 5 个交易日 < MA100 → 减仓一半；连续 5 个交易日收回 MA100 上方才解除。
- 和最上面「SPY 月 MA10」的区别：这条是日线、反应快一个月左右；月 MA10 是慢闸。
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


def _bool_segs(s: pd.Series) -> list:
    """日频布尔 Series → 连续 True 段 [(首日, 末日)]。"""
    _flip = s.ne(s.shift()).cumsum()
    return [
        (_grp.index[0], _grp.index[-1])
        for _gid, _grp in s.groupby(_flip)
        if bool(_grp.iloc[0])
    ]


def _build_ma_chart(name: str, s: pd.Series, win: int, x_lo, x_hi, key: str):
    """单指标月线 + MA 折线图，红段（跌破 MA）用背景色标出。"""
    s = s.dropna()
    if s.empty:
        return
    ma = s.rolling(win).mean()
    mask = _red_mask(s, "below", win)
    fig = go.Figure()
    for _s0, _s1 in _segs(mask):
        fig.add_vrect(x0=_s0, x1=_s1, fillcolor="rgba(231,76,60,0.18)", line_width=0, layer="below")
    fig.add_trace(go.Scatter(
        x=s.index, y=s.values, mode="lines", name=name,
        line=dict(color="#ddd", width=1.3),
    ))
    fig.add_trace(go.Scatter(
        x=ma.index, y=ma.values, mode="lines", name=f"MA{win}",
        line=dict(color="#f39c12", width=1.3, dash="dot"),
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=50, r=20, t=30, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"),
        title=dict(text=f"{name} · 月线 & MA{win}", font=dict(size=13, color="#ddd")),
        legend=dict(orientation="h", y=1.18, x=0, font=dict(size=10)),
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.06)",
            range=[x_lo, x_hi], tickformat="%Y", dtick="M12",
            ticks="outside", tickfont=dict(size=10, color="#999"),
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.06)",
            tickfont=dict(size=10, color="#999"),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


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
    ("BTC", btc, "below", 10, "加密风险偏好退潮"),
    ("HYG÷LQD", _ratio(hyg, lqd), "below", 24, "信用利差走阔"),
    ("ARKK÷SPY", _ratio(arkk, spy), "below", 24, "高 beta 科技跑输"),
    ("SMH÷SPY", _ratio(smh, spy), "below", 24, "半导体动能退潮"),
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
    if st.button("🔄 强制刷新（清月线 + 后端缓存）"):
        from api_client import compute_macro_regime_api as _cmr

        _monthly_close.clear()
        _cmr.clear()
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

# ── 第 2 条：熊市闸门条带（与「科技龙头」页同源，后端 bear_gate_daily）
# 橙 = SPY 连续 5 日收盘 < MA100（连续 5 日收回才关）→ 减仓一半
_danger_half = None
_cal = None
_chain_regime = None
df_prices = None
try:
    from api_client import (
        get_global_data,
        compute_macro_regime_api,
    )

    with st.spinner("📊 加载熊市闸门（后端）..."):
        df_prices = get_global_data(["SPY"], years=10)
        _chain_regime = compute_macro_regime_api(z_window=750)

    if df_prices is not None and not df_prices.empty:
        _cal = pd.DatetimeIndex(df_prices.index).sort_values()
        _bg_raw = (_chain_regime or {}).get("bear_gate_daily", {}) or {}
        if _bg_raw:
            _bear_gate = (
                pd.Series(list(_bg_raw.values()), index=pd.to_datetime(list(_bg_raw.keys()), errors="coerce"))
                .dropna().sort_index().astype(bool)
                .reindex(_cal, method="ffill").fillna(False).astype(bool)
            )
        else:
            _bear_gate = None
        _danger_half = _bear_gate
except Exception:
    _danger_half = None
    _cal = None

if _danger_half is not None and _cal is not None and bool(_danger_half.any()):
    st.markdown(
        "#### ⚠️ 熊市闸门条带 "
        "<span style='font-size:13px; color:#888; font-weight:normal;'>"
        "(橙 = SPY 跌破 MA100，减仓一半；绿 = 满仓)</span>",
        unsafe_allow_html=True,
    )

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

    if bool(_danger_half.iloc[-1]):
        _dz_status_txt = "<span style='color:#E67E22; font-weight:bold;'>减仓区（SPY &lt; MA100）</span>"
    else:
        _dz_status_txt = "<span style='color:#2ECC71; font-weight:bold;'>满仓</span>"
    _dz_half_1y = int(_danger_half.iloc[-252:].sum())
    st.caption(
        f"当前：{_dz_status_txt} · 近一年 橙(减半) {_dz_half_1y} 天 / "
        f"共 {min(len(_danger_half), 252)} 天 · 绿=满仓",
        unsafe_allow_html=True,
    )
else:
    st.info("熊市闸门暂不可用（后端 bear_gate_daily 未拉到）。")

# ── GBDT 急跌概率：寂静后首峰读法（后端 horsemen_daily_quiet_spike，与熊市闸门同一次 API 调用）
st.markdown("#### 🤖 急跌概率 — 寂静后首峰（仅参考，不驱动仓位）")
st.caption(
    "急跌模型学「未来 20 交易日 SPY 最低点 ≤ -8%」，历史概率为 walk-forward。"
    "原 0.50 规则 10 年报 24 次中 6 次，假警几乎全挤在大崩盘后一年的余震期，改用新读法："
    "概率在 0.10 以下安静 ≥ 120 个交易日后第一次冲过 0.10 就报警；"
    "报警后 60 个交易日 SPY 最低点 ≤ -8% 算真。假警那座小山不重置寂静计数，真警或概率冲过 0.50 的大山才重置。"
    "仓位闸门是上面的 SPY 日线 MA100。"
)


def _api_series(key: str) -> pd.Series:
    raw = (_chain_regime or {}).get(key, {}) or {}
    if not raw:
        return pd.Series(dtype=float)
    return pd.Series(list(raw.values()), index=pd.to_datetime(list(raw.keys()))).sort_index()


_prob_s = _api_series("horsemen_daily_chaos_prob").astype(float)
if not _prob_s.empty:
    _qs_raw = (_chain_regime or {}).get("horsemen_daily_quiet_spike", {}) or {}
    _qs = pd.DataFrame(_qs_raw.get("signals", []) or [])
    _quiet_now = int(_qs_raw.get("quiet_days_now", 0) or 0)
    _pk = pd.DataFrame(_qs_raw.get("panic_peaks", []) or [])
    if not _pk.empty:
        _pk["date"] = pd.to_datetime(_pk["date"])
    if not _qs.empty:
        _qs["date"] = pd.to_datetime(_qs["date"])
        _qs = _qs.sort_values("date")
    _QS_STYLE = {
        "真":   ("#E74C3C", "真警"),
        "假":   ("#888888", "假警"),
        "评估中": ("#E67E22", "评估中"),
    }

    _spy_d = None
    if df_prices is not None and not df_prices.empty and "SPY" in df_prices.columns:
        _spy_d = df_prices["SPY"].dropna()
        _spy_idx = pd.DatetimeIndex(_spy_d.index)
        _spy_d.index = _spy_idx.tz_localize(None) if _spy_idx.tz is not None else _spy_idx
        _dd = (_spy_d / _spy_d.cummax() - 1)[_spy_d.index >= _prob_s.index[0]]
        _spy_d = _spy_d[_spy_d.index >= _prob_s.index[0]]

    _fig_g = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        row_heights=[0.5, 0.25, 0.25],
    )
    if _spy_d is not None and not _spy_d.empty:
        _fig_g.add_trace(go.Scatter(
            x=_dd.index, y=_dd.values * 100, mode="lines", name="距前高回撤",
            line=dict(color="#E74C3C", width=1), fill="tozeroy", fillcolor="rgba(231,76,60,0.15)",
            hovertemplate="%{x|%Y-%m-%d}<br>距前高 %{y:.1f}%<extra></extra>", showlegend=False,
        ), row=3, col=1)
        for _lv in (-10, -20):
            _fig_g.add_hline(y=_lv, line=dict(color="#666", width=1, dash="dot"), row=3, col=1)
    if _spy_d is not None and not _spy_d.empty:
        _fig_g.add_trace(go.Scatter(
            x=_spy_d.index, y=_spy_d.values, mode="lines", name="SPY",
            line=dict(color="#ddd", width=1.2),
        ), row=1, col=1)

    _fig_g.add_trace(go.Scatter(
        x=_prob_s.index, y=_prob_s.values, mode="lines", name="急跌概率(20日)",
        line=dict(color="rgba(52,152,219,0.25)", width=0.6), hoverinfo="skip",
    ), row=2, col=1)
    _fig_g.add_hline(y=0.10, line=dict(color="#888", width=1, dash="dash"), row=2, col=1)

    if not _qs.empty:
        for _verdict, (_clr, _nm) in _QS_STYLE.items():
            _sub = _qs[_qs["verdict"] == _verdict]
            if _sub.empty:
                continue
            _cd = list(zip(_sub["prob"], _sub["quiet_days"],
                           [("—" if pd.isna(m) else f"{m*100:+.1f}%") for m in _sub["mdd"]]))
            _hover = ("%{x|%Y-%m-%d}<br>概率 %{customdata[0]:.2f} · 寂静 %{customdata[1]} 日"
                      "<br>后 60 日最低 %{customdata[2]}<extra>" + _nm + "</extra>")
            if _spy_d is not None and not _spy_d.empty:
                _fig_g.add_trace(go.Scatter(
                    x=_sub["date"], y=_spy_d.reindex(_sub["date"], method="nearest").values,
                    mode="markers", name=_nm,
                    marker=dict(color=_clr, size=11, symbol="triangle-down",
                                line=dict(color="#1a1a1a", width=1)),
                    customdata=_cd, hovertemplate=_hover,
                ), row=1, col=1)
            _fig_g.add_trace(go.Scatter(
                x=_sub["date"], y=_sub["prob"], mode="markers", name=_nm, showlegend=False,
                marker=dict(color=_clr, size=9, line=dict(color="#1a1a1a", width=1)),
                customdata=_cd, hovertemplate=_hover,
            ), row=2, col=1)

    if not _pk.empty:
        _pk_cd = [("—" if r is None or pd.isna(r) else f"{r*100:+.1f}%") for r in _pk["fwd_ret"]]
        _pk_hover = "%{x|%Y-%m-%d}<br>概率 %{customdata:.2f} → 后 60 日 %{text}<extra>极致恐慌</extra>"
        if _spy_d is not None and not _spy_d.empty:
            _pk_pos = _spy_d.index.get_indexer(_pk["date"], method="nearest")
            _buy = _spy_d.iloc[sorted({p for s in _pk_pos for p in range(s, min(s + 10, len(_spy_d)))})]
            _fig_g.add_trace(go.Scatter(
                x=_buy.index, y=_buy.values, mode="markers", name="恐慌后买入(10 交易日)",
                marker=dict(color="#2ECC71", size=5),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY %{y:.2f}<extra>买入日</extra>",
            ), row=1, col=1)
            _fig_g.add_trace(go.Scatter(
                x=_pk["date"], y=_spy_d.reindex(_pk["date"], method="nearest").values,
                mode="markers", name="极致恐慌(≥0.90)",
                marker=dict(color="#2ECC71", size=11, symbol="triangle-up",
                            line=dict(color="#1a1a1a", width=1)),
                customdata=_pk["prob"], text=_pk_cd, hovertemplate=_pk_hover,
            ), row=1, col=1)
        _fig_g.add_trace(go.Scatter(
            x=_pk["date"], y=_pk["prob"], mode="markers", name="极致恐慌(≥0.90)", showlegend=False,
            marker=dict(color="#2ECC71", size=9, symbol="triangle-up", line=dict(color="#1a1a1a", width=1)),
            customdata=_pk["prob"], text=_pk_cd, hovertemplate=_pk_hover,
        ), row=2, col=1)
        _fig_g.add_hline(y=0.90, line=dict(color="#2ECC71", width=1, dash="dot"), row=2, col=1)

    # plotly 的 across 竖线只跨「用同一根 x 轴」的子图，所以三行都挂到 x 上
    _fig_g.update_traces(xaxis="x")
    _fig_g.update_shapes(xref="x domain")

    _grid = dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=10, color="#999"))
    _fig_g.update_layout(
        height=680,
        margin=dict(l=50, r=20, t=30, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"),
        legend=dict(orientation="h", y=1.06, x=0, font=dict(size=10)),
        hovermode="closest",
        spikedistance=-1,
        xaxis2_visible=False, xaxis3_visible=False,
    )
    _fig_g.update_xaxes(**_grid, tickformat="%Y", dtick="M12", hoverformat="%Y-%m-%d")
    _fig_g.update_xaxes(
        anchor="y3", matches=None, showticklabels=True,
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikedash="dot", spikecolor="#888",
        row=1, col=1,
    )
    _fig_g.update_yaxes(**_grid, title_text="SPY", row=1, col=1)
    _fig_g.update_yaxes(**_grid, title_text="概率", range=[0, 1], row=2, col=1)
    _fig_g.update_yaxes(**_grid, title_text="回撤%", ticksuffix="%", row=3, col=1)
    st.plotly_chart(_fig_g, use_container_width=True, key="risk_gbdt_chart")

    _cur_prob = float(_prob_s.iloc[-1])
    if _quiet_now >= 120:
        _armed_txt = f"<span style='color:#E67E22; font-weight:bold;'>寂静已满 {_quiet_now} 日，下次冲过 0.10 即报警</span>"
    else:
        _armed_txt = f"寂静累计 {_quiet_now} 日（需 ≥ 120 才会报警）"
    if _qs.empty:
        st.caption(f"历史上无寂静后首峰信号。当前概率 {_cur_prob:.2f}，{_armed_txt}。", unsafe_allow_html=True)
    else:
        _n_true = int((_qs["verdict"] == "真").sum())
        _n_false = int((_qs["verdict"] == "假").sum())
        _last = _qs.iloc[-1]
        _last_clr, _last_nm = _QS_STYLE.get(_last["verdict"], ("#888", _last["verdict"]))
        st.caption(
            f"历史 {len(_qs)} 次报警：真 {_n_true} · 假 {_n_false}。"
            f"最近一次 {_last['date'].date()}（概率 {_last['prob']:.2f}，寂静 {int(_last['quiet_days'])} 日）→ "
            f"<span style='color:{_last_clr}; font-weight:bold;'>{_last_nm}</span>。"
            f"当前概率 {_cur_prob:.2f}，{_armed_txt}。"
            "红 = 后 60 日跌 ≥ 8%，灰 = 没跌，橙 = 60 日窗口未走完。淡蓝细线 = 原始概率，只当背景。",
            unsafe_allow_html=True,
        )
    if not _pk.empty:
        _pk_done = _pk["fwd_ret"].dropna()
        st.caption(
            f"绿色 ▲ = 概率首次冲过 0.90（前 20 日没过线），历史 {len(_pk)} 次，"
            "SPY 线上的绿色小点 = 从信号日起连续 10 个交易日（两周）每天买入，"
            f"后 60 日为正 {int((_pk_done > 0).sum())}/{len(_pk_done)}，均值 {_pk_done.mean()*100:+.1f}%。"
            "读作 2–6 个月视角的加仓区，不是当日抄底：2020-03 / 2022-06 过线后又跌 22% / 12% 才见底。"
        )

    if _spy_d is not None and not _spy_d.empty:
        _ev = [(d, _QS_STYLE.get(v, ("", v))[1]) for d, v in zip(_qs.get("date", []), _qs.get("verdict", []))]
        _ev += [(d, "极致恐慌") for d in _pk.get("date", [])]
        _rows = []
        for _d, _kind in sorted(_ev):
            _i = _spy_d.index.get_indexer([_d], method="nearest")[0]
            _win = _spy_d.iloc[_i:_i + 61]
            _t = _win.idxmin()
            _rows.append({
                "信号日": _spy_d.index[_i].date(),
                "类型": _kind,
                "当日距前高": f"{_dd.iloc[_i] * 100:+.1f}%",
                "之后 60 日再跌": f"{(_win.min() / _win.iloc[0] - 1) * 100:+.1f}%",
                "低点日期": _t.date(),
                "低点距前高": f"{_dd.loc[_t] * 100:+.1f}%",
                "信号到低点(交易日)": _spy_d.index.get_loc(_t) - _i,
            })
        st.caption(
            f"当前 SPY 距前高 {_dd.iloc[-1] * 100:+.1f}%，本图区间最深 {_dd.min() * 100:.1f}%"
            f"（{_dd.idxmin().date()}）。下表：每个信号出现后 60 个交易日内的最低点，最后几行窗口可能未走完。"
        )
        if _rows:
            st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

    for _top_key, _top_title in (
        ("horsemen_daily_chaos_top_features", "急跌模型最新一日归因（SHAP top3）"),
        ("horsemen_daily_slow_top_features", "慢跌模型最新一日归因（SHAP top3）"),
    ):
        _latest_top = (_chain_regime or {}).get(_top_key, []) or []
        if _latest_top:
            _top_lines = [
                f"- **{item.get('feature','?')}**：贡献 {float(item.get('shap', 0.0)):+.3f}"
                for item in _latest_top[:3]
            ]
            st.markdown(f"**{_top_title}**：\n" + "\n".join(_top_lines))
else:
    st.info("GBDT 数据暂不可用（后端 horsemen_daily_chaos_prob 未拉到）。")

# ── 第 3 条起：风险偏好内部（BTC / HYG÷LQD / ARKK÷SPY / SMH÷SPY）
st.markdown("#### 🌡️ 风险偏好内部（BTC 月 MA10 / 其余月 MA24 交叉）")
_rest = [(name, reds[name], desc) for name, _, _, _, desc in INDICATORS
         if name != _spy_name and _avail[name]]
if _rest:
    _build_ribbon(_rest, _x_lo, _x_hi, key="risk_ribbons")

st.caption(
    "读法：红段 = 该指标当月破位（跌破自己的 MA），绿段 = 安全。"
    "各指标独立看，破位了没、结合自己的判断操作。"
)

# ── 第 4 条：防守腿池宽度（page 8 FCF%单仓 联动，round17）
# 单票破线是噪声（54 段 whipsaw 实证），全池同破 = 系统性下跌。
# 只在 2008 式慢熊有反应时间（2008-07 触发，离底还有 8 个月）；
# 2020 式快崩月频信号来不及，触发时底已过，不建议照着行动。
_BR_OFF, _BR_ON, _BR_MIN_VALID = 0.40, 0.50, 10
_breadth, _br_state = None, None
try:
    from api_client import fetch_logr2_stable_pool, get_global_data as _ggd

    _doc = fetch_logr2_stable_pool()
    _pools = ({int(y): list(m) for y, m in (_doc.get("pools") or {}).items()}
              if _doc.get("success") else {})
    _meta = _doc.get("meta") or {}
    _pool_rest = sorted({t for mem in _pools.values() for t in mem
                         if not (_meta.get(t) or {}).get("is_tech")})
    if _pool_rest:
        _BR_ALIAS = {"BRK.B": "BRK-B"}
        with st.spinner("📊 加载防守池宽度（page 8 联动）..."):
            _pxd = _ggd([_BR_ALIAS.get(t, t) for t in _pool_rest], years=12)
        if _pxd is not None and not _pxd.empty:
            _cm = pd.DataFrame({t: _pxd[_BR_ALIAS.get(t, t)]
                                for t in _pool_rest if _BR_ALIAS.get(t, t) in _pxd.columns})
            _cm = _cm.resample("ME").last()
            _floor = _cm.rolling(6).mean() * (1 - 0.25 * _cm.pct_change().rolling(12).std())
            _memb_b = pd.DataFrame(False, index=_cm.index, columns=_cm.columns)
            for _y, _mem in _pools.items():
                _memb_b.loc[_memb_b.index.year == _y,
                            [t for t in _mem if t in _memb_b.columns]] = True
            _valid = _memb_b & _floor.notna() & _cm.notna()
            _nv = _valid.sum(axis=1)
            _breadth = (((_cm > _floor) & _valid).sum(axis=1) / _nv.where(_nv >= 1)).dropna()
            _on, _st_rec = True, {}
            for _dt in _breadth.index:
                _b = float(_breadth[_dt])
                if int(_nv.get(_dt, 0)) >= _BR_MIN_VALID:
                    if _on and _b < _BR_OFF:
                        _on = False
                    elif not _on and _b >= _BR_ON:
                        _on = True
                _st_rec[_dt] = _on
            _br_state = pd.Series(_st_rec)
except Exception:
    _breadth, _br_state = None, None

if _breadth is not None and _br_state is not None and not _breadth.empty:
    st.markdown(
        "#### 🛡️ 防守腿池宽度 "
        "<span style='font-size:13px; color:#888; font-weight:normal;'>"
        "(page 8 带鱼池非科技 · 通道上方成员占比 · &lt;40% 报警，回到 ≥50% 解除)</span>",
        unsafe_allow_html=True,
    )
    _br_red = (~_br_state).astype(float)
    _build_ribbon([("防守池宽度", _br_red, "")], _x_lo, _x_hi, key="risk_breadth_ribbon")

    _fig_b = go.Figure()
    for _s0, _s1 in _segs(_br_red):
        _fig_b.add_vrect(x0=_s0, x1=_s1, fillcolor="rgba(231,76,60,0.18)",
                         line_width=0, layer="below")
    _fig_b.add_trace(go.Scatter(
        x=_breadth.index, y=_breadth.values, mode="lines", name="宽度",
        line=dict(color="#ddd", width=1.3),
    ))
    _fig_b.add_hline(y=_BR_OFF, line=dict(color="#E74C3C", width=1, dash="dot"))
    _fig_b.add_hline(y=_BR_ON, line=dict(color="#2ECC71", width=1, dash="dot"))
    _fig_b.update_layout(
        height=220,
        margin=dict(l=50, r=20, t=30, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"), showlegend=False,
        title=dict(text="防守池宽度 · 月频（红线 40% 报警 / 绿线 50% 解除）",
                   font=dict(size=13, color="#ddd")),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)",
                   range=[_x_lo, _x_hi], tickformat="%Y", dtick="M12",
                   ticks="outside", tickfont=dict(size=10, color="#999")),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)",
                   tickformat=".0%", range=[0, 1.02],
                   tickfont=dict(size=10, color="#999")),
    )
    st.plotly_chart(_fig_b, use_container_width=True, key="risk_breadth_chart")

    _b_last = float(_breadth.iloc[-1])
    if bool(_br_state.iloc[-1]):
        _b_txt = "<span style='color:#2ECC71; font-weight:bold;'>安全</span>"
    else:
        _b_txt = "<span style='color:#E74C3C; font-weight:bold;'>报警（系统性下跌）</span>"
    st.caption(
        f"当前：{_b_txt} · 宽度 {_b_last * 100:.0f}%"
        f"（{_breadth.index[-1].strftime('%Y-%m')}，当月未走完）。"
        "读法：这是 page 8 防守腿的慢熊警报——单票破线是噪声，全池同破才是系统性下跌。"
        "回测（round17）：2008 式慢熊触发时离底还有 8 个月，有反应时间；"
        "2020 式快崩触发时底已过，别照着砍。是否降防守腿仓位自己判断，引擎不自动动。",
        unsafe_allow_html=True,
    )
else:
    st.info("防守池宽度暂不可用（池子或价格未拉到，其余条带不受影响）。")

# ── 三个比值指标详情图（月线 + MA24），方便肉眼判断走势/破位是否靠谱
st.markdown("#### 📈 三个比值指标详情（月线 + MA24）")
for _name, _s, _d, _w, _desc in INDICATORS:
    if _name in ("HYG÷LQD", "ARKK÷SPY", "SMH÷SPY") and _avail[_name]:
        _build_ma_chart(_name, _s, _w, _x_lo, _x_hi, key=f"risk_ma_chart_{_name}")
