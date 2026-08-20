import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from api_client import fetch_close_series, fetch_core_data

st.set_page_config(page_title="价格台阶", layout="wide", page_icon="🪜")
st.title("🪜 价格台阶图")
st.caption("纵轴按固定涨跌幅划格，价格穿一格才走一步。横盘期间线是平的，一眼看出涨幅由哪几天贡献。")

with st.sidebar:
    if st.button("🔄 清除缓存"):
        fetch_core_data.clear()
        fetch_close_series.clear()
        st.rerun()

core = fetch_core_data()
groups = core.get("USER_GROUPS_DEF", {})
tic_map = core.get("TIC_MAP", {})
if not groups:
    st.warning("自选池为空，后端 stock_pool_data 没返回 USER_GROUPS_DEF。")
    st.stop()

c1, c2, c3, c4 = st.columns([1.1, 1.9, 1.6, 1])
with c1:
    group_names = ["全部"] + list(groups.keys())
    group = st.selectbox("分组", group_names)
with c2:
    if group == "全部":
        pool = sorted({t for lst in groups.values() for t in lst})
    else:
        pool = sorted(groups[group])
    labels = []
    for t in pool:
        cn = tic_map.get(t, "")
        labels.append(f"{t}  |  {cn}" if cn else t)
    picked = st.selectbox("标的", labels)
    ticker = picked.split("  |  ")[0].strip()
with c3:
    grid = st.slider("每格涨跌 %", min_value=0.5, max_value=50.0, value=10.0, step=0.5,
                     help="格子越小台阶越密。ETH 这类高波动标的建议 10-50，蓝筹建议 2-10")
with c4:
    years = st.selectbox("回看年数", [3, 5, 10, 15, 25], index=2)

px = fetch_close_series(ticker, years)
if px.empty or len(px) < 30:
    st.error(f"拿不到 {ticker} 的价格，或数据不足 30 天。")
    st.stop()


def to_steps(series: pd.Series, pct: float):
    """价格穿过上/下一格边界才换格，自带一格滞后，格子里怎么抖都不动。"""
    mult = 1.0 + pct / 100.0
    base = float(series.iloc[0])
    lv = 0
    levels, moves = [], []
    for ts, p in series.items():
        while p >= base * mult ** (lv + 1):
            lv += 1
            moves.append((ts, 1))
        while p <= base * mult ** (lv - 1):
            lv -= 1
            moves.append((ts, -1))
        levels.append(base * mult ** lv)
    return pd.Series(levels, index=series.index, dtype=float), moves


step, moves = to_steps(px, grid)
n_up = sum(1 for _, d in moves if d > 0)
n_dn = len(moves) - n_up
move_days = len({ts for ts, _ in moves})
seg = (step != step.shift()).cumsum()
plateau = step.groupby(seg).size()
longest = int(plateau.max()) if len(plateau) else 0

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("在走台阶的天数", f"{move_days} / {len(px)}", f"{move_days / len(px) * 100:.1f}% 的时间")
m2.metric("向上跳格", f"{n_up} 次")
m3.metric("向下跳格", f"{n_dn} 次")
m4.metric("净剩格数", f"{n_up - n_dn} 格", f"{(1 + grid / 100) ** (n_up - n_dn):.2f} 倍")
m5.metric("最长横盘", f"{longest} 天")

fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    row_heights=[0.82, 0.18], vertical_spacing=0.03)
fig.add_trace(go.Scatter(x=px.index, y=px.values, name="原始价格",
                         line=dict(color="#5c6577", width=1)), row=1, col=1)
fig.add_trace(go.Scatter(x=step.index, y=step.values, name=f"台阶（每格 {grid:g}%）",
                         line=dict(color="#4da3ff", width=2.4, shape="hv")), row=1, col=1)

# 格子边界线，太密就不画了，否则整张图糊成一片
levels = sorted(step.unique())
if len(levels) <= 30:
    for lv_price in levels:
        fig.add_hline(y=lv_price, line_color="#2b3242", line_width=1, row=1, col=1)

xs_up, ys_up, xs_dn, ys_dn = [], [], [], []
for ts, d in moves:
    # 必须转成原生 datetime，pandas Timestamp 过不了 plotly 的 JSON 序列化
    t = ts.to_pydatetime()
    # 上跳走上半格、下跳走下半格，密集时红绿才不会叠在一起糊成灰色
    if d > 0:
        xs_up += [t, t, None]
        ys_up += [0.52, 1, None]
    else:
        xs_dn += [t, t, None]
        ys_dn += [0, 0.48, None]
fig.add_trace(go.Scatter(x=xs_up, y=ys_up, mode="lines", name="向上跳格",
                         line=dict(color="#26c281", width=1.5), hoverinfo="x"), row=2, col=1)
fig.add_trace(go.Scatter(x=xs_dn, y=ys_dn, mode="lines", name="向下跳格",
                         line=dict(color="#e05a4a", width=1.5), hoverinfo="x"), row=2, col=1)

fig.update_layout(
    height=680, plot_bgcolor="#111", paper_bgcolor="#111",
    font=dict(color="#ddd", size=13), legend=dict(orientation="h", y=1.06),
    margin=dict(l=50, r=30, t=30, b=40), hovermode="x unified",
)
fig.update_yaxes(type="log", title="价格（对数坐标）", gridcolor="#222", row=1, col=1)
fig.update_yaxes(visible=False, range=[0, 1], row=2, col=1)
fig.update_xaxes(showgrid=False, row=1, col=1)
fig.update_xaxes(showgrid=False, tickformat="%Y-%m", row=2, col=1)
st.plotly_chart(fig, use_container_width=True)

with st.expander(f"全部 {len(moves)} 次跳格明细"):
    if moves:
        ret = px.pct_change()
        rows = []
        for ts, d in moves:
            rows.append({
                "日期": ts.strftime("%Y-%m-%d"),
                "方向": "上" if d > 0 else "下",
                "当日涨跌 %": round(float(ret.get(ts, 0.0)) * 100, 2),
                "收盘价": round(float(px.loc[ts]), 2),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(f"每格 {grid:g}% 太宽，这段时间一格都没穿过。调小格子试试。")
