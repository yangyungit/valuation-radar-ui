"""科技龙头页双窗口切换离线扫描。

灵敏腿 L=10M/MA4（线上现行）与迟缓腿并存，按「Top1−Top2 动量差」+ 滞回切换。
净值走页面原引擎 holdings_viz.build_nav_from_holdings（单边 200bps），
三段 3Y/5Y/10Y 归一化 Calmar 取 maximin 选参。不改页面任何代码。

跑法（先 anchor 对账，对上了再 sweep）：
  cd valuation-radar-ui && ../system/venv/bin/python scripts/sweep_tl_dual_window.py --anchor
  cd valuation-radar-ui && ../system/venv/bin/python scripts/sweep_tl_dual_window.py --sweep
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
GAP_ENTER_GRID = [0.05, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25]
GAP_EXIT_OFFSETS = [0.0, 0.05, 0.10, 0.20, 0.40]
COST_BPS = 200.0
OUT_CSV = Path(__file__).resolve().parent.parent / "data" / "tl_dual_window_sweep.csv"

# 选仓层常量，复刻 pages/21_科技龙头.py:376-378 传给 render_group 的实参，不得改。
N_HOLD = 1
BAND = 2
ENTRY_MIN_TOP2_HITS = 2

HORIZONS = [("3y", 3), ("5y", 5), ("10y", 10)]
DD_RELAX = 0.03          # 10Y 回撤比灵敏腿基线差过这么多就剔除（plan 1.8）
GAP_ANCHOR = 0.13        # 并列时离它近的赢（第二道关实测最低桶上界）

CSV_FIELDS = [
    "kind", "slow_L", "slow_MA", "gap_enter", "gap_exit",
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
              since: pd.Timestamp | None = None) -> dict:
    """返回该腿的 {"score", "rank", "ten6", "streak", "ret_mask"} 五张表 + 预编译的逐月行。

    since 只给 --anchor 的页面口径用：页面 window=10Y 时把 king_m 裁到近 10 年再排名，
    留任掩码 ret_mask 仍走未裁、未 mask 的 close_me（页面 303 行先算掩码、318 行才 mask）。
    """
    ret_mask = cme > cme.rolling(MA).mean()
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


def compute_gap(fast_score: pd.DataFrame) -> pd.Series:
    """月末 t 的 Top1−Top2 动量差（小数），不足 2 只时 NaN。只用灵敏腿面板算。"""
    out = {}
    for ts, row in fast_score.iterrows():
        v = row.dropna().sort_values(ascending=False)
        out[ts] = float(v.iloc[0] - v.iloc[1]) if len(v) >= 2 else float("nan")
    return pd.Series(out).sort_index()


def switch_path(gap: pd.Series, gap_enter: float, gap_exit: float) -> pd.Series:
    """滞回状态机：差小走迟缓、差大守灵敏。信号缺失保持上月状态，不重置。"""
    on_slow = False
    out = {}
    for ts in gap.index:
        g = gap.get(ts)
        if pd.notna(g):
            on_slow = bool(g < (gap_exit if on_slow else gap_enter))
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
    """硬约束只影响推荐排名，不影响落盘：三段 Calmar 都不许比纯灵敏腿差，10Y 回撤不许差 3pp 以上。"""
    for r in rows:
        why = []
        for lbl, _ in HORIZONS:
            c, b = r[f"calmar_{lbl}"], base[f"calmar_{lbl}"]
            if pd.isna(c):
                why.append(f"calmar_{lbl}_nan")
            elif pd.notna(b) and c < b:
                why.append(f"calmar_{lbl}<{b:.2f}")
        if pd.notna(r["dd_10y"]) and pd.notna(base["dd_10y"]) \
                and r["dd_10y"] < base["dd_10y"] - DD_RELAX:
            why.append(f"dd_10y<{base['dd_10y'] - DD_RELAX:.2%}")
        r["rejected"] = bool(why)
        r["reject_reason"] = "|".join(why)


def rank_key(r: dict) -> tuple:
    gap = r["gap_enter"]
    return (-r["score"], r["norm_std"], r["swaps_10y"],
            abs(gap - GAP_ANCHOR) if gap is not None else 9.99)


def show_top(rows: list, n: int = 15) -> None:
    print(f"\n推荐排名前 {n}（maximin 得分，已剔除被硬约束打掉的组）：")
    print("  迟缓腿   enter  exit  | score  std    | calmar 3Y/5Y/10Y      | "
          "norm 3Y/5Y/10Y      | swaps slow cash | 10Y 收益/回撤")
    for r in rows[:n]:
        leg = ("灵敏基线" if r["kind"] == "baseline_fast"
               else f"L{r['slow_L']}/MA{r['slow_MA']}")
        gap = ("  —     —  " if r["gap_enter"] is None
               else f"{r['gap_enter']:5.2f} {r['gap_exit']:5.2f}")
        print(f"  {leg:<9s}{gap} | {r['score']:.4f} {r['norm_std']:.4f} | "
              f"{r['calmar_3y']:.2f}/{r['calmar_5y']:.2f}/{r['calmar_10y']:.2f}     | "
              f"{r['norm_3y']:.2f}/{r['norm_5y']:.2f}/{r['norm_10y']:.2f}     | "
              f"{r['swaps_10y']:5d} {r['slow_months']:4d} {r['cash_months_10y']:4d} | "
              f"{r['ret_10y']:+.0f}% {r['dd_10y']:.1%}")


def run_sweep(cme, memb, fast_leg, slow_legs, cache, spy_daily) -> None:
    months = list(cme.index)
    gap = compute_gap(fast_leg["score"])
    # 两行分位都打：阈值网格是照近 10Y 分布定的，全历史那段含 2014 年前无 PIT 成分 mask 的月份。
    for lbl, g in (("全历史", gap),
                   ("近 10Y", gap[gap.index >= gap.index[-1] - pd.DateOffset(years=10)])):
        print(f"gap 分位 {lbl}（{int(g.notna().sum())} 个月末）："
              + "、".join(f"P{q}={g.quantile(q / 100):.1%}" for q in (10, 25, 50, 75, 90)))

    rows: list = []
    nav_cache: dict = {}

    def measured(sig_key, holdings) -> dict:
        """同一条持仓序列不重复跑净值——455 组里大量 (enter, exit) 落到同一条切换路径。"""
        if sig_key not in nav_cache:
            nav_cache[sig_key] = nav_metrics(holdings, nav_of(holdings, cache, spy_daily))
        return dict(nav_cache[sig_key])

    base_holdings = select({ts: fast_leg for ts in months}, months)
    base_win = set(exec_window_10y(base_holdings))
    row = {"kind": "baseline_fast", "slow_L": None, "slow_MA": None,
           "gap_enter": None, "gap_exit": None, "slow_months": 0}
    row.update(measured(("fast",), base_holdings))
    rows.append(row)
    base_row = row

    for (L, MA), leg in slow_legs.items():
        holdings = select({ts: leg for ts in months}, months)
        row = {"kind": "baseline_slow", "slow_L": L, "slow_MA": MA,
               "gap_enter": None, "gap_exit": None,
               "slow_months": len(exec_window_10y(holdings))}
        row.update(measured(("slow", L, MA), holdings))
        rows.append(row)

    t0 = time.time()
    total = len(SLOW_GRID) * len(GAP_ENTER_GRID) * len(GAP_EXIT_OFFSETS)
    done = 0
    for (L, MA), leg in slow_legs.items():
        for enter in GAP_ENTER_GRID:
            for off in GAP_EXIT_OFFSETS:
                exit_ = round(enter + off, 4)
                on_slow = switch_path(gap, enter, exit_)
                holdings = select({ts: (leg if on_slow.get(ts, False) else fast_leg)
                                   for ts in months}, months)
                slow_exec = {hv.next_month_key(ts.strftime("%Y-%m"), 1)
                             for ts in months if bool(on_slow.get(ts, False))}
                row = {"kind": "switch", "slow_L": L, "slow_MA": MA,
                       "gap_enter": enter, "gap_exit": exit_,
                       "slow_months": len(slow_exec & set(exec_window_10y(holdings)))}
                sig = ("switch", L, MA, tuple(holdings[m][0] for m in sorted(holdings)))
                row.update(measured(sig, holdings))
                rows.append(row)
                done += 1
        print(f"  L{L}/MA{MA} 跑完，{done}/{total} 组，{time.time() - t0:.0f}s", flush=True)

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


def main() -> None:
    ap = argparse.ArgumentParser(description="科技龙头双窗口切换离线扫描")
    ap.add_argument("--anchor", action="store_true", help="只跑纯灵敏腿自验，不跑网格")
    ap.add_argument("--sweep", action="store_true", help="跑 14 基线 + 455 组切换网格")
    args = ap.parse_args()
    if not (args.anchor or args.sweep):
        ap.error("须指定 --anchor 或 --sweep")

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
    run_sweep(cme, memb, fast_leg, slow_legs, cache, spy_daily)


if __name__ == "__main__":
    main()
