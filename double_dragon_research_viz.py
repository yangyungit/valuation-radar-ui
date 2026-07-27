"""Page 13 独立的标普500无前视研究Tab。"""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from api_client import fetch_dynasty_double_dragon_walk_forward


_VARIANT_LABELS = {
    "mom12_0_fixed": "12-0＋固定K",
    "mom12_1_fixed": "12-1＋相同固定K",
    "mom12_0_walk_forward": "12-0＋走步K",
    "mom12_1_walk_forward": "12-1＋走步K",
}
_COLORS = {
    "mom12_0_fixed": "#4C78A8",
    "mom12_1_fixed": "#72B7B2",
    "mom12_0_walk_forward": "#F58518",
    "mom12_1_walk_forward": "#E45756",
}
_DEFAULT_OVERVIEW_SERIES = [*_VARIANT_LABELS, "spy"]


def _pct(value) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _equity_stats(dates, equity) -> dict:
    """为没有后端策略统计的基准曲线补齐可比较的净值指标。"""
    frame = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "equity": pd.to_numeric(pd.Series(equity), errors="coerce"),
    }).dropna()
    frame = frame[frame["equity"] > 0]
    if frame.empty:
        return {}
    first = float(frame["equity"].iloc[0])
    last = float(frame["equity"].iloc[-1])
    years = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days / 365.2425, 1 / 365.2425)
    cagr = (last / first) ** (1 / years) - 1
    max_dd = float((frame["equity"] / frame["equity"].cummax() - 1).min())
    return {
        "cum_return": last / first - 1,
        "cagr": cagr,
        "max_dd": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else None,
    }


def _overview_catalog(data: dict, result: dict) -> dict:
    """建立图表与统计表共用的曲线目录，避免两处各自维护。"""
    fixed_k = (data.get("config") or {}).get("fixed_k")
    catalog = {}
    for key in _VARIANT_LABELS:
        payload = (result.get("variants") or {}).get(key)
        if not payload:
            continue
        if key.endswith("_fixed"):
            k_basis = f"固定K={fixed_k}" if fixed_k is not None else "固定K"
        else:
            k_basis = "年度走步K"
        catalog[key] = {
            "label": _VARIANT_LABELS[key],
            "equity": payload.get("equity", []),
            "stats": payload.get("stats") or {},
            "k_basis": k_basis,
            "color": _COLORS.get(key),
            "line": dict(color=_COLORS.get(key), width=2.2),
        }

    catalog["spy"] = {
        "label": "SPY",
        "equity": result.get("spy", []),
        "stats": _equity_stats(result.get("dates", []), result.get("spy", [])),
        "k_basis": "—",
        "color": "#A0A0A0",
        "line": dict(color="#A0A0A0", width=1.5),
    }
    for signal in ("12_0", "12_1"):
        payload = (result.get("in_sample_upper_bounds") or {}).get(signal)
        if not payload:
            continue
        key = f"in_sample_{signal}"
        k = payload.get("k")
        label_signal = signal.replace("_", "-")
        catalog[key] = {
            "label": f"{label_signal} 完整窗口最佳K{k}（样本内上限）",
            "equity": payload.get("equity", []),
            "stats": payload.get("stats") or {},
            "k_basis": f"完整窗口最佳K={k}",
            "color": "#777",
            "line": dict(color="#777", width=1.2, dash="dash"),
        }
    return catalog


def _stats_table(catalog: dict, selected: list[str]) -> pd.DataFrame:
    rows = []
    for key in selected:
        payload = catalog.get(key)
        if not payload:
            continue
        s = payload.get("stats") or {}
        rows.append({
            "策略": payload.get("label", key),
            "K口径": payload.get("k_basis", "—"),
            "累计收益": _pct(s.get("cum_return")),
            "CAGR": _pct(s.get("cagr")),
            "最大回撤": _pct(s.get("max_dd")),
            "Calmar": None if s.get("calmar") is None else round(float(s["calmar"]), 2),
            "年换手": _pct(s.get("ann_turnover")),
            "平均持有(月)": s.get("avg_hold_months"),
            "换仓次数": s.get("n_swaps"),
        })
    return pd.DataFrame(rows)


def _overview(data: dict, window: str) -> None:
    result = data["results_by_window"][window]
    dates = pd.to_datetime(result["dates"])
    catalog = _overview_catalog(data, result)
    series_options = list(catalog)
    selected = st.multiselect(
        "显示曲线（图表与下方统计表同步）",
        options=series_options,
        default=[key for key in _DEFAULT_OVERVIEW_SERIES if key in catalog],
        format_func=lambda key: catalog[key]["label"],
        key=f"wf_overview_series_{window}",
    )
    fig = go.Figure()
    for key in selected:
        payload = catalog[key]
        fig.add_trace(go.Scatter(
            x=dates, y=payload.get("equity", []), mode="lines",
            name=payload["label"], line=payload["line"],
        ))
    fig.update_layout(
        height=500, template="plotly_dark", hovermode="x unified",
        margin=dict(l=10, r=10, t=30, b=10), yaxis_type="log", yaxis_title="净值（对数）",
        legend=dict(orientation="h", y=1.14),
    )
    st.plotly_chart(fig, width="stretch", key=f"wf_overview_{window}")
    st.caption(
        "下方表格跟随“显示曲线”选择；图例点击只用于临时显隐。"
        "两条灰色虚线使用完整展示窗口选K，只是样本内参考上限，不参与主策略排名。"
    )
    stats = _stats_table(catalog, selected)
    if stats.empty:
        st.info("请至少选择一条曲线，以查看对应图表和统计。")
    else:
        st.dataframe(stats, hide_index=True, width="stretch")

    sens = pd.DataFrame(data.get("fixed_k_sensitivity", {}).get(window, []))
    if not sens.empty:
        st.markdown("##### 固定K配对差异（12-1 减 12-0）")
        heat = go.Figure(go.Heatmap(
            z=[sens["cagr_delta"], sens["max_dd_delta"], sens["turnover_delta"]],
            x=sens["k"], y=["CAGR差", "最大回撤差", "年换手差"],
            colorscale="RdBu", zmid=0, colorbar=dict(title="差值"),
        ))
        heat.update_layout(height=280, template="plotly_dark", margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(heat, width="stretch", key=f"wf_sensitivity_{window}")
        st.caption("覆盖 TopN…60 的每个整数K；用于判断12-1结论是否只依赖默认K30。")


def _k_audit(data: dict, window: str) -> None:
    logs = data.get("k_selection_log") or {}
    fig = go.Figure()
    for signal, rows in logs.items():
        if not rows:
            continue
        fig.add_trace(go.Scatter(
            x=[r["effective_start"] for r in rows], y=[r["selected_k"] for r in rows],
            mode="lines+markers", line_shape="hv", name=signal.replace("_", "-"),
        ))
    fig.update_layout(height=330, template="plotly_dark", yaxis_title="生效K", xaxis_title="生效年度")
    st.plotly_chart(fig, width="stretch", key="wf_k_steps")

    signal_choice = st.radio("训练期候选K审计", ["12_0", "12_1"], horizontal=True, key="wf_k_signal")
    rows = logs.get(signal_choice, [])
    if rows:
        ks = sorted({int(k) for row in rows for k in (row.get("candidate_metrics") or {})})
        z = [[(row.get("candidate_metrics") or {}).get(str(k), {}).get("cagr") for k in ks] for row in rows]
        heat = go.Figure(go.Heatmap(
            z=z, x=ks, y=[r["training_end"][:4] for r in rows], colorscale="Viridis",
            colorbar=dict(title="训练CAGR"),
        ))
        heat.update_layout(height=420, template="plotly_dark", xaxis_title="候选K", yaxis_title="选择年")
        st.plotly_chart(heat, width="stretch", key=f"wf_k_heat_{signal_choice}")
        audit = pd.DataFrame([{
            "训练区间": f"{r['training_start']} → {r['training_end']}",
            "选择日": r["selection_as_of"], "前K": r.get("previous_k"),
            "选中K": r["selected_k"], "生效区间": f"{r['effective_start']} → {r['effective_end']}",
            "依据": r["reason"], "稳定区间": r.get("plateau"),
        } for r in rows])
        st.dataframe(audit, hide_index=True, width="stretch")
        st.download_button(
            "下载K日程 CSV", audit.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"walk_forward_k_{signal_choice}.csv", mime="text/csv",
        )

    comp_rows = []
    for selector, by_signal in (data.get("selector_comparison", {}).get(window, {}) or {}).items():
        for signal, stats in by_signal.items():
            comp_rows.append({"选择器": selector, "信号": signal.replace("_", "-"),
                              "CAGR": _pct(stats.get("cagr")), "最大回撤": _pct(stats.get("max_dd")),
                              "Calmar": stats.get("calmar"), "年换手": _pct(stats.get("ann_turnover"))})
    if comp_rows:
        st.markdown("##### 三种走步选择器对照")
        st.dataframe(pd.DataFrame(comp_rows), hide_index=True, width="stretch")

    cross = data.get("signal_k_decomposition", {}).get(window, {})
    if cross:
        st.markdown("##### 信号变化与K日程变化分解")
        st.dataframe(pd.DataFrame([{"交叉组合": k, "CAGR": _pct(v.get("cagr")),
                                            "最大回撤": _pct(v.get("max_dd")),
                                            "年换手": _pct(v.get("ann_turnover"))}
                                           for k, v in cross.items()]), hide_index=True, width="stretch")


def _chasing_and_winners(data: dict) -> None:
    diagnostics = data.get("diagnostics") or {}
    failure_rows, winner_rows, cases = [], [], []
    for variant, diag in diagnostics.items():
        for horizon in (42, 63):
            d = diag.get(f"failure_{horizon}d") or {}
            failure_rows.append({"策略": _VARIANT_LABELS.get(variant, variant), "期限": f"{horizon}日",
                                 "绝对亏损率": _pct(d.get("absolute_loss_rate")),
                                 "跑输SPY率": _pct(d.get("under_spy_rate")),
                                 "成熟": d.get("mature"), "未成熟": d.get("censored")})
        w = diag.get("super_winners") or {}
        actual = diag.get("actual_holding_failures") or {}
        winner_rows.append({"策略": _VARIANT_LABELS.get(variant, variant),
                            "超级赢家机会": w.get("opportunities"),
                            "捕获率": _pct(w.get("capture_rate")),
                            "平均入场延迟(月)": w.get("average_entry_delay_months"),
                            "捕获后持满252日率": _pct(w.get("retained_252d_rate")),
                            "提前退出": w.get("early_exit_count"),
                            "重新买回": w.get("repurchased_count"),
                            "三个月内退出且亏损": _pct(actual.get("three_month_exit_loss_rate"))})
        cases.extend(diag.get("case_studies") or [])
    st.markdown("##### 42/63交易日前瞻失败")
    st.dataframe(pd.DataFrame(failure_rows), hide_index=True, width="stretch")
    st.markdown("##### 实际退出失败与超级赢家保留")
    st.dataframe(pd.DataFrame(winner_rows), hide_index=True, width="stretch")
    if cases:
        st.markdown("##### 具名案例（不参与选参）")
        case_df = pd.DataFrame(cases)
        show = [c for c in ["variant", "ticker", "entry_date", "exit_date", "holding_months", "net_return",
                             "momentum_12_0", "momentum_12_1", "forward_42d", "forward_63d", "forward_252d"] if c in case_df]
        st.dataframe(case_df[show], hide_index=True, width="stretch")


def _holdings_and_industry(data: dict, controls: tuple) -> None:
    diagnostics = data.get("diagnostics") or {}
    variant = st.selectbox("策略", list(_VARIANT_LABELS), format_func=lambda x: _VARIANT_LABELS[x], key="wf_industry_variant")
    industry = (diagnostics.get(variant) or {}).get("industry_concentration") or {}
    rows = pd.DataFrame(industry.get("monthly") or [])
    c1, c2, c3 = st.columns(3)
    c1.metric("平均最大行业权重", _pct(industry.get("average_top1_weight")))
    c2.metric("平均行业HHI", "—" if industry.get("average_hhi") is None else f"{industry['average_hhi']:.3f}")
    c3.metric("最大行业≥75%月份", _pct(industry.get("high_concentration_month_rate")))
    if not rows.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=rows["month"], y=rows["top1_weight"], name="Top1行业权重"))
        fig.add_trace(go.Scatter(x=rows["month"], y=rows["hhi"], name="HHI"))
        fig.update_layout(height=330, template="plotly_dark", hovermode="x unified")
        st.plotly_chart(fig, width="stretch", key="wf_industry_trend")

    if st.button("加载逐笔持仓明细", key="wf_load_full"):
        st.session_state["wf_full_requested"] = True
    if st.session_state.get("wf_full_requested"):
        n, fixed_k, cost, selector = controls
        with st.spinner("读取完整逐笔账本…"):
            full = fetch_dynasty_double_dragon_walk_forward(n, fixed_k, cost, selector, "full")
        if not full.get("success"):
            st.error(full.get("error", "明细加载失败"))
        else:
            ledger = pd.DataFrame((full.get("holding_ledger") or {}).get(variant, []))
            if ledger.empty:
                st.info("该组合暂无持仓明细。")
            else:
                ticker_filter = st.multiselect("Ticker筛选", sorted(ledger["ticker"].dropna().unique()), key="wf_ledger_tickers")
                shown = ledger[ledger["ticker"].isin(ticker_filter)] if ticker_filter else ledger
                st.dataframe(shown, hide_index=True, width="stretch")
                st.download_button("下载逐笔账本 CSV", shown.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"{variant}_holding_ledger.csv", mime="text/csv")


def _data_truth(data: dict) -> None:
    q = data.get("data_quality") or {}
    cols = st.columns(5)
    cols[0].metric("PIT起点", q.get("pit_start", "—"))
    cols[1].metric("严格OOS起点", q.get("strict_oos_start", "—"))
    cols[2].metric("可信截止月", q.get("last_valid_month", "—"))
    cols[3].metric("价格截止", q.get("price_as_of", "—"))
    cols[4].metric("确认终值事件", len(q.get("terminal_confirmations") or {}))
    st.code(q.get("data_fingerprint", ""), language=None)
    st.caption("行业标签：静态最新GICS近似，不是PIT行业分类。退市终值：仅Sharadar公司行动确认后，末个closeadj结清并转BIL；未确认断尾会使回测失败。")
    coverage = pd.DataFrame(q.get("coverage") or [])
    if not coverage.empty:
        st.dataframe(coverage.tail(36), hide_index=True, width="stretch")
    terminals = q.get("terminal_confirmations") or {}
    with st.expander("查看退市/收购/换代码终值确认"):
        if terminals:
            st.dataframe(pd.DataFrame([{"ticker": k, **v} for k, v in terminals.items()]), hide_index=True, width="stretch")
    if q.get("trailing_invalid_months"):
        st.warning("尾部月份未通过门禁，已停在最近完整月：" + "；".join(q["trailing_invalid_months"][:8]))


def render_sp500_walk_forward_research() -> None:
    st.markdown("### 🧪 标普500无前视实验")
    st.info("训练60个完整自然月 · 每年12月更新K · 下一交易日收盘执行 · 逐月PIT · 动量>0＋MA200 · 固定不再平衡 · 扣单边成本 · 自动δ未参与")
    c1, c2, c3, c4 = st.columns(4)
    n = c1.select_slider("TopN", options=[1, 2, 3, 4, 5], value=2, key="wf_topn")
    fixed_default = max(n, 30)
    fixed_k = c2.slider("固定K", min_value=n, max_value=60, value=fixed_default, key="wf_fixed_k")
    cost = c3.slider("单边成本(bps)", 0, 50, 10, key="wf_cost")
    selector_label = c4.selectbox("走步选择器", ["WF-CAGR", "WF-Calmar", "稳定平台"], key="wf_selector")
    selector = {"WF-CAGR": "cagr", "WF-Calmar": "calmar", "稳定平台": "plateau"}[selector_label]
    window = st.radio("观察窗口", ["5Y", "10Y"], horizontal=True, key="wf_window")

    with st.spinner("构建严格样本外母曲线（冷启动通常约20秒）…"):
        data = fetch_dynasty_double_dragon_walk_forward(n, fixed_k, cost, selector, "summary")
    if not data.get("success"):
        st.error("研究数据门禁失败：" + str(data.get("error", "未知错误")))
        st.caption("本Tab不会回退到旧自动K或旧回测结果。")
        return

    tabs = st.tabs(["总览", "走步K审计", "追高与超级赢家", "持仓与行业", "数据真实性"])
    with tabs[0]:
        _overview(data, window)
    with tabs[1]:
        _k_audit(data, window)
    with tabs[2]:
        _chasing_and_winners(data)
    with tabs[3]:
        _holdings_and_industry(data, (n, fixed_k, cost, selector))
    with tabs[4]:
        _data_truth(data)
