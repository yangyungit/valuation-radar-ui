"""arena_history 读取源（真相源 = Render universe.db，本地 JSON 仅离线兜底）。

为什么存在：harness / 脚本以前直接 open 本地 data/arena_history.json，那是个会过期的
快照，导致用旧小池数据验今天的逻辑（瞎测）。本模块统一从 Render API 取数，连不上才
降级本地文件，并把后端的新版 dict schema 桥接回 harness 期望的旧版 list schema。

不依赖 streamlit / requests，纯标准库，供 pytest 与命令行脚本直接 import。
"""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache

LOCAL_API_URL = "http://localhost:8000"
DEFAULT_REMOTE_API_URL = "https://valuation-radar-server.onrender.com"

_HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_HISTORY_PATH = os.path.join(_HERE, "data", "arena_history.json")
_CLASSES = ("A", "B", "C", "D", "Z")


def resolve_api_base() -> str:
    """与 api_client.py 同一套优先级：RADAR_API_URL > USE_LOCAL_API > 默认生产地址。"""
    env = os.environ.get("RADAR_API_URL", "").strip()
    if env:
        return env
    if os.environ.get("USE_LOCAL_API") == "true":
        return LOCAL_API_URL
    return DEFAULT_REMOTE_API_URL


def _get_json(url: str, timeout: int = 30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _records(rec) -> list:
    """把单赛道记录归一化为 ticker 列表（兼容 None / 旧 list / 新 dict schema）。"""
    if rec is None:
        return []
    if isinstance(rec, list):
        return rec
    if isinstance(rec, dict):
        t = rec.get("tickers", [])
        return t if isinstance(t, list) else []
    return []


def fetch_from_render(timeout: int = 30) -> dict | None:
    """从 Render 重建 harness 期望的旧版 schema。

    结构：{"YYYY-MM": {"A": [rec...], "B": [...], ...},
           "_conviction_X": {ticker: float}, "_holders_X": [...]}
    arena/history 拉取失败或为空时返回 None（让调用方降级本地）。
    """
    base = resolve_api_base()
    raw = _get_json(f"{base}/api/v1/arena/history", timeout)
    if not isinstance(raw, dict):
        return None
    history = raw.get("history", raw)
    if not isinstance(history, dict):
        return None

    out: dict = {}
    for month, clsmap in history.items():
        if month.startswith("_") or not isinstance(clsmap, dict):
            continue
        out[month] = {cls: _records(rec) for cls, rec in clsmap.items()}
    if not out:
        return None

    # 信念状态在独立端点（arena/history 不含 _conviction_X / _holders_X）
    for cls in _CLASSES:
        cs = _get_json(f"{base}/api/v1/conviction_state/{cls}", timeout)
        if isinstance(cs, dict):
            out[f"_conviction_{cls}"] = cs.get("state", {}) or {}
            out[f"_holders_{cls}"] = cs.get("holders", []) or []
    return out


@lru_cache(maxsize=8)
def _cached(local_path: str, prefer_remote: bool) -> str:
    # 缓存 json 字符串（不可变），调用方每次拿到独立 dict，避免跨用例共享可变状态
    data = fetch_from_render() if prefer_remote else None
    if data is None:
        with open(local_path, encoding="utf-8") as f:
            return f.read()
    return json.dumps(data)


def load_arena_history(local_path=LOCAL_HISTORY_PATH,
                       prefer_remote: bool | None = None) -> dict:
    """优先 Render（真相源），连不上才降级本地 JSON。

    prefer_remote=None 时看环境变量 ARENA_HISTORY_SOURCE：'local' → 只读本地，
    其余 → 优先 Render。
    """
    if prefer_remote is None:
        prefer_remote = os.environ.get("ARENA_HISTORY_SOURCE", "remote").lower() != "local"
    return json.loads(_cached(str(local_path), prefer_remote))


def describe_source() -> str:
    """供报告/日志显示当前实际取数源，避免再被'读了本地却以为读后端'误导。"""
    if os.environ.get("ARENA_HISTORY_SOURCE", "remote").lower() == "local":
        return f"本地文件 {LOCAL_HISTORY_PATH}"
    return f"Render {resolve_api_base()}（不可达时降级本地兜底）"


def write_local(local_path=LOCAL_HISTORY_PATH) -> tuple[int, str]:
    """拉 Render 覆盖本地快照。Render 不可达时抛异常，不破坏现有本地文件。"""
    data = fetch_from_render()
    if not data:
        raise RuntimeError(
            f"Render ({resolve_api_base()}) 拉取 arena_history 失败或为空，未覆盖本地。"
        )
    local_path = str(local_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    months = [k for k in data if not k.startswith("_")]
    return len(months), local_path
