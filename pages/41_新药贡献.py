"""新药贡献：大药企公司总收入同比拆成「新药增量 + 其余所有产品的变化」。
算法在后端 /api/v1/drug_revenue（valuation-radar/scripts/drug_revenue.py），本页只画图。
不给买卖判断：2026-11-16 回测，这个指标 2015 年以后对之后 12 个月的涨跌没有区分力。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_drug_revenue

st.set_page_config(page_title="新药贡献", layout="wide", page_icon="💊")
st.title("💊 新药贡献")
st.caption("公司总收入同比 = 新药的增量 + 其余所有产品的变化，三个数都除以一年前的公司总收入。绿柱盖得住红柱，新药才算帮公司打赢了。"
           "回测（2026-11-16，84 家药企）：总收入同比高的公司，2015 年以后并不比低的涨得好，所以这页只看图，不当买卖信号。")

with st.sidebar:
    years = st.selectbox("获批几年内算新药", [3, 5, 8], index=1)
    n_q = st.slider("显示几个季度", 8, 40, 20, step=4)
    if st.button("🔄 强制刷新"):
        fetch_drug_revenue.clear()
        st.rerun()

d = fetch_drug_revenue(int(years))
if not d.get("success"):
    st.error(f"后端没返回数据：{d.get('error')}")
    st.stop()
cos = [c for c in d["companies"] if not c.get("error") and c.get("latest")]
for c in d["companies"]:
    if c.get("error"):
        st.warning(f"{c['ticker']} {c['name']}：{c['error']}")
if not cos:
    st.stop()
st.caption(f"最新一份财报稿 {d['asof']} · 新药 = 最新一季季末往前 {d['years']} 年内 FDA 首次获批的药 · 每天 07:45 读新稿")

st.markdown("### 最新一季")
ov = pd.DataFrame([{"公司": f"{c['ticker']} {c['name']}", "季度": c["latest"]["q"],
                    "总收入同比%": c["latest"]["total_yoy"] * 100, "新药贡献%": c["latest"]["new"] * 100,
                    "其余贡献%": c["latest"]["rest"] * 100, "算作新药的": "、".join(c["cohort"]) or "没有"} for c in cos])
ov = ov.sort_values("新药贡献%", ascending=False)
pct = st.column_config.NumberColumn(format="%+.1f")
st.dataframe(ov, hide_index=True, width="stretch",
             column_config={"总收入同比%": pct, "新药贡献%": pct, "其余贡献%": pct})

st.markdown("### 单家公司")
by = {c["ticker"]: c for c in cos}
order = [s.split()[0] for s in ov["公司"]]
t = st.selectbox("公司", order, format_func=lambda x: f"{x} {by[x]['name']}")
co = by[t]
appr = {x["drug"]: x["approved"] for x in co["all_drugs"]}
opts = sorted(appr, key=lambda x: appr[x] or "0000", reverse=True)     # 获批日从新到旧，没对上的排最后
picked = st.multiselect("算作新药的（绿柱）", opts, default=co["default"], key=f"pick_{t}_{years}",
                        format_func=lambda x: f"{x}（{appr[x] or '没对上获批日'}）")
if sorted(picked) != co["default"]:
    r = fetch_drug_revenue(int(years), t, ",".join(sorted(picked)) or "-")
    if r.get("success") and not r["companies"][0].get("error"):
        co = r["companies"][0]
    else:
        st.error(f"重算失败：{r.get('error') or r['companies'][0].get('error')}")

rows = pd.DataFrame(co["rows"]).tail(int(n_q))
rows[["new", "rest", "total_yoy"]] = rows[["new", "rest", "total_yoy"]].astype(float)   # 缺的季度是 None，转成 NaN 才能比大小
fig = go.Figure()
fig.add_trace(go.Bar(x=rows["q"], y=rows["new"], name="新药增量", marker_color="#2ecc71"))
fig.add_trace(go.Bar(x=rows["q"], y=rows["rest"].where(rows["rest"] < 0), name="其余产品在跌", marker_color="#e74c3c"))
fig.add_trace(go.Bar(x=rows["q"], y=rows["rest"].where(rows["rest"] >= 0), name="其余产品在涨",
                     marker_color="rgba(231,76,60,0.35)"))
fig.add_trace(go.Scatter(x=rows["q"], y=rows["total_yoy"], name="公司总收入同比（= 柱子相加）", mode="lines+markers",
                         line=dict(color="#ddd", width=2), connectgaps=False))
fig.update_layout(barmode="relative", height=420, margin=dict(l=30, r=10, t=10, b=30),
                  yaxis=dict(tickformat="+.0%", zeroline=True, zerolinecolor="#888"),
                  xaxis=dict(type="category"), legend=dict(orientation="h", y=1.1))
st.plotly_chart(fig, width="stretch")
notes = [co["note"]] if co.get("note") else []
if co.get("n_gap"):
    notes.append(f"{co['n_gap']} 个季度没抽到数，图上留空")
if co.get("n_fixed"):
    notes.append(f"{co['n_fixed']} 个季度稿里的总收入和 Sharadar 对不上，用了 Sharadar 的")
if co.get("unmatched"):
    notes.append("没对上 FDA 获批日、按老产品算的：" + "、".join(co["unmatched"]))
if notes:
    st.caption("；".join(notes))

st.markdown(f"#### {co['last_q']} 每个产品比一年前多卖 / 少卖了多少（百万美元）")
tb = pd.DataFrame(co["table"])
tb["contrib"] = tb["contrib"] * 100
tb["is_new"] = tb["is_new"].map({True: "新药", False: ""})
tb = tb[["drug", "approved", "is_new", "cur", "prev", "chg", "contrib"]]
tb.columns = ["产品", "FDA 首次获批", "归类", "本季", "一年前", "变化", "占一年前公司收入%"]
st.dataframe(tb, hide_index=True, width="stretch", height=min(40 + 36 * len(tb), 700),
             column_config={"占一年前公司收入%": st.column_config.NumberColumn(format="%+.1f")})
st.caption("数字由 DeepSeek 从 8-K 财报稿的分产品收入表里抽，药名按第一个商品名归一（TRIKAFTA/KAFTRIO → TRIKAFTA）。"
           "收购来的药、获批前靠紧急授权卖的药，只要获批日在窗口内都算新药。疫苗和细胞疗法的获批日是手工表，新出的要手动加。")
