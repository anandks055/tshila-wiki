#!/usr/bin/env bash
# Bootstrap an Oracle Cloud Always Free VM for the read-only wiki API.
# Run as root on a fresh Ubuntu 22.04/24.04 ARM instance:
#   curl -fsSL <raw-url>/setup-vm.sh | bash
# Or copy this repo to the VM and run: sudo bash deploy/oracle-vm/setup-vm.sh

set -euo pipefail

echo "==> Installing packages"
apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx ufw rsync git

echo "==> Enabling Docker"
systemctl enable --now docker

echo "==> Creating data and app directories"
mkdir -p /data/wiki-articles
mkdir -p /opt/wiki-api

echo "==> Firewall: allow SSH, HTTP, HTTPS"
ufw allow OpenSSH
ufw allow "Nginx Full"
ufw --force enable

echo "==> Copy deployment files into /opt/wiki-api"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cp "${REPO_ROOT}/api_server.py" /opt/wiki-api/
cp "${REPO_ROOT}/requirements.txt" /opt/wiki-api/
cp "${REPO_ROOT}/Dockerfile" /opt/wiki-api/
cp "${REPO_ROOT}/docker-compose.yml" /opt/wiki-api/

if [[ ! -f /opt/wiki-api/.env ]]; then
  cp "${SCRIPT_DIR}/env.example" /opt/wiki-api/.env
  echo "WARNING: edit /opt/wiki-api/.env and set API_KEY before going live."
fi

echo "==> Installing systemd unit"
cp "${SCRIPT_DIR}/wiki-api.service" /etc/systemd/system/wiki-api.service
systemctl daemon-reload
systemctl enable wiki-api

echo "==> Installing nginx site (edit server_name before certbot)"
cp "${SCRIPT_DIR}/nginx-wiki-api.conf" /etc/nginx/sites-available/wiki-api
ln -sf /etc/nginx/sites-available/wiki-api /etc/nginx/sites-enabled/wiki-api
nginx -t
systemctl reload nginx

cat <<'EOF'

Setup complete. Next steps:

1. Sync articles from the university server (outbound only):
     bash deploy/oracle-vm/sync-articles.sh <vm-user>@<vm-ip>

2. On the VM, edit secrets:
     nano /opt/wiki-api/.env

3. Edit nginx server_name if needed:
     nano /etc/nginx/sites-available/wiki-api

4. Start the API:
     systemctl start wiki-api

5. Issue TLS certificate:
     certbot --nginx -d api.bheri.in

6. In the frontend repo, set:
     VITE_API_URL=https://api.bheri.in
     VITE_API_KEY=<same value as API_KEY in .env>

EOF
