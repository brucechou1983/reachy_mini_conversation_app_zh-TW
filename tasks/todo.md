# Task: hotfix — 重開機後對話壞掉（launchctl env 被清）

## 病因（app log 直接證實）
使用者用 `launchctl setenv` 設 HANDLER_TYPE=gemini / REACHY_MINI_CUSTOM_PROFILE / GEMINI_API_KEY。
重開機 → launchd session env 清空 → app 跌回 OpenAI + default profile + 無效 OpenAI 金鑰 →
`session.update` 被拒（invalid_api_key）→ 靜默 aborting startup → 連對話都起不來。
（log: `No .env file found` / `Conversation backend: OpenAI Realtime` / `invalid_request_error.invalid_api_key`）
→ 與 v0.4.17 / #44 完全無關。

## 修法（使用者選 b）
- **耐久 .env**：config.py 新增 `_load_env_files()`，多讀一份 `~/.reachy_mini/.env`
  （或 `$REACHY_MINI_HOME/.env`）當 fallback（override=False，不蓋掉明確 env）。
  優先序：CWD .env > OS env(launchctl) > 耐久 .env。重開機/重裝都不會被清。
- **不要再靜默壞掉**：openai_realtime 在 invalid_api_key 時改印明確可行動訊息
  （指向設定頁 http://localhost:7860/ ＋ `~/.reachy_mini/.env` ＋ 提示 HANDLER_TYPE=gemini），
  不再只是 generic exception 後默默 return。
- 文件：.env.example 頂部說明放置位置；lessons.md 記錄。

## To-do
- [x] config.py _load_env_files + reachy_mini_home（fallback override=False、硬編 ~/.reachy_mini）
- [x] openai_realtime invalid_api_key 明確報錯（in-band ＋ handshake 401 都涵蓋）
- [x] tests：config 優先序 + _is_auth_error 偵測
- [x] .env.example + lessons.md
- [x] ruff + mypy + 全套 pytest（380 passed）+ 端到端 smoke
- [x] 對抗式審查（11 agents）→ 處理
- [x] 版本 bump + uv lock + commit + PR + CI + HF sync（進行中）

## Review
對抗式審查抓到兩點，已修：
- **[HIGH] 報錯分支其實不會觸發**：真正的 auth 失敗可能在 WS handshake（`InvalidStatus` HTTP 401，
  字串不含 invalid_api_key），落在 try 之外。改用 `_is_auth_error()`（涵蓋 in-band 的
  invalid_api_key 字串＝使用者實際案例、handshake 401/403、openai AuthenticationError），
  並在 session.update except 與 start_up（ConnectionClosed 分支＋新增 generic except）都接住 → 才真的「不再靜默」。
- **[LOW] REACHY_MINI_HOME split-brain**：那個 env var 只搬 .env、不搬 books/progress，且 env var
  本身也會被重開機清掉（自相矛盾）→ 移除，硬編 `~/.reachy_mini`。

最終：耐久 fallback `~/.reachy_mini/.env`（override=False，不蓋明確 env）＋ 金鑰無效時明確可行動報錯。
380 passed、ruff/mypy 全綠。

## 使用者要做的
重開機後先 `launchctl setenv ...` 重設、重啟 app（眼前復原）；
之後建一份 `~/.reachy_mini/.env` 放 HANDLER_TYPE=gemini / REACHY_MINI_CUSTOM_PROFILE=english_learner /
GEMINI_API_KEY，就一勞永逸（不再被重開機清掉，也不用 launchctl）。
