from __future__ import annotations

import math
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import streamlit as st
from _yf_session import new_yf_session

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
    h = yf.Ticker(ticker, session=new_yf_session()).history(period="5y")
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
    h = yf.Ticker(ticker, session=new_yf_session()).history(start="2021-06-01")
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
    """'2026-05' + k 个月 → '2026-06'。去 look-ahead 用：M 月末信号落到 M+k 月桶，
    该桶首个交易日（即信号日的次交易日）开盘执行。"""
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
        slots = slot_assignments.get(m, [])
        tk = slots[slot_idx] if slot_idx < len(slots) else None
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

    shift_months：M 月末信号落到 M+N 月桶执行，去 look-ahead（M 的排名用截至 M 月末
    数据算，只能在 M 月末的次交易日进场，正好是 M+N 月桶的首个交易日）。
    slot_assignments / gate_closed 的 key 随之顺延，下游窗口（月初→月末）自然落在执行月。
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


def blend_relay_scores(
    rs_month_by_w: dict,
    adv_month: pd.DataFrame,
    mom_windows: list,
    blend: str = "zavg",
    score_basis: str = "momentum",
    cap_weight: float = 0.8,
) -> pd.DataFrame:
    """王朝接力净值实验台的打分层：多窗口动量 blend + 口径切换，横截面在传入的
    选仓池（columns）内做。返回月×板块 score（越大越强），供选仓层排名。

    rs_month_by_w: {window: 月×板块 原始 RS DataFrame}（已 resample("ME").last()）。
    adv_month:     月×板块 ADV_63d（king_score 容量项用）。
    mom_windows:   选中的动量窗口列表（63/126/252/504）。
    blend:         'zavg'（各窗口横截面 Z 后平均）/ 'borda'（各窗口名次平均）。
    score_basis:   'momentum'（纯动量）/ 'king_score'（动量 Z + cap_weight×Z(log10 ADV)）。
    """
    wins = [w for w in mom_windows if w in rs_month_by_w and not rs_month_by_w[w].empty]
    if not wins:
        return pd.DataFrame()

    def _xs_z(df: pd.DataFrame) -> pd.DataFrame:
        return df.sub(df.mean(axis=1), axis=0).div(
            df.std(axis=1).replace(0, np.nan), axis=0
        )

    if blend == "borda":
        rank_acc = None
        for w in wins:
            rk = rs_month_by_w[w].rank(axis=1, ascending=True)  # 越大 RS 名次越高=越强
            rank_acc = rk if rank_acc is None else rank_acc.add(rk, fill_value=np.nan)
        mom = _xs_z(rank_acc / len(wins))  # 平均名次再标准化，越大越强
    else:  # zavg
        z_acc = None
        for w in wins:
            z = _xs_z(rs_month_by_w[w].astype(float))
            z_acc = z if z_acc is None else z_acc.add(z, fill_value=np.nan)
        mom = z_acc / len(wins)

    if score_basis == "king_score":
        mom_z = _xs_z(mom)
        adv = adv_month.reindex(index=mom.index, columns=mom.columns).astype(float)
        log_adv = np.log10(adv.where(adv > 0))
        adv_z = _xs_z(log_adv)
        score = mom_z + cap_weight * adv_z
        # 缺 ADV 的票（如 D-ext 早期）退回纯动量分，不整月被丢出排名
        score = score.where(score.notna(), mom_z)
        return score
    return mom


def select_relay_holdings(
    score_m: pd.DataFrame,
    n_holdings: int = 2,
    gate: str = "seniority",
    guard: str = "buffer",
    buffer_n: int = 4,
    k_delta: float = 1.0,
    shift_months: int = 1,
) -> dict:
    """王朝接力净值实验台选仓层：进场门槛 + 守擂机制参数化，产出每月 N 票持仓。
    返回 {执行月: [tickers]}（已顺延 shift_months 去 look-ahead）。

    gate:  'seniority'（现状：新进场须当月前3 + 近6月进前3次数排序）/ 'pure'（纯 TopN by score）。
    guard: 'buffer'（名次死区，在任票掉出前 buffer_n 才换）/ 'delta'（分差死区，在任票分数
           低于「第N名门槛 − k_delta×当月横截面σ」才换）/ 'none'（每月直接换 TopN）。
    """
    if score_m.empty or len(score_m) < 2:
        return {}
    n = max(1, int(n_holdings))
    rank_m = score_m.rank(axis=1, ascending=False, method="min")
    ten6 = (rank_m <= 3).astype(int).rolling(6, min_periods=1).sum()
    mh: dict = {}
    prev: list = []
    for ts, row in score_m.iterrows():
        s = row.dropna()
        if s.empty:
            continue
        order = s.sort_values(ascending=False).index.tolist()  # 分高在前
        rk = rank_m.loc[ts]
        if gate == "pure":
            elig_sorted = order[:]
        else:  # seniority
            tnow = ten6.loc[ts]
            elig = [t for t in order if rk.get(t, 99) <= 3]
            elig_sorted = sorted(elig, key=lambda t: (-float(tnow.get(t, 0)), rk.get(t, 99)))
        # 守擂：决定上月持仓哪些留任
        if not prev or guard == "none":
            hold: list = []
        elif guard == "delta":
            thresh = float(s[order[n - 1]]) if len(order) >= n else float(s.min())
            sigma = float(s.std()) if len(s) > 1 else 0.0
            keep_line = thresh - float(k_delta) * sigma
            hold = [t for t in prev if t in s.index and float(s[t]) >= keep_line][:n]
        else:  # buffer
            tN = set(order[:buffer_n])
            hold = [t for t in prev if t in tN][:n]
        # 补足空槽：先够格池，再兜底原始 order
        for t in elig_sorted:
            if len(hold) >= n:
                break
            if t not in hold:
                hold.append(t)
        if len(hold) < n:
            for t in order:
                if len(hold) >= n:
                    break
                if t not in hold:
                    hold.append(t)
        hold = hold[:n]
        exec_m = next_month_key(ts.strftime("%Y-%m"), shift_months)
        mh[exec_m] = hold
        prev = hold
    return mh


def relay_turnover_stats(monthly_holdings: dict) -> dict:
    """从 {执行月: [tickers]} 算换股次数 / 年均换手 / 平均持有月数（口径对齐动量双龙统计卡）。
    换股次数 = 相邻月新增标的数之和；年均换手 = 平均每月换手率×12；
    平均持有月数 = 总持仓槽月 / 段数（一段 = 同一标的连续持有）。
    """
    months = sorted(monthly_holdings)
    if len(months) < 2:
        return {"n_swaps": 0, "ann_turnover": 0.0, "avg_hold_months": 0.0}
    n_swaps = 0
    turns: list = []
    prev: set = set()
    for m in months:
        cur = {t for t in monthly_holdings.get(m, []) if t and t != "CASH"}
        if prev:
            added = cur - prev
            n_swaps += len(added)
            denom = max(len(cur), len(prev), 1)
            turns.append(len(added) / denom)
        prev = cur
    ann_turnover = float(np.mean(turns)) * 12 if turns else 0.0
    # 平均持有月数：按标的追踪连续段
    seg_count = 0
    slot_months = 0
    for m in months:
        cur = [t for t in monthly_holdings.get(m, []) if t and t != "CASH"]
        slot_months += len(cur)
    # 段数：每个标的的连续持有段
    all_tks = {t for m in months for t in monthly_holdings.get(m, []) if t and t != "CASH"}
    for tk in all_tks:
        held_prev = False
        for m in months:
            held = tk in (monthly_holdings.get(m, []) or [])
            if held and not held_prev:
                seg_count += 1
            held_prev = held
    avg_hold = (slot_months / seg_count) if seg_count else 0.0
    return {
        "n_swaps": n_swaps,
        "ann_turnover": ann_turnover,
        "avg_hold_months": round(avg_hold, 1),
    }


def build_basket_slot_assignments(monthly_holdings: dict, months: list) -> dict:
    """把篮子月度持仓 {month: [top1, top2, ...]} 拆成槽位分配，供拼接图用。
    无守擂缓冲，但保持槽位连续：上月在该槽的标的若本月仍持有就留原槽，
    避免同一篮子顺序变化时左右列来回跳。空仓月填 CASH。
    """
    slot_assignments: dict = {}
    max_slots = max(2, max((len([t for t in monthly_holdings.get(m, []) if t]) for m in months), default=0))
    prev_slots: list = [None] * max_slots
    for m in months:
        basket = [t for t in monthly_holdings.get(m, []) if t]
        if not basket:
            slot_assignments[m] = ["CASH"] * max_slots
            prev_slots = [None] * max_slots
            continue
        new_slots: list = [None] * max_slots
        assigned: set = set()
        for si in range(max_slots):
            if prev_slots[si] and prev_slots[si] in basket:
                new_slots[si] = prev_slots[si]
                assigned.add(prev_slots[si])
        for t in basket:
            if t in assigned:
                continue
            for si in range(max_slots):
                if new_slots[si] is None:
                    new_slots[si] = t
                    assigned.add(t)
                    break
        slot_assignments[m] = [t if t else "CASH" for t in new_slots]
        prev_slots = new_slots
    return slot_assignments


def dynasty_relay_slots(dyn_ts: dict, groups: list = None, buffer_n: int = 4):
    """从 dynasty 时序算王朝接力「左列/右列」每月实际持仓，与板块王朝页 king_score
    接力完全同源（月末 king_score 横截面 rank → 进前 3 才够格 → 资历排序 → 守擂缓冲
    → 顺延 1 月执行）。返回 (slot_assignments, name_map, exec_months)。
    slot_assignments: {exec_month: [左列ticker, 右列ticker]}（空槽为 'CASH'）。
    """
    tickers = dyn_ts.get("tickers", {}) or {}
    dates = dyn_ts.get("dates", []) or []
    if groups:
        picked = {tk: p for tk, p in tickers.items() if p.get("group", "") in groups}
    else:
        picked = dict(tickers)
    if not picked or not dates:
        return {}, {}, []
    idx = pd.to_datetime(dates, errors="coerce")
    king = pd.DataFrame(
        {tk: p.get("king_score", []) for tk, p in picked.items()}, index=idx
    ).astype(float)
    name_map = {tk: p.get("name", tk) for tk, p in picked.items()}
    king_m = king.resample("ME").last()
    if king_m.empty or len(king_m) < 2:
        return {}, name_map, []

    rank_m = king_m.rank(axis=1, ascending=False, method="min")
    ten6 = (rank_m <= 3).astype(int).rolling(6, min_periods=1).sum()
    mh: dict = {}
    prev_h: list = []
    for ts, row in rank_m.iterrows():
        r = row.dropna().sort_values()
        if r.empty:
            continue
        order = r.index.tolist()
        tN = set(order[:buffer_n])
        tnow = ten6.loc[ts]
        elig = [t for t in order if r[t] <= 3]
        elig_t = sorted(elig, key=lambda t: (-float(tnow.get(t, 0)), r[t]))
        hold = [t for t in prev_h if t in tN][:2] if prev_h else []
        for t in elig_t:
            if len(hold) >= 2:
                break
            if t not in hold:
                hold.append(t)
        if len(hold) < 2:
            for t in order:
                if len(hold) >= 2:
                    break
                if t not in hold:
                    hold.append(t)
        exec_m = next_month_key(ts.strftime("%Y-%m"), 1)
        mh[exec_m] = hold
        prev_h = hold
    exec_months = sorted(mh)
    if not exec_months:
        return {}, name_map, []
    slots = build_basket_slot_assignments(mh, exec_months)
    return slots, name_map, exec_months


def build_relay_gantt(
    slot_assignments: dict, exec_months: list, name_map: dict = None,
    title: str = "王朝接力左右列时间条带",
) -> go.Figure:
    """把左右列每月持仓画成甘特时间条带：两条轨道（左列/右列），每段连续持有同一板块
    = 一个色带，带上标中文名 + 代码。"""
    nm = name_map if name_map is not None else {}
    fig = go.Figure()

    tks: list = []
    for m in exec_months:
        for t in slot_assignments.get(m, []):
            if t and t != "CASH" and t not in tks:
                tks.append(t)
    color_map = {t: SLOT_COLORS[i % len(SLOT_COLORS)] for i, t in enumerate(tks)}

    tracks = [(0, 1.0), (1, 0.0)]
    for slot_idx, yc in tracks:
        for tk, s_m, e_m in build_slot_segments(slot_assignments, slot_idx, exec_months):
            x0 = pd.Timestamp(f"{s_m}-01")
            x1 = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
            if not tk or tk == "CASH":
                fillc, label = "#2a2a2a", "空仓"
            else:
                fillc = color_map.get(tk, "#888")
                label = f"{nm.get(tk, tk)}<br>{tk}"
            fig.add_shape(
                type="rect", x0=x0, x1=x1, y0=yc - 0.4, y1=yc + 0.4,
                fillcolor=fillc, opacity=0.9, line=dict(width=1, color="#111"),
                layer="below",
            )
            xmid = x0 + (x1 - x0) / 2
            fig.add_annotation(
                x=xmid, y=yc, text=label, showarrow=False,
                font=dict(size=10, color="#fff"),
            )
    fig.update_layout(
        height=240,
        margin=dict(l=80, r=20, t=44, b=24),
        plot_bgcolor="#111111", paper_bgcolor="#111111",
        font=dict(color="#ddd"),
        title=dict(text=title, font=dict(size=14), x=0.01, xanchor="left"),
        showlegend=False,
    )
    fig.update_yaxes(
        tickvals=[1.0, 0.0], ticktext=["左列 · 龙头", "右列 · 次龙头"],
        range=[-0.6, 1.6], showgrid=False, zeroline=False,
    )
    if exec_months:
        x0 = pd.Timestamp(f"{exec_months[0]}-01")
        x1 = pd.Timestamp(f"{exec_months[-1]}-01") + pd.offsets.MonthEnd(1)
        fig.update_xaxes(
            type="date", range=[x0, x1], showgrid=True, gridcolor="#222",
        )
    else:
        fig.update_xaxes(type="date", showgrid=True, gridcolor="#222")
    return fig


def build_stitched_fig(
    segs: list, slot_name: str,
    spy_wk: pd.DataFrame = None,
    price_cache: dict = None,
    name_map: dict = None,
    grade_map: dict = None,
    danger_daily: pd.Series = None,
    danger_half_daily: pd.Series = None,
) -> go.Figure:
    pc = price_cache if price_cache is not None else {}
    nm = name_map if name_map is not None else {}
    gm = grade_map if grade_map is not None else {}
    fig = go.Figure()
    x_offset = 0
    tick_vals: list = []
    tick_texts: list = []
    boundary_xs: list = []
    name_annotations: list = []
    running_nav = 1.0
    spy_close = (
        spy_wk["Close"].astype(float).dropna()
        if spy_wk is not None and not spy_wk.empty
        else None
    )
    spy_x_all: list = []
    spy_y_all: list = []
    spy_running_nav = 1.0

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
                        x=x_vals, y=[max(0.001, running_nav)] * n,
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
                            spy_nav = (spy_seg / float(spy_seg.iloc[0])) * spy_running_nav
                            for si, sdt in enumerate(cash_idx):
                                if sdt in spy_seg.index:
                                    spy_x_all.append(x_offset + si)
                                    spy_y_all.append(max(0.001, float(spy_nav.loc[sdt])))
                            spy_running_nav = float(spy_nav.iloc[-1])
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
        # 熊市防御：清仓 bar 收益换现金(年化4%)净值走平，减半 bar 换 0.5×个股+0.5×现金，
        # 其余 bar 照旧跟随个股。cumprod(pct_change) 起点等于 running_nav，与原口径一致。
        _state = None  # 0=满仓 1=减仓一半 2=清仓
        if danger_daily is not None or danger_half_daily is not None:
            _cash_wr = 1.04 ** (1.0 / 52) - 1.0
            _dg = (danger_daily.reindex(closes.index, method="ffill").fillna(False).astype(bool)
                   if danger_daily is not None else pd.Series(False, index=closes.index))
            _dh = (danger_half_daily.reindex(closes.index, method="ffill").fillna(False).astype(bool)
                   if danger_half_daily is not None else pd.Series(False, index=closes.index))
            _dh = _dh & ~_dg
            _seg_ret = closes.pct_change()
            _seg_ret = _seg_ret.where(~_dh, 0.5 * _seg_ret + 0.5 * _cash_wr)
            _seg_ret = _seg_ret.where(~_dg, _cash_wr).fillna(0.0)
            seg_nav = running_nav * (1.0 + _seg_ret).cumprod()
            _state = pd.Series(0, index=closes.index)
            _state[_dh] = 1
            _state[_dg] = 2
        else:
            seg_nav = (closes / float(closes.iloc[0])) * running_nav

        _y_vals = [max(0.001, v) for v in seg_nav]
        if _state is not None and int((_state != 0).sum()) > 0:
            # 按防御状态切成连续小段：满仓 = 槽色实线，减仓一半 = 白实线，清仓 = 白虚线。
            # 每小段起点接前一个点，保持线条连续。
            _runs = []
            _run_start = 0
            for _i in range(1, n + 1):
                if _i == n or int(_state.iloc[_i]) != int(_state.iloc[_run_start]):
                    _runs.append((_run_start, _i, int(_state.iloc[_run_start])))
                    _run_start = _i
            _LINE_BY_STATE = {
                0: dict(color=color, width=2),
                1: dict(color="#FFFFFF", width=2),
                2: dict(color="#FFFFFF", width=2, dash="dash"),
            }
            for _rs, _re, _stv in _runs:
                _lo = max(0, _rs - 1)
                fig.add_trace(go.Scatter(
                    x=x_vals[_lo:_re], y=_y_vals[_lo:_re], mode="lines",
                    line=_LINE_BY_STATE[_stv],
                    name=f"{tk}（{s_m}→{e_m}）",
                    showlegend=False,
                ))
        else:
            fig.add_trace(go.Scatter(
                x=x_vals, y=_y_vals, mode="lines",
                line=dict(color=color, width=2),
                name=f"{tk}（{s_m}→{e_m}）",
                showlegend=False,
            ))
        running_nav = float(seg_nav.iloc[-1])

        if spy_close is not None:
            spy_seg = spy_close.reindex(closes.index, method="ffill").bfill().dropna()
            if len(spy_seg) >= 2:
                spy_nav = (spy_seg / float(spy_seg.iloc[0])) * spy_running_nav
                for si, sdt in enumerate(closes.index):
                    if sdt in spy_seg.index:
                        spy_x_all.append(x_offset + si)
                        spy_y_all.append(max(0.001, float(spy_nav.loc[sdt])))
                spy_running_nav = float(spy_nav.iloc[-1])

        tick_vals.append(x_offset + n // 2)
        tick_texts.append(f"{s_m}→{e_m}")
        _g = gm.get(tk, "")
        _ann_text = f"{tk}({_g})" if _g else tk
        name_annotations.append(dict(
            x=x_offset + n // 2, y=1.0,
            xref="x", yref="paper",
            text=_ann_text, showarrow=False,
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
            name=f"SPY 同期 {(spy_running_nav - 1) * 100:+.1f}%",
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
            title="NAV（对数，1.0 = 起始）",
            type="log",
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
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
    """等权 top_n 篮子，次交易日开盘买入（去 look-ahead）。

    决策月 M 的篮子（用截至 M 月末数据算的排名）在 M+shift_months 月桶进场，
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


def build_nav_from_holdings(
    monthly_holdings: dict,
    price_cache_daily: dict,
    spy_daily: pd.DataFrame,
    top_n: int | None = 1,
    cash_rate: float = 0.04,
    cost_bps: float = 10.0,
) -> dict:
    """日线净值：每个执行月首个交易日 Open 买入、持有到月末 Close，按换手只数扣单边 cost_bps。
    持仓直接吃 monthly_holdings（外部已带 δ 守擂 + 进场门槛选好），内部不再选仓。
    返回 {"nav"(日线 Series), "nav_wk"(周线 Series 供 KPI), "total_ret", "max_dd"}。
    """
    months = sorted(monthly_holdings)
    empty = {"nav": pd.Series(dtype=float), "nav_wk": pd.Series(dtype=float),
             "total_ret": 0.0, "max_dd": 0.0}
    if not months or spy_daily is None or spy_daily.empty:
        return empty
    cal = spy_daily.index
    running_nav = 1.0
    nav_parts: list = []
    prev: list = []
    prev_slot_count = 0
    for m in months:
        raw_basket = [t for t in monthly_holdings.get(m, []) if t]
        if top_n is None:
            slots = raw_basket or ["CASH"]
            slot_count = max(1, len(slots))
        else:
            slot_count = max(1, int(top_n))
            slots = (raw_basket + ["CASH"] * max(slot_count - len(raw_basket), 0))[:slot_count]
        basket = [t for t in slots if t != "CASH"]
        sd = pd.Timestamp(f"{m}-01")
        ed = sd + pd.offsets.MonthEnd(1)
        day_idx = cal[(cal >= sd) & (cal <= ed)]
        traded = len(set(prev) ^ set(basket))
        cost_denom = max(prev_slot_count, slot_count, 1)
        if cost_bps and traded and len(day_idx) >= 1:
            running_nav *= max(0.0, 1.0 - (traded / cost_denom) * cost_bps / 10000.0)
        prev = basket
        prev_slot_count = slot_count
        if not basket or len(day_idx) < 1:
            if len(day_idx) >= 1:
                days = (day_idx - day_idx[0]).days.to_numpy()
                part = pd.Series(running_nav * (1.0 + cash_rate) ** (days / 365.0),
                                 index=day_idx, dtype=float)
                nav_parts.append(part)
                running_nav = float(part.iloc[-1])
            continue
        valid_paths: list = []
        days = (day_idx - day_idx[0]).days.to_numpy()
        cash_path = pd.Series((1.0 + cash_rate) ** (days / 365.0), index=day_idx, dtype=float)
        for tk in slots:
            if tk == "CASH":
                valid_paths.append(cash_path)
                continue
            d = price_cache_daily.get(tk)
            if d is None or d.empty:
                valid_paths.append(cash_path)
                continue
            win = d[(d.index >= sd) & (d.index <= ed)]
            if len(win) < 2:
                valid_paths.append(cash_path)
                continue
            entry = float(win["Open"].iloc[0])
            if entry <= 0:
                valid_paths.append(cash_path)
                continue
            path = (win["Close"].astype(float) / entry).reindex(day_idx, method="ffill").bfill()
            valid_paths.append(path)
        if not valid_paths:
            days = (day_idx - day_idx[0]).days.to_numpy()
            part = pd.Series(running_nav * (1.0 + cash_rate) ** (days / 365.0),
                             index=day_idx, dtype=float)
            nav_parts.append(part)
            running_nav = float(part.iloc[-1])
            continue
        seg = pd.concat(valid_paths, axis=1).mean(axis=1) * running_nav
        running_nav = float(seg.iloc[-1])
        nav_parts.append(seg)
    if not nav_parts:
        return empty
    nav = pd.concat(nav_parts).sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    nav_wk = nav.resample("W-FRI").last().dropna()
    total_ret = (float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100
    peak = nav.cummax()
    max_dd = float(((peak - nav) / peak.replace(0, float("nan"))).max()) * 100
    return {"nav": nav, "nav_wk": nav_wk, "total_ret": total_ret, "max_dd": max_dd}


def _as_close_series(x) -> pd.Series:
    """spy_daily 在各页面里传入格式不统一（Series 或带 Close 列的 OHLCV DataFrame），
    统一取出收盘价 Series，供执行层日频规则 / 甘特+NAV 组合图使用。"""
    if x is None:
        return pd.Series(dtype=float)
    if isinstance(x, pd.DataFrame):
        return x["Close"].astype(float).dropna() if "Close" in x.columns else pd.Series(dtype=float)
    return x.astype(float).dropna()


def _rule_active(close: pd.Series, kind: str, param: int, ma_reentry: pd.Series) -> tuple:
    """执行层价格规则（照搬 valuation-radar/backtest_a_leg_round10.py 的 _rule_active，
    逻辑一比一，不重新设计）。返回 (active bool Series, entry_cnt, exit_cnt)。
    已 shift(1) 去 look-ahead：第 t 日仓位由 t-1 日收盘信号决定，段起点默认进场。"""
    close = close.dropna()
    if len(close) < 2:
        return pd.Series(True, index=close.index), 0, 0
    if kind == "MA":
        ma = close.rolling(param).mean()
        sig = (close >= ma)
        sig = sig.where(ma.notna(), True)   # MA 未 warmup 时默认在场
    else:  # DD：距持有期高点回撤 > param% 出场，收盘回 ma_reentry 上方买回
        m100 = ma_reentry.reindex(close.index)
        vals = close.to_numpy()
        m100v = m100.to_numpy()
        n = len(vals)
        act = np.ones(n, dtype=bool)
        high = vals[0]
        holding = True
        thr = param / 100.0
        for i in range(n):
            if holding:
                high = max(high, vals[i])
                if vals[i] < high * (1.0 - thr):
                    holding = False
                    act[i] = False
                else:
                    act[i] = True
            else:
                # 收盘回买回门上方买回（MA 缺失时也允许买回，避免早期段永久空仓）
                if np.isnan(m100v[i]) or vals[i] >= m100v[i]:
                    holding = True
                    high = vals[i]
                    act[i] = True
                else:
                    act[i] = False
        sig = pd.Series(act, index=close.index)
    sig = sig.shift(1).fillna(True).astype(bool)
    trans = sig.astype(int).diff().fillna(0)
    entry_cnt = int((trans == 1).sum())
    exit_cnt = int((trans == -1).sum())
    return sig, entry_cnt, exit_cnt


def build_nav_from_daily_positions(
    segs: list,
    daily_close_cache: dict,
    spy_daily: pd.Series,
    rule: dict,
    cash_rate: float = 0.04,
    reentry_ma_cache: dict = None,
) -> dict:
    """选股层推荐区间（一个槽）→ 执行层日频价格规则进出场 → 日线 NAV。
    照搬 valuation-radar/backtest_a_leg_round10.py 的 execute_slot()，逻辑不重新设计。
    segs: [(ticker_or_CASH, 起始月, 结束月), ...]（hv.build_slot_segments 的输出）。
    rule: {"kind": "MA"|"DD", "param": int, "reentry_ma": int（DD 族买回门窗口，默认100）}。
    reentry_ma_cache: DD 族买回门用——{ticker: 该票全历史 rolling(reentry_ma).mean()}，
        对齐 round10 execute() 里 ma100 是按全历史算好一次再按段 reindex，不是段内现算
        （段内现算会让每段前 ~reentry_ma 天买回门形同虚设，回撤止损组合 DD 明显失真）。
        不传时退化为段内现算（MA 族本就该段内算，行为不受影响）。
    返回 {"nav": 日线 Series, "positions": 逐日 bool Series（True=在场）,
          "entries": int, "exits": int,
          "events": [(日期, ticker, "entry"|"exit"), ...]（区间内实际进出场，供持仓表用）}。
    """
    _spy_close = _as_close_series(spy_daily)
    cal = _spy_close.index if not _spy_close.empty else None
    reentry_win = int(rule.get("reentry_ma", 100))
    cash_dr = (1.0 + cash_rate) ** (1.0 / 365.0) - 1.0
    running = 1.0
    nav_parts, pos_parts, events = [], [], []
    ent = exo = 0
    for tk, s_m, e_m in segs:
        sd = pd.Timestamp(f"{s_m}-01")
        ed = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
        widx = cal[(cal >= sd) & (cal <= ed)] if cal is not None else pd.DatetimeIndex([])
        if len(widx) < 1:
            continue
        close = daily_close_cache.get(tk) if tk and tk != "CASH" else None
        if tk == "CASH" or close is None or close.empty:
            days = (widx - widx[0]).days.to_numpy()
            part = running * (1.0 + cash_rate) ** (days / 365.0)
            nav_parts.append(pd.Series(part, index=widx))
            pos_parts.append(pd.Series(False, index=widx))
            running = float(nav_parts[-1].iloc[-1])
            continue
        px = close.reindex(widx).ffill()
        if px.dropna().shape[0] < 2:
            days = (widx - widx[0]).days.to_numpy()
            part = running * (1.0 + cash_rate) ** (days / 365.0)
            nav_parts.append(pd.Series(part, index=widx))
            pos_parts.append(pd.Series(False, index=widx))
            running = float(nav_parts[-1].iloc[-1])
            continue
        if reentry_ma_cache is not None and tk in reentry_ma_cache:
            ma_reentry = reentry_ma_cache[tk].reindex(widx)
        else:
            ma_reentry = px.rolling(reentry_win).mean()
        act, _, _ = _rule_active(px, rule["kind"], int(rule["param"]), ma_reentry)
        act = act.reindex(widx).ffill().fillna(True).astype(bool)
        trans = act.astype(int).diff().fillna(0)
        ent += int((trans == 1).sum())
        exo += int((trans == -1).sum())
        for dt in trans.index[trans == 1]:
            events.append((dt, tk, "entry"))
        for dt in trans.index[trans == -1]:
            events.append((dt, tk, "exit"))
        stock_ret = px.pct_change().fillna(0.0)
        day_ret = np.where(act.to_numpy(), stock_ret.to_numpy(), cash_dr)
        nav = running * np.cumprod(1.0 + day_ret)
        nav_parts.append(pd.Series(nav, index=widx))
        pos_parts.append(act)
        running = float(nav[-1])
    if not nav_parts:
        return {"nav": pd.Series(dtype=float), "positions": pd.Series(dtype=bool),
                "entries": 0, "exits": 0, "events": []}
    nav = pd.concat(nav_parts).sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    positions = pd.concat(pos_parts).sort_index()
    positions = positions[~positions.index.duplicated(keep="last")]
    events.sort(key=lambda e: e[0])
    return {"nav": nav, "positions": positions, "entries": ent, "exits": exo, "events": events}


def build_slot_gantt_nav_fig(
    segs: list,
    positions: pd.Series,
    nav: pd.Series,
    spy_daily: pd.Series,
    slot_name: str,
    name_map: dict = None,
    grade_map: dict = None,
) -> go.Figure:
    """单图：顶部按自己颜色的文字标签标注每段推荐票（同 build_stitched_fig 风格），
    股票名字那行用小竖杠分隔换股边界、边界上方标换股日期；下方 NAV 按「当前持有票」
    的颜色着色（空仓灰虚线），段内视觉降采样到周频，但每段起止两端仍保留精确到日
    的真实数据点；实际进出场（执行层日频规则触发，可能早于/晚于换股边界）不画三角，
    只在图底部标精确日期。大盘 SPY 同期线同样降到周频。
    segs: [(ticker_or_CASH, 起始月, 结束月), ...]（推荐区间，hv.build_slot_segments 输出）。
    positions: build_nav_from_daily_positions 返回的逐日 bool Series（True=在场）。
    nav: 同一槽的日线 NAV Series。
    """
    nm = name_map or {}
    gm = grade_map or {}
    fig = go.Figure()
    tks = [tk for tk, _, _ in segs if tk and tk != "CASH"]
    color_map = {t: SLOT_COLORS[i % len(SLOT_COLORS)] for i, t in enumerate(dict.fromkeys(tks))}

    seg_bounds: list = []  # (x0, x1, ticker_or_"")；""=空仓（不用 None，避免 pandas 把 None
    # 和字符串混列时悄悄转成 float nan，导致 nan != nan 把连续空仓切成逐日碎段）
    for tk, s_m, e_m in segs:
        x0 = pd.Timestamp(f"{s_m}-01")
        x1 = pd.Timestamp(f"{e_m}-01") + pd.offsets.MonthEnd(1)
        seg_bounds.append((x0, x1, "" if (not tk or tk == "CASH") else tk))

    annotations: list = []
    shapes: list = []
    for i, (x0, x1, tk) in enumerate(seg_bounds):
        if not tk:
            color, label = "#999", "💰 空仓"
        else:
            color = color_map.get(tk, "#888")
            g = gm.get(tk, "")
            label = f"{nm.get(tk, tk)}({g})" if g else nm.get(tk, tk)
        _mid = (x0 + (x1 - x0) / 2).to_pydatetime()
        annotations.append(dict(
            x=_mid, y=1.15, xref="x", yref="paper",
            text=label, showarrow=False,
            font=dict(size=12, color=color), xanchor="center", yanchor="bottom",
        ))
        if i > 0:
            _bx = x0.to_pydatetime()
            # 换股边界：竖杠跟股票名字同一高度（都在 1.0~1.2 这个头部区间内），
            # 边界正上方标精确换股日期
            shapes.append(dict(
                type="line", xref="x", yref="paper",
                x0=_bx, x1=_bx, y0=1.0, y1=1.2,
                line=dict(color="rgba(200,200,200,0.6)", width=1),
            ))
            annotations.append(dict(
                x=_bx, y=1.0, xref="x", yref="paper",
                text=x0.strftime("%Y-%m-%d"), showarrow=False,
                font=dict(size=9, color="#999"), xanchor="left", yanchor="bottom",
                textangle=-40,
            ))

    _y_all: list = []  # 收集全部实际画出的 y 值，用于固定 log 轴 range（下方引导线要精确打到轴底）
    if nav is not None and not nav.empty:
        nav_rel = nav.astype(float) / float(nav.iloc[0])
        pos = (
            positions.reindex(nav_rel.index).fillna(False).astype(bool)
            if positions is not None and not positions.empty
            else pd.Series(True, index=nav_rel.index)
        )

        # 每天所处的推荐段票（段之间首尾相接，取「最近一个已开始的段」）
        _starts = np.array([b[0].value for b in seg_bounds]) if seg_bounds else np.array([])
        _tk_by_start = [b[2] for b in seg_bounds]
        if len(_starts):
            _day_ns = nav_rel.index.values.astype("datetime64[ns]").astype("int64")
            _pos_idx = np.clip(np.searchsorted(_starts, _day_ns, side="right") - 1, 0, len(_tk_by_start) - 1)
            seg_tk_of_day = pd.Series([_tk_by_start[i] for i in _pos_idx], index=nav_rel.index)
        else:
            seg_tk_of_day = pd.Series([""] * len(nav_rel), index=nav_rel.index)
        # 着色状态：在场 = 该段票自己的颜色；空仓/未在场 = ""（灰虚线）
        _seg_tk_list = seg_tk_of_day.tolist()
        _pos_list = pos.tolist()
        _keys = [tk if ok else "" for tk, ok in zip(_seg_tk_list, _pos_list)]
        n = len(_keys)
        runs, run_start = [], 0
        for i in range(1, n + 1):
            if i == n or _keys[i] != _keys[run_start]:
                runs.append((run_start, i, _keys[run_start]))
                run_start = i

        for rs, re_, tkv in runs:
            lo = max(0, rs - 1)  # 接上前一点，保持折线连续
            run_idx = nav_rel.index[lo:re_]
            run_val = nav_rel.iloc[lo:re_]
            if len(run_idx) == 0:
                continue
            _pts = run_val.resample("W-FRI").last().dropna()
            _pts.loc[run_idx[0]] = run_val.iloc[0]
            _pts.loc[run_idx[-1]] = run_val.iloc[-1]
            _pts = _pts[~_pts.index.duplicated(keep="last")].sort_index()
            _y = [max(0.001, v) for v in _pts.values]
            _y_all.extend(_y)
            _line = (
                dict(color="#888", width=1.5, dash="dash") if not tkv
                else dict(color=color_map.get(tkv, "#888"), width=2)
            )
            fig.add_trace(go.Scatter(x=_pts.index, y=_y, mode="lines", line=_line, showlegend=False))

        _spy_close = _as_close_series(spy_daily)
        if not _spy_close.empty:
            spy_seg = _spy_close.reindex(nav_rel.index).ffill().dropna()
            if len(spy_seg) >= 2:
                spy_rel = (spy_seg / float(spy_seg.iloc[0])).resample("W-FRI").last().dropna()
                _y_all.extend(float(v) for v in spy_rel.values)
                fig.add_trace(go.Scatter(
                    x=spy_rel.index, y=spy_rel.values, mode="lines",
                    line=dict(color="rgba(180,180,180,0.4)", width=1.5, dash="dot"),
                    name=f"SPY 同期 {(float(spy_rel.iloc[-1]) - 1) * 100:+.1f}%",
                ))

        # log 轴 range 先固定下来，下方引导线才能精确打到轴底（也避免被引导线的极小值拉爆自动量程）
        y_lo = min(_y_all) * 0.85 if _y_all else 0.5
        y_hi = max(_y_all) * 1.15 if _y_all else 2.0
        _log_lo, _log_hi = float(np.log10(y_lo)), float(np.log10(y_hi))

        # 实际进出场（执行层日频规则触发）：三角标记放在下方年份刻度同一高度，
        # 用一根细引导线（图内竖线 + 图外竖线两段拼接）连回图上真正的进出场点位置，
        # 日期文字用灰色（方向靠三角颜色区分）。
        _BOTTOM_Y = -0.06
        trans = pos.astype(int).diff().fillna(0)
        entries = nav_rel.index[trans == 1]
        exits = nav_rel.index[trans == -1]
        for d, arrow, color in (
            [(d, "▲", "#2ECC71") for d in entries] + [(d, "▼", "#E74C3C") for d in exits]
        ):
            _dx = d.to_pydatetime()
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=_dx, x1=_dx, y0=float(nav_rel.loc[d]), y1=y_lo,
                line=dict(color="rgba(200,200,200,0.45)", width=1),
            ))
            shapes.append(dict(
                type="line", xref="x", yref="paper",
                x0=_dx, x1=_dx, y0=0.0, y1=_BOTTOM_Y,
                line=dict(color="rgba(200,200,200,0.45)", width=1),
            ))
            annotations.append(dict(
                x=_dx, y=_BOTTOM_Y, xref="x", yref="paper",
                text=f"<span style='color:{color}'>{arrow}</span> <span style='color:#999'>{d.strftime('%Y-%m-%d')}</span>",
                showarrow=False, font=dict(size=9), xanchor="left", yanchor="middle",
            ))
    else:
        _log_lo, _log_hi = float(np.log10(0.5)), float(np.log10(2.0))

    fig.update_layout(
        xaxis=dict(type="date", showgrid=True, gridcolor="rgba(100,100,100,0.3)", title="日期"),
        yaxis=dict(
            title="NAV（对数，1.0=起始）", type="log", range=[_log_lo, _log_hi],
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
            gridcolor="rgba(100,100,100,0.3)",
        ),
        annotations=annotations, shapes=shapes,
        height=640, margin=dict(l=10, r=10, t=100, b=90),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        showlegend=True,
    )
    return fig


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

    def _nav_rel(s: pd.Series) -> pd.Series:
        s = s.astype(float).dropna()
        return s / float(s.iloc[0]) if not s.empty else s

    # SPY 对齐到合成曲线的时间区间（最底层）
    if spy_wk is not None and not spy_wk.empty:
        sd, ed = nav_combined.index[0], nav_combined.index[-1]
        spy_seg = spy_wk[(spy_wk.index >= sd) & (spy_wk.index <= ed)]["Close"]
        spy_seg = spy_seg.astype(float).dropna()
        if len(spy_seg) >= 2:
            spy_nav = spy_seg / float(spy_seg.iloc[0])
            fig.add_trace(go.Scatter(
                x=spy_nav.index, y=spy_nav.values, mode="lines",
                name=f"SPY {(float(spy_nav.iloc[-1]) - 1) * 100:+.1f}%",
                line=dict(color="rgba(170,170,170,0.45)", width=1.5, dash="dot"),
            ))

    if not nav_l.empty:
        l_nav = _nav_rel(nav_l)
        fig.add_trace(go.Scatter(
            x=l_nav.index, y=l_nav.values, mode="lines",
            name=f"左列 Slot 0 {(float(l_nav.iloc[-1]) - 1) * 100:+.1f}%",
            line=dict(color="rgba(46,204,113,0.7)", width=1.5),
        ))
    if not nav_r.empty:
        r_nav = _nav_rel(nav_r)
        fig.add_trace(go.Scatter(
            x=r_nav.index, y=r_nav.values, mode="lines",
            name=f"右列 Slot 1 {(float(r_nav.iloc[-1]) - 1) * 100:+.1f}%",
            line=dict(color="rgba(52,152,219,0.7)", width=1.5),
        ))

    a_nav = _nav_rel(nav_combined)
    fig.add_trace(go.Scatter(
        x=a_nav.index, y=a_nav.values, mode="lines",
        name=f"A 曲线（50/50 合成） {(float(a_nav.iloc[-1]) - 1) * 100:+.1f}%",
        line=dict(color="#F1C40F", width=3),
    ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="NAV（对数，1.0 = 起始）",
            type="log",
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
            gridcolor="rgba(100,100,100,0.3)",
        ),
        height=480, margin=dict(l=10, r=10, t=44, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=13),
        showlegend=True,
    )
    return fig


def build_combined_fig_n(
    slot_navs: list,
    nav_combined: pd.Series,
    spy_wk: pd.DataFrame,
    title: str,
) -> go.Figure:
    """N 条 slot 净值 + 等权合成线 + SPY 叠加（build_combined_fig 的 2→N 泛化）。
    slot_navs: [(label, nav_series), ...]，各序列相对自身起点归一为累计收益率。
    合成线（黄）最上层，SPY（灰虚线）最底层。
    """
    fig = go.Figure()
    if nav_combined is None or nav_combined.empty:
        return fig

    def _nav_rel(s: pd.Series) -> pd.Series:
        s = s.astype(float).dropna()
        return s / float(s.iloc[0]) if not s.empty else s

    if spy_wk is not None and not spy_wk.empty:
        sd, ed = nav_combined.index[0], nav_combined.index[-1]
        spy_seg = spy_wk[(spy_wk.index >= sd) & (spy_wk.index <= ed)]["Close"]
        spy_seg = spy_seg.astype(float).dropna()
        if len(spy_seg) >= 2:
            spy_nav = spy_seg / float(spy_seg.iloc[0])
            fig.add_trace(go.Scatter(
                x=spy_nav.index, y=spy_nav.values, mode="lines",
                name=f"SPY {(float(spy_nav.iloc[-1]) - 1) * 100:+.1f}%",
                line=dict(color="rgba(170,170,170,0.45)", width=1.5, dash="dot"),
            ))

    for si, (label, nav) in enumerate(slot_navs):
        if nav is None or nav.empty:
            continue
        rel = _nav_rel(nav)
        if rel.empty:
            continue
        color = SLOT_COLORS[si % len(SLOT_COLORS)]
        fig.add_trace(go.Scatter(
            x=rel.index, y=rel.values, mode="lines",
            name=f"{label} {(float(rel.iloc[-1]) - 1) * 100:+.1f}%",
            line=dict(color=color, width=1.5),
        ))

    a_nav = _nav_rel(nav_combined)
    fig.add_trace(go.Scatter(
        x=a_nav.index, y=a_nav.values, mode="lines",
        name=f"合成（等权 {len(slot_navs)} 仓） {(float(a_nav.iloc[-1]) - 1) * 100:+.1f}%",
        line=dict(color="#F1C40F", width=3),
    ))

    fig.update_layout(
        title=title,
        xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="NAV（对数，1.0 = 起始）",
            type="log",
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
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
    nav_rel = nav.astype(float) / float(nav.iloc[0])
    fig.add_trace(go.Scatter(
        x=nav_rel.index, y=nav_rel.values,
        mode="lines", name=f"{title} {(float(nav_rel.iloc[-1]) - 1) * 100:+.1f}%",
        line=dict(color="#F1C40F", width=2),
    ))
    if spy_wk is not None and not spy_wk.empty:
        spy_mask = (spy_wk.index >= nav.index[0]) & (spy_wk.index <= nav.index[-1])
        spy_seg = spy_wk[spy_mask]["Close"].astype(float).dropna()
        if len(spy_seg) >= 2:
            spy_rel = spy_seg / float(spy_seg.iloc[0])
            fig.add_trace(go.Scatter(
                x=spy_rel.index, y=spy_rel.values,
                mode="lines", name=f"SPY {(float(spy_rel.iloc[-1]) - 1) * 100:+.1f}%",
                line=dict(color="#888", width=1.5, dash="dot"),
            ))
    fig.update_layout(
        title=title,
        xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="NAV（对数，1.0 = 起始）",
            type="log",
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
            gridcolor="rgba(100,100,100,0.3)",
        ),
        height=480, margin=dict(l=10, r=10, t=44, b=60),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30,30,30,0.6)",
        font=dict(color="#ccc", size=13),
        showlegend=True,
    )
    return fig
