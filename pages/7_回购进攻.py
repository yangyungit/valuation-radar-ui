import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_buyback_relay_timeseries, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="回购进攻", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("👑 回购股接力图 (Buyback Relay)")
st.caption(
    "**池子**:回购股.md 第一、二节(教科书级 + 大型现金流机器,排除陷阱版)里的**纯科技股**(半导体/软件/平台,不含 V/MA)。"
    "**排名**:king_score = Z(RS_210d) —— 纯动量,动量窗口用 210 日(回测择优)。"
    "**🥇 金牌 = 当月 Top1 且 RS_210d > 0(跑赢 SPY,否则降灰)/🥈 银牌 = Top2**。"
    "下方持有**金+银两个仓位等权**,月末选仓、次交易日开盘执行(去 look-ahead)。"
)

with st.sidebar:
    if st.button("🔄 强制刷新回购股数据"):
        fetch_buyback_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=2, horizontal=True, key="bb_window")

with st.spinner("📊 加载回购股接力数据..."):
    ts = fetch_buyback_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_buyback_relay_timeseries("10Y")

if not ts.get("success"):
    st.error(f"⚠️ 回购股接力数据暂不可用:{ts.get('error', '未知错误')}")
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
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

# ── 月末快照(全池一次算好,两组共享)──
king_m = king.resample("ME").last()
rs_m = rs.resample("ME").last()
adv_m = adv.resample("ME").last()
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

# 纯科技股:半导体 / 软件 / 平台。支付网络 V/MA 不算,归入「其余」组。
_TECH_TICKERS = {"AAPL", "MSFT", "GOOGL", "META", "TXN", "AVGO", "ORCL", "CSCO", "ADBE", "QCOM"}

# ── 价格(全池一次拉好,两组共享)──
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
    ).astype(float)
    return _king_l.resample("ME").last()


king_m_long = _long_king_m()

_all_cols = list(king_m.columns)
_tech_cols = [c for c in _all_cols if c in _TECH_TICKERS]

st.markdown("## 💻 纯科技股组")
render_group("纯科技股", _tech_cols, "bb_tech",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="king_score", score_fmt="{:+.2f}",
             default_k=0.75, **_COMMON)
