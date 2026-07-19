import streamlit as st
import pandas as pd
import numpy as np

import holdings_viz as hv
from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="斜率进攻", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ 斜率进攻（带鱼池 × 当前段斜率 Top2 × 通道斩仓）")
st.caption(
    "**池子**：与 FCF收益率稳定页同一个带鱼池（年度 PIT，市值≥$30B / TTM FCF>0 / 5Y CAGR≥8% "
    "且 maxDD≥-45% / 带方向 logR² 前40），只看**非科技子集**，池子零改动。"
    "**排名轴 = 当前段年化斜率**：月末在 52~260 周里找最长的仍达标（logR²≥0.70 且年化斜率≥8%）"
    "后缀窗当「当前段」，段斜率越陡排名越前；无达标段 = 无资格。**🥇 金牌 = 斜率 Top1 / 🥈 银牌 = Top2**。"
    "**组合 = 斜率 Top2 月调 + 通道斩仓**：月末收盘**连续 2 个月** ≤ MA6×(1−0.25σ) 才斩仓、换现金，"
    "名额不顺延、空槽拿现金 4%（选股层每月出斜率 Top2，连 2 月破线才把该股踢出当月持仓，不是段内日线止损；"
    "单月破线立刻斩会被均线附近抽波反复触发，换手翻倍却不多规避回撤，故加 2 月确认）。"
    "⚠️ **下列回测数字是旧「单月破线即斩」版，2 月确认改动后待重跑更新**（月度近似估计：换手降到 ~1.9 次/年、"
    "回撤仍守 ~-31%、Calmar 略升）。回测（round7-11，2017-04→2026-06，单边 200bps）：全程 CAGR 18.4% / DD -30.5% / Calmar 0.60"
    "（SPY 15.0% / -23.9% / 0.63），3Y 29.3% / -13.4% / 2.19，5Y 16.8% / -30.5% / 0.55，"
    "换手 1.7 次/年，常态空仓 23%。同池对照：无斩仓（纯斜率 Top2）17.5%/**-49.2%**/0.36——"
    "斩仓把回撤从 -49% 砍到 -30%，CAGR 反升，是这页的核心 alpha。"
    "**四条警告**：① 本组合是 round7-11 20+ 形态择优（k=0.25 取平台 [0.15,0.35] 中心非孤峰），预期打折看待；"
    "② 全程 Calmar 略低于 SPY，价值在近 3Y regime 和止损纪律——这是**进攻腿**，与 FCF收益率稳定页（防守腿）互补，别当同类；"
    "③ 双票高集中且全是最陡动量票，破线月末才确认，崩盘首段 -15~-20% 跑不掉；"
    "④ 空仓 23% 是特性不是 bug：无合格陡票时拿现金，别手痒补仓。"
    "**注：下方热力图/奖牌/接力净值走前端周线复权价，与上列月线回测数字会有小差，持仓逻辑一致。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

TOP_N = 2
K_STOP = 0.25
CONFIRM_M = 2        # 连续 2 月破线才斩，滤掉单月抽波假信号（降换手）
MA_W, SIG_W = 6, 12
COST_BPS = 200.0     # 单边 200bps

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(mem) for y, mem in (doc.get("pools") or {}).items()}
meta = doc.get("meta") or {}
seg_panel = doc.get("seg_panel") or {}
if not seg_panel:
    st.warning("⚠️ seg_panel 未就绪（本地重跑 build_logr2_stable_pool.py 并上传后生效）")
    st.stop()
built = pd.to_datetime(doc.get("built_at"), errors="coerce", utc=True)
if pd.notna(built) and (pd.Timestamp.now(tz="UTC") - built).days > 40:
    st.warning(f"⚠️ 数据已 {(pd.Timestamp.now(tz='UTC') - built).days} 天未重建"
               "（本地跑 build_logr2_stable_pool.py 并上传后排名才会更新）")

union = sorted({t for mem in pools.values() for t in mem})
rest = [t for t in union if not (meta.get(t) or {}).get("is_tech")]

# 当前段面板：seg_panel[tk][date] = [年化斜率%, 段长周]（这里只用斜率当排名轴）
slope_m = pd.DataFrame({tk: pd.Series({d: v[0] for d, v in (seg_panel.get(tk) or {}).items()},
                                      dtype=float) for tk in rest})
slope_m.index = pd.to_datetime(slope_m.index)
slope_m = slope_m.sort_index()

memb = pd.DataFrame(False, index=slope_m.index, columns=slope_m.columns)
for y, mem in pools.items():
    memb.loc[memb.index.year == y, [t for t in mem if t in memb.columns]] = True
sc_in = slope_m.where(memb)                     # 排名轴：段斜率（池成员 mask）
rank_m = sc_in.rank(axis=1, ascending=False, method="first")

# ── 价格（yfinance + Sharadar 补缺，BRK.B 走别名）──
_ALIAS = {"BRK.B": "BRK-B"}
window = st.radio("时间跨度", ["3Y", "5Y", "10Y"], index=2, horizontal=True, key="seg_window")
with st.spinner("📊 加载价格..."):
    _px = get_global_data([_ALIAS.get(t, t) for t in rest] + ["SPY"], years=12)
close_d = {}
if _px is not None and not _px.empty:
    for t in rest:
        col = _ALIAS.get(t, t)
        if col in _px.columns and _px[col].notna().sum() >= 2:
            close_d[t] = _px[col].dropna()
_missing = [t for t in rest if t not in close_d]
if _missing:
    for t, rows_p in (fetch_gbdt_oos_prices(tuple(sorted(_missing))) or {}).items():
        if rows_p:
            arr = pd.DataFrame(rows_p, columns=["date", "o", "h", "l", "c", "v"])
            close_d[t] = arr.assign(date=pd.to_datetime(arr["date"])).set_index("date")["c"].astype(float)

# 周线价格喂 render_group 的接力引擎（calc_slot_stats）
_price_cache = {t: s.resample("W-FRI").last().dropna().to_frame(name="Close")
                for t, s in close_d.items() if s.resample("W-FRI").last().dropna().shape[0] >= 2}
_spy_wk = pd.DataFrame()
if _px is not None and "SPY" in _px.columns:
    _spy_wk = _px["SPY"].dropna().resample("W-FRI").last().dropna().to_frame(name="Close")

close_m = pd.DataFrame({t: s.resample("ME").last() for t, s in close_d.items()}).sort_index()

# ── 通道斩仓线：连续 CONFIRM_M 个月收盘 ≤ MA6×(1−0.25σ12) 才出局（月度选股层决策）。
#    单月破线立刻斩会被最陡动量票在均线附近的抽波反复触发，换手翻倍却不多规避回撤；
#    要求连 2 月都破线才确认，去掉假信号，换手降一档、回撤守住 ~-31%。──
ma6 = close_m.rolling(MA_W).mean()
ret_m = close_m.pct_change(fill_method=None)
sig12 = ret_m.rolling(SIG_W).std()
floor_m = ma6 * (1 - K_STOP * sig12)
_above0 = (close_m > floor_m).reindex(index=slope_m.index, columns=slope_m.columns).fillna(False)
_conf_below = (~_above0).rolling(CONFIRM_M).sum().fillna(0) >= CONFIRM_M
above = ~_conf_below

# ── 每月持仓：斜率 Top2 且在通道上方；破线换现金、名额不顺延（决策月 → 执行月 +1）──
sel = (rank_m <= TOP_N) & above & memb          # 通道过滤后的实际持仓
raw = (rank_m <= TOP_N) & memb                  # 原始斜率 Top2（未过滤，持仓表对照用）
_mh, _mh_raw = {}, {}
for d in slope_m.index:
    order = rank_m.loc[d].dropna().sort_values().index.tolist()
    em = hv.next_month_key(d.strftime("%Y-%m"), 1)
    _mh[em] = [t for t in order if bool(sel.at[d, t])][:TOP_N]
    _mh_raw[em] = [t for t in order if bool(raw.at[d, t])][:TOP_N]

last_month = sc_in.index[-1]
window_lo = last_month - pd.DateOffset(years=int(window[:-1]))
name_map = {t: (meta.get(t) or {}).get("name", t) for t in rest}
_rs_dummy = pd.DataFrame(np.nan, index=sc_in.index, columns=sc_in.columns)

render_group(
    "非科技陡票", rest, "seg_rest",
    score_m=sc_in, sweep_score_m=None,
    rs_m=_rs_dummy, king_m=sc_in, name_map=name_map, grade_map={},
    window=window, month_in_progress=False, last_month=last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="段斜率%", score_fmt="{:.1f}",
    n_hold=TOP_N, gold_needs_rs=False,
    nav_engine="weekly", cost_bps=COST_BPS,
    medal_table_hide_unmedaled=True,
    display_from=window_lo,
    precomputed_holdings=_mh, precomputed_raw=_mh_raw,
)
