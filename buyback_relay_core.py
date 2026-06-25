import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import holdings_viz as hv

_BADGE = {0: "⚪ 灰", 2: "🥈 银", 3: "🥇 金"}


def render_group(
    group_label: str,
    cols: list,
    kp: str,
    *,
    score_m: pd.DataFrame,
    rs_m: pd.DataFrame,
    king_m: pd.DataFrame,
    name_map: dict,
    grade_map: dict,
    window: str,
    month_in_progress: bool,
    last_month,
    price_cache: dict,
    spy_wk: pd.DataFrame,
    score_label: str = "king_score",
    score_fmt: str = "{:+.2f}",
):
    """对一个候选子池跑完整流程：组内横截面排名 → 热力图 → 奖牌榜 → 净值重建。
    kp = 该组所有 streamlit widget / plotly key 的前缀，避免两组撞 key。
    score_m 决定排名；rs_m 只用于金牌 RS > 0 门槛（不变）。
    """
    cols = [c for c in cols if c in score_m.columns]
    if not cols:
        st.info(f"{group_label}：无可用标的")
        return

    g_score = score_m[cols]
    g_rs = rs_m[cols]
    rank_m = g_score.rank(axis=1, ascending=False, method="min")
    tier = pd.DataFrame(0, index=rank_m.index, columns=rank_m.columns, dtype=int)
    tier[rank_m <= 2] = 2
    tier = tier.mask((rank_m == 1) & (g_rs > 0), 3)
    tier = tier.mask((rank_m == 1) & (g_rs <= 0), 0)

    _confirmed = tier.iloc[:-1] if month_in_progress else tier

    _gold_cnt = (_confirmed == 3).sum(axis=0)
    _silver_cnt = (_confirmed == 2).sum(axis=0)
    _ordered = (_gold_cnt * 10000 + _silver_cnt).sort_values(ascending=False).index.tolist()

    _tier_yx = tier[_ordered].T
    _rank_yx = rank_m[_ordered].T
    _rs_yx = g_rs[_ordered].T
    _score_yx = g_score[_ordered].T
    _ylabels = [f"{name_map.get(tk, tk)} ({tk})" for tk in _ordered]

    _hover = []
    for tk in _ordered:
        row = []
        for d in _tier_yx.columns:
            t = int(_tier_yx.loc[tk, d])
            rk = _rank_yx.loc[tk, d]
            rsv = _rs_yx.loc[tk, d]
            sv = _score_yx.loc[tk, d]
            _ip = "（进行中）" if (month_in_progress and d == last_month) else ""
            _rk_s = f"第 {int(rk)}" if pd.notna(rk) else "—"
            try:
                _sv_s = score_fmt.format(sv) if pd.notna(sv) else "—"
            except (TypeError, ValueError):
                _sv_s = "—"
            _rs_s = f"{rsv:+.2f}%" if pd.notna(rsv) else "—"
            row.append(
                f"<b>{name_map.get(tk, tk)} ({tk})</b><br>"
                f"{d.strftime('%Y-%m')}{_ip}<br>"
                f"{_BADGE[t]}<br>"
                f"排名 {_rk_s}<br>"
                f"{score_label} {_sv_s}<br>"
                f"RS_210d {_rs_s}"
            )
        _hover.append(row)

    _xlabels = [
        (f"{d.strftime('%Y-%m')} (进行中)" if (month_in_progress and d == last_month) else d.strftime("%Y-%m"))
        for d in _tier_yx.columns
    ]

    fig = go.Figure(data=go.Heatmap(
        z=_tier_yx.values,
        x=list(_tier_yx.columns),
        y=_ylabels,
        colorscale=[
            [0.0, "#2a2a2a"], [0.6, "#2a2a2a"],
            [0.6, "#c0c0c0"], [0.9, "#c0c0c0"],
            [0.9, "#FFD700"], [1.0, "#FFD700"],
        ],
        zmin=0, zmax=3,
        customdata=np.array(_hover, dtype=object),
        hovertemplate="%{customdata}<extra></extra>",
        showscale=False, xgap=1, ygap=1,
    ))
    fig.update_layout(
        height=max(400, 24 * len(_ordered)),
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="#111111", paper_bgcolor="#111111",
        font=dict(color="#ddd"),
        xaxis=dict(showgrid=False, side="bottom", tickangle=-45),
        yaxis=dict(showgrid=False, autorange="reversed"),
        title=dict(
            text=f"{window} 月末{group_label}接力 · 组内 {score_label} 排名 · {len(_ordered)} 只 · {len(_xlabels)} 月",
            font=dict(size=14), x=0.01, xanchor="left",
        ),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{kp}_heatmap")

    _last_col = _tier_yx[last_month]
    _gold_now = _last_col[_last_col == 3].index.tolist()
    _silver_now = _last_col[_last_col == 2].index.tolist()
    _gold_html = " ".join(
        f"<span class='tag-bull'>🥇 {name_map.get(t, t)} ({t})</span>" for t in _gold_now
    ) or "<span style='color:#888'>当前无金牌(无个股同时满足 Top1 + RS_210d &gt; 0)</span>"
    _silver_html = " ".join(f"<span class='tag-bear'>🥈 {name_map.get(t, t)} ({t})</span>" for t in _silver_now) or "—"
    _label = "当月领先(进行中·未定格)" if month_in_progress else "当前在位"
    st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>👑 {group_label}接力摘要 ({window} · {len(_xlabels)} 个月)</div>
<div style='margin-bottom:6px'>📍 {_label}({last_month.strftime('%Y-%m')}): {_gold_html} &nbsp; {_silver_html}</div>
</div>
""", unsafe_allow_html=True)

    _medal_rows = []
    _conf_yx = _confirmed[_ordered].T
    for tk in _ordered:
        trow = _conf_yx.loc[tk].values
        gold = int((trow == 3).sum())
        silver = int((trow == 2).sum())
        streak = cur = 0
        for v in trow:
            if v == 3:
                cur += 1
                streak = max(streak, cur)
            else:
                cur = 0
        gdates = _conf_yx.loc[tk].index[_conf_yx.loc[tk].values == 3]
        _medal_rows.append({
            "股票": name_map.get(tk, tk),
            "代码": tk,
            "档位": grade_map.get(tk, ""),
            "🥇 累计金牌(月)": gold,
            "🥈 累计银牌(月)": silver,
            "最长连续金": streak,
            "最近戴金月": gdates.max().strftime("%Y-%m") if len(gdates) else "—",
        })
    _medal_df = pd.DataFrame(_medal_rows)
    st.markdown("#### 🏅 奖牌榜(按累计金牌 → 银牌排序)")
    st.dataframe(_medal_df, use_container_width=True, hide_index=True)

    st.markdown(f"### 📈 持有金 + 银两仓(等权)· 净值 vs SPY")
    st.caption(
        f"每月末按 {score_label} 选组内 Top2，顺延 1 月执行(去 look-ahead) · **进场门槛**：新进场必须当月在组内前 2(金/银) · "
        "**守擂防抖**：在任票掉到第 N 名以内不换，掉出才替换 · 左右两列各等权，合成线 = 50/50 · "
        "周线 NAV，价格 yfinance 股息+拆股复权 · 净值最长回看约 10 年。"
    )
    _buf = int(st.number_input("守擂缓冲区 Top-N(≥2,越大越不换仓)", min_value=2, max_value=10, value=4, step=1, key=f"{kp}_buf"))

    _ten6 = (rank_m <= 2).astype(int).rolling(6, min_periods=1).sum()
    _mh: dict = {}
    _mh_raw: dict = {}
    _prev_h: list = []
    for _ts, _row in rank_m.iterrows():
        _r = _row.dropna().sort_values()
        if _r.empty:
            continue
        _order = _r.index.tolist()
        _t2 = _order[:2]
        _tN = set(_order[:_buf])
        _tnow = _ten6.loc[_ts]
        _elig = [t for t in _order if _r[t] <= 2]
        _elig_t = sorted(_elig, key=lambda t: (-float(_tnow.get(t, 0)), _r[t]))
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
        _mh_raw[_exec_m] = _t2
        _prev_h = _hold

    _exec_months = sorted(_mh)
    if not price_cache or not _exec_months:
        st.info("价格数据不足，无法重建净值。")
        return

    _slots = hv.build_basket_slot_assignments(_mh, _exec_months)
    _seg_l = hv.build_slot_segments(_slots, 0, _exec_months)
    _seg_r = hv.build_slot_segments(_slots, 1, _exec_months)
    _nav_l = hv.calc_slot_stats(_seg_l, price_cache, spy_wk, 0.04)[2]
    _nav_r = hv.calc_slot_stats(_seg_r, price_cache, spy_wk, 0.04)[2]

    _navc = pd.Series(dtype=float)
    if not _nav_l.empty and not _nav_r.empty:
        _uidx = _nav_l.index.union(_nav_r.index)
        _navc = 0.5 * _nav_l.reindex(_uidx).ffill().bfill() + 0.5 * _nav_r.reindex(_uidx).ffill().bfill()
    elif not _nav_l.empty:
        _navc = _nav_l.copy()
    elif not _nav_r.empty:
        _navc = _nav_r.copy()

    if _navc.empty:
        st.info("价格窗口内无足够数据生成净值曲线。")
        return

    _ret_c = (float(_navc.iloc[-1]) / float(_navc.iloc[0]) - 1) * 100
    _peak = _navc.cummax()
    _dd_c = float(((_peak - _navc) / _peak.replace(0, float("nan"))).max()) * 100
    _kpi = hv.compute_nav_kpi(_navc)

    def _fmt(v, f=".2f"):
        try:
            if isinstance(v, float) and (v != v or abs(v) == float("inf")):
                return "—"
            return f"{v:{f}}"
        except (TypeError, ValueError):
            return "—"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("总收益", f"{_ret_c:+.1f}%")
    c2.metric("最大回撤", f"-{_dd_c:.1f}%")
    _cagr_v = _kpi.get("cagr", float("nan"))
    c3.metric("CAGR", f"{_cagr_v * 100:+.1f}%" if not (_cagr_v != _cagr_v) else "—")
    c4.metric("Calmar", _fmt(_kpi.get("calmar", float("nan"))))
    c5.metric("Sortino", _fmt(_kpi.get("sortino", float("nan"))))
    c6.metric("logR²", _fmt(_kpi.get("r2", float("nan"))))

    st.plotly_chart(
        hv.build_combined_fig(_nav_l, _nav_r, _navc, spy_wk, f"{group_label} Top2 — 左右两列 50/50 合成 vs SPY"),
        use_container_width=True, key=f"{kp}_nav_combined",
    )
    st.plotly_chart(
        hv.build_stitched_fig(_seg_l, f"{group_label}接力 左列 (Slot 0)", spy_wk, price_cache, name_map),
        use_container_width=True, key=f"{kp}_nav_l",
    )
    st.plotly_chart(
        hv.build_stitched_fig(_seg_r, f"{group_label}接力 右列 (Slot 1)", spy_wk, price_cache, name_map),
        use_container_width=True, key=f"{kp}_nav_r",
    )

    def _nm(t):
        return f"{name_map.get(t, t)} ({t})" if (t and t != "CASH") else "—"

    _pick_rows = []
    for _em in _exec_months:
        _sa = _slots.get(_em, ["—", "—"])
        _raw = _mh_raw.get(_em, [])
        _held = {t for t in _sa if t and t != "CASH"}
        _kept = bool(_raw) and _held != set(_raw)
        _pick_rows.append({
            "来源月 Top1(金)": _nm(_raw[0] if len(_raw) > 0 else None),
            "来源月 Top2(银)": _nm(_raw[1] if len(_raw) > 1 else None),
            "执行月": _em,
            "左列实际持有": _nm(_sa[0]),
            "右列实际持有": _nm(_sa[1]),
            "守擂留任": "是" if _kept else "",
        })
    st.markdown("**每月实际持仓**(对照上方接力图核对；执行月 = 来源月 + 1)")
    st.dataframe(pd.DataFrame(_pick_rows).iloc[::-1], use_container_width=True, hide_index=True)
