from __future__ import annotations

import math
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import streamlit as st
from _yf_session import YF_SESSION

SLOT_COLORS = [
    "#2ECC71", "#3498DB", "#E67E22", "#9B59B6",
    "#1ABC9C", "#E74C3C", "#F1C40F", "#8E44AD",
]


# Sharadar 价格缓存：Page 6 净值重建优先用后端推来的股息复权日线（含退市票、深 8 年），
# 缺的票（如系统上线后新增的活票）才回退 yfinance（只有 ~5 年）。
# prime_sharadar_prices() 由 Page 6 在拉价前注入一次。
_SHARADAR_DAILY: dict = {}


def _series_to_daily(series: list) -> pd.DataFrame:
    """后端 [[date,o,h,l,c,v], ...] → 日线 DataFrame（index=date, cols=OHLCV）。"""
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series, columns=["date", "Open", "High", "Low", "Close", "Volume"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["Close"])


def prime_sharadar_prices(prices: dict) -> int:
    """注入后端 Sharadar 日线（{ticker: [[date,o,h,l,c,v]]}），供 fetch_*_ohlcv 优先取用。"""
    n = 0
    for tk, series in (prices or {}).items():
        d = _series_to_daily(series)
        if not d.empty:
            _SHARADAR_DAILY[tk] = d
            n += 1
    return n


def fetch_weekly_ohlcv(ticker: str) -> pd.DataFrame:
    """周线 OHLCV：优先 Sharadar（含退市、深历史），缺则回退 yfinance。"""
    if ticker in _SHARADAR_DAILY:
        return daily_to_weekly(_SHARADAR_DAILY[ticker])
    return _fetch_weekly_yf(ticker)


def fetch_daily_ohlcv(ticker: str) -> pd.DataFrame:
    """日线 OHLCV：优先 Sharadar（含退市、深历史），缺则回退 yfinance。"""
    if ticker in _SHARADAR_DAILY:
        return _SHARADAR_DAILY[ticker]
    return _fetch_daily_yf(ticker)


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def _fetch_weekly_yf(ticker: str) -> pd.DataFrame:
    h = yf.Ticker(ticker, session=YF_SESSION).history(period="5y")
    if h.empty:
        return pd.DataFrame()
    w = h.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()
    if w.index.tz is not None:
        try:
            w.index = w.index.tz_localize(None)
        except TypeError:
            w.index = w.index.tz_convert(None)
    return w


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def _fetch_daily_yf(ticker: str) -> pd.DataFrame:
    """日线 OHLC（含分红调整）。day1 开盘买必须用日线，周线只有周五。"""
    h = yf.Ticker(ticker, session=YF_SESSION).history(start="2021-06-01")
    if h.empty:
        return pd.DataFrame()
    d = h[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
    if d.index.tz is not None:
        try:
            d.index = d.index.tz_localize(None)
        except TypeError:
            d.index = d.index.tz_convert(None)
    return d


def daily_to_weekly(d: pd.DataFrame) -> pd.DataFrame:
    """日线降采样到 W-FRI（拼接图 / A 曲线复用，省一次网络拉取）。"""
    if d is None or d.empty:
        return pd.DataFrame()
    w = d.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()
    return w


def next_month_key(m: str, k: int = 1) -> str:
    """'2026-05' + k 个月 → '2026-06'。去 look-ahead 用：决策月顺延执行。"""
    y, mm = int(m[:4]), int(m[5:7])
    mm += k
    y += (mm - 1) // 12
    mm = (mm - 1) % 12 + 1
    return f"{y:04d}-{mm:02d}"


def get_holding_periods(cls_map: dict, ticker: str) -> list:
    periods: list = []
    in_h, start, prev = False, None, None
    for m in sorted(cls_map.keys()):
        if ticker in cls_map[m]:
            if not in_h:
                start = m
                in_h = True
            prev = m
        elif in_h:
            periods.append((start, prev))
            in_h = False
    if in_h:
        periods.append((start, prev))
    return periods


def build_slot_segments(slot_assignments: dict, slot_idx: int, months: list) -> list:
    segs: list = []
    cur_tk, cur_s, cur_e = None, None, None
    for m in months:
        tk = slot_assignments.get(m, [None, None])[slot_idx]
        if tk == cur_tk:
            cur_e = m
        else:
            if cur_tk is not None:
                segs.append((cur_tk, cur_s, cur_e))
            cur_tk, cur_s, cur_e = tk, m, m
    if cur_tk is not None:
        segs.append((cur_tk, cur_s, cur_e))
    return segs


def build_slot_assignments(
    history: dict, grade: str, buffer_n: int, shift_months: int = 1,
) -> tuple[dict, dict, list]:
    """返回 (slot_assignments, hold_map, gate_closed).
    slot_assignments: {month: [slot0_ticker_or_CASH, slot1_...]}
    hold_map:         {month: set(持仓)}（闸门关月为空集）
    gate_closed:      [(month, reason), ...]
    逻辑与 page5 525-596 完全一致。

    shift_months：决策月顺延 N 月执行，去 look-ahead（月 M 的持仓在 M+N 才进场，
    因为 M 的排名是用截至 M 月末的数据算的）。slot_assignments / gate_closed 的 key
    随之顺延，下游窗口（月初→月末）自然落在执行月。
    """
    months = sorted(k for k in history if not k.startswith("_"))
    hold_map: dict = {}
    gate_closed: list = []
    prev_h: set = set()

    for m in months:
        rec = history[m].get(
            grade, {"tickers": [], "gate_status": "open", "gate_reason": ""}
        )
        gate_open = rec.get("gate_status", "open") != "closed"
        if not gate_open:
            gate_closed.append((m, rec.get("gate_reason", "")))
        recs = rec.get("tickers", [])
        t3 = {r.get("ticker", "") for r in recs[:buffer_n]} - {""}
        t2 = {r.get("ticker", "") for r in recs[:2]} - {""}

        if prev_h:
            survivors = prev_h & t3
            if len(survivors) >= 2:
                strategy_hold = survivors
            elif len(survivors) == 1:
                fill = next(
                    (r.get("ticker") for r in recs[:buffer_n]
                     if r.get("ticker") and r["ticker"] not in survivors),
                    None,
                )
                strategy_hold = survivors | {fill} if fill else t2
            else:
                strategy_hold = t2
        else:
            strategy_hold = t2

        hold_map[m] = strategy_hold if gate_open else set()
        prev_h = strategy_hold

    gate_months: set = {m for m, _ in gate_closed}
    slot_assignments: dict = {}
    prev_slots: list = [None, None]

    for m in months:
        if m in gate_months:
            slot_assignments[m] = ["CASH", "CASH"]
            continue
        hold_set = hold_map.get(m, set())
        new_slots: list = [None, None]
        assigned: set = set()
        for si in range(2):
            if prev_slots[si] and prev_slots[si] in hold_set:
                new_slots[si] = prev_slots[si]
                assigned.add(prev_slots[si])
        for t in sorted(t for t in hold_set if t not in assigned):
            for si in range(2):
                if new_slots[si] is None:
                    new_slots[si] = t
                    break
        slot_assignments[m] = new_slots
        prev_slots = new_slots

    if shift_months:
        slot_assignments = {
            next_month_key(m, shift_months): v for m, v in slot_assignments.items()
        }
        hold_map = {next_month_key(m, shift_months): v for m, v in hold_map.items()}
        gate_closed = [(next_month_key(m, shift_months), r) for m, r in gate_closed]

    return slot_assignments, hold_map, gate_closed


def build_basket_slot_assignments(monthly_holdings: dict, months: list) -> dict:
    """把篮子月度持仓 {month: [top1, top2]} 拆成两槽分配，供拼接图用。
    无守擂缓冲，但保持槽位连续：上月在该槽的标的若本月仍持有就留原槽，
    避免同两只股票顺序变化时左右列来回跳。空仓月填 CASH。
    """
    slot_assignments: dict = {}
    prev_slots: list = [None, None]
    for m in months:
        basket = [t for t in monthly_holdings.get(m, []) if t]
        if not basket:
            slot_assignments[m] = ["CASH", "CASH"]
            prev_slots = [None, None]
            continue
        new_slots: list = [None, None]
        assigned: set = set()
        for si in range(2):
            if prev_slots[si] and prev_slots[si] in basket:
                new_slots[si] = prev_slots[si]
                assigned.add(prev_slots[si])
        for t in basket:
            if t in assigned:
                continue
            for si in range(2):
                if new_slots[si] is None:
                    new_slots[si] = t
                    assigned.add(t)
                    break
        slot_assignments[m] = new_slots
        prev_slots = new_slots
    return slot_assignments


def build_stitched_fig(
    segs: list, slot_name: str,
    spy_wk: pd.DataFrame = None,
    price_cache: dict = None,
    name_map: dict = None,
) -> go.Figure:
    pc = price_cache if price_cache is not None else {}
    nm = name_map if name_map is not None else {}
    fig = go.Figure()
    x_offset = 0
    tick_vals: list = []
    tick_texts: list = []
    boundary_xs: list = []
    name_annotations: list = []
    running_return = 0.0
    spy_close = (
        spy_wk["Close"].astype(float).dropna()
        if spy_wk is not None and not spy_wk.empty
        else None
    )
    spy_x_all: list = []
    spy_y_all: list = []
    spy_running_return = 0.0

    for ci, (tk, s_m, e_m) in enumerate(segs):
        if tk == "CASH":
            if spy_wk is not None and not spy_wk.empty:
                sd = pd.Timestamp(f"{s_m}-01")
                ed = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
                cash_idx = spy_wk.index[(spy_wk.index >= sd) & (spy_wk.index <= ed)]
                if len(cash_idx) >= 1:
                    n = len(cash_idx)
                    x_vals = list(range(x_offset, x_offset + n))
                    fig.add_trace(go.Scatter(
                        x=x_vals, y=[running_return] * n,
                        mode="lines",
                        line=dict(color="#bbbbbb", width=2, dash="dot"),
                        name=f"💰 空仓（{s_m}→{e_m}）",
                        showlegend=False,
                    ))
                    tick_vals.append(x_offset + n // 2)
                    tick_texts.append(f"{s_m}→{e_m}")
                    name_annotations.append(dict(
                        x=x_offset + n // 2, y=1.0,
                        xref="x", yref="paper",
                        text="💰 空仓", showarrow=False,
                        font=dict(size=13, color="#bbbbbb"),
                        xanchor="center", yanchor="bottom",
                    ))
                    if x_offset > 0:
                        boundary_xs.append(x_offset - 0.5)
                    if spy_close is not None:
                        spy_seg = spy_close.reindex(cash_idx, method="ffill").bfill().dropna()
                        if len(spy_seg) >= 2:
                            spy_pct = (spy_seg / float(spy_seg.iloc[0]) - 1) * 100
                            spy_cum = spy_running_return + spy_pct
                            for si, sdt in enumerate(cash_idx):
                                if sdt in spy_seg.index:
                                    spy_x_all.append(x_offset + si)
                                    spy_y_all.append(float(spy_cum.loc[sdt]))
                            spy_running_return = float(spy_cum.iloc[-1])
                    x_offset += n
            continue

        wkd = pc.get(tk)
        if wkd is None or wkd.empty:
            continue
        sd = pd.Timestamp(f"{s_m}-01")
        ed = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
        mask = (wkd.index >= sd) & (wkd.index <= ed)
        closes = wkd[mask]["Close"].astype(float).dropna()
        if len(closes) < 2:
            continue

        n = len(closes)
        x_vals = list(range(x_offset, x_offset + n))
        color = SLOT_COLORS[ci % len(SLOT_COLORS)]
        seg_pct = (closes / float(closes.iloc[0]) - 1) * 100
        seg_cum = running_return + seg_pct

        fig.add_trace(go.Scatter(
            x=x_vals, y=seg_cum.values, mode="lines",
            line=dict(color=color, width=2),
            name=f"{tk}（{s_m}→{e_m}）",
            showlegend=False,
        ))
        running_return = float(seg_cum.iloc[-1])

        if spy_close is not None:
            spy_seg = spy_close.reindex(closes.index, method="ffill").bfill().dropna()
            if len(spy_seg) >= 2:
                spy_pct = (spy_seg / float(spy_seg.iloc[0]) - 1) * 100
                spy_cum = spy_running_return + spy_pct
                for si, sdt in enumerate(closes.index):
                    if sdt in spy_seg.index:
                        spy_x_all.append(x_offset + si)
                        spy_y_all.append(float(spy_cum.loc[sdt]))
                spy_running_return = float(spy_cum.iloc[-1])

        tick_vals.append(x_offset + n // 2)
        tick_texts.append(f"{s_m}→{e_m}")
        name_annotations.append(dict(
            x=x_offset + n // 2, y=1.0,
            xref="x", yref="paper",
            text=tk, showarrow=False,
            font=dict(size=13, color=color),
            xanchor="center", yanchor="bottom",
        ))
        if x_offset > 0:
            boundary_xs.append(x_offset - 0.5)
        x_offset += n

    for bx in boundary_xs:
        fig.add_vline(x=bx, line_dash="dash",
                      line_color="rgba(200,200,200,0.35)", line_width=1)

    if spy_x_all:
        fig.add_trace(go.Scatter(
            x=spy_x_all, y=spy_y_all, mode="lines",
            line=dict(color="rgba(180,180,180,0.4)", width=2, dash="dot"),
            name=f"SPY 同期 {spy_running_return:+.1f}%",
        ))
        fig.data = fig.data[-1:] + fig.data[:-1]

    fig.update_layout(
        title=f"{slot_name} — 累计收益率（共 {len(segs)} 段）",
        xaxis=dict(
            tickvals=tick_vals, ticktext=tick_texts,
            tickfont=dict(size=11), tickangle=-30,
            gridcolor="rgba(100,100,100,0.3)",
        ),
        yaxis=dict(
            title="累计收益率 (%)", ticksuffix="%",
            gridcolor="rgba(100,100,100,0.3)",
        ),
        annotations=name_annotations,
        height=560, margin=dict(l=10, r=10, t=44, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=13),
        showlegend=bool(spy_x_all),
    )
    return fig


def calc_slot_stats(
    segs: list,
    price_cache: dict = None,
    spy_wk: pd.DataFrame = None,
    cash_rate: float = 0.04,
    cost_bps: float = 0.0,
) -> tuple:
    """cost_bps：单边换仓成本（手续费+滑点）。每次卖出旧标的、买入新标的各扣一次；
    CASH 不算成本资产。成本在每段渲染前从 running_nav 扣除，只对真正进入价格窗口
    的段计费（窗口外被跳过的段不计），避免凭空侵蚀起点。"""
    pc = price_cache if price_cache is not None else {}
    nav_all: list = []
    running_nav = 1.0
    last_tk = None  # 上一段「实际渲染」的标的（用于判断换仓边界）
    for tk, s_m, e_m in segs:
        if tk == "CASH":
            if spy_wk is not None and not spy_wk.empty:
                sd = pd.Timestamp(f"{s_m}-01")
                ed = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
                cash_idx = spy_wk.index[(spy_wk.index >= sd) & (spy_wk.index <= ed)]
                if len(cash_idx) >= 1:
                    if cost_bps and last_tk is not None and last_tk != "CASH":
                        running_nav *= max(0.0, 1.0 - cost_bps / 10000.0)
                    days = (cash_idx - cash_idx[0]).days.to_numpy()
                    cash_nav = running_nav * (1.0 + cash_rate) ** (days / 365.0)
                    cash_series = pd.Series(cash_nav, index=cash_idx, dtype=float)
                    nav_all.append(cash_series)
                    running_nav = float(cash_series.iloc[-1])
                    last_tk = "CASH"
            continue
        wkd = pc.get(tk)
        if wkd is None or wkd.empty:
            continue
        sd = pd.Timestamp(f"{s_m}-01")
        ed = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
        mask = (wkd.index >= sd) & (wkd.index <= ed)
        closes = wkd[mask]["Close"].astype(float).dropna()
        if len(closes) < 2:
            continue
        if cost_bps:
            sides = (1 if (last_tk is not None and last_tk != "CASH") else 0) + 1
            running_nav *= max(0.0, 1.0 - sides * cost_bps / 10000.0)
        seg_nav = (closes / float(closes.iloc[0])) * running_nav
        running_nav = float(seg_nav.iloc[-1])
        last_tk = tk
        nav_all.append(seg_nav)
    if not nav_all:
        return 0.0, 0.0, pd.Series(dtype=float)
    nav = pd.concat(nav_all).sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    total_ret = (float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100
    peak = nav.cummax()
    dd = (peak - nav) / peak.replace(0, float("nan"))
    max_dd = float(dd.max()) * 100
    return total_ret, max_dd, nav


def compute_nav_kpi(nav: pd.Series) -> dict:
    """Calmar / log-NAV R² / Sortino（周线 NAV 输入，√52 年化）。"""
    if nav.empty or len(nav) < 8:
        return {"calmar": float("nan"), "r2": float("nan"), "sortino": float("nan")}
    nav = nav.astype(float).dropna()
    wk_ret = nav.pct_change().dropna()
    years = len(nav) / 52.0
    if years < 0.1:
        return {"calmar": float("nan"), "r2": float("nan"), "sortino": float("nan")}
    cagr = (float(nav.iloc[-1]) / float(nav.iloc[0])) ** (1.0 / years) - 1.0
    peak = nav.cummax()
    max_dd = abs(float((nav / peak - 1.0).min()))
    calmar = cagr / max_dd if max_dd > 1e-9 else float("nan")
    log_nav = np.log(nav.values)
    x = np.arange(len(log_nav), dtype=float)
    coeffs = np.polyfit(x, log_nav, 1)
    pred = np.polyval(coeffs, x)
    ss_res = float(np.sum((log_nav - pred) ** 2))
    ss_tot = float(np.sum((log_nav - log_nav.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
    neg_rets = wk_ret[wk_ret < 0]
    down_std = (
        float(neg_rets.std()) * (52.0 ** 0.5) if len(neg_rets) > 1 else float("nan")
    )
    sortino = (
        cagr / down_std
        if (down_std and not math.isnan(down_std) and down_std > 1e-9)
        else float("nan")
    )
    return {"calmar": calmar, "r2": r2, "sortino": sortino, "cagr": cagr}


def _basket_select(history: dict, grade: str, top_n: int,
                   buffer_n: int | None) -> dict:
    """{决策月: [tickers]}，闸门关→[]。动量缓冲逻辑同原 build_basket_nav。"""
    months = sorted(k for k in history if not k.startswith("_"))
    out: dict = {}
    prev_basket: list = []
    for m in months:
        rec = history[m].get(
            grade, {"tickers": [], "gate_status": "open", "gate_reason": ""})
        if rec.get("gate_status", "open") == "closed":
            out[m] = []
            prev_basket = []
            continue
        ranked = [r.get("ticker", "") for r in rec.get("tickers", []) if r.get("ticker")]
        if buffer_n and prev_basket:
            top_buf = ranked[:buffer_n]
            basket = [t for t in prev_basket if t in top_buf][:top_n]
            for t in ranked:
                if len(basket) >= top_n:
                    break
                if t not in basket:
                    basket.append(t)
        else:
            basket = ranked[:top_n]
        out[m] = basket
        prev_basket = basket
    return out


def build_basket_nav(
    history: dict,
    grade: str,
    price_cache_daily: dict,
    spy_daily: pd.DataFrame,
    top_n: int = 2,
    cash_rate: float = 0.04,
    buffer_n: int | None = None,
    cost_bps: float = 0.0,
    rebalance_step: int = 1,
    shift_months: int = 1,
) -> dict:
    """等权 top_n 篮子，日1开盘买入 + 顺延执行（去 look-ahead）。

    决策月 M 的篮子（用截至 M 月末数据算的排名）在 M+shift_months 月才进场，
    每 rebalance_step 个月调一次仓（1=月度，3=季度）。进场=执行段首个交易日开盘价，
    持有到段末交易日收盘，按日线走净值，卖出一日卖在调仓点。
    返回的 nav 已降采样到周线，供 compute_nav_kpi（√52 年化）消费。

    buffer_n：动量缓冲（同原逻辑）。cost_bps：单边换仓成本，按换手只数计费一次。
    返回 {"nav", "total_ret", "max_dd", "turnover_pct", "monthly_holdings"}
    """
    decision_baskets = _basket_select(history, grade, top_n, buffer_n)
    dmonths = sorted(decision_baskets)
    empty = {"nav": pd.Series(dtype=float), "total_ret": 0.0, "max_dd": 0.0,
             "turnover_pct": 0.0, "monthly_holdings": {}}
    if len(dmonths) < 2 or spy_daily is None or spy_daily.empty:
        return empty

    cal = spy_daily.index
    running_nav = 1.0
    nav_parts: list = []
    exec_holdings: dict = {}
    prev: list = []
    turns: list = []

    for i in range(0, len(dmonths), rebalance_step):
        dm = dmonths[i]
        basket = decision_baskets[dm]
        start_m = next_month_key(dm, shift_months)
        span = [next_month_key(start_m, j) for j in range(rebalance_step)]
        sd = pd.Timestamp(f"{span[0]}-01")
        ed = pd.Timestamp(f"{span[-1]}-01") + pd.offsets.MonthEnd(1)
        day_idx = cal[(cal >= sd) & (cal <= ed)]

        if i > 0:
            denom = max(len(basket), len(prev), 1)
            turns.append(len(set(basket) - set(prev)) / denom)
        traded = len(set(prev) ^ set(basket))
        for sm in span:
            exec_holdings[sm] = basket
        if cost_bps and basket and traded and top_n > 0 and len(day_idx) >= 1:
            running_nav *= max(0.0, 1.0 - (traded / top_n) * cost_bps / 10000.0)
        prev = basket

        if not basket or len(day_idx) < 1:
            if len(day_idx) >= 1:
                days = (day_idx - day_idx[0]).days.to_numpy()
                cash_nav = running_nav * (1.0 + cash_rate) ** (days / 365.0)
                part = pd.Series(cash_nav, index=day_idx, dtype=float)
                nav_parts.append(part)
                running_nav = float(part.iloc[-1])
            continue

        valid_paths: list = []
        for tk in basket:
            d = price_cache_daily.get(tk)
            if d is None or d.empty:
                continue
            win = d[(d.index >= sd) & (d.index <= ed)]
            if len(win) < 2:
                continue
            entry = float(win["Open"].iloc[0])
            if entry <= 0:
                continue
            path = win["Close"].astype(float) / entry
            valid_paths.append(path.reindex(day_idx, method="ffill").bfill())

        if not valid_paths:
            days = (day_idx - day_idx[0]).days.to_numpy()
            cash_nav = running_nav * (1.0 + cash_rate) ** (days / 365.0)
            part = pd.Series(cash_nav, index=day_idx, dtype=float)
            nav_parts.append(part)
            running_nav = float(part.iloc[-1])
            continue

        basket_path = pd.concat(valid_paths, axis=1).mean(axis=1)
        seg_nav = basket_path * running_nav
        running_nav = float(seg_nav.iloc[-1])
        nav_parts.append(seg_nav)

    if not nav_parts:
        return {**empty, "monthly_holdings": exec_holdings}

    nav_daily = pd.concat(nav_parts).sort_index()
    nav_daily = nav_daily[~nav_daily.index.duplicated(keep="last")]
    nav = nav_daily.resample("W-FRI").last().dropna()
    if len(nav) < 2:
        return {**empty, "monthly_holdings": exec_holdings}
    total_ret = (float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100
    peak = nav.cummax()
    dd = (peak - nav) / peak.replace(0, float("nan"))
    max_dd = float(dd.max()) * 100
    turnover_pct = float(np.mean(turns)) * 100 if turns else 0.0

    return {
        "nav": nav,
        "total_ret": total_ret,
        "max_dd": max_dd,
        "turnover_pct": turnover_pct,
        "monthly_holdings": exec_holdings,
    }


def build_combined_fig(
    nav_l: pd.Series,
    nav_r: pd.Series,
    nav_combined: pd.Series,
    spy_wk: pd.DataFrame,
    title: str,
) -> go.Figure:
    """合成 A 曲线 + 左列 + 右列 + SPY 四线叠加。
    各序列相对自身起点归一为累计收益率；add 顺序决定 z 层，
    SPY 最底、合成 A 曲线最上。
    """
    fig = go.Figure()
    if nav_combined.empty:
        return fig

    def _pct(s: pd.Series) -> pd.Series:
        s = s.astype(float).dropna()
        return (s / float(s.iloc[0]) - 1) * 100 if not s.empty else s

    # SPY 对齐到合成曲线的时间区间（最底层）
    if spy_wk is not None and not spy_wk.empty:
        sd, ed = nav_combined.index[0], nav_combined.index[-1]
        spy_seg = spy_wk[(spy_wk.index >= sd) & (spy_wk.index <= ed)]["Close"]
        spy_seg = spy_seg.astype(float).dropna()
        if len(spy_seg) >= 2:
            spy_pct = (spy_seg / float(spy_seg.iloc[0]) - 1) * 100
            fig.add_trace(go.Scatter(
                x=spy_pct.index, y=spy_pct.values, mode="lines",
                name=f"SPY {float(spy_pct.iloc[-1]):+.1f}%",
                line=dict(color="rgba(170,170,170,0.45)", width=1.5, dash="dot"),
            ))

    if not nav_l.empty:
        l_pct = _pct(nav_l)
        fig.add_trace(go.Scatter(
            x=l_pct.index, y=l_pct.values, mode="lines",
            name=f"左列 Slot 0 {float(l_pct.iloc[-1]):+.1f}%",
            line=dict(color="rgba(46,204,113,0.7)", width=1.5),
        ))
    if not nav_r.empty:
        r_pct = _pct(nav_r)
        fig.add_trace(go.Scatter(
            x=r_pct.index, y=r_pct.values, mode="lines",
            name=f"右列 Slot 1 {float(r_pct.iloc[-1]):+.1f}%",
            line=dict(color="rgba(52,152,219,0.7)", width=1.5),
        ))

    a_pct = _pct(nav_combined)
    fig.add_trace(go.Scatter(
        x=a_pct.index, y=a_pct.values, mode="lines",
        name=f"A 曲线（50/50 合成） {float(a_pct.iloc[-1]):+.1f}%",
        line=dict(color="#F1C40F", width=3),
    ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="累计收益率 (%)", ticksuffix="%",
            gridcolor="rgba(100,100,100,0.3)",
        ),
        height=480, margin=dict(l=10, r=10, t=44, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=13),
        showlegend=True,
    )
    return fig


def build_basket_fig(nav: pd.Series, spy_wk: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    if nav.empty:
        return fig
    nav_pct = (nav / float(nav.iloc[0]) - 1) * 100
    fig.add_trace(go.Scatter(
        x=nav_pct.index, y=nav_pct.values,
        mode="lines", name=title,
        line=dict(color="#F1C40F", width=2),
    ))
    if spy_wk is not None and not spy_wk.empty:
        spy_mask = (spy_wk.index >= nav.index[0]) & (spy_wk.index <= nav.index[-1])
        spy_seg = spy_wk[spy_mask]["Close"].astype(float).dropna()
        if len(spy_seg) >= 2:
            spy_pct = (spy_seg / float(spy_seg.iloc[0]) - 1) * 100
            fig.add_trace(go.Scatter(
                x=spy_pct.index, y=spy_pct.values,
                mode="lines", name="SPY",
                line=dict(color="#888", width=1.5, dash="dot"),
            ))
    fig.update_layout(
        title=title,
        xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="累计收益率 (%)", ticksuffix="%",
            gridcolor="rgba(100,100,100,0.3)",
        ),
        height=480, margin=dict(l=10, r=10, t=44, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=13),
        showlegend=True,
    )
    return fig
