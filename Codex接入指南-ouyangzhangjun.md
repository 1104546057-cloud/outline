# Codex 接入指南（ouyangzhangjun 专用）：室外巡检项目 DevicesWebControl

更新时间：2026-10-17（北京时间）。
适用对象：ouyangzhangjun，使用 Codex 在自己的 Windows 电脑上参与开发。项目原负责人为huyunfeng，当前阶段两人共同开发，后续整体移交给ouyangzhangjun。

本文写给 Codex 读。Codex 每次开新会话时都应先完整阅读本文，再动手。文中的地址、设备身份、服务状态是 2026-10-17 的核实结果，每次会话都要重新只读验证，不得沿用上次会话的结论。

---

## 0. 给 Codex 的开场提示词（新会话直接粘贴）

```text
请先完整阅读项目根目录的《Codex接入指南-ouyangzhangjun.md》，以及 tools/cursor_connect.py。
本次操作的是室外巡检项目 DevicesWebControl，我是 ouyangzhangjun，和 huyunfeng 共用服务器账号开发。

本地项目：<我的本地项目目录>（请先确认路径）
SSH 私钥：$env:USERPROFILE\.ssh\ouyangzhangjun.pem
服务器：huyunfeng@8.134.135.58:22（共用账号，主机名 icclab-aliyungz）
服务器项目：/home/huyunfeng/projects/DevicesWebControl
服务器服务：outdoor-deviceswebcontrol.service（systemctl --user，端口 52734，HTTPS）
生产网页：https://8.134.135.58:52734

目标车辆：室外巡检车01，平台 device_id=1，ZeroTier IP=10.139.91.240
车端用户/主机：wheeltec / wheeltec
车端工作目录：/home/wheeltec/Dong/DevicesWebControl

请先只读验证：
1. 用私钥连接服务器，确认 hostname=icclab-aliyungz、whoami=huyunfeng、项目路径存在、服务 active。
2. 在服务器运行 tools/cursor_connect.py status，报告平台健康、车辆身份、控制/媒体/Remote Access、录像与推理状态。
3. 需要连车时，优先走服务器 tools/cursor_connect.py vehicle 反向通道；车端密码由我在自己的终端输入。
4. 检查服务器 git status，报告与 GitHub 和本地的差异，不要自行同步。

连接成功后不要顺手重启服务、发运动指令、启停 DAI、启动录像或改网络。
修改前先读取服务器/车端当前实际文件，备份后做最小补丁；不要整目录覆盖。
密码、Token、私钥内容不得写进文件、命令参数、报告或聊天。
室内 18443、旧室外 52733/:88、DAI 10.139.91.78 都不是目标车辆，不要混用。
```

---

## 1. 账号与权限现状（务必理解）

- ouyangzhangjun在服务器上有自己的账号 `ouyangzhangjun`，但**该账号无权访问项目**（`/home/huyunfeng` 权限为 750），也控制不了项目服务。
- 因此当前做法是**共用 huyunfeng 账号**：ouyangzhangjun的公钥已加入 `/home/huyunfeng/.ssh/authorized_keys`，注释为 `ouyangzhangjun-shared`。用他自己的私钥登录 `huyunfeng@8.134.135.58`，权限与huyunfeng完全相同。
- 两人都**没有 sudo**。服务器 `sudo` 组为空，所有操作必须在 huyunfeng 用户权限内完成。需要 root 的事情（装系统包、改防火墙、改系统服务）要找服务器管理员，Codex 不要尝试提权。
- 服务器上还有其他同学的账号和服务（`/home` 下有 admin、fengyuan、guohaitao、kexiaoyu、youweijian 等）。**不要碰其他用户的文件、进程或端口。**
- 共用账号意味着服务器上分不清操作是谁做的。重要操作（部署、重启、改配置）前，先和huyunfeng沟通；完成后在 git 提交信息或群里说明。

---

## 2. 本机准备（ouyangzhangjun在自己电脑上做一次）

### 2.1 放置私钥

微信传来的 `ouyangzhangjun.pem` 有两个已知问题：末尾缺换行符（OpenSSH 会报 `invalid format`），以及 Windows 权限过宽（会报 `UNPROTECTED PRIVATE KEY FILE`）。在 PowerShell 执行：

```powershell
$k = "$env:USERPROFILE\.ssh\ouyangzhangjun.pem"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
Copy-Item "<微信里收到的 ouyangzhangjun.pem 路径>" $k
Add-Content $k ""
icacls $k /inheritance:r /grant:r "${env:USERNAME}:F"
```

### 2.2 第一次连接服务器并核对指纹

```powershell
ssh -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o StrictHostKeyChecking=accept-new huyunfeng@8.134.135.58 "hostname; whoami"
```

服务器正确的 ED25519 主机指纹是：

```text
SHA256:vqZmR6zV9xiumb7ya0o4yJZuo0adSjTtrdcH0vmRyKg
```

首次连接提示的指纹必须与此一致。之后的自动化命令都加 `-o BatchMode=yes`，避免卡在交互提示上。

### 2.3 可选：配置 SSH 别名

在 `$env:USERPROFILE\.ssh\config` 加入：

```text
Host dwc
    HostName 8.134.135.58
    User huyunfeng
    IdentityFile ~/.ssh/ouyangzhangjun.pem
    IdentitiesOnly yes
    ServerAliveInterval 30
```

之后 `ssh dwc` 即可。本文后续命令为了不依赖这个配置，仍写完整参数。

### 2.4 Codex 的运行设置

- Codex 需要执行 `ssh` 访问外网。默认沙箱可能禁止网络，需要在 Codex 中批准网络访问，或使用允许网络的沙箱模式（例如 `workspace-write` 并开启网络访问）。具体选项以所用 Codex 版本为准。
- 需要输入密码的命令（车端 SSH、`--sudo`）Codex 的自动执行器无法交互。遇到 `password:` 提示时，Codex 应停下，把完整命令交给ouyangzhangjun在自己的终端执行。
- 可以把本文复制或软链为项目根目录的 `AGENTS.md`，Codex 会自动读取。注意不要把 `AGENTS.md` 提交成含个人路径的版本，避免影响huyunfeng。

### 2.5 可选：ZeroTier

只有直连车端（`10.139.91.240`）或 DAI 推理节点（`10.139.91.78`）时才需要 ZeroTier：安装 ZeroTier、加入与huyunfeng相同的网络 ID，并由网络管理员在 ZeroTier Central 授权该设备。日常开发、部署和经反向通道连车都**不需要** ZeroTier。

---

## 3. PowerShell 下执行远程命令的坑（Codex 必读）

Codex 在 Windows 上默认用 PowerShell 执行命令，以下问题已经实际踩过：

1. **双引号会被吞。** Windows PowerShell 5 给原生程序传参时会剥掉内部双引号，`ssh host 'K="a b"; ...'` 到了远端会变成 `K=a b`，命令直接出错。
2. **多行或带引号的远程脚本，用标准输入传给 `bash -s`：**

   ```powershell
   $script = @'
   cd ~/projects/DevicesWebControl
   git status -sb
   systemctl --user is-active outdoor-deviceswebcontrol.service
   # end
   '@
   $script -replace "`r","" | ssh -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'bash -s'
   ```

3. **管道末尾会多一个 `\r`。** PowerShell 往原生程序管道写数据时会在结尾补 CRLF，导致脚本最后一行多出 `\r`，比如 `ls tools` 变成找不到 `tools\r`。规避办法：让脚本最后一行是注释（如 `# end`），多出的 `\r` 就落在注释里，不影响执行。
4. 简单的单行命令，用单引号包整条命令、内部不用双引号即可：

   ```powershell
   ssh -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'cd ~/projects/DevicesWebControl && git log --oneline -3'
   ```

---

## 4. 系统架构总览

```text
浏览器 ──HTTPS:52734──> 服务器 8.134.135.58（FastAPI + 已构建的 React 前端，MySQL）
                              ▲            │
           车端 Agent 主动连接 │            │ HTTP 调用
   （遥测 / 控制 / 媒体 / Remote Access）    ▼
                              │      DAI 推理节点 10.139.91.78:9100（经 ZeroTier）
                    室外巡检车01（Wheeltec ROS1，4G 上网，ZeroTier 10.139.91.240）
                      ├─ eth0：激光雷达
                      └─ eth1：有线摄像头 192.168.1.11（RTSP H.265 + ONVIF 云台）
```

- 车端采用**主动连接模式**：平台先创建设备并生成 Token，车端 Agent 用同一 Token 上报遥测、接收控制、上传媒体。服务器不需要能主动访问车。
- Remote Access：车端 Remote Access Agent 主动连平台，平台再把 SSH、文件管理、远程桌面转接到车端，所以车在 4G 下也能远程登录。

### 4.1 代码目录

```text
DevicesWebControl/
├─ backend/              FastAPI 后端（main.py 入口，routers/ 各业务接口）
├─ frontend/             React + Vite 前端
├─ agent/
│  ├─ ros/               Wheeltec ROS1 车端 Agent（室外巡检车01 用这个）
│  ├─ common/            非 ROS 树莓派 / Jetson Nano 小车 Agent
│  └─ remote_access/     车端 Remote Access Agent
├─ tools/cursor_connect.py   服务器上的连接与状态检查脚本
├─ docs/                 历史文档（handover-for-gpt-lab-server.md 已过时，不可作为依据）
├─ Cursor新对话接入指南.md      huyunfeng用的版本（路径是他的）
└─ Codex接入指南-ouyangzhangjun.md   本文
```

本地开发环境的搭建（conda、npm、MySQL、`init_db.py`、本地启动前后端）见项目根目录 `README.md`。注意 README 里的本地默认端口（8000/5273）和默认账号只适用于本地开发，与生产不同。

---

## 5. 服务器详情（2026-10-17 核实）

| 项目 | 值 |
| --- | --- |
| 登录 | `huyunfeng@8.134.135.58:22`，主机名 `icclab-aliyungz` |
| 项目目录 | `/home/huyunfeng/projects/DevicesWebControl` |
| Python | 项目内 `.venv/bin/python` |
| 服务 | 用户级 `outdoor-deviceswebcontrol.service`，所有 systemctl / journalctl 命令都要加 `--user` |
| 端口 | `0.0.0.0:52734`，uvicorn 直接提供 HTTPS |
| TLS 证书 | `/home/huyunfeng/.config/outdoor-dwc/tls/server.crt` 与 `server.key` |
| 数据库 | MySQL，`127.0.0.1:3306`，库名与账号见 `backend/.env` 的 `DB_*`（`backend/database.py` 只支持 MySQL） |
| 后端配置 | `backend/.env`（权限 600，含密钥，不得 cat 到聊天） |
| 录像存储 | 项目内 `data/camera_videos/`，元信息为同名 JSON |
| Node | `mise` 管理，`node@24.19.0` |
| linger | 已开启，用户退出登录后服务继续运行 |

服务的启动命令（来自 systemd 单元）：

```text
.venv/bin/python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port 52734
    --ssl-keyfile ~/.config/outdoor-dwc/tls/server.key
    --ssl-certfile ~/.config/outdoor-dwc/tls/server.crt
    --limit-concurrency 100 --timeout-keep-alive 10
```

关于数据库的注意事项：

- `.env` 里虽然有 `SQLITE_PATH` 和 `DB_BACKEND`，但当前代码不读取这两项。`~/.config/outdoor-dwc/outdoor.db` 是 2026-08-20 留下的旧文件，不是生产数据，不要据此判断数据状态。
- 服务器上的 MySQL 监听 `0.0.0.0:3306`，可能还有其他同学的库。只操作本项目的库，不要建删库、不要改全局配置、不要动其他用户。
- 改表结构或批量改数据前，先用 `mysqldump` 备份本项目的库（密码从 `.env` 读入环境变量，不要写在命令行里）。

单元文件位置：`~/.config/systemd/user/outdoor-deviceswebcontrol.service`。改了单元文件后要先 `systemctl --user daemon-reload`。

`backend/.env` 包含的配置项（只列名称）：`SQLITE_PATH DB_BACKEND DB_USER DB_PASSWORD DB_HOST DB_PORT DB_NAME DEFAULT_ADMIN_USER DEFAULT_ADMIN_PASSWORD JWT_SECRET_KEY JWT_ALGORITHM ACCESS_TOKEN_EXPIRE_MINUTES AUTH_COOKIE_SECURE PUBLIC_SERVER_URL DETECTOR_URL DETECTOR_TIMEOUT RECOGNITION_REQUEST_TIMEOUT`。查看某一项时只输出键名或做存在性判断，不要打印值。

### 5.1 不能碰的东西

- 室内平台 `indoor-platform.service`、端口 `18443`。
- 旧室外平台 `52733` 和 `:88`。
- FRP、其他用户账号及其服务。
- `~/.ssh/authorized_keys` 里huyunfeng的公钥（注释 `root@icclab-aliyungz`）。

---

## 6. 代码同步现状（重要，2026-10-17）

**目前三处代码不一致，GitHub 不是线上真实版本：**

| 位置 | 状态 |
| --- | --- |
| GitHub `1104546057-cloud/outline` 的 `main` | 最新提交 `f66b197 fix: cap proxied camera stream rate` |
| 服务器 git | HEAD 停在 `52ff110`，比 GitHub 落后 10 个提交；另有未提交修改：`.gitignore`、`agent/ros/deploy.sh`、`agent/ros/robot_control_server.py`、`agent/ros/ros_camera_server.py` |
| huyunfeng本地 | 比 GitHub 多 1 个未推送提交 `3f9808e feat: freeze outdoor recognition over ZeroTier and persist results`，另有 20 多个文件未提交（backend/routers、frontend 页面、agent 等） |

原因：过去的部署方式是**直接把文件拷到服务器**，没有走 git pull。所以服务器 git 历史落后，但实际运行的文件可能比 git 记录新。

对 Codex 的要求：

- **以服务器上实际运行的文件为准**。改某个文件前，先读服务器上的当前内容，并与本地版本比对。
- **不要在服务器上执行 `git pull`、`git checkout .`、`git reset --hard`、`git stash`**，这会覆盖已部署但未提交的线上代码。
- 发现差异时报告给用户，由huyunfeng和ouyangzhangjun决定怎么合并。
- 理想流程（待huyunfeng把本地改动整理、推送到 GitHub 之后执行）：两人在各自电脑开发 → 推送到 GitHub 分支 → PR 合并 → 服务器 `git pull` 部署。在这个流程建立之前，按"读服务器文件 → 备份 → 最小补丁"的方式改。

在服务器上提交时署ouyangzhangjun自己的名字（服务器 git 默认身份是huyunfeng）：

```bash
git -c user.name="ouyangzhangjun" -c user.email="<他的邮箱>" commit -m "..."
```

服务器 git 的远程是 HTTPS 地址，服务器上没有配置 GitHub 推送凭据；推送一般在本地电脑完成。

---

## 7. 日常操作

### 7.1 只读状态检查

```powershell
ssh -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'cd ~/projects/DevicesWebControl && .venv/bin/python tools/cursor_connect.py status'
```

`status` 只读：不启动录像、不启停推理、不发云台或底盘动作。它在服务器上用项目已有账号生成 3 分钟有效的内存登录凭据，调用认证接口，不打印 Token，不创建或重置账号。HTTPS 校验以服务器上的 `server.crt` 为信任来源。

重点看：

- `platform_health.status` 是否为 `ok`。
- `vehicle` 是否仍为室外巡检车01、`id=1`、`10.139.91.240`。
- `control_connected`、`media_connected`、`remote_access.connected`：三者分开判断。
- 摄像头 `recognition.camera.online`；推理 `enabled/online/stopped/live`。推理停止时摄像头仍可在线。
- `recording.recording`：有人在录像时，不要用重启服务的方式打断。

设备 `status=online` 单独不足以证明车在线，关机后该字段可能滞后。

### 7.2 查看服务日志

```powershell
ssh -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'journalctl --user -u outdoor-deviceswebcontrol.service -n 100 --no-pager'
```

### 7.3 修改后端并重启

1. 读服务器上的目标文件，与本地比对。
2. 备份：`cp backend/xxx.py backend/xxx.py.bak-$(date +%Y%m%d-%H%M%S)`，或参照项目里已有的 `.deploy-backup-<日期>-<说明>/` 目录做整体备份。
3. 做最小补丁。
4. 语法检查：`.venv/bin/python -m py_compile backend/xxx.py`。
5. 确认没人在录像（看 `status` 的 `recording`），并与huyunfeng确认后重启：

   ```bash
   systemctl --user restart outdoor-deviceswebcontrol.service
   systemctl --user is-active outdoor-deviceswebcontrol.service
   journalctl --user -u outdoor-deviceswebcontrol.service -n 50 --no-pager
   ```

6. 再跑一次 `cursor_connect.py status` 验证。

后端有测试目录 `backend/tests/`（`test_camera_recording.py`、`test_recognition_status.py`、`test_recognition_store.py`）。服务器的生产 `.venv` 里**没有安装 pytest**，测试请在本地开发环境运行；不要为了跑测试往生产环境装包，除非用户同意。

### 7.4 修改并发布前端

在服务器上构建，不要把 Windows 上构建的 `dist` 传上去覆盖：

```bash
cd ~/projects/DevicesWebControl/frontend
mise exec node@24.19.0 -- npm run build
```

构建前先确认 `mise ls node` 里仍有 24.19.0。`frontend/.env` 含高德地图 Key，不要打印。

### 7.5 回滚

项目里有 `.rollback/` 和多个 `.deploy-backup-*` 目录，是以往部署前的备份。回滚前先看清楚备份对应的日期和内容，只恢复需要的文件。

---

## 8. 网页

```text
https://8.134.135.58:52734/video-analysis   视频识别分析
https://8.134.135.58:52734/patrol/results   巡检成果
https://8.134.135.58:52734/remote-access    远程访问（SSH 终端、文件管理、远程桌面）
https://8.134.135.58:52734/devices          设备管理
```

- 浏览器会提示自签名证书，由用户手动处理，Codex 不要尝试绕过。
- 登录账号请向huyunfeng要，或让他在平台上单独开一个。不要使用 README 或旧文档里的默认密码。
- 登录态主要靠 Cookie `access_token`，不要假设加 Bearer 头就能调用所有接口。
- 服务器 API 检查通过不等于浏览器已登录；视频是否正常要看画面持续有新帧，单张快照或列表显示在线都不能单独证明。

---

## 9. 连接车端

### 方式 A：经服务器反向通道（推荐，不需要 ZeroTier）

```powershell
ssh -t -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'cd ~/projects/DevicesWebControl && .venv/bin/python tools/cursor_connect.py vehicle'
```

默认做只读诊断：主机名、用户名、当前目录和两个车端服务状态。出现 `Vehicle SSH password (not saved):` 时由ouyangzhangjun在终端输入车端密码（不回显、不保存）。车端密码向huyunfeng索取，不要写进任何文件、命令参数或聊天。

执行指定命令：

```powershell
ssh -t -i $env:USERPROFILE\.ssh\ouyangzhangjun.pem -o BatchMode=yes huyunfeng@8.134.135.58 'cd ~/projects/DevicesWebControl && .venv/bin/python tools/cursor_connect.py vehicle --command "hostname; whoami; pwd; ip route get 192.168.1.11"'
```

- 默认超时 35 秒，必要时加 `--timeout 60`。超时只代表本次等待结束，不保证远端命令已终止；不要用长时间前台任务做测试。
- 支持 `--sudo`，只在用户明确授权特权操作、且目标核实无误时使用。
- 若执行环境已安全注入 `DWC_VEHICLE_PASSWORD`，脚本会读取它；不要为此把密码写进 PowerShell 历史、`.env` 或仓库。

### 方式 B：ZeroTier 直连（需要先完成 2.5）

```powershell
ssh -o ConnectTimeout=8 wheeltec@10.139.91.240
```

直连超时不代表车断网，也不代表 Remote Access 断了。不要为了一次直连失败去改车端网络、删路由或重装 ZeroTier。

### 方式 C：网页

在 `/remote-access` 选择室外巡检车01，进入 SSH 终端，用 `wheeltec` 登录。车端桌面目录是 `/home/wheeltec/Desktop`。

### 车不在线时

`remote_access.connected=false` 或车已关机：报告离线，等车开机或网络恢复。不要反复重启服务器服务，不要把室外巡检车02 或 DAI 节点当作替代目标。

---

## 10. 车端详情

- 用户和主机名都是 `wheeltec`。
- 运行目录：`/home/wheeltec/Dong/DevicesWebControl/`，是**平铺**的脚本目录。本地源码在 `agent/ros/`，部署时文件直接放进运行目录，车上没有 `agent/ros/` 这层目录。
- 主要服务（系统级，需要 sudo）：
  - `DevicesWebControl-robot_control_server.service`：控制与媒体通道
  - `DevicesWebControl-camera.service`：摄像头
  - 另外 `deploy.sh` 还会配置 `turn_on_wheeltec_robot.service`、`DevicesWebControl-g70.service`（GPS/电量）、`DevicesWebControl-iot_client.service`（遥测）
- 查看服务：`systemctl status DevicesWebControl-camera`；日志：`journalctl -u DevicesWebControl-camera -n 100 --no-pager`。
- 车端 `iot_client.conf` 里有平台地址和设备 Token，不要打印 Token。
- ROS 环境：`source /opt/ros/noetic/setup.bash` 和 `source ~/wheeltec_robot/devel/setup.bash`。

### 10.1 摄像头与网络基线（2026-10-13 验收记录，用于定位，不代替实时检查）

- 有线摄像头 `192.168.1.11`，主流 `rtsp://192.168.1.11/live/0/MAIN`，实际编码 H.265。
- ONVIF 型号 `G3CLA-52PHM-S/G`。云台走摄像头 ONVIF；网页上的底盘方向键是另一条控制链。
- 摄像头配置文件 `/etc/devices-web-control/gun-camera.env` 可能含口令，不要 cat 全文。
- 画质基线：转发 `1920×1080`，JPEG 质量 `85`。4G 带宽决定实际帧率，配置上限不等于实测值。
- 云台按钮：按住持续转、松开停，用户已确认实机正常。不要仅凭 ONVIF `IDLE` 或请求超时参数断言"断网自动停止"已验收。
- 车端 `eth0` 接雷达，`eth1` 接摄像头。`ip route get 192.168.1.11` 应走摄像头接口；`carrier=off` 表示链路没通，先查供电和网线。

### 10.2 录像与巡检成果

- 视频页可开始录制、停止并保存，录像存服务器 `data/camera_videos/`，元信息为同名 JSON。
- 有该车进行中的巡检任务时自动关联；没有时 `task_id=null` 是正常的，不要捏造关联。
- 回放接口 `/api/patrol-results/media/{relative_path}`，支持 Range。历史视频清单看巡检成果接口；`/api/devices/camera/recordings` 只是当前录制会话。

### 10.3 DAI 推理节点

- 地址 `10.139.91.78:9100`（经 ZeroTier），后端通过 `DETECTOR_URL` 调用。
- 独立于车端。推理停止时不要把摄像头判为离线，也不要因此禁用车辆控制。连车不需要它在线。

---

## 11. 安全底线

- 私钥、密码、Token、JWT 密钥、高德 Key 的**值**不得出现在文件、命令参数、提交、报告或聊天中。
- 注意：仓库里的 `backend/.env.example` 历史上提交过看似真实的高德 Key、JWT 密钥和数据库密码。不要再往示例文件里写真实值；是否轮换由两位负责人决定。
- 不要绕过浏览器证书提示，不要关闭 TLS 校验。
- 不要做不可逆操作（删数据库、删录像、`rm -rf` 项目目录、强制推送）。确有需要时先备份并取得明确同意。
- 首次接入一律只读，报告实际结果；用户提出具体任务后再按授权修改。

---

## 12. 移交路线（备忘）

当前：共用 huyunfeng 账号共同开发。正式移交时预计要做：

1. huyunfeng把本地改动整理提交、推送 GitHub，使服务器、GitHub、本地三处一致。
2. 在 GitHub 把ouyangzhangjun加为 Collaborator，最终转移仓库所有权。
3. 把服务、项目目录、TLS 证书、MySQL 库（或其访问账号）、录像数据迁移到 `ouyangzhangjun` 账号（需要该账号开启 linger，用户级服务才能常驻）。
4. 更换平台管理员账号、车端 `wheeltec` 密码，用ouyangzhangjun自己的账号重新申请高德 Key。
5. 从 `huyunfeng` 的 `authorized_keys` 删除 `ouyangzhangjun-shared` 这一行，或整体停用 huyunfeng 账号下的服务。
6. 更新本文，把所有 huyunfeng 路径改为新路径。
