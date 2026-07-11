import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from api_client import (
    fetch_buyback_relay_timeseries,
    fetch_buyback_fcf_relay_timeseries,
    fetch_macro_radar_timeseries,
    fetch_gbdt_oos_prices,
    get_global_data,
)
import holdings_viz as hv

st.set_page_config(page_title="组合净值", layout="wide")

# ── 组合口径（与原页保持同源）──
WINDOW = "10Y"                       # 三条曲线统一 10Y
WEIGHTS = {"A": 0.4, "B": 0.3, "C": 0.3}  # 起始仓位 4:3:3，每年末再平衡回此比例
_TECH_TICKERS = {"AAPL", "MSFT", "GOOGL", "META", "TXN", "AVGO", "ORCL", "CSCO", "ADBE", "QCOM"}
_DYNASTY_GROUPS = ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"]
_DYNASTY_BUFFER = 4
_K_STABLE = 1.0                      # A（回购稳定）δ 默认，同 page 8
_K_ATTACK = 0.75                     # C（回购进攻）δ 默认，同 page 7

st.title("📊 ABC 组合净值")
st.caption(
    "**A = 回购稳定**（股东回报率排名，金+银 2 仓 50/50，δ=1.0）· "
    "**B = 板块王朝外层 ETF 轮动**（king_score 月末排名接力，左列+右列 50/50，守擂 buffer=4）· "
    "**C = 回购进攻**（纯科技股 king_score 动量，金+银 2 仓 50/50，δ=0.75）· "
    f"三条均 {WINDOW} 周线、与原页同源。合成 = 起始 4:3:3、**每年末再平衡**回此比例。"
    "三条 + 合成 + SPY 统一裁到「三条都有数据」的共同窗口、起点归一为 1。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_buyback_relay_timeseries.clear()
        fetch_buyback_fcf_relay_timeseries.clear()
        fetch_macro_radar_timeseries.clear()
        get_global_data.clear()
        st.rerun()


def _inband_streak(rank_df: pd.DataFrame, limit: int) -> pd.DataFrame:
    """每月「连续在榜」月数：本月在 Top{limit} 则 = 上月 +1，否则清零。"""
    _ib = (rank_df <= limit).to_numpy()
    _arr = _ib.astype(int)
    for _i in range(1, _arr.shape[0]):
        _arr[_i] = (_arr[_i - 1] + 1) * _ib[_i]
    return pd.DataFrame(_arr, index=rank_df.index, columns=rank_df.columns)


def _relay_navc(score_m, cols, price_cache, spy_wk, k, n_hold=2, entry_min_top2_hits=2):
    """复刻 buyback_relay_core.render_group 默认档（weekly / 非动态 / 无 MA 留任）的
    持仓选择 + 左右列 50/50 合成净值，不渲染 UI。用于组合页 A / C 曲线，保证与 page 7/8 同源。
    """
    cols = [c for c in cols if c in score_m.columns]
    if not cols:
        return pd.Series(dtype=float)
    g_score = score_m[cols]
    rank_m = g_score.rank(axis=1, ascending=False, method="min")
    band = n_hold
    ten6 = (rank_m <= band).astype(int).rolling(6, min_periods=1).sum()
    streak = _inband_streak(rank_m, band)

    mh: dict = {}
    prev_h: list = []
    for ts, row in rank_m.iterrows():
        r = row.dropna().sort_values()
        if r.empty:
            continue
        order = r.index.tolist()
        tnow = ten6.loc[ts]
        snow = streak.loc[ts]
        sc = g_score.loc[ts].dropna()
        cut2 = (
            float(sc.sort_values(ascending=False).iloc[band - 1]) if len(sc) >= band
            else (float(sc.iloc[0]) if len(sc) else float("nan"))
        )
        delta = k * (float(sc.std()) if len(sc) >= 2 else 0.0)
        hold = [t for t in prev_h if t != "CASH" and t in sc.index and sc[t] >= cut2 - delta][:n_hold] if prev_h else []
        elig = [t for t in order if r[t] <= band and float(tnow.get(t, 0)) >= entry_min_top2_hits]
        elig_t = sorted(elig, key=lambda t: (-float(snow.get(t, 0)), r[t]))
        for t in elig_t:
            if len(hold) >= n_hold:
                break
            if t not in hold:
                hold.append(t)
        hold = (hold + ["CASH"] * n_hold)[:n_hold]
        mh[hv.next_month_key(ts.strftime("%Y-%m"), 1)] = hold
        prev_h = hold

    exec_months = sorted(mh)
    if not exec_months:
        return pd.Series(dtype=float)
    slots = hv.build_basket_slot_assignments(mh, exec_months)
    seg_l = hv.build_slot_segments(slots, 0, exec_months)
    seg_r = hv.build_slot_segments(slots, 1, exec_months)
    nav_l = hv.calc_slot_stats(seg_l, price_cache, spy_wk, 0.04)[2]
    nav_r = hv.calc_slot_stats(seg_r, price_cache, spy_wk, 0.04)[2]
    if nav_l.empty and nav_r.empty:
        return pd.Series(dtype=float)
    if nav_l.empty:
        return nav_r.copy()
    if nav_r.empty:
        return nav_l.copy()
    uidx = nav_l.index.union(nav_r.index)
    return 0.5 * nav_l.reindex(uidx).ffill().bfill() + 0.5 * nav_r.reindex(uidx).ffill().bfill()


def _weekly_cache(pool, years=10):
    """get_global_data → {ticker: DataFrame(Close)} 周线 + SPY 周线。"""
    px = get_global_data(list(pool) + ["SPY"], years=years)
    price_cache: dict = {}
    spy_wk = pd.DataFrame()
    if px is not None and not px.empty:
        wk = px.resample("W-FRI").last()
        if "SPY" in wk.columns:
            spy_wk = wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
        for tk in pool:
            if tk in wk.columns:
                s = wk[tk].dropna()
                if len(s) >= 2:
                    price_cache[tk] = s.to_frame(name="Close")
    return price_cache, spy_wk


# ── A：回购稳定（旧接口，剔除科技子集后的其余组，与 page 8 同源）──
with st.spinner("📊 加载回购股东回报率时序 + 价格..."):
    bb = fetch_buyback_relay_timeseries(WINDOW)

nav_a = pd.Series(dtype=float)
spy_wk_bb = pd.DataFrame()
if not bb.get("success"):
    st.warning(f"⚠️ 回购股东回报率时序不可用：{bb.get('error', '未知错误')}（A 曲线缺失）")
else:
    _bt = bb.get("tickers", {}) or {}
    _bd = bb.get("dates", []) or []
    if _bt and _bd:
        _bidx = pd.to_datetime(_bd, errors="coerce")
        _n = len(_bidx)

        def _al(v):
            v = list(v or [])
            return v if len(v) == _n else [np.nan] * _n

        shy_m = pd.DataFrame({tk: _al(p.get("shareholder_yield")) for tk, p in _bt.items()}, index=_bidx).astype(float).resample("ME").last()
        with st.spinner("📊 加载回购稳定价格..."):
            _bb_cache, spy_wk_bb = _weekly_cache(list(_bt.keys()))
        _rest = [c for c in shy_m.columns if c not in _TECH_TICKERS]
        nav_a = _relay_navc(shy_m, _rest, _bb_cache, spy_wk_bb, _K_STABLE)     # A

# ── C：回购进攻（FCF margin 规则池新接口，is_tech 子集，与 page 7 同源）──
with st.spinner("📊 加载回购进攻(FCF池)时序 + 价格..."):
    bbf = fetch_buyback_fcf_relay_timeseries(WINDOW)

nav_c = pd.Series(dtype=float)
if not bbf.get("success"):
    st.warning(f"⚠️ 回购进攻(FCF池)时序不可用：{bbf.get('error', '未知错误')}（C 曲线缺失）")
else:
    _ft = bbf.get("tickers", {}) or {}
    _fd = bbf.get("dates", []) or []
    if _ft and _fd:
        _fidx = pd.to_datetime(_fd, errors="coerce")
        _fn = len(_fidx)

        def _alf(v):
            v = list(v or [])
            return v if len(v) == _fn else [np.nan] * _fn

        king_m_c = pd.DataFrame({tk: _alf(p.get("king_score")) for tk, p in _ft.items()}, index=_fidx).astype(float).resample("ME").last()
        _tech_cols = [c for c in king_m_c.columns if (_ft.get(c, {}) or {}).get("is_tech")]
        with st.spinner("📊 加载回购进攻价格（含退市补全）..."):
            _fcf_cache, spy_wk_bbf = _weekly_cache(list(_ft.keys()))
            # yfinance 拉不到的退市票（如 ANSS）从 Sharadar gbdt_oos_prices 补全复权日线，同 page 7
            _missing = [t for t in _tech_cols if t not in _fcf_cache]
            if _missing:
                hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(_missing))))
                for _tk in _missing:
                    _d = hv.fetch_daily_ohlcv(_tk)
                    if not _d.empty:
                        _fcf_cache[_tk] = _d["Close"].resample("W-FRI").last().dropna().to_frame(name="Close")
        nav_c = _relay_navc(king_m_c, _tech_cols, _fcf_cache, spy_wk_bbf, _K_ATTACK)   # C

# ── B：板块王朝外层 ETF 轮动（king_score 接力，C+D 组别，buffer=4）──
with st.spinner("📊 加载板块王朝时序 + ETF 价格..."):
    dyn = fetch_macro_radar_timeseries(window=WINDOW, profile="dynasty")

nav_b = pd.Series(dtype=float)
if not dyn.get("success"):
    st.warning(f"⚠️ 板块王朝时序不可用：{dyn.get('error', '未知错误')}（B 曲线缺失）")
else:
    _groups_avail = sorted({
        p.get("group", "") for p in (dyn.get("tickers", {}) or {}).values() if p.get("group", "")
    })
    _groups = [g for g in _DYNASTY_GROUPS if g in _groups_avail] or None
    _slots, _dnm, _exec = hv.dynasty_relay_slots(dyn, _groups, buffer_n=_DYNASTY_BUFFER)
    if _slots and _exec:
        _dyn_pool = sorted({t for m in _exec for t in _slots.get(m, []) if t and t != "CASH"})
        with st.spinner("📊 加载 ETF 价格..."):
            _dyn_cache, _dyn_spy = _weekly_cache(_dyn_pool)
        _seg_l = hv.build_slot_segments(_slots, 0, _exec)
        _seg_r = hv.build_slot_segments(_slots, 1, _exec)
        _nl = hv.calc_slot_stats(_seg_l, _dyn_cache, _dyn_spy, 0.04)[2]
        _nr = hv.calc_slot_stats(_seg_r, _dyn_cache, _dyn_spy, 0.04)[2]
        if not _nl.empty and not _nr.empty:
            _u = _nl.index.union(_nr.index)
            nav_b = 0.5 * _nl.reindex(_u).ffill().bfill() + 0.5 * _nr.reindex(_u).ffill().bfill()
        elif not _nl.empty:
            nav_b = _nl.copy()
        elif not _nr.empty:
            nav_b = _nr.copy()

_sleeves = {"A": nav_a, "B": nav_b, "C": nav_c}
_missing = [k for k, v in _sleeves.items() if v is None or v.empty]
if _missing:
    st.error(f"⚠️ 缺少曲线：{', '.join(_missing)}，无法合成组合。")
    st.stop()

# ── 对齐到共同窗口（交集起点），周线并集索引 ffill ──
_lo = max(v.index.min() for v in _sleeves.values())
_hi = min(v.index.max() for v in _sleeves.values())
if _lo >= _hi:
    st.error("⚠️ 三条曲线无重叠区间，无法合成。")
    st.stop()

_grid = pd.date_range(_lo, _hi, freq="W-FRI")
_norm = {}
for k, v in _sleeves.items():
    s = v.reindex(v.index.union(_grid)).ffill().reindex(_grid).ffill().bfill()
    _norm[k] = s / float(s.iloc[0])

# SPY 同窗口归一
_spy_src = spy_wk_bb if not spy_wk_bb.empty else pd.DataFrame()
spy_norm = pd.Series(dtype=float)
if not _spy_src.empty:
    _sp = _spy_src["Close"].astype(float).reindex(_spy_src.index.union(_grid)).ffill().reindex(_grid).ffill().bfill()
    spy_norm = _sp / float(_sp.iloc[0])

# ── 合成：起始 4:3:3，每年末再平衡回此比例 ──
_a, _b, _c = _norm["A"], _norm["B"], _norm["C"]
_alloc = {"A": WEIGHTS["A"], "B": WEIGHTS["B"], "C": WEIGHTS["C"]}
_prev = {"A": float(_a.iloc[0]), "B": float(_b.iloc[0]), "C": float(_c.iloc[0])}
_out = [1.0]
_year = _grid[0].year
for _t in _grid[1:]:
    _cur = {"A": float(_a.loc[_t]), "B": float(_b.loc[_t]), "C": float(_c.loc[_t])}
    for _k in _alloc:
        _alloc[_k] *= _cur[_k] / _prev[_k] if _prev[_k] else 1.0
    _val = sum(_alloc.values())
    if _t.year != _year:                       # 新年首个周线点 → 再平衡回 4:3:3
        _alloc = {_k: WEIGHTS[_k] * _val for _k in _alloc}
        _year = _t.year
    _prev = _cur
    _out.append(_val)
combined = pd.Series(_out, index=_grid)

# ── 5 条曲线图 ──
_COLORS = {
    "合成": "#F1C40F", "A": "#2ECC71", "B": "#3498DB",
    "C": "#E67E22", "SPY": "rgba(170,170,170,0.55)",
}
_LABELS = {
    "合成": "合成 (4:3:3, 年度再平衡)", "A": "A 回购稳定", "B": "B 板块轮动", "C": "C 回购进攻",
}
fig = go.Figure()
for _k in ["SPY", "A", "B", "C", "合成"]:
    if _k == "SPY":
        if spy_norm.empty:
            continue
        s = spy_norm
        name = f"SPY {(float(s.iloc[-1]) - 1) * 100:+.1f}%"
        line = dict(color=_COLORS["SPY"], width=1.5, dash="dot")
    else:
        s = combined if _k == "合成" else _norm[_k]
        name = f"{_LABELS[_k]} {(float(s.iloc[-1]) - 1) * 100:+.1f}%"
        line = dict(color=_COLORS[_k], width=3 if _k == "合成" else 1.6)
    fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=name, line=line))

fig.update_layout(
    title=f"ABC 组合净值 vs 各分策略 vs SPY · {_grid[0]:%Y-%m} → {_grid[-1]:%Y-%m}（起点归一 = 1）",
    xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
    yaxis=dict(
        title="NAV（对数，1.0 = 起始）", type="log",
        tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
        ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
        gridcolor="rgba(100,100,100,0.3)",
    ),
    height=520, margin=dict(l=10, r=10, t=44, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
    font=dict(color="#ccc", size=13), showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
)
st.plotly_chart(fig, use_container_width=True, key="combo_nav")

# ── 指标表 ──
def _metrics(nav: pd.Series) -> dict:
    nav = nav.astype(float).dropna()
    if len(nav) < 2:
        return {"总收益": float("nan"), "CAGR": float("nan"), "DD": float("nan"),
                "Calmar": float("nan"), "Sortino": float("nan"), "logR²": float("nan")}
    ret = (float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100
    peak = nav.cummax()
    dd = float(((peak - nav) / peak.replace(0, float("nan"))).max()) * 100
    kpi = hv.compute_nav_kpi(nav)
    cagr = kpi.get("cagr", float("nan"))
    return {
        "总收益": ret,
        "CAGR": cagr * 100 if cagr == cagr else float("nan"),
        "DD": -dd,
        "Calmar": kpi.get("calmar", float("nan")),
        "Sortino": kpi.get("sortino", float("nan")),
        "logR²": kpi.get("r2", float("nan")),
    }


_rows = []
_series_for_table = {
    "合成 (4:3:3)": combined, "A 回购稳定": _norm["A"], "B 板块轮动": _norm["B"],
    "C 回购进攻": _norm["C"], "SPY 大盘": spy_norm,
}
for _label, _s in _series_for_table.items():
    if _s is None or _s.empty:
        continue
    _m = _metrics(_s)
    _rows.append({"曲线": _label, **_m})

_df = pd.DataFrame(_rows).set_index("曲线")
st.markdown("### 📋 五条曲线指标（同一共同窗口）")
st.dataframe(
    _df.style.format({
        "总收益": "{:+.1f}%", "CAGR": "{:+.1f}%", "DD": "{:.1f}%",
        "Calmar": "{:.2f}", "Sortino": "{:.2f}", "logR²": "{:.2f}",
    }),
    use_container_width=True,
)
st.caption(
    "指标口径同各原页：周线 NAV，Calmar = CAGR/最大回撤，Sortino = CAGR/下行波动(√52 年化)，"
    "logR² = log(NAV) 对时间线性拟合优度（越接近 1 越像匀速复利、越平滑）。"
    "DD 为最大回撤（负值）。所有曲线裁到三条都有数据的共同窗口后再算，口径一致可比。"
)
