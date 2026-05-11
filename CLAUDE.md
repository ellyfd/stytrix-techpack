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

> **2026-05-11 快照**(在 2026-05-09 之上加 m7_pullon 21-brand + Bible idempotency 修):
>
> 1. **m7_pullon 跨 21 brand**(原 10 → +11 新 brand:HLF / WMT / QCE / HLA / NET / JF / BR / SAN / DST / ZAR / ASICS)。source 端聚陽 push 進 4,562 件 EIDH;Bible(`l2_l3_ie/*.json`) actuals.by_brand 跟著刷到 21 brand,大小 73.7 → 79.1 MB(+7%)。
>
> 2. **`derive_bible_actuals.py` idempotency 修**(原 `derive_view_l2_l3_ie.py`,2026-05-11 改名;見 #5):2026-05-08 第一次升 Phase 2 dict schema 後,script 對已是 dict 的 step 直接 pass-through,不重算 actuals → 新 brand 進 m7_pullon 後 Bible 不會跟著刷,即使 `--all --in-place` 也 0 diff。修法:dict step 也走完整 lookup → recompute → 寫入(actuals empty 時清掉,避免殘留)。
>
> 3. **`data/runtime/brands.json` 新檔 + Step 4c**:`scripts/core/build_brands.py` 從 `entries.jsonl` client_distribution 聚合各 brand 的 n_entries / n_designs,排序 n_designs DESC 寫進 `data/runtime/brands.json`(~1.8 KB)。CI `rebuild_master.yml` Step 4c 在 Step 4b 之後跑,brands.json 跟著 m7_pullon push 自動更新。
>
> 4. **前端 Brand 下拉改動態**(`index.html`):拔掉硬寫 10 entry 的 `const BRANDS = [...]`,改 boot 時 eager fetch `./data/runtime/brands.json`。新 brand 進 m7_pullon → CI 重產 brands.json → 用戶 reload 就看到,不用手 patch 前端常數。
>
> 5. **Bible 兩支腳本 + workflow 改名**(避免跟 `l2_l3_ie/` 目錄撞名):
>    - `scripts/core/build_l2_l3_ie.py` → `scripts/core/build_bible_skeleton.py`(從 xlsx 建骨架,brand-agnostic,本機 SOP)
>    - `star_schema/scripts/derive_view_l2_l3_ie.py` → `star_schema/scripts/derive_bible_actuals.py`(掛 m7_pullon 觀察值,CI Step 4b)
>    - `.github/workflows/build_l2_l3_ie.yml` → `.github/workflows/build_bible_skeleton.yml`
>    - 目錄 `l2_l3_ie/` 保留(L2/L3/IE 三層工時名有資訊量,改成 bible/ 是內部黑話)
>
> 6. **前端 `filterBibleByCategory` 6 維 filter + canonical alias 擴張**(commit `83727c0`):
>    - **filterBibleByCategory(bible, {brand, fabric, gender, dept, gt, it})**(`index.html:216`)— 在 `filterBibleByBrand`(只 brand)之上加 5 維:runtime 反查 `data/ingest/m7_pullon/designs.jsonl.gz`(6.4 MB gzipped lazy fetch + native `DecompressionStream('gzip')`,4,562 designs cache module-scope),篩中後在 `(L2|L3|L4|L5)` key 上重算 `sec_median` + design count,把 Bible actuals 換成「符合 filter 的 designs 在這個 step 觀察到的中位數」。任何 filter 可省略;全空 fallback `filterBibleByBrand` 或整體。失敗時 fallback brand-only。**消費端**:`index.html:5645` 取代舊 `filterBibleByBrand`-only 呼叫。
>    - **canonical_aliases.json 擴張到 23 brand 代碼 / 28 alias entries**:加進 16 個新 client / 微調 2 個(`DICKS SPORTING GOODS → DKS`(原 `DICKS`)、`GAP OUTLET → GAP`(原 `GO`))。新加 BY / HLF / WMT / QCE / HLA / JF / SAN / DST / ZAR / ASICS / NET / LEV / CATO / SMC,對齊 m7_pullon 21 brand + 平台預備擴張。`data/runtime/brands.json` 21 brand 為實際在 entries.jsonl 出現過的(其他 alias 是預備)。

> **2026-05-09 快照**(consolidated 從 2026-05-07 重組 + 2026-05-08 ~ 09 各 PR):
>
> 1. **Phase 2 derive views(View A + B 接線)** — View A (`derive_view_recipes_master.py`,Step 4a 剝 `_m7_*` 內部欄)/ View B (`derive_bible_actuals.py --all --in-place`,Step 4b 升級 `l2_l3_ie/<L1>.json` 38 檔為 dict schema + 掛 m7_pullon `actuals`)。**View C designs_index per-EIDH 在 2026-05-09 retired** — 確認前端無 UI 消費,刪 derive script + workflow Step 4c + 3,900 個 dead 產物。spec 見 `docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md`。
>
> 2. **Bible 升級 20260507**:`data/source/五階層展開項目_20260507.xlsx` 35.7 MB(2.3x prior),sheet schema 改成「語系資料 + 全部五階層」雙 sheet,新增 `機種 / 尺寸 / 圖片名字 / *_Sort` 欄。**xlsx 不再進 repo**(>25 MB GitHub web 上限),改寫 SOP `data/source/BIBLE_UPGRADE.md`。維護者本機跑 `scripts/core/build_bible_skeleton.py` build raw,Step 4b 升 dict + 掛 actuals。
>
> 3. **m7_pullon 第 7 個 source**:`data/ingest/m7_pullon/{entries.jsonl(746 行,聚合,餵 cascade), designs.jsonl.gz(3,900 件 EIDH 含 5-level 工段 + canonical block,餵 View B/C derive)}`。`build_recipes_master.py` 加 `build_from_m7_pullon()`。
>
> 4. **canonical block + alias normalizer**(designs.jsonl.gz 每筆 design):8 canonical 欄位(客戶/報價款號/Program/Subgroup/W/K/Item/Season/PRODUCT_CATEGORY)各做 multi-source consensus(M7 列管 priority 3 / PDF priority 2 / 推論 priority 1),M7 兜底所以 `canonical.<field>.value` 永遠 100% 不掉拍;`confidence` "high"/"medium"/"low" 標 audit 強度;`sources` 留 audit trail。Alias 規則放 `data/source/canonical_aliases.json` 手維護。**Consumer**:`build_recipes_master.py` 讀 aggregated `entries.jsonl`;Phase 2 View B + C 直接吃 `designs.jsonl.gz` 含 canonical block。
>
> 5. **bucket_taxonomy 統一到 `data/runtime/`**(PR #312):過去兩份(root + runtime)並存,合併成一份含 **28 v4 4-dim**(`<GENDER>_<DEPT>_<GT>_<IT>` UPPERCASE,scalar 值)+ **59 legacy 3-dim**(`<GENDER>_<DEPT>_<GT>` UPPERCASE,list 值,兜底 pre-v4 facts/consensus)+ `legacy_note`。`build_recipes_master.py:72` `BUCKET_TAX_PATH` 指 `data/runtime/`(不再讀 root)。schema 細節見 `MK_METADATA.md`。
>
> 6. **CI Pre-Step 3 schema gate**(PR #313):`scripts/core/validate_buckets.py` 已重寫支援 v4 + legacy 兩段檢查(原 v3 期望 lowercase 但 v4 是 UPPERCASE),接進 `rebuild_master.yml` 跑在 Step 3 build 前 < 1s 早期 catch drift。失敗模式涵蓋:UPPERCASE 違反 / 必填欄空 / 案例衝突 / 3-dim/4-dim prefix collision warn。

> **2026-05-07 結構大調整**:把過去散在 root 的 14 份 .md / 2 份 .xlsx 集中,把 `data/`
> 拆 runtime/ingest/source/legacy 四層,scripts/ 拆 core/lib,徹底退役 `pom_analysis_v5.5.1/`,
> `General Model_Path2_Construction Suggestion/` 改名 `path2_universal/`。
> 詳細搬遷清單見 `git log --oneline pre-restructure-2026-05-07..HEAD`。

> **Metadata schema canonical doc**:每個資料 source(Bible / m7_pullon / ISO dictionary 等)的欄位語意、來源、provenance 走 [`MK_METADATA.md`](./MK_METADATA.md)(2026-05-08 v1.0)為準。本文件 Part A 只記「資料夾分工」,不記欄位細節,避免兩處 schema 描述 diverge。

把每個資料夾當成放特定文件的櫃子,就像打版室分「上衣版」「下身版」「配件版」,不會亂放。

| 資料夾 | 放什麼(類比成衣流程) | 舉例 | 不要放什麼 |
|--------|----------------------|------|------------|
| `data/runtime/` | **線上系統 runtime 讀的成品 JSON**(17 個 .json)。前端 `fetch('./data/runtime/...')`、API `analyze.js` 啟動時讀 | `l1_standard_38.json`、`l2_visual_guide.json`、`l2_decision_trees.json`、`recipes_master.json`、`iso_dictionary.json`、`pom_dictionary.json`、`grading_patterns.json`、`bucket_taxonomy.json`(28 v4 + 59 legacy)、`construction_bridge_v6.json`、`brands.json`(2026-05-11 加,前端 Brand 下拉動態 source) | 原始 xlsx;靜態文件;ingest 中繼檔;**`designs_index/`** 已退役(2026-05-09) |
| `data/source/` | **手維護 / 上傳的原始底稿**(被 `scripts/core/build_*` 讀來生 runtime JSON) | `L2_代號中文對照表.xlsx`(L1/L2 代號對照,14 KB)、`BIBLE_UPGRADE.md`(SOP)、`M7_PULLON_DATA_SCHEMA.md`(m7_pullon source schema)、**`canonical_aliases.json`**(2026-05-08 加,8 canonical 欄位的 alias normalize 規則,M7_Pipeline `consolidate_canonical.py` 讀;repo 暫存當 source-of-truth 規則表) | runtime 讀的檔;說明文件;**`五階層展開項目_*.xlsx` 不再進 repo**(2026-05-08 起,xlsx 留聚陽端,38 個 derive JSONs 進 repo) |
| `data/ingest/` | **Pipeline staging**(CI / 外部協作上傳處)。`build_recipes_master.py` 的 `data/ingest/*/facts.jsonl` glob 會掃 | `data/ingest/uploads/`(PDF/PPTX 上傳處)、`data/ingest/{unified,vlm,pdf,metadata}/`、`data/ingest/{consensus_rules,ocr_v1,consensus_v1}/`、**`data/ingest/m7_pullon/`(2026-05-08 加,聚陽端 PullOn pipeline 推進來)** | runtime 讀的成品(放 `data/runtime/`) |
| `data/legacy/` | **舊 `pom_analysis_v5.5.1/` 退役後留下的 fallback**(只給 `vlm_pipeline.py` / `extract_unified.py` 在 runtime 找不到時用) | `all_designs_gt_it_classification.json`、`pom_dictionary.json` | 任何新檔(此資料夾只縮不增) |
| `pom_rules/` | **自動產生的 POM 規則庫**。81 個 bucket(性別 × 部門 × GT 品類 × Fabric),像 81 本機器編的規格書 | `pom_rules/*.json`(由 `scripts/core/reclassify_and_rebuild.py` 產出) | 手寫規則;說明文件 |
| `l2_l3_ie/` | **Bible 五階層展開** — 38 個 L1 部位,每部位 L1→L2→L3→L4→L5 工段樹。**Phase 2 dict schema(2026-05-08 commit f9faa8b 升級完成)**:每個 L5 step 是 dict `{l5, ie_standard:{sec,grade,primary,machine}, actuals?}`,`actuals` 含 m7_pullon 觀察值(`n_designs / sec_median / by_brand / machine_top`,option B trim 後)。`_metadata.schema = "phase2"` 標記。Bible **結構** 由 IE xlsx 決定(brand-agnostic),**L1-L5 樹不被 per-design 改**;Bible 38 檔現是 CI 自動產 — `derive_bible_actuals.py --all --in-place` 在 `rebuild_master.yml` Step 4b 跑,讀 xlsx-derived raw + `data/ingest/m7_pullon/designs.jsonl.gz` 後寫回。**`new_part_*` / `new_shape_design_*` / `new_method_describe_*` / `(NEW)*` placeholder 在 derive 層全 drop 不進 Bible**(IE 治理任務,聚陽端 SSRS 處理) | 按 L1 代號分檔的 JSON,38 檔 + `_index.json` | 其他層級的規則;**手改(CI 會蓋掉)**;brand 欄位嵌進樹結構(brand 走 actuals.by_brand);`new_*` placeholder |
| `l2_l3_ie_by_client/` | ~~RETIRED 2026-05-08(Phase 2.5b)~~ — git rm 完成,功能由 `l2_l3_ie/<L1>.json` 升級後 schema 的 `actuals.by_brand` + frontend 的 `filterBibleByBrand()` / `filterBibleByCategory()` helper(2026-05-11 加 6 維,runtime 反查 designs.jsonl.gz)取代 | — | — |
| `recipes/` | **PATH2 做工配方**(根目錄 72 檔)。是 `star_schema/scripts/build_recipes_master.py` 活檔的輸入,不是遺留 | `recipe_<GENDER>_<DEPT>_<GT>_<IT>.json`(72 檔)+ `_index.json` | 一次性實驗檔(放 Notion / Drive) |
| `path2_universal/` | **通用模型(不分客戶/品牌)的做工推薦資料源**。ISO 工藝代號查表、knit/woven 做工紀錄、PATH2 pipeline 文件。前身為 `General Model_Path2_Construction Suggestion/`(2026-05-07 改名) | `iso_lookup_factory_v4.3.json`、`iso_lookup_factory_v4.json`、`PATH2_通用模型_做工推薦Pipeline.md` | 前端 runtime fetch 的檔(那該放 `data/runtime/`) |
| `scripts/core/` | **資料產線腳本**(repo 內部執行的 build / rebuild / extract / search) | `build_l2_visual_guide.py`、`build_bible_skeleton.py`、`build_brands.py`(2026-05-11 加,從 m7_pullon entries.jsonl 聚合產 runtime/brands.json)、`run_extract_new.py`、`reclassify_and_rebuild.py`、`enforce_tier1.py` | 共用函式庫(放 `scripts/lib/`);一次性 ad-hoc 腳本 |
| `scripts/lib/` | **共用函式庫**(被 `scripts/core/` 的腳本 import,不是 entry point) | `extract_techpack.py`(PDF parser,被 `run_extract_new.py` / `run_extract_2025_seasonal.py` import) | 直接執行的腳本 |
| `star_schema/scripts/` | **CI 觸發的 ingest pipeline**(GitHub Actions `rebuild_master.yml` 直接呼叫,**6 支** + 1 支 derive 在 `scripts/core/`) | Step 1 `extract_raw_text.py`、Step 2b `vlm_pipeline.py`、Step 2a `extract_unified.py`、Step 3 `build_recipes_master.py`、Step 4a `derive_view_recipes_master.py`、Step 4b `derive_bible_actuals.py`、Step 4c `scripts/core/build_brands.py`(2026-05-11 加;原 designs_index per-EIDH derive 在 2026-05-09 retired)| 內部產線腳本(放 `scripts/core/`) |
| `api/` | **線上系統後端 endpoint**(Vercel functions) | `analyze.js`(Claude Vision)、`push-pom-dict.js`、`ingest_token.js` | 靜態資料 |
| `docs/spec/` | **跨模組共用規格文件**(被 code 或 LLM prompt 引用) | `L1_部位定義_Sketch視覺指引.md`、`L2_VLM_Decision_Tree_Prompts_v2.md`、`L2_Visual_Differentiation_FullAnalysis_修正版.md`、`techpack-translation-style-guide.md`(api/analyze.js 啟動時 inject)、`pom_rules_v55_classification_logic.md`、`網站架構圖.md` | 純人類操作 SOP(放 `docs/sop/`);子系統內部文件 |
| `docs/sop/` | **純人類操作流程**(沒有 code 引用) | `pom_rules_pipeline_guide_v2.md` | 規格文件(放 `docs/spec/`) |
| repo 根目錄 `.md` | **入口兩件套**(專案最頂層的 README / CLAUDE) | `README.md`、`CLAUDE.md` | 規格文件(放 `docs/spec/`);SOP(放 `docs/sop/`) |

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
- ~~`l2_l3_ie_by_client/` 27 檔~~ — **2026-05-08 已退役(Phase 2.5b)**:同日早上 gate 攔下後,Phase 2.1-2.5 一連串 PR 把退役三前提都完成:① `l2_l3_ie/` 38 檔升級成 Phase 2 dict schema(commit f9faa8b);② frontend `filterBibleByBrand()` helper 直接從 actuals.by_brand 過濾(取代 derive_view_by_client.py 的計畫);③ `index.html:5426` 的 fetch 已拔掉。`build_recipes_master.py` 的 `_m7_by_client` 欄位也順便清掉
- `data/ingest/pdf/callout_manifest.jsonl`(0 bytes 空檔) — **2026-05-08 gate 攔下**:`star_schema/scripts/extract_raw_text.py:572` 是 append 寫入目標,workflow `rebuild_master.yml:54` 也引用,是 active output target 只是還沒資料。**不可刪**
- `scripts/core/{search_recipes,build_recipe_embeddings,eval_recipe_retrieval}.py` 三隻 — **2026-05-08 gate 攔下**:雖然不在 CI / workflow 內被呼叫,但 `data/ingest/recipe_index/index.json` 是 623 KB 真實 build 產物,代表是有人 build 過的離線評估工具。屬於手動 CLI(類似 eval 性質),**不是 dead code**

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

### 真實教訓 (2026-05-08)

第二輪 codebase audit(掃 dup / dead code / stale doc)時,gate 又攔下三個誤判,記下來避免下次重蹈:

- **「DEPRECATED 標籤 ≠ 可刪」**:`l2_l3_ie_by_client/` 在 Part A 表上標 DEPRECATED,但 `index.html:5426` 仍 fetch、`build_recipes_master.py:693` 仍寫 `_m7_by_client`。退役只是「不要新增」,要 git rm 必須先把所有讀寫端切走。檢查 candidate 標 DEPRECATED 時務必 grep 線上前端 + 所有 producer 端,不可只看 Part A 文字。
- **「空檔 ≠ 死檔」**:`data/ingest/pdf/callout_manifest.jsonl` 是 0 bytes,看似 placeholder,實際是 `extract_raw_text.py:572` 的 append target。空檔可能是「pipeline 還沒跑出資料」,不是「沒人要寫」。檢查空檔要 grep producer 端,不只看消費端。
- **「不在 CI 內 ≠ dead code」**:`scripts/core/search_recipes.py` / `build_recipe_embeddings.py` / `eval_recipe_retrieval.py` 三隻沒在 workflow 內被呼叫,但 `data/ingest/recipe_index/index.json`(623 KB)是它們 build 出來的真實產物,代表有人手動跑過。離線評估 / 研究工具不會進 CI,但仍是活工具。
- **「文件宣稱 ≠ 實況」**:CLAUDE.md L43 寫 Phase 2 schema 升級已完成,實測 `l2_l3_ie/AE.json` 仍是 5-elem list 的 Phase 1 格式。**文件描述要跟著事實改,不能寫成「目標狀態」當「現況」**(已修正,Part A 改回「Phase 1 list,Phase 2 規劃中」)。

教訓加進 Part B SOP:Step 6 (glob check) 之後加 **Step 7 — frontend fetch + producer write check**,grep `fetch.*<candidate>`、`open.*<candidate>.*'a'`、`append`、`>>` 對候選的引用。

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
python3 scripts/core/build_bible_skeleton.py --dry-run
python3 star_schema/scripts/build_recipes_master.py
```

衍生 JSON(`data/runtime/recipes_master.json` 等)裡的 `source_versions` 字串會殘留舊路徑,但 CI 下次跑會自動更新,**不算未修**。
