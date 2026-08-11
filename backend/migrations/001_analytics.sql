-- 数据统计研判模块 · 建表与种子数据迁移脚本
-- 版本：001  ·  日期：2026-08-11
-- 说明：本脚本由 init_db.py 在 ORM 建表后追加执行，用于：
--   1) 创建 analytics_event 月度 RANGE 分区（MySQL 不支持 ORM 直接声明分区）
--   2) 为现有用户补默认角色 viewer（admin 账户补 admin）
--   3) 插入 15 个默认指标字典
--   4) 插入 5 条示例研判规则
-- 幂等：所有语句均带 IF NOT EXISTS 或先 SELECT 判断，可重复执行。

-- ===== 1. analytics_event 月度分区 =====
-- 注：MySQL 要求分区表主键必须包含分区列，故仅当表为空时改造。
-- 这里给出改造示例（首次执行时手动运行）：
--
-- ALTER TABLE analytics_event
--   DROP PRIMARY KEY,
--   ADD PRIMARY KEY (id, occurred_at)
--   PARTITION BY RANGE (TO_DAYS(occurred_at)) (
--     PARTITION p202608 VALUES LESS THAN (TO_DAYS('2026-09-01')),
--     PARTITION p202609 VALUES LESS THAN (TO_DAYS('2026-10-01')),
--     PARTITION pmax     VALUES LESS THAN MAXVALUE
--   );

-- ===== 2. 为现有用户补默认角色 =====
-- admin 用户 → admin，其他用户 → viewer
INSERT INTO user_roles (user_id, role, created_at, updated_at)
SELECT u.id,
       CASE WHEN u.username = 'admin' THEN 'admin' ELSE 'viewer' END,
       NOW(), NOW()
FROM users u
WHERE NOT EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id);

-- ===== 3. 默认指标字典（15 个） =====
-- 字段：code, name, category, data_source, unit, granularity, expression(JSON 字符串), description
INSERT INTO analytics_indicator
  (code, name, category, data_source, unit, granularity, expression, description, is_active, created_at, updated_at)
VALUES
  ('device_online_rate', '设备在线率', 'device', 'telemetry', '%', 'day',
   '{"type":"ratio","numerator":{"table":"devices","filter":{"status":"online"}},"denominator":{"table":"devices","filter":{}}}',
   '在线设备数 / 总设备数', true, NOW(), NOW()),

  ('device_avg_battery', '平均电量', 'device', 'telemetry', '%', 'day',
   '{"type":"aggregate","func":"avg","table":"devices","field":"battery"}',
   '所有设备当前电量平均值', true, NOW(), NOW()),

  ('device_low_battery_count', '低电量设备数', 'device', 'telemetry', '台', 'day',
   '{"type":"aggregate","func":"count","table":"devices","filter":{"battery_lt":20}}',
   '电量低于 20% 的设备数量', true, NOW(), NOW()),

  ('patrol_task_completion_rate', '巡检完成率', 'patrol', 'patrol', '%', 'day',
   '{"type":"ratio","numerator":{"table":"patrol_tasks","filter":{"status":"completed"}},"denominator":{"table":"patrol_tasks","filter":{}}}',
   '已完成巡检任务数 / 总任务数', true, NOW(), NOW()),

  ('patrol_task_avg_duration', '平均巡检时长', 'patrol', 'patrol', '分钟', 'day',
   '{"type":"aggregate","func":"avg","table":"patrol_tasks","field":"duration_minutes","filter":{"status":"completed"}}',
   '已完成任务的平均耗时', true, NOW(), NOW()),

  ('patrol_distance_total', '巡检总里程', 'patrol', 'patrol', '米', 'day',
   '{"type":"aggregate","func":"sum","table":"patrol_routes","field":"distance"}',
   '当日执行巡检任务的线路总里程', true, NOW(), NOW()),

  ('alert_total', '告警总数', 'alert', 'alert', '条', 'day',
   '{"type":"aggregate","func":"count","table":"security_alerts"}',
   '当日新增告警总数', true, NOW(), NOW()),

  ('alert_by_severity', '分级告警数', 'alert', 'alert', '条', 'day',
   '{"type":"aggregate","func":"count","table":"security_alerts","group_by":"severity"}',
   '按告警等级分组的数量', true, NOW(), NOW()),

  ('alert_avg_close_time', '告警平均处置时长', 'alert', 'alert', '分钟', 'day',
   '{"type":"aggregate","func":"avg","table":"security_alerts","field":"close_minutes","filter":{"status":"closed"}}',
   '已关闭告警的平均处置耗时', true, NOW(), NOW()),

  ('alert_pending_count', '待处置告警数', 'alert', 'alert', '条', '5min',
   '{"type":"aggregate","func":"count","table":"security_alerts","filter":{"status_in":["pending","acknowledged"]}}',
   '当前未关闭告警数量（近实时）', true, NOW(), NOW()),

  ('cluster_active_rate', '集群活跃率', 'device', 'telemetry', '%', 'day',
   '{"type":"ratio","numerator":{"table":"clusters","filter":{"has_online":true}},"denominator":{"table":"clusters","filter":{}}}',
   '含有至少一台在线设备的集群占比', true, NOW(), NOW()),

  ('device_signal_avg', '平均信号强度', 'device', 'telemetry', '%', 'day',
   '{"type":"aggregate","func":"avg","table":"devices","field":"signal"}',
   '所有设备当前信号强度平均值', true, NOW(), NOW()),

  ('device_offline_duration', '离线总时长', 'device', 'telemetry', '分钟', 'day',
   '{"type":"aggregate","func":"sum","table":"device_offline_log","field":"minutes"}',
   '当日所有设备离线累计时长', true, NOW(), NOW()),

  ('external_weather_impact', '天气影响分', 'external', 'external', '分', 'day',
   '{"type":"external","provider":"weather","field":"impact_score"}',
   '外部天气 API 计算的巡逻影响分', true, NOW(), NOW()),

  ('manual_event_count', '人工录入事件数', 'manual', 'manual', '条', 'day',
   '{"type":"aggregate","func":"count","table":"analytics_event","filter":{"source":"manual"}}',
   '当日人工录入事件总数', true, NOW(), NOW())
ON DUPLICATE KEY UPDATE updated_at = NOW();

-- ===== 4. 示例研判规则（5 条） =====
INSERT INTO analytics_rule
  (name, indicator_id, rule_type, `condition`, severity, alert_type, description, is_active, created_at, updated_at)
SELECT r.name, i.id, r.rule_type, r.cond, r.severity, r.alert_type, r.desc, true, NOW(), NOW()
FROM (
  SELECT '低电量预警' AS name, 'device_low_battery_count' AS code, 'threshold' AS rule_type,
         '{"op":">","value":0,"window_days":1}' AS cond, 'medium' AS severity, 'low_battery' AS alert_type,
         '存在低电量设备时触发' AS desc
  UNION ALL SELECT '在线率突降', 'device_online_rate', 'zscore',
         '{"z_threshold":-2,"window_days":7}', 'high', 'online_drop',
         '在线率 7 日 Z-Score 小于 -2'
  UNION ALL SELECT '巡检完成率不达标', 'patrol_task_completion_rate', 'consecutive',
         '{"op":"<","value":0.8,"consecutive_days":3}', 'medium', 'patrol_low_completion',
         '巡检完成率连续 3 天低于 80%'
  UNION ALL SELECT '告警积压', 'alert_pending_count', 'threshold',
         '{"op":">","value":10,"window_minutes":60}', 'high', 'alert_backlog',
         '待处置告警超过 10 条且持续 1 小时'
  UNION ALL SELECT '信号异常下降', 'device_signal_avg', 'ratio',
         '{"compare":"baseline","drop_pct":0.3,"window_days":3}', 'low', 'signal_drop',
         '信号强度较基线下降 30%'
) r
JOIN analytics_indicator i ON i.code = r.code
WHERE NOT EXISTS (SELECT 1 FROM analytics_rule ar WHERE ar.name = r.name);

-- ===== 结束 =====
