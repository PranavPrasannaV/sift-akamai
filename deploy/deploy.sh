#!/usr/bin/env bash
# Copy the app to the Linode and (re)start it.  Usage: IP=1.2.3.4 bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${IP:?set IP to the Linode IPv4 address}"
tar --exclude=.venv --exclude=web/node_modules --exclude=web/.next --exclude=.git \
    --exclude='__pycache__' --exclude='data/*.db' -czf - . | ssh root@"$IP" "mkdir -p /root/sift && tar -xzf - -C /root/sift"
ssh root@"$IP" 'set -e; cd /root/sift
  /root/.local/bin/uv venv -q --allow-existing .venv -p 3.12
  /root/.local/bin/uv pip install -q -p .venv -r requirements.txt
  cp deploy/sift.service /etc/systemd/system/sift.service
  systemctl disable --now app.service 2>/dev/null || true
  systemctl daemon-reload && systemctl enable -q sift.service && systemctl restart sift.service
  sleep 4; systemctl is-active sift.service; curl -s localhost/health; echo'
