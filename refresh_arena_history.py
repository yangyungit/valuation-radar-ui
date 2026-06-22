#!/usr/bin/env python3
"""从 Render 拉取最新 arena_history + conviction_state，覆盖本地离线兜底快照。

真相源是 Render universe.db；本地 data/arena_history.json 仅在离线 / Render 返回空时兜底。
默认 harness 与页面都走 Render API，本脚本只是给离线场景手动刷新本地快照用。

用法：
    python refresh_arena_history.py
    RADAR_API_URL=http://localhost:8000 python refresh_arena_history.py  # 指向本地后端
"""

import sys

from arena_history_source import resolve_api_base, write_local


def main() -> int:
    base = resolve_api_base()
    print(f"源: {base}")
    try:
        n, path = write_local()
    except Exception as e:
        print(f"刷新失败: {e}", file=sys.stderr)
        return 1
    print(f"已写入 {path}（{n} 个月）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
