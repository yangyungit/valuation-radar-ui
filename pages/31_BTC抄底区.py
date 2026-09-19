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

from api_client import fetch_crypto_bottom_zone

st.set_page_config(page_title="BTC 抄底区", layout="wide", page_icon="₿")

ZONE_COLOR = "rgba(231,76,60,0.16)"
DEEP_COLOR = "rgba(192,57,43,0.34)"

st.title("₿ BTC 抄底区")
st.caption(
    "**浮盈 / 已实现市值**跌破 4 年滚动 −1σ 就进抄底区。已实现市值是全网按每枚币"
    "最后一次链上移动时的价格计的总成本，所以这个比值等于「全网浮盈相当于成本的几倍」，"
    "掉到低位说明平均持币人几乎不赚钱。**阈值是回测定的不是抄来的**，依据在页面底部。"
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
c1, c2, c3, c4 = st.columns(4)
c1.metric("当前状态", ["正常", "抄底区", "深度抄底区"][level])
c2.metric("浮盈/已实现市值", f"{res['ratio']:.2f}", f"−1σ 线 {res['lower']:.2f}", "off")
c3.metric("z 值", f"{res['z']:+.2f}", f"触发线 {res['zone_z']:+.1f}", "off")
c4.metric("BTC", f"${res['price']:,.0f}", f"数据截至 {res['as_of']}", "off")

(st.error if level == 2 else st.warning if level == 1 else st.info)(res["verdict"])
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
    for color, mask in ((ZONE_COLOR, lv == 1), (DEEP_COLOR, lv == 2)):
        for x0, x1 in segs(mask):
            fig.add_vrect(x0=x0, x1=x1, fillcolor=color, line_width=0,
                          layer="below", row=row, col=1)

fig.add_trace(go.Scatter(x=idx, y=s["price"], name="BTC 价格", line=dict(color="#ddd", width=1.2)),
              row=1, col=1)
fig.add_trace(go.Scatter(x=idx, y=s["ratio"], name="浮盈/已实现市值",
                         line=dict(color="#4fc3e8", width=1.3),
                         fill="tozeroy", fillcolor="rgba(79,195,232,0.18)"), row=2, col=1)
for key, label, color, dash in (("upper", "+1σ", "#5cb85c", "dot"),
                                ("mean", "4 年均值", "#b04ec8", "solid"),
                                ("lower", "−1σ（抄底线）", "#f39c12", "dash"),
                                ("deep", "−1.25σ（深度）", "#e74c3c", "dash")):
    fig.add_trace(go.Scatter(x=idx, y=s[key], name=label,
                             line=dict(color=color, width=1.1, dash=dash)), row=2, col=1)

fig.update_yaxes(title_text="BTC 价格（对数）", type="log", gridcolor="#222", row=1, col=1)
fig.update_yaxes(title_text="浮盈 / 已实现市值", gridcolor="#222", row=2, col=1)
fig.update_xaxes(gridcolor="#222", row=2, col=1)
fig.update_layout(height=660, margin=dict(l=60, r=20, t=30, b=30),
                  plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                  font=dict(color="#ccc"), hovermode="x unified",
                  legend=dict(orientation="h", y=1.06, x=0))
st.plotly_chart(fig, width="stretch")
st.caption("浅红 = 抄底区（z ≤ −1σ）　深红 = 深度抄底区（z ≤ −1.25σ）")

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

with st.expander("阈值怎么来的 / 这个信号能信到什么程度"):
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
""")
