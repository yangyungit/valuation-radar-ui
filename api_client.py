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

# URL 优先级：环境变量 RADAR_API_URL > USE_LOCAL_API 强制本地 > 默认生产地址
# 本地调试时，请设置 USE_LOCAL_API=true 或 RADAR_API_URL=http://localhost:8000
_env_url = os.environ.get("RADAR_API_URL", "").strip()
if _env_url:
    API_BASE_URL = _env_url
elif os.environ.get("USE_LOCAL_API") == "true":
    API_BASE_URL = "http://localhost:8000"
else:
    API_BASE_URL = "https://valuation-radar-server.onrender.com"

# True 当且仅当通过 RADAR_API_URL 显式指向远程生产环境（非 localhost）
# 用于在前端层面阻断对生产数据库的危险写操作
IS_PROD_REMOTE = bool(_env_url) and "localhost" not in _env_url

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

def _calc_ttm_div_yield(ticker_obj, price: float) -> float:
    """计算 TTM（过去12个月）真实股息率，适配月度/季度/年度等任意付息频率。"""
    try:
        if price <= 0:
            return 0.0
        divs = ticker_obj.dividends
        if divs is None or divs.empty:
            return 0.0
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=400)
        recent = divs[divs.index >= cutoff]
        if recent.empty:
            return 0.0
        ttm_div = float(recent.sum())
        return round(ttm_div / price * 100, 2)
    except Exception:
        return 0.0


@st.cache_data(ttl=3600*24)
def get_stock_metadata(tickers):
    """获取市值和 TTM 真实股息率等公开元数据 (10线程并发版)

    div_yield 使用过去12个月真实分红历史计算 TTM 年化股息率，
    正确处理月度/季度/年度等任意付息频率（JEPI/O/STAG 等月度付息资产不再被低估）。
    """
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_one(t):
        try:
            stock = yf.Ticker(t)
            fi = stock.fast_info
            mcap = fi.get('marketCap', 0) or 0
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = _calc_ttm_div_yield(stock, price)
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
    """获取 A 组 ScorecardA 所需避风港因子 (252 日回溯)：
    - fcf_yield:  自由现金流收益率 FCF/MCap (%)，ETF 无 FCF 时回退到股息率
    - div_yield:  TTM 股息率 (%)，供 Z 组复用
    - max_dd_252: 近252日最大回撤 (负数)
    - spy_corr:   与 SPY 日收益率的皮尔逊相关系数
    - ann_vol:    252日年化波动率，供 Z 组复用
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
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = _calc_ttm_div_yield(stock, price)

            # FCF yield: freeCashflow / marketCap as %; fallback to div_yield for ETFs
            fcf_yield = div_yield
            try:
                info = stock.info or {}
                fcf = info.get('freeCashflow')
                mcap_val = info.get('marketCap') or mcap
                if fcf is not None and mcap_val and float(mcap_val) > 0:
                    fcf_yield = max(0.0, float(fcf) / float(mcap_val) * 100.0)
            except Exception:
                pass

            # 2y period to ensure ma60 series has 180+ valid values for ribbon computation
            hist = stock.history(period="2y")
            if hist.empty or len(hist) < 60:
                return t, {"fcf_yield": fcf_yield, "div_yield": div_yield,
                           "max_dd_252": 0.0, "spy_corr": 0.5, "ann_vol": 0.30,
                           "ribbon_score": 0.0}

            prices = hist["Close"].dropna().astype(float)

            # Use last 252 days for core metrics to preserve backward compatibility
            prices_1y = prices.iloc[-252:] if len(prices) >= 252 else prices
            daily_ret = prices_1y.pct_change().dropna()

            roll_max = prices_1y.cummax()
            max_dd = float((prices_1y / roll_max - 1.0).min())

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

            # ── Ribbon Quality Score (0~1) ──────────────────────────────
            ribbon_score = 0.0
            try:
                ma20_series = prices.rolling(20).mean().dropna()
                ma60_series = prices.rolling(60).mean().dropna()
                min_len = min(len(ma20_series), len(ma60_series))
                if min_len >= 80:
                    ma20_s = ma20_series.iloc[-min_len:]
                    ma60_s = ma60_series.iloc[-min_len:]

                    # S1: MA spread stability (30%) — parallel railroad tracks
                    spread = (ma20_s - ma60_s) / ma60_s.replace(0, np.nan)
                    spread_120 = spread.dropna().iloc[-120:]
                    if len(spread_120) >= 30:
                        spread_std = float(spread_120.std())
                        s1 = float(np.clip(1.0 - spread_std / 0.05, 0.0, 1.0))
                    else:
                        s1 = 0.0

                    # S2: Consecutive trend days ma20 > ma60 (35%)
                    cross = (ma20_s > ma60_s).values[::-1]
                    streak = int(np.argmin(cross)) if not np.all(cross) else len(cross)
                    s2 = float(np.clip(streak / 252.0, 0.0, 1.0))

                    # S3: Slope stability of ma60 (25%) — constant-velocity ribbon
                    ma60_tail = ma60_s.iloc[-61:] if len(ma60_s) >= 61 else ma60_s
                    pct_changes = (ma60_tail.diff() / ma60_tail.shift(1)).dropna()
                    if len(pct_changes) >= 20:
                        mean_ch = float(pct_changes.abs().mean())
                        std_ch  = float(pct_changes.std())
                        cv = std_ch / mean_ch if mean_ch > 1e-9 else 10.0
                        s3 = float(np.clip(1.0 / (1.0 + cv), 0.0, 1.0))
                    else:
                        s3 = 0.0

                    # S4: Price adhesion to ma20 (10%) — price hugs the moving average
                    prices_tail = prices.iloc[-60:] if len(prices) >= 60 else prices
                    ma20_tail   = prices_tail.rolling(20).mean().dropna()
                    aligned_p   = prices_tail.iloc[-len(ma20_tail):]
                    dev = ((aligned_p.values - ma20_tail.values) /
                           ma20_tail.replace(0, np.nan).values)
                    dev_std = float(np.nanstd(dev)) if len(dev) > 5 else 0.05
                    s4 = float(np.clip(1.0 - dev_std / 0.05, 0.0, 1.0))

                    ribbon_score = float(np.clip(
                        0.30 * s1 + 0.35 * s2 + 0.25 * s3 + 0.10 * s4, 0.0, 1.0))
            except Exception:
                ribbon_score = 0.0
            # ───────────────────────────────────────────────────────────

            return t, {
                "fcf_yield": fcf_yield,
                "div_yield": div_yield,
                "max_dd_252": max_dd,
                "spy_corr": spy_corr,
                "ann_vol": ann_vol,
                "ribbon_score": ribbon_score,
            }
        except Exception:
            return t, {"fcf_yield": 0.0, "div_yield": 0.0, "max_dd_252": 0.0,
                       "spy_corr": 0.5, "ann_vol": 0.30, "ribbon_score": 0.0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t, data in executor.map(_fetch_one, tickers):
            result[t] = data
    return result


@st.cache_data(ttl=3600*4)
def get_arena_b_factors(tickers: tuple) -> dict:
    """获取 B/Z 组所需慢变量因子：
    - div_yield:          年化股息率 (%)
    - max_dd_252:         近252日最大回撤 (负数)
    - sharpe_252:         近252日年化夏普比率
    - rs_120d:            120日相对 SPY 超额收益 (%)
    - log_mcap:           log10(市值)
    - eps_stability:      EPS稳定性代理 (年化波动率倒数)
    - revenue_growth:     Revenue 增速 (%)
    - price_return_252:   近252日纯价格回报（不含股息，用于 Z 组净值趋势因子）
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
            price = fi.get('regularMarketPrice', 0) or fi.get('previousClose', 1) or 1
            div_yield = _calc_ttm_div_yield(stock, price)

            hist = stock.history(period="1y")
            if hist.empty or len(hist) < 60:
                return t, {"div_yield": div_yield, "max_dd_252": 0.0, "sharpe_252": 0.0,
                           "rs_120d": 0.0, "log_mcap": float(np.log10(max(mcap, 1e6))),
                           "eps_stability": 0.0, "revenue_growth": 0.0, "price_return_252": 0.0}

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

            price_ret_252 = float(prices.iloc[-1] / prices.iloc[0] - 1) if len(prices) >= 2 else 0.0
            if np.isnan(price_ret_252) or np.isinf(price_ret_252):
                price_ret_252 = 0.0

            return t, {
                "div_yield": div_yield,
                "max_dd_252": max_dd,
                "sharpe_252": sharpe,
                "rs_120d": rs_120d,
                "log_mcap": float(np.log10(max(mcap, 1e6))),
                "eps_stability": eps_stab,
                "revenue_growth": rev_growth,
                "price_return_252": price_ret_252,
            }
        except Exception:
            return t, {"div_yield": 0.0, "max_dd_252": 0.0, "sharpe_252": 0.0,
                       "rs_120d": 0.0, "log_mcap": 9.0, "eps_stability": 0.0,
                       "revenue_growth": 0.0, "price_return_252": 0.0}

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
def fetch_funnel_v2_scores(df, tickers, meta_data, theme_heat_dict, macro_scores=None):
    """v2 跨组竞争漏斗：同一 ticker 可进入多个 Scorecard，返回额外的 cross_group_map。
    
    Returns
    -------
    (metrics_df, spy_mom20, cross_group_map)
    cross_group_map: {ticker: [grade1, grade2, ...]}（仅包含出现在 2+ 个组的 ticker）
    """
    try:
        payload = {
            "df_json": df.to_json(orient="split"),
            "tickers": tickers,
            "meta_data": meta_data,
            "theme_heat_dict": theme_heat_dict,
        }
        if macro_scores is not None:
            payload["macro_scores"] = macro_scores
        response = requests.post(f"{API_BASE_URL}/api/v1/calculate_funnel_v2", json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        metrics_df = pd.read_json(io.StringIO(data["metrics_json"]), orient="split")
        return metrics_df, data.get("spy_mom20", 0.0), data.get("cross_group_map", {})
    except Exception as e:
        st.error(f"🚨 云端漏斗 v2 引擎连接失败: {e}")
        return pd.DataFrame(), 0.0, {}


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
# 3. 信念状态 API 客户端 (Conviction State)
# ==========================================

def fetch_conviction_state(cls: str) -> tuple[dict, list]:
    """从后端 universe.db 读取信念状态。失败时返回 ({}, [])。"""
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/conviction_state/{cls}", timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("state", {}), data.get("holders", [])
    except Exception:
        return {}, []


def push_conviction_state(cls: str, state: dict, holders: list) -> bool:
    """将信念状态推送到后端 universe.db 持久化。返回是否成功。"""
    if IS_PROD_REMOTE:
        return False
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/conviction_state/{cls}",
            json={"state": state, "holders": holders},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("success", False)
    except Exception:
        return False


# ==========================================
# 3c. Arena 月度档案 API 客户端
# ==========================================

def fetch_arena_history() -> dict:
    """从后端读取全量 arena 月度档案。失败时返回 {}。"""
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/arena/history", timeout=15)
        r.raise_for_status()
        return r.json().get("history", {})
    except Exception:
        return {}


def push_arena_history_batch(history: dict) -> bool:
    """批量 upsert arena 月度档案到后端。返回是否成功。"""
    if IS_PROD_REMOTE:
        return False
    if not history:
        return True
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/arena/history/batch",
            json={"history": history},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("success", False)
    except Exception:
        return False


def clear_arena_history_backend() -> bool:
    """清空后端全部 arena 月度档案。返回是否成功。"""
    if IS_PROD_REMOTE:
        return False
    try:
        r = requests.delete(f"{API_BASE_URL}/api/v1/arena/history", timeout=10)
        r.raise_for_status()
        return r.json().get("success", False)
    except Exception:
        return False


# ==========================================
# 3b. 宏观 Regime 缓存 API 客户端
# ==========================================

@st.cache_data(ttl=3600 * 4)
def compute_macro_regime_api(z_window: int = 750) -> dict:
    """调用后端 POST /api/v1/macro/compute，后端自拉 yfinance + FRED，返回完整 regime 数据包。
    响应格式：{
        "success": True,
        "data": { regime_dict },
        "horsemen_monthly_table": [ records ],
        "horsemen_daily_verdict": { date_str: verdict_cn }
    }
    失败时返回 {}。
    """
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/macro/compute",
            json={"z_window": z_window},
            timeout=300,
        )
        r.raise_for_status()
        resp = r.json()
        if resp.get("success"):
            fetch_current_regime.clear()
        return resp
    except Exception as e:
        st.warning(f"⚠️ 后端 regime 计算失败，将回退本地计算: {e}")
        return {}


@st.cache_data(ttl=3600 * 4)
def fetch_macro_radar() -> dict:
    """从后端获取宏观雷达指标（Z-Score/RS/趋势结构）。
    后端自行下载 yfinance 数据并计算，前端零感知。
    返回 {"success": True, "metrics": [...], "spy_mom20": float, "insights": {...}}。
    """
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/macro/radar", timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"success": False, "metrics": [], "spy_mom20": 0.0, "insights": {}}

@st.cache_data(ttl=300)
def fetch_current_regime() -> dict:
    """从后端 universe.db 读取最新 macro regime 数据包。失败时返回 {}。
    TTL=300s（5 分钟），Page 1 写入后可主动调 fetch_current_regime.clear() 使缓存失效。
    """
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/macro/current-regime", timeout=10)
        r.raise_for_status()
        return r.json().get("data", {})
    except Exception:
        return {}


def push_macro_regime(payload: dict) -> bool:
    """将 Page 1 计算出的 regime 数据包推送到后端持久化。返回是否成功。"""
    if IS_PROD_REMOTE:
        return False
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/macro/regime",
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        fetch_current_regime.clear()
        return r.json().get("success", False)
    except Exception:
        return False


# ==========================================
# 3c. ABCD 筛选结果缓存 API 客户端
# ==========================================

@st.cache_data(ttl=300)
def fetch_screen_results() -> dict:
    """从后端 universe.db 读取最新 ABCD 分类 + Arena 竞选结果。失败时返回 {}。"""
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/screen/results", timeout=10)
        r.raise_for_status()
        return r.json().get("data", {})
    except Exception:
        return {}


def push_screen_results(payload: dict) -> bool:
    """将 Page 3 的 ABCD 分类 + Arena 竞选结果推送到后端持久化。返回是否成功。"""
    if IS_PROD_REMOTE:
        return False
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/screen/results",
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        fetch_screen_results.clear()
        return r.json().get("success", False)
    except Exception:
        return False


def run_classification_api(
    screen_tickers: list,
    meta_data: dict,
    prev_grades_map: dict = None,
    z_seed_tickers: list = None,
    thresholds: dict = None,
    conv_state_a: dict = None,
    conv_holders_a: list = None,
    conv_state_b: dict = None,
    conv_holders_b: list = None,
    conv_config_a: dict = None,
    conv_config_b: dict = None,
    price_df=None,
) -> dict:
    """调用后端 /api/v1/screen/run-classification。
    price_df=None 时后端自拉 yfinance（推荐）；传入 price_df 时仍走旧序列化路径（向后兼容）。
    返回 {"success": True, "abcd_classified_assets": ..., "selected_a": ..., "selected_b": ...}。
    失败时返回 {"success": False, "error": ...}。
    """
    try:
        if price_df is not None:
            price_records = price_df.to_dict(orient="index")
            price_records = {str(k): v for k, v in price_records.items()}
        else:
            price_records = {}
        payload = {
            "price_records":   price_records,
            "screen_tickers":  screen_tickers,
            "meta_data":       meta_data or {},
            "prev_grades_map": prev_grades_map or {},
            "z_seed_tickers":  list(z_seed_tickers or []),
            "thresholds":      thresholds or {},
            "conv_state_a":    conv_state_a or {},
            "conv_holders_a":  conv_holders_a or [],
            "conv_state_b":    conv_state_b or {},
            "conv_holders_b":  conv_holders_b or [],
            "conv_config_a":   conv_config_a or {},
            "conv_config_b":   conv_config_b or {},
        }
        r = requests.post(
            f"{API_BASE_URL}/api/v1/screen/run-classification",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ==========================================
# 4. 叙事引擎 API 客户端 (Narrative Engine)
# ==========================================

def _narrative_get(path, params=None):
    """GET 叙事引擎端点，失败时返回 {"degraded": True, "error": ...}。"""
    try:
        r = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=45)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"degraded": True, "error": str(e)}


def _narrative_post(path, json=None, params=None, timeout=60):
    """POST 叙事引擎端点，失败时返回 {"success": False, "error": ...}。"""
    if IS_PROD_REMOTE and not st.session_state.get("prod_write_confirmed", False):
        return {"success": False, "blocked": True, "error": "⚠️ 直连生产环境写保护：请在页面顶部勾选确认后再操作"}
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=json, params=params, timeout=timeout)
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


def trigger_batch_backfill(days: int = 180, start_date: str = None, end_date: str = None, force_missing: bool = False):
    """触发 Render 服务端批量历史回填（非阻塞，服务端自主循环跑完所有日期）。"""
    payload = {"days": days, "force_missing": force_missing}
    if start_date:
        payload["start_date"] = start_date
    if end_date:
        payload["end_date"] = end_date
    return _narrative_post("/api/v1/narrative/batch_backfill", json=payload)


def fetch_batch_backfill_status():
    """轮询 Render 服务端批量回填进度。"""
    return _narrative_get("/api/v1/narrative/batch_backfill_status")


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


def purge_junk_orphans():
    """Archive existing orphan terms that contain non-finance/entertainment trigger words."""
    return _narrative_post("/api/v1/narrative/orphan_purge_junk")


def fetch_theme_proposals(status="pending"):
    return _narrative_get("/api/v1/narrative/theme_proposals", params={"status": status})


def approve_theme_proposal(proposal_id, l2_override=None, zh_override=None):
    payload = {}
    if l2_override:
        payload["l2_override"] = l2_override
    if zh_override:
        payload["zh_override"] = zh_override
    return _narrative_post(f"/api/v1/narrative/theme_proposals/{proposal_id}/approve", json=payload)


def reject_theme_proposal(proposal_id):
    return _narrative_post(f"/api/v1/narrative/theme_proposals/{proposal_id}/reject")


def backfill_proposals_terms_zh():
    # 每个提案调用 Gemini/Google Translate，重试等待上限 10+20s；20 个提案最长约 7 分钟
    return _narrative_post("/api/v1/narrative/theme_proposals/backfill_terms_zh", timeout=420)


def trigger_generate_seed_proposals():
    return _narrative_post("/api/v1/narrative/generate_seed_proposals")


def trigger_retroactive_screen():
    return _narrative_post("/api/v1/narrative/retroactive_screen", timeout=180)


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


def get_batch_ticker_cooccurrence(tickers: list, days: int = 7) -> dict:
    """Batch wrapper: {ticker: cooccurrence_resp} for resonance matching."""
    result = {}
    for t in tickers:
        try:
            result[t] = get_ticker_cooccurrence(t, days=days)
        except Exception:
            result[t] = {"data": []}
    return result


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