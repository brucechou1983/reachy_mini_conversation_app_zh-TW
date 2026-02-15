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
"$PIP" install --force-reinstall --no-deps "$PROJECT_DIR"

echo "Done. Relaunch the app on the robot to pick up changes."
