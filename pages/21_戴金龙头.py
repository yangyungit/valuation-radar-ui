import math

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import fetch_dynasty_gold_leader
from cn_names import cn_name_map

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
                         win_lo=None, win_hi=None, shade_spans: list = None) -> None:
    fig = go.Figure()
    for x0, x1 in (shade_spans or []):
        fig.add_vrect(x0=x0, x1=x1, fillcolor="#F39C12", opacity=0.10,
                      line_width=0, layer="below")
    for key, name, color, vis_default, *_style in series_cfg:
        dash = _style[0] if _style else None
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
            line=dict(color=color, width=1.3 if dash else (2 if vis_default else 1.4),
                      dash=dash),
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


with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_gold_leader.clear()
        st.rerun()

st.title("🏅 戴金龙头 (Gold Dynasty Leader)")
st.caption("C组戴金板块 → 板块内市值前3选5年超额 Top2；金牌板块 RS 领先银牌不足阈值时，第二个槽改从银牌板块选龙头 → 下月执行。上月持有的龙头只要落后新第 1 名不太多（按 5 年涨幅比值算，门槛见下方月度明细）就继续持有，减少板块内来回换手。与 12M 动量守擂不是一套方法，已从 C组双龙 拆出单独成页。")

_window = st.radio(
    "时间跨度",
    options=_WINDOWS,
    index=_WINDOWS.index("5Y"),
    horizontal=True,
    key="gl_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

st.caption(
    "**主线**：C组王朝接力图戴金板块 → 板块内市值前3、5年超额 Top2（上月持有的落后不多就留任）→ 下月执行。"
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
             "默认打开：这套口径的防抖参数是在开着再平衡的前提下寻优出来的。",
    )
with _gl_c2:
    st.caption(
        "固定持有 Top2；再平衡=每月卖一点涨多的槽位、补一点涨少的槽位，"
        "重新回到两个槽位各 50%。这套口径（含擂主保护、金牌回退防护）同一份 10Y 面板切三段的 Calmar，"
        "开着再平衡是 2.18/1.50/1.12，关掉是 1.58/1.56/1.14——关掉后 3Y 回撤从 −18.0% 扩到 −27.8%。"
    )

with st.expander("交易假设"):
    _gl_cost = st.slider(
        "单边成本 (bps)", 0, 50, 10, key="gl_cost",
        help="买/卖各算一次，扣在成交名义额上；影响回测净值和统计。",
    )
    _gl_rs_gap = st.slider(
        "RS 差进场阈",
        min_value=-5.0, max_value=40.0, value=5.0, step=0.5, key="gl_rs_gap",
        help="金牌板块 RS 领先银牌不到这个点数时，第二个槽改从银牌板块选龙头。"
             "调大=更常分两个板块；调到 0 以下≈两个槽都选同一金牌板块 Top2（不分板块）。",
    )
    _gl_rs_gap_exit = st.slider(
        "滞回退出阈（RS 差回到这个点数以上才合回一个板块）",
        min_value=0.0, max_value=45.0, value=10.0, step=0.5,
        key="gl_rs_gap_exit",
        help="拖到等于进场阈就没有滞回；调大=已经分开后更黏，减少阈值边界反复横跳。"
             "改前这套口径 5Y 的 29 次槽1换手里有 20 次来自这种横跳。",
    )
    _gl_silver_buf = st.slider(
        "银牌板块名次死区", 0, 6, 6, key="gl_silver_buf",
        help="0=关闭（每月改选 king_score 第 2 名）；N>0=上月的银牌板块只要今月名次还在前 N "
             "且 RS>0 就留任。关掉时银牌板块 5 年换 34 次、跨 8 个板块，零粘性。",
    )
    _gl_gold_revert = st.toggle(
        "金牌回退防护",
        value=True,
        key="gl_gold_revert",
        help="刚被换掉的老金牌（最近 12 个月连续当过 3 个月以上）又冲回第 1 名时，"
             "要连续 3 个月第 1 才换回去，期间留任现金牌（哪怕它当月 RS 跑输 SPY）、老金牌降成银牌。"
             "只管左列金牌；同样规则加到银牌上实测 3Y Calmar 从 1.83 掉到 1.31，所以不加。",
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
    gold_revert=bool(_gl_gold_revert),
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
    _two = _gl.get("two_sector", {}) or {}
    _hold_gap = _two.get("leader_hold_gap")
    _hold_gap_txt = f"约 {math.exp(_hold_gap) - 1:.0%}" if isinstance(_hold_gap, (int, float)) else "门槛"

    if not _two.get("available"):
        st.info("后端未返回强弱切换口径（`two_sector`），可能是后端版本较旧。")
    else:
        _rb_slots, _rb_names, _rb_months, _rb_dim, _rb_split = build_sector_ribbon(
            _gl.get("two_sector_timeline") or [], str(_meta.get("display_start", ""))[:7]
        )
        _split_n = _two.get("split_months", 0)
        _total_n = _two.get("total_months", 0)
        _gap = _two.get("silver_rs_gap", 5.0)
        _gap_exit = _two.get("silver_rs_gap_exit")
        _buf_n = _two.get("silver_buffer_n", 0) or 0
        _held_n = _two.get("held_over_months", 0) or 0
        st.caption(
            f"金牌板块 RS 领先银牌不到 **{_gap:g}** 个点时，第二个槽改从**银牌板块**选龙头；"
            f"领先够多时两个槽都选金牌板块 Top2。展示期内 **{_split_n}/{_total_n}** 个月真的分了两个板块。"
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
        if _two.get("gold_revert"):
            _anti.append(
                f"金牌回退防护开启，展示期内 **{_two.get('gold_revert_months', 0)}** 个月"
                "金牌是留任的（老金牌冲回第 1 未满 3 个月）"
            )
        else:
            _anti.append("金牌回退防护关闭，每月取 king_score 第 1 名当金牌")
        st.caption("｜".join(_anti))
        st.caption(
            "**别只看收益**：这套口径的超额里 2023-05 单月就贡献 +18.1%，收益比值一步"
            "从 0.98 跳到 1.158 之后再没回落，所以三个防抖参数是按 Calmar 而不是按累计"
            "收益寻优的。三段 Calmar 从 1.14/1.24/0.92 提到 1.36/1.48/1.12，同时换股"
            "次数从 31/39/72 降到 26/34/63（同一份 10Y 面板切三段实测，"
            "和上面按窗口分别拉的数字不是一个口径，短窗口不是长窗口的尾部切片）。"
        )

        st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜戴金龙头Top2")
        render_holding_cards(
            _two.get("current_holdings", {}).get("slots", []),
            "当月无 C 组戴金板块或无足够龙头候选",
        )

        _win_lo, _win_hi = render_time_window_slider(_dates, "gl_two")

        st.markdown("##### 组合收益（起点归一为 1）")
        _eq_plot = dict(_eq)
        for _row in (_two.get("slot_equity") or []):
            _eq_plot[f"slot{int(_row.get('slot', 0))}"] = _row.get("equity", [])
        render_equity_chart(_dates, _eq_plot, [
            ("two_sector", "戴金龙头Top2（强弱切换+擂主保护）", "#F39C12", True),
            ("spy", "SPY", "#3498DB", True),
            ("slot0", "左列 · 金牌槽", "rgba(243,156,18,0.55)", True, "dot"),
            ("slot1", "右列 · 银牌槽", "rgba(170,178,189,0.75)", True, "dot"),
        ], "gl_eq_two", _win_lo, _win_hi, split_month_spans(_rb_split, _win_lo, _win_hi))
        st.caption(
            "橙色竖条 = 那段时间真的分投了金银两个板块，没底色的月份两个槽都在金牌板块里。"
            "左列 / 右列是两个槽各自的净值，组合曲线 = 两条各占一半取平均；"
            "上方时间窗口同步套用到本图和下方 Slot 分段图"
        )

        st.markdown("##### 统计卡")
        _stats_two = dict(_two.get("stats", {}))
        _two_nav = _norm_series(_eq.get("two_sector", []), _dates)
        if not _two_nav.empty:
            _stats_two["r2"] = hv.compute_nav_kpi(_two_nav).get("r2")
        render_stats_cards(_stats_two)
        st.caption("logR² = 净值曲线取对数后对时间做线性回归的拟合优度，越接近 1 越是匀速上涨、越低说明涨跌越颠簸。")

        st.markdown("##### Slot 分段收益")
        _ribbons = hv.relay_ribbon_segments(
            _rb_slots, _rb_months, _rb_names, _rb_dim, "<br>未选中"
        ) if _rb_months else None
        if _rb_months:
            st.caption(
                "每张接力图顶部的色带是对应的板块：槽A 顶部 = 左列金牌板块，槽B 顶部 = 右列银牌板块。"
                "**和本页回测完全同源**：C 组 11 个 SPDR 按 king_score 排名，第 1 名 = 金牌，"
                "第 2 名带名次死区 = 银牌，月末出信号、下月第一个交易日执行。"
                "**银牌压暗的段 = 那几个月银牌板块没被选中**，金牌 RS 领先够多，槽B 实际买的是"
                "金牌板块的第 2 只龙头；银牌亮着才是真的分投金银。"
                "灰段 = 当月没有戴金板块、持 BIL 空仓。"
                "开着金牌回退防护时，被挡下的月份左列仍是原金牌，不一定是当月 king_score 第 1 名。"
                "条带从第一个有戴金板块的月份画起——RS 要满 252 个交易日才有第一个值，"
                "窗口起点往后约一年的月份查不到 king_score，回测那几个月也躺在 BIL 上，"
                "但那是数据没热起来、不是判断出来的空仓，所以不画进条带。"
            )
        if not render_slot_segment_returns(
            _two.get("slot_equity") or [], _two.get("holdings_timeline") or [],
            _dates, _eq.get("spy", []), "gl_two", _win_lo, _win_hi, _rb_split,
            ribbons=_ribbons, ribbon_labels=("金牌", "银牌"),
        ):
            st.caption("后端暂未返回 slot_equity。")
        else:
            st.caption("橙色竖条含义同上：那几个月真的分投了金银两个板块。")

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
                "擂主留任": "、".join(r.get("leader_held_over") or []),
            } for r in reversed(_ts_rows)])
            st.dataframe(_tbl, use_container_width=True, hide_index=True, height=320)
            st.caption(f"擂主留任 = 硬排名本该换掉、但因落后第 1 名不到 {_hold_gap_txt} 继续持有的票。")
        else:
            st.caption("后端暂未返回月度明细。")

        st.markdown("##### 板块内龙头防抖对照")
        _plain = _gl.get("two_sector_plain", {}) or {}
        _lp = _gl.get("leader_pair", {}) or {}
        if not (_plain.get("available") or _lp.get("available")):
            st.caption("后端暂未返回板块内防抖对照。")
        else:
            st.caption(
                "板块怎么选和上面完全一样，只改板块内选哪只龙头。领先幅度 = "
                f"ln((100+前者5年涨幅)/(100+后者5年涨幅))。**现行**已含擂主保护（落后不到 {_hold_gap_txt} 留任）；"
                "**无防抖**是改之前的旧主线，每月硬排名；"
                f"**板块内对半**是第 1 名领先下一名不到 {_lp.get('gap', 0):.1%} 就两只各半仓。"
                "门槛 2026-10-03 从约 16% 放宽到约 28%，为的是挡住 GOOGL→META→GOOGL 这类板块内来回切，"
                "放宽后三段 Calmar 都不低于旧门槛、年化换手再低 5-10%。"
            )
            render_equity_chart(_dates, _eq, [
                ("two_sector", "现行（擂主保护）", "#F39C12", True),
                ("two_sector_plain", "无防抖（旧主线）", "#95A5A6", True),
                ("leader_pair", "板块内对半", "#9B59B6", True),
                ("spy", "SPY", "#3498DB", True),
            ], "gl_eq_leader", _win_lo, _win_hi)
            _cmp = []
            for _name, _s in (("现行（擂主保护）", _two.get("stats", {})),
                              ("无防抖（旧主线）", _plain.get("stats", {})),
                              ("板块内对半", _lp.get("stats", {}))):
                if not _s:
                    continue
                _cmp.append({
                    "口径": _name,
                    "总收益": f"{_s.get('cum_return', 0) * 100:.0f}%",
                    "CAGR": f"{_s.get('cagr', 0) * 100:.1f}%",
                    "MaxDD": f"{_s.get('max_dd', 0) * 100:.1f}%",
                    "Calmar": f"{_s.get('calmar', 0):.2f}",
                    "年化换手": f"{_s.get('ann_turnover', 0):.2f}",
                    "累计成本": f"{_s.get('cum_cost', 0) * 100:.1f}%",
                })
            st.dataframe(pd.DataFrame(_cmp), use_container_width=True, hide_index=True)
            st.caption("板块内对半是 4 个半仓位，换股次数和 2 仓位口径不可比，这里只比年化换手。"
                       "统计按整个展示窗口算，不跟随上方时间窗口滑块。")
            _diff = []
            for _label, _v in (("无防抖（旧主线）", _plain), ("板块内对半", _lp)):
                for _r in (_v.get("timeline") or []):
                    if _r.get("differs"):
                        _diff.append({"月份": _r.get("month"), "口径": _label,
                                      "现行持仓": _r.get("base_holdings"),
                                      "本口径持仓": _r.get("holdings")})
            if _diff:
                st.markdown("###### 和现行持仓不一样的月份")
                st.dataframe(pd.DataFrame(sorted(_diff, key=lambda r: r["月份"], reverse=True)),
                             use_container_width=True, hide_index=True, height=320)
                st.caption("「A/B」= 这个仓位两只各半。")
