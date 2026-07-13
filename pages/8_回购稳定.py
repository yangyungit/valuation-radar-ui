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
    "**出场按相对波动通道**：在任票只要月末价 > 自己的 MA6 × (1−0.5×近12月波动) 通道下沿就一直拿，跌破才换。"
    "波动带随个股波动自适应——低波动龙头(AZO/BKNG)绳子更短、高波动票更松，替代一刀切 MA4"
    "（MA4 对低波动票太紧、频繁被浅回调震出，空仓率高达 91%；通道后空仓降到 42%、总收益 152%→344%）。"
    "**进场门 MA4 > MA15×(1+0.125×近12月波动) + 下穿重置**：卖出后须先见 MA4 跌破门槛，"
    "之后 MA4 再上穿门槛才准重新进场——只用「当下 MA4 在门槛上方」的话，霸榜票跌破 MA4 当月就被排名原地买回，"
    "卖不出去（BKNG 2019-11 案例）。门槛幅度随个股波动缩放：高波动票要求更强的上穿确认、低波动票几乎贴着 MA15"
    "（10Y 回测：总收益 301%→339%、回撤 16.0%→15.0%，3/5/10Y Calmar 齐≥1；一刀切 MA15 三段 Calmar 0.80/0.85/0.90）。"
    "排名/进场计数/在任状态用窗口起点前 ~12 个月预热历史算、净值从窗口起点记账（消除窗口首月全体现金的冷启动伪影，与 fcf稳定页同口径）。"
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

# 出场：在任票月末价跌破自己的「相对波动通道」下沿才腾位。
# 通道下沿 = MA6 × (1 − k×近12月月收益波动)，k=0.5 全池固定。波动带随个股自身波动缩放——
# 低波动龙头(AZO/BKNG)绳子更短、高波动票更松，替代一刀切 MA4（对低波动票太紧、
# 频繁被浅回调震出、空仓率 91%）。10Y 回测：总收益 152%→344%、空仓 91%→42%、
# 回撤 6.9%→12.7%(仍是 SPY 一半)，稳健平台在 N5~7 / k0.2~0.8（三段 Calmar 齐≥1）。
# 进场门：MA4 > MA15 × (1 + 0.125×近12月波动) + 下穿重置（entry_reset_below）——卖出后须先见
# MA4 跌破门槛，再上穿门槛才准重新进场，堵住跌破当月被排名原地买回（BKNG 2019-11 案例）。
# 门槛幅度随个股波动缩放：高波动票要求更强的上穿确认，低波动票几乎贴着 MA15。
# 10Y 回测（tmp_entry_compare.py）：一刀切 MA15 总收益 301% / 回撤 16.0% / 3/5/10Y Calmar
# 0.80/0.85/0.90 → 缩放后 339% / 15.0% / 1.10/1.08/1.03，系数扫 [-0.75,1.0] maximin 最优在
# 0.125（平台 0.125~0.25，c≥0.5 只有 3Y 好看=过拟合）。注意：直接把出场通道搬来当进场条件
# （价格收回自己下沿/MA6/上沿即可买）全样本更差——崩盘后均线跟着塌、门常开，缺趋势确认。
_RET_MA, _RET_K, _RET_VOL_WIN = 6, 0.5, 12
_ENTRY_VOL_K = 0.125
_close_m = pd.DataFrame(_close_m_cols).sort_index()
_ret_vol = _close_m.pct_change().rolling(_RET_VOL_WIN).std()
_ret_mask = _close_m > _close_m.rolling(_RET_MA).mean() * (1 - _RET_K * _ret_vol)
_entry_vol_scale = 1 + _ENTRY_VOL_K * _ret_vol
_entry_mask = _close_m.rolling(4).mean() > _close_m.rolling(15).mean() * _entry_vol_scale

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
             display_from=ts.get("display_from"),
             retention_mask=_ret_mask,
             retention_price_m=_close_m,
             retention_ma_window=_RET_MA,
             retention_desc=(
                 f"在任票只要月末价 > 自己的 MA{_RET_MA} × (1 − {_RET_K}×近{_RET_VOL_WIN}月波动) "
                 "波动通道下沿就一直拿，不管别人排第几；跌破通道下沿才腾位"
                 "（波动带随个股波动自适应：低波动龙头绳子更短、高波动票更松，替代一刀切 MA4）"
             ),
             entry_mask=_entry_mask,
             entry_ma_window=15,
             entry_short_ma=4,
             entry_reset_below=True,
             entry_vol_scale=_entry_vol_scale,
             entry_vol_desc=f"×(1+{_ENTRY_VOL_K}×近{_RET_VOL_WIN}月波动)",
             gold_needs_rs=False,
             **_COMMON)
