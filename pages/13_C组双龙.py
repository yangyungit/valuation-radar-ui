import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import fetch_dynasty_double_dragon

st.set_page_config(page_title="C组双龙", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
</style>
""", unsafe_allow_html=True)

_DYNASTY_TAB_WINDOWS = ["3Y", "5Y", "10Y"]
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


def render_slot_segment_returns(dd: dict) -> bool:
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
            format="YYYY-MM", key=f"dd_slot_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
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
        st.plotly_chart(fig, use_container_width=True, key=f"dd_slot_segment_{slot_i}")
    return True

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_double_dragon.clear()
        st.rerun()

st.title("📈 C组双龙 (Double Dragon)")
st.caption("C组戴金板块龙头策略 · 标普500动量K守擂 · 标普500动量防抖守擂 · 三策略对照")

_dynasty_window = st.radio(
    "时间跨度",
    options=_DYNASTY_TAB_WINDOWS,
    index=_DYNASTY_TAB_WINDOWS.index("5Y"),
    horizontal=True,
    key="dynasty_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

st.markdown("#### 📈 C组双龙持仓 — 三策略对照")
_dd_n_cur = 2
st.caption(
    f"**主线A**：C组王朝接力图戴金板块 → 板块内王朝龙头区间超额 Top{_dd_n_cur} → 下月执行。"
    "**主线B**：当前标普500股票池 → 12M 动量 + MA200 → TopN/K 守擂 → 下月执行。"
    "**主线C**：同一套 12M 动量候选池 → TopN/分差 δ 防抖守擂 → 下月执行。"
    "**诚实声明**：信号**不看未来**、可执行规则模拟；股票池=**逐月真实标普500成分**"
    "（PIT，Sharadar 数据含当年被剔除/退市/收购的公司），**已去生存者偏差**。"
)

_strategy_options = {
    "戴金龙头Top2": "c_gold_dynasty_leader_top2",
    "12M动量K守擂": "sp500_12m_ma200_k_guard",
    "12M动量防抖守擂": _DD_DELTA_STRATEGY,
}
_dd_risk = True
_dd_strategy_label = st.radio(
    "当前查看策略",
    list(_strategy_options.keys()),
    index=0,
    horizontal=True,
    key="dd_strategy",
    help="决定当前持仓卡、统计卡、Slot分段收益和时间带展示哪条策略；组合收益图仍保留三条策略曲线作参考。",
)
_dd_signal = _strategy_options[_dd_strategy_label]

_dd_legacy_n = int(st.session_state.get("dd_legacy_n", 2) or 2)
_dd_rebal = False
_dd_k = 0
_dd_delta_k = -1.0
_dd_k_display = None
_dd_delta_display = None

if _dd_signal in {_DD_MOMENTUM_STRATEGY, _DD_DELTA_STRATEGY}:
    st.markdown("##### 12M动量守擂设置")
    _mom_c1, _mom_c2 = st.columns([1.1, 1.2])
    with _mom_c1:
        _dd_legacy_n = st.selectbox(
            "持仓数量 TopN",
            [1, 2, 3, 4, 5],
            index=[1, 2, 3, 4, 5].index(_dd_legacy_n) if _dd_legacy_n in [1, 2, 3, 4, 5] else 1,
            key="dd_legacy_n",
            help="只作用于两条 12M 动量守擂策略；戴金龙头策略固定 Top2。",
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
else:
    st.markdown("##### 戴金龙头Top2设置")
    _gold_c1, _gold_c2 = st.columns([1.1, 2.0])
    with _gold_c1:
        _dd_rebal = st.toggle(
            "月度等权再平衡",
            value=False,
            key="dd_rebal",
            help="只作用于戴金龙头Top2：每月把两个槽位重新拉回50/50；关闭时各槽位独立复利。",
        )
    with _gold_c2:
        st.caption(
            "固定持有 Top2；再平衡=每月卖一点涨多的槽位、补一点涨少的槽位，"
            "重新回到两个槽位各 50%。"
        )

with st.expander("交易假设（作用于三条策略）"):
    _dd_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="dd_cost",
        help="买/卖各算一次，扣在成交名义额上；会影响三条策略的回测净值和统计。",
    )

_dd = fetch_dynasty_double_dragon(
    window=_dynasty_window, signal=_dd_signal, k=_dd_k, delta_k=_dd_delta_k,
    risk_protect=_dd_risk, rebalance=_dd_rebal, cost_bps=float(_dd_cost),
    n_holdings=int(_dd_legacy_n),
)

if not _dd.get("success"):
    if _dd_k_display is not None:
        _dd_k_display.metric("自动守擂K", "—")
    if _dd_delta_display is not None:
        _dd_delta_display.metric("自动防抖强度", "—")
    st.warning(f"⚠️ C组双龙回测暂不可用：{_dd.get('error', '未知错误')}")

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
    # ── 当前持仓卡
    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    if _primary_strategy == _DD_MOMENTUM_STRATEGY:
        _strategy_title = "12M动量K守擂"
    elif _primary_strategy == _DD_DELTA_STRATEGY:
        _strategy_title = "12M动量防抖守擂"
    else:
        _strategy_title = "戴金龙头Top2"
    st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜{_strategy_title}")
    _cur = _dd.get("current_holdings", {})
    _cur_slots = _cur.get("slots", [])
    _hold_cols = st.columns(max(len(_cur_slots), 1))
    for _si in range(len(_cur_slots)):
        _slabel = _SLOT_LABELS[_si] if _si < len(_SLOT_LABELS) else f"槽{_si+1}"
        _sdata = _cur_slots[_si] or {}
        with _hold_cols[_si]:
            if not _sdata or _sdata.get("bil"):
                _bil_msg = (
                    "BIL（无满足 12M 动量 + MA200 的合格股票）"
                    if _primary_strategy in {_DD_MOMENTUM_STRATEGY, _DD_DELTA_STRATEGY}
                    else "BIL（当月无 C 组戴金板块或无足够龙头候选）"
                )
                _slot_html = (
                    f"<div class='insight-box'><div class='insight-title'>{_slabel}</div>"
                    "<div style='font-size:15px;color:#bbb;'>"
                    f"{_bil_msg}</div></div>"
                )
            else:
                if _primary_strategy in {_DD_MOMENTUM_STRATEGY, _DD_DELTA_STRATEGY}:
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
    st.markdown("##### 选中版本组合收益（起点归一为 1）")
    _eq = _dd.get("equity", {})
    _dd_dates = pd.to_datetime(_dd.get("dates", []), errors="coerce")
    _series_cfg = [
        ("gold_leader_top2", "戴金龙头Top2", "#E74C3C", True),
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
    st.plotly_chart(_fig_eq, use_container_width=True)
    st.caption("当前组合主图保留戴金Top2、动量TopN/K、防抖TopN/δ和SPY；点图例可展开 RSP / 11行业ETF等权")

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
        _delta_note = (
            "kδ 由系统按 3Y/5Y/10Y 稳健平台自动选择"
            if _delta_k_mode == "robust_maximin"
            else "kδ 使用请求参数"
        )
        st.caption(
            f"当前统计卡为 12M 动量防抖守擂 Top{_legacy_n_val}/{_delta_k_txt}；"
            f"{_delta_note}；已有持仓距 TopN 门槛在 δ 内就留任，差得更多才换。该策略固定不再平衡。"
        )
    else:
        st.caption(
            "当前统计卡为戴金龙头 Top2；该口径无 K 守擂，换手由 C 组戴金板块切换和板块内 Top2 变化决定。"
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
    _has_slot_returns = render_slot_segment_returns(_dd)
    if not _has_slot_returns:
        st.caption("后端暂未返回 slot_equity。")

    # ── 防抖守擂 δ 稳健性（尾部 3Y/5Y/10Y，仿 10_科技龙头）
    _sweep = (_delta_params.get("selection", {}) or {}).get("sweep_grid", {}) or {}
    if _sweep:
        st.markdown("##### 防抖守擂 δ 稳健性（尾部 3Y/5Y/10Y）")
        _HZ = ["3Y", "5Y", "10Y"]
        _dk_grid = sorted(_sweep.keys(), key=lambda s: float(s))
        _x = [float(s) for s in _dk_grid]
        _curves = {hz: [float(_sweep[s].get(hz, float("nan"))) * 100 for s in _dk_grid] for hz in _HZ}
        _norm = {}
        for hz in _HZ:
            _c = pd.Series(_curves[hz])
            _mx = _c.max()
            _norm[hz] = (_c / _mx) if (_mx == _mx and _mx > 0) else _c * float("nan")
        _COLOR = {"3Y": "#5DADE2", "5Y": "#FFD700", "10Y": "#E67E22"}
        _fig_sweep = go.Figure()
        for hz in _HZ:
            if pd.Series(_curves[hz]).notna().sum() < 2:
                continue
            _lw = 4 if hz == "3Y" else 2
            _fig_sweep.add_trace(go.Scatter(
                x=_x, y=list(_norm[hz]), mode="lines+markers", name=hz,
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
                text="δ 稳健性 · 尾部 3Y/5Y/10Y 总收益（各自归一化；三线齐高处=稳健 δ）",
                font=dict(size=13), x=0.01, xanchor="left",
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        )
        st.plotly_chart(_fig_sweep, use_container_width=True, key="dd_delta_sweep")

        def _argmax_delta(hz):
            _c = pd.Series(_curves[hz])
            return _dk_grid[int(_c.idxmax())] if _c.notna().any() else None
        _peaks = " · ".join(
            f"{hz} 单峰 δ={_argmax_delta(hz)}" for hz in _HZ if _argmax_delta(hz) is not None
        )
        if _delta_k_val is not None:
            st.caption(
                f"✅ **推荐 δ\\* = {_delta_k_val:.2f}**（三段都不差的重叠平台，跨窗口稳健）。"
                f"对照各段单独最优：{_peaks}——单段峰值各不相同正是过拟合的症状，别照搬。"
            )
