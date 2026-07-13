#!/bin/bash

set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "错误: 请使用 sudo 运行此脚本。" >&2
  exit 1
fi

RUN_USER="${DWC_RUN_USER:-${SUDO_USER:-wheeltec}}"
WORK_DIR="${DWC_WORK_DIR:-/home/${RUN_USER}/Dong/DevicesWebControl}"
REMOTE_ROOT="${DWC_REMOTE_ROOT:-/home/${RUN_USER}}"
REMOTE_SERVER="${DWC_REMOTE_SERVER:-}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --user)
      RUN_USER="$2"
      shift 2
      ;;
    --work-dir)
      WORK_DIR="${2%/}"
      shift 2
      ;;
    --root)
      REMOTE_ROOT="${2%/}"
      shift 2
      ;;
    *)
      echo "错误: 未知参数 $1" >&2
      exit 2
      ;;
  esac
done

for file in remote_access_agent.py iot_client.conf; do
  if [ ! -f "${WORK_DIR}/${file}" ]; then
    echo "错误: 缺少 ${WORK_DIR}/${file}" >&2
    exit 1
  fi
done

if ! id "${RUN_USER}" >/dev/null 2>&1; then
  echo "错误: 用户 ${RUN_USER} 不存在" >&2
  exit 1
fi

if ! /usr/bin/python3 -c 'import websockets' >/dev/null 2>&1; then
  echo "错误: 系统 Python 缺少 websockets，请先安装 python3-websockets。" >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "错误: 车端缺少 OpenSSH 客户端。" >&2
  exit 1
fi

chmod 0755 "${WORK_DIR}/remote_access_agent.py"
chown "${RUN_USER}:${RUN_USER}" "${WORK_DIR}/remote_access_agent.py"

cat > /etc/systemd/system/DevicesWebControl-remote_access_agent.service <<EOF
[Unit]
Description=DevicesWebControl Remote SSH File and VNC Agent
After=network-online.target ssh.service x11vnc.service
Wants=network-online.target ssh.service x11vnc.service

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_USER}
WorkingDirectory=${WORK_DIR}
Environment="DWC_REMOTE_ROOT=${REMOTE_ROOT}"
Environment="DWC_REMOTE_SSH_PORT=22"
Environment="DWC_REMOTE_VNC_PORT=5900"
Environment="DWC_REMOTE_SERVER=${REMOTE_SERVER}"
ExecStart=/usr/bin/python3 ${WORK_DIR}/remote_access_agent.py --config ${WORK_DIR}/iot_client.conf
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable DevicesWebControl-remote_access_agent.service
systemctl restart DevicesWebControl-remote_access_agent.service
systemctl --no-pager --full status DevicesWebControl-remote_access_agent.service
