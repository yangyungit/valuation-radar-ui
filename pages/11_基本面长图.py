import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from api_client import fetch_fundamentals_manifest, fetch_fundamentals

st.set_page_config(page_title="基本面长图", layout="wide", page_icon="📈")
st.title("📈 基本面长图（ROIC / Rule40 / 利润率 / 股东总回报率 / EPS / PE / FCF / 营收 vs 股价）")
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

# 可叠加到主图的序列。pct 类挂左轴(指标值 %)，dollar/ratio 类各挂独立右轴(量纲差异大)。
OVERLAYS = [
    ("ROIC %",        "roic_pct",         "#1f6fb4", "pct"),
    ("Rule of 40 %",  "rule40",           "#d62728", "pct"),
    ("净利率 %",      "net_margin",       "#2ca02c", "pct"),
    ("毛利率 %",      "gross_margin",     "#9467bd", "pct"),
    ("股东总回报率 %","shareholder_yield","#bcbd22", "pct"),
    ("EPS (TTM,$)",  "eps_ttm",          "#ff7f0e", "dollar"),
    ("PE (TTM)",     "pe",               "#8c564b", "ratio"),
    ("FCF ($)",      "fcf_usd",          "#17becf", "dollar"),
    ("营收 (TTM,$)", "revenue_usd",      "#e377c2", "dollar"),
]
sel_overlays = st.multiselect(
    "叠加到主图（自选）", [o[0] for o in OVERLAYS], default=["ROIC %", "Rule of 40 %"],
    help="ROIC/Rule40/净利率/毛利率/股东总回报率挂左侧 % 轴；EPS/PE/FCF/营收 各挂独立右侧轴",
)

dollar_sel = [o for o in OVERLAYS if o[3] != "pct" and o[0] in sel_overlays]
# 右侧轴：第 0 条永远是复权价，其余是被勾选的 $ 序列，依次向右排开
step = 0.055
plot_right = max(0.55, 1.0 - step * len(dollar_sel))

fig = go.Figure()
for label, key, color, kind in OVERLAYS:
    if kind == "pct" and label in sel_overlays:
        fig.add_trace(go.Scatter(x=fi, y=f[key], name=label,
                                 line=dict(color=color, width=1.6), yaxis="y"))
fig.add_trace(go.Scatter(x=pdt, y=px["closeadj"], name=f"{tk} 复权价(log)",
                         line=dict(color="#7f7f7f", width=1.1), yaxis="y2"))

axis_layout = {}
for i, (label, key, color, _) in enumerate(dollar_sel):
    ax = f"y{i + 3}"
    fig.add_trace(go.Scatter(x=fi, y=f[key], name=label,
                             line=dict(color=color, width=1.6), yaxis=ax))
    axis_layout[f"yaxis{i + 3}"] = dict(
        title=dict(text=label, font=dict(color=color)),
        tickfont=dict(color=color), overlaying="y", side="right",
        anchor="free", position=min(0.999, plot_right + step * (i + 1)),
        showgrid=False,
    )

fig.add_hline(y=40, line_dash="dash", line_color="#d62728", opacity=0.4)
fig.add_hline(y=20, line_dash="dash", line_color="#1f6fb4", opacity=0.4)

pct_vals = []
for label, key, _, kind in OVERLAYS:
    if kind == "pct" and label in sel_overlays and f.get(key) is not None:
        pct_vals += [v for v in f[key] if v is not None]
vals = np.array(pct_vals, dtype=float)
yrange = None
if len(vals):
    lo = min(np.nanpercentile(vals, 2), -20); hi = max(np.nanpercentile(vals, 97), 60)
    yrange = [lo - 10, hi + 15]

fig.update_layout(
    height=640, plot_bgcolor="#111", paper_bgcolor="#111",
    font=dict(color="#ddd"), legend=dict(orientation="h", y=1.04),
    margin=dict(l=50, r=50, t=30, b=40),
    hovermode="x unified",
    xaxis=dict(domain=[0.0, plot_right], showspikes=True, spikemode="across",
               spikesnap="cursor", spikedash="dash", spikecolor="#999",
               spikethickness=1),
    yaxis=dict(title="指标值 (%)", range=yrange),
    yaxis2=dict(title="复权价 (log)", type="log", overlaying="y",
                side="right", anchor="x", showgrid=False),
    **axis_layout,
)
st.plotly_chart(fig, use_container_width=True)
