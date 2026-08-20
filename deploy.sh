#!/usr/bin/env bash
# 一键部署到远端生产服务器
#
# 用法：
#   ./deploy.sh           # 构建前端 + push 到 prod（自动触发远端 hook 同步 + 重启）
#   ./deploy.sh --no-build  # 跳过前端构建，仅 push（适合只改了后端时）
#
# 前置条件：
#   1. 本地 git 已配置 prod remote（指向远端裸仓库）
#   2. 远端 ~/.ssh/authorized_keys 已包含本地公钥
#   3. 远端 post-receive hook 已就绪（首次部署时已配置）
#
# 前端构建产物 frontend/dist 不在 git 仓库内（被 .gitignore 排除），
# 所以需要单独打包并通过 scp 上传到远端部署目录。

set -e

cd "$(dirname "$0")"
REMOTE_HOST="icclab-aliyungz"
REMOTE_DIR="~/devicewebcontrol"

SKIP_BUILD=false
if [ "$1" = "--no-build" ]; then
  SKIP_BUILD=true
fi

echo "===== 1. 检查工作树状态 ====="
if [ -n "$(git status --porcelain)" ]; then
  echo "工作树有未提交改动，请先 commit 或 stash："
  git status --short
  exit 1
fi
echo "工作树干净，当前 HEAD: $(git rev-parse --short HEAD) on $(git branch --show-current)"

if [ "$SKIP_BUILD" = false ]; then
  echo
  echo "===== 2. 构建前端 ====="
  cd frontend
  npm run build
  cd ..
  echo "前端构建完成，dist 已更新"
fi

echo
echo "===== 3. 上传前端 dist 到远端 ====="
# dist 不在 git 仓库内，需要单独上传
tar -czf /tmp/dwc_dist.tar.gz -C frontend dist
scp /tmp/dwc_dist.tar.gz "$REMOTE_HOST:/tmp/"
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && rm -rf frontend/dist && tar -xzf /tmp/dwc_dist.tar.gz -C frontend/ && rm -f /tmp/dwc_dist.tar.gz"
echo "远端 frontend/dist 已更新"

echo
echo "===== 4. push 到 prod 触发自动部署 ====="
git push prod main

echo
echo "===== 5. 等待服务重启并验证 ====="
sleep 4
ssh "$REMOTE_HOST" 'echo "deploy.log 末尾:" && tail -5 ~/deploy.log && echo && echo "服务状态: $(systemctl --user is-active devicewebcontrol.service)" && echo "健康检查: $(curl -sf http://127.0.0.1:52733/api/health)"'

echo
echo "===== 部署完成 ====="
echo "如需查看完整日志：ssh $REMOTE_HOST tail -30 ~/deploy.log"
