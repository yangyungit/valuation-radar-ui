import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="市场分化雷达", layout="wide", page_icon="📡")

st.title("📡 市场分化雷达 (Market Differentiation Radar)")
st.caption("核心监控：**共振** (大家都一样) vs **分化** (只有少数人赢) | 数据范围：**过去 10 年**")

# --- 1. 数据引擎 ---
@st.cache_data(ttl=3600*4)
def get_radar_data():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650) # 10年
    
    indices = ['SPY', 'RSP']
    sectors = {'XLK': '科技', 'XLF': '金融', 'XLV': '医疗', 'XLY': '可选', 'XLP': '必选', 'XLE': '能源', 'XLI': '工业', 'XLB': '材料', 'XLU': '公用', 'XLRE': '地产', 'XLC': '通讯'}
    tickers = indices + list(sectors.keys())
    
    try:
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']
        data = data.ffill()
        return data, sectors
    except: return pd.DataFrame(), {}

df, sector_map = get_radar_data()

if not df.empty:
    # 指标计算
    df['SPY_Norm'] = (df['SPY'] / df['SPY'].iloc[0] - 1) * 100
    df['RSP_Norm'] = (df['RSP'] / df['RSP'].iloc[0] - 1) * 100
    
    sector_cols = list(sector_map.keys())
    df['Dispersion'] = df[sector_cols].pct_change().std(axis=1) * 100 
    df['Dispersion_MA20'] = df['Dispersion'].rolling(window=20).mean()
    
    # 图表 1: 抱团指数
    st.subheader("🛠️ 抱团指数：市值加权(红) vs 等权平均(蓝)")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=df.index, y=df['SPY_Norm'], name="SPY (市值) %", line=dict(color='#E74C3C', width=2)))
    fig1.add_trace(go.Scatter(x=df.index, y=df['RSP_Norm'], name="RSP (等权) %", line=dict(color='#3498DB', width=2), fill='tonexty'))
    fig1.update_layout(height=450, hovermode="x unified", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig1, use_container_width=True)

    st.markdown("---")

    # 图表 2: 板块离散度
    st.subheader("🌊 板块离散度 (Dispersion)")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=df.index, y=df['Dispersion_MA20'], name="离散度 (MA20)", line=dict(color='#8E44AD', width=2), fill='tozeroy'))
    fig2.add_hline(y=1.5, line_dash="dot", line_color="red", annotation_text="混乱")
    fig2.add_hline(y=0.5, line_dash="dot", line_color="green", annotation_text="一致")
    fig2.update_layout(height=400, hovermode="x unified", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig2, use_container_width=True)

else:
    st.info("⏳ 正在拉取分化数据...")