"""通胀利率：整体 / 核心 CPI 同比 + WTI 原油，联邦基金利率上限 + 2 年期美债。
数据在后端 /api/v1/macro/inflation_rates（macro_engine.compute_inflation_rates，FRED），本页只画图。
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from api_client import fetch_inflation_rates

st.set_page_config(page_title="通胀利率", layout="wide", page_icon="📈")
st.title("📈 通胀与利率")

_WINDOWS = {"2Y": 2, "5Y": 5, "10Y": 10}
with st.sidebar:
    win = st.radio("窗口", list(_WINDOWS), index=0, horizontal=True)
    if st.button("🔄 强制刷新"):
        st.cache_data.clear()
        st.rerun()

d = fetch_inflation_rates()
if not d.get("success"):
    st.error(f"后端没返回数据：{d.get('error')}")
    st.stop()
lt = d["latest"]
st.caption(f"FRED · CPI 截至 {lt['cpi_month']} · 原油 / 利率截至 {lt['week']}")


def _frame(block: dict) -> pd.DataFrame:
    df = pd.DataFrame(block)
    df.index = pd.to_datetime(df.pop("dates"))
    return df.astype(float)


start = pd.Timestamp.today() - pd.DateOffset(years=_WINDOWS[win])
cpi = _frame(d["cpi"]).loc[start:]
wk = _frame(d["weekly"]).loc[start:]
_layout = dict(height=420, xaxis_tickformat="%Y-%m", legend=dict(orientation="h", y=1.12),
               margin=dict(l=40, r=40, t=70, b=30), hovermode="x unified")

fig = make_subplots(specs=[[{"secondary_y": True}]])
for col, name, color in (("headline", "整体 CPI", "#e74c3c"), ("core", "核心 CPI", "#3498db")):
    s = cpi[col].dropna()
    fig.add_trace(go.Scatter(x=s.index, y=s, name=name, line=dict(color=color, width=2)), secondary_y=False)
s = wk["wti"].dropna()
fig.add_trace(go.Scatter(x=s.index, y=s, name="WTI", line=dict(color="#999", width=1.2), opacity=0.6),
              secondary_y=True)
fig.update_yaxes(title_text="同比 %", secondary_y=False)
fig.update_yaxes(title_text="美元/桶", secondary_y=True, showgrid=False)
fig.update_layout(title=f"通胀　整体 {lt['headline']:.2f}% · 核心 {lt['core']:.2f}% · WTI {lt['wti']:.0f}", **_layout)
st.plotly_chart(fig, width="stretch")
st.caption("核心 CPI 去掉食品和能源。整体和核心差得多，说明是油价在推。")

fig = go.Figure()
s = wk["fed_upper"].dropna()
fig.add_trace(go.Scatter(x=s.index, y=s, name="联邦基金利率上限", line=dict(color="#ddd", width=2, shape="hv")))
s = wk["dgs2"].dropna()
fig.add_trace(go.Scatter(x=s.index, y=s, name="2 年期美债", line=dict(color="#f39c12", width=2)))
fig.update_yaxes(title_text="%")
fig.update_layout(title=f"利率　基金上限 {lt['fed_upper']:.2f}% · 2 年期 {lt['dgs2']:.2f}%", **_layout)
st.plotly_chart(fig, width="stretch")
st.caption("2 年期在基金利率上方，市场在押继续加息。")
