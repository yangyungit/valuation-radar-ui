import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from api_client import (
    fetch_sp500_pit_relay_timeseries,
    fetch_ndx100_pit_relay_timeseries,
    fetch_gbdt_oos_prices,
    fetch_macro_radar_timeseries,
    get_global_data,
    fetch_current_regime,
    compute_macro_regime_api,
)
from buyback_relay_core import render_group
import holdings_viz as hv

st.set_page_config(page_title="标普500+纳指100 PIT 接力", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("📊 标普500 + 纳指100 合并池 PIT 接力图")
st.caption(
    "**池子**:S&P500 ∪ NASDAQ-100 每月真实历史成分并集（含退市，2016 起）,每月只在合并成分内横截面排名。"
    "**排名**:按 **raw 10M 绝对涨幅**（月末价/10 个月前月末价 − 1）横截面排名。"
    "**🥇 金牌 = 当月 Top1 / 🥈 银牌 = Top2**（已删 RS 门槛，只看排名）。"
    "**净值口径**:日线、执行月首个交易日 Open 买入、持有到月末 Close、扣单边 10bps；"
    "满仓单票、进场按 Top2 判定：新进场须当月 Top2 且最近 6 月内 ≥2 次进 Top2(滤掉闪现一月的生面孔)，"
    "多票并列时优先连续在榜月数最长的(更连贯新鲜)、打平看当月排名，"
    "**留任按趋势**:在任票只要月末价 > 自己的 4 月均线(≈MA80 日线)就一直拿、不管别人排第几，跌破均线才换，"
    "空仓现金年化 4%。"
)

# ============================================================
# 危险区域时间条带 (Danger Zone Ribbon) —— 与「宏观雷达」页同源
# 红 = GBDT 日频卖出信号后 20 交易日 → 清仓（月中触发即空仓，不等月末）
# 橙 = 旧闸门 chaos_share>0.40 月 → 减仓一半；重叠时 GBDT 清仓优先
# ============================================================
with st.spinner("📊 加载危险区域条带..."):
    df_prices       = get_global_data(["SPY"], years=10)
    _current_regime = fetch_current_regime()
    _chain_regime   = compute_macro_regime_api(z_window=750)

_DANGER_FWD_DAYS = 20  # GBDT 碎信号向后延伸的交易日数

_danger_full = None  # GBDT → 清仓
_danger_half = None  # 旧闸门 → 减仓一半
try:
    if df_prices is not None and not df_prices.empty:
        _cal = pd.DatetimeIndex(df_prices.index).sort_values()
        _danger_full = pd.Series(False, index=_cal)
        _danger_half = pd.Series(False, index=_cal)

        # (1) GBDT 每个触发日 + 后 N 个交易日 → 清仓（纯日频，月中触发即空仓，不依赖月末）
        _dz_trig_raw = (_chain_regime or {}).get("horsemen_daily_chaos_trigger", {}) or {}
        _dz_trig_dates = pd.to_datetime(
            [k for k, v in _dz_trig_raw.items() if v], errors="coerce"
        ).dropna()
        for _td in _dz_trig_dates:
            _pos = int(_cal.searchsorted(_td))
            if _pos < len(_cal):
                _danger_full.iloc[_pos:_pos + _DANGER_FWD_DAYS + 1] = True

        # (2) 旧闸门 chaos_share>0.40 月 → 减仓一半（月频概念，保留月频）
        # 优先取 compute 自带的月频 probs（120 月满档）；持久化 current-regime 那份常年空，仅作兜底
        _dz_hmp = (
            ((_chain_regime or {}).get("data", {}) or {}).get("horsemen_monthly_probs", {})
            or (_current_regime or {}).get("horsemen_monthly_probs", {})
            or {}
        )
        _dz_recs = []
        for _m_str, _probs in _dz_hmp.items():
            if not isinstance(_probs, dict):
                continue
            try:
                _m_ts = pd.Timestamp(str(_m_str) + "-01")
            except Exception:
                continue
            _dz_recs.append((
                _m_ts,
                float(_probs.get("chaos_share", 0.0) or 0.0) > 0.40,
            ))
        if _dz_recs:
            _dz_mdf = (
                pd.DataFrame(_dz_recs, columns=["date", "old_gate"])
                .set_index("date").sort_index()
            )
            _danger_half = (
                _dz_mdf["old_gate"].reindex(_cal, method="ffill").fillna(False).astype(bool)
            )
        _danger_half = _danger_half & ~_danger_full
except Exception:
    _danger_full = None
    _danger_half = None

if _danger_full is not None and bool((_danger_full | _danger_half).any()):
    st.markdown(
        "#### ⚠️ 危险区域条带 "
        "<span style='font-size:13px; color:#888; font-weight:normal;'>"
        "(红 = GBDT 清仓：卖出信号后 20 交易日；橙 = 旧闸门 chaos_share&gt;0.40 月，减仓一半)</span>",
        unsafe_allow_html=True,
    )

    def _bool_segs(s: pd.Series) -> list:
        _flip = s.ne(s.shift()).cumsum()
        return [
            (_grp.index[0], _grp.index[-1])
            for _gid, _grp in s.groupby(_flip)
            if bool(_grp.iloc[0])
        ]

    # 条带占上半部(y 0.42~1)，下半部留给逐段日期标注
    _BAND_Y0 = 0.42
    _rib = go.Figure()
    _rib.add_shape(
        type="rect", xref="x", yref="paper",
        x0=_cal[0], x1=_cal[-1], y0=_BAND_Y0, y1=1,
        fillcolor="rgba(46,204,113,0.10)", line_width=0, layer="below",
    )
    for _seg_list, _fill, _txt_color in [
        (_bool_segs(_danger_half), "rgba(230,126,34,0.55)", "#E67E22"),
        (_bool_segs(_danger_full), "rgba(231,76,60,0.55)", "#E67E73"),
    ]:
        for _s0, _s1 in _seg_list:
            _rib.add_shape(
                type="rect", xref="x", yref="paper",
                x0=_s0, x1=_s1, y0=_BAND_Y0, y1=1,
                fillcolor=_fill, line_width=0, layer="below",
            )
            # 每段起止日期标注（条带下方，小字倾斜；起点左对齐、终点右对齐）
            _rib.add_annotation(
                x=_s0, y=_BAND_Y0 - 0.06, xref="x", yref="paper",
                text=_s0.strftime("%y/%m/%d"),
                showarrow=False, textangle=45,
                xanchor="right", yanchor="top",
                font=dict(size=9, color=_txt_color),
            )
            _rib.add_annotation(
                x=_s1, y=_BAND_Y0 - 0.06, xref="x", yref="paper",
                text=_s1.strftime("%y/%m/%d"),
                showarrow=False, textangle=45,
                xanchor="left", yanchor="top",
                font=dict(size=9, color=_txt_color),
            )
    # 透明散点：撑起 x 轴日期范围（shape 本身不建立坐标）
    _rib.add_trace(go.Scatter(
        x=[_cal[0], _cal[-1]], y=[0.5, 0.5], mode="markers",
        marker=dict(opacity=0), showlegend=False, hoverinfo="skip",
    ))
    _rib.update_layout(
        height=130,
        margin=dict(l=20, r=20, t=10, b=28),
        plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
        font=dict(color="#ddd"),
        showlegend=False,
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.06)",
            range=[_cal[0], _cal[-1]],
            tickformat="%Y", dtick="M12",
            showticklabels=True, ticks="outside",
            tickfont=dict(size=11, color="#999"),
        ),
        yaxis=dict(visible=False, range=[0, 1]),
    )
    st.plotly_chart(_rib, use_container_width=True, key="tl_danger_ribbon")

    if bool(_danger_full.iloc[-1]):
        _dz_status_txt = "<span style='color:#E74C3C; font-weight:bold;'>清仓区（GBDT）</span>"
    elif bool(_danger_half.iloc[-1]):
        _dz_status_txt = "<span style='color:#E67E22; font-weight:bold;'>减仓区（旧闸门）</span>"
    else:
        _dz_status_txt = "<span style='color:#2ECC71; font-weight:bold;'>安全</span>"
    _dz_full_1y = int(_danger_full.iloc[-252:].sum())
    _dz_half_1y = int(_danger_half.iloc[-252:].sum())
    st.caption(
        f"当前：{_dz_status_txt} · 近一年 红(清仓) {_dz_full_1y} 天 / 橙(减半) {_dz_half_1y} 天 / "
        f"共 {min(len(_danger_full), 252)} 天 · 绿=安全",
        unsafe_allow_html=True,
    )
    st.markdown("---")

with st.sidebar:
    if st.button("🔄 强制刷新合并池接力数据"):
        fetch_sp500_pit_relay_timeseries.clear()
        fetch_ndx100_pit_relay_timeseries.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

_WINDOWS = ["3Y", "5Y", "10Y"]
window = st.radio("时间跨度", _WINDOWS, index=2, horizontal=True, key="tl_window")

# ── 顶部对照：板块王朝接力左右列甘特条带（与「板块王朝」页 king_score 接力同源）
# 用途：把「最火板块」的时间轴摆在科技龙头之上，肉眼核对当月选出的龙头股是否落在同期最热板块里。
_DYN_GROUPS = ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"]
with st.spinner("📊 加载板块王朝接力条带..."):
    _dyn_ts = fetch_macro_radar_timeseries(window=window, profile="dynasty")
if not _dyn_ts.get("success"):
    st.info(f"板块王朝条带暂不可用：{_dyn_ts.get('error', '未知错误')}")
else:
    _dyn_slots, _dyn_name_map, _dyn_exec_months = hv.dynasty_relay_slots(
        _dyn_ts, groups=_DYN_GROUPS, buffer_n=4,
    )
    if _dyn_slots:
        st.markdown("### 🔥 板块王朝接力（最火板块时间条带）")
        st.caption(
            "两条轨道 = 王朝接力左列（龙头板块）/ 右列（次龙头板块），每段色带 = 一段连续持有的板块，"
            f"带上标中文名 + ETF 代码。与「板块王朝」页 {window} king_score 接力同源。"
            "对照下方选出的科技龙头个股：看当月龙头是否正好落在同期最热板块里（互相命中）。"
        )
        st.plotly_chart(
            hv.build_relay_gantt(
                _dyn_slots, _dyn_exec_months, _dyn_name_map,
                title=f"{window} 王朝接力左右列 · 板块时间条带",
            ),
            use_container_width=True,
            key="tl_dynasty_gantt",
        )
        st.markdown("---")


def _merge_relay_ts(a: dict, b: dict) -> dict:
    """把标普500 与纳指100 两套 PIT 接力时序 union 成合并池。以 a(标普500) 为底表。
    - tickers(含 rs 等)、dates 两池同轴，直接 dict 合并（重叠票以 a 为准）。
    - close_me 两池月末日期轴可能不同(build 时点不同)，各带自己 close_me_dates 对齐后 combine_first。
    - membership 按月取并集。
    排名仍是 raw 10M 绝对涨幅在合并池内横截面 rank，口径不变。
    """
    out = dict(a)
    out["tickers"] = {**b.get("tickers", {}), **a.get("tickers", {})}

    ai = pd.to_datetime(a.get("close_me_dates", []) or [], errors="coerce")
    bi = pd.to_datetime(b.get("close_me_dates", []) or [], errors="coerce")
    da = pd.DataFrame(a.get("close_me", {}) or {}, index=ai).astype(float)
    db = pd.DataFrame(b.get("close_me", {}) or {}, index=bi).astype(float)
    cme = da.combine_first(db).sort_index() if not db.empty else da.sort_index()
    out["close_me_dates"] = [d.strftime("%Y-%m-%d") for d in cme.index]
    out["close_me"] = {c: cme[c].where(pd.notna(cme[c]), None).tolist() for c in cme.columns}

    memb_a = a.get("sp500_membership", {}) or {}
    memb_b = b.get("ndx100_membership", {}) or {}
    merged = {}
    for ym in set(memb_a) | set(memb_b):
        merged[ym] = sorted(set(memb_a.get(ym, [])) | set(memb_b.get(ym, [])))
    out["pool_membership"] = merged
    return out


with st.spinner("📊 加载标普500 + 纳指100 合并池接力数据..."):
    ts_sp = fetch_sp500_pit_relay_timeseries(window)
    ts_ndx = fetch_ndx100_pit_relay_timeseries(window)

if not ts_sp.get("success"):
    st.error(f"⚠️ 标普500 PIT 接力数据暂不可用:{ts_sp.get('error', '未知错误')}")
    st.stop()
if not ts_ndx.get("success"):
    st.warning(f"⚠️ 纳指100 数据暂不可用（回退纯标普500）:{ts_ndx.get('error', '未知错误')}")
    ts = dict(ts_sp)
    ts["pool_membership"] = ts_sp.get("sp500_membership", {}) or {}
else:
    ts = _merge_relay_ts(ts_sp, ts_ndx)

_all_tickers = ts.get("tickers", {}) or {}
_tickers = _all_tickers
_dates = ts.get("dates", []) or []
if not _tickers or not _dates:
    st.warning("⚠️ 标普500 PIT 母体数据为空")
    st.stop()
st.caption(f"股池：S&P500 ∪ NASDAQ-100 PIT 历史成分并集，当前后端命中 {len(_tickers)} 只。")

_idx = pd.to_datetime(_dates, errors="coerce")
rs = pd.DataFrame({tk: p.get("rs", []) for tk, p in _tickers.items()}, index=_idx).astype(float)
name_map = {tk: p.get("name", tk) for tk, p in _tickers.items()}
grade_map = {tk: p.get("group", "") for tk, p in _tickers.items()}
asof = pd.to_datetime(ts.get("asof"), errors="coerce")
rs_m = rs.resample("ME").last()

# 排名/热力图用 10M 动量，月末收盘直接取后端面板 close_me（全历史、免拉 750 只日线）。
# 回看窗口 L 稳健性扫描（离线跑 L=6..15 三段 Calmar）：甜区 9-12M，≤8M 追一月脉冲、
# ≥13M 太滞后都变差；10M 落在平台正中，离两侧悬崖各一步，比原 12M 抗甜区漂移。
# close_me 走全历史（后端不随 window 裁），保证 shift(10) 回看和 δ 稳健性切尾部 10Y。
_cme_idx = pd.to_datetime(ts.get("close_me_dates", []) or [], errors="coerce")
_close_me = pd.DataFrame(ts.get("close_me", {}) or {}, index=_cme_idx).astype(float)
if _close_me.empty or len(_close_me) < 11:
    st.warning("⚠️ 后端 close_me 面板为空（需先跑 build_sp500_pit_relay_panel 并上传）")
    st.stop()
king_m = (_close_me / _close_me.shift(10) - 1.0)

# 趋势留任掩码：在任票月末价 > 自己 4 月均线才留（≈ MA80 日线）。全历史算，
# 保证 MA4 在展示窗口起点就有效；render_group 里按在任票逐月查此表决定守不守。
# MA4 = 尾部 3Y/5Y 总收益全面压过原 MA10（2-3 倍），10Y 打平；卖得更快、早期动量段吃得更满。
_ret_mask = _close_me > _close_me.rolling(4).mean()

_memb = ts.get("pool_membership", {}) or {}


def _mask_by_membership(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for dt in out.index:
        ym = dt.strftime("%Y-%m")
        allowed = set(_memb.get(ym, []))
        if allowed:
            out.loc[dt, [c for c in out.columns if c not in allowed]] = float("nan")
    return out


king_m = _mask_by_membership(king_m)

# close_me 是全历史；king_m_long 保留全历史供 δ 稳健性扫描切尾部 3/5/10Y，
# 展示用 king_m 按选中跨度裁剪，否则选 5Y 也画 10Y。
king_m_long = king_m
_WIN_YEARS = {"3Y": 3, "5Y": 5, "10Y": 10}
_win_start = king_m.index[-1] - pd.DateOffset(years=_WIN_YEARS.get(window, 10))
king_m = king_m[king_m.index >= _win_start]
if king_m.empty or len(king_m) < 2:
    st.warning("⚠️ 选中窗口内月末快照数据不足")
    st.stop()

# 净值只需历史上进过 Top2 的票的日线，免拉全池 750 只（曾达 111MB，
# 在 Streamlit Cloud 免费档上悄悄失败 → 回退 5 年 yfinance，导致选 10Y 也只有 5 年）。
_rank_long = king_m_long.rank(axis=1, ascending=False, method="min")
_shortlist = [c for c in king_m_long.columns if bool((_rank_long[c] <= 2).any())]
price_cache_daily: dict = {}
price_cache: dict = {}
spy_daily = pd.DataFrame()
spy_wk = pd.DataFrame()
with st.spinner("📊 加载持仓票日线价格..."):
    try:
        hv.prime_sharadar_prices(fetch_gbdt_oos_prices(tuple(sorted(set(_shortlist) | {"SPY"}))))
    except Exception:
        pass
    spy_daily = hv.fetch_daily_ohlcv("SPY")
    spy_wk = hv.daily_to_weekly(spy_daily)
    for _tk in _shortlist:
        try:
            _d = hv.fetch_daily_ohlcv(_tk)
            if not _d.empty:
                price_cache_daily[_tk] = _d
                price_cache[_tk] = hv.daily_to_weekly(_d)
        except Exception:
            pass

if not price_cache_daily:
    st.warning("⚠️ 持仓票价格数据为空")
    st.stop()

_last_month = king_m.index[-1]
_month_in_progress = bool(pd.notna(asof) and _last_month.to_period("M").end_time.normalize() > asof.normalize())

_COMMON = dict(
    rs_m=rs_m, king_m=king_m, name_map=name_map, grade_map=grade_map,
    window=window, month_in_progress=_month_in_progress, last_month=_last_month,
    price_cache=price_cache, spy_wk=spy_wk,
)


_cols = list(king_m.columns)
_label = "标普500+纳指100"
st.markdown(f"## 🏆 标普500 + 纳指100 合并池（{len(_cols)} 只）")

render_group(_label, _cols, "tl_main",
             score_m=king_m, sweep_score_m=king_m_long,
             score_label="10M动量", score_fmt="{:+.1%}",
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
             segment_window_slider=True,
             retention_mask=_ret_mask,
             retention_price_m=_close_me,
             retention_ma_window=4,
             danger_daily=_danger_full,
             danger_half_daily=_danger_half,
             bear_default=True,
             **_COMMON)
