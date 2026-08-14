-- 视频识别分析 · 数据迁移脚本 003
-- =====================================================================
-- 关联计划：docs/plans/video-analysis-module-plan.md（M3 §3.3.3 / M5 §3.5.4）
--
-- 说明：
--   1. 本脚本由 init_db.py 自动追加执行，幂等可重复运行。
--   2. 表由 SQLAlchemy ORM 的 Base.metadata.create_all 创建：
--        video_track_history   追踪轨迹元数据
--        inference_run_log     推理管线运行日志
--   3. 本脚本只补充 ORM 自动命名之外的复合索引。
-- =====================================================================

-- 轨迹元数据按 (device_id, track_id) 查询（upsert 与历史查询）
CREATE INDEX IF NOT EXISTS idx_video_track_history_device_track
  ON video_track_history (device_id, track_id);

-- 运行日志按设备 + 动作过滤
CREATE INDEX IF NOT EXISTS idx_inference_run_log_device_action
  ON inference_run_log (device_id, action);
