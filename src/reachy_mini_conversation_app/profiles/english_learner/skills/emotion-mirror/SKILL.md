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
