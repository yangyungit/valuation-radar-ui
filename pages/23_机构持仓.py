import pandas as pd
import streamlit as st

from api_client import (
    fetch_congress_hot,
    fetch_congress_trades,
    fetch_h13f_consensus,
    fetch_h13f_curve,
    fetch_h13f_holdings,
    fetch_h13f_investors,
    fetch_h13f_leaderboard,
    fetch_h13f_meta,
    fetch_h13f_new_positions,
    fetch_h13f_ticker,
)

st.set_page_config(page_title="机构持仓", layout="wide")
st.title("🏛️ 机构持仓与国会交易")
st.caption(
    "**数据**：机构 13F 持仓，2013Q4–2026Q1 来自买断的 Sharadar SF3 底稿，"
    "2026Q2 起由 `fetch_13f_edgar.py` 直接从 SEC EDGAR 抓、申报当天可见。"
    "国会交易来自众议院书记官办公室的 Periodic Transaction Report。"
    "**13F 的边界**：只有美国上市证券的多头（含 TSM/ASML 这类 ADR），"
    "港股日股本地上市看不到，空头、债券、期货也没有，且法定滞后 45 天。"
    "**国会披露的边界**：只有金额区间，没有确切股数和成交价。"
)

meta = fetch_h13f_meta()
if not meta.get("success"):
    st.error(f"后端没连上：{meta.get('error')}")
    st.stop()

QUARTERS = meta["quarters"]
CATEGORIES = ["全部"] + meta["categories"]
GURUS = pd.DataFrame(meta["gurus"])
LABEL = dict(zip(GURUS.investorname, GURUS.label))

_MONEY = "${:,.0f}"


def _money(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:,.1f}{unit}"
    return _MONEY.format(v)


def _pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:,.1f}%"


with st.sidebar:
    quarter = st.selectbox("报告期", QUARTERS, index=0)
    category = st.selectbox("机构类别", CATEGORIES, index=0)
    curated = st.toggle(
        "只看策划名单（108 家）", value=True,
        help="关掉就不用名单，改用下面的规则从全部 8000 多家申报人里自己圈。",
    )
    if not curated:
        st.caption("规则筛：持仓越集中、规模越大，越像主动管理而不是指数基金。")
        n_lo, n_hi = st.slider("持仓只数区间", 1, 300, (5, 120))
        min_value_b = st.slider("规模下限（十亿美元）", 0.5, 50.0, 2.0, step=0.5)
    else:
        n_lo, n_hi, min_value_b = 5, 120, 2.0

    if quarter > meta["sf3_last_quarter"]:
        st.info(f"{quarter} 这期来自 EDGAR 实时抓取，只覆盖名单里的 108 家。", icon="📡")

    if st.button("🔄 清缓存重取"):
        for f in (fetch_h13f_meta, fetch_h13f_investors, fetch_h13f_holdings,
                  fetch_h13f_consensus, fetch_h13f_new_positions, fetch_h13f_ticker,
                  fetch_h13f_leaderboard, fetch_h13f_curve,
                  fetch_congress_trades, fetch_congress_hot):
            f.clear()
        st.rerun()

_cat = None if category == "全部" else category
_rule = dict(min_tickers=n_lo, max_tickers=n_hi, min_value=min_value_b * 1e9)

tab_new, tab_pool, tab_fund, tab_stock, tab_perf, tab_congress = st.tabs(
    ["🆕 新建仓", "🤝 共同持股池", "📋 单机构持仓", "🔍 单只票", "🏆 业绩排行", "🏛️ 国会交易"]
)

# ── 新建仓 ──────────────────────────────────────────────────────────
with tab_new:
    st.subheader(f"{quarter} 新建仓的票")
    st.caption("上一期没有、这一期有。同一只票被几家同时买进，比单家买进更值得看。")
    c1, c2, c3 = st.columns([1, 1, 2])
    min_new = c1.slider("至少几家新建仓", 1, 10, 2, key="new_min")
    only_unknown = c2.toggle(
        "只看陌生票", value=True,
        help="剔掉标普500、纳指100 和 ETF 锚池里已有的票，只留没进过你视野的。",
    )
    stocks_only_new = c3.toggle("排除 ETF / 优先股 / warrant", value=True, key="new_so")

    res = fetch_h13f_new_positions(
        quarter, min_new_holders=min_new, category=_cat, curated=curated,
        stocks_only=stocks_only_new, exclude_universe=only_unknown, **_rule,
    )
    if not res.get("success"):
        st.error(res.get("error"))
    else:
        rows = res["rows"]
        st.caption(
            f"机构 {res['n_investors']} 家"
            + (f"，已剔除 {res['n_excluded']} 只已知票" if only_unknown else "")
            + f"，命中 {len(rows)} 只"
        )
        if not rows:
            st.info("这个条件下没有新建仓，把「至少几家」调低试试。")
        else:
            df = pd.DataFrame(rows)
            df["买入方"] = df.buyers.map(lambda b: "、".join(LABEL.get(x, x) for x in b))
            show = df.rename(columns={
                "ticker": "代码", "name": "公司", "sector": "板块",
                "new_holders": "新建仓家数",
            })[["代码", "公司", "板块", "新建仓家数", "new_value", "买入方"]]
            show["建仓市值"] = df.new_value.map(_money)
            st.dataframe(show.drop(columns=["new_value"]), use_container_width=True,
                         hide_index=True, height=560)

# ── 共同持股池 ──────────────────────────────────────────────────────
with tab_pool:
    st.subheader(f"{quarter} 共同持股池")
    st.caption(
        "被多家集中型机构同时持有的票。调高门槛就是更严的粗筛——"
        "阈值给到 20 家时通常只剩一百多只，比标普 500 小得多。"
    )
    c1, c2 = st.columns([1, 3])
    min_holders = c1.slider("至少几家持有", 2, 60, 15, key="pool_min")
    stocks_only_pool = c2.toggle("排除 ETF / 优先股 / warrant", value=True, key="pool_so")

    res = fetch_h13f_consensus(quarter, min_holders=min_holders, category=_cat,
                               curated=curated, stocks_only=stocks_only_pool, **_rule)
    if not res.get("success"):
        st.error(res.get("error"))
    else:
        rows = res["rows"]
        st.metric(f"机构 {res['n_investors']} 家，池子大小", f"{len(rows)} 只",
                  delta="标普500 是 500 只", delta_color="off")
        if rows:
            df = pd.DataFrame(rows)
            df["主要持有方"] = df.top_holders.map(
                lambda b: "、".join(LABEL.get(x, x) for x in b))
            show = df.rename(columns={
                "ticker": "代码", "name": "公司", "sector": "板块", "holders": "持有家数",
            })[["代码", "公司", "板块", "持有家数", "主要持有方"]]
            show["合计市值"] = df.total_value.map(_money)
            st.dataframe(show, use_container_width=True, hide_index=True, height=560)
            st.download_button("下载这个池子（CSV）", df.to_csv(index=False).encode(),
                               f"consensus_{quarter}_{min_holders}家.csv", "text/csv")

# ── 单机构持仓 ──────────────────────────────────────────────────────
with tab_fund:
    res = fetch_h13f_investors(quarter, category=_cat, curated=curated, **_rule)
    inv = pd.DataFrame(res["rows"]) if res.get("success") else pd.DataFrame()
    if not res.get("success"):
        st.error(res.get("error"))
    elif inv.empty:
        st.info("这个条件下没有机构，放宽筛选试试。")
    else:
        inv["_opt"] = inv.apply(
            lambda r: f"{r.get('label') or r.investorname}（{int(r.n_tickers)} 只 / "
                      f"{_money(r.total_value)}）", axis=1)
        pick = st.selectbox("选机构", inv._opt.tolist(), index=0)
        who = inv.loc[inv._opt == pick, "investorname"].iloc[0]

        det = fetch_h13f_holdings(who, quarter)
        if not det.get("success"):
            st.error(det.get("error"))
        else:
            hold = pd.DataFrame(det["rows"])
            outs = pd.DataFrame(det["exits"])
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("持仓只数", len(hold))
            k2.metric("总市值", _money(hold.value.sum()) if len(hold) else "—")
            k3.metric("前十大占比",
                      _pct(hold.nlargest(10, "value").value.sum() / hold.value.sum())
                      if len(hold) else "—")
            k4.metric("本期清仓", f"{len(outs)} 只")
            st.caption(f"对比上一期：{det.get('prev_quarter') or '（无）'}")

            if len(hold):
                show = hold.rename(columns={
                    "ticker": "代码", "name": "公司", "sector": "板块",
                    "action": "动作", "units": "股数", "prev_units": "上期股数",
                })
                show["权重"] = hold.weight.map(_pct)
                show["市值"] = hold.value.map(_money)
                cols = ["代码", "公司", "板块", "市值", "权重", "股数", "上期股数"]
                if "动作" in show:
                    cols.append("动作")
                st.dataframe(show[cols], use_container_width=True, hide_index=True,
                             height=460)
            if len(outs):
                st.markdown("**本期清仓**")
                outs["上期市值"] = outs.prev_value.map(_money)
                st.dataframe(
                    outs.rename(columns={"ticker": "代码", "name": "公司",
                                         "prev_units": "上期股数"})
                    [["代码", "公司", "上期市值", "上期股数"]],
                    use_container_width=True, hide_index=True)

# ── 单只票 ──────────────────────────────────────────────────────────
with tab_stock:
    tk = st.text_input("股票代码", value="GOOGL", key="h13f_tk").strip().upper()
    if tk:
        res = fetch_h13f_ticker(tk, quarter, curated=curated, category=_cat)
        if not res.get("success"):
            st.error(res.get("error"))
        else:
            owners = pd.DataFrame(res["owners"])
            hist = pd.DataFrame(res["history"])
            if owners.empty:
                st.info(f"{quarter} 没有名单内机构持有 {tk}。")
            else:
                k1, k2 = st.columns(2)
                k1.metric("持有机构", len(owners))
                k2.metric("合计市值", _money(owners.value.sum()))
                if not hist.empty:
                    st.markdown("**持有家数走势**（抱团在建还是在散）")
                    st.line_chart(hist.set_index("calendardate")[["holders"]],
                                  height=200)
                show = owners.rename(columns={
                    "label": "机构", "units": "股数", "prev_units": "上期股数",
                    "action": "动作",
                })
                show["市值"] = owners.value.map(_money)
                cols = ["机构", "市值", "股数", "上期股数"]
                if "动作" in show:
                    cols.append("动作")
                st.dataframe(show[cols], use_container_width=True, hide_index=True,
                             height=460)

# ── 业绩排行 ────────────────────────────────────────────────────────
with tab_perf:
    st.caption(
        "每期在 13F 申报截止日（季末 + 45 天）按持仓市值加权买入，持到下一期申报日"
        "再换一遍，这是照抄 13F 能跑到的最快节奏。**不是机构的真实收益**——"
        "13F 看不到空头、美国以外上市的股票和季度中间的进出，"
        "所以做空对冲多、海外仓位重的机构会被系统性低估。"
    )
    c1, c2 = st.columns([1, 3])
    years = c1.selectbox("回看年数", [3, 5, 10, 13], index=2)
    min_q = c2.slider("至少几期才进榜", 4, 40, 8,
                      help="期数太少的机构，收益基本靠运气，排名不可比。")

    res = fetch_h13f_leaderboard(years=years, min_quarters=min_q,
                                 category=_cat, curated=curated)
    lb = pd.DataFrame(res["rows"]) if res.get("success") and res["rows"] else pd.DataFrame()
    if not res.get("success"):
        st.error(res.get("error"))
    elif lb.empty:
        st.info("这个条件下没有机构进榜，把期数门槛调低试试。")
    else:
        beat = int((lb.excess > 0).sum())
        c1, c2 = st.columns(2)
        c1.metric("进榜机构", f"{len(lb)} 家")
        c2.metric("年化跑赢 SPY 的", f"{beat} 家",
                  delta=f"占 {beat / len(lb) * 100:.0f}%", delta_color="off")

        show = lb.rename(columns={
            "label": "机构", "category": "类别", "quarters": "期数",
            "start": "起", "end": "止",
        })[["机构", "类别", "期数", "起", "止"]].copy()
        for src, dst in (("cagr", "年化"), ("spy_cagr", "同期SPY"), ("excess", "超额"),
                         ("win_rate", "季度胜率"), ("worst", "最差单季"), ("cover", "价格覆盖")):
            show[dst] = lb[src].map(_pct)
        show["累计"] = lb.cum.map(lambda v: f"{v:.2f}x")
        st.dataframe(
            show[["机构", "类别", "期数", "年化", "同期SPY", "超额", "累计",
                  "季度胜率", "最差单季", "起", "止", "价格覆盖"]],
            use_container_width=True, hide_index=True, height=560)

        pick = st.selectbox("看谁的净值曲线", lb.investorname.tolist(),
                            format_func=lambda n: LABEL.get(n, n))
        cur = fetch_h13f_curve(pick, years=years)
        if cur.get("success") and cur["rows"]:
            g = pd.DataFrame(cur["rows"]).set_index("nq")
            st.line_chart(g[["nav", "spy_nav"]].rename(
                columns={"nav": LABEL.get(pick, pick), "spy_nav": "SPY"}))
            st.caption("净值从回看区间第一期的申报日起算，两条线同起点。")

# ── 国会交易 ────────────────────────────────────────────────────────
with tab_congress:
    st.caption(
        "众议员本人及配偶子女的股票买卖。`owner` 列：SP=配偶、DC=子女、JT=夫妻共有、"
        "空=议员本人。法定 45 天内申报，实际常常几天就报，比 13F 快得多；"
        "代价是只有金额区间，没有确切股数。参议院的披露另有一套系统，暂未接。"
    )
    c1, c2, c3 = st.columns(3)
    days = c1.slider("回溯天数", 30, 720, 120, step=30)
    min_members = c2.slider("至少几人交易", 1, 8, 2)
    who = c3.text_input("按议员姓名过滤（英文，可留空）", value="")

    hot = fetch_congress_hot(days=days, min_members=min_members)
    if hot.get("success") and hot["rows"]:
        st.markdown(f"**最近 {days} 天多人交易的票**")
        h = pd.DataFrame(hot["rows"]).rename(columns={
            "ticker": "代码", "buyers": "买入人数", "sellers": "卖出人数",
            "last_trade": "最近交易日", "members": "涉及议员",
        })
        h["买入金额上限"] = pd.DataFrame(hot["rows"]).buy_amount_max.map(_money)
        st.dataframe(h[["代码", "买入人数", "卖出人数", "买入金额上限", "最近交易日",
                        "涉及议员"]],
                     use_container_width=True, hide_index=True, height=320)

    tr = fetch_congress_trades(days=days, member=who or None)
    if tr.get("success") and tr["rows"]:
        st.markdown("**逐笔明细**")
        t = pd.DataFrame(tr["rows"])
        t["金额区间"] = t.apply(
            lambda r: f"{_money(r.amount_low)} – {_money(r.amount_high)}", axis=1)
        show = t.rename(columns={
            "member": "议员", "state_dst": "选区", "owner": "持有人", "ticker": "代码",
            "tx_type": "方向", "tx_date": "交易日", "filed_date": "申报日",
            "description": "备注",
        })[["议员", "选区", "持有人", "代码", "方向", "交易日", "申报日", "金额区间",
            "备注"]]
        st.dataframe(show, use_container_width=True, hide_index=True, height=520)
    elif tr.get("success"):
        st.info("这个条件下没有记录。")
    else:
        st.error(tr.get("error"))
