import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import holdings_viz as hv

_BADGE = {0: "⚪ 灰", 1: "🥉 铜", 2: "🥈 银", 3: "🥇 金"}

# 进场持续性门槛：新进场须最近 6 月内 ≥ 这么多次进过 Top2，滤掉只闪现一个月的生面孔
# （KLAC 式动量假突破：冲上榜单一个月就反转崩盘）。守擂留任不受此约束。
_ENTRY_MIN_TOP2_HITS = 2


def _crop_segments_by_slider(segs: list, spy_wk: pd.DataFrame, key: str):
    """在接力持仓段上方放一个时间窗口拉杆（同 13_C组双龙）。拖动后只留与窗口有交集的段，
    build_stitched_fig 会把窗口最左端归一为 1、SPY 同样从窗口起点对齐，方便看清早期段。"""
    _months = [pd.Timestamp(f"{s}-01") for _, s, _ in segs] + [pd.Timestamp(f"{e}-01") for _, _, e in segs]
    win_lo, win_hi = min(_months), max(_months)
    if win_lo < win_hi:
        _lo_py, _hi_py = win_lo.to_pydatetime(), win_hi.to_pydatetime()
        # key 绑定段起止：切窗口后段变了就换新 key 重置为满窗口，否则保留上一窗口选值画短段。
        _sel = st.slider(
            "分段图时间窗口（拖动重设起点，各段与 SPY 在窗口最左端对齐归一）",
            min_value=_lo_py, max_value=_hi_py, value=(_lo_py, _hi_py),
            format="YYYY-MM", key=f"{key}_seg_window_{_lo_py:%Y%m}_{_hi_py:%Y%m}",
        )
        win_lo, win_hi = pd.Timestamp(_sel[0]), pd.Timestamp(_sel[1])
    lo_m, hi_m = win_lo.strftime("%Y-%m"), win_hi.strftime("%Y-%m")
    _segs = [s for s in segs if not (s[2] < lo_m or s[1] > hi_m)]
    _spy = spy_wk
    if spy_wk is not None and not spy_wk.empty:
        _hi_end = win_hi + pd.offsets.MonthEnd(1)
        _spy = spy_wk[(spy_wk.index >= win_lo) & (spy_wk.index <= _hi_end)]
    return _segs, _spy


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
    n_hold: int = 2,
    hold_band: int = None,
    entry_min_top2_hits: int = 2,
    show_medal_table: bool = True,
    only_medaled_in_heatmap: bool = False,
    nav_engine: str = "weekly",
    daily_price_cache: dict = None,
    spy_daily: pd.DataFrame = None,
    cost_bps: float = 0.0,
    gold_needs_rs: bool = True,
    sweep_horizons: list = None,
    dynamic_n_hold: bool = False,
    max_n_hold: int = 3,
    segment_window_slider: bool = False,
    retention_mask: pd.DataFrame = None,
):
    """对一个候选子池跑完整流程：组内横截面排名 → 热力图 → 奖牌榜 → 净值重建。
    kp = 该组所有 streamlit widget / plotly key 的前缀，避免两组撞 key。
    score_m 决定排名；rs_m 只用于金牌 RS > 0 门槛（不变）。
    n_hold = 同时持有几个仓位：2 = 金+银两仓 50/50（默认，回购页用）；
             1 = 只持一仓满仓。
    hold_band = 进出场的排名带（rank ≤ band 才算在带内）。默认 = n_hold。
             设 hold_band=2 而 n_hold=1，即满仓单票但进场/守擂都按 Top2 判定：
             进场须当月 Top2，在任票没掉出 Top2(+δ) 就继续拿，换手比盯 Top1 更低。
    dynamic_n_hold = True 时，每月在 Top1-TopN 里按进场持续性动态持有 1-N 仓。
    """
    n_hold = max(1, int(n_hold))
    max_n_hold = max(1, int(max_n_hold))
    if dynamic_n_hold:
        max_n_hold = max(n_hold, max_n_hold)
        _band = max_n_hold
    else:
        max_n_hold = n_hold
        _band = max(n_hold, int(hold_band)) if hold_band else n_hold
    cols = [c for c in cols if c in score_m.columns]
    if not cols:
        st.info(f"{group_label}：无可用标的")
        return

    g_score = score_m[cols]
    # score_m / rs_m 来自不同数据源（动量走日线缓存、RS 走后端），月份网格和 ticker 集合都可能对不上。
    # 对齐到 score 的索引/列，缺的填 NaN，避免后面 hover 里 _rs_yx.loc[tk, d] 撞 KeyError。
    g_rs = rs_m.reindex(index=g_score.index, columns=cols)
    rank_m = g_score.rank(axis=1, ascending=False, method="min")
    tier = pd.DataFrame(0, index=rank_m.index, columns=rank_m.columns, dtype=int)
    if dynamic_n_hold and max_n_hold >= 3:
        tier[rank_m == 3] = 1
    tier[rank_m <= 2] = 2
    if gold_needs_rs:
        tier = tier.mask((rank_m == 1) & (g_rs > 0), 3)
        tier = tier.mask((rank_m == 1) & (g_rs <= 0), 0)
    else:
        # 已删 RS 门槛：金牌 = Top1、银牌 = Top2，金银同口径只看排名。
        tier = tier.mask(rank_m == 1, 3)

    _confirmed = tier.iloc[:-1] if month_in_progress else tier

    _gold_cnt = (_confirmed == 3).sum(axis=0)
    _silver_cnt = (_confirmed == 2).sum(axis=0)
    _bronze_cnt = (_confirmed == 1).sum(axis=0)
    _ordered = (_gold_cnt * 10000 + _silver_cnt * 100 + _bronze_cnt).sort_values(ascending=False).index.tolist()

    if only_medaled_in_heatmap:
        # 只留曾够格建仓的票：用和进场门槛一致的口径（最近 6 月内进 Top_band ≥ entry_min_top2_hits 次），
        # 滤掉只闪现一次、净值里根本没买过的生面孔，避免热力图误导。
        _entry_ok = (rank_m <= _band).astype(int).rolling(6, min_periods=1).sum().max(axis=0) >= entry_min_top2_hits
        _ordered = [tk for tk in _ordered if bool(_entry_ok.get(tk, False))]
        if not _ordered:
            _ordered = (_gold_cnt * 10000 + _silver_cnt * 100 + _bronze_cnt).sort_values(ascending=False).index.tolist()[:1]

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
            [0.0, "#2a2a2a"], [0.24, "#2a2a2a"],
            [0.25, "#CD7F32"], [0.49, "#CD7F32"],
            [0.5, "#c0c0c0"], [0.74, "#c0c0c0"],
            [0.75, "#FFD700"], [1.0, "#FFD700"],
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
    _bronze_now = _last_col[_last_col == 1].index.tolist()
    def _label(t):
        g = grade_map.get(t, "")
        return f"{t}({g})" if g else t

    _gold_html = " ".join(
        f"<span class='tag-bull'>🥇 {_label(t)}</span>" for t in _gold_now
    ) or "<span style='color:#888'>当前无金牌(无个股同时满足 Top1 + RS_210d &gt; 0)</span>"
    _silver_html = " ".join(f"<span class='tag-bear'>🥈 {_label(t)}</span>" for t in _silver_now) or "—"
    _bronze_html = " ".join(f"<span class='tag-bear'>🥉 {_label(t)}</span>" for t in _bronze_now) or "—"
    _label = "当月领先(进行中·未定格)" if month_in_progress else "当前在位"
    _bronze_line = f"&nbsp; {_bronze_html}" if dynamic_n_hold and max_n_hold >= 3 else ""
    st.markdown(f"""
<div class='insight-box'>
<div class='insight-title'>👑 {group_label}接力摘要 ({window} · {len(_xlabels)} 个月)</div>
<div style='margin-bottom:6px'>📍 {_label}({last_month.strftime('%Y-%m')}): {_gold_html} &nbsp; {_silver_html}{_bronze_line}</div>
</div>
""", unsafe_allow_html=True)

    _medal_rows = []
    _conf_yx = _confirmed[_ordered].T
    for tk in _ordered:
        trow = _conf_yx.loc[tk].values
        gold = int((trow == 3).sum())
        silver = int((trow == 2).sum())
        bronze = int((trow == 1).sum())
        streak = cur = 0
        for v in trow:
            if v == 3:
                cur += 1
                streak = max(streak, cur)
            else:
                cur = 0
        gdates = _conf_yx.loc[tk].index[_conf_yx.loc[tk].values == 3]
        row = {
            "股票": tk,
            "档位": grade_map.get(tk, ""),
            "🥇 累计金牌(月)": gold,
            "🥈 累计银牌(月)": silver,
        }
        if dynamic_n_hold and max_n_hold >= 3:
            row["🥉 累计铜牌(月)"] = bronze
        row["最长连续金"] = streak
        row["最近戴金月"] = gdates.max().strftime("%Y-%m") if len(gdates) else "—"
        _medal_rows.append(row)
    _medal_df = pd.DataFrame(_medal_rows)
    if show_medal_table:
        _rank_suffix = " → 铜牌" if dynamic_n_hold and max_n_hold >= 3 else ""
        st.markdown(f"#### 🏅 奖牌榜(按累计金牌 → 银牌{_rank_suffix}排序)")
        st.dataframe(_medal_df, use_container_width=True, hide_index=True)

    if dynamic_n_hold:
        st.markdown(f"### 📈 动态持有 Top1-Top{max_n_hold} · 净值 vs SPY")
        st.caption(
            f"每月末按 {score_label} 看组内 Top{max_n_hold}，次交易日开盘执行(去 look-ahead) · "
            f"**动态仓位**：最近 6 月内 ≥{entry_min_top2_hits} 次进 Top{max_n_hold} 的候选数决定目标仓位，最少 1 仓、最多 {max_n_hold} 仓 · "
            f"**多票并列优先连续在榜月数最长的**(更连贯新鲜)，打平看当月排名 · "
            f"**没够格不硬上**：当月没有合格新票时持现金(年化 4%) · "
            f"**守擂死区**：在任票的分数距目标仓位门槛在 δ 以内就不换，差得更多才替换 · "
            "组合按当月实际持仓等权 · 日线 NAV，执行月首个交易日 Open 买入，扣单边成本。"
        )
    elif n_hold < 2:
        st.markdown(f"### 📈 满仓单票 · 进出场按 Top{_band} 判定 · 净值 vs SPY")
        _hold_rule = (
            "**趋势留任(MA)**：在任票只要月末价 > 自己的 4 月均线就一直拿，不管别人排第几；"
            "跌破均线才腾位 · "
        ) if retention_mask is not None else (
            f"**守擂死区**：在任票只要没掉出 Top{_band} 就不换，掉出且分差超过 δ 才替换(δ = k × 当月横截面标准差) · "
        )
        st.caption(
            f"每月末按 {score_label} 看组内 Top{_band}，次交易日开盘执行(去 look-ahead) · "
            f"**进场门槛**：新进场须当月组内 Top{_band} **且最近 6 月内 ≥{entry_min_top2_hits} 次进 Top{_band}**(滤掉只闪现一个月的生面孔) · "
            f"**多票并列**：优先连续在榜月数最长的(更连贯新鲜)，打平再看当月排名 · "
            f"**没够格不硬上**：没合格 Top{_band} 就持现金(年化 4%，至少不亏本) · "
            f"{_hold_rule}"
            "满仓单票，无 50/50 · 周线 NAV，价格 yfinance 股息+拆股复权 · 净值最长回看约 10 年。"
        )
    else:
        st.markdown(f"### 📈 持有金 + 银两仓(等权)· 净值 vs SPY")
        st.caption(
            f"每月末按 {score_label} 选组内 Top2，次交易日开盘执行(去 look-ahead) · "
            "**进场门槛**：新进场须当月在组内前 2(金/银) **且最近 6 月内 ≥2 次进 Top2**(滤掉只闪现一个月的生面孔) · "
            "**多票并列**：优先连续在榜月数最长的(更连贯新鲜)，打平再看当月排名 · "
            "**没够格不硬上**：凑不满 2 仓的槽位持现金(年化 4%，至少不亏本) · "
            "**守擂死区**：在任票的分数距 Top2 门槛在 δ 以内就不换，差得更多才替换(δ = k × 当月横截面标准差) · "
            "左右两列各等权，合成线 = 50/50 · 周线 NAV，价格 yfinance 股息+拆股复权 · 净值最长回看约 10 年。"
        )
    if retention_mask is not None:
        # MA 趋势留任：留任判据不含 k，δ 死区滑块无意义，直接取默认值占位。
        _k = float(default_k)
    else:
        _k = float(st.number_input(
            f"守擂死区 δ(×当月横截面标准差,越大越不换仓; 0=掉出 Top{_band} 立刻换)",
            min_value=0.0, max_value=3.0, value=float(default_k), step=0.25, key=f"{kp}_dk",
        ))

    _entry_rank_limit = _band
    _ten6 = (rank_m <= _entry_rank_limit).astype(int).rolling(6, min_periods=1).sum()

    def _inband_streak(rank_df, limit):
        # 每月「连续在榜」月数：本月在 Top{limit} 则 = 上月 streak + 1，否则清零。
        # 用来给新进场候选按「连贯度」排序：连续在榜越久优先级越高（更新鲜、更连贯）。
        _ib = (rank_df <= limit).to_numpy()
        _arr = _ib.astype(int)
        for _i in range(1, _arr.shape[0]):
            _arr[_i] = (_arr[_i - 1] + 1) * _ib[_i]
        return pd.DataFrame(_arr, index=rank_df.index, columns=rank_df.columns)

    _streak = _inband_streak(rank_m, _entry_rank_limit)

    # δ 敏感性扫描专用的「最长历史」源：用 10Y 时序，才能切出尾部 3/5/10Y 三段。
    # 展示用的 NAV/热力图仍走当前 radio 窗口（rank_m/g_score/_ten6），二者互不污染。
    if sweep_score_m is not None and not sweep_score_m.empty:
        _cols_L = [c for c in cols if c in sweep_score_m.columns]
        _gscore_L = sweep_score_m[_cols_L]
        _rank_L = _gscore_L.rank(axis=1, ascending=False, method="min")
        _ten6_L = (_rank_L <= _entry_rank_limit).astype(int).rolling(6, min_periods=1).sum()
        _streak_L = _inband_streak(_rank_L, _entry_rank_limit)
    else:
        _gscore_L, _rank_L, _ten6_L, _streak_L = g_score, rank_m, _ten6, _streak

    def _holdings_for_k(kval, rank_src=rank_m, score_src=g_score, ten6_src=_ten6, streak_src=_streak):
        _mh, _mh_raw, _prev_h = {}, {}, []
        for _ts, _row in rank_src.iterrows():
            _r = _row.dropna().sort_values()
            if _r.empty:
                continue
            _order = _r.index.tolist()
            _tnow = ten6_src.loc[_ts]
            _snow = streak_src.loc[_ts]
            if dynamic_n_hold:
                _eligible_top = [
                    t for t in _order
                    if _r[t] <= max_n_hold and float(_tnow.get(t, 0)) >= entry_min_top2_hits
                ]
                _n_cur = max(1, min(max_n_hold, len(_eligible_top)))
                _raw = _order[:max_n_hold]
                _elig_rank_limit = max_n_hold
            else:
                _n_cur = n_hold
                _raw = _order[:_band]
                _elig_rank_limit = _band
            _sc = score_src.loc[_ts].dropna()
            if retention_mask is not None:
                # MA 趋势留任：在任票只看自己趋势没坏（月末价 > 自己 MA），不跟别人比名次，
                # 也不受进场门槛约束。跌破 MA 或掉出当月成分（分数变 NaN）才腾位。
                _hold = [t for t in _prev_h
                         if t != "CASH" and t in _sc.index and t in retention_mask.columns
                         and _ts in retention_mask.index and bool(retention_mask.at[_ts, t])][:_n_cur] if _prev_h else []
            else:
                # 守擂死区：留任阈值建在「分数」上，而非排名位置——排名会被旁边股票挤动，
                # 分差只看在任票自身离门槛多远，不被后面的股票污染。
                # 非动态时门槛建在 band 档（Top{band}）的分数上：满仓单票但 band=2 时，
                # 在任票没掉出 Top2 就留任，换手比盯 Top1 更低。
                _cut_rank = _n_cur if dynamic_n_hold else _band
                _cut2 = float(_sc.sort_values(ascending=False).iloc[_cut_rank - 1]) if len(_sc) >= _cut_rank else (
                    float(_sc.iloc[0]) if len(_sc) else float("nan"))
                _delta = kval * (float(_sc.std()) if len(_sc) >= 2 else 0.0)
                # 在任票：分数仍在死区内就留任，不受进场门槛约束（已经进来的不赶）。
                _hold = [t for t in _prev_h
                         if t != "CASH" and t in _sc.index and _sc[t] >= _cut2 - _delta][:_n_cur] if _prev_h else []
            # 新进场门槛：当月排名进入目标区间且最近 6 月内 ≥ _ENTRY_MIN_TOP2_HITS 次进过观察区间，
            # 滤掉只闪现一个月的生面孔。
            _elig = [t for t in _order
                     if _r[t] <= _elig_rank_limit and float(_tnow.get(t, 0)) >= entry_min_top2_hits]
            # 多个合格新票时，优先「连续在榜月数」最长的（更连贯、更新鲜），
            # 连贯度打平再看当月排名。避免 6 月内凑够 2 次的陈旧散点盖过当月冲上来的连续新票。
            _elig_t = sorted(_elig, key=lambda t: (-float(_snow.get(t, 0)), _r[t]))
            for t in _elig_t:
                if len(_hold) >= _n_cur:
                    break
                if t not in _hold:
                    _hold.append(t)
            # 没机会不硬上：凑不满目标仓位的槽位持现金（年化 4%，至少不亏本）。
            _hold = (_hold + ["CASH"] * _n_cur)[:_n_cur]
            _exec_m = hv.next_month_key(_ts.strftime("%Y-%m"), 1)
            _mh[_exec_m] = _hold
            _mh_raw[_exec_m] = _raw
            _prev_h = _hold
        return _mh, _mh_raw

    def _build_nav(_mh):
        _exec_months = sorted(_mh)
        if not _exec_months:
            return None
        _slot_count = max(1, max((len(v) for v in _mh.values()), default=n_hold))
        _slots = hv.build_basket_slot_assignments(_mh, _exec_months)
        _slot_segs = [hv.build_slot_segments(_slots, i, _exec_months) for i in range(_slot_count)]
        if nav_engine == "daily":
            _r = hv.build_nav_from_holdings(
                _mh, daily_price_cache or {}, spy_daily,
                top_n=None if dynamic_n_hold else n_hold, cash_rate=0.04, cost_bps=cost_bps,
            )
            _navc = _r["nav"]
            if dynamic_n_hold:
                return _exec_months, _slots, _slot_segs, pd.Series(dtype=float), pd.Series(dtype=float), _navc
            if n_hold < 2:
                return _exec_months, _slots, _slot_segs, _navc, pd.Series(dtype=float), _navc
            _mh_l = {m: [_slots.get(m, ["CASH", "CASH"])[0]] for m in _exec_months}
            _mh_r = {m: [_slots.get(m, ["CASH", "CASH"])[1]] for m in _exec_months}
            _nav_l = hv.build_nav_from_holdings(
                _mh_l, daily_price_cache or {}, spy_daily,
                top_n=1, cash_rate=0.04, cost_bps=cost_bps,
            )["nav"]
            _nav_r = hv.build_nav_from_holdings(
                _mh_r, daily_price_cache or {}, spy_daily,
                top_n=1, cash_rate=0.04, cost_bps=cost_bps,
            )["nav"]
            return _exec_months, _slots, _slot_segs, _nav_l, _nav_r, _navc
        if not price_cache:
            return None
        _seg_l = _slot_segs[0]
        _nav_l = hv.calc_slot_stats(_seg_l, price_cache, spy_wk, 0.04)[2]
        if n_hold < 2:
            # 单仓：满仓 Top1，净值 = 左列，不掺现金、不做 50/50。
            return _exec_months, _slots, _slot_segs, _nav_l, pd.Series(dtype=float), _nav_l.copy()
        _seg_r = _slot_segs[1]
        _nav_r = hv.calc_slot_stats(_seg_r, price_cache, spy_wk, 0.04)[2]
        _navc = pd.Series(dtype=float)
        if not _nav_l.empty and not _nav_r.empty:
            _uidx = _nav_l.index.union(_nav_r.index)
            _navc = 0.5 * _nav_l.reindex(_uidx).ffill().bfill() + 0.5 * _nav_r.reindex(_uidx).ffill().bfill()
        elif not _nav_l.empty:
            _navc = _nav_l.copy()
        elif not _nav_r.empty:
            _navc = _nav_r.copy()
        return _exec_months, _slots, _slot_segs, _nav_l, _nav_r, _navc

    # ── δ 跨 3/5/10Y 稳健性扫描：用最长历史建净值，按尾部 3/5/10Y 各算总收益。
    #    单段峰值 = 过拟合（短窗口噪声最大）；找三段都不差的 δ（plateau 重叠）才稳健。──
    # MA 趋势留任模式下留任判据不含 k，扫描无意义 → 空网格跳过，后面不渲染扫描图。
    _k_grid = [] if retention_mask is not None else [round(x * 0.25, 2) for x in range(13)]
    _HZ = sweep_horizons or [("3Y", 3), ("5Y", 5), ("10Y", 10)]

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
        _rk = _build_nav(_holdings_for_k(_kv, _rank_L, _gscore_L, _ten6_L, _streak_L)[0])
        _nav_kv = _rk[5] if (_rk is not None) else None
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

    _COLOR = {"3Y": "#5DADE2", "5Y": "#FFD700", "9Y": "#E67E22", "10Y": "#E67E22"}
    _sweep_fig = go.Figure()
    for lbl, _ in _HZ:
        if pd.Series(_curves[lbl]).notna().sum() < 2:
            continue
        _lw = 4 if lbl == "3Y" else 2  # 3Y 加粗，避免和 5Y 归一化曲线重合时被金线整条盖住
        _sweep_fig.add_trace(go.Scatter(
            x=_k_grid, y=list(_norm[lbl]), mode="lines+markers", name=lbl,
            line=dict(color=_COLOR.get(lbl, "#E67E22"), width=_lw), marker=dict(size=5),
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
            text=f"δ 稳健性 · 尾部 {'/'.join(l for l, _ in _HZ)} 总收益（各自归一化；三线齐高处=稳健 δ；灰点线=当前 δ）",
            font=dict(size=13), x=0.01, xanchor="left",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
    )
    if retention_mask is None:
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
            st.caption(f"⚠️ 净值历史不足，无法跨 {'/'.join(l for l, _ in _HZ)} 比较 δ（多为长窗口数据未就绪）。")

    _mh, _mh_raw = _holdings_for_k(_k)
    _nav = _build_nav(_mh)
    if _nav is None:
        st.info("价格数据不足，无法重建净值。")
        return
    _exec_months, _slots, _slot_segs, _nav_l, _nav_r, _navc = _nav

    if _navc.empty:
        st.info("价格窗口内无足够数据生成净值曲线。")
        return

    _ret_c = (float(_navc.iloc[-1]) / float(_navc.iloc[0]) - 1) * 100
    _peak = _navc.cummax()
    _dd_c = float(((_peak - _navc) / _peak.replace(0, float("nan"))).max()) * 100
    _nav_for_kpi = _navc.resample("W-FRI").last().dropna() if nav_engine == "daily" else _navc
    _kpi = hv.compute_nav_kpi(_nav_for_kpi)

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

    if dynamic_n_hold:
        st.plotly_chart(
            hv.build_basket_fig(_navc, spy_wk, f"{group_label} 动态 Top1-Top{max_n_hold} — 净值 vs SPY"),
            use_container_width=True, key=f"{kp}_nav_combined",
        )
        for _i, _seg in enumerate(_slot_segs[:max_n_hold]):
            st.plotly_chart(
                hv.build_stitched_fig(_seg, f"{group_label}接力 槽{_i + 1}", spy_wk, price_cache, name_map, grade_map),
                use_container_width=True, key=f"{kp}_nav_slot_{_i}",
            )
    elif n_hold < 2:
        st.plotly_chart(
            hv.build_basket_fig(_navc, spy_wk, f"{group_label} Top1 满仓 — 净值 vs SPY"),
            use_container_width=True, key=f"{kp}_nav_combined",
        )
        _seg0, _spy_seg = _slot_segs[0], spy_wk
        if segment_window_slider and _seg0:
            _seg0, _spy_seg = _crop_segments_by_slider(_seg0, spy_wk, kp)
        st.plotly_chart(
            hv.build_stitched_fig(_seg0, f"{group_label}接力 持仓段", _spy_seg, price_cache, name_map, grade_map),
            use_container_width=True, key=f"{kp}_nav_l",
        )
    else:
        st.plotly_chart(
            hv.build_combined_fig(_nav_l, _nav_r, _navc, spy_wk, f"{group_label} Top2 — 左右两列 50/50 合成 vs SPY"),
            use_container_width=True, key=f"{kp}_nav_combined",
        )
        st.plotly_chart(
            hv.build_stitched_fig(_slot_segs[0], f"{group_label}接力 左列 (Slot 0)", spy_wk, price_cache, name_map, grade_map),
            use_container_width=True, key=f"{kp}_nav_l",
        )
        st.plotly_chart(
            hv.build_stitched_fig(_slot_segs[1], f"{group_label}接力 右列 (Slot 1)", spy_wk, price_cache, name_map, grade_map),
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
        if dynamic_n_hold:
            _held = [t for t in _sa[:max_n_hold] if t and t != "CASH"]
            _kept = bool(_raw) and any(t not in set(_raw) for t in _held)
            _pick_rows.append({
                "来源月 Top1": _nmg(_raw[0] if len(_raw) > 0 else None),
                "来源月 Top2": _nmg(_raw[1] if len(_raw) > 1 else None),
                "来源月 Top3": _nmg(_raw[2] if len(_raw) > 2 else None),
                "执行月": _em,
                "实际仓位数": len(_held),
                "实际持有": " / ".join(_nmg(t) for t in _held) or "—",
                "守擂留任": "是" if _kept else "",
            })
        elif n_hold < 2:
            _hticker = _sa[0] if (_sa[0] and _sa[0] != "CASH") else None
            _kept = _hticker is not None and _hticker != (_raw[0] if _raw else None)
            _pick_rows.append({
                "来源月 Top1": _nmg(_raw[0] if len(_raw) > 0 else None),
                "来源月 Top2": _nmg(_raw[1] if len(_raw) > 1 else None),
                "执行月": _em,
                "实际持有": _nmg(_sa[0]),
                "守擂留任(非当月Top1)": "是" if _kept else "",
            })
        else:
            _held = {t for t in _sa[:n_hold] if t and t != "CASH"}
            _kept = bool(_raw) and _held != set(_raw[:n_hold])
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
