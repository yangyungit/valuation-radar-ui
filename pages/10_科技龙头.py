import streamlit as st
import pandas as pd

from api_client import fetch_sp500_pit_relay_timeseries, fetch_gbdt_oos_prices
from buyback_relay_core import render_group
import holdings_viz as hv

st.set_page_config(page_title="标普500 PIT 接力", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📊 标普500 PIT 接力图")
st.caption(
    "**池子**:S&P500 每月真实历史成分（含退市，2016 起），每月只在当月成分内横截面排名。"
    "**排名**:按 **raw 12M 绝对涨幅**（月末价/12 个月前月末价 − 1）横截面排名。"
    "**🥇 金牌 = 当月 Top1 / 🥈 银牌 = Top2**（已删 RS 门槛，只看排名）。"
    "**净值口径**:日线、执行月首个交易日 Open 买入、持有到月末 Close、扣单边 10bps；"
    "满仓单票、进出场按 Top2 判定：新进场须当月 Top2 且最近 6 月内 ≥2 次进 Top2(滤掉闪现一月的生面孔)，"
    "在任票没掉出 Top2 就继续拿，空仓现金年化 4%。"
)

with st.sidebar:
    if st.button("🔄 强制刷新标普500接力数据"):
        fetch_sp500_pit_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=1, horizontal=True, key="tl_window")

with st.spinner("📊 加载标普500 PIT 接力数据..."):
    ts = fetch_sp500_pit_relay_timeseries(window)

if not ts.get("success"):
    st.error(f"⚠️ 标普500 PIT 接力数据暂不可用:{ts.get('error', '未知错误')}")
    st.stop()

_all_tickers = ts.get("tickers", {}) or {}
_tickers = _all_tickers
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 标普500 PIT 母体数据为空")
    st.stop()
st.caption(f"股池：S&P500 PIT 历史成分并集，当前后端命中 {len(_tickers)} 只。")

_idx = pd.to_datetime(_dates, errors="coerce")
rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
adv = pd.DataFrame({tk: p.get("adv_63d", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

rs_m = rs.resample("ME").last()
adv_m = adv.resample("ME").last()

_pool = list(_tickers.keys())
price_cache_daily: dict = {}
price_cache: dict = {}
spy_daily = pd.DataFrame()
spy_wk = pd.DataFrame()
with st.spinner("📊 加载日线价格（首次较慢）..."):
    try:
        hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(_pool + ["SPY"]))))
    except Exception:
        pass
    spy_daily = hv.fetch_daily_ohlcv("SPY")
    spy_wk = hv.daily_to_weekly(spy_daily)
    for _tk in _pool:
        try:
            _d = hv.fetch_daily_ohlcv(_tk)
            if not _d.empty:
                price_cache_daily[_tk] = _d
                price_cache[_tk] = hv.daily_to_weekly(_d)
        except Exception:
            pass

if not price_cache_daily:
    st.warning("⚠️ 股池价格数据为空")
    st.stop()

_px_me = pd.concat(
    {tk: price_cache_daily[tk]["Close"] for tk in price_cache_daily}, axis=1
).resample("ME").last()
king_m = (_px_me / _px_me.shift(12) - 1.0)

if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_memb = ts.get("sp500_membership", {}) or {}


def _mask_by_membership(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for dt in out.index:
        ym = dt.strftime("%Y-%m")
        allowed = set(_memb.get(ym, []))
        if allowed:
            out.loc[dt, [c for c in out.columns if c not in allowed]] = float("nan")
    return out


king_m = _mask_by_membership(king_m)

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=price_cache, spy_wk=spy_wk,
)


king_m_long = king_m

_cols = list(king_m.columns)
_label = "标普500"
st.markdown(f"## 🏆 标普500组（{len(_cols)} 只）")

render_group(_label, _cols, "tl_main",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="12M动量", score_fmt="{:+.1%}",
             default_k=0.75, n_hold=1, hold_band=2,
             entry_min_top2_hits=2,
             gold_needs_rs=False,
             sweep_horizons=[("3Y", 3), ("5Y", 5), ("10Y", 10)],
             show_medal_table=False,
             only_medaled_in_heatmap=True,
             nav_engine="daily",
             daily_price_cache=price_cache_daily,
             spy_daily=spy_daily,
             cost_bps=10.0,
             **_COMMON)
