"""科技龙头页双窗口切换离线扫描。

灵敏腿 L=10M/MA4（线上现行）与迟缓腿并存，按「龙头领先程度」信号 + 滞回切换。
净值走页面原引擎 holdings_viz.build_nav_from_holdings（单边 200bps），
三段 3Y/5Y/10Y 归一化 Calmar 取 maximin 选参。不改页面任何代码。

信号有三种（见 SIGNALS）。第一轮只跑 abs（Top1−Top2 动量差绝对值）已判死：
阈值 0.13 是在「龙头和第二名差个位数百分点」的年代校准的，动量差的年度中位数
2015 年 8.4%、2026 年 1266%，量纲漂了两个数量级，近两年一次都不触发。
pct / ratio 两种无量纲信号就是为了绕开这个漂移。

跑法（先 anchor 对账，对上了再 sweep）：
  cd valuation-radar-ui && ../system/venv/bin/python scripts/sweep_tl_dual_window.py --anchor
  cd valuation-radar-ui && ../system/venv/bin/python scripts/sweep_tl_dual_window.py --sweep
  cd valuation-radar-ui && ../system/venv/bin/python scripts/sweep_tl_dual_window.py --sweep --signals pct60,ratio
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import holdings_viz as hv  # noqa: E402

API = "http://127.0.0.1:8000"
FAST = (10, 4)
SLOW_GRID = [(12, 6), (12, 8), (12, 10), (14, 6), (14, 8), (14, 10),
             (15, 6), (15, 8), (15, 10), (10, 8), (10, 10), (12, 4), (14, 4)]
COST_BPS = 200.0
OUT_CSV = Path(__file__).resolve().parent.parent / "data" / "tl_dual_window_sweep.csv"

# 三种切换信号。三者共用一套状态机：信号值低 = 龙头领先不明显 = 秩序不稳定 → 走迟缓腿。
# enter 是进迟缓腿的门槛，exit = enter + offset 是退回灵敏腿的门槛（滞回，exit ≥ enter）。
# anchor 只用于并列时的排序偏好，不参与筛选。
SIGNALS = {
    "abs": {
        "desc": "Top1−Top2 动量差绝对值（第一轮已判死，留着当对照）",
        "enter": [0.05, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25],
        "offsets": [0.0, 0.05, 0.10, 0.20, 0.40],
        "anchor": 0.13,   # 第二道关实测最低桶上界
        "fmt": "{:.2f}",
    },
    "pct24": {
        "desc": "动量差在自己滚动 24 个月分布里的分位",
        "enter": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
        "offsets": [0.0, 0.05, 0.10, 0.15, 0.20],
        "anchor": 0.25,
        "fmt": "{:.2f}",
    },
    "pct36": {
        "desc": "动量差在自己滚动 36 个月分布里的分位",
        "enter": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
        "offsets": [0.0, 0.05, 0.10, 0.15, 0.20],
        "anchor": 0.25,
        "fmt": "{:.2f}",
    },
    "pct60": {
        "desc": "动量差在自己滚动 60 个月分布里的分位",
        "enter": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
        "offsets": [0.0, 0.05, 0.10, 0.15, 0.20],
        "anchor": 0.25,
        "fmt": "{:.2f}",
    },
    "ratio": {
        "desc": "Top1 动量 / Top2 动量（≥1，越接近 1 越胶着）",
        "enter": [1.10, 1.20, 1.35, 1.50, 1.75, 2.00, 2.50],
        "offsets": [0.0, 0.10, 0.25, 0.50, 1.00],
        "anchor": 1.35,
        "fmt": "{:.2f}",
    },
}
DEFAULT_SIGNALS = ["pct24", "pct36", "pct60", "ratio"]
PCT_MIN_MONTHS = 24      # 滚动分位至少要这么多个月的历史才出值，不够记 NaN
# PIT 成分只覆盖 2014-01 起，之前 close_me 面板每月只有 2~8 只票有数（2015 年起才 ~520 只）。
# 「8 只票里第一名领先第二名多少」和「520 只票里龙头领先多少」不是一个量，混进滚动分位的
# 参考分布就是上一轮量纲漂移的同类错误。有效票数不够的月份整月不给信号。
MIN_UNIVERSE = 50

# 选仓层常量，复刻 pages/21_科技龙头.py:376-378 传给 render_group 的实参，不得改。
N_HOLD = 1
BAND = 2
ENTRY_MIN_TOP2_HITS = 2

HORIZONS = [("3y", 3), ("5y", 5), ("10y", 10)]
DD_RELAX = 0.03          # 10Y 回撤比灵敏腿基线差过这么多就剔除（plan 1.8）
CALMAR_TOL = 1e-6        # Calmar 相对容差。没有它 455 组里 425 组会因第 16 位小数被误杀
# 判读线，比第一轮严：上一轮赢家 3Y +0.0% / 5Y +4.3%，收益全挤在 2016-2021。
# 这一轮要求 3Y 和 5Y 两段总收益相对基线各自提升 ≥ 10% 才算「肉眼可见」。
# 只用于打印结论，不筛掉任何行——数字全部落盘由人复核。
SEG_IMPROVE_MIN = 0.10

CSV_FIELDS = [
    "kind", "signal", "slow_L", "slow_MA", "thr_enter", "thr_exit",
    "ret_3y", "ret_5y", "ret_10y", "dd_10y",
    "calmar_3y", "calmar_5y", "calmar_10y",
    "norm_3y", "norm_5y", "norm_10y", "score",
    "swaps_10y", "cash_months_10y", "slow_months", "rejected", "reject_reason",
]


def load_panels() -> tuple[pd.DataFrame, dict, str]:
    """拉 sp500_pit_relay + ndx100_pit_relay 时序，合并出 close_me 面板与 PIT 成分并集。

    合并口径逐行复刻 pages/21_科技龙头.py:_merge_relay_ts：close_me 按日期轴 combine_first
    （标普为底表），成分按月取并集。返回 (close_me, membership, asof)。
    """
    got = {}
    for name in ("sp500_pit_relay", "ndx100_pit_relay"):
        try:
            r = requests.get(f"{API}/api/v1/macro/{name}/timeseries",
                             params={"window": "10Y"}, timeout=300)
            r.raise_for_status()
            js = r.json()
        except Exception as exc:
            raise SystemExit(f"{name} 接口拉不动：{exc}")
        if not js.get("success"):
            raise SystemExit(f"{name} 接口 success=False：{js.get('error')}")
        got[name] = js

    a, b = got["sp500_pit_relay"], got["ndx100_pit_relay"]
    da = pd.DataFrame(a.get("close_me", {}) or {},
                      index=pd.to_datetime(a.get("close_me_dates", []) or [])).astype(float)
    db = pd.DataFrame(b.get("close_me", {}) or {},
                      index=pd.to_datetime(b.get("close_me_dates", []) or [])).astype(float)
    cme = (da.combine_first(db) if not db.empty else da).sort_index()
    if cme.empty or len(cme) < 20:
        raise SystemExit("合并后的 close_me 面板为空或过短，后端面板没建好")

    memb_a = a.get("sp500_membership", {}) or {}
    memb_b = b.get("ndx100_membership", {}) or {}
    memb = {ym: sorted(set(memb_a.get(ym, [])) | set(memb_b.get(ym, [])))
            for ym in set(memb_a) | set(memb_b)}
    return cme, memb, str(a.get("asof"))


def mask_by_membership(df: pd.DataFrame, memb: dict) -> pd.DataFrame:
    """当月不在 PIT 成分里的票分数置 NaN；该月没有成分记录时整行不 mask（同页面）。"""
    allow = pd.DataFrame(True, index=df.index, columns=df.columns)
    for dt in df.index:
        names = memb.get(dt.strftime("%Y-%m"))
        if names:
            allow.loc[dt] = df.columns.isin(names)
    return df.where(allow)


def _inband_streak(rank_df: pd.DataFrame, limit: int) -> pd.DataFrame:
    ib = (rank_df <= limit).to_numpy()
    arr = ib.astype(int)
    for i in range(1, arr.shape[0]):
        arr[i] = (arr[i - 1] + 1) * ib[i]
    return pd.DataFrame(arr, index=rank_df.index, columns=rank_df.columns)


def build_leg(cme: pd.DataFrame, memb: dict, L: int, MA: int,
              since: pd.Timestamp | None = None,
              grace: int = 0, band: float = 0.0) -> dict:
    """返回该腿的 {"score", "rank", "ten6", "streak", "ret_mask"} 五张表 + 预编译的逐月行。

    since 只给 --anchor 的页面口径用：页面 window=10Y 时把 king_m 裁到近 10 年再排名，
    留任掩码 ret_mask 仍走未裁、未 mask 的 close_me（页面 303 行先算掩码、318 行才 mask）。

    grace / band 放宽留任条件，默认 0/0 时和页面完全一致：
    - band：跌破均线不超过 band 就还算站得住（容差带）
    - grace：近 grace+1 个月里只要有一个月站得住就继续留（宽限期，不为第一次跌破就卖）
    """
    ma = cme.rolling(MA).mean()
    ret_mask = cme > ma * (1.0 - band)
    if grace > 0:
        ret_mask = ret_mask.astype(float).rolling(grace + 1, min_periods=1).max() > 0
    score = mask_by_membership(cme / cme.shift(L) - 1.0, memb)
    if since is not None:
        score = score[score.index >= since]
    rank = score.rank(axis=1, ascending=False, method="min")
    ten6 = (rank <= BAND).astype(int).rolling(6, min_periods=1).sum()
    streak = _inband_streak(rank, BAND)
    leg = {"score": score, "rank": rank, "ten6": ten6,
           "streak": streak, "ret_mask": ret_mask}
    leg["rows"] = _compile_rows(leg)
    return leg


def _compile_rows(leg: dict) -> dict:
    """把 _holdings_for_k 每月要查的四件事预先算好，网格里 455 次选仓只做 dict 查表。"""
    rank, score = leg["rank"], leg["score"]
    ten6, streak, rmask = leg["ten6"], leg["streak"], leg["ret_mask"]
    rows: dict = {}
    for ts in rank.index:
        r = rank.loc[ts].dropna().sort_values()
        if r.empty:
            continue
        t6, sk = ten6.loc[ts], streak.loc[ts]
        elig = [t for t in r.index
                if r[t] <= BAND and float(t6.get(t, 0)) >= ENTRY_MIN_TOP2_HITS]
        elig.sort(key=lambda t: (-float(sk.get(t, 0)), float(r[t])))
        keep = rmask.loc[ts] if ts in rmask.index else pd.Series(dtype=bool)
        rows[ts] = {
            "exec": hv.next_month_key(ts.strftime("%Y-%m"), 1),
            "valid": set(score.loc[ts].dropna().index),
            "keep": set(keep[keep.astype(bool)].index),
            "elig": elig,
        }
    return rows


def top2_momentum(fast_score: pd.DataFrame) -> pd.DataFrame:
    """每个月末的 Top1 / Top2 动量（小数）。只用灵敏腿面板算。

    当月有效票不足 MIN_UNIVERSE 只时整月记 NaN——那是 2015 年以前面板只有几只票的年代，
    算出来的「领先程度」和成分完整后的月份不可比。
    """
    out = {}
    for ts, row in fast_score.iterrows():
        v = row.dropna().sort_values(ascending=False)
        out[ts] = ((float(v.iloc[0]), float(v.iloc[1])) if len(v) >= MIN_UNIVERSE
                   else (float("nan"), float("nan")))
    return pd.DataFrame.from_dict(out, orient="index", columns=["m1", "m2"]).sort_index()


def raw_gap(top2: pd.DataFrame) -> pd.Series:
    """Top1−Top2 动量差，第一轮用的绝对量。"""
    return (top2["m1"] - top2["m2"]).rename("abs")


def raw_ratio(top2: pd.DataFrame) -> pd.Series:
    """Top1 动量 / Top2 动量。两个动量都是收益率、可能为负，所以要定边界：

    - m2 > 0：正常相除，结果 ≥ 1（m1 按定义不小于 m2），越接近 1 越胶着
    - m2 ≤ 0 < m1：龙头是全场唯一涨的，领先程度无上限，记 +inf（状态机永远判它守灵敏腿）
    - m1 ≤ 0：全池动量都为负，「谁领先」无意义，记 NaN（状态机保持上月状态）
    """
    m1, m2 = top2["m1"], top2["m2"]
    out = pd.Series(float("nan"), index=top2.index, name="ratio")
    ok = m2 > 0
    out[ok] = m1[ok] / m2[ok]
    out[(~ok) & (m1 > 0)] = float("inf")
    return out


def rolling_pct(gap: pd.Series, window: int) -> pd.Series:
    """gap 在自己最近 window 个月（含当月）分布里的分位。

    只用 t 及之前的月份，无前视。历史不足 PCT_MIN_MONTHS 时给 NaN，
    状态机见 NaN 保持上月状态，所以样本最早那几年默认走灵敏腿。
    """
    g = gap.dropna()
    pct = g.rolling(window, min_periods=PCT_MIN_MONTHS).apply(
        lambda w: float((w <= w[-1]).mean()), raw=True)
    return pct.reindex(gap.index).rename(f"pct{window}")


def build_signals(fast_score: pd.DataFrame, names: list) -> dict:
    """按名字造信号序列，顺便把诊断打出来（量纲漂移就是靠逐年中位数看出来的）。"""
    top2 = top2_momentum(fast_score)
    gap = raw_gap(top2)
    built = {}
    for name in names:
        if name == "abs":
            s = gap
        elif name == "ratio":
            s = raw_ratio(top2)
            live = top2["m1"].notna()          # 只统计成分完整的月份，不含面板稀疏的早年
            n_inf = int(np.isinf(s[live]).sum())
            n_nan = int(s[live].isna().sum())
            print(f"  ratio 边界：成分完整的 {int(live.sum())} 个月里，Top2 动量 ≤ 0 记 +inf 的"
                  f" {n_inf} 个月，全池动量为负记 NaN 的 {n_nan} 个月")
        elif name.startswith("pct"):
            s = rolling_pct(gap, int(name[3:]))
            first = s.first_valid_index()
            print(f"  {name} 首个有效月 {first.date() if first is not None else '无'}"
                  f"（此前保持灵敏腿）")
        else:
            raise SystemExit(f"未知信号 {name}，可选：{'/'.join(SIGNALS)}")
        built[name] = s
        print(f"  {name} 逐年中位数：{yearly_median(s)}")
    return built


def yearly_median(s: pd.Series) -> str:
    g = s.replace([np.inf, -np.inf], float("nan")).dropna()
    if g.empty:
        return "无有效值"
    by = g.groupby(g.index.year).median()
    return "、".join(f"{y} {v:.2f}" for y, v in by.items())


def yearly_trigger(on_slow: pd.Series) -> str:
    """逐年「走迟缓腿的月份数 / 该年月份数」。第一轮就是靠这个看出近两年一次都不触发。"""
    x = on_slow.astype(int)
    by = x.groupby(x.index.year).agg(["sum", "count"])
    return "、".join(f"{y} {int(r['sum'])}/{int(r['count'])}" for y, r in by.iterrows())


def switch_path(sig: pd.Series, thr_enter: float, thr_exit: float) -> pd.Series:
    """滞回状态机：信号低走迟缓、信号高守灵敏。信号缺失保持上月状态，不重置。"""
    on_slow = False
    out = {}
    for ts in sig.index:
        g = sig.get(ts)
        if pd.notna(g):
            on_slow = bool(g < (thr_exit if on_slow else thr_enter))
        out[ts] = on_slow
    return pd.Series(out)


def select(legs_by_month: dict, months) -> dict:
    """统一选仓循环：每月用当月生效那条腿的面板，对组合实际的上月持仓做留任判定。

    n_hold=1 时 _holdings_for_k 的逻辑等价于：上月那只票还有当月分数、且还在自己的
    留任 MA 之上 → 继续拿；否则按「连续在榜月数 → 当月排名」取第一个合格新票，没有则持现金。
    留任失败的票如果当月仍在 Top2 且满足进场门槛，会被原地买回——页面没有进场门（entry_mask
    为 None），这里照旧。返回 {执行月: [票]}。
    """
    mh: dict = {}
    prev = "CASH"
    for ts in months:
        row = legs_by_month[ts]["rows"].get(ts)
        if row is None:
            continue
        hold = prev if (prev != "CASH" and prev in row["valid"] and prev in row["keep"]) else None
        if hold is None:
            hold = row["elig"][0] if row["elig"] else "CASH"
        mh[row["exec"]] = [hold]
        prev = hold
    return mh


def fetch_prices(tickers) -> tuple[dict, pd.DataFrame]:
    """后端 Sharadar 股息复权日线灌进 holdings_viz，不许回退 yfinance。"""
    names = sorted(set(tickers))
    try:
        r = requests.post(f"{API}/api/v1/gbdt/oos_prices",
                          json={"tickers": names}, timeout=600)
        r.raise_for_status()
        raw = r.json().get("prices", {}) or {}
    except Exception as exc:
        raise SystemExit(f"oos_prices 接口拉不动：{exc}")
    hv.prime_sharadar_prices(raw)
    missing = [t for t in names if not raw.get(t)]
    if missing:
        print(f"⚠️ {len(missing)}/{len(names)} 只票后端没有日线，净值里按现金走："
              + "、".join(missing))
    if not raw.get("SPY"):
        raise SystemExit("后端没返回 SPY 日线，净值引擎没有交易日历可用")
    spy_daily = hv.fetch_daily_ohlcv("SPY")
    cache = {t: hv.fetch_daily_ohlcv(t) for t in names if t != "SPY" and raw.get(t)}
    cache = {t: d for t, d in cache.items() if not d.empty}
    return cache, spy_daily


def nav_of(holdings: dict, cache: dict, spy_daily: pd.DataFrame) -> pd.Series:
    return hv.build_nav_from_holdings(
        holdings, cache, spy_daily,
        top_n=N_HOLD, cash_rate=hv.CASH_APY, cost_bps=COST_BPS,
    )["nav"]


def _tail(nav: pd.Series, yrs: int) -> pd.Series | None:
    """尾部 yrs 年切片；历史不够 0.9×yrs 就返回 None，不拿短的冒充长的。"""
    if nav is None or nav.empty:
        return None
    end = nav.index[-1]
    if (end - nav.index[0]).days < yrs * 365.25 * 0.9:
        return None
    return nav[nav.index >= end - pd.DateOffset(years=yrs)]


def trail_calmar(nav: pd.Series, yrs: int) -> float:
    """逐行复刻 buyback_relay_core.py:713 的 _trail_calmar（nav_engine="daily" → 先转周线）。"""
    seg = _tail(nav, yrs)
    if seg is None:
        return float("nan")
    wk = seg.resample("W-FRI").last().dropna()
    if len(wk) < 8:
        return float("nan")
    return hv.compute_nav_kpi(wk).get("calmar", float("nan"))


def trail_ret(nav: pd.Series, yrs: int) -> float:
    seg = _tail(nav, yrs)
    if seg is None or len(seg) < 2:
        return float("nan")
    return (float(seg.iloc[-1]) / float(seg.iloc[0]) - 1) * 100


def trail_dd(nav: pd.Series, yrs: int) -> float:
    """段内最大回撤，负小数（-0.35 = 回撤 35%）。"""
    seg = _tail(nav, yrs)
    if seg is None or len(seg) < 2:
        return float("nan")
    peak = seg.cummax()
    return -float(((peak - seg) / peak.replace(0, float("nan"))).max())


def exec_window_10y(holdings: dict) -> list:
    """最后一个执行月往回数 10 年的执行月列表（实测 121 个，对齐笔记里的 67/121）。"""
    months = sorted(holdings)
    if not months:
        return []
    cut = pd.Timestamp(f"{months[-1]}-01") - pd.DateOffset(years=10)
    return [m for m in months if pd.Timestamp(f"{m}-01") >= cut]


def swaps_10y(holdings: dict) -> int:
    """持仓票发生变化的执行月数，含进出现金。"""
    months = sorted(holdings)
    win = set(exec_window_10y(holdings))
    n = 0
    for i, m in enumerate(months):
        if m in win and i > 0 and holdings[m] != holdings[months[i - 1]]:
            n += 1
    return n


def cash_months_10y(holdings: dict) -> int:
    return sum(1 for m in exec_window_10y(holdings)
               if all(t == "CASH" for t in holdings[m]))


def nav_metrics(holdings: dict, nav: pd.Series) -> dict:
    row = {"dd_10y": trail_dd(nav, 10),
           "swaps_10y": swaps_10y(holdings),
           "cash_months_10y": cash_months_10y(holdings)}
    for lbl, yrs in HORIZONS:
        row[f"ret_{lbl}"] = trail_ret(nav, yrs)
        row[f"calmar_{lbl}"] = trail_calmar(nav, yrs)
    return row


def shortlist_of(legs: list) -> set:
    """任何一条腿历史上进过 Top2 的票的并集。

    选仓只会挑 rank ≤ 2 的票，所以这是「切换组合可能持有的票」的严格超集——
    比 plan 说的「14 条纯腿实际持有过的票」宽，但切换路径可能踩到纯腿没踩过的票，
    按纯腿持仓取价会漏票、漏掉的票在净值里被当现金，属静默错账。
    """
    out: set = set()
    for leg in legs:
        rank = leg["rank"]
        out |= {c for c in rank.columns if bool((rank[c] <= 2).any())}
    return out


def _seg_stats(nav: pd.Series, holdings: dict, label: str) -> None:
    kpi = hv.compute_nav_kpi(nav.resample("W-FRI").last().dropna())
    peak = nav.cummax()
    dd = float(((peak - nav) / peak.replace(0, float("nan"))).max()) * 100
    print(f"  {label}")
    print(f"    区间 {nav.index[0].date()} ~ {nav.index[-1].date()}"
          f"｜总收益 {(float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100:+.1f}%"
          f"｜最大回撤 -{dd:.1f}%"
          f"｜CAGR {kpi.get('cagr', float('nan')) * 100:+.1f}%"
          f"｜Calmar {kpi.get('calmar', float('nan')):.2f}")
    print(f"    换股次数 {swaps_10y(holdings)}｜持现金月数 {cash_months_10y(holdings)}"
          f"｜执行月 {len(exec_window_10y(holdings))}")


def monthly_returns(cache: dict, spy_daily: pd.DataFrame) -> dict:
    """{(票, 执行月): 该月收益}，口径对齐 build_nav_from_holdings：

    月内持有——首个交易日 Open 买入、最后一个交易日 Close 结算。交易日历用 SPY，
    和引擎一致。不含换手成本（成本在 nav_of 里按实际换手扣）。
    """
    cal = spy_daily.index
    keys = pd.Series(cal.strftime("%Y-%m"), index=cal)
    out: dict = {}
    for tk, d in cache.items():
        if d is None or d.empty:
            continue
        win = d.reindex(cal).dropna(subset=["Open", "Close"])
        if win.empty:
            continue
        g = win.groupby(keys.reindex(win.index))
        first_open = g["Open"].first().astype(float)
        last_close = g["Close"].last().astype(float)
        r = (last_close / first_open.where(first_open > 0) - 1.0).dropna()
        for m, v in r.items():
            out[(tk, m)] = float(v)
    return out


def _leg_pick(leg: dict, ts, prev: str):
    """把 select() 里那段选仓判定单独拿出来，给 oracle 逐月问「这条腿这个月会拿什么」。"""
    row = leg["rows"].get(ts)
    if row is None:
        return None
    hold = prev if (prev != "CASH" and prev in row["valid"] and prev in row["keep"]) else None
    if hold is None:
        hold = row["elig"][0] if row["elig"] else "CASH"
    return hold, row["exec"]


def _cost_factor(prev: str, hold: str) -> float:
    """换手成本，复刻引擎：n_hold=1 时 cost_denom 恒为 1，换票扣两腿共 2×COST_BPS。"""
    a = set() if prev == "CASH" else {prev}
    b = set() if hold == "CASH" else {hold}
    return max(0.0, 1.0 - len(a ^ b) * COST_BPS / 10000.0)


def dp_ceiling(fast_leg: dict, slow_leg: dict, months, init_hold: str,
               mret: dict) -> tuple[float, list]:
    """事后视角能拿到的最高终值，动态规划求全局最优（不是贪心）。

    贪心（每月挑当月涨得多的腿）不是上界——这个月换过去会改变下个月的留任判定，
    把人带到更差的持仓链上，实测 5Y 比纯灵敏腿还低 20%。
    状态是「月末 + 当前持仓」，每月两条腿各给一个候选持仓，取到达同一持仓的最大财富。
    含换手成本。返回 (财富倍数, 路径)，路径元素是 (执行月, 持仓, 两条腿各自的候选)。
    """
    dp = {init_hold: (1.0, ())}
    for ts in months:
        nxt: dict = {}
        for prev, (w, path) in dp.items():
            cands = {}
            for name, leg in (("fast", fast_leg), ("slow", slow_leg)):
                got = _leg_pick(leg, ts, prev)
                if got is not None:
                    cands[name] = got
            if not cands:
                continue
            picks = {n: cands[n][0] for n in cands}
            for name, (hold, ex) in cands.items():
                r = 0.0 if hold == "CASH" else mret.get((hold, ex), 0.0)
                w2 = w * _cost_factor(prev, hold) * (1.0 + r)
                if w2 > nxt.get(hold, (-1.0, ()))[0]:
                    nxt[hold] = (w2, path + ((ex, hold, picks),))
        if nxt:
            dp = nxt
    w, path = max(dp.values(), key=lambda v: v[0])
    return w, list(path)


def fixed_leg_wealth(leg: dict, months, init_hold: str, mret: dict) -> float:
    """同一套月度口径下只走一条腿的终值，拿来和 dp_ceiling 对比才是同尺度。"""
    w, prev = 1.0, init_hold
    for ts in months:
        got = _leg_pick(leg, ts, prev)
        if got is None:
            continue
        hold, ex = got
        r = 0.0 if hold == "CASH" else mret.get((hold, ex), 0.0)
        w *= _cost_factor(prev, hold) * (1.0 + r)
        prev = hold
    return w


def run_oracle(cme, memb, fast_leg, slow_legs, cache, spy_daily) -> None:
    """对每条迟缓腿算「完美切换」的收益天花板。

    天花板要是没比纯灵敏腿高多少，说明两条腿近年没有可收割的分歧，换什么信号都白搭；
    天花板要是高很多，说明有肉、只是信号没找对，那就该继续找信号。
    """
    months = list(cme.index)
    mret = monthly_returns(cache, spy_daily)
    mh_fast = select({ts: fast_leg for ts in months}, months)
    ts_exec = {ts: fast_leg["rows"][ts]["exec"] for ts in months if ts in fast_leg["rows"]}
    last_exec = max(ts_exec.values())

    print("\n完美切换天花板（动态规划，事后视角，含 200bps 换手成本）：")
    print("  口径：同段内只走灵敏腿的终值 → 每月可自由选腿的最优终值")
    for lbl, yrs in HORIZONS:
        cut = pd.Timestamp(f"{last_exec}-01") - pd.DateOffset(years=yrs)
        win = [ts for ts in months if ts in ts_exec
               and pd.Timestamp(f"{ts_exec[ts]}-01") >= cut]
        prior = [m for m in sorted(mh_fast) if pd.Timestamp(f"{m}-01") < cut]
        init = mh_fast[prior[-1]][0] if prior else "CASH"
        w_fast = fixed_leg_wealth(fast_leg, win, init, mret)
        print(f"\n  {lbl.upper()}（{len(win)} 个执行月，段初持仓 {init}）"
              f"｜只走灵敏腿 {(w_fast - 1) * 100:+.1f}%")
        best = None
        for (L, MA), leg in slow_legs.items():
            w_orc, path = dp_ceiling(fast_leg, leg, win, init, mret)
            up = w_orc / w_fast - 1
            n_div = sum(1 for _, _, p in path if len(set(p.values())) > 1)
            n_slow = sum(1 for _, h, p in path
                         if len(set(p.values())) > 1 and h == p.get("slow"))
            print(f"    L{L}/MA{MA:<3d} 天花板 {(w_orc - 1) * 100:+10.1f}%"
                  f"｜较灵敏腿 {up:+7.1%}｜最优路径上两腿分歧 {n_div} 月、"
                  f"其中该走迟缓 {n_slow} 月")
            if best is None or up > best[0]:
                best = (up, (L, MA), path)
        if lbl == "3y" and best is not None:
            up, (L, MA), path = best
            print(f"\n    近 3Y 天花板最高的 L{L}/MA{MA}，最优路径上的分歧月：")
            for ex, hold, p in path:
                if len(set(p.values())) <= 1:
                    continue
                f_tk, s_tk = p.get("fast", "—"), p.get("slow", "—")
                f_r = 0.0 if f_tk == "CASH" else mret.get((f_tk, ex), float("nan"))
                s_r = 0.0 if s_tk == "CASH" else mret.get((s_tk, ex), float("nan"))
                print(f"      {ex}｜灵敏 {f_tk:<5s} {f_r:+7.1%}｜迟缓 {s_tk:<5s} {s_r:+7.1%}"
                      f"｜最优选 {'迟缓' if hold == s_tk else '灵敏'}")


def run_retain(cme, memb, fast_leg, cache, spy_daily) -> None:
    """只动灵敏腿的留任宽容度，不做双窗口切换。

    --oracle 摊出来的 10 个决策点全是同一个形状：灵敏腿想换手、最优解是别换。
    迟缓腿的唯一贡献就是它更慢的留任均线不会把人踢出去。所以直接在单腿上加
    宽限期 grace 和容差带 band，对准这 10 个事件，比找切换信号短得多。
    """
    months = list(cme.index)
    mh_base = select({ts: fast_leg for ts in months}, months)
    nav_base = nav_of(mh_base, cache, spy_daily)
    base = nav_metrics(mh_base, nav_base)
    print("\n灵敏腿 L10/MA4 基线（grace=0 band=0，与页面同口径）："
          + "｜".join(f"{l.upper()} {base[f'ret_{l}']:+.1f}%" for l, _ in HORIZONS)
          + f"｜dd_10y {base['dd_10y']:.1%}｜换股 {base['swaps_10y']}")
    print("\n放宽留任后（收益括号里是相对基线的提升）：")
    print("  grace band | 收益 3Y / 5Y / 10Y                                    | "
          "calmar 3Y/5Y/10Y  | 10Y 回撤 换股")

    rows = []
    for grace in (0, 1, 2, 3):
        for band in (0.0, 0.02, 0.05, 0.08, 0.12):
            if grace == 0 and band == 0.0:
                r = dict(base)
            else:
                leg = build_leg(cme, memb, *FAST, grace=grace, band=band)
                mh = select({ts: leg for ts in months}, months)
                r = nav_metrics(mh, nav_of(mh, cache, spy_daily))
            r.update({"grace": grace, "band": band})
            up = {l: (1 + r[f"ret_{l}"] / 100) / (1 + base[f"ret_{l}"] / 100) - 1
                  for l, _ in HORIZONS}
            r["up"] = up
            rows.append(r)
            print(f"  {grace:5d} {band:5.0%} | "
                  + " / ".join(f"{r[f'ret_{l}']:+9.1f}%({up[l]:+6.1%})" for l, _ in HORIZONS)
                  + f" | {r['calmar_3y']:.2f}/{r['calmar_5y']:.2f}/{r['calmar_10y']:.2f} | "
                  f"{r['dd_10y']:6.1%} {r['swaps_10y']:4d}")

    ok = [r for r in rows if all(r["up"][l] >= SEG_IMPROVE_MIN for l in ("3y", "5y"))
          and all(r[f"calmar_{l}"] >= base[f"calmar_{l}"] * (1 - CALMAR_TOL)
                  for l, _ in HORIZONS)]
    print(f"\n3Y 和 5Y 两段收益各自提升 ≥ {SEG_IMPROVE_MIN:.0%}、且三段 Calmar 都不劣于基线的："
          f"{len(ok)} 组")
    for r in sorted(ok, key=lambda r: -min(r["up"]["3y"], r["up"]["5y"])):
        print(f"    grace={r['grace']} band={r['band']:.0%}｜"
              f"3Y {r['up']['3y']:+.1%}、5Y {r['up']['5y']:+.1%}、10Y {r['up']['10y']:+.1%}"
              f"｜换股 {base['swaps_10y']} → {r['swaps_10y']}")


def run_anchor(cme, memb, fast_leg, cache, spy_daily) -> None:
    """两条口径各算一遍纯灵敏腿：一条对页面卡片，一条对 CSV 的 baseline_fast 行。"""
    months = list(cme.index)

    since = cme.index[-1] - pd.DateOffset(years=10)
    page_leg = build_leg(cme, memb, *FAST, since=since)
    page_months = [ts for ts in months if ts >= since]
    mh_page = select({ts: page_leg for ts in page_months}, page_months)
    nav_page = nav_of(mh_page, cache, spy_daily)

    mh_grid = select({ts: fast_leg for ts in months}, months)
    nav_grid = nav_of(mh_grid, cache, spy_daily)
    seg = _tail(nav_grid, 10)

    print("\n纯灵敏腿 L=10M/MA4 自验（熊市防御关闭，单边 200bps，现金年化 0）：")
    _seg_stats(nav_page, mh_page,
               "① 页面口径（king_m 裁到近 10Y 后冷启动选仓）→ 对页面 21 的统计卡")
    _seg_stats(seg, mh_grid,
               "② 网格口径（全历史选仓，尾部切 10Y）→ 对 CSV 的 baseline_fast 行")
    print(f"    ② 的 calmar_10y = {trail_calmar(nav_grid, 10):.4f}"
          f"（验收第 6 条要求与 CSV baseline_fast 完全相同）")

    tail = sorted(mh_page)[-14:]
    print("\n  页面口径最近 14 个执行月：" + "、".join(f"{m} {mh_page[m][0]}" for m in tail))


def score_rows(rows: list) -> None:
    """每段拿全池最大 Calmar 当分母各自归一，score = 三段归一值取最小（maximin）。"""
    best = {}
    for lbl, _ in HORIZONS:
        vals = [r[f"calmar_{lbl}"] for r in rows if pd.notna(r[f"calmar_{lbl}"])]
        best[lbl] = max(vals) if vals else float("nan")
    for r in rows:
        norms = []
        for lbl, _ in HORIZONS:
            c, b = r[f"calmar_{lbl}"], best[lbl]
            n = c / b if (pd.notna(c) and pd.notna(b) and b) else float("nan")
            r[f"norm_{lbl}"] = n
            norms.append(n)
        r["score"] = float("nan") if any(pd.isna(n) for n in norms) else min(norms)
        r["norm_std"] = float("nan") if any(pd.isna(n) for n in norms) else float(np.std(norms))


def mark_rejected(rows: list, base: dict) -> None:
    """硬约束只影响推荐排名，不影响落盘：三段 Calmar 都不许比纯灵敏腿差，10Y 回撤不许差 3pp 以上。

    Calmar 比较必须带相对容差：没走切换的月份净值和基线逐位相同，浮点累加顺序不同会在
    第 16 位小数上分出高下，第一轮就是这样把 425 组「其实完全等于基线」的组误判成劣于基线。
    """
    for r in rows:
        why = []
        for lbl, _ in HORIZONS:
            c, b = r[f"calmar_{lbl}"], base[f"calmar_{lbl}"]
            if pd.isna(c):
                why.append(f"calmar_{lbl}_nan")
            elif pd.notna(b) and c < b - abs(b) * CALMAR_TOL:
                why.append(f"calmar_{lbl}<{b:.2f}")
        if pd.notna(r["dd_10y"]) and pd.notna(base["dd_10y"]) \
                and r["dd_10y"] < base["dd_10y"] - DD_RELAX:
            why.append(f"dd_10y<{base['dd_10y'] - DD_RELAX:.2%}")
        r["rejected"] = bool(why)
        r["reject_reason"] = "|".join(why)


def rank_key(r: dict) -> tuple:
    thr, sig = r["thr_enter"], r["signal"]
    anchor = SIGNALS[sig]["anchor"] if sig in SIGNALS else None
    return (-r["score"], r["norm_std"], r["swaps_10y"],
            abs(thr - anchor) if (thr is not None and anchor is not None) else 9.99)


def show_top(rows: list, n: int = 15) -> None:
    print(f"\n推荐排名前 {n}（maximin 得分，已剔除被硬约束打掉的组）：")
    print("  信号    迟缓腿   enter  exit  | score  std    | calmar 3Y/5Y/10Y  | "
          "swaps slow cash | 收益 3Y/5Y/10Y | 10Y 回撤")
    for r in rows[:n]:
        leg = ("灵敏基线" if r["kind"] == "baseline_fast"
               else f"L{r['slow_L']}/MA{r['slow_MA']}")
        thr = ("  —     —  " if r["thr_enter"] is None
               else f"{r['thr_enter']:5.2f} {r['thr_exit']:5.2f}")
        print(f"  {r['signal'] or '—':<7s} {leg:<9s}{thr} | "
              f"{r['score']:.4f} {r['norm_std']:.4f} | "
              f"{r['calmar_3y']:.2f}/{r['calmar_5y']:.2f}/{r['calmar_10y']:.2f} | "
              f"{r['swaps_10y']:5d} {r['slow_months']:4d} {r['cash_months_10y']:4d} | "
              f"{r['ret_3y']:+.0f}%/{r['ret_5y']:+.0f}%/{r['ret_10y']:+.0f}% | "
              f"{r['dd_10y']:.1%}")


def show_verdict(rows: list, base: dict, signals: dict) -> None:
    """对每种信号的头名逐段对基线，直接给过不过。

    第一轮死在「收益全在 10Y、近 3 年完全无反应」，所以这里把 3Y / 5Y 的相对提升
    和逐年触发次数摆在一起——不触发就不可能有提升，两个数看在一起才知道是信号没响
    还是响了没用。
    """
    print(f"\n判读（要求 3Y 和 5Y 两段总收益相对基线各自提升 ≥ {SEG_IMPROVE_MIN:.0%}）：")
    for name in signals:
        cand = [r for r in rows if r["signal"] == name and not r["rejected"]
                and pd.notna(r["score"])]
        if not cand:
            print(f"\n  【{name}】没有任何组通过硬约束")
            continue
        r = sorted(cand, key=rank_key)[0]
        print(f"\n  【{name}】头名 L{r['slow_L']}/MA{r['slow_MA']} "
              f"enter={r['thr_enter']} exit={r['thr_exit']}"
              f"（{len(cand)} 组过约束）")
        deltas = {}
        for lbl, _ in HORIZONS:
            b, c = base[f"ret_{lbl}"], r[f"ret_{lbl}"]
            d = (1 + c / 100) / (1 + b / 100) - 1 if pd.notna(b) and pd.notna(c) else float("nan")
            deltas[lbl] = d
            print(f"    {lbl.upper():>4s} 总收益 {b:+.1f}% → {c:+.1f}%（相对 {d:+.1%}）"
                  f"｜Calmar {base[f'calmar_{lbl}']:.2f} → {r[f'calmar_{lbl}']:.2f}")
        print(f"    10Y 回撤 {base['dd_10y']:.1%} → {r['dd_10y']:.1%}"
              f"｜换股 {base['swaps_10y']} → {r['swaps_10y']}｜走迟缓 {r['slow_months']} 月")
        on_slow = switch_path(signals[name], r["thr_enter"], r["thr_exit"])
        print(f"    逐年触发：{yearly_trigger(on_slow)}")
        ok = all(pd.notna(deltas[l]) and deltas[l] >= SEG_IMPROVE_MIN for l in ("3y", "5y"))
        print(f"    → {'通过' if ok else '不通过'}"
              f"（3Y {deltas['3y']:+.1%}、5Y {deltas['5y']:+.1%}）")


def run_sweep(cme, memb, fast_leg, slow_legs, cache, spy_daily, sig_names) -> None:
    months = list(cme.index)
    print(f"\n造信号（{'、'.join(sig_names)}）：")
    signals = build_signals(fast_leg["score"], sig_names)

    rows: list = []
    nav_cache: dict = {}

    def measured(sig_key, holdings) -> dict:
        """同一条持仓序列不重复跑净值——455 组里大量 (enter, exit) 落到同一条切换路径。"""
        if sig_key not in nav_cache:
            nav_cache[sig_key] = nav_metrics(holdings, nav_of(holdings, cache, spy_daily))
        return dict(nav_cache[sig_key])

    base_holdings = select({ts: fast_leg for ts in months}, months)
    row = {"kind": "baseline_fast", "signal": "", "slow_L": None, "slow_MA": None,
           "thr_enter": None, "thr_exit": None, "slow_months": 0}
    row.update(measured(("fast",), base_holdings))
    rows.append(row)
    base_row = row

    for (L, MA), leg in slow_legs.items():
        holdings = select({ts: leg for ts in months}, months)
        row = {"kind": "baseline_slow", "signal": "", "slow_L": L, "slow_MA": MA,
               "thr_enter": None, "thr_exit": None,
               "slow_months": len(exec_window_10y(holdings))}
        row.update(measured(("slow", L, MA), holdings))
        rows.append(row)

    t0 = time.time()
    total = sum(len(SLOW_GRID) * len(SIGNALS[n]["enter"]) * len(SIGNALS[n]["offsets"])
                for n in sig_names)
    done = 0
    for name in sig_names:
        series, cfg = signals[name], SIGNALS[name]
        for (L, MA), leg in slow_legs.items():
            for enter in cfg["enter"]:
                for off in cfg["offsets"]:
                    exit_ = round(enter + off, 4)
                    on_slow = switch_path(series, enter, exit_)
                    holdings = select({ts: (leg if on_slow.get(ts, False) else fast_leg)
                                       for ts in months}, months)
                    slow_exec = {hv.next_month_key(ts.strftime("%Y-%m"), 1)
                                 for ts in months if bool(on_slow.get(ts, False))}
                    row = {"kind": "switch", "signal": name, "slow_L": L, "slow_MA": MA,
                           "thr_enter": enter, "thr_exit": exit_,
                           "slow_months": len(slow_exec & set(exec_window_10y(holdings)))}
                    key = ("switch", L, MA, tuple(holdings[m][0] for m in sorted(holdings)))
                    row.update(measured(key, holdings))
                    rows.append(row)
                    done += 1
        print(f"  信号 {name} 跑完，{done}/{total} 组，"
              f"净值算了 {len(nav_cache)} 条，{time.time() - t0:.0f}s", flush=True)

    score_rows(rows)
    mark_rejected(rows, base_row)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: (-(r["score"] if pd.notna(r["score"]) else -9),
                                             r["kind"])):
            w.writerow(r)
    print(f"\n写出 {OUT_CSV}（{len(rows)} 行，{OUT_CSV.stat().st_size / 1024:.0f} KB）")

    print("纯灵敏腿基线（硬约束来源）："
          + "｜".join(f"calmar_{l} {base_row[f'calmar_{l}']:.2f}" for l, _ in HORIZONS)
          + f"｜dd_10y {base_row['dd_10y']:.2%}"
          + f"（回撤下限 {base_row['dd_10y'] - DD_RELAX:.2%}）")
    n_rej = sum(1 for r in rows if r["rejected"])
    print(f"{len(rows)} 行里 {n_rej} 行被硬约束剔除，{len(rows) - n_rej} 行进推荐排名")

    kept = [r for r in rows if not r["rejected"] and pd.notna(r["score"])]
    if not kept:
        raise SystemExit("所有组合都被硬约束淘汰，停下汇报（plan 三、最后一条）")
    show_top(sorted(kept, key=rank_key))
    show_verdict(rows, base_row, signals)


def main() -> None:
    ap = argparse.ArgumentParser(description="科技龙头双窗口切换离线扫描")
    ap.add_argument("--anchor", action="store_true", help="只跑纯灵敏腿自验，不跑网格")
    ap.add_argument("--sweep", action="store_true", help="跑 14 基线 + 每种信号 455 组切换网格")
    ap.add_argument("--oracle", action="store_true",
                    help="算完美切换上界（事后选腿），看两条腿近年还有没有可收割的分歧")
    ap.add_argument("--retain", action="store_true",
                    help="只扫灵敏腿的留任宽容度（宽限期 + 容差带），不做双窗口切换")
    ap.add_argument("--signals", default=",".join(DEFAULT_SIGNALS),
                    help=f"逗号分隔，可选 {'/'.join(SIGNALS)}，默认 {','.join(DEFAULT_SIGNALS)}")
    args = ap.parse_args()
    if not (args.anchor or args.sweep or args.oracle or args.retain):
        ap.error("须指定 --anchor / --sweep / --oracle / --retain")
    sig_names = [s.strip() for s in args.signals.split(",") if s.strip()]
    bad = [s for s in sig_names if s not in SIGNALS]
    if bad:
        ap.error(f"未知信号 {'、'.join(bad)}，可选 {'/'.join(SIGNALS)}")

    cme, memb, asof = load_panels()
    print(f"面板 asof = {asof}"
          + ("" if asof == "2026-07-31" else "  ← 不是成文时的 2026-07-31，注意口径")
          + f"｜close_me {cme.shape[0]} 月 × {cme.shape[1]} 只"
          f"（{cme.index[0].date()} ~ {cme.index[-1].date()}）"
          f"｜PIT 成分覆盖 {min(memb)} ~ {max(memb)}")

    fast_leg = build_leg(cme, memb, *FAST)
    slow_legs = {(L, MA): build_leg(cme, memb, L, MA) for L, MA in SLOW_GRID}
    names = shortlist_of([fast_leg] + list(slow_legs.values()))
    print(f"14 条腿历史上进过 Top2 的票共 {len(names)} 只，拉它们的后端日线")
    cache, spy_daily = fetch_prices(names | {"SPY"})
    print(f"拿到 {len(cache)} 只票日线，SPY "
          f"{spy_daily.index[0].date()} ~ {spy_daily.index[-1].date()}")

    if args.anchor:
        run_anchor(cme, memb, fast_leg, cache, spy_daily)
        return
    if args.oracle:
        run_oracle(cme, memb, fast_leg, slow_legs, cache, spy_daily)
        return
    if args.retain:
        run_retain(cme, memb, fast_leg, cache, spy_daily)
        return
    run_sweep(cme, memb, fast_leg, slow_legs, cache, spy_daily, sig_names)


if __name__ == "__main__":
    main()
