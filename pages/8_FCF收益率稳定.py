import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="FCF收益率稳定", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("💵 FCF收益率稳定（带鱼池 × FCF收益率 Top2）")
st.caption(
    "**池子**：年度 PIT 价格行为池（带鱼池，不变）——市值≥$30B / TTM FCF>0 / 近5Y周线 CAGR≥8% 且 "
    "maxDD≥-45% / 按带方向 logR² 前40，每年12月末重构次年生效（本地 Sharadar 构建上传）。"
    "页面只看**非科技子集**。**排名轴 = FCF收益率**（ART PIT fcf/marketcap，季频 ffill 到月末，池成员内排名）。"
    "**组合 = 等权 Top2 月末调仓**——无金银牌、无 MA/回撤择时：round3-5 已证伪接力形态"
    "（所有排名轴的双槽接力全跑输等权篮子，见 backtest_logr2_stable_round3/4/5.py）。"
    "回测（round6，2017-04→2026-06，单边 200bps）：全程 CAGR 12.3% / DD -21.2% / Calmar 0.58"
    "（SPY 15.0% / -23.9% / 0.63），3Y 13.5% / -10.7% / 1.26，5Y 9.9% / -11.7% / 0.85，换手 2.1 次/年。"
    "**三条警告**：① 全程跑输 SPY 2.7pp，价值只在 DD 更浅，是防守腿不是进攻腿；"
    "② 持仓常年是成对保险股（TRV/CB/PGR/ACGL），等于一注押保险业，行业集中需人工过目，别当黑箱信；"
    "③ 该组合是 24 个候选里择优出来的（唯一佐证：对未来 12 月收益池内 IC +0.115，其余轴全≈0），预期打折看待。"
    "**注：下方热力图/奖牌/接力净值走前端周线复权价，与上列月线回测数字会有小差，持仓逻辑一致（🥇=Top1 / 🥈=Top2，等权月调）。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

TOP_N = 2
COST_BPS = 200.0     # 单边 200bps

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(mem) for y, mem in (doc.get("pools") or {}).items()}
meta = doc.get("meta") or {}
fcfy_panel = doc.get("fcfy_panel") or {}
if not fcfy_panel:
    st.warning("⚠️ fcfy_panel 未就绪（本地重跑 build_logr2_stable_pool.py 并上传后生效）")
    st.stop()
built = pd.to_datetime(doc.get("built_at"), errors="coerce", utc=True)
if pd.notna(built) and (pd.Timestamp.now(tz="UTC") - built).days > 40:
    st.warning(f"⚠️ 数据已 {(pd.Timestamp.now(tz='UTC') - built).days} 天未重建"
               "（本地跑 build_logr2_stable_pool.py 并上传后排名才会更新）")

union = sorted({t for mem in pools.values() for t in mem})
rest = [t for t in union if not (meta.get(t) or {}).get("is_tech")]

# FCF 收益率面板：ART 季频 datekey → 月末 ffill（PIT），池成员内排名
raw = pd.DataFrame({tk: pd.Series(fcfy_panel.get(tk) or {}, dtype=float) for tk in rest})
raw.index = pd.to_datetime(raw.index)
raw = raw.sort_index()
grid = pd.date_range(raw.index.min(), pd.Timestamp.today(), freq="ME")
score_m = raw.reindex(raw.index.union(grid)).ffill().reindex(grid)

memb = pd.DataFrame(False, index=score_m.index, columns=score_m.columns)
for y, mem in pools.items():
    memb.loc[memb.index.year == y, [t for t in mem if t in memb.columns]] = True
score_in = score_m.where(memb & score_m.notna())        # 排名轴：FCF收益率（池成员 mask）
rank_m = score_in.rank(axis=1, ascending=False, method="first")

# ── 价格（yfinance + Sharadar 补缺，BRK.B 走别名）──
_ALIAS = {"BRK.B": "BRK-B"}
window = st.radio("时间跨度", ["3Y", "5Y", "10Y"], index=2, horizontal=True, key="fcfy_window")
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

# ── 每月持仓：当月 FCF收益率 Top2，月末调仓，次月执行（决策月 → 执行月 +1）。
#    无守擂、无接力留任——每月重取当月 Top2，等权两仓。──
_mh, _mh_raw = {}, {}
for d in score_in.index:
    order = rank_m.loc[d].dropna().sort_values().index.tolist()
    top2 = order[:TOP_N]
    em = hv.next_month_key(d.strftime("%Y-%m"), 1)
    _mh[em] = list(top2)
    _mh_raw[em] = list(top2)

last_month = score_in.index[-1]
window_lo = last_month - pd.DateOffset(years=int(window[:-1]))
name_map = {t: (meta.get(t) or {}).get("name", t) for t in rest}
_rs_dummy = pd.DataFrame(float("nan"), index=score_in.index, columns=score_in.columns)

render_group(
    "非科技 FCF收益率", rest, "fcfy_rest",
    score_m=score_in, sweep_score_m=None,
    rs_m=_rs_dummy, king_m=score_in, name_map=name_map, grade_map={},
    window=window, month_in_progress=False, last_month=last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="FCF收益率%", score_fmt="{:.1f}",
    n_hold=TOP_N, gold_needs_rs=False,
    nav_engine="weekly", cost_bps=COST_BPS,
    medal_table_hide_unmedaled=True,
    display_from=window_lo,
    precomputed_holdings=_mh, precomputed_raw=_mh_raw,
)
