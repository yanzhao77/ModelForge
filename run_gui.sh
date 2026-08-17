#!/usr/bin/env bash
# ModelForge 本地启动脚本（默认不启动 Docker）
# 流程：先启动本地 uvicorn（若未运行）→ 等待健康检查通过 → 再启动 GUI 客户端。
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
HOST="127.0.0.1"
PORT="8000"
BASE_URL="http://$HOST:$PORT"

if [ ! -x "$VENV/bin/python" ]; then
    echo "错误：未找到虚拟环境 $VENV" >&2
    echo "请先执行：python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt -r requirements-gui.txt" >&2
    exit 1
fi

# 1. 确保本地 uvicorn 已启动
if curl -fsS --max-time 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
    echo "✓ 本地 uvicorn 已在运行：$BASE_URL"
else
    echo "启动本地 uvicorn（$BASE_URL）..."
    "$VENV/bin/python" -m uvicorn main:app \
        --app-dir "$ROOT/backend/app" \
        --host "$HOST" --port "$PORT" \
        >"$ROOT/logs/uvicorn.log" 2>&1 &
    UVICORN_PID=$!
    echo "uvicorn PID=$UVICORN_PID"

    # 等待健康检查通过
    ready=0
    for _ in $(seq 1 30); do
        if curl -fsS --max-time 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    if [ "$ready" -ne 1 ]; then
        echo "错误：uvicorn 未能在 30s 内就绪，请查看 $ROOT/logs/uvicorn.log" >&2
        exit 1
    fi
    echo "✓ 本地 uvicorn 已就绪：$BASE_URL"
fi

# 2. 启动 GUI 客户端
echo "启动 GUI 客户端（连接 $BASE_URL）..."
cd "$ROOT/client/pyside6"
exec "$VENV/bin/python" main.py
