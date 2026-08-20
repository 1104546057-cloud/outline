#!/bin/bash

# 遇到错误即退出
set -e

# 检查是否以 root 权限运行
if [ "$EUID" -ne 0 ]; then
  echo "错误: 请使用 root 权限运行此脚本 (例如: sudo ./deploy.sh)"
  exit 1
fi

echo "=========================================="
echo "开始自动部署 DevicesWebControl Agent"
echo "=========================================="

read -p "请输入运行服务的普通用户名 [直接回车则默认为 nano]: " RUN_USER
RUN_USER=${RUN_USER:-nano}

read -p "请输入部署工作路径 [直接回车则默认为 /home/${RUN_USER}/Dong/DevicesWebControl]: " WORK_DIR
WORK_DIR=${WORK_DIR:-/home/${RUN_USER}/Dong/DevicesWebControl}
# 移除末尾可能的斜杠，保证后续拼接格式统一
WORK_DIR=${WORK_DIR%/}

echo "使用工作路径: $WORK_DIR"

echo ">>> 检查工作目录文件..."
if [ ! -d "$WORK_DIR" ]; then
  echo "错误: 工作路径 $WORK_DIR 不存在！"
  exit 1
fi

REQUIRED_FILES="iot_client.conf iot_client.py robot_control_server.py start_camera.sh"

MISSING_FILES=""
for file in $REQUIRED_FILES; do
  if [ ! -f "$WORK_DIR/$file" ]; then
    MISSING_FILES="$MISSING_FILES $file"
  fi
done

if [ -n "$MISSING_FILES" ]; then
  echo "错误: 缺少以下核心文件，请确认文件已正确上传！"
  for missing in $MISSING_FILES; do
    echo "  - $WORK_DIR/$missing"
  done
  exit 1
fi
echo "文件检查通过！"

echo ">>> 赋予工作目录下所有的 shell 脚本执行权限..."
sudo chmod +x "$WORK_DIR"/*.sh

echo ">>> 2.1 配置 apt 清华源..."
if [ "$RUN_USER" = "pi" ]; then
    DEFAULT_APT_SYS="pi"
elif [ "$RUN_USER" = "nano" ]; then
    DEFAULT_APT_SYS="nano"
else
    DEFAULT_APT_SYS="no"
fi

read -p "配置什么系统的清华源[nano/pi/no，默认为${DEFAULT_APT_SYS}]: " APT_SYS
APT_SYS=${APT_SYS:-$DEFAULT_APT_SYS}

if [ "$APT_SYS" != "no" ]; then
    if [ -f /etc/apt/sources.list ]; then
        sudo mv /etc/apt/sources.list /etc/apt/sources.list.bak
        echo ">> 已备份 /etc/apt/sources.list -> /etc/apt/sources.list.bak"
    fi

    if [ -f /etc/apt/sources.list.d/debian.sources ]; then
        sudo mv /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/debian.sources.bak
        echo ">> 已备份 /etc/apt/sources.list.d/debian.sources -> /etc/apt/sources.list.d/debian.sources.bak"
    fi

    if [ -f /etc/apt/sources.list.d/raspi.sources ]; then
        sudo mv /etc/apt/sources.list.d/raspi.sources /etc/apt/sources.list.d/raspi.sources.bak
        echo ">> 已备份 /etc/apt/sources.list.d/raspi.sources -> /etc/apt/sources.list.d/raspi.sources.bak"
    fi
fi

if [ "$APT_SYS" = "pi" ]; then
    sudo tee /etc/apt/sources.list > /dev/null << 'EOF'
# Debian 13 Trixie
# 默认注释了源码镜像以提高 apt update 速度，如有需要可自行取消注释
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie main contrib non-free non-free-firmware
# deb-src https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie main contrib non-free non-free-firmware

deb https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie-updates main contrib non-free non-free-firmware
# deb-src https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie-updates main contrib non-free non-free-firmware

deb https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie-backports main contrib non-free non-free-firmware
# deb-src https://mirrors.tuna.tsinghua.edu.cn/debian/ trixie-backports main contrib non-free non-free-firmware

# 以下安全更新软件源为镜像站配置
deb https://mirrors.tuna.tsinghua.edu.cn/debian-security trixie-security main contrib non-free non-free-firmware
# deb-src https://mirrors.tuna.tsinghua.edu.cn/debian-security trixie-security main contrib non-free non-free-firmware

# Raspberry Pi 软件源
deb https://mirrors.tuna.tsinghua.edu.cn/raspberrypi/ trixie main
EOF
    sudo apt update
elif [ "$APT_SYS" = "nano" ]; then
    sudo tee /etc/apt/sources.list > /dev/null << 'EOF'
deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic main restricted universe multiverse
# deb-src http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic main restricted universe multiverse

deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-updates main restricted universe multiverse
# deb-src http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-updates main restricted universe multiverse

deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-backports main restricted universe multiverse
# deb-src http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-backports main restricted universe multiverse

deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-security main restricted universe multiverse
# deb-src http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ bionic-security main restricted universe multiverse
EOF
    sudo apt update
else
    echo ">> 跳过清华源配置"
fi

echo ">>> 2.2 安装编译依赖..."
if [ "$APT_SYS" = "nano" ]; then
    sudo apt-get -y install gcc g++ cmake libjpeg-dev libv4l-dev
else
    sudo apt-get -y install gcc g++ cmake libjpeg62-turbo-dev
fi

echo ">>> 2.3 编译安装 mjpg_streamer..."
if [ ! -d "mjpg-streamer" ]; then
    git clone https://github.com/jacksonliam/mjpg-streamer.git
fi
cd mjpg-streamer/mjpg-streamer-experimental
make
sudo make install
cd ../..

echo ">>> 3. 安装 GPS 工具并配置..."
sudo apt-get -y install gpsd gpsd-clients

echo ">> 配置 /etc/default/gpsd..."
sudo tee /etc/default/gpsd > /dev/null << 'EOF'
# /etc/default/gpsd
START_DAEMON="true"
GPSD_OPTIONS="-n -s 38400"
DEVICES="/dev/ttyUSB0"
USBAUTO="true"
GPSD_SOCKET="/var/run/gpsd.sock"
EOF

sudo systemctl restart gpsd
sudo systemctl enable gpsd

echo ">>> 4. 安装 Python 依赖 (系统状态、串口通信、WebSocket 与 UPS 电量读取)..."
sudo apt-get -y install python3-smbus python3-serial python3-psutil python3-websockets iw wireless-tools

if [ -f /etc/nv_tegra_release ]; then
    echo ">> 检测到 NVIDIA Jetson，安装 jtop 遥测依赖..."
    sudo apt-get -y install python3-pip
    sudo -H /usr/bin/python3 -m pip install jetson-stats
    sudo systemctl daemon-reload
    sudo systemctl restart jtop.service || echo "警告: jtop.service 启动失败，GPU 遥测将自动跳过。"
fi

echo ">>> 5. 授权并配置服务..."

echo ">> 5.1 将用户加入硬件访问组 (dialout, video, i2c)..."
sudo usermod -aG dialout,video,i2c ${RUN_USER} || echo "警告: 组分配可能未完全成功，请检查系统组。"

echo ">> 5.2 配置主动连接服务 (WebSocket Agent)..."
sudo tee /etc/systemd/system/DevicesWebControl-robot_control_server.service > /dev/null << EOF
[Unit]
Description=DevicesWebControl Outbound WebSocket Agent
After=network-online.target DevicesWebControl-camera.service
Wants=network-online.target DevicesWebControl-camera.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${WORK_DIR}/robot_control_server.py --config ${WORK_DIR}/iot_client.conf
WorkingDirectory=${WORK_DIR}/
Restart=always
RestartSec=3
User=${RUN_USER}
Group=${RUN_USER}

[Install]
WantedBy=multi-user.target
EOF

echo ">> 5.3 配置 IoT 服务 (iot_client)..."
sudo tee /etc/systemd/system/DevicesWebControl-iot_client.service > /dev/null << EOF
[Unit]
Description=DevicesWebControl IoT Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${WORK_DIR}
ExecStart=/usr/bin/python3 ${WORK_DIR}/iot_client.py --config ${WORK_DIR}/iot_client.conf
Restart=always
RestartSec=5
User=${RUN_USER}

[Install]
WantedBy=multi-user.target
EOF

echo ">> 5.4 配置摄像头采集服务 (camera)..."
sudo tee /etc/systemd/system/DevicesWebControl-camera.service > /dev/null << EOF
[Unit]
Description=DevicesWebControl USB Camera MJPEG Stream
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
Group=video
ExecStart=${WORK_DIR}/start_camera.sh
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo ">> 启动并激活相关服务..."
sudo systemctl daemon-reload

sudo systemctl enable DevicesWebControl-robot_control_server
sudo systemctl start DevicesWebControl-robot_control_server

sudo systemctl enable DevicesWebControl-iot_client
sudo systemctl start DevicesWebControl-iot_client

sudo systemctl enable DevicesWebControl-camera
sudo systemctl start DevicesWebControl-camera

echo "=========================================="
echo "部署完成！请确认 iot_client.conf 已填写公网入口和平台生成的设备 Token。"
echo "=========================================="
