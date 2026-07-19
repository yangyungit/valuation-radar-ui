import streamlit as st
import pandas as pd
import numpy as np

import holdings_viz as hv
from api_client import (fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data,
                        compute_macro_regime_api, fetch_current_regime)
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
    "且 maxDD≥-45% / 带方向 logR² 前40），只看**非科技子集**，池子零改动"
    "（放宽入池实测大幅变差：round12 全程 CAGR 3~11%、DD -38~-50%，吸进能源周期票——"
    "5Y 质量门是承重墙，进场晚是代价不是 bug）。"
    "**排名轴 = 当前段年化斜率**：月末在 52~260 周里找最长的仍达标（logR²≥0.70 且年化斜率≥8%）"
    "后缀窗当「当前段」，段斜率越陡排名越前；无达标段 = 无资格。**🥇 金牌 = 斜率 Top1 / 🥈 银牌 = Top2**。"
    "**组合 = 带鱼持有 + 通道斩仓**：斜率排名只决定买什么，不决定卖什么——槽位买入后一直持有，"
    "直到月末收盘 ≤ MA6×(1−0.25σ) 破线才斩仓换现金（单月确认）；腾出的槽给当月斜率 Top2 里"
    "通道上方、且**价在自身近 12 月高点 5% 内**（浅V不容忍：挡深V反抽半山腰进场）的未持有票，"
    "没有就拿现金 4%（掉出 Top2 不卖：一直参与直的，直到被打破才找下一个）。"
    "回测（round12-14，2017-04→2026-06，单边 200bps）：全程 CAGR 18.6% / DD -26.2% / Calmar 0.71"
    "（SPY 15.0% / -23.9% / 0.63），3Y 27.6% / -26.2% / 1.05，5Y 15.0% / -26.2% / 0.57，"
    "换手 1.25 次/年，常态空仓 21%。同池对照：旧「斜率 Top2 月调 + 2 月确认斩仓」= 22.1%/-31.5%/0.70——"
    "持到破位让 3.5pp CAGR，换 5.3pp 回撤 + 换手更低 + 不再中途卖掉没破位的带鱼。"
    "**四条警告**：① 本组合是 round7-14 20+ 形态择优（k=0.25 取平台 [0.15,0.35] 中心非孤峰），预期打折看待；"
    "② 近 3Y Calmar 1.05 低于旧月调版的 2.15，价值在全程回撤和持有纪律——这是**进攻腿**，"
    "与 FCF收益率稳定页（防守腿）互补，别当同类；"
    "③ 双票高集中，破线月末才确认，崩盘首段 -15~-20% 跑不掉（最大回撤窗 2025-01→2025-03）；"
    "④ 空仓 21% 是特性不是 bug：Top2 都不合格或在通道下方时拿现金，别手痒补仓。"
    "**注：下方热力图/奖牌/接力净值走前端周线复权价，与上列月线回测数字会有小差，持仓逻辑一致。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

TOP_N = 2
K_STOP = 0.25
MA_W, SIG_W = 6, 12
COST_BPS = 200.0     # 单边 200bps
NEAR_HIGH = 0.95     # 浅V不容忍：新进场须月末价 ≥ 自身近 12 月最高价 ×0.95（5% 内），
                     # 深V反抽还远在前高下方直接挡掉（REGN/AGN 2016、MSCI 2022、PWR 2025-02 那批）

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

# ── seg_panel 是什么、怎么算出来的（后端 build_logr2_stable_pool.py 的 seg_trend_panels）──
#   结构：seg_panel[tk][月末date] = [当前段年化斜率%, 当前段长度周]。本页只取 [0] 斜率当排名轴。
#
#   「当前段」= 以今天为终点、往回找到的「最长的仍达标」后缀窗，不是最陡的窗：
#     · 候选窗长 SEG_WINDOWS = range(52,261,26) = 52/78/104/.../260 周（1~5 年，每半年一档）。
#     · 每个窗都从今天往回取，算两件事：够不够直（signed logR² = corr(logP,t)×|corr|）、
#       够不够陡（年化斜率%）。达标线 = R²≥0.70 且 斜率≥8%（后端 SEG_R2_MIN / SEG_SLOPE_MIN）。
#     · 后端循环从短到长、达标就覆盖（slope_p = sl.where(ok, slope_p)），最终留下的是
#       「达标里最长的窗」= 当前段；段斜率随之取那个最长窗的斜率（不是最陡短窗的斜率）。
#     · 所有窗都不达标 → NaN → 该票本月无资格、不进榜。
#
#   为什么取最长窗而不是最陡窗（设计取舍，不是唯一解）：
#     · 52/78 周超短窗斜率常虚高（瞬时爆发 300~500%），用它排名会每月追最陡票、换手翻倍、
#       且专挑加速赶顶的位置。取最长达标窗 = 用更成熟、跨度更长的斜率读数，排名更稳。
#     · R² 门槛 0.70 是「软过滤」：浅 V（先跌后强反弹）只要整段仍拟合成上升直线就放行，
#       深 V 会被 R² 拦掉。容忍浅 V 是为了在「底部反转已确认、但尚未创新高」时就早上车抓
#       深蹲起跳；代价是可能买在下跌中继反抽的半山腰——这个回撤风险不在选段这步控制，
#       由下游「通道斩仓」收口（月末收盘跌破 MA6×(1−0.25σ) 就砍仓换现金，见下方 above）。
#
#   排名（本页）：每月对每只票各自算出当前段斜率，再把全池按段斜率降序排、取 Top2 进持仓
#     （见下方 sc_in / rank_m）。「最陡」是跨票 PK 排名用的，「最长达标」是单票内部选段用的。
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

# ── 通道斩仓线：月末收盘 ≤ MA6×(1−0.25σ12) 即斩仓换现金（单月确认）。
#    持到破位形态下破线是唯一卖出口，必须灵敏；2 月确认是旧「月调重排」场景的
#    降换手补丁，这里只会多吃一个月下跌（round14：conf2 Calmar 0.56 vs conf1 0.71）──
ma6 = close_m.rolling(MA_W).mean()
ret_m = close_m.pct_change(fill_method=None)
sig12 = ret_m.rolling(SIG_W).std()
floor_m = ma6 * (1 - K_STOP * sig12)
above = (close_m > floor_m).reindex(index=slope_m.index, columns=slope_m.columns).fillna(False)

# ── 浅V不容忍进场门：月末价距自身近 12 月最高价 ≥ NEAR_HIGH（在高位、非深V反抽）才准新进场。
#    只卡新进场，不卡在任票（带鱼持有不受此门约束）。深V被 seg 选段的 R²≥0.70 软过滤放行，
#    这道门在下游把「反抽半山腰」的进场再挡一层（实测 Calmar 0.23→0.31、换手降 30%）。──
_roll_high = close_m.rolling(12, min_periods=3).max()
near_high = (close_m / _roll_high).reindex(index=slope_m.index, columns=slope_m.columns)
near_ok = (near_high >= NEAR_HIGH).fillna(False)

# ── 每月持仓：带鱼持有——槽位买入后不按名次月调，破线才斩仓腾槽；
#    补槽 = 当月段斜率 Top2 里通道上方的未持有票，没有就空槽拿现金
#    （决策月 → 执行月 +1）──
raw = (rank_m <= TOP_N) & memb                  # 原始斜率 Top2（持仓表对照用）
_mh, _mh_raw = {}, {}
_held: list = []
for d in slope_m.index:
    _held = [t for t in _held if bool(above.at[d, t])]
    order = rank_m.loc[d].dropna().sort_values().index.tolist()
    for t in order:
        if len(_held) >= TOP_N or rank_m.at[d, t] > TOP_N:
            break
        if t not in _held and bool(above.at[d, t]) and bool(near_ok.at[d, t]):
            _held.append(t)
    em = hv.next_month_key(d.strftime("%Y-%m"), 1)
    _mh[em] = list(_held)
    _mh_raw[em] = [t for t in order if bool(raw.at[d, t])][:TOP_N]

last_month = sc_in.index[-1]
window_lo = last_month - pd.DateOffset(years=int(window[:-1]))
name_map = {t: (meta.get(t) or {}).get("name", t) for t in rest}
_rs_dummy = pd.DataFrame(np.nan, index=sc_in.index, columns=sc_in.columns)

# ── 熊市防御条带（与「科技龙头」页同源，默认关）：
#    红 = GBDT 日频 chaos 触发后 20 交易日 → 清仓持现金；橙 = 旧闸门 chaos_share>0.40 月 → 减仓一半。
#    render_group 里的开关默认关（bear_default=False），打开后量化能规避多少回撤。──
_DANGER_FWD_DAYS = 20
_danger_full = _danger_half = None
try:
    if _px is not None and "SPY" in _px.columns:
        _cal = pd.DatetimeIndex(_px["SPY"].dropna().index).sort_values()
        _chain = compute_macro_regime_api(z_window=750) or {}
        _cur = fetch_current_regime() or {}
        _danger_full = pd.Series(False, index=_cal)
        _danger_half = pd.Series(False, index=_cal)
        _trig = (_chain.get("horsemen_daily_chaos_trigger", {}) or {})
        for _td in pd.to_datetime([k for k, v in _trig.items() if v], errors="coerce").dropna():
            _pos = int(_cal.searchsorted(_td))
            if _pos < len(_cal):
                _danger_full.iloc[_pos:_pos + _DANGER_FWD_DAYS + 1] = True
        _hmp = (((_chain.get("data", {}) or {}).get("horsemen_monthly_probs", {}))
                or (_cur.get("horsemen_monthly_probs", {})) or {})
        _recs = []
        for _ms, _pr in _hmp.items():
            if isinstance(_pr, dict):
                try:
                    _recs.append((pd.Timestamp(str(_ms) + "-01"),
                                  float(_pr.get("chaos_share", 0.0) or 0.0) > 0.40))
                except Exception:
                    pass
        if _recs:
            _mdf = pd.DataFrame(_recs, columns=["date", "g"]).set_index("date").sort_index()
            _danger_half = _mdf["g"].reindex(_cal, method="ffill").fillna(False).astype(bool)
        _danger_half = _danger_half & ~_danger_full
except Exception:
    _danger_full = _danger_half = None

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
    danger_daily=_danger_full, danger_half_daily=_danger_half, bear_default=False,
)
