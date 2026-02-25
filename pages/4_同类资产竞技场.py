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
        "label": "A类：核心底仓",
        "icon": "🌤️",
        "color": "#2ECC71",
        "bg": "#0d2b1a",
    },
    "B": {
        "label": "B类：主线动量",
        "icon": "🔥",
        "color": "#F39C12",
        "bg": "#2b1e09",
    },
    "C": {
        "label": "C类：周期拐点",
        "icon": "🌧️",
        "color": "#E74C3C",
        "bg": "#2b0d0d",
    },
    "D": {
        "label": "D类：防御收缩",
        "icon": "❄️",
        "color": "#3498DB",
        "bg": "#0d1a2b",
    },
}

# ─────────────────────────────────────────────────────────────────
#  各赛道评分配置（Relative Scoring Config）
#  每个赛道有独立的权重体系和竞技逻辑
# ─────────────────────────────────────────────────────────────────
ARENA_CONFIG: dict = {
    "A": {
        "score_name": "护城河指数",
        "weights": {"z_score": 0.35, "mom20": 0.35, "bullish": 0.30},
        "invert_z": False,
        "factor_labels": {
            "z_score": "估值溢价接受度 (Z↑)",
            "mom20":   "成长动能 (Mom↑)",
            "bullish": "趋势健康度 (MA20>MA60)",
        },
        "logic": (
            "核心底仓的竞技逻辑：三维共振才是真护城河。"
            "① 市场愿意持续支付估值溢价（Z-Score 正向，权重 35%）"
            "② 成长动能持续兑现（20日动量强劲，权重 35%）"
            "③ 均线结构健康（MA20 > MA60，权重 30%）。"
            "三维共振的品种方为长期核心仓位的最优标的。"
        ),
    },
    "B": {
        "score_name": "动量强度指数",
        "weights": {"z_score": 0.20, "mom20": 0.60, "bullish": 0.20},
        "invert_z": False,
        "factor_labels": {
            "z_score": "溢价基础 (Z↑)",
            "mom20":   "资金流速 (Mom↑↑)",
            "bullish": "趋势持续性",
        },
        "logic": (
            "主线动量的竞技逻辑：资金流速决定胜负。"
            "再通胀/周期行情中，谁的资金吸附速度最快，谁就是主线。"
            "20日动量拿下 60% 权重——在 B 类竞技场中，弱动量无优势可言。"
            "估值基础（20%）与趋势延续性（20%）作为辅助筛选因子。"
        ),
    },
    "C": {
        "score_name": "拐点爆发指数",
        "weights": {"z_score_inv": 0.40, "mom20": 0.40, "bullish": 0.20},
        "invert_z": True,
        "factor_labels": {
            "z_score_inv": "低估潜力 (-Z↓，剩余空间)",
            "mom20":       "动能觉醒 (Mom↑)",
            "bullish":     "趋势启动信号",
        },
        "logic": (
            "周期拐点的竞技逻辑：最被低估 × 动能觉醒 = 最大爆发潜力。"
            "① 低估潜力（Z-Score 反转取负值，Z 越低→剩余空间越大，权重 40%）"
            "② 动能觉醒（20日动量开始转正，权重 40%）"
            "③ 趋势启动信号（均线多头排列开始形成，权重 20%）。"
            "【注意】该赛道估值因子为反向计分，Z 越低得分越高。"
        ),
    },
    "D": {
        "score_name": "防御稳定指数",
        "weights": {"z_score": 0.25, "mom20": 0.30, "bullish": 0.45},
        "invert_z": False,
        "factor_labels": {
            "z_score": "估值合理度 (Z↑)",
            "mom20":   "稳步上行动能",
            "bullish": "趋势坚韧度 (MA结构)",
        },
        "logic": (
            "防御收缩的竞技逻辑：稳定性优先于弹性，趋势坚韧是压舱石的核心属性。"
            "均线趋势健康度拿下 45% 最高权重——衰退中仍保持 MA20 > MA60 的资产，"
            "正是机构系统性避险再配置的核心标的。"
            "稳步上行动能（30%）与估值合理度（25%）辅助筛选高性价比防御品种。"
        ),
    },
}

# ─────────────────────────────────────────────────────────────────
#  演示模式 Mock 数据（当上游 Page 2 尚未运行时使用）
# ─────────────────────────────────────────────────────────────────
_MOCK_ASSETS: dict = {
    # A类：核心底仓（软着陆/成长）
    "AAPL":  {"cls": "A", "cn_name": "苹果",     "z_score":  1.2, "mom20":  8.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "MSFT":  {"cls": "A", "cn_name": "微软",     "z_score":  1.8, "mom20":  6.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "NVDA":  {"cls": "A", "cn_name": "英伟达",   "z_score":  2.4, "mom20": 18.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "GOOGL": {"cls": "A", "cn_name": "谷歌",     "z_score":  0.9, "mom20":  4.8, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "META":  {"cls": "A", "cn_name": "Meta",     "z_score":  1.5, "mom20": 11.2, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "AMZN":  {"cls": "A", "cn_name": "亚马逊",   "z_score":  0.7, "mom20":  3.1, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # B类：主线动量（再通胀/周期）
    "XLE":   {"cls": "B", "cn_name": "能源 ETF", "z_score":  0.4, "mom20":  7.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "XLI":   {"cls": "B", "cn_name": "工业 ETF", "z_score":  0.6, "mom20":  5.1, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "FCX":   {"cls": "B", "cn_name": "自由港",   "z_score": -0.2, "mom20":  9.8, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "GS":    {"cls": "B", "cn_name": "高盛",     "z_score":  0.8, "mom20":  3.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "CVX":   {"cls": "B", "cn_name": "雪佛龙",   "z_score":  0.2, "mom20": 12.4, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # C类：周期拐点（滞胀/实物）
    "GLD":   {"cls": "C", "cn_name": "黄金 ETF", "z_score":  0.3, "mom20":  2.1, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "SLV":   {"cls": "C", "cn_name": "白银 ETF", "z_score": -0.5, "mom20":  3.8, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "URA":   {"cls": "C", "cn_name": "铀矿 ETF", "z_score": -1.2, "mom20":  5.5, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "DBA":   {"cls": "C", "cn_name": "农产品 ETF","z_score": -0.8, "mom20":  1.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    # D类：防御收缩（衰退/防御）
    "XLU":   {"cls": "D", "cn_name": "公用事业 ETF", "z_score":  0.1, "mom20":  1.5, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "XLP":   {"cls": "D", "cn_name": "必选消费 ETF", "z_score":  0.3, "mom20":  0.8, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "XLV":   {"cls": "D", "cn_name": "医疗健康 ETF", "z_score": -0.2, "mom20":  2.3, "is_bullish": True,  "reason": "Mock 演示", "method": "Mock", "has_data": True},
    "TLT":   {"cls": "D", "cn_name": "长期国债 ETF", "z_score": -0.8, "mom20":  3.1, "is_bullish": False, "reason": "Mock 演示", "method": "Mock", "has_data": True},
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
    在同类资产内部计算相对竞技得分。
    - A/B/D：Z-Score 正向计分（高 Z = 市场认可）
    - C：Z-Score 反向计分（低 Z = 剩余空间大 = 拐点爆发潜力高）
    返回按竞技得分降序排列的 DataFrame，含因子分解列。
    """
    if df.empty:
        return df

    cfg = ARENA_CONFIG[cls]
    w = cfg["weights"]
    result = df.copy()

    z_norm = _minmax_norm(result["Z-Score"].astype(float))
    m_norm = _minmax_norm(result["20日动量"].astype(float))
    b_norm = result["趋势健康"].astype(float) * 100.0  # True=100, False=0

    f1_label = list(cfg["factor_labels"].keys())[0]

    if cfg["invert_z"]:
        # C 类：低 Z = 更大潜力，故取负值做归一化
        z_inv_norm = _minmax_norm(-result["Z-Score"].astype(float))
        w1 = w.get("z_score_inv", 0.40)
        result["_f1"] = w1 * z_inv_norm
    else:
        w1 = w.get("z_score", 0.35)
        result["_f1"] = w1 * z_norm

    w2 = w.get("mom20", 0.35)
    w3 = w.get("bullish", 0.30)
    result["_f2"] = w2 * m_norm
    result["_f3"] = w3 * b_norm

    result["竞技得分"] = (result["_f1"] + result["_f2"] + result["_f3"]).round(1)
    result["因子1_分"] = result["_f1"].round(1)
    result["因子2_分"] = result["_f2"].round(1)
    result["因子3_分"] = result["_f3"].round(1)
    result.drop(columns=["_f1", "_f2", "_f3"], inplace=True)

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
    "🌤️ A类：核心底仓",
    "🔥 B类：主线动量",
    "🌧️ C类：周期拐点",
    "❄️ D类：防御收缩",
])

with tab_a:
    _render_arena_tab(df_all[df_all["类别"] == "A"].copy(), "A")

with tab_b:
    _render_arena_tab(df_all[df_all["类别"] == "B"].copy(), "B")

with tab_c:
    _render_arena_tab(df_all[df_all["类别"] == "C"].copy(), "C")

with tab_d:
    _render_arena_tab(df_all[df_all["类别"] == "D"].copy(), "D")
