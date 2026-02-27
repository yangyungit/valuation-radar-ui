import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# #region agent log
import json as _json, time as _time, pathlib as _pl, traceback as _tb
def _dbg(msg, data=None, hyp="H?"):
    try:
        entry = _json.dumps({"sessionId":"926536","timestamp":int(_time.time()*1000),"location":"4_资产细筛.py","message":msg,"data":data or {},"hypothesisId":hyp})
        _pl.Path("/Users/zhanghao/yangyun/Code_Projects/valuation-radar-ui/.cursor/debug-926536.log").open("a").write(entry+"\n")
    except Exception: pass
# #endregion

# #region agent log
_dbg("page module loading started", {}, "H1")
try:
    import api_client as _ac_mod
    _dbg("api_client module loaded OK", {"attrs": [a for a in dir(_ac_mod) if not a.startswith("_")]}, "H1")
    from api_client import fetch_core_data, get_stock_metadata, get_arena_c_factors, get_arena_d_factors
    _dbg("all 4 functions imported OK", {}, "H2")
except Exception as _ie:
    _full_tb = _tb.format_exc()
    _dbg("IMPORT FAILED", {"error": str(_ie), "type": type(_ie).__name__, "traceback": _full_tb}, "H1")
    st.error(f"🚨 [DEBUG] 导入错误 ({type(_ie).__name__}): {_ie}")
    st.code(_full_tb, language="python")
    st.stop()
# #endregion

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
        "score_name": "压舱石稳定指数",
        "weights": {"bullish": 0.30, "z_score": 0.20, "mom20": 0.25, "div_yield": 0.25},
        "invert_z": False,
        "factor_labels": {
            "bullish":   "低回撤防线 (MA结构坚实)",
            "z_score":   "派息可持续性 (估值稳健)",
            "mom20":     "长周期索提诺 (平稳正向动能)",
            "div_yield": "股息率 (防守收益护城河)",
        },
        "logic": (
            "压舱石的竞技逻辑：稳定性远大于弹性，任何一项结构性恶化直接踢出。"
            "① 低回撤防线（均线结构坚实 MA20 > MA60，代理最大回撤控制能力，权重 30%）"
            "② 派息可持续性（估值稳健不过热，市场对现金流的长期定价，权重 20%）"
            "③ 长周期索提诺（平稳正向动能，非爆发性脉冲，权重 25%）"
            "④ 股息率（真实股息越高防守属性越强，直接体现现金流回报，权重 25%）。"
            "四维同时达标方为真正压舱石，任一维度结构性恶化即触发降级熔断。"
        ),
    },
    "B": {
        "score_name": "大猩猩质量指数",
        "weights": {"z_score": 0.35, "mom20": 0.35, "bullish": 0.30},
        "invert_z": False,
        "factor_labels": {
            "z_score": "护城河溢价 (市值/网络效应)",
            "mom20":   "FCF 质量 (自由现金流动能)",
            "bullish": "ROIC 持续性 (均线趋势代理)",
        },
        "logic": (
            "大猩猩的竞技逻辑：护城河宽度 × FCF 质量 × ROIC 持续性 = 真正的质量因子。"
            "① 护城河溢价（市场愿意持续支付估值溢价，代理网络效应/定价权，权重 35%）"
            "② FCF 质量（自由现金流持续流入反映在动量上，权重 35%）"
            "③ ROIC 持续性（均线趋势健康代理长期资本回报率稳定性，权重 30%）。"
            "估值合理性作为筛选门槛：Z-Score 极端异常时触发质量降级预警。"
        ),
    },
    "C": {
        "score_name": "Alpha 爆发力测试",
        "weights": {},
        "invert_z": False,
        "factor_labels": {
            "eps_growth":      "Forward EPS增速 Z-Score (基本面核动力)",
            "log_mcap":        "log₁₀(市值) (流动性保障)",
            "vol_z":           "5日量能 Z-Score (机构抢筹信号)",
            "macro_alignment": "宏观剧本顺风匹配 (Macro Fit)",
            "narrative_heat":  "叙事热度 (Narrative Heat)",
        },
        "logic": (
            "时代之王 ScorecardC — Alpha 爆发力测试（满分 100 分）："
            "① Forward EPS 增速（华尔街一致预期 12 个月 EPS 增速截面 Z-Score，权重 40%）"
            "② log₁₀(市值)（市值越大流动性越好，机构可大仓位介入，权重 15%）"
            "③ 5日量能 Z-Score（过去 5 日成交量相对 60 日基准的异动强度，捕捉机构抢筹，权重 20%）"
            "④ 宏观顺风（标的宏观标签与当前胜率最高剧本完全匹配得满分，错配得 0，权重 15%）"
            "⑤ 叙事热度（读取资产池内置叙事热度打分，Max-Norm 归一化，权重 10%）。"
            "所有因子均经 Min-Max 归一化至 [0, 100] 后加权求和。"
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
            "🚀 D 组「爆点扫描仪」使命：全市场无差别扫描，只抓【底部放巨量突破】且【走势远强于大盘】的早期异动股。"
            "① 量价共振烈度（5日均量 Z-Score 相对 60日基准，机构入场信号，权重 45%）"
            "② 相对强度 Alpha（近 20 日超越 SPY 超额收益率，时代之王预备特征，权重 35%）"
            "③ 均线起飞姿态（价格与季线 MA60 位置关系，最佳为刚突破 0-20%，乖离过大扣分，权重 20%）。"
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


def compute_scorecard_c(df: pd.DataFrame, macro_regime: str) -> pd.DataFrame:
    """
    ScorecardC — C 组「Alpha 爆发力测试」评分体系 (满分 100 分)

    Score_C = (40 × Z_ForwardEPS) + (15 × log10(MCap)) + (20 × Z_Vol)
            + (15 × Fit_Macro) + (10 × Heat_Narrative)

    各项均先 Min-Max 归一化至 [0, 1] 再乘权重，确保总分上限 100 分。
    """
    if df.empty:
        return df

    result = df.copy()

    # ── 因子 1: Forward EPS Growth Z-Score (40%)
    eps_raw = result.get("EPS增速", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f1_norm = _minmax_norm(eps_raw)

    # ── 因子 2: log10(MarketCap) (15%)
    mcap_log = result.get("市值对数", pd.Series(9.0, index=result.index)).astype(float).fillna(9.0)
    f2_norm = _minmax_norm(mcap_log)

    # ── 因子 3: 5日成交量 Z-Score (20%)
    vol_z = result.get("量能Z", pd.Series(0.0, index=result.index)).astype(float).fillna(0.0)
    f3_norm = _minmax_norm(vol_z)

    # ── 因子 4: Macro Alignment — 标的宏观标签与当前胜率剧本匹配 (15%)
    aligned_tickers = set(_MACRO_TAGS_MAP.get(macro_regime, []))
    f4_norm = result["Ticker"].apply(lambda t: 100.0 if t in aligned_tickers else 0.0)

    # ── 因子 5: Narrative Heat — 叙事热度（来自资产池配置）(10%)
    max_heat = max(_NARRATIVE_HEAT_MAP.values()) if _NARRATIVE_HEAT_MAP else 10.0
    f5_norm = result["Ticker"].apply(
        lambda t: (_NARRATIVE_HEAT_MAP.get(_STOCK_NARRATIVE.get(t, ""), 0.0) / max_heat) * 100.0
    )

    result["因子1_分"] = (0.40 * f1_norm).round(1)
    result["因子2_分"] = (0.15 * f2_norm).round(1)
    result["因子3_分"] = (0.20 * f3_norm).round(1)
    result["因子4_分"] = (0.15 * f4_norm).round(1)
    result["因子5_分"] = (0.10 * f5_norm).round(1)

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
        z_val = row["Z-Score"]
        m_val = row["20日动量"]
        score = row["竞技得分"]
        trend_icon = "✅" if row["趋势健康"] else "🔒"
        trend_txt  = "趋势健康" if row["趋势健康"] else "趋势走弱"
        z_color = "#2ECC71" if z_val > 0.5 else ("#E74C3C" if z_val < -0.5 else "#F1C40F")
        m_color = "#2ECC71" if m_val >= 0 else "#E74C3C"

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
                    <span style='color:#888;'>Z-Score</span>
                    <span style='color:{z_color}; font-weight:bold; float:right;'>{z_val:+.2f}</span><br>
                    <span style='color:#888;'>20日动量</span>
                    <span style='color:{m_color}; font-weight:bold; float:right;'>{m_val:+.1f}%</span><br>
                    <span style='color:#888;'>趋势状态</span>
                    <span style='color:#ccc; float:right;'>{trend_icon} {trend_txt}</span>
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
        z_val = row["Z-Score"]
        m_val = row["20日动量"]
        trend_icon = "✅" if row["趋势健康"] else "🔒"
        z_color = "#2ECC71" if z_val > 0.5 else ("#E74C3C" if z_val < -0.5 else "#F1C40F")
        m_color = "#2ECC71" if m_val >= 0 else "#E74C3C"

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
            f"<div style='width:72px; text-align:right; font-weight:bold; color:{z_color};'>{z_val:+.2f}</div>"
            f"<div style='width:90px; text-align:right; font-weight:bold; color:{m_color};'>{m_val:+.1f}%</div>"
            f"<div style='width:46px; text-align:center;'>{trend_icon}</div>"
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
    df_scored = compute_arena_scores(df_cls, cls)

    # ── 赛道统计 ─────────────────────────────────────────────────
    n_total    = len(df_scored)
    n_bullish  = int(df_scored["趋势健康"].sum())
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

    kpi_cols = st.columns(4)
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
        trend_txt = "趋势健康 (MA20 > MA60)" if champ["趋势健康"] else "趋势走弱 (MA20 < MA60)"
        factor_names = list(cfg["factor_labels"].values())
        factor_breakdown = "，".join(
            f"F{fi}（{fname}）= {champ.get(f'因子{fi}_分', 0.0):.1f}"
            for fi, fname in enumerate(factor_names, start=1)
        )
        st.success(
            f"**{meta['icon']} 赛道冠军深度解读 — {champ['Ticker']} ({champ['名称']})**\n\n"
            f"在 {meta['label']} 的 {n_total} 位参赛标的中，{champ['Ticker']} "
            f"以 **{cfg['score_name']} {champ['竞技得分']:.0f} 分**夺冠。\n"
            f"Z-Score = **{champ['Z-Score']:+.2f}**，20日动量 = **{champ['20日动量']:+.1f}%**，"
            f"{trend_txt}。\n"
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
    st.subheader("🧭 宏观剧本设定")
    st.caption("用于 C 组 ScorecardC 的宏观顺风因子（Macro Alignment）打分")
    _regime_options = ["Soft", "Hot", "Stag", "Rec"]
    _regime_labels  = {"Soft": "软着陆/复苏", "Hot": "过热/再通胀", "Stag": "滞胀", "Rec": "衰退"}
    macro_regime = st.selectbox(
        "当前胜率最高剧本",
        options=_regime_options,
        format_func=lambda x: f"{x} — {_regime_labels[x]}",
        index=0,
    )
    st.markdown("---")
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重刷"):
        st.cache_data.clear()
        st.success("缓存已清除！")
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
        with st.spinner("正在拉取 A 组股息率数据…"):
            _meta_a = get_stock_metadata(tuple(df_a["Ticker"].tolist()))
        df_a["股息率"] = df_a["Ticker"].map(lambda t: float(_meta_a.get(t, {}).get("div_yield", 0.0)))
    else:
        df_a["股息率"] = 0.0
    _render_arena_tab(df_a, "A")

elif _sel4 == "B":
    _render_arena_tab(df_all[df_all["类别"] == "B"].copy(), "B")

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
            <span class='factor-pill' style='background:{meta["color"]}22; color:{meta["color"]}; border:1px solid {meta["color"]}55;'>Forward EPS Z-Score  40%</span>
            <span class='factor-pill' style='background:#3498DB22; color:#3498DB; border:1px solid #3498DB55;'>log₁₀(MCap)  15%</span>
            <span class='factor-pill' style='background:#9B59B622; color:#9B59B6; border:1px solid #9B59B655;'>量能 Z-Score  20%</span>
            <span class='factor-pill' style='background:#F39C1222; color:#F39C12; border:1px solid #F39C1255;'>宏观顺风  15%</span>
            <span class='factor-pill' style='background:#1ABC9C22; color:#1ABC9C; border:1px solid #1ABC9C55;'>叙事热度  10%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 白盒公式展示 ──────────────────────────────────────────────
    st.markdown("""
    <div class='formula-box' style='background:#1a1a1a; border-left:3px solid #E74C3C; padding:14px; margin-bottom:16px; font-size:13px; color:#ccc; border-radius:4px;'>
    <b>⚙️ ScorecardC 白盒公式（满分 100 分）：</b><br><br>
    <span style='color:#E74C3C; font-weight:bold;'>Score<sub>C</sub></span> =
    <span style='color:#E74C3C;'>(40 × Z<sub>ForwardEPS</sub>)</span> +
    <span style='color:#3498DB;'>(15 × log₁₀(MCap)<sub>norm</sub>)</span> +
    <span style='color:#9B59B6;'>(20 × Z<sub>Vol5d</sub>)</span> +
    <span style='color:#F39C12;'>(15 × Fit<sub>Macro</sub>)</span> +
    <span style='color:#1ABC9C;'>(10 × Heat<sub>Narrative</sub>)</span><br><br>
    <span style='color:#888; font-size:11px;'>
    注：各项因子均经 Min-Max 归一化至 [0, 100] 区间后乘以权重系数求和。
    当前宏观剧本（Macro Fit 判定基准）：<b style='color:#F39C12;'>{regime}</b>
    </span>
    </div>
    """.format(regime=macro_regime), unsafe_allow_html=True)

    if df_c.empty:
        st.info(f"当前 C 级赛道暂无参赛资产。请先运行 **2 资产分拣** 或开启演示模式。")
    else:
        with st.spinner("正在拉取 C 组基本面因子数据（EPS增速、量能Z、市值）…"):
            _meta_c    = get_stock_metadata(tuple(df_c["Ticker"].tolist()))
            _factors_c = get_arena_c_factors(tuple(df_c["Ticker"].tolist()))

        df_c["市值对数"] = df_c["Ticker"].map(
            lambda t: float(np.log10(max(float(_meta_c.get(t, {}).get("mcap", 1e9)), 1e6)))
        )
        df_c["EPS增速"] = df_c["Ticker"].map(
            lambda t: float(_factors_c.get(t, {}).get("earnings_growth", 0.0))
        )
        df_c["量能Z"] = df_c["Ticker"].map(
            lambda t: float(_factors_c.get(t, {}).get("vol_z", 0.0))
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
            narrative_c = _STOCK_NARRATIVE.get(champ_c["Ticker"], "未映射")
            heat_c = _NARRATIVE_HEAT_MAP.get(narrative_c, 0.0)
            st.success(
                f"**👑 赛道冠军深度解读 — {champ_c['Ticker']} ({champ_c['名称']})**\n\n"
                f"在 C 级 {n_c} 位参赛标的中以 **Alpha 爆发力 {champ_c['竞技得分']:.0f} 分**夺冠。\n"
                f"Forward EPS 增速贡献 = {champ_c['因子1_分']:.1f}，"
                f"log₁₀(市值) 贡献 = {champ_c['因子2_分']:.1f}，"
                f"量能 Z-Score 贡献 = {champ_c['因子3_分']:.1f}，"
                f"宏观顺风 = {champ_c['因子4_分']:.1f}（{'✅ 顺风' if aligned_c else '❌ 逆风'}，剧本：{macro_regime}），"
                f"叙事热度 = {champ_c['因子5_分']:.1f}（主题：{narrative_c}，热度 {heat_c}/10）。\n"
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
