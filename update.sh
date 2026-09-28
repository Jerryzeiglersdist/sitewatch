#!/usr/bin/env bash
# Pull the latest sitewatch from GitHub and restart the service if anything changed.
# Run by the sitewatch-update.timer every 10 minutes, or by hand:  sudo /opt/sitewatch/update.sh
# Appends to logs/update.log (trimmed to the last 500 lines). .env, venv/ and logs/ are never touched.
set -euo pipefail

DEST=/opt/sitewatch
BRANCH=main
LOG="$DEST/logs/update.log"
mkdir -p "$DEST/logs"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

cd "$DEST"
if ! git fetch --quiet origin "$BRANCH" 2>>"$LOG"; then
  log "fetch failed (no internet?)"; exit 0
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
if [[ "$LOCAL" == "$REMOTE" ]]; then
  [[ "${1:-}" == "-v" ]] && log "up to date at ${LOCAL:0:7}"
  exit 0
fi

log "updating ${LOCAL:0:7} -> ${REMOTE:0:7}"
git log --oneline "$LOCAL..$REMOTE" | sed 's/^/    /' | tee -a "$LOG"
git reset --hard --quiet "origin/$BRANCH"
chmod +x "$DEST"/*.sh

if git diff --name-only "$LOCAL" "$REMOTE" | grep -q '^requirements.txt$'; then
  log "requirements.txt changed; installing"
  "$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt" >>"$LOG" 2>&1
fi

for unit in sitewatch.service sitewatch-status.service sitewatch-update.service sitewatch-update.timer; do
  if [[ -f "$DEST/$unit" ]] && ! cmp -s "$DEST/$unit" "/etc/systemd/system/$unit"; then
    cp "$DEST/$unit" "/etc/systemd/system/$unit"; RELOAD=1
  fi
done
[[ "${RELOAD:-}" ]] && systemctl daemon-reload

if git diff --name-only "$LOCAL" "$REMOTE" | grep -qE '^(sitewatch\.py|games\.py|sitewatch\.service)$'; then
  systemctl restart sitewatch && log "sitewatch restarted"
fi
if git diff --name-only "$LOCAL" "$REMOTE" | grep -qE '^(status\.py|sitewatch-status\.service)$'; then
  systemctl restart sitewatch-status && log "status page restarted"
fi

tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
log "done"
