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

echo ">>> 2.1 配置 apt 清华源..."
if [ -f /etc/apt/sources.list ]; then
    sudo mv /etc/apt/sources.list /etc/apt/sources.list.bak
fi

if [ -f /etc/apt/sources.list.d/debian.sources ]; then
    sudo mv /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/debian.sources.bak
fi

if [ -f /etc/apt/sources.list.d/raspi.sources ]; then
    sudo mv /etc/apt/sources.list.d/raspi.sources /etc/apt/sources.list.d/raspi.sources.bak
fi

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

echo ">>> 2.2 安装编译依赖..."
sudo apt-get -y install gcc g++ cmake libjpeg62-turbo-dev

echo ">>> 2.3 编译安装 mjpg_streamer..."
if [ ! -d "mjpg-streamer" ]; then
    git clone https://github.com/jacksonliam/mjpg-streamer.git
fi
cd mjpg-streamer/mjpg-streamer-experimental
make
sudo make install
cd ../..

echo ">>> 3. 安装 GPS 工具..."
sudo apt-get -y install gpsd gpsd-clients

echo ">>> 4. 配置服务..."

echo ">> 4.1 配置控制服务 (robot_control_server)..."
sudo tee /etc/systemd/system/DevicesWebControl-robot_control_server.service > /dev/null << 'EOF'
[Unit]
Description=DevicesWebControl Robot Control Server

[Service]
ExecStart=/usr/bin/python3 /home/pi/DevicesWebControl/robot_control_server.py
WorkingDirectory=/home/pi/DevicesWebControl/
Restart=always
User=pi
Group=pi

[Install]
WantedBy=multi-user.target
EOF

echo ">> 4.2 配置 IoT 服务 (iot_client)..."
sudo tee /etc/systemd/system/DevicesWebControl-iot_client.service > /dev/null << 'EOF'
[Unit]
Description=DevicesWebControl IoT Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/DevicesWebControl
ExecStart=/usr/bin/python3 /home/pi/DevicesWebControl/iot_client.py --config /home/pi/DevicesWebControl/iot_client.conf
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
EOF

echo ">> 4.3 配置摄像头采集服务 (camera)..."
sudo tee /etc/systemd/system/DevicesWebControl-camera.service > /dev/null << 'EOF'
[Unit]
Description=DevicesWebControl USB Camera MJPEG Stream
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=video
ExecStart=/home/pi/DevicesWebControl/start_camera.sh
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

echo ">>> 4.4 授权 pi 用户重启 iot 服务..."
echo "pi ALL=(root) NOPASSWD: /usr/bin/systemctl restart DevicesWebControl-iot_client" | sudo tee /etc/sudoers.d/deviceswebcontrol
sudo chmod 0440 /etc/sudoers.d/deviceswebcontrol

echo "=========================================="
echo "部署完成！接下来请进入控制台进行添加设备。"
echo "=========================================="
