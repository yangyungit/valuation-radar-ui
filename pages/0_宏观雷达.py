import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from api_client import (
    fetch_macro_radar,
    fetch_current_regime,
    get_global_data,
    compute_macro_regime_api,
)

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
st.caption("市场结构总览 · 全景雷达 · 趋势状态机 · 分化证据链 · 主力归因")

# --- 侧边栏缓存控制 ---
with st.sidebar:
    if st.button("🔄 强制刷新雷达数据"):
        fetch_macro_radar.clear()
        fetch_current_regime.clear()
        compute_macro_regime_api.clear()
        get_global_data.clear()
        st.rerun()

# ============================================================
# 数据层（四个 section 共享）
# ============================================================
_PAGE_TICKERS = [
    "SPY", "QQQ", "RSP", "MAGS", "IJH", "IWM",
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLE",
    "XLI", "XLB", "XLU", "XLRE", "XLC",
]

with st.spinner("📊 加载市场结构数据..."):
    df_prices       = get_global_data(_PAGE_TICKERS, years=10)
    _radar          = fetch_macro_radar()
    _current_regime = fetch_current_regime()

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

# ============================================================
# Section 2: 大盘趋势状态机 (Market Trend Matrix)
# ============================================================
st.markdown("---")
st.header("📊 大盘趋势状态机 (Market Trend Matrix)")
st.caption("基于 Close / MA60 / MA200 的四象限绝对强弱切割 · 背景色按月度剧本裁决（chaos 月份显示灰色）")

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
        "再通胀": "rgba(231,76,60,0.15)",
        "滞胀":   "rgba(241,196,15,0.15)",
        "衰退":   "rgba(52,152,219,0.15)",
        "混沌期": "rgba(128,128,128,0.15)",
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
                    折线颜色 = 技术形态状态机（价格维度）。
                    两者不一致时信号最有价值：🟢背景+🔴折线 = 基本面好但技术超跌，潜在抄底窗口；🔴背景+🟢折线 = 宏观恶化但技术仍强，需警惕。
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

# --- 数据准备 ---
with st.spinner("📡 加载传导链数据..."):
    _chain_regime = compute_macro_regime_api(z_window=750)
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
_QUAD_COLOR = {"软着陆": "#2ECC71", "再通胀": "#E74C3C", "滞胀": "#F1C40F", "衰退": "#3498DB"}
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

st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)
_chain_dv   = (_chain_regime or {}).get("horsemen_daily_verdict", {}) or {}
_chain_dc   = (_chain_regime or {}).get("horsemen_daily_confidence", {}) or {}
_chain_dp   = (_chain_regime or {}).get("horsemen_daily_chaos_prob", {}) or {}

# === Row 1: Regime 当前 + 切换日 ===
_REG_EN_CN = {"Soft": "软着陆", "Hot": "再通胀", "Stag": "滞胀", "Rec": "衰退"}
_REG_COLOR = {"Soft": "#2ECC71", "Hot": "#E74C3C", "Stag": "#F1C40F", "Rec": "#3498DB"}
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
_CONF_COLOR = {"high": "#2ECC71", "medium": "#F1C40F", "chaos": "#888"}
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
