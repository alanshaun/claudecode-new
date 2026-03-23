#!/bin/bash
# 确保 tasks 模块可被导入
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
exec chainlit run chainlit_app.py --host 0.0.0.0 --port 8080 "$@"
