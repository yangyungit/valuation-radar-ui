import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from api_client import fetch_dynasty_double_dragon

st.set_page_config(page_title="C组双龙", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
</style>
""", unsafe_allow_html=True)

_DYNASTY_TAB_WINDOWS = ["3Y", "5Y", "10Y"]

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_double_dragon.clear()
        st.rerun()

st.title("📈 C组双龙 (Double Dragon)")
st.caption("C组戴金板块龙头策略 · 标普500动量守擂策略 · 双策略对照")

_dynasty_window = st.radio(
    "时间跨度",
    options=_DYNASTY_TAB_WINDOWS,
    index=_DYNASTY_TAB_WINDOWS.index("5Y"),
    horizontal=True,
    key="dynasty_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

st.markdown("#### 📈 C组双龙持仓 — 双策略对照")
_dd_n_cur = 2
st.caption(
    f"**主线A**：C组王朝接力图戴金板块 → 板块内王朝龙头区间超额 Top{_dd_n_cur} → 下月执行。"
    "**主线B**：当前标普500股票池 → 12M 动量 + MA200 → TopN/K 守擂 → 下月执行。"
    "**诚实声明**：信号**不看未来**、可执行规则模拟；但股票池=**当前**标普500成分，"
    "**含生存者偏差**（缺历史上被剔除/退市/收购的公司），结果偏乐观 → **研究原型，非真实业绩**。"
)

_strategy_options = {
    "戴金龙头Top2": "c_gold_dynasty_leader_top2",
    "12M动量K守擂": "sp500_12m_ma200_k_guard",
}
_dd_risk = True
_dd_c0, _dd_c1, _dd_c2, _dd_c3 = st.columns([1.7, 1.1, 1.2, 1.2])
with _dd_c0:
    _dd_strategy_label = st.radio(
        "主策略", list(_strategy_options.keys()), index=0, horizontal=True,
        key="dd_strategy",
        help="决定当前持仓卡、统计卡和时间带展示哪条策略；净值图会同时画两条曲线。",
    )
_dd_signal = _strategy_options[_dd_strategy_label]
with _dd_c1:
    _dd_legacy_n = st.selectbox(
        "动量TopN", [1, 2, 3, 4, 5], index=1, key="dd_legacy_n",
        help="只作用于 12M 动量 K 守擂策略；戴金龙头策略固定两仓。",
    )
_dd_k = 0
with _dd_c2:
    _dd_k_display = st.empty()
    _dd_k_display.caption("动量守擂K：自动择优，加载后显示")
with _dd_c3:
    _dd_rebal = st.toggle(
        "戴金策略再平衡", value=False, key="dd_rebal",
        help="只作用于戴金龙头 Top2；12M 动量 K 守擂策略固定不再平衡。",
    )

with st.expander("⚙️ 高级设置"):
    _dd_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="dd_cost",
        help="买/卖各算一次，扣在成交名义额上",
    )
    _dd_show11 = st.checkbox(
        "叠加 11 行业 ETF 等权", value=False, key="dd_show11"
    )

_dd = fetch_dynasty_double_dragon(
    window=_dynasty_window, signal=_dd_signal, k=_dd_k,
    risk_protect=_dd_risk, rebalance=_dd_rebal, cost_bps=float(_dd_cost),
    n_holdings=int(_dd_legacy_n),
)

if not _dd.get("success"):
    _dd_k_display.metric("自动K", "—")
    st.warning(f"⚠️ C组双龙回测暂不可用：{_dd.get('error', '未知错误')}")
else:
    _meta = _dd.get("meta", {})
    _notes = []
    if not _meta.get("legacy_date_added_used"):
        _notes.append("旧动量策略未启用入指数日过滤（date_added 不可靠）")
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
            f"请求{_dynasty_window}｜实际约 {_meta.get('actual_years', 0):.1f}Y"
            f"（{_meta.get('actual_days', 0)} 个交易日）"
        )
    if _meta.get("is_stale"):
        st.warning(
            f"价格数据截至 {_meta.get('price_as_of', '—')}，"
            f"已落后最近收盘 {_meta.get('stale_days', '—')} 个交易日；"
            "以下持仓仅代表该历史信号时点。"
        )

    _primary_strategy = _meta.get("selection_strategy", _dd.get("signal", ""))
    _legacy_params = _meta.get("legacy_params", {}) or {}
    _legacy_n_val = int(_legacy_params.get("n_holdings", _dd_legacy_n))
    _legacy_k_raw = _legacy_params.get("k", None)
    _legacy_k_val = int(_legacy_k_raw) if isinstance(_legacy_k_raw, (int, float)) else None
    _legacy_k_txt = f"K{_legacy_k_val}" if _legacy_k_val is not None else "K自动"
    _legacy_k_mode = str(_legacy_params.get("k_mode", "manual") or "manual")
    _dd_k_display.metric("自动K", _legacy_k_txt)

    # ── 当前持仓卡
    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    _strategy_title = "12M动量K守擂" if _primary_strategy == "sp500_12m_ma200_k_guard" else "戴金龙头Top2"
    st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜{_strategy_title}")
    _cur = _dd.get("current_holdings", {})
    _cur_slots = _cur.get("slots", [])
    _hold_cols = st.columns(max(len(_cur_slots), 1))
    _slot_labels_card = ["槽A", "槽B", "槽C", "槽D", "槽E"]
    for _si in range(len(_cur_slots)):
        _slabel = _slot_labels_card[_si] if _si < len(_slot_labels_card) else f"槽{_si+1}"
        _sdata = _cur_slots[_si] or {}
        with _hold_cols[_si]:
            if not _sdata or _sdata.get("bil"):
                _bil_msg = (
                    "BIL（无满足 12M 动量 + MA200 的合格股票）"
                    if _primary_strategy == "sp500_12m_ma200_k_guard"
                    else "BIL（当月无 C 组戴金板块或无足够龙头候选）"
                )
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    "<div style='font-size:15px;color:#bbb;'>"
                    f"{_bil_msg}</div></div>"
                )
            else:
                if _primary_strategy == "sp500_12m_ma200_k_guard":
                    _mom_val = _sdata.get("momentum_12m_pct")
                    _mom_txt = f"{_mom_val:+.1f}%" if isinstance(_mom_val, (int, float)) else "—"
                    _slot_detail = (
                        f"12M排名 第 {_sdata.get('rank', '—')}｜12M涨幅 {_mom_txt}"
                        f"｜MA200上方 {'是' if _sdata.get('above_ma200') else '—'}"
                        f"<br>首次持有 {_sdata.get('since', '—')}｜已持有 {_sdata.get('held_months', '—')} 月"
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
    st.markdown("##### 净值曲线（起点归一为 1）")
    _eq = _dd.get("equity", {})
    _dd_dates = pd.to_datetime(_dd.get("dates", []), errors="coerce")
    _series_cfg = [
        ("gold_leader_top2", "戴金龙头Top2", "#E74C3C", True),
        ("momentum_k_guard", f"12M动量守擂 Top{_legacy_n_val}/{_legacy_k_txt}", "#F39C12", True),
        ("spy", "SPY", "#3498DB", True),
        ("rsp", "RSP 等权标普", "#9B59B6", False),
    ]
    if _dd_show11:
        _series_cfg.append(("eqw11", "11行业ETF等权", "#16A085", False))
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
        legend=dict(orientation="h", y=1.08), yaxis_title="净值",
    )
    st.plotly_chart(_fig_eq, use_container_width=True)
    st.caption("默认显示两条选股策略 + SPY；点图例可展开 RSP" + ("/11ETF" if _dd_show11 else ""))

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
    if _primary_strategy == "sp500_12m_ma200_k_guard":
        _k_note = (
            "K 由系统按当前窗口年化收益最高自动选择"
            if _legacy_k_mode == "best_cagr"
            else "K 使用请求参数"
        )
        st.caption(
            f"当前统计卡为 12M 动量守擂 Top{_legacy_n_val}/{_legacy_k_txt}；"
            f"{_k_note}；已有持仓仍在前 K 就留任，跌出前 K 才换。该策略固定不再平衡。"
        )
    else:
        st.caption(
            "当前统计卡为戴金龙头 Top2；该口径无 K 守擂，换手由 C 组戴金板块切换和板块内 Top2 变化决定。"
        )
    if _legacy_k_val is not None:
        st.caption(
            f"动量守擂自动K：当前 Top{_legacy_n_val} 采用 {_legacy_k_txt}；"
            "页面不再提供手动 K 滑杆，避免把参数搜索误当成实时可控信号。"
        )

    # ── 持仓时间带
    st.markdown("##### 持仓时间带")
    _tl = _dd.get("holdings_timeline", [])
    _band_rows = []
    _slot_labels_band = ["槽A", "槽B", "槽C", "槽D", "槽E"]
    _n_track = _dd.get("n_holdings", 2)
    for _slot_i in range(_n_track):
        _track = _slot_labels_band[_slot_i] if _slot_i < len(_slot_labels_band) else f"槽{_slot_i+1}"
        _prev = None
        _start = None
        for _h in _tl:
            _m = _h["month"]
            _slots_list = _h.get("slots", [])
            _cell = _slots_list[_slot_i] if _slot_i < len(_slots_list) else None
            if not _cell:
                _lab = "—"
            elif _cell.get("bil"):
                _lab = "BIL"
            else:
                _lab = _cell.get("ticker", "—")
            if _lab != _prev:
                if _prev is not None and _prev != "—":
                    _band_rows.append({
                        "Track": _track, "持仓": _prev,
                        "Start": _start, "Finish": pd.Timestamp(_m + "-01"),
                    })
                _prev = _lab
                _start = pd.Timestamp(_m + "-01")
        if _prev is not None and _prev != "—" and _tl:
            _band_rows.append({
                "Track": _track, "持仓": _prev, "Start": _start,
                "Finish": pd.Timestamp(_tl[-1]["month"] + "-01") + pd.offsets.MonthBegin(1),
            })
    if _band_rows:
        _df_band = pd.DataFrame(_band_rows)
        _fig_band = px.timeline(
            _df_band, x_start="Start", x_end="Finish", y="Track",
            color="持仓", color_discrete_map={"BIL": "#7f8c8d"},
        )
        _fig_band.update_yaxes(autorange="reversed", title="")
        _fig_band.update_layout(
            height=240, template="plotly_dark",
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", y=-0.25),
        )
        st.plotly_chart(_fig_band, use_container_width=True)
        st.caption("每只票一色，BIL 灰色；hover 看持有区间")
