import streamlit as st
import pandas as pd
import numpy as np

from api_client import fetch_logr2_stable_pool, fetch_gbdt_oos_prices, get_global_data

st.set_page_config(page_title="斜率进攻", layout="wide")
st.title("⚡ 斜率进攻（带鱼池 × 当前段斜率 Top2 × 通道斩仓）")
st.caption(
    "**池子**：与 FCF收益率稳定页同一个带鱼池（年度 PIT，市值≥$30B / TTM FCF>0 / 5Y CAGR≥8% "
    "且 maxDD≥-45% / 带方向 logR² 前40），只看**非科技子集**，池子零改动。"
    "**排名轴 = 当前段年化斜率**：月末在 52~260 周里找最长的仍达标（logR²≥0.70 且年化斜率≥8%）"
    "后缀窗当「当前段」，段斜率越陡排名越前；无达标段 = 无资格。"
    "**组合 = 斜率 Top2 月调 + 通道斩仓**：月末收盘 ≤ MA6×(1−0.25σ) 即斩仓，"
    "名额不顺延、空槽拿现金 4%（round8 证伪顺延接刀 -60%；round9-10 证伪深跌进场，无 alpha 且踏空主升段）。"
    "回测（round7-11，2017-04→2026-06，单边 200bps）：全程 CAGR 18.4% / DD -30.5% / Calmar 0.60"
    "（SPY 15.0% / -23.9% / 0.63），3Y 29.3% / -13.4% / 2.19，5Y 16.8% / -30.5% / 0.55，"
    "换手 1.7 次/年，常态空仓 23%。"
    "**四条警告**：① 本组合是 round7-11 20+ 形态择优（k=0.25 取平台 [0.15,0.35] 中心非孤峰），预期打折看待；"
    "② 全程 Calmar 略低于 SPY，价值在近 3Y regime 和止损纪律——这是**进攻腿**，与 FCF收益率稳定页（防守腿）互补，别当同类；"
    "③ 双票高集中且全是最陡动量票，破线月末才确认，崩盘首段 -15~-20% 跑不掉；"
    "④ 空仓 23% 是特性不是 bug：无合格陡票时拿现金，别手痒补仓。"
)

with st.sidebar:
    if st.button("🔄 强制刷新数据"):
        fetch_logr2_stable_pool.clear()
        fetch_gbdt_oos_prices.clear()
        st.rerun()

TOP_N = 2
K_STOP = 0.25
MA_W, SIG_W = 6, 12
COST = 0.02          # 单边 200bps
CASH_APY = 0.04

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

# 当前段面板：seg_panel[tk][date] = [年化斜率%, 段长周]
slope_m = pd.DataFrame({tk: pd.Series({d: v[0] for d, v in (seg_panel.get(tk) or {}).items()},
                                      dtype=float) for tk in rest})
len_m = pd.DataFrame({tk: pd.Series({d: v[1] for d, v in (seg_panel.get(tk) or {}).items()},
                                    dtype=float) for tk in rest})
slope_m.index = pd.to_datetime(slope_m.index)
len_m.index = pd.to_datetime(len_m.index)
slope_m, len_m = slope_m.sort_index(), len_m.sort_index()

memb = pd.DataFrame(False, index=slope_m.index, columns=slope_m.columns)
for y, mem in pools.items():
    memb.loc[memb.index.year == y, [t for t in mem if t in memb.columns]] = True
sc_in = slope_m.where(memb)
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
close_m = pd.DataFrame({t: s.resample("ME").last() for t, s in close_d.items()}).sort_index()
spy_m = _px["SPY"].dropna().resample("ME").last() if (_px is not None and "SPY" in _px.columns) else pd.Series(dtype=float)

# ── 斩仓线：月收盘 ≤ MA6×(1−0.25σ12) 即出局 ──
ma6 = close_m.rolling(MA_W).mean()
sig12 = close_m.pct_change(fill_method=None).rolling(SIG_W).std()
floor_m = ma6 * (1 - K_STOP * sig12)
above = close_m > floor_m

# ── 最新排名表 ──
last = sc_in.index[-1]
fl_last = floor_m.loc[:last].iloc[-1] if not floor_m.loc[:last].empty else pd.Series(dtype=float)
px_last = close_m.loc[:last].iloc[-1] if not close_m.loc[:last].empty else pd.Series(dtype=float)
cur = rank_m.loc[last].dropna().sort_values().head(15)
rows = []
for t in cur.index:
    dist = ((float(px_last.get(t)) / float(fl_last.get(t)) - 1) * 100
            if pd.notna(px_last.get(t)) and pd.notna(fl_last.get(t)) else None)
    on = dist is not None and dist > 0
    rows.append({"排名": int(cur[t]), "代码": t, "名称": (meta.get(t) or {}).get("name", t),
                 "行业": (meta.get(t) or {}).get("industry", ""),
                 "段斜率%": round(float(sc_in.at[last, t]), 1),
                 "段长(年)": round(float(len_m.at[last, t]) / 52, 1) if pd.notna(len_m.at[last, t]) else None,
                 "距斩仓线%": round(dist, 1) if dist is not None else None,
                 "持仓": "✅" if (cur[t] <= TOP_N and on) else ("⛔破线" if cur[t] <= TOP_N else "")})
st.markdown(f"## ⚡ 非科技 当前段斜率排名（{last.date()}，池 {int(memb.loc[last].sum())} 只）")
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ── 等权净值（月调，Top2 且在通道上方；破线斩仓不顺延，空槽现金 4%）──
ret_m = close_m.pct_change(fill_method=None)

def ew_nav(sel: pd.DataFrame) -> pd.Series:
    """与 page 8 同款：持仓槽等权、空槽现金。Top2 曲线的空槽现金即「斩仓不顺延」。"""
    w_raw = sel.reindex(index=ret_m.index, columns=ret_m.columns).fillna(False).astype(float)
    w = w_raw.div(w_raw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    cash_w = (1 - w.sum(axis=1)).clip(lower=0.0)
    port = (w.shift(1) * ret_m).sum(axis=1) + cash_w.shift(1).fillna(0) * (CASH_APY / 12)
    turn = (w - w.shift(1)).abs().sum(axis=1) * 0.5
    return (1 + port - turn * COST).cumprod()

memb_px = (memb & sc_in.notna()).reindex(index=ret_m.index).fillna(False)
above_px = above.reindex(index=ret_m.index, columns=memb_px.columns).fillna(False)
rank_px = rank_m.reindex(index=ret_m.index)
nav2 = ew_nav((rank_px <= TOP_N) & above_px & memb_px)
nav_all = ew_nav(memb_px)
lo = close_m.index[-1] - pd.DateOffset(years=int(window[:-1]))
chart = pd.DataFrame({"斜率Top2+斩仓": nav2, "等权全池": nav_all, "SPY": spy_m})
chart = chart[chart.index >= lo].dropna(how="all")
chart = chart / chart.iloc[0]
st.markdown("## 📈 斜率 Top2 + 通道斩仓 vs 全池 vs SPY")
st.line_chart(chart)

# ── 逐年收益 ──
def yearly(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s.groupby(s.index.year).apply(lambda t: (float(t.iloc[-1]) / float(t.iloc[0]) - 1) * 100).round(1)

st.markdown("## 📅 逐年收益%")
st.dataframe(pd.DataFrame({"斜率Top2+斩仓": yearly(nav2[nav2.index >= lo]),
                           "等权全池": yearly(nav_all[nav_all.index >= lo]),
                           "SPY": yearly(spy_m[spy_m.index >= lo])}),
             use_container_width=True)
