"""持仓段 → 周线 NAV 拼接 + KPI 计算的纯函数。

从 pages/5_个股择时.py 抽出，供 page0 持仓回测图与 page5 A/B 图共用，避免两页各写一份。
这三个函数无 Streamlit / 闭包依赖，行为与 page5 原实现逐行一致。
"""
import math

import numpy as np
import pandas as pd


def build_slot_segments(slot_assignments: dict, slot_idx: int, tm_months: list) -> list:
    """slot 序列 → 连续持仓段 [(ticker, start_month, end_month), ...]。

    slot_assignments: {month: [slot0_ticker, slot1_ticker, ...]}；
    相邻同 ticker 合并成一段，ticker 变化处换段。"CASH" 也作为独立段。
    """
    segs: list = []
    _cur_tk, _cur_s, _cur_e = None, None, None
    for _m in tm_months:
        _tk = slot_assignments.get(_m, [None, None])[slot_idx]
        if _tk == _cur_tk:
            _cur_e = _m
        else:
            if _cur_tk is not None:
                segs.append((_cur_tk, _cur_s, _cur_e))
            _cur_tk, _cur_s, _cur_e = _tk, _m, _m
    if _cur_tk is not None:
        segs.append((_cur_tk, _cur_s, _cur_e))
    return segs


def calc_slot_stats(
    segs: list, price_cache: dict = None, spy_wk: pd.DataFrame = None,
    cash_rate: float = 0.04,
) -> tuple:
    """持仓段序列 → 周线 NAV（含 CASH 段按年化复利），返回 (总收益%, 最大回撤%, NAV Series)。

    price_cache: {ticker: 周线 OHLCV DataFrame}；CASH 段用 spy_wk 的时间轴补日期。
    """
    _pc2 = price_cache if price_cache is not None else {}
    nav_all: list = []
    running_nav = 1.0
    for _tk, _s_m, _e_m in segs:
        if _tk == "CASH":
            # 闸门关月份：按 cash_rate 年化复利累积，用 SPY 时间轴补日期
            if spy_wk is not None and not spy_wk.empty:
                _sd = pd.Timestamp(f"{_s_m}-01")
                _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
                _cash_idx = spy_wk.index[(spy_wk.index >= _sd) & (spy_wk.index <= _ed)]
                if len(_cash_idx) >= 1:
                    _days = (_cash_idx - _cash_idx[0]).days.to_numpy()
                    _cash_nav = running_nav * (1.0 + cash_rate) ** (_days / 365.0)
                    _cash_series = pd.Series(_cash_nav, index=_cash_idx, dtype=float)
                    nav_all.append(_cash_series)
                    running_nav = float(_cash_series.iloc[-1])
            continue
        _wkd = _pc2.get(_tk)
        if _wkd is None or _wkd.empty:
            continue
        _sd = pd.Timestamp(f"{_s_m}-01")
        _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
        _mask = (_wkd.index >= _sd) & (_wkd.index <= _ed)
        _seg_wk = _wkd[_mask].copy()
        _closes = _seg_wk["Close"].astype(float).dropna()
        if len(_closes) < 2:
            continue
        _seg_nav = (_closes / float(_closes.iloc[0])) * running_nav
        running_nav = float(_seg_nav.iloc[-1])
        nav_all.append(_seg_nav)
    if not nav_all:
        return 0.0, 0.0, pd.Series(dtype=float)
    _nav = pd.concat(nav_all).sort_index()
    _nav = _nav[~_nav.index.duplicated(keep="last")]
    _total_ret = (float(_nav.iloc[-1]) / float(_nav.iloc[0]) - 1) * 100
    _peak = _nav.cummax()
    _dd = (_peak - _nav) / _peak.replace(0, float("nan"))
    _max_dd = float(_dd.max()) * 100
    return _total_ret, _max_dd, _nav


def compute_nav_kpi(nav: pd.Series) -> dict:
    """Calmar / log-NAV R² / Sortino / CAGR / Ulcer（周线 NAV 输入，√52 年化）。"""
    if nav.empty or len(nav) < 8:
        return {"calmar": float("nan"), "r2": float("nan"),
                "sortino": float("nan"), "ulcer": float("nan")}
    nav = nav.astype(float).dropna()
    wk_ret = nav.pct_change().dropna()
    years = len(nav) / 52.0
    if years < 0.1:
        return {"calmar": float("nan"), "r2": float("nan"),
                "sortino": float("nan"), "ulcer": float("nan")}
    cagr = (float(nav.iloc[-1]) / float(nav.iloc[0])) ** (1.0 / years) - 1.0
    peak = nav.cummax()
    dd = nav / peak - 1.0
    max_dd = abs(float(dd.min()))
    # Ulcer Index：回撤深度×水下时长的 RMS（百分比口径），与 harness portfolio_engine 同口径
    ulcer = float(np.sqrt(np.mean((dd.values.astype(float) * 100.0) ** 2)))
    calmar = cagr / max_dd if max_dd > 1e-9 else float("nan")
    log_nav = np.log(nav.values)
    x = np.arange(len(log_nav), dtype=float)
    coeffs = np.polyfit(x, log_nav, 1)
    pred = np.polyval(coeffs, x)
    ss_res = float(np.sum((log_nav - pred) ** 2))
    ss_tot = float(np.sum((log_nav - log_nav.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
    neg_rets = wk_ret[wk_ret < 0]
    down_std = float(neg_rets.std()) * (52.0 ** 0.5) if len(neg_rets) > 1 else float("nan")
    sortino = cagr / down_std if (down_std and not math.isnan(down_std) and down_std > 1e-9) else float("nan")
    return {"calmar": calmar, "r2": r2, "sortino": sortino, "cagr": cagr, "ulcer": ulcer}
