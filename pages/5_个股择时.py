import os
import json
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from api_client import fetch_core_data, fetch_vcp_analysis

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

# ── Sidebar ──
with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        fetch_vcp_analysis.clear()
        st.success("当前页缓存已清除！")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.success("所有页面缓存已清除！")
        st.rerun()

# ── VCP 目标选择逻辑（数据预处理，不渲染 UI）──
p4_arena_leaders = st.session_state.get("p4_arena_leaders", {})
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

# ── Load Arena History Data ──
_ARENA_HIST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")
_arena_data: dict = {}
try:
    if os.path.exists(_ARENA_HIST_PATH):
        with open(_ARENA_HIST_PATH, "r", encoding="utf-8") as _af:
            _arena_data = json.load(_af)
except Exception:
    pass

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
    h = yf.Ticker(ticker).history(period="5y")
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


if _arena_data:
    # ── 惰性换手持仓推算（宁缺毋滥版） ──
    # A/B 赛道使用 conviction 门槛 + 空位回补 + 消极退出；其余赛道保持原逻辑
    _A_MIN_CONV = 40   # A 组入选 / 回补最低信念
    _A_FLOOR_CONV = 40  # A 组持仓中消极退出地板
    _B_MIN_CONV = 40   # B 组入选 / 回补最低信念
    _B_FLOOR_CONV = 40  # B 组持仓中消极退出地板

    _tm_months = sorted(k for k in _arena_data if not k.startswith("_"))
    _tm_hold: dict = {}
    _score_anomalies: list = []

    for _c in ["A", "B", "C", "D"]:
        _prev_h: set = set()
        _cm: dict = {}
        for _m in _tm_months:
            _recs = _arena_data[_m].get(_c, [])
            _t3 = {r["ticker"] for r in _recs[:3]}

            if _c in ("A", "B"):
                _min_conv = _A_MIN_CONV if _c == "A" else _B_MIN_CONV
                _floor_conv = _A_FLOOR_CONV if _c == "A" else _B_FLOOR_CONV
                _conv_map = {r["ticker"]: r.get("conviction", 0) for r in _recs}
                _score_map = {r["ticker"]: r.get("score", 0) for r in _recs}

                if _c == "B":
                    for _r in _recs[:3]:
                        if _r.get("score", 999) == 0 or _r.get("score") is None:
                            _score_anomalies.append({
                                "month": _m, "ticker": _r["ticker"],
                                "name": _r.get("name", _r["ticker"]),
                                "rank": _recs.index(_r) + 1,
                                "conviction": _r.get("conviction", "—"),
                            })

                _surviving = {tk for tk in _prev_h
                              if tk in _t3
                              and _conv_map.get(tk, 0) >= _floor_conv}
                _hold: set = _surviving.copy()
                for _r in _recs[:3]:
                    if len(_hold) >= 2:
                        break
                    _tk = _r["ticker"]
                    if (_tk not in _hold
                            and _conv_map.get(_tk, 0) >= _min_conv
                            and _score_map.get(_tk, 0) > 0):
                        _hold.add(_tk)
            else:
                _t2 = {r["ticker"] for r in _recs[:2]}
                _hold = _prev_h if (_prev_h and _prev_h.issubset(_t3)) else _t2

            _cm[_m] = _hold
            _prev_h = _hold
        _tm_hold[_c] = _cm

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

    _name_map: dict = {}
    for _m in _tm_months:
        for _c_nm in ["A", "B", "C", "D"]:
            for _rec in _arena_data[_m].get(_c_nm, []):
                _name_map[_rec["ticker"]] = _rec.get("name", _rec["ticker"])

    _seen_tickers: set = set()
    for _c_nm in _pf_classes:
        _seen_tickers.update(tk for hset in _tm_hold[_c_nm].values() for tk in hset)

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
            _all_c_tickers = sorted({tk for hset in _tm_hold[_c_nm].values() for tk in hset})
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
            height=min(400, 35 * len(_profit_df) + 38),
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
    # ── 择时风控逻辑白盒 ──
    with st.expander("📐 择时风控逻辑白盒 — 点击展开", expanded=False):
        st.markdown("""
<div class='timing-box'>
<b style='font-size:15px; color:#2ECC71;'>核心原则：细筛选人，择时决定上/下场</b><br><br>
<b>📊 图表解读</b><br>
&nbsp;&nbsp;• <b style='color:#2ECC71;'>🟩 绿色半透明区域</b> = 标的在竞技场候选名单中（细筛入选，月度更新）<br>
&nbsp;&nbsp;• <b style='color:#2ECC71;'>▲ 绿色三角</b> = 择时买入（A/B: MA12w 金叉 MA60w | C/D: 价格站上生命线）<br>
&nbsp;&nbsp;• <b style='color:#E74C3C;'>▼ 红色三角</b> = 择时卖出（A/B: MA12w 死叉 MA60w | C/D: 价格跌破生命线 | 退出名单强制平仓）<br>
&nbsp;&nbsp;• <b style='color:#E74C3C;'>━ 红色虚线</b> = 快线 MA（A/B: MA12w | C: MA8w | D: MA4w）<br>
&nbsp;&nbsp;• <b style='color:#F39C12;'>━ 橙色虚线</b> = 慢线 MA60w（仅 A/B 组，用于金叉 / 死叉判定）<br><br>
<b>🔄 两层决策分离</b><br>
&nbsp;&nbsp;① <b>细筛层（慢）</b>：月度 Arena 排名 → 决定「谁有资格进组合」→ 对应绿色区域<br>
&nbsp;&nbsp;② <b>择时层（快）</b>：周度 MA 信号 → 决定「此刻该持有还是暂泊」→ 对应箭头信号<br>
&nbsp;&nbsp;在名单 ≠ 在持仓，择时信号决定实际上/下车，退出名单时自动平仓。<br><br>
<b>📏 各级别生命线标准</b><br>
&nbsp;&nbsp;• <b>A/B 组</b>（长持型）：MA12w / MA60w 金叉死叉 ≈ 日线 MA60 / MA300 交叉，最大幅减少 whipsaw<br>
&nbsp;&nbsp;• <b>C 组</b>（趋势型）：8 周 MA ≈ 日线 MA40，中等灵敏<br>
&nbsp;&nbsp;• <b>D 组</b>（短线型）：4 周 MA ≈ 日线 MA20，快速反应
</div>
""", unsafe_allow_html=True)

    # ── 用户控件 ──
    _cc1, _cc2 = st.columns([1, 3])
    with _cc1:
        _tm_cls = st.selectbox(
            "选择赛道", ["A", "B", "C", "D"],
            format_func=lambda x: _CLS_LBL[x], key="tm_cls",
        )
    _all_tk = sorted({tk for hset in _tm_hold[_tm_cls].values() for tk in hset})
    with _cc2:
        _tm_sel = st.multiselect(
            "选择标的（可多选）", _all_tk,
            default=_all_tk[:2] if len(_all_tk) >= 2 else _all_tk,
            key="tm_sel",
        )

    def _compute_timing(wk_df: pd.DataFrame, roster_periods: list,
                        ma_weeks: int = 12, slow_ma_weeks: int = None) -> tuple:
        """MA 择时：返回 (signals, benched_zones, timed_rets, raw_rets, fast_ma, slow_ma)。
        当 slow_ma_weeks 不为 None 时使用快慢 MA 金叉/死叉（A/B 组），
        否则使用价格 vs MA 突破逻辑（C/D 组）。
        退出候选名单时若仍持仓则强制卖出。
        """
        close = wk_df["Close"].astype(float)
        fast_ma = close.rolling(ma_weeks, min_periods=ma_weeks).mean()
        use_cross = slow_ma_weeks is not None
        slow_ma = close.rolling(slow_ma_weeks, min_periods=slow_ma_weeks).mean() if use_cross else None

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
                in_pos = False
            if bench_start is not None and not seg_c.empty:
                benched_zones.append((bench_start, seg_c.index[-1]))

            timed_rets.append((cum - 1) * 100)

        return signals, benched_zones, timed_rets, raw_rets, fast_ma, slow_ma

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

        _sigs, _bench_zones, _t_rets, _r_rets, _fast_ma, _slow_ma = _compute_timing(
            _wk, _pds, ma_weeks=_ma_w, slow_ma_weeks=_slow_ma_w,
        )

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

        # MA 生命线
        _fast_valid = _fast_ma.dropna()
        if not _fast_valid.empty:
            _ma_label = f"MA{_ma_w}w" + (" 快线" if _slow_ma is not None else " 生命线")
            _fig.add_trace(go.Scatter(
                x=_fast_valid.index, y=_fast_valid.astype(float),
                line=dict(color="#E74C3C", width=1.5, dash="dash"),
                name=_ma_label,
            ), row=1, col=1)
        if _slow_ma is not None:
            _slow_valid = _slow_ma.dropna()
            if not _slow_valid.empty:
                _fig.add_trace(go.Scatter(
                    x=_slow_valid.index, y=_slow_valid.astype(float),
                    line=dict(color="#F39C12", width=1.5, dash="dash"),
                    name=f"MA{_slow_ma_w}w 慢线",
                ), row=1, col=1)

        # 灰色成交量
        _fig.add_trace(go.Bar(
            x=_wk.index, y=_wk["Volume"].astype(float),
            marker_color="#444", name="成交量", opacity=0.4,
        ), row=2, col=1)

        # ── 绿色候选区域 + 收益标注 ──
        _cum_raw, _cum_timed = 0.0, 0.0
        _wins_raw, _wins_timed = 0, 0
        _detail_rows: list = []
        _price_hi = float(_wk["High"].astype(float).max())

        for _i, (_sm, _em) in enumerate(_pds):
            _sd = pd.Timestamp(f"{_sm}-01")
            _ed = pd.Timestamp(f"{_em}-01") + pd.offsets.MonthEnd(1)

            # 绿色候选名单区域（统一绿色 = 细筛入选）
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
            _tr = _t_rets[_i] if _i < len(_t_rets) else 0.0
            _cum_raw += _rr
            _cum_timed += _tr
            if _rr > 0:
                _wins_raw += 1
            if _tr > 0:
                _wins_timed += 1

            _mask_seg = (_wk.index >= _sd) & (_wk.index <= _ed)
            _seg = _wk[_mask_seg]
            _ep, _xp = 0.0, 0.0
            if len(_seg) >= 1:
                _ep = float(_seg["Open"].astype(float).iloc[0])
                _xp = float(_seg["Close"].astype(float).iloc[-1])

            _n_months = len([m for m in _tm_months if _sm <= m <= _em])
            _n_trades = len([s for s in _sigs if _sd <= s["date"] <= _ed])
            _detail_rows.append({
                "候选区间": f"{_sm} → {_em}",
                "月数": _n_months,
                "入选价": f"${_ep:.2f}" if _ep else "—",
                "退选价": f"${_xp:.2f}" if _xp else "—",
                "名单收益": f"{_rr:+.1f}%",
                "择时收益": f"{_tr:+.1f}%",
                "择时交易": f"{_n_trades} 笔",
            })

            # 收益率标注：名单收益 → 择时收益
            _rc = "#2ECC71" if _rr >= 0 else "#E74C3C"
            _mid = _sd + (_ed - _sd) / 2
            _y_pos = _price_hi * (1.05 if _i % 2 == 0 else 0.97)
            _fig.add_annotation(
                x=_mid, y=_y_pos,
                text=f"名单 <b>{_rr:+.1f}%</b> → 择时 <b>{_tr:+.1f}%</b>",
                showarrow=False,
                font=dict(size=11, color="#ddd"),
                bgcolor="rgba(0,0,0,0.75)",
                bordercolor=_rc, borderwidth=1, borderpad=3,
                row=1, col=1,
            )

        # ── 择时买卖箭头 ──
        _buy_sigs = [s for s in _sigs if s["type"] == "buy"]
        _sell_sigs = [s for s in _sigs if s["type"] == "sell"]
        if _buy_sigs:
            _fig.add_trace(go.Scatter(
                x=[s["date"] for s in _buy_sigs],
                y=[s["price"] for s in _buy_sigs],
                mode="markers",
                marker=dict(symbol="triangle-up", size=12, color="#2ECC71",
                            line=dict(color="white", width=1)),
                name="▲ 买入/回场",
                hovertemplate="%{x|%Y-%m-%d}<br>▲ 买入 $%{y:.2f}<extra></extra>",
            ), row=1, col=1)
        if _sell_sigs:
            _fig.add_trace(go.Scatter(
                x=[s["date"] for s in _sell_sigs],
                y=[s["price"] for s in _sell_sigs],
                mode="markers",
                marker=dict(symbol="triangle-down", size=12, color="#E74C3C",
                            line=dict(color="white", width=1)),
                name="▼ 暂泊/下场",
                hovertemplate="%{x|%Y-%m-%d}<br>▼ 暂泊 $%{y:.2f}<extra></extra>",
            ), row=1, col=1)

        _wr_raw = (_wins_raw / len(_pds) * 100) if _pds else 0
        _wr_timed = (_wins_timed / len(_pds) * 100) if _pds else 0
        _fig.update_layout(
            title=dict(
                text=(
                    f"{_tk} ({_cn}) | {_CLS_LBL[_tm_cls]} | "
                    f"{len(_pds)}段候选 · 名单{_cum_raw:+.1f}% · "
                    f"择时{_cum_timed:+.1f}% · 胜率{_wr_timed:.0f}%"
                ),
                font=dict(size=14),
            ),
            height=500, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", y=1.08, font=dict(size=11)),
            margin=dict(t=60, l=10, r=10, b=10),
        )
        _fig.update_yaxes(title_text="价格", row=1, col=1)
        _fig.update_yaxes(title_text="成交量", row=2, col=1)

        st.plotly_chart(_fig, use_container_width=True)

        # 持仓明细表
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
            stock = yf.Ticker(target_ticker)
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
