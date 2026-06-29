import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from api_client import fetch_fundamentals_manifest, fetch_fundamentals

st.set_page_config(page_title="基本面长图", layout="wide", page_icon="📈")
st.title("📈 基本面长图（ROIC / Rule40 / 利润率 / EPS / FCF / 营收 vs 股价）")
st.caption("数据源：Sharadar SF1 (ART/TTM, PIT datekey) + SEP closeadj。仅含已 push 的关注股。")

with st.sidebar:
    if st.button("🔄 清除缓存"):
        fetch_fundamentals_manifest.clear(); fetch_fundamentals.clear(); st.rerun()

mani = fetch_fundamentals_manifest()
tickers = mani.get("tickers", [])
if not tickers:
    st.warning("尚无基本面数据。请本地跑 push_fundamentals_to_render.py 推送关注股。")
    st.stop()

opts = [f"{t['ticker']}  |  {t.get('name','')}" for t in tickers]
sel = st.selectbox("选择标的", opts)
tk = sel.split("  |  ")[0].strip()

resp = fetch_fundamentals(tk)
if not resp.get("success"):
    st.error(f"读取 {tk} 失败：{resp.get('error')}"); st.stop()
d = resp["data"]; f = d["fundamentals"]; px = d["price"]
fi = pd.to_datetime(f["datekey"]); pdt = pd.to_datetime(px["date"])

show_margin = st.checkbox("叠加净利率 / 毛利率", value=False)

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Scatter(x=fi, y=f["roic_pct"], name="ROIC %", line=dict(color="#1f6fb4", width=2)), secondary_y=False)
fig.add_trace(go.Scatter(x=fi, y=f["rule40"], name="Rule of 40 %", line=dict(color="#d62728", width=2)), secondary_y=False)
if show_margin:
    fig.add_trace(go.Scatter(x=fi, y=f["net_margin"], name="净利率 %", line=dict(color="#2ca02c", width=1.4)), secondary_y=False)
    fig.add_trace(go.Scatter(x=fi, y=f["gross_margin"], name="毛利率 %", line=dict(color="#9467bd", width=1.4)), secondary_y=False)
fig.add_trace(go.Scatter(x=pdt, y=px["closeadj"], name=f"{tk} 复权价(log)", line=dict(color="#7f7f7f", width=1.1)), secondary_y=True)
fig.add_hline(y=40, line_dash="dash", line_color="#d62728", opacity=0.4, secondary_y=False)
fig.add_hline(y=20, line_dash="dash", line_color="#1f6fb4", opacity=0.4, secondary_y=False)

vals = np.array([v for v in (f["roic_pct"] + f["rule40"]) if v is not None], dtype=float)
if len(vals):
    lo = min(np.nanpercentile(vals, 2), -20); hi = max(np.nanpercentile(vals, 97), 60)
    fig.update_yaxes(range=[lo - 10, hi + 15], title_text="指标值 (%)", secondary_y=False)
fig.update_yaxes(type="log", title_text="复权价 (log)", secondary_y=True)
fig.update_layout(height=620, plot_bgcolor="#111", paper_bgcolor="#111",
                  font=dict(color="#ddd"), legend=dict(orientation="h", y=1.02),
                  margin=dict(l=50, r=50, t=30, b=40))
st.plotly_chart(fig, use_container_width=True)

with st.expander("EPS / FCF / 营收 明细（单位不同分开看）", expanded=False):
    c1, c2, c3 = st.columns(3)
    for col, key, title in [(c1, "eps_ttm", "EPS (TTM, $)"),
                            (c2, "fcf_usd", "FCF ($)"),
                            (c3, "revenue_usd", "Revenue (TTM, $)")]:
        mini = go.Figure(go.Scatter(x=fi, y=f[key], line=dict(color="#1f6fb4")))
        mini.update_layout(title=title, height=240, plot_bgcolor="#111",
                           paper_bgcolor="#111", font=dict(color="#ccc"),
                           margin=dict(l=40, r=10, t=40, b=30))
        col.plotly_chart(mini, use_container_width=True)
