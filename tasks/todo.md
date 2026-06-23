# Read-Along (Ello-style SEL English picture books) — 跟著汪汪讀

## Goal
研究 Ello 的核心 → 用 skills 把「背景圖＋前景朗讀文字」的繪本帶讀加進汪汪，
**用 Ello 的方式帶小朋友讀英文**。內容必須是**高品質、SEL（社會情緒學習）主題**的精選讀物，
不可用 LLM 隨機生成的劣質內容。**體驗要跟 Ello 完全一樣**，**測試要寫足**。

## Ello core (research distilled)
小朋友**自己讀**，汪汪**聽 + 階梯式介入**（不是機器人自動朗讀）：
1. Pre-read：小提示 + 暖身難字（預教）。
2. 顯示一頁（背景圖 + 前景單字）。
3. 邀請小朋友讀這一頁。
4. 小朋友讀，汪汪聽（realtime 模型原生支援）。
5. 讀對 → 稱讚 + success 視覺 + 翻頁。
6. 卡住/停頓 → 先輕推（你試試看）。
7. 讀錯（階梯式）：1st miss → **bounce**；2nd miss → **highlight**；點字/求助 → **拆音 sound-out** → **示範 model**。
8. **永遠不說「錯」** → 「我們再讀一次這個字」。
9. 翻頁；最後做**開放式理解 + SEL 情緒對話**，給星星獎勵。
三種書型：decodable（自己讀）、turn-taking（你一段我一段）、storytime（既有 story_book_create）。

## Architecture decision
- 重用：`BookLibrary`（圖片快取上磁碟）、`/reader/api/.../image`、FastAPI mount、reader.css 變數。
- 新建獨立 ReadAlong 子系統（不污染既有 story_book reader，且在 **Gemini backend** 也能跑——
  既有 auto-advance 是 OpenAI-only，但 read-along 不用 auto-narrate，靠 LLM 呼叫 next_page）。
- 內容：**手寫精選 SEL decodable 英文繪本**（文字品質完全可控）；插畫用既有 Gemini image pipeline 產生並快取，
  無圖時優雅降級為純文字。

## Build checklist
- [ ] `read_along_books.py` — 精選 SEL 書目 + tokenizer + catalog + 驗證 helper
- [ ] `read_along_store.py` — ReadAlongStore 單例（session/page/word_states/miss/stars/SSE/handler ref）
- [ ] tool `read_along_start` — 列書/開書（載入＋確保插畫＋開 reader）＋回傳第一頁字＋Ello 協定
- [ ] tool `read_along_cue` — bounce/highlight/sound_out/success/clear（word→index）
- [ ] tool `read_along_next_page` — 翻頁、回傳下一頁字 + is_last
- [ ] tool `read_along_finish` — 結束、星星獎勵 + wrapup
- [ ] handler `inject_user_text` — OpenAI + Gemini（tap-to-sound-out 用）
- [ ] routes：serve read-along reader、SSE、state、tap
- [ ] static：read_along.html / .js / .css（word spans + bounce/highlight/sound-out/success + 星星 + tap）
- [ ] SKILL.md `read-with-me`（Ello 協定）+ english_learner/tools.txt 接線
- [ ] tests：books / store / tools / routes（測試寫足）
- [ ] version 0.1.4 → 0.2.0、uv lock、ruff/mypy/pytest 全綠
- [ ] README + .env 文件、PR

## Review (完成)

全部完成，**234 passed**、ruff + mypy 全綠（0.1.4 → 0.2.0）。

### 交付
- 內容：`read_along_books.py` — 3 本手寫精選 SEL 英文 decodable 繪本（My Big Feelings / I Can Calm Down / We Are Kind），每頁含 tricky 目標字 + 開放式情緒提問 + 插圖 prompt；tokenizer/normalize。
- 狀態機：`read_along_store.py` — session/翻頁/word_states/**階梯式 miss（bounce→highlight→拆音）**/星星/SSE，全部 server 端可測。
- 插圖：`read_along_illustrate.py` — 重用 Gemini image pipeline，背景產生並快取到 BookLibrary，無 key 時純文字降級。
- 4 個工具：`read_along_start`（列書/開書 + 回傳 Ello 協定）、`read_along_cue`、`read_along_next_page`、`read_along_finish`。
- 雙後端 `inject_user_text`（tap 求助→汪汪拆音），routes（reader/SSE/state/tap），Ello 風 reader（`read_along.html/js/css`：word spans + 4 種狀態動畫 + 星星 + 點字）。
- SKILL.md `read-with-me` + 接進 english_learner/tools.txt。
- 測試：books / store / tools / routes + 兩後端 inject（~75 個新測試）。
- README + lessons 更新。

### 順手修掉的 latent bug
- `package-data` 沒列 `*.md` → **所有 SKILL.md 在部署的 wheel/HF Space 都沒被打包**（很可能是「英文小遊戲好像沒有」的真正原因之一）。已加 `profiles/**/*.md`。

### 使用者要做的（我無法跑實機）
- Desktop App 更新到 **0.2.0**、`REACHY_MINI_CUSTOM_PROFILE=english_learner`，跟汪汪說「我想讀英文繪本」實機驗證帶讀體驗。
