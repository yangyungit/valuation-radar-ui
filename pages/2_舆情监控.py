import html as html_lib
import json
import time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from api_client import (
    trigger_narrative_pipeline,
    fetch_narrative_status,
    fetch_narrative_inbox,
    review_narrative_term,
    review_narrative_batch,
    fetch_orphan_stats,
    trigger_orphan_review,
    fetch_orphan_review_status,
    fetch_theme_proposals,
    approve_theme_proposal,
    reject_theme_proposal,
    fetch_match_log,
    fetch_tfidf_terms,
    fetch_corpus_stats,
    trigger_slow_clock,
    fetch_slow_clock_status,
    fetch_noise_words,
    fetch_quality_log,
    post_noise_word_add,
    post_noise_word_remove,
    trigger_generate_seed_proposals,
    fetch_dictionary_stats,
    fetch_taxonomy,
    fetch_taxonomy_full,
    post_dictionary_add,
    post_dictionary_remove,
    post_dictionary_batch_archive,
    post_dictionary_batch_restore,
    post_dictionary_batch_move,
    fetch_pending_inbox,
    fetch_uncategorized,
    migrate_uncategorized,
    propose_uncategorized,
    post_borderline_force_pass,
    post_borderline_mark_noise,
    fetch_term_trace,
    fetch_recently_promoted,
    fetch_new_terms,
    fetch_borderline_terms,
    fetch_l2_l3_detail,
    fetch_quadrant_history,
    post_dictionary_batch_delete,
    post_dictionary_batch_mark_noise,
    post_dictionary_rename_l2,
    post_dictionary_delete_l2,
    fetch_crawler_status,
    fetch_core_data,
    get_arena_d_factors,
    get_etf_rs20d,
    fetch_narrative_sector_heat,
    fetch_cio_watchlist,
    add_to_cio_watchlist,
    remove_from_cio_watchlist,
    update_cio_watchlist_notes,
    get_alpaca_ticker_news,
    get_ticker_cooccurrence,
    get_alpaca_snapshots,
)
from datetime import date as _date, timedelta as _timedelta
import math
import re as _re

st.set_page_config(page_title="叙事与舆情雷达", layout="wide")

# ---------------------------------------------------------------------------
# Phase color palette (shared by stepper + phase headers)
# ---------------------------------------------------------------------------
PHASE_COLORS = {
    1: "#3498DB",
    2: "#2ECC71",
    3: "#1ABC9C",
    4: "#9B59B6",
    5: "#F39C12",
    6: "#E74C3C",
}

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* ---- Pipeline Stepper ---- */
    .pipeline-stepper {
        display: flex; align-items: center; justify-content: center;
        gap: 0; margin: 10px 0 20px 0; padding: 12px 0;
    }
    .step-node {
        display: flex; align-items: center; gap: 8px;
        padding: 6px 14px; border-radius: 20px;
        background: rgba(255,255,255,0.04);
        white-space: nowrap;
    }
    .step-num {
        display: inline-flex; align-items: center; justify-content: center;
        width: 22px; height: 22px; border-radius: 50%;
        font-size: 13px; font-weight: 700; color: #0d1117;
    }
    .step-label { font-size: 13px; font-weight: 600; }
    .step-connector {
        width: 36px; height: 2px; flex-shrink: 0;
        background: linear-gradient(90deg, #333, #555, #333);
    }

    /* ---- Phase Header Card ---- */
    .phase-header {
        display: flex; align-items: center; gap: 14px;
        background: #0d1117; border-radius: 8px;
        padding: 14px 18px; margin-bottom: 16px;
        border-left: 4px solid #555;
    }
    .phase-badge {
        display: inline-flex; align-items: center; justify-content: center;
        width: 32px; height: 32px; border-radius: 50%;
        font-size: 15px; font-weight: 700; color: #0d1117; flex-shrink: 0;
    }
    .phase-info { flex: 1; }
    .phase-title { font-size: 17px; font-weight: 700; color: #e0e0e0; }
    .phase-desc  { font-size: 13px; color: #888; margin-top: 2px; }

    /* ---- Functional styles (preserved) ---- */
    .inbox-row {
        background-color: #1a1a1a; padding: 12px 16px;
        border-radius: 6px; margin-bottom: 8px;
        border-left: 3px solid #3498DB;
    }
    .inbox-term { font-size: 15px; font-weight: bold; color: #fff; }
    .inbox-meta { font-size: 13px; color: #aaa; margin-top: 4px; }
    .degraded-banner {
        background-color: rgba(241, 196, 15, 0.15);
        border-left: 4px solid #F1C40F;
        padding: 12px 16px; border-radius: 6px; margin-bottom: 16px;
        font-size: 14px; color: #F1C40F;
    }
    .pipeline-running {
        background-color: rgba(52, 152, 219, 0.15);
        border-left: 4px solid #3498DB;
        padding: 10px 16px; border-radius: 6px;
        font-size: 14px; color: #3498DB;
    }
    .prov-table { width: 100%; border-collapse: collapse; }
    .prov-table th {
        text-align: left; padding: 8px 10px; font-size: 13px;
        color: #888; border-bottom: 1px solid #333;
        position: sticky; top: 0; background: #0d1117;
    }
    .prov-table td {
        padding: 7px 10px; font-size: 13px; color: #ccc;
        border-bottom: 1px solid #1a1a1a; vertical-align: middle;
    }
    .prov-table tr:hover td { background: rgba(52,152,219,0.08); }
    .prov-badge {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 13px; font-weight: 600; margin-right: 4px;
    }
    .prov-arrow { color: #555; margin: 0 4px; font-size: 13px; }
    .prov-kw { color: #F39C12; font-weight: bold; font-size: 13px; }
    .prov-src { font-size: 13px; }
    .prov-headline a {
        color: #58a6ff; text-decoration: none; font-size: 13px;
    }
    .prov-headline a:hover { text-decoration: underline; }
    .prov-sentiment-pos { color: #2ECC71; font-weight: bold; }
    .prov-sentiment-neg { color: #E74C3C; font-weight: bold; }
    .prov-sentiment-neu { color: #888; }
    .prov-page-info { font-size: 13px; color: #888; margin-top: 8px; }
    .prov-freq {
        display: inline-block; min-width: 24px; text-align: center;
        padding: 2px 6px; border-radius: 4px; font-weight: 700;
        font-size: 13px;
    }
    .prov-freq-hot { background: rgba(231,76,60,0.18); color: #E74C3C; }
    .prov-freq-warm { background: rgba(243,156,18,0.18); color: #F39C12; }
    .prov-freq-cool { background: rgba(136,136,136,0.15); color: #aaa; }
    .prov-reason {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 13px; font-weight: 600;
    }
    .prov-reason-seed { background: rgba(52,152,219,0.18); color: #3498DB; }
    .prov-reason-auto { background: rgba(46,204,113,0.18); color: #2ECC71; }
    .prov-reason-manual { background: rgba(155,89,182,0.18); color: #9B59B6; }
    .prov-reason-bottomup { background: rgba(243,156,18,0.18); color: #F39C12; }
    .prov-reason-tfidf { background: rgba(26,188,156,0.18); color: #1ABC9C; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helper: render a unified phase-header card
# ---------------------------------------------------------------------------
def _phase_header(number: int, title: str, desc: str):
    c = PHASE_COLORS[number]
    st.markdown(
        f'<div class="phase-header" style="border-left-color:{c}">'
        f'<span class="phase-badge" style="background:{c}">{number}</span>'
        f'<div class="phase-info">'
        f'<div class="phase-title">{title}</div>'
        f'<div class="phase-desc">{desc}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def _render_slow_clock_summary(status: dict):
    """Display the last slow-clock run summary in the sidebar."""
    ts = (status.get("last_run") or "")[:19]
    err = status.get("last_error")
    if err:
        st.error(f"上次维护失败: {err[:120]}")
        return
    res = status.get("last_result") or {}
    parts = []
    if res.get("promoted"):
        parts.append(f"晋升 {res['promoted']}")
    if res.get("dormanted"):
        parts.append(f"休眠 {res['dormanted']}")
    if res.get("archived"):
        parts.append(f"归档 {res['archived']}")
    if res.get("frozen_l2s"):
        parts.append(f"冻结L2 {res['frozen_l2s']}")
    if res.get("noise_rejected"):
        parts.append(f"噪声剔除 {res['noise_rejected']}")
    if res.get("expired_zombies"):
        parts.append(f"僵尸过期 {res['expired_zombies']}")
    if res.get("uncat_migrated"):
        parts.append(f"未分类归入 {res['uncat_migrated']}")
    summary = " · ".join(parts) if parts else "无变更"
    st.caption(f"上次维护: {ts}｜{summary}")


# ---------------------------------------------------------------------------
# Page title
# ---------------------------------------------------------------------------
st.title("📡 叙事与舆情雷达 (Narrative & Sentiment Radar)")
st.caption("NLP 驱动的双因子共振引擎 — 捕获 \"高价格动量 + 高舆情爆发\" 的大象起舞级交易机会")

# ---------------------------------------------------------------------------
# Pipeline Stepper (visual workflow indicator)
# ---------------------------------------------------------------------------
_steps = [
    (1, "信号溯源"),
    (2, "发现与归类"),
    (3, "词汇热力"),
    (4, "词典管理"),
    (5, "叙事雷达"),
    (6, "共振猎场"),
]
stepper_nodes = []
for idx, (num, label) in enumerate(_steps):
    c = PHASE_COLORS[num]
    stepper_nodes.append(
        f'<div class="step-node">'
        f'<span class="step-num" style="background:{c}">{num}</span>'
        f'<span class="step-label" style="color:{c}">{label}</span>'
        f'</div>'
    )
    if idx < len(_steps) - 1:
        stepper_nodes.append('<div class="step-connector"></div>')

st.markdown(
    '<div class="pipeline-stepper">' + "".join(stepper_nodes) + '</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: controls
# ---------------------------------------------------------------------------
with st.sidebar:
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.rerun()

    # --- Global: NLP Pipeline ---
    st.divider()
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin:8px 0">'
        '<span style="font-size:14px;font-weight:700;color:#ccc">⚙️ 全局 · NLP 流水线</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    status = fetch_narrative_status()
    currently_running = status.get("running", False)
    prev_running = st.session_state.get("_pipeline_was_running", False)

    if prev_running and not currently_running:
        st.session_state["_pipeline_was_running"] = False
        st.cache_data.clear()
        st.rerun()

    if currently_running:
        st.session_state["_pipeline_was_running"] = True
        st.markdown('<div class="pipeline-running">⏳ 流水线正在运行中，每 5 秒自动刷新…</div>',
                    unsafe_allow_html=True)
        time.sleep(5)
        st.rerun()
    elif status.get("last_run"):
        last_summary = status.get("last_summary") or {}
        news_count = last_summary.get("news_count", -1)
        if news_count == 0 or status.get("last_warning"):
            st.warning(f"上次运行: {status['last_run'][:19]}（⚠️ 语料为空）")
            st.caption(status.get("last_warning") or "语料为空，建议重跑或检查网络")
        else:
            count_label = f"｜语料 {news_count} 篇" if news_count > 0 else ""
            st.success(f"上次运行: {status['last_run'][:19]}{count_label}")
    else:
        st.info("尚未运行过 NLP 流水线")

    if status.get("last_error"):
        st.error(f"上次错误: {status['last_error'][:100]}")

    if st.button("🚀 触发 NLP 流水线", disabled=currently_running):
        result = trigger_narrative_pipeline()
        if result.get("status") == "started":
            st.session_state["_pipeline_was_running"] = True
            st.success("流水线已在后台启动，页面将自动轮询直到完成后刷新视图。")
        else:
            st.warning(result.get("message", "未知状态"))
        st.rerun()

    st.divider()

    orphan_stats = fetch_orphan_stats()
    orphan_count = orphan_stats.get("total_orphans", 0)
    orphan_top = orphan_stats.get("top_terms", [])
    tfidf_overlap = orphan_stats.get("tfidf_overlap_count", 0)
    if orphan_count > 0:
        st.metric("🏚️ 孤儿词总数", orphan_count)
        if tfidf_overlap > 0:
            st.caption(f"其中 {tfidf_overlap} 个已被 TF-IDF 通道追踪（去重后不再重复处理）")
        if orphan_top:
            parts = []
            for t in orphan_top[:3]:
                tag = " 🔵" if t.get("tfidf_overlap") else ""
                parts.append(f"{t['term']}({t['frequency']}){tag}")
            top_str = " · ".join(parts)
            st.caption(f"高频孤儿：{top_str}")
    else:
        st.info("孤儿院暂无词条")

    orphan_rv_status = fetch_orphan_review_status()
    orphan_running = orphan_rv_status.get("running", False)
    prev_orphan_running = st.session_state.get("_orphan_review_was_running", False)

    if prev_orphan_running and not orphan_running:
        st.session_state["_orphan_review_was_running"] = False
        st.cache_data.clear()
        last_err = orphan_rv_status.get("last_error")
        last_res = orphan_rv_status.get("last_result") or {}
        if last_err:
            st.error(f"巡检出错: {last_err[:120]}")
        else:
            proposed = last_res.get("proposed", 0)
            if proposed > 0:
                st.success(f"巡检完成！生成了 {proposed} 条新主题提案，请查看「主题发现」Tab。")
            else:
                st.info(last_res.get("message", "巡检完成，暂无新提案。"))
        st.rerun()

    if orphan_running:
        st.session_state["_orphan_review_was_running"] = True
        st.markdown(
            '<div class="pipeline-running">⏳ AI 孤儿巡检运行中，Gemini 正在分析集群…每 5 秒自动刷新</div>',
            unsafe_allow_html=True,
        )
        time.sleep(5)
        st.rerun()
    elif orphan_rv_status.get("last_run"):
        last_res = orphan_rv_status.get("last_result") or {}
        proposed = last_res.get("proposed", 0)
        ts = orphan_rv_status["last_run"][:19]
        if orphan_rv_status.get("last_error"):
            st.error(f"上次巡检失败: {orphan_rv_status['last_error'][:80]}")
        elif proposed > 0:
            st.success(f"上次巡检: {ts}｜生成 {proposed} 条提案")
        else:
            st.caption(f"上次巡检: {ts}｜{last_res.get('message', '无新提案')}")

    force_review = st.checkbox("⚡ 强制跑（跳过成熟门槛）", value=False, help="数据积累不足时可勾选此项强制触发，仅用于测试")
    if st.button("🔬 触发 AI 孤儿巡检", disabled=orphan_running):
        result = trigger_orphan_review(force=force_review)
        if result.get("status") == "started":
            st.session_state["_orphan_review_was_running"] = True
            st.success(result.get("message", "Gemini 巡检已在后台启动"))
        elif result.get("status") == "already_running":
            st.session_state["_orphan_review_was_running"] = True
            st.info("巡检已在运行中，请等待完成。")
        else:
            st.warning(result.get("message", "未知状态"))
        st.rerun()

    st.divider()

    corpus = fetch_corpus_stats()
    if not corpus.get("degraded"):
        st.metric("今日语料", f"{corpus.get('total_articles', 0):,} 篇")
        st.metric("TF-IDF 候选词", corpus.get("tfidf_candidates", 0))
        st.metric("TF-IDF 已晋升", corpus.get("tfidf_promoted", 0))

    sc_status = fetch_slow_clock_status()
    sc_running = sc_status.get("running", False)
    prev_sc_running = st.session_state.get("_slow_clock_was_running", False)

    if prev_sc_running and not sc_running:
        st.session_state["_slow_clock_was_running"] = False
        st.cache_data.clear()
        st.rerun()

    if sc_running:
        st.session_state["_slow_clock_was_running"] = True
        st.markdown(
            '<div class="pipeline-running">⏳ 慢时钟维护运行中…每 3 秒自动刷新</div>',
            unsafe_allow_html=True,
        )
        time.sleep(3)
        st.rerun()

    if st.button("⏱️ 运行慢时钟维护", disabled=sc_running):
        result = trigger_slow_clock()
        if result.get("status") == "started":
            st.session_state["_slow_clock_was_running"] = True
            st.rerun()
        elif result.get("status") == "already_running":
            st.session_state["_slow_clock_was_running"] = True
            st.rerun()
        else:
            st.warning(result.get("message", "未知状态"))

    if not sc_running and sc_status.get("last_run"):
        _render_slow_clock_summary(sc_status)

    # --- Crawler Daemon Health ---
    st.divider()
    st.markdown(
        '<div style="display:flex;align-items:center;gap:8px;margin:8px 0">'
        '<span style="font-size:14px;font-weight:700;color:#ccc">🕷️ 新闻爬虫守护进程</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    _craw = fetch_crawler_status()
    if _craw.get("running"):
        st.caption("✅ 守护进程运行中（Finnhub / Alpaca / Polygon 持续采集）")
    else:
        st.caption("⚠️ 守护进程未运行")

    _craw_sources = [
        ("Finnhub",     _craw.get("finnhub", {})),
        ("Alpaca",      _craw.get("alpaca", {})),
        ("Polygon.io",  _craw.get("polygon", {})),
    ]
    for _cname, _cinfo in _craw_sources:
        _c_last = _cinfo.get("last_fetch")
        _c_today = _cinfo.get("articles_today", 0)
        _c_err = _cinfo.get("last_error")
        if _c_err:
            _c_icon = "🔴"
            _c_detail = f"错误: {_c_err[:60]}"
        elif _c_last:
            _c_icon = "🟢"
            _c_detail = f"最后抓取 {_c_last[11:19]} ｜今日 {_c_today} 篇"
        else:
            _c_icon = "⚪"
            _c_detail = "尚未运行"
        st.markdown(
            f'<div style="font-size:13px;margin:2px 0">'
            f'{_c_icon} <b>{_cname}</b>：{_c_detail}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
SOURCE_LABEL = {
    "gdelt": "GDELT API",
    "gdelt_gkg": "GDELT GKG",
    "google_rss": "Google RSS",
    "finnhub_general": "Finnhub",
    "alpaca": "Alpaca",
    "polygon": "Polygon.io",
}
_SRC_BG = {
    "seed":       "rgba(52,152,219,0.18)",
    "approved":   "rgba(155,89,182,0.18)",
    "manual":     "rgba(155,89,182,0.18)",
    "bottom_up":  "rgba(243,156,18,0.18)",
    "tfidf_auto": "rgba(26,188,156,0.18)",
}
_SRC_FG = {
    "seed":       "#3498DB",
    "approved":   "#9B59B6",
    "manual":     "#9B59B6",
    "bottom_up":  "#F39C12",
    "tfidf_auto": "#1ABC9C",
}

NARRATIVE_SOURCE_DISPLAY = {
    "seed": "种子词",
    "approved": "人工审批",
    "manual": "人工审批",
    "bottom_up": "孤儿词提案",
    "tfidf_auto": "TF-IDF晋升",
}


def _narrative_source_label(raw) -> str:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return "—"
    key = str(raw).strip().lower()
    return NARRATIVE_SOURCE_DISPLAY.get(key, str(raw))


def _normalize_dict_source(src) -> str:
    s = (src or "seed").strip().lower()
    return "approved" if s == "manual" else s


# =========================================================================
# Top-level Tabs (unified workflow navigation)
# =========================================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📡 1 · 信号溯源",
    "💡 2 · 发现与归类",
    "🔍 3 · 词汇热力",
    "🗂️ 4 · 词典管理",
    "🎯 5 · 叙事雷达",
    "⚡ 6 · 共振猎场",
])


# =========================================================================
# Tab 1: NLP Signal Provenance Panel
# =========================================================================
with tab1:
    _phase_header(1, "NLP 信号溯源面板", "追踪每条新闻从采集到关键词匹配的全链路，支持按信息源、日期、关键词多维度筛选")

    prov_col1, prov_col2, prov_col3, prov_col4 = st.columns([1, 1, 1, 2])
    with prov_col1:
        prov_days = st.selectbox("回溯天数", [7, 14, 30, 60], index=0, key="prov_days")
    with prov_col2:
        prov_src = st.selectbox(
            "信息源",
            ["全部", "GDELT API", "GDELT GKG", "Google RSS", "Finnhub", "Alpaca", "Polygon.io"],
            index=0, key="prov_src",
        )
    with prov_col3:
        prov_page_size = st.selectbox("每页条数", [25, 50, 100], index=1, key="prov_ps")
    with prov_col4:
        prov_search = st.text_input("🔍 搜索关键词 / 标题", key="prov_search")

    _src_filter = ""
    _src_reverse = {v: k for k, v in SOURCE_LABEL.items()}
    if prov_src != "全部":
        _src_filter = _src_reverse.get(prov_src, "")

    if "prov_page" not in st.session_state:
        st.session_state["prov_page"] = 1

    log_resp = fetch_match_log(
        days=prov_days, source=_src_filter,
        search=prov_search, page=st.session_state["prov_page"],
        page_size=prov_page_size,
    )
    log_data = log_resp.get("data", [])
    log_total = log_resp.get("total", 0)

    if log_resp.get("degraded"):
        st.markdown(
            f'<div class="degraded-banner">⚠️ 溯源面板降级：{log_resp.get("error", "未知")}</div>',
            unsafe_allow_html=True,
        )

    if log_data:
        rows_html = []
        for row in log_data:
            l2_name = row.get("l2_sector", "") or "—"
            kw = row.get("matched_keyword", "")
            src_raw = row.get("news_source", "")
            src_label = SOURCE_LABEL.get(src_raw, src_raw or "—")
            headline = row.get("headline", "") or "—"
            url = row.get("article_url", "")
            sent = row.get("sentiment", 0.0) or 0.0
            m_date = row.get("match_date", "")

            if sent > 0.05:
                sent_cls = "prov-sentiment-pos"
                sent_txt = f"+{sent:.2f}"
            elif sent < -0.05:
                sent_cls = "prov-sentiment-neg"
                sent_txt = f"{sent:.2f}"
            else:
                sent_cls = "prov-sentiment-neu"
                sent_txt = f"{sent:.2f}"

            headline_display = headline[:80] + "…" if len(headline) > 80 else headline
            headline_cell = (
                f'<a href="{url}" target="_blank" title="{headline}">{headline_display}</a>'
                if url else headline_display
            )

            kw_src = (row.get("keyword_source") or "seed").lower()
            src_bg = _SRC_BG.get(kw_src, "rgba(100,100,100,0.15)")
            src_fg = _SRC_FG.get(kw_src, "#aaa")

            kw_badge = (
                f'<span style="background:rgba(255,255,255,0.07);color:#e0e0e0;'
                f'padding:2px 8px;border-radius:4px;font-size:13px;font-weight:600">{kw}</span>'
            )
            l2_badge = (
                f'<span style="background:rgba(255,255,255,0.07);color:#aaa;'
                f'padding:2px 8px;border-radius:4px;font-size:13px">{l2_name}</span>'
            )

            day_freq = row.get("day_freq", 0) or 0
            if day_freq >= 5:
                freq_cls = "prov-freq prov-freq-hot"
            elif day_freq >= 2:
                freq_cls = "prov-freq prov-freq-warm"
            else:
                freq_cls = "prov-freq prov-freq-cool"

            reason_map = {
                "seed":       ("种子词",     "prov-reason prov-reason-seed"),
                "approved":   ("人工审批",   "prov-reason prov-reason-manual"),
                "manual":     ("人工审批",   "prov-reason prov-reason-manual"),
                "bottom_up":  ("孤儿词提案", "prov-reason prov-reason-bottomup"),
                "tfidf_auto": ("TF-IDF晋升", "prov-reason prov-reason-tfidf"),
            }
            reason_label, reason_cls = reason_map.get(kw_src, (kw_src, "prov-reason prov-reason-seed"))

            rows_html.append(
                f"<tr>"
                f'<td style="color:#666;white-space:nowrap">{m_date}</td>'
                f"<td>{kw_badge}</td>"
                f'<td><span class="{freq_cls}">{day_freq}</span></td>'
                f"<td>{l2_badge}</td>"
                f'<td><span class="{reason_cls}">{reason_label}</span></td>'
                f'<td class="{sent_cls}">{sent_txt}</td>'
                f'<td class="prov-src">{src_label}</td>'
                f'<td class="prov-headline">{headline_cell}</td>'
                f"</tr>"
            )

        table_html = (
            '<div style="max-height:520px;overflow-y:auto;border:1px solid #222;border-radius:6px">'
            '<table class="prov-table">'
            "<thead><tr>"
            "<th>日期</th><th>关键词</th><th>词频</th><th>L2 子行业</th>"
            "<th>入库原因</th><th>情感</th><th>信息源</th><th>文章标题</th>"
            "</tr></thead><tbody>"
            + "\n".join(rows_html)
            + "</tbody></table></div>"
        )
        st.markdown(table_html, unsafe_allow_html=True)

        total_pages = max(1, (log_total + prov_page_size - 1) // prov_page_size)
        cur_page = st.session_state["prov_page"]

        pg_col1, pg_col2, pg_col3 = st.columns([1, 3, 1])
        with pg_col1:
            if st.button("⬅ 上一页", disabled=(cur_page <= 1), key="prov_prev"):
                st.session_state["prov_page"] = max(1, cur_page - 1)
                st.rerun()
        with pg_col2:
            st.markdown(
                f'<div class="prov-page-info" style="text-align:center">'
                f'第 {cur_page}/{total_pages} 页 · 共 {log_total} 条记录</div>',
                unsafe_allow_html=True,
            )
        with pg_col3:
            if st.button("下一页 ➡", disabled=(cur_page >= total_pages), key="prov_next"):
                st.session_state["prov_page"] = min(total_pages, cur_page + 1)
                st.rerun()
    else:
        st.info("暂无匹配日志。请先触发 NLP 流水线采集数据后刷新查看。")


# =========================================================================
# Tab 2: Orphanage & Bottom-Up Theme Discovery
# =========================================================================
with tab2:
    _phase_header(2, "主题发现与归类中心", "AI 巡检未归类高频词 → 聚类提案新赛道 → 待归类词统一收纳")

    dict_stats = fetch_dictionary_stats()
    # degraded（API 冷启动超时）时不误判为空；种子词典就位即视为已建库
    _dict_api_ok = not dict_stats.get("degraded", False)
    has_active_library = _dict_api_ok and (
        dict_stats.get("total_active_count", dict_stats.get("active_non_seed_count", 0)) > 0
    )

    if _dict_api_ok and not has_active_library:
        st.markdown("""
        <div style="background:#1a1a2e;border:2px solid #E67E22;border-radius:10px;
                    padding:22px 24px;margin-bottom:20px">
            <div style="font-size:18px;font-weight:bold;color:#E67E22;margin-bottom:8px">
                🚀 快速建库（首次启动）
            </div>
            <div style="font-size:14px;color:#ccc;margin-bottom:14px">
                检测到叙事词典为空。请先生成种子提案，然后一键批准以启动雷达。
            </div>
        </div>
        """, unsafe_allow_html=True)

        qb_col1, qb_col2, qb_col3 = st.columns([2, 2, 4])
        with qb_col1:
            if st.button("📦 生成种子提案", type="secondary"):
                gen_result = trigger_generate_seed_proposals()
                if gen_result.get("success"):
                    st.success(f"已生成 {gen_result.get('proposals_created', 0)} 条种子提案")
                else:
                    st.error(gen_result.get("error", "生成失败"))
                st.rerun()

    t2_sub1, t2_sub2 = st.tabs(["💡 新主题提案", "🧩 待归类中心"])

    # ---- Sub-tab 1: Theme Proposals (original Tab2 content) ----
    with t2_sub1:
        proposals_resp = fetch_theme_proposals(status="pending")
        proposals = proposals_resp.get("data", [])

        if proposals_resp.get("degraded"):
            st.markdown(
                f'<div class="degraded-banner">⚠️ 提案加载失败：{proposals_resp.get("error", "未知")}</div>',
                unsafe_allow_html=True,
            )

        if proposals:
            if not has_active_library and len(proposals) > 1:
                if st.button("✅ 一键全部建库", type="primary"):
                    ok_count = 0
                    for p in proposals:
                        r = approve_theme_proposal(p["id"])
                        if r.get("success"):
                            ok_count += 1
                    st.success(f"已批准 {ok_count}/{len(proposals)} 个种子主题，雷达词库已激活！")
                    st.rerun()

            st.markdown(f"### 💡 待审批新主题提案：{len(proposals)} 条")
            st.caption("系统通过孤儿词聚类 + Gemini AI 分析，识别出以下潜在新赛道，等待 CIO 拍板建库。")

            for prop in proposals:
                prop_id = prop["id"]
                terms_data = prop.get("terms_data", {})
                l2_display = terms_data.get("l2_display") or prop["proposed_l2"]
                all_terms = terms_data.get("terms", [])
                reasoning = prop.get("llm_reasoning", "")

                terms_preview = " · ".join(f"<code style='font-size:13px'>{t}</code>" for t in all_terms[:8])
                if len(all_terms) > 8:
                    terms_preview += f" <span style='color:#666;font-size:13px'>+{len(all_terms)-8} 个词</span>"

                st.markdown(f"""
                <div style="background:#111;border:1px solid #2ECC71;border-radius:8px;
                            padding:18px 20px;margin-bottom:12px">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
                        <span style="font-size:18px;font-weight:bold;color:#2ECC71">
                            📦 新建 L2: {l2_display}
                        </span>
                        <span style="color:#888;font-size:13px;margin-left:auto">
                            {prop.get('total_mentions',0)} 次提及 · {prop.get('days_active',0)} 天
                        </span>
                    </div>
                    <div style="margin-bottom:10px;font-size:13px;color:#aaa">
                        📝 {reasoning}
                    </div>
                    <div style="font-size:13px;color:#ddd">
                        🔑 集群词条：{terms_preview}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_l2_input, col_approve, col_reject = st.columns([3, 1, 1])
                with col_l2_input:
                    custom_l2 = st.text_input(
                        "L2 名称（可改）", value=l2_display,
                        key=f"l2_input_{prop_id}",
                        help="格式: Sector_Name，留空使用 AI 建议值",
                        label_visibility="collapsed",
                    )
                with col_approve:
                    if st.button("✅ 批准建库", key=f"approve_prop_{prop_id}", type="primary",
                                 use_container_width=True):
                        result = approve_theme_proposal(
                            prop_id,
                            l2_override=custom_l2 or None,
                        )
                        if result.get("success"):
                            st.success(f"已建库 {result.get('l2')}，导入 {result.get('terms_added')} 个词")
                        else:
                            st.error(result.get("error", "操作失败"))
                        st.rerun()
                with col_reject:
                    if st.button("❌ 驳回", key=f"reject_prop_{prop_id}",
                                 use_container_width=True):
                        result = reject_theme_proposal(prop_id)
                        if result.get("success"):
                            st.info("已驳回该提案")
                        else:
                            st.error(result.get("error", "操作失败"))
                        st.rerun()
        else:
            st.info("暂无待审批的新主题提案。如孤儿院已积累足量词条，点击侧边栏「🔬 触发 AI 孤儿巡检」生成提案。")

    # ---- Sub-tab 2: Unified Classification Center ----
    with t2_sub2:
        st.markdown(
            "<div style='padding:10px 14px;background:rgba(46,204,113,0.10);"
            "border-left:3px solid #2ECC71;border-radius:4px;margin-bottom:14px;"
            "font-size:14px;color:#ccc'>"
            "以下词条已通过质量门筛选，但系统无法确定其 L2 归属。"
            "「模糊竞争」词条请 CIO 手动选定 L2；「超时边界词」请强制通过或标噪。"
            "</div>",
            unsafe_allow_html=True,
        )

        # --- Section A: Ambiguous L2 (two candidates too close, CIO picks one) ---
        ambig_resp = fetch_pending_inbox(reason="ambiguous_l2")
        ambig_data = ambig_resp.get("data", [])
        ambig_total = ambig_resp.get("total", 0)

        # --- Section B: Stale borderline terms (from quality gate timeout) ---
        stale_bl_resp = fetch_borderline_terms(days=90, min_age_days=5)
        stale_bl_data = stale_bl_resp.get("data", [])

        combined_total = ambig_total + len(stale_bl_data)

        if ambig_resp.get("error"):
            st.warning(f"待归类数据加载失败: {ambig_resp.get('error', '')}")

        if combined_total == 0:
            st.success("当前无待归类词条，所有 L3 关键词已成功归类或裁决。")
        else:
            st.markdown(f"### 🧩 待归类词条总览：{combined_total} 个")

            # --- A: Ambiguous L2 — CIO picks from two candidates ---
            if ambig_total > 0:
                st.markdown(
                    f"<div style='padding:8px 14px;background:rgba(243,156,18,0.12);"
                    f"border-left:3px solid #F39C12;border-radius:4px;margin-bottom:12px;"
                    f"font-size:14px'>"
                    f"<b>模糊竞争待决策</b>：{ambig_total} 个词条通过 Gate1→2→3，"
                    f"但系统计算出两个 L2 得分非常接近，无法自动选定。请 CIO 手动指定归属。"
                    "</div>",
                    unsafe_allow_html=True,
                )

                # --- One-click batch: assign all to their best candidate ---
                batch_col1, batch_col2 = st.columns([2, 3])
                with batch_col1:
                    if st.button("⚡ 一键全部用最高分 L2 归类", key="btn_ambig_batch_best"):
                        ok_n = 0
                        for d in ambig_data:
                            cands = d.get("candidates") or {}
                            best_l2 = cands.get("best") or d.get("suggested_l2") or ""
                            if not best_l2:
                                continue
                            res = review_narrative_term(d["id"], "approve", l2_sector=best_l2)
                            if res.get("success"):
                                ok_n += 1
                        st.success(f"已批量归类 {ok_n}/{ambig_total} 个词条")
                        st.rerun()
                with batch_col2:
                    st.caption("每行也可独立选择，逐条拍板后点「确认归类」。")

                st.divider()

                # --- Per-term CIO decision ---
                all_l2_names_ambig = sorted(set(
                    item["l2"] for item in
                    (fetch_taxonomy_full().get("data") or [])
                ))

                for d in ambig_data:
                    cands = d.get("candidates") or {}
                    best_c = cands.get("best") or d.get("suggested_l2") or ""
                    best_sc = cands.get("best_score", 0.0)
                    runner_up = cands.get("runner_up") or ""
                    runner_sc = cands.get("runner_up_score", 0.0)

                    with st.container():
                        col_term, col_pick, col_btn = st.columns([3, 4, 2])
                        with col_term:
                            st.markdown(
                                f"<div style='padding:6px 0;font-size:14px;"
                                f"font-weight:600;color:#e0e0e0'>{d['term']}</div>"
                                f"<div style='font-size:13px;color:#888'>"
                                f"发现日: {d.get('discovered_date','—')} · "
                                f"频次: {d.get('frequency',0)}</div>",
                                unsafe_allow_html=True,
                            )
                        with col_pick:
                            candidate_hint = []
                            if best_c:
                                candidate_hint.append(f"{best_c} ({best_sc*100:.0f}%)")
                            if runner_up and runner_up != best_c:
                                candidate_hint.append(f"{runner_up} ({runner_sc*100:.0f}%)")
                            hint_text = " vs ".join(candidate_hint) if candidate_hint else "无候选"

                            default_opts = [x for x in [best_c, runner_up] if x]
                            extra_opts = [x for x in all_l2_names_ambig if x not in default_opts]
                            select_opts = default_opts + extra_opts

                            chosen = st.selectbox(
                                f"选择 L2（{hint_text}）",
                                options=select_opts,
                                index=0 if select_opts else None,
                                key=f"ambig_pick_{d['id']}",
                                label_visibility="collapsed",
                            )
                        with col_btn:
                            if st.button("确认归类", key=f"ambig_approve_{d['id']}",
                                         type="primary", use_container_width=True):
                                if chosen:
                                    res = review_narrative_term(d["id"], "approve", l2_sector=chosen)
                                    if res.get("success"):
                                        st.success(f"已归类到 {chosen}")
                                    else:
                                        st.error(res.get("error", "操作失败"))
                                    st.rerun()
                            if st.button("驳回", key=f"ambig_dismiss_{d['id']}",
                                         use_container_width=True):
                                res = review_narrative_term(d["id"], "dismiss")
                                if res.get("success"):
                                    st.info("已驳回")
                                st.rerun()

            # --- B: Stale borderline terms (from quality gate timeout) ---
            if stale_bl_data:
                st.divider()
                st.markdown(
                    f"<div style='padding:8px 14px;background:rgba(91,141,239,0.12);"
                    f"border-left:3px solid #5B8DEF;border-radius:4px;margin-bottom:12px;"
                    f"font-size:14px'>"
                    f"<b>边界词-超时流转</b>：{len(stale_bl_data)} 个词条在质检阶段滞留超过 5 天，"
                    f"自动流转至此等待归类。</div>",
                    unsafe_allow_html=True,
                )
                sbl_rows = []
                for bl in stale_bl_data:
                    sbl_rows.append({
                        "词条": bl["term"],
                        "最后检测日": bl.get("check_date", ""),
                        "爆发系数": round(bl.get("burst_ratio", 0) or 0, 2),
                        "共现度": round(bl.get("cooc_degree", 0) or 0, 3),
                        "文档数": bl.get("doc_count", 0) or 0,
                        "连续天数": bl.get("consecutive", 0) or 0,
                    })
                st.dataframe(pd.DataFrame(sbl_rows), use_container_width=True, hide_index=True)

                sbl_col1, sbl_col2 = st.columns(2)
                with sbl_col1:
                    if st.button("✅ 全部强制通过", key="btn_stale_bl_pass_all"):
                        ok = 0
                        for bl in stale_bl_data:
                            res = post_borderline_force_pass(bl["term"])
                            if res.get("ok"):
                                ok += 1
                        st.success(f"已强制通过 {ok}/{len(stale_bl_data)} 个边界词")
                        st.rerun()
                with sbl_col2:
                    if st.button("🚫 全部标为噪音", key="btn_stale_bl_noise_all"):
                        ok = 0
                        for bl in stale_bl_data:
                            res = post_borderline_mark_noise(bl["term"])
                            if res.get("ok"):
                                ok += 1
                        st.success(f"已标噪 {ok}/{len(stale_bl_data)} 个边界词")
                        st.rerun()


# =========================================================================
# Tab 3: TF-IDF Bottom-Up Discovery + Quality Inspector
# =========================================================================
with tab3:
    _phase_header(3, "词汇热力发现（TF-IDF 自底向上）", "标题语料 TF-IDF 挖掘高频新词，质检员自动过滤噪音，CIO 可手动管理噪音词表")

    v3_sub1, v3_sub2, v3_sub3 = st.tabs(["📊 TF-IDF 信号词", "📋 质检日志", "🆕 今日新发现"])

    # ----- Sub-tab: TF-IDF Signal Words -----
    with v3_sub1:
        tfidf_col1, tfidf_col2 = st.columns([1, 1])
        with tfidf_col1:
            tfidf_days = st.selectbox("回溯天数", [3, 7, 14, 30], index=1, key="tfidf_days")
        with tfidf_col2:
            tfidf_topk = st.selectbox("显示条数上限", [50, 100, 300, 500], index=2, key="tfidf_topk")

        corpus_resp = fetch_corpus_stats()
        if not corpus_resp.get("degraded"):
            c1, c2, c3 = st.columns(3)
            c1.metric("今日语料总量", f"{corpus_resp.get('total_articles', 0):,} 篇")
            c2.metric("TF-IDF 候选词", f"{corpus_resp.get('tfidf_candidates', 0):,}")
            c3.metric("TF-IDF 已晋升", f"{corpus_resp.get('tfidf_promoted', 0):,}")
        else:
            st.markdown(
                "<div class='degraded-banner'>⚠️ 语料库统计暂不可用，请确认后端流水线已运行。</div>",
                unsafe_allow_html=True,
            )

        tfidf_resp = fetch_tfidf_terms(days=tfidf_days, top_k=tfidf_topk)
        tfidf_data = tfidf_resp.get("data", [])
        quality_filtered = tfidf_resp.get("quality_filtered", False)
        gate3_available = tfidf_resp.get("gate3_available", False)
        if tfidf_resp.get("degraded"):
            st.warning(f"TF-IDF 数据拉取失败: {tfidf_resp.get('error', '未知错误')}")
        elif gate3_available and not tfidf_data:
            st.info("本日无高质量信号词（所有候选词均未通过 LLM 质检）。")
        elif not tfidf_data:
            st.info("暂无 TF-IDF 信号词数据。请先触发 NLP 流水线（需 Route A 版本后端）。")
        else:
            if gate3_available:
                st.caption(
                    f"以下 {len(tfidf_data)} 个词已通过 LLM 质检（Gemini Flash 审判），"
                    f"噪音词已自动过滤。爆发系数 > 2.0 = 放量信号，共现度 > 0.3 = 有主题归属。"
                )
            elif quality_filtered:
                st.caption(
                    f"以下 {len(tfidf_data)} 个词已通过统计质检（✅ 通过 / 🛡️ L3保护），"
                    f"噪音、低爆发、孤立词已自动过滤。爆发系数 > 2.0 = 放量信号，共现度 > 0.3 = 有主题归属。"
                )
            else:
                st.caption(
                    f"以下 {len(tfidf_data)} 个词由 TF-IDF 引擎自动浮现（质检员尚未运行，显示全量候选词，含噪音）。"
                    f"爆发系数 > 2.0 = 放量信号，共现度 > 0.3 = 有主题归属。"
                )

            rows = []
            for item in tfidf_data:
                streak = item.get("consecutive_days", 0)
                br = item.get("burst_ratio", 0.0)
                cd = item.get("cooc_degree", 0.0)
                verdict = item.get("verdict", "unreviewed")
                gate3_reason = item.get("gate3_reason", "")
                if verdict == "protected_l3":
                    verdict_tag = "🛡️ 词典保护"
                elif gate3_reason:
                    verdict_tag = f"✅ {gate3_reason}"
                elif quality_filtered:
                    verdict_tag = "✅ 统计通过"
                else:
                    verdict_tag = "—"
                in_dict = item.get("in_dict", False)
                if in_dict:
                    l2_label = item.get("dict_l2") or "—"
                    l2_conf_pct = None
                else:
                    l2_aff = item.get("l2_affinity", "Uncategorized")
                    l2_label = l2_aff if l2_aff != "Uncategorized" else "🟠 未归类"
                    l2_conf_pct = round(item.get("l2_confidence", 0.0) * 100, 1)
                promo = item.get("promo_status", "候选中")
                rows.append({
                    "词汇": item["term"],
                    "入库状态": promo,
                    "TF-IDF 分": round(item.get("tfidf_score", 0.0), 5),
                    "今日文档数": item.get("doc_count", 0),
                    "爆发系数": round(br, 2),
                    "共现度": round(cd, 3),
                    "连续出现天": streak,
                    "归属 L2": l2_label,
                    "亲和置信度": l2_conf_pct,
                    "首次发现": item.get("first_seen", ""),
                    "质检": verdict_tag,
                })

            tfidf_df = pd.DataFrame(rows)
            st.dataframe(
                tfidf_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TF-IDF 分": st.column_config.NumberColumn(format="%.5f"),
                    "今日文档数": st.column_config.NumberColumn(format="%d"),
                    "爆发系数": st.column_config.ProgressColumn(
                        min_value=0.0, max_value=10.0, format="%.1fx"
                    ),
                    "共现度": st.column_config.ProgressColumn(
                        min_value=0.0, max_value=1.0, format="%.3f"
                    ),
                    "连续出现天": st.column_config.ProgressColumn(
                        min_value=0, max_value=14, format="%d 天"
                    ),
                    "亲和置信度": st.column_config.ProgressColumn(
                        "亲和置信度 %", min_value=0, max_value=100, format="%.0f%%"
                    ),
                },
            )

            top20 = tfidf_df.head(20)
            if not top20.empty:
                fig_bar = go.Figure(go.Bar(
                    x=top20["词汇"].tolist(),
                    y=top20["TF-IDF 分"].astype(float).tolist(),
                    marker_color="#3498DB",
                    text=top20["今日文档数"].astype(str).tolist(),
                    textposition="outside",
                ))
                fig_bar.update_layout(
                    title="质检通过词 Top-20 热度",
                    xaxis_title="词汇",
                    yaxis_title="TF-IDF 分",
                    height=350,
                    margin=dict(t=40, b=80, l=40, r=20),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc", size=13),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

    # ----- Sub-tab: Quality Gate Log -----
    with v3_sub2:
        qlog_lookback = st.selectbox("回溯天数", [7, 14, 30, 90], index=0, key="qlog_lookback")
        qlog_resp = fetch_quality_log(days=qlog_lookback)
        qlog_data = qlog_resp.get("data", [])
        if qlog_resp.get("degraded"):
            st.caption("质检日志暂不可用（后端可能未升级）。")
        elif not qlog_data:
            st.caption("暂无质检记录——请先运行流水线或 backfill。")
        else:
            verdict_map = {
                "pass": "✅ 通过",
                "protected_l3": "🛡️ L3保护",
                "borderline": "⚠️ 待人工",
                "noise_auto": "🚫 自动噪音",
                "noise_auto_stale": "🚫 超时自动噪音",
                "noise_llm": "🤖 LLM拒绝",
                "noise_cio": "🚫 CIO拒绝",
                "escalated": "📤 已升级归类",
                "low_burst": "📉 低爆发",
                "isolated": "🔇 孤立词",
            }
            bl_resp = fetch_borderline_terms(days=5)
            borderline_records = bl_resp.get("data", [])

            if borderline_records:
                st.markdown(
                    f"**⚠️ {len(borderline_records)} 个近期 borderline 词条待快速裁决**"
                    "（仅显示近 5 天新产生的边界词）"
                )

                bl_batch_col1, bl_batch_col2 = st.columns(2)
                with bl_batch_col1:
                    if st.button("✅ 全部强制通过", key="bl_batch_pass_v3"):
                        ok = 0
                        for bl in borderline_records:
                            res = post_borderline_force_pass(bl["term"])
                            if res.get("ok"):
                                ok += 1
                        st.success(f"已批量通过 {ok}/{len(borderline_records)} 个边界词")
                        st.rerun()
                with bl_batch_col2:
                    if st.button("🚫 全部标为噪音", key="bl_batch_noise_v3"):
                        ok = 0
                        for bl in borderline_records:
                            res = post_borderline_mark_noise(bl["term"])
                            if res.get("ok"):
                                ok += 1
                        st.success(f"已批量标噪 {ok}/{len(borderline_records)} 个边界词")
                        st.rerun()

                for bl in borderline_records:
                    bl_term = bl["term"]
                    burst = round(bl.get("burst_ratio", 0) or 0, 2)
                    cooc = round(bl.get("cooc_degree", 0) or 0, 3)
                    docs = bl.get("doc_count", 0) or 0
                    streak = bl.get("consecutive", 0) or 0
                    g2_pass = bl.get("gate2_pass", False)

                    g3_raw = bl.get("gate3_result") or ""
                    g3 = {}
                    if isinstance(g3_raw, str) and g3_raw.strip():
                        try:
                            g3 = json.loads(g3_raw)
                        except (json.JSONDecodeError, TypeError):
                            g3 = {}
                    elif isinstance(g3_raw, dict):
                        g3 = g3_raw
                    g3_reason = g3.get("reason", "")
                    g3_l2 = g3.get("l2_hint", "")

                    if g2_pass:
                        gate_label = "Gate3-语义：LLM判定模糊"
                        gate_color = "#5B8DEF"
                    else:
                        gate_label = "Gate2-矛盾：量大但无特征"
                        gate_color = "#E8913A"

                    st.markdown(
                        f'<div style="background:#1e1e2e;border-left:4px solid {gate_color};'
                        f'padding:10px 14px;margin-bottom:8px;border-radius:6px;">'
                        f'<span style="background:{gate_color};color:#fff;padding:2px 8px;'
                        f'border-radius:4px;font-size:13px;font-weight:600;">{gate_label}</span>'
                        f'&nbsp;&nbsp;<strong style="font-size:15px;">{html_lib.escape(bl_term)}</strong>'
                        f'<br><span style="font-size:13px;color:#aaa;">'
                        f'爆发系数: <b>{burst}</b> &nbsp;|&nbsp; '
                        f'共现度: <b>{cooc}</b> &nbsp;|&nbsp; '
                        f'文档数: <b>{docs}</b> &nbsp;|&nbsp; '
                        f'连续天数: <b>{streak}</b></span>',
                        unsafe_allow_html=True,
                    )
                    if g3_reason:
                        st.markdown(
                            f'<span style="font-size:13px;color:#ccc;">'
                            f'💬 Gemini: <i>"{html_lib.escape(g3_reason)}"</i></span>',
                            unsafe_allow_html=True,
                        )
                    if g3_l2:
                        st.markdown(
                            f'<span style="font-size:13px;color:#ccc;">'
                            f'📌 建议板块: <b>{html_lib.escape(g3_l2)}</b></span>',
                            unsafe_allow_html=True,
                        )
                    st.markdown('</div>', unsafe_allow_html=True)

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("✅ 强制通过", key=f"bl_pass_{bl_term}"):
                            res = post_borderline_force_pass(bl_term)
                            if res.get("ok"):
                                st.success(f"已通过: {bl_term}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "操作失败"))
                    with bc2:
                        if st.button("🚫 标记噪音", key=f"bl_noise_{bl_term}"):
                            res = post_borderline_mark_noise(bl_term)
                            if res.get("ok"):
                                st.success(f"已标噪: {bl_term}")
                                st.rerun()
                            else:
                                st.error(res.get("error", "操作失败"))
                st.divider()
            else:
                st.success("近 5 天内无新增边界词，无需裁决。")

            st.markdown(
                "<div style='padding:8px 14px;background:rgba(91,141,239,0.08);"
                "border-left:3px solid #5B8DEF;border-radius:4px;margin-bottom:12px;"
                "font-size:13px;color:#aaa'>"
                "超过 5 天未裁决的边界词将由慢时钟自动处理：活跃词升级到 "
                "<b>[主题发现] → 待归类中心</b>，衰退词自动标为噪音。"
                "</div>",
                unsafe_allow_html=True,
            )

            qlog_rows = []
            for q in qlog_data:
                verdict = q.get("final_verdict", "")
                qlog_rows.append({
                    "日期": q.get("check_date", ""),
                    "词汇": q["term"],
                    "爆发系数": round(q.get("burst_ratio", 0), 2),
                    "共现度": round(q.get("cooc_degree", 0), 3),
                    "连续天数": q.get("consecutive", 0),
                    "文档数": q.get("doc_count", 0),
                    "判决": verdict_map.get(verdict, verdict),
                })
            qlog_df = pd.DataFrame(qlog_rows)
            st.dataframe(qlog_df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("**📥 近期自动入库**")
        promoted_resp = fetch_recently_promoted(days=qlog_lookback)
        promoted_data = promoted_resp.get("data", [])
        if promoted_resp.get("degraded"):
            st.caption("近期自动入库数据暂不可用（需后端升级）。")
        elif not promoted_data:
            st.caption(f"过去 {qlog_lookback} 天内无自动入库词条。")
        else:
            st.caption(f"过去 {qlog_lookback} 天内，系统自动发现并入库了 **{len(promoted_data)}** 个新词。")
            promo_rows = []
            for p in promoted_data:
                promo_rows.append({
                    "词汇": p["term"],
                    "归属 L2": p.get("l2_sector", ""),
                    "入库时间": p.get("created_at", ""),
                    "TF-IDF 分": round(p.get("tfidf_score", 0) or 0, 5),
                    "连续天数": p.get("consecutive_days", 0),
                    "爆发系数": round(p.get("burst_ratio", 0) or 0, 2),
                    "共现度": round(p.get("cooc_degree", 0) or 0, 3),
                })
            st.dataframe(pd.DataFrame(promo_rows), use_container_width=True, hide_index=True)

    # ----- Sub-tab: New Terms Discovery -----
    with v3_sub3:
        NEW_TERM_WINDOWS = {"今日": 1, "近 3 日": 3, "近 7 日": 7}
        nt_window_label = st.selectbox(
            "时间窗", list(NEW_TERM_WINDOWS.keys()), index=0, key="nt_window"
        )
        nt_days = NEW_TERM_WINDOWS[nt_window_label]

        nt_resp = fetch_new_terms(days=nt_days, top_k=100)
        nt_data = nt_resp.get("data", [])

        if nt_resp.get("degraded"):
            st.markdown(
                "<div class='degraded-banner'>⚠️ 新词发现数据暂不可用，请确认后端流水线已运行。</div>",
                unsafe_allow_html=True,
            )
        else:
            auto_expanded = False
            if not nt_data and nt_days == 1:
                nt_resp = fetch_new_terms(days=3, top_k=100)
                nt_data = nt_resp.get("data", [])
                auto_expanded = True

            today_count = sum(1 for d in nt_data if d.get("is_today"))
            l2_set = set(d.get("l2_affinity", "Uncategorized") for d in nt_data)
            l2_set.discard("Uncategorized")

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("本窗口新词数", len(nt_data))
            mc2.metric("其中今日首现", today_count)
            mc3.metric("涉及板块", len(l2_set) if l2_set else "—")

            if auto_expanded:
                st.info("今日暂无新词冒头，已自动扩展至近 3 日。")

            if not nt_data:
                st.caption("近期无新词发现。")
            else:
                for item in nt_data:
                    term = item["term"]
                    is_today = item.get("is_today", False)
                    badge = "🆕 今日" if is_today else "🕐 近期"
                    tfidf_s = round(float(item.get("tfidf_score", 0)), 5)
                    burst = round(float(item.get("burst_ratio", 0)), 2)
                    l2 = item.get("l2_affinity", "Uncategorized")
                    first_seen = item.get("first_seen", "")
                    promo = item.get("promo_status", "候选中")
                    verdict = item.get("verdict", "unreviewed")

                    if verdict == "pass":
                        v_tag = "✅ 通过"
                    elif verdict == "protected_l3":
                        v_tag = "🛡️ 受保护"
                    elif verdict == "borderline":
                        v_tag = "⚠️ 边缘"
                    elif verdict == "fail":
                        v_tag = "❌ 未通过"
                    else:
                        v_tag = "🔘 未审"

                    card_html = (
                        f"<div style='border:1px solid #444; border-radius:8px; "
                        f"padding:12px 16px; margin-bottom:8px; "
                        f"background:rgba(26,188,156,0.06);'>"
                        f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                        f"<span style='font-size:16px; font-weight:700;'>{html_lib.escape(term)}</span>"
                        f"<span style='font-size:13px; padding:2px 8px; border-radius:4px; "
                        f"background:{'#1abc9c' if is_today else '#7f8c8d'}; color:#fff;'>"
                        f"{badge}</span></div>"
                        f"<div style='font-size:13px; margin-top:6px; color:#aaa;'>"
                        f"TF-IDF: <b>{tfidf_s}</b> &nbsp;|&nbsp; "
                        f"爆发系数: <b>{burst}</b> &nbsp;|&nbsp; "
                        f"板块: <b>{html_lib.escape(l2)}</b> &nbsp;|&nbsp; "
                        f"首现: <b>{first_seen}</b></div>"
                        f"<div style='font-size:13px; margin-top:4px; color:#aaa;'>"
                        f"入库状态: {html_lib.escape(promo)} &nbsp;|&nbsp; 质检: {v_tag}</div>"
                        f"</div>"
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

                l2_counts: dict[str, int] = {}
                for item in nt_data:
                    l2_name = item.get("l2_affinity", "Uncategorized")
                    l2_counts[l2_name] = l2_counts.get(l2_name, 0) + 1

                if len(l2_counts) > 1 or (len(l2_counts) == 1 and "Uncategorized" not in l2_counts):
                    sorted_l2 = sorted(l2_counts.items(), key=lambda x: x[1], reverse=True)
                    l2_labels = [x[0] for x in sorted_l2]
                    l2_vals = [float(x[1]) for x in sorted_l2]

                    fig_l2 = go.Figure(go.Bar(
                        x=l2_vals,
                        y=l2_labels,
                        orientation="h",
                        marker_color="#1abc9c",
                    ))
                    fig_l2.update_layout(
                        title="新词板块分布",
                        xaxis_title="新词数量",
                        yaxis_title="",
                        height=max(250, len(l2_labels) * 32),
                        margin=dict(l=10, r=10, t=40, b=30),
                    )
                    st.plotly_chart(fig_l2, use_container_width=True)


# =========================================================================
# Tab 4: L2/L3 Taxonomy Panorama & CIO Management
# =========================================================================
with tab4:
    _phase_header(4, "L2/L3 词典全景 & CIO 管理", "浏览完整词典树与词汇档案，CIO 可添加、归档、恢复词条")

    taxonomy_full_resp = fetch_taxonomy_full()
    taxonomy_full_data = taxonomy_full_resp.get("data", [])
    taxonomy_summary = taxonomy_full_resp.get("summary", {})

    if taxonomy_full_resp.get("degraded"):
        st.markdown(
            f'<div class="degraded-banner">⚠️ 词典加载失败：{taxonomy_full_resp.get("error", "未知")}</div>',
            unsafe_allow_html=True,
        )
    elif not taxonomy_full_data:
        st.info("叙事词典为空。请先在「主题发现」中生成并批准种子提案以建库。")
    else:
        v4_sub1, v4_sub2, v4_sub3, v4_sub4 = st.tabs(["📂 词典全景", "🛠️ CIO 词库管理", "🔇 噪音词管理", "📋 词汇档案"])

        # ----- Sub-tab: Taxonomy Panorama -----
        with v4_sub1:
            sm_c1, sm_c2, sm_c3, sm_c4 = st.columns(4)
            sm_c1.metric("L2 板块总数", taxonomy_summary.get("total_l2", 0))
            sm_c2.metric("L3 关键词总数", taxonomy_summary.get("total_terms", 0))
            sm_c3.metric("当前活跃 L2", taxonomy_summary.get("active_l2", 0))
            sm_c4.metric("当前活跃 L3", taxonomy_summary.get("active_terms", 0))

            tax_f_col1, tax_f_col2, tax_f_col3 = st.columns([2, 2, 3])
            with tax_f_col1:
                status_options = ["全部状态", "仅活跃", "含休眠", "含归档", "仅未激活蓝图"]
                status_filter_label = st.selectbox("按状态筛选", status_options, key="tax_status_filter")
            with tax_f_col2:
                src_options = [
                    "全部来源",
                    "seed（种子词）",
                    "approved（人工审批）",
                    "bottom_up（孤儿词提案）",
                    "tfidf_auto（TF-IDF晋升）",
                ]
                src_filter_label = st.selectbox("按来源筛选", src_options, key="tax_src_filter")
            with tax_f_col3:
                tax_search = st.text_input("🔍 搜索 L2 板块或 L3 关键词", key="tax_search", placeholder="输入关键词过滤...")

            src_filter_map = {
                "seed（种子词）": "seed",
                "approved（人工审批）": "approved",
                "bottom_up（孤儿词提案）": "bottom_up",
                "tfidf_auto（TF-IDF晋升）": "tfidf_auto",
            }
            active_src_filter = src_filter_map.get(src_filter_label, "")

            STATUS_STYLE = {
                "active":    {"bg": "rgba(255,255,255,0.07)", "color": "#e0e0e0", "suffix": " (活跃)",  "italic": False},
                "dormant":   {"bg": "",                       "color": "#666",    "suffix": "",          "italic": True},
                "archived":  {"bg": "",                       "color": "#444",    "suffix": "",          "italic": True},
                "seed_only": {"bg": "",                       "color": "#666",    "suffix": "",          "italic": True},
            }
            SOURCE_COLOR = {
                "seed":       ("rgba(52,152,219,0.18)",  "#3498DB"),
                "approved":   ("rgba(155,89,182,0.18)",  "#9B59B6"),
                "bottom_up":  ("rgba(243,156,18,0.18)",  "#F39C12"),
                "tfidf_auto": ("rgba(26,188,156,0.18)",  "#1ABC9C"),
            }

            filtered_l2s = []
            for l2_item in taxonomy_full_data:
                l2_name = l2_item["l2"]
                terms = l2_item["terms"]

                if status_filter_label == "仅活跃":
                    terms = [t for t in terms if t.get("status") == "active"]
                elif status_filter_label == "含休眠":
                    terms = [t for t in terms if t.get("status") in ("active", "dormant")]
                elif status_filter_label == "含归档":
                    terms = [t for t in terms if t.get("status") in ("active", "dormant", "archived")]
                elif status_filter_label == "仅未激活蓝图":
                    terms = [t for t in terms if t.get("status") == "seed_only"]

                if active_src_filter:
                    terms = [
                        t for t in terms
                        if _normalize_dict_source(t.get("source")) == active_src_filter
                    ]

                if tax_search.strip():
                    kw = tax_search.strip().lower()
                    if kw not in l2_name.lower() and not any(kw in t["term"].lower() for t in terms):
                        continue
                    if kw not in l2_name.lower():
                        terms = [t for t in terms if kw in t["term"].lower()]

                if terms:
                    filtered_l2s.append({
                        "l2": l2_name, "terms": terms,
                        "status_counts": l2_item.get("status_counts", {}),
                        "source_counts": l2_item.get("source_counts", {}),
                    })

            if not filtered_l2s:
                st.info("没有符合筛选条件的词条。")
            else:
                filtered_total = sum(len(item["terms"]) for item in filtered_l2s)
                st.caption(f"筛选结果：{len(filtered_l2s)} 个 L2 板块 · {filtered_total} 个 L3 关键词")

                for l2_item in filtered_l2s:
                    l2_name = l2_item["l2"]
                    terms = l2_item["terms"]
                    sc = l2_item["status_counts"]

                    status_parts = []
                    for sk, sl, scl in [
                        ("active", "活跃", "#2ECC71"), ("dormant", "休眠", "#ddd"),
                        ("archived", "归档", "#666"), ("seed_only", "未激活", "#3498DB"),
                    ]:
                        cnt = sc.get(sk, 0)
                        if cnt:
                            status_parts.append(f"<span style='color:{scl};font-size:13px'>{sl} {cnt}</span>")
                    status_summary = " &nbsp;·&nbsp; ".join(status_parts) if status_parts else ""

                    active_srcs = [
                        _normalize_dict_source(t.get("source", "seed"))
                        for t in terms if t.get("status") == "active"
                    ]
                    src_pool = active_srcs if active_srcs else [
                        _normalize_dict_source(t.get("source", "seed")) for t in terms
                    ]
                    dominant_src = max(set(src_pool), key=src_pool.count) if src_pool else "seed"
                    _, l2_color = SOURCE_COLOR.get(dominant_src, ("", "#F39C12"))

                    src_label_map = {
                        k: NARRATIVE_SOURCE_DISPLAY[k]
                        for k in ("seed", "approved", "bottom_up", "tfidf_auto")
                    }
                    src_order = [
                        ("seed", "#3498DB"),
                        ("approved", "#9B59B6"),
                        ("bottom_up", "#F39C12"),
                        ("tfidf_auto", "#1ABC9C"),
                    ]
                    src_counts_local: dict = {}
                    for t in terms:
                        s = _normalize_dict_source(t.get("source", "seed"))
                        src_counts_local[s] = src_counts_local.get(s, 0) + 1
                    l2_tooltip_parts = [
                        f"{src_label_map.get(sk, sk)}×{src_counts_local[sk]}"
                        for sk, _ in src_order if src_counts_local.get(sk, 0) > 0
                    ]
                    l2_tooltip = " / ".join(l2_tooltip_parts)

                    badges_html = ""
                    src_label_map_short = {
                        "seed": "种子",
                        "approved": "人工",
                        "bottom_up": "孤儿词",
                        "tfidf_auto": "TF-IDF",
                    }
                    for t in terms:
                        t_status = t.get("status", "active")
                        t_source = _normalize_dict_source(t.get("source", "seed"))
                        ss = STATUS_STYLE.get(t_status, STATUS_STYLE["active"])
                        term_safe = html_lib.escape(t["term"])
                        src_display = src_label_map_short.get(t_source, t_source)
                        tooltip = html_lib.escape(f"来源: {src_display} · 状态: {t_status}", quote=True)

                        bg = ss["bg"]
                        color = ss["color"]
                        suffix = ss["suffix"]
                        italic = ss.get("italic", False)
                        italic_style = "font-style:italic;" if italic else ""
                        bg_style = f"background:{bg};" if bg else ""
                        fw_style = "font-weight:600;" if t_status == "active" else ""
                        suffix_html = (
                            f"<small style='color:#888;font-weight:400'>{suffix}</small>"
                            if suffix else ""
                        )
                        badges_html += (
                            f"<span title='{tooltip}' style='display:inline-block;"
                            f"{bg_style}color:{color};padding:2px 8px;border-radius:4px;"
                            f"font-size:13px;margin:2px 3px 2px 0;{fw_style}{italic_style}'>"
                            f"{term_safe}{suffix_html}</span>"
                        )

                    st.markdown(f"""
                    <div style="background:#111;border:1px solid #2a2a2a;border-radius:8px;
                                padding:14px 18px;margin-bottom:10px">
                        <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
                            <span title="{l2_tooltip}" style="font-size:15px;font-weight:bold;color:{l2_color};cursor:default">
                                📂 {l2_name}
                            </span>
                            <span style="font-size:13px;color:#888">{len(terms)} 个词</span>
                            <span style="margin-left:auto">{status_summary}</span>
                        </div>
                        <div style="line-height:1.8">{badges_html}</div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("""
            <div style="font-size:13px;color:#888;margin-top:12px;padding:6px 0">
                <b>状态：</b>
                词后带 <small style='color:#888'>(活跃)</small> = 活跃 &nbsp;·&nbsp;
                <span style='color:#666;font-style:italic;font-size:13px'>斜体灰字 = 不活跃（休眠或从未命中）</span>&nbsp;·&nbsp;
                <span style='color:#444;font-style:italic;font-size:13px'>极暗斜体 = 归档</span>
                <br><b>来源：</b>
                <span style='background:rgba(52,152,219,0.18);color:#3498DB;padding:1px 7px;border-radius:3px;font-size:13px'>种子词</span>&nbsp;
                <span style='background:rgba(155,89,182,0.18);color:#9B59B6;padding:1px 7px;border-radius:3px;font-size:13px'>人工审批</span>&nbsp;
                <span style='background:rgba(243,156,18,0.18);color:#F39C12;padding:1px 7px;border-radius:3px;font-size:13px'>孤儿词提案</span>&nbsp;
                <span style='background:rgba(26,188,156,0.18);color:#1ABC9C;padding:1px 7px;border-radius:3px;font-size:13px'>TF-IDF晋升</span>
            </div>
            """, unsafe_allow_html=True)

        # ----- Sub-tab: CIO Dictionary Management (redesigned) -----
        with v4_sub2:
            all_l2_names = sorted(set(item["l2"] for item in taxonomy_full_data))

            # ================================================================
            # ZONE 1: L2 板块级管理（新建 / 重命名 / 删除）
            # ================================================================
            st.markdown("#### 🗂️ L2 板块管理")
            z1_new_col, z1_rename_col, z1_del_col = st.columns(3)

            with z1_new_col:
                st.markdown("**新建 L2 板块**")
                new_l2_name = st.text_input(
                    "板块名称", key="z1_new_l2_name", placeholder="例: AI_Infrastructure"
                )
                new_l2_seed = st.text_input(
                    "首个 L3 关键词（必填）", key="z1_new_l2_seed", placeholder="例: GPU cluster"
                )
                st.caption("新建板块必须附带至少一个关键词")
                if st.button("➕ 创建板块", key="z1_new_btn", use_container_width=True):
                    if new_l2_name.strip() and new_l2_seed.strip():
                        res = post_dictionary_add(new_l2_name.strip(), new_l2_seed.strip())
                        if res.get("success"):
                            st.success(f"已创建板块 [{new_l2_name.strip()}] 并添加首词 [{new_l2_seed.strip()}]")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"创建失败: {res.get('error')}")
                    else:
                        st.warning("板块名称和首个关键词均不可为空")

            with z1_rename_col:
                st.markdown("**重命名 L2 板块**")
                if all_l2_names:
                    rename_src = st.selectbox("选择要重命名的板块", all_l2_names, key="z1_rename_src")
                    rename_dst = st.text_input(
                        "新名称", key="z1_rename_dst", placeholder="输入新板块名..."
                    )
                    st.caption("重命名将同步更新所有历史匹配记录")
                    if st.button("✏️ 确认重命名", key="z1_rename_btn", use_container_width=True):
                        if rename_dst.strip():
                            res = post_dictionary_rename_l2(rename_src, rename_dst.strip())
                            if res.get("success"):
                                n = res.get("terms_updated", 0)
                                st.success(f"已将 [{rename_src}] 重命名为 [{rename_dst.strip()}]，涉及 {n} 条词条")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"重命名失败: {res.get('error')}")
                        else:
                            st.warning("新名称不可为空")
                else:
                    st.caption("暂无 L2 板块")

            with z1_del_col:
                st.markdown("**删除 L2 板块**")
                if all_l2_names:
                    del_l2 = st.selectbox("选择要删除的板块", all_l2_names, key="z1_del_l2")
                    st.caption("归档或删除后，种子词将同步压制，不再重新出现")
                    del_mode = st.radio(
                        "删除模式",
                        ["归档（可恢复）", "彻底删除（不可恢复）"],
                        key="z1_del_mode",
                        help="归档：将该板块所有词条标记为 archived；彻底删除：从数据库中永久删除",
                    )
                    mode_val = "archive" if del_mode == "归档（可恢复）" else "purge"
                    btn_label = "🗄️ 归档整个板块" if mode_val == "archive" else "🗑️ 彻底删除板块"
                    btn_type = "secondary" if mode_val == "archive" else "primary"
                    if mode_val == "purge":
                        st.warning("⚠️ 彻底删除后无法恢复，请谨慎操作")
                    if st.button(btn_label, key="z1_del_btn", use_container_width=True, type=btn_type):
                        res = post_dictionary_delete_l2(del_l2, mode=mode_val)
                        if res.get("success"):
                            n = res.get("terms_affected", 0)
                            action = res.get("action", "")
                            if action == "suppressed_seed":
                                action_label = "已永久压制（纯蓝图种子词板块）"
                            elif action == "archived":
                                action_label = "已归档"
                            else:
                                action_label = "已彻底删除"
                            st.success(f"{action_label}板块 [{del_l2}]，涉及 {n} 条词条")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"操作失败: {res.get('error')}")
                else:
                    st.caption("暂无 L2 板块")

            st.divider()

            # ================================================================
            # ZONE 2: 批量操作
            # ================================================================
            st.markdown("#### 🔑 L3 关键词管理")
            bt_add, bt_arc, bt_res, bt_mv, bt_noise = st.tabs([
                "➕ 批量添加", "🗄️ 批量归档", "♻️ 批量恢复", "📦 批量迁移", "🚫 批量标噪"
            ])

            with bt_add:
                st.markdown("""
<div style="background:rgba(46,204,113,0.08);border:1px solid rgba(46,204,113,0.3);
            border-radius:8px;padding:14px 18px;margin-bottom:14px">
    <div style="font-size:15px;font-weight:bold;color:#2ECC71;margin-bottom:8px">
        📋 批量添加格式说明
    </div>
    <div style="font-size:13px;color:#ccc;line-height:1.9">
        在下方文本框中粘贴要添加的 L3 关键词，<b>每行一个词</b>，纯文字即可，无需引号或逗号。<br>
        系统会自动跳过空行与已存在的活跃词，重复词不会报错。<br>
        所有通过此入口添加的词来源均标记为 <span style="background:rgba(155,89,182,0.18);
        color:#9B59B6;padding:1px 7px;border-radius:3px;font-size:13px">approved（人工审批）</span>。
    </div>
    <div style="font-size:13px;color:#888;margin-top:10px">
        <b>示例输入：</b>
    </div>
    <div style="font-family:monospace;font-size:13px;color:#aaa;background:#0d0d0d;
                border-radius:4px;padding:8px 12px;margin-top:4px;line-height:1.8">
        GPU cluster<br>AI chip<br>LLM inference<br>sovereign debt ceiling
    </div>
</div>
""", unsafe_allow_html=True)

                ba_add_l2 = st.selectbox(
                    "选择目标 L2 板块", all_l2_names, key="batch_add_l2"
                ) if all_l2_names else None

                if ba_add_l2:
                    ba_add_raw = st.text_area(
                        "粘贴 L3 关键词（每行一个）",
                        key="batch_add_raw",
                        height=160,
                        placeholder="GPU cluster\nAI chip\nLLM inference\n...",
                    )
                    ba_add_lines = [ln.strip() for ln in ba_add_raw.splitlines() if ln.strip()]
                    st.caption(f"已识别 {len(ba_add_lines)} 个词条待提交")

                    if st.button(
                        f"➕ 批量添加 ({len(ba_add_lines)} 条) → {ba_add_l2}",
                        key="batch_add_btn",
                        use_container_width=True,
                        disabled=len(ba_add_lines) == 0,
                    ):
                        added, skipped, failed = 0, 0, []
                        for kw in ba_add_lines:
                            res = post_dictionary_add(ba_add_l2, kw)
                            if res.get("success"):
                                action = res.get("action", "added")
                                if action == "already_active":
                                    skipped += 1
                                else:
                                    added += 1
                            else:
                                failed.append(f"{kw}（{res.get('error', '未知错误')}）")
                        st.success(f"批量添加完成：新增 {added} 条，跳过重复 {skipped} 条，失败 {len(failed)} 条")
                        if failed:
                            st.warning("以下词条添加失败：\n" + "\n".join(failed))
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.caption("暂无 L2 板块，请先在上方创建")

            with bt_arc:
                st.markdown("将选中词条软删除（归档），可通过批量恢复还原。")
                ba_l2 = st.selectbox("选择 L2 板块", all_l2_names, key="batch_arc_l2") if all_l2_names else None
                if ba_l2:
                    ba_terms = []
                    for item in taxonomy_full_data:
                        if item["l2"] == ba_l2:
                            for t in item["terms"]:
                                if t.get("status") in ("active", "dormant"):
                                    ba_terms.append(t["term"])
                            break
                    if ba_terms:
                        ba_selected = st.multiselect(
                            "勾选要归档的词条", sorted(ba_terms), key="batch_arc_sel",
                            placeholder="可多选..."
                        )
                        if st.button(
                            f"🗄️ 批量归档 ({len(ba_selected)} 条)",
                            key="batch_arc_btn", use_container_width=True,
                            disabled=len(ba_selected) == 0,
                        ):
                            items = [{"l2_sector": ba_l2, "l3_keyword": kw} for kw in ba_selected]
                            res = post_dictionary_batch_archive(items)
                            if res.get("success"):
                                st.success(f"批量归档完成：成功 {res.get('processed', 0)}/{res.get('total', 0)} 条")
                                failed = [d for d in res.get("details", []) if not d.get("ok")]
                                if failed:
                                    for f in failed:
                                        st.warning(f"[{f.get('term')}] 失败: {f.get('reason')}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"批量归档失败: {res.get('error')}")
                    else:
                        st.caption("该板块下无可归档的词条")

            with bt_res:
                st.markdown("将休眠或归档词条批量恢复为活跃状态。")
                br_l2_options = []
                for item in taxonomy_full_data:
                    for t in item["terms"]:
                        if t.get("status") in ("dormant", "archived"):
                            br_l2_options.append(item["l2"])
                            break
                if br_l2_options:
                    br_l2 = st.selectbox("选择 L2 板块", sorted(br_l2_options), key="batch_res_l2")
                    br_terms = []
                    for item in taxonomy_full_data:
                        if item["l2"] == br_l2:
                            for t in item["terms"]:
                                if t.get("status") in ("dormant", "archived"):
                                    status_label = "休眠" if t["status"] == "dormant" else "归档"
                                    br_terms.append((t["term"], status_label))
                            break
                    if br_terms:
                        br_labels = [f"{term} ({label})" for term, label in br_terms]
                        br_selected = st.multiselect(
                            "勾选要恢复的词条", sorted(br_labels), key="batch_res_sel",
                            placeholder="可多选..."
                        )
                        if st.button(
                            f"♻️ 批量恢复 ({len(br_selected)} 条)",
                            key="batch_res_btn", use_container_width=True,
                            disabled=len(br_selected) == 0,
                        ):
                            items = [
                                {"l2_sector": br_l2, "l3_keyword": lbl.rsplit(" (", 1)[0]}
                                for lbl in br_selected
                            ]
                            res = post_dictionary_batch_restore(items)
                            if res.get("success"):
                                st.success(f"批量恢复完成：成功 {res.get('processed', 0)}/{res.get('total', 0)} 条")
                                failed = [d for d in res.get("details", []) if not d.get("ok")]
                                if failed:
                                    for f in failed:
                                        st.warning(f"[{f.get('term')}] 失败: {f.get('reason')}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"批量恢复失败: {res.get('error')}")
                    else:
                        st.caption("该板块下无可恢复的词条")
                else:
                    st.caption("当前没有休眠或归档状态的词条")

            with bt_mv:
                st.markdown("将词条从一个 L2 板块批量迁移到另一个板块。")
                if len(all_l2_names) >= 2:
                    mv_src_l2 = st.selectbox("源 L2 板块", all_l2_names, key="batch_mv_src")
                    mv_terms = []
                    for item in taxonomy_full_data:
                        if item["l2"] == mv_src_l2:
                            for t in item["terms"]:
                                if t.get("status") in ("active", "dormant"):
                                    mv_terms.append(t["term"])
                            break
                    if mv_terms:
                        mv_selected = st.multiselect(
                            "勾选要迁移的词条", sorted(mv_terms), key="batch_mv_sel",
                            placeholder="可多选..."
                        )
                        mv_tgt_options = [n for n in all_l2_names if n != mv_src_l2]
                        mv_tgt_l2 = st.selectbox("目标 L2 板块", mv_tgt_options, key="batch_mv_tgt")
                        if st.button(
                            f"📦 批量迁移 ({len(mv_selected)} 条) → {mv_tgt_l2}",
                            key="batch_mv_btn", use_container_width=True,
                            disabled=len(mv_selected) == 0,
                        ):
                            res = post_dictionary_batch_move(mv_src_l2, mv_tgt_l2, mv_selected)
                            if res.get("success"):
                                st.success(f"批量迁移完成：成功 {res.get('processed', 0)}/{res.get('total', 0)} 条")
                                failed = [d for d in res.get("details", []) if not d.get("ok")]
                                if failed:
                                    for f in failed:
                                        st.warning(f"[{f.get('term')}] 失败: {f.get('reason')}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"批量迁移失败: {res.get('error')}")
                    else:
                        st.caption("该板块下无可迁移的词条")
                else:
                    st.caption("至少需要 2 个 L2 板块才能使用迁移功能")

            with bt_noise:
                st.markdown("从词典中彻底移除词条，可选择是否同时加入噪音黑名单。")
                bn_l2 = st.selectbox("选择 L2 板块", all_l2_names, key="batch_noise_l2") if all_l2_names else None
                if bn_l2:
                    bn_terms = []
                    for item in taxonomy_full_data:
                        if item["l2"] == bn_l2:
                            for t in item["terms"]:
                                if t.get("status") in ("active", "dormant", "archived"):
                                    bn_terms.append(t["term"])
                            break
                    if bn_terms:
                        bn_selected = st.multiselect(
                            "勾选要删除的词条", sorted(bn_terms), key="batch_noise_sel",
                            placeholder="可多选..."
                        )
                        bn_mode = st.radio(
                            "操作类型",
                            ["🗑️ 仅从词典删除（不加入噪音黑名单）", "🚫 删除 + 标记为噪音（不可撤销）"],
                            key="batch_del_mode",
                            horizontal=False,
                        )
                        if bn_mode.startswith("🗑️"):
                            st.caption("词条将从词典永久移除，但不会进入噪音黑名单。")
                            bn_btn_label = f"🗑️ 批量删除 ({len(bn_selected)} 条)"
                        else:
                            st.caption("⚠️ 词条将从词典删除并加入噪音黑名单，不可通过恢复功能撤销。")
                            bn_btn_label = f"🚫 批量删除并标噪 ({len(bn_selected)} 条)"
                        if st.button(
                            bn_btn_label,
                            key="batch_noise_btn", use_container_width=True,
                            disabled=len(bn_selected) == 0,
                            type="secondary",
                        ):
                            items = [{"l2_sector": bn_l2, "l3_keyword": kw} for kw in bn_selected]
                            if bn_mode.startswith("🗑️"):
                                res = post_dictionary_batch_delete(items)
                                if res.get("success"):
                                    st.success(f"批量删除完成：{res.get('processed', 0)}/{res.get('total', 0)} 条已从词典移除")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"批量删除失败: {res.get('error')}")
                            else:
                                res = post_dictionary_batch_mark_noise(items)
                                if res.get("success"):
                                    st.success(f"标噪完成：{res.get('processed', 0)}/{res.get('total', 0)} 条已移入噪音黑名单")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"标噪失败: {res.get('error')}")

        # ----- Sub-tab: Noise Words Management (enhanced) -----
        with v4_sub3:
            noise_resp = fetch_noise_words()
            noise_data = noise_resp.get("data", [])

            if noise_resp.get("degraded"):
                st.caption("噪音词表暂不可用（后端可能未升级）。")
            else:
                noise_search = st.text_input(
                    "🔍 搜索噪音词", key="v4_noise_search",
                    placeholder="输入关键词过滤列表...",
                )

                display_data = noise_data
                if noise_search.strip():
                    kw = noise_search.strip().lower()
                    display_data = [
                        nw for nw in noise_data
                        if kw in nw["term"].lower()
                        or kw in (nw.get("reason") or "").lower()
                        or kw in (nw.get("source") or "").lower()
                    ]

                if not noise_data:
                    st.caption("动态噪音词表为空——暂无自动或手动标记的噪音词。")
                elif not display_data:
                    st.caption(f"没有匹配「{noise_search.strip()}」的噪音词。")
                else:
                    noise_rows = []
                    for nw in display_data:
                        noise_rows.append({
                            "词汇": nw["term"],
                            "来源": nw["source"],
                            "置信度": round(nw.get("confidence", 0), 2),
                            "添加日期": nw.get("added_date", ""),
                            "过期日期": nw.get("expires_date", ""),
                            "原因": nw.get("reason", ""),
                        })
                    noise_df = pd.DataFrame(noise_rows)
                    st.dataframe(noise_df, use_container_width=True, hide_index=True)
                    st.caption(f"共 {len(noise_data)} 条噪音词，当前显示 {len(display_data)} 条")

                st.divider()

                st.markdown("**➕ 手动添加噪音词**")
                na_c1, na_c2 = st.columns([3, 1])
                with na_c1:
                    noise_add_term = st.text_input(
                        "词汇", placeholder="输入要屏蔽的词汇...",
                        key="v4_noise_add_input", label_visibility="collapsed",
                    )
                with na_c2:
                    if st.button("添加到噪音词表", key="v4_noise_add_btn", use_container_width=True):
                        if noise_add_term.strip():
                            res = post_noise_word_add(noise_add_term.strip())
                            if res.get("ok"):
                                st.success(f"已添加 \"{noise_add_term.strip()}\"，过期: {res.get('expires_date')}")
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(f"添加失败: {res.get('error')}")
                        else:
                            st.warning("请输入要添加的词汇")

                if noise_data:
                    st.divider()
                    st.markdown("**🗑️ 移除噪音词（解除屏蔽）**")
                    nr_c1, nr_c2 = st.columns([3, 1])
                    with nr_c1:
                        noise_rm_input = st.text_input(
                            "词汇", placeholder="输入要移除的词汇名称...",
                            key="v4_noise_rm_input", label_visibility="collapsed",
                        )
                    with nr_c2:
                        rm_disabled = not noise_rm_input.strip()
                        if st.button(
                            "移除（解除屏蔽）", key="v4_noise_rm_btn",
                            use_container_width=True, disabled=rm_disabled,
                        ):
                            target = noise_rm_input.strip()
                            existing = [nw["term"] for nw in noise_data]
                            if target in existing:
                                res = post_noise_word_remove(target)
                                if res.get("ok"):
                                    st.success(f"已解除 \"{target}\" 的屏蔽")
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(f"移除失败: {res.get('error')}")
                            else:
                                st.warning(f"噪音词表中不存在 \"{target}\"，请检查拼写")
                    if noise_rm_input.strip():
                        kw_rm = noise_rm_input.strip().lower()
                        matches = [nw["term"] for nw in noise_data if kw_rm in nw["term"].lower()]
                        if matches:
                            st.caption(f"匹配到 {len(matches)} 个词：{', '.join(matches[:20])}")
                        else:
                            st.caption("未匹配到任何噪音词")

        # ----- Sub-tab: Vocabulary Archive -----
        with v4_sub4:
            st.caption("按 L2 板块浏览词汇档案，选择词条查看完整四阶段生命轨迹。")

            _TIMELINE_CSS = """
            <style>
            .tl-card{position:relative;padding:12px 16px 12px 28px;margin-left:16px;
                     border-left:3px solid #333;margin-bottom:0}
            .tl-card:last-child{border-left-color:transparent}
            .tl-dot{position:absolute;left:-9px;top:14px;width:14px;height:14px;
                    border-radius:50%;border:2px solid #222}
            .tl-stage{font-size:14px;font-weight:600;margin-bottom:4px}
            .tl-detail{font-size:13px;color:#aaa;line-height:1.6}
            </style>
            """
            st.markdown(_TIMELINE_CSS, unsafe_allow_html=True)

            for l2_item in taxonomy_full_data:
                l2_name = l2_item["l2"]
                terms = l2_item["terms"]
                active_n = sum(1 for t in terms if t.get("status") == "active")
                with st.expander(f"📂 {l2_name}  ({active_n} 活跃 / {len(terms)} 总计)"):
                    arch_rows = []
                    for t in terms:
                        arch_rows.append({
                            "L3 关键词": t["term"],
                            "状态": t.get("status", ""),
                            "来源": _narrative_source_label(t.get("source", "")),
                        })
                    st.dataframe(pd.DataFrame(arch_rows), use_container_width=True, hide_index=True)

                    term_names = [t["term"] for t in terms]
                    sel_term = st.selectbox(
                        "选择词条查看档案", term_names,
                        key=f"v4arch_sel_{l2_name}",
                    )
                    if st.button("📜 展开生命轨迹", key=f"v4arch_btn_{l2_name}"):
                        trace_resp = fetch_term_trace(sel_term)
                        if not trace_resp.get("found"):
                            st.info(f"未找到 [{sel_term}] 的生命轨迹记录。")
                        else:
                            timeline = trace_resp.get("timeline", [])
                            _STAGE_STYLE = {
                                "TF-IDF 候选": ("#3498DB", "🔵"),
                                "质检记录":    ("#F39C12", "🔬"),
                                "词典入库":    ("#2ECC71", "📗"),
                                "噪音黑名单":  ("#E74C3C", "🚫"),
                            }
                            cards_html = ""
                            for entry in timeline:
                                stage = entry.get("stage", "")
                                color, icon = _STAGE_STYLE.get(stage, ("#888", "❓"))
                                detail = ""
                                if stage == "TF-IDF 候选":
                                    s_icon = {"candidate": "🔵", "promoted": "✅", "noise_rejected": "🚫", "expired": "⏰"}.get(entry.get("status", ""), "❓")
                                    detail = (
                                        f"状态: {s_icon} {entry.get('status')} · "
                                        f"首次: {entry.get('first_seen')} · 最后: {entry.get('last_seen')} · "
                                        f"连续 {entry.get('consecutive_days')} 天<br>"
                                        f"TF-IDF: {entry.get('tfidf_score')} · "
                                        f"爆发: {entry.get('burst_ratio')}x · "
                                        f"共现度: {entry.get('cooc_degree')} · "
                                        f"Gate3: {'通过' if entry.get('gate3_pass') else '未通过'}"
                                    )
                                elif stage == "质检记录":
                                    v_map = {"pass": "✅ 通过", "borderline": "⚠️ 待人工", "noise_auto": "🚫 自动噪音",
                                             "noise_auto_stale": "🚫 超时自动噪音", "escalated": "📤 已升级归类",
                                             "noise_llm": "🤖 LLM拒绝", "noise_cio": "🚫 CIO拒绝",
                                             "protected_l3": "🛡️ 词典保护", "low_burst": "📉 低爆发", "isolated": "🔇 孤立"}
                                    v_label = v_map.get(entry.get("verdict", ""), entry.get("verdict", ""))
                                    detail = f"日期: {entry.get('date')} · 判决: {v_label}"
                                elif stage == "词典入库":
                                    hint = entry.get('promoted_l2_hint') or '—'
                                    conf = entry.get('promoted_confidence', 0) * 100
                                    detail = (
                                        f"L2: {entry.get('l2_sector')} · 状态: {entry.get('status')} · "
                                        f"来源: {entry.get('source')}<br>"
                                        f"入库时间: {entry.get('created_at')} · 推荐: {hint} ({conf:.0f}%)"
                                    )
                                elif stage == "噪音黑名单":
                                    detail = (
                                        f"加入: {entry.get('added_date')} · 过期: {entry.get('expires_date')}<br>"
                                        f"来源: {entry.get('source')} · 置信度: {entry.get('confidence')} · "
                                        f"原因: {entry.get('reason', '')}"
                                    )
                                cards_html += (
                                    f"<div class='tl-card'>"
                                    f"<div class='tl-dot' style='background:{color}'></div>"
                                    f"<div class='tl-stage' style='color:{color}'>{icon} {stage}</div>"
                                    f"<div class='tl-detail'>{detail}</div>"
                                    f"</div>"
                                )
                            st.markdown(cards_html, unsafe_allow_html=True)


# =========================================================================
# Tab 5: Narrative Quadrant Radar (v2 — cross-sector heat ranking + L3 drill-down)
# =========================================================================
with tab5:
    _phase_header(
        5, "叙事四象限雷达",
        "横轴 = 综合热力原始分 (0-1)，纵轴 = 情感动量，颜色 = 热度集中类型",
    )

    # ---------- Fetch APIs ----------
    l2l3_resp = fetch_l2_l3_detail(days=7)
    l2l3_data = l2l3_resp.get("data", [])
    qh_resp = fetch_quadrant_history(days=30)
    qh_data = qh_resp.get("data", [])

    if l2l3_resp.get("degraded"):
        st.markdown(
            f'<div class="degraded-banner">⚠️ 数据降级：{l2l3_resp.get("error", "未知")}</div>',
            unsafe_allow_html=True,
        )
    if qh_resp.get("degraded"):
        st.warning(
            f"⚠️ 四象限历史快照不可用：{qh_resp.get('error', '未知错误')}"
            "（历史日期选择器将仅显示「今天」）"
        )

    # (legacy heatmap API removed — sub-tabs 2 & 3 now share l2l3/qh data)

    # --- Build quadrant history lookup for dwell / prev-quadrant --------
    _qh_by_sector: dict[str, list[dict]] = {}
    for qr in qh_data:
        _qh_by_sector.setdefault(qr["l2_sector"], []).append(qr)
    for _sk in _qh_by_sector:
        _qh_by_sector[_sk].sort(key=lambda x: x["date"])

    def _compute_dwell(sector: str, ref_date_str: str):
        """Return (dwell_days, prev_quadrant) from quadrant history."""
        seq = _qh_by_sector.get(sector, [])
        relevant = [s for s in seq if s["date"] <= ref_date_str]
        if not relevant:
            return 0, "—"
        current_q = relevant[-1]["quadrant"]
        dwell = 0
        prev_q = "—"
        for item in reversed(relevant):
            if item["quadrant"] == current_q:
                dwell += 1
            else:
                prev_q = item["quadrant"]
                break
        return dwell, prev_q

    # --- Available history dates for date picker ---
    _hist_dates_set = sorted({qr["date"] for qr in qh_data})

    if l2l3_data:
        df_radar = pd.DataFrame(l2l3_data)
        df_radar["heat_percentile"] = df_radar["heat_percentile"].astype(float)
        df_radar["sentiment_momentum"] = df_radar["sentiment_momentum"].astype(float)
        df_radar["composite_heat"] = df_radar["composite_heat"].astype(float)
        df_radar["mention_count"] = pd.to_numeric(df_radar["mention_count"], errors="coerce").fillna(0)
        if "sentiment_data_days" not in df_radar.columns:
            df_radar["sentiment_data_days"] = 7

        v5_sub1, v5_sub2, v5_sub3 = st.tabs(["🎯 四象限雷达", "🏆 板块热度榜", "⚡ 情绪异动榜"])

        # =====================================================================
        # Sub-tab 1: Quadrant Radar (rewritten v3)
        # =====================================================================
        with v5_sub1:
            # --- Date picker (snapshot replay) ---
            _today_str = _date.today().isoformat()
            _date_options = sorted(set(_hist_dates_set + [_today_str]))
            _default_idx = len(_date_options) - 1
            snap_col1, snap_col2 = st.columns([3, 1])
            with snap_col2:
                _n_hist = len(_hist_dates_set)
                selected_snap_date = st.selectbox(
                    f"快照日期（共 {_n_hist} 个历史日期）",
                    _date_options,
                    index=_default_idx,
                    key="quad_snap_date",
                    format_func=lambda d: "今天" if d == _today_str else d,
                )
            with snap_col1:
                st.caption(
                    "横轴 = 综合热力分 (0-1, 越右越热)"
                    "　｜　纵轴 = 情感动量 (固定 ±0.5)"
                    "　｜　🔴 单词爆发型 / 🔵 多词共振型"
                )

            # --- Build snapshot DataFrame ---
            _use_today = (selected_snap_date == _today_str)
            if _use_today:
                df_snap = df_radar.copy()
            else:
                snap_rows = [r for r in qh_data if r["date"] == selected_snap_date]
                if snap_rows:
                    df_snap = pd.DataFrame(snap_rows)
                    df_snap["mention_count"] = 0
                    df_snap["heat_type"] = "distributed"
                    df_snap["heat_concentration"] = 0.0
                    df_snap["active_l3_count"] = 0
                    df_snap["total_l3_count"] = 0
                    df_snap["heat_rank"] = 0
                    df_snap["sentiment_data_days"] = 7
                    df_snap["top_l3_keywords"] = [[] for _ in range(len(df_snap))]
                    df_snap["heat_factor_breakdown"] = [None for _ in range(len(df_snap))]
                    df_snap["composite_heat"] = df_snap["composite_heat"].astype(float)
                    df_snap["sentiment_momentum"] = df_snap["sentiment_momentum"].astype(float)
                    df_snap = df_snap.sort_values("composite_heat", ascending=False).reset_index(drop=True)
                    for ri in range(len(df_snap)):
                        df_snap.loc[df_snap.index[ri], "heat_rank"] = ri + 1
                    for ri, row in df_snap.iterrows():
                        ht = [r for r in l2l3_data if r["l2_sector"] == row["l2_sector"]]
                        if ht:
                            df_snap.at[ri, "heat_type"] = ht[0].get("heat_type", "distributed")
                            df_snap.at[ri, "mention_count"] = ht[0].get("mention_count", 0)
                else:
                    st.warning(
                        f"⚠️ 历史日期 {selected_snap_date} 无可用快照数据，已回退显示今天的数据。"
                    )
                    df_snap = df_radar.copy()

            # --- Build scatter plot ---
            fig_quad = go.Figure()

            # Neutral zone gray rectangle
            fig_quad.add_shape(
                type="rect", x0=0, x1=1, y0=-0.1, y1=0.1,
                fillcolor="rgba(128,128,128,0.08)", line_width=0, layer="below",
            )
            # Reference lines
            fig_quad.add_hline(y=0, line_dash="dash", line_color="#FFFFFF", opacity=0.4)
            fig_quad.add_hline(y=0.1, line_dash="dot", line_color="#888", opacity=0.35)
            fig_quad.add_hline(y=-0.1, line_dash="dot", line_color="#888", opacity=0.35)
            fig_quad.add_hline(y=0.2, line_color="#666", opacity=0.4, line_width=1)
            fig_quad.add_hline(y=-0.2, line_color="#666", opacity=0.4, line_width=1)
            fig_quad.add_vline(x=0.5, line_dash="dash", line_color="#FFFFFF", opacity=0.3)

            for _, row in df_snap.iterrows():
                is_concentrated = row.get("heat_type") == "concentrated"
                type_label = "单词爆发" if is_concentrated else "多词共振"

                dwell_d, prev_q = _compute_dwell(row["l2_sector"], selected_snap_date)

                top_kws = row.get("top_l3_keywords", [])
                kw_lines = ""
                if isinstance(top_kws, list):
                    for kw in top_kws[:3]:
                        if isinstance(kw, dict):
                            kw_lines += (
                                f"  {kw['keyword']}: {kw['doc_count']}篇, "
                                f"burst {kw['burst_ratio']:.1f}x, "
                                f"{kw['consecutive_days']}天<br>"
                            )
                if not kw_lines:
                    kw_lines = "  (无活跃 L3 词)<br>"

                hover_text = (
                    f"<b>{row['l2_sector']}</b><br>"
                    f"热力排名: #{int(row.get('heat_rank', 0))} "
                    f"(综合分 {float(row['composite_heat']):.3f})<br>"
                    f"情感动量: {float(row['sentiment_momentum']):+.3f}<br>"
                    f"提及量: {int(row.get('mention_count', 0))}<br>"
                    f"类型: {type_label}<br>"
                    f"象限停留: {dwell_d}天 | 上一象限: {prev_q}<br>"
                    f"--- Top L3 ---<br>{kw_lines}"
                )

                border_color = "#E74C3C" if is_concentrated else "#3498DB"

                fig_quad.add_trace(go.Scatter(
                    x=[float(row["composite_heat"])],
                    y=[float(row["sentiment_momentum"])],
                    mode="markers+text",
                    text=[row["l2_sector"]],
                    textposition="top center",
                    textfont=dict(size=13, color="#eee"),
                    marker=dict(
                        size=13,
                        symbol="circle",
                        color=border_color,
                        opacity=0.85,
                        line=dict(width=1, color=border_color),
                    ),
                    hovertext=hover_text,
                    hoverinfo="text",
                    showlegend=False,
                ))

            # Quadrant label annotations
            fig_quad.add_annotation(
                x=0.85, y=0.38,
                text="🔥 舆论风口<br><span style='font-size:13px'>(热度高+情感升温)</span>",
                showarrow=False, font=dict(color="#E74C3C", size=14),
            )
            fig_quad.add_annotation(
                x=0.15, y=-0.38,
                text="❄️ 冷淡低迷<br><span style='font-size:13px'>(热度低+情感降温)</span>",
                showarrow=False, font=dict(color="#3498DB", size=14),
            )
            fig_quad.add_annotation(
                x=0.15, y=0.38,
                text="🌱 静默潜伏<br><span style='font-size:13px'>(热度低+情感升温)</span>",
                showarrow=False, font=dict(color="#2ECC71", size=14),
            )
            fig_quad.add_annotation(
                x=0.85, y=-0.38,
                text="⚠️ 舆论恐慌<br><span style='font-size:13px'>(热度高+情感降温)</span>",
                showarrow=False, font=dict(color="#E67E22", size=14),
            )

            fig_quad.update_layout(
                height=600,
                plot_bgcolor="#111111",
                paper_bgcolor="#111111",
                font=dict(color="#ddd", size=13),
                showlegend=False,
                xaxis=dict(
                    title="冷门 ← 综合热力分 → 爆发",
                    zeroline=False,
                    range=[-0.08, 1.08],
                    tickvals=[0, 0.25, 0.5, 0.75, 1.0],
                    ticktext=["0", "0.25", "0.5", "0.75", "1.0"],
                    gridcolor="rgba(80,80,80,0.3)",
                ),
                yaxis=dict(
                    title="情感降温 ← 情感动量 → 情感升温",
                    zeroline=False,
                    range=[-0.5, 0.5],
                    tickvals=[-0.4, -0.2, -0.1, 0, 0.1, 0.2, 0.4],
                    gridcolor="rgba(80,80,80,0.3)",
                ),
                margin=dict(l=80, r=30, t=50, b=70),
            )
            st.markdown(
                "<div style='display:flex;gap:24px;padding:6px 12px;"
                "background:rgba(0,0,0,0.4);border-radius:6px;"
                "font-size:13px;color:#ddd;margin-bottom:4px'>"
                "<span>🔴 单词爆发型（集中度高）</span>"
                "<span>🔵 多词共振型（集中度低）</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(fig_quad, use_container_width=True)

            # --- Quadrant attribution cards (v3) ---
            def _assign_quadrant(ch, sm):
                if ch > 0.5 and sm > 0:
                    return "舆论风口"
                elif ch <= 0.5 and sm > 0:
                    return "静默潜伏"
                elif ch > 0.5 and sm <= 0:
                    return "舆论恐慌"
                return "冷淡低迷"

            _q_map = {"舆论风口": [], "静默潜伏": [], "舆论恐慌": [], "冷淡低迷": []}
            for _, row in df_snap.iterrows():
                q_label = _assign_quadrant(float(row["composite_heat"]), float(row["sentiment_momentum"]))
                _q_map[q_label].append(
                    f"<span style='font-size:13px'><b>{row['l2_sector']}</b></span>"
                )

            def _fmt_q_tags(items):
                return " ".join(items) if items else "<span style='color:#666'>—</span>"

            st.markdown(f"""
<div style="background:#1a1a1a;border-left:4px solid #F39C12;padding:14px 16px;
            border-radius:6px;margin-top:8px">
    <div style="font-size:15px;font-weight:bold;color:#F39C12;margin-bottom:10px">
        四象限归因
    </div>
    <div style="display:flex;flex-direction:column;gap:6px;font-size:14px;color:#ddd">
        <div>🔥 <b style="color:#E74C3C">舆论风口</b> ({len(_q_map['舆论风口'])}): {_fmt_q_tags(_q_map['舆论风口'])}</div>
        <div>🌱 <b style="color:#2ECC71">静默潜伏</b> ({len(_q_map['静默潜伏'])}): {_fmt_q_tags(_q_map['静默潜伏'])}</div>
        <div>⚠️ <b style="color:#E67E22">舆论恐慌</b> ({len(_q_map['舆论恐慌'])}): {_fmt_q_tags(_q_map['舆论恐慌'])}</div>
        <div>❄️ <b style="color:#3498DB">冷淡低迷</b> ({len(_q_map['冷淡低迷'])}): {_fmt_q_tags(_q_map['冷淡低迷'])}</div>
    </div>
</div>
""", unsafe_allow_html=True)

            # --- L3 drill-down panel (enhanced v3) ---
            st.markdown("---")
            st.markdown(
                "<div style='font-size:15px;font-weight:bold;color:#F39C12;margin-bottom:6px'>"
                "🔍 L3 关键词贡献下钻（选择板块查看详情）</div>",
                unsafe_allow_html=True,
            )
            sector_options = df_snap.sort_values("heat_rank")["l2_sector"].tolist()
            selected_sector = st.selectbox(
                "选择 L2 板块", sector_options, key="l3_drilldown_sector",
                label_visibility="collapsed",
            )

            sel_row = df_snap[df_snap["l2_sector"] == selected_sector]
            if not sel_row.empty:
                sr = sel_row.iloc[0]
                dwell_d, prev_q = _compute_dwell(selected_sector, selected_snap_date)
                cur_q = _assign_quadrant(float(sr["composite_heat"]), float(sr["sentiment_momentum"]))

                sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
                sc1.metric("热力排名", f"#{int(sr.get('heat_rank', 0))}")
                sc2.metric("综合热力分", f"{float(sr['composite_heat']):.3f}")
                sc3.metric("情感动量", f"{float(sr['sentiment_momentum']):+.3f}")
                type_label = "🔴 单词爆发" if sr.get("heat_type") == "concentrated" else "🔵 多词共振"
                sc4.metric("热度类型", type_label)
                sc5.metric("当前象限", cur_q)
                sc6.metric("象限停留", f"{dwell_d}天")

                # --- Heat factor breakdown stacked bar ---
                hfb = sr.get("heat_factor_breakdown")
                if isinstance(hfb, dict) and hfb:
                    factor_labels = ["提及量", "爆发度", "活跃词数", "持续天数"]
                    factor_keys = ["mention_norm", "burst_norm", "active_l3_norm", "consecutive_norm"]
                    factor_colors = ["#3498DB", "#E74C3C", "#2ECC71", "#F39C12"]
                    factor_vals = [float(hfb.get(k, 0)) for k in factor_keys]

                    fig_hfb = go.Figure()
                    cumx = 0.0
                    for fi in range(4):
                        w = factor_vals[fi]
                        fig_hfb.add_trace(go.Bar(
                            y=["热力因子"],
                            x=[w],
                            orientation="h",
                            name=f"{factor_labels[fi]} ({w:.2f})",
                            marker_color=factor_colors[fi],
                            text=[f"{factor_labels[fi]}<br>{w:.2f}"],
                            textposition="inside",
                            textfont=dict(size=13, color="#fff"),
                            hovertemplate=f"{factor_labels[fi]}: {w:.3f}<extra></extra>",
                        ))
                        cumx += w
                    fig_hfb.update_layout(
                        barmode="stack",
                        height=80,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#ccc", size=13),
                        xaxis=dict(range=[0, max(cumx * 1.05, 1.0)], showticklabels=False),
                        yaxis=dict(showticklabels=False),
                        margin=dict(l=10, r=10, t=5, b=5),
                        legend=dict(
                            font=dict(size=13), orientation="h",
                            yanchor="top", y=-0.3, xanchor="left", x=0,
                        ),
                        showlegend=True,
                    )
                    st.plotly_chart(fig_hfb, use_container_width=True)

                # --- L3 bar chart (enhanced) ---
                top_kws = sr.get("top_l3_keywords", [])
                if isinstance(top_kws, list) and top_kws and isinstance(top_kws[0], dict):
                    kw_df = pd.DataFrame(top_kws)
                    kw_df = kw_df.sort_values("doc_count", ascending=True)

                    fig_kw = go.Figure()

                    # Main bar: doc_count
                    colors = []
                    for _, kw_row in kw_df.iterrows():
                        br = float(kw_row.get("burst_ratio", 0))
                        if br >= 3.0:
                            colors.append("#E74C3C")
                        elif br >= 1.5:
                            colors.append("#F39C12")
                        else:
                            colors.append("#3498DB")

                    max_dc = float(kw_df["doc_count"].max()) if not kw_df.empty else 1.0

                    fig_kw.add_trace(go.Bar(
                        y=kw_df["keyword"].tolist(),
                        x=kw_df["doc_count"].astype(float).tolist(),
                        orientation="h",
                        marker_color=colors,
                        name="命中文章",
                        hovertemplate="<b>%{y}</b><br>命中文章: %{x:.0f}<extra></extra>",
                    ))

                    # Right-side consecutive_days annotations
                    for idx, (_, kw_row) in enumerate(kw_df.iterrows()):
                        cd = int(kw_row.get("consecutive_days", 0))
                        br = float(kw_row.get("burst_ratio", 0))
                        fig_kw.add_annotation(
                            x=float(kw_row["doc_count"]) + max_dc * 0.05,
                            y=kw_row["keyword"],
                            text=f"burst {br:.1f}x | {cd}天",
                            showarrow=False,
                            font=dict(size=13, color="#aaa"),
                            xanchor="left",
                        )

                    fig_kw.update_layout(
                        height=max(200, len(kw_df) * 50 + 60),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#ccc", size=13),
                        xaxis=dict(title="命中文章数", range=[0, max_dc * 1.5]),
                        yaxis=dict(title=""),
                        margin=dict(l=140, r=140, t=10, b=40),
                        legend=dict(font=dict(size=13), orientation="h", y=-0.15),
                    )
                    st.plotly_chart(fig_kw, use_container_width=True)
                    st.caption(
                        "条形颜色：🔴 burst >= 3.0（强爆发）| 🟠 burst >= 1.5（中度）| 🔵 burst < 1.5（平稳）"
                    )
                else:
                    st.info("该板块暂无活跃 L3 关键词（TF-IDF 候选表中无近期匹配）。")

        # =====================================================================
        # Sub-tab 2: Heat Leaderboard (table with date comparison)
        # =====================================================================
        with v5_sub2:
            _lb_today = _date.today()
            _lb_today_iso = _lb_today.isoformat()

            _compare_opts = {
                "1\u5929\u524d": 1, "3\u5929\u524d": 3,
                "7\u5929\u524d": 7, "14\u5929\u524d": 14,
                "30\u5929\u524d": 30,
            }
            _cmp_label = st.radio(
                "\u5bf9\u6bd4\u57fa\u51c6",
                list(_compare_opts.keys()),
                horizontal=True,
                key="lb_compare_days",
            )
            _cmp_days = _compare_opts[_cmp_label]

            _target_iso = (_lb_today - _timedelta(days=_cmp_days)).isoformat()
            _avail = [d for d in _hist_dates_set if d <= _target_iso]
            _base_date = _avail[-1] if _avail else None

            _base_rank: dict[str, int] = {}
            _base_score: dict[str, float] = {}
            if _base_date:
                _bsnaps = [
                    (r["l2_sector"], float(r["composite_heat"]))
                    for r in qh_data if r["date"] == _base_date
                ]
                _bsnaps.sort(key=lambda x: x[1], reverse=True)
                for _ri, (_sec, _sc) in enumerate(_bsnaps):
                    _base_rank[_sec] = _ri + 1
                    _base_score[_sec] = _sc

            if _base_date:
                _real_gap = (_lb_today - _date.fromisoformat(_base_date)).days
                if _real_gap != _cmp_days:
                    st.caption(
                        f"\u5386\u53f2\u6570\u636e\u6700\u8fd1\u53ef\u7528"
                        f"\u65e5\u671f: {_base_date}"
                        f"\uff08\u5b9e\u9645\u76f8\u8ddd {_real_gap} \u5929\uff09"
                    )

            df_lb = df_radar.sort_values(
                "composite_heat", ascending=False,
            ).reset_index(drop=True)

            _hdr = f"\u8f83{_cmp_label}"
            _th = (
                'padding:10px 8px;font-weight:600;color:#888;'
                'border-bottom:2px solid #444'
            )
            _tbl = (
                '<table style="width:100%;border-collapse:collapse;'
                'font-size:14px;color:#ddd">'
                '<thead><tr>'
                f'<th style="{_th};text-align:left">\u6392\u540d</th>'
                f'<th style="{_th};text-align:left">\u677f\u5757</th>'
                f'<th style="{_th};text-align:right">\u70ed\u5ea6\u5206</th>'
                f'<th style="{_th};text-align:right">{_hdr}</th>'
                f'<th style="{_th};text-align:right">\u60c5\u7eea</th>'
                '</tr></thead><tbody>'
            )

            for idx, row in df_lb.iterrows():
                rank = idx + 1
                sector = row["l2_sector"]
                ch = float(row["composite_heat"])
                sm = float(row["sentiment_momentum"])
                score = ch * 100

                prev_r = _base_rank.get(sector)
                if prev_r is not None:
                    rd = prev_r - rank
                    if rd > 0:
                        rank_html = (
                            f'{rank} <span style="color:#2ECC71;'
                            f'font-weight:bold">\u2191{rd}</span>'
                        )
                    elif rd < 0:
                        rank_html = (
                            f'{rank} <span style="color:#E74C3C;'
                            f'font-weight:bold">\u2193{abs(rd)}</span>'
                        )
                    else:
                        rank_html = (
                            f'{rank} <span style="color:#666">\u2192</span>'
                        )
                else:
                    rd = 0
                    rank_html = (
                        f'{rank} <span style="color:#F39C12;'
                        f'font-weight:bold">NEW</span>'
                    )

                bs = _base_score.get(sector)
                if bs is not None:
                    sd = (ch - bs) * 100
                    if sd > 0.05:
                        delta_html = (
                            f'<span style="color:#2ECC71">+{sd:.1f}</span>'
                        )
                    elif sd < -0.05:
                        delta_html = (
                            f'<span style="color:#E74C3C">{sd:.1f}</span>'
                        )
                    else:
                        delta_html = '<span style="color:#666">0.0</span>'
                else:
                    delta_html = '<span style="color:#666">\u2014</span>'

                if sm > 0.05:
                    sent_html = (
                        f'<span style="color:#2ECC71">{sm:+.2f}</span>'
                    )
                elif sm < -0.05:
                    sent_html = (
                        f'<span style="color:#E74C3C">{sm:+.2f}</span>'
                    )
                else:
                    sent_html = (
                        f'<span style="color:#888">{sm:+.2f}</span>'
                    )

                is_anom = prev_r is not None and abs(rd) >= 3
                row_border = (
                    'border-left:3px solid #F39C12;' if is_anom else ''
                )
                anom_tag = (
                    ' <span style="color:#F39C12;font-size:13px;'
                    'font-weight:bold">\u5f02\u52a8</span>'
                    if is_anom else ''
                )

                _tbl += (
                    f'<tr style="border-bottom:1px solid #333;{row_border}">'
                    f'<td style="padding:10px 8px;white-space:nowrap">'
                    f'{rank_html}</td>'
                    f'<td style="padding:10px 8px;font-weight:bold">'
                    f'{sector}{anom_tag}</td>'
                    f'<td style="padding:10px 8px;text-align:right;'
                    f'font-weight:bold">{score:.1f}</td>'
                    f'<td style="padding:10px 8px;text-align:right">'
                    f'{delta_html}</td>'
                    f'<td style="padding:10px 8px;text-align:right">'
                    f'{sent_html}</td>'
                    f'</tr>'
                )

            _tbl += '</tbody></table>'
            st.markdown(_tbl, unsafe_allow_html=True)
            st.caption(
                "\u6392\u540d\u6309\u7efc\u5408\u70ed\u5ea6\u5206\u964d\u5e8f"
                " \u00b7 \u5f02\u52a8 = \u6392\u540d\u53d8\u5316 \u2265 3 \u4f4d"
            )

        # =====================================================================
        # Sub-tab 3: Sentiment Anomaly Ranking (diverging bar chart)
        # =====================================================================
        with v5_sub3:
            df_anom = df_radar.copy()
            df_anom["abs_momentum"] = df_anom["sentiment_momentum"].abs()
            df_anom = df_anom.sort_values(
                "abs_momentum", ascending=True,
            ).reset_index(drop=True)

            _anom_colors = []
            _anom_hovers = []
            _anom_texts = []
            for _, row in df_anom.iterrows():
                sm = float(row["sentiment_momentum"])
                ch = float(row["composite_heat"])
                mc = int(row.get("mention_count", 0))
                quad = _assign_quadrant(ch, sm)

                if sm > 0:
                    _anom_colors.append("#2ECC71")
                elif sm < 0:
                    _anom_colors.append("#E74C3C")
                else:
                    _anom_colors.append("#666")

                _anom_texts.append(f"{sm:+.3f}")

                kw_lines = ""
                top_kws = row.get("top_l3_keywords", [])
                if isinstance(top_kws, list):
                    for kw in top_kws[:5]:
                        if isinstance(kw, dict):
                            kw_lines += (
                                f"  \u00b7 {kw['keyword']} "
                                f"({kw['doc_count']}\u7bc7, "
                                f"burst {kw['burst_ratio']:.1f}x)<br>"
                            )
                if not kw_lines:
                    kw_lines = "  (\u65e0\u6d3b\u8dc3\u5173\u952e\u8bcd)<br>"

                direction = (
                    "\u60c5\u611f\u8f6c\u6696 \u2191" if sm > 0
                    else "\u60c5\u611f\u8f6c\u51b7 \u2193" if sm < 0
                    else "\u6301\u5e73"
                )
                _anom_hovers.append(
                    f"<b>{row['l2_sector']}</b><br>"
                    f"\u60c5\u611f\u52a8\u91cf: {sm:+.3f} ({direction})<br>"
                    f"\u7efc\u5408\u70ed\u529b: {ch:.3f}<br>"
                    f"\u5f53\u524d\u8c61\u9650: {quad}<br>"
                    f"\u63d0\u53ca\u91cf: {mc}\u7bc7<br>"
                    f"---<br>"
                    f"<b>\u6d3b\u8dc3\u5173\u952e\u8bcd:</b><br>{kw_lines}"
                )

            fig_anom = go.Figure()
            fig_anom.add_trace(go.Bar(
                y=df_anom["l2_sector"].tolist(),
                x=df_anom["sentiment_momentum"].astype(float).tolist(),
                orientation="h",
                marker_color=_anom_colors,
                text=_anom_texts,
                textposition="outside",
                textfont=dict(size=13, color="#ddd"),
                hovertext=_anom_hovers,
                hoverinfo="text",
            ))

            fig_anom.add_vline(x=0, line_color="#555", line_width=1)
            fig_anom.add_vline(
                x=0.1, line_dash="dot", line_color="#2ECC71", opacity=0.3,
            )
            fig_anom.add_vline(
                x=-0.1, line_dash="dot", line_color="#E74C3C", opacity=0.3,
            )

            _max_abs = float(max(df_anom["abs_momentum"].max(), 0.15)) * 1.4

            fig_anom.update_layout(
                height=max(400, len(df_anom) * 35),
                plot_bgcolor="#111111",
                paper_bgcolor="#111111",
                font=dict(color="#ddd", size=13),
                xaxis=dict(
                    title=(
                        "\u2190 \u60c5\u611f\u8f6c\u51b7\u3000\u3000\u3000"
                        "\u60c5\u611f\u52a8\u91cf\u3000\u3000\u3000"
                        "\u60c5\u611f\u8f6c\u6696 \u2192"
                    ),
                    range=[-_max_abs, _max_abs],
                    zeroline=False,
                    gridcolor="rgba(80,80,80,0.3)",
                ),
                yaxis=dict(title=""),
                margin=dict(l=150, r=80, t=30, b=50),
            )

            st.markdown(
                "<div style='font-size:13px;color:#888;margin-bottom:8px'>"
                "\u6309\u60c5\u611f\u52a8\u91cf\u7edd\u5bf9\u503c\u6392\u5e8f"
                "\uff08\u53d8\u5316\u6700\u5927\u5728\u4e0a\u65b9\uff09\u00b7 "
                "\U0001f7e2 \u6b63\u503c = \u60c5\u611f\u8f6c\u6696 \u00b7 "
                "\U0001f534 \u8d1f\u503c = \u60c5\u611f\u8f6c\u51b7 \u00b7 "
                "\u865a\u7ebf = \u00b10.1 \u663e\u8457\u6027\u53c2\u8003\u7ebf"
                "</div>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(fig_anom, use_container_width=True)
    else:
        st.info("暂无数据。请先在侧边栏触发 NLP 流水线，待数据采集完成后刷新。")


# =========================================================================
# Tab 6: ⚡ 共振猎场 (Resonance Arena)
# =========================================================================
with tab6:
    _phase_header(
        6, "共振猎场",
        "D级高动量标的 × 叙事热力 — 双因子共振扫描、裸奔隔离、风口追踪",
    )

    # ------------------------------------------------------------------
    # Helper: percentile without scipy dependency
    # ------------------------------------------------------------------
    def _percentile_rank(arr: list, val: float) -> float:
        if not arr:
            return 50.0
        below = sum(1 for x in arr if x < val)
        equal = sum(1 for x in arr if x == val)
        return (below + 0.5 * equal) / len(arr) * 100

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------
    with st.spinner("🔄 正在加载共振猎场数据…"):
        _core = fetch_core_data()
        _snm      = _core.get("STOCK_NARRATIVE_MAP", {})   # 仅用于 narr_label 展示
        _stl2     = _core.get("STOCK_L2_MAP", {})           # 精确 ticker→L2 映射
        _tic      = _core.get("TIC_MAP", {})
        _l2_etf_map = _core.get("L2_ETF_MAP", {})           # L2 板块 → 代理 ETF
        _ugd = _core.get("USER_GROUPS_DEF", {})
        _d_key = next((k for k in _ugd if k.startswith("D")), None)
        _d_tickers = _ugd.get(_d_key, []) if _d_key else []

    if not _d_tickers:
        st.warning("⚠️ 未找到 D 级标的，请检查核心数据配置。")
    else:
        with st.spinner("🔄 拉取 D 级动量因子（Vol_Z / RS_20d / MA60偏离）…"):
            _d_fac = get_arena_d_factors(tuple(_d_tickers))
            _sh_resp = fetch_narrative_sector_heat(days=7)
            _sh_data = _sh_resp.get("data", [])
            # 拉取 L2 代理 ETF 近 20 日超额收益（板块偏离检测用）
            _etf_tickers_needed = tuple(set(_l2_etf_map.values()))
            _etf_rs20d = get_etf_rs20d(_etf_tickers_needed) if _etf_tickers_needed else {}
            # ⚡ Alpaca 实时价格快照（TTL 60s，覆盖 D 级所有标的）
            _snap_data: dict = get_alpaca_snapshots(tuple(_d_tickers))

        # -- L2 heat lookup (reuse Phase 5 l2l3_data) --
        _l2_heat: dict[str, float] = {}
        _l2_quad: dict[str, str] = {}
        _l2_sent: dict[str, float] = {}
        for _item in l2l3_data:
            _n = _item.get("l2_sector", "")
            _l2_heat[_n] = float(_item.get("composite_heat", 0))
            _l2_quad[_n] = _item.get("quadrant", "")
            _l2_sent[_n] = float(_item.get("sentiment_momentum", 0))

        _sector_z: dict[str, float] = {}
        for _sh in _sh_data:
            _sector_z[_sh["l2_sector"]] = float(_sh.get("z_score", 0))

        # -- Velocity helper --
        _today_iso = _date.today().isoformat()
        _yday_iso = (_date.today() - _timedelta(days=1)).isoformat()

        def _calc_vel(sector: str) -> tuple:
            seq = _qh_by_sector.get(sector, [])
            th = next((x["composite_heat"] for x in seq if x["date"] == _today_iso), None)
            yh = next((x["composite_heat"] for x in seq if x["date"] == _yday_iso), None)
            if th is None or yh is None or float(yh) == 0:
                return "➡️ 稳定", 0.0
            v = (float(th) - float(yh)) / float(yh)
            if v > 0.5:
                return "🔥 突发", v
            if v > 0.2:
                return "📈 加速", v
            if v > -0.1:
                return "➡️ 稳定", v
            return "📉 降温", v

        # ------------------------------------------------------------------
        # Build per-ticker records
        # ------------------------------------------------------------------
        # 预先计算 D 组全体 MinMax 边界（对齐 Page 4 compute_scorecard_d 逻辑）
        _all_vz_vals  = [float(_d_fac.get(t, {}).get("vol_z", 0))   for t in _d_tickers]
        _all_rs_vals  = [float(_d_fac.get(t, {}).get("rs_20d", 0))  for t in _d_tickers]
        _all_m60_vals = [float(_d_fac.get(t, {}).get("ma60_dist", 0)) for t in _d_tickers]

        def _minmax(val, lo, hi):
            """MinMax 归一化到 [0, 1]，区间为零时返回 0.5"""
            if hi <= lo:
                return 0.5
            return max(0.0, min(1.0, (val - lo) / (hi - lo)))

        _vz_lo,  _vz_hi  = min(_all_vz_vals),  max(_all_vz_vals)
        _rs_lo,  _rs_hi  = min(_all_rs_vals),  max(_all_rs_vals)
        _m60_lo, _m60_hi = min(_all_m60_vals), max(_all_m60_vals)

        _recs: list[dict] = []
        for _t in _d_tickers:
            _f = _d_fac.get(_t, {})
            vz = float(_f.get("vol_z", 0))
            rs = float(_f.get("rs_20d", 0))
            m60 = float(_f.get("ma60_dist", 0))

            # MinMax 归一化 + 权重 45 / 35 / 20（对齐后端 compute_scorecard_d）
            _s_rs  = _minmax(rs,  _rs_lo,  _rs_hi)  * 45.0
            _s_vz  = _minmax(vz,  _vz_lo,  _vz_hi)  * 35.0
            _s_ma  = _minmax(m60, _m60_lo, _m60_hi)  * 20.0
            _ds = round(_s_rs + _s_vz + _s_ma, 1)

            _label = _snm.get(_t, "")           # emoji 标签，仅用于 hover 展示
            _l2n = _stl2.get(_t, "")            # 精确 L2 sector（直接查 STOCK_L2_MAP）
            _ch  = _l2_heat.get(_l2n, 0.0)
            _qd  = _l2_quad.get(_l2n, "")
            _sm  = _l2_sent.get(_l2n, 0.0)

            vel_lbl, vel_val = _calc_vel(_l2n) if _l2n else ("—", 0.0)

            _nz = _sector_z.get(_l2n, 0.0)
            _narr_mult = round(1.0 + min(0.3, max(0.0, _nz) * 0.1), 2)

            _recs.append({
                "ticker": _t, "cn_name": _tic.get(_t, _t),
                "narr_label": _label, "l2_name": _l2n,
                "narrative_score": _ch, "quadrant": _qd,
                "sentiment_momentum": _sm,
                "d_score": _ds, "vol_z": vz, "rs_20d": rs, "ma60_dist": m60,
                "vel_label": vel_lbl, "vel_value": vel_val,
                "narr_mult": _narr_mult,
                "adj_score": round(_ds * _narr_mult, 1),
            })

        # ------------------------------------------------------------------
        # Resonance + Naked Detection + Signal Classification
        # ------------------------------------------------------------------
        _all_ds = [r["d_score"] for r in _recs]
        _all_ns = [r["narrative_score"] for r in _recs]

        for _r in _recs:
            # -- Resonance Index --
            mp = _percentile_rank(_all_ds, _r["d_score"])
            nrp = _percentile_rank(_all_ns, _r["narrative_score"])
            raw = math.sqrt(max(mp, 0) * max(nrp, 0))
            m60 = _r["ma60_dist"]
            qm = 1.0 if -10 <= m60 <= 20 else (0.9 if m60 <= 50 else 0.75)
            qv = 1.0 if _r["vol_z"] >= 1.5 else 0.9
            qs = 1.0 if _r["sentiment_momentum"] >= 0 else 0.85
            quality = (qm + qv + qs) / 3.0
            adj = round(raw * quality, 1)
            if adj >= 85:
                tier = "🔥 强共振"
            elif adj >= 70:
                tier = "✅ 共振"
            elif adj >= 50:
                tier = "📊 观察"
            else:
                tier = "⚠️ 弱信号"
            _r["resonance"] = adj
            _r["resonance_tier"] = tier

            # -- Naked Detection --
            _flags: list[str] = []
            if _r["narrative_score"] < 0.2:
                _flags.append("叙事真空")
            if abs(_r["vol_z"]) > 2.5:
                _flags.append("量能异常")
            if _r["rs_20d"] > 8 and _r["vol_z"] < 0:
                _flags.append("价量背离")
            # 板块偏离检测：个股 rs_20d 超跑代理 ETF 10%+ 且 ETF 自身涨幅偏低
            _etf_t = _l2_etf_map.get(_r["l2_name"], "")
            if _etf_t and _etf_rs20d.get(_etf_t) is not None:
                _etf_rs = float(_etf_rs20d[_etf_t])
                if _r["rs_20d"] - _etf_rs > 10:
                    _flags.append("板块偏离")
            _thresh = 3 if _r["narrative_score"] > 0.3 else 2
            _r["is_naked"] = len(_flags) >= _thresh
            _r["naked_flags"] = _flags
            _r["naked_risk"] = (
                "high" if len(_flags) >= 3
                else "medium" if len(_flags) == 2
                else "low"
            )

            # -- Signal Classification (mutually exclusive, priority order) --
            ns = _r["narrative_score"]
            ds = _r["d_score"]
            ma = _r["ma60_dist"]
            qd = _r["quadrant"]
            sm = _r["sentiment_momentum"]
            if _r["is_naked"]:
                _r["signal"] = "⚠️ 裸奔"
            elif ns >= 0.5 and ds >= 60 and -10 <= ma <= 20 and "舆论风口" in qd:
                _r["signal"] = "🔥 双高共振"
            elif ns >= 0.4 and sm > 0 and ds < 60:
                _r["signal"] = "📰 叙事预热"
            elif ds >= 70 and ns < 0.3:
                _r["signal"] = "🚀 动量领先"
            else:
                _r["signal"] = "💤 双低观望"

        # ==================================================================
        # MODULE A: 今日风口摘要栏 (Top 3 cards)
        # ==================================================================
        st.markdown("### 🌊 今日风口摘要")
        _wind_sectors = [
            item for item in l2l3_data
            if float(item.get("composite_heat", 0)) >= 0.5
            and float(item.get("sentiment_momentum", 0)) >= 0.1
        ]
        _wind_sectors.sort(key=lambda x: float(x.get("composite_heat", 0)), reverse=True)
        _wind_top3 = _wind_sectors[:3]

        if _wind_top3:
            cols_a = st.columns(min(len(_wind_top3), 3))
            for ci, ws in enumerate(_wind_top3):
                sec_name = ws.get("l2_sector", "")
                ch_val = float(ws.get("composite_heat", 0))
                sm_val = float(ws.get("sentiment_momentum", 0))
                v_lbl, _ = _calc_vel(sec_name)
                related = sorted(
                    [r for r in _recs if r["l2_name"] == sec_name],
                    key=lambda x: x["resonance"], reverse=True,
                )
                ticker_chips = " ".join(
                    f"<code>{r['ticker']}</code>" for r in related[:5]
                )
                best_txt = (
                    f"（共振最强: {related[0]['ticker']} "
                    f"共振指数 {related[0]['resonance']}）"
                    if related else ""
                )
                sm_color = "#2ECC71" if sm_val > 0 else "#E74C3C"
                card = (
                    f'<div style="background:#161b22;border:1px solid #30363d;'
                    f'border-radius:10px;padding:16px;height:100%">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center;margin-bottom:8px">'
                    f'<span style="font-size:15px;font-weight:700;color:#f0f6fc">'
                    f'🔥 {sec_name}</span>'
                    f'<span style="font-size:14px;color:#F39C12;font-weight:600">'
                    f'热力: {ch_val:.2f}</span></div>'
                    f'<div style="font-size:13px;color:#8b949e;margin-bottom:10px">'
                    f'情感动量: <span style="color:{sm_color}">{sm_val:+.2f}</span>'
                    f'&nbsp; 叙事速度: {v_lbl}</div>'
                    f'<hr style="border-color:#30363d;margin:8px 0">'
                    f'<div style="font-size:13px;color:#8b949e">'
                    f'关联D级标的: {ticker_chips or "无"}</div>'
                    f'<div style="font-size:13px;color:#F39C12;margin-top:4px">'
                    f'{best_txt}</div></div>'
                )
                with cols_a[ci]:
                    st.markdown(card, unsafe_allow_html=True)
        else:
            st.info(
                "📭 今日暂无达到风口阈值的板块"
                "（composite_heat ≥ 0.5 且 sentiment_momentum ≥ 0.1）"
            )

        st.markdown("")

        # ==================================================================
        # MODULE B + C: 散点图 (7:3) + 共振排行
        # ==================================================================
        col_chart, col_rank = st.columns([7, 3])

        # ---------- MODULE B: 2D Resonance Scatter ----------
        with col_chart:
            st.markdown("### 🎯 双因子共振散点图")
            fig_scatter = go.Figure()

            fig_scatter.add_annotation(
                x=0.75, y=85, text="🔥 双高共振", showarrow=False,
                font=dict(size=18, color="rgba(231,76,60,0.15)"),
                xref="x", yref="y",
            )
            fig_scatter.add_annotation(
                x=0.15, y=85, text="🚀 动量领先<br>⚠️ 裸奔嫌疑", showarrow=False,
                font=dict(size=14, color="rgba(243,156,18,0.15)"),
                xref="x", yref="y",
            )
            fig_scatter.add_annotation(
                x=0.75, y=25, text="📰 叙事预热", showarrow=False,
                font=dict(size=18, color="rgba(52,152,219,0.15)"),
                xref="x", yref="y",
            )
            fig_scatter.add_annotation(
                x=0.15, y=25, text="💤 双低观望", showarrow=False,
                font=dict(size=18, color="rgba(136,136,136,0.12)"),
                xref="x", yref="y",
            )
            fig_scatter.add_hline(y=60, line_dash="dot", line_color="#555", opacity=0.5)
            fig_scatter.add_vline(x=0.5, line_dash="dot", line_color="#555", opacity=0.5)

            for _r in _recs:
                ns = _r["narrative_score"]
                ds = _r["d_score"]
                vz = _r["vol_z"]
                m60 = _r["ma60_dist"]
                sig = _r["signal"]

                sz = min(8 + max(0, vz) * 6, 40)

                if not _r["l2_name"]:
                    fill = "#666"
                elif -10 <= m60 <= 20:
                    fill = "#2ECC71"
                elif 20 < m60 <= 50:
                    fill = "#F39C12"
                else:
                    fill = "#E74C3C"

                if sig == "🔥 双高共振":
                    bcolor, bwidth = "gold", 2
                elif sig == "📰 叙事预热":
                    bcolor, bwidth = "#3498DB", 1.5
                elif sig == "⚠️ 裸奔":
                    bcolor, bwidth = "#E74C3C", 1.5
                else:
                    bcolor, bwidth = "#555", 1

                vel_pct = (
                    f" {_r['vel_value']:+.0%}" if _r["vel_value"] != 0 else ""
                )
                hover = (
                    f"<b>{_r['ticker']}</b> | {_r['cn_name']}<br>"
                    f"──────────────────<br>"
                    f"叙事主线: {_r['narr_label'] or '叙事未知'}<br>"
                    f"L2 板块: {_r['l2_name'] or '无'} ({ns:.2f})<br>"
                    f"叙事速度: {_r['vel_label']}{vel_pct}<br>"
                    f"叙事象限: {_r['quadrant'] or '—'}<br>"
                    f"──────────────────<br>"
                    f"动量得分: {ds:.0f} / 100<br>"
                    f"Vol_Z: {vz:+.1f}x<br>"
                    f"RS_20d: {_r['rs_20d']:+.1f}%（超越SPY）<br>"
                    f"MA60偏离: {m60:+.0f}%<br>"
                    f"──────────────────<br>"
                    f"共振指数: {_r['resonance']} {_r['resonance_tier']}<br>"
                    f"信号: {sig}"
                )

                fig_scatter.add_trace(go.Scatter(
                    x=[ns], y=[ds],
                    mode="markers+text",
                    text=[_r["ticker"]],
                    textposition="top center",
                    textfont=dict(size=10, color="#ccc"),
                    marker=dict(
                        size=sz, color=fill, opacity=0.85,
                        line=dict(color=bcolor, width=bwidth),
                    ),
                    hovertext=hover, hoverinfo="text",
                    showlegend=False,
                ))

            fig_scatter.update_layout(
                height=550,
                plot_bgcolor="#0d1117",
                paper_bgcolor="#0d1117",
                font=dict(color="#ddd", size=13),
                xaxis=dict(
                    title="叙事热力分（Narrative Score, 0–1）",
                    range=[-0.05, 1.05],
                    gridcolor="rgba(80,80,80,0.2)",
                    zeroline=False,
                ),
                yaxis=dict(
                    title="D级动量得分（D-Score, 0–100）",
                    range=[-5, 105],
                    gridcolor="rgba(80,80,80,0.2)",
                    zeroline=False,
                ),
                margin=dict(l=60, r=20, t=30, b=60),
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

        # ---------- MODULE C: Ranking Tabs ----------
        with col_rank:
            st.markdown("### 📊 共振排行")
            rt1, rt2, rt3 = st.tabs([
                "🔥 双高共振", "📰 叙事预热", "⚠️ 裸奔隔离",
            ])

            with rt1:
                with st.container(height=500, border=False):
                    _dh = sorted(
                        [r for r in _recs if r["signal"] == "🔥 双高共振"],
                        key=lambda x: x["resonance"], reverse=True,
                    )
                    if not _dh:
                        st.caption("暂无双高共振标的")
                    for _r in _dh:
                        m60c = (
                            "#2ECC71" if -10 <= _r["ma60_dist"] <= 20
                            else "#F39C12" if _r["ma60_dist"] <= 50
                            else "#E74C3C"
                        )
                        # 实时价格 badge
                        _snap = _snap_data.get(_r["ticker"], {})
                        _rt_price = _snap.get("price")
                        _rt_chg = _snap.get("chg_pct")
                        _price_html = ""
                        if _rt_price:
                            _chg_c = "#2ECC71" if (_rt_chg or 0) >= 0 else "#E74C3C"
                            _chg_txt = f"{_rt_chg:+.2f}%" if _rt_chg is not None else ""
                            _price_html = (
                                f'<span style="font-size:13px;color:#f0f6fc;font-weight:600">'
                                f'${_rt_price:.2f}</span>'
                                f'<span style="font-size:13px;color:{_chg_c};margin-left:4px">'
                                f'{_chg_txt}</span>'
                            )
                        st.markdown(
                            f'<div style="background:#161b22;border-radius:8px;'
                            f'padding:10px 12px;margin-bottom:2px;'
                            f'border-left:3px solid gold">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center">'
                            f'<span style="font-weight:700;font-size:14px;'
                            f'color:#f0f6fc">{_r["ticker"]}</span>'
                            f'<div style="display:flex;gap:10px;align-items:center">'
                            f'{_price_html}'
                            f'<span style="font-size:14px;font-weight:700;'
                            f'color:#E74C3C">{_r["resonance"]}</span></div></div>'
                            f'<div style="font-size:13px;color:#8b949e">'
                            f'{_r["cn_name"]} · {_r["narr_label"]}</div>'
                            f'<div style="font-size:13px;color:#8b949e;margin-top:2px">'
                            f'L2热力 {_r["narrative_score"]:.2f} · '
                            f'{_r["vel_label"]} · 动量 {_r["d_score"]:.0f} · '
                            f'<span style="color:{m60c}">MA60 '
                            f'{_r["ma60_dist"]:+.0f}%</span> · '
                            f'<span style="color:#2ECC71">叙事乘数 ×{_r["narr_mult"]:.2f} → {_r["adj_score"]:.0f}分</span>'
                            f'</div></div>',
                            unsafe_allow_html=True,
                        )
                        # ── 叙事共现标签 ──
                        _co_data = get_ticker_cooccurrence(_r["ticker"], days=7)
                        if _co_data:
                            _co_chips = " ".join(
                                f'<span style="background:rgba(52,152,219,0.15);'
                                f'color:#3498DB;border-radius:4px;padding:1px 6px;'
                                f'font-size:13px">{c["l2_sector"]} ×{c["count"]}</span>'
                                for c in _co_data[:4]
                            )
                            st.markdown(
                                f'<div style="font-size:13px;color:#8b949e;'
                                f'padding:4px 12px 6px;margin-bottom:2px">'
                                f'7日板块共现: {_co_chips}</div>',
                                unsafe_allow_html=True,
                            )
                        # ── 驱动新闻折叠区 ──
                        with st.expander(f"📰 {_r['ticker']} 驱动新闻（最新 5 条）", expanded=False):
                            _news = get_alpaca_ticker_news(_r["ticker"], limit=5)
                            if not _news:
                                st.caption("暂无相关新闻数据")
                            for _n in _news:
                                _pub = _n.get("published_at", "")
                                _src = _n.get("source", "alpaca")
                                _url = _n.get("url", "")
                                _hl = _n.get("headline", "")
                                _sm = _n.get("summary", "")
                                _syms = ", ".join(_n.get("symbols", [])[:6])
                                _hl_html = (
                                    f'<a href="{_url}" target="_blank" style="color:#f0f6fc;text-decoration:none">{_hl}</a>'
                                    if _url else _hl
                                )
                                st.markdown(
                                    f'<div style="background:#0d1117;border-radius:6px;'
                                    f'padding:10px 12px;margin-bottom:6px;'
                                    f'border-left:2px solid #F39C12">'
                                    f'<div style="font-size:14px;font-weight:600;color:#f0f6fc;'
                                    f'margin-bottom:4px">'
                                    f'{_hl_html}'
                                    f'</div>'
                                    f'<div style="font-size:13px;color:#8b949e;margin-bottom:4px">'
                                    f'{_sm}</div>'
                                    f'<div style="font-size:13px;color:#555">'
                                    f'{_pub} · {_src}'
                                    f'{(" · 相关: " + _syms) if _syms else ""}'
                                    f'</div></div>',
                                    unsafe_allow_html=True,
                                )
                        st.markdown('<div style="margin-bottom:8px"></div>', unsafe_allow_html=True)

            with rt2:
                with st.container(height=500, border=False):
                    _np_list = sorted(
                        [r for r in _recs if r["signal"] == "📰 叙事预热"],
                        key=lambda x: x["narrative_score"], reverse=True,
                    )
                    if not _np_list:
                        st.caption("暂无叙事预热标的")
                    for _r in _np_list:
                        smc = "#2ECC71" if _r["sentiment_momentum"] > 0 else "#E74C3C"
                        _np_col1, _np_col2 = st.columns([5, 1])
                        with _np_col1:
                            _snap2 = _snap_data.get(_r["ticker"], {})
                            _rt_p2 = _snap2.get("price")
                            _rt_c2 = _snap2.get("chg_pct")
                            _p2_html = ""
                            if _rt_p2:
                                _c2_col = "#2ECC71" if (_rt_c2 or 0) >= 0 else "#E74C3C"
                                _p2_html = (
                                    f'<span style="font-size:13px;color:#f0f6fc;font-weight:600">'
                                    f'${_rt_p2:.2f}</span>'
                                    f'<span style="font-size:13px;color:{_c2_col};margin-left:4px">'
                                    f'{_rt_c2:+.2f}%</span>'
                                    if _rt_c2 is not None else
                                    f'<span style="font-size:13px;color:#f0f6fc;font-weight:600">'
                                    f'${_rt_p2:.2f}</span>'
                                )
                            st.markdown(
                                f'<div style="background:#161b22;border-radius:8px;'
                                f'padding:10px 12px;margin-bottom:6px;'
                                f'border-left:3px solid #3498DB">'
                                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                                f'<span style="font-weight:700;font-size:14px;'
                                f'color:#f0f6fc">{_r["ticker"]}</span>'
                                f'<div style="display:flex;gap:8px;align-items:center">'
                                f'{_p2_html}'
                                f'<span style="font-size:14px;color:#F39C12">'
                                f'{_r["narrative_score"]:.2f}</span></div></div>'
                                f'<div style="font-size:13px;color:#8b949e">'
                                f'{_r["cn_name"]} · {_r["narr_label"]}</div>'
                                f'<div style="font-size:13px;color:#8b949e;margin-top:2px">'
                                f'情感 <span style="color:{smc}">'
                                f'{_r["sentiment_momentum"]:+.2f}</span> · '
                                f'{_r["vel_label"]} · 动量 {_r["d_score"]:.0f}'
                                f'</div></div>',
                                unsafe_allow_html=True,
                            )
                        with _np_col2:
                            if st.button("⭐ 加入", key=f"wl_add_{_r['ticker']}", help="加入 CIO 观察池"):
                                _add_res = add_to_cio_watchlist(_r["ticker"])
                                if _add_res.get("success"):
                                    st.toast(f"✅ {_r['ticker']} 已加入观察池", icon="⭐")
                                else:
                                    st.toast(f"⚠️ 加入失败：{_add_res.get('error','')}", icon="❌")
                    if _np_list:
                        st.markdown(
                            '<div style="font-size:13px;color:#8b949e;margin-top:8px;'
                            'padding:8px;background:rgba(52,152,219,0.08);'
                            'border-radius:6px">'
                            'ℹ️ 叙事预热标的价格尚未跟进，作为左侧布局参考，'
                            '需等待量价确认后再行动。</div>',
                            unsafe_allow_html=True,
                        )

            with rt3:
                with st.container(height=500, border=False):
                    _nk = sorted(
                        [r for r in _recs if r["is_naked"]],
                        key=lambda x: x["d_score"], reverse=True,
                    )
                    if not _nk:
                        st.caption("暂无裸奔标的 ✅")
                    for _r in _nk:
                        risk_c = (
                            "#E74C3C" if _r["naked_risk"] == "high"
                            else "#F39C12" if _r["naked_risk"] == "medium"
                            else "#888"
                        )
                        flags_html = " · ".join(
                            f'<span style="color:#E74C3C">🚩{f}</span>'
                            for f in _r["naked_flags"]
                        )
                        st.markdown(
                            f'<div style="background:#161b22;border-radius:8px;'
                            f'padding:10px 12px;margin-bottom:6px;'
                            f'border-left:3px solid #E74C3C">'
                            f'<div style="display:flex;justify-content:space-between">'
                            f'<span style="font-weight:700;font-size:14px;'
                            f'color:#f0f6fc">{_r["ticker"]}</span>'
                            f'<span style="font-size:13px;color:{risk_c};'
                            f'font-weight:600">{_r["naked_risk"].upper()}</span>'
                            f'</div>'
                            f'<div style="font-size:13px;color:#8b949e">'
                            f'动量 {_r["d_score"]:.0f} · '
                            f'叙事 {_r["narrative_score"]:.2f}</div>'
                            f'<div style="font-size:13px;margin-top:4px">'
                            f'{flags_html}</div></div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        '<div style="background:rgba(231,76,60,0.06);'
                        'border-radius:8px;padding:12px;margin-top:8px;'
                        'font-size:13px;color:#8b949e">'
                        '<b>⚠️ 裸奔隔离区说明</b><br>'
                        '这些标的出现价格动量但缺乏叙事支撑或存在量能异常。<br>'
                        '可能原因：庄股操作 / 纯技术性反弹 / 信息尚未公开传播。<br>'
                        '建议：等待叙事出现后再重新评估，不建议追高入场。</div>',
                        unsafe_allow_html=True,
                    )

        # ==================================================================
        # MODULE D: 叙事5日热力趋势图
        # ==================================================================
        st.markdown("### 📈 叙事 5 日热力趋势")
        _bound_l2s = {r["l2_name"] for r in _recs if r["l2_name"]}
        _5d_dates = sorted({qr["date"] for qr in qh_data})[-5:] if qh_data else []
        _trend_map: dict[str, dict[str, float]] = {}
        for sec in _bound_l2s:
            seq = _qh_by_sector.get(sec, [])
            _trend_map[sec] = {
                r["date"]: float(r["composite_heat"])
                for r in seq if r["date"] in _5d_dates
            }

        if _trend_map and _5d_dates:
            fig_trend = go.Figure()
            for sec, vals in _trend_map.items():
                y_vals = [vals.get(d, None) for d in _5d_dates]
                qd = _l2_quad.get(sec, "")
                if "舆论风口" in qd:
                    lc = "#E74C3C"
                elif "静默潜伏" in qd:
                    lc = "#2ECC71"
                else:
                    lc = "#888"
                tickers_in = [r["ticker"] for r in _recs if r["l2_name"] == sec]
                fig_trend.add_trace(go.Scatter(
                    x=_5d_dates, y=y_vals, name=sec,
                    mode="lines+markers",
                    line=dict(color=lc, width=2),
                    marker=dict(size=5),
                    hovertemplate=(
                        f"<b>{sec}</b><br>"
                        f"D级标的: {', '.join(tickers_in[:5])}<br>"
                        "日期: %{x}<br>热力: %{y:.3f}<extra></extra>"
                    ),
                ))
            fig_trend.update_layout(
                height=250,
                plot_bgcolor="#0d1117",
                paper_bgcolor="#0d1117",
                font=dict(color="#ddd", size=13),
                xaxis=dict(gridcolor="rgba(80,80,80,0.2)"),
                yaxis=dict(
                    title="Composite Heat",
                    gridcolor="rgba(80,80,80,0.2)",
                ),
                margin=dict(l=60, r=20, t=10, b=40),
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02,
                    font=dict(size=13),
                ),
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("暂无趋势数据（需至少 1 天的板块历史快照）。")

        # ==================================================================
        # Narrative Unknown Hint
        # ==================================================================
        _unknown = [r for r in _recs if not r["l2_name"]]
        if _unknown:
            _unk_tickers = ", ".join(r["ticker"] for r in _unknown[:10])
            _unk_suffix = "…" if len(_unknown) > 10 else ""
            st.markdown(
                f'<div style="font-size:13px;color:#8b949e;padding:10px 14px;'
                f'background:rgba(136,136,136,0.06);border-radius:8px;'
                f'margin-top:8px">'
                f'ℹ️ {len(_unknown)} 只D级标的无叙事标签，不参与共振评分。'
                f'如需绑定，请前往「4·词典管理」补充。'
                f'（{_unk_tickers}{_unk_suffix}）</div>',
                unsafe_allow_html=True,
            )

        # ==================================================================
        # ⭐ CIO 观察池 — 持久化追踪「叙事预热」候选升级情况
        # ==================================================================
        st.markdown("---")
        with st.expander("⭐ 我的观察池 — CIO Watchlist", expanded=False):
            _wl_resp = fetch_cio_watchlist()
            _wl_items = _wl_resp.get("data", [])

            # 构建当前信号快照（ticker → signal）
            _cur_signal_map = {r["ticker"]: r["signal"] for r in _recs}

            if not _wl_items:
                st.info("观察池为空。请在「📰 叙事预热」列表中点击「⭐ 加入」将感兴趣的标的加入追踪。")
            else:
                # 批量拉取观察池标的实时价格（与 D 组快照合并）
                _wl_ticker_set = tuple({_wi["ticker"] for _wi in _wl_items} - set(_d_tickers))
                _wl_snap_extra: dict = get_alpaca_snapshots(_wl_ticker_set) if _wl_ticker_set else {}
                _all_snap = {**_snap_data, **_wl_snap_extra}

                st.caption(f"共 {len(_wl_items)} 只标的在追踪中，目标信号：升级为 🔥 双高共振")
                for _wi in _wl_items:
                    _wt = _wi["ticker"]
                    _wa = _wi.get("added_at", "—")
                    _wn = _wi.get("notes", "")
                    _cur_sig = _cur_signal_map.get(_wt, "—（不在D组）")
                    _sig_color = (
                        "#2ECC71" if "双高共振" in _cur_sig
                        else "#F39C12" if "叙事预热" in _cur_sig
                        else "#E74C3C" if "裸奔" in _cur_sig
                        else "#8b949e"
                    )
                    _upgraded = "双高共振" in _cur_sig

                    # 实时价格行
                    _wl_snap = _all_snap.get(_wt, {})
                    _wl_price = _wl_snap.get("price")
                    _wl_chg = _wl_snap.get("chg_pct")
                    _wl_price_row = ""
                    if _wl_price:
                        _wl_chg_c = "#2ECC71" if (_wl_chg or 0) >= 0 else "#E74C3C"
                        _wl_chg_str = f'{_wl_chg:+.2f}%' if _wl_chg is not None else ""
                        _wl_price_row = (
                            f'<div style="font-size:13px;margin-top:3px">'
                            f'实时价格: <span style="color:#f0f6fc;font-weight:600">'
                            f'${_wl_price:.2f}</span>'
                            f'<span style="color:{_wl_chg_c};margin-left:6px">'
                            f'{_wl_chg_str}</span>'
                            f'<span style="color:#555;margin-left:6px;font-size:13px">⚡ Alpaca 实时</span>'
                            f'</div>'
                        )

                    _wl_c1, _wl_c2, _wl_c3 = st.columns([4, 3, 1])
                    _upgraded_html = '<div style="font-size:13px;color:#2ECC71;margin-top:3px">🎉 已达目标信号！</div>' if _upgraded else ""
                    with _wl_c1:
                        st.markdown(
                            f'<div style="background:#161b22;border-radius:8px;'
                            f'padding:10px 12px;border-left:3px solid '
                            f'{"#2ECC71" if _upgraded else "#F39C12"}">'
                            f'<div style="font-weight:700;font-size:15px;color:#f0f6fc">'
                            f'{"🎯 " if _upgraded else ""}{_wt}</div>'
                            f'<div style="font-size:13px;color:#8b949e;margin-top:2px">'
                            f'入池时间: {_wa}</div>'
                            f'<div style="font-size:13px;margin-top:3px">'
                            f'当前信号: <span style="color:{_sig_color}">{_cur_sig}</span>'
                            f'</div>'
                            f'{_wl_price_row}'
                            f'{_upgraded_html}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with _wl_c2:
                        _new_note = st.text_input(
                            "备注", value=_wn,
                            key=f"wl_note_{_wt}",
                            placeholder="输入追踪备注…",
                            label_visibility="collapsed",
                        )
                        if _new_note != _wn:
                            if st.button("💾 保存", key=f"wl_save_{_wt}"):
                                update_cio_watchlist_notes(_wt, _new_note)
                                st.rerun()
                    with _wl_c3:
                        if st.button("🗑️ 移除", key=f"wl_rm_{_wt}"):
                            remove_from_cio_watchlist(_wt)
                            st.rerun()
