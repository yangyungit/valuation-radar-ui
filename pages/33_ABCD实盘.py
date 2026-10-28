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
    delete_portfolio_thesis,
    delete_portfolio_trade,
    fetch_portfolio_ledger,
    fetch_portfolio_summary,
    fetch_portfolio_thesis,
    fetch_portfolio_watch,
    post_portfolio_cash_flow,
    post_portfolio_trade,
    put_portfolio_thesis,
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
            c1, c2, c3, c4, c9 = st.columns(5)
            d = c1.date_input("日期", value=date.today())
            sleeve = c2.selectbox("仓位", ["A", "B", "C", "D"])
            ticker = c3.text_input("代码", placeholder="如 AAPL / 0700.HK / BTC-USD")
            side = c4.selectbox("类型", ["OPEN", "BUY", "SELL", "DIV"])
            broker = c9.selectbox("券商", ["IBKR", "嘉信"])
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
                    "broker": broker,
                })
                if res.get("success"):
                    st.success("已记录")
                    st.rerun()
                else:
                    st.error(res.get("error", "未知错误"))
    with tab_flow:
        with st.form("flow_form", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns(4)
            d = c1.date_input("日期", value=date.today(), key="flow_date")
            amount = c2.number_input("金额（USD，出金填负数）", value=0.0, format="%.2f",
                                     help="券商间划转记两笔：转出方负数、转入方正数")
            broker = c3.selectbox("券商", ["IBKR", "嘉信"], key="flow_broker")
            note = c4.text_input("备注", key="flow_note")
            if st.form_submit_button("提交出入金"):
                res = post_portfolio_cash_flow(
                    {"date": d.isoformat(), "amount": amount, "note": note, "broker": broker})
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


def thesis_form(tk: str, card: dict | None, labels: dict) -> None:
    card = card or {"tailwind": "", "break_when": "", "probes": [], "dl_refs": "", "news_terms": ""}
    with st.form(f"thesis_{tk}"):
        tail = st.text_area("顺风是什么", card["tailwind"], key=f"tw_{tk}")
        brk = st.text_area("什么时候坏", card["break_when"], key=f"bw_{tk}")
        dl = st.text_input("决策日志编号（逗号分隔）", card["dl_refs"], key=f"dl_{tk}")
        terms = st.text_input("盯盘关键词（逗号分隔，空 = 不盯）", card.get("news_terms", ""), key=f"nt_{tk}")
        st.caption("探针：每行一个，格式 `metric,op,threshold,label`，metric 取下方词表")
        st.caption(" · ".join(f"`{k}` {v}" for k, v in labels.items()))
        raw = "\n".join(f"{p['metric']},{p['op']},{p['threshold']:g},{p['label']}" for p in card["probes"])
        txt = st.text_area("看哪个数", raw, key=f"pr_{tk}", height=110)
        c1, c2 = st.columns([1, 5])
        if c1.form_submit_button("保存"):
            probes = []
            try:
                for line in txt.splitlines():
                    parts = [s.strip() for s in line.split(",", 3)]
                    if len(parts) == 4 and parts[0]:
                        probes.append({"metric": parts[0], "op": parts[1],
                                       "threshold": float(parts[2]), "label": parts[3]})
            except ValueError:
                st.error("阈值不是数字")
            else:
                res = put_portfolio_thesis(tk, {"tailwind": tail, "break_when": brk,
                                                "probes": probes, "dl_refs": dl, "news_terms": terms})
                if res.get("success"):
                    st.rerun()
                else:
                    st.error(res.get("error", "未知错误"))
        if c2.form_submit_button("删卡"):
            res = delete_portfolio_thesis(tk)
            if res.get("success"):
                st.rerun()
            else:
                st.error(res.get("error", "未知错误"))


WATCH_STATUS = {
    "intact": "🟢 没碰理由", "watch": "🟡 有关但没坏", "threatened": "🔴 可能在坏",
    "no_new": "⚪ 没新材料", "no_card": "还没写卡", "error": "❌ 出错",
}
DEEP_VERDICT = {"broken": "理由被推翻", "weakened": "理由被削弱", "false_alarm": "虚惊"}


def _md(ts: str | None) -> str:
    return (ts or "")[5:10]


def watch_section() -> None:
    st.markdown("### 持仓盯盘")
    st.caption("每天北京 07:20 跑。DeepSeek 对照卡上「什么时候坏」读新 8-K 和新闻，自己决定下次搜什么；"
               "判 threatened 或探针新碰线才交给 Claude 联网核实，判理由被推翻 / 削弱才推 #choice。")
    w = fetch_portfolio_watch()
    if not w.get("success"):
        st.caption(f"拿不到盯盘记录：{w.get('error', '未知错误')}")
        return
    cost = w.get("cost_30d")
    st.caption(f"近 30 天模型花费 {'—' if cost is None else f'${cost:.2f}'}")
    tickers = w.get("tickers", [])
    if not tickers:
        st.caption("还没有运行记录")
        return
    st.dataframe(pd.DataFrame([{
        "代码": t["ticker"],
        "最近运行": f"{_md(t['last_run'])} {t['last_run'][11:16]}",
        "判断": WATCH_STATUS.get(t["status"], t["status"]),
        "新 8-K": t["n_filings"], "新标题": t["n_headlines"],
        "交给 Claude": "是" if t["escalated"] else "否",
        "卡外风险": t.get("novel_risk") or "—",
    } for t in tickers]), width="stretch", hide_index=True)

    runs, mats, deeps = w.get("runs", []), w.get("materials", []), w.get("deep", [])
    for t in tickers:
        tk = t["ticker"]
        tk_deep = [d for d in deeps if d["ticker"] == tk]
        with st.expander(f"{tk} 近 14 天", expanded=bool(tk_deep) or t["status"] == "threatened"):
            st.markdown("**它在搜什么**：" + (" · ".join(t.get("queries") or []) or "—"))
            tk_mats = [m for m in mats if m["ticker"] == tk][:30]
            st.markdown("**它读了什么**")
            if tk_mats:
                st.dataframe(pd.DataFrame([{
                    "日期": (m.get("published") or "")[:10],
                    "类型": "8-K" if m["kind"] == "8-K" else "新闻",
                    "标题": m.get("title") or m["ref"],
                    "链接": m.get("url") or None,
                } for m in tk_mats]), width="stretch", hide_index=True,
                    column_config={"链接": st.column_config.LinkColumn("链接", display_text="打开")})
            else:
                st.caption("没有")
            st.markdown("**它怎么判的**")
            for r in (r for r in runs if r["ticker"] == tk):
                why = "；".join(h.get("why_zh", "") for h in r.get("hits_json", []))
                st.markdown(f"- {_md(r['run_at'])} {WATCH_STATUS.get(r['status'], r['status'])}"
                            + (f" · {why}" if why else ""))
                if r.get("novel_risk"):
                    st.markdown(f"　卡外风险：{r['novel_risk']}（要加进卡请手动改上面的『什么时候坏』）")
            if tk_deep:
                st.markdown("**Claude 深判**")
            for d in tk_deep:
                st.markdown(f"- {_md(d['run_at'])} **{DEEP_VERDICT.get(d['verdict'], d['verdict'])}**"
                            f"{'　已推送' if d.get('pushed') else ''}：{d.get('summary_zh') or d.get('error') or ''}")
                for e in d.get("evidence_json", []):
                    st.markdown(f"　　- “{e.get('quote', '')}” — {e.get('source', '')}")
                if d.get("searches_json"):
                    st.caption("搜了：" + " · ".join(d["searches_json"]))


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
    st.caption("现金：" + " · ".join(f"{b} {money(v)}" for b, v in summary["cash_by_broker"].items()))

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
    rb = summary.get("rebalance") or {}
    if rb:
        {"now": st.error, "year_end": st.warning}.get(rb["level"], st.success)(rb["text"])
    al = summary.get("alarm") or {}
    if al.get("phase") in ("defend", "buyback"):
        stage = "守仓中（B、C 已清）" if al["phase"] == "defend" else f"买回中 第 {al['tranche']}/4 周"
        dd = f"{al['spy_dd']:.1%}" if al.get("spy_dd") is not None else "—"
        st.info(f"急跌报警 {al['alarm_date']}｜阶段：{stage}｜SPY 距一年高点 {dd}｜最晚 {al['deadline']} 回满仓")
    if al.get("weather_asof"):
        st.caption(f"报警来源：宏观天气（数据截至 {al['weather_asof']}）")
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
    st.caption("目标 A 35% / B 25% / C 25% / D 15%。D 越出 10%–20% 带 → 四腿立刻整体回目标；"
               "A/B/C 偏离超过 5 个百分点只标记，年末归位。D 带内的加减仍按 MVRV 规则。"
               "急跌模型寂静首峰报警 → 卖光 B、C；SPY 距一年高点回撤 ≥10% 后分 4 周买回，12 周没跌到直接买回。")

    # ---- 持仓明细 ----
    st.markdown("### 持仓明细")
    pos_rows = []
    for p in summary["positions"]:
        row = {
            "仓位": p["sleeve"], "券商": p["broker"], "代码": p["ticker"], "币种": p["ccy"],
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

    # ---- 论点卡 ----
    st.markdown("### 论点卡")
    st.caption("每只持仓三句话：顺风是什么 / 什么时候坏 / 看哪个数知道坏了。"
               "能从本地 Sharadar 算的数由后端盯，碰线标红；算不了的（capex 指引、综合成本率）靠人读财报。"
               "坏法写成带日期阈值的判断进中台决策日志，编号填在卡上。")
    th = fetch_portfolio_thesis()
    if not th.get("success"):
        st.caption(f"拿不到论点卡：{th.get('error', '未知错误')}")
    else:
        da = th.get("data_asof") or {}
        st.caption(f"探针数据截至：财报 {da.get('sf1', '—')} · 价格 {da.get('price', '—')}")
        cards = {c["ticker"]: c for c in th.get("cards", [])}
        held = list(dict.fromkeys(p["ticker"] for p in summary["positions"]))
        for tk in held + [t for t in cards if t not in held]:
            c = cards.get(tk)
            n_hit = sum(1 for p in (c or {}).get("probes", []) if p.get("breached"))
            tag = "　🔴 碰线 %d" % n_hit if n_hit else ("" if c else "　还没写卡")
            with st.expander(f"{tk}{tag}{'' if tk in held else '　（已不在持仓）'}", expanded=bool(n_hit)):
                if c:
                    st.markdown(f"**顺风**：{c['tailwind'] or '—'}")
                    st.markdown(f"**什么时候坏**：{c['break_when'] or '—'}")
                    if c.get("dl_refs"):
                        st.markdown(f"**决策日志**：{c['dl_refs']}")
                    st.markdown(f"**盯盘关键词**：{c.get('news_terms') or '不盯'}")
                    prow = [{
                        "看哪个数": p["label"], "指标": p["metric"],
                        "当前": "无数据" if p.get("value") is None else f"{p['value']:.1f}",
                        "阈值": f"{p['op']} {p['threshold']:g}",
                        "状态": "🔴 碰线" if p.get("breached") else ("—" if p.get("value") is None else "🟢"),
                        "数据截至": p.get("as_of") or "—",
                    } for p in c["probes"]]
                    if prow:
                        st.dataframe(pd.DataFrame(prow), width="stretch", hide_index=True)
                    st.caption(f"更新于 {c['updated_at'][:10]}")
                if not IS_PROD_REMOTE:
                    thesis_form(tk, c, th.get("metric_labels", {}))

    watch_section()

    st.markdown("### 周报文本")
    st.code(summary["weekly_text"], language="markdown")

# ---- 录入 ----
if not IS_PROD_REMOTE:
    with st.expander("录入", expanded=bool(summary.get("empty", False))):
        entry_forms()
    with st.expander("流水与删除"):
        ledger_section()
