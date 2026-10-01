import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data
from buyback_relay_core import render_group
from cn_names import cn_name_map

st.set_page_config(page_title="FCF%单仓", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

COST_BPS = 200.0     # 单边 200bps
LOGR2_GATE = 0.75    # 逐月趋势顺滑度门槛：候选票当月滚动260周带方向logR²需≥此值
K_TOP1 = 2.0         # 单仓死区 k：取 δ 扫描推荐 δ*，2.25 起悬崖式下跌
K_TOP2 = 1.0

st.title("💵 FCF%单仓（带鱼池 × FCF收益率 Top1 单仓）")
st.caption(
    "**池子**：年度 PIT 价格行为池（带鱼池，不变）——市值≥$30B / TTM FCF>0 / 近5Y周线 CAGR≥8% 且 "
    "maxDD≥-45% / 按带方向 logR² 前40，每年12月末重构次年生效（本地 Sharadar 构建）。"
    "页面只看**非科技子集**。**排名轴 = FCF收益率**（ART PIT fcf/marketcap，季频 ffill 到月末，池成员内排名）。"
    "**组合 = 只持 Top1 满仓，月末调仓 + 守擂死区 + 逐月趋势门槛**——在任票 fcfy 距当月 Top1 分"
    f"≤{K_TOP1}×截面标准差就不换（k 取下方 δ 跨 3/5/10Y 稳健性扫描的推荐 δ*）；"
    "**候选票另需当月带方向 logR² ≥ 0.75**（把进池后趋势掉头的票当月踢出，如 ADM 2024 logR² 0.83→0.28）；"
    "无金银牌、无 MA/回撤择时。"
    "月线回测（2017-04→2026-09，单边 200bps）：单仓 CAGR 24.2% / DD -18.3% / Calmar 1.33 / 换手 0.63 次/年；"
    "对照 Top2（k=1.0）18.4% / -21.2% / 0.87 / 0.95；SPY 15.0% / -23.9% / 0.62。"
    "**三条警告**：① 9 年只换 7 段、98% 时间持保险/医保股（PGR 两段贡献大头），等于一注押保险业，"
    "2018/2019/2021 明显跑输 SPY，行业集中需人工过目，别当黑箱信；"
    "② k=2.0 是 3/5/10Y 共同峰顶但紧挨悬崖——k=2.25 起 10Y 总收益从 607% 塌到 258%，"
    "k=1.75 是稳妥的退路；门槛 0.75 也取自平台，预期打折看待；"
    "③ 和 Top2 的差距几乎全在 2022–2024（2017–2021 两者打平）。"
    "**注：下方热力图/接力净值/δ 扫描走前端周线复权价，与上列月线回测数字有差，持仓逻辑一致。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(mem) for y, mem in (doc.get("pools") or {}).items()}
meta = doc.get("meta") or {}
fcfy_panel = doc.get("fcfy_panel") or {}
logr2_panel = doc.get("logr2_panel") or {}
if not fcfy_panel:
    st.warning("⚠️ fcfy_panel 未就绪（本地重跑 build_logr2_stable_pool.py 并上传后生效）")
    st.stop()
if not logr2_panel:
    st.warning("⚠️ logr2_panel 未就绪（趋势门槛依赖它，本地重跑 build_logr2_stable_pool.py 并上传后生效）")
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

# 逐月趋势顺滑度门槛：池按年重建（粘性），进池后趋势掉头（如 ADM 2024 logR² 0.83→0.28）
# 靠这道闸当月踢出候选，让持仓集中在平滑上行票。NaN（logR² 未就绪）视为不达标。
logr2_m = pd.DataFrame({tk: pd.Series(logr2_panel.get(tk) or {}, dtype=float) for tk in rest})
logr2_m.index = pd.to_datetime(logr2_m.index)
logr2_m = logr2_m.sort_index().reindex(index=score_m.index, columns=score_m.columns)
gate_mask = logr2_m >= LOGR2_GATE
score_in = score_m.where(memb & gate_mask & score_m.notna())  # 排名轴：FCF收益率（池成员 × logR²门槛）

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
cn_map = cn_name_map(rest)
_rs_dummy = pd.DataFrame(float("nan"), index=score_in.index, columns=score_in.columns)

_common = dict(
    score_m=score_in, sweep_score_m=None,
    rs_m=_rs_dummy, king_m=score_in, name_map=name_map, grade_map=cn_map,
    window=window, month_in_progress=False, last_month=last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="FCF收益率%", score_fmt="{:.1f}",
    gold_needs_rs=False, nav_engine="weekly", cost_bps=COST_BPS,
    medal_table_hide_unmedaled=True, display_from=window_lo,
    stitched_name_style="cn_ticker",
)

tab1, tab2 = st.tabs(["🥇 Top1 单仓（主版本）", "🥈 Top2 双仓（对照）"])

with tab1:
    render_group(
        "非科技 FCF收益率(单仓)", rest, "fcfy_rest_top1",
        n_hold=1, default_k=K_TOP1, holdings_fn=lambda k: _deadband_holdings(1, k), **_common,
    )

with tab2:
    render_group(
        "非科技 FCF收益率", rest, "fcfy_rest",
        n_hold=2, default_k=K_TOP2, holdings_fn=lambda k: _deadband_holdings(2, k), **_common,
    )
