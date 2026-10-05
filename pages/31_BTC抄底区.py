"""BTC 抄底区：全网浮盈跌到 4 年低位时标红，历史上这些红带就是周期底。

指标是浮盈占已实现市值的比值（CapMVRVCur − 1），阈值 −1σ 是回测定的：
红带内买入 1 年后中位 +80%、无一亏损、最差 +12%，对照组（任意日买入）
中位 +78%、胜率 73%、最差 −84%。收益中位数几乎一样，差别全在消掉亏损尾巴。
通道计算和区间判定全在后端 crypto/bottom_zone.py，这页只负责展示。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from api_client import fetch_crypto_bottom_zone, fetch_portfolio_ledger, fetch_portfolio_summary

st.set_page_config(page_title="BTC 周期 · D 策略", layout="wide", page_icon="₿")

ZONE_COLOR = "rgba(231,76,60,0.16)"
DEEP_COLOR = "rgba(192,57,43,0.34)"
SELL_COLOR = "rgba(46,204,113,0.16)"

st.title("₿ BTC 周期 · D 策略")
st.caption(
    "**浮盈 / 已实现市值**跌破 4 年滚动 −1σ 就进抄底区。已实现市值是全网按每枚币"
    "最后一次链上移动时的价格计的总成本，所以这个比值等于「全网浮盈相当于成本的几倍」，"
    "掉到低位说明平均持币人几乎不赚钱。**阈值是回测定的不是抄来的**，依据在页面底部。"
    "**浮盈涨到 +1σ 以上进定卖区（绿色）**，历史上这个位置买入 1 年后中位收益接近 0。"
    "D 策略的仓位按这两条线定投、定卖。"
)

with st.sidebar:
    st.subheader("显示范围")
    span = st.selectbox("时间窗", ["全部", "近 3 年", "近 5 年", "近 8 年"], index=0)
    if st.button("🔄 强制刷新"):
        fetch_crypto_bottom_zone.clear()
        st.rerun()

years = {"全部": None, "近 3 年": 3.0, "近 5 年": 5.0, "近 8 年": 8.0}[span]
res = fetch_crypto_bottom_zone(years)
if not res.get("success"):
    st.error(f"⚠️ 后端拿不到链上数据：{res.get('error', '未知错误')}")
    st.info("💡 本地调试需设 `USE_LOCAL_API=true`，并确认后端在跑、"
            "`crypto/bottom_zone.py --refresh` 至少跑过一次。")
    st.stop()

level = res["level"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("当前状态", "定卖区" if res["in_sell_zone"] else ["正常", "抄底区", "深度抄底区"][level])
c2.metric("浮盈/已实现市值", f"{res['ratio']:.2f}", f"−1σ 线 {res['lower']:.2f}", "off")
c3.metric("z 值", f"{res['z']:+.2f}", f"触发线 {res['zone_z']:+.1f}", "off")
c4.metric("BTC", f"${res['price']:,.0f}", f"数据截至 {res['as_of']}", "off")
c5.metric("本周操作", res["action"])

(st.success if res["in_sell_zone"] else st.error if level == 2
 else st.warning if level == 1 else st.info)(res["verdict"])
if res["stale_days"] > 3:
    st.caption(f"⚠️ 链上数据是 {res['stale_days']} 天前的，"
               "CoinMetrics 正常落后 1-2 天，超过说明更新任务没跑。")

# ---- 主图：价格 + 指标通道，抄底区铺底色 ----
idx = pd.to_datetime(res["dates"])
s = {k: pd.Series(v, index=idx).astype(float) for k, v in res["series"].items()}
lv = pd.Series(res["levels"], index=idx)


def segs(mask: pd.Series) -> list:
    """布尔 Series → 连续区间 [(起, 止)]。"""
    m = mask.fillna(False)
    if not bool(m.any()):
        return []
    return [(g.index[0], g.index[-1])
            for _, g in m.groupby(m.ne(m.shift()).cumsum()) if bool(g.iloc[0])]


fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                    row_heights=[0.52, 0.48])
for row in (1, 2):
    for color, mask in ((ZONE_COLOR, lv == 1), (DEEP_COLOR, lv == 2),
                        (SELL_COLOR, pd.Series(res["sells"], index=idx))):
        for x0, x1 in segs(mask):
            fig.add_vrect(x0=x0, x1=x1, fillcolor=color, line_width=0,
                          layer="below", row=row, col=1)

fig.add_trace(go.Scatter(x=idx, y=s["price"], name="BTC 价格", line=dict(color="#ddd", width=1.2)),
              row=1, col=1)
fig.add_trace(go.Scatter(x=idx, y=s["ratio"], name="浮盈/已实现市值",
                         line=dict(color="#4fc3e8", width=1.3),
                         fill="tozeroy", fillcolor="rgba(79,195,232,0.18)"), row=2, col=1)
for key, label, color, dash in (("upper", "+1σ（定卖线）", "#5cb85c", "dot"),
                                ("mean", "4 年均值", "#b04ec8", "solid"),
                                ("lower", "−1σ（抄底线）", "#f39c12", "dash"),
                                ("deep", "−1.25σ（深度）", "#e74c3c", "dash")):
    fig.add_trace(go.Scatter(x=idx, y=s[key], name=label,
                             line=dict(color=color, width=1.1, dash=dash)), row=2, col=1)

_led = fetch_portfolio_ledger()
if _led.get("success"):
    _d = [t for t in _led["trades"] if t["sleeve"] == "D" and t["ticker"] == "BTC-USD"]
    for sides, name, color, symbol in ((("OPEN", "BUY"), "D 买入", "#2ecc71", "triangle-up"),
                                       (("SELL",), "D 卖出", "#e74c3c", "triangle-down")):
        pts = [t for t in _d if t["side"] in sides]
        if pts:
            fig.add_trace(go.Scatter(
                x=pd.to_datetime([t["date"] for t in pts]), y=[t["price"] for t in pts],
                mode="markers", name=name,
                marker=dict(color=color, symbol=symbol, size=11,
                            line=dict(color="#fff", width=1))), row=1, col=1)

fig.update_yaxes(title_text="BTC 价格（对数）", type="log", gridcolor="#222", row=1, col=1)
fig.update_yaxes(title_text="浮盈 / 已实现市值", gridcolor="#222", row=2, col=1)
fig.update_xaxes(gridcolor="#222", row=2, col=1)
fig.update_layout(height=660, margin=dict(l=60, r=20, t=30, b=30),
                  plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                  font=dict(color="#ccc"), hovermode="x unified",
                  legend=dict(orientation="h", y=1.06, x=0))
st.plotly_chart(fig, width="stretch")
st.caption("浅红 = 抄底区（z ≤ −1σ）　深红 = 深度抄底区（z ≤ −1.25σ）　绿 = 定卖区（z ≥ +1σ）")

# ---- 历史区间表 ----
st.subheader("历史抄底区")
eps = res["episodes"]
tbl = pd.DataFrame([{
    "起": e["start"], "止": e["end"], "天数": e["days"],
    "深度": "●" if e["deep"] else "",
    "区间最低价": f"${e['min_price']:,.0f}",
    "最低 z": f"{e['min_z']:+.2f}",
    "出区后 1 年": "未满 1 年" if e["fwd_1y"] is None else f"{e['fwd_1y'] * 100:+.0f}%",
} for e in reversed(eps)])
st.dataframe(tbl, width="stretch", hide_index=True, height=340)

done = [e for e in eps if e["fwd_1y"] is not None]
if done:
    wins = sum(1 for e in done if e["fwd_1y"] > 0)
    worst = min(done, key=lambda e: e["fwd_1y"])
    st.caption(f"走完的 {len(done)} 段里 {wins} 段出区后 1 年上涨，"
               f"最差一段 {worst['start']} 起 {worst['fwd_1y'] * 100:+.0f}%。")

st.subheader("D 策略持仓")
_sm = fetch_portfolio_summary()
_pos = next((p for p in _sm.get("positions", [])
             if p["sleeve"] == "D" and p["ticker"] == "BTC-USD"), None) if _sm.get("success") else None
_row = next((r for r in _sm.get("sleeves", []) if r["sleeve"] == "D"), None) if _sm.get("success") else None
if _pos and _row and _pos["qty"] > 0:
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("持有数量", f"{_pos['qty']:,.6g} BTC")
    d2.metric("均价", f"${_pos['avg_cost']:,.0f}")
    d3.metric("浮盈", f"{_pos['unrealized_pct']:+.1%}")
    d4.metric("占总仓", f"{_row['weight']:.1%}", "上限 15%", "off")
else:
    st.caption("实盘账本还没有 D 的记录，去『ABCD 实盘』页录入。")

st.subheader("历史定卖区")
sell_eps = res["sell_episodes"]
st.dataframe(pd.DataFrame([{
    "起": e["start"], "止": e["end"], "天数": e["days"],
    "区间最高价": f"${e['max_price']:,.0f}",
    "最高 z": f"{e['max_z']:+.2f}",
    "出区后 1 年": "未满 1 年" if e["fwd_1y"] is None else f"{e['fwd_1y'] * 100:+.0f}%",
} for e in reversed(sell_eps)]), width="stretch", hide_index=True, height=300)

st.subheader("D 策略回测")
bt = res["backtest"]
st_s, st_h = bt["stats"]["strategy"], bt["stats"]["hold"]
b1, b2, b3, b4 = st.columns(4)
b1.metric("策略年化", f"{st_s['cagr']:+.1%}", f"持有 {st_h['cagr']:+.1%}", "off")
b2.metric("策略累计", f"{st_s['total'] + 1:,.0f} 倍", f"持有 {st_h['total'] + 1:,.0f} 倍", "off")
b3.metric("策略最大回撤", f"{st_s['max_dd']:.0%}", f"持有 {st_h['max_dd']:.0%}", "off")
b4.metric("当前 BTC 占比", f"{bt['btc_weight'][-1]:.0%}")

bidx = pd.to_datetime(bt["dates"])
bfig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                     row_heights=[0.7, 0.3])
bfig.add_trace(go.Scatter(x=bidx, y=bt["nav"], name="D 策略",
                          line=dict(color="#b04ec8", width=1.6)), row=1, col=1)
bfig.add_trace(go.Scatter(x=bidx, y=bt["hold"], name="全程持有 BTC",
                          line=dict(color="#ddd", width=1.1, dash="dot")), row=1, col=1)
nav_at = pd.Series(bt["nav"], index=bidx)
for side, color, symbol in (("定投开始", "#f39c12", "triangle-up"),
                            ("定卖开始", "#2ecc71", "triangle-down")):
    pts = [e for e in bt["events"] if e["side"] == side]
    if pts:
        x = pd.to_datetime([e["date"] for e in pts])
        bfig.add_trace(go.Scatter(
            x=x, y=nav_at.reindex(x), mode="markers", name=side,
            customdata=[e["price"] for e in pts],
            hovertemplate="BTC $%{customdata:,.0f}",
            marker=dict(color=color, symbol=symbol, size=11,
                        line=dict(color="#fff", width=1))), row=1, col=1)
bfig.add_trace(go.Scatter(x=bidx, y=bt["btc_weight"], name="BTC 占比",
                          line=dict(color="#b04ec8", width=0.8),
                          fill="tozeroy", fillcolor="rgba(176,78,200,0.25)",
                          hovertemplate="%{y:.0%}"), row=2, col=1)
bfig.update_yaxes(title_text="净值（起点 1，对数）", type="log", gridcolor="#222", row=1, col=1)
bfig.update_yaxes(title_text="BTC 占比", tickformat=".0%", range=[0, 1.05],
                  gridcolor="#222", row=2, col=1)
bfig.update_xaxes(gridcolor="#222", row=2, col=1)
bfig.update_layout(height=560, margin=dict(l=60, r=20, t=30, b=30),
                   plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                   font=dict(color="#ccc"), hovermode="x unified",
                   legend=dict(orientation="h", y=1.08, x=0))
st.plotly_chart(bfig, width="stretch")
st.caption(
    f"规则：从全现金起步，进抄底区（跌破橙色 −1σ 线）当天的现金分 {bt['buy_days']} 天每天等额买完；"
    f"买完后冷却 {bt['cool_days'] / 365:.0f} 年，期间碰到定卖区不卖（四年周期中途的小山峰不算）；"
    f"冷却期过后新进定卖区（涨过绿色 +1σ 线），当天的持仓分 {bt['sell_days']} 天每天等额卖完。"
    "信号按前一天收盘判定、今天收盘成交，闲置现金按 0 收益，不计手续费。"
    "回测始终用全历史，不受左侧时间窗影响。"
)

st.markdown("**冷却期敏感性**")
st.dataframe(pd.DataFrame([{
    "买完后冷却": f"{s['cool_years']:g} 年",
    "年化": f"{s['cagr']:+.1%}",
    "累计": f"{s['total'] + 1:,.0f} 倍",
    "最大回撤": f"{s['max_dd']:.0%}",
    "卖点": "　".join(f"{e['date'][:7]} ${e['price']:,.0f}" for e in s["sells"]),
} for s in bt["sensitivity"]]), width="stretch", hide_index=True)
st.caption(
    "结果对冷却期很敏感：少半年就从上千倍掉到一两百倍，多半年回撤加深到 −77% 以上。"
    "全历史只有 3 轮完整周期，2 年这个最好的结果有事后挑参数的成分，别把它当预期收益。"
    f"稳的结论是冷却 2–3 年都跑赢全程持有（年化 {st_h['cagr']:+.1%}），1.5 年以下就跑输。"
)

with st.expander("阈值怎么来的 / 这两个信号能信到什么程度"):
    st.markdown(f"""
**回测对照**（2014-12 起，共 {len(idx) if years is None else '全历史'} 天样本，持有 1 年）：

| 买入条件 | 占交易日 | 中位收益 | 胜率 | 最差一次 |
|---|---|---|---|---|
| z ≤ −0.75 | 21.6% | +95% | 96% | **−14%** |
| **z ≤ −1.0（本页阈值）** | 10.8% | +80% | **100%** | **+12%** |
| z ≤ −1.25（深度） | 3.2% | +119% | 100% | +14% |
| 对照组：任意一天买入 | 100% | +78% | 73% | **−84%** |

**这个信号买的不是收益，是「不被埋」。** 中位收益 +80% 和随便哪天买的 +78%
几乎没差别——BTC 长期本来就涨。真正的差别在最后两列：红带内买历史上一年后
没亏过，随便买则有四分之一概率一年后还在亏、最惨腰斩到只剩零头。

**三条必须打折的地方：**

1. **独立样本只有 5 个。** 414 个红带日聚成 5 轮周期底（2015 / 2018-19 / 2020 /
   2022-23 / 2026），「100% 胜率」实际是「5 次全中」，不是几百次。
2. **这是区间不是买点。** 它说现在便宜，不说还会不会更便宜——2022-06 那段红带里
   买，半年后仍浮亏 23%，一年后才 +23%。
3. **4 年窗口是滚动的。** 通道会随着市场结构变化平移，今天的 −1σ 和 2015 年的
   −1σ 不是同一个绝对水平。

**口径**：指标 = CapMVRVCur − 1，{res['window_days']} 天滚动均值 ± 标准差。
数据 CoinMetrics community 档（免费免 key，2010-07 起日频，落后现实 1-2 天）。
报警由 `crypto/bottom_zone_alert.py` 每天跑，进出区间时推 Discord，冷却 2 天。

**定卖区阈值依据**（本地 `onchain_daily.parquet`，2014-12-30 ~ 2026-10-03，持有 1 年后收益）：

| 条件 | 占交易日 | 1 年后中位 | 胜率 |
|---|---|---|---|
| z ≥ +0.5 | 25.6% | −6% | 47% |
| z ≥ +0.75 | 18.5% | −6% | 47% |
| **z ≥ +1.0（定卖线）** | 12.9% | −1% | 50% |
| z ≥ +1.5 | 5.9% | −3% | 49% |
| z ≥ +2.0 | 2.1% | −25% | 36% |
| 任意一天 | 100% | +77% | 73% |

周期顶 z 值：2017-12-16 为 3.70，2021-11-08 为 1.41，2025-10-06 为 **0.99（没碰到 +1σ）**；+1σ 在 2025-07 碰过（$120,068）。顶部一轮比一轮低，这条线说的是「往后一年的预期收益没了」，不是「这就是顶」。
""")
