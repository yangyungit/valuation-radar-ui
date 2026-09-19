"""财务恶化阶段体检：找出 FCF / OCF / 净利掉头向下、营收增速掉档的时段，
逐段给出「像什么问题」和「股价到底受没受影响」。

判断股价受影响与否靠两把尺子，缺一不可：
  1. 这段的最大回撤在该股**自己**历史回撤里排第几分位——跌 30% 对 KO 是大事，对 AMZN 是家常便饭；
  2. 同窗口 SPY 跌了多少——2008 年 AMZN 跌 56%，SPY 跌 51%，那是大盘的事，不是基本面的事。

纯计算，不 import streamlit，可直接跑脚本验证。
"""
import numpy as np
import pandas as pd

METRICS = [("ocf_usd", "OCF"), ("fcf_usd", "FCF"), ("net_income_usd", "净利")]


def _clean(values, index):
    s = pd.Series(values, index=index, dtype=float).dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


def _episodes(s, rebound_frac=0.30, rebound_cap=None, min_q=2):
    """峰 → 谷 → 确认回升。回升幅度要达到跌幅的 rebound_frac 才认拐点，否则谷底一路顺延。

    rebound_cap 给营收增速用：增速是长期衰减的量（AMZN 从 313% 掉到个位数），
    按跌幅比例要求回升会把 24 年并成一段，改成「回升 5pp 就算拐头」。
    """
    if len(s) < 8:
        return []
    raw, pk, tr = [], 0, None
    for i in range(1, len(s)):
        v = s.iloc[i]
        if tr is None:
            if v >= s.iloc[pk]:
                pk = i
            else:
                tr = i
            continue
        if v <= s.iloc[tr]:
            tr = i
            continue
        depth = s.iloc[pk] - s.iloc[tr]
        need = depth * rebound_frac if rebound_cap is None else min(depth * rebound_frac, rebound_cap)
        if depth > 0 and (v - s.iloc[tr]) >= need:
            raw.append((pk, tr, False))
            pk, tr = i, None
    if tr is not None and s.iloc[tr] < s.iloc[pk]:
        raw.append((pk, tr, True))

    out = []
    for a, b, _ in raw:
        if b - a < min_q:
            continue
        back = s.index[(s.index > s.index[b]) & (s.values >= s.iloc[a])]
        # 谷底就落在最后一两个披露点上 = 还没看到拐头，别当成已经走完的历史段
        out.append(dict(t0=s.index[a], t1=s.index[b], v0=float(s.iloc[a]), v1=float(s.iloc[b]),
                        quarters=b - a, ongoing=b >= len(s) - 2,
                        recovered=back[0] if len(back) else None))
    return out


def _asof(s, t):
    v = s[s.index <= t]
    return float(v.iloc[-1]) if len(v) else np.nan


def drawdowns(s, min_depth=0.10):
    """整段历史里所有 ≥min_depth 的回撤深度（峰→谷），用来给单次回撤排分位。"""
    out, a, tr = [], 0, None
    for i in range(1, len(s)):
        v = s.iloc[i]
        if tr is None:
            if v >= s.iloc[a]:
                a = i
            else:
                tr = i
            continue
        if v <= s.iloc[tr]:
            tr = i
            continue
        if v >= s.iloc[a]:
            if (dep := 1 - s.iloc[tr] / s.iloc[a]) >= min_depth:
                out.append(dep)
            a, tr = i, None
    if tr is not None and (dep := 1 - s.iloc[tr] / s.iloc[a]) >= min_depth:
        out.append(dep)
    return sorted(out)


def metric_episodes(f, datekey, min_drop_pct=25, min_rev_pct=3, min_yoy_pp=10):
    """逐个指标找恶化段。

    金额类要同时过两道门槛：跌幅占峰值 ≥min_drop_pct%，且跌掉的绝对额 ≥ 营收的 min_rev_pct%。
    只看百分比会把「净利从 0.1 亿掉到 0.01 亿」判成 -90% 的大事，只看占营收会漏掉小体量公司。
    峰值本身是负数时百分比没意义（-0.3 亿掉到 -14 亿算跌几倍？），只用占营收那道门槛。
    """
    rev = _clean(f.get("revenue_usd"), datekey)
    out = []
    for key, name in METRICS:
        if not f.get(key):
            continue
        s = _clean(f[key], datekey)
        for e in _episodes(s):
            drop = e["v0"] - e["v1"]
            r = _asof(rev, e["t0"])
            rev_frac = drop / r * 100 if r > 0 else np.nan
            pct = drop / abs(e["v0"]) * 100 if e["v0"] > 0 else np.nan
            if not (rev_frac >= min_rev_pct):
                continue
            if not (np.isnan(pct) or pct >= min_drop_pct):
                continue
            out.append({**e, "metric": name, "drop": pct, "unit": "%", "drop_rev": rev_frac})
    if f.get("rev_yoy"):
        for e in _episodes(_clean(f["rev_yoy"], datekey), rebound_cap=5.0):
            if (pp := e["v0"] - e["v1"]) >= min_yoy_pp:
                out.append({**e, "metric": "营收增速", "drop": pp, "unit": "pp",
                            "drop_rev": np.nan})
    out.sort(key=lambda x: (x["t0"], x["t1"]))
    return out


def _diagnose(metrics, rev_chg, d_op_margin, op_margin_end, d_capex_frac):
    """把「坏了哪几项 + 利润率怎么动 + CapEx 怎么动」翻译成一句人话。
    顺序即优先级：先看营收本身，再看主营利润率，最后才轮到线下项和资本开支。"""
    if op_margin_end < 0:
        main = "整段都在亏，本来就是烧钱期"
    elif rev_chg < -2:
        main = "营收本身在缩，需求端出问题"
    elif d_op_margin <= -2 and ("OCF" in metrics or "净利" in metrics):
        main = "经营利润率真的掉了，主营变差"
    elif "OCF" in metrics:
        main = "利润率没坏，OCF 掉更像营运资本/收付时点"
    elif "净利" in metrics:
        main = "经营利润率没坏，净利被线下项打掉（税/减值/投资损益），一次性嫌疑大"
    elif "FCF" in metrics:
        main = "OCF 和净利都没掉，只有 FCF 掉"
    elif metrics == {"营收增速"}:
        main = "只是增速放缓，利润和现金流没坏"
    else:
        main = "多项同时走弱"
    if "FCF" in metrics and d_capex_frac > 1:
        main += f"；同时 CapEx 占营收 +{d_capex_frac:.0f}pp，是在加投入"
    return main


def _verdict(quantile, excess_pp, big_q=75, mild_q=40, excess_gate=15):
    if quantile >= big_q and (np.isnan(excess_pp) or excess_pp >= excess_gate):
        return "有影响（自身问题）"
    if quantile >= big_q:
        return "跌得深，但大盘同跌"
    if quantile < mild_q:
        return "基本没影响"
    return "影响有限"


def build_phases(f, datekey, price, spy=None, *, min_drop_pct=25, min_rev_pct=3,
                 min_yoy_pp=10, pad_months=3):
    """把逐指标的恶化段按时间重叠合并成阶段，逐段配上原因判断和股价影响判断。

    price / spy 都是 pd.Series(index=DatetimeIndex)。spy 传 None 时不给同期大盘对比。
    """
    eps = metric_episodes(f, datekey, min_drop_pct, min_rev_pct, min_yoy_pp)
    if not eps:
        return [], eps, []

    phases = []
    for e in eps:
        if phases and e["t0"] <= phases[-1]["t1"]:
            phases[-1]["t1"] = max(phases[-1]["t1"], e["t1"])
            phases[-1]["eps"].append(e)
        else:
            phases.append(dict(t0=e["t0"], t1=e["t1"], eps=[e]))

    price = price.dropna().sort_index()
    hist = drawdowns(price)
    rev = _clean(f.get("revenue_usd"), datekey)
    opm = _clean(f.get("op_margin"), datekey)
    capex = _clean(f.get("capex_usd"), datekey)

    for ph in phases:
        w0 = ph["t0"] - pd.DateOffset(months=pad_months)
        w1 = ph["t1"] + pd.DateOffset(months=pad_months)
        seg = price[(price.index >= w0) & (price.index <= w1)]
        ph["metrics"] = sorted({e["metric"] for e in ph["eps"]})
        ph["ongoing"] = any(e["ongoing"] for e in ph["eps"])
        ph["window"] = (w0, w1)
        if len(seg) < 4:
            ph["depth"] = ph["quantile"] = ph["ret"] = ph["spy_depth"] = ph["excess"] = np.nan
            ph["verdict"] = "价格数据不够"
        else:
            ph["depth"] = float(-(seg / seg.cummax() - 1).min())
            ph["ret"] = float(seg.iloc[-1] / seg.iloc[0] - 1)
            ph["quantile"] = (sum(1 for x in hist if x <= ph["depth"]) / len(hist) * 100
                              if hist else np.nan)
            sseg = spy[(spy.index >= w0) & (spy.index <= w1)] if spy is not None else None
            if sseg is not None and len(sseg) >= 4:
                ph["spy_depth"] = float(-(sseg / sseg.cummax() - 1).min())
                ph["excess"] = (ph["depth"] - ph["spy_depth"]) * 100
            else:
                ph["spy_depth"] = ph["excess"] = np.nan
            ph["verdict"] = _verdict(ph["quantile"], ph["excess"])

        r0, r1 = _asof(rev, ph["t0"]), _asof(rev, ph["t1"])
        ph["rev_chg"] = (r1 / r0 - 1) * 100 if r0 > 0 else np.nan
        ph["om0"], ph["om1"] = _asof(opm, ph["t0"]), _asof(opm, ph["t1"])
        ph["capex0"] = abs(_asof(capex, ph["t0"])) / r0 * 100 if r0 > 0 else np.nan
        ph["capex1"] = abs(_asof(capex, ph["t1"])) / r1 * 100 if r1 > 0 else np.nan
        d_om = ph["om1"] - ph["om0"]
        d_cap = ph["capex1"] - ph["capex0"]
        ph["why"] = _diagnose(set(ph["metrics"]),
                              0 if np.isnan(ph["rev_chg"]) else ph["rev_chg"],
                              0 if np.isnan(d_om) else d_om,
                              0 if np.isnan(ph["om1"]) else ph["om1"],
                              0 if np.isnan(d_cap) else d_cap)
    return phases, eps, hist
