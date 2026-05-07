# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

> 想直接看全貌 Mermaid 圖（4 張：高階流程 / 前端模式分流 / 資料依賴 / Ingest Pipeline）+ 資料夾對照表 + 架構債清單 + 權威手冊登記表：[`docs/spec/網站架構圖.md`](./docs/spec/網站架構圖.md)
>
> **2026-05-07 重組**:資料夾大整理(`data/` 拆 runtime/ingest/source/legacy、`scripts/` 拆 core/lib、根目錄 .md 集中到 `docs/`、`General Model_Path2_Construction Suggestion/` → `path2_universal/`、`pom_analysis_v5.5.1/` 退役)。所有 GitHub 連結到舊路徑會 404,請用新路徑。

## 兩種模式

Header 右上提供「**聚陽模型** / **通用模型**」切換（選擇會記在 `localStorage.stytrix.appMode`）。

| 模式 | 作工建議 | 尺寸 | 全碼 |
|------|----------|------|------|
| **聚陽模型** (`makalot`) | 五階層：L1 部位 → L2 零件 → L3 形狀 → L4 工法 → L5 工段 + IE 秒數 | POM tier（必備 / 建議 / 選配），依 `pom_rules/<bucket>.json` | ✓ 各 size 中位數 + 公差 + 跳碼 |
| **通用模型** (`universal`) | Path 2：VLM 只判 L1，雙表查 ISO：先 `path2_universal/iso_lookup_factory_v4.3.json`(Dept × **Gender** × GT × L1，fine GT 對齊 UI 下拉選單，230 entries)再退 `path2_universal/iso_lookup_factory_v4.json`(Fabric × Dept × GT × L1_code，282 entries，提供 iso_zh/機種)；另吃 `data/runtime/recipes_master.json` 顯示 recipe 推薦 | 僅 5 項基礎大尺寸（上衣：肩/胸/下擺/袖長/身長；下身：腰/臀/前後檔/內長/褲口） | — |

通用模型後端 (`api/analyze.js`) 接 `mode=universal` 時**只跑 Pass 1（L1 偵測）**，省掉 Pass 2 的 decision-tree token。

## 架構

純靜態 HTML + Vercel Node.js Functions，無 bundler、無 `package.json`。

```
index.html                                    ← 整個 app（React via CDN + 內聯 JS/CSS）
LOGO.png                                      ← Header logo 圖檔
api/
  ├─ analyze.js                               ← Claude Vision（claude-sonnet-4-6）：Pass 1 (L1) + Pass 2 (L2 decision tree)
  │                                             mode=universal 時只跑 Pass 1；module init 讀 data/runtime/{l2_visual_guide,l2_decision_trees,l1_standard_38}.json
  │                                             + docs/spec/techpack-translation-style-guide.md
  ├─ push-pom-dict.js                         ← Admin：POM 翻譯表寫回 data/runtime/pom_dictionary.json
  └─ ingest_token.js                          ← Admin：發 GITHUB_PAT 讓瀏覽器直連 GitHub（繞 4.5MB body 上限）
.github/workflows/
  ├─ rebuild_master.yml                       ← push 到 data/ingest/uploads/** 時觸發；自動重建 recipes_master 並 push 回 main
  └─ build_l2_l3_ie.yml                       ← push 到 五階層展開項目_*.xlsx 時觸發；自動重建 l2_l3_ie/*.json
vercel.json                                   ← functions config：includeFiles 把 data/** + docs/spec/techpack-translation-style-guide.md 編進 analyze.js bundle
docs/
  ├─ spec/                                    ← 跨模組共用規格(被 code / LLM prompt 引用)
  │   ├─ L1_部位定義_Sketch視覺指引.md         ← VLM Pass 1 system prompt 資料來源
  │   ├─ L2_VLM_Decision_Tree_Prompts_v2.md   ← Pass 2 decision tree 原始資料
  │   ├─ L2_Visual_Differentiation_FullAnalysis_修正版.md ← 282 個 L2 視覺特徵
  │   ├─ techpack-translation-style-guide.md  ← runtime 規格:ISO 術語 + POM 翻譯;analyze.js 啟動時 inject
  │   ├─ pom_rules_v55_classification_logic.md ← v5.5.1 分類邏輯完整文件
  │   └─ 網站架構圖.md                         ← 本 repo 架構全貌(Mermaid)
  └─ sop/                                     ← 純人類操作流程
      └─ pom_rules_pipeline_guide_v2.md       ← scripts/core/ 產線完整操作手冊(五階段)
data/
  ├─ runtime/                                 ← 線上系統 runtime 讀的成品 JSON
  │   ├─ l2_visual_guide.json                 ← 聚陽模型 Pass 1/2 視覺指引(由 analyze.js 靠 includeFiles 編進 bundle)
  │   ├─ l2_decision_trees.json               ← 聚陽模型 Pass 2 decision tree(同上)
  │   ├─ l1_standard_38.json                  ← 38 個 L1 部位標準表(上游由 ingest pipeline 或線下腳本重建)
  │   ├─ grading_patterns.json                ← 跳碼 pattern(基碼頁)
  │   ├─ bodytype_variance.json               ← Body Type 差異
  │   ├─ pom_dictionary.json                  ← POM 代號 → 中英文對照(admin 可編)
  │   ├─ recipes_master.json                  ← 通用模型 recipe 推薦(GitHub Actions 自動重建)
  │   ├─ iso_dictionary.json                  ← ISO 字典(同上,自動重建)
  │   ├─ construction_bridge_v6.json          ← 跨設計 GT × zone 施工統計(build_recipes_master 會吃)
  │   ├─ gender_gt_pom_rules.json             ← Gender × GT 的 POM 規則(規則產線輸出,1.5 MB)
  │   ├─ all_designs_gt_it_classification.json ← 全量 design 的 GT / IT 分類(1292 designs)
  │   ├─ bucket_taxonomy.json                 ← 59 個 bucket 分類表(Step 3 --strict 驗證用)
  │   ├─ client_rules.json / design_classification_v5.json / ...
  │   ├─ l1_part_presence_v1.json             ← 聚陽模型:GT×IT 下每個部位出現率(345 KB)
  │   └─ l1_iso_recommendations_v1.json       ← 聚陽模型:部位名 → ISO 建議(519 KB)
  ├─ source/                                  ← 手維護 / 上傳的原始底稿
  │   ├─ 五階層展開項目_YYYYMMDD.xlsx         ← IE 五階層展開(9.5 MB,build_l2_l3_ie 拆成 38 份)
  │   └─ L2_代號中文對照表.xlsx               ← L1/L2 代號對照(283 L2,build_l2_visual_guide 讀)
  ├─ legacy/                                  ← 退役的 pom_analysis_v5.5.1 留下的 fallback
  │   ├─ all_designs_gt_it_classification.json ← vlm_pipeline / extract_unified fallback
  │   └─ pom_dictionary.json                  ← snapshot 期版本(只給 fallback 用)
  └─ ingest/                                  ← PDF/PPTX 上傳後的 staging 區,Actions workflow 讀寫
      ├─ uploads/                             ←   使用者上傳的原始 PDF/PPTX（處理完由 workflow 刪）
      ├─ metadata/designs.jsonl               ←   D-number 去重表（Step 1 append）
      ├─ pptx/<slug>.txt                      ←   PPTX 文字（Step 1）
      ├─ pdf/callout_images/<DID>_p<N>.png    ←   PDF callout 影像（Step 1，216 DPI，處理完不保留）
      ├─ pdf/callout_manifest.jsonl           ←   PDF callout 影像索引
      ├─ unified/{dim,facts}.jsonl            ←   Step 2a 全量合併 4 來源的 facts
      ├─ vlm/{facts.jsonl,vlm_callout_extracts.json}
      │                                       ←   Step 2b 輸出（**vlm/**，不是 vlm_v1）
      ├─ consensus_v1/entries.jsonl           ←   手動 bucket consensus 規則（275 條，build_recipes_master 吃）
      ├─ construction_by_bucket/              ←   外部資料源（688 設計，Step 2a 讀）
      ├─ consensus_rules/                     ← 275 筆 `source=consensus_rules_final`，build_recipes_master 透過 `*/facts.jsonl` glob 讀；大多跟 consensus_v1 重疊被 dedup，但仍貢獻少數 entries
      └─ ocr_v1/                              ← 1202 筆 OCR 輸出，同樣靠 glob 被讀到；貢獻 ~249 個 entries（2026-04-24 實測）
l2_l3_ie/*.json                               ← 聚陽模型:38 個 L1 部位的 L2-L3-IE 規則(39 檔 = 38 L1 + 1 index)
pom_rules/*.json                              ← POM 規則(81 bucket + _index.json = 82 檔,由 scripts/core/reclassify_and_rebuild.py 產出)
recipes/*.json                                ← PATH2 做工配方(72 檔,被 star_schema/scripts/build_recipes_master.py 吃)
path2_universal/                              ← 通用模型(不分客戶/品牌)的做工推薦資料源(原 General Model_Path2_Construction Suggestion/,2026-05-07 改名)
  ├─ iso_lookup_factory_v4.3.json             ← **primary** 查表:Dept × Gender × GT × L1(230 entries)
  ├─ iso_lookup_factory_v4.json               ← v4 fallback 查表:Fabric × Dept × GT × L1_code(282 entries,提供 iso_zh / 機種)
  ├─ PATH2_通用模型_做工推薦Pipeline.md       ← 通用模型 pipeline 總說明
  ├─ PATH2_Phase2_Upload_Pipeline.md          ← Phase 2 上傳 pipeline 實作說明
  └─ README.md                                ← 資料夾本身的 v4.3 說明
scripts/
  ├─ core/                                    ← 線下產線腳本(17 支 entry-point;BASE 目錄用 --base-dir 或 $POM_PIPELINE_BASE 指定)
  └─ lib/
      └─ extract_techpack.py                  ← PDF parser 函式庫,被 scripts/core/run_extract_*.py import
star_schema/scripts/                          ← **線上 ingest pipeline**(由 .github/workflows/rebuild_master.yml 呼叫)
  ├─ extract_raw_text.py                      ← Step 1:掃 uploads/,抽 PPTX 文字 + PDF callout 圖;支援 --allow-empty / --force
  ├─ extract_unified.py                       ← Step 2a:合併 4 來源 → data/ingest/unified/{dim,facts}.jsonl
  ├─ vlm_pipeline.py                          ← Step 2b:讀 vlm_raw_extracts.json → ISO 對映 → data/ingest/vlm/facts.jsonl(continue-on-error)
  └─ build_recipes_master.py                  ← Step 3 (--strict):5 來源合併 → data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json
requirements-pipeline.txt                     ← GitHub Actions 用的 Python 依賴(pymupdf + python-pptx)
README.md / CLAUDE.md / PIPELINE.md           ← 入口三件套(只剩這三份在 root)
```

### ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 使用狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender；含 iso_zh / machine / pptx_2025_votes | **fallback** |
| v4.3 | Department × Gender × GT × L1 | 230 | **fine GT 對齊 App UI**（PANTS/LEGGINGS/SHORTS 保留細分）；5 種來源合併；1,328 designs | **primary** |

前端 `isoOptionsFor(v43, v4, filters, l1Code)` 先試 v4.3（性別 + 細 GT），查無對應則退 v4；v4 的 iso_zh/machine 表順便用在 v4.3 的 ISO 顯示。

v4.3 GT 已經對齊 UI，不再需要 `BOTTOM` 粗桶，alias 縮到只剩 `BODYSUIT → TOP` 和 `SWIM_PIECE → TOP` 兩個 UI 有但 v4.3 沒 bucket 的例外（`V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS`）。歷史版本（v3 / v4.1 / v4.2 / full_analysis / knit_pptx_* / woven_*）已陸續移除。

## 兩組獨立的資料 pipeline

| | 線下規則產線 (`scripts/core/`) | 線上 ingest pipeline (`star_schema/scripts/`) |
|---|---|---|
| **Trigger** | 手動執行 | GitHub Actions：push 到 `data/ingest/uploads/**` |
| **執行環境** | 本機或 CI 皆可；BASE 目錄用 `--base-dir` CLI 或 `$POM_PIPELINE_BASE` env var 指定（見 `scripts/core/_pipeline_base.py`） | `ubuntu-latest` runner，依 `requirements-pipeline.txt` 裝 Python 依賴 |
| **主要輸出** | `pom_rules/*.json`（81 bucket）、`l2_l3_ie/*.json`、`data/runtime/{l2_visual_guide,l2_decision_trees,l1_*}.json` 等 | `data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json`、`data/ingest/**` |
| **操作文件** | `docs/sop/pom_rules_pipeline_guide_v2.md` | `path2_universal/PATH2_Phase2_Upload_Pipeline.md` |

兩者**彼此不共用程式碼**，動其中一邊不會自動影響另一邊。

### 線下產線（`scripts/`）主要腳本

| 腳本 | 做什麼 | 產出 |
|---|---|---|
| `reclassify_and_rebuild.py` | v6.0 全量重分類（Gender/Dept/GT/Fabric）+ rebuild POM 規則 | `pom_rules/*.json` 81 bucket + `_index.json` + `pom_names.json` |
| `rebuild_profiles.py` | 重建 profile union，reclassify 的上游 | profile union（內部路徑） |
| `enforce_tier1.py` | 產線後強制 tier-1 rule（必備 POM 下限） | 覆蓋 `pom_rules/*.json` |
| `fix_sort_order.py` | 修 bucket 內 `pom_sort_order` 欄位排序 | 覆蓋 `pom_rules/*.json` |
| `run_extract_2025_seasonal.py` / `run_extract_new.py` | 從 2025 / 2026 PDF 抽 MC+POM | `mc_pom_*.jsonl` |
| `build_l2_visual_guide.py` / `build_l2_decision_trees.py` | 從 xlsx + md 產生 Pass 2 guide / decision tree | `data/runtime/l2_visual_guide.json` / `data/runtime/l2_decision_trees.json` |
| `build_l2_l3_ie.py` | 從 `data/source/五階層展開項目_YYYYMMDD.xlsx` 拆分成 38 個 L1 JSON(純 stdlib,自動抓最新日期的 xlsx) | `l2_l3_ie/*.json`(+ `_index.json`) |
| `rebuild_all_analysis_v2.py` / `rebuild_grading_3d.py` | 全量分析 / 3D grading 重建 | `$BASE/*.json`(吃 `$POM_PIPELINE_BASE`,輸出在外部 BASE 樹) |
| `validate_buckets.py` | 驗證 `data/runtime/bucket_taxonomy.json` + `pom_rules/*.json` 一致性 | exit 0 / 1 |

分類邏輯改了或新資料進來時的流程（每支腳本都接受 `--base-dir` 或 `$POM_PIPELINE_BASE`）：

```bash
export POM_PIPELINE_BASE=/你的 BASE 路徑
python3 scripts/core/run_extract_new.py              # 1. 新 PDF → mc_pom_*.jsonl
python3 scripts/core/rebuild_profiles.py             # 2. 合併 profile union
python3 scripts/core/reclassify_and_rebuild.py       # 3. 重算 → 覆蓋 pom_rules/
python3 scripts/core/enforce_tier1.py                # 4a. 後處理:tier1 強制
python3 scripts/core/fix_sort_order.py               # 4b. 後處理:排序
# 5. push 到 main,前端自動套用
```

BASE 目錄需包含 `2024/ 2025/ 2026/` PDF 樹 + `_parsed/` + `all_years.jsonl` + `pom_dictionary.json`（詳情看 `scripts/core/_pipeline_base.py` docstring）。想給外部單位跑,用前端「📦 打包 Pipeline」下載 zip。

### 新增 bucket 的 SOP

兩組 bucket 有不同來源和新增方式,**不要混淆**:

| Bucket 集 | 位置 | 形狀 | 新增方式 |
|---|---|---|---|
| **Pipeline A (recipes_master) 的 59 bucket** | `data/runtime/bucket_taxonomy.json` | `<gender>_<dept>_<gt>` (lowercase) | **手動** — 編輯 JSON 加新 entry,每個 entry 必須有 `gender` / `dept` / `gt` 三個非空 list。加完跑 `python3 scripts/core/validate_buckets.py` 驗證一致性,再重新跑 `python3 star_schema/scripts/build_recipes_master.py --strict` 確認 facts 被接受。 |
| **Pipeline B (POM RULES) 的 81 bucket** | `pom_rules/*.json` + `pom_rules/_index.json` | `<DEPT>_<GT>\|<GENDER>` (UPPERCASE) | **自動** — 不要手改。把新 PDF 放進 BASE 資料夾,跑 `reclassify_and_rebuild.py`,它會自動建出新 bucket 檔。 |

**Recipes** (`recipes/recipe_<GENDER>_<DEPT>_<GT>_<IT>.json`) 是第三個維度(多個 item_type),跟兩組 bucket 不是 1:1,由 Pipeline A 的 ingest 產生,一般不手動改。

Validator: `python3 scripts/core/validate_buckets.py` 檢查:
- `pom_rules/_index.json` 跟磁碟上的檔案對得上
- 每個 bucket 檔的 `bucket` 字串跟自己 `gender`/`department`/`garment_type` 欄位一致
- `data/runtime/bucket_taxonomy.json` keys 全 lowercase、無 case collision、三欄位齊全

`--strict` 旗標把 warning 也當 error。加到 CI 的方式:在 `.github/workflows/rebuild_master.yml` 的 Step 3 前加一步 `python3 scripts/core/validate_buckets.py --strict`。

### Extract scripts 三個位置的角色分工

Repo 裡有三個位置各有 `extract*.py`,形狀相似但**產出格式完全不同、餵不同 pipeline**,常混淆:

| 位置 | 腳本 | 輸入 | 輸出格式 | 餵誰 | 現狀 |
|---|---|---|---|---|---|
| `scripts/lib/` | `extract_techpack.py` | Centric 8 ONY 單份 PDF | in-memory dict:`{design_number, mcs:[{poms:[{POM_Code,sizes:{...}}]}]}` | 被 `scripts/core/run_extract_*.py` import 當底層 parser | **活**(純函式庫,2026-05-07 從 pom_analysis_v5.5.1/scripts/ 抽出) |
| `scripts/core/` | `run_extract_2025_seasonal.py` | `$BASE/2025/{FA25,HO25,SP25,SU25}/**/*.pdf` | `$BASE/_parsed/mc_pom_2025.jsonl` | Pipeline B(POM RULES)的 `rebuild_profiles.py` | **活** — 2025 backlog 專用 |
| `scripts/core/` | `run_extract_new.py` | `$BASE/2026/{5,FA26,HO26,SP26,SU26,SP23,SP27}/**/*.pdf` | `$BASE/_parsed/mc_pom_2026.jsonl` | 同上 | **活** — 2026 production(~5K PDF)|
| `star_schema/scripts/` | `extract_raw_text.py` | `data/ingest/uploads/*.pdf`、`*.pptx` | `data/ingest/metadata/designs.jsonl` + `pptx/*.txt` + `pdf/callout_images/*.png` | Pipeline A(recipes_master)Step 1 | **活** — CI 每次 push uploads/ 自動跑 |
| `star_schema/scripts/` | `extract_unified.py` | `data/ingest/{metadata,pptx,pdf,vlm}/` | `data/ingest/unified/{dim,facts}.jsonl` | Pipeline A Step 2a | **活** — 同上,CI 自動跑 |

**怎麼選用**:

- 重建 **POM RULES**(81 bucket 尺寸規則)→ 用 `scripts/core/run_extract_*.py`(+ `scripts/lib/extract_techpack.py` 當 parser)。`mc_pom_*.jsonl` 含 measurement chart + POM rows,是 `rebuild_profiles.py` 的唯一進料
- 重建 **recipes_master**(做工配方)→ 用 `star_schema/scripts/extract_*.py`。不關心 MC/POM 尺寸,抓的是做工 callout + ISO zone
- ~~v5.5.1/run_extract.py~~ 已於 2026-05-07 隨 `pom_analysis_v5.5.1/` 整個資料夾退役;`extract_techpack.py` 抽到 `scripts/lib/`,其餘清掉

### 線上 ingest pipeline（`star_schema/scripts/` + GitHub Actions）

Admin 在前端「📤 上傳 Techpack」丟一份 PDF/PPTX：

1. **上傳路徑**：`POST /api/ingest_token` 取 `GITHUB_PAT`，瀏覽器直連 GitHub `PUT contents` 把檔案送進 `data/ingest/uploads/`。沒檔案大小分流（歷史上曾規劃走 `/api/ingest_upload` 的小檔路徑，2026-04-24 移除未實作的 endpoint；現在任何大小都走直連）。
2. **GitHub Actions 觸發**（`.github/workflows/rebuild_master.yml`，`push: paths: data/ingest/uploads/**`）。實際步驟順序是 **1 → 2b → 2a → 3**（2b 刻意排在 2a 前，讓 2a 的 unified 合併能吃到本次 run 剛產出的 VLM facts）：
   - **Step 1** `extract_raw_text.py` — 掃 uploads/；PDF 讀首頁元資料（季節 / 品牌 / 類型）+ 抽 D-number，PPTX 逐頁取文字，PDF callout 頁面評分後 216 DPI 渲染成 PNG。`--allow-empty` 允許首次空掃，`--force` 忽略已處理重跑。
   - **Step 2b** `vlm_pipeline.py --map-iso --ingest-dir data/ingest --out data/ingest/vlm` — 若沒預填 `vlm_raw_extracts.json` 但 `ANTHROPIC_API_KEY` 有設，會對每張 callout PNG 呼叫 Claude Haiku 自動分析（`requirements-pipeline.txt` 加 `anthropic>=0.25.0`）；否則讀既有 `vlm_raw_extracts.json` 走手填路徑。輸出 `vlm/facts.jsonl`（含 `bucket` 欄位，Step 3 才能用）+ `vlm_callout_extracts.json`。**資料夾是 `vlm/`，不是 `vlm_v1/`**。`continue-on-error`，失敗不擋 build。
   - **Step 2b failure notice**（跟在 2b 後面，`if: steps.vlm.outcome == 'failure'`）— 2b 失敗時寫醒目警告到 `$GITHUB_STEP_SUMMARY` 並設 `VLM_FAILED=true`；Commit step 會把這個 flag 加到 commit message body，讓翻 git log 或 Actions UI 的人一眼看得到。
   - **Step 2a** `extract_unified.py` — **全量**合併 4 來源（PPTX 中文 / PDF 英文 / construction_by_bucket / construction_from_dir5）+ Step 2b 剛產的 VLM facts → `unified/{dim,facts}.jsonl`。中文 / 英文各自 parse zone + ISO，優先級：PPTX JSON > PPTX txt > 其他。
   - **Step 3** `build_recipes_master.py --strict` — 合併 5 份來源 → 全量重建：
     - `path2_universal/iso_lookup_factory_v4.3.json`（primary，230 條）
     - `path2_universal/iso_lookup_factory_v4.json`（fallback，282 條）
     - `data/runtime/construction_bridge_v6.json`（跨設計 GT × zone 統計）
     - `recipes/*.json`（72 檔，含 `_index.json` + 71 recipe）
     - `data/ingest/consensus_v1/entries.jsonl`（275 條 bucket consensus）
     - 加上 `data/ingest/*/facts.jsonl`（含 vlm/）；L1 必須在 38 標準內、bucket 必須在 taxonomy 內。違規 exit 1，擋住 commit。
     - 輸出：`data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json`
3. **Commit 回 `main`**：`git rm data/ingest/uploads/*` + `git add` 重建結果 + `git add data/ingest/vlm/`（讓 VLM 分析結果持久化）；訊息 `chore(data): auto-rebuild recipes_master [skip ci]` 避免無限循環；Vercel 偵測 push → 自動重新部署。

前端在「📤 上傳 Techpack」Modal 內 poll `GET /repos/.../actions/runs?head_sha=<sha>`，依 workflow 實際順序顯示 5 個 step：**1｜拆解文字 & callout 圖片 → 2b｜VLM 分析 callout (PDF) → 2a｜統一萃取 (PPTX) → 3｜重建 recipes_master → 提交資料**。Actions API 回 403/404（私人 repo / token 缺 `actions:read` scope）會降級成不帶 token 重試，仍失敗時直接顯示 GitHub Actions 連結不再 poll。

## Admin 通道

所有 admin 入口都要 `x-admin-token`（對應 Vercel 的 `ADMIN_TOKEN` 環境變數）；進到前端管理選單先在「⚙ 設定」填。管理選單分兩組:**Pipeline 對外協作** + **管理工具**。

| 入口 | 做什麼 | 走哪 | Body 大小 |
|---|---|---|---|
| 📦 下載 Pipeline 包（PackageModal） | 組 zip 給外部協作單位在本機跑 **Pipeline A(recipes_master)+ Pipeline B(POM RULES)** 兩條線。含 13 個 py + 參考資料 + 2 份 pom pipeline .md + 自動產 README / VERSION / `.env.example` / `run.sh` / `run_pom_rules.sh` | 取 PAT → GitHub API 抓 main sha + recipes/ 列表 → 並行拉 raw.githubusercontent.com → JSZip 瀏覽器組 zip → 觸發下載 | — |
| 📥 上傳 Pipeline 結果（ResultsUploadModal） | 吃外部送回的 zip / jsonl,merge 到 `data/ingest/{unified,vlm}/facts.jsonl` + `metadata/designs.jsonl`(append 或 append-dedup by design_id) | JSZip 瀏覽器解壓 → 比對 path → GET 現有 → merge → 直連 `PUT contents` | 無實質上限 |
| 📤 上傳 Techpack（UploadModal） | 丟 PDF/PPTX 進 `data/ingest/uploads/`,觸發 Actions 重建 recipes_master | `POST /api/ingest_token` → 瀏覽器直連 GitHub `PUT` | 無實質上限 |
| 📝 POM 翻譯表編輯（AdminModal） | 編 `data/runtime/pom_dictionary.json`,自動 diff + commit msg | `POST /api/push-pom-dict`(Vercel endpoint) | 小 |
| 🛠 IE 底稿管理（IEAdminModal） | 聚陽送新版 xlsx 時上傳到 `data/source/五階層展開項目_YYYYMMDD.xlsx`,觸發 `build_l2_l3_ie.yml` workflow 自動重建 `l2_l3_ie/*.json`。xlsx 通常 9.5 MB。 | `POST /api/ingest_token` → 瀏覽器直連 GitHub `PUT`(因 xlsx 超過 Vercel 4.5 MB) | 無實質上限 |
| 📚 權威手冊登記表（ManualsModal） | Read-only,顯示 7 份權威手冊的角色 / 引用鏈 | 無後端呼叫 | — |

> ~~🩹 上傳 Patch (JSON)（PatchUploadModal）~~ — 2026-04-23 移除,由 📥 上傳 Pipeline 結果取代(新通道吃 raw facts.jsonl 而非 recipes_master.json patch,更符合外部協作實際流程)。

所有直連 GitHub 的路徑共用 `/api/ingest_token` 發出的 `GITHUB_PAT`(需 `contents: write`);PAT 只在 admin 瀏覽器 session 裡活著。

### Pipeline 外送包

📦 下載後交給協作單位,內含:
- **Pipeline A 腳本**:`star_schema/scripts/*.py`(4 檔)
- **Pipeline B 腳本**:`scripts/core/*.py`(8 檔包含 `_pipeline_base.py` + 7 支改用 `--base-dir` / `$POM_PIPELINE_BASE` 的產線腳本)+ `scripts/lib/extract_techpack.py`
- `requirements-pipeline.txt`、`docs/spec/techpack-translation-style-guide.md`
- 所有 reference JSON(construction_bridge / bucket_taxonomy / l1_standard_38 / pom_dictionary / consensus / iso_lookup × 2 / recipes × 72)
- Pipeline B 產線文件:`docs/sop/pom_rules_pipeline_guide_v2.md` + `docs/spec/pom_rules_v55_classification_logic.md`
- 動態產:`README.md`(繁中含兩條 pipeline 的 setup/run/回傳步驟)、`VERSION`(commit sha)、`.env.example`(提醒自備 `ANTHROPIC_API_KEY`)、`run.sh`(Pipeline A)、`run_pom_rules.sh`(Pipeline B)

外部跑完 Pipeline A 的 `./run.sh` 後,把 `data/ingest/{metadata,unified,vlm}/*.jsonl` 打成 zip → 📥 上傳回來 → 到 Actions 手動 workflow_dispatch 重建 recipes_master。
Pipeline B(`./run_pom_rules.sh`)跑完產出的 `$POM_PIPELINE_BASE/pom_rules/` 整個覆蓋 repo 的 `pom_rules/` 目錄 → PR 推上去。

## 本機預覽

直接用任何 static server 指到專案根目錄即可：

```bash
python3 -m http.server 5173
# 或
npx serve .
```

`/api/*` 本機無法執行（需 Vercel runtime）；要測 AI 功能或 admin 通道請部署到 Vercel preview。

## 部署

GitHub push → Vercel 自動建置（preview / production）。

**Vercel 環境變數**（Project Settings）：
- `ANTHROPIC_API_KEY` — `api/analyze.js` 呼叫 Claude Vision 用
- `ADMIN_TOKEN` — 所有 admin 端點共享的驗證 token
- `GITHUB_PAT` — `api/push-pom-dict.js` / `api/ingest_token.js` 寫回 GitHub 用（需 `contents: write`）

**GitHub Actions secrets**（Repo Settings）：
- `ANTHROPIC_API_KEY` — workflow Step 2b VLM pipeline 用（沒設定時 2b 跳過，不擋 build）
- `GITHUB_TOKEN` — 自動注入，Commit step push 用
