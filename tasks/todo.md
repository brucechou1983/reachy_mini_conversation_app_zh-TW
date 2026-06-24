# Task: 新增「打開故事書架」工具 + 點封面就開讀

## 目標
讓汪汪可以打開 http://localhost:7860/reader 的故事書架，小朋友可以選之前做好的書。

## 設計
- 新工具 `story_book_shelf`：打開書架頁面（既有 /reader 已是視覺書架，不需新頁面），
  回傳書名+book_id+頁數清單給模型參考。
- **點封面就開讀**（對齊 read-along 的 select 機制）：
  - StoryStore 加 `bind_handler(handler, loop)`（鏡像 ReadAlongStore）。
  - 新 route `POST /reader/api/books/{id}/select` → 注入訊息給 handler → 模型呼叫 story_book_open。
  - reader.js：點卡片 → POST select → 再導頁。
  - story_book_shelf 呼叫時綁定 handler。

## 對抗式審查發現（已驗證）
1. **[HIGH] 點封面是死路**：點卡片只導頁，機器人不知道、不會唸 → 修：select route + 注入（同 read-along）。
2. **[LOW] 同名書無法區分**：清單加 page_count（與 story_book_open 對齊）+ 指示確認書名。
3. **[LOW] headless 時 webbrowser.open 回 False 不丟錯**：訊息謊稱已開 → 修：接回傳值，分支訊息。
   （subjective）is_available 綁 GEMINI：刻意的，與 story_book_open 一致，保留不動。

## To-do
- [x] story_store.py：bind_handler + handler/loop
- [x] story_routes.py：_schedule_injection + _inject_story_select + POST /reader/api/books/{id}/select
- [x] reader.js：點卡片 → POST select → 導頁（data-id 用 raw id 避免雙重編碼）
- [x] story_book_shelf.py：綁定 handler、接 webbrowser 回傳值分支訊息、清單加 page_count
- [x] instructions.txt：說明點選會自動通知 + 同名確認
- [x] tests：store binding / select route / 工具（347 passed）
- [x] ruff + mypy + 全套 pytest 綠
- [ ] 版本 bump（0.4.16）+ uv lock + commit + PR + CI + HF sync

## Review
新工具 `story_book_shelf` + 「點封面就開讀」橋接（對齊既有 read-along 的 tap→robot 機制）。

**交付**
- `story_book_shelf` 工具：打開 /reader 視覺書架、綁定 realtime handler、回傳書名/book_id/頁數清單。
  接 webbrowser.open 回傳值——開不起來（headless）就改用唸書名，不謊稱已開螢幕。
- `POST /reader/api/books/{id}/select`：小朋友點封面 → 注入訊息給 handler → 模型呼叫 story_book_open 開讀。
- StoryStore.bind_handler（鏡像 ReadAlongStore）；`_schedule_injection` 抽共用（read-along 與 story 共用，跨執行緒用 run_coroutine_threadsafe）。
- reader.js：點封面先 POST select 再導頁；handler 沒綁也安全（catch 後照樣開書）。
- instructions：點封面會自動通知、同名書先確認。

**對抗式審查（11 agents）→ 全數處理**
- [HIGH] 點封面是死路 → 已用 select route + 注入修好（核心）。
- [LOW] 同名書 → 清單加 page_count + 指示確認。
- [LOW] headless webbrowser 回 False → 接回傳值分支訊息。
- (subjective) is_available 綁 GEMINI → 刻意保留（與 story_book_open 一致）。

**驗證**：347 passed、ruff+mypy 全綠；工具註冊 + 進 LLM specs + select route 掛載皆已 smoke 驗證。
實機需更新後做一本書→開書架→點封面，確認汪汪會自動開那本書來唸。
