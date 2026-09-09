import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import holdings_viz as hv
from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices

st.set_page_config(page_title="黄金带鱼", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #FFD700; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #FFD700; font-size: 18px; margin-bottom: 10px; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🥇 黄金带鱼（规则池等权月调）")
st.error(
    "⚠️ **这套规则只在 2016-2026 这一段验证过，搬到样本外不成立**（round10/11/12，2026-09-09）。"
    "同一套规则跑 2003-2015：CAGR −1.8% / DD −60.6% / Calmar −0.03，"
    "全程 2003-2026 是 6.5 / −60.6 / 0.11，**跑输 SPY 的 11.4 / −50.8 / 0.23**。"
    "失效方式很具体：2007-12-31 判 BEN（资管）+ CAT（工程机械）进入黄金阶段，2008 年当年 −36.5%；"
    "2009-2012 连续四年零合格票，全程空仓错过复苏。**合格票数本身是反向指标**——"
    "2007/2008 月均 6.8/7.8 只（顶部最多），2009-2012 归零（底部最少），2021 冲到 17.4。"
    "三条修补路都试过都不成立：① 改价格窗长度（3/4/6 年样本外 Calmar 0.14/0.09/0.14，全低于 SPY 0.17）；"
    "② 把净利增速门换成营收增速门（全程 0.04~0.09，不如现行净利门的 0.11）；"
    "③ 改成「合格就一直拿、不合格才换人、青黄不接就空仓」（5 年窗下全程 0.30 看着最好，"
    "但把 2000-2002 科技熊补进样本、价格窗换成 3 年，同一段就从 0.27 掉到 0.01、反而输给现行规则）。"
    "**下面所有回测数字都是 2015-12→2026-06 这一段的，别当成全周期检验。**"
)
st.caption(
    "**策略 = 规则池本体，等权月调**：黄金阶段六道门槛（规则与逐年名单见页底）每年 12-31 PIT 重算次年生效，"
    "要求 3-31/6-30/9-30/12-31 **四个季末全部达标**才算候选（只闪现过一两季的不要），"
    "再**排掉科技票、按近 4 年最大回撤最浅取 2 只**，当年等权、月末再平衡，单边 200bps。"
    "回测（`backtest_golden_ribbon_round8.py`，2015-12→2026-06，Sharadar 复权价）："
    "全程 CAGR 18.6% / DD −16.9% / Calmar 1.10（SPY 15.1 / −23.9 / 0.63），3Y 31.8 / −10.2 / 3.12，5Y 20.8 / −10.2 / 2.03。"
    "**为什么加这两道后处理**（round8）：不加时池均 5.2、2022 年膨胀到 17 只，全程 0.82。"
    "只排科技 = 0.97（少赚 0.9pp 换回撤浅 4.7pp）；再取 2 只 = 1.10。"
    "**砍到几只不重要，按什么排序砍才重要**：同样砍到 2 只，按字母序（等于抽签）全程 Calmar 只有 0.37、"
    "砍到 3 只是 0.45，都远低于不砍的 0.82——无脑砍人纯亏分散度，改善全靠排序键把好票留下。"
    "**排序键选回撤不选价格 CAGR**：价格 CAGR 在取 3 只时冲到全表最高的 1.43，但取 2/4/5/6 只是 0.96/1.19/0.97/0.84，"
    "单点尖峰；回撤在取 2~6 只是 1.09/1.10/0.91/0.99/0.92，一整片高原。价格 logR² 和净利 CAGR 两个键全线 0.4~0.9。"
    "**两个改动叠加没有加成**：排科技 + 取 2 只 = 1.10，不排科技只取 2 只 = 1.09，一样——"
    "按坑最浅排本来就把高波动科技票排到后面了，排科技是主理人的口味约束，不是它还能再加分。"
    "**为什么要四季全达标**（round5）：只看 12-31 一天是 18.7 / −26.3 / 0.71，CAGR 高 0.9pp 但回撤深 2.6pp；"
    "放宽成「四季至少 1/2/3 次达标」全部更差（Calmar 0.48 / 0.51 / 0.58）——放宽等于把闪现票收进来稀释。"
    "**为什么回撤门只看近 4 年**（round6）：原来六道门里的 maxDD 也在 5 年窗上算，"
    "结果 2020 疫情那个坑要到 2025 年才滚出窗外，一批票被五年前的老坑一票否决。"
    "改成只看近 4 年（其余五道门和 logR²/CAGR 的 5 年窗全不动）：全程 Calmar 0.75 → 0.82、近 3Y 回撤 −21.9% → −12.5%。"
    "「2/3/4 年窗 × 门槛 −35/−40/−45」这 9 格的 Calmar 全在 0.72~0.82 且名单完全相同，是一整片稳健区不是尖峰；"
    "门槛收到 −25/−30 则全线崩到 0.30~0.70，所以不是越松越好。"
    "**换名单频率与价格窗口都扫过**（round5）：每年换 18.7 / 0.71 完胜每半年 15.9 / 每季 12.1 / 每月 11.6"
    "（三根价格轴是滞后指标，跌完才踢 = 在底部卖）；价格窗口 5 年是峰值，3 年窗崩到 8.3 / 0.27。"
    "**这条「5 年是峰值」只在 2016-2026 段成立**（round11）：拉到 2003-2015 重扫，"
    "5 年窗是四档里唯一负收益的（Calmar −0.03），3/4/6 年窗是 0.14/0.09/0.14——同样全低于 SPY 0.17，"
    "换窗口长度救不了。round12 还发现窗口缩到 3 年会在 2004-08 买进 EBAY"
    "（2001-2004 从科技股废墟上平滑暴涨三年，5 年窗因含 2000-2001 崩盘筛不进来），次年 −44%；"
    "**5 年窗不是「太长」而是「还不够长」**。"
    "**中途换人三条路全灭**（round6）：名单改按季滚动 CAGR 13.4 / Calmar 0.46、掉出就把仓位给剩下的 12.7 / 0.56、"
    "掉出就按 logR² 补齐 13.9 / 0.59，全部远差于锁一年——SNPS 2024-12-31 的 logR² 正好 0.900 压线过门、"
    "2025-01 就掉出，但它之后又涨了半年（1 月底 525 → 7 月底 633）才在 9-11 月崩，"
    "按报警换人 = 卖在上涨起点，且当时能换进来的 AJG（全年 −8.0%）/ MSI（−16.2%）比 SNPS（−3.2%）更差。"
    "**为什么不按动量轮动**（round2）：12M 动量 Top1/2/3 × 通道留任/出池即卖 6 变体全灭"
    "（全程 CAGR −2.6%~9.8%，全跑输等权池甚至 SPY；通道 k 0→3 扫描无稳健平台）——"
    "动量排名专挑刚进池的高位票（AJG −27% / SNPS −21% / FTNT −24% 的亏损段全是这么来的）。"
    "现在的 Top2 按的是**回撤最浅**不是动量，方向正好相反。本页仍不发奖牌、年内不换人。"
    "**对照**：手挑 4 只（AAPL/LLY/TJX/COST）静态等权 25.8 / −14.1 / 1.84 更漂亮，但那是 2026 年事后挑的十年最漂亮票，"
    "后视镜产物，图里只作对照线。原来的手挑 7 只多了 V/BRK.B/MA 三只金融，同引擎同窗口只有 22.2 / −14.7 / 1.51——"
    "三只挤在同一行业不提供分散（`backtest_quality_seven.py` 留一法：去掉 MA / BRK.B / V 分别 +0.23 / +0.19 / +0.16 Calmar），已删。"
    "**四条警告**：① **每年只有 2 只，集中度是本页最大风险**，绝不是分散组合；"
    "2025 年 SNPS 崩盘那种单票事故，现在只有一只票分摊（老口径那年 4 只、当年 +5.3%，新口径 AZO+GWW 当年 +4.9%）；"
    "② 差距高度集中在 2022 一年——新口径拿 PGR+TMO 当年 +1.9%，老口径拿 17 只 −16.5%，"
    "换一段样本这一年的运气就没了；11 年只有 11 个年度决策，48 个变体里挑最好的，过拟合风险照旧；"
    "③ 近 3Y 收益含 AI 资本开支 beta（GWW/PWR）；"
    "④ 规则 2026-09-08 起连改三处（「只看 12-31」→「四季全达标」、回撤门 5 年窗 → 4 年窗、排科技 + 取 2 只），"
    "属**年中换规则**；三次改完 2026 名单都还是 GWW/PWR 各 50%，持仓不受影响，"
    "但回测覆盖的是每年年初按规则建仓，年中切换不在回测范围内。"
    "**净值走后端 Sharadar 复权价（与回测同源），新鲜度到上次本地价格推送为止。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

COST_BPS = 200.0
CASH_RATE = hv.CASH_APY
HAND_GOLD = ["AAPL", "LLY", "TJX", "COST"]   # 仅对照线 + 页底对照表
name_map = {"AAPL": "Apple", "LLY": "Eli Lilly", "TJX": "TJX", "COST": "Costco"}
# 后端 sector 字段是英文原名，仅展示时换中文简称（与 holdings_viz._SECTOR_CN 同一套词）
SECTOR_CN = {
    "Technology": "科技", "Industrials": "工业", "Healthcare": "医疗",
    "Financial Services": "金融", "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必选消费", "Communication Services": "通讯服务",
    "Energy": "能源", "Basic Materials": "原材料",
    "Real Estate": "房地产", "Utilities": "公用事业",
}

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(m) for y, m in (doc.get("golden_pools") or {}).items()}
gaxes_by_y = doc.get("golden_axes") or {}
gthr = doc.get("golden_thresholds") or {}
gmeta = doc.get("meta") or {}
top_n = int(doc.get("golden_top_n") or 2)
if not pools or not gaxes_by_y or not gthr:
    st.info("规则池未就绪（本地重跑 build_logr2_stable_pool.py 并上传后生效）")
    st.stop()

built = pd.to_datetime(doc.get("built_at"), errors="coerce", utc=True)
if pd.notna(built) and (pd.Timestamp.now(tz="UTC") - built).days > 40:
    st.warning(f"⚠️ 数据已 {(pd.Timestamp.now(tz='UTC') - built).days} 天未重建"
               "（本地跑 build_logr2_stable_pool.py 并上传后排名才会更新）")

union = sorted({t for m in pools.values() for t in m})
cur_year = max(pools)
gaxes = gaxes_by_y.get(str(cur_year), {})

# ── 净值一律走后端 Sharadar 复权价，与回测同源（data-consistency.mdc 红线，不用 yfinance 画净值）──
with st.spinner("📊 加载价格（Sharadar 复权）..."):
    _raw = fetch_gbdt_oos_prices(tuple(sorted(set(union + HAND_GOLD + ["SPY"]))))
close_d = {}
for t, rows in (_raw or {}).items():
    if rows:
        arr = pd.DataFrame(rows, columns=["date", "o", "h", "l", "c", "v"])
        close_d[t] = arr.assign(date=pd.to_datetime(arr["date"])).set_index("date")["c"].astype(float)
_missing = [t for t in sorted(set(union + HAND_GOLD + ["SPY"])) if t not in close_d]
if _missing:
    st.warning(f"⚠️ 价格缓存缺票：{_missing}（本地 push_local_to_render --tables gbdt_oos_prices 后消失）")

close_all = pd.DataFrame(close_d).sort_index()
close_m = close_all.resample("ME").last()
ret_m = close_m.pct_change(fill_method=None)


def _ew_nav(members_by_month) -> pd.Series:
    """members_by_month: {月末Timestamp: [tk]}。月末决策次月执行，等权、单边 200bps、空池现金 4%。"""
    w = pd.DataFrame(0.0, index=list(members_by_month), columns=close_m.columns)
    for d, mem in members_by_month.items():
        ok = [t for t in mem if t in close_m.columns and pd.notna(close_m.at[d, t])]
        for t in ok:
            w.at[d, t] = 1.0 / len(ok) if ok else 0.0
    cash = (1 - w.sum(axis=1)).clip(lower=0.0)
    port = (w.shift(1) * ret_m.reindex(w.index)).sum(axis=1) + cash.shift(1).fillna(1.0) * CASH_RATE / 12
    turn = (w - w.shift(1)).abs().sum(axis=1) * 0.5
    return (1 + port - turn * COST_BPS / 10000).cumprod()


_months = [d for d in close_m.index if d.year in pools]
nav_pool = _ew_nav({d: pools[d.year] for d in _months})
nav_hand = _ew_nav({d: HAND_GOLD for d in _months})
nav_spy = _ew_nav({d: ["SPY"] for d in _months})

if nav_pool.dropna().empty:
    st.error("⚠️ 规则池净值不可用（价格缺失过多），无法展示")
    st.stop()

_QUARTERS = ("03-31", "06-30", "09-30", "12-31")   # 四季全达标才进池，后端 round5 定稿
_AXIS_COLS = ["p_r2", "p_cagr", "p_dd", "rev_r2", "rev_cagr", "ni_r2", "ni_cagr"]
_AXIS_LABEL = {"p_r2": "价格logR²", "p_cagr": "价格CAGR%", "p_dd": "价格近4Y maxDD%",
               "rev_r2": "营收logR²", "rev_cagr": "营收CAGR%", "ni_r2": "净利logR²", "ni_cagr": "净利CAGR%"}


def _axis_row(tk):
    a = gaxes.get(tk, {})
    _sec = gmeta.get(tk, {}).get("sector", "")
    row = {"ticker": tk, "name": gmeta.get(tk, {}).get("name", ""),
           "sector": SECTOR_CN.get(_sec, _sec),
           "四季达标": f"{a.get('q_pass', 0)}/4"}
    row.update({c: a.get(c) for c in _AXIS_COLS})
    return row, a


def _cut_reason(tk: str, a: dict) -> str:
    """四季全达标之后为什么没进池——科技被排掉，还是回撤排名不够前 2。"""
    if a.get("picked"):
        return "进池"
    if a.get("is_tech") or gmeta.get(tk, {}).get("is_tech"):
        return "科技票，排除"
    return f"回撤排名不进前 {top_n}"


def _missing_axes(tk: str, a: dict) -> str:
    """七轴只有 12-31 那季的值，六道门全过也可能因为别的季度掉链子而不进池。"""
    if not a:
        return "轴缺数据"
    miss = []
    for k, thr in gthr.items():
        v = a.get(k)
        if v is None:
            miss.append(f"{_AXIS_LABEL.get(k, k)}缺数据")
        elif v < thr:
            miss.append(f"{_AXIS_LABEL.get(k, k)} {v}<{thr}")
    if miss:
        return " · ".join(miss)
    q = a.get("q_pass", 0)
    if q < len(_QUARTERS):
        return f"12-31 六道门全过，但四季只达标 {q}/4"
    return "全达标 · " + _cut_reason(tk, a)


# ── 1. 当前持仓卡：最新生效年池等权 + 七轴详情 ──
st.markdown(f"### 📌 当前持仓（{cur_year} 年生效池，等权月调）")
cur_holdings = pools[cur_year]
if cur_holdings:
    _cols = st.columns(len(cur_holdings))
    for _c, _tk in zip(_cols, cur_holdings):
        _c.metric(_tk, f"{100.0 / len(cur_holdings):.1f}%", name_map.get(_tk, gmeta.get(_tk, {}).get("name", "")))
else:
    st.warning(f"{cur_year} 年池为空")

_cur_rows = [dict(_axis_row(tk)[0], 是否进池=_cut_reason(tk, a))
             for tk, a in gaxes.items() if a.get("gold")]
if _cur_rows:
    st.dataframe(pd.DataFrame(_cur_rows).sort_values("p_dd", ascending=False),
                 hide_index=True, use_container_width=True)
    st.caption(f"表里是 {cur_year} 年四个季末全部过六道门槛的票，按近 4Y maxDD 从浅到深排；"
               f"排掉科技票后取前 {top_n} 只进池，其余列出来看差在哪。")
else:
    st.warning(f"{cur_year} 年无票四个季末全部过六道门槛")

st.markdown("---")

# ── 2. 净值图：等权规则池 / 手挑4静态等权 / SPY ──
window = st.radio("时间跨度", ["3Y", "5Y", "10Y"], index=2, horizontal=True, key="gold_window")
_last = nav_pool.index.max()
_lo = _last - pd.DateOffset(years=int(window[:-1]))


def _slice(nav: pd.Series) -> pd.Series:
    s = nav[nav.index >= _lo].dropna()
    return s


def _rebase(nav: pd.Series) -> pd.Series:
    s = _slice(nav)
    return s / float(s.iloc[0]) if not s.empty else s


def _kpi(nav: pd.Series) -> dict:
    s = _slice(nav)
    if len(s) < 6:
        return {"cagr": float("nan"), "dd": float("nan"), "calmar": float("nan")}
    years = len(s) / 12.0
    cagr = (float(s.iloc[-1]) / float(s.iloc[0])) ** (1.0 / years) - 1.0
    peak = s.cummax()
    max_dd = abs(float((s / peak - 1.0).min()))
    calmar = cagr / max_dd if max_dd > 1e-9 else float("nan")
    return {"cagr": cagr, "dd": max_dd, "calmar": calmar}


_p, _h, _s = _rebase(nav_pool), _rebase(nav_hand), _rebase(nav_spy)
fig = go.Figure()
for _lbl, _series, _color in [
    ("等权规则池", _p, "#FFD700"),
    ("手挑4静态等权", _h, "#3498DB"),
    ("SPY", _s, "rgba(170,170,170,0.7)"),
]:
    if _series.empty:
        continue
    _name = f"{_lbl} {(float(_series.iloc[-1]) - 1) * 100:+.1f}%"
    fig.add_trace(go.Scatter(x=_series.index, y=_series.values, mode="lines", name=_name,
                              line=dict(color=_color, width=2.4 if _lbl == "等权规则池" else 1.6)))
fig.update_layout(
    title=f"黄金带鱼净值 · {window} · 起点归一 = 1",
    xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
    yaxis=dict(title="NAV（对数）", type="log", gridcolor="rgba(100,100,100,0.3)"),
    height=480, margin=dict(l=10, r=10, t=44, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
    font=dict(color="#ccc", size=13), showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
)
st.plotly_chart(fig, use_container_width=True, key="gold_nav")

_kpi_pool = _kpi(nav_pool)
_m1, _m2, _m3 = st.columns(3)
_m1.metric(f"CAGR（{window}）", f"{_kpi_pool['cagr'] * 100:+.1f}%" if _kpi_pool["cagr"] == _kpi_pool["cagr"] else "N/A")
_m2.metric(f"maxDD（{window}）", f"{-_kpi_pool['dd'] * 100:.1f}%" if _kpi_pool["dd"] == _kpi_pool["dd"] else "N/A")
_m3.metric(f"Calmar（{window}）", f"{_kpi_pool['calmar']:.2f}" if _kpi_pool["calmar"] == _kpi_pool["calmar"] else "N/A")
st.caption("统计卡为「等权规则池」曲线按当前选中窗口切段计算（月线 NAV）。")

st.markdown("---")

# ── 3. 左右列接力：每年 2 只，拆成两槽看哪只票扛了哪一段 ──
st.markdown("### 🎞️ 左列 / 右列接力")
st.caption(
    "每年 2 只，拆成左右两槽：上月在某槽的票今年还在池里就留原槽，换人才换色带"
    "（HD 在右槽 2016-02→2019-01 连拿 3 年，TMO 左槽连拿 2 年）。"
    "名单 12-31 定、延迟一个月生效（与 `backtest_golden_ribbon_round5.py` 的 `by_year` 同口径），"
    "所以色带从当年 2 月起算，2016-01 是空仓。"
    "**再平衡时点**：合成线上每一个点 = 一个月末，那一刻两只票削回 50/50；"
    "灰竖线 = 每年 2 月换名单生效（卖旧买新）。年内漂移不大——月末削回前的偏离中位只有 2.0pp、"
    "最高 10.9pp（2026-04 GWW 44.5% / PWR 55.5%），逐月实际权重见下方展开表。"
    "各槽净值是**周线单票口径**（段内不动，换票时卖出 + 买入各扣 200bps），只作归因，"
    "不是你的实际仓位路径；实际路径是「合成」那条月线等权再平衡曲线（与回测同源）。"
    "两条差 135pp，但**不是月度削回的功劳**：同一份月线价格上把「每月末削回」换成「只在换名单时重置」，"
    "全程从 +458.5% 只掉到 +449.6%（年内最多漂到 60/40，一年重置一次就够）。"
    "差距主要在成本口径——槽位图每次换票卖 200 + 买 200 各扣一次，比月线引擎多一倍："
    "同样从不重置，换票免费是 +525.5%、双边 400bps 只剩 +379.2%。本节固定看全程。"
)

_wk = close_all.resample("W-FRI").last()
_spy_wk = (_wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
           if "SPY" in _wk.columns else pd.DataFrame())
_pc = {t: _wk[t].dropna().to_frame("Close") for t in union
       if t in _wk.columns and _wk[t].notna().sum() >= 2}
# 执行月的持仓 = 上一个月末生效的年池（对齐 _ew_nav 里的 w.shift(1)）
_exec_months = [d.strftime("%Y-%m") for d in _months]
_slots = hv.build_basket_slot_assignments(
    {d.strftime("%Y-%m"): pools.get(d.year if d.month > 1 else d.year - 1, []) for d in _months},
    _exec_months,
)
_nm = {t: gmeta.get(t, {}).get("name", t) for t in union}
_slot_segs = [hv.build_slot_segments(_slots, si, _exec_months) for si in range(2)]
_slot_navs = [(lbl, hv.calc_slot_stats(seg, _pc, _spy_wk, CASH_RATE, COST_BPS)[2])
              for lbl, seg in zip(("左列", "右列"), _slot_segs)]

st.plotly_chart(
    hv.build_relay_gantt(_slots, _exec_months, _nm,
                         title="黄金带鱼左右列 · 持仓时间条带",
                         track_labels=("左列 · Slot 0", "右列 · Slot 1")),
    use_container_width=True, key="gold_gantt",
)
_fig_c = hv.build_combined_fig_n(_slot_navs, nav_pool, _spy_wk,
                                 "黄金带鱼 — 左右列各自净值 vs 月线等权合成 vs SPY")
# 合成线每个点 = 一个月末再平衡时刻；竖线 = 换名单生效月
for _tr in _fig_c.data:
    if str(_tr.name).startswith("合成"):
        _tr.mode = "lines+markers"
        _tr.marker = dict(size=4, color="#F1C40F")
        _tr.hovertemplate = "%{x|%Y-%m} 月末再平衡<br>NAV %{y:.2f}<extra></extra>"
for _y in sorted(pools):
    _x = pd.Timestamp(f"{_y}-02-01")
    if nav_pool.index.min() <= _x <= nav_pool.index.max():
        _fig_c.add_vline(x=_x, line=dict(color="rgba(150,150,150,0.35)", width=1, dash="dot"),
                         annotation_text=str(_y), annotation_position="top",
                         annotation_font=dict(size=9, color="#999"))
st.plotly_chart(_fig_c, use_container_width=True, key="gold_slot_combined")

_drift = []
for _i, _d in enumerate(_months):
    _held = pools.get(_months[_i - 1].year, []) if _i > 0 else []
    if len(_held) != 2:
        continue
    _a, _b = _held
    _ra, _rb = ret_m.at[_d, _a], ret_m.at[_d, _b]
    if pd.isna(_ra) or pd.isna(_rb):
        continue
    _wa = 0.5 * (1 + _ra) / (0.5 * (1 + _ra) + 0.5 * (1 + _rb))
    _drift.append({
        "月末": _d.strftime("%Y-%m"),
        "持仓": f"{_a} / {_b}",
        "削回前权重": f"{_wa * 100:.1f}% / {(1 - _wa) * 100:.1f}%",
        "偏离": f"{abs(_wa - 0.5) * 200:.1f}pp",
        "事件": "🔄 新名单第一个月" if _d.month == 2 else "",
    })
with st.expander(f"逐月实际仓位（{len(_drift)} 个月末，倒序）"):
    st.caption("「削回前权重」= 该月两只票走完之后、月末再平衡之前的实际占比，"
               "月末一律削回 50/50。偏离大 = 那个月两只票走势分岔得厉害。")
    st.dataframe(pd.DataFrame(_drift).iloc[::-1], hide_index=True, use_container_width=True)
for _si, (_lbl, _) in enumerate(_slot_navs):
    st.plotly_chart(
        hv.build_stitched_fig(_slot_segs[_si], f"黄金带鱼 {_lbl} (Slot {_si})",
                              _spy_wk, _pc, _nm, cost_bps=COST_BPS),
        use_container_width=True, key=f"gold_slot_{_si}",
    )

st.markdown("---")
st.markdown("## 📏 黄金阶段规则池（PIT 逐年重算）")
st.caption(
    "**规则**（阈值出处 valuation-radar `backtest_golden_ribbon_round1.py` commit 3704cba，"
    "四季全达标出处 `round5`，回撤门改 4 年窗出处 `round6`，排科技 + 取 2 只出处 `round8`）："
    "基础闸门（市值≥$30B / TTM FCF>0 / 5Y 周线 CAGR≥8% / 5Y maxDD≥−45%）+ 价格 logR²≥0.90（5Y）+ 价格 CAGR≥20%（5Y）+ "
    "**近 4Y maxDD≥−40%** + 营收 logR²≥0.80 + 净利 CAGR≥10% + 净利 logR²≥0.60（尾部 20 个 ART 季，PIT），"
    "且 3-31/6-30/9-30/12-31 **四个季末全部达标**；再**排掉科技票**（Sharadar sector = Technology，"
    "或 industry = Internet Content & Information，GOOGL 这类归科技）、"
    f"**按近 4Y maxDD 最浅取 {top_n} 只**。名单仍每年 12-31 定、次年生效。"
    "下表七轴是 12-31 那季的值，「四季达标」列记四季里过了几次——WAB 这类 12-31 六道门全过但只有 3/4 的，不算候选。"
    "消融：纯价格 14.9%、纯基本面 11.4%——基本面轴只在陡坡端（CAGR≥20%）有增量。"
    "**手挑名单分歧是特性不是 bug**：手挑记住的是过去十年的王，规则盯的是正在王座上的——"
    "规则说 AAPL 的黄金阶段（5Y 口径）已淡出（价格 logR² 0.816<0.90）、LLY 卡在净利 logR² 0.52<0.60、"
    "TJX 净利 logR² 0.40、COST 价格 logR² 0.886 差一点。"
)

st.markdown("#### 🆚 手挑 4 只对照")
_hand_rows = []
for tk in HAND_GOLD:
    row, a = _axis_row(tk)
    row["缺哪条轴"] = _missing_axes(tk, a)
    _hand_rows.append(row)
st.dataframe(pd.DataFrame(_hand_rows), hide_index=True, use_container_width=True)

with st.expander(f"全部候选（12-31 过基础闸门 {len(gaxes)} 只，含 near-miss）"):
    _all_rows = [dict(_axis_row(tk)[0], 四季全达标=a.get("gold", False),
                      进池=a.get("picked", False), _q=a.get("q_pass", 0))
                 for tk, a in gaxes.items()]
    _df_all = (pd.DataFrame(_all_rows).sort_values(["_q", "p_dd"], ascending=False)
               .drop(columns="_q"))
    st.dataframe(_df_all, hide_index=True, use_container_width=True)

with st.expander("逐年池"):
    st.caption(f"排科技 + 取前 {top_n} 只之后每年固定 2 只。"
               "改规则前是 7/3/3/3/6/5/17/5/2/4/2（池均 5.2），2022 那 17 只正值市场顶部——"
               "候选池膨胀可能是过热信号，现在被 Top2 截断后这个信号从名单上看不见了")
    _year_rows = [{"年": y, "n只": len(pools[y]), "名单": "、".join(pools[y])} for y in sorted(pools)]
    st.dataframe(pd.DataFrame(_year_rows), hide_index=True, use_container_width=True)
