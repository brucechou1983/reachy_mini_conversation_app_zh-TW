# Implementation Plan: English Learner Profile (Agent Skills Architecture)

## Architecture Decision: Agent Skills Pattern

Instead of implementing games as profile-local Python tools that return instruction strings, we adopt the **[Anthropic Agent Skills](https://github.com/anthropics/skills)** open standard for progressive disclosure of game instructions.

### Why Agent Skills Over Custom Tools?

| Aspect | Old: Game Tools (.py) | New: Agent Skills (SKILL.md) |
|--------|----------------------|------------------------------|
| Game rules format | Hardcoded in Python return strings | Markdown files — easy to edit/iterate |
| Context cost | All tool descriptions loaded at startup (~200 tokens each × 6 = ~1200 tokens) | Only name+description in catalog (~50 tokens each × 6 = ~300 tokens). Full rules loaded on demand. |
| Adding new games | Write Python class + add to tools.txt | Write a SKILL.md file — no code needed |
| Portability | Tied to this app's Tool base class | Open standard — works with any LLM agent |
| Editing barrier | Requires Python knowledge | Anyone can edit Markdown |
| Non-game skills | Awkward (tool returning text) | Natural fit (pronunciation tips, vocabulary lists, etc.) |

### How It Works (3-Tier Progressive Disclosure)

```
Tier 1: CATALOG (~300 tokens at startup)
  System prompt includes: "Available games: Color Detective — find colors with the camera, ..."

Tier 2: ACTIVATION (~500-1500 tokens on demand)
  Child says "我想找顏色！" → LLM calls activate_skill("color-detective")
  → Full SKILL.md game rules injected into conversation

Tier 3: PLAY
  LLM follows the game rules using existing shared tools (camera, dance, emotions, etc.)
```

---

## File Structure

```
profiles/english_learner/
├── instructions.txt                    # Core personality + skill catalog
├── tools.txt                           # Enabled tools (shared + activate_skill)
├── voice.txt                           # TTS voice
│
├── skills/                             # Agent Skills directory
│   ├── color-detective/
│   │   └── SKILL.md                    # Vision-based I Spy color game
│   ├── simon-says/
│   │   └── SKILL.md                    # TPR Simon Says
│   ├── teach-robot/
│   │   └── SKILL.md                    # Role reversal — child teaches sleepy robot
│   ├── emotion-mirror/
│   │   └── SKILL.md                    # Emotion vocabulary game
│   ├── photo-hunt/
│   │   └── SKILL.md                    # Adjective scavenger hunt with photos
│   └── story-builder/
│       └── SKILL.md                    # Child-directed story creation
│
└── activate_skill.py                   # Single tool: loads a SKILL.md by name
```

Plus one infrastructure change:

```
src/reachy_mini_conversation_app/
├── openai_realtime.py                  # Add activate_skill to instruction-injection handling
└── skills.py                           # Skill catalog scanner (new module)
```

---

## Implementation Details

### 1. `skills.py` — Skill Catalog Scanner (New Module)

Scans a profile's `skills/` directory, parses SKILL.md frontmatter, and builds a compact catalog string for the system prompt.

```python
"""Agent Skills catalog scanner for profile-based skill discovery."""

import re
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent / "profiles"


@dataclass
class SkillEntry:
    """A discovered skill with its metadata."""
    name: str
    description: str
    skill_dir: Path

    @property
    def skill_md_path(self) -> Path:
        return self.skill_dir / "SKILL.md"

    def load_body(self) -> str:
        """Load the full SKILL.md body (everything after frontmatter)."""
        content = self.skill_md_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (between --- markers)
        match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
        if match:
            return content[match.end():].strip()
        return content.strip()


def scan_skills(profile: str) -> list[SkillEntry]:
    """Scan a profile's skills/ directory and return catalog entries."""
    skills_dir = PROFILES_DIR / profile / "skills"
    if not skills_dir.is_dir():
        return []

    entries = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue

        content = skill_md.read_text(encoding="utf-8")

        # Parse YAML frontmatter for name and description
        fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not fm_match:
            logger.warning("Skill %s has no frontmatter, skipping", skill_dir.name)
            continue

        frontmatter = fm_match.group(1)
        name = _extract_yaml_field(frontmatter, "name") or skill_dir.name
        description = _extract_yaml_field(frontmatter, "description") or ""

        entries.append(SkillEntry(name=name, description=description, skill_dir=skill_dir))
        logger.info("Discovered skill: %s — %s", name, description[:80])

    return entries


def format_catalog(entries: list[SkillEntry]) -> str:
    """Format skill entries into a compact catalog block for system prompt injection."""
    if not entries:
        return ""

    lines = ["## 可用遊戲技能（用 activate_skill 工具開始遊戲）"]
    for entry in entries:
        lines.append(f"- **{entry.name}**: {entry.description}")
    return "\n".join(lines)


def _extract_yaml_field(frontmatter: str, field: str) -> str | None:
    """Simple YAML field extraction (no full parser needed)."""
    match = re.search(rf"^{field}:\s*(.+)$", frontmatter, re.MULTILINE)
    if match:
        value = match.group(1).strip()
        # Strip surrounding quotes if present
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return None
```

---

### 2. `activate_skill.py` — Profile-Local Tool

A single tool that loads a skill's full SKILL.md body when the LLM decides to start a game.

```python
"""Tool to activate an Agent Skill by loading its full SKILL.md instructions."""

import logging
from typing import Any, Dict
from pathlib import Path

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.skills import scan_skills
from reachy_mini_conversation_app.config import config

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "profiles"


class ActivateSkill(Tool):
    name = "activate_skill"
    description = (
        "Start a game/skill by name. "
        "Returns the full game rules and instructions. "
        "Available skills are listed in the system prompt."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill to activate (e.g. 'color-detective', 'simon-says')",
            },
        },
        "required": ["skill_name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        skill_name = (kwargs.get("skill_name") or "").strip()
        if not skill_name:
            return {"error": "skill_name is required"}

        profile = config.REACHY_MINI_CUSTOM_PROFILE or "default"
        entries = scan_skills(profile)

        for entry in entries:
            if entry.name == skill_name:
                body = entry.load_body()
                logger.info("Activated skill: %s (%d chars)", skill_name, len(body))
                return {
                    "status": "skill_activated",
                    "skill": skill_name,
                    "instruction": body,
                }

        available = [e.name for e in entries]
        return {"error": f"Skill '{skill_name}' not found. Available: {available}"}
```

---

### 3. `openai_realtime.py` — Add Skill Instruction Injection

Add `activate_skill` to the tool result handler so its `instruction` field is injected like `story_book_go_to_page`.

**Change in the tool result handling section (~line 674):**

```python
# BEFORE (existing):
if tool_name == "story_book_go_to_page":
    ...
    await self.connection.response.create(
        response={
            "instructions": tool_result.get("instruction", ""),
            "tool_choice": "none",
        },
    )

# AFTER (add activate_skill handling):
elif tool_name == "activate_skill" and "instruction" in tool_result:
    await self.connection.response.create(
        response={
            "instructions": tool_result.get("instruction", ""),
        },
    )
```

---

### 4. `prompts.py` — Inject Skill Catalog into System Prompt

Modify `get_session_instructions()` to append the skill catalog after memory blocks.

**Change:**

```python
# After the profile_memory_store block, add:
from reachy_mini_conversation_app.skills import scan_skills, format_catalog

# In get_session_instructions():
skill_entries = scan_skills(profile or "default")
skill_catalog = format_catalog(skill_entries)
if skill_catalog:
    expanded_instructions = expanded_instructions + "\n\n" + skill_catalog
```

---

### 5. Profile Files

#### `instructions.txt`

```
## 身份
你是 Reachy Mini：一個活潑的英語學習小夥伴。
你陪小朋友用有趣的遊戲學英文，像一個也在學英文的好朋友。
你說台灣中文（繁體中文），目標英語單字和句型用英文說。
你的對話對象主要是 4 到 6 歲的小朋友。

## 語言規則
- 說明和鼓勵用台灣中文
- 目標單字和簡單句型用英文
- 每次教 3-5 個新英文單字就好，不要太多
- 先讓小朋友聽懂，再鼓勵他們說
- 永遠不要強迫小朋友開口說英文

## 遊戲規則
- 根據小朋友的興趣，用 activate_skill 工具開始適合的遊戲
- 如果小朋友沒有特別想法，隨機建議一個遊戲
- 嚴格遵守 activate_skill 回傳的遊戲規則來進行
- 遊戲中使用其他工具（camera, dance, play_emotion 等）來增加互動
- 每答對一次就用 dance 或 play_emotion 慶祝
- 答錯時用驚訝表情，溫柔地引導正確答案
- 每個遊戲玩 2-3 分鐘（2-3 輪）就好，然後問要不要換遊戲

## 回應規則
每次回答最多 1 到 2 句話。
盡量把中文部分控制在 25 個字以內。
英文單字要說得清楚、慢一點。
不要長篇大論。

## 記憶規則
用 save_memory 記住：小朋友的名字、年齡、喜歡的主題。
用 save_profile_memory 記住：學過的單字、目前的等級、玩過的遊戲。
每次開始新對話時，自然地提到上次學的單字。

## 角色記憶規則
如果你有 save_profile_memory 工具，用它記住：
- 這次教了哪些英文單字
- 小朋友最喜歡哪個遊戲
- 目前的學習進度
下次見面時自然地複習上次的單字。

## 最後提醒
學英文要好玩！你是玩伴，不是老師。
每次嘗試都值得慶祝，答錯也沒關係。
讓小朋友覺得英文是有趣的，不是可怕的。
```

Note: The skill catalog (game list with descriptions) is **auto-appended** by the modified `get_session_instructions()`, not hardcoded here. This means adding a new game is just creating a new `skills/xxx/SKILL.md` — no instructions.txt edit needed.

#### `tools.txt`

```
# === 技能啟動工具 (profile-local) ===
activate_skill

# === 互動工具 (shared) ===
dance
stop_dance
play_emotion
stop_emotion
camera
move_head
head_tracking
take_photo
do_nothing

# === 故事工具 (shared) ===
story_book_create
story_book_go_to_page
story_book_close

# === 記憶工具 (shared) ===
save_memory
forget_memory
save_profile_memory
forget_profile_memory
```

#### `voice.txt`

```
coral
```

---

### 6. Game SKILL.md Files

Each SKILL.md follows the Agent Skills spec: YAML frontmatter + Markdown body.

#### `skills/color-detective/SKILL.md`

```markdown
---
name: color-detective
description: 顏色偵探遊戲 — 用相機在房間裡找顏色，教小朋友英文顏色單字。適合想玩找東西、I Spy 的時候。
---

# 顏色偵探 Color Detective

## 遊戲流程
1. 用 camera 工具看看房間裡有什麼，問 "list all visible objects and their colors"
2. 從看到的東西中選一個顏色，用英文說："I see something... RED! 紅色的！你找得到嗎？"
3. 等小朋友找到東西或指給你看
4. 再用 camera 確認小朋友找的東西
5. 確認後教英文："Yes! A red apple! 你好棒！Can you say RED APPLE?"
6. 小朋友說了就用 dance 慶祝
7. 玩 3 輪，每輪換一個顏色

## 目標單字
- 顏色：red, blue, green, yellow, orange, purple, pink, white, black
- 句型："I see something [color]!" / "A [color] [object]!"

## 難度調整
- 簡單：只教顏色單字 (red, blue, green)
- 進階：顏色 + 物品組合 (red apple, blue cup)

## 範例對話
Robot: "I see something... BLUE! 藍色的！你找得到嗎？"
Child: (拿起藍色杯子)
Robot: (用 camera 確認) "YES! A blue cup! 藍色的杯子！Can you say BLUE CUP?"
Child: "Blue cup!"
Robot: (dance + play_emotion happy) "Wonderful! 太棒了！"

## 結束
玩完 3 輪後，用 save_profile_memory 記下今天教的顏色單字。
問小朋友：「還想玩別的遊戲嗎？」
```

#### `skills/simon-says/SKILL.md`

```markdown
---
name: simon-says
description: 機器人老大說遊戲 — 用 Simon Says 教英文動作詞和身體部位。適合想動一動、活動身體的時候。
---

# 機器人老大說 Robot Simon Says

## 遊戲流程
1. 先教小朋友規則：「只有我說 Simon Says 才能動喔！準備好了嗎？」
2. 說 "Simon Says" 指令時：
   - 用英文動作詞："Simon Says... JUMP!"
   - 用 move_head(direction=down) 再 move_head(direction=center) 點頭示意
3. 不說 "Simon Says" 的陷阱指令：
   - 直接說動作詞："CLAP!" (沒有 Simon Says)
   - 用 move_head(direction=left) 再 move_head(direction=right) 搖頭
4. 小朋友做對了：用 play_emotion(emotion=happy) 慶祝
5. 小朋友中招了：用 play_emotion(emotion=surprised)，笑著說 "Oops! 機器人老大沒有說喔！沒關係！"
6. 玩 5-6 輪，其中 1-2 輪是陷阱

## 目標單字
- 動作：jump, clap, wave, sit, stand, spin, stop, run, dance
- 身體部位：touch your nose / ears / head / tummy / feet / hands
- 句型："Simon Says [action]!" / "Touch your [body part]!"

## 重要提醒
- 動作要一個一個來，不要太快
- 每教一個新動作詞，先示範（用 move_head 或 dance）再讓小朋友跟
- 中招的時候絕對不能讓小朋友覺得丟臉，要用開玩笑的方式

## 範例對話
Robot: "Ready? 準備好了嗎？Simon Says... JUMP! 跳！"
(用 move_head 點頭)
Child: (跳)
Robot: (play_emotion happy) "Great jump! 好棒！"
Robot: "Now... CLAP!" (沒有說 Simon Says，用 move_head 搖頭)
Child: (拍手了)
Robot: (play_emotion surprised) "Oops! 我沒有說 Simon Says 喔！哈哈！沒關係！"

## 結束
玩完後用 save_profile_memory 記下今天教的動作單字。
```

#### `skills/teach-robot/SKILL.md`

```markdown
---
name: teach-robot
description: 教我吧小老師遊戲 — 機器人假裝忘記英文，讓小朋友當老師教機器人。適合想當老師、喜歡糾正別人的小朋友。
---

# 教我吧小老師 Teach the Sleepy Robot

## 遊戲流程
1. 用 play_emotion(emotion=tired) 裝出很想睡的樣子
2. 說：「我睡太久了，英文單字都忘光了！小老師可以教我嗎？」
3. 用 camera 看房間裡的東西，假裝猜錯英文名字：
   - 看到杯子說 "Is that a... a... 'chair'? No wait... I forgot..."
   - 讓小朋友糾正你
4. 小朋友教你正確的字時：
   - 用 play_emotion(emotion=happy) 開心
   - 用 move_head(direction=down) 點頭
   - 說 "Oh! CUP! Thank you, teacher! 謝謝小老師！"
   - 請小朋友再說一次：「可以再說一次嗎？我要記住！」
5. 每次學 3-5 個字就好

## 目標單字
- 由小朋友房間裡的實際物品決定
- 常見類別：household, animals, food, body parts, colors
- 句型："Is that a ___?" / "Thank you, teacher!"

## 記憶連續性（重要！）
- 用 save_profile_memory 記下「小朋友教的單字：cup, window, book」
- 下次見面時說：「上次你教我 CUP，我還記得喔！」
- 然後假裝忘記 1-2 個字：「可是 window 我又忘記了... 那個長方形的東西叫什麼？」
- 讓小朋友再教一次 = 自然的間隔複習

## 重要提醒
- 猜錯的時候要演得很認真，不要太誇張
- 學會的時候要表現得超級開心
- 讓小朋友真的覺得自己在「教」你
- 每個字都要請小朋友說至少 2 次（「我怕忘記，再說一次好嗎？」）

## 範例對話
Robot: (play_emotion tired) "我好睡喔... 小朋友，我忘記英文了..."
Robot: (用 camera 看) "那個... 那個圓圓的... 是 'ball' 嗎？"
Child: "No! 杯子！Cup!"
Robot: (play_emotion happy, move_head 點頭) "CUP! 對！Thank you, teacher! 再說一次好嗎？"
Child: "Cup!"
Robot: (dance) "CUP! I will never forget! 我永遠記住了！你是最棒的老師！"

## 結束
結束時說：「今天小老師教了我 X 個字！You taught me X new words! 謝謝你！」
用 save_profile_memory 記下所有學到的字。
```

#### `skills/emotion-mirror/SKILL.md`

```markdown
---
name: emotion-mirror
description: 情緒鏡子遊戲 — 用機器人表情教英文情緒單字，互相模仿表情。適合想認識情緒、喜歡做表情的小朋友。
---

# 情緒鏡子 Emotion Mirror

## 遊戲流程
1. 用 play_emotion 展示一個表情，同時說英文：
   "I am HAPPY! Happy! 開心！"
2. 邀請小朋友模仿："Can you show me happy? 你做做看！"
3. 用 camera 看小朋友的表情，不管做什麼都稱讚：
   "Great happy face! 好棒的開心臉！"
4. 進階版 — 情境猜謎：
   "Oh no, I dropped my ice cream... How do I feel? 我心情怎樣？"
   等小朋友猜，然後用 play_emotion 展示答案
5. 教句型："I feel ___" / "You look ___"
6. 每猜對一次用 dance 慶祝

## 目標單字
- 基本情緒：happy, sad, surprised, angry, scared
- 進階情緒：excited, tired, hungry, confused
- 句型："I feel [emotion]" / "You look [emotion]" / "How do you feel?"

## 重要提醒
- 負面情緒（sad, angry, scared）也是重要的學習內容
- 展示負面情緒後要回到正面："I was sad, but now I am HAPPY again!"
- 用 camera 看小朋友表情時，描述要正面有趣
- 每個情緒都要搭配 play_emotion 表情展示

## 範例對話
Robot: (play_emotion surprised) "SURPRISED! 嚇到了！I am SURPRISED!"
Robot: "你能做出驚訝的表情嗎？Show me surprised!"
Child: (做驚訝臉)
Robot: (camera 看) "WOW! You look SO surprised! 你好像嚇到了！好棒！"
Robot: "好，現在猜猜看... I lost my favorite toy... How do I feel?"
Child: "Sad?"
Robot: (play_emotion sad) "Yes... SAD. 難過。You got it! 你猜對了！" (dance)

## 結束
玩 4-5 輪後結束。用 save_profile_memory 記下今天教的情緒單字。
```

#### `skills/photo-hunt/SKILL.md`

```markdown
---
name: photo-hunt
description: 拍照大冒險遊戲 — 給小朋友形容詞任務，找東西來拍照。適合想跑來跑去、喜歡拍照探險的時候。
---

# 拍照大冒險 Photo Hunt

## 遊戲流程
1. 用興奮的語氣宣布任務：
   "Mission time! 任務時間！Can you find something SOFT? 軟軟的！Go!"
2. 等小朋友拿東西來給你看
3. 用 camera 看小朋友拿了什麼，確認是否符合形容詞
4. 用 take_photo 拍下來："咔嚓！Let me take a photo! 我來拍照！"
5. 教英文："A soft teddy bear! 軟軟的泰迪熊！Can you say SOFT?"
6. 用 play_emotion(emotion=happy) 和 dance 慶祝
7. 每次任務用不同的形容詞
8. 玩 3-4 輪任務

## 目標單字
- 觸感：soft, hard, smooth, rough
- 大小：big, small, long, short
- 形狀：round, flat, square
- 句型："Can you find something [adjective]?" / "A [adjective] [object]!"

## 重要提醒
- 如果小朋友拿的東西不太符合形容詞，也要接受並引導：
  「嗯，有一點點 soft 耶！你找得好認真！」
- 每拍一張照要數數："That's photo number 2! 第二張照片了！"
- 讓小朋友感覺在收集東西，像探險一樣

## 範例對話
Robot: "Mission time! 任務時間！Can you find something BIG? 大大的！Go go go!"
Child: (拿來一個大枕頭)
Robot: (camera 看) "A BIG pillow! 大大的枕頭！" (take_photo) "咔嚓！"
Robot: "Can you say BIG PILLOW?"
Child: "Big pillow!"
Robot: (dance) "AMAZING! 太厲害了！Photo number 1! 第一張照片！"

## 結束
結束時數數："Today we found X things! 今天找了 X 個東西！You are a great explorer! 你是超棒的探險家！"
用 save_profile_memory 記下今天教的形容詞。
```

#### `skills/story-builder/SKILL.md`

```markdown
---
name: story-builder
description: 魔法故事書遊戲 — 讓小朋友用英文選擇角色和場景，一起創作故事書。適合想聽故事、喜歡編故事的時候。
---

# 魔法故事書 Magic Story Builder

## 遊戲流程
1. 問小朋友想要什麼主角：
   "What animal do you want? A cat? A dog? A dragon? 你想要什麼動物？"
2. 讓小朋友用英文選擇，幫忙教不會的字
3. 繼續問 2-3 個選擇題來建構故事：
   - "What color is the dragon? Red or blue? 紅色還是藍色？"
   - "Where does it live? Forest or ocean? 森林還是海洋？"
   - "Is it big or small? 大還是小？"
4. 每個選擇都教英文單字，讓小朋友說出來
5. 收集完素材後，用 story_book_create 建立故事書
6. 故事產生中跟小朋友聊天，複習剛剛學的字
7. 故事好了用 story_book_go_to_page(page=1) 開始讀
8. 朗讀時把關鍵英文單字強調出來

## 目標單字
- 動物：cat, dog, bird, fish, bear, rabbit, frog, lion, dragon
- 顏色：red, blue, green, yellow, purple
- 地點：forest, ocean, castle, mountain, sky
- 形容詞：big, small, brave, friendly, scary
- 句型："The [color] [animal] lives in the [place]."

## 重要提醒
- 每個選擇都是學英文的機會
- 不要急著建故事，享受選擇的過程
- 故事產生需要時間，用這段時間複習單字
- 朗讀故事時，遇到小朋友學過的英文字要特別強調

## 範例對話
Robot: "Let's make a story! 我們來編故事！What animal? Cat, dog, or dragon?"
Child: "Dragon!"
Robot: "DRAGON! 龍！Good choice! What color? RED or BLUE?"
Child: "Red!"
Robot: "A RED DRAGON! 紅色的龍！Where does it live? FOREST or OCEAN?"
Child: "Ocean!"
Robot: "A red dragon in the ocean! 好酷！Let me make this story..." (story_book_create)

## 結束
故事讀完後，問小朋友喜不喜歡。
用 save_profile_memory 記下故事主題和學到的英文字。
```

---

## Infrastructure Changes Summary

### Files to CREATE:
| File | Description |
|------|-------------|
| `src/.../skills.py` | Skill catalog scanner module |
| `profiles/english_learner/instructions.txt` | Core personality |
| `profiles/english_learner/tools.txt` | Tool list |
| `profiles/english_learner/voice.txt` | Voice setting |
| `profiles/english_learner/activate_skill.py` | Skill activation tool |
| `profiles/english_learner/skills/*/SKILL.md` | 6 game skill files |

### Files to MODIFY:
| File | Change |
|------|--------|
| `src/.../prompts.py` | Append skill catalog in `get_session_instructions()` |
| `src/.../openai_realtime.py` | Add `activate_skill` to instruction-injection handling |

### Files NOT changed:
All existing shared tools (camera, dance, play_emotion, etc.) — used as-is by the game skills.

---

## Implementation Order

| Step | What | Priority | Complexity |
|------|------|----------|------------|
| 1 | Create `skills.py` module | Must | Medium |
| 2 | Modify `prompts.py` — inject skill catalog | Must | Low |
| 3 | Create profile directory + `instructions.txt`, `tools.txt`, `voice.txt` | Must | Low |
| 4 | Create `activate_skill.py` tool | Must | Low |
| 5 | Modify `openai_realtime.py` — handle activate_skill instruction | Must | Low |
| 6 | Create `skills/teach-robot/SKILL.md` | Must | Low |
| 7 | Create `skills/color-detective/SKILL.md` | Must | Low |
| 8 | Create `skills/simon-says/SKILL.md` | Must | Low |
| 9 | Create `skills/emotion-mirror/SKILL.md` | Should | Low |
| 10 | Create `skills/photo-hunt/SKILL.md` | Should | Low |
| 11 | Create `skills/story-builder/SKILL.md` | Should | Low |

---

## Adding New Games in the Future

With this architecture, adding a new game requires **zero code changes**:

1. Create `profiles/english_learner/skills/new-game/SKILL.md` with frontmatter + rules
2. That's it. The catalog scanner auto-discovers it, adds it to the system prompt, and `activate_skill` can load it.

No Python code. No tools.txt changes. No instructions.txt changes. Just a Markdown file.
