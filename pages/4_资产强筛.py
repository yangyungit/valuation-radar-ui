import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

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
        "weights": {"bullish": 0.40, "z_score": 0.30, "mom20": 0.30},
        "invert_z": False,
        "factor_labels": {
            "bullish": "低回撤防线 (MA结构坚实)",
            "z_score": "派息可持续性 (估值稳健)",
            "mom20":   "长周期索提诺 (平稳正向动能)",
        },
        "logic": (
            "压舱石的竞技逻辑：稳定性远大于弹性，任何一项结构性恶化直接踢出。"
            "① 低回撤防线（均线结构坚实 MA20 > MA60，代理最大回撤控制能力，权重 40%）"
            "② 派息可持续性（估值稳健不过热，市场对现金流的长期定价，权重 30%）"
            "③ 长周期索提诺（平稳正向动能，非爆发性脉冲，权重 30%）。"
            "三维同时达标方为真正压舱石，任一维度结构性恶化即触发降级熔断。"
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
        "score_name": "时代之王动量指数",
        "weights": {"mom20": 0.50, "z_score": 0.25, "bullish": 0.25},
        "invert_z": False,
        "factor_labels": {
            "mom20":   "RS 强度 (相对动量核心)",
            "z_score": "叙事强度 (宏观剧本契合度)",
            "bullish": "资金面确认 (主升浪信号)",
        },
        "logic": (
            "时代之王的竞技逻辑：宏观叙事 × 动量共振 × 资金确认 = 当前周期的主角。"
            "① RS 强度（相对动量是时代之王的核心，20日动量领跑全场，权重 50%）"
            "② 叙事强度（估值溢价代理市场对当前宏观剧本的定价共识，权重 25%）"
            "③ 资金面确认（主升浪均线结构信号，MA20 > MA60 确认机构持续流入，权重 25%）。"
            "【核心筛选】必须符合当前得分最高的宏观剧本，衰退期的强周期股不能入围。"
        ),
    },
    "D": {
        "score_name": "预备队爆发指数",
        "weights": {"mom20": 0.50, "z_score_inv": 0.30, "bullish": 0.20},
        "invert_z": True,
        "factor_labels": {
            "mom20":       "右侧放量突破 (催化剂强度)",
            "z_score_inv": "盈亏比 R:R (低估=更大上行空间)",
            "bullish":     "右侧突破确认 (趋势启动信号)",
        },
        "logic": (
            "预备队的竞技逻辑：催化剂清晰度 × 右侧放量突破，规则大于判断，严守止损位。"
            "① 右侧放量突破（近 20 天动量爆发是催化剂兑现的直接信号，权重 50%）"
            "② 盈亏比 R:R（Z-Score 越低代表越大的上行空间，估值因子反向计分，权重 30%）"
            "③ 右侧突破确认（均线开始金叉，主升浪启动信号，权重 20%）。"
            "【注意】R:R 因子为反向计分，Z 越低得分越高，代表更佳的风险收益比。"
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

    _source_map = {
        "z_score":     z_norm,
        "z_score_inv": z_inv_norm,
        "mom20":       m_norm,
        "bullish":     b_norm,
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


# ─────────────────────────────────────────────────────────────────
#  UI：颁奖台（Top 3 高亮展示）
# ─────────────────────────────────────────────────────────────────
_PODIUM_MEDALS = [
    ("🥇", "#FFD700", "podium-gold",   "冠军"),
    ("🥈", "#C0C0C0", "podium-silver", "亚军"),
    ("🥉", "#CD7F32", "podium-bronze", "季军"),
]


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

        # 三因子分解文字
        f1_name = list(cfg["factor_labels"].values())[0]
        f2_name = list(cfg["factor_labels"].values())[1]
        f3_name = list(cfg["factor_labels"].values())[2]

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
                <div style='font-size:10px; color:#777; text-align:left; line-height:1.8;'>
                    <span style='color:{meta["color"]}30; background:{meta["color"]}20;
                                 border-radius:3px; padding:1px 6px;'>
                        F1 {row['因子1_分']:.1f}
                    </span>
                    <span style='color:#3498DB30; background:#3498DB20;
                                 border-radius:3px; padding:1px 6px;'>
                        F2 {row['因子2_分']:.1f}
                    </span>
                    <span style='color:#9B59B630; background:#9B59B620;
                                 border-radius:3px; padding:1px 6px;'>
                        F3 {row['因子3_分']:.1f}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
#  UI：完整排行榜（含得分条形图）
# ─────────────────────────────────────────────────────────────────
def _render_leaderboard(df_scored: pd.DataFrame, cls: str) -> None:
    """渲染完整赛道排行榜 + 因子分解横向条形图。"""
    meta = CLASS_META[cls]
    cfg = ARENA_CONFIG[cls]

    st.markdown(f"#### 完整排行榜（{meta['icon']} {len(df_scored)} 位参赛选手）")

    # ── 排行榜（div flexbox，规避 st.markdown 不渲染 table 标签的限制）──
    header_html = (
        "<div style='display:flex; align-items:center; border-bottom:2px solid #333;"
        " color:#888; font-size:11px; padding:6px 0; font-weight:bold;'>"
        "<div style='width:46px; text-align:center;'>排名</div>"
        "<div style='flex:1;'>资产</div>"
        "<div style='width:72px; text-align:right;'>Z-Score</div>"
        "<div style='width:90px; text-align:right;'>20日动量</div>"
        "<div style='width:46px; text-align:center;'>趋势</div>"
        f"<div style='width:190px;'>{cfg['score_name']}</div>"
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

        rows_html += (
            "<div style='display:flex; align-items:center; border-bottom:1px solid #1e1e1e; padding:8px 0;'>"
            f"<div style='width:46px; text-align:center;'>{rank_html}</div>"
            "<div style='flex:1;'>"
            f"<span style='font-size:14px; font-weight:bold; color:#eee;'>{row['Ticker']}</span>"
            f"<span style='font-size:11px; color:#888; margin-left:8px;'>{row['名称']}</span>"
            "</div>"
            f"<div style='width:72px; text-align:right; font-weight:bold; color:{z_color};'>{z_val:+.2f}</div>"
            f"<div style='width:90px; text-align:right; font-weight:bold; color:{m_color};'>{m_val:+.1f}%</div>"
            f"<div style='width:46px; text-align:center;'>{trend_icon}</div>"
            "<div style='width:190px; padding-left:8px;'>"
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

    # ── 因子分解横向堆叠条形图 ─────────────────────────────────
    if len(df_scored) < 2:
        return

    factor_labels = list(cfg["factor_labels"].values())
    f_colors = [meta["color"], "#3498DB", "#9B59B6"]

    fig = go.Figure()

    tickers = df_scored["Ticker"].tolist()

    for fi, (col, label, color) in enumerate(zip(
        ["因子1_分", "因子2_分", "因子3_分"],
        factor_labels,
        f_colors,
    )):
        fig.add_trace(go.Bar(
            y=tickers,
            x=df_scored[col].tolist(),
            name=label,
            orientation="h",
            marker_color=color,
            opacity=0.85,
            hovertemplate=f"<b>%{{y}}</b><br>{label}: <b>%{{x:.1f}}</b><extra></extra>",
        ))

    fig.update_layout(
        barmode="stack",
        height=max(180, len(df_scored) * 38),
        plot_bgcolor="#111111",
        paper_bgcolor="#111111",
        font=dict(color="#cccccc", size=11),
        xaxis=dict(
            title="因子得分分解",
            gridcolor="#1e1e1e",
            range=[0, 105],
        ),
        yaxis=dict(
            categoryorder="array",
            categoryarray=tickers[::-1],
            gridcolor="#1a1a1a",
        ),
        legend=dict(
            bgcolor="#1a1a1a", bordercolor="#333", borderwidth=1,
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        ),
        margin=dict(l=60, r=30, t=40, b=40),
        title=dict(
            text=f"因子贡献分解 — {meta['icon']} {cfg['score_name']}",
            font=dict(size=13, color="#aaa"),
        ),
    )

    st.plotly_chart(fig, use_container_width=True)


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

    # 权重 pills
    pills_html = ""
    f_colors = [meta["color"], "#3498DB", "#9B59B6"]
    for (fname, flabel), fcolor in zip(cfg["factor_labels"].items(), f_colors):
        w_key = fname if fname in cfg["weights"] else list(cfg["weights"].keys())[
            list(cfg["factor_labels"].keys()).index(fname)
        ]
        wval = cfg["weights"].get(w_key, 0.0)
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
        st.success(
            f"**{meta['icon']} 赛道冠军深度解读 — {champ['Ticker']} ({champ['名称']})**\n\n"
            f"在 {meta['label']} 的 {n_total} 位参赛标的中，{champ['Ticker']} "
            f"以 **{cfg['score_name']} {champ['竞技得分']:.0f} 分**夺冠。\n"
            f"Z-Score = **{champ['Z-Score']:+.2f}**，20日动量 = **{champ['20日动量']:+.1f}%**，"
            f"{trend_txt}。\n"
            f"因子贡献：F1（{list(cfg['factor_labels'].values())[0]}）= {champ['因子1_分']:.1f}，"
            f"F2（{list(cfg['factor_labels'].values())[1]}）= {champ['因子2_分']:.1f}，"
            f"F3（{list(cfg['factor_labels'].values())[2]}）= {champ['因子3_分']:.1f}。"
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
#  全局概览横幅
# ─────────────────────────────────────────────────────────────────
overview_cols = st.columns(4)
for i, cls in enumerate(["A", "B", "C", "D"]):
    meta = CLASS_META[cls]
    n = len(df_all[df_all["类别"] == cls])
    with overview_cols[i]:
        st.markdown(f"""
        <div style='background:{meta["bg"]}; border:1px solid {meta["color"]}44;
                    border-radius:8px; padding:12px; text-align:center;'>
            <div style='font-size:22px;'>{meta["icon"]}</div>
            <div style='font-size:24px; font-weight:bold; color:{meta["color"]};'>{n}</div>
            <div style='font-size:10px; color:#888;'>{meta["label"]}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  四大竞技场 Tabs
# ─────────────────────────────────────────────────────────────────
tab_a, tab_b, tab_c, tab_d = st.tabs([
    "⚓ A级：压舱石",
    "🦍 B级：大猩猩",
    "👑 C级：时代之王",
    "🚀 D级：预备队",
])

with tab_a:
    _render_arena_tab(df_all[df_all["类别"] == "A"].copy(), "A")

with tab_b:
    _render_arena_tab(df_all[df_all["类别"] == "B"].copy(), "B")

with tab_c:
    _render_arena_tab(df_all[df_all["类别"] == "C"].copy(), "C")

with tab_d:
    _render_arena_tab(df_all[df_all["类别"] == "D"].copy(), "D")
