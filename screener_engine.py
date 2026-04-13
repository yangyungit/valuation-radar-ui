"""
Shared screener classification engine.

Provides compute_metrics(), classify_asset_parallel(), and classify_all_at_date()
for parallel independent ABCD evaluation with hysteresis bands.

Legacy classify_asset() (cascade funnel) is retained but deprecated.
"""

import math
import numpy as np
import pandas as pd


def compute_metrics(ticker: str, df: pd.DataFrame, spy_col: str = "SPY") -> dict:
    """Compute all quantitative metrics needed by the ABCD screener for a single asset.

    Unlike the original Page 2 version, this function receives the price DataFrame
    explicitly so it can work on arbitrary historical slices.
    """
    base = {"has_data": False, "ticker": ticker}
    if ticker not in df.columns:
        return base
    ts = df[ticker].dropna().astype(float)
    if len(ts) < 60:
        return {**base, "data_len": len(ts)}

    curr     = float(ts.iloc[-1])
    data_len = len(ts)

    ma20  = float(ts.rolling(20).mean().iloc[-1])
    ma60  = float(ts.rolling(60).mean().iloc[-1])
    ma200_val = float(ts.rolling(200).mean().iloc[-1]) if data_len >= 200 else None
    ma250_val = float(ts.rolling(250).mean().iloc[-1]) if data_len >= 250 else None

    z_score = 0.0
    if data_len >= 250:
        mean250 = float(ts.rolling(250).mean().iloc[-1])
        std250  = float(ts.rolling(250).std().iloc[-1])
        z_score = round((curr - mean250) / std250, 2) if std250 > 0 else 0.0

    mom20 = round((curr / float(ts.iloc[-21]) - 1) * 100, 2) if data_len > 20 and ts.iloc[-21] > 0 else 0.0
    mom5  = round((curr / float(ts.iloc[-6])  - 1) * 100, 2) if data_len > 5  and ts.iloc[-6]  > 0 else 0.0

    rs_raw = None
    if data_len >= 127 and float(ts.iloc[-127]) > 0:
        rs_raw = round((curr / float(ts.iloc[-127]) - 1) * 100, 2)

    ts_1y    = ts.iloc[-252:] if data_len >= 252 else ts
    roll_max = ts_1y.cummax().replace(0, np.nan)
    drawdowns = (ts_1y - roll_max) / roll_max * 100
    max_dd = round(abs(float(drawdowns.min())), 1) if not drawdowns.isna().all() else 0.0

    ts_3y = ts.iloc[-756:] if data_len >= 756 else ts
    roll_max_3y = ts_3y.cummax().replace(0, np.nan)
    drawdowns_3y = (ts_3y - roll_max_3y) / roll_max_3y * 100
    max_dd_3y = round(abs(float(drawdowns_3y.min())), 1) if not drawdowns_3y.isna().all() else 0.0

    spy_corr = 0.0
    w_asset = ts.resample("W").last().pct_change().dropna()
    if spy_col in df.columns:
        w_spy  = df[spy_col].dropna().astype(float).resample("W").last().pct_change().dropna()
        common = w_asset.index.intersection(w_spy.index)
        if len(common) >= 26:
            c = float(w_asset.loc[common].corr(w_spy.loc[common]))
            spy_corr = round(c, 2) if not np.isnan(c) else 0.0

    daily_rets = ts.pct_change().dropna()
    sortino = 0.0
    if len(daily_rets) >= 60:
        ann_ret  = (1 + float(daily_rets.mean())) ** 252 - 1
        downside = daily_rets[daily_rets < 0]
        down_std = float(downside.std()) * np.sqrt(252) if len(downside) > 5 else 1.0
        sortino  = round((ann_ret - 0.04) / down_std, 2) if down_std > 0 else 0.0

    hv_60d = 0.0
    if len(daily_rets) >= 60:
        hv_60d = round(float(daily_rets.iloc[-60:].std()) * math.sqrt(250), 4)

    return {
        "has_data":     True,
        "data_len":     data_len,
        "curr":         curr,
        "ma20":         round(ma20, 2),
        "ma60":         round(ma60, 2),
        "ma200":        round(ma200_val, 2) if ma200_val is not None else None,
        "ma250":        round(ma250_val, 2) if ma250_val is not None else None,
        "is_bullish":   ma20 > ma60,
        "slow_bullish": (ma200_val is not None and ma60 > ma200_val),
        "full_uptrend": (ma250_val is not None and ma20 > ma60 > ma250_val),
        "z_score":      z_score,
        "mom20":        mom20,
        "mom5":         mom5,
        "rs_raw":       rs_raw,
        "rs_rank_pct":  1.0,
        "rs_rel":       0.0,
        "max_dd":       max_dd,
        "max_dd_3y":    max_dd_3y,
        "spy_corr":     spy_corr,
        "sortino":      sortino,
        "hv_60d":       hv_60d,
        "trend_label":  "趋势健康 (MA20>MA60)" if ma20 > ma60 else "趋势走弱 (MA20<MA60)",
    }


_GRADE_PRIORITY = {"A": 0, "B": 1, "Z": 2, "C": 3, "D": 4}


def classify_asset_parallel(
    m: dict, div_yield: float, mcap: float,
    prev_grades: list = None,
    thresholds: dict = None,
) -> tuple:
    """Parallel independent evaluation of all 4 grades with hysteresis.

    Returns (qualifying_grades: list, all_details: dict).
    Each grade is evaluated independently; an asset can qualify for multiple grades.
    When ``prev_grades`` includes a grade, that grade uses relaxed exit thresholds
    instead of strict entry thresholds (hysteresis band).

    Parameters
    ----------
    thresholds : Optional dict with keys for A-grade hysteresis thresholds:
        a_income_enter (default 1.0), a_income_exit (default 0.5),
        a_dd_enter (default 15.0), a_dd_exit (default 20.0),
        a_corr_enter (default 0.65), a_corr_exit (default 0.75).
        None means use original defaults (fully backward-compatible).
    """
    if not m.get("has_data"):
        return [], {"error": "数据不足"}

    prev = set(prev_grades or [])
    th = thresholds or {}
    grades = []
    all_details = {}

    # ── A: Anchor (defensive) ──
    was_a = "A" in prev
    _a_ie = float(th.get("a_income_enter", 1.0))
    _a_ix = float(th.get("a_income_exit",  0.5))
    _a_de = float(th.get("a_dd_enter",    15.0))
    _a_dx = float(th.get("a_dd_exit",     20.0))
    _a_ce = float(th.get("a_corr_enter",  0.65))
    _a_cx = float(th.get("a_corr_exit",   0.75))

    a_income_enter = div_yield >= _a_ie or m.get("slow_bullish", False)
    a_income_exit  = div_yield < _a_ix and not m.get("slow_bullish", False)
    a_dd_enter     = m["max_dd"] < _a_de
    a_dd_exit      = m["max_dd"] > _a_dx
    a_corr_enter   = m["spy_corr"] < _a_ce
    a_corr_exit    = m["spy_corr"] > _a_cx

    if was_a:
        a_pass = not a_income_exit and not a_dd_exit and not a_corr_exit
    else:
        a_pass = a_income_enter and a_dd_enter and a_corr_enter

    div_tag = f"股息 {div_yield:.1f}%" if div_yield >= _a_ie else ("慢趋势健康(MA60>MA200)" if m.get("slow_bullish") else "无收益来源")
    all_details["A"] = {
        "pass": a_pass,
        "收益来源(股息/慢趋势)": (a_income_enter if not was_a else not a_income_exit,
                               f"{div_tag}（进入需股息≥{_a_ie:.1f}%或MA60>MA200；退出需股息<{_a_ix:.1f}%且MA60<MA200）"),
        "1年最大回撤": (a_dd_enter if not was_a else not a_dd_exit,
                      f"{m['max_dd']:.1f}%（进入<{_a_de:.0f}%，退出>{_a_dx:.0f}%）"),
        "SPY相关性":   (a_corr_enter if not was_a else not a_corr_exit,
                      f"{m['spy_corr']:.2f}（进入<{_a_ce:.2f}，退出>{_a_cx:.2f}）"),
        # Extra keys for whitebox (non-destructive additions)
        "_was_a":       was_a,
        "_enter_checks": (a_income_enter, a_dd_enter, a_corr_enter),
        "_exit_checks":  (a_income_exit,  a_dd_exit,  a_corr_exit),
        "_div_yield":    div_yield,
        "_max_dd":       m.get("max_dd", 0.0),
        "_spy_corr":     m.get("spy_corr", 0.0),
    }
    if a_pass:
        grades.append("A")

    # ── B: Gorilla (blue-chip) ──
    was_b = "B" in prev
    b_mcap_enter    = mcap > 1e11
    b_mcap_exit     = mcap < 8e10
    b_dd3y_enter    = m.get("max_dd_3y", 99.0) < 40.0
    b_dd3y_exit     = m.get("max_dd_3y", 99.0) > 50.0
    _ma200          = m.get("ma200")
    b_ma200_enter   = _ma200 is not None and m["curr"] > _ma200 * 1.03
    b_ma200_exit    = _ma200 is not None and m["curr"] < _ma200 * 0.95

    if was_b:
        b_pass = not b_mcap_exit and not b_dd3y_exit and not b_ma200_exit
    else:
        b_pass = b_mcap_enter and b_dd3y_enter and b_ma200_enter

    all_details["B"] = {
        "pass": b_pass,
        "市值":          (b_mcap_enter if not was_b else not b_mcap_exit,
                         f"${mcap/1e9:.0f}B（进入>$1000亿，退出<$800亿）"),
        "近3年最大回撤":  (b_dd3y_enter if not was_b else not b_dd3y_exit,
                         f"{m.get('max_dd_3y', 0):.1f}%（进入<40%，退出>50%）"),
        "价格vs MA200":  (b_ma200_enter if not was_b else not b_ma200_exit,
                         f"{'>' if b_ma200_enter else '<'}MA200（进入需>MA200×1.03，退出需<MA200×0.95）"),
    }
    if b_pass:
        grades.append("B")

    # ── C: King (growth momentum) ──
    was_c = "C" in prev
    c_rs_enter      = m["rs_rank_pct"] <= 0.20
    c_rs_exit       = m["rs_rank_pct"] > 0.35
    _ma250          = m.get("ma250")
    c_ma250_enter   = _ma250 is not None and m["curr"] > _ma250
    c_ma250_exit    = _ma250 is not None and m["curr"] < _ma250 * 0.95

    if was_c:
        c_pass = not c_rs_exit and not c_ma250_exit
    else:
        c_pass = c_rs_enter and c_ma250_enter

    all_details["C"] = {
        "pass": c_pass,
        "RS动量排名": (c_rs_enter if not was_c else not c_rs_exit,
                      f"全域前 {m['rs_rank_pct']*100:.0f}%（进入≤20%，退出>35%）"),
        "年线支撑":   (c_ma250_enter if not was_c else not c_ma250_exit,
                      f"curr vs MA250（进入需站上年线，退出需<MA250×0.95）"),
    }
    if c_pass:
        grades.append("C")

    # ── Z: Cash-flow fortress (high dividend, no hysteresis on entry) ──
    z_div_pass = div_yield >= 1.0
    all_details["Z"] = {
        "pass": z_div_pass,
        "股息率": (z_div_pass, f"{div_yield:.2f}%（需≥1.0%，零股息资产不参赛）"),
    }
    if z_div_pass:
        grades.append("Z")

    # ── D: Scout (speculative momentum, no hysteresis) ──
    d_mom20 = m["mom20"] > 8.0
    d_mom5  = m["mom5"] > 5.0
    d_hv    = m.get("hv_60d", 0.0) > 0.25
    d_pass  = (d_mom20 or d_mom5) and d_hv

    all_details["D"] = {
        "pass": d_pass,
        "20日涨幅":       (d_mom20, f"{m['mom20']:+.1f}%（需>+8%）"),
        "5日涨幅":        (d_mom5,  f"{m['mom5']:+.1f}%（需>+5%）"),
        "60日年化波动率": (d_hv,    f"{m.get('hv_60d', 0.0)*100:.1f}%（需>25%）"),
    }
    if d_pass:
        grades.append("D")

    return grades, all_details


def _primary_grade(grades: list) -> str:
    """Return highest-priority grade from qualifying list, or '?' if empty."""
    if not grades:
        return "?"
    return min(grades, key=lambda g: _GRADE_PRIORITY.get(g, 99))


# ── Deprecated: original cascade funnel classifier ──
def classify_asset(m: dict, div_yield: float, mcap: float) -> tuple:
    """Funnel classification: A -> B -> C -> D -> ?.

    Returns (class_str, reason_str, criteria_detail_dict).
    """
    if not m.get("has_data"):
        return "?", "数据不足，无法完成分拣", {}

    # -- A --
    a_income = div_yield >= 1.0 or m["is_bullish"]
    a_dd     = m["max_dd"] < 15.0
    a_corr   = m["spy_corr"] < 0.65
    div_tag  = f"股息 {div_yield:.1f}%" if div_yield >= 1.0 else "趋势健康(无股息)"
    detail_a = {
        "收益来源(股息/趋势)": (a_income, f"{div_tag}（需股息≥1% 或 MA20>MA60）"),
        "1年最大回撤":        (a_dd,     f"{m['max_dd']:.1f}%（需<15%）"),
        "SPY相关性":          (a_corr,   f"{m['spy_corr']:.2f}（需<0.65）"),
    }
    if a_income and a_dd and a_corr:
        reason = (
            f"通过A级三重关卡：{div_tag}，"
            f"1年最大回撤 {m['max_dd']:.1f}% < 15%，"
            f"SPY相关性 {m['spy_corr']:.2f} < 0.65（低相关，对冲价值高）"
        )
        return "A", reason, detail_a

    # -- B --
    b_mcap        = mcap > 1e11
    b_dd_3y       = m.get("max_dd_3y", 99.0) < 40.0
    _ma200        = m.get("ma200")
    b_above_ma200 = _ma200 is not None and m["curr"] > _ma200
    detail_b = {
        "市值":         (b_mcap,        f"${mcap/1e9:.0f}B（需>$1000亿）"),
        "近3年最大回撤": (b_dd_3y,       f"{m.get('max_dd_3y', 0):.1f}%（需<40%）"),
        "价格vs MA200":  (b_above_ma200, f"收盘价{'>' if b_above_ma200 else '<'}MA200（长线牛熊）"),
    }
    if b_mcap and b_dd_3y and b_above_ma200:
        reason = (
            f"通过B级三重关卡：市值 ${mcap/1e9:.0f}B > $1000亿，"
            f"近3年最大回撤 {m.get('max_dd_3y', 0):.1f}% < 40%，"
            f"收盘价({m['curr']:.1f}) > MA200({_ma200:.1f}) 长线趋势健康"
        )
        return "B", reason, detail_b

    b_reject_note = ""
    if b_mcap and (not b_dd_3y or not b_above_ma200):
        _rej = []
        if not b_dd_3y:
            _rej.append(f"因近3年最大回撤超标被拒签({m.get('max_dd_3y', 0):.1f}%>=40%)")
        if not b_above_ma200:
            _rej.append("收盘价未站上MA200")
        b_reject_note = "[B级拒签：" + "，".join(_rej) + "] "

    # -- C --
    c_rs    = m["rs_rank_pct"] <= 0.20
    c_trend = m["full_uptrend"]
    detail_c = {
        "RS动量排名": (c_rs,    f"全域前 {m['rs_rank_pct']*100:.0f}%（需≤20%）"),
        "主升浪":     (c_trend, f"MA20>MA60>MA250：{'✅' if c_trend else '❌'}"),
    }
    if c_rs and c_trend:
        reason = (
            f"通过C级双重关卡：RS动量排名全域前 {m['rs_rank_pct']*100:.0f}%，"
            f"站稳 MA20>MA60>MA250 主升浪"
        )
        return "C", b_reject_note + reason, detail_c

    # -- D --
    d_mom20 = m["mom20"] > 8.0
    d_mom5  = m["mom5"] > 5.0
    d_hv    = m.get("hv_60d", 0.0) > 0.25
    detail_d = {
        "20日涨幅":       (d_mom20, f"{m['mom20']:+.1f}%（需>+8%）"),
        "5日涨幅":        (d_mom5,  f"{m['mom5']:+.1f}%（需>+5%）"),
        "60日年化波动率": (d_hv,    f"{m.get('hv_60d', 0.0)*100:.1f}%（需>25%）"),
    }
    if (d_mom20 or d_mom5) and d_hv:
        reason = (
            f"通过D级关卡：20日涨幅 {m['mom20']:+.1f}%，"
            f"5日涨幅 {m['mom5']:+.1f}%，"
            f"60日年化波动率 {m.get('hv_60d', 0.0)*100:.1f}% > 25%，近期资金介入信号强烈"
        )
        return "D", b_reject_note + reason, detail_d

    # -- Not classified --
    fail_parts = []
    if not a_income:  fail_parts.append(f"股息率{div_yield:.1f}%且趋势走弱")
    if not a_dd:   fail_parts.append(f"回撤{m['max_dd']:.1f}%过大")
    if not b_mcap: fail_parts.append(f"市值${mcap/1e9:.0f}B不足")
    if not c_rs:   fail_parts.append(f"RS排名{m['rs_rank_pct']*100:.0f}%靠后")
    if not d_mom20 and not d_mom5:
        fail_parts.append(f"动量不足({m['mom20']:+.1f}%)")
    elif not d_hv:
        fail_parts.append(f"因年化波动率不足25%被拒签（HV_60d={m.get('hv_60d', 0.0)*100:.1f}%）")
    reason = b_reject_note + "未通过任何分拣关卡：" + "，".join(fail_parts[:4])
    return "?", reason, {}


def classify_all_at_date(
    price_df: pd.DataFrame,
    date_idx: int,
    screen_tickers: list,
    meta_data: dict,
    tic_map: dict = None,
    prev_grades_map: dict = None,
    z_seed_tickers: set = None,
    thresholds: dict = None,
) -> dict:
    """Run the full parallel ABCD classification at a specific historical date.

    Parameters
    ----------
    price_df : DataFrame with DatetimeIndex, columns = tickers (including SPY).
    date_idx : Integer row index into price_df; the slice ``price_df.iloc[:date_idx+1]``
               represents all data available up to (and including) that date.
    screen_tickers : List of tickers to classify (excluding SPY).
    meta_data : {ticker: {"mcap": float, "div_yield": float}} — current metadata
                used as an approximation for all historical dates.
    tic_map : Optional {ticker: cn_name} for human-readable names.
    prev_grades_map : Optional {ticker: [grade_list]} from previous period for hysteresis.
    z_seed_tickers : Optional set of tickers from Z_SEED_POOL; excluded from A-grade
                     to prevent fixed-income/yield assets dominating the equity arena.

    Returns
    -------
    {ticker: {"cls": str, "qualifying_grades": list, "primary_cls": str,
              "criteria": dict, "cn_name": str, ...}}
    """
    if tic_map is None:
        tic_map = {}
    if prev_grades_map is None:
        prev_grades_map = {}

    df_slice = price_df.iloc[: date_idx + 1]

    # Pass 1: compute per-asset metrics
    all_metrics: dict = {}
    for ticker in screen_tickers:
        all_metrics[ticker] = compute_metrics(ticker, df_slice, spy_col="SPY")

    # RS rank across the pool
    spy_ts = df_slice["SPY"].dropna().astype(float) if "SPY" in df_slice.columns else pd.Series(dtype=float)
    spy_6m = (
        (float(spy_ts.iloc[-1]) / float(spy_ts.iloc[-127]) - 1) * 100
        if len(spy_ts) >= 127 and float(spy_ts.iloc[-127]) > 0 else 0.0
    )
    rs_values: dict = {
        t: m["rs_raw"] - spy_6m
        for t, m in all_metrics.items()
        if m.get("has_data") and m.get("rs_raw") is not None
    }
    if rs_values:
        rs_series = pd.Series(rs_values)
        n = len(rs_series)
        rs_ranks = (rs_series.rank(ascending=False, method="average") - 1) / n
        for t in all_metrics:
            if t in rs_values:
                all_metrics[t]["rs_rank_pct"] = round(float(rs_ranks[t]), 3)
                all_metrics[t]["rs_rel"]      = round(rs_values[t], 1)

    # Pass 2: parallel classify with hysteresis
    _z_seeds = set(z_seed_tickers or ())
    all_assets: dict = {}
    for ticker in screen_tickers:
        m       = all_metrics[ticker]
        m_info  = meta_data.get(ticker, {"mcap": 0, "div_yield": 0.0})
        mcap      = float(m_info.get("mcap", 0) or 0)
        div_yield = float(m_info.get("div_yield", 0.0) or 0.0)
        cn_name   = tic_map.get(ticker, ticker)
        prev_g    = prev_grades_map.get(ticker, [])

        q_grades, details = classify_asset_parallel(m, div_yield, mcap, prev_grades=prev_g, thresholds=thresholds)

        if ticker in _z_seeds and "A" in q_grades:
            q_grades = [g for g in q_grades if g != "A"]

        p_cls = _primary_grade(q_grades)

        all_assets[ticker] = {
            "cls":               p_cls,
            "qualifying_grades": q_grades,
            "primary_cls":       p_cls,
            "criteria":          details,
            "cn_name":           cn_name,
            "has_data":          m.get("has_data", False),
            "is_bullish":        m.get("is_bullish", False),
            "slow_bullish":      m.get("slow_bullish", False),
            "z_score":           m.get("z_score", 0.0),
            "mom20":             m.get("mom20", 0.0),
            "trend_label":       m.get("trend_label", "数据不足"),
            "rs_rank_pct":       m.get("rs_rank_pct", 1.0),
            "rs_rel":            m.get("rs_rel", 0.0),
            "sortino":           m.get("sortino", 0.0),
            "max_dd":            m.get("max_dd", 0.0),
            "spy_corr":          m.get("spy_corr", 0.0),
            "div_yield":         div_yield,
            "mcap":              mcap,
        }

    return all_assets
