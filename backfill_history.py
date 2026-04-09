#!/usr/bin/env python3
"""
NLP 叙事快照 · 历史批量回填脚本
===================================
用途：按日遍历过去 N 个月，依次触发远端 API 跑 NLP 流水线并等待完成。
      适合挂在后台睡觉跑：nohup python backfill_history.py > backfill.log 2>&1 &

用法示例：
  python backfill_history.py                 # 默认回填过去 180 天
  python backfill_history.py --days 90       # 回填过去 90 天
  python backfill_history.py --start 2025-10-01 --end 2026-04-08  # 指定日期段
  python backfill_history.py --dry-run       # 仅打印待处理日期，不实际发请求
"""

import argparse
import sys
import time
import requests
from datetime import date, timedelta

# ─── 配置 ──────────────────────────────────────────────────────────────────
API_BASE_URL = "https://valuation-radar.onrender.com"

# 每次 poll 状态的间隔（秒），流水线通常 1-3 分钟
POLL_INTERVAL = 15

# 单个日期最长等待时间（秒），超过后跳过并记为 TIMEOUT
MAX_WAIT_PER_DATE = 10 * 60   # 10 分钟

# 两个日期之间的冷却（秒），给服务器喘息
COOLDOWN = 5
# ───────────────────────────────────────────────────────────────────────────


def trigger(target_date: str) -> dict:
    try:
        r = requests.post(
            f"{API_BASE_URL}/api/v1/narrative/run_pipeline",
            json={"target_date": target_date},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_status() -> dict:
    try:
        r = requests.get(f"{API_BASE_URL}/api/v1/narrative/status", timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"degraded": True, "error": str(e)}


def wait_until_done(target_date: str) -> str:
    """等待流水线跑完，返回 'ok' / 'timeout' / 'error'。"""
    deadline = time.time() + MAX_WAIT_PER_DATE
    while time.time() < deadline:
        st = get_status()
        if st.get("degraded"):
            print(f"    ⚠️  后端不可达: {st.get('error', '')[:80]}，等待 {POLL_INTERVAL}s 重试…")
            time.sleep(POLL_INTERVAL)
            continue

        running = st.get("running", False)
        last_run = st.get("last_run", "")
        last_summary = st.get("last_summary") or {}
        news_count = last_summary.get("news_count", -1)

        if not running:
            # 流水线已停止——检查 last_run 是否就是今天这个日期的结果
            # 简单策略：只要 running=False 就视为完成（后端串行队列）
            status_emoji = "✅" if news_count >= 0 else "⚠️"
            count_str = f"语料 {news_count} 篇" if news_count >= 0 else "语料未知"
            print(f"    {status_emoji} 完成 | {count_str} | last_run={last_run[:19]}")
            return "ok"

        remaining = int(deadline - time.time())
        print(f"    ⏳ 运行中… 剩余等待上限 {remaining}s，{POLL_INTERVAL}s 后再查…")
        time.sleep(POLL_INTERVAL)

    print(f"    ⏰ 超时（{MAX_WAIT_PER_DATE}s），跳过该日期继续下一天。")
    return "timeout"


def build_date_range(start: date, end: date) -> list[date]:
    """生成 [start, end] 的所有工作日（简单过滤掉周六周日）。"""
    days = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:   # 0=周一 … 4=周五
            days.append(cur)
        cur += timedelta(days=1)
    return days


def main():
    parser = argparse.ArgumentParser(description="NLP 历史批量回填")
    parser.add_argument("--days", type=int, default=180, help="往前回填天数（默认 180）")
    parser.add_argument("--start", type=str, help="起始日期 YYYY-MM-DD（优先于 --days）")
    parser.add_argument("--end", type=str, help="结束日期 YYYY-MM-DD（默认昨天）")
    parser.add_argument("--dry-run", action="store_true", help="只打印日期，不发请求")
    args = parser.parse_args()

    today = date.today()
    end_date = date.fromisoformat(args.end) if args.end else today - timedelta(days=1)
    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        start_date = end_date - timedelta(days=args.days)

    if start_date > end_date:
        print("❌ start 不能晚于 end，请检查参数。")
        sys.exit(1)

    date_list = build_date_range(start_date, end_date)
    total = len(date_list)

    print(f"\n{'='*60}")
    print(f"  NLP 历史批量回填")
    print(f"  目标区间: {start_date} → {end_date}  共 {total} 个工作日")
    print(f"  后端 API: {API_BASE_URL}")
    print(f"  每日超时: {MAX_WAIT_PER_DATE//60} 分钟  |  冷却: {COOLDOWN}s")
    if args.dry_run:
        print("  模式: DRY-RUN（只打印，不发请求）")
    print(f"{'='*60}\n")

    if args.dry_run:
        for d in date_list:
            print(f"  [{d}]")
        print(f"\n共 {total} 个日期，dry-run 结束。")
        return

    results = {"ok": 0, "timeout": 0, "trigger_fail": 0, "skipped": 0}

    for idx, d in enumerate(date_list, 1):
        d_str = d.isoformat()
        print(f"\n[{idx}/{total}] 处理日期: {d_str}")

        # 先确认当前没有任务在跑（如有，等它结束）
        st = get_status()
        if st.get("running"):
            print(f"  检测到流水线正在运行（可能是上个任务残留），先等待完成…")
            wait_until_done(d_str)

        # 触发
        resp = trigger(d_str)
        started = resp.get("status") == "started"
        if not started:
            err = resp.get("error") or resp.get("message") or str(resp)
            # 有些后端对已有快照的日期会直接返回 skipped/exists
            if "exist" in str(resp).lower() or "skip" in str(resp).lower() or "already" in str(resp).lower():
                print(f"  ⏭️  已有快照，跳过。({err[:60]})")
                results["skipped"] += 1
            else:
                print(f"  ❌ 触发失败: {err[:120]}")
                results["trigger_fail"] += 1
            time.sleep(COOLDOWN)
            continue

        print(f"  🚀 已触发，等待完成…")
        outcome = wait_until_done(d_str)
        results[outcome] += 1
        time.sleep(COOLDOWN)

    print(f"\n{'='*60}")
    print(f"  批量回填完成！汇总:")
    print(f"    ✅ 成功     : {results['ok']}")
    print(f"    ⏭️  已有跳过  : {results['skipped']}")
    print(f"    ⏰ 超时     : {results['timeout']}")
    print(f"    ❌ 触发失败  : {results['trigger_fail']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
