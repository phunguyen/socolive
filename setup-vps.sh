#!/usr/bin/env bash
# Bootstrap the crawler on a Linux VPS (must be in an allowed region — VN).
# Run once from inside the cloned repo:  bash setup-vps.sh
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "❌ thiếu python3 — sudo apt install -y python3"; exit 1; }
command -v git >/dev/null     || { echo "❌ thiếu git — sudo apt install -y git"; exit 1; }

echo "→ kiểm tra region..."
code="$(curl -sS -o /dev/null -w '%{http_code}' 'https://json.vnres.co/all_live_rooms.json' || true)"
echo "  API HTTP $code"
[ "$code" = "200" ] || { echo "❌ API không trả 200 (VPS có thể bị chặn region). Dừng."; exit 1; }

echo "→ chạy thử deploy..."
bash deploy.sh

echo "→ cài cron (mỗi 5 phút, idempotent)..."
line="*/5 * * * * cd $(pwd) && /bin/bash deploy.sh >> deploy.log 2>&1"
( crontab -l 2>/dev/null | grep -vF "deploy.sh" ; echo "$line" ) | crontab -
echo "✅ xong. cron hiện tại:"
crontab -l | grep deploy.sh
