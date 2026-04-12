"""
Moltbot 质检员 (Quality Inspector)
===================================
集中检测前端/后端所有已知故障模式，结果汇总到首页仪表盘。

检查类别:
  1. 后端连通  – API 可达性、响应延迟
  2. API 契约  – 端点状态码 & 返回格式
  3. 数据完整  – 本地数据文件 + 核心数据结构
  4. 行情数据  – yfinance 可用性 & 数据新鲜度
  5. 依赖环境  – Python 版本、必需包安装
  6. 舆情引擎  – 叙事引擎状态、爬虫、词典、积压
  7. 页面完整  – 页面文件存在性 + 语法校验
  8. 代码冲突  – Git merge conflict markers 扫描
"""

import os
import json
import time
import platform
import importlib
import sys
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
CRITICAL = "critical"
ERROR = "error"
WARNING = "warning"
INFO = "info"
OK = "ok"

SEVERITY_ORDER = {CRITICAL: 0, ERROR: 1, WARNING: 2, INFO: 3, OK: 4}
SEVERITY_ICON = {
    CRITICAL: "🔴", ERROR: "🟠", WARNING: "🟡", INFO: "🔵", OK: "🟢",
}
SEVERITY_LABEL = {
    CRITICAL: "严重", ERROR: "错误", WARNING: "警告", INFO: "提示", OK: "通过",
}

PROJECT_ROOT = Path(__file__).parent


def _make(category, name, severity, message, detail="", elapsed_ms=0.0):
    """Build a serializable check-result dict (no dataclass for cache compat)."""
    return {
        "category": category,
        "name": name,
        "severity": severity,
        "message": message,
        "detail": detail,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _api_base():
    if platform.system() == "Darwin" or os.environ.get("USE_LOCAL_API") == "true":
        return "http://localhost:8000"
    return "https://valuation-radar.onrender.com"


# ===================================================================
# 1. 后端连通性
# ===================================================================
def check_backend_connectivity():
    results = []
    base = _api_base()

    t0 = time.time()
    try:
        r = requests.get(f"{base}/api/v1/stock_pool_data", timeout=8)
        ms = (time.time() - t0) * 1000
        if r.status_code == 200:
            body = r.json()
            if body and isinstance(body, dict):
                results.append(_make("后端连通", "核心数据 API",
                                     OK, f"连接正常 ({ms:.0f}ms)",
                                     f"URL: {base}", ms))
                if ms > 3000:
                    results.append(_make("后端连通", "响应延迟",
                                         WARNING,
                                         f"核心 API 响应缓慢 ({ms:.0f}ms > 3000ms)",
                                         "考虑检查后端性能或网络状况", ms))
            else:
                results.append(_make("后端连通", "核心数据 API",
                                     ERROR, "API 返回数据格式异常",
                                     f"类型: {type(body).__name__}", ms))
        else:
            results.append(_make("后端连通", "核心数据 API",
                                 CRITICAL, f"HTTP {r.status_code}",
                                 f"URL: {base}", ms))
    except requests.exceptions.ConnectionError:
        ms = (time.time() - t0) * 1000
        results.append(_make("后端连通", "核心数据 API",
                             CRITICAL, "后端服务未启动或无法连接",
                             f"无法连接 {base}，请启动 api_server.py", ms))
    except requests.exceptions.Timeout:
        ms = (time.time() - t0) * 1000
        results.append(_make("后端连通", "核心数据 API",
                             ERROR, "核心 API 响应超时 (>8s)",
                             f"URL: {base}", ms))
    except Exception as e:
        ms = (time.time() - t0) * 1000
        results.append(_make("后端连通", "核心数据 API",
                             ERROR, f"未知连接错误: {type(e).__name__}",
                             str(e), ms))
    return results


# ===================================================================
# 2. API 契约一致性
# ===================================================================
def check_api_contract():
    results = []
    base = _api_base()

    endpoints = [
        ("/api/v1/stock_pool_data", "核心数据"),
        ("/api/v1/narrative/status", "舆情状态"),
        ("/api/v1/narrative/taxonomy", "分类体系"),
        ("/api/v1/narrative/dictionary_stats", "词典统计"),
        ("/api/v1/narrative/crawler_status", "爬虫状态"),
        ("/api/v1/arena/watchlist", "CIO 观察池"),
    ]

    for path, desc in endpoints:
        t0 = time.time()
        try:
            r = requests.get(f"{base}{path}", timeout=5)
            ms = (time.time() - t0) * 1000
            if r.status_code == 200:
                try:
                    r.json()
                    results.append(_make("API契约", desc, OK,
                                         f"{path} → 200 OK ({ms:.0f}ms)", "", ms))
                except ValueError:
                    results.append(_make("API契约", desc, ERROR,
                                         f"{path} 返回非 JSON",
                                         f"Content-Type: {r.headers.get('content-type', '?')}", ms))
            elif r.status_code == 404:
                results.append(_make("API契约", desc, ERROR,
                                     f"{path} → 404 (端点不存在)",
                                     "后端版本可能不匹配", ms))
            elif r.status_code == 500:
                results.append(_make("API契约", desc, ERROR,
                                     f"{path} → 500 (服务端内部错误)",
                                     "检查后端日志", ms))
            else:
                results.append(_make("API契约", desc, WARNING,
                                     f"{path} → HTTP {r.status_code}", "", ms))
        except requests.exceptions.ConnectionError:
            results.append(_make("API契约", desc, CRITICAL,
                                 f"{path} 连接失败", "后端未启动"))
            break
        except requests.exceptions.Timeout:
            ms = (time.time() - t0) * 1000
            results.append(_make("API契约", desc, WARNING,
                                 f"{path} 超时 (>5s)", "", ms))
        except Exception as e:
            results.append(_make("API契约", desc, WARNING,
                                 f"{path} 异常", str(e)))
    return results


# ===================================================================
# 3. 数据完整性
# ===================================================================
def check_data_integrity():
    results = []
    data_dir = PROJECT_ROOT / "data"

    required_files = {
        "arena_history.json": ("竞技场历史", 24 * 14),
        "horsemen_monthly_verdict.json": ("宏观月度裁决", 24 * 45),
        "prev_classification.json": ("上期 ABCD 分类", 24 * 14),
    }

    for fname, (desc, stale_hours) in required_files.items():
        fpath = data_dir / fname
        if not fpath.exists():
            results.append(_make("数据完整", fname, ERROR,
                                 f"{desc}文件缺失", f"路径: {fpath}"))
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                results.append(_make("数据完整", fname, WARNING,
                                     f"{desc}文件内容为空", ""))
                continue
        except json.JSONDecodeError as e:
            results.append(_make("数据完整", fname, ERROR,
                                 f"{desc} JSON 格式损坏", str(e)))
            continue
        except Exception as e:
            results.append(_make("数据完整", fname, ERROR,
                                 f"{desc}读取失败", str(e)))
            continue

        mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
        age_h = (datetime.now() - mtime).total_seconds() / 3600
        if age_h > stale_hours:
            results.append(_make("数据完整", fname, WARNING,
                                 f"{desc}数据可能过期 ({age_h:.0f}h 前更新)",
                                 f"阈值 {stale_hours}h · 更新于 {mtime:%Y-%m-%d %H:%M}"))
        else:
            results.append(_make("数据完整", fname, OK,
                                 f"{desc} · 更新于 {mtime:%m-%d %H:%M}", ""))

    # Core data structure validation (reuse connectivity result if available)
    base = _api_base()
    try:
        r = requests.get(f"{base}/api/v1/stock_pool_data", timeout=5)
        if r.status_code == 200:
            core = r.json()
            expected_keys = ["TIC_MAP", "USER_GROUPS_DEF"]
            missing_keys = [k for k in expected_keys if k not in core]
            if missing_keys:
                results.append(_make("数据完整", "核心数据字段", ERROR,
                                     f"缺少关键字段: {', '.join(missing_keys)}",
                                     f"实际字段: {list(core.keys())[:10]}"))
            empty_keys = [k for k in expected_keys if k in core and not core[k]]
            if empty_keys:
                results.append(_make("数据完整", "核心数据字段", WARNING,
                                     f"以下字段为空: {', '.join(empty_keys)}", ""))
            tic_map = core.get("TIC_MAP", {})
            if tic_map:
                cnt = len(tic_map)
                if cnt < 10:
                    results.append(_make("数据完整", "资产池规模", WARNING,
                                         f"监控资产仅 {cnt} 只，低于预期", ""))
                else:
                    results.append(_make("数据完整", "资产池规模", OK,
                                         f"{cnt} 只资产在监控", ""))
    except Exception:
        pass
    return results


# ===================================================================
# 4. 行情数据源
# ===================================================================
def check_market_data():
    results = []
    try:
        import yfinance as yf
    except ImportError:
        results.append(_make("行情数据", "yfinance", CRITICAL,
                             "yfinance 未安装", "pip install yfinance"))
        return results

    t0 = time.time()
    try:
        spy = yf.Ticker("SPY").history(period="5d")
        ms = (time.time() - t0) * 1000
        if spy.empty:
            results.append(_make("行情数据", "yfinance (SPY)", ERROR,
                                 "yfinance 返回空数据", "SPY 5日历史为空", ms))
        else:
            latest = spy.index[-1]
            days_old = (datetime.now() - latest.to_pydatetime().replace(tzinfo=None)).days
            if days_old > 4:
                results.append(_make("行情数据", "yfinance (SPY)", WARNING,
                                     f"行情数据滞后 ({days_old} 天)",
                                     f"最新日期: {latest:%Y-%m-%d}", ms))
            else:
                results.append(_make("行情数据", "yfinance (SPY)", OK,
                                     f"正常 ({ms:.0f}ms · 最新 {latest:%m-%d})",
                                     "", ms))
    except Exception as e:
        ms = (time.time() - t0) * 1000
        results.append(_make("行情数据", "yfinance (SPY)", ERROR,
                             f"请求失败: {type(e).__name__}", str(e), ms))
    return results


# ===================================================================
# 5. 依赖与环境
# ===================================================================
def check_dependencies():
    results = []

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 11):
        results.append(_make("依赖环境", "Python 版本", WARNING,
                             f"Python {py_ver}，建议 ≥3.11", ""))
    else:
        results.append(_make("依赖环境", "Python 版本", OK,
                             f"Python {py_ver}", ""))

    required_packages = {
        "streamlit": "streamlit",
        "yfinance": "yfinance",
        "pandas": "pandas",
        "plotly": "plotly",
        "requests": "requests",
        "numpy": "numpy",
        "pandas_datareader": "pandas_datareader",
        "deep_translator": "deep-translator",
        "matplotlib": "matplotlib",
    }

    missing = []
    installed = []
    broken = []
    for mod_name, pip_name in required_packages.items():
        try:
            mod = importlib.import_module(mod_name)
            ver = getattr(mod, "__version__", "?")
            installed.append(f"{pip_name}=={ver}")
        except ImportError:
            missing.append(pip_name)
        except Exception as e:
            broken.append((pip_name, f"{type(e).__name__}: {e}"))
            installed.append(pip_name)

    if missing:
        results.append(_make("依赖环境", "缺失依赖包", ERROR,
                             f"{len(missing)} 个包未安装: {', '.join(missing)}",
                             f"pip install {' '.join(missing)}"))
    else:
        results.append(_make("依赖环境", "依赖包完整性", OK,
                             f"全部 {len(installed)} 个必需包已安装", ""))

    if broken:
        for pkg, err_msg in broken:
            results.append(_make("依赖环境", f"{pkg} 导入异常", WARNING,
                                 f"{pkg} 已安装但导入时出错",
                                 err_msg))

    # Streamlit version detail
    try:
        import streamlit as _st
        sv = _st.__version__
        results.append(_make("依赖环境", "Streamlit 版本", INFO,
                             f"Streamlit {sv}", ""))
    except Exception:
        pass

    # yfinance version detail
    try:
        import yfinance as _yf
        results.append(_make("依赖环境", "yfinance 版本", INFO,
                             f"yfinance {_yf.__version__}", ""))
    except Exception:
        pass

    return results


# ===================================================================
# 6. 舆情引擎健康度
# ===================================================================
def check_narrative_engine():
    results = []
    base = _api_base()

    # Quick reachability
    try:
        r = requests.get(f"{base}/api/v1/narrative/status", timeout=5)
        if r.status_code != 200:
            results.append(_make("舆情引擎", "引擎状态", ERROR,
                                 f"状态接口 HTTP {r.status_code}", ""))
            return results
        data = r.json()
        if data.get("degraded"):
            results.append(_make("舆情引擎", "引擎状态", WARNING,
                                 "舆情引擎处于降级模式", data.get("error", "")))
        else:
            results.append(_make("舆情引擎", "引擎状态", OK,
                                 "运行正常", ""))
    except Exception as e:
        results.append(_make("舆情引擎", "引擎状态", WARNING,
                             "舆情引擎不可达", str(e)))
        return results

    # Crawler
    try:
        r = requests.get(f"{base}/api/v1/narrative/crawler_status", timeout=5)
        if r.status_code == 200:
            d = r.json()
            if d.get("degraded"):
                results.append(_make("舆情引擎", "爬虫状态", WARNING,
                                     "爬虫数据降级", d.get("error", "")))
            else:
                results.append(_make("舆情引擎", "爬虫状态", OK,
                                     "爬虫正常", ""))
    except Exception:
        results.append(_make("舆情引擎", "爬虫状态", INFO,
                             "爬虫状态获取失败", ""))

    # Dictionary
    try:
        r = requests.get(f"{base}/api/v1/narrative/dictionary_stats", timeout=5)
        if r.status_code == 200:
            d = r.json()
            if not d.get("degraded"):
                total = d.get("total_terms", 0)
                if total == 0:
                    results.append(_make("舆情引擎", "叙事词典", WARNING,
                                         "叙事词典为空", "需初始化"))
                else:
                    results.append(_make("舆情引擎", "叙事词典", OK,
                                         f"{total} 个词条", ""))
    except Exception:
        pass

    # Pending inbox backlog
    try:
        r = requests.get(f"{base}/api/v1/narrative/pending_inbox",
                         params={"status": "pending", "limit": 1}, timeout=5)
        if r.status_code == 200:
            d = r.json()
            if not d.get("degraded"):
                pending = d.get("total", 0)
                if pending > 100:
                    results.append(_make("舆情引擎", "待审收件箱", WARNING,
                                         f"{pending} 条待审词条积压",
                                         "建议尽快审核"))
                elif pending > 0:
                    results.append(_make("舆情引擎", "待审收件箱", INFO,
                                         f"{pending} 条待审", ""))
                else:
                    results.append(_make("舆情引擎", "待审收件箱", OK,
                                         "无积压", ""))
    except Exception:
        pass

    return results


# ===================================================================
# 7. 页面完整性 & 核心模块语法
# ===================================================================
def check_page_integrity():
    results = []
    pages_dir = PROJECT_ROOT / "pages"

    expected_pages = {
        "0_宏观雷达.py": "宏观雷达",
        "1_宏观定调.py": "宏观定调",
        "2_舆情监控.py": "舆情监控",
        "3_资产细筛.py": "资产细筛",
        "4_资产调研.py": "资产调研",
        "5_个股择时.py": "个股择时",
        "6_仓位配置.py": "仓位配置",
    }

    for fname, desc in expected_pages.items():
        fpath = pages_dir / fname
        if not fpath.exists():
            results.append(_make("页面完整", desc, ERROR,
                                 f"页面文件缺失: {fname}", f"路径: {fpath}"))
            continue
        size = fpath.stat().st_size
        if size < 100:
            results.append(_make("页面完整", desc, WARNING,
                                 f"文件内容异常 ({size} bytes)", "文件过小"))
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
            compile(content, str(fpath), "exec")
            results.append(_make("页面完整", desc, OK, f"{fname} 语法正常", ""))
        except SyntaxError as e:
            results.append(_make("页面完整", desc, ERROR,
                                 f"语法错误 L{e.lineno}: {e.msg}",
                                 f"{fname}:{e.lineno}"))

    # Core modules
    for mod_file in ["api_client.py", "screener_engine.py", "conviction_engine.py"]:
        fpath = PROJECT_ROOT / mod_file
        if not fpath.exists():
            results.append(_make("页面完整", mod_file, ERROR,
                                 f"核心模块缺失", ""))
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
            compile(content, str(fpath), "exec")
            results.append(_make("页面完整", mod_file, OK, "语法正常", ""))
        except SyntaxError as e:
            results.append(_make("页面完整", mod_file, ERROR,
                                 f"语法错误 L{e.lineno}: {e.msg}",
                                 f"{mod_file}:{e.lineno}"))
    return results


# ===================================================================
# 8. 代码冲突检测 (Git merge conflict markers)
# ===================================================================
def check_code_conflicts():
    results = []
    # Build marker dynamically to avoid this file triggering itself
    conflict_marker = "<" * 7 + " "
    scan_dirs = [PROJECT_ROOT, PROJECT_ROOT / "pages"]
    conflict_files = []

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for fpath in scan_dir.glob("*.py"):
            if fpath.name == "health_checker.py":
                continue
            try:
                content = fpath.read_text(encoding="utf-8")
                if conflict_marker in content:
                    lines = [i + 1 for i, line in enumerate(content.splitlines())
                             if line.startswith(conflict_marker)]
                    conflict_files.append((fpath.name, lines))
            except Exception:
                pass

    if conflict_files:
        detail_parts = [f"{name} (L{','.join(map(str, lns))})"
                        for name, lns in conflict_files]
        results.append(_make("代码冲突", "Git 合并冲突", ERROR,
                             f"{len(conflict_files)} 个文件含未解决的合并冲突",
                             " | ".join(detail_parts)))
    else:
        results.append(_make("代码冲突", "Git 合并冲突", OK,
                             "无合并冲突标记", ""))
    return results


# ===================================================================
# 9. 第三方 API 密钥配置状态
# ===================================================================
def check_api_keys():
    """通过后端 /api/v1/system/api_keys_status 端点检查各 key 是否已配置。"""
    results = []
    base = _api_base()
    try:
        r = requests.get(f"{base}/api/v1/system/api_keys_status", timeout=5)
        if r.status_code != 200:
            results.append(_make("API密钥", "密钥状态接口", WARNING,
                                 f"状态端点返回 HTTP {r.status_code}", ""))
            return results
        data = r.json()
    except requests.exceptions.ConnectionError:
        results.append(_make("API密钥", "密钥状态接口", CRITICAL,
                             "后端不可达，无法检查 API Key", ""))
        return results
    except Exception as e:
        results.append(_make("API密钥", "密钥状态接口", WARNING,
                             "密钥状态检查异常", str(e)))
        return results

    for item in data.get("keys", []):
        env_name = item["env_name"]
        provider = item["provider"]
        purpose = item["purpose"]
        configured = item["configured"]
        if configured:
            results.append(_make("API密钥", f"{provider} ({env_name})", OK,
                                 f"已配置 — {purpose}", ""))
        else:
            results.append(_make("API密钥", f"{provider} ({env_name})", WARNING,
                                 f"未配置 — {purpose} 功能将降级",
                                 f"在 Render → Environment 中设置 {env_name}"))
    return results


# ===================================================================
# Orchestrator — parallel execution, cached 5 min
# ===================================================================
def run_all_checks() -> dict:
    """Run all checkers in parallel threads. Returns a plain dict for cache."""
    checkers = [
        check_backend_connectivity,
        check_api_contract,
        check_data_integrity,
        check_market_data,
        check_dependencies,
        check_narrative_engine,
        check_page_integrity,
        check_code_conflicts,
        check_api_keys,
    ]

    all_results = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in checkers}
        for future in as_completed(futures):
            fn_name = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as e:
                all_results.append(_make("质检系统", fn_name, ERROR,
                                         f"检查器自身异常: {type(e).__name__}",
                                         str(e)))

    elapsed_total = (time.time() - t_start) * 1000

    counts = {CRITICAL: 0, ERROR: 0, WARNING: 0, INFO: 0, OK: 0}
    for r in all_results:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1

    # Group by category, preserve order
    categories = {}
    for r in all_results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)

    # Per-category worst severity
    cat_summary = {}
    for cat, items in categories.items():
        worst = min(items, key=lambda x: SEVERITY_ORDER.get(x["severity"], 99))
        cat_summary[cat] = worst["severity"]

    return {
        "results": all_results,
        "counts": counts,
        "categories": categories,
        "cat_summary": cat_summary,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": round(elapsed_total, 1),
        "total": len(all_results),
    }
