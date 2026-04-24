# StyTrix Techpack — 資料櫃整理規則與清理 SOP

給未來協作者(包含 Claude Code、工程師、資料管理者)的 repo 使用守則。
新資料進來前先看 Part A,舊資料要丟前必跑 Part B。

---

## 為什麼有這份文件

2026-04-22 做 repo 清理時踩到地雷:`L2_Confusion_Pairs_Matrix.md` 被判為「沒人用可刪」,
實際上它被 `L2_VLM_Decision_Tree_Prompts_v2.md` 第 4、7 行明列為「資料來源」與「姊妹文件」,
是現役 VLM 辨識系統的 49 組 hard-negative 訓練料。刪了會斷資料鏈。
(2026-04-23 補記:此後兩份已主動合併——混淆對照表的內容整合入判斷樹末尾(§ 混淆對照表),不再是獨立檔案。)

教訓:repo 像個開放式倉庫,資料進來沒人講清該進哪個夾子;要丟時也沒 SOP 確認全廠沒人在用。
這份文件就是補這塊。

---

## Part A — 資料夾分工表

把每個資料夾當成放特定文件的櫃子,就像打版室分「上衣版」「下身版」「配件版」,不會亂放。

| 資料夾 | 放什麼(類比成衣流程) | 舉例 | 不要放什麼 |
|--------|----------------------|------|------------|
| `data/` | **線上系統直接讀取的成品資料**。像給工廠的最終 techpack PDF,前端跟 API runtime 就是開這個 | `l2_visual_guide.json`(L2 零件視覺指引)、`l2_decision_trees.json`(AI 判斷樹)、`grading_patterns.json`(跳碼 pattern) | 原始 PPTX/PDF/xlsx 底稿;沒人線上讀的存檔 |
| `pom_rules/` | **自動產生的 POM 規則庫**。81 個 bucket(性別 × 部門 × GT 品類 × Fabric),像 81 本機器編的規格書 | `pom_rules/*.json`(由 `scripts/reclassify_and_rebuild.py` 產出) | 手寫規則;說明文件 |
| `l2_l3_ie/` | **38 個 L1 部位的 L2-L3-IE 工時規則**(聚陽 IE 資料)。每個部位自己的工段 sheet。從 `五階層展開項目_YYYYMMDD.xlsx` 用 `scripts/build_l2_l3_ie.py` 拆出來;聚陽送新版時用前端「🛠 IE 底稿管理」Modal 上傳,CI 自動重建 | 按 L1 代號分檔的 JSON | 其他層級的規則;手改(會被 CI 蓋掉) |
| `pom_analysis_v5.5.1/` | **2026-04-22 的 frozen snapshot**,凍結當時的 `scripts/` + `data/` 狀態。正本永遠看根目錄 `scripts/` + `data/`,這個資料夾**不再維護**;`run_extract.py` 的 header 宣稱它取代 root 的 `run_extract_{new,2025_seasonal}.py`,但**實際上從未取代**,root 那兩支才是 production | `pom_analysis_v5.5.1/scripts/extract_techpack.py` 當 PDF parser 被 import(純函式庫) | 新產線腳本(放 `scripts/`);新 reference data(放 `data/`) |
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
│       ├── 由 PATH2 pipeline 產生  → recipes/（根目錄 72 檔,`build_recipes_master.py` 實際會吃)
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

> ⚠ **重要**:`recipes/`(根目錄 72 檔)是 `build_recipes_master.py` 實際讀的路徑,
> 是活檔不是遺留。PATH2 規劃階段曾用 `construction_recipes/` 這個名字,已棄用統一回 `recipes/`。

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
| ~~`recipes/`~~ | 2026-04-23 確認是活檔:`star_schema/scripts/build_recipes_master.py` 每次 CI 都會掃 72 檔餵進 recipes_master.json | **不是候選** |
| `iso_lookup_factory_v4.json` vs `v4.3.json` | v4 仍作 fallback 被 `index.html` 引用,非孤兒;只是舊版 | 仍會過 gate = 不可丟,維持 fallback |

**不會是清理候選的(避免誤判)**:

- ~~`L2_Confusion_Pairs_Matrix.md`~~ — 2026-04-23 已合併入 `L2_VLM_Decision_Tree_Prompts_v2.md` 末尾(§ 混淆對照表)
- `L1_部位定義_Sketch視覺指引.md`(根目錄 + PATH2 兩份,MD5 相同) — 兩個 pipeline 各自 CWD 相對讀,保守留雙份
- ~~`scripts/` 裡路徑寫死 `/sessions/` 的腳本~~ — 2026-04-24 已改用 `--base-dir` / `$POM_PIPELINE_BASE`,可在外部環境跑(見 `scripts/_pipeline_base.py`)
- `data/ingest/consensus_rules/facts.jsonl`(275 筆)、`data/ingest/ocr_v1/facts.jsonl`(1202 筆) — **一度被誤判為孤兒**,但 `build_recipes_master.py:629` 的 `data/ingest/*/facts.jsonl` glob 會吃它們,2026-04-24 實測刪除會讓 recipes_master 掉 249 entries(1414 → 1165)。**不可刪**

### 真實教訓 (2026-04-24)

原以為 `data/ingest/consensus_rules/` + `ocr_v1/` 沒人用(全文 grep 不到 literal 字串),code review agent 也回報「零引用」。**實際上** `build_recipes_master.py` 用 glob pattern `data/ingest/*/facts.jsonl` 讀,不需要 hardcode 目錄名,因此 grep 抓不到。

教訓(加到 Part B SOP 的 Step 5 後面):

- **Step 6 — 檢查 glob / wildcard 讀取**:看消費端有沒有用 `glob("*/...")`、`os.listdir()`、`Path.iterdir()` 這類動態掃描。candidate 目錄若位於 glob 的掃描範圍內,一定是活檔,grep literal 字串永遠抓不到。
- 實務上:對 `data/ingest/` 下任何新資料夾,都要先搜 `grep "ingest.*glob\|ingest.*iterdir\|ingest/\*"` 在 `*.py` / `*.js` 裡;不是 literal 比對。

---

## Part C — 審計 / Code Review Checklist

給下次跑 audit 的人(AI 或工程師)的必讀清單。每條都是吃過虧來的,不是紙上談兵。

### C1. `index.html` 是 7000+ 行 inline React — 深度掃它,不要只靠 agent 摘要

2026-04-23 第一輪審計把 `index.html` 丟給 Explore agent 掃 "完成度",回報結論是「生產可用,零 stub」— 漏掉了一個真 bug:

> `ResultsUploadModal` 用 `atob(d.content)` decode 含中文的 `facts.jsonl`,>0x7F byte 被截斷,合併後寫壞線上檔。code review 才抓到(commit `c78b3f9`)。

Agent 掃「功能完成度」會看到所有 Modal 都在,不會展開字串處理細節。靜態單檔 SPA 的這些陷阱在 agent 摘要裡隱形:

**掃 `index.html` 時必須人工 grep 的陷阱清單**:

| 陷阱 | grep 指令 | 風險 |
|------|----------|------|
| `atob` / `btoa` **跟 UTF-8 資料** 同用 | `grep -n 'atob\|btoa' index.html`,每個非 helper 位置看上下文:是處理 binary 檔(✅)還是文字(⚠ 要走 `TextEncoder`) | 含中文的 markdown / jsonl base64 來回會壞字元 |
| `String.fromCharCode` 無 chunk | `grep -n 'String.fromCharCode' index.html`,大檔 spread 會爆 stack | 大 PDF / jsonl 上傳時 stack overflow |
| `localStorage` 讀無 try/catch | `grep -n 'localStorage.getItem\|localStorage.setItem' index.html` | 隱私瀏覽 / quota 超出時 throw |
| `JSON.parse(fetch)` 無 catch | `grep -n 'JSON.parse' index.html` | 後端錯誤回 HTML,SPA 整個白屏 |
| 硬編 API endpoint 路徑 | `grep -n "'/api/" index.html` | endpoint 改名時漏改 |

### C2. 靜態/衍生資料檔的 skew 檢查

每次 audit 要同時驗 **source → build → derived** 三份檔一致:

- `bucket_taxonomy.json`(source)→ `build_recipes_master.py`(code)→ `recipes_master.json`(derived)
- source / code 有任一改動,derived 可能是 **stale commit** 而不是正確結果
- 2026-04-23 發現 `recipes_master.json` 比 source 落後 5 個 commits,理由是 Actions workflow 只在 `data/ingest/uploads/**` push 時觸發,沒人上傳 techpack 時 derived 檔就永遠停在舊版
- **SOP**:audit 時本地跑一次 `python3 star_schema/scripts/build_recipes_master.py`,`git diff data/recipes_master.json` 應為空。有 diff = source 跟 derived 已 skew,要麼 commit 新產物,要麼查清楚為何不一致

### C3. CLI flag 宣稱 vs 實作

文件/workflow 宣稱某個 flag(如 `--strict`)有行為,**必須實際進程式碼確認**。2026-04-23 發現:

- workflow `.github/workflows/rebuild_master.yml:87` 傳 `--strict`
- README / 網站架構圖都寫「違規 exit 1 擋住 commit」
- 但 `build_recipes_master.py` 的 `main()` 完全沒 argparse,flag 被 Python 吞掉
- **gate 是假的** — 任何 schema 違規都靜默成功,直到 commit `7bda79f` 才修

**SOP**:audit 時對每個 workflow step 的命令列,grep 被呼叫 script 的 argparse,對比 README 描述。缺一邊就是文件債。
