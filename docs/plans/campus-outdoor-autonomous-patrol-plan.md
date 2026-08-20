# 校园室外自主巡检 — 开发计划

- **关联需求**：`docs/requirements/campus-outdoor-autonomous-patrol.md` v0.1
- **状态**：待评审
- **版本**：v0.1
- **制定依据**：当前代码落点核查（2026-08-12）

---

## 0. 当前代码现状盘点

| 模块 | 现状 | 与本期缺口 |
| --- | --- | --- |
| `backend/models.py` | 已有 `PatrolArea / PatrolPoint / PatrolRoute / PatrolRoutePoint / PatrolTask`（均为室内 SLAM 模式，无坐标类型字段） | 需新增 `OutdoorCalibration / OutdoorRoute / OutdoorWaypoint / OutdoorPatrolTask / OutdoorPatrolEvent`，且禁止复用既有表以免污染室内流程 |
| `backend/routers/navigation.py` | `NavigationGoalRequest` 仅 `x/y/yaw`，无 `mode / coordinateType / calibrationVersion` 字段 | 需扩展契约或新建室外独立路由 |
| `backend/routers/patrol.py` | 室内巡检 CRUD，无版本化、无预检、无到点判定 | 室外任务需独立状态机与审计 |
| `agent/ros/iot_client.py` | 已订阅 `/gps/fix /odom /imu`，G70 RTK 驱动 (`wheeltec_nmea_driver.launch`) | 需新增定位健康度计算、GNSS fix 类型枚举、融合定位上报 |
| `agent/ros/robot_control_server.py` | 已实现 `/move_base_simple/goal` 发布与 `nav_status` | 需新增室外任务编排、安全门禁、阻塞处置、急停路径 |
| `frontend/.../PatrolNavigation.jsx` | 室内 SLAM 地图导航界面（栅格地图、move_base 状态） | 需新建独立的室外模式界面，严禁与室内混用 |
| `frontend/.../CampusMap.jsx` | 高德地图展示（WGS84→GCJ-02 仅显示） | 需扩展路线/围栏绘制、定位模式标识、轨迹回放 |

**关键约束**：需求第 5.1 条强制规则要求室内室外严格分离；第 4.2 条新增范围不得污染既有巡检表。本计划据此采用**新建独立模块**而非改造既有表的策略。

---

## 1. 阶段划分与里程碑

完全遵循需求文档第 10 章的阶段划分，但明确每阶段的工程交付物、依赖关系与闸门条件。

```text
阶段 A 硬件与定位可行性
   ├─ 闸门 A：GNSS 能力确认 + 融合定位输出
   ▼
阶段 B 坐标标定与路线配置
   ├─ 闸门 B：试点路线冻结 + 双向转换校验
   ▼
阶段 C 单车受监控巡检 (MVP 最小验收)
   ├─ 闸门 C：开阔区 3 航点巡检验收
   ▼
阶段 D 校园道路试点
   ├─ 闸门 D：10 次试点完成率 ≥95%
   ▼
阶段 E 规模化运行评估
```

任一闸门未通过不得进入下一阶段；闸门失败需返回上一阶段补齐。

---

## 2. 阶段 A：硬件与定位可行性

**目标**：消除需求第 13 章列出的"待确认硬件事实"风险，确认融合定位链路可用。

### 2.1 任务清单

| 编号 | 任务 | 负责端 | 产出 |
| --- | --- | --- | --- |
| A-1 | 采集 GNSS 实际能力清单 | 车端 | `agent/ros/docs/gnss_capability.md`：型号、ROS topic、字段、刷新率、fix 类型 |
| A-2 | 采集校园三区定位样本 | 现场 + 车端 | 开阔区/树荫区/楼宇边缘各 30 分钟 `/gps/fix` rosbag |
| A-3 | 验证 IMU 与轮速里程计可用性 | 车端 | `/imu /odom` 时间对齐记录、TF 树检查 |
| A-4 | 接入融合定位（EKF / robot_localization） | 车端 | `agent/ros/outdoor_localization.launch`、`/odometry/filtered` 话题 |
| A-5 | 实现定位健康度规则骨架 | 车端 | `agent/ros/localization_health.py`（按 FR-01 规则输出 `localizationHealthy`） |
| A-6 | 扩展遥测上报结构 | 车端 + 后端 | `iot_client.py` 输出 §8.2 的 `outdoor_localization` 结构；后端 `DeviceTelemetry.extra_json` 接收 |

### 2.2 退出闸门 A

1. GNSS 能力清单已归档；若**不支持 RTK**，则本计划整体返回评审（影响后续所有阶段）。
2. `/odometry/filtered` 在开阔区稳定输出，`dataAge < 0.5s`。
3. 三区定位样本中，树荫/楼宇边缘的 fix 类型与精度衰减已量化。
4. 后端能持久化至少一次 `outdoor_localization` 上报。

### 2.3 失败回退

- 若硬件无 RTK：停止本计划，重新评估是否改用纯激光 SLAM + 视觉里程计方案。
- 若融合发散：先排查 TF 与单位（度/弧度），必要时切换融合软件包。

---

## 3. 阶段 B：坐标标定与路线配置

**目标**：建立可追溯的坐标基准，完成地图端路线配置能力。

### 3.1 后端任务

| 编号 | 任务 | 关键字段 |
| --- | --- | --- |
| B-1 | 新增数据模型 `OutdoorCalibration` | `name / origin_lng / origin_lat / origin_yaw / version / status / created_at` |
| B-2 | 新增 `OutdoorRoute`（绑定标定版本） | `calibration_id / version / fence_geojson / max_speed / status` |
| B-3 | 新增 `OutdoorWaypoint` | `route_id / seq_order / geo_lng / geo_lat / enu_x / enu_y / yaw / arrival_radius / dwell_sec / action / timeout_sec` |
| B-4 | 实现坐标转换服务 | `backend/services/coord_transform.py`：WGS84↔ENU↔map；记录转换日志（输入/输出/版本/责任端） |
| B-5 | 新增校准版本启用流程 | 必须现场对点验证后才能 `status=active` |
| B-6 | 数据库迁移脚本 | `backend/migrations/xxxx_outdoor_tables.py`，**不修改既有巡检表** |

### 3.2 前端任务

| 编号 | 任务 |
| --- | --- |
| B-7 | `CampusMap` 增加：标定原点标注、围栏多边形绘制、路线折线编辑、航点编辑表单 |
| B-8 | 新增「室外路线管理」页面 `OutdoorRouteAdmin.jsx`（与室内路线页面并列，独立路由） |
| B-9 | 路线保存即生成新版本；版本列表可回溯 |
| B-10 | 所有地图坐标一律保留 `(lng, lat, coordinateType='wgs84')`，展示层做 GCJ-02 转换 |

### 3.3 退出闸门 B

1. 至少 1 个 `campus-main-v1` 标定通过现场对点验证（2 个已知点误差 < 配置阈值）。
2. WGS84→ENU→map 与反向转换均通过单元测试，转换日志可追溯。
3. 1 条试点路线（≥3 航点）已发布并冻结版本。

---

## 4. 阶段 C：单车受监控巡检（MVP）

**目标**：达成需求 §11.1 阶段 C 最小验收标准。此阶段是项目能否继续的关键里程碑。

### 4.1 任务编排引擎（后端）

| 编号 | 任务 | 说明 |
| --- | --- | --- |
| C-1 | 新增 `OutdoorPatrolTask` 与 `OutdoorPatrolEvent` 模型 | 任务冻结路线版本与标定版本快照 |
| C-2 | 实现启动预检接口 `POST /api/outdoor-patrol/precheck` | 按 FR-04.2 列出 8 项预检，返回失败原因清单 |
| C-3 | 实现任务状态机 | `待执行 / 导航中 / 已到达 / 跳过 / 失败 / 暂停 / 已取消`；状态变迁全部入 `OutdoorPatrolEvent` |
| C-4 | 实现航点下发循环 | 按序下发 `/api/navigation/goal`（扩展为 outdoor 契约）；结合到点半径 + 停留时长判定到达 |
| C-5 | 实现航点超时处置 | 每航点 `timeout_sec` 触发后停车并进入异常处理 |
| C-6 | 实现断点恢复策略 | 服务重启或断线后，任务进入 `paused`；恢复需重新预检 |
| C-7 | 扩展 `NavigationGoalRequest` | 新增 `mode / coordinateType / calibrationVersion / goalId`；后端按 `mode` 分流到室内/室外处理 |

### 4.2 车端能力（agent）

| 编号 | 任务 | 说明 |
| --- | --- | --- |
| C-8 | `robot_control_server.py` 增加 `outdoor_goal` 命令类型 | 接收带 `coordinateType` 的目标，必要时按标定版本转换为 `map` 坐标 |
| C-9 | 增加局部避障状态读取 | 订阅 `/move_base/local_costmap` 或等价话题；输出 `obstacle_blocked` 状态 |
| C-10 | 增加阻塞超时处置 | 阻塞超过 `block_timeout` 上报「路线受阻」并停车 |
| C-11 | 增加急停命令通道 | `outdoor_estop` 命令；不依赖前端在线 |
| C-12 | 增加安全门禁本地兜底 | 定位失效、围栏越界、避障失效时车端自行停车，不等后端指令 |

### 4.3 前端可视化

| 编号 | 任务 |
| --- | --- |
| C-13 | 新增「室外巡检监控」页面 `OutdoorPatrolMonitor.jsx`：实时位置、定位模式徽章、当前航点、任务进度条、告警面板 |
| C-14 | 新增任务控制条：启动（触发预检）/ 暂停 / 继续 / 取消 / **急停（红色，始终可用）** |
| C-15 | 实时轨迹绘制（保留最近 N 个融合位置点） |
| C-16 | 异常事件流：展示 `OutdoorPatrolEvent` 时间线 |

### 4.4 退出闸门 C（对应需求 §11.1）

1. ✅ 开阔授权区域完成 ≥3 航点顺序巡检。
2. ✅ 每航点可追溯：路线版本、标定版本、定位状态、下发时间、最终结果。
3. ✅ 地图实时展示位置，明确区分融合位置 vs GNSS 展示位置。
4. ✅ 5 类异常（定位失效/导航失败/传感器失效/通信中断/急停）任一发生均能停车并生成事件。
5. ✅ 恢复需人工触发且重跑预检。
6. ✅ 全链路无 WGS84/GCJ-02 误用为 `map` 坐标的代码路径（代码审查 + 自动化测试覆盖）。

---

## 5. 阶段 D：校园道路试点

**目标**：达成需求 §11.2 试点验收；验证真实场景鲁棒性。

### 5.1 任务

| 编号 | 任务 |
| --- | --- |
| D-1 | 接入任务计划（定时触发），支持 cron 表达式或时间窗口 |
| D-2 | 实现轨迹回放页面：加载任务冻结的路线与标定版本，按时间轴回放轨迹与事件 |
| D-3 | 实现低电量处置：低于阈值自动暂停任务并上报；返航策略评估（未必实现） |
| D-4 | 实现运行告警面板：定位降级区段标注、受阻事件汇总 |
| D-5 | 现场测试矩阵：转弯 / 遮挡 / 临时障碍物 / 短时 GNSS 降级 / 网络中断 / 急停恢复 |

### 5.2 退出闸门 D

- 连续 ≥10 次完整试点，完成率 ≥95%。
- 航点到达误差、安全响应时限满足现场风险评估确认的阈值。
- 试点验收报告归档于 `docs/verification/stage-d-report.md`。

---

## 6. 阶段 E：规模化运行评估

仅在阶段 D 验收通过、校园授权与应急流程明确后进入。本期不承诺交付内容，仅评估：

- 多路线覆盖与定时任务稳定性
- 巡检结果联动（拍照/视频采样）
- 低电量自动返航可行性
- 多车协同是否立项

---

## 7. 配置项清单（对应需求 §9）

所有阈值集中存储于 `backend/config/outdoor_thresholds.py` 或数据库 `outdoor_threshold` 表，按环境（dev/staging/prod）隔离，前端不写死。

| 配置项 | 默认值（待现场标定） | 阶段 |
| --- | --- | --- |
| 最大运行速度 | 0.8 m/s | B |
| GNSS 数据最大年龄 | 1.0 s | A |
| 最低可启动 GNSS 状态 | `RTK_FLOAT` | A |
| 最大允许定位精度 | 0.5 m | A |
| 目标点到达半径 | 0.5 m | C |
| 航点最大执行时长 | 120 s | C |
| 障碍物阻塞超时 | 30 s | C |
| 电子围栏边界缓冲 | 0.3 m | B |
| 低电量停车阈值 | 20% | C |
| 低电量返航阈值 | 15% | D（评估） |
| 控制通道健康窗 | 5 s | C |
| 避障传感器健康窗 | 2 s | C |
| 融合定位健康窗 | 1 s | A |

---

## 8. 接口契约要点

### 8.1 扩展导航目标（禁止破坏室内契约）

新建独立路径 `POST /api/outdoor-navigation/goal`，与室内 `/api/navigation/goal` **物理隔离**，避免 mode 判断遗漏导致坐标混用：

```json
{
  "robotId": 1,
  "coordinateType": "enu" | "wgs84",
  "calibrationVersion": "campus-main-v1",
  "x": 23.42, "y": 15.08, "yaw": 1.57,
  "goalId": "task-123-point-4"
}
```

若 `coordinateType=wgs84`，后端或车端按已固定契约转换；**两端不得重复换算**（需求 §6.2）。

### 8.2 预检接口

`POST /api/outdoor-patrol/precheck` 返回结构：

```json
{
  "ok": false,
  "checks": [
    {"item": "device_online", "passed": true},
    {"item": "control_channel", "passed": true},
    {"item": "localization_healthy", "passed": false, "reason": "GNSS fix=GPS, 低于阈值 RTK_FLOAT"},
    ...
  ]
}
```

任一 `passed=false` 则前端禁用启动按钮并展示原因。

---

## 9. 安全门禁实现要点（对应 FR-07）

| 触发条件 | 检测端 | 处置 |
| --- | --- | --- |
| 定位失效 / 精度超阈 | 车端 + 后端双判 | 立即停车；任务置 `failed` |
| 电子围栏越界 | 后端周期判定 | 立即停车；生成 `fence_breach` 事件 |
| 导航进程异常 | 车端 | 停车；上报 `nav_abnormal` |
| 局部避障数据失效 | 车端 | 禁止启动或停车 |
| 控制通道断开 | 双端心跳 | 车端兜底停车 |
| 电量低于阈值 | 车端 | 停车；后端置 `paused` |
| 人工急停 | 前端按钮 / 车端物理开关 | 最高优先级，立即停车 |

**关键设计**：车端必须实现本地兜底，不能因后端不可达而继续运动（需求 §6.1）。

---

## 10. 测试矩阵（对应需求 §12）

| 层级 | 覆盖项 | 阶段 |
| --- | --- | --- |
| 单元 | 坐标转换、标定版本校验、定位健康度、到点判定、围栏判断、状态机 | B/C |
| 接口 | 成功/非法坐标/标定缺失/版本不一致/设备离线/定位异常/权限不足/超时 | C |
| 车端集成 | ROS topic、TF 链、融合输出、避障输入、导航状态、停车行为 | A/C |
| 现场 | 开阔/树荫/楼宇边缘/转弯/动态障碍物/网络中断/低电量 | C/D |
| 回归 | **室内 SLAM 巡检、手动控制、遥测、地图展示、媒体流** | 每阶段必跑 |

**回归红线**：任何阶段合入前必须验证室内既有功能未受影响（需求 §12.5）。

---

## 11. 风险跟踪（对应需求 §13）

| 风险 | 触发阶段 | 触发后动作 |
| --- | --- | --- |
| GNSS 无 RTK | A | 计划整体暂停，重评方案 |
| 融合定位在树荫区精度恶化 | A | 评估视觉/激光补偿；缩小试点范围 |
| 标定对点误差超阈 | B | 重做标定流程；检查天线安装 |
| 阻塞超时频繁触发 | C/D | 调整代价地图参数；优化路线 |
| 网络中断导致状态丢失 | C | 强化车端本地状态持久化 |
| 校园授权未取得 | D 前 | 不得进入 D 阶段 |

---

## 12. 文档与交付物索引

每个阶段必须产出以下文档，归档于 `docs/`：

- `docs/hardware/gnss-capability.md`（A）
- `docs/verification/stage-a-localization.md`（A）
- `docs/calibration/campus-main-v1.yaml`（B）
- `docs/verification/stage-b-calibration.md`（B）
- `docs/api/outdoor-patrol.md`（C）
- `docs/verification/stage-c-mvp.md`（C）
- `docs/verification/stage-d-pilot.md`（D）
- `docs/runbook/outdoor-emergency.md`（D 前，应急流程）

---

## 13. 立即行动项（Next Actions）

评审通过后，优先启动以下 3 项，其余进入 backlog：

1. **【A-1】采集 GNSS 能力清单** — 阻塞后续所有阶段，优先级最高。
2. **【A-4】接入 EKF 融合定位** — 基于 `robot_localization` 软件包，输出 `/odometry/filtered`。
3. **【B-1/B-2/B-3】起草室外数据模型** — 可与 A 阶段并行，模型设计评审不依赖硬件结论。

---

## 14. 评审检查表

- [ ] 是否认同新建独立模块而非改造既有巡检表？
- [ ] 阶段闸门条件是否可接受、可验证？
- [ ] 安全门禁的"车端兜底停车"策略是否获得车端负责人认可？
- [ ] 是否已识别校内授权对接窗口期？
- [ ] 是否需要在本计划中补充人力与时间估算？（当前未包含）
