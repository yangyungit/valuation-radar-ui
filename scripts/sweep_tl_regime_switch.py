"""大盘弱势时切走迟缓腿 / 现金——用动量面板之外的信息做换手判别器，已判死。

结论（2026-09-17，复盘见 obsidian_notes/99_Human_Zone/过拟合检测器.md）：20 组 0 通过。
最好的 ma200 → L12/MA6 是 3Y +15.7% / 5Y +20.3% 但 10Y −32.2%，而那个 +15.7% 正好等于
3Y 天花板——盈亏各来自一个事件（2025-04 没割 APP、2020-04 割掉 TSLA），样本量 2，是在赌。

四段输出：
  A  灵敏腿近 10Y 的 121 个执行月按 SPY 强弱分组，看换手和亏损是不是真的挤在弱势月
  A2 弱势月里两条腿的当月候选对拍，不含路径效应
  B  弱势月改走迟缓腿或现金，走页面原净值引擎，按既有判读线过不过
  C  摊开最好那组逐月的持仓差异和三段 Calmar 精确值

信号全部在面板月末 ts 计算、在 ts+1 执行，无前视。跑法：
  cd valuation-radar-ui && PYTHONPATH=scripts ../system/venv/bin/python scripts/sweep_tl_regime_switch.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sweep_tl_dual_window import (
    FAST, HORIZONS, SEG_IMPROVE_MIN, CALMAR_TOL, DD_RELAX,
    build_leg, exec_window_10y, fetch_prices, load_panels, monthly_returns,
    nav_metrics, nav_of, select, shortlist_of, _leg_pick,
)

SLOW_TARGETS = [(12, 6), (12, 10), (14, 6)]


def spy_regimes(spy_daily: pd.DataFrame, months) -> pd.DataFrame:
    """每个面板月末一行，各列 True = 大盘强势（照常走灵敏腿）。"""
    px = spy_daily["Close"].astype(float).dropna()
    ma200 = px.rolling(200).mean()
    ma50 = px.rolling(50).mean()
    hi12 = px.rolling(252).max()

    me = px.resample("ME").last().dropna()
    ma10m = me.rolling(10).mean()
    r12m = me / me.shift(12) - 1.0

    out = {}
    for ts in months:
        d = px.index[px.index <= ts]
        if len(d) == 0:
            continue
        t = d[-1]
        m = me.index[me.index <= ts]
        mt = m[-1] if len(m) else None
        out[ts] = {
            "ma200": px[t] > ma200.get(t, np.nan),
            "ma50_200": ma50.get(t, np.nan) > ma200.get(t, np.nan),
            "dd12_10": (px[t] / hi12.get(t, np.nan) - 1.0) > -0.10,
            "ma10m": (me[mt] > ma10m.get(mt, np.nan)) if mt is not None else np.nan,
            "r12": (r12m.get(mt, np.nan) > 0) if mt is not None else np.nan,
        }
    df = pd.DataFrame.from_dict(out, orient="index").sort_index()
    # 历史不足导致的 NaN 一律按「强势」处理：等价于默认走灵敏腿，和状态机的缺失处理一致
    return df.fillna(True).astype(bool)


def part_a(fast_leg, months, mret, reg) -> pd.DataFrame:
    mh = select({ts: fast_leg for ts in months}, months)
    win = exec_window_10y(mh)
    ex2ts = {fast_leg["rows"][ts]["exec"]: ts for ts in months if ts in fast_leg["rows"]}

    rows = []
    prev = None
    for m in sorted(mh):
        hold = mh[m][0]
        if m in set(win):
            ts = ex2ts[m]
            rows.append({
                "exec": m, "ts": ts, "hold": hold,
                "swap": prev is not None and hold != prev,
                "ret": 0.0 if hold == "CASH" else mret.get((hold, m), np.nan),
                **{c: bool(reg.loc[ts, c]) for c in reg.columns},
            })
        prev = hold
    df = pd.DataFrame(rows)

    print(f"\n【A】灵敏腿 L{FAST[0]}/MA{FAST[1]} 近 10Y {len(df)} 个执行月，按 SPY 强弱分组")
    print("  信号        分组   月数  换手数 换手率 | 月收益 均值/中位数 | 负收益月占比 | 累计收益")
    for c in reg.columns:
        for label, sub in (("强势", df[df[c]]), ("弱势", df[~df[c]])):
            if sub.empty:
                print(f"  {c:<11s} {label}    0 —")
                continue
            r = sub["ret"].dropna()
            cum = float(np.prod(1.0 + r.to_numpy())) - 1.0
            print(f"  {c:<11s} {label} {len(sub):5d} {int(sub['swap'].sum()):6d} "
                  f"{sub['swap'].mean():6.1%} | {r.mean():+7.2%} / {r.median():+7.2%} | "
                  f"{(r < 0).mean():11.1%} | {cum:+9.1%}")
    return df


def part_a2(fast_leg, slow_legs, months, mret, reg, base_df) -> None:
    """弱势月里，迟缓腿当月候选比灵敏腿候选好还是坏——不含路径效应，只看单月对拍。"""
    print("\n【A2】弱势月单月对拍：同一个上月持仓下，两条腿各自的候选当月收益")
    print("  信号        迟缓腿    弱势月 分歧月 | 迟缓胜 灵敏胜 | 迟缓均值 灵敏均值 差")
    for c in reg.columns:
        for (L, MA), slow in slow_legs.items():
            prev, recs = "CASH", []
            for ts in months:
                got = _leg_pick(fast_leg, ts, prev)
                if got is None:
                    continue
                f_tk, ex = got
                s_got = _leg_pick(slow, ts, prev)
                if (ex in set(base_df["exec"])) and (not bool(reg.loc[ts, c])) and s_got:
                    s_tk = s_got[0]
                    if s_tk != f_tk:
                        fr = 0.0 if f_tk == "CASH" else mret.get((f_tk, ex), np.nan)
                        sr = 0.0 if s_tk == "CASH" else mret.get((s_tk, ex), np.nan)
                        if pd.notna(fr) and pd.notna(sr):
                            recs.append((sr, fr))
                prev = f_tk
            n_weak = int((~reg[c]).reindex(months).fillna(False).sum())
            if not recs:
                print(f"  {c:<11s} L{L}/MA{MA:<4d} {n_weak:6d} {0:6d} | 无分歧")
                continue
            a = np.array(recs)
            print(f"  {c:<11s} L{L}/MA{MA:<4d} {n_weak:6d} {len(recs):6d} | "
                  f"{int((a[:, 0] > a[:, 1]).sum()):6d} {int((a[:, 0] < a[:, 1]).sum()):6d} | "
                  f"{a[:, 0].mean():+8.2%} {a[:, 1].mean():+8.2%} "
                  f"{a[:, 0].mean() - a[:, 1].mean():+7.2%}")


def select_with_cash(fast_leg, months, weak: pd.Series) -> dict:
    """弱势月强制持现金，其余月份照灵敏腿选仓。"""
    mh, prev = {}, "CASH"
    for ts in months:
        row = fast_leg["rows"].get(ts)
        if row is None:
            continue
        if bool(weak.get(ts, False)):
            hold = "CASH"
        else:
            hold = prev if (prev != "CASH" and prev in row["valid"]
                            and prev in row["keep"]) else None
            if hold is None:
                hold = row["elig"][0] if row["elig"] else "CASH"
        mh[row["exec"]] = [hold]
        prev = hold
    return mh


def part_b(fast_leg, slow_legs, months, cache, spy_daily, reg) -> None:
    mh_base = select({ts: fast_leg for ts in months}, months)
    base = nav_metrics(mh_base, nav_of(mh_base, cache, spy_daily))
    print("\n【B】弱势月切腿 / 切现金，页面原净值引擎（单边 200bps，现金年化 0）")
    print("  基线 灵敏腿｜" + "｜".join(f"{l.upper()} {base[f'ret_{l}']:+.1f}%" for l, _ in HORIZONS)
          + f"｜calmar {base['calmar_3y']:.2f}/{base['calmar_5y']:.2f}/{base['calmar_10y']:.2f}"
          f"｜dd10y {base['dd_10y']:.1%}｜换股 {base['swaps_10y']}")
    print("\n  信号        弱势去哪  | 收益 3Y / 5Y / 10Y（括号为相对基线）"
          "                       | calmar 3Y/5Y/10Y | dd10y  换股 现金")

    rows = []
    for c in reg.columns:
        weak = ~reg[c]
        for tgt in ["CASH"] + [f"L{L}/MA{MA}" for L, MA in SLOW_TARGETS]:
            if tgt == "CASH":
                mh = select_with_cash(fast_leg, months, weak)
            else:
                L, MA = (int(x) for x in tgt[1:].replace("MA", "").split("/"))
                slow = slow_legs[(L, MA)]
                mh = select({ts: (slow if bool(weak.get(ts, False)) else fast_leg)
                             for ts in months}, months)
            r = nav_metrics(mh, nav_of(mh, cache, spy_daily))
            up = {l: (1 + r[f"ret_{l}"] / 100) / (1 + base[f"ret_{l}"] / 100) - 1
                  for l, _ in HORIZONS}
            r.update({"signal": c, "target": tgt, "up": up})
            rows.append(r)
            print(f"  {c:<11s} {tgt:<9s} | "
                  + " / ".join(f"{r[f'ret_{l}']:+9.1f}%({up[l]:+7.1%})" for l, _ in HORIZONS)
                  + f" | {r['calmar_3y']:.2f}/{r['calmar_5y']:.2f}/{r['calmar_10y']:.2f}"
                  f" | {r['dd_10y']:6.1%} {r['swaps_10y']:4d} {r['cash_months_10y']:4d}")

    ok = [r for r in rows
          if all(r["up"][l] >= SEG_IMPROVE_MIN for l in ("3y", "5y"))
          and all(r[f"calmar_{l}"] >= base[f"calmar_{l}"] - abs(base[f"calmar_{l}"]) * CALMAR_TOL
                  for l, _ in HORIZONS)
          and r["dd_10y"] >= base["dd_10y"] - DD_RELAX]
    print(f"\n  过判读线（3Y 和 5Y 各 +{SEG_IMPROVE_MIN:.0%}、三段 calmar 不劣、"
          f"10Y 回撤不差 {DD_RELAX:.0%} 以上）的组数：{len(ok)} / {len(rows)}")
    for r in ok:
        print(f"    {r['signal']} → {r['target']}｜3Y {r['up']['3y']:+.1%}、"
              f"5Y {r['up']['5y']:+.1%}、10Y {r['up']['10y']:+.1%}")


def part_c(fast_leg, slow_legs, months, mret, reg, cache, spy_daily,
           sig: str, L: int, MA: int) -> None:
    """摊开最好那组到底靠哪几个执行月赚的——只有两三个月就是运气，不是规律。"""
    weak = ~reg[sig]
    slow = slow_legs[(L, MA)]
    mh_base = select({ts: fast_leg for ts in months}, months)
    mh_new = select({ts: (slow if bool(weak.get(ts, False)) else fast_leg)
                     for ts in months}, months)
    win = exec_window_10y(mh_base)
    diff = [m for m in win if mh_base.get(m) != mh_new.get(m)]
    last = max(win)
    print(f"\n【C】{sig} → L{L}/MA{MA}：近 10Y {len(win)} 个执行月里持仓与基线不同的有 {len(diff)} 个")
    print("  执行月  基线持仓 该月收益 | 切换后持仓 该月收益 | 差  | 落在哪些段")
    for m in diff:
        b, n = mh_base[m][0], mh_new[m][0]
        br = 0.0 if b == "CASH" else mret.get((b, m), np.nan)
        nr = 0.0 if n == "CASH" else mret.get((n, m), np.nan)
        segs = [lbl.upper() for lbl, yrs in HORIZONS
                if pd.Timestamp(f"{m}-01") >= pd.Timestamp(f"{last}-01")
                - pd.DateOffset(years=yrs)]
        print(f"  {m} {b:<8s} {br:+7.2%} | {n:<10s} {nr:+7.2%} | {nr - br:+7.2%} | "
              + "/".join(segs))
    base = nav_metrics(mh_base, nav_of(mh_base, cache, spy_daily))
    new = nav_metrics(mh_new, nav_of(mh_new, cache, spy_daily))
    print("  三段 calmar 精确值（判读线要求三段都不劣于基线）：")
    for lbl, _ in HORIZONS:
        b, c = base[f"calmar_{lbl}"], new[f"calmar_{lbl}"]
        print(f"    {lbl.upper():<4s} 基线 {b:.6f} → 切换 {c:.6f}"
              f"（{'不劣' if c >= b - abs(b) * CALMAR_TOL else '劣于基线，被打掉'}）")


def main() -> None:
    cme, memb, asof = load_panels()
    print(f"面板 asof = {asof}｜close_me {cme.shape[0]} 月 × {cme.shape[1]} 只")
    fast_leg = build_leg(cme, memb, *FAST)
    slow_legs = {(L, MA): build_leg(cme, memb, L, MA) for L, MA in SLOW_TARGETS}
    names = shortlist_of([fast_leg] + list(slow_legs.values()))
    cache, spy_daily = fetch_prices(names | {"SPY"})
    print(f"拿到 {len(cache)} 只票日线，SPY {spy_daily.index[0].date()} ~ {spy_daily.index[-1].date()}")

    months = list(cme.index)
    mret = monthly_returns(cache, spy_daily)
    reg = spy_regimes(spy_daily, months)
    print("\nSPY 强弱信号逐年「弱势月数/该年月数」：")
    for c in reg.columns:
        x = (~reg[c]).astype(int)
        by = x.groupby(x.index.year).agg(["sum", "count"])
        print(f"  {c:<11s} " + "、".join(f"{y} {int(r['sum'])}/{int(r['count'])}"
                                        for y, r in by.iterrows() if y >= 2015))

    base_df = part_a(fast_leg, months, mret, reg)
    part_a2(fast_leg, slow_legs, months, mret, reg, base_df)
    part_b(fast_leg, slow_legs, months, cache, spy_daily, reg)
    part_c(fast_leg, slow_legs, months, mret, reg, cache, spy_daily, "ma200", 12, 6)


if __name__ == "__main__":
    main()
