import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from api_client import (
    fetch_macro_radar,
    fetch_macro_radar_timeseries,
    fetch_current_regime,
    get_global_data,
    compute_macro_regime_api,
    fetch_changepoint,
    fetch_sector_rotation,
    fetch_etf_meta,
    fetch_dynasty_leaders,
)
import holdings_viz as hv

st.set_page_config(page_title="宏观雷达", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
    .insight-section { margin-top: 10px; font-size: 14px; color: #ddd; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .logic-text { color: #aaa; font-style: italic; margin-left: 5px; }
    .key-point { font-weight: bold; color: #fff; }
</style>
""", unsafe_allow_html=True)

st.title("🔭 宏观雷达 (Macro Radar)")
st.caption("市场结构总览 · 全景雷达 · 趋势状态机 · 传导链 · 变点检测 · 分化证据链 · 主力归因")

# --- 侧边栏缓存控制 ---
with st.sidebar:
    if st.button("🔄 强制刷新雷达数据"):
        fetch_macro_radar.clear()
        fetch_macro_radar_timeseries.clear()   # streamlit cache_data 按参数自动分桶，clear 一次即清所有 window
        fetch_current_regime.clear()
        compute_macro_regime_api.clear()
        get_global_data.clear()
        fetch_changepoint.clear()
        fetch_sector_rotation.clear()
        fetch_etf_meta.clear()
        fetch_dynasty_leaders.clear()
        st.rerun()

# ============================================================
# 主升浪识别（ZigZag 思路，事后回看一次扫描，无未来函数）
# 反向回撤超过 swing 才确认上升段结束。swing 按窗口振幅 × 比例自适应，
# 过滤"震荡中的小上涨"，只保留大结构主升浪。
# ============================================================
def _zigzag_up_mask(values: np.ndarray, swing: float) -> np.ndarray:
    n = len(values)
    mask = np.zeros(n, dtype=bool)
    if n < 2 or swing <= 0:
        return mask
    first = 0
    while first < n and not np.isfinite(values[first]):
        first += 1
    if first >= n - 1:
        return mask
    hi_idx = lo_idx = first
    hi_val = lo_val = float(values[first])
    trend = 0
    seg_start = first
    for i in range(first + 1, n):
        v = values[i]
        if not np.isfinite(v):
            continue
        v = float(v)
        if trend == 0:
            if v > hi_val: hi_idx, hi_val = i, v
            if v < lo_val: lo_idx, lo_val = i, v
            if hi_val - lo_val >= swing:
                if lo_idx < hi_idx:
                    trend = +1
                    seg_start = lo_idx
                else:
                    trend = -1
                    seg_start = hi_idx
        elif trend == +1:
            if v > hi_val:
                hi_idx, hi_val = i, v
            elif hi_val - v >= swing:
                mask[seg_start:hi_idx + 1] = True
                trend = -1
                seg_start = hi_idx
                lo_idx, lo_val = i, v
        else:
            if v < lo_val:
                lo_idx, lo_val = i, v
            elif v - lo_val >= swing:
                trend = +1
                seg_start = lo_idx
                hi_idx, hi_val = i, v
    if trend == +1:
        mask[seg_start:hi_idx + 1] = True
    return mask


# ============================================================
# 数据层（四个 section 共享）
# ============================================================
_PAGE_TICKERS = [
    "SPY", "QQQ", "RSP", "MAGS", "IJH", "IWM",
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLE",
    "XLI", "XLB", "XLU", "XLRE", "XLC",
]

_WAVE_TAB_WINDOWS = ["1M", "3M", "6M", "1Y", "5Y", "10Y"]

with st.spinner("📊 加载市场结构数据..."):
    df_prices       = get_global_data(_PAGE_TICKERS, years=10)
    _radar          = fetch_macro_radar()
    # 6 个 tab 各 fetch 一次（后端按 window 用不同 RS/Z 窗口计算）
    _radar_ts_by_window = {
        w: fetch_macro_radar_timeseries(window=w) for w in _WAVE_TAB_WINDOWS
    }
    _current_regime = fetch_current_regime()
    _chain_regime   = compute_macro_regime_api(z_window=750)
    _cp             = fetch_changepoint()
    _sr             = fetch_sector_rotation()
    _etf_meta       = fetch_etf_meta()

# 变点检测「确认信号」日期集（单日 n_t≥K），用于 §2 MTM 主图底部紫色竖杠。
# 严格按后端 timeline.level 字段筛，不在前端重算 streak，避免与 §2.6 数值漂移。
_cp_confirm_dates = pd.DatetimeIndex([])
_cp_K_global = int((_cp.get("constants") or {}).get("K", 5)) if _cp.get("success") else 5
if _cp.get("success"):
    _tl_cp_raw = _cp.get("timeline", []) or []
    if _tl_cp_raw:
        _cp_confirm_dates = pd.to_datetime(
            [t["date"] for t in _tl_cp_raw if t.get("level") == "确认信号"],
            errors="coerce",
        ).dropna()

# ============================================================
# Section 1: 宏观全景雷达（保留原散点图）
# ============================================================
st.markdown("---")
st.header("🎯 宏观全景雷达 (Sector Panoramic)")
st.caption("双维监控：横轴【估值 Z-Score】，纵轴【相对强度 RS】。")

if not _radar.get("success") or not _radar.get("metrics"):
    st.warning("⚠️ 雷达数据暂不可用，请检查后端连接或稍后刷新。")
else:
    df_metrics    = pd.DataFrame(_radar["metrics"])
    benchmark_mom = float(_radar.get("spy_mom20", 0.0))
    _insights     = _radar.get("insights", {})

    def _render_insight_html(group_name: str, df_group: pd.DataFrame, plain_text: str) -> str:
        df_sorted = df_group.sort_values("相对强度", ascending=False)
        leaders   = df_sorted.head(3)
        laggards  = df_sorted.tail(3)
        leader_html  = " ".join([f"<span class='tag-bull'>{r['名称']}</span>" for _, r in leaders.iterrows()])
        laggard_html = " ".join([f"<span class='tag-bear'>{r['名称']}</span>" for _, r in laggards.iterrows()])
        parts = plain_text.split(" | ") if plain_text else []
        analysis_text     = parts[1] if len(parts) > 1 else "数据特征不明显，维持中性观察。"
        macro_implication = parts[2].replace("宏观含义: ", "") if len(parts) > 2 else "暂无明确宏观指向。"
        return f"""
<div class='insight-box'>
<div class='insight-title'>🧠 深度归因 (Deep Insight): {group_name.split(':')[0]}</div>
<div style='display:flex; gap:24px; align-items:center; margin-bottom:10px; flex-wrap:wrap'>
<div>🚀 领涨: {leader_html}</div>
<div>🥀 领跌: {laggard_html}</div>
</div>
<div class='insight-section'>
<span class='key-point'>🧐 现象解读:</span> {analysis_text}
</div>
<div class='insight-section' style='margin-top:5px'>
<span class='key-point'>🌍 宏观启示:</span> <span class='logic-text'>{macro_implication}</span>
</div>
</div>
"""

    with st.sidebar:
        st.header("资产筛选")
        st.metric("基准 (SPY) 20日涨跌", f"{benchmark_mom:.2f}%")
        all_groups = df_metrics["组别"].unique().tolist() if not df_metrics.empty else []
        default_groups = [g for g in ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"] if g in all_groups]
        selected_groups = st.multiselect("显示资产组别：", all_groups, default=default_groups)

    if df_metrics.empty:
        st.warning("暂无数据")
    else:
        df_plot = df_metrics[df_metrics["组别"].isin(selected_groups)] if selected_groups else df_metrics

        fig_radar = px.scatter(
            df_plot, x="Z-Score", y="相对强度", color="相对强度", text="名称",
            hover_data={"代码": True, "趋势结构": True, "Z-Score": ":.2f", "相对强度": ":.2f", "名称": False, "相对强度": False},
            color_continuous_scale="RdYlGn", range_color=[-10, 10]
        )

        fig_radar.add_hline(y=0, line_dash="dash", line_color="#FFFFFF", opacity=0.5)
        fig_radar.add_vline(x=0, line_dash="dash", line_color="#FFFFFF", opacity=0.3)
        fig_radar.update_traces(textposition="top center", marker=dict(size=10, opacity=0.9))

        fig_radar.add_annotation(x=2,  y=5,  text="领涨/拥挤\n(减仓)",  showarrow=False, font=dict(color="#E74C3C", size=10))
        fig_radar.add_annotation(x=-2, y=-5, text="滞涨/弱势\n(观察)",  showarrow=False, font=dict(color="#3498DB", size=10))
        fig_radar.add_annotation(x=-2, y=5,  text="抗跌/启动\n(加仓)",  showarrow=False, font=dict(color="#2ECC71", size=10))
        fig_radar.add_annotation(x=2,  y=-5, text="补跌/崩盘\n(离场)",  showarrow=False, font=dict(color="#E67E22", size=10))

        fig_radar.update_layout(
            height=600, plot_bgcolor="#111111", paper_bgcolor="#111111",
            font=dict(color="#ddd"),
            xaxis_title="便宜 (低 Z-Score) <---> 昂贵",
            yaxis_title="弱于大盘 <---> 强于大盘",
        )
        st.plotly_chart(fig_radar, use_container_width=True)

        for group in selected_groups:
            df_sub = df_metrics[df_metrics["组别"] == group]
            plain  = _insights.get(group, "")
            st.markdown(_render_insight_html(group, df_sub, plain), unsafe_allow_html=True)

        st.markdown("### 📋 详细数据表 (Trend Structure)")

        def color_structure(val):
            if "长牛" in val: return "color: #2ECC71; font-weight: bold"
            if "熊市" in val: return "color: #E74C3C"
            if "反弹" in val: return "color: #F1C40F"
            return "color: #aaa"

        st.dataframe(
            df_plot.sort_values("相对强度", ascending=False).style.map(
                color_structure, subset=["趋势结构"]
            ).format({"Z-Score": "{:.2f}", "相对强度": "{:.2f}", "L/VL": "{:.2f}"}),
            use_container_width=True, hide_index=True
        )

    # ── §1.5 板块强势波形 (Sector Strength Waveform) — RS + Z ────────
    # 强势 = 横截面标准化(RS) + 横截面标准化(Z)，看「主升浪在哪」(跟随，接近顶部要警惕)
    # 摘要叠加「💎 黄金 / ⚠️ 高估」标签 = 横截面标准化(RS) − 横截面标准化(Z) 排序 Top3 / Bottom3
    st.markdown("---")
    st.markdown("### 📈 板块强势波形 (Sector Strength Waveform) — RS + Z")
    st.caption(
        "**强势分 = 横截面标准化(RS) + 横截面标准化(Z)**（每天对所有板块的 RS / Z 各做 Z-Score 再相加，两个维度平权，量级 ±3，5 日 EMA 平滑）· "
        "**用途**：看「主升浪在哪」——跟随强势，但接近顶部要警惕，配合摘要里的「💎 黄金板块」/「⚠️ 高估警告」做交叉验证 · "
        "**窗口随 tab 缩放**：短 tab 用快窗口看择时（RS_20d/Z_250d）、长 tab 用慢窗口看大周期（RS_252d/Z_750d）· "
        "Y 轴正值 = 在当天 universe 里相对强势，负值 = 相对弱势 · "
        "**着色**：每条板块自身的**主升浪段彩色高亮**（ZigZag 识别，反向回撤超过自身振幅 15% 才算段结束 + 段长门槛过滤短段），震荡 / 下跌段淡灰显示，事后回看无未来函数"
    )

    if not selected_groups:
        st.info("👈 请在侧边栏勾选至少一个组别")
    else:
        _PALETTE = px.colors.qualitative.Light24

        _tab_1m, _tab_3m, _tab_6m, _tab_1y, _tab_5y, _tab_10y = st.tabs([
            "📅 近 1 个月 (1M)", "📅 近 3 个月 (3M)",
            "📅 近 6 个月 (6M)", "📅 近 1 年 (1Y)",
            "📅 近 5 年 (5Y)",   "📅 近 10 年 (10Y)",
        ])

        def _render_wave_tab(
            window_name, tab, *,
            composite_field: str = "composite",
            mode_label: str = "强势",      # 标题前缀（"强势" / "潜力"）
            formula_op: str = "+",         # "+" / "−"（U+2212 真减号）
            hover_label: str = "强势分",   # hover / Y 轴 / 摘要里的字段名
        ):
            with tab:
                _radar_ts = _radar_ts_by_window.get(window_name, {})
                if not _radar_ts.get("success"):
                    st.warning(f"⚠️ {window_name} 时序数据暂不可用：{_radar_ts.get('error', '未知错误')}")
                    return
                _ts_tickers = _radar_ts.get("tickers", {}) or {}
                _ts_dates_raw = _radar_ts.get("dates", []) or []
                if not _ts_tickers or not _ts_dates_raw:
                    st.warning(f"⚠️ {window_name} 后端时序数据为空")
                    return

                _picked = {
                    tk: payload for tk, payload in _ts_tickers.items()
                    if payload.get("group", "") in selected_groups
                }
                if not _picked:
                    st.warning(f"⚠️ {window_name}: 选中组别在时序数据中无可用 ticker")
                    return

                _ts_dates = pd.to_datetime(_ts_dates_raw, errors="coerce")
                _comp_df = pd.DataFrame(
                    {tk: p.get(composite_field, []) for tk, p in _picked.items()},
                    index=_ts_dates,
                ).astype(float)
                _rs_df = pd.DataFrame(
                    {tk: p.get("rs", []) for tk, p in _picked.items()},
                    index=_ts_dates,
                ).astype(float)
                _z_df = pd.DataFrame(
                    {tk: p.get("z", []) for tk, p in _picked.items()},
                    index=_ts_dates,
                ).astype(float)
                _pot_df = pd.DataFrame(
                    {tk: p.get("composite_value", []) for tk, p in _picked.items()},
                    index=_ts_dates,
                ).astype(float)
                _comp_smooth_df = _comp_df.ewm(span=5, adjust=False).mean()
                _pot_smooth_df  = _pot_df.ewm(span=5, adjust=False).mean()
                _rank_df = _comp_df.rank(axis=1, ascending=False, method='min').dropna(how="all")

                _name_map = {tk: p.get("name", tk) for tk, p in _picked.items()}
                _n_pool   = len(_picked)
                _rs_w     = _radar_ts.get("rs_window", "?")
                _z_w      = _radar_ts.get("z_window", "?")

                if _comp_smooth_df.empty or len(_comp_smooth_df) < 2:
                    st.warning(f"⚠️ {window_name} 窗口数据不足")
                    return

                # legend 按当前复合分（最后一日，平滑后）降序——强者排在 legend 顶部
                _curr_score = _comp_smooth_df.iloc[-1].dropna().sort_values(ascending=False)
                _tickers_sorted = _curr_score.index.tolist()

                # 主升浪识别：每条板块独立 ZigZag，swing = max(0.5, 自身振幅 × 15%)
                # 再加最短段长门槛——连续 True 段太短直接刷回 False，消除"小蚯蚓"
                # composite 改横截面标准化后量级 ±3，所以 swing floor 从 5.0 → 0.5
                _SWING_FRAC = 0.15
                _SWING_FLOOR = 0.5
                _MIN_SEG_DAYS = {
                    "1M": 3, "3M": 5, "6M": 10, "1Y": 15, "5Y": 25, "10Y": 40,
                }.get(window_name, 10)
                _up_mask_df = pd.DataFrame(
                    False, index=_comp_smooth_df.index, columns=_comp_smooth_df.columns
                )
                for _tk in _comp_smooth_df.columns:
                    _s = _comp_smooth_df[_tk].to_numpy(dtype=float)
                    _finite = _s[np.isfinite(_s)]
                    if len(_finite) >= 2:
                        _amp = float(_finite.max() - _finite.min())
                        _swing = max(_SWING_FLOOR, _SWING_FRAC * _amp)
                        _mask = _zigzag_up_mask(_s, _swing)
                        if _MIN_SEG_DAYS > 1:
                            _padded = np.concatenate(([False], _mask, [False]))
                            _runs = np.diff(_padded.astype(int))
                            _starts = np.where(_runs == 1)[0]
                            _ends   = np.where(_runs == -1)[0]
                            for _a, _b in zip(_starts, _ends):
                                if _b - _a < _MIN_SEG_DAYS:
                                    _mask[_a:_b] = False
                        _up_mask_df[_tk] = _mask

                # 当日排名仅供 hover 显示（与着色解耦）
                _rank_smooth_df = _comp_smooth_df.rank(axis=1, ascending=False, method='min')

                # 默认彩色集 = top 5 强者（当前复合分）+ rising 2 黑马（排名上升）
                # 其余板块淡灰 + legend 默认隐藏，点击 legend 可临时展开
                _TOP_N = 5
                _RISING_N = 2
                _top_strong = _tickers_sorted[:_TOP_N]
                if len(_rank_df) >= 2:
                    _start_rank = _rank_df.iloc[0]
                    _end_rank   = _rank_df.iloc[-1]
                    _delta = (_start_rank - _end_rank).dropna()   # 正 = 排名上升
                    _delta_sorted = _delta.sort_values(ascending=False)
                    _top_rising = [
                        tk for tk in _delta_sorted.index
                        if _delta_sorted[tk] > 0 and tk not in _top_strong
                    ][:_RISING_N]
                else:
                    _delta = None
                    _delta_sorted = None
                    _top_rising = []
                _color_set = set(_top_strong) | set(_top_rising)

                _legend_order = _top_strong + _top_rising + [
                    tk for tk in _tickers_sorted if tk not in _color_set
                ]

                _top_names = "、".join(_name_map.get(tk, tk) for tk in _top_strong)
                _rising_names = "、".join(_name_map.get(tk, tk) for tk in _top_rising) or "—"
                st.caption(
                    f"📌 默认彩色：**强者 Top{len(_top_strong)}**（{_top_names}）"
                    f" + **黑马 Rising{len(_top_rising)}**（{_rising_names}）· "
                    f"其余 {_n_pool - len(_color_set)} 个板块淡显，点击右侧图例可展开"
                )

                fig_wave = go.Figure()
                for i, tk in enumerate(_legend_order):
                    _is_color = tk in _color_set
                    _color = _PALETTE[i % len(_PALETTE)]
                    _y_full = _comp_smooth_df[tk].values
                    _mask = _up_mask_df[tk].values
                    _y_up   = np.where(_mask,  _y_full, np.nan)
                    _y_rest = np.where(~_mask, _y_full, np.nan)
                    _cust = np.stack([
                        _comp_df[tk].values,
                        _rs_df[tk].values,
                        _z_df[tk].values,
                        _rank_smooth_df[tk].values,
                    ], axis=-1)
                    if _is_color:
                        _rest_color = 'rgba(150,150,150,0.18)'
                        _rest_width = 0.8
                        _up_color   = _color
                        _up_width   = 1.8
                        _visible    = True
                    else:
                        _rest_color = 'rgba(150,150,150,0.08)'
                        _rest_width = 0.6
                        _up_color   = 'rgba(150,150,150,0.08)'
                        _up_width   = 0.6
                        _visible    = 'legendonly'
                    _hover_up = (
                        f"<b>{_name_map.get(tk, tk)}</b> ({tk})  🟢 主升浪<br>"
                        "%{x|%Y-%m-%d}<br>"
                        f"{hover_label}(平滑) " "%{y:+.2f}<br>"
                        f"当日排名 第%{{customdata[3]:.0f}} / {_n_pool}<br>"
                        f"{hover_label}(原始) " "%{customdata[0]:+.2f}<br>"
                        f"RS_{_rs_w}d " "%{customdata[1]:+.2f}%<br>"
                        f"Z_{_z_w}d "  "%{customdata[2]:+.2f}"
                        "<extra></extra>"
                    )
                    _hover_rest = (
                        f"<b>{_name_map.get(tk, tk)}</b> ({tk})  ⚪ 震荡/下跌<br>"
                        "%{x|%Y-%m-%d}<br>"
                        f"{hover_label}(平滑) " "%{y:+.2f}<br>"
                        f"当日排名 第%{{customdata[3]:.0f}} / {_n_pool}<br>"
                        f"{hover_label}(原始) " "%{customdata[0]:+.2f}<br>"
                        f"RS_{_rs_w}d " "%{customdata[1]:+.2f}%<br>"
                        f"Z_{_z_w}d "  "%{customdata[2]:+.2f}"
                        "<extra></extra>"
                    )
                    fig_wave.add_trace(go.Scatter(
                        x=_comp_smooth_df.index,
                        y=_y_rest,
                        mode='lines',
                        name=_name_map.get(tk, tk),
                        legendgroup=tk,
                        showlegend=False,
                        visible=_visible,
                        line=dict(color=_rest_color, width=_rest_width),
                        customdata=_cust,
                        hovertemplate=_hover_rest,
                        connectgaps=False,
                    ))
                    fig_wave.add_trace(go.Scatter(
                        x=_comp_smooth_df.index,
                        y=_y_up,
                        mode='lines',
                        name=_name_map.get(tk, tk),
                        legendgroup=tk,
                        visible=_visible,
                        line=dict(color=_up_color, width=_up_width),
                        customdata=_cust,
                        hovertemplate=_hover_up,
                        connectgaps=False,
                    ))

                fig_wave.add_hline(
                    y=0, line_dash="dash", line_color="rgba(255,255,255,0.35)",
                    annotation_text="基准 (= SPY)", annotation_position="right",
                )

                fig_wave.update_layout(
                    height=520,
                    margin=dict(l=20, r=20, t=40, b=20),
                    plot_bgcolor='#111111', paper_bgcolor='#111111',
                    font=dict(color='#ddd'),
                    hovermode="closest",
                    legend=dict(orientation="v", y=1.0, x=1.02, font=dict(size=11)),
                    xaxis=dict(showgrid=False),
                    yaxis=dict(
                        title=f"{hover_label} = 横截面标准化(RS_{_rs_w}d) {formula_op} 横截面标准化(Z_{_z_w}d)（越高越强）",
                        zeroline=False,
                        showgrid=True, gridcolor='rgba(255,255,255,0.06)',
                    ),
                    title=dict(
                        text=f"{window_name} {mode_label}波形 · RS_{_rs_w}d {formula_op} Z_{_z_w}d · 共 {_n_pool} 个板块",
                        font=dict(size=14), x=0.01, xanchor='left',
                    ),
                )
                st.plotly_chart(fig_wave, use_container_width=True)

                if _delta is not None and len(_delta) >= 1:
                    _delta_df = pd.DataFrame({
                        "板块":     [_name_map.get(tk, tk) for tk in _delta.index],
                        "代码":     _delta.index,
                        "起点排名": _start_rank.reindex(_delta.index).values,
                        "当前排名": _end_rank.reindex(_delta.index).values,
                        "排名变化": _delta.values,
                    }).dropna().sort_values("排名变化", ascending=False)
                    _ups = _delta_df.head(3)
                    _dns = _delta_df.tail(3).iloc[::-1]

                    _ups_html = " ".join([
                        f"<span class='tag-bull'>{r['板块']} #{int(r['起点排名'])}→#{int(r['当前排名'])} (+{int(r['排名变化'])})</span>"
                        for _, r in _ups.iterrows() if r["排名变化"] > 0
                    ]) or "—"
                    _dns_html = " ".join([
                        f"<span class='tag-bear'>{r['板块']} #{int(r['起点排名'])}→#{int(r['当前排名'])} ({int(r['排名变化'])})</span>"
                        for _, r in _dns.iterrows() if r["排名变化"] < 0
                    ]) or "—"

                    # 潜力分用后端 composite_value（RS 横截面 Z − Z 横截面 Z），取末日 5 日 EMA 后做排名
                    _curr_pot = _pot_smooth_df.iloc[-1].dropna().sort_values(ascending=False)
                    _golden_html = " ".join([
                        f"<span class='tag-bull'>{_name_map.get(tk, tk)} {v:+.2f}</span>"
                        for tk, v in _curr_pot.head(3).items()
                    ]) or "—"
                    _overheated_html = " ".join([
                        f"<span class='tag-bear'>{_name_map.get(tk, tk)} {v:+.2f}</span>"
                        for tk, v in _curr_pot.tail(3).iloc[::-1].items()
                    ]) or "—"

                    st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>🌊 {mode_label}波形轮动摘要 ({window_name} 窗口 · RS_{_rs_w}d {formula_op} Z_{_z_w}d)</div>
<div style='display:flex; gap:24px; align-items:center; margin-bottom:6px; flex-wrap:wrap'>
<div>🚀 排名上升 Top3: {_ups_html}</div>
<div>🥀 排名下降 Top3: {_dns_html}</div>
</div>
<div style='display:flex; gap:24px; align-items:center; margin-bottom:6px; flex-wrap:wrap'>
<div>💎 黄金板块 Top3（强且便宜，RS−Z 高）: {_golden_html}</div>
<div>⚠️ 高估警告 Top3（强但贵，RS−Z 低）: {_overheated_html}</div>
</div>
<div class='insight-section' style='font-size:13px; color:#888;'>
读法：<b style='color:#aaa;'>线在 0 上方</b> = 强于基准 SPY；<b style='color:#aaa;'>线在 0 下方</b> = 弱于基准。<b style='color:#aaa;'>波形抬升</b> = {mode_label}在增强（资金轮入）；<b style='color:#aaa;'>波形下沉</b> = {mode_label}走弱（资金离开）。<b style='color:#aaa;'>💎 黄金</b> = RS 高 + Z 低（强且便宜，买入候选）；<b style='color:#aaa;'>⚠️ 高估</b> = RS 高 + Z 高（已涨贵，警惕回调）。<b>本 tab 窗口</b>：RS={_rs_w} 日动量、Z={_z_w} 日估值偏离。
</div>
</div>
""", unsafe_allow_html=True)

        for _w, _t in zip(_WAVE_TAB_WINDOWS, (_tab_1m, _tab_3m, _tab_6m, _tab_1y, _tab_5y, _tab_10y)):
            _render_wave_tab(
                _w, _t,
                composite_field="composite",
                mode_label="强势",
                formula_op="+",
                hover_label="强势分",
            )

    # ── §1.6 板块王朝接力图 (Dynasty Relay) — 月末 Top1/Top3 染色 ─────
    # 主图按 king_score 排名 = w_rs×Z(rs) + w_cap×Z(log10(adv_63d))
    # 动量 + 容量两维,对应「时代之王 = 涨得多 + 大资金能进出」
    st.markdown("---")
    st.markdown("### 👑 板块王朝接力图 (Dynasty Relay) — 月末 Top1/Top3 染色")
    st.caption(
        "**规则**:每月末对 25 个板块做横截面排名,**Top1 = 🥇 金 / Top2-3 = 🥈 银 / 其他 = ⚪ 灰** · "
        "**加冕门槛**:Top1 + RS_252d > 0(年化跑赢 SPY)才戴金,否则降为灰——熊市无王 · "
        "**主图排序指标 king_score = 1.0×Z(RS_252d) + 0.8×Z(log10 ADV_63d)** —— 两项都做横截面 Z-Score 再加权,对应「动量 + 容量」。**容量项把 URA/TAN 这类小众主题盘压下去**,机构盘(XL*/SMH/IGV)容量项加分 · "
        "**ADV 逐月动态**:每月用当月过去 63 日 (Close × Volume) 均值,**不是用当前快照穿越历史** · "
        "**用途**:找「时代之王」——连续戴金且容量充足 = 真王朝。hover 里有当月 ADV_63d + 当前 AUM 快照(AUM 历史 yfinance 拿不到,只展示不进算法)"
    )

    _dynasty_window = st.radio(
        "时间跨度",
        options=["5Y", "10Y"],
        horizontal=True,
        key="dynasty_window",
        help="5Y = 60 个月格子 / 10Y = 120 个月格子",
    )

    _dyn_tab1, _dyn_tab2 = st.tabs(["👑 王朝接力图", "🏆 王朝龙头股"])
    with _dyn_tab1:
        if not selected_groups:
            st.info("👈 请在侧边栏勾选至少一个组别以渲染王朝图")
        else:
            _dyn_ts = _radar_ts_by_window.get(_dynasty_window, {}) or {}
            if not _dyn_ts.get("success"):
                st.warning(f"⚠️ {_dynasty_window} 时序数据暂不可用:{_dyn_ts.get('error', '未知错误')}")
            else:
                _dyn_tickers = _dyn_ts.get("tickers", {}) or {}
                _dyn_dates_raw = _dyn_ts.get("dates", []) or []
                _picked_d = {
                    tk: p for tk, p in _dyn_tickers.items()
                    if p.get("group", "") in selected_groups
                }
                if not _picked_d or not _dyn_dates_raw:
                    st.warning(f"⚠️ {_dynasty_window}:选中组别在时序数据中无可用 ticker")
                else:
                    _dyn_idx = pd.to_datetime(_dyn_dates_raw, errors="coerce")
                    _d_rs = pd.DataFrame(
                        {tk: p.get("rs", []) for tk, p in _picked_d.items()},
                        index=_dyn_idx,
                    ).astype(float)
                    _d_king = pd.DataFrame(
                        {tk: p.get("king_score", []) for tk, p in _picked_d.items()},
                        index=_dyn_idx,
                    ).astype(float)
                    _d_adv_hist = pd.DataFrame(
                        {tk: p.get("adv_63d", []) for tk, p in _picked_d.items()},
                        index=_dyn_idx,
                    ).astype(float)
                    _d_name_map = {tk: p.get("name", tk) for tk, p in _picked_d.items()}
                    _king_w = _dyn_ts.get("king_score_weights", {"rs": 1.0, "cap": 0.8})

                    # ETF AUM + ADV 标注(机构容量维度,辨别真王朝 vs 小众短命王)
                    _etf_info = _etf_meta.get("tickers", {}) if _etf_meta.get("success") else {}

                    def _fmt_usd(x):
                        if x is None or not isinstance(x, (int, float)) or x <= 0:
                            return "—"
                        if x >= 1e9:
                            return f"${x/1e9:.1f}B"
                        elif x >= 1e6:
                            return f"${x/1e6:.0f}M"
                        else:
                            return f"${x/1e3:.0f}k"

                    # 前端自算 RS_63d(后端 5Y/10Y window 只提供 RS_252d)
                    # 公式与 macro_engine 一致: RS_63d = ETF 63d 动量 − SPY 63d 动量
                    # 用途: 加冕门槛的「最近 3 月仍跑赢 SPY」过滤,防止 URA 这类登顶横盘仍戴金
                    _RS63_WIN = 63
                    _d_rs63 = None
                    if (
                        df_prices is not None
                        and not df_prices.empty
                        and "SPY" in df_prices.columns
                        and len(df_prices) > _RS63_WIN + 5
                    ):
                        _spy_p = df_prices["SPY"].astype(float)
                        _spy_mom63 = (_spy_p / _spy_p.shift(_RS63_WIN + 1) - 1.0) * 100.0
                        _rs63_cols = {}
                        for tk in _picked_d:
                            if tk in df_prices.columns:
                                _etf_p = df_prices[tk].astype(float)
                                _etf_mom63 = (_etf_p / _etf_p.shift(_RS63_WIN + 1) - 1.0) * 100.0
                                _rs63_cols[tk] = (_etf_mom63 - _spy_mom63).reindex(_dyn_idx)
                            else:
                                _rs63_cols[tk] = pd.Series(np.nan, index=_dyn_idx)
                        _d_rs63 = pd.DataFrame(_rs63_cols, index=_dyn_idx).astype(float)

                    # 王朝接力净值用价格:dynasty ETF 不全在 _PAGE_TICKERS,单独拉
                    # 一次(yfinance,缓存 4h)。周线 Close 喂 holdings_viz(同 Page 6 持仓对比)。
                    _dyn_px = get_global_data(sorted(_picked_d.keys()) + ["SPY"], years=10)
                    _dyn_price_cache: dict = {}
                    _dyn_spy_wk = pd.DataFrame()
                    if _dyn_px is not None and not _dyn_px.empty:
                        _dyn_wk = _dyn_px.resample("W-FRI").last()
                        if "SPY" in _dyn_wk.columns:
                            _dyn_spy_wk = (
                                _dyn_wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
                            )
                        for _tk in _picked_d:
                            if _tk in _dyn_wk.columns:
                                _s = _dyn_wk[_tk].dropna()
                                if len(_s) >= 2:
                                    _dyn_price_cache[_tk] = _s.to_frame(name="Close")

                    # 同一套规则渲染王朝接力图:任意 metric_df 做横截面排名 + 加冕门槛
                    # 加冕门槛: Top1 + RS_252d > 0(年化跑赢 SPY),熊市无王降级
                    # RS_63d 仅作 hover 参考信息显示,不进门槛——双 RS 实测过严,正常回调被误杀
                    # 通过 key_suffix 避免 streamlit 在同一页面 render 两次时 widget key 冲突
                    _adv_m_global = _d_adv_hist.resample("ME").last()
                    def _render_relay(metric_df, metric_label, hover_metric_label, key_suffix):
                        _metric_m = metric_df.resample("ME").last()
                        _rs_m = _d_rs.resample("ME").last()
                        _rs63_m = _d_rs63.resample("ME").last() if _d_rs63 is not None else None
                        if _metric_m.empty or len(_metric_m) < 2:
                            st.warning(f"⚠️ {_dynasty_window}:月末快照数据不足")
                            return

                        _rank_m = _metric_m.rank(axis=1, ascending=False, method="min")
                        _tier = pd.DataFrame(
                            0, index=_rank_m.index, columns=_rank_m.columns, dtype=int
                        )
                        _tier[_rank_m <= 3] = 1
                        _gold_mask = (_rank_m == 1) & (_rs_m > 0)
                        _tier = _tier.mask(_gold_mask, 2)
                        _demoted_mask = (_rank_m == 1) & (_rs_m <= 0)
                        _tier = _tier.mask(_demoted_mask, 0)

                        _gold_cnt = (_tier == 2).sum(axis=0)
                        _silver_cnt = (_tier == 1).sum(axis=0)
                        _sort_key = _gold_cnt * 10000 + _silver_cnt
                        _ordered_tk = _sort_key.sort_values(ascending=False).index.tolist()

                        _tier_yx   = _tier[_ordered_tk].T
                        _rank_yx   = _rank_m[_ordered_tk].T
                        _rs_yx     = _rs_m[_ordered_tk].T
                        _metric_yx = _metric_m[_ordered_tk].T
                        _rs63_yx   = _rs63_m[_ordered_tk].T if _rs63_m is not None else None
                        _adv_yx    = _adv_m_global.reindex(columns=_ordered_tk).T

                        _ylabels = []
                        for tk in _ordered_tk:
                            _name = _d_name_map.get(tk, tk)
                            _meta = _etf_info.get(tk, {})
                            _adv_str = _fmt_usd(_meta.get("adv_usd"))
                            _ylabels.append(f"{_name} ({tk}) · ADV {_adv_str}")
                        _xlabels = _tier_yx.columns.strftime("%Y-%m").tolist()

                        _BADGE = {0: "⚪ 灰", 1: "🥈 银", 2: "🥇 金"}
                        _hover_text = []
                        for tk in _ordered_tk:
                            _row_txt = []
                            for _d in _tier_yx.columns:
                                _t_val = int(_tier_yx.loc[tk, _d])
                                _r_val = _rank_yx.loc[tk, _d]
                                _rs_val = _rs_yx.loc[tk, _d]
                                _m_val = _metric_yx.loc[tk, _d]
                                _rs63_val = _rs63_yx.loc[tk, _d] if _rs63_yx is not None else None
                                _adv_hist_val = _adv_yx.loc[tk, _d] if _d in _adv_yx.columns else None
                                _rank_str = f"第 {int(_r_val)}" if pd.notna(_r_val) else "—"
                                _rs_str   = f"{_rs_val:+.2f}%" if pd.notna(_rs_val) else "—"
                                _m_str    = f"{_m_val:+.2f}" if pd.notna(_m_val) else "—"
                                _rs63_str = (
                                    f"{_rs63_val:+.2f}%" if (_rs63_val is not None and pd.notna(_rs63_val))
                                    else "—"
                                )
                                _adv_hist_str = (
                                    _fmt_usd(float(_adv_hist_val))
                                    if (_adv_hist_val is not None and pd.notna(_adv_hist_val))
                                    else "—"
                                )
                                # Top1 但降为灰 = RS_252d ≤ 0(熊市无王)
                                _demote_note = ""
                                if (
                                    _t_val == 0 and pd.notna(_r_val) and int(_r_val) == 1
                                    and pd.notna(_rs_val) and _rs_val <= 0
                                ):
                                    _demote_note = "<br><i>Top1 但 RS_252d ≤ 0 → 降级(熊市无王)</i>"
                                _meta = _etf_info.get(tk, {})
                                _aum_str = _fmt_usd(_meta.get("aum"))
                                _row_txt.append(
                                    f"<b>{_d_name_map.get(tk, tk)} ({tk})</b><br>"
                                    f"{_d.strftime('%Y-%m')}<br>"
                                    f"{_BADGE[_t_val]}<br>"
                                    f"排名 {_rank_str}<br>"
                                    f"{hover_metric_label} {_m_str}<br>"
                                    f"RS_252d {_rs_str}<br>"
                                    f"RS_63d {_rs63_str} <i>(仅参考,不进门槛)</i><br>"
                                    f"ADV_63d(当月) {_adv_hist_str}<br>"
                                    f"AUM(当前快照) {_aum_str}"
                                    f"{_demote_note}"
                                )
                            _hover_text.append(_row_txt)

                        fig_dyn = go.Figure(data=go.Heatmap(
                            z=_tier_yx.values,
                            x=_xlabels,
                            y=_ylabels,
                            colorscale=[
                                [0.00, "#2a2a2a"],
                                [0.33, "#2a2a2a"],
                                [0.34, "#9aa0a6"],
                                [0.66, "#9aa0a6"],
                                [0.67, "#FFD700"],
                                [1.00, "#FFD700"],
                            ],
                            zmin=0, zmax=2,
                            text=_hover_text,
                            hovertemplate="%{text}<extra></extra>",
                            showscale=False,
                            xgap=1, ygap=1,
                        ))
                        fig_dyn.update_layout(
                            height=max(400, 24 * len(_ordered_tk)),
                            margin=dict(l=20, r=20, t=40, b=20),
                            plot_bgcolor="#111111", paper_bgcolor="#111111",
                            font=dict(color="#ddd"),
                            xaxis=dict(showgrid=False, side="bottom", tickangle=-45),
                            yaxis=dict(showgrid=False, autorange="reversed"),
                            title=dict(
                                text=f"{_dynasty_window} 月末王朝接力 · 按 {metric_label} 排名 · {len(_ordered_tk)} 板块 · {len(_xlabels)} 月",
                                font=dict(size=14), x=0.01, xanchor="left",
                            ),
                        )
                        st.plotly_chart(fig_dyn, use_container_width=True, key=f"fig_dyn_{key_suffix}")

                        _stat_rows = []
                        for tk in _ordered_tk:
                            _t_row = _tier_yx.loc[tk].values
                            _gold = int((_t_row == 2).sum())
                            _silver = int((_t_row == 1).sum())
                            _max_streak = 0
                            _cur = 0
                            for v in _t_row:
                                if v == 2:
                                    _cur += 1
                                    _max_streak = max(_max_streak, _cur)
                                else:
                                    _cur = 0
                            _gold_dates = _tier_yx.loc[tk].index[_tier_yx.loc[tk].values == 2]
                            _last_gold = _gold_dates.max() if len(_gold_dates) > 0 else None
                            _stat_rows.append({
                                "板块": _d_name_map.get(tk, tk),
                                "代码": tk,
                                "累计戴金月数": _gold,
                                "累计戴银月数": _silver,
                                "最长连续戴金": _max_streak,
                                "最近戴金月份": _last_gold.strftime("%Y-%m") if _last_gold is not None else "—",
                            })
                        _stat_df = pd.DataFrame(_stat_rows)

                        _kings_top3 = _stat_df[_stat_df["累计戴金月数"] > 0].head(3)
                        _kings_html = " ".join([
                            f"<span class='tag-bull'>{r['板块']} 金{int(r['累计戴金月数'])}月/最长连续{int(r['最长连续戴金'])}月</span>"
                            for _, r in _kings_top3.iterrows()
                        ]) or "—"

                        _last_month = _tier_yx.columns[-1]
                        _last_col = _tier_yx[_last_month]
                        _current_king_tk = None
                        _gold_now = _last_col[_last_col == 2]
                        if len(_gold_now) > 0:
                            _current_king_tk = _gold_now.index[0]
                        _current_silver_tks = _last_col[_last_col == 1].index.tolist()
                        if _current_king_tk:
                            _current_html = (
                                f"<span class='tag-bull'>🥇 {_d_name_map.get(_current_king_tk, _current_king_tk)} "
                                f"({_current_king_tk})</span>"
                            )
                        else:
                            _current_html = "<span style='color:#888'>当前无王(无板块同时满足 Top1 + RS_252d &gt; 0)</span>"
                        _silver_html = " ".join([
                            f"<span class='tag-bear'>🥈 {_d_name_map.get(tk, tk)} ({tk})</span>"
                            for tk in _current_silver_tks
                        ]) or "—"

                        st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>👑 {metric_label} · 王朝接力摘要 ({_dynasty_window} · {len(_xlabels)} 个月)</div>
<div style='margin-bottom:6px'>📍 当前在位之王({_last_month.strftime('%Y-%m')}): {_current_html} &nbsp; {_silver_html}</div>
<div style='margin-bottom:6px'>👑 累计王朝长度 Top3: {_kings_html}</div>
<div class='insight-section' style='font-size:13px; color:#888;'>
读法:🥇 金块 = 当月 Top1 且 RS_252d &gt; 0(跑赢 SPY);🥈 银块 = Top2-3;⚪ 灰块 = 其他,或 Top1 但 RS_252d ≤ 0(熊市无王降级)。<b style='color:#aaa;'>连续金块</b> = 王朝期;<b style='color:#aaa;'>累计金多 + 最长连续金长</b> = 真时代之王。<b style='color:#aaa;'>对比 🅰️ 与 🅱️</b>:king_score 把 URA/TAN 这类小众主题盘从「时代之王」候选里压下去——它们 RS 可能称霸,但 ADV 显著低于 XL*/SMH/IGV 机构盘,容量项是负贡献。
</div>
</div>
""", unsafe_allow_html=True)

                        with st.expander(
                            f"📊 {_dynasty_window} · {metric_label} · 王朝统计明细表(所有板块)",
                            expanded=False,
                        ):
                            st.dataframe(
                                _stat_df.style.background_gradient(
                                    subset=["累计戴金月数", "累计戴银月数", "最长连续戴金"],
                                    cmap="YlOrBr",
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )

                        # ── 王朝接力净值:每月取 metric top-2(龙头+次龙头)持有,顺延 1 月
                        # 执行去 look-ahead;左右两列保持槽位连续(上月在左列且本月仍持有就
                        # 留左列),方便观察持仓。周线净值复用 holdings_viz(同 Page 6 持仓对比)。
                        st.markdown("---")
                        st.markdown(f"##### 📈 {metric_label} · 王朝接力净值(龙头 + 次龙头,左右两列)")
                        st.caption(
                            "每月末按排名取 **Top1(龙头) + Top2(次龙头)** 两个仓位,顺延 1 月执行"
                            "(去 look-ahead) · **守擂防抖**:已持有的标的只要还在 Top-N 缓冲区内就"
                            "继续持有,掉出缓冲区才换人——避免排名在 2/3 名边界抖动时来回换仓 · "
                            "左右两列只为对齐观察:上月在某列且本月仍持有的留原列,不来回跳 · "
                            "各列等权,合成线 = 左右 50/50 · 周线 NAV,价格 yfinance 股息+拆股复权,"
                            "与后端 king_score 同源 · 净值最长回看约 10 年,早期未上市的 ETF 月份缺价。"
                        )
                        _dyn_buf = int(st.number_input(
                            "守擂缓冲区 Top-N(≥2,越大越不换仓)",
                            min_value=2, max_value=10, value=4, step=1,
                            key=f"dyn_nav_buf_{key_suffix}",
                            help="持有的票掉到第 N 名以内都不换;掉出第 N 名才被替换为当前 Top2。"
                                 "= 2 即严格只拿前两名(最敏感,换手最高)。",
                        ))
                        if not _dyn_price_cache:
                            st.info("暂无可用价格数据,无法渲染王朝接力净值。")
                        else:
                            # 守擂防抖:已持有票在 Top-N 内则留任,否则换成当前 Top2。
                            # 逻辑同 holdings_viz.build_slot_assignments 的 survivor 选择。
                            _mh: dict = {}
                            _prev_h: list = []
                            for _ts, _row in _rank_m.iterrows():
                                _r = _row.dropna().sort_values()
                                if _r.empty:
                                    continue
                                _order = _r.index.tolist()
                                _t2 = _order[:2]
                                _tN = set(_order[:_dyn_buf])
                                if _prev_h:
                                    _surv = [t for t in _prev_h if t in _tN]
                                    if len(_surv) >= 2:
                                        _hold = _surv[:2]
                                    elif len(_surv) == 1:
                                        _fill = next(
                                            (t for t in _order if t not in _surv), None)
                                        _hold = _surv + ([_fill] if _fill else [])
                                        if len(_hold) < 2:
                                            _hold = _t2
                                    else:
                                        _hold = _t2
                                else:
                                    _hold = _t2
                                _mh[hv.next_month_key(_ts.strftime("%Y-%m"), 1)] = _hold
                                _prev_h = _hold
                            _exec_months = sorted(_mh)
                            if not _exec_months:
                                st.info("月度排名数据不足,无法渲染净值。")
                            else:
                                _slots = hv.build_basket_slot_assignments(_mh, _exec_months)
                                _seg_l = hv.build_slot_segments(_slots, 0, _exec_months)
                                _seg_r = hv.build_slot_segments(_slots, 1, _exec_months)
                                _nav_l = hv.calc_slot_stats(
                                    _seg_l, _dyn_price_cache, _dyn_spy_wk, 0.04)[2]
                                _nav_r = hv.calc_slot_stats(
                                    _seg_r, _dyn_price_cache, _dyn_spy_wk, 0.04)[2]

                                _navc = pd.Series(dtype=float)
                                if not _nav_l.empty and not _nav_r.empty:
                                    _uidx = _nav_l.index.union(_nav_r.index)
                                    _nl = _nav_l.reindex(_uidx).ffill().bfill()
                                    _nr = _nav_r.reindex(_uidx).ffill().bfill()
                                    _navc = 0.5 * _nl + 0.5 * _nr
                                elif not _nav_l.empty:
                                    _navc = _nav_l.copy()
                                elif not _nav_r.empty:
                                    _navc = _nav_r.copy()

                                if _navc.empty:
                                    st.info("价格窗口内无足够数据生成净值曲线。")
                                else:
                                    _ret_c = (
                                        float(_navc.iloc[-1]) / float(_navc.iloc[0]) - 1
                                    ) * 100
                                    _peak_c = _navc.cummax()
                                    _dd_c = float(
                                        ((_peak_c - _navc)
                                         / _peak_c.replace(0, float("nan"))).max()
                                    ) * 100
                                    _kpi = hv.compute_nav_kpi(_navc)

                                    def _fmt_k(v, f=".2f"):
                                        try:
                                            if isinstance(v, float) and (
                                                v != v or abs(v) == float("inf")):
                                                return "—"
                                            return f"{v:{f}}"
                                        except (TypeError, ValueError):
                                            return "—"

                                    _c1, _c2, _c3, _c4, _c5 = st.columns(5)
                                    _c1.metric("总收益", f"{_ret_c:+.1f}%")
                                    _c2.metric("最大回撤", f"-{_dd_c:.1f}%")
                                    _c3.metric("Calmar", _fmt_k(_kpi.get("calmar", float("nan"))))
                                    _c4.metric("Sortino", _fmt_k(_kpi.get("sortino", float("nan"))))
                                    _c5.metric("logR²", _fmt_k(_kpi.get("r2", float("nan"))))

                                    st.plotly_chart(
                                        hv.build_combined_fig(
                                            _nav_l, _nav_r, _navc, _dyn_spy_wk,
                                            "王朝接力 — 左列+右列 50/50 合成 vs SPY",
                                        ),
                                        use_container_width=True,
                                        key=f"dyn_nav_combined_{key_suffix}",
                                    )
                                    st.plotly_chart(
                                        hv.build_stitched_fig(
                                            _seg_l, "王朝接力 左列 (Slot 0)",
                                            _dyn_spy_wk, _dyn_price_cache, _d_name_map,
                                        ),
                                        use_container_width=True,
                                        key=f"dyn_nav_l_{key_suffix}",
                                    )
                                    st.plotly_chart(
                                        hv.build_stitched_fig(
                                            _seg_r, "王朝接力 右列 (Slot 1)",
                                            _dyn_spy_wk, _dyn_price_cache, _d_name_map,
                                        ),
                                        use_container_width=True,
                                        key=f"dyn_nav_r_{key_suffix}",
                                    )

                    st.markdown(
                        f"##### 🅰️ 按 king_score 排名(主图 · 动量+容量 · "
                        f"w_rs={_king_w['rs']:.1f} / w_cap={_king_w['cap']:.1f})"
                    )
                    _render_relay(_d_king, "king_score", "king_score", "king")


    with _dyn_tab2:
        st.caption(
            "**钻取**:对每个板块识别所有「连续金块期」,调后端 GICS 静态映射拿成分股,"
            "按 **超额 = 个股累计涨幅 − 板块 ETF 累计涨幅** 排出 Top 3 龙头。"
            "**偏差诚实说明**:用当前 S&P 500 + GICS,早期被剔除 / 当时未上市的股票会漏(标 ⚠️)。"
            "GICS Sector 变更(如 FB 从 Tech 划到 Communication Services)按当前归类。"
        )

        if not selected_groups:
            st.info("👈 请在侧边栏勾选至少一个组别以识别王朝期")
        elif not (_dyn_ts := _radar_ts_by_window.get(_dynasty_window, {})) or not _dyn_ts.get("success"):
            st.warning(f"⚠️ {_dynasty_window} 时序数据暂不可用")
        else:
            _dyn_tickers2 = _dyn_ts.get("tickers", {}) or {}
            _dyn_dates_raw2 = _dyn_ts.get("dates", []) or []
            _picked_d2 = {
                tk: p for tk, p in _dyn_tickers2.items()
                if p.get("group", "") in selected_groups
            }
            if not _picked_d2 or not _dyn_dates_raw2:
                st.info(f"⚠️ {_dynasty_window}:选中组别无可用 ticker")
            else:
                _dyn_idx2 = pd.to_datetime(_dyn_dates_raw2, errors="coerce")
                # 龙头股 tab 与主图 🅰️ 保持同一套加冕规则:都按 king_score 排名,
                # 否则两个 tab 识别的「连续金块期」会不一致
                _d_king2 = pd.DataFrame(
                    {tk: p.get("king_score", []) for tk, p in _picked_d2.items()},
                    index=_dyn_idx2,
                ).astype(float)
                _d_rs2 = pd.DataFrame(
                    {tk: p.get("rs", []) for tk, p in _picked_d2.items()},
                    index=_dyn_idx2,
                ).astype(float)
                _d_king_m2 = _d_king2.resample("ME").last()
                _d_rs_m2   = _d_rs2.resample("ME").last()

                if _d_king_m2.empty or len(_d_king_m2) < 2:
                    st.warning(f"⚠️ {_dynasty_window}:月末快照数据不足")
                else:
                    _rank_m2 = _d_king_m2.rank(axis=1, ascending=False, method="min")
                    _tier2 = pd.DataFrame(0, index=_rank_m2.index, columns=_rank_m2.columns, dtype=int)
                    _tier2[_rank_m2 <= 3] = 1
                    _gold_mask2 = (_rank_m2 == 1) & (_d_rs_m2 > 0)
                    _tier2 = _tier2.mask(_gold_mask2, 2)
                    _demoted_mask2 = (_rank_m2 == 1) & (_d_rs_m2 <= 0)
                    _tier2 = _tier2.mask(_demoted_mask2, 0)

                    _d_name_map2 = {tk: p.get("name", tk) for tk, p in _picked_d2.items()}
                    _gold_cnt2 = (_tier2 == 2).sum(axis=0)
                    _silver_cnt2 = (_tier2 == 1).sum(axis=0)
                    _sort_key2 = _gold_cnt2 * 10000 + _silver_cnt2
                    _ordered_tk2 = _sort_key2.sort_values(ascending=False).index.tolist()
                    _tier_yx2 = _tier2[_ordered_tk2].T

                    _dynasties = []
                    for tk in _ordered_tk2:
                        _row = _tier_yx2.loc[tk].values
                        _months = _tier_yx2.columns
                        _i = 0
                        while _i < len(_row):
                            if _row[_i] == 2:
                                _j = _i
                                while _j + 1 < len(_row) and _row[_j + 1] == 2:
                                    _j += 1
                                _dynasties.append({
                                    "ticker":      tk,
                                    "name":        _d_name_map2.get(tk, tk),
                                    "start_date":  _months[_i].strftime("%Y-%m-%d"),
                                    "end_date":    _months[_j].strftime("%Y-%m-%d"),
                                    "start_label": _months[_i].strftime("%Y-%m"),
                                    "end_label":   _months[_j].strftime("%Y-%m"),
                                    "n_months":    _j - _i + 1,
                                })
                                _i = _j + 1
                            else:
                                _i += 1

                    if not _dynasties:
                        st.info(f"{_dynasty_window} 内未识别到任何连续金块期 (无王朝期)")
                    else:
                        _dynasties.sort(
                            key=lambda d: (d["ticker"], -d["n_months"], d["start_date"])
                        )
                        st.markdown(
                            f"**{_dynasty_window} 共识别到 {len(_dynasties)} 段王朝期** "
                            f"(每段调一次后端 API,首次加载会慢 5-10 秒)"
                        )

                        _rows = []
                        with st.spinner(f"拉 {len(_dynasties)} 段王朝期的成分股龙头..."):
                            for d in _dynasties:
                                _res = fetch_dynasty_leaders(
                                    d["ticker"], d["start_date"], d["end_date"], 3
                                )
                                if not _res or not _res.get("success"):
                                    _leaders_cells = ["—", "—", "—"]
                                    _excess_cells  = ["—", "—", "—"]
                                    _etf_ret_str   = "—"
                                else:
                                    _etf_ret_str = f"{_res['etf_return_pct']:+.1f}%"
                                    _leaders = _res.get("leaders", [])
                                    _leaders_cells = []
                                    _excess_cells  = []
                                    for i in range(3):
                                        if i < len(_leaders):
                                            _l = _leaders[i]
                                            _flag = "" if _l.get("listed_full_period") else " ⚠️"
                                            _leaders_cells.append(
                                                f"{_l['ticker']}{_flag} ({_l['name'][:20]})"
                                            )
                                            _excess_cells.append(f"{_l['excess_pct']:+.1f}%")
                                        else:
                                            _leaders_cells.append("—")
                                            _excess_cells.append("—")
                                _rows.append({
                                    "板块": f"{d['name']} ({d['ticker']})",
                                    "王朝期": f"{d['start_label']} → {d['end_label']}",
                                    "持续(月)": d["n_months"],
                                    "板块ETF涨幅": _etf_ret_str,
                                    "🥇 Top1": _leaders_cells[0],
                                    "Top1 超额": _excess_cells[0],
                                    "🥈 Top2": _leaders_cells[1],
                                    "Top2 超额": _excess_cells[1],
                                    "🥉 Top3": _leaders_cells[2],
                                    "Top3 超额": _excess_cells[2],
                                })

                        _df_leaders = pd.DataFrame(_rows)
                        st.dataframe(
                            _df_leaders,
                            use_container_width=True,
                            hide_index=True,
                            height=min(800, 40 + 35 * len(_rows)),
                        )
                        st.caption(
                            "⚠️ 标记 = 该股在王朝期开始时未上市,按其实际上市后区间算超额(样本不完整,数字可能虚高)。"
                            "板块按累计戴金月数倒序、同板块按王朝期长度倒序排列。"
                        )


# ============================================================
# Section 2: 大盘趋势状态机 (Market Trend Matrix)
# ============================================================
st.markdown("---")
st.header("📊 大盘趋势状态机 (Market Trend Matrix)")
st.caption("基于 Close / MA60 / MA200 的四象限绝对强弱切割 · 背景色按月度剧本裁决（chaos 月份显示红色）")

if df_prices is None or df_prices.empty or len(df_prices) < 200:
    st.warning("⚠️ 价格数据不足（需至少 200 个交易日），无法计算 MA200")
else:
    _MTM_COLORS = {
        "主升狂飙": "#2ECC71",
        "颠簸震荡": "#F1C40F",
        "冰面滑行": "#E74C3C",
        "触底抢修": "#3498DB",
    }
    _MTM_EN = {
        "主升狂飙": "Full Throttle",
        "颠簸震荡": "Bumpy Road",
        "冰面滑行": "Slippery Ice",
        "触底抢修": "Bottom Rebound",
    }
    _MTM_DESC = {
        "主升狂飙": "Close > MA60 > MA200：均线完美多头排列，主力趋势全面向上，进攻优先，是持仓最舒适的环境。",
        "颠簸震荡": "Close < MA60，MA60 > MA200：价格跌破 60 日生命线，但长期趋势（MA200）仍上行，属牛市内部震荡回调，需等待重新站上 MA60 确认。",
        "冰面滑行": "Close < MA60 < MA200：均线空头排列，价格在双均线下方滑行，市场处于下跌通道，风险最高，严控仓位。",
        "触底抢修": "Close > MA60，MA60 < MA200：短期动能回归站上 MA60，但 200 日长期趋势仍朝下，属底部修复试探信号，需谨慎观察 MA200 能否被打穿。",
    }
    _MTM_INDEX_YLABEL = {"SPY": "SPY 收盘价 ($)", "QQQ": "QQQ 收盘价 ($)"}

    _REGIME_BG_C_MTM = {
        "软着陆": "rgba(46,204,113,0.15)",
        "再通胀": "rgba(22,160,133,0.15)",
        "滞胀":   "rgba(241,196,15,0.15)",
        "衰退":   "rgba(197,216,109,0.15)",
        "混沌期": "rgba(231,76,60,0.15)",
    }

    # universe.db 只持久化 horsemen_monthly_probs(10 年月度概率含 chaos_gbdt_trigger),
    # 在前端用月度数据 ffill 成日度作为背景染色。chaos 月份覆盖为"混沌期"。
    _hmp = (_current_regime or {}).get("horsemen_monthly_probs", {}) or {}
    _EN_TO_CN = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
    _monthly_recs = []
    for _m_str, _probs in _hmp.items():
        try:
            _m_ts = pd.Timestamp(str(_m_str) + "-01")
        except Exception:
            continue
        if not isinstance(_probs, dict):
            continue
        _cands = {k: float(_probs.get(k, 0.0) or 0.0) for k in _EN_TO_CN.keys()}
        _winner_en = max(_cands, key=lambda k: _cands[k])
        _winner_cn = _EN_TO_CN.get(_winner_en, "软着陆")
        _chaos = bool(_probs.get("chaos_gbdt_trigger", False))
        _monthly_recs.append((_m_ts, _winner_cn, _chaos))

    if _monthly_recs:
        _df_mhp = (
            pd.DataFrame(_monthly_recs, columns=["date", "verdict", "chaos"])
            .set_index("date").sort_index()
        )
        _daily_idx = pd.date_range(_df_mhp.index.min(), pd.Timestamp.now().normalize(), freq="D")
        _verdict_daily = _df_mhp["verdict"].reindex(_daily_idx, method="ffill")
        _chaos_daily = _df_mhp["chaos"].reindex(_daily_idx, method="ffill").fillna(False).astype(bool)
        _horsemen_daily_mtm = _verdict_daily.copy()
        _horsemen_daily_mtm_display = _verdict_daily.copy()
        _horsemen_daily_mtm_display.loc[_chaos_daily] = "混沌期"
    else:
        _horsemen_daily_mtm = pd.Series(dtype=str)
        _horsemen_daily_mtm_display = pd.Series(dtype=str)

    _chaos_trig_raw_mtm = (_chain_regime or {}).get("horsemen_daily_chaos_trigger", {}) or {}
    if _chaos_trig_raw_mtm:
        _chaos_trig_idx = pd.to_datetime(list(_chaos_trig_raw_mtm.keys()), errors="coerce")
        _chaos_trig_s = pd.Series(
            list(_chaos_trig_raw_mtm.values()), index=_chaos_trig_idx
        ).dropna().sort_index().astype(bool)
        _chaos_trig_dates = _chaos_trig_s[_chaos_trig_s].index
    else:
        _chaos_trig_dates = pd.DatetimeIndex([])

    def _classify_mtm(row):
        c, m60, m200 = row['close'], row['ma60'], row['ma200']
        if c > m60 and m60 > m200:   return "主升狂飙"
        elif c < m60 and m60 > m200: return "颠簸震荡"
        elif c < m60 and m60 < m200: return "冰面滑行"
        else:                        return "触底抢修"

    _mtm_tab_spy, _mtm_tab_qqq = st.tabs(["🇺🇸 SPY (标普500)", "📡 QQQ (纳斯达克100)"])

    def _render_mtm_tab(ticker, tab):
        with tab:
            if ticker not in df_prices.columns:
                st.warning(f"⚠️ {ticker} 数据暂不可用")
                return
            _full  = df_prices[ticker].dropna().astype(float)
            _ma60  = _full.rolling(60).mean()
            _ma200 = _full.rolling(200).mean()
            _df = pd.DataFrame({'close': _full, 'ma60': _ma60, 'ma200': _ma200}).dropna()
            _df['phase'] = _df.apply(_classify_mtm, axis=1)

            if _df.empty:
                st.warning(f"⚠️ {ticker} 数据不足（需至少 200 个交易日），无法计算 MA200")
                return

            _show_chaos = st.toggle(
                "叠加 GBDT 卖出信号",
                value=True,
                key=f"mtm_chaos_overlay_{ticker}",
                help="GBDT chaos 概率 P>0.50 持续 5 个交易日 → 触发清仓 BIL 闸门。算法详见 Page 1 §宏观时钟。",
            )

            _latest    = _df.iloc[-1]
            _phase     = _latest['phase']
            _price     = float(_latest['close'])
            _ma60_val  = float(_latest['ma60'])
            _ma200_val = float(_latest['ma200'])
            _color     = _MTM_COLORS.get(_phase, "#888")
            _date_str  = _df.index[-1].strftime('%Y-%m-%d')

            st.markdown(f"""
            <div style='background:#1a1a1a; border-left:5px solid {_color}; border-radius:8px; padding:14px 20px; margin-bottom:12px; display:flex; align-items:center; gap:32px;'>
                <div>
                    <div style='font-size:13px; color:#aaa; margin-bottom:4px;'>当前阶段（{_date_str}）</div>
                    <div style='font-size:28px; font-weight:bold; color:{_color}; margin-bottom:2px;'>{_phase}</div>
                    <div style='font-size:14px; color:#ccc;'>{_MTM_EN.get(_phase, "")}</div>
                </div>
                <div style='font-size:13px; color:#aaa; line-height:2.0; border-left:1px solid #333; padding-left:24px;'>
                    <b>Close &nbsp;</b> <span style='color:#ddd;'>${_price:.2f}</span><br>
                    <b>MA60 &nbsp;&nbsp;</b> <span style='color:#F1C40F;'>${_ma60_val:.2f}</span><br>
                    <b>MA200 &nbsp;</b> <span style='color:#3498DB;'>${_ma200_val:.2f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            _bg_shapes = []
            if not _horsemen_daily_mtm_display.empty:
                _regime_aligned = _horsemen_daily_mtm_display.reindex(_df.index).ffill().dropna()
                _prev_regime = None
                _seg_start   = None
                for _dt, _reg in _regime_aligned.items():
                    if _reg != _prev_regime:
                        if _prev_regime is not None and _seg_start is not None:
                            _bg_shapes.append(dict(
                                type="rect", x0=_seg_start, x1=_dt,
                                y0=0, y1=1, yref="paper",
                                fillcolor=_REGIME_BG_C_MTM.get(_prev_regime, "rgba(128,128,128,0.1)"),
                                line_width=0, layer="below"
                            ))
                        _prev_regime = _reg
                        _seg_start   = _dt
                if _prev_regime is not None and _seg_start is not None:
                    _bg_shapes.append(dict(
                        type="rect", x0=_seg_start, x1=_df.index[-1],
                        y0=0, y1=1, yref="paper",
                        fillcolor=_REGIME_BG_C_MTM.get(_prev_regime, "rgba(128,128,128,0.1)"),
                        line_width=0, layer="below"
                    ))

            # 变点检测「确认信号」紫色竖杠（图底 10%，避开 K 线主区）
            # mixed reference 必须显式 xref="x"，否则 plotly 把竖线当 paper 坐标解析失败。
            if len(_cp_confirm_dates) > 0:
                _cp_in_range = _cp_confirm_dates.intersection(_df.index)
                for _cp_dt in _cp_in_range:
                    _bg_shapes.append(dict(
                        type="line",
                        xref="x", yref="paper",
                        x0=_cp_dt, x1=_cp_dt,
                        y0=0, y1=0.10,
                        line=dict(color="rgba(142,68,173,0.95)", width=2.5),
                        layer="above",
                    ))

            _change_pts = [0]
            for _i in range(1, len(_df)):
                if _df['phase'].iloc[_i] != _df['phase'].iloc[_i - 1]:
                    _change_pts.append(_i)
            _change_pts.append(len(_df))

            _traces = []
            _seen   = set()
            for _j in range(len(_change_pts) - 1):
                _s  = _change_pts[_j]
                _e  = min(_change_pts[_j + 1] + 1, len(_df))
                _seg = _df.iloc[_s:_e]
                _ph  = _df['phase'].iloc[_s]
                _traces.append(go.Scatter(
                    x=_seg.index,
                    y=_seg['close'].astype(float).values,
                    mode='lines',
                    line=dict(color=_MTM_COLORS.get(_ph, '#888'), width=2),
                    name=_ph,
                    showlegend=(_ph not in _seen),
                    legendgroup=_ph,
                ))
                _seen.add(_ph)

            _fig = go.Figure()
            for _tr in _traces:
                _fig.add_trace(_tr)
            _fig.add_trace(go.Scatter(
                x=_df.index, y=_df['ma60'].astype(float),
                mode='lines', name='MA60',
                line=dict(color='rgba(241,196,15,0.5)', width=1, dash='dot'),
            ))
            _fig.add_trace(go.Scatter(
                x=_df.index, y=_df['ma200'].astype(float),
                mode='lines', name='MA200',
                line=dict(color='rgba(52,152,219,0.5)', width=1, dash='dash'),
            ))

            if _show_chaos and len(_chaos_trig_dates) > 0:
                _trig_in_range = _chaos_trig_dates.intersection(_df.index)
                if len(_trig_in_range) > 0:
                    _trig_close = _df.loc[_trig_in_range, 'close'].astype(float)
                    _fig.add_trace(go.Scatter(
                        x=_trig_in_range,
                        y=_trig_close.values,
                        mode='markers',
                        name='GBDT 卖出信号',
                        marker=dict(
                            symbol='triangle-down',
                            color='#C0392B',
                            size=12,
                            line=dict(color='#FFFFFF', width=1),
                        ),
                        hovertemplate=(
                            f"日期: %{{x|%Y-%m-%d}}<br>"
                            f"{ticker} 收盘: $%{{y:.2f}}<br>"
                            f"GBDT 触发<extra></extra>"
                        ),
                    ))

            _fig.update_layout(
                height=340,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor='#1a1a1a', paper_bgcolor='#1a1a1a',
                font=dict(color='#ddd'),
                showlegend=True,
                legend=dict(orientation="h", y=1.18, x=0.5, xanchor="center", font=dict(size=12)),
                hovermode="x unified",
                xaxis=dict(showgrid=False),
                yaxis=dict(title=_MTM_INDEX_YLABEL.get(ticker, f"{ticker} 收盘价 ($)"), showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
                title=dict(text=f"{ticker} 历史路况：技术形态 × 剧本背景双维叠加", font=dict(size=14), x=0.01, xanchor='left'),
                shapes=_bg_shapes if _bg_shapes else [],
            )
            st.plotly_chart(_fig, use_container_width=True)

            _desc = _MTM_DESC.get(_phase, "")
            st.markdown(f"""
            <div style='background:#1a1a1a; border-left:4px solid {_color}; border-radius:6px; padding:12px 16px; margin-top:4px;'>
                <div style='font-size:13px; color:#aaa; margin-bottom:5px;'>🧠 当前阶段白盒解读</div>
                <div style='font-size:14px; color:#ddd; line-height:1.75;'>{_desc}</div>
            </div>
            <div style='background:#111; border:1px solid #2a2a2a; border-radius:6px; padding:10px 18px; margin-top:6px;'>
                <div style='font-size:13px; color:#888; line-height:1.7;'>
                    📌 <b style='color:#bbb;'>图层说明：</b>
                    背景色带 = 四大剧本宏观裁决（基本面维度）；
                    折线颜色 = 技术形态状态机（价格维度）；
                    🟪 <b style='color:#8E44AD;'>图底紫色竖杠</b> = 变点检测「确认信号」（多变量 CUSUM 单日 n_t ≥ {_cp_K_global}，对应「调阵型」时刻，详见 §2.6）。
                    🎭 <b>剧本切换</b>看 §2.7「板块轮动剧本」——变点告诉你"什么时候变"，剧本告诉你"变成什么"。
                    背景与折线不一致时信号最有价值：🟢背景+🔴折线 = 基本面好但技术超跌，潜在抄底窗口；🔴背景+🟢折线 = 宏观恶化但技术仍强，需警惕。
                </div>
            </div>
            <div style='background:#111; border:1px solid #2a2a2a; border-radius:6px; padding:14px 18px; margin-top:8px;'>
                <div style='font-size:13px; color:#888; margin-bottom:10px; letter-spacing:0.3px;'>📐 折线四色判断标准（Close / MA60 / MA200）</div>
                <div style='display:grid; grid-template-columns:1fr 1fr; gap:8px;'>
                    <div style='background:#1a1a1a; border-left:3px solid #2ECC71; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#2ECC71; margin-bottom:3px;'>🟢 主升狂飙 · Full Throttle</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &gt; MA60 &gt; MA200<br>均线完美多头排列，趋势最强</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #F1C40F; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#F1C40F; margin-bottom:3px;'>🟡 颠簸震荡 · Bumpy Road</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &lt; MA60，MA60 &gt; MA200<br>牛市内部回调，长期趋势仍健康</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #3498DB; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#3498DB; margin-bottom:3px;'>🔵 触底抢修 · Bottom Rebound</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &gt; MA60，MA60 &lt; MA200<br>短期动能回归，长期趋势仍朝下</div>
                    </div>
                    <div style='background:#1a1a1a; border-left:3px solid #E74C3C; border-radius:4px; padding:8px 12px;'>
                        <div style='font-size:13px; font-weight:bold; color:#E74C3C; margin-bottom:3px;'>🔴 冰面滑行 · Slippery Ice</div>
                        <div style='font-size:13px; color:#aaa; line-height:1.6;'>Close &lt; MA60 &lt; MA200<br>均线空头排列，风险最高，严控仓位</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    _render_mtm_tab("SPY", _mtm_tab_spy)
    _render_mtm_tab("QQQ", _mtm_tab_qqq)

# ============================================================
# §2.5 共享变量预计算（SPY 状态机时序 + 因子风格切换三指标）
# 算法与 §4「指数主力归因」末尾旁白卡片完全一致；同算法同数据保证数值不漂移。
# ============================================================
_spy_phase_df = None
if df_prices is not None and not df_prices.empty and 'SPY' in df_prices.columns:
    _spy_full_25 = df_prices['SPY'].dropna().astype(float)
    if len(_spy_full_25) >= 200:
        _tmp_spy = pd.DataFrame({
            'close': _spy_full_25,
            'ma60':  _spy_full_25.rolling(60).mean(),
            'ma200': _spy_full_25.rolling(200).mean(),
        }).dropna()
        if not _tmp_spy.empty:
            def _phase_25(c, m60, m200):
                if   c > m60 and m60 > m200: return "主升狂飙"
                elif c < m60 and m60 > m200: return "颠簸震荡"
                elif c < m60 and m60 < m200: return "冰面滑行"
                else:                        return "触底抢修"
            _tmp_spy['phase'] = _tmp_spy.apply(
                lambda r: _phase_25(r['close'], r['ma60'], r['ma200']), axis=1
            )
            _spy_phase_df = _tmp_spy

_LEAD25_TICKERS = ["MAGS", "SPY", "RSP", "IJH", "IWM"]
_lead25_avail = [
    t for t in _LEAD25_TICKERS
    if df_prices is not None and t in df_prices.columns
]
_df_lead25 = (
    df_prices[_lead25_avail].dropna(how='all').ffill().dropna()
    if df_prices is not None and len(_lead25_avail) >= 3
    else pd.DataFrame()
)

_alert25       = "数据不足"
_slope_60d_d25 = 0.0
if (not _df_lead25.empty
    and "MAGS" in _df_lead25.columns and "IWM" in _df_lead25.columns
    and len(_df_lead25) >= 252):
    _diff25 = (_df_lead25["MAGS"] - _df_lead25["IWM"]).dropna()
    if len(_diff25) >= 252:
        _base252 = _diff25.iloc[-252]
        if abs(_base252) > 1e-9:
            _diff_norm25 = (_diff25 / _base252) * 100.0
            _arr_60d25 = _diff_norm25.iloc[-60:].values.astype(float)
            _slope_60d_d25 = float(np.polyfit(np.arange(60), _arr_60d25, 1)[0])
            _arr_5d25 = _diff_norm25.iloc[-5:].values.astype(float)
            _slope_5d_d25 = float(np.polyfit(np.arange(5), _arr_5d25, 1)[0])
            _down_days_25 = int(_diff_norm25.iloc[-21:].diff().lt(0).sum())
            if _slope_60d_d25 > 0:
                _alert25 = "未触发"
            elif _slope_60d_d25 < 0 and _slope_5d_d25 < 0 and _down_days_25 >= 15:
                _alert25 = "已切换"
            else:
                _alert25 = "早期信号"

# ============================================================
# Section 2.5: 风格传导链 (Style Transmission Chain)
# ============================================================
st.markdown("---")
st.header("📡 风格传导链 (Style Transmission Chain)")
st.caption("宏观 → 折现率 → Regime → 因子 → 行业 → 价格：每层切换时间戳一字排开，回答\"风格何时切换\"")

_chain_data = (_chain_regime or {}).get("data", {}) or {}

# --- 上游 3 层摘要卡 + 折叠详情（数据来自后端 upstream_summary）---
_upstream = (_chain_data.get("upstream_summary") or {})
_us_stars  = (_upstream.get("stars") or {})
_us_bonds  = (_upstream.get("bond_ladder") or {})
_us_liq    = (_upstream.get("liquidity") or {})

def _upstream_color(z, hi=0.5, mid=0.2):
    """统一染色：|z| 大且为正→绿，大且为负→红，其他→黄"""
    if z is None:
        return "#888"
    if z >= hi:    return "#2ECC71"
    if z <= -hi:   return "#E74C3C"
    if abs(z) < mid: return "#888"
    return "#F1C40F"

def _upstream_card_html(border_color, head_label, summary_html):
    return (
        f"<div style='background:#1a1a1a; border-left:4px solid {border_color}; "
        f"border-radius:6px; padding:10px 16px; margin:0 0 4px 0; "
        f"display:flex; align-items:center; gap:14px;'>"
        f"<div style='flex:0 0 130px; font-size:13px; color:#aaa; font-weight:bold;'>{head_label}</div>"
        f"<div style='flex:1; font-size:14px; color:#ddd; line-height:1.6;'>{summary_html}</div>"
        f"</div>"
    )

# ── 最上游：流动性（Net Liquidity = WALCL - TGA - RRP）──
if _us_liq:
    _liq_v   = float(_us_liq.get("value_t", 0.0))
    _liq_chg = float(_us_liq.get("change_6m_pct", 0.0))
    _liq_z   = float(_us_liq.get("z_3y", 0.0))
    _liq_asof = str(_us_liq.get("asof", "—"))
    _liq_color = _upstream_color(_liq_z)
    _liq_chg_color = "#2ECC71" if _liq_chg > 1.0 else ("#E74C3C" if _liq_chg < -1.0 else "#F1C40F")
    _liq_summary = (
        f"⏫ <b>最上游 · 流动性</b>"
        f"&nbsp;&nbsp;<b style='color:#ddd; font-size:15px;'>${_liq_v:.2f}T</b>"
        f"&nbsp;&nbsp;<span style='color:#888;'>6M:</span> "
        f"<b style='color:{_liq_chg_color};'>{_liq_chg:+.1f}%</b>"
        f"&nbsp;&nbsp;<span style='color:#888;'>3Y Z:</span> "
        f"<b style='color:{_liq_color};'>{_liq_z:+.2f}</b>"
    )
else:
    _liq_color = "#666"
    _liq_summary = (
        "⏫ <b>最上游 · 流动性</b>"
        "&nbsp;&nbsp;<span style='color:#888;'>FRED 暂不可用（FRED_API_KEY 未配置或拉取失败）</span>"
    )
st.markdown(_upstream_card_html(_liq_color, "Net Liquidity", _liq_summary), unsafe_allow_html=True)
with st.expander("📖 流动性详情（FRED WALCL / TGA / RRP）", expanded=False):
    if _us_liq:
        st.markdown(
            f"- **当前值**：`{_us_liq.get('value_t', 0.0):.3f} 万亿美元`（数据日期 `{_us_liq.get('asof', '—')}`）\n"
            f"- **6 个月变化率**：`{_us_liq.get('change_6m_pct', 0.0):+.2f}%` "
            f"（>+5% = 央行放水加速；<-5% = 缩表收紧）\n"
            f"- **3Y 标准 Z-Score**：`{_us_liq.get('z_3y', 0.0):+.2f}` "
            f"（>+1 = 历史性宽松；<-1 = 历史性紧缩）\n"
            f"- **公式**：`Net Liquidity = Fed_Assets (WALCL) - TGA (WTREGEN) - RRP (RRPONTSYD)`\n"
            f"- **跳转 Page 1 §5** 看完整 Treemap / Sankey / 鳄鱼嘴对决图。"
        )
    else:
        st.info("后端未返回流动性摘要。可能原因：FRED_API_KEY 未配置 / 临时拉取失败。前往 Page 1 §5 手动加载完整流动性大项。")

# ── 上游 1：宏观双星 G/I（rank_signed [-1, +1] 标度）──
_g  = float(_us_stars.get("g", 0.0)) if _us_stars else 0.0
_i  = float(_us_stars.get("i", 0.0)) if _us_stars else 0.0
_quad = str(_us_stars.get("quad", "—")) if _us_stars else "—"
_QUAD_COLOR = {"软着陆": "#2ECC71", "再通胀": "#16A085", "滞胀": "#F1C40F", "衰退": "#C5D86D"}
_quad_color = _QUAD_COLOR.get(_quad, "#888")
_g_color = _upstream_color(_g, hi=0.3, mid=0.1)
_i_color = _upstream_color(_i, hi=0.3, mid=0.1)
_stars_summary = (
    f"⏫ <b>上游 1 · 宏观双星 G/I</b>"
    f"&nbsp;&nbsp;<b style='color:{_quad_color}; font-size:15px;'>{_quad}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>Growth:</span> "
    f"<b style='color:{_g_color};'>{_g:+.2f}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>Inflation:</span> "
    f"<b style='color:{_i_color};'>{_i:+.2f}</b>"
)
st.markdown(_upstream_card_html(_quad_color, "Star A (G/I)", _stars_summary), unsafe_allow_html=True)
with st.expander("📖 双星详情（市场前瞻星 Star A 的 G/I 复合轴）", expanded=False):
    st.markdown(
        f"- **当前象限**：<b style='color:{_quad_color};'>{_quad}</b> "
        f"（G/I 都在 ±0.20 内 → 软着陆；G+I+ → 再通胀；G-I+ → 滞胀；G-I- → 衰退）\n"
        f"- **Growth 轴 G = `{_g:+.2f}`**（标度 [-1, +1] 的 3Y 滚动百分位）  \n"
        f"  合成自 `CPER/GLD`（铜金比）+ `XLI/XLU`（工业/公用）+ `HYG/IEF`（信用/国债），等权平均\n"
        f"- **Inflation 轴 I = `{_i:+.2f}`**（同标度）  \n"
        f"  合成自 `T10YIE`（10Y 隐含通胀，FRED）+ `DBC/IEF`（商品/债券），等权平均\n"
        f"- **跳转 Page 1 §1 宏观时钟** 看双星散点图、四色染色图、剧本验证图。",
        unsafe_allow_html=True,
    )

# ── 上游 2：债市阶梯（标准 Z-Score [-3, +3] 标度，与 Page 1 完全一致）──
_z_tlt_shy = float(_us_bonds.get("tlt_shy_z", 0.0)) if _us_bonds else 0.0
_z_hyg_ief = float(_us_bonds.get("hyg_ief_z", 0.0)) if _us_bonds else 0.0
_z_tip_ief = float(_us_bonds.get("tip_ief_z", 0.0)) if _us_bonds else 0.0
_z_uup_shy = float(_us_bonds.get("uup_shy_z", 0.0)) if _us_bonds else 0.0
_z_growth_color = _upstream_color(_z_tlt_shy)
_z_risk_color   = _upstream_color(_z_hyg_ief)
_z_infl_color   = _upstream_color(_z_tip_ief)
_z_usd_color    = _upstream_color(_z_uup_shy)
_bonds_border_color = _upstream_color((_z_tlt_shy + _z_hyg_ief + _z_tip_ief + _z_uup_shy) / 4.0)
_bonds_summary = (
    f"⏫ <b>上游 2 · 债市阶梯</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>📉 增长:</span> "
    f"<b style='color:{_z_growth_color};'>{_z_tlt_shy:+.2f}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>🦁 风险:</span> "
    f"<b style='color:{_z_risk_color};'>{_z_hyg_ief:+.2f}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>🎈 通胀:</span> "
    f"<b style='color:{_z_infl_color};'>{_z_tip_ief:+.2f}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>💪 美元:</span> "
    f"<b style='color:{_z_usd_color};'>{_z_uup_shy:+.2f}</b>"
)
st.markdown(_upstream_card_html(_bonds_border_color, "Bond Ladder (Z)", _bonds_summary), unsafe_allow_html=True)
with st.expander("📖 债市阶梯详情（4 个 ratio 3Y 滚动 Z-Score）", expanded=False):
    st.markdown(
        f"- **📉 增长预期 `TLT/SHY` Z = {_z_tlt_shy:+.2f}**  \n"
        f"  长债/短债：`>0` 长端历史性强 = 降息预期升温/增长放缓；`<0` 增长强劲\n"
        f"- **🦁 风险偏好 `HYG/IEF` Z = {_z_hyg_ief:+.2f}**  \n"
        f"  高收益债/国债：`>0` Risk-On；`<0` Risk-Off\n"
        f"- **🎈 通胀预期 `TIP/IEF` Z = {_z_tip_ief:+.2f}**  \n"
        f"  通胀保值/名义：`>0` 通胀升温；`<0` 通胀回落\n"
        f"- **💪 美元强弱 `UUP/SHY` Z = {_z_uup_shy:+.2f}**  \n"
        f"  美元/现金：`>0` 美元历史性走强 = 全球流动性收紧；`<0` 美元走弱\n"
        f"- **跳转 Page 1 §1 债市阶梯** 看 4 张完整 K-line + 滚动 Z 趋势图。"
    )

# ── 上游 2.5：信用利差闸门（同步「真信用伤害」标尺，level 由后端定）──
_us_credit  = (_upstream.get("credit") or {})
_credit_lvl = str(_us_credit.get("level", "平静"))
_credit_z   = float(_us_credit.get("z", 0.0))
_CREDIT_COLOR = {"平静": "#2ECC71", "走阔": "#F1C40F", "爆开": "#E74C3C"}
_CREDIT_DOT   = {"平静": "🟢", "走阔": "🟡", "爆开": "🔴"}
_credit_color = _CREDIT_COLOR.get(_credit_lvl, "#888")
_credit_dot   = _CREDIT_DOT.get(_credit_lvl, "⚪")
_credit_summary = (
    f"⏫ <b>上游 2.5 · 信用利差闸门</b>"
    f"&nbsp;&nbsp;<b style='color:{_credit_color}; font-size:15px;'>{_credit_dot} {_credit_lvl}</b>"
    f"&nbsp;&nbsp;<span style='color:#888;'>HY 利差 Z:</span> "
    f"<b style='color:{_credit_color};'>{_credit_z:+.2f}</b>"
)
st.markdown(_upstream_card_html(_credit_color, "Credit Gate", _credit_summary), unsafe_allow_html=True)
if _credit_lvl == "爆开":
    st.warning(
        "信用利差爆开（HY 利差 Z≥2）→ 真信用伤害，建议调阵型降敞口（非清仓）。"
        "时长看政策：美联储救=V 型别清仓，加息不救=阴跌减仓。"
    )
with st.expander("📖 信用利差闸门详情（同步指标，绝不触发清仓）", expanded=False):
    st.markdown(
        f"- **当前状态**：{_credit_dot} <b style='color:{_credit_color};'>{_credit_lvl}</b>"
        f"（HY 利差 Z = `{_credit_z:+.2f}`）\n"
        f"- **三档**：`Z<1.0` 平静（下跌大概率假摔，逢跌加）；`1.0≤Z<2.0` 走阔（警戒审视）；`Z≥2.0` 爆开（真信用伤害，降敞口）\n"
        f"- **信号源**：`HYG/IEF` 比值 250 日滚动 Z（高收益债 vs 国债，利差走阔=信用伤害）\n"
        f"- **核心定位**：同步指标，等它爆崩盘已发生。**绝不触发清仓**（清仓=卖底），只输出状态供调阵型 + 人工判断。",
        unsafe_allow_html=True,
    )

st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)
_chain_dv   = (_chain_regime or {}).get("horsemen_daily_verdict", {}) or {}
_chain_dc   = (_chain_regime or {}).get("horsemen_daily_confidence", {}) or {}
_chain_dp   = (_chain_regime or {}).get("horsemen_daily_chaos_prob", {}) or {}

# === Row 1: Regime 当前 + 切换日 ===
_REG_EN_CN = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
_REG_COLOR = {"Soft": "#2ECC71", "Hot": "#16A085", "Stag": "#F1C40F", "Rec": "#C5D86D"}
_curr_regime_en = str(_chain_data.get("current_macro_regime", "Soft"))
_curr_regime_cn = _REG_EN_CN.get(_curr_regime_en, _curr_regime_en)
_curr_regime_color = _REG_COLOR.get(_curr_regime_en, "#888")
_regime_probs = _chain_data.get("smoothed_regime_probs", {}) or {}

_regime_switch_date = None
_regime_prev_cn     = "—"
_regime_days_since  = "—"
if _chain_dv:
    _dv_idx = pd.to_datetime(list(_chain_dv.keys()), errors="coerce")
    _dv_s = pd.Series(list(_chain_dv.values()), index=_dv_idx).dropna().sort_index()
    if len(_dv_s) >= 2:
        _changes_dv = _dv_s.ne(_dv_s.shift(1))
        _change_dates_dv = _dv_s.index[_changes_dv]
        if len(_change_dates_dv) >= 2:
            _last_dv  = pd.Timestamp(_change_dates_dv[-1])
            _regime_switch_date = _last_dv.strftime("%Y-%m-%d")
            _regime_days_since  = int((pd.Timestamp.today().normalize() - _last_dv.normalize()).days)
            _regime_prev_cn     = str(_dv_s.loc[_change_dates_dv[-2]])

_chaos_prob_curr = 0.0
if _chain_dp:
    _cp_idx = pd.to_datetime(list(_chain_dp.keys()), errors="coerce")
    _cp_s = pd.Series([float(v) for v in _chain_dp.values()], index=_cp_idx).dropna().sort_index()
    if not _cp_s.empty:
        _chaos_prob_curr = float(_cp_s.iloc[-1])

_conf_curr = "—"
if _chain_dc:
    _cc_idx = pd.to_datetime(list(_chain_dc.keys()), errors="coerce")
    _cc_s = pd.Series(list(_chain_dc.values()), index=_cc_idx).dropna().sort_index()
    if not _cc_s.empty:
        _conf_curr = str(_cc_s.iloc[-1])
_CONF_COLOR = {"high": "#2ECC71", "medium": "#F1C40F", "chaos": "#E74C3C"}
_conf_color = _CONF_COLOR.get(_conf_curr, "#888")

# === Row 4: 行业领涨/领跌（复用顶部已 fetch 的 _radar）===
_top3_names = []
_bot3_names = []
if _radar.get("success") and _radar.get("metrics"):
    _df_m_chain = pd.DataFrame(_radar["metrics"])
    _all_groups = _df_m_chain["组别"].unique().tolist() if not _df_m_chain.empty else []
    _c_group = next((g for g in _all_groups if g.startswith("C:")), None)
    if _c_group is not None:
        _df_c_chain = _df_m_chain[_df_m_chain["组别"] == _c_group].sort_values("相对强度", ascending=False)
        _top3_names = _df_c_chain.head(3)["名称"].tolist()
        _bot3_names = _df_c_chain.tail(3)["名称"].tolist()

# === Row 5: SPY 价格状态机 + 切换日 ===
_spy_phase_curr  = "—"
_spy_switch_date = None
_spy_days_since  = "—"
if _spy_phase_df is not None and not _spy_phase_df.empty:
    _spy_phase_curr = str(_spy_phase_df['phase'].iloc[-1])
    _changes_spy = _spy_phase_df['phase'].ne(_spy_phase_df['phase'].shift(1))
    _change_dates_spy = _spy_phase_df.index[_changes_spy]
    if len(_change_dates_spy) >= 2:
        _last_spy = pd.Timestamp(_change_dates_spy[-1])
        _spy_switch_date = _last_spy.strftime("%Y-%m-%d")
        _spy_days_since  = int((pd.Timestamp.today().normalize() - _last_spy.normalize()).days)
_SPY_PHASE_COLOR = {
    "主升狂飙": "#2ECC71", "颠簸震荡": "#F1C40F",
    "冰面滑行": "#E74C3C", "触底抢修": "#3498DB",
}
_spy_phase_color = _SPY_PHASE_COLOR.get(_spy_phase_curr, "#888")

# === 传导一致性徽章规则 ===
# Row 1 (Regime)：Soft/Hot = 进攻；Stag/Rec = 防御
# Row 3 (因子)：未触发 = 进攻；早期信号 = 中性；已切换 = 防御
# Row 5 (价格)：主升狂飙/触底抢修 = 进攻；颠簸震荡/冰面滑行 = 防御
def _layer_dir(layer, val):
    if layer == "regime":
        return "att" if val in ("Soft", "Hot") else "def"
    if layer == "factor":
        if val == "未触发":   return "att"
        if val == "已切换":   return "def"
        if val == "早期信号": return "neu"
        return "neu"
    if layer == "price":
        return "att" if val in ("主升狂飙", "触底抢修") else "def"
    return "neu"

_dir_r1 = _layer_dir("regime", _curr_regime_en)
_dir_r3 = _layer_dir("factor", _alert25)
_dir_r5 = _layer_dir("price",  _spy_phase_curr)

def _pair_badge(this_dir, upstream_dir):
    if this_dir == "neu" or upstream_dir == "neu":
        return ("中性", "#888")
    if this_dir == upstream_dir:
        return ("共振", "#2ECC71")
    if upstream_dir == "att" and this_dir == "def":
        return ("提前防御", "#F1C40F")
    return ("滞后", "#E74C3C")

_b3_text, _b3_color = _pair_badge(_dir_r3, _dir_r1)
_b5_text, _b5_color = _pair_badge(_dir_r5, _dir_r3)

# === 渲染 5 行卡片 ===
def _chain_row_html(head_color, head_label, body_html, badge_text=None, badge_color=None):
    badge_block = (
        f"<div style='flex:0 0 110px; text-align:right; font-size:13px; "
        f"color:{badge_color or '#888'}; font-weight:bold;'>{badge_text}</div>"
        if badge_text else ""
    )
    return (
        f"<div style='background:#1a1a1a; border-left:4px solid {head_color}; "
        f"border-radius:6px; padding:12px 18px; margin-bottom:8px; "
        f"display:flex; align-items:center; gap:18px;'>"
        f"<div style='flex:0 0 130px; font-size:13px; color:#aaa; font-weight:bold;'>{head_label}</div>"
        f"<div style='flex:1; font-size:14px; color:#ddd; line-height:1.7;'>{body_html}</div>"
        f"{badge_block}"
        f"</div>"
    )

# Row 1: Regime
_prob_str = ""
if _regime_probs:
    _prob_pairs = sorted(_regime_probs.items(), key=lambda kv: kv[1], reverse=True)
    _prob_str = " | ".join(
        f"{_REG_EN_CN.get(k, k)} {int(round(float(v) * 100))}%"
        for k, v in _prob_pairs
    )
_row1_body = (
    f"<b style='color:{_curr_regime_color}; font-size:15px;'>{_curr_regime_cn}</b>"
    f"&nbsp;<span style='color:{_conf_color}; font-size:13px;'>({_conf_curr} 置信)</span>"
)
if _prob_str:
    _row1_body += f"<br><span style='color:#888; font-size:13px;'>{_prob_str}</span>"
if _regime_switch_date:
    _row1_body += (
        f"<br><span style='color:#aaa; font-size:13px;'>"
        f"上次切换 {_regime_switch_date} · 已 {_regime_days_since} 天 · 前剧本 {_regime_prev_cn}"
        f"</span>"
    )
st.markdown(_chain_row_html(_curr_regime_color, "① Regime", _row1_body), unsafe_allow_html=True)

# Row 2: 风险信号 (Chaos prob 进度条)
_chaos_color = (
    "#E74C3C" if _chaos_prob_curr >= 0.50
    else ("#F1C40F" if _chaos_prob_curr >= 0.30 else "#2ECC71")
)
_row2_body = (
    f"<b style='color:{_chaos_color}; font-size:15px;'>Chaos prob {_chaos_prob_curr:.2f}</b>"
    f"&nbsp;<span style='color:#888; font-size:13px;'>(阈值 0.50)</span>"
    f"<div style='background:#0a0a0a; height:8px; border-radius:4px; "
    f"margin-top:6px; position:relative;'>"
    f"<div style='background:{_chaos_color}; width:{min(_chaos_prob_curr * 100.0, 100.0):.1f}%; "
    f"height:100%; border-radius:4px;'></div>"
    f"<div style='position:absolute; left:50%; top:-3px; height:14px; width:1px; background:#aaa;'></div>"
    f"</div>"
)
st.markdown(_chain_row_html(_chaos_color, "② 风险信号", _row2_body), unsafe_allow_html=True)

# Row 3: 因子风格切换警报
_ALERT_COLOR = {"未触发": "#2ECC71", "早期信号": "#F1C40F", "已切换": "#E74C3C"}
_alert_color = _ALERT_COLOR.get(_alert25, "#888")
_row3_body = (
    f"<b style='color:{_alert_color}; font-size:15px;'>{_alert25}</b>"
    f"&nbsp;<span style='color:#888; font-size:13px;'>"
    f"MAGS-IWM 60D 斜率 {_slope_60d_d25:+.4f}</span>"
)
st.markdown(_chain_row_html(_alert_color, "③ 因子切换", _row3_body, _b3_text, _b3_color), unsafe_allow_html=True)

# Row 4: 行业领涨/领跌
_top_html = " · ".join(_top3_names) if _top3_names else "—"
_bot_html = " · ".join(_bot3_names) if _bot3_names else "—"
_row4_body = (
    f"<span style='color:#2ECC71; font-weight:bold;'>领涨</span> {_top_html}"
    f"<br><span style='color:#E74C3C; font-weight:bold;'>领跌</span> {_bot_html}"
)
st.markdown(_chain_row_html("#888888", "④ 行业表象", _row4_body), unsafe_allow_html=True)

# Row 5: SPY 价格状态机
_row5_body = f"<b style='color:{_spy_phase_color}; font-size:15px;'>{_spy_phase_curr}</b>"
if _spy_switch_date:
    _row5_body += (
        f"<br><span style='color:#aaa; font-size:13px;'>"
        f"上次切换 {_spy_switch_date} · 已 {_spy_days_since} 天</span>"
    )
st.markdown(_chain_row_html(_spy_phase_color, "⑤ 价格 (SPY)", _row5_body, _b5_text, _b5_color), unsafe_allow_html=True)

st.caption(
    "色标含义 · 共振:本层与上层同向(传导已完成) · 提前防御:上层进攻本层防守(早期信号最有价值) · "
    "滞后:本层先动上层未跟(罕见) · 中性:其中一层处于过渡态"
)

# ============================================================
# Section 2.6: 变点检测 (Change-Point Detection)
# 多变量 CUSUM 算法，输出 4 级信号。与 §② chaos 闸门并联不替代。
# 笔记: obsidian_notes/99_Human_Zone/变点检测.md
# ============================================================
st.markdown("---")
st.header("📡 变点检测 (Change-Point Detection)")
st.caption("多变量 CUSUM · 当前是不是发生 regime shift？与 chaos 闸门并联不替代（chaos 答\"未来会不会大跌\"→ 清仓；本节答\"是否换挡\"→ 调阵型）")

if not _cp.get("success"):
    st.warning(f"⚠️ 变点检测数据暂不可用：{_cp.get('error', '未知错误')}")
else:
    _cp_level = _cp.get("level", "无信号")
    _cp_n_trig = int(_cp.get("n_triggered", 0))
    _cp_n_weak = int(_cp.get("n_weak", 0))
    _cp_n_vars = int(_cp.get("n_vars", 0))
    _cp_dur = int(_cp.get("duration_days", 0))
    _cp_asof = str(_cp.get("asof", "—"))
    _cp_consts = _cp.get("constants", {}) or {}
    _cp_K = int(_cp_consts.get("K", 4))
    _cp_confirm = int(_cp_consts.get("confirm_days", 5))
    _cp_weak_z = float(_cp_consts.get("weak_z_threshold", 3.0))
    _cp_h = float(_cp_consts.get("h", 5.0))
    _cp_k = float(_cp_consts.get("k", 0.5))
    _cp_window = int(_cp_consts.get("z_window", 750))
    _cp_cooldown = int(_cp_consts.get("cooldown_days", 60))

    _LEVEL_COLOR = {
        "确认信号": "#E74C3C",
        "强信号":   "#F39C12",
        "弱信号":   "#F1C40F",
        "无信号":   "#2ECC71",
    }
    _LEVEL_ICON = {
        "确认信号": "🚨",
        "强信号":   "🟠",
        "弱信号":   "🟡",
        "无信号":   "🟢",
    }
    _level_color = _LEVEL_COLOR.get(_cp_level, "#888")
    _level_icon = _LEVEL_ICON.get(_cp_level, "⚪")

    _progress_pct = min(_cp_dur / max(_cp_confirm, 1), 1.0) * 100.0
    _banner_action = {
        "确认信号": "建议立即重新审视各档资产权重（A 压舱石 / B 大猩猩 / C 时代之王 / D 预备队）",
        "强信号":   f"持续 {_cp_dur}/{_cp_confirm} 天 → 达 {_cp_confirm} 天将升级为确认信号",
        "弱信号":   "留意但不动作（可能单一指标异常）",
        "无信号":   "宏观状态稳定，无明显 regime shift 迹象",
    }.get(_cp_level, "")

    st.markdown(f"""
<div style='background:#1a1a1a; border-left:5px solid {_level_color}; border-radius:8px; padding:14px 20px; margin-bottom:12px;'>
    <div style='display:flex; align-items:center; gap:24px; flex-wrap:wrap;'>
        <div style='min-width:160px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:4px;'>当前级别（{_cp_asof}）</div>
            <div style='font-size:24px; font-weight:bold; color:{_level_color};'>{_level_icon} {_cp_level}</div>
        </div>
        <div style='font-size:13px; color:#aaa; line-height:2.0; border-left:1px solid #333; padding-left:24px;'>
            <b>触发变量</b> <span style='color:#ddd;'>{_cp_n_trig} / {_cp_n_vars}</span>（阈值 ≥ {_cp_K}）<br>
            <b>|z|&gt;{_cp_weak_z:.0f} 变量</b> <span style='color:#ddd;'>{_cp_n_weak} / {_cp_n_vars}</span><br>
            <b>强信号持续</b> <span style='color:#ddd;'>{_cp_dur}</span> 天（确认需 ≥ {_cp_confirm}）
        </div>
        <div style='flex:1; min-width:220px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:6px;'>距离确认信号进度</div>
            <div style='background:#0a0a0a; height:10px; border-radius:5px; position:relative;'>
                <div style='background:{_level_color}; width:{_progress_pct:.1f}%; height:100%; border-radius:5px;'></div>
            </div>
            <div style='font-size:12px; color:#888; margin-top:6px;'>{_banner_action}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

    _vars = _cp.get("variables", []) or []
    if _vars:
        st.markdown("**📋 变量触发明细（按 |z| 降序）**")
        _df_v = pd.DataFrame(_vars).rename(columns={
            "name":         "变量",
            "z_curr":       "当前 Z",
            "s_pos_curr":   "CUSUM+",
            "s_neg_curr":   "CUSUM-",
            "triggered":    "今日触发",
            "trigger_days": "近30日触发次数",
        })
        _df_v["今日触发"] = _df_v["今日触发"].map({True: "🟢 触发", False: "—"})

        def _color_z_cp(v):
            try:
                f = float(v)
                if abs(f) > 3:    return "color: #E74C3C; font-weight: bold"
                if abs(f) > 1.5:  return "color: #F1C40F"
                return "color: #aaa"
            except Exception:
                return "color: #aaa"

        def _color_cusum_cp(v):
            try:
                f = float(v)
                if abs(f) > _cp_h:        return "color: #E74C3C; font-weight: bold"
                if abs(f) > _cp_h * 0.6:  return "color: #F1C40F"
                return "color: #aaa"
            except Exception:
                return "color: #aaa"

        st.dataframe(
            _df_v.style.format({
                "当前 Z":         "{:+.2f}",
                "CUSUM+":         "{:+.2f}",
                "CUSUM-":         "{:+.2f}",
                "近30日触发次数": "{:d}",
            }).map(_color_z_cp,     subset=["当前 Z"])
              .map(_color_cusum_cp, subset=["CUSUM+", "CUSUM-"]),
            use_container_width=True, hide_index=True,
        )

    _tl = _cp.get("timeline", []) or []
    if _tl:
        _df_tl = pd.DataFrame(_tl)
        _df_tl["date"] = pd.to_datetime(_df_tl["date"])
        fig_cp = go.Figure()
        fig_cp.add_trace(go.Scatter(
            x=_df_tl["date"], y=_df_tl["n_triggered"],
            mode="lines",
            line=dict(color="#8E44AD", width=2),
            fill="tozeroy",
            name="触发变量数 n_t",
            hovertemplate="日期: %{x|%Y-%m-%d}<br>触发变量数: %{y}<extra></extra>",
        ))
        fig_cp.add_hline(
            y=_cp_K, line_dash="dash", line_color="#E74C3C",
            annotation_text=f"强信号阈值 K={_cp_K}", annotation_position="right",
        )
        if len(_df_tl) > 0:
            fig_cp.add_trace(go.Scatter(
                x=[_df_tl["date"].iloc[-1]],
                y=[_df_tl["n_triggered"].iloc[-1]],
                mode="markers",
                marker=dict(color=_level_color, size=12, symbol="circle",
                           line=dict(color="#FFFFFF", width=1)),
                name="当前",
                showlegend=False,
                hovertemplate=f"当前: {_cp_level}<br>触发: %{{y}} 个变量<extra></extra>",
            ))
        fig_cp.update_layout(
            height=320,
            margin=dict(l=20, r=20, t=40, b=20),
            plot_bgcolor="#111111", paper_bgcolor="#111111",
            font=dict(color="#ddd"),
            hovermode="x unified",
            xaxis=dict(showgrid=False),
            yaxis=dict(title=f"触发变量数 (共 {_cp_n_vars} 个)", showgrid=True,
                       gridcolor="rgba(255,255,255,0.06)"),
            title=dict(text="2017 年至今 触发变量数 (n_t)", font=dict(size=14),
                       x=0.01, xanchor="left"),
            legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
        )
        st.plotly_chart(fig_cp, use_container_width=True)

    with st.expander("📖 算法白盒 & 何时该看 & 与 chaos 闸门的区别", expanded=False):
        st.markdown(f"""
**变点检测 vs chaos 闸门**

| | 答的是 | 触发后做什么 |
|---|---|---|
| **chaos 闸门**（§②） | 未来 N 天会不会大跌 | **清仓**（直接行动） |
| **变点检测**（本节） | 当前是不是发生 regime shift | **调阵型**（不是清仓） |

「调阵型」具体指：重新评估各档资产权重 + 触发因子重新审视。两者**并联使用**：chaos = 快应急刹车；变点 = 换挡提示。

---

**三级信号**

| 级别 | 触发条件 | 处理 |
|---|---|---|
| 🟡 **弱信号** | 单一变量 \\|z\\| > {_cp_weak_z:.0f} 或 1 ≤ n < {_cp_K} | 留意但不动作 |
| 🟠 **强信号** | n ≥ {_cp_K}（{_cp_K}/{_cp_n_vars} 变量同时触发） | 进入审视模式 |
| 🚨 **确认信号** | n ≥ {_cp_K} 当日即触发（confirm_days={_cp_confirm}） | 触发调阵型 |

注：早期版本要求强信号持续 5 个交易日确认，但 9 年历史从未触发；现放宽为单日 n ≥ K 即确认，同时加 **cooldown={_cp_cooldown} 个交易日**（约 3 个月）的事件去重——一次确认信号后该窗口内即便 n_t 仍≥K 也只标「强信号」，确保每个紫色竖杠对应一个独立宏观事件（防 2020-03 持续触发一个事件吃掉 30 天视觉权重）。9 年历史命中约 17 次，覆盖 2018-02 闪崩 / 2020-03 疫情 / 2022-04 加息开局 / 2023-03 SVB / 2024-02 AI 行情 / 2025-04 关税 等关键换挡点。

---

**CUSUM 算法常量**

- `k = {_cp_k}`（允许偏差，小 = 灵敏）
- `h = {_cp_h}`（触发阈值，大 = 稳健）
- `z_window = {_cp_window}`（≈3 年滚动 Z-Score）
- 月频/周频变量加 **dedup mask**：原始值未变化的天不累加（防 ffill 后 CUSUM 爆炸误触发）
- 触发后**不 reset** CUSUM：让累积量持续在阈值上方表示压力持续

---

**14 监控变量分布**

- 利率类 (3)：DGS10 / DGS2 / 10Y-2Y 利差
- 风险类 (4)：VIX / HY_Spread / TLT-SHY / HYG-IEF
- 货币类 (1)：UUP-SHY
- 商品类 (1)：CPER-GLD（铜金比）
- 通胀类 (2)：Core_CPI_YoY / T10YIE
- 就业类 (2)：PAYEMS_YoY / ICSA
- 产出类 (1)：INDPRO_YoY

---

**输出位置**

变点检测的输出是「让人重新审视」，**不是「自动调仓」**——不接入下单链。
""")

# ============================================================
# Section 2.7: 板块轮动剧本 (Sector Rotation Scenario)
# 11 板块 RS 多窗口加权匹配 4 剧本模板，与 horsemen 基本面体系并联
# 算法 Sam Stovall Sector Rotation Model 工程化版，后端 macro_engine 计算
# ============================================================
st.markdown("---")
st.header("🎭 板块轮动剧本 (Sector Rotation Scenario)")
st.caption("11 板块谁在领涨能分剧本 · 与 horsemen 基本面投票并联 · 资金流领先于基本面 2-3 个月")

if not _sr.get("success"):
    st.warning(f"⚠️ 板块轮动数据暂不可用：{_sr.get('error', '未知错误')}")
else:
    _sr_probs     = _sr.get("probs", {}) or {}
    _sr_winner    = str(_sr.get("winner", "—"))
    _sr_ranks     = _sr.get("ranks", {}) or {}
    _sr_rs_curr   = _sr.get("rs_curr", {}) or {}
    _sr_templates = _sr.get("templates", {}) or {}
    _sr_timeline  = _sr.get("timeline", []) or []
    _sr_asof      = str(_sr.get("asof", "—"))

    _SR_CN = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
    _SR_COLOR = {"Soft": "#2ECC71", "Hot": "#16A085", "Stag": "#F1C40F", "Rec": "#C5D86D"}

    _sr_winner_cn    = _SR_CN.get(_sr_winner, _sr_winner)
    _sr_winner_color = _SR_COLOR.get(_sr_winner, "#888")
    _sr_winner_prob  = float(_sr_probs.get(_sr_winner, 0.0))

    # ── 当前剧本 banner + 4 概率条 ──
    _sorted_probs = sorted(_sr_probs.items(), key=lambda kv: kv[1], reverse=True)
    _prob_bars_html = ""
    for k, v in _sorted_probs:
        cn = _SR_CN.get(k, k)
        col = _SR_COLOR.get(k, "#888")
        pct = float(v) * 100.0
        _prob_bars_html += (
            f"<div style='margin-bottom:6px;'>"
            f"<div style='display:flex; justify-content:space-between; font-size:13px; margin-bottom:2px;'>"
            f"<span style='color:#ddd;'>{cn}</span>"
            f"<span style='color:{col}; font-weight:bold;'>{pct:.1f}%</span>"
            f"</div>"
            f"<div style='background:#0a0a0a; height:8px; border-radius:4px;'>"
            f"<div style='background:{col}; width:{pct:.1f}%; height:100%; border-radius:4px;'></div>"
            f"</div></div>"
        )

    st.markdown(f"""
<div style='background:#1a1a1a; border-left:5px solid {_sr_winner_color}; border-radius:8px; padding:14px 20px; margin-bottom:12px;'>
    <div style='display:flex; align-items:center; gap:32px; flex-wrap:wrap;'>
        <div style='min-width:180px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:4px;'>当前剧本（{_sr_asof}）</div>
            <div style='font-size:28px; font-weight:bold; color:{_sr_winner_color};'>{_sr_winner_cn}</div>
            <div style='font-size:14px; color:#ccc; margin-top:2px;'>{_sr_winner_prob*100:.1f}% 资金流投票</div>
        </div>
        <div style='flex:1; min-width:260px;'>
            {_prob_bars_html}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

    # ── 与 horsemen 对照 ──
    _hm_winner_en = str((_chain_regime or {}).get("data", {}).get("current_macro_regime", "Soft"))
    _hm_winner_cn = _SR_CN.get(_hm_winner_en, _hm_winner_en)
    _hm_winner_color = _SR_COLOR.get(_hm_winner_en, "#888")

    if _hm_winner_en == _sr_winner:
        _diag_text = "共振 — 基本面与资金流都指向同一剧本"
        _diag_color = "#2ECC71"
        _diag_logic = "两套独立体系给出一致信号，剧本判断高置信"
    else:
        _diag_text = "分歧 — 基本面与资金流给出不同剧本"
        _diag_color = "#F1C40F"
        _diag_logic = (
            f"horsemen（月频基本面）判 <b style='color:{_hm_winner_color};'>{_hm_winner_cn}</b>，"
            f"sector_rotation（日频资金流）判 <b style='color:{_sr_winner_color};'>{_sr_winner_cn}</b>。"
            "资金流通常领先基本面 2-3 个月——分歧出现时观察基本面是否跟上。"
        )

    st.markdown(f"""
<div style='background:#111; border:1px solid #2a2a2a; border-radius:6px; padding:12px 18px; margin-bottom:12px;'>
    <div style='display:flex; align-items:center; gap:18px; flex-wrap:wrap;'>
        <div style='flex:1; min-width:240px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:6px;'>① horsemen 基本面投票</div>
            <div style='font-size:18px; font-weight:bold; color:{_hm_winner_color};'>{_hm_winner_cn}</div>
            <div style='font-size:12px; color:#888;'>数据源：14 个 FRED + ETF 比率，月频 GBDT</div>
        </div>
        <div style='flex:1; min-width:240px;'>
            <div style='font-size:13px; color:#aaa; margin-bottom:6px;'>② sector_rotation 资金流投票</div>
            <div style='font-size:18px; font-weight:bold; color:{_sr_winner_color};'>{_sr_winner_cn} ({_sr_winner_prob*100:.1f}%)</div>
            <div style='font-size:12px; color:#888;'>数据源：11 板块 RS 排名匹配模板，日频 EMA 平滑</div>
        </div>
        <div style='flex:0 0 100%; border-top:1px solid #2a2a2a; padding-top:10px; margin-top:4px;'>
            <span style='color:{_diag_color}; font-weight:bold; font-size:14px;'>{_diag_text}</span>
            <span style='color:#aaa; font-size:13px; margin-left:8px;'>{_diag_logic}</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

    # ── 6 年时序：上层 winner 色带（切换瞬间陡峭可见）+ 下层 4 概率独立折线 ──
    if _sr_timeline:
        from plotly.subplots import make_subplots

        _df_sr_tl = pd.DataFrame(_sr_timeline)
        _df_sr_tl["date"] = pd.to_datetime(_df_sr_tl["date"])

        # ── 两张并列 SPY 染色图 ──
        # 上：horsemen（月频基本面）winner 染色；下：sector_rotation（日频资金流）winner 染色。
        # 用同一段 SPY 价格做底图，肉眼对比两套体系对宏观切换的定义。
        _sr_bg_color = {
            "Soft": "rgba(46,204,113,0.18)",
            "Hot":  "rgba(22,160,133,0.18)",
            "Stag": "rgba(241,196,15,0.18)",
            "Rec":  "rgba(197,216,109,0.18)",
        }
        _sr_legend_color = {
            "Soft": "#2ECC71",
            "Hot":  "#16A085",
            "Stag": "#F1C40F",
            "Rec":  "#C5D86D",
        }
        _hm_bg_color = {
            "软着陆": "rgba(46,204,113,0.18)",
            "再通胀": "rgba(22,160,133,0.18)",
            "滞胀":   "rgba(241,196,15,0.18)",
            "衰退":   "rgba(197,216,109,0.18)",
            "混沌期": "rgba(231,76,60,0.20)",
        }
        _hm_legend_color = {
            "软着陆": "#2ECC71",
            "再通胀": "#16A085",
            "滞胀":   "#F1C40F",
            "衰退":   "#C5D86D",
            "混沌期": "#E74C3C",
        }
        if (
            df_prices is not None
            and "SPY" in df_prices.columns
            and len(df_prices) > 0
        ):
            _sr_start = _df_sr_tl["date"].iloc[0]
            _sr_end   = _df_sr_tl["date"].iloc[-1]
            _spy_sr = (
                df_prices["SPY"]
                .dropna()
                .astype(float)
                .loc[_sr_start:_sr_end]
            )

            # ── 上图：SPY × horsemen winner 染色 ──
            _hmp_sr27 = (_current_regime or {}).get("horsemen_monthly_probs", {}) or {}
            _en_to_cn_sr27 = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
            _hm_recs_sr27 = []
            for _m_str, _probs in _hmp_sr27.items():
                try:
                    _m_ts = pd.Timestamp(str(_m_str) + "-01")
                except Exception:
                    continue
                if not isinstance(_probs, dict):
                    continue
                _cands = {k: float(_probs.get(k, 0.0) or 0.0) for k in _en_to_cn_sr27.keys()}
                _winner_en_27 = max(_cands, key=lambda k: _cands[k])
                _winner_cn_27 = _en_to_cn_sr27.get(_winner_en_27, "软着陆")
                _chaos_27 = bool(_probs.get("chaos_gbdt_trigger", False))
                _hm_recs_sr27.append((_m_ts, _winner_cn_27, _chaos_27))

            if _hm_recs_sr27 and not _spy_sr.empty:
                _df_hm_sr27 = (
                    pd.DataFrame(_hm_recs_sr27, columns=["date", "verdict", "chaos"])
                    .set_index("date").sort_index()
                )
                _hm_daily_27 = _df_hm_sr27["verdict"].reindex(_spy_sr.index, method="ffill")
                _hm_chaos_27 = _df_hm_sr27["chaos"].reindex(_spy_sr.index, method="ffill").fillna(False).astype(bool)
                _hm_disp_27 = _hm_daily_27.copy()
                _hm_disp_27.loc[_hm_chaos_27] = "混沌期"
                _hm_disp_27 = _hm_disp_27.dropna()

                _hm_bg_shapes = []
                _prev_h = None
                _seg_start_h = None
                for _dt, _h in _hm_disp_27.items():
                    if _h != _prev_h:
                        if _prev_h is not None and _seg_start_h is not None:
                            _hm_bg_shapes.append(dict(
                                type="rect", x0=_seg_start_h, x1=_dt,
                                y0=0, y1=1, yref="paper",
                                fillcolor=_hm_bg_color.get(_prev_h, "rgba(128,128,128,0.1)"),
                                line_width=0, layer="below",
                            ))
                        _prev_h = _h
                        _seg_start_h = _dt
                if _prev_h is not None and _seg_start_h is not None:
                    _hm_bg_shapes.append(dict(
                        type="rect", x0=_seg_start_h, x1=_hm_disp_27.index[-1],
                        y0=0, y1=1, yref="paper",
                        fillcolor=_hm_bg_color.get(_prev_h, "rgba(128,128,128,0.1)"),
                        line_width=0, layer="below",
                    ))

                _fig_spy_hm = go.Figure()
                _fig_spy_hm.add_trace(go.Scatter(
                    x=_spy_sr.index, y=_spy_sr.values,
                    mode="lines", name="SPY 收盘",
                    line=dict(color="#FFFFFF", width=1.6),
                    hovertemplate="%{x|%Y-%m-%d}<br>SPY: $%{y:.2f}<extra></extra>",
                ))
                for _k in ["软着陆", "再通胀", "滞胀", "衰退", "混沌期"]:
                    _fig_spy_hm.add_trace(go.Scatter(
                        x=[None], y=[None], mode="markers",
                        marker=dict(size=12, color=_hm_legend_color.get(_k, "#888"), symbol="square"),
                        name=_k, showlegend=True,
                    ))
                _fig_spy_hm.update_layout(
                    height=280,
                    margin=dict(l=20, r=20, t=40, b=20),
                    plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                    font=dict(color="#ddd"),
                    showlegend=True,
                    legend=dict(orientation="h", y=1.18, x=0.5, xanchor="center", font=dict(size=12)),
                    hovermode="x unified",
                    xaxis=dict(showgrid=False),
                    yaxis=dict(title="SPY 收盘价 ($)", showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
                    title=dict(
                        text="SPY 历史路况：horsemen winner 染色背景 — 月频基本面剧本对宏观切换的定义",
                        font=dict(size=14), x=0.01, xanchor="left",
                    ),
                    shapes=_hm_bg_shapes,
                )
                st.plotly_chart(_fig_spy_hm, use_container_width=True)

            if not _spy_sr.empty:
                _winner_aligned = (
                    _df_sr_tl.set_index("date")["winner"]
                    .reindex(_spy_sr.index, method="ffill")
                    .dropna()
                )
                _sr_bg_shapes = []
                _prev_w = None
                _seg_start_w = None
                for _dt, _w in _winner_aligned.items():
                    if _w != _prev_w:
                        if _prev_w is not None and _seg_start_w is not None:
                            _sr_bg_shapes.append(dict(
                                type="rect", x0=_seg_start_w, x1=_dt,
                                y0=0, y1=1, yref="paper",
                                fillcolor=_sr_bg_color.get(_prev_w, "rgba(128,128,128,0.1)"),
                                line_width=0, layer="below",
                            ))
                        _prev_w = _w
                        _seg_start_w = _dt
                if _prev_w is not None and _seg_start_w is not None:
                    _sr_bg_shapes.append(dict(
                        type="rect", x0=_seg_start_w, x1=_winner_aligned.index[-1],
                        y0=0, y1=1, yref="paper",
                        fillcolor=_sr_bg_color.get(_prev_w, "rgba(128,128,128,0.1)"),
                        line_width=0, layer="below",
                    ))

                _fig_spy_sr = go.Figure()
                _fig_spy_sr.add_trace(go.Scatter(
                    x=_spy_sr.index, y=_spy_sr.values,
                    mode="lines", name="SPY 收盘",
                    line=dict(color="#FFFFFF", width=1.6),
                    hovertemplate="%{x|%Y-%m-%d}<br>SPY: $%{y:.2f}<extra></extra>",
                ))
                # legend 占位：4 个 winner 背景色块（用空散点假装图例）
                for _k in ["Soft", "Hot", "Stag", "Rec"]:
                    _fig_spy_sr.add_trace(go.Scatter(
                        x=[None], y=[None],
                        mode="markers",
                        marker=dict(size=12, color=_sr_legend_color.get(_k, "#888"), symbol="square"),
                        name=_SR_CN.get(_k, _k),
                        showlegend=True,
                    ))
                _fig_spy_sr.update_layout(
                    height=280,
                    margin=dict(l=20, r=20, t=40, b=20),
                    plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                    font=dict(color="#ddd"),
                    showlegend=True,
                    legend=dict(orientation="h", y=1.18, x=0.5, xanchor="center", font=dict(size=12)),
                    hovermode="x unified",
                    xaxis=dict(showgrid=False),
                    yaxis=dict(title="SPY 收盘价 ($)", showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
                    title=dict(
                        text="SPY 历史路况：sector_rotation winner 染色背景 — 肉眼验证资金流剧本对宏观切换的定义",
                        font=dict(size=14), x=0.01, xanchor="left",
                    ),
                    shapes=_sr_bg_shapes,
                )
                st.plotly_chart(_fig_spy_sr, use_container_width=True)

        # winner 离散编码 → 阶梯式 colorscale，避免 plotly 在过渡像素上插值出脏色
        _winner_codes = {"Soft": 0, "Hot": 1, "Stag": 2, "Rec": 3}
        _df_sr_tl["winner_code"] = _df_sr_tl["winner"].map(_winner_codes).astype(float)
        _band_colorscale = [
            [0.000, "#2ECC71"], [0.249, "#2ECC71"],
            [0.250, "#16A085"], [0.499, "#16A085"],
            [0.500, "#F1C40F"], [0.749, "#F1C40F"],
            [0.750, "#C5D86D"], [1.000, "#C5D86D"],
        ]
        _band_customdata = np.array(
            [[_SR_CN.get(w, w) for w in _df_sr_tl["winner"]]],
            dtype=object,
        )

        fig_sr = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.16, 0.84],
            vertical_spacing=0.03,
        )
        fig_sr.add_trace(
            go.Heatmap(
                x=_df_sr_tl["date"],
                y=["winner"],
                z=[_df_sr_tl["winner_code"].values],
                colorscale=_band_colorscale,
                zmin=-0.5, zmax=3.5,
                showscale=False,
                customdata=_band_customdata,
                hovertemplate="%{x|%Y-%m-%d}<br>当日 winner: %{customdata}<extra></extra>",
            ),
            row=1, col=1,
        )
        for k in ["Soft", "Hot", "Stag", "Rec"]:
            fig_sr.add_trace(
                go.Scatter(
                    x=_df_sr_tl["date"],
                    y=_df_sr_tl[k].astype(float),
                    mode="lines",
                    name=_SR_CN.get(k, k),
                    line=dict(color=_SR_COLOR.get(k, "#888"), width=1.6),
                    hovertemplate=f"%{{x|%Y-%m-%d}}<br>{_SR_CN.get(k, k)}: %{{y:.1%}}<extra></extra>",
                ),
                row=2, col=1,
            )
        fig_sr.add_hline(y=0.25, line_dash="dot", line_color="rgba(255,255,255,0.25)",
                         annotation_text="均分线 25%", annotation_position="right", row=2, col=1)
        fig_sr.add_hline(y=0.35, line_dash="dash", line_color="rgba(255,255,255,0.35)",
                         annotation_text="显著切换 35%", annotation_position="right", row=2, col=1)
        fig_sr.update_yaxes(showticklabels=False, showgrid=False, row=1, col=1)
        fig_sr.update_yaxes(
            title="4 剧本概率", tickformat=".0%", range=[0, 1],
            showgrid=True, gridcolor="rgba(255,255,255,0.06)", row=2, col=1,
        )
        fig_sr.update_xaxes(showgrid=False, row=1, col=1)
        fig_sr.update_xaxes(showgrid=False, row=2, col=1)
        fig_sr.update_layout(
            height=420,
            margin=dict(l=20, r=20, t=50, b=20),
            plot_bgcolor="#111111", paper_bgcolor="#111111",
            font=dict(color="#ddd"),
            hovermode="x unified",
            legend=dict(orientation="h", y=1.18, x=0.5, xanchor="center", font=dict(size=12)),
            title=dict(
                text="6 年 sector_rotation 剧本切换 · 上层 winner 色带（切换瞬间陡峭） · 下层 4 概率独立折线",
                font=dict(size=14), x=0.01, xanchor="left",
            ),
        )
        st.plotly_chart(fig_sr, use_container_width=True)

    # ── 11 板块 RS 历史热力图（6 年）──
    # 前端直接复现后端 _compute_sector_rs_multi 的加权 RS（20D 0.25 + 60D 0.5 + 120D 0.25），
    # 保证和 §"当前 11 板块 RS 排名表"列出来的 RS 60D 同一口径。
    _SECTORS_11_HM = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE",
                      "XLI", "XLB", "XLU", "XLRE", "XLC"]
    _sectors_avail_hm = [
        t for t in _SECTORS_11_HM
        if df_prices is not None and t in df_prices.columns
    ]
    _spy_ok_hm = (
        df_prices is not None and "SPY" in df_prices.columns
        and len(df_prices) >= 200
    )
    if len(_sectors_avail_hm) >= 8 and _spy_ok_hm:
        _RS_HM_LOOKBACKS = {20: 0.25, 60: 0.50, 120: 0.25}
        _spy_pct_hm = {L: df_prices["SPY"].pct_change(L) for L in _RS_HM_LOOKBACKS}
        _hm_dict = {}
        for _t in _sectors_avail_hm:
            _rs_w = None
            for _L, _w in _RS_HM_LOOKBACKS.items():
                _r = df_prices[_t].pct_change(_L) - _spy_pct_hm[_L]
                _rs_w = _r * _w if _rs_w is None else _rs_w + _r * _w
            _hm_dict[_t] = _rs_w
        _df_hm_rs = pd.DataFrame(_hm_dict).dropna(how="all")
        if len(_df_hm_rs) > 1500:
            _df_hm_rs = _df_hm_rs.iloc[-1500:]

        # y 轴按当前 rank 从强到弱排（rank=1 在顶部）
        _y_order_hm = sorted(_sectors_avail_hm,
                             key=lambda t: int(_sr_ranks.get(t, 9999)))
        _z_hm = _df_hm_rs[_y_order_hm].T.values.astype(float)

        st.markdown("**🌡️ 11 板块 RS 加权历史热力图（6 年；y 轴按当前排名从强到弱）**")
        fig_hm = go.Figure(data=go.Heatmap(
            z=_z_hm,
            x=_df_hm_rs.index,
            y=_y_order_hm,
            colorscale="RdYlGn",
            zmid=0.0, zmin=-0.15, zmax=0.15,
            colorbar=dict(title="RS", thickness=12, tickformat=".0%"),
            hovertemplate=("日期: %{x|%Y-%m-%d}<br>板块: %{y}"
                           "<br>加权 RS: %{z:+.2%}<extra></extra>"),
        ))
        fig_hm.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=40, b=20),
            plot_bgcolor="#111111", paper_bgcolor="#111111",
            font=dict(color="#ddd"),
            title=dict(
                text="绿 = 跑赢 SPY，红 = 跑输 SPY · 横看每板块的持续走强/走弱时段",
                font=dict(size=13), x=0.01, xanchor="left",
            ),
            yaxis=dict(autorange="reversed"),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig_hm, use_container_width=True)

    # ── 当前 11 板块 RS 排名表 ──
    if _sr_ranks:
        st.markdown("**📋 当前板块 RS 排名（rank=1 最强，标记每个板块在 4 剧本模板中的角色）**")
        _table_rows = []
        for t, r in sorted(_sr_ranks.items(), key=lambda kv: kv[1]):
            row = {"排名": int(r), "板块": t, "RS 60D": float(_sr_rs_curr.get(t, 0.0))}
            for scen in ["Soft", "Hot", "Stag", "Rec"]:
                tpl = _sr_templates.get(scen, {}) or {}
                strong_set = set(tpl.get("strong") or [])
                weak_set   = set(tpl.get("weak") or [])
                if t in strong_set:   role = "强"
                elif t in weak_set:   role = "弱"
                else:                 role = "中"
                row[_SR_CN.get(scen, scen)] = role
            _table_rows.append(row)
        _df_sr_tbl = pd.DataFrame(_table_rows)

        def _color_role(v):
            if v == "强": return "color: #2ECC71; font-weight: bold"
            if v == "弱": return "color: #E74C3C"
            return "color: #888"

        def _color_rs(v):
            try:
                f = float(v)
                if f > 0.05:  return "color: #2ECC71; font-weight: bold"
                if f > 0:     return "color: #aaa"
                if f < -0.05: return "color: #E74C3C; font-weight: bold"
                return "color: #888"
            except Exception:
                return "color: #aaa"

        st.dataframe(
            _df_sr_tbl.style.format({"RS 60D": "{:+.4f}"})
                .map(_color_role, subset=["软着陆", "再通胀", "滞胀", "衰退"])
                .map(_color_rs,   subset=["RS 60D"]),
            use_container_width=True, hide_index=True,
        )

    with st.expander("📖 算法白盒 & 为什么和 horsemen 并联", expanded=False):
        st.markdown("""
**两张时序图怎么读**

- **上层 winner 色带**：每天的颜色 = 当日 sector_rotation 的 winner（绿=软着陆 / 青绿=再通胀 / 黄=滞胀 / 橄榄绿=衰退）。**色块边界 = 剧本切换日**，肉眼即可数清 6 年里发生过几次切换。
- **下层 4 概率折线**：4 条独立折线，**winner 通常贴近或高于 35% 虚线**（显著切换阈值）；4 条都在 25% 均分线附近 = 低置信"模糊期"。
- **11 板块 RS 热力图**：横轴 6 年时间，纵轴 11 板块按当前排名从强到弱排。**横看一行**得到「这个板块从什么时候开始持续走强/走弱」；**竖看一列**得到「这一天 11 板块各自表现」。配合上方 winner 色带切换日 → 验证模板：例如 2022-04 切到 Stag 当天起 XLE 那行应该开始大片绿、XLK 那行开始大片红。

---

**为什么要有这套？**

主理人质疑过四象限剧本"切了又切回去没意义"——美股 75%+ 时间软着陆，宏观变量切换得太慢且经常反复，按 horsemen 月频信号操作大概率跑不赢 buy-hold SPY。

**但板块轮动不一样**——大盘涨这件事抹杀宏观差异，**谁在领涨却没法骗人**。Sam Stovall 的 Sector Rotation Model 是华尔街用了 30 年的经典：

| 剧本 | 典型领涨板块 | 典型领跌板块 |
|---|---|---|
| 软着陆 / 早周期 | XLK / XLY / XLF / XLC / XLI（进攻） | XLU / XLP / XLV（防御） |
| 再通胀 / 加息 | XLE / XLB / XLF / XLI（周期+商品） | XLK / XLY / XLC / XLRE（高估值杀） |
| 滞胀 | XLE / XLP / XLV / XLU（能源+防御） | XLY / XLF / XLK / XLRE |
| 衰退 | XLP / XLU / XLV（纯防御） | XLY / XLF / XLI / XLB / XLK |

---

**算法（白盒可解释）**

1. **多窗口 RS**：11 板块对 SPY 的 20 日 / 60 日 / 120 日累计超额收益，权重 0.25 / 0.5 / 0.25 加权
2. **板块排名**：当日 11 板块按加权 RS 从高到低排名（rank=1 最强）
3. **匹配分**：对每个剧本，强板块应排名靠前（rank 小得分高）、弱板块应排名靠后（rank 大得分高），归一化到 [0, 1]
4. **Softmax**：温度 T=1.5，4 剧本概率和=100%
5. **平滑**：输出概率 5 日 EMA，避免单日抖动

---

**与 horsemen 体系的关系**

| | horsemen GBDT | sector_rotation |
|---|---|---|
| 数据源 | 14 个 FRED + ETF 比率（基本面） | 11 板块 RS 排名（资金流） |
| 频率 | 月频 | 日频 |
| 性质 | 基本面驱动 | 资金流驱动 |
| 滞后/领先 | 滞后于市场 | 领先于基本面 2-3 个月 |

**两套并联使用——重头戏在分歧处**：
- horsemen 还判 Soft 但 sector_rotation 已切 Hot → 资金流抢跑，未来 2-3 个月基本面将跟上
- horsemen 判 Stag 但 sector_rotation 判 Soft → 基本面落后于资金流，可能是 false alarm

---

**历史经典切换点验证**

后端实测：
- 2022-04 加息开局 → Stag ✓
- 2024-02 AI 行情起点 → Soft ✓
- 2025-04 关税暴跌 → Rec ✓

---

**实操价值**

板块轮动信号对应**板块层面的换仓**（XLK→XLE 之类），不是仓位进出（chaos 闸门管那个）。粒度刚好——
- 当前剧本切换时，调整持仓中板块权重而非清仓
- 4 剧本概率分布平时较平（25/25/25/25 附近）属正常，winner 偏离 35%+ 才是显著切换信号
- 与 horsemen 长期分歧时，作为基本面前置预警

**输出位置**：本节是观察工具，不接入下单链——主理人看时序判断当前是不是"该调结构"的时候。
""")

# ============================================================
# Section 3: 市场分化证据链 (Market Differentiation)
# ============================================================
st.markdown("---")
st.header("🛠️ 市场分化证据链 (Market Differentiation)")
st.caption("共振 (大家都一样) vs 分化 (只有少数人赢) — 结构性机会的早期预警")

if df_prices is None or df_prices.empty:
    st.warning("⚠️ 价格数据不可用")
else:
    sector_disp_cols = [t for t in ['XLK', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE', 'XLC'] if t in df_prices.columns]
    _spy_valid = 'SPY' in df_prices.columns and df_prices['SPY'].dropna().shape[0] > 0
    _rsp_valid = 'RSP' in df_prices.columns and df_prices['RSP'].dropna().shape[0] > 0
    if _spy_valid and _rsp_valid and len(sector_disp_cols) >= 5:
        df_disp = df_prices[['SPY', 'RSP'] + sector_disp_cols].dropna(how='all').copy()
        spy_base = df_disp['SPY'].dropna().iloc[0]
        rsp_base = df_disp['RSP'].dropna().iloc[0]
        df_disp['SPY_Norm'] = (df_disp['SPY'] / spy_base - 1) * 100
        df_disp['RSP_Norm'] = (df_disp['RSP'] / rsp_base - 1) * 100
        df_disp['Dispersion'] = df_disp[sector_disp_cols].pct_change().std(axis=1) * 100
        df_disp['Dispersion_MA20'] = df_disp['Dispersion'].rolling(20).mean()

        c_d1, c_d2 = st.columns(2)
        with c_d1:
            st.markdown("**🛠️ 抱团指数：市值加权(红) vs 等权(蓝)**")
            fig_d1 = go.Figure()
            fig_d1.add_trace(go.Scatter(x=df_disp.index, y=df_disp['SPY_Norm'], name="SPY (市值) %", line=dict(color='#E74C3C', width=2)))
            fig_d1.add_trace(go.Scatter(x=df_disp.index, y=df_disp['RSP_Norm'], name="RSP (等权) %", line=dict(color='#3498DB', width=2), fill='tonexty'))
            fig_d1.update_layout(height=350, hovermode="x unified", legend=dict(orientation="h", y=1.1), plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'))
            st.plotly_chart(fig_d1, use_container_width=True)
        with c_d2:
            st.markdown("**🌊 板块离散度 (Dispersion)**")
            fig_d2 = go.Figure()
            fig_d2.add_trace(go.Scatter(x=df_disp.index, y=df_disp['Dispersion_MA20'], name="离散度 (MA20)", line=dict(color='#8E44AD', width=2), fill='tozeroy'))
            fig_d2.add_hline(y=1.5, line_dash="dot", line_color="red", annotation_text="混乱")
            fig_d2.add_hline(y=0.5, line_dash="dot", line_color="green", annotation_text="一致")
            fig_d2.update_layout(height=350, hovermode="x unified", legend=dict(orientation="h", y=1.1), plot_bgcolor='#111111', paper_bgcolor='#111111', font=dict(color='#ddd'))
            st.plotly_chart(fig_d2, use_container_width=True)
    else:
        st.warning("⚠️ SPY / RSP / 板块 ETF 数据不全，无法计算分化证据链")

# ============================================================
# Section 4: 指数主力归因 (Index Leadership)
# ============================================================
st.markdown("---")
st.header("🏆 指数主力归因 (Index Leadership)")
st.caption("近期是谁在扛大盘？Mag7 / 大盘 / 等权 / 中盘 / 小盘 五带累计涨幅对比（窗口起点归一到 100）")

_LEAD_TICKERS = ["MAGS", "SPY", "RSP", "IJH", "IWM"]
_LEAD_COLORS = {
    "MAGS": "#E74C3C",
    "SPY":  "#95A5A6",
    "RSP":  "#3498DB",
    "IJH":  "#F1C40F",
    "IWM":  "#2ECC71",
}
_LEAD_LABELS = {
    "MAGS": "MAGS · Mag7",
    "SPY":  "SPY · 标普500",
    "RSP":  "RSP · 等权",
    "IJH":  "IJH · 中盘400",
    "IWM":  "IWM · Russell 2000",
}

_lead_avail = [t for t in _LEAD_TICKERS if t in (df_prices.columns if df_prices is not None else [])]
_lead_missing = [t for t in _LEAD_TICKERS if t not in _lead_avail]

if df_prices is None or df_prices.empty or len(_lead_avail) < 3:
    st.warning(f"⚠️ 主力归因数据不全（缺失 {_lead_missing}），跳过此 section")
else:
    if _lead_missing:
        st.info(f"ℹ️ 部分 ETF 数据缺失：{_lead_missing}，仅展示可用 {_lead_avail}")

    _df_lead = df_prices[_lead_avail].dropna(how='all').ffill().dropna()

    def _slice_window(df_in, window_name: str):
        """按窗口名返回切片 + 起点价。"""
        if window_name == "1M":
            n = 21
            return df_in.iloc[-n:] if len(df_in) >= n else df_in
        if window_name == "3M":
            n = 63
            return df_in.iloc[-n:] if len(df_in) >= n else df_in
        if window_name == "YTD":
            ts = df_in.index[-1]
            ytd_start = pd.Timestamp(year=ts.year, month=1, day=2)
            mask = df_in.index >= ytd_start
            return df_in.loc[mask] if mask.any() else df_in
        return df_in

    def _normalize_to_100(df_in):
        base = df_in.iloc[0]
        return (df_in / base) * 100.0

    _tab_1m, _tab_3m, _tab_ytd = st.tabs(["📅 近 1 个月 (1M)", "📅 近 3 个月 (3M)", "📅 年初至今 (YTD)"])

    def _render_lead_tab(window_name, tab):
        with tab:
            _seg = _slice_window(_df_lead, window_name)
            if _seg.empty or len(_seg) < 2:
                st.warning(f"⚠️ {window_name} 窗口数据不足")
                return
            _seg_norm = _normalize_to_100(_seg)
            _fig = go.Figure()
            for t in _lead_avail:
                if t not in _seg_norm.columns:
                    continue
                _is_spy = (t == "SPY")
                _fig.add_trace(go.Scatter(
                    x=_seg_norm.index,
                    y=_seg_norm[t].astype(float),
                    mode='lines',
                    name=_LEAD_LABELS.get(t, t),
                    line=dict(
                        color=_LEAD_COLORS.get(t, "#888"),
                        width=2.0,
                        dash='dash' if _is_spy else 'solid',
                    ),
                ))
            _fig.add_hline(y=100, line_dash="dot", line_color="rgba(255,255,255,0.25)")
            _fig.update_layout(
                height=380,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor='#111111', paper_bgcolor='#111111',
                font=dict(color='#ddd'),
                hovermode="x unified",
                legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center", font=dict(size=12)),
                xaxis=dict(showgrid=False),
                yaxis=dict(title="窗口起点 = 100", showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
                title=dict(text=f"{window_name} 累计涨幅（窗口起点 = 100，SPY 虚线为参照）", font=dict(size=14), x=0.01, xanchor='left'),
            )
            st.plotly_chart(_fig, use_container_width=True)

    _render_lead_tab("1M",  _tab_1m)
    _render_lead_tab("3M",  _tab_3m)
    _render_lead_tab("YTD", _tab_ytd)

    # ── 归因柱状图：1M / 3M / YTD × 4 ETF（MAGS / SPY / RSP / IWM） ──
    _BAR_TICKERS = [t for t in ["MAGS", "SPY", "RSP", "IWM"] if t in _lead_avail]

    def _window_return(df_in, window_name: str) -> dict:
        _seg = _slice_window(df_in, window_name)
        if _seg.empty or len(_seg) < 2:
            return {t: 0.0 for t in _BAR_TICKERS}
        _ret = {}
        for t in _BAR_TICKERS:
            if t not in _seg.columns:
                _ret[t] = 0.0
                continue
            _s = _seg[t].dropna()
            if len(_s) < 2:
                _ret[t] = 0.0
                continue
            _ret[t] = float((_s.iloc[-1] / _s.iloc[0] - 1.0) * 100.0)
        return _ret

    _ret_1m  = _window_return(_df_lead, "1M")
    _ret_3m  = _window_return(_df_lead, "3M")
    _ret_ytd = _window_return(_df_lead, "YTD")

    _bar_rows = []
    for window_name, ret_map in [("1M", _ret_1m), ("3M", _ret_3m), ("YTD", _ret_ytd)]:
        for t in _BAR_TICKERS:
            _bar_rows.append({"窗口": window_name, "ETF": t, "涨幅%": round(ret_map.get(t, 0.0), 2)})
    _df_bar = pd.DataFrame(_bar_rows)

    fig_bar = go.Figure()
    for t in _BAR_TICKERS:
        _sub = _df_bar[_df_bar["ETF"] == t]
        fig_bar.add_trace(go.Bar(
            x=_sub["窗口"].tolist(),
            y=_sub["涨幅%"].astype(float).tolist(),
            name=_LEAD_LABELS.get(t, t),
            marker_color=_LEAD_COLORS.get(t, "#888"),
        ))
    fig_bar.add_hline(y=0, line_dash="dot", line_color="rgba(255,255,255,0.3)")
    fig_bar.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='#111111', paper_bgcolor='#111111',
        font=dict(color='#ddd'),
        barmode='group',
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center", font=dict(size=12)),
        yaxis=dict(title="期间总涨幅 (%)", showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
        xaxis=dict(showgrid=False),
        title=dict(text="1M / 3M / YTD 归因柱状图", font=dict(size=14), x=0.01, xanchor='left'),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── 旁白卡片（三句话规则化产出） ──
    def _format_pct(v: float) -> str:
        return f"{v:+.2f}%"

    # 第 1 句：扛把子（取 3M 涨幅最高）
    _champ_pool = {t: _ret_3m.get(t, 0.0) for t in _lead_avail}
    if _champ_pool:
        _champion = max(_champ_pool.keys(), key=lambda t: _champ_pool[t])
        _champ_label = _LEAD_LABELS.get(_champion, _champion)
        _ranking_text = ", ".join(
            [f"{_LEAD_LABELS.get(t, t)} {_format_pct(v)}"
             for t, v in sorted(_champ_pool.items(), key=lambda kv: kv[1], reverse=True)]
        )
    else:
        _champion    = "—"
        _champ_label = "—"
        _ranking_text = "数据不足"

    # 第 2 句：宽度信号（RSP/SPY 比值近 60D 斜率）
    _width_signal = "中性"
    _slope_60d_w  = 0.0
    if "RSP" in _df_lead.columns and "SPY" in _df_lead.columns and len(_df_lead) >= 60:
        _ratio = (_df_lead["RSP"] / _df_lead["SPY"]).dropna()
        if len(_ratio) >= 60:
            _ratio_60 = _ratio.iloc[-60:].values.astype(float)
            _slope_60d_w = float(np.polyfit(np.arange(60), _ratio_60, 1)[0])
            if   _slope_60d_w > 1e-5:  _width_signal = "扩张中"
            elif _slope_60d_w < -1e-5: _width_signal = "收缩中"
            else:                      _width_signal = "中性"

    # 第 3 句：风格切换警报（MAGS - IWM 价差归一化后 60D 斜率）
    _alert         = "数据不足"
    _slope_60d_d   = 0.0
    if "MAGS" in _df_lead.columns and "IWM" in _df_lead.columns and len(_df_lead) >= 252:
        _diff = (_df_lead["MAGS"] - _df_lead["IWM"]).dropna()
        if len(_diff) >= 252:
            _base_252 = _diff.iloc[-252]
            if abs(_base_252) > 1e-9:
                _diff_norm = (_diff / _base_252) * 100.0
                _arr_60 = _diff_norm.iloc[-60:].values.astype(float)
                _slope_60d_d = float(np.polyfit(np.arange(60), _arr_60, 1)[0])
                _arr_5 = _diff_norm.iloc[-5:].values.astype(float)
                _slope_5d_d = float(np.polyfit(np.arange(5), _arr_5, 1)[0])
                _down_days_21 = int(_diff_norm.iloc[-21:].diff().lt(0).sum())
                if _slope_60d_d > 0:
                    _alert = "未触发"
                elif _slope_60d_d < 0 and _slope_5d_d < 0 and _down_days_21 >= 15:
                    _alert = "已切换"
                else:
                    _alert = "早期信号"

    _alert_color = {"未触发": "#2ECC71", "早期信号": "#F1C40F", "已切换": "#E74C3C"}.get(_alert, "#888")
    _width_color = {"扩张中": "#2ECC71", "收缩中": "#E74C3C", "中性": "#888"}.get(_width_signal, "#888")

    st.markdown(f"""
    <div class='insight-box'>
        <div class='insight-title'>🧠 主力归因白盒解读</div>
        <div class='insight-section'>
            <span class='key-point'>🏆 近 3 个月扛把子：</span>
            <span class='tag-bull'>{_champ_label}</span>
            <span style='color:#aaa; margin-left:8px; font-size:13px;'>排名：{_ranking_text}</span>
        </div>
        <div class='insight-section'>
            <span class='key-point'>📡 宽度信号：</span>
            <span style='color:{_width_color}; font-weight:bold;'>{_width_signal}</span>
            <span style='color:#888; margin-left:8px; font-size:13px;'>RSP/SPY 比值近 60 日斜率 {_slope_60d_w:.6f}</span>
        </div>
        <div class='insight-section'>
            <span class='key-point'>🚨 风格切换警报：</span>
            <span style='color:{_alert_color}; font-weight:bold;'>{_alert}</span>
            <span style='color:#888; margin-left:8px; font-size:13px;'>MAGS-IWM 归一化 60 日斜率 {_slope_60d_d:.4f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
