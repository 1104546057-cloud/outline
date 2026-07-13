# Remote Access Agent

该独立 Agent 为平台提供三项能力：

- 通过本机 OpenSSH 创建真实 SSH 会话；
- 在 `DWC_REMOTE_ROOT`（默认是运行用户家目录）内提供文件浏览、上传、下载、新建目录、重命名和安全删除；
- 将本机 `127.0.0.1:5900` VNC 服务转发给平台中的 noVNC。

Agent 仅主动连接平台的 `/api/agent/ws/remote-access`，不会新增公网监听端口。它读取现有 `iot_client.conf` 中的 `server` 与 `token`。
如需让远程访问独立连接另一套平台，可只为本服务设置 `DWC_REMOTE_SERVER`，不会改动控制、媒体和遥测服务共用的配置。

部署到设备工作目录后执行：

```bash
sudo DWC_RUN_USER=wheeltec \
  DWC_WORK_DIR=/home/wheeltec/Dong/DevicesWebControl \
  DWC_REMOTE_ROOT=/home/wheeltec \
  ./deploy.sh
```

文件删除不递归处理非空目录，避免网页误操作造成大范围数据丢失。
