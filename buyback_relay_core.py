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
    default_k: float = 1.0,
    sweep_score_m: pd.DataFrame = None,
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
    _ylabels = [f"{tk}({grade_map.get(tk, '')})" if grade_map.get(tk) else tk for tk in _ordered]

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
                f"<b>{tk}</b><br>"
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
    def _label(t):
        g = grade_map.get(t, "")
        return f"{t}({g})" if g else t

    _gold_html = " ".join(
        f"<span class='tag-bull'>🥇 {_label(t)}</span>" for t in _gold_now
    ) or "<span style='color:#888'>当前无金牌(无个股同时满足 Top1 + RS_210d &gt; 0)</span>"
    _silver_html = " ".join(f"<span class='tag-bear'>🥈 {_label(t)}</span>" for t in _silver_now) or "—"
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
            "股票": tk,
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
        "**守擂死区**：在任票的分数距 Top2 门槛在 δ 以内就不换，差得更多才替换(δ = k × 当月横截面标准差) · "
        "左右两列各等权，合成线 = 50/50 · 周线 NAV，价格 yfinance 股息+拆股复权 · 净值最长回看约 10 年。"
    )
    _k = float(st.number_input(
        "守擂死区 δ(×当月横截面标准差,越大越不换仓; 0=掉出 Top2 立刻换)",
        min_value=0.0, max_value=3.0, value=float(default_k), step=0.25, key=f"{kp}_dk",
    ))

    _ten6 = (rank_m <= 2).astype(int).rolling(6, min_periods=1).sum()

    # δ 敏感性扫描专用的「最长历史」源：用 10Y 时序，才能切出尾部 3/5/10Y 三段。
    # 展示用的 NAV/热力图仍走当前 radio 窗口（rank_m/g_score/_ten6），二者互不污染。
    if sweep_score_m is not None and not sweep_score_m.empty:
        _cols_L = [c for c in cols if c in sweep_score_m.columns]
        _gscore_L = sweep_score_m[_cols_L]
        _rank_L = _gscore_L.rank(axis=1, ascending=False, method="min")
        _ten6_L = (_rank_L <= 2).astype(int).rolling(6, min_periods=1).sum()
    else:
        _gscore_L, _rank_L, _ten6_L = g_score, rank_m, _ten6

    def _holdings_for_k(kval, rank_src=rank_m, score_src=g_score, ten6_src=_ten6):
        _mh, _mh_raw, _prev_h = {}, {}, []
        for _ts, _row in rank_src.iterrows():
            _r = _row.dropna().sort_values()
            if _r.empty:
                continue
            _order = _r.index.tolist()
            _t2 = _order[:2]
            _sc = score_src.loc[_ts].dropna()
            # 守擂死区：留任阈值建在「分数」上，而非排名位置——排名会被旁边股票挤动，
            # 分差只看在任票自身离 Top2 门槛多远，不被第三只股票污染。
            _cut2 = float(_sc.sort_values(ascending=False).iloc[1]) if len(_sc) >= 2 else (
                float(_sc.iloc[0]) if len(_sc) else float("nan"))
            _delta = kval * (float(_sc.std()) if len(_sc) >= 2 else 0.0)
            _tnow = ten6_src.loc[_ts]
            _elig = [t for t in _order if _r[t] <= 2]
            _elig_t = sorted(_elig, key=lambda t: (-float(_tnow.get(t, 0)), _r[t]))
            _hold = [t for t in _prev_h if t in _sc.index and _sc[t] >= _cut2 - _delta][:2] if _prev_h else []
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
        return _mh, _mh_raw

    def _build_nav(_mh):
        _exec_months = sorted(_mh)
        if not price_cache or not _exec_months:
            return None
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
        return _exec_months, _slots, _seg_l, _seg_r, _nav_l, _nav_r, _navc

    # ── δ 跨 3/5/10Y 稳健性扫描：用最长历史建净值，按尾部 3/5/10Y 各算总收益。
    #    单段峰值 = 过拟合（短窗口噪声最大）；找三段都不差的 δ（plateau 重叠）才稳健。──
    _k_grid = [round(x * 0.25, 2) for x in range(13)]  # 0.00 → 3.00 步长 0.25
    _HZ = [("3Y", 3), ("5Y", 5), ("10Y", 10)]

    def _trail_ret(_nav_s, _yrs):
        # 长度不够这段窗口就返回 NaN，不拿短历史冒充长窗口
        if _nav_s is None or _nav_s.empty:
            return float("nan")
        _end = _nav_s.index[-1]
        if (_end - _nav_s.index[0]).days < _yrs * 365.25 * 0.9:
            return float("nan")
        _seg = _nav_s[_nav_s.index >= _end - pd.DateOffset(years=_yrs)]
        if len(_seg) < 2:
            return float("nan")
        return (float(_seg.iloc[-1]) / float(_seg.iloc[0]) - 1) * 100

    _curves = {lbl: [] for lbl, _ in _HZ}
    for _kv in _k_grid:
        _rk = _build_nav(_holdings_for_k(_kv, _rank_L, _gscore_L, _ten6_L)[0])
        _nav_kv = _rk[6] if (_rk is not None) else None
        for lbl, yrs in _HZ:
            _curves[lbl].append(_trail_ret(_nav_kv, yrs))

    # 各段在网格内转百分位（抗量级差/负收益）；稳健分 = 三段百分位取最小（maximin）
    _valid_hz = [lbl for lbl, _ in _HZ if pd.Series(_curves[lbl]).notna().sum() >= 2]
    _robust = pd.Series([float("nan")] * len(_k_grid))
    if _valid_hz:
        _pct_stack = pd.concat([pd.Series(_curves[l]).rank(pct=True) for l in _valid_hz], axis=1)
        _robust = _pct_stack.min(axis=1)  # 任一段 NaN → 该 δ 不可比 → NaN

    # 各段归一化到自身峰值（形状可比，重叠平台一眼可见 + 算跨段离散）
    _norm = {}
    for lbl, _ in _HZ:
        _c = pd.Series(_curves[lbl])
        _mx = _c.max()
        _norm[lbl] = (_c / _mx) if (_mx == _mx and _mx > 0) else _c * float("nan")

    # 推荐 δ*：稳健分最高；并列先挑跨段离散最小（抖动小），再挑更大 δ（换手低）
    _rec_k = None
    if _robust.notna().any() and _valid_hz:
        _spread = pd.concat([_norm[l] for l in _valid_hz], axis=1)
        _spread = _spread.max(axis=1) - _spread.min(axis=1)
        _best = _robust.max()
        _cand = [i for i in range(len(_k_grid)) if _robust[i] == _robust[i] and _robust[i] >= _best - 1e-9]
        _cand.sort(key=lambda i: (_spread[i] if _spread[i] == _spread[i] else 9e9, -_k_grid[i]))
        _rec_k = _k_grid[_cand[0]]

    _COLOR = {"3Y": "#5DADE2", "5Y": "#FFD700", "10Y": "#E67E22"}
    _sweep_fig = go.Figure()
    for lbl, _ in _HZ:
        if pd.Series(_curves[lbl]).notna().sum() < 2:
            continue
        _sweep_fig.add_trace(go.Scatter(
            x=_k_grid, y=list(_norm[lbl]), mode="lines+markers", name=lbl,
            line=dict(color=_COLOR[lbl], width=2), marker=dict(size=5),
            customdata=_curves[lbl],
            hovertemplate=f"{lbl} δ=%{{x}} → 总收益 %{{customdata:.1f}}%<extra></extra>",
        ))
    if _rec_k is not None:
        _sweep_fig.add_vline(x=_rec_k, line=dict(color="#2ECC71", width=2, dash="dash"))
        _sweep_fig.add_annotation(
            x=_rec_k, y=1.02, yref="paper", text=f"推荐 δ*={_rec_k}", showarrow=False,
            font=dict(color="#2ECC71", size=12), bgcolor="#111", xanchor="left",
        )
    _sweep_fig.add_vline(x=_k, line=dict(color="#888", width=1, dash="dot"))
    _sweep_fig.update_layout(
        height=300, margin=dict(l=20, r=20, t=46, b=20),
        plot_bgcolor="#111111", paper_bgcolor="#111111", font=dict(color="#ddd"),
        xaxis=dict(title="δ (×横截面标准差)", showgrid=True, gridcolor="#222", dtick=0.25),
        yaxis=dict(title="各段归一化收益 (÷自身峰值)", showgrid=True, gridcolor="#222"),
        title=dict(
            text="δ 稳健性 · 尾部 3/5/10Y 总收益（各自归一化；三线齐高处=稳健 δ；灰点线=当前 δ）",
            font=dict(size=13), x=0.01, xanchor="left",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
    )
    st.plotly_chart(_sweep_fig, use_container_width=True, key=f"{kp}_dk_sweep")

    def _argmax_k(lbl):
        _c = pd.Series(_curves[lbl])
        return _k_grid[int(_c.idxmax())] if _c.notna().any() else None

    _peaks = " · ".join(f"{lbl} 单峰 δ={_argmax_k(lbl)}" for lbl, _ in _HZ if _argmax_k(lbl) is not None)
    if _rec_k is not None:
        st.caption(
            f"✅ **推荐 δ\\* = {_rec_k}**（三段都不差的重叠平台，跨窗口稳健；当前 δ={_k}）。"
            f"对照各段单独最优：{_peaks}——单段峰值各不相同正是过拟合的症状，别照搬，按 δ\\* 钉死。"
        )
    else:
        st.caption("⚠️ 净值历史不足，无法跨 3/5/10Y 比较 δ（多为长窗口数据未就绪）。")

    _mh, _mh_raw = _holdings_for_k(_k)
    _nav = _build_nav(_mh)
    if _nav is None:
        st.info("价格数据不足，无法重建净值。")
        return
    _exec_months, _slots, _seg_l, _seg_r, _nav_l, _nav_r, _navc = _nav

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
        return t if (t and t != "CASH") else "—"

    def _nmg(t):
        if not t or t == "CASH":
            return "—"
        g = grade_map.get(t, "")
        return f"{t}({g})" if g else t

    _pick_rows = []
    for _em in _exec_months:
        _sa = _slots.get(_em, ["—", "—"])
        _raw = _mh_raw.get(_em, [])
        _held = {t for t in _sa if t and t != "CASH"}
        _kept = bool(_raw) and _held != set(_raw)
        _pick_rows.append({
            "来源月 Top1(金)": _nmg(_raw[0] if len(_raw) > 0 else None),
            "来源月 Top2(银)": _nmg(_raw[1] if len(_raw) > 1 else None),
            "执行月": _em,
            "左列实际持有": _nmg(_sa[0]),
            "右列实际持有": _nmg(_sa[1]),
            "守擂留任": "是" if _kept else "",
        })
    st.markdown("**每月实际持仓**(对照上方接力图核对；执行月 = 来源月 + 1)")
    st.dataframe(pd.DataFrame(_pick_rows).iloc[::-1], use_container_width=True, hide_index=True)
