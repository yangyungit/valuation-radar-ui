import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from api_client import fetch_core_data, fetch_vcp_analysis

core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
ASSET_CN_DB = core_data.get("ASSET_CN_DB", {})

st.set_page_config(page_title="VCP 猎杀 & TWAP 作战室", layout="wide", page_icon="🎯")

st.markdown("""
<style>
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 14px; margin: 10px 0; font-size: 14px; color: #ccc; border-radius: 0 6px 6px 0; line-height: 1.7; }
    .twap-box { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); border: 1px solid #0f3460; border-radius: 10px; padding: 20px; margin: 15px 0; font-size: 14px; color: #ddd; line-height: 1.8; }
    .twap-box b { color: #e94560; }
    .grade-a { color: #2ECC71; font-weight: bold; font-size: 26px; }
    .grade-b { color: #3498DB; font-weight: bold; font-size: 26px; }
    .grade-c { color: #F1C40F; font-weight: bold; font-size: 26px; }
    .grade-d { color: #E67E22; font-weight: bold; font-size: 26px; }
    .grade-f { color: #E74C3C; font-weight: bold; font-size: 26px; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──
with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！")
        st.rerun()

with st.sidebar:
    st.header("🎯 猎杀目标选择")

    p4_arena_leaders = st.session_state.get("p4_arena_leaders", {})
    p4_routed = st.session_state.get("p4_champion_ticker", "")

    auto_ticker = ""
    if p4_arena_leaders:
        all_candidates = []
        rank_labels = ["🥇", "🥈", "🥉"]
        for c in ["A", "B", "C", "D"]:
            entries = p4_arena_leaders.get(c, [])
            for rank, entry in enumerate(entries):
                medal = rank_labels[rank] if rank < 3 else ""
                all_candidates.append({
                    "label": f"{medal} {entry['ticker']} ({entry['name']}) | {c}级#{rank+1} {entry['score']:.0f}分",
                    "ticker": entry["ticker"],
                })

        default_idx = 0
        if p4_routed:
            for i, cand in enumerate(all_candidates):
                if cand["ticker"] == p4_routed:
                    default_idx = i
                    break

        st.caption("📡 数据来源：Page 4 竞技场 Top 3 × 4 赛道")
        selected_label = st.selectbox("🏆 赛道精英候选池:", [c["label"] for c in all_candidates], index=default_idx)
        auto_ticker = selected_label.split(" ")[1]

        if p4_routed:
            st.info(f"🏆 竞技场直通：**{p4_routed}**")
            if st.button("✖ 清除路由", key="clear_p4_route"):
                del st.session_state["p4_champion_ticker"]
                st.rerun()
    else:
        st.warning(
            "尚未获取到竞技场冠军数据。\n\n"
            "请先访问 **4 资产强筛** 页面，待各赛道评分完成后再返回此页。"
        )

    st.markdown("---")
    st.caption("手动越权查询 / 覆盖路由:")
    manual_ticker = st.text_input("🔍 输入自定义代码:", value=p4_routed if p4_routed else "").upper()
    target_ticker = manual_ticker if manual_ticker else auto_ticker

    st.markdown("---")
    st.header("📐 VCP 参数")
    lookback_days = st.slider(
        "VCP 回溯天数", 90, 360, 180, step=30,
        help="越长捕获越大级别的 VCP 底部，越短聚焦近期收缩形态",
    )

# ── Main ──
st.title("🎯 Layer 5: VCP 精准猎杀 & TWAP 作战室")
st.caption("核心逻辑：Page 4 竞技场推荐标的 ➡️ Minervini VCP 形态解剖 ➡️ TWAP 最优建仓执行")

if target_ticker:
    try:
        with st.spinner(f"正在拉取 {target_ticker} 历史数据 (2年)..."):
            stock = yf.Ticker(target_ticker)
            hist = stock.history(period="2y")
            try:
                info = stock.info or {}
            except Exception:
                info = {}

        if hist.empty:
            st.warning(f"无法获取 {target_ticker} 的历史数据。")
            st.stop()

        hist = hist.dropna(subset=['Close'])
        if len(hist) < 200:
            st.warning(f"{target_ticker} 历史数据不足 200 个交易日，无法进行 VCP 分析。")
            st.stop()

        curr_price = float(hist['Close'].iloc[-1])
        cn_name = TIC_MAP.get(target_ticker, target_ticker)

        ohlcv = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        if ohlcv.index.tz is not None:
            try:
                ohlcv.index = ohlcv.index.tz_localize(None)
            except TypeError:
                ohlcv.index = ohlcv.index.tz_convert(None)

        with st.spinner("🔬 VCP 引擎深度分析中..."):
            vcp = fetch_vcp_analysis(ohlcv, lookback_days)

        if "error" in vcp:
            st.error(f"VCP 分析失败: {vcp['error']}")
            st.stop()

        # ── Header ──
        st.header(f"📊 {target_ticker} ({cn_name})")
        with st.expander("🏢 基本面简述", expanded=False):
            if target_ticker in ASSET_CN_DB:
                st.info(f"**【战略基调】** {ASSET_CN_DB[target_ticker]}")
            else:
                summary = info.get('longBusinessSummary', '暂无描述。')
                st.info(f"**【简介】** {summary[:300]}{'...' if len(summary) > 300 else ''}")

        # ── Dashboard Metrics ──
        grade = vcp["vcp_grade"]
        score = vcp["vcp_score"]
        grade_css = f"grade-{grade.lower()}"

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("当前价格", f"${curr_price:.2f}")
        mc2.markdown("**VCP 评分**")
        mc2.markdown(f"<span class='{grade_css}'>{score:.0f} ({grade}级)</span>", unsafe_allow_html=True)
        s2_label = "✅ Stage 2 确认" if vcp["stage2"]["is_stage2"] else "❌ 非 Stage 2"
        mc3.metric("趋势阶段", s2_label)
        mc4.metric("TWAP 指令", vcp["twap"]["action_label"])

        # ── VCP Chart ──
        chart_bars = min(len(hist), lookback_days + 60)
        hist_chart = hist.iloc[-chart_bars:].copy()
        if hist_chart.index.tz is not None:
            try:
                hist_chart.index = hist_chart.index.tz_localize(None)
            except TypeError:
                hist_chart.index = hist_chart.index.tz_convert(None)

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.03, row_heights=[0.7, 0.3],
        )

        fig.add_trace(go.Candlestick(
            x=hist_chart.index,
            open=hist_chart['Open'].astype(float),
            high=hist_chart['High'].astype(float),
            low=hist_chart['Low'].astype(float),
            close=hist_chart['Close'].astype(float),
            name="K线",
            increasing_line_color='#2ECC71', decreasing_line_color='#E74C3C',
        ), row=1, col=1)

        ma50_line = hist_chart['Close'].astype(float).rolling(50).mean()
        ma150_line = hist_chart['Close'].astype(float).rolling(150).mean()
        ma200_line = hist_chart['Close'].astype(float).rolling(200).mean()
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma50_line, line=dict(color='#3498DB', width=1), name='MA50'), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma150_line, line=dict(color='#F39C12', width=1), name='MA150'), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist_chart.index, y=ma200_line, line=dict(color='#E74C3C', width=1.5), name='MA200'), row=1, col=1)

        for ci, cw in enumerate(vcp.get("contractions", [])):
            fig.add_shape(
                type="rect",
                x0=cw["peak_date"], x1=cw["trough_date"],
                y0=cw["trough_price"], y1=cw["peak_price"],
                fillcolor=f"rgba(231, 76, 60, {0.08 + ci * 0.04})",
                line=dict(color="rgba(231, 76, 60, 0.4)", width=1),
                row=1, col=1,
            )
            fig.add_annotation(
                x=cw["trough_date"], y=cw["trough_price"],
                text=f"W{cw['wave']}: {cw['depth_pct']:.1f}%",
                showarrow=True, arrowhead=2, arrowcolor="#E74C3C",
                font=dict(size=11, color="#E74C3C"),
                row=1, col=1,
            )

        ext = vcp.get("extrema", [])
        if ext:
            ext_colors = ['#E74C3C' if e['type'] == 'H' else '#2ECC71' for e in ext]
            fig.add_trace(go.Scatter(
                x=[e["date"] for e in ext],
                y=[e["price"] for e in ext],
                mode='lines+markers',
                line=dict(color='rgba(255,255,255,0.4)', width=1, dash='dot'),
                marker=dict(size=7, color=ext_colors),
                name='峰谷极值',
            ), row=1, col=1)

        fig.add_hline(
            y=vcp["pivot"]["price"], line_dash="dash", line_color="cyan",
            annotation_text=f"枢轴点 ${vcp['pivot']['price']:.2f}",
            annotation_position="top left", row=1, col=1,
        )

        twap = vcp["twap"]
        if twap["action"] in ("EXECUTE", "PREPARE"):
            fig.add_hline(y=twap["entry_price"], line_dash="dot", line_color="#2ECC71",
                          annotation_text=f"Entry ${twap['entry_price']:.2f}",
                          annotation_position="bottom right", row=1, col=1)
            fig.add_hline(y=twap["stop_loss"], line_dash="dot", line_color="#E74C3C",
                          annotation_text=f"Stop ${twap['stop_loss']:.2f}",
                          annotation_position="bottom right", row=1, col=1)
            fig.add_hline(y=twap["target_price"], line_dash="dot", line_color="#F1C40F",
                          annotation_text=f"Target ${twap['target_price']:.2f}",
                          annotation_position="top right", row=1, col=1)

        vol_colors = []
        for c_val, o_val in zip(hist_chart['Close'].astype(float), hist_chart['Open'].astype(float)):
            vol_colors.append('#E74C3C' if float(c_val) < float(o_val) else '#2ECC71')
        fig.add_trace(go.Bar(
            x=hist_chart.index, y=hist_chart['Volume'].astype(float),
            marker_color=vol_colors, name='成交量', opacity=0.6,
        ), row=2, col=1)

        vol_ma50 = hist_chart['Volume'].astype(float).rolling(50).mean()
        fig.add_trace(go.Scatter(
            x=hist_chart.index, y=vol_ma50,
            line=dict(color='#F39C12', width=1), name='50日均量',
        ), row=2, col=1)

        fig.update_layout(
            height=650, template="plotly_dark",
            xaxis_rangeslider_visible=False,
            showlegend=True,
            legend=dict(orientation="h", y=1.05, font=dict(size=11)),
            margin=dict(t=40, l=10, r=10, b=10),
        )
        fig.update_yaxes(title_text="价格", row=1, col=1)
        fig.update_yaxes(title_text="成交量", row=2, col=1)

        st.plotly_chart(fig, use_container_width=True)

        # ── Analysis Panels ──
        col_l, col_r = st.columns(2)

        with col_l:
            s2_tag = "通过" if vcp["stage2"]["is_stage2"] else "未通过"
            with st.expander(f"📐 Stage 2 趋势检查（{s2_tag} {vcp['stage2']['score']}/5）", expanded=True):
                for line in vcp["stage2"]["details"]:
                    st.markdown(f"- {line}")
                if not vcp["stage2"]["is_stage2"]:
                    st.warning("⚠️ VCP 的大前提——Stage 2 上升趋势——尚未满足。即使出现收缩形态，成功率大打折扣。")

            with st.expander("📊 量能枯竭分析", expanded=True):
                vc1, vc2 = st.columns(2)
                vc1.metric("近5日均量", f"{vcp['volume']['recent_5d_vol']:,.0f}")
                delta_color = "inverse" if vcp["volume"]["is_dry"] else "normal"
                vc2.metric("50日均量", f"{vcp['volume']['vol_50d_avg']:,.0f}",
                           delta=f"{vcp['volume']['vol_ratio'] * 100:.0f}% 比率", delta_color=delta_color)
                for line in vcp["volume"]["details"]:
                    st.markdown(f"- {line}")

        with col_r:
            with st.expander(f"🌊 收缩波解剖（{vcp['n_contractions']}浪）", expanded=True):
                if vcp["contractions"]:
                    st.markdown(f"**收缩路径:** {vcp['contraction_summary']}")
                    c_rows = []
                    for cw in vcp["contractions"]:
                        c_rows.append({
                            "波段": f"Wave {cw['wave']}",
                            "峰值": f"${cw['peak_price']:.2f}",
                            "谷底": f"${cw['trough_price']:.2f}",
                            "深度": f"{cw['depth_pct']:.1f}%",
                            "均量": f"{cw['avg_volume']:,.0f}",
                        })
                    st.dataframe(pd.DataFrame(c_rows), use_container_width=True, hide_index=True)
                else:
                    st.warning("未检测到明确的 VCP 收缩波形。该标的可能不在 VCP 形态中。")

            with st.expander("🎯 枢轴点分析", expanded=True):
                st.metric("枢轴点价格", f"${vcp['pivot']['price']:.2f}",
                          delta=f"近10日波幅 {vcp['pivot']['last_10d_range_pct']:.1f}%")
                for line in vcp["pivot"]["details"]:
                    st.markdown(f"- {line}")

        # ── TWAP Command Center ──
        st.markdown("---")
        st.subheader("🏛️ TWAP 作战指挥中心")

        action = twap["action"]
        if action == "EXECUTE":
            st.success(f"**{twap['action_label']}** — 所有条件已满足！")
        elif action == "PREPARE":
            st.info(f"**{twap['action_label']}** — VCP 形态就绪，等待枢轴点突破触发。")
        elif action == "MONITOR":
            st.warning(f"**{twap['action_label']}** — 形态尚在发育，暂不宜入场。")
        else:
            st.error(f"**{twap['action_label']}** — 不具备 VCP 条件，建议观望。")

        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric("🎯 入场价", f"${twap['entry_price']:.2f}")
        tc2.metric("🛡️ 止损价", f"${twap['stop_loss']:.2f}",
                   delta=f"-{twap['risk_pct']:.1f}%", delta_color="inverse")
        tc3.metric("🎪 目标价", f"${twap['target_price']:.2f}")
        rr_tag = "优秀" if twap["rr_ratio"] >= 3 else ("可行" if twap["rr_ratio"] >= 2 else "偏低")
        tc4.metric("📐 盈亏比 R:R", f"{twap['rr_ratio']:.1f}", delta=rr_tag)

        if twap.get("trigger_conditions"):
            st.markdown("**🔔 激活触发条件:**")
            for cond in twap["trigger_conditions"]:
                st.markdown(f"- {cond}")

        st.markdown(f"""
        <div class='twap-box'>
        <b>⚙️ TWAP 执行建议:</b><br><br>
        • 建仓窗口: <b>{twap['twap_window_hours']} 小时</b>（时间加权均匀分割）<br>
        • 风险敞口: <b>{twap['risk_pct']:.1f}%</b>（入场至止损距离）<br>
        • 盈亏比: <b>{twap['rr_ratio']:.1f} : 1</b><br><br>
        {twap['details']}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class='formula-box'>
        <b>📐 VCP 方法论 (Mark Minervini):</b><br><br>
        VCP (Volatility Contraction Pattern) 是机构级趋势交易的黄金模式：<br>
        1. <b>Stage 2 大前提</b> — 股票必须处于长期上升趋势（价格 > 150/200日均线，200MA 向上）<br>
        2. <b>价格收缩</b> — 2-6次回调，每次深度递减（如 -25% → -12% → -4%），浮筹被逐步洗净<br>
        3. <b>量能枯竭</b> — 最后一波收缩中成交量极度萎缩（< 50日均量的50%），无人愿卖<br>
        4. <b>枢轴突破</b> — 价格收敛至极致后，放量突破阻力线（枢轴点）= 最佳入场<br><br>
        <b>TWAP 配合:</b> 发现 VCP 极致收缩 → 次日若放量突破枢轴 → 激活 TWAP 2-4h 平滑建仓，规避单笔冲击成本。
        </div>
        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"分析模块遭遇异常中止: {e}")
        import traceback
        st.code(traceback.format_exc())
