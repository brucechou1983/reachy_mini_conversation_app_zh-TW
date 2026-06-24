# Task: 提升故事繪本品質（角色一致性 / 工藤紀子畫風 / 文案）

## 問題（現況 story_book_create.py）
- 每頁插畫各自獨立生成（`_generate_illustration(theme, page_text,…)`），**沒有共用角色參考**→ 同一角色每頁長相都不同。
- 畫風 prompt 只有泛泛的「soft watercolor」→ 沒有特色。
- 文字 prompt 平庸（「簡短、溫暖、有趣」）→ 文案平庸。

## 設計（三步生成，集中在 story_book_create.py）
1. **故事聖經（story bible）**：一次文字生成回傳結構化 JSON：
   - `title`、`characters:[{name, description(固定外觀)}]`、`pages:[{text(朗讀), scene(該頁畫面描述，用角色名)}]`。
   - 文案 prompt 注入童書寫作手法：清楚的 want→阻礙→轉折→溫暖結局、重複句/回應句(refrain)、狀聲詞、感官具體細節(show-don't-tell)、朗讀節奏、翻頁懸念、不說教的結尾。
2. **角色參考圖（reference sheet）**：用 characters 描述 + 工藤紀子畫風，生成**一張**多角色正面參考圖（中性背景）。
3. **逐頁插畫**：把參考圖當 image input 餵進每頁生成（`types.Part.from_bytes`），prompt 要求「沿用參考圖中完全相同的角色/顏色/畫風」+ 該頁 scene + 工藤畫風 + 不要文字。

## 工藤紀子畫風描述（常數，靠視覺特徵而非僅靠人名）
粗而均勻的黑色描線、平塗暖色（gouache 質感）、圓潤厚實可愛角色、簡單點線五官、明亮微復古配色、溫馨有幽默感的構圖。

## 可測試的純函式（抽出以便單元測試，不打 API）
- `_STYLE`（畫風常數）
- `build_bible_prompt(theme, num_pages)`、`parse_bible(text, num_pages)`（健壯 JSON、補 scene 後備）
- `build_character_sheet_prompt(characters)`、`build_page_prompt(scene, narration)`

## 資料模型
- StoryPage 仍只需 text + image → **不動** StoryStore / BookLibrary / reader（參考圖僅生成期間記憶體用，最小衝擊）。

## To-do
- [x] 重構 story_book_create.py：三步生成 + 純函式抽出
- [x] 工藤畫風常數 + 文案手法 prompt
- [x] 參考圖生成 + 逐頁 image-input
- [x] 新增 tests/test_story_book_create.py（純函式 + mock orchestration）
- [x] ruff + mypy + 全套 pytest 綠（332 passed）
- [ ] 版本 bump（0.4.15）+ uv lock + commit + PR + CI + HF sync

## Review
三點全數落實，集中在 `story_book_create.py`（最小衝擊，未動 StoryStore/reader/persist）：

1. **角色一致性**：三步生成 —
   - `_generate_story_bible` 先產出結構化故事聖經（固定角色 + 每頁 text/scene）。
   - `_generate_character_sheet` 用角色描述產**一張**多角色正面參考圖（中性背景）。
   - 每頁 `_generate_illustration` 把參考圖當 `types.Part.from_bytes` image input 餵進去，
     prompt 要求「與參考圖完全一致（臉/色/服裝/比例）」→ 角色不再每頁漂移。
   - orchestration 測試證明：參考圖只產一次、每頁都收到同一張。
2. **工藤紀子畫風**：`_STYLE` 常數（粗黑描線、平塗暖色 gouache、圓潤厚實角色、點線五官、
   微復古配色、溫馨幽默構圖），同時套在參考圖與每頁；靠視覺特徵描述而非僅靠人名。
3. **文案品質**：`build_bible_prompt` 注入 7 項童書手法（故事弧／refrain／狀聲詞／
   show-don't-tell／朗讀節奏／翻頁懸念／溫暖結尾），並把朗讀 text（中文）與插畫 scene（英文）分離。

**順手**：read_along 改用共用 `generate_book_image`（保留自己的 soft watercolor 風），
移除對舊 `_generate_illustration` 簽名的依賴；書名改用聖經 title（比 raw theme 漂亮）。

**驗證**：332 passed、ruff + mypy 全綠。實機圖像品質需使用者在 Desktop App（有 key）做一本書目視驗證。
