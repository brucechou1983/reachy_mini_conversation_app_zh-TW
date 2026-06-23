#!/usr/bin/env bash
#
# 在一台新的 Mac 上一鍵安裝本應用程式。
# One-command setup for this app on a fresh Mac.
#
# 用法 / Usage:
#   ./scripts/setup-mac.sh
#
# 做的事 / What it does:
#   1. 確認 (必要時安裝) uv —— Python 套件/環境管理工具
#   2. 用 uv.lock 重現完全一致的相依環境 (uv sync --frozen)
#   3. 若沒有 .env 就從 .env.example 複製一份
#   4. 印出下一步 (填 API key、啟動 daemon、執行 app)
#
# 這個腳本是冪等的：重複執行是安全的。
set -euo pipefail

# --- 移動到 repo 根目錄 (腳本所在目錄的上一層) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
info() { printf "  • %s\n" "$1"; }
warn() { printf "\033[33m  ! %s\033[0m\n" "$1"; }

bold "==> Reachy Mini 對話程式 — Mac 安裝"

# --- 1. 確認 uv ---
if ! command -v uv >/dev/null 2>&1; then
  warn "找不到 uv，正在安裝 (官方安裝程式)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # 安裝後 uv 通常落在 ~/.local/bin；把它加進本次 shell 的 PATH。
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv >/dev/null 2>&1; then
    warn "uv 安裝後仍找不到。請重開終端機，或把 ~/.local/bin 加入 PATH 後再執行一次。"
    exit 1
  fi
fi
info "uv: $(uv --version)"

# --- 2. 用 lockfile 重現環境 ---
bold "==> 安裝相依套件 (uv sync --frozen)…"
uv sync --frozen
info "虛擬環境已就緒：.venv"

# 想要本機視覺 / 無線版時，可改用下列其中一行 (二選一或自行組合)：
#   uv sync --frozen --extra all_vision        # 全部視覺方案
#   uv sync --frozen --extra reachy_mini_wireless

# --- 3. .env ---
if [ ! -f .env ]; then
  cp .env.example .env
  info "已從 .env.example 建立 .env"
else
  info ".env 已存在，保留不動"
fi

# 檢查 OPENAI_API_KEY 是否已填
if grep -qE '^OPENAI_API_KEY=.+' .env; then
  info "OPENAI_API_KEY 已設定"
  OPENAI_OK=1
else
  warn "OPENAI_API_KEY 尚未填寫 —— 啟動前必填"
  OPENAI_OK=0
fi

# --- 4. 下一步 ---
echo
bold "==> 安裝完成。下一步："
if [ "${OPENAI_OK}" -eq 0 ]; then
  echo "  1) 編輯 .env，填入 OPENAI_API_KEY (必填)。"
  echo "     選填：GEMINI_API_KEY (說故事 + 記憶整理)、TAVILY_API_KEY (網路搜尋)。"
else
  echo "  1) (選填) 在 .env 補上 GEMINI_API_KEY / TAVILY_API_KEY。"
fi
echo "  2) 確認 Reachy Mini daemon 已在執行 (來自 Reachy Mini SDK)。"
echo "     參見 https://github.com/pollen-robotics/reachy_mini/"
echo "  3) 啟動 app："
echo "       ./scripts/run.sh            # console 模式"
echo "       ./scripts/run.sh --gradio   # 開啟 Gradio 網頁介面"
echo
