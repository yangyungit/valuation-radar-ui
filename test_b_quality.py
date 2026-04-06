"""
B组细筛质量 Harness Test
═══════════════════════════════════════════════════════════════════

目的：量化B组（大猩猩赛道）历史持仓质量，用 pytest 驱动 AI 自动迭代。

当前架构：信念积累 + 在位者惯性 + 冠军守擂制
  - 因子分数不再直接决定 Top 3 排名
  - 因子分数作为信念积分的输入信号
  - 标的需连续多月表现好才能积累到入选门槛
  - 在位者享有慢衰减（holder_decay_rate），动量噪声不轻易驱逐
  - 在位者享有守擂优势，挑战者必须显著超越才能替换

工作流：
  1. pytest test_b_quality.py -v -s   → 看到详细报告 + 哪些 test FAIL
  2. AI 根据失败原因修改：
     - 信念引擎参数 → conviction_engine.py  CONVICTION_B_CONFIG
     - 入选门槛 → screener_engine.py  classify_asset_parallel()
     - 评分权重 → pages/3_资产细筛.py  compute_scorecard_b()
  3. 在 Streamlit 页面点「回填历史数据」重新生成 arena_history.json
  4. 再跑 pytest → 看是否改善 → 循环直到全部通过

问题根源与可调旋钮一览：
  ┌─────────────────┬─────────────────────────────────────────────────┐
  │ 问题模式         │ 可能的修复方向                                    │
  ├─────────────────┼─────────────────────────────────────────────────┤
  │ 闪现(1-2月)      │ 提高 entry_threshold / 降低 accumulate_rate      │
  │ 碎片化(反复进出)  │ 提高 holder_decay_rate / 加大 challenge_margin    │
  │ 高换手           │ 提高 holder_decay_rate / 加大 challenge_margin    │
  │ 短stint亏损      │ 在 compute_scorecard_b 中加大抗跌韧性权重         │
  │ 长stint低效      │ 在 compute_scorecard_b 中加大夏普权重             │
  │ 严重亏损(>5%)    │ 加入 MA200 趋势健康门槛到分类阶段                  │
  │ 宏观切换碎片化    │ 调整 B_REGIME_WEIGHTS 各剧本档位权重               │
  │ 防御期动量噪声    │ B_REGIME_WEIGHTS Stag/Rec 的 RS120d 已归零        │
  └─────────────────┴─────────────────────────────────────────────────┘

依赖: pip install pytest yfinance pandas numpy
运行: pytest test_b_quality.py -v -s
"""

import json
import pickle
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
#  路径与配置
# ═══════════════════════════════════════════════════════════════════

ROOT = Path(__file__).parent
HISTORY_FILE = ROOT / "data" / "arena_history.json"
PRICE_CACHE = ROOT / "data" / "_test_price_cache.pkl"
TARGET_CLS = "B"
TOP_N = 3

# ═══════════════════════════════════════════════════════════════════
#  质量阈值 —— 这些就是 AI 需要逼近的目标
#  初始值故意偏严，驱动迭代；随着优化推进可逐步收紧
# ═══════════════════════════════════════════════════════════════════

# --- 1. 闪现控制 ---
MIN_STINT_MONTHS = 3          # 低于此月数视为"闪现"
MAX_FLASH_RATIO = 0.30        # 闪现stint占比上限

# --- 2. 碎片化控制 ---
MAX_STINTS_PER_TICKER = 3     # 单ticker最多几段持仓
MAX_FRAGMENTED_RATIO = 0.20   # 超标ticker占比上限

# --- 3. 亏损控制 ---
MAX_LOSING_STINT_RATIO = 0.20  # 亏损stint占比上限
MAX_SEVERE_LOSS_PCT = -5.0     # 单stint最大允许亏损(%)
MAX_SEVERE_LOSS_COUNT = 0      # 严重亏损stint数量上限

# --- 4. 效率控制 ---
MIN_SHORT_STINT_MONTHLY_RET = 1.0   # 短stint(<=3月)月均收益下限(%)
MAX_SHORT_INEFFICIENT_RATIO = 0.40  # 短stint中低效占比上限
MIN_LONG_STINT_ANNUAL_RET = 8.0     # 长stint(>12月)年化收益下限(%)
MAX_LONG_INEFFICIENT_RATIO = 0.30   # 长stint中低效占比上限

# --- 5. 综合指标 ---
MIN_WIN_RATE = 0.65           # stint盈利率下限
MIN_AVG_HOLDING_MONTHS = 3.5  # 平均持仓月数下限

# --- 6. 换手率控制 ---
MAX_AVG_MONTHLY_TURNOVER = 1.0  # 月均 Top3 换入新ticker数上限(3个位子平均每月换≤1个)


# ═══════════════════════════════════════════════════════════════════
#  数据加载工具
# ═══════════════════════════════════════════════════════════════════

def load_b_monthly() -> dict[str, list[str]]:
    """从 arena_history.json 提取B组每月 Top N ticker 列表。"""
    with open(HISTORY_FILE) as f:
        history = json.load(f)
    result = {}
    for month in sorted(k for k in history if not k.startswith("_")):
        records = history[month].get(TARGET_CLS, [])[:TOP_N]
        result[month] = [r["ticker"] for r in records]
    return result


def build_stints(b_monthly: dict[str, list[str]]) -> list[dict]:
    """
    从月度 Top N 重建每个 ticker 的持仓段(stint)。
    每个stint: {ticker, start, end, months, gap_after}
    """
    ticker_months: dict[str, list[str]] = {}
    for month in sorted(b_monthly):
        for tk in b_monthly[month]:
            ticker_months.setdefault(tk, []).append(month)

    stints = []
    for tk, months in ticker_months.items():
        months = sorted(months)
        start = end = months[0]
        for i in range(1, len(months)):
            prev_ts = pd.Timestamp(end + "-01")
            curr_ts = pd.Timestamp(months[i] + "-01")
            delta = (curr_ts.year - prev_ts.year) * 12 + (curr_ts.month - prev_ts.month)
            if delta == 1:
                end = months[i]
            else:
                s_ts = pd.Timestamp(start + "-01")
                e_ts = pd.Timestamp(end + "-01")
                n = (e_ts.year - s_ts.year) * 12 + (e_ts.month - s_ts.month) + 1
                stints.append({"ticker": tk, "start": start, "end": end,
                               "months": n, "gap_after": delta - 1})
                start = end = months[i]
        s_ts = pd.Timestamp(start + "-01")
        e_ts = pd.Timestamp(end + "-01")
        n = (e_ts.year - s_ts.year) * 12 + (e_ts.month - s_ts.month) + 1
        stints.append({"ticker": tk, "start": start, "end": end,
                       "months": n, "gap_after": 0})
    return stints


def _download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """下载收盘价，优先读本地缓存。"""
    import yfinance as yf

    cache_valid = False
    if PRICE_CACHE.exists():
        try:
            with open(PRICE_CACHE, "rb") as f:
                cached = pickle.load(f)
            cached_tickers = set(cached.get("tickers", []))
            if set(tickers).issubset(cached_tickers) and cached.get("start") <= start:
                cache_valid = True
                close = cached["close"]
        except Exception:
            pass

    if not cache_valid:
        data = yf.download(tickers, start=start, end=end, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"]
        else:
            close = data
            if len(tickers) == 1:
                close = close.to_frame(tickers[0]) if isinstance(close, pd.Series) else close
                close.columns = tickers

        try:
            with open(PRICE_CACHE, "wb") as f:
                pickle.dump({"tickers": tickers, "start": start, "close": close}, f)
        except Exception:
            pass

    return close


def enrich_stints_with_returns(stints: list[dict]) -> list[dict]:
    """为每个stint计算收益率指标。"""
    tickers = sorted(set(s["ticker"] for s in stints))
    earliest = min(s["start"] for s in stints)
    latest = max(s["end"] for s in stints)
    start_dl = (pd.Timestamp(earliest + "-01") - pd.DateOffset(months=1)).strftime("%Y-%m-%d")
    end_dl = (pd.Timestamp(latest + "-01") + pd.DateOffset(months=2)).strftime("%Y-%m-%d")

    close = _download_prices(tickers, start_dl, end_dl)

    for s in stints:
        tk = s["ticker"]
        s["return_pct"] = None
        s["monthly_return"] = None
        s["annualized_return"] = None

        if tk not in close.columns:
            continue
        prices = close[tk].dropna()
        entry_date = pd.Timestamp(s["start"] + "-01")
        exit_date = pd.Timestamp(s["end"] + "-01") + pd.offsets.MonthEnd(1)
        seg = prices[(prices.index >= entry_date) & (prices.index <= exit_date)]
        if len(seg) < 2:
            continue

        ret = (float(seg.iloc[-1]) / float(seg.iloc[0]) - 1) * 100
        s["return_pct"] = round(ret, 2)
        s["monthly_return"] = round(ret / max(s["months"], 1), 2)
        s["annualized_return"] = round(ret / max(s["months"], 1) * 12, 1)

    return stints


# ═══════════════════════════════════════════════════════════════════
#  Pytest Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def stints() -> list[dict]:
    """构建并缓存所有B组stint（含收益数据）。"""
    b_monthly = load_b_monthly()
    raw = build_stints(b_monthly)
    enriched = enrich_stints_with_returns(raw)
    return [s for s in enriched if s["return_pct"] is not None]


@pytest.fixture(scope="module", autouse=True)
def print_report(stints):
    """每次测试前打印完整质量报告，供 AI 分析。"""
    by_ticker: dict[str, list[dict]] = {}
    for s in stints:
        by_ticker.setdefault(s["ticker"], []).append(s)

    sep = "=" * 78
    print(f"\n{sep}")
    print("  B组持仓质量诊断报告")
    print(f"  数据来源: {HISTORY_FILE}")
    print(f"  总stint数: {len(stints)}  |  涉及ticker数: {len(by_ticker)}")
    print(sep)

    # Per-ticker detail
    for tk in sorted(by_ticker):
        tk_stints = sorted(by_ticker[tk], key=lambda x: x["start"])
        total_ret = sum(s["return_pct"] for s in tk_stints)
        total_months = sum(s["months"] for s in tk_stints)
        print(f"\n  {tk}  (共{len(tk_stints)}段, 累计{total_months}月, 累计收益{total_ret:+.1f}%)")

        for i, s in enumerate(tk_stints):
            flags = []
            if s["months"] < MIN_STINT_MONTHS:
                flags.append("闪现")
            if s["return_pct"] < 0:
                flags.append("亏损")
            if s["return_pct"] < MAX_SEVERE_LOSS_PCT:
                flags.append("严重亏损")
            if s["months"] <= 3 and s["monthly_return"] < MIN_SHORT_STINT_MONTHLY_RET:
                flags.append("低效")
            if s["months"] > 12 and s["annualized_return"] < MIN_LONG_STINT_ANNUAL_RET:
                flags.append("长期低效")

            flag_str = f"  ← {'|'.join(flags)}" if flags else ""
            gap_str = f"  (后空{s['gap_after']}月)" if s["gap_after"] > 0 else ""
            print(f"    [{i+1}] {s['start']}~{s['end']} ({s['months']:>2}月) "
                  f"收益={s['return_pct']:>+7.1f}%  月均={s['monthly_return']:>+6.2f}%"
                  f"{gap_str}{flag_str}")

    # Summary stats
    flash_count = sum(1 for s in stints if s["months"] < MIN_STINT_MONTHS)
    losing_count = sum(1 for s in stints if s["return_pct"] < 0)
    severe_count = sum(1 for s in stints if s["return_pct"] < MAX_SEVERE_LOSS_PCT)
    win_count = sum(1 for s in stints if s["return_pct"] > 0)
    avg_months = np.mean([s["months"] for s in stints])
    frag_count = sum(1 for tk, ss in by_ticker.items() if len(ss) > MAX_STINTS_PER_TICKER)

    print(f"\n{sep}")
    print("  汇总指标")
    print(sep)
    print(f"  闪现比例(<{MIN_STINT_MONTHS}月):  {flash_count}/{len(stints)} = "
          f"{flash_count/len(stints):.1%}  (目标 ≤{MAX_FLASH_RATIO:.0%})")
    print(f"  碎片化ticker:      {frag_count}/{len(by_ticker)} = "
          f"{frag_count/len(by_ticker):.1%}  (目标 ≤{MAX_FRAGMENTED_RATIO:.0%})")
    print(f"  亏损stint:         {losing_count}/{len(stints)} = "
          f"{losing_count/len(stints):.1%}  (目标 ≤{MAX_LOSING_STINT_RATIO:.0%})")
    print(f"  严重亏损(>{abs(MAX_SEVERE_LOSS_PCT)}%): {severe_count}  (目标 ={MAX_SEVERE_LOSS_COUNT})")
    print(f"  整体胜率:          {win_count}/{len(stints)} = "
          f"{win_count/len(stints):.1%}  (目标 ≥{MIN_WIN_RATE:.0%})")
    print(f"  平均持仓月数:      {avg_months:.1f}  (目标 ≥{MIN_AVG_HOLDING_MONTHS})")

    # Turnover stats
    b_mo = load_b_monthly()
    mo_keys = sorted(b_mo.keys())
    if len(mo_keys) >= 2:
        t_counts = []
        for i in range(1, len(mo_keys)):
            t_counts.append(len(set(b_mo[mo_keys[i]]) - set(b_mo[mo_keys[i-1]])))
        avg_to = np.mean(t_counts)
        print(f"  月均换手(Top3):    {avg_to:.2f} 个位子/月  (目标 ≤{MAX_AVG_MONTHLY_TURNOVER})")

    print(sep + "\n")


# ═══════════════════════════════════════════════════════════════════
#  Tests — 每个 test 对应一个质量维度
# ═══════════════════════════════════════════════════════════════════

class TestFlashControl:
    """闪现控制：减少1-2个月即进即出的无效持仓。"""

    def test_flash_ratio(self, stints):
        """闪现stint占总stint比例不超过上限。"""
        flash = [s for s in stints if s["months"] < MIN_STINT_MONTHS]
        ratio = len(flash) / len(stints)
        assert ratio <= MAX_FLASH_RATIO, (
            f"闪现stint占比 {ratio:.1%} 超过上限 {MAX_FLASH_RATIO:.0%}。\n"
            f"共 {len(flash)} 个闪现stint:\n" +
            "\n".join(f"  {s['ticker']} {s['start']}~{s['end']} "
                      f"({s['months']}月, {s['return_pct']:+.1f}%)" for s in flash) +
            "\n\n修复方向: "
            "在 screener_engine.py 加大 B 组 MA200 滞后带，"
            "或在 compute_scorecard_b 中引入趋势延续性因子(如连续N月MA20>MA60)。"
        )

    def test_avg_holding_months(self, stints):
        """平均持仓月数不低于下限，防止整体持仓过短。"""
        avg = np.mean([s["months"] for s in stints])
        assert avg >= MIN_AVG_HOLDING_MONTHS, (
            f"平均持仓 {avg:.1f} 月低于下限 {MIN_AVG_HOLDING_MONTHS} 月。\n"
            f"修复方向: 加大滞后带宽度，提高评分中长期因子权重。"
        )


class TestFragmentationControl:
    """碎片化控制：同一ticker不应反复进出Top3。"""

    def test_fragmentation_ratio(self, stints):
        """超过最大stint数的ticker占比不超过上限。"""
        by_tk = {}
        for s in stints:
            by_tk.setdefault(s["ticker"], []).append(s)
        fragmented = {tk: ss for tk, ss in by_tk.items()
                      if len(ss) > MAX_STINTS_PER_TICKER}
        ratio = len(fragmented) / len(by_tk) if by_tk else 0

        detail = "\n".join(
            f"  {tk}: {len(ss)}段 — " +
            ", ".join(f"{s['start']}~{s['end']}({s['months']}月)" for s in sorted(ss, key=lambda x: x['start']))
            for tk, ss in fragmented.items()
        )
        assert ratio <= MAX_FRAGMENTED_RATIO, (
            f"碎片化ticker占比 {ratio:.1%} 超过上限 {MAX_FRAGMENTED_RATIO:.0%}。\n"
            f"共 {len(fragmented)} 个:\n{detail}\n\n"
            f"修复方向: 加大 B 组 hysteresis 退出阈值(如 MA200 退出从 0.95 放宽到 0.90)，"
            f"减少边界震荡。"
        )


class TestLossControl:
    """亏损控制：B组蓝筹不应频繁亏损。"""

    def test_losing_stint_ratio(self, stints):
        """亏损stint占比不超过上限。"""
        losing = [s for s in stints if s["return_pct"] < 0]
        ratio = len(losing) / len(stints) if stints else 0
        assert ratio <= MAX_LOSING_STINT_RATIO, (
            f"亏损stint占比 {ratio:.1%} 超过上限 {MAX_LOSING_STINT_RATIO:.0%}。\n"
            f"共 {len(losing)} 个:\n" +
            "\n".join(f"  {s['ticker']} {s['start']}~{s['end']} "
                      f"({s['months']}月, {s['return_pct']:+.1f}%)" for s in losing) +
            "\n\n修复方向: 在 compute_scorecard_b 加大 Resilience(抗跌韧性) 权重，"
            "或在入选门槛加入 20日动量>0 的硬条件。"
        )

    def test_no_severe_loss(self, stints):
        """不应存在严重亏损stint(单stint亏损超过阈值)。"""
        severe = [s for s in stints if s["return_pct"] < MAX_SEVERE_LOSS_PCT]
        assert len(severe) <= MAX_SEVERE_LOSS_COUNT, (
            f"存在 {len(severe)} 个严重亏损stint(>{abs(MAX_SEVERE_LOSS_PCT)}%):\n" +
            "\n".join(f"  {s['ticker']} {s['start']}~{s['end']} "
                      f"({s['months']}月, {s['return_pct']:+.1f}%)" for s in severe) +
            "\n\n修复方向: 在 screener_engine.py B 组入选条件中加入短期动量门槛，"
            "或在评分函数中惩罚近期大幅下跌的标的。"
        )

    def test_win_rate(self, stints):
        """整体胜率(stint收益>0的比例)不低于下限。"""
        winners = [s for s in stints if s["return_pct"] > 0]
        rate = len(winners) / len(stints) if stints else 0
        assert rate >= MIN_WIN_RATE, (
            f"胜率 {rate:.1%} 低于下限 {MIN_WIN_RATE:.0%}。"
        )


class TestEfficiencyControl:
    """效率控制：持仓期间的收益不应太低。"""

    def test_short_stint_efficiency(self, stints):
        """短stint(<=3月)中低效占比不超过上限。"""
        short = [s for s in stints
                 if s["months"] <= 3 and s["monthly_return"] is not None]
        if not short:
            pytest.skip("无短stint数据")
        inefficient = [s for s in short
                       if s["monthly_return"] < MIN_SHORT_STINT_MONTHLY_RET]
        ratio = len(inefficient) / len(short)
        assert ratio <= MAX_SHORT_INEFFICIENT_RATIO, (
            f"短stint低效比 {ratio:.1%} 超过上限 {MAX_SHORT_INEFFICIENT_RATIO:.0%}。\n"
            f"共 {len(inefficient)} 个:\n" +
            "\n".join(f"  {s['ticker']} {s['start']}~{s['end']} "
                      f"({s['months']}月, 月均{s['monthly_return']:+.2f}%)" for s in inefficient) +
            "\n\n修复方向: 短stint本身就是问题(见闪现控制)，减少闪现=减少短stint低效。"
            "也可在评分中加大夏普比率权重。"
        )

    def test_long_stint_efficiency(self, stints):
        """长stint(>12月)中低效占比不超过上限。"""
        long = [s for s in stints
                if s["months"] > 12 and s["annualized_return"] is not None]
        if not long:
            pytest.skip("无长stint数据")
        inefficient = [s for s in long
                       if s["annualized_return"] < MIN_LONG_STINT_ANNUAL_RET]
        ratio = len(inefficient) / len(long)
        assert ratio <= MAX_LONG_INEFFICIENT_RATIO, (
            f"长stint低效比 {ratio:.1%} 超过上限 {MAX_LONG_INEFFICIENT_RATIO:.0%}。\n" +
            "\n".join(f"  {s['ticker']} {s['start']}~{s['end']} "
                      f"({s['months']}月, 年化{s['annualized_return']:+.1f}%)" for s in inefficient) +
            "\n\n修复方向: 在 compute_scorecard_b 加大 Sharpe1Y 权重，"
            "引入资金效率惩罚(如持仓超12月但年化<SPY的标的降分)。"
        )


class TestTurnoverControl:
    """换手率控制：Top 3 名单不应频繁更换。"""

    def test_monthly_top3_turnover(self):
        """月均换手率（每月新进入 Top3 的 ticker 数）不超过上限。"""
        b_monthly = load_b_monthly()
        months = sorted(b_monthly.keys())
        if len(months) < 2:
            pytest.skip("不足 2 个月数据")

        turnover_counts = []
        for i in range(1, len(months)):
            prev_set = set(b_monthly[months[i - 1]])
            curr_set = set(b_monthly[months[i]])
            new_entries = len(curr_set - prev_set)
            turnover_counts.append(new_entries)

        avg_turnover = np.mean(turnover_counts)
        high_turnover_months = [(months[i], turnover_counts[i - 1])
                                for i in range(1, len(months))
                                if turnover_counts[i - 1] >= 2]

        assert avg_turnover <= MAX_AVG_MONTHLY_TURNOVER, (
            f"月均换手 {avg_turnover:.2f} 个位子超过上限 {MAX_AVG_MONTHLY_TURNOVER}。\n"
            f"共 {len(months)-1} 个月对，高换手(≥2)月份 {len(high_turnover_months)} 个:\n" +
            "\n".join(f"  {m}: 换入{n}个新ticker" for m, n in high_turnover_months[:15]) +
            "\n\n修复方向(信念守擂制参数): "
            "加大 challenge_margin(守擂优势) 让在位者更难被替换；"
            "降低 decay_rate 让信念衰减更慢；"
            "提高 entry_threshold 让新标的更难入选。"
        )


class TestComposite:
    """复合指标：从整体角度审视B组质量。"""

    def test_total_return_positive(self, stints):
        """所有stint的总收益应为正。"""
        total = sum(s["return_pct"] for s in stints)
        total_months = sum(s["months"] for s in stints)
        assert total > 0, (
            f"B组stint累计收益 {total:+.1f}%，{total_months}个月加总竟然亏钱。"
        )

    def test_median_stint_quality(self, stints):
        """中位stint的月均收益应为正且合理。"""
        monthly_rets = [s["monthly_return"] for s in stints if s["monthly_return"] is not None]
        median_mr = np.median(monthly_rets)
        assert median_mr > 0.0, (
            f"中位stint月均收益 {median_mr:+.2f}%，连中位数都不赚钱。"
        )

    def test_best_vs_worst_balance(self, stints):
        """最佳stint的收益应显著覆盖最差stint的亏损。"""
        returns = sorted(s["return_pct"] for s in stints)
        worst_5 = sum(returns[:5])
        best_5 = sum(returns[-5:])
        assert best_5 > abs(worst_5) * 2, (
            f"Top5 stint累计收益 {best_5:+.1f}% vs Bottom5 {worst_5:+.1f}%，"
            f"好的不够覆盖差的(需要2x覆盖)。"
        )


class TestConvictionIntegrity:
    """信念守擂制完整性检查：验证 conviction 数据已正确写入历史。"""

    def test_conviction_state_exists(self):
        """arena_history.json 中应包含 B 组信念状态。"""
        with open(HISTORY_FILE) as f:
            history = json.load(f)
        conv_state = history.get("_conviction_B", {})
        holders    = history.get("_holders_B", [])
        assert len(conv_state) > 0, (
            "arena_history.json 中未找到 _conviction_B 数据。\n"
            "请先用回填按钮重新生成历史数据（回填会自动使用信念守擂制）。"
        )
        assert len(holders) > 0, (
            "arena_history.json 中未找到 _holders_B 数据。"
        )

    def test_recent_records_have_conviction(self):
        """最近 6 个月的 B 组记录应包含 conviction 字段。"""
        with open(HISTORY_FILE) as f:
            history = json.load(f)
        sorted_months = sorted(k for k in history if not k.startswith("_"))
        recent = sorted_months[-6:] if len(sorted_months) >= 6 else sorted_months
        missing = []
        for mo in recent:
            recs = history[mo].get(TARGET_CLS, [])
            for r in recs:
                if "conviction" not in r:
                    missing.append(f"{mo}: {r.get('ticker', '?')}")
        assert len(missing) == 0, (
            f"以下记录缺少 conviction 字段（需回填）:\n" +
            "\n".join(f"  {m}" for m in missing[:20]) +
            "\n\n修复方向: 重新执行回填操作。"
        )

    def test_conviction_values_reasonable(self):
        """信念值应在合理范围内 [0, 100]。"""
        with open(HISTORY_FILE) as f:
            history = json.load(f)
        conv_state = history.get("_conviction_B", {})
        if not conv_state:
            pytest.skip("无信念状态数据")
        out_of_range = [
            (tk, v) for tk, v in conv_state.items()
            if v < 0 or v > 100
        ]
        assert len(out_of_range) == 0, (
            f"发现 {len(out_of_range)} 个信念值超出 [0, 100]:\n" +
            "\n".join(f"  {tk}: {v}" for tk, v in out_of_range)
        )

    def test_holders_match_latest_month(self):
        """_holders_B 应与最近一个月的 B 组 Top 3 一致。"""
        with open(HISTORY_FILE) as f:
            history = json.load(f)
        holders = set(history.get("_holders_B", []))
        if not holders:
            pytest.skip("无 holders 数据")
        sorted_months = sorted(k for k in history if not k.startswith("_"))
        if not sorted_months:
            pytest.skip("无月度数据")
        latest = sorted_months[-1]
        latest_tickers = {r["ticker"] for r in history[latest].get(TARGET_CLS, [])}
        assert holders == latest_tickers, (
            f"_holders_B {holders} 与最新月 {latest} 的 Top 3 {latest_tickers} 不一致。"
        )
