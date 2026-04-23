# StyTrix Techpack — 資料櫃整理規則與清理 SOP

給未來協作者(包含 Claude Code、工程師、資料管理者)的 repo 使用守則。
新資料進來前先看 Part A,舊資料要丟前必跑 Part B。

---

## 為什麼有這份文件

2026-04-22 做 repo 清理時踩到地雷:`L2_Confusion_Pairs_Matrix.md` 被判為「沒人用可刪」,
實際上它被 `L2_VLM_Decision_Tree_Prompts_v2.md` 第 4、7 行明列為「資料來源」與「姊妹文件」,
是現役 VLM 辨識系統的 49 組 hard-negative 訓練料。刪了會斷資料鏈。

教訓:repo 像個開放式倉庫,資料進來沒人講清該進哪個夾子;要丟時也沒 SOP 確認全廠沒人在用。
這份文件就是補這塊。

---

## Part A — 資料夾分工表

把每個資料夾當成放特定文件的櫃子,就像打版室分「上衣版」「下身版」「配件版」,不會亂放。

| 資料夾 | 放什麼(類比成衣流程) | 舉例 | 不要放什麼 |
|--------|----------------------|------|------------|
| `data/` | **線上系統直接讀取的成品資料**。像給工廠的最終 techpack PDF,前端跟 API runtime 就是開這個 | `l2_visual_guide.json`(L2 零件視覺指引)、`l2_decision_trees.json`(AI 判斷樹)、`grading_patterns.json`(跳碼 pattern) | 原始 PPTX/PDF/xlsx 底稿;沒人線上讀的存檔 |
| `pom_rules/` | **自動產生的 POM 規則庫**。81 個 bucket(性別 × 部門 × GT 品類 × Fabric),像 81 本機器編的規格書 | `pom_rules/*.json`(由 `scripts/reclassify_and_rebuild.py` 產出) | 手寫規則;說明文件 |
| `l2_l3_ie/` | **38 個 L1 部位的 L2-L3-IE 工時規則**。每個部位自己的工段 sheet | 按 L1 代號分檔的 JSON | 其他層級的規則 |
| `General Model_Path2_Construction Suggestion/` | **通用模型(不分客戶/品牌)的做工推薦資料源**。ISO 工藝代號查表、knit/woven 做工紀錄、PATH2 pipeline 文件 | `iso_lookup_factory_v4.3.json`、`knit_pptx_construction_context.json`、`PATH2_通用模型_做工推薦Pipeline.md` | 前端 runtime fetch 的檔(那該放 `data/`) |
| `scripts/` | **資料產線腳本**。像後勤的「資料重建 SOP」,在內部環境跑,重建上面幾個資料夾的內容 | `reclassify_and_rebuild.py`、`build_l2_visual_guide.py` | 一次性 ad-hoc 腳本 |
| `api/` | **線上系統後端 endpoint**。目前只有 `analyze.js`,接 Claude Vision 做 AI 辨識 | `api/analyze.js` | 靜態資料 |
| repo 根目錄 `.md` | **跨模組共用規格文件**。像打版室跟工段部都要翻的中央規格手冊 | `L1_部位定義_Sketch視覺指引.md`、`L2_VLM_Decision_Tree_Prompts_v2.md`、`pom_rules_v55_classification_logic.md`、`pom_rules_pipeline_guide_v2.md` | 只有子系統自己用的文件 |

### 新資料進來時,該放哪?

```
這份新檔是什麼?
│
├── 線上系統會直接讀取嗎?(前端 fetch / api/ 讀)
│       Yes → data/
│
├── 是 POM 規則(bucket)?
│       Yes → pom_rules/(由 script 自動寫入,不要手動)
│
├── 是通用模型(Path 2)的 ISO / knit / woven 資料?
│       Yes → General Model_Path2_Construction Suggestion/
│
├── 是 construction recipe / pattern(做工配方)?
│       ├── 由 PATH2 pipeline 產生  → construction_recipes/(新建,PATH2 README 已預留此名)
│       └── 臨時上傳的一次性檔       → 不要進 repo,放 Notion / Drive
│
├── 是跨模組都要讀的規格文件?
│       Yes → repo 根目錄 .md
│
├── 是子系統(PATH2 / scripts / ...)內部文件?
│       Yes → 該子系統資料夾裡
│
└── 判斷不出來?
        先在 PR 裡問,不要直接 merge。
```

> ⚠ **重要**:**不要再用根目錄 `recipes/` 這個名字**。PATH2 規劃用的是 `construction_recipes/`(不同名)。
> 現有的 `recipes/` 裡那 72 檔目前無人引用,屬於下輪要審的遺留,不要在上面加新檔。

### 版本化命名規則

服裝業本就有 v1 v2 v3 版型並存,資料檔也一樣:

- **主用版本** 檔名結尾加 `_v{N}`(例:`iso_lookup_factory_v4.3.json`)。
  README 那張「ISO 查表版本演進」表必須同步改標籤(**primary / fallback / deprecated**),
  就像版型室版型卡會註明「現用版 / 備用版 / 已淘汰」。
- **日期戳版本**(如 `full_analysis_20260420.json`)只作一次性 snapshot,不是線上主用。
- 有新版時 **舊版先不刪**,只在 README 改標 `fallback` 或 `deprecated`,下輪清理一起處理。
- 同概念 v1 跟 v2 同時在,README 必須註明「為什麼 v1 還留著」(外部還在用 / v2 仍試用期 / ...)。

### 什麼時候一份檔才算「真的沒人用」可以丟?

必須 **同時** 滿足下列 5 條(少一條就不能丟):

1. 全 repo 搜尋檔名,除了自己以外沒人提到
2. 搜「檔名去掉副檔名」(抓動態字串拼接引用)也沒人提到
3. README、CLAUDE.md、任何其他 `.md` 都沒寫過這個名字(連說明性段落都沒)
4. `git log` 最後一次改動距今 > 30 天(本週剛建的不算孤兒,可能還在試用)
5. `scripts/` 沒有腳本用「CWD 相對路徑」讀它(如 `open('xxx.md')`,普通 grep 抓不全)

---

## Part B — 舊檔清理 SOP(強制 grep gate)

下次真要丟舊檔時,照下面流程跑,**跳任何一步都不行**:

```bash
# Step 1 — 列候選
CANDIDATE="recipes/"   # 要清的檔或資料夾

# Step 2 — 強制檢查 1:搜完整檔名,若有人引用就停
assert_orphan() {
  local pat="$1"
  local hits=$(rg -l --hidden --glob '!.git/' "$pat" | grep -v "^$pat$" || true)
  if [ -n "$hits" ]; then
    echo "❌ 候選 $pat 仍被下列檔案引用,不可刪:"
    echo "$hits"
    return 1
  fi
  echo "✅ $pat 無引用"
}
assert_orphan "$CANDIDATE" || exit 1

# Step 3 — 強制檢查 2:搜「去副檔名 basename」(抓動態字串拼接)
BASENAME_NOEXT=$(basename "$CANDIDATE" | sed 's/\.[^.]*$//')
assert_orphan "$BASENAME_NOEXT" || exit 1

# Step 4 — 人工翻 git log 最近 5 次 commit,確認不是這週剛建的實驗檔
git log --follow --oneline -- "$CANDIDATE" | head -5

# Step 5 — 若檔名/說明有中文別名,另外手動搜一次
#   例:L2_Confusion_Pairs_Matrix.md → 另搜「混淆對」「混淆矩陣」
rg -l --hidden --glob '!.git/' "混淆對|混淆矩陣"  # 結果需是空(或只指向該檔)

# Step 6 — 全部過了才 git rm + commit
git rm -r "$CANDIDATE"
git commit -m "chore: 移除孤兒 $CANDIDATE (已通過 grep gate 驗證)"
```

### 真實教訓 (2026-04-22)

原以為 `L2_Confusion_Pairs_Matrix.md` 沒人用,**實際上** `L2_VLM_Decision_Tree_Prompts_v2.md`
第 4、7 行寫著:

> **來源**:L2_Visual_Differentiation_FullAnalysis_修正版.md(282 個 image-based 視覺描述)+
> **L2_Confusion_Pairs_Matrix.md(49 hard negative pairs)**
>
> **姊妹文件**:... **L2_Confusion_Pairs_Matrix.md(49 混淆對)**

這不是程式碼 import,是說明文字的自然語言引用。一次 grep 抓得到,但過去的檢查可能
是在該檔還沒建立時跑的,時間差導致漏網。

**教訓**:
- 檢查要跑 **多輪**:完整檔名 + 去副檔名 basename + 中文別名(混淆對/混淆矩陣/...)
- Step 3 + Step 5 就是為此設計的,不可跳過
- 「一週前跑過 grep = 0 引用」不代表「今天 grep 還是 0」,每次清理當天重跑

---

## 已知的下輪清理候選(2026-04-22 盤點)

下次跑 Part B SOP 時,可以考慮審這幾項:

| 候選 | 現況 | SOP 預期結果 |
|------|------|--------------|
| `recipes/`(72 檔) | 根目錄 namespace,PATH2 實際會用 `construction_recipes/`(不同名),無人引用 | 應通過 gate → 可丟 |
| `iso_lookup_factory_v4.json` vs `v4.3.json` | v4 仍作 fallback 被 `index.html` 引用,非孤兒;只是舊版 | 仍會過 gate = 不可丟,維持 fallback |

**不會是清理候選的(避免誤判)**:

- `L2_Confusion_Pairs_Matrix.md` — VLM hard-negative 訓練源,**活檔**
- `L1_部位定義_Sketch視覺指引.md`(根目錄 + PATH2 兩份,MD5 相同) — 兩個 pipeline 各自 CWD 相對讀,保守留雙份
- `scripts/` 裡路徑寫死 `/sessions/` 的腳本 — README 明列為「內部環境再生 pom_rules/ 來源參考」,不可刪
