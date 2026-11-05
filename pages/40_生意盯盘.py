"""生意盯盘：题库现役表的候选表（评分 + 10 年斜率 + Ulcer + PE 分位）和持仓的「跌破提示」。
算法在后端 /api/v1/macro/biz_watch（valuation-radar/scripts/biz_watch.py），本页只画图。
它不选股、不给买卖：价格规则触发后一年有六成概率反弹，所以触发只等于「去重答 11 题」。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_biz_watch

st.set_page_config(page_title="生意盯盘", layout="wide", page_icon="👀")
st.title("👀 生意盯盘")
st.caption("带鱼池 PIT 回测（2026-11-05）：评分 + 价格筛机械做成组合只有 8–10% CAGR，跑输 SPY；"
           "「5 年 Ulcer 穿 15 / 跌破 5 年线 / 回撤 20%」各种换出规则触发后一年都有六成反弹。"
           "所以这页不替你选，只做两件事：列候选、持仓跌破时提醒重答 11 题。换不换由生意决定，不由价格决定。")

with st.sidebar:
    holdings = st.text_input("持仓（逗号分隔）", value="V, WM")
    min_score = st.number_input("评分下限", value=14, step=1, min_value=0, max_value=22)
    min_slope = st.number_input("10 年斜率下限（年化 %）", value=8.0, step=1.0)
    top_n = st.number_input("候选取 Ulcer 最低几只", value=16, step=1, min_value=1)
    if st.button("🔄 强制刷新"):
        fetch_biz_watch.clear()
        st.rerun()

d = fetch_biz_watch(int(min_score), float(min_slope), int(top_n), holdings)
if not d.get("success"):
    st.error(f"后端没返回数据：{d.get('error')}")
    st.stop()
rule = d["rule"]
bench = d["bench"]
st.caption(f"数据截至 {d['asof']}（本地 Sharadar，每周日更新）· 现役表 {d['n_scored']} 只有评分 · "
           f"评分 ≥{rule['min_score']} 且 10 年斜率 ≥{rule['min_slope']}% 的 {d['n_cand']} 只按 10 年 Ulcer 排，前 {rule['top_n']} 进候选 · "
           f"SPY 近 10 年斜率 {bench['SPY']['slope10']}% / Ulcer {bench['SPY']['ulcer10']}")

st.markdown("### 持仓盯盘")
st.caption(f"三条线任一触发就该重答 11 题：跌破 5 年拟合线 {abs(rule['z_break'])} 个 std、距 5 年高点回撤 {abs(rule['dd_break']):.0f}%、"
           f"5 年 Ulcer > {rule['ulcer_break']:.0f}。另外每年 4 月 10-K 季后看一眼「评分还过线吗 / Ulcer 还在候选里吗」。")
cols = st.columns(max(len(d["holdings"]), 1))
for col, h in zip(cols, d["holdings"]):
    with col:
        if h.get("error"):
            st.warning(f"{h['ticker']}：{h['error']}")
            continue
        flags = h["flags"]
        st.markdown(f"#### {h['ticker']} · {h['name']}")
        if flags:
            st.error("触发：" + "；".join(flags) + " → 重答 11 题")
        else:
            st.success("三条线都没触发")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("评分", f"{h['score']:.0f}" if h.get("score") is not None else "-",
                  "过线" if h["score_ok"] else "掉线", delta_color="normal" if h["score_ok"] else "inverse")
        m2.metric("候选名次", f"#{h['rank']}" if h.get("rank") else "不在候选", "前 %d" % rule["top_n"] if h["in_top"] else None)
        m3.metric("对 5 年线", f"{h['z5']:+.1f} std", f"{h['dev5']:+.1f}%")
        m4.metric("距 5 年高点", f"{h['dd5']:.1f}%", f"5y Ulcer {h['ulcer5']}")
        v1, v2, v3 = st.columns(3)
        v1.metric("PE", f"{h['pe']}" if h.get("pe") else "-",
                  f"10 年 {h['pe_pct']:.0f}% 分位" if h.get("pe_pct") is not None else None, delta_color="off")
        v2.metric("FCF 收益率", f"{h['fcfy']}%" if h.get("fcfy") else "-")
        v3.metric("10 年斜率 / Ulcer", f"{h['slope10']}% / {h['ulcer10']}")
        c = h["chart"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=c["dates"], y=c["upper"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=c["dates"], y=c["lower"], fill="tonexty", fillcolor="rgba(79,195,232,0.12)",
                                 line=dict(width=0), name=f"±{abs(rule['z_break'])} std", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=c["dates"], y=c["fit"], name="5 年拟合线", line=dict(color="#f39c12", dash="dash", width=1.5)))
        fig.add_trace(go.Scatter(x=c["dates"], y=c["close"], name=h["ticker"], line=dict(color="#ddd", width=1.5)))
        fig.add_hline(y=c["dd_line"], line=dict(color="#e74c3c", dash="dot", width=1),
                      annotation_text=f"高点 {rule['dd_break']:.0f}%", annotation_position="bottom left")
        fig.update_layout(yaxis_type="log", height=320, margin=dict(l=30, r=10, t=10, b=30),
                          legend=dict(orientation="h", y=1.1), showlegend=True)
        st.plotly_chart(fig, width="stretch")
        with st.expander("题库里「什么能把它连根拔起」/「客户换掉它的代价」"):
            st.markdown(f"**Q10** {h.get('q10') or '-'}\n\n**Q2** {h.get('q2') or '-'}")

st.markdown("### 候选表")
df = pd.DataFrame(d["rows"])
cand = df[df["rank"].notna()].sort_values("rank")
show_all = st.checkbox(f"显示现役表全部 {len(df)} 只（含评分不够 / 斜率不够的）", value=False)
tbl = (df.sort_values(["rank", "ulcer10"], na_position="last") if show_all else cand).copy()
held = {h["ticker"] for h in d["holdings"]}
tbl["标记"] = [("持仓 " if t in held else "") + (f"手挑{g}" if g else "") for t, g in zip(tbl["ticker"], tbl["group"])]
tbl = tbl[["rank", "ticker", "name", "sector", "标记", "score", "verdict", "slope10", "ulcer10", "martin10", "mdd10",
           "slope5", "ulcer5", "dd5", "z5", "dev5", "pe", "pe_pct", "pe_med10", "fcfy"]]
tbl.columns = ["名次", "代码", "名称", "行业", "标记", "评分", "总评", "10年斜率%", "10年Ulcer", "10年Martin", "10年MDD%",
               "5年斜率%", "5年Ulcer", "距5年高点%", "对5年线(std)", "对5年线%", "PE", "PE 10年分位%", "PE 10年中位", "FCF收益率%"]
st.dataframe(tbl, hide_index=True, width="stretch", height=min(40 + 36 * len(tbl), 800))
st.caption("评分 = 题库机器总评（A=2 B=1 C=0，满分 22，拼合 > Opus > DeepSeek 取第一个答满的）。斜率 = 窗口内周线 log 价拟合直线换成复合年化，"
           "Ulcer = 每天离前高跌幅的均方根，股息按扣 10% 税再投。PE 按最新一季 SF1 用现价缩放，分位 = 现 PE 在自己近 10 年季度 PE 里的位置。"
           "名次只是 10 年 Ulcer 的顺序，不是推荐顺序——2016 池 PIT 回测里「Ulcer 最低」挑出来的是当时买贵的避险股。")
