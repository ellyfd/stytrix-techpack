# M7 Pull-on Pants Pipeline — IE 人員執行 SOP

> **目的**：把 IE 人員列管的 m7 設計清單（1180 件 PullOn 褲款）自動轉成跨客戶做工共識規則庫，最終產出可上傳 StyTrix 平台 / IE 報價系統的 `construction_bridge_v7.json`。
>
> **使用對象**：IE 人員（執行）+ 工程師（debug）
>
> **最後更新**：2026-05-05

---

## 0. 為什麼要這條 Pipeline

### 痛點

聚陽 IE 部門有兩種資料：

1. **客戶端 Techpack**（PDF + PPTX）— 每個客戶設計師寫的縫法 callout，散落在每件設計的圖紙裡，**英文 + 中文混雜、格式各異**。
2. **聚陽五階工時表**（csv_5level）— IE 人員實際展開的工序明細，含工序、機種、秒值。

兩邊資料**沒有自動對齊**：
- 業務報新單時，要憑經驗估算工序、機種、秒值
- 設計師寫「ISO 406 三本雙針」但 IE 工序表展開後最高頻機種是「平車」— 兩邊看似衝突
- 不同客戶的同一部位（如「腰頭」）做工差異有多大？沒有跨客戶共識資料

### 這條 Pipeline 解的事

```
1180 件 PullOn   ──→  自動抽 callout 文字（PDF/PPTX/Vision）
                     ↓
              標準化成 (zone, ISO, method) 結構化 facts
                     ↓
              跟 IE 五階共識對齊（bucket × L1 部位）
                     ↓
              產出對照表：設計意圖 vs 量產實做 + 落差分析
                     ↓
              JSON deliverable → 上 StyTrix 平台 / IE 報價系統
```

**最終價值**：
- 跨 17 客戶 × 38 部位的做工共識
- 8 個 gap_real 部位（設計意圖 ≠ 工序展開最高頻）→ 業務 / IE 會議重點討論
- 新單來時，可從 bridge 表查同 (bucket, L1) 的 typical_recipe + avg_seconds → 加速報價

---

## 1. 整體資料流程圖

```
┌────────────────────────────────────────────────────────────────┐
│  [IE 人員列管] M7 索引 Excel  +  csv_5level/ 五階 CSV 列管     │
│                                                                 │
│        M7資源索引_M7URL正確版_YYYYMMDD.xlsx                    │
│        m7_organized_v2/csv_5level/{eidh}_*.csv (1180 個)       │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase A：蒐集 — 從 SMB 內網拉客戶 Techpack                    │
│  scripts/2_fetch_tp.ps1   (PowerShell, 跑 ~3 hr)                │
│      ↓                                                          │
│  tp_samples_v2/  (3063 files / 11.4 GB raw)                    │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase B：整理 — 分類 PDF / PPTX                               │
│  scripts/3_reorganize.py                                        │
│      ↓                                                          │
│  m7_organized_v2/pdf_tp/    (PDF Techpack)                     │
│  m7_organized_v2/ppt_tp/    (PPTX 聚陽中文展開檔)              │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase C：抽取 callout — 4 個來源平行進                        │
│                                                                 │
│  C1. extract_pdf_metadata.py                                    │
│       PDF cover page → designs.jsonl 增 metadata（season,        │
│       brand_division, dept, vendor 等業務欄）                   │
│                                                                 │
│  C2. extract_unified_m7.py  (PPTX 路徑，主來源)                 │
│       PPTX 中文 callout → unified/facts.jsonl                   │
│       套：KW_TO_L1_BOTTOMS, multi-zone splitter,                │
│            enrich_method_zh (Style Guide 規格)                  │
│                                                                 │
│  C3. append_pdf_text_facts.py  (PDF text layer 補抽)            │
│       PDF callout 頁的 text spans → unified/pdf_text_facts.jsonl│
│                                                                 │
│  C4. vlm_fallback_api.py  (Vision API，補圖層 callout)          │
│       對 image-only PDF → Claude Vision → vision_facts.jsonl    │
│                                                                 │
│  全部 cat 進 unified/facts.jsonl  ← 所有 source 統一 schema     │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase D：對齊 IE 五階                                          │
│                                                                 │
│  D1. analyze_ie_consensus.py                                    │
│       讀 csv_5level/ 1180 CSV → 算每 (bucket, L1) 的            │
│       IE 工序共識（typical_machine, typical_l4, avg_seconds）   │
│       → aligned/ie_consensus.jsonl                              │
│                                                                 │
│  D2. align_to_ie_m7.py                                          │
│       facts.jsonl ↔ ie_consensus.jsonl 對齊                     │
│       → aligned/facts_aligned.jsonl                             │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase E：跨客戶共識                                            │
│  scripts/build_consensus_m7.py                                  │
│      ↓                                                          │
│  aligned/consensus_m7.jsonl  (29 entries × bucket × L1)        │
│      欄位：top_iso, top_method, methods 分布,                   │
│             ie_distribution, typical_recipe,                    │
│             confidence (high/medium/low)                        │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase F：產出 V7 部位對照表（最終 deliverable）                │
│  scripts/build_construction_bridge_v7.py                        │
│      ↓                                                          │
│  outputs/bridge_v7/                                             │
│      ├── construction_bridge_v7.json   ← 上平台用              │
│      ├── construction_bridge_v7_flat.csv  ← 人類看 / Excel     │
│      └── README.md                       ← 使用說明             │
│                                                                 │
│  含：design_intent + production_reality + gap_flag              │
│       (align / gap_layered / gap_real / no_data)               │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  Phase G：驗證                                                  │
│  scripts/validate_bridge_m7.py     (8 維 metadata 覆蓋率)       │
│  scripts/validate_ie_consistency.py (五階核對)                  │
│  scripts/count_zero_fact_pdfs.py    (找漏網 design)             │
└────────────────────────────────────────────────────────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │  上傳 StyTrix 平台 / │
                │  IE 報價系統         │
                └──────────────────────┘
```

---

## 2. 列管輸入規格

### IE 人員需要提供 / 維護 2 份檔案

#### 2.1 M7 索引 Excel（每季更新）

**檔名**：`M7資源索引_M7URL正確版_YYYYMMDD.xlsx`
**位置**：`M7_Pipeline/` 根目錄
**Sheet**：`新做工_PullOn`
**必要欄位**：

| 欄位 | 說明 | 範例 |
|---|---|---|
| Eidh | 設計唯一 ID | 327840 |
| 客戶 | 客戶名（會自動 normalize） | OLD NAVY、A&F、TARGET... |
| 報價款號 | 內部 design_id | D97929 |
| Item | 品類 | Pull On Pants |
| W/K | 布料類型（必填）| Woven / Knit |
| Subgroup | 客戶內部分類（業務碼，影響 gender 推導）| #D34、D41... |
| Program | 客戶 program | OLD NAVY WOMENS HOLIDAY... |
| Season | 季別 | HO26、SU26、SP26... |
| TP 路徑 | SMB 路徑（給 PowerShell fetch）| `\\192.168.1.220\TechPack\TPK\...` |

#### 2.2 csv_5level/ 五階工時 CSV（IE 內部產出）

**位置**：`m7_organized_v2/csv_5level/{eidh}_{description}.csv`
**每 EIDH 一檔**，內容是 IE 五階展開後的工序：

| 欄位 | 說明 |
|---|---|
| Textbox8 | 工序流水號 |
| category | L1 部位（中文，如「腰頭」「褲口」）|
| part | L2 部件 |
| Shape_Design | L3 形狀設計 |
| Method_Describe | L4 工序方法描述 |
| section | L5 段落 |
| Sewing_Process | 縫紉工序類別 |
| Skill_Level | 技能等級 |
| machine_name | 機種名（如「四線拷克」「平車-細針距」）|
| size | 尺寸 |
| total_second | 該工序秒值 |

> ⚠️ **IE 必須確保**：每個 EIDH 都有對應 CSV。沒 CSV 的設計 align rate 會掉。

---

## 3. 各階段詳細

### Phase A：SMB 拉客戶 Techpack（PowerShell 內網跑）

**做什麼**：根據 M7 索引每筆 EIDH 的「TP 路徑」欄，從 SMB 內網 `\\192.168.1.220\TechPack\` 把整個 TPK 資料夾複製到本機 `tp_samples_v2/`。

**為什麼**：客戶 Techpack 散在 SMB 不同路徑，要先集中到本機才能批次處理。

**指令**：
```powershell
cd "C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline"
.\scripts\2_fetch_tp.ps1
```

**重點**：
- 必須在內網（聚陽公司網路）才能存取 SMB
- 預估 1180 EIDH × 平均 2-3 檔 × 平均 3-5 MB = ~15 GB / 3 hr
- 中間斷網要重跑（PowerShell 會 skip 已存在檔）

**注意**：
- 客戶有時會把 Techpack 移路徑 → 索引檔的「TP 路徑」要更新
- 部分檔有 `LAFitComments` / `MeasurementChart` / `sizechart` 字眼 — Phase B 會自動排除（不是 construction）

**輸出**：
- `tp_samples_v2/` 含 ~3063 檔（PDF + PPTX 混合）

**檢查**：
```powershell
Get-ChildItem -Recurse "tp_samples_v2" | Measure-Object Length -Sum
# 預期 11+ GB
```

---

### Phase B：分類 PDF / PPTX

**做什麼**：把 `tp_samples_v2/` 裡的檔依副檔名分類到 `pdf_tp/` 或 `ppt_tp/`，並改名加上 client 前綴方便後續識別。

**為什麼**：後續 parser 需要按 PDF / PPTX 分流（PDF 走 PyMuPDF text-layer，PPTX 走中文 parser）。

**指令**：
```powershell
python scripts\3_reorganize.py
```

**重點**：
- **規則簡單**：PDF → `pdf_tp/`，PPTX → `ppt_tp/`，僅 hard-exclude `LAFitComments / MeasurementChart / sizechart` 字眼（這些是量測表，不是 construction）
- 檔名 normalize：`{CLIENT}_{design_id}_{rest}.{ext}`（如 `ONY_D97929.pdf`）

**注意**：
- 不要過濾太嚴！過去版本曾因命名規則太嚴漏掉 13/50 design — 已修
- 客戶名 normalize 對照表：`scripts/m7_constants.py:CUSTOMER_TO_CODE`，新客戶要加進去

**輸出**：
- `m7_organized_v2/pdf_tp/`
- `m7_organized_v2/ppt_tp/`

---

### Phase C：抽取 callout（4 個 source）

#### C1. PDF cover metadata 抽取

**做什麼**：開每個 PDF 的封面頁，抽客戶業務 metadata（season、brand_division、department、collection、bom_number、vendor 等）寫進 `pdf_metadata.jsonl`。

**為什麼**：客戶 PDF 封面頁有業務資訊（如「OLD NAVY - WOMENS / HOLIDAY 2026 / WOMENS PERFORMANCE」），這些是後續 derive_metadata 推 gender / dept 的關鍵。

**指令**：
```powershell
python scripts\extract_pdf_metadata.py
```

**重點**：
- 用 per-client adapter（ONY Centric 8、DICKS DSG 各有專屬 layout 解析器）
- 沒對應 adapter 的客戶 fallback 到 generic 通用 regex

**注意**：
- 不是所有 PDF 都有 cover metadata（有些 PDF 是 spec sheet 直接開始）— 沒抽到沒關係，只是少一些業務欄
- 新客戶要在 `extract_pdf_metadata.py:CLIENT_PARSERS` 加 adapter

**輸出**：
- `data/ingest/metadata/pdf_metadata.jsonl`

#### C2. PPTX 中文 callout 抽取（**主來源** ~70% facts）

**做什麼**：開每個 PPTX，抽聚陽 IE 用中文寫的 construction callout（如「腰頭 拷克」「褲口 三本雙針」），對應 ZH_TO_L1 字典轉成結構化 facts。

**為什麼**：PPTX 是聚陽 IE 內部展開檔，內容已經中文化、結構化，是抽 facts 主來源。

**指令**：
```powershell
cd "..\stytrix-pipeline-Download0504"
python ..\M7_Pipeline\scripts\extract_unified_m7.py `
  --ingest-dir data\ingest `
  --out data\ingest\unified
```

**重點**：
- **三刀規則套用**（2026-05-05 新增）：
  1. 英文 zone 直接 → L1（不走 EN→ZH 翻譯兩跳路徑）
  2. Multi-zone splitter（"RISE/OUTSEAM/INSEAM:" → 3 個 fact）
  3. ISO_TO_ZH_METHOD：method 字串套 Style Guide canonical（"COVERSTITCH" → "三本雙針(406)"）
- **GUARD 機制**：facts 必須有 ISO 或 method 才生（沒就跳，避免抓到 POM 量測欄）
- 資料字典統一從 `data/zone_glossary.json` 載入（不寫死 .py）

**注意**：
- explicit confidence（有顯式 ISO）約 12%，zh_inferred（中文推 ISO）約 88%
- PPTX 主要中文，英文 path 在 PPTX 上效益有限（補約 +15 facts）

**輸出**：
- `data/ingest/unified/facts.jsonl` (累積，每筆一行)
- `data/ingest/unified/dim.jsonl` (design 維度資料)

#### C3. PDF text-layer 補抽（補 ~13% facts）

**做什麼**：對 detect 階段判定有 callout 的 PDF 頁，用 PyMuPDF 抽 text spans，套同樣 parser 規則生 facts。

**為什麼**：PDF text 層有些 callout 是 PPTX 沒覆蓋的（特別是 ONY/A&F 客戶寫得詳細的部分）。

**指令**：
```powershell
cd "..\M7_Pipeline"
python scripts\append_pdf_text_facts.py --reset --batch-size 1180 --max-seconds 600
```

**重點**：
- `--reset` 清掉 state file 從頭跑（避免接續到舊版規則的 fact）
- `--max-seconds 600` 給本地 10 分鐘預算（sandbox 跑要設 35）
- 反覆 call 直到看到 `═══ ALL DONE ═══`
- 寫到獨立檔 `pdf_text_facts.jsonl`，跑完要手動 `Get-Content ... | Add-Content` 併進 `facts.jsonl`

**注意**：
- 同一 design 的 PDF text 跟 PPTX 中文可能 overlap → 接受 dup（後續 consensus 會 dedup by source_line + design_id）

**輸出**：
- `data/ingest/unified/pdf_text_facts.jsonl`
- 併進 `data/ingest/unified/facts.jsonl`

#### C4. Vision API 補圖層 callout（補 ~5% facts，可選）

**做什麼**：對 image-only PDF 設計（圖層 callout，text-layer 抽不到的），用 Claude Vision API 自動辨識 callout 文字。

**為什麼**：ONY 等客戶常把 callout 直接畫在人形圖上（圖層而非 text 層），text-layer 完全抽不到。Vision 是唯一辦法。

**指令**：
```powershell
# 1. 裝 SDK（一次）
pip install anthropic

# 2. 設 API key（每次新 PowerShell session）
$env:ANTHROPIC_API_KEY="sk-ant-api03-..."

# 3. 確認候選清單
python scripts\count_zero_fact_pdfs.py     # 看 n_with_image_pages_only
python scripts\vlm_fallback_m7.py --mode list

# 4. 跑全量（~10-15 min, ~$1-2 USD）
python scripts\vlm_fallback_api.py

# 5. 併進 facts.jsonl
python scripts\vlm_fallback_m7.py --mode merge
```

**重點**：
- 用 Sonnet 4.5（性價比好），可改 `--model opus` 提精度
- API key 必須是真實 key（不是 sk-ant-XXXX 佔位）
- 跑完**立即去 console.anthropic.com rotate API key**（避免外洩）
- Hit rate 約 47%（不是每張 PNG 都有 callout，有些是 inspiration 圖）

**注意**：
- PNG 不能 > 5 MB（API limit），dimension 不能 > 8000 px
- 4 個 PNG 在 1180 跑時超限失敗 — resize 後可重跑（通常 ROI 太低不值得）

**輸出**：
- `data/ingest/unified/vision_facts.jsonl`
- merge 後併進 `facts.jsonl`

---

### Phase D：對齊 IE 五階

#### D1. IE 五階共識計算

**做什麼**：讀 1180 個 csv_5level/CSV，group by (bucket, L1)，算每組的 typical_machine、typical_l4、machine_dist、avg_seconds。

**為什麼**：IE 五階表是「量產實做」的真實資料，要把每個部位的「最高頻機種」算出來才能跟設計師 callout 比對。

**指令**：
```powershell
python scripts\analyze_ie_consensus.py
```

**重點**：
- bucket = `{wk}_BOTTOMS`（WOVEN_BOTTOMS / KNIT_BOTTOMS）
- L1 來自 csv 的 `category` 欄（38 個聚陽 IE 標準部位碼）
- by_client 同時算 — 顯示同部位在不同客戶的差異

**注意**：
- IE typical_machine 最高頻常出現「手工-含做記號、翻修等工段」這種 catch-all step，不是真縫紉機種 — 後續 v7 + validate 會 filter 掉
- IE_NON_SEWING_KEYWORDS 列表在 `data/zone_glossary.json`

**輸出**：
- `m7_organized_v2/aligned/ie_consensus.jsonl`（44 entries）

#### D2. facts ↔ IE 對齊

**做什麼**：對每筆 fact，查找對應 EIDH 的 IE CSV，把 fact 跟 CSV 中 same L1 的工序資訊 join 起來。

**指令**：
```powershell
python scripts\align_to_ie_m7.py
```

**重點**：
- 含模糊比對（同義詞）以提升 align rate
- 沒對應 IE CSV 的 fact 標 `no_ie`（會在後續被 skip）

**注意**：
- align rate 預期 ~64%（不是 100% 是正常的，PPTX 抽到的「其它」zone 沒 IE 對應）

**輸出**：
- `m7_organized_v2/aligned/final_aligned.csv`（人類看版）
- `m7_organized_v2/aligned/facts_aligned.jsonl`（給 build_consensus_m7 用）
- `m7_organized_v2/aligned/_summary.csv`

---

### Phase E：跨客戶共識

**做什麼**：group facts by (bucket, L1)，算每組的 ISO 分布、method 分布、IE 分布、typical_recipe，給 confidence label（high/medium/low/very_low）。

**為什麼**：跨 17 客戶的同一部位（如「腰頭」），ISO 用法是否一致？最常見方法是什麼？這個共識才是平台 / 報價系統能查的「standard recipe」。

**指令**：
```powershell
python scripts\build_consensus_m7.py
```

**重點**：
- confidence 規則：
  - **high**: n_facts ≥ 20 AND clients ≥ 5
  - **medium**: n_facts ≥ 10 AND clients ≥ 3
  - **low**: n_facts ≥ 5
  - **very_low**: 其他

- 同步算 `ie_step_coverage`：我們抽到 fact 的 design 中，IE CSV 有對應 L1 的比例

**注意**：
- 1180 全跑後預期 29 entries（10-13 high）
- low / very_low 的 entry 不要直接拿來用，樣本太少

**輸出**：
- `m7_organized_v2/aligned/consensus_m7.jsonl`
- `m7_organized_v2/aligned/consensus_summary.csv`

---

### Phase F：產出 V7 Bridge（最終 Deliverable）

**做什麼**：合併三個來源產出最終可上平台的 JSON：
1. `consensus_m7.jsonl` — 我們的 callout 共識（design intent）
2. `ie_consensus.jsonl` — IE 五階共識（production reality）
3. `construction_bridge_v6.json` — 舊版 v6.1 legacy GT（保留 TOP/DRESS/OUTERWEAR/SET，PullOn 範圍以外）

每 (bucket, L1) 算 **gap_flag**：
- `align`：design_iso 對應 ZH 機種 = IE 真縫紉 top1（過濾手工/燙工後）
- `gap_layered`：在 IE machine_dist top 3 之內
- `gap_real`：完全不在 IE top 3 → 真衝突，要看
- `no_data` / `no_iso_mapping`：資料不足

**指令**：
```powershell
python scripts\build_construction_bridge_v7.py
```

**重點**：
- 結構：`bridges → bucket → zones → 部位中文名 → {design_intent, production_reality, alignment, typical_recipe}`
- 設計師看 design_intent 跟客戶確認外觀
- IE / 報價系統看 production_reality（含 typical_recipe + machine_dist + avg_seconds）報秒值
- gap_real 部位 = 博士 / Vanessa 會議優先檢討清單

**注意**：
- `production_machine`（過濾 catch-all 後 top1）跟 `production_machine_typical`（IE 原 typical，可能含手工）兩欄並存，下游可選
- v6.1 legacy 沒 IE join，只有 callout 分布，cross-bucket 對齊精度不如 v7 主表

**輸出**：
- `outputs/bridge_v7/construction_bridge_v7.json`（**最終 deliverable，給 StyTrix 平台**）
- `outputs/bridge_v7/construction_bridge_v7_flat.csv`（給博士會議 / Excel）
- `outputs/bridge_v7/README.md`（含 gap_real 解讀）

---

### Phase G：驗證

#### G1. validate_bridge_m7.py — 8 維 metadata 覆蓋率

**做什麼**：對 unified facts.jsonl 算 8 個欄位（callout_id / client / fabric / garment_type / item_type / body_type / season / gender / department）的覆蓋率，看是否合格。

**指令**：
```powershell
python scripts\validate_bridge_m7.py
```

**目標覆蓋率**：除 gender 外都 100%。gender 因為要靠 subgroup 推導，~58% 是預期（剩下 UNKNOWN）。

#### G2. validate_ie_consistency.py — 五階核對

**做什麼**：對每 (bucket, L1) 比對 design_iso ↔ IE machine_dist 一致度，flag inconsistent。

**指令**：
```powershell
python scripts\validate_ie_consistency.py
```

#### G3. count_zero_fact_pdfs.py — 找漏網

**做什麼**：列出 detect 階段判定有 callout 但 0 fact 的 design，分 client 看分布。

**指令**：
```powershell
python scripts\count_zero_fact_pdfs.py
```

決定是否值得跑 Vision fallback。

---

## 4. 完整 SOP（IE 人員每季更新跑法）

```powershell
# === 起手：cd 到 M7_Pipeline 根 ===
cd "C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline"

# === Phase A：SMB 拉檔（內網跑，~3 hr）===
.\scripts\2_fetch_tp.ps1

# === Phase B：分類 ===
python scripts\3_reorganize.py

# === Phase B.5：cp 到 unified workspace ===
robocopy m7_organized_v2\pdf_tp ..\stytrix-pipeline-Download0504\data\ingest\uploads /XO /R:1
robocopy m7_organized_v2\ppt_tp ..\stytrix-pipeline-Download0504\data\ingest\uploads /XO /R:1

# === Phase C1：PDF metadata ===
python scripts\extract_pdf_metadata.py

# === Phase C2：PPTX 抽 facts（主來源）===
cd "..\stytrix-pipeline-Download0504"
python ..\M7_Pipeline\scripts\extract_unified_m7.py --ingest-dir data\ingest --out data\ingest\unified

# === Phase C3：PDF text-layer 補抽 ===
cd "..\M7_Pipeline"
python scripts\append_pdf_text_facts.py --reset --batch-size 1180 --max-seconds 600
# 反覆 call 直到 ALL DONE

# 併進 facts.jsonl
cd "..\stytrix-pipeline-Download0504"
Get-Content data\ingest\unified\pdf_text_facts.jsonl | Add-Content data\ingest\unified\facts.jsonl

# === Phase C4 (optional)：Vision API 補圖層 callout ===
cd "..\M7_Pipeline"
$env:ANTHROPIC_API_KEY="sk-ant-api03-..."   # 真 key
python scripts\count_zero_fact_pdfs.py       # 看候選量
python scripts\vlm_fallback_api.py            # 跑全量
python scripts\vlm_fallback_m7.py --mode merge

# === Phase D：對齊 IE 五階 ===
python scripts\analyze_ie_consensus.py        # 算 IE 共識（如果 csv_5level 更新才要重跑）
python scripts\align_to_ie_m7.py

# === Phase E：跨客戶共識 ===
python scripts\build_consensus_m7.py

# === Phase F：V7 Bridge（最終 Deliverable）===
python scripts\build_construction_bridge_v7.py

# === Phase G：驗證 ===
python scripts\validate_bridge_m7.py
python scripts\validate_ie_consistency.py

# === 完成。檢查 outputs/bridge_v7/ ===
explorer outputs\bridge_v7
```

---

## 5. 失敗排查 cheatsheet

| 症狀 | 可能原因 | 解法 |
|---|---|---|
| Phase A 卡住 | 不在內網 / SMB 路徑變了 | 連聚陽 VPN；更新 M7 索引「TP 路徑」欄 |
| `ModuleNotFoundError: fitz` | 沒裝 PyMuPDF | `pip install pymupdf` |
| `ModuleNotFoundError: python_calamine` | 沒裝 calamine engine | `pip install python-calamine` |
| `ModuleNotFoundError: anthropic` | Vision API 才需要 | `pip install anthropic` |
| facts 數明顯比上次少 | PDF text-layer 沒併進 facts.jsonl | 跑 `Get-Content pdf_text_facts.jsonl \| Add-Content facts.jsonl` |
| Vision API 401 error | API key 沒設 / 設錯 | 檢查 `$env:ANTHROPIC_API_KEY`，必須是真 key |
| Vision API "image cannot be empty" | PNG 檔損壞 | 跳過該 PNG，不影響全局 |
| Vision API "image exceeds 5 MB" | PNG 太大 | resize 後重跑，或略過 |
| align rate 突然掉 | csv_5level 缺檔 | 確認 1180 EIDH 都有對應 CSV |
| consensus high tier 數變少 | 新加客戶但 fact 還沒夠 | 跑足夠樣本後 high tier 才會升 |
| gap_real 突然變多 | 新加 client 樣本 / 新批 facts 把分布拉偏 | 檢查 _flat.csv 的 design_intent 看是否合理 |

---

## 6. 重點 / 注意（給 IE 人員）

### 6.1 改字典只改 `data/zone_glossary.json`

不要改 .py 裡的 dict（會 drift）。所有 dict 都從 zone_glossary.json 載入：
- `KW_TO_L1_BOTTOMS`：英文 zone keyword → L1 部位
- `ISO_TO_ZH_METHOD`：ISO → ZH method（Style Guide canonical）
- `METHOD_EN_TO_ISO`：method EN → ISO 反查
- `ISO_TO_IE_KEYWORDS`：ISO → IE machine 關鍵字（gap_flag 判斷用）
- `IE_NON_SEWING_KEYWORDS`：手工 / 燙工 catch-all 列表

### 6.2 新客戶加入流程

1. M7 索引加新筆 EIDH
2. `m7_constants.py:CUSTOMER_TO_CODE` 加客戶縮寫對照
3. `derive_metadata.py:_MANUAL_MAPPING` 補 (client, subgroup) → gender 對照（如必要）
4. 跑 Pipeline 全流程
5. 看 align rate / gap_real 是否合理

### 6.3 ISO 字典維護

`zone_glossary.json:ISO_TO_ZH_METHOD` 目前 11 個 ISO，按 `techpack-translation-style-guide.md` Part A1 canonical 命名。新增 ISO（如 511 / 603 等）：
1. 加進 `ISO_TO_ZH_METHOD`
2. 加進 `ISO_TO_IE_KEYWORDS`（給 gap_flag 用）
3. 加進 `VALID_ISOS` list
4. 重跑 Phase C2 / C3 / C4 → Phase E / F

### 6.4 gap_real 處理建議

8 個 gap_real（穩定不變）的解讀：

| (bucket, L1) | 設計意圖 | IE 量產實做 | 解讀 |
|---|---|---|---|
| KNIT × PS（褲合身）| 605 | 514 | 同 overlock 系列，不同針線數，可接受 |
| KNIT × WB（腰頭）| 605 | 301 | 設計講「主縫法」605，IE 工序拆細後 301 平車主導 |
| WOVEN × BM（下襬）| 602 | 301 | 同上，設計師畫 602 但工廠用 301 收 |
| WOVEN × DC（繩類）| 401 | 301 | 繩類加工差異 |
| WOVEN × LI（裡布）| 514 | 301 | 裡布拷克 vs 工廠 301 接合 |
| WOVEN × PD（褶）| 406 | 301 | 褶用 301 平車是工廠標準 |
| WOVEN × SS（脅邊）| 607 | 301 | 設計畫併縫，IE 用 301 |
| WOVEN × WB（腰頭）| 401 | 301 | 鎖鏈 vs 平車 |

→ 都是「設計講主視覺縫法 vs IE 工序拆細後最高頻 301」結構性差異。報價時兩個分開算（design 給客戶 confirm 縫法外觀，IE 報實際秒值）。

### 6.5 何時要重跑 IE consensus

`analyze_ie_consensus.py` 重跑時機：
- csv_5level/ 有新增 / 修改 EIDH
- 修改 IE_NON_SEWING_KEYWORDS（zone_glossary.json）
- 平常不需要重跑（只跑一次得到 ie_consensus.jsonl 即可）

---

## 7. 檔案清單與位置

```
M7_Pipeline/
├── data/
│   └── zone_glossary.json         ← 唯一資料字典（dicts source of truth）
│
├── scripts/
│   ├── shared/
│   │   ├── zone_resolver.py       ← 共用 helpers（dict 載入 + zone/method 函式）
│   │   └── ie_alignment.py        ← gap_flag 判斷邏輯
│   │
│   ├── m7_constants.py            ← re-export shared + 客戶 normalize
│   ├── 1_fetch.py                 ← (legacy)
│   ├── 2_fetch_tp.ps1             ← Phase A SMB 拉檔
│   ├── 3_reorganize.py            ← Phase B 分類
│   ├── extract_pdf_metadata.py    ← Phase C1
│   ├── extract_unified_m7.py      ← Phase C2 (PPTX)
│   ├── append_pdf_text_facts.py   ← Phase C3 (PDF text-layer)
│   ├── vlm_fallback_api.py        ← Phase C4 (Vision API)
│   ├── vlm_fallback_m7.py         ← Vision 候選列舉 / merge 模式
│   ├── analyze_ie_consensus.py    ← Phase D1
│   ├── align_to_ie_m7.py          ← Phase D2
│   ├── build_consensus_m7.py      ← Phase E
│   ├── build_construction_bridge_v7.py  ← Phase F (deliverable)
│   ├── validate_bridge_m7.py      ← Phase G1
│   ├── validate_ie_consistency.py ← Phase G2
│   ├── count_zero_fact_pdfs.py    ← Phase G3
│   ├── inspect_text_miss.py       ← (debug) 看 A&F 等 text-miss 設計
│   ├── derive_metadata.py         ← gender 推導 4 段式
│   ├── m7_pdf_detect.py           ← detect_construction_pages
│   └── extract_raw_text_m7.py     ← (legacy)
│
├── m7_organized_v2/
│   ├── pdf_tp/                    ← Phase B 分類 PDF
│   ├── ppt_tp/                    ← Phase B 分類 PPTX
│   ├── csv_5level/                ← IE 五階 CSV（IE 提供，1180 個）
│   ├── sketches/                  ← 設計縮圖 jpeg（1174 張）
│   │                                  ★ 給 StyTrix Techpack Creator
│   │                                    Stage 1 sketch shape 辨識 training，
│   │                                    pair (sketch, csv_5level) 是訓練樣本
│   └── aligned/
│       ├── ie_consensus.jsonl     ← Phase D1 輸出
│       ├── facts_aligned.jsonl    ← Phase D2 輸出
│       ├── consensus_m7.jsonl     ← Phase E 輸出
│       └── consensus_summary.csv
│
├── outputs/
│   ├── bridge_v7/
│   │   ├── construction_bridge_v7.json   ← ★ 最終 deliverable
│   │   ├── construction_bridge_v7_flat.csv
│   │   └── README.md
│   ├── ie_consistency/_check.csv  ← Phase G2 輸出
│   └── zero_fact_pdfs/            ← Phase G3 輸出
│
├── construction_bridge_v6.json    ← v6.1 legacy（v7 會合併進來）
├── M7資源索引_M7URL正確版_*.xlsx  ← IE 提供
└── PIPELINE.md                    ← 本檔
```

外部相依（在 `..\stytrix-pipeline-Download0504\`）：
```
data/ingest/
├── uploads/                       ← Phase B.5 cp 後的 PDF/PPTX
├── pdf/
│   ├── callout_manifest.jsonl     ← detect 階段產出
│   └── callout_images/            ← PDF page 渲成 PNG（Vision 用）
├── metadata/
│   ├── designs.jsonl              ← M7 索引轉成 JSONL
│   └── pdf_metadata.jsonl         ← Phase C1 輸出
└── unified/
    ├── facts.jsonl                ← ★ 主 fact 資料
    ├── dim.jsonl                  ← design 維度
    ├── pdf_text_facts.jsonl       ← Phase C3 輸出（要併進 facts.jsonl）
    └── vision_facts.jsonl         ← Phase C4 輸出（要 merge 進 facts.jsonl）
```

---

## 8. 目前 baseline 數字（2026-05-05）

```
├── facts                  3256
├── aligned                2086 (64.1%)
├── consensus entries      29 (13 high + 7 medium + 5 low + 4 very_low)
├── gap_real               8（穩定，博士會議重點）
├── ONY align rate         70.7% (232/328 designs)
└── 17 客戶覆蓋
```

每季 IE 列管更新後重跑，ratio 應該維持，n 數會 grow。

---

## 9. sketches/ 與 StyTrix Techpack Creator 銜接（Training Data 出口）

### 為什麼這個 folder 重要

`m7_organized_v2/sketches/` 1174 張設計縮圖**不是這條 PullOn pipeline 直接用**，而是給下一層 ML 系統 — **StyTrix Techpack Creator** — 做 sketch shape 辨識的訓練素材。

### 訓練 / 推理流程

```
┌─────────────────────────────────────────────────────────────────┐
│  Training（離線，1180 EIDH 都用）                                │
│                                                                  │
│  sketches/{eidh}.jpeg          csv_5level/{eidh}.csv             │
│  （設計縮圖）                   （IE 五階 ground truth）          │
│       ↓                              ↓                           │
│       └─────── pair → supervised training ─────┘                │
│                              ↓                                   │
│         VLM/CLIP 學「看到這 sketch → 應有 L1/L2/L3 部位          │
│                       + 對應的五階工段 recipe」                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ deploy
┌─────────────────────────────────────────────────────────────────┐
│  Inference（線上，新單推 recipe）                                │
│                                                                  │
│  設計師上傳 sketch                                               │
│       ↓                                                          │
│  Stage 1：VLM 部位形狀辨識                                       │
│       → 回 L1（38 個部位中哪幾個）→ L2 part → L3 shape design    │
│       ↓                                                          │
│  Stage 2：查 consensus_m7.jsonl 找 same (bucket, L1)             │
│       → typical_recipe（L4/L5/machine/avg_seconds）              │
│       ↓                                                          │
│  Stage 3：業務看 recipe + IE 套秒值 → 自動報價                   │
└─────────────────────────────────────────────────────────────────┘
```

### Prompt Engineering 環節（user 強調的關鍵）

**作法**（怎麼把 sketch → L1/L2/L3 訓練做好）：

1. **聚類**：對 csv_5level/ 1180 個 CSV 做 group by 同樣的「五階工段組合」
   - 例如：腰頭_拷克接合_四線拷克 + 褲口_反折_三本雙針 + 脅邊_併縫 = 一個 recipe pattern
   - 找出多個 EIDH 共用同一套五階工段 → 同組 sketch 應該長得「形狀相近」

2. **回看圖片**：把同 recipe pattern 的 sketches/ 圖一起看
   - 觀察視覺特徵：哪幾個是 jogger？哪幾個是 flare？哪幾個有褶？
   - 找出視覺差異跟 recipe 差異的對應關係

3. **Prompt iteration**：
   - 寫 prompt 給 VLM「請判斷這 sketch 是否含 X 部位 / 是哪種輪廓」
   - 回看訓練 set 上 wrong predictions 的 sketch
   - 改 prompt 直到 VLM 抽 L1/L2/L3 跟 ground truth recipe 對齊

4. **驗證迴圈**：
   - 對 holdout set 的 sketch 跑 prompt → 預測 recipe
   - 跟該 EIDH 真實 csv_5level 比對
   - 計算 L1/L2/L3 各層 accuracy
   - 不夠精準回 step 3 改 prompt

### 這個 folder 在 M7 Pipeline 內的角色

```
M7 PullOn Pipeline （這條）            StyTrix Techpack Creator（下游）
──────────────────────────             ─────────────────────────────
[輸入] M7 索引 + csv_5level             [輸入] 設計師新 sketch
        ↓                                       ↓
[抽 callout + 對齊 IE]                  [Stage 1] VLM sketch shape 辨識
        ↓                                       ↓
[output] consensus_m7.jsonl  ──────→   [Stage 2] 查 consensus 找 recipe
[output] sketches/ + csv_5level pair                ↓
              ↓                          [Stage 3] 報價
   作為 Training Data 出口
```

**M7 Pipeline 提供兩個 deliverable 給 Techpack Creator**：
1. **跨客戶 consensus**（`consensus_m7.jsonl` / `construction_bridge_v7.json`）— Inference 時查 typical_recipe
2. **(sketch, csv_5level) pair**（`sketches/` × `csv_5level/`）— Training 時學 sketch → recipe 對應

### 為什麼不直接在這條 Pipeline 做

- M7 Pipeline 專注「callout → IE 對齊 → consensus」 — text/data pipeline
- Sketch 辨識是 **VLM/ML pipeline**，技術棧不同（要 GPU、訓練 framework、prompt iteration）
- 但**訓練資料的清洗、配對、ground truth 標準化**這些前置工作在 M7 Pipeline 完成，下游接手即可

### 檢查 sketch ↔ csv_5level 配對完整性

```powershell
# 看每 EIDH 是否同時有 sketch + csv
python -c "
from pathlib import Path
sk = {f.stem.split('_')[0] for f in Path('m7_organized_v2/sketches').iterdir()}
csv = {f.stem.split('_')[0] for f in Path('m7_organized_v2/csv_5level').iterdir()}
both = sk & csv
sk_only = sk - csv
csv_only = csv - sk
print(f'sketch: {len(sk)}, csv: {len(csv)}, paired: {len(both)}, sk_only: {len(sk_only)}, csv_only: {len(csv_only)}')
"
```

理想情況：1180 三個都對齊。實際 sketches 1174、csv 1180、配對 ~1170+。

---

## 10. 變更歷史

| 日期 | 版本 | 重點 |
|---|---|---|
| 2026-04-21 | v6.1 | callout consensus by GT（PANTS 不分 bucket）|
| 2026-05-04 | v7.0 baseline | 整 1180 PullOn / 5 bucket-aware bridge |
| **2026-05-05** | **v7.1** | **三刀規則升級（multi-zone, EN-direct, ISO→ZH method, gauge）+ Code review 5 quick wins + 架構重構（zone_glossary.json + shared/）+ Vision API 全 49 image-only PDF (+174 facts) → 3256 facts / 8 gap_real** |

---

*文件維護：@elly · 工程：跑 Pipeline 有問題請看 §5 失敗排查*
