import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data

st.set_page_config(page_title="logR²稳定", layout="wide")
st.title("📈 logR² 稳定（带鱼池 × 滚动 5Y logR² 排名）")
st.caption(
    "**池子**：年度 PIT 价格行为池——市值≥$30B / TTM FCF>0 / 近5Y周线 CAGR≥8% 且 maxDD≥-45% / "
    "按带方向 logR²（log价格对时间回归 R²×斜率符号）前40，每年12月末重构次年生效（本地 Sharadar 构建上传）。"
    "页面只看**非科技子集**。**排名轴 = 月末滚动 260 周带方向 logR²**——衡量『价格像不像一条直线向上』，"
    "与基本面无关。**组合 = 等权 Top10 月末调仓**（无金银牌、无 MA 择时：回测双槽接力引擎在带鱼池上"
    "全面跑输，等权篮子才成立，见 backtest_logr2_stable_round1/2.py）。"
    "回测（2017-04→2026-06，单边 200bps）：等权 Top10 全程 CAGR 10.6% / DD -24.5%，"
    "尾部 3Y CAGR 18.0% / DD -6.6% / Calmar 2.74（SPY 20.5% / -16.9% / 1.22）。"
    "**定性 = 防守腿**：全程收益跑输 SPY（15.0%），价值在回撤减半；"
    "敏感度 Top5/15/全池 全程 CAGR 13.0/10.2/11.4%。"
    "**警告**：2026 池被中游能源（MPLX/EPD/ET/WMB/TRGP）挤入——管道收租生意 logR² 天然高，"
    "行业集中需人工过目，别当黑箱信。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

TOP_N = 10
COST = 0.02          # 单边 200bps
CASH_APY = 0.04

doc = fetch_logr2_stable_pool()
if not doc.get("success"):
    st.error(f"⚠️ 数据暂不可用：{doc.get('error', '未知错误')}")
    st.stop()

pools = {int(y): list(mem) for y, mem in (doc.get("pools") or {}).items()}
meta = doc.get("meta") or {}
panel = doc.get("logr2_panel") or {}
built = pd.to_datetime(doc.get("built_at"), errors="coerce", utc=True)
if pd.notna(built) and (pd.Timestamp.now(tz="UTC") - built).days > 40:
    st.warning(f"⚠️ 数据已 {(pd.Timestamp.now(tz='UTC') - built).days} 天未重建"
               "（本地跑 build_logr2_stable_pool.py 并上传后排名才会更新）")

union = sorted({t for mem in pools.values() for t in mem})
rest = [t for t in union if not (meta.get(t) or {}).get("is_tech")]

# logR2 月末面板（构建时已是月末值）
score_m = pd.DataFrame({tk: pd.Series(panel.get(tk) or {}, dtype=float) for tk in rest})
score_m.index = pd.to_datetime(score_m.index)
score_m = score_m.sort_index()

memb = pd.DataFrame(False, index=score_m.index, columns=score_m.columns)
for y, mem in pools.items():
    memb.loc[memb.index.year == y, [t for t in mem if t in memb.columns]] = True
score_in = score_m.where(memb)
rank_m = score_in.rank(axis=1, ascending=False, method="min")

# ── 最新排名表 ──
last = score_in.index[-1]
cur = rank_m.loc[last].dropna().sort_values().head(15)
rows = [{"排名": int(cur[t]), "代码": t, "名称": (meta.get(t) or {}).get("name", t),
         "行业": (meta.get(t) or {}).get("industry", ""),
         "logR²": round(float(score_in.at[last, t]), 3),
         "Top10": "✅" if cur[t] <= TOP_N else ""} for t in cur.index]
st.markdown(f"## 🏛️ 非科技带鱼排名（{last.date()}，池 {int(memb.loc[last].sum())} 只）")
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ── 价格（yfinance + Sharadar 补缺，BRK.B 走别名）──
_ALIAS = {"BRK.B": "BRK-B"}
window = st.radio("时间跨度", ["3Y", "5Y", "10Y"], index=2, horizontal=True, key="logr2_window")
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
close_m = pd.DataFrame({t: s.resample("ME").last() for t, s in close_d.items()}).sort_index()
spy_m = _px["SPY"].dropna().resample("ME").last() if (_px is not None and "SPY" in _px.columns) else pd.Series(dtype=float)

# ── 等权净值（月调，成本=单边换手×200bps，空位现金 4%）──
ret_m = close_m.pct_change(fill_method=None)

def ew_nav(sel: pd.DataFrame) -> pd.Series:
    w_raw = sel.reindex(index=ret_m.index, columns=ret_m.columns).fillna(False).astype(float)
    w = w_raw.div(w_raw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    cash_w = (1 - w.sum(axis=1)).clip(lower=0.0)
    port = (w.shift(1) * ret_m).sum(axis=1) + cash_w.shift(1).fillna(0) * (CASH_APY / 12)
    turn = (w - w.shift(1)).abs().sum(axis=1) * 0.5
    return (1 + port - turn * COST).cumprod()

memb_px = memb & score_in.notna()
nav10 = ew_nav((rank_m <= TOP_N) & memb_px)
nav_all = ew_nav(memb_px)
lo = close_m.index[-1] - pd.DateOffset(years=int(window[:-1]))
chart = pd.DataFrame({"等权Top10": nav10, "等权全池": nav_all, "SPY": spy_m})
chart = chart[chart.index >= lo].dropna(how="all")
chart = chart / chart.iloc[0]
st.markdown("## 📈 等权 Top10 月调 vs 全池 vs SPY")
st.line_chart(chart)

# ── 逐年收益 ──
def yearly(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s.groupby(s.index.year).apply(lambda t: (float(t.iloc[-1]) / float(t.iloc[0]) - 1) * 100).round(1)

st.markdown("## 📅 逐年收益%")
st.dataframe(pd.DataFrame({"等权Top10": yearly(nav10[nav10.index >= lo]),
                           "等权全池": yearly(nav_all[nav_all.index >= lo]),
                           "SPY": yearly(spy_m[spy_m.index >= lo])}),
             use_container_width=True)
