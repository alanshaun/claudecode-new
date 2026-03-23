#!/bin/bash
# 一键启动 GlobalMatch-Agent-V1
# 务必使用 run_celery.sh 和 run_chainlit.sh，避免 No module named 'tasks'/'scrapers' 错误
cd "$(dirname "$0")"

echo "🔍 检查 Redis..."
redis-cli ping >/dev/null 2>&1 || { brew services start redis 2>/dev/null; sleep 2; }
redis-cli ping >/dev/null 2>&1 || { echo "❌ Redis 未运行: brew install redis && brew services start redis"; exit 1; }
echo "✅ Redis OK"
echo ""
echo "请开两个终端分别运行："
echo "  终端1: ./run_celery.sh"
echo "  终端2: ./run_chainlit.sh"
echo "  访问: http://localhost:8080"
