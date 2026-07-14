import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_buyback_stable_relay_timeseries, fetch_gbdt_oos_prices, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="fcf稳定", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("💰 ROIC 稳定（FCF+不稀释规则池 × ROIC 排名）")
st.caption(
    "**池子**：年度 PIT 规则池——近5财年 FCF 全正增长 / 5年股本净增≤2%（不稀释即可，不再强制回购缩股）/ "
    "ROIC≥10% / 市值≥$5B / 按 ROIC 前40，每年12月末用当时财报重构、次年生效（本地 Sharadar 构建上传）。"
    "页面只跑**非科技子集**（is_tech=False）。**排名轴 = ROIC**（季频 ART PIT，池成员内排名）。"
    "金牌门槛不变：当月 Top1 且 RS_210d>0；银牌 = Top2。留任 MA4 卖出 / MA15 买回门不变。"
    "回测见 backtest_a_leg_round8/9.py：2017-04→2026-06 +1603%、DD -36.6%、Calmar 0.98（SPY +264%），近5年 +589%。"
    "**三条警告**：收益高度集中，FIX+TPL+MA 三只贡献 77% 的 log 收益，剔 TPL 后全程只剩 +308%≈SPY；"
    "DD 比 SPY 深，本质是押 ROIC 榜首单票的进攻腿，不是防守腿；截断宽度敏感（top20 +494%/top40 +1603%/top60 +1127%）。"
    "排名/进场计数/在任状态用窗口起点前 ~12 个月预热历史算、净值从窗口起点记账。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_buyback_stable_relay_timeseries.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=2, horizontal=True, key="shy_window")

with st.spinner("📊 加载 ROIC 稳定池数据..."):
    ts = fetch_buyback_stable_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_buyback_stable_relay_timeseries("10Y")

if not ts.get("success"):
    st.error(f"⚠️ 数据暂不可用：{ts.get('error', '未知错误')}")
    st.stop()

_tickers = ts.get("tickers", {}) or {}
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 时序数据为空")
    st.stop()

_idx = pd.to_datetime(_dates, errors="coerce")
_n = len(_idx)


def _aligned(vals):
    vals = list(vals or [])
    return vals if len(vals) == _n else [np.nan] * _n


roic_raw = pd.DataFrame(
    {tk: _aligned(p.get("roic")) for tk, p in _tickers.items()}, index=_idx
).astype(float)

if roic_raw.isnull().all().all():
    st.warning("⚠️ ROIC 数据未就绪（buyback_stable_pool.json 未更新到 Render）")
    st.stop()

rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
king = pd.DataFrame({tk: p.get("king_score", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

king_m = king.resample("ME").last()
rs_m = rs.resample("ME").last()
roic_m = roic_raw.resample("ME").last()
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

with st.spinner("📊 加载价格..."):
    _pool = list(_tickers.keys())
    # 12 年而非 10 年：MA15 需要 15 个月 warmup，否则 10Y 窗口开头的买回门全关（进不了场）。
    _px = get_global_data(_pool + ["SPY"], years=12)

_price_cache: dict = {}
_close_m_cols: dict = {}
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
                _close_m_cols[_tk] = _px[_tk].dropna().resample("ME").last()

# yfinance 拉不到的退市票从 Sharadar gbdt_oos_prices 补全复权日线
_missing = [t for t in _pool if t not in _price_cache]
if _missing:
    import holdings_viz as hv
    hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(_missing))))
    for _tk in _missing:
        _d = hv.fetch_daily_ohlcv(_tk)
        if not _d.empty:
            _price_cache[_tk] = _d["Close"].resample("W-FRI").last().dropna().to_frame(name="Close")
            _close_m_cols[_tk] = _d["Close"].resample("ME").last()

# MA4 留任 + MA15 买回门：在任票月末价 > 自己 4 月均线才留；腾位后须收回 15 月均线
# 上方才准重新进场。回测 backtest_shy_ma_asym.py：+429% / DD -19.2% / Calmar 0.94，
# vs 无买回门旧版 +421% / -30.0% / 0.60。
_close_m = pd.DataFrame(_close_m_cols).sort_index()
_ret_mask = _close_m > _close_m.rolling(4).mean()
_entry_mask = _close_m > _close_m.rolling(15).mean()

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="ROIC%", score_fmt="{:.1f}",
)

_all_cols = list(king_m.columns)
_rest_cols = [c for c in _all_cols if not (_tickers.get(c, {}) or {}).get("is_tech")]


def _long_score_m():
    """从 10Y 长历史构造月末 ROIC，供 δ 稳健性扫描切尾部 3/5/10Y。失败返回 None。"""
    if window == "10Y":
        return roic_m
    if not (isinstance(ts_long, dict) and ts_long.get("success")):
        return None
    _tk_l = ts_long.get("tickers", {}) or {}
    _dt_l = ts_long.get("dates", []) or []
    if not _tk_l or not _dt_l:
        return None
    _ix_l = pd.to_datetime(_dt_l, errors="coerce")
    _nl = len(_ix_l)
    _raw_l = pd.DataFrame(
        {tk: (lambda v: v if len(v) == _nl else [np.nan] * _nl)(list(p.get("roic") or []))
         for tk, p in _tk_l.items()},
        index=_ix_l,
    ).astype(float)
    return _raw_l.resample("ME").last()


roic_m_long = _long_score_m()

st.markdown("## 🏛️ 非科技组（按 ROIC 排名）")
render_group("回购稳定", _rest_cols, "stable_rest", score_m=roic_m, sweep_score_m=roic_m_long,
             display_from=ts.get("display_from"),
             retention_mask=_ret_mask,
             retention_price_m=_close_m,
             retention_ma_window=4,
             entry_mask=_entry_mask,
             entry_ma_window=15,
             **_COMMON)
