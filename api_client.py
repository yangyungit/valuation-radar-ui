import requests
import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import json
import io

# ==========================================
# 1. 核心机密数据获取 (通过 API 向后厨请求)
# ==========================================
import os
import platform

# 自动判断当前是否为本地开发环境 (Mac系统自动判定为本地)
# 这样当你推送到云端(Linux环境)时，会自动切回生产 API，不需要手动来回改代码了！
if platform.system() == "Darwin" or os.environ.get("USE_LOCAL_API") == "true":
    API_BASE_URL = "http://localhost:8000" 
else:
    API_BASE_URL = "https://valuation-radar.onrender.com"

@st.cache_data(ttl=3600)
def fetch_core_data():
    """通过 REST API 获取核心资产字典与研报"""
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/stock_pool_data", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # 添加重试机制给 UI 更友好的体验
        st.warning("⚠️ 正在尝试重新连接核心计算引擎...")
        import time
        time.sleep(2)
        try:
            response = requests.get(f"{API_BASE_URL}/api/v1/stock_pool_data", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as retry_e:
            st.error(f"🚨 核心引擎彻底失联 (连接 {API_BASE_URL} 失败): {retry_e}")
            st.info("💡 请确保您已经在另一个终端中执行了： `cd valuation-radar && source ../system/venv/bin/activate && python api_server.py`")
            st.stop()
    except Exception as e:
        st.error(f"🚨 发生未知错误: {e}")
        st.stop()

# ==========================================
# 2. 公共市场数据获取 (前端负责拉取公开行情)
# ==========================================
# 架构规范：yfinance 等公开行情数据不属于商业机密，
# 为了减轻 API 服务器压力，公开数据的拉取可以直接在前端执行。
@st.cache_data(ttl=3600*4)
def get_global_data(tickers, years=4):
    # #region agent log
    import json
    import time
    def _write_debug_log(hypothesis_id, message, data):
        log_path = "/Users/zhanghao/yangyun/Code_Projects/valuation-radar-ui/.cursor/debug.log"
        log_entry = {
            "id": f"log_{int(time.time()*1000)}_{hypothesis_id}",
            "timestamp": int(time.time()*1000),
            "location": "api_client.py:get_global_data",
            "message": message,
            "data": data,
            "runId": "run2",
            "hypothesisId": hypothesis_id
        }
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
    t0 = time.time()
    _write_debug_log("H1_slow", "Starting get_global_data", {"num_tickers": len(tickers) if tickers else 0})
    # #endregion
    if not tickers: return pd.DataFrame()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*years)
    try:
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)['Close']
        if isinstance(data, pd.DataFrame):
            missing_tickers = [t for t in tickers if t not in data.columns or data[t].isnull().all()]
            if missing_tickers:
                import time as mod_time
                mod_time.sleep(1)
                retry_data = yf.download(missing_tickers, start=start_date, end=end_date, progress=False)
                if 'Close' in retry_data:
                    retry_close = retry_data['Close']
                    if isinstance(retry_close, pd.Series) and len(missing_tickers) == 1:
                        data[missing_tickers[0]] = retry_close
                    elif isinstance(retry_close, pd.DataFrame):
                        for t in missing_tickers:
                            if t in retry_close.columns and not retry_close[t].isnull().all():
                                data[t] = retry_close[t]

        data = data[data.index.dayofweek < 5]
        data = data.reindex(columns=tickers)
        res = data.ffill().dropna(how='all')
        # #region agent log
        _write_debug_log("H1_slow", "Finished get_global_data", {"duration_sec": time.time() - t0, "rows": len(res)})
        # #endregion
        return res
    except Exception as e:
        # #region agent log
        _write_debug_log("H1_slow", "Failed get_global_data", {"duration_sec": time.time() - t0, "error": str(e)})
        # #endregion
        return pd.DataFrame()

@st.cache_data(ttl=3600*24)
def get_stock_metadata(tickers):
    """获取市值等公开元数据 (FastInfo 加速版)"""
    # #region agent log
    import json
    import time
    def _write_debug_log(hypothesis_id, message, data):
        log_path = "/Users/zhanghao/yangyun/Code_Projects/valuation-radar-ui/.cursor/debug.log"
        log_entry = {
            "id": f"log_{int(time.time()*1000)}_{hypothesis_id}",
            "timestamp": int(time.time()*1000),
            "location": "api_client.py:get_stock_metadata",
            "message": message,
            "data": data,
            "runId": "run2",
            "hypothesisId": hypothesis_id
        }
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
    t0 = time.time()
    _write_debug_log("H2_slow", "Starting get_stock_metadata", {"num_tickers": len(tickers)})
    # #endregion
    metadata = {}
    for t in tickers:
        try:
            stock = yf.Ticker(t)
            mcap = stock.fast_info.get('marketCap', 1e10)
            metadata[t] = {"mcap": mcap}
        except:
            metadata[t] = {"mcap": 1e10}
    # #region agent log
    _write_debug_log("H2_slow", "Finished get_stock_metadata", {"duration_sec": time.time() - t0})
    # #endregion
    return metadata



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



def fetch_funnel_scores(df, tickers, meta_data, theme_heat_dict, macro_scores=None):
    """将沉重的公开数据和参数打包发给云端，换取打分结果"""
    try:
        payload = {
            "df_json": df.to_json(orient="split"),
            "tickers": tickers,
            "meta_data": meta_data,
            "theme_heat_dict": theme_heat_dict
        }
        if macro_scores is not None:
            payload["macro_scores"] = macro_scores
        response = requests.post(f"{API_BASE_URL}/api/v1/calculate_funnel", json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        
        # 将云端传回来的精英名单重组为 DataFrame
        metrics_df = pd.read_json(io.StringIO(data["metrics_json"]), orient="split")
        return metrics_df, data["spy_mom20"]
    except Exception as e:
        st.error(f"🚨 云端漏斗计算引擎连接失败: {e}")
        return pd.DataFrame(), 0.0