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

# ── 1. 自动探测虚拟环境 ──────────────────────────────────────────────────────
find_venv() {
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

VENV_ACTIVATE=$(find_venv) || {
    echo ""
    echo "ERROR: 找不到 Python 虚拟环境，已搜索以下路径："
    echo "  · $PARENT_DIR/system/venv"
    echo "  · $SCRIPT_DIR/venv"
    echo "  · $SCRIPT_DIR/.venv"
    echo ""
    echo "请手动创建虚拟环境，或将其放置在上述任一位置后重试。"
    exit 1
}

echo "✔ 使用虚拟环境: $VENV_ACTIVATE"
source "$VENV_ACTIVATE"

# ── 2. 启动后端 ──────────────────────────────────────────────────────────────
if [ ! -d "$BACKEND_DIR" ]; then
    echo ""
    echo "ERROR: 找不到后端目录: $BACKEND_DIR"
    echo "请确认 valuation-radar 与 valuation-radar-ui 位于同一父目录下。"
    exit 1
fi

echo "🚀 启动后端 API 服务 (http://localhost:8000) ..."
cd "$BACKEND_DIR"
python api_server.py &
BACKEND_PID=$!
echo "   后端进程 PID: $BACKEND_PID"

# 等待后端初始化
sleep 2

# ── 3. 启动前端 ──────────────────────────────────────────────────────────────
echo "🌐 启动前端 Streamlit (http://localhost:8501) ..."
cd "$SCRIPT_DIR"
streamlit run app.py

# ── 4. 退出时自动关闭后端 ─────────────────────────────────────────────────────
trap 'echo ""; echo "🛑 正在关闭后端 (PID $BACKEND_PID)..."; kill "$BACKEND_PID" 2>/dev/null; exit 0' EXIT INT TERM
