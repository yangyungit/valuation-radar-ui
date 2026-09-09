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
    喂给 holdings_viz.build_stitched_fig（与 22_动量双龙 / 21_科技龙头 同一套接力段渲染）。"""
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


def render_slot_segment_returns(slot_equity: list, timeline: list, dates,
                                spy_values: list, key_prefix: str) -> bool:
    if not slot_equity or not timeline or len(dates) == 0:
        return False

    _valid = dates.dropna()
    win_lo, win_hi = _valid.min(), _valid.max()
    if pd.notna(win_lo) and pd.notna(win_hi) and win_lo < win_hi:
        _lo_py, _hi_py = win_lo.to_pydatetime(), win_hi.to_pydatetime()
        _sel = st.slider(
            "分段图时间窗口（拖动重设起点，各段与 SPY 在窗口最左端对齐归一）",
            min_value=_lo_py, max_value=_hi_py, value=(_lo_py, _hi_py),
            format="YYYY-MM", key=f"{key_prefix}_slot_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
        )
        win_lo, win_hi = pd.Timestamp(_sel[0]), pd.Timestamp(_sel[1])
    lo_m, hi_m = win_lo.strftime("%Y-%m"), win_hi.strftime("%Y-%m")

    spy = _norm_series(spy_values, dates)
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
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_slot_segment_{slot_i}")
    return True


def render_holding_cards(slots: list, bil_reason: str) -> None:
    cols = st.columns(max(len(slots), 1))
    for si in range(len(slots)):
        label = _SLOT_LABELS[si] if si < len(_SLOT_LABELS) else f"槽{si+1}"
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
                detail = (
                    f"板块 {sector_txt}｜龙头第 {data.get('leader_rank', '—')}｜5Y超额 {excess_txt}"
                    f"<br>首次持有 {data.get('since', '—')}｜已持有 {data.get('held_months', '—')} 月"
                )
                html = (
                    f"<div class='insight-box'><div class='insight-title'>{label}</div>"
                    f"<div style='font-size:16px;color:#fff;font-weight:bold;'>"
                    f"{data.get('name', '')} ({data.get('ticker', '')})</div>"
                    f"<div style='font-size:14px;color:#bbb;margin-top:6px;'>{detail}</div></div>"
                )
            st.markdown(html, unsafe_allow_html=True)


def render_equity_chart(dates, equity: dict, series_cfg: list, chart_key: str) -> None:
    fig = go.Figure()
    for key, name, color, vis_default in series_cfg:
        vals = equity.get(key, []) or []
        if not vals:
            continue
        s = pd.Series(vals, index=dates).astype(float).dropna()
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, name=name,
            line=dict(color=color, width=2 if vis_default else 1.4),
            visible=True if vis_default else "legendonly",
        ))
    fig.update_layout(
        height=420, hovermode="x unified", template="plotly_dark",
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.08),
        yaxis_title="净值（对数轴）", yaxis_type="log",
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def render_stats_cards(stats: dict, baseline: dict | None = None) -> None:
    """baseline 非空时，第二行指标附上与现行口径的差值。"""
    def _delta_pct(key):
        if not baseline:
            return None
        return f"{(stats.get(key, 0) - baseline.get(key, 0)) * 100:+.0f}% vs 现行"

    def _delta_num(key, fmt="{:+.2f} vs 现行"):
        if not baseline:
            return None
        return fmt.format(stats.get(key, 0) - baseline.get(key, 0))

    row_a = [
        ("累计收益", f"{stats.get('cum_return', 0) * 100:.0f}%", _delta_pct("cum_return")),
        ("年化收益", f"{stats.get('cagr', 0) * 100:.0f}%", _delta_pct("cagr")),
        ("最大回撤", f"{stats.get('max_dd', 0) * 100:.0f}%", _delta_pct("max_dd")),
        ("收益回撤比", f"{stats.get('calmar', 0):.2f}", _delta_num("calmar")),
        ("比SPY多赚", f"{stats.get('excess_vs_spy', 0) * 100:.0f}%", _delta_pct("excess_vs_spy")),
    ]
    row_b = [
        ("换股次数", f"{stats.get('n_swaps', 0)}", _delta_num("n_swaps", "{:+.0f} vs 现行")),
        ("平均一只拿几个月", f"{stats.get('avg_hold_months', 0)}", None),
        ("年均换手", f"{stats.get('ann_turnover', 0):.2f}", _delta_num("ann_turnover")),
        ("累计成本", f"{stats.get('cum_cost', 0) * 100:.1f}%", _delta_pct("cum_cost")),
        ("Sortino 比率", f"{stats.get('sortino', 0):.2f}", _delta_num("sortino")),
    ]
    for row in (row_a, row_b):
        cols = st.columns(5)
        for mi, (label, value, delta) in enumerate(row):
            with cols[mi]:
                st.metric(label, value, delta=delta, delta_color="off" if delta else "normal")


with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_gold_leader.clear()
        st.rerun()

st.title("🏅 戴金龙头 (Gold Dynasty Leader)")
st.caption("C组戴金板块 → 板块内市值前3选5年超额 Top2 → 下月执行。与 12M 动量守擂不是一套方法，已从 C组双龙 拆出单独成页。第二个 tab 是「强弱接近时分两个板块」的对照口径，线上规则仍是第一个 tab。")

_window = st.radio(
    "时间跨度",
    options=_WINDOWS,
    index=_WINDOWS.index("5Y"),
    horizontal=True,
    key="gl_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

hv.render_dynasty_ribbon(
    _window, key="gl_dynasty_gantt",
    compare_hint="本页下方回测只在 C 组 11 个 SPDR 里按 king_score 原值取第 1 名，"
                 "实测 5 年 55 个月里只有 17 个月和条带左列是同一个板块。",
)

st.caption(
    "**主线**：C组王朝接力图戴金板块 → 板块内市值前3、5年超额 Top2 → 下月执行。"
    "**诚实声明**：信号**不看未来**、可执行规则模拟；股票池=**逐月真实标普500成分**"
    "（PIT，Sharadar 数据含当年被剔除/退市/收购的公司），**已去生存者偏差**。"
)

_gl_c1, _gl_c2 = st.columns([1.1, 2.0])
with _gl_c1:
    _gl_rebal = st.toggle(
        "月度等权再平衡",
        value=True,
        key="gl_rebal",
        help="每月把两个槽位重新拉回50/50；关闭时各槽位独立复利。"
             "默认打开：对照口径的防抖参数是在开着再平衡的前提下寻优出来的。",
    )
with _gl_c2:
    st.caption(
        "固定持有 Top2；再平衡=每月卖一点涨多的槽位、补一点涨少的槽位，"
        "重新回到两个槽位各 50%。对照口径的三段 Calmar 在开着时是 1.36/1.48/1.12，"
        "关掉只剩 1.12/1.32/1.03——防抖的收益有一部分要靠再平衡才兑现。"
    )

with st.expander("交易假设"):
    _gl_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="gl_cost",
        help="买/卖各算一次，扣在成交名义额上；影响回测净值和统计。",
    )
    _gl_rs_gap = st.slider(
        "对照口径：RS 差进场阈（只影响「分两个板块」那个 tab）",
        min_value=-5.0, max_value=40.0, value=5.0, step=0.5, key="gl_rs_gap",
        help="金牌板块 RS 领先银牌不到这个点数时，第二个槽改从银牌板块选龙头。"
             "调大=更常分两个板块；调到 0 以下≈退回现行的金牌 Top2。",
    )
    _gl_rs_gap_exit = st.slider(
        "对照口径：滞回退出阈（RS 差回到这个点数以上才合回一个板块）",
        min_value=0.0, max_value=45.0, value=10.0, step=0.5,
        key="gl_rs_gap_exit",
        help="拖到等于进场阈就没有滞回；调大=已经分开后更黏，减少阈值边界反复横跳。"
             "改前对照口径 5Y 的 29 次槽1换手里有 20 次来自这种横跳。",
    )
    _gl_silver_buf = st.slider(
        "对照口径：银牌板块名次死区", 0, 6, 6, key="gl_silver_buf",
        help="0=关闭（每月改选 king_score 第 2 名）；N>0=上月的银牌板块只要今月名次还在前 N "
             "且 RS>0 就留任。关掉时银牌板块 5 年换 34 次、跨 8 个板块，零粘性。",
    )
    st.caption(
        "上面三个默认值 5.0 / 10.0 / 6 是 scripts/sweep_dd_silver_antiwhipsaw.py 在一份 "
        "10Y 面板上切 3Y/5Y/10Y 三段、504 组网格、按三段归一化 Calmar 的 maximin 选出来的。"
        "目标用 Calmar 而不是累计收益，因为累计收益里 2023-05 单月就贡献 +18.1%，"
        "拿它当目标等于对那一个月过拟合。"
    )

_gl = fetch_dynasty_gold_leader(
    window=_window, rebalance=_gl_rebal, cost_bps=float(_gl_cost),
    silver_rs_gap=float(_gl_rs_gap),
    silver_rs_gap_exit=float(_gl_rs_gap_exit),
    silver_buffer_n=int(_gl_silver_buf),
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
    if not _meta.get("mcap_gate_applied"):
        _notes.append("市值门票产物缺失，本次未按市值前3过滤")
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

    _signal_as_of = str(_meta.get("signal_as_of", "") or "")
    _signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
    _eq = _gl.get("equity", {})
    _dates = pd.to_datetime(_gl.get("dates", []), errors="coerce")
    _stats = _gl.get("stats", {})
    _two = _gl.get("two_sector", {}) or {}

    _tab_now, _tab_two = st.tabs(["现行：金牌板块 Top2", "对照：强弱接近时分两个板块"])

    with _tab_now:
        st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜戴金龙头Top2")
        render_holding_cards(
            _gl.get("current_holdings", {}).get("slots", []),
            "当月无 C 组戴金板块或无足够龙头候选",
        )

        st.markdown("##### 组合收益（起点归一为 1）")
        render_equity_chart(_dates, _eq, [
            ("gold_leader_top2", "戴金龙头Top2", "#E74C3C", True),
            ("spy", "SPY", "#3498DB", True),
            ("rsp", "RSP 等权标普", "#9B59B6", False),
            ("eqw11", "11行业ETF等权", "#16A085", False),
        ], "gl_eq_now")
        st.caption("主图为戴金龙头Top2 与 SPY；点图例可展开 RSP / 11行业ETF等权对照")

        st.markdown("##### 统计卡")
        render_stats_cards(_stats)
        st.caption(
            "戴金龙头 Top2 无 K 守擂，换手由 C 组戴金板块切换和板块内 Top2 变化决定。"
        )

        st.markdown("##### Slot 分段收益")
        if not render_slot_segment_returns(
            _gl.get("slot_equity") or [], _gl.get("holdings_timeline") or [],
            _dates, _eq.get("spy", []), "gl_now",
        ):
            st.caption("后端暂未返回 slot_equity。")

    with _tab_two:
        if not _two.get("available"):
            st.info("后端未返回对照口径（`two_sector`），可能是后端版本较旧。")
        else:
            _split_n = _two.get("split_months", 0)
            _total_n = _two.get("total_months", 0)
            _gap = _two.get("silver_rs_gap", 5.0)
            _gap_exit = _two.get("silver_rs_gap_exit")
            _buf_n = _two.get("silver_buffer_n", 0) or 0
            _held_n = _two.get("held_over_months", 0) or 0
            st.caption(
                f"**这个 tab 只是对照，不是线上规则。** 金牌板块 RS 领先银牌不到 "
                f"**{_gap:g}** 个点时，第二个槽改从**银牌板块**选龙头；领先够多就和现行一样"
                f"（金牌板块 Top2）。展示期内 **{_split_n}/{_total_n}** 个月真的分了两个板块。"
                "当月没有戴金板块时仍持 BIL，不因为有银牌板块就破例持股。"
            )
            _anti = []
            if _gap_exit is not None and _gap_exit > _gap:
                _anti.append(
                    f"滞回生效：没分开时 RS 差 < **{_gap:g}** 才分，已分开时要回到 "
                    f"**{_gap_exit:g}** 以上才合回"
                )
            else:
                _anti.append("滞回未生效（退出阈 = 进场阈），每月按同一个硬阈值判断")
            if _buf_n > 0:
                _anti.append(
                    f"银牌名次死区 N=**{_buf_n}**，展示期内 **{_held_n}** 个月的银牌板块是留任的"
                )
            else:
                _anti.append("银牌名次死区关闭，每月改选 king_score 第 2 名")
            st.caption("｜".join(_anti))
            st.caption(
                "**别只看收益**：这套口径的超额里 2023-05 单月就贡献 +18.1%，收益比值一步"
                "从 0.98 跳到 1.158 之后再没回落，所以三个防抖参数是按 Calmar 而不是按累计"
                "收益寻优的。三段 Calmar 从 1.14/1.24/0.92 提到 1.36/1.48/1.12，同时换股"
                "次数从 31/39/72 降到 26/34/63（同一份 10Y 面板切三段实测，"
                "和上面按窗口分别拉的数字不是一个口径，短窗口不是长窗口的尾部切片）。"
            )

            st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜对照口径")
            render_holding_cards(
                _two.get("current_holdings", {}).get("slots", []),
                "当月无 C 组戴金板块或无足够龙头候选",
            )

            st.markdown("##### 组合收益（与现行口径同图对比）")
            render_equity_chart(_dates, _eq, [
                ("two_sector", "对照：分两个板块", "#F39C12", True),
                ("gold_leader_top2", "现行：金牌Top2", "#E74C3C", True),
                ("spy", "SPY", "#3498DB", True),
                ("rsp", "RSP 等权标普", "#9B59B6", False),
                ("eqw11", "11行业ETF等权", "#16A085", False),
            ], "gl_eq_two")
            st.caption("橙线=对照口径，红线=现行口径，同一起点归一，可直接比斜率和回撤深度")

            st.markdown("##### 统计卡（差值 = 对照 − 现行）")
            render_stats_cards(_two.get("stats", {}), baseline=_stats)

            st.markdown("##### 哪些月份走了银牌板块")
            _ts_rows = [
                r for r in (_gl.get("two_sector_timeline") or [])
                if r.get("month", "") >= str(_meta.get("display_start", ""))[:7]
            ]
            if _ts_rows:
                _tbl = pd.DataFrame([{
                    "月份": r.get("month"),
                    "金牌板块": r.get("sector_etf") or "—",
                    "银牌板块": r.get("silver_sector_etf") or "—",
                    "RS 差": r.get("rs_gap"),
                    "分两个板块": "是" if r.get("split_sectors") else "",
                    "持仓": " + ".join(r.get("picks") or []),
                } for r in reversed(_ts_rows)])
                st.dataframe(_tbl, use_container_width=True, hide_index=True, height=320)
            else:
                st.caption("后端暂未返回对照口径的月度明细。")

            st.markdown("##### Slot 分段收益")
            if not render_slot_segment_returns(
                _two.get("slot_equity") or [], _two.get("holdings_timeline") or [],
                _dates, _eq.get("spy", []), "gl_two",
            ):
                st.caption("后端暂未返回 slot_equity。")
