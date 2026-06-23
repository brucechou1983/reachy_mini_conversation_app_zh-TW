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
