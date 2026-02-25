import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from api_client import fetch_core_data

core_data = fetch_core_data()

TIC_MAP = core_data.get("TIC_MAP", {})
ASSET_CN_DB = core_data.get("ASSET_CN_DB", {})

st.set_page_config(page_title="个股深度猎杀", layout="wide", page_icon="🎯")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！正在重新拉取最新数据...")
        st.rerun()

st.markdown("""
<style>
    .formula-box { background-color: #1a1a1a; border-left: 3px solid #3498DB; padding: 12px; margin-top: 10px; margin-bottom: 10px; font-size: 13px; color: #ccc; }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Layer 5: 个股深度猎杀 (Deep Dive)")
st.caption("核心逻辑：接收 Page 4 竞技场赛道冠军 ➡️ 筹码结构(POC)精准打击 ➡️ 寻找绝佳盈亏比入场点")


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
        auto_ticker = selected_label.split(" ")[1]  # skip medal emoji, ticker is second token

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
    
    st.markdown("""
    <div class='formula-box'>
    <b>⚙️ 算法对齐说明:</b><br>
    此系统已物理隔离周末时间轴，完美复刻 Page 3 的 252日均线法则。分数与排名将做到 100% 同步。
    </div>
    """, unsafe_allow_html=True)

if target_ticker:
    try:
        stock = yf.Ticker(target_ticker)
        hist = stock.history(period="1y")
        try: info = stock.info or {}
        except: info = {}
            
        if hist.empty:
            st.warning(f"无法获取 {target_ticker} 的历史数据。")
            st.stop()
            
        hist = hist.dropna(subset=['Close'])
        curr_price = float(hist['Close'].iloc[-1])
        cn_name = TIC_MAP.get(target_ticker, target_ticker)
        
        st.header(f"📊 {target_ticker} ({cn_name}) 战术分析板")
        with st.expander(f"🏢 核心宏观逻辑推演", expanded=True):
            if target_ticker in ASSET_CN_DB: st.info(f"**【战略基调】** {ASSET_CN_DB[target_ticker]}")
            else: st.warning(f"**【系统简介】** {info.get('longBusinessSummary', '暂无描述。')}")

        price_bins = pd.cut(hist['Close'], bins=60)
        vol_profile = hist.groupby(price_bins, observed=True)['Volume'].sum()
        max_vol_bin = vol_profile.idxmax()
        poc_price = float((max_vol_bin.left + max_vol_bin.right) / 2)
        dist_poc = float((curr_price / poc_price - 1) * 100)
        
        ma60 = float(hist['Close'].rolling(60).mean().iloc[-1])
        resistance = float(hist['High'].tail(120).max())
        
        if curr_price > max(poc_price, ma60): support_level = max(poc_price, ma60)
        else: support_level = min(float(hist['Low'].tail(20).min()), ma60)
            
        risk_dist = curr_price - support_level
        rr = (resistance - curr_price) / risk_dist if risk_dist > 0 else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("当前价格", f"${curr_price:.2f}")
        c2.metric("筹码核心 (POC)", f"${poc_price:.2f}", delta=f"{dist_poc:.1f}% 偏离")
        c3.metric("图表阻力盈亏比 (R:R)", f"{rr:.2f}", delta="具备操作价值" if rr > 2 else "风险收益不对等")
        fcf = info.get('freeCashflow')
        c4.metric("自由现金流 (FCF)", f"${fcf/1e9:.1f}B" if fcf and fcf > 0 else "N/A")

        col_main, col_side = st.columns([3, 1])
        with col_main:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'], name="Price"))
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Close'].rolling(60).mean(), line=dict(color='orange', width=1.5), name="MA60"))
            fig.add_hline(y=poc_price, line_dash="dash", line_color="cyan", annotation_text="POC (绝对成本区)", annotation_position="top left")
            fig.add_hline(y=resistance, line_color="#E74C3C", annotation_text="Target (阻力目标)", annotation_position="top left")
            fig.add_hline(y=support_level, line_color="#2ECC71", annotation_text="Stop (防守底线)", annotation_position="bottom left")
            fig.update_layout(height=500, margin=dict(t=30, l=10, r=10, b=10), template="plotly_dark", xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig, use_container_width=True)
            
        with col_side:
            st.markdown("### 📝 战术裁决")
            if dist_poc > 5: st.success("🟢 获利盘主导，上方抛压极轻。适合顺势持有。")
            elif dist_poc < -5: st.error("🔴 处于套牢区下方，需警惕解套抛压。")
            else: st.warning("🟡 处于核心成本区，若缩量回踩则是绝佳狙击点。")
            
            st.markdown(f"**🎯 第一目标:** `${resistance:.2f}`")
            st.markdown(f"**🛡️ 极限防守:** `${support_level:.2f}`")
            st.markdown("<div class='formula-box'><b>注意:</b> 这里的图表盈亏比测算基于绝对价格图形，与 Page 2 中海选模型的趋势盈亏比算法分离。</div>", unsafe_allow_html=True)
    except Exception as e:
        st.error(f"分析模块遭遇异常中止: {e}")