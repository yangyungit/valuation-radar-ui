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
    """获取 B 组 ScorecardB 所需慢变量因子：
    - div_yield:       年化股息率 (%)
    - max_dd_252:      近252日最大回撤 (负数)
    - sharpe_252:      近252日年化夏普比率
    - rs_120d:         120日相对 SPY 超额收益 (%)
    - log_mcap:        log10(市值)
    - eps_stability:   EPS稳定性代理 (年化波动率倒数)
    - revenue_growth:  Revenue 增速 (%)
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    spy_hist = yf.Ticker("SPY").history(period="1y")
    spy_prices = spy_hist["Close"].dropna().astype(float) if not spy_hist.empty else pd.Series(dtype=float)

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
                           "rs_120d": 0.0, "log_mcap": float(np.log10(max(mcap, 1e6))),
                           "eps_stability": 0.0, "revenue_growth": 0.0}

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

            rs_120d = 0.0
            if len(prices) >= 121 and len(spy_prices) >= 121:
                ret120 = float((prices.iloc[-1] / prices.iloc[-121] - 1) * 100)
                spy_ret120 = float((spy_prices.iloc[-1] / spy_prices.iloc[-121] - 1) * 100)
                rs_120d = ret120 - spy_ret120
                if np.isnan(rs_120d) or np.isinf(rs_120d):
                    rs_120d = 0.0

            try:
                fin = stock.financials
                if fin is not None and "Total Revenue" in fin.index and fin.shape[1] >= 2:
                    rev_curr = fin.loc["Total Revenue"].iloc[0]
                    rev_prev = fin.loc["Total Revenue"].iloc[1]
                    rev_growth = float((rev_curr - rev_prev) / abs(rev_prev) * 100) if rev_prev != 0 else 0.0
                else:
                    rev_growth = 0.0
            except Exception:
                rev_growth = 0.0
            if np.isnan(rev_growth) or np.isinf(rev_growth):
                rev_growth = 0.0

            return t, {
                "div_yield": div_yield,
                "max_dd_252": max_dd,
                "sharpe_252": sharpe,
                "rs_120d": rs_120d,
                "log_mcap": float(np.log10(max(mcap, 1e6))),
                "eps_stability": eps_stab,
                "revenue_growth": rev_growth,
            }
        except Exception:
            return t, {"div_yield": 0.0, "max_dd_252": 0.0, "sharpe_252": 0.0,
                       "rs_120d": 0.0, "log_mcap": 9.0, "eps_stability": 0.0,
                       "revenue_growth": 0.0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600*4)
def get_arena_c_factors(tickers: tuple) -> dict:
    """获取 C 组 ScorecardC 所需特殊因子：
    - earnings_growth: Forward EPS 增速
    - rs_120d: 120日中长线相对强度 RS vs SPY
    - rs_250d: 250日年度超额收益 RS vs SPY
    tickers 用 tuple 传入以保证 st.cache_data 可序列化。
    """
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np

    # SPY 基准：120日 + 250日收益
    try:
        spy_hist = yf.Ticker("SPY").history(period="2y")
        spy_prices = spy_hist["Close"].dropna().astype(float) if not spy_hist.empty else pd.Series(dtype=float)
        spy_ret120 = float((spy_prices.iloc[-1] / spy_prices.iloc[-121] - 1) * 100) if len(spy_prices) >= 121 else 0.0
        spy_ret250 = float((spy_prices.iloc[-1] / spy_prices.iloc[-251] - 1) * 100) if len(spy_prices) >= 251 else 0.0
    except Exception:
        spy_ret120 = 0.0
        spy_ret250 = 0.0

    def _fetch_one(t):
        try:
            stock = yf.Ticker(t)
            info = {}
            try:
                info = stock.info or {}
            except Exception:
                pass
            earnings_growth = info.get("earningsGrowth") or info.get("revenueGrowth") or 0.0

            hist = stock.history(period="2y")
            if not hist.empty:
                prices = hist["Close"].dropna().astype(float)
            else:
                prices = pd.Series(dtype=float)

            if len(prices) >= 121:
                ret120 = float((prices.iloc[-1] / prices.iloc[-121] - 1) * 100)
                rs_120d = ret120 - spy_ret120
            else:
                rs_120d = 0.0

            if len(prices) >= 251:
                ret250 = float((prices.iloc[-1] / prices.iloc[-251] - 1) * 100)
                rs_250d = ret250 - spy_ret250
            else:
                rs_250d = 0.0

            return t, {"earnings_growth": float(earnings_growth), "rs_120d": rs_120d, "rs_250d": rs_250d}
        except Exception:
            return t, {"earnings_growth": 0.0, "rs_120d": 0.0, "rs_250d": 0.0}

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


# ==========================================
# 3. 叙事引擎 API 客户端 (Narrative Engine)
# ==========================================

def _narrative_get(path, params=None):
    """GET 叙事引擎端点，失败时返回 {"degraded": True, "error": ...}。"""
    try:
        r = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"degraded": True, "error": str(e)}


def _narrative_post(path, json=None, params=None):
    """POST 叙事引擎端点，失败时返回 {"success": False, "error": ...}。"""
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=json, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def trigger_narrative_pipeline(target_date=None):
    payload = {}
    if target_date:
        payload["target_date"] = str(target_date)
    return _narrative_post("/api/v1/narrative/run_pipeline", json=payload)


def fetch_narrative_status():
    return _narrative_get("/api/v1/narrative/status")


def fetch_crawler_status():
    return _narrative_get("/api/v1/narrative/crawler_status")


def fetch_narrative_inbox():
    return _narrative_get("/api/v1/narrative/inbox")


def fetch_pending_inbox(reason="", status="pending", limit=200):
    params = {"status": status, "limit": limit}
    if reason:
        params["reason"] = reason
    return _narrative_get("/api/v1/narrative/pending_inbox", params=params)


def review_narrative_term(id, action, l2_sector=None):
    payload = {"id": id, "action": action}
    if l2_sector:
        payload["l2_sector"] = l2_sector
    return _narrative_post("/api/v1/narrative/review", json=payload)


def review_narrative_batch(ids, action):
    return _narrative_post("/api/v1/narrative/review_batch", json={"ids": ids, "action": action})


def fetch_match_log(days=7, l2_sector="", source="", search="", page=1, page_size=50):
    params = {"days": days, "page": page, "page_size": page_size}
    if l2_sector:
        params["l2_sector"] = l2_sector
    if source:
        params["source"] = source
    if search:
        params["search"] = search
    return _narrative_get("/api/v1/narrative/match_log", params=params)


def fetch_orphan_stats():
    return _narrative_get("/api/v1/narrative/orphan_stats")


def trigger_orphan_review(force=False):
    return _narrative_post("/api/v1/narrative/orphan_review", params={"force": str(force).lower()})


def fetch_orphan_review_status():
    return _narrative_get("/api/v1/narrative/orphan_review_status")


def fetch_theme_proposals(status="pending"):
    return _narrative_get("/api/v1/narrative/theme_proposals", params={"status": status})


def approve_theme_proposal(proposal_id, l2_override=None):
    payload = {}
    if l2_override:
        payload["l2_override"] = l2_override
    return _narrative_post(f"/api/v1/narrative/theme_proposals/{proposal_id}/approve", json=payload)


def reject_theme_proposal(proposal_id):
    return _narrative_post(f"/api/v1/narrative/theme_proposals/{proposal_id}/reject")


def trigger_generate_seed_proposals():
    return _narrative_post("/api/v1/narrative/generate_seed_proposals")


def fetch_dictionary_stats():
    return _narrative_get("/api/v1/narrative/dictionary_stats")


def fetch_taxonomy():
    return _narrative_get("/api/v1/narrative/taxonomy")


def fetch_taxonomy_full():
    return _narrative_get("/api/v1/narrative/taxonomy/full")


def post_dictionary_add(l2_sector, l3_keyword):
    return _narrative_post("/api/v1/narrative/dictionary/add",
                           json={"l2_sector": l2_sector, "l3_keyword": l3_keyword})


def post_dictionary_remove(l2_sector, l3_keyword):
    return _narrative_post("/api/v1/narrative/dictionary/remove",
                           json={"l2_sector": l2_sector, "l3_keyword": l3_keyword})


def post_dictionary_batch_archive(items):
    """items: list of {"l2_sector": str, "l3_keyword": str}"""
    return _narrative_post("/api/v1/narrative/dictionary/batch_archive", json={"items": items})


def post_dictionary_batch_restore(items):
    """items: list of {"l2_sector": str, "l3_keyword": str}"""
    return _narrative_post("/api/v1/narrative/dictionary/batch_restore", json={"items": items})


def post_dictionary_batch_move(source_l2, target_l2, keywords):
    """keywords: list of str"""
    return _narrative_post("/api/v1/narrative/dictionary/batch_move",
                           json={"source_l2": source_l2, "target_l2": target_l2, "keywords": keywords})


def post_dictionary_batch_delete(items):
    """items: list of {"l2_sector": str, "l3_keyword": str}"""
    return _narrative_post("/api/v1/narrative/dictionary/batch_delete", json={"items": items})


def post_dictionary_batch_mark_noise(items):
    """items: list of {"l2_sector": str, "l3_keyword": str}"""
    return _narrative_post("/api/v1/narrative/dictionary/batch_mark_noise", json={"items": items})


def post_dictionary_rename_l2(old_name, new_name):
    return _narrative_post("/api/v1/narrative/dictionary/rename_l2",
                           json={"old_name": old_name, "new_name": new_name})


def post_dictionary_delete_l2(l2_sector, mode="archive"):
    return _narrative_post("/api/v1/narrative/dictionary/delete_l2",
                           json={"l2_sector": l2_sector, "mode": mode})


def fetch_uncategorized():
    return _narrative_get("/api/v1/narrative/uncategorized")


def migrate_uncategorized(min_confidence=0.4):
    return _narrative_post("/api/v1/narrative/uncategorized/migrate",
                           json={"min_confidence": min_confidence})


def propose_uncategorized():
    return _narrative_post("/api/v1/narrative/uncategorized/propose")


def post_borderline_force_pass(term):
    return _narrative_post("/api/v1/narrative/borderline/force_pass", params={"term": term})


def post_borderline_mark_noise(term, ttl_days=90):
    return _narrative_post("/api/v1/narrative/borderline/mark_noise",
                           params={"term": term, "ttl_days": ttl_days})


def fetch_term_trace(term):
    return _narrative_get("/api/v1/narrative/term_trace", params={"term": term})


def fetch_recently_promoted(days=7):
    return _narrative_get("/api/v1/narrative/recently_promoted", params={"days": days})


def fetch_new_terms(days=1, top_k=50):
    return _narrative_get("/api/v1/narrative/new_terms", params={"days": days, "top_k": top_k})


def fetch_borderline_terms(days=30, min_age_days=0):
    return _narrative_get("/api/v1/narrative/borderline_terms",
                          params={"days": days, "min_age_days": min_age_days})


def fetch_l2_l3_detail(days=7):
    return _narrative_get("/api/v1/narrative/l2_l3_detail", params={"days": days})


def fetch_quadrant_history(days=30):
    return _narrative_get("/api/v1/narrative/quadrant_history", params={"days": days})


@st.cache_data(ttl=60)
def fetch_tfidf_terms(days=7, top_k=50, show_all=False):
    return _narrative_get("/api/v1/narrative/tfidf_terms",
                          params={"days": days, "top_k": top_k, "show_all": show_all})


def fetch_corpus_stats():
    return _narrative_get("/api/v1/narrative/corpus_stats")


def fetch_noise_words():
    return _narrative_get("/api/v1/narrative/noise_words")


def post_noise_word_add(term, ttl_days=90, reason="manual_cio"):
    return _narrative_post("/api/v1/narrative/noise_words/add",
                           params={"term": term, "ttl_days": ttl_days, "reason": reason})


def post_noise_word_remove(term):
    return _narrative_post("/api/v1/narrative/noise_words/remove", params={"term": term})


def fetch_quality_log(days=3, per_day=50):
    return _narrative_get("/api/v1/narrative/quality_log", params={"days": days, "per_day": per_day})


def trigger_slow_clock():
    return _narrative_post("/api/v1/narrative/run_slow_clock")


def fetch_slow_clock_status():
    return _narrative_get("/api/v1/narrative/slow_clock_status")


@st.cache_data(ttl=60)
def fetch_narrative_sector_heat(days=7):
    return _narrative_get("/api/v1/narrative/sector_heat", params={"days": days})


# ==========================================
# 4. CIO 观察池 (Watchlist)
# ==========================================

@st.cache_data(ttl=30)
def fetch_cio_watchlist():
    return _narrative_get("/api/v1/arena/watchlist")


def add_to_cio_watchlist(ticker, notes=""):
    fetch_cio_watchlist.clear()
    return _narrative_post("/api/v1/arena/watchlist/add",
                           json={"ticker": ticker, "notes": notes})


def remove_from_cio_watchlist(ticker):
    fetch_cio_watchlist.clear()
    return _narrative_post("/api/v1/arena/watchlist/remove", json={"ticker": ticker})


def update_cio_watchlist_notes(ticker, notes):
    fetch_cio_watchlist.clear()
    return _narrative_post("/api/v1/arena/watchlist/update_notes",
                           json={"ticker": ticker, "notes": notes})


# ==========================================
# 5. Alpaca 数据增强
# ==========================================

@st.cache_data(ttl=300)
def get_alpaca_ticker_news(ticker, limit=5):
    return _narrative_get("/api/v1/alpaca/ticker_news",
                          params={"ticker": ticker, "limit": limit})


@st.cache_data(ttl=60)
def get_ticker_cooccurrence(ticker, days=7):
    return _narrative_get("/api/v1/narrative/ticker_cooccurrence",
                          params={"ticker": ticker, "days": days})


@st.cache_data(ttl=60)
def get_alpaca_snapshots(tickers_tuple):
    """tickers_tuple: tuple of ticker strings (hashable for cache)。"""
    symbols = ",".join(tickers_tuple)
    return _narrative_get("/api/v1/alpaca/snapshots", params={"symbols": symbols})


# ==========================================
# 6. ETF 相对强度 (前端 yfinance 计算)
# ==========================================

@st.cache_data(ttl=3600)
def get_etf_rs20d(tickers: tuple) -> dict:
    """计算各 ETF 近 20 日相对 SPY 超额收益，用于 L2 板块偏离检测。"""
    import numpy as np
    try:
        spy_hist = yf.Ticker("SPY").history(period="30d")
        spy_prices = spy_hist["Close"].dropna().astype(float) if not spy_hist.empty else pd.Series(dtype=float)
        spy_ret20 = float((spy_prices.iloc[-1] / spy_prices.iloc[-21] - 1) * 100) if len(spy_prices) >= 21 else 0.0
    except Exception:
        spy_ret20 = 0.0

    result = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="30d")
            if hist.empty or len(hist) < 5:
                result[t] = 0.0
                continue
            prices = hist["Close"].dropna().astype(float)
            if len(prices) >= 21:
                ret20 = float((prices.iloc[-1] / prices.iloc[-21] - 1) * 100)
                rs = ret20 - spy_ret20
            else:
                rs = 0.0
            result[t] = round(rs, 2) if not (np.isnan(rs) or np.isinf(rs)) else 0.0
        except Exception:
            result[t] = 0.0
    return result