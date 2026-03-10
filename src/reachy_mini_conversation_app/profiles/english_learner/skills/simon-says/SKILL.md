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
