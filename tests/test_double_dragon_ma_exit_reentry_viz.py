import numpy as np
import pandas as pd

import double_dragon_ma_exit_reentry_viz as viz
from streamlit.testing.v1 import AppTest


def _strategy(exit_ma=50, mode="immediate", parking="bil", scale=1.0, stage=False):
    dates = pd.bdate_range("2024-01-02", periods=80)
    equity = np.linspace(1.0, 1.4 * scale, len(dates))
    equity[25:40] *= np.linspace(1.0, 0.75, 15)
    equity[40:55] *= np.linspace(0.76, 1.0, 15)
    payload = {
        "strategy_config": {"exit_ma": exit_ma, "reentry_mode": mode, "parking_mode": parking},
        "equity": equity.round(6).tolist(),
        "stats": {
            "final_nav": float(equity[-1]), "cum_return": float(equity[-1] - 1),
            "cagr": 0.30 * scale, "max_dd": -0.24 / scale, "calmar": 1.25 * scale,
            "ann_turnover": 0.8, "n_swaps": 4, "avg_hold_months": 5.0,
            "cum_cost": 0.01, "parking_weight_daily": 0.1 if mode != "immediate" else 0,
            "parking_slot_months": 2 if mode != "immediate" else 0,
            "max_dd_peak": dates[24].strftime("%Y-%m-%d"),
            "max_dd_trough": dates[39].strftime("%Y-%m-%d"),
            "max_dd_contribution": [{"slot": 1, "contribution": -0.15, "holdings": ["AAA", "BIL", "BBB"]}],
        },
        "drawdown_episodes": [{
            "peak_date": dates[24].strftime("%Y-%m-%d"),
            "trough_date": dates[39].strftime("%Y-%m-%d"),
            "recovery_date": dates[54].strftime("%Y-%m-%d"),
            "max_dd": -0.24 / scale, "days_to_trough": 21,
            "recovery_calendar_days": 42, "right_censored": False,
        }],
        "annual_returns": [{"year": 2024, "return": float(equity[-1] - 1), "partial": True}],
        "attribution": {
            "events": 1, "mature_events": 1, "average_avoided_loss": 0.08,
            "average_missed_upside": 0.02, "repurchase_rate_3m": 1.0,
            "whipsaw_rate_3m": 0.0, "by_reason": {"ma_only": 1},
        },
        "case_studies": [],
        "ma_events": [{
            "event_id": 0, "signal_month": "2024-02", "signal_date": dates[23].strftime("%Y-%m-%d"),
            "execution_date": dates[25].strftime("%Y-%m-%d"), "slot": 1, "ticker": "AAA",
            "exit_ma": exit_ma, "exit_reason": "ma_only", "reentry_mode": mode,
            "parking_mode": parking, "reentry_date": dates[45].strftime("%Y-%m-%d"),
            "reentry_ticker": "BBB", "wait_signal_months": 1 if mode != "immediate" else 0,
            "avoided_loss": 0.08, "missed_upside": 0.02,
        }],
    }
    if stage:
        middle_ticker = {
            "cash_0": "CASH0", "fixed_5": "CASH5", "bil": "BIL",
        }.get(parking, "BIL") if mode != "immediate" else "DDD"
        payload["slot_equity"] = [
            {"slot": 0, "equity": equity.round(6).tolist()},
            {"slot": 1, "equity": (equity * 0.9 + 0.1).round(6).tolist()},
        ]
        payload["holdings_timeline"] = [
            {"execution_date": dates[0].strftime("%Y-%m-%d"), "slots": [{"ticker": "AAA"}, {"ticker": "CCC"}]},
            {"execution_date": dates[25].strftime("%Y-%m-%d"), "slots": [{"ticker": middle_ticker}, {"ticker": "CCC"}]},
            {"execution_date": dates[45].strftime("%Y-%m-%d"), "slots": [{"ticker": "BBB"}, {"ticker": "CCC"}]},
        ]
    return payload


def _payload():
    dates = pd.bdate_range("2024-01-02", periods=80)
    baseline = _strategy(exit_ma=None, scale=0.9)
    ma30 = _strategy(exit_ma=30, scale=0.95)
    immediate = _strategy(exit_ma=50, scale=1.0, stage=True)
    ma100 = _strategy(exit_ma=100, scale=0.92)
    fast = _strategy(exit_ma=50, mode="wait_fast", parking="fixed_5", scale=0.97, stage=True)
    confirmed = _strategy(exit_ma=100, mode="wait_confirmed", parking="bil", scale=0.98, stage=True)
    strategies = {
        "no_ma": baseline, "ma30_immediate": ma30, "ma50_immediate": immediate,
        "ma100_immediate": ma100, "ma50_wait_fast_fixed_5": fast,
        "ma100_wait_confirmed_bil": confirmed,
    }
    waits = {parking: _strategy(50, "wait_fast", parking, 0.96) for parking in viz.PARKING_LABELS}
    confirms = {parking: _strategy(50, "wait_confirmed", parking, 0.94) for parking in viz.PARKING_LABELS}
    for parking, strategy in waits.items():
        strategies[f"ma50_wait_fast_{parking}"] = fast if parking == "fixed_5" else strategy
    for parking, strategy in confirms.items():
        strategies[f"ma50_wait_confirmed_{parking}"] = strategy
    result = {
        "dates": [date.strftime("%Y-%m-%d") for date in dates],
        "spy": np.linspace(1.0, 1.15, len(dates)).round(6).tolist(),
        "sample": {"first_signal_month": "2024-01", "last_signal_month": "2024-04", "signal_months": 4, "cold_start": True},
        "complete_strategies": strategies,
        "best_strategy_keys": {"cagr": "ma50_immediate", "calmar": "ma100_wait_confirmed_bil"},
        "complete_ranking": [],
        "sell_comparison": {"no_ma": baseline, "ma30": ma30, "ma50": immediate, "ma100": ma100},
        "reentry_comparison": {"immediate": immediate, "wait_fast": waits, "wait_confirmed": confirms},
    }
    return {
        "success": True, "schema_version": viz.SCHEMA_VERSION,
        "config": {"fixed_k": 30, "momentum_formula": "P(t)/P(t-252)-1", "fixed_5_formula": "1.05^(days/365)-1"},
        "data_quality": {"pit_start": "2014-01", "pit_end": "2024-04", "universe_size": 600, "signal_as_of": "2024-04-30", "last_execution_date": "2024-05-01", "price_source": "closeadj", "rank_universe": "PIT+252d+positive momentum", "identity_mode": "stable security id", "coverage": []},
        "results_by_window": {"5Y": result, "10Y": result},
    }


def _app():
    viz._APPTEST_PAYLOAD = _payload()
    script = """
import double_dragon_ma_exit_reentry_viz as viz
viz.fetch_dynasty_double_dragon_ma_exit_reentry = lambda *args, **kwargs: viz._APPTEST_PAYLOAD
viz.render_ma_exit_reentry_research()
"""
    return AppTest.from_string(script, default_timeout=20).run(timeout=20)


def test_default_page_starts_with_complete_strategy_overview():
    app = _app()
    assert not app.exception
    labels = [tab.label for tab in app.tabs]
    for expected in ("整体收益与回撤", "大跌与再入时点", "参数拆解", "MA退出得失", "大牛股是否被过早卖出", "数据真实性"):
        assert expected in labels
    assert app.selectbox(key="maer_complete_reentry").value == "immediate"
    assert app.selectbox(key="maer_complete_parking").disabled is True
    assert len(app.get("plotly_chart")) >= 6


def test_waiting_strategy_switches_parking_and_rerenders_complete_path():
    app = _app()
    app.selectbox(key="maer_complete_reentry").select("wait_fast").run(timeout=20)
    assert not app.exception
    assert app.selectbox(key="maer_complete_parking").disabled is False
    app.selectbox(key="maer_complete_parking").select("fixed_5").run(timeout=20)
    assert not app.exception
    assert any("MA50＋等一月快速再入＋固定年化5%" in item.value for item in app.markdown)


def test_holding_segments_follow_execution_month_and_preserve_parking_identity():
    timeline = [
        {"month": "2024-01", "execution_date": "2024-02-01", "slots": [{"ticker": "AAA"}]},
        {"month": "2024-02", "execution_date": "2024-03-01", "slots": [{"ticker": "BIL"}]},
        {"month": "2024-03", "execution_date": "2024-04-01", "slots": [{"ticker": "CASH5"}]},
        {"month": "2024-04", "execution_date": "2024-05-01", "slots": [{"ticker": "BBB"}]},
    ]
    assert viz._stage_month_segments(timeline, 0) == [
        ("AAA", "2024-02", "2024-02"),
        ("BIL", "2024-03", "2024-03"),
        ("固定5%", "2024-04", "2024-04"),
        ("BBB", "2024-05", "2024-05"),
    ]
