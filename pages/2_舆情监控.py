import streamlit as st
from api_client import clear_api_caches

st.set_page_config(page_title="词频统计与标的发现", layout="wide", page_icon="📊")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 轻量刷新（仅刷新 API 数据）"):
        clear_api_caches()
        st.success("API 缓存已刷新！历史价格数据保留。")
        st.rerun()
    if st.button("🗑️ 全局缓存重置（含历史价格）"):
        st.cache_data.clear()
        st.success("全部缓存已清除！")
        st.rerun()

st.title("📊 词频统计与标的发现 (Word Frequency & Ticker Discovery)")
st.caption(
    "本页面将用于聚合研报、新闻、社交媒体中的关键词词频统计，"
    "自动发现高频提及标的并为下游 D 组筛选提供候选因子。"
)

st.markdown("---")

st.info(
    "**功能开发中** — 词频统计模块正在建设中，计划功能包括：\n\n"
    "- 研报 / 新闻标题关键词词频热力图\n"
    "- 高频提及标的自动识别与标的池扩展建议\n"
    "- 词频趋势作为 D 组筛选的辅助因子\n\n"
    "当前 ABCD 分类与评分功能已迁移至 **4 同类资产竞技场** 页面一体化运行。",
    icon="🚧",
)
