-- GlobalMatch-Agent-V1 数据库初始化
-- 在 Supabase SQL Editor 中运行此脚本

-- 搜索任务表
CREATE TABLE IF NOT EXISTS search_tasks (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT UNIQUE NOT NULL,
    user_query TEXT,
    keywords TEXT[] DEFAULT '{}',
    target_countries TEXT[] DEFAULT '{}',
    buyer_types TEXT[] DEFAULT '{}',
    target_count INTEGER DEFAULT 100,
    status TEXT DEFAULT 'pending',   -- pending / running / completed / failed / timeout
    progress INTEGER DEFAULT 0,
    status_message TEXT DEFAULT '',
    result_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 搜索结果（买家）表
CREATE TABLE IF NOT EXISTS search_results (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT REFERENCES search_tasks(task_id) ON DELETE CASCADE,
    company_name TEXT,
    email TEXT,
    website TEXT,
    linkedin TEXT,
    whatsapp TEXT,
    country TEXT,
    city TEXT,
    contact_name TEXT,
    phone TEXT,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 已发送邮件表
CREATE TABLE IF NOT EXISTS sent_emails (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT,
    buyer_id BIGINT REFERENCES search_results(id) ON DELETE SET NULL,
    to_email TEXT,
    subject TEXT,
    body TEXT,
    status TEXT DEFAULT 'sent',   -- sent / failed / bounced
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

-- 买家回复表
CREATE TABLE IF NOT EXISTS replies (
    id BIGSERIAL PRIMARY KEY,
    from_email TEXT,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    task_id TEXT,
    is_read BOOLEAN DEFAULT FALSE
);

-- 用户设置表
CREATE TABLE IF NOT EXISTS user_settings (
    id BIGSERIAL PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 通知表
CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    type TEXT,
    message TEXT,
    is_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引加速查询
CREATE INDEX IF NOT EXISTS idx_search_tasks_status ON search_tasks(status);
CREATE INDEX IF NOT EXISTS idx_search_tasks_task_id ON search_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_search_results_task_id ON search_results(task_id);
CREATE INDEX IF NOT EXISTS idx_search_results_email ON search_results(email);
