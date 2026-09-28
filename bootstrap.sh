#!/usr/bin/env bash
# One-time: turn an existing /opt/sitewatch install into a git checkout that
# updates itself from GitHub. Keeps .env, venv/ and logs/ exactly as they are.
#
#   curl -fsSL https://raw.githubusercontent.com/OWNER/sitewatch/main/bootstrap.sh | sudo bash -s OWNER
#
# For a private repo, first put a read-only deploy key at /root/.ssh/id_ed25519 and use:
#   REPO=git@github.com:OWNER/sitewatch.git  sudo -E bash bootstrap.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

OWNER="${1:-}"
REPO="${REPO:-https://github.com/${OWNER}/sitewatch.git}"
DEST=/opt/sitewatch
[[ -n "$OWNER" || -n "${REPO:-}" ]] || { echo "usage: bootstrap.sh GITHUB_OWNER" >&2; exit 1; }

echo "==> git + tools"
apt-get install -y -qq git iw >/dev/null

echo "==> turning $DEST into a checkout of $REPO"
mkdir -p "$DEST"; cd "$DEST"
[[ -d .git ]] || git init -q -b main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"
git config user.email "sitewatch@$(hostname)"; git config user.name "sitewatch"
git fetch -q origin main
git reset -q --hard origin/main         # only tracked files change; .env/venv/logs are untracked
chmod +x "$DEST"/*.sh
[[ -f "$DEST/.env" ]] || cp "$DEST/.env.example" "$DEST/.env"

echo "==> systemd units (service, status page, update timer)"
for unit in sitewatch.service sitewatch-status.service sitewatch-update.service sitewatch-update.timer; do
  cp "$DEST/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable -q --now sitewatch-status.service sitewatch-update.timer
systemctl restart sitewatch.service

echo "==> Wi-Fi: turn off power saving (a power-save stall looks like an internet outage)"
CON=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | grep ':wlan0$' | cut -d: -f1 || true)
if [[ -n "$CON" ]]; then
  nmcli connection modify "$CON" wifi.powersave 2 && echo "    powersave disabled on '$CON'"
  iw dev wlan0 set power_save off 2>/dev/null || true
fi

echo
echo "Done. sitewatch now tracks $REPO"
echo "  status page:  http://$(hostname).local:8080/"
echo "  update now:   sudo $DEST/update.sh -v      (the timer also checks every 10 min)"
systemctl --no-pager --lines=0 status sitewatch sitewatch-status | grep -E 'sitewatch|Active'
