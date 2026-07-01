import streamlit as st
import pandas as pd

from api_client import fetch_tech_leader_relay_timeseries, fetch_gbdt_oos_prices
from buyback_relay_core import render_group
import holdings_viz as hv

st.set_page_config(page_title="科技龙头", layout="wide")

_NOTE_TECH_LEADERS = (
    "NVDA", "AVGO", "AMD", "TSM", "ASML", "QCOM", "TXN", "MU", "INTC",
    "AMAT", "LRCX", "KLAC", "ARM",
    "MSFT", "ORCL", "CRM", "ADBE", "NOW", "SNOW", "PLTR", "DDOG", "CRWD",
    "PANW", "FTNT", "ZS", "NET", "MDB",
    "AAPL", "GOOGL", "META", "AMZN", "NFLX", "UBER", "ABNB", "SHOP", "SPOT", "BKNG",
    "TSLA", "DELL", "HPQ", "CSCO", "ANET", "IBM", "V", "MA", "PYPL", "ADYEY",
    "0700", "9988", "3690", "9618", "1024", "9888", "9961", "9999", "9992", "1810", "981",
    "6758", "6861", "8035", "6098", "9984", "6594", "7974", "6857",
    "SAP", "ASMIY", "BESIY", "ADYYF",
)
_NOTE_TECH_SET = set(_NOTE_TECH_LEADERS)

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🏆 科技龙头接力图 (Tech Leader Relay)")
st.caption(
    "**池子**:按《科技龙头公司》笔记收缩后的科技龙头清单；页面使用后端当前可用 ticker 的交集。"
    "**排名**:按 **raw 12M 绝对涨幅**（月末价/12 个月前月末价 − 1）横截面排名。"
    "**🥇 金牌 = 当月 Top1 / 🥈 银牌 = Top2**（已删 RS 门槛，只看排名）。"
    "**净值口径**:日线、执行月首个交易日 Open 买入、持有到月末 Close、扣单边 10bps；"
    "新进场须最近 6 月内 ≥2 次进 Top2(滤掉闪现一月的生面孔)，固定双持仓，空仓现金年化 4%。"
)

with st.sidebar:
    if st.button("🔄 强制刷新科技龙头数据"):
        fetch_tech_leader_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "9Y"]
window = st.radio("时间跨度", _WINDOWS, index=1, horizontal=True, key="tl_window")

with st.spinner("📊 加载科技龙头接力数据..."):
    ts = fetch_tech_leader_relay_timeseries(window)

if not ts.get("success"):
    st.error(f"⚠️ 科技龙头接力数据暂不可用:{ts.get('error', '未知错误')}")
    st.stop()

_all_tickers = ts.get("tickers", {}) or {}
_tickers = {tk: p for tk, p in _all_tickers.items() if tk in _NOTE_TECH_SET}
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 科技龙头笔记股池与当前后端数据没有交集")
    st.stop()
st.caption(f"股池过滤：笔记清单 {len(_NOTE_TECH_SET)} 只，当前后端命中 {len(_tickers)} 只。")

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

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=price_cache, spy_wk=spy_wk,
)


king_m_long = king_m

_cols = list(king_m.columns)
_label = "科技龙头"
st.markdown(f"## 🏆 科技龙头组（{len(_cols)} 只）")

render_group(_label, _cols, "tl_main",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="12M动量", score_fmt="{:+.1%}",
             default_k=0.75, n_hold=2,
             entry_min_top2_hits=2,
             gold_needs_rs=False,
             sweep_horizons=[("3Y", 3), ("5Y", 5), ("9Y", 9)],
             show_medal_table=False,
             only_medaled_in_heatmap=True,
             nav_engine="daily",
             daily_price_cache=price_cache_daily,
             spy_daily=spy_daily,
             cost_bps=10.0,
             **_COMMON)
