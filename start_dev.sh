#!/usr/bin/env bash
# =============================================================================
# start_dev.sh — Valuation Radar 一键开发环境启动脚本 (macOS / Linux)
#
# 目录约定（推荐，也会自动回退到其他位置）：
#   <parent>/
#   ├── valuation-radar/       ← 后端
#   ├── valuation-radar-ui/    ← 前端（本脚本所在目录）
#   └── system/venv/           ← 共享虚拟环境
#
# 用法：bash start_dev.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PARENT_DIR/valuation-radar"

# ── 1. 自动探测前后端各自的虚拟环境 ──────────────────────────────────────────
find_frontend_venv() {
    local candidates=(
        "$PARENT_DIR/system/venv/bin/activate"
        "$SCRIPT_DIR/venv/bin/activate"
        "$SCRIPT_DIR/.venv/bin/activate"
        "$PARENT_DIR/venv/bin/activate"
    )
    for path in "${candidates[@]}"; do
        if [ -f "$path" ]; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

find_backend_venv() {
    local candidates=(
        "$BACKEND_DIR/venv/bin/activate"
        "$BACKEND_DIR/.venv/bin/activate"
        "$PARENT_DIR/system/venv/bin/activate"
        "$PARENT_DIR/venv/bin/activate"
    )
    for path in "${candidates[@]}"; do
        if [ -f "$path" ]; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

FRONTEND_VENV_ACTIVATE=$(find_frontend_venv) || {
    echo ""
    echo "ERROR: 找不到前端 Python 虚拟环境，已搜索以下路径："
    echo "  · $PARENT_DIR/system/venv"
    echo "  · $SCRIPT_DIR/venv"
    echo "  · $SCRIPT_DIR/.venv"
    echo "  · $PARENT_DIR/venv"
    echo ""
    echo "请先为前端创建虚拟环境。"
    exit 1
}

BACKEND_VENV_ACTIVATE=$(find_backend_venv) || {
    echo ""
    echo "ERROR: 找不到后端 Python 虚拟环境，已搜索以下路径："
    echo "  · $BACKEND_DIR/venv"
    echo "  · $BACKEND_DIR/.venv"
    echo "  · $PARENT_DIR/system/venv"
    echo "  · $PARENT_DIR/venv"
    echo ""
    echo "请先为后端创建虚拟环境。"
    exit 1
}

echo "✔ 前端虚拟环境: $FRONTEND_VENV_ACTIVATE"
echo "✔ 后端虚拟环境: $BACKEND_VENV_ACTIVATE"
source "$FRONTEND_VENV_ACTIVATE"

# ── 2. Python 版本检查（前端环境） ───────────────────────────────────────────
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_VER="$PY_MAJOR.$PY_MINOR"
if [ "$PY_MAJOR" -lt 3 ] || ( [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ] ); then
    echo ""
    echo "❌ Python $PY_VER 不满足要求，请升级到 Python 3.11+"
    echo "   推荐方式: brew install pyenv && pyenv install 3.11 && pyenv global 3.11"
    echo "   然后重建虚拟环境后重试。"
    exit 1
fi
echo "✔ Python $PY_VER OK"

# ── 3. 启动后端 ──────────────────────────────────────────────────────────────
if [ ! -d "$BACKEND_DIR" ]; then
    echo ""
    echo "ERROR: 找不到后端目录: $BACKEND_DIR"
    echo "请确认 valuation-radar 与 valuation-radar-ui 位于同一父目录下。"
    exit 1
fi

echo "🚀 启动后端 API 服务 (http://localhost:8000) ..."
cd "$BACKEND_DIR"

# page 8 的年度 PIT 规则池属于本地运行时数据，不进 Git。若工作区清理或切换环境后缺失，
# 直接用同级 data/sharadar/parquet 的 SF1/TICKERS 自动重建，避免后端启动后页面才报错。
STABLE_POOL_FILE="$BACKEND_DIR/data/buyback_stable_pool.json"
if [ ! -f "$STABLE_POOL_FILE" ]; then
    echo "⚙️ 缺少 buyback_stable_pool.json，正在从 Sharadar Parquet 重建..."
    bash -lc "source \"$BACKEND_VENV_ACTIVATE\" && cd \"$BACKEND_DIR\" && python scripts/build_buyback_stable_pool.py"
    if [ ! -s "$STABLE_POOL_FILE" ]; then
        echo "ERROR: buyback_stable_pool.json 重建失败，后端未启动。"
        exit 1
    fi
    echo "✔ ROIC 稳定池已重建: $STABLE_POOL_FILE"
fi

# 基本面长图同样依赖被 Git 忽略的本地运行时 JSON。目录被清理后，后端会把缺失的
# manifest 当成成功的空列表返回，页面因此只显示“尚无数据”。启动时仅在缺失时重建；
# 失败只告警，不影响其他页面继续启动。
FUNDAMENTALS_MANIFEST="$BACKEND_DIR/data/fundamentals/_manifest.json"
if [ ! -s "$FUNDAMENTALS_MANIFEST" ]; then
    echo "⚙️ 缺少基本面长图数据，正在从 Sharadar Parquet 重建..."
    bash -lc "source \"$BACKEND_VENV_ACTIVATE\" && cd \"$BACKEND_DIR\" && python scripts/push_fundamentals_to_render.py --local"
    if [ -s "$FUNDAMENTALS_MANIFEST" ]; then
        echo "✔ 基本面长图数据已重建: $FUNDAMENTALS_MANIFEST"
    else
        echo "⚠ 基本面长图数据重建失败；其他页面将继续启动。"
    fi
fi

# 从前端 secrets.toml 解析 RESONANCE_INTERNAL_TOKEN，注入后端进程，避免前后端 token 错位
RESONANCE_TOKEN=""
if [ -f "$SCRIPT_DIR/.streamlit/secrets.toml" ]; then
    RESONANCE_TOKEN=$(python3 - <<PYEOF 2>/dev/null || true
try:
    import tomllib
except ImportError:
    import tomli as tomllib
try:
    with open("$SCRIPT_DIR/.streamlit/secrets.toml", "rb") as f:
        data = tomllib.load(f)
    print(data.get("RESONANCE_INTERNAL_TOKEN", ""))
except Exception:
    print("")
PYEOF
)
fi
if [ -n "$RESONANCE_TOKEN" ]; then
    echo "✔ RESONANCE_INTERNAL_TOKEN 已从 secrets.toml 注入后端"
else
    echo "⚠ secrets.toml 未配置 RESONANCE_INTERNAL_TOKEN，叙事共振 API 将返回 503"
fi

bash -lc "source \"$BACKEND_VENV_ACTIVATE\" && RESONANCE_INTERNAL_TOKEN=\"$RESONANCE_TOKEN\" python api_server.py" &
BACKEND_PID=$!
echo "   后端进程 PID: $BACKEND_PID"

trap 'echo ""; echo "🛑 正在关闭后端 (PID $BACKEND_PID)..."; kill "$BACKEND_PID" 2>/dev/null; exit 0' EXIT INT TERM

# 等待后端初始化
sleep 2

# ── 4. 启动前端 ──────────────────────────────────────────────────────────────
echo "🌐 启动前端 Streamlit (http://localhost:8501) ..."
export RADAR_API_URL="http://localhost:8000"
export USE_LOCAL_API="true"
echo "   前端 API 目标已锁定: $RADAR_API_URL"
cd "$SCRIPT_DIR"
streamlit run app.py
