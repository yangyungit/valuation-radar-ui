import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from api_client import (
    fetch_macro_radar_timeseries,
    fetch_etf_meta,
    fetch_dynasty_leaders,
    fetch_theme_holdings_status,
    get_global_data,
)
import holdings_viz as hv

st.set_page_config(page_title="板块王朝", layout="wide")

st.markdown("""
<style>
    .insight-box { border-left: 4px solid #3498DB; background-color: #1a1a1a; padding: 15px; border-radius: 5px; margin-bottom: 20px; margin-top: 20px; }
    .insight-title { font-weight: bold; color: #3498DB; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; }
    .insight-section { margin-top: 10px; font-size: 14px; color: #ddd; }
    .tag-bull { background-color: rgba(46, 204, 113, 0.2); color: #2ECC71; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .tag-bear { background-color: rgba(231, 76, 60, 0.2); color: #E74C3C; padding: 2px 6px; border-radius: 4px; font-size: 13px; font-weight: bold; }
    .logic-text { color: #aaa; font-style: italic; margin-left: 5px; }
    .key-point { font-weight: bold; color: #fff; }
</style>
""", unsafe_allow_html=True)

_DYNASTY_TAB_WINDOWS = ["3Y", "5Y", "10Y"]

with st.sidebar:
    if st.button("🔄 强制刷新"):
        fetch_macro_radar_timeseries.clear()
        fetch_etf_meta.clear()
        fetch_dynasty_leaders.clear()
        fetch_theme_holdings_status.clear()
        get_global_data.clear()
        st.rerun()

with st.spinner("📊 加载王朝时序数据..."):
    _dynasty_ts_by_window = {
        w: fetch_macro_radar_timeseries(window=w, profile="dynasty")
        for w in _DYNASTY_TAB_WINDOWS
    }
    _etf_meta = fetch_etf_meta()

_holdings_status = fetch_theme_holdings_status()
_holdings_items = (_holdings_status.get("items") or {}) if _holdings_status.get("success") else {}

_all_groups = sorted({
    p.get("group", "")
    for _ts in _dynasty_ts_by_window.values()
    if _ts.get("success")
    for p in (_ts.get("tickers", {}) or {}).values()
    if p.get("group", "")
})
# D-ext（净值回测扩展票）不进组别 multiselect，只由「D 组扩展版」checkbox 控制并入选仓池
_all_groups_display = [g for g in _all_groups if not g.startswith("D-ext")]
_default_groups = [
    g for g in ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"]
    if g in _all_groups_display
]

with st.sidebar:
    selected_groups = st.multiselect("显示资产组别：", _all_groups_display, default=_default_groups)
    _d_selected = any(g.startswith("D:") for g in selected_groups)
    _use_dext = False
    if _d_selected:
        _use_dext = st.checkbox(
            "D 组扩展版(+SOXX/URNM/COPX/XHB)", value=False,
            help="仅并入王朝接力净值实验台的选仓池，不进染色图母体。"
                 "SOXX≈SMH、XHB≈ITB 高度重叠;COPX 铜矿是真新赛道;URNM 2019-12 上市。",
        )

st.title("👑 板块王朝 (Dynasty Relay)")
st.caption("月末板块排名 · 王朝期识别 · ETF 轮动净值")

st.markdown("### 👑 板块王朝接力图 (Dynasty Relay) — 月末 Top1/Top3 染色")
st.caption(
    "**规则**:每月末在 25 个板块内做横截面标准化与排名,**Top1 = 🥇 金 / Top2-3 = 🥈 银 / 其他 = ⚪ 灰** · "
    "**加冕门槛**:Top1 + RS_252d > 0(年化跑赢 SPY)才戴金,否则降为灰——熊市无王 · "
    "**主图排序指标 king_score = 1.0×Z(RS_252d) + 0.8×Z(log10 ADV_63d)** —— 两项都**只在这 25 个板块内**做横截面 Z-Score(不掺美债/BTC 等跨资产,否则小众盘容量惩罚被摊薄),RS 用真实美股交易日 252 日动量。**容量项把 URA/TAN 这类小众主题盘压下去**,机构盘(XL*/SMH/IGV)容量项加分 · "
    "**ADV 逐月动态**:每月用当月过去 63 日 (Close × Volume) 均值,**不是用当前快照穿越历史** · "
    "**用途**:找「时代之王」——连续戴金且容量充足 = 真王朝。hover 里有当月 ADV_63d + 当前 AUM 快照(AUM 历史 yfinance 拿不到,只展示不进算法)"
)

_dynasty_window = st.radio(
    "时间跨度",
    options=_DYNASTY_TAB_WINDOWS,
    index=_DYNASTY_TAB_WINDOWS.index("5Y"),
    horizontal=True,
    key="dynasty_window",
    help="月末快照：3Y/5Y/10Y 约对应 36/60/120 个格子",
)

_dyn_tab1, _dyn_tab2 = st.tabs(["👑 王朝接力图", "🏆 王朝龙头股"])

with _dyn_tab1:
    if not selected_groups:
        st.info("👈 请在侧边栏勾选至少一个组别以渲染王朝图")
    else:
        _dyn_ts = _dynasty_ts_by_window.get(_dynasty_window, {}) or {}
        if not _dyn_ts.get("success"):
            st.warning(f"⚠️ {_dynasty_window} 时序数据暂不可用:{_dyn_ts.get('error', '未知错误')}")
        else:
            _dyn_tickers = _dyn_ts.get("tickers", {}) or {}
            _dyn_dates_raw = _dyn_ts.get("dates", []) or []
            _picked_d = {
                tk: p for tk, p in _dyn_tickers.items()
                if p.get("group", "") in selected_groups
            }
            if not _picked_d or not _dyn_dates_raw:
                st.warning(f"⚠️ {_dynasty_window}:选中组别在时序数据中无可用 ticker")
            else:
                _dyn_idx = pd.to_datetime(_dyn_dates_raw, errors="coerce")
                _d_rs = pd.DataFrame(
                    {tk: p.get("rs", []) for tk, p in _picked_d.items()},
                    index=_dyn_idx,
                ).astype(float)
                _d_king = pd.DataFrame(
                    {tk: p.get("king_score", []) for tk, p in _picked_d.items()},
                    index=_dyn_idx,
                ).astype(float)
                _d_adv_hist = pd.DataFrame(
                    {tk: p.get("adv_63d", []) for tk, p in _picked_d.items()},
                    index=_dyn_idx,
                ).astype(float)
                _d_name_map = {tk: p.get("name", tk) for tk, p in _picked_d.items()}
                _king_w = _dyn_ts.get("king_score_weights", {"rs": 1.0, "cap": 0.8})
                _dyn_asof = pd.to_datetime(_dyn_ts.get("asof"), errors="coerce")

                _etf_info = _etf_meta.get("tickers", {}) if _etf_meta.get("success") else {}

                def _fmt_usd(x):
                    if x is None or not isinstance(x, (int, float)) or x <= 0:
                        return "—"
                    if x >= 1e9:
                        return f"${x/1e9:.1f}B"
                    elif x >= 1e6:
                        return f"${x/1e6:.0f}M"
                    else:
                        return f"${x/1e3:.0f}k"

                # 王朝接力净值用价格：dynasty ETF 不全在基础 tickers，单独拉
                _dyn_px = get_global_data(sorted(_picked_d.keys()) + ["SPY"], years=10)
                _dyn_price_cache: dict = {}
                _dyn_spy_wk = pd.DataFrame()
                if _dyn_px is not None and not _dyn_px.empty:
                    _dyn_wk = _dyn_px.resample("W-FRI").last()
                    if "SPY" in _dyn_wk.columns:
                        _dyn_spy_wk = (
                            _dyn_wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
                        )
                    for _tk in _picked_d:
                        if _tk in _dyn_wk.columns:
                            _s = _dyn_wk[_tk].dropna()
                            if len(_s) >= 2:
                                _dyn_price_cache[_tk] = _s.to_frame(name="Close")

                # 前端自算 RS_63d（用 _dyn_px 替代 df_prices）
                # 用途: hover 参考「最近 3 月是否仍跑赢 SPY」；不参与加冕门槛
                _RS63_WIN = 63
                _d_rs63 = None
                if (
                    _dyn_px is not None
                    and not _dyn_px.empty
                    and "SPY" in _dyn_px.columns
                    and len(_dyn_px) > _RS63_WIN + 5
                ):
                    _spy_p = _dyn_px["SPY"].astype(float)
                    _spy_mom63 = (_spy_p / _spy_p.shift(_RS63_WIN + 1) - 1.0) * 100.0
                    _rs63_cols = {}
                    for tk in _picked_d:
                        if tk in _dyn_px.columns:
                            _etf_p = _dyn_px[tk].astype(float)
                            _etf_mom63 = (_etf_p / _etf_p.shift(_RS63_WIN + 1) - 1.0) * 100.0
                            _rs63_cols[tk] = (_etf_mom63 - _spy_mom63).reindex(_dyn_idx)
                        else:
                            _rs63_cols[tk] = pd.Series(np.nan, index=_dyn_idx)
                    _d_rs63 = pd.DataFrame(_rs63_cols, index=_dyn_idx).astype(float)

                _adv_m_global = _d_adv_hist.resample("ME").last()

                def _render_relay(metric_df, metric_label, hover_metric_label, key_suffix):
                    _metric_m = metric_df.resample("ME").last()
                    _rs_m = _d_rs.resample("ME").last()
                    _rs63_m = _d_rs63.resample("ME").last() if _d_rs63 is not None else None
                    if _metric_m.empty or len(_metric_m) < 2:
                        st.warning(f"⚠️ {_dynasty_window}:月末快照数据不足")
                        return

                    _rank_m = _metric_m.rank(axis=1, ascending=False, method="min")
                    _tier = pd.DataFrame(
                        0, index=_rank_m.index, columns=_rank_m.columns, dtype=int
                    )
                    _tier[_rank_m <= 3] = 1
                    _tier[_rank_m <= 2] = 2
                    _gold_mask = (_rank_m == 1) & (_rs_m > 0)
                    _tier = _tier.mask(_gold_mask, 3)
                    _demoted_mask = (_rank_m == 1) & (_rs_m <= 0)
                    _tier = _tier.mask(_demoted_mask, 0)

                    _last_month = _tier.index[-1]
                    _month_in_progress = bool(
                        pd.notna(_dyn_asof) and _last_month > _dyn_asof
                    )
                    _confirmed_tier = (
                        _tier.iloc[:-1] if _month_in_progress else _tier
                    )

                    _gold_cnt = (_confirmed_tier == 3).sum(axis=0)
                    _silver_cnt = ((_confirmed_tier == 1) | (_confirmed_tier == 2)).sum(axis=0)
                    _sort_key = _gold_cnt * 10000 + _silver_cnt
                    _ordered_tk = _sort_key.sort_values(ascending=False).index.tolist()

                    _tier_yx   = _tier[_ordered_tk].T
                    _rank_yx   = _rank_m[_ordered_tk].T
                    _rs_yx     = _rs_m[_ordered_tk].T
                    _metric_yx = _metric_m[_ordered_tk].T
                    _rs63_yx   = _rs63_m[_ordered_tk].T if _rs63_m is not None else None
                    _adv_yx    = _adv_m_global.reindex(columns=_ordered_tk).T

                    _ylabels = []
                    for tk in _ordered_tk:
                        _name = _d_name_map.get(tk, tk)
                        _meta = _etf_info.get(tk, {})
                        _adv_str = _fmt_usd(_meta.get("adv_usd"))
                        _ylabels.append(f"{_name} ({tk}) · ADV {_adv_str}")
                    _xlabels = [
                        (
                            f"{d.strftime('%Y-%m')} (进行中)"
                            if _month_in_progress and d == _last_month
                            else d.strftime("%Y-%m")
                        )
                        for d in _tier_yx.columns
                    ]

                    _BADGE = {0: "⚪ 灰", 1: "🥉 第3", 2: "🥈 第2", 3: "🥇 金"}
                    _hover_text = []
                    for tk in _ordered_tk:
                        _row_txt = []
                        for _d in _tier_yx.columns:
                            _t_val = int(_tier_yx.loc[tk, _d])
                            _r_val = _rank_yx.loc[tk, _d]
                            _rs_val = _rs_yx.loc[tk, _d]
                            _m_val = _metric_yx.loc[tk, _d]
                            _rs63_val = _rs63_yx.loc[tk, _d] if _rs63_yx is not None else None
                            _adv_hist_val = _adv_yx.loc[tk, _d] if _d in _adv_yx.columns else None
                            _rank_str = f"第 {int(_r_val)}" if pd.notna(_r_val) else "—"
                            _rs_str   = f"{_rs_val:+.2f}%" if pd.notna(_rs_val) else "—"
                            _m_str    = f"{_m_val:+.2f}" if pd.notna(_m_val) else "—"
                            _rs63_str = (
                                f"{_rs63_val:+.2f}%" if (_rs63_val is not None and pd.notna(_rs63_val))
                                else "—"
                            )
                            _adv_hist_str = (
                                _fmt_usd(float(_adv_hist_val))
                                if (_adv_hist_val is not None and pd.notna(_adv_hist_val))
                                else "—"
                            )
                            _demote_note = ""
                            if (
                                _t_val == 0 and pd.notna(_r_val) and int(_r_val) == 1
                                and pd.notna(_rs_val) and _rs_val <= 0
                            ):
                                _demote_note = "<br><i>Top1 但 RS_252d ≤ 0 → 降级(熊市无王)</i>"
                            _meta = _etf_info.get(tk, {})
                            _aum_str = _fmt_usd(_meta.get("aum"))
                            _in_prog_note = (
                                "（进行中）" if (_month_in_progress and _d == _last_month) else ""
                            )
                            _row_txt.append(
                                f"<b>{_d_name_map.get(tk, tk)} ({tk})</b><br>"
                                f"{_d.strftime('%Y-%m')}{_in_prog_note}<br>"
                                f"{_BADGE[_t_val]}<br>"
                                f"排名 {_rank_str}<br>"
                                f"{hover_metric_label} {_m_str}<br>"
                                f"RS_252d {_rs_str}<br>"
                                f"RS_63d {_rs63_str} <i>(仅参考,不进门槛)</i><br>"
                                f"ADV_63d(当月) {_adv_hist_str}<br>"
                                f"AUM(当前快照) {_aum_str}"
                                f"{_demote_note}"
                            )
                        _hover_text.append(_row_txt)

                    fig_dyn = go.Figure(data=go.Heatmap(
                        z=_tier_yx.values,
                        x=list(_tier_yx.columns),
                        y=_ylabels,
                        colorscale=[
                            [0.0000, "#2a2a2a"],
                            [0.1667, "#2a2a2a"],
                            [0.1667, "#565b60"],
                            [0.5000, "#565b60"],
                            [0.5000, "#aab0b6"],
                            [0.8333, "#aab0b6"],
                            [0.8333, "#FFD700"],
                            [1.0000, "#FFD700"],
                        ],
                        zmin=0, zmax=3,
                        customdata=np.array(_hover_text, dtype=object),
                        hovertemplate="%{customdata}<extra></extra>",
                        showscale=False,
                        xgap=1, ygap=1,
                    ))
                    fig_dyn.update_layout(
                        height=max(400, 24 * len(_ordered_tk)),
                        margin=dict(l=20, r=20, t=40, b=20),
                        plot_bgcolor="#111111", paper_bgcolor="#111111",
                        font=dict(color="#ddd"),
                        xaxis=dict(showgrid=False, side="bottom", tickformat="%b %Y", tickangle=-45),
                        yaxis=dict(showgrid=False, autorange="reversed"),
                        title=dict(
                            text=f"{_dynasty_window} 月末王朝接力 · 按 {metric_label} 排名 · {len(_ordered_tk)} 板块 · {len(_xlabels)} 月",
                            font=dict(size=14), x=0.01, xanchor="left",
                        ),
                    )
                    st.plotly_chart(fig_dyn, use_container_width=True, key=f"fig_dyn_{key_suffix}")

                    _stat_rows = []
                    _confirmed_tier_yx = _confirmed_tier[_ordered_tk].T
                    for tk in _ordered_tk:
                        _t_row = _confirmed_tier_yx.loc[tk].values
                        _gold = int((_t_row == 3).sum())
                        _silver = int(((_t_row == 1) | (_t_row == 2)).sum())
                        _max_streak = 0
                        _cur = 0
                        for v in _t_row:
                            if v == 3:
                                _cur += 1
                                _max_streak = max(_max_streak, _cur)
                            else:
                                _cur = 0
                        _confirmed_row = _confirmed_tier_yx.loc[tk]
                        _gold_dates = _confirmed_row.index[_confirmed_row.values == 3]
                        _last_gold = _gold_dates.max() if len(_gold_dates) > 0 else None
                        _stat_rows.append({
                            "板块": _d_name_map.get(tk, tk),
                            "代码": tk,
                            "累计戴金月数": _gold,
                            "累计戴银月数": _silver,
                            "最长连续戴金": _max_streak,
                            "最近戴金月份": _last_gold.strftime("%Y-%m") if _last_gold is not None else "—",
                        })
                    _stat_df = pd.DataFrame(_stat_rows)

                    _kings_top3 = _stat_df[_stat_df["累计戴金月数"] > 0].head(3)
                    _kings_html = " ".join([
                        f"<span class='tag-bull'>{r['板块']} 金{int(r['累计戴金月数'])}月/最长连续{int(r['最长连续戴金'])}月</span>"
                        for _, r in _kings_top3.iterrows()
                    ]) or "—"

                    _last_col = _tier_yx[_last_month]
                    _current_king_tk = None
                    _gold_now = _last_col[_last_col == 3]
                    if len(_gold_now) > 0:
                        _current_king_tk = _gold_now.index[0]
                    _current_silver_tks = _last_col[(_last_col == 1) | (_last_col == 2)].index.tolist()
                    if _current_king_tk:
                        _current_html = (
                            f"<span class='tag-bull'>🥇 {_d_name_map.get(_current_king_tk, _current_king_tk)} "
                            f"({_current_king_tk})</span>"
                        )
                    else:
                        _current_html = "<span style='color:#888'>当前无王(无板块同时满足 Top1 + RS_252d &gt; 0)</span>"
                    _silver_html = " ".join([
                        f"<span class='tag-bear'>🥈 {_d_name_map.get(tk, tk)} ({tk})</span>"
                        for tk in _current_silver_tks
                    ]) or "—"
                    _current_label = (
                        "当月领先(进行中·未定格)"
                        if _month_in_progress
                        else "当前在位之王"
                    )

                    st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>👑 {metric_label} · 王朝接力摘要 ({_dynasty_window} · {len(_xlabels)} 个月)</div>
<div style='margin-bottom:6px'>📍 {_current_label}({_last_month.strftime('%Y-%m')}): {_current_html} &nbsp; {_silver_html}</div>
<div style='margin-bottom:6px'>👑 累计王朝长度 Top3: {_kings_html}</div>
<div class='insight-section' style='font-size:13px; color:#888;'>
读法:🥇 金块 = 当月 Top1 且 RS_252d &gt; 0(跑赢 SPY);🥈 亮灰 = 第2名,🥉 暗灰 = 第3名;⚪ 深灰块 = 其他,或 Top1 但 RS_252d ≤ 0(熊市无王降级)。<b style='color:#aaa;'>连续金块</b> = 王朝期;<b style='color:#aaa;'>累计金多 + 最长连续金长</b> = 真时代之王。<b style='color:#aaa;'>对比 🅰️ 与 🅱️</b>:king_score 把 URA/TAN 这类小众主题盘从「时代之王」候选里压下去——它们 RS 可能称霸,但 ADV 显著低于 XL*/SMH/IGV 机构盘,容量项是负贡献。
</div>
</div>
""", unsafe_allow_html=True)

                    _render_relay_lab(key_suffix)

                def _render_relay_lab(key_suffix):
                    # ── 王朝接力净值实验台（多层筛选回测）
                    st.markdown("---")
                    st.markdown("##### 🧪 王朝接力净值实验台(多层筛选回测)")
                    st.caption(
                        "月末选仓、顺延 1 月执行(去 look-ahead) · 周线 NAV,价格 yfinance 复权 · "
                        "打分口径固定 king_score、进场门槛固定资历接力、多窗口 blend 固定 Borda(沿袭板块王朝) · "
                        "窗口/持仓数/守擂可调 · 早期未上市 ETF 月份自动缺席 · 净值扣单边 2%(200bps 滑点)。"
                    )

                    # 控件区：一排旋钮，显式 for 渲染（架构约束：禁列表推导生成组件）
                    # 打分口径固定 king_score、进场门槛固定资历接力、多窗口 blend 固定 Borda（沿袭板块王朝）
                    _ctrl_cols = st.columns([1.4, 0.9, 2.2])
                    _guard_choices = ["buffer", "δ", "无"]
                    with _ctrl_cols[0]:
                        _mom_wins = st.multiselect(
                            "动量窗口(日)", [63, 126, 252, 504], default=[252],
                            key=f"lab_wins_{key_suffix}",
                            help="多选做 blend(Borda 名次平均);单选=纯单窗口动量。",
                        )
                    with _ctrl_cols[1]:
                        _n_hold = int(st.selectbox("持仓数 N", [1, 2, 3, 4, 5], index=1, key=f"lab_n_{key_suffix}"))
                    with _ctrl_cols[2]:
                        _guard_sel = st.radio(
                            "守擂", _guard_choices, key=f"lab_guard_{key_suffix}", horizontal=True,
                        )

                    # 守擂三档规则说明（常显，供新用户看懂）
                    st.markdown(
                        "<div style='font-size:13px;color:#aaa;line-height:1.7;margin:-4px 0 6px'>"
                        "<b style='color:#ccc'>守擂 = 上月持仓的留任规则：</b>"
                        "<b>buffer</b> 在任票掉出前 buffer_N 名才换,减少无谓换仓 · "
                        "<b>δ</b> 在任票分数 ≥「第N名门槛 − kδ×当月σ」就留任 · "
                        "<b>无</b> 不留任,每月按排名硬换 TopN(换手最高)。"
                        "buffer_N / kδ 由系统 maximin 自动定最优,无需手选。"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                    # buffer_N / kδ 不再手选：由下方 maximin sweep 自动定最优后回填主曲线
                    _buf_n = max(4, _n_hold)
                    _kdelta = 1.0

                    if not _mom_wins:
                        _mom_wins = [252]
                    _basis_code = "king_score"
                    _blend_code = "borda"
                    _guard_code = {"buffer": "buffer", "δ": "delta", "无": "none"}[_guard_sel]
                    _gate_code = "seniority"

                    # 选仓池：选中 C/D + 可选 D-ext 4 票（染色图不含,只进净值回测）
                    _pool = dict(_picked_d)
                    _dext_in = []
                    if _use_dext:
                        for _tk, _p in _dyn_tickers.items():
                            if str(_p.get("group", "")).startswith("D-ext"):
                                _pool[_tk] = _p
                                _dext_in.append(_tk)
                    _pool_name_map = {tk: p.get("name", tk) for tk, p in _pool.items()}
                    if _dext_in:
                        st.caption(
                            "D 组扩展版已并入选仓池:"
                            + "、".join(f"{_pool_name_map.get(t, t)}({t})" for t in _dext_in)
                            + " · SOXX≈SMH、XHB≈ITB 高度重叠(近似重复暴露),COPX 铜矿是真新赛道 · "
                            "URNM 2019-12 上市,10Y 早期缺席。"
                        )

                    def _score_from_ts(_ts_dict, _wins=None):
                        """从某窗口时序算选仓池月末 score（月×板块）。_wins=None 用当前旋钮。"""
                        _use_wins = _mom_wins if _wins is None else _wins
                        _tks = _ts_dict.get("tickers", {}) or {}
                        _dates = _ts_dict.get("dates", []) or []
                        if not _dates:
                            return pd.DataFrame()
                        _ix = pd.to_datetime(_dates, errors="coerce")
                        _pl = {tk: p for tk, p in _tks.items() if tk in _pool}
                        if not _pl:
                            return pd.DataFrame()
                        _rsw = {}
                        for _w in [63, 126, 252, 504]:
                            _cols = {}
                            for tk, p in _pl.items():
                                _v = p.get(f"rs_{_w}")
                                if _v is None:
                                    _v = p.get("rs")
                                if _v is not None:
                                    _cols[tk] = _v
                            if _cols:
                                _rsw[_w] = pd.DataFrame(_cols, index=_ix).astype(float).resample("ME").last()
                        _advm = pd.DataFrame(
                            {tk: p.get("adv_63d") for tk, p in _pl.items()}, index=_ix
                        ).astype(float).resample("ME").last()
                        return hv.blend_relay_scores(_rsw, _advm, _use_wins, _blend_code, _basis_code)

                    # 当前窗口打分
                    _score_m = _score_from_ts(_dyn_ts)

                    # 价格：选仓池 + SPY，周线（含 D-ext）
                    _pool_px = get_global_data(sorted(_pool.keys()) + ["SPY"], years=10)
                    _pc: dict = {}
                    _spy_wk = _dyn_spy_wk
                    if _pool_px is not None and not _pool_px.empty:
                        _wk = _pool_px.resample("W-FRI").last()
                        if "SPY" in _wk.columns:
                            _spy_wk = _wk[["SPY"]].rename(columns={"SPY": "Close"}).dropna()
                        for _tk in _pool:
                            if _tk in _wk.columns:
                                _s = _wk[_tk].dropna()
                                if len(_s) >= 2:
                                    _pc[_tk] = _s.to_frame(name="Close")

                    def _build_navc(_sm, _gd, _bn, _kd, _n=None):
                        """选仓 → 槽位 → 各槽周线 NAV → 等权合成。_n=None 用当前旋钮。
                        返回 (monthly_holdings, slots, exec_months, slot_navs, navc)。"""
                        _nn = _n_hold if _n is None else int(_n)
                        if _sm is None or _sm.empty:
                            return {}, {}, [], [], pd.Series(dtype=float)
                        _mh2 = hv.select_relay_holdings(
                            _sm, _nn, _gate_code, _gd, _bn, _kd
                        )
                        if not _mh2:
                            return {}, {}, [], [], pd.Series(dtype=float)
                        _em = sorted(_mh2)
                        _sl = hv.build_basket_slot_assignments(_mh2, _em)
                        _ns = max((len(v) for v in _sl.values()), default=_nn)
                        _snavs = []
                        for _si in range(_ns):
                            _sg = hv.build_slot_segments(_sl, _si, _em)
                            _nv = hv.calc_slot_stats(_sg, _pc, _spy_wk, 0.04, 200.0)[2]
                            _snavs.append((f"仓{_si + 1}", _nv))
                        _valid = [nv for _, nv in _snavs if not nv.empty]
                        _navc2 = pd.Series(dtype=float)
                        if _valid:
                            _ui = _valid[0].index
                            for _n in _valid[1:]:
                                _ui = _ui.union(_n.index)
                            _acc = None
                            for _n in _valid:
                                _r = _n.reindex(_ui).ffill().bfill()
                                _acc = _r if _acc is None else _acc + _r
                            _navc2 = _acc / len(_valid)
                        return _mh2, _sl, _em, _snavs, _navc2

                    if _score_m.empty or not _pc:
                        st.info("暂无足够数据渲染净值(检查选仓池 / 动量窗口 / 价格)。")
                        return

                    # ── 守擂参数自动寻优：在选中守擂方式上跑 3Y/5Y/10Y 网格，maximin 定最优后回填主曲线
                    _HZ = ["3Y", "5Y", "10Y"]
                    _hz_color = {"3Y": "#5DADE2", "5Y": "#FFD700", "10Y": "#E67E22"}

                    def _maximin(grid_vals, cum_by_val):
                        """各段归一化后取 min 最高（并列取跨段 std 最小）。"""
                        _norm = {}
                        for hz in _HZ:
                            _vals = [cum_by_val[v].get(hz, float("nan")) for v in grid_vals]
                            _mx = max([x for x in _vals if x == x], default=float("nan"))
                            _norm[hz] = [
                                (x / _mx) if (_mx == _mx and _mx > 0 and x == x) else float("nan")
                                for x in _vals
                            ]
                        _best, _best_key = None, None
                        for _i, v in enumerate(grid_vals):
                            _sc = [_norm[hz][_i] for hz in _HZ if _norm[hz][_i] == _norm[hz][_i]]
                            if len(_sc) < len(_HZ):
                                continue
                            _key = (min(_sc), -float(np.std(_sc)))
                            if _best_key is None or _key > _best_key:
                                _best_key, _best = _key, v
                        return _best, _norm

                    _rec_val = None
                    _sweep_grid, _sweep_norm, _sweep_cum = [], {}, {}
                    if _guard_code != "none":
                        _score_by_hz = {
                            hz: _score_from_ts(_dynasty_ts_by_window.get(hz, {}) or {})
                            for hz in _HZ
                        }

                        def _cum_ret_for(hz, gd, bn, kd):
                            _sm2 = _score_by_hz.get(hz)
                            if _sm2 is None or _sm2.empty:
                                return float("nan")
                            _r = _build_navc(_sm2, gd, bn, kd)[4]
                            if _r.empty:
                                return float("nan")
                            return (float(_r.iloc[-1]) / float(_r.iloc[0]) - 1.0) * 100.0

                        with st.spinner("守擂参数寻优（3Y/5Y/10Y 网格）..."):
                            if _guard_code == "delta":
                                _sweep_grid = [round(x * 0.25, 2) for x in range(0, 13)]  # 0~3.0
                                _sweep_cum = {
                                    dk: {hz: _cum_ret_for(hz, "delta", _buf_n, dk) for hz in _HZ}
                                    for dk in _sweep_grid
                                }
                            else:  # buffer
                                _sweep_grid = list(range(int(_n_hold), 11))  # buffer N~10
                                _sweep_cum = {
                                    bn: {hz: _cum_ret_for(hz, "buffer", bn, _kdelta) for hz in _HZ}
                                    for bn in _sweep_grid
                                }
                        _rec_val, _sweep_norm = _maximin(_sweep_grid, _sweep_cum)

                        # 回填主曲线所用守擂参数（无稳健解则保留默认）
                        if _rec_val is not None:
                            if _guard_code == "delta":
                                _kdelta = float(_rec_val)
                            else:
                                _buf_n = int(_rec_val)

                    _mh, _slots, _exec_months, _slot_navs, _navc = _build_navc(
                        _score_m, _guard_code, _buf_n, _kdelta
                    )
                    if _navc.empty:
                        st.info("价格窗口内无足够数据生成净值曲线。")
                        return

                    # 统计卡（两排，第二排抄动量双龙口径：换股 / 换手 / 持有月数）
                    _ret_c = (float(_navc.iloc[-1]) / float(_navc.iloc[0]) - 1) * 100
                    _peak_c = _navc.cummax()
                    _dd_c = float(((_peak_c - _navc) / _peak_c.replace(0, float("nan"))).max()) * 100
                    _kpi = hv.compute_nav_kpi(_navc)
                    _years_c = (_navc.index[-1] - _navc.index[0]).days / 365.25
                    _cagr_c = (
                        ((float(_navc.iloc[-1]) / float(_navc.iloc[0])) ** (1 / _years_c) - 1) * 100
                        if _years_c > 0 else float("nan")
                    )
                    _turn = hv.relay_turnover_stats(_mh)

                    def _fmt_k(v, f=".2f"):
                        try:
                            if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                                return "—"
                            return f"{v:{f}}"
                        except (TypeError, ValueError):
                            return "—"

                    _row_a = st.columns(6)
                    _metrics_a = [
                        ("总收益", f"{_ret_c:+.1f}%"),
                        ("CAGR", f"{_cagr_c:+.1f}%" if _cagr_c == _cagr_c else "—"),
                        ("最大回撤", f"-{_dd_c:.1f}%"),
                        ("Calmar", _fmt_k(_kpi.get("calmar", float("nan")))),
                        ("Sortino", _fmt_k(_kpi.get("sortino", float("nan")))),
                        ("logR²", _fmt_k(_kpi.get("r2", float("nan")))),
                    ]
                    for _mi in range(len(_metrics_a)):
                        _row_a[_mi].metric(_metrics_a[_mi][0], _metrics_a[_mi][1])
                    _row_b = st.columns(3)
                    _metrics_b = [
                        ("换股次数", f"{_turn['n_swaps']}"),
                        ("年均换手", f"{_turn['ann_turnover']:.2f}"),
                        ("平均持有月数", f"{_turn['avg_hold_months']}"),
                    ]
                    for _mi in range(len(_metrics_b)):
                        _row_b[_mi].metric(_metrics_b[_mi][0], _metrics_b[_mi][1])

                    # ── 收益总览：各动量配置各自最优 N+守擂 的合成净值对比（maximin 选优,各自起点归一）
                    st.markdown("---")
                    _ov_key = f"lab_overview_{key_suffix}"
                    if st.button(
                        "📊 生成收益总览对比(各动量配置最优 N+守擂)",
                        key=f"{_ov_key}_btn",
                        help="7 种动量窗口配置,各自搜 N×守擂 最优(maximin 3Y/5Y/10Y);计算较重,点一次算一次。",
                    ):
                        _ov_configs = [
                            ([63], "63d"), ([126], "126d"), ([252], "252d"), ([504], "504d"),
                            ([63, 126], "63+126"), ([63, 126, 252], "63+126+252"),
                            ([63, 126, 252, 504], "63+126+252+504"),
                        ]
                        _ov_hz = ["3Y", "5Y", "10Y"]
                        _ov_delta_grid = [round(x * 0.25, 2) for x in range(0, 13)]
                        _ov_ts = {hz: (_dynasty_ts_by_window.get(hz, {}) or {}) for hz in _ov_hz}

                        def _ov_tot_ret(_sm, _n, _gd, _bn, _kd):
                            _r = _build_navc(_sm, _gd, _bn, _kd, _n)[4]
                            if _r is None or _r.empty:
                                return float("nan")
                            return (float(_r.iloc[-1]) / float(_r.iloc[0]) - 1.0) * 100.0

                        _ov_results = []
                        _ov_prog = st.progress(0.0, text="搜索各动量配置最优参数...")
                        for _ci in range(len(_ov_configs)):
                            _wins, _clabel = _ov_configs[_ci]
                            _score_hz = {hz: _score_from_ts(_ov_ts[hz], _wins) for hz in _ov_hz}
                            _score_disp = _score_hz.get("10Y", pd.DataFrame())
                            if _score_disp is None or _score_disp.empty:
                                for hz in ["5Y", "3Y"]:
                                    if not _score_hz.get(hz, pd.DataFrame()).empty:
                                        _score_disp = _score_hz[hz]
                                        break
                            # 候选：N × 守擂 × 参数
                            _cands = []
                            for _n in [1, 2, 3, 4, 5]:
                                for _bn in range(int(_n), 11):
                                    _cands.append((_n, "buffer", _bn, 1.0))
                                for _dk in _ov_delta_grid:
                                    _cands.append((_n, "delta", max(4, _n), _dk))
                                _cands.append((_n, "none", max(4, _n), 1.0))
                            _rows = []
                            for (_n, _gd, _bn, _kd) in _cands:
                                _rr = {
                                    hz: _ov_tot_ret(_score_hz.get(hz, pd.DataFrame()), _n, _gd, _bn, _kd)
                                    for hz in _ov_hz
                                }
                                _rows.append(((_n, _gd, _bn, _kd), _rr))
                            # 各段按候选集内最大值归一，maximin 选优
                            _nmax = {}
                            for hz in _ov_hz:
                                _vals = [rr[hz] for _, rr in _rows if rr[hz] == rr[hz]]
                                _nmax[hz] = max(_vals) if _vals else float("nan")
                            _best, _best_key = None, None
                            for (_params, _rr) in _rows:
                                _sc, _ok = [], True
                                for hz in _ov_hz:
                                    _mx, _v = _nmax[hz], _rr[hz]
                                    if not (_mx == _mx and _mx > 0 and _v == _v):
                                        _ok = False
                                        break
                                    _sc.append(_v / _mx)
                                if not _ok:
                                    continue
                                _key = (min(_sc), -float(np.std(_sc)))
                                if _best_key is None or _key > _best_key:
                                    _best_key, _best = _key, _params
                            if _best is None:  # 三段凑不齐则退化为 10Y 总收益最高
                                _best_r = None
                                for (_params, _rr) in _rows:
                                    _v = _rr.get("10Y", float("nan"))
                                    if _v == _v and (_best_r is None or _v > _best_r):
                                        _best_r, _best = _v, _params
                            # 用最长可用时序建展示曲线（各自起点归一）
                            _rel, _fret = pd.Series(dtype=float), float("nan")
                            if _best is not None and _score_disp is not None and not _score_disp.empty:
                                _n, _gd, _bn, _kd = _best
                                _navc_w = _build_navc(_score_disp, _gd, _bn, _kd, _n)[4]
                                if not _navc_w.empty:
                                    _rel = _navc_w.astype(float).dropna()
                                    _rel = _rel / float(_rel.iloc[0])
                                    _fret = (float(_rel.iloc[-1]) - 1.0) * 100.0
                            _ov_results.append(
                                {"label": _clabel, "params": _best, "rel": _rel, "ret": _fret}
                            )
                            _ov_prog.progress((_ci + 1) / len(_ov_configs), text=f"{_clabel} 完成")
                        _ov_prog.empty()

                        # 固定对比线：252d · N=2 · buffer(4)，不参与寻优，供与各配置最优对比
                        _pin_wins, _pin_n, _pin_bn = [252], 2, 4
                        _pin_score_hz = {hz: _score_from_ts(_ov_ts[hz], _pin_wins) for hz in _ov_hz}
                        _pin_disp = _pin_score_hz.get("10Y", pd.DataFrame())
                        if _pin_disp is None or _pin_disp.empty:
                            for hz in ["5Y", "3Y"]:
                                if not _pin_score_hz.get(hz, pd.DataFrame()).empty:
                                    _pin_disp = _pin_score_hz[hz]
                                    break
                        _pin_rel, _pin_ret = pd.Series(dtype=float), float("nan")
                        if _pin_disp is not None and not _pin_disp.empty:
                            _pin_navc = _build_navc(_pin_disp, "buffer", _pin_bn, 1.0, _pin_n)[4]
                            if not _pin_navc.empty:
                                _pin_rel = _pin_navc.astype(float).dropna()
                                _pin_rel = _pin_rel / float(_pin_rel.iloc[0])
                                _pin_ret = (float(_pin_rel.iloc[-1]) - 1.0) * 100.0
                        _ov_results.append({
                            "label": "252d(固定)", "params": (_pin_n, "buffer", _pin_bn, 1.0),
                            "rel": _pin_rel, "ret": _pin_ret, "pinned": True,
                        })

                        st.session_state[_ov_key] = _ov_results

                    _ov_cached = st.session_state.get(_ov_key)
                    if _ov_cached:
                        _guard_disp = {"buffer": "buffer", "delta": "δ", "none": "无"}
                        _ov_palette = ["#E74C3C", "#E67E22", "#F1C40F", "#2ECC71",
                                       "#3498DB", "#9B59B6", "#1ABC9C"]
                        _ov_fig = go.Figure()
                        # 颜色按原配置序固定，图例按最终总收益从高到低排
                        _ov_entries = []
                        for _i in range(len(_ov_cached)):
                            _res = _ov_cached[_i]
                            _rel = _res.get("rel")
                            if _rel is None or _rel.empty:
                                continue
                            _p = _res.get("params")
                            if _p:
                                _n, _gd, _bn, _kd = _p
                                _pstr = f"N={_n}·{_guard_disp.get(_gd, _gd)}"
                                if _gd == "buffer":
                                    _pstr += f"({_bn})"
                                elif _gd == "delta":
                                    _pstr += f"({_kd})"
                            else:
                                _pstr = "—"
                            _is_pin = bool(_res.get("pinned"))
                            _ov_entries.append({
                                "rel": _rel,
                                "color": "#FFFFFF" if _is_pin else _ov_palette[_i % len(_ov_palette)],
                                "name": f"{_res['label']} · {_pstr} {_res['ret']:+.0f}%",
                                "ret": _res.get("ret", float("nan")),
                                "width": 3 if _is_pin else 2,
                                "dash": "dash" if _is_pin else None,
                            })
                        _ov_entries.sort(
                            key=lambda e: (e["ret"] if e["ret"] == e["ret"] else float("-inf")),
                            reverse=True,
                        )
                        for _e in _ov_entries:
                            _ov_fig.add_trace(go.Scatter(
                                x=_e["rel"].index, y=_e["rel"].values, mode="lines",
                                name=_e["name"],
                                line=dict(color=_e["color"], width=_e["width"], dash=_e["dash"]),
                            ))
                        # SPY 基准置于图例末尾
                        if _spy_wk is not None and not _spy_wk.empty:
                            _spy_s = _spy_wk["Close"].astype(float).dropna()
                            if len(_spy_s) >= 2:
                                _spy_rel = _spy_s / float(_spy_s.iloc[0])
                                _ov_fig.add_trace(go.Scatter(
                                    x=_spy_rel.index, y=_spy_rel.values, mode="lines",
                                    name=f"SPY {(float(_spy_rel.iloc[-1]) - 1) * 100:+.1f}%",
                                    line=dict(color="rgba(170,170,170,0.45)", width=1.5, dash="dot"),
                                ))
                        _ov_fig.update_layout(
                            title="收益总览 · 各动量配置最优 N+守擂 vs SPY(各自起点归一)",
                            xaxis=dict(title="日期", gridcolor="rgba(100,100,100,0.3)"),
                            yaxis=dict(
                                title="NAV(对数,1.0 = 起始)", type="log",
                                tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
                                ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
                                gridcolor="rgba(100,100,100,0.3)",
                            ),
                            height=460, margin=dict(l=10, r=10, t=44, b=60),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,30,30,0.6)",
                            font=dict(color="#ccc", size=13), showlegend=True,
                        )
                        st.plotly_chart(_ov_fig, use_container_width=True, key=f"{_ov_key}_fig")
                        st.caption(
                            "每条 = 该动量配置在 maximin(3Y/5Y/10Y)口径下最优的 N+守擂,图例标出选中参数。"
                            "白色粗虚线「252d(固定)」= 固定 N=2·buffer(4),不参与寻优,作对比基线。"
                            "各自起点归一;起点日期因窗口预热长度而异(504d 最晚)。"
                        )

                    # 主曲线所用守擂参数说明（自动寻优结果）
                    if _guard_code == "none":
                        _guard_txt = "守擂=无 · 每月按排名硬换仓"
                    elif _rec_val is not None:
                        _lbl = "kδ" if _guard_code == "delta" else "buffer_N"
                        _guard_txt = f"守擂={_guard_sel} · maximin 最优 {_lbl}\\* = {_rec_val} · 主曲线已按此值回测"
                    else:
                        _lbl, _val = ("kδ", _kdelta) if _guard_code == "delta" else ("buffer_N", _buf_n)
                        _guard_txt = f"守擂={_guard_sel} · 网格无稳健解,主曲线用默认 {_lbl}={_val}"
                    st.caption(_guard_txt)

                    # 合成净值 + 各仓叠加
                    st.plotly_chart(
                        hv.build_combined_fig_n(
                            _slot_navs, _navc, _spy_wk,
                            f"王朝接力净值实验台 — 等权 {_n_hold} 仓合成 vs SPY",
                        ),
                        use_container_width=True,
                        key=f"lab_combined_{key_suffix}",
                    )

                    # 每月持仓表
                    _pick_rows = []
                    for _em in _exec_months:
                        _sa = _slots.get(_em, [])
                        _row = {"执行月(持有)": _em}
                        for _si in range(len(_sa)):
                            _t = _sa[_si]
                            _row[f"仓{_si + 1}"] = (
                                "—" if (not _t or _t == "CASH")
                                else f"{_pool_name_map.get(_t, _t)} ({_t})"
                            )
                        _pick_rows.append(_row)
                    if _pick_rows:
                        st.markdown("**每月实际持仓**(执行月 = 排名来源月 + 1,去 look-ahead)")
                        st.dataframe(
                            pd.DataFrame(_pick_rows).iloc[::-1],
                            use_container_width=True, hide_index=True,
                        )

                    # 各仓分段拼接图
                    for _si in range(len(_slot_navs)):
                        _seg = hv.build_slot_segments(_slots, _si, _exec_months)
                        st.plotly_chart(
                            hv.build_stitched_fig(
                                _seg, f"王朝接力 仓{_si + 1} (Slot {_si})",
                                _spy_wk, _pc, _pool_name_map,
                            ),
                            use_container_width=True,
                            key=f"lab_slot{_si}_{key_suffix}",
                        )

                    # ── 守擂稳健性 sweep（尾部 3Y/5Y/10Y，各自归一化 + maximin）
                    # 参数已在上方自动寻优并回填主曲线，这里佐证：三线齐高=稳健平台，单段峰值各异=过拟合。
                    if _guard_code != "none" and _sweep_grid:
                        st.markdown("---")

                        def _sweep_fig(grid_vals, norm, cum_by_val, rec, xlabel, title):
                            _fig = go.Figure()
                            for hz in _HZ:
                                _y = norm.get(hz, [])
                                if sum(1 for v in _y if v == v) < 2:
                                    continue
                                _cd = [cum_by_val[v].get(hz, float("nan")) for v in grid_vals]
                                _fig.add_trace(go.Scatter(
                                    x=grid_vals, y=_y, mode="lines+markers", name=hz,
                                    line=dict(color=_hz_color.get(hz, "#E67E22"),
                                              width=4 if hz == "3Y" else 2),
                                    marker=dict(size=5), customdata=_cd,
                                    hovertemplate=f"{hz} {xlabel}=%{{x}} → 总收益 %{{customdata:.1f}}%<extra></extra>",
                                ))
                            if rec is not None:
                                _fig.add_vline(x=rec, line=dict(color="#2ECC71", width=2, dash="dash"))
                                _fig.add_annotation(
                                    x=rec, y=1.02, yref="paper", text=f"maximin={rec}",
                                    showarrow=False, font=dict(color="#2ECC71", size=13),
                                    bgcolor="#111", xanchor="left",
                                )
                            _fig.update_layout(
                                height=300, margin=dict(l=20, r=20, t=46, b=20),
                                plot_bgcolor="#111111", paper_bgcolor="#111111",
                                font=dict(color="#ddd"),
                                xaxis=dict(title=xlabel, showgrid=True, gridcolor="#222"),
                                yaxis=dict(title="各段归一化收益 (÷自身峰值)", showgrid=True, gridcolor="#222"),
                                title=dict(text=title, font=dict(size=13), x=0.01, xanchor="left"),
                                legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
                            )
                            return _fig

                        if _guard_code == "delta":
                            _xlabel = "kδ (×横截面σ)"
                            _title = "δ 稳健性 · 3Y/5Y/10Y(各自归一化;三线齐高=稳健平台)"
                            _rec_label = f"δ\\* = {_rec_val}" if _rec_val is not None else ""
                        else:
                            _xlabel = "buffer_N"
                            _title = "buffer 稳健性 · 3Y/5Y/10Y(各自归一化;三线齐高=稳健平台)"
                            _rec_label = f"buffer_N\\* = {_rec_val}" if _rec_val is not None else ""
                        st.plotly_chart(
                            _sweep_fig(_sweep_grid, _sweep_norm, _sweep_cum, _rec_val, _xlabel, _title),
                            use_container_width=True, key=f"lab_sweep_{key_suffix}",
                        )
                        st.caption(
                            ("✅ maximin 最优:" + _rec_label + " —— 三段都不差的重叠平台,主曲线已按此值回测。"
                             if _rec_label else "网格内暂无三段齐全的稳健点,主曲线用默认守擂参数。")
                            + " 单段峰值各异是过拟合症状,别照搬;60 分平台优先于 90 分尖峰。"
                        )

                st.markdown(
                    f"##### 🅰️ 按 king_score 排名(主图 · 动量+容量 · "
                    f"w_rs={_king_w['rs']:.1f} / w_cap={_king_w['cap']:.1f})"
                )
                _render_relay(_d_king, "king_score", "king_score", "king")

with _dyn_tab2:
    st.caption(
        "**钻取口径**:先识别连续金块期,再按「上一个月末 → 末段月末」计算"
        "**在位期超额 = 个股累计涨幅 − 板块 ETF 累计涨幅**,排出 Top 3 龙头。"
        "一级行业用 S&P500+GICS；主题 ETF 优先用 Yahoo/发行商 holdings 快照，失败才回退本地 seed（候选池列标记）。"
        "⚠️ = 该股计算区间开始时未上市，数字可能虚高。"
    )

    if not selected_groups:
        st.info("👈 请在侧边栏勾选至少一个组别以识别王朝期")
    elif not (_dyn_ts := _dynasty_ts_by_window.get(_dynasty_window, {})) or not _dyn_ts.get("success"):
        st.warning(f"⚠️ {_dynasty_window} 时序数据暂不可用")
    else:
        _dyn_tickers2 = _dyn_ts.get("tickers", {}) or {}
        _dyn_dates_raw2 = _dyn_ts.get("dates", []) or []
        _picked_d2 = {
            tk: p for tk, p in _dyn_tickers2.items()
            if p.get("group", "") in selected_groups
        }
        if not _picked_d2 or not _dyn_dates_raw2:
            st.info(f"⚠️ {_dynasty_window}:选中组别无可用 ticker")
        else:
            _dyn_idx2 = pd.to_datetime(_dyn_dates_raw2, errors="coerce")
            _d_king2 = pd.DataFrame(
                {tk: p.get("king_score", []) for tk, p in _picked_d2.items()},
                index=_dyn_idx2,
            ).astype(float)
            _d_rs2 = pd.DataFrame(
                {tk: p.get("rs", []) for tk, p in _picked_d2.items()},
                index=_dyn_idx2,
            ).astype(float)
            _d_king_m2 = _d_king2.resample("ME").last()
            _d_rs_m2   = _d_rs2.resample("ME").last()
            _dyn_asof2 = pd.to_datetime(_dyn_ts.get("asof"), errors="coerce")

            if _d_king_m2.empty or len(_d_king_m2) < 2:
                st.warning(f"⚠️ {_dynasty_window}:月末快照数据不足")
            else:
                _rank_m2 = _d_king_m2.rank(axis=1, ascending=False, method="min")
                _tier2 = pd.DataFrame(0, index=_rank_m2.index, columns=_rank_m2.columns, dtype=int)
                _tier2[_rank_m2 <= 3] = 1
                _gold_mask2 = (_rank_m2 == 1) & (_d_rs_m2 > 0)
                _tier2 = _tier2.mask(_gold_mask2, 2)
                _demoted_mask2 = (_rank_m2 == 1) & (_d_rs_m2 <= 0)
                _tier2 = _tier2.mask(_demoted_mask2, 0)
                _last_month2 = _tier2.index[-1]
                _month_in_progress2 = bool(
                    pd.notna(_dyn_asof2) and _last_month2 > _dyn_asof2
                )
                _in_progress_tier2 = (
                    _tier2.iloc[-1] if _month_in_progress2 else None
                )
                _confirmed_tier2 = (
                    _tier2.iloc[:-1] if _month_in_progress2 else _tier2
                )

                _d_name_map2 = {tk: p.get("name", tk) for tk, p in _picked_d2.items()}
                _gold_cnt2 = (_confirmed_tier2 == 2).sum(axis=0)
                _silver_cnt2 = (_confirmed_tier2 == 1).sum(axis=0)
                _sort_key2 = _gold_cnt2 * 10000 + _silver_cnt2
                _ordered_tk2 = _sort_key2.sort_values(ascending=False).index.tolist()
                _tier_yx2 = _confirmed_tier2[_ordered_tk2].T
                _group_map2 = {tk: p.get("group", "") for tk, p in _picked_d2.items()}

                def _segment_type(n_months: int) -> str:
                    if n_months >= 3:
                        return "王朝"
                    if n_months == 2:
                        return "接力段"
                    return "脉冲"

                def _source_hint(tk: str) -> str:
                    _g = _group_map2.get(tk, "")
                    if _g.startswith("C:"):
                        return "S&P500+GICS"
                    if not _g.startswith("D:"):
                        return "不支持/观察"
                    _m = _holdings_items.get(tk, {})
                    _src  = _m.get("source")
                    _prv  = _m.get("provider")
                    _aod  = _m.get("as_of_date")
                    _fb   = _m.get("is_fallback", True)
                    _stale = _m.get("is_stale", True)
                    if not _src:
                        return "seed fallback"
                    if _src == "local_seed" or _fb:
                        return "seed fallback"
                    if _src == "yahoo":
                        _date_str = f" ({_aod})" if _aod else ""
                        _warn = " ⚠️stale" if _stale else ""
                        return f"Yahoo{_date_str}{_warn}"
                    _prv_label = {
                        "spdr": "SPDR", "ishares": "iShares",
                        "globalx": "Global X", "vaneck": "VanEck",
                        "invesco": "Invesco", "firsttrust": "First Trust",
                    }.get(_prv or "", _prv or "issuer")
                    _date_str = f" ({_aod})" if _aod else ""
                    _warn = " ⚠️stale" if _stale else ""
                    return f"{_prv_label}{_date_str}{_warn}"

                _dynasties = []
                for _sector_order, tk in enumerate(_ordered_tk2):
                    _row = _tier_yx2.loc[tk].values
                    _months = _tier_yx2.columns
                    _i = 0
                    while _i < len(_row):
                        if _row[_i] == 2:
                            _j = _i
                            while _j + 1 < len(_row) and _row[_j + 1] == 2:
                                _j += 1
                            _api_start_idx = _i - 1 if _i > 0 else _i
                            _n_months = _j - _i + 1
                            _continues_in_progress = bool(
                                _month_in_progress2
                                and _j == len(_row) - 1
                                and _in_progress_tier2 is not None
                                and int(_in_progress_tier2.get(tk, 0)) == 2
                            )
                            _dynasties.append({
                                "ticker":              tk,
                                "name":                _d_name_map2.get(tk, tk),
                                "display_start_date":  _months[_i],
                                "display_end_date":    _months[_j],
                                "api_start_date":      _months[_api_start_idx].strftime("%Y-%m-%d"),
                                "api_end_date":        _months[_j].strftime("%Y-%m-%d"),
                                "display_start_label": _months[_i].strftime("%Y-%m"),
                                "display_end_label":   _months[_j].strftime("%Y-%m"),
                                "api_start_label":     _months[_api_start_idx].strftime("%Y-%m"),
                                "api_end_label":       _months[_j].strftime("%Y-%m"),
                                "n_months":            _n_months,
                                "segment_type":        _segment_type(_n_months),
                                "sector_gold_total":   int(_gold_cnt2.get(tk, 0)),
                                "sector_order":        _sector_order,
                                "source_hint":         _source_hint(tk),
                                "continues_in_progress": _continues_in_progress,
                            })
                            _i = _j + 1
                        else:
                            _i += 1

                if not _dynasties:
                    st.info(f"{_dynasty_window} 内未识别到任何连续金块期 (无王朝期)")
                else:
                    if _month_in_progress2 and _in_progress_tier2 is not None:
                        _leading_now = _in_progress_tier2[
                            _in_progress_tier2 == 2
                        ].index.tolist()
                        _leading_now_text = "、".join(
                            f"{_d_name_map2.get(tk, tk)} ({tk})"
                            for tk in _leading_now
                        ) or "无板块满足加冕门槛"
                        st.caption(
                            f"{_last_month2.strftime('%Y-%m')} 当月领先（进行中·未定格）："
                            f"{_leading_now_text}；不计入正式王朝月数。"
                        )
                    _dynasties.sort(
                        key=lambda d: (
                            -d["sector_gold_total"],
                            d["sector_order"],
                            -d["n_months"],
                            -d["display_start_date"].value,
                        )
                    )
                    st.markdown(
                        f"**{_dynasty_window} 共识别到 {len(_dynasties)} 段王朝期** "
                        f"(按板块累计戴金月数排序;每段调一次后端 API,首次加载会慢 5-10 秒)"
                    )

                    _rows = []
                    with st.spinner(f"拉 {len(_dynasties)} 段王朝期的成分股龙头..."):
                        for d in _dynasties:
                            _res = fetch_dynasty_leaders(
                                d["ticker"], d["api_start_date"], d["api_end_date"], 3
                            )
                            if not _res or not _res.get("success"):
                                _leaders_cells = ["—", "—", "—"]
                                _excess_cells  = ["—", "—", "—"]
                                _etf_ret_str   = "—"
                                _status = (_res or {}).get("error", "API失败")
                            else:
                                _etf_ret_str = f"{_res['etf_return_pct']:+.1f}%"
                                _leaders = _res.get("leaders", [])
                                _leaders_cells = []
                                _excess_cells  = []
                                for i in range(3):
                                    if i < len(_leaders):
                                        _l = _leaders[i]
                                        _has_warning = (
                                            not _l.get("listed_full_period")
                                            or bool(_l.get("stale_endpoint"))
                                        )
                                        _flag = " ⚠️" if _has_warning else ""
                                        _leaders_cells.append(
                                            f"{_l['ticker']}{_flag} ({_l['name'][:20]})"
                                        )
                                        _excess_cells.append(f"{_l['excess_pct']:+.1f}%")
                                    else:
                                        _leaders_cells.append("—")
                                        _excess_cells.append("—")
                                _stale_tickers = [
                                    _l["ticker"] for _l in _leaders
                                    if _l.get("stale_endpoint")
                                ]
                                _status = (
                                    f"端点落后: {','.join(_stale_tickers)}"
                                    if _stale_tickers
                                    else ("OK" if _leaders else "无候选")
                                )
                            _rows.append({
                                "板块": f"{d['name']} ({d['ticker']})",
                                "类型": d["segment_type"],
                                "王朝期": (
                                    f"{d['display_start_label']} → {d['display_end_label']}"
                                    f"{'（当月进行中）' if d['continues_in_progress'] else ''}"
                                ),
                                "计算区间": f"{d['api_start_label']} → {d['api_end_label']}",
                                "持续(月)": d["n_months"],
                                "累计戴金(月)": d["sector_gold_total"],
                                "候选池": d["source_hint"],
                                "板块ETF涨幅": _etf_ret_str,
                                "🥇 Top1": _leaders_cells[0],
                                "Top1 超额": _excess_cells[0],
                                "🥈 Top2": _leaders_cells[1],
                                "Top2 超额": _excess_cells[1],
                                "🥉 Top3": _leaders_cells[2],
                                "Top3 超额": _excess_cells[2],
                                "状态": str(_status)[:60],
                            })

                    _df_leaders = pd.DataFrame(_rows)
                    st.dataframe(
                        _df_leaders,
                        use_container_width=True,
                        hide_index=True,
                        height=min(800, 40 + 35 * len(_rows)),
                    )
                    st.caption(
                        "类型: 王朝=连续戴金≥3个月 / 接力段=2个月 / 脉冲=1个月。"
                        "计算区间使用「上一个月末→末段月末」，单月脉冲也能算在位超额。"
                        "⚠️ = 计算区间开始时未上市，或个股端点落后 ETF 超过 5 个交易日。"
                        "候选池: S&P500+GICS=一级行业当前成分；Yahoo/发行商=主题 ETF 官方持仓快照；"
                        "seed fallback=本地维护持仓，非实时官方数据。"
                    )
