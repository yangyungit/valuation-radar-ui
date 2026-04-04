import math
import os
import json
import calendar
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from api_client import fetch_core_data, get_global_data, get_stock_metadata, clear_api_caches
from screener_engine import (
    compute_metrics as _engine_compute_metrics,
    classify_asset,
    classify_all_at_date,
)

st.set_page_config(page_title="资产分拣与白盒初筛", layout="wide", page_icon="🗂️")

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

st.markdown("""
<style>
    .reason-text { font-size: 14px; color: #bbb; line-height: 1.6; }
    .rule-box { border-left: 3px solid; padding: 10px 14px; margin-bottom: 12px; border-radius: 0 6px 6px 0; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  动态分拣四级门槛 (Screener Tiers)
#  漏斗级联：A → B → C → D，通过某级即停止
#  A = 最严格 (三项全过)，D = 最宽松 (单项即入)
#  注：宏观剧本决定四类资产的仓位权重，不介入粗筛逻辑
# ─────────────────────────────────────────────────────────────────
CLASS_META = {
    "A": {
        "label": "A级：压舱石",
        "nickname": "Anchor",
        "icon": "⚓",
        "color": "#3498DB",
        "update_freq": "月/季",
        "criteria": "（股息率 ≥ 1% 或 趋势健康）  |  近1年最大回撤 < 15%  |  与 SPY 相关性 < 0.65",
        "logic": (
            "三重关卡，全部通过方可入列。收益来源灵活：有股息(≥1%)或均线趋势健康均认可，"
            "回撤 < 20% 控制尾部风险，低 SPY 相关性提供组合对冲价值。月/季度评估。"
        ),
    },
    "B": {
        "label": "B级：大猩猩",
        "nickname": "Gorilla",
        "icon": "🦍",
        "color": "#F39C12",
        "update_freq": "月/季",
        "criteria": "市值>$1000亿 | 近3年最大回撤<40% | 价格>MA200 (长线牛熊)",
        "logic": (
            "超大市值护城河+极强的跨周期抗跌能力。"
            "强行将强周期巨头拒签，使其向下流入 C 组赛道。"
        ),
    },
    "C": {
        "label": "C级：时代之王",
        "nickname": "King",
        "icon": "👑",
        "color": "#2ECC71",
        "update_freq": "周",
        "criteria": "RS动量(6M vs SPY)进全域前20%  |  MA20 > MA60 > MA250（站稳主升浪）",
        "logic": (
            "动量最强的进攻矛头，两项全部通过方可入列。"
            "宏观剧本在上游分配仓位时会对 C 级内部的风格进行再偏移，周度评估。"
        ),
    },
    "D": {
        "label": "D级：预备队",
        "nickname": "Scout",
        "icon": "🔭",
        "color": "#9B59B6",
        "update_freq": "日/周",
        "criteria": "(近20天涨幅 > +8% 或 近5天涨幅 > +5%)  且  近60日年化波动率 > 25%",
        "logic": (
            "最宽容的单项关卡：宏观归因尚未明确，但近期资金行为极强。"
            "条件：(近20天涨幅 > +8% 或 近5天涨幅 > +5%) 且 (近60日年化波动率 > 25%)。"
            "强行剔除低波动防守股的短期脉冲假阳性。"
        ),
    },
}

# ─────────────────────────────────────────────────────────────────
#  数据加载
# ─────────────────────────────────────────────────────────────────
core_data = fetch_core_data()
TIC_MAP = core_data.get("TIC_MAP", {})
USER_TICKERS = list(TIC_MAP.keys())

page1_picks = st.session_state.get("page1_macro_recommended", [])
SCREEN_TICKERS = sorted(set(USER_TICKERS + page1_picks))
# SPY 仅用于 RS 排名计算，不参与分拣
DOWNLOAD_TICKERS = sorted(set(SCREEN_TICKERS + ["SPY"]))

with st.spinner("⏳ 正在加载资产价格矩阵..."):
    df = get_global_data(DOWNLOAD_TICKERS, years=3)

with st.spinner("⏳ 正在加载基本面元数据（市值/股息率）..."):
    meta_data = get_stock_metadata(SCREEN_TICKERS)

if df.empty or len(df) < 30:
    st.error("⚠️ 价格数据加载失败，请检查网络或清理缓存后重试。")
    st.stop()

# ─────────────────────────────────────────────────────────────────
#  核心函数
# ─────────────────────────────────────────────────────────────────
def compute_metrics(ticker: str) -> dict:
    """Thin wrapper: delegates to screener_engine using page-level ``df``."""
    return _engine_compute_metrics(ticker, df, spy_col="SPY")


# ─────────────────────────────────────────────────────────────────
#  主页面渲染
# ─────────────────────────────────────────────────────────────────
st.title("🗂️ 资产分拣与白盒初筛 (Dynamic Asset Screener)")
st.caption(
    "基于四级动态分拣门槛的白盒筛选引擎 — "
    "透明展示每一笔资产通过/未通过各关卡的具体数值与判定理由"
)

# ── Section 1：白盒规则说明 ────────────────────────────────────
with st.expander("🛡️ 白盒声明：四级分拣关卡体系 — 点击展开查看所有判定依据"):
    rule_cols = st.columns(4)
    for i, (cls, meta) in enumerate(CLASS_META.items()):
        with rule_cols[i]:
            st.markdown(f"""
            <div class='rule-box' style='border-color:{meta["color"]};'>
                <b style='color:{meta["color"]}; font-size:16px;'>{meta["icon"]} {meta["label"]}</b>
                <div style='font-size:12px; color:#888; margin:4px 0;'>更新频率：{meta["update_freq"]}</div>
                <div style='font-size:14px; color:#F1C40F; margin-bottom:6px;'>{meta["criteria"]}</div>
                <span class='reason-text'>{meta["logic"]}</span>
            </div>
            """, unsafe_allow_html=True)
    st.info(
        "**漏斗逻辑：** A → B → C → D 级联检验，通过某级即停止，"
        "未通过任何关卡则标记为「待分类」等待人工审核。"
        "**宏观剧本** 不介入此处粗筛，仅在下游「首席投资官中枢」中决定各级仓位权重。"
    )

st.markdown("---")

# ── 分拣引擎运行（两遍扫描）─────────────────────────────────────
# 第一遍：计算全资产技术指标
all_metrics: dict = {}
with st.spinner("⚙️ 正在计算分拣指标…"):
    for ticker in SCREEN_TICKERS:
        all_metrics[ticker] = compute_metrics(ticker)

# 计算全域 RS 相对排名（6M 超额收益 vs SPY）
spy_ts = df["SPY"].dropna().astype(float) if "SPY" in df.columns else pd.Series(dtype=float)
spy_6m = (
    (float(spy_ts.iloc[-1]) / float(spy_ts.iloc[-127]) - 1) * 100
    if len(spy_ts) >= 127 and float(spy_ts.iloc[-127]) > 0 else 0.0
)
rs_values: dict = {
    t: m["rs_raw"] - spy_6m
    for t, m in all_metrics.items()
    if m.get("has_data") and m.get("rs_raw") is not None
}
if rs_values:
    rs_series = pd.Series(rs_values)
    n = len(rs_series)
    rs_ranks = (rs_series.rank(ascending=False, method="average") - 1) / n
    for t in all_metrics:
        if t in rs_values:
            all_metrics[t]["rs_rank_pct"] = round(float(rs_ranks[t]), 3)
            all_metrics[t]["rs_rel"]      = round(rs_values[t], 1)

# 第二遍：漏斗分拣
all_assets: dict = {}
for ticker in SCREEN_TICKERS:
    m         = all_metrics[ticker]
    m_info    = meta_data.get(ticker, {"mcap": 0, "div_yield": 0.0})
    mcap      = float(m_info.get("mcap", 0) or 0)
    div_yield = float(m_info.get("div_yield", 0.0) or 0.0)
    cn_name   = TIC_MAP.get(ticker, ticker)

    cls, reason, criteria_detail = classify_asset(m, div_yield, mcap)

    all_assets[ticker] = {
        "cls":         cls,
        "reason":      reason,
        "criteria":    criteria_detail,
        "source":      "用户自选股池" if ticker in TIC_MAP else "宏观定调中心",
        "cn_name":     cn_name,
        "method":      "动态分拣（四级门槛）",
        "div_yield":   div_yield,
        "mcap":        mcap,
        # 以下字段保持与下游 Page 3 的接口兼容
        "has_data":    m.get("has_data", False),
        "is_bullish":  m.get("is_bullish", False),
        "z_score":     m.get("z_score", 0.0),
        "mom20":       m.get("mom20", 0.0),
        "trend_label": m.get("trend_label", "数据不足"),
        "rs_rank_pct": m.get("rs_rank_pct", 1.0),
        "rs_rel":      m.get("rs_rel", 0.0),
        "sortino":     m.get("sortino", 0.0),
        "max_dd":      m.get("max_dd", 0.0),
        "spy_corr":    m.get("spy_corr", 0.0),
    }

# 写入 session_state，供下游 Page 3 消费
st.session_state["abcd_classified_assets"] = all_assets

# 初始化分组选择状态
if "page2_selected_group" not in st.session_state:
    st.session_state["page2_selected_group"] = "A"

# 按类分组，组内按 Z-Score 降序
class_groups: dict = {"A": [], "B": [], "C": [], "D": [], "?": []}
for ticker, info in all_assets.items():
    grp = info["cls"] if info["cls"] in class_groups else "?"
    class_groups[grp].append((ticker, info))

for grp in class_groups:
    class_groups[grp].sort(
        key=lambda x: (not x[1].get("has_data", False), -x[1].get("z_score", -99))
    )

# ── Section 2：分拣结果概览（可点击切换分组）─────────────────
st.header("1️⃣ 分拣结果总览 (Screener Summary)")

_sel = st.session_state["page2_selected_group"]

# CSS：隐形 button 叠在 HTML 大色块上方，捕获点击；:has() 实现悬停增亮
_card_h = 136
_ABCD5 = ("[data-testid='stMainBlockContainer'] "
          "div[data-testid='stHorizontalBlock']"
          ":has(> div:nth-child(5)):not(:has(> div:nth-child(6)))")

_hover_css = []
for _i2 in range(1, 6):
    _hover_css.append(
        f"{_ABCD5} > div:nth-child({_i2}):has(button:hover)"
        f" div[data-testid='stMarkdownContainer'] > div {{"
        f" filter:brightness(1.18)!important; transform:translateY(-3px)!important; }}"
    )

st.markdown(f"""
<style>
{_ABCD5} div[data-testid='stButton'] {{
    height:0!important; position:relative!important; z-index:100!important;
}}
{_ABCD5} div[data-testid='stButton'] button {{
    position:absolute!important; top:-{_card_h}px!important;
    left:0!important; right:0!important; height:{_card_h}px!important;
    opacity:0!important; cursor:pointer!important;
    border:none!important; background:transparent!important;
}}
{_ABCD5} div[data-testid='stMarkdownContainer'] > div {{
    transition: filter 0.15s ease, transform 0.15s ease;
}}
{chr(10).join(_hover_css)}
</style>
""", unsafe_allow_html=True)

sum_cols = st.columns(5)
for i, cls in enumerate(["A", "B", "C", "D", "?"]):
    with sum_cols[i]:
        count    = len(class_groups[cls])
        selected = (cls == _sel)
        if cls in CLASS_META:
            meta  = CLASS_META[cls]
            color = meta["color"]
            bg    = f"{color}30" if selected else f"{color}18"
            bdr   = f"2px solid {color}" if selected else f"1px solid {color}66"
            glow  = f"0 0 14px {color}55" if selected else "none"
            st.markdown(f"""
            <div style='background:{bg}; border:{bdr}; box-shadow:{glow};
                        border-radius:8px; padding:12px; text-align:center;
                        height:{_card_h}px; display:flex; flex-direction:column;
                        justify-content:center; align-items:center; gap:4px;'>
                <div style='font-size:26px;'>{meta["icon"]}</div>
                <div style='font-size:30px; font-weight:bold; color:{color}; line-height:1.1;'>{count}</div>
                <div style='font-size:14px; color:#ddd;'>{meta["label"]}</div>
                <div style='font-size:11px; color:#888; margin-top:2px;'>更新：{meta["update_freq"]}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            bg  = "#2e2e2e" if selected else "#1e1e1e"
            bdr = "2px solid #888" if selected else "1px solid #444"
            st.markdown(f"""
            <div style='background:{bg}; border:{bdr};
                        border-radius:8px; padding:12px; text-align:center;
                        height:{_card_h}px; display:flex; flex-direction:column;
                        justify-content:center; align-items:center; gap:4px;'>
                <div style='font-size:26px;'>❓</div>
                <div style='font-size:30px; font-weight:bold; color:#888; line-height:1.1;'>{count}</div>
                <div style='font-size:14px; color:#aaa;'>待人工审核</div>
            </div>
            """, unsafe_allow_html=True)
        if st.button("", key=f"grp_btn_{cls}", use_container_width=True):
            st.session_state["page2_selected_group"] = cls
            st.rerun()

st.markdown("---")

# ── Section 3：各级别详情（由顶部色块控制）─────────────────────
st.header("2️⃣ 详细分拣清单 (Classified Asset Roster)")


def _badges_html(criteria_detail: dict) -> str:
    parts = []
    for name, (passed, val_str) in criteria_detail.items():
        color = "#2ECC71" if passed else "#E74C3C"
        icon  = "✅" if passed else "❌"
        parts.append(
            f"<span style='color:{color}; font-size:13px; margin-right:10px;'>"
            f"{icon} {name}：{val_str}</span>"
        )
    return "".join(parts)


def render_class_tab(asset_list: list, cls: str):
    if not asset_list:
        st.info("此级别暂无资产通过筛选。")
        return

    if cls in CLASS_META:
        meta = CLASS_META[cls]
        st.markdown(f"""
        <div class='rule-box' style='border-color:{meta["color"]}; margin-bottom:16px;'>
            <b style='color:{meta["color"]}; font-size:16px;'>{meta["icon"]} {meta["label"]} — 入选关卡</b><br>
            <span style='font-size:14px; color:#F1C40F;'>{meta["criteria"]}</span><br>
            <span class='reason-text'>{meta["logic"]}</span>
        </div>
        """, unsafe_allow_html=True)

    h0, h1, h2, h3, h4, h5 = st.columns([0.7, 1.0, 3.2, 1.1, 0.8, 0.9])
    h0.markdown("**Ticker**")
    h1.markdown("**名称**")
    h2.markdown("**分拣结论与关卡详情（白盒）**")
    h3.markdown("**趋势状态**")
    h4.markdown("**Z-Score**")
    h5.markdown("**20日动量**")
    st.markdown("<hr style='border-color:#333; margin:4px 0 8px 0;'>", unsafe_allow_html=True)

    for ticker, info in asset_list:
        col_color = CLASS_META.get(cls, {}).get("color", "#888") if cls in CLASS_META else "#888"
        r0, r1, r2, r3, r4, r5 = st.columns([0.7, 1.0, 3.2, 1.1, 0.8, 0.9])

        r0.markdown(
            f"<span style='color:{col_color}; font-weight:bold; font-size:16px;'>{ticker}</span>",
            unsafe_allow_html=True
        )
        r1.markdown(
            f"<span style='font-size:14px; color:#ccc;'>{info.get('cn_name', '-')}</span>",
            unsafe_allow_html=True
        )

        badges = _badges_html(info.get("criteria", {}))
        r2.markdown(
            f"<div style='font-size:14px; color:#bbb; margin-bottom:4px;'>{info.get('reason', '-')}</div>"
            + (f"<div>{badges}</div>" if badges else ""),
            unsafe_allow_html=True
        )

        if info.get("has_data"):
            trend_color = "#2ECC71" if info.get("is_bullish") else "#E74C3C"
            trend_icon  = "✅" if info.get("is_bullish") else "🔒"
            r3.markdown(
                f"<span style='color:{trend_color}; font-size:14px;'>"
                f"{trend_icon} {info.get('trend_label', '-')}</span>",
                unsafe_allow_html=True
            )
            z = info.get("z_score", 0.0)
            z_color = "#2ECC71" if z > 0.5 else ("#E74C3C" if z < -0.5 else "#F1C40F")
            r4.markdown(
                f"<span style='color:{z_color}; font-size:15px;'>{z:+.2f}</span>",
                unsafe_allow_html=True
            )
            m20 = info.get("mom20", 0.0)
            m20_color = "#2ECC71" if m20 >= 0 else "#E74C3C"
            r5.markdown(
                f"<span style='color:{m20_color}; font-size:15px;'>{m20:+.1f}%</span>",
                unsafe_allow_html=True
            )
        else:
            r3.markdown("<span style='color:#555; font-size:14px;'>数据不足</span>", unsafe_allow_html=True)
            r4.markdown("<span style='color:#555; font-size:15px;'>—</span>", unsafe_allow_html=True)
            r5.markdown("<span style='color:#555; font-size:15px;'>—</span>", unsafe_allow_html=True)

    bullish_n = sum(1 for _, i in asset_list if i.get("is_bullish"))
    data_n    = sum(1 for _, i in asset_list if i.get("has_data"))
    if data_n > 0:
        st.markdown(
            f"<div style='margin-top:12px; font-size:12px; color:#888;'>"
            f"共 {len(asset_list)} 个资产 | "
            f"趋势健康：{bullish_n}/{data_n}（{bullish_n/data_n*100:.0f}%）"
            f"</div>",
            unsafe_allow_html=True
        )


_active_cls = st.session_state["page2_selected_group"]
render_class_tab(class_groups[_active_cls], _active_cls)

# ─────────────────────────────────────────────────────────────────
#  历史分拣名单 — Point-in-Time 回溯
# ─────────────────────────────────────────────────────────────────
_SCREENER_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "screener_history.json")


def _load_screener_history() -> dict:
    try:
        if os.path.exists(_SCREENER_HISTORY_FILE):
            with open(_SCREENER_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_screener_history(history: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_SCREENER_HISTORY_FILE), exist_ok=True)
        with open(_SCREENER_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _fetch_screener_backfill_prices(tickers: tuple) -> pd.DataFrame:
    end   = datetime.now()
    start = end - timedelta(days=365 * 6)
    try:
        raw = yf.download(list(tickers) + ["SPY"], start=start, end=end, progress=False)
        return raw["Close"].ffill().dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _backfill_screener_history(screen_tickers: list, meta_data: dict,
                               tic_map: dict, months_back: int = 24) -> tuple:
    """Re-run classify_asset at each historical month-end (Point-in-Time).

    Returns (saved_count, error_msg).
    """
    all_dl = tuple(sorted(set(screen_tickers)))
    price_df = _fetch_screener_backfill_prices(all_dl)
    if price_df.empty:
        return 0, "历史价格数据下载失败，请检查网络或稍后重试。"

    today = datetime.now()
    y, m = today.year, today.month
    m -= 1
    if m == 0:
        m, y = 12, y - 1

    month_ends: list = []
    for _ in range(months_back):
        last_day = calendar.monthrange(y, m)[1]
        target   = pd.Timestamp(y, m, last_day)
        avail    = price_df.index[price_df.index <= target]
        if len(avail) > 0:
            month_ends.append((f"{y:04d}-{m:02d}", avail[-1]))
        m -= 1
        if m == 0:
            m, y = 12, y - 1

    history = _load_screener_history()
    saved   = 0

    for month_key, me_date in month_ends:
        loc = price_df.index.get_loc(me_date)
        if loc < 120:
            continue

        pit_assets = classify_all_at_date(
            price_df, loc, screen_tickers, meta_data, tic_map=tic_map,
        )

        month_record: dict = {}
        for cls_key in ["A", "B", "C", "D", "?"]:
            tickers_in_cls = [
                t for t, info in pit_assets.items() if info["cls"] == cls_key
            ]
            month_record[cls_key] = {
                "count": len(tickers_in_cls),
                "tickers": sorted(tickers_in_cls),
            }
        history[month_key] = month_record
        saved += 1

    _save_screener_history(history)
    return saved, ""


# ── Section 4：历史分拣名单变化 ─────────────────────────────────
st.markdown("---")
st.header("3️⃣ 历史分拣名单变化 (Screener Roster Drift)")
st.caption(
    "Point-in-Time 回溯：用历史价格数据在每个月末重新执行粗筛分拣逻辑，"
    "展示 ABCD 各级人数的月度变化。市值与股息率使用当前值作为近似。"
)

_bf2_col1, _bf2_col2, _bf2_col3 = st.columns([2, 1, 3])
with _bf2_col1:
    _bf2_months = st.selectbox(
        "回填月数", options=[12, 18, 24, 36, 60], index=2,
        format_func=lambda x: f"过去 {x} 个月",
        key="bf2_months_sel",
        help="选择要回填的历史月份数（月数越多下载时间越长）",
    )
with _bf2_col2:
    _do_bf2 = st.button("🔄 回填历史分拣", use_container_width=True,
                         help="用 yfinance 历史价格在每个月末重新跑粗筛分拣")
with _bf2_col3:
    st.markdown(
        "<div style='font-size:13px; color:#666; padding-top:8px;'>"
        "注：每个月末会对全池资产重新跑 ABCD 分拣（计算 RS/MA/回撤等），"
        "市值和股息率使用当前快照近似。首次下载约需 60-120 秒。</div>",
        unsafe_allow_html=True,
    )

if _do_bf2:
    with st.spinner(f"正在下载 {len(SCREEN_TICKERS)} 只标的约 6 年历史数据并逐月分拣…"):
        _bf2_saved, _bf2_err = _backfill_screener_history(
            SCREEN_TICKERS, meta_data, TIC_MAP, months_back=_bf2_months,
        )
    if _bf2_err:
        st.error(f"回填失败：{_bf2_err}")
    else:
        st.success(f"回填完成！已写入 {_bf2_saved} 个月的历史分拣档案。")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ── 历史数据展示 ─────────────────────────────────────────────────
_scr_history = _load_screener_history()
_CLASS_COLORS = {
    "A": "#3498DB", "B": "#F39C12", "C": "#2ECC71", "D": "#9B59B6", "?": "#888",
}
_CLASS_ICONS = {"A": "⚓", "B": "🦍", "C": "👑", "D": "🔭", "?": "❓"}

if not _scr_history:
    st.info("暂无历史分拣记录。点击上方「回填历史分拣」按钮，一键生成过去 N 个月的档案。", icon="📋")
else:
    _sorted_months = sorted(_scr_history.keys(), reverse=True)

    _header_html = (
        "<div style='display:flex; align-items:center; padding:6px 8px; "
        "border-bottom:2px solid #2a2a2a; font-size:13px; color:#555; font-weight:bold;'>"
        "<div style='width:80px; flex-shrink:0;'>月份</div>"
    )
    for _ck in ["A", "B", "C", "D", "?"]:
        _lbl = CLASS_META[_ck]["label"] if _ck in CLASS_META else "待审核"
        _ico = _CLASS_ICONS[_ck]
        _header_html += (
            f"<div style='width:100px; text-align:center; flex-shrink:0;'>"
            f"{_ico} {_ck if _ck != '?' else '?'}</div>"
        )
    _header_html += "<div style='flex:1; padding-left:8px;'>合计</div></div>"

    _data_rows = ""
    for _idx, _mo in enumerate(_sorted_months):
        _rec   = _scr_history[_mo]
        _bg    = "#111" if _idx % 2 == 0 else "#0d0d0d"
        _row   = (
            f"<div style='display:flex; align-items:center; padding:8px 8px; "
            f"background:{_bg}; border-bottom:1px solid #1a1a1a;'>"
            f"<div style='width:80px; font-size:13px; font-weight:bold; "
            f"color:#ccc; flex-shrink:0;'>{_mo}</div>"
        )
        _total = 0
        # 表格按月份降序（新在上）；红绿数字 = 该行月份相对「日历上的上一个月」的增减
        _prev_mo_rec = None
        if _idx + 1 < len(_sorted_months):
            _prev_mo_rec = _scr_history[_sorted_months[_idx + 1]]
        for _ck in ["A", "B", "C", "D", "?"]:
            _cnt   = _rec.get(_ck, {}).get("count", 0)
            _total += _cnt
            _color = _CLASS_COLORS[_ck]

            _delta_html = ""
            if _prev_mo_rec is not None:
                _prev = _prev_mo_rec.get(_ck, {}).get("count", 0)
                _diff = _cnt - _prev
                if _diff > 0:
                    _delta_html = f"<span style='color:#2ECC71; font-size:13px; margin-left:4px;'>+{_diff}</span>"
                elif _diff < 0:
                    _delta_html = f"<span style='color:#E74C3C; font-size:13px; margin-left:4px;'>{_diff}</span>"

            _row += (
                f"<div style='width:100px; text-align:center; flex-shrink:0;'>"
                f"<span style='font-size:15px; font-weight:bold; color:{_color};'>{_cnt}</span>"
                f"{_delta_html}</div>"
            )
        _row += (
            f"<div style='flex:1; padding-left:8px; font-size:14px; color:#888;'>"
            f"{_total}</div></div>"
        )
        _data_rows += _row

    st.markdown(
        f"<div style='border:1px solid #333; border-radius:8px; overflow:hidden;'>"
        f"{_header_html}{_data_rows}</div>",
        unsafe_allow_html=True,
    )

    # 可展开查看某月具体标的
    with st.expander("🔍 展开查看各月具体标的清单"):
        _detail_month = st.selectbox(
            "选择月份", options=_sorted_months, key="scr_hist_detail_month",
        )
        if _detail_month in _scr_history:
            _dm = _scr_history[_detail_month]
            for _ck in ["A", "B", "C", "D", "?"]:
                _info = _dm.get(_ck, {})
                _tks  = _info.get("tickers", [])
                _cnt  = _info.get("count", 0)
                _icon = _CLASS_ICONS[_ck]
                _color = _CLASS_COLORS[_ck]
                _lbl  = CLASS_META[_ck]["label"] if _ck in CLASS_META else "待人工审核"
                st.markdown(
                    f"<div style='margin-bottom:8px;'>"
                    f"<span style='color:{_color}; font-weight:bold; font-size:14px;'>"
                    f"{_icon} {_lbl}（{_cnt}）</span>"
                    f"<span style='color:#888; font-size:13px; margin-left:12px;'>"
                    f"{', '.join(_tks) if _tks else '—'}</span></div>",
                    unsafe_allow_html=True,
                )
