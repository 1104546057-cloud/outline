# RTK 实时导航开发完整交接说明（Cursor 接手版）

> 项目：室外巡检车 `DevicesWebControl`
>
> 整理日期：2026-08-31（Asia/Shanghai）
>
> 本地仓库：`C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl`
>
> 当前分支：`zndong-e8aace8-deploy`
>
> 当前 HEAD：`4f97ba9`（2026-08-25）
> 重要状态：RTK 道路采集、道路网络、地图选点、A* 规划、自动路线执行及两轮现场修复都在**未提交工作区**中。不要把“HEAD 较旧”误判为功能不存在，更不要执行 `git reset --hard`、`git checkout -- .` 或整目录覆盖。

## 1. 给 Cursor 的首要指令

接手后请先完整阅读本文，再检查真实代码和当前差异。以下边界必须遵守：

1. 先执行 `git status --short`、`git diff --stat` 和针对目标文件的 `git diff`，保护用户已有修改和未跟踪文件。
2. 不要为了“清理仓库”而重置、删除或覆盖当前工作区；这里的 RTK 新功能大部分尚未形成 Git 提交。
3. 车是实车，不得仅凭网页显示“Agent 已连接”就发送速度、导航目标、启动 RTK/NTRIP、重启底盘或移动车辆。
4. 对实车的默认动作是只读检查。任何会导致运动的操作都必须得到用户当次明确授权，并先确认车辆身份、现场有人监护、急停可用、车前方安全、速度为零。
5. 车端系统使用 Python 3.8，类型注解不能使用 Python 3.9 才支持的 `tuple[...]`、`list[...]` 形式；车端新增代码应使用 `typing.Tuple`、`typing.List` 等兼容写法。
6. 账号、密码、NTRIP 凭据只放车端 `/etc/devices-web-control/rtk.env`，不得写入 Git、网页、平台数据库、WebSocket 消息、日志或本文档。
7. 必须区分三个结论：
   - 代码完成：静态检查和单元测试通过。
   - 已部署：文件和服务已更新。
   - 实车验收通过：室外 Fixed、TF、激光、局部规划和真实运动均验证通过。
8. 当前只能确认前两项的大部分内容；**最后一轮 TF 修复后尚未完成实车自动驾驶闭环验收**，不能对外宣称“厘米级自动导航已经验收完成”。

## 2. 需求起点和最终方案

### 2.1 原始问题

高德地图在中国大陆使用 GCJ-02 坐标。车辆 G70/FindCM RTK 输出的是 WGS-84。若直接把高德页面点击位置当作 RTK 目标，会产生明显坐标偏移，无法发挥厘米级 RTK 的优势。

用户最初希望换成 Google 地图，但这并不能自动解决校园内部道路、禁行区、路口拓扑和车辆可通行性问题。卫星图只是影像，不知道车能否穿过台阶、绿化、建筑或狭窄区域。最终采用的工程方案是：

- 前端用 MapLibre GL JS 作为地图渲染器。
- 页面交互坐标统一为 WGS-84。
- 当前测试底图为 Esri World Imagery 卫星瓦片，可通过环境变量替换为合法授权的 WGS-84 底图或自建正射影像。
- 先由操作员在 RTK Fixed 状态下人工驾驶采集校园道路中心线。
- 将一条或多条实测轨迹生成车辆专用道路网络。
- 用户在地图上点击目标，系统把目标吸附到最近道路节点，再用 A* 沿实测道路规划。
- 操作员确认后，车端依据实时 RTK 位置重新规划，并将 WGS-84 路径转换为本地 `map` 坐标，逐点交给 `move_base` 执行。

这套方案不依赖高德坐标，也不是让车辆每次都手工定制路线。人工采集只用于建立和扩充一次性道路资产；道路网络成熟后，日常操作就是地图选点、规划、确认、执行。

### 2.2 MapLibre 是什么

MapLibre 不是卫星地图供应商，它是开源地图渲染引擎。它负责显示瓦片、轨迹、节点、路径和响应点击；真正的影像来自配置的瓦片服务。

当前前端默认配置：

```env
VITE_RTK_MAP_STYLE_URL=
VITE_RTK_RASTER_TILE_URL=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}
VITE_RTK_RASTER_ATTRIBUTION=Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community
VITE_RTK_MAP_PROVIDER_NAME=Esri World Imagery WGS-84 卫星底图
VITE_RTK_DIRECT_GOAL_MAX_DISTANCE_M=10
VITE_RTK_ROAD_NETWORK_MAX_SNAP_M=5
```

配置文件：`frontend/.env.rtk.example`。

曾尝试 OpenStreetMap 公共瓦片，但现场浏览器出现 `Failed to fetch https://tile.openstreetmap.org/...`，因此切换到 Esri World Imagery。公共瓦片的可访问性、授权和并发限制都不应被视作生产保障。

### 2.3 坐标精度的正确理解

- MapLibre 的点击经纬度是 WGS-84。
- G70/FindCM 和采集道路也是 WGS-84。
- 规划和车辆控制使用采集点的数值坐标，不从卫星图片像素反算路线。
- 卫星影像自身可能存在米级拼接或绝对定位误差，所以影像只能辅助观察，不能作为厘米级控制基准。
- 点击目标会吸附到实测道路网络；吸附后执行的是实测 WGS-84 道路坐标，而不是影像上看起来的道路中心。
- 正式厘米级验收还必须测量 GNSS 天线相对 `base_footprint` 的杆臂偏移，当前默认 `0,0,0` 只是兼容旧系统的临时假设。

## 3. 整体架构和通信链

```text
浏览器 / React / MapLibre
        |
        | HTTPS REST（认证后）
        v
公网服务器 FastAPI
        |
        | Remote Access WebSocket 命令/响应
        v
车端 robot_control_server.py（Agent）
        |
        +--> G70 /gps/fix + /gnss/gpgga
        +--> FindCM NTRIP -> RTCM3 -> /dev/wheeltec_gnss
        +--> IMU /imu
        +--> 轮式里程计 /odom
        +--> 激光 /scan
        |
        +--> robot_localization / navsat_transform_node
        |       map -> odom_combined -> base_footprint -> navsat_link
        |
        +--> move_base + GlobalPlanner + DWAPlannerROS
                |
                +--> /cmd_vel -> 底盘
```

已知部署拓扑：

- 公网服务器：`huyunfeng@8.134.135.58`
- 公网应用：`https://8.134.135.58:52734`
- 服务器项目目录：`/home/huyunfeng/projects/DevicesWebControl`
- 服务器服务：`outdoor-deviceswebcontrol.service`
- 车端通过既有 Remote Access 链路连接，车端目标最终为 `wheeltec@127.0.0.1:22`
- 车端项目目录：`/home/wheeltec/Dong/DevicesWebControl`
- 车端 Agent：`DevicesWebControl-robot_control_server.service`
- 相关车端服务：`DevicesWebControl-g70.service`、`DevicesWebControl-ntrip.service`、`turn_on_wheeltec_robot.service`

注意：服务器网页正常、TCP 端口可达、Agent 显示连接，都不能单独证明车端 ROS、G70、NTRIP、TF、激光或导航可用。每层必须独立验证。

## 4. RTK 定位和安全门槛

### 4.1 定位链

目标定位链：

```text
G70 /gps/fix + 原始 GGA /gnss/gpgga
IMU /imu
轮式里程计 /odom
        |
        v
navsat_transform_node + global EKF
        |
        v
map -> odom_combined -> base_footprint
```

`dwc_rtk_navigation.launch` 同时启动：

- `dwc_base_to_navsat` 静态 TF。
- `dwc_navsat_transform`。
- `dwc_rtk_global_ekf`。
- `move_base`。

局部代价地图使用激光 `/scan`，全局和局部代价地图都是 rolling window，不依赖预先制作的 PGM/YAML 静态地图。

### 4.2 Fixed 判定

放行条件不是“收到 GPS”或 `NavSatStatus=GBAS`，而是新鲜的原始 GGA：

- `gps_qual == 4` 才是 RTK Fixed。
- `/gps/fix` 默认超过 2 秒视为过期。
- GGA 默认超过 2 秒视为过期。
- 位置跳变至少 1 米且推算速度超过 3 m/s 时锁定为异常。
- 跳变后默认需要 3 个稳定 Fix 才恢复。
- 执行中连续失去有效 RTK 超过 1 秒，会取消目标并发布零速度。

相关实现：`agent/ros/rtk_navigation_core.py` 的 `RtkHealthTracker`，以及 `robot_control_server.py` 的 `rtk_safety_loop()`。

## 5. 道路采集完整流程

### 5.1 操作方式

采集页面把以下功能放在同一个界面：

- 实时前置摄像头。
- 人工方向控制九宫格。
- 速度倍率滑块和 `-5%` / `+5%` 微调。
- 开始、暂停、继续、停止并保存、放弃本次。
- 当前采集轨迹、点数、距离、Fixed/拒绝点统计。
- 已保存轨迹和道路网络显示。

组件为 `frontend/src/components/RtkSurveyCockpit.jsx`，主页面为 `frontend/src/pages/OutdoorRtkNavigation.jsx`。

操作员只需点击一次“开始采集”，随后人工驾驶。车端从 RTK 回调自动记录点，不需要边开车边逐点点击。

### 5.2 采样规则

当前规则：

- 直行最小点间距：1.0 m。
- 转弯最小点间距：0.5 m。
- 转弯判定阈值：航向变化 12°。
- 只有新鲜 `gps_qual=4` 才计入有效轨迹。
- 失去 Fixed 时保留会话但停止收有效点，恢复后可继续。

这些参数来自：

```env
DWC_RTK_ROAD_RECORD_SPACING_M=1.0
DWC_RTK_ROAD_TURN_RECORD_SPACING_M=0.5
DWC_RTK_ROAD_TURN_THRESHOLD_DEG=12.0
```

用户曾反馈 0.5 m 全程采一点过密，因此改为“直行 1 m、转弯 0.5 m”。不要把“1 m/s”误写成采样间距；用户口头表达的实际落地配置是每 1 m 记录一点，代码按距离采样。

### 5.3 数据保存

默认车端目录：

```text
/home/wheeltec/Dong/DevicesWebControl/rtk_roads
```

由 `DWC_RTK_ROAD_WORKSPACE_DIR` 覆盖。数据由 `agent/ros/rtk_road_network.py` 中的 `RoadWorkspace` 管理，并使用原子 JSON 写入。

用户点击“停止并保存”后，轨迹没有丢失。页面需要重新拉取轨迹列表并选中对应轨迹/网络才能显示；早期曾出现“保存后看不到点”，后来补充了轨迹和网络的显示逻辑。

一次现场数据示例是约 401 个采集点、410.1 m；由所选轨迹生成的网络示例是 275 个节点、281 条边。这只是当次现场数据，不是代码常量。

## 6. 道路网络、目标吸附和 A* 规划

### 6.1 生成网络

用户选择一条或多条已保存轨迹，点击生成道路网络。`RoadWorkspace.build_network()` 会：

1. 按 `DWC_RTK_ROAD_NETWORK_SPACING_M` 重新采样，默认 0.25 m。
2. 在 `DWC_RTK_ROAD_MERGE_RADIUS_M` 内合并邻近节点，默认 0.75 m。
3. 按轨迹顺序建立道路边。
4. 持久化网络并返回节点、边和预览数据。

多次采集的支路可以合并，但十字路口、双向道路、相邻平行道路的误合并必须现场复核。当前还没有完整的车道方向、道路宽度、禁行区和转向限制模型。

### 6.2 地图选点和规划

用户在 MapLibre 地图上点击目标：

1. 前端取得 WGS-84 经度和纬度。
2. 请求 `/api/navigation/rtk/roads/plan`。
3. 车端以实时当前位置为起点。
4. 起点和目标都吸附到道路网络。
5. 最大吸附距离默认 5 m，超过即拒绝，避免从道路外硬拉路径。
6. 使用 A* 沿道路边规划。
7. 页面显示橙色规划线、目标坐标、吸附距离和路线长度。
8. 页面只做预览，不会因为一次点击立即发车。

地图图例：

- 黄色点/青色线：原始实测轨迹。
- 蓝色线：生成的道路网络。
- 橙色线：当前规划结果。

## 7. 自动驾驶执行链

### 7.1 为什么不能直接信任前端路线

用户确认后，前端只发送：

```json
{
  "robotId": 1,
  "networkId": "<network-id>",
  "goalLongitude": 113.0,
  "goalLatitude": 22.0,
  "maxSnapM": 5.0
}
```

后端不会直接相信浏览器提交的一串路径点。车端在启动瞬间重新读取当前 RTK 位置、再次规划并再次执行安全检查，防止车辆已移动或页面数据过期。

### 7.2 启动前检查

`start_rtk_route_execution()` 的关键顺序：

1. 拒绝已有活动路线。
2. 检查当前 RTK 健康状态和 `gps_qual=4`。
3. 从当前实时 WGS-84 位置重新执行道路规划。
4. 检查规划路线长度，当前硬上限是 50 m。
5. 启动或确认 RTK 导航 ROS 进程就绪。
6. 用当前点调用一次 `/fromLL` 做预检。
7. 等待当前时刻的 TF 链连续 3 次成功。
8. 启动 `RtkRouteExecutor`。

路线长度上限指沿道路规划出的路径长度，不是起终点直线距离。

### 7.3 逐点执行

`agent/ros/rtk_route_executor.py` 会：

- 将规划路线压缩为约 2 m 间距的执行点。
- 对每个 WGS-84 点调用 `/fromLL` 转为本地 `map` 坐标。
- 计算朝向并发布 `/move_base_simple/goal`。
- 监听 `/move_base/status` 和结果。
- 成功后进入下一个点。
- `ABORTED`、`REJECTED`、`RECALLED`、`LOST` 等状态会使路线失败。
- 单个点默认 45 秒超时。
- 支持暂停、继续、立即停车。

暂停和停止都会取消 move_base 目标并发布零速度。RTK 失锁也会进入紧急停止路径。

### 7.4 当前速度

`agent/ros/rtk/rtk_move_base.yaml` 当前自动导航上限：

```yaml
max_vel_x: 0.65
max_vel_trans: 0.65
```

这是代码参数，不代表应直接以 0.65 m/s 做第一次验收。第一次闭环测试应临时限制在约 0.20 m/s，先完成 3–5 m 的封闭场地直线测试，再逐级放开。人工遥控采集速度与 DWA 自动导航速度不是同一套控制入口，不要混淆。

## 8. 前后端 API

统一前缀：`/api/navigation`。所有请求经过平台认证并通过 Agent Gateway 转发到指定车辆。

### 8.1 RTK 导航

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/rtk/status?robot_id=<id>` | 读取 RTK、NTRIP、ROS 进程、路线执行和限制状态 |
| POST | `/rtk/start` | 启动 RTK 导航 ROS 进程 |
| POST | `/rtk/goal` | 直接发送单个 WGS-84 目标，主要用于受控调试 |
| POST | `/rtk/stop` | 停止 RTK 导航进程并停车 |
| POST | `/rtk/route/start` | 从当前 RTK 位置重新规划并执行道路路线 |
| POST | `/rtk/route/pause` | 暂停路线 |
| POST | `/rtk/route/resume` | 继续路线 |
| POST | `/rtk/route/stop` | 取消路线并停车 |

### 8.2 道路采集和网络

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/rtk/roads/status?robot_id=<id>` | 采集状态 |
| POST | `/rtk/roads/start` | 开始自动记录 Fixed 轨迹 |
| POST | `/rtk/roads/pause` | 暂停采集 |
| POST | `/rtk/roads/resume` | 继续采集 |
| POST | `/rtk/roads/stop` | 停止并保存 |
| POST | `/rtk/roads/discard` | 放弃本次采集 |
| GET | `/rtk/roads/tracks?robot_id=<id>` | 已保存轨迹列表 |
| GET | `/rtk/roads/tracks/{track_id}?robot_id=<id>` | 单条轨迹详情 |
| POST | `/rtk/roads/networks/build` | 由多条轨迹生成道路网络 |
| GET | `/rtk/roads/networks?robot_id=<id>` | 网络列表 |
| GET | `/rtk/roads/networks/{network_id}?robot_id=<id>` | 网络详情 |
| POST | `/rtk/roads/plan` | 只读目标吸附和 A* 规划 |

请求模型位于 `backend/schemas.py`：

- `RtkNavigationGoalRequest`
- `RtkRoadCollectionStartRequest`
- `RtkRoadActionRequest`
- `RtkRoadNetworkBuildRequest`
- `RtkRoadPlanRequest`
- `RtkRouteStartRequest`

## 9. 关键文件和调用链

### 9.1 前端

| 文件 | 作用 |
|---|---|
| `frontend/src/pages/OutdoorRtkNavigation.jsx` | RTK 主页面、MapLibre、轨迹/网络/规划图层、状态轮询、规划与自动驾驶按钮 |
| `frontend/src/components/RtkSurveyCockpit.jsx` | 摄像头、人工驾驶、速度控制和采集驾驶舱 |
| `frontend/src/styles/OutdoorRtkNavigation.css` | RTK 页面布局和状态样式 |
| `frontend/.env.rtk.example` | 底图、吸附距离、直接目标限制示例 |
| `frontend/vite.config.js` | MapLibre 依赖构建配置 |

### 9.2 服务器

| 文件 | 作用 |
|---|---|
| `backend/routers/navigation.py` | `/api/navigation/rtk/*` REST 接口及 Agent 转发 |
| `backend/schemas.py` | RTK、采集、规划和路线请求模型 |

### 9.3 车端 Agent 和 ROS

| 文件 | 作用 |
|---|---|
| `agent/ros/robot_control_server.py` | Agent 主进程、ROS 订阅、RTK 状态、安全门、命令分发、`/fromLL`、TF 预检、路线启动 |
| `agent/ros/rtk_navigation_core.py` | Fixed、时效、跳点和恢复状态机 |
| `agent/ros/rtk_road_network.py` | 轨迹采集、持久化、网络构建、吸附和 A* |
| `agent/ros/rtk_route_executor.py` | 路径抽稀、逐点转换、move_base 状态机、暂停/继续/急停 |
| `agent/ros/ntrip_rtcm_client.py` | FindCM NTRIP 连接、GGA 回传、RTCM3 写入 G70 |
| `agent/ros/launch/dwc_rtk_navigation.launch` | navsat、EKF、静态天线 TF、move_base |
| `agent/ros/launch/dwc_pointcloud_scan.launch` | 点云到 `/scan` 的转换链 |
| `agent/ros/rtk/rtk_navsat.yaml` | navsat_transform 参数 |
| `agent/ros/rtk/rtk_global_ekf.yaml` | global EKF 和 TF 时间参数 |
| `agent/ros/rtk/rtk_costmap_common.yaml` | 公共 costmap / footprint / obstacle 参数 |
| `agent/ros/rtk/rtk_global_costmap.yaml` | 滚动全局代价地图 |
| `agent/ros/rtk/rtk_local_costmap.yaml` | 激光局部代价地图 |
| `agent/ros/rtk/rtk_move_base.yaml` | GlobalPlanner / DWA 参数 |
| `agent/ros/rtk/findcm.env.example` | 无密钥的车端配置模板 |
| `agent/ros/rtk/README.md` | 早期 RTK 说明，第一段仍有“高德转 WGS-84”的历史描述，接手时应以本文和当前 MapLibre 代码为准并择机修正文档 |

端到端调用链：

```text
OutdoorRtkNavigation.jsx
  -> backend/routers/navigation.py
  -> agent_gateway.send_command()
  -> robot_control_server.py execute_command()
  -> RoadWorkspace / RtkRouteExecutor / ROS
  -> status response
  -> FastAPI
  -> React 状态面板和 MapLibre 图层
```

## 10. 车端配置参数

下面只列参数名和默认值，不含真实凭据：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `DWC_RTK_GPS_TOPIC` | `/gps/fix` | WGS-84 NavSatFix |
| `DWC_RTK_GGA_TOPIC` | `/gnss/gpgga` | 必须含 `gps_qual` 的原始 GGA |
| `DWC_RTK_IMU_TOPIC` | `/imu` | IMU |
| `DWC_RTK_ODOM_TOPIC` | `/odom` | 轮式里程计 |
| `DWC_RTK_SCAN_TOPIC` | `/scan` | 激光扫描 |
| `DWC_RTK_BASE_FRAME` | `base_footprint` | 车体基准 |
| `DWC_RTK_ODOM_FRAME` | `odom_combined` | 本地里程计坐标系 |
| `DWC_RTK_GPS_FRAME` | `navsat_link` | 天线坐标系 |
| `DWC_RTK_GPS_OFFSET_X/Y/Z` | `0.0` | 天线相对车体杆臂，正式验收前必须实测 |
| `DWC_RTK_FIX_STALE_SEC` | `2.0` | Fix 超时 |
| `DWC_RTK_GGA_STALE_SEC` | `2.0` | GGA 超时 |
| `DWC_RTK_MIN_JUMP_M` | `1.0` | 跳点距离门槛 |
| `DWC_RTK_MAX_JUMP_SPEED_MPS` | `3.0` | 跳点速度门槛 |
| `DWC_RTK_RECOVERY_FIXES` | `3` | 恢复所需稳定点数 |
| `DWC_RTK_LOSS_GRACE_SEC` | `1.0` | 执行中失锁停车宽限 |
| `DWC_RTK_ROAD_RECORD_SPACING_M` | `1.0` | 直行采集间距 |
| `DWC_RTK_ROAD_TURN_RECORD_SPACING_M` | `0.5` | 转弯采集间距 |
| `DWC_RTK_ROAD_TURN_THRESHOLD_DEG` | `12.0` | 转弯加密阈值 |
| `DWC_RTK_ROAD_NETWORK_SPACING_M` | `0.25` | 网络生成重采样间距 |
| `DWC_RTK_ROAD_MERGE_RADIUS_M` | `0.75` | 网络节点合并半径 |
| `DWC_RTK_ROUTE_MAX_DISTANCE_M` | `50.0` | 单次规划路线硬上限 |
| `DWC_RTK_ROUTE_WAYPOINT_SPACING_M` | `2.0` | 执行点间距 |
| `DWC_RTK_ROUTE_WAYPOINT_TIMEOUT_SEC` | `45.0` | 单点超时 |
| `DWC_RTK_NAV_STARTUP_TIMEOUT_SEC` | `20.0` | ROS 导航启动等待 |
| `DWC_RTK_FROM_LL_TIMEOUT_SEC` | `12.0` | `/fromLL` 可用等待 |
| `DWC_RTK_TF_READY_TIMEOUT_SEC` | `12.0` | TF 连续就绪等待 |

这里有一个需要 Cursor 核对的命名细节：`robot_control_server.py` 读取的是 `DWC_RTK_ROUTE_STARTUP_TIMEOUT_SEC`，而 `findcm.env.example` 当前写的是 `DWC_RTK_NAV_STARTUP_TIMEOUT_SEC`。这会导致环境文件设置不生效、代码继续使用 20 秒默认值。后续应统一名称并补测试，但不要在不了解车端现有环境文件的情况下直接改生产值。

## 11. 两次现场自动驾驶失败和修复

### 11.1 第一次：`/fromLL` 返回空错误

页面错误：

```text
service [/fromLL] responded with an error: b''
```

判断：`navsat_transform_node` 已经创建 `/fromLL` 服务，但 datum/转换链尚未真正可用。仅等待 service 名字存在并不等于转换已就绪。

修复：

- `wgs84_to_map()` 增加有界重试，默认最多 12 秒。
- 启动自动路线前先用车辆当前位置调用一次 `/fromLL` 预检。
- 状态接口返回 `fromLlTimeoutSec`，便于页面和诊断确认真实配置。

### 11.2 第二次：DWA 找不到有效控制

页面错误：

```text
Failed to find a valid control. Even after executing recovery behaviors.
```

现场只读诊断发现：

- `/scan` 和 `/odom` 都约 20 Hz。
- 激光约 1000 个 range，其中约 592 个有效，最近点约 0.301 m。
- 真正关键的 rosout 是：

```text
Extrapolation Error: Lookup would require extrapolation 0.024921613s into the future...
from frame [odom_combined] to frame [map]
```

当时 TF 所有权：

- `/dwc_rtk_global_ekf` 发布 `map -> odom_combined`。
- `/robot_pose_ekf` 发布 `odom_combined -> base_footprint`。
- 静态 TF 提供 base 到激光、相机、IMU 等链接。

因此不能简单归因于“前方有障碍”。根因是全局规划使用 `map`、局部控制使用 `odom_combined` 时，控制周期查询到了比 `map -> odom_combined` 最新时间略新的变换。

已部署修复：

1. `agent/ros/rtk/rtk_global_ekf.yaml` 设置 `transform_time_offset: 0.10`。
2. `wait_for_rtk_tf_ready()` 在发车前检查当前时刻：
   - `odom_combined <- map`
   - `map <- base_footprint`
   - 连续 3 次成功才放行，最多等待 12 秒。
3. launch 新增 `dwc_base_to_navsat` 静态 TF，并允许通过环境变量配置天线偏移。
4. DWA 明确设置非完整约束：
   - `acc_lim_y: 0`
   - `max_vel_y: 0`
   - `min_vel_y: 0`
   - `vy_samples: 1`

重要：上述补丁已通过静态检查和服务检查，但天气变差、车辆已回到遮挡区域，最后没有继续做运动测试。需要在下一次室外 Fixed 条件下确认 TF extrapolation 是否真正消失。

## 12. 当前验证结果

2026-08-31 在本地当前工作区重新验证：

```powershell
cd C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl\agent\ros
python -m unittest discover -s tests -v
```

结果：20 个测试通过，1 个 Linux PTY 集成测试因 Windows 环境跳过。

覆盖内容包括：

- NTRIP 配置、GGA、新鲜度、认证失败脱敏和状态文件不泄密。
- RTK Fixed、跳点锁定和稳定恢复。
- 采集 Fixed 门槛、暂停/恢复/持久化、直行与转弯密度。
- 网络构建、规划和超出吸附范围拒绝。
- 路线抽稀、逐点完成、失败和 RTK 无效停止。

前端：

```powershell
cd C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl\frontend
npm run build
```

结果：Vite 构建通过。存在 MapLibre 和主 bundle 大于 500 kB 的警告，当前不影响功能，但后续可用动态导入和 manual chunks 优化。

历史部署前还执行过：

```powershell
python -m py_compile agent\ros\robot_control_server.py agent\ros\rtk_route_executor.py agent\ros\rtk_road_network.py agent\ros\rtk_navigation_core.py
git diff --check
```

以及 launch XML 解析、YAML `safe_load`、目标前端文件 ESLint。`git diff --check` 只有 LF/CRLF 提示时，不应进行全仓换行格式化。

## 13. 最后一次部署和运行状态

最后一次现场部署/检查时间为 2026-08-29，确认过：

- `DevicesWebControl-robot_control_server.service` 为 active，重启计数 0。
- G70、NTRIP、Agent 服务存在且当时可检查。
- 状态接口能看到路线最大 50 m、`/fromLL` 12 秒、TF 12 秒、路线执行 idle。
- 车辆速度为零，RTK 导航没有运行。
- 车辆回到遮挡区域后 `rtkFixed=false`，所以没有继续自动运动测试。

部署备份目录：

```text
车端：/home/wheeltec/Dong/DevicesWebControl/.deploy-backups/rtk-auto-50m-20260829
车端：/home/wheeltec/Dong/DevicesWebControl/.deploy-backups/fromll-hotfix-20260829
车端：/home/wheeltec/Dong/DevicesWebControl/.deploy-backups/tf-hotfix-20260829
服务器：/home/huyunfeng/backups/rtk-auto-50m-20260829
```

这些是历史备份线索。回滚前仍要只读确认目录内容、时间和目标文件，不能盲目覆盖。

## 14. 安全部署原则

只更新室外项目：

- 可以操作：`outdoor-deviceswebcontrol.service`、车端本项目 Agent/RTK 文件。
- 不要影响：室内平台 `18443`、旧室外 `:88`、FRP、其他车辆和室内 `192.168.31.9`。

推荐发布顺序：

1. 本地保存 `git status --short`、目标文件 diff 和测试结果。
2. 将目标文件上传到远端临时 staging 目录，不直接覆盖运行目录。
3. 在目标主机计算 SHA256 并执行 Python/XML/YAML 静态检查。
4. 备份将被替换的精确文件。
5. 用明确路径替换，不使用宽泛 glob。
6. 确认车辆 `/odom` 线速度和角速度为零。
7. 只重启需要的服务。
8. 检查 `systemctl status`、`NRestarts`、日志和平台状态。
9. 清理临时传输目录。
10. 不因服务 active 就开始运动，另行执行现场验收清单。

真实密码和密钥不应写入任何交接提示。让操作者使用已经配置好的 SSH/Remote Access 凭据或安全输入。

## 15. 下一次实车验收清单

### 15.1 发车前，只读检查

1. 确认是室外巡检车，不是室内车或旧服务。
2. 现场有人监护，急停按钮可立即触达，测试区域封闭、前方无人员和车辆。
3. 确认 `/odom` 连续为零，网页没有残留按键，`/cmd_vel` 没有异常发布者。
4. 检查 G70 串口、NTRIP 字节持续增加、GGA 时间新鲜。
5. 必须观察原始 GGA `gps_qual=4` 稳定保持，不能只看 `/gps/fix` 或网页绿色标签。
6. 检查 `/gps/fix` 数值非 NaN、协方差合理、时间戳新鲜。
7. 检查 TF 只有预期发布者，并验证当前时间：
   - `map -> odom_combined`
   - `odom_combined -> base_footprint`
   - `base_footprint -> navsat_link`
8. 检查 `/scan` 频率、时间戳、frame、有效 range 和近障碍物。
9. 核对 footprint 与实车尺寸，确认没有把车体边缘当成障碍或漏算车宽。
10. 核对当前道路网络和目标，吸附距离不超过 5 m，规划路径不超过 50 m。

### 15.2 必须先测天线杆臂

测量 GNSS 天线相位中心相对 `base_footprint` 原点的：

- X：车头方向为正。
- Y：车体左侧为正。
- Z：向上为正。

填入车端环境文件：

```env
DWC_RTK_GPS_OFFSET_X=<measured-x>
DWC_RTK_GPS_OFFSET_Y=<measured-y>
DWC_RTK_GPS_OFFSET_Z=<measured-z>
```

如果不做这一步，即使 RTK 本身是厘米级，车辆控制点也可能持续偏离道路中心几十厘米甚至更多。

### 15.3 分级运动验证

建议按以下顺序，每级成功后再进入下一级：

1. 0 m：只启动导航进程，不发目标，确认无自发运动。
2. 3–5 m：直线路径，自动速度临时限制约 0.20 m/s。
3. 5–10 m：包含轻微弯曲，检查横向误差和停车位置。
4. 10–20 m：包含一个明确转弯，检查 DWA、TF 和激光避障。
5. 人为短暂制造 RTK 无效条件，验证 1 秒宽限后取消目标并零速度；这一步必须在架空轮或非常安全的封闭条件下设计执行。
6. 验证网页“暂停、继续、立即停车”。
7. 确认 rosout 不再出现 TF future extrapolation、navsat transform、valid control 等关键错误。
8. 完成多次稳定复现后，才测试 20–50 m 路线并逐步恢复速度。

通过标准至少包括：

- 全程原始 GGA Fixed 稳定。
- TF 查询无时间外推错误。
- 路线进度和车辆实际位置一致。
- move_base 不进入 recovery 循环。
- 激光近障碍能触发停车/绕行，急停有效。
- 停止、失锁、错误状态均能取消目标并持续零速度。
- 记录实际横向误差、终点误差和重复性，不只看卫星图视觉重合。

## 16. 已知缺口和后续开发优先级

### P0：实车闭环验收

- 测量并配置 GNSS 天线杆臂。
- 室外 Fixed 条件下完成 3–5 m、约 0.20 m/s 的低速测试。
- 验证 TF extrapolation 修复有效。
- 检查 footprint、激光盲区、最小障碍距离和真实制动距离。

### P1：道路网络可靠性

- 增加禁行区、多边形障碍区和临时封路。
- 为道路边增加方向、速度上限、宽度和转弯限制。
- 增加十字路口/回环/平行道路的拓扑校验和人工编辑。
- 增加网络版本、来源轨迹和回滚能力。
- 增加采集质量报告：Fixed 占比、跳点、缺口、重复路线误差。

### P1：自动驾驶任务管理

- 保存规划任务和执行历史。
- 记录每个 waypoint 的开始、成功、失败、RTK/TF/scan 快照。
- 页面明确区分“规划完成”“等待确认”“执行中”“暂停”“失锁停车”“执行失败”。
- 防止浏览器重复点击产生重复 start 请求。
- 后端增加幂等 token 或 route execution id。

### P2：地图和前端工程

- 生产环境使用具备合法授权、稳定 SLA 的瓦片或校园自建正射影像。
- MapLibre 懒加载/分包，减少约 1 MB 的 JS chunk。
- 增加底图切换、离线瓦片缓存和瓦片失败降级提示。
- 不要加入 GCJ-02 二次转换，除非另做清晰隔离的高德显示模式，并保证 RTK 控制数据始终保存为 WGS-84。

### P2：文档和配置一致性

- 修正 `agent/ros/rtk/README.md` 中仍写高德转换的历史描述。
- 统一 `DWC_RTK_ROUTE_STARTUP_TIMEOUT_SEC` 与 `DWC_RTK_NAV_STARTUP_TIMEOUT_SEC` 命名。
- 将环境变量解析和默认值集中管理，减少前端、示例文件和 Agent 各自维护造成的漂移。

## 17. Cursor 接手后的建议顺序

第一轮只做理解和验证，不改实车：

```powershell
cd C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl
git status --short
git diff --stat
git diff -- agent/ros/robot_control_server.py
git diff -- backend/routers/navigation.py backend/schemas.py
git diff -- frontend/src/pages/OutdoorRtkNavigation.jsx frontend/src/components/RtkSurveyCockpit.jsx
```

然后跑本地测试：

```powershell
cd C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl\agent\ros
python -m unittest discover -s tests -v

cd C:\Users\11045\Desktop\室外巡检项目开发\DevicesWebControl\frontend
npm run build
```

随后优先完成两个小修复：

1. 统一启动超时环境变量名称，并为环境变量覆盖行为补测试。
2. 更新 `agent/ros/rtk/README.md`，使其与 MapLibre + WGS-84 实现一致。

但在修改前仍要确认这些文件中的未提交内容是用户要保留的工作，并采用窄范围补丁。

## 18. 一句话总结当前状态

当前系统已经具备“人工驾驶自动采集 WGS-84 道路 → 保存轨迹 → 生成道路网络 → 地图点击目标 → 吸附并 A* 规划 → 人工确认 → 车端按实时 RTK 重规划并逐点交给 move_base”的完整软件链；本地测试和前端构建通过，也部署过 `/fromLL` 与 TF 时间修复，但最后一轮修复后的室外低速自动行驶尚未验收，下一步应先测量天线杆臂并完成 3–5 m 封闭场地 Fixed 测试。
