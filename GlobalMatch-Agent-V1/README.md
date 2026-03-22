# 🌍 GlobalMatch-Agent-V1

**中国卖家的AI全球买家开发神器**

输入一句话，后台Agent自动爬取全球买家 → 验证联系方式 → 一键发送开发信 → 监控买家回复 → 微信推送通知。全程存档，完全自动化。

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔍 **AI买家搜索** | 输入产品描述，自动分析并从20个全球数据源爬取真实买家 |
| 📄 **PDF/链接解析** | 上传产品PDF或粘贴链接，AI自动提取产品信息 |
| 📧 **AI开发信生成** | Kimi AI根据买家公司信息生成个性化英文邮件 |
| 📤 **批量发送** | 使用用户自己的SMTP账号发送，随机延迟防封 |
| 📱 **微信通知** | Server酱推送：搜索完成、买家回复 |
| 📊 **全程存档** | 所有搜索、发送、回复记录存Supabase |
| 🔄 **后台任务** | Celery确保用户关闭浏览器后任务继续运行 |

---

## 🗂 20个数据源

| 地区 | 平台 |
|------|------|
| 北美 | ImportYeti, Piers.com, Thomasnet, Hoovers |
| 欧洲 | Kompass, Europages, Wlw.de, Kellysearch |
| 中东 | Zawya, TradeArabia |
| 东南亚/印度 | TradeIndia, ExportersIndia, EC21 |
| 全球通用 | Alibaba RFQ, Google搜索, LinkedIn公开页 |
| 全球补充 | TradeKey, TradeWheel, ExportHub, Yellowpages |

任意数据源失败自动切换，保证高容错。

---

## 🚀 快速启动（GitHub Codespaces）

### 方式一：GitHub Codespaces（推荐，零配置）

1. 点击仓库页面的 **Code → Codespaces → Create codespace on main**
2. 等待环境初始化（约3分钟）
3. 在终端执行：

```bash
# 1. 复制环境变量文件
cp .env.example .env

# 2. 编辑.env，填入必需配置（至少填Kimi和Supabase）
nano .env

# 3. 启动所有服务
docker-compose up -d

# 4. 等待服务启动（约1分钟）
docker-compose logs -f
```

4. 访问 Codespaces 转发的 8080 端口即可使用

---

### 方式二：本地开发

#### 前提条件
- Python 3.12+
- Redis（或使用Docker）
- Git

#### 步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-repo/GlobalMatch-Agent-V1.git
cd GlobalMatch-Agent-V1

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装Playwright浏览器
playwright install chromium --with-deps

# 5. 复制并配置环境变量
cp .env.example .env
# 编辑.env文件，填入你的配置

# 6. 启动Redis（如果本地没有Redis，使用Docker）
docker run -d -p 6379:6379 redis:7.4-alpine

# 7. 启动Celery Worker（新终端）
celery -A tasks.celery_app worker --loglevel=info -Q default,search,email,monitor

# 8. 启动Celery Beat（定时任务，新终端）
celery -A tasks.celery_app beat --loglevel=info

# 9. 启动Chainlit前端（新终端）
chainlit run chainlit_app.py --host 0.0.0.0 --port 8080

# 10. 访问
# 前端界面：http://localhost:8080
# API文档：http://localhost:8000/docs
# Flower监控：http://localhost:5555 (admin/admin123)
```

---

### 方式三：Docker Compose（一键启动）

```bash
# 1. 配置环境变量
cp .env.example .env
nano .env  # 填入配置

# 2. 一键启动所有服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f chainlit    # 前端日志
docker-compose logs -f celery_worker  # Celery日志
docker-compose logs -f redis       # Redis日志

# 4. 停止服务
docker-compose down

# 5. 更新代码后重启
git pull && docker-compose up -d --build
```

---

## 🔧 环境变量说明

### 必填项

| 变量名 | 说明 | 获取方式 |
|--------|------|----------|
| `KIMI_API_KEY` | Kimi AI API密钥 | https://platform.moonshot.cn/console/api-keys |
| `SUPABASE_URL` | Supabase项目URL | https://supabase.com/dashboard → 项目设置 → API |
| `SUPABASE_KEY` | Supabase anon key | 同上 |

### 邮件配置（发送开发信必填）

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `SMTP_HOST` | SMTP服务器地址 | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP端口 | `587`（TLS）或 `465`（SSL） |
| `SMTP_USER` | 邮箱账号 | `your@gmail.com` |
| `SMTP_PASSWORD` | 邮箱密码/应用密码 | Gmail需要应用专用密码 |
| `IMAP_HOST` | IMAP服务器（收件监控） | `imap.gmail.com` |
| `IMAP_USER` | IMAP账号（通常同SMTP） | `your@gmail.com` |
| `IMAP_PASSWORD` | IMAP密码 | 同上 |

**Gmail应用密码获取**：
Google账号 → 安全 → 两步验证（需先开启） → 应用专用密码 → 生成

**163邮箱示例**：
```
SMTP_HOST=smtp.163.com
SMTP_PORT=465
SMTP_USE_TLS=false
```

### 微信通知（可选）

| 变量名 | 说明 | 获取方式 |
|--------|------|----------|
| `SERVERCHAN_SEND_KEY` | Server酱SendKey | https://sct.ftqq.com/ 免费注册 |

**Server酱配置步骤**：
1. 访问 https://sct.ftqq.com/
2. 用微信扫码登录
3. 点击"发送消息"→ 复制 SendKey
4. 填入 `.env` 的 `SERVERCHAN_SEND_KEY`

### WhatsApp（可选）

| 变量名 | 说明 |
|--------|------|
| `WHATSAPP_TOKEN` | WhatsApp Business API Token |
| `WHATSAPP_PHONE_NUMBER_ID` | 手机号ID |

---

## 🗄 Supabase数据库配置

首次使用需要在Supabase中创建数据表。进入 Supabase 控制台 → SQL Editor，执行以下SQL：

```sql
-- 复制 database/supabase_client.py 中 SUPABASE_DDL 变量的内容执行
-- 或者访问: https://your-project.supabase.co/project/default/sql
```

或者通过API自动创建（首次运行时执行）：

```bash
python -c "
from database.supabase_client import db, SUPABASE_DDL
client = db._get_client()
# 在Supabase控制台SQL Editor中执行 SUPABASE_DDL 中的SQL
print(SUPABASE_DDL)
"
```

---

## 📊 Celery监控（Flower）

访问 http://localhost:5555（默认账号：admin / admin123）

可以查看：
- 任务队列状态
- Worker运行状态
- 任务成功/失败统计
- 实时任务日志

---

## 🔍 容错机制说明

### 爬虫层
- 20个数据源独立进程隔离，一个崩了不影响其他
- 每个页面超时30秒，超时自动关闭重试（最多3次）
- 反爬触发（403/429/验证码）自动切换备用数据源
- 内存保护：每个Playwright browser用完强制close
- 结果不足自动扩展关键词（同义词/相关品类/扩大地区）

### Celery任务层
- 失败自动重试3次（60/120/240秒间隔）
- 软超时30分钟，硬超时35分钟
- worker意外崩溃，任务自动重新入队（acks_late=True）
- 任务结果持久化到Supabase，重启后可恢复

### 数据库层
- 连接失败自动重试3次
- 写入失败记录到本地fallback文件（`fallback/fallback_writes.jsonl`）
- 每小时自动将fallback文件补写到Supabase
- 大批量写入分批50条，避免超时

### 邮件发送层
- SMTP连接失败自动重试
- 单封邮件发失败不影响其他邮件（断点续发）
- 收到550/421错误自动降速
- 每分钟最多5封 + 随机延迟5-30秒防封

---

## 📁 项目结构

```
GlobalMatch-Agent-V1/
├── chainlit_app.py          # Chainlit前端（中文界面）
├── main.py                  # FastAPI后端 + 健康检查
├── config.py                # 全局配置，启动时验证环境变量
├── agent/
│   ├── kimi_client.py       # Kimi AI封装（产品分析+邮件生成）
│   ├── search_agent.py      # 搜索Agent（协调20个爬虫）
│   ├── email_agent.py       # 邮件发送Agent
│   └── monitor_agent.py     # IMAP回复监控Agent
├── scrapers/                # 20个数据源爬虫（独立文件）
│   ├── base_scraper.py      # 爬虫基类
│   ├── importyeti_scraper.py
│   ├── kompass_scraper.py
│   └── ...（共20个）
├── tasks/
│   ├── celery_app.py        # Celery配置（队列/调度/超时）
│   ├── search_task.py       # 搜索Celery任务
│   ├── email_task.py        # 发送Celery任务
│   └── monitor_task.py      # 监控Beat定时任务
├── database/
│   └── supabase_client.py   # Supabase操作封装（重试+fallback）
├── utils/
│   ├── pdf_parser.py        # PyMuPDF解析
│   ├── email_validator.py   # 邮箱验证
│   ├── wechat_notify.py     # Server酱微信通知
│   └── dedup.py             # 买家去重逻辑
├── fallback/                # 数据库写入失败时的本地备份
├── .env.example             # 环境变量模板
├── requirements.txt
├── Dockerfile
├── docker-compose.yml       # 一键启动（Redis+Celery+Chainlit）
└── .github/workflows/deploy.yml
```

---

## 🛠 常见问题

**Q: Redis连接失败？**
```bash
# 检查Redis是否启动
redis-cli ping
# 或者用Docker启动
docker run -d -p 6379:6379 redis:7.4-alpine
```

**Q: Playwright安装失败？**
```bash
playwright install chromium --with-deps
# 如果在Docker中，确保Dockerfile包含系统依赖
```

**Q: Supabase连接失败？**
- 检查 `SUPABASE_URL` 和 `SUPABASE_KEY` 是否正确
- 确保已在Supabase中执行建表SQL

**Q: Gmail发送失败？**
- 需要开启两步验证并生成应用专用密码
- 不能使用账号原始密码

**Q: 搜索结果为空？**
- 检查网络是否可以访问外国网站
- 某些爬虫需要能访问对应网站
- 尝试更换关键词（英文效果更好）

---

## 📝 版本历史

- **v1.0.0** (2026-03) - 初始版本，20数据源，Chainlit界面，Celery后台任务

---

## 📄 许可证

MIT License - 详见 LICENSE 文件
