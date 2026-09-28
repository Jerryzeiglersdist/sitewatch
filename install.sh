#!/usr/bin/env bash
# One-shot installer for sitewatch on Raspberry Pi OS (Bookworm or Bullseye).
# Run from the folder containing sitewatch.py:   sudo bash install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash install.sh" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST=/opt/sitewatch

echo "==> Installing OS packages"
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev build-essential

echo "==> Copying files to $DEST"
mkdir -p "$DEST"
cp "$SRC_DIR"/sitewatch.py "$SRC_DIR"/status.py "$SRC_DIR"/update.sh "$SRC_DIR"/requirements.txt "$SRC_DIR"/*.service "$SRC_DIR"/*.timer "$DEST"/
chmod +x "$DEST"/*.sh
[[ -f "$DEST/.env" ]] || cp "$SRC_DIR/.env.example" "$DEST/.env"

echo "==> Creating virtualenv and installing Python packages (rpi_ws281x compiles; ~2 min on a Pi 3)"
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

echo "==> Disabling onboard audio (GPIO18 PWM is shared with it)"
CONFIG=/boot/firmware/config.txt
[[ -f "$CONFIG" ]] || CONFIG=/boot/config.txt
if grep -qE '^dtparam=audio=on' "$CONFIG"; then
  sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CONFIG"
elif ! grep -qE '^dtparam=audio=off' "$CONFIG"; then
  echo "dtparam=audio=off" >> "$CONFIG"
fi
# The analog audio module fights the PWM driver; keep it from loading.
echo "blacklist snd_bcm2835" > /etc/modprobe.d/sitewatch-blacklist.conf

echo "==> Installing systemd service"
cp "$SRC_DIR"/sitewatch.service "$SRC_DIR"/sitewatch-status.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sitewatch.service sitewatch-status.service

echo
echo "Installed. Edit $DEST/.env if you want to change the URL or brightness, then:"
echo "    sudo reboot"
echo "After reboot:"
echo "    sudo systemctl status sitewatch"
echo "    tail -f $DEST/logs/sitewatch_*.log     or open http://$(hostname).local:8080/"
echo "To have the Pi pull updates from GitHub on its own, see bootstrap.sh"
echo "Wiring test (stop the service first):"
echo "    sudo systemctl stop sitewatch && sudo $DEST/venv/bin/python $DEST/sitewatch.py --test"
