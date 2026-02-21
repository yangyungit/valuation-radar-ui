import streamlit as st
from api_client import fetch_core_data

st.set_page_config(page_title="Moltbot 宏观雷达", layout="wide", page_icon="📡")

st.title("📡 Moltbot Investment System (UI Terminal)")
st.caption("Architecture: Microservices API Decoupled")

# 在首页静默测试 API 连接
with st.spinner("正在与云端核心计算引擎建立加密连接..."):
    core_data = fetch_core_data()

if core_data:
    st.success("✅ 核心引擎握手成功！数据流已打通。")
    st.info("👈 请从左侧边栏选择战术面板进行操作。")
    
    st.markdown("---")
    st.markdown("### 📊 系统运行状态")
    st.markdown(f"- **总监控资产数量**: `{len(core_data.get('TIC_MAP', {}))} 只`")
    st.markdown(f"- **战术阵型分组**: `{len(core_data.get('USER_GROUPS_DEF', {}))} 组`")
else:
    st.error("🚨 无法连接到核心引擎，请联系架构师检查 Google Cloud API 状态。")