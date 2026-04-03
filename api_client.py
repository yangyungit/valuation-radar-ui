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
        return data.ffill().dropna(how='all')
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=3600*24)
def get_stock_metadata(tickers):
    """获取市值和近似股息率等公开元数据 (10线程并发 FastInfo 版)

    div_yield 使用 lastDividendValue * 4 / price 近似年化；
    月度付息资产会低估，已在 DEV_LOG 记录。
    """
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(t):
        try:
            fi = yf.Ticker(t).fast_info
            mcap = fi.get('marketCap', 0) or 0
            last_div = fi.get('lastDividendValue', 0) or 0
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = round(last_div * 4 / price * 100, 2) if (last_div > 0 and price > 0) else 0.0
            return t, {"mcap": mcap, "div_yield": div_yield}
        except Exception:
            return t, {"mcap": 0, "div_yield": 0.0}

    metadata = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            metadata[t] = data
    return metadata



@st.cache_data(ttl=3600*4)
def get_arena_a_factors(tickers: tuple) -> dict:
    """获取 A 组 ScorecardA 所需四维避风港因子 (252 日回溯)：
    - div_yield:  年化股息率 (%)
    - max_dd_252: 近252日最大回撤 (负数)
    - spy_corr:   与 SPY 日收益率的皮尔逊相关系数
    - ann_vol:    252日年化波动率
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    try:
        spy_hist = yf.Ticker("SPY").history(period="1y")
        if not spy_hist.empty and len(spy_hist) >= 60:
            spy_prices = spy_hist["Close"].dropna().astype(float)
            spy_daily_ret = spy_prices.pct_change().dropna()
        else:
            spy_daily_ret = pd.Series(dtype=float)
    except Exception:
        spy_daily_ret = pd.Series(dtype=float)

    def _fetch_one(t):
        try:
            stock = yf.Ticker(t)
            fi = stock.fast_info
            mcap = fi.get('marketCap', 0) or 0
            last_div = fi.get('lastDividendValue', 0) or 0
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = round(last_div * 4 / price * 100, 2) if (last_div > 0 and price > 0) else 0.0

            hist = stock.history(period="1y")
            if hist.empty or len(hist) < 60:
                return t, {"div_yield": div_yield, "max_dd_252": 0.0,
                           "spy_corr": 0.5, "ann_vol": 0.30}

            prices = hist["Close"].dropna().astype(float)
            daily_ret = prices.pct_change().dropna()

            roll_max = prices.cummax()
            max_dd = float((prices / roll_max - 1.0).min())

            vol = float(daily_ret.std())
            ann_vol = vol * np.sqrt(252) if vol > 1e-9 else 0.30
            if np.isnan(ann_vol) or np.isinf(ann_vol):
                ann_vol = 0.30

            if len(spy_daily_ret) > 30:
                aligned = pd.concat([daily_ret, spy_daily_ret], axis=1).dropna()
                if len(aligned) > 30:
                    spy_corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                    if np.isnan(spy_corr) or np.isinf(spy_corr):
                        spy_corr = 0.5
                else:
                    spy_corr = 0.5
            else:
                spy_corr = 0.5

            return t, {
                "div_yield": div_yield,
                "max_dd_252": max_dd,
                "spy_corr": spy_corr,
                "ann_vol": ann_vol,
            }
        except Exception:
            return t, {"div_yield": 0.0, "max_dd_252": 0.0,
                       "spy_corr": 0.5, "ann_vol": 0.30}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600*4)
def get_arena_b_factors(tickers: tuple) -> dict:
    """获取 B 组 ScorecardB 所需四维慢变量因子：
    - div_yield:      年化股息率 (%)
    - max_dd_252:     近252日最大回撤 (负数)
    - sharpe_252:     近252日年化夏普比率
    - log_mcap:       log10(市值)
    - eps_stability:  EPS稳定性代理 (年化波动率倒数)
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    def _fetch_one(t):
        try:
            stock = yf.Ticker(t)
            fi = stock.fast_info
            mcap = fi.get('marketCap', 0) or 0
            if mcap < 1e6:
                mcap = 1e9
            last_div = fi.get('lastDividendValue', 0) or 0
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = round(last_div * 4 / price * 100, 2) if (last_div > 0 and price > 0) else 0.0

            hist = stock.history(period="1y")
            if hist.empty or len(hist) < 60:
                return t, {"div_yield": div_yield, "max_dd_252": 0.0, "sharpe_252": 0.0,
                           "log_mcap": float(np.log10(max(mcap, 1e6))), "eps_stability": 0.0}

            prices = hist["Close"].dropna().astype(float)
            daily_ret = prices.pct_change().dropna()

            roll_max = prices.cummax()
            max_dd = float((prices / roll_max - 1.0).min())

            vol = float(daily_ret.std())
            sharpe = (float(daily_ret.mean()) / vol * np.sqrt(252)) if vol > 1e-9 else 0.0
            if np.isnan(sharpe) or np.isinf(sharpe):
                sharpe = 0.0

            ann_vol = vol * np.sqrt(252)
            eps_stab = 1.0 / max(ann_vol, 0.01)

            return t, {
                "div_yield": div_yield,
                "max_dd_252": max_dd,
                "sharpe_252": sharpe,
                "log_mcap": float(np.log10(max(mcap, 1e6))),
                "eps_stability": eps_stab,
            }
        except Exception:
            return t, {"div_yield": 0.0, "max_dd_252": 0.0, "sharpe_252": 0.0,
                       "log_mcap": 9.0, "eps_stability": 0.0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600*4)
def get_arena_c_factors(tickers: tuple) -> dict:
    """获取 C 组 ScorecardC 所需特殊因子：Forward EPS 增速 + 120日中长线相对强度 RS。
    tickers 用 tuple 传入以保证 st.cache_data 可序列化。
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    # 先取 SPY 基准 120 日收益（135d 确保拿满 121 根 bar）
    try:
        spy_hist = yf.Ticker("SPY").history(period="135d")
        if not spy_hist.empty and len(spy_hist) >= 121:
            spy_prices = spy_hist["Close"].dropna().astype(float)
            spy_ret120 = float((spy_prices.iloc[-1] / spy_prices.iloc[-121] - 1) * 100)
        else:
            spy_ret120 = 0.0
    except Exception:
        spy_ret120 = 0.0

    def _fetch_one(t):
        try:
            stock = yf.Ticker(t)
            info = {}
            try:
                info = stock.info or {}
            except Exception:
                pass
            # earningsGrowth 为华尔街一致预期 YoY EPS 增速（小数形式）
            earnings_growth = info.get("earningsGrowth") or info.get("revenueGrowth") or 0.0

            # 120 日中长线相对强度 RS（vs SPY 超额收益率）
            hist = stock.history(period="135d")
            if not hist.empty and len(hist) >= 121:
                prices = hist["Close"].dropna().astype(float)
                ret120 = float((prices.iloc[-1] / prices.iloc[-121] - 1) * 100)
                rs_120d = ret120 - spy_ret120
            else:
                rs_120d = 0.0

            return t, {"earnings_growth": float(earnings_growth), "rs_120d": rs_120d}
        except Exception:
            return t, {"earnings_growth": 0.0, "rs_120d": 0.0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600*4)
def get_arena_d_factors(tickers: tuple) -> dict:
    """获取 D 组 ScorecardD 所需三维因子：
    - vol_z:     5日均量 Z-Score（相对60日基准，量价共振烈度）
    - rs_20d:    近20日相对 SPY 超额收益率（%，相对强度 Alpha）
    - ma60_dist: 当前价格距 MA60 偏离百分比（%，均线起飞姿态）
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    # 先取 SPY 基准 20 日收益
    try:
        spy_hist = yf.Ticker("SPY").history(period="65d")
        if not spy_hist.empty and len(spy_hist) >= 21:
            spy_prices = spy_hist["Close"].dropna().astype(float)
            spy_ret20 = float((spy_prices.iloc[-1] / spy_prices.iloc[-21] - 1) * 100)
        else:
            spy_ret20 = 0.0
    except Exception:
        spy_ret20 = 0.0

    def _fetch_one(t):
        try:
            hist = yf.Ticker(t).history(period="65d")
            if hist.empty or len(hist) < 10:
                return t, {"vol_z": 0.0, "rs_20d": 0.0, "ma60_dist": 0.0}

            prices = hist["Close"].dropna().astype(float)
            vol    = hist["Volume"].dropna().astype(float)

            # Vol Z-Score (5日均量 vs 60日基线)
            mu, sigma = vol.mean(), vol.std()
            recent5   = vol.tail(5).mean()
            vol_z = float((recent5 - mu) / sigma) if sigma > 0 else 0.0

            # RS 20日超额收益
            if len(prices) >= 21:
                ret20 = float((prices.iloc[-1] / prices.iloc[-21] - 1) * 100)
                rs_20d = ret20 - spy_ret20
            else:
                rs_20d = 0.0

            # MA60 偏离百分比
            if len(prices) >= 60:
                ma60 = prices.tail(60).mean()
            else:
                ma60 = prices.mean()
            ma60_dist = float((prices.iloc[-1] / ma60 - 1) * 100) if ma60 > 0 else 0.0

            return t, {"vol_z": vol_z, "rs_20d": rs_20d, "ma60_dist": ma60_dist}
        except Exception:
            return t, {"vol_z": 0.0, "rs_20d": 0.0, "ma60_dist": 0.0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600)
def fetch_macro_scores(df, clock_g=None, clock_i=None):
    """将公开 DataFrame 发送到云端，换取机密打分结果"""
    try:
        # 将 DataFrame 压缩为 JSON 字符串
        payload = {"df_json": df.to_json(orient="split")}
        if clock_g is not None and clock_i is not None:
            payload["clock_g"] = float(clock_g)
            payload["clock_i"] = float(clock_i)
        response = requests.post(f"{API_BASE_URL}/api/v1/calculate_macro", json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data["raw_probs"], data["clock_regime"]
    except Exception as e:
        st.error(f"🚨 云端算力引擎请求失败: {e}")
        return {"Soft": 0, "Hot": 0, "Stag": 0, "Rec": 0}, "未知"



@st.cache_data(ttl=3600*4)
def fetch_rolling_backtest(df, group_assignments: dict, regime_history: dict = None,
                           trim_enabled: bool = True, drift_threshold: float = 0.30,
                           arena_history: dict = None) -> dict:
    """发送价格数据和 Core-Satellite 分组映射给后端，换取 VectorBT 动态滚动回测结果。
    group_assignments : {ticker: group}  group in ['A','B','C','D']
    regime_history    : {"YYYY-MM": {"Soft":f,"Hot":f,"Stag":f,"Rec":f}} — Page 1 月度历史裁决表
    arena_history     : {"YYYY-MM": {"C":[{ticker,score}...],"D":[...]}} — Page 4 Arena 月度 SSOT
                        传入后回测引擎用 Arena 历史选股替代 PIT 动量逻辑，确保 C/D 卫星与 Page 4 完全一致。
    返回: {nav, spy_nav, total_ret, spy_total_ret, sharpe, calmar, max_dd,
           n_rebal, sim_start, sim_end, weight_history}
    或 {"error": "..."} on failure.
    """
    try:
        payload = {
            "df_json": df.to_json(orient="split"),
            "group_assignments": group_assignments,
            "trim_enabled": trim_enabled,
            "drift_threshold": drift_threshold,
        }
        if regime_history:
            payload["regime_history"] = regime_history
        if arena_history:
            payload["arena_history"] = arena_history
        response = requests.post(f"{API_BASE_URL}/api/v1/rolling_backtest", json=payload, timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": f"滚动回测引擎连接失败: {e}"}


@st.cache_data(ttl=3600)
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


@st.cache_data(ttl=3600)
def fetch_vcp_analysis(ohlcv_df, lookback_days=180):
    """发送 OHLCV 数据到后端 VCP 分析引擎，获取 VCP 形态诊断与 TWAP 建议"""
    try:
        payload = {
            "ohlcv_json": ohlcv_df.to_json(orient="split"),
            "lookback_days": lookback_days,
        }
        response = requests.post(f"{API_BASE_URL}/api/v1/vcp_analysis", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": f"VCP 分析引擎连接失败: {e}"}


# ==========================================
# 分级缓存清除工具
# ==========================================
def clear_api_caches():
    """轻量刷新：只清除 API 请求和实时因子缓存（秒级可恢复），
    保留重型历史数据下载缓存（_fetch_backfill_prices / get_global_data / fetch_rolling_backtest）。
    """
    fetch_core_data.clear()
    get_stock_metadata.clear()
    get_arena_a_factors.clear()
    get_arena_b_factors.clear()
    get_arena_c_factors.clear()
    get_arena_d_factors.clear()
    fetch_macro_scores.clear()
    fetch_funnel_scores.clear()
    fetch_vcp_analysis.clear()