import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from api_client import fetch_fundamentals_manifest, fetch_fundamentals, fetch_estimates

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
for i, (label, key, color, kind) in enumerate(dollar_sel):
    ax = f"y{i + 3}"
    fig.add_trace(go.Scatter(x=fi, y=f[key], name=label,
                             line=dict(color=color, width=1.6), yaxis=ax))
    cfg = dict(
        title=dict(text=label, font=dict(color=color)),
        tickfont=dict(color=color), overlaying="y", side="right",
        anchor="free", position=min(0.999, plot_right + step * (i + 1)),
        showgrid=False,
    )
    # PE 这类倍数：早年盈利近 0 会爆出离群值撑爆轴，按分位数夹一下（同估值带图口径）
    if kind == "ratio":
        vv = np.array([v for v in (f.get(key) or []) if v is not None], dtype=float)
        if len(vv):
            hi = min(np.nanpercentile(vv, 90) * 1.8, np.nanpercentile(vv, 99.5))
            cfg["range"] = [0, hi]
    axis_layout[f"yaxis{i + 3}"] = cfg

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

st.divider()
st.subheader("🔭 分析师预期修正")
st.caption("数据源：yfinance 一致预期，只覆盖本财年和下一财年——2028 及以后是付费数据。"
           "重点看方向不看绝对值：共识还在上修说明市场对这家公司的预期在变强。")

if st.toggle("加载分析师预期（首次约 5-8 秒，之后走缓存）", value=True, key="est_on"):
    est = fetch_estimates(tk)
    if not est.get("success"):
        st.info(f"{tk} 拿不到分析师预期：{est.get('error')}")
    else:
        fy = [p for p in est["periods"] if p["period"] in ("0y", "+1y")]
        cols = st.columns(len(fy) + 1)
        for c, p in zip(cols, fy):
            cur, d30, d90 = p.get("eps_avg"), p.get("eps_30d"), p.get("eps_90d")
            chg30 = (cur / d30 - 1) * 100 if cur and d30 else None
            chg90 = (cur / d90 - 1) * 100 if cur and d90 else None
            c.metric(f"{p['label']} EPS 共识", f"${cur:,.2f}" if cur else "—",
                     f"{chg30:+.1f}%　近 30 天" if chg30 is not None else None)
            bits = []
            if chg90 is not None:
                bits.append(f"近 90 天 {chg90:+.1f}%")
            up, dn = int(p.get("up_30d") or 0), int(p.get("down_30d") or 0)
            bits.append(f"30 天内 {up} 家上修 / {dn} 家下修")
            if p.get("analysts"):
                bits.append(f"{int(p['analysts'])} 家覆盖")
            c.caption("　·　".join(bits))

        pt, rt = est.get("price_target") or {}, est.get("ratings") or {}
        c = cols[-1]
        if pt.get("mean") and pt.get("current"):
            up_pct = (pt["mean"] / pt["current"] - 1) * 100
            c.metric("目标价均值", f"${pt['mean']:,.0f}", f"{up_pct:+.1f}% 空间")
            c.caption(f"区间 ${pt.get('low', 0):,.0f} – ${pt.get('high', 0):,.0f}　·　"
                      f"现价 ${pt['current']:,.2f}")
        if rt.get("mean"):
            c.caption(f"评级均值 {rt['mean']:.2f}（1=强买 5=强卖）　·　"
                      f"强买 {rt.get('strong_buy') or 0} / 买 {rt.get('buy') or 0} / "
                      f"持有 {rt.get('hold') or 0} / 卖 {(rt.get('sell') or 0) + (rt.get('strong_sell') or 0)}")

        # 两个财年 EPS 量级不同，统一归一到「相对 90 天前的 %」才能同图比斜率
        STEPS = [("eps_90d", -90), ("eps_60d", -60), ("eps_30d", -30),
                 ("eps_7d", -7), ("eps_avg", 0)]
        figr = go.Figure()
        for p, color in zip(fy, ("#1f6fb4", "#ff7f0e")):
            base = p.get("eps_90d")
            if not base:
                continue
            xs, ys = [], []
            for key, off in STEPS:
                v = p.get(key)
                if v:
                    xs.append(off); ys.append((v / base - 1) * 100)
            if len(xs) > 1:
                figr.add_trace(go.Scatter(x=xs, y=ys, name=f"{p['label']} EPS",
                                          mode="lines+markers",
                                          line=dict(color=color, width=2)))
        if figr.data:
            figr.add_hline(y=0, line_dash="dash", line_color="#666", opacity=0.6)
            figr.update_layout(
                height=300, plot_bgcolor="#111", paper_bgcolor="#111",
                font=dict(color="#ddd"), legend=dict(orientation="h", y=1.12),
                margin=dict(l=50, r=30, t=30, b=40), hovermode="x unified",
                xaxis=dict(title="距今天数", showgrid=False),
                yaxis=dict(title="相对 90 天前 (%)", zeroline=False),
            )
            st.plotly_chart(figr, use_container_width=True)

        with st.expander("季度共识明细"):
            q = [p for p in est["periods"] if p["period"] in ("0q", "+1q")]
            st.dataframe(pd.DataFrame([{
                "期间": p["label"],
                "EPS 共识": p.get("eps_avg"),
                "30 天前": p.get("eps_30d"),
                "90 天前": p.get("eps_90d"),
                "上修(30天)": p.get("up_30d"),
                "下修(30天)": p.get("down_30d"),
                "营收共识": p.get("rev_avg"),
                "同比": p.get("rev_growth"),
            } for p in q]), use_container_width=True, hide_index=True)

        hist = est.get("history") or []
        if len(hist) > 1:
            with st.expander(f"自攒快照历史（{len(hist)} 份）"):
                st.caption("每次打开本页都会存一份当天的共识，跑久了就有了自己的时点预期历史。")
                st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)
        st.caption(f"快照日期 {est.get('snapshot_date')}")
