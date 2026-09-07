import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import (
    clear_valuation_caches,
    fetch_valuation_history,
    fetch_valuation_lookup,
    fetch_valuation_members,
    fetch_valuation_sector_history,
    fetch_valuation_snapshot,
    fetch_valuation_universe,
)

st.set_page_config(page_title="行业 PE", layout="wide", page_icon="📐")
st.title("📐 行业估值分位")
st.caption("同一个 PE 在不同行业含义完全不同。先看同行分布，再判断贵贱。分位数只统计正值样本，亏损公司单列。")

# 跨行业对照默认组：消费/科技/金融/能源/医药各拿一个典型，撑开估值区间
DEFAULT_PEERS = [
    "Semiconductors", "Software - Infrastructure", "Software - Application",
    "Consumer Electronics", "Internet Content & Information", "Discount Stores",
    "Beverages - Non-Alcoholic", "Banks - Diversified", "Oil & Gas Integrated",
    "Utilities - Regulated Electric", "Drug Manufacturers - General",
    "Aerospace & Defense", "Auto Manufacturers",
]
CRISES = [
    ("2000-03", "2002-10", "互联网泡沫"),
    ("2007-10", "2009-03", "金融危机"),
    ("2020-02", "2020-04", "疫情"),
    ("2022-01", "2022-10", "加息"),
]
SECTOR_COLORS = {
    "Technology": "#1f77b4", "Consumer Cyclical": "#ff7f0e",
    "Consumer Defensive": "#2ca02c", "Financial Services": "#9467bd",
    "Energy": "#8c564b", "Utilities": "#7f7f7f", "Healthcare": "#e377c2",
    "Industrials": "#17becf", "Real Estate": "#bcbd22",
    "Basic Materials": "#d62728", "Communication Services": "#aec7e8",
}
SECTOR_ZH = {
    "Technology": "科技", "Consumer Cyclical": "消费周期",
    "Consumer Defensive": "消费防御", "Financial Services": "金融服务",
    "Energy": "能源", "Utilities": "公用事业", "Healthcare": "医疗保健",
    "Industrials": "工业", "Real Estate": "房地产",
    "Basic Materials": "基础材料", "Communication Services": "通讯服务",
}
# Morningstar 细分行业英文名 → 中文简称，仅用于展示，接口参数仍传英文原名
INDUSTRY_ZH = {
    "Advertising Agencies": "广告代理", "Aerospace & Defense": "航空航天与国防",
    "Agricultural Inputs": "农业投入品", "Airlines": "航空公司",
    "Airports & Air Services": "机场与航空服务", "Apparel Manufacturing": "服装制造",
    "Apparel Retail": "服装零售", "Asset Management": "资产管理",
    "Auto & Truck Dealerships": "汽车经销商", "Auto Manufacturers": "汽车制造",
    "Auto Parts": "汽车零部件", "Banks - Diversified": "银行-综合",
    "Banks - Regional": "银行-区域", "Beverages - Brewers": "饮料-啤酒",
    "Beverages - Non-Alcoholic": "饮料-无酒精", "Biotechnology": "生物科技",
    "Building Materials": "建材", "Building Products & Equipment": "建筑产品与设备",
    "Capital Markets": "资本市场", "Communication Equipment": "通信设备",
    "Computer Hardware": "计算机硬件", "Conglomerates": "综合企业",
    "Consulting Services": "咨询服务", "Consumer Electronics": "消费电子",
    "Credit Services": "信贷服务", "Diagnostics & Research": "诊断与研究",
    "Discount Stores": "折扣零售", "Drug Manufacturers - General": "制药-综合",
    "Drug Manufacturers - Specialty & Generic": "制药-专科与仿制",
    "Education & Training Services": "教育培训",
    "Electrical Equipment & Parts": "电气设备与零件", "Electronic Components": "电子元件",
    "Electronic Gaming & Multimedia": "电子游戏与多媒体", "Engineering & Construction": "工程建筑",
    "Entertainment": "娱乐", "Farm & Heavy Construction Machinery": "农用与重型机械",
    "Financial Data & Stock Exchanges": "金融数据与交易所", "Food Distribution": "食品经销",
    "Footwear & Accessories": "鞋类与配饰", "Furnishings Fixtures & Appliances": "家具家电",
    "Gambling": "博彩", "Gold": "黄金", "Health Information Services": "医疗信息服务",
    "Healthcare Plans": "医保计划", "Household & Personal Products": "家庭与个人用品",
    "Industrial Distribution": "工业分销", "Information Technology Services": "IT 服务",
    "Insurance - Diversified": "保险-综合", "Insurance - Life": "保险-寿险",
    "Insurance - Property & Casualty": "保险-财产与意外", "Insurance - Reinsurance": "保险-再保险",
    "Insurance - Specialty": "保险-专业", "Insurance Brokers": "保险经纪",
    "Integrated Freight & Logistics": "综合货运物流",
    "Internet Content & Information": "互联网内容与信息", "Internet Retail": "互联网零售",
    "Leisure": "休闲", "Lodging": "酒店住宿", "Marine Shipping": "海运",
    "Medical Care Facilities": "医疗机构", "Medical Devices": "医疗器械",
    "Medical Instruments & Supplies": "医疗仪器与耗材", "Metal Fabrication": "金属加工",
    "Oil & Gas Drilling": "油气钻探", "Oil & Gas E&P": "油气勘探开发",
    "Oil & Gas Equipment & Services": "油气设备与服务", "Oil & Gas Integrated": "油气综合",
    "Oil & Gas Midstream": "油气中游", "Oil & Gas Refining & Marketing": "油气炼化销售",
    "Other Industrial Metals & Mining": "其他工业金属与采矿", "Packaged Foods": "包装食品",
    "Packaging & Containers": "包装容器", "Personal Services": "个人服务",
    "Pollution & Treatment Controls": "污染治理", "REIT - Diversified": "REIT-综合",
    "REIT - Healthcare Facilities": "REIT-医疗设施", "REIT - Hotel & Motel": "REIT-酒店",
    "REIT - Industrial": "REIT-工业", "REIT - Mortgage": "REIT-抵押",
    "REIT - Office": "REIT-写字楼", "REIT - Residential": "REIT-住宅",
    "REIT - Retail": "REIT-零售", "REIT - Specialty": "REIT-专业",
    "Railroads": "铁路", "Real Estate Services": "房地产服务",
    "Recreational Vehicles": "休闲车", "Rental & Leasing Services": "租赁服务",
    "Residential Construction": "住宅建筑", "Resorts & Casinos": "度假村与赌场",
    "Restaurants": "餐饮", "Scientific & Technical Instruments": "科学与技术仪器",
    "Security & Protection Services": "安防服务",
    "Semiconductor Equipment & Materials": "半导体设备与材料", "Semiconductors": "半导体",
    "Software - Application": "软件-应用", "Software - Infrastructure": "软件-基础设施",
    "Solar": "太阳能", "Specialty Business Services": "专业商业服务",
    "Specialty Chemicals": "特种化学品", "Specialty Industrial Machinery": "专用工业机械",
    "Specialty Retail": "专业零售", "Staffing & Employment Services": "人力资源服务",
    "Steel": "钢铁", "Telecom Services": "电信服务", "Tools & Accessories": "工具配件",
    "Travel Services": "旅游服务", "Trucking": "卡车运输",
    "Utilities - Diversified": "公用事业-综合",
    "Utilities - Independent Power Producers": "公用事业-独立电力",
    "Utilities - Regulated Electric": "公用事业-电力监管",
    "Utilities - Regulated Gas": "公用事业-燃气监管",
    "Utilities - Regulated Water": "公用事业-水务监管",
    "Utilities - Renewable": "公用事业-可再生能源", "Waste Management": "废物管理",
}


def zh(name):
    """行业/大类英文名 → 中文简称，查不到就原样返回。"""
    return INDUSTRY_ZH.get(name) or SECTOR_ZH.get(name) or name

with st.sidebar:
    if st.button("🔄 清除缓存"):
        clear_valuation_caches()
        st.rerun()

uni = fetch_valuation_universe()
if not uni.get("success"):
    st.error(f"拿不到行业名单：{uni.get('error', '')}")
    st.info("后端缺预计算表的话，跑一次 `valuation-radar/scripts/build_industry_valuation.py`。")
    st.stop()

metrics = uni["metrics"]
c1, c2, c3 = st.columns([1.1, 1.2, 2.4])
with c1:
    metric_keys = list(metrics.keys())
    metric = st.selectbox("指标", metric_keys, format_func=lambda k: metrics[k])
with c2:
    ticker = st.text_input("对标个股", value="TSLA", placeholder="美股代码").strip().upper()
with c3:
    live_as_of = uni.get("live_as_of")
    if live_as_of:
        fresh = f"当期 {live_as_of} 实时｜历史截至 {uni['as_of']}"
    else:
        fresh = f"数据截止 {uni['as_of']}（Sharadar 买断到此为止）"
    st.markdown(
        f"<div style='font-size:13px;color:#888;padding-top:32px'>{fresh}</div>",
        unsafe_allow_html=True,
    )

info = fetch_valuation_lookup(ticker) if ticker else {"success": False}
if ticker and not info.get("success"):
    st.warning(f"{ticker} 不在母体里，只看行业分布。（母体 = 美国交易所普通股 + ADR）")
home = info.get("industry") if info.get("success") else None

if home:
    st.markdown(
        f"<div style='font-size:15px;padding:6px 0'>"
        f"<b>{info['ticker']}</b> {info['name']} — 归类 <b>{zh(info['sector'])} / {zh(home)}</b></div>",
        unsafe_allow_html=True,
    )

# ============ 图 A：当期横截面 ============
st.subheader("当期各行业分布")

picks = list(DEFAULT_PEERS)
if home and home not in picks:
    picks.insert(0, home)
picks = [p for p in picks if p in uni["industries"]]
picks = st.multiselect("对照行业", uni["industries"], default=picks, format_func=zh)

if not picks:
    st.info("选至少一个行业。")
    st.stop()

snap = fetch_valuation_snapshot(metric, "industry")
mem = fetch_valuation_members(tuple(sorted(picks)), metric, "industry")
band_df = pd.DataFrame(snap.get("rows", []))
mem_df = pd.DataFrame(mem.get("rows", []))

if band_df.empty:
    st.error("当期没有任何行业满足样本门槛。")
    st.stop()

band_df = band_df[band_df["group_name"].isin(picks)].copy()
for col in ("p10", "p25", "p50", "p75", "p90"):
    band_df[col] = band_df[col].astype(float)
band_df = band_df.dropna(subset=["p25", "p50", "p75"]).sort_values("p50")
order = band_df["group_name"].tolist()
order_zh = [zh(o) for o in order]

fig_a = go.Figure()
for _, r in band_df.iterrows():
    loss = int(round(r["loss_ratio"] * r["n_total"]))
    name_zh = zh(r["group_name"])
    fig_a.add_trace(go.Box(
        x=[name_zh], q1=[r["p25"]], median=[r["p50"]], q3=[r["p75"]],
        lowerfence=[r["p10"]], upperfence=[r["p90"]],
        name=name_zh, showlegend=False,
        marker_color="#4a7ba7", fillcolor="rgba(158,202,225,0.55)", line_width=1.4,
        hovertext=(f"{name_zh}<br>中位 {r['p50']:.1f}｜"
                   f"25-75 {r['p25']:.1f}-{r['p75']:.1f}<br>"
                   f"样本 {int(r['n_pos'])} 家｜亏损 {loss}/{int(r['n_total'])}"),
        hoverinfo="text",
    ))
    # 中位线用粗横杠标记叠在箱体上，plotly box 本身不支持单独加粗 median
    fig_a.add_trace(go.Scatter(
        x=[name_zh], y=[r["p50"]], mode="markers", showlegend=False, hoverinfo="skip",
        marker=dict(symbol="line-ew", size=34, line=dict(color="#c0392b", width=3)),
    ))

star_note = ""
if not mem_df.empty:
    mem_df = mem_df[mem_df["industry"].isin(order)].copy()
    mem_df["industry_zh"] = mem_df["industry"].map(zh)
    mem_df["value"] = mem_df["value"].astype(float)
    pts = mem_df[mem_df["value"] > 0].dropna(subset=["value"])
    dots = pts[pts["ticker"] != ticker]
    fig_a.add_trace(go.Scatter(
        x=dots["industry_zh"], y=dots["value"], mode="markers", name="成分股",
        marker=dict(size=6, color="rgba(120,120,120,0.55)"),
        customdata=dots[["ticker", "name"]].values,
        hovertemplate="%{customdata[0]} %{customdata[1]}<br>%{y:.1f}x<extra></extra>",
    ))
    star = pts[pts["ticker"] == ticker]
    if not star.empty:
        fig_a.add_trace(go.Scatter(
            x=star["industry_zh"], y=star["value"], mode="markers+text", name=ticker,
            marker=dict(size=17, color="#d62728", symbol="star",
                        line=dict(width=1, color="#000")),
            text=[f"  {ticker} {star.iloc[0]['value']:.0f}x"], textposition="middle right",
            textfont=dict(size=13, color="#d62728"),
            hovertemplate=f"{ticker}<br>%{{y:.1f}}x<extra></extra>",
        ))
    elif ticker:
        # 亏损股在图上没有点，不提示的话会以为图坏了
        raw = mem_df[mem_df["ticker"] == ticker]
        if not raw.empty and raw.iloc[0].get("is_loss"):
            v = raw.iloc[0]["value"]
            shown = f"为 {v:.1f}" if pd.notna(v) else "算不出来"
            star_note = f"{ticker} 当期亏损（{metrics[metric]} {shown}），图上不画点。"
        elif home in order:
            star_note = f"{ticker} 当期缺{metrics[metric]}数据，或市值低于 $2B 门槛。"

fig_a.update_layout(
    height=520, yaxis_type="log", yaxis_title=f"{metrics[metric]}（对数轴）",
    xaxis=dict(categoryorder="array", categoryarray=order_zh, tickangle=-28),
    margin=dict(l=10, r=10, t=30, b=10), hovermode="closest",
)
st.plotly_chart(fig_a, use_container_width=True)

if star_note:
    st.info(star_note)

lo, hi = band_df.iloc[0], band_df.iloc[-1]
st.markdown(
    f"<div style='font-size:13px;color:#666'>最便宜 {zh(lo['group_name'])} 中位 {lo['p50']:.1f}x，"
    f"最贵 {zh(hi['group_name'])} 中位 {hi['p50']:.1f}x，差 {hi['p50'] / lo['p50']:.1f} 倍。"
    f"箱体 = 25-75 分位，须 = 10-90 分位。</div>",
    unsafe_allow_html=True,
)

# ============ 图 B：历史分位带 ============
st.divider()
st.subheader("历史走势：同业区间 + 个股")

h1, h2 = st.columns([2.6, 1])
with h1:
    focus = st.selectbox("行业", order, index=order.index(home) if home in order else 0,
                        format_func=zh)
with h2:
    start = st.selectbox("起点", ["2015-01", "2010-01", "2005-01", "2000-01"], index=0)

hist = fetch_valuation_history(focus, metric, "industry", ticker or None, start)
if not hist.get("success"):
    st.warning(hist.get("error", "拿不到历史"))
else:
    b = pd.DataFrame(hist["band"])
    b["ym"] = pd.to_datetime(b["ym"])
    for col in ("p25", "p50", "p75"):
        b[col] = b[col].astype(float)
    b = b.dropna(subset=["p25", "p50", "p75"])

    fig_b = go.Figure()
    fig_b.add_trace(go.Scatter(x=b["ym"], y=b["p75"], mode="lines", name="75 分位",
                               line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig_b.add_trace(go.Scatter(x=b["ym"], y=b["p25"], mode="lines", name="同业 25-75 分位",
                               line=dict(width=0), fill="tonexty",
                               fillcolor="rgba(158,202,225,0.45)", hoverinfo="skip"))
    fig_b.add_trace(go.Scatter(x=b["ym"], y=b["p50"], mode="lines", name="同业中位数",
                               line=dict(color="#1a4d7a", width=2.2),
                               hovertemplate="%{x|%Y-%m} 中位 %{y:.1f}x<extra></extra>"))

    line = pd.DataFrame(hist.get("ticker_line", []))
    if not line.empty:
        line["ym"] = pd.to_datetime(line["ym"])
        line["value"] = line["value"].astype(float)
        fig_b.add_trace(go.Scatter(x=line["ym"], y=line["value"], mode="lines", name=ticker,
                                   line=dict(color="#d62728", width=2),
                                   connectgaps=False,
                                   hovertemplate="%{x|%Y-%m} " + ticker + " %{y:.1f}x<extra></extra>"))

    fig_b.update_layout(height=420, yaxis_type="log",
                        yaxis_title=f"{metrics[metric]}（对数轴）",
                        margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                        legend=dict(orientation="h", y=1.08, x=0))
    st.plotly_chart(fig_b, use_container_width=True)

    note = f"红线断开 = 当月{metrics[metric]}为负（亏损）。"
    if not line.empty and line["value"].notna().any():
        cur = line["value"].dropna().iloc[-1]
        rank = (line["value"].dropna() <= cur).mean() * 100
        note += f" {ticker} 当前 {cur:.0f}x，处于自己 {start} 以来的 {rank:.0f}% 分位。"
    if hist.get("live_from"):
        note += (f" 最后一段连到 {hist['live_from']} 的实时值，"
                 f"中间月份 Sharadar 停更后补不上，是直线连过去的。")
    st.markdown(f"<div style='font-size:13px;color:#666'>{note}</div>", unsafe_allow_html=True)

# ============ 图 C：大环境 ============
st.divider()
st.subheader("大环境：各大类行业中位数")

sec = fetch_valuation_sector_history(metric, "2000-01")
if not sec.get("success"):
    st.warning(sec.get("error", "拿不到大类历史"))
else:
    idx = pd.to_datetime(pd.Series(sec["index"]))
    fig_c = go.Figure()
    for name in sorted(sec["series"].keys()):
        s = pd.Series(sec["series"][name], index=idx).astype(float)
        s = s.rolling(3, min_periods=1).mean().dropna()
        name_zh = zh(name)
        fig_c.add_trace(go.Scatter(
            x=s.index, y=s, mode="lines", name=name_zh,
            line=dict(width=1.7, color=SECTOR_COLORS.get(name)),
            hovertemplate="%{x|%Y-%m} " + name_zh + " %{y:.1f}x<extra></extra>",
        ))
    for x0, x1, lab in CRISES:
        fig_c.add_vrect(x0=x0, x1=x1, fillcolor="grey", opacity=0.15, line_width=0,
                        annotation_text=lab, annotation_position="top left",
                        annotation_font_size=13)
    fig_c.update_layout(height=430, yaxis_title=f"{metrics[metric]} 中位数",
                        margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
                        legend=dict(orientation="h", y=-0.16, font=dict(size=11)))
    st.plotly_chart(fig_c, use_container_width=True)
    st.markdown(
        "<div style='font-size:13px;color:#666'>灰带 = 危机或加息期。"
        "全行业同步下台阶说明是环境问题，不是公司问题。3 个月平滑。</div>",
        unsafe_allow_html=True,
    )
