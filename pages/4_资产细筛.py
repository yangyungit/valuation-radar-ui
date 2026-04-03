import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import os
import calendar
import yfinance as yf
from datetime import datetime, timedelta
from api_client import (fetch_core_data, get_stock_metadata,
                        get_arena_a_factors, get_arena_b_factors,
                        get_arena_c_factors, get_arena_d_factors,
                        clear_api_caches)

_core_data = fetch_core_data()
_MACRO_TAGS_MAP     = _core_data.get("MACRO_TAGS_MAP", {})
_NARRATIVE_HEAT_MAP = _core_data.get("NARRATIVE_THEMES_HEAT", {})
_STOCK_NARRATIVE    = _core_data.get("STOCK_NARRATIVE_MAP", {})

st.set_page_config(page_title="同类资产竞技场", layout="wide", page_icon="🏆")

# ─────────────────────────────────────────────────────────────────
#  全局样式
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .podium-gold   { background: linear-gradient(135deg,#3d2f00,#1a1200);
                     border: 2px solid #FFD700; border-radius:12px; padding:20px;
                     text-align:center; position:relative; }
    .podium-silver { background: linear-gradient(135deg,#2a2a2a,#111);
                     border: 2px solid #C0C0C0; border-radius:12px; padding:20px;
                     text-align:center; }
    .podium-bronze { background: linear-gradient(135deg,#2d1a0a,#111);
                     border: 2px solid #CD7F32; border-radius:12px; padding:20px;
                     text-align:center; }
    .arena-header  { border-radius:10px; padding:16px 20px; margin-bottom:16px; }
    .factor-pill   { display:inline-block; border-radius:20px; padding:3px 10px;
                     font-size:11px; margin:2px; }
    .score-bar-bg  { background:#1e1e1e; border-radius:4px; height:8px; width:100%; }
    .score-bar-fg  { border-radius:4px; height:8px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  ABCD 宏观剧本元信息（与 Page 2 / Page 3 保持一致）
# ─────────────────────────────────────────────────────────────────
CLASS_META: dict = {
    "A": {
        "label": "A级：压舱石",
        "icon": "⚓",
        "color": "#2ECC71",
        "bg": "#0d2b1a",
    },
    "B": {
        "label": "B级：大猩猩",
        "icon": "🦍",
        "color": "#F39C12",
        "bg": "#2b1e09",
    },
    "C": {
        "label": "C级：时代之王",
        "icon": "👑",
        "color": "#E74C3C",
        "bg": "#2b0d0d",
    },
    "D": {
        "label": "D级：预备队",
        "icon": "🚀",
        "color": "#9B59B6",
        "bg": "#1a0d2b",
    },
}

# ─────────────────────────────────────────────────────────────────
#  各赛道评分配置（Relative Scoring Config）
#  每个赛道有独立的权重体系和竞技逻辑
# ─────────────────────────────────────────────────────────────────
ARENA_CONFIG: dict = {
    "A": {
        "score_name": "避风港防御指数",
        "weights": {"max_dd_inv": 0.35, "div_yield": 0.25, "spy_corr_inv": 0.20, "vol_inv": 0.20},
        "invert_z": False,
        "factor_labels": {
            "max_dd_inv":   "极限抗跌 (最大回撤倒数)",
            "div_yield":    "现金奶牛 (股息率)",
            "spy_corr_inv": "宏观对冲 (SPY相关性倒数)",
            "vol_inv":      "绝对低波 (年化波动率倒数)",
        },
        "logic": (
            "压舱石的竞技逻辑：彻底摒弃动量与均线，专抓极低波动与大盘对冲属性。<br>"
            "① 极限抗跌（真实252日最大回撤取倒数，回撤越小得分越高，权重 35%）<br>"
            "② 现金奶牛（真实股息率，现金流回报越高越好，权重 25%）<br>"
            "③ 宏观对冲（与SPY日收益率皮尔逊相关系数取倒数，低/负相关得高分，权重 20%）<br>"
            "④ 绝对低波（252日年化波动率取倒数，波动越低得分越高，权重 20%）<br>"
            "四维纯统计指标同时达标方为真正避风港，拒绝一切短期动量噪音。"
        ),
    },
    "B": {
        "score_name": "核心底仓质量指数",
        "weights": {"real_quality": 0.40, "resilience": 0.30, "sharpe_1y": 0.20, "mcap_premium": 0.10},
        "invert_z": False,
        "factor_labels": {
            "real_quality":  "真·护城河质量 (股息率+盈利稳定性)",
            "resilience":    "抗跌韧性 (近1年最大回撤倒数)",
            "sharpe_1y":     "长效性价比 (近1年夏普比率)",
            "mcap_premium":  "绝对体量 (log10市值壁垒)",
        },
        "logic": (
            "核心底仓质量指数：彻底剔除短期动量，追求极低换手率与极强抗跌性。<br>"
            "① 真·护城河质量（股息率 + 盈利稳定性双因子代理 FCF/ROIC，权重 40%）<br>"
            "② 抗跌韧性（近 1 年最大回撤越小得分越高，权重 30%）<br>"
            "③ 长效性价比（近 1 年夏普比率，长期风险调整收益，权重 20%）<br>"
            "④ 绝对体量（log10 市值壁垒，大象起舞加分，权重 10%）<br>"
            "高分者将形成稳固的长期护城河。"
        ),
    },
    "C": {
        "score_name": "慢变量霸权指数",
        "weights": {},
        "invert_z": False,
        "factor_labels": {
            "eps_growth":      "Forward EPS Z-Score (基本面核动力)",
            "log_mcap":        "log₁₀(市值) (流动性保障)",
            "rs_120d":         "RS₁₂₀ 中长线相对强度 (半年超额收益)",
            "macro_alignment": "宏观剧本顺风匹配 (Macro Fit)",
        },
        "logic": (
            "时代之王 ScorecardC — 慢变量霸权测试（满分 100 分）<br>"
            "① Forward EPS 增速（华尔街一致预期 12 个月 EPS 增速截面 Z-Score，权重 50%）— 盈利是王道。<br>"
            "② log₁₀(市值)（市值越大流动性越好，机构可大仓位介入，权重 15%）<br>"
            "③ RS₁₂₀ 中长线相对强度（过去 120 日相对 SPY 超额收益率，看它是否在半年维度持续跑赢大盘，权重 15%）<br>"
            "④ 宏观顺风（标的宏观标签与当前胜率最高剧本完全匹配得满分，错配得 0，权重 20%）<br>"
            "所有因子均经 Min-Max 归一化至 [0, 100] 后加权求和。时代之王的评分只问长期基本面与宏大叙事稳健资金沉淀，拒绝短期噪音（5日量能、叙事热度已迁入 D 组）。"
        ),
    },
    "D": {
        "score_name": "爆点扫描指数",
        "weights": {"vol_z": 0.45, "rs_20d": 0.35, "ma60_breakout": 0.20},
        "factor_labels": {
            "vol_z":        "量价共振烈度 Vol-Price Ignition (机构巨量抢筹)",
            "rs_20d":       "相对强度 Alpha RS₂₀ (超越大盘超额收益)",
            "ma60_breakout": "均线起飞姿态 Base Breakout (季线突破健康度)",
        },
        "logic": (
            "🚀 D 组「爆点扫描仪」使命：全市场无差别扫描，只抓【底部放巨量突破】且【走势远强于大盘】的早期异动股。<br>"
            "① 量价共振烈度（5日均量 Z-Score 相对 60日基准，机构入场信号，权重 45%）<br>"
            "② 相对强度 Alpha（近 20 日超越 SPY 超额收益率，时代之王预备特征，权重 35%）<br>"
            "③ 均线起飞姿态（价格与季线 MA60 位置关系，最佳为刚突破 0-20%，乖离过大扣分，权重 20%）<br>"
            "D 组不区分行业，只看爆发质量：高分即送入 C 组候选，低分说明是骗炮。"
        ),
    },
}

# ─────────────────────────────────────────────────────────────────
#  演示模式 Mock 数据（当上游 Page 2 尚未运行时使用）
# ─────────────────────────────────────────────────────────────────
_MOCK_ASSETS: dict = {
    # A级：压舱石（高股息/低回撤/抗跌）
    "JNJ":   {"cls": "A", "cn_name": "强生",         "z_score":  0.4, "mom20":  2.1, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "KO":    {"cls": "A", "cn_name": "可口可乐",     "z_score":  0.6, "mom20":  1.8, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "PG":    {"cls": "A", "cn_name": "宝洁",         "z_score":  0.8, "mom20":  3.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "VZ":    {"cls": "A", "cn_name": "威瑞森",       "z_score": -0.3, "mom20":  0.9, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "XLU":   {"cls": "A", "cn_name": "公用事业 ETF", "z_score":  0.2, "mom20":  1.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # B级：大猩猩（宽护城河/高FCF/ROIC优秀）
    "AAPL":  {"cls": "B", "cn_name": "苹果",   "z_score":  1.2, "mom20":  8.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "MSFT":  {"cls": "B", "cn_name": "微软",   "z_score":  1.8, "mom20":  6.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "GOOGL": {"cls": "B", "cn_name": "谷歌",   "z_score":  0.9, "mom20":  4.8, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "META":  {"cls": "B", "cn_name": "Meta",   "z_score":  1.5, "mom20": 11.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "V":     {"cls": "B", "cn_name": "Visa",   "z_score":  1.1, "mom20":  5.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # C级：时代之王（高动量/宏观剧本契合/主升浪）
    "NVDA":  {"cls": "C", "cn_name": "英伟达",   "z_score":  2.4, "mom20": 18.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "AMZN":  {"cls": "C", "cn_name": "亚马逊",   "z_score":  0.7, "mom20": 12.1, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "GLD":   {"cls": "C", "cn_name": "黄金 ETF", "z_score":  0.3, "mom20":  9.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "XLE":   {"cls": "C", "cn_name": "能源 ETF", "z_score":  0.4, "mom20":  7.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # D级：预备队（催化剂清晰/右侧放量突破/严格止损）
    "FCX":   {"cls": "D", "cn_name": "自由港",   "z_score": -0.2, "mom20": 22.4, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "URA":   {"cls": "D", "cn_name": "铀矿 ETF", "z_score": -1.2, "mom20": 15.5, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "SLV":   {"cls": "D", "cn_name": "白银 ETF", "z_score": -0.5, "mom20": 18.8, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "CVX":   {"cls": "D", "cn_name": "雪佛龙",   "z_score":  0.2, "mom20": 12.4, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
}

# ─────────────────────────────────────────────────────────────────
#  宏观剧本派生（Macro Regime Derivation）
# ─────────────────────────────────────────────────────────────────
def _derive_monthly_regimes(probs: dict) -> tuple:
    """从月度四大剧本概率派生 B/C 和 D 组使用的宏观剧本。
    B/C: 概率最高剧本；D: 第二高剧本若 >60% 则用之，否则同 B/C。
    probs 格式: {"Soft": float, "Hot": float, "Stag": float, "Rec": float}
    """
    if not probs:
        return "Soft", "Soft"
    sorted_r = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    bc = sorted_r[0][0]
    d  = sorted_r[1][0] if (len(sorted_r) >= 2 and sorted_r[1][1] > 0.60) else bc
    return bc, d


# ─────────────────────────────────────────────────────────────────
#  历史榜单持久化（History Persistence）
# ─────────────────────────────────────────────────────────────────
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")


def _load_arena_history() -> dict:
    """从 JSON 文件加载历史月度 Top 3 记录。"""
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _record_arena_history(cls: str, top3_records: list, month_key: str = None,
                          bc_regime: str = None, d_regime: str = None) -> None:
    """将某月某赛道的 Top 3 写入历史文件（自动覆盖同月同赛道旧数据）。
    month_key 为 None 时默认使用当前月份（YYYY-MM）。
    bc_regime / d_regime 有值时写入 _meta，供历史榜单展示宏观背景。
    """
    if month_key is None:
        month_key = datetime.now().strftime("%Y-%m")
    history = _load_arena_history()
    if month_key not in history:
        history[month_key] = {}
    history[month_key][cls] = [
        {"ticker": r["ticker"], "name": r["name"], "score": r["score"]}
        for r in top3_records
    ]
    if bc_regime is not None or d_regime is not None:
        meta = history[month_key].get("_meta", {})
        if bc_regime is not None:
            meta["bc_regime"] = bc_regime
        if d_regime is not None:
            meta["d_regime"] = d_regime
        history[month_key]["_meta"] = meta
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _fetch_backfill_prices(tickers: tuple) -> tuple:
    """批量下载约 6 年历史收盘价 + 成交量（含 SPY 基准），供回填使用。"""
    all_dl = list(tickers) + ["SPY"]
    end   = datetime.now()
    start = end - timedelta(days=365 * 6)
    try:
        raw      = yf.download(all_dl, start=start, end=end, progress=False)
        price_df = raw["Close"].ffill().dropna(how="all")
        vol_df   = raw["Volume"].ffill().fillna(0)
        return price_df, vol_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def _backfill_arena_history(all_assets: dict, months_back: int = 24,
                            monthly_probs: dict = None) -> tuple:
    """
    用历史价格数据回填过去 N 个月各赛道的 Top 3。
    使用当前 ABCD 分类；Z-Score 用价格滚动 Z 代理；C 组 EPS 用动量代理；
    D 组三因子（Vol_Z / RS₂₀ / MA60偏离）全量计算。
    monthly_probs: {"YYYY-MM": {"Soft": f, "Hot": f, "Stag": f, "Rec": f}}
                   从 Page 1 的 horsemen_monthly_probs 传入，用于逐月派生宏观剧本。
    返回 (saved_month_count, error_msg)
    """
    cls_tickers: dict = {"A": [], "B": [], "C": [], "D": []}
    ticker_names: dict = {}
    for ticker, info in all_assets.items():
        cls = info.get("cls", "?")
        if cls not in cls_tickers or not info.get("has_data", True):
            continue
        cls_tickers[cls].append(ticker)
        ticker_names[ticker] = info.get("cn_name", ticker)

    all_tickers = tuple(t for ts in cls_tickers.values() for t in ts)
    if not all_tickers:
        return 0, "无有效标的"

    price_df, vol_df = _fetch_backfill_prices(all_tickers)
    if price_df.empty:
        return 0, "历史价格数据下载失败，请检查网络或稍后重试。"

    # 构建月末日期列表（从上个月起，向前推 months_back 个月）
    today = datetime.now()
    y, m  = today.year, today.month
    m -= 1
    if m == 0:
        m, y = 12, y - 1

    month_ends: list = []
    for _ in range(months_back):
        last_day = calendar.monthrange(y, m)[1]
        target   = pd.Timestamp(y, m, last_day)
        avail    = price_df.index[price_df.index <= target]
        if len(avail) > 0:
            month_ends.append((f"{y:04d}-{m:02d}", avail[-1]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1

    spy_col = "SPY" if "SPY" in price_df.columns else None
    saved   = 0

    for month_key, me_date in month_ends:
        loc = price_df.index.get_loc(me_date)
        if loc < 120:
            continue

        # 派生该月 B/C 和 D 组宏观剧本
        _m_probs = (monthly_probs or {}).get(month_key, {})
        bc_regime, d_regime = _derive_monthly_regimes(_m_probs)

        p_slice   = price_df.iloc[: loc + 1]
        v_slice   = vol_df.iloc[: loc + 1] if not vol_df.empty else pd.DataFrame()
        spy_slice = p_slice[spy_col].dropna().astype(float) if spy_col else pd.Series(dtype=float)

        for cls, tickers in cls_tickers.items():
            if not tickers:
                continue
            rows: list = []
            for t in tickers:
                if t not in p_slice.columns:
                    continue
                p = p_slice[t].dropna().astype(float)
                if len(p) < 60:
                    continue

                mom20      = float((p.iloc[-1] / p.iloc[-21] - 1) * 100) if len(p) >= 21 else 0.0
                ma20       = float(p.tail(20).mean())
                ma60       = float(p.tail(60).mean())
                is_bullish = bool(ma20 > ma60)
                window     = min(252, len(p))
                mu, sigma  = p.tail(window).mean(), p.tail(window).std()
                z_score    = float((p.iloc[-1] - mu) / sigma) if sigma > 0 else 0.0

                row: dict = {
                    "Ticker": t, "名称": ticker_names.get(t, t),
                    "Z-Score": z_score, "20日动量": mom20,
                    "趋势健康": is_bullish, "股息率": 0.0,
                }

                if cls == "A":
                    p_1yr_a = p.tail(min(252, len(p)))
                    daily_ret_a = p_1yr_a.pct_change().dropna()
                    roll_max_a = p_1yr_a.cummax()
                    max_dd_a = float((p_1yr_a / roll_max_a - 1.0).min()) if not p_1yr_a.empty else 0.0
                    vol_a = float(daily_ret_a.std()) if len(daily_ret_a) > 10 else 0.30
                    ann_vol_a = vol_a * np.sqrt(252) if vol_a > 1e-9 else 0.30
                    spy_corr_a = 0.5
                    if len(spy_slice) >= 60:
                        spy_ret_a = spy_slice.pct_change().dropna()
                        spy_ret_a = spy_ret_a.iloc[-min(252, len(spy_ret_a)):]
                        aligned_a = pd.concat([daily_ret_a, spy_ret_a], axis=1).dropna()
                        if len(aligned_a) > 30:
                            _c = float(aligned_a.iloc[:, 0].corr(aligned_a.iloc[:, 1]))
                            if not (np.isnan(_c) or np.isinf(_c)):
                                spy_corr_a = _c
                    row.update({
                        "最大回撤_raw": max_dd_a,
                        "SPY相关性": spy_corr_a,
                        "年化波动率": ann_vol_a,
                    })

                elif cls == "B":
                    p_1yr = p.tail(min(252, len(p)))
                    daily_ret_b = p_1yr.pct_change().dropna()
                    vol_b = float(daily_ret_b.std()) if len(daily_ret_b) > 10 else 1.0
                    ann_vol_b = vol_b * np.sqrt(252)
                    sharpe_b = float(daily_ret_b.mean() / vol_b * np.sqrt(252)) if vol_b > 1e-9 else 0.0
                    roll_max_b = p_1yr.cummax()
                    max_dd_b = float((p_1yr / roll_max_b - 1.0).min()) if not p_1yr.empty else 0.0
                    eps_stability_b = 1.0 / max(ann_vol_b, 0.01)
                    row.update({
                        "股息率": 0.0,
                        "最大回撤_raw": max_dd_b,
                        "夏普比率": sharpe_b,
                        "市值对数": 9.0,
                        "EPS稳定性": eps_stability_b,
                    })

                elif cls == "C":
                    spy_ret120 = float((spy_slice.iloc[-1] / spy_slice.iloc[-121] - 1) * 100) if len(spy_slice) >= 121 else 0.0
                    ret120     = float((p.iloc[-1] / p.iloc[-121] - 1) * 100) if len(p) >= 121 else 0.0
                    row.update({"EPS增速": z_score * 10, "RS120d": ret120 - spy_ret120, "市值对数": 9.0})

                elif cls == "D":
                    spy_ret20  = float((spy_slice.iloc[-1] / spy_slice.iloc[-21] - 1) * 100) if len(spy_slice) >= 21 else 0.0
                    ret20      = float((p.iloc[-1] / p.iloc[-21] - 1) * 100) if len(p) >= 21 else 0.0
                    ma60_dist  = float((p.iloc[-1] / ma60 - 1) * 100) if ma60 > 0 else 0.0
                    vol_z      = 0.0
                    if not v_slice.empty and t in v_slice.columns:
                        v = v_slice[t].dropna().astype(float)
                        if len(v) >= 10:
                            mu_v, sig_v = v.mean(), v.std()
                            vol_z = float((v.tail(5).mean() - mu_v) / sig_v) if sig_v > 0 else 0.0
                    row.update({"Vol_Z": vol_z, "RS_20d": ret20 - spy_ret20, "MA60偏离": ma60_dist})

                rows.append(row)

            if not rows:
                continue

            df_cls = pd.DataFrame(rows)
            if cls == "A":
                df_scored = compute_scorecard_a(df_cls)
            elif cls == "B":
                df_scored = compute_scorecard_b(df_cls)
            elif cls == "C":
                df_scored = compute_scorecard_c(df_cls, bc_regime)
            elif cls == "D":
                df_scored = compute_scorecard_d(df_cls)
            else:
                df_scored = compute_arena_scores(df_cls, cls)

            if df_scored.empty:
                continue

            top3 = [
                {"ticker": r["Ticker"], "name": r["名称"], "score": float(r["竞技得分"])}
                for _, r in df_scored.head(3).iterrows()
            ]
            _record_arena_history(cls, top3, month_key=month_key,
                                  bc_regime=bc_regime, d_regime=d_regime)

        saved += 1

    return saved, ""


# ─────────────────────────────────────────────────────────────────
#  相对评分引擎（Relative Scoring Engine）
# ─────────────────────────────────────────────────────────────────
def _minmax_norm(series: pd.Series) -> pd.Series:
    """Min-max 归一化至 [0, 100]，单值情况返回 50。"""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([50.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo) * 100.0


def compute_arena_scores(df: pd.DataFrame, cls: str) -> pd.DataFrame:
    """
    在同类资产内部计算相对竞技得分，完全由 ARENA_CONFIG 驱动。
    factor_labels 的 key 决定计分源：
      z_score     -> Z-Score 正向归一化
      z_score_inv -> Z-Score 反向归一化（低Z=高分，适用 D 级 R:R 因子）
      mom20       -> 20日动量正向归一化
      bullish     -> 趋势健康 (True=100, False=0)
    返回按竞技得分降序排列的 DataFrame，含因子分解列。
    """
    if df.empty:
        return df

    cfg = ARENA_CONFIG[cls]
    w = cfg["weights"]
    result = df.copy()

    z_norm     = _minmax_norm(result["Z-Score"].astype(float))
    z_inv_norm = _minmax_norm(-result["Z-Score"].astype(float))
    m_norm     = _minmax_norm(result["20日动量"].astype(float))
    b_norm     = result["趋势健康"].astype(float) * 100.0
    dy_norm    = _minmax_norm(result["股息率"].astype(float)) if "股息率" in result.columns else pd.Series(0.0, index=result.index)

    _source_map = {
        "z_score":     z_norm,
        "z_score_inv": z_inv_norm,
        "mom20":       m_norm,
        "bullish":     b_norm,
        "div_yield":   dy_norm,
    }

    factor_keys = list(cfg["factor_labels"].keys())
    total_score = pd.Series(0.0, index=result.index)
    for fi, fkey in enumerate(factor_keys, start=1):
        weight = w.get(fkey, 0.0)
        contrib = weight * _source_map[fkey]
        result[f"_f{fi}"] = contrib
        total_score += contrib

    result["竞技得分"] = total_score.round(1)
    for fi in range(1, len(factor_keys) + 1):
        result[f"因子{fi}_分"] = result[f"_f{fi}"].round(1)
        result.drop(columns=[f"_f{fi}"], inplace=True)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


def compute_scorecard_a(df: pd.DataFrame) -> pd.DataFrame:
    """
    ScorecardA -- A 组「避风港防御指数」评分体系 (满分 100 分)

    Score_A = (35 x InvMaxDD) + (25 x DivYield)
            + (20 x InvSPYCorr) + (20 x InvVol)

    每项原始值先取 Z-Score 再 Min-Max 归一化至 [0, 100] 后乘权重。
    需要 df 已含 "最大回撤_raw", "股息率", "SPY相关性", "年化波动率" 四列。
    """
    if df.empty:
        return df

    result = df.copy()

    dd_raw = result.get("最大回撤_raw", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _minmax_norm(-dd_raw.abs())

    div_raw = result.get("股息率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _minmax_norm(div_raw)

    corr_raw = result.get("SPY相关性", pd.Series(0.5, index=result.index)).astype(float).fillna(0.5)
    f3_norm = _minmax_norm(-corr_raw)

    vol_raw = result.get("年化波动率", pd.Series(0.3, index=result.index)).astype(float).fillna(0.3)
    f4_norm = _minmax_norm(-vol_raw)

    result["因子1_分"] = (0.35 * f1_norm).round(1)
    result["因子2_分"] = (0.25 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.20 * f4_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"] + result["因子4_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


def compute_scorecard_c(df: pd.DataFrame, macro_regime: str) -> pd.DataFrame:
    """
    ScorecardC — C 组「慢变量霸权」评分体系 (满分 100 分)

    Score_C = (50 × Z_ForwardEPS) + (15 × log10(MCap))
            + (15 × RS_120d_vs_SPY) + (20 × Fit_Macro)

    各项均先 Min-Max 归一化至 [0, 100] 后加权求和，确保总分上限 100 分。
    5日量能 Z-Score 与叙事热度已迁出 C 组，归入 D 组短周期噪音体系。
    """
    if df.empty:
        return df

    result = df.copy()

    # ── 因子 1: Forward EPS Growth Z-Score (50%)
    eps_raw = result.get("EPS增速", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _minmax_norm(eps_raw)

    # ── 因子 2: log10(MarketCap) (15%)
    mcap_log = result.get("市值对数", pd.Series(9.0, index=result.index)).astype(float).fillna(9.0)
    f2_norm = _minmax_norm(mcap_log)

    # ── 因子 3: RS_120d 中长线相对强度 vs SPY (15%)
    rs_raw = result.get("RS120d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _minmax_norm(rs_raw)

    # ── 因子 4: Macro Alignment — 标的宏观标签与当前胜率剧本匹配 (20%)
    aligned_tickers = set(_MACRO_TAGS_MAP.get(macro_regime, []))
    f4_norm = result["Ticker"].apply(lambda t: 100.0 if t in aligned_tickers else 0.0)

    result["因子1_分"] = (0.50 * f1_norm).round(1)
    result["因子2_分"] = (0.15 * f2_norm).round(1)
    result["因子3_分"] = (0.15 * f3_norm).round(1)
    result["因子4_分"] = (0.20 * f4_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"] + result["因子4_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


def _score_ma60_breakout(dist: float) -> float:
    """
    将 MA60 偏离率 (%) 转换为 0-100 分的「起飞姿态」得分。
    最佳区间：价格在 MA60 上方 0-20%（刚刚突破，旱地拔葱）→ 100 分
    超出 50%：强弩之末 → 0 分
    深埋 MA60 下方 > 20%：基础太弱 → 0 分
    """
    if -10.0 <= dist <= 20.0:
        return 100.0
    elif 20.0 < dist <= 50.0:
        return max(0.0, 100.0 - (dist - 20.0) / 30.0 * 100.0)
    elif dist > 50.0:
        return 0.0
    elif -20.0 <= dist < -10.0:
        return max(0.0, 100.0 - (abs(dist) - 10.0) / 10.0 * 50.0)
    else:
        return max(0.0, 50.0 - (abs(dist) - 20.0) / 20.0 * 50.0)


def compute_scorecard_d(df: pd.DataFrame) -> pd.DataFrame:
    """
    ScorecardD — D 组「爆点扫描仪」评分体系（满分 100 分）

    Score_D = (45 × Z_Vol5d) + (35 × RS_20d_vs_SPY) + (20 × MA60_Breakout)

    各项均先归一化至 [0, 100] 后乘权重，确保总分上限 100 分。
    需要 df 已含 "Vol_Z", "RS_20d", "MA60偏离" 三列。
    """
    if df.empty:
        return df

    result = df.copy()

    # ── 因子 1: 5日量能 Z-Score → 正向 MinMax (45%)
    vol_z_raw = result.get("Vol_Z", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _minmax_norm(vol_z_raw)

    # ── 因子 2: 20日相对 SPY 超额收益率 → 正向 MinMax (35%)
    rs_raw = result.get("RS_20d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _minmax_norm(rs_raw)

    # ── 因子 3: MA60 起飞姿态分 → 分段打分 (20%)
    ma60_raw = result.get("MA60偏离", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = ma60_raw.apply(_score_ma60_breakout)

    result["因子1_分"] = (0.45 * f1_norm).round(1)
    result["因子2_分"] = (0.35 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


def compute_scorecard_b(df: pd.DataFrame) -> pd.DataFrame:
    """
    ScorecardB -- B 组「核心底仓质量指数」评分体系 (满分 100 分)

    Score_B = (40 x RealQuality) + (30 x Resilience)
            + (20 x Sharpe1Y) + (10 x MCapPremium)

    RealQuality = (DivYield_norm + EPS_Stability_norm) / 2
    Resilience  = inverse MaxDrawdown (closer to 0 = higher score)
    Sharpe1Y    = annualized Sharpe ratio
    MCapPremium = log10(MCap) normalized
    """
    if df.empty:
        return df

    result = df.copy()

    div_raw = result.get("股息率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    eps_stab_raw = result.get("EPS稳定性", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    div_norm = _minmax_norm(div_raw)
    eps_stab_norm = _minmax_norm(eps_stab_raw)
    f1_norm = (div_norm + eps_stab_norm) / 2.0

    dd_raw = result.get("最大回撤_raw", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _minmax_norm(-dd_raw.abs())

    sharpe_raw = result.get("夏普比率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _minmax_norm(sharpe_raw)

    mcap_raw = result.get("市值对数", pd.Series(9.0, index=result.index)).astype(float).fillna(9.0)
    f4_norm = _minmax_norm(mcap_raw)

    result["因子1_分"] = (0.40 * f1_norm).round(1)
    result["因子2_分"] = (0.30 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.10 * f4_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"] + result["因子4_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


# ─────────────────────────────────────────────────────────────────
#  UI：颁奖台（Top 3 高亮展示）
# ─────────────────────────────────────────────────────────────────
_PODIUM_MEDALS = [
    ("🥇", "#FFD700", "podium-gold",   "冠军"),
    ("🥈", "#C0C0C0", "podium-silver", "亚军"),
    ("🥉", "#CD7F32", "podium-bronze", "季军"),
]

# 最多支持 5 个因子的调色板（F1 颜色由赛道 meta["color"] 动态注入）
_FACTOR_PALETTE = ["", "#3498DB", "#9B59B6", "#F39C12", "#1ABC9C"]


def _render_podium(top3: pd.DataFrame, cls: str) -> None:
    """渲染 Top 3 颁奖台卡片。"""
    meta = CLASS_META[cls]
    cfg = ARENA_CONFIG[cls]

    cols = st.columns(3)
    for i, (medal, medal_color, css_class, title) in enumerate(_PODIUM_MEDALS):
        if i >= len(top3):
            with cols[i]:
                st.markdown(
                    f"<div style='border:1px dashed #333; border-radius:12px; "
                    f"padding:20px; text-align:center; color:#555; font-size:13px;'>"
                    f"暂无数据</div>",
                    unsafe_allow_html=True,
                )
            continue

        row = top3.iloc[i]
        score = row["竞技得分"]

        n_factors = len(cfg["factor_labels"])
        f_colors = [meta["color"]] + _FACTOR_PALETTE[1:n_factors]
        factor_pills_html = ""
        for fi in range(1, n_factors + 1):
            fc = f_colors[fi - 1]
            factor_pills_html += (
                f"<span style='color:{fc}30; background:{fc}20; "
                f"border-radius:3px; padding:1px 6px;'>"
                f"F{fi} {row.get(f'因子{fi}_分', 0.0):.1f}</span> "
            )

        if cls == "A":
            dd_pct = row.get("最大回撤_raw", 0.0) * 100
            corr_v = row.get("SPY相关性", 0.5)
            vol_pct = row.get("年化波动率", 0.3) * 100
            dd_color = "#2ECC71" if abs(dd_pct) < 10 else ("#F1C40F" if abs(dd_pct) < 20 else "#E74C3C")
            corr_color = "#2ECC71" if corr_v < 0.3 else ("#F1C40F" if corr_v < 0.6 else "#E74C3C")
            vol_color = "#2ECC71" if vol_pct < 15 else ("#F1C40F" if vol_pct < 25 else "#E74C3C")
            kpi_html = (
                f"<span style='color:#888;'>最大回撤</span>"
                f"<span style='color:{dd_color}; font-weight:bold; float:right;'>{dd_pct:.1f}%</span><br>"
                f"<span style='color:#888;'>SPY相关性</span>"
                f"<span style='color:{corr_color}; font-weight:bold; float:right;'>{corr_v:.2f}</span><br>"
                f"<span style='color:#888;'>年化波动率</span>"
                f"<span style='color:{vol_color}; font-weight:bold; float:right;'>{vol_pct:.1f}%</span>"
            )
        else:
            z_val = row.get("Z-Score", 0.0)
            m_val = row.get("20日动量", 0.0)
            trend_icon = "✅" if row.get("趋势健康", False) else "🔒"
            trend_txt  = "趋势健康" if row.get("趋势健康", False) else "趋势走弱"
            z_color = "#2ECC71" if z_val > 0.5 else ("#E74C3C" if z_val < -0.5 else "#F1C40F")
            m_color = "#2ECC71" if m_val >= 0 else "#E74C3C"
            kpi_html = (
                f"<span style='color:#888;'>Z-Score</span>"
                f"<span style='color:{z_color}; font-weight:bold; float:right;'>{z_val:+.2f}</span><br>"
                f"<span style='color:#888;'>20日动量</span>"
                f"<span style='color:{m_color}; font-weight:bold; float:right;'>{m_val:+.1f}%</span><br>"
                f"<span style='color:#888;'>趋势状态</span>"
                f"<span style='color:#ccc; float:right;'>{trend_icon} {trend_txt}</span>"
            )

        with cols[i]:
            st.markdown(f"""
            <div class='{css_class}'>
                <div style='font-size:32px; margin-bottom:4px;'>{medal}</div>
                <div style='font-size:11px; color:{medal_color}; font-weight:bold;
                            letter-spacing:1px; margin-bottom:10px;'>{title}</div>
                <div style='font-size:26px; font-weight:bold; color:#eee;'>
                    {row['Ticker']}
                </div>
                <div style='font-size:11px; color:#aaa; margin-bottom:10px;'>
                    {row['名称']}
                </div>
                <div style='font-size:34px; font-weight:bold; color:{medal_color};
                            margin-bottom:4px;'>
                    {score:.0f}
                </div>
                <div style='font-size:10px; color:#888; margin-bottom:14px;'>
                    {cfg['score_name']} / 100
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:11px; text-align:left; line-height:2;'>
                    {kpi_html}
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:10px; color:#777; text-align:left; line-height:1.8; display:flex; flex-wrap:wrap; gap:4px;'>
                    {factor_pills_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
#  UI：完整排行榜（含得分条形图）
# ─────────────────────────────────────────────────────────────────
def _render_leaderboard(df_scored: pd.DataFrame, cls: str) -> None:
    """渲染完整赛道排行榜 + 因子分解横向条形图（内联至列表）。"""
    meta = CLASS_META[cls]
    cfg = ARENA_CONFIG[cls]

    st.markdown(f"#### 完整排行榜（{meta['icon']} {len(df_scored)} 位参赛选手）")

    if df_scored.empty:
        return

    factor_labels = list(cfg["factor_labels"].values())
    n_factors = len(factor_labels)
    f_colors = ([meta["color"]] + _FACTOR_PALETTE[1:n_factors])

    # 因子图例
    legend_html = "<div style='display:flex; gap:16px; font-size:11px; color:#888; margin-bottom:8px; align-items:center; flex-wrap:wrap;'>"
    legend_html += "<span style='font-weight:bold;'>因子贡献分解：</span>"
    for label, color in zip(factor_labels, f_colors):
        legend_html += f"<span style='display:flex; align-items:center; gap:4px;'><div style='width:10px; height:10px; background:{color}; border-radius:2px;'></div>{label}</span>"
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

    # ── 排行榜（div flexbox，规避 st.markdown 不渲染 table 标签的限制）──
    if cls == "A":
        header_html = (
            "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
            " color:#888; font-size:11px; padding:6px 0; font-weight:bold;'>"
            "<div style='width:46px; text-align:center;'>排名</div>"
            "<div style='width:150px;'>资产</div>"
            "<div style='flex:1; padding:0 20px;'>因子贡献分解 (堆叠)</div>"
            "<div style='width:82px; text-align:right;'>最大回撤</div>"
            "<div style='width:82px; text-align:right;'>SPY相关</div>"
            "<div style='width:82px; text-align:right;'>年化波动</div>"
            f"<div style='width:160px; padding-left:12px;'>{cfg['score_name']}</div>"
            "</div>"
        )
    else:
        header_html = (
            "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
            " color:#888; font-size:11px; padding:6px 0; font-weight:bold;'>"
            "<div style='width:46px; text-align:center;'>排名</div>"
            "<div style='width:150px;'>资产</div>"
            "<div style='flex:1; padding:0 20px;'>因子贡献分解 (堆叠)</div>"
            "<div style='width:72px; text-align:right;'>Z-Score</div>"
            "<div style='width:90px; text-align:right;'>20日动量</div>"
            "<div style='width:46px; text-align:center;'>趋势</div>"
            f"<div style='width:160px; padding-left:12px;'>{cfg['score_name']}</div>"
            "</div>"
        )

    max_score = df_scored["竞技得分"].max() if not df_scored.empty else 100.0
    rows_html = ""
    for _, row in df_scored.iterrows():
        rank = int(row["排名"])
        score = row["竞技得分"]
        bar_pct = score / max(max_score, 1.0) * 100

        if rank == 1:
            rank_html = "<span style='font-size:16px;'>🥇</span>"
        elif rank == 2:
            rank_html = "<span style='font-size:16px;'>🥈</span>"
        elif rank == 3:
            rank_html = "<span style='font-size:16px;'>🥉</span>"
        else:
            rank_html = f"<span style='color:#555; font-size:13px;'>#{rank}</span>"

        factor_bars_html = ""
        for fi, (fl, fc) in enumerate(zip(factor_labels, f_colors), start=1):
            fi_key = f"因子{fi}_分"
            fi_val = row.get(fi_key, 0.0)
            fi_pct = fi_val / max(max_score, 1.0) * 100
            factor_bars_html += (
                f"<div style='width:{fi_pct}%; background:{fc};' "
                f"title='{fl}: {fi_val:.1f}'></div>"
            )

        if cls == "A":
            dd_pct = row.get("最大回撤_raw", 0.0) * 100
            corr_v = row.get("SPY相关性", 0.5)
            vol_pct = row.get("年化波动率", 0.3) * 100
            dd_color = "#2ECC71" if abs(dd_pct) < 10 else ("#F1C40F" if abs(dd_pct) < 20 else "#E74C3C")
            corr_color = "#2ECC71" if corr_v < 0.3 else ("#F1C40F" if corr_v < 0.6 else "#E74C3C")
            vol_color = "#2ECC71" if vol_pct < 15 else ("#F1C40F" if vol_pct < 25 else "#E74C3C")
            kpi_cells = (
                f"<div style='width:82px; text-align:right; font-weight:bold; color:{dd_color};'>{dd_pct:.1f}%</div>"
                f"<div style='width:82px; text-align:right; font-weight:bold; color:{corr_color};'>{corr_v:.2f}</div>"
                f"<div style='width:82px; text-align:right; font-weight:bold; color:{vol_color};'>{vol_pct:.1f}%</div>"
            )
        else:
            z_val = row.get("Z-Score", 0.0)
            m_val = row.get("20日动量", 0.0)
            trend_icon = "✅" if row.get("趋势健康", False) else "🔒"
            z_color = "#2ECC71" if z_val > 0.5 else ("#E74C3C" if z_val < -0.5 else "#F1C40F")
            m_color = "#2ECC71" if m_val >= 0 else "#E74C3C"
            kpi_cells = (
                f"<div style='width:72px; text-align:right; font-weight:bold; color:{z_color};'>{z_val:+.2f}</div>"
                f"<div style='width:90px; text-align:right; font-weight:bold; color:{m_color};'>{m_val:+.1f}%</div>"
                f"<div style='width:46px; text-align:center;'>{trend_icon}</div>"
            )

        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='width:150px; display:flex; align-items:baseline; gap:8px;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:11px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{row['名称']}</span>"
            "</div>"
            "<div style='flex:1; padding:0 20px;'>"
            "<div style='display:flex; width:100%; height:10px; background:#1e1e1e; border-radius:4px; overflow:hidden;'>"
            f"{factor_bars_html}"
            "</div>"
            "</div>"
            f"{kpi_cells}"
            "<div style='width:160px; padding-left:12px;'>"
            "<div style='display:flex; align-items:center; gap:8px;'>"
            "<div style='flex:1; background:#1e1e1e; border-radius:4px; height:8px;'>"
            f"<div style='width:{bar_pct:.0f}%; background:{meta['color']}; border-radius:4px; height:8px;'></div>"
            "</div>"
            f"<span style='font-size:13px; font-weight:bold; color:{meta['color']}; min-width:32px;'>{score:.0f}</span>"
            "</div></div></div>"
        )

    st.markdown(
        f"<div style='width:100%; font-size:13px;'>{header_html}{rows_html}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)



# ─────────────────────────────────────────────────────────────────
#  UI：D 组专属颁奖台（展示量价/RS/MA60 三维指标）
# ─────────────────────────────────────────────────────────────────
_D_FACTOR_COLORS = ["#9B59B6", "#3498DB", "#F39C12"]   # Vol_Z / RS / MA60


def _render_podium_d(top3: pd.DataFrame) -> None:
    """D 组爆点扫描仪专属 Top 3 颁奖台。"""
    meta = CLASS_META["D"]
    cols = st.columns(3)
    for i, (medal, medal_color, css_class, title) in enumerate(_PODIUM_MEDALS):
        if i >= len(top3):
            with cols[i]:
                st.markdown(
                    "<div style='border:1px dashed #333; border-radius:12px; "
                    "padding:20px; text-align:center; color:#555; font-size:13px;'>"
                    "暂无数据</div>",
                    unsafe_allow_html=True,
                )
            continue

        row   = top3.iloc[i]
        score = row["竞技得分"]
        vol_z = row.get("Vol_Z", 0.0)
        rs    = row.get("RS_20d", 0.0)
        ma60  = row.get("MA60偏离", 0.0)

        # Vol_Z 颜色：> 1 绿，< 0 红，其余黄
        vz_color = "#2ECC71" if vol_z > 1.0 else ("#E74C3C" if vol_z < 0 else "#F1C40F")
        rs_color = "#2ECC71" if rs > 0 else "#E74C3C"

        # MA60 姿态标注
        if -10 <= ma60 <= 20:
            ma60_tag  = "⚡ 黄金突破区"
            ma60_color = "#2ECC71"
        elif 20 < ma60 <= 50:
            ma60_tag  = "⚠️ 偏高注意"
            ma60_color = "#F39C12"
        elif ma60 > 50:
            ma60_tag  = "🔴 强弩之末"
            ma60_color = "#E74C3C"
        else:
            ma60_tag  = "🔵 基础蓄力"
            ma60_color = "#3498DB"

        factor_pills_html = (
            f"<span style='color:{_D_FACTOR_COLORS[0]}30; background:{_D_FACTOR_COLORS[0]}20; "
            f"border-radius:3px; padding:1px 6px;'>F1 {row.get('因子1_分',0.0):.1f}</span> "
            f"<span style='color:{_D_FACTOR_COLORS[1]}30; background:{_D_FACTOR_COLORS[1]}20; "
            f"border-radius:3px; padding:1px 6px;'>F2 {row.get('因子2_分',0.0):.1f}</span> "
            f"<span style='color:{_D_FACTOR_COLORS[2]}30; background:{_D_FACTOR_COLORS[2]}20; "
            f"border-radius:3px; padding:1px 6px;'>F3 {row.get('因子3_分',0.0):.1f}</span>"
        )

        with cols[i]:
            st.markdown(f"""
            <div class='{css_class}'>
                <div style='font-size:32px; margin-bottom:4px;'>{medal}</div>
                <div style='font-size:11px; color:{medal_color}; font-weight:bold;
                            letter-spacing:1px; margin-bottom:10px;'>{title}</div>
                <div style='font-size:26px; font-weight:bold; color:#eee;'>{row['Ticker']}</div>
                <div style='font-size:11px; color:#aaa; margin-bottom:10px;'>{row['名称']}</div>
                <div style='font-size:34px; font-weight:bold; color:{medal_color}; margin-bottom:4px;'>
                    {score:.0f}
                </div>
                <div style='font-size:10px; color:#888; margin-bottom:14px;'>爆点扫描指数 / 100</div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:11px; text-align:left; line-height:2;'>
                    <span style='color:#888;'>量能 Z-Score</span>
                    <span style='color:{vz_color}; font-weight:bold; float:right;'>{vol_z:+.2f}</span><br>
                    <span style='color:#888;'>RS vs SPY (20d)</span>
                    <span style='color:{rs_color}; font-weight:bold; float:right;'>{rs:+.1f}%</span><br>
                    <span style='color:#888;'>MA60 偏离</span>
                    <span style='color:{ma60_color}; float:right;'>{ma60:+.1f}% {ma60_tag}</span>
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:10px; color:#777; text-align:left; line-height:1.8; display:flex; flex-wrap:wrap; gap:4px;'>
                    {factor_pills_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


def _render_leaderboard_d(df_scored: pd.DataFrame) -> None:
    """D 组爆点扫描仪专属排行榜（Vol_Z / RS / MA60 三维列）。"""
    meta = CLASS_META["D"]
    n    = len(df_scored)
    st.markdown(f"#### 完整排行榜（{meta['icon']} {n} 位参赛选手）")
    if df_scored.empty:
        return

    d_factor_labels = [
        "量价共振烈度 Vol-Price Ignition",
        "相对强度 Alpha RS₂₀",
        "均线起飞姿态 Base Breakout",
    ]
    legend_html = (
        "<div style='display:flex; gap:16px; font-size:11px; color:#888; margin-bottom:8px; "
        "align-items:center; flex-wrap:wrap;'>"
        "<span style='font-weight:bold;'>因子贡献分解：</span>"
    )
    for label, color in zip(d_factor_labels, _D_FACTOR_COLORS):
        legend_html += (
            f"<span style='display:flex; align-items:center; gap:4px;'>"
            f"<div style='width:10px; height:10px; background:{color}; border-radius:2px;'></div>"
            f"{label}</span>"
        )
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

    header_html = (
        "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
        " color:#888; font-size:11px; padding:6px 0; font-weight:bold;'>"
        "<div style='width:46px; text-align:center;'>排名</div>"
        "<div style='width:150px;'>资产</div>"
        "<div style='flex:1; padding:0 20px;'>因子贡献分解 (堆叠)</div>"
        "<div style='width:82px; text-align:right;'>量能 Z</div>"
        "<div style='width:100px; text-align:right;'>RS vs SPY</div>"
        "<div style='width:90px; text-align:right;'>MA60 偏离</div>"
        "<div style='width:160px; padding-left:12px;'>爆点扫描指数</div>"
        "</div>"
    )

    max_score  = df_scored["竞技得分"].max() if not df_scored.empty else 100.0
    rows_html  = ""
    for _, row in df_scored.iterrows():
        rank   = int(row["排名"])
        score  = row["竞技得分"]
        bar_pct = score / max(max_score, 1.0) * 100
        vol_z  = row.get("Vol_Z", 0.0)
        rs     = row.get("RS_20d", 0.0)
        ma60   = row.get("MA60偏离", 0.0)

        vz_color  = "#2ECC71" if vol_z > 1.0 else ("#E74C3C" if vol_z < 0 else "#F1C40F")
        rs_color  = "#2ECC71" if rs > 0 else "#E74C3C"
        ma60_color = "#2ECC71" if -10 <= ma60 <= 20 else ("#F39C12" if ma60 <= 50 else "#E74C3C")

        if rank == 1:
            rank_html = "<span style='font-size:16px;'>🥇</span>"
        elif rank == 2:
            rank_html = "<span style='font-size:16px;'>🥈</span>"
        elif rank == 3:
            rank_html = "<span style='font-size:16px;'>🥉</span>"
        else:
            rank_html = f"<span style='color:#555; font-size:13px;'>#{rank}</span>"

        f1_val = row.get("因子1_分", 0.0)
        f2_val = row.get("因子2_分", 0.0)
        f3_val = row.get("因子3_分", 0.0)
        f1_pct = f1_val / max(max_score, 1.0) * 100
        f2_pct = f2_val / max(max_score, 1.0) * 100
        f3_pct = f3_val / max(max_score, 1.0) * 100
        factor_bars_html = (
            f"<div style='width:{f1_pct:.0f}%; background:{_D_FACTOR_COLORS[0]};' "
            f"title='量价共振烈度: {f1_val:.1f}'></div>"
            f"<div style='width:{f2_pct:.0f}%; background:{_D_FACTOR_COLORS[1]};' "
            f"title='相对强度 Alpha: {f2_val:.1f}'></div>"
            f"<div style='width:{f3_pct:.0f}%; background:{_D_FACTOR_COLORS[2]};' "
            f"title='均线起飞姿态: {f3_val:.1f}'></div>"
        )

        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='width:150px; display:flex; align-items:baseline; gap:8px;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:11px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{row['名称']}</span>"
            "</div>"
            "<div style='flex:1; padding:0 20px;'>"
            "<div style='display:flex; width:100%; height:10px; background:#1e1e1e; border-radius:4px; overflow:hidden;'>"
            f"{factor_bars_html}"
            "</div></div>"
            f"<div style='width:82px; text-align:right; font-weight:bold; color:{vz_color};'>{vol_z:+.2f}</div>"
            f"<div style='width:100px; text-align:right; font-weight:bold; color:{rs_color};'>{rs:+.1f}%</div>"
            f"<div style='width:90px; text-align:right; font-weight:bold; color:{ma60_color};'>{ma60:+.1f}%</div>"
            "<div style='width:160px; padding-left:12px;'>"
            "<div style='display:flex; align-items:center; gap:8px;'>"
            "<div style='flex:1; background:#1e1e1e; border-radius:4px; height:8px;'>"
            f"<div style='width:{bar_pct:.0f}%; background:{meta['color']}; border-radius:4px; height:8px;'></div>"
            "</div>"
            f"<span style='font-size:13px; font-weight:bold; color:{meta['color']}; min-width:32px;'>{score:.0f}</span>"
            "</div></div></div>"
        )

    st.markdown(
        f"<div style='width:100%; font-size:13px;'>{header_html}{rows_html}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
#  UI：B 组专属颁奖台（展示股息率/最大回撤/夏普三维指标）
# ─────────────────────────────────────────────────────────────────
_B_FACTOR_COLORS = ["#F39C12", "#3498DB", "#2ECC71", "#9B59B6"]


def _render_podium_b(top3: pd.DataFrame) -> None:
    """B 组核心底仓质量指数专属 Top 3 颁奖台。"""
    meta = CLASS_META["B"]
    cols = st.columns(3)
    for i, (medal, medal_color, css_class, title) in enumerate(_PODIUM_MEDALS):
        if i >= len(top3):
            with cols[i]:
                st.markdown(
                    "<div style='border:1px dashed #333; border-radius:12px; "
                    "padding:20px; text-align:center; color:#555; font-size:13px;'>"
                    "暂无数据</div>",
                    unsafe_allow_html=True,
                )
            continue

        row   = top3.iloc[i]
        score = row["竞技得分"]
        dy    = row.get("股息率", 0.0)
        dd    = row.get("最大回撤_raw", 0.0)
        sp    = row.get("夏普比率", 0.0)

        dy_color = "#2ECC71" if dy > 2.0 else ("#F1C40F" if dy > 0.5 else "#888")
        dd_color = "#2ECC71" if abs(dd) < 0.15 else ("#F39C12" if abs(dd) < 0.25 else "#E74C3C")
        sp_color = "#2ECC71" if sp > 1.0 else ("#F1C40F" if sp > 0 else "#E74C3C")

        factor_pills_html = ""
        for fi in range(1, 5):
            fc = _B_FACTOR_COLORS[fi - 1]
            factor_pills_html += (
                f"<span style='color:{fc}30; background:{fc}20; "
                f"border-radius:3px; padding:1px 6px;'>"
                f"F{fi} {row.get(f'因子{fi}_分', 0.0):.1f}</span> "
            )

        with cols[i]:
            st.markdown(f"""
            <div class='{css_class}'>
                <div style='font-size:32px; margin-bottom:4px;'>{medal}</div>
                <div style='font-size:13px; color:{medal_color}; font-weight:bold;
                            letter-spacing:1px; margin-bottom:10px;'>{title}</div>
                <div style='font-size:26px; font-weight:bold; color:#eee;'>{row['Ticker']}</div>
                <div style='font-size:13px; color:#aaa; margin-bottom:10px;'>{row['名称']}</div>
                <div style='font-size:34px; font-weight:bold; color:{medal_color}; margin-bottom:4px;'>
                    {score:.0f}
                </div>
                <div style='font-size:13px; color:#888; margin-bottom:14px;'>核心底仓质量指数 / 100</div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; text-align:left; line-height:2;'>
                    <span style='color:#888;'>股息率</span>
                    <span style='color:{dy_color}; font-weight:bold; float:right;'>{dy:.2f}%</span><br>
                    <span style='color:#888;'>最大回撤(1Y)</span>
                    <span style='color:{dd_color}; font-weight:bold; float:right;'>{dd*100:.1f}%</span><br>
                    <span style='color:#888;'>夏普比率(1Y)</span>
                    <span style='color:{sp_color}; font-weight:bold; float:right;'>{sp:.2f}</span>
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; color:#777; text-align:left; line-height:1.8; display:flex; flex-wrap:wrap; gap:4px;'>
                    {factor_pills_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


def _render_leaderboard_b(df_scored: pd.DataFrame) -> None:
    """B 组核心底仓质量指数专属排行榜（DivYield / MaxDD / Sharpe 三维列）。"""
    meta = CLASS_META["B"]
    n    = len(df_scored)
    st.markdown(f"#### 完整排行榜（{meta['icon']} {n} 位参赛选手）")
    if df_scored.empty:
        return

    b_factor_labels = [
        "真·护城河质量",
        "抗跌韧性",
        "长效性价比 Sharpe",
        "绝对体量 MCap",
    ]
    legend_html = (
        "<div style='display:flex; gap:16px; font-size:13px; color:#888; margin-bottom:8px; "
        "align-items:center; flex-wrap:wrap;'>"
        "<span style='font-weight:bold;'>因子贡献分解：</span>"
    )
    for label, color in zip(b_factor_labels, _B_FACTOR_COLORS):
        legend_html += (
            f"<span style='display:flex; align-items:center; gap:4px;'>"
            f"<div style='width:10px; height:10px; background:{color}; border-radius:2px;'></div>"
            f"{label}</span>"
        )
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

    header_html = (
        "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
        " color:#888; font-size:13px; padding:6px 0; font-weight:bold;'>"
        "<div style='width:46px; text-align:center;'>排名</div>"
        "<div style='width:150px;'>资产</div>"
        "<div style='flex:1; padding:0 20px;'>因子贡献分解 (堆叠)</div>"
        "<div style='width:82px; text-align:right;'>股息率</div>"
        "<div style='width:100px; text-align:right;'>最大回撤</div>"
        "<div style='width:90px; text-align:right;'>夏普比率</div>"
        "<div style='width:160px; padding-left:12px;'>核心底仓质量指数</div>"
        "</div>"
    )

    max_score  = df_scored["竞技得分"].max() if not df_scored.empty else 100.0
    rows_html  = ""
    for _, row in df_scored.iterrows():
        rank   = int(row["排名"])
        score  = row["竞技得分"]
        bar_pct = score / max(max_score, 1.0) * 100
        dy     = row.get("股息率", 0.0)
        dd     = row.get("最大回撤_raw", 0.0)
        sp     = row.get("夏普比率", 0.0)

        dy_color = "#2ECC71" if dy > 2.0 else ("#F1C40F" if dy > 0.5 else "#888")
        dd_color = "#2ECC71" if abs(dd) < 0.15 else ("#F39C12" if abs(dd) < 0.25 else "#E74C3C")
        sp_color = "#2ECC71" if sp > 1.0 else ("#F1C40F" if sp > 0 else "#E74C3C")

        if rank == 1:
            rank_html = "<span style='font-size:16px;'>🥇</span>"
        elif rank == 2:
            rank_html = "<span style='font-size:16px;'>🥈</span>"
        elif rank == 3:
            rank_html = "<span style='font-size:16px;'>🥉</span>"
        else:
            rank_html = f"<span style='color:#555; font-size:13px;'>#{rank}</span>"

        factor_bars_html = ""
        for fi in range(1, 5):
            fi_val = row.get(f"因子{fi}_分", 0.0)
            fi_pct = fi_val / max(max_score, 1.0) * 100
            fc = _B_FACTOR_COLORS[fi - 1]
            fl = b_factor_labels[fi - 1]
            factor_bars_html += (
                f"<div style='width:{fi_pct:.0f}%; background:{fc};' "
                f"title='{fl}: {fi_val:.1f}'></div>"
            )

        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='width:150px; display:flex; align-items:baseline; gap:8px;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:13px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{row['名称']}</span>"
            "</div>"
            "<div style='flex:1; padding:0 20px;'>"
            "<div style='display:flex; width:100%; height:10px; background:#1e1e1e; border-radius:4px; overflow:hidden;'>"
            f"{factor_bars_html}"
            "</div></div>"
            f"<div style='width:82px; text-align:right; font-weight:bold; color:{dy_color};'>{dy:.2f}%</div>"
            f"<div style='width:100px; text-align:right; font-weight:bold; color:{dd_color};'>{dd*100:.1f}%</div>"
            f"<div style='width:90px; text-align:right; font-weight:bold; color:{sp_color};'>{sp:.2f}</div>"
            "<div style='width:160px; padding-left:12px;'>"
            "<div style='display:flex; align-items:center; gap:8px;'>"
            "<div style='flex:1; background:#1e1e1e; border-radius:4px; height:8px;'>"
            f"<div style='width:{bar_pct:.0f}%; background:{meta['color']}; border-radius:4px; height:8px;'></div>"
            "</div>"
            f"<span style='font-size:13px; font-weight:bold; color:{meta['color']}; min-width:32px;'>{score:.0f}</span>"
            "</div></div></div>"
        )

    st.markdown(
        f"<div style='width:100%; font-size:13px;'>{header_html}{rows_html}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
#  UI：单个竞技场 Tab 渲染函数
# ─────────────────────────────────────────────────────────────────
def _render_arena_tab(df_cls: pd.DataFrame, cls: str) -> None:
    meta = CLASS_META[cls]
    cfg = ARENA_CONFIG[cls]

    # ── 赛道头部介绍 ─────────────────────────────────────────────
    st.markdown(f"""
    <div class='arena-header' style='background:{meta["bg"]}; border:1px solid {meta["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta["color"]}; margin-bottom:8px;'>
            {meta["icon"]} {meta["label"]} — {cfg["score_name"]}赛道
        </div>
        <div style='font-size:12px; color:#bbb; line-height:1.8;'>{cfg["logic"]}</div>
        <div style='margin-top:10px; font-size:11px; color:#666;'>
            评分权重 →
    """, unsafe_allow_html=True)

    # 权重 pills（动态颜色，支持 2-5 个因子）
    pills_html = ""
    _n = len(cfg["factor_labels"])
    _fc_list = [meta["color"]] + _FACTOR_PALETTE[1:_n]
    for (fname, flabel), fcolor in zip(cfg["factor_labels"].items(), _fc_list):
        wval = cfg["weights"].get(fname, 0.0)
        pills_html += (
            f"<span class='factor-pill' "
            f"style='background:{fcolor}22; color:{fcolor}; border:1px solid {fcolor}55;'>"
            f"{flabel}  {int(wval*100)}%</span>"
        )

    st.markdown(f"""
            {pills_html}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if df_cls.empty:
        st.info(f"当前 {meta['label']} 赛道暂无参赛资产。请先运行 **2 资产分拣** 或开启演示模式。")
        return

    # ── 计算评分 ─────────────────────────────────────────────────
    if cls == "A":
        df_scored = compute_scorecard_a(df_cls)
    else:
        df_scored = compute_arena_scores(df_cls, cls)

    # ── 赛道统计 ─────────────────────────────────────────────────
    n_total    = len(df_scored)
    n_bullish  = int(df_scored["趋势健康"].sum()) if "趋势健康" in df_scored.columns else 0
    top_score  = df_scored["竞技得分"].iloc[0] if n_total > 0 else 0.0
    avg_score  = df_scored["竞技得分"].mean()

    if n_total > 0:
        leaders = st.session_state.get("p4_arena_leaders", {})
        leaders[cls] = [
            {
                "ticker": row["Ticker"],
                "name":   row["名称"],
                "score":  float(row["竞技得分"]),
                "cls":    cls,
            }
            for _, row in df_scored.head(3).iterrows()
        ]
        st.session_state["p4_arena_leaders"] = leaders
        _record_arena_history(cls, leaders[cls])

        # 全局数据流：将 Top-3 Ticker 写入 arena_winners，供 Page 6 消费
        _aw = st.session_state.get("arena_winners", {})
        _aw[cls] = [row["Ticker"] for _, row in df_scored.head(3).iterrows()]
        st.session_state["arena_winners"] = _aw

    kpi_cols = st.columns(4)
    if cls == "A":
        n_low_dd = int((df_scored["最大回撤_raw"].abs() < 0.15).sum()) if "最大回撤_raw" in df_scored.columns else 0
        kpi_data = [
            ("参赛资产", f"{n_total}", "只"),
            ("低回撤(<15%)", f"{n_low_dd}", f"/ {n_total}"),
            ("赛道冠军分", f"{top_score:.0f}", "/ 100"),
            ("赛道平均分", f"{avg_score:.0f}", "/ 100"),
        ]
    else:
        kpi_data = [
            ("参赛资产", f"{n_total}", "只"),
            ("趋势健康", f"{n_bullish}", f"/ {n_total}"),
            ("赛道冠军分", f"{top_score:.0f}", "/ 100"),
            ("赛道平均分", f"{avg_score:.0f}", "/ 100"),
        ]
    for col_obj, (label, val, suffix) in zip(kpi_cols, kpi_data):
        with col_obj:
            st.metric(label=label, value=val, delta=suffix)

    st.markdown("---")

    # ── 颁奖台 ───────────────────────────────────────────────────
    st.markdown(f"#### 🏆 赛道翘楚 — Top 3 高亮置顶")
    top3 = df_scored.head(3)
    _render_podium(top3, cls)

    # 冠军深度解读
    if n_total > 0:
        champ = df_scored.iloc[0]
        factor_names = list(cfg["factor_labels"].values())
        factor_breakdown = "，".join(
            f"F{fi}（{fname}）= {champ.get(f'因子{fi}_分', 0.0):.1f}"
            for fi, fname in enumerate(factor_names, start=1)
        )
        if cls == "A":
            dd_val = champ.get("最大回撤_raw", 0.0)
            corr_val = champ.get("SPY相关性", 0.5)
            vol_val = champ.get("年化波动率", 0.3)
            extra_line = (
                f"最大回撤 = **{dd_val*100:.1f}%**，SPY相关性 = **{corr_val:.2f}**，"
                f"年化波动率 = **{vol_val*100:.1f}%**。"
            )
        else:
            trend_txt = "趋势健康 (MA20 > MA60)" if champ.get("趋势健康", False) else "趋势走弱 (MA20 < MA60)"
            extra_line = (
                f"Z-Score = **{champ['Z-Score']:+.2f}**，20日动量 = **{champ['20日动量']:+.1f}%**，"
                f"{trend_txt}。"
            )
        st.success(
            f"**{meta['icon']} 赛道冠军深度解读 — {champ['Ticker']} ({champ['名称']})**\n\n"
            f"在 {meta['label']} 的 {n_total} 位参赛标的中，{champ['Ticker']} "
            f"以 **{cfg['score_name']} {champ['竞技得分']:.0f} 分**夺冠。\n"
            f"{extra_line}\n"
            f"因子贡献：{factor_breakdown}。"
        )

    st.markdown("---")

    # ── 完整排行榜 + 因子图 ──────────────────────────────────────
    _render_leaderboard(df_scored, cls)

    # ── 快捷跳转 ─────────────────────────────────────────────────
    if n_total > 0:
        champ_ticker = df_scored.iloc[0]["Ticker"]
        champ_name   = df_scored.iloc[0]["名称"]
        col_hint, col_btn = st.columns([3, 1])
        with col_hint:
            st.markdown(
                f"<div style='font-size:12px; color:#888; margin-top:6px;'>"
                f"🏆 赛道冠军 <b style='color:#FFD700;'>{champ_ticker}</b>"
                f" ({champ_name}) 已就绪，可一键送入深度猎杀模块进行单体精析。"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button("🎯 深度猎杀", key=f"hunt_{cls}"):
                st.session_state["p4_champion_ticker"] = champ_ticker
                st.success(f"已锁定 {champ_ticker}！请切换至 **5 个股深度猎杀** 页面。")


# ─────────────────────────────────────────────────────────────────
#  侧边栏
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🏆 竞技场控制台")
    demo_mode = st.toggle("演示模式（使用 Mock 数据）", value=False)
    if demo_mode:
        st.info("当前使用内置 Mock 数据演示。关闭此开关后，将读取上游 Page 2 分拣结果。")
    st.markdown("---")
    st.subheader("🧭 宏观剧本设定 (3Y 中期战略视角)")
    st.caption("平滑剧本供 B/C 组使用；原始剧本供 D 组宏观匹配")
    _regime_options = ["Soft", "Hot", "Stag", "Rec"]
    _regime_labels  = {"Soft": "软着陆/复苏", "Hot": "过热/再通胀", "Stag": "滞胀", "Rec": "衰退"}
    _ss_regime     = st.session_state.get("current_macro_regime")
    _ss_regime_raw = st.session_state.get("current_macro_regime_raw")
    _default_regime_idx = (
        _regime_options.index(_ss_regime)
        if _ss_regime in _regime_options
        else 0
    )
    if _ss_regime:
        st.success(
            f"🔗 现任剧本 (B/C)：**{_ss_regime} — {_regime_labels.get(_ss_regime, '')}**",
            icon="✅"
        )
    else:
        st.info("尚未从 Page 1 获取宏观剧本，请先访问「1 宏观定调」页面。", icon="ℹ️")
    if _ss_regime_raw:
        _raw_label = _regime_labels.get(_ss_regime_raw, _ss_regime_raw)
        st.info(f"🔭 原始信号 (D 组)：**{_ss_regime_raw} — {_raw_label}**", icon="📡")
    macro_regime = st.selectbox(
        "当前胜率最高剧本 (B/C 组用)",
        options=_regime_options,
        format_func=lambda x: f"{x} — {_regime_labels[x]}",
        index=_default_regime_idx,
    )
    _default_raw_idx = (
        _regime_options.index(_ss_regime_raw)
        if _ss_regime_raw in _regime_options
        else _default_regime_idx
    )
    macro_regime_raw = st.selectbox(
        "原始剧本 (D 组宏观匹配用)",
        options=_regime_options,
        format_func=lambda x: f"{x} — {_regime_labels[x]}",
        index=_default_raw_idx,
    )
    st.markdown("---")
    st.header("🛠️ 系统维护")
    if st.button("🔄 轻量刷新（保留历史档案与回填缓存）"):
        clear_api_caches()
        st.success("实时因子缓存已刷新！历史档案和回填价格数据完好保留。")
        st.rerun()
    if st.button("🗑️ 全局缓存重置（含回填价格缓存）"):
        st.cache_data.clear()
        st.success("全部缓存已清除（下次回填需重新下载历史价格）。历史档案文件不受影响。")
        st.rerun()
    if st.button("⚠️ 清空历史档案（换策略时使用）"):
        st.session_state["_confirm_delete_history"] = True
    if st.session_state.get("_confirm_delete_history"):
        st.warning("此操作将删除所有赛道历史月度 Top 3 记录，不可撤销。")
        _c1, _c2 = st.columns(2)
        with _c1:
            if st.button("确认删除", type="primary"):
                try:
                    if os.path.exists(_HISTORY_FILE):
                        os.remove(_HISTORY_FILE)
                    st.session_state.pop("_confirm_delete_history", None)
                    st.success("历史档案已清空！")
                    st.rerun()
                except Exception as _e:
                    st.error(f"删除失败：{_e}")
        with _c2:
            if st.button("取消"):
                st.session_state.pop("_confirm_delete_history", None)
                st.rerun()

# ─────────────────────────────────────────────────────────────────
#  页面标题
# ─────────────────────────────────────────────────────────────────
st.title("🏆 同类资产竞技场 (Same-Class Arena)")
st.caption(
    "数据源：上游 Page 2「资产分拣与白盒初筛」ABCD 分类结果 → "
    "同类内部相对评分 → 赛道翘楚高亮置顶 → 向下游 Page 5 输送冠军标的"
)

# ─────────────────────────────────────────────────────────────────
#  数据来源决策
# ─────────────────────────────────────────────────────────────────
if demo_mode:
    all_assets: dict = _MOCK_ASSETS
elif "abcd_classified_assets" in st.session_state:
    all_assets = st.session_state["abcd_classified_assets"]
else:
    st.warning(
        "**尚未获取到分拣数据。** 请先访问左侧导航栏中的 "
        "**2 资产分拣与白盒初筛** 页面完成资产 ABCD 分拣，"
        "或在左侧侧边栏开启**演示模式**以查看竞技场效果。",
        icon="🏆",
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────
#  构建全量 DataFrame
# ─────────────────────────────────────────────────────────────────
rows = []
for ticker, info in all_assets.items():
    cls = info.get("cls", "?")
    if not info.get("has_data", True) or cls not in CLASS_META:
        continue
    rows.append({
        "Ticker":   ticker,
        "名称":     info.get("cn_name", ticker),
        "类别":     cls,
        "Z-Score":  float(info.get("z_score", 0.0)),
        "20日动量": float(info.get("mom20",   0.0)),
        "趋势健康": bool(info.get("is_bullish", False)),
    })

if not rows:
    st.error("数据中无有效资产，请返回 Page 2 检查数据加载状态，或开启演示模式。")
    st.stop()

df_all = pd.DataFrame(rows).astype({"Z-Score": float, "20日动量": float})

# ─────────────────────────────────────────────────────────────────
#  Mock 模式快速预计算：一次性计算全部 4 赛道冠军并写入 arena_winners
#  （避免用户必须逐个点击 Tab 才能让 Page 6 获取完整冠军名单）
# ─────────────────────────────────────────────────────────────────
if demo_mode:
    _pre_aw: dict = {}
    _df_pre_a = df_all[df_all["类别"] == "A"].copy()
    if not _df_pre_a.empty:
        _df_pre_a["股息率"]     = 2.0
        _df_pre_a["最大回撤_raw"] = -0.08
        _df_pre_a["SPY相关性"]   = 0.3
        _df_pre_a["年化波动率"]   = 0.12
        _df_pre_a_scored = compute_scorecard_a(_df_pre_a)
        _pre_aw["A"] = [row["Ticker"] for _, row in _df_pre_a_scored.head(3).iterrows()]
    # B 组 Mock：生成模拟质量因子
    _df_pre_b = df_all[df_all["类别"] == "B"].copy()
    if not _df_pre_b.empty:
        _df_pre_b["股息率"]      = 1.5
        _df_pre_b["最大回撤_raw"] = -0.12
        _df_pre_b["夏普比率"]     = 1.2
        _df_pre_b["市值对数"]     = 11.5
        _df_pre_b["EPS稳定性"]   = 5.0
        _df_pre_b_scored = compute_scorecard_b(_df_pre_b)
        _pre_aw["B"] = [row["Ticker"] for _, row in _df_pre_b_scored.head(3).iterrows()]
    for _cls in ["C", "D"]:
        _df_pre = df_all[df_all["类别"] == _cls].copy()
        if not _df_pre.empty:
            _pre_aw[_cls] = (
                _df_pre.sort_values("20日动量", ascending=False)["Ticker"].head(3).tolist()
            )
    if _pre_aw:
        st.session_state["arena_winners"] = _pre_aw

# ─────────────────────────────────────────────────────────────────
#  全局概览横幅（可点击切换竞技场）
# ─────────────────────────────────────────────────────────────────
if "page4_selected_group" not in st.session_state:
    st.session_state["page4_selected_group"] = "A"

_sel4 = st.session_state["page4_selected_group"]

# CSS：隐形 button 叠在 HTML 大色块上方，捕获点击；:has() 实现悬停增亮
_card4_h = 120
_ABCD4 = ("[data-testid='stMainBlockContainer'] "
          "div[data-testid='stHorizontalBlock']"
          ":has(> div:nth-child(4)):not(:has(> div:nth-child(5)))"
          ":has(div[data-testid='stButton'])")

_hover4_css = []
for _i4h in range(1, 5):
    _hover4_css.append(
        f"{_ABCD4} > div:nth-child({_i4h}):has(button:hover)"
        f" div[data-testid='stMarkdownContainer'] > div {{"
        f" filter:brightness(1.18)!important; transform:translateY(-3px)!important; }}"
    )

st.markdown(f"""
<style>
{_ABCD4} div[data-testid='stButton'] {{
    height:0!important; position:relative!important; z-index:100!important;
}}
{_ABCD4} div[data-testid='stButton'] button {{
    position:absolute!important; top:-{_card4_h}px!important;
    left:0!important; right:0!important; height:{_card4_h}px!important;
    opacity:0!important; cursor:pointer!important;
    border:none!important; background:transparent!important;
}}
{_ABCD4} div[data-testid='stMarkdownContainer'] > div {{
    transition: filter 0.15s ease, transform 0.15s ease;
}}
{chr(10).join(_hover4_css)}
</style>
""", unsafe_allow_html=True)

overview_cols = st.columns(4)
for i, cls in enumerate(["A", "B", "C", "D"]):
    meta     = CLASS_META[cls]
    n        = len(df_all[df_all["类别"] == cls])
    selected = (cls == _sel4)
    color    = meta["color"]
    bg       = f"{color}30" if selected else meta["bg"]
    bdr      = f"2px solid {color}" if selected else f"1px solid {color}44"
    glow     = f"0 0 14px {color}55" if selected else "none"
    with overview_cols[i]:
        st.markdown(f"""
        <div style='background:{bg}; border:{bdr}; box-shadow:{glow};
                    border-radius:8px; padding:12px; text-align:center;
                    height:{_card4_h}px; display:flex; flex-direction:column;
                    justify-content:center; align-items:center; gap:4px;'>
            <div style='font-size:24px;'>{meta["icon"]}</div>
            <div style='font-size:26px; font-weight:bold; color:{color}; line-height:1.1;'>{n}</div>
            <div style='font-size:11px; color:#bbb;'>{meta["label"]}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("", key=f"arena_btn_{cls}", use_container_width=True):
            st.session_state["page4_selected_group"] = cls
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  四大竞技场（由顶部色块控制，无 Tabs）
# ─────────────────────────────────────────────────────────────────

_sel4 = st.session_state["page4_selected_group"]

if _sel4 == "A":
    df_a = df_all[df_all["类别"] == "A"].copy()
    if not df_a.empty:
        with st.spinner("正在拉取 A 组避风港因子数据（最大回撤、股息率、SPY相关性、年化波动率）…"):
            _factors_a = get_arena_a_factors(tuple(df_a["Ticker"].tolist()))
        df_a["股息率"]     = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("div_yield",   0.0)))
        df_a["最大回撤_raw"] = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("max_dd_252",  0.0)))
        df_a["SPY相关性"]   = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("spy_corr",    0.5)))
        df_a["年化波动率"]   = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("ann_vol",     0.30)))
    else:
        df_a["股息率"]     = 0.0
        df_a["最大回撤_raw"] = 0.0
        df_a["SPY相关性"]   = 0.5
        df_a["年化波动率"]   = 0.30
    _render_arena_tab(df_a, "A")

elif _sel4 == "B":
    df_b  = df_all[df_all["类别"] == "B"].copy()
    meta  = CLASS_META["B"]
    cfg_b = ARENA_CONFIG["B"]

    st.markdown(f"""
    <div class='arena-header' style='background:{meta["bg"]}; border:1px solid {meta["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta["color"]}; margin-bottom:8px;'>
            {meta["icon"]} {meta["label"]} -- {cfg_b["score_name"]}赛道
        </div>
        <div style='font-size:13px; color:#bbb; line-height:1.8;'>{cfg_b["logic"]}</div>
        <div style='margin-top:10px; font-size:13px; color:#666;'>
            评分权重 →
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[0]}22; color:{_B_FACTOR_COLORS[0]}; border:1px solid {_B_FACTOR_COLORS[0]}55;'>真·护城河质量  40%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[1]}22; color:{_B_FACTOR_COLORS[1]}; border:1px solid {_B_FACTOR_COLORS[1]}55;'>抗跌韧性  30%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[2]}22; color:{_B_FACTOR_COLORS[2]}; border:1px solid {_B_FACTOR_COLORS[2]}55;'>夏普比率  20%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[3]}22; color:{_B_FACTOR_COLORS[3]}; border:1px solid {_B_FACTOR_COLORS[3]}55;'>绝对体量  10%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #F39C12;
         padding:14px; margin-bottom:16px; font-size:14px; color:#ccc; border-radius:4px;'>
    <b>ScorecardB 白盒公式（满分 100 分）-- 慢变量底仓质量，拒绝短期动量：</b><br><br>
    <span style='color:#F39C12; font-weight:bold;'>Score<sub>B</sub></span> =
    <span style='color:#F39C12;'>(40 x RealQuality<sub>norm</sub>)</span> +
    <span style='color:#3498DB;'>(30 x Resilience<sub>InvMaxDD</sub>)</span> +
    <span style='color:#2ECC71;'>(20 x Sharpe<sub>1Y</sub>)</span> +
    <span style='color:#9B59B6;'>(10 x MCap<sub>log10</sub>)</span><br><br>
    <span style='color:#888; font-size:13px;'>
    RealQuality = (DivYield<sub>norm</sub> + EPS_Stability<sub>norm</sub>) / 2 (股息率 + 年化波动率倒数 代理 FCF/ROIC)。<br>
    Resilience = 近 252 日最大回撤取倒数，回撤越小得分越高。<br>
    所有因子均经 Min-Max 归一化至 [0, 100] 后加权求和。彻底剔除动量/均线等短线信号。
    </span>
    </div>
    """, unsafe_allow_html=True)

    if df_b.empty:
        st.info("当前 B 级赛道暂无参赛资产。请先运行 **2 资产分拣** 或开启演示模式。")
    else:
        with st.spinner("正在拉取 B 组底仓质量因子数据（股息率、最大回撤、夏普比率、市值）…"):
            _factors_b = get_arena_b_factors(tuple(df_b["Ticker"].tolist()))

        df_b["股息率"]     = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("div_yield",      0.0)))
        df_b["最大回撤_raw"] = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("max_dd_252",     0.0)))
        df_b["夏普比率"]    = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("sharpe_252",      0.0)))
        df_b["市值对数"]    = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("log_mcap",        9.0)))
        df_b["EPS稳定性"]  = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("eps_stability",   0.0)))

        df_scored_b = compute_scorecard_b(df_b)

        n_b = len(df_scored_b)
        if n_b > 0:
            leaders = st.session_state.get("p4_arena_leaders", {})
            leaders["B"] = [
                {"ticker": row["Ticker"], "name": row["名称"], "score": float(row["竞技得分"]), "cls": "B"}
                for _, row in df_scored_b.head(3).iterrows()
            ]
            st.session_state["p4_arena_leaders"] = leaders
            _record_arena_history("B", leaders["B"])

            _aw = st.session_state.get("arena_winners", {})
            _aw["B"] = [row["Ticker"] for _, row in df_scored_b.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw

        top_score_b = df_scored_b["竞技得分"].iloc[0] if n_b > 0 else 0.0
        avg_score_b = df_scored_b["竞技得分"].mean()  if n_b > 0 else 0.0
        n_low_dd    = int((df_scored_b["最大回撤_raw"].abs() < 0.15).sum()) if n_b > 0 else 0

        kpi_cols_b = st.columns(4)
        for col_obj, (label, val, suffix) in zip(kpi_cols_b, [
            ("参赛资产",       f"{n_b}",            "只"),
            ("低回撤(<15%)",   f"{n_low_dd}",       f"/ {n_b}"),
            ("赛道冠军分",     f"{top_score_b:.0f}", "/ 100"),
            ("赛道平均分",     f"{avg_score_b:.0f}", "/ 100"),
        ]):
            with col_obj:
                st.metric(label=label, value=val, delta=suffix)

        st.markdown("---")
        st.markdown("#### 🏆 赛道翘楚 -- Top 3 高亮置顶")
        _render_podium_b(df_scored_b.head(3))

        if n_b > 0:
            champ_b  = df_scored_b.iloc[0]
            dy_c     = champ_b.get("股息率", 0.0)
            dd_c     = champ_b.get("最大回撤_raw", 0.0)
            sp_c     = champ_b.get("夏普比率", 0.0)

            if abs(dd_c) < 0.10:
                dd_verdict = "极强抗跌韧性"
            elif abs(dd_c) < 0.20:
                dd_verdict = "回撤控制良好"
            else:
                dd_verdict = "回撤偏大，需警惕"

            st.success(
                f"**🦍 赛道冠军深度解读 -- {champ_b['Ticker']} ({champ_b['名称']})**\n\n"
                f"在 B 级 {n_b} 位参赛标的中以 **核心底仓质量指数 {champ_b['竞技得分']:.0f} 分**夺冠。\n"
                f"真·护城河质量贡献 = {champ_b['因子1_分']:.1f}（股息率 {dy_c:.2f}%），"
                f"抗跌韧性贡献 = {champ_b['因子2_分']:.1f}（最大回撤 {dd_c*100:.1f}% -- {dd_verdict}），"
                f"夏普比率贡献 = {champ_b['因子3_分']:.1f}（Sharpe {sp_c:.2f}），"
                f"市值壁垒贡献 = {champ_b['因子4_分']:.1f}。"
            )

        st.markdown("---")
        _render_leaderboard_b(df_scored_b)

        if n_b > 0:
            champ_ticker_b = df_scored_b.iloc[0]["Ticker"]
            champ_name_b   = df_scored_b.iloc[0]["名称"]
            col_hint_b, col_btn_b = st.columns([3, 1])
            with col_hint_b:
                st.markdown(
                    f"<div style='font-size:13px; color:#888; margin-top:6px;'>"
                    f"🏆 赛道冠军 <b style='color:#FFD700;'>{champ_ticker_b}</b>"
                    f" ({champ_name_b}) 已就绪，可一键送入深度猎杀模块进行单体精析。"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_btn_b:
                if st.button("🎯 深度猎杀", key="hunt_B"):
                    st.session_state["p4_champion_ticker"] = champ_ticker_b
                    st.success(f"已锁定 {champ_ticker_b}！请切换至 **5 个股深度猎杀** 页面。")

elif _sel4 == "C":
    df_c = df_all[df_all["类别"] == "C"].copy()
    meta = CLASS_META["C"]
    cfg_c = ARENA_CONFIG["C"]

    st.markdown(f"""
    <div class='arena-header' style='background:{meta["bg"]}; border:1px solid {meta["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta["color"]}; margin-bottom:8px;'>
            {meta["icon"]} {meta["label"]} — {cfg_c["score_name"]}赛道
        </div>
        <div style='font-size:12px; color:#bbb; line-height:1.8;'>{cfg_c["logic"]}</div>
        <div style='margin-top:10px; font-size:11px; color:#666;'>
            评分权重 →
            <span class='factor-pill' style='background:{meta["color"]}22; color:{meta["color"]}; border:1px solid {meta["color"]}55;'>Forward EPS Z-Score  50%</span>
            <span class='factor-pill' style='background:#3498DB22; color:#3498DB; border:1px solid #3498DB55;'>log₁₀(MCap)  15%</span>
            <span class='factor-pill' style='background:#9B59B622; color:#9B59B6; border:1px solid #9B59B655;'>RS₁₂₀ 中长线强度  15%</span>
            <span class='factor-pill' style='background:#F39C1222; color:#F39C12; border:1px solid #F39C1255;'>宏观顺风  20%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 白盒公式展示 ──────────────────────────────────────────────
    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #E74C3C; padding:14px; margin-bottom:16px; font-size:13px; color:#ccc; border-radius:4px;'>
    <b>⚙️ ScorecardC 白盒公式（满分 100 分）— 慢变量霸权，拒绝短期噪音：</b><br><br>
    <span style='color:#E74C3C; font-weight:bold;'>Score<sub>C</sub></span> =
    <span style='color:#E74C3C;'>(50 × Z<sub>ForwardEPS</sub>)</span> +
    <span style='color:#3498DB;'>(15 × log₁₀(MCap)<sub>norm</sub>)</span> +
    <span style='color:#9B59B6;'>(15 × RS<sub>120d vs SPY</sub>)</span> +
    <span style='color:#F39C12;'>(20 × Fit<sub>Macro</sub>)</span><br><br>
    <span style='color:#888; font-size:13px;'>
    各因子均经 Min-Max 归一化至 [0, 100] 后加权求和。RS₁₂₀ = 标的过去 120 日涨跌幅 − SPY 同期涨跌幅（半年超额收益）。<br>
    5日量能 Z-Score 与叙事热度已迁入 D 组短周期体系，不再参与 C 组定价。<br>
    当前宏观剧本（Macro Fit 判定基准）：<b style='color:#F39C12;'>{regime}</b>
    </span>
    </div>
    """.format(regime=macro_regime), unsafe_allow_html=True)

    if df_c.empty:
        st.info(f"当前 C 级赛道暂无参赛资产。请先运行 **2 资产分拣** 或开启演示模式。")
    else:
        with st.spinner("正在拉取 C 组基本面因子数据（EPS增速、RS₁₂₀中长线强度、市值）…"):
            _meta_c    = get_stock_metadata(tuple(df_c["Ticker"].tolist()))
            _factors_c = get_arena_c_factors(tuple(df_c["Ticker"].tolist()))

        df_c["市值对数"] = df_c["Ticker"].map(
            lambda t: float(np.log10(max(float(_meta_c.get(t, {}).get("mcap", 1e9)), 1e6)))
        )
        df_c["EPS增速"] = df_c["Ticker"].map(
            lambda t: float(_factors_c.get(t, {}).get("earnings_growth", 0.0))
        )
        df_c["RS120d"] = df_c["Ticker"].map(
            lambda t: float(_factors_c.get(t, {}).get("rs_120d", 0.0))
        )

        df_scored_c = compute_scorecard_c(df_c, macro_regime)

        # 保存至 session_state 供下游使用
        n_c = len(df_scored_c)
        if n_c > 0:
            leaders = st.session_state.get("p4_arena_leaders", {})
            leaders["C"] = [
                {"ticker": row["Ticker"], "name": row["名称"], "score": float(row["竞技得分"]), "cls": "C"}
                for _, row in df_scored_c.head(3).iterrows()
            ]
            st.session_state["p4_arena_leaders"] = leaders
            _record_arena_history("C", leaders["C"],
                                  bc_regime=macro_regime, d_regime=macro_regime_raw)

            # 全局数据流：C 组 Top-3 Ticker → arena_winners
            _aw = st.session_state.get("arena_winners", {})
            _aw["C"] = [row["Ticker"] for _, row in df_scored_c.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw

        n_bullish_c = int(df_scored_c["趋势健康"].sum())
        top_score_c = df_scored_c["竞技得分"].iloc[0] if n_c > 0 else 0.0
        avg_score_c = df_scored_c["竞技得分"].mean() if n_c > 0 else 0.0

        kpi_cols_c = st.columns(4)
        for col_obj, (label, val, suffix) in zip(kpi_cols_c, [
            ("参赛资产", f"{n_c}", "只"),
            ("趋势健康", f"{n_bullish_c}", f"/ {n_c}"),
            ("赛道冠军分", f"{top_score_c:.0f}", "/ 100"),
            ("赛道平均分", f"{avg_score_c:.0f}", "/ 100"),
        ]):
            with col_obj:
                st.metric(label=label, value=val, delta=suffix)

        st.markdown("---")
        st.markdown("#### 🏆 赛道翘楚 — Top 3 高亮置顶")
        _render_podium(df_scored_c.head(3), "C")

        if n_c > 0:
            champ_c = df_scored_c.iloc[0]
            trend_txt_c = "趋势健康 (MA20 > MA60)" if champ_c["趋势健康"] else "趋势走弱 (MA20 < MA60)"
            aligned_c = champ_c["Ticker"] in set(_MACRO_TAGS_MAP.get(macro_regime, []))
            rs_c = float(champ_c.get("RS120d", 0.0))
            st.success(
                f"**👑 赛道冠军深度解读 — {champ_c['Ticker']} ({champ_c['名称']})**\n\n"
                f"在 C 级 {n_c} 位参赛标的中以 **慢变量霸权指数 {champ_c['竞技得分']:.0f} 分**夺冠。\n"
                f"Forward EPS 增速贡献 = {champ_c['因子1_分']:.1f}，"
                f"log₁₀(市值) 贡献 = {champ_c['因子2_分']:.1f}，"
                f"RS₁₂₀ 中长线强度贡献 = {champ_c['因子3_分']:.1f}（半年超额收益 {rs_c:+.1f}%），"
                f"宏观顺风 = {champ_c['因子4_分']:.1f}（{'✅ 顺风' if aligned_c else '❌ 逆风'}，剧本：{macro_regime}）。\n"
                f"趋势状态：{trend_txt_c}。"
            )

        st.markdown("---")
        _render_leaderboard(df_scored_c, "C")

        if n_c > 0:
            champ_ticker_c = df_scored_c.iloc[0]["Ticker"]
            champ_name_c   = df_scored_c.iloc[0]["名称"]
            col_hint_c, col_btn_c = st.columns([3, 1])
            with col_hint_c:
                st.markdown(
                    f"<div style='font-size:12px; color:#888; margin-top:6px;'>"
                    f"🏆 赛道冠军 <b style='color:#FFD700;'>{champ_ticker_c}</b>"
                    f" ({champ_name_c}) 已就绪，可一键送入深度猎杀模块进行单体精析。"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_btn_c:
                if st.button("🎯 深度猎杀", key="hunt_C"):
                    st.session_state["p4_champion_ticker"] = champ_ticker_c
                    st.success(f"已锁定 {champ_ticker_c}！请切换至 **5 个股深度猎杀** 页面。")

elif _sel4 == "D":
    df_d  = df_all[df_all["类别"] == "D"].copy()
    meta  = CLASS_META["D"]
    cfg_d = ARENA_CONFIG["D"]

    # ── 赛道头部介绍 ──────────────────────────────────────────────
    st.markdown(f"""
    <div class='arena-header' style='background:{meta["bg"]}; border:1px solid {meta["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta["color"]}; margin-bottom:8px;'>
            {meta["icon"]} {meta["label"]} — {cfg_d["score_name"]}赛道
        </div>
        <div style='font-size:13px; color:#bbb; line-height:1.8;'>{cfg_d["logic"]}</div>
        <div style='margin-top:10px; font-size:11px; color:#666;'>
            评分权重 →
            <span class='factor-pill' style='background:{_D_FACTOR_COLORS[0]}22; color:{_D_FACTOR_COLORS[0]}; border:1px solid {_D_FACTOR_COLORS[0]}55;'>量价共振烈度  45%</span>
            <span class='factor-pill' style='background:{_D_FACTOR_COLORS[1]}22; color:{_D_FACTOR_COLORS[1]}; border:1px solid {_D_FACTOR_COLORS[1]}55;'>相对强度 Alpha RS₂₀  35%</span>
            <span class='factor-pill' style='background:{_D_FACTOR_COLORS[2]}22; color:{_D_FACTOR_COLORS[2]}; border:1px solid {_D_FACTOR_COLORS[2]}55;'>均线起飞姿态  20%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 白盒公式展示 ──────────────────────────────────────────────
    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #9B59B6;
         padding:14px; margin-bottom:16px; font-size:13px; color:#ccc; border-radius:4px;'>
    <b>⚙️ ScorecardD 白盒公式（满分 100 分）：</b><br><br>
    <span style='color:#9B59B6; font-weight:bold;'>Score<sub>D</sub></span> =
    <span style='color:#9B59B6;'>(45 × Z<sub>Vol5d</sub>)</span> +
    <span style='color:#3498DB;'>(35 × RS<sub>20d vs SPY</sub>)</span> +
    <span style='color:#F39C12;'>(20 × MA60<sub>Breakout</sub>)</span><br><br>
    <span style='color:#888; font-size:11px;'>
    MA60 起飞姿态分：0-20% 突破区满分，>50% 强弩之末 0 分，
    深埋 MA60 20% 以下得分递减。Vol Z-Score 和 RS 均经 Min-Max 归一化。
    </span>
    </div>
    """, unsafe_allow_html=True)

    if df_d.empty:
        st.info("当前 D 级赛道暂无参赛资产。请先运行 **2 资产分拣** 或开启演示模式。")
    else:
        with st.spinner("正在拉取 D 组爆点因子数据（Vol_Z、RS vs SPY、MA60 位置）…"):
            _factors_d = get_arena_d_factors(tuple(df_d["Ticker"].tolist()))

        df_d["Vol_Z"]   = df_d["Ticker"].map(lambda t: float(_factors_d.get(t, {}).get("vol_z",    0.0)))
        df_d["RS_20d"]  = df_d["Ticker"].map(lambda t: float(_factors_d.get(t, {}).get("rs_20d",   0.0)))
        df_d["MA60偏离"] = df_d["Ticker"].map(lambda t: float(_factors_d.get(t, {}).get("ma60_dist", 0.0)))

        df_scored_d = compute_scorecard_d(df_d)

        # 保存至 session_state 供下游使用
        n_d = len(df_scored_d)
        if n_d > 0:
            leaders = st.session_state.get("p4_arena_leaders", {})
            leaders["D"] = [
                {"ticker": row["Ticker"], "name": row["名称"], "score": float(row["竞技得分"]), "cls": "D"}
                for _, row in df_scored_d.head(3).iterrows()
            ]
            st.session_state["p4_arena_leaders"] = leaders
            _record_arena_history("D", leaders["D"],
                                  bc_regime=macro_regime, d_regime=macro_regime_raw)

            # 全局数据流：D 组 Top-3 Ticker → arena_winners
            _aw = st.session_state.get("arena_winners", {})
            _aw["D"] = [row["Ticker"] for _, row in df_scored_d.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw

        # ── KPI 卡片 ─────────────────────────────────────────────
        top_score_d = df_scored_d["竞技得分"].iloc[0] if n_d > 0 else 0.0
        avg_score_d = df_scored_d["竞技得分"].mean()  if n_d > 0 else 0.0
        n_breakout  = int((df_scored_d["MA60偏离"].between(-10, 20)).sum()) if n_d > 0 else 0

        kpi_cols_d = st.columns(4)
        for col_obj, (label, val, suffix) in zip(kpi_cols_d, [
            ("参赛资产",       f"{n_d}",           "只"),
            ("黄金突破区",     f"{n_breakout}",    f"/ {n_d}"),
            ("赛道冠军分",     f"{top_score_d:.0f}", "/ 100"),
            ("赛道平均分",     f"{avg_score_d:.0f}", "/ 100"),
        ]):
            with col_obj:
                st.metric(label=label, value=val, delta=suffix)

        st.markdown("---")

        # ── 颁奖台 ────────────────────────────────────────────────
        st.markdown("#### 🏆 赛道翘楚 — Top 3 高亮置顶")
        _render_podium_d(df_scored_d.head(3))

        # ── 冠军深度解读 ──────────────────────────────────────────
        if n_d > 0:
            champ_d = df_scored_d.iloc[0]
            vol_z_c  = champ_d.get("Vol_Z", 0.0)
            rs_c     = champ_d.get("RS_20d", 0.0)
            ma60_c   = champ_d.get("MA60偏离", 0.0)

            if -10 <= ma60_c <= 20:
                ma60_verdict = "⚡ 处于黄金突破区（季线起飞最佳姿态）"
            elif ma60_c > 50:
                ma60_verdict = "🔴 乖离过大（强弩之末，建议等回调）"
            elif ma60_c > 20:
                ma60_verdict = "⚠️ 偏离季线偏高，注意追高风险"
            else:
                ma60_verdict = "🔵 尚在季线下方蓄力，等待突破信号"

            st.success(
                f"**🚀 赛道冠军深度解读 — {champ_d['Ticker']} ({champ_d['名称']})**\n\n"
                f"在 D 级 {n_d} 位参赛标的中以 **爆点扫描指数 {champ_d['竞技得分']:.0f} 分**夺冠。\n"
                f"量价共振烈度（Vol_Z）= **{vol_z_c:+.2f}**，贡献 {champ_d['因子1_分']:.1f} 分；"
                f"相对强度 RS₂₀ vs SPY = **{rs_c:+.1f}%**，贡献 {champ_d['因子2_分']:.1f} 分；"
                f"MA60 偏离 = **{ma60_c:+.1f}%** — {ma60_verdict}，贡献 {champ_d['因子3_分']:.1f} 分。"
            )

        st.markdown("---")

        # ── 完整排行榜 ─────────────────────────────────────────────
        _render_leaderboard_d(df_scored_d)

        # ── 快捷跳转 ──────────────────────────────────────────────
        if n_d > 0:
            champ_ticker_d = df_scored_d.iloc[0]["Ticker"]
            champ_name_d   = df_scored_d.iloc[0]["名称"]
            col_hint_d, col_btn_d = st.columns([3, 1])
            with col_hint_d:
                st.markdown(
                    f"<div style='font-size:13px; color:#888; margin-top:6px;'>"
                    f"🏆 赛道冠军 <b style='color:#FFD700;'>{champ_ticker_d}</b>"
                    f" ({champ_name_d}) 已就绪，可一键送入深度猎杀模块进行单体精析。"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_btn_d:
                if st.button("🎯 深度猎杀", key="hunt_D"):
                    st.session_state["p4_champion_ticker"] = champ_ticker_d
                    st.success(f"已锁定 {champ_ticker_d}！请切换至 **5 个股深度猎杀** 页面。")

# ─────────────────────────────────────────────────────────────────
#  历史榜单 — 只显示当前选中赛道（_sel4）的月度 Top 3
# ─────────────────────────────────────────────────────────────────
_hist_meta = CLASS_META[_sel4]
st.markdown("---")
st.markdown(
    f"### 📅 {_hist_meta['icon']} {_hist_meta['label']} — 历史月度 Top 3",
)
st.caption(
    f"当前赛道：{_hist_meta['label']}。纵向追踪每月末排名，"
    "方便确认哪些标的被持续输送至 Page 5 / Page 6。"
    "切换顶部 ABCD 色块即可查看其他赛道历史。"
)

# ── 回填控制区 ───────────────────────────────────────────────────
_bf_col1, _bf_col2, _bf_col3 = st.columns([2, 1, 3])
with _bf_col1:
    _bf_months = st.selectbox(
        "回填月数", options=[12, 18, 24, 36, 60], index=2,
        format_func=lambda x: f"过去 {x} 个月",
        key="bf_months_sel",
        help="选择要回填的历史月份数（月数越多下载时间越长）",
    )
with _bf_col2:
    _do_backfill = st.button("🔄 回填历史数据", use_container_width=True,
                             help="用 yfinance 历史价格数据重算每月末各赛道排名并写入档案")
with _bf_col3:
    st.markdown(
        "<div style='font-size:13px; color:#666; padding-top:8px;'>"
        "注：A/B 组 Z-Score 用价格滚动 Z 代理；C 组 EPS 用动量代理；D 组三因子全量计算。"
        "首次下载约需 60-120 秒（5年数据量较大）。</div>",
        unsafe_allow_html=True,
    )

if _do_backfill:
    with st.spinner(f"正在下载 {len(all_assets)} 只标的约 6 年历史数据并逐月计算…"):
        _bf_saved, _bf_err = _backfill_arena_history(
            all_assets, months_back=_bf_months,
            monthly_probs=st.session_state.get("horsemen_monthly_probs", {}),
        )
    if _bf_err:
        st.error(f"回填失败：{_bf_err}")
    else:
        st.success(f"回填完成！已写入 {_bf_saved} 个月的历史档案。")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ── 当前赛道历史数据展示 ─────────────────────────────────────────
_history      = _load_arena_history()
_medal_icons  = ["🥇", "🥈", "🥉"]
_medal_colors = ["#FFD700", "#C0C0C0", "#CD7F32"]

# 宏观剧本徽章（用于历史榜单宏观列）
_REGIME_BADGE: dict = {
    "Soft": ("<span style='color:#2ECC71; font-size:12px; font-weight:bold;'>🚗 软着陆</span>", "#2ECC71"),
    "Hot":  ("<span style='color:#E74C3C; font-size:12px; font-weight:bold;'>🔥 再通胀</span>", "#E74C3C"),
    "Stag": ("<span style='color:#F1C40F; font-size:12px; font-weight:bold;'>🚨 滞胀</span>",   "#F1C40F"),
    "Rec":  ("<span style='color:#3498DB; font-size:12px; font-weight:bold;'>❄️ 衰退</span>",   "#3498DB"),
}
_REGIME_BADGE_EMPTY = ("<span style='color:#444; font-size:12px;'>—</span>", "#444")


def _hist_cell(rec: dict, medal_color: str) -> str:
    return (
        f"<div style='flex:1; display:flex; align-items:baseline; gap:5px; "
        f"min-width:0; padding-left:4px;'>"
        f"<span style='font-size:14px; font-weight:bold; color:#eee; flex-shrink:0;'>"
        f"{rec['ticker']}</span>"
        f"<span style='font-size:13px; color:#888; overflow:hidden; "
        f"text-overflow:ellipsis; white-space:nowrap; flex:1;'>{rec['name']}</span>"
        f"<span style='font-size:13px; font-weight:bold; color:{medal_color}; "
        f"flex-shrink:0; margin-left:4px;'>{rec['score']:.0f}</span>"
        f"</div>"
    )


def _hist_empty() -> str:
    return "<div style='flex:1; font-size:13px; color:#333; padding-left:4px;'>—</div>"


if not _history:
    st.info("暂无历史记录。点击上方「回填历史数据」按钮，一键生成过去 N 个月的档案。", icon="📋")
else:
    _sorted_months = sorted(_history.keys(), reverse=True)
    _cls_months    = [mo for mo in _sorted_months if _sel4 in _history[mo]]

    if not _cls_months:
        st.info(
            f"{_hist_meta['icon']} {_hist_meta['label']} 暂无历史记录。"
            "点击上方「回填历史数据」按钮生成档案。",
            icon="📋",
        )
    else:
        _TH = (
            "display:flex; align-items:center; padding:6px 8px; "
            "border-bottom:2px solid #2a2a2a; font-size:13px; color:#555; font-weight:bold;"
        )
        _header_row = (
            f"<div style='{_TH}'>"
            f"<div style='width:80px; flex-shrink:0;'>月份</div>"
            f"<div style='width:100px; flex-shrink:0; padding-left:4px;'>宏观背景</div>"
            f"<div style='flex:1; padding-left:4px;'>🥇 冠军</div>"
            f"<div style='flex:1; padding-left:4px;'>🥈 亚军</div>"
            f"<div style='flex:1; padding-left:4px;'>🥉 季军</div>"
            f"</div>"
        )
        _data_rows = ""
        for _idx, _mo in enumerate(_cls_months):
            _recs  = _history[_mo].get(_sel4, [])
            _meta  = _history[_mo].get("_meta", {})
            _rkey  = _meta.get("d_regime", "") if _sel4 == "D" else _meta.get("bc_regime", "")
            _badge_html, _badge_color = _REGIME_BADGE.get(_rkey, _REGIME_BADGE_EMPTY)
            _bg    = "#111" if _idx % 2 == 0 else "#0d0d0d"
            _row   = (
                f"<div style='display:flex; align-items:center; padding:8px 8px; "
                f"background:{_bg}; border-bottom:1px solid #1a1a1a;'>"
                f"<div style='width:80px; font-size:13px; font-weight:bold; "
                f"color:{_hist_meta['color']}; flex-shrink:0;'>{_mo}</div>"
                f"<div style='width:100px; flex-shrink:0; padding-left:4px;'>{_badge_html}</div>"
            )
            for _ri in range(3):
                _row += _hist_cell(_recs[_ri], _medal_colors[_ri]) if _ri < len(_recs) else _hist_empty()
            _row += "</div>"
            _data_rows += _row

        st.markdown(
            f"<div style='border:1px solid {_hist_meta['color']}44; border-radius:8px; "
            f"overflow:hidden;'>{_header_row}{_data_rows}</div>",
            unsafe_allow_html=True,
        )
