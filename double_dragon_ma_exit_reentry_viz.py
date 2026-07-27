"""Page 13 independent MA-exit and re-entry research tab."""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import holdings_viz as hv
from api_client import fetch_dynasty_double_dragon_ma_exit_reentry


SCHEMA_VERSION = "dd_ma_exit_reentry_v1"
PERIOD_LABELS = {"12_0": "12M / 12-0", "12_1": "12M-1 / 12-1", "6_0": "6M / 6-0"}
SELL_LABELS = {"no_ma": "无MA卖出", "ma30": "MA30卖出", "ma50": "MA50卖出", "ma100": "MA100卖出"}
SELL_COLORS = {"no_ma": "#A0A0A0", "ma30": "#E45756", "ma50": "#F2CF5B", "ma100": "#54A24B"}
REENTRY_LABELS = {
    "immediate": "立即替补（卖出MA＋MA200）",
    "wait_fast": "现金一月后快速再入（卖出MA）",
    "wait_confirmed": "现金一月后趋势确认（卖出MA＋MA200）",
}
REENTRY_COLORS = {"immediate": "#4C78A8", "wait_fast": "#F58518", "wait_confirmed": "#54A24B"}
PARKING_LABELS = {"cash_0": "现金0%", "bil": "历史真实BIL", "fixed_5": "固定年化5%（假设）"}
OVERVIEW_COLORS = {
    "baseline": "#A0A0A0", "current": "#4C78A8", "best_cagr": "#F2CF5B",
    "best_calmar": "#54A24B", "spy": "#777777",
}
REASON_LABELS = {
    "ma_only": "仅MA触发",
    "ma_mixed": "MA与其他条件共同触发",
    "ma_exit": "跌破卖出MA",
    "rank_exit": "跌出固定K",
    "momentum_nonpositive": "动量不再为正",
    "pit_removed": "不再是PIT成员",
}


def _pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value) * 100:.{digits}f}%"


def _number(value, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _equity_stats(dates, values) -> dict:
    frame = pd.DataFrame({
        "date": pd.to_datetime(dates, errors="coerce"),
        "equity": pd.to_numeric(pd.Series(values), errors="coerce"),
    }).dropna()
    if len(frame) < 2 or float(frame["equity"].iloc[0]) <= 0:
        return {}
    years = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days / 365.2425, 1 / 365.2425)
    first, last = float(frame["equity"].iloc[0]), float(frame["equity"].iloc[-1])
    cagr = (last / first) ** (1.0 / years) - 1.0
    max_dd = float((frame["equity"] / frame["equity"].cummax() - 1.0).min())
    return {
        "final_nav": last / first,
        "cum_return": last / first - 1.0,
        "cagr": cagr,
        "max_dd": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else None,
    }


def _stats_row(label: str, payload: dict) -> dict:
    stats = payload.get("stats") or {}
    return {
        "策略": label,
        "终值": _number(stats.get("final_nav")),
        "累计收益": _pct(stats.get("cum_return")),
        "CAGR": _pct(stats.get("cagr")),
        "最大回撤": _pct(stats.get("max_dd")),
        "Calmar": _number(stats.get("calmar")),
        "年换手": _pct(stats.get("ann_turnover")),
        "换股次数": "—" if stats.get("n_swaps") is None else str(stats.get("n_swaps")),
        "平均持有(月)": _number(stats.get("avg_hold_months")),
        "累计成本": _pct(stats.get("cum_cost")),
        "停车资金暴露": _pct(stats.get("parking_weight_daily")),
        "停车槽月": "—" if stats.get("parking_slot_months") is None else str(stats.get("parking_slot_months")),
    }


def _reentry_payload(result: dict, mode: str, parking: str) -> dict:
    comparison = result.get("reentry_comparison") or {}
    if mode == "immediate":
        return comparison.get("immediate") or {}
    return (comparison.get(mode) or {}).get(parking) or {}


def _line_chart(dates, series: list[tuple[str, list, str]], key: str, height: int = 500) -> None:
    fig = go.Figure()
    for label, values, color in series:
        if not values:
            continue
        fig.add_trace(go.Scatter(
            x=dates, y=values, mode="lines", name=label,
            line=dict(color=color, width=2.1),
        ))
    fig.update_layout(
        height=height, template="plotly_dark", hovermode="x unified",
        yaxis_type="log", yaxis_title="净值（对数）",
        margin=dict(l=10, r=10, t=35, b=10),
        legend=dict(orientation="h", y=1.14),
    )
    st.plotly_chart(fig, width="stretch", key=key)


def _complete_key(exit_ma: int, reentry_mode: str, parking_mode: str) -> str:
    if reentry_mode == "immediate":
        return f"ma{exit_ma}_immediate"
    return f"ma{exit_ma}_{reentry_mode}_{parking_mode}"


def _strategy_label(payload: dict, short: bool = False) -> str:
    config = payload.get("strategy_config") or {}
    exit_ma = config.get("exit_ma")
    if exit_ma is None:
        return "无MA卖出基准"
    mode = config.get("reentry_mode", "immediate")
    if mode == "immediate":
        return f"MA{exit_ma}＋立即替补"
    mode_label = "等一月快速再入" if mode == "wait_fast" else "等一月趋势确认"
    parking = PARKING_LABELS.get(config.get("parking_mode"), config.get("parking_mode", "—"))
    return f"MA{exit_ma}＋{mode_label}" if short else f"MA{exit_ma}＋{mode_label}＋{parking}"


def _drawdown_curve(values: list) -> list:
    series = pd.to_numeric(pd.Series(values), errors="coerce")
    return (series / series.cummax() - 1.0).tolist()


def _drawdown_chart(dates, catalog: list[tuple[str, dict, str]], key: str) -> None:
    fig = go.Figure()
    for label, payload, color in catalog:
        values = payload.get("equity") or []
        if not values:
            continue
        fig.add_trace(go.Scatter(
            x=dates, y=_drawdown_curve(values), mode="lines", name=label,
            line=dict(color=color, width=2), hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1%}<extra>%{fullData.name}</extra>",
        ))
    fig.update_layout(
        height=350, template="plotly_dark", hovermode="x unified",
        yaxis=dict(title="距历史高点回撤", tickformat=".0%"),
        margin=dict(l=10, r=10, t=25, b=10), legend=dict(orientation="h", y=1.16),
    )
    st.plotly_chart(fig, width="stretch", key=key)


def _overview_catalog(result: dict, current_key: str) -> list[tuple[str, dict, str, str]]:
    strategies = result.get("complete_strategies") or {}
    best = result.get("best_strategy_keys") or {}
    roles = [
        ("baseline", "无MA卖出基准", "no_ma"),
        ("current", "当前完整策略", current_key),
        ("best_cagr", "最高CAGR（样本内）", best.get("cagr")),
        ("best_calmar", "最高Calmar（样本内）", best.get("calmar")),
    ]
    merged: dict[str, dict] = {}
    for role, role_label, strategy_key in roles:
        if not strategy_key or strategy_key not in strategies:
            continue
        item = merged.setdefault(strategy_key, {
            "payload": strategies[strategy_key], "roles": [], "role": role,
            "color": OVERVIEW_COLORS[role],
        })
        item["roles"].append(role_label)
        if role == "current":
            item["role"], item["color"] = role, OVERVIEW_COLORS[role]
    return [
        (" / ".join(item["roles"]) + " · " + _strategy_label(item["payload"]),
         item["payload"], item["color"], key)
        for key, item in merged.items()
    ]


def _spy_payload(result: dict) -> dict:
    return {
        "equity": result.get("spy") or [],
        "stats": _equity_stats(result.get("dates") or [], result.get("spy") or []),
        "strategy_config": {},
    }


def _overview_tab(result: dict, window: str, current_key: str) -> None:
    catalog = _overview_catalog(result, current_key)
    dates = pd.to_datetime(result.get("dates") or [], errors="coerce")
    fig = go.Figure()
    for label, payload, color, key in catalog:
        role_dash = "dash" if "样本内" in label and "当前完整策略" not in label else "solid"
        fig.add_trace(go.Scatter(
            x=dates, y=payload.get("equity") or [], mode="lines", name=label,
            line=dict(color=color, width=2.5 if key == current_key else 2, dash=role_dash),
        ))
    spy_payload = _spy_payload(result)
    fig.add_trace(go.Scatter(
        x=dates, y=spy_payload["equity"], mode="lines", name="SPY",
        line=dict(color=OVERVIEW_COLORS["spy"], width=1.5),
    ))
    fig.update_layout(
        height=520, template="plotly_dark", hovermode="x unified", yaxis_type="log",
        yaxis_title="完整策略净值（对数）", margin=dict(l=10, r=10, t=35, b=10),
        legend=dict(orientation="h", y=1.17),
    )
    st.plotly_chart(fig, width="stretch", key=f"maer_complete_equity_{window}_{current_key}")
    st.caption(
        "每条线都是从持有、MA卖出、停车到重新买入的一套完整策略。最高CAGR和最高Calmar"
        "均由当前5Y/10Y窗口内的完整组合扫描得到，只表示样本内上限，不是推荐参数。"
    )

    strategies = result.get("complete_strategies") or {}
    current = strategies.get(current_key) or {}
    baseline = strategies.get("no_ma") or {}
    current_stats, baseline_stats = current.get("stats") or {}, baseline.get("stats") or {}
    dd_improvement = None
    if current_stats.get("max_dd") is not None and baseline_stats.get("max_dd") is not None:
        dd_improvement = float(current_stats["max_dd"]) - float(baseline_stats["max_dd"])
    cols = st.columns(6)
    cols[0].metric("当前策略终值", _number(current_stats.get("final_nav")))
    cols[1].metric("当前策略CAGR", _pct(current_stats.get("cagr")))
    cols[2].metric("当前策略最大回撤", _pct(current_stats.get("max_dd")))
    cols[3].metric("较无MA少跌", _pct(dd_improvement) if dd_improvement is not None else "—")
    cols[4].metric("Calmar", _number(current_stats.get("calmar")))
    cols[5].metric("停车资金暴露", _pct(current_stats.get("parking_weight_daily")))

    rows = []
    for label, payload, _, _ in catalog:
        row = _stats_row(label, payload)
        row["最大回撤区间"] = (
            f"{(payload.get('stats') or {}).get('max_dd_peak', '—')} → "
            f"{(payload.get('stats') or {}).get('max_dd_trough', '—')}"
        )
        rows.append(row)
    spy_row = _stats_row("SPY", spy_payload)
    spy_row["最大回撤区间"] = "—"
    rows.append(spy_row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.markdown("##### 同步回撤图：大跌是否真的被控制")
    drawdown_catalog = [(label, payload, color) for label, payload, color, _ in catalog]
    drawdown_catalog.append(("SPY", spy_payload, OVERVIEW_COLORS["spy"]))
    _drawdown_chart(dates, drawdown_catalog, f"maer_complete_drawdown_{window}_{current_key}")

    st.markdown("##### 当前完整策略持仓状态")
    st.caption(
        f"{_strategy_label(current)}。每个槽位固定不再平衡；顶部标签按实际执行日切换，"
        "BIL、现金0%和固定5%停车阶段会作为独立持仓段显示。"
    )
    if not _render_standard_slot_stages(
        result, current, window, f"maer_current_{current_key}",
    ):
        st.info("当前完整策略缺少逐槽净值或持仓时间线，请重启后端并强制刷新缓存。")

    st.markdown("##### 完整策略年度结果")
    annual_rows = []
    for label, payload, _, _ in catalog:
        for row in payload.get("annual_returns") or []:
            annual_rows.append({
                "完整策略": label, "年份": row.get("year"), "收益": _pct(row.get("return")),
                "不完整年度": bool(row.get("partial")),
            })
    if annual_rows:
        st.dataframe(pd.DataFrame(annual_rows), hide_index=True, width="stretch")

    with st.expander("查看全部21套MA完整策略组合（按样本内Calmar排序）"):
        ranking_rows = []
        for rank, item in enumerate(result.get("complete_ranking") or [], 1):
            ranking_rows.append({
                "排名": rank,
                "完整策略": _strategy_label({"strategy_config": item.get("strategy_config") or {}}),
                "终值": _number(item.get("final_nav")), "CAGR": _pct(item.get("cagr")),
                "最大回撤": _pct(item.get("max_dd")), "Calmar": _number(item.get("calmar")),
                "年换手": _pct(item.get("ann_turnover")),
                "停车暴露": _pct(item.get("parking_weight_daily")),
            })
        st.dataframe(pd.DataFrame(ranking_rows), hide_index=True, width="stretch")

    st.markdown("##### 最佳表现完整策略的具体持仓阶段")
    _best_strategy_stages(result, window)


_SLOT_LABELS = ["槽A", "槽B", "槽C", "槽D", "槽E"]


def _stage_ticker(cell: dict | None) -> str:
    ticker = (cell or {}).get("ticker")
    return {
        "CASH0": "现金0%", "CASH5": "固定5%", "BIL": "BIL",
    }.get(ticker, str(ticker or "CASH"))


def _stage_month_segments(timeline: list[dict], slot: int) -> list[tuple[str, str, str]]:
    """Collapse actual post-execution holdings into monthly stitched segments."""
    segments: list[tuple[str, str, str]] = []
    previous = None
    start_month = None
    last_month = None
    for row in timeline:
        execution = pd.to_datetime(row.get("execution_date"), errors="coerce")
        if pd.isna(execution):
            continue
        month = pd.Timestamp(execution).strftime("%Y-%m")
        cells = row.get("slots") or []
        ticker = _stage_ticker(cells[slot] if slot < len(cells) else None)
        if ticker != previous:
            if previous is not None:
                segments.append((previous, start_month, last_month))
            previous, start_month = ticker, month
        last_month = month
    if previous is not None:
        segments.append((previous, start_month, last_month))
    return segments


def _render_standard_slot_stages(
    result: dict, payload: dict, window: str, key_prefix: str,
) -> bool:
    """Use the same stitched holding-state figures as the main S&P 500 tab."""
    slot_rows = payload.get("slot_equity") or []
    timeline = payload.get("holdings_timeline") or []
    dates = pd.DatetimeIndex(pd.to_datetime(result.get("dates") or [], errors="coerce")).dropna()
    if dates.empty or not slot_rows or not timeline:
        return False

    win_lo, win_hi = dates.min(), dates.max()
    selected = st.slider(
        "持仓图时间窗口（拖动重设起点，各持仓段与SPY在窗口左端归一）",
        min_value=win_lo.to_pydatetime(), max_value=win_hi.to_pydatetime(),
        value=(win_lo.to_pydatetime(), win_hi.to_pydatetime()), format="YYYY-MM",
        key=f"{key_prefix}_window_{win_lo:%Y%m}_{win_hi:%Y%m}",
    )
    win_lo, win_hi = pd.Timestamp(selected[0]), pd.Timestamp(selected[1])
    lo_month, hi_month = win_lo.strftime("%Y-%m"), win_hi.strftime("%Y-%m")
    spy = pd.Series(result.get("spy") or [], index=dates, dtype=float).dropna()
    spy = spy[(spy.index >= win_lo) & (spy.index <= win_hi)]
    spy_frame = pd.DataFrame({"Close": spy}) if not spy.empty else pd.DataFrame()

    rendered = False
    for slot_row in slot_rows:
        slot = int(slot_row.get("slot", 0))
        slot_name = _SLOT_LABELS[slot] if slot < len(_SLOT_LABELS) else f"槽{slot + 1}"
        values = pd.to_numeric(pd.Series(slot_row.get("equity") or []), errors="coerce")
        if len(values) != len(dates):
            continue
        slot_series = pd.Series(values.to_numpy(), index=dates, dtype=float).dropna()
        slot_series = slot_series[(slot_series.index >= win_lo) & (slot_series.index <= win_hi)]
        if slot_series.empty:
            continue
        segments = [
            segment for segment in _stage_month_segments(timeline, slot)
            if not (segment[2] < lo_month or segment[1] > hi_month)
        ]
        if not segments:
            continue
        price_cache = {
            ticker: pd.DataFrame({"Close": slot_series})
            for ticker, _, _ in segments if ticker != "CASH"
        }
        figure = hv.build_stitched_fig(
            segments, f"{slot_name}接力 持仓段", spy_frame, price_cache, {}, {},
        )
        st.plotly_chart(
            figure, width="stretch", key=f"{key_prefix}_slot_{window}_{slot}",
        )
        rendered = True
    return rendered


def _best_strategy_stages(result: dict, window: str) -> None:
    strategies = result.get("complete_strategies") or {}
    best = result.get("best_strategy_keys") or {}
    available: dict[str, list[str]] = {}
    for metric, label in (("cagr", "最高CAGR"), ("calmar", "最高Calmar")):
        strategy_key = best.get(metric)
        if strategy_key and strategy_key in strategies:
            available.setdefault(strategy_key, []).append(label)
    if not available:
        st.info("后端暂未返回最佳完整策略的逐槽持仓阶段。")
        return
    selected_key = st.selectbox(
        "查看哪条样本内最佳完整策略", list(available),
        format_func=lambda key: " / ".join(available[key]) + " · " + _strategy_label(strategies[key]),
        key=f"maer_best_stage_strategy_{window}",
    )
    payload = strategies[selected_key]
    if not _render_standard_slot_stages(
        result, payload, window, f"maer_best_{selected_key}",
    ):
        st.info("该最佳组合缺少逐槽持仓阶段数据。")
    st.caption(
        "持仓阶段图沿用固定不再平衡、月末信号、下一交易日收盘执行和相同成本；"
        "最佳组合由完整展示窗口挑选，只用于解释样本内曲线如何形成。"
    )


def _episode_events(payload: dict, peak: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    events = pd.DataFrame(payload.get("ma_events") or [])
    if events.empty:
        return events
    execution = pd.to_datetime(events.get("execution_date"), errors="coerce")
    reentry = pd.to_datetime(events.get("reentry_date"), errors="coerce")
    lead = peak - pd.Timedelta(days=45)
    return events[((execution >= lead) & (execution <= end)) | ((reentry >= peak) & (reentry <= end))].copy()


def _big_drop_tab(result: dict, window: str, current_key: str) -> None:
    strategies = result.get("complete_strategies") or {}
    current = strategies.get(current_key) or {}
    baseline = strategies.get("no_ma") or {}
    episodes = current.get("drawdown_episodes") or []
    if not episodes:
        st.info("当前完整策略没有可展示的回撤区间。")
        return
    st.markdown(f"#### 当前完整策略：{_strategy_label(current)}")
    st.caption("以下区间来自当前完整策略自身的三次最深水下期，不按新闻日期或主观挑选。")
    episode_rows = []
    for index, episode in enumerate(episodes, 1):
        peak = pd.Timestamp(episode["peak_date"])
        end = pd.Timestamp(episode.get("recovery_date") or result.get("dates", [])[-1])
        episode_rows.append({
            "序号": index, "峰值": episode.get("peak_date"), "谷底": episode.get("trough_date"),
            "恢复": episode.get("recovery_date") or "尚未恢复", "最大回撤": _pct(episode.get("max_dd")),
            "峰到谷(日历日)": episode.get("days_to_trough"),
            "完整恢复(日历日)": episode.get("recovery_calendar_days"),
            "期间MA退出": len(_episode_events(current, peak, end)),
        })
    st.dataframe(pd.DataFrame(episode_rows), hide_index=True, width="stretch")
    chosen = st.selectbox(
        "逐次查看大跌与重新买入", range(len(episodes)),
        format_func=lambda index: (
            f"第{index + 1}深回撤 · {episodes[index].get('peak_date')} → "
            f"{episodes[index].get('trough_date')} · {_pct(episodes[index].get('max_dd'))}"
        ), key=f"maer_episode_{window}_{current_key}",
    )
    episode = episodes[chosen]
    dates = pd.DatetimeIndex(pd.to_datetime(result.get("dates") or [], errors="coerce"))
    peak = pd.Timestamp(episode["peak_date"])
    trough = pd.Timestamp(episode["trough_date"])
    end = pd.Timestamp(episode.get("recovery_date") or dates[-1])
    current_series = pd.Series(current.get("equity") or [], index=dates, dtype=float)
    baseline_series = pd.Series(baseline.get("equity") or [], index=dates, dtype=float)
    spy_series = pd.Series(result.get("spy") or [], index=dates, dtype=float)
    frame = pd.DataFrame({"current": current_series, "baseline": baseline_series, "spy": spy_series}).loc[peak:end]
    frame = frame / frame.iloc[0] - 1.0
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame.index, y=frame["current"], name="当前完整策略", line=dict(color="#4C78A8", width=2.7)))
    fig.add_trace(go.Scatter(x=frame.index, y=frame["baseline"], name="同期无MA", line=dict(color="#A0A0A0", width=2)))
    fig.add_trace(go.Scatter(x=frame.index, y=frame["spy"], name="同期SPY", line=dict(color="#777777", width=1.5, dash="dot")))
    events = _episode_events(current, peak, end)
    if not events.empty:
        exit_dates = pd.to_datetime(events["execution_date"], errors="coerce").dropna()
        exit_y = [frame["current"].asof(date) for date in exit_dates]
        exit_text = [
            f"卖出 {row.get('ticker')}<br>{row.get('execution_date')}<br>{row.get('exit_reason')}"
            for _, row in events.loc[exit_dates.index].iterrows()
        ]
        fig.add_trace(go.Scatter(
            x=exit_dates, y=exit_y, mode="markers", name="MA卖出",
            marker=dict(color="#E45756", size=10, symbol="triangle-down"), text=exit_text,
            hovertemplate="%{text}<extra></extra>",
        ))
        reentries = events.dropna(subset=["reentry_date"]).copy()
        if not reentries.empty:
            reentry_dates = pd.to_datetime(reentries["reentry_date"], errors="coerce")
            reentry_y = [frame["current"].asof(date) for date in reentry_dates]
            reentry_text = [
                f"买入 {row.get('reentry_ticker')}<br>{row.get('reentry_date')}<br>等待{row.get('wait_signal_months')}个信号月"
                for _, row in reentries.iterrows()
            ]
            fig.add_trace(go.Scatter(
                x=reentry_dates, y=reentry_y, mode="markers", name="重新买入",
                marker=dict(color="#54A24B", size=10, symbol="triangle-up"), text=reentry_text,
                hovertemplate="%{text}<extra></extra>",
            ))
    fig.add_vline(x=trough, line_dash="dash", line_color="rgba(242,207,91,0.65)")
    fig.update_layout(
        height=500, template="plotly_dark", hovermode="x unified",
        yaxis=dict(title="从回撤峰值起的收益", tickformat=".0%"),
        margin=dict(l=10, r=10, t=35, b=10), legend=dict(orientation="h", y=1.14),
    )
    st.plotly_chart(fig, width="stretch", key=f"maer_episode_chart_{window}_{current_key}_{chosen}")

    trough_frame = frame.loc[:trough]
    current_drop = float(trough_frame["current"].min())
    baseline_drop = float(trough_frame["baseline"].min())
    cols = st.columns(5)
    cols[0].metric("当前策略区间最深", _pct(current_drop))
    cols[1].metric("同期无MA最深", _pct(baseline_drop))
    cols[2].metric("同期少跌", _pct(current_drop - baseline_drop))
    cols[3].metric("MA退出次数", len(events))
    cols[4].metric("恢复日", episode.get("recovery_date") or "尚未恢复")
    if events.empty:
        st.info("该回撤区间没有MA退出事件，因此不能把这次少跌或多跌归因于MA卖出。")
        return
    shown = events.copy()
    shown["卖出后状态"] = shown.apply(
        lambda row: "立即买入 " + str(row.get("reentry_ticker"))
        if row.get("wait_signal_months") == 0 else PARKING_LABELS.get(row.get("parking_mode"), row.get("parking_mode")), axis=1,
    )
    shown["再入"] = shown.apply(
        lambda row: f"{row.get('reentry_date') or '尚未'} → {row.get('reentry_ticker') or '—'}", axis=1,
    )
    shown["避免损失"] = shown.get("avoided_loss", pd.Series(index=shown.index)).map(_pct)
    shown["错过上涨"] = shown.get("missed_upside", pd.Series(index=shown.index)).map(_pct)
    columns = ["execution_date", "ticker", "exit_reason", "卖出后状态", "再入", "wait_signal_months", "避免损失", "错过上涨"]
    st.dataframe(
        shown[[column for column in columns if column in shown]].rename(columns={
            "execution_date": "执行卖出日", "ticker": "卖出股票", "exit_reason": "退出原因",
            "wait_signal_months": "等待信号月",
        }), hide_index=True, width="stretch",
    )


def _parameter_breakdown_tab(data: dict, result: dict, window: str) -> None:
    st.info("下面两组图只用于拆解参数，不代表最终完整策略总览；最终收益和回撤请看第一个子页。")
    st.markdown("#### A. 只改变卖出MA：所有版本都固定立即替补")
    _sell_length_tab(data, result, window)
    st.markdown("#### B. 固定当前卖出MA：只改变卖出后的再入状态")
    _reentry_tab(data, result, window)


def _sell_length_tab(data: dict, result: dict, window: str) -> None:
    comparison = result.get("sell_comparison") or {}
    dates = pd.to_datetime(result.get("dates") or [], errors="coerce")
    series = [
        (SELL_LABELS[key], payload.get("equity") or [], SELL_COLORS[key])
        for key, payload in comparison.items() if key in SELL_LABELS
    ]
    series.append(("SPY", result.get("spy") or [], "#777777"))
    _line_chart(dates, series, f"maer_sell_equity_{window}")
    st.caption(
        "四条策略共用PIT股票池、动量周期、TopN、固定K、MA200初始入场、执行日和成本；"
        "MA30/50/100只额外改变已经持有股票的卖出条件。"
    )
    rows = [_stats_row(SELL_LABELS[key], payload) for key, payload in comparison.items() if key in SELL_LABELS]
    spy_stats = _equity_stats(result.get("dates") or [], result.get("spy") or [])
    rows.append({
        "策略": "SPY", "终值": _number(spy_stats.get("final_nav")),
        "累计收益": _pct(spy_stats.get("cum_return")), "CAGR": _pct(spy_stats.get("cagr")),
        "最大回撤": _pct(spy_stats.get("max_dd")), "Calmar": _number(spy_stats.get("calmar")),
        "年换手": "—", "换股次数": "—", "平均持有(月)": "—", "累计成本": "—",
        "停车资金暴露": "—", "停车槽月": "—",
    })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    selected = st.selectbox(
        "查看哪条策略的最大回撤构成",
        list(comparison), format_func=lambda key: SELL_LABELS.get(key, key),
        key=f"maer_dd_variant_{window}",
    )
    stats = (comparison.get(selected) or {}).get("stats") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("最大回撤", _pct(stats.get("max_dd")))
    c2.metric("峰值日期", stats.get("max_dd_peak", "—"))
    c3.metric("谷底日期", stats.get("max_dd_trough", "—"))
    contribution = pd.DataFrame(stats.get("max_dd_contribution") or [])
    if not contribution.empty:
        contribution["回撤贡献"] = contribution["contribution"].map(_pct)
        contribution["期间持仓接力"] = contribution["holdings"].map(
            lambda value: " → ".join(value) if isinstance(value, list) else "—"
        )
        st.dataframe(
            contribution[["slot", "回撤贡献", "期间持仓接力"]].rename(columns={"slot": "槽位"}),
            hide_index=True, width="stretch",
        )


def _reentry_tab(data: dict, result: dict, window: str) -> str:
    parking = st.radio(
        "等待期间的资金处理",
        list(PARKING_LABELS), index=1, horizontal=True,
        format_func=PARKING_LABELS.get, key=f"maer_parking_{window}",
    )
    dates = pd.to_datetime(result.get("dates") or [], errors="coerce")
    series = []
    for mode in REENTRY_LABELS:
        payload = _reentry_payload(result, mode, parking)
        series.append((REENTRY_LABELS[mode], payload.get("equity") or [], REENTRY_COLORS[mode]))
    series.append(("SPY", result.get("spy") or [], "#777777"))
    _line_chart(dates, series, f"maer_reentry_equity_{window}_{parking}")
    st.caption(
        "立即替补不经过停车；另外两条线至少停留一个完整信号周期。"
        "快速再入只要求重新站上卖出MA，趋势确认还要求站上MA200。"
    )
    st.dataframe(pd.DataFrame([
        _stats_row(REENTRY_LABELS[mode], _reentry_payload(result, mode, parking))
        for mode in REENTRY_LABELS
    ]), hide_index=True, width="stretch")

    st.markdown("##### 现金0%、历史BIL与固定5%的配对差异")
    paired = []
    for mode in ("wait_fast", "wait_confirmed"):
        cash_nav = (((result.get("reentry_comparison") or {}).get(mode) or {}).get("cash_0") or {}).get("stats", {}).get("final_nav")
        for park in PARKING_LABELS:
            payload = _reentry_payload(result, mode, park)
            stats = payload.get("stats") or {}
            paired.append({
                "再入机制": REENTRY_LABELS[mode], "停车方式": PARKING_LABELS[park],
                "终值": _number(stats.get("final_nav")),
                "相对现金0%终值": (
                    "—" if cash_nav is None or stats.get("final_nav") is None
                    else f"{float(stats['final_nav']) - float(cash_nav):+.3f}"
                ),
                "CAGR": _pct(stats.get("cagr")), "最大回撤": _pct(stats.get("max_dd")),
                "累计成本": _pct(stats.get("cum_cost")),
                "停车资金暴露": _pct(stats.get("parking_weight_daily")),
            })
    st.dataframe(pd.DataFrame(paired), hide_index=True, width="stretch")

    st.markdown("##### 年度收益")
    annual_rows = []
    for mode in REENTRY_LABELS:
        payload = _reentry_payload(result, mode, parking)
        for row in payload.get("annual_returns") or []:
            annual_rows.append({
                "策略": REENTRY_LABELS[mode], "年份": row.get("year"),
                "收益": _pct(row.get("return")), "不完整年度": bool(row.get("partial")),
            })
    if annual_rows:
        st.dataframe(pd.DataFrame(annual_rows), hide_index=True, width="stretch")
    return parking


def _full_signature(momentum_period: str, n_holdings: int, fixed_k: int,
                    cost_bps: float, selected_exit_ma: int) -> tuple:
    return momentum_period, n_holdings, fixed_k, float(cost_bps), selected_exit_ma


def _load_full_if_requested(momentum_period: str, n_holdings: int, fixed_k: int,
                            cost_bps: float, selected_exit_ma: int) -> dict | None:
    signature = _full_signature(momentum_period, n_holdings, fixed_k, cost_bps, selected_exit_ma)
    if st.button("加载完整MA退出事件账本", key="maer_load_full"):
        with st.spinner("加载完整成交、退出与再入账本…"):
            full = fetch_dynasty_double_dragon_ma_exit_reentry(
                momentum_period, n_holdings, fixed_k, cost_bps,
                selected_exit_ma, "full",
            )
        st.session_state["maer_full_payload"] = full
        st.session_state["maer_full_signature"] = signature
    if st.session_state.get("maer_full_signature") == signature:
        return st.session_state.get("maer_full_payload")
    return None


def _event_payload(result: dict, mode: str, parking: str, current_key: str | None = None) -> dict:
    if mode == "current" and current_key:
        return (result.get("complete_strategies") or {}).get(current_key) or {}
    if mode == "sell_ma":
        config_ma = int(st.session_state.get("maer_selected_exit_ma", 50))
        return (result.get("sell_comparison") or {}).get(f"ma{config_ma}") or {}
    return _reentry_payload(result, mode, parking)


def _events_tab(data: dict, result: dict, window: str, parking: str,
                controls: tuple[str, int, int, float, int], current_key: str) -> None:
    mode_options = ["current", "sell_ma", "immediate", "wait_fast", "wait_confirmed"]
    mode_labels = {
        "current": "当前完整策略 · " + _strategy_label(
            ((result.get("complete_strategies") or {}).get(current_key) or {})
        ),
        "sell_ma": "卖出MA参数拆解中的立即替补",
        **REENTRY_LABELS,
    }
    mode = st.selectbox(
        "查看哪条路径的退出得失", mode_options,
        format_func=mode_labels.get, key=f"maer_event_mode_{window}",
    )
    payload = _event_payload(result, mode, parking, current_key)
    attribution = payload.get("attribution") or {}
    cols = st.columns(6)
    cols[0].metric("MA退出事件", attribution.get("events", 0))
    cols[1].metric("可完整归因", attribution.get("mature_events", 0))
    cols[2].metric("单次平均避免损失", _pct(attribution.get("average_avoided_loss")))
    cols[3].metric("单次平均错过上涨", _pct(attribution.get("average_missed_upside")))
    cols[4].metric("3月内买回率", _pct(attribution.get("repurchase_rate_3m")))
    cols[5].metric("买回后再卖率", _pct(attribution.get("whipsaw_rate_3m")))
    reasons = attribution.get("by_reason") or {}
    if reasons:
        st.dataframe(pd.DataFrame([
            {"退出归因": REASON_LABELS.get(key, key), "事件数": value}
            for key, value in reasons.items()
        ]), hide_index=True, width="stretch")
    st.caption(
        "每次MA退出都建立一条无MA影子持仓，直到它按K、正动量或PIT规则自然退出；"
        "实际袖套比影子多赚计为避免损失，少赚计为错过上涨。右删失事件不计入得失合计。"
    )

    full = _load_full_if_requested(*controls)
    if not full:
        return
    if not full.get("success"):
        st.error(full.get("error", "完整账本加载失败"))
        return
    full_result = (full.get("results_by_window") or {}).get(window) or {}
    full_payload = _event_payload(full_result, mode, parking, current_key)
    events = pd.DataFrame(full_payload.get("events") or [])
    if events.empty:
        st.info("当前路径没有MA退出事件。")
        return
    if "company_actions" in events:
        events["company_actions"] = events["company_actions"].map(
            lambda value: json.dumps(value, ensure_ascii=False)
        )
    preferred = [
        "signal_month", "execution_date", "slot", "ticker", "security_id", "exit_ma",
        "exit_reason", "rank", "momentum", "price", "ma_value", "ma200",
        "reentry_date", "reentry_ticker", "wait_signal_months", "natural_exit_date",
        "shadow_return", "actual_sleeve_return", "avoided_loss", "missed_upside",
        "profit_giveback", "profit_giveback_ratio", "repurchase_signal_months", "whipsaw_3m",
    ]
    shown = [column for column in preferred if column in events]
    st.dataframe(events[shown], hide_index=True, width="stretch", height=460)
    st.download_button(
        "下载当前路径MA退出事件 CSV",
        events.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"ma_exit_events_{window}_{mode}_{parking}.csv",
        mime="text/csv",
    )


def _winner_tab(result: dict, window: str, parking: str, current_key: str) -> None:
    options = ["current", *REENTRY_LABELS]
    labels = {
        "current": "当前完整策略 · " + _strategy_label(
            ((result.get("complete_strategies") or {}).get(current_key) or {})
        ),
        **REENTRY_LABELS,
    }
    mode = st.selectbox(
        "查看哪条完整路径", options,
        format_func=labels.get, key=f"maer_case_mode_{window}",
    )
    payload = _event_payload(result, mode, parking, current_key)
    cases = payload.get("case_studies") or []
    if not cases:
        st.info("当前参数和窗口下，NVDA、PLTR、WDC、SNDK没有构成真实MA退出事件，因此不构成MA误杀案例。")
        return
    frame = pd.DataFrame(cases)
    summary_cols = [
        "ticker", "signal_month", "execution_date", "exit_ma", "exit_reason",
        "natural_exit_date", "shadow_return", "actual_sleeve_return", "missed_upside",
        "avoided_loss", "reentry_date", "reentry_ticker", "forward_252d",
        "is_superwinner_252d", "identity_verified", "attribution_eligible",
    ]
    summary_cols = [column for column in summary_cols if column in frame]
    st.dataframe(frame[summary_cols], hide_index=True, width="stretch")
    if "attribution_eligible" in frame and not bool(frame["attribution_eligible"].all()):
        st.warning("部分具名事件未通过稳定证券身份核验，只展示时间线，不用于判断MA避免损失或错过上涨。")
    ticker = st.selectbox(
        "查看具名股票的完整时间线", sorted(frame["ticker"].dropna().unique()),
        key=f"maer_case_ticker_{window}_{mode}",
    )
    selected = frame[frame["ticker"] == ticker]
    detail_cols = [
        "signal_month", "signal_date", "execution_date", "price", "ma_value", "ma200",
        "rank", "momentum", "natural_exit_date", "natural_exit_reason", "shadow_return",
        "reentry_date", "reentry_ticker", "repurchase_date", "profit_giveback",
        "profit_giveback_ratio", "forward_252d", "price_source",
    ]
    st.dataframe(selected[[column for column in detail_cols if column in selected]], hide_index=True, width="stretch")
    st.caption(
        "具名股票只在它确实被策略持有并发生MA退出时出现；这些案例不参与选择MA、K或动量周期。"
        "证券身份使用稳定ID，价格使用公司行动复权后的closeadj。"
    )


def _data_truth_tab(data: dict, result: dict, window: str) -> None:
    quality = data.get("data_quality") or {}
    sample = result.get("sample") or {}
    cols = st.columns(5)
    cols[0].metric("PIT覆盖", f"{quality.get('pit_start', '—')} → {quality.get('pit_end', '—')}")
    cols[1].metric("历史证券并集", quality.get("universe_size", "—"))
    cols[2].metric("最后信号", quality.get("signal_as_of", "—"))
    cols[3].metric("最后执行", quality.get("last_execution_date", "—"))
    cols[4].metric("价格来源", quality.get("price_source", "—"))
    config = data.get("config") or {}
    st.dataframe(pd.DataFrame([
        {"项目": "动量公式", "当前口径": config.get("momentum_formula")},
        {"项目": "K排名池", "当前口径": quality.get("rank_universe")},
        {"项目": "普通初始入场", "当前口径": "MA200＋不得已触发当前卖出MA"},
        {"项目": "卖出MA", "当前口径": "无MA / MA30 / MA50 / MA100，只作用于已有持仓"},
        {"项目": "完整策略网格", "当前口径": "21套MA卖出×再入×停车组合，另列无MA基准"},
        {"项目": "最佳表现曲线", "当前口径": "当前5Y/10Y完整窗口内最高CAGR与最高Calmar，属于样本内上限"},
        {"项目": "固定5%", "当前口径": config.get("fixed_5_formula")},
        {"项目": "证券身份", "当前口径": quality.get("identity_mode")},
    ]), hide_index=True, width="stretch")
    st.markdown(
        "- 股票池：逐月真实标普500历史成分，包含后来删除、退市、收购或换代码的证券。\n"
        "- 留任排名：只看PIT成员、252日历史和正动量，不把MA200继续当作留任条件。\n"
        "- 执行：完成自然月最后一个交易日收盘形成信号，下一交易日收盘成交。\n"
        "- 总览：每条主曲线都包含卖出、停车和重新买入全过程；卖出MA与再入机制拆解不再充当最终结果。\n"
        "- 现金：现金0%和固定5%是合成情景；BIL使用真实股息复权总收益并扣买卖成本。\n"
        "- SNDK/WDC等具名案例携带稳定证券ID及公司行动；身份异常时不作MA得失归因。"
    )
    st.caption(
        f"当前{window}窗口：{sample.get('first_signal_month')} → {sample.get('last_signal_month')}，"
        f"{sample.get('signal_months')}个完成信号月，冷启动={sample.get('cold_start')}。"
    )
    coverage = pd.DataFrame(quality.get("coverage") or [])
    if not coverage.empty:
        st.markdown("##### 最近24个月数据覆盖")
        st.dataframe(coverage.tail(24), hide_index=True, width="stretch")
    trailing = quality.get("trailing_invalid_months") or []
    if trailing:
        st.warning("未纳入实验的尾部月份：" + "；".join(map(str, trailing[:8])))


def render_ma_exit_reentry_research() -> None:
    st.markdown("## 🧪 MA退出与再入实验")
    st.info(
        "逐月真实标普500 PIT · MA200普通初始入场 · 只比较无MA/MA30/MA50/MA100卖出 · "
        "完整回测覆盖卖出→停车→再入 · 固定TopN/K · 月末信号 · 下一交易日收盘 · "
        "固定不再平衡 · 自动δ不参与"
    )
    c1, c2, c3, c4, c5 = st.columns([1.25, 1, 1, 1, 1])
    with c1:
        momentum_period = st.selectbox(
            "动量周期", list(PERIOD_LABELS), format_func=PERIOD_LABELS.get,
            key="maer_period",
        )
    with c2:
        n_holdings = st.slider("TopN", 1, 5, 2, key="maer_topn")
    if st.session_state.get("maer_fixed_k", 30) < n_holdings:
        st.session_state["maer_fixed_k"] = n_holdings
    with c3:
        fixed_k = st.slider("固定K", n_holdings, 60, 30, key="maer_fixed_k")
    with c4:
        selected_exit_ma = st.selectbox(
            "完整策略卖出MA", [30, 50, 100], index=1,
            format_func=lambda value: f"MA{value}", key="maer_selected_exit_ma",
        )
    with c5:
        cost_bps = st.slider("单边成本(bps)", 0, 50, 10, key="maer_cost")
    window = st.radio("观察窗口", ["5Y", "10Y"], horizontal=True, key="maer_window")
    r1, r2 = st.columns(2)
    with r1:
        selected_reentry_mode = st.selectbox(
            "当前完整策略：卖出后如何回来", list(REENTRY_LABELS),
            format_func=REENTRY_LABELS.get, key="maer_complete_reentry",
        )
    with r2:
        selected_parking = st.selectbox(
            "当前完整策略：等待期间资金处理", list(PARKING_LABELS), index=1,
            format_func=PARKING_LABELS.get, key="maer_complete_parking",
            disabled=selected_reentry_mode == "immediate",
            help="立即替补没有等待期；此时停车方式不影响结果。",
        )
    active_parking = "bil" if selected_reentry_mode == "immediate" else selected_parking
    current_key = _complete_key(selected_exit_ma, selected_reentry_mode, active_parking)

    with st.spinner("加载MA退出与再入共同口径实验…"):
        data = fetch_dynasty_double_dragon_ma_exit_reentry(
            momentum_period, n_holdings, fixed_k, float(cost_bps),
            selected_exit_ma, "summary",
        )
    if not data.get("success"):
        st.error(f"MA退出与再入实验加载失败：{data.get('error', '未知错误')}")
        return
    if data.get("schema_version") != SCHEMA_VERSION:
        st.error(f"后端合同版本不匹配：{data.get('schema_version')}")
        return
    result = (data.get("results_by_window") or {}).get(window) or {}
    if not result:
        st.error(f"后端未返回{window}结果。")
        return
    if not result.get("complete_strategies"):
        st.error("后端仍在返回旧版MA实验缓存；请重启后端服务并点击侧栏“强制刷新”。")
        return
    if current_key not in (result.get("complete_strategies") or {}):
        st.error(f"后端未返回当前完整策略：{current_key}")
        return

    tabs = st.tabs([
        "整体收益与回撤", "大跌与再入时点", "参数拆解",
        "MA退出得失", "大牛股是否被过早卖出", "数据真实性",
    ])
    with tabs[0]:
        _overview_tab(result, window, current_key)
    with tabs[1]:
        _big_drop_tab(result, window, current_key)
    with tabs[2]:
        _parameter_breakdown_tab(data, result, window)
    controls = (momentum_period, n_holdings, fixed_k, float(cost_bps), selected_exit_ma)
    with tabs[3]:
        _events_tab(data, result, window, active_parking, controls, current_key)
    with tabs[4]:
        _winner_tab(result, window, active_parking, current_key)
    with tabs[5]:
        _data_truth_tab(data, result, window)
