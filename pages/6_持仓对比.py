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

st.info(
    "本页是**真实样本外**回放：每个月只用该月之前的数据重训模型再选股，"
    "代表当时实际能做到的业绩。曲线起点晚于回填页（头两年训练数据不足被切掉），"
    "数值远低于 Page 3 回填曲线属正常——后者用全样本模型回填，含未来函数。",
    icon="📊",
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

for _bk in ("buf_a", "buf_b", "buf_c"):
    _v = st.session_state.get(_bk)
    st.session_state[_bk] = (
        min(6, _max_buffer_n) if _v is None
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


all_tickers: set = set()
for _g in ["A", "B", "C"]:
    all_tickers |= _collect_tickers(_gbdt, _g, _max_buffer_n)

price_cache: dict = {}
spy_wk: pd.DataFrame = pd.DataFrame()

with st.spinner("正在获取价格数据..."):
    try:
        spy_wk = hv.fetch_weekly_ohlcv("SPY")
    except Exception as _e:
        st.warning(f"⚠️ SPY 价格拉取失败: {_e}")
    for _tk in sorted(all_tickers):
        try:
            _wkd = hv.fetch_weekly_ohlcv(_tk)
            if not _wkd.empty:
                price_cache[_tk] = _wkd
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
):
    """左右槽 NAV + 50/50 合成 NAV，供渲染与最优扫描共用。"""
    slots, _, gate_closed = hv.build_slot_assignments(gbdt, grade, buffer_n)
    seg_l = hv.build_slot_segments(slots, 0, months)
    seg_r = hv.build_slot_segments(slots, 1, months)
    ret_l, dd_l, nav_l = hv.calc_slot_stats(seg_l, price_cache, spy_wk, cash_rate)
    ret_r, dd_r, nav_r = hv.calc_slot_stats(seg_r, price_cache, spy_wk, cash_rate)

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
) -> int | None:
    best_n, best_cal = None, float("-inf")
    for n in range(2, max_n + 1):
        nav_c = _slot_navs(gbdt, grade, n, price_cache, spy_wk, cash_rate, months)[4]
        cal = _calmar_of(nav_c)
        if cal == cal and cal > best_cal:
            best_cal, best_n = cal, n
    return best_n


def _best_buffer_basket(
    gbdt: dict, grade: str, price_cache: dict,
    spy_wk: pd.DataFrame, cash_rate: float, max_n: int,
) -> int | None:
    best_n, best_cal = None, float("-inf")
    for n in range(2, max_n + 1):
        r = hv.build_basket_nav(
            gbdt, grade, price_cache, spy_wk, top_n=2, cash_rate=cash_rate, buffer_n=n,
        )
        cal = _calmar_of(r["nav"])
        if cal == cal and cal > best_cal:
            best_cal, best_n = cal, n
    return best_n


def _render_slot(
    gbdt: dict, grade: str,
    _buffer_n: int, _price_cache: dict,
    _spy_wk: pd.DataFrame, _name_map: dict, _cash_rate: float,
) -> None:
    months = sorted(k for k in gbdt if not k.startswith("_"))
    if len(months) < 2:
        st.info("数据不足（月份 < 2）")
        return

    (seg_l, seg_r, nav_l, nav_r, nav_combined,
     ret_combined, dd_combined, gate_closed) = _slot_navs(
        gbdt, grade, _buffer_n, _price_cache, _spy_wk, _cash_rate, months,
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
    _price_cache: dict, _spy_wk: pd.DataFrame, _name_map: dict, _cash_rate: float,
    _buffer_n: int | None = None,
) -> None:
    st.markdown("**GBDT · 等权 top-2 篮子**")
    months = sorted(k for k in gbdt if not k.startswith("_"))
    if len(months) < 2:
        st.info("数据不足（月份 < 2）")
        return

    r = hv.build_basket_nav(
        gbdt, grade, _price_cache, _spy_wk, top_n=2, cash_rate=_cash_rate,
        buffer_n=_buffer_n,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("总收益", f"{r['total_ret']:+.1f}%")
    c2.metric("最大回撤", f"-{r['max_dd']:.1f}%")
    c3.metric("月均换手", f"{r['turnover_pct']:.0f}%")

    kpi = hv.compute_nav_kpi(r["nav"]) if not r["nav"].empty else {}
    ck1, ck2, ck3 = st.columns(3)
    ck1.metric("Calmar", _fmt_kpi(kpi.get("calmar", float("nan"))))
    ck2.metric("Sortino", _fmt_kpi(kpi.get("sortino", float("nan"))))
    ck3.metric("logR²", _fmt_kpi(kpi.get("r2", float("nan"))))

    if not r["nav"].empty:
        st.plotly_chart(
            hv.build_basket_fig(r["nav"], _spy_wk, "GBDT C 篮子"),
            use_container_width=True,
            key="C_gbdt_basket",
        )
    else:
        st.info("暂无足够数据生成图表。")

    st.markdown("**持仓过程（每月 top-2 拆成左右两列，月度再平衡）**")
    slots = hv.build_basket_slot_assignments(r["monthly_holdings"], months)
    seg_l = hv.build_slot_segments(slots, 0, months)
    seg_r = hv.build_slot_segments(slots, 1, months)
    fig_l = hv.build_stitched_fig(
        seg_l, f"GBDT {grade} 左列（每月 top-1）",
        _spy_wk, _price_cache, _name_map,
    )
    fig_r = hv.build_stitched_fig(
        seg_r, f"GBDT {grade} 右列（每月 top-2）",
        _spy_wk, _price_cache, _name_map,
    )
    st.plotly_chart(fig_l, use_container_width=True, key=f"{grade}_basket_slot0")
    st.plotly_chart(fig_r, use_container_width=True, key=f"{grade}_basket_slot1")


st.markdown(f"**守擂缓冲区 Top-N（A/B/C 各自独立，数据深度上限 {_max_buffer_n}）**")
_cc1, _cc2, _cc3, _cc4 = st.columns([1, 1, 1, 1.6])
with _cc1:
    st.number_input("🛡️ A 档", min_value=2, max_value=_max_buffer_n, step=1, key="buf_a")
with _cc2:
    st.number_input("🏦 B 档", min_value=2, max_value=_max_buffer_n, step=1, key="buf_b")
with _cc3:
    st.number_input("🚀 C 档", min_value=2, max_value=_max_buffer_n, step=1, key="buf_c")
with _cc4:
    st.write("")
    if st.button("🎯 自动选最优 (Calmar)", use_container_width=True):
        with st.spinner("扫描各档 Top-N…"):
            _ba = _best_buffer_slot(
                _gbdt, "A", price_cache, spy_wk, _CASH_RATE, _max_buffer_n, months_all)
            _bb = _best_buffer_slot(
                _gbdt, "B", price_cache, spy_wk, _CASH_RATE, _max_buffer_n, months_all)
            _bc = _best_buffer_basket(
                _gbdt, "C", price_cache, spy_wk, _CASH_RATE, _max_buffer_n)
        if _ba:
            st.session_state["buf_a"] = _ba
        if _bb:
            st.session_state["buf_b"] = _bb
        if _bc:
            st.session_state["buf_c"] = _bc
        st.rerun()
st.caption(
    "⚠️ 自动值是在这段 OOS 窗口内回看挑 Calmar 最高，属样本内最优，有过拟合风险，仅供参考。"
)

tab_a, tab_b, tab_c = st.tabs(["🛡️ A 档", "🏦 B 档", "🚀 C 档"])
with tab_a:
    _render_slot(
        _gbdt, "A", st.session_state["buf_a"],
        price_cache, spy_wk, name_map, _CASH_RATE)
with tab_b:
    _render_slot(
        _gbdt, "B", st.session_state["buf_b"],
        price_cache, spy_wk, name_map, _CASH_RATE)
with tab_c:
    _render_basket(
        _gbdt, "C", price_cache, spy_wk, name_map, _CASH_RATE,
        st.session_state["buf_c"])
