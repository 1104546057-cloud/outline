# 无预建图 RTK 室外导航

该模式与原 AMCL 地图导航互斥，不读取 PGM/YAML 静态地图。G70 输出 WGS-84，前端高德地图点位（GCJ-02）在下发前转换为 WGS-84；车端再通过 `navsat_transform_node` 的 `/fromLL` 服务转换为本地 `map` 坐标。

定位链为：G70 `/gps/fix` + `/gnss/gpgga`、IMU `/imu`、轮式里程计 `/odom` -> `robot_localization` -> `map -> odom_combined -> base_footprint`。规划链为：200 m 滚动全局代价地图 + 16 m 激光局部代价地图 -> `move_base`。

安全门槛：仅接受 `gps_qual=4`（RTK Fixed）；定位超时、Float/单点、跳点均拒绝新目标。目标执行中持续失锁超过宽限时间后，Agent 会取消目标并发布零速度。G70 的 `NavSatStatus=GBAS` 不能单独区分 Fixed/Float，因此不会作为放行条件。

上线前必须在静止、架空轮或封闭场地完成：话题名/频率、IMU 航向和 `yaw_offset`、车体 footprint、TF 唯一发布者、激光 frame、低速参数、失锁停车和急停验证。默认 footprint 与速度是保守初值，不代表已经适配实车尺寸。

本车实测 G70 为 `/dev/wheeltec_gnss -> /dev/ttyACM0`，车载网络来自独立 Quectel 4G 模块。`ntrip_rtcm_client.py` 使用现有 4G 网络连接 FindCM，将 RTCM3 直接写入 G70 USB；不要求额外购买或配置 4G DTU。它从 `/gps/nmea_sentence` 取得新鲜 GGA 回传给 NTRIP caster，并通过本地状态文件向控制 Agent 暴露连接质量。

账号密码只允许保存在车端 `/etc/devices-web-control/rtk.env`（`0640 root:wheeltec`），不经过网页、平台数据库或 WebSocket，也不得提交到 Git。复制 `findcm.env.example` 后填写真实值，确认车辆静止、天线位于室外开阔处，再启动 `DevicesWebControl-ntrip.service`。只有 `/gnss/gpgga.gps_qual=4` 才能放行 RTK 导航。

控制 Agent 也需通过 `DevicesWebControl-robot_control_server-rtk.conf` 加载同一个环境文件；将它安装到 systemd drop-in 目录后执行 `daemon-reload`。这样平台只显示“凭据已配置”，不读取或回传密文。

## WGS-84 道路采集与规划框架

道路采集由人工驾驶触发：操作员在网页点击一次“开始采集”，车端 Agent 随后从 `/gps/fix` 自动连续记录 WGS-84 轨迹；不需要逐点点击。只有新鲜的原始 GGA `gps_qual=4` 才会写入有效轨迹，失去 Fixed 时自动停止收点，恢复后继续。人工可暂停、继续、停止保存或放弃本次会话。

原始轨迹与生成后的道路网络只保存在车端 `DWC_RTK_ROAD_WORKSPACE_DIR`（默认 `/home/wheeltec/Dong/DevicesWebControl/rtk_roads`）。多次采集的支路可以合并为节点/道路边图，目标先吸附到最近道路节点，再由 A* 规划。自动驾驶必须由操作员在网页再次确认；车端会按实时位置重新规划，拒绝超过 50 米的单次路线，并在失去 RTK Fixed 时取消目标、发布零速度。

可选环境变量：

- `DWC_RTK_ROAD_WORKSPACE_DIR`：轨迹和道路网络目录。
- `DWC_RTK_ROAD_PREVIEW_POINTS`：网页预览最大点数，默认 500。
- `DWC_RTK_ROAD_RECORD_SPACING_M`：直行轨迹最小间距，默认 1.0 米。
- `DWC_RTK_ROAD_TURN_RECORD_SPACING_M`：转弯轨迹最小间距，默认 0.5 米。
- `DWC_RTK_ROAD_TURN_THRESHOLD_DEG`：触发转弯加密的航向变化阈值，默认 12 度。
- `DWC_RTK_ROAD_NETWORK_SPACING_M`：生成道路网络前的采样间距，默认 0.25 米。
- `DWC_RTK_ROAD_MERGE_RADIUS_M`：相邻轨迹节点合并半径，默认 0.75 米；必须依据道路宽度和实测结果复核。
- `DWC_RTK_ROUTE_MAX_DISTANCE_M`：单次自动路线长度上限，默认 50 米。
- `DWC_RTK_ROUTE_WAYPOINT_SPACING_M`：自动执行时的目标点间距，默认 2 米。
- `DWC_RTK_ROUTE_WAYPOINT_TIMEOUT_SEC`：单个目标点超时，默认 45 秒。
- `DWC_RTK_NAV_STARTUP_TIMEOUT_SEC`：等待 RTK 导航进程就绪的时间，默认 20 秒。
- `DWC_RTK_FROM_LL_TIMEOUT_SEC`：等待 WGS-84 到本地地图坐标转换真正可用的时间，默认 12 秒。
- `DWC_RTK_TF_READY_TIMEOUT_SEC`：发车前连续验证 `map -> odom_combined -> base_footprint` 的等待时间，默认 12 秒。
- `DWC_RTK_GPS_FRAME` 与 `DWC_RTK_GPS_OFFSET_X/Y/Z`：GNSS 天线坐标系及其相对车体中心的安装偏移；默认零偏移只等同于旧系统的“天线在车体原点”假设，正式厘米级验收前必须实测填写。
