# M7 PullOn Pipeline — 從 4 個資料源蒸餾出跨客戶做工共識

> **一頁總結**：1180 件 PullOn 褲款 × 4 個資料源（客戶 PDF/PPTX + 聚陽 nt-net2 / nt-netsql2）→ 自動抽取 → 標準化 → 跨客戶共識 →
> - **`recipes_master.json` 247 platform recipes**（5-dim canonical key，跨 brand 共識）
> - **`l2_l3_ie_by_client/<L1>.json` 26 個檔**（10 brand × knit/woven 各自完整五階工法樹）
>
> 平台 RAG / IE 報價系統直接吸；聚陽模式選 brand 直接撈 brand-specific 五階。
>
> **最後更新**：2026-05-08 | **版本**：v8（PDF per-client metadata 抽取 + 8 canonical multi-source consensus + alias normalizer + 自動 push 到 platform）

---

## 目錄

1. [問題：為什麼非做這條 pipeline 不可](#1-問題)
2. [架構：Phase A–F 蒸餾邏輯](#2-架構)
3. [資料夾：single source of truth](#3-資料夾)
4. [Deliverable：數字快照](#4-deliverable)
5. [與 StyTrix Techpack Creator 銜接](#5-銜接)
6. [SOP：一鍵跑 + 增量更新](#6-sop)
7. [失敗排查](#7-失敗排查)
8. [檔案結構 / 共用模組](#8-檔案結構)
9. [Coding 約定](#9-coding-約定)
10. [已知限制 / Phase H 規劃](#10-限制)
11. [變更歷史](#11-變更歷史)

---

## 1. 問題

### 1.1 聚陽 IE 部門面對的 4 個資料黑洞

| 資料源 | 內容 | 痛點 |
|---|---|---|
| 客戶 Techpack（PDF / PPTX） | 設計師 callout（"ISO 401 三本雙針"）| 散在 SMB 1181 個資料夾、PDF / PPTX 混雜、英中文格式各異、callout 常在圖層（text-layer 抽不到，要 VLM）|
| 聚陽 PPTX 中文翻譯檔 | IE 中文展開的 callout | 已 normalize 但跟客戶 PDF 沒自動對齊 |
| 聚陽 M7 五階摘要（nt-net2）| 報價總額 / IE 工時 / 機種 / flags | 散在內網 ASP.NET 系統，須手動逐筆查 |
| 聚陽 M7 細工段（nt-netsql2 SSRS）| sub-operation × machine_name × Skill_Level | 需 NTLM 認證 + SSRS CSV export |

### 1.2 核心問題

- ❌ 業務報新單憑經驗估秒值（無共識資料）
- ❌ 跨客戶（A&F、GAP、ONY、BY、ATH 等 10 brand）同部位做工差異未知
- ❌ 設計意圖（ISO）vs 量產實做（machine_name）落差無對照
- ❌ 1180 件 PullOn 工時 / 機種 / 工序資料躺在 4 個系統互不通

### 1.3 平台需要的 RAG schema

```json
{
  "key": {"gender": "WOMENS", "dept": "GENERAL", "gt": "LEGGINGS", "it": "LEGGINGS", "l1": "WB"},
  "iso_distribution": [{"iso": "301", "n": 2178, "pct": 46.7}],
  "methods": [{"name": "Lockstitch", "n": 2178, "pct": 35.2}],
  "n_total": 1186, "confidence": "high"
}
```

舊版 2-dim bucket schema 平台無法吸；v7 對齊平台 5-dim canonical key（gender / dept / gt / it / l1，wk merge 進 entries）。

---

## 2. 架構

```
[GROUND TRUTH] M7 索引 Excel：1180 EIDH × {客戶, Subgroup, Style#, Item, W/K}
                      │                              │
       CLIENT 端（PDF/PPTX）               MAKALOT 端（內網）
              │                                     │
       Phase A: SMB 拉檔                    Phase A2: 抓內網
       2_fetch_tp.ps1                       fetch_m7_report_playwright（nt-net2 CDP）
       3_reorganize.py                      fetch_m7_detail.py（nt-netsql2 SSRS）
              └─────────────────┬────────────────────┘
                                ▼
                      Phase B: 分類 + 統一資料夾
                      3_reorganize.py / sync_ppt_tp.py
                      → m7_organized_v2/ 統一單一資料源 (★ v7 新增)
                                ▼
                      Phase C: 抽 callout（4 源）
                      C1 PDF cover metadata                (~248 design)
                      C2 PPTX 中文 callout（主源）          ~70%
                      C3 PDF text-layer                    ~13%
                      C4 Claude Vision API（image-only）   ~5%
                                ▼
                      Phase D: 對齊 + JOIN
                      align_to_ie_m7（facts ↔ IE 共識）
                      enrich_dim（designs + m7_report JOIN）
                                ▼
                      Phase E: Platform Recipes ⭐
                      build_recipes_master_v6.py
                        → recipes_master_v6.jsonl (551 entries / 6-dim)
                      convert_to_platform_schema.py
                        → recipes_master_platform.json (247 entries / 5-dim)
                      build_client_specific_l2_l3_ie.py
                        → l2_l3_ie_by_client/<L1>.json (26 檔 / 10 brand × knit/woven)
                                ▼
                      Phase F: Audit / 驗證
                      show_vlm_status.py / merge_into_platform_repo.py
```

### 2.1 Phase 細節

| Phase | 做什麼 | 主要 script |
|---|---|---|
| **A** | PowerShell `robocopy` 按 M7 索引 TP 路徑從 SMB 拉到本機 | `2_fetch_tp.ps1` |
| **A2-1** | nt-net2 五階摘要：Playwright CDP attach Chrome 9222 + JS evaluator 抓 span | `fetch_m7_report_playwright.py` |
| **A2-2** | nt-netsql2 SSRS：HTTP + NTLM + `&rs:Format=CSV` 直接 export | `fetch_m7_detail.py` |
| **B** | 按副檔名分到 `pdf_tp/` / `ppt_tp/`；補漏 copy | `3_reorganize.py` / `sync_ppt_tp.py` |
| **C1** | 抽 PDF cover metadata（**v8 改 per-client adapter,7 parser × 11 客戶,輸出 8 canonical**)| `extract_pdf_metadata.py` |
| **C2** | 抽 PPTX 中文 callout | `extract_unified_m7.py` |
| **C3** | 抽 PDF text-layer callout | `append_pdf_text_facts.py` |
| **C4** | Claude Vision API 補 image-only PDF（**v7 加 image pre-process**）| `vlm_fallback_api.py` |
| **C5** | **(v8 新)** 8 canonical multi-source consensus(M7 列管 + PDF + 推論)+ alias normalize | `lib/consolidate_canonical.py`(被 `build_m7_pullon_source_v3.py` import)+ `data/canonical_aliases.json` |
| **D** | 每筆 fact 查對應 EIDH 的 IE CSV；designs + m7_report JOIN | `align_to_ie_m7.py` / `enrich_dim.py` |
| **E** | 5-dim consensus + JOIN m7_detail sub-op + EN canonical | `build_recipes_master_v6.py` |
| **E2** | 6-dim → 5-dim wk merge | `convert_to_platform_schema.py` |
| **E3** | brand-specific 完整五階樹 | `build_client_specific_l2_l3_ie.py` |
| **E4** | **(v8 新)** per-EIDH 完整履歷 + canonical block | `build_m7_pullon_source_v3.py` |
| **F** | callout coverage / consensus 驗證 | `show_vlm_status.py` / `audit_*.py` / `report_canonical_coverage.py` / `report_canonical_consensus.py` |
| **F2** | **(v8 新)** 推 designs/entries 到 `stytrix-techpack` repo(自動 gzip + copy)| `push_m7_pullon_to_platform.py` |

---

## 3. 資料夾

### 3.1 v7 統一 single source of truth

**2026-05-07 重整**：所有 callout / facts / manifest 統一到 `M7_Pipeline/m7_organized_v2/`，舊位置 `stytrix-pipeline-Download0504/data/ingest/` 改為 read-only legacy fallback。

```
M7_Pipeline/m7_organized_v2/   ← ★ single source of truth
├── callout_images/             1263 PNG / 608 MB（Phase C 產出）
├── callout_manifest.jsonl      3802 entries / 476 unique designs
├── designs.jsonl               PDF metadata（season / dept / vendor / wk）
├── facts.jsonl                 統一 fact 資料（PPTX + PDF text）
├── pdf_text_facts.jsonl        PDF text-layer facts
├── vision_facts.jsonl          ★ VLM 抽取結果（v7 168 新 facts）
├── pdf_tp/                     PDF 原檔（Phase A 拉下來）
├── ppt_tp/                     PPTX 原檔
├── aligned/facts_aligned.jsonl IE 對齊後的 facts
├── csv_5level/                 五階 CSV（每 EIDH 一檔）
├── sketches/                   sketch 縮圖
└── inventory.csv               資產盤點
```

### 3.2 路徑優先序（所有腳本）

```python
ROOT = Path(__file__).resolve().parent.parent
M7_ORG = ROOT / "m7_organized_v2"           # primary
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback

# 自動切換：m7_organized_v2 有檔就讀那邊，否則 fallback DL
MANIFEST = M7_ORG / "callout_manifest.jsonl" if (M7_ORG / "callout_manifest.jsonl").exists() else DL / "data" / "ingest" / "pdf" / "callout_manifest.jsonl"
```

寫入永遠寫 `m7_organized_v2/`，不寫回 legacy。

---

## 4. Deliverable

### 4.1 數字快照（v7 / 2026-05-07）

| 資產 | 量 | 變化 |
|---|---|---|
| sub-operations 結構化 | 65,803 筆 | — |
| 五階 step（含 IE 秒值）| 30,323 筆 | — |
| PDF callout facts | **3,344 筆** | 含 VLM 369 facts |
| Facts unique designs (vision) | **109** | 之前 32（+77）|
| recipes_master_v6.jsonl | **551 entries / 6-dim** | 之前 470（+81）|
| Platform recipes | **247 entries / 5-dim** | 之前 197（+50）|
| **LEGGINGS** | **61** | 之前 9（×6.7）|
| by_client 五階檔 | **26 L1 檔** | 10 brand × knit/woven |
| Confidence | high 56 / med 48 / low 72 / very_low 71 | — |

### 4.2 Brand stats（by_client）

| Brand | designs | steps | IE seconds |
|---|---:|---:|---:|
| TGT | 266 | 7,109 | 519,499 |
| ONY | 230 | 5,122 | 364,937 |
| GAP | 139 | 2,914 | 182,316 |
| DKS | 116 | 3,489 | 257,789 |
| ANF | 80 | 1,196 | 75,911 |
| ATH | 67 | 1,880 | 165,661 |
| KOH | 67 | 1,789 | 131,339 |
| UA | 54 | 1,846 | 154,155 |
| GU | 37 | 1,406 | 115,516 |
| BY | 26 | 695 | 63,502 |

---

## 5. 銜接

```
[Training]  sketches/{eidh}.jpeg + csv_5level/{eidh}.csv
              → VLM/CLIP supervised → 學「sketch → L1/L2/L3 + recipe」

[Inference] 設計師 sketch
              → Stage 1 VLM 部位辨識（identifyL1）
              → Stage 2 VLM L2 decision tree（identifyL2）
              → Stage 3 查 recipes_master.json 拿 ISO consensus（通用模型）
                 OR 查 l2_l3_ie_by_client/<L1>.json[brand] 拿真實五階（聚陽模型 + 選 brand）
              → Stage 4 業務報價
```

兩個 deliverable：
1. **跨客戶 consensus**（`recipes_master.json` 247 entries）— Inference 時查 typical_recipe，通用模型用
2. **brand-specific 五階**（`l2_l3_ie_by_client/<L1>.json` 26 檔）— 聚陽模型選 brand 後撈該 brand 真實 L2/L3/L4/L5 + IE 秒值

**沒這條 pipeline，Techpack Creator 沒 RAG 知識庫，等於空殼。**

---

## 6. SOP

### 6.1 一鍵跑全 Pipeline

```powershell
cd M7_Pipeline

# Step 1: 拉最新 M7 索引
cp "\\nas\share\M7列管*.xlsx" .

# Step 2: Phase A + A2
.\scripts\2_fetch_tp.ps1
python scripts\fetch_m7_report_playwright.py
python scripts\fetch_m7_detail.py

# Step 3: Phase B - 分類
python scripts\3_reorganize.py
python scripts\sync_ppt_tp.py

# Step 4: 統一資料源（v7 新增，第一次跑或補資料時用）
.\scripts\migrate_to_m7_organized.ps1

# Step 5: Phase C - 抽 callout
python scripts\extract_pdf_metadata.py --client "ONY,ATHLETA,GAP,GAP_OUTLET,DICKS,TARGET,KOHLS,A_&_F,GU,CATO,BR"
#  ↑ v8 起改 per-client adapter,輸出 outputs/platform/pdf_metadata.jsonl(8 canonical 欄位)
python scripts\extract_raw_text_m7.py --output-dir m7_organized_v2 --pdf-only --force
python scripts\extract_unified_m7.py
python scripts\append_pdf_text_facts.py

# Step 6: VLM 補 image-only PDF（需 ANTHROPIC_API_KEY）
python scripts\vlm_fallback_api.py --from-manifest --skip-existing --append --model sonnet

# Step 7: Phase D - 對齊
python scripts\align_to_ie_m7.py
python scripts\enrich_dim.py

# Step 8: Phase E - 產 recipes + per-EIDH 履歷
python scripts\build_recipes_master_v6.py
python scripts\convert_to_platform_schema.py
python scripts\build_client_specific_l2_l3_ie.py
python scripts\build_m7_pullon_source_v3.py
#  ↑ v8 起讀 pdf_metadata.jsonl + canonical_aliases.json 加 canonical block

# Step 9: Phase F - 驗證(canonical coverage / consensus 報告)
python scripts\report_canonical_coverage.py     # PDF 端 8 canonical coverage
python scripts\report_canonical_consensus.py    # M7+PDF consensus + 衝突 audit list
python scripts\show_vlm_status.py
python scripts\merge_into_platform_repo.py --diff-only
python scripts\merge_into_platform_repo.py --mode replace --apply

# Step 10: Phase F2 - 推 designs/entries 到 stytrix-techpack repo (v8 新)
python scripts\push_m7_pullon_to_platform.py --dry-run   # 先看 SRC/DST 對不對
python scripts\push_m7_pullon_to_platform.py             # 正式 copy + gzip
```

### 6.2 增量更新（只跑變動部分）

```powershell
# 改 derive_metadata 規則 / dept mapping → 只重產 recipes
python scripts\build_recipes_master_v6.py
python scripts\convert_to_platform_schema.py

# 改 ZH_NORMALIZE 規則 → 只重產 by_client
python scripts\build_client_specific_l2_l3_ie.py

# 補上傳新 client PDF → 重建 manifest + 重跑 VLM
.\scripts\rebuild_manifest.ps1
python scripts\vlm_fallback_api.py --from-manifest --skip-existing --append
```

### 6.3 derive_metadata 五段 fallback

| 優先序 | 規則 | 涵蓋 |
|---|---|---|
| 1 | `_GENDER_TOKENS` from Style# / Subgroup（MENS/MISSY/BOY/GIRL/KIDS）| ~60% |
| 2 | `_CLIENT_DEFAULT_GENDER`（BEYOND YOGA/ATHLETA/CALIA → WOMEN）| ~15% |
| 3 | `_CLIENT_DEFAULT_DEPT` 17 客戶 ACTIVE / RTW 對照 | ~10% |
| 4 | M7 索引 Excel `subgroup` 欄位 + `client_metadata_mapping.json` | ~12% |
| 5 | UNKNOWN（skip）| ~3% |

### 6.4 derive_item_type 強化（v7 新增 / Task #3）

| 優先序 | 規則 | 例子 |
|---|---|---|
| 1 | 顯式 keyword（design_id / program / item / subgroup）| `LEGGING` / `TIGHT` / `JOGGER` / `SWEATPANT` / `SHORT` / `BIKE` / `CAPRI` / `SKIRT` |
| 2 | Subgroup heuristics → LEGGINGS | `COMPRESSION` / `BUTTERSOFT` / `POWERSOFT` / `STUDIOSMOOTH` / `ALL DAY` / `FLX` |
| 3 | Active brand prior → LEGGINGS | `BEYOND YOGA` / `ATHLETA` / `UNDER ARMOUR` / `CALIA` + `dept=ACTIVE` |
| 4 | fallback PANTS | — |

效果：LEGGINGS 從 9 → 61（×6.7）

### 6.5 中文 Normalize（v7 新增）

`build_client_specific_l2_l3_ie.py:ZH_NORMALIZE` 修簡體 / 誤字：

| 誤字 | 正字 | 來源 |
|---|---|---|
| 檔底片 | 襠底片 | m7_report 31 筆簡體 / 輸入法錯 |
| 褶底片 | 襠底片 | AI hallucinate fallback |

規範：「**襠**」(crotch piece) 是身體部位；「**檔**」是 POM measurement context（Rise/前檔/後檔）；「**褶**」是 pleat / dart。做工 callout 用「襠」。

### 6.6 新客戶加入流程

1. M7 索引 Excel 加新筆 EIDH
2. `m7_constants.py:CUSTOMER_TO_CODE` 加客戶縮寫
3. `data/client_metadata_mapping.json` 補 (client, subgroup) → gender / dept
4. `build_recipes_master_v6.py:derive_item_type` 視需要加 client-specific prior
5. 跑 Pipeline 全流程
6. 確認 `show_vlm_status.py` + `convert_to_platform_schema.py` 數字合理

### 6.7 改字典只改 JSON（不改 .py）

- `data/zone_glossary.json` — L1 部位 / ISO ↔ ZH method / KW → L1
- `data/iso_dictionary.json` — ISO ↔ EN canonical / machine name
- `data/client_metadata_mapping.json` — 客戶 subgroup_codes

---

## 7. 失敗排查

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| Phase A 卡住 | 不在內網 / SMB 路徑變 | 連聚陽 VPN；更新 M7 索引 TP 路徑欄 |
| `ModuleNotFoundError: fitz` | 沒裝 PyMuPDF | `pip install pymupdf` |
| `ModuleNotFoundError: anthropic` | Vision API 才需要 | `pip install anthropic` |
| `ModuleNotFoundError: PIL` | v7 image pre-process 需要 | `pip install pillow` |
| Playwright `connect_over_cdp` 失敗 | Chrome 9222 port 沒開 | `chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome_debug_profile"` |
| Vision API "image exceeds 5 MB" | v7 已自動 resize / recompress | 升級腳本到 v7（`_prepare_image()`）|
| Vision API "image dimensions exceed 8000 pixels" | 同上 | 升級腳本到 v7 |
| Vision API "image cannot be empty" | PNG 損壞 < 1KB | v7 已自動 skip |
| MuPDF `zlib error` / `structure tree` warning | PDF 有壞 stream / accessibility tag 不標準 | **正常 warning，可忽略**；errors 計數才是真壞 PDF |
| facts 數明顯比上次少 | PDF text-layer 沒 cat 進 | `Get-Content pdf_text_facts.jsonl \| Add-Content facts.jsonl` |
| build_recipes_master crash on print | cp950 codec 不認 ✓ | v7 已改 `[Y]` `[N]`；舊版改 `set PYTHONIOENCODING=utf-8` |
| 太多 UNKNOWN bucket | derive_metadata fallback 不夠 | 補 `_CLIENT_DEFAULT_DEPT` / `_GENDER_TOKENS` |
| LEGGINGS 數量不合理低 | derive_item_type 沒命中 | 補 subgroup heuristics 或 active brand prior |
| Vision facts 進不了 build_recipes_master | 路徑常數沒讀 m7_organized_v2 | v7 已修；舊版 hard-code DL 路徑 |

---

## 8. 檔案結構

```
M7_Pipeline/
├── data/
│   ├── zone_glossary.json          ← L1_STANDARD_38, ISO→ZH method
│   ├── iso_dictionary.json         ← ISO ZH/EN canonical + machine
│   ├── client_metadata_mapping.json ← 22 客戶 subgroup_codes
│   └── canonical_aliases.json      ← (v8 新) 8 canonical alias normalize 規則,被 lib/consolidate_canonical.py 讀
│
├── scripts/（30+ 個現役 .py + 3 個 .ps1）
│   ├── shared/pdf_helpers.py / zone_resolver.py / ie_alignment.py
│   ├── lib/consolidate_canonical.py  ← (v8 新) generic multi-source consensus + alias normalizer
│   ├── m7_constants.py / m7_pdf_detect.py
│   │── Phase A: 2_fetch_tp.ps1 / 3_reorganize.py / sync_ppt_tp.py
│   │── Phase A2: fetch_m7_report_playwright.py / fetch_m7_detail.py
│   │── Phase C: extract_pdf_metadata ★ (v8 改 per-client adapter) / extract_raw_text_m7
│   │           / extract_unified_m7 / append_pdf_text_facts / vlm_fallback_api / vlm_fallback_m7
│   │── Phase D: align_to_ie_m7 / enrich_dim / derive_metadata
│   │── Phase E: build_recipes_master_v6 ★ / convert_to_platform_schema
│   │           / build_client_specific_l2_l3_ie ★ / build_m7_pullon_source_v3 ★ (v8 加 canonical block)
│   │── Phase F: show_vlm_status / merge_into_platform_repo / audit_*
│   │           / report_canonical_coverage (v8 新) / report_canonical_consensus (v8 新)
│   │── Phase F2 (v8 新): push_m7_pullon_to_platform.py    auto gzip + copy 到 stytrix-techpack
│   │── Helper（v7 新增）:
│   │       migrate_to_m7_organized.ps1   一鍵搬資料到 m7_organized_v2/
│   │       rebuild_manifest.ps1           套新 detector 重建 manifest
│   │       show_vlm_status.py             VLM pipeline 狀態 + per-client 拆分
│
├── m7_organized_v2/（★ v7 single source of truth）
│   ├── callout_images/        1263 PNG
│   ├── callout_manifest.jsonl 3802 entries
│   ├── designs.jsonl          (legacy, 通用 PDF cover metadata)
│   ├── metadata/designs.jsonl (5/8+ 新位置)
│   ├── facts.jsonl
│   ├── vision_facts.jsonl     ★ VLM 結果（109 designs / 168 facts）
│   ├── pdf_text_facts.jsonl
│   ├── pdf_tp/ ppt_tp/ csv_5level/ sketches/ aligned/
│
├── outputs/platform/ ← ★ Phase E + F deliverable
│   ├── recipes_master_v6.jsonl              551 entries / 6-dim source
│   ├── recipes_master_platform.json         247 entries / 5-dim platform
│   ├── l2_l3_ie_by_client/<L1>.json        26 檔 / 10 brand × knit/woven
│   ├── pdf_metadata.jsonl                  (v8 新) per-client 抽出的 8 canonical raw,1448 件 / 11 客戶
│   ├── m7_pullon_designs.jsonl             (v8 新) per-EIDH 履歷含 canonical block,3900 件 / 78 MB
│   ├── m7_pullon_source.jsonl              (v8 新) aggregated 6-dim,746 entries / 7.2 MB
│   ├── canonical_coverage.txt              (v8 新) PDF 端 8 canonical coverage 報告
│   └── canonical_consensus_report.txt      (v8 新) M7+PDF consensus + 衝突 audit list
│
├── tp_samples_v2/<EIDH>_*/<source>.pdf     (v8 新 Master PDF location, 4644 EIDH 子目錄)
│
└── PIPELINE.md（本檔）/ construction-page-rules.md / techpack-translation-style-guide.md
```

外部相依（**stytrix-pipeline-Download0504/** legacy）：
- `metadata/m7_report.jsonl` ← A2-1 原始輸出（讀，不寫）
- `metadata/m7_detail.csv` ← A2-2 原始輸出（讀，不寫）

---

## 9. Coding 約定

- **編碼**：UTF-8 with BOM（`utf-8-sig`）寫入；Python 讀用 `encoding="utf-8"`
- **Path**：`ROOT = M7_Pipeline/`，`M7_ORG = ROOT / "m7_organized_v2"`，`DL = stytrix-pipeline-Download0504/`，用 `Path(__file__).resolve().parent.parent`
- **路徑常數模式**：primary 路徑 + legacy fallback，寫入永遠寫 primary
- **Imports**：`sys.path.insert(0, str(ROOT / "scripts"))`，不用相對 import
- **Status 寫檔**：`.{name}_state` 存目前 idx，`--reset` 砍 state + output
- **錯誤處理**：HTTP / file 都包 try/except，loop 不停（單筆 err 不影響全流程）
- **改字典只改 JSON**：`data/*.json`，不改 .py 內 dict（會 drift）
- **Console output**：避開 unicode 字元（✓✗🖼️🚫）— Windows cp950 codepage 不認；用 `[Y]` `[N]` `[img]` `[no_img]` 代替
- **PDF parse warning**：MuPDF `zlib error` / `structure tree` 是 warning 非 error，不要當失敗

---

## 10. 限制

### 已知限制

- **PullOn-only**：只 cover Pull-on Pants；其他 GT（TOP/DRESS/OUTERWEAR/SET）待對應 pipeline
- **`it` 維度精度有限**：v7 強化 derive_item_type 後 LEGGINGS 從 9 → 61，但 SHORTS/JOGGERS 仍偏低（Item 欄全是 "Pull On Pants"，沒 ground truth 細分）
- **gender UNKNOWN 仍佔 ~23%**：m7_report 直接抓的 EIDH 多數沒 subgroup
- **iso_distribution ~88% cover**：剩 12% 是純中文 free-form 描述
- **147 EIDH 沒 PPT**：M7 系統就沒上 PPT，無法補
- **VLM hallucinate 風險**（Task #1 後續）：
  - `api/analyze.js:identifyL2` prompt 沒鎖死 vocabulary，model 可能輸出 L2 名不在 `l2_decision_trees.json`
  - UI 拿到無對應的 L2 時，沒 fallback 警告，反而讓 LLM 編 L3/L4/L5 給用戶
  - 例：螢幕顯示「褶底片・內貼式・上下SNAP副料織帶」整段 hallucinate（資料庫實際是「襠底片」/「三角型剪接」/「拷克拉開」）

### Phase H 規劃（未做）

- **VLM 修補**：identifyL2 鎖死 vocabulary + UI fallback 找不到 DB 對應顯示 ⚠ 警告 + top-k 候選
- **覆蓋廣度**：寫 OUTERWEAR / TOP / DRESS pipeline（量大優先 OUTERWEAR）
- **跨 GT 共識**：同 L1 不同 GT 做工是否共通
- **PPTX 中文擴展**：拿 GAP / TGT / KOH / UA / DKS / ANF / GU / BY / ATH 的 PPTX 中文版本（目前主要 ONY）
- **Visual Similarity Gallery 補圖**：4773/5203 缺 455 張
- **L2 VLM Decision Tree 訓練 Phase 0**：6 個全綠 L1 / 26 L2 pilot

---

## 11. 變更歷史

| 日期 | 版本 | 重點 |
|---|---|---|
| 2026-04-21 | v6.1 | callout consensus by GT（PANTS 不分 bucket）|
| 2026-05-04 | v7.0 | 1180 PullOn / 5 bucket-aware bridge / 中文 L1 |
| 2026-05-05 | v7.1 | 三刀規則 + Code review + Vision API 全 49 image-only PDF |
| 2026-05-06 | v3 | m7_report 五階展開 fix + 5-dim recipes + EN L1 |
| 2026-05-06 | v4 | + m7_detail SSRS 細工段 JOIN（65K sub-ops）|
| 2026-05-06 | v5 | 對齊平台 schema（iso_dictionary / n_total / aggregation_level）|
| 2026-05-07 | v6 | by_client 五階開全客戶 — 10 brand × knit/woven 26 L1（PR #275）|
| 2026-05-07 | v7 | 資料源統一 + VLM pipeline 修補 + LEGGINGS 推導 + 中文 normalize |
| **2026-05-08** | **v8** | **★ PDF per-client metadata 抽取 + 8 canonical multi-source consensus + alias normalizer + 自動 push 到 platform**(PR #297 merged + claude/normalizer-and-v43-fix open)|

### v7 改動清單（2026-05-07）

**資料源統一（single source of truth）**：
- 全 callout / facts / manifest 從 `stytrix-pipeline-Download0504/data/ingest/` 統一搬到 `M7_Pipeline/m7_organized_v2/`（1263 PNG / 608 MB）
- 5 隻腳本路徑常數加 primary + legacy fallback：`vlm_fallback_api.py` / `vlm_fallback_m7.py` / `count_zero_fact_pdfs.py` / `append_pdf_text_facts.py` / `build_recipes_master_v6.py`
- `extract_raw_text_m7.py` 加 flat layout 支援（output_dir 末段是 `m7_organized_v2` 時不再 nested 到 `pdf/` 子層）

**Detector 收緊（`m7_pdf_detect.py`）**：
- image-type 二次 filter：必須有 ISO regex / callout 關鍵字（CALLOUT/CONSTRUCTION/STITCH/SEAM/SEW/TOPSTITCH/OVERLOCK/FLATLOCK/COVERSTITCH/BARTACK/CHAINSTITCH/HEM/CUFF）/ margin spec 任一個
- 對齊 skill `training-pipeline-lessons.md` §鐵則 2 `is_callout_page` 規範
- 結果：image-type 比例從 12% → 10.2%（cover/spec sheet/mannequin 假陽性被踢出）

**VLM Vision API pre-process（`vlm_fallback_api.py`）**：
- 新 `_prepare_image()` 函式
- 自動 resize 最長邊 7800px（API 限制 8000）
- 自動 JPEG recompress 到 < 4.5 MB（API 限制 5 MB）
- skip empty PNG（< 1 KB）
- 結果：4 個 API error（5MB/8000px/empty）→ **0 errors**

**`derive_item_type()` 強化（`build_recipes_master_v6.py`）**：
- 加 subgroup heuristics（COMPRESSION/POWERSOFT/BUTTERSOFT/STUDIOSMOOTH/ALL DAY/FLX → LEGGINGS）
- 加 active brand prior（BY/ATH/UA/CALIA + dept=ACTIVE → LEGGINGS）
- 加 TIGHT/SWEATPANT/BIKE SHORT/BIKER 顯式 keyword
- 結果：LEGGINGS 從 9 → 61（×6.7）

**中文 normalize（`build_client_specific_l2_l3_ie.py`）**：
- `ZH_NORMALIZE` 替換規則
- 「檔底片」→「襠底片」（31 筆簡體 / 誤字）
- 「褶底片」→「襠底片」（AI hallucinate fallback）

**cp950 unicode bug 修補**：
- `build_recipes_master_v6.py` 的 print 階段把 `✓` `✗` `🖼️` `🚫` 改 `[Y]` `[N]` `[img]` `[no_img]`，避免 Windows cp950 codepage crash

**新增 helper 腳本**：
- `migrate_to_m7_organized.ps1` — 一鍵搬資料 + show stats
- `rebuild_manifest.ps1` — 套新 detector 重建 manifest
- `show_vlm_status.py` — 顯示 manifest entries / image-type designs / 已處理 / 待跑 + per-client 拆分

**新增 .gitignore（platform repo）**：
- `data/recipes_master.backup_*.json` — 排除 merge_into_platform_repo.py 自動產的本地備份
- `data/recipes_master_merged_preview.json` — 排除 preview 檔
- `onl *` — 排除 PowerShell redirect typo 檔

**結果（v6 → v7 數字）**：

| 指標 | v6 | v7 |
|---|---|---|
| Manifest entries | 1263 | 3802（全 982 PDF）|
| Vision unique designs | 32 | 109（+77）|
| Vision facts | ~5（殘留）| **+168 新**（首次 0 errors）|
| recipes_master_v6.jsonl | 470 | 551 |
| Platform recipes | 197 | **247** |
| LEGGINGS | 9 | **61** |
| 「檔底片」殘留 | 31 筆 | **0** |
| API errors | 4 | **0** |

### v8 改動清單（2026-05-08）

**問題:** 過去聚陽 M7 列管的 8 個 canonical 欄位(客戶/報價款號/Program/Subgroup/W/K/Item/Season/PRODUCT_CATEGORY)只有 M7 內部值,沒跟客戶端 PDF cover 上的命名做對齊。Filter 在跨來源 join 時可能掉拍(M7 寫 `WOMEN`,PDF 寫 `WOMENS` 對不上)。

**PDF metadata per-client adapter(`extract_pdf_metadata.py` 重寫)**:
- 11 客戶 PDF cover layout 各自不同(Centric 8 / DSG / Workfront / Makalot screenshot / Centric 8-A&F / 日文 GU / CATO Direct Source 等),用 7 個 parser cover:
  - `parse_centric8` → ONY / GAP / GAP_OUTLET / ATHLETA / BR(5 客戶共用 Gap Inc. 集團 PLM)
  - `parse_dicks` / `parse_target` / `parse_kohls` / `parse_anf` / `parse_gu` / `parse_cato` 各自獨立
  - TARGET 內含 3 sub-template(Workfront / AIM 中文 / POM-only),自動偵測
- 每客戶 parser 抽 raw fields 後再 `derive_*_canonical()` 推到 8 canonical
- 結果:1448 / 1486 PDF 抽出有效 metadata(輸出 `outputs/platform/pdf_metadata.jsonl`)

**Generic multi-source consensus(`scripts/lib/consolidate_canonical.py` 新增)**:
- 把原 `consolidate_fabric()`(只 W/K)推廣成 generic `consolidate_field(sources, primary_source, field_name, aliases)`
- Source priority:M7 列管 weight 3(primary)/ PDF weight 2(cross-check)/ 推論 weight 1(fallback)
- Confidence rule:M7 + PDF 一致 → high;不一致 → medium(衝突 audit);M7 only → high;沒 M7 → low/medium 看其他 source
- Output schema 每筆 design 加:
  ```json
  "canonical": {
    "客戶": {"value": "OLD NAVY", "confidence": "high",
             "sources": {"m7_列管": {...}, "pdf": {...}}},
    "報價款號": {...}, ...8 個欄位完整
  }
  ```
- `build_m7_pullon_source_v3.py` 整合進 main loop,每筆 design 履歷加 `canonical` block

**Alias normalizer(`data/canonical_aliases.json` 新增)**:
- 手維護 alias 對照,在 voting 前先 normalize:
  - 客戶:DICKS SPORTING GOODS↔DICKS / OLD NAVY↔ONY / GAP OUTLET↔GO / A&F 變體
  - PRODUCT_CATEGORY:WOMEN↔WOMENS, MEN↔MENS 單複數對齊
  - Subgroup:TG↔TEKGEAR, Wmn↔WOMEN, Act↔ACTIVE
  - Item:M7-only(用款號 join MK 資料即可,PDF 端不一致就放掉)
  - Season:Fall 2025 ↔ FA25 ↔ V-FA 2025 ↔ 2025FW(統一 SS/FA/HO/SP + YY)
  - 報價款號:GU `60225F046A` → `225F046`(trim 6-prefix + 尾碼字母);ONY/GAP M7 design ID vs PDF D-style 不該對齊(保留兩欄)
- Season 用 regex 在程式裡(JSON 表達不便),其他用 dict exact match
- Repo side 同份檔在 `stytrix-techpack/data/source/canonical_aliases.json`(手維護 source-of-truth)

**Reports(`scripts/report_canonical_*.py` 新增)**:
- `report_canonical_coverage.py`:讀 `pdf_metadata.jsonl`,輸出 per-(client × canonical)PDF 抽取覆蓋率
- `report_canonical_consensus.py`:讀 `m7_pullon_designs.jsonl`,輸出:
  - per-(client × field)confidence distribution(H/M/L 比例)
  - filter 角度 `canonical.<field>.value` 非空比例
  - PDF vs M7 列管衝突清單(confidence=medium 待人工 audit)+ 前 20 大衝突類型 + sample disagreements
- 給 IE / 業務當 audit deliverable 直接看

**自動 push 到 platform(`scripts/push_m7_pullon_to_platform.py` 新增)**:
- 自動 gzip `m7_pullon_designs.jsonl` → `data/ingest/m7_pullon/designs.jsonl.gz`
- 自動 copy `m7_pullon_source.jsonl` → `data/ingest/m7_pullon/entries.jsonl`
- `--dry-run` 先看 SRC/DST 對不對

**結果(v7 → v8 數字)**:

| 指標 | v7 | v8 |
|---|---|---|
| PDF metadata coverage | 0(沒抽 8 canonical)| **1448 件 / 11 客戶** |
| m7_pullon_designs.jsonl | 沒這檔 | **3900 件 / 78 MB(含 canonical block)** |
| Filter join coverage(8 canonical) | 不齊 | **100%(M7 兜底)** |
| 客戶 confidence high% | — | **98%** |
| 報價款號 high% | — | 85% |
| Program high% | — | 86% |
| Subgroup high% | — | 92% |
| W/K high% | — | **100%** |
| Item high% | — | **100%**(M7 only) |
| Season high% | — | 85% |
| PRODUCT_CATEGORY high% | — | 79% |
| Audit medium 衝突 | 沒清單 | **2169 件**(per-client × field 排序,IE / 業務逐筆 review) |
| Platform repo m7_pullon entries | 0 | **746** |

**剩下的 medium 衝突全是真實 audit items(不是 normalize 規則能消的)**:
- ONY M7 design ID(`510383_FA25`)vs PDF D-style(`D40583`)— 兩個 ID 系統並存,不該 normalize
- KOH 複合 Subgroup `ACT (TG WMN)` vs PDF sub-brand `TEKGEAR` — 不同顆粒度,需業務決策
- DKS PDF Season 字串截尾(`Softlines - Athletic Boy's - Fall -` 沒接年份)— PDF 模板問題
- GAP_OUTLET PDF 模板印 `GAP` 沒區分 sub-brand
- ANF Year 只到年沒月份/季

**Cross-repo bug fix(stytrix-techpack 端 `star_schema/scripts/build_recipes_master.py`)**:
- 2026-05-07 重組漏改的兩個 path:
  - `General Model_Path2_Construction Suggestion/` → `path2_universal/`(line 8/10/58/59)
  - `data/construction_bridge_v6.json` → `data/runtime/construction_bridge_v6.json`(line 12/60)
- 修完後 `build_recipes_master.py` 跑通(B-tier 0 違規,746 m7_pullon entries 進 platform)

**Consumer 狀態(2026-05-08)**:
- `stytrix-techpack/star_schema/scripts/build_recipes_master.py` 仍讀 aggregated `entries.jsonl`,**還沒讀 `designs.jsonl.gz` 的 canonical block**
- 是 data-ready / consumer-未接 狀態,Phase 2 designs_index 視圖才會直接用 canonical block

---

*文件維護:@elly | 最後更新 2026-05-08*
