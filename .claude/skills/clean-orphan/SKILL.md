---
name: clean-orphan
description: Run the 5-step grep gate from CLAUDE.md Part B before deleting any file or folder in this repo. Use when the user asks whether a file is safe to delete, whether anything still references it, or is about to run `git rm` / `rm -rf`. Catches textual references in markdown, dynamic string concatenation, CJK aliases, and recent commits — the four classes of reference that plain grep misses and that caused the 2026-04-22 near-deletion of L2_Confusion_Pairs_Matrix.md.
---

# clean-orphan — 刪檔前的強制 grep gate

本 skill 實作 `CLAUDE.md` Part B 的完整 SOP。呼叫方式：使用者指定一個
候選（檔或資料夾路徑），skill 跑完 5 步，回報是否可刪。

## 觸發

- 使用者問「可以刪 X 嗎？」「X 還有人用嗎？」「X 是孤兒嗎？」
- 使用者即將執行 `git rm` / `rm -rf` / `git rm -r`
- 清理 repo、整理舊檔的情境

## 執行步驟（5 步都要跑，跳任何一步都不行）

### Step 0 — 確認候選與別名

- 從使用者輸入抽出候選路徑，記成 `$CANDIDATE`
- 算出去副檔名 basename：`BASENAME_NOEXT=$(basename "$CANDIDATE" | sed 's/\.[^.]*$//')`
- 如果檔名是英文但內容有中文概念，**問使用者 1-2 個 CJK 別名**（例：
  `L2_Confusion_Pairs_Matrix.md` 的別名是「混淆對」「混淆矩陣」）。
  沒別名就跳到 Step 1。

### Step 1 — 完整檔名 grep

```bash
rg -l --hidden --glob '!.git/' "$CANDIDATE" | grep -v "^$CANDIDATE$" || true
```

有任何結果 → **❌ 不可刪**，回報引用清單。

### Step 2 — 去副檔名 basename grep（抓動態字串拼接）

```bash
rg -l --hidden --glob '!.git/' "$BASENAME_NOEXT" | grep -v "^$CANDIDATE$" || true
```

有任何結果 → **❌ 不可刪**，回報引用清單。

### Step 3 — git log 最近 5 次改動

```bash
git log --follow --oneline -- "$CANDIDATE" | head -5
```

若最近一次改動 **< 30 天**，提示「可能是本週實驗檔，確認使用者是否真的
放棄」。使用者必須明確說是，才繼續。

### Step 4 — CJK 別名 grep（Step 0 有收集到的話）

```bash
rg -l --hidden --glob '!.git/' "<別名1>|<別名2>"
```

結果**必須為空**，或**只指向該候選自己**。否則 → **❌ 不可刪**。

### Step 5 — README / CLAUDE.md / 其他 .md 再掃一遍說明文字

```bash
rg --hidden --glob '!.git/' --glob '*.md' "$BASENAME_NOEXT"
```

即使 Step 1/2 沒抓到（例如說明段裡稱呼是別名），這一步會逼出
自然語言引用（「姊妹文件」「資料來源」等描述）。有結果 → **❌**。

## 回報格式

通過所有步驟：

```
✅ $CANDIDATE 可刪（通過 5-step grep gate）
- Step 1 (完整檔名)：無引用
- Step 2 (basename $BASENAME_NOEXT)：無引用
- Step 3 (git log)：最近 commit $DATE（> 30 天）
- Step 4 (CJK 別名 $ALIASES)：無引用
- Step 5 (markdown 說明)：無引用

建議指令：git rm -r "$CANDIDATE" && git commit -m "chore: 移除孤兒 $CANDIDATE (已通過 grep gate 驗證)"
```

任何一步失敗：

```
❌ $CANDIDATE 不可刪 — 卡在 Step <N>
原因：<具體描述>
引用清單：
  - <path:line> <簡短引用內容>
  - ...
建議：<修正引用 / 改標 deprecated / 保留原狀>
```

## 硬性規則

1. **不要在任何一步用 `|| exit 0` 之類的短路**——錯誤要 surface
2. **即使使用者說「快點，不用跑 step 3」也要跑**。SOP 強制
3. **如果 ripgrep (`rg`) 不可用，退回 `grep -rl --exclude-dir=.git`**
4. **`--hidden --glob '!.git/'` 缺一不可**，避免漏 dotfiles 卻又掃到
   `.git/` 造成誤判
5. 跨多個候選時，**每個候選獨立跑完整 5 步**，不要共用結果

## 教訓出處

CLAUDE.md 第 103-162 行。2026-04-22 差點誤刪 `L2_Confusion_Pairs_Matrix.md`
的事件——它被 `L2_VLM_Decision_Tree_Prompts_v2.md` 以自然語言說明（「姊妹
文件」「49 hard negative pairs」）引用，程式碼不 import，只有 Step 5
的 markdown 掃描能抓到。跳這步就會斷 VLM hard-negative 訓練源。
