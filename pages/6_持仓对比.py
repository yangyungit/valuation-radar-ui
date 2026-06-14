import streamlit as st
import pandas as pd
from api_client import fetch_core_data, fetch_gbdt_oos_history
import holdings_viz as hv

st.set_page_config(page_title="GBDT 持仓回放", layout="wide", page_icon="⚖️")
st.title("⚖️ Layer 6: GBDT 持仓回放（真实样本外）")
st.caption("gbdt_history_oos｜walk-forward 回放：每月只用历史数据重训，无未来函数")

core = fetch_core_data()
TIC_MAP = core.get("TIC_MAP", {})

_gbdt = fetch_gbdt_oos_history()

if not _gbdt:
    st.error(
        "🚨 **数据告警**：gbdt_history_oos 为空，无法渲染。"
        "请到 Page 3 点『🔬 生成 OOS 回放（真实样本外）』。"
    )
    st.stop()

# 系统 2026-02 才上线，更早全是用今天 universe 回填的，越往前幸存者偏差越重。
# 截到 2023-01 这条判断线之后再回测（早期污染区不展示）。
_BT_CUTOFF = "2023-01"
_gbdt = {m: v for m, v in _gbdt.items() if m.startswith("_") or m >= _BT_CUTOFF}

st.info(
    "本页是**真实样本外**回放：每个月只用该月之前的数据重训模型再选股，"
    "代表当时实际能做到的业绩。数值远低于 Page 3 回填曲线属正常——后者用全样本模型回填，含未来函数。",
    icon="📊",
)
st.warning(
    f"⚠️ 曲线从 **{_BT_CUTOFF}** 起。系统 2026-02 才上线，更早的榜单都是用今天的 universe "
    "回填的，已退市的输家不在池里（幸存者偏差），越往前越虚。2023 这条线是判断取舍，不是数据上的"
    "干净起点——即便它也带轻度偏差。",
    icon="🪦",
)


def _get_max_depth(hist: dict) -> int:
    months = sorted([k for k in hist if not k.startswith("_")], reverse=True)
    if not months:
        return 3
    latest = months[0]
    depths = [
        len(hist[latest].get(c, {}).get("tickers", []))
        for c in ["A", "B", "C", "D"]
        if hist[latest].get(c, {}).get("tickers")
    ]
    return min(depths) if depths else 3


_max_buffer_n = max(2, _get_max_depth(_gbdt))
months_all = sorted(k for k in _gbdt if not k.startswith("_"))

_BUF_DEFAULTS = {"buf_a": 6, "buf_b": 6, "buf_c": 10, "buf_d": 4}
for _bk in ("buf_a", "buf_b", "buf_c", "buf_d"):
    _pending = st.session_state.pop(f"{_bk}_auto", None)
    _v = _pending if _pending is not None else st.session_state.get(_bk)
    st.session_state[_bk] = (
        max(2, min(_BUF_DEFAULTS[_bk], _max_buffer_n)) if _v is None
        else max(2, min(int(_v), _max_buffer_n))
    )

_CASH_RATE = 0.04


def _collect_tickers(hist: dict, grade: str, top_n: int) -> set:
    tickers: set = set()
    if not hist:
        return tickers
    for m_data in hist.values():
        rec = m_data.get(grade, {})
        for r in rec.get("tickers", [])[:top_n]:
            tk = r.get("ticker", "")
            if tk:
                tickers.add(tk)
    return tickers


_ab_tickers: set = set()
for _g in ["A", "B"]:
    _ab_tickers |= _collect_tickers(_gbdt, _g, _max_buffer_n)
_cd_tickers: set = set()
for _g in ["C", "D"]:
    _cd_tickers |= _collect_tickers(_gbdt, _g, _max_buffer_n)

price_cache: dict = {}          # 周线：A/B 槽位图 + C/D 持仓过程拼接图
price_cache_daily: dict = {}    # 日线：C/D 篮子 day1 开盘买
spy_daily: pd.DataFrame = pd.DataFrame()
spy_wk: pd.DataFrame = pd.DataFrame()

with st.spinner("正在获取价格数据..."):
    try:
        spy_daily = hv.fetch_daily_ohlcv("SPY")
        spy_wk = hv.daily_to_weekly(spy_daily)
    except Exception as _e:
        st.warning(f"⚠️ SPY 价格拉取失败: {_e}")
    for _tk in sorted(_ab_tickers):
        try:
            _wkd = hv.fetch_weekly_ohlcv(_tk)
            if not _wkd.empty:
                price_cache[_tk] = _wkd
        except Exception:
            pass
    for _tk in sorted(_cd_tickers):
        try:
            _d = hv.fetch_daily_ohlcv(_tk)
            if not _d.empty:
                price_cache_daily[_tk] = _d
                price_cache[_tk] = hv.daily_to_weekly(_d)
        except Exception:
            pass

name_map: dict = dict(TIC_MAP)
for _m_data in _gbdt.values():
    for _g_nm in ["A", "B", "C", "D"]:
        for _r in _m_data.get(_g_nm, {}).get("tickers", []):
            if _r.get("ticker") and _r.get("name"):
                name_map[_r["ticker"]] = _r["name"]


def _fmt_kpi(v, fmt: str = ".2f") -> str:
    try:
        if isinstance(v, float) and (v != v or abs(v) == float("inf")):
            return "—"
        return f"{v:{fmt}}"
    except (TypeError, ValueError):
        return "—"


def _slot_navs(
    gbdt: dict, grade: str, buffer_n: int,
    price_cache: dict, spy_wk: pd.DataFrame, cash_rate: float, months: list,
    cost_bps: float = 0.0,
):
    """左右槽 NAV + 50/50 合成 NAV，供渲染与最优扫描共用。"""
    slots, _, gate_closed = hv.build_slot_assignments(gbdt, grade, buffer_n)
    months_exec = sorted(slots)
    seg_l = hv.build_slot_segments(slots, 0, months_exec)
    seg_r = hv.build_slot_segments(slots, 1, months_exec)
    ret_l, dd_l, nav_l = hv.calc_slot_stats(seg_l, price_cache, spy_wk, cash_rate, cost_bps)
    ret_r, dd_r, nav_r = hv.calc_slot_stats(seg_r, price_cache, spy_wk, cash_rate, cost_bps)

    nav_combined = pd.Series(dtype=float)
    ret_combined, dd_combined = 0.0, 0.0
    if not nav_l.empty and not nav_r.empty:
        idx_union = nav_l.index.union(nav_r.index)
        nl = nav_l.reindex(idx_union).ffill().bfill()
        nr = nav_r.reindex(idx_union).ffill().bfill()
        nav_combined = 0.5 * nl + 0.5 * nr
        ret_combined = (float(nav_combined.iloc[-1]) / float(nav_combined.iloc[0]) - 1) * 100
        peak_c = nav_combined.cummax()
        dd_combined = float(
            ((peak_c - nav_combined) / peak_c.replace(0, float("nan"))).max()
        ) * 100
    elif not nav_l.empty:
        nav_combined, ret_combined, dd_combined = nav_l.copy(), ret_l, dd_l
    elif not nav_r.empty:
        nav_combined, ret_combined, dd_combined = nav_r.copy(), ret_r, dd_r

    return seg_l, seg_r, nav_l, nav_r, nav_combined, ret_combined, dd_combined, gate_closed


def _calmar_of(nav: pd.Series) -> float:
    if nav is None or nav.empty:
        return float("nan")
    cal = hv.compute_nav_kpi(nav).get("calmar", float("nan"))
    return cal if (cal == cal and abs(cal) != float("inf")) else float("nan")


def _best_buffer_slot(
    gbdt: dict, grade: str, price_cache: dict,
    spy_wk: pd.DataFrame, cash_rate: float, max_n: int, months: list,
    cost_bps: float = 0.0,
) -> int | None:
    best_n, best_cal = None, float("-inf")
    for n in range(2, max_n + 1):
        nav_c = _slot_navs(
            gbdt, grade, n, price_cache, spy_wk, cash_rate, months, cost_bps)[4]
        cal = _calmar_of(nav_c)
        if cal == cal and cal > best_cal:
            best_cal, best_n = cal, n
    return best_n


def _best_buffer_basket(
    gbdt: dict, grade: str, price_cache_daily: dict,
    spy_daily: pd.DataFrame, cash_rate: float, max_n: int,
    cost_bps: float = 0.0, rebalance_step: int = 1,
) -> int | None:
    best_n, best_cal = None, float("-inf")
    for n in range(2, max_n + 1):
        r = hv.build_basket_nav(
            gbdt, grade, price_cache_daily, spy_daily, top_n=2, cash_rate=cash_rate,
            buffer_n=n, cost_bps=cost_bps, rebalance_step=rebalance_step,
        )
        cal = _calmar_of(r["nav"])
        if cal == cal and cal > best_cal:
            best_cal, best_n = cal, n
    return best_n


def _render_slot(
    gbdt: dict, grade: str,
    _buffer_n: int, _price_cache: dict,
    _spy_wk: pd.DataFrame, _name_map: dict, _cash_rate: float,
    _cost_bps: float = 0.0,
) -> None:
    months = sorted(k for k in gbdt if not k.startswith("_"))
    if len(months) < 2:
        st.info("数据不足（月份 < 2）")
        return

    (seg_l, seg_r, nav_l, nav_r, nav_combined,
     ret_combined, dd_combined, gate_closed) = _slot_navs(
        gbdt, grade, _buffer_n, _price_cache, _spy_wk, _cash_rate, months, _cost_bps,
    )

    kpi = hv.compute_nav_kpi(nav_combined) if not nav_combined.empty else {}
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总收益", f"{ret_combined:+.1f}%")
    c2.metric("最大回撤", f"-{dd_combined:.1f}%")
    c3.metric("Calmar", _fmt_kpi(kpi.get("calmar", float("nan"))))
    c4.metric("Sortino", _fmt_kpi(kpi.get("sortino", float("nan"))))
    c5.metric("logR²", _fmt_kpi(kpi.get("r2", float("nan"))))

    if gate_closed:
        with st.expander(f"⚠️ {grade} 组历史闸门关（{len(gate_closed)} 个月）", expanded=False):
            for gm, gr in gate_closed:
                st.markdown(f"- **{gm}**：{gr or '不满足持仓条件'}")

    fig_combined = hv.build_combined_fig(
        nav_l, nav_r, nav_combined, _spy_wk,
        f"GBDT {grade} — A 曲线（左+右 50/50 合成）vs SPY",
    )
    st.plotly_chart(fig_combined, use_container_width=True, key=f"{grade}_gbdt_combined")

    fig_l = hv.build_stitched_fig(
        seg_l, f"GBDT {grade} 左列 (Slot 0)",
        _spy_wk, _price_cache, _name_map,
    )
    fig_r = hv.build_stitched_fig(
        seg_r, f"GBDT {grade} 右列 (Slot 1)",
        _spy_wk, _price_cache, _name_map,
    )
    st.plotly_chart(fig_l, use_container_width=True, key=f"{grade}_gbdt_slot0")
    st.plotly_chart(fig_r, use_container_width=True, key=f"{grade}_gbdt_slot1")


def _render_basket(
    gbdt: dict, grade: str,
    _price_cache: dict, _price_cache_daily: dict,
    _spy_daily: pd.DataFrame, _spy_wk: pd.DataFrame,
    _name_map: dict, _cash_rate: float,
    _buffer_n: int | None = None, _cost_bps: float = 0.0,
    _rebalance_step: int = 1,
) -> None:
    _freq_cn = "季度" if _rebalance_step == 3 else "月度"
    st.markdown(f"**GBDT · 等权 top-2 篮子（{_freq_cn}调仓，日1开盘买，已顺延1月去 look-ahead）**")
    months = sorted(k for k in gbdt if not k.startswith("_"))
    if len(months) < 2:
        st.info("数据不足（月份 < 2）")
        return

    r = hv.build_basket_nav(
        gbdt, grade, _price_cache_daily, _spy_daily, top_n=2, cash_rate=_cash_rate,
        buffer_n=_buffer_n, cost_bps=_cost_bps, rebalance_step=_rebalance_step,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("总收益", f"{r['total_ret']:+.1f}%")
    c2.metric("最大回撤", f"-{r['max_dd']:.1f}%")
    c3.metric(f"{_freq_cn[0]}均换手", f"{r['turnover_pct']:.0f}%")

    kpi = hv.compute_nav_kpi(r["nav"]) if not r["nav"].empty else {}
    ck1, ck2, ck3 = st.columns(3)
    ck1.metric("Calmar", _fmt_kpi(kpi.get("calmar", float("nan"))))
    ck2.metric("Sortino", _fmt_kpi(kpi.get("sortino", float("nan"))))
    ck3.metric("logR²", _fmt_kpi(kpi.get("r2", float("nan"))))

    if not r["nav"].empty:
        st.plotly_chart(
            hv.build_basket_fig(r["nav"], _spy_wk, f"GBDT {grade} 篮子"),
            use_container_width=True,
            key=f"{grade}_gbdt_basket",
        )
    else:
        st.info("暂无足够数据生成图表。")

    _exec_months = sorted(r["monthly_holdings"])
    st.markdown(f"**持仓过程（top-2 拆成左右两列，{_freq_cn}再平衡）**")
    slots = hv.build_basket_slot_assignments(r["monthly_holdings"], _exec_months)
    seg_l = hv.build_slot_segments(slots, 0, _exec_months)
    seg_r = hv.build_slot_segments(slots, 1, _exec_months)
    fig_l = hv.build_stitched_fig(
        seg_l, f"GBDT {grade} 左列（top-1）",
        _spy_wk, _price_cache, _name_map,
    )
    fig_r = hv.build_stitched_fig(
        seg_r, f"GBDT {grade} 右列（top-2）",
        _spy_wk, _price_cache, _name_map,
    )
    st.plotly_chart(fig_l, use_container_width=True, key=f"{grade}_basket_slot0")
    st.plotly_chart(fig_r, use_container_width=True, key=f"{grade}_basket_slot1")


# A/B/C/D 各档默认单边成本：波动级别不同，滑点不可能相同。
# A=蓝筹低点差，B=中盘，C=小盘/高波动季度篮，D=短动量月度高换手点差最大。各自可调。
_COST_DEFAULTS = {"A": 10.0, "B": 30.0, "C": 80.0, "D": 100.0}


def _cost_input(grade: str, key: str) -> float:
    """单档换仓成本输入（单边 bps，买卖各扣一次）。"""
    v = float(st.number_input(
        f"{grade} 档换仓成本（单边 bps，买卖各扣一次）",
        min_value=0.0, max_value=500.0, value=_COST_DEFAULTS[grade], step=5.0,
        key=key,
        help="月度颗粒度抓不到日内/周内闪崩，真实点差+滑点建议调大留余量。"
             "归零可还原未计成本的旧曲线。",
    ))
    st.caption(
        f"当前 {grade} 单边 {v:.0f} bps（一次完整换仓 = 卖+买 = {v * 2:.0f} bps）。"
    )
    return v


def _topn_control(grade: str, key: str, is_basket: bool, cost_bps: float,
                  rebalance_step: int = 1) -> None:
    """单档 Top-N 控件：number_input + 自动选最优按钮（按 Calmar 穷举扫描）。
    自动值写临时 key + rerun，由页首在 widget 实例化前应用，避开 Streamlit
    『widget 实例化后不能改同名 session_state』限制。"""
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.number_input(
            f"守擂缓冲区 Top-N（上限 {_max_buffer_n}）",
            min_value=2, max_value=_max_buffer_n, step=1, key=key,
        )
    with c2:
        st.write("")
        if st.button("🎯 自动选最优 (Calmar)", key=f"auto_{key}", use_container_width=True):
            with st.spinner("扫描 Top-N…"):
                best = (
                    _best_buffer_basket(
                        _gbdt, grade, price_cache_daily, spy_daily, _CASH_RATE,
                        _max_buffer_n, cost_bps, rebalance_step)
                    if is_basket else
                    _best_buffer_slot(
                        _gbdt, grade, price_cache, spy_wk, _CASH_RATE,
                        _max_buffer_n, months_all, cost_bps)
                )
            if best:
                st.session_state[f"{key}_auto"] = best
                st.rerun()
    st.caption("⚠️ 自动值是样本内回看挑 Calmar 最高（已计入本档换仓成本），有过拟合风险，仅供参考。")


tab_a, tab_b, tab_c, tab_d = st.tabs(
    ["🛡️ A 档", "🏦 B 档", "👑 C 档（季度）", "🚀 D 档（月度自营）"])
with tab_a:
    _cost_a = _cost_input("A", "cost_a")
    _topn_control("A", "buf_a", is_basket=False, cost_bps=_cost_a)
    _render_slot(
        _gbdt, "A", st.session_state["buf_a"],
        price_cache, spy_wk, name_map, _CASH_RATE, _cost_a)
with tab_b:
    _cost_b = _cost_input("B", "cost_b")
    _topn_control("B", "buf_b", is_basket=False, cost_bps=_cost_b)
    _render_slot(
        _gbdt, "B", st.session_state["buf_b"],
        price_cache, spy_wk, name_map, _CASH_RATE, _cost_b)
with tab_c:
    st.caption("C = 超长动量（252d）。季度调仓、日1开盘买、卖出一日卖。低换手、抗进场时机。")
    _cost_c = _cost_input("C", "cost_c")
    _topn_control("C", "buf_c", is_basket=True, cost_bps=_cost_c, rebalance_step=3)
    _render_basket(
        _gbdt, "C", price_cache, price_cache_daily, spy_daily, spy_wk,
        name_map, _CASH_RATE, st.session_state["buf_c"], _cost_c, _rebalance_step=3)
with tab_d:
    st.caption("D = 短动量自营（信号头几天就得进场）。月度调仓、日1开盘买、卖出一日卖。高换手、收益高、回撤大。")
    _cost_d = _cost_input("D", "cost_d")
    _topn_control("D", "buf_d", is_basket=True, cost_bps=_cost_d, rebalance_step=1)
    _render_basket(
        _gbdt, "D", price_cache, price_cache_daily, spy_daily, spy_wk,
        name_map, _CASH_RATE, st.session_state["buf_d"], _cost_d, _rebalance_step=1)
