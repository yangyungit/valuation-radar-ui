"""质量硬门槛——core_engine / screener_engine / refresh_universe 共用的唯一阈值源。

不依赖 streamlit / yfinance，保证 screener_engine 和回测脚本能零成本 import。

门槛口径（2026-09-19 敲定）：
  - 连续 8 个季度 ROIC / FCF / 净利润全部为正
  - 8 季度 ROIC 中位数 ≥ 10%
  - 债务/EBITDA < 3.0

杠杆用债务/EBITDA 而非负债权益比：常年回购的公司（BKNG / MCK / HPQ / ORLY）
股东权益为负，负债权益比是负数，`de < 2.0` 会因为负数小于 2 而误放行，
改成 `0 < de < 2.0` 又会把这 26 只优质回购股全部误杀。
"""
from __future__ import annotations

QUALITY_ROIC_MED_MIN     = 0.10
QUALITY_DEBT_EBITDA_MAX  = 3.0
QUALITY_LOOKBACK_QUARTERS = 8

# 质量门槛只挂长期持有档。A 压舱石的职责是抗跌、Z 现金流堡垒的职责是收息，
# 都不追求超额收益，挂上去只会被 ROIC 口径误杀公用事业 / REIT / 保险；
# D 侦察兵是短线投机动量，持有期太短，质量是慢变量管不到。
QUALITY_GATED_GRADES = ("B", "C")

# 选股池代码 → Sharadar 代码。必须多对一：GOOG 和 GOOGL 同时在池子里，
# 指向同一家公司同一条 SF1 记录，建反向字典会让其中一只静默丢数据。
SHARADAR_TICKER_OVERRIDES = {
    "GOOG": "GOOGL",
    "FOX":  "FOXA",
    "NWS":  "NWSA",
}


def to_sharadar_ticker(ticker: str) -> str:
    """选股池代码转 Sharadar 代码：双类股特例优先，其余横杠转点号（BRK-B → BRK.B）。"""
    if ticker in SHARADAR_TICKER_OVERRIDES:
        return SHARADAR_TICKER_OVERRIDES[ticker]
    return ticker.replace("-", ".")


def _num(v):
    """把 pandas NA / NaN / None 统一成 None，其余转 float。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _all_positive(series) -> bool:
    """缺失值视作不达标——拿不准就不放行。"""
    vals = [_num(v) for v in series]
    return all(v is not None and v > 0 for v in vals)


def eval_quality(roic_series, fcf_series, netinc_series, debt, ebitda) -> dict:
    """按定好的口径判一只标的。序列需按 datekey 升序、且已截到最近 8 期。

    返回 {quality_pass, roic_med, debt_ebitda, reason}。
    """
    n = len(roic_series)
    if n < QUALITY_LOOKBACK_QUARTERS:
        return {"quality_pass": False, "roic_med": None, "debt_ebitda": None,
                "reason": f"财报仅 {n} 期，不足 {QUALITY_LOOKBACK_QUARTERS} 期"}

    roic_vals = sorted(v for v in (_num(x) for x in roic_series) if v is not None)
    if not roic_vals:
        return {"quality_pass": False, "roic_med": None, "debt_ebitda": None,
                "reason": "8 季度 ROIC 全部缺失"}
    k = len(roic_vals)
    roic_med = roic_vals[k // 2] if k % 2 else (roic_vals[k // 2 - 1] + roic_vals[k // 2]) / 2

    debt_f, ebitda_f = _num(debt), _num(ebitda)
    debt_ebitda = (debt_f / ebitda_f) if (debt_f is not None and ebitda_f and ebitda_f > 0) else None

    if not _all_positive(roic_series):
        reason = "8 季度 ROIC 未能全为正"
    elif not _all_positive(fcf_series):
        reason = "8 季度自由现金流未能全为正"
    elif not _all_positive(netinc_series):
        reason = "8 季度净利润未能全为正"
    elif roic_med < QUALITY_ROIC_MED_MIN:
        reason = f"ROIC 中位 {roic_med:.1%} < {QUALITY_ROIC_MED_MIN:.0%}"
    elif debt_ebitda is None:
        reason = "EBITDA 非正，杠杆无法计算"
    elif debt_ebitda >= QUALITY_DEBT_EBITDA_MAX:
        reason = f"债务/EBITDA {debt_ebitda:.2f} ≥ {QUALITY_DEBT_EBITDA_MAX:.1f}"
    else:
        return {"quality_pass": True, "roic_med": roic_med,
                "debt_ebitda": debt_ebitda, "reason": "通过"}

    return {"quality_pass": False, "roic_med": roic_med,
            "debt_ebitda": debt_ebitda, "reason": reason}


def quality_ok(meta: dict) -> bool:
    """给 ABCD 分类用。

    refresh_universe 会给选股池里每一只都写一行结论，所以线上路径每只都带
    quality_source：算出来不合格的、Sharadar 里找不到的新票（quality_source='missing'）
    一律判不通过，符合「宁缺毋滥」。

    完全没带 quality_source 的是调用方压根没提供质量数据——PIT 回测走的就是这条路
    （历史 meta 只有 mcap/div/fcf）。这种情况下门槛不生效，否则回测里 B/C 两档会
    整体清空。要让回测也带质量门槛，得另外构造逐月的 PIT 质量序列。
    """
    meta = meta or {}
    if not meta.get("quality_source"):
        return True
    return bool(meta.get("quality_pass"))


def quality_detail(meta: dict) -> tuple:
    """白盒展示用，返回 (是否通过, 说明文案)。"""
    meta = meta or {}
    src = meta.get("quality_source")
    if not src:
        return True, "未提供质量数据，本次不施加质量门槛"
    if src == "etf_exempt":
        return True, "ETF 无财报，豁免质量门槛"
    if src == "missing":
        return False, "未通过：Sharadar 无足额财报（新上市或新进成分股），按宁缺毋滥判不通过"

    roic, lev = meta.get("roic_med"), meta.get("debt_ebitda")
    roic_txt = f"{roic:.1%}" if roic is not None else "—"
    lev_txt  = f"{lev:.2f}" if lev is not None else "—"
    asof     = meta.get("quality_asof") or "—"
    tail = (f"ROIC中位 {roic_txt}（需≥{QUALITY_ROIC_MED_MIN:.0%}）、"
            f"债务/EBITDA {lev_txt}（需<{QUALITY_DEBT_EBITDA_MAX:.1f}）、"
            f"8季度ROIC/FCF/净利需全正，财报截至 {asof}")
    if quality_ok(meta):
        return True, f"通过：{tail}"
    why = meta.get("quality_reason")
    head = f"未通过（{why}）" if why else "未通过"
    return False, f"{head}：{tail}"
