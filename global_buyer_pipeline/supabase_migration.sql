-- pipeline_progress 表：断点续传
-- 在 Supabase SQL Editor 中执行

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

COMMENT ON TABLE pipeline_progress IS '全球买家管道断点续传表';

-- buyers 表（与 GlobalMatch 对齐）
CREATE TABLE IF NOT EXISTS buyers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(500),
    country VARCHAR(100),
    email VARCHAR(500),
    website VARCHAR(500),
    categories TEXT[],
    source VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_buyers_company_country ON buyers(company_name, country);
CREATE INDEX IF NOT EXISTS idx_buyers_source ON buyers(source);
CREATE INDEX IF NOT EXISTS idx_buyers_email ON buyers(email) WHERE email IS NOT NULL;
