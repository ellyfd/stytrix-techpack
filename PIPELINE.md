# M7 PullOn Pipeline — 從 4 個資料源蒸餾出跨客戶做工共識

> **一頁總結**：1180 件 PullOn 褲款 × 4 個資料源（客戶 PDF/PPTX + 聚陽 nt-net2 / nt-netsql2 / nt-eip）→ 自動抽取 → 標準化 → 跨客戶共識 → **`recipes_master.json` 307 platform recipes (99 high confidence, 5-dim, EN canonical)**，平台 RAG / IE 報價系統直接吸。
>
> **最後更新**：2026-05-06
>
> **版本**：v5（schema 對齊平台）

---

## 目錄

1. [問題：為什麼非做這條 pipeline 不可](#1-問題)
2. [為什麼要做：解了問題能多賺什麼](#2-為什麼要做)
3. [如何做：4 源 × 5 phase 蒸餾邏輯](#3-如何做)
4. [能達到什麼：deliverable + 數字](#4-能達到什麼)
5. [用什麼工具：技術棧選型理由](#5-用什麼工具)
6. [SOP：每季更新一鍵跑全 pipeline](#6-sop)
7. [失敗排查](#7-失敗排查)
8. [檔案結構 / 共用模組](#8-檔案結構)

---

## 1. 問題

### 1.1 聚陽 IE 部門面對的 4 個資料黑洞

| 資料源 | 內容 | 痛點 |
|---|---|---|
| 客戶 Techpack（PDF / PPTX） | 設計師 callout（"ISO 401 三本雙針"） | 散在 SMB 的 1181 個資料夾、PDF / PPTX 混雜、英中文格式各異、有些 callout 在圖層（text 抽不到） |
| 聚陽 PPTX 中文翻譯檔 | IE 中文展開的 callout | 已 normalize 但跟客戶 PDF 沒自動對齊 |
| 聚陽 M7 五階摘要 (nt-net2) | 報價總額 / IE 工時 / 機種 / flags | 散在內網 ASP.NET 系統，要手動逐筆查 |
| 聚陽 M7 細工段 (nt-netsql2 SSRS) | sub-operation × machine_name × Skill_Level | 同上，要 NTLM 認證 + SSRS CSV export |

### 1.2 沒這條 pipeline 之前

設計師畫「ISO 406 三本雙針」，IE 工序展開後最高頻機種卻是「平車-細針距」。**兩邊看似衝突，但沒有 ground truth 對照，業務只能憑經驗報價。**

具體痛在哪：
- ❌ 業務報新單時憑經驗估秒值（沒共識資料）
- ❌ 不同客戶（A&F、GAP、ONY）同部位「腰頭」做工差異多大？沒人知道
- ❌ 設計意圖（ISO）vs 量產實做（machine_name）落差有多少？沒對照
- ❌ 1180 件 PullOn 的工時 / 機種 / 工序資料躺在 4 個系統，互不通

### 1.3 平台需要什麼但拿不到

StyTrix 平台 / IE 報價系統需要的 RAG 知識庫格式：

```json
{
  "key": {"gender": "WOMEN", "dept": "ACTIVE", "gt": "PANTS", "it": "KNIT", "l1": "WB"},
  "iso_distribution": [{"iso": "301", "n": 450, "pct": 61.3}],
  "methods": [{"name": "Lockstitch", "n": 450, "pct": 35.2}],
  "n_total": 734, "confidence": "high"
}
```

之前的 `construction_bridge_v7.json` 是 2-dim（`bucket × 中文 L1`），平台吃不下。

**核心問題：**有資料、沒 schema、無法直接餵 RAG。

---

## 2. 為什麼要做

### 2.1 直接 ROI

| 痛點 | 解了之後 | 量化 |
|---|---|---|
| 業務憑經驗報價，誤差大 | 查 (gender, dept, gt, it, L1) 拿 typical recipe + IE avg secs | 報價時間 ↓ + 準度 ↑ |
| IE 跟設計師意見衝突 | gap_flag (align / gap_layered / gap_real) 三色標 | 會議聚焦 8 個真衝突部位 |
| 新人 onboarding 慢 | top_machines / Skill_Level / sections 自動帶出 | 訓練時間 ↓ |
| 跨客戶經驗無法共享 | 1180 件跨 17 客戶共識自動算 | 17 客戶 × 38 部位的「我們做過」資料庫 |

### 2.2 平台層面的價值

`recipes_master.json` 是 **StyTrix Techpack Creator** 的下游 RAG：

```
設計師上傳新 sketch
    ↓
Stage 1: VLM 部位辨識 (使用 sketches/ × csv_5level/ training data)
    ↓
Stage 2: 查 recipes_master.json 找 same (gender, dept, gt, it, L1) 的 typical recipe
    ↓
Stage 3: 平台帶出 ISO + EN method + 機種 + Skill + IE avg secs
    ↓
業務 / 客戶看到：「這 sketch 的腰頭，10 個客戶 × 152 個 design 的 consensus 是 Lockstitch (301)，平均 0.066 秒/step」
```

**沒這條 pipeline，Techpack Creator 沒 RAG 知識庫，等於空殼。**

### 2.3 資料資產化

聚陽過去 1180 件 PullOn 累積的工序知識，散在 4 個系統。Pipeline 跑完後變成：
- **65,803 sub-operations** 結構化（含真實機種 + Skill_Level）
- **29,868 五階 step**（含 IE 秒值）
- **2,761 PDF callout facts**（含 ISO + method + zone）
- **307 5-dim platform recipes**（99 high confidence）

→ 這些資料隨時可以餵到任何下游系統（RAG / 報價引擎 / 訓練 ML）。

---

## 3. 如何做

### 3.1 整體蒸餾流程

```
┌─────────────────────────────────────────────────────────────────┐
│  GROUND TRUTH                                                    │
│  M7 索引 Excel: 1180 EIDH × {客戶, Subgroup, Style#, Item, W/K} │
└──────────────┬─────────────────────────────────┬────────────────┘
               │                                 │
   ┌───────────┴────────────┐  ┌─────────────────┴────────────┐
   │  CLIENT 端 (PDF/PPTX) │  │  MAKALOT 端 (內網)            │
   ├────────────────────────┤  ├──────────────────────────────┤
   │ Phase A:  SMB 拉檔      │  │ Phase A2:                    │
   │   2_fetch_tp.ps1       │  │   fetch_m7_report_playwright │
   │ Phase B:  分類          │  │     → m7_report.jsonl (1180) │
   │   3_reorganize.py      │  │   fetch_m7_detail.py         │
   │   sync_ppt_tp.py       │  │     → m7_detail.csv (65K)    │
   └────────────┬───────────┘  └──────────────┬───────────────┘
                │                             │
                ▼                             ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Phase C: 抽 callout (4 源 cat 進 facts.jsonl)            │
   │   C1. extract_pdf_metadata     (PDF cover)               │
   │   C2. extract_unified_m7        (PPTX 主源)              │
   │   C3. append_pdf_text_facts     (PDF text-layer)         │
   │   C4. vlm_fallback_api          (Claude Vision 補圖層)    │
   └────────────────────┬─────────────────────────────────────┘
                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Phase D: 對齊 + JOIN                                     │
   │   align_to_ie_m7    (facts ↔ IE 共識)                    │
   │   enrich_dim         (designs + m7_report)               │
   └────────────────────┬─────────────────────────────────────┘
                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Phase E: Platform Recipes ⭐                             │
   │   v3 (5lev consensus) → v4 (+ sub-op JOIN) → v5 (schema) │
   │     → recipes_master.json (★ 平台直接吸)                 │
   └────────────────────┬─────────────────────────────────────┘
                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Phase F: Audit / 驗證                                    │
   │   audit_ppt_coverage / check_ppt_smb / validate_*        │
   └──────────────────────────────────────────────────────────┘
```

### 3.2 每 phase 解什麼問題

#### Phase A — 把客戶 Techpack 拉到本機

**問題**：客戶 Techpack 散在 SMB `\\192.168.1.220\TechPack\` 不同路徑。
**做法**：M7 索引每筆 EIDH 有「TP 路徑」欄，用 PowerShell 自動 robocopy 過來。
**為什麼**：本機處理比每次連 SMB 快 10×；批次 ML 處理需要本機 cache。

#### Phase A2 — 抓聚陽內網系統（**v5 新增**）

**問題**：聚陽 nt-net2 / nt-netsql2 有完整 IE 五階展開 + 細工段，但沒 API。

**做法**：
- nt-net2 ASP.NET → **Playwright CDP attach** 到使用者本機 Chrome（自帶 SSO cookie），跑 JS evaluator 抓 span ID 結構化資料
- nt-netsql2 SSRS → **HTTP 直連 + NTLM 認證**，加 `&rs:Format=CSV` 參數直接 export CSV

**為什麼**：
- Chrome CDP 比 headless 穩（避開 NTLM 認證流程）
- SSRS 內建 CSV export 比 scrape HTML 簡單 100×

**結果**：1180/1180 全 cover，0 error。

#### Phase B — PDF / PPTX 分類 + 同步

**問題**：客戶檔 PDF/PPTX 混雜，pipeline 需要按副檔名分流（PDF 走 PyMuPDF，PPTX 走 python-pptx）。

**做法**：
- `3_reorganize.py` 按副檔名搬到 `pdf_tp/` / `ppt_tp/`，命名 normalize
- `sync_ppt_tp.py` 修補 reorganize 偶爾漏 copy（同步 tp_samples_v2/ 跟 ppt_tp/）

#### Phase C — 抽 callout（4 源平行）

**問題**：客戶 callout 散在 4 個地方，格式各異。

**4 源解決 4 種情況**：
| Source | 解什麼 | 抽到的量 |
|---|---|---|
| C1 PDF cover metadata | 業務 metadata（season/dept/vendor） | 248 design |
| C2 PPTX 中文 callout | 聚陽 IE 翻譯後的結構化資料 | ~70% facts |
| C3 PDF text-layer | PDF 文字層的 callout | ~13% facts |
| C4 Vision API（Claude） | image-only PDF 的圖層 callout | ~5% facts |

**全部 cat 進 `facts.jsonl`** — schema 統一，不管哪個來源都長一樣。

#### Phase D — 對齊 IE 五階 + JOIN designs

**問題**：抽到的 callout 是 raw 資料，要跟 IE 量產共識對齊才有 ground truth。

**做法**：
- `align_to_ie_m7.py`：每筆 fact 查對應 EIDH 的 IE CSV，把 facts 跟 IE 工序 JOIN
- `enrich_dim.py`：把 designs.jsonl + m7_report.jsonl 五階展開 JOIN，產出 `dim_enriched.jsonl`

#### Phase E — Platform Recipes（多版迭代到對齊 schema）

**問題**：平台需要 5-dim key + EN canonical method + iso_distribution[]。

**v3 → v4 → v5 三步**：
- **v3**: 用 m7_report 五階展開做 5-dim consensus（gender × dept × gt × it × L1）→ 307 recipes / 99 high
- **v4**: v3 + JOIN m7_detail sub-op → 每 recipe 多 typical_machine + Skill_Level + section
- **v5**: 對齊平台 schema：
  - 欄位 rename（`n_steps` → `n_total`，`item_type` → `it`）
  - 加 `aggregation_level: "5dim_full"` + `source: "m7_pullon_v5"`
  - method 中文 → EN canonical（從 `iso_dictionary.json` 反查，21 個標準名稱）
  - **iso_distribution[] 三源 hybrid**：
    - (a) PDF callout facts 的 ISO（嚴謹）
    - (b) m7 method 文字 regex 抽 ISO（廣度）
    - (c) m7_detail machine_name 反查 ISO（補強）

**結果**：271/307 (88%) 有 iso_distribution，307/307 (100%) 有 EN methods。

#### Phase F — Audit / 驗證

確認 deliverable 品質：
- `audit_ppt_coverage.py` — PPT 覆蓋率（1033/1180 = 87.5%；147 真的 M7 系統沒上 PPT）
- `check_ppt_smb.py` — SMB 缺檔 verdict（11 漏抓 vs 147 系統沒）
- `validate_bridge_m7.py` — 8 維 metadata 覆蓋率
- `validate_ie_consistency.py` — 五階核對

---

## 4. 能達到什麼

### 4.1 核心 deliverable

`outputs/platform/recipes_master.json` ⭐ **307 platform recipes**

```json
{
  "key": {"gender": "WOMEN", "dept": "ACTIVE", "gt": "PANTS", "it": "KNIT", "l1": "WB"},
  "aggregation_level": "5dim_full",
  "source": "m7_pullon_v5",
  "n_total": 734,
  "iso_distribution": [
    {"iso": "301", "n": 450, "pct": 61.3},
    {"iso": "514", "n": 200, "pct": 27.2}
  ],
  "methods": [
    {"name": "Lockstitch",        "n": 450, "pct": 35.2},
    {"name": "4-thread Overlock", "n": 200, "pct": 15.6},
    {"name": "Marking",           "n": 280, "pct": 21.9}
  ],
  "confidence": "high",
  "n_designs": 152,
  "n_clients": 10,
  "n_subops": 2934,
  "ie_avg_seconds": 0.066,
  "ie_median_seconds": 0.034,
  "category_zh": "腰頭",
  "top_parts":         [{"name": "剪接腰頭_整圈", "count": 91}],
  "top_machines":      [{"name": "手工-含做記號、翻修等工段", "n": 432}],
  "top_skill_levels":  [{"level": "B", "n": 1100}, {"level": "E", "n": 800}],
  "top_sections":      [{"section": "做上腰頭記號", "n": 450}],
  "_iso_source_breakdown": {"from_pdf_facts": {...}, "from_m7_text": {...}}
}
```

### 4.2 數字盤點

| 項目 | 覆蓋率 | 數量 |
|---|---|---|
| **M7 索引 EIDH** | 100% | 1180（ground truth） |
| **PPT 檔** | 87.5% | 1033 |
| **PDF metadata** | 21% | 248 design |
| **PDF construction facts** | 22% | 263 design / 2,761 facts |
| **m7_report 五階摘要** | **100%** | 1180 EIDH |
| **m7_report five_level_detail** | **100%** | 1180 EIDH / 29,868 step |
| **m7_detail 細工段** | **100%** | 1180 EIDH / 65,803 sub-ops |
| **dim_enriched** | 100% PullOn | 394 designs |
| **Platform Recipes v5** | — | **307 recipes / 99 high** |
| **iso_distribution cover** | 88% | 271 / 307 recipes |
| **methods[] cover** | 100% | 307 / 307 recipes |

### 4.3 EN canonical method 分佈（v5 high recipes）

| EN canonical | n | ISO |
|---|---|---|
| Marking | 22,776 | — |
| Lockstitch | 20,449 | 301 |
| 4-thread Overlock | 11,391 | 514 |
| Pressing | 5,712 | — |
| Bartack | 5,151 | — |
| Heat Press / Heat Transfer | 3,496 | — |
| Flatlock | 1,997 | 607 |
| Buttonhole | 1,781 | — |
| Coverstitch | 1,579 | 406 |
| Manual | 1,529 | — |
| Trim | 1,186 | — |
| 5-thread Overlock | 1,182 | 516 |
| Safety Stitch | 777 | 504 |
| Chainstitch | 475 | 401 |

→ 主力縫紉 ISO 排序（301 / 514 / 406 / 607）跟 PullOn 工序常識相符。

### 4.4 其他 deliverable

| 檔案 | 內容 | 給誰用 |
|---|---|---|
| `m7_report.jsonl` | 1180 EIDH × m7 五階摘要 + flags + machines + 五階展開 | IE / 業務 |
| `m7_detail.csv` | 65,803 細工段（含 machine_name + Skill_Level） | IE / 訓練資料 |
| `dim_enriched.jsonl` | 394 PullOn designs（含 makalot_side 完整） | 平台 / 報價 |
| `facts_aligned.jsonl` | 2,761 PDF callout facts × IE 共識對齊 | 平台 / RAG |
| `recipes_master_v3/v4.csv` | v5 前一版（debug 用） | 工程師 |
| `ppt_coverage_audit.csv` | PPT 覆蓋率 audit | 列管 |
| `construction_bridge_v7.json` | (legacy 2-dim 中文 L1) | 博士會議用 |

---

## 5. 用什麼工具

### 5.1 技術棧選型理由

| 工具 | 用在哪 | 為什麼選它 |
|---|---|---|
| **PyMuPDF (fitz)** | PDF text-layer 抽取 + 渲染成 PNG | 比 pdfplumber 快 5×，原生支援圖層 / drawing 計數（用來判斷是否 callout 頁） |
| **python-pptx** | PPTX 中文 callout 解析 | 標準工具，支援文字框 + 表格 |
| **anthropic Claude API** | Vision 補圖層 callout | Sonnet 4.5 性價比好，hit rate ~47%（image-only PDF 的 callout） |
| **Playwright + CDP attach** | nt-net2 ASP.NET 抓五階摘要 | 接管使用者本機 Chrome 帶 SSO cookie，避開 NTLM 流程；JS evaluator 抓動態渲染內容 |
| **requests + requests_negotiate_sspi** | nt-netsql2 SSRS 抓細工段 | NTLM Windows AD SSO；SSRS `&rs:Format=CSV` 直接 export，比 scrape HTML 簡單 |
| **pandas + python-calamine** | M7 索引 Excel 讀取 | calamine 比 openpyxl 快 3×，且 Python 3.14 不會 SystemError |
| **Python 標準 csv / json** | 全部結構化資料寫入 | jsonl per-line + utf-8-sig 寫 BOM，Excel 直接開不亂碼 |
| **PowerShell** | SMB 拉檔（內網跑） | robocopy 是 Windows 原生，比 Python 快、有 retry / skip exists |

### 5.2 為什麼不用其他選擇

| 不用的方案 | 為什麼不用 |
|---|---|
| ❌ requests + NTLM 直接 scrape nt-net2 | nt-net2 ASP.NET 動態渲染，session 過期難維持，CDP attach 一勞永逸 |
| ❌ pywinauto + Sample Schedule WinForms 客戶端 | UIA backend 看不到 WinForms 的 Custom 控件（506 Pane / 0 Button） |
| ❌ Selenium | Playwright API 更穩，CDP attach 內建支援 |
| ❌ pdfplumber | 速度慢，不支援 page.get_drawings()（callout 偵測會差） |
| ❌ openpyxl 跑 Python 3.14 | SystemError（calamine 是 fallback） |

### 5.3 共用模組（refactor 第二波）

| 模組 | 內容 | 給誰用 |
|---|---|---|
| `shared/pdf_helpers.py` | `detect_construction_pages` + `is_centric8_non_construction` | extract_raw_text_m7 / extract_unified_m7 |
| `shared/zone_resolver.py` | ZH/EN zone splitter, ISO regex | 多個 |
| `shared/ie_alignment.py` | facts ↔ IE 對齊邏輯 | align_to_ie_m7 |
| `m7_constants.py` | CUSTOMER_TO_CODE, normalize_client, KEYWORD_TO_METHOD | 多個 |
| `data/zone_glossary.json` | L1_STANDARD_38, ISO_TO_ZH_METHOD, KW_TO_L1_BOTTOMS | 多個 |
| `data/iso_dictionary.json` | ISO ZH/EN canonical + machine name（★ v5 用） | build_recipes_master_v5 |
| `data/client_metadata_mapping.json` | 22 客戶 × subgroup_codes mapping | derive_metadata |

---

## 6. SOP

### 6.1 一鍵跑全 pipeline（每季更新）

```cmd
cd "C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline"

REM Phase A — SMB 拉檔（內網跑，~3 hr）
.\scripts\2_fetch_tp.ps1

REM Phase A2 — 抓內網（~2 hr）
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome_debug_profile"
REM ↑ 第一次手動登入 nt-net2，後續 script 用 CDP attach
python scripts\fetch_m7_report_playwright.py --reset
python scripts\fetch_m7_detail.py --reset

REM Phase B — 整理 PPT
python scripts\3_reorganize.py
python scripts\sync_ppt_tp.py

REM Phase C — 抽 callout
python scripts\extract_pdf_metadata.py
cd ..\stytrix-pipeline-Download0504
python ..\M7_Pipeline\scripts\extract_unified_m7.py --ingest-dir data\ingest --out data\ingest\unified
cd ..\M7_Pipeline
python scripts\append_pdf_text_facts.py --reset
python scripts\vlm_fallback_api.py     REM (optional, 需 ANTHROPIC_API_KEY)

REM Phase D — 對齊 + JOIN
python scripts\analyze_ie_consensus.py
python scripts\align_to_ie_m7.py
python scripts\enrich_dim.py

REM Phase E — Platform Recipes
python scripts\build_platform_recipes_v3.py
python scripts\build_platform_recipes_v4.py
python scripts\build_recipes_master_v5.py

REM Phase F — Audit
python scripts\audit_ppt_coverage.py
```

成功標誌：
```
=== recipes_master_v5 summary ===
  total recipes:     307
  high      :        99
  medium    :        46
  low       :        69
  very_low  :        93
  with iso_distribution: 271 / 307
  with methods[]:        307 / 307
[output]
  outputs/platform/recipes_master.json  ← 平台用這個
```

### 6.2 derive_metadata 推導（5 段式）

`scripts/derive_metadata.py` 從 `(client, subgroup, program, item, wk)` 推 `(gender, dept, gt, item_type, brand)`：

| 段 | 規則 | 命中率 |
|---|---|---|
| 1 | `_MANUAL_MAPPING` (user manual) + `client_metadata_mapping.json` | ~5% |
| 2 | `PULL ON pure data.xlsx` 學的 (Customer, Subgroup) → Gender 對照 | ~79% |
| 3 | Subgroup 含 gender 字（`MENS/MISSY/WAC/MAC/GAC/BAC/SLW/UA(MENS)`等） | ~6% |
| 4 | `_CLIENT_DEFAULT_GENDER` (BEYOND YOGA/ATHLETA → WOMEN) | ~3% |
| 5 | `_CLIENT_DEFAULT_DEPT` (OLD NAVY→RTW, KOHLS→ACTIVE 等 17 客戶) | UNKNOWN→known |

加 fallback 後 v3 從 620 UNKNOWN bucket → 18 (skipped)。

### 6.3 新客戶加入流程

1. M7 索引 Excel 加新筆 EIDH
2. `m7_constants.py:CUSTOMER_TO_CODE` 加客戶縮寫
3. `data/client_metadata_mapping.json` 補 (client, subgroup) → gender/dept
4. 跑 Pipeline 全流程（§6.1）
5. 看 `recipes_master_v5 summary` 的 high/medium 數字是否合理

### 6.4 改字典只改 JSON

不要改 `.py` 裡的 dict（會 drift）：
- 改 `data/zone_glossary.json` — L1 部位 / ISO ↔ ZH method / KW → L1
- 改 `data/iso_dictionary.json` — ISO ↔ EN canonical / machine name
- 改 `data/client_metadata_mapping.json` — 客戶 subgroup_codes

---

## 7. 失敗排查

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| Phase A 卡住 | 不在內網 / SMB 路徑變了 | 連聚陽 VPN；更新 M7 索引「TP 路徑」欄 |
| `ModuleNotFoundError: fitz` | 沒裝 PyMuPDF | `pip install pymupdf` |
| `ModuleNotFoundError: requests_negotiate_sspi` | Phase A2-2 SSRS 才需要 | `pip install requests_negotiate_sspi` |
| `ModuleNotFoundError: anthropic` | Vision API 才需要 | `pip install anthropic` |
| Playwright `connect_over_cdp` 失敗 | Chrome 9222 port 沒開 | `chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome_debug_profile"` |
| Vision API 401 / "image cannot be empty" | API key 錯 / PNG 損壞 | 檢查 `$env:ANTHROPIC_API_KEY`；資源 PNG 跳過 |
| facts 數明顯比上次少 | PDF text-layer 沒併進 facts.jsonl | `Get-Content pdf_text_facts.jsonl \| Add-Content facts.jsonl` |
| v3 太多 UNKNOWN bucket | derive_metadata fallback 不夠 | 補 `_CLIENT_DEFAULT_DEPT` / `_GENDER_TOKENS` |
| v4 sub-op match 0% | JOIN key 用錯欄位 | m7_detail 的 `Method_Describe` 對應 m7_report 的 `method_code` |
| v5 method 還是大寫 | facts_aligned 端沒過 normalize | 確認 `normalize_method_name()` 套用到 source (a) |

---

## 8. 檔案結構

```
M7_Pipeline/                                    ← 372 KB scripts (清理過)
├── data/
│   ├── zone_glossary.json                      ← L1_STANDARD_38, ISO→ZH method
│   ├── iso_dictionary.json                     ← ★ v5 用 (ISO ZH/EN canonical + machine)
│   ├── client_metadata_mapping.json            ← 22 客戶 subgroup_codes
│   └── metadata_mapping.md
│
├── scripts/  (31 個現役 .py + 1 個 .ps1)
│   ├── shared/
│   │   ├── pdf_helpers.py                      ← detect_construction_pages + Centric8
│   │   ├── zone_resolver.py                    ← ZH/EN zone helpers
│   │   └── ie_alignment.py
│   ├── m7_constants.py                         ← CUSTOMER_TO_CODE, normalize_client
│   │
│   │  ── Phase A ──
│   ├── 2_fetch_tp.ps1                          ← SMB 拉檔
│   ├── 3_reorganize.py                         ← 分類 PDF/PPTX
│   ├── sync_ppt_tp.py                          ← 補漏 copy
│   ├── patch_ppt_11.py                         ← 補 11 個 SMB 漏抓
│   │
│   │  ── Phase A2 (★ v5 新增) ──
│   ├── fetch_m7_report_playwright.py           ← nt-net2 五階摘要 (Chrome CDP)
│   ├── fetch_m7_detail.py                      ← nt-netsql2 SSRS 細工段
│   ├── inspect_m7_report.py                    ← 解析 nt-net2 HTML 結構 (debug)
│   │
│   │  ── Phase C ──
│   ├── extract_pdf_metadata.py                 ← C1 cover metadata
│   ├── extract_unified_m7.py                   ← C2 PPTX 主源
│   ├── extract_raw_text_m7.py
│   ├── append_pdf_text_facts.py                ← C3 PDF text-layer
│   ├── vlm_fallback_api.py                     ← C4 Claude Vision
│   ├── vlm_fallback_m7.py                      ← Vision merge / list
│   ├── m7_pdf_detect.py
│   │
│   │  ── Phase D ──
│   ├── analyze_ie_consensus.py
│   ├── align_to_ie_m7.py
│   ├── enrich_dim.py                           ← JOIN designs + m7_report
│   ├── derive_metadata.py                      ← 5 段式 metadata 推導
│   │
│   │  ── Phase E ──
│   ├── build_consensus_m7.py                   (legacy 共識)
│   ├── build_construction_bridge_v7.py         (legacy 中文 deliverable)
│   ├── build_platform_recipes_v3.py            ← v3 m7 5lev consensus
│   ├── build_platform_recipes_v4.py            ← v4 + sub-op JOIN
│   └── build_recipes_master_v5.py              ← ★ v5 平台 schema 對齊
│   │
│   │  ── Phase F (Audit) ──
│   ├── audit_ppt_coverage.py
│   ├── check_ppt_smb.py
│   ├── validate_bridge_m7.py
│   ├── validate_ie_consistency.py
│   ├── count_zero_fact_pdfs.py
│   ├── inspect_text_miss.py
│   │
│   ├── 1_fetch.py                              (legacy)
│   └── cleanup_repo.py                         ← 整理工具
│
├── m7_organized_v2/                            ← 9.8 GB
│   ├── pdf_tp/                                 ← 分類 PDF
│   ├── ppt_tp/                                 ← 分類 PPTX (扁平 1033)
│   ├── csv_5level/                             ← IE 五階 CSV
│   ├── sketches/                               ← 設計縮圖（給 Techpack Creator）
│   └── aligned/
│       ├── ie_consensus.jsonl
│       ├── facts_aligned.jsonl
│       └── consensus_m7.jsonl
│
├── tp_samples_v2/                              ← 12 GB（原始 SMB 拉的）
│
├── outputs/
│   ├── platform/                               ← ★ v5 deliverable
│   │   ├── recipes_master.json                 ← ★★ 平台直接吸
│   │   ├── recipes_master_v5.csv / .jsonl
│   │   ├── recipes_master_v3.csv / .jsonl
│   │   └── recipes_master_v4.csv / .jsonl
│   ├── bridge_v7/                              (legacy 中文 deliverable)
│   ├── ppt_coverage_audit.csv
│   ├── ppt_smb_check.csv
│   ├── ppt_missing_eidhs.txt
│   └── ie_consistency / validate_bridge_* / zero_fact_pdfs/
│
├── M7資源索引_M7URL正確版_*.xlsx               ← IE 列管 ground truth
├── PIPELINE.md                                 ← 本檔
├── construction-page-rules.md
├── techpack-translation-style-guide.md
├── construction_bridge_v6.json                 (v6.1 legacy)
└── .gitignore
```

外部相依（在 `..\stytrix-pipeline-Download0504\`）：
```
data/ingest/
├── uploads/                                    ← cp 後 PDF/PPTX
├── pdf/
│   ├── callout_manifest.jsonl
│   └── callout_images/
├── metadata/
│   ├── designs.jsonl                           ← M7 索引轉 JSONL
│   ├── pdf_metadata.jsonl
│   ├── m7_report.jsonl                         ← ★ A2-1 輸出
│   ├── m7_detail.csv                           ← ★ A2-2 輸出
│   └── dim_enriched.jsonl                      ← Phase D3 輸出
└── unified/
    ├── facts.jsonl                             ← 主 fact 資料
    ├── pdf_text_facts.jsonl
    └── vision_facts.jsonl
```

### 8.1 sketches/ 與 StyTrix Techpack Creator 銜接

`m7_organized_v2/sketches/` 1174 張縮圖**不是這條 PullOn pipeline 直接用**，而是給下一層 — **StyTrix Techpack Creator** — 做 sketch shape 辨識訓練：

```
[Training] sketches/{eidh}.jpeg + csv_5level/{eidh}.csv → VLM/CLIP supervised
                                                              ↓
                                  學「sketch → L1/L2/L3 + recipe」

[Inference] 設計師 sketch
              → Stage 1 VLM 部位辨識
              → Stage 2 查 recipes_master.json 拿 typical recipe
              → Stage 3 業務報價
```

M7 Pipeline 提供兩個 deliverable 給 Techpack Creator：
1. **跨客戶 consensus**（`recipes_master.json`）— Inference 時查 typical_recipe
2. **(sketch, csv_5level) pair**（`sketches/` × `csv_5level/`）— Training 時學 sketch → recipe 對應

### 8.2 Coding 約定

- **編碼**：所有檔案 UTF-8 with BOM (`utf-8-sig`) 寫入；Python 開啟用 `encoding="utf-8"` 讀
- **Path 規則**：`ROOT = M7_Pipeline/`，`DL = stytrix-pipeline-Download0504/`，data 路徑用 `Path(__file__).resolve().parent.parent`
- **Imports**：scripts/ 內互 import 用 `sys.path.insert(0, str(ROOT / "scripts"))`，不用相對 import
- **Status 寫檔**：`.{name}_state` 存目前 idx，續跑用。`--reset` 砍 state + output
- **錯誤處理**：HTTP / file 都包 try/except，loop 不停（單筆 err 不影響全流程）
- **改字典只改 JSON**：`data/*.json` — 不要改 .py 內 dict（會 drift）

---

## 9. 已知限制 / 未來優化

### 限制
- **PullOn-only**：只 cover Pull-on Pants。其他 GT (TOP/DRESS/OUTERWEAR/SET) 要等對應 pipeline
- **gender UNKNOWN 仍佔 23%**：m7_report 直接抓的 EIDH 多數沒 subgroup
- **iso_distribution 88% cover**：剩 12% recipe 是純中文 free-form 描述沒對到 ISO，需人工確認
- **147 EIDH 沒 PPT**：M7 系統就沒上 PPT，無法補

### Phase H 規劃（未做）
- **Refactor 第三波**（task #52）：抽 `fact_extractor` + `m7_metadata` → shared module
- **覆蓋廣度展開**：寫 OUTERWEAR / TOP / DRESS pipeline
- **跨 GT 共識**：design 同 L1 但不同 GT，做工是否共通？
- **gender UNKNOWN 收尾**：v3 改從 M7 索引 Excel 讀 subgroup（不靠 designs.jsonl 的 PDF cover）

---

## 10. 變更歷史

| 日期 | 版本 | 重點 |
|---|---|---|
| 2026-04-21 | v6.1 | callout consensus by GT（PANTS 不分 bucket） |
| 2026-05-04 | v7.0 | 1180 PullOn / 5 bucket-aware bridge / 中文 L1 |
| 2026-05-05 | v7.1 | 三刀規則 + Code review quick wins + 架構重構 + Vision API 全 49 image-only PDF |
| 2026-05-06 | v3 | m7_report 五階展開 fix + 5-dim platform recipes（302 / 72 high）+ EN L1 |
| 2026-05-06 | v4 | + m7_detail SSRS 細工段 JOIN（65K sub-ops）+ machine + skill |
| **2026-05-06** | **v5** | **★ 對齊平台 schema（iso_dictionary canonical + n_total + aggregation_level + iso_distribution[] 三源 hybrid + methods[] EN canonical）** |

---

*文件維護：@elly · 工程：跑 Pipeline 有問題請看 §7 失敗排查*
