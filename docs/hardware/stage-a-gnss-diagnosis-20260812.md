# 阶段 A GNSS 实地诊断报告

- **日期**：2026-08-12 17:48–18:00（GMT+8）
- **车端**：wheeltec · 192.168.31.202 · Ubuntu 20.04.6 · 内核 5.10.216-tegra（Jetson 平台）
- **操作人**：远程 SSH（wheeltec 用户）
- **结论**：**闸门 A 阻塞** — 当前 GNSS 硬件链路无定位输出，须先解决硬件/天线问题再继续。

## 1. 硬件事实

| 项目 | 值 | 来源 |
| --- | --- | --- |
| GNSS 模块 | **u-blox AG**，USB ID `1546:01a9`（USB CDC ACM 类） | `lsusb` |
| 推测型号 | u-blox M8 系列（多星座，支持 RTK 的具体型号待确认） | GNGGA 前缀为 GN（多星座），非 GP |
| 设备节点 | `/dev/ttyACM0`（udev 别名 `/dev/wheeltec_gnss`） | `readlink -f` |
| 驱动波特率 | 9600（NMEA 默认） | `rosparam get /nmea_serial_driver_node` |
| 当前驱动进程 | PID 10111 `nmea_serial_driver`，由 `wheeltec_nmea_driver.launch` 启动 | `ps` |

## 2. ROS 话题事实

| 话题 | 类型 | 频率 | 数据 |
| --- | --- | --- | --- |
| `/gps/fix` | sensor_msgs/NavSatFix | ≈5 Hz | `status=-1 (NO_FIX), lat=nan, lng=nan` |
| `/gps/nmea_sentence` | nmea_msgs/Sentence | **稳定 5.0 Hz** | 持续输出空 GGA（每 0.2 秒一条） |
| `/imu` | sensor_msgs/Imu | 约 50 Hz | 正常输出（orientation/angular_velocity/linear_acceleration） |
| `/odom` | nav_msgs/Odometry | 约 10 Hz | 正常输出（frame_id=odom_combined） |
| `/scan` | sensor_msgs/LaserScan | 已存在 | 未采样 |
| `/heading`, `/heading_deg` | 已存在 | 未采样 | 说明系统配置了某种航向输出（可能为双天线 RTK 预留） |

## 3. NMEA 句子分析

采集 30 秒原始 NMEA 输出：

```
$GNGGA,,,,,,0,00,99.99,,,,,,*56    × 146 条
```

- **唯一出现的句子类型**：`GNGGA`（共 146 条 / 30 秒）
- **完全缺失**：`GSV`（卫星视野）、`GSA`（精度因子）、`RMC`（推荐最小定位）、`VTG`（速度航向）、`GGL`、`ZDA`
- **GGA 字段解读**：
  - 字段 2–5（纬度、N/S、经度、E/W）全空
  - 字段 6 **fix quality = 0**（无定位）
  - 字段 7 **卫星数 = 00**
  - 字段 8 **HDOP = 99.99**（最差值）
  - 字段 9–11（海拔、单位、地球大地水准面高度）全空

**初步判定**：u-blox 模块**收到 NMEA 输出任务并按时输出**，但**内部没有解算任何卫星**。这种"只输出空 GGA"通常对应下列硬件状态之一：

1. **天线未连接或损坏** — u-blox 没接天线时通常会这样
2. **天线被金属遮挡** — 车体金属罩、密封舱内、地下室等
3. **u-blox 配置丢失或处于某种保护模式** — u-blox 内部参数被擦除后可能只保留 GGA 输出
4. **供电不足** — 部分 USB Hub 供电不足会导致 u-blox 不工作但 USB 通讯仍维持

## 4. 同时刻运行的相关进程

```
PID 9838  roslaunch wheeltec_gps_driver wheeltec_nmea_driver.launch
PID 10111 nmea_serial_driver_node → 占用 /dev/ttyACM0
PID 18878 iot_client.py（已订阅 /gps/fix 上报后端）
PID 19493 navigation.launch（导航栈在跑）
```

注：`/diagnostics` 当前由 amcl 报告"标准差过大"，符合室内无 GPS 定位的预期。

## 5. 闸门 A 评估

按 `docs/plans/campus-outdoor-autonomous-patrol-plan.md` §2.3 退出闸门：

| 条件 | 状态 |
| --- | --- |
| GNSS 能力清单已归档 | **部分完成**（本报告归档了硬件型号，但缺 RTK 能力实测） |
| `/odometry/filtered` 稳定输出 | **未实现** — robot_localization 未安装，且 GNSS 无定位无法融合 |
| 三区定位样本采集 | **未启动** — 须先恢复 GNSS fix |
| `outdoor_localization` 上报持久化 | **未启动** |

**结论**：**闸门 A 阻塞**，按计划 §2.3 失败回退规则执行：
> 若硬件无 RTK：停止本计划，重新评估是否改用纯激光 SLAM + 视觉里程计方案。
> 若融合发散：先排查 TF 与单位（度/弧度），必要时切换融合软件包。

本次阻塞属于"硬件无任何定位输出"，**在物理问题解决前无法判定是否支持 RTK**。

## 6. 现场排查行动项（按优先级）

下列项目需要现场人员介入，软件开发在此期间暂停阶段 A 推进。

### 优先级 P0：物理层确认

- [ ] **检查 GNSS 天线物理连接**
  - 天线 SMA/MCX 接头是否松动或脱落
  - 天线是否安装在车顶正中且无金属遮挡
  - 天线馈线有无破损、折弯
- [ ] **天线环境检查**
  - 当前车辆是否在室内 / 地下室 / 飞机棚内？（高灵敏度 GNSS 室内搜不到星）
  - 把车辆推到开阔室外（看到天空面积 > 50%），重启 u-blox 供电，等待冷启动 60–120 秒
- [ ] **天线工作指示灯**
  - u-blox 模块上通常有 **GPS LED**，闪烁表示在工作，常亮或常灭需要查 u-blox 数据手册

### 优先级 P1：u-blox 配置诊断

- [ ] **用 u-blox u-center 软件直接连模块**（Windows PC 接 USB）
  - 查 Power Management、Satellite Fix、Constellation 配置
  - 看 PCONFIG 是否完整，必要时恢复出厂并重新配置
- [ ] **波特率核对**
  - 当前驱动用 9600，但 RTK 高刷新率模式通常配置为 38400 或 460800
  - 试运行 `screen /dev/ttyACM0 38400` 看是否能拿到完整 NMEA 句子集
- [ ] **检查是否误启了 dual_rtk 配置但只接了一根天线**

### 优先级 P2：驱动层切换

车端 `/home/wheeltec/wheeltec_robot/src/wheeltec_gps/wheeltec_gps_driver/launch/` 下存在多种 launch 文件：

| 文件 | 适用 |
| --- | --- |
| `wheeltec_nmea_driver.launch`（当前运行） | 普通 NMEA 模式，9600 |
| `wheeltec_ublox_driver.launch` | u-blox 专用驱动（ublox_gps 软件包），配置文件 `ublox_serial_driver.yaml` |
| `nmea_gps_path.launch` | 带 GPS path 轨迹输出 |
| `unicore_gps_path_dualrtk.launch` | Unicore 双天线 RTK |
| `wheeltec_dual_rtk_driver_nmea.launch` | 双天线 RTK NMEA 模式 |
| `ublox_gps_path.launch` | u-blox 专用 + path 输出 |

**建议**：先用 `wheeltec_ublox_driver.launch` 替换当前 `wheeltec_nmea_driver.launch`，因为它使用 ublox_gps 驱动包，能正确读取 u-blox 二进制协议（UBX），比通用 NMEA 驱动提供更完整的诊断信息（可见卫星数、信号强度、RTK 状态字节）。

切换命令（现场执行，需先停当前驱动）：

```bash
# 1. 停当前 GNSS 驱动
kill 9838 10111

# 2. 启 ublox 专用驱动（需要预先检查 ublox_serial_driver.yaml 端口配置）
source /opt/ros/noetic/setup.bash
source /home/wheeltec/wheeltec_robot/devel/setup.bash
roslaunch wheeltec_gps_driver wheeltec_ublox_driver.launch
```

### 优先级 P3：采集补全

天线恢复 fix 之后，立即采集以下数据：

- [ ] 用 `agent/ros/probe_gnss.py` 跑 30 分钟，覆盖开阔区 / 树荫区 / 楼宇边缘
- [ ] 录 rosbag，包含 `/gps/fix`、`/imu`、`/odom`，作为后续阶段 A-4 EKF 调参的离线输入
- [ ] 在 `gnss_capability_template.md` 中填齐所有"待确认"字段，作为闸门 A 最终证据

## 7. 后续软件工作可继续推进的部分

GNSS 物理问题排查期间，软件侧这些工作不依赖实测数据，可以并行推进：

| 任务 | 说明 |
| --- | --- |
| B-4 坐标转换服务 `coord_transform.py` | WGS84↔ENU 数学公式独立，单元测试可用模拟坐标 |
| B-7/B-8 前端路线管理页面骨架 | UI 与数据模型不依赖现场 |
| C-2 预检接口骨架 | 接口契约已定，可实现 mock 版本 |
| `localization_health.py` 车端集成测试脚本 | 可在无 GPS 信号时验证"健康度判定为 false"的逻辑 |

## 8. 原始证据留存

- 本诊断的所有命令输出截图与日志详见对话上下文
- 关键证据摘要：
  - `lsusb` 显示 `1546:01a9 U-Blox AG`（设备在线）
  - 30 秒 NMEA 仅含 146 条空 GGA，无其它句子类型
  - `/gps/fix` 持续 `status=-1, lat=nan, lng=nan`
  - 驱动 PID 10111 正确绑定 `/dev/ttyACM0`（驱动无错）
