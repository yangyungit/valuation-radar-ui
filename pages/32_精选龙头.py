import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import fetch_dynasty_gold_leader
from gold_leader_viz import (
    INSIGHT_CSS, WINDOWS, norm_series, render_equity_chart, render_holding_cards,
    render_meta_captions, render_slot_segment_returns, render_stats_cards,
    render_time_window_slider, show_missing_warning, split_month_spans,
)

st.set_page_config(page_title="精选龙头", layout="wide")
st.markdown(INSIGHT_CSS, unsafe_allow_html=True)

_MIN_HOLD_DEFAULT = 9
_LOCK_COLOR = "#2ECC71"

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_dynasty_gold_leader.clear()
        st.rerun()

st.title("🎯 精选龙头 (Selected Leaders)")
st.caption(
    "**= 戴金龙头主线 + 每只票最短持有 9 个月。** 板块怎么选（金银牌、滞回、名次死区、金牌回退防护）、"
    "板块内选谁（市值前 3 选 5 年超额 Top2、擂主保护）、无戴金板块转 BIL，全部和 21 页一样；"
    "唯一多的一条：主线想换掉一只持了不到 9 个月的票时不让换，持满再说。退市/被收购的票不受此保护。"
    "**诚实声明**：信号不看未来、次日成交、扣成本；池 = 逐月真实标普 500 成分（含退市，已去生存者偏差）；研究原型，非真实业绩。"
)
st.caption(
    "**为什么是 9**：N=7/8/9 在 2016-09~2020-09 九个错开起点、逐年剔除（含剔 2021）下 Calmar 都不低于主线，"
    "N≥10 把 2021 拿掉就输给主线；9 是三档里换手最低的。10Y 实测换股 39→21、年化换手 2.16→1.23、"
    "Calmar 0.95→1.25。但多赚的部分主要来自 2021 年 NVDA/TSLA 没被换掉，剔掉 2021 只多赚 11%——"
    "这条规则的可信之处是**少换**，不是**多赚**。"
)

_window = st.radio("时间跨度", options=WINDOWS, index=WINDOWS.index("5Y"), horizontal=True,
                   key="sl_window", help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子")
_c1, _c2 = st.columns([1.1, 2.0])
with _c1:
    _rebal = st.toggle("月度等权再平衡", value=True, key="sl_rebal",
                       help="每月把两个槽位拉回 50/50。所有验证都是开着再平衡做的，关掉的结果没验证过。")
with _c2:
    st.caption("持满 9 个月的计法：买入当月记 1，第 9 个决策月起可换。当月无戴金板块全 BIL 时不锁、重新计数。")
with st.expander("交易假设"):
    _cost = st.slider("单边成本 (bps)", 0, 50, 10, key="sl_cost")
    _min_hold = st.slider(
        "最短持有月数", 4, 12, _MIN_HOLD_DEFAULT, key="sl_min_hold",
        help="默认 9。7~9 在稳健性检验里是一个平台，不是 9 独好；≤6 比主线差，≥10 剔掉 2021 就输。"
             "拖这个滑块只为看敏感度，不建议改默认值。",
    )

_gl = fetch_dynasty_gold_leader(window=_window, rebalance=_rebal, cost_bps=float(_cost),
                                min_hold=int(_min_hold))
if not _gl.get("success"):
    st.warning(f"⚠️ 精选龙头回测暂不可用：{_gl.get('error', '未知错误')}")
    st.stop()

_meta = _gl.get("meta", {})
render_meta_captions(_meta, _window)
_lk = _gl.get("two_sector_locked") or {}
_two = _gl.get("two_sector") or {}
if not _lk.get("available"):
    st.info("后端未返回精选龙头口径（`two_sector_locked`），可能是后端版本较旧。")
    st.stop()
show_missing_warning(_lk)

_signal_as_of = str(_meta.get("signal_as_of", "") or "")
_signal_month = _signal_as_of[:7] if _signal_as_of else "最近信号"
_eq = dict(_gl.get("equity", {}))
_dates = pd.to_datetime(_gl.get("dates", []), errors="coerce")
_disp = str(_meta.get("display_start", ""))[:7]
_lk_rows = [r for r in (_gl.get("two_sector_locked_timeline") or []) if r.get("month", "") >= _disp]
_locked_exec_months = {
    str(r.get("execution_date", "") or "")[:7] for r in _lk_rows if r.get("min_hold_blocked")
}

st.markdown(f"##### 截至 {_signal_month} 信号的模拟持仓｜精选龙头")
render_holding_cards(
    (_lk.get("current_holdings") or {}).get("slots", []),
    "当月无 C 组戴金板块或无足够龙头候选",
)

_win_lo, _win_hi = render_time_window_slider(_dates, "sl")

st.markdown("##### 组合收益（起点归一为 1）")
_eq_plot = dict(_eq)
for _row in (_lk.get("slot_equity") or []):
    _eq_plot[f"slot{int(_row.get('slot', 0))}"] = _row.get("equity", [])
render_equity_chart(_dates, _eq_plot, [
    ("two_sector_locked", f"精选龙头（主线 + 最短持有 {_min_hold} 月）", _LOCK_COLOR, True),
    ("two_sector", "戴金龙头主线", "#F39C12", True),
    ("spy", "SPY", "#3498DB", True),
    ("slot0", "槽A", "rgba(46,204,113,0.55)", False, "dot"),
    ("slot1", "槽B", "rgba(170,178,189,0.75)", False, "dot"),
], "sl_eq", _win_lo, _win_hi, split_month_spans(_locked_exec_months, _win_lo, _win_hi),
    shade_color=_LOCK_COLOR)
st.caption("绿色竖条 = 那个月主线想换票、被最短持有期按住了。两条实线起点归一为 1。")

st.markdown("##### 统计卡（精选龙头）")
_stats = dict(_lk.get("stats") or {})
_nav = norm_series(_eq.get("two_sector_locked"), _dates)
if not _nav.empty:
    _stats["r2"] = hv.compute_nav_kpi(_nav).get("r2")
render_stats_cards(_stats)

st.markdown("##### 和主线对照（整个展示窗口）")
_cmp = []
for _name, _s in (("精选龙头", _lk.get("stats") or {}), ("戴金龙头主线", _two.get("stats") or {})):
    if not _s:
        continue
    _cmp.append({
        "口径": _name,
        "总收益": f"{_s.get('cum_return', 0) * 100:.0f}%",
        "CAGR": f"{_s.get('cagr', 0) * 100:.1f}%",
        "MaxDD": f"{_s.get('max_dd', 0) * 100:.1f}%",
        "Calmar": f"{_s.get('calmar', 0):.2f}",
        "换股次数": f"{_s.get('n_swaps', 0)}",
        "平均持有(月)": f"{_s.get('avg_hold_months', 0)}",
        "年化换手": f"{_s.get('ann_turnover', 0):.2f}",
        "累计成本": f"{_s.get('cum_cost', 0) * 100:.1f}%",
    })
st.dataframe(pd.DataFrame(_cmp), use_container_width=True, hide_index=True)
st.caption(
    f"展示期内 {_lk.get('locked_months', 0)} 个月有换股被按住，共按住 {_lk.get('blocked_swaps', 0)} 笔；"
    f"和主线持仓不同的月份 {len(_lk.get('diff_months') or [])} 个。统计按整个展示窗口算，不跟随时间窗口滑块。"
)

st.markdown("##### Slot 分段收益")
if not render_slot_segment_returns(
    _lk.get("slot_equity") or [], _lk.get("holdings_timeline") or [],
    _dates, _eq.get("spy", []), "sl", _win_lo, _win_hi, _locked_exec_months,
):
    st.caption("后端暂未返回 slot_equity。")
else:
    st.caption("绿色竖条含义同上。")

st.markdown("##### 月度明细")
if _lk_rows:
    _tbl = pd.DataFrame([{
        "月份": r.get("month"),
        "金牌板块": r.get("sector_etf") or "—",
        "银牌板块": r.get("silver_sector_etf") or "—",
        "持仓": " + ".join(r.get("picks") or []),
        "被按住的换股": "、".join(f"{b['kept']}←{b['wanted']}" for b in (r.get("min_hold_blocked") or [])),
        "擂主留任": "、".join(r.get("leader_held_over") or []),
        "数据缺失": "、".join(r.get("data_missing") or []),
    } for r in reversed(_lk_rows)])
    st.dataframe(_tbl, use_container_width=True, hide_index=True, height=320)
    st.caption(f"被按住的换股「A←B」= 主线这个月想把 A 换成 B，A 持了不到 {_min_hold} 个月没换成。")
else:
    st.caption("后端暂未返回月度明细。")

_diff = _lk.get("diff_months") or []
if _diff:
    st.markdown("###### 和主线持仓不一样的月份")
    st.dataframe(pd.DataFrame([{
        "月份": d.get("month"), "主线持仓": d.get("base"), "精选龙头持仓": d.get("locked"),
    } for d in reversed(_diff)]), use_container_width=True, hide_index=True, height=320)
    st.caption("锁一次之后擂主保护保护的也是实际持有的票，后面整条路径都会不同，不只是被按住的那几个月。")
