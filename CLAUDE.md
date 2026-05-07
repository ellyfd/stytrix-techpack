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

> **2026-05-07 結構大調整**:把過去散在 root 的 14 份 .md / 2 份 .xlsx 集中,把 `data/`
> 拆 runtime/ingest/source/legacy 四層,scripts/ 拆 core/lib,徹底退役 `pom_analysis_v5.5.1/`,
> `General Model_Path2_Construction Suggestion/` 改名 `path2_universal/`。
> 詳細搬遷清單見 `git log --oneline pre-restructure-2026-05-07..HEAD`。

把每個資料夾當成放特定文件的櫃子,就像打版室分「上衣版」「下身版」「配件版」,不會亂放。

| 資料夾 | 放什麼(類比成衣流程) | 舉例 | 不要放什麼 |
|--------|----------------------|------|------------|
| `data/runtime/` | **線上系統 runtime 讀的成品 JSON**。前端 `fetch('./data/runtime/...')`、API `analyze.js` 啟動時讀 | `l1_standard_38.json`、`l2_visual_guide.json`、`l2_decision_trees.json`、`recipes_master.json`、`iso_dictionary.json`、`pom_dictionary.json`、`grading_patterns.json` | 原始 xlsx;靜態文件;ingest 中繼檔 |
| `data/source/` | **手維護 / 上傳的原始底稿**(被 `scripts/core/build_*` 讀來生 runtime JSON) | `五階層展開項目_YYYYMMDD.xlsx`(IE 五階層展開,9.5 MB)、`L2_代號中文對照表.xlsx` | runtime 讀的檔;說明文件 |
| `data/ingest/` | **Pipeline staging**(CI / 外部協作上傳處)。`build_recipes_master.py:629` 的 `data/ingest/*/facts.jsonl` glob 會掃 | `data/ingest/uploads/`、`data/ingest/{unified,vlm,pdf,metadata}/`、`data/ingest/{consensus_rules,ocr_v1,consensus_v1}/` | runtime 讀的成品(放 `data/runtime/`) |
| `data/legacy/` | **舊 `pom_analysis_v5.5.1/` 退役後留下的 fallback**(只給 `vlm_pipeline.py` / `extract_unified.py` 在 runtime 找不到時用) | `all_designs_gt_it_classification.json`、`pom_dictionary.json` | 任何新檔(此資料夾只縮不增) |
| `pom_rules/` | **自動產生的 POM 規則庫**。81 個 bucket(性別 × 部門 × GT 品類 × Fabric),像 81 本機器編的規格書 | `pom_rules/*.json`(由 `scripts/core/reclassify_and_rebuild.py` 產出) | 手寫規則;說明文件 |
| `l2_l3_ie/` | **38 個 L1 部位的 L2-L3-IE 工時規則**(聚陽 IE 資料)。每個部位自己的工段 sheet。從 `data/source/五階層展開項目_YYYYMMDD.xlsx` 用 `scripts/core/build_l2_l3_ie.py` 拆出來;聚陽送新版時用前端「🛠 IE 底稿管理」Modal 上傳到 `data/source/`,CI 自動重建 | 按 L1 代號分檔的 JSON | 其他層級的規則;手改(會被 CI 蓋掉) |
| `recipes/` | **PATH2 做工配方**(根目錄 72 檔)。是 `star_schema/scripts/build_recipes_master.py` 活檔的輸入,不是遺留 | `recipe_<GENDER>_<DEPT>_<GT>_<IT>.json`(72 檔)+ `_index.json` | 一次性實驗檔(放 Notion / Drive) |
| `path2_universal/` | **通用模型(不分客戶/品牌)的做工推薦資料源**。ISO 工藝代號查表、knit/woven 做工紀錄、PATH2 pipeline 文件。前身為 `General Model_Path2_Construction Suggestion/`(2026-05-07 改名) | `iso_lookup_factory_v4.3.json`、`iso_lookup_factory_v4.json`、`PATH2_通用模型_做工推薦Pipeline.md` | 前端 runtime fetch 的檔(那該放 `data/runtime/`) |
| `scripts/core/` | **資料產線腳本**(repo 內部執行的 build / rebuild / extract / search) | `build_l2_visual_guide.py`、`build_l2_l3_ie.py`、`run_extract_new.py`、`reclassify_and_rebuild.py`、`enforce_tier1.py` | 共用函式庫(放 `scripts/lib/`);一次性 ad-hoc 腳本 |
| `scripts/lib/` | **共用函式庫**(被 `scripts/core/` 的腳本 import,不是 entry point) | `extract_techpack.py`(PDF parser,被 `run_extract_new.py` / `run_extract_2025_seasonal.py` import) | 直接執行的腳本 |
| `star_schema/scripts/` | **CI 觸發的 ingest pipeline**(GitHub Actions `rebuild_master.yml` 直接呼叫) | `extract_raw_text.py`、`vlm_pipeline.py`、`extract_unified.py`、`build_recipes_master.py` | 內部產線腳本(放 `scripts/core/`) |
| `api/` | **線上系統後端 endpoint**(Vercel functions) | `analyze.js`(Claude Vision)、`push-pom-dict.js`、`ingest_token.js` | 靜態資料 |
| `docs/spec/` | **跨模組共用規格文件**(被 code 或 LLM prompt 引用) | `L1_部位定義_Sketch視覺指引.md`、`L2_VLM_Decision_Tree_Prompts_v2.md`、`L2_Visual_Differentiation_FullAnalysis_修正版.md`、`techpack-translation-style-guide.md`(api/analyze.js 啟動時 inject)、`pom_rules_v55_classification_logic.md`、`網站架構圖.md` | 純人類操作 SOP(放 `docs/sop/`);子系統內部文件 |
| `docs/sop/` | **純人類操作流程**(沒有 code 引用) | `pom_rules_pipeline_guide_v2.md` | 規格文件(放 `docs/spec/`) |
| repo 根目錄 `.md` | **入口三件套**(專案最頂層的 README / CLAUDE / PIPELINE 摘要) | `README.md`、`CLAUDE.md`、`PIPELINE.md` | 規格文件(放 `docs/spec/`);SOP(放 `docs/sop/`) |

### 新資料進來時,該放哪?

```
這份新檔是什麼?
│
├── 線上系統會直接讀取嗎?(前端 fetch / api/ 讀)
│       Yes → data/runtime/
│
├── 是手維護的原始底稿(xlsx / source PDF)?
│       Yes → data/source/
│
├── 是 pipeline 中繼檔 / 上傳區?
│       Yes → data/ingest/<subsystem>/
│
├── 是 POM 規則(bucket)?
│       Yes → pom_rules/(由 script 自動寫入,不要手動)
│
├── 是通用模型(Path 2)的 ISO / knit / woven 資料?
│       Yes → path2_universal/
│
├── 是 construction recipe / pattern(做工配方)?
│       ├── 由 PATH2 pipeline 產生  → recipes/（根目錄 72 檔,`build_recipes_master.py` 實際會吃)
│       └── 臨時上傳的一次性檔       → 不要進 repo,放 Notion / Drive
│
├── 是跨模組都要讀的規格文件?
│       Yes → docs/spec/
│
├── 是純人類操作 SOP(沒有 code 引用)?
│       Yes → docs/sop/
│
├── 是新的產線腳本?
│       ├── entry point          → scripts/core/
│       └── 共用函式庫(被 import)→ scripts/lib/
│
└── 判斷不出來?
        先在 PR 裡問,不要直接 merge。
```

> ⚠ **重要**:`recipes/`(根目錄 72 檔)是 `star_schema/scripts/build_recipes_master.py` 實際讀的路徑,
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

## 已知的下輪清理候選(2026-04-22 盤點 + 2026-05-07 重組後狀態)

下次跑 Part B SOP 時,可以考慮審這幾項:

| 候選 | 現況 | SOP 預期結果 |
|------|------|--------------|
| ~~`recipes/`~~ | 2026-04-23 確認是活檔:`star_schema/scripts/build_recipes_master.py` 每次 CI 都會掃 72 檔餵進 recipes_master.json | **不是候選** |
| `path2_universal/iso_lookup_factory_v4.json` vs `v4.3.json` | v4 仍作 fallback 被 `index.html`、`build_recipes_master.py` 引用,非孤兒;只是舊版 | 仍會過 gate = 不可丟,維持 fallback |
| `data/legacy/{all_designs_gt_it_classification,pom_dictionary}.json` | 2026-05-07 從 `pom_analysis_v5.5.1/data/` 搬過來,被 `vlm_pipeline.py` / `extract_unified.py` 當 fallback | 暫時 keep;下輪確認 runtime 副本是否完全取代後可清 |

**不會是清理候選的(避免誤判)**:

- ~~`L2_Confusion_Pairs_Matrix.md`~~ — 2026-04-23 已合併入 `docs/spec/L2_VLM_Decision_Tree_Prompts_v2.md` 末尾(§ 混淆對照表)
- ~~`L1_部位定義_Sketch視覺指引.md` 雙份~~ — 2026-05-07 已刪 PATH2 那份,只留 `docs/spec/L1_部位定義_Sketch視覺指引.md`
- ~~`scripts/` 裡路徑寫死 `/sessions/` 的腳本~~ — 2026-04-24 已改用 `--base-dir` / `$POM_PIPELINE_BASE`,可在外部環境跑(見 `scripts/core/_pipeline_base.py`)
- ~~`pom_analysis_v5.5.1/`~~ — 2026-05-07 已徹底退役:`extract_techpack.py` 抽到 `scripts/lib/`,其餘 5 個 MD5 相同 JSON、6 支 fork 後沒人 import 的舊版 .py、`run_extract.py` 孤兒、舊版 pipeline guide MD 全清
- `data/ingest/consensus_rules/facts.jsonl`(275 筆)、`data/ingest/ocr_v1/facts.jsonl`(1202 筆) — **一度被誤判為孤兒**,但 `build_recipes_master.py:629` 的 `data/ingest/*/facts.jsonl` glob 會吃它們,2026-04-24 實測刪除會讓 recipes_master 掉 249 entries(1414 → 1165)。**不可刪**

### 2026-05-07 重組:外部 BASE 與 repo 內部命名解耦

- `scripts/core/{rebuild_grading_3d,reclassify_and_rebuild,...}.py` 內仍有 `pom_analysis_v5.5.1/data/` 字串,但這是 **外部使用者 BASE 目錄結構**(`$BASE/pom_analysis_v5.5.1/data/`),**不是這個 repo 的資料夾**。重組時刻意保留以維持外部 BASE 用戶的相容性。下輪可考慮把 BASE 結構也一併重新命名(屬於外部契約變更,需另案通知)。

### 真實教訓 (2026-04-24)

原以為 `data/ingest/consensus_rules/` + `ocr_v1/` 沒人用(全文 grep 不到 literal 字串),code review agent 也回報「零引用」。**實際上** `build_recipes_master.py` 用 glob pattern `data/ingest/*/facts.jsonl` 讀,不需要 hardcode 目錄名,因此 grep 抓不到。

教訓(加到 Part B SOP 的 Step 5 後面):

- **Step 6 — 檢查 glob / wildcard 讀取**:看消費端有沒有用 `glob("*/...")`、`os.listdir()`、`Path.iterdir()` 這類動態掃描。candidate 目錄若位於 glob 的掃描範圍內,一定是活檔,grep literal 字串永遠抓不到。
- 實務上:對 `data/ingest/` 下任何新資料夾,都要先搜 `grep "ingest.*glob\|ingest.*iterdir\|ingest/\*"` 在 `*.py` / `*.js` 裡;不是 literal 比對。

### 真實教訓 (2026-05-07)

中度資料夾重組時碰到兩個容易踩雷的點,記錄下來給下次重組參考:

- **REPO_ROOT 深度**:把 `scripts/X.py` 搬到 `scripts/core/X.py` 後,所有 `Path(__file__).resolve().parent.parent` 計算的「repo root」都變成 `scripts/`(少一層)。grep `Path\(__file__\).*parent\.parent` 抓出所有需要改 `.parent.parent.parent` 的位置。
- **中文檔名 git mv**:含「五階層展開項目」、「部位定義」這類中文檔名,先 `git config core.quotepath false`,否則 `git status` 會顯示 `\xxx\xxx` 八進位編碼很難讀。macOS 還要設 `core.precomposeunicode true` 避免 NFD/NFC 不一致。
- **rename 配對誤判**:兩份 MD5 相同的檔案(`L1_部位定義_Sketch視覺指引.md` root + PATH2 兩份),git 的 rename detection 會把刪 + 加配對成 rename,可能把錯的那份標 D。功能性無影響(內容仍在),但 `git log --follow` history chain 會斷在被誤標的那一邊。可接受。
- **外部 BASE 路徑名 ≠ repo 路徑名**:`scripts/core/rebuild_grading_3d.py` 等腳本用 `BASE` 環境變數指向外部目錄,內部結構 `BASE/pom_analysis_v5.5.1/data/` 是外部使用者契約,不是這個 repo 的路徑。重組 repo 時這類字串故意保留,別誤改。

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

- `data/runtime/bucket_taxonomy.json`(source)→ `build_recipes_master.py`(code)→ `data/runtime/recipes_master.json`(derived)
- source / code 有任一改動,derived 可能是 **stale commit** 而不是正確結果
- 2026-04-23 發現 `recipes_master.json` 比 source 落後 5 個 commits,理由是 Actions workflow 只在 `data/ingest/uploads/**` push 時觸發,沒人上傳 techpack 時 derived 檔就永遠停在舊版
- **SOP**:audit 時本地跑一次 `python3 star_schema/scripts/build_recipes_master.py`,`git diff data/runtime/recipes_master.json` 應為空(或只有 timestamp 行)。有實質 diff = source 跟 derived 已 skew,要麼 commit 新產物,要麼查清楚為何不一致

### C3. CLI flag 宣稱 vs 實作

文件/workflow 宣稱某個 flag(如 `--strict`)有行為,**必須實際進程式碼確認**。2026-04-23 發現:

- workflow `.github/workflows/rebuild_master.yml:87` 傳 `--strict`
- README / 網站架構圖都寫「違規 exit 1 擋住 commit」
- 但 `build_recipes_master.py` 的 `main()` 完全沒 argparse,flag 被 Python 吞掉
- **gate 是假的** — 任何 schema 違規都靜默成功,直到 commit `7bda79f` 才修

**SOP**:audit 時對每個 workflow step 的命令列,grep 被呼叫 script 的 argparse,對比 README 描述。缺一邊就是文件債。

### C4. 重組後路徑驗證(2026-05-07 加入)

每次大規模 mv 後,跑下列 grep 確認沒有殘留舊路徑:

```bash
# 應為 0 行(忽略 .git 與衍生 derived JSON)
grep -rn "General Model_Path2" --include='*.py' --include='*.js' --include='*.html' --include='*.yml' .
grep -rn "pom_analysis_v5\.5\.1" --include='*.py' --include='*.js' --include='*.html' . | grep -v 'rebuild_grading_3d\|reclassify_and_rebuild\|index\.html.*\$BASE'
grep -rnE "['\"\`]data/(l1_standard_38|l2_visual_guide|l2_decision_trees|recipes_master|construction_bridge_v6|iso_dictionary|pom_dictionary|grading_patterns|bucket_taxonomy|design_classification_v5|client_rules|gender_gt_pom_rules|bodytype_variance|l1_iso_recommendations_v1|l1_part_presence_v1)\.json" --include='*.py' --include='*.js' --include='*.html' . | grep -v 'data/runtime\|data/legacy\|data/source\|data/ingest'

# 也跑這 4 個冒煙 build,看 git diff 是否只剩 timestamp:
python3 scripts/core/build_l2_visual_guide.py
python3 scripts/core/build_l2_decision_trees.py
python3 scripts/core/build_l2_l3_ie.py --dry-run
python3 star_schema/scripts/build_recipes_master.py
```

衍生 JSON(`data/runtime/recipes_master.json` 等)裡的 `source_versions` 字串會殘留舊路徑,但 CI 下次跑會自動更新,**不算未修**。
