# agent/ros — 校园室外巡检阶段 A 车端能力

本目录新增的文件用于需求 `docs/requirements/campus-outdoor-autonomous-patrol.md` 阶段 A 的「硬件与定位可行性」验证。

## 文件清单

```
agent/ros/
├── probe_gnss.py              # GNSS 能力探测脚本（A-1）
├── localization_health.py     # 定位健康度评估节点（FR-01）
├── docs/
│   └── gnss_capability_template.md   # 能力清单模板（A-1）
├── launch/
│   └── outdoor_localization.launch   # EKF 融合定位启动（A-4）
└── config/
    └── outdoor_ekf.yaml              # EKF 参数配置（A-4）
```

## 阶段 A 启动流程

### 1. GNSS 能力探测（A-1，闸门 A 关键证据）

车端启动底盘 + GNSS 驱动后，运行：

```bash
python3 probe_gnss.py --duration 60 --out /tmp/gnss_report.json
```

输出 JSON 包含：实际话题、刷新率、fix 状态分布、协方差统计、初步闸门判定。
然后将结果填入 `docs/gnss_capability_template.md`，归档到 `docs/hardware/gnss-capability.md`。

### 2. 启动 EKF 融合定位（A-4）

前置：

```bash
sudo apt install ros-noetic-robot-localization
```

启动（假设本目录已加入 ROS workspace）：

```bash
roslaunch outdoor_localization.launch \
  base_link_frame:=base_link \
  use_gps:=true
```

启动后会发布：

| 话题 | 类型 | 说明 |
| --- | --- | --- |
| `/odometry/filtered` | nav_msgs/Odometry | 融合位姿（map 系） |
| `/tf` | tf2_msgs/TFMessage | map→odom→base_link |
| `/localization/health` | std_msgs/Bool | 定位健康度（latched） |
| `/localization/diagnostics` | diagnostic_msgs/DiagnosticArray | 详细诊断 |

### 3. 参数现场标定清单

`outdoor_ekf.yaml` 与 launch 中以下参数需在现场标定：

- `navsat_transform.magnetic_declination_radians` — 校园所在地的磁偏角
- `navsat_transform.yaw_offset` — IMU 安装偏航角
- `process_noise_covariance` — 阶段 A 用默认值，阶段 B 根据数据调整
- `localization_health.max_gnss_age_seconds` 等 — 见 `backend/config/outdoor_thresholds.py`

## 安全说明

- 所有新增节点均为**订阅 / 发布**节点，不直接发布 `/cmd_vel`。
- 控制指令仍由 `robot_control_server.py` 统一处理，符合需求 §6.1 的边界。
- `localization_health` 仅输出布尔标志，具体停车动作由任务编排层响应。

## 已知遗留

- [ ] `localization_health.py` 的协方差判定当前使用 GNSS 协方差近似，阶段 B 应切换到 `/odometry/filtered.pose.covariance` 的真实 trace。
- [ ] `outdoor_localization.launch` 假设 ROS workspace 包名为 `devices_web_control`，实际接入时需要在车端 workspace 中创建对应包链接。
- [ ] `navsat_transform_node` 的 `magnetic_declination_radians` 需要现场查表填写（例：北京约 -6.5° = -0.113 rad）。
