import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
from api_client import fetch_core_data, get_global_data, fetch_macro_scores

# 1. 动态向云端 API 请求核心机密字典
core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})
MACRO_TAGS_MAP = core_data.get("MACRO_TAGS_MAP", {})
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})

ALL_TICKERS = list(TIC_MAP.keys())
# --- 架构师注释: 宏观定调中心 v13.37 (终极量化逻辑升级版) ---
# 1. 实装 SPY 5阶状态机（强多头/多头回调/上涨力竭/强空头/震荡）。
# 2. SSOT 对齐缓存，消除 Z-Score 漂移与缩进报错。

st.set_page_config(page_title="宏观定调中心", layout="wide", page_icon="🧭")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！正在重新拉取最新数据...")
        st.rerun()

st.markdown("""
<style>
    .metric-value { font-size: 24px; font-weight: bold; }
    .status-green { color: #2ECC71; font-weight: bold; font-size: 14px; }
    .status-red { color: #E74C3C; font-weight: bold; font-size: 14px; }
    .status-grey { color: #95A5A6; font-weight: bold; font-size: 14px; }
    
    .scenario-card { border-radius: 8px; padding: 15px; margin-bottom: 20px; border: 1px solid #444; background-color: #222; height: 100%; }
    .evidence-list { margin-top: 15px; border-top: 1px solid #444; padding-top: 10px; }
    .ev-item { margin-bottom: 6px; font-size: 12px; line-height: 1.4; display: flex; color: #ddd; }
    .ev-pass { color: #2ECC71; font-weight: bold; margin-right: 5px; }
    .ev-fail { color: #7f8c8d; margin-right: 5px; }
    
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 15px; margin-top: 10px; font-size: 13px; color: #ccc; }
    .conclusion-box { background-color: rgba(46, 204, 113, 0.1); border-left: 3px solid #2ECC71; padding: 12px; margin-top: 5px; font-size: 13px; color: #ddd; }
    .sub-ticker { font-size: 12px; color: #f1c40f; margin-left: 20px; border-left: 1px dashed #555; padding-left: 8px; margin-bottom: 4px;}
</style>
""", unsafe_allow_html=True)

st.title("🧭 宏观定调中心 (Macro Regime Center)")
st.caption("逻辑链：宏观底色/时钟 ➡️ **债市/因子 (可视化验证)** ➡️ **全证据链推演 (四象限裁决)**")

CLOCK_ASSETS = ["XLY", "XLP", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "SPY", "LQD"]
FACTOR_ASSETS = ["MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG"]
TARGETS_A = ["XLK", "XLC", "SMH", "IGV", "AIQ", "ITB", "XRT", "KWEB"] 
TARGETS_B = ["XLE", "XLI", "XOP", "OIH", "CPER", "URA", "PAVE", "PICK", "KRE", "USO"] 
TARGETS_C = ["GLD", "SLV", "DBA", "ITA", "URA"]
TARGETS_D = ["XLV", "XLU", "XLP"]

TOP_HOLDINGS = {
    "XLK": ["AAPL", "MSFT", "NVDA"], "XLC": ["META", "GOOGL", "NFLX"],
    "SMH": ["TSM", "AVGO", "AMD"], "IGV": ["CRM", "ADBE", "INTU"],
    "XLE": ["XOM", "CVX", "COP"], "XLI": ["GE", "CAT", "HON"],
    "XOP": ["EOG", "OXY", "PXD"], "OIH": ["SLB", "BKR", "HAL"],
    "GLD": ["NEM", "GOLD", "AEM"], "SLV": ["PAAS", "AG", "HL"],
    "XLV": ["LLY", "UNH", "JNJ", "PFE"], 
    "XLU": ["NEE", "DUK", "SO"],
    "XLP": ["WMT", "COST", "KO", "PEP", "MCD"], 
    "KRE": ["USB", "PNC", "TFC"],
    "ITB": ["DHI", "LEN", "PHM"], "XRT": ["AMZN", "HD", "TGT"], 
    "URA": ["CCJ", "NXE", "UUUU"], "PAVE": ["VMC", "MLM", "URI"],
    "ITA": ["LMT", "NOC", "KTOS"], 
    "PICK": ["BHP", "VALE", "RIO"],
    "CPER": ["FCX", "SCCO", "TECK"], "DBA": ["ADM", "BG", "TSN"]
}

CONSTITUENT_STOCKS = []
for stocks in TOP_HOLDINGS.values(): CONSTITUENT_STOCKS.extend(stocks)
ALL_TICKERS = list(set(CLOCK_ASSETS + FACTOR_ASSETS + TARGETS_A + TARGETS_B + TARGETS_C + TARGETS_D + CONSTITUENT_STOCKS))

ASSET_NAMES = {
    "XLK": "科技", "XLC": "通讯", "SMH": "半导体", "IGV": "软件", "AIQ": "AI", 
    "ITB": "房屋建筑", "XRT": "零售", "KWEB": "中概互联", "NVDA": "英伟达", "MSFT": "微软",
    "XLE": "能源", "XLI": "工业", "XOP": "油气开采", "OIH": "油服", "CPER": "铜", 
    "URA": "铀矿", "PAVE": "基建", "PICK": "矿业", "KRE": "区域银行", "USO": "原油",
    "BHP": "必和必拓", "VALE": "淡水河谷", "RIO": "力拓",
    "GLD": "黄金", "SLV": "白银", "DBA": "农产品", "XOM": "埃克森美孚", "MO": "奥驰亚", 
    "CCJ": "卡梅科", "NEM": "纽蒙特", "XLV": "医疗", "XLU": "公用", "MCD": "麦当劳", 
    "WMT": "沃尔玛", "KO": "可口可乐", "PEP": "百事", "JNJ": "强生", "PFE": "辉瑞",
    "AAPL": "苹果", "META": "Meta", "GOOGL": "谷歌", "NFLX": "奈飞", "TSM": "台积电", 
    "AVGO": "博通", "AMD": "超威", "CRM": "赛富时", "ADBE": "Adobe", "INTU": "直觉软件",
    "CVX": "雪佛龙", "COP": "康菲石油", "GE": "通用电气", "CAT": "卡特彼勒", "HON": "霍尼韦尔",
    "EOG": "EOG能源", "OXY": "西方石油", "PXD": "先锋自然", "SLB": "斯伦贝谢", "BKR": "贝克休斯", "HAL": "哈里伯顿",
    "GOLD": "巴里克黄金", "AEM": "伊格尔矿业", "PAAS": "泛美白银", "AG": "First Majestic", "HL": "赫克拉",
    "LLY": "礼来", "UNH": "联合健康", "NEE": "新纪元能源", "DUK": "杜克能源", "SO": "南方公司",
    "PG": "宝洁", "USB": "美国合众银行", "PNC": "PNC金融", "TFC": "Truist",
    "DHI": "霍顿房屋", "LEN": "莱纳建筑", "PHM": "普尔特房屋", "COST": "开市客", "TGT": "塔吉特",
    "NXE": "NexGen", "UUUU": "Energy Fuels", "VMC": "火神材料", "MLM": "马丁玛丽埃塔", "URI": "联合租赁",
    "FCX": "自由港", "SCCO": "南方铜业", "TECK": "泰克资源", "ADM": "阿彻丹尼尔斯", "BG": "邦吉", "TSN": "泰森食品"
}

MACRO_ASSETS_ALL = ["XLY", "XLP", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "XLK"]
UNIVERSAL_TICKERS = list(set(ALL_TICKERS + MACRO_ASSETS_ALL + list(TIC_MAP.keys()) + list(REGIME_MAP.keys())))
UNIVERSAL_TICKERS.sort() 

with st.spinner("⏳ 正在与中央厨房建立数据量子纠缠 (SSOT)..."):
    df = get_global_data(UNIVERSAL_TICKERS, years=4)

if not df.empty and len(df) > 750:
    
    def get_ret(ticker, days=20): 
        if ticker in df.columns:
            s = df[ticker].dropna()
            if len(s) > days:
                return float((s.iloc[-1] / s.iloc[-1-days] - 1) * 100)
        return 0.0

    df_calc = pd.DataFrame(index=df.index)
    df_calc['Growth_Raw'] = df['XLY'] / df['XLP']
    df_calc['Inflation_Raw'] = df['TIP'] / df['IEF']
    
    df_calc['Growth_Smooth'] = df_calc['Growth_Raw'].rolling(window=20).mean()
    df_calc['Inflation_Smooth'] = df_calc['Inflation_Raw'].rolling(window=20).mean()
    
    z_window = 750
    df_z = pd.DataFrame(index=df_calc.index)
    for col, raw in [('Growth', 'Growth_Smooth'), ('Inflation', 'Inflation_Smooth')]:
        roll_mean = df_calc[raw].rolling(window=z_window).mean()
        roll_std = df_calc[raw].rolling(window=z_window).std()
        df_z[col] = (df_calc[raw] - roll_mean) / roll_std
    
    df_z = df_z.dropna()
    curr_clock_g = float(df_z['Growth'].iloc[-1]) if len(df_z) > 0 else 0.0
    curr_clock_i = float(df_z['Inflation'].iloc[-1]) if len(df_z) > 0 else 0.0

    tlt_shy_diff = get_ret('TLT') - get_ret('SHY')
    hyg_ief_diff = get_ret('HYG') - get_ret('IEF')
    tip_ief_diff = get_ret('TIP') - get_ret('IEF')
    usd_val = get_ret('UUP')
    
    # =======================================================
    # 🧠 架构师级更新：实装 SPY 5阶趋势状态机，精准捕捉“力竭”与“回调”
    # =======================================================
    spy_ts = df['SPY'].dropna()
    is_bullish = False
    if len(spy_ts) > 120:
        spy_cur = float(spy_ts.iloc[-1])
        ma20 = float(spy_ts.rolling(20).mean().iloc[-1])
        ma60 = float(spy_ts.rolling(60).mean().iloc[-1])
        ma120 = float(spy_ts.rolling(120).mean().iloc[-1])
        
        if spy_cur > ma20 and ma20 > ma60 and ma60 > ma120:
            spy_status = "🔥 强多头 (完美均线多头排列)"
            is_bullish = True
        elif ma20 > spy_cur > ma60 and ma60 > ma120:
            spy_status = "⚠️ 多头回调 (跌破20日线，短期喘息)"
            is_bullish = True  # 核心趋势未破，仍定性为上升通道
        elif spy_cur < ma60 and ma20 > ma120:
            spy_status = "🌩️ 上涨力竭 (跌破60日生命线/顶背离)"
            is_bullish = False # 核心趋势已破，警报拉响
        elif spy_cur < ma20 and ma20 < ma60 and ma60 < ma120:
            spy_status = "❄️ 强空头 (完美均线空头排列)"
            is_bullish = False
        else:
            spy_status = "⚖️ 震荡分化 (均线交叉纠缠/无趋势)"
            is_bullish = False
    else:
        spy_status = "未知 (数据不足)"
    # =======================================================

    st.header("1️⃣ 宏观底色 (Macro Dashboard)")
    if tlt_shy_diff > 0: rate_txt = "📉 增长放缓"; rate_cls = "status-red" 
    else: rate_txt = "📈 增长强劲"; rate_cls = "status-green"
    if hyg_ief_diff > 0: risk_txt = "🦁 Risk-On"; risk_cls = "status-green"
    else: risk_txt = "❄️ Risk-Off"; risk_cls = "status-red"
    if tip_ief_diff > 0: inf_txt = "🎈 通胀升温"; inf_cls = "status-red"
    else: inf_txt = "💧 通胀回落"; inf_cls = "status-green"
    if usd_val > 0: usd_txt = "💪 美元走强"; usd_cls = "status-red"
    else: usd_txt = "🍃 美元走弱"; usd_cls = "status-green"

    c1, c2, c3, c4 = st.columns(4)
    def draw_card(col, title, val, txt, cls, desc):
        with col:
            st.markdown(f"**{title}**")
            st.markdown(f"<div class='metric-value'>{val:.2f}%</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='{cls}'>{txt}</div>", unsafe_allow_html=True)
            st.caption(desc)
    draw_card(c1, "增长预期 (TLT-SHY)", tlt_shy_diff, rate_txt, rate_cls, "长债跑赢 = 衰退预期")
    draw_card(c2, "风险偏好 (HYG-IEF)", hyg_ief_diff, risk_txt, risk_cls, "利差收窄 = 追逐风险")
    draw_card(c3, "通胀预期 (TIP-IEF)", tip_ief_diff, inf_txt, inf_cls, "抗通胀债跑赢 = 预期抬头")
    draw_card(c4, "美元压力 (UUP)", usd_val, usd_txt, usd_cls, "美元上涨 = 流动性收紧")
    
    st.markdown("---")
    
    # 获取云端时钟状态以对齐显示
    raw_probs, api_clock_regime = fetch_macro_scores(df)

    st.markdown(f"### 🕰️ 宏观周期定位: <span style='color:#3498DB'>{api_clock_regime}</span>", unsafe_allow_html=True)
    
    col_clock, col_logic = st.columns([1.5, 1])
    
    with col_clock:
        fig_clock = go.Figure()
        limit = 3.0
        fig_clock.add_shape(type="rect",x0=0,y0=0,x1=limit,y1=limit,fillcolor="rgba(231,76,60,0.1)",line_width=0) 
        fig_clock.add_shape(type="rect",x0=0,y0=-limit,x1=limit,y1=0,fillcolor="rgba(46,204,113,0.1)",line_width=0) 
        fig_clock.add_shape(type="rect",x0=-limit,y0=-limit,x1=0,y1=0,fillcolor="rgba(52,152,219,0.1)",line_width=0) 
        fig_clock.add_shape(type="rect",x0=-limit,y0=0,x1=0,y1=limit,fillcolor="rgba(241,196,15,0.1)",line_width=0) 
        
        df_track = df_z.iloc[-60:] 
        fig_clock.add_trace(go.Scatter(x=df_track['Growth'], y=df_track['Inflation'], mode='lines', name='过去60天路径', line=dict(color='gray', width=1, dash='dot')))
        fig_clock.add_trace(go.Scatter(x=[curr_clock_g], y=[curr_clock_i], mode='markers+text', name='当前位置', marker=dict(color='#E74C3C', size=15, symbol='star'), text=["📍我们在这"], textposition="top center"))
        
        fig_clock.update_layout(height=350, margin=dict(l=20,r=20,t=20,b=20), xaxis=dict(title="<-- 衰退 (Growth -) | 复苏 (Growth +) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), yaxis=dict(title="<-- 通缩 (Inflation -) | 通胀 (Inflation +) -->", range=[-limit, limit], zeroline=True, zerolinewidth=2), showlegend=False, plot_bgcolor='#222', paper_bgcolor='#222', font=dict(color='#ddd'))
        
        fig_clock.add_annotation(x=1.5, y=1.5, text="🔥 过热 (Overheat)", showarrow=False, font=dict(color="#E74C3C", size=14))
        fig_clock.add_annotation(x=1.5, y=-1.5, text="🟢 复苏 (Recovery)", showarrow=False, font=dict(color="#2ECC71", size=14))
        fig_clock.add_annotation(x=-1.5, y=-1.5, text="❄️ 衰退 (Reflation)", showarrow=False, font=dict(color="#3498DB", size=14))
        fig_clock.add_annotation(x=-1.5, y=1.5, text="🌧️ 滞胀 (Stagflation)", showarrow=False, font=dict(color="#F1C40F", size=14))
        st.plotly_chart(fig_clock, use_container_width=True)

    with col_logic:
        st.markdown("#### 📐 模型逻辑 (Qualitative Logic)")
        st.info(f"**当前坐标:** X(增长)={curr_clock_g:.2f} | Y(通胀)={curr_clock_i:.2f}")
        
        st.markdown("""
        <div class="formula-box">
        <b>1. 📈 增长轴 (X轴) - 消费折现:</b><br>
        通过对比 <code>可选消费(XLY)</code> 与 <code>必选消费(XLP)</code> 的相对强弱。<br>
        <span style='color:#aaa; font-size:12px;'><i>逻辑：当经济向好时，居民更愿意借贷购买汽车等非刚需品；反之则退守牙膏可乐等必需品。数值向右代表经济动能扩张。</i></span>
        </div>
        <div class="formula-box">
        <b>2. 🎈 通胀轴 (Y轴) - 聪明钱定价:</b><br>
        通过对比 <code>抗通胀债(TIP)</code> 与 <code>中期国债(IEF)</code> 的相对强弱。<br>
        <span style='color:#aaa; font-size:12px;'><i>逻辑：当大资金预期物价飞涨时，会疯狂抢筹带有通胀保护条款的 TIP 避险。数值向上代表市场正在定价恶性通胀（当 Z-Score=0 时，代表预期已完美均值回归）。</i></span>
        </div>
        <div class="formula-box">
        <b>3. 🎯 极值定位 (Z-Score):</b><br>
        <span style='color:#aaa; font-size:12px;'><i>不看短期绝对涨跌，而是将当前斜率与<b>过去 3 年 (750日)</b> 的历史平均水位进行对比，过滤日常噪音，定位宏观极值点。</i></span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    st.header("🔬 债市阶梯深度透视 (Bond Ladder)")
    r_tlt, r_ief, r_shy = get_ret('TLT'), get_ret('IEF'), get_ret('SHY')
    
    if r_tlt > r_ief > r_shy: 
        curve_shape = "🟢 牛陡 (Bull Steepening)"
        curve_desc = "长债大幅跑赢短债。市场正在强烈定价衰退与未来的降息预期，资金涌入长端国债避险。"
    elif r_shy > r_ief > r_tlt: 
        curve_shape = "🔴 熊平 (Bear Flattening)"
        curve_desc = "短端承压大于长端。市场正在定价加息、紧缩或滞胀风险，流动性预期恶化。"
    else: 
        curve_shape = "⚖️ 混合震荡 (Mixed)"
        curve_desc = "长短端收益率变化不一致，市场对未来宏观路径存在分歧，缺乏单边趋势。"

    c_hyg, c_lqd, c_ief = get_ret('HYG'), get_ret('LQD'), get_ret('IEF')
    
    if c_hyg > c_lqd > c_ief:
        credit_desc = "垃圾债跑赢投资级和国债。信用利差收窄，资金无惧违约风险，处于极度 Risk-On 追逐收益的状态。"
    elif c_ief > c_lqd > c_hyg:
        credit_desc = "国债大幅跑赢信用债。信用利差走阔，资金担忧企业违约风险，处于极度 Risk-Off 的避险状态。"
    else:
        credit_desc = "信用利差保持平稳，市场风险偏好处于中性温和状态。"
    
    c_b1, c_b2 = st.columns(2)
    with c_b1:
        st.info(f"📈 **利率形态：{curve_shape}**")
        rates_data = {"SHY (短)": r_shy, "IEF (中)": r_ief, "TLT (长)": r_tlt}
        fig_r = px.bar(pd.DataFrame(list(rates_data.items()), columns=['期限', '涨跌']), x='涨跌', y='期限', orientation='h', color='涨跌', color_continuous_scale='RdYlGn')
        fig_r.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_r, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 宏观结论：</b>{curve_desc}</div>", unsafe_allow_html=True)

    with c_b2:
        st.info(f"🦁 **信用风险偏好**")
        credit_data = {"HYG (垃圾)": c_hyg, "LQD (投资)": c_lqd, "IEF (国债)": c_ief}
        fig_c = px.bar(pd.DataFrame(list(credit_data.items()), columns=['资产', '涨跌']), x='涨跌', y='资产', orientation='h', color='涨跌', color_continuous_scale='RdYlGn')
        fig_c.update_layout(height=200, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a', font=dict(color='#ddd'))
        st.plotly_chart(fig_c, use_container_width=True)
        st.markdown(f"<div class='conclusion-box'><b>🧠 资金行为：</b>{credit_desc}</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("2️⃣ 聪明钱因子 (Smart Money Factors)")
    off_f = {"动量": get_ret('MTUM'), "小盘": get_ret('IWM'), "高贝塔": get_ret('SPHB'), "投机": get_ret('ARKK')}
    def_f = {"低波": get_ret('USMV'), "质量": get_ret('QUAL'), "价值": get_ret('VLUE'), "红利": get_ret('VIG')}
    
    off_mean = sum(off_f.values()) / len(off_f)
    def_mean = sum(def_f.values()) / len(def_f)
    best_f = max({**off_f, **def_f}, key={**off_f, **def_f}.get)
    
    if off_mean > def_mean + 0.5:
        factor_desc = "⚔️ **进攻占优 (Risk-On):** 动量、高贝塔等高弹性因子整体领涨，资金疯狂追逐利润，市场情绪较为亢奋。"
    elif def_mean > off_mean + 0.5:
        factor_desc = "🛡️ **防守占优 (Risk-Off):** 红利、低波等防御因子抗跌，资金正在进行避险调仓，防范下行风险。"
    else:
        factor_desc = "⚖️ **均衡博弈:** 进攻与防守因子整体表现差异不大，市场处于风格切换的震荡期或缺乏主线。"
    
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        fig_off = px.bar(pd.DataFrame(list(off_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-5,5])
        fig_off.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="⚔️ 进攻组 (Risk)")
        st.plotly_chart(fig_off, use_container_width=True)
    with c_f2:
        fig_def = px.bar(pd.DataFrame(list(def_f.items()), columns=['F', 'V']), x='V', y='F', orientation='h', color='V', color_continuous_scale='RdYlGn', range_color=[-5,5])
        fig_def.update_layout(height=200, plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'), title="🛡️ 防守组 (Safety)")
        st.plotly_chart(fig_def, use_container_width=True)

    st.markdown(f"<div class='conclusion-box'><b>🧠 因子轮动结论：</b>{factor_desc} (当前市场最强单一因子为: <b>{best_f}</b>)</div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("3️⃣ 四大剧本推演 (The Four Horsemen)")

    prob_a = int(raw_probs.get("Soft", 0) * 100)
    prob_b = int(raw_probs.get("Hot", 0) * 100)
    prob_c = int(raw_probs.get("Stag", 0) * 100)
    prob_d = int(raw_probs.get("Rec", 0) * 100)

    def check(condition, desc_pass, desc_fail):
        if condition: return f"<div class='ev-item'><span class='ev-pass'>✅</span> <span>{desc_pass}</span></div>"
        else: return f"<div class='ev-item'><span class='ev-fail'>⚪</span> <span>{desc_fail}</span></div>"

    # =======================================================
    # 🧠 将全新的 5阶 SPY 状态深度融入白盒化推演中
    # =======================================================
    items_a = [
        check("Recovery" in api_clock_regime, "时钟指向复苏/软着陆", f"时钟不符 ({api_clock_regime})"),
        check(is_bullish, f"美股维持上升通道 ({spy_status})", f"美股动能破坏 ({spy_status})"),
        check(get_ret('XLY') > get_ret('XLP'), f"消费信心强 (XLY收益 > XLP)", f"消费防御占优 (XLY弱于XLP)"),
        check(get_ret('XLK') > 0, f"科技领涨 (+{get_ret('XLK'):.1f}%)", f"科技走弱 ({get_ret('XLK'):.1f}%)"),
        check(hyg_ief_diff > -0.5, f"信用风险低 (HYG-IEF利差: {hyg_ief_diff:.2f}%)", f"信用利差走阔 ({hyg_ief_diff:.2f}%)")
    ]
    items_b = [
        check("Overheat" in api_clock_regime, "时钟指向过热/再通胀", f"时钟不符 ({api_clock_regime})"),
        check(get_ret('CPER') > 0 or get_ret('USO') > 0, f"大宗商品上涨 (铜{get_ret('CPER'):.1f}%, 油{get_ret('USO'):.1f}%)", f"大宗走弱 (铜{get_ret('CPER'):.1f}%, 油{get_ret('USO'):.1f}%)"),
        check(get_ret('XLI') > get_ret('SPY'), "工业/制造跑赢大盘 (XLI > SPY)", "工业跑输大盘"),
        check(tip_ief_diff > 0, f"通胀预期抬头 (TIP-IEF: {tip_ief_diff:.2f}%)", f"通胀预期平稳 ({tip_ief_diff:.2f}%)"),
        check(get_ret('KRE') > 0, f"银行/金融活跃 (+{get_ret('KRE'):.1f}%)", f"银行走弱 ({get_ret('KRE'):.1f}%)")
    ]
    items_c = [
        check("Stagflation" in api_clock_regime, "时钟指向滞胀", f"时钟不符 ({api_clock_regime})"),
        check("熊平" in curve_shape, f"曲线熊平 (短端利率上行抗通胀)", f"形态不符 ({curve_shape})"),
        check(get_ret('GLD') > get_ret('SPY'), "黄金跑赢美股 (GLD > SPY)", "黄金未跑赢"),
        check(get_ret('VLUE') > get_ret('MTUM'), "价值跑赢成长 (VLUE > MTUM)", "成长跑赢价值"),
        check(not is_bullish, f"美股上升趋势破坏 ({spy_status})", f"美股仍具韧性 ({spy_status})")
    ]
    items_d = [
        check("Reflation" in api_clock_regime, "时钟指向衰退", f"时钟不符 ({api_clock_regime})"),
        check("牛陡" in curve_shape, f"曲线牛陡 (长债买盘汹涌/衰退交易)", f"形态不符 ({curve_shape})"),
        check(tlt_shy_diff > 1.5, f"长债大涨避险 (TLT-SHY: {tlt_shy_diff:.2f}%)", f"长债平淡 ({tlt_shy_diff:.2f}%)"),
        check(get_ret('XLP') > get_ret('SPY'), "必选消费/公用抗跌 (XLP > SPY)", "防御板块未跑赢"),
        check(get_ret('HYG') < -1, f"信用利差崩塌 ({get_ret('HYG'):.1f}%)", f"信用尚可 ({get_ret('HYG'):.1f}%)")
    ]

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"<div class='scenario-card'><b>🌤️ 软着陆 ({prob_a}%)</b><div class='evidence-list'>{''.join(items_a)}</div></div>", unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='scenario-card'><b>🔥 再通胀 ({prob_b}%)</b><div class='evidence-list'>{''.join(items_b)}</div></div>", unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='scenario-card'><b>🌧️ 滞胀 ({prob_c}%)</b><div class='evidence-list'>{''.join(items_c)}</div></div>", unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='scenario-card'><b>❄️ 衰退 ({prob_d}%)</b><div class='evidence-list'>{''.join(items_d)}</div></div>", unsafe_allow_html=True)

    st.markdown("---")

    st.header("4️⃣ 分场景实战推荐 (Sector & Stock Picks)")
    st.caption("穿透板块表面：当板块强势时，自动为您展开其底层三大权重龙头股进行精确制导。")
    with st.expander("🛡️ 白盒化声明：为什么 XLF, XLB, XLRE, XLY 等常见大宽基被系统剔除？"):
        st.markdown("""
        根据 **《Moltbot 白盒化设计第一基本法》**，本系统拒绝黑盒逻辑。以下传统宽基 ETF 因宏观特征不纯、弹性不足或逻辑冲突，已被剥夺“战术统帅”资格，由更锋利的特种部队替代：
        
        * 🚫 **XLF (大金融)**：内部逻辑打架（商业银行吃息差盼加息 vs 投行发债盼降息），走势温吞。**👉 战术替代：由对利率和经济复苏极度敏感的 `KRE (区域银行)` 填补。**
        * 🚫 **XLB (大材料)**：成分极其不纯（包含造纸箱、卖涂料等无通胀避险属性的伪周期股）。**👉 战术替代：由纯血通胀斗士 `CPER (铜)`、`PICK (矿业)`、`URA (铀矿)` 填补。**
        * 🚫 **XLRE (大地产)**：被居家办公(WFH)摧毁的商业地产(写字楼)严重拖累，降息也无法挽救其空置率。**👉 战术替代：由纯粹反映住宅供需短缺的 `ITB (房屋建筑)` 填补。**
        * 🚫 **XLY (可选消费)**：寡头垄断严重失真（AMZN 和 TSLA 两家占比近 40%），买 XLY 等同于赌财报，无法反映宏观消费全貌。**👉 战术替代：由等权重的 `XRT (零售)` 填补。**
        
        *💡 战术纪律：在宏观对冲的战场上，“平庸与模糊”就是最大的风险。宁可留白，绝不收录温吞水资产。如果未来以上宏观压制因素解除，主理人可随时将其重新编入字典。*
        """)
    def render_picks_with_stocks(targets, col):
        for t in targets:
            if t not in df.columns: continue
            try:
                ts = df[t].dropna()
                if len(ts) < 200: continue
                
                curr = float(ts.iloc[-1])
                ma20 = float(ts.rolling(20).mean().iloc[-1])
                ma60 = float(ts.rolling(60).mean().iloc[-1])
                
                roll_mean = float(ts.rolling(250).mean().iloc[-1])
                roll_std = float(ts.rolling(250).std().iloc[-1])
                z_score = (curr - roll_mean) / roll_std if roll_std != 0 else 0.0
                
                is_active = ma20 > ma60
                display_name = ASSET_NAMES.get(t, t)
                
                if is_active: 
                    col.markdown(f"✅ **{t} ({display_name})**<br><span style='font-size:12px;color:#aaa'>Z: {z_score:.2f} | 强势</span>", unsafe_allow_html=True)
                else: 
                    col.markdown(f"<span style='color:#555'>🔒 {t} ({display_name})</span><br><span style='font-size:12px;color:#444'>Z: {z_score:.2f} | 观察 (板块休整)</span>", unsafe_allow_html=True)
                
                if t in TOP_HOLDINGS:
                    for sub_t in TOP_HOLDINGS[t]:
                        if sub_t in df.columns:
                            sub_ts = df[sub_t].dropna()
                            if len(sub_ts) < 200: continue
                            sub_curr = float(sub_ts.iloc[-1])
                            sub_rm = float(sub_ts.rolling(250).mean().iloc[-1])
                            sub_rs = float(sub_ts.rolling(250).std().iloc[-1])
                            sub_z = (sub_curr - sub_rm) / sub_rs if sub_rs != 0 else 0.0
                            
                            sub_m20 = float(sub_ts.rolling(20).mean().iloc[-1])
                            sub_m60 = float(sub_ts.rolling(60).mean().iloc[-1])
                            sub_icon = "🔥" if sub_m20 > sub_m60 else "⏱️"
                            
                            opacity_style = "opacity: 1.0;" if is_active else "opacity: 0.4;"
                            col.markdown(f"<div class='sub-ticker' style='{opacity_style}'>{sub_icon} <b>{sub_t}</b> ({ASSET_NAMES.get(sub_t, sub_t)}) | Z: {sub_z:.1f}</div>", unsafe_allow_html=True)
            except: continue

    col_pa, col_pb, col_pc, col_pd = st.columns(4)
    with col_pa:
        st.subheader("🟢 买入：软着陆")
        render_picks_with_stocks(TARGETS_A, col_pa)
    with col_pb:
        st.subheader("🟡 买入：再通胀")
        render_picks_with_stocks(TARGETS_B, col_pb)
    with col_pc:
        st.subheader("🟠 买入：滞胀")
        render_picks_with_stocks(TARGETS_C, col_pc)
    with col_pd:
        st.subheader("🔴 买入：衰退")
        render_picks_with_stocks(TARGETS_D, col_pd)

else:
    st.info("⏳ 正在计算宏观时钟与全证据链数据 (Fetching Data)...")