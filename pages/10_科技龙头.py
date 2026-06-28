import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_tech_leader_relay_timeseries, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="科技龙头", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 科技龙头接力图 (Tech Leader Relay)")
st.caption(
    "**池子**:美股 + 美股 ADR 的科技龙头(半导体/软件云/平台/硬件支付),**不要求真回购**,含 NVDA / SaaS / 成长股。"
    "与「回购进攻」页独立,不混池(回购管防御腿、本页看进攻腿)。"
    "**两层**:先过**慢变量门槛**(营收 TTM YoY 增速 > 0 且近 2 季加速度 ≥ 0,砍掉增速塌掉的伪龙头),"
    "存活者再按 **king_score = Z(RS_210d)** 纯动量排名(窗口 210 日)。门槛逐月生效、无 look-ahead。"
    "**🥇 金牌 = 当月 Top1 且 RS_210d > 0(跑赢 SPY,否则降灰)/🥈 银牌 = Top2**。"
    "下方持有**金+银两个仓位等权**,月末选仓、顺延 1 月执行(去 look-ahead)。"
)

with st.sidebar:
    if st.button("🔄 强制刷新科技龙头数据"):
        fetch_tech_leader_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=1, horizontal=True, key="tl_window")

with st.spinner("📊 加载科技龙头接力数据..."):
    ts = fetch_tech_leader_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_tech_leader_relay_timeseries("10Y")

if not ts.get("success"):
    st.error(f"⚠️ 科技龙头接力数据暂不可用:{ts.get('error', '未知错误')}")
    st.stop()

_tickers = ts.get("tickers", {}) or {}
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 时序数据为空")
    st.stop()

_idx = pd.to_datetime(_dates, errors="coerce")
king = pd.DataFrame({tk: p.get("king_score", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
adv = pd.DataFrame({tk: p.get("adv_63d", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
rev_yoy = pd.DataFrame({tk: p.get("rev_yoy", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
rev_accel = pd.DataFrame({tk: p.get("rev_accel_2q", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
# 慢变量 gate：True/False/None → 1/0/NaN（None = 缺基本面，放行不刷）
gate = pd.DataFrame(
    {tk: [1.0 if v is True else (0.0 if v is False else np.nan) for v in p.get("gate_pass", [])]
     for tk, p in _tickers.items()},
    index=_idx,
)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

king_m = king.resample("ME").last()
rs_m = rs.resample("ME").last()
adv_m = adv.resample("ME").last()
gate_m = gate.resample("ME").last()
rev_yoy_m = rev_yoy.resample("ME").last()
rev_accel_m = rev_accel.resample("ME").last()
# 慢变量 gate 逐月生效：某票某月没过门(gate_m==0)就把那月 king_score 置 NaN，
# 它当月排不进 Top2、历史回排也用各月真实门槛（无 look-ahead）。缺基本面(NaN)放行。
_gate_fail = gate_m.reindex(index=king_m.index, columns=king_m.columns) == 0
king_m = king_m.mask(_gate_fail)
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

with st.spinner("📊 加载价格..."):
    _pool = list(_tickers.keys())
    _px = get_global_data(_pool + ["SPY"], years=10)

_price_cache: dict = {}
_spy_wk = pd.DataFrame()
if _px is not None and not _px.empty:
    _wk = _px.resample("W-FRI").last()
    if "SPY" in _wk.columns:
        _spy_wk = _wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
    for _tk in _pool:
        if _tk in _wk.columns:
            _s = _wk[_tk].dropna()
            if len(_s) >= 2:
                _price_cache[_tk] = _s.to_frame(name="Close")

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
)


def _long_king_m():
    """从 10Y 长历史构造月末 king_score，供 δ 稳健性扫描切尾部 3/5/10Y。失败返回 None。"""
    if window == "10Y":
        return king_m
    if not (isinstance(ts_long, dict) and ts_long.get("success")):
        return None
    _tk_l = ts_long.get("tickers", {}) or {}
    _dt_l = ts_long.get("dates", []) or []
    if not _tk_l or not _dt_l:
        return None
    _ix_l = pd.to_datetime(_dt_l, errors="coerce")
    _king_l = pd.DataFrame(
        {tk: p.get("king_score", []) for tk, p in _tk_l.items()}, index=_ix_l
    ).astype(float).resample("ME").last()
    _gate_l = pd.DataFrame(
        {tk: [1.0 if v is True else (0.0 if v is False else np.nan) for v in p.get("gate_pass", [])]
         for tk, p in _tk_l.items()},
        index=_ix_l,
    ).resample("ME").last()
    return _king_l.mask(_gate_l.reindex(index=_king_l.index, columns=_king_l.columns) == 0)


king_m_long = _long_king_m()

_all_cols = list(king_m.columns)
_SECTORS = ["半导体", "软件云", "平台", "硬件支付"]
_view = st.radio(
    "看哪一组(横截面排名母体)", ["全科技龙头"] + _SECTORS,
    index=0, horizontal=True, key="tl_view",
)
if _view == "全科技龙头":
    _cols = _all_cols
    _label = "全科技龙头"
else:
    _cols = [c for c in _all_cols if grade_map.get(c) == _view]
    _label = _view

st.markdown(f"## 🚀 {_label}组（{len(_cols)} 只）")
st.caption("切换上方分组 = 换横截面排名母体：全池 = 47 只一起排 Top2；单赛道 = 只在该赛道内排 Top2。")

# 慢变量门槛体检：本月母体内谁被刷掉、谁缺基本面放行（透明展示，不做黑盒）
_gm_last = gate_m.iloc[-1] if not gate_m.empty else pd.Series(dtype=float)
_yoy_last = rev_yoy_m.iloc[-1] if not rev_yoy_m.empty else pd.Series(dtype=float)
_acc_last = rev_accel_m.iloc[-1] if not rev_accel_m.empty else pd.Series(dtype=float)
_gated_out = [c for c in _cols if _gm_last.get(c) == 0]
_passed = [c for c in _cols if _gm_last.get(c) == 1]
_no_data = [c for c in _cols if c in _gm_last.index and pd.isna(_gm_last.get(c))]
st.caption(
    f"🚦 **慢变量门槛**（营收 TTM YoY 增速 > 0 且近 2 季加速度 ≥ 0）：本月母体 {len(_cols)} 只 → "
    f"过门 **{len(_passed)}** 只参与排名，刷掉 {len(_gated_out)} 只，缺基本面放行 {len(_no_data)} 只。"
    "门槛逐月生效、月末取值顺延执行，被刷的月份 king_score 置空、自动排不进金银牌。"
)
with st.expander(f"🚦 本月门槛体检（刷掉 {len(_gated_out)} · 放行 {len(_no_data)} 缺数据）"):
    def _gate_tbl(_list):
        return pd.DataFrame([{
            "股票": f"{t}({grade_map.get(t, '')})" if grade_map.get(t) else t,
            "名称": name_map.get(t, t),
            "营收YoY增速%": round(float(_yoy_last[t]), 1) if t in _yoy_last.index and pd.notna(_yoy_last.get(t)) else None,
            "近2季加速度": round(float(_acc_last[t]), 1) if t in _acc_last.index and pd.notna(_acc_last.get(t)) else None,
        } for t in _list])
    if _gated_out:
        st.markdown("**被刷掉（增速塌掉或减速）**")
        st.dataframe(_gate_tbl(_gated_out), use_container_width=True, hide_index=True)
    if _no_data:
        st.markdown("**缺基本面数据 → 放行不刷**（SF1 无营收，多为部分 ADR / 次新股）")
        st.caption("、".join(_no_data))

render_group(_label, _cols, "tl_main",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="king_score", score_fmt="{:+.2f}",
             default_k=0.75, **_COMMON)
