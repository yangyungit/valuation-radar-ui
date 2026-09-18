"""币圈再平衡监控：填当前持仓，看偏离多少、该不该动。

目标权重是 60 日波动率倒数（BTC 垫地板、各 alt 封顶），触发条件用相对偏离带
而不是日历——回测里偏离带 8.7 年只触发 9 次，收益和月度再平衡差不到 1 个百分点。
权重计算和告警判断全在后端 crypto/rebalance_monitor.py，这页只负责展示。
"""

import pandas as pd
import streamlit as st

from api_client import (
    clear_crypto_rebalance_caches,
    fetch_crypto_rebalance,
    fetch_crypto_research_summary,
    fetch_crypto_universe,
)

st.set_page_config(page_title="币圈再平衡", layout="wide", page_icon="⚖️")

DEFAULT_HOLDINGS = [
    {"标的": "BTC", "持仓市值": 40000.0},
    {"标的": "ETH", "持仓市值": 20000.0},
    {"标的": "BNB", "持仓市值": 10000.0},
    {"标的": "SOL", "持仓市值": 15000.0},
    {"标的": "HYPE", "持仓市值": 15000.0},
]

st.title("⚖️ 币圈再平衡监控")
st.caption(
    "填入当前各标的的持仓市值 → 看相对目标权重偏离多少、越不越线、该买该卖多少钱。"
    "**目标权重 = 60 日波动率倒数**（波动大的自动降权），再套 BTC 下限和各 alt 上限。"
    "**触发用相对偏离带，不看日历**——月度再平衡在换 alt 测试里 7 个池子只有 2 个为正、"
    "中位 −3.70%，偏离带触发次数少得多、收益几乎一样。"
    "底部折叠区有回测依据。"
)

uni = fetch_crypto_universe()
if not uni.get("success"):
    st.error(f"⚠️ 后端拿不到币圈价格数据：{uni.get('error', '未知错误')}")
    st.info("💡 本地调试需设 `USE_LOCAL_API=true`，并确认 `valuation-radar/api_server.py` 在跑。")
    st.stop()

available = [a["asset"] for a in uni.get("assets", [])]
start_map = {a["asset"]: a["start"] for a in uni.get("assets", [])}

with st.sidebar:
    st.subheader("触发线")
    band = st.slider("相对偏离带", 0.05, 1.00, 0.25, 0.05,
                     help="某个标的的当前权重相对目标权重偏离超过这个比例才算越线。"
                          "回测主表用的是 25%。")
    if st.button("🔄 强制刷新"):
        clear_crypto_rebalance_caches()
        st.rerun()
    st.caption("可用标的及数据起点：\n\n" +
               "\n\n".join(f"- {t}：{start_map[t]}" for t in available))

st.subheader("当前持仓")
st.caption("市值单位随你（美元 / 人民币都行，只按占比算）。直接改数字，加减行都可以。")
edited = st.data_editor(
    pd.DataFrame(DEFAULT_HOLDINGS),
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_config={
        "标的": st.column_config.SelectboxColumn("标的", options=available, required=True),
        "持仓市值": st.column_config.NumberColumn("持仓市值", min_value=0.0, format="%.0f"),
    },
    key="crypto_holdings",
)

holdings = {}
for _, row in edited.iterrows():
    t, v = row.get("标的"), row.get("持仓市值")
    if not t or pd.isna(v) or float(v) <= 0:
        continue
    holdings[str(t).strip().upper()] = holdings.get(str(t).strip().upper(), 0.0) + float(v)

if not holdings:
    st.info("填至少一个标的的持仓市值。")
    st.stop()

res = fetch_crypto_rebalance(tuple(sorted(holdings.items())), band)
if not res.get("success"):
    st.error(f"⚠️ 算不出来：{res.get('error', '未知错误')}")
    st.stop()

# ── 结论条 ──────────────────────────────────────────────────
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    if res["need_rebalance"]:
        st.error(f"### 🔴 {res['verdict']}")
    else:
        st.success(f"### 🟢 {res['verdict']}")
c2.metric("最大相对偏离", f"{res['max_rel_drift']:.1%}", f"触发线 {res['band']:.0%}",
          delta_color="off")
c3.metric("持仓合计", f"{res['total']:,.0f}",
          f"价格截至 {res['as_of']}（{res['stale_days']} 天前）", delta_color="off")

if res["stale_days"] > 3:
    st.warning(f"⚠️ 价格数据是 {res['stale_days']} 天前的，"
               "波动率和偏离都算在旧价上——先跑 `crypto/fetch_prices.py` 再看结论。")

# ── 偏离明细 ────────────────────────────────────────────────
st.subheader("偏离明细")
rows = res["rows"]
df = pd.DataFrame([{
    "标的": r["asset"],
    "持仓市值": r["holding"],
    "当前权重": r["current_weight"],
    "目标权重": r["target_weight"],
    "相对偏离": r["rel_drift"],
    "该买该卖": r["delta_weight"],
    "金额": r["amount"],
    "相对BTC三年回撤": r["dd_vs_btc_3y"],
    "半年相对BTC": r["rel_6m_vs_btc"],
    "越线": "⚠️" if r["breached"] else "",
} for r in rows])


def _color_amount(v: float) -> str:
    if v > 1:
        return "color: #2ECC71"   # 要买入
    if v < -1:
        return "color: #E74C3C"   # 要卖出
    return "color: #888888"


st.dataframe(
    df.style
      .map(_color_amount, subset=["该买该卖", "金额"])
      .format({
          "持仓市值": "{:,.0f}", "当前权重": "{:.1%}", "目标权重": "{:.1%}",
          "相对偏离": "{:+.1%}", "该买该卖": "{:+.1%}", "金额": "{:+,.0f}",
          "相对BTC三年回撤": "{:+.0%}", "半年相对BTC": "{:+.0%}",
      }),
    hide_index=True,
    width="stretch",
)
st.caption(
    f"**口径**：{res['basis']}。"
    "**金额**为正 = 按目标权重要买入，为负 = 要卖出。"
    "**相对BTC三年回撤**衡量结构性走弱（实测 ADA −79% / DOT −87% 是真衰退，"
    "ETH −26% / BNB −15% 健康），**半年相对BTC**区分它是在回来还是还在跌。"
)

# ── 叮嘱 ────────────────────────────────────────────────────
msgs = res.get("warnings") or []
if msgs:
    st.subheader("叮嘱")
    for m in msgs:
        if m.startswith("[重度]"):
            st.error(m)
        elif m.startswith("[中度]"):
            st.warning(m)
        else:
            st.info(m)

# ── 研究结论 ────────────────────────────────────────────────
with st.expander("📚 这套口径是怎么定出来的（回测依据）"):
    st.markdown("""
**再平衡不是免费的**。换 alt 敏感性测试（固定窗口 2021-01→2026-09，核心固定
BTC+ETH+BNB，第 4 个 alt 在 SOL / ADA / XRP / DOT / LTC / LINK / AVAX 之间轮换）跑出来：

- **波动率倒数降权是对的**：倒数 − 加权 6/7 个池子为正，中位 **+7.76%**，唯一反例是
  SOL 池（−16.48%）。和 alt 自身收益的相关系数 −0.77——四标的里「加权赢」纯粹因为
  SOL 恰好是赢家。
- **月度再平衡站不住**：月度 − 买入持有只有 2/7 为正，中位 **−3.70%**，DOT 池 −18.02%。
  和 alt 自身收益相关 **+0.80**——它是在赌落后的会回来，不是在收割波动。
- **趋势砍半没用**：趋势砍半 − 倒数 0/7 为正，中位 −2.94%，相关仅 −0.17
  （不是选股运气不好，是方法本身不 work）。
- **再平衡放大选错标的的代价**：等权买入持有跨池子散在 36.0~56.6%，等权月度散在
  17.9~59.8%，区间宽了一倍。DOT 池里等权月度 17.9%，和纯 BTC 的 17.8% 一样。

**所以这页只报警、不自动调仓**。机械按「跑输就砍权重」回测是亏的（0/7 为正），
砍不砍要你自己判断这标的是还会回来还是真的完了。

**衰退阈值（回撤 ≤ −45% 且半年相对为负）是拿 11 个已知结局的标的事后校准的**，
换一批标的未必还准。单看回撤分不开——SOL −50% 和 LTC −54% 数字撞车，
但 SOL 年化 +77%、LTC −17%，所以必须两个条件同时成立才报警。

**几个数据上的限制**：11 个标的全是活下来的，没有一个归零（LUNA / FTT 这类拿不到历史），
所以「再平衡对衰退标的有害」的实际强度比测出来的更大，不是反过来；
7 个池子共用 BTC+ETH+BNB 核心，不是 7 次独立实验，而且只有一个区间没做滚动；
HYPE 只有 2024-12 起的 1.8 年数据，用它历史波动算出来的权重偏乐观。
""")

    research = fetch_crypto_research_summary()
    if not research.get("success"):
        st.caption(f"回测汇总表暂不可用：{research.get('error', '未知错误')}")
    else:
        pct = ["年化收益", "年化波动", "最大回撤", "年化换手"]
        num = ["总倍数", "收益/波动", "收益/回撤", "再平衡次数"]
        for key, title, note in (
            ("two_asset", "两标的 BTC/ETH（2018-01 起，8.7 年）",
             "2017 年 ETH 单年 +9034% 会把年化完全带偏，所以主表一律从 2018-01-01 起算。"),
            ("multi_asset", "四标的 BTC/ETH/BNB/SOL（2021-01 起，SOL 上市后）",
             "这张表里「波动率加权」领先，但换 alt 测试说明那是 SOL 赢家效应，别当普适结论。"),
        ):
            data = research.get(key) or []
            if not data:
                continue
            st.markdown(f"**{title}**")
            t = pd.DataFrame(data).set_index("方案")
            st.dataframe(
                t.style.format({**{c: "{:.1%}" for c in pct if c in t.columns},
                                **{c: "{:.2f}" for c in num if c in t.columns}}),
                width="stretch",
            )
            st.caption(note)
