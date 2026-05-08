# StyTrix Techpack 完整資料架構 v3.0

> **目標**：建立一條從**所有資料源 → 統一 master → 多個 view** 的可持續架構，支援：
> - **聚陽內部用**：分客戶五階 IE 報價（看 brand × L1 × L2 × L3 × L4 × L5 + IE 秒值）
> - **外部設計師用**：StyTrix Techpack Creator 做工單（看 5-dim consensus + ISO + methods）
>
> **核心原則**：
> 1. **Single source of truth, multiple views** — 兩個用途**同一份 database，不同讀取方式**
> 2. **跑出來的資料都是補充進 master 的，不是 master 本身**
> 3. **規則（Bible）vs 真實資料（Source）嚴格分開**
> 4. **Maximize info 整合**（不 cascade fallback，整合各 source 的所有可用欄位）
> 5. M7 Pipeline 是 platform pipeline 的**第 7 個 source**（不是另一條獨立 pipeline）
> 6. **POM (尺寸表) 是獨立 pipeline**，跟做工不交集（除 bucket_taxonomy.json）
>
> **作者**：@elly | **日期**：2026-05-08 v3.0 | **狀態**：design v3.0（fetch 跑完後實作）

---

## v3.0 改動（vs v2）

| 議題 | v2 | **v3** |
|---|---|---|
| 命名 | L1/L2/L3/L4 layer | **Step 1/2/3/4**（避免跟五階 L1-L5 撞名）|
| 「設計師上傳」 | 寫在 doc 裡 | **移除** — `data/ingest/uploads/` 是後端 admin 上傳處理好的檔，不是設計師 |
| Bibles 範圍 | 只列五階字典 / ISO 等 | **完整列**：L1-L5 視覺規則合併進五階定義；補中英對照；補客戶 metadata 標準 |
| construction_bridge_v6 | 列 Bible | **移到 Source**（會被新 design 補入）|
| iso_lookup v4 vs v4.3 | cascade fallback | **整合最大化**（v4 + v4.3 + m7_pullon merge 成 v5）|
| 5 階 CSV per EIDH | 列 raw | **retire**（跟 m7_detail.csv 重疊）|
| 客戶 metadata mapping | v1 + v2 兩份 | **合併成 v3**（一份檔含 ground truth + PDF field mapping）|
| build_master_v7.py | 命名誤導（M7 端產 master）| **重命名 build_m7_pullon_source.py**（產 source #7，不是 master）|

---

## 0. 完整 Bibles（規則資料 / 永久 reference / 不會被新 design 補入）

| Bible 群 | 內含檔 / Excel | 用途 |
|---|---|---|
| **五階定義**（L1-L5 + VLM 視覺規則） | `data/zone_glossary.json:L1_STANDARD_38` + `data/l1_standard_38.json` + `五階層部位.xlsx` + `L1_部位定義_Sketch視覺指引.md` + `data/l2_visual_guide.json` + `data/l2_decision_trees.json` + `L2_VLM_Decision_Tree_Prompts_v2.md` + `L2_Visual_Differentiation_FullAnalysis_修正版.md` + `L2_代號中文對照表.xlsx` + `五階層展開項目_YYYYMMDD.xlsx` → `l2_l3_ie/<L1>.json` 38 檔 | 38 L1 部位 + 282 L2 零件 + VLM 判定規則 + 1117 L3 形狀 + L4 工法 + L5 細工段 + IE 標準秒值 |
| **ISO 機種** | `data/iso_dictionary.json` + `ISO對應五階層機種.xlsx` + `data/zone_glossary.json:ISO_TO_*` | ISO ↔ EN canonical / ZH method / 機種 |
| **客人 callout glossary** | `ISO_客人縫法對照表_Glossary.xlsx` + `data/zone_glossary.json:KW_TO_L1_TOPS/BOTTOMS/ZH_ZONE_TO_L1` + `techpack-translation-style-guide.md` | 13 客人寫法 → L1 router + 中英術語統一 |
| **客戶 metadata 標準**（v3 合併版） | `data/client_canonical_mapping.json`（v3 合併 v1 + v2）| 22 客戶 subgroup_codes + 4 維 ground truth (gender/dept/fabric/category) + PDF field mapping |
| **POM 字典**（POM 用，做工不碰）| `data/pom_dictionary.json` | POM 代號 ↔ 中英對照 |
| **Bucket 分類**（做工 + POM 共用）| `data/runtime/bucket_taxonomy.json` | 59 bucket schema |

---

## Step 1 — Raw 收集（真實 design 資料 / 持續補入）

### A. YY 系統導出（五階相關）

| 檔 | 來源 | 截取方式 | 一筆 = |
|---|---|---|---|
| `m7_report.jsonl` | nt-net2 ASP.NET | `fetch_m7_report_playwright.py` Playwright CDP | per design 整體摘要（IE 工時 / 機種 / flag / **five_level_detail[]**）|
| `m7_detail.csv` | nt-netsql2 SSRS | `fetch_m7_detail.py` HTTP NTLM CSV export | per sub-operation × machine_name × Skill_Level × second |
| `M7列管_YYYYMMDD.xlsx` | YY 系統 export | 手動 download → Source-Data/ | per design metadata（eidh / 客戶 / 報價款號 / Subgroup / TP資料夾 / Sketch URL / W/K / Item / Program / PRODUCT_CATEGORY / 42 columns）|

> ⛔ `5 階 CSV per EIDH` 已 **retire**（資料跟 m7_detail.csv 重疊）

### B. Sample Schedule（Techpack 相關）

**真實 raw**（從哪來）：

| 檔 | 來源 | 截取方式 |
|---|---|---|
| 客戶 PDF Techpack | SMB `\\nas\share\TP\<EIDH>\<TP folder>\*.pdf` | `2_fetch_tp.ps1` robocopy 按 M7 索引「TP資料夾」欄拉 |
| 客戶 PPTX 中文翻譯（聚陽 IE 翻過的）| 同 SMB | 同上 |
| 客戶 sketch | M7 Sketch 表 URL | `1_fetch.py` requests download |

**從這些 raw 抽什麼**（Step 1 → Step 2 之間）：

| 檔類型 | 抽什麼 | 用什麼方式 | 抽出的內容 |
|---|---|---|---|
| 客戶 PDF（cover）| 設計 metadata | `extract_pdf_metadata.py` PyMuPDF + Centric 8 schema | season / dept / category / sub_category / brand_division / fit_camp / rise / collection |
| 客戶 PDF（text-layer）| callout 文字 | `append_pdf_text_facts.py` PyMuPDF + KW_TO_L1 router | (zone, ISO, method, raw_line) → `pdf_text_facts.jsonl` |
| 客戶 PDF（圖層 image-only）| callout 圖中文字 | `vlm_fallback_api.py` Claude Vision API + KW_TO_L1 router | (zone, ISO, method, page_num) → `vision_facts.jsonl` |
| 客戶 PPTX | 中文 callout | `extract_unified_m7.py` python-pptx + ZH_ZONE_TO_L1 router | (中文 zone, ISO, 中文 method, raw_text) → `facts.jsonl` |
| 客戶 sketch | 視覺資料 | （目前只 download，給未來 VLM 訓練）| design 圖檔本身 |

### C. Platform 既有 raw（已存 platform repo）

| 檔 | 內容 | 是否會持續補入 |
|---|---|---|
| `data/ingest/uploads/*.{pdf,pptx,xlsx}` | 後端 admin 透過 GitHub PAT 上傳的客戶資料 | ✅ 持續補入 |
| `data/ingest/consensus_v1/entries.jsonl` | 275 條人工驗證 same_bucket 規則 | ✅ |
| `data/ingest/consensus_rules/` | OCR 整合規則 | ✅ |
| `data/ingest/ocr_v1/` | 1202 OCR facts | ✅ |
| `data/ingest/construction_by_bucket/` | 688 設計外部資料源 | ✅ |
| `data/construction_bridge_v6.json` | 跨設計 GT × zone × ISO bridge | ✅ |
| `recipes/*.json` (71 檔) | same_sub_category 統計 | ✅（新 sub-category 加） |
| `General Model_Path2/iso_lookup_factory_v4.3.json` | 230 entries (Dept × Gender × GT × L1) | ✅（會被 v5 整合）|
| `General Model_Path2/iso_lookup_factory_v4.json` | 282 entries (Fabric × Dept × GT × L1) | ✅（會被 v5 整合）|

### D. POM Raw（**獨立 pipeline，⛔ 不交集**）

| 檔 | 內容 |
|---|---|
| `mc_pom_*.jsonl` | Centric 8 PDF 抽 |
| ONY 完整 PDF | 客戶端 |
| `pom_rules/*.json` (81 檔) | `scripts/reclassify_and_rebuild.py` 線下產出 |

### 補入機制（誰補都可以）

❌ **不是設計師上傳**

✅ 三條路徑（給內部 / agent / 後端用）：
1. **GitHub commit + push**（git push 進 ingest/ 子目錄觸發 workflow）
2. **線上 admin 上傳到 `data/ingest/uploads/`**（透過 `api/ingest_token.js` 拿 PAT 直連 GitHub）
3. **後端 M7 Pipeline 跑完 push**（push 到 `data/ingest/m7_pullon/`）

**規格化產出**：每 source 產 entries.jsonl 對齊 platform schema，不限產出單位（IE / 業務 / 製樣中心 / agent / fetch script）。

---

## Step 2 — 整合（用 Bibles 對照成 normalized entries.jsonl）

把 Step 1 raw 資料**用 Bibles 對照**成統一 schema，產 source entries：

```
Raw → 用 Bibles 對照 → Source entries.jsonl
```

對照規則：
- callout zone → `KW_TO_L1_*` router → L1 code
- ISO → `iso_dictionary` → canonical EN
- 客戶 (client, subgroup) → `client_canonical_mapping.json` → 4 維 (gender/dept/fabric/category)
- 五階 step → `五階字典` → 標準 L1/L2/L3/L4/L5 code

產出 7 個 source（platform 端 + M7 端）：

| # | Source | 在 platform 哪裡 | 怎麼產 |
|---|---|---|---|
| 1 | `recipe` | `recipes/*.json` (71) | 手動編輯 |
| 2 | `consensus_v1` | `data/ingest/consensus_v1/entries.jsonl` | OCR + facts 整合（人工驗證） |
| 3 | `facts_agg` | 動態算 `data/ingest/*/facts.jsonl` | `extract_unified.py` 跑 |
| 4 | `iso_lookup` (v4 + v4.3 整合) | `General Model_Path2/iso_lookup_factory_*.json` → 整合進 master | **v3 改：v4 + v4.3 maximize merge** |
| 5 | `bridge` | `data/construction_bridge_v6.json` | （持續補入的整合資料）|
| 6 | `m7_pullon` ★ | `data/ingest/m7_pullon/entries.jsonl` | **M7 端 `build_m7_pullon_source.py` 產，git push 進來** |
| 7 | `consensus_rules / ocr_v1 / construction_by_bucket` | data/ingest 子目錄 | 既有 |

---

## Step 3 — 分析（按平台需求 cascade merge + aggregate + maximize info 整合）

### Step 3a：build_recipes_master.py — 7 source merge cascade

```python
all_entries = []
all_entries += build_from_recipes(...)        # 1
all_entries += build_from_consensus(...)      # 2
all_entries += build_from_facts_agg(...)      # 3
all_entries += build_from_iso_lookup_merged() # 4 ★ v4 + v4.3 整合最大化
all_entries += build_from_bridge(...)         # 5
all_entries += build_from_m7_pullon(...)      # 6 ★ M7 source
all_entries += build_from_other_ingest(...)   # 7

master = run_cascade(all_entries)  # cascade: same_sub → same_bucket → same_gt → general → cross_design
```

### Step 3b：Maximize Info 整合策略（**關鍵改動**）

不 cascade fallback，**同 5+1 維 key 合多 source 欄位**：

| Key | 維度 |
|---|---|
| 5+1 維 | gender × dept × gt × it × **fabric** × l1 |

**整合規則**（同 key 多 source 提供時）：

| 欄位 | 取值規則 | source 提供者 |
|---|---|---|
| `iso_distribution` | merge 各 source 票數，標記每 ISO 來源 | m7_pullon + v4.3 + v4 + facts_agg |
| `iso_zh` | 取現有值（v4 主）| v4 |
| `machine` | 取現有值（v4 主）| v4 |
| `methods` | m7_pullon ground truth | m7_pullon |
| `client_distribution` | m7_pullon | m7_pullon |
| `by_client` | m7_pullon（給聚陽 view B 用）| m7_pullon |
| `ie_total_seconds` | m7_pullon | m7_pullon |
| `n_total` | sum 各 source | all |
| Gender 維度 | v4.3 + m7 都有就用，v4 沒就**新建** entry |  |
| Fabric 維度 | v4 + m7 都有就用，v4.3 沒就**新建** entry | |
| `sources_merged` | array 含所有 contribute source | all |
| `confidence` | 依 n_total + source 數量算 | computed |

### Step 3c：Output

`data/master.jsonl` ★ single source of truth（**做工 only**，不含 POM）

每筆 entry schema：

```json
{
  "key": {
    "gender": "WOMENS",
    "dept": "ACTIVE",
    "gt": "PANTS",
    "it": "LEGGINGS",
    "fabric": "KNIT",
    "l1": "WB"
  },
  "n_total": 1186,
  "sources_merged": ["m7_pullon", "v4.3", "v4"],
  "confidence": "high",
  
  // 通用模型 view 用
  "iso_distribution": [
    {"iso": "301", "n": 552, "pct": 46.5, "from": ["m7_pullon", "v4.3"]}
  ],
  "iso_zh": "車縫",
  "machine": ["平車", "lockstitch"],
  "methods": [{"name": "Lockstitch", "n": 552, "pct": 35.2}],
  "client_distribution": [{"client": "ONY", "n": 230, "pct": 19.4}],
  
  // 聚陽 view 用
  "by_client": {
    "ONY": {
      "n_designs": 230,
      "knit": [
        {"l2": "鬆緊腰", "shapes": [{"l3": "1.5\" 鬆緊", "methods": [{"l4": "車縫類", "steps": [["L5 細工段", "skill_B", 42.9, "主"]]}]}]}
      ],
      "woven": [...]
    }
  },
  "ie_total_seconds": 42.9,
  
  // 共用
  "design_ids": ["D97929", "D63529"],
  "embedding_text": "WOMEN ACTIVE PANTS LEGGINGS WB 腰頭 ...",
  
  "_metadata": {
    "last_updated": "2026-05-08T...",
    "build_version": "v3"
  }
}
```

---

## Step 4 — 抽取（每用途一個 view 模板）

從 `master.jsonl` 抽各用途子集：

| View | 檔 | UI 用途 | 從 master 抽什麼 |
|---|---|---|---|
| **A** | `data/recipes_master.json` | 通用模型 ISO consensus | drop `by_client` / `ie_total_seconds`，輕量化 |
| **B** | `l2_l3_ie_by_client/<L1>.json` (26 檔) | 聚陽模型 + brand 五階 | regroup by L1 + brand，含 `by_client` + IE 秒值 + machine + skill |
| **C** | `l2_l3_ie/<L1>.json` (38 檔) | 聚陽通用五階字典 | drop brand 維度，merge by L1，含 L2-L5 |

衍生 script：
- `derive_view_recipes.py`（master → view A）
- `derive_view_by_client.py`（master → view B）
- `derive_view_l2_l3_ie.py`（master → view C，取代從 xlsx 直 build）

---

## 完整 4 步流程圖

```
                    Bibles（規則資料，永久 reference）
                    ┌────────────────────────────────────────┐
                    │ 五階定義（L1-L5 + VLM 視覺規則）         │
                    │ ISO 機種對照                             │
                    │ 客人 callout glossary                    │
                    │ 客戶 metadata 標準（v3）                 │
                    │ POM 字典 / Bucket 分類                   │
                    └────────────────────────────────────────┘
                                      │ 對照用
                                      ↓
┌──────────── Step 1 — Raw 收集 ─────────────┐
│ YY 系統:                                     │
│   m7_report.jsonl / m7_detail.csv / M7列管   │
│ Sample Schedule:                             │
│   客戶 PDF / PPTX / Sketch (SMB)             │
│ Platform 既有:                               │
│   uploads/ / consensus_v1/ / ocr_v1/         │
│   construction_bridge_v6 / recipes/          │
│   iso_lookup_factory_v4 / v4.3               │
│ POM Raw（獨立）:                              │
│   mc_pom_*.jsonl / ONY PDF                   │
└──────────────┬──────────────────────────────┘
               │ Bibles 對照 normalize
               ↓
┌──────────── Step 2 — 整合 ──────────────────┐
│ 7 個做工 source（normalize entries.jsonl）：  │
│   1. recipe                                  │
│   2. consensus_v1                            │
│   3. facts_agg                               │
│   4. iso_lookup (v4 + v4.3 maximize merge)   │
│   5. bridge                                  │
│   6. m7_pullon ★（M7 端產 + push）           │
│   7. consensus_rules / ocr_v1 / etc          │
│                                              │
│ POM 走獨立 pipeline (scripts/reclassify_*)   │
└──────────────┬──────────────────────────────┘
               │ build_recipes_master.py cascade + maximize
               ↓
┌──────────── Step 3 — 分析（Master）─────────┐
│ data/master.jsonl ★ Single Source of Truth  │
│ (做工 only)                                   │
│                                              │
│ 每 entry: 5+1 維 key + ISO + methods +       │
│           by_client + ie_seconds + design_ids│
│ sources_merged 標記欄位來源                   │
└──────────────┬──────────────────────────────┘
               │ derive
       ┌───────┼────────┐
       ↓       ↓        ↓
┌──── Step 4 — 抽取（Views）─────────┐
│  A. recipes_master.json (通用)      │
│  B. l2_l3_ie_by_client/* (聚陽brand)│
│  C. l2_l3_ie/* (聚陽通用)           │
│                                    │
│  POM 自己的 view:                   │
│  pom_rules/* / gender_gt_pom_rules │
│  (走獨立 pipeline 不在這條)          │
└──────────────┬─────────────────────┘
               ↓
       ┌────────┴─────────┐
       ↓                  ↓
   通用模型 UI         聚陽模型 UI
  (view A + ISO)    (view B + view C)
```

---

## ⛔ Scope Boundary — 做工 vs POM

| 做工 ✅（這份架構）| POM ⛔（獨立 pipeline）|
|---|---|
| Step 1: m7_report / facts / uploads / bridge | Step 1: mc_pom / ONY PDF |
| Step 2: 7 個 source 進 build_recipes_master | Step 2: scripts/ 線下產線（reclassify_and_rebuild） |
| Step 3: data/master.jsonl | Step 3: pom_rules/* (81 buckets) — 無 master 概念 |
| Step 4: recipes_master / l2_l3_ie / by_client | Step 4: pom_rules/<bucket>.json 直接給 UI |

**Cross-cut layer：MK Metadata（雙方共用 master schema）**：
- `data/client_canonical_mapping.json` (v3) — 客戶 × subgroup → 4 維 ground truth
- `data/zone_glossary.json` — L1 部位 + Callout zone router
- `data/iso_dictionary.json` — ISO ↔ EN/ZH/機種
- `data/runtime/bucket_taxonomy.json` (v4) — **從 MK 推導**（不再 hand-curate），4 維 key 做工 + POM 共用

**bucket_taxonomy v4 直接重寫**（不慢慢 retire）：
- 來源：`generate_bucket_taxonomy_from_mk.py` 跑 MK Metadata cartesian product 過濾
- 4 維 key：`<gender>_<dept>_<gt>_<it>`
- 做工用 6 維（+ fabric + l1），POM 用 4 維 prefix
- 詳見 [`MK_METADATA.md`](./MK_METADATA.md)

---

## 變更歷史

| 版本 | 日期 | 重點 |
|---|---|---|
| v1.0 | 2026-05-07 | 初版，提出 single source + multi-view 概念 |
| v2.0 | 2026-05-08 | M7 端 master / 平台端 master 釐清 → 確認在 platform 端 |
| **v3.0** | **2026-05-08** | **Step 1/2/3/4 命名 / Bibles 完整列表 / Maximize info 整合 v4+v4.3+m7 / 客戶 metadata v3 合併 / 移除「設計師上傳」字眼** |

---

*作者：@elly | v3.0 | fetch 跑完後實作 | 範圍：⛔ 只動做工，POM 不碰*
