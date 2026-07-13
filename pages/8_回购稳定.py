import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_buyback_relay_timeseries, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="回购稳定", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("💰 回购股股东回报率接力 (Shareholder Yield Relay)")
st.caption(
    "**池子**：回购股.md 第一、二节里**剔除纯科技股后的其余组**（支付网络 / 消费 / 金融数据 / 工业医疗等）。"
    "**排名轴换成股东回报率 = 股息率 + 净回购率**（季频 Sharadar SF1 ART，PIT 安全）。"
    "净回购率 = (t−4Q 股本 / t 股本 − 1) × 100，增发为负（惩罚稀释股东的公司）。"
    "季报变化慢，排名比动量稳——对非科技低波动质量股更适用。"
    "**金牌 = Top1、银牌 = Top2**：纯按股东回报率排名发牌，不设 RS 门槛"
    "（发牌口径与净值回测一致；Page 7 动量版仍保留 RS 门槛）。"
    "**出场按趋势**：在任票只要月末价 > 自己的 4 月均线就一直拿，跌破 MA4 才换（对齐 Page 7/10，替代原 δ 死区）。"
    "**进场门 MA4>MA15 + 下穿重置**：卖出后须先见 MA4 跌破 MA15，之后 MA4 再上穿 MA15 才准重新进场——"
    "只用「当下 MA4 在 MA15 上方」的话，霸榜票跌破 MA4 当月就被排名原地买回，卖不出去（BKNG 2019-11 案例）。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_buyback_relay_timeseries.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=2, horizontal=True, key="shy_window")

with st.spinner("📊 加载回购股数据..."):
    ts = fetch_buyback_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_buyback_relay_timeseries("10Y")

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


shy_raw = pd.DataFrame(
    {tk: _aligned(p.get("shareholder_yield")) for tk, p in _tickers.items()}, index=_idx
).astype(float)

if shy_raw.isnull().all().all():
    st.warning("⚠️ 股东回报率数据未就绪（buyback_shareholder_yield.json 尚未上传到 Render）")
    st.stop()

rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
king = pd.DataFrame({tk: p.get("king_score", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")

king_m = king.resample("ME").last()
rs_m = rs.resample("ME").last()
shy_m = shy_raw.resample("ME").last()
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 月末快照数据不足")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

_TECH_TICKERS = {"AAPL", "MSFT", "GOOGL", "META", "TXN", "AVGO", "ORCL", "CSCO", "ADBE", "QCOM"}

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

# 出场：在任票月末价跌破自己 4 月均线才腾位（_ret_mask = price > MA4）。
# 进场门：MA4 > MA15（水平）+ 下穿重置（entry_reset_below）——卖出后须先见 MA4 跌破 MA15，
# 之后 MA4 再上穿 MA15 才准重新进场，堵住跌破 MA4 当月被排名原地买回（BKNG 2019-11 案例）。
_close_m = pd.DataFrame(_close_m_cols).sort_index()
_ret_mask = _close_m > _close_m.rolling(4).mean()
_entry_mask = _close_m.rolling(4).mean() > _close_m.rolling(15).mean()

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="股东回报率%", score_fmt="{:+.1f}",
)

_all_cols = list(king_m.columns)
_rest_cols = [c for c in _all_cols if c not in _TECH_TICKERS]


def _long_score_m():
    """从 10Y 长历史构造月末股东回报率，供 δ 稳健性扫描切尾部 3/5/10Y。失败返回 None。"""
    if window == "10Y":
        return shy_m
    if not (isinstance(ts_long, dict) and ts_long.get("success")):
        return None
    _tk_l = ts_long.get("tickers", {}) or {}
    _dt_l = ts_long.get("dates", []) or []
    if not _tk_l or not _dt_l:
        return None
    _ix_l = pd.to_datetime(_dt_l, errors="coerce")
    _nl = len(_ix_l)
    _raw_l = pd.DataFrame(
        {tk: (lambda v: v if len(v) == _nl else [np.nan] * _nl)(list(p.get("shareholder_yield") or []))
         for tk, p in _tk_l.items()},
        index=_ix_l,
    ).astype(float)
    return _raw_l.resample("ME").last()


shy_m_long = _long_score_m()

st.markdown("## 🏛️ 其余组（按股东回报率排名）")
render_group("其余回购股", _rest_cols, "shy_rest", score_m=shy_m, sweep_score_m=shy_m_long,
             retention_mask=_ret_mask,
             retention_price_m=_close_m,
             retention_ma_window=4,
             entry_mask=_entry_mask,
             entry_ma_window=15,
             entry_short_ma=4,
             entry_reset_below=True,
             gold_needs_rs=False,
             **_COMMON)
