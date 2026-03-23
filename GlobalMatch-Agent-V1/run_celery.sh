#!/bin/bash
# 确保 scrapers 等模块可被 Worker 导入
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
exec celery -A tasks.celery_app worker --loglevel=info -Q default,search,email,monitor "$@"
