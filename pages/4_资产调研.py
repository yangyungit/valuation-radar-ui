import streamlit as st
import pandas as pd
import numpy as np
import os, json
import plotly.graph_objects as go
from api_client import fetch_core_data, fetch_screen_results, fetch_arena_history as _fetch_arena_history
from shared_state import SharedKeys  # 跨页面 session_state key 集中定义（约束 4）

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
    "Z": {
        "label": "Z级：现金流堡垒",
        "nickname": "Yield",
        "icon": "🏦",
        "color": "#1ABC9C",
        "update_freq": "月",
        "criteria": (
            "现金流堡垒指数：(40% 真实股息率) + (25% 分红续航力) "
            "+ (20% 绝对低波·年化波动率倒数) + (15% 本金盾·最大回撤倒数)"
        ),
        "logic": (
            "专为收息型持仓设计，四维纯现金流指标优选能持续派息的资产。"
            "公式：(40% 真实股息率) + (25% EPS稳定性/分红续航力) "
            "+ (20% 年化波动率倒数) + (15% 最大回撤倒数)。"
            "入选门槛：股息率 ≥ 1%，零股息资产（如 GLD）不参赛。月度评估。"
        ),
        "strategy": (
            "收息型底仓，专注真实现金流的长期积累。"
            "锚定高股息可持续性与低波动保本，换手率极低，"
            "配合宏观衰退/滞胀剧本使用时对冲效果最佳。"
            "只展示赛道得分前 20 名（按现值偏低优先排序）。"
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
        options=["A", "B", "C", "D", "Z"],
        default=["A", "B", "C", "D", "Z"],
        format_func=lambda x: f"{CLASS_META[x]['icon']} {CLASS_META[x]['label']}",
    )
    only_bullish = st.checkbox("仅显示趋势健康资产 (MA20 > MA60)", value=False)
    st.markdown("---")
    st.header("🛠️ 系统维护")
    if st.button("🔄 仅清除当前页缓存"):
        fetch_core_data.clear()
        st.success("当前页缓存已清除！")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.success("所有页面缓存已清除！")
        st.rerun()

# ─────────────────────────────────────────────────────────────────
#  标题
# ─────────────────────────────────────────────────────────────────
st.title("📡 资产矩阵与雷达 (Asset Matrix & Radar)")
st.caption("数据源：上游 Page 4「同类资产竞技场」ABCD 分类结果 → 四象限视觉映射 → 类别逻辑深挖")

# ─────────────────────────────────────────────────────────────────
#  数据读取：优先后端缓存，回退 session_state
# ─────────────────────────────────────────────────────────────────
_screen_cache = fetch_screen_results()
all_assets: dict = (
    _screen_cache.get("abcd_classified_assets")
    or st.session_state.get("abcd_classified_assets")
)
if not all_assets:
    st.warning(
        "**尚未获取到分拣数据。** 请先访问左侧导航栏中的 "
        "**3 同类资产竞技场** 页面——系统完成资产 ABCD 分类后，"
        "结果将自动传入本视图。",
        icon="🗂️",
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────
#  构建绘图数据框（按 qualifying_grades 展开，与 page3 对齐）
# ─────────────────────────────────────────────────────────────────
_GRADE_JITTER = {"A": (0, 0), "B": (0.06, 0.4), "C": (-0.06, -0.4), "D": (0.04, -0.6), "Z": (-0.04, 0.3)}

rows = []
for ticker, info in all_assets.items():
    if not info.get("has_data"):
        continue
    q_grades = [g for g in info.get("qualifying_grades", []) if g in CLASS_META]
    if not q_grades:
        continue
    primary = info.get("cls", q_grades[0])
    all_badges = " + ".join(q_grades)
    base_z   = float(info.get("z_score", 0.0))
    base_mom = float(info.get("mom20", 0.0))
    for g in q_grades:
        jx, jy = _GRADE_JITTER.get(g, (0, 0)) if len(q_grades) > 1 else (0, 0)
        rows.append({
            "Ticker":     ticker,
            "名称":       info.get("cn_name", ticker),
            "类别":       g,
            "is_primary": g == primary,
            "all_grades": all_badges,
            "Z-Score":    base_z + jx,
            "20日动量":   base_mom + jy,
            "趋势健康":   bool(info.get("is_bullish", False)),
            "趋势标签":   "✅ 趋势健康" if info.get("is_bullish") else "🔒 趋势走弱",
            "判定理由":   info.get("reason", "—"),
            "分类方法":   info.get("method", "—"),
        })

if not rows:
    st.error("分拣数据中无可用技术指标，请返回 Page 4 检查数据加载状态。")
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

    # 每个 ABCD 类单独一条轨迹；多级别副本用空心环标记
    for cls in ["A", "B", "C", "D", "Z"]:
        sub = df_show[df_show["类别"] == cls]
        if sub.empty:
            continue
        meta = CLASS_META[cls]
        sub_primary   = sub[sub["is_primary"]]
        sub_secondary = sub[~sub["is_primary"]]

        for part, is_pri in [(sub_primary, True), (sub_secondary, False)]:
            if part.empty:
                continue
            custom = list(zip(
                part["名称"].tolist(),
                part["趋势标签"].tolist(),
                part["判定理由"].tolist(),
                part["all_grades"].tolist(),
            ))
            fig.add_trace(go.Scatter(
                x=part["Z-Score"].tolist(),
                y=part["20日动量"].tolist(),
                mode="markers+text" if is_pri else "markers",
                name=f"{meta['icon']} {meta['label']}",
                legendgroup=cls,
                showlegend=is_pri,
                marker=dict(
                    color=meta["color"] if is_pri else "rgba(0,0,0,0)",
                    size=13 if is_pri else 16,
                    opacity=0.88 if is_pri else 0.7,
                    line=dict(color=meta["color"], width=1 if is_pri else 2.5),
                    symbol="circle" if is_pri else "circle-open",
                ),
                text=part["Ticker"].tolist() if is_pri else None,
                textposition="top center" if is_pri else None,
                textfont=dict(size=9, color=meta["color"]) if is_pri else None,
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[3]}</b><br>"
                    "<b>" + ("" if is_pri else "⭕ 副级别 ") + meta["label"] + "</b>: "
                    "%{customdata[0]}<br>"
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
st.header("2️⃣ 资产排名概览")

# ─────────────────────────────────────────────────────────────────
#  Section 2.5：竞技场胜出者 (Arena Top-2 Winners)
# ─────────────────────────────────────────────────────────────────
_ARENA_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "arena_history.json")
_arena_hist: dict = {}
# 优先从后端 API 读取（支持 Top-10 候选数据），降级到本地 JSON 离线备用
try:
    _arena_hist = _fetch_arena_history() or {}
except Exception:
    _arena_hist = {}
if not _arena_hist:
    try:
        if os.path.exists(_ARENA_HISTORY_FILE):
            with open(_ARENA_HISTORY_FILE, "r", encoding="utf-8") as _f:
                _raw = json.load(_f)
            _arena_hist = {k: v for k, v in _raw.items() if not k.startswith("_")}
    except Exception:
        pass

if _arena_hist:
    _sorted_months = sorted(
        [k for k in _arena_hist if not k.startswith("_")],
        reverse=True,
    )
    _latest_month = _sorted_months[0] if _sorted_months else None

    def _compute_streaks_p4(cls: str, top_n: int = 3) -> dict:
        """按时间正序遍历，计算每月每个标的在该赛道 Top-N 的连续在榜月数。"""
        _months_asc = sorted(k for k in _arena_hist if not k.startswith("_"))
        _prev_tk: set = set()
        _prev_st: dict = {}
        _res: dict = {}
        for _m in _months_asc:
            _recs = _arena_hist[_m].get(cls, [])[:top_n]
            _cur_tk = {r["ticker"] for r in _recs}
            _cur_st = {}
            for _t in _cur_tk:
                _cur_st[_t] = _prev_st.get(_t, 0) + 1 if _t in _prev_tk else 1
            _res[_m] = _cur_st
            _prev_tk = _cur_tk
            _prev_st = _cur_st
        return _res

    # ── 白盒化管道说明：Top-N → Top-2 筛选逻辑 ──────────────────────
    # 注意：slider 必须在计算之前渲染并捕获返回值，否则换仓历史不会随 N 变化
    st.markdown(
        "<div style='margin-top:24px; margin-bottom:8px;'>"
        "<span style='font-size:18px; font-weight:bold; color:#eee;'>"
        "🔬 选股管道白盒（Top-N → 最终持仓）"
        "</span></div>",
        unsafe_allow_html=True,
    )

    _ARENA_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "arena_config.json")

    def _load_buffer_n() -> int:
        try:
            if os.path.exists(_ARENA_CONFIG_FILE):
                with open(_ARENA_CONFIG_FILE, "r", encoding="utf-8") as _cf:
                    return int(json.load(_cf).get("buffer_n", 3))
        except Exception:
            pass
        return 3

    def _save_buffer_n(n: int) -> None:
        try:
            os.makedirs(os.path.dirname(_ARENA_CONFIG_FILE), exist_ok=True)
            with open(_ARENA_CONFIG_FILE, "w", encoding="utf-8") as _cf:
                json.dump({"buffer_n": n}, _cf)
        except Exception:
            pass

    # ── 检测历史数据实际深度（以最近月份为准，旧月份由切片自动兜底）──
    _latest_depths = []
    if _latest_month and _latest_month in _arena_hist:
        for _c in ["A", "B", "C", "D", "Z"]:
            _recs_depth = _arena_hist[_latest_month].get(_c, [])
            if _recs_depth:
                _latest_depths.append(len(_recs_depth))
    _min_data_depth = min(_latest_depths) if _latest_depths else 3
    _max_buffer_n = max(2, _min_data_depth)

    if SharedKeys.CONFIRMED_BUFFER_N not in st.session_state:
        st.session_state[SharedKeys.CONFIRMED_BUFFER_N] = min(_load_buffer_n(), _max_buffer_n)

    _buf_col, _btn_col, _info_col = st.columns([1, 1, 3])
    with _buf_col:
        _input_n = st.number_input(
            "守擂缓冲区 Top-N",
            min_value=2,
            max_value=_max_buffer_n,
            value=min(st.session_state[SharedKeys.CONFIRMED_BUFFER_N], _max_buffer_n),
            step=1,
            key="arena_buffer_n_input",
            help=(
                f"上期持仓在本月 Top-N 内即保留不换仓（越大越不易触发换仓）。"
                f"当前历史数据每赛道存储深度为 {_min_data_depth} 条，上限受此约束。"
            ),
        )
    with _btn_col:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button("✅ 确认", key="confirm_buffer_n"):
            _clamped_n = min(int(_input_n), _max_buffer_n)
            st.session_state[SharedKeys.CONFIRMED_BUFFER_N] = _clamped_n
            _save_buffer_n(_clamped_n)
            st.toast(f"缓冲区已更新为 Top-{_clamped_n}，历史换仓历史已重算 ✅", icon="🔄")
    _buffer_n: int = st.session_state[SharedKeys.CONFIRMED_BUFFER_N]

    if _min_data_depth <= 3:
        st.warning(
            f"⚠️ **数据深度不足**：历史档案每赛道仅存储 **{_min_data_depth}** 条候选记录，"
            f"守擂缓冲区上限被锁定在 **Top-{_max_buffer_n}**。"
            f"如需支持更大缓冲区，请前往 **Page 3 → 历史回填**（当前代码已配置 Top-10 存储深度，"
            f"重新回填后此上限将自动放开）。",
            icon="🔒",
        )

    with _info_col:
        st.caption(
            f"展示每月如何从 Page 3 竞技场 Top-{_buffer_n} 收窄为最终 Top-2 持仓。"
            f"当前缓冲区 Top-{_buffer_n}（数据深度上限 {_min_data_depth}），"
            "修改数值后点击「确认」重新计算换仓历史。"
            "持仓目标（Top-2）保持不变，只有守擂「宽容度」发生变化。"
        )

    # ── 以 slider 返回值（_buffer_n）驱动下方所有计算 ──────────────
    _all_streaks = {c: _compute_streaks_p4(c, _buffer_n) for c in ["A", "B", "C", "D", "Z"]}

    _holdings_map: dict = {}
    for _cls in ["A", "B", "C", "D", "Z"]:
        _months_asc = sorted(k for k in _arena_hist if not k.startswith("_"))
        _prev_hold: set = set()
        _cls_map: dict = {}
        for _m in _months_asc:
            _recs = _arena_hist[_m].get(_cls, [])
            _t2_set = {r["ticker"] for r in _recs[:2]}
            _t3_set = {r["ticker"] for r in _recs[:_buffer_n]}
            _t2_list = [r["ticker"] for r in _recs[:2]]
            if _prev_hold:
                _survivors = _prev_hold & _t3_set
                if len(_survivors) >= 2:
                    _hold = _survivors
                elif len(_survivors) == 1:
                    _fill = next((r["ticker"] for r in _recs[:_buffer_n] if r["ticker"] not in _survivors), None)
                    _hold = _survivors | {_fill} if _fill else _t2_set
                else:
                    _hold = _t2_set
            else:
                _hold = _t2_set
            # diff=True：守擂生效但 Top-2 已变；traded=True：持仓发生变化
            _cls_map[_m] = {
                "hold": _hold,
                "top2": _t2_list,
                "diff": _hold != _t2_set,
                "traded": bool(_prev_hold) and _hold != _prev_hold,
            }
            _prev_hold = _hold
        _holdings_map[_cls] = _cls_map

    # slot-stable column ordering: keep the same ticker in the same
    # left / right position across consecutive months for visual alignment
    _slot_assignments: dict = {}
    for _cls in ["A", "B", "C", "D", "Z"]:
        _months_asc = sorted(k for k in _arena_hist if not k.startswith("_"))
        _prev_slots: list = [None, None]
        _cls_slots: dict = {}
        for _m in _months_asc:
            _h = _holdings_map[_cls].get(_m, {})
            _hold_set = _h.get("hold", set())
            _new_slots: list = [None, None]
            _assigned: set = set()
            for i in range(2):
                if _prev_slots[i] and _prev_slots[i] in _hold_set:
                    _new_slots[i] = _prev_slots[i]
                    _assigned.add(_prev_slots[i])
            _remaining = sorted(t for t in _hold_set if t not in _assigned)
            for t in _remaining:
                for i in range(2):
                    if _new_slots[i] is None:
                        _new_slots[i] = t
                        break
            _cls_slots[_m] = _new_slots
            _prev_slots = _new_slots
        _slot_assignments[_cls] = _cls_slots

    # 持仓连续月数（ticker 连续出现在 hold 集合中的月数）
    _hold_streaks: dict = {}
    for _cls in ["A", "B", "C", "D", "Z"]:
        _months_asc_h = sorted(k for k in _arena_hist if not k.startswith("_"))
        _prev_hs: set = set()
        _prev_hst: dict = {}
        _cls_hs: dict = {}
        for _m in _months_asc_h:
            _cur_hs = _holdings_map[_cls].get(_m, {}).get("hold", set())
            _cur_hst = {
                _t: (_prev_hst.get(_t, 0) + 1 if _t in _prev_hs else 1)
                for _t in _cur_hs
            }
            _cls_hs[_m] = _cur_hst
            _prev_hs = _cur_hs
            _prev_hst = _cur_hst
        _hold_streaks[_cls] = _cls_hs

    # 规则说明卡片
    st.markdown(
        "<div style='background:#1a1a2e; border:1px solid #3a3a5c; border-radius:8px;"
        " padding:14px 18px; margin-bottom:16px; font-size:13px; color:#ccc; line-height:1.8;'>"
        "<b style='color:#F1C40F; font-size:14px;'>📐 换仓规则（持仓稳定性协议）</b><br>"
        f"① Page 3 竞技场每月产出各赛道 <b>Top-{_buffer_n}</b> 综合评分排名（缓冲区大小可调）。<br>"
        f"② 若上月持仓的所有标的仍出现在本月 Top-{_buffer_n} 之内，则 <b style='color:#2ECC71;'>维持不动（信念守擂制）</b>——"
        f"在位者只要守住 Top-{_buffer_n} 席位即可保留持仓，减少无谓换手。<br>"
        "③ 若任意一只持仓跌出缓冲区，则全部换仓，采用本月 <b style='color:#F39C12;'>Top-2</b> 作为新持仓。<br>"
        "④ 历史表格中 <code>[Top2→X/Y]</code> 标注代表当月 <b style='color:#E67E22;'>守擂生效</b>——上月持仓仍在缓冲区内未触发换仓，"
        "但 Top-2 排名已更新为 X/Y，括号内为本期真实前两名供参考。"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div style='margin-top:24px; margin-bottom:8px; display:flex; align-items:center; gap:12px;'>"
        "<span style='font-size:18px; font-weight:bold; color:#eee;'>"
        f"📅 历史月度 Top-2 胜出者（共 {len(_sorted_months)} 个月）"
        "</span>"
        f"<span style='font-size:13px; font-weight:600; color:#F1C40F; "
        f"background:#2e2400; border:1px solid #F1C40F55; border-radius:999px; "
        f"padding:2px 12px;'>守擂缓冲区：Top-{_buffer_n}</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── 彩色 HTML 表格：绿=稳居前二无守擂压力，默认=守擂中（在前三属于正常） ──
    _th_style = (
        "padding:8px 12px; border-bottom:1px solid #333; "
        "text-align:left; background:#1a1a1a; white-space:nowrap;"
    )
    _td_style = "padding:7px 12px; border-bottom:1px solid #222; white-space:nowrap;"

    _tbl = [
        "<table style='width:100%; border-collapse:collapse; font-size:13px;'>",
        "<thead><tr>",
        "<th style='" + _th_style + " color:#aaa;'>月份</th>",
    ]
    for _cls in ["A", "B", "C", "D", "Z"]:
        _m = CLASS_META[_cls]
        _mc = _m["color"]
        _tbl.append(
            "<th style='" + _th_style + " color:" + _mc + ";'>"
            + _m["icon"] + " " + _cls + " 持仓</th>"
        )
    _tbl.append("</tr></thead><tbody>")

    for _mo in _sorted_months:
        _entry = _arena_hist[_mo]
        _tbl.append("<tr>")
        _tbl.append(
            "<td style='" + _td_style + " color:#ddd; font-weight:600;'>" + _mo + "</td>"
        )
        for _cls in ["A", "B", "C", "D", "Z"]:
            _h = _holdings_map[_cls].get(_mo, {})
            _hold_set = _h.get("hold", set())
            _t2_list = _h.get("top2", [])
            _is_diff = _h.get("diff", False)
            _mo_st = _hold_streaks[_cls].get(_mo, {})

            _all_recs = _entry.get(_cls, [])[:_buffer_n]
            _rec_map = {r["ticker"]: r for r in _all_recs if r["ticker"] in _hold_set}
            _slots = _slot_assignments[_cls].get(_mo, [None, None])

            _t2_set = set(_t2_list)
            _slot_spans = ["", ""]
            for _si, _slot_tk in enumerate(_slots):
                if not _slot_tk or _slot_tk not in _rec_map:
                    continue
                _s = _mo_st.get(_slot_tk, 0)
                _txt = _slot_tk + "(" + str(_s) + "月)"
                if not _is_diff:
                    _slot_spans[_si] = "<span style='color:#ddd;'>" + _txt + "</span>"
                elif _slot_tk not in _t2_set:
                    _slot_spans[_si] = (
                        "<span style='color:#E74C3C; font-weight:600;'>" + _txt + "</span>"
                    )
                else:
                    _slot_spans[_si] = (
                        "<span style='color:#2ECC71; font-weight:600;'>" + _txt + "</span>"
                    )

            if not _slot_spans[0] and not _slot_spans[1]:
                _cell_html = "<span style='color:#555;'>—</span>"
            else:
                _cell_html = (
                    "<span style='display:inline-block; min-width:105px;'>"
                    + (_slot_spans[0] or "&nbsp;") + "</span>"
                    + _slot_spans[1]
                )
            if _is_diff and _t2_list:
                _cell_html += (
                    " <span style='color:#E67E22; font-size:12px;'>"
                    "[Top2→" + "/".join(_t2_list) + "]</span>"
                )
            _tbl.append("<td style='" + _td_style + "'>" + _cell_html + "</td>")
        _tbl.append("</tr>")

    _tbl.append("</tbody></table>")

    st.markdown(
        "<div style='overflow-x:auto; max-height:600px; overflow-y:auto; "
        "border:1px solid #2a2a2a; border-radius:6px;'>"
        + "".join(_tbl)
        + "</div>",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ─────────────────────────────────────────────────────────────────
#  Section 3：资产详情查询面板
# ─────────────────────────────────────────────────────────────────
st.header("3️⃣ 资产深度查询 (Asset Intelligence Panel)")

# 深度查询候选池：使用全量 df_all，不受侧边栏类别过滤限制
# Z 类优先保留（许多资产同时属于 A+Z，需先提取 Z 行再去重）
_z_pool = (
    df_all[df_all["类别"] == "Z"]
    .drop_duplicates(subset="Ticker")
)
_z_tickers = set(_z_pool["Ticker"].tolist())
_non_z_pool = (
    df_all[df_all["类别"] != "Z"]
    .drop_duplicates(subset="Ticker", keep="first")
    .pipe(lambda d: d[~d["Ticker"].isin(_z_tickers)])
)
df_show_unique = pd.concat([_non_z_pool, _z_pool], ignore_index=True)

if df_show_unique.empty:
    st.info("当前无可查询资产。")
    st.stop()

# 下拉选项：Ticker | 名称 | 所有符合级别
options = []
for _, row in df_show_unique.iterrows():
    badges = row.get("all_grades", row["类别"])
    meta = CLASS_META[row["类别"]]
    options.append(f"{row['Ticker']}  |  {row['名称']}  |  {meta['icon']} {badges}")

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
sel_row    = df_show_unique[df_show_unique["Ticker"] == sel_ticker].iloc[0]
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
