import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_factor_relay_timeseries, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="因子轮动", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🔄 因子 ETF 轮动接力 (Factor Rotation Relay)")
st.caption(
    "**池子**：美股因子 ETF（动量 / 价值 / 质量 / 低波 / 成长 / 高股息 / 小盘 / 等权 / 高Beta），对标 SPY。"
    "**排名**：全池横截面 **king_score = Z(RS_252d)**——纯动量，看谁跑赢 SPY 最多（年化）。"
    "**🥇 金牌 = 当月 Top1 且 RS_252d > 0（跑赢 SPY，否则降灰）/🥈 银牌 = Top2**。"
    "下方持有**金+银两仓等权**，月末选仓、次交易日开盘执行（去 look-ahead）。"
)

with st.sidebar:
    if st.button("🔄 强制刷新因子 ETF 数据"):
        fetch_factor_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=1, horizontal=True, key="fac_window")

with st.spinner("📊 加载因子 ETF 数据..."):
    ts = fetch_factor_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_factor_relay_timeseries("10Y")

if not ts.get("success"):
    st.error(f"⚠️ 因子 ETF 数据暂不可用：{ts.get('error', '未知错误')}")
    st.stop()

_tickers = ts.get("tickers", {}) or {}
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 时序数据为空")
    st.stop()

_idx = pd.to_datetime(_dates, errors="coerce")
rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")


def _zrows(df: pd.DataFrame) -> pd.DataFrame:
    """逐行（每个月末）做横截面 Z-Score。"""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, np.nan), axis=0)


def _king(_rs_m: pd.DataFrame) -> pd.DataFrame:
    """king_score = Z(RS)，纯动量。"""
    return _zrows(_rs_m)


rs_m = rs.resample("ME").last()
king_m = _king(rs_m)
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

# ── 价格（全池一次拉好，喂净值重建；同 Page 6/7/8）──
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


def _king_long():
    """从 10Y 长历史构造月末 king_score，供 δ 稳健性扫描切尾部 3/5/10Y。"""
    if window == "10Y":
        return king_m
    if not (isinstance(ts_long, dict) and ts_long.get("success")):
        return None
    _tk_l = ts_long.get("tickers", {}) or {}
    _dt_l = ts_long.get("dates", []) or []
    if not _tk_l or not _dt_l:
        return None
    _ix_l = pd.to_datetime(_dt_l, errors="coerce")
    _rs_l = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tk_l.items()}, index=_ix_l).astype(float).resample("ME").last()
    return _king(_rs_l)


king_m_long = _king_long()

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="king_score", score_fmt="{:+.2f}",
)

_all_cols = list(king_m.columns)
st.markdown("## 🔄 全因子 ETF 轮动（纯动量）")
render_group("因子 ETF", _all_cols, "fac_all",
             score_m=king_m, sweep_score_m=king_m_long, default_k=0.75, **_COMMON)
