import streamlit as st
from api_client import fetch_core_data
from health_checker import (
    run_all_checks, CRITICAL, ERROR, WARNING, INFO, OK,
    SEVERITY_ICON, SEVERITY_LABEL, SEVERITY_ORDER,
)

st.set_page_config(page_title="Moltbot 宏观雷达", layout="wide", page_icon="📡")

st.title("📡 Moltbot Investment System (UI Terminal)")
st.caption("Architecture: Microservices API Decoupled")

# ------------------------------------------------------------------
# 原有核心连接测试
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# 质检员仪表盘
# ------------------------------------------------------------------
st.markdown("---")

# Sidebar refresh button
with st.sidebar:
    st.markdown("---")
    if st.button("🔄 重新质检", use_container_width=True):
        run_all_checks.clear() if hasattr(run_all_checks, "clear") else None
        st.rerun()

# Run checks (cached 5 min via @st.cache_data in the caller wrapper below)
@st.cache_data(ttl=300, show_spinner=False)
def _cached_checks():
    return run_all_checks()

with st.spinner("🔍 质检员正在巡检系统 …"):
    report = _cached_checks()

counts = report["counts"]
n_critical = counts.get(CRITICAL, 0)
n_error = counts.get(ERROR, 0)
n_warning = counts.get(WARNING, 0)
n_info = counts.get(INFO, 0)
n_ok = counts.get(OK, 0)
n_issues = n_critical + n_error + n_warning

# ---------- Overall health banner ----------
if n_critical > 0:
    _banner_color = "#5c1a1a"
    _banner_border = "#e74c3c"
    _banner_text = "系统存在严重故障，请立即处理"
    _banner_icon = "🚨"
elif n_error > 0:
    _banner_color = "#5c3a1a"
    _banner_border = "#e67e22"
    _banner_text = "系统存在错误，部分功能可能不可用"
    _banner_icon = "⚠️"
elif n_warning > 0:
    _banner_color = "#4a4a1a"
    _banner_border = "#f1c40f"
    _banner_text = "系统运行中，存在告警需关注"
    _banner_icon = "📋"
else:
    _banner_color = "#1a3d1a"
    _banner_border = "#27ae60"
    _banner_text = "所有检查项通过，系统运行正常"
    _banner_icon = "✅"

st.markdown(f"""
<div style="background:{_banner_color}; border-left:4px solid {_banner_border};
            padding:14px 20px; border-radius:6px; margin-bottom:16px;">
  <span style="font-size:16px; font-weight:600;">
    {_banner_icon} 质检员报告 &nbsp;—&nbsp; {_banner_text}
  </span>
  <span style="float:right; font-size:13px; opacity:0.7;">
    {report['timestamp']} · {report['elapsed_ms']:.0f}ms · 缓存 5min
  </span>
</div>
""", unsafe_allow_html=True)

# ---------- Summary metric cards ----------
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("🔴 严重", n_critical)
col2.metric("🟠 错误", n_error)
col3.metric("🟡 警告", n_warning)
col4.metric("🔵 提示", n_info)
col5.metric("🟢 通过", n_ok)

# ---------- Category-by-category detail ----------
CATEGORY_ICONS = {
    "后端连通": "🌐", "API契约": "📜", "数据完整": "💾",
    "行情数据": "📈", "依赖环境": "📦", "舆情引擎": "🗞️",
    "页面完整": "📄", "代码冲突": "🔀", "质检系统": "🔧",
    "API密钥": "🔑",
}

CATEGORY_ORDER = [
    "后端连通", "API契约", "API密钥", "数据完整", "行情数据",
    "依赖环境", "舆情引擎", "页面完整", "代码冲突", "质检系统",
]

categories = report.get("categories", {})
cat_summary = report.get("cat_summary", {})

sorted_cats = sorted(
    categories.keys(),
    key=lambda c: (SEVERITY_ORDER.get(cat_summary.get(c, OK), 99),
                   CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99),
)

for cat in sorted_cats:
    items = categories[cat]
    worst = cat_summary.get(cat, OK)
    icon = CATEGORY_ICONS.get(cat, "🔹")
    sev_icon = SEVERITY_ICON.get(worst, "")

    n_pass = sum(1 for i in items if i["severity"] == OK)
    n_total = len(items)
    n_issues_cat = n_total - n_pass - sum(1 for i in items if i["severity"] == INFO)

    if n_issues_cat > 0:
        badge = f"{sev_icon} {n_issues_cat} 项异常"
    else:
        badge = f"🟢 {n_pass}/{n_total} 通过"

    default_open = worst in (CRITICAL, ERROR)

    with st.expander(f"{icon} **{cat}**　{badge}", expanded=default_open):
        for item in sorted(items, key=lambda x: SEVERITY_ORDER.get(x["severity"], 99)):
            sev = item["severity"]
            s_icon = SEVERITY_ICON.get(sev, "")
            s_label = SEVERITY_LABEL.get(sev, sev)
            msg = item["message"]
            detail = item.get("detail", "")
            name = item["name"]
            ms = item.get("elapsed_ms", 0)

            ms_tag = f"  `{ms:.0f}ms`" if ms > 0 else ""

            if sev == OK:
                st.markdown(f"&emsp;{s_icon} **{name}** — {msg}{ms_tag}")
            elif sev == INFO:
                st.markdown(f"&emsp;{s_icon} **{name}** — {msg}{ms_tag}")
            else:
                st.markdown(f"&emsp;{s_icon} **{name}** — {msg}{ms_tag}")
                if detail:
                    st.markdown(
                        f"&emsp;&emsp;<span style='font-size:13px; opacity:0.7;'>"
                        f"↳ {detail}</span>",
                        unsafe_allow_html=True,
                    )
