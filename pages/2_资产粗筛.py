import streamlit as st
import pandas as pd
import numpy as np
from api_client import fetch_core_data, get_global_data, get_stock_metadata

st.set_page_config(page_title="资产分拣与白盒初筛", layout="wide", page_icon="🗂️")

with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🔄 清理缓存并重新下载数据"):
        st.cache_data.clear()
        st.success("缓存已清除！")
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
        "criteria": "市值 > $1000亿  |  索提诺比率 > 1.0  |  MA20 > MA60（趋势健康）",
        "logic": (
            "超大市值护城河 + 优秀的风险调整收益 + 趋势健康，三项全部通过。"
            "代表具有宽护城河的核心基石标的。月/季度评估。"
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
        "criteria": "近20天涨幅 > +8%  或  近5天涨幅 > +5%（短期动量突破信号）",
        "logic": (
            "最宽容的单项关卡：宏观归因尚未明确，但近期资金行为极强。"
            "是趋势爆发前的早期布局候选，日/周动态追踪，止损纪律第一。"
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
    df = get_global_data(DOWNLOAD_TICKERS, years=2)

with st.spinner("⏳ 正在加载基本面元数据（市值/股息率）..."):
    meta_data = get_stock_metadata(SCREEN_TICKERS)

if df.empty or len(df) < 30:
    st.error("⚠️ 价格数据加载失败，请检查网络或清理缓存后重试。")
    st.stop()

# ─────────────────────────────────────────────────────────────────
#  核心函数
# ─────────────────────────────────────────────────────────────────
def compute_metrics(ticker: str) -> dict:
    """计算单个资产的所有分拣所需量化指标。"""
    base = {"has_data": False, "ticker": ticker}
    if ticker not in df.columns:
        return base
    ts = df[ticker].dropna().astype(float)
    if len(ts) < 60:
        return {**base, "data_len": len(ts)}

    curr     = float(ts.iloc[-1])
    data_len = len(ts)

    ma20  = float(ts.rolling(20).mean().iloc[-1])
    ma60  = float(ts.rolling(60).mean().iloc[-1])
    ma250_val = float(ts.rolling(250).mean().iloc[-1]) if data_len >= 250 else None

    z_score = 0.0
    if data_len >= 250:
        mean250 = float(ts.rolling(250).mean().iloc[-1])
        std250  = float(ts.rolling(250).std().iloc[-1])
        z_score = round((curr - mean250) / std250, 2) if std250 > 0 else 0.0

    mom20 = round((curr / float(ts.iloc[-21]) - 1) * 100, 2) if data_len > 20 and ts.iloc[-21] > 0 else 0.0
    mom5  = round((curr / float(ts.iloc[-6])  - 1) * 100, 2) if data_len > 5  and ts.iloc[-6]  > 0 else 0.0

    rs_raw = None
    if data_len >= 127 and float(ts.iloc[-127]) > 0:
        rs_raw = round((curr / float(ts.iloc[-127]) - 1) * 100, 2)

    ts_1y    = ts.iloc[-252:] if data_len >= 252 else ts
    roll_max = ts_1y.cummax().replace(0, np.nan)
    drawdowns = (ts_1y - roll_max) / roll_max * 100
    max_dd = round(abs(float(drawdowns.min())), 1) if not drawdowns.isna().all() else 0.0

    # SPY 相关性（周度，近1年）
    spy_corr = 0.0
    w_asset = ts.resample("W").last().pct_change().dropna()
    if "SPY" in df.columns:
        w_spy  = df["SPY"].dropna().astype(float).resample("W").last().pct_change().dropna()
        common = w_asset.index.intersection(w_spy.index)
        if len(common) >= 26:
            c = float(w_asset.loc[common].corr(w_spy.loc[common]))
            spy_corr = round(c, 2) if not np.isnan(c) else 0.0

    # 索提诺比率（近2年，4% 无风险利率）
    daily_rets = ts.pct_change().dropna()
    sortino = 0.0
    if len(daily_rets) >= 60:
        ann_ret  = (1 + float(daily_rets.mean())) ** 252 - 1
        downside = daily_rets[daily_rets < 0]
        down_std = float(downside.std()) * np.sqrt(252) if len(downside) > 5 else 1.0
        sortino  = round((ann_ret - 0.04) / down_std, 2) if down_std > 0 else 0.0

    return {
        "has_data":     True,
        "data_len":     data_len,
        "curr":         curr,
        "ma20":         round(ma20, 2),
        "ma60":         round(ma60, 2),
        "ma250":        round(ma250_val, 2) if ma250_val is not None else None,
        "is_bullish":   ma20 > ma60,
        "full_uptrend": (ma250_val is not None and ma20 > ma60 > ma250_val),
        "z_score":      z_score,
        "mom20":        mom20,
        "mom5":         mom5,
        "rs_raw":       rs_raw,
        "rs_rank_pct":  1.0,
        "rs_rel":       0.0,
        "max_dd":       max_dd,
        "spy_corr":     spy_corr,
        "sortino":      sortino,
        "trend_label":  "趋势健康 (MA20>MA60)" if ma20 > ma60 else "趋势走弱 (MA20<MA60)",
    }


def classify_asset(m: dict, div_yield: float, mcap: float) -> tuple:
    """
    漏斗级联分拣：A → B → C → D → ?
    返回 (class_str, reason_str, criteria_detail_dict)
    criteria_detail: {名称: (passed: bool, value_str: str)}
    """
    if not m.get("has_data"):
        return "?", "数据不足，无法完成分拣", {}

    # ── A 级 ──────────────────────────────────────────────────────
    # 收益入口灵活：有股息(≥1%)或均线趋势健康二选一
    # 回撤与相关性保持严格：压舱石的核心护城河
    a_income = div_yield >= 1.0 or m["is_bullish"]
    a_dd     = m["max_dd"] < 15.0
    a_corr   = m["spy_corr"] < 0.65
    div_tag  = f"股息 {div_yield:.1f}%" if div_yield >= 1.0 else "趋势健康(无股息)"
    detail_a = {
        "收益来源(股息/趋势)": (a_income, f"{div_tag}（需股息≥1% 或 MA20>MA60）"),
        "1年最大回撤":        (a_dd,     f"{m['max_dd']:.1f}%（需<15%）"),
        "SPY相关性":          (a_corr,   f"{m['spy_corr']:.2f}（需<0.65）"),
    }
    if a_income and a_dd and a_corr:
        reason = (
            f"通过A级三重关卡：{div_tag}，"
            f"1年最大回撤 {m['max_dd']:.1f}% < 15%，"
            f"SPY相关性 {m['spy_corr']:.2f} < 0.65（低相关，对冲价值高）"
        )
        return "A", reason, detail_a

    # ── B 级 ──────────────────────────────────────────────────────
    b_mcap    = mcap > 1e11
    b_sortino = m["sortino"] > 1.0
    b_trend   = m["is_bullish"]
    detail_b = {
        "市值":   (b_mcap,    f"${mcap/1e9:.0f}B（需>$1000亿）"),
        "索提诺": (b_sortino, f"{m['sortino']:.2f}（需>1.0）"),
        "趋势":   (b_trend,   f"MA20 {'>' if b_trend else '<'} MA60"),
    }
    if b_mcap and b_sortino and b_trend:
        reason = (
            f"通过B级三重关卡：市值 ${mcap/1e9:.0f}B > $1000亿，"
            f"索提诺比率 {m['sortino']:.2f} > 1.0，"
            f"MA20({m['ma20']:.1f}) > MA60({m['ma60']:.1f}) 趋势健康"
        )
        return "B", reason, detail_b

    # ── C 级 ──────────────────────────────────────────────────────
    c_rs    = m["rs_rank_pct"] <= 0.20
    c_trend = m["full_uptrend"]
    detail_c = {
        "RS动量排名": (c_rs,    f"全域前 {m['rs_rank_pct']*100:.0f}%（需≤20%）"),
        "主升浪":     (c_trend, f"MA20>MA60>MA250：{'✅' if c_trend else '❌'}"),
    }
    if c_rs and c_trend:
        reason = (
            f"通过C级双重关卡：RS动量排名全域前 {m['rs_rank_pct']*100:.0f}%，"
            f"站稳 MA20>MA60>MA250 主升浪"
        )
        return "C", reason, detail_c

    # ── D 级 ──────────────────────────────────────────────────────
    d_mom20 = m["mom20"] > 8.0
    d_mom5  = m["mom5"] > 5.0
    detail_d = {
        "20日涨幅": (d_mom20, f"{m['mom20']:+.1f}%（需>+8%）"),
        "5日涨幅":  (d_mom5,  f"{m['mom5']:+.1f}%（需>+5%）"),
    }
    if d_mom20 or d_mom5:
        reason = (
            f"通过D级动量关卡：20日涨幅 {m['mom20']:+.1f}%，"
            f"5日涨幅 {m['mom5']:+.1f}%，近期资金介入信号强烈"
        )
        return "D", reason, detail_d

    # ── 未通过任何关卡 ─────────────────────────────────────────────
    fail_parts = []
    if not a_income:  fail_parts.append(f"股息率{div_yield:.1f}%且趋势走弱")
    if not a_dd:   fail_parts.append(f"回撤{m['max_dd']:.1f}%过大")
    if not b_mcap: fail_parts.append(f"市值${mcap/1e9:.0f}B不足")
    if not c_rs:   fail_parts.append(f"RS排名{m['rs_rank_pct']*100:.0f}%靠后")
    if not d_mom20 and not d_mom5: fail_parts.append(f"动量不足({m['mom20']:+.1f}%)")
    reason = "未通过任何分拣关卡：" + "，".join(fail_parts[:4])
    return "?", reason, {}


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

# 按类分组，组内按 Z-Score 降序
class_groups: dict = {"A": [], "B": [], "C": [], "D": [], "?": []}
for ticker, info in all_assets.items():
    grp = info["cls"] if info["cls"] in class_groups else "?"
    class_groups[grp].append((ticker, info))

for grp in class_groups:
    class_groups[grp].sort(
        key=lambda x: (not x[1].get("has_data", False), -x[1].get("z_score", -99))
    )

# ── Section 2：分拣结果概览 ────────────────────────────────────
st.header("1️⃣ 分拣结果总览 (Screener Summary)")

sum_cols = st.columns(5)
for i, cls in enumerate(["A", "B", "C", "D", "?"]):
    with sum_cols[i]:
        count = len(class_groups[cls])
        if cls in CLASS_META:
            meta = CLASS_META[cls]
            st.markdown(f"""
            <div style='background:{meta["color"]}1A; border:1px solid {meta["color"]};
                        border-radius:8px; padding:12px; text-align:center;'>
                <div style='font-size:24px;'>{meta["icon"]}</div>
                <div style='font-size:28px; font-weight:bold; color:{meta["color"]};'>{count}</div>
                <div style='font-size:14px; color:#aaa;'>{meta["label"]}</div>
                <div style='font-size:12px; color:#888; margin-top:4px;'>更新：{meta["update_freq"]}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background:#2a2a2a; border:1px solid #555;
                        border-radius:8px; padding:12px; text-align:center;'>
                <div style='font-size:24px;'>❓</div>
                <div style='font-size:28px; font-weight:bold; color:#888;'>{count}</div>
                <div style='font-size:14px; color:#aaa;'>待人工审核</div>
            </div>
            """, unsafe_allow_html=True)

st.markdown("---")

# ── Section 3：各级别详情 Tab ──────────────────────────────────
st.header("2️⃣ 详细分拣清单 (Classified Asset Roster)")

tab_labels = [
    f"⚓ A级 ({len(class_groups['A'])})",
    f"🦍 B级 ({len(class_groups['B'])})",
    f"👑 C级 ({len(class_groups['C'])})",
    f"🔭 D级 ({len(class_groups['D'])})",
    f"❓ 待分类 ({len(class_groups['?'])})",
]
tabs = st.tabs(tab_labels)


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


def render_class_tab(tab, asset_list: list, cls: str):
    with tab:
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


for i, cls in enumerate(["A", "B", "C", "D", "?"]):
    render_class_tab(tabs[i], class_groups[cls], cls)
