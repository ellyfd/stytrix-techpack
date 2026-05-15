# Platform Data Pipeline Mapping

⚠️ **每次 build / 改 data path 之前 RTFM 這份。違反 = 資料用錯。**

聚陽端 mirror 在 `M7_Pipeline/skills/data-pipeline-mapping/SKILL.md`。兩邊邊界:
- 聚陽端負責 SSRS / TP fetch → push 進這個 repo 的 `data/ingest/m7/`
- 這份文件從 `data/ingest/m7/` 收件開始

---

## 1. 資料夾分工(2026-05-08 結構)

```
data/
  runtime/                    線上系統 runtime 讀的成品 JSON (前端 fetch / api/ 讀)
    recipes_master.json       通用模型 ISO consensus,GitHub Actions 自動重建
    iso_dictionary.json       ISO 字典,自動重建
    l1_standard_38.json       38 個 L1 部位標準
    l2_visual_guide.json      聚陽 Pass 1/2 視覺指引
    l2_decision_trees.json    Pass 2 decision tree
    pom_dictionary.json       POM 代號對照(admin 編)
    construction_bridge_v6.json  跨設計 GT × zone 統計
    bucket_taxonomy.json      v4 4-dim + legacy_buckets alias (28+59)
    grading_patterns.json     跳碼 pattern
    bodytype_variance.json    Body Type 差異
    all_designs_gt_it_classification.json  全量 design 分類 (CI Step 2 fallback 用)
    l1_part_presence_v1.json   聚陽模型部位出現率
    l1_iso_recommendations_v1.json
    code_manifest.json        Code 瀏覽 modal 的檔案清單
    brands.json               前端 Brand 下拉 source (Step 4c 產)
    # 2026-05-14:gender_gt_pom_rules / client_rules / design_classification_v5
    # 從 runtime/ 退役搬到 pom_rules/_derive/ (Pipeline B 內部產物,前端/api 不讀)

  source/                     手維護 / 上傳的原始底稿
    L2_代號中文對照表.xlsx    L1/L2 代號對照(14 KB)
    BIBLE_UPGRADE.md          Bible 升級 SOP (xlsx 留聚陽端不進 repo)
    M7_PULLON_DATA_SCHEMA.md  m7 source schema 文件
    # ❌ 五階層展開項目_*.xlsx 不再進 repo

  ingest/                     Pipeline staging
    uploads/                  使用者上傳 PDF/PPTX(處理完 workflow 刪)
    metadata/designs.jsonl    Step 1 PDF/PPTX 抽出的 D-number + cover metadata
    pptx/<slug>.txt           Step 1 PPTX 文字
    pdf/construction_images/  Step 1 PDF construction 頁 PNG(2026-05-12 rename)
    pdf/construction_manifest.jsonl Step 1 manifest
    unified/{dim,facts}.jsonl  Step 2a 全量合併
    vlm/{facts.jsonl,...}     Step 2b VLM 抽出
    consensus_v1/entries.jsonl  人工 consensus(275)
    consensus_rules/facts.jsonl  舊 OCR consensus(275,glob)
    ocr_v1/facts.jsonl        舊 OCR 1202(glob)
    construction_by_bucket/   外部資料源(688)
    m7/                ⭐ 2026-05-08+ 聚陽 PullOn pipeline 推進來
      entries.jsonl           30 MB / 5,076 entries (aggregated)
      designs.jsonl.gz        ~32 MB (gzipped per-EIDH 履歷,5,076 designs)

  legacy/                     退役 fallback (只縮不增)

l2_l3_ie/<L1>.json (38 + _index)     Bible 五階層展開,Phase 2 dict schema (升級於 2026-05-08);
                                     每 L5 step 含 ie_standard + 可選 actuals (m7 by_brand 觀察值)
# l2_l3_ie_by_client/                ✅ RETIRED 2026-05-08 (Phase 2.5b);功能由
#                                     l2_l3_ie/ + frontend filterBibleByBrand() helper 取代
recipes/                              PATH2 做工配方(72 檔)
pom_rules/                            137 個 bucket(自動產)
path2_universal/                      通用模型 ISO 查表 (v4.3 + v4)
star_schema/scripts/                  CI 觸發的 ingest pipeline
api/                                  Vercel functions
docs/spec/                            跨模組共用規格
docs/architecture/                    架構設計文件
docs/sop/                             純人類操作 SOP
```

---

## 2. 上游 → 線上 4 階段

```
Step 1 raw 收集     Step 2 source       Step 3 master         Step 4 view
   ↓                   ↓                    ↓                     ↓
data/ingest/       per-source 中介      build_recipes_master   derive_view_*
uploads/           facts.jsonl                                  (Phase 2)
聚陽 push                              data/master.jsonl       data/runtime/
                                       (Phase 2.1+)            recipes_master.json
                                                               l2_l3_ie/<L1>.json
                                                               (原 designs_index/ 2026-05-09 retired)
```

---

## 3. 工具 → 中介檔(`data/ingest/`)

### `star_schema/scripts/extract_raw_text.py`

```
python star_schema/scripts/extract_raw_text.py --scan-dir data/ingest/uploads --output-dir data/ingest
```

| 輸入 | 輸出 |
|---|---|
| `data/ingest/uploads/*.pdf` | `data/ingest/metadata/designs.jsonl`(append) |
| 同上 PDF | `data/ingest/pdf/construction_images/<DID>_p<N>.png`(216 DPI) |
| 同上 PDF | `data/ingest/pdf/construction_manifest.jsonl` |
| `data/ingest/uploads/*.pptx` | `data/ingest/pptx/<slug>.txt` |

### `star_schema/scripts/vlm_pipeline.py --map-iso`

```
python star_schema/scripts/vlm_pipeline.py --map-iso --out data/ingest/vlm --construction-dir data/ingest/pdf/construction_images --ingest-dir data/ingest
```

| 輸入 | 輸出 |
|---|---|
| `data/ingest/pdf/construction_images/*.png` | `data/ingest/vlm/facts.jsonl`(Claude Vision 抽 ISO/L1/zone) |
| 同上 | `data/ingest/vlm/vlm_construction_extracts.json` |

### `star_schema/scripts/extract_unified.py`

```
python star_schema/scripts/extract_unified.py --ingest-dir data/ingest --out data/ingest/unified
```

| 輸入 | 輸出 |
|---|---|
| `data/ingest/pptx/*.txt` + `metadata/designs.jsonl` + `vlm/facts.jsonl` | `data/ingest/unified/{dim,facts}.jsonl`(全量重建) |

---

## 4. 整合工具:`star_schema/scripts/build_recipes_master.py`

```
python star_schema/scripts/build_recipes_master.py --strict
```

**讀什麼**(7 來源 cascade):

| Source | 路徑 | 量 |
|---|---|---|
| recipe (same_sub) | `recipes/recipe_*.json` | 71-72 |
| consensus_v1 (same_bucket) | `data/ingest/consensus_v1/entries.jsonl` | 275 |
| facts_agg (same_bucket) | `data/ingest/*/facts.jsonl` glob | 動態 |
| **m7** ⭐ (same_bucket) | `data/ingest/m7/entries.jsonl` | 5,076 entries (~750 unique buckets) |
| v4.3 (same_gt) | `path2_universal/iso_lookup_factory_v4.3.json` | 230 |
| v4 (general) | `path2_universal/iso_lookup_factory_v4.json` | 282 |
| bridge (cross_design) | `data/runtime/construction_bridge_v6.json` | 53 |

**驗證**:L1 對 `l1_standard_38`、bucket 對 `bucket_taxonomy.json`(v4 + legacy_buckets)。違規 `--strict` exit 1。

**Step 3 寫什麼**:
- `data/master.jsonl` + `data/master.meta.json`(internal master,含 `_m7_*` 給 derive 用)
- `data/runtime/recipes_master.json`(初版,Step 4a 會覆寫剝乾淨版)
- `data/runtime/iso_dictionary.json`
- `data/runtime/l1_standard_38.json`

**Step 4 derive views**(2026-05-08+ View A + B 實裝,spec 見 `docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md`):
- **Step 4a** `derive_view_recipes_master.py` → View A:覆寫 `data/runtime/recipes_master.json`,剝 `_m7_*` 內部欄位
- **Step 4b** `derive_bible_actuals.py --all --in-place` → View B:升級 `l2_l3_ie/<L1>.json` 38 檔為 Phase 2 dict schema + 掛 m7 `actuals`(**2026-05-11 修 dict pass-through bug,永遠重算 actuals,新 brand 才會跟著 m7 push 自動進 by_brand**)
- **Step 4c** `scripts/core/build_brands.py` → `data/runtime/brands.json`:從 m7 `entries.jsonl` 聚合各 brand 的 n_entries / n_designs(2026-05-11 加,前端 Brand 下拉動態 source,取代硬寫 BRANDS 常數)
- ~~舊 Step 4c `derive_view_designs_index.py` → View C(per-EIDH designs_index)~~ — **2026-05-09 retired**(前端無 UI 消費,移除避免 dead 產物)。新 Step 4c 重用編號是因為 retired 後位置空出

---

## 5. Bible 升級:`scripts/core/build_bible_skeleton.py`

```
python scripts/core/build_bible_skeleton.py
```

| 輸入 | 輸出 |
|---|---|
| `data/source/五階層展開項目_YYYYMMDD.xlsx`(維護者本機,**不進 repo**) | `l2_l3_ie/<L1>.json` 38 檔 + `_index.json` |
| `data/source/L2_代號中文對照表.xlsx` | (registry) |

⚠ xlsx 留維護者本機,build 完 push 38 個 JSON。詳見 `data/source/BIBLE_UPGRADE.md`。

CI workflow `.github/workflows/build_bible_skeleton.yml` = `workflow_dispatch` only(不再 auto-trigger)。

---

## 6. POM Pipeline(獨立)

```
python scripts/core/reclassify_and_rebuild.py
```

| 輸入 | 輸出 |
|---|---|
| (POM 規則底稿) | `pom_rules/<bucket>.json` 137 個 |
| (POM dictionary) | `data/runtime/pom_dictionary.json` |

⛔ POM 跟做工 cascade 完全獨立,不要 cross-import。

---

## 7. 前端讀什麼

| 模式 | Fetch 路徑 |
|---|---|
| 通用模型 | `data/runtime/recipes_master.json` + `data/runtime/iso_dictionary.json` + `data/runtime/l1_standard_38.json` |
| 聚陽模型 | 上面 + `l2_l3_ie/<L1>.json`(lazy by 部位)+ `pom_rules/<bucket>.json` |
| VLM Pass 1/2 | `api/analyze.js` 啟動 inject `data/runtime/{l2_visual_guide,l2_decision_trees,l1_standard_38}.json` |

---

## 8. CI workflow

| Workflow | Trigger | 跑什麼 |
|---|---|---|
| `.github/workflows/rebuild_master.yml` | push `data/ingest/uploads/**` 或 `data/ingest/m7/**`(2026-05-12 改 `m7_pullon` → `m7`,commit `a0dc4f6`)| Step 1 extract_raw_text → 2b vlm_pipeline → 2a extract_unified → Pre-3 validate_buckets --strict → 3 build_recipes_master --strict → 4a derive_view_recipes_master → 4b derive_bible_actuals → 4c build_brands |
| `.github/workflows/validate_pom_rules.yml` ★ **2026-05-13 加** | push `pom_rules/**` 或 `scripts/core/validate_buckets.py` 或 workflow 本身 | 只跑 `validate_buckets.py --strict`(schema gate <1s,exit 1 on drift)。**不 regen** — 因為 regen 需要外部 `$POM_PIPELINE_BASE` 8,892 設計資料,CI 不具備 |
| `.github/workflows/build_bible_skeleton.yml` | `workflow_dispatch` only | build_bible_skeleton |

---

## 9. 常見錯誤對照

| 症狀 | 原因 | 修法 |
|---|---|---|
| `bucket not in taxonomy` 報錯 | 用 v3 schema 讀 v4 file | 確認 `load_bucket_taxonomy()` 已升級含 `legacy_buckets` 合併 |
| `recipes_master.json` 缺 m7 entries | `data/ingest/m7/entries.jsonl` 沒 push 上 | 跑 M7 端 `push_m7_pullon_v3.ps1` |
| `l2_l3_ie/<L1>.json` 沒更新 | xlsx 沒 build | 維護者本機跑 `scripts/core/build_bible_skeleton.py` 後 push 38 JSON |
| 前端看到舊 ISO | CI 沒重跑 | 確認 push 有碰 `data/ingest/uploads/**` 或 `m7/**`;否則手動 `workflow_dispatch` |
| brand-specific 五階層拿不到 | 還在試 fetch `/l2_l3_ie_by_client/`(已退役) | 改用 `l2_l3_ie/<L1>.json` + frontend `filterBibleByBrand()` (從 actuals.by_brand 過濾)。需要更細的 client × 品類組合用 `filterBibleByCategory(bible, {brand,fabric,gender,dept,gt,it})` 6 維 runtime filter,反查 `designs.jsonl.gz` 重算 sec_median(2026-05-11+) |

---

## 10. 不要碰

- ❌ `l2_l3_ie/` 38 檔手改 — CI 自動產(`derive_bible_actuals.py --in-place`,從 xlsx + m7)
- ❌ `recipes_master.json` 手改 — CI 自動產(`derive_view_recipes_master.py`)
- ❌ `pom_rules/*.json` 手改 — script 自動產
- ❌ `l2_l3_ie_by_client/` 加新檔 — RETIRED 2026-05-08 (Phase 2.5b),已 git rm
- ❌ `data/legacy/` 加新檔 — 只縮不增
- ❌ `data/source/五階層展開項目_*.xlsx` 進 repo — 留聚陽端

---

## 11. 流程順序(從零跑)

```bash
# A. 維護者本機 build Bible(若 xlsx 改了)
python scripts/core/build_bible_skeleton.py
git add l2_l3_ie/ && git commit -m "feat(bible): rebuild" && git push

# B. 聚陽端 push m7 source(若 SSRS / 列管有更新)
#    在 M7_Pipeline 端跑(見 M7 端 SKILL):
#    python scripts/build_m7_pullon_source_v3.py
#    .\scripts\push_m7_pullon_v3.ps1

# C. 使用者上傳 PDF/PPTX 觸發 CI
#    走 web upload 進 data/ingest/uploads/ → CI auto build_recipes_master

# D. (可選)手動觸發 workflow
#    GitHub Actions → "Rebuild recipes_master" → Run workflow
```

---

## 鏡像對應

`M7_Pipeline/skills/data-pipeline-mapping/SKILL.md`(聚陽 Windows 端):
- M7 SSRS 五階展開 + m7_report fetch
- TP PDF/PPTX SMB 拉取
- `extract_raw_text_m7.py` 三 mode(--metadata-only / --pptx-only / --pdf-only)
- `build_m7_pullon_source_v3.py`(deprecate v1+v2)
- push 進這個 repo 的 `data/ingest/m7/`

**邊界**:聚陽端 push 完結束。Platform 端從 `data/ingest/m7/` 收件開始。
