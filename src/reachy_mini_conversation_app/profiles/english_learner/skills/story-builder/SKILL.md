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
