import pandas as pd
import streamlit as st

from api_client import (
    IS_LOCAL_API,
    fetch_signal_summary,
    fetch_signal_theses,
    fetch_signal_thesis_detail,
    fetch_signal_trends,
)

st.set_page_config(page_title="新闻趋势跟踪", layout="wide")

st.title("📡 新闻趋势跟踪")
st.caption(
    "从联邦采购公告、SEC 8-K、联邦公报、全球新闻里抓可验证的变化，抽成带证伪条件的"
    "投资假设，再拿后续新材料检验它有没有在往趋势上走。数据来自 `data/signals.db`，"
    "每天北京时间 7:30 由 launchd 定时任务自动跑一轮采集+判定，这页只读，不会触发流水线。"
)
if not IS_LOCAL_API:
    st.warning("当前连的是 Render 远端，数据已停更，仅供历史参考。切本地后端才是最新数据。")

STATUS_EMOJI = {"active": "🟢", "weakened": "🟡", "paused": "⏸️",
                "closed": "⚫", "revived": "🔁"}
STATUS_CN = {"active": "活跃", "weakened": "转弱", "paused": "停滞",
             "closed": "已关闭", "revived": "复活"}
ROLE_CN = {"origin": "首发", "support": "支持", "weaken": "削弱",
           "disconfirm_met": "反证命中", "unclear": "不明"}
ROLE_BADGE = {"support": "🟢", "weaken": "🟠", "disconfirm_met": "🔴",
              "unclear": "⚪", "origin": "🔹"}
TYPE_EMOJI = {"新需求出现": "🆕", "买家行为改变": "🛒",
              "成本或能力跨过门槛": "📉", "供给或规则改变": "⚖️",
              "其他重要变化": "📌"}


def type_tags(t: dict) -> str:
    """一条假设的变化类型标签，可能有两个。"""
    tags = t.get("change_tags") or ([t["change_type"]] if t.get("change_type") else [])
    return " ".join(f"{TYPE_EMOJI.get(x, '')}{x}" for x in tags) or "—"

if st.button("🔄 刷新数据"):
    fetch_signal_summary.clear()
    fetch_signal_trends.clear()
    fetch_signal_theses.clear()
    fetch_signal_thesis_detail.clear()
    st.rerun()

summary = fetch_signal_summary()
if not summary.get("success"):
    st.error(f"汇总数据取不到：{summary.get('error')}")
    st.stop()

by_status = {r["status"]: r["n"] for r in summary["thesis_by_status"]}
total_thesis = sum(by_status.values())
n_followup_evidence = sum(
    r["n"] for r in summary["evidence_by_role"] if r["role"] != "origin")
n_indep_followup = sum(
    r["indep"] for r in summary["evidence_by_role"] if r["role"] != "origin")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("假设总数", total_thesis)
c2.metric("活跃", by_status.get("active", 0))
c3.metric("趋势组", summary["n_trends"])
c4.metric("后续证据", f"{n_followup_evidence} 条", help="不含首发信号本身，独立证据"
          f"（排除转载/跟进报道）{n_indep_followup} 条")
c5.metric("已判定配对数", summary["pairs_checked"], help="假设-新材料的候选配对，"
          "只要送过模型判过一次就计入，不论判定结果是不是相关")

type_counts = {r["change_type"]: r["n"] for r in summary["thesis_by_type"]}

st.markdown("**四类变化各有多少**")
st.caption("一条假设最多挂两个标签，所以这五个数加起来会比假设总数大。"
           "某一类长期是 0 说明采集那头压根没捞到这类材料，不是市场上没发生。")
tcols = st.columns(len(summary["thesis_by_type"]) or 1)
for col, r in zip(tcols, summary["thesis_by_type"]):
    col.metric(f"{TYPE_EMOJI.get(r['change_type'], '')} {r['change_type']}", r["n"])

with st.expander("按状态细分"):
    st.dataframe(pd.DataFrame(summary["thesis_by_status"]).rename(
        columns={"status": "状态", "n": "数量"}), hide_index=True, use_container_width=True)


def render_thesis_detail(t: dict | None) -> None:
    """假设详情：正文 + 涉及标的 + 确认/证伪条件 + 证据链 + 状态变更历史。"""
    if not t:
        st.warning("这条详情取不到。")
        return

    meta = (f"状态 `{STATUS_CN.get(t['status'], t['status'])}` ｜ "
            f"类型 {type_tags(t)} ｜ "
            f"重要度 {t.get('importance') or 0:.0f} ｜ "
            f"独立证据 {t.get('independent_evidence_n', 1)} 条 ｜ "
            f"发现于 {(t.get('discovered_at') or '')[:10]}")
    st.caption(meta)
    if t["status"] == "closed" and t.get("close_reason"):
        st.error(f"已关闭：{t['close_reason']}")
    elif t["status"] in ("weakened", "paused") and t.get("status_changed_at"):
        st.warning(f"{STATUS_CN[t['status']]}，变更于 {t['status_changed_at'][:10]}")

    st.markdown(f"**新事实**：{t.get('new_fact') or '—'}")
    if t.get("broader_pattern"):
        st.markdown(f"**更大的变化**：{t['broader_pattern']}")
    else:
        st.caption("这条假设看不出更大的图景——材料本身就是孤例，还是巧合，暂时无法判断。")
    if t.get("prior_view"):
        st.markdown(f"**挑战了什么已有认识**：{t['prior_view']}"
                    f"（依据：{t.get('prior_view_basis') or '未知'}）")

    assets = t.get("assets") or []
    if assets:
        st.markdown("**涉及标的**")
        st.dataframe(pd.DataFrame([{
            "标的": f"{a.get('name') or '未知'}（{a.get('ticker') or '无代码'}）",
            "关系": {"direct": "直接", "indirect": "间接"}.get(a.get("relation"), a.get("relation")),
            "涨跌%": a.get("ret_pct"),
            "超额%（vs SPY）": a.get("excess_vs_spy_pct"),
            "理由": a.get("why"),
        } for a in assets]), hide_index=True, use_container_width=True)
        if not any(a.get("ret_pct") is not None for a in assets):
            st.caption("价格反应暂未算出：事件日太近或落在未来（合同类信号的日期常取合同起始日），"
                       "跑几周后会自然补上。")

    conf, disc = t.get("confirm_signals") or [], t.get("disconfirm_signals") or []
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**如果成立，应该看到**")
        for x in conf:
            st.markdown(f"- {x}")
    with col2:
        st.markdown("**出现这些说明不成立**")
        for x in disc:
            st.markdown(f"- {x}")

    if t.get("unknowns"):
        with st.expander("材料没回答的问题"):
            for x in t["unknowns"]:
                st.markdown(f"- {x}")

    evidence = sorted(t.get("evidence") or [], key=lambda e: e.get("added_at") or "")
    followups = [e for e in evidence if e["role"] != "origin"]
    st.markdown(f"**证据链**（{len(followups)} 条后续证据）")
    if not followups:
        st.caption("还没有后续证据，只有触发这条假设的首发信号。")
    for e in evidence:
        badge = ROLE_BADGE.get(e["role"], "•")
        label = ROLE_CN.get(e["role"], e["role"])
        indep_tag = "" if e.get("independent") else "（转述/跟进报道，不计入独立证据）"
        st.markdown(f"{badge} **{label}**{indep_tag} · "
                    f"{(e.get('published_at') or '')[:10] or '日期未知'} · "
                    f"{e.get('source') or ''} · {e.get('title') or ''}")
        if e.get("which_claim"):
            st.caption(f"影响判断：{e['which_claim']}")
        if e.get("note"):
            st.caption(e["note"])

    changes = [u for u in (t.get("updates") or []) if u["verdict"] == "status_change"]
    if changes:
        with st.expander(f"状态变更历史（{len(changes)} 次）"):
            for u in changes:
                st.markdown(f"- {u['ts'][:19]}　{u['summary']}")


st.divider()
st.subheader("趋势分组")
st.caption("同一个更大的变化反复出现在不同主体身上才归成一组；只发生一次的独立事件在"
           "下面「按假设浏览」里。")
trends = fetch_signal_trends(min_theses=2)
if not trends.get("success"):
    st.error(f"趋势数据取不到：{trends.get('error')}")
elif not trends.get("data"):
    st.info("暂无满足条件的趋势组（同一变化至少要出现在 2 条独立假设上）。")
else:
    for tr in trends["data"]:
        head = (f"🔗 {tr['label']}　（{tr['n']} 条假设，{tr['n_active']} 条活跃，"
                f"最高重要度 {tr['top_importance']:.0f}）")
        with st.expander(head):
            for member in tr["theses"]:
                st.markdown(
                    f"{STATUS_EMOJI.get(member['status'], '•')} **{member['title']}**　"
                    f"重要度 {member['importance']:.0f} ｜ "
                    f"独立证据 {member['independent_evidence_n']} 条")
            picked = st.selectbox(
                "看某一条的详情", tr["theses"], format_func=lambda m: m["title"][:60],
                key=f"trend_pick_{tr['trend_id']}")
            if picked:
                st.divider()
                render_thesis_detail(
                    fetch_signal_thesis_detail(picked["thesis_id"]).get("data"))

st.divider()
st.subheader("按假设浏览")

all_statuses = sorted(by_status) or ["active"]
all_types = [r["change_type"] for r in summary["thesis_by_type"]]
with st.sidebar:
    st.markdown("### 新闻趋势筛选")
    picked_types = st.multiselect(
        "变化类型", all_types, default=all_types,
        format_func=lambda x: f"{TYPE_EMOJI.get(x, '')} {x}（{type_counts.get(x, 0)}）",
        help="一条假设最多挂两个标签，选中任意一个标签就会出现。")
    picked_statuses = st.multiselect(
        "状态", all_statuses, default=all_statuses,
        format_func=lambda s: f"{STATUS_EMOJI.get(s, '')} {STATUS_CN.get(s, s)}")
    orphan_only = st.checkbox(
        "只看孤立事件", value=False,
        help="broader_pattern 为空——材料本身看不出这是不是孤例，还没到能判断趋势的地步。")
    no_trend_only = st.checkbox("只看未归入任何趋势组", value=False,
                                 help="含孤立事件，也含已有更大图景但还没等到搭子的假设。")
    browse_limit = st.slider("最多显示条数", 10, 200, 60, step=10)

if not picked_types or not picked_statuses:
    st.info("变化类型或状态有一栏一个都没勾，这一栏按不筛选处理。")

theses_resp = fetch_signal_theses(
    status=",".join(picked_statuses), change_types=",".join(picked_types),
    orphan=orphan_only, no_trend=no_trend_only, limit=browse_limit)
if not theses_resp.get("success"):
    st.error(f"假设列表取不到：{theses_resp.get('error')}")
elif not theses_resp.get("data"):
    st.info("没有符合筛选条件的假设。")
else:
    rows = theses_resp["data"]
    st.caption(f"共 {len(rows)} 条")
    for t in rows:
        badge = STATUS_EMOJI.get(t["status"], "•")
        if t.get("trend_id"):
            group_tag = "🔗 已归趋势"
        elif not t.get("broader_pattern"):
            group_tag = "孤立事件"
        else:
            group_tag = "未归组"
        emo = "".join(TYPE_EMOJI.get(x, "") for x in (t.get("change_tags") or []))
        head = (f"{badge}{emo} {t['title'][:70]}　·　{group_tag}　·　"
                f"重要度 {(t.get('importance') or 0):.0f}")
        with st.expander(head):
            detail = fetch_signal_thesis_detail(t["thesis_id"])
            render_thesis_detail(detail.get("data"))
