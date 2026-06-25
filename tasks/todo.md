# Task: 書架文案（聽 vs 讀）+ 無螢幕時停用視覺功能

## A. 文案：聽故事 vs 自己讀
- 故事書架 reader.html → 標題「聽故事 / Listen to a story」+ 標語「汪汪唸給你聽」（reader.css 加 .shelf-sub/.shelf-tagline）。
- 英文書架 read_along_shelf.html → 「我自己讀英文 / I read it myself」+「你自己讀、汪汪在旁邊陪你」。
- english_learner instructions → 兩活動明標【聽故事】vs【自己讀】；汪汪先問「你想聽汪汪說故事，還是自己讀英文？」。

## B. 無螢幕偵測 → 停用視覺功能、順聊天
- config.detect_screen()：override REACHY_MINI_HAS_SCREEN > Linux $DISPLAY/$WAYLAND > macOS CoreGraphics(Online) > 預設 True（fail-safe）。啟動時算一次 → config.SCREEN_AVAILABLE。
- core_tools：Tool.requires_screen（10 個故事/帶讀工具設 True）；_tool_enabled 在註冊、get_tool_specs、**dispatch_tool_call** 三處 gate。無螢幕 → 視覺工具消失、聊天工具保留。
- prompts：無螢幕時附註告知模型視覺功能停用（且只在該 profile 真的有視覺工具時才附）。

## 對抗式審查（13 agents）→ 已修
- **[HIGH] dispatch 沒 gate disabled 工具**：specs 雖隱藏，但 dispatch_tool_call 用 _ALL_TOOL_INSTANCES，幻覺/回音/路由注入仍可執行（甚至翻動 activity state）→ 在 dispatch 開頭加 _tool_enabled 守門（gate 之前），擋下並回 error，不動 state。
- **[HIGH] 無螢幕附註注入每個 profile**：非童書 persona 也被塞童書文字 → 改成只有「該 profile 真的有 requires_screen 工具」時才附。
- **[MED] CGGetActiveDisplayList（可繪製）→ 改 CGGetOnlineDisplayList（實際接上）**：避免 clamshell/休眠誤判成沒螢幕、停掉有螢幕機器的功能。
- **[LOW] 指示軟矛盾**：強化附註「也不要問聽還是讀」。
- (subjective) 啟動算一次不重評 → 正是「啟動時偵測」的需求，保留。

## 驗證
- 本機（有螢幕）Online 偵測 True（不誤關）；REACHY_MINI_HAS_SCREEN=false → 10 個視覺工具從 specs 消失、聊天工具留、dispatch 也擋下、附註出現。
- 391 passed、ruff + mypy 全綠。

## Review
完成。實機：無螢幕的汪汪啟動後應只聊天、不提故事書/繪本；有螢幕則照舊，且書架標題清楚分「聽 vs 讀」。
可用 REACHY_MINI_HAS_SCREEN=true/false 覆寫偵測（建議寫進 ~/.reachy_mini/.env）。
