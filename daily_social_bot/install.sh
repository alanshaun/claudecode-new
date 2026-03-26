#!/bin/bash
# 一键安装脚本 — 在 Mac 终端运行
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 1/4 写入配置 ==="
cat > .env << 'ENVEOF'
TWITTER_USERNAME=alanxx3yy5w
TWITTER_PASSWORD=730225Aa@
KIMI_API_KEY=sk-m9kVL52fZbRu4PjH9yj2JJ1ruKDUDjaJzvuD8qcXBd3EOvrG
GEMINI_API_KEY=AIzaSyD2TGnFz8G3Hj1DcA2Yi71NhZAZP3fu8U4
FEISHU_APP_ID=cli_a9493909c1611cc6
FEISHU_APP_SECRET=2oWswLgRJLSQGerzCOEXkeJBy35ShOGL
FEISHU_USER_ID=ou_0d87b97dab5ad3be9fceefa57b2a8aff
ENVEOF

echo "=== 2/4 安装 Python 依赖 ==="
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -q

echo "=== 3/4 安装 Playwright 浏览器 ==="
playwright install chromium

echo "=== 4/4 设置定时任务（14:00 / 16:00 / 18:00）==="
PYTHON="$SCRIPT_DIR/.venv/bin/python"
LOG="$SCRIPT_DIR/run.log"
CRONTAB=$(crontab -l 2>/dev/null | grep -v "daily_social_bot" || true)
printf '%s\n' "$CRONTAB" \
  "0 14 * * * cd $SCRIPT_DIR && $PYTHON run_job.py >> $LOG 2>&1" \
  "0 16 * * * cd $SCRIPT_DIR && $PYTHON run_job.py >> $LOG 2>&1" \
  "0 18 * * * cd $SCRIPT_DIR && $PYTHON run_job.py >> $LOG 2>&1" \
  | crontab -

echo ""
echo "✅ 完成！每天 14:00 / 16:00 / 18:00 自动发推"
echo ""
echo "现在测试一次："
echo "  cd $SCRIPT_DIR && source .venv/bin/activate && python run_job.py"
