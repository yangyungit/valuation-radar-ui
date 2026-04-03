import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
from datetime import datetime, timedelta

st.set_page_config(page_title="宏观全景雷达", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
    .insight-section { margin-top: 10px; font-size: 14px; color: #ddd; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; }
    .logic-text { color: #aaa; font-style: italic; margin-left: 5px; }
    .key-point { font-weight: bold; color: #fff; }
</style>
""", unsafe_allow_html=True)

st.title("🔭 宏观全景雷达 (Macro Panoramic Radar)")
st.caption("双维监控：横轴【估值 Z-Score】，纵轴【相对强度 RS】。")

# --- 1. 定义资产池 ---
ASSET_GROUPS = {
    "A: 全球国别 (Global)": {
        "SPY": "美股", "QQQ": "纳指", "IWM": "罗素小盘", 
        "EEM": "新兴市场", "VGK": "欧洲", "EWJ": "日本", 
        "MCHI": "中国大盘", "KWEB": "中概互联", 
        "INDA": "印度", "VNM": "越南", "EWZ": "巴西",
        "ARGT": "阿根廷", "EWY": "韩国"
    },
    "B: 大宗/货币 (Macro)": {
        "UUP": "美元", "FXY": "日元", "CYB": "人民币",
        "GLD": "黄金", "SLV": "白银", "GDX": "金矿",
        "USO": "原油", "UNG": "天然气", 
        "CPER": "铜", "DBA": "农产品", 
        "BTC-USD": "BTC"
    },
    "C: 核心板块 (Level 1 Sectors)": {
        "XLK": "科技", "XLF": "金融", "XLV": "医疗", 
        "XLE": "能源", "XLI": "工业", "XLP": "必选", 
        "XLY": "可选", "XLB": "材料", "XLU": "公用", 
        "XLRE": "地产", "XLC": "通讯"
    },
    "D: 细分赛道 (Level 2/Themes)": {
        "SMH": "半导体", "IGV": "软件", "CIBR": "网安", "AIQ": "AI", 
        "KRE": "区域银行", "XRT": "零售", "ITB": "房屋建筑", 
        "XOP": "油气开采", "OIH": "油服", "URA": "铀矿", "TAN": "光伏", 
        "IBB": "生物科技", "ITA": "军工航天", "PAVE": "基建"
    },
    "E: 固收阶梯 (Fixed Income)": {
        "SHY": "1-3年美债", "IEF": "7-10年美债", "TLT": "20年美债",
        "LQD": "投资级债", "HYG": "垃圾债", "EMB": "新兴债",
        "MUB": "市政债", "TIP": "抗通胀债"
    },
    "F: 聪明钱因子 (Factors)": {
        "MTUM": "动量", "USMV": "低波", "VLUE": "价值",
        "QUAL": "质量", "IWF": "成长", "RSP": "等权",
        "SPHB": "高贝塔", "ARKK": "投机", "VIG": "红利"
    }
}

# --- 2. 数据引擎 ---
@st.cache_data(ttl=3600*4)
def get_data():
    all_tickers = []
    for group in ASSET_GROUPS.values():
        all_tickers.extend(list(group.keys()))
    all_tickers = list(set(all_tickers))
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730) 
    
    try:
        data = yf.download(all_tickers, start=start_date, end=end_date, progress=False, group_by='ticker')
        return data
    except: return pd.DataFrame()

raw_data = get_data()

# --- 3. 计算逻辑 ---
def calculate_metrics():
    metrics = []
    spy_mom20 = 0
    
    try:
        if isinstance(raw_data.columns, pd.MultiIndex):
            spy_df = raw_data['SPY']['Close'].dropna()
        else:
            spy_df = raw_data['Close'].dropna()
        if len(spy_df) > 21:
            spy_mom20 = (spy_df.iloc[-1] / spy_df.iloc[-21] - 1) * 100
    except: pass
    
    for group_name, tickers in ASSET_GROUPS.items():
        for ticker, name in tickers.items():
            try:
                if isinstance(raw_data.columns, pd.MultiIndex):
                    if ticker not in raw_data.columns.levels[0]: continue
                    df_t = raw_data[ticker]['Close'].dropna()
                else:
                    df_t = raw_data['Close'].dropna()

                if len(df_t) < 250: continue
                
                curr = df_t.iloc[-1]
                
                ma250 = df_t.rolling(250, min_periods=200).mean().iloc[-1]
                std250 = df_t.rolling(250, min_periods=200).std().iloc[-1]
                z_score = (curr - ma250) / std250 if std250 != 0 else 0
                
                abs_mom20 = (curr / df_t.iloc[-21] - 1) * 100
                rel_mom20 = abs_mom20 - spy_mom20
                
                ema20 = df_t.ewm(span=20, adjust=False).mean().iloc[-1]
                ema60 = df_t.ewm(span=60, adjust=False).mean().iloc[-1]
                ema120 = df_t.ewm(span=120, adjust=False).mean().iloc[-1]
                ema200 = df_t.ewm(span=200, adjust=False).mean().iloc[-1]
                
                l_vl = (ema120 - ema200) / ema200 * 100
                
                structure_type = "震荡/纠结"
                if ema20 > ema60 > ema120 > ema200: structure_type = "结构性长牛"
                elif ema20 < ema60 < ema120 < ema200: structure_type = "结构性熊市"
                elif ema20 > ema60 and curr < ema120: structure_type = "超跌反弹"
                elif ema20 < ema60 and curr > ema120: structure_type = "牛市回调"
                
                metrics.append({
                    "代码": ticker, "名称": name, "组别": group_name,
                    "Z-Score": round(z_score, 2), "相对强度": round(rel_mom20, 2), 
                    "趋势结构": structure_type, "L/VL": round(l_vl, 2),
                    "MA200": ema200, "Curr": curr
                })
            except: continue
            
    return pd.DataFrame(metrics), spy_mom20

# --- 4. 深度归因逻辑引擎 ---
def generate_deep_insight(df_group, group_name):
    if df_group.empty: return ""
    
    def get_val(ticker, col):
        row = df_group[df_group['代码'] == ticker]
        if not row.empty: return row.iloc[0][col]
        return None

    df_sorted = df_group.sort_values("相对强度", ascending=False)
    leaders = df_sorted.head(3)
    laggards = df_sorted.tail(3)
    
    leader_html = " ".join([f"<span class='tag-bull'>{row['名称']}</span>" for _, row in leaders.iterrows()])
    laggard_html = " ".join([f"<span class='tag-bear'>{row['名称']}</span>" for _, row in laggards.iterrows()])
    
    analysis_text = "数据特征不明显，维持中性观察。"
    macro_implication = "暂无明确宏观指向。"
    
    if "国别" in group_name:
        spy_rs = get_val("SPY", "相对强度")
        eem_rs = get_val("EEM", "相对强度")
        kweb_rs = get_val("KWEB", "相对强度")
        if spy_rs is not None and eem_rs is not None:
            if spy_rs > eem_rs + 3:
                analysis_text = "🇺🇸 **美股虹吸效应:** 资金回流美国，抛售新兴市场。"
                macro_implication = "利好美元资产，非美市场承压。"
            elif kweb_rs is not None and kweb_rs > spy_rs + 5:
                analysis_text = "🇨🇳 **中国资产独立行情:** 中概互联显著跑赢美股。"
                macro_implication = "关注资金流向全球估值洼地。"
            else: analysis_text = "🌏 **全球共振:** 各国股市同步性较高。"

    elif "大宗" in group_name:
        gld_rs = get_val("GLD", "相对强度")
        uso_rs = get_val("USO", "相对强度")
        dba_rs = get_val("DBA", "相对强度")
        if gld_rs is not None and uso_rs is not None:
            if gld_rs > 2 and uso_rs > 2:
                analysis_text = "🔥 **再通胀交易:** 黄金与原油共振上涨。"
                macro_implication = "利空长久期成长股，利好资源股。"
            elif gld_rs > 2 and uso_rs < -2:
                analysis_text = "📉 **衰退恐慌:** 黄金涨（避险），原油跌（需求差）。"
                macro_implication = "警惕股市系统性风险，债市利好。"
            elif dba_rs is not None and dba_rs > 5:
                analysis_text = "🌾 **刚性通胀:** 农产品异军突起。"

    elif "核心板块" in group_name:
        xlk_rs = get_val("XLK", "相对强度")
        xle_rs = get_val("XLE", "相对强度")
        xlp_rs = get_val("XLP", "相对强度")
        if xlk_rs is not None and xle_rs is not None:
            if xlk_rs > xle_rs + 3:
                analysis_text = "🚀 **Goldilocks (金发姑娘):** 科技领涨，能源回落。"
                macro_implication = "做多窗口期，持有成长股。"
            elif xle_rs > xlk_rs + 3:
                analysis_text = "🌧️ **滞胀防御:** 能源强于科技。"
                macro_implication = "减少高估值仓位，增加实物资产。"
            elif xlp_rs > xlk_rs and xlp_rs > xle_rs:
                analysis_text = "🛡️ **极度避险:** 必选消费成为避风港。"

    elif "细分赛道" in group_name:
        smh_rs = get_val("SMH", "相对强度")
        kre_rs = get_val("KRE", "相对强度")
        itb_rs = get_val("ITB", "相对强度")
        if smh_rs is not None and kre_rs is not None:
            if smh_rs > 0 and kre_rs < -3:
                analysis_text = "⚠️ **宏观背离:** AI在涨，银行在跌。"
                macro_implication = "行情‘瘸腿’，警惕补跌。"
            elif itb_rs is not None and itb_rs > 3:
                analysis_text = "🏠 **降息抢跑:** 房屋建筑商(ITB)领涨。"

    return f"""
<div class='insight-box'>
<div class='insight-title'>🧠 深度归因 (Deep Insight): {group_name.split(':')[0]}</div>
<div style='display:flex; gap:24px; align-items:center; margin-bottom:10px; flex-wrap:wrap'>
<div>🚀 领涨: {leader_html}</div>
<div>🥀 领跌: {laggard_html}</div>
</div>
<div class='insight-section'>
<span class='key-point'>🧐 现象解读:</span> {analysis_text}
</div>
<div class='insight-section' style='margin-top:5px'>
<span class='key-point'>🌍 宏观启示:</span> <span class='logic-text'>{macro_implication}</span>
</div>
</div>
"""

# --- 5. 绘图与展示 ---
if not raw_data.empty:
    df_metrics, benchmark_mom = calculate_metrics()
    
    if not df_metrics.empty:
        with st.sidebar:
            st.header("资产筛选")
            st.metric("基准 (SPY) 20日涨跌", f"{benchmark_mom:.2f}%")
            all_groups = list(ASSET_GROUPS.keys())
            selected_groups = st.multiselect("显示资产组别：", all_groups, default=["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"])
            
        df_plot = df_metrics[df_metrics['组别'].isin(selected_groups)]
        
        fig = px.scatter(
            df_plot, x="Z-Score", y="相对强度", color="相对强度", text="名称",
            hover_data={"代码": True, "趋势结构": True, "Z-Score": ":.2f", "相对强度": ":.2f", "名称": False, "相对强度": False},
            color_continuous_scale="RdYlGn", range_color=[-10, 10]
        )
        
        fig.add_hline(y=0, line_dash="dash", line_color="#FFFFFF", opacity=0.5)
        fig.add_vline(x=0, line_dash="dash", line_color="#FFFFFF", opacity=0.3)
        fig.update_traces(textposition='top center', marker=dict(size=10, opacity=0.9))
        
        fig.add_annotation(x=2, y=5, text="领涨/拥挤\n(减仓)", showarrow=False, font=dict(color="#E74C3C", size=10))
        fig.add_annotation(x=-2, y=-5, text="滞涨/弱势\n(观察)", showarrow=False, font=dict(color="#3498DB", size=10))
        fig.add_annotation(x=-2, y=5, text="抗跌/启动\n(加仓)", showarrow=False, font=dict(color="#2ECC71", size=10))
        fig.add_annotation(x=2, y=-5, text="补跌/崩盘\n(离场)", showarrow=False, font=dict(color="#E67E22", size=10))
        
        fig.update_layout(height=600, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), xaxis_title="便宜 (低 Z-Score) <---> 昂贵", yaxis_title="弱于大盘 <---> 强于大盘")
        st.plotly_chart(fig, use_container_width=True)
        
        if len(selected_groups) > 0:
            for idx, group in enumerate(selected_groups):
                df_sub = df_metrics[df_metrics['组别'] == group]
                st.markdown(generate_deep_insight(df_sub, group), unsafe_allow_html=True)
                
        st.markdown("### 📋 详细数据表 (Trend Structure)")
        def color_structure(val):
            if "长牛" in val: return 'color: #2ECC71; font-weight: bold'
            if "熊市" in val: return 'color: #E74C3C'
            if "反弹" in val: return 'color: #F1C40F'
            return 'color: #aaa'

        st.dataframe(
            df_plot.sort_values("相对强度", ascending=False).style.map(
                color_structure, subset=['趋势结构']
            ).format({"Z-Score": "{:.2f}", "相对强度": "{:.2f}", "L/VL": "{:.2f}"}), 
            use_container_width=True, hide_index=True
        )
    else: st.warning("暂无数据")
else: st.info("⏳ 正在计算数据...")