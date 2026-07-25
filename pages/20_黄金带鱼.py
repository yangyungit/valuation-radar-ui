import streamlit as st
import pandas as pd
import plotly.graph_objects as go

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
st.caption(
    "**策略 = 规则池本体，等权月调**：黄金阶段六道门槛（规则与逐年名单见页底）每年 12-31 PIT 重算次年生效，"
    "当年池内等权、月末再平衡，单边 200bps。回测（`backtest_golden_ribbon_round2.py`，2017-04→2026-07，Sharadar 复权价）："
    "全程 CAGR 18.5% / DD −26.3% / Calmar 0.70（SPY 14.9 / −23.9 / 0.62），3Y 25.4 / −9.2 / 2.75，5Y 14.9 / −26.3 / 0.57。"
    "**为什么不轮动**：12M 动量 Top1/2/3 × 通道留任/出池即卖 6 变体全灭（全程 CAGR −2.6%~9.8%，全跑输等权池甚至 SPY；"
    "通道 k 0→3 扫描无稳健平台）——池子六道门已按「又陡又顺」筛过，池内再押 Top-n = 抽签，且动量排名专挑刚进池的高位票"
    "（AJG −27% / SNPS −21% / FTNT −24% 的亏损段全是这么来的）。本页不做轮动、不发奖牌。"
    "**对照**：手挑 7 只静态等权 22.7 / −14.7 / 1.55 更漂亮，但那是 2026 年事后挑的十年最漂亮票，后视镜产物，图里只作对照线。"
    "**四条警告**：① 近 3Y 收益含 AI 资本开支 beta（ANET/AVGO/GWW/PWR）；"
    "② 池小（年均 10 只）且行业集中，2026 池仅 3 只，别当分散组合；"
    "③ 5Y 段只比 SPY 好一点（14.9 vs 12.7）且回撤更深（−26.3 vs −23.9），价值主要在 3Y 段和纪律性；"
    "④ 2022 池膨胀到 32 只正值市场顶部，池大小可能是过热信号，待单独验证。"
    "**净值走后端 Sharadar 复权价（与回测同源），新鲜度到上次本地价格推送为止。**"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

COST_BPS = 200.0
CASH_RATE = 0.04
HAND_GOLD = ["AAPL", "LLY", "TJX", "COST", "V", "BRK.B", "MA"]   # 仅对照线 + 页底对照表
name_map = {"AAPL": "Apple", "LLY": "Eli Lilly", "TJX": "TJX", "COST": "Costco",
            "V": "Visa", "BRK.B": "Berkshire", "MA": "Mastercard"}

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(m) for y, m in (doc.get("golden_pools") or {}).items()}
gaxes_by_y = doc.get("golden_axes") or {}
gthr = doc.get("golden_thresholds") or {}
gmeta = doc.get("meta") or {}
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

close_m = pd.DataFrame(close_d).sort_index().resample("ME").last()
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

_AXIS_COLS = ["p_r2", "p_cagr", "p_dd", "rev_r2", "rev_cagr", "ni_r2", "ni_cagr"]
_AXIS_LABEL = {"p_r2": "价格logR²", "p_cagr": "价格CAGR%", "p_dd": "价格maxDD%",
               "rev_r2": "营收logR²", "rev_cagr": "营收CAGR%", "ni_r2": "净利logR²", "ni_cagr": "净利CAGR%"}


def _axis_row(tk):
    a = gaxes.get(tk, {})
    row = {"ticker": tk, "name": gmeta.get(tk, {}).get("name", ""), "sector": gmeta.get(tk, {}).get("sector", "")}
    row.update({c: a.get(c) for c in _AXIS_COLS})
    return row, a


def _missing_axes(a: dict) -> str:
    if not a:
        return "轴缺数据"
    miss = []
    for k, thr in gthr.items():
        v = a.get(k)
        if v is None:
            miss.append(f"{_AXIS_LABEL.get(k, k)}缺数据")
        elif v < thr:
            miss.append(f"{_AXIS_LABEL.get(k, k)} {v}<{thr}")
    return " · ".join(miss) if miss else "全达标"


# ── 1. 当前持仓卡：最新生效年池等权 + 七轴详情 ──
st.markdown(f"### 📌 当前持仓（{cur_year} 年生效池，等权月调）")
cur_holdings = pools[cur_year]
if cur_holdings:
    _cols = st.columns(len(cur_holdings))
    for _c, _tk in zip(_cols, cur_holdings):
        _c.metric(_tk, f"{100.0 / len(cur_holdings):.1f}%", name_map.get(_tk, gmeta.get(_tk, {}).get("name", "")))
else:
    st.warning(f"{cur_year} 年池为空")

_cur_rows = [_axis_row(tk)[0] for tk, a in gaxes.items() if a.get("gold")]
if _cur_rows:
    st.dataframe(pd.DataFrame(_cur_rows).sort_values("p_cagr", ascending=False),
                 hide_index=True, use_container_width=True)
else:
    st.warning(f"{cur_year} 年无票过黄金阶段全部六道门槛")

st.markdown("---")

# ── 2. 净值图：等权规则池 / 手挑7静态等权 / SPY ──
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
    ("手挑7静态等权", _h, "#3498DB"),
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
st.markdown("## 📏 黄金阶段规则池（PIT 逐年重算）")
st.caption(
    "**规则**（回测定稿，出处 valuation-radar `backtest_golden_ribbon_round1.py`，commit 3704cba）："
    "基础闸门（市值≥$30B / TTM FCF>0 / 5Y 周线 CAGR≥8% / maxDD≥−45%）+ 价格 logR²≥0.90 + 价格 CAGR≥20% + "
    "maxDD≥−40% + 营收 logR²≥0.80 + 净利 CAGR≥10% + 净利 logR²≥0.60（尾部 20 个 ART 季，PIT），"
    "每年 12-31 重算次年生效。消融：纯价格 14.9%、纯基本面 11.4%——基本面轴只在陡坡端（CAGR≥20%）有增量。"
    "**手挑名单分歧是特性不是 bug**：手挑记住的是过去十年的王，规则盯的是正在王座上的——"
    "规则说 AAPL/V/MA 的黄金阶段（5Y 口径）已淡出、LLY 卡在净利 logR² 0.52<0.60。"
)

st.markdown("#### 🆚 手挑 7 只对照")
_hand_rows = []
for tk in HAND_GOLD:
    row, a = _axis_row(tk)
    row["缺哪条轴"] = _missing_axes(a)
    _hand_rows.append(row)
st.dataframe(pd.DataFrame(_hand_rows), hide_index=True, use_container_width=True)

with st.expander(f"全部候选（过基础闸门 {len(gaxes)} 只，含 near-miss）"):
    _all_rows = [dict(_axis_row(tk)[0], gold=a.get("gold", False)) for tk, a in gaxes.items()]
    _df_all = pd.DataFrame(_all_rows).sort_values("p_cagr", ascending=False)
    st.dataframe(_df_all, hide_index=True, use_container_width=True)

with st.expander("逐年池"):
    _sizes = pd.Series({y: len(pools[y]) for y in sorted(pools)})
    st.bar_chart(_sizes)
    st.caption("2022 年池膨胀到高位正值市场顶部，池大小可能是过热信号，待单独验证")
    _year_rows = [{"年": y, "n只": len(pools[y]), "名单": "、".join(pools[y])} for y in sorted(pools)]
    st.dataframe(pd.DataFrame(_year_rows), hide_index=True, use_container_width=True)
