# DevicesWebControl 运行与无人车接入说明

本项目是智慧校园巡逻管理系统，包含本地 Web 管理平台、FastAPI 后端、React 前端，以及部署在无人车上的 Agent。无人车采用主动连接模式：平台先创建设备并生成 Token，车端 Agent 再使用同一个 Token 上报遥测、接收控制指令并上传媒体流。

## 目录结构

```text
DevicesWebControl/
├─ backend/      # FastAPI 后端、数据库模型、设备与遥测接口
├─ frontend/     # React + Vite 前端
├─ agent/
│  ├─ ros/       # ROS1 Wheeltec 无人车端 Agent
│  └─ common/    # 非 ROS 树莓派 / Nano 小车端 Agent
└─ README.md
```

## 创建运行环境

下面假设已经安装好 Conda、Node.js、MySQL。这里不展开这些软件本身的安装过程，只说明本项目需要执行的命令。

在项目根目录创建并进入后端 Python 环境：

```powershell
cd DevicesWebControl
conda create -n DevicesWebControl python=3.12 -y
conda activate DevicesWebControl
```

安装后端 Python 依赖：

```powershell
cd backend
python -m pip install -r requirements.txt
```

如果还没有后端配置文件，从示例文件复制一份：

```powershell
cp .env.example .env
```

安装前端依赖：

```powershell
cd ../frontend
npm install
```

如果还没有前端配置文件，从示例文件复制一份：

```powershell
cp .env.example .env
```

## 配置 MySQL 和环境变量

假设本机已经安装并启动 MySQL，可以先创建项目数据库和账号：
以xxx为例

```sql
CREATE DATABASE devices_web_control DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'dwc'@'localhost' IDENTIFIED BY 'dwc@123';
GRANT ALL PRIVILEGES ON devices_web_control.* TO 'dwc'@'localhost';
CREATE USER 'dwc'@'127.0.0.1' IDENTIFIED BY 'dwc@123';
GRANT ALL PRIVILEGES ON devices_web_control.* TO 'dwc'@'127.0.0.1';
FLUSH PRIVILEGES;
```

实际业务表不需要手写 SQL，后面执行 `backend/init_db.py` 会自动创建用户表、设备表、遥测表、巡检表等项目表结构。

确认 `backend/.env` 中的数据库连接信息与上面的 MySQL 设置一致：

```env
DB_USER=dwc
DB_PASSWORD=dwc@123
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=devices_web_control
```

这些参数的含义如下：

```text
DB_USER        后端连接 MySQL 使用的用户名
DB_PASSWORD    后端连接 MySQL 使用的密码
DB_HOST        MySQL 地址，本机运行通常写 127.0.0.1
DB_PORT        MySQL 端口，默认 3306
DB_NAME        本项目使用的数据库名
```

如果前端地图页面需要正常显示地图，确认 `frontend/.env` 中已有：

```env
VITE_AMAP_API_KEY=你的高德 Key
VITE_AMAP_API_SECURE_KEY=你的高德安全密钥
```

这些参数的含义如下：

```text
VITE_AMAP_API_KEY          前端加载高德地图 SDK 使用的 Key
VITE_AMAP_API_SECURE_KEY   高德地图 Web 端安全密钥
```

在 `backend/.env` 中配置平台对车端暴露的实际入口：

```env
PUBLIC_SERVER_URL=http://<平台IP或域名>:5273
```

`PUBLIC_SERVER_URL` 是平台对车端暴露的统一入口。这里不要照抄示例，必须填写无人车或小车能够访问到的平台机器 IP、域名和端口。添加设备后，后端会把这个地址返回给前端，用来提示车端 `iot_client.conf` 应填写的 `server`。

## 初始化数据库

首次运行或数据库表结构缺失时，在 `backend` 目录执行：

```powershell
cd DevicesWebControl/backend
conda activate DevicesWebControl
python init_db.py
```

默认管理员账号由 `backend/.env` 控制；如果没有改过，默认是：

```text
用户名：admin
密码：admin123
```

## 启动后端

在 `backend` 目录执行：

```powershell
cd DevicesWebControl/backend
conda activate DevicesWebControl
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 1
```

后端健康检查地址：

```text
http://127.0.0.1:8000/api/health
```

## 启动前端

在另一个终端进入 `frontend` 目录：

```powershell
cd DevicesWebControl/frontend
npm run dev
```

前端默认访问地址：

```text
http://localhost:5273
```

Vite 开发服务器会把 `/api` 请求和 WebSocket 转发到 `http://127.0.0.1:8000`，所以开发时浏览器访问 `5273` 端口即可。

## 添加无人车并获取 Token

1. 打开 `http://localhost:5273`。
2. 使用管理员账号登录。
3. 进入设备管理页面，添加一台设备，类型选择无人车。
4. 平台会生成设备 Token，并显示服务器地址。
5. 记录这两个值：

```text
server = http://<平台IP或域名>:5273
token  = 平台生成的设备 Token
```

同一个 Token 会同时用于遥测上报、控制通道和媒体通道。

## 选择车端 Agent

车端 Agent 分两套：

```text
agent/ros/       ROS1 Wheeltec 无人车，控制走 ROS /cmd_vel，媒体走 ROS Gemini 相机服务
agent/common/    非 ROS 树莓派 / Nano 小车，控制走串口，媒体走 USB 摄像头 MJPEG 流
```

如果车上运行的是 Wheeltec ROS1 底盘，使用 `agent/ros`。如果车上没有 ROS，只是树莓派或 Jetson Nano 通过串口控制底盘，使用 `agent/common`。

## 配置非 ROS 小车 Agent

非 ROS 小车使用 `agent/common` 目录中的文件。将该目录中的核心文件放到小车工作目录。下面用 `/path/to/DevicesWebControl` 表示车端实际存放目录：

```text
/path/to/DevicesWebControl
```

车端至少需要包含这些文件：

```text
iot_client.conf
iot_client.py
robot_control_server.py
start_camera.sh
deploy.sh
```

编辑车端 `iot_client.conf`：

```ini
[client]
server   = http://<平台IP或域名>:5273
token    = 平台生成的设备 Token
```

必要参数只有这两个：

```text
server                   小车能访问到的平台入口，填写实际平台 IP、域名和端口
token                    平台给这台设备生成的 Token，用于遥测、控制和媒体通道鉴权
```

非 ROS 控制 Agent 默认通过串口 `/dev/ttyACM0`、波特率 `115200` 给底盘发送速度包；如果实际底盘串口不同，需要改 `agent/common/robot_control_server.py` 中的 `SERIAL_PORT` 和 `BAUDRATE`。

## 启动非 ROS 小车服务

在树莓派或 Jetson Nano 小车上进入工作目录：

```bash
cd /path/to/DevicesWebControl
sudo ./deploy.sh
```

脚本会配置并启动这些 systemd 服务：

```text
DevicesWebControl-robot_control_server.service
DevicesWebControl-iot_client.service
DevicesWebControl-camera.service
```

如果只是临时调试，也可以手动启动：

```bash
cd /path/to/DevicesWebControl
python3 iot_client.py --config iot_client.conf
```

控制与媒体通道由 `robot_control_server.py` 提供：

```bash
cd /path/to/DevicesWebControl
python3 robot_control_server.py --config iot_client.conf
```

非 ROS 小车连接成功后，平台可以看到遥测、GPS、CPU、内存、磁盘、网络、USB、可选 Jetson GPU 信息，并可通过控制页面下发前进、后退、转向、停止等速度控制指令。

## 配置 ROS1 无人车 Agent

车端使用 `agent/ros` 目录中的文件。将该目录中的核心文件放到无人车工作目录。下面同样用 `/path/to/DevicesWebControl` 表示车端实际存放目录：

```text
/path/to/DevicesWebControl
```

车端至少需要包含这些文件：

```text
iot_client.conf
iot_client.py
robot_control_server.py
ros_camera_server.py
rosconsole_camera.config
start_camera.sh
deploy.sh
```

编辑车端 `iot_client.conf`：

```ini
[client]
server   = http://<平台IP或域名>:5273
token    = 平台生成的设备 Token
```

必要参数只有这两个：

```text
server     无人车能访问到的平台入口，填写实际平台 IP、域名和端口
token      平台给这台设备生成的 Token，用于遥测、控制和媒体通道鉴权
```

ROS1 Agent 还可以通过环境变量调整运行细节，常见配置如下：

```text
ROS_MASTER_URI           ROS Master 地址，默认 http://localhost:11311
DWC_ROS_IP               当前车端 ROS 节点对外声明的 IP，单机 ROS 通常用 127.0.0.1
DWC_GPS_TOPIC            定位话题，默认 /gps/fix
DWC_GPS_STALE_SEC        GPS 数据过期时间，超过该秒数未更新则认为定位失效
DWC_SLAM_MAP_DIR         导航地图目录，默认是车端工作目录下的 slam_map
DWC_ROS_SETUP            ROS setup.bash 路径，默认 /opt/ros/noetic/setup.bash
DWC_LIDAR_SETUP          雷达工作空间 setup.bash 路径
DWC_WHEELTEC_SETUP       Wheeltec 底盘工作空间 setup.bash 路径
```

## 启动车端服务

在 ROS1 Wheeltec 无人车上进入工作目录：

```bash
cd /path/to/DevicesWebControl
sudo ./deploy.sh
```

脚本会配置并启动这些 systemd 服务：

```text
turn_on_wheeltec_robot.service
DevicesWebControl-robot_control_server.service
DevicesWebControl-g70.service
DevicesWebControl-iot_client.service
DevicesWebControl-camera.service
```

如果只是临时调试，也可以手动启动主要 Agent：

```bash
source /opt/ros/noetic/setup.bash
source ~/wheeltec_robot/devel/setup.bash
cd /path/to/DevicesWebControl
python3 iot_client.py --config iot_client.conf
```

控制与媒体通道由 `robot_control_server.py` 提供：

```bash
source /opt/ros/noetic/setup.bash
source ~/wheeltec_robot/devel/setup.bash
cd /path/to/DevicesWebControl
python3 robot_control_server.py --config iot_client.conf
```

## 确认无人车已连接

平台侧确认：

1. 打开前端设备管理页面。
2. 对应无人车状态显示为在线。
3. 设备详情中能看到最近上报时间、电量、GPS、CPU、内存等遥测信息。
4. 控制页面能进入无人车控制或视频页面。

车端确认：

```bash
systemctl status DevicesWebControl-iot_client
systemctl status DevicesWebControl-robot_control_server
systemctl status DevicesWebControl-camera
```

查看实时日志：

```bash
journalctl -u DevicesWebControl-iot_client -f
journalctl -u DevicesWebControl-robot_control_server -f
journalctl -u DevicesWebControl-camera -f
```

常见正常日志包括：

```text
遥测上报成功
控制通道已连接
媒体通道已连接
ROS /cmd_vel Publisher 已就绪
```

## 常见问题

如果前端看不到设备在线，先检查：

- `iot_client.conf` 的 `server` 是否是无人车能访问到的地址。
- `token` 是否和平台设备 Token 完全一致。
- 平台前端 `5273` 端口和后端 `8000` 端口是否都在运行。
- 无人车或小车与平台电脑是否在同一网络或路由可达。

如果设备在线但不能控制，检查：

- `DevicesWebControl-robot_control_server.service` 是否正在运行。
- ROS 车检查 `turn_on_wheeltec_robot.service` 是否正在运行，ROS 图中 `/cmd_vel` 是否有底盘节点订阅。
- 非 ROS 小车检查底盘串口是否为 `/dev/ttyACM0`，以及运行服务的用户是否有串口访问权限。

如果没有 GPS 或电量数据，检查：

- ROS 车检查 `DevicesWebControl-g70.service` 是否正在运行，ROS 中是否存在 `/gps/fix`、`/PowerVoltage`、`/odom`、`/imu` 等话题。
- 非 ROS 小车检查 GPS 设备是否接入、串口和波特率是否与实际模块一致。

如果视频不可用，检查：

- `DevicesWebControl-camera.service` 是否正在运行。
- 车端本地 `http://127.0.0.1:8080/?action=stream&view=color` 是否能提供视频流。
- 非 ROS 小车的 USB 摄像头流地址通常是 `http://127.0.0.1:8080/?action=stream`。
