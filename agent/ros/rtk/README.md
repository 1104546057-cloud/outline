# 无预建图 RTK 室外导航

该模式与原 AMCL 地图导航互斥，不读取 PGM/YAML 静态地图。G70 输出 WGS-84，前端高德地图点位（GCJ-02）在下发前转换为 WGS-84；车端再通过 `navsat_transform_node` 的 `/fromLL` 服务转换为本地 `map` 坐标。

定位链为：G70 `/gps/fix` + `/gnss/gpgga`、IMU `/imu`、轮式里程计 `/odom` -> `robot_localization` -> `map -> odom_combined -> base_footprint`。规划链为：200 m 滚动全局代价地图 + 16 m 激光局部代价地图 -> `move_base`。

安全门槛：仅接受 `gps_qual=4`（RTK Fixed）；定位超时、Float/单点、跳点均拒绝新目标。目标执行中持续失锁超过宽限时间后，Agent 会取消目标并发布零速度。G70 的 `NavSatStatus=GBAS` 不能单独区分 Fixed/Float，因此不会作为放行条件。

上线前必须在静止、架空轮或封闭场地完成：话题名/频率、IMU 航向和 `yaw_offset`、车体 footprint、TF 唯一发布者、激光 frame、低速参数、失锁停车和急停验证。默认 footprint 与速度是保守初值，不代表已经适配实车尺寸。

本车实测 G70 为 `/dev/wheeltec_gnss -> /dev/ttyACM0`，车载网络来自独立 Quectel 4G 模块。`ntrip_rtcm_client.py` 使用现有 4G 网络连接 FindCM，将 RTCM3 直接写入 G70 USB；不要求额外购买或配置 4G DTU。它从 `/gps/nmea_sentence` 取得新鲜 GGA 回传给 NTRIP caster，并通过本地状态文件向控制 Agent 暴露连接质量。

账号密码只允许保存在车端 `/etc/devices-web-control/rtk.env`（`0640 root:wheeltec`），不经过网页、平台数据库或 WebSocket，也不得提交到 Git。复制 `findcm.env.example` 后填写真实值，确认车辆静止、天线位于室外开阔处，再启动 `DevicesWebControl-ntrip.service`。只有 `/gnss/gpgga.gps_qual=4` 才能放行 RTK 导航。

控制 Agent 也需通过 `DevicesWebControl-robot_control_server-rtk.conf` 加载同一个环境文件；将它安装到 systemd drop-in 目录后执行 `daemon-reload`。这样平台只显示“凭据已配置”，不读取或回传密文。
