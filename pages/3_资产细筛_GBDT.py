"""GBDT 选股并联页 — 镜像 3_资产细筛.py 结构，打分器换成 GBDT + SHAP。

与原 arena 页并排运行：同一批 universe、同一时点结果可对比。
删除 = 删本文件 + 删 api_client 里 gbdt_* 函数，原 arena 页无感。
"""
import streamlit as st
import pandas as pd
import calendar
import yfinance as yf
from _yf_session import YF_SESSION
from datetime import datetime, timedelta
from api_client import (
    fetch_core_data, fetch_active_universe, get_global_data,
    get_stock_metadata, fetch_current_regime,
    gbdt_score as _api_gbdt_score,
    fetch_gbdt_history as _api_fetch_gbdt_history,
    save_gbdt_state as _api_save_gbdt_state,
    IS_PROD_REMOTE,
)

_GBDT_SAVE_N = 10
_BF_MONTHS   = 60

_core_data       = fetch_core_data()
_Z_SEED_TICKERS  = set(_core_data.get("Z_SEED_TICKERS", []))

st.set_page_config(page_title="GBDT 选股", layout="wide", page_icon="🤖")

if IS_PROD_REMOTE:
    st.info(
        "🌐 **生产环境** — 连接 Render 后端。",
        icon="ℹ️",
    )

# ─────────────────────────────────────────────────────────────────
#  全局样式（复用 arena 样式名）
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .podium-gold   { background: linear-gradient(135deg,#3d2f00,#1a1200);
                     border: 2px solid #FFD700; border-radius:12px; padding:20px;
                     text-align:center; position:relative; }
    .podium-silver { background: linear-gradient(135deg,#2a2a2a,#111);
                     border: 2px solid #C0C0C0; border-radius:12px; padding:20px;
                     text-align:center; }
    .podium-bronze { background: linear-gradient(135deg,#2d1a0a,#111);
                     border: 2px solid #CD7F32; border-radius:12px; padding:20px;
                     text-align:center; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
#  赛道元信息（对齐 3_资产细筛.py）
# ─────────────────────────────────────────────────────────────────
CLASS_META: dict = {
    "A": {"label": "A级：压舱石",     "icon": "⚓", "color": "#2ECC71"},
    "B": {"label": "B级：大猩猩",     "icon": "🦍", "color": "#F39C12"},
    "C": {"label": "C级：时代之王",   "icon": "👑", "color": "#E74C3C"},
    "D": {"label": "D级：预备队",     "icon": "🚀", "color": "#9B59B6"},
    "Z": {"label": "Z级：现金流堡垒", "icon": "🏦", "color": "#1ABC9C"},
}

_PODIUM_MEDALS = [
    ("🥇", "#FFD700", "podium-gold",   "冠军"),
    ("🥈", "#C0C0C0", "podium-silver", "亚军"),
    ("🥉", "#CD7F32", "podium-bronze", "季军"),
]

# SHAP 因子组 → 颜色 / 中文名
_SHAP_GROUP_META: dict = {
    "momentum":     {"cn": "动量",   "color": "#E74C3C"},
    "quality":      {"cn": "质量",   "color": "#3498DB"},
    "value_income": {"cn": "估值/股息","color": "#2ECC71"},
    "vol_dd":       {"cn": "波动/回撤","color": "#F39C12"},
    "scale_liq":    {"cn": "规模/流动","color": "#9B59B6"},
    "macro_sens":   {"cn": "宏观敏感","color": "#1ABC9C"},
    "regime":       {"cn": "剧本权重","color": "#E67E22"},
    "category":     {"cn": "类别特征","color": "#95A5A6"},
    "other":        {"cn": "其他",   "color": "#7F8C8D"},
}


# ─────────────────────────────────────────────────────────────────
#  辅助函数
# ─────────────────────────────────────────────────────────────────
def _lazy_subtab_nav(key: str, options: list, default: str | None = None,
                     accent: str = "#9B59B6") -> str:
    if not options:
        return ""
    default_value = default if default in options else options[0]
    if st.session_state.get(key) not in options:
        st.session_state[key] = default_value
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    cols = st.columns(len(options))
    for idx, option in enumerate(options):
        active = st.session_state.get(key) == option
        marker = f"lazy-subtab-{key}-{idx}".replace("_", "-")
        text_color   = accent if active else "#c9d1d9"
        border_color = accent if active else "rgba(139,148,158,0.32)"
        bottom_width = "3px" if active else "1px"
        font_weight  = "700" if active else "600"
        bg_color     = f"{accent}14" if active else "transparent"
        with cols[idx]:
            st.markdown(
                f"<style>"
                f"div[data-testid='stColumn']:has(#{marker}) "
                f"[data-testid='stButton'] button{{"
                f"background:{bg_color} !important;"
                f"border:0 !important;"
                f"border-bottom:{bottom_width} solid {border_color} !important;"
                f"border-radius:0 !important; box-shadow:none !important;"
                f"color:{text_color} !important; font-weight:{font_weight} !important;"
                f"min-height:42px !important; padding:7px 8px 9px 8px !important;"
                f"}}</style>"
                f"<span id='{marker}' style='display:none'></span>",
                unsafe_allow_html=True,
            )
            if st.button(option, key=f"{key}_btn_{idx}",
                         use_container_width=True, type="secondary"):
                st.session_state[key] = option
                st.rerun()
    st.markdown(
        "<div style='height:1px;background:rgba(139,148,158,0.24);margin:-1px 0 18px 0;'></div>",
        unsafe_allow_html=True,
    )
    return st.session_state[key]


def _shap_bars_html(shap: dict, max_abs: float = None) -> str:
    """把 SHAP 组级贡献渲成正/负小条形图，内嵌 HTML。"""
    if not shap:
        return "<span style='color:#555;font-size:12px;'>—</span>"
    items = sorted(shap.items(), key=lambda x: abs(x[1]), reverse=True)
    if max_abs is None or max_abs <= 0:
        max_abs = max(abs(v) for _, v in items) or 1.0
    parts = []
    for g, v in items[:5]:
        gm = _SHAP_GROUP_META.get(g, {"cn": g, "color": "#888"})
        bar_w  = min(int(abs(v) / max_abs * 60), 60)
        color  = gm["color"] if v >= 0 else "#888"
        sign   = "+" if v >= 0 else "−"
        parts.append(
            f"<div style='display:flex;align-items:center;gap:4px;margin:1px 0;font-size:11px;'>"
            f"<span style='color:#777;width:60px;flex-shrink:0;'>{gm['cn']}</span>"
            f"<div style='width:{bar_w}px;height:6px;background:{color};"
            f"border-radius:3px;'></div>"
            f"<span style='color:{color};font-weight:bold;'>{sign}{abs(v):.2f}</span>"
            f"</div>"
        )
    return "".join(parts)


def _render_gbdt_podium(recs: list, cls: str) -> None:
    """渲染 GBDT Top 3 颁奖台（SHAP bars 代替因子 pills）。"""
    meta  = CLASS_META[cls]
    cols  = st.columns(3)
    for i, (medal, medal_color, css_class, title) in enumerate(_PODIUM_MEDALS):
        if i >= len(recs):
            with cols[i]:
                st.markdown(
                    "<div style='border:1px dashed #333;border-radius:12px;"
                    "padding:20px;text-align:center;color:#555;font-size:13px;'>"
                    "暂无数据</div>",
                    unsafe_allow_html=True,
                )
            continue
        rec   = recs[i]
        score = float(rec.get("score", 0.0))
        shap  = rec.get("shap") or {}
        max_abs = max((abs(v) for v in shap.values()), default=1.0)
        shap_html = _shap_bars_html(shap, max_abs)
        with cols[i]:
            st.markdown(f"""
            <div class='{css_class}'>
                <div style='font-size:32px;margin-bottom:4px;'>{medal}</div>
                <div style='font-size:11px;color:{medal_color};font-weight:bold;
                            letter-spacing:1px;margin-bottom:10px;'>{title}</div>
                <div style='font-size:26px;font-weight:bold;color:#eee;'>
                    {rec.get('ticker', '?')}
                </div>
                <div style='font-size:11px;color:#aaa;margin-bottom:10px;'>
                    {rec.get('name', '')}
                </div>
                <div style='font-size:34px;font-weight:bold;color:{medal_color};
                            margin-bottom:4px;'>
                    {score:.0f}
                </div>
                <div style='font-size:10px;color:#888;margin-bottom:14px;'>
                    GBDT 百分位 / 100
                </div>
                <hr style='border-color:#333;margin:8px 0;'>
                <div style='font-size:11px;text-align:left;'>
                    <div style='color:#888;margin-bottom:6px;font-size:10px;'>
                        SHAP 组级贡献（正=推高分）
                    </div>
                    {shap_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


def _render_gbdt_leaderboard(recs: list, cls: str) -> None:
    """渲染 GBDT 完整排行榜 + SHAP 展开。"""
    meta = CLASS_META[cls]
    if not recs:
        st.info("暂无排行榜数据。")
        return
    st.markdown(f"#### {meta['icon']} {meta['label']} — 完整排行榜")
    for i, rec in enumerate(recs, 1):
        score = float(rec.get("score", 0.0))
        shap  = rec.get("shap") or {}
        gate_closed = False
        if isinstance(rec, dict):
            gate_closed = rec.get("gate_status") == "closed"

        score_bar = int(score * 0.6)
        row_bg = "#1a1a1a" if i % 2 == 0 else "#141414"
        with st.container():
            left, right = st.columns([3, 2])
            with left:
                st.markdown(
                    f"<div style='background:{row_bg};border-radius:8px;padding:8px 12px;"
                    f"display:flex;align-items:center;gap:12px;'>"
                    f"<span style='color:#555;font-size:13px;width:24px;'>{i}</span>"
                    f"<div style='flex:1;'>"
                    f"<span style='font-weight:bold;color:#eee;font-size:14px;'>"
                    f"{rec.get('ticker','?')}</span>"
                    f"<span style='color:#888;font-size:12px;margin-left:8px;'>"
                    f"{rec.get('name','')}</span>"
                    f"</div>"
                    f"<div style='text-align:right;'>"
                    f"<div style='color:{meta['color']};font-weight:bold;font-size:18px;'>"
                    f"{score:.0f}</div>"
                    f"<div style='background:#1e1e1e;border-radius:4px;height:6px;"
                    f"width:80px;margin-top:4px;'>"
                    f"<div style='background:{meta['color']};border-radius:4px;height:6px;"
                    f"width:{score_bar}px;'></div></div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
            with right:
                if shap:
                    st.markdown(
                        "<div style='font-size:11px;color:#888;'>SHAP</div>"
                        + _shap_bars_html(shap, None),
                        unsafe_allow_html=True,
                    )


# ─────────────────────────────────────────────────────────────────
#  历史渲染（镜像 _render_monthly_top10）
# ─────────────────────────────────────────────────────────────────
def _compute_streaks_gbdt(history: dict, cls: str) -> dict:
    sorted_months = sorted(k for k in history)
    prev_tickers: set = set()
    prev_streaks: dict = {}
    result: dict = {}
    for mo in sorted_months:
        cls_raw = history[mo].get(cls, {})
        recs = cls_raw.get("tickers", []) if isinstance(cls_raw, dict) else []
        cur_tickers = {r["ticker"] for r in recs[:10] if isinstance(r, dict)}
        cur_streaks = {
            tk: prev_streaks.get(tk, 0) + 1 if tk in prev_tickers else 1
            for tk in cur_tickers
        }
        result[mo] = cur_streaks
        prev_tickers = cur_tickers
        prev_streaks = cur_streaks
    return result


def _streak_html(streak: int) -> str:
    if streak >= 6:
        return (f"<span style='background:#F39C12;color:#000;font-size:12px;"
                f"font-weight:bold;padding:0 4px;border-radius:3px;margin-left:3px;'>"
                f"{streak}月</span>")
    if streak >= 3:
        return (f"<span style='background:#2ECC71;color:#000;font-size:12px;"
                f"font-weight:bold;padding:0 4px;border-radius:3px;margin-left:3px;'>"
                f"{streak}月</span>")
    if streak >= 1:
        return (f"<span style='font-size:12px;color:#555;margin-left:3px;'>{streak}月</span>")
    return ""


def _render_history_tab(history: dict, cls: str) -> None:
    hm = CLASS_META[cls]
    sorted_months = sorted(history.keys(), reverse=True)
    cls_months = [mo for mo in sorted_months if cls in history[mo]]
    if not cls_months:
        st.info(f"{hm['icon']} {hm['label']} 暂无 GBDT 历史记录，点上方「回填 GBDT 历史」生成。")
        return

    streaks_map = _compute_streaks_gbdt(history, cls)
    medals_color = ["#FFD700", "#C0C0C0", "#CD7F32"]

    # 表头
    TH = "display:flex;align-items:center;padding:6px 8px;border-bottom:2px solid #2a2a2a;font-size:13px;color:#555;font-weight:bold;"
    header = (
        f"<div style='{TH}'>"
        f"<div style='width:80px;flex-shrink:0;'>月份</div>"
        f"<div style='flex:1;padding-left:4px;'>🥇 冠军</div>"
        f"<div style='flex:1;padding-left:4px;'>🥈 亚军</div>"
        f"<div style='flex:1;padding-left:4px;'>🥉 季军</div>"
        f"<div style='flex:2;padding-left:4px;color:#666;'>#4—#10</div>"
        f"</div>"
    )
    rows_html = ""
    for idx, mo in enumerate(cls_months):
        cls_raw = history[mo].get(cls, {})
        recs = cls_raw.get("tickers", []) if isinstance(cls_raw, dict) else []
        gate_closed = isinstance(cls_raw, dict) and cls_raw.get("gate_status") == "closed"
        gate_reason = cls_raw.get("gate_reason", "") if isinstance(cls_raw, dict) else ""
        mo_streaks = streaks_map.get(mo, {})
        bg = "#111" if idx % 2 == 0 else "#0d0d0d"

        row = (
            f"<div style='display:flex;align-items:center;padding:8px 8px;"
            f"background:{bg};border-bottom:1px solid #1a1a1a;'>"
            f"<div style='width:80px;font-size:13px;font-weight:bold;"
            f"color:{hm['color']};flex-shrink:0;'>{mo}"
        )
        if gate_closed:
            row += f"<div style='font-size:10px;color:#E74C3C;'>🔒 {gate_reason[:20]}</div>"
        row += "</div>"

        for ri in range(3):
            if ri < len(recs):
                rec = recs[ri]
                tk = rec.get("ticker", "?")
                nm = rec.get("name", "")[:16]
                sc = rec.get("score", 0.0)
                streak = mo_streaks.get(tk, 0)
                mc = medals_color[ri]
                row += (
                    f"<div style='flex:1;display:flex;align-items:baseline;gap:4px;"
                    f"min-width:0;padding-left:4px;'>"
                    f"<span style='font-size:14px;font-weight:bold;color:#eee;flex-shrink:0;'>{tk}</span>"
                    f"<span style='font-size:12px;color:#888;overflow:hidden;text-overflow:ellipsis;"
                    f"white-space:nowrap;'>{nm}</span>"
                    f"<span style='font-size:12px;color:{mc};font-weight:bold;flex-shrink:0;'>"
                    f"{sc:.0f}</span>"
                    + _streak_html(streak) +
                    f"</div>"
                )
            else:
                row += "<div style='flex:1;font-size:13px;color:#333;padding-left:4px;'>—</div>"

        rest = recs[3:10]
        if rest:
            rest_items = "".join(
                f"<span style='color:#666;white-space:nowrap;'>"
                f"<span style='color:#555;'>#{ri2}</span> {r.get('ticker','?')}</span>"
                for ri2, r in enumerate(rest, start=4)
            )
            row += (
                f"<div style='flex:2;display:flex;flex-wrap:wrap;gap:4px 10px;"
                f"align-items:baseline;padding-left:4px;font-size:12px;'>"
                + rest_items + "</div>"
            )
        else:
            row += "<div style='flex:2;font-size:13px;color:#333;padding-left:4px;'>—</div>"
        row += "</div>"
        rows_html += row

    st.markdown(
        f"<div style='border:1px solid {hm['color']}44;border-radius:8px;"
        f"overflow:hidden;margin-top:12px;'>{header}{rows_html}</div>",
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────
#  回填入口
# ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _fetch_backfill_prices_gbdt(tickers: tuple) -> tuple:
    all_dl = list(tickers) + ["SPY"]
    end   = datetime.now()
    start = end - timedelta(days=365 * 6)
    try:
        raw      = yf.download(all_dl, start=start, end=end, progress=False, session=YF_SESSION)
        price_df = raw["Close"].ffill().dropna(how="all")
        vol_df   = raw["Volume"].ffill().fillna(0)
        return price_df, vol_df
    except Exception:
        return pd.DataFrame(), pd.DataFrame()


def _backfill_gbdt_history(all_tickers: list, months_back: int = 60,
                            monthly_probs: dict = None,
                            warmup_months: int = 12) -> tuple[int, str]:
    """下载历史价格 → 组月度 specs → 调后端 gbdt/score 批量打分。

    镜像 _backfill_arena_history 逻辑，但打分换成 GBDT（后端内部落 gbdt_history）。
    """
    price_df, vol_df = _fetch_backfill_prices_gbdt(tuple(sorted(all_tickers)))
    if price_df.empty or len(price_df) < 120:
        return 0, "历史价格下载失败或数据量不足"

    total_months = months_back + warmup_months
    today        = datetime.now().date()
    month_ends: list = []
    for i in range(total_months + 2):
        d = today.replace(day=1) - timedelta(days=i * 28)
        d = d.replace(day=1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        me = d.replace(day=last_day)
        me_ts = pd.Timestamp(me)
        if me_ts > price_df.index[-1]:
            continue
        if me_ts < price_df.index[0] + pd.Timedelta(days=120):
            break
        month_key = me.strftime("%Y-%m")
        if not any(mk == month_key for mk, _ in month_ends):
            month_ends.append((month_key, me_ts))

    month_ends = sorted(set(month_ends), key=lambda x: x[0], reverse=True)[:total_months]
    month_ends = sorted(month_ends, key=lambda x: x[0])

    warmup_keys = {mk for mk, _ in month_ends[:warmup_months]}

    month_specs: list = []
    for month_key, me_ts in month_ends:
        try:
            loc = price_df.index.get_loc(me_ts)
        except KeyError:
            idx_arr = price_df.index.searchsorted(me_ts)
            loc = int(min(idx_arr, len(price_df) - 1))
        if loc < 120:
            continue
        _m_probs = (monthly_probs or {}).get(month_key, {})
        month_specs.append({
            "month_key":    month_key,
            "date_idx":     int(loc),
            "macro_scores": _m_probs,
            "is_warmup":    month_key in warmup_keys,
        })

    if not month_specs:
        return 0, "无有效月份可回填"

    resp = _api_gbdt_score(
        price_df=price_df,
        vol_df=vol_df if not vol_df.empty else None,
        month_specs=month_specs,
        z_seed_tickers=list(_Z_SEED_TICKERS),
        arena_save_n=_GBDT_SAVE_N,
    )

    gbdt_records_resp = resp.get("gbdt_records", {})
    saved = len(gbdt_records_resp)

    if not resp.get("success"):
        err = resp.get("error", "未知错误")
        if resp.get("partial"):
            done  = resp.get("completed_chunks", 0)
            total = resp.get("total_chunks", 0)
            return saved, f"部分成功（{done}/{total} 批，已落盘 {saved} 个月）：{err}"
        return 0, f"后端 GBDT 打分失败：{err}"

    # 持久化 A/B 守擂状态
    for grade in ("A", "B"):
        state_key   = f"conv_state_{grade.lower()}"
        holders_key = f"conv_holders_{grade.lower()}"
        st_v   = resp.get(state_key, {})
        hold_v = resp.get(holders_key, [])
        if st_v or hold_v:
            _api_save_gbdt_state(grade, st_v, hold_v)

    return saved, ""


# ─────────────────────────────────────────────────────────────────
#  侧边栏
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🤖 GBDT 打分控制台")
    st.markdown("---")
    st.caption(
        "GBDT 并联打分器 — 与「3_资产细筛」同一批 universe，"
        "打分用 LightGBM + SHAP 代替锚点归一化，结果独立存 gbdt_history 表。"
    )
    st.markdown("---")
    st.header("🛠️ 缓存管理")
    if st.button("🔄 清除 GBDT 历史缓存"):
        _api_fetch_gbdt_history.clear()
        _fetch_backfill_prices_gbdt.clear()
        st.success("GBDT 缓存已清除")
        st.rerun()
    if st.button("🗑️ 清除所有页面缓存"):
        st.cache_data.clear()
        st.success("所有缓存已清除")
        st.rerun()

# ─────────────────────────────────────────────────────────────────
#  页面标题
# ─────────────────────────────────────────────────────────────────
st.title("🤖 GBDT 选股（并联打分器）")
st.caption(
    "LightGBM 学习因子组合 → GBDT 百分位得分 → SHAP 组级贡献可解释 → "
    "独立存 gbdt_history（删本页不影响 arena 原页）"
)

# ─────────────────────────────────────────────────────────────────
#  加载 universe + 价格
# ─────────────────────────────────────────────────────────────────
_core_live = fetch_core_data()
_MY_POOL_TIC_MAP = _core_live.get("TIC_MAP", {})
_active_universe = fetch_active_universe()

if _active_universe:
    _SCREEN_TICKERS = sorted(_active_universe.keys())
    _TIC_MAP = {
        tk: (_MY_POOL_TIC_MAP.get(tk) or _active_universe[tk].get("name") or tk)
        for tk in _SCREEN_TICKERS
    }
else:
    _TIC_MAP = _MY_POOL_TIC_MAP
    _SCREEN_TICKERS = sorted(set(_TIC_MAP.keys()))

# ─────────────────────────────────────────────────────────────────
#  主选项卡：按赛道
# ─────────────────────────────────────────────────────────────────
_GRADE_OPTIONS = ["⚓ A", "🦍 B", "👑 C", "🚀 D", "🏦 Z"]
_sel = _lazy_subtab_nav("gbdt_grade_tab", _GRADE_OPTIONS, accent="#00BCD4")
_CLS = _sel.split()[-1]

hm  = CLASS_META[_CLS]
st.markdown(
    f"<div style='background:{hm.get('bg', '#111')};border:1px solid {hm['color']}44;"
    f"border-radius:10px;padding:12px 20px;margin-bottom:16px;'>"
    f"<span style='font-size:22px;'>{hm['icon']}</span> "
    f"<span style='font-size:18px;font-weight:bold;color:{hm['color']};'>"
    f"{hm['label']}</span>"
    f"<span style='font-size:12px;color:#666;margin-left:12px;'>GBDT 打分器</span>"
    f"</div>",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────
#  回填控制区
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
bf_col1, bf_col2 = st.columns([1, 3])
with bf_col1:
    _do_backfill = st.button(
        "🔄 回填 GBDT 历史",
        use_container_width=True,
        help="用 yfinance 历史价格 → GBDT 月度打分，回填过去 60 个月并落盘 gbdt_history。",
    )
with bf_col2:
    st.markdown(
        "<div style='font-size:13px;color:#666;padding-top:8px;'>"
        "固定回填过去 60 个月（含 12 个月热身期）。"
        "首次约 120-300 秒（模型训练 + 5 年价格下载）。"
        "后端已内部去重，重复点击不覆盖已有月份（等价 upsert）。</div>",
        unsafe_allow_html=True,
    )

if _do_backfill:
    with st.spinner(
        f"正在下载 {len(_SCREEN_TICKERS)} 只标的约 6 年历史价格 → GBDT 月度打分…"
        f"（{_BF_MONTHS + 12} 个月含热身）"
    ):
        _regime_resp = fetch_current_regime()
        _monthly_probs = (
            _regime_resp.get("horsemen_monthly_probs") or {}
        )
        _saved, _err = _backfill_gbdt_history(
            all_tickers=_SCREEN_TICKERS,
            months_back=_BF_MONTHS,
            monthly_probs=_monthly_probs,
            warmup_months=12,
        )
    if _err and "部分成功" in _err:
        st.warning(f"⚠️ 回填{_err}。前面批次已持久化，可稍后再点补剩余。", icon="⚠️")
    elif _err:
        st.error(f"回填失败：{_err}")
    else:
        st.success(f"回填完成！已写入 {_saved} 个月的 GBDT 历史档案。")
        _api_fetch_gbdt_history.clear()
        st.rerun()

# ─────────────────────────────────────────────────────────────────
#  历史月度 Top 10
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"### 📅 {hm['icon']} {hm['label']} — GBDT 历史月度 Top 10")
st.caption(
    "纵向追踪每月末 GBDT 打分排名（百分位 0-100）。"
    "「SHAP 贡献」列展示当月最强因子组方向。"
    "点击颁奖台展开 SHAP 详细拆解。"
)

_gbdt_history = _api_fetch_gbdt_history()

if not _gbdt_history:
    st.info("暂无 GBDT 历史记录。点击上方「回填 GBDT 历史」生成。", icon="📋")
else:
    # ── 最近月颁奖台 ────────────────────────────────────────────
    _sorted_months = sorted(_gbdt_history.keys(), reverse=True)
    _cls_months    = [mo for mo in _sorted_months if _CLS in _gbdt_history[mo]]

    if _cls_months:
        _latest_mo  = _cls_months[0]
        _latest_rec = _gbdt_history[_latest_mo].get(_CLS, {})
        _latest_tickers = (
            _latest_rec.get("tickers", []) if isinstance(_latest_rec, dict)
            else _latest_rec or []
        )
        if _latest_tickers:
            _gate_closed = (
                isinstance(_latest_rec, dict)
                and _latest_rec.get("gate_status") == "closed"
            )
            st.markdown(f"#### 🏆 最新月（{_latest_mo}）赛道翘楚 — Top 3")
            if _gate_closed:
                st.warning(
                    f"🔒 闸门关闭：{_latest_rec.get('gate_reason','')}"
                    " — 本月 GBDT 打分完成但守擂未选股。",
                    icon="🔒",
                )
            _render_gbdt_podium(_latest_tickers[:3], _CLS)
            st.markdown("---")

            # Top 10 展开
            with st.expander(f"展开 {_latest_mo} 完整 Top 10", expanded=False):
                _render_gbdt_leaderboard(_latest_tickers[:10], _CLS)

    # ── 历史月度列表 ─────────────────────────────────────────────
    st.markdown(f"#### 📋 全部历史月（{len(_cls_months)} 个月）")
    _render_history_tab(_gbdt_history, _CLS)
