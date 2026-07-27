"""Page 13: clean seven-period fixed-K momentum experiment."""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import holdings_viz as hv
from api_client import fetch_dynasty_double_dragon_momentum_periods


PERIOD_LABELS = {
    "1_0": "1M / 1-0",
    "3_0": "3M / 3-0",
    "6_0": "6M / 6-0",
    "12_0": "12M / 12-0",
    "3_1": "3-1",
    "6_1": "6-1",
    "12_1": "12-1",
}
PERIOD_COLORS = {
    "1_0": "#4C78A8", "3_0": "#F58518", "6_0": "#E45756",
    "12_0": "#72B7B2", "3_1": "#54A24B", "6_1": "#EECA3B",
    "12_1": "#B279A2",
}
FORMULAS = {
    "1_0": "P(t) / P(t-21) - 1",
    "3_0": "P(t) / P(t-63) - 1",
    "6_0": "P(t) / P(t-126) - 1",
    "12_0": "P(t) / P(t-252) - 1",
    "3_1": "P(t-21) / P(t-63) - 1",
    "6_1": "P(t-21) / P(t-126) - 1",
    "12_1": "P(t-21) / P(t-252) - 1",
}
_DEFAULT_STAGE_PERIODS = ["12_1", "12_0", "6_0"]
_SLOT_LABELS = ["槽A", "槽B", "槽C", "槽D", "槽E"]


def _pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value) * 100:.{digits}f}%"


def _equity_stats(dates, values) -> dict:
    frame = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "value": pd.to_numeric(pd.Series(values), errors="coerce"),
    }).dropna()
    if len(frame) < 2 or float(frame["value"].iloc[0]) <= 0:
        return {}
    first, last = float(frame["value"].iloc[0]), float(frame["value"].iloc[-1])
    years = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days / 365.2425, 1 / 365.2425)
    cagr = (last / first) ** (1 / years) - 1
    max_dd = float((frame["value"] / frame["value"].cummax() - 1).min())
    return {
        "cum_return": last / first - 1,
        "cagr": cagr,
        "max_dd": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else None,
    }


def _catalog(data: dict, result: dict) -> dict:
    fixed_k = (data.get("config") or {}).get("fixed_k")
    catalog = {}
    for period, label in PERIOD_LABELS.items():
        payload = (result.get("fixed_variants") or {}).get(period) or {}
        catalog[period] = {
            "label": f"{label} · 固定K{fixed_k}",
            "equity": payload.get("equity") or [],
            "stats": payload.get("stats") or {},
            "line": dict(color=PERIOD_COLORS[period], width=2.1),
            "k_basis": f"固定K={fixed_k}",
        }
    catalog["spy"] = {
        "label": "SPY", "equity": result.get("spy") or [],
        "stats": _equity_stats(result.get("dates") or [], result.get("spy") or []),
        "line": dict(color="#A0A0A0", width=1.5), "k_basis": "—",
    }
    for period, payload in (result.get("in_sample_upper_bounds") or {}).items():
        k = payload.get("k")
        catalog[f"best_{period}"] = {
            "label": f"{PERIOD_LABELS[period]} · 完整窗口最佳K{k}（样本内上限）",
            "equity": payload.get("equity") or [], "stats": payload.get("stats") or {},
            "line": dict(color=PERIOD_COLORS[period], width=1.3, dash="dash"),
            "k_basis": f"完整窗口最佳K={k}",
        }
    return catalog


def _stats_frame(catalog: dict, selected: list[str]) -> pd.DataFrame:
    rows = []
    for key in selected:
        item = catalog.get(key) or {}
        stats = item.get("stats") or {}
        rows.append({
            "曲线": item.get("label", key), "K口径": item.get("k_basis", "—"),
            "累计收益": _pct(stats.get("cum_return")), "CAGR": _pct(stats.get("cagr")),
            "最大回撤": _pct(stats.get("max_dd")),
            "Calmar": None if stats.get("calmar") is None else round(float(stats["calmar"]), 2),
            "换仓次数": stats.get("n_swaps"), "年换手": _pct(stats.get("ann_turnover")),
            "平均持有(月)": stats.get("avg_hold_months"),
        })
    return pd.DataFrame(rows)


def _holding_ticker(cell: dict | None) -> str:
    if not cell or cell.get("bil") or cell.get("ticker") == "BIL":
        return "CASH"
    return str(cell.get("ticker") or "CASH")


def _slot_stage_segments(timeline: list[dict], slot: int, final_date: pd.Timestamp) -> list[tuple]:
    """Collapse monthly post-execution holdings into exact dated ticker stages."""
    changes: list[tuple[pd.Timestamp, str]] = []
    for row in timeline:
        start = pd.to_datetime(row.get("execution_date"), errors="coerce")
        if pd.isna(start):
            continue
        cells = row.get("slots") or []
        ticker = _holding_ticker(cells[slot] if slot < len(cells) else None)
        if not changes or ticker != changes[-1][1]:
            changes.append((pd.Timestamp(start), ticker))
    return [
        (ticker, start, changes[i + 1][0] if i + 1 < len(changes) else final_date)
        for i, (start, ticker) in enumerate(changes)
        if start <= final_date
    ]


def _stage_figure(
    dates: pd.DatetimeIndex,
    slot_equity: list,
    spy_equity: list,
    timeline: list[dict],
    slot: int,
    title: str,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
) -> go.Figure:
    frame = pd.DataFrame({
        "date": dates,
        "slot": pd.to_numeric(pd.Series(slot_equity), errors="coerce"),
        "spy": pd.to_numeric(pd.Series(spy_equity), errors="coerce"),
    }).dropna(subset=["date", "slot"])
    frame = frame[(frame["date"] >= window_start) & (frame["date"] <= window_end)]
    fig = go.Figure()
    if frame.empty:
        return fig
    frame["slot"] = frame["slot"] / float(frame["slot"].iloc[0])
    if frame["spy"].notna().any():
        first_spy = float(frame["spy"].dropna().iloc[0])
        frame["spy"] = frame["spy"] / first_spy

    segments = _slot_stage_segments(timeline, slot, frame["date"].max())
    visible_segments = []
    for ticker, start, end in segments:
        start = max(pd.Timestamp(start), window_start)
        end = min(pd.Timestamp(end), window_end)
        if start > end:
            continue
        seg = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        if seg.empty:
            continue
        visible_segments.append((ticker, start, end, seg))

    annotations = []
    tickvals, ticktexts = [], []
    for i, (ticker, start, end, seg) in enumerate(visible_segments):
        color = "#BBBBBB" if ticker == "CASH" else hv.SLOT_COLORS[i % len(hv.SLOT_COLORS)]
        line = dict(color=color, width=2.2)
        if ticker == "CASH":
            line["dash"] = "dot"
        fig.add_trace(go.Scatter(
            x=seg["date"], y=seg["slot"], mode="lines", line=line,
            name=f"{ticker} · {start:%Y-%m-%d}→{end:%Y-%m-%d}", showlegend=False,
            hovertemplate=f"{ticker}<br>%{{x|%Y-%m-%d}}<br>NAV %{{y:.3f}}<extra></extra>",
        ))
        middle = start + (end - start) / 2
        annotations.append(dict(
            x=middle, y=1.0, xref="x", yref="paper", text=("💰 BIL" if ticker == "CASH" else ticker),
            showarrow=False, font=dict(size=12, color=color), xanchor="center", yanchor="bottom",
        ))
        tickvals.append(start)
        ticktexts.append(start.strftime("%Y-%m-%d"))
        if i > 0:
            fig.add_vline(x=start, line_dash="dash", line_color="rgba(200,200,200,0.35)", line_width=1)

    spy = frame.dropna(subset=["spy"])
    if not spy.empty:
        spy_return = float(spy["spy"].iloc[-1] - 1.0)
        fig.add_trace(go.Scatter(
            x=spy["date"], y=spy["spy"], mode="lines",
            line=dict(color="rgba(180,180,180,0.45)", width=2, dash="dot"),
            name=f"SPY 同期 {spy_return * 100:+.1f}%",
            hovertemplate="SPY<br>%{x|%Y-%m-%d}<br>NAV %{y:.3f}<extra></extra>",
        ))
    fig.update_layout(
        title=f"{title} — 累计收益率（共 {len(visible_segments)} 段）",
        height=560, template="plotly_dark", annotations=annotations,
        margin=dict(l=10, r=10, t=48, b=70),
        xaxis=dict(tickvals=tickvals, ticktext=ticktexts, tickangle=-30, gridcolor="rgba(100,100,100,0.3)"),
        yaxis=dict(
            title="NAV（对数，1.0 = 窗口起点）", type="log",
            tickvals=[0.25, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
            ticktext=["-75%", "-50%", "-30%", "0%", "+50%", "+100%", "+200%", "+400%", "+900%"],
            gridcolor="rgba(100,100,100,0.3)",
        ),
        legend=dict(orientation="h", y=1.08, x=1.0, xanchor="right"),
    )
    return fig


def _best_k_holding_stages(result: dict, window: str) -> None:
    upper = result.get("in_sample_upper_bounds") or {}
    available = [period for period in PERIOD_LABELS if (upper.get(period) or {}).get("slot_equity")]
    if not available:
        st.info("后端暂未返回最佳K逐槽持仓数据。")
        return
    selected = st.multiselect(
        "展示哪些最佳K持仓阶段（最多3条）", available,
        default=[period for period in _DEFAULT_STAGE_PERIODS if period in available],
        format_func=lambda period: f"{PERIOD_LABELS[period]} · 最佳K{upper[period].get('k')}",
        max_selections=3, key=f"mp_stage_periods_{window}",
    )
    if not selected:
        st.info("请选择至少一条最佳K曲线查看持仓阶段。")
        return
    tabs = st.tabs([
        f"{PERIOD_LABELS[period]} · 最佳K{upper[period].get('k')}" for period in selected
    ])
    dates = pd.DatetimeIndex(pd.to_datetime(result.get("dates") or [], errors="coerce")).dropna()
    if dates.empty:
        return
    for tab, period in zip(tabs, selected):
        with tab:
            payload = upper[period]
            timeline = payload.get("holdings_timeline") or []
            slots = payload.get("slot_equity") or []
            start, end = dates.min().to_pydatetime(), dates.max().to_pydatetime()
            chosen = st.slider(
                "持仓阶段观察窗口", min_value=start, max_value=end, value=(start, end),
                format="YYYY-MM", key=f"mp_stage_window_{window}_{period}",
            )
            for slot_row in slots:
                slot = int(slot_row.get("slot", 0))
                slot_name = _SLOT_LABELS[slot] if slot < len(_SLOT_LABELS) else f"槽{slot + 1}"
                fig = _stage_figure(
                    dates, slot_row.get("equity") or [], result.get("spy") or [], timeline, slot,
                    f"{PERIOD_LABELS[period]} 最佳K{payload.get('k')} · {slot_name}接力 持仓段",
                    pd.Timestamp(chosen[0]), pd.Timestamp(chosen[1]),
                )
                st.plotly_chart(fig, width="stretch", key=f"mp_stage_fig_{window}_{period}_{slot}")
    st.caption(
        "阶段图对应各周期完整展示窗口上的最佳K模拟，属于样本内敏感性参考；"
        "逐槽净值沿用固定不再平衡、次日收盘执行和同一交易成本口径。"
    )


def _annual_heatmap(result: dict) -> None:
    annual = result.get("annual_returns") or {}
    years = sorted({int(row["year"]) for rows in annual.values() for row in rows})
    if not years:
        return
    lookup = {period: {int(row["year"]): row.get("return") for row in rows} for period, rows in annual.items()}
    z = [[lookup.get(period, {}).get(year) for year in years] for period in PERIOD_LABELS]
    text = [["—" if value is None else f"{value * 100:.1f}%" for value in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=years, y=[PERIOD_LABELS[p] for p in PERIOD_LABELS],
        text=text, texttemplate="%{text}", colorscale="RdYlGn", zmid=0,
        colorbar=dict(title="收益"), hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>",
    ))
    fig.update_layout(height=330, template="plotly_dark", margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width="stretch", key="mp_annual_heat")
    st.caption("首尾自然年为不完整年度；年度收益按组合逐日收益在该自然年内连乘。")


def _overview(data: dict, window: str) -> None:
    result = data["results_by_window"][window]
    catalog = _catalog(data, result)
    defaults = [*PERIOD_LABELS, "spy"]
    selected = st.multiselect(
        "显示曲线（图表与统计表同步）", list(catalog), defaults,
        format_func=lambda key: catalog[key]["label"], key=f"mp_series_{window}",
    )
    fig = go.Figure()
    dates = pd.to_datetime(result.get("dates") or [], errors="coerce")
    for key in selected:
        item = catalog[key]
        fig.add_trace(go.Scatter(
            x=dates, y=item["equity"], name=item["label"], mode="lines", line=item["line"],
        ))
    fig.update_layout(
        height=520, template="plotly_dark", hovermode="x unified", yaxis_type="log",
        yaxis_title="净值（对数）", margin=dict(l=10, r=10, t=35, b=10),
        legend=dict(orientation="h", y=1.16),
    )
    st.plotly_chart(fig, width="stretch", key=f"mp_overview_{window}")
    st.caption(
        "七条实线始终使用页面同一个固定K。下拉框内的虚线是各周期在完整展示窗口上扫描"
        "TopN…60 后得到的样本内CAGR上限，只作敏感性参考，不用于挑选主策略。"
    )
    table = _stats_frame(catalog, selected)
    if table.empty:
        st.info("请至少选择一条曲线。")
    else:
        st.dataframe(table, hide_index=True, width="stretch")
    st.markdown("##### 最佳K曲线的具体持仓阶段")
    _best_k_holding_stages(result, window)
    st.markdown("##### 年度收益")
    _annual_heatmap(result)


def _k_sensitivity(data: dict, window: str) -> None:
    result = data["results_by_window"][window]
    metric_labels = {"cagr": "CAGR", "calmar": "Calmar", "max_dd": "最大回撤", "ann_turnover": "年换手"}
    metric = st.selectbox("热图指标", list(metric_labels), format_func=metric_labels.get, key=f"mp_k_metric_{window}")
    rows = result.get("k_sensitivity") or []
    ks = [int(row["k"]) for row in rows]
    z = [[((row.get("periods") or {}).get(period) or {}).get(metric) for row in rows] for period in PERIOD_LABELS]
    fig = go.Figure(go.Heatmap(
        z=z, x=ks, y=[PERIOD_LABELS[p] for p in PERIOD_LABELS], colorscale="Viridis",
        colorbar=dict(title=metric_labels[metric]), hovertemplate="%{y} · K=%{x}<br>%{z:.3f}<extra></extra>",
    ))
    fig.update_layout(height=390, template="plotly_dark", xaxis_title="同一个固定K", margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width="stretch", key=f"mp_k_heat_{window}_{metric}")
    best_rows = []
    for period, payload in (result.get("in_sample_upper_bounds") or {}).items():
        stats = payload.get("stats") or {}
        best_rows.append({
            "周期": PERIOD_LABELS[period], "完整窗口最佳K": payload.get("k"),
            "CAGR": _pct(stats.get("cagr")), "最大回撤": _pct(stats.get("max_dd")),
            "Calmar": None if stats.get("calmar") is None else round(float(stats["calmar"]), 2),
            "年换手": _pct(stats.get("ann_turnover")),
        })
    st.dataframe(pd.DataFrame(best_rows), hide_index=True, width="stretch")
    st.caption("每个格子都是同一 TopN、同一成本下的独立固定K回测；最佳K仅是完整窗口样本内上限。")


def _chasing_and_winners(data: dict, window: str) -> None:
    result = data["results_by_window"][window]
    failures, holding_failures, winners = [], [], []
    for period, diag in (result.get("diagnostics") or {}).items():
        for horizon in (42, 63):
            row = diag.get(f"failure_{horizon}d") or {}
            failures.append({
                "周期": PERIOD_LABELS[period], "观察期": f"{horizon}交易日",
                "绝对亏损率": _pct(row.get("absolute_loss_rate")),
                "跑输SPY率": _pct(row.get("under_spy_rate")),
                "成熟入场": row.get("mature"), "右删失": row.get("censored"),
            })
        hf = diag.get("holding_failures") or {}
        holding_failures.append({
            "周期": PERIOD_LABELS[period], "已退出持仓": hf.get("closed_positions"),
            "2–3月退出": hf.get("exit_2_3m_count"), "其中亏损退出": hf.get("loss_exit_2_3m_count"),
            "占全部退出": _pct(hf.get("loss_exit_2_3m_rate_all_closed")),
            "2–3月退出内部亏损率": _pct(hf.get("loss_rate_within_2_3m_exits")),
        })
        sw = diag.get("super_winners") or {}
        winners.append({
            "周期": PERIOD_LABELS[period], "赢家事件": sw.get("episodes"),
            "捕获事件": sw.get("captured_episodes"), "事件捕获率": _pct(sw.get("episode_capture_rate")),
            "平均入场延迟(月)": sw.get("average_entry_delay_months"),
            "提前退出事件": sw.get("early_exit_episodes"),
            "提前退出率": _pct(sw.get("early_exit_episode_rate")),
            "重复买入次数": sw.get("repurchased_count"),
        })
    st.markdown("##### 入场后42/63交易日失败率")
    st.dataframe(pd.DataFrame(failures), hide_index=True, width="stretch")
    st.markdown("##### 持有2–3个月即亏损退出")
    st.dataframe(pd.DataFrame(holding_failures), hide_index=True, width="stretch")
    st.markdown("##### 超级赢家捕获、入场延迟与提前退出")
    st.dataframe(pd.DataFrame(winners), hide_index=True, width="stretch")
    st.caption("超级赢家共同定义：从执行日向后252交易日涨幅≥100%，或位列该信号月共同可用股票的未来收益Top5；未来不足252日的机会不进入分母。")

    pairs = []
    for row in result.get("pair_diagnostics") or []:
        skip_only = int(row.get("skip_only_slot_months") or 0)
        negative = int(row.get("skip_only_recent_21d_negative") or 0)
        pairs.append({
            "配对": f"{PERIOD_LABELS[row['zero_period']]} vs {PERIOD_LABELS[row['skip_period']]}",
            "不跳月独有槽月": row.get("zero_only_slot_months"), "跳月独有槽月": skip_only,
            "跳月独有且最近21日已转弱": negative,
            "转弱占跳月独有": _pct(negative / skip_only if skip_only else None),
        })
    st.markdown("##### 跳过最近一个月的配对证据")
    st.dataframe(pd.DataFrame(pairs), hide_index=True, width="stretch")

    case_rows = data.get("case_studies", {}).get(window, []) or []
    if case_rows:
        ticker = st.selectbox("具名案例", sorted({row["ticker"] for row in case_rows}), key=f"mp_case_{window}")
        flattened = []
        for row in case_rows:
            if row["ticker"] != ticker:
                continue
            for period, detail in (row.get("periods") or {}).items():
                flattened.append({
                    "月份": row["month"], "周期": PERIOD_LABELS[period], "PIT成员": row.get("pit_member"),
                    "共同门禁": row.get("common_eligible"), "动量": detail.get("score"),
                    "排名": detail.get("rank"), "持有": detail.get("held"),
                    "稳定证券ID": row.get("security_id"),
                })
        st.dataframe(pd.DataFrame(flattened), hide_index=True, width="stretch", height=380)


def _holdings_and_industry(data: dict, window: str, n_holdings: int, fixed_k: int, cost_bps: float) -> None:
    result = data["results_by_window"][window]
    period = st.selectbox("查看周期", list(PERIOD_LABELS), format_func=PERIOD_LABELS.get, key=f"mp_hold_period_{window}")
    timeline = ((result.get("fixed_variants") or {}).get(period) or {}).get("holdings_timeline") or []
    flat = []
    for row in timeline:
        for slot in row.get("slots") or []:
            flat.append({
                "信号月": row.get("month"), "信号日": row.get("signal_date"), "执行日": row.get("execution_date"),
                "槽位": slot.get("slot"), "持仓": slot.get("ticker"), "权重": slot.get("weight"),
                "信号排名": slot.get("rank"), "动量": slot.get("score"),
            })
    holdings_df = pd.DataFrame(flat)
    st.markdown("##### 完整月度历史持仓")
    st.dataframe(holdings_df, hide_index=True, width="stretch", height=430)
    if not holdings_df.empty:
        st.download_button(
            "下载当前周期持仓 CSV", holdings_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"momentum_period_{period}_{window}_holdings.csv", mime="text/csv",
        )

    industry = (((result.get("diagnostics") or {}).get(period) or {}).get("industry_concentration") or {})
    monthly = pd.DataFrame(industry.get("monthly") or [])
    if not monthly.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["top1_weight"], name="最大行业权重"))
        fig.add_trace(go.Scatter(x=monthly["month"], y=monthly["hhi"], name="行业HHI"))
        fig.update_layout(height=300, template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig, width="stretch", key=f"mp_industry_{window}_{period}")
        st.caption(
            f"平均最大行业权重 {_pct(industry.get('average_top1_weight'))} · "
            f"平均HHI {industry.get('average_hhi')} · 最大行业≥75%的月份 {_pct(industry.get('high_concentration_month_rate'))}。"
            "历史行业标签使用当前可得GICS近似，不把它伪装成PIT行业分类。"
        )

    overlap = result.get("overlap") or {}
    matrix = overlap.get("stock_matrix") or {}
    z = [[(matrix.get(left) or {}).get(right) for right in PERIOD_LABELS] for left in PERIOD_LABELS]
    fig = go.Figure(go.Heatmap(
        z=z, x=[PERIOD_LABELS[p] for p in PERIOD_LABELS], y=[PERIOD_LABELS[p] for p in PERIOD_LABELS],
        zmin=0, zmax=1, colorscale="Blues", texttemplate="%{z:.0%}", colorbar=dict(title="重合率"),
    ))
    fig.update_layout(height=430, template="plotly_dark", margin=dict(l=10, r=10, t=20, b=10))
    st.markdown("##### 周期之间每月持仓重合率")
    st.plotly_chart(fig, width="stretch", key=f"mp_overlap_{window}")
    pair_options = overlap.get("pairs") or []
    if pair_options:
        selected_pair = st.selectbox(
            "查看逐月重合", range(len(pair_options)),
            format_func=lambda i: f"{PERIOD_LABELS[pair_options[i]['left']]} vs {PERIOD_LABELS[pair_options[i]['right']]}",
            key=f"mp_overlap_pair_{window}",
        )
        month_rows = pd.DataFrame(pair_options[selected_pair].get("monthly") or [])
        if not month_rows.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=month_rows["month"], y=month_rows["stock_overlap"], name="股票槽位重合"))
            fig.add_trace(go.Scatter(x=month_rows["month"], y=month_rows["weight_overlap"], name="权重重合"))
            fig.update_layout(height=280, template="plotly_dark", yaxis=dict(range=[0, 1]), margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig, width="stretch", key=f"mp_overlap_monthly_{window}_{selected_pair}")
    st.caption("股票槽位重合率=共同股票数÷TopN；权重重合率=两组合对每个资产较小权重之和。")

    if st.button("加载逐笔完整持仓账本", key=f"mp_full_ledger_{window}"):
        with st.spinner("加载逐笔入场、退出、成本与前瞻诊断…"):
            full = fetch_dynasty_double_dragon_momentum_periods(n_holdings, fixed_k, cost_bps, "full")
        if not full.get("success"):
            st.error(full.get("error", "完整账本加载失败"))
        else:
            ledger = pd.DataFrame((((full.get("holding_ledger") or {}).get(window) or {}).get(period) or []))
            if "company_actions" in ledger:
                ledger["company_actions"] = ledger["company_actions"].map(lambda value: json.dumps(value, ensure_ascii=False))
            st.dataframe(ledger, hide_index=True, width="stretch", height=430)
            st.download_button(
                "下载逐笔账本 CSV", ledger.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"momentum_period_{period}_{window}_ledger.csv", mime="text/csv",
            )


def _data_truth(data: dict, window: str) -> None:
    quality = data.get("data_quality") or {}
    sample = (data.get("results_by_window") or {}).get(window, {}).get("sample") or {}
    cols = st.columns(5)
    cols[0].metric("PIT覆盖", f"{quality.get('pit_start')} → {quality.get('pit_end')}")
    cols[1].metric("历史证券并集", quality.get("universe_size", "—"))
    cols[2].metric("最后信号", quality.get("signal_as_of", "—"))
    cols[3].metric("最后执行", quality.get("last_execution_date", "—"))
    cols[4].metric("估值截至", quality.get("valuation_as_of", "—"))
    st.dataframe(pd.DataFrame([
        {"周期": PERIOD_LABELS[p], "公式": FORMULAS[p], "共同预热": "252交易日", "自身动量门禁": "> 0"}
        for p in PERIOD_LABELS
    ]), hide_index=True, width="stretch")
    st.markdown(
        "- 股票池：逐月真实标普500历史成分；包含当时存在、后来被删除、退市、收购或更换代码的证券。\n"
        "- 信号：完成自然月最后一个交易日收盘形成；所有周期共同要求252交易日真实锚点价与MA200。\n"
        "- 执行：下一交易日收盘；当日不可成交的候选按信号排名顺延，不回写月末信号。\n"
        "- 持仓：每槽独立复利、固定不再平衡；无股票候选时由BIL补位；单边成本按每条买卖腿扣除。\n"
        "- 窗口：5Y/10Y各自现金冷启动，分别固定60/120个完成信号月；不继承窗口前持仓。\n"
        "- 证券身份：逐笔账本附Sharadar permaticker，便于识别代码更换前后的同一证券；"
        "确认终止报价的证券按最后复权收盘后接BIL估值。"
    )
    st.caption(
        f"当前窗口：{sample.get('first_signal_month')} → {sample.get('last_signal_month')}，"
        f"{sample.get('signal_months')}个信号月，实际估值跨度{sample.get('actual_years')}年。"
    )
    coverage = pd.DataFrame(quality.get("coverage") or [])
    if not coverage.empty:
        st.markdown("##### 逐月成员与价格覆盖审计")
        st.dataframe(coverage, hide_index=True, width="stretch", height=390)
    trailing = quality.get("trailing_invalid_months") or []
    if trailing:
        st.info("未纳入信号的尾部月份：" + "；".join(map(str, trailing)))


def render_momentum_period_research() -> None:
    st.markdown("## 🧪 动量周期实验")
    st.info(
        "七种动量共用逐月PIT标普500股票池、TopN、同一个固定K、MA200、执行日、成本、"
        "不再平衡和BIL补位。页面只改变动量观察周期。"
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_holdings = st.slider("TopN", 1, 5, 2, key="mp_topn")
    if st.session_state.get("mp_fixed_k", 30) < n_holdings:
        st.session_state["mp_fixed_k"] = n_holdings
    with c2:
        fixed_k = st.slider("固定K", n_holdings, 60, 30, key="mp_fixed_k")
    with c3:
        cost_bps = st.slider("单边成本 (bps)", 0, 50, 10, key="mp_cost")
    with c4:
        window = st.radio("观察窗口", ["5Y", "10Y"], horizontal=True, key="mp_window")

    with st.spinner("加载七周期共同口径实验…"):
        data = fetch_dynasty_double_dragon_momentum_periods(n_holdings, fixed_k, float(cost_bps), "summary")
    if not data.get("success"):
        st.error(f"动量周期实验加载失败：{data.get('error', '未知错误')}")
        return
    if data.get("schema_version") != "dd_momentum_period_v1":
        st.error(f"后端合同版本不匹配：{data.get('schema_version')}")
        return

    tabs = st.tabs(["总览", "K敏感性", "追高与超级赢家", "持仓与行业", "数据真实性"])
    with tabs[0]:
        _overview(data, window)
    with tabs[1]:
        _k_sensitivity(data, window)
    with tabs[2]:
        _chasing_and_winners(data, window)
    with tabs[3]:
        _holdings_and_industry(data, window, n_holdings, fixed_k, float(cost_bps))
    with tabs[4]:
        _data_truth(data, window)
