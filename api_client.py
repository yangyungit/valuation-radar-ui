import requests
import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# ==========================================
# 1. 核心机密数据获取 (通过 API 向后厨请求)
# ==========================================
API_BASE_URL = "http://127.0.0.1:8000"

@st.cache_data(ttl=3600)
def fetch_core_data():
    """通过 REST API 获取核心资产字典与研报"""
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/stock_pool_data", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"🚨 核心引擎失联，API 请求失败: {e}")
        st.stop()

# ==========================================
# 2. 公共市场数据获取 (前端负责拉取公开行情)
# ==========================================
# 架构规范：yfinance 等公开行情数据不属于商业机密，
# 为了减轻 API 服务器压力，公开数据的拉取可以直接在前端执行。
@st.cache_data(ttl=3600*4)
def get_global_data(tickers, years=4):
    if not tickers: return pd.DataFrame()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*years)
    try:
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']
        data = data[data.index.dayofweek < 5] # 过滤周末
        return data.ffill().dropna(how='all')
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=3600*24)
def get_stock_metadata(tickers):
    """获取市值等公开元数据"""
    metadata = {}
    for t in tickers:
        try:
            stock = yf.Ticker(t)
            info = stock.info
            metadata[t] = {"mcap": info.get('marketCap', 1e10)}
        except:
            metadata[t] = {"mcap": 1e10}
    return metadata

import json

def fetch_macro_scores(df):
    """将公开 DataFrame 发送到云端，换取机密打分结果"""
    try:
        # 将 DataFrame 压缩为 JSON 字符串
        payload = {"df_json": df.to_json(orient="split")}
        response = requests.post(f"{API_BASE_URL}/api/v1/calculate_macro", json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data["raw_probs"], data["clock_regime"]
    except Exception as e:
        st.error(f"🚨 云端算力引擎请求失败: {e}")
        return {"Soft": 0, "Hot": 0, "Stag": 0, "Rec": 0}, "未知"