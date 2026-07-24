import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import get_global_data
from buyback_relay_core import render_group

st.set_page_config(page_title="黄金带鱼", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🥇 黄金带鱼轮动（黄金档7只 × 12M动量 × 通道留任）")
st.caption(
    "**池子**：带鱼.md 黄金档手挑 7 只——AAPL / LLY / TJX / COST / V / BRK.B / MA（又陡又顺的品牌龙头，固定名单）。"
    "**排名轴 = 12M 动量**（月末价 12 个月涨幅，纯前端 yfinance 价格计算，无后端依赖）。"
    "**组合 = 排名决定买、通道决定卖**：在任票只要月末价 > 自己的 MA6×(1−0.5×近12月波动) 通道下沿就一直拿，"
    "排名掉了不卖；跌破通道下沿才腾位，腾位当月立刻按 12M 动量排名补最强票，**无进场门、无空仓**"
    "（跌破但当月动量仍在 Top 档 → 原地留任，视为噪音；破线 + 掉出 Top 档同时发生才真换仓）。"
    "月末决策、次月执行。回测（月线，2016-07→2026-07，单边 200bps）："
    "Top2 全程 CAGR 20.7% / DD -21.2% / Calmar 0.98（SPY 14.8 / -23.9 / 0.62），"
    "5Y 21.2 / -18.4 / 1.15，3Y 23.7 / -11.5 / 2.05，换仓 1.9 次/年。"
    "**四条警告**：① 这 7 只是 2026-07 **事后**手挑的十年最漂亮票，所有数字自带后视镜光环——"
    "等权 7 只拿住不动就是 22.8 / -14.7 / 1.56 的怪物基线，**轮动版并没有跑赢它**，"
    "本页价值是持有纪律和换仓提示，不是证明轮动更赚；"
    "② 回购页同款严进场门（MA4>MA15+下穿重置）在 7 只小池实测崩坏（10Y CAGR 3.1% / DD -43% / 空槽率 30%——"
    "小池腾位后长期填不满，这池子空仓就是亏），故本页无进场门；"
    "③ 规则经 6 变体择优（严门/松门/无门/k0.25/12-1动量/榜内不限档），最简单的版本胜出，预期仍打折看待；"
    "④ Top1 单仓实测 17.3 / -30.6 / 0.57，单票集中回撤太深，只留作对照别当主力。"
    "**注：下方热力图/奖牌/接力净值走前端周线复权价，与上列月线回测数字会有小差，持仓逻辑一致（🥇=Top1 / 🥈=Top2）。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        st.rerun()

COST_BPS = 200.0          # 单边 200bps，与姊妹页同口径
MOM_W = 12                # 12M 动量
RET_MA, RET_K, VOL_W = 6, 0.5, 12   # 通道下沿 = MA6 × (1 − 0.5×近12月波动)，回购稳定页同款

GOLD = ["AAPL", "LLY", "TJX", "COST", "V", "BRK.B", "MA"]
_ALIAS = {"BRK.B": "BRK-B"}
name_map = {"AAPL": "Apple", "LLY": "Eli Lilly", "TJX": "TJX", "COST": "Costco",
            "V": "Visa", "BRK.B": "Berkshire", "MA": "Mastercard"}

window = st.radio("时间跨度", ["3Y", "5Y", "10Y"], index=2, horizontal=True, key="gold_window")

with st.spinner("📊 加载价格..."):
    _px = get_global_data([_ALIAS.get(t, t) for t in GOLD] + ["SPY"], years=12)
if _px is None or _px.empty:
    st.error("⚠️ 价格数据拉取失败（yfinance），点侧栏刷新重试")
    st.stop()

close_d = {}
for t in GOLD:
    col = _ALIAS.get(t, t)
    if col in _px.columns and _px[col].notna().sum() >= 2:
        close_d[t] = _px[col].dropna()
pool = list(close_d.keys())
if len(pool) < 2:
    st.error("⚠️ 有效价格不足 2 只，无法排名")
    st.stop()

_price_cache = {t: s.resample("W-FRI").last().dropna().to_frame(name="Close")
                for t, s in close_d.items()}
_spy_wk = pd.DataFrame()
if "SPY" in _px.columns:
    _spy_wk = _px["SPY"].dropna().resample("W-FRI").last().dropna().to_frame(name="Close")

close_m = pd.DataFrame({t: s.resample("ME").last() for t, s in close_d.items()}).sort_index()
mom_m = close_m.pct_change(MOM_W) * 100
_vol = close_m.pct_change().rolling(VOL_W).std()
ret_mask = close_m > close_m.rolling(RET_MA).mean() * (1 - RET_K * _vol)

asof = max(s.index[-1] for s in close_d.values())
last_month = mom_m.index[-1]
month_in_progress = bool(last_month.to_period("M").end_time.normalize() > asof.normalize())


# ── 每月持仓：在任票 > 自身通道下沿就留任（排名掉了不卖）；
#    跌破才腾位，当月按 12M 动量排名补 Top-n 里未留任的最强票（无进场门，回测见 caption ②）。──
def _channel_holdings(n):
    _mh, _mh_raw, _prev = {}, {}, []
    for d in mom_m.index:
        order = mom_m.loc[d].dropna().sort_values(ascending=False)
        top = order.index[:n].tolist()
        keep = [t for t in _prev if bool(ret_mask.at[d, t])]
        hold = keep + [t for t in top if t not in keep][:n - len(keep)]
        _prev = hold
        em = hv.next_month_key(d.strftime("%Y-%m"), 1)
        _mh[em] = list(hold)
        _mh_raw[em] = list(top)
    return _mh, _mh_raw


window_lo = last_month - pd.DateOffset(years=int(window[:-1]))
_rs_dummy = pd.DataFrame(float("nan"), index=mom_m.index, columns=mom_m.columns)

_common = dict(
    score_m=mom_m, sweep_score_m=None,
    rs_m=_rs_dummy, king_m=mom_m, name_map=name_map, grade_map={},
    window=window, month_in_progress=month_in_progress, last_month=last_month,
    price_cache=_price_cache, spy_wk=_spy_wk,
    score_label="12M动量%", score_fmt="{:+.1f}",
    gold_needs_rs=False, nav_engine="weekly", cost_bps=COST_BPS,
    medal_table_hide_unmedaled=True, display_from=window_lo,
    pick_show_name=True,
)

tab2, tab1 = st.tabs(["🥈 Top2 双仓（现状）", "🥇 Top1 单仓（对照 · 回撤深）"])

with tab2:
    _mh2, _mh2_raw = _channel_holdings(2)
    render_group(
        "黄金带鱼 12M动量", pool, "gold_ribbon",
        n_hold=2, precomputed_holdings=_mh2, precomputed_raw=_mh2_raw, **_common,
    )

with tab1:
    st.info(
        "**单仓对照**：只持 12M 动量 Top1，通道留任同款。月线回测（2016-07→，单边 200bps）："
        "CAGR 17.3% / DD -30.6% / Calmar 0.57——单票集中，LLY 式 -40% 深跌要月末破线才确认，"
        "回撤比 Top2（-21.2%）深一截，收益还更低。放这里只为对照，别当主力。"
    )
    _mh1, _mh1_raw = _channel_holdings(1)
    render_group(
        "黄金带鱼 12M动量(单仓)", pool, "gold_ribbon_top1",
        n_hold=1, precomputed_holdings=_mh1, precomputed_raw=_mh1_raw, **_common,
    )
