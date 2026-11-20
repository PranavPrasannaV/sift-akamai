#!/usr/bin/env bash
# Build the dashboard, copy the app to the Linode, and (re)start both services:
#   sift-web  Next.js dashboard (Sift's original UI) on port 80, proxying /api/v1
#   sift      Python API, matcher and folder watcher on 127.0.0.1:8000
# Usage: IP=1.2.3.4 bash deploy/deploy.sh      (needs node + npm locally, uv on the Linode)
set -euo pipefail
cd "$(dirname "$0")/.."
: "${IP:?set IP to the Linode IPv4 address}"

(cd web && npm ci --no-audit --no-fund --loglevel=error && npm run build)
cp -r web/.next/static web/.next/standalone/.next/static
[ -d web/public ] && cp -r web/public web/.next/standalone/public

tar --exclude=.venv --exclude=web --exclude=.git \
    --exclude='__pycache__' --exclude='data/*.db' -czf - . | ssh root@"$IP" "mkdir -p /root/sift && tar -xzf - -C /root/sift"
tar -czf - -C web/.next/standalone . | ssh root@"$IP" "rm -rf /root/sift-web && mkdir -p /root/sift-web && tar -xzf - -C /root/sift-web"

ssh root@"$IP" 'set -e; cd /root/sift
  [ -x /opt/node/bin/node ] || (mkdir -p /opt/node && curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar -xJ -C /opt/node --strip-components=1)
  /root/.local/bin/uv venv -q --allow-existing .venv -p 3.12
  /root/.local/bin/uv pip install -q -p .venv -r requirements.txt
  cp deploy/sift.service deploy/sift-web.service /etc/systemd/system/
  systemctl disable --now app.service 2>/dev/null || true
  systemctl daemon-reload && systemctl enable -q sift.service sift-web.service
  systemctl restart sift.service sift-web.service
  sleep 5; systemctl is-active sift.service sift-web.service; curl -s localhost/health; echo'
