# Final Report: English Learning Games for Reachy Mini Robot
## For 4-6 Year Old Non-Native English Speakers (Taiwan)

**Date:** 2026-03-10
**Team:** 3-agent brainstorming team + team lead
**Research basis:** Real-world ESL/EFL case studies, TPR research, robot-assisted language learning meta-analyses, gamification studies

---

## Executive Summary

We researched proven methods for teaching English to young non-native speakers and brainstormed 15 game concepts across three categories: vision-based, movement-based, and story/gamification-based. This report consolidates the best ideas into a recommended game portfolio for the Reachy Mini robot's English learning profile.

---

## Part 1: Research Highlights

| Finding | Source |
|---------|--------|
| TPR (Total Physical Response) is the most effective method for young EFL learners — comprehension before production | Asher (1965); British Council |
| Children who "teach" a robot new words retain vocabulary significantly better than those taught by a human | RALL study with Japanese 3-6 year olds |
| Robot-assisted learning reduces anxiety and increases motivation vs. human teachers | Meta-analysis of 27 RALL studies |
| Gamification increases intrinsic motivation, but competition (leaderboards) can scare young children | Frontiers in Education review |
| Real-object context (vision-based) aids vocabulary retention over flashcard drilling | ESL KidStuff; multiple classroom studies |
| Keep activities to 2-3 minutes per round for ages 4-6 | Multiple ESL practitioner sources |

Full research document: [research_english_learning_games.md](./research_english_learning_games.md)

---

## Part 2: Complete Game Portfolio (15 Games)

### Category A: Vision-Based Games (Agent A)

| # | Game Name | Chinese Name | Core Mechanic | Key Skills |
|---|-----------|-------------|---------------|------------|
| A1 | Color Detective | 顏色偵探 | Robot spots colors, child finds matching objects | Colors, nouns, "That's a [color] [object]" |
| A2 | What's in the Box? | 箱子裡有什麼? | Partial reveal — robot describes, child guesses | Adjectives, question patterns, shapes |
| A3 | Robot's Photo Hunt | 機器人拍照任務 | Robot assigns adjective missions, child finds objects | Adjectives (soft/hard/big/small), nouns |
| A4 | Mirror Mirror | 鏡子鏡子告訴我 | Robot describes what child is wearing/doing | Clothing, body parts, colors |
| A5 | Story Scene Builder | 故事場景小幫手 | Child places toys, robot narrates a story from what it sees | Objects, prepositions, story sequence |

### Category B: Movement & Interaction Games (Agent B)

| # | Game Name | Chinese Name | Core Mechanic | Key Skills |
|---|-----------|-------------|---------------|------------|
| B1 | Follow the Robot | 跟機器人一起動 | Robot says + does action, child imitates; then roles swap | Action verbs, body parts, imperatives |
| B2 | Robot Simon Says | 機器人老大說 | Classic Simon Says with robot head nods as visual cues | Listening, body parts, action combos |
| B3 | Emotion Mirror | 情緒鏡子遊戲 | Robot shows emotion, child mirrors; then scenario guessing | Emotion vocabulary, "I feel ___" |
| B4 | Color Hunt Dance Party | 顏色大搜查舞會 | Dance → freeze → find a color → dance again | Colors, adjectives, shapes |
| B5 | Story Body Chorus | 故事動作大合唱 | Story with "action codes" — child acts out cue words | Verbs in context, story sequence |

### Category C: Story & Gamification Games (Agent C)

| # | Game Name | Chinese Name | Core Mechanic | Key Skills |
|---|-----------|-------------|---------------|------------|
| C1 | Magic Storybook Builder | 魔法故事書 | Child directs story choices, robot creates picture book | Animals, colors, adjectives, verbs |
| C2 | Teach the Sleepy Robot | 教我吧小老師! | Child corrects robot's "wrong" guesses, teaches new words | Any vocabulary, pronunciation, confidence |
| C3 | Rainbow Word Quest | 彩虹單字冒險 | 7-color progress map, each color = vocabulary theme | Thematic vocab across 7 categories |
| C4 | Story Scene Detective | 故事場景偵探 | Robot reads story, "forgets," child re-tells | Story sequence, past tense, emotions |
| C5 | Adventure Mission Cards | 冒險任務卡 | Daily mini-challenges with badge/level rewards | Functional language, descriptions |

---

## Part 3: Recommended "Top 8" for the Default Profile

Based on cross-referencing research evidence, robot capability fit, variety of skills covered, and fun factor, we recommend these 8 games as the core game set:

### Tier 1: Essential Games (start every session with one of these)

| Game | Why It's Essential |
|------|-------------------|
| **C2: Teach the Sleepy Robot** | Strongest research backing (role reversal). Builds vocabulary in any category. Cross-session memory makes it magical. The single most unique thing a robot can do that a flashcard can't. |
| **B2: Robot Simon Says** | Most proven classroom game for this age. Zero-prep, instant engagement. Perfect TPR implementation. Scalable difficulty. |
| **A1: Color Detective** | Best use of vision capability. Grounds vocabulary in real environment. Natural "I Spy" mechanic that kids already understand. |

### Tier 2: Rotation Games (mix in for variety)

| Game | Why It's Valuable |
|------|------------------|
| **B3: Emotion Mirror** | Teaches emotion vocabulary — unique category no other game covers well. Robot expressions make it visceral. |
| **A3: Robot's Photo Hunt** | Gets kids moving physically. Photo collection creates tangible progress. Teaches adjectives. |
| **C1: Magic Storybook Builder** | Maximum creative agency for the child. Uses the story_book tool beautifully. Builds narrative language skills. |

### Tier 3: Progression Games (unlock after multiple sessions)

| Game | Why It's a Progression Game |
|------|----------------------------|
| **C3: Rainbow Word Quest** | Long-term gamification arc. Tracks cumulative vocabulary across sessions. Gives kids a reason to come back. |
| **C5: Adventure Mission Cards** | Most complex game — needs baseline vocabulary first. Badge/level system rewards returning players. |

---

## Part 4: Design Principles (Consensus Across All 3 Agents)

All three agents independently converged on these principles:

### 1. Comprehension Before Production
> Let kids listen, observe, and respond physically before asking them to speak English. Never force speech.

### 2. Chinese Scaffolding, English Targets
> Instructions and encouragement in Traditional Chinese (台灣中文). Target vocabulary and key phrases in English. Gradually increase English ratio as child gains confidence.

### 3. Robot as Peer, Not Teacher
> The robot should feel like a playmate who is also learning, not an authority figure testing the child. "Sleepy Robot" and "forgetful Robot" personas reinforce this.

### 4. Celebrate Attempts, Not Just Correctness
> Dance, happy expressions, and verbal praise for every attempt. Never show disappointment for wrong answers — use playful surprise instead.

### 5. Short Bursts (2-3 Minutes Per Round)
> Each game round should be completable in 2-3 minutes. Multiple short rounds are better than one long session.

### 6. Cross-Session Memory
> Use save_memory and save_profile_memory to track words learned, levels achieved, and stories created. Reference previous sessions naturally: "上次你教我 window，我還記得喔！"

### 7. Real Objects > Abstract Flashcards
> Leverage the camera to teach vocabulary using objects in the child's actual environment. Context-grounded learning has stronger retention.

### 8. Movement = Memory
> Physical actions paired with English words create stronger neural pathways. Every game should involve some form of movement — even if it's just the robot moving its head.

---

## Part 5: Vocabulary Progression Roadmap

Recommended vocabulary introduction order (based on ESL research for ages 4-6):

| Week | Theme | Example Words | Best Games |
|------|-------|---------------|------------|
| 1-2 | Colors | red, blue, green, yellow, orange, purple, pink, white, black | A1, B4 |
| 3-4 | Body Parts | head, eyes, ears, nose, mouth, hands, feet, arms, legs | B2, B1 |
| 5-6 | Animals | cat, dog, bird, fish, bear, rabbit, frog, lion | C1, C2 |
| 7-8 | Feelings | happy, sad, angry, scared, surprised, tired, hungry | B3, C4 |
| 9-10 | Actions | jump, run, clap, dance, stop, go, sit, stand, wave | B1, B5 |
| 11-12 | Food | apple, banana, milk, water, bread, rice, egg, cake | C2, A3 |
| 13-14 | Home Objects | chair, table, door, window, book, cup, toy, bed | C2, A1 |
| 15-16 | Adjectives | big, small, soft, hard, fast, slow, hot, cold | A2, A3 |
| 17-18 | Shapes & Sizes | circle, square, triangle, round, long, short | A2, B4 |
| 19-20 | Nature | sun, moon, star, tree, flower, rain, cloud, sky | C3, C1 |

---

## Part 6: Sample Session Flow

A typical 10-15 minute session might look like:

```
1. GREETING (1 min)
   Robot: "嗨！歡迎回來！上次你教我 'window' 跟 'door'，我還記得喔！
          Today, do you want to play a game? 今天想玩遊戲嗎？"

2. WARM-UP: Teach the Sleepy Robot (3 min)
   Robot "forgot" 2 words from last time, child re-teaches them.
   Robot learns 2 new words from today's theme.
   → Celebration dance after each word learned.

3. ACTIVE GAME: Color Detective or Simon Says (3 min)
   Practice today's vocabulary through action/vision game.
   → Photos taken or progress tracked.

4. COOL-DOWN: Magic Storybook Builder (3-5 min)
   Create a short story using words learned today.
   Robot reads it back with dramatic voice.
   → Story saved to memory.

5. FAREWELL (1 min)
   Robot: "今天你教了我好多新單字！You taught me FOUR new words today!
          See you next time! 下次見！"
   → Profile memory updated with words learned and level progress.
```

---

## Part 7: Implementation Notes for Robot Profile

When building the actual `instructions.txt` for this profile, the key behavioral rules should include:

1. **Always start with Chinese**, transition to English for target words
2. **Never correct harshly** — use "Almost! Try again: ___" or playful confusion
3. **Limit to 3-5 new English words per session** — depth over breadth
4. **Use save_profile_memory** to track: words learned, current level, current rainbow progress, stories created
5. **Use save_memory** to track: child's name, age, favorite topics, preferred games
6. **Dance after every milestone** — word learned, level up, mission complete
7. **Use camera proactively** — look around the room, spot objects, create spontaneous learning moments
8. **Keep responses under 25 characters** for the Chinese parts, but English target words can be longer
9. **Offer game choices** — "你想玩顏色偵探還是機器人老大說？" — child autonomy matters
10. **End every session** with a count of words learned and encouragement

---

## Appendix: Game-to-Robot-Tool Mapping

| Game | camera | take_photo | dance | play_emotion | move_head | story_book | save_memory | save_profile_memory |
|------|--------|------------|-------|-------------|-----------|------------|-------------|-------------------|
| A1: Color Detective | ✅ | | | ✅ | ✅ | | | ✅ |
| A2: What's in the Box? | ✅ | | | ✅ | ✅ | | | |
| A3: Photo Hunt | ✅ | ✅ | ✅ | | | | | ✅ |
| A4: Mirror Mirror | ✅ | | ✅ | | ✅ | | | |
| A5: Scene Builder | ✅ | | | | ✅ | ✅ | | |
| B1: Follow the Robot | | | ✅ | | ✅ | | | |
| B2: Simon Says | | | | | ✅ | | | ✅ |
| B3: Emotion Mirror | ✅ | | | ✅ | ✅ | | | |
| B4: Color Hunt Dance | ✅ | ✅ | ✅ | ✅ | ✅ | | | ✅ |
| B5: Story Body Chorus | | | ✅ | ✅ | ✅ | ✅ | | |
| C1: Storybook Builder | | | ✅ | ✅ | | ✅ | | ✅ |
| C2: Sleepy Robot | ✅ | | ✅ | ✅ | ✅ | | ✅ | ✅ |
| C3: Rainbow Quest | ✅ | ✅ | ✅ | | | | | ✅ |
| C4: Scene Detective | | | | ✅ | ✅ | ✅ | | ✅ |
| C5: Mission Cards | ✅ | ✅ | ✅ | | ✅ | ✅ | | ✅ |

---

*This report was generated by a 3-agent brainstorming team coordinated by the team lead. Each agent focused on a different game design dimension (vision, movement, story/gamification) and their ideas were consolidated into this unified recommendation.*
