import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from api_client import (
    fetch_macro_radar,
    fetch_current_regime,
    get_global_data,
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
    df_prices       = get_global_data(_PAGE_TICKERS, years=2)
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
st.caption("基于 Close / MA60 / MA200 的四象限绝对强弱切割 · 四色背景需先访问宏观定调页计算后才会叠加")

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

    _dv_mtm = (_current_regime or {}).get("horsemen_daily_verdict", {})
    if _dv_mtm:
        _horsemen_daily_mtm = pd.Series(
            list(_dv_mtm.values()),
            index=pd.to_datetime(list(_dv_mtm.keys())),
        ).sort_index()
    else:
        _horsemen_daily_mtm = pd.Series(dtype=str)

    _dc_mtm = (_current_regime or {}).get("horsemen_daily_confidence", {})
    if _dc_mtm and not _horsemen_daily_mtm.empty:
        _conf_mtm = pd.Series(
            list(_dc_mtm.values()),
            index=pd.to_datetime(list(_dc_mtm.keys())),
        ).sort_index()
        _horsemen_daily_mtm_display = _horsemen_daily_mtm.copy()
        _chaos_idx = _conf_mtm[_conf_mtm == "chaos"].index
        _shared = _horsemen_daily_mtm_display.index.intersection(_chaos_idx)
        if len(_shared) > 0:
            _horsemen_daily_mtm_display.loc[_shared] = "混沌期"
    else:
        _horsemen_daily_mtm_display = _horsemen_daily_mtm

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
