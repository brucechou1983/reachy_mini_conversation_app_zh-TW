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
