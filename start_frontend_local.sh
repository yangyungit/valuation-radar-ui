#!/usr/bin/env bash
# 本地前端常驻入口，由 launchd (com.yangyun.vr-frontend) 调用。
# 后端由 com.yangyun.vr-backend 单独常驻，这里只起 Streamlit，不重复拉后端。
# 想让局域网其他设备（手机 / iPad）也能看，把 --server.address 改成 0.0.0.0。
# fileWatcherType 必须是 watchdog：poll 模式的线程池只有 4 个 worker，一个文件占一个，
# 32 个 page 只有前 4 个会被监听；none 则完全不监听，改完代码得手动重启。
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(dirname "$HERE")"
STREAMLIT="$WORKSPACE/system/venv/bin/streamlit"

cd "$HERE"

export RADAR_API_URL="http://localhost:8000"
export USE_LOCAL_API="true"
export PYTHONUNBUFFERED=1

exec "$STREAMLIT" run app.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.headless true \
    --server.fileWatcherType watchdog \
    --server.runOnSave true \
    --browser.gatherUsageStats false
