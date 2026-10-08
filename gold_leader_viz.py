"""戴金龙头（21 页）/ 精选龙头（32 页）共用的渲染函数。"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from cn_names import cn_name_map

INSIGHT_CSS = """
<style>
    .insight-box { border-left: 4px solid #E74C3C; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #E74C3C; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
</style>
"""

WINDOWS = ["3Y", "5Y", "10Y"]
SLOT_LABELS = ["槽A", "槽B", "槽C", "槽D", "槽E"]


def norm_series(values, dates) -> pd.Series:
    if not values or len(values) != len(dates):
        return pd.Series(dtype=float)
    return pd.Series(values, index=dates).astype(float).dropna()


def holding_label(cell: dict | None) -> str:
    if not cell:
        return "—"
    if cell.get("bil"):
        return "BIL"
    return str(cell.get("ticker", "—") or "—")


def slot_month_segments(timeline: list[dict], slot_i: int) -> list[tuple]:
    """把某个槽的月度持仓压成 [(ticker_or_CASH, 起始月, 结束月), ...]，BIL/空档折成 CASH，
    喂给 holdings_viz.build_stitched_fig（与 22_动量双龙 / 21_科技龙头 同一套接力段渲染）。

    timeline 的 month 是决策月（后端 macro_engine 用信号月末打标签），决策月末出信号、
    次月第一个交易日才成交，所以要 next_month_key 顺延一格才对得上净值曲线——
    和 build_sector_ribbon 用 execution_date 是同一个口径。"""
    segs: list[tuple] = []
    prev = None
    s_m = None
    last_m = None
    for h in timeline:
        month = str(h.get("month", ""))
        if not month:
            continue
        month = hv.next_month_key(month)
        slots = h.get("slots", [])
        cell = slots[slot_i] if slot_i < len(slots) else None
        lab = holding_label(cell)
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


def render_time_window_slider(dates, key_prefix: str) -> tuple:
    """时间窗口滑块（拖动重设起点），供组合收益净值图和 Slot 分段图共用同一个窗口。"""
    _valid = dates.dropna()
    win_lo, win_hi = _valid.min(), _valid.max()
    if pd.notna(win_lo) and pd.notna(win_hi) and win_lo < win_hi:
        _lo_py, _hi_py = win_lo.to_pydatetime(), win_hi.to_pydatetime()
        _sel = st.slider(
            "时间窗口（拖动重设起点，组合收益净值图和下方 Slot 分段图会一起重新归一）",
            min_value=_lo_py, max_value=_hi_py, value=(_lo_py, _hi_py),
            format="YYYY-MM", key=f"{key_prefix}_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
        )
        win_lo, win_hi = pd.Timestamp(_sel[0]), pd.Timestamp(_sel[1])
    return win_lo, win_hi


def render_slot_segment_returns(slot_equity: list, timeline: list, dates,
                                spy_values: list, key_prefix: str,
                                win_lo, win_hi, shade_months: set = None,
                                ribbons: list = None, ribbon_labels: tuple = ()) -> bool:
    if not slot_equity or not timeline or len(dates) == 0:
        return False

    lo_m, hi_m = win_lo.strftime("%Y-%m"), win_hi.strftime("%Y-%m")

    spy = norm_series(spy_values, dates)
    spy = spy[(spy.index >= win_lo) & (spy.index <= win_hi)]
    spy_wk = pd.DataFrame({"Close": spy}) if not spy.empty else pd.DataFrame()

    for slot_row in slot_equity:
        slot_i = int(slot_row.get("slot", 0))
        slot_name = SLOT_LABELS[slot_i] if slot_i < len(SLOT_LABELS) else f"槽{slot_i + 1}"
        slot_s = norm_series(slot_row.get("equity", []), dates)
        slot_s = slot_s[(slot_s.index >= win_lo) & (slot_s.index <= win_hi)]
        if slot_s.empty:
            continue
        segs = slot_month_segments(timeline, slot_i)
        segs = [s for s in segs if not (s[2] < lo_m or s[1] > hi_m)]
        if not segs:
            continue
        price_cache = {tk: pd.DataFrame({"Close": slot_s}) for tk, _, _ in segs if tk != "CASH"}
        _cn = cn_name_map(tk for tk, _, _ in segs)
        fig = hv.build_stitched_fig(
            segs, f"{slot_name}接力 持仓段", spy_wk, price_cache, _cn, _cn,
            name_style="cn_ticker", shade_months=shade_months,
            ribbon=ribbons[slot_i] if ribbons and slot_i < len(ribbons) else None,
            ribbon_label=ribbon_labels[slot_i] if slot_i < len(ribbon_labels) else "",
        )
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_slot_segment_{slot_i}")
    return True


def render_holding_cards(slots: list, bil_reason: str) -> None:
    cols = st.columns(max(len(slots), 1))
    for si in range(len(slots)):
        label = SLOT_LABELS[si] if si < len(SLOT_LABELS) else f"槽{si+1}"
        data = slots[si] or {}
        with cols[si]:
            if not data or data.get("bil"):
                html = (
                    f"<div class='insight-box'><div class='insight-title'>{label}</div>"
                    f"<div style='font-size:15px;color:#bbb;'>BIL（{bil_reason}）</div></div>"
                )
            else:
                sector_txt = (
                    f"{data.get('sector_name', data.get('sector_etf', '—'))}"
                    f"({data.get('sector_etf', '—')})"
                )
                excess = data.get("excess_pct")
                excess_txt = f"{excess:+.1f}%" if isinstance(excess, (int, float)) else "—"
                if data.get("data_missing_carry"):
                    detail = f"⚠ {data.get('missing_etf')} 当月数据缺失，沿用上月持仓"
                else:
                    detail = (
                        f"板块 {sector_txt}｜龙头第 {data.get('leader_rank', '—')}｜5Y超额 {excess_txt}"
                        f"<br>首次持有 {data.get('since', '—')}｜已持有 {data.get('held_months', '—')} 月"
                    )
                if data.get("unlock_in") is not None:
                    detail += (
                        f"<br>🔒 最短持有未满，还需 {data['unlock_in']} 月才按主线换"
                        if data["unlock_in"] > 0 else "<br>✅ 已满最短持有期，可按主线换"
                    )
                html = (
                    f"<div class='insight-box'><div class='insight-title'>{label}</div>"
                    f"<div style='font-size:16px;color:#fff;font-weight:bold;'>"
                    f"{data.get('name', '')} ({data.get('ticker', '')})</div>"
                    f"<div style='font-size:14px;color:#bbb;margin-top:6px;'>{detail}</div></div>"
                )
            st.markdown(html, unsafe_allow_html=True)


def show_missing_warning(variant: dict) -> None:
    miss = variant.get("data_missing_months") or []
    if miss:
        st.warning(
            "以下月份选中的板块没有龙头候选股（数据缺失），对应槽沿用上月持仓，需要手动核实龙头："
            + "；".join(f"{m['month']} {'、'.join(m['etfs'])}" for m in miss)
        )


def build_sector_ribbon(timeline: list[dict], since_month: str) -> tuple[dict, dict, list, dict, set]:
    """把对照口径的决策月时序拼成「金牌板块 / 银牌板块」两条轨道，键是执行月
    （决策月末出信号、次月第一个交易日执行，所以要顺延一格才对得上净值曲线）。

    右列始终显示当月的银牌板块候选：真分投的月份正常上色，没分投（两个槽都买金牌
    板块龙头）的月份压暗——暗段 = 这个银牌板块当月落选，第二个槽实际买的是金牌板块
    的第 2 只龙头。少数月份后端给不出银牌候选（silver_sector_etf 为空），右列退回
    显示金牌板块，一样压暗，保证「右列亮着 = 真分投金银」这一条没有例外。
    BIL 月两列都空仓。

    开头的空仓月不画：RS 要 252 个交易日才有第一个值，窗口起点往后约一年的月份查不到
    king_score / RS，会被当成「没有戴金板块」，那段灰不是判断结果。中间的空仓月照画。"""
    slots: dict = {}
    dim: dict = {}
    name_map: dict = {}
    split_months: set = set()
    for r in timeline:
        exec_m = str(r.get("execution_date", "") or "")[:7]
        if not exec_m or exec_m < since_month:
            continue
        gold = r.get("sector_etf")
        if not gold or r.get("is_bil"):
            slots[exec_m] = ["CASH", "CASH"]
            dim[exec_m] = [False, False]
            continue
        silver = r.get("silver_sector_etf")
        split = bool(r.get("split_sectors"))
        right = silver or gold
        picks = r.get("picks") or []
        left_cash = len(picks) < 1 or picks[0] == "BIL"
        right_cash = len(picks) < 2 or picks[1] == "BIL"
        slots[exec_m] = [
            "CASH" if left_cash else gold,
            "CASH" if right_cash else right,
        ]
        dim[exec_m] = [False, (not split) and not right_cash]
        for ci in (r.get("carried_slots") or []):
            if ci in (0, 1):
                miss = (r.get("data_missing") or [gold])[0]
                slots[exec_m][ci] = "MISSING:" + miss
                dim[exec_m][ci] = False
                name_map["MISSING:" + miss] = f"⚠ 数据缺失（{miss}）"
        if split:
            split_months.add(exec_m)
        name_map[gold] = r.get("sector_name") or gold
        if silver:
            name_map[silver] = r.get("silver_sector_name") or silver
    months = sorted(slots)
    first = next((i for i, m in enumerate(months) if slots[m] != ["CASH", "CASH"]), len(months))
    months = months[first:]
    return ({m: slots[m] for m in months}, name_map, months,
            {m: dim[m] for m in months}, split_months & set(months))


def split_month_spans(split_months: set, win_lo, win_hi) -> list:
    """把「真分投金银」的执行月压成连续区间，给净值图画竖向背景条。相邻月份合并成
    一段，再裁到当前时间窗口内——vrect 会把坐标轴撑开，超出窗口的段不能留。"""
    spans: list = []
    for m in sorted(split_months):
        x0 = pd.Timestamp(f"{m}-01")
        x1 = x0 + pd.offsets.MonthEnd(1)
        if spans and x0 <= spans[-1][1] + pd.Timedelta(days=1):
            spans[-1] = (spans[-1][0], x1)
        else:
            spans.append((x0, x1))
    if win_lo is None or win_hi is None:
        return spans
    return [(max(a, win_lo), min(b, win_hi)) for a, b in spans
            if b >= win_lo and a <= win_hi]


def render_equity_chart(dates, equity: dict, series_cfg: list, chart_key: str,
                         win_lo=None, win_hi=None, shade_spans: list = None,
                         shade_color: str = "#F39C12") -> None:
    fig = go.Figure()
    for x0, x1 in (shade_spans or []):
        fig.add_vrect(x0=x0, x1=x1, fillcolor=shade_color, opacity=0.10,
                      line_width=0, layer="below")
    for key, name, color, vis_default, *_style in series_cfg:
        dash = _style[0] if _style else None
        width = _style[1] if len(_style) > 1 else (1.3 if dash else (2 if vis_default else 1.4))
        vals = equity.get(key, []) or []
        if not vals:
            continue
        s = pd.Series(vals, index=dates).astype(float).dropna()
        if s.empty:
            continue
        if win_lo is not None and win_hi is not None:
            s = s[(s.index >= win_lo) & (s.index <= win_hi)]
            if s.empty:
                continue
            s = s / s.iloc[0]
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, name=name,
            line=dict(color=color, width=width, dash=dash),
            visible=True if vis_default else "legendonly",
        ))
    fig.update_layout(
        height=420, hovermode="x unified", template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.08),
        yaxis_title="净值（对数轴）", yaxis_type="log",
        xaxis=dict(tickformat="%Y-%m-%d", hoverformat="%Y-%m-%d", tickangle=-30),
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def render_stats_cards(stats: dict) -> None:
    row_a = [
        ("总收益", f"{stats.get('cum_return', 0) * 100:.0f}%"),
        ("CAGR", f"{stats.get('cagr', 0) * 100:.0f}%"),
        ("MaxDD", f"{stats.get('max_dd', 0) * 100:.0f}%"),
        ("Calmar", f"{stats.get('calmar', 0):.2f}"),
        ("超额 vs SPY", f"{stats.get('excess_vs_spy', 0) * 100:.0f}%"),
    ]
    _r2 = stats.get("r2")
    row_b = [
        ("换股次数", f"{stats.get('n_swaps', 0)}"),
        ("平均持有(月)", f"{stats.get('avg_hold_months', 0)}"),
        ("年化换手", f"{stats.get('ann_turnover', 0):.2f}"),
        ("累计成本", f"{stats.get('cum_cost', 0) * 100:.1f}%"),
        ("Sortino", f"{stats.get('sortino', 0):.2f}"),
        ("logR²", f"{_r2:.2f}" if isinstance(_r2, (int, float)) and _r2 == _r2 else "—"),
    ]
    for row in (row_a, row_b):
        cols = st.columns(len(row))
        for mi, (label, value) in enumerate(row):
            with cols[mi]:
                st.metric(label, value)


def render_meta_captions(meta: dict, window: str) -> None:
    _notes = []
    if meta.get("pit_membership_gated"):
        _notes.append("已按逐月真实成分选股（PIT，含退市，去生存者偏差）")
    if not meta.get("bil_available"):
        _notes.append("BIL 历史缺失，BIL 持有段按现金 0 收益")
    if not meta.get("mcap_gate_applied"):
        _notes.append("市值门票产物缺失，本次未按市值前3过滤")
    st.caption(
        f"池 {meta.get('universe_size', '?')} 只 · 展示自 {meta.get('display_start', '')}"
        f" · 价格截至 {meta.get('price_as_of', '')} · "
        + ("⚠️ " + "；".join(_notes) if _notes else "数据完整")
    )
    if not meta.get("window_complete", True):
        st.caption(
            f"请求{window}｜实际约 {meta.get('actual_years', 0):.1f}Y"
            f"（{meta.get('actual_days', 0)} 个交易日）"
        )
    if meta.get("is_stale"):
        st.warning(
            f"价格数据截至 {meta.get('price_as_of', '—')}，"
            f"已落后最近收盘 {meta.get('stale_days', '—')} 个交易日；"
            "以下持仓仅代表该历史信号时点。"
        )
