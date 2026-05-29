#!/bin/bash
# Install macOS LaunchAgent for daily framework run.
#
# Usage:
#   bash scripts/install_cron.sh           # install + load
#   bash scripts/install_cron.sh uninstall # remove
#
# Schedule: Mon-Fri 09:30 local time.

set -e

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_PATH="$(which python3)"
PLIST_SRC="${SKILL_DIR}/configs/com.stock-framework.daily.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.stock-framework.daily.plist"
LOG_DIR="${SKILL_DIR}/logs"

ACTION="${1:-install}"

if [ "$ACTION" = "uninstall" ]; then
    if [ -f "$PLIST_DEST" ]; then
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        rm -f "$PLIST_DEST"
        echo "[install_cron] uninstalled $PLIST_DEST"
    else
        echo "[install_cron] not installed."
    fi
    exit 0
fi

if [ ! -f "$PLIST_SRC" ]; then
    echo "[install_cron] ERROR: plist template missing: $PLIST_SRC" >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
mkdir -p "${HOME}/Library/LaunchAgents"

# Substitute template placeholders
sed -e "s|__PYTHON__|${PYTHON_PATH}|g" \
    -e "s|__SKILL_DIR__|${SKILL_DIR}|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

# Reload
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "[install_cron] installed: $PLIST_DEST"
echo "[install_cron] python:    $PYTHON_PATH"
echo "[install_cron] skill_dir: $SKILL_DIR"
echo "[install_cron] logs:      $LOG_DIR/run_daily.{stdout,stderr}.log"
echo
echo "Schedule: Mon-Fri 09:30 local time."
echo "Test run now:  python3 ${SKILL_DIR}/scripts/run_daily.py --quick"
echo "View jobs:     launchctl list | grep stock-framework"
echo "Uninstall:     bash scripts/install_cron.sh uninstall"
