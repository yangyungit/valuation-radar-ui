import os
import json
from typing import NamedTuple
import streamlit as st
import pandas as pd
import yfinance as yf
from _yf_session import YF_SESSION  # curl_cffi 浏览器指纹，绕 Yahoo 401
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from api_client import (fetch_core_data, fetch_vcp_analysis, fetch_screen_results,
                        fetch_arena_history)
from shared_state import SharedKeys  # 跨页面 session_state key 集中定义（约束 4）

core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
ASSET_CN_DB = core_data.get("ASSET_CN_DB", {})

st.set_page_config(page_title="个股择时 & VCP 猎杀", layout="wide", page_icon="🎯")

st.markdown("""
<style>
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 14px; margin: 10px 0; font-size: 14px; color: #ccc; border-radius: 0 6px 6px 0; line-height: 1.7; }
    .twap-box { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border: 1px solid #0f3460; border-radius: 10px; padding: 20px; margin: 15px 0; font-size: 14px; color: #ddd; line-height: 1.8; }
    .twap-box b { color: #e94560; }
    .grade-a { color: #2ECC71; font-weight: bold; font-size: 26px; }
    .grade-b { color: #3498DB; font-weight: bold; font-size: 26px; }
    .grade-c { color: #F1C40F; font-weight: bold; font-size: 26px; }
    .grade-d { color: #E67E22; font-weight: bold; font-size: 26px; }
    .grade-f { color: #E74C3C; font-weight: bold; font-size: 26px; }
    .timing-box { background: rgba(46,204,113,0.06); border-left: 4px solid #2ECC71; padding: 18px 20px; border-radius: 0 8px 8px 0; margin: 10px 0 18px 0; font-size: 14px; color: #ddd; line-height: 1.8; }
</style>
""", unsafe_allow_html=True)

# ── VCP 目标选择逻辑（数据预处理，不渲染 UI）──
_screen_cache_p5 = fetch_screen_results()
p4_arena_leaders = (
    _screen_cache_p5.get("p4_arena_leaders")
    or st.session_state.get("p4_arena_leaders", {})
)
p4_routed = st.session_state.get("p4_champion_ticker", "")

all_candidates = []
if p4_arena_leaders:
    rank_labels = ["🥇", "🥈", "🥉"]
    for c in ["A", "B", "C", "D"]:
        entries = p4_arena_leaders.get(c, [])
        for rank, entry in enumerate(entries):
            medal = rank_labels[rank] if rank < 3 else ""
            medal_prefix = f"{medal} " if medal else ""
            all_candidates.append({
                "label": f"{medal_prefix}{entry['ticker']} ({entry['name']}) | {c}级#{rank+1} {entry['score']:.0f}分",
                "ticker": entry["ticker"],
            })

options = ["-- 🔍 手动输入自定义代码 --"] + [c["label"] for c in all_candidates]
label_to_ticker = {c["label"]: c["ticker"] for c in all_candidates}

default_idx = 1 if all_candidates else 0
if p4_routed:
    for i, cand in enumerate(all_candidates):
        if cand["ticker"] == p4_routed:
            default_idx = i + 1
            break

# ── Main ──
st.title("🎯 Layer 5: 个股择时")
st.caption("竞技场择时回顾 ➡️ VCP 形态猎杀 ➡️ TWAP 最优建仓执行")

# ── Load Arena History Data（主：后端 API，降级：本地 JSON）──
# 约束 2（禁止静默失败）：降级到本地必须红字告警，否则用户会误以为在看最新数据
_ARENA_HIST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")
_arena_data: dict = fetch_arena_history()
_arena_is_fallback: bool = False
_arena_local_mtime: str = ""
if not _arena_data:
    try:
        if os.path.exists(_ARENA_HIST_PATH):
            with open(_ARENA_HIST_PATH, "r", encoding="utf-8") as _af:
                _raw = json.load(_af)
            _arena_data = {k: v for k, v in _raw.items() if not k.startswith("_")}
            # 本地 fallback 可能是旧 list 格式，升级为新 dict 格式
            for _fb_m in _arena_data:
                _fb_cls_map = _arena_data[_fb_m]
                if not isinstance(_fb_cls_map, dict):
                    continue
                for _fb_c in list(_fb_cls_map.keys()):
                    _fb_rec = _fb_cls_map[_fb_c]
                    if isinstance(_fb_rec, list):
                        _fb_cls_map[_fb_c] = {
                            "tickers": _fb_rec, "gate_status": "open", "gate_reason": "",
                        }
            _arena_is_fallback = bool(_arena_data)
            if _arena_is_fallback:
                import datetime as _dt
                _arena_local_mtime = _dt.datetime.fromtimestamp(
                    os.path.getmtime(_ARENA_HIST_PATH)
                ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

if _arena_is_fallback:
    st.toast("⚠️ Render 后端 arena_history 为空，已降级本地陈旧快照", icon="🚨")
    st.error(
        f"🚨 **数据降级告警**：后端 `arena_history` 表当前返回空，Page 5 已 fallback 到本地快照 "
        f"`data/arena_history.json`（最后修改 **{_arena_local_mtime}**）。"
        "\n\n图表与榜单**不反映最新分类结果**，请先访问 **Page 3 资产细筛** 重新跑分类并回填，"
        "或登录 Render 排查 `universe.db.arena_history` 表。"
    )

_CLS_CLR = {"A": "#2ECC71", "B": "#3498DB", "C": "#F39C12", "D": "#E74C3C"}
_CLS_LBL = {
    "A": "🛡️ A 避风港", "B": "🏦 B 压舱石",
    "C": "🚀 C 趋势动量", "D": "⚡ D 短线爆发",
}
_CLS_MA_WEEKS = {"A": 12, "B": 12, "C": 8, "D": 4}
_CLS_SLOW_MA = {"A": 60, "B": 60, "C": None, "D": None}


def _get_holding_periods(cls_map: dict, ticker: str) -> list:
    periods: list = []
    in_h, start, prev = False, None, None
    for m in sorted(cls_map.keys()):
        if ticker in cls_map[m]:
            if not in_h:
                start = m
                in_h = True
            prev = m
        elif in_h:
            periods.append((start, prev))
            in_h = False
    if in_h:
        periods.append((start, prev))
    return periods


@st.cache_data(ttl=3600 * 4, show_spinner=False)
def _fetch_weekly_ohlcv(ticker: str) -> pd.DataFrame:
    h = yf.Ticker(ticker, session=YF_SESSION).history(period="5y")
    if h.empty:
        return pd.DataFrame()
    w = h.resample("W-FRI").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()
    if w.index.tz is not None:
        try:
            w.index = w.index.tz_localize(None)
        except TypeError:
            w.index = w.index.tz_convert(None)
    return w


# ── Sidebar（必须在 _fetch_weekly_ohlcv 定义之后）──
with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        fetch_vcp_analysis.clear()
        fetch_screen_results.clear()
        _fetch_weekly_ohlcv.clear()
        st.toast("当前页缓存已清除！")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.toast("所有页面缓存已清除！")
        st.rerun()

    st.divider()
    st.subheader("💸 摩擦成本参数")
    _p5_commission_pct = st.slider(
        "佣金率 (%)", min_value=0.00, max_value=0.50,
        value=0.03, step=0.01, format="%.2f",
        key="p5_commission_rate",
        help="单边佣金率（富途/盈透级别约 0.03%）",
    )
    _p5_slippage_pct = st.slider(
        "滑点率 (%)", min_value=0.00, max_value=0.50,
        value=0.10, step=0.01, format="%.2f",
        key="p5_slippage_rate",
        help="单边滑点率（A 级流动性 ETF/蓝筹约 0.10%）",
    )
    # 摩擦成本公式：2(标的) × (买+卖) × 50%仓位 = 2×(佣金+滑点) / 100
    _p5_per_switch_friction = 2.0 * (_p5_commission_pct + _p5_slippage_pct) / 100.0
    st.slider(
        "空仓年化收益率 (%)", min_value=0.00, max_value=6.00,
        value=4.00, step=0.25, format="%.2f",
        key="p5_cash_annual_return",
        help="闸门关期间现金仓按此利率复利计息（对应 SGOV/BIL 约 4~5%）",
    )


# ── 择时策略接口标准 ──────────────────────────────────────────────────
class TimingResult(NamedTuple):
    signals: list       # [{"date": Timestamp, "type": "buy"/"sell", "price": float}, ...]
    benched_zones: list  # [(start_date, end_date), ...]
    timed_rets: list    # 每个 roster period 的择时收益 %
    raw_rets: list      # 每个 roster period 的名单原始收益 %（各工具相同）
    overlays: list      # [{"label": str, "series": pd.Series, "color": str, "dash": str}]


def _timing_ma_cross(wk_df: pd.DataFrame, roster_periods: list,
                     fast_weeks: int = 12, slow_weeks: int = None, **kwargs) -> TimingResult:
    """MA 金叉死叉（或价格 vs 生命线）策略。
    fast_weeks: 快线 MA 周期；slow_weeks: 慢线 MA 周期（None 时退化为价格 vs 快线）。
    """
    close = wk_df["Close"].astype(float)
    fast_ma = close.rolling(fast_weeks, min_periods=fast_weeks).mean()
    use_cross = slow_weeks is not None
    slow_ma = close.rolling(slow_weeks, min_periods=slow_weeks).mean() if use_cross else None

    signals, benched_zones = [], []
    timed_rets, raw_rets = [], []

    for sm, em in roster_periods:
        sd = pd.Timestamp(f"{sm}-01")
        ed = pd.Timestamp(f"{em}-01") + pd.offsets.MonthEnd(1)
        mask = (wk_df.index >= sd) & (wk_df.index <= ed)
        seg_c = close[mask]
        seg_fast = fast_ma[mask]
        seg_slow = slow_ma[mask] if use_cross else None

        if seg_c.empty:
            timed_rets.append(0.0)
            raw_rets.append(0.0)
            continue

        raw_ep = float(seg_c.iloc[0])
        raw_xp = float(seg_c.iloc[-1])
        raw_rets.append((raw_xp / raw_ep - 1) * 100 if raw_ep > 0 else 0.0)

        in_pos, entry_p, cum = False, None, 1.0
        bench_start = None

        for dt in seg_c.index:
            p = float(seg_c.loc[dt])
            fv = seg_fast.loc[dt]

            if use_cross:
                sv = seg_slow.loc[dt]
                if pd.isna(fv) or pd.isna(sv):
                    if not in_pos and bench_start is None:
                        bench_start = dt
                    continue
                fv_f, sv_f = float(fv), float(sv)
                if not in_pos:
                    if fv_f > sv_f:
                        signals.append({"date": dt, "type": "buy", "price": p})
                        in_pos, entry_p = True, p
                        if bench_start is not None:
                            benched_zones.append((bench_start, dt))
                            bench_start = None
                    elif bench_start is None:
                        bench_start = dt
                else:
                    if fv_f < sv_f:
                        signals.append({"date": dt, "type": "sell", "price": p})
                        if entry_p and entry_p > 0:
                            cum *= p / entry_p
                        in_pos, entry_p = False, None
                        bench_start = dt
            else:
                if pd.isna(fv):
                    if not in_pos and bench_start is None:
                        bench_start = dt
                    continue
                mv = float(fv)
                if not in_pos:
                    if p > mv:
                        signals.append({"date": dt, "type": "buy", "price": p})
                        in_pos, entry_p = True, p
                        if bench_start is not None:
                            benched_zones.append((bench_start, dt))
                            bench_start = None
                    elif bench_start is None:
                        bench_start = dt
                else:
                    if p < mv:
                        signals.append({"date": dt, "type": "sell", "price": p})
                        if entry_p and entry_p > 0:
                            cum *= p / entry_p
                        in_pos, entry_p = False, None
                        bench_start = dt

        if in_pos and entry_p and entry_p > 0:
            last_p = float(seg_c.iloc[-1])
            signals.append({"date": seg_c.index[-1], "type": "sell", "price": last_p})
            cum *= last_p / entry_p
        if bench_start is not None and not seg_c.empty:
            benched_zones.append((bench_start, seg_c.index[-1]))
        timed_rets.append((cum - 1) * 100)

    overlays = []
    fast_label = f"MA{fast_weeks}w" + (" 快线" if use_cross else " 生命线")
    overlays.append({"label": fast_label, "series": fast_ma, "color": "#E74C3C", "dash": "dash"})
    if slow_ma is not None:
        overlays.append({"label": f"MA{slow_weeks}w 慢线", "series": slow_ma,
                         "color": "#F39C12", "dash": "dash"})
    return TimingResult(signals, benched_zones, timed_rets, raw_rets, overlays)


def _timing_break_ma(wk_df: pd.DataFrame, roster_periods: list,
                     ma_weeks: int, line_color: str, **kwargs) -> TimingResult:
    """价格跌破 MA 生命线策略（通用实现，供 break_ma60 / break_ma20 复用）。"""
    close = wk_df["Close"].astype(float)
    ma = close.rolling(ma_weeks, min_periods=ma_weeks).mean()
    signals, benched_zones = [], []
    timed_rets, raw_rets = [], []

    for sm, em in roster_periods:
        sd = pd.Timestamp(f"{sm}-01")
        ed = pd.Timestamp(f"{em}-01") + pd.offsets.MonthEnd(1)
        mask = (wk_df.index >= sd) & (wk_df.index <= ed)
        seg_c = close[mask]
        seg_ma = ma[mask]

        if seg_c.empty:
            timed_rets.append(0.0)
            raw_rets.append(0.0)
            continue

        raw_ep = float(seg_c.iloc[0])
        raw_xp = float(seg_c.iloc[-1])
        raw_rets.append((raw_xp / raw_ep - 1) * 100 if raw_ep > 0 else 0.0)

        in_pos, entry_p, cum = False, None, 1.0
        bench_start = None

        for dt in seg_c.index:
            p = float(seg_c.loc[dt])
            mv_raw = seg_ma.loc[dt]
            if pd.isna(mv_raw):
                if not in_pos and bench_start is None:
                    bench_start = dt
                continue
            mv = float(mv_raw)
            if not in_pos:
                if p > mv:
                    signals.append({"date": dt, "type": "buy", "price": p})
                    in_pos, entry_p = True, p
                    if bench_start is not None:
                        benched_zones.append((bench_start, dt))
                        bench_start = None
                elif bench_start is None:
                    bench_start = dt
            else:
                if p < mv:
                    signals.append({"date": dt, "type": "sell", "price": p})
                    if entry_p and entry_p > 0:
                        cum *= p / entry_p
                    in_pos, entry_p = False, None
                    bench_start = dt

        if in_pos and entry_p and entry_p > 0:
            last_p = float(seg_c.iloc[-1])
            signals.append({"date": seg_c.index[-1], "type": "sell", "price": last_p})
            cum *= last_p / entry_p
        if bench_start is not None and not seg_c.empty:
            benched_zones.append((bench_start, seg_c.index[-1]))
        timed_rets.append((cum - 1) * 100)

    overlays = [{"label": f"MA{ma_weeks}w", "series": ma, "color": line_color, "dash": "dash"}]
    return TimingResult(signals, benched_zones, timed_rets, raw_rets, overlays)


def _timing_break_ma60(wk_df: pd.DataFrame, roster_periods: list, **kwargs) -> TimingResult:
    """价格跌破 MA60w 生命线策略。"""
    return _timing_break_ma(wk_df, roster_periods, ma_weeks=60, line_color="#3498DB")


def _timing_break_ma20(wk_df: pd.DataFrame, roster_periods: list, **kwargs) -> TimingResult:
    """价格跌破 MA20w 线策略。"""
    return _timing_break_ma(wk_df, roster_periods, ma_weeks=20, line_color="#9B59B6")


def _timing_rapid_drop(wk_df: pd.DataFrame, roster_periods: list,
                       drop_pct: float = 8.0, **kwargs) -> TimingResult:
    """急跌速断器：默认持仓；单周跌幅 > drop_pct% 紧急清仓；价格重新站上 MA12w 后回场。"""
    close = wk_df["Close"].astype(float)
    ma12 = close.rolling(12, min_periods=12).mean()
    wk_ret_pct = close.pct_change() * 100

    signals, benched_zones = [], []
    timed_rets, raw_rets = [], []

    for sm, em in roster_periods:
        sd = pd.Timestamp(f"{sm}-01")
        ed = pd.Timestamp(f"{em}-01") + pd.offsets.MonthEnd(1)
        mask = (wk_df.index >= sd) & (wk_df.index <= ed)
        seg_c = close[mask]
        seg_ma12 = ma12[mask]
        seg_wkret = wk_ret_pct[mask]

        if seg_c.empty:
            timed_rets.append(0.0)
            raw_rets.append(0.0)
            continue

        raw_ep = float(seg_c.iloc[0])
        raw_xp = float(seg_c.iloc[-1])
        raw_rets.append((raw_xp / raw_ep - 1) * 100 if raw_ep > 0 else 0.0)

        in_pos = True
        entry_p = raw_ep
        cum = 1.0
        bench_start = None
        signals.append({"date": seg_c.index[0], "type": "buy", "price": raw_ep})

        for dt in seg_c.index:
            p = float(seg_c.loc[dt])
            wkr_raw = seg_wkret.loc[dt]
            wkr = float(wkr_raw) if not pd.isna(wkr_raw) else 0.0
            mv_raw = seg_ma12.loc[dt]
            mv = float(mv_raw) if not pd.isna(mv_raw) else None

            if in_pos:
                if wkr < -drop_pct:
                    signals.append({"date": dt, "type": "sell", "price": p})
                    if entry_p and entry_p > 0:
                        cum *= p / entry_p
                    in_pos = False
                    entry_p = None
                    bench_start = dt
            else:
                if mv is not None and p > mv:
                    signals.append({"date": dt, "type": "buy", "price": p})
                    in_pos = True
                    entry_p = p
                    if bench_start is not None:
                        benched_zones.append((bench_start, dt))
                        bench_start = None

        if in_pos and entry_p and entry_p > 0:
            last_p = float(seg_c.iloc[-1])
            last_dt = seg_c.index[-1]
            last_sig = signals[-1] if signals else None
            if not (last_sig and last_sig["type"] == "sell" and last_sig["date"] == last_dt):
                signals.append({"date": last_dt, "type": "sell", "price": last_p})
            cum *= last_p / entry_p
        if bench_start is not None and not seg_c.empty:
            benched_zones.append((bench_start, seg_c.index[-1]))
        timed_rets.append((cum - 1) * 100)

    overlays = [{"label": "MA12w 参考线", "series": ma12, "color": "#E67E22", "dash": "dot"}]
    return TimingResult(signals, benched_zones, timed_rets, raw_rets, overlays)


_TIMING_TOOLS = {
    "ma_cross":   {"label": "MA金叉死叉",    "fn": _timing_ma_cross,   "desc": "MA12w/MA60w 金叉买入、死叉卖出"},
    "break_ma60": {"label": "跌破MA60生命线", "fn": _timing_break_ma60, "desc": "价格站上 MA60w 买入、跌破卖出"},
    "break_ma20": {"label": "跌破MA20线",    "fn": _timing_break_ma20, "desc": "价格站上 MA20w 买入、跌破卖出"},
    "rapid_drop": {"label": "急跌速断器",    "fn": _timing_rapid_drop,  "desc": "单周暴跌超阈值紧急卖出"},
}

_TOOL_COLORS = {
    "ma_cross":   {"buy": "#2ECC71", "sell": "#E74C3C"},
    "break_ma60": {"buy": "#3498DB", "sell": "#1A6EA8"},
    "break_ma20": {"buy": "#9B59B6", "sell": "#7D3C98"},
    "rapid_drop": {"buy": "#E67E22", "sell": "#CA6F1E"},
}

_TOOL_SYMBOLS = {
    "ma_cross":   {"buy": "triangle-up",  "sell": "triangle-down"},
    "break_ma60": {"buy": "diamond",      "sell": "diamond"},
    "break_ma20": {"buy": "circle",       "sell": "circle"},
    "rapid_drop": {"buy": "star",         "sell": "star"},
}


_ARENA_CONFIG_FILE_P5 = os.path.join(os.path.dirname(__file__), "..", "data", "arena_config.json")

def _load_buffer_n_p5() -> int:
    """优先 session_state（同会话 Page 4 已写入），回退磁盘文件，兜底默认 3。"""
    if SharedKeys.CONFIRMED_BUFFER_N in st.session_state:
        return int(st.session_state[SharedKeys.CONFIRMED_BUFFER_N])
    try:
        if os.path.exists(_ARENA_CONFIG_FILE_P5):
            with open(_ARENA_CONFIG_FILE_P5, "r", encoding="utf-8") as _cf:
                return int(json.load(_cf).get("buffer_n", 3))
    except Exception:
        pass
    return 3


def _save_buffer_n_p5(n: int) -> None:
    try:
        os.makedirs(os.path.dirname(_ARENA_CONFIG_FILE_P5), exist_ok=True)
        with open(_ARENA_CONFIG_FILE_P5, "w", encoding="utf-8") as _cf:
            json.dump({"buffer_n": n}, _cf)
    except Exception:
        pass


if _arena_data:
    # ── 检测数据深度（以最近月份为准，旧月份由切片自动兜底）────────
    _p5_sorted_months = sorted(
        [k for k in _arena_data if not k.startswith("_")], reverse=True,
    )
    _p5_latest = _p5_sorted_months[0] if _p5_sorted_months else None
    _p5_depths = []
    if _p5_latest and _p5_latest in _arena_data:
        for _c_p5 in ["A", "B", "C", "D", "Z"]:
            _rr_p5 = _arena_data[_p5_latest].get(_c_p5, {}).get("tickers", [])
            if _rr_p5:
                _p5_depths.append(len(_rr_p5))
    _p5_min_depth = min(_p5_depths) if _p5_depths else 3
    _p5_max_buffer_n = max(2, _p5_min_depth)

    _auth_buffer = min(_load_buffer_n_p5(), _p5_max_buffer_n)
    if "p5_buffer_n_input" not in st.session_state:
        st.session_state["p5_buffer_n_input"] = _auth_buffer
        st.session_state[SharedKeys.P5_BUFFER_SYNCED] = _auth_buffer
    else:
        _last_synced = st.session_state.get(SharedKeys.P5_BUFFER_SYNCED)
        if _auth_buffer != _last_synced:
            st.session_state["p5_buffer_n_input"] = _auth_buffer
            st.session_state[SharedKeys.P5_BUFFER_SYNCED] = _auth_buffer
    _buffer_n: int = min(int(st.session_state["p5_buffer_n_input"]), _p5_max_buffer_n)
    _tm_months = sorted(k for k in _arena_data if not k.startswith("_"))
    _tm_hold: dict = {}
    _score_anomalies: list = []

    # _gate_closed_by_cls: {cls: [(month, reason), ...]} 记录每组闸门关闭月份
    _gate_closed_by_cls: dict = {c: [] for c in ["A", "B", "C", "D"]}

    for _c in ["A", "B", "C", "D"]:
        _prev_h: set = set()
        _cm: dict = {}
        for _m in _tm_months:
            _rec_obj = _arena_data[_m].get(
                _c, {"tickers": [], "gate_status": "open", "gate_reason": ""}
            )
            _gate_open = _rec_obj.get("gate_status", "open") != "closed"
            _gate_reason = _rec_obj.get("gate_reason", "")
            if not _gate_open:
                _gate_closed_by_cls[_c].append((_m, _gate_reason))
            _recs = _rec_obj.get("tickers", [])
            _t3 = {r.get("ticker", "") for r in _recs[:_buffer_n]} - {""}
            _t2 = {r.get("ticker", "") for r in _recs[:2]} - {""}

            if _c == "B":
                for _r in _recs[:_buffer_n]:
                    if _r.get("score", 999) == 0 or _r.get("score") is None:
                        _score_anomalies.append({
                            "month": _m, "ticker": _r.get("ticker", "?"),
                            "name": _r.get("name", _r.get("ticker", "?")),
                            "rank": _recs.index(_r) + 1,
                            "conviction": _r.get("conviction", "—"),
                        })

            if _prev_h:
                _survivors = _prev_h & _t3
                if len(_survivors) >= 2:
                    _strategy_hold = _survivors
                elif len(_survivors) == 1:
                    _fill = next((r.get("ticker") for r in _recs[:_buffer_n] if r.get("ticker") and r["ticker"] not in _survivors), None)
                    _strategy_hold = _survivors | {_fill} if _fill else _t2
                else:
                    _strategy_hold = _t2
            else:
                _strategy_hold = _t2

            # 闸门关：当月 hold 置空（NAV 记现金）；_prev_h 保留策略持仓，守擂记忆不中断
            _cm[_m] = _strategy_hold if _gate_open else set()
            _prev_h = _strategy_hold
        _tm_hold[_c] = _cm

    # ── 名称映射（供 K 线图和盈利统计共用）─────────────────────────────
    _name_map: dict = {}
    for _m in _tm_months:
        for _c_nm in ["A", "B", "C", "D"]:
            for _rec in _arena_data[_m].get(_c_nm, {}).get("tickers", []):
                _name_map[_rec["ticker"]] = _rec.get("name", _rec["ticker"])

    # ── A 组 slot-stable 列分配 ─────────────────────────────────────────
    _a_slot_assignments: dict = {}
    _prev_slots_a: list = [None, None]
    _a_gate_months: set = {m for m, _ in _gate_closed_by_cls.get("A", [])}
    for _m in _tm_months:
        if _m in _a_gate_months:
            _a_slot_assignments[_m] = ["CASH", "CASH"]
            continue  # 不更新 _prev_slots_a，守擂记忆原地保持
        _hold_set_a = _tm_hold["A"].get(_m, set())
        _new_slots_a = [None, None]
        _assigned_a: set = set()
        for _si in range(2):
            if _prev_slots_a[_si] and _prev_slots_a[_si] in _hold_set_a:
                _new_slots_a[_si] = _prev_slots_a[_si]
                _assigned_a.add(_prev_slots_a[_si])
        _remaining_a = sorted(t for t in _hold_set_a if t not in _assigned_a)
        for _t in _remaining_a:
            for _si in range(2):
                if _new_slots_a[_si] is None:
                    _new_slots_a[_si] = _t
                    break
        _a_slot_assignments[_m] = _new_slots_a
        _prev_slots_a = _new_slots_a

    # ── 构建左/右列持仓段序列 ──────────────────────────────────────────
    _SLOT_COLORS = [
        "#2ECC71", "#3498DB", "#E67E22", "#9B59B6",
        "#1ABC9C", "#E74C3C", "#F1C40F", "#8E44AD",
    ]

    def _build_slot_segments(slot_assignments: dict, slot_idx: int, tm_months: list) -> list:
        segs: list = []
        _cur_tk, _cur_s, _cur_e = None, None, None
        for _m in tm_months:
            _tk = slot_assignments.get(_m, [None, None])[slot_idx]
            if _tk == _cur_tk:
                _cur_e = _m
            else:
                if _cur_tk is not None:
                    segs.append((_cur_tk, _cur_s, _cur_e))
                _cur_tk, _cur_s, _cur_e = _tk, _m, _m
        if _cur_tk is not None:
            segs.append((_cur_tk, _cur_s, _cur_e))
        return segs

    _seg_left = _build_slot_segments(_a_slot_assignments, 0, _tm_months)
    _seg_right = _build_slot_segments(_a_slot_assignments, 1, _tm_months)

    # ── 信念在榜连续月数计算 ────────────────────────────────────────────
    def _compute_streaks_p5(cls: str, top_n: int) -> dict:
        """返回 {month: {ticker: 连续在 Top-N 内的月数}}"""
        _months_s = sorted(k for k in _arena_data if not k.startswith("_"))
        _res_s: dict = {}
        _prev_tk_s: set = set()
        _prev_st_s: dict = {}
        for _ms in _months_s:
            _recs_s = _arena_data[_ms].get(cls, {}).get("tickers", [])
            _cur_tk_s = {r["ticker"] for r in _recs_s[:top_n]}
            _cur_st_s: dict = {}
            for _t_s in _cur_tk_s:
                _cur_st_s[_t_s] = _prev_st_s.get(_t_s, 0) + 1 if _t_s in _prev_tk_s else 1
            _res_s[_ms] = _cur_st_s
            _prev_tk_s = _cur_tk_s
            _prev_st_s = _cur_st_s
        return _res_s

    def _compute_slot_weights(slot_assignments: dict, streaks: dict, months: list) -> dict:
        """返回 {month: (w_left, w_right)}，streak 更长的 slot 权重更高（限制在 30%-70%）"""
        _sw_res: dict = {}
        for _m_sw in months:
            _slots_sw = slot_assignments.get(_m_sw, [None, None])
            _tk_l, _tk_r = _slots_sw[0], _slots_sw[1]
            _s_l = streaks.get(_m_sw, {}).get(_tk_l, 1) if _tk_l else 1
            _s_r = streaks.get(_m_sw, {}).get(_tk_r, 1) if _tk_r else 1
            _total_sw = _s_l + _s_r
            if _total_sw == 0:
                _sw_res[_m_sw] = (0.5, 0.5)
            else:
                _raw_l = _s_l / _total_sw
                _w_l = max(0.30, min(0.70, _raw_l))
                _sw_res[_m_sw] = (_w_l, 1.0 - _w_l)
        return _sw_res

    # 提前读取权重模式（session_state，供下方 NAV 合成使用；radio 控件在图表标题下方渲染）
    _weight_mode: str = st.session_state.get("a_weight_mode", "等权 50/50")
    _a_streaks_full = _compute_streaks_p5("A", _buffer_n)
    _a_slot_weights = _compute_slot_weights(_a_slot_assignments, _a_streaks_full, _tm_months)

    # ── 拉取 A 组所有标的 OHLCV ───────────────────────────────────────
    _a_tickers_all = sorted({
        tk for slots in _a_slot_assignments.values() for tk in slots if tk and tk != "CASH"
    })
    _a_price_cache: dict = {}
    _a_section_error: str | None = None
    try:
        with st.spinner("正在获取 A 组 K 线数据..."):
            for _tk in _a_tickers_all:
                try:
                    _wkd = _fetch_weekly_ohlcv(_tk)
                    if not _wkd.empty:
                        _a_price_cache[_tk] = _wkd
                except Exception:
                    pass
    except Exception as _e:
        _a_section_error = f"A 组价格数据拉取失败: {_e}"

    _spy_wk_a: pd.DataFrame = pd.DataFrame()
    try:
        _spy_wk_a = _fetch_weekly_ohlcv("SPY")
    except Exception:
        pass

    # ── B 组 slot-stable 列分配 ─────────────────────────────────────────
    _b_slot_assignments: dict = {}
    _prev_slots_b: list = [None, None]
    _b_gate_months: set = {m for m, _ in _gate_closed_by_cls.get("B", [])}
    for _m in _tm_months:
        if _m in _b_gate_months:
            _b_slot_assignments[_m] = ["CASH", "CASH"]
            continue  # 不更新 _prev_slots_b，守擂记忆原地保持
        _hold_set_b = _tm_hold["B"].get(_m, set())
        _new_slots_b = [None, None]
        _assigned_b: set = set()
        for _si in range(2):
            if _prev_slots_b[_si] and _prev_slots_b[_si] in _hold_set_b:
                _new_slots_b[_si] = _prev_slots_b[_si]
                _assigned_b.add(_prev_slots_b[_si])
        _remaining_b = sorted(t for t in _hold_set_b if t not in _assigned_b)
        for _t in _remaining_b:
            for _si in range(2):
                if _new_slots_b[_si] is None:
                    _new_slots_b[_si] = _t
                    break
        _b_slot_assignments[_m] = _new_slots_b
        _prev_slots_b = _new_slots_b

    _b_seg_left = _build_slot_segments(_b_slot_assignments, 0, _tm_months)
    _b_seg_right = _build_slot_segments(_b_slot_assignments, 1, _tm_months)

    _b_weight_mode: str = st.session_state.get("b_weight_mode", "等权 50/50")
    _b_streaks_full = _compute_streaks_p5("B", _buffer_n)
    _b_slot_weights = _compute_slot_weights(_b_slot_assignments, _b_streaks_full, _tm_months)

    # ── 拉取 B 组所有标的 OHLCV ───────────────────────────────────────
    _b_tickers_all = sorted({
        tk for slots in _b_slot_assignments.values() for tk in slots if tk and tk != "CASH"
    })
    _b_price_cache: dict = {}
    _b_section_error: str | None = None
    try:
        with st.spinner("正在获取 B 组 K 线数据..."):
            for _tk in _b_tickers_all:
                try:
                    _wkd = _fetch_weekly_ohlcv(_tk)
                    if not _wkd.empty:
                        _b_price_cache[_tk] = _wkd
                except Exception:
                    pass
    except Exception as _e:
        _b_section_error = f"B 组价格数据拉取失败: {_e}"

    # ── 绘制首尾相接拼接累计收益率线形图（整数 x 轴，各段顺序衔接）────────────
    def _build_stitched_kline_fig(
        segs: list, slot_name: str, spy_wk: pd.DataFrame = None,
        price_cache: dict = None, name_map: dict = None,
    ) -> go.Figure:
        _pc = price_cache if price_cache is not None else {}
        _nm = name_map if name_map is not None else {}
        fig = go.Figure()
        x_offset = 0
        tick_vals: list = []
        tick_texts: list = []
        boundary_xs: list = []
        name_annotations: list = []
        running_return = 0.0
        spy_close = spy_wk["Close"].astype(float).dropna() if spy_wk is not None and not spy_wk.empty else None
        spy_x_all: list = []
        spy_y_all: list = []
        spy_running_return = 0.0

        for _ci, (_tk, _s_m, _e_m) in enumerate(segs):
            if _tk == "CASH":
                if spy_wk is not None and not spy_wk.empty:
                    _sd = pd.Timestamp(f"{_s_m}-01")
                    _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
                    _mask = (spy_wk.index >= _sd) & (spy_wk.index <= _ed)
                    _cash_idx = spy_wk.index[_mask]
                    if len(_cash_idx) >= 1:
                        _n = len(_cash_idx)
                        _x_vals = list(range(x_offset, x_offset + _n))
                        fig.add_trace(go.Scatter(
                            x=_x_vals,
                            y=[running_return] * _n,
                            mode="lines",
                            line=dict(color="#bbbbbb", width=2, dash="dot"),
                            name=f"💰 空仓（{_s_m}→{_e_m}）",
                            showlegend=False,
                        ))
                        tick_vals.append(x_offset + _n // 2)
                        tick_texts.append(f"{_s_m}→{_e_m}")
                        name_annotations.append(dict(
                            x=x_offset + _n // 2, y=1.0,
                            xref="x", yref="paper",
                            text="💰 空仓",
                            showarrow=False,
                            font=dict(size=13, color="#bbbbbb"),
                            xanchor="center", yanchor="bottom",
                        ))
                        if x_offset > 0:
                            boundary_xs.append(x_offset - 0.5)
                        x_offset += _n
                continue
            _wkd = _pc.get(_tk)
            if _wkd is None or _wkd.empty:
                continue
            _sd = pd.Timestamp(f"{_s_m}-01")
            _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
            _mask = (_wkd.index >= _sd) & (_wkd.index <= _ed)
            _seg_wk = _wkd[_mask].copy()
            _closes = _seg_wk["Close"].astype(float).dropna()
            if len(_closes) < 2:
                continue

            _n = len(_closes)
            _x_vals = list(range(x_offset, x_offset + _n))
            _color = _SLOT_COLORS[_ci % len(_SLOT_COLORS)]
            _cn = _nm.get(_tk, _tk)

            # 本段内部收益率（%），叠加到累计收益率
            _seg_pct = (_closes / float(_closes.iloc[0]) - 1) * 100
            _seg_cum = running_return + _seg_pct

            fig.add_trace(go.Scatter(
                x=_x_vals,
                y=_seg_cum.values,
                mode="lines",
                line=dict(color=_color, width=2),
                name=f"{_cn}（{_s_m}→{_e_m}）",
                showlegend=False,
            ))

            running_return = float(_seg_cum.iloc[-1])

            if spy_close is not None:
                _spy_seg = spy_close.reindex(_closes.index, method="ffill")
                _spy_seg = _spy_seg.bfill().dropna()
                if len(_spy_seg) >= 2:
                    _spy_pct = (_spy_seg / float(_spy_seg.iloc[0]) - 1) * 100
                    _spy_cum = spy_running_return + _spy_pct
                    for _si, _sdt in enumerate(_closes.index):
                        if _sdt in _spy_seg.index:
                            spy_x_all.append(x_offset + _si)
                            spy_y_all.append(float(_spy_cum.loc[_sdt]))
                    spy_running_return = float(_spy_cum.iloc[-1])

            # x 轴只显示时间区间，名称单独以 annotation 显示在图表顶部
            tick_vals.append(x_offset + _n // 2)
            tick_texts.append(f"{_s_m}→{_e_m}")

            name_annotations.append(dict(
                x=x_offset + _n // 2,
                y=1.0,
                xref="x",
                yref="paper",
                text=_cn,
                showarrow=False,
                font=dict(size=13, color=_color),
                xanchor="center",
                yanchor="bottom",
            ))

            if x_offset > 0:
                boundary_xs.append(x_offset - 0.5)

            x_offset += _n

        for _bx in boundary_xs:
            fig.add_vline(x=_bx, line_dash="dash",
                          line_color="rgba(200,200,200,0.35)", line_width=1)

        if spy_x_all:
            fig.add_trace(go.Scatter(
                x=spy_x_all,
                y=spy_y_all,
                mode="lines",
                line=dict(color="rgba(180,180,180,0.4)", width=2, dash="dot"),
                name=f"SPY 同期 {spy_running_return:+.1f}%",
            ))
            fig.data = fig.data[-1:] + fig.data[:-1]

        fig.update_layout(
            title=f"{slot_name} — 累计收益率（共 {len(segs)} 段）",
            xaxis=dict(
                tickvals=tick_vals,
                ticktext=tick_texts,
                tickfont=dict(size=11),
                tickangle=-30,
                gridcolor="rgba(100,100,100,0.3)",
            ),
            yaxis=dict(
                title="累计收益率 (%)",
                ticksuffix="%",
                gridcolor="rgba(100,100,100,0.3)",
            ),
            annotations=name_annotations,
            height=560,
            margin=dict(l=10, r=10, t=44, b=60),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(30,30,30,0.6)",
            font=dict(color="#ccc", size=13),
            showlegend=bool(spy_x_all),
        )
        return fig

    # ── 计算每列总收益与最大回撤 ──────────────────────────────────────
    def _calc_slot_stats(
        segs: list, price_cache: dict = None, spy_wk: pd.DataFrame = None,
        cash_rate: float = 0.04,
    ) -> tuple:
        _pc2 = price_cache if price_cache is not None else {}
        nav_all: list = []
        running_nav = 1.0
        for _tk, _s_m, _e_m in segs:
            if _tk == "CASH":
                # 闸门关月份：按 cash_rate 年化复利累积，用 SPY 时间轴补日期
                if spy_wk is not None and not spy_wk.empty:
                    _sd = pd.Timestamp(f"{_s_m}-01")
                    _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
                    _cash_idx = spy_wk.index[(spy_wk.index >= _sd) & (spy_wk.index <= _ed)]
                    if len(_cash_idx) >= 1:
                        _days = (_cash_idx - _cash_idx[0]).days.to_numpy()
                        _cash_nav = running_nav * (1.0 + cash_rate) ** (_days / 365.0)
                        _cash_series = pd.Series(_cash_nav, index=_cash_idx, dtype=float)
                        nav_all.append(_cash_series)
                        running_nav = float(_cash_series.iloc[-1])
                continue
            _wkd = _pc2.get(_tk)
            if _wkd is None or _wkd.empty:
                continue
            _sd = pd.Timestamp(f"{_s_m}-01")
            _ed = pd.Timestamp(f"{_e_m}-01") + pd.offsets.MonthEnd(1)
            _mask = (_wkd.index >= _sd) & (_wkd.index <= _ed)
            _seg_wk = _wkd[_mask].copy()
            _closes = _seg_wk["Close"].astype(float).dropna()
            if len(_closes) < 2:
                continue
            _seg_nav = (_closes / float(_closes.iloc[0])) * running_nav
            running_nav = float(_seg_nav.iloc[-1])
            nav_all.append(_seg_nav)
        if not nav_all:
            return 0.0, 0.0, pd.Series(dtype=float)
        _nav = pd.concat(nav_all).sort_index()
        _nav = _nav[~_nav.index.duplicated(keep="last")]
        _total_ret = (float(_nav.iloc[-1]) / float(_nav.iloc[0]) - 1) * 100
        _peak = _nav.cummax()
        _dd = (_peak - _nav) / _peak.replace(0, float("nan"))
        _max_dd = float(_dd.max()) * 100
        return _total_ret, _max_dd, _nav

    def _compute_nav_kpi(nav: pd.Series) -> dict:
        """Calmar / log-NAV R² / Sortino（周线 NAV 输入，√52 年化）。"""
        import numpy as np
        import math
        if nav.empty or len(nav) < 8:
            return {"calmar": float("nan"), "r2": float("nan"), "sortino": float("nan")}
        nav = nav.astype(float).dropna()
        wk_ret = nav.pct_change().dropna()
        years = len(nav) / 52.0
        if years < 0.1:
            return {"calmar": float("nan"), "r2": float("nan"), "sortino": float("nan")}
        cagr = (float(nav.iloc[-1]) / float(nav.iloc[0])) ** (1.0 / years) - 1.0
        peak = nav.cummax()
        max_dd = abs(float((nav / peak - 1.0).min()))
        calmar = cagr / max_dd if max_dd > 1e-9 else float("nan")
        log_nav = np.log(nav.values)
        x = np.arange(len(log_nav), dtype=float)
        coeffs = np.polyfit(x, log_nav, 1)
        pred = np.polyval(coeffs, x)
        ss_res = float(np.sum((log_nav - pred) ** 2))
        ss_tot = float(np.sum((log_nav - log_nav.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
        neg_rets = wk_ret[wk_ret < 0]
        down_std = float(neg_rets.std()) * (52.0 ** 0.5) if len(neg_rets) > 1 else float("nan")
        sortino = cagr / down_std if (down_std and not math.isnan(down_std) and down_std > 1e-9) else float("nan")
        return {"calmar": calmar, "r2": r2, "sortino": sortino}

    def _fmt_kpi(v, fmt=".2f") -> str:
        import math
        try:
            if math.isnan(v):
                return "—"
            return f"{v:{fmt}}"
        except (TypeError, ValueError):
            return "—"

    # ═══════════════════════════════════════════════════════════════════
    #  Section: A/B 级累计收益率图（Tab 切换）
    # ═══════════════════════════════════════════════════════════════════
    st.header("📈 累计收益率图")
    st.caption("左/右列 = Page 4 月度 Top-2 的 slot-stable 分配；颜色区分持仓期，💰 空仓 = 闸门关")

    _main_tab_a, _main_tab_b = st.tabs(["🛡️ A 级（避风港）", "🏦 B 级（压舱石）"])

    with _main_tab_a:
        # 闸门关闭告警（当月最新月份优先显示）
        _a_closed = _gate_closed_by_cls.get("A", [])
        if _a_closed:
            _a_latest_m = _tm_months[-1] if _tm_months else ""
            _a_cur_reason = next((r for m, r in _a_closed if m == _a_latest_m), None)
            if _a_cur_reason is not None:
                st.error(f"🚧 **A 组闸门关（{_a_latest_m}）**：{_a_cur_reason or '本月空仓'}")
            if len(_a_closed) > (1 if _a_cur_reason is not None else 0):
                with st.expander(f"⚠️ A 组历史闸门关（{len(_a_closed)} 个月）", expanded=False):
                    for _ag_m, _ag_r in _a_closed:
                        st.markdown(f"- **{_ag_m}**：{_ag_r or '不满足持仓条件'}")

        if _a_section_error:
            st.error(_a_section_error)

        _p5_cash_rate = st.session_state.get("p5_cash_annual_return", 0.04)
        _ret_left, _dd_left, _nav_left = _calc_slot_stats(_seg_left, _a_price_cache, _spy_wk_a, cash_rate=_p5_cash_rate)
        _ret_right, _dd_right, _nav_right = _calc_slot_stats(_seg_right, _a_price_cache, _spy_wk_a, cash_rate=_p5_cash_rate)

        # ── 合成 A 级整体（等权或信念倾斜）────────────────────────────────
        _ret_combined, _dd_combined = 0.0, 0.0
        _nav_combined: pd.Series = pd.Series(dtype=float)
        if not _nav_left.empty and not _nav_right.empty:
            _idx_union = _nav_left.index.union(_nav_right.index)
            _nl = _nav_left.reindex(_idx_union).ffill().bfill()
            _nr = _nav_right.reindex(_idx_union).ffill().bfill()
            if _weight_mode.startswith("信念倾斜"):
                _month_keys_arr = _idx_union.strftime("%Y-%m")
                _w_left_arr = pd.Series(
                    [_a_slot_weights.get(_mk, (0.5, 0.5))[0] for _mk in _month_keys_arr],
                    index=_idx_union, dtype=float,
                )
                _w_right_arr = 1.0 - _w_left_arr
                _nav_combined = (_w_left_arr * _nl + _w_right_arr * _nr).astype(float)
            else:
                _nav_combined = 0.5 * _nl + 0.5 * _nr
            _ret_combined = (float(_nav_combined.iloc[-1]) / float(_nav_combined.iloc[0]) - 1) * 100
            _peak_c = _nav_combined.cummax()
            _dd_c = (_peak_c - _nav_combined) / _peak_c.replace(0, float("nan"))
            _dd_combined = float(_dd_c.max()) * 100
        elif not _nav_left.empty:
            _ret_combined, _dd_combined = _ret_left, _dd_left
            _nav_combined = _nav_left.copy()
        elif not _nav_right.empty:
            _ret_combined, _dd_combined = _ret_right, _dd_right
            _nav_combined = _nav_right.copy()

        # ── 换仓次数统计 ────────────────────────────────────────────────
        _a_months_with_hold = [m for m in _tm_months if _tm_hold["A"].get(m)]
        _switch_count = sum(
            1 for _i in range(1, len(_a_months_with_hold))
            if _tm_hold["A"].get(_a_months_with_hold[_i]) != _tm_hold["A"].get(_a_months_with_hold[_i - 1])
        )

        _a_friction_pct = _switch_count * _p5_per_switch_friction * 100
        _a_net_ret = _ret_combined - _a_friction_pct

        _a_adv: dict = {}
        _spy_adv_a: dict = {}
        if not _nav_combined.empty:
            _a_adv = _compute_nav_kpi(_nav_combined)
            if _spy_wk_a is not None and not _spy_wk_a.empty:
                _spy_mask_a = (
                    (_spy_wk_a.index >= _nav_combined.index[0])
                    & (_spy_wk_a.index <= _nav_combined.index[-1])
                )
                _spy_close_a = _spy_wk_a[_spy_mask_a]["Close"].astype(float).dropna()
                if len(_spy_close_a) >= 8:
                    _spy_nav_a = _spy_close_a / float(_spy_close_a.iloc[0])
                    _spy_adv_a = _compute_nav_kpi(_spy_nav_a)

        _buf_col_p5, _w_col = st.columns([1, 2])
        with _buf_col_p5:
            st.number_input(
                "守擂缓冲区 Top-N",
                min_value=2,
                max_value=_p5_max_buffer_n,
                step=1,
                key="p5_buffer_n_input",
                help=f"数据深度 {_p5_min_depth} 条/赛道/月。修改后图表立即更新，与 Page 4 双向同步。",
            )
            _effective_p5 = min(int(st.session_state["p5_buffer_n_input"]), _p5_max_buffer_n)
            if _effective_p5 != st.session_state.get("confirmed_buffer_n"):
                st.session_state["confirmed_buffer_n"] = _effective_p5
                _save_buffer_n_p5(_effective_p5)
                st.session_state["_p5_buffer_synced"] = _effective_p5
        with _w_col:
            st.radio(
                "合成权重", ["等权 50/50", "信念倾斜（按在榜月数）"],
                horizontal=True, key="a_weight_mode",
            )

        st.caption(
            f"Top-{_buffer_n}（上限 {_p5_min_depth}）｜"
            f"换仓 **{_switch_count}** 次 × 4腿 ｜ "
            f"摩擦 **-{_a_friction_pct:.1f}%**（佣金 {_p5_commission_pct:.2f}% + 滑点 {_p5_slippage_pct:.2f}%）"
        )

        st.markdown("**🟨 A 级合成**")
        _ac1, _ac2, _ac3, _ac4, _ac5 = st.columns(5)
        _ac1.metric(
            "总收益（毛）", f"{_ret_combined:+.1f}%",
            delta=f"净 {_a_net_ret:+.1f}%", delta_color="off",
        )
        _ac2.metric("最大回撤", f"-{_dd_combined:.1f}%")
        if _a_adv:
            _ac3.metric(
                "Calmar", _fmt_kpi(_a_adv.get("calmar", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_a.get('calmar', float('nan')))}" if _spy_adv_a else None,
                delta_color="off",
            )
            _ac4.metric(
                "logNAV R²", _fmt_kpi(_a_adv.get("r2", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_a.get('r2', float('nan')))}" if _spy_adv_a else None,
                delta_color="off",
            )
            _ac5.metric(
                "Sortino", _fmt_kpi(_a_adv.get("sortino", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_a.get('sortino', float('nan')))}" if _spy_adv_a else None,
                delta_color="off",
            )

        _block_l, _block_r = st.columns(2)
        with _block_l:
            st.markdown("**🟦 左列 Slot 0**")
            _lc1, _lc2 = st.columns(2)
            _lc1.metric("总收益", f"{_ret_left:+.1f}%")
            _lc2.metric("最大回撤", f"-{_dd_left:.1f}%")
        with _block_r:
            st.markdown("**🟦 右列 Slot 1**")
            _rc1, _rc2 = st.columns(2)
            _rc1.metric("总收益", f"{_ret_right:+.1f}%")
            _rc2.metric("最大回撤", f"-{_dd_right:.1f}%")

        if _weight_mode.startswith("信念倾斜") and _a_slot_weights:
            _avg_wl = sum(v[0] for v in _a_slot_weights.values()) / max(len(_a_slot_weights), 1)
            _avg_wr = 1.0 - _avg_wl
            st.caption(
                f"信念倾斜模式：历史月均权重 左列 **{_avg_wl*100:.0f}%** / 右列 **{_avg_wr*100:.0f}%**"
                "（streak 更长的 slot 权重更高，范围限制在 30%-70%）"
            )

        _tab_left, _tab_right, _tab_combined = st.tabs([
            "📈 左列 (Slot 0)", "📈 右列 (Slot 1)", "📊 合成收益率",
        ])
        with _tab_left:
            _fig_left = _build_stitched_kline_fig(_seg_left, "左列 (Slot 0)", _spy_wk_a, _a_price_cache, _name_map)
            st.plotly_chart(_fig_left, use_container_width=True, key="a_slot0_chart")
        with _tab_right:
            _fig_right = _build_stitched_kline_fig(_seg_right, "右列 (Slot 1)", _spy_wk_a, _a_price_cache, _name_map)
            st.plotly_chart(_fig_right, use_container_width=True, key="a_slot1_chart")
        with _tab_combined:
            if not _nav_combined.empty:
                _fig_comb = go.Figure()
                _nav_pct = (_nav_combined / float(_nav_combined.iloc[0]) - 1) * 100
                _fig_comb.add_trace(go.Scatter(
                    x=_nav_pct.index, y=_nav_pct.values,
                    mode="lines", name=f"A 级合成（{_weight_mode.split('（')[0]}）",
                    line=dict(color="#F1C40F", width=2),
                ))
                if _spy_wk_a is not None and not _spy_wk_a.empty:
                    _spy_mask_c = (
                        (_spy_wk_a.index >= _nav_combined.index[0])
                        & (_spy_wk_a.index <= _nav_combined.index[-1])
                    )
                    _spy_seg_c = _spy_wk_a[_spy_mask_c]["Close"].astype(float).dropna()
                    if len(_spy_seg_c) >= 2:
                        _spy_pct_c = (_spy_seg_c / float(_spy_seg_c.iloc[0]) - 1) * 100
                        _fig_comb.add_trace(go.Scatter(
                            x=_spy_pct_c.index, y=_spy_pct_c.values,
                            mode="lines", name="SPY",
                            line=dict(color="#888", width=1.5, dash="dot"),
                        ))
                _fig_comb.update_layout(
                    title=f"A 级合成收益率（{_weight_mode}）",
                    xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
                    yaxis=dict(title="累计收益率 (%)", ticksuffix="%", gridcolor="rgba(100,100,100,0.3)"),
                    height=520,
                    margin=dict(l=10, r=10, t=44, b=60),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(30,30,30,0.6)",
                    font=dict(color="#ccc", size=13),
                    showlegend=True,
                )
                st.plotly_chart(_fig_comb, use_container_width=True, key="a_combined_chart")
            else:
                st.info("暂无足够数据生成合成收益率图。")

    with _main_tab_b:
        # 闸门关闭告警
        _b_closed = _gate_closed_by_cls.get("B", [])
        if _b_closed:
            _b_latest_m = _tm_months[-1] if _tm_months else ""
            _b_cur_reason = next((r for m, r in _b_closed if m == _b_latest_m), None)
            if _b_cur_reason is not None:
                st.error(f"🚧 **B 组闸门关（{_b_latest_m}）**：{_b_cur_reason or '本月空仓'}")
            if len(_b_closed) > (1 if _b_cur_reason is not None else 0):
                with st.expander(f"⚠️ B 组历史闸门关（{len(_b_closed)} 个月）", expanded=False):
                    for _bg_m, _bg_r in _b_closed:
                        st.markdown(f"- **{_bg_m}**：{_bg_r or '不满足持仓条件'}")

        if _b_section_error:
            st.error(_b_section_error)

        _b_ret_left, _b_dd_left, _b_nav_left = _calc_slot_stats(_b_seg_left, _b_price_cache, _spy_wk_a, cash_rate=_p5_cash_rate)
        _b_ret_right, _b_dd_right, _b_nav_right = _calc_slot_stats(_b_seg_right, _b_price_cache, _spy_wk_a, cash_rate=_p5_cash_rate)

        # ── 合成 B 级整体（等权或信念倾斜）────────────────────────────────
        _b_ret_combined, _b_dd_combined = 0.0, 0.0
        _b_nav_combined: pd.Series = pd.Series(dtype=float)
        if not _b_nav_left.empty and not _b_nav_right.empty:
            _b_idx_union = _b_nav_left.index.union(_b_nav_right.index)
            _b_nl = _b_nav_left.reindex(_b_idx_union).ffill().bfill()
            _b_nr = _b_nav_right.reindex(_b_idx_union).ffill().bfill()
            if _b_weight_mode.startswith("信念倾斜"):
                _b_month_keys_arr = _b_idx_union.strftime("%Y-%m")
                _b_w_left_arr = pd.Series(
                    [_b_slot_weights.get(_mk, (0.5, 0.5))[0] for _mk in _b_month_keys_arr],
                    index=_b_idx_union, dtype=float,
                )
                _b_w_right_arr = 1.0 - _b_w_left_arr
                _b_nav_combined = (_b_w_left_arr * _b_nl + _b_w_right_arr * _b_nr).astype(float)
            else:
                _b_nav_combined = 0.5 * _b_nl + 0.5 * _b_nr
            _b_ret_combined = (float(_b_nav_combined.iloc[-1]) / float(_b_nav_combined.iloc[0]) - 1) * 100
            _b_peak_c = _b_nav_combined.cummax()
            _b_dd_c = (_b_peak_c - _b_nav_combined) / _b_peak_c.replace(0, float("nan"))
            _b_dd_combined = float(_b_dd_c.max()) * 100
        elif not _b_nav_left.empty:
            _b_ret_combined, _b_dd_combined = _b_ret_left, _b_dd_left
            _b_nav_combined = _b_nav_left.copy()
        elif not _b_nav_right.empty:
            _b_ret_combined, _b_dd_combined = _b_ret_right, _b_dd_right
            _b_nav_combined = _b_nav_right.copy()

        # ── 换仓次数统计 ────────────────────────────────────────────────
        _b_months_with_hold = [m for m in _tm_months if _tm_hold["B"].get(m)]
        _b_switch_count = sum(
            1 for _i in range(1, len(_b_months_with_hold))
            if _tm_hold["B"].get(_b_months_with_hold[_i]) != _tm_hold["B"].get(_b_months_with_hold[_i - 1])
        )

        _b_friction_pct = _b_switch_count * _p5_per_switch_friction * 100
        _b_net_ret = _b_ret_combined - _b_friction_pct

        _b_adv: dict = {}
        _spy_adv_b: dict = {}
        if not _b_nav_combined.empty:
            _b_adv = _compute_nav_kpi(_b_nav_combined)
            if _spy_wk_a is not None and not _spy_wk_a.empty:
                _spy_mask_b = (
                    (_spy_wk_a.index >= _b_nav_combined.index[0])
                    & (_spy_wk_a.index <= _b_nav_combined.index[-1])
                )
                _spy_close_b = _spy_wk_a[_spy_mask_b]["Close"].astype(float).dropna()
                if len(_spy_close_b) >= 8:
                    _spy_nav_b = _spy_close_b / float(_spy_close_b.iloc[0])
                    _spy_adv_b = _compute_nav_kpi(_spy_nav_b)

        st.radio(
            "合成权重", ["等权 50/50", "信念倾斜（按在榜月数）"],
            horizontal=True, key="b_weight_mode",
        )

        st.caption(
            f"Top-{_buffer_n}（上限 {_p5_min_depth}）｜"
            f"换仓 **{_b_switch_count}** 次 × 4腿 ｜ "
            f"摩擦 **-{_b_friction_pct:.1f}%**（佣金 {_p5_commission_pct:.2f}% + 滑点 {_p5_slippage_pct:.2f}%）"
        )

        st.markdown("**🟨 B 级合成**")
        _bc1, _bc2, _bc3, _bc4, _bc5 = st.columns(5)
        _bc1.metric(
            "总收益（毛）", f"{_b_ret_combined:+.1f}%",
            delta=f"净 {_b_net_ret:+.1f}%", delta_color="off",
        )
        _bc2.metric("最大回撤", f"-{_b_dd_combined:.1f}%")
        if _b_adv:
            _bc3.metric(
                "Calmar", _fmt_kpi(_b_adv.get("calmar", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_b.get('calmar', float('nan')))}" if _spy_adv_b else None,
                delta_color="off",
            )
            _bc4.metric(
                "logNAV R²", _fmt_kpi(_b_adv.get("r2", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_b.get('r2', float('nan')))}" if _spy_adv_b else None,
                delta_color="off",
            )
            _bc5.metric(
                "Sortino", _fmt_kpi(_b_adv.get("sortino", float("nan"))),
                delta=f"SPY {_fmt_kpi(_spy_adv_b.get('sortino', float('nan')))}" if _spy_adv_b else None,
                delta_color="off",
            )

        _b_block_l, _b_block_r = st.columns(2)
        with _b_block_l:
            st.markdown("**🟦 左列 Slot 0**")
            _b_lc1, _b_lc2 = st.columns(2)
            _b_lc1.metric("总收益", f"{_b_ret_left:+.1f}%")
            _b_lc2.metric("最大回撤", f"-{_b_dd_left:.1f}%")
        with _b_block_r:
            st.markdown("**🟦 右列 Slot 1**")
            _b_rc1, _b_rc2 = st.columns(2)
            _b_rc1.metric("总收益", f"{_b_ret_right:+.1f}%")
            _b_rc2.metric("最大回撤", f"-{_b_dd_right:.1f}%")

        if _b_weight_mode.startswith("信念倾斜") and _b_slot_weights:
            _b_avg_wl = sum(v[0] for v in _b_slot_weights.values()) / max(len(_b_slot_weights), 1)
            _b_avg_wr = 1.0 - _b_avg_wl
            st.caption(
                f"信念倾斜模式：历史月均权重 左列 **{_b_avg_wl*100:.0f}%** / 右列 **{_b_avg_wr*100:.0f}%**"
                "（streak 更长的 slot 权重更高，范围限制在 30%-70%）"
            )

        _b_tab_left, _b_tab_right, _b_tab_combined = st.tabs([
            "📈 左列 (Slot 0)", "📈 右列 (Slot 1)", "📊 合成收益率",
        ])
        with _b_tab_left:
            _b_fig_left = _build_stitched_kline_fig(_b_seg_left, "左列 (Slot 0)", _spy_wk_a, _b_price_cache, _name_map)
            st.plotly_chart(_b_fig_left, use_container_width=True, key="b_slot0_chart")
        with _b_tab_right:
            _b_fig_right = _build_stitched_kline_fig(_b_seg_right, "右列 (Slot 1)", _spy_wk_a, _b_price_cache, _name_map)
            st.plotly_chart(_b_fig_right, use_container_width=True, key="b_slot1_chart")
        with _b_tab_combined:
            if not _b_nav_combined.empty:
                _b_fig_comb = go.Figure()
                _b_nav_pct = (_b_nav_combined / float(_b_nav_combined.iloc[0]) - 1) * 100
                _b_fig_comb.add_trace(go.Scatter(
                    x=_b_nav_pct.index, y=_b_nav_pct.values,
                    mode="lines", name=f"B 级合成（{_b_weight_mode.split('（')[0]}）",
                    line=dict(color="#3498DB", width=2),
                ))
                if _spy_wk_a is not None and not _spy_wk_a.empty:
                    _b_spy_mask_c = (
                        (_spy_wk_a.index >= _b_nav_combined.index[0])
                        & (_spy_wk_a.index <= _b_nav_combined.index[-1])
                    )
                    _b_spy_seg_c = _spy_wk_a[_b_spy_mask_c]["Close"].astype(float).dropna()
                    if len(_b_spy_seg_c) >= 2:
                        _b_spy_pct_c = (_b_spy_seg_c / float(_b_spy_seg_c.iloc[0]) - 1) * 100
                        _b_fig_comb.add_trace(go.Scatter(
                            x=_b_spy_pct_c.index, y=_b_spy_pct_c.values,
                            mode="lines", name="SPY",
                            line=dict(color="#888", width=1.5, dash="dot"),
                        ))
                _b_fig_comb.update_layout(
                    title=f"B 级合成收益率（{_b_weight_mode}）",
                    xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
                    yaxis=dict(title="累计收益率 (%)", ticksuffix="%", gridcolor="rgba(100,100,100,0.3)"),
                    height=520,
                    margin=dict(l=10, r=10, t=44, b=60),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(30,30,30,0.6)",
                    font=dict(color="#ccc", size=13),
                    showlegend=True,
                )
                st.plotly_chart(_b_fig_comb, use_container_width=True, key="b_combined_chart")
            else:
                st.info("暂无足够数据生成合成收益率图。")

    # ═══════════════════════════════════════════════════════════════════
    #  Section 0: 资产细筛盈利统计
    # ═══════════════════════════════════════════════════════════════════
    st.header("📊 资产细筛盈利统计")
    st.caption("汇总各赛道细筛入选标的的持有期盈亏 — 按退出时间倒序排列")

    # ── B赛道分数归零异常告警 ──
    if _score_anomalies:
        with st.expander(f"⚠️ B赛道数据异常告警 — {len(_score_anomalies)} 条分数归零记录（点击展开）",
                         expanded=False):
            st.markdown("""
<div style='background:rgba(231,76,60,0.08); border-left:4px solid #E74C3C;
            padding:14px 18px; border-radius:0 8px 8px 0; margin-bottom:14px;
            font-size:14px; color:#ddd; line-height:1.7;'>
<b style='color:#E74C3C;'>分数归零 = 评分系统未能获取该标的当月数据</b><br>
这会导致信念快速衰减、持仓被错误剔除。建议排查后端 <code>compute_scorecard_b()</code>
对应月份的数据拉取是否正常，修复后重新回填历史。
</div>""", unsafe_allow_html=True)
            _anom_df = pd.DataFrame(_score_anomalies)
            _anom_df.columns = ["月份", "标的", "名称", "排名", "信念"]
            st.dataframe(_anom_df, use_container_width=True, hide_index=True)

    _pf_cls_opts = {"全部": ["A", "B", "C", "D"], "A": ["A"], "B": ["B"], "C": ["C"], "D": ["D"]}
    _pf_cls_sel = st.selectbox(
        "筛选赛道", list(_pf_cls_opts.keys()),
        format_func=lambda x: x if x == "全部" else _CLS_LBL[x],
        key="pf_cls_sel",
    )
    _pf_classes = _pf_cls_opts[_pf_cls_sel]

    _seen_tickers: set = set()
    for _c_nm in _pf_classes:
        _seen_tickers.update(tk for hset in _tm_hold[_c_nm].values() for tk in hset if tk != "CASH")

    _profit_rows: list = []
    with st.spinner("正在汇总持仓盈亏..."):
        _price_cache: dict = {}
        for _tk in sorted(_seen_tickers):
            try:
                _wk_data = _fetch_weekly_ohlcv(_tk)
                if not _wk_data.empty:
                    _price_cache[_tk] = _wk_data
            except Exception:
                pass

        _spy_wk = _price_cache.get("SPY")
        if _spy_wk is None:
            try:
                _spy_wk = _fetch_weekly_ohlcv("SPY")
            except Exception:
                _spy_wk = pd.DataFrame()

        for _c_nm in _pf_classes:
            _all_c_tickers = sorted({tk for hset in _tm_hold[_c_nm].values() for tk in hset if tk != "CASH"})
            for _tk in _all_c_tickers:
                _pds = _get_holding_periods(_tm_hold[_c_nm], _tk)
                _wk = _price_cache.get(_tk)
                if _wk is None or _wk.empty:
                    continue
                for _sm, _em in _pds:
                    _sd = pd.Timestamp(f"{_sm}-01")
                    _ed = pd.Timestamp(f"{_em}-01") + pd.offsets.MonthEnd(1)
                    _mask = (_wk.index >= _sd) & (_wk.index <= _ed)
                    _seg = _wk[_mask]
                    if _seg.empty:
                        continue
                    _ep = float(_seg["Open"].astype(float).iloc[0])
                    _xp = float(_seg["Close"].astype(float).iloc[-1])
                    if _ep <= 0:
                        continue
                    _pnl_pct = (_xp / _ep - 1) * 100
                    _n_months = len([m for m in _tm_months if _sm <= m <= _em])
                    _cn = _name_map.get(_tk, _tk)

                    _years = max(_n_months, 1) / 12.0
                    _asset_ratio = _xp / _ep
                    _cagr_str = "—"
                    if _asset_ratio > 0:
                        _cagr = (_asset_ratio ** (1.0 / _years) - 1) * 100
                        _cagr_str = f"{_cagr:+.1f}%"

                    _spy_ret_str = "—"
                    _spy_ret_val = 0.0
                    if _spy_wk is not None and not _spy_wk.empty:
                        _spy_seg = _spy_wk[(_spy_wk.index >= _sd) & (_spy_wk.index <= _ed)]
                        if not _spy_seg.empty:
                            _spy_ep = float(_spy_seg["Open"].astype(float).iloc[0])
                            _spy_xp = float(_spy_seg["Close"].astype(float).iloc[-1])
                            if _spy_ep > 0:
                                _spy_ret_val = (_spy_xp / _spy_ep - 1) * 100
                                _spy_ret_str = f"{_spy_ret_val:+.1f}%"

                    _profit_rows.append({
                        "赛道": _c_nm,
                        "标的": f"{_tk} ({_cn})",
                        "入选月": _sm,
                        "退选月": _em,
                        "持有时长": f"{_n_months} 个月",
                        "入选价": f"${_ep:.2f}",
                        "退选价": f"${_xp:.2f}",
                        "盈亏": f"{_pnl_pct:+.1f}%",
                        "复合年化": _cagr_str,
                        "同期SPY": _spy_ret_str,
                        "_sort_key": _em,
                        "_pnl": _pnl_pct,
                        "_spy_ret": _spy_ret_val,
                    })

    if _profit_rows:
        _profit_df = pd.DataFrame(_profit_rows)
        _profit_df = _profit_df.sort_values("_sort_key", ascending=False).reset_index(drop=True)
        _total = len(_profit_df)
        _wins = len(_profit_df[_profit_df["_pnl"] > 0])
        _avg_pnl = _profit_df["_pnl"].mean()

        _mc1, _mc2, _mc3 = st.columns(3)
        _mc1.metric("总交易段数", f"{_total}")
        _mc2.metric("胜率", f"{_wins / _total * 100:.0f}%" if _total > 0 else "—")
        _mc3.metric("平均盈亏", f"{_avg_pnl:+.1f}%")

        _display_cols = ["赛道", "标的", "入选月", "退选月", "持有时长", "入选价", "退选价", "盈亏", "复合年化", "同期SPY"]

        def _style_pnl_vs_spy(s):
            """盈亏列：跑赢同期 SPY → 绿；跑输 → 红；无 SPY 数据 → 不染色。"""
            styles = []
            for i in s.index:
                _pnl_v = _profit_df.at[i, "_pnl"]
                _spy_v = _profit_df.at[i, "_spy_ret"]
                _spy_avail = _profit_df.at[i, "同期SPY"] != "—"
                if not _spy_avail:
                    styles.append("")
                elif _pnl_v > _spy_v:
                    styles.append("color: #27AE60; font-weight:600")
                else:
                    styles.append("color: #E74C3C; font-weight:600")
            return styles

        _styled_df = _profit_df[_display_cols].style.apply(_style_pnl_vs_spy, subset=["盈亏"])
        st.dataframe(
            _styled_df,
            use_container_width=True, hide_index=True,
            height=min(900, 35 * len(_profit_df) + 38),
        )
    else:
        st.info("无法获取足够的价格数据来计算盈亏统计。")

    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════
#  Section 1: 竞技场持仓择时回顾 (Arena Timing Review)
# ═══════════════════════════════════════════════════════════════════
st.header("🕐 竞技场持仓择时回顾")
st.caption("复盘各赛道历史选股 — 🟩 绿色区域 = 细筛入选 | ▲ 买入 ▼ 卖出 = MA 择时信号")

if _arena_data:
    # ── 用户控件 ──
    _cc1, _cc2, _cc3 = st.columns([1, 3, 2])
    with _cc1:
        _tm_cls = st.selectbox(
            "选择赛道", ["A", "B", "C", "D"],
            format_func=lambda x: _CLS_LBL[x], key="tm_cls",
        )
    _all_tk = sorted({tk for hset in _tm_hold[_tm_cls].values() for tk in hset if tk != "CASH"})
    with _cc2:
        _tm_sel = st.multiselect(
            "选择标的（可多选）", _all_tk,
            default=_all_tk[:2] if len(_all_tk) >= 2 else _all_tk,
            key="tm_sel",
        )
    with _cc3:
        _tm_tools_sel = st.multiselect(
            "择时工具（可多选对比）",
            list(_TIMING_TOOLS.keys()),
            default=["ma_cross"],
            format_func=lambda x: _TIMING_TOOLS[x]["label"],
            key="tm_tools_sel",
        )
    if not _tm_tools_sel:
        _tm_tools_sel = ["ma_cross"]

    # ── 择时风控逻辑白盒（动态展示选中工具说明）──
    with st.expander("📐 择时风控逻辑白盒 — 点击展开", expanded=False):
        _wb_parts = []
        for _tid in _tm_tools_sel:
            _tclr = _TOOL_COLORS[_tid]["buy"]
            _tlab = _TIMING_TOOLS[_tid]["label"]
            if _tid == "ma_cross":
                _wb_parts.append(
                    f"<b style='color:{_tclr};'>▶ {_tlab}</b>（当前赛道：{_CLS_LBL[_tm_cls]}）<br>"
                    f"&nbsp;&nbsp;• <b>A/B 组</b>：MA12w 金叉 MA60w 买入，死叉卖出（等效日线 MA60/MA300 交叉）<br>"
                    f"&nbsp;&nbsp;• <b>C 组</b>：价格站上 MA8w 买入，跌破卖出（等效日线 MA40）<br>"
                    f"&nbsp;&nbsp;• <b>D 组</b>：价格站上 MA4w 买入，跌破卖出（等效日线 MA20）"
                )
            elif _tid == "break_ma60":
                _wb_parts.append(
                    f"<b style='color:{_tclr};'>▶ {_tlab}</b><br>"
                    f"&nbsp;&nbsp;• 价格站上 MA60w（≈ 日线 MA300）视为趋势健康，买入持有<br>"
                    f"&nbsp;&nbsp;• 价格跌破 MA60w 生命线，无论赛道或信念，强制清仓"
                )
            elif _tid == "break_ma20":
                _wb_parts.append(
                    f"<b style='color:{_tclr};'>▶ {_tlab}</b><br>"
                    f"&nbsp;&nbsp;• 价格站上 MA20w（≈ 日线 MA100）买入持有<br>"
                    f"&nbsp;&nbsp;• 价格跌破 MA20w 卖出，适合 C/D 组短周期趋势标的"
                )
            elif _tid == "rapid_drop":
                _wb_parts.append(
                    f"<b style='color:{_tclr};'>▶ {_tlab}</b><br>"
                    f"&nbsp;&nbsp;• 默认持仓（不主动追高），仅在极端周跌幅 &gt;8% 时紧急平仓<br>"
                    f"&nbsp;&nbsp;• 平仓后等待价格重新站上 MA12w 再回场，规避连续踩踏"
                )
        _wb_html = "<br><br>".join(_wb_parts)
        st.markdown(f"""
<div class='timing-box'>
<b style='font-size:15px; color:#2ECC71;'>核心原则：细筛选人，择时决定上/下场</b><br><br>
<b>📊 图表解读</b><br>
&nbsp;&nbsp;• <b style='color:#2ECC71;'>🟩 绿色半透明区域</b> = 标的在竞技场候选名单中（细筛入选，月度更新）<br>
&nbsp;&nbsp;• <b>各工具买入</b>用不同颜色/形状标注（▲ MA金叉 | ◆ MA60 | ● MA20 | ★ 速断器）<br>
&nbsp;&nbsp;• <b>卖出信号</b>与对应工具同色，形状相同<br><br>
<b>🔄 两层决策分离</b><br>
&nbsp;&nbsp;① <b>细筛层（慢）</b>：月度 Arena 排名 → 决定「谁有资格进组合」→ 对应绿色区域<br>
&nbsp;&nbsp;② <b>择时层（快）</b>：周度信号 → 决定「此刻该持有还是暂泊」<br><br>
<b>🧰 当前选中策略说明</b><br>
{_wb_html}
</div>
""", unsafe_allow_html=True)

    # ── 逐标的绘制 ──
    if not _tm_sel:
        st.info("👆 请在上方选择至少一个标的以查看择时回顾图表。")

    for _tk in _tm_sel:
        _pds = _get_holding_periods(_tm_hold[_tm_cls], _tk)
        if not _pds:
            continue

        with st.spinner(f"正在拉取 {_tk} 周线数据..."):
            _wk = _fetch_weekly_ohlcv(_tk)
        if _wk.empty:
            st.warning(f"⚠️ {_tk} 历史数据不可用")
            continue

        _cn = TIC_MAP.get(_tk, _tk)
        _ma_w = _CLS_MA_WEEKS[_tm_cls]
        _slow_ma_w = _CLS_SLOW_MA[_tm_cls]

        # 运行所有选中的择时工具
        _tool_results: dict = {}
        for _tool_id in _tm_tools_sel:
            _tool_results[_tool_id] = _TIMING_TOOLS[_tool_id]["fn"](
                _wk, _pds, fast_weeks=_ma_w, slow_weeks=_slow_ma_w, drop_pct=8.0,
            )

        _r_rets = _tool_results[_tm_tools_sel[0]].raw_rets

        _fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.03, row_heights=[0.75, 0.25],
        )

        # 灰色 K 线
        _fig.add_trace(go.Candlestick(
            x=_wk.index,
            open=_wk["Open"].astype(float),
            high=_wk["High"].astype(float),
            low=_wk["Low"].astype(float),
            close=_wk["Close"].astype(float),
            increasing_line_color="#666", decreasing_line_color="#444",
            increasing_fillcolor="#555", decreasing_fillcolor="#333",
            name="周线",
        ), row=1, col=1)

        # 各工具叠加线（MA 辅助线等）
        for _tool_id in _tm_tools_sel:
            for _ov in _tool_results[_tool_id].overlays:
                _ov_s = _ov["series"].dropna()
                if not _ov_s.empty:
                    _fig.add_trace(go.Scatter(
                        x=_ov_s.index, y=_ov_s.astype(float),
                        line=dict(color=_ov["color"], width=1.5, dash=_ov["dash"]),
                        name=f"{_TIMING_TOOLS[_tool_id]['label']} · {_ov['label']}",
                    ), row=1, col=1)

        # 灰色成交量
        _fig.add_trace(go.Bar(
            x=_wk.index, y=_wk["Volume"].astype(float),
            marker_color="#444", name="成交量", opacity=0.4,
        ), row=2, col=1)

        # ── 绿色候选区域 + 多工具收益标注 ──
        _price_hi = float(_wk["High"].astype(float).max())
        _detail_rows: list = []
        _tool_cum: dict = {tid: 0.0 for tid in _tm_tools_sel}
        _tool_wins: dict = {tid: 0 for tid in _tm_tools_sel}

        for _i, (_sm, _em) in enumerate(_pds):
            _sd = pd.Timestamp(f"{_sm}-01")
            _ed = pd.Timestamp(f"{_em}-01") + pd.offsets.MonthEnd(1)

            _fig.add_vrect(
                x0=_sd, x1=_ed, fillcolor="#2ECC71", opacity=0.10,
                line=dict(color="#2ECC71", width=1, dash="dot"),
                row=1, col=1,
            )
            _fig.add_vrect(
                x0=_sd, x1=_ed, fillcolor="#2ECC71", opacity=0.06,
                line=dict(width=0), row=2, col=1,
            )

            _rr = _r_rets[_i] if _i < len(_r_rets) else 0.0
            _ann_parts = [f"名单 <b>{_rr:+.1f}%</b>"]
            _detail_row = {
                "候选区间": f"{_sm} → {_em}",
                "月数": len([m for m in _tm_months if _sm <= m <= _em]),
                "名单收益": f"{_rr:+.1f}%",
            }

            for _tid in _tm_tools_sel:
                _tr = (_tool_results[_tid].timed_rets[_i]
                       if _i < len(_tool_results[_tid].timed_rets) else 0.0)
                _tool_cum[_tid] += _tr
                if _tr > 0:
                    _tool_wins[_tid] += 1
                _tl = _TIMING_TOOLS[_tid]["label"]
                _ann_parts.append(f"{_tl} <b>{_tr:+.1f}%</b>")
                _detail_row[f"{_tl} 择时"] = f"{_tr:+.1f}%"

            _mask_seg = (_wk.index >= _sd) & (_wk.index <= _ed)
            _seg = _wk[_mask_seg]
            _ep, _xp = 0.0, 0.0
            if len(_seg) >= 1:
                _ep = float(_seg["Open"].astype(float).iloc[0])
                _xp = float(_seg["Close"].astype(float).iloc[-1])
            _detail_row["入选价"] = f"${_ep:.2f}" if _ep else "—"
            _detail_row["退选价"] = f"${_xp:.2f}" if _xp else "—"
            _detail_rows.append(_detail_row)

            _rc = "#2ECC71" if _rr >= 0 else "#E74C3C"
            _mid = _sd + (_ed - _sd) / 2
            _y_pos = _price_hi * (1.05 if _i % 2 == 0 else 0.97)
            _fig.add_annotation(
                x=_mid, y=_y_pos,
                text=" | ".join(_ann_parts),
                showarrow=False,
                font=dict(size=11, color="#ddd"),
                bgcolor="rgba(0,0,0,0.75)",
                bordercolor=_rc, borderwidth=1, borderpad=3,
                row=1, col=1,
            )

        # ── 各工具买卖信号（分色分形）──
        for _tid in _tm_tools_sel:
            _result = _tool_results[_tid]
            _tclr = _TOOL_COLORS[_tid]
            _tsym = _TOOL_SYMBOLS[_tid]
            _tlab = _TIMING_TOOLS[_tid]["label"]
            _buy_sigs = [s for s in _result.signals if s["type"] == "buy"]
            _sell_sigs = [s for s in _result.signals if s["type"] == "sell"]
            if _buy_sigs:
                _fig.add_trace(go.Scatter(
                    x=[s["date"] for s in _buy_sigs],
                    y=[s["price"] for s in _buy_sigs],
                    mode="markers",
                    marker=dict(symbol=_tsym["buy"], size=12, color=_tclr["buy"],
                                line=dict(color="white", width=1)),
                    name=f"▲ {_tlab} 买入",
                    hovertemplate="%{x|%Y-%m-%d}<br>▲ 买入 $%{y:.2f}<extra></extra>",
                ), row=1, col=1)
            if _sell_sigs:
                _fig.add_trace(go.Scatter(
                    x=[s["date"] for s in _sell_sigs],
                    y=[s["price"] for s in _sell_sigs],
                    mode="markers",
                    marker=dict(symbol=_tsym["sell"], size=12, color=_tclr["sell"],
                                line=dict(color="white", width=1)),
                    name=f"▼ {_tlab} 卖出",
                    hovertemplate="%{x|%Y-%m-%d}<br>▼ 卖出 $%{y:.2f}<extra></extra>",
                ), row=1, col=1)

        # 图表标题：各工具累计收益 + 胜率
        _title_parts = [f"{_tk} ({_cn}) | {_CLS_LBL[_tm_cls]} | {len(_pds)}段候选"]
        for _tid in _tm_tools_sel:
            _wr = (_tool_wins[_tid] / len(_pds) * 100) if _pds else 0
            _title_parts.append(
                f"{_TIMING_TOOLS[_tid]['label']} {_tool_cum[_tid]:+.1f}% 胜率{_wr:.0f}%"
            )

        _fig.update_layout(
            title=dict(text=" · ".join(_title_parts), font=dict(size=14)),
            height=500, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", y=1.08, font=dict(size=11)),
            margin=dict(t=60, l=10, r=10, b=10),
        )
        _fig.update_yaxes(title_text="价格", row=1, col=1)
        _fig.update_yaxes(title_text="成交量", row=2, col=1)

        st.plotly_chart(_fig, use_container_width=True)

        # 持仓明细表（多工具列）
        if _detail_rows:
            with st.expander(f"📋 {_tk} 持仓明细（{len(_pds)}段候选期）", expanded=False):
                st.dataframe(
                    pd.DataFrame(_detail_rows),
                    use_container_width=True, hide_index=True,
                )
else:
    st.info("竞技场历史数据不可用，无法生成择时回顾。请先在 Page 4 运行竞技场。")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════
#  Section 2: VCP 精准猎杀 & TWAP 作战室
# ═══════════════════════════════════════════════════════════════════
st.header("🔬 VCP 精准猎杀 & TWAP 作战室")
st.caption("核心逻辑：Page 4 竞技场推荐标的 ➡️ Minervini VCP 形态解剖 ➡️ TWAP 最优建仓执行")

# ── 目标选择控件 ──
sel_col, manual_col, route_col = st.columns([3, 2, 1])

with sel_col:
    if p4_arena_leaders:
        st.caption("📡 数据来源：Page 4 竞技场 Top 3 × 4 赛道")
    selected_label = st.selectbox("🏆 猎杀目标选择:", options, index=default_idx, label_visibility="visible")

target_ticker = ""
if selected_label == "-- 🔍 手动输入自定义代码 --":
    with manual_col:
        st.caption("输入任意股票代码")
        manual_ticker = st.text_input("🔍 自定义代码 (如 AAPL, 000001.SS):", value="", label_visibility="visible").upper()
    target_ticker = manual_ticker
else:
    target_ticker = label_to_ticker[selected_label]

with route_col:
    if p4_routed:
        st.caption(" ")
        st.info(f"直通: **{p4_routed}**")
        if st.button("✖ 清除", key="clear_p4_route"):
            del st.session_state["p4_champion_ticker"]
            st.rerun()
    elif not p4_arena_leaders:
        st.warning("请先访问 **4 资产强筛** 获取竞技场数据")

st.markdown("---")

with st.expander("📐 VCP 方法论 (Mark Minervini) — 点击展开核心逻辑", expanded=False):
    st.markdown("""
**VCP (Volatility Contraction Pattern)** 是机构级趋势交易的黄金模式，由 Mark Minervini 系统化为四步法：

1. **Stage 2 大前提** — 股票必须处于长期上升趋势（价格 > 150/200日均线，200MA 向上）
2. **价格收缩** — 2-6次回调，每次深度递减（如 -25% → -12% → -4%），浮筹被逐步洗净
3. **量能枯竭** — 最后一波收缩中成交量极度萎缩（< 50日均量的50%），无人愿卖
4. **枢轴突破** — 价格收敛至极致后，放量突破阻力线（枢轴点）= 最佳入场

**TWAP 配合：** 发现 VCP 极致收缩 → 次日若放量突破枢轴 → 激活 TWAP 2-4h 平滑建仓，规避单笔冲击成本。

---

**每一只股票的生命周期都在这四个阶段里轮回：**

📉 **Stage 1（筑底阶段 - 忽视期）：** 股票刚经历了大熊市，在底部半死不活地横盘。均线走平。没人关注。（绝不能买，会浪费时间）

🚀 **Stage 2（上升阶段 - 主升浪）：** 股票放量突破底部，价格站上 150 日和 200 日均线，且 200 日均线拐头向上。机构疯狂建仓。（VCP 唯一的作战区域！）本页通过 4/5 的打分就是在测算这个。

🌋 **Stage 3（做头阶段 - 派发期）：** 股价涨到了极高位，开始剧烈震荡（宽幅大阴大阳），均线走平。这是机构在把筹码卖给最后的接盘侠（散户）。（危险区域，准备逃顶）

💀 **Stage 4（下降阶段 - 崩溃期）：** 价格跌破 200 日均线，均线向下发散。（绝对禁区，做空或空仓）
""")

if target_ticker:
    try:
        with st.spinner(f"正在拉取 {target_ticker} 历史数据 (5年)..."):
            stock = yf.Ticker(target_ticker, session=YF_SESSION)
            hist = stock.history(period="5y")
            try:
                info = stock.info or {}
            except Exception:
                info = {}

        if hist.empty:
            st.warning(f"无法获取 {target_ticker} 的历史数据。")
            st.stop()

        hist = hist.dropna(subset=['Close'])
        if len(hist) < 200:
            st.warning(f"{target_ticker} 历史数据不足 200 个交易日，无法进行 VCP 分析。")
            st.stop()

        curr_price = float(hist['Close'].iloc[-1])
        cn_name = TIC_MAP.get(target_ticker, target_ticker)

        # ── VCP 参数 & K线频率（图表上方控件栏） ──
        ctrl_l, ctrl_r = st.columns([3, 1])
        with ctrl_l:
            lookback_days = st.slider(
                "📐 VCP 回溯天数", 90, 360, 180, step=30,
                help="越长捕获越大级别的 VCP 底部，越短聚焦近期收缩形态",
            )
        with ctrl_r:
            timeframe = st.radio(
                "📡 K线频率",
                ["周线 🛰️ 卫星图", "日线 🔭 狙击镜"],
                horizontal=True,
                help="周线看阵型：过滤日线噪音，确认宏大 Base | 日线扣扳机：精确枢轴突破入场",
            )
            is_weekly = timeframe.startswith("周线")

        ohlcv = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        if ohlcv.index.tz is not None:
            try:
                ohlcv.index = ohlcv.index.tz_localize(None)
            except TypeError:
                ohlcv.index = ohlcv.index.tz_convert(None)

        with st.spinner("🔬 VCP 引擎深度分析中..."):
            vcp = fetch_vcp_analysis(ohlcv, lookback_days)

        if "error" in vcp:
            st.error(f"VCP 分析失败: {vcp['error']}")
            st.stop()

        # ── Header ──
        st.header(f"📊 {target_ticker} ({cn_name})")
        with st.expander("🏢 基本面简述", expanded=False):
            if target_ticker in ASSET_CN_DB:
                st.info(f"**【战略基调】** {ASSET_CN_DB[target_ticker]}")
            else:
                summary = info.get('longBusinessSummary', '暂无描述。')
                st.info(f"**【简介】** {summary[:300]}{'...' if len(summary) > 300 else ''}")

        # ── Dashboard Metrics ──
        grade = vcp["vcp_grade"]
        score = vcp["vcp_score"]
        grade_css = f"grade-{grade.lower()}"

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("当前价格", f"${curr_price:.2f}")
        mc2.markdown("**VCP 评分**")
        mc2.markdown(f"<span class='{grade_css}'>{score:.0f} ({grade}级)</span>", unsafe_allow_html=True)
        s2_label = "✅ Stage 2 确认" if vcp["stage2"]["is_stage2"] else "❌ 非 Stage 2"
        mc3.metric("趋势阶段", s2_label)
        mc4.metric("TWAP 指令", vcp["twap"]["action_label"])

        # ── VCP Chart ──
        if is_weekly:
            hist_w = hist.resample('W-FRI').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min',
                'Close': 'last', 'Volume': 'sum',
            }).dropna()
            hist_chart = hist_w.copy()
            ma_short, ma_mid, ma_long = 10, 30, 40
            ma_labels = ('MA10w', 'MA30w', 'MA40w')
        else:
            chart_bars = min(len(hist), lookback_days + 60)
            hist_chart = hist.iloc[-chart_bars:].copy()
            ma_short, ma_mid, ma_long = 50, 150, 200
            ma_labels = ('MA50', 'MA150', 'MA200')

        if hist_chart.index.tz is not None:
            try:
                hist_chart.index = hist_chart.index.tz_localize(None)
            except TypeError:
                hist_chart.index = hist_chart.index.tz_convert(None)

        tf_tag = "周线 · 卫星图" if is_weekly else "日线 · 狙击镜"
        st.caption(f"📡 当前视图: **{tf_tag}** — 回溯 {len(hist_chart)} 根 K 线")

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.03, row_heights=[0.7, 0.3],
        )

        fig.add_trace(go.Candlestick(
            x=hist_chart.index,
            open=hist_chart['Open'].astype(float),
            high=hist_chart['High'].astype(float),
            low=hist_chart['Low'].astype(float),
            close=hist_chart['Close'].astype(float),
            name="K线",
            increasing_line_color='#2ECC71', decreasing_line_color='#E74C3C',
        ), row=1, col=1)

        ma_s = hist_chart['Close'].astype(float).rolling(ma_short).mean()
        ma_m = hist_chart['Close'].astype(float).rolling(ma_mid).mean()
        ma_l = hist_chart['Close'].astype(float).rolling(ma_long).mean()
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma_s, line=dict(color='#3498DB', width=1), name=ma_labels[0]), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma_m, line=dict(color='#F39C12', width=1), name=ma_labels[1]), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma_l, line=dict(color='#E74C3C', width=1.5), name=ma_labels[2]), row=1, col=1)

        for ci, cw in enumerate(vcp.get("contractions", [])):
            fig.add_shape(
                type="rect",
                x0=cw["peak_date"], x1=cw["trough_date"],
                y0=cw["trough_price"], y1=cw["peak_price"],
                fillcolor=f"rgba(231, 76, 60, {0.08 + ci * 0.04})",
                line=dict(color="rgba(231, 76, 60, 0.4)", width=1),
                row=1, col=1,
            )
            fig.add_annotation(
                x=cw["trough_date"], y=cw["trough_price"],
                text=f"W{cw['wave']}: {cw['depth_pct']:.1f}%",
                showarrow=True, arrowhead=2, arrowcolor="#E74C3C",
                font=dict(size=11, color="#E74C3C"),
                row=1, col=1,
            )

        ext = vcp.get("extrema", [])
        if ext:
            ext_colors = ['#E74C3C' if e['type'] == 'H' else '#2ECC71' for e in ext]
            fig.add_trace(go.Scatter(
                x=[e["date"] for e in ext],
                y=[e["price"] for e in ext],
                mode='lines+markers',
                line=dict(color='rgba(255,255,255,0.4)', width=1, dash='dot'),
                marker=dict(size=7, color=ext_colors),
                name='峰谷极值',
            ), row=1, col=1)

        fig.add_hline(
            y=vcp["pivot"]["price"], line_dash="dash", line_color="cyan",
            annotation_text=f"枢轴点 ${vcp['pivot']['price']:.2f}",
            annotation_position="top left", row=1, col=1,
        )

        twap = vcp["twap"]
        if twap["action"] in ("EXECUTE", "PREPARE"):
            fig.add_hline(y=twap["entry_price"], line_dash="dot", line_color="#2ECC71",
                          annotation_text=f"Entry ${twap['entry_price']:.2f}",
                          annotation_position="bottom right", row=1, col=1)
            fig.add_hline(y=twap["stop_loss"], line_dash="dot", line_color="#E74C3C",
                          annotation_text=f"Stop ${twap['stop_loss']:.2f}",
                          annotation_position="bottom right", row=1, col=1)
            fig.add_hline(y=twap["target_price"], line_dash="dot", line_color="#F1C40F",
                          annotation_text=f"Target ${twap['target_price']:.2f}",
                          annotation_position="top right", row=1, col=1)

        vol_colors = []
        for c_val, o_val in zip(hist_chart['Close'].astype(float), hist_chart['Open'].astype(float)):
            vol_colors.append('#E74C3C' if float(c_val) < float(o_val) else '#2ECC71')
        fig.add_trace(go.Bar(
            x=hist_chart.index, y=hist_chart['Volume'].astype(float),
            marker_color=vol_colors, name='成交量', opacity=0.6,
        ), row=2, col=1)

        vol_ma_period = 10 if is_weekly else 50
        vol_ma = hist_chart['Volume'].astype(float).rolling(vol_ma_period).mean()
        vol_ma_label = '10周均量' if is_weekly else '50日均量'
        fig.add_trace(go.Scatter(
            x=hist_chart.index, y=vol_ma,
            line=dict(color='#F39C12', width=1), name=vol_ma_label,
        ), row=2, col=1)

        fig.update_layout(
            height=650, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", y=1.05, font=dict(size=11)),
            margin=dict(t=40, l=10, r=10, b=10),
        )
        fig.update_yaxes(title_text="价格", row=1, col=1)
        fig.update_yaxes(title_text="成交量", row=2, col=1)

        st.plotly_chart(fig, use_container_width=True)

        # ── Analysis Panels ──
        col_l, col_r = st.columns(2)

        with col_l:
            s2_tag = "通过" if vcp["stage2"]["is_stage2"] else "未通过"
            with st.expander(f"📐 Stage 2 趋势检查（{s2_tag} {vcp['stage2']['score']}/5）", expanded=True):
                for line in vcp["stage2"]["details"]:
                    st.markdown(f"- {line}")
                if not vcp["stage2"]["is_stage2"]:
                    st.warning("⚠️ VCP 的大前提——Stage 2 上升趋势——尚未满足。即使出现收缩形态，成功率大打折扣。")

            with st.expander("📊 量能枯竭分析", expanded=True):
                vc1, vc2 = st.columns(2)
                vc1.metric("近5日均量", f"{vcp['volume']['recent_5d_vol']:,.0f}")
                delta_color = "inverse" if vcp["volume"]["is_dry"] else "normal"
                vc2.metric("50日均量", f"{vcp['volume']['vol_50d_avg']:,.0f}",
                           delta=f"{vcp['volume']['vol_ratio'] * 100:.0f}% 比率", delta_color=delta_color)
                for line in vcp["volume"]["details"]:
                    st.markdown(f"- {line}")

        with col_r:
            with st.expander(f"🌊 收缩波解剖（{vcp['n_contractions']}浪）", expanded=True):
                if vcp["contractions"]:
                    st.markdown(f"**收缩路径:** {vcp['contraction_summary']}")
                    c_rows = []
                    for cw in vcp["contractions"]:
                        c_rows.append({
                            "波段": f"Wave {cw['wave']}",
                            "峰值": f"${cw['peak_price']:.2f}",
                            "谷底": f"${cw['trough_price']:.2f}",
                            "深度": f"{cw['depth_pct']:.1f}%",
                            "均量": f"{cw['avg_volume']:,.0f}",
                        })
                    st.dataframe(pd.DataFrame(c_rows), use_container_width=True, hide_index=True)
                else:
                    st.warning("未检测到明确的 VCP 收缩波形。该标的可能不在 VCP 形态中。")

            with st.expander("🎯 枢轴点分析", expanded=True):
                st.metric("枢轴点价格", f"${vcp['pivot']['price']:.2f}",
                          delta=f"近10日波幅 {vcp['pivot']['last_10d_range_pct']:.1f}%")
                for line in vcp["pivot"]["details"]:
                    st.markdown(f"- {line}")

        # ── TWAP Command Center ──
        st.markdown("---")
        st.subheader("🏛️ TWAP 作战指挥中心")

        action = twap["action"]
        if action == "EXECUTE":
            st.success(f"**{twap['action_label']}** — 所有条件已满足！")
        elif action == "PREPARE":
            st.info(f"**{twap['action_label']}** — VCP 形态就绪，等待枢轴点突破触发。")
        elif action == "MONITOR":
            st.warning(f"**{twap['action_label']}** — 形态尚在发育，暂不宜入场。")
        else:
            st.error(f"**{twap['action_label']}** — 不具备 VCP 条件，建议观望。")

        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("🎯 入场价", f"${twap['entry_price']:.2f}")
        tc2.metric("🛡️ 止损价", f"${twap['stop_loss']:.2f}",
                   delta=f"-{twap['risk_pct']:.1f}%", delta_color="inverse")
        tc3.metric("🎪 目标价", f"${twap['target_price']:.2f}")
        rr_tag = "优秀" if twap["rr_ratio"] >= 3 else ("可行" if twap["rr_ratio"] >= 2 else "偏低")
        tc4.metric("📐 盈亏比 R:R", f"{twap['rr_ratio']:.1f}", delta=rr_tag)

        if twap.get("trigger_conditions"):
            st.markdown("**🔔 激活触发条件:**")
            for cond in twap["trigger_conditions"]:
                st.markdown(f"- {cond}")

        st.markdown(f"""
        <div class='twap-box'>
        <b>⚙️ TWAP 执行建议:</b><br><br>
        • 建仓窗口: <b>{twap['twap_window_hours']} 小时</b>（时间加权均匀分割）<br>
        • 风险敞口: <b>{twap['risk_pct']:.1f}%</b>（入场至止损距离）<br>
        • 盈亏比: <b>{twap['rr_ratio']:.1f} : 1</b><br><br>
        {twap['details']}
        </div>
        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"分析模块遭遇异常中止: {e}")
        import traceback
        st.code(traceback.format_exc())
