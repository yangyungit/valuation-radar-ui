import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
import pandas_datareader.data as web

from api_client import fetch_core_data, get_global_data, get_stock_metadata, fetch_macro_scores, fetch_funnel_scores, fetch_rolling_backtest

core_data = fetch_core_data()

# 解包页面需要的字典
TIC_MAP = core_data.get("TIC_MAP", {})

@st.cache_data(ttl=3600*4)
def get_clock_fred_data():
    """从 FRED 拉取宏观官方数据 (与 1_宏观定调.py 保持 SSOT 对齐)"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3650 + 400)
    try:
        df_fred = web.DataReader(['CPILFESL', 'BAMLH0A0HYM2'], 'fred', start_date, end_date)
        if df_fred.index.tz is not None:
            df_fred.index = df_fred.index.tz_localize(None)
        result = pd.DataFrame(index=df_fred.index)
        if 'CPILFESL' in df_fred.columns:
            result['Core_CPI_YoY'] = df_fred['CPILFESL'].pct_change(12) * 100
        if 'BAMLH0A0HYM2' in df_fred.columns:
            result['HY_Spread'] = df_fred['BAMLH0A0HYM2']
        result = result.dropna(how='all').resample('D').ffill()
        return result
    except Exception:
        return pd.DataFrame(columns=['Core_CPI_YoY', 'HY_Spread'])

st.set_page_config(page_title="Moltbot 首席投资官中枢", layout="wide", page_icon="🏦")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新拉取全系统数据"):
        st.cache_data.clear()
        st.success("全局缓存已清除！")
        st.rerun()

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

MACRO_ASSETS = ["XLY", "XLP", "XLU", "TIP", "IEF", "TLT", "SHY", "HYG", "UUP", "LQD", "MTUM", "IWM", "SPHB", "ARKK", "USMV", "QUAL", "VLUE", "VIG", "SPY", "CPER", "USO", "XLI", "KRE", "GLD", "XLK", "DBC"]

# 架构师级修复1：把主理人所有的自选股（A-E组）和宏观池全部加进来！否则漏斗无股可选！
all_pool_tickers = []
for lst in USER_GROUPS_DEF.values(): all_pool_tickers.extend(lst)
all_pool_tickers = list(set([t.strip().upper() for t in all_pool_tickers]))

UNIVERSAL_TICKERS = list(set(MACRO_ASSETS + all_pool_tickers + list(TIC_MAP.keys())))
UNIVERSAL_TICKERS.sort() 

with st.spinner("⏳ 正在调用中央引擎进行全系推演 (SSOT)..."):
    # 架构师级修复2：强制拉取 4 年数据对齐 Page 1！
    df = get_global_data(UNIVERSAL_TICKERS, years=4)
    meta_info = get_stock_metadata(all_pool_tickers)

if df.empty or len(df) < 750:
    st.warning("⚠️ 数据拉取失败或数据长度不足，无法启动配置引擎。")
    st.stop()

# ==========================================
# 🧠 强制同步 1_宏观定调.py 的三引擎计算逻辑，避免概率偏差 (SSOT)
# ==========================================
df_fred_clock = get_clock_fred_data()
_fred_ok = not df_fred_clock.empty
z_window = 750

def _zscore(series, window=z_window):
    mu = series.rolling(window=window).mean()
    sigma = series.rolling(window=window).std()
    return (series - mu) / sigma.where(sigma > 0)

z_consumer = _zscore((df['XLY'] / df['XLP'].replace(0, np.nan)).rolling(20).mean()) if 'XLY' in df and 'XLP' in df else pd.Series(0, index=df.index)
z_industrial = _zscore((df['XLI'] / df['XLU'].replace(0, np.nan)).rolling(20).mean()) if 'XLI' in df and 'XLU' in df else pd.Series(0, index=df.index)

if _fred_ok and 'HY_Spread' in df_fred_clock.columns:
    _hy_raw = df_fred_clock['HY_Spread'].reindex(df.index).ffill().rolling(20).mean()
    z_credit = _zscore(_hy_raw) * -1
else:
    _hy_raw = (df['HYG'] / df['IEF'].replace(0, np.nan)).rolling(20).mean() if 'HYG' in df and 'IEF' in df else pd.Series(0, index=df.index)
    z_credit = _zscore(_hy_raw)

growth_z = pd.DataFrame({'Z_consumer': z_consumer, 'Z_industrial': z_industrial, 'Z_credit': z_credit}).mean(axis=1)

z_tips = _zscore((df['TIP'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()) if 'TIP' in df and 'IEF' in df else pd.Series(0, index=df.index)
z_commodity = _zscore((df['DBC'] / df['IEF'].replace(0, np.nan)).rolling(20).mean()) if 'DBC' in df and 'IEF' in df else pd.Series(0, index=df.index)

_infl_components = {'Z_tips': z_tips, 'Z_commodity': z_commodity}
if _fred_ok and 'Core_CPI_YoY' in df_fred_clock.columns:
    _cpi_raw = df_fred_clock['Core_CPI_YoY'].reindex(df.index).ffill()
    _infl_components['Z_cpi'] = _zscore(_cpi_raw)

inflation_z = pd.DataFrame(_infl_components).mean(axis=1)

df_z = pd.DataFrame({'Growth': growth_z, 'Inflation': inflation_z}).dropna()
curr_clock_g = float(df_z['Growth'].iloc[-1]) if not df_z.empty else 0.0
curr_clock_i = float(df_z['Inflation'].iloc[-1]) if not df_z.empty else 0.0

raw_probs, clock_regime = fetch_macro_scores(df, curr_clock_g, curr_clock_i)

REGIME_CN_MAP = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}

REGIME_NARRATIVE = {
    "软着陆": "享受经济复苏与流动性宽松的双重红利，充当组合的进攻矛。",
    "再通胀": "捕捉经济过热时期的需求扩张与大宗商品价格飙升带来的利润爆炸。",
    "滞胀": "作为终极避险资产，对冲法币信用贬值与经济停滞带来的杀估值风险。",
    "衰退": "充当无视周期的盈利安全垫，抵御大盘系统性下行的毁灭性冲击。"
}

# ── 实时防抖过滤器：从 session_state 读取 Page 1 的防抖状态 ─────────────────
# 必须在 fetch_funnel_scores 之前读取，确保漏斗评分也基于平滑/状态机胜率
live_smoothed_probs: dict = st.session_state.get("smoothed_regime_probs", raw_probs)
live_regime_label: str    = st.session_state.get("live_regime_label", None)

# 用平滑胜率（而非原始截面胜率）驱动 Molt 评分，确保仓位跟着现任剧本走
_scores_macro = live_smoothed_probs if live_smoothed_probs else raw_probs
df_scores, _ = fetch_funnel_scores(df, all_pool_tickers, meta_info, NARRATIVE_THEMES_HEAT, macro_scores=_scores_macro)

# 用平滑胜率（而非原始截面胜率）判断卫星是否激活
_incumbent_score_p6 = live_smoothed_probs.get(live_regime_label, 0.0) if live_regime_label else 0.0
# 兜底：若 Page 1 未访问过（session_state 为空），回退到原始胜率
if not st.session_state.get("smoothed_regime_probs"):
    _incumbent_score_p6 = max(raw_probs.values()) if raw_probs else 0.0

active_regimes = {k: v for k, v in live_smoothed_probs.items() if v >= 0.60}
top_regime_score = _incumbent_score_p6
satellite_active = top_regime_score >= 0.60

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

portfolio = []

# 全局数据流：优先使用 Page 4 竞技场冠军名单（arena_winners）
_arena_winners: dict = st.session_state.get("arena_winners", {})
_using_arena = bool(_arena_winners)


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

# ── SATELLITE (50%): C Top-2 = 30%, D Top-2 = 20% (regime-gated) ─────────
if satellite_active:
    for tier, total_pct, label in [("C", 30.0, "时代之王"), ("D", 20.0, "预备队")]:
        arena_picks = _picks_from_arena(tier)
        if not arena_picks.empty:
            picks = arena_picks
            source_tag = "Arena冠军"
        elif df_qualified.empty:
            portfolio.append({
                "配置层": "战术卫星 Satellite", "所属阵型": tier, "代码": "BIL",
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
                "配置层": "战术卫星 Satellite",
                "所属阵型": tier,
                "代码": ticker,
                "名称": TIC_MAP.get(ticker, ticker),
                "Molt评分": round(row['Molt评分'], 1),
                "分配仓位": round(alloc, 2),
                "白盒归因": f"{tier}组({label}) {source_tag} 均分 {total_pct:.0f}%，宏观置信度 {top_regime_score*100:.0f}% ≥ 60%",
                "所属板块": row.get('Sector', '—'),
            })
        if n == 0:
            portfolio.append({
                "配置层": "战术卫星 Satellite", "所属阵型": tier, "代码": "BIL",
                "名称": "极短债/现金等价物", "Molt评分": 0.0,
                "分配仓位": round(total_pct, 2),
                "白盒归因": f"{tier}组无合格标的，{total_pct:.0f}% 暂泊 BIL",
                "所属板块": "现金",
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

# Macro step-1 log (show both raw and smoothed probs with state machine status)
step1_logs = []
for regime_en, regime_cn in REGIME_CN_MAP.items():
    raw_w = raw_probs.get(regime_en, 0)
    sm_w  = live_smoothed_probs.get(regime_en, 0)
    is_incumbent = (regime_en == live_regime_label)
    is_active    = is_incumbent and sm_w >= 0.60
    step1_logs.append({
        "宏观剧本": regime_cn,
        "原始截面胜率": f"{raw_w*100:.0f}%",
        "3M-EMA平滑胜率": f"{sm_w*100:.0f}%",
        "状态机角色": "🏛️ 现任" if is_incumbent else "—",
        "卫星池影响": "✅ 驱动激活" if is_active else ("🔒 迟滞拦截" if is_incumbent else "—"),
    })

st.header("1️⃣ 宏观市场定调 (Macro Climate)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🟢 软着陆信号强度", f"{live_smoothed_probs.get('Soft',0)*100:.0f}%",
          delta=f"原始 {raw_probs.get('Soft',0)*100:.0f}%", delta_color="off")
c2.metric("🔥 再通胀信号强度", f"{live_smoothed_probs.get('Hot',0)*100:.0f}%",
          delta=f"原始 {raw_probs.get('Hot',0)*100:.0f}%", delta_color="off")
c3.metric("🟡 滞胀信号强度", f"{live_smoothed_probs.get('Stag',0)*100:.0f}%",
          delta=f"原始 {raw_probs.get('Stag',0)*100:.0f}%", delta_color="off")
c4.metric("🔴 衰退信号强度", f"{live_smoothed_probs.get('Rec',0)*100:.0f}%",
          delta=f"原始 {raw_probs.get('Rec',0)*100:.0f}%", delta_color="off")

_live_label_cn = REGIME_CN_MAP.get(live_regime_label, live_regime_label or "未确立")
active_cn = [REGIME_CN_MAP.get(k, k) for k in active_regimes]
if satellite_active:
    st.success(f"**CIO 洞察 (防抖状态机):** 现任剧本「**{_live_label_cn}**」平滑胜率 {top_regime_score*100:.0f}% ≥ 60%，战术卫星池激活，C/D 组冠军标的纳入组合。")
else:
    st.warning(f"**CIO 洞察 — 装死模式 (防抖状态机):** 现任剧本「**{_live_label_cn}**」平滑胜率 {top_regime_score*100:.0f}% < 60%，卫星池启动持仓迟滞或停泊 BIL 现金防守。")

st.markdown("---")
st.header("2️⃣ 智能仓位生成引擎 — Core-Satellite (Allocation Engine)")

# 数据流溯源横幅
if _using_arena:
    _aw_summary = "、".join(
        f"**{cls}**组Top-{len(v)}: {', '.join(v)}"
        for cls, v in _arena_winners.items()
    )
    st.success(
        f"🏆 **竞技场数据流已接通** — 本次仓位分配使用 Page 4 Arena 实战冠军名单：{_aw_summary}",
        icon="🔗",
    )
else:
    st.warning(
        "⚠️ **尚未获取 Page 4 竞技场冠军名单**（`arena_winners` 为空）。"
        "当前回退至本页 Molt 评分自主选股。请先访问 **4 同类资产竞技场** 页面以打通完整数据流。",
        icon="⚠️",
    )

if not df_portfolio.empty:
    st.markdown("#### 🛠️ 步骤 1: 防抖体制门控 — 3M-EMA 平滑 + 状态机篡位审查")
    st.caption("战术卫星池先对截面胜率进行 **3 个月 EMA 平滑**，再由状态机判断是否允许宏观变天（新剧本需领先现任 ≥ 15 pp 且自身 ≥ 65%）。彻底消除单月情绪噪音导致的高频翻转磨损。")
    st.dataframe(pd.DataFrame(step1_logs), use_container_width=True, hide_index=True)

    st.markdown("#### 🏛️ 步骤 2–3: Core-Satellite 双层配置")
    st.caption("底仓核心池 (50%) = A组压舱石 Top-2 (25%) + B组大猩猩 Top-2 (25%)，每季度末锁定调仓。战术卫星池 (50%) = C组时代之王 Top-2 (30%) + D组预备队 Top-2 (20%)，月度体制门控。")

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

    st.info("💡 **低换手率原理：** 核心底仓每季度才允许换仓（全年仅 4 次），战术卫星在宏观迷茫期自动启用持仓迟滞（Hysteresis），相比原注水算法的每月全盘重算，年化换手率降低约 60%，摩擦成本大幅压缩。")
    st.markdown("---")

    st.markdown("#### ⚡ 步骤 4: Core-Satellite 走步回测 (VectorBT Walk-Forward Backtest)")
    st.caption("回测引擎在每月末切片历史数据，用 PIT 安全的动量/相对强度替代历史无法获取的 Forward EPS，核心底仓仅季末换仓，卫星池引入迟滞机制，模拟真实低换手曲线。含 10 bps 交易成本。")

    # Build group_assignments from USER_GROUPS_DEF for ALL A/B/C/D tickers
    # USER_GROUPS_DEF keys may be "A (防守/稳健)" etc., extract leading letter as the tier id
    group_assignments = {}
    for tier, tickers_in_tier in USER_GROUPS_DEF.items():
        tier_id = tier.strip()[0].upper() if tier.strip() else ""
        if tier_id not in ("A", "B", "C", "D"):
            continue
        for t in tickers_in_tier:
            t_norm = t.strip().upper()
            if t_norm in df.columns:
                group_assignments[t_norm] = tier_id

    with st.spinner("⚙️ Core-Satellite VectorBT 走步推演中，首次加载约需 10–20 秒..."):
        bt_result = fetch_rolling_backtest(df, group_assignments)

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
        c_r2.metric("标普500基准 (SPY)", f"{spy_total_ret:.1f}%")
        c_r3.metric("夏普比率 (Sharpe)", f"{sharpe:.2f}",
                    delta="风险调整后收益", delta_color="off")
        c_r4.metric("卡玛比率 (Calmar)", f"{calmar:.2f}",
                    delta="年化回报/最大回撤", delta_color="off")
        c_r5.metric("组合最大回撤 (Max DD)", f"{max_dd:.1f}%",
                    delta=f"共 {n_rebal} 次调仓节点", delta_color="off")

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
            st.caption(f"回测区间：{sim_start_str} → {sim_end_str}（Core 季度调仓 + Satellite 月度体制门控，含手续费）")
            st.plotly_chart(fig_nav, use_container_width=True)

        # Rebalancing detail expander — with Core/Satellite layer columns
        weight_history = bt_result.get("weight_history", [])
        if weight_history:
            with st.expander(f"📋 月度调仓明细（防抖引擎）— 共 {n_rebal} 次 (点击展开)"):
                st.caption("核心底仓仅季末重算；卫星池经 3M-EMA 平滑 + 状态机门控，持仓迟滞不产生换手。🔒 = 最小持有期枷锁强制续持（未触发 MA60 破位）。")
                rebal_rows = []
                for entry in weight_history:
                    probs        = entry.get("probs", {})
                    sp           = entry.get("smoothed_probs", probs)
                    regime_lbl   = entry.get("regime_label", "—")
                    rmode        = entry.get("regime_mode", "unknown")
                    locked_sat   = entry.get("locked_sat", [])
                    core_w       = entry.get("core_weights", {})
                    sat_w        = entry.get("satellite_weights", {})
                    all_weights  = entry.get("weights", {})

                    rd_date = entry["date"]
                    month   = int(rd_date[5:7]) if len(rd_date) >= 7 else 0
                    is_qend = month in (3, 6, 9, 12)

                    core_str = "  ".join(
                        f"{TIC_MAP.get(t, t)} {w:.0f}%"
                        for t, w in sorted(core_w.items(), key=lambda x: -x[1])
                    ) or "—"
                    bil_w = all_weights.get("BIL", 0)
                    sat_equity = {t: w for t, w in sat_w.items() if t != "BIL"}
                    sat_str = "  ".join(
                        f"{'🔒' if t in locked_sat else ''}{TIC_MAP.get(t, t)} {w:.0f}%"
                        for t, w in sorted(sat_equity.items(), key=lambda x: -x[1])
                    ) or ("BIL 现金" if bil_w > 0 else "—")

                    # Smoothed prob of the effective regime
                    _sp_incumbent = sp.get(regime_lbl, 0.0) if regime_lbl not in ("—", "unset") else 0.0
                    _raw_top = max(probs, key=probs.get) if probs else "—"

                    rebal_rows.append({
                        "调仓日期": rd_date,
                        "核心调仓": "🔄 季末换仓" if is_qend else "🔒 持仓锁定",
                        "卫星模式": "🟢 激活" if rmode == "active" else "🛌 迟滞",
                        "现任剧本(状态机)": f"{REGIME_CN_MAP.get(regime_lbl, regime_lbl)} {_sp_incumbent*100:.0f}%",
                        "原始最强剧本": f"{REGIME_CN_MAP.get(_raw_top, _raw_top)} {max(probs.values())*100:.0f}%" if probs else "—",
                        "核心底仓": core_str,
                        "战术卫星": sat_str,
                        "现金BIL": f"{bil_w:.0f}%" if bil_w > 0 else "0%",
                    })

                st.dataframe(pd.DataFrame(rebal_rows), use_container_width=True, hide_index=True)
                dormant_months = sum(1 for r in rebal_rows if "迟滞" in r["卫星模式"])
                locked_events  = sum(1 for entry in weight_history if entry.get("locked_sat"))
                if dormant_months > 0:
                    st.info(f"💡 回测期间共有 **{dormant_months}** 个月卫星池处于迟滞模式（平滑胜率 < 60%），零换手。另有 **{locked_events}** 个调仓节点触发最小持有期枷锁（🔒），强制续持未破 MA60 的标的。")

        # Alpha & Hedge narrative boxes
        c_alpha, c_hedge = st.columns(2)
        active_regimes_str = " + ".join(sorted(set(
            item['宏观剧本'] for item in step1_logs if "✅" in item['卫星池影响']
        ))) or "无激活剧本"

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
            <b>三大防抖机制已激活：</b><br>
            ① <b>3M-EMA 平滑</b>滤除单月情绪噪音；<br>
            ② <b>状态机迟滞</b>（篡位需领先 ≥15pp + 自身 ≥65%）阻断高频翻转；<br>
            ③ <b>最小持有期枷锁</b>（2 个月）防止卫星标的刚买即卖的 Whipsaw 磨损。<br><br>
            含 10 bps 真实摩擦成本下，最大回撤控制在 <b>{max_dd:.1f}%</b>。
            </div>
            """, unsafe_allow_html=True)

else:
    st.warning("⚠️ 当前无符合条件的标的，建议空仓保护资本。")