import streamlit as st
from contextlib import ExitStack
import numpy as np
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import (
    fetch_dynasty_double_dragon,
    fetch_dynasty_double_dragon_ma_exit_reentry,
    fetch_dynasty_double_dragon_momentum_periods,
    fetch_dynasty_double_dragon_walk_forward,
)
from double_dragon_ma_exit_reentry_viz import render_ma_exit_reentry_research
from double_dragon_momentum_period_viz import render_momentum_period_research
from double_dragon_research_viz import render_sp500_walk_forward_research

st.set_page_config(page_title="12M动量双龙", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
</style>
""", unsafe_allow_html=True)

_DYNASTY_TAB_WINDOWS = ["3Y", "5Y", "10Y"]
_D_THEME_TAB_WINDOWS = ["3Y", "5Y", "ALL"]
_POOL_TAB_LABELS = [
    "标普500选股池",
    "D组ETF历史成分池",
    "🧪 标普500无前视实验",
    "🧪 动量周期实验",
    "🧪 MA退出与再入实验",
]
_SLOT_LABELS = ["槽A", "槽B", "槽C", "槽D", "槽E"]
_DD_MOMENTUM_STRATEGY = "sp500_12m_ma200_k_guard"
_DD_DELTA_STRATEGY = "sp500_12m_ma200_delta_guard"
def _norm_series(values, dates) -> pd.Series:
    if not values or len(values) != len(dates):
        return pd.Series(dtype=float)
    s = pd.Series(values, index=dates).astype(float).dropna()
    return s


def _holding_label(cell: dict | None) -> str:
    if not cell:
        return "—"
    if cell.get("bil"):
        return "BIL"
    return str(cell.get("ticker", "—") or "—")


def _slot_month_segments(timeline: list[dict], slot_i: int) -> list[tuple]:
    """把某个槽的月度持仓压成 [(ticker_or_CASH, 起始月, 结束月), ...]，BIL/空档折成 CASH，
    喂给 holdings_viz.build_stitched_fig（与 10_科技龙头 同一套接力段渲染）。"""
    segs: list[tuple] = []
    prev = None
    s_m = None
    last_m = None
    for h in timeline:
        month = str(h.get("month", ""))
        if not month:
            continue
        slots = h.get("slots", [])
        cell = slots[slot_i] if slot_i < len(slots) else None
        lab = _holding_label(cell)
        lab = "CASH" if lab in ("BIL", "—") else lab
        if lab != prev:
            if prev is not None:
                segs.append((prev, s_m, last_m))
            prev = lab
            s_m = month
        last_m = month
    if prev is not None:
        segs.append((prev, s_m, last_m))
    return segs


def render_slot_segment_returns(dd: dict, key_prefix: str = "dd") -> bool:
    slot_equity = dd.get("slot_equity") or []
    timeline = dd.get("holdings_timeline") or []
    dates = pd.to_datetime(dd.get("dates", []), errors="coerce")
    if not slot_equity or not timeline or len(dates) == 0:
        return False

    # 时间窗口：拖动后裁到窗口内的段，build_stitched_fig 会把窗口最左端归一为 1、
    # SPY 同样从窗口起点对齐；y 轴对数自适应。方便看清早期段（如 2018 单票 -64% 回撤）。
    _valid = dates.dropna()
    win_lo, win_hi = _valid.min(), _valid.max()
    if pd.notna(win_lo) and pd.notna(win_hi) and win_lo < win_hi:
        _lo_py, _hi_py = win_lo.to_pydatetime(), win_hi.to_pydatetime()
        # key 绑定数据实际起止：切 3Y/5Y/10Y 后 dates 变了，slider 换新 key 重置为满窗口。
        # 否则 Streamlit 会保留上一个窗口的选值（如 5Y 起点），10Y 也只画 5Y。
        _sel = st.slider(
            "分段图时间窗口（拖动重设起点，各段与 SPY 在窗口最左端对齐归一）",
            min_value=_lo_py, max_value=_hi_py, value=(_lo_py, _hi_py),
            format="YYYY-MM",
            key=f"{key_prefix}_slot_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
        )
        win_lo, win_hi = pd.Timestamp(_sel[0]), pd.Timestamp(_sel[1])
    lo_m, hi_m = win_lo.strftime("%Y-%m"), win_hi.strftime("%Y-%m")

    spy = _norm_series((dd.get("equity") or {}).get("spy", []), dates)
    spy = spy[(spy.index >= win_lo) & (spy.index <= win_hi)]
    spy_wk = pd.DataFrame({"Close": spy}) if not spy.empty else pd.DataFrame()

    for slot_row in slot_equity:
        slot_i = int(slot_row.get("slot", 0))
        slot_name = _SLOT_LABELS[slot_i] if slot_i < len(_SLOT_LABELS) else f"槽{slot_i + 1}"
        slot_s = _norm_series(slot_row.get("equity", []), dates)
        slot_s = slot_s[(slot_s.index >= win_lo) & (slot_s.index <= win_hi)]
        if slot_s.empty:
            continue
        segs = _slot_month_segments(timeline, slot_i)
        # 只留与窗口月份有交集的段；build_stitched_fig 按窗口内实际数据把首点归一为 1。
        segs = [s for s in segs if not (s[2] < lo_m or s[1] > hi_m)]
        if not segs:
            continue
        # 槽净值本身就是该槽持仓的连续净值，按段切片即得每段真实涨跌，无需逐票拉价。
        price_cache = {tk: pd.DataFrame({"Close": slot_s}) for tk, _, _ in segs if tk != "CASH"}
        fig = hv.build_stitched_fig(
            segs, f"{slot_name}接力 持仓段", spy_wk, price_cache, {}, {},
        )
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_slot_segment_{slot_i}")
    return True


# ══════════════════════════════════════════════════════════════════════
# 【本地实验】抗回撤对照台（纯前端在 slot_equity 上模拟，不改后端口径）
# 三类对照组：
#   · 我最初的通用做法：持有段「净值峰值回撤%」止损 → 现金 → 下月首日重进（_stop_on_base）
#   · 系统现成机制①MA4留任：在任票月末价 > 自己4月均线才留，跌破换现金（_ma4_on_base，抄 render_group.retention_mask）
#   · 系统现成机制②exec_rule 回撤止损：距持有段高点回撤>阈值出场，日线收盘站回 MA{reentry} 上方才买回（_execdd_on_base）
# 组合净值 = 各槽在展示窗起点真实权重加权和；slot_equity 被后端各自归一到 1.0 丢了起点权重，
#            用最小二乘从后端组合净值反解 wᵢ（关掉风控时与后端逐点对齐）。逻辑集中，好迭代。
# ══════════════════════════════════════════════════════════════════════
def _dd_holding_label_for_stop(cell: dict | None) -> str:
    if not cell or cell.get("bil"):
        return "CASH"
    return str(cell.get("ticker") or "CASH")


def _dd_reconstruct(dd: dict):
    """重建可复用基座：每槽归一净值、逐日持仓标签、组合权重、后端组合净值。缺数据返回 None。"""
    dates = pd.to_datetime(dd.get("dates", []), errors="coerce")
    slot_equity = dd.get("slot_equity") or []
    timeline = dd.get("holdings_timeline") or []
    n = len(dates)
    if n < 30 or not slot_equity or not timeline:
        return None
    day_ym = [d.strftime("%Y-%m") if pd.notna(d) else "" for d in dates]

    orig_slots: list[pd.Series] = []
    labels: list[list[str]] = []
    for slot_row in slot_equity:
        slot_i = int(slot_row.get("slot", 0))
        s = pd.Series(slot_row.get("equity", []), index=dates).astype(float)
        if s.dropna().empty:
            continue
        s = s.ffill().bfill()
        mlab: dict[str, str] = {}
        for h in timeline:
            m = str(h.get("month", ""))
            slots = h.get("slots", [])
            cell = slots[slot_i] if slot_i < len(slots) else None
            if m:
                mlab[m] = _dd_holding_label_for_stop(cell)
        sorted_m = sorted(mlab)
        labs: list[str] = []
        for ym in day_ym:
            if ym in mlab:
                labs.append(mlab[ym])
            else:
                prior = [m for m in sorted_m if m <= ym]
                labs.append(mlab[prior[-1]] if prior else "CASH")
        orig_slots.append(s / float(s.iloc[0]))
        labels.append(labs)

    if not orig_slots:
        return None
    _sel = (dd.get("meta", {}) or {}).get("selection_strategy", "")
    _key = "momentum_delta_guard" if _sel == _DD_DELTA_STRATEGY else "momentum_k_guard"
    bk = pd.Series((dd.get("equity", {}) or {}).get(_key, []), index=dates).astype(float)
    _S = np.column_stack([s.values for s in orig_slots])
    if not bk.dropna().empty:
        _w, _, _, _ = np.linalg.lstsq(_S, bk.values, rcond=None)
    else:
        _w = np.full(_S.shape[1], 1.0 / _S.shape[1])
    return {"dates": dates, "day_ym": day_ym, "orig_slots": orig_slots,
            "labels": labels, "weights": _w, "backend": bk}


def _dd_combine(base: dict, slot_navs: list[pd.Series]) -> pd.Series:
    _S = np.column_stack([x.reindex(base["dates"]).astype(float).values for x in slot_navs])
    return pd.Series(_S @ base["weights"], index=base["dates"])


def _dd_orig_port(base: dict) -> pd.Series:
    return _dd_combine(base, base["orig_slots"])


def _stop_on_base(base: dict, stop_pct: float, cash_annual: float = 0.04) -> pd.Series:
    """我最初的通用做法：每槽自净值峰值回撤达阈值→止损转现金，下月首日按当月持仓重进。"""
    dates = base["dates"]
    n = len(dates)
    cash_daily = (1.0 + cash_annual) ** (1.0 / 252.0) - 1.0
    out: list[pd.Series] = []
    for si in range(len(base["orig_slots"])):
        s = base["orig_slots"][si]
        labs = base["labels"][si]
        r = s.pct_change().fillna(0.0).values
        nav = 1.0
        navs = []
        pos_val = 1.0
        pos_peak = 1.0
        stopped = False
        prev_label = None
        prev_ym = None
        for t in range(n):
            lab = labs[t]
            ym = base["day_ym"][t]
            if prev_ym is not None and ym != prev_ym and stopped:
                stopped = False
                pos_val = 1.0
                pos_peak = 1.0
            if lab != prev_label:
                pos_val = 1.0
                pos_peak = 1.0
                stopped = False
            rt = float(r[t])
            if stopped:
                eff_r = cash_daily
            else:
                eff_r = rt
                if lab != "CASH":
                    pos_val *= (1.0 + rt)
                    pos_peak = max(pos_peak, pos_val)
                    if pos_peak > 0 and (pos_val / pos_peak - 1.0) <= -abs(stop_pct):
                        stopped = True
            nav *= (1.0 + eff_r)
            navs.append(nav)
            prev_label = lab
            prev_ym = ym
        out.append(pd.Series(navs, index=dates))
    return _dd_combine(base, out)


def _dd_fetch_held_prices(dd: dict) -> dict:
    """取 holdings_timeline 里全部持仓票的 Sharadar 日线 close（供 MA4/exec 规则算均线）。"""
    tks: set[str] = set()
    for h in dd.get("holdings_timeline") or []:
        for cell in h.get("slots") or []:
            lab = _dd_holding_label_for_stop(cell)
            if lab != "CASH":
                tks.add(lab)
    out: dict[str, pd.Series] = {}
    if not tks:
        return out
    try:
        from api_client import fetch_gbdt_oos_prices
        hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(tks))))
    except Exception:
        pass
    for tk in tks:
        try:
            d = hv.fetch_daily_ohlcv(tk)
            if d is not None and not d.empty:
                c = d["Close"].astype(float).dropna()
                if c.index.tz is not None:
                    c.index = c.index.tz_localize(None)
                out[tk] = c
        except Exception:
            pass
    return out


def _ma4_on_base(base: dict, held: dict, ma_months: int = 4, cash_annual: float = 0.04) -> pd.Series:
    """系统机制①MA4留任（抄 render_group.retention_mask）：在任票月末价 > 自己4月均线才留，
    跌破换现金；用上月末信号去前视。缺该票日线时默认留任。"""
    dates = base["dates"]
    n = len(dates)
    cash_daily = (1.0 + cash_annual) ** (1.0 / 252.0) - 1.0
    ret_ok: dict[str, dict] = {}
    for tk, c in held.items():
        mc = c.resample("ME").last().dropna()
        ok = (mc > mc.rolling(ma_months).mean()).shift(1)
        ret_ok[tk] = {ts.strftime("%Y-%m"): (bool(v) if pd.notna(v) else True) for ts, v in ok.items()}
    out: list[pd.Series] = []
    for si in range(len(base["orig_slots"])):
        s = base["orig_slots"][si]
        labs = base["labels"][si]
        r = s.pct_change().fillna(0.0).values
        nav = 1.0
        navs = []
        for t in range(n):
            lab = labs[t]
            if lab == "CASH":
                eff_r = float(r[t])
            else:
                ok = ret_ok.get(lab, {}).get(base["day_ym"][t], True)
                eff_r = float(r[t]) if ok else cash_daily
            nav *= (1.0 + eff_r)
            navs.append(nav)
        out.append(pd.Series(navs, index=dates))
    return _dd_combine(base, out)


def _execdd_on_base(base: dict, held: dict, stop_pct: float,
                    reentry_ma: int = 100, cash_annual: float = 0.04) -> pd.Series:
    """系统机制②exec_rule 回撤止损：距持有段高点(个股价)回撤>阈值出场，
    日线收盘站回自身 MA{reentry_ma} 上方才买回。缺该票日线时不做止损。"""
    dates = base["dates"]
    n = len(dates)
    cash_daily = (1.0 + cash_annual) ** (1.0 / 252.0) - 1.0
    px: dict[str, np.ndarray] = {}
    ma: dict[str, np.ndarray] = {}
    for tk, c in held.items():
        cc = c.reindex(dates, method="ffill")
        px[tk] = cc.values
        ma[tk] = cc.rolling(reentry_ma, min_periods=reentry_ma).mean().values
    out: list[pd.Series] = []
    for si in range(len(base["orig_slots"])):
        s = base["orig_slots"][si]
        labs = base["labels"][si]
        r = s.pct_change().fillna(0.0).values
        nav = 1.0
        navs = []
        stopped = False
        peak = None
        prev_label = None
        for t in range(n):
            lab = labs[t]
            if lab != prev_label:
                stopped = False
                peak = None
            arr = px.get(lab)
            if lab == "CASH" or arr is None:
                eff_r = float(r[t])
            else:
                c_t = arr[t]
                m_t = ma[lab][t]
                if stopped:
                    eff_r = cash_daily
                    if pd.notna(c_t) and pd.notna(m_t) and c_t > m_t:
                        stopped = False
                        peak = c_t
                else:
                    eff_r = float(r[t])
                    if pd.notna(c_t):
                        peak = c_t if peak is None else max(peak, c_t)
                        if peak > 0 and (c_t / peak - 1.0) <= -abs(stop_pct):
                            stopped = True
            nav *= (1.0 + eff_r)
            navs.append(nav)
            prev_label = lab
        out.append(pd.Series(navs, index=dates))
    return _dd_combine(base, out)


def _curve_stats(nav: pd.Series) -> dict:
    nav = nav.astype(float).dropna()
    if len(nav) < 2:
        return {"cum": 0.0, "cagr": 0.0, "max_dd": 0.0, "calmar": 0.0}
    yrs = max((nav.index[-1] - nav.index[0]).days / 365.25, 1e-9)
    cum = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / yrs) - 1.0)
    dd_series = nav / nav.cummax() - 1.0
    max_dd = float(dd_series.min())
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    return {"cum": cum, "cagr": cagr, "max_dd": max_dd, "calmar": calmar}


def _spy_ma200_risk_off(dd: dict, dates: pd.DatetimeIndex, ma_win: int = 200):
    """SPY 收盘 < 自身 MA200 → risk-off。优先用全历史 Sharadar 日线(窗口起点即有信号)，
    失败回退 payload 内 spy(窗口内近似，前 ma_win 日无信号)。返回已 shift(1) 去前视的布尔序列。"""
    _close = None
    try:
        from api_client import fetch_gbdt_oos_prices
        hv.prime_sharadar_prices(fetch_gbdt_oos_prices(("SPY",)))
        _spy_d = hv.fetch_daily_ohlcv("SPY")
        if _spy_d is not None and not _spy_d.empty:
            _close = _spy_d["Close"].astype(float).dropna()
            if _close.index.tz is not None:
                _close.index = _close.index.tz_localize(None)
    except Exception:
        _close = None
    if _close is None or _close.empty:
        _close = pd.Series((dd.get("equity", {}) or {}).get("spy", []), index=dates).astype(float).dropna()
    if _close.empty:
        return pd.Series(False, index=dates), False
    _ma = _close.rolling(ma_win, min_periods=ma_win).mean()
    _ro = (_close < _ma)
    _ro = _ro.reindex(dates, method="ffill").fillna(False).astype(bool)
    _ro = _ro.shift(1).fillna(False).astype(bool)
    return _ro, True


def _chaos_risk_off(dates: pd.DatetimeIndex, fwd_days: int = 20):
    """日频 chaos 闸门：GBDT horsemen_daily_chaos_trigger 触发日 + 后 fwd_days 交易日 → risk-off。
    与「10_科技龙头」清仓信号同源。返回布尔序列 + 是否取到信号。"""
    try:
        from api_client import compute_macro_regime_api
        _cr = compute_macro_regime_api(z_window=750) or {}
        _trig = _cr.get("horsemen_daily_chaos_trigger", {}) or {}
        _td = pd.to_datetime([k for k, v in _trig.items() if v], errors="coerce").dropna()
        _cal = pd.DatetimeIndex(dates)
        _ro = pd.Series(False, index=dates)
        for _t in _td:
            _pos = int(_cal.searchsorted(_t))
            if _pos < len(_cal):
                _ro.iloc[_pos:_pos + fwd_days + 1] = True
        return _ro.astype(bool), bool(len(_td) > 0)
    except Exception:
        return pd.Series(False, index=dates), False


def _apply_regime(nav: pd.Series, risk_off: pd.Series, mode: str = "清仓", cash_annual: float = 0.04) -> pd.Series:
    """把组合日收益在 risk-off 日替换为现金(清仓)或半仓(减半)，重建净值。"""
    nav = nav.astype(float)
    cash_daily = (1.0 + cash_annual) ** (1.0 / 252.0) - 1.0
    _r = nav.pct_change().fillna(0.0)
    _ro = risk_off.reindex(nav.index).fillna(False).astype(bool)
    if mode == "减半":
        _eff = _r.where(~_ro, 0.5 * _r + 0.5 * cash_daily)
    else:
        _eff = _r.where(~_ro, cash_daily)
    return (1.0 + _eff).cumprod() * float(nav.iloc[0])


def render_dd_stop_tab(dd: dict, strategy_title: str, key_prefix: str = "dd") -> None:
    st.caption(
        f"在**{strategy_title}**的每槽净值上模拟「持有段回撤止损」，纯前端估算，不改后端口径。"
        "规则：某槽从进场起算，净值较自身峰值回撤达阈值即当日止损转现金(年化4%)，"
        "持现金到下月首个交易日再按当月持仓重进；换名也重置峰值。"
    )
    _c1, _c2, _c3 = st.columns([1.2, 1.0, 1.4])
    with _c1:
        _stop = st.slider(
            "回撤止损阈值", 5, 40, 20, step=1, format="%d%%",
            key=f"{key_prefix}_stop_pct",
            help="方向1：某槽自峰值回撤达此值即止损。越小越早离场但可能错杀反弹。",
        ) / 100.0
    with _c2:
        _mode = st.selectbox(
            "择时降仓方式", ["清仓", "减半"], index=0,
            key=f"{key_prefix}_regime_mode",
            help="方向2：risk-off 日整体转现金(清仓)或半仓半现金(减半)。",
        )
    with _c3:
        _use_chaos = st.checkbox(
            "叠加日频 chaos 闸门（较慢，需拉宏观 regime）",
            value=False, key=f"{key_prefix}_use_chaos",
            help="GBDT 日频崩盘信号触发后 20 交易日清仓，与「科技龙头」同源。",
        )

    _use_sys = st.checkbox(
        "叠加系统现成机制对照：MA4留任 / exec_rule 回撤止损（需拉持仓票日线）",
        value=True, key=f"{key_prefix}_use_sys",
        help="MA4留任=在任票跌破自己4月线换现金(抄 render_group.retention_mask)；"
             "exec回撤止损=距高点回撤>阈值出场、收盘站回日线MA100 才买回。",
    )

    _base = _dd_reconstruct(dd)
    if _base is None:
        st.info("后端未返回 slot_equity 或数据不足，无法模拟。")
        return
    _dts = _base["dates"]
    _orig = _dd_orig_port(_base)
    _stopped = _stop_on_base(_base, _stop)
    _sanity = (
        float((_orig - _base["backend"]).abs().max())
        if not _base["backend"].dropna().empty else float("nan")
    )

    _spy = pd.Series((dd.get("equity", {}) or {}).get("spy", []), index=_dts).astype(float)
    if not _spy.dropna().empty:
        _spy = _spy / float(_spy.dropna().iloc[0])

    _ro_ma, _ma_ok = _spy_ma200_risk_off(dd, _dts)
    _regime_ma = _apply_regime(_orig, _ro_ma, _mode)
    _ro_chaos = None
    _regime_chaos = None
    if _use_chaos:
        with st.spinner("拉取宏观 regime（日频 chaos 闸门）..."):
            _ro_chaos, _chaos_ok = _chaos_risk_off(_dts)
        if _chaos_ok:
            _regime_chaos = _apply_regime(_orig, _ro_chaos, _mode)

    _ma4_port = None
    _execdd_port = None
    if _use_sys:
        with st.spinner("拉取持仓票日线（MA4留任 / exec 回撤止损）..."):
            _held = _dd_fetch_held_prices(dd)
        if _held:
            _ma4_port = _ma4_on_base(_base, _held)
            _execdd_port = _execdd_on_base(_base, _held, _stop)

    _series = [
        ("原版(无风控)", _orig, "#F39C12", 2),
        (f"我的做法 峰值止损 -{int(_stop*100)}%", _stopped, "#2ECC71", 2),
        (f"方向2 SPY<MA200 {_mode}", _regime_ma, "#E74C3C", 2),
    ]
    if _regime_chaos is not None:
        _series.append((f"方向2 chaos闸门 {_mode}", _regime_chaos, "#F1C40F", 2))
    if _ma4_port is not None:
        _series.append(("系统 MA4留任", _ma4_port, "#1ABC9C", 2))
    if _execdd_port is not None:
        _series.append((f"系统 exec止损 -{int(_stop*100)}%/MA100买回", _execdd_port, "#9B59B6", 2))
    if not _spy.dropna().empty:
        _series.append(("SPY", _spy, "#3498DB", 1.4))

    _fig = go.Figure()
    for _nm, _s, _col, _w in _series:
        _sv = _s.astype(float).dropna()
        if _sv.empty:
            continue
        _fig.add_trace(go.Scatter(x=_sv.index, y=_sv.values, name=_nm, line=dict(color=_col, width=_w)))
    _fig.update_layout(
        height=420, hovermode="x unified", template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.12),
        yaxis_title="净值（对数）", yaxis_type="log",
    )
    st.plotly_chart(_fig, use_container_width=True, key=f"{key_prefix}_stop_curve")

    # 统计对照表
    _table_rows = [("原版(无风控)", _orig),
                   (f"我的做法 峰值止损 -{int(_stop*100)}%", _stopped),
                   ("方向2 SPY<MA200", _regime_ma)]
    if _regime_chaos is not None:
        _table_rows.append(("方向2 chaos闸门", _regime_chaos))
    if _ma4_port is not None:
        _table_rows.append(("系统 MA4留任", _ma4_port))
    if _execdd_port is not None:
        _table_rows.append(("系统 exec回撤止损", _execdd_port))
    _recs = []
    for _nm, _s in _table_rows:
        _cs = _curve_stats(_s)
        _recs.append({
            "组合": _nm,
            "最大回撤": f"{_cs['max_dd']*100:.0f}%",
            "累计收益": f"{_cs['cum']*100:.0f}%",
            "年化收益": f"{_cs['cagr']*100:.1f}%",
            "收益回撤比": f"{_cs['calmar']:.2f}",
        })
    st.table(pd.DataFrame(_recs).set_index("组合"))

    _dd_dt = _orig / _orig.cummax() - 1.0
    _trough = _dd_dt.idxmin()
    _peak = _orig[:_trough].idxmax() if pd.notna(_trough) else None
    if _peak is not None and pd.notna(_trough):
        _span = int(list(_dts).index(_trough) - list(_dts).index(_peak))
        st.caption(
            f"原版最大回撤 {_dd_dt.min()*100:.0f}%，发生在 {_peak.date()}→{_trough.date()}"
            f"（峰谷仅 {_span} 交易日）。回撤越快，慢均线越接不住，日频 chaos 闸门才可能有效。"
        )
    st.caption(
        f"SPY<MA200 的 risk-off 天数占比 {_ro_ma.mean()*100:.0f}%"
        + (f" · chaos 闸门 risk-off 占比 {_ro_chaos.mean()*100:.0f}%" if _ro_chaos is not None else "")
    )
    if _sanity == _sanity:
        st.caption(f"自检：重建原版组合 vs 后端净值最大绝对偏差 {_sanity:.4f}（越接近0越可信）。")
    if _ma4_port is not None:
        st.caption(
            "结论：MA4留任 / exec回撤止损（抄 relay 家族现成机制）在本策略上**回撤更深、收益更差**——"
            "Top2 持的是超高波动动量票，跌破均线时已砸 20%+ 才割，站回均线才买回=接在反弹高位，来回打脸。"
            "急跌用均线类信号救不了，只有方向2（整本账按 SPY<MA200 / chaos 日频降仓）才有戏。"
        )
    st.caption(
        "⚠️ 纯前端 what-if：止损未扣换仓成本、重进用「下月」近似；择时按当日信号次日执行(已去前视)。"
        "只作方向判断，落地需在后端 `_dd_run` 实现并按 "
        + ("3Y/5Y/全历史" if "dtheme" in key_prefix else "3Y/5Y/10Y")
        + " 三段验证。"
    )


with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_double_dragon.clear()
        fetch_dynasty_double_dragon_ma_exit_reentry.clear()
        fetch_dynasty_double_dragon_walk_forward.clear()
        fetch_dynasty_double_dragon_momentum_periods.clear()
        st.rerun()

st.title("📈 12M动量双龙 (Momentum Guard)")
# 必须启用 rerun 才会把当前活动标签写入 Session State；否则前端虽然能切换
# 标签，Python 端仍一直按默认标签渲染，第二个标签就会呈现为空白。
_pool_tabs = st.tabs(_POOL_TAB_LABELS, key="dd_pool_tab", on_change="rerun")
_active_pool_label = st.session_state.get("dd_pool_tab", _POOL_TAB_LABELS[0])
if _active_pool_label not in _POOL_TAB_LABELS:
    _active_pool_label = _POOL_TAB_LABELS[0]
_active_pool_idx = _POOL_TAB_LABELS.index(_active_pool_label)
_active_tab_stack = ExitStack()
_active_tab_stack.enter_context(_pool_tabs[_active_pool_idx])

if _active_pool_idx == 2:
    render_sp500_walk_forward_research()
    _active_tab_stack.close()
    st.stop()

if _active_pool_idx == 3:
    render_momentum_period_research()
    _active_tab_stack.close()
    st.stop()

if _active_pool_idx == 4:
    render_ma_exit_reentry_research()
    _active_tab_stack.close()
    st.stop()

_pool_mode = "d_theme_pit" if _active_pool_idx == 1 else "sp500_pit"
_is_d_theme = _pool_mode == "d_theme_pit"
_key_prefix = "dd_dtheme" if _is_d_theme else "dd_sp500"
_window_options = _D_THEME_TAB_WINDOWS if _is_d_theme else _DYNASTY_TAB_WINDOWS
if _is_d_theme:
    st.caption(
        "D组14只ETF历史Top15成分 · 12M动量K守擂 · 12M动量防抖守擂。"
        "标普500成员资格既不加分，也不构成排除条件。"
    )
else:
    st.caption(
        "标普500动量K守擂 · 标普500动量防抖守擂 · 两策略对照。"
        "戴金龙头已拆到「🏅 戴金龙头」单独一页。"
        "当前自动K为完整窗口样本内最佳，仅作参考；严格无前视结果见实验Tab。"
    )

_dynasty_window = st.radio(
    "时间跨度",
    options=_window_options,
    index=_window_options.index("5Y"),
    horizontal=True,
    key=f"{_key_prefix}_window",
    format_func=lambda value: "全历史" if value == "ALL" else value,
    help=(
        "月末快照：3年/5年/全历史；全历史从14只ETF首次完整公开覆盖开始"
        if _is_d_theme else
        "月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子"
    ),
)

st.markdown("#### 📈 12M动量双龙持仓 — 两策略对照")
if _is_d_theme:
    st.caption(
        "**主线A**：当时已公开的D组ETF历史成分池 → 12M动量 + MA200 → TopN/K守擂 → 下月执行。"
        "**主线B**：同一候选池 → TopN/分差δ防抖守擂 → 下月执行。"
        "**真实数据口径**：SEC N-PORT公开后下一交易日才可用；先筛美国交易所普通股/ADR，"
        "再取每只ETF权重Top15并去重；快照超过120天或任一ETF缺失则整月不可用。"
    )
else:
    st.caption(
        "**主线A**：逐月真实标普500股票池 → 12M 动量 + MA200 → TopN/K 守擂 → 下月执行。"
        "**主线B**：同一套 12M 动量候选池 → TopN/分差 δ 防抖守擂 → 下月执行。"
        "**诚实声明**：信号**不看未来**、可执行规则模拟；股票池=**逐月真实标普500成分**"
        "（PIT，Sharadar 数据含当年被剔除/退市/收购的公司），**已去生存者偏差**。"
    )

_strategy_options = {
    "12M动量K守擂": "sp500_12m_ma200_k_guard",
    "12M动量防抖守擂": _DD_DELTA_STRATEGY,
}
_dd_risk = True
_dd_strategy_label = st.radio(
    "当前查看策略",
    list(_strategy_options.keys()),
    index=0,
    horizontal=True,
    key=f"{_key_prefix}_strategy",
    help="决定当前持仓卡、统计卡、Slot分段收益和时间带展示哪条策略；组合收益图保留两条策略曲线作参考。",
)
_dd_signal = _strategy_options[_dd_strategy_label]

_legacy_n_key = f"{_key_prefix}_legacy_n"
_dd_legacy_n = int(st.session_state.get(_legacy_n_key, 2) or 2)
_dd_rebal = False
_dd_k = 0
_dd_delta_k = -1.0
_dd_k_display = None
_dd_delta_display = None

st.markdown("##### 12M动量守擂设置")
_mom_c1, _mom_c2 = st.columns([1.1, 1.2])
with _mom_c1:
    _dd_legacy_n = st.selectbox(
        "持仓数量 TopN",
        [1, 2, 3, 4, 5],
        index=[1, 2, 3, 4, 5].index(_dd_legacy_n) if _dd_legacy_n in [1, 2, 3, 4, 5] else 1,
        key=_legacy_n_key,
        help="作用于两条 12M 动量守擂策略。",
    )
with _mom_c2:
    if _dd_signal == _DD_MOMENTUM_STRATEGY:
        _dd_k_display = st.empty()
        _dd_k_display.caption("自动守擂K：加载后显示")
    else:
        _dd_delta_display = st.empty()
        _dd_delta_display.caption("自动防抖强度：加载后显示")
if _dd_signal == _DD_MOMENTUM_STRATEGY:
    st.caption(
        "固定不再平衡：每个槽位独立复利，持仓仍在前 K 就留任，跌出前 K 才换；"
        "不做月度等权拉回，避免额外卖强买弱和模糊守擂语义。"
    )
else:
    st.caption(
        "固定不再平衡：每个槽位独立复利；在任票只要 12M 动量分数距 TopN 门槛在 δ 内就留任。"
        "δ = kδ × 当月横截面 12M 动量标准差，用来减少排名挤动造成的无意义换仓，不承诺收益更高。"
    )

with st.expander("交易假设（作用于两条策略）"):
    _dd_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key=f"{_key_prefix}_cost",
        help="买/卖各算一次，扣在成交名义额上；会影响两条策略的回测净值和统计。",
    )

_dd = fetch_dynasty_double_dragon(
    window=_dynasty_window, signal=_dd_signal, k=_dd_k, delta_k=_dd_delta_k,
    risk_protect=_dd_risk, rebalance=_dd_rebal, cost_bps=float(_dd_cost),
    n_holdings=int(_dd_legacy_n), pool_mode=_pool_mode,
)

if not _dd.get("success"):
    if _dd_k_display is not None:
        _dd_k_display.metric("自动守擂K", "—")
    if _dd_delta_display is not None:
        _dd_delta_display.metric("自动防抖强度", "—")
    st.warning(f"⚠️ 12M动量双龙回测暂不可用：{_dd.get('error', '未知错误')}")

if _dd.get("success"):
    _meta = _dd.get("meta", {})
    _legacy_params = _meta.get("legacy_params", {}) or {}
    _delta_params = _meta.get("delta_params", {}) or {}
    _legacy_n_val = int(_legacy_params.get("n_holdings", _dd_legacy_n))
    _legacy_k_raw = _legacy_params.get("k", None)
    _legacy_k_val = int(_legacy_k_raw) if isinstance(_legacy_k_raw, (int, float)) else None
    _legacy_k_txt = f"K{_legacy_k_val}" if _legacy_k_val is not None else "K自动"
    _legacy_k_mode = str(_legacy_params.get("k_mode", "manual") or "manual")
    _delta_k_raw = _delta_params.get("delta_k", None)
    _delta_k_val = float(_delta_k_raw) if isinstance(_delta_k_raw, (int, float)) else None
    _delta_k_txt = f"kδ={_delta_k_val:.2f}" if _delta_k_val is not None else "kδ自动"
    _delta_k_mode = str(_delta_params.get("delta_mode", "manual") or "manual")
    if _dd_k_display is not None:
        _dd_k_display.metric("自动守擂K", _legacy_k_txt)
    if _dd_delta_display is not None:
        _dd_delta_display.metric("自动防抖强度", _delta_k_txt)

    _notes = []
    if _meta.get("pit_membership_gated"):
        _notes.append(
            "已按SEC公开日使用D14历史成分（PIT，含退市）"
            if _is_d_theme else
            "已按逐月真实成分选股（PIT，含退市，去生存者偏差）"
        )
    if not _meta.get("bil_available"):
        _notes.append("BIL 历史缺失，BIL 持有段按现金 0 收益")
    if not _meta.get("rsp_available"):
        _notes.append("RSP 缺失，未画等权标普对照")
    _pool_size = _meta.get("pool_size", _meta.get("universe_size", "?"))
    st.caption(
        f"当前池 {_pool_size} 只 · 历史并集 {_meta.get('universe_size', '?')} 只"
        f" · 展示自 {_meta.get('display_start', '')}"
        f" · 价格截至 {_meta.get('price_as_of', '')} · "
        + ("⚠️ " + "；".join(_notes) if _notes else "数据完整")
    )
    if _is_d_theme:
        _covered = _meta.get("covered_etfs") or []
        st.caption(
            f"N-PORT覆盖 {_meta.get('coverage_start', '—')} 至今 · "
            f"当前公开持仓报告截至 {_meta.get('holdings_report_asof', '—')} · "
            f"公开可用日截至 {_meta.get('public_asof', '—')} · "
            f"ETF覆盖 {len(_covered)}/14 · 数据哈希 {str(_meta.get('data_hash', ''))[:12]}"
        )
        st.info(
            "D组当前池也只使用SEC N-PORT公开文件，因此可能比发行商官网最新持仓滞后一季；"
            "这种滞后与历史回测完全同口径。SPY、RSP和11行业ETF仅作比较，不参与D组选股。",
            icon="ℹ️",
        )
    if not _meta.get("window_complete", True):
        _window_label = "全历史" if _dynasty_window == "ALL" else _dynasty_window
        st.caption(
            f"请求{_window_label}｜实际约 {_meta.get('actual_years', 0):.1f}Y"
            f"（{_meta.get('actual_days', 0)} 个交易日）"
        )
    if _meta.get("is_stale"):
        st.warning(
            f"价格数据截至 {_meta.get('price_as_of', '—')}，"
            f"已落后最近收盘 {_meta.get('stale_days', '—')} 个交易日；"
            "以下持仓仅代表该历史信号时点。"
        )

    _primary_strategy = _meta.get("selection_strategy", _dd.get("signal", ""))
    # ── 当前持仓卡
    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    if _primary_strategy == _DD_DELTA_STRATEGY:
        _strategy_title = "12M动量防抖守擂"
    else:
        _strategy_title = "12M动量K守擂"
    st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜{_strategy_title}")
    _cur = _dd.get("current_holdings", {})
    _cur_slots = _cur.get("slots", [])
    _hold_cols = st.columns(max(len(_cur_slots), 1))
    for _si in range(len(_cur_slots)):
        _slabel = _SLOT_LABELS[_si] if _si < len(_SLOT_LABELS) else f"槽{_si+1}"
        _sdata = _cur_slots[_si] or {}
        with _hold_cols[_si]:
            if not _sdata or _sdata.get("bil"):
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    "<div style='font-size:15px;color:#bbb;'>"
                    "BIL（无满足 12M 动量 + MA200 的合格股票）</div></div>"
                )
            else:
                _mom_val = _sdata.get("momentum_12m_pct")
                _mom_txt = f"{_mom_val:+.1f}%" if isinstance(_mom_val, (int, float)) else "—"
                _source_rows = _sdata.get("source_etfs") or []
                _source_names = [
                    row.get("etf") if isinstance(row, dict) else str(row)
                    for row in _source_rows
                ]
                _source_line = (
                    f"<br>D组来源 {' / '.join(x for x in _source_names if x)}"
                    if _is_d_theme and _source_names else ""
                )
                _slot_detail = (
                    f"12M排名 第 {_sdata.get('rank', '—')}｜12M涨幅 {_mom_txt}"
                    f"｜MA200上方 {'是' if _sdata.get('above_ma200') else '—'}"
                    f"<br>首次持有 {_sdata.get('since', '—')}｜已持有 {_sdata.get('held_months', '—')} 月"
                    f"{_source_line}"
                )
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    f"<div style='font-size:16px;color:#fff;font-weight:bold;'>"
                    f"{_sdata.get('name', '')} ({_sdata.get('ticker', '')})</div>"
                    f"<div style='font-size:14px;color:#bbb;margin-top:6px;'>{_slot_detail}</div></div>"
                )
            st.markdown(_slot_html, unsafe_allow_html=True)

    # ── 净值曲线
    st.markdown("##### 选中版本组合收益（起点归一为 1）")
    _eq = _dd.get("equity", {})
    _dd_dates = pd.to_datetime(_dd.get("dates", []), errors="coerce")
    _series_cfg = [
        ("momentum_k_guard", f"12M动量守擂 Top{_legacy_n_val}/{_legacy_k_txt}", "#F39C12", True),
        ("momentum_delta_guard", f"12M动量防抖 Top{_legacy_n_val}/{_delta_k_txt}", "#2ECC71", True),
        ("spy", "SPY", "#3498DB", True),
        ("rsp", "RSP 等权标普", "#9B59B6", False),
        ("eqw11", "11行业ETF等权", "#16A085", False),
    ]
    _fig_eq = go.Figure()
    for _key, _name, _color, _vis_default in _series_cfg:
        _vals = _eq.get(_key, []) or []
        if not _vals:
            continue
        _s = pd.Series(_vals, index=_dd_dates).astype(float).dropna()
        if _s.empty:
            continue
        _fig_eq.add_trace(go.Scatter(
            x=_s.index, y=_s.values, name=_name,
            line=dict(color=_color, width=2 if _vis_default else 1.4),
            visible=True if _vis_default else "legendonly",
        ))
    _fig_eq.update_layout(
        height=420, hovermode="x unified", template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.08),
        yaxis_title="净值（对数轴）",
        yaxis_type="log",
    )
    st.plotly_chart(_fig_eq, use_container_width=True, key=f"{_key_prefix}_equity")
    st.caption("当前组合主图保留动量TopN/K、防抖TopN/δ和SPY；点图例可展开 RSP / 11行业ETF等权")

    # ── 统计卡
    st.markdown("##### 统计卡")
    _stats = _dd.get("stats", {})
    _metrics_a = [
        ("累计收益", f"{_stats.get('cum_return', 0) * 100:.0f}%"),
        ("年化收益", f"{_stats.get('cagr', 0) * 100:.0f}%"),
        ("最大回撤", f"{_stats.get('max_dd', 0) * 100:.0f}%"),
        ("收益回撤比", f"{_stats.get('calmar', 0):.2f}"),
        ("比SPY多赚", f"{_stats.get('excess_vs_spy', 0) * 100:.0f}%"),
    ]
    _metrics_b = [
        ("换股次数", f"{_stats.get('n_swaps', 0)}"),
        ("平均一只拿几个月", f"{_stats.get('avg_hold_months', 0)}"),
        ("年均换手", f"{_stats.get('ann_turnover', 0):.2f}"),
        ("累计成本", f"{_stats.get('cum_cost', 0) * 100:.1f}%"),
        ("Sortino 比率", f"{_stats.get('sortino', 0):.2f}"),
    ]
    _row_a = st.columns(5)
    for _mi in range(len(_metrics_a)):
        with _row_a[_mi]:
            st.metric(_metrics_a[_mi][0], _metrics_a[_mi][1])
    _row_b = st.columns(5)
    for _mi in range(len(_metrics_b)):
        with _row_b[_mi]:
            st.metric(_metrics_b[_mi][0], _metrics_b[_mi][1])
    if _primary_strategy == _DD_MOMENTUM_STRATEGY:
        _k_note = (
            "K 由系统按当前窗口年化收益最高自动选择"
            if _legacy_k_mode == "best_cagr"
            else "K 使用请求参数"
        )
        st.caption(
            f"当前统计卡为 12M 动量守擂 Top{_legacy_n_val}/{_legacy_k_txt}；"
            f"{_k_note}；已有持仓仍在前 K 就留任，跌出前 K 才换。该策略固定不再平衡。"
        )
    elif _primary_strategy == _DD_DELTA_STRATEGY:
        _delta_horizons = (
            (_delta_params.get("selection", {}) or {}).get("horizons")
            or (["3Y", "5Y", "ALL"] if _is_d_theme else ["3Y", "5Y", "10Y"])
        )
        _delta_horizon_text = "/".join(
            "全历史" if value == "ALL" else value for value in _delta_horizons
        )
        _delta_note = (
            f"kδ 由系统按 {_delta_horizon_text} 稳健平台自动选择"
            if _delta_k_mode == "robust_maximin"
            else "kδ 使用请求参数"
        )
        st.caption(
            f"当前统计卡为 12M 动量防抖守擂 Top{_legacy_n_val}/{_delta_k_txt}；"
            f"{_delta_note}；已有持仓距 TopN 门槛在 δ 内就留任，差得更多才换。该策略固定不再平衡。"
        )
    if _primary_strategy == _DD_MOMENTUM_STRATEGY and _legacy_k_val is not None:
        st.caption(
            f"动量守擂自动K：当前 Top{_legacy_n_val} 采用 {_legacy_k_txt}；"
            "页面不再提供手动 K 滑杆，避免把参数搜索误当成实时可控信号。"
        )
    if _primary_strategy == _DD_DELTA_STRATEGY and _delta_k_val is not None:
        st.caption(
            f"防抖守擂自动 kδ：当前 Top{_legacy_n_val} 采用 {_delta_k_txt}；"
            "自动值取三段窗口都不差的平台点，不取单段最高收益尖峰。"
        )

    # ── Slot 分段收益
    st.markdown("##### Slot 分段收益")
    _has_slot_returns = render_slot_segment_returns(_dd, _key_prefix)
    if not _has_slot_returns:
        st.caption("后端暂未返回 slot_equity。")

    # ── 防抖守擂 δ 稳健性（D组用 3Y/5Y/全历史；标普保留 3Y/5Y/10Y）
    _sweep = (_delta_params.get("selection", {}) or {}).get("sweep_grid", {}) or {}
    if _sweep:
        _HZ = (
            (_delta_params.get("selection", {}) or {}).get("horizons")
            or (["3Y", "5Y", "ALL"] if _is_d_theme else ["3Y", "5Y", "10Y"])
        )
        _hz_title = "/".join("全历史" if value == "ALL" else value for value in _HZ)
        st.markdown(f"##### 防抖守擂 δ 稳健性（{_hz_title}）")
        _dk_grid = sorted(_sweep.keys(), key=lambda s: float(s))
        _x = [float(s) for s in _dk_grid]
        _curves = {hz: [float(_sweep[s].get(hz, float("nan"))) * 100 for s in _dk_grid] for hz in _HZ}
        _norm = {}
        for hz in _HZ:
            _c = pd.Series(_curves[hz])
            _mx = _c.max()
            _norm[hz] = (_c / _mx) if (_mx == _mx and _mx > 0) else _c * float("nan")
        _COLOR = {"3Y": "#5DADE2", "5Y": "#FFD700", "10Y": "#E67E22", "ALL": "#E67E22"}
        _fig_sweep = go.Figure()
        for hz in _HZ:
            if pd.Series(_curves[hz]).notna().sum() < 2:
                continue
            _lw = 4 if hz == "3Y" else 2
            _fig_sweep.add_trace(go.Scatter(
                x=_x, y=list(_norm[hz]), mode="lines+markers",
                name="全历史" if hz == "ALL" else hz,
                line=dict(color=_COLOR.get(hz, "#E67E22"), width=_lw), marker=dict(size=5),
                customdata=_curves[hz],
                hovertemplate=f"{hz} δ=%{{x}} → 总收益 %{{customdata:.1f}}%<extra></extra>",
            ))
        if _delta_k_val is not None:
            _fig_sweep.add_vline(x=_delta_k_val, line=dict(color="#2ECC71", width=2, dash="dash"))
            _fig_sweep.add_annotation(
                x=_delta_k_val, y=1.02, yref="paper", text=f"推荐 δ*={_delta_k_val:.2f}",
                showarrow=False, font=dict(color="#2ECC71", size=12), bgcolor="#111", xanchor="left",
            )
        _fig_sweep.update_layout(
            height=300, margin=dict(l=20, r=20, t=46, b=20),
            plot_bgcolor="#111111", paper_bgcolor="#111111", font=dict(color="#ddd"),
            xaxis=dict(title="δ (×横截面标准差)", showgrid=True, gridcolor="#222", dtick=0.25),
            yaxis=dict(title="各段归一化收益 (÷自身峰值)", showgrid=True, gridcolor="#222"),
            title=dict(
                text=f"δ 稳健性 · {_hz_title} 总收益（各自归一化；三线齐高处=稳健 δ）",
                font=dict(size=13), x=0.01, xanchor="left",
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        )
        st.plotly_chart(_fig_sweep, use_container_width=True, key=f"{_key_prefix}_delta_sweep")

        def _argmax_delta(hz):
            _c = pd.Series(_curves[hz])
            return _dk_grid[int(_c.idxmax())] if _c.notna().any() else None
        _peaks = " · ".join(
            f"{'全历史' if hz == 'ALL' else hz} 单峰 δ={_argmax_delta(hz)}"
            for hz in _HZ if _argmax_delta(hz) is not None
        )
        if _delta_k_val is not None:
            st.caption(
                f"✅ **推荐 δ\\* = {_delta_k_val:.2f}**（三段都不差的重叠平台，跨窗口稳健）。"
                f"对照各段单独最优：{_peaks}——单段峰值各不相同正是过拟合的症状，别照搬。"
            )

    # ── 【本地实验】回撤止损原型（独立 tab，便于后续迭代/删除）──
    st.markdown("---")
    _proto_tabs = st.tabs(["📉 回撤止损原型（本地实验）"])
    with _proto_tabs[0]:
        render_dd_stop_tab(_dd, _strategy_title, _key_prefix)

_active_tab_stack.close()
