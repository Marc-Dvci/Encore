#!/usr/bin/env bash
# Runs ON the instance (Amazon Linux 2023, arm64) as root, through SSM. Idempotent; keeps /opt/encore/var.
set -euo pipefail
HOST=${1:?usage: setup_instance.sh <host, e.g. 1-2-3-4.sslip.io>}
SRC=$(cd "$(dirname "$0")/.." && pwd)
export TMPDIR=/var/tmp
APP=/opt/encore
CADDY_VERSION=2.10.2

dnf install -y -q python3.11 rsync tar gzip >/dev/null
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
id encore >/dev/null 2>&1 || useradd --system --home-dir $APP --shell /sbin/nologin encore
mkdir -p $APP
rsync -a --delete --exclude var/ --exclude .venv/ "$SRC/" $APP/
mkdir -p $APP/var
[ -x $APP/.venv/bin/python ] || python3.11 -m venv $APP/.venv
$APP/.venv/bin/pip install -q --upgrade pip
$APP/.venv/bin/pip install -q -r $APP/requirements.txt -c $APP/constraints.txt
chown -R encore:encore $APP

if [ ! -x /usr/local/bin/caddy ]; then
  curl -sSL -o /var/tmp/caddy.tgz "https://github.com/caddyserver/caddy/releases/download/v$CADDY_VERSION/caddy_${CADDY_VERSION}_linux_arm64.tar.gz"
  tar -xzf /var/tmp/caddy.tgz -C /usr/local/bin caddy
  id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --create-home --shell /sbin/nologin caddy
fi
mkdir -p /etc/caddy
sed "s/{\$ENCORE_HOST}/$HOST/" $APP/deploy/Caddyfile > /etc/caddy/Caddyfile
install -m 644 $APP/deploy/caddy.service /etc/systemd/system/caddy.service

TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
param() { aws ssm get-parameter --name "/encore/$1" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null || true; }
umask 077
{
  echo "QLOO_API_KEY=$(param QLOO_API_KEY)"
  echo "GEMINI_API_KEY=$(param GEMINI_API_KEY)"
  echo "ENCORE_AI_PROVIDER=gemini"
  echo "ENCORE_GEMINI_MODEL=gemini-3.7-flash"
  echo "ENCORE_AI_UNTIL=2026-11-30"
  echo "ENCORE_AI_DAILY_CAP=600"
  echo "ENCORE_AI_PER_VISITOR_HOURLY=40"
  echo "ENCORE_DATA_DIR=$APP/var"
} > /etc/encore.env
chown root:encore /etc/encore.env && chmod 640 /etc/encore.env
umask 022
for u in encore.service encore-reset.service encore-reset.timer; do
  install -m 644 $APP/deploy/$u /etc/systemd/system/$u
done
systemctl daemon-reload
systemctl enable --now encore caddy encore-reset.timer
systemctl restart encore caddy
sleep 6
curl -s http://127.0.0.1:8000/api/status && echo
