---
title: Reachy Mini 台灣中文對話（兒童版）
emoji: 🎤
colorFrom: red
colorTo: blue
sdk: static
pinned: false
short_description: 用台灣中文跟 Reachy Mini 聊天！專為 4-7 歲小朋友設計
suggested_storage: large
tags:
 - reachy_mini
 - reachy_mini_python_app
---

# Reachy Mini 台灣中文對話程式（兒童版）

<p align="center">
  <img src="docs/assets/taiwan_banner.png" alt="Reachy Mini x 台灣" width="600"/>
</p>

Reachy Mini 機器人的對話應用程式，結合 OpenAI 即時語音 API、視覺處理管線、編排動作庫，以及由 Google Gemini 驅動的互動說故事功能。

> **分支聲明**
> 本專案源自 HuggingFace 官方 [`reachy-mini-conversation-app`](https://huggingface.co/spaces/pollen-robotics/reachy-mini-conversation-app)，針對**繁體中文 + 兒童互動情境**進行大幅修改與功能擴充。未來不保證與官方主分支的功能或架構保持同步。

![Reachy Mini Dance](docs/assets/reachy_mini_dance.gif)

## 適合的用戶

- 4–7 歲兒童的**家長、老師、展場人員**，想讓機器人成為互動夥伴
- 想用**繁體中文**與 Reachy Mini 互動的人
- 想讓機器人**說故事給小朋友聽**的人

## 功能列表

| 功能 | 說明 |
|------|------|
| 即時語音對話 | 透過 OpenAI 即時 API 進行低延遲中文語音對話 |
| 互動說故事 | Google Gemini 產生繪本故事，搭配水彩風格插圖，在平板即時顯示 |
| 舞蹈與情緒動作 | 內建舞蹈庫與情緒動作播放 |
| 視覺 / 相機 / 臉部追蹤 | 支援 gpt-realtime、SmolVLM2、YOLO、MediaPipe 等多種視覺方案 |
| 網路搜尋 | 透過 Tavily 即時搜尋網路回答問題 |
| 長期記憶 | 以 Markdown（Zettelkasten 風格）跨工作階段記住偏好與事實，可由 Gemini 自動整理去重 |
| 英語學習遊戲 | `english_learner` 角色以 Agent Skills（SKILL.md）提供 6 種互動英語遊戲，專為 4–6 歲設計 |
| 多角色 Profile | 16 個內建角色，也可自訂專屬角色與工具 |

## 快速上手

### 1. 取得應用程式

透過 [Reachy Mini Desktop App](https://github.com/pollen-robotics/reachy-mini-desktop-app) 搜尋 `reachy_mini_conversation_app_zh-TW`，即可一鍵安裝本應用程式。

**或者：用腳本在任何 Mac 上安裝（CLI）。** 想把機器人接到不同 Mac 直接跑時，這是最簡單的可重現方式——`uv.lock` 確保每台機器裝出完全一致的環境（不需要 Docker；Docker Desktop on Mac 跑在 Linux VM 裡，無法存取 Mac 的相機/麥克風/喇叭與 USB）：

```bash
git clone https://github.com/brucechou1983/reachy_mini_conversation_app_zh-TW.git
cd reachy_mini_conversation_app_zh-TW
./scripts/setup-mac.sh        # 安裝 uv (必要時) + 依 uv.lock 建環境 + 建立 .env
# 編輯 .env 填入 OPENAI_API_KEY，並確認 Reachy Mini daemon 已啟動
./scripts/run.sh              # 啟動 (加 --gradio 開網頁介面)
```

`setup-mac.sh` 是冪等的，重跑安全；換新 Mac 只要重複這幾行即可。

### 2. 基本設定

| 變數 | 必填 | 說明 |
|------|:----:|------|
| `OPENAI_API_KEY` | **是** | OpenAI 即時語音 API 金鑰 |
| `GEMINI_API_KEY` | 選填 | 互動說故事與長期記憶自動整理所需（[取得](https://aistudio.google.com)） |
| `TAVILY_API_KEY` | 選填 | 網路搜尋功能所需（[取得](https://tavily.com)） |


### 3. 故事閱讀器

啟動後請汪汪開啟故事書，或是手動打開 `http://127.0.0.1:7860/reader`，即可看到你的繪本。

---

# 技術細節

以下為完整的架構說明、安裝選項、環境變數與開發流程。

## 架構

本應用程式採用分層架構，串接使用者、AI 服務與機器人硬體：

<p align="center">
  <img src="docs/assets/conversation_app_arch.svg" alt="架構圖" width="600"/>
</p>

## 總覽
- 透過 OpenAI 即時 API 與 `fastrtc` 進行低延遲串流，實現即時語音對話迴圈。
- 視覺處理預設使用 gpt-realtime（使用相機工具時），也可透過 `--local-vision` 旗標改用 SmolVLM2 模型在本機（CPU/GPU/MPS）執行視覺處理。
- 分層動作系統將主要動作（舞蹈、情緒、移動姿勢、呼吸）排入佇列，同時融合語音反應搖擺與臉部追蹤。
- 非同步工具調度整合機器人動作、相機擷取、網路搜尋、長期記憶與臉部追蹤等功能，並透過 Gradio 網頁介面提供即時逐字稿。
- 互動說故事功能透過 Google Gemini 產生繪本故事，並在網頁閱讀器上以 SSE 即時更新顯示。

## 安裝（完整版）

### 使用 uv
透過 [uv](https://docs.astral.sh/uv/) 可快速設定專案：

```bash
uv venv --python 3.12.1  # 建立 Python 3.12.1 虛擬環境
source .venv/bin/activate
uv sync
```

> [!NOTE]
> 若要重現本 repo 的 `uv.lock` 中記錄的完整相依套件版本，請加上 `--locked`（或 `--frozen`）執行 `uv sync`，確保直接從 lockfile 安裝，不會重新解析或更新版本。

安裝選用相依套件：
```
uv sync --extra reachy_mini_wireless # 無線版 Reachy Mini（GStreamer 支援）
uv sync --extra local_vision         # 本機 PyTorch/Transformers 視覺
uv sync --extra yolo_vision          # YOLO 視覺
uv sync --extra mediapipe_vision     # MediaPipe 視覺
uv sync --extra all_vision           # 所有視覺功能
```

可組合多個 extras 或加入開發相依：
```
uv sync --extra all_vision --group dev
```

### 使用 pip

```bash
python -m venv .venv # 建立虛擬環境
source .venv/bin/activate
pip install -e .
```

依需求安裝選用 extras：

```bash
# 無線版 Reachy Mini 支援
pip install -e .[reachy_mini_wireless]

# 視覺功能（若要使用臉部追蹤，請至少安裝一種）
pip install -e .[local_vision]
pip install -e .[yolo_vision]
pip install -e .[mediapipe_vision]
pip install -e .[all_vision]        # 安裝所有視覺 extras

# 開發工具
pip install -e .[dev]
```

部分套件（如 PyTorch）檔案較大，需要相容的 CUDA 或 CPU 版本——請確認你的平台與安裝的二進位檔相符。

## 選用相依套件群組

| Extra | 用途 | 備註 |
|-------|------|------|
| `reachy_mini_wireless` | 無線版 Reachy Mini（GStreamer 支援）。 | 無線版 Reachy Mini 必裝，包含 GStreamer 相依。
| `local_vision` | 透過 PyTorch/Transformers 執行本機 VLM（SmolVLM2）。 | 建議使用 GPU；請確認 PyTorch 版本與平台相容。
| `yolo_vision` | 透過 `ultralytics` 與 `supervision` 進行 YOLOv8 追蹤。 | CPU 友善；支援 `--head-tracker yolo` 選項。
| `mediapipe_vision` | 使用 MediaPipe 進行輕量級特徵點追蹤。 | 可在 CPU 上執行；啟用 `--head-tracker mediapipe`。
| `all_vision` | 安裝所有視覺 extras 的便捷別名。 | 想嘗試所有視覺方案時使用。
| `dev` | 開發工具（`pytest`、`ruff`、`mypy`）。 | 可疊加在基本安裝或 `all_vision` 環境之上。

## 設定（完整環境變數）

1. 將 `.env.example` 複製為 `.env`。
2. 填入必要的值，特別是 OpenAI API 金鑰。

| 變數 | 說明 |
|------|------|
| `OPENAI_API_KEY` | 必填。用於存取 OpenAI 即時語音端點。
| `MODEL_NAME` | 覆寫即時模型（預設為 `gpt-realtime`）。同時用於對話與視覺（除非使用 `--local-vision`）。
| `GEMINI_API_KEY` | 選填。互動說故事工具（`story_book_create` 等）與長期記憶自動整理（記憶過多時合併去重）所需。可至 [Google AI Studio](https://aistudio.google.com) 取得。
| `TAVILY_API_KEY` | 選填。啟用 `web_search` 工具進行即時網路搜尋。可至 [tavily.com](https://tavily.com) 取得。
| `HF_HOME` | 本機 Hugging Face 下載的快取目錄（僅搭配 `--local-vision` 使用，預設為 `./cache`）。
| `HF_TOKEN` | Hugging Face 模型的選用 Token（僅搭配 `--local-vision` 使用，也可用 `huggingface-cli login`）。
| `LOCAL_VISION_MODEL` | 本機視覺處理的 Hugging Face 模型路徑（僅搭配 `--local-vision` 使用，預設為 `HuggingFaceTB/SmolVLM2-2.2B-Instruct`）。
| `REACHY_MINI_CUSTOM_PROFILE` | 啟動時載入的 profile 名稱（`profiles/` 下的資料夾）。未設定時預設為 `default`。
| `STORY_BOOKS_DIR` | 故事書的持久化儲存目錄。預設為 `~/.reachy_mini/books/`。

## 命令列選項

| 選項 | 預設值 | 說明 |
|------|--------|------|
| `--head-tracker {yolo,mediapipe}` | `None` | 在有相機時選擇臉部追蹤後端。YOLO 為本機實作，MediaPipe 來自 `reachy_mini_toolbox` 套件。需安裝對應的選用 extra。 |
| `--no-camera` | `False` | 不使用相機擷取與臉部追蹤。 |
| `--local-vision` | `False` | 使用本機視覺模型（SmolVLM2）定期處理影像，取代 gpt-realtime 視覺。需安裝 `local_vision` extra。 |
| `--gradio` | `False` | 啟動 Gradio 網頁介面。不加此旗標則以 console 模式執行。模擬模式下必須使用。 |
| `--debug` | `False` | 啟用詳細日誌以利除錯。 |
| `--robot-name <name>` | `None` | Zenoh 主題的機器人名稱/前綴（需與 daemon 的 `--robot-name` 一致）。僅在多台機器人開發時需要。 |

## 疑難排解

- 逾時錯誤：
如果出現以下錯誤：
  ```bash
  TimeoutError: Timeout while waiting for connection with the server.
  ```
很可能是 Reachy Mini 的 daemon 未在執行。請安裝 [Reachy Mini SDK](https://github.com/pollen-robotics/reachy_mini/) 並啟動 daemon。

## LLM 工具一覽

| 工具 | 功能 | 相依條件 |
|------|------|----------|
| `move_head` | 排入頭部姿勢變更（左/右/上/下/正前方）。 | 僅需基本安裝。 |
| `camera` | 擷取最新相機影像並傳送給 gpt-realtime 進行視覺分析。 | 需要相機 worker；預設使用 gpt-realtime 視覺。 |
| `take_photo` | 從相機擷取高解析度照片。 | 需要相機 worker。 |
| `head_tracking` | 啟用或停用臉部追蹤偏移（非臉部辨識，僅偵測與追蹤臉部位置）。 | 需要相機 worker 及設定好的 head tracker。 |
| `dance` | 從 `reachy_mini_dances_library` 排入舞蹈動作。 | 僅需基本安裝。 |
| `stop_dance` | 清除已排入的舞蹈。 | 僅需基本安裝。 |
| `play_emotion` | 透過 Hugging Face 素材播放錄製的情緒動作。 | 需要 `HF_TOKEN` 以存取情緒動作資料集。 |
| `stop_emotion` | 清除已排入的情緒動作。 | 僅需基本安裝。 |
| `web_search` | 透過 Tavily 搜尋網路即時資訊。 | 需要 `TAVILY_API_KEY`。 |
| `save_memory` / `forget_memory` | 儲存或移除跨工作階段的記憶（如使用者偏好、事實）。 | 僅需基本安裝。 |
| `save_profile_memory` / `forget_profile_memory` | 儲存或移除限定於當前 profile 的記憶。 | 僅需基本安裝。 |
| `story_book_create` | 透過 Google Gemini 非同步產生繪本故事（文字 + 插圖）。 | 需要 `GEMINI_API_KEY`。 |
| `story_book_open` | 從繪本書庫開啟已儲存的故事，或列出可用書籍。 | 需要 `GEMINI_API_KEY`。 |
| `story_book_go_to_page` | 跳到當前故事的指定頁面，並回傳頁面文字。 | 需要正在進行的故事工作階段。 |
| `story_book_close` | 關閉故事閱讀器，回到一般對話模式。 | 需要正在進行的故事工作階段。 |
| `do_nothing` | 明確保持閒置。 | 僅需基本安裝。 |

## 互動說故事（詳細版）

互動說故事功能讓機器人產生繪本故事並朗讀給小朋友聽，同時在平板或螢幕上即時顯示繪本頁面。

### 運作方式

1. **建立故事** -- 小朋友告訴機器人想聽什麼故事。機器人呼叫 `story_book_create` 並帶入主題，觸發 Google Gemini 非同步產生故事（`gemini-2.5-flash` 產生文字，`gemini-2.5-flash-image` 產生水彩風格插圖）。產生過程在背景執行，機器人可繼續聊天。
2. **閱讀器顯示** -- 位於 `/reader` 的網頁閱讀器透過 Server-Sent Events（SSE）接收即時更新。產生中顯示載入畫面，完成後切換至閱讀檢視，顯示全頁插圖與文字。
3. **朗讀** -- 故事準備好後，機器人透過 OpenAI 即時 TTS 語音逐頁朗讀。閱讀器同步更新，顯示對應的插圖與文字。
4. **繪本書庫** -- 完成的故事會儲存至持久化書庫（預設為 `~/.reachy_mini/books/`），之後可透過 `story_book_open` 重新開啟。

### 故事閱讀器 API 端點

| 端點 | 說明 |
|------|------|
| `GET /reader` | 網頁故事閱讀器介面（可在平板/第二螢幕上開啟）。 |
| `GET /reader/events` | SSE 串流，提供即時故事狀態更新。 |
| `GET /reader/story` | 當前故事狀態的 JSON 快照（供頁面重新整理後恢復狀態）。 |
| `GET /reader/api/books` | 列出書庫中所有已儲存的書籍。 |
| `GET /reader/api/books/{book_id}/download` | 以 ZIP 壓縮檔下載書籍。 |
| `DELETE /reader/api/books/{book_id}` | 從書庫刪除書籍。 |

### 說故事人 Profile

內建 `storyteller` profile，具備溫暖、富想像力的角色設定，專為 4-7 歲兒童設計（指令為繁體中文）。設定 `REACHY_MINI_CUSTOM_PROFILE=storyteller` 即可使用，或在網頁介面中動態切換 profile。

## 長期記憶（詳細版）

機器人會把重要資訊存成人類可讀、git 友善的 Markdown 檔（Zettelkasten 風格），跨工作階段沿用。

### 兩層記憶
- **全域記憶**：所有 profile 共用的使用者層級事實與事件，存於 `~/.reachy_mini_memories/`（最多 20 筆）。
- **角色記憶**：每個 profile 獨立、互不干擾的活動記錄，存於 `~/.reachy_mini_memories/profiles/<profile>/`（最多 10 筆）。

### 儲存結構
每筆記憶是一個帶 YAML frontmatter 的 `.md` 檔，依類型分到 `facts/`（事實／偏好）或 `events/`（事件／活動）子資料夾，檔名取自內容（支援中文）以利瀏覽。達到容量上限時自動淘汰最舊的一筆。

### 自動整理（選填）
若設定了 `GEMINI_API_KEY`，每次工作階段開始時，當事實數量超過門檻（預設 15 筆）會呼叫 Gemini（`gemini-2.5-flash`）合併重複／過時的事實並去重；事件不受影響。整理失敗為非致命，不影響正常啟動。

### 相關工具
LLM 透過 `save_memory` / `forget_memory`（全域）與 `save_profile_memory` / `forget_profile_memory`（角色）讀寫記憶；變更會即時注入系統提示。

> **從舊版升級**：首次啟動會自動把舊的 `~/.reachy_mini_memories.json` 遷移成新的 Markdown 結構，原檔重新命名為 `.json.migrated`。

## 英語學習與 Agent Skills

`english_learner` 角色是專為 4–6 歲台灣小朋友設計的英語學習夥伴，透過遊戲化互動教英文。它採用 **Agent Skills 架構**（借鑑 Anthropic 的 SKILL.md 漸進式揭露）：系統提示只放各遊戲的名稱與簡介，完整規則在需要時才載入，藉此降低 token 用量。

### 運作方式
1. 啟動時 `skills.py` 掃描 `profiles/english_learner/skills/` 下每個含 `SKILL.md` 的資料夾，把名稱與描述彙整成「可用遊戲技能」目錄，附加到系統提示。
2. 小朋友選遊戲後，LLM 呼叫 profile 專屬的 `activate_skill` 工具載入該 `SKILL.md` 的完整規則，並以之引導接下來的對話。

### 內建 6 種遊戲
| 遊戲 | 內容 |
|------|------|
| `color-detective` | 顏色偵探：用相機在房間找顏色，教英文顏色單字。 |
| `simon-says` | 機器人老大說（Simon Says）：用肢體動作教英文動作詞與身體部位。 |
| `teach-robot` | 教我吧小老師：角色互換，由小朋友當老師教機器人英文。 |
| `emotion-mirror` | 情緒鏡子：用表情互相模仿，教英文情緒單字。 |
| `photo-hunt` | 拍照大冒險：用形容詞任務找東西拍照學單字。 |
| `story-builder` | 魔法故事書：用英文選角色與場景，一起創作故事。 |

### 新增遊戲
只需在 `profiles/english_learner/skills/<game-name>/` 新增一個含 YAML frontmatter（`name`、`description`）的 `SKILL.md`，即會自動被發現並出現在目錄中，無需改任何程式碼。詳見 [`docs/english_learner_guide.md`](docs/english_learner_guide.md)。

## 自訂 Profile
建立自訂 profile，搭配專屬指令與工具組合！

設定 `REACHY_MINI_CUSTOM_PROFILE=<name>` 以載入 `src/reachy_mini_conversation_app/profiles/<name>/`（參見 `.env.example`）。未設定時使用 `default` profile。

每個 profile 需要兩個檔案：`instructions.txt`（指令文字）和 `tools.txt`（啟用的工具清單），另外可選擇性地包含自訂工具實作與 `voice.txt` 檔案以覆寫 TTS 語音。

### 內建 Profile

本應用程式內建 16 個角色 profile：

| Profile | 說明 |
|---------|------|
| `default` | 通用對話角色，具備完整工具存取權限。 |
| `storyteller` | 溫暖、富想像力的說故事人，適合 4-7 歲兒童（繁體中文）。 |
| `english_learner` | 英語學習遊戲老師，以 6 種 Agent Skills 遊戲教 4–6 歲小朋友英文（繁體中文引導）。 |
| `cosmic_kitchen` | 太空主題料理角色。 |
| `mars_rover` | 火星探索導覽員。 |
| `sorry_bro` | 愛道歉的角色。 |
| `short_bored_teenager` | 無聊的青少年。 |
| `short_captain_circuit` | 機器人船長。 |
| `short_chess_coach` | 西洋棋教練。 |
| `short_hype_bot` | 熱血激勵機器人。 |
| `short_mad_scientist_assistant` | 瘋狂科學家的助手。 |
| `short_nature_documentarian` | 自然紀錄片旁白員。 |
| `short_noir_detective` | 黑色電影風格偵探。 |
| `short_time_traveler` | 時空旅人。 |
| `short_victorian_butler` | 維多利亞時代管家。 |
| `example` | 參考用範本，含自訂工具（`sweep_look`）。 |

### 自訂指令
在 `instructions.txt` 中撰寫純文字指令。若要重複使用共享的指令片段，可加入如下佔位符：
```
[passion_for_lobster_jokes]
[identities/witty_identity]
```
每個佔位符會對應載入 `src/reachy_mini_conversation_app/prompts/` 下的相應檔案（支援巢狀路徑）。參見 `src/reachy_mini_conversation_app/profiles/example/` 的範例配置。

### 啟用工具
在 `tools.txt` 中列出啟用的工具，每行一個；以 `#` 前綴可註解掉。例如：

```
play_emotion
# move_head

# 在 profile 資料夾中定義的自訂工具
sweep_look
```
工具優先從 profile 資料夾中的 Python 檔案（自訂工具）載入，其次從共享工具庫 `src/reachy_mini_conversation_app/tools/`（如 `dance`、`head_tracking`）載入。

### 自訂工具
除了共享工具庫中的內建工具外，你可以在 profile 資料夾中新增 Python 檔案來實作 profile 專屬的自訂工具。
自訂工具需繼承 `reachy_mini_conversation_app.tools.core_tools.Tool`（參見 `profiles/example/sweep_look.py`）。

### 從介面編輯角色
使用 `--gradio` 執行時，展開「Personality」區塊：
- 從可用 profile 中選擇（`src/reachy_mini_conversation_app/profiles/` 下的資料夾）或使用內建預設值。
- 點擊「Apply」即時更新當前工作階段的指令。
- 輸入名稱與指令文字即可建立新角色；檔案會儲存在 `profiles/<name>/` 下，並從 `default` profile 複製 `tools.txt`。

注意：「Personality」面板更新的是對話指令。工具組合在啟動時從 `tools.txt` 載入，不支援熱重載。


## 開發流程
- 安裝開發用 extras：`uv sync --group dev` 或 `pip install -e .[dev]`。
- 格式化與 linting：`ruff check .`。
- 執行測試：`pytest`。
- 型別檢查：`mypy`。
- 調整機器人動作時，請保持控制迴圈的回應性 => 使用 `tools.py` 中的輔助函式卸載阻塞工作。

## 授權條款
Apache 2.0
