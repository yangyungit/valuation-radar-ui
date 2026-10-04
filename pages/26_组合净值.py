import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from api_client import (
    fetch_logr2_stable_pool,
    fetch_macro_radar_timeseries,
    fetch_dynasty_relay_selection_batch,
    fetch_dynasty_gold_leader,
    fetch_gbdt_oos_prices,
    get_global_data,
    fetch_factor_attribution,
)
import holdings_viz as hv
from factor_attrib_view import render_factor_attribution

st.set_page_config(page_title="组合净值", layout="wide")

# ── 组合口径（与原页保持同源）──
WINDOW = "10Y"                       # 三条统一 10Y
WEIGHTS = {"A": 0.4, "B": 0.3, "C": 0.3}  # 起始仓位 4:3:3，每年末再平衡回此比例

# A（FCF%单仓）口径，同 page 17 主版本
_FCFY_K = 2.0
_FCFY_LOGR2_GATE = 0.75
_FCFY_COST_BPS = 200.0

# B（板块王朝）口径，同 page 19 王朝接力净值实验台默认档
_DYNASTY_GROUPS = ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"]
_DYN_N = 2
_DYN_MOM = "504"
_DYN_SWEEP_HZ = ["3Y", "5Y", "10Y"]
_DYN_COST_BPS = 200.0

# C（精选龙头）口径，同 page 32 默认
_SL_MIN_HOLD = 9
_SL_COST_BPS = 10.0

st.title("📊 ABC 组合净值")
st.caption(
    f"**A = FCF%单仓**（带鱼池非科技子集，FCF收益率 Top1 满仓，守擂死区 k={_FCFY_K}，"
    f"候选需 logR²≥{_FCFY_LOGR2_GATE}，单边 200bps；同 page 17 主版本）· "
    "**B = 板块王朝**（C+D 组 ETF，504 日动量 king_score 接力，2 仓，buffer 守擂按 3Y/5Y/10Y maximin 自动定，"
    "差速器开，单边 200bps；同 page 19）· "
    f"**C = 精选龙头**（戴金龙头主线 + 最短持有 {_SL_MIN_HOLD} 月，月度再平衡，单边 10bps；同 page 32）· "
    f"三条均 {WINDOW}、周线。合成 = 起始 4:3:3、**每年末再平衡**回此比例。"
    "三条 + 合成 + SPY 统一裁到「三条都有数据」的共同窗口、起点归一为 1。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_macro_radar_timeseries.clear()
        fetch_dynasty_relay_selection_batch.clear()
        fetch_dynasty_gold_leader.clear()
        get_global_data.clear()
        fetch_factor_attribution.clear()
        st.rerun()


def _avg_slot_navs(navs: list) -> pd.Series:
    valid = [n for n in navs if not n.empty]
    if not valid:
        return pd.Series(dtype=float)
    uidx = valid[0].index
    for n in valid[1:]:
        uidx = uidx.union(n.index)
    return sum(n.reindex(uidx).ffill().bfill() for n in valid) / len(valid)


def _fcfy_stable_nav():
    """复刻 page 17「FCF%单仓」Top1 主版本：带鱼池非科技子集，FCF收益率池内排名 × logR² 门槛，
    守擂死区 k，月末决策次月执行，周线接力引擎扣单边 200bps。返回 (周线 NAV, SPY 周线 Close 帧)。"""
    doc = fetch_logr2_stable_pool()
    if not doc.get("success"):
        return pd.Series(dtype=float), pd.DataFrame()
    pools = {int(y): list(mem) for y, mem in (doc.get("pools") or {}).items()}
    meta = doc.get("meta") or {}
    fcfy_panel = doc.get("fcfy_panel") or {}
    logr2_panel = doc.get("logr2_panel") or {}
    if not pools or not fcfy_panel or not logr2_panel:
        return pd.Series(dtype=float), pd.DataFrame()

    union = sorted({t for mem in pools.values() for t in mem})
    rest = [t for t in union if not (meta.get(t) or {}).get("is_tech")]

    raw = pd.DataFrame({tk: pd.Series(fcfy_panel.get(tk) or {}, dtype=float) for tk in rest})
    raw.index = pd.to_datetime(raw.index)
    raw = raw.sort_index()
    grid = pd.date_range(raw.index.min(), pd.Timestamp.today(), freq="ME")
    score_m = raw.reindex(raw.index.union(grid)).ffill().reindex(grid)

    memb = pd.DataFrame(False, index=score_m.index, columns=score_m.columns)
    for y, mem in pools.items():
        memb.loc[memb.index.year == y, [t for t in mem if t in memb.columns]] = True
    logr2_m = pd.DataFrame({tk: pd.Series(logr2_panel.get(tk) or {}, dtype=float) for tk in rest})
    logr2_m.index = pd.to_datetime(logr2_m.index)
    logr2_m = logr2_m.sort_index().reindex(index=score_m.index, columns=score_m.columns)
    score_in = score_m.where(memb & (logr2_m >= _FCFY_LOGR2_GATE) & score_m.notna())

    _ALIAS = {"BRK.B": "BRK-B"}
    _px = get_global_data([_ALIAS.get(t, t) for t in rest] + ["SPY"], years=12)
    close_d = {}
    if _px is not None and not _px.empty:
        for t in rest:
            col = _ALIAS.get(t, t)
            if col in _px.columns and _px[col].notna().sum() >= 2:
                close_d[t] = _px[col].dropna()
    _missing = [t for t in rest if t not in close_d]
    if _missing:
        for t, rows_p in (fetch_gbdt_oos_prices(tuple(sorted(_missing))) or {}).items():
            if rows_p:
                arr = pd.DataFrame(rows_p, columns=["date", "o", "h", "l", "c", "v"])
                close_d[t] = arr.assign(date=pd.to_datetime(arr["date"])).set_index("date")["c"].astype(float)
    if not close_d:
        return pd.Series(dtype=float), pd.DataFrame()
    price_cache = {t: s.resample("W-FRI").last().dropna().to_frame(name="Close")
                   for t, s in close_d.items() if s.resample("W-FRI").last().dropna().shape[0] >= 2}
    spy_wk = pd.DataFrame()
    if _px is not None and "SPY" in _px.columns:
        spy_wk = _px["SPY"].dropna().resample("W-FRI").last().dropna().to_frame(name="Close")

    mh, prev = {}, []
    for d in score_in.index:
        row = score_in.loc[d]
        order = row.dropna().sort_values(ascending=False)
        if len(order) >= 1:
            thresh = float(order.iloc[0]) - _FCFY_K * float(row.std())
            keep = [t for t in prev if pd.notna(row.get(t)) and float(row[t]) >= thresh]
            hold = keep + [t for t in order.index if t not in keep][:1 - len(keep)]
        else:
            hold = []
        prev = hold
        mh[hv.next_month_key(d.strftime("%Y-%m"), 1)] = list(hold)
    m0 = hv.next_month_key((score_in.index[-1] - pd.DateOffset(years=int(WINDOW[:-1]))).strftime("%Y-%m"), 1)
    mh = {m: h for m, h in mh.items() if m >= m0}
    exec_months = sorted(mh)
    if not exec_months:
        return pd.Series(dtype=float), spy_wk
    slots = hv.build_basket_slot_assignments(mh, exec_months)
    seg = hv.build_slot_segments(slots, 0, exec_months)
    nav = hv.calc_slot_stats(seg, price_cache, spy_wk, hv.CASH_APY, _FCFY_COST_BPS)[2]
    return nav, spy_wk


def _dynasty_nav():
    """复刻 page 19 王朝接力净值实验台默认档：后端选仓，前端周线槽位净值等权合成；
    buffer_N 在 3Y/5Y/10Y 上按归一化总收益 maximin 选。返回 (周线 NAV, 错误信息)。"""
    dyn = fetch_macro_radar_timeseries(window=WINDOW, profile="dynasty")
    if not dyn.get("success"):
        return pd.Series(dtype=float), dyn.get("error", "未知错误")
    pool = sorted(tk for tk, p in (dyn.get("tickers", {}) or {}).items() if p.get("group", "") in _DYNASTY_GROUPS)
    if not pool:
        return pd.Series(dtype=float), "C/D 组无可用 ETF"
    pool_csv = ",".join(pool)
    price_cache, spy_wk = _weekly_cache(pool)
    if not price_cache:
        return pd.Series(dtype=float), "ETF 价格缺失"

    def _batch(hz, combos):
        resp = fetch_dynasty_relay_selection_batch(
            window=hz, tickers=pool_csv, mom_windows=_DYN_MOM,
            blend="borda", basis="king_score", gate="seniority", combos=combos,
        )
        return resp.get("results") or [] if resp.get("success") else []

    def _navc(mh, single=None):
        if not mh:
            return pd.Series(dtype=float)
        em = sorted(mh)
        sl = hv.build_basket_slot_assignments(mh, em)
        for m, t in (single or {}).items():
            if m in sl:
                sl[m] = [t] * len(sl[m])
        ns = max((len(v) for v in sl.values()), default=_DYN_N)
        return _avg_slot_navs([
            hv.calc_slot_stats(hv.build_slot_segments(sl, i, em), price_cache, spy_wk, hv.CASH_APY, _DYN_COST_BPS)[2]
            for i in range(ns)
        ])

    grid = list(range(_DYN_N, 11))
    combos = tuple(
        (("n_holdings", _DYN_N), ("guard", "buffer"), ("buffer_n", bn), ("k_delta", 1.0)) for bn in grid
    )
    cum = {bn: {} for bn in grid}
    for hz in _DYN_SWEEP_HZ:
        for r in _batch(hz, combos):
            bn = int(r["buffer_n"])
            nv = _navc(r.get("monthly_holdings") or {})
            if bn in cum and not nv.empty:
                cum[bn][hz] = float(nv.iloc[-1]) / float(nv.iloc[0]) - 1.0
    peak = {hz: max((cum[bn][hz] for bn in grid if hz in cum[bn]), default=float("nan")) for hz in _DYN_SWEEP_HZ}
    buf_n, best_key = max(4, _DYN_N), None
    for bn in grid:
        sc = [cum[bn][hz] / peak[hz] for hz in _DYN_SWEEP_HZ if hz in cum[bn] and peak[hz] > 0]
        if len(sc) < len(_DYN_SWEEP_HZ):
            continue
        key = (min(sc), -float(np.std(sc)))
        if best_key is None or key > best_key:
            best_key, buf_n = key, bn

    main = _batch(WINDOW, (
        (("n_holdings", _DYN_N), ("guard", "buffer"), ("buffer_n", buf_n), ("k_delta", 1.0), ("diff", True)),
    ))
    if not main:
        return pd.Series(dtype=float), "王朝选仓接口无返回"
    return _navc(main[0].get("monthly_holdings") or {}, main[0].get("single_months") or {}), None


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


def _combine_433(norm: dict, grid) -> pd.Series:
    """起始 4:3:3，跨年后首个点再平衡回此比例。"""
    alloc = dict(WEIGHTS)
    prev = {k: float(norm[k].iloc[0]) for k in WEIGHTS}
    out = [1.0]
    year = grid[0].year
    for t in grid[1:]:
        cur = {k: float(norm[k].loc[t]) for k in WEIGHTS}
        for k in alloc:
            alloc[k] *= cur[k] / prev[k] if prev[k] else 1.0
        val = sum(alloc.values())
        if t.year != year:
            alloc = {k: WEIGHTS[k] * val for k in alloc}
            year = t.year
        prev = cur
        out.append(val)
    return pd.Series(out, index=grid)


# ── A：FCF%单仓（同 page 17 Top1 主版本）──
with st.spinner("📊 加载 FCF%单仓 面板 + 价格..."):
    nav_a, spy_wk_a = _fcfy_stable_nav()

if nav_a.empty:
    st.warning("⚠️ FCF%单仓 净值不可用（A 曲线缺失，本地重跑 build_logr2_stable_pool.py 并上传后生效）")

# ── B：板块王朝（同 page 19 王朝接力净值实验台默认档）──
with st.spinner("📊 加载板块王朝选仓 + ETF 价格（守擂 3Y/5Y/10Y 寻优）..."):
    nav_b, _dyn_err = _dynasty_nav()
if _dyn_err:
    st.warning(f"⚠️ 板块王朝不可用：{_dyn_err}（B 曲线缺失）")

# ── C：精选龙头（同 page 32，后端回测净值）──
with st.spinner("📊 加载精选龙头回测..."):
    _gl = fetch_dynasty_gold_leader(window=WINDOW, rebalance=True, cost_bps=_SL_COST_BPS, min_hold=_SL_MIN_HOLD)

nav_c = pd.Series(dtype=float)
_sl_eq = (_gl.get("equity") or {}).get("two_sector_locked") or []
_sl_dates = _gl.get("dates") or []
if not _gl.get("success"):
    st.warning(f"⚠️ 精选龙头回测不可用：{_gl.get('error', '未知错误')}（C 曲线缺失）")
elif len(_sl_eq) != len(_sl_dates) or not _sl_eq:
    st.warning("⚠️ 后端未返回精选龙头净值（two_sector_locked），C 曲线缺失")
else:
    nav_c = (pd.Series(_sl_eq, index=pd.to_datetime(_sl_dates)).astype(float).dropna()
             .resample("W-FRI").last().dropna())

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
_spy_src = spy_wk_a if not spy_wk_a.empty else pd.DataFrame()
spy_norm = pd.Series(dtype=float)
if not _spy_src.empty:
    _sp = _spy_src["Close"].astype(float).reindex(_spy_src.index.union(_grid)).ffill().reindex(_grid).ffill().bfill()
    spy_norm = _sp / float(_sp.iloc[0])

# ── 合成：起始 4:3:3，每年末再平衡回此比例 ──
combined = _combine_433(_norm, _grid)

# ── 5 条曲线图 ──
_COLORS = {
    "合成": "#F1C40F", "A": "#2ECC71", "B": "#3498DB",
    "C": "#E67E22", "SPY": "rgba(170,170,170,0.55)",
}
_LABELS = {
    "合成": "合成 (4:3:3, 年度再平衡)", "A": "A FCF%单仓", "B": "B 板块王朝", "C": "C 精选龙头",
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
    "合成 (4:3:3)": combined, "A FCF%单仓": _norm["A"], "B 板块王朝": _norm["B"],
    "C 精选龙头": _norm["C"], "SPY 大盘": spy_norm,
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

# ── A/B/C（+SPY）周收益相关矩阵 ──
_ret_src = {"A FCF%单仓": _norm["A"], "B 板块王朝": _norm["B"], "C 精选龙头": _norm["C"]}
if not spy_norm.empty:
    _ret_src["SPY 大盘"] = spy_norm
_ret_df = pd.DataFrame(_ret_src).pct_change().dropna(how="any")
st.markdown("### 🔗 分策略周收益相关矩阵")
if len(_ret_df) < 8:
    st.warning("⚠️ 共同窗口内周收益样本不足，相关矩阵不可靠。")
else:
    _corr = _ret_df.corr()
    _hm = go.Figure(data=go.Heatmap(
        z=_corr.values, x=list(_corr.columns), y=list(_corr.index),
        zmin=-1, zmax=1, colorscale="RdBu_r", reversescale=False,
        text=[[f"{v:.2f}" for v in row] for row in _corr.values],
        texttemplate="%{text}", textfont=dict(size=15),
        colorbar=dict(title="ρ"),
    ))
    _hm.update_layout(
        height=380, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc", size=13),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(_hm, use_container_width=True, key="combo_corr")
    st.caption(
        "基于共同窗口的**周收益率**（非净值）皮尔逊相关。ρ 越接近 0 越分散、越接近 1 越同涨同跌、负值为对冲。"
        "三条全是美股 long-only，与 SPY 一列反映各自的市场 beta 相关，是系统性下跌里同跌的部分。"
    )

render_factor_attribution({
    "合成 (4:3:3)": combined, "A FCF%单仓": _norm["A"],
    "B 板块王朝": _norm["B"], "C 精选龙头": _norm["C"],
}, kp="combo")
