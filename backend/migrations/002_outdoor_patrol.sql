-- 校园室外自主巡检 · 数据迁移脚本 002
-- =====================================================================
-- 关联需求：docs/requirements/campus-outdoor-autonomous-patrol.md
-- 关联计划：docs/plans/campus-outdoor-autonomous-patrol-plan.md
--
-- 说明：
--   1. 本脚本由 init_db.py 自动追加执行，幂等可重复运行。
--   2. 所有表通过 SQLAlchemy ORM 的 Base.metadata.create_all 创建；
--      本脚本只补充 ORM 无法表达的约束、索引与种子数据。
--   3. 严禁修改既有 patrol_* 表结构（室内 SLAM 巡检）。
--
-- 表清单（由 ORM 创建）：
--   outdoor_calibrations      校园坐标标定
--   outdoor_routes            室外路线（版本化）
--   outdoor_waypoints         室外航点
--   outdoor_patrol_tasks      室外巡检任务
--   outdoor_patrol_events     室外巡检事件审计
-- =====================================================================


-- ===== 1. outdoor_calibrations 索引与约束 =====
-- 版本号唯一性已由 ORM 保证；这里追加状态查询索引。
-- （MySQL 中 ORM 创建索引名可能与下述冲突，故包裹忽略错误）

CREATE INDEX IF NOT EXISTS idx_outdoor_calibrations_status
  ON outdoor_calibrations (status);

-- active 状态只能有一条记录（避免多版本同时生效）
-- 注：MySQL 不支持 IF NOT EXISTS for unique constraints，需要人工维护。
-- 此处保留注释，由应用层强制。

-- ===== 2. outdoor_routes 索引 =====
CREATE INDEX IF NOT EXISTS idx_outdoor_routes_calibration
  ON outdoor_routes (calibration_id);

CREATE INDEX IF NOT EXISTS idx_outdoor_routes_status
  ON outdoor_routes (status);

-- ===== 3. outdoor_waypoints 索引与唯一键 =====
-- 同一路线下 seq_order 应唯一，避免顺序冲突
-- 注：MySQL 没有 IF NOT EXISTS for unique index；语句若已存在会报错被捕获。
CREATE UNIQUE INDEX IF NOT EXISTS uq_outdoor_waypoints_route_seq
  ON outdoor_waypoints (route_id, seq_order);

-- ===== 4. outdoor_patrol_tasks 索引 =====
CREATE INDEX IF NOT EXISTS idx_outdoor_patrol_tasks_status
  ON outdoor_patrol_tasks (status);

CREATE INDEX IF NOT EXISTS idx_outdoor_patrol_tasks_device
  ON outdoor_patrol_tasks (device_id);

CREATE INDEX IF NOT EXISTS idx_outdoor_patrol_tasks_route
  ON outdoor_patrol_tasks (route_id);

-- ===== 5. outdoor_patrol_events 索引 =====
CREATE INDEX IF NOT EXISTS idx_outdoor_patrol_events_task_type
  ON outdoor_patrol_events (task_id, event_type);

CREATE INDEX IF NOT EXISTS idx_outdoor_patrol_events_occurred
  ON outdoor_patrol_events (occurred_at);

-- ===== 6. 种子数据 =====
-- 不插入任何示例路线或标定记录；
-- 这些数据必须在阶段 B 由管理员通过前端配置界面创建，并完成现场对点验证后才启用。
-- 切勿在迁移脚本中写入虚构坐标（需求 §13 强调真实值由现场试验确定）。

-- ===== 7. 结束 =====
-- 注意：
--   - 本脚本不修改 outdoor_* 表的字段；字段变更通过 ORM 模型修改并由
--     SQLAlchemy 在 init_db.py 中 create_all 时追加（已有表不会被自动 ALTER）。
--   - 如需 ALTER 已有表，请新增 003_xxx.sql 迁移脚本。
