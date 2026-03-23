-- 若 anon key 无法写入，在 Supabase SQL Editor 执行以下策略
-- 或改用 Service Role Key（在 API settings > Secret keys 中获取）

-- buyers 表：允许 anon 读写
ALTER TABLE buyers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "buyers_anon_all" ON buyers;
CREATE POLICY "buyers_anon_all" ON buyers FOR ALL USING (true) WITH CHECK (true);

-- pipeline_progress 表：允许 anon 读写
ALTER TABLE pipeline_progress ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "progress_anon_all" ON pipeline_progress;
CREATE POLICY "progress_anon_all" ON pipeline_progress FOR ALL USING (true) WITH CHECK (true);
