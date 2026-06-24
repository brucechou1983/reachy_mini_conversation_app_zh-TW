# Task: 兩個書架徹底分開（AI讀繪本 vs 英文朗讀）+ 正確指定當下活動

## 使用者決定
同一隻汪汪、可切換活動；在「程式碼層」強制分開（不靠提示）。
- 說「做故事書」→ 切到繪本活動、關掉英文朗讀；反之亦然。
- 當下=英文朗讀時：繪本工具不可呼叫、點繪本書架卡片→拒絕(409)；書架各自只顯示自己的書。

## 已驗證的纏繞（4 層）
1. 資料：共用 BookLibrary/books.csv；read-along 的 sel-* 書存進同一庫；/reader/api/books 無過濾→繪本書架顯示英文書。
2. 執行期：StoryStore 與 ReadAlongStore 都 bind 同一 handler、永不解綁、無「當下活動」概念→跨活動注入。兩個 store 可同時 live。
3. profile/工具：english_learner 同時有 read_along_* 與 story_book_create/go_to_page/close（混）；且缺 open/shelf。
4. 前端：繪本書架渲染漏出的英文卡片；read_along.html 的「回書架」連到繪本書架。

## 設計
### A. 資料命名空間（book_library 加 kind）
- BookMeta + CSV 加 `kind`（story|read_along）；list_books(kind)、get_book(id,kind)、delete_book(id,kind) 皆 kind-aware。
- save_book(story, kind=...)：story_book_create→story；read_along_illustrate→read_along。
- 舊 CSV 遷移：讀取時 kind 缺→由 id 前綴推導（sel-* → read_along，否則 story）；save 改 upsert（永遠寫新表頭、順手去重）。
- 共用圖片路由 /reader/api/books/{id}/pages/{n}/image 保留（read-along 封面/頁圖靠它）。

### B. 當下活動（新 activity_state.py）
- ActivityState 單例：current(None|story|read_along)、activate(activity)（設 current＋關掉另一個 store）、allows(activity)=current in {None, activity}。
- ENTRY_TOOLS（create/open/shelf/start）＝進入/切換該活動；WITHIN_TOOLS（go_to_page/close、cue/grade/next/finish）＝只在該活動 current 時可用。
- 在 dispatch_tool_call 強制：entry→activate；within→allows() 否則回 error。涵蓋兩個 backend＋autoread 路徑。

### C. 路由/注入 gating（story_routes）
- /reader/api/books list → kind=story；delete/download → kind=story 守門。
- 點選/點字注入：_select_book 需 allows(story) 否則 409；_read_along_tap/select 需 allows(read_along) 否則 409。

### D. profile/前端
- english_learner 補上 story_book_open + story_book_shelf（讓繪本活動完整）；instructions 說明活動切換模型。
- read_along.html「回書架」→ /reader/read-along。

## To-do
- [x] activity_state.py（新）+ 測試
- [x] book_library.py kind + 遷移/upsert + 測試
- [x] core_tools.dispatch_tool_call gating + 測試
- [x] story 工具/路由/read_along_illustrate 帶 kind
- [x] story_routes 注入/點選 gating + 測試
- [x] english_learner tools.txt + instructions
- [x] read_along.html 回書架連結
- [x] ruff + mypy + 全套 pytest 綠（371 passed）
- [ ] 版本 bump（0.4.17）+ uv lock + commit + PR + CI + HF sync

## Review
三層徹底分離 + 單一「當下活動」。

**A. 資料命名空間**：book_library 加 kind 欄（story|read_along），list/get/delete kind-aware；
save 改 upsert（順手去重 + 遷移舊表頭）；舊 CSV 由 id 前綴(sel-*)推導 kind。共用圖片路由保留。
→ 故事書架只列故事書、英文書架只列英文書，互不出現；故事工具不能開/刪英文書（404）。

**B. 當下活動**：新 activity_state.ActivityState（current + activate 關掉另一個 + allows）。
dispatch_tool_call 強制：entry 工具切換活動、within 工具非當下活動則擋下（兩 backend + autoread 都過這條）。
活動結束（story_book_close / read_along_finish）會 deactivate → current 歸 None，另一個書架又能點。

**C. 路由/注入 gating**：故事點選需 allows(story) 否則 409；英文點字/點選需 allows(read_along) 否則 409；
故事 reader 的 list/select/delete/download/meta/pages 全部 kind=story 守門（圖片路由除外，英文封面靠它）。

**D. profile/前端**：english_learner 補上 story_book_open+shelf（繪本活動完整）、instructions 說明切換模型；
read_along.html「回書架」改回英文書架。

**對抗式審查（15 agents）→ 已修**
- [HIGH] current 黏住不清 → 活動結束 deactivate（修好「做完一個後另一個書架點不動」死路）。
- [MED] autoread 收尾在被擋下時仍朗讀「故事說完了」→ 依結果守門。
- [MED] /pages JSON 沒 kind 守門 → 補上（圖片路由保留）。
- [LOW] story_book_create 背景生成完仍開故事分頁/朗讀 → 依當下活動守門。
- (false positive) activate 沒取消另一活動 autoread → 經驗證 gate 會優雅擋下，無需處理。

**驗證**：371 passed、ruff+mypy 全綠；切換循環 smoke 通過。實機需用 english_learner 測切換。
