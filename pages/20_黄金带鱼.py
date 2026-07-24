import streamlit as st
import pandas as pd

import holdings_viz as hv
from api_client import get_global_data
from buyback_relay_core import render_group, _plot_param_sweep

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
    "**组合 = 排名决定买、通道决定卖**：在任票只要月末价 > 自己的 MA6×(1−1.5×近12月波动) 通道下沿就一直拿，"
    "排名掉了不卖；跌破通道下沿才腾位，腾位当月立刻按 12M 动量排名补最强票，**无进场门、无空仓**"
    "（跌破但当月动量仍在 Top 档 → 原地留任，视为噪音；破线 + 掉出 Top 档同时发生才真换仓）。"
    "月末决策、次月执行。回测（月线，2016-07→2026-07，单边 200bps）："
    "Top2 全程 CAGR 20.7% / DD -21.2% / Calmar 0.98（SPY 14.8 / -23.9 / 0.62），"
    "5Y 21.2 / -18.4 / 1.15，3Y 23.7 / -11.5 / 2.05，换仓 1.9 次/年。"
    "（⚠️ 2026-07 通道 k 由 0.5 调至 1.5：卖得更慢、不在急跌里瞎腾仓——10Y 周线 回撤 -35.7%→-25.5% / Calmar 0.58→0.98 / logR² 0.972→0.976。"
    "上列月线数字系 k=0.5 旧基线待重跑，现以统计卡 + 下方 k 扫描图为准；k 值坐在跨 3/5/10Y 的重叠平台上，非单窗口碰运气。）"
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
RET_MA, RET_K, VOL_W = 6, 1.5, 12   # 通道下沿 = MA6 × (1 − k×近12月波动)，k 由下方跨3/5/10Y Calmar 扫描定（暂用 1.5）

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


# ── 通道 k 值跨 3/5/10Y Calmar 稳健性扫描：全历史各 k 重建 Top2 净值 → 切尾部三段算
#    Calmar（周线 CAGR/最大回撤）→ 归一化找三线齐高的重叠平台。口径与主净值完全同源，
#    只有 k 变。别把 k 写死——每次数据更新重画，看平台漂没漂。──
_HZ_SWEEP = [("3Y", 3), ("5Y", 5), ("10Y", 10)]


def _channel_holdings_mask(n, mask):
    _mh, _prev = {}, []
    for d in mom_m.index:
        order = mom_m.loc[d].dropna().sort_values(ascending=False)
        top = order.index[:n].tolist()
        keep = [t for t in _prev if (d in mask.index and t in mask.columns and bool(mask.at[d, t]))]
        hold = keep + [t for t in top if t not in keep][:n - len(keep)]
        _prev = hold
        _mh[hv.next_month_key(d.strftime("%Y-%m"), 1)] = list(hold)
    return _mh


def _navc_for_k(kval):
    _mask = close_m > close_m.rolling(RET_MA).mean() * (1 - kval * _vol)
    _mh = _channel_holdings_mask(2, _mask)
    _ems = sorted(_mh)
    _slots = hv.build_basket_slot_assignments(_mh, _ems)
    _segs = [hv.build_slot_segments(_slots, i, _ems) for i in range(2)]
    _nl = hv.calc_slot_stats(_segs[0], _price_cache, _spy_wk, 0.04, COST_BPS)[2]
    _nr = hv.calc_slot_stats(_segs[1], _price_cache, _spy_wk, 0.04, COST_BPS)[2]
    if _nl.empty and _nr.empty:
        return pd.Series(dtype=float)
    if _nl.empty:
        return _nr
    if _nr.empty:
        return _nl
    _ui = _nl.index.union(_nr.index)
    return 0.5 * _nl.reindex(_ui).ffill().bfill() + 0.5 * _nr.reindex(_ui).ffill().bfill()


def _trail_calmar(_nav, _yrs):
    if _nav is None or _nav.empty:
        return float("nan")
    _end = _nav.index[-1]
    if (_end - _nav.index[0]).days < _yrs * 365.25 * 0.9:
        return float("nan")
    _seg = _nav[_nav.index >= _end - pd.DateOffset(years=_yrs)]
    if len(_seg) < 8:
        return float("nan")
    return hv.compute_nav_kpi(_seg).get("calmar", float("nan"))


@st.cache_data(ttl=3600, show_spinner=False)
def _k_sweep_curves(_asof_key):
    # _asof_key 只作缓存键：数据更新（asof 变）→ 重算；同日多次 rerun 走缓存。
    _grid = [round(x * 0.1, 2) for x in range(0, 31)]   # 0.0 → 3.0，步长 0.1
    _curves = {lbl: [] for lbl, _ in _HZ_SWEEP}
    for _kv in _grid:
        _nav = _navc_for_k(_kv)
        for lbl, yrs in _HZ_SWEEP:
            _curves[lbl].append(_trail_calmar(_nav, yrs))
    return _grid, _curves


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

    st.markdown("---")
    st.markdown(f"#### 🔧 通道 k 值稳健性扫描（当前 k={RET_K}）")
    with st.spinner("扫描 k=0→3 · 重建净值算 Calmar..."):
        _grid, _curves = _k_sweep_curves(asof.strftime("%Y-%m-%d"))
    _rec_k = _plot_param_sweep(
        _grid, _curves, _HZ_SWEEP, RET_K,
        axis_title="通道 k 值（下沿 = MA6×(1−k×近12月波动)；k 越大下沿越低=拿得越久越少腾位）",
        rec_sym="k",
        title_text="通道 k 稳健性 · 尾部 3/5/10Y Calmar（各自归一化；三线齐高处=稳健平台；绿=自动 maximin 推荐；灰=当前）",
        key="gold_k_sweep", dtick=0.5, metric_name="Calmar", val_fmt=".2f", unit="",
        yaxis_title="各段归一化 Calmar (÷自身峰值)",
    )
    st.caption(
        f"✅ 当前钉在 **k={RET_K}**（1.5–1.8 的重叠平台左端，三段 Calmar 齐高：3Y≈1.7 / 5Y≈1.2 / 10Y≈0.96）。"
        f"⚠️ **别照搬绿线自动推荐（k*={_rec_k}）**：它只认 maximin 单点最高，识别不了「峰紧贴 k=2.0 悬崖」——"
        "k=1.9 冲最高后 2.0 瞬间崩到 0.2–0.5，参数抖一点就掉下去，正是过拟合。取平台左端 1.5 离悬崖留足边际。"
        "k≥2.2 还有条更宽的平台，但那里通道几乎不触发≈拿住不卖，3Y/5Y 反而更低。每次数据更新回来看这张图，平台漂了再调 k。"
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
