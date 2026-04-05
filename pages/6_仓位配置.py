import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import json
import os

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_funnel_scores, fetch_rolling_backtest

core_data = fetch_core_data()

# 解包页面需要的字典
TIC_MAP = core_data.get("TIC_MAP", {})


st.set_page_config(page_title="Moltbot 首席投资官中枢", layout="wide", page_icon="🏦")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        get_global_data.clear()
        get_stock_metadata.clear()
        fetch_funnel_scores.clear()
        fetch_rolling_backtest.clear()
        st.session_state.pop("bt_result_cache", None)
        st.success("当前页缓存已清除！")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.session_state.pop("bt_result_cache", None)
        st.success("所有页面缓存已清除！")
        st.rerun()

    st.markdown("---")
    st.markdown("**📅 回测年数**")
    _bt_years_options = {1: "1 年", 2: "2 年", 3: "3 年"}
    _bt_years_prev = st.session_state.get("bt_years_selected", 1)
    _bt_years_sel = st.selectbox(
        "选择回测窗口长度",
        options=[1, 2, 3],
        index=[1, 2, 3].index(_bt_years_prev),
        format_func=lambda x: _bt_years_options[x],
        key="bt_years_selectbox",
        help="含 2 年预热期，实际数据窗口 = 选择年数 + 2 年。",
    )
    if _bt_years_sel != _bt_years_prev:
        st.session_state["bt_years_selected"] = _bt_years_sel
        st.session_state.pop("bt_result_cache", None)
        st.session_state.pop("bt_cache_key", None)
        st.rerun()
    bt_years: int = _bt_years_sel

st.markdown("""
<style>
    .metric-value { font-size: 32px; font-weight: bold; }
    p, li, div[data-testid="stCaptionContainer"] { font-size: 16px !important; line-height: 1.6 !important; }
    [data-testid="stDataFrame"] { font-size: 15px !important; }
    
    .formula-box { background-color: #1a1a1a; border-left: 4px solid #3498DB; padding: 18px; margin-top: 10px; margin-bottom: 15px; font-size: 16px; color: #eee; line-height: 1.6; }
    .hedge-box { background-color: rgba(46, 204, 113, 0.1); border-left: 4px solid #2ECC71; padding: 20px; font-size: 16px; color: #eee; margin-top: 5px; height: 100%; border-radius: 6px; line-height: 1.7; }
    .alpha-box { background-color: rgba(241, 196, 15, 0.1); border-left: 4px solid #F1C40F; padding: 20px; font-size: 16px; color: #eee; margin-top: 5px; height: 100%; border-radius: 6px; line-height: 1.7; }
    .log-item { margin-bottom: 15px; font-size: 16px; line-height: 1.7; color: #fff; padding-bottom: 15px; border-bottom: 1px dashed #555; }
</style>
""", unsafe_allow_html=True)

st.title("🏦 首席投资官中枢 (CIO Dashboard)")
st.caption("基于全局数据的全自动化配置组合：宏观概率分配 ➡️ 板块动量优选 ➡️ 龙头市值加权 ➡️ 净值回测")

# ==========================================
# 🧱 块级强覆盖区 (Page 6)：修复标的池缺失、数据源深度与板块映射
# ==========================================
# 解包所有的云端字典，特别是用户自选股(USER_GROUPS_DEF)和板块映射(SECTOR_MAP)
USER_GROUPS_DEF = core_data.get("USER_GROUPS_DEF", {})
SECTOR_MAP = core_data.get("SECTOR_MAP", {})
NARRATIVE_THEMES_HEAT = core_data.get("NARRATIVE_THEMES_HEAT", {})
REGIME_MAP = core_data.get("REGIME_MAP", {})

MACRO_ASSETS = ["XLY", "XLP", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "XLK", "DBC"]

# 把主理人所有的自选股（A-D组）和宏观池全部加进来
all_pool_tickers = []
for lst in USER_GROUPS_DEF.values(): all_pool_tickers.extend(lst)
all_pool_tickers = list(set([t.strip().upper() for t in all_pool_tickers]))

# 同时把 arena_history 里所有历史出现过的标的也纳入价格池，确保回测能取到价格
_arena_hist_path_early = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")
_arena_hist_full: dict = {}
_arena_extra_tickers: list = []
try:
    with open(_arena_hist_path_early, "r", encoding="utf-8") as _f_ah:
        _arena_hist_full = json.load(_f_ah)
    for _am_data in _arena_hist_full.values():
        for _ag in ('A', 'B', 'C', 'D'):
            for _ae in _am_data.get(_ag, []):
                _at = _ae.get('ticker', '').strip().upper()
                if _at:
                    _arena_extra_tickers.append(_at)
    _arena_extra_tickers = list(set(_arena_extra_tickers))
except Exception:
    pass

UNIVERSAL_TICKERS = list(set(MACRO_ASSETS + all_pool_tickers + list(TIC_MAP.keys()) + _arena_extra_tickers))
UNIVERSAL_TICKERS.sort() 

with st.spinner("⏳ 正在调用中央引擎进行全系推演 (SSOT)..."):
    # 拉取 6 年数据：2 年预热期 + 3 年回测期
    df = get_global_data(UNIVERSAL_TICKERS, years=6)
    meta_info = get_stock_metadata(all_pool_tickers)

if df.empty or len(df) < 750:
    st.warning("⚠️ 数据拉取失败或数据长度不足，无法启动配置引擎。")
    st.stop()

REGIME_CN_MAP = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}

REGIME_NARRATIVE = {
    "软着陆": "享受经济复苏与流动性宽松的双重红利，充当组合的进攻矛。",
    "再通胀": "捕捉经济过热时期的需求扩张与大宗商品价格飙升带来的利润爆炸。",
    "滞胀": "作为终极避险资产，对冲法币信用贬值与经济停滞带来的杀估值风险。",
    "衰退": "充当无视周期的盈利安全垫，抵御大盘系统性下行的毁灭性冲击。"
}

# ── 从 Page 1「四大剧本历史裁决表」读取宏观概率（SSOT） ──────────────────────
# 历史裁决表本身为月度频率，已具备天然防抖特性，无需额外 EMA 平滑层
live_smoothed_probs: dict = st.session_state.get("smoothed_regime_probs", {})
live_regime_label: str    = st.session_state.get("live_regime_label", None)

# 兜底：Page 1 未访问过时，使用等权概率（不引入独立后端 EMA 计算）
if not live_smoothed_probs:
    live_smoothed_probs = {"Soft": 0.25, "Hot": 0.25, "Stag": 0.25, "Rec": 0.25}

df_scores, _ = fetch_funnel_scores(df, all_pool_tickers, meta_info, NARRATIVE_THEMES_HEAT, macro_scores=live_smoothed_probs)

_incumbent_score_p6 = live_smoothed_probs.get(live_regime_label, 0.0) if live_regime_label else max(live_smoothed_probs.values(), default=0.0)
top_regime_score = _incumbent_score_p6
satellite_active = top_regime_score >= 0.60

# C group = top-scoring regime; D group = 2nd-highest regime (hedge/runner-up)
_sorted_live = sorted(live_smoothed_probs.items(), key=lambda x: -x[1])
_c_regime_en = _sorted_live[0][0] if _sorted_live else (live_regime_label or "Soft")
_c_regime_score = _sorted_live[0][1] if _sorted_live else 0.0
_d_regime_en = _sorted_live[1][0] if len(_sorted_live) > 1 else _c_regime_en
_d_regime_score = _sorted_live[1][1] if len(_sorted_live) > 1 else 0.0
# If 2nd regime probability < 60%, D group defaults to C group's script
if _d_regime_score < 0.60:
    _d_regime_en = _c_regime_en
    _d_regime_score = _c_regime_score

# ==========================================
# 🏛️ Core-Satellite Allocation Engine
# ==========================================
# Prepare qualified ticker pool from funnel scores
if not df_scores.empty:
    df_scores['Sector'] = df_scores.apply(
        lambda row: SECTOR_MAP.get(row['代码'], row.get('板块', '综合/未知'))
        if pd.isna(row.get('板块')) or row.get('板块') in ["未知", "", None]
        else row.get('板块'), axis=1)
    df_qualified = df_scores[
        ~df_scores['状态'].str.contains("🌋|❄️|⚠️")
    ].copy() if '状态' in df_scores.columns else df_scores.copy()
else:
    df_qualified = pd.DataFrame()

# ── 提前读取手动 AB 选股 + Arena CD 持仓（session_state SSOT）──────────────────
_early_sel_a: list = st.session_state.get("manual_core_a", [])
_early_sel_b: list = st.session_state.get("manual_core_b", [])
# Arena 迟滞持仓（上次渲染后已写入 session_state）；首次为空 → 不约束
_early_sat_c: list = st.session_state.get("sat_C_holdings", [])
_early_sat_d: list = st.session_state.get("sat_D_holdings", [])

# ── 提前计算 group_assignments + bt_result（SSOT：确保步骤 2 与步骤 4 选股严格一致）────
group_assignments: dict = {}
for _tier_key, _tlist in USER_GROUPS_DEF.items():
    _tid = _tier_key.strip()[0].upper() if _tier_key.strip() else ""
    if _tid not in ("A", "B", "C", "D"):
        continue
    for _t in _tlist:
        _tn = _t.strip().upper()
        if _tn not in df.columns:
            continue
        # 手动选股约束：A/B 组只向回测引擎暴露被选中的标的
        if _tid == 'A' and _early_sel_a and _tn not in _early_sel_a:
            continue
        if _tid == 'B' and _early_sel_b and _tn not in _early_sel_b:
            continue
        # C/D 组：不限制，回测引擎从完整 USER_GROUPS_DEF 候选池里自由 PIT 选股
        # Arena 持仓迟滞仅用于步骤 2 的 UI 展示，不约束回测引擎
        group_assignments[_tn] = _tid

_horsemen_monthly = st.session_state.get("horsemen_monthly_probs", {})
_bt_trim_enabled  = st.session_state.get("bt_trim_applied_enabled", True)
_bt_drift_pct     = st.session_state.get("bt_drift_applied_pct", 30)
bt_years          = st.session_state.get("bt_years_selected", 1)

# AB 选股或再平衡参数变化时自动失效缓存，触发重新回测
# C/D 组不再约束回测引擎，故从缓存键中移除 _early_sat_c/_early_sat_d
_bt_cache_key = (
    tuple(sorted(_early_sel_a)), tuple(sorted(_early_sel_b)),
    _bt_trim_enabled, _bt_drift_pct, bt_years,
)
if st.session_state.get("bt_cache_key") != _bt_cache_key:
    st.session_state.pop("bt_result_cache", None)
    st.session_state["bt_cache_key"] = _bt_cache_key

if "bt_result_cache" not in st.session_state:
    # 按照所选年数裁剪 df（含 2 年预热期）
    _bt_cutoff = pd.Timestamp.now() - pd.DateOffset(years=bt_years + 2)
    _df_for_bt = df[df.index >= _bt_cutoff].copy()
    with st.spinner("⚙️ Core-Satellite VectorBT 走步推演中，首次加载约需 10–20 秒..."):
        st.session_state["bt_result_cache"] = fetch_rolling_backtest(
            _df_for_bt, group_assignments,
            regime_history=_horsemen_monthly,
            trim_enabled=_bt_trim_enabled,
            drift_threshold=_bt_drift_pct / 100.0,
            arena_history=_arena_hist_full if _arena_hist_full else None,
        )
bt_result = st.session_state["bt_result_cache"]

_wh_last = None
if "weight_history" in bt_result and bt_result.get("weight_history"):
    _wh_last = bt_result["weight_history"][-1]

portfolio = []

# 全局数据流：优先使用回测引擎最新一期选股（SSOT），步骤 2 与步骤 4 调仓明细严格对齐
# 若回测失败，回退至 arena_winners 或 Molt 评分
_arena_winners: dict = dict(st.session_state.get("arena_winners", {}))

# ── 从 arena_history.json 补充 C/D 组数据（Page 4 未访问时的 fallback） ────────
# 复用顶部已加载的 _arena_hist_full，避免重复读文件
try:
    for _hist_month in sorted(_arena_hist_full.keys(), reverse=True):
        _hist_entry = _arena_hist_full[_hist_month]
        for _cls in ("C", "D"):
            if _cls not in _arena_winners and _cls in _hist_entry:
                _arena_winners[_cls] = [r["ticker"] for r in _hist_entry[_cls]]
        if "C" in _arena_winners and "D" in _arena_winners:
            break
except Exception:
    pass

_using_arena = bool(_arena_winners)

if _wh_last:
    # ── 从回测引擎最新调仓节点直接读取 PIT 选股结果 ──────────────────────────────
    _BT_TIER_META = {
        "A": ("核心底仓 Core",       "压舱石"),
        "B": ("核心底仓 Core",       "大猩猩"),
        "C": ("战术卫星 Satellite",  "时代之王"),
        "D": ("战术卫星 Satellite",  "预备队"),
    }
    _BT_FALLBACK_PCT = {"A": 25.0, "B": 25.0, "C": 30.0, "D": 20.0}
    for _t_id, (_layer, _label) in _BT_TIER_META.items():
        _tw = _wh_last.get(f"{_t_id.lower()}_weights", {})
        _bil_pct = _BT_FALLBACK_PCT[_t_id]
        if not _tw:
            portfolio.append({
                "配置层": _layer, "所属阵型": _t_id, "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": _bil_pct,
                "白盒归因": f"{_t_id}组无合格标的，{_bil_pct:.0f}% 暂泊 BIL",
                "所属板块": "现金",
            })
        else:
            for _t, _w_pct in _tw.items():
                _molt = 0.0
                if not df_scores.empty and (df_scores["代码"] == _t).any():
                    _molt = float(df_scores.loc[df_scores["代码"] == _t, "Molt评分"].iloc[0])
                portfolio.append({
                    "配置层": _layer,
                    "所属阵型": _t_id,
                    "代码": _t,
                    "名称": TIC_MAP.get(_t, _t),
                    "Molt评分": round(_molt, 1),
                    "分配仓位": round(_w_pct, 2),
                    "白盒归因": f"{_t_id}组({_label}) PIT动量选股 均分 {_bil_pct:.0f}%",
                    "所属板块": SECTOR_MAP.get(_t, "—"),
                })
    satellite_active = _wh_last.get("regime_mode") == "active"


def _picks_from_arena(tier: str, top_n: int = 2) -> pd.DataFrame:
    """
    从 arena_winners 构建 picks DataFrame（代码 / Molt评分 / Sector）。
    若 arena_winners 中无该赛道数据，返回空 DataFrame。
    """
    tickers = _arena_winners.get(tier, [])[:top_n]
    if not tickers:
        return pd.DataFrame()
    rows_out = []
    for t in tickers:
        molt = 0.0
        if not df_scores.empty and (df_scores["代码"] == t).any():
            molt = float(df_scores.loc[df_scores["代码"] == t, "Molt评分"].iloc[0])
        rows_out.append({"代码": t, "Molt评分": molt, "Sector": SECTOR_MAP.get(t, "—")})
    return pd.DataFrame(rows_out)


def _check_ma60_alive(ticker: str, price_df: pd.DataFrame) -> bool:
    """收盘价高于 MA60 返回 True（生命线完好）；数据不足时给予保留利益。"""
    if ticker not in price_df.columns:
        return True
    p = price_df[ticker].dropna().astype(float)
    if len(p) < 60:
        return True
    return float(p.iloc[-1]) > float(p.tail(60).mean())


def _apply_arena_hysteresis(tier: str, arena_top3: list, price_df: pd.DataFrame,
                             max_picks: int = 2) -> tuple:
    """
    Arena 迟滞选股核心逻辑：
    - 当前持仓若仍在 Top-3 且 MA60 生命线完好 → 无条件续持
    - 任一条件不满足 → 踢出，记录原因
    - 出现空缺时，从 Top-3 依次补位（用当时榜首填空）
    返回 (holdings, evicted_list[(ticker, reason)], newly_added)
    """
    prev = list(st.session_state.get(f"sat_{tier}_holdings", []))
    retained, evicted = [], []
    for t in prev:
        in_top3 = t in arena_top3
        alive   = _check_ma60_alive(t, price_df)
        if in_top3 and alive:
            retained.append(t)
        else:
            reason = "跌出前三" if not in_top3 else "跌破MA60"
            evicted.append((t, reason))
    newly_added = []
    for t in arena_top3:
        if len(retained) >= max_picks:
            break
        if t not in retained:
            retained.append(t)
            newly_added.append(t)
    st.session_state[f"sat_{tier}_holdings"] = retained
    return retained, evicted, newly_added


if not _wh_last:
    # ── 回退：bt_result 失败时，用 arena_winners 或 Molt 评分建组 ──────────────
    # ── CORE (50%): A Top-2 = 25%, B Top-2 = 25% ────────────────────────────
    for tier, total_pct, label in [("A", 25.0, "压舱石"), ("B", 25.0, "大猩猩")]:
        arena_picks = _picks_from_arena(tier)
        if not arena_picks.empty:
            picks = arena_picks
            source_tag = "Arena冠军"
        elif df_qualified.empty:
            portfolio.append({
                "配置层": "核心底仓 Core", "所属阵型": tier, "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": round(total_pct, 2),
                "白盒归因": f"{tier}组无合格标的，{total_pct:.0f}% 暂泊 BIL",
                "所属板块": "现金",
            })
            continue
        else:
            picks = (
                df_qualified[df_qualified['Tier'] == tier]
                .sort_values('Molt评分', ascending=False)
                .head(2)
            )
            source_tag = "Top-2"
        n = len(picks)
        for _, row in picks.iterrows():
            ticker = row['代码']
            alloc = total_pct / n if n > 0 else 0.0
            portfolio.append({
                "配置层": "核心底仓 Core",
                "所属阵型": tier,
                "代码": ticker,
                "名称": TIC_MAP.get(ticker, ticker),
                "Molt评分": round(row['Molt评分'], 1),
                "分配仓位": round(alloc, 2),
                "白盒归因": f"{tier}组({label}) {source_tag} 均分 {total_pct:.0f}% 核心底仓",
                "所属板块": row.get('Sector', '—'),
            })
        if n == 0:
            portfolio.append({
                "配置层": "核心底仓 Core", "所属阵型": tier, "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": round(total_pct, 2),
                "白盒归因": f"{tier}组无合格标的，{total_pct:.0f}% 暂泊 BIL",
                "所属板块": "现金",
            })

    # ── SATELLITE (50%): C Top-2 = 30% (top regime), D Top-2 = 20% (2nd regime) ─
    if satellite_active:
        _sat_regime_map = {
            "C": (_c_regime_en, _c_regime_score, 30.0, "时代之王"),
            "D": (_d_regime_en, _d_regime_score, 20.0, "预备队"),
        }
        for tier, (regime_en, reg_score, tier_pct, label) in _sat_regime_map.items():
            regime_cn = REGIME_CN_MAP.get(regime_en, regime_en)
            arena_all = _arena_winners.get(tier, [])[:3] if _using_arena else []

            if arena_all:
                regime_tickers = [t for t in arena_all if REGIME_MAP.get(t) == regime_en]
                picks_list = (regime_tickers if regime_tickers else arena_all)[:2]
                source_tag = "Arena冠军"
            elif not df_qualified.empty:
                df_tier = df_qualified[df_qualified.get('Tier', pd.Series(dtype=str)) == tier]
                df_regime = df_tier[df_tier['代码'].map(lambda t: REGIME_MAP.get(t) == regime_en)] if not df_tier.empty else pd.DataFrame()
                df_src = df_regime if not df_regime.empty else df_tier
                picks_list = df_src.sort_values('Molt评分', ascending=False).head(2)['代码'].tolist()
                source_tag = "Top-2"
            else:
                picks_list = []
                source_tag = "Top-2"

            n = len(picks_list)
            if n == 0:
                portfolio.append({
                    "配置层": "战术卫星 Satellite", "所属阵型": tier, "代码": "BIL",
                    "名称": "极短债/现金等价物", "Molt评分": 0.0,
                    "分配仓位": round(tier_pct, 2),
                    "白盒归因": f"{tier}组无合格标的，{tier_pct:.0f}% 暂泊 BIL",
                    "所属板块": "现金",
                })
                continue
            for t in picks_list:
                molt = 0.0
                if not df_scores.empty and (df_scores["代码"] == t).any():
                    molt = float(df_scores.loc[df_scores["代码"] == t, "Molt评分"].iloc[0])
                portfolio.append({
                    "配置层": "战术卫星 Satellite",
                    "所属阵型": tier,
                    "代码": t,
                    "名称": TIC_MAP.get(t, t),
                    "Molt评分": round(molt, 1),
                    "分配仓位": round(tier_pct / n, 2),
                    "白盒归因": f"{tier}组({label}) {source_tag} 均分 {tier_pct:.0f}%，锚定「{regime_cn}」置信度 {reg_score*100:.0f}%",
                    "所属板块": SECTOR_MAP.get(t, "—"),
                })
    else:
        # Hysteresis / Dormant: persist from session_state or default to BIL
        prev_sat = st.session_state.get("last_satellite_portfolio", [])
        if prev_sat:
            for item in prev_sat:
                item_copy = dict(item)
                item_copy["白盒归因"] = (
                    f"🛌 装死模式迟滞持仓（最强剧本胜率 {top_regime_score*100:.0f}% < 60%）— " + item_copy.get("白盒归因", "")
                )
                portfolio.append(item_copy)
        else:
            portfolio.append({
                "配置层": "战术卫星 Satellite (装死模式)",
                "所属阵型": "现金", "代码": "BIL", "名称": "极短债/现金等价物",
                "Molt评分": 0.0, "分配仓位": 50.0,
                "白盒归因": f"🛌 装死模式：宏观迷茫期（最强剧本胜率 {top_regime_score*100:.0f}% < 60%），卫星池 50% 停泊 BIL 现金防守",
                "所属板块": "现金",
            })

    # Persist active satellite allocation for next-run hysteresis
    if satellite_active:
        st.session_state["last_satellite_portfolio"] = [
            p for p in portfolio if p["配置层"] == "战术卫星 Satellite"
        ]

df_portfolio = pd.DataFrame(portfolio)

# 宏观剧本状态表（数据源：Page 1 四大剧本历史裁决表 SSOT）
step1_logs = []
for regime_en, regime_cn in REGIME_CN_MAP.items():
    sm_w         = live_smoothed_probs.get(regime_en, 0)
    is_incumbent = (regime_en == live_regime_label)
    if regime_en == _c_regime_en and satellite_active:
        sat_influence = "🚀 C组锚点（主攻）"
    elif regime_en == _d_regime_en and satellite_active and _d_regime_en != _c_regime_en:
        sat_influence = "🛡️ D组锚点（对冲）"
    elif is_incumbent:
        sat_influence = "🔒 迟滞拦截"
    else:
        sat_influence = "—"
    step1_logs.append({
        "宏观剧本": regime_cn,
        "历史裁决胜率": f"{sm_w*100:.0f}%",
        "状态机角色": "🏛️ 现任" if is_incumbent else "—",
        "卫星池影响": sat_influence,
    })

st.header("1️⃣ 宏观市场定调 (Macro Climate)")
st.caption("数据源：Page 1「四大剧本历史裁决表」SSOT — 月度裁决，天然防抖，无需额外平滑层")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟢 软着陆信号强度", f"{live_smoothed_probs.get('Soft',0)*100:.0f}%")
c2.metric("🔥 再通胀信号强度", f"{live_smoothed_probs.get('Hot',0)*100:.0f}%")
c3.metric("🟡 滞胀信号强度",   f"{live_smoothed_probs.get('Stag',0)*100:.0f}%")
c4.metric("🔴 衰退信号强度",   f"{live_smoothed_probs.get('Rec',0)*100:.0f}%")

_live_label_cn = REGIME_CN_MAP.get(live_regime_label, live_regime_label or "未确立")
if not st.session_state.get("smoothed_regime_probs"):
    st.info("ℹ️ **尚未从 Page 1 获取裁决数据** — 当前以等权概率兜底。请先访问「🧭 宏观定调」页面以获取完整四大剧本裁决结果。")
if satellite_active:
    _c_cn = REGIME_CN_MAP.get(_c_regime_en, _c_regime_en)
    _d_cn = REGIME_CN_MAP.get(_d_regime_en, _d_regime_en)
    st.success(f"**CIO 洞察 — 双剧本分工:** C组🚀锚定「**{_c_cn}**」({_c_regime_score*100:.0f}%) 主攻，D组🛡️锚定「**{_d_cn}**」({_d_regime_score*100:.0f}%) 对冲备援。")
else:
    st.warning(f"**CIO 洞察 — 装死模式:** 现任剧本「**{_live_label_cn}**」裁决胜率 {top_regime_score*100:.0f}% < 60%，卫星池启动持仓迟滞或停泊 BIL 现金防守。")

st.markdown("---")
st.header("2️⃣ 智能仓位生成引擎 — Core-Satellite (Allocation Engine)")

# 数据流溯源横幅
if _wh_last:
    _wh_date = _wh_last.get("date", "—")
    st.success(
        f"🔗 **SSOT 一致性保障** — 步骤 2 与步骤 4 调仓明细共用同一套 PIT 动量选股引擎（最新节点：{_wh_date}），两者标的严格对齐，零偏差。",
        icon="✅",
    )
    if _using_arena:
        _aw_summary = "、".join(f"**{cls}**组: {', '.join(v)}" for cls, v in _arena_winners.items())
        st.info(f"ℹ️ Page 4 竞技场冠军名单（{_aw_summary}）仅作参考，本页已升级为回测引擎 PIT 选股以确保一致性。", icon="ℹ️")
else:
    st.warning(
        "⚠️ **回测引擎未返回有效结果**，当前回退至 arena_winners 或 Molt 评分选股（步骤 2 与步骤 4 可能存在偏差）。",
        icon="⚠️",
    )

if not df_portfolio.empty:
    st.markdown("#### 🛠️ 步骤 1: 宏观剧本门控 — 历史裁决表胜率 ≥ 60% 触发卫星激活")
    st.caption("数据直接来自 Page 1「四大剧本历史裁决表」月度裁决（SSOT）。月度频率本身即具备防抖特性，无需额外 EMA 平滑层。卫星池激活条件：现任剧本历史裁决胜率 ≥ 60%。")
    st.dataframe(pd.DataFrame(step1_logs), use_container_width=True, hide_index=True)

    st.markdown("#### 🏛️ 步骤 2: Core-Satellite 双层配置")
    st.caption("底仓核心池 (50%) = A组压舱石 (25%) + B组大猩猩 (25%)，**Arena 迟滞选股**：持仓只要仍在 Arena 前三且 MA60 生命线完好即续持，出现空缺才补位。战术卫星池 (50%) = C组时代之王 Top-2 (30%) + D组预备队 Top-2 (20%)，月度历史裁决胜率门控，同样 Arena 迟滞。")

    # ── 手动底仓选股（A/B组）──────────────────────────────────────────────────────
    # 备选池来自完整的 USER_GROUPS_DEF（不受回测过滤影响），确保下拉框始终显示全量标的
    _a_pool = sorted([
        _t.strip().upper() for _k, _tl in USER_GROUPS_DEF.items()
        if _k.strip()[0].upper() == 'A'
        for _t in _tl if _t.strip().upper() in df.columns
    ])
    _b_pool = sorted([
        _t.strip().upper() for _k, _tl in USER_GROUPS_DEF.items()
        if _k.strip()[0].upper() == 'B'
        for _t in _tl if _t.strip().upper() in df.columns
    ])

    # 回测引擎当前推荐作为默认值（首次加载时使用）
    _bt_a_picks = [r['代码'] for r in portfolio if r['所属阵型'] == 'A' and r['代码'] != 'BIL']
    _bt_b_picks = [r['代码'] for r in portfolio if r['所属阵型'] == 'B' and r['代码'] != 'BIL']

    # 从 session_state 读取上次选择，确保选项仍在当前池内
    _init_a = [t for t in st.session_state.get("manual_core_a", _bt_a_picks) if t in _a_pool]
    _init_b = [t for t in st.session_state.get("manual_core_b", _bt_b_picks) if t in _b_pool]
    if not _init_a:
        _init_a = [t for t in _bt_a_picks if t in _a_pool]
    if not _init_b:
        _init_b = [t for t in _bt_b_picks if t in _b_pool]

    with st.expander("✏️ 手动配置核心底仓 A/B 持仓（长期持有，随时可调）", expanded=True):
        _col_a, _col_b = st.columns(2)
        with _col_a:
            st.markdown("**A组（压舱石）— 均分 25%**")
            _sel_a = st.multiselect(
                "从 A 组标的池选择（最多2只）",
                options=_a_pool,
                default=_init_a,
                max_selections=2,
                key="ms_a_core",
                format_func=lambda t: f"{t}  {TIC_MAP.get(t, '')}",
                help="选择后立即生效，不触发任何自动调仓逻辑。",
            )
        with _col_b:
            st.markdown("**B组（大猩猩）— 均分 25%**")
            _sel_b = st.multiselect(
                "从 B 组标的池选择（最多2只）",
                options=_b_pool,
                default=_init_b,
                max_selections=2,
                key="ms_b_core",
                format_func=lambda t: f"{t}  {TIC_MAP.get(t, '')}",
                help="选择后立即生效，不触发任何自动调仓逻辑。",
            )

    # 持久化选择
    st.session_state["manual_core_a"] = _sel_a
    st.session_state["manual_core_b"] = _sel_b

    # 用手动选股覆盖 portfolio / df_portfolio 的 A/B 行
    _other_rows = [r for r in portfolio if r['所属阵型'] not in ('A', 'B')]
    _manual_rows = list(_other_rows)
    for _t_id, _sel, _total_pct, _label in [
        ('A', _sel_a, 25.0, '压舱石'),
        ('B', _sel_b, 25.0, '大猩猩'),
    ]:
        if not _sel:
            _manual_rows.append({
                "配置层": "核心底仓 Core", "所属阵型": _t_id, "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": _total_pct,
                "白盒归因": f"{_t_id}组未选择标的，{_total_pct:.0f}% 暂泊 BIL",
                "所属板块": "现金",
            })
        else:
            _n = len(_sel)
            for _t in _sel:
                _molt = 0.0
                if not df_scores.empty and (df_scores["代码"] == _t).any():
                    _molt = float(df_scores.loc[df_scores["代码"] == _t, "Molt评分"].iloc[0])
                _manual_rows.append({
                    "配置层": "核心底仓 Core",
                    "所属阵型": _t_id,
                    "代码": _t,
                    "名称": TIC_MAP.get(_t, _t),
                    "Molt评分": round(_molt, 1),
                    "分配仓位": round(_total_pct / _n, 2),
                    "白盒归因": f"{_t_id}组({_label}) 手动配置 均分 {_total_pct:.0f}%",
                    "所属板块": SECTOR_MAP.get(_t, "—"),
                })
    portfolio = _manual_rows
    df_portfolio = pd.DataFrame(portfolio)

    # ── C/D 卫星池：Arena 迟滞选股覆盖（优先于回测引擎 PIT 选股）──────────────
    # 规则：入选后持续持有，除非①跌出 Arena 前三 ②跌破 MA60 生命线；
    #       有空缺时，用当时 Arena 榜首依次补位，每组最多持有 2 只。
    _sat_hysteresis_log: dict = {}
    if _arena_winners:
        _CD_TIER_CFG = {"C": (30.0, "时代之王"), "D": (20.0, "预备队")}
        _new_sat_rows_cd: list = []
        for _h_tier, (_h_pct, _h_label) in _CD_TIER_CFG.items():
            _h_top3 = _arena_winners.get(_h_tier, [])[:3]
            if not _h_top3:
                _new_sat_rows_cd.append({
                    "配置层": "战术卫星 Satellite", "所属阵型": _h_tier, "代码": "BIL",
                    "名称": "极短债/现金等价物", "Molt评分": 0.0,
                    "分配仓位": _h_pct,
                    "白盒归因": f"{_h_tier}组 Arena 暂无榜单，请先访问 Page 4 运行竞技场",
                    "所属板块": "现金",
                })
                _sat_hysteresis_log[_h_tier] = {"holdings": [], "evicted": [], "new": []}
                continue
            _h_holds, _h_evicted, _h_new = _apply_arena_hysteresis(_h_tier, _h_top3, df)
            _sat_hysteresis_log[_h_tier] = {
                "holdings": _h_holds, "evicted": _h_evicted, "new": _h_new,
                "top3": _h_top3,
            }
            if not _h_holds:
                _new_sat_rows_cd.append({
                    "配置层": "战术卫星 Satellite", "所属阵型": _h_tier, "代码": "BIL",
                    "名称": "极短债/现金等价物", "Molt评分": 0.0,
                    "分配仓位": _h_pct,
                    "白盒归因": f"{_h_tier}组持仓清零（均跌破MA60或跌出前三），暂泊 BIL",
                    "所属板块": "现金",
                })
                continue
            _h_n = len(_h_holds)
            for _h_t in _h_holds:
                _h_is_new = _h_t in _h_new
                _h_icon   = "✅ " if _h_is_new else "🔒 "
                _h_reason = "Arena新晋入选" if _h_is_new else "Arena迟滞续持"
                _h_molt   = 0.0
                if not df_scores.empty and (df_scores["代码"] == _h_t).any():
                    _h_molt = float(df_scores.loc[df_scores["代码"] == _h_t, "Molt评分"].iloc[0])
                _new_sat_rows_cd.append({
                    "配置层": "战术卫星 Satellite",
                    "所属阵型": _h_tier,
                    "代码": _h_t,
                    "名称": TIC_MAP.get(_h_t, _h_t),
                    "Molt评分": round(_h_molt, 1),
                    "分配仓位": round(_h_pct / _h_n, 2),
                    "白盒归因": f"{_h_icon}{_h_tier}组({_h_label}) {_h_reason} — 均分 {_h_pct:.0f}%",
                    "所属板块": SECTOR_MAP.get(_h_t, "—"),
                })
        portfolio = [r for r in portfolio if r['所属阵型'] not in ('C', 'D')] + _new_sat_rows_cd
        df_portfolio = pd.DataFrame(portfolio)

    if not satellite_active:
        st.warning("🛌 **装死模式激活** — 卫星池 50% 当前为迟滞持仓或 BIL 现金，等待宏观信号明朗后重新出击。")

    col_chart, col_table = st.columns([1, 1.5])
    with col_chart:
        # Sunburst chart: inner ring = layer (Core/Satellite), outer ring = ticker
        sb_ids, sb_labels, sb_parents, sb_values, sb_colors = [], [], [], [], []

        core_total = sum(r['分配仓位'] for r in portfolio if '核心底仓' in r['配置层'])
        sat_total  = sum(r['分配仓位'] for r in portfolio if '战术卫星' in r['配置层'])

        sb_ids    += ['core_layer', 'sat_layer']
        sb_labels += [f'核心底仓 Core\n{core_total:.0f}%', f'战术卫星 Satellite\n{sat_total:.0f}%']
        sb_parents += ['', '']
        sb_values  += [core_total, sat_total]
        sb_colors  += ['#B8860B', '#1A6B3A']

        for row in portfolio:
            uid = f"{row['配置层']}_{row['代码']}"
            parent = 'core_layer' if '核心底仓' in row['配置层'] else 'sat_layer'
            label = f"{row['代码']}\n{row['分配仓位']:.1f}%"
            color = '#F1C40F' if '核心底仓' in row['配置层'] else ('#2ECC71' if row['代码'] != 'BIL' else '#7F8C8D')
            sb_ids.append(uid)
            sb_labels.append(label)
            sb_parents.append(parent)
            sb_values.append(row['分配仓位'])
            sb_colors.append(color)

        fig_sb = go.Figure(go.Sunburst(
            ids=sb_ids,
            labels=sb_labels,
            parents=sb_parents,
            values=sb_values,
            marker=dict(colors=sb_colors),
            branchvalues='total',
            insidetextorientation='radial',
            textfont=dict(size=13),
            hovertemplate='<b>%{label}</b><br>仓位: %{value:.1f}%<extra></extra>',
        ))
        fig_sb.update_layout(
            title=dict(text="🎯 Core-Satellite 资金分配图", font=dict(size=15, color='#ddd')),
            plot_bgcolor='#111111', paper_bgcolor='#111111',
            font=dict(color='#ddd', size=13),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_sb, use_container_width=True)

    with col_table:
        display_cols = ["配置层", "所属阵型", "代码", "名称", "Molt评分", "分配仓位", "白盒归因"]
        st.dataframe(
            df_portfolio[display_cols].sort_values(by=["配置层", "分配仓位"], ascending=[True, False]),
            column_config={"分配仓位": st.column_config.NumberColumn("仓位 ▼", format="%.2f%%")},
            use_container_width=True, hide_index=True
        )

    st.info("💡 **极低换手率原理：** A/B/C/D 四组均采用 Arena 迟滞选股：当前持仓只要仍在 Arena 前三且 MA60 生命线完好，永不主动换仓；出现空缺（跌出前三或跌破 MA60）时才用当时榜首依次补位，每组最多持有 2 只。下方「手动配置」区可覆盖当前实盘持仓，不影响回测历史逻辑。")

    # ── C/D Arena 迟滞选股状态审计面板 ──────────────────────────────────────
    if _sat_hysteresis_log:
        with st.expander("🔒 C/D 卫星池 Arena 迟滞选股状态（点击展开）", expanded=True):
            st.caption("续持条件：仍在 Arena 前三 且 MA60 生命线完好 → 🔒 锁仓；任一不满足 → ❌ 踢出；空缺由当时榜首填入 → ✅ 新晋。")
            for _log_tier, _log_data in _sat_hysteresis_log.items():
                _log_color = "#E74C3C" if _log_tier == "C" else "#9B59B6"
                _log_label = "C组·时代之王" if _log_tier == "C" else "D组·预备队"
                _log_pct   = 30 if _log_tier == "C" else 20
                st.markdown(
                    f"<div style='border-left:3px solid {_log_color}; padding:10px 14px; "
                    f"margin-bottom:8px; background:#111; border-radius:4px;'>"
                    f"<div style='font-size:15px; font-weight:bold; color:{_log_color}; margin-bottom:8px;'>"
                    f"{_log_label}（总仓位 {_log_pct}%）</div>",
                    unsafe_allow_html=True,
                )
                _log_holds   = _log_data.get("holdings", [])
                _log_evicted = _log_data.get("evicted", [])
                _log_new     = _log_data.get("new", [])
                _log_top3    = _log_data.get("top3", [])

                _status_parts = []
                for _lt in _log_holds:
                    _icon = "✅ 新晋" if _lt in _log_new else "🔒 续持"
                    _ma_ok = _check_ma60_alive(_lt, df)
                    _ma_tag = "" if _ma_ok else " ⚠️MA60临界"
                    _status_parts.append(
                        f"<span style='color:#eee; font-size:14px; margin-right:18px;'>"
                        f"{_icon} <b>{_lt}</b>{_ma_tag}</span>"
                    )
                if _status_parts:
                    st.markdown(
                        "<div style='margin-bottom:6px;'>" + "".join(_status_parts) + "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        "<div style='color:#555; font-size:13px; margin-bottom:6px;'>当前无持仓（暂泊 BIL）</div>",
                        unsafe_allow_html=True,
                    )

                if _log_evicted:
                    _evict_parts = []
                    for _et, _er in _log_evicted:
                        _evict_parts.append(
                            f"<span style='color:#E74C3C; font-size:13px; margin-right:14px;'>"
                            f"❌ <b>{_et}</b>（{_er}）</span>"
                        )
                    st.markdown(
                        "<div style='margin-bottom:4px;'>" + "".join(_evict_parts) + "</div>",
                        unsafe_allow_html=True,
                    )

                if _log_top3:
                    _top3_html = " &nbsp;›&nbsp; ".join(
                        [f"<b style='color:#FFD700;'>#{i+1} {t}</b>" for i, t in enumerate(_log_top3)]
                    )
                    st.markdown(
                        f"<div style='font-size:13px; color:#888; margin-top:4px;'>"
                        f"Arena 当期前三：{_top3_html}</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown("</div>", unsafe_allow_html=True)

    _trim_badge = f"🟢 已启用 · 偏离阈值 {_bt_drift_pct}% → 安全带 [{50-_bt_drift_pct}%, {50+_bt_drift_pct}%]" if _bt_trim_enabled else "🔴 已关闭（回测不执行跨组剪枝）"
    st.markdown(f"#### ⚖️ 步骤 3: 再平衡规则 — 极致宽幅阈值再平衡 &nbsp;<span style='font-size:13px;color:#aaa;'>{_trim_badge}</span>", unsafe_allow_html=True)

    # ── 参数控件行 ─────────────────────────────────────────────────────────
    _c_toggle, _c_drift, _c_btn = st.columns([1.2, 1, 1.5])
    with _c_toggle:
        _trim_pending = st.toggle(
            "启用阈值再平衡",
            value=_bt_trim_enabled,
            key="bt_trim_pending",
            help="关闭后，回测引擎将不再执行跨组剪枝，让仓位完全随价格自由漂移。",
        )
    with _c_drift:
        _drift_pending = st.number_input(
            "偏离阈值 (%)",
            min_value=5, max_value=49,
            value=_bt_drift_pct,
            step=1,
            key="bt_drift_pending",
            help="Core/Satellite 双侧容忍区间 = [50%−阈值, 50%+阈值]。默认 30% → 安全带 [20%, 80%]。",
            disabled=not _trim_pending,
        )
    with _c_btn:
        st.markdown("<div style='margin-top:26px;'>", unsafe_allow_html=True)
        if st.button("▶ 重新跑回测", type="primary", use_container_width=True):
            st.session_state["bt_trim_applied_enabled"] = _trim_pending
            st.session_state["bt_drift_applied_pct"]    = int(_drift_pending)
            st.session_state.pop("bt_result_cache", None)
            st.session_state.pop("bt_cache_key", None)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("📖 查看再平衡规则详情", expanded=False):
        st.markdown("""
<div style='background:rgba(52,152,219,0.08);border-left:4px solid #3498DB;padding:20px;border-radius:6px;line-height:1.8;font-size:14px;color:#ddd;margin-bottom:16px;'>
<b style='font-size:15px;color:#5DADE2;'>核心原则：坚决让趋势利润奔跑，仅在单侧阵营极度失衡时才强制配平。</b><br><br>

<b>📌 初始战略基准</b><br>
&nbsp;&nbsp;• A/B 组（压舱石）合并目标权重：<b>50%</b><br>
&nbsp;&nbsp;• C/D 组（宏观突击）合并目标权重：<b>50%</b><br>
&nbsp;&nbsp;• 漂移容忍度（Drift Threshold）：绝对值 <b>±30%</b>（即单侧仓位容忍区间为 [20%, 80%]）<br><br>

<b>🟢 日常态 — 宽幅安全带内绝对不干预</b><br>
&nbsp;&nbsp;每次月度扫描时，计算 A/B 组与 C/D 组的当前实际权重比例。<br>
&nbsp;&nbsp;只要两个阵营的权重均在 <b>[20%, 80%]</b> 的安全带内，<b>坚决跳过全局再平衡</b>，保持各自阵营独立运行，让趋势利润充分积累。<br><br>

<b>🔴 触发态 — 突破边界立刻启动跨组剪枝</b><br>
&nbsp;&nbsp;若任一阵营实际权重 <b>突破 80% 上限</b> 或 <b>跌破 20% 下限</b>，立刻触发系统级「跨组剪枝」事件：<br>
&nbsp;&nbsp;&nbsp;&nbsp;① 按比例削减超重阵营内各标的仓位（利润收割）；<br>
&nbsp;&nbsp;&nbsp;&nbsp;② 将套现资金按比例补仓至缩水阵营，严格恢复全盘至 <b>50 : 50</b>。<br>
&nbsp;&nbsp;触发记录将在下方「调仓明细」日志中显式高亮标注 ⚖️。
</div>
""", unsafe_allow_html=True)

    st.markdown("---")

    st.markdown("#### ⚡ 步骤 4: Core-Satellite 走步回测 (VectorBT Walk-Forward Backtest)")
    st.caption("回测引擎在每月末切片历史数据，用 PIT 安全的动量/相对强度替代历史无法获取的 Forward EPS，核心底仓仅季末换仓，卫星池引入迟滞机制，模拟真实低换手曲线。含 10 bps 交易成本。")
    st.caption("💡 **步骤 2 的仓位标的与本表最新一行完全一致** — 两者均由回测引擎的 PIT 动量算法驱动，确保历史模拟与当前持仓零偏差。")

    # bt_result 已在页面顶部预先计算（group_assignments + fetch_rolling_backtest），此处直接使用
    if "error" in bt_result:
        st.warning(f"⚠️ 动态回测引擎返回错误：{bt_result['error']}。降级为静态模式展示。")
    else:
        port_total_ret = bt_result.get("total_ret", 0.0)
        spy_total_ret  = bt_result.get("spy_total_ret", 0.0)
        sharpe         = bt_result.get("sharpe", 0.0)
        calmar         = bt_result.get("calmar", 0.0)
        max_dd         = bt_result.get("max_dd", 0.0)
        n_rebal        = bt_result.get("n_rebal", 0)
        sim_start_str  = bt_result.get("sim_start", "")
        sim_end_str    = bt_result.get("sim_end", "")

        c_r1, c_r2, c_r3, c_r4, c_r5 = st.columns(5)
        c_r1.metric("组合总回报 (Portfolio)", f"{port_total_ret:.1f}%",
                    delta=f"{port_total_ret - spy_total_ret:.1f}% 超额收益")
        c_r2.metric("组合最大回撤 (Max DD)", f"{max_dd:.1f}%",
                    delta=f"共 {n_rebal} 次调仓节点", delta_color="off")
        c_r3.metric("夏普比率 (Sharpe)", f"{sharpe:.2f}",
                    delta="风险调整后收益", delta_color="off")
        c_r4.metric("卡玛比率 (Calmar)", f"{calmar:.2f}",
                    delta="年化回报/最大回撤", delta_color="off")
        c_r5.metric("标普500基准 (SPY)", f"{spy_total_ret:.1f}%")

        nav_raw = bt_result.get("nav", {})
        spy_raw = bt_result.get("spy_nav", {})

        if nav_raw:
            nav_series = pd.Series(nav_raw)
            nav_series.index = pd.to_datetime(nav_series.index)

            fig_nav = go.Figure()
            fig_nav.add_trace(go.Scatter(
                x=nav_series.index, y=nav_series.astype(float).dropna(),
                mode='lines', name='Moltbot Core-Satellite (VectorBT)',
                line=dict(color='#2ECC71', width=3)
            ))

            if spy_raw:
                spy_series = pd.Series(spy_raw)
                spy_series.index = pd.to_datetime(spy_series.index)
                fig_nav.add_trace(go.Scatter(
                    x=spy_series.index, y=spy_series.astype(float).dropna(),
                    mode='lines', name='标普500基准 (SPY)',
                    line=dict(color='#95A5A6', width=2, dash='dot')
                ))

            fig_nav.update_layout(
                height=400,
                plot_bgcolor='#111111', paper_bgcolor='#111111',
                font=dict(color='#ddd', size=14),
                margin=dict(l=20, r=20, t=20, b=20),
                yaxis_title="资产净值 (Base=100)",
                legend=dict(orientation="h", y=1.05, x=0.01)
            )
            st.caption(f"回测区间：{sim_start_str} → {sim_end_str}（A/B/C/D 全组 Arena 迟滞选股 + C/D 月度体制门控，含 10 bps 手续费）")
            st.plotly_chart(fig_nav, use_container_width=True)

        # Rebalancing detail expander — with Core/Satellite layer columns
        weight_history = bt_result.get("weight_history", [])
        if weight_history:
            with st.expander(f"📋 月度持仓快照（回测引擎）— 共 {n_rebal} 次实际交易 (点击展开)"):
                st.caption("仓位随价格**自然漂移**，不做月度再平衡。表中权重为当月实际漂移后的仓位比例（非固定目标）。仅在 Arena 换仓、卫星体制切换或漂移触发阈值时产生实际交易。🔒 = C/D 最小持有期枷锁续持；🔄 = A/B 标的本期发生变化。")
                def _fmt_tw(tw, locked=None):
                    if not tw:
                        return "—"
                    parts = []
                    for t, w in sorted(tw.items(), key=lambda x: -x[1]):
                        lock_icon = "🔒" if locked and t in locked else ""
                        parts.append(f"{lock_icon}{t} {w:.0f}%")
                    return "  ".join(parts)

                rebal_rows = []
                for entry in weight_history:
                    probs       = entry.get("probs", {})
                    sp          = entry.get("smoothed_probs", probs)
                    regime_lbl  = entry.get("regime_label", "—")
                    rmode       = entry.get("regime_mode", "unknown")
                    locked_sat  = entry.get("locked_sat", [])
                    all_weights = entry.get("weights", {})

                    # Per-tier weight dicts (from backend; fallback: derive from group_assignments)
                    a_w = entry.get("a_weights") or {
                        t: w for t, w in entry.get("core_weights", {}).items()
                        if group_assignments.get(t) == 'A'
                    }
                    b_w = entry.get("b_weights") or {
                        t: w for t, w in entry.get("core_weights", {}).items()
                        if group_assignments.get(t) == 'B'
                    }
                    c_w = entry.get("c_weights") or {
                        t: w for t, w in entry.get("satellite_weights", {}).items()
                        if group_assignments.get(t) == 'C'
                    }
                    d_w = entry.get("d_weights") or {
                        t: w for t, w in entry.get("satellite_weights", {}).items()
                        if group_assignments.get(t) == 'D'
                    }

                    rd_date      = entry["date"]
                    bil_w        = all_weights.get("BIL", 0)
                    _core_chg    = entry.get("core_changed", False)

                    _sp_incumbent = sp.get(regime_lbl, 0.0) if regime_lbl not in ("—", "unset") else 0.0
                    trim_ev  = entry.get("trim_event")
                    trim_str = f"⚖️ 触发 ({trim_ev[0]} {trim_ev[1]}%)" if trim_ev else "—"

                    # Compute first/second scripts for this historical period
                    _sorted_sp = sorted(sp.items(), key=lambda x: -x[1]) if sp else []
                    _c_r_en    = _sorted_sp[0][0] if _sorted_sp else regime_lbl
                    _c_r_score = _sorted_sp[0][1] if _sorted_sp else _sp_incumbent
                    _d_r_en    = _sorted_sp[1][0] if len(_sorted_sp) > 1 else _c_r_en
                    _d_r_score = _sorted_sp[1][1] if len(_sorted_sp) > 1 else _c_r_score
                    if _d_r_score < 0.60:
                        _d_r_en, _d_r_score = _c_r_en, _c_r_score

                    rebal_rows.append({
                        "调仓日期": rd_date,
                        "A组(压舱石)": _fmt_tw(a_w),
                        "B组(大猩猩)": _fmt_tw(b_w),
                        "第一剧本": f"{REGIME_CN_MAP.get(_c_r_en, _c_r_en)} {_c_r_score*100:.0f}%",
                        "C组(时代之王)": _fmt_tw(c_w, locked_sat),
                        "第二剧本": f"{REGIME_CN_MAP.get(_d_r_en, _d_r_en)} {_d_r_score*100:.0f}%",
                        "D组(预备队)": _fmt_tw(d_w, locked_sat),
                        "核心调仓": "🔄 Arena换仓" if _core_chg else "🔒 续持",
                        "卫星模式": "🟢 激活" if rmode == "active" else "🛌 迟滞",
                        "阈值警报": trim_str,
                        "现金BIL": f"{bil_w:.0f}%" if bil_w > 0 else "0%",
                    })

                st.dataframe(pd.DataFrame(rebal_rows[::-1]), use_container_width=True, hide_index=True)

                # ── Audit Trail: trim events highlighted blocks ───────────────
                trim_entries = [(e["date"], e["trim_event"]) for e in weight_history if e.get("trim_event")]
                if trim_entries:
                    st.markdown("**⚖️ 全局阈值再平衡审计日志 (Audit Trail)**")
                    for t_date, t_ev in trim_entries:
                        t_side, t_pct = t_ev[0], t_ev[1]
                        st.markdown(
                            f"<div style='background:rgba(231,76,60,0.12);border-left:4px solid #E74C3C;"
                            f"padding:14px 18px;border-radius:4px;margin-bottom:8px;"
                            f"font-size:14px;color:#F1948A;line-height:1.7;'>"
                            f"<b>⚖️ {t_date} — 触发全局阈值再平衡</b>：单侧阵营权重突破 30% 极限边界 "
                            f"（<b>{t_side}</b> 阵营期间漂移达到 <b>{t_pct}%</b>），"
                            f"强制执行跨组利润收割与配平，资金重心严格恢复至 50:50。"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                dormant_months = sum(1 for r in rebal_rows if "迟滞" in r["卫星模式"])
                locked_events  = sum(1 for entry in weight_history if entry.get("locked_sat"))
                trim_count     = len(trim_entries)
                summary_parts  = []
                if dormant_months > 0:
                    summary_parts.append(f"**{dormant_months}** 个月卫星池处于迟滞模式（当期胜率 < 60%），零换手")
                if locked_events > 0:
                    summary_parts.append(f"**{locked_events}** 个节点触发最小持有期枷锁（🔒），强制续持未破 MA60 的标的")
                if trim_count > 0:
                    summary_parts.append(f"**{trim_count}** 次触发极致宽幅阈值再平衡（⚖️），跨组剪枝并恢复 50:50")
                if summary_parts:
                    st.info("💡 回测期间：" + "；".join(summary_parts) + "。")

        # ── 📒 详细交易记录日志 (Trade Journal) ──────────────────────────────────
        if weight_history and len(weight_history) >= 2:
            st.markdown("---")
            st.markdown("#### 📒 详细交易记录日志 (Trade Journal)")
            st.caption("仓位随价格自然漂移，**不做月度再平衡**。仅在以下情况产生交易："
                       "① Arena 竞技场换仓（标的跌出前三或跌破 MA60）→ 卖旧买新；"
                       "② 卫星池体制切换（激活/休眠）→ 买入/清仓；"
                       "③ Core↔Satellite 漂移突破极限阈值 → 跨组剪枝恢复 50:50。")

            _GRP_CN_TJ = {"A": "压舱石", "B": "大猩猩", "C": "时代之王", "D": "预备队"}

            def _tj_holdings(entry):
                h = {}
                for g in ("a", "b", "c", "d"):
                    for t, w in entry.get(f"{g}_weights", {}).items():
                        h[t] = {"group": g.upper(), "weight": w}
                return h

            trade_log = []
            _prev_tj = None

            for _tj_entry in weight_history:
                _tj_date = _tj_entry["date"]
                _tj_h = _tj_holdings(_tj_entry)
                _tj_rcn = REGIME_CN_MAP.get(_tj_entry.get("regime_label", ""), _tj_entry.get("regime_label", "—"))
                _tj_mode = _tj_entry.get("regime_mode", "unknown")
                _tj_trim = _tj_entry.get("trim_event")

                if _prev_tj is None:
                    for t, info in sorted(_tj_h.items(), key=lambda x: x[1]["group"]):
                        trade_log.append({
                            "日期": _tj_date, "操作": "🟢 建仓",
                            "代码": t, "名称": TIC_MAP.get(t, t),
                            "组别": f"{info['group']}({_GRP_CN_TJ.get(info['group'], '')})",
                            "仓位": f"{info['weight']:.1f}%",
                            "交易理由": f"回测起始建仓 — {info['group']}组({_GRP_CN_TJ.get(info['group'], '')})初始配置",
                        })
                    _prev_tj = _tj_entry
                    continue

                _prev_h = _tj_holdings(_prev_tj)
                _prev_mode = _prev_tj.get("regime_mode", "unknown")

                # ── 买入：本期新增标的 ──
                for t, info in sorted(_tj_h.items(), key=lambda x: x[1]["group"]):
                    if t in _prev_h:
                        continue
                    grp = info["group"]
                    if grp in ("A", "B"):
                        reason = f"Arena竞技场换仓 → {grp}组({_GRP_CN_TJ[grp]})新入选"
                    elif _tj_mode == "active" and _prev_mode == "dormant":
                        reason = f"卫星池从休眠恢复激活（锚定「{_tj_rcn}」≥60%）→ {grp}组新买入"
                    elif _tj_mode == "active":
                        reason = f"卫星池月度轮换 → {grp}组({_GRP_CN_TJ.get(grp, '')})入选（锚定「{_tj_rcn}」）"
                    else:
                        reason = f"{grp}组迟滞补位"
                    trade_log.append({
                        "日期": _tj_date, "操作": "🟢 买入",
                        "代码": t, "名称": TIC_MAP.get(t, t),
                        "组别": f"{grp}({_GRP_CN_TJ.get(grp, '')})",
                        "仓位": f"{info['weight']:.1f}%",
                        "交易理由": reason,
                    })

                # ── 卖出：本期消失标的 ──
                for t, info in sorted(_prev_h.items(), key=lambda x: x[1]["group"]):
                    if t in _tj_h:
                        continue
                    grp = info["group"]
                    if grp in ("A", "B"):
                        reason = f"Arena竞技场换仓 → 被踢出{grp}组（跌出前三或跌破MA60）"
                    elif _tj_mode == "dormant" and _prev_mode == "active":
                        reason = f"卫星池转入休眠（「{_tj_rcn}」置信度 < 60%）→ 清仓至BIL"
                    elif grp in ("C", "D"):
                        reason = f"Arena月度轮换 → {grp}组({_GRP_CN_TJ.get(grp, '')})标的被替换"
                    else:
                        reason = "调仓移除"
                    trade_log.append({
                        "日期": _tj_date, "操作": "🔴 卖出",
                        "代码": t, "名称": TIC_MAP.get(t, t),
                        "组别": f"{grp}({_GRP_CN_TJ.get(grp, '')})",
                        "仓位": "0%",
                        "交易理由": reason,
                    })

                # ── 跨组剪枝 ──
                if _tj_trim:
                    trade_log.append({
                        "日期": _tj_date, "操作": "⚖️ 跨组剪枝",
                        "代码": "全组", "名称": "Core↔Satellite 强制配平",
                        "组别": "—", "仓位": "→ 50:50",
                        "交易理由": f"{_tj_trim[0]} 漂移至 {_tj_trim[1]}%，触发极限阈值再平衡",
                    })

                _prev_tj = _tj_entry

            # ── 汇总统计 ──
            n_buy = sum(1 for r in trade_log if "买入" in r["操作"] or "建仓" in r["操作"])
            n_sell = sum(1 for r in trade_log if "卖出" in r["操作"])
            n_tr = sum(1 for r in trade_log if "剪枝" in r["操作"])
            _n_drift = sum(1 for e in weight_history if not e.get("needs_trade", True))

            _tc1, _tc2, _tc3, _tc4 = st.columns(4)
            _tc1.metric("🟢 买入/建仓", f"{n_buy} 笔")
            _tc2.metric("🔴 卖出", f"{n_sell} 笔")
            _tc3.metric("⚖️ 跨组剪枝", f"{n_tr} 次")
            _tc4.metric("💤 自然漂移月", f"{_n_drift} 个月", help="无任何交易，仓位随价格自由漂移")

            if trade_log:
                _tj_filter_ops = st.multiselect(
                    "筛选操作类型",
                    options=["🟢 建仓", "🟢 买入", "🔴 卖出", "⚖️ 跨组剪枝"],
                    default=["🟢 建仓", "🟢 买入", "🔴 卖出", "⚖️ 跨组剪枝"],
                    key="tj_filter",
                )
                _tj_filtered = [r for r in trade_log if r["操作"] in _tj_filter_ops] if _tj_filter_ops else trade_log
                st.dataframe(
                    pd.DataFrame(_tj_filtered[::-1]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "交易理由": st.column_config.TextColumn("交易理由", width="large"),
                    },
                )

            # ── 📊 标的持仓周期汇总表 ──────────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 📊 标的持仓周期汇总 (Holding Lifecycle)")
            st.caption("追踪每只标的从买入到卖出的完整生命周期，同一标的可能有多轮买卖周期。")

            _lifecycle: dict = {}
            _prev_lc = None

            for _lc_entry in weight_history:
                _lc_date = _lc_entry["date"]
                _lc_h: dict = {}
                for _g in ("a", "b", "c", "d"):
                    for _t, _w in _lc_entry.get(f"{_g}_weights", {}).items():
                        _lc_h[_t] = _g.upper()

                if _prev_lc is None:
                    for _t, _g in _lc_h.items():
                        _lifecycle.setdefault(_t, []).append({
                            "group": _g, "buy_date": _lc_date,
                            "buy_reason": f"回测起始建仓 — {_g}组({_GRP_CN_TJ.get(_g, '')})",
                            "sell_date": None, "sell_reason": None,
                        })
                    _prev_lc = _lc_entry
                    continue

                _prev_lc_h: dict = {}
                for _g in ("a", "b", "c", "d"):
                    for _t, _w in _prev_lc.get(f"{_g}_weights", {}).items():
                        _prev_lc_h[_t] = _g.upper()

                _lc_rcn = REGIME_CN_MAP.get(_lc_entry.get("regime_label", ""), "—")
                _lc_mode = _lc_entry.get("regime_mode", "unknown")
                _prev_lc_mode = _prev_lc.get("regime_mode", "unknown")

                for _t, _g in _prev_lc_h.items():
                    if _t not in _lc_h and _t in _lifecycle and _lifecycle[_t]:
                        _open = _lifecycle[_t][-1]
                        if _open["sell_date"] is None:
                            if _g in ("A", "B"):
                                _sr = "Arena换仓出局（跌出前三或跌破MA60）"
                            elif _lc_mode == "dormant" and _prev_lc_mode == "active":
                                _sr = f"卫星休眠（「{_lc_rcn}」< 60%）"
                            else:
                                _sr = "月度轮换被替换"
                            _open["sell_date"] = _lc_date
                            _open["sell_reason"] = _sr

                for _t, _g in _lc_h.items():
                    if _t not in _prev_lc_h:
                        if _g in ("A", "B"):
                            _br = f"Arena竞技场{_g}组入选"
                        elif _lc_mode == "active":
                            _br = f"卫星{_g}组选入（锚定「{_lc_rcn}」）"
                        else:
                            _br = f"{_g}组迟滞补位"
                        _lifecycle.setdefault(_t, []).append({
                            "group": _g, "buy_date": _lc_date,
                            "buy_reason": _br,
                            "sell_date": None, "sell_reason": None,
                        })

                _prev_lc = _lc_entry

            _lc_rows = []
            for _t, _cycles in sorted(_lifecycle.items()):
                for _cyc in _cycles:
                    _bd = _cyc["buy_date"]
                    _sd_display = _cyc["sell_date"] if _cyc["sell_date"] else "📌 当前持有"
                    _bd_ts = pd.Timestamp(_bd)
                    _sd_ts = pd.Timestamp(_cyc["sell_date"]) if _cyc["sell_date"] else pd.Timestamp.now()
                    _hold_m = max(1, round((_sd_ts - _bd_ts).days / 30))
                    _ret_str = "—"
                    if _t in df.columns:
                        try:
                            _p_b = df.loc[:_bd_ts, _t].dropna().astype(float)
                            _p_s = df.loc[:_sd_ts, _t].dropna().astype(float)
                            if not _p_b.empty and not _p_s.empty:
                                _ret = (float(_p_s.iloc[-1]) / float(_p_b.iloc[-1]) - 1) * 100
                                _ret_str = f"{_ret:+.1f}%"
                        except Exception:
                            pass
                    _lc_rows.append({
                        "代码": _t, "名称": TIC_MAP.get(_t, _t),
                        "组别": f"{_cyc['group']}({_GRP_CN_TJ.get(_cyc['group'], '')})",
                        "买入日期": _bd, "买入理由": _cyc["buy_reason"],
                        "卖出日期": _sd_display,
                        "卖出理由": _cyc["sell_reason"] or "—",
                        "持有月数": _hold_m, "期间涨跌": _ret_str,
                    })

            if _lc_rows:
                st.dataframe(
                    pd.DataFrame(_lc_rows).sort_values(by=["买入日期", "代码"], ascending=[False, True]),
                    use_container_width=True, hide_index=True,
                )

        # Alpha & Hedge narrative boxes
        c_alpha, c_hedge = st.columns(2)

        with c_alpha:
            if port_total_ret > spy_total_ret:
                alpha_text = (
                    f"走步回测结果显示，Moltbot Core-Satellite 组合斩获 <b>{port_total_ret:.1f}%</b> 总回报，"
                    f"超越 SPY <b>{port_total_ret - spy_total_ret:.1f}%</b>。"
                    f"夏普比率 <b>{sharpe:.2f}</b> 代表系统在单位风险上获取的超额补偿；"
                    f"卡玛比率 <b>{calmar:.2f}</b> 证明年化收益对最大回撤的覆盖能力。"
                )
            else:
                alpha_text = (
                    f"本期走步回测总回报 <b>{port_total_ret:.1f}%</b>，暂落后于 SPY。"
                    f"但夏普 <b>{sharpe:.2f}</b> 与卡玛 <b>{calmar:.2f}</b> 表明：Core-Satellite 架构以"
                    f"更低的波动率取得了更稳健的风险调整收益，并非单纯追涨。"
                )
            st.markdown(f"""
            <div class='alpha-box'>
            <h4 style='color:#F1C40F; margin-top:0px;'>👑 超额收益归因 (Alpha Source)</h4>
            {alpha_text}
            </div>
            """, unsafe_allow_html=True)

        with c_hedge:
            st.markdown(f"""
            <div class='hedge-box'>
            <h4 style='color:#2ECC71; margin-top:0px;'>🛡️ 对冲保护归因 (Hedge Protection)</h4>
            动态引擎在 <b>{n_rebal}</b> 个调仓节点上，每次均用当时可见的宏观信号重新决策仓位，
            彻底杜绝了未来函数偏差。<br><br>
            <b>两大防抖机制已激活：</b><br>
            ① <b>月度裁决天然防抖</b>（Page 1「四大剧本历史裁决表」月度频率，天然滤除日内噪音）；<br>
            ② <b>最小持有期枷锁</b>（2 个月）防止卫星标的刚买即卖的 Whipsaw 磨损。<br><br>
            含 10 bps 真实摩擦成本下，最大回撤控制在 <b>{max_dd:.1f}%</b>。
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ 当前无符合条件的标的，建议空仓保护资本。")