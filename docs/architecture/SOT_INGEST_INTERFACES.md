# SOT Ingest Interfaces — StyTrix Techpack Platform

> **目的**：定義外部資料如何進入 platform 的每個 SOT(source of truth)。每個 SOT 一份 ingest spec，固定 5 欄：誰寫 / Schema / 路徑 / Validation gate / 衝突 priority。
>
> 設計原則：**Single SOT, multiple consumers, derived runtime exports**。手維護的 SOT 放 `data/source/`，CI 自動產出的 runtime view 放 `data/runtime/`，副本不允許。
>
> **2026-05-16 v1** — Elly + Claude session 確立架構

---

## 0. SOT 全景圖

```
                   ┌───────────────────────┐
                   │   外部 source           │
                   │  (聚陽 IE / 工程 / PR)  │
                   └──────────┬────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────┐
       │  data/source/      ← 手維護 SOT (人類)     │
       │  ─────────────────                        │
       │  iso_dictionary.json                      │
       │  canonical_aliases.json                   │
       │  l1_standard_38.json                      │
       │  bucket_taxonomy.json                     │
       │  client_canonical_mapping.json            │
       │  {dept,gt,fabric,gender}_keywords.json    │
       │  ISO對應五階層機種.xlsx                    │
       │  五階層展開項目_*.xlsx                     │
       │  ISO_客人縫法對照表_Glossary.xlsx          │
       └──────────────────────────────────────────┘
                              │
                              ▼ CI derive (workflow rebuild_master.yml Step 4a-e)
                              │
       ┌──────────────────────────────────────────┐
       │  data/runtime/     ← derived (read-only) │
       │  ─────────────────                        │
       │  brand_pom_alias.json    (Step 4d)        │
       │  brands.json             (Step 4c)        │
       │  dept_lookup_by_subgroup.json  (Step 4e)  │
       │  gender_lookup_by_subgroup.json (Step 4e) │
       │  customer_terminology_master.json (one-off│
       │  customer_style_profile.json    跑 build) │
       │  recipes_master.json     (Step 3)         │
       │  l2_l3_ie/*.json         (Step 4b)        │
       └──────────────────────────────────────────┘
                              │
                              ▼
                        ┌─────────┐
                        │ 前端    │
                        │ analyze │
                        │   api    │
                        └─────────┘
```

---

## 1. `iso_dictionary` — ISO 機種主表

| 欄 | 內容 |
|---|---|
| **路徑** | `data/runtime/iso_dictionary.json` (SOT)。M7_Pipeline 副本已刪 (2026-05-15)。|
| **誰寫** | 工程 + IE 共同維護。新增 ISO 編號 by PR review。|
| **Schema** | `{ "entries": { "<ISO_CODE>": { "zh": "...", "en_canonical": "...", "machine": "...", "_source": "..." } } }`。ISO_CODE = string (`"301"` / `"406"` / `"514+401"`)。 |
| **進入路徑** | (a) PR → review → merge。(b) 工程腳本 commit (例: `d366d22` 補 101/500/503)。 |
| **Validation gate** | `tests/test_schema.py` 驗 38 主要 ISO 碼必存在;`api/analyze.js` 啟動時 load 一次驗 JSON 可 parse;前端 `index.html:6320` runtime fetch + 顯示。 |
| **衝突 priority** | 手動 PR 衝突走標準 git review。新 ISO 碼必填 `_source` 註明依據 (例: "聚陽 IE 設備清單 2026-04 / Centric 8 manual")。 |

**Derived from**: `ISO對應五階層機種.xlsx` (聚陽端設備清單)。手 sync 進 JSON,xlsx 不在 CI 路徑上。

---

## 2. `canonical_aliases` — 8 維 alias 對照

| 欄 | 內容 |
|---|---|
| **路徑** | `data/source/canonical_aliases.json` (SOT v2 schema)。 |
| **誰寫** | Elly + 業務知識手維護。新增客戶或客戶改寫法時更新。 |
| **Schema (v2)** | `{ "<DIMENSION>": { "<short_code>": ["<alias1>", "<alias2>", ...] } }`。8 維度: 客戶 / PRODUCT_CATEGORY / Subgroup / Item / Season / 報價款號 (Season + 報價款號 走 regex normalize 不 list)。 |
| **進入路徑** | PR 編輯 JSON → review → merge。每個短碼一行 + alias list。`_schema: "v2"` 標明。 |
| **Validation gate** | `consolidate_canonical.py:_load_aliases()` graceful 退空 dict (parse 失敗不擋 build);`tests/test_schema.py` 抓 dup-key bug;v1 backward compat 留至 PR-2 拔掉。 |
| **衝突 priority** | M7 列管 > PDF 寫法 > 推論 (見 consolidate_canonical.py `consolidate_field()` 的 weight 設計, M7 weight 3 / PDF 2 / inferred 1)。 |

**Derived runtime**: `data/runtime/brand_pom_alias.json` (Step 4d from `canonical_aliases.客戶` + `client_canonical_mapping.aliases`)。

---

## 3. `l1_standard_38` — 38 L1 部位

| 欄 | 內容 |
|---|---|
| **路徑** | `data/runtime/l1_standard_38.json` (SOT)。 |
| **誰寫** | IE 部位定義工程 + Elly。38 部位 schema 固定,不會新增 (除非整套 L1-L5 重設計)。 |
| **Schema** | `[{ "code": "WB", "zh": "腰頭", "category": "BOTTOM", ... }] × 38`。 |
| **進入路徑** | 從 `五階層部位.xlsx` 手 sync。改動極少。 |
| **Validation gate** | `tests/test_schema.py:test_l1_38_parts`;`extract_unified.py:_load_l1_standard_38()` 讀 SOT (commit `a6c73cc`);`l2_l3_ie/_index.json` 38 個 file 對應檢查。 |
| **衝突 priority** | 不允許 38 碼變動。新加碼需 ADR (Architecture Decision Record) + 全 IE 表重生。 |

---

## 4. `bucket_taxonomy` — 28 v4 + 59 legacy buckets

| 欄 | 內容 |
|---|---|
| **路徑** | `data/runtime/bucket_taxonomy.json` (SOT)。 |
| **誰寫** | 聚陽端 `M7_Pipeline/scripts/generate_bucket_taxonomy_from_mk.py` 從 MK Metadata 重生。 |
| **Schema** | `{ "v4_buckets": {...28 entry...}, "legacy_buckets": {...59 entry...}, "legacy_note": "..." }`。v4 = `<GENDER>_<DEPT>_<GT>_<IT>` 4 維 UPPER; legacy = 3 維 (`<GENDER>_<DEPT>_<GT>`) 兜底。 |
| **進入路徑** | 聚陽端跑 generator → JSON drop in → PR → CI Step 3 `build_recipes_master.py` 讀。 |
| **Validation gate** | `scripts/core/validate_buckets.py --strict` (Pre-Step 3 + workflow `validate_pom_rules.yml`) 檢: UPPERCASE / 必填欄 / v4-v3 prefix collision。 |
| **衝突 priority** | M7 Metadata → bucket schema。手動 PR 不允許 (要對齊 v9 GT 就重跑 generator)。 |

---

## 5. `client_canonical_mapping` — 22 客戶 × subgroup × 4 維 GT

| 欄 | 內容 |
|---|---|
| **路徑** | `data/client_canonical_mapping.json` (SOT v3)。 |
| **誰寫** | 聚陽端 `merge_client_metadata_v3.py` 從 v1 (`client_metadata_mapping.json`) + v2 (`client_canonical_mapping_v2.json`) 合併產出。 |
| **Schema** | `{ "client_canonical_mapping": { "<CLIENT>": { "subgroup_to_meta": { "<SUBGROUP>": { "dept": {"value":"ACTIVE","purity":100}, "gender": {...}, "fabric": {...}, "category": {...} } } } } }`。 |
| **進入路徑** | 聚陽端跑 merge → PR → CI Step 4e `build_dept_lookup_by_subgroup.py` derive 兩個 runtime lookup。 |
| **Validation gate** | `_purity_threshold_pct: 60` (本身就濾過低 purity);Step 4e graceful 退空 (purity < 60 跳過,not error)。 |
| **衝突 priority** | M7 列管 5/7 索引 ground truth > v1 legacy hard mapping > regex token > client default。 |

**Derived runtime**:
- `data/runtime/dept_lookup_by_subgroup.json` (Step 4e, 111 entries)
- `data/runtime/gender_lookup_by_subgroup.json` (Step 4e, 100 entries)

---

## 6. 4 維分類 keyword tables (2026-05-16 加)

| 欄 | 內容 |
|---|---|
| **路徑** | `data/source/{dept,gt,fabric,gender}_keywords.json` (SOT)。 |
| **誰寫** | Elly + 工程手維護。新增 token / 新規則改 JSON 不改 .py。 |
| **Schema** | 每檔 ~50-200 行 JSON,內含 cascade priority + tier-by-tier keyword tables (見各檔 `_priority_cascade` field)。 |
| **進入路徑** | PR 編輯 JSON。Consumer .py (`resolve_classification.py`) lazy load + cache。 |
| **Validation gate** | 暫無 dedicated test (因為是 keyword cascade,不擋 schema)。實際驗證走 `build_recipes_master --strict` (entries 數應穩定)。**未來補**: 寫 `test_classification_smoke.py` 驗一組 fixed input → expected output 不會 drift。 |
| **衝突 priority** | Cascade 內: T1 (M7 canonical lookup) > T2-T7 (keyword)。tier 內: priority_order field 定義 (如 ACTIVE 在 FLEECE 之前)。 |

---

## 7. `customer_terminology` — 客人縫法 glossary (2026-05-16 加)

| 欄 | 內容 |
|---|---|
| **路徑** | `Source-Data/做工翻譯/` (raw xlsx 13 客人 + 蒸餾 Glossary 31K + style guide MD) |
| **誰寫** | 黃宇傑 (聚陽 IE) 維護 raw `做工翻譯_<CLIENT>.xlsx`。新客戶加入或客戶寫法更新時更新。蒸餾版 `ISO_客人縫法對照表_Glossary.xlsx` 由 黃宇傑 階段性產出。 |
| **Schema** | Raw xlsx 客人寫法逐句。蒸餾版 Sheet1 = ISO×客人寫法矩陣 (11 ISO × 13 客人 ≈ 130 cells)、Sheet2 = 客人 style profile (7 維)。 |
| **進入路徑** | `scripts/core/build_customer_terminology.py` 跑一次,從 Glossary xlsx 蒸餾 → `data/runtime/customer_terminology_master.json` + `customer_style_profile.json`。**不在 CI workflow 內**,手動跑(因為 raw xlsx 不在 repo path)。 |
| **Validation gate** | `_canonical_clients` field 列出 13 客人,驗證 count ≥ 11 ISO codes;`_todo: l5_anchors` flag 提醒接通 iso_lookup_5dim machine→L5 reverse map。 |
| **衝突 priority** | Glossary 31K 蒸餾版 > raw xlsx (raw 是 source of detail,蒸餾版是 source of truth for ISO mapping)。 |

**Consumer**:
- ingest: PDF/PPTX extract 時 客人 phrasing → ISO normalize (reverse map)
- output: 做工建議 formatter (五階 L5 → ISO → 客人慣用語 forward map,套 style profile format)

---

## 8. M7 entries.jsonl / designs.jsonl.gz

特殊狀態 — 不是「手維護 SOT」,是聚陽 m7 push pipeline 的 raw 產出,直接進 `data/ingest/m7/`。

| 欄 | 內容 |
|---|---|
| **路徑** | `data/ingest/m7/entries.jsonl` + `data/ingest/m7/designs.jsonl.gz` |
| **誰寫** | 聚陽 Windows 端 `M7_Pipeline/scripts/build_m7_pullon_source_v3.py` (PullOn pipeline) push 進來。 |
| **Schema** | `entries.jsonl` 每行 = 一個 6 維 key (gender/dept/gt/it/fabric/l1) 的聚合;`designs.jsonl.gz` 每行 = 一個 design 含 canonical block + 5-level 工段樹。 |
| **進入路徑** | 聚陽 push 後觸發 workflow `rebuild_master.yml` (paths: `data/ingest/m7/**`)。Step 3 `build_recipes_master.py` 吃 entries.jsonl。Step 4b `derive_bible_actuals.py` 吃 designs.jsonl.gz 升 Bible actuals。Step 4c `build_brands.py` 從 entries.jsonl 算 brands.json。 |
| **Validation gate** | Step 3 strict gate (B-tier 0 筆才繼續)。Step 4b idempotent (重跑同 push 不會 drift)。 |
| **衝突 priority** | M7 m7 push = ground truth,前端永遠跟著刷。 |

---

## 9. 統一規範

### 9.1 SOT 副本嚴禁
任何 SOT 只能存在一份。M7_Pipeline 端如果要讀 SOT,走 `_find_<SOT>_path()` resolver pattern (跨 repo + Source-Data 解析),不允許 copy。

### 9.2 `_sot` / `_consumer` / `_source` 三件套
每個 SOT JSON 檔 frontmatter 必有:
- `_sot`: 標明本檔是 SOT (不要再建副本)
- `_consumer`: 列出哪些 code 讀本檔
- `_source`: 資料來源 (xlsx / 業務知識 / generated by 哪支 script)

### 9.3 v1 → v2 schema 升級規範
- Consumer 先支援雙 schema (v1 backward + v2 forward)
- Data 後切 v2 (帶 `_schema: "v2"` field)
- 觀察穩定後 PR-2 拔掉 v1 backward path
- 範例: `canonical_aliases.json` v1 (`alias→short`) → v2 (`short→[alias_list]`),consumer `consolidate_canonical.py:_apply_alias()` 支援雙 schema

### 9.4 雙 location 同步 (repo + Source-Data)
聚陽 Windows 端跟 repo 內各放一份共用腳本 (`consolidate_canonical.py` / `resolve_classification.py` / `derive_metadata.py`)。改動兩邊都改,PR 時兩個 location 同 commit。

### 9.5 Bash mount stale 規則
Repo files via bash 在某些環境下會看到 stale view (cache 沒刷新)。驗 repo 檔狀態用 file system 工具 (Read tool / Windows Explorer)。bash 顯示異常時 cross-verify 真實 disk 狀態。

---

## 10. 未來擴張接口

預留 5 個 SOT slot,等資料 ready 再進來:
1. **`customer_size_runs`** (尺寸套 5/14 已做) — 盤 × 客人 × gender × 尺寸套 × 基碼
2. **`bodytype_variance` per-brand** — 補上 brand 維度 (現只有 ONY)
3. **`pom_rules` 24 brand re-extract** — v9 已部分,完整 24 brand 還沒
4. **`l5_anchors` for customer_terminology** — 從 iso_lookup_5dim machine→L5 reverse 接通
5. **`pdf_facets` ingest opening** — brandspec_5dim 已預留 STUB,等 VLM pipeline 跑完接通

每個新 SOT 加進這份 spec 時用同 5 欄結構 + 9.1-9.5 規範。

---

## 附錄: 2026-05-16 落地的 ingest 改動

- **新加 4 個 SOT**: `dept_keywords.json` / `gt_keywords.json` / `fabric_keywords.json` / `gender_keywords.json` (4 維分類 cascade,放 `data/source/`)
- **新加 2 個 derived runtime**: `dept_lookup_by_subgroup.json` + `gender_lookup_by_subgroup.json` (Step 4e from `client_canonical_mapping.json`)
- **新加 1 個 SOT 域**: `customer_terminology` (Source-Data/做工翻譯/ → 2 個 runtime JSON via `build_customer_terminology.py`)
- **schema 升級**: `canonical_aliases.json` v1 → v2 (短碼→alias list)
- **新加 resolver module**: `scripts/lib/resolve_classification.py` (4 維分類統一查表)
- **CI step 加**: Step 4e `build_dept_lookup_by_subgroup.py` (從 client_canonical_mapping export 2 個 runtime lookup)
