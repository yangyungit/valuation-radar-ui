import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_buyback_fcf_relay_timeseries, fetch_gbdt_oos_prices, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="FCF进攻", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# 纯科技股组的池子里退市成员多，很多是冷门 B2B 软件/半导体公司，热力图/接力净值图上
# 光看 ticker 认不出是谁——用中文名代替原来占位的 sector("Technology")。查不到的退回 sector。
_TICKER_CN_NAME = {
    "AAPL": "苹果", "ADBE": "奥多比", "AKAM": "阿卡迈", "AMAT": "应用材料",
    "ANSS": "ANSYS(仿真软件)", "APH": "安费诺", "AZPN1": "阿斯本技术",
    "CDNS": "铿腾电子", "CLGX": "CoreLogic", "CPAY": "Corpay",
    "CRUS": "凌云逻辑", "CSCO": "思科", "CTXS": "思杰", "DBX": "Dropbox",
    "FFIV": "F5网络", "FISV": "费哲金融服务", "FLIR": "菲力尔", "FTNT": "飞塔",
    "GDDY": "戈达迪", "GLW": "康宁", "GOOGL": "谷歌", "INTC": "英特尔",
    "INTU": "直觉软件", "IT": "高德纳", "JKHY": "杰克亨利", "KEYS": "是德科技",
    "KLAC": "科磊", "LRCX": "泛林集团", "MANH": "曼哈顿软件", "META": "Meta",
    "MSFT": "微软", "MXIM": "美信集成", "NTAP": "网存", "NUAN": "纽昂斯通讯",
    "NVDA": "英伟达", "NXPI": "恩智浦", "ORCL": "甲骨文", "QCOM": "高通",
    "QRVO": "威讯联合半导体", "RHT": "红帽", "RMBS": "兰博士", "SWKS": "思佳讯",
    "TDC": "天睿", "TER": "泰瑞达", "TXN": "德州仪器", "UI": "优比快",
    "VMW": "威睿", "XLNX": "赛灵思",
}

st.title("👑 回购股接力图 (Buyback Relay)")
st.caption(
    "**池子**：三判据（近5财年FCF全正增长/股本5年净缩减≥5%且逐年降/回购分红≤FCF）+ 按 **FCF margin 前 40**，"
    "每年 12 月末用当时财报 PIT 重构、次年生效（本地 Sharadar 构建上传）。页面只跑**科技子集**（sector=Technology + GOOGL/META），"
    "退市成员历史价格走 Sharadar。**排名**：king_score = Z(RS_210d)，横截面 = 当年池成员。"
    "**🥇 金牌 = 当月 Top1 且 RS_210d > 0 / 🥈 银牌 = Top2**，金+银等权，月末选仓次日执行。"
    "**选股与买卖解耦**：留任改按纯排名——在任票掉出 Top2 即结束推荐（进场仍 Top2）；"
    "执行层按日线价格规则进出场——收盘 < 自身 MA100 出场，收盘回 MA100 上方买回。"
    "回测见 valuation-radar/backtest_a_leg_round10.py：2017-04→2026-06 = +3255%、回撤 -29.4%、Calmar 1.59"
    "（原月频 MA4 趋势留任版 +1477%、-35.7%；SPY +264%）——解耦后收益翻倍多，回撤反而收窄。"
)

with st.sidebar:
    if st.button("🔄 强制刷新回购股数据"):
        fetch_buyback_fcf_relay_timeseries.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=2, horizontal=True, key="bb_window")

with st.spinner("📊 加载回购股接力数据..."):
    ts = fetch_buyback_fcf_relay_timeseries(window)
    # δ 稳健性扫描要切尾部 3/5/10Y，固定再拉一份最长历史（缓存；选 10Y 时零额外成本）
    ts_long = ts if window == "10Y" else fetch_buyback_fcf_relay_timeseries("10Y")

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
grade_map = {tk: _TICKER_CN_NAME.get(tk, p.get("group", "")) for tk, p in _tickers.items()}
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

# ── 价格(全池一次拉好,两组共享)──
with st.spinner("📊 加载价格..."):
    _pool = list(_tickers.keys())
    _px = get_global_data(_pool + ["SPY"], years=10)

_price_cache: dict = {}
_daily_close_cache: dict = {}
_spy_wk = pd.DataFrame()
_spy_daily = pd.Series(dtype=float)
if _px is not None and not _px.empty:
    _wk = _px.resample("W-FRI").last()
    if "SPY" in _wk.columns:
        _spy_wk = _wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
    if "SPY" in _px.columns:
        _spy_daily = _px["SPY"].dropna()
    for _tk in _pool:
        if _tk in _wk.columns:
            _s = _wk[_tk].dropna()
            if len(_s) >= 2:
                _price_cache[_tk] = _s.to_frame(name="Close")
        if _tk in _px.columns:
            _ds = _px[_tk].dropna()
            if len(_ds) >= 2:
                _daily_close_cache[_tk] = _ds

# yfinance 拉不到的退市票（如 ANSS）从 Sharadar gbdt_oos_prices 补全复权日线（周线喂旧图缓存、日线喂执行层）
_missing = [t for t in _pool if t not in _price_cache]
if _missing:
    import holdings_viz as hv
    hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(_missing))))
    for _tk in _missing:
        _d = hv.fetch_daily_ohlcv(_tk)
        if not _d.empty:
            _price_cache[_tk] = _d["Close"].resample("W-FRI").last().dropna().to_frame(name="Close")
            _daily_close_cache[_tk] = _d["Close"].dropna()

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
_tech_cols = [c for c in _all_cols if (_tickers.get(c, {}) or {}).get("is_tech")]

st.markdown("## 💻 纯科技股组")
render_group("纯科技股", _tech_cols, "bb_tech",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="king_score", score_fmt="{:+.2f}",
             retention_band=2,
             exec_rule={"kind": "MA", "param": 100},
             daily_price_cache=_daily_close_cache,
             spy_daily=_spy_daily,
             nav_engine="daily",
             cost_bps=200.0,
             **_COMMON)
