import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import os
import requests
import calendar
import yfinance as yf
from _yf_session import YF_SESSION  # curl_cffi 浏览器指纹，绕 Yahoo 401
from datetime import datetime, timedelta
from api_client import (fetch_core_data, get_global_data, get_stock_metadata,
                        get_arena_a_factors, get_arena_b_factors,
                        get_arena_c_factors, get_arena_d_factors,
                        get_arena_a_scores as _api_get_arena_a_scores,
                        fetch_l2_l3_detail, get_batch_ticker_cooccurrence,
                        fetch_conviction_state as _api_fetch_conv,
                        push_conviction_state as _api_push_conv,
                        fetch_arena_history as _api_fetch_history,
                        push_arena_history_batch as _api_push_history_batch,
                        clear_arena_history_backend as _api_clear_history,
                        fetch_current_regime, push_screen_results,
                        run_classification_api,
                        arena_backfill_score as _api_arena_backfill_score,
                        API_BASE_URL, IS_PROD_REMOTE)
from screener_engine import (
    compute_metrics as _engine_compute_metrics,
    classify_asset_parallel,
    classify_all_at_date,
    _primary_grade,
)
from conviction_engine import (
    CONVICTION_A_CONFIG,
    CONVICTION_B_CONFIG,
    update_convictions as _conv_update,
    select_top_n as _conv_select,
    explain_config_html as _conv_explain_html,
    conviction_bar_html as _conv_bar_html,
    decisions_html as _conv_decisions_html,
    get_status_label as _conv_status_label,
)

_ARENA_SAVE_N = 10

_core_data = fetch_core_data()
_MACRO_TAGS_MAP     = _core_data.get("MACRO_TAGS_MAP", {})
_NARRATIVE_HEAT_MAP = _core_data.get("NARRATIVE_THEMES_HEAT", {})
_STOCK_NARRATIVE    = _core_data.get("STOCK_NARRATIVE_MAP", {})
_SECTOR_MAP         = _core_data.get("SECTOR_MAP", {})
_Z_SEED_TICKERS     = set(_core_data.get("Z_SEED_TICKERS", []))

st.set_page_config(page_title="同类资产竞技场", layout="wide", page_icon="🏆")

if IS_PROD_REMOTE:
    st.info(
        "🌐 **生产环境** — 正在通过 `RADAR_API_URL` 连接 Render 后端。"
        "归档/信念写入正常，仅「清空历史」等破坏性操作被禁用。",
        icon="ℹ️",
    )

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
#  ABCD 宏观剧本元信息（与 Page 3 保持一致）
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
    "Z": {
        "label": "Z级：现金流堡垒",
        "icon": "🏦",
        "color": "#1ABC9C",
        "bg": "#0d2b25",
    },
}

# ─────────────────────────────────────────────────────────────────
#  各赛道评分配置（Relative Scoring Config）
#  每个赛道有独立的权重体系和竞技逻辑
# ─────────────────────────────────────────────────────────────────
ARENA_CONFIG: dict = {
    "A": {
        "score_name": "避风港防御指数",
        "weights": {
            "max_dd_inv": 0.30, "fcf_yield": 0.20,
            "spy_corr_inv": 0.20, "ribbon_quality": 0.30,
        },
        "invert_z": False,
        "factor_labels": {
            "max_dd_inv":     "极限抗跌 (最大回撤倒数)",
            "fcf_yield":      "现金奶牛 (FCF收益率)",
            "spy_corr_inv":   "宏观对冲 (SPY相关性倒数)",
            "ribbon_quality": "带鱼质量 (趋势干净度)",
        },
        "logic": (
            "压舱石的竞技逻辑：防守 + 温和趋势质量四维体系，专抓真实现金流、大盘对冲与均线带鱼形态。<br>"
            "① 极限抗跌（真实252日最大回撤取倒数，回撤越小得分越高，权重 30%）<br>"
            "② 现金奶牛（自由现金流收益率 FCF/MCap，ETF 回退至股息率，权重 20%）<br>"
            "③ 宏观对冲（与SPY日收益率皮尔逊相关系数取倒数，低/负相关得高分，权重 20%）<br>"
            "④ 带鱼质量（MA间距稳定性+持续天数+斜率稳定性+价格贴轨度，趋势干净度，权重 30%）<br>"
            "四维统计指标同时达标方为真正避风港，拒绝一切短期动量噪音。"
        ),
    },
    "B": {
        "score_name": "核心底仓质量指数",
        "weights": {"real_quality": 0.25, "resilience": 0.20, "sharpe_1y": 0.20, "rs_120d": 0.15, "mcap_premium": 0.10, "revenue_growth": 0.10},
        "invert_z": False,
        "factor_labels": {
            "real_quality":   "真·护城河质量 (股息率+盈利稳定性)",
            "resilience":     "抗跌韧性 (近1年最大回撤倒数)",
            "sharpe_1y":      "长效性价比 (近1年夏普比率)",
            "rs_120d":        "中期相对强度 RS₁₂₀ (半年超额收益)",
            "mcap_premium":   "绝对体量 (log10市值壁垒)",
            "revenue_growth": "成长弹性 (Revenue 增速)",
        },
        "logic": (
            "核心底仓质量指数：兼顾防御、效率与趋势，追求极低换手率与极强抗跌性。<br>"
            "① 真·护城河质量（股息率 + 盈利稳定性双因子代理，权重 25%）<br>"
            "② 抗跌韧性（近 1 年最大回撤越小得分越高，权重 20%）<br>"
            "③ 长效性价比（近 1 年夏普比率，长期风险调整收益，权重 20%）<br>"
            "④ 中期相对强度 RS₁₂₀（过去 120 日相对 SPY 超额收益，捕捉趋势切换，权重 15%）<br>"
            "⑤ 绝对体量（log10 市值壁垒，大象起舞加分，权重 10%）<br>"
            "⑥ 成长弹性（Revenue 增速，避免纯防御型占位，权重 10%）<br>"
            "高分者兼具护城河深度、成长宽度与趋势顺风。"
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
            "rs_250d":         "RS₂₅₀ 年度超额收益 (年线级慢动量)",
        },
        "logic": (
            "时代之王 ScorecardC — 慢变量霸权测试（满分 100 分）<br>"
            "① Forward EPS 增速（华尔街一致预期 12 个月 EPS 增速截面 Z-Score，权重 25%）— 盈利是王道。<br>"
            "② log₁₀(市值)（市值越大流动性越好，机构可大仓位介入，权重 15%）<br>"
            "③ RS₁₂₀ 中长线相对强度（过去 120 日相对 SPY 超额收益率，权重 20%）<br>"
            "④ 宏观顺风（标的宏观标签与当前胜率最高剧本完全匹配得满分，错配得 0，权重 20%）<br>"
            "⑤ RS₂₅₀ 年度超额收益（过去 250 日相对 SPY 超额收益率，年线级慢动量，权重 20%）<br>"
            "所有因子均经锚点归一化至 [0, 100] 后加权求和。拒绝短期噪音（5日量能、叙事热度已迁入 D 组）。"
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
    "Z": {
        "score_name": "现金流堡垒指数",
        "weights": {"sharpe_1y": 0.30, "div_yield": 0.20, "div_sustainability": 0.20, "max_dd_inv": 0.15, "price_return": 0.15},
        "invert_z": False,
        "factor_labels": {
            "sharpe_1y":        "总回报效率 (近1年夏普比率)",
            "div_yield":        "现金奶牛 (真实股息率)",
            "div_sustainability": "分红续航力 (盈利稳定性代理)",
            "max_dd_inv":       "本金盾 (最大回撤倒数)",
            "price_return":     "净值趋势 (近1年纯价格回报)",
        },
        "logic": (
            "Z 组「现金流堡垒」使命：筛选能持续提供真实现金流、且本金不被侵蚀的资产。<br>"
            "① 总回报效率（近1年夏普比率，风险调整总收益，权重 30%）— Total Return 才是真正的王<br>"
            "② 现金奶牛（真实股息率，权重 20%）— 降权：锦上添花而非决胜主因<br>"
            "③ 分红续航力（盈利稳定性代理，权重 20%）— 确保分红可持续<br>"
            "④ 本金盾（最大回撤倒数，权重 15%）— 保护本金安全<br>"
            "⑤ 净值趋势（近1年纯价格回报，权重 15%）— 惩罚净值阴跌的财富粉碎机<br>"
            "⚠️ 股息陷阱熔断：股息率>8% 且净值跌>20%，额外扣 20 分。入选门槛：股息率 ≥ 1%。"
        ),
    },
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
#  主存储：universe.db（后端），本地 JSON 仅作离线备用
# ─────────────────────────────────────────────────────────────────
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")
_HORSEMEN_VERDICT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "horsemen_monthly_verdict.json")
_PREV_CLASSIFICATION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "prev_classification.json")


def _load_horsemen_verdict_archive() -> dict:
    """Page 1「四大剧本历史裁决表」持久化副本：按月 SSOT 裁决（与 C 组宏观匹配同源概率表）。"""
    try:
        if os.path.exists(_HORSEMEN_VERDICT_FILE):
            with open(_HORSEMEN_VERDICT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("months", {}) or {}
    except Exception:
        pass
    return {}


def _verdict_cn_from_session_probs(month_key: str) -> str:
    """当本地档案缺失时，用后端缓存的 horsemen_monthly_probs 推导该月最高概率剧本（中文）。
    优先读后端 API，回退到 session_state。
    """
    _regime_data = fetch_current_regime()
    probs = (
        _regime_data.get("horsemen_monthly_probs", {}).get(month_key)
        or st.session_state.get("horsemen_monthly_probs", {}).get(month_key)
    )
    if not probs:
        return ""
    _cn = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
    w = max(probs.items(), key=lambda x: x[1])[0]
    return _cn.get(w, "")


def _resolve_horsemen_verdict_cn(month_key: str, archive: dict) -> str:
    rec = archive.get(month_key)
    if isinstance(rec, dict) and rec.get("verdict_cn"):
        return str(rec["verdict_cn"])
    return _verdict_cn_from_session_probs(month_key)


def _load_prev_classification() -> dict:
    """Load {ticker: [grade_list]} from previous run for hysteresis."""
    try:
        if os.path.exists(_PREV_CLASSIFICATION_FILE):
            with open(_PREV_CLASSIFICATION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_prev_classification(grades_map: dict) -> None:
    """Persist {ticker: [grade_list]} for next run's hysteresis."""
    try:
        os.makedirs(os.path.dirname(_PREV_CLASSIFICATION_FILE), exist_ok=True)
        with open(_PREV_CLASSIFICATION_FILE, "w", encoding="utf-8") as f:
            json.dump(grades_map, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_arena_history() -> dict:
    """从后端加载历史月度 Top 3 记录（主），本地 JSON 作离线降级备用。
    返回格式：{"YYYY-MM": {"A": [...], "B": [...], ...}, ...}
    注意：不含 _conviction_* / _holders_* 等旧格式内嵌键。
    """
    history = _api_fetch_history()
    if history:
        return history
    # 降级：从本地 JSON 读（过滤掉旧格式的内嵌信念键）
    try:
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {k: v for k, v in raw.items() if not k.startswith("_")}
    except Exception:
        pass
    return {}


def _make_record_list(top3_records: list) -> list:
    """将 top3 条目标准化为存储格式。"""
    result = []
    for r in top3_records:
        entry = {"ticker": r["ticker"], "name": r["name"], "score": r.get("score", 0.0)}
        if "conviction" in r:
            entry["conviction"] = r["conviction"]
        if "status" in r:
            entry["status"] = r["status"]
        result.append(entry)
    return result


def _expand_arena_records(base_records: list, df_scored: pd.DataFrame,
                          n: int = _ARENA_SAVE_N) -> list:
    """将 base_records（通常 3 条）用 df_scored 补齐至 n 条，保留原始排序。"""
    if len(base_records) >= n or df_scored.empty:
        return base_records[:n]
    existing = {r["ticker"] for r in base_records}
    expanded = list(base_records)
    for _, row in df_scored.iterrows():
        if len(expanded) >= n:
            break
        tk = row["Ticker"]
        if tk not in existing:
            expanded.append({"ticker": tk, "name": row["名称"],
                             "score": float(row["竞技得分"])})
            existing.add(tk)
    return expanded


def _save_history_to_local_json(batch: dict) -> bool:
    """将 arena history 批量数据合并写入本地 JSON（后端不可用时的兜底）。

    返回是否写入成功（供约束 2：禁止静默失败）。
    """
    try:
        existing: dict = {}
        if os.path.exists(_HISTORY_FILE):
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        for mk, cls_map in batch.items():
            if mk not in existing:
                existing[mk] = {}
            for cls, recs in cls_map.items():
                existing[mk][cls] = recs
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[_save_history_to_local_json] {e}")
        return False


def _record_arena_history(cls: str, records: list, month_key: str = None,
                          _batch_buf: dict | None = None) -> bool:
    """将某月某赛道的排名记录写入后端（实时）或暂存至 _batch_buf（回填批量）。

    _batch_buf 不为 None 时只写入内存字典（永远返回 True），由调用方负责批量推送。
    实时写入（_batch_buf 为 None）时，若后端推送失败则回退写本地 JSON。

    返回值说明（遵循 DATA_CONSISTENCY_PROTOCOL 约束 2）：
    - True：后端推送成功，或批量缓冲已收录
    - False：后端推送失败且本地兜底也失败（双失败）；后端失败但本地兜底成功仍返回 True
    """
    if month_key is None:
        month_key = datetime.now().strftime("%Y-%m")
    rec_list = _make_record_list(records)
    if _batch_buf is not None:
        if month_key not in _batch_buf:
            _batch_buf[month_key] = {}
        _batch_buf[month_key][cls] = rec_list
        return True
    payload = {month_key: {cls: rec_list}}
    ok = _api_push_history_batch(payload)
    if ok:
        return True
    fallback_ok = _save_history_to_local_json(payload)
    if fallback_ok:
        st.toast(f"⚠️ {cls} 档案后端写入失败，已降级本地 JSON", icon="⚠️")
        return True
    st.toast(f"🚨 {cls} 档案写入彻底失败（后端+本地兜底均失败）", icon="🚨")
    return False


def _save_conviction_state(cls: str, state: dict, holders: list,
                           verify: bool = False) -> bool:
    """持久化信念状态到后端 universe.db（唯一存储源）。

    返回值说明（遵循 DATA_CONSISTENCY_PROTOCOL 约束 2 + 5）：
    - True：推送成功（verify=True 时还要求写后校验通过）
    - False：推送失败或写后校验不一致；失败时自动 st.toast 红字告警

    verify=True 时执行"写后立即读一次"严格校验样板（约束 5，仅关键路径开启避免拖慢）：
    - 比对 holders 数量；读回值 < 写入值视为收缩，告警并返回 False
    """
    ok = _api_push_conv(cls, state, holders)
    if not ok:
        st.toast(f"🚨 {cls} 信念状态写入失败（后端 API 不可达或拒绝）", icon="🚨")
        return False
    if verify:
        try:
            state_back, holders_back = _api_fetch_conv(cls)
            if len(holders_back) < len(holders):
                st.toast(
                    f"🚨 {cls} 信念写后校验失败：holders {len(holders)} → {len(holders_back)}",
                    icon="🚨",
                )
                return False
        except Exception as e:
            print(f"[_save_conviction_state verify] {e}")
    return True


def _load_conviction_state(cls: str) -> tuple[dict, list]:
    """从后端 universe.db 读取信念状态。"""
    return _api_fetch_conv(cls)


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _fetch_backfill_prices(tickers: tuple) -> tuple:
    """批量下载约 6 年历史收盘价 + 成交量（含 SPY 基准），供回填使用。"""
    all_dl = list(tickers) + ["SPY"]
    end   = datetime.now()
    start = end - timedelta(days=365 * 6)
    try:
        raw      = yf.download(all_dl, start=start, end=end, progress=False, session=YF_SESSION)
        price_df = raw["Close"].ffill().dropna(how="all")
        vol_df   = raw["Volume"].ffill().fillna(0)
        return price_df, vol_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def _backfill_arena_history(all_assets: dict, months_back: int = 24,
                            monthly_probs: dict = None,
                            meta_data: dict = None,
                            warmup_months: int = 12) -> tuple:
    """
    用历史价格数据回填过去 N 个月各赛道的 Top N。
    评分引擎已后移至后端 /api/v1/arena/backfill_score（ScorecardA + arena_scoring）。

    本函数负责：
      1. 下载历史价格（含 SPY）
      2. 构建 month_specs 列表（含 date_idx + macro_regime + is_warmup）
      3. 一次性调用后端端点
      4. 遍历 response 写入 arena_history + 持久化 conviction_state

    warmup_months: 热身阶段月数（与后端共用，后端不返回热身月的 arena_records）。
    monthly_probs: {"YYYY-MM": {"Soft": f, "Hot": f, "Stag": f, "Rec": f}}
    meta_data: {ticker: {"mcap": float, "div_yield": float, "fcf_yield": float, ...}}
    返回 (saved_month_count, error_msg)
    """
    ticker_names: dict = {}
    all_tickers_set: set = set()
    for ticker, info in all_assets.items():
        if not info.get("has_data", True):
            continue
        all_tickers_set.add(ticker)
        ticker_names[ticker] = info.get("cn_name", ticker)

    all_tickers = tuple(sorted(all_tickers_set))
    if not all_tickers:
        return 0, "无有效标的"

    if meta_data is None:
        meta_data = {}

    price_df, vol_df = _fetch_backfill_prices(all_tickers)
    if price_df.empty:
        return 0, "历史价格数据下载失败，请检查网络或稍后重试。"

    today = datetime.now()
    y, m  = today.year, today.month
    m -= 1
    if m == 0:
        m, y = 12, y - 1

    # 构建总月份列表：warmup + 正式记录，时间正序
    total_months = months_back + warmup_months
    month_ends: list = []
    for _ in range(total_months):
        last_day = calendar.monthrange(y, m)[1]
        target   = pd.Timestamp(y, m, last_day)
        avail    = price_df.index[price_df.index <= target]
        if len(avail) > 0:
            month_ends.append((f"{y:04d}-{m:02d}", avail[-1]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_ends.reverse()  # 时间正序

    warmup_keys: set = {mk for mk, _ in month_ends[:warmup_months]}

    # 构建 month_specs 列表传给后端
    month_specs: list = []
    for month_key, me_date in month_ends:
        loc = price_df.index.get_loc(me_date)
        if loc < 120:
            continue
        _m_probs = (monthly_probs or {}).get(month_key, {})
        bc_regime, _ = _derive_monthly_regimes(_m_probs)
        month_specs.append({
            "month_key":    month_key,
            "date_idx":     int(loc),
            "macro_regime": bc_regime,
            "macro_scores": _m_probs,
            "is_warmup":    month_key in warmup_keys,
        })

    if not month_specs:
        return 0, "无有效月份可回填"

    # 调用后端评分端点（一次 HTTP，服务端循环 61 个月）
    resp = _api_arena_backfill_score(
        price_df=price_df,
        vol_df=vol_df if not vol_df.empty else None,
        meta_data=meta_data,
        month_specs=month_specs,
        z_seed_tickers=list(_Z_SEED_TICKERS),
        arena_save_n=_ARENA_SAVE_N,
    )
    if not resp.get("success"):
        err = resp.get("error", "未知错误")
        return 0, f"后端回填端点失败：{err}"

    arena_records_resp = resp.get("arena_records", {})
    conv_state_a  = resp.get("conv_state_a", {})
    conv_holders_a = resp.get("conv_holders_a", [])
    conv_state_b  = resp.get("conv_state_b", {})
    conv_holders_b = resp.get("conv_holders_b", [])

    # 遍历响应，写入 arena_history（每 6 个月 checkpoint 批量推送）
    _bf_history_buf: dict = {}
    saved = 0
    for month_key, cls_map in sorted(arena_records_resp.items()):
        for cls, records in cls_map.items():
            _record_arena_history(cls, records, month_key=month_key,
                                  _batch_buf=_bf_history_buf)
        saved += 1
        if saved % 6 == 0:
            if not _api_push_history_batch(_bf_history_buf):
                _save_history_to_local_json(_bf_history_buf)
            _bf_history_buf.clear()

    if _bf_history_buf:
        if not _api_push_history_batch(_bf_history_buf):
            _save_history_to_local_json(_bf_history_buf)

    # 持久化信念状态
    _save_conviction_state("A", conv_state_a, conv_holders_a)
    _save_conviction_state("B", conv_state_b, conv_holders_b)
    return saved, ""


# ─────────────────────────────────────────────────────────────────
#  相对评分引擎（Relative Scoring Engine）
# ─────────────────────────────────────────────────────────────────
FACTOR_ANCHORS: dict = {
    "max_dd_inv":    (-0.25, -0.03),
    "div_yield":     (0.0, 5.0),
    "div_yield_z":        (0.0, 12.0),       # Z 组股息率上限扩至 12%（覆盖 Strategy 优先股 10%、JEPQ ~9%、STRC 浮动 ~11%）
    "sharpe_1y_z":        (-0.5, 2.0),       # Z 组夏普比率：-0.5 极差 → 2.0 优秀
    "price_return_1y_z":  (-0.35, 0.15),     # Z 组净值趋势：-35% 财富粉碎机 → +15% 稳健增值
    "fcf_yield":     (0.0, 10.0),
    "spy_corr_inv":  (-0.8, 0.3),
    "vol_inv":       (0.40, 0.08),
    "sharpe_1y":     (-0.5, 2.5),
    "log_mcap":      (9.0, 12.5),
    "eps_stability": (0.5, 10.0),
    "eps_growth":    (-20.0, 40.0),
    "rs_120d":       (-15.0, 30.0),
    "rs_250d":       (-20.0, 40.0),
    "vol_z":         (-1.0, 4.0),
    "rs_20d":        (-10.0, 25.0),
    "ma60_breakout": (0.0, 100.0),
    "revenue_growth": (-5.0, 25.0),    # B 组收入增速 %
    "ribbon_quality": (0.0, 0.80),     # 带鱼质量 0=完全无趋势, 0.80=教科书级稳定带鱼
}


def _anchor_norm(series: pd.Series, lo: float, hi: float) -> pd.Series:
    """Anchor-based normalization using fixed historical percentile bounds.
    Values outside [lo, hi] are clipped to [0, 100]."""
    if abs(hi - lo) < 1e-9:
        return pd.Series(50.0, index=series.index)
    return ((series - lo) / (hi - lo) * 100.0).clip(0, 100)


def _minmax_norm(series: pd.Series) -> pd.Series:
    """Min-max normalization to [0, 100]. Deprecated: use _anchor_norm instead."""
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

    z_norm     = _minmax_norm(result["Z-Score"].astype(float))  # generic fallback still uses minmax
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



def compute_scorecard_c(df: pd.DataFrame, macro_regime: str) -> pd.DataFrame:
    """
    ScorecardC — C 组「慢变量霸权」评分体系 (满分 100 分)

    Score_C = (25 × Z_ForwardEPS) + (15 × log10(MCap))
            + (20 × RS_120d) + (20 × Fit_Macro) + (20 × RS_250d)

    各项均经锚点归一化至 [0, 100] 后加权求和。
    """
    if df.empty:
        return df

    result = df.copy()

    # ── 因子 1: Forward EPS Growth Z-Score (25%, was 50%)
    eps_raw = result.get("EPS增速", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _anchor_norm(eps_raw, *FACTOR_ANCHORS["eps_growth"])

    # ── 因子 2: log10(MarketCap) (15%)
    mcap_log = result.get("市值对数", pd.Series(9.0, index=result.index)).astype(float).fillna(9.0)
    f2_norm = _anchor_norm(mcap_log, *FACTOR_ANCHORS["log_mcap"])

    # ── 因子 3: RS_120d 中长线相对强度 vs SPY (20%, was 15%)
    rs120_raw = result.get("RS120d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _anchor_norm(rs120_raw, *FACTOR_ANCHORS["rs_120d"])

    # ── 因子 4: Macro Alignment — 标的宏观标签与当前胜率剧本匹配 (20%)
    aligned_tickers = set(_MACRO_TAGS_MAP.get(macro_regime, []))
    f4_norm = result["Ticker"].apply(lambda t: 100.0 if t in aligned_tickers else 0.0)

    # ── 因子 5: RS_250d 年度超额收益 vs SPY (20%, new)
    rs250_raw = result.get("RS250d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f5_norm = _anchor_norm(rs250_raw, *FACTOR_ANCHORS["rs_250d"])

    result["因子1_分"] = (0.25 * f1_norm).round(1)
    result["因子2_分"] = (0.15 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.20 * f4_norm).round(1)
    result["因子5_分"] = (0.20 * f5_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"]
        + result["因子4_分"] + result["因子5_分"]
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

    # ── 因子 1: 5日量能 Z-Score → 锚点归一化 (45%)
    vol_z_raw = result.get("Vol_Z", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _anchor_norm(vol_z_raw, *FACTOR_ANCHORS["vol_z"])

    # ── 因子 2: 20日相对 SPY 超额收益率 → 锚点归一化 (35%)
    rs_raw = result.get("RS_20d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _anchor_norm(rs_raw, *FACTOR_ANCHORS["rs_20d"])

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


# ── B 组宏观适配权重表 ──
# 四档权重: (Quality, Resilience, Sharpe, RS120d, MCap, Revenue, MacroAlign)
# 进攻期(Soft/Hot) → RS120d 10%；防御期(Stag/Rec) → RS120d 归零，Quality/Resilience 加码
B_REGIME_WEIGHTS: dict = {
    "Soft": (0.20, 0.20, 0.20, 0.10, 0.10, 0.10, 0.10),
    "Hot":  (0.20, 0.15, 0.20, 0.10, 0.10, 0.15, 0.10),
    "Stag": (0.25, 0.25, 0.20, 0.00, 0.10, 0.10, 0.10),
    "Rec":  (0.30, 0.25, 0.20, 0.00, 0.10, 0.05, 0.10),
}


def compute_scorecard_b(df: pd.DataFrame, macro_regime: str = "Soft") -> pd.DataFrame:
    """
    ScorecardB -- B 组「核心底仓质量指数」宏观适配评分体系 (满分 100 分)

    权重随宏观剧本动态调整（B_REGIME_WEIGHTS）：
      进攻期 (Soft/Hot): 保留 RS120d 10% — 动量辅助选优
      防御期 (Stag/Rec): RS120d 归零 — 纯质量/韧性筛选

    7 因子:
      F1 RealQuality    = (DivYield_norm + EPS_Stability_norm) / 2
      F2 Resilience     = inverse MaxDrawdown
      F3 Sharpe1Y       = annualized Sharpe ratio
      F4 RS120d         = 120-day relative strength vs SPY
      F5 MCapPremium    = log10(MCap) normalized
      F6 RevenueGrowth  = TTM Revenue growth rate %
      F7 MacroAlignment = 标的是否匹配当前宏观剧本 (binary, 同 C 组同源)
    """
    if df.empty:
        return df

    result = df.copy()

    div_raw = result.get("股息率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    eps_stab_raw = result.get("EPS稳定性", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    div_norm = _anchor_norm(div_raw, *FACTOR_ANCHORS["div_yield"])
    eps_stab_norm = _anchor_norm(eps_stab_raw, *FACTOR_ANCHORS["eps_stability"])
    f1_norm = (div_norm + eps_stab_norm) / 2.0

    dd_raw = result.get("最大回撤_raw", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f2_norm = _anchor_norm(-dd_raw.abs(), *FACTOR_ANCHORS["max_dd_inv"])

    sharpe_raw = result.get("夏普比率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _anchor_norm(sharpe_raw, *FACTOR_ANCHORS["sharpe_1y"])

    rs120_raw = result.get("RS120d", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f4_norm = _anchor_norm(rs120_raw, *FACTOR_ANCHORS["rs_120d"])

    mcap_raw = result.get("市值对数", pd.Series(9.0, index=result.index)).astype(float).fillna(9.0)
    f5_norm = _anchor_norm(mcap_raw, *FACTOR_ANCHORS["log_mcap"])

    rev_raw = result.get("Revenue增速", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f6_norm = _anchor_norm(rev_raw, *FACTOR_ANCHORS["revenue_growth"])

    aligned_tickers = set(_MACRO_TAGS_MAP.get(macro_regime, []))
    f7_norm = result["Ticker"].apply(lambda t: 100.0 if t in aligned_tickers else 0.0)

    w = B_REGIME_WEIGHTS.get(macro_regime, B_REGIME_WEIGHTS["Soft"])
    w_q, w_r, w_s, w_rs, w_m, w_rev, w_macro = w

    result["因子1_分"] = (w_q * f1_norm).round(1)
    result["因子2_分"] = (w_r * f2_norm).round(1)
    result["因子3_分"] = (w_s * f3_norm).round(1)
    result["因子4_分"] = (w_rs * f4_norm).round(1)
    result["因子5_分"] = (w_m * f5_norm).round(1)
    result["因子6_分"] = (w_rev * f6_norm).round(1)
    result["因子7_分"] = (w_macro * f7_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"]
        + result["因子4_分"] + result["因子5_分"] + result["因子6_分"]
        + result["因子7_分"]
    ).round(1)

    result = result.sort_values("竞技得分", ascending=False).reset_index(drop=True)
    result["排名"] = range(1, len(result) + 1)
    return result


def compute_scorecard_z(df: pd.DataFrame) -> pd.DataFrame:
    """
    ScorecardZ -- Z 组「现金流堡垒指数」评分体系 (满分 100 分)

    Score_Z = (30 x Sharpe_1Y) + (20 x DivYield)
            + (20 x DivSustainability) + (15 x InvMaxDD) + (15 x PriceReturn)

    股息陷阱熔断：股息率>8% 且近1年纯价格回报<-20%，额外扣 20 分。
    入选门槛：股息率 >= 1.0%，零股息资产不参赛。
    """
    if df.empty:
        return df

    result = df.copy()

    # 硬过滤：股息率 >= 1%
    div_raw = result.get("股息率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    result = result[div_raw >= 1.0].copy()
    if result.empty:
        return result

    # F1: Sharpe 1Y — 风险调整总回报 (30%)
    sharpe_raw = result.get("夏普比率", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _anchor_norm(sharpe_raw, *FACTOR_ANCHORS["sharpe_1y_z"])

    # F2: Dividend Yield — 现金奶牛 (20%)
    div_raw = result["股息率"].astype(float).fillna(0.0)
    f2_norm = _anchor_norm(div_raw, *FACTOR_ANCHORS["div_yield_z"])

    # F3: Dividend Sustainability — 分红续航力 (20%)
    eps_stab_raw = result.get("EPS稳定性", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _anchor_norm(eps_stab_raw, *FACTOR_ANCHORS["eps_stability"])

    # F4: Max Drawdown Inverse — 本金盾 (15%)
    dd_raw = result.get("最大回撤_raw", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f4_norm = _anchor_norm(-dd_raw.abs(), *FACTOR_ANCHORS["max_dd_inv"])

    # F5: Price Return 1Y — 净值趋势惩罚 (15%)
    price_ret_raw = result.get("净值趋势_1Y", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f5_norm = _anchor_norm(price_ret_raw, *FACTOR_ANCHORS["price_return_1y_z"])

    result["因子1_分"] = (0.30 * f1_norm).round(1)
    result["因子2_分"] = (0.20 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.15 * f4_norm).round(1)
    result["因子5_分"] = (0.15 * f5_norm).round(1)

    result["竞技得分"] = (
        result["因子1_分"] + result["因子2_分"] + result["因子3_分"]
        + result["因子4_分"] + result["因子5_分"]
    ).round(1)

    # 股息陷阱熔断：股息率>8% 且净值跌>20%，触发扣分预警
    div_col = result["股息率"].astype(float).fillna(0.0)
    ret_col = result.get("净值趋势_1Y", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    trap_mask = (div_col > 8.0) & (ret_col < -0.20)
    result.loc[trap_mask, "竞技得分"] -= 20
    result["股息陷阱"] = trap_mask
    result["竞技得分"] = result["竞技得分"].clip(0, 100)

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
_FACTOR_PALETTE = ["", "#3498DB", "#9B59B6", "#F39C12", "#1ABC9C", "#E74C3C"]


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
def _render_leaderboard(df_scored: pd.DataFrame, cls: str,
                        conviction_map: dict | None = None) -> None:
    """渲染完整赛道排行榜 + 因子分解横向条形图（内联至列表）。

    conviction_map: {ticker: {"conviction": float, "status": str}}
        仅 A/B 组传入，用于在最大回撤左侧展示信念值与守擂状态。
    """
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
            "<div style='width:90px; text-align:right;'>信念值</div>"
            "<div style='width:82px; text-align:right;'>最大回撤</div>"
            "<div style='width:82px; text-align:right;'>SPY相关</div>"
            "<div style='width:82px; text-align:right;'>年化波动</div>"
            "</div>"
        )
    elif cls == "Z":
        header_html = (
            "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
            " color:#888; font-size:11px; padding:6px 0; font-weight:bold;'>"
            "<div style='width:46px; text-align:center;'>排名</div>"
            "<div style='width:150px;'>资产</div>"
            "<div style='flex:1; padding:0 20px;'>因子贡献分解 (堆叠)</div>"
            "<div style='width:82px; text-align:right;'>股息率</div>"
            "<div style='width:82px; text-align:right;'>Sharpe</div>"
            "<div style='width:100px; text-align:right;'>净值趋势</div>"
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

    factor_cols = [f"因子{i}_分" for i in range(1, n_factors + 1)]
    _factor_sums = df_scored[factor_cols].sum(axis=1) if not df_scored.empty else pd.Series([100.0])
    max_score = max(float(_factor_sums.max()), 1.0)
    rows_html = ""
    for _, row in df_scored.iterrows():
        rank = int(row["排名"])
        score = row["竞技得分"]
        bar_pct = score / max_score * 100

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
            is_fused = row.get("熔断状态", "").startswith("🌋")
            dd_label = f"🌋 {dd_pct:.1f}%" if is_fused else f"{dd_pct:.1f}%"
            dd_color = "#2ECC71" if abs(dd_pct) < 10 else ("#F1C40F" if abs(dd_pct) < 20 else "#E74C3C")
            corr_color = "#2ECC71" if corr_v < 0.3 else ("#F1C40F" if corr_v < 0.6 else "#E74C3C")
            vol_color = "#2ECC71" if vol_pct < 15 else ("#F1C40F" if vol_pct < 25 else "#E74C3C")
            # ── 信念值单元格 ──────────────────────────────────────────
            _conv_data = (conviction_map or {}).get(row["Ticker"], {})
            _conv_val  = _conv_data.get("conviction", 0.0)
            _conv_st   = _conv_data.get("status", "")
            _CONV_ICONS = {
                "defending":  ("🛡️", "#2ECC71"),
                "new_entry":  ("🆕", "#3498DB"),
                "challenged": ("⚔️", "#F39C12"),
                "cold_start": ("🔰", "#9B59B6"),
            }
            _conv_icon, _conv_clr = _CONV_ICONS.get(_conv_st, ("", "#888"))
            if _conv_val > 0:
                _conv_cell = (
                    f"<div style='width:90px; text-align:right; font-weight:bold;"
                    f" color:{_conv_clr};'>{_conv_icon} {_conv_val:.0f}</div>"
                )
            else:
                _conv_cell = "<div style='width:90px; text-align:right; color:#555;'>—</div>"
            kpi_cells = (
                _conv_cell
                + f"<div style='width:82px; text-align:right; font-weight:bold; color:{dd_color};'"
                  f" title='3Y最大回撤 (ScorecardA F1同源)'>{dd_label}</div>"
                + f"<div style='width:82px; text-align:right; font-weight:bold; color:{corr_color};'>{corr_v:.2f}</div>"
                + f"<div style='width:82px; text-align:right; font-weight:bold; color:{vol_color};'>{vol_pct:.1f}%</div>"
            )
        elif cls == "Z":
            dy_z = row.get("股息率", 0.0)
            sharpe_z = row.get("夏普比率", 0.0)
            price_ret_z = row.get("净值趋势_1Y", 0.0) * 100
            is_trap = bool(row.get("股息陷阱", False))
            dy_color = "#2ECC71" if dy_z >= 3.0 else ("#F1C40F" if dy_z >= 1.0 else "#888")
            if is_trap:
                dy_label = f"🌋 {dy_z:.2f}%"
            else:
                dy_label = f"{dy_z:.2f}%"
            sharpe_color = "#2ECC71" if sharpe_z >= 1.0 else ("#F1C40F" if sharpe_z >= 0.3 else "#E74C3C")
            ret_color = "#2ECC71" if price_ret_z >= 0 else ("#F1C40F" if price_ret_z >= -10 else "#E74C3C")
            kpi_cells = (
                f"<div style='width:82px; text-align:right; font-weight:bold; color:{dy_color};'>{dy_label}</div>"
                f"<div style='width:82px; text-align:right; font-weight:bold; color:{sharpe_color};'>{sharpe_z:.2f}</div>"
                f"<div style='width:100px; text-align:right; font-weight:bold; color:{ret_color};'>{price_ret_z:+.1f}%</div>"
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

        # A 组：因子分内嵌在堆叠条右侧，不再单独渲染得分栏
        if cls == "A":
            bar_area_html = (
                "<div style='flex:1; padding:0 20px; display:flex; align-items:center; gap:8px;'>"
                "<div style='flex:1; display:flex; height:10px; background:#1e1e1e;"
                " border-radius:4px; overflow:hidden;'>"
                f"{factor_bars_html}"
                "</div>"
                f"<span style='font-size:13px; color:{'#E74C3C' if score < 0 else '#555'}; min-width:24px;"
                f" text-align:right;'>{score:.0f}</span>"
                "</div>"
            )
            score_col_html = ""
        else:
            bar_area_html = (
                "<div style='flex:1; padding:0 20px;'>"
                "<div style='display:flex; width:100%; height:10px; background:#1e1e1e;"
                " border-radius:4px; overflow:hidden;'>"
                f"{factor_bars_html}"
                "</div>"
                "</div>"
            )
            score_col_html = (
                "<div style='width:160px; padding-left:12px;'>"
                "<div style='display:flex; align-items:center; gap:8px;'>"
                "<div style='flex:1; background:#1e1e1e; border-radius:4px; height:8px;'>"
                f"<div style='width:{bar_pct:.0f}%; background:{meta['color']};"
                " border-radius:4px; height:8px;'></div>"
                "</div>"
                f"<span style='font-size:13px; font-weight:bold; color:{meta['color']};"
                f" min-width:32px;'>{score:.0f}</span>"
                "</div></div>"
            )
        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='width:150px; display:flex; align-items:baseline; gap:8px;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:11px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{row['名称']}</span>"
            "</div>"
            f"{bar_area_html}"
            f"{kpi_cells}"
            f"{score_col_html}"
            "</div>"
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
_B_FACTOR_COLORS = ["#F39C12", "#3498DB", "#2ECC71", "#E67E22", "#9B59B6", "#E74C3C", "#1ABC9C"]


def _render_podium_b(top3: pd.DataFrame) -> None:
    """B 组信念守擂制专属 Top 3 颁奖台（展示信念值 + 因子指标）。"""
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
        conv  = row.get("信念值", 0.0)
        status = row.get("守擂状态", "")

        dy_color = "#2ECC71" if dy > 2.0 else ("#F1C40F" if dy > 0.5 else "#888")
        dd_color = "#2ECC71" if abs(dd) < 0.15 else ("#F39C12" if abs(dd) < 0.25 else "#E74C3C")
        sp_color = "#2ECC71" if sp > 1.0 else ("#F1C40F" if sp > 0 else "#E74C3C")

        rev_g = row.get("Revenue增速", 0.0)
        rev_color = "#2ECC71" if rev_g >= 10 else ("#F1C40F" if rev_g >= 0 else "#E74C3C")

        status_lbl, status_clr = _conv_status_label(status)
        conv_pct = min(conv / 100 * 100, 100)

        rs120 = row.get("RS120d", 0.0)
        rs_color = "#2ECC71" if rs120 > 5 else ("#F1C40F" if rs120 > 0 else "#E74C3C")

        factor_pills_html = ""
        for fi in range(1, 8):
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
                            letter-spacing:1px; margin-bottom:6px;'>{title}</div>
                <div style='font-size:26px; font-weight:bold; color:#eee;'>{row['Ticker']}</div>
                <div style='font-size:13px; color:#aaa; margin-bottom:6px;'>{row['名称']}</div>
                <div style='display:inline-block; background:{status_clr}22;
                     border:1px solid {status_clr}55; border-radius:12px;
                     padding:2px 10px; font-size:13px; color:{status_clr};
                     font-weight:bold; margin-bottom:8px;'>{status_lbl}</div>
                <div style='font-size:34px; font-weight:bold; color:{medal_color}; margin-bottom:2px;'>
                    {conv:.0f}
                </div>
                <div style='font-size:13px; color:#888; margin-bottom:4px;'>信念值 / 100</div>
                <div style='background:#1e1e1e; border-radius:4px; height:6px; margin:0 20px 8px;'>
                    <div style='width:{conv_pct:.0f}%; background:{status_clr};
                         border-radius:4px; height:6px;'></div>
                </div>
                <div style='font-size:13px; color:#666; margin-bottom:10px;'>因子分 {score:.0f}/100</div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; text-align:left; line-height:2;'>
                    <span style='color:#888;'>股息率</span>
                    <span style='color:{dy_color}; font-weight:bold; float:right;'>{dy:.2f}%</span><br>
                    <span style='color:#888;'>最大回撤(1Y)</span>
                    <span style='color:{dd_color}; font-weight:bold; float:right;'>{dd*100:.1f}%</span><br>
                    <span style='color:#888;'>夏普比率(1Y)</span>
                    <span style='color:{sp_color}; font-weight:bold; float:right;'>{sp:.2f}</span><br>
                    <span style='color:#888;'>RS₁₂₀ vs SPY</span>
                    <span style='color:{rs_color}; font-weight:bold; float:right;'>{rs120:+.1f}%</span><br>
                    <span style='color:#888;'>Revenue 增速</span>
                    <span style='color:{rev_color}; font-weight:bold; float:right;'>{rev_g:+.1f}%</span>
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; color:#777; text-align:left; line-height:1.8; display:flex; flex-wrap:wrap; gap:4px;'>
                    {factor_pills_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


_A_FACTOR_COLORS = ["#2ECC71", "#3498DB", "#9B59B6", "#F39C12", "#E74C3C"]


def _render_podium_a(top3: pd.DataFrame) -> None:
    """A 组信念守擂制专属 Top 3 颁奖台（展示信念值 + 避风港因子指标）。"""
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

        row      = top3.iloc[i]
        score    = row["竞技得分"]
        fcf_v    = row.get("FCF收益率", 0.0)
        dd       = row.get("最大回撤_raw", 0.0)
        corr_v   = row.get("SPY相关性", 0.5)
        ribbon_v = row.get("带鱼质量", 0.0)
        conv     = row.get("信念值", 0.0)
        status   = row.get("守擂状态", "")

        fcf_color    = "#2ECC71" if fcf_v > 5.0 else ("#F1C40F" if fcf_v > 2.0 else "#888")
        dd_color     = "#2ECC71" if abs(dd) < 0.10 else ("#F39C12" if abs(dd) < 0.20 else "#E74C3C")
        corr_color   = "#2ECC71" if corr_v < 0.3 else ("#F1C40F" if corr_v < 0.6 else "#E74C3C")
        ribbon_color = "#2ECC71" if ribbon_v >= 0.55 else ("#F1C40F" if ribbon_v >= 0.30 else "#888")

        status_lbl, status_clr = _conv_status_label(status)
        conv_pct = min(conv / 100 * 100, 100)

        factor_pills_html = ""
        for fi in range(1, 5):
            fc = _A_FACTOR_COLORS[fi - 1]
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
                            letter-spacing:1px; margin-bottom:6px;'>{title}</div>
                <div style='font-size:26px; font-weight:bold; color:#eee;'>{row['Ticker']}</div>
                <div style='font-size:13px; color:#aaa; margin-bottom:6px;'>{row['名称']}</div>
                <div style='display:inline-block; background:{status_clr}22;
                     border:1px solid {status_clr}55; border-radius:12px;
                     padding:2px 10px; font-size:13px; color:{status_clr};
                     font-weight:bold; margin-bottom:8px;'>{status_lbl}</div>
                <div style='font-size:34px; font-weight:bold; color:{medal_color}; margin-bottom:2px;'>
                    {conv:.0f}
                </div>
                <div style='font-size:13px; color:#888; margin-bottom:4px;'>信念值 / 100</div>
                <div style='background:#1e1e1e; border-radius:4px; height:6px; margin:0 20px 8px;'>
                    <div style='width:{conv_pct:.0f}%; background:{status_clr};
                         border-radius:4px; height:6px;'></div>
                </div>
                <div style='font-size:13px; color:#666; margin-bottom:10px;'>因子分 {score:.0f}/100</div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; text-align:left; line-height:2;'>
                    <span style='color:#888;'>最大回撤(1Y)</span>
                    <span style='color:{dd_color}; font-weight:bold; float:right;'>{dd*100:.1f}%</span><br>
                    <span style='color:#888;'>FCF收益率</span>
                    <span style='color:{fcf_color}; font-weight:bold; float:right;'>{fcf_v:.2f}%</span><br>
                    <span style='color:#888;'>SPY相关性</span>
                    <span style='color:{corr_color}; font-weight:bold; float:right;'>{corr_v:.2f}</span><br>
                    <span style='color:#888;'>带鱼质量</span>
                    <span style='color:{ribbon_color}; font-weight:bold; float:right;'>{ribbon_v:.2f}</span>
                </div>
                <hr style='border-color:#333; margin:8px 0;'>
                <div style='font-size:13px; color:#777; text-align:left; line-height:1.8; display:flex; flex-wrap:wrap; gap:4px;'>
                    {factor_pills_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


def _render_leaderboard_b(df_scored: pd.DataFrame,
                          conviction_map: dict | None = None) -> None:
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
        "中期相对强度 RS₁₂₀",
        "绝对体量 MCap",
        "成长弹性 Revenue",
        "宏观适配",
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
        "<div style='width:90px; text-align:right;'>信念值</div>"
        "<div style='width:82px; text-align:right;'>股息率</div>"
        "<div style='width:100px; text-align:right;'>最大回撤</div>"
        "<div style='width:80px; text-align:right;'>夏普比率</div>"
        "<div style='width:80px; text-align:right;'>RS₁₂₀</div>"
        "<div style='width:80px; text-align:right;'>Rev增速</div>"
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
        rs120  = row.get("RS120d", 0.0)
        rv     = row.get("Revenue增速", 0.0)

        dy_color = "#2ECC71" if dy > 2.0 else ("#F1C40F" if dy > 0.5 else "#888")
        dd_color = "#2ECC71" if abs(dd) < 0.15 else ("#F39C12" if abs(dd) < 0.25 else "#E74C3C")
        sp_color = "#2ECC71" if sp > 1.0 else ("#F1C40F" if sp > 0 else "#E74C3C")
        rs_color = "#2ECC71" if rs120 > 5 else ("#F1C40F" if rs120 > 0 else "#E74C3C")
        rv_color = "#2ECC71" if rv >= 10 else ("#F1C40F" if rv >= 0 else "#E74C3C")

        if rank == 1:
            rank_html = "<span style='font-size:16px;'>🥇</span>"
        elif rank == 2:
            rank_html = "<span style='font-size:16px;'>🥈</span>"
        elif rank == 3:
            rank_html = "<span style='font-size:16px;'>🥉</span>"
        else:
            rank_html = f"<span style='color:#555; font-size:13px;'>#{rank}</span>"

        factor_bars_html = ""
        for fi in range(1, 8):
            fi_val = row.get(f"因子{fi}_分", 0.0)
            fi_pct = fi_val / max(max_score, 1.0) * 100
            fc = _B_FACTOR_COLORS[fi - 1]
            fl = b_factor_labels[fi - 1]
            factor_bars_html += (
                f"<div style='width:{fi_pct:.0f}%; background:{fc};' "
                f"title='{fl}: {fi_val:.1f}'></div>"
            )

        # ── 信念值单元格 ──────────────────────────────────────────────
        _conv_data_b = (conviction_map or {}).get(row["Ticker"], {})
        _conv_val_b  = _conv_data_b.get("conviction", 0.0)
        _conv_st_b   = _conv_data_b.get("status", "")
        _CONV_ICONS_B = {
            "defending":  ("🛡️", "#2ECC71"),
            "new_entry":  ("🆕", "#3498DB"),
            "challenged": ("⚔️", "#F39C12"),
            "cold_start": ("🔰", "#9B59B6"),
        }
        _conv_icon_b, _conv_clr_b = _CONV_ICONS_B.get(_conv_st_b, ("", "#888"))
        if _conv_val_b > 0:
            _conv_cell_b = (
                f"<div style='width:90px; text-align:right; font-weight:bold;"
                f" color:{_conv_clr_b};'>{_conv_icon_b} {_conv_val_b:.0f}</div>"
            )
        else:
            _conv_cell_b = "<div style='width:90px; text-align:right; color:#555;'>—</div>"

        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='width:150px; display:flex; align-items:baseline; gap:8px;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:13px; color:#888; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{row['名称']}</span>"
            "</div>"
            "<div style='flex:1; padding:0 20px; display:flex; align-items:center; gap:8px;'>"
            "<div style='flex:1; display:flex; height:10px; background:#1e1e1e;"
            " border-radius:4px; overflow:hidden;'>"
            f"{factor_bars_html}"
            "</div>"
            f"<span style='font-size:13px; color:#555; min-width:24px; text-align:right;'>{score:.0f}</span>"
            "</div>"
            f"{_conv_cell_b}"
            f"<div style='width:82px; text-align:right; font-weight:bold; color:{dy_color};'>{dy:.2f}%</div>"
            f"<div style='width:100px; text-align:right; font-weight:bold; color:{dd_color};'>{dd*100:.1f}%</div>"
            f"<div style='width:80px; text-align:right; font-weight:bold; color:{sp_color};'>{sp:.2f}</div>"
            f"<div style='width:80px; text-align:right; font-weight:bold; color:{rs_color};'>{rs120:+.1f}%</div>"
            f"<div style='width:80px; text-align:right; font-weight:bold; color:{rv_color};'>{rv:+.1f}%</div>"
            "</div>"
        )

    st.markdown(
        f"<div style='width:100%; font-size:13px;'>{header_html}{rows_html}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
#  白盒加工台：分类迟滞 & 信念守擂
# ─────────────────────────────────────────────────────────────────

def _render_hysteresis_whitebox(all_assets_dict: dict) -> None:
    """第一层白盒：A 组分类迟滞全量审计表 + 可调迟滞阈值 sliders。"""
    with st.expander("🔬 第一层白盒 — A 组分类迟滞审计表", expanded=False):
        # ── 阈值调节 sliders ──────────────────────────────────────
        st.markdown(
            "<div style='font-size:14px; color:#F39C12; font-weight:bold;"
            " margin-bottom:8px;'>⚙️ A 组迟滞阈值调节（修改后即时生效）</div>",
            unsafe_allow_html=True,
        )
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.slider("股息进入线 (%)", 0.0, 3.0, step=0.1,
                      key="hyst_a_income_enter",
                      help="股息率需≥此值才算满足收益来源（进入）")
            st.slider("股息退出线 (%)", 0.0, 2.0, step=0.1,
                      key="hyst_a_income_exit",
                      help="股息率<此值且慢趋势弱才触发退出信号")
        with sc2:
            st.slider("回撤进入线 (%)", 5.0, 25.0, step=0.5,
                      key="hyst_a_dd_enter",
                      help="1年最大回撤需<此值方可进入A组")
            st.slider("回撤退出线 (%)", 10.0, 35.0, step=0.5,
                      key="hyst_a_dd_exit",
                      help="1年最大回撤>此值触发退出")
        with sc3:
            st.slider("相关性进入线", 0.30, 0.80, step=0.01,
                      key="hyst_a_corr_enter",
                      help="SPY相关性需<此值方可进入A组")
            st.slider("相关性退出线", 0.40, 0.90, step=0.01,
                      key="hyst_a_corr_exit",
                      help="SPY相关性>此值触发退出")

        st.markdown("<hr style='border-color:#333; margin:10px 0;'>", unsafe_allow_html=True)

        # ── 渲染全量审计表 ─────────────────────────────────────────
        rows_html = ""
        tickers_sorted = sorted(
            all_assets_dict.keys(),
            key=lambda t: (
                0 if all_assets_dict[t]["criteria"].get("A", {}).get("pass") else 1,
                -all_assets_dict[t].get("div_yield", 0.0),
            ),
        )
        th_ie = st.session_state.get("hyst_a_income_enter", 1.0)
        th_ix = st.session_state.get("hyst_a_income_exit",  0.5)
        th_de = st.session_state.get("hyst_a_dd_enter",    15.0)
        th_dx = st.session_state.get("hyst_a_dd_exit",     20.0)
        th_ce = st.session_state.get("hyst_a_corr_enter",  0.65)
        th_cx = st.session_state.get("hyst_a_corr_exit",   0.75)

        header_html = (
            "<div style='display:flex; gap:6px; padding:4px 0; border-bottom:2px solid #333;"
            " font-size:13px; color:#888; font-weight:bold;'>"
            "<span style='width:70px;'>Ticker</span>"
            "<span style='width:110px;'>名称</span>"
            "<span style='width:60px; text-align:center;'>上期A</span>"
            "<span style='width:80px; text-align:right;'>股息%</span>"
            "<span style='width:80px; text-align:right;'>回撤%</span>"
            "<span style='width:80px; text-align:right;'>SPY相关</span>"
            "<span style='width:90px; text-align:center;'>收益达标</span>"
            "<span style='width:90px; text-align:center;'>回撤达标</span>"
            "<span style='width:90px; text-align:center;'>相关达标</span>"
            "<span style='width:80px; text-align:center;'>最终结果</span>"
            "<span style='width:100px; text-align:center;'>迟滞效果</span>"
            "</div>"
        )
        for tk in tickers_sorted:
            info = all_assets_dict[tk]
            a_crit = info.get("criteria", {}).get("A", {})
            if not a_crit or "pass" not in a_crit:
                continue
            was_a      = a_crit.get("_was_a", False)
            a_pass     = a_crit.get("pass", False)
            div_yield  = float(a_crit.get("_div_yield", info.get("div_yield", 0.0)))
            max_dd     = float(a_crit.get("_max_dd", info.get("max_dd", 0.0)))
            spy_corr   = float(a_crit.get("_spy_corr", info.get("spy_corr", 0.0)))
            slow_bull  = info.get("slow_bullish", False)

            # Recompute checks using current threshold values
            ie = div_yield >= th_ie or slow_bull
            ix = div_yield < th_ix and not slow_bull
            de = max_dd < th_de
            dx = max_dd > th_dx
            ce = spy_corr < th_ce
            cx = spy_corr > th_cx

            # Hysteresis effect: incumbent kept in who would have failed entry
            if was_a and a_pass and (not ie or not de or not ce):
                hyst_tag = "<span style='color:#F39C12; font-size:13px;'>🔒 迟滞留任</span>"
            elif not was_a and not a_pass and (not ix and not dx and not cx):
                hyst_tag = "<span style='color:#888; font-size:13px;'>— 正常拒签</span>"
            else:
                hyst_tag = "<span style='color:#555; font-size:13px;'>—</span>"

            row_bg = "#1e2a1e" if a_pass else "#1a1a1a"
            pass_clr = "#2ECC71" if a_pass else "#E74C3C"
            was_a_icon = "✅" if was_a else "—"

            def _chk(ok: bool) -> str:
                return f"<span style='color:{'#2ECC71' if ok else '#E74C3C'};'>{'✅' if ok else '❌'}</span>"

            rows_html += (
                f"<div style='display:flex; gap:6px; padding:5px 0; "
                f"border-bottom:1px solid #222; background:{row_bg}; font-size:13px;'>"
                f"<span style='width:70px; font-weight:bold; color:{pass_clr};'>{tk}</span>"
                f"<span style='width:110px; color:#aaa; overflow:hidden; text-overflow:ellipsis; "
                f"white-space:nowrap;'>{info.get('cn_name', tk)}</span>"
                f"<span style='width:60px; text-align:center; color:#aaa;'>{was_a_icon}</span>"
                f"<span style='width:80px; text-align:right; color:#ccc;'>{div_yield:.2f}%</span>"
                f"<span style='width:80px; text-align:right; color:#ccc;'>{max_dd:.1f}%</span>"
                f"<span style='width:80px; text-align:right; color:#ccc;'>{spy_corr:.2f}</span>"
                f"<span style='width:90px; text-align:center;'>{_chk(ie if not was_a else not ix)}</span>"
                f"<span style='width:90px; text-align:center;'>{_chk(de if not was_a else not dx)}</span>"
                f"<span style='width:90px; text-align:center;'>{_chk(ce if not was_a else not cx)}</span>"
                f"<span style='width:80px; text-align:center; font-weight:bold; color:{pass_clr};'>"
                f"{'✅ 入选' if a_pass else '❌ 未入'}</span>"
                f"<span style='width:100px; text-align:center;'>{hyst_tag}</span>"
                f"</div>"
            )

        st.markdown(
            f"<div style='font-size:13px; color:#888; margin-bottom:6px;'>"
            f"阈值（进入）: 股息≥{th_ie:.1f}% | 回撤&lt;{th_de:.0f}% | 相关&lt;{th_ce:.2f} &nbsp;｜&nbsp;"
            f"阈值（退出）: 股息&lt;{th_ix:.1f}% | 回撤&gt;{th_dx:.0f}% | 相关&gt;{th_cx:.2f}"
            f"</div>"
            f"<div style='background:#111; border-radius:6px; padding:8px; overflow-x:auto;'>"
            f"{header_html}{rows_html}</div>",
            unsafe_allow_html=True,
        )


def _render_conviction_whitebox(
    conv_state: dict,
    prev_conv_state: dict,
    holders: list,
    factor_scores: dict,
    names: dict,
    cfg: dict,
    selected: list,
    decisions: list,
    group_cls: str,
) -> None:
    """第二层白盒：信念守擂全量推演（Panel A/B/C + 参数调节 sliders）。"""
    _ss_prefix = f"conv_{group_cls.lower()}"
    _entry_th = cfg["entry_threshold"]
    _exit_th  = cfg["exit_threshold"]
    _margin   = cfg["challenge_margin"]
    _top_n    = cfg["top_n"]

    with st.expander(f"🔬 第二层白盒 — {group_cls} 组信念守擂全量推演", expanded=False):

        # ── 信念参数 sliders ───────────────────────────────────────
        st.markdown(
            f"<div style='font-size:14px; color:#3498DB; font-weight:bold;"
            f" margin-bottom:8px;'>⚙️ {group_cls} 组信念参数调节（修改后即时生效）</div>",
            unsafe_allow_html=True,
        )
        _sp1, _sp2, _sp3, _sp4 = st.columns(4)
        with _sp1:
            st.slider("挑战者衰减 decay", 0.50, 0.95, step=0.01,
                      key=f"{_ss_prefix}_decay",
                      help="非在位者每月信念衰减系数（越小衰减越快）")
            st.slider("在位者衰减 holder_decay", 0.50, 0.95, step=0.01,
                      key=f"{_ss_prefix}_holder_decay",
                      help="在位者享受更慢衰减（惯性）")
        with _sp2:
            st.slider("积累率 accumulate", 0.05, 0.50, step=0.01,
                      key=f"{_ss_prefix}_accum",
                      help="因子分 → 信念的转化率")
            st.slider("席位数 top_n", 1, 5, step=1,
                      key=f"{_ss_prefix}_top_n",
                      help="守擂席位数")
        with _sp3:
            st.slider("入选门槛 entry", 20, 80, step=1,
                      key=f"{_ss_prefix}_entry",
                      help="信念需达此值方可入选")
        with _sp4:
            st.slider("退出门槛 exit", 10, 60, step=1,
                      key=f"{_ss_prefix}_exit",
                      help="在位者信念跌破此值即退出")
            st.slider("守擂优势 margin", 0, 30, step=1,
                      key=f"{_ss_prefix}_margin",
                      help="挑战者需比最弱在位者高出此值才能替换")

        st.markdown("<hr style='border-color:#333; margin:10px 0;'>", unsafe_allow_html=True)

        # ── Panel A：信念积累明细表 ────────────────────────────────
        st.markdown(
            "<div style='font-size:15px; font-weight:bold; color:#F39C12;"
            " margin-bottom:8px;'>Panel A — 信念积累明细（全候选）</div>",
            unsafe_allow_html=True,
        )
        _selected_set = {s["ticker"] for s in selected}
        _holder_set   = set(holders)
        all_tickers_sorted = sorted(conv_state.keys(), key=lambda t: conv_state[t], reverse=True)

        panel_a_html = (
            "<div style='display:flex; gap:6px; padding:4px 0; border-bottom:2px solid #333;"
            " font-size:13px; color:#888; font-weight:bold;'>"
            "<span style='width:70px;'>Ticker</span>"
            "<span style='width:110px;'>名称</span>"
            "<span style='width:70px; text-align:right;'>旧信念</span>"
            "<span style='width:70px; text-align:right;'>因子分</span>"
            "<span style='width:60px; text-align:center;'>角色</span>"
            "<span style='width:70px; text-align:right;'>衰减率</span>"
            "<span style='width:80px; text-align:right;'>新信念</span>"
            "<span style='width:70px; text-align:right;'>变化量</span>"
            "<span style='flex:1;'>信念条</span>"
            "<span style='width:80px; text-align:center;'>状态</span>"
            "</div>"
        )
        for tk in all_tickers_sorted:
            new_cv   = conv_state.get(tk, 0.0)
            old_cv   = prev_conv_state.get(tk, 0.0)
            fs       = factor_scores.get(tk, 0.0)
            nm       = names.get(tk, tk)
            is_holder = tk in _holder_set
            is_sel   = tk in _selected_set
            decay_used = cfg.get("holder_decay_rate", cfg["decay_rate"]) if is_holder else cfg["decay_rate"]
            delta    = new_cv - old_cv

            if is_sel:
                row_color = "#1e2a1e"
                tk_color  = "#F39C12"
                badge     = "🛡️ 持仓"
            elif new_cv >= _entry_th:
                row_color = "#1a1f2a"
                tk_color  = "#3498DB"
                badge     = "达入选线"
            elif new_cv >= _exit_th:
                row_color = "#1a1a1a"
                tk_color  = "#aaa"
                badge     = "达退出线"
            else:
                row_color = "#111"
                tk_color  = "#555"
                badge     = "低于退出线"

            bar_pct = min(new_cv / 100 * 100, 100)
            entry_mark = int(_entry_th)
            exit_mark  = int(_exit_th)
            bar_color  = "#F39C12" if is_sel else ("#2ECC71" if new_cv >= _entry_th else (
                "#888" if new_cv >= _exit_th else "#333"))
            role_lbl = "在位" if is_holder else "挑战"
            delta_clr = "#2ECC71" if delta >= 0 else "#E74C3C"

            panel_a_html += (
                f"<div style='display:flex; gap:6px; align-items:center; padding:4px 0;"
                f" border-bottom:1px solid #222; background:{row_color}; font-size:13px;'>"
                f"<span style='width:70px; font-weight:bold; color:{tk_color};'>{tk}</span>"
                f"<span style='width:110px; color:#aaa; overflow:hidden; text-overflow:ellipsis;"
                f" white-space:nowrap;'>{nm}</span>"
                f"<span style='width:70px; text-align:right; color:#888;'>{old_cv:.0f}</span>"
                f"<span style='width:70px; text-align:right; color:#888;'>{fs:.0f}</span>"
                f"<span style='width:60px; text-align:center; color:{'#F39C12' if is_holder else '#3498DB'};'>"
                f"{role_lbl}</span>"
                f"<span style='width:70px; text-align:right; color:#888;'>{decay_used:.2f}</span>"
                f"<span style='width:80px; text-align:right; font-weight:bold; color:{tk_color};'>"
                f"{new_cv:.0f}</span>"
                f"<span style='width:70px; text-align:right; color:{delta_clr};'>"
                f"{delta:+.0f}</span>"
                f"<div style='flex:1; position:relative; background:#1e1e1e;"
                f" border-radius:4px; height:8px; min-width:80px;'>"
                f"<div style='width:{bar_pct:.0f}%; background:{bar_color};"
                f" border-radius:4px; height:8px;'></div>"
                f"<div style='position:absolute; top:0; left:{entry_mark}%;"
                f" width:2px; height:8px; background:#3498DB; opacity:0.8;'></div>"
                f"<div style='position:absolute; top:0; left:{exit_mark}%;"
                f" width:2px; height:8px; background:#E74C3C; opacity:0.8;'></div>"
                f"</div>"
                f"<span style='width:80px; text-align:center; font-size:13px; color:#aaa;'>"
                f"{badge}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='font-size:13px; color:#888; margin-bottom:4px;'>"
            f"🔵 蓝线 = 入选线({_entry_th:.0f}) ｜ 🔴 红线 = 退出线({_exit_th:.0f}) ｜"
            f" 🛡️ = 当前持仓 ｜ 按新信念降序</div>"
            f"<div style='background:#111; border-radius:6px; padding:8px;'>"
            f"{panel_a_html}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Panel B：守擂选拔推演 ─────────────────────────────────
        st.markdown(
            "<div style='font-size:15px; font-weight:bold; color:#2ECC71;"
            " margin-bottom:8px;'>Panel B — 守擂选拔推演</div>",
            unsafe_allow_html=True,
        )
        _action_color = {
            "defending":  "#2ECC71",
            "new_entry":  "#3498DB",
            "challenged": "#F39C12",
            "cold_start": "#9B59B6",
            "dropped":    "#E74C3C",
        }
        _action_label = {
            "defending":  "🛡️ 留任",
            "new_entry":  "🆕 新晋",
            "challenged": "⚔️ 挑战",
            "cold_start": "🔰 新兵",
            "dropped":    "📉 退出",
        }
        panel_b_html = ""
        for d in decisions:
            _tk   = d["ticker"]
            _act  = d["action"]
            _det  = d["detail"]
            _nm   = names.get(_tk, _tk)
            _clr  = _action_color.get(_act, "#888")
            _lbl  = _action_label.get(_act, _act)
            _cv   = conv_state.get(_tk, 0.0)
            panel_b_html += (
                f"<div style='display:flex; align-items:center; gap:8px;"
                f" padding:6px 8px; border-bottom:1px solid #222;"
                f" border-left:3px solid {_clr}; margin-bottom:4px;"
                f" background:#111; border-radius:0 4px 4px 0; font-size:13px;'>"
                f"<span style='width:60px; font-weight:bold; color:{_clr};'>{_tk}</span>"
                f"<span style='width:100px; color:#aaa;'>{_nm}</span>"
                f"<span style='width:80px; font-weight:bold; color:{_clr};'>{_lbl}</span>"
                f"<span style='color:#888;'>{_det}</span>"
                f"<span style='margin-left:auto; color:#666; font-size:13px;'>"
                f"信念: {_cv:.0f}</span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='background:#0d0d0d; border-radius:6px; padding:8px;'>"
            f"{panel_b_html}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Panel C：因子排名 vs 信念排名 ─────────────────────────
        st.markdown(
            "<div style='font-size:15px; font-weight:bold; color:#9B59B6;"
            " margin-bottom:8px;'>Panel C — 因子排名 vs 信念排名对比</div>",
            unsafe_allow_html=True,
        )
        tickers_with_scores = [t for t in factor_scores if t in conv_state]
        factor_ranked  = sorted(tickers_with_scores, key=lambda t: factor_scores.get(t, 0.0), reverse=True)
        conv_ranked    = sorted(tickers_with_scores, key=lambda t: conv_state.get(t, 0.0), reverse=True)
        _top_k = min(max(_top_n * 2, 6), len(tickers_with_scores))

        panel_c_html = (
            "<div style='display:grid; grid-template-columns:1fr 1fr; gap:12px;'>"
            "<div>"
            "<div style='font-size:14px; color:#9B59B6; font-weight:bold; margin-bottom:6px;'>"
            "📊 因子分 Top N</div>"
        )
        for i, tk in enumerate(factor_ranked[:_top_k]):
            _fs  = factor_scores.get(tk, 0.0)
            _cv  = conv_state.get(tk, 0.0)
            _nm  = names.get(tk, tk)
            _sel = tk in _selected_set
            _clr = "#F39C12" if _sel else ("#2ECC71" if _cv >= _entry_th else "#888")
            _sel_tag = " 🛡️" if _sel else ""
            panel_c_html += (
                f"<div style='display:flex; justify-content:space-between;"
                f" padding:4px 0; border-bottom:1px solid #222; font-size:13px;'>"
                f"<span style='color:{_clr}; font-weight:{'bold' if _sel else 'normal'};'>"
                f"#{i+1} {tk} {_nm[:8]}{_sel_tag}</span>"
                f"<span style='color:#888;'>F:{_fs:.0f} / C:{_cv:.0f}</span>"
                f"</div>"
            )
        panel_c_html += "</div><div>"
        panel_c_html += (
            "<div style='font-size:14px; color:#F39C12; font-weight:bold; margin-bottom:6px;'>"
            "🛡️ 信念分 Top N</div>"
        )
        for i, tk in enumerate(conv_ranked[:_top_k]):
            _cv  = conv_state.get(tk, 0.0)
            _fs  = factor_scores.get(tk, 0.0)
            _nm  = names.get(tk, tk)
            _sel = tk in _selected_set
            _clr = "#F39C12" if _sel else ("#2ECC71" if _cv >= _entry_th else "#888")
            _sel_tag = " 🛡️" if _sel else ""
            panel_c_html += (
                f"<div style='display:flex; justify-content:space-between;"
                f" padding:4px 0; border-bottom:1px solid #222; font-size:13px;'>"
                f"<span style='color:{_clr}; font-weight:{'bold' if _sel else 'normal'};'>"
                f"#{i+1} {tk} {_nm[:8]}{_sel_tag}</span>"
                f"<span style='color:#888;'>C:{_cv:.0f} / F:{_fs:.0f}</span>"
                f"</div>"
            )
        panel_c_html += "</div></div>"
        # Highlight divergence
        diverged = [
            t for t in tickers_with_scores
            if (factor_ranked.index(t) < _top_n and t not in _selected_set)
            or (t in _selected_set and factor_ranked.index(t) >= _top_n)
        ]
        if diverged:
            div_tags = ", ".join(
                f"<b style='color:#E74C3C;'>{t}</b>"
                if (factor_ranked.index(t) < _top_n and t not in _selected_set)
                else f"<b style='color:#F39C12;'>{t}</b>"
                for t in diverged[:6]
            )
            panel_c_html += (
                f"<div style='margin-top:8px; font-size:13px; color:#888;'>"
                f"⚡ 因子/信念分歧标的：{div_tags}"
                f"（<span style='color:#E74C3C;'>红</span>=因子高但信念未入选，"
                f"<span style='color:#F39C12;'>橙</span>=因子低但信念守住席位）</div>"
            )
        st.markdown(
            f"<div style='background:#111; border-radius:6px; padding:12px;'>"
            f"{panel_c_html}</div>",
            unsafe_allow_html=True,
        )


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
        st.info(f"当前 {meta['label']} 赛道暂无参赛资产。请检查数据加载状态或清除缓存后重试。")
        return

    # ── 计算评分 ─────────────────────────────────────────────────
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
        _record_arena_history(cls, _expand_arena_records(leaders[cls], df_scored))

        # 全局数据流：将 Top-3 Ticker 写入 arena_winners，供 Page 6 消费
        _aw = st.session_state.get("arena_winners", {})
        _aw[cls] = [row["Ticker"] for _, row in df_scored.head(3).iterrows()]
        st.session_state["arena_winners"] = _aw
        _sync_arena_to_backend()

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
            fcf_val = champ.get("FCF收益率", 0.0)
            ribbon_val = champ.get("带鱼质量", 0.0)
            extra_line = (
                f"最大回撤 = **{dd_val*100:.1f}%**，FCF收益率 = **{fcf_val:.2f}%**，"
                f"SPY相关性 = **{corr_val:.2f}**，带鱼质量 = **{ribbon_val:.2f}**。"
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



# ─────────────────────────────────────────────────────────────────
#  侧边栏
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🏆 竞技场控制台")
    st.markdown("---")
    st.subheader("🧭 宏观剧本设定 (3Y 中期战略视角)")
    st.caption("平滑剧本供 B/C 组使用；原始剧本供 D 组宏观匹配")
    _regime_options = ["Soft", "Hot", "Stag", "Rec"]
    _regime_labels  = {"Soft": "软着陆/复苏", "Hot": "过热/再通胀", "Stag": "滞胀", "Rec": "衰退"}
    # 优先读后端缓存，回退到 session_state（write-through 过渡兼容）
    _regime_cache   = fetch_current_regime()
    _ss_regime     = (
        _regime_cache.get("current_macro_regime")
        or st.session_state.get("current_macro_regime")
    )
    _ss_regime_raw = (
        _regime_cache.get("current_macro_regime_raw")
        or st.session_state.get("current_macro_regime_raw")
    )
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
        st.info("后端缓存暂无宏观剧本（首次启动或后端未运行），已默认「Soft」，可手动调整。", icon="ℹ️")
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
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        get_global_data.clear()
        get_stock_metadata.clear()
        get_arena_a_factors.clear()
        get_arena_b_factors.clear()
        get_arena_c_factors.clear()
        get_arena_d_factors.clear()
        _api_get_arena_a_scores.clear()  # A 组 ScorecardA 评分（Render 冷启动失败曾被毒化 30 分钟）
        st.success("当前页缓存已清除！历史档案文件不受影响。")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.success("所有页面缓存已清除！历史档案文件不受影响。")
        st.rerun()
    if st.button("⚠️ 仅清除历史月度 Top 10"):
        st.session_state["_confirm_delete_history"] = True
    if st.session_state.get("_confirm_delete_history"):
        st.warning("此操作将删除所有赛道历史月度 Top 10 记录，不可撤销。")
        _c1, _c2 = st.columns(2)
        with _c1:
            if st.button("确认删除", type="primary"):
                try:
                    # 清空后端 arena_history 表
                    _api_clear_history()
                    # 同步清零 A/B 组信念状态，防止删除历史后残留信念积分影响公平性
                    if not IS_PROD_REMOTE:
                        _api_push_conv("A", {}, [])
                        _api_push_conv("B", {}, [])
                    # 同步删除本地 JSON 备份
                    if os.path.exists(_HISTORY_FILE):
                        os.remove(_HISTORY_FILE)
                    st.session_state.pop("_confirm_delete_history", None)
                    st.success("历史档案及 A/B 组信念状态已同步清空！")
                    st.rerun()
                except Exception as _e:
                    st.error(f"删除失败：{_e}")
        with _c2:
            if st.button("取消"):
                st.session_state.pop("_confirm_delete_history", None)
                st.rerun()

    # ── 生息雷达（Z级新品发现）─────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔭 生息雷达")
    st.sidebar.caption("每周自动扫描全市场高息标的，发现池外新品")
    try:
        _scan_resp = requests.get(f"{API_BASE_URL}/api/v1/z_scan_discoveries", timeout=5)
        if _scan_resp.status_code == 200:
            _scan_data = _scan_resp.json()
            _discoveries = [d for d in _scan_data.get("discoveries", []) if "ticker" in d]
            _scan_time = _scan_data.get("generated_at", "")
            if _discoveries:
                st.sidebar.warning(f"发现 **{len(_discoveries)}** 个池外高息标的！")
                for _d in _discoveries[:8]:
                    st.sidebar.markdown(
                        f"**{_d['ticker']}** {_d.get('name','')[:18]}  \n"
                        f"<span style='color:#1ABC9C;font-size:13px;'>股息率 {_d.get('div_yield_pct',0):.1f}%</span>"
                        f" <span style='color:#888;font-size:12px;'>| {_d.get('source_profile','')}</span>",
                        unsafe_allow_html=True,
                    )
                if len(_discoveries) > 8:
                    st.sidebar.caption(f"...及另外 {len(_discoveries)-8} 个标的")
                if _scan_time:
                    st.sidebar.caption(f"扫描时间：{_scan_time[:10]}")
            else:
                st.sidebar.success("✅ 本轮无新发现，当前池已全覆盖")
                if _scan_time:
                    st.sidebar.caption(f"扫描时间：{_scan_time[:10]}")
        else:
            st.sidebar.caption("生息雷达：暂无扫描报告")
    except Exception:
        st.sidebar.caption("🔭 生息雷达离线（需运行 z_scanner.py）")

    # ── SEC 新品发行警报 ──────────────────────────────────────
    st.sidebar.markdown("### 📋 SEC 新品告警")
    st.sidebar.caption("监控优先股/ETF 新注册申报")
    try:
        _sec_resp = requests.get(f"{API_BASE_URL}/api/v1/sec_alerts", timeout=5)
        if _sec_resp.status_code == 200:
            _sec_data = _sec_resp.json()
            _alerts = _sec_data.get("alerts", [])
            if _alerts:
                st.sidebar.warning(f"过去14天 **{len(_alerts)}** 条新申报！")
                for _a in _alerts[:5]:
                    st.sidebar.markdown(
                        f"**{_a.get('issuer','')}** `{_a.get('form','')}` {_a.get('date','')}",
                    )
            else:
                st.sidebar.success("✅ 过去14天无新发行申报")
        else:
            st.sidebar.caption("SEC 监控：暂无数据")
    except Exception:
        st.sidebar.caption("📋 SEC 监控离线（需 sec_monitor.py）")

# ─────────────────────────────────────────────────────────────────
#  页面标题
# ─────────────────────────────────────────────────────────────────
st.title("🏆 同类资产竞技场 (Same-Class Arena)")
st.caption(
    "一体化分类 + 评分引擎 — 并行独立评估 ABCD 四级（含滞后带） → "
    "同类内部锚点归一化评分 → 赛道翘楚高亮置顶 → 向下游 Page 5 输送冠军标的"
)

# ─────────────────────────────────────────────────────────────────
#  数据来源决策 + 自主分类
# ─────────────────────────────────────────────────────────────────
_core_live = fetch_core_data()
_TIC_MAP = _core_live.get("TIC_MAP", {})
_USER_TICKERS = list(_TIC_MAP.keys())
_SCREEN_TICKERS = sorted(set(_USER_TICKERS))
_DOWNLOAD_TICKERS = sorted(set(_SCREEN_TICKERS + ["SPY"]))

with st.spinner("⏳ 正在加载资产价格矩阵..."):
    _price_df = get_global_data(_DOWNLOAD_TICKERS, years=3)

with st.spinner("⏳ 正在加载基本面元数据（市值/股息率）..."):
    _meta_live = get_stock_metadata(_SCREEN_TICKERS)

if _price_df.empty or len(_price_df) < 30:
    st.error("⚠️ 价格数据加载失败，请检查网络或清理缓存后重试。")
    st.stop()

_prev_grades_map = _load_prev_classification()

# Read hysteresis thresholds from session_state (set by sliders in whitebox section)
_hyst_thresholds = {
    "a_income_enter": st.session_state.get("hyst_a_income_enter", 1.0),
    "a_income_exit":  st.session_state.get("hyst_a_income_exit",  0.5),
    "a_dd_enter":     st.session_state.get("hyst_a_dd_enter",    15.0),
    "a_dd_exit":      st.session_state.get("hyst_a_dd_exit",     20.0),
    "a_corr_enter":   st.session_state.get("hyst_a_corr_enter",  0.65),
    "a_corr_exit":    st.session_state.get("hyst_a_corr_exit",   0.75),
}

with st.spinner("⚙️ 正在执行并行 ABCD 分类（含滞后带）…"):
    _cls_result = run_classification_api(
        screen_tickers=_SCREEN_TICKERS,
        meta_data=_meta_live,
        prev_grades_map=_prev_grades_map,
        z_seed_tickers=list(_Z_SEED_TICKERS),
        thresholds=_hyst_thresholds,
        price_df=_price_df,
    )
    if _cls_result.get("success"):
        all_assets = _cls_result["abcd_classified_assets"]
    else:
        st.warning(f"⚠️ 后端分类 API 失败，回退本地计算: {_cls_result.get('error','')}", icon="⚠️")
        _date_idx = len(_price_df) - 1
        all_assets = classify_all_at_date(
            _price_df, _date_idx, _SCREEN_TICKERS, _meta_live,
            tic_map=_TIC_MAP, prev_grades_map=_prev_grades_map,
            z_seed_tickers=_Z_SEED_TICKERS,
            thresholds=_hyst_thresholds,
        )

_new_grades_map = {
    t: info.get("qualifying_grades", [])
    for t, info in all_assets.items()
}
_save_prev_classification(_new_grades_map)

st.session_state["abcd_classified_assets"] = all_assets
# write-through：同步到后端（arena_winners 此时尚未计算，先持久化资产分类）
# 遵循 DATA_CONSISTENCY_PROTOCOL 约束 2：禁止静默失败
if not push_screen_results({
    "abcd_classified_assets": all_assets,
    "arena_winners": st.session_state.get("arena_winners", {}),
    "p4_arena_leaders": st.session_state.get("p4_arena_leaders", {}),
}):
    st.toast("⚠️ ABCD 分类首次同步后端失败，下游页面可能看到陈旧数据", icon="⚠️")


# ─────────────────────────────────────────────────────────────────
#  构建全量 DataFrame（并行模式：每个 qualifying grade 一行）
# ─────────────────────────────────────────────────────────────────
rows = []
for ticker, info in all_assets.items():
    if not info.get("has_data", True):
        continue
    q_grades = info.get("qualifying_grades", [])
    if not q_grades:
        p_cls = info.get("cls", "?")
        if p_cls in CLASS_META:
            q_grades = [p_cls]
        else:
            continue
    for g in q_grades:
        if g not in CLASS_META:
            continue
        rows.append({
            "Ticker":   ticker,
            "名称":     info.get("cn_name", ticker),
            "类别":     g,
            "Z-Score":  float(info.get("z_score", 0.0)),
            "20日动量": float(info.get("mom20",   0.0)),
            "趋势健康": bool(info.get("is_bullish", False)),
        })

if not rows:
    st.error("数据中无有效资产，请检查数据加载状态或清除缓存后重试。")
    st.stop()

df_all = pd.DataFrame(rows).astype({"Z-Score": float, "20日动量": float})

def _sync_arena_to_backend() -> bool:
    """write-through：将当前 arena_winners + p4_arena_leaders 同步到后端缓存。

    返回是否成功（遵循 DATA_CONSISTENCY_PROTOCOL 约束 2）。失败时 st.toast 告警。
    """
    ok = push_screen_results({
        "abcd_classified_assets": st.session_state.get("abcd_classified_assets", {}),
        "arena_winners":          st.session_state.get("arena_winners", {}),
        "p4_arena_leaders":       st.session_state.get("p4_arena_leaders", {}),
    })
    if not ok:
        st.toast("⚠️ Arena 结果同步后端失败，Page 4/5/6 可能看到陈旧数据", icon="⚠️")
    return ok

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
          ":has(> div:nth-child(5)):not(:has(> div:nth-child(6)))"
          ":has(div[data-testid='stButton'])")

_hover4_css = []
for _i4h in range(1, 6):
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

overview_cols = st.columns(5)
for i, cls in enumerate(["Z", "A", "B", "C", "D"]):
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
    df_a  = df_all[df_all["类别"] == "A"].copy()
    meta_a  = CLASS_META["A"]
    cfg_a = ARENA_CONFIG["A"]

    _a_pills_html = ""
    for (_fn, _fl), _fc in zip(cfg_a["factor_labels"].items(), _A_FACTOR_COLORS):
        _wv = cfg_a["weights"].get(_fn, 0.0)
        _a_pills_html += (
            f"<span class='factor-pill' style='background:{_fc}22; color:{_fc}; "
            f"border:1px solid {_fc}55;'>{_fl}  {int(_wv*100)}%</span>"
        )
    st.markdown(f"""
    <div class='arena-header' style='background:{meta_a["bg"]}; border:1px solid {meta_a["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta_a["color"]}; margin-bottom:8px;'>
            {meta_a["icon"]} {meta_a["label"]} -- {cfg_a["score_name"]}赛道
        </div>
        <div style='font-size:13px; color:#bbb; line-height:1.8;'>{cfg_a["logic"]}</div>
        <div style='margin-top:10px; font-size:13px; color:#666;'>
            评分权重 → {_a_pills_html}
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(_conv_explain_html(config=CONVICTION_A_CONFIG), unsafe_allow_html=True)

    with st.expander("📐 底层因子公式（ScorecardA 满分 100）", expanded=False):
        st.markdown("""
        <div style='font-size:14px; color:#ccc; line-height:1.8;'>
        <span style='color:#2ECC71; font-weight:bold;'>Score<sub>A</sub></span> =
        <span style='color:#2ECC71;'>(35 &times; InvMaxDD<sub>norm</sub>)</span> +
        <span style='color:#3498DB;'>(25 &times; DivYield<sub>norm</sub>)</span> +
        <span style='color:#9B59B6;'>(20 &times; InvSPYCorr<sub>norm</sub>)</span> +
        <span style='color:#F39C12;'>(20 &times; InvVol<sub>norm</sub>)</span><br>
        <span style='color:#888; font-size:13px;'>
        此因子分数作为「信念积分的输入信号」，不再直接决定排名。
        连续多月高分 &rarr; 信念积累 &rarr; 达标入选 &rarr; 守擂留任。
        四维纯统计指标同时达标方为真正避风港，拒绝一切短期噪音。
        </span>
        </div>
        """, unsafe_allow_html=True)

    if df_a.empty:
        st.info("当前 A 级赛道暂无参赛资产。请检查数据加载状态或清除缓存后重试。")
    else:
        with st.spinner("正在拉取 A 组避风港因子数据（最大回撤、FCF收益率、SPY相关性、带鱼质量）…"):
            _factors_a = get_arena_a_factors(tuple(df_a["Ticker"].tolist()))

        df_a["FCF收益率"]   = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("fcf_yield",   0.0)))
        df_a["最大回撤_raw"] = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("max_dd_252",  0.0)))
        df_a["SPY相关性"]   = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("spy_corr",    0.5)))
        df_a["年化波动率"]   = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("ann_vol",     0.30)))
        df_a["带鱼质量"]    = df_a["Ticker"].map(lambda t: float(_factors_a.get(t, {}).get("ribbon_score", 0.0)))

        _a_fallback_tickers = [t for t in df_a["Ticker"] if _factors_a.get(t, {}).get("_fallback")]
        if _a_fallback_tickers:
            st.warning(
                f"⚠️ **{len(_a_fallback_tickers)} 个标的因子数据拉取失败**（yfinance 限速），"
                f"排行榜中其最大回撤/SPY相关/年化波动显示为占位符：**{', '.join(_a_fallback_tickers)}**。"
                f"点击侧边栏「清除当前页缓存」后刷新可重试。"
            )

        # ── 使用后端 ScorecardA（新公式：45/20/20/15，3年回溯，DCR）──
        _score_err_msg = None
        with st.spinner("正在调用后端 ScorecardA 新公式评分…"):
            try:
                _new_a_result = _api_get_arena_a_scores(tuple(df_a["Ticker"].tolist()))
            except Exception as _score_exc:
                # api_client 层对失败/空结果一律抛异常（避免毒化 @cache_data）
                _score_err_msg = f"{type(_score_exc).__name__}: {str(_score_exc)[:240]}"
                _new_a_result = {"scores": {}, "breakdowns": {}}
        _new_a_scores  = _new_a_result.get("scores", {})
        _a_breakdowns  = _new_a_result.get("breakdowns", {})
        if _new_a_scores:
            df_a["竞技得分"] = df_a["Ticker"].map(lambda t: float(_new_a_scores.get(t, 0.0)))
        else:
            # 常驻 st.error 代替易错过的 st.toast，把真实异常类型和错因永久显示
            st.error(
                f"🔴 **ScorecardA 评分失败 → 排行榜得分置零**\n\n"
                f"**错因：** `{_score_err_msg or 'scores 字段为空（后端 score_a 返回成功但载荷空）'}`\n\n"
                f"**常见根因：** yfinance 被 Yahoo 反爬封禁（401 Invalid Crumb / 云 IP 黑名单）、"
                f"Render 冷启动超时、后端 OOM 重启。请查 Render logs 和 Streamlit Cloud app logs 进一步定位。"
            )
            df_a["竞技得分"] = 0.0
        df_scored_a = df_a.sort_values("竞技得分", ascending=False).reset_index(drop=True)
        df_scored_a["排名"] = range(1, len(df_scored_a) + 1)

        # 因子分直接取后端 breakdowns，与 ScorecardA 打分完全同口径
        df_scored_a["因子1_分"] = df_scored_a["Ticker"].map(
            lambda t: float(_a_breakdowns.get(t, {}).get("score_dd",     0.0)))
        df_scored_a["因子2_分"] = df_scored_a["Ticker"].map(
            lambda t: float(_a_breakdowns.get(t, {}).get("score_fcf",    0.0)))
        df_scored_a["因子3_分"] = df_scored_a["Ticker"].map(
            lambda t: float(_a_breakdowns.get(t, {}).get("score_dcr",    0.0)))
        df_scored_a["因子4_分"] = df_scored_a["Ticker"].map(
            lambda t: float(_a_breakdowns.get(t, {}).get("score_ribbon", 0.0)))
        # 最大回撤列改用 3Y，与 ScorecardA F1 同口径；降级时保留原 1Y 值
        _a_dd_1y = df_scored_a.set_index("Ticker")["最大回撤_raw"].to_dict()
        df_scored_a["最大回撤_raw"] = df_scored_a["Ticker"].map(
            lambda t: float(_a_breakdowns.get(t, {}).get("max_dd_3y", _a_dd_1y.get(t, 0.0))))
        df_scored_a["熔断状态"] = df_scored_a["Ticker"].map(
            lambda t: str(_a_breakdowns.get(t, {}).get("status", "")))

        n_a = len(df_scored_a)
        _rt_selected_a = []
        _rt_decisions_a = []
        _rt_old_conv_a: dict = {}

        # Build conviction config from session_state sliders (defaults = CONVICTION_A_CONFIG)
        _rt_conv_cfg_a = {
            "decay_rate":        st.session_state.get("conv_a_decay",        CONVICTION_A_CONFIG["decay_rate"]),
            "holder_decay_rate": st.session_state.get("conv_a_holder_decay", CONVICTION_A_CONFIG["holder_decay_rate"]),
            "accumulate_rate":   st.session_state.get("conv_a_accum",        CONVICTION_A_CONFIG["accumulate_rate"]),
            "entry_threshold":   float(st.session_state.get("conv_a_entry",  CONVICTION_A_CONFIG["entry_threshold"])),
            "exit_threshold":    float(st.session_state.get("conv_a_exit",   CONVICTION_A_CONFIG["exit_threshold"])),
            "challenge_margin":  float(st.session_state.get("conv_a_margin", CONVICTION_A_CONFIG["challenge_margin"])),
            "max_conviction":    CONVICTION_A_CONFIG["max_conviction"],
            "top_n":             int(st.session_state.get("conv_a_top_n",    CONVICTION_A_CONFIG["top_n"])),
        }

        if n_a > 0:
            _rt_factor_scores_a = {
                row["Ticker"]: float(row["竞技得分"])
                for _, row in df_scored_a.iterrows()
            }
            _rt_prev_conv_a, _rt_conv_holders_a = _load_conviction_state("A")
            _rt_old_conv_a = dict(_rt_prev_conv_a)  # snapshot before update for whitebox
            _rt_conv_state_a = _conv_update(
                _rt_prev_conv_a, _rt_factor_scores_a,
                current_holders=_rt_conv_holders_a,
                config=_rt_conv_cfg_a,
            )
            _rt_names_a = {row["Ticker"]: row["名称"] for _, row in df_scored_a.iterrows()}
            _rt_selected_a, _rt_decisions_a = _conv_select(
                _rt_conv_state_a, _rt_conv_holders_a,
                ticker_names=_rt_names_a,
                factor_scores=_rt_factor_scores_a,
                config=_rt_conv_cfg_a,
            )
            _rt_new_holders_a = [s["ticker"] for s in _rt_selected_a]

            leaders = st.session_state.get("p4_arena_leaders", {})
            leaders["A"] = [
                {"ticker": s["ticker"], "name": s["name"],
                 "score": s.get("factor_score", 0.0),
                 "conviction": s["conviction"], "status": s["status"],
                 "cls": "A"}
                for s in _rt_selected_a
            ]
            st.session_state["p4_arena_leaders"] = leaders
            _record_arena_history("A", _expand_arena_records(leaders["A"], df_scored_a))
            _save_conviction_state("A", _rt_conv_state_a, _rt_new_holders_a)

            _aw = st.session_state.get("arena_winners", {})
            _aw["A"] = _rt_new_holders_a
            st.session_state["arena_winners"] = _aw
            _sync_arena_to_backend()

        st.markdown("---")
        # 构建全量信念 map（含守擂状态），传入排行榜以展示信念值列
        _full_conv_map_a: dict = {}
        if n_a > 0:
            _sel_status_map_a = {s["ticker"]: s["status"] for s in _rt_selected_a}
            for _tk, _cv in _rt_conv_state_a.items():
                _full_conv_map_a[_tk] = {
                    "conviction": _cv,
                    "status": _sel_status_map_a.get(_tk, ""),
                }
        _render_leaderboard(df_scored_a, "A", conviction_map=_full_conv_map_a)


        # ── 白盒加工台 ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:16px; font-weight:bold; color:#F39C12;"
            " margin-bottom:4px;'>🔬 白盒加工台 — 排行榜到 Top 3 的完整推演</div>",
            unsafe_allow_html=True,
        )
        _ab_assets = st.session_state.get("abcd_classified_assets", {})
        _render_hysteresis_whitebox(_ab_assets)
        if n_a > 0:
            _render_conviction_whitebox(
                conv_state=_rt_conv_state_a,
                prev_conv_state=_rt_old_conv_a,
                holders=_rt_conv_holders_a,
                factor_scores=_rt_factor_scores_a,
                names=_rt_names_a,
                cfg=_rt_conv_cfg_a,
                selected=_rt_selected_a,
                decisions=_rt_decisions_a,
                group_cls="A",
            )

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
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[0]}22; color:{_B_FACTOR_COLORS[0]}; border:1px solid {_B_FACTOR_COLORS[0]}55;'>真·护城河质量  25%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[1]}22; color:{_B_FACTOR_COLORS[1]}; border:1px solid {_B_FACTOR_COLORS[1]}55;'>抗跌韧性  20%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[2]}22; color:{_B_FACTOR_COLORS[2]}; border:1px solid {_B_FACTOR_COLORS[2]}55;'>夏普比率  20%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[3]}22; color:{_B_FACTOR_COLORS[3]}; border:1px solid {_B_FACTOR_COLORS[3]}55;'>中期相对强度 RS₁₂₀  15%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[4]}22; color:{_B_FACTOR_COLORS[4]}; border:1px solid {_B_FACTOR_COLORS[4]}55;'>绝对体量  10%</span>
            <span class='factor-pill' style='background:{_B_FACTOR_COLORS[5]}22; color:{_B_FACTOR_COLORS[5]}; border:1px solid {_B_FACTOR_COLORS[5]}55;'>Revenue增速  10%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(_conv_explain_html(), unsafe_allow_html=True)

    with st.expander("📐 底层因子公式（ScorecardB 满分 100）", expanded=False):
        st.markdown("""
        <div style='font-size:14px; color:#ccc; line-height:1.8;'>
        <span style='color:#F39C12; font-weight:bold;'>Score<sub>B</sub></span> =
        <span style='color:#F39C12;'>(25 × RealQuality<sub>norm</sub>)</span> +
        <span style='color:#3498DB;'>(20 × Resilience<sub>InvMaxDD</sub>)</span> +
        <span style='color:#2ECC71;'>(20 × Sharpe<sub>1Y</sub>)</span> +
        <span style='color:#E67E22;'>(15 × RS₁₂₀<sub>vs SPY</sub>)</span> +
        <span style='color:#9B59B6;'>(10 × MCap<sub>log10</sub>)</span> +
        <span style='color:#E74C3C;'>(10 × RevenueGrowth<sub>TTM</sub>)</span><br>
        <span style='color:#888; font-size:13px;'>
        此因子分数作为「信念积分的输入信号」，不再直接决定排名。
        连续多月高分 → 信念积累 → 达标入选 → 守擂留任。
        RS₁₂₀ 捕捉中期趋势切换，避免走弱标的长期霸占席位。
        </span>
        </div>
        """, unsafe_allow_html=True)

    if df_b.empty:
        st.info("当前 B 级赛道暂无参赛资产。请检查数据加载状态或清除缓存后重试。")
    else:
        with st.spinner("正在拉取 B 组底仓质量因子数据（股息率、最大回撤、夏普比率、市值）…"):
            _factors_b = get_arena_b_factors(tuple(df_b["Ticker"].tolist()))

        df_b["股息率"]     = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("div_yield",      0.0)))
        df_b["最大回撤_raw"] = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("max_dd_252",     0.0)))
        df_b["夏普比率"]    = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("sharpe_252",      0.0)))
        df_b["RS120d"]     = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("rs_120d",         0.0)))
        df_b["市值对数"]    = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("log_mcap",        9.0)))
        df_b["EPS稳定性"]  = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("eps_stability",   0.0)))
        df_b["Revenue增速"] = df_b["Ticker"].map(lambda t: float(_factors_b.get(t, {}).get("revenue_growth", 0.0)))

        df_scored_b = compute_scorecard_b(df_b, macro_regime)

        n_b = len(df_scored_b)
        _rt_selected = []
        _rt_decisions = []
        _rt_old_conv_b: dict = {}

        # Build conviction config from session_state sliders (defaults = CONVICTION_B_CONFIG)
        _rt_conv_cfg_b = {
            "decay_rate":        st.session_state.get("conv_b_decay",        CONVICTION_B_CONFIG["decay_rate"]),
            "holder_decay_rate": st.session_state.get("conv_b_holder_decay", CONVICTION_B_CONFIG["holder_decay_rate"]),
            "accumulate_rate":   st.session_state.get("conv_b_accum",        CONVICTION_B_CONFIG["accumulate_rate"]),
            "entry_threshold":   float(st.session_state.get("conv_b_entry",  CONVICTION_B_CONFIG["entry_threshold"])),
            "exit_threshold":    float(st.session_state.get("conv_b_exit",   CONVICTION_B_CONFIG["exit_threshold"])),
            "challenge_margin":  float(st.session_state.get("conv_b_margin", CONVICTION_B_CONFIG["challenge_margin"])),
            "max_conviction":    CONVICTION_B_CONFIG["max_conviction"],
            "top_n":             int(st.session_state.get("conv_b_top_n",    CONVICTION_B_CONFIG["top_n"])),
        }

        if n_b > 0:
            # ── 信念积累 + 冠军守擂 ──
            _rt_factor_scores = {
                row["Ticker"]: float(row["竞技得分"])
                for _, row in df_scored_b.iterrows()
            }
            _rt_prev_conv_b, _rt_conv_holders = _load_conviction_state("B")
            _rt_old_conv_b = dict(_rt_prev_conv_b)  # snapshot before update for whitebox
            _rt_conv_state = _conv_update(
                _rt_prev_conv_b, _rt_factor_scores,
                current_holders=_rt_conv_holders,
                config=_rt_conv_cfg_b,
            )
            _rt_names = {row["Ticker"]: row["名称"] for _, row in df_scored_b.iterrows()}
            _rt_selected, _rt_decisions = _conv_select(
                _rt_conv_state, _rt_conv_holders,
                ticker_names=_rt_names,
                factor_scores=_rt_factor_scores,
                config=_rt_conv_cfg_b,
            )
            _rt_new_holders = [s["ticker"] for s in _rt_selected]

            leaders = st.session_state.get("p4_arena_leaders", {})
            leaders["B"] = [
                {"ticker": s["ticker"], "name": s["name"],
                 "score": s.get("factor_score", 0.0),
                 "conviction": s["conviction"], "status": s["status"],
                 "cls": "B"}
                for s in _rt_selected
            ]
            st.session_state["p4_arena_leaders"] = leaders
            _record_arena_history("B", _expand_arena_records(leaders["B"], df_scored_b))
            _save_conviction_state("B", _rt_conv_state, _rt_new_holders)

            _aw = st.session_state.get("arena_winners", {})
            _aw["B"] = _rt_new_holders
            st.session_state["arena_winners"] = _aw
            _sync_arena_to_backend()

        st.markdown("---")
        # 构建全量信念 map（含守擂状态），传入排行榜以展示信念值列
        _full_conv_map_b: dict = {}
        if n_b > 0:
            _sel_status_map_b = {s["ticker"]: s["status"] for s in _rt_selected}
            for _tk, _cv in _rt_conv_state.items():
                _full_conv_map_b[_tk] = {
                    "conviction": _cv,
                    "status": _sel_status_map_b.get(_tk, ""),
                }
        _render_leaderboard_b(df_scored_b, conviction_map=_full_conv_map_b)


        # ── 白盒加工台 ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown(
            "<div style='font-size:16px; font-weight:bold; color:#F39C12;"
            " margin-bottom:4px;'>🔬 白盒加工台 — 排行榜到 Top 3 的完整推演</div>",
            unsafe_allow_html=True,
        )
        if n_b > 0:
            _render_conviction_whitebox(
                conv_state=_rt_conv_state,
                prev_conv_state=_rt_old_conv_b,
                holders=_rt_conv_holders,
                factor_scores=_rt_factor_scores,
                names=_rt_names,
                cfg=_rt_conv_cfg_b,
                selected=_rt_selected,
                decisions=_rt_decisions,
                group_cls="B",
            )

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
            <span class='factor-pill' style='background:{meta["color"]}22; color:{meta["color"]}; border:1px solid {meta["color"]}55;'>Forward EPS Z-Score  25%</span>
            <span class='factor-pill' style='background:#3498DB22; color:#3498DB; border:1px solid #3498DB55;'>log₁₀(MCap)  15%</span>
            <span class='factor-pill' style='background:#9B59B622; color:#9B59B6; border:1px solid #9B59B655;'>RS₁₂₀ 中长线强度  20%</span>
            <span class='factor-pill' style='background:#F39C1222; color:#F39C12; border:1px solid #F39C1255;'>宏观顺风  20%</span>
            <span class='factor-pill' style='background:#2ECC7122; color:#2ECC71; border:1px solid #2ECC7155;'>RS₂₅₀ 年度超额  20%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 白盒公式展示 ──────────────────────────────────────────────
    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #E74C3C; padding:14px; margin-bottom:16px; font-size:13px; color:#ccc; border-radius:4px;'>
    <b>⚙️ ScorecardC 白盒公式（满分 100 分）— 慢变量霸权，拒绝短期噪音：</b><br><br>
    <span style='color:#E74C3C; font-weight:bold;'>Score<sub>C</sub></span> =
    <span style='color:#E74C3C;'>(25 × Z<sub>ForwardEPS</sub>)</span> +
    <span style='color:#3498DB;'>(15 × log₁₀(MCap)<sub>norm</sub>)</span> +
    <span style='color:#9B59B6;'>(20 × RS<sub>120d vs SPY</sub>)</span> +
    <span style='color:#F39C12;'>(20 × Fit<sub>Macro</sub>)</span> +
    <span style='color:#2ECC71;'>(20 × RS<sub>250d vs SPY</sub>)</span><br><br>
    <span style='color:#888; font-size:13px;'>
    各因子均经锚点归一化至 [0, 100] 后加权求和。RS₂₅₀ = 标的过去 250 日涨跌幅 − SPY 同期涨跌幅（年度超额收益，半年才显著变化）。<br>
    5日量能 Z-Score 与叙事热度已迁入 D 组短周期体系，不再参与 C 组定价。<br>
    当前宏观剧本（Macro Fit 判定基准）：<b style='color:#F39C12;'>{regime}</b>
    </span>
    </div>
    """.format(regime=macro_regime), unsafe_allow_html=True)

    if df_c.empty:
        st.info(f"当前 C 级赛道暂无参赛资产。请检查数据或清除缓存后重试。")
    else:
        with st.spinner("正在拉取 C 组基本面因子数据（EPS增速、RS₁₂₀、RS₂₅₀、市值）…"):
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
        df_c["RS250d"] = df_c["Ticker"].map(
            lambda t: float(_factors_c.get(t, {}).get("rs_250d", 0.0))
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
            _record_arena_history("C", _expand_arena_records(leaders["C"], df_scored_c))

            # 全局数据流：C 组 Top-3 Ticker → arena_winners
            _aw = st.session_state.get("arena_winners", {})
            _aw["C"] = [row["Ticker"] for _, row in df_scored_c.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw
            _sync_arena_to_backend()

        st.markdown("---")
        st.markdown("#### 🏆 赛道翘楚 — Top 3 高亮置顶")
        _render_podium(df_scored_c.head(3), "C")

        st.markdown("---")
        _render_leaderboard(df_scored_c, "C")


elif _sel4 == "Z":
    df_z_base = df_all[df_all["类别"] == "Z"].copy()
    meta_z  = CLASS_META["Z"]
    cfg_z   = ARENA_CONFIG["Z"]

    st.markdown(f"""
    <div class='arena-header' style='background:{meta_z["bg"]}; border:1px solid {meta_z["color"]}44;'>
        <div style='font-size:18px; font-weight:bold; color:{meta_z["color"]}; margin-bottom:8px;'>
            {meta_z["icon"]} {meta_z["label"]} — {cfg_z["score_name"]}赛道
        </div>
        <div style='font-size:13px; color:#bbb; line-height:1.8;'>{cfg_z["logic"]}</div>
        <div style='margin-top:10px; font-size:13px; color:#666;'>
            评分权重 →
            <span class='factor-pill' style='background:{meta_z["color"]}22; color:{meta_z["color"]}; border:1px solid {meta_z["color"]}55;'>总回报效率 (Sharpe)  30%</span>
            <span class='factor-pill' style='background:#3498DB22; color:#3498DB; border:1px solid #3498DB55;'>真实股息率  20%</span>
            <span class='factor-pill' style='background:#9B59B622; color:#9B59B6; border:1px solid #9B59B655;'>分红续航力  20%</span>
            <span class='factor-pill' style='background:#F39C1222; color:#F39C12; border:1px solid #F39C1255;'>本金盾  15%</span>
            <span class='factor-pill' style='background:#E74C3C22; color:#E74C3C; border:1px solid #E74C3C55;'>净值趋势  15%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #1ABC9C;
         padding:14px; margin-bottom:16px; font-size:14px; color:#ccc; border-radius:4px;'>
    <b>ScorecardZ 白盒公式（满分 100 分）— Total Return 才是真正的王：</b><br><br>
    <span style='color:#1ABC9C; font-weight:bold;'>Score<sub>Z</sub></span> =
    <span style='color:#1ABC9C;'>(30 × Sharpe<sub>1Y</sub>)</span> +
    <span style='color:#3498DB;'>(20 × DivYield<sub>norm</sub>)</span> +
    <span style='color:#9B59B6;'>(20 × DivSustainability<sub>norm</sub>)</span> +
    <span style='color:#F39C12;'>(15 × InvMaxDD<sub>norm</sub>)</span> +
    <span style='color:#E74C3C;'>(15 × PriceReturn<sub>1Y</sub>)</span><br><br>
    <span style='color:#888; font-size:13px;'>
    入选门槛：股息率 ≥ 1%，零股息资产（如 GLD）不参赛。⚠️ 股息陷阱熔断：股息率 &gt; 8% 且净值跌 &gt; 20% 触发
    <span style='color:#E74C3C; font-weight:bold;'>🌋 股息陷阱</span> 预警，额外扣 20 分——高息未必是财富，极可能是跌出来的假高息。
    </span>
    </div>
    """, unsafe_allow_html=True)

    if df_z_base.empty:
        st.info("当前 Z 级赛道暂无参赛资产（需股息率 ≥ 1%）。请检查数据或清除缓存后重试。")
    else:
        with st.spinner("正在拉取 Z 组五维因子数据（Sharpe、股息率、分红续航力、最大回撤、净值趋势）…"):
            _z_tickers = tuple(df_z_base["Ticker"].tolist())
            _factors_a_z = get_arena_a_factors(_z_tickers)
            _factors_b_z = get_arena_b_factors(_z_tickers)

        df_z = df_z_base.copy()
        df_z["股息率"]      = df_z["Ticker"].map(lambda t: float(_factors_a_z.get(t, {}).get("div_yield",       0.0)))
        df_z["最大回撤_raw"] = df_z["Ticker"].map(lambda t: float(_factors_a_z.get(t, {}).get("max_dd_252",     0.0)))
        df_z["年化波动率"]   = df_z["Ticker"].map(lambda t: float(_factors_a_z.get(t, {}).get("ann_vol",        0.30)))
        df_z["EPS稳定性"]   = df_z["Ticker"].map(lambda t: float(_factors_b_z.get(t, {}).get("eps_stability",  0.0)))
        df_z["夏普比率"]     = df_z["Ticker"].map(lambda t: float(_factors_b_z.get(t, {}).get("sharpe_252",     0.0)))
        df_z["净值趋势_1Y"]  = df_z["Ticker"].map(lambda t: float(_factors_b_z.get(t, {}).get("price_return_252", 0.0)))

        df_scored_z = compute_scorecard_z(df_z)

        n_z = len(df_scored_z)
        if n_z > 0:
            leaders_z = st.session_state.get("p4_arena_leaders", {})
            leaders_z["Z"] = [
                {"ticker": row["Ticker"], "name": row["名称"], "score": float(row["竞技得分"]), "cls": "Z"}
                for _, row in df_scored_z.head(3).iterrows()
            ]
            st.session_state["p4_arena_leaders"] = leaders_z
            _record_arena_history("Z", _expand_arena_records(leaders_z["Z"], df_scored_z))

            _aw_z = st.session_state.get("arena_winners", {})
            _aw_z["Z"] = [row["Ticker"] for _, row in df_scored_z.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw_z
            _sync_arena_to_backend()

        st.markdown("---")
        st.markdown("#### 🏆 赛道翘楚 — Top 3 高亮置顶")
        _render_podium(df_scored_z.head(3), "Z")

        st.markdown("---")

        # Z 赛道子类分布标签
        _Z_SUBCLASS_COLORS = {
            "固收": "#3498DB", "高息权益": "#2ECC71",
            "REIT": "#E67E22", "优先股": "#E74C3C", "BDC": "#9B59B6",
        }
        if n_z > 0:
            _sector_pill_html = ""
            _subclass_counts: dict = {}
            for _, _zr in df_scored_z.iterrows():
                _sc = _SECTOR_MAP.get(_zr["Ticker"], "其他")
                _subclass_counts[_sc] = _subclass_counts.get(_sc, 0) + 1
            for _sc, _cnt in sorted(_subclass_counts.items(), key=lambda x: -x[1]):
                _c = _Z_SUBCLASS_COLORS.get(_sc, "#888")
                _sector_pill_html += (
                    f"<span style='background:{_c}22; color:{_c}; border:1px solid {_c}55; "
                    f"border-radius:4px; padding:2px 8px; margin-right:6px; font-size:13px;'>"
                    f"{_sc} {_cnt}</span>"
                )
            st.markdown(
                f"<div style='margin-bottom:12px;'>📂 参赛子类分布：{_sector_pill_html}</div>",
                unsafe_allow_html=True,
            )

        _render_leaderboard(df_scored_z, "Z")


        # ── DeFi 链上收益率参考面板（独立赛道，不参与 ScorecardZ）──────
        st.markdown("---")
        with st.expander("🔗 DeFi 链上稳定币收益率参考（不参与 ScorecardZ 评分）", expanded=False):
            st.caption(
                "数据来源：DeFi Llama 公开 API | 仅展示 TVL > $100M 的稳定币借贷池 | "
                "APY 实时波动，仅供参考，不构成投资建议"
            )
            try:
                _defi_resp = requests.get(f"{API_BASE_URL}/api/v1/defi_yields", timeout=8)
                if _defi_resp.status_code == 200:
                    _defi_data = _defi_resp.json()
                    _defi_pools = _defi_data.get("pools", [])
                    if _defi_pools and "error" not in _defi_pools[0]:
                        _df_defi = pd.DataFrame(_defi_pools)
                        _df_defi = _df_defi[["protocol", "chain", "symbol", "apy", "tvl_m"]].copy()
                        _df_defi.columns = ["协议", "链", "币种", "APY(%)", "TVL($M)"]
                        _df_defi["APY(%)"] = _df_defi["APY(%)"].astype(float)
                        _df_defi["TVL($M)"] = _df_defi["TVL($M)"].astype(float)
                        st.dataframe(
                            _df_defi.style.background_gradient(subset=["APY(%)"], cmap="Greens"),
                            use_container_width=True,
                            hide_index=True,
                        )
                        _top_defi = _df_defi.iloc[0]
                        st.info(
                            f"🏆 当前链上最优稳定币收益：**{_top_defi['协议']}** ({_top_defi['链']}) "
                            f"— {_top_defi['币种']} APY = **{_top_defi['APY(%)']:.2f}%**，"
                            f"TVL = ${_top_defi['TVL($M)']:.0f}M"
                        )
                    elif _defi_pools and "error" in _defi_pools[0]:
                        st.warning(_defi_pools[0]["error"])
                    else:
                        st.info("暂无 DeFi 收益率数据")
                else:
                    st.caption("DeFi 监控端点未响应")
            except Exception:
                st.caption("🔗 DeFi 监控离线（需后端启动且 defi_monitor.py 已部署）")

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
        st.info("当前 D 级赛道暂无参赛资产。请检查数据加载状态或清除缓存后重试。")
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
            _record_arena_history("D", _expand_arena_records(leaders["D"], df_scored_d))

            # 全局数据流：D 组 Top-3 Ticker → arena_winners
            _aw = st.session_state.get("arena_winners", {})
            _aw["D"] = [row["Ticker"] for _, row in df_scored_d.head(3).iterrows()]
            st.session_state["arena_winners"] = _aw
            _sync_arena_to_backend()

        # ── KPI 卡片 ─────────────────────────────────────────────
        st.markdown("---")

        # ── 颁奖台 ────────────────────────────────────────────────
        st.markdown("#### 🏆 赛道翘楚 — Top 3 高亮置顶")
        _render_podium_d(df_scored_d.head(3))

        st.markdown("---")

        # ── 完整排行榜 ─────────────────────────────────────────────
        _render_leaderboard_d(df_scored_d)

        # ── 共振猎场 — 叙事动量 × 价格动量 交叉验证 ──────────────
        st.markdown("---")
        st.markdown("#### 🔗 共振猎场 — 叙事 × 动量 交叉验证")
        st.caption(
            "共振分 = ScorecardD 动量分 × 叙事热度分 / 100。"
            "叙事热度分 = L2 板块热力分 × L3 关键词匹配度。"
            "仅当价格动量与叙事热度同时拉满时才会排名靠前，"
            "过滤掉\"有动量无故事\"或\"有故事无动量\"的噪音。"
        )

        # White-box formula
        st.markdown("""
        <div style='background:#1a1a1a; border-left:3px solid #E67E22;
             padding:14px; margin-bottom:16px; font-size:14px; color:#ccc; border-radius:4px;'>
        <b>共振公式（白盒）：</b><br><br>
        <span style='color:#E67E22; font-weight:bold;'>共振分</span> =
        <span style='color:#9B59B6;'>ScorecardD</span> ×
        <span style='color:#2ECC71;'>叙事热度分</span> / 100<br><br>
        <span style='color:#2ECC71;'>叙事热度分</span> =
        <span style='color:#3498DB;'>L2 板块热力分</span> ×
        <span style='color:#F1C40F;'>L3 匹配度</span><br><br>
        <span style='color:#888; font-size:13px;'>
        L3 匹配度 = 共现命中 L3 词的温度总和 / 该 L2 全部 L3 词温度总和。<br>
        通过新闻共现（co-occurrence）动态关联 Ticker 与关键词，无需硬编码映射。
        </span>
        </div>
        """, unsafe_allow_html=True)

        if n_d > 0:
            # --- 始终走 API 获取叙事热度排行（消灭 Page 2 -> Page 3 session_state 依赖）---
            _narr_ranking = None
            _narr_l2l3_raw = None
            with st.spinner("正在拉取叙事雷达数据…"):
                _narr_resp = fetch_l2_l3_detail(days=7)
                _narr_l2l3_raw = _narr_resp.get("data", [])
            if _narr_l2l3_raw:
                    _max_pos_m = max(
                        (float(r.get("heat_momentum", 0)) for r in _narr_l2l3_raw
                         if float(r.get("heat_momentum", 0)) > 0),
                        default=1.0,
                    )
                    _narr_ranking = {}
                    for _nr in _narr_l2l3_raw:
                        _ch = float(_nr.get("composite_heat", 0))
                        _hm = float(_nr.get("heat_momentum", 0))
                        _mb = max(0.0, _hm) / max(_max_pos_m, 0.01)
                        _ns = round((0.6 * _ch + 0.4 * _mb) * 100, 1)
                        _tl3 = _nr.get("top_l3_keywords", [])
                        _narr_ranking[_nr.get("l2_sector", "")] = {
                            "score": _ns,
                            "heat": _ch,
                            "momentum": _hm,
                            "top_l3": [kw.get("keyword", "") for kw in (_tl3 or [])[:3] if isinstance(kw, dict)],
                            "top_l3_full": _tl3 if isinstance(_tl3, list) else [],
                        }

            if _narr_ranking:
                # --- Batch fetch co-occurrence for all D-group tickers ---
                _d_tickers = df_scored_d["Ticker"].tolist()
                with st.spinner(f"正在查询 {len(_d_tickers)} 个 D 组标的的新闻共现关键词…"):
                    _cooc_batch = get_batch_ticker_cooccurrence(_d_tickers, days=7)

                # --- Compute resonance for each ticker ---
                _resonance_rows = []
                for _, _row in df_scored_d.iterrows():
                    _tk = _row["Ticker"]
                    _d_score = float(_row["竞技得分"])

                    # Extract co-occurring keywords for this ticker
                    _cooc_resp = _cooc_batch.get(_tk, {})
                    _cooc_data = _cooc_resp.get("data", [])
                    if isinstance(_cooc_data, dict):
                        _cooc_data = _cooc_data.get("keywords", [])
                    _cooc_kws = set()
                    if isinstance(_cooc_data, list):
                        for _ck in _cooc_data:
                            if isinstance(_ck, dict):
                                _cooc_kws.add(_ck.get("keyword", "").strip().lower())
                            elif isinstance(_ck, str):
                                _cooc_kws.add(_ck.strip().lower())

                    # Match against each L2 sector's L3 keywords
                    _best_l2 = ""
                    _best_narr_score = 0.0
                    _best_match_quality = 0.0
                    _best_matched_kws = []
                    _best_l2_score = 0.0

                    for _l2_name, _l2_info in _narr_ranking.items():
                        _l2_score = _l2_info["score"]
                        _l3_full = _l2_info.get("top_l3_full", [])
                        if not _l3_full:
                            continue

                        _total_burst = 0.0
                        _matched_burst = 0.0
                        _matched_words = []
                        for _l3 in _l3_full:
                            if not isinstance(_l3, dict):
                                continue
                            _kw = _l3.get("keyword", "").strip().lower()
                            _br = float(_l3.get("burst_ratio", 0.0))
                            _total_burst += max(_br, 0.01)
                            if _kw and _kw in _cooc_kws:
                                _matched_burst += max(_br, 0.01)
                                _matched_words.append(_l3.get("keyword", ""))

                        _mq = (_matched_burst / _total_burst) if _total_burst > 0 else 0.0
                        _candidate_score = _l2_score * _mq

                        if _candidate_score > _best_narr_score:
                            _best_narr_score = _candidate_score
                            _best_l2 = _l2_name
                            _best_match_quality = _mq
                            _best_matched_kws = _matched_words
                            _best_l2_score = _l2_score

                    _resonance = round(_d_score * _best_narr_score / 100, 1) if _best_narr_score > 0 else 0.0

                    _resonance_rows.append({
                        "Ticker": _tk,
                        "名称": _row["名称"],
                        "D组动量分": round(_d_score, 1),
                        "匹配L2板块": _best_l2 or "—",
                        "L2热力分": round(_best_l2_score, 1),
                        "L3匹配度": round(_best_match_quality * 100, 1),
                        "叙事热度分": round(_best_narr_score, 1),
                        "共振分": _resonance,
                        "_matched_kws": _best_matched_kws,
                    })

                _resonance_rows.sort(key=lambda x: -x["共振分"])
                df_resonance = pd.DataFrame(_resonance_rows)

                # --- Display: metric cards for top resonance ---
                _has_resonance = any(r["共振分"] > 0 for r in _resonance_rows)
                if _has_resonance:
                    _top3_res = [r for r in _resonance_rows if r["共振分"] > 0][:3]
                    _medal_res = ["🥇", "🥈", "🥉"]
                    _medal_clr_res = ["#FFD700", "#C0C0C0", "#CD7F32"]
                    _cols_res = st.columns(min(3, len(_top3_res)))
                    for _ri, _rr in enumerate(_top3_res):
                        with _cols_res[_ri]:
                            _kw_display = ", ".join(_rr["_matched_kws"][:4]) if _rr["_matched_kws"] else "—"
                            st.markdown(f"""
                            <div style='background:#1a1200; border:1px solid {_medal_clr_res[_ri]}44;
                                 border-radius:10px; padding:16px; text-align:center;'>
                                <div style='font-size:28px;'>{_medal_res[_ri]}</div>
                                <div style='font-size:22px; font-weight:bold; color:#eee;'>{_rr['Ticker']}</div>
                                <div style='font-size:13px; color:#aaa;'>{_rr['名称']}</div>
                                <div style='font-size:30px; font-weight:bold; color:#E67E22;
                                     margin:8px 0 4px 0;'>{_rr['共振分']:.0f}</div>
                                <div style='font-size:13px; color:#888;'>共振分</div>
                                <hr style='border-color:#333; margin:10px 0;'>
                                <div style='font-size:13px; text-align:left; line-height:2; color:#bbb;'>
                                    <span style='color:#888;'>D组动量分</span>
                                    <span style='color:#9B59B6; font-weight:bold; float:right;'>{_rr['D组动量分']:.0f}</span><br>
                                    <span style='color:#888;'>匹配板块</span>
                                    <span style='color:#3498DB; float:right;'>{_rr['匹配L2板块']}</span><br>
                                    <span style='color:#888;'>L2热力分</span>
                                    <span style='color:#2ECC71; float:right;'>{_rr['L2热力分']:.0f}</span><br>
                                    <span style='color:#888;'>L3匹配度</span>
                                    <span style='color:#F1C40F; float:right;'>{_rr['L3匹配度']:.0f}%</span><br>
                                    <span style='color:#888;'>叙事热度分</span>
                                    <span style='color:#2ECC71; font-weight:bold; float:right;'>{_rr['叙事热度分']:.1f}</span><br>
                                </div>
                                <hr style='border-color:#333; margin:10px 0;'>
                                <div style='font-size:13px; color:#E67E22;'>
                                    命中词: {_kw_display}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)

                    # --- Full resonance table ---
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("##### 完整共振排行")
                    _display_cols = ["Ticker", "名称", "D组动量分", "匹配L2板块",
                                     "L2热力分", "L3匹配度", "叙事热度分", "共振分"]
                    st.dataframe(
                        df_resonance[_display_cols].style.format({
                            "D组动量分": "{:.0f}",
                            "L2热力分": "{:.0f}",
                            "L3匹配度": "{:.0f}%",
                            "叙事热度分": "{:.1f}",
                            "共振分": "{:.1f}",
                        }).background_gradient(
                            subset=["共振分"], cmap="YlOrRd", vmin=0
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                    # --- Per-ticker white-box attribution ---
                    with st.expander("🔍 逐标的共振归因明细（白盒化）"):
                        for _rr in _resonance_rows:
                            if _rr["共振分"] <= 0:
                                continue
                            _kw_list = _rr["_matched_kws"]
                            _kw_html = " ".join(
                                f"<span style='background:#E67E2222; color:#E67E22; "
                                f"border:1px solid #E67E2255; border-radius:3px; "
                                f"padding:1px 6px; font-size:13px;'>{w}</span>"
                                for w in _kw_list
                            ) if _kw_list else "<span style='color:#666;'>无命中</span>"
                            st.markdown(f"""
                            <div style='background:#1a1a1a; border-left:3px solid #E67E22;
                                 padding:12px; margin-bottom:10px; border-radius:4px;'>
                                <b style='color:#eee; font-size:15px;'>{_rr['Ticker']}</b>
                                <span style='color:#888; font-size:13px;'>({_rr['名称']})</span>
                                <span style='color:#E67E22; font-weight:bold; float:right;
                                       font-size:15px;'>共振分 {_rr['共振分']:.1f}</span>
                                <div style='margin-top:8px; font-size:13px; color:#bbb; line-height:1.8;'>
                                    D组动量分 <b style='color:#9B59B6;'>{_rr['D组动量分']:.0f}</b>
                                    × 叙事热度分 <b style='color:#2ECC71;'>{_rr['叙事热度分']:.1f}</b>
                                    / 100
                                    = <b style='color:#E67E22;'>{_rr['共振分']:.1f}</b><br>
                                    叙事热度分 = L2「{_rr['匹配L2板块']}」热力分 <b style='color:#3498DB;'>{_rr['L2热力分']:.0f}</b>
                                    × L3 匹配度 <b style='color:#F1C40F;'>{_rr['L3匹配度']:.0f}%</b>
                                </div>
                                <div style='margin-top:6px;'>共现命中 L3 词: {_kw_html}</div>
                            </div>
                            """, unsafe_allow_html=True)

                else:
                    st.info(
                        "当前 D 组标的与叙事雷达热词无共振命中。"
                        "可能原因：1) 新闻共现数据尚未覆盖这些标的；"
                        "2) D 组标的与当前热点叙事主题暂无交集。"
                        "D 组 ScorecardD 纯动量排名仍然有效。"
                    )
            else:
                st.warning(
                    "叙事雷达数据不可用（API 可能未就绪）。"
                    "共振排行暂时跳过，D 组 ScorecardD 排名不受影响。"
                )

        st.markdown("---")


# ─────────────────────────────────────────────────────────────────
#  历史榜单 — 只显示当前选中赛道（_sel4）的月度 Top 10
# ─────────────────────────────────────────────────────────────────
_hist_meta = CLASS_META[_sel4]
st.markdown("---")
st.markdown(
    f"### 📅 {_hist_meta['icon']} {_hist_meta['label']} — 历史月度 Top 10",
)
_hist_macro_note = (
    "本赛道评分不受宏观剧本变化影响，四剧本裁决列仅供市场环境参考。"
    if _sel4 in ("A", "D", "Z")
    else "B 组权重随剧本动态调整；C 组宏观顺风标的随剧本切换，切换月份将自动插入白盒注释行。"
)
st.caption(
    f"当前赛道：{_hist_meta['label']}。纵向追踪每月末排名，"
    "方便确认哪些标的被持续输送至 Page 5 / Page 6。"
    "「四剧本裁决」列来自 Page 1 月度表（与 C 组宏观匹配同源）。"
    f"切换顶部 ABCD 色块即可查看其他赛道历史。{_hist_macro_note}"
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
        "注：每月末先 Point-in-Time 重新执行 ABCD 分类（消除前视偏差），再在各赛道内评分。"
        "首次下载约需 60-120 秒（5年数据量较大）。</div>",
        unsafe_allow_html=True,
    )

if _do_backfill:
    with st.spinner(f"正在下载 {len(all_assets)} 只标的约 6 年历史数据并逐月 PIT 分拣 + 评分…"
                    f"（含 12 个月信念热身期，共计算 {_bf_months + 12} 个月）"):
        _bf_meta = get_stock_metadata(tuple(all_assets.keys()))
        _bf_saved, _bf_err = _backfill_arena_history(
            all_assets, months_back=_bf_months,
            monthly_probs=(
                fetch_current_regime().get("horsemen_monthly_probs")
                or st.session_state.get("horsemen_monthly_probs", {})
            ),
            meta_data=_bf_meta,
            warmup_months=12,
        )
    if _bf_err:
        st.error(f"回填失败：{_bf_err}")
    else:
        st.success(f"回填完成！已写入 {_bf_saved} 个月的历史档案。")
        # ── Phase 4 等价性断言：B/C/D/Z 新旧榜单比对 ──
        _api_fetch_history.clear()
        _new_hist  = _api_fetch_history()
        _old_hist  = _history  # 回填前快照（页面级变量）
        _mismatch_details: list = []
        for _mk in sorted(set(_new_hist) & set(_old_hist)):
            for _cls in ("B", "C", "D", "Z"):
                _new_recs = [r["ticker"] for r in (_new_hist.get(_mk, {}).get(_cls, []) or [])[:3]]
                _old_recs = [r["ticker"] for r in (_old_hist.get(_mk, {}).get(_cls, []) or [])[:3]]
                if _new_recs and _old_recs and _new_recs != _old_recs:
                    _score_diff = [
                        (r["ticker"], round(r.get("score", 0) - next(
                            (o.get("score", 0) for o in (_old_hist.get(_mk, {}).get(_cls, []) or [])
                             if o["ticker"] == r["ticker"]), 0), 2))
                        for r in (_new_hist.get(_mk, {}).get(_cls, []) or [])[:5]
                        if any(o["ticker"] == r["ticker"] for o in (_old_hist.get(_mk, {}).get(_cls, []) or []))
                    ]
                    _mismatch_details.append(f"{_mk}/{_cls}: 新={_new_recs} 旧={_old_recs} 分差前5={_score_diff}")
        if _mismatch_details:
            st.error(
                f"🚨 **等价性断言失败**：B/C/D/Z 搬家前后榜单不一致（共 {len(_mismatch_details)} 处），"
                "请人工核查 arena_scoring.py 是否与前端公式完全一致：",
                icon="🚨",
            )
            for _line in _mismatch_details[:10]:
                st.markdown(f"- `{_line}`")
        else:
            st.success("✅ 等价性断言通过：B/C/D/Z Top 3 与旧库完全一致，可安全上线。")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ── 当前赛道历史数据展示 ─────────────────────────────────────────
_history           = _load_arena_history()
_horsemen_archive  = _load_horsemen_verdict_archive()
_medal_icons  = ["🥇", "🥈", "🥉"]
_medal_colors = ["#FFD700", "#C0C0C0", "#CD7F32"]

# Page 1 裁决表为中文「剧本裁决」列
_REGIME_BADGE_CN: dict = {
    "软着陆": ("<span style='color:#2ECC71; font-size:13px; font-weight:bold;'>🚗 软着陆</span>", "#2ECC71"),
    "再通胀": ("<span style='color:#E74C3C; font-size:13px; font-weight:bold;'>🔥 再通胀</span>", "#E74C3C"),
    "滞胀":   ("<span style='color:#F1C40F; font-size:13px; font-weight:bold;'>🚨 滞胀</span>",   "#F1C40F"),
    "衰退":   ("<span style='color:#3498DB; font-size:13px; font-weight:bold;'>❄️ 衰退</span>",   "#3498DB"),
}
_REGIME_BADGE_EMPTY = ("<span style='color:#444; font-size:13px;'>—</span>", "#444")


def _compute_streaks(history: dict, cls: str) -> dict:
    """按时间正序遍历，计算每个月每个标的在该赛道 Top 10 的连续在榜月数。
    返回 {month: {ticker: streak_count}}。"""
    sorted_months = sorted(k for k in history if not k.startswith("_"))
    prev_tickers: set = set()
    prev_streaks: dict = {}
    result: dict = {}
    for mo in sorted_months:
        recs = history[mo].get(cls, [])[:10]
        cur_tickers = {r["ticker"] for r in recs}
        cur_streaks = {}
        for tk in cur_tickers:
            cur_streaks[tk] = prev_streaks.get(tk, 0) + 1 if tk in prev_tickers else 1
        result[mo] = cur_streaks
        prev_tickers = cur_tickers
        prev_streaks = cur_streaks
    return result


def _streak_badge_html(streak: int) -> str:
    if streak >= 6:
        return (f"<span style='background:#F39C12; color:#000; font-size:13px; "
                f"font-weight:bold; padding:0 5px; border-radius:3px; "
                f"flex-shrink:0; margin-left:4px;'>{streak}月</span>")
    if streak >= 3:
        return (f"<span style='background:#2ECC71; color:#000; font-size:13px; "
                f"font-weight:bold; padding:0 5px; border-radius:3px; "
                f"flex-shrink:0; margin-left:4px;'>{streak}月</span>")
    return (f"<span style='font-size:13px; color:#555; "
            f"flex-shrink:0; margin-left:4px;'>{streak}月</span>")


_HIST_CONV_ICONS: dict = {
    "defending":  ("🛡️", "#2ECC71"),
    "new_entry":  ("🆕", "#3498DB"),
    "challenged": ("⚔️", "#F39C12"),
    "cold_start": ("🔰", "#9B59B6"),
}


def _hist_cell(rec: dict, medal_color: str, streak: int = 0) -> str:
    _streak_html = _streak_badge_html(streak) if streak >= 1 else ""
    _conv = rec.get("conviction")
    _conv_html = ""
    if _conv is not None:
        _status = rec.get("status", "")
        _icon, _conv_color = _HIST_CONV_ICONS.get(_status, ("🔮", "#9B59B6"))
        _conv_html = (
            f"<span style='font-size:13px; color:{_conv_color}; font-weight:bold; "
            f"flex-shrink:0; margin-left:4px;'>{_icon} {_conv:.0f}</span>"
        )
    return (
        f"<div style='flex:1; display:flex; align-items:baseline; gap:5px; "
        f"min-width:0; padding-left:4px;'>"
        f"<span style='font-size:14px; font-weight:bold; color:#eee; flex-shrink:0;'>"
        f"{rec['ticker']}</span>"
        f"<span style='font-size:13px; color:#888; overflow:hidden; "
        f"text-overflow:ellipsis; white-space:nowrap;'>{rec['name']}</span>"
        f"{_conv_html}"
        f"{_streak_html}"
        f"</div>"
    )


def _hist_empty() -> str:
    return "<div style='flex:1; font-size:13px; color:#333; padding-left:4px;'>—</div>"


_REGIME_CN_TO_CODE: dict = {"软着陆": "Soft", "再通胀": "Hot", "滞胀": "Stag", "衰退": "Rec"}
_REGIME_EMOJI: dict = {"软着陆": "🚗", "再通胀": "🔥", "滞胀": "🚨", "衰退": "❄️"}
_B_FACTOR_LABELS = ("Quality", "Resilience", "Sharpe", "RS120d", "MCap", "Revenue", "MacroAlign")


def _regime_shift_annotation(prev_cn: str, curr_cn: str, cls: str) -> str:
    """Return annotation-row HTML describing regime shift impact; empty string for A/D/Z."""
    if cls not in ("B", "C"):
        return ""
    prev_code = _REGIME_CN_TO_CODE.get(prev_cn, "")
    curr_code = _REGIME_CN_TO_CODE.get(curr_cn, "")
    if not prev_code or not curr_code:
        return ""

    lines: list = []
    if cls == "B":
        pw = B_REGIME_WEIGHTS.get(prev_code, B_REGIME_WEIGHTS["Soft"])
        cw = B_REGIME_WEIGHTS.get(curr_code, B_REGIME_WEIGHTS["Soft"])
        changes = []
        for i, label in enumerate(_B_FACTOR_LABELS):
            if pw[i] != cw[i]:
                direction = "↑" if cw[i] > pw[i] else "↓"
                color = "#2ECC71" if cw[i] > pw[i] else "#E74C3C"
                changes.append(
                    f"<span style='color:{color}; font-weight:bold;'>"
                    f"{label} {int(pw[i]*100)}%→{int(cw[i]*100)}% {direction}"
                    f"</span>"
                )
        if changes:
            lines.append("B组权重调整：" + "　".join(changes))
    else:  # C
        prev_t = set(_MACRO_TAGS_MAP.get(prev_code, []))
        curr_t = set(_MACRO_TAGS_MAP.get(curr_code, []))
        added   = sorted(curr_t - prev_t)
        removed = sorted(prev_t - curr_t)
        if added:
            tickers_html = " ".join(
                f"<span style='color:#2ECC71; font-weight:bold;'>{t}</span>"
                for t in added
            )
            lines.append(f"宏观顺风新增：{tickers_html}")
        if removed:
            tickers_html = " ".join(
                f"<span style='color:#E74C3C; font-weight:bold; "
                f"text-decoration:line-through;'>{t}</span>"
                for t in removed
            )
            lines.append(f"宏观顺风移出：{tickers_html}")

    if not lines:
        return ""

    content = "　｜　".join(lines)
    return (
        f"<div style='display:flex; align-items:flex-start; padding:5px 8px 5px 11px; "
        f"background:#1a1200; border-left:3px solid #F39C12; "
        f"border-bottom:1px solid #1a1a1a; font-size:13px; color:#ccc;'>"
        f"<span style='color:#F39C12; font-weight:bold; "
        f"flex-shrink:0; margin-right:8px; white-space:nowrap;'>🔀 剧本切换影响</span>"
        f"<span style='flex:1; line-height:1.5;'>{content}</span>"
        f"</div>"
    )


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
        _streaks_map = _compute_streaks(_history, _sel4)

        _TH = (
            "display:flex; align-items:center; padding:6px 8px; "
            "border-bottom:2px solid #2a2a2a; font-size:13px; color:#555; font-weight:bold;"
        )
        _header_row = (
            f"<div style='{_TH}'>"
            f"<div style='width:80px; flex-shrink:0;'>月份</div>"
            f"<div style='width:118px; flex-shrink:0; padding-left:4px;'>四剧本裁决</div>"
            f"<div style='flex:1; padding-left:4px;'>🥇 冠军</div>"
            f"<div style='flex:1; padding-left:4px;'>🥈 亚军</div>"
            f"<div style='flex:1; padding-left:4px;'>🥉 季军</div>"
            f"<div style='flex:2; padding-left:4px; color:#666;'>#4 — #10 候补</div>"
            f"</div>"
        )
        # Pre-compute verdicts to enable look-ahead shift detection
        # _cls_months is newest-first; _cls_months[i+1] = chronologically previous month
        _all_verdicts = [_resolve_horsemen_verdict_cn(_mo, _horsemen_archive) for _mo in _cls_months]
        _data_rows = ""
        for _idx, _mo in enumerate(_cls_months):
            _recs  = _history[_mo].get(_sel4, [])
            _mo_streaks = _streaks_map.get(_mo, {})
            _v_cn   = _all_verdicts[_idx]
            _next_v_cn = _all_verdicts[_idx + 1] if _idx + 1 < len(_cls_months) else ""
            _regime_shifted = bool(_v_cn and _next_v_cn and _v_cn != _next_v_cn)

            if _regime_shifted:
                _prev_emoji = _REGIME_EMOJI.get(_next_v_cn, "")
                _curr_badge, _ = _REGIME_BADGE_CN.get(_v_cn, _REGIME_BADGE_EMPTY)
                _v_html = (
                    f"<div style='line-height:1.3;'>"
                    f"<div style='font-size:13px; color:#777;'>{_prev_emoji}→</div>"
                    f"{_curr_badge}"
                    f"</div>"
                )
            else:
                _v_html, _ = _REGIME_BADGE_CN.get(_v_cn, _REGIME_BADGE_EMPTY)

            _bg    = "#111" if _idx % 2 == 0 else "#0d0d0d"
            _row   = (
                f"<div style='display:flex; align-items:center; padding:8px 8px; "
                f"background:{_bg}; border-bottom:1px solid #1a1a1a;'>"
                f"<div style='width:80px; font-size:13px; font-weight:bold; "
                f"color:{_hist_meta['color']}; flex-shrink:0;'>{_mo}</div>"
                f"<div style='width:118px; flex-shrink:0; padding-left:4px;'>{_v_html}</div>"
            )
            for _ri in range(3):
                if _ri < len(_recs):
                    _row += _hist_cell(_recs[_ri], _medal_colors[_ri], _mo_streaks.get(_recs[_ri]["ticker"], 0))
                else:
                    _row += _hist_empty()
            # #4-#10 候补：灰色小字紧凑排列
            _rest = _recs[3:10]
            if _rest:
                _rest_items = []
                for _ri2, _rec2 in enumerate(_rest, start=4):
                    _rest_items.append(
                        f"<span style='color:#666; white-space:nowrap;'>"
                        f"<span style='color:#555;'>#{_ri2}</span> {_rec2['ticker']}</span>"
                    )
                _rest_html = (
                    f"<div style='flex:2; display:flex; flex-wrap:wrap; gap:4px 10px; "
                    f"align-items:baseline; padding-left:4px; font-size:13px;'>"
                    + "".join(_rest_items)
                    + "</div>"
                )
            else:
                _rest_html = "<div style='flex:2; font-size:13px; color:#333; padding-left:4px;'>—</div>"
            _row += _rest_html
            _row += "</div>"
            _data_rows += _row

            if _regime_shifted:
                _anno = _regime_shift_annotation(_next_v_cn, _v_cn, _sel4)
                if _anno:
                    _data_rows += _anno

        st.markdown(
            f"<div style='border:1px solid {_hist_meta['color']}44; border-radius:8px; "
            f"overflow:hidden;'>{_header_row}{_data_rows}</div>",
            unsafe_allow_html=True,
        )
