#!/usr/bin/env bash
#
# 啟動 Reachy Mini 對話程式。
# Launch the Reachy Mini conversation app.
#
# 用法 / Usage:
#   ./scripts/run.sh                 # console 模式
#   ./scripts/run.sh --gradio        # Gradio 網頁介面
#   ./scripts/run.sh --no-camera     # 不使用相機
#   ./scripts/run.sh --help          # 看所有旗標
#
# 任何旗標都會原封不動傳給 app。
# 必須先跑過 ./scripts/setup-mac.sh，且 Reachy Mini daemon 要在執行中。
set -euo pipefail

# 從 repo 根目錄執行，讓 app 能找到 .env (config 以 cwd 往上搜尋 .env)。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -d .venv ]; then
  printf "\033[33m找不到 .venv，請先執行 ./scripts/setup-mac.sh\033[0m\n" >&2
  exit 1
fi

exec uv run reachy-mini-conversation-app-zh-tw "$@"
