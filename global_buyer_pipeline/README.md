# global_buyer_pipeline

全球买家数据管道，通过免费官方数据源向 Supabase `buyers` 表批量写入真实全球买家数据。**仅运行在 GitHub Actions，不在本地运行**。

## 数据来源

| 来源 | 说明 |
|------|------|
| UN Comtrade | 按 HS 编码查全球进口数据 |
| 美国海关 | Census 公开 CSV |
| 印度贸易 | tradestat.commerce.gov.in |
| 巴西海关 | MDIC 公开数据 |
| 欧盟 Eurostat | 欧盟贸易 API |
| 展会名录 | 广交会、Ambiente、CES 等 |
| OpenCorporates | 按国家+关键词查公司 |

## 覆盖范围

- **品类**：服装、电子、玩具、户外、设备、装饰、材料、其他消费品
- **地区**：北美、南美、欧洲、中东、东南亚、非洲、大洋洲

## GitHub Actions 配置

### 1. 创建仓库并推送代码

将本目录推送到 GitHub 仓库。

### 2. 添加 Secrets

在仓库 **Settings → Secrets and variables → Actions** 中添加：

- `SUPABASE_URL`：Supabase 项目 URL
- `SUPABASE_KEY`：Supabase service_role 或 anon key
- `COMTRADE_API_KEY`：UN Comtrade API Key（免费注册：https://comtradeapi.un.org）

### 3. Workflows 说明

| Workflow | 触发时间 | 内容 |
|----------|----------|------|
| daily_pipeline | 每天 01:00 北京 | Comtrade + OpenCorporates，最多 5000 条 |
| weekly_pipeline | 每周日 02:00 北京 | 全部 7 个来源，最多 50000 条 |
| email_enrichment | 每天 03:00 北京 | 邮箱补全，最多 1000 条 |

### 4. 手动触发

在 **Actions** 页面选择对应 workflow，点击 **Run workflow**。

## Supabase 建表

在 Supabase SQL Editor 中执行 `supabase_migration.sql`：

```sql
-- pipeline_progress
CREATE TABLE IF NOT EXISTS pipeline_progress (
    id SERIAL PRIMARY KEY,
    source VARCHAR(80) NOT NULL UNIQUE,
    last_hs_code VARCHAR(20),
    last_page INTEGER DEFAULT 0,
    last_offset INTEGER DEFAULT 0,
    total_inserted INTEGER DEFAULT 0,
    last_run TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- buyers（与 GlobalMatch 对齐）
CREATE TABLE IF NOT EXISTS buyers (...);
```

## 项目结构

```
global_buyer_pipeline/
├── pipelines/
│   ├── comtrade.py
│   ├── us_customs.py
│   ├── india_trade.py
│   ├── brazil_trade.py
│   ├── eurostat.py
│   ├── exhibitions.py
│   └── opencorporates.py
├── enrichment/
│   └── email_enrichment.py
├── database/
│   └── supabase_client.py
├── utils/
│   ├── cleaner.py
│   ├── dedup.py
│   └── logger.py
├── main.py
├── .github/workflows/
│   ├── daily_pipeline.yml
│   ├── weekly_pipeline.yml
│   └── email_enrichment.yml
├── requirements.txt
├── .env.example
└── README.md
```

## 数据清洗与去重

- `company_name`、`country` 必填
- 国家标准化：CN→China, US→United States 等
- 去重：`company_name + country` 唯一；`email` 唯一（非空时）
- 已有记录但 email 为空时，新数据有 email 则 UPDATE 补充
