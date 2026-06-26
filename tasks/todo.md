# Task: 修 Gemini 後端「閒置觸發工具呼叫 → 講話講到一半完全卡住」

## 症狀
HANDLER_TYPE=gemini。小朋友安靜一陣子 → 觸發 idle nudge → 模型呼叫 dance +
save_profile_memory → 之後整個卡死，log 只剩 setPeerStatus/Pong 心跳，無錯誤、無 traceback。

## 根因（已對抗式驗證）
`gemini_realtime.py` 的 idle 路徑：`send_idle_signal` 設 `is_idle_tool_call=True`，
`_handle_tool_call` 便「跳過」`send_tool_response`。但 Gemini Live 是 blocking
function call：沒收到 tool response，模型這個 turn 永遠不結束、也不再出聲（沒有協定層
timeout）。又因為是「閒置」觸發，沒有後續使用者輸入來把它解開 → 永久卡在講話中。
這是從 OpenAI handler 誤搬：OpenAI 的 is_idle_tool_call 是用來「抑制事後的
response.create 口語回覆」（always 會送 function_call_output），而 Gemini Live 根本
沒有獨立的 response 步驟。

## 修法（最小、對齊 OpenAI 正確行為）
- `_handle_tool_call`：只要有 function call，就「一律」`send_tool_response`。
- 移除無用的 `is_idle_tool_call` flag（init + send_idle_signal + 跳過邏輯）。
- 行為差異：閒置跳完舞後，汪汪「可能」順口講一句（而不是卡死）——嚴格更好。

## 驗證
- 新增 2 個回歸測試（test_gemini_realtime.py）：tool call 一律回 response、idle nudge 後也回。
  舊碼在第二個測試會失敗（重現 bug）。
- 全套 414 passed、ruff + mypy 全綠。
- 對抗式 skeptic：確認根因充分、修法安全；排除 dance queue/head_wobbler.reset/silent
  session drop 等替代假說（dance queue_move 非阻塞、reset 不阻塞、掉線會有 log+重連）。

## 後續（超出本次範圍，記錄）
- Gemini handler 存記憶後沒有像 OpenAI 那樣刷新 system instruction（新記憶要下次 session 才生效）。
- MemoryStore.add 在 event loop 上做同步檔案 I/O（目前資料小，影響可忽略）。

## Review
完成。實機：小朋友安靜時汪汪自己跳舞/做表情後，會正常接回對話，不再卡死。
