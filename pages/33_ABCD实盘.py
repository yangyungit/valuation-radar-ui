"""ABCD 实盘：真实交易记录 + 份额法净值 + 再平衡建议。

账本存后端 SQLite（valuation-radar/data/portfolio.db），净值、均价、再平衡目标
全在后端 portfolio_book.py 算，这页只负责展示和录入。
"""

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import (
    IS_PROD_REMOTE,
    clear_portfolio_caches,
    delete_portfolio_cash_flow,
    delete_portfolio_trade,
    fetch_portfolio_ledger,
    fetch_portfolio_summary,
    post_portfolio_cash_flow,
    post_portfolio_trade,
)

st.set_page_config(page_title="ABCD 实盘", layout="wide", page_icon="📒")

st.title("📒 ABCD 实盘")
st.caption(
    "真实交易记录。净值按基金份额算：入金只加份额不算收益。"
    "ABC 的历史回测见『ABC投资组合』页。D 的操作依据见『BTC 周期 · D 策略』页。"
)

if IS_PROD_REMOTE:
    st.warning("实盘账本只在本机后端，连远端时只读且大概率拿不到数据")

with st.sidebar:
    if st.button("🔄 强制刷新"):
        clear_portfolio_caches()
        st.rerun()
    hide_amt = st.checkbox("隐藏金额", value=False)

SLEEVE_COLORS = {"A": "#4fc3e8", "B": "#5cb85c", "C": "#f39c12", "D": "#b04ec8", "现金": "#888"}


def money(v: float) -> str:
    return "***" if hide_amt else f"${v:,.0f}"


def entry_forms() -> None:
    tab_trade, tab_flow = st.tabs(["交易", "入金出金"])
    with tab_trade:
        with st.form("trade_form", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns(4)
            d = c1.date_input("日期", value=date.today())
            sleeve = c2.selectbox("仓位", ["A", "B", "C", "D"])
            ticker = c3.text_input("代码", placeholder="如 AAPL / 0700.HK / BTC-USD")
            side = c4.selectbox("类型", ["OPEN", "BUY", "SELL", "DIV"])
            c5, c6, c7, c8 = st.columns(4)
            qty = c5.number_input("数量", min_value=0.0, value=0.0, format="%.8f")
            price = c6.number_input(
                "价格", min_value=0.0, value=0.0, format="%.6f",
                help="本币单价；OPEN 填真实均价；DIV 填到账总额，数量填 0")
            fee = c7.number_input("手续费", min_value=0.0, value=0.0, format="%.4f")
            note = c8.text_input("备注")
            if st.form_submit_button("提交交易"):
                res = post_portfolio_trade({
                    "date": d.isoformat(), "sleeve": sleeve, "ticker": ticker,
                    "side": side, "qty": qty, "price": price, "fee": fee, "note": note,
                })
                if res.get("success"):
                    st.success("已记录")
                    st.rerun()
                else:
                    st.error(res.get("error", "未知错误"))
    with tab_flow:
        with st.form("flow_form", clear_on_submit=False):
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("日期", value=date.today(), key="flow_date")
            amount = c2.number_input("金额（USD，出金填负数）", value=0.0, format="%.2f")
            note = c3.text_input("备注", key="flow_note")
            if st.form_submit_button("提交出入金"):
                res = post_portfolio_cash_flow(
                    {"date": d.isoformat(), "amount": amount, "note": note})
                if res.get("success"):
                    st.success("已记录")
                    st.rerun()
                else:
                    st.error(res.get("error", "未知错误"))


def ledger_section() -> None:
    led = fetch_portfolio_ledger()
    if not led.get("success"):
        st.caption(f"拿不到流水：{led.get('error', '未知错误')}")
        return
    st.markdown("**交易流水**")
    trades = pd.DataFrame(led["trades"])
    st.dataframe(trades, width="stretch", hide_index=True)
    c1, c2, c3 = st.columns([1, 1, 4])
    tid = c1.number_input("要删除的 id", min_value=0, step=1, value=0, key="del_trade_id")
    if c2.button("删除交易"):
        res = delete_portfolio_trade(int(tid))
        if res.get("success"):
            st.rerun()
        else:
            st.error(res.get("error", "未知错误"))
    st.download_button("导出交易 CSV", trades.to_csv(index=False).encode("utf-8-sig"),
                       file_name="portfolio_trades.csv", mime="text/csv")

    st.markdown("**出入金流水**")
    flows = pd.DataFrame(led["cash_flows"])
    st.dataframe(flows, width="stretch", hide_index=True)
    c1, c2, c3 = st.columns([1, 1, 4])
    fid = c1.number_input("要删除的 id", min_value=0, step=1, value=0, key="del_flow_id")
    if c2.button("删除出入金"):
        res = delete_portfolio_cash_flow(int(fid))
        if res.get("success"):
            st.rerun()
        else:
            st.error(res.get("error", "未知错误"))
    st.download_button("导出出入金 CSV", flows.to_csv(index=False).encode("utf-8-sig"),
                       file_name="portfolio_cash_flows.csv", mime="text/csv")


summary = fetch_portfolio_summary()
if not summary.get("success"):
    st.error(f"⚠️ 后端拿不到账本数据：{summary.get('error', '未知错误')}")
    st.stop()

if summary.get("empty"):
    st.info("还没有记录。先在下方录入建仓快照：每个持仓选 OPEN，价格填真实均价；"
            "现金用『入金』录入同一天。")
else:
    # ---- 指标行 ----
    cols = st.columns(6)
    cols[0].metric("单位净值", f"{summary['nav']:.4f}")
    cols[1].metric("本周", f"{summary['ret_1w']:+.2%}")
    cols[2].metric("今年", f"{summary['ret_ytd']:+.2%}")
    cols[3].metric("起步以来", f"{summary['ret_total']:+.2%}",
                   f"SPY 同期 {summary['spy_ret_total']:+.2%}", "off")
    cols[4].metric("最大回撤", f"{summary['max_dd']:.2%}")
    if not hide_amt:
        cols[5].metric("总市值", money(summary["total_value"]))
    st.caption(f"起点 {summary['start']}　截至 {summary['as_of']}")

    # ---- 净值图 ----
    ser = summary["series"]
    idx = pd.to_datetime(ser["dates"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=idx, y=ser["nav"], name="单位净值",
                             line=dict(color="#4fc3e8", width=1.6)))
    fig.add_trace(go.Scatter(x=idx, y=ser["spy"], name="SPY（总收益）",
                             line=dict(color="#ddd", width=1.1, dash="dot")))
    fig.update_yaxes(gridcolor="#222")
    fig.update_xaxes(gridcolor="#222")
    fig.update_layout(height=380, margin=dict(l=60, r=20, t=30, b=30),
                      plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                      font=dict(color="#ccc"), hovermode="x unified",
                      legend=dict(orientation="h", y=1.1, x=0))
    st.plotly_chart(fig, width="stretch")

    # ---- 仓位配置与再平衡 ----
    st.markdown("### 仓位配置与再平衡")
    rows = []
    for s in summary["sleeves"]:
        row = {
            "仓位": s["sleeve"],
            "当前占比": f"{s['weight']:.1%}",
            "目标": f"{s['target']:.1%}",
            "偏离（百分点）": f"{s['diff_pp']:+.1f}",
        }
        if not hide_amt:
            row["建议买卖金额"] = f"${s['action_usd']:+,.0f}"
        row["状态"] = s["flag"]
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    wfig = go.Figure()
    for name, vals in ser["weights"].items():
        wfig.add_trace(go.Scatter(x=idx, y=vals, name=name, stackgroup="w",
                                  line=dict(width=0.5, color=SLEEVE_COLORS.get(name)),
                                  hovertemplate="%{y:.1%}"))
    wfig.update_yaxes(gridcolor="#222", tickformat=".0%", range=[0, 1])
    wfig.update_xaxes(gridcolor="#222")
    wfig.update_layout(height=300, margin=dict(l=60, r=20, t=30, b=30),
                       plot_bgcolor="#1a1a1a", paper_bgcolor="#1a1a1a",
                       font=dict(color="#ccc"), hovermode="x unified",
                       legend=dict(orientation="h", y=1.15, x=0))
    st.plotly_chart(wfig, width="stretch")
    st.caption("D 上限 15%，由 MVRV 规则加减；A/B/C 在其余资金里按 4:3:3；"
               "偏离超过 5 个百分点标『越线』。")

    # ---- 持仓明细 ----
    st.markdown("### 持仓明细")
    pos_rows = []
    for p in summary["positions"]:
        row = {
            "仓位": p["sleeve"], "代码": p["ticker"], "币种": p["ccy"],
            "数量": f"{p['qty']:,.6g}", "均价": f"{p['avg_cost']:,.2f}",
            "现价": f"{p['last_price']:,.2f}", "占总仓": f"{p['weight']:.1%}",
            "浮盈 %": f"{p['unrealized_pct']:+.1%}",
        }
        if not hide_amt:
            row["市值 USD"] = f"${p['value_usd']:,.0f}"
            row["浮盈 USD"] = f"${p['unrealized_usd']:+,.0f}"
            row["已实现 USD"] = f"${p['realized_usd']:+,.0f}"
        pos_rows.append(row)
    st.dataframe(pd.DataFrame(pos_rows), width="stretch", hide_index=True)
    for w in summary.get("warnings", []):
        st.warning(w)

    st.markdown("### 周报文本")
    st.code(summary["weekly_text"], language="markdown")

# ---- 录入 ----
if not IS_PROD_REMOTE:
    with st.expander("录入", expanded=bool(summary.get("empty", False))):
        entry_forms()
    with st.expander("流水与删除"):
        ledger_section()
