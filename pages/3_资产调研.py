import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from api_client import fetch_core_data

st.set_page_config(page_title="资产矩阵与雷达", layout="wide", page_icon="📡")

# ─────────────────────────────────────────────────────────────────
#  ABCD 战术分级元信息 (与 Page 2 保持完全一致)
# ─────────────────────────────────────────────────────────────────
CLASS_META: dict = {
    "A": {
        "label": "A级：压舱石",
        "nickname": "Anchor",
        "icon": "⚓",
        "color": "#3498DB",
        "update_freq": "月/季",
        "criteria": (
            "绝对防御与对冲指数：(35% 真实最大回撤倒数) + (25% 股息率) "
            "+ (20% SPY相关性倒数) + (20% 年化波动率倒数)"
        ),
        "logic": (
            "彻底摒弃动量与均线，专抓极低波动与大盘对冲属性。"
            "公式：(35% 真实最大回撤倒数) + (25% 股息率) + (20% SPY相关性倒数) + (20% 年化波动率倒数)。"
            "选出的资产将长年卧倒不动，构成投资组合最后的避难所。月/季度评估。"
        ),
        "strategy": (
            "衰退与高波动周期的定海神针。四维纯统计指标筛出极少数「真正的避风港资产」，"
            "持仓目标是对冲组合波动、压低最大回撤，而非博取弹性。"
        ),
    },
    "B": {
        "label": "B级：大猩猩",
        "nickname": "Gorilla",
        "icon": "🦍",
        "color": "#F39C12",
        "update_freq": "月/季",
        "criteria": (
            "核心底仓质量指数：(40% 真·自由现金流/回报率质量) + "
            "(30% 近3年最低最大回撤) + (20% 近3年夏普比率) + (10% 绝对市值壁垒)"
        ),
        "logic": (
            "核心底仓质量指数。彻底剔除短期动量，追求极低换手率与极强抗跌性。"
            "公式：(40% 真·自由现金流/回报率质量) + (30% 近3年最低最大回撤) + "
            "(20% 近3年夏普比率) + (10% 绝对市值壁垒)。"
            "高分者将形成稳固的长期护城河。月/季度评估。"
            "3年超长回溯期犹如周期照妖镜，彻底过滤掉伪装成白马的短期爆发周期股。"
        ),
        "strategy": (
            "长期底仓的定海神针。以股息率与盈利稳定性代理 FCF/ROIC 质量，"
            "辅以抗跌韧性和夏普比率双重风控，彻底拒绝短线动量噪音。"
            "换手率极低，只在年度调仓窗口微调。"
        ),
    },
    "C": {
        "label": "C级：时代之王",
        "nickname": "King",
        "icon": "👑",
        "color": "#2ECC71",
        "update_freq": "周",
        "criteria": "RS动量(6M vs SPY)进全域前20%  |  MA20 > MA60 > MA250（站稳主升浪）",
        "logic": (
            "动量最强的进攻矛头，两项全部通过方可入列。"
            "宏观剧本在上游分配仓位时会对 C 级内部的风格进行再偏移，周度评估。"
        ),
        "strategy": (
            "做多当前宏观叙事最强的「时代主角」。动量与趋势双重共振，"
            "超额收益的核心来源，跟踪止损纪律第一，周度滚动淘汰。"
        ),
    },
    "D": {
        "label": "D级：预备队",
        "nickname": "Scout",
        "icon": "🔭",
        "color": "#9B59B6",
        "update_freq": "日/周",
        "criteria": "近20天涨幅 > +8%  或  近5天涨幅 > +5%（短期动量突破信号）",
        "logic": (
            "最宽容的单项关卡：宏观归因尚未明确，但近期资金行为极强。"
            "是趋势爆发前的早期布局候选，日/周动态追踪，止损纪律第一。"
        ),
        "strategy": (
            "早期侦察兵，捕捉主升浪前的资金异动。仓位保持轻量，"
            "止损设在近期低点下方，一旦纳入 B/C 级则切换评估框架。"
        ),
    },
}

st.markdown("""
<style>
    .info-card  { border-radius:8px; padding:16px; }
    .detail-box { border-radius:0 6px 6px 0; padding:14px; margin-bottom:10px; }
    .small-text { font-size:11px; color:#888; line-height:1.5; }
    .macro-pill {
        display:inline-block; padding:3px 10px; border-radius:999px;
        font-size:13px; font-weight:600; margin:3px 4px 3px 0;
        border:1px solid transparent;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  宏观场景元信息
# ─────────────────────────────────────────────────────────────────
MACRO_SCENARIO_META: dict = {
    "Soft": {
        "label": "软着陆",
        "color": "#2ECC71",
        "bg":    "#0d2e1a",
        "desc":  "经济温和降速、通胀受控、美联储停止加息，风险资产普涨环境",
    },
    "Hot":  {
        "label": "再通胀",
        "color": "#F39C12",
        "bg":    "#2e1a00",
        "desc":  "经济强劲复苏、大宗商品与能源受益、通胀预期抬升",
    },
    "Stag": {
        "label": "滞胀",
        "color": "#E74C3C",
        "bg":    "#2e0a0a",
        "desc":  "经济停滞 + 通胀顽固，实物资产与防御板块相对占优",
    },
    "Rec":  {
        "label": "衰退防御",
        "color": "#3498DB",
        "bg":    "#0a1a2e",
        "desc":  "经济衰退预期上升，资金流向高股息、低波动、刚需消费类资产",
    },
    "Other": {
        "label": "其他",
        "color": "#888888",
        "bg":    "#1a1a1a",
        "desc":  "暂无明确宏观剧本归因",
    },
}

# ─────────────────────────────────────────────────────────────────
#  侧边栏
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📡 矩阵过滤器")
    selected_cls = st.multiselect(
        "显示类别",
        options=["A", "B", "C", "D"],
        default=["A", "B", "C", "D"],
        format_func=lambda x: f"{CLASS_META[x]['icon']} {CLASS_META[x]['label']}",
    )
    only_bullish = st.checkbox("仅显示趋势健康资产 (MA20 > MA60)", value=False)
    st.markdown("---")
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重刷"):
        st.cache_data.clear()
        st.success("缓存已清除！")
        st.rerun()

# ─────────────────────────────────────────────────────────────────
#  标题
# ─────────────────────────────────────────────────────────────────
st.title("📡 资产矩阵与雷达 (Asset Matrix & Radar)")
st.caption("数据源：上游 Page 2「资产分拣与白盒初筛」ABCD 分类结果 → 四象限视觉映射 → 类别逻辑深挖")

# ─────────────────────────────────────────────────────────────────
#  数据读取：依赖上游 Page 2 写入 session_state
# ─────────────────────────────────────────────────────────────────
if "abcd_classified_assets" not in st.session_state:
    st.warning(
        "**尚未获取到分拣数据。** 请先访问左侧导航栏中的 "
        "**2 资产分拣与白盒初筛** 页面——系统完成资产 ABCD 分拣后，"
        "结果将自动传入本视图。",
        icon="🗂️",
    )
    st.stop()

all_assets: dict = st.session_state["abcd_classified_assets"]

# ─────────────────────────────────────────────────────────────────
#  构建绘图数据框
# ─────────────────────────────────────────────────────────────────
rows = []
for ticker, info in all_assets.items():
    cls = info.get("cls", "?")
    if not info.get("has_data") or cls not in CLASS_META:
        continue
    rows.append({
        "Ticker":     ticker,
        "名称":       info.get("cn_name", ticker),
        "类别":       cls,
        "Z-Score":    float(info.get("z_score", 0.0)),
        "20日动量":   float(info.get("mom20", 0.0)),
        "趋势健康":   bool(info.get("is_bullish", False)),
        "趋势标签":   "✅ 趋势健康" if info.get("is_bullish") else "🔒 趋势走弱",
        "判定理由":   info.get("reason", "—"),
        "分类方法":   info.get("method", "—"),
    })

if not rows:
    st.error("分拣数据中无可用技术指标，请返回 Page 2 检查数据加载状态。")
    st.stop()

df_all = pd.DataFrame(rows).astype({"Z-Score": float, "20日动量": float})

# 应用过滤
df_show = df_all[df_all["类别"].isin(selected_cls)].copy()
if only_bullish:
    df_show = df_show[df_show["趋势健康"]]

# ─────────────────────────────────────────────────────────────────
#  Section 1：四象限估值×动量矩阵
# ─────────────────────────────────────────────────────────────────
st.header("1️⃣ 四象限估值-动量矩阵 (Valuation × Momentum Matrix)")

quad_l, quad_r = st.columns(2)
with quad_l:
    st.markdown("""
    <div style='font-size:12px; color:#aaa; line-height:2;'>
    <span style='color:#2ECC71; font-weight:bold;'>▶ 右上：强势延续区</span> — Z↑ 动量↑ — 趋势与估值共振，当前最强势板块<br>
    <span style='color:#F39C12; font-weight:bold;'>◀ 左上：反转猎手区</span> — Z↓ 动量↑ — 低位动能觉醒，潜在反转先行者
    </div>
    """, unsafe_allow_html=True)
with quad_r:
    st.markdown("""
    <div style='font-size:12px; color:#aaa; line-height:2;'>
    <span style='color:#3498DB; font-weight:bold;'>◀ 左下：深度价值区</span> — Z↓ 动量↓ — 逆向布局候选，等待宏观催化剂<br>
    <span style='color:#E74C3C; font-weight:bold;'>▶ 右下：高危减仓区</span> — Z↑ 动量↓ — 动能衰竭高位滞涨，建议规避
    </div>
    """, unsafe_allow_html=True)

if df_show.empty:
    st.info("当前过滤条件下无数据，请调整侧边栏设置。")
else:
    # 动态坐标轴范围
    x_abs = max(3.5, df_show["Z-Score"].abs().max() * 1.25)
    y_abs = max(25.0, df_show["20日动量"].abs().max() * 1.25)

    fig = go.Figure()

    # 象限背景色块
    quad_fills = [
        (0, 0, x_abs, y_abs, "rgba(46,204,113,0.05)"),    # 右上 绿
        (-x_abs, 0, 0, y_abs, "rgba(243,156,18,0.05)"),   # 左上 橙
        (-x_abs, -y_abs, 0, 0, "rgba(52,152,219,0.05)"),  # 左下 蓝
        (0, -y_abs, x_abs, 0, "rgba(231,76,60,0.07)"),    # 右下 红
    ]
    for x0, y0, x1, y1, fc in quad_fills:
        fig.add_shape(
            type="rect", x0=x0, y0=y0, x1=x1, y1=y1,
            fillcolor=fc, line_width=0, layer="below",
        )

    # 每个 ABCD 类单独一条轨迹（确保图例完整且颜色独立）
    for cls in ["A", "B", "C", "D"]:
        sub = df_show[df_show["类别"] == cls]
        if sub.empty:
            continue
        meta = CLASS_META[cls]
        # 悬浮提示用的 customdata 列
        custom = list(zip(
            sub["名称"].tolist(),
            sub["趋势标签"].tolist(),
            sub["判定理由"].tolist(),
        ))
        fig.add_trace(go.Scatter(
            x=sub["Z-Score"].tolist(),
            y=sub["20日动量"].tolist(),
            mode="markers+text",
            name=f"{meta['icon']} {meta['label']}",
            marker=dict(
                color=meta["color"], size=13, opacity=0.88,
                line=dict(color="#111111", width=1),
                symbol="circle",
            ),
            text=sub["Ticker"].tolist(),
            textposition="top center",
            textfont=dict(size=9, color=meta["color"]),
            customdata=custom,
            hovertemplate=(
                "<b>%{text}</b>  %{customdata[0]}<br>"
                "Z-Score: <b>%{x:.2f}</b>　　20日动量: <b>%{y:.1f}%</b><br>"
                "趋势: %{customdata[1]}<br>"
                "<span style='color:#aaa; font-size:10px;'>%{customdata[2]}</span>"
                "<extra></extra>"
            ),
        ))

    # 坐标轴基准线
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", line_width=1)
    fig.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,0.2)", line_width=1)

    # 象限文字标注
    quad_labels = [
        (x_abs * 0.75,  y_abs * 0.9,  "强势延续区", "rgba(46,204,113,0.45)"),
        (-x_abs * 0.75, y_abs * 0.9,  "反转猎手区", "rgba(243,156,18,0.45)"),
        (-x_abs * 0.75, -y_abs * 0.9, "深度价值区", "rgba(52,152,219,0.45)"),
        (x_abs * 0.75,  -y_abs * 0.9, "高危减仓区", "rgba(231,76,60,0.45)"),
    ]
    for xp, yp, txt, fc in quad_labels:
        fig.add_annotation(
            x=xp, y=yp, text=txt, showarrow=False,
            font=dict(size=12, color=fc),
        )

    fig.update_layout(
        height=640,
        plot_bgcolor="#111111",
        paper_bgcolor="#111111",
        font=dict(color="#dddddd", size=12),
        xaxis=dict(
            title="Z-Score　（估值偏差，1Y 均值归一化）",
            gridcolor="#1e1e1e", zeroline=False,
            range=[-x_abs, x_abs],
        ),
        yaxis=dict(
            title="20日动量 (%)",
            gridcolor="#1e1e1e", zeroline=False,
            range=[-y_abs, y_abs],
        ),
        legend=dict(
            bgcolor="#1a1a1a", bordercolor="#333333", borderwidth=1,
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
        ),
        margin=dict(l=60, r=30, t=50, b=60),
        hoverlabel=dict(bgcolor="#1a1a1a", bordercolor="#444", font_size=12),
    )

    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────
#  Section 2：资产宇宙统计卡片
# ─────────────────────────────────────────────────────────────────
st.header("2️⃣ 资产宇宙概览 (Universe Snapshot)")
stat_cols = st.columns(4)
for i, cls in enumerate(["A", "B", "C", "D"]):
    meta = CLASS_META[cls]
    total_n   = len(df_all[df_all["类别"] == cls])
    show_n    = len(df_show[df_show["类别"] == cls])
    bullish_n = len(df_all[(df_all["类别"] == cls) & df_all["趋势健康"]])
    bull_pct  = round(bullish_n / total_n * 100) if total_n else 0
    with stat_cols[i]:
        st.markdown(f"""
        <div style='background:{meta["color"]}14; border:1px solid {meta["color"]}66;
                    border-radius:8px; padding:14px; text-align:center;'>
            <div style='font-size:26px;'>{meta["icon"]}</div>
            <div style='font-size:30px; font-weight:bold; color:{meta["color"]};'>{show_n}</div>
            <div style='font-size:10px; color:#888;'>/ {total_n} 总计</div>
            <div style='font-size:11px; color:#ccc; margin-top:4px;'>{meta["label"]}</div>
            <div style='font-size:10px; color:#F1C40F; margin-top:6px;'>趋势健康 {bull_pct}%</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────
#  Section 3：资产详情查询面板
# ─────────────────────────────────────────────────────────────────
st.header("3️⃣ 资产深度查询 (Asset Intelligence Panel)")

if df_show.empty:
    st.info("当前过滤条件下无可查询资产。")
    st.stop()

# 下拉选项：Ticker | 名称 | 类别标签
options = []
for _, row in df_show.iterrows():
    meta = CLASS_META[row["类别"]]
    options.append(f"{row['Ticker']}  |  {row['名称']}  |  {meta['icon']} {meta['label']}")

selected_option = st.selectbox(
    "选择资产，查看完整档案与类别投资逻辑：",
    options=options,
)

if not selected_option:
    st.stop()

# 加载核心数据（DEEP_INSIGHTS + MACRO_TAGS_MAP）
_core_data      = fetch_core_data()
_deep_insights: dict = _core_data.get("DEEP_INSIGHTS", {})

# 构建 ticker → 宏观标签列表 的反向查找字典
_macro_tags_map: dict = _core_data.get("MACRO_TAGS_MAP", {})
_ticker_macro: dict = {}
for scenario, tickers_in_scenario in _macro_tags_map.items():
    for t in tickers_in_scenario:
        _ticker_macro.setdefault(t, []).append(scenario)

sel_ticker = selected_option.split("  |  ")[0].strip()
sel_row    = df_show[df_show["Ticker"] == sel_ticker].iloc[0]
sel_cls    = sel_row["类别"]
sel_meta   = CLASS_META[sel_cls]

z_val  = sel_row["Z-Score"]
m_val  = sel_row["20日动量"]
z_color = "#2ECC71" if z_val > 0.5 else ("#E74C3C" if z_val < -0.5 else "#F1C40F")
m_color = "#2ECC71" if m_val >= 0 else "#E74C3C"

# 象限判断
if z_val > 0 and m_val > 0:
    quad_title  = "当前位置：强势延续区 ▶"
    quad_color  = "#2ECC71"
    quad_advice = (
        "趋势与估值共振，是当前最强势区域。可顺势持有或小幅加仓，"
        "严格设置跟踪止损线，持续监控动量是否出现顶背离迹象。"
    )
elif z_val <= 0 and m_val > 0:
    quad_title  = "当前位置：反转猎手区 ◀"
    quad_color  = "#F39C12"
    quad_advice = (
        "低位动能觉醒，存在反转潜力。需观察成交量配合及宏观催化剂落地情况，"
        "建议分批建仓控制风险，止损设在近期低点下方。"
    )
elif z_val <= 0 and m_val <= 0:
    quad_title  = "当前位置：深度价值区 ◀"
    quad_color  = "#3498DB"
    quad_advice = (
        "逆向布局候选。需耐心等待趋势反转信号（动量首次转正），"
        "宏观剧本与该类别对齐时方为介入时机，仓位保持低配。"
    )
else:
    quad_title  = "当前位置：高危减仓区 ▶"
    quad_color  = "#E74C3C"
    quad_advice = (
        "动能衰竭 + 高位滞涨，风险收益比极差。"
        "除非有突发催化，否则建议大幅减仓或规避，"
        "等待 Z-Score 回落至合理区间后再重新评估。"
    )

col_badge, col_detail = st.columns([1, 3])

with col_badge:
    st.markdown(f"""
    <div style='background:{sel_meta["color"]}14; border:2px solid {sel_meta["color"]};
                border-radius:10px; padding:22px; text-align:center;'>
        <div style='font-size:44px;'>{sel_meta["icon"]}</div>
        <div style='font-size:15px; font-weight:bold; color:{sel_meta["color"]}; margin-top:10px;'>
            {sel_meta["label"]}
        </div>
        <hr style='border-color:{sel_meta["color"]}33; margin:12px 0;'>
        <div style='font-size:15px; font-weight:bold; color:#eee;'>{sel_ticker}</div>
        <div style='font-size:12px; color:#aaa; margin-top:4px;'>{sel_row["名称"]}</div>
        <hr style='border-color:#2a2a2a; margin:12px 0;'>
        <div style='display:flex; justify-content:space-between; font-size:13px; margin-bottom:6px;'>
            <span style='color:#888;'>Z-Score</span>
            <span style='color:{z_color}; font-weight:bold;'>{z_val:+.2f}</span>
        </div>
        <div style='display:flex; justify-content:space-between; font-size:13px;'>
            <span style='color:#888;'>20日动量</span>
            <span style='color:{m_color}; font-weight:bold;'>{m_val:+.1f}%</span>
        </div>
        <div style='font-size:11px; color:#aaa; margin-top:10px;'>{sel_row["趋势标签"]}</div>
    </div>
    """, unsafe_allow_html=True)

with col_detail:
    # ① 宏观场景属性标签
    _ticker_scenarios = _ticker_macro.get(sel_ticker, [])
    if _ticker_scenarios:
        pills_html = "".join(
            f"<span class='macro-pill' "
            f"style='color:{MACRO_SCENARIO_META[s]['color']}; "
            f"background:{MACRO_SCENARIO_META[s]['bg']}; "
            f"border-color:{MACRO_SCENARIO_META[s]['color']}55;'>"
            f"{MACRO_SCENARIO_META[s]['label']}</span>"
            for s in _ticker_scenarios
            if s in MACRO_SCENARIO_META
        )
        descriptions_html = "<br>".join(
            f"<span style='color:{MACRO_SCENARIO_META[s]['color']}; font-weight:600;'>"
            f"{MACRO_SCENARIO_META[s]['label']}：</span>"
            f"<span style='color:#bbb;'>{MACRO_SCENARIO_META[s]['desc']}</span>"
            for s in _ticker_scenarios
            if s in MACRO_SCENARIO_META
        )
        st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid #9B59B6; background:#120a1a;'>
        <div style='font-size:13px; font-weight:bold; color:#BB8FCE; margin-bottom:10px;'>
            🌐 宏观场景适配
        </div>
        <div style='margin-bottom:10px;'>{pills_html}</div>
        <div style='font-size:13px; color:#888; line-height:2.0;'>{descriptions_html}</div>
    </div>
    """, unsafe_allow_html=True)

    # ③ 机构级核心逻辑 (来自 DEEP_INSIGHTS)
    _insight = _deep_insights.get(sel_ticker, "")
    if _insight:
        st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid #F1C40F; background:#1a1800;'>
        <div style='font-size:13px; font-weight:bold; color:#F1C40F; margin-bottom:8px;'>
            💡 核心业务与持仓逻辑
        </div>
        <div style='font-size:12px; color:#ddd; line-height:1.8;'>{_insight}</div>
    </div>
    """, unsafe_allow_html=True)

    # ④ 类别入选标准逻辑
    st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid {sel_meta["color"]};
                background:{sel_meta["color"]}0D;'>
        <div style='font-size:13px; font-weight:bold; color:{sel_meta["color"]}; margin-bottom:8px;'>
            {sel_meta["icon"]} {sel_meta["label"]} — 入选门槛
        </div>
        <div style='font-size:11px; color:#888; margin-bottom:6px;'>更新频率：{sel_meta["update_freq"]}</div>
        <div style='font-size:12px; color:#ccc; line-height:1.75;'>{sel_meta["logic"]}</div>
    </div>
    """, unsafe_allow_html=True)

    # ⑤ 个股白盒判定理由
    method_color = "#2980B9" if "相关性" in sel_row["分类方法"] else "#27AE60"
    st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid #444; background:#161616;'>
        <div style='font-size:13px; font-weight:bold; color:#bbb; margin-bottom:8px;'>
            🔬 个股白盒判定理由
        </div>
        <div style='font-size:12px; color:#aaa; line-height:1.75;'>{sel_row["判定理由"]}</div>
        <div style='font-size:10px; color:{method_color}; margin-top:8px;'>
            分类方法：{sel_row["分类方法"]}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ⑥ 象限操作建议
    st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid {quad_color};
                background:{quad_color}0D;'>
        <div style='font-size:13px; font-weight:bold; color:{quad_color}; margin-bottom:8px;'>
            🧭 {quad_title}
        </div>
        <div style='font-size:12px; color:#ccc; line-height:1.75;'>{quad_advice}</div>
    </div>
    """, unsafe_allow_html=True)

    # ⑦ 类别整体战略建议
    st.markdown(f"""
    <div class='detail-box' style='border-left:3px solid #555; background:#1a1a1a;'>
        <div style='font-size:13px; font-weight:bold; color:#999; margin-bottom:8px;'>
            📋 {sel_meta["icon"]} {sel_meta["label"]} — 整体配置战略
        </div>
        <div style='font-size:12px; color:#aaa; line-height:1.75;'>{sel_meta["strategy"]}</div>
    </div>
    """, unsafe_allow_html=True)
