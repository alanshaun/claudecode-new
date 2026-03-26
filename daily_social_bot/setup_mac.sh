#!/bin/bash
# 本地 Mac 一键安装脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 安装 Python 依赖 ==="
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -q

echo "=== 安装 Playwright 浏览器 ==="
playwright install chromium

echo "=== 检查 .env 文件 ==="
if [ ! -f ".env" ]; then
    cp .env.template .env
    echo "⚠️  请先填写 .env 文件中的配置，然后重新运行此脚本"
    exit 1
fi

echo "=== 设置定时任务 ==="
PYTHON="$SCRIPT_DIR/.venv/bin/python"
JOB="$PYTHON $SCRIPT_DIR/run_job.py >> $SCRIPT_DIR/run.log 2>&1"
CRON_FILE=$(mktemp)

# 导出现有 cron，过滤掉旧的 daily_social 任务
crontab -l 2>/dev/null | grep -v "run_job.py" > "$CRON_FILE" || true

# 下午时段：14:00 / 16:00 / 18:00（北京时间）
echo "0 14 * * * $JOB" >> "$CRON_FILE"
echo "0 16 * * * $JOB" >> "$CRON_FILE"
echo "0 18 * * * $JOB" >> "$CRON_FILE"

crontab "$CRON_FILE"
rm "$CRON_FILE"

echo ""
echo "✅ 安装完成！"
echo "   定时任务：每天 14:00 / 16:00 / 18:00 自动运行"
echo "   日志文件：$SCRIPT_DIR/run.log"
echo ""
echo "手动测试运行："
echo "  cd $SCRIPT_DIR && source .venv/bin/activate && python run_job.py"
