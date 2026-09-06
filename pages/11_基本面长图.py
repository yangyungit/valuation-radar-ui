import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from api_client import (fetch_fundamentals_manifest, fetch_fundamentals,
                        fetch_estimates, fetch_estimate_quarters)

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
if "fund_chart_sel" not in st.session_state or st.session_state["fund_chart_sel"] not in opts:
    st.session_state["fund_chart_sel"] = opts[0]
sel = st.selectbox("选择标的", opts, index=None, key="fund_chart_sel",
                    placeholder="输入代码或名称筛选…")
if sel is None:
    st.info("请选择一只标的")
    st.stop()
tk = sel.split("  |  ")[0].strip()

resp = fetch_fundamentals(tk)
if not resp.get("success"):
    st.error(f"读取 {tk} 失败：{resp.get('error')}"); st.stop()
d = resp["data"]; f = d["fundamentals"]; px = d["price"]
fi = pd.to_datetime(f["datekey"]); pdt = pd.to_datetime(px["date"])

# 净利润没有单独字段，用营收 * 净利率反推（Sharadar netmargin 本就是 netinc/revenue）
if f.get("revenue_usd") is not None and f.get("net_margin") is not None:
    f["net_income_usd"] = [
        (r * m / 100) if (r is not None and m is not None) else None
        for r, m in zip(f["revenue_usd"], f["net_margin"])
    ]

# 净利润同比：口径对齐后端 rev_yoy（push_fundamentals_to_render.py）——按 datekey 位移 4 期
# (季度频),但只信 300~460 天真实间隔一年的那次位移，避免财报换期导致的假同比；
# 上期净利润 <=0（去年是亏损年）时同比 % 会失真，直接标 NaN 不画。
_dk = pd.Series(pd.to_datetime(f["datekey"]))
_ni = pd.Series(f.get("net_income_usd"), dtype=float)
_gap_ok = (_dk - _dk.shift(4)).dt.days.between(300, 460)
_ni_prior = _ni.shift(4)
f["net_income_yoy"] = np.where(_gap_ok & (_ni_prior > 0), (_ni / _ni_prior - 1) * 100, np.nan).tolist()

# 净利润/经营现金流历史上只要出现过负值，log 轴就画不出那几个点，此时退回线性轴。
# 资本开支本身恒为负（现金流出），不开 log。
_ni_vals = [v for v in f["net_income_usd"] if v is not None]
net_income_log = bool(_ni_vals) and min(_ni_vals) > 0
_ocf_vals = [v for v in (f.get("ocf_usd") or []) if v is not None]
ocf_log = bool(_ocf_vals) and min(_ocf_vals) > 0

# 可叠加到主图的序列。pct 类挂左轴(指标值 %)，dollar/ratio 类各挂独立右轴(量纲差异大)。
# 第 5 项 log=True 表示该序列右轴用对数坐标（看增长速度，和复权价的 log 轴口径一致）。
OVERLAYS = [
    ("ROIC %",        "roic_pct",         "#1f6fb4", "pct",    False),
    ("Rule of 40 %",  "rule40",           "#d62728", "pct",    False),
    ("净利率 %",      "net_margin",       "#2ca02c", "pct",    False),
    ("毛利率 %",      "gross_margin",     "#9467bd", "pct",    False),
    ("营收同比 %",    "rev_yoy",          "#7f7f00", "pct",    False),
    ("净利润同比 %",  "net_income_yoy",   "#aa40fc", "pct",    False),
    ("股东总回报率 %","shareholder_yield","#bcbd22", "pct",    False),
    ("EPS (TTM,$)",  "eps_ttm",          "#ff7f0e", "dollar", False),
    ("PE (TTM)",     "pe",               "#8c564b", "ratio",  False),
    ("FCF ($)",      "fcf_usd",          "#17becf", "dollar", False),
    ("经营现金流 (TTM,$)","ocf_usd",      "#98df8a", "dollar", ocf_log),
    ("资本开支 (TTM,$)","capex_usd",      "#c49c94", "dollar", False),
    ("净利润 (TTM,$)","net_income_usd",   "#ff9896", "dollar", net_income_log),
    ("营收 (TTM,$)", "revenue_usd",      "#e377c2", "dollar", True),
]
sel_overlays = st.multiselect(
    "叠加到主图（自选）", [o[0] for o in OVERLAYS], default=["ROIC %", "Rule of 40 %"],
    help="ROIC/Rule40/净利率/毛利率/营收同比/净利润同比/股东总回报率挂左侧 % 轴；"
         "EPS/PE/FCF/经营现金流/资本开支/净利润/营收 各挂独立右侧轴。"
         "FCF = 经营现金流 + 资本开支（资本开支本身是负数）",
)

dollar_sel = [o for o in OVERLAYS if o[3] != "pct" and o[0] in sel_overlays]
# 右侧轴：第 0 条永远是复权价，其余是被勾选的 $ 序列，依次向右排开
step = 0.055
plot_right = max(0.55, 1.0 - step * len(dollar_sel))

fig = go.Figure()
for label, key, color, kind, log in OVERLAYS:
    if kind == "pct" and label in sel_overlays:
        fig.add_trace(go.Scatter(x=fi, y=f[key], name=label,
                                 line=dict(color=color, width=1.6), yaxis="y"))
fig.add_trace(go.Scatter(x=pdt, y=px["closeadj"], name=f"{tk} 复权价(log)",
                         line=dict(color="#7f7f7f", width=1.1), yaxis="y2"))

axis_layout = {}
for i, (label, key, color, kind, log) in enumerate(dollar_sel):
    ax = f"y{i + 3}"
    fig.add_trace(go.Scatter(x=fi, y=f[key], name=label,
                             line=dict(color=color, width=1.6), yaxis=ax))
    cfg = dict(
        title=dict(text=label, font=dict(color=color)),
        tickfont=dict(color=color), overlaying="y", side="right",
        anchor="free", position=min(0.999, plot_right + step * (i + 1)),
        showgrid=False,
    )
    if log:
        cfg["type"] = "log"
    # PE 这类倍数：早年盈利近 0 会爆出离群值撑爆轴，按分位数夹一下（同估值带图口径）
    if kind == "ratio":
        vv = np.array([v for v in (f.get(key) or []) if v is not None], dtype=float)
        if len(vv):
            hi = min(np.nanpercentile(vv, 90) * 1.8, np.nanpercentile(vv, 99.5))
            cfg["range"] = [0, hi]
    axis_layout[f"yaxis{i + 3}"] = cfg
    # 净利润挂自己的独立右轴，标一条 0 轴看它哪年由亏转盈（log 轴下 0 画不出来，跳过）
    if key == "net_income_usd" and not log:
        fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref=ax,
                     y0=0, y1=0, line=dict(color=color, width=1, dash="dot"), opacity=0.6)

# 这两条阈值线只对 Rule40/ROIC 有意义，没勾这两个指标时不画（否则会在无关的左轴范围里
# 显得莫名其妙——比如只看净利润同比时，左轴变成 % 同比范围，40/20 阈值线毫无意义）
if "Rule of 40 %" in sel_overlays:
    fig.add_hline(y=40, line_dash="dash", line_color="#d62728", opacity=0.4)
if "ROIC %" in sel_overlays:
    fig.add_hline(y=20, line_dash="dash", line_color="#1f6fb4", opacity=0.4)

pct_sel = [label for label, key, _, kind, _ in OVERLAYS if kind == "pct" and label in sel_overlays]
pct_vals = []
for label, key, _, kind, _ in OVERLAYS:
    if kind == "pct" and label in sel_overlays and f.get(key) is not None:
        pct_vals += [v for v in f[key] if v is not None]
vals = np.array(pct_vals, dtype=float)
yrange = None
if len(vals):
    lo = min(np.nanpercentile(vals, 2), -20); hi = max(np.nanpercentile(vals, 97), 60)
    yrange = [lo - 10, hi + 15]
# 左轴同时挂好几条 % 指标，靠图例颜色区分，轴标题就报当前挂了哪几条（太多就只报数量）
if not pct_sel:
    left_title = "指标值 (%)"
elif len(pct_sel) <= 4:
    left_title = "指标值 %（" + " / ".join(pct_sel) + "）"
else:
    left_title = f"指标值 %（{len(pct_sel)} 条，见图例颜色）"

fig.update_layout(
    height=640, plot_bgcolor="#111", paper_bgcolor="#111",
    font=dict(color="#ddd"), legend=dict(orientation="h", y=1.04),
    margin=dict(l=50, r=50, t=30, b=40),
    hovermode="x unified",
    xaxis=dict(domain=[0.0, plot_right], showspikes=True, spikemode="across",
               spikesnap="cursor", spikedash="dash", spikecolor="#999",
               spikethickness=1),
    yaxis=dict(title=left_title, range=yrange),
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

        qs = fetch_estimate_quarters(tk)
        rows = [e for e in (qs.get("quarters") or [])
                if e.get("revision_90d_pct") is not None]
        if rows:
            ys = [e["revision_90d_pct"] for e in rows]
            up = sum(1 for v in ys if v > 0)
            st.markdown("**历史每季的 90 天修正**")
            st.caption(f"数据源：Alpha Vantage，覆盖 {rows[0]['period_date']} 至今。"
                       f"每根柱子是那个季度临近财报时、分析师相对 90 天前把预期改了多少。"
                       f"　·　{len(ys)} 个季度里 {up} 个上修、{len(ys) - up} 个下修")
            figq = go.Figure(go.Bar(
                x=[e["period_date"] for e in rows], y=ys,
                marker_color=["#2ca02c" if v >= 0 else "#d62728" for v in ys],
                hovertemplate="%{x}<br>修正 %{y:+.1f}%<extra></extra>"))
            figq.update_layout(
                height=280, plot_bgcolor="#111", paper_bgcolor="#111",
                font=dict(color="#ddd"), showlegend=False,
                margin=dict(l=50, r=30, t=20, b=40),
                xaxis=dict(showgrid=False),
                yaxis=dict(title="相对 90 天前 (%)", zeroline=True, zerolinecolor="#666"),
            )
            st.plotly_chart(figq, use_container_width=True)
        elif qs.get("error"):
            st.caption(f"历史季度预期暂不可用：{qs['error']}")

        hist = est.get("history") or []
        if len(hist) > 1:
            with st.expander(f"自攒快照历史（{len(hist)} 份）"):
                st.caption("每次打开本页都会存一份当天的共识，跑久了就有了自己的时点预期历史。")
                st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)
        st.caption(f"快照日期 {est.get('snapshot_date')}")
