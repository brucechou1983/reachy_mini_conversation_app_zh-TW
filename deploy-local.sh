#!/usr/bin/env bash
# Deploy the conversation app (zh-TW) to the local Reachy Mini venv.
# Usage: ./deploy-local.sh
set -euo pipefail

VENV="/Applications/Reachy Mini Control.app/Contents/Resources/reachy_mini_conversation_app_zh_tw_venv"
PIP="$VENV/bin/pip"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -x "$PIP" ]]; then
    echo "Error: Reachy Mini venv not found at $VENV" >&2
    exit 1
fi

echo "Installing reachy_mini_conversation_app_zh_tw from $PROJECT_DIR ..."
"$PIP" install --force-reinstall "$PROJECT_DIR"

# Patch the daemon dashboard's apps.js to fix the gear icon in WKWebView.
# The native Reachy Mini Control app renders the dashboard in a WKWebView,
# which silently drops <a target="_blank"> links. Replace with same-window
# navigation so clicking the gear icon actually opens the settings page.
APPS_JS="$VENV/lib/python3.12/site-packages/reachy_mini/daemon/app/dashboard/static/js/apps.js"
if [[ -f "$APPS_JS" ]]; then
    if grep -q "settingsLink.target = '_blank'" "$APPS_JS"; then
        sed -i '' \
            -e "s|settingsLink.target = '_blank';|settingsLink.target = '_self';|" \
            "$APPS_JS"
        echo "Patched apps.js: gear icon now navigates in-place (WKWebView fix)."
    else
        echo "apps.js already patched or format changed, skipping."
    fi
fi

echo "Done. Relaunch the app on the robot to pick up changes."
