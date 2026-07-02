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
_default_groups = [
    g for g in ["C: 核心板块 (Level 1 Sectors)", "D: 细分赛道 (Level 2/Themes)"]
    if g in _all_groups
]

with st.sidebar:
    selected_groups = st.multiselect("显示资产组别：", _all_groups, default=_default_groups)

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

                    # ── 王朝接力净值
                    st.markdown("---")
                    st.markdown(f"##### 📈 {metric_label} · 王朝接力净值(龙头 + 次龙头,左右两列)")
                    st.caption(
                        "每月末选 **2 个仓位**,顺延 1 月执行(去 look-ahead) · **进场门槛**:新进场"
                        "必须当月在前 3(图上银/金格) · **资历优先**:够格的按近 6 月进前 3 次数排序,"
                        "优先老牌、不追单月暴涨 · **守擂防抖**:在任票只要还在 Top-N 缓冲区内就继续持有,"
                        "掉出缓冲区才换人 · 左右两列只为对齐观察:上月在某列且本月仍持有的留原列,不来回跳 · "
                        "各列等权,合成线 = 左右 50/50 · 周线 NAV,价格 yfinance 股息+拆股复权,"
                        "与后端 king_score 同源 · 净值最长回看约 10 年,早期未上市的 ETF 月份缺价。"
                    )
                    _dyn_buf = int(st.number_input(
                        "守擂缓冲区 buffer_N(≥2,越大越不换仓)",
                        min_value=2, max_value=10, value=4, step=1,
                        key=f"dyn_nav_buf_{key_suffix}",
                        help="持有的票掉到第 N 名以内都不换;掉出第 N 名才被替换为当前 Top2。"
                             "= 2 即严格只拿前两名(最敏感,换手最高)。",
                    ))
                    _ten6 = (_rank_m <= 3).astype(int).rolling(6, min_periods=1).sum()
                    if not _dyn_price_cache:
                        st.info("暂无可用价格数据,无法渲染王朝接力净值。")
                    else:
                        _mh: dict = {}
                        _mh_src: dict = {}
                        _mh_raw: dict = {}
                        _mh_ten: dict = {}
                        _prev_h: list = []
                        for _ts, _row in _rank_m.iterrows():
                            _r = _row.dropna().sort_values()
                            if _r.empty:
                                continue
                            _order = _r.index.tolist()
                            _t2 = _order[:2]
                            _tN = set(_order[:_dyn_buf])
                            _tnow = _ten6.loc[_ts]
                            _elig = [t for t in _order if _r[t] <= 3]
                            _elig_t = sorted(
                                _elig, key=lambda t: (-float(_tnow.get(t, 0)), _r[t]))
                            _hold = [t for t in _prev_h if t in _tN][:2] if _prev_h else []
                            for t in _elig_t:
                                if len(_hold) >= 2:
                                    break
                                if t not in _hold:
                                    _hold.append(t)
                            if len(_hold) < 2:
                                for t in _order:
                                    if len(_hold) >= 2:
                                        break
                                    if t not in _hold:
                                        _hold.append(t)
                            _exec_m = hv.next_month_key(_ts.strftime("%Y-%m"), 1)
                            _mh[_exec_m] = _hold
                            _mh_src[_exec_m] = _ts.strftime("%Y-%m")
                            _mh_raw[_exec_m] = _t2
                            _mh_ten[_exec_m] = {t: int(_tnow.get(t, 0)) for t in _hold}
                            _prev_h = _hold
                        _exec_months = sorted(_mh)
                        if not _exec_months:
                            st.info("月度排名数据不足,无法渲染净值。")
                        else:
                            _slots = hv.build_basket_slot_assignments(_mh, _exec_months)

                            def _dyn_nm(t):
                                if not t or t == "CASH":
                                    return "—"
                                return f"{_d_name_map.get(t, t)} ({t})"

                            def _wt(t, ten):
                                b = _dyn_nm(t)
                                return (f"{b} · 资历{ten[t]}"
                                        if (t and t != "CASH" and t in ten) else b)
                            _picks_rows = []
                            for _em in _exec_months:
                                _sa = _slots.get(_em, ["—", "—"])
                                _raw = _mh_raw.get(_em, [])
                                _raw1 = _raw[0] if len(_raw) > 0 else None
                                _raw2 = _raw[1] if len(_raw) > 1 else None
                                _ten = _mh_ten.get(_em, {})
                                _held = {t for t in _sa if t and t != "CASH"}
                                _kept = bool(_raw) and _held != set(_raw)
                                _picks_rows.append({
                                    "排名来源月": _mh_src.get(_em, "—"),
                                    "执行月(实际持有)": _em,
                                    "来源月 Top1(龙头)": _dyn_nm(_raw1),
                                    "来源月 Top2(次龙头)": _dyn_nm(_raw2),
                                    "左列实际持有": _wt(_sa[0], _ten),
                                    "右列实际持有": _wt(_sa[1], _ten),
                                    "守擂留任": "是" if _kept else "",
                                })
                            st.markdown("**每月左右两列实际持仓**(对照上方王朝接力图逐行核对)")
                            st.caption(
                                "「排名来源月」对应王朝接力图里那一格的月份;「执行月」= 来源月 + 1 = 真正持有的月份"
                                "(去 look-ahead:月末排名是用截至月末的价格算的,只能下月才进场)。"
                                "**选股两层**:① 新进场必须当月在前 3(图上银/金格)才够格;② 够格的按「资历」"
                                "(近 6 月进过前 3 的次数,数字越大越老牌)排序,优先老牌、不追单月暴涨。"
                                "标的后缀 `· 资历N` 就是这个次数。当「实际持有」≠「来源月 Top1/Top2」时:"
                                "① **守擂留任=是**——上月的票还在缓冲区内被留任;② 资历更高的老牌把单月窜上来的新票挤掉。"
                            )
                            st.dataframe(
                                pd.DataFrame(_picks_rows).iloc[::-1],
                                use_container_width=True, hide_index=True,
                            )

                            _seg_l = hv.build_slot_segments(_slots, 0, _exec_months)
                            _seg_r = hv.build_slot_segments(_slots, 1, _exec_months)
                            _nav_l = hv.calc_slot_stats(
                                _seg_l, _dyn_price_cache, _dyn_spy_wk, 0.04)[2]
                            _nav_r = hv.calc_slot_stats(
                                _seg_r, _dyn_price_cache, _dyn_spy_wk, 0.04)[2]

                            _navc = pd.Series(dtype=float)
                            if not _nav_l.empty and not _nav_r.empty:
                                _uidx = _nav_l.index.union(_nav_r.index)
                                _nl = _nav_l.reindex(_uidx).ffill().bfill()
                                _nr = _nav_r.reindex(_uidx).ffill().bfill()
                                _navc = 0.5 * _nl + 0.5 * _nr
                            elif not _nav_l.empty:
                                _navc = _nav_l.copy()
                            elif not _nav_r.empty:
                                _navc = _nav_r.copy()

                            if _navc.empty:
                                st.info("价格窗口内无足够数据生成净值曲线。")
                            else:
                                _ret_c = (
                                    float(_navc.iloc[-1]) / float(_navc.iloc[0]) - 1
                                ) * 100
                                _peak_c = _navc.cummax()
                                _dd_c = float(
                                    ((_peak_c - _navc)
                                     / _peak_c.replace(0, float("nan"))).max()
                                ) * 100
                                _kpi = hv.compute_nav_kpi(_navc)
                                _years_c = (_navc.index[-1] - _navc.index[0]).days / 365.25
                                _cagr_c = (
                                    ((float(_navc.iloc[-1]) / float(_navc.iloc[0])) ** (1 / _years_c) - 1) * 100
                                    if _years_c > 0 else float("nan")
                                )

                                def _fmt_k(v, f=".2f"):
                                    try:
                                        if isinstance(v, float) and (
                                            v != v or abs(v) == float("inf")):
                                            return "—"
                                        return f"{v:{f}}"
                                    except (TypeError, ValueError):
                                        return "—"

                                _c1, _c2, _c3, _c4, _c5, _c6 = st.columns(6)
                                _c1.metric("总收益", f"{_ret_c:+.1f}%")
                                _c2.metric("CAGR", f"{_cagr_c:+.1f}%" if _cagr_c == _cagr_c else "—")
                                _c3.metric("最大回撤", f"-{_dd_c:.1f}%")
                                _c4.metric("Calmar", _fmt_k(_kpi.get("calmar", float("nan"))))
                                _c5.metric("Sortino", _fmt_k(_kpi.get("sortino", float("nan"))))
                                _c6.metric("logR²", _fmt_k(_kpi.get("r2", float("nan"))))

                                st.plotly_chart(
                                    hv.build_combined_fig(
                                        _nav_l, _nav_r, _navc, _dyn_spy_wk,
                                        "王朝接力 — 左列+右列 50/50 合成 vs SPY",
                                    ),
                                    use_container_width=True,
                                    key=f"dyn_nav_combined_{key_suffix}",
                                )
                                st.plotly_chart(
                                    hv.build_stitched_fig(
                                        _seg_l, "王朝接力 左列 (Slot 0)",
                                        _dyn_spy_wk, _dyn_price_cache, _d_name_map,
                                    ),
                                    use_container_width=True,
                                    key=f"dyn_nav_l_{key_suffix}",
                                )
                                st.plotly_chart(
                                    hv.build_stitched_fig(
                                        _seg_r, "王朝接力 右列 (Slot 1)",
                                        _dyn_spy_wk, _dyn_price_cache, _d_name_map,
                                    ),
                                    use_container_width=True,
                                    key=f"dyn_nav_r_{key_suffix}",
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
