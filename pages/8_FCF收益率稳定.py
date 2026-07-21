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
    "**组合 = 等权 Top2 月末调仓 + 守擂死区**（round16）——在任票 fcfy 距当月 Top2 门槛分"
    "≤1×截面标准差就不换，腾槽按当月排名补；无金银牌、无 MA/回撤择时（round3-5 已证伪接力形态，"
    "round16 证伪照抄 ROIC 页按名次留任——fcfy 轴 2~5 名名次是噪声，按名次留任照样乒乓）。"
    "回测（round16，2017-04→2026-06，单边 200bps）：全程 CAGR 17.1% / DD -21.2% / Calmar 0.81"
    "（SPY 15.0% / -23.9% / 0.63），3Y 22.8% / -10.7% / 2.13，5Y 19.3% / -10.7% / 1.80，"
    "换手 0.87 次/年（原月调硬重排 2.06）。"
    "**三条警告**：① 持仓常年是成对保险股（TRV/CB/PGR/ACGL），等于一注押保险业，行业集中需人工过目，别当黑箱信；"
    "② 死区 k=1.0 是 round6 之后又一轮 ~20 变体择优（邻域 [0.9,1.2] 平台、0.7/0.8 有坑），预期打折看待；"
    "③ 死区只降换手不防崩：2018 年 -16.7%（SPY -9.6%），DD 与硬重排相同 -21.2%。"
    "**注：下方热力图/奖牌/接力净值走前端周线复权价，与上列月线回测数字会有小差，持仓逻辑一致（🥇=Top1 / 🥈=Top2）。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

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

# ── 每月持仓：守擂死区——在任票 fcfy ≥ 当月 Top-n 门槛分 − k×截面 std 就不换；
#    腾出的槽按当月排名补。月末决策，次月执行。──
def _deadband_holdings(n, k):
    _mh, _mh_raw, _prev = {}, {}, []
    for d in score_in.index:
        row = score_in.loc[d]
        order = row.dropna().sort_values(ascending=False)
        top = order.index[:n].tolist()
        if len(order) >= n:
            thresh = float(order.iloc[n - 1]) - k * float(row.std())
            keep = [t for t in _prev if pd.notna(row.get(t)) and float(row[t]) >= thresh]
            hold = keep + [t for t in order.index if t not in keep][:n - len(keep)]
        else:
            hold = top
        _prev = hold
        em = hv.next_month_key(d.strftime("%Y-%m"), 1)
        _mh[em] = list(hold)
        _mh_raw[em] = list(top)
    return _mh, _mh_raw

last_month = score_in.index[-1]
window_lo = last_month - pd.DateOffset(years=int(window[:-1]))
name_map = {t: (meta.get(t) or {}).get("name", t) for t in rest}
_rs_dummy = pd.DataFrame(float("nan"), index=score_in.index, columns=score_in.columns)

_common = dict(
    score_m=score_in, sweep_score_m=None,
    rs_m=_rs_dummy, king_m=score_in, name_map=name_map, grade_map={},
    window=window, month_in_progress=False, last_month=last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="FCF收益率%", score_fmt="{:.1f}",
    gold_needs_rs=False, nav_engine="weekly", cost_bps=COST_BPS,
    medal_table_hide_unmedaled=True, display_from=window_lo,
)

tab2, tab1 = st.tabs(["🥈 Top2 双仓（现状 · 死区 k=1.0）", "🥇 Top1 单仓（死区 k=2.0 · 实验）"])

with tab2:
    _mh2, _mh2_raw = _deadband_holdings(2, 1.0)
    render_group(
        "非科技 FCF收益率", rest, "fcfy_rest",
        n_hold=2, precomputed_holdings=_mh2, precomputed_raw=_mh2_raw, **_common,
    )

with tab1:
    st.info(
        "**单仓实验**：只持 FCF收益率 Top1，守擂死区 k=2.0（在任票 fcfy ≥ 当月 Top1 门槛分 "
        "− 2.0×截面 std 就不换）。月线回测（2017-04→，单边 200bps）：CAGR 18.1% / DD -18.3% / "
        "Calmar 0.99，对照现状 Top2 的 17.1% / -21.2% / 0.81——单仓年化更高、回撤更浅、Calmar 更好，"
        "换手 0.98 次/年。**k=2.0 取自回撤平台右肩**：k∈[1.0,2.0] 是同型持仓平台（DD 恒 -18.x、9 段结构一致），"
        "CAGR 随 k 单调升到 2.0，k≥2.25 才因漏切换令 DD 恶化到 -21.9。仍是参数择优，预期打折看待；"
        "下方走前端周线复权价重建，与月线回测数字有小差。"
    )
    _mh1, _mh1_raw = _deadband_holdings(1, 2.0)
    render_group(
        "非科技 FCF收益率(单仓)", rest, "fcfy_rest_top1",
        n_hold=1, precomputed_holdings=_mh1, precomputed_raw=_mh1_raw, **_common,
    )
