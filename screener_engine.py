"""
Shared screener classification engine.

Provides compute_metrics(), classify_asset(), and classify_all_at_date()
for both real-time Page 2 classification and historical Point-in-Time backfill.
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
) -> dict:
    """Run the full ABCD classification at a specific historical date.

    Parameters
    ----------
    price_df : DataFrame with DatetimeIndex, columns = tickers (including SPY).
    date_idx : Integer row index into price_df; the slice ``price_df.iloc[:date_idx+1]``
               represents all data available up to (and including) that date.
    screen_tickers : List of tickers to classify (excluding SPY).
    meta_data : {ticker: {"mcap": float, "div_yield": float}} — current metadata
                used as an approximation for all historical dates.
    tic_map : Optional {ticker: cn_name} for human-readable names.

    Returns
    -------
    {ticker: {"cls": str, "reason": str, "criteria": dict, "cn_name": str, ...}}
    """
    if tic_map is None:
        tic_map = {}

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

    # Pass 2: classify
    all_assets: dict = {}
    for ticker in screen_tickers:
        m       = all_metrics[ticker]
        m_info  = meta_data.get(ticker, {"mcap": 0, "div_yield": 0.0})
        mcap      = float(m_info.get("mcap", 0) or 0)
        div_yield = float(m_info.get("div_yield", 0.0) or 0.0)
        cn_name   = tic_map.get(ticker, ticker)

        cls, reason, criteria_detail = classify_asset(m, div_yield, mcap)

        all_assets[ticker] = {
            "cls":         cls,
            "reason":      reason,
            "criteria":    criteria_detail,
            "cn_name":     cn_name,
            "has_data":    m.get("has_data", False),
            "is_bullish":  m.get("is_bullish", False),
            "z_score":     m.get("z_score", 0.0),
            "mom20":       m.get("mom20", 0.0),
            "trend_label": m.get("trend_label", "数据不足"),
            "rs_rank_pct": m.get("rs_rank_pct", 1.0),
            "rs_rel":      m.get("rs_rel", 0.0),
            "sortino":     m.get("sortino", 0.0),
            "max_dd":      m.get("max_dd", 0.0),
            "spy_corr":    m.get("spy_corr", 0.0),
            "div_yield":   div_yield,
            "mcap":        mcap,
        }

    return all_assets
