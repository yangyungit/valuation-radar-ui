import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import fetch_dynasty_gold_leader

st.set_page_config(page_title="戴金龙头", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #E74C3C; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #E74C3C; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
</style>
""", unsafe_allow_html=True)

_WINDOWS = ["3Y", "5Y", "10Y"]
_SLOT_LABELS = ["槽A", "槽B", "槽C", "槽D", "槽E"]


def _norm_series(values, dates) -> pd.Series:
    if not values or len(values) != len(dates):
        return pd.Series(dtype=float)
    return pd.Series(values, index=dates).astype(float).dropna()


def _holding_label(cell: dict | None) -> str:
    if not cell:
        return "—"
    if cell.get("bil"):
        return "BIL"
    return str(cell.get("ticker", "—") or "—")


def _slot_month_segments(timeline: list[dict], slot_i: int) -> list[tuple]:
    """把某个槽的月度持仓压成 [(ticker_or_CASH, 起始月, 结束月), ...]，BIL/空档折成 CASH，
    喂给 holdings_viz.build_stitched_fig（与 13_动量双龙 / 10_科技龙头 同一套接力段渲染）。"""
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


def render_slot_segment_returns(dd: dict) -> bool:
    slot_equity = dd.get("slot_equity") or []
    timeline = dd.get("holdings_timeline") or []
    dates = pd.to_datetime(dd.get("dates", []), errors="coerce")
    if not slot_equity or not timeline or len(dates) == 0:
        return False

    _valid = dates.dropna()
    win_lo, win_hi = _valid.min(), _valid.max()
    if pd.notna(win_lo) and pd.notna(win_hi) and win_lo < win_hi:
        _lo_py, _hi_py = win_lo.to_pydatetime(), win_hi.to_pydatetime()
        _sel = st.slider(
            "分段图时间窗口（拖动重设起点，各段与 SPY 在窗口最左端对齐归一）",
            min_value=_lo_py, max_value=_hi_py, value=(_lo_py, _hi_py),
            format="YYYY-MM", key=f"gl_slot_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
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
        segs = [s for s in segs if not (s[2] < lo_m or s[1] > hi_m)]
        if not segs:
            continue
        price_cache = {tk: pd.DataFrame({"Close": slot_s}) for tk, _, _ in segs if tk != "CASH"}
        fig = hv.build_stitched_fig(
            segs, f"{slot_name}接力 持仓段", spy_wk, price_cache, {}, {},
        )
        st.plotly_chart(fig, use_container_width=True, key=f"gl_slot_segment_{slot_i}")
    return True


with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_gold_leader.clear()
        st.rerun()

st.title("🏅 戴金龙头 (Gold Dynasty Leader)")
st.caption("C组戴金板块 → 板块内王朝龙头 Top2 → 下月执行。与 12M 动量守擂不是一套方法，已从 C组双龙 拆出单独成页。")

_window = st.radio(
    "时间跨度",
    options=_WINDOWS,
    index=_WINDOWS.index("5Y"),
    horizontal=True,
    key="gl_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

st.caption(
    "**主线**：C组王朝接力图戴金板块 → 板块内王朝龙头区间超额 Top2 → 下月执行。"
    "**诚实声明**：信号**不看未来**、可执行规则模拟；股票池=**逐月真实标普500成分**"
    "（PIT，Sharadar 数据含当年被剔除/退市/收购的公司），**已去生存者偏差**。"
)

_gl_c1, _gl_c2 = st.columns([1.1, 2.0])
with _gl_c1:
    _gl_rebal = st.toggle(
        "月度等权再平衡",
        value=False,
        key="gl_rebal",
        help="每月把两个槽位重新拉回50/50；关闭时各槽位独立复利。",
    )
with _gl_c2:
    st.caption(
        "固定持有 Top2；再平衡=每月卖一点涨多的槽位、补一点涨少的槽位，"
        "重新回到两个槽位各 50%。"
    )

with st.expander("交易假设"):
    _gl_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="gl_cost",
        help="买/卖各算一次，扣在成交名义额上；影响回测净值和统计。",
    )

_gl = fetch_dynasty_gold_leader(
    window=_window, rebalance=_gl_rebal, cost_bps=float(_gl_cost),
)

if not _gl.get("success"):
    st.warning(f"⚠️ 戴金龙头回测暂不可用：{_gl.get('error', '未知错误')}")

if _gl.get("success"):
    _meta = _gl.get("meta", {})

    _notes = []
    if _meta.get("pit_membership_gated"):
        _notes.append("已按逐月真实成分选股（PIT，含退市，去生存者偏差）")
    if not _meta.get("bil_available"):
        _notes.append("BIL 历史缺失，BIL 持有段按现金 0 收益")
    if not _meta.get("rsp_available"):
        _notes.append("RSP 缺失，未画等权标普对照")
    st.caption(
        f"池 {_meta.get('universe_size', '?')} 只 · 展示自 {_meta.get('display_start', '')}"
        f" · 价格截至 {_meta.get('price_as_of', '')} · "
        + ("⚠️ " + "；".join(_notes) if _notes else "数据完整")
    )
    if not _meta.get("window_complete", True):
        st.caption(
            f"请求{_window}｜实际约 {_meta.get('actual_years', 0):.1f}Y"
            f"（{_meta.get('actual_days', 0)} 个交易日）"
        )
    if _meta.get("is_stale"):
        st.warning(
            f"价格数据截至 {_meta.get('price_as_of', '—')}，"
            f"已落后最近收盘 {_meta.get('stale_days', '—')} 个交易日；"
            "以下持仓仅代表该历史信号时点。"
        )

    # ── 当前持仓卡
    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜戴金龙头Top2")
    _cur_slots = _gl.get("current_holdings", {}).get("slots", [])
    _hold_cols = st.columns(max(len(_cur_slots), 1))
    for _si in range(len(_cur_slots)):
        _slabel = _SLOT_LABELS[_si] if _si < len(_SLOT_LABELS) else f"槽{_si+1}"
        _sdata = _cur_slots[_si] or {}
        with _hold_cols[_si]:
            if not _sdata or _sdata.get("bil"):
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    "<div style='font-size:15px;color:#bbb;'>"
                    "BIL（当月无 C 组戴金板块或无足够龙头候选）</div></div>"
                )
            else:
                _sector_txt = (
                    f"{_sdata.get('sector_name', _sdata.get('sector_etf', '—'))}"
                    f"({_sdata.get('sector_etf', '—')})"
                )
                _excess_val = _sdata.get("excess_pct")
                _excess_txt = f"{_excess_val:+.1f}%" if isinstance(_excess_val, (int, float)) else "—"
                _slot_detail = (
                    f"戴金板块 {_sector_txt}｜龙头第 {_sdata.get('leader_rank', '—')}｜区间超额 {_excess_txt}"
                    f"<br>首次持有 {_sdata.get('since', '—')}｜已持有 {_sdata.get('held_months', '—')} 月"
                )
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    f"<div style='font-size:16px;color:#fff;font-weight:bold;'>"
                    f"{_sdata.get('name', '')} ({_sdata.get('ticker', '')})</div>"
                    f"<div style='font-size:14px;color:#bbb;margin-top:6px;'>{_slot_detail}</div></div>"
                )
            st.markdown(_slot_html, unsafe_allow_html=True)

    # ── 净值曲线
    st.markdown("##### 组合收益（起点归一为 1）")
    _eq = _gl.get("equity", {})
    _dates = pd.to_datetime(_gl.get("dates", []), errors="coerce")
    _series_cfg = [
        ("gold_leader_top2", "戴金龙头Top2", "#E74C3C", True),
        ("spy", "SPY", "#3498DB", True),
        ("rsp", "RSP 等权标普", "#9B59B6", False),
        ("eqw11", "11行业ETF等权", "#16A085", False),
    ]
    _fig_eq = go.Figure()
    for _key, _name, _color, _vis_default in _series_cfg:
        _vals = _eq.get(_key, []) or []
        if not _vals:
            continue
        _s = pd.Series(_vals, index=_dates).astype(float).dropna()
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
    st.plotly_chart(_fig_eq, use_container_width=True)
    st.caption("主图为戴金龙头Top2 与 SPY；点图例可展开 RSP / 11行业ETF等权对照")

    # ── 统计卡
    st.markdown("##### 统计卡")
    _stats = _gl.get("stats", {})
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
    st.caption(
        "戴金龙头 Top2 无 K 守擂，换手由 C 组戴金板块切换和板块内 Top2 变化决定。"
    )

    # ── Slot 分段收益
    st.markdown("##### Slot 分段收益")
    _has_slot_returns = render_slot_segment_returns(_gl)
    if not _has_slot_returns:
        st.caption("后端暂未返回 slot_equity。")
