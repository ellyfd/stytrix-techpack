# POM Rules Pipeline v5.5.1 — 完整操作手冊

## 全局架構圖

```
ONY 資料夾 (PDF 原始檔)
  │
  ├── 2024/  (月份資料夾: 1~12, 每個月份下平放 PDF)
  ├── 2025/  (季節資料夾: SP25/SU25/FA25/HO25, 巢狀結構)
  └── 2026/  (季節資料夾: SP26/SU26/FA26/HO26/SP27, 巢狀結構)
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Phase 1: PDF 萃取 (extract)                            │
  │  截圖來源 → Centric PLM 匯出的 Techpack PDF             │
  │  輸出 → mc_pom_{year}.jsonl                             │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Phase 2: 合併 + 建立 Profile (rebuild_profiles)        │
  │  輸出 → measurement_profiles_union.json                 │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Phase 3: 分類 + 產出規則 (reclassify_and_rebuild)      │
  │  輸出 → pom_rules/*.json (83 bucket files)              │
  │       → design_classification_v5.json                   │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Phase 4: 後處理 (enforce_tier1 → fix_sort_order)       │
  │  輸出 → 同 pom_rules/*.json (原地更新)                  │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Phase 5: 延伸分析 (6 支分析腳本)                       │
  │  輸出 → _parsed/ 下各分析 JSON                          │
  └─────────────────────────────────────────────────────────┘
```

---

## Phase 1: PDF 萃取

### 原始資料來源

**截圖什麼：** Centric PLM 系統匯出的 Techpack PDF（每個 design 一份）

每份 PDF 包含以下結構化資訊（不需要手動截圖，用腳本自動萃取）：

| PDF 區塊 | 萃取欄位 | 說明 |
|-----------|---------|------|
| Header / Meta | Design Number, Description, Brand/Division, Department, Category, Sub_Category, Item Type, Design Type, Fit Camp, Collection, Flow | 設計的身份識別 + 分類用 metadata |
| MC Table (Measurement Chart) | MC Key, Body Type, Status, Sizes | 尺寸表的識別欄。一個 design 可能有多張 MC（如 REGULAR / PETITE / TALL） |
| POM Rows (Points of Measure) | POM_Code (如 H1, F10), POM_Name (如 Waistband Height), sizes (各尺碼數值), tolerance (pos/neg) | 每個量測點的尺碼數值 + 公差 |
| Construction / ISO | 車縫做工、ISO 縫法代碼 | 用於 Construction Bridge（Phase 5） |
| Callout Image | 量測點標示圖 | 萃取但不用於 pom_rules |

### 萃取腳本

| 腳本 | 處理範圍 | 輸出檔 |
|------|----------|--------|
| `run_extract_new.py` | 2026 全部 PDF（月份 + 季節資料夾，5,037 筆） | `_parsed/mc_pom_2026.jsonl` |
| `measurement_pipeline.py` (舊版) | 2024 月份 PDF（499 筆）+ 2025 月份 PDF（5,225 筆） | `_parsed/mc_pom_2024.jsonl` + `_parsed/mc_pom_2025.jsonl` |
| `run_extract_2025_seasonal.py` | 2025 季節 PDF (SP25/SU25/FA25/HO25，1,277 筆) — append 到既有檔 | `_parsed/mc_pom_2025.jsonl` |

**特性：**
- Resume-safe：每次執行會跳過已處理的檔案（比對 `_source_file` 欄位）
- 540 秒 timeout：超時自動停止，下次接著跑
- 自動從路徑/檔名提取 Design Number（正則 `D\d{4,6}`）

### 輸出格式：`mc_pom_{year}.jsonl`

每行一筆 design，JSON 結構：

```json
{
  "_source_file": "ONY_638686982601810474.pdf",
  "_month": "5",
  "design_number": "D34117",
  "description": "Stretch To Fit MINIMAL BANDEAU TOP",
  "brand_division": "Old Navy Womens",
  "department": "Swim",
  "category": "KNITS",
  "sub_category": "",
  "item_type": "SWIM_TOP",
  "design_type": "Swim",
  "fit_camp": "",
  "collection": "SP26",
  "flow": "",
  "mcs": [
    {
      "mc_key": "MC_1",
      "body_type": "REGULAR",
      "status": "Adopted",
      "sizes": ["XS", "S", "M", "L", "XL", "XXL"],
      "poms": [
        {
          "POM_Code": "H2",
          "POM_Name": "Straight Waistband",
          "sizes": {
            "XS": "13 1⁄2",
            "S": "14 1⁄2",
            "M": "15 1⁄2",
            "L": "17 1⁄4",
            "XL": "19 1⁄2",
            "XXL": "22"
          },
          "tolerance": { "neg": "- 1/2", "pos": "1/2" }
        }
      ]
    }
  ]
}
```

### 目前資料量

| 年份 | PDF 數 | 萃取筆數 |
|------|--------|---------|
| 2024 | 499 | 499 |
| 2025 | 6,502 | 6,502 |
| 2026 | 5,037 | 5,037 |
| **合計** | **12,038** | **12,038** |

---

## Phase 2: 合併 + 建立 Profile

### 腳本：`rebuild_profiles.py`

**做什麼：** 把三年 JSONL 合併成一個統一的 profile 檔案，同時從 `brand_division` / `department` 推導 Gender。

**輸入：** `_parsed/mc_pom_combined.jsonl`（三年合併檔，由 cat 指令產生）

**處理邏輯：**
1. 讀取每筆 design 的 metadata
2. `extract_gender()` 從 brand_division 推導性別：
   - MATERNITY > BABY/TODDLER > GIRLS/BOYS/WOMENS/MENS
   - 如果 brand_division 沒線索，fallback 到 department
3. 整理 mc_poms（攤平 MC → POM 巢狀結構）
4. 收集所有 sizes 和 body_types

**輸出：** `measurement_profiles_union.json`

```json
{
  "source": "mc_pom_combined.jsonl",
  "total": 12038,
  "with_mc_pom": 1304,
  "profiles": [
    {
      "design_id": "D34117",
      "gender": "WOMENS",
      "item_type": "SWIM_TOP",
      "category": "KNITS",
      "department_raw": "Swim",
      "brand_division": "Old Navy Womens",
      "design_type": "Swim",
      "description": "...",
      "has_mc_pom": true,
      "mc_poms": [...],
      "sizes": ["XS", "S", "M", "L", "XL", "XXL"],
      "body_types": ["REGULAR"]
    }
  ]
}
```

**關鍵數字：** 12,038 total profiles，其中 1,304 有 MC+POM 數據（其餘 PDF 沒有尺寸表或尺寸表為空）。

---

## Phase 3: 分類 + 產出規則

### 腳本：`reclassify_and_rebuild.py`（核心腳本，24KB）

**做什麼：** 這是整條 pipeline 的心臟。對每個有 MC+POM 的 design 做三層分類，然後按 bucket 聚合產出統計規則。

### Step 3a: 三層分類器

對 1,304 個有數據的 design，排除 ATHLETA 品牌後剩 1,056 個，依序跑三個分類器：

**① `real_dept_v4()` — Department 分類（6 類）**

| Department | 邏輯 | 範例 |
|-----------|------|------|
| Swimwear | item_type 含 SWIM（排除 RASHGUARD）；或 dept=Swim 且非 Active 類 item_type | SWIM_TOP, SWIM_BOTTOM |
| Sleepwear | item_type 含 SLEEP 或 = SLEEPWEAR/LOUNGE | PJ SET, SLEEP PANT |
| Collaboration | dept = NFL / NBA / MISCSPORTS | NFL 聯名款 |
| Active | dept 含 PERFORMANCE ACTIVE / ACTIVE / FLEECE（無 SWIM）；或 category=IPSS | LEGGING, SPORT BRA |
| Fleece | dept 含 FLEECE（且非 Active 優先） | FLEECE HOODIE |
| RTW | 以上都不符合（預設） | 一般針織/梭織服飾 |

重要規則：
- ATHLETA 品牌在 load 階段就排除（Old Navy only）
- Maternity 是 **Gender** 不是 Department
- IPSS category → 強制歸 Active（運動專精 = Knit）

**② `infer_fabric()` — 面料推導（3 類）**

| 優先序 | 條件 | Fabric |
|--------|------|--------|
| 1 | category 開頭 IPSS | Knit |
| 2 | category 開頭 DENIM | Denim |
| 3 | category 開頭 KNITS | Knit |
| 4 | category 開頭 WOVEN | Woven |
| 5 | sub_category 含 TSD | Woven |
| 6 | dept 含 KNIT | Knit |
| 7 | dept 含 WOVEN | Woven |
| 8 | dept 含 DENIM | Denim |
| 9 | 以上都無 → 預設 | Woven |

**③ `real_gt_v2()` — Garment Type 分類（10 類 + UNKNOWN）**

優先順序：ROMPER_JUMPSUIT → BODYSUIT → SET → DRESS → LEGGINGS → SHORTS → SKIRT → PANTS → OUTERWEAR → TOP → UNKNOWN

從 `design_type` + `item_type` + `description` 三個欄位的關鍵字做比對。

### Step 3b: Bucket 分組

分類完成後，每個 design 得到一組 key：
```
{Gender}_{Department}_{Fabric}_{GT}
→ 如：womens_active_knit_LEGGINGS
```

Bucket 命名規則：`{gender}_{dept}_{gt}` 或 `{gender}_{dept}_{fabric}_{gt}`（如果 fabric 有區分價值的話）。

### Step 3c: POM 統計 + 規則產出

對每個 bucket 內的所有 design，統計每個 POM code 的：

| 統計項 | 計算方式 | 用途 |
|--------|---------|------|
| `rate` | 該 POM 出現在 bucket 內 design 的比率 (0~1) | 判斷 must/recommend/optional |
| `count` | 出現次數 | 樣本量信心度 |
| `median_values` | 各尺碼的中位數 | 預設尺寸建議值 |
| `tolerance` | pos/neg 中位數 | 預設公差建議值 |
| `grading_inches` | 相鄰尺碼間的跳檔量 | Grading 規則 |

**Tier 分級邏輯：**
- `must`：rate ≥ 0.7（超過 70% 的 design 都有這個 POM）
- `recommend`：0.3 ≤ rate < 0.7
- `optional`：rate < 0.3

### 輸出

**`pom_rules/*.json`**（83 個 bucket 檔案）— 每個檔案結構：

```json
{
  "bucket": "womens_active_knit_LEGGINGS",
  "gender": "WOMENS",
  "department": "Active",
  "fabric": "Knit",
  "garment_type": "LEGGINGS",
  "design_count": 45,
  "designs": ["D12345", "D23456", ...],
  "measurement_rules": {
    "must": {
      "H1": {
        "rate": 0.95,
        "count": 43,
        "name": "Waistband Height",
        "name_zh": "腰帶高",
        "median_values": { "XS": 2.5, "S": 2.5, "M": 2.5, "L": 2.5, ... },
        "tolerance": { "pos": "1/8", "neg": "1/8" },
        "grading_inches": [0, 0, 0, 0.25, 0.25]
      }
    },
    "recommend": { ... },
    "optional": { ... }
  },
  "pom_sort_order": ["H1", "H2", "K1", "K2", "L2", "L8", "N9", "O4", ...],
  "foundational_measurements": { "tier1_poms": [...], "enforced": true }
}
```

**`pom_rules/_index.json`** — 全局索引，列出所有 bucket 和 meta 資訊

**`design_classification_v5.json`** — 每個 design 的完整分類結果

---

## Phase 4: 後處理

### Step 4a: `enforce_tier1.py` — Tier 1 基礎量測點強制

**做什麼：** 確保每個 bucket 的 `must` tier 都包含「不管怎樣一定要量的基礎 POM」。

| 身體位置 | Tier 1 POMs | 適用 GT |
|----------|-------------|---------|
| Upper body | F10(胸圍), C1(肩寬), J9/J10(前後身長), E1(袖長), I5(下擺) | TOP, OUTERWEAR, DRESS |
| Lower body | H1(腰帶高), L2(臀圍位), L8(臀圍), K1/K2(前後襠), O4(內長), N9(腿口) | PANTS, LEGGINGS, SHORTS, SKIRT |
| Combined | 上 + 下全部 | ROMPER_JUMPSUIT, SET, BODYSUIT |

規則：
- 如果 Tier 1 POM 在 recommend/optional → 移到 must，標記 `tier1_enforced: true`
- 如果已在 must → 只加標記
- 如果完全不存在 → 跳過（不硬塞沒有的 POM）

### Step 4b: `fix_sort_order.py` — 量測點排序

**做什麼：** 依照成衣量測慣例，將 `pom_sort_order` 排成合理的身體部位順序。

Upper body 順序：領(B) → 肩(C) → 袖籠(D) → 胸(F) → 下擺(I) → 袖(E) → 身長(J) → 腰(H) → 口袋(P) → 繩帶(Q) → 釦(S) → 其他(Z)

Lower body 順序：腰帶(H) → 約克(G) → 門襟(R) → 襠(K) → 臀圍(L) → 三角(M) → 腿圍(N) → 內外長(O) → 口袋(P) → 繩帶(Q) → 釦(S) → 其他(Z)

同一區段內的 sub-order 也有定義（如 K1 前襠 → K6 → K2 後襠）。

---

## Phase 5: 延伸分析

統一腳本：`_parsed/rebuild_all_analysis_v2.py`，一次產出全部 6 個分析檔案。

所有分析都基於 `design_classification_v5.json` 的 v5.5.1 分類系統：
- **10 GT：** TOP, PANTS, LEGGINGS, SHORTS, SKIRT, OUTERWEAR, DRESS, SET, ROMPER_JUMPSUIT, BODYSUIT
- **7 Gender：** WOMENS, MENS, GIRLS, BOYS, BABY/TODDLER, MATERNITY, UNKNOWN
- **6 Department：** Active, RTW, Fleece, Swimwear, Sleepwear, Collaboration
- **3 Fabric：** Knit, Woven, Denim

Body type 對照：ONY 系統的 `MISSY` = 業界的 `REGULAR`（標準體型）。

### ① `gender_gt_pom_rules.json`

**分析什麼：** 跨 Department 看「同一個 Gender × GT 組合，POM 分佈有什麼共性」

**用途：** 當新 design 只知道 Gender + GT、還不確定 Department 時，可以用這個做初步推薦。

**分組 key：** `{Gender}|{GT}`，如 `WOMENS|LEGGINGS`、`BOYS|SHORTS`

**輸出：** 57 個 Gender×GT 組合（7 Gender × 11 GT 有數據的交集），297 個 median groups（進一步按 item_type 細分）。每組包含 must/recommend/optional 三層 POM 及其 median 數值。

**覆蓋 GT：** BODYSUIT, DRESS, LEGGINGS, OUTERWEAR, PANTS, ROMPER_JUMPSUIT, SET, SHORTS, SKIRT, TOP, UNKNOWN

### ② `grading_patterns.json`

**分析什麼：** 每個 Gender×GT 的 grading（尺碼間跳檔量）是否一致

**用途：** 自動填入 grading 值。inflection = 某個尺碼跳檔量突然變大的比率，越低表示 grading 越穩定。

**排除：** BABY/TODDLER（嬰幼兒尺碼系統為 NB/0-3M/3-6M 等月齡制，無法計算跳檔量）。最少需 3 個 design 的組合才納入計算。

**輸出：** 40 個 Gender×GT 組合，2,066 個 POM families，inflection rate 45.4%。

**覆蓋 GT：** 全部 11 個（含 UNKNOWN），排除 BABY/TODDLER 的組合。

### ③ `bodytype_variance.json`

**分析什麼：** REGULAR(MISSY) vs PETITE vs TALL vs PLUS 之間，同一個 POM 的數值差異有多大

**用途：** 判斷是否需要為不同 body type 建立獨立規則，還是用同一套 + offset。

**比較方式：** 每個 Gender×GT 組合中，取 M 碼數值比較（REGULAR vs 其他 body type），同時比較 grading pattern 是否相同。

**輸出：** 43 組比較（不限於 WOMENS，任何 Gender×GT 只要有多體型數據都會產出）。

**覆蓋 body type：** PETITE, PLUS, TALL（vs REGULAR/MISSY 基準）
**覆蓋 GT：** BODYSUIT, DRESS, LEGGINGS, OUTERWEAR, PANTS, ROMPER_JUMPSUIT, SET, SHORTS, TOP, UNKNOWN（SKIRT 因無多體型數據未產出）

### ④ `client_rules.json`

**分析什麼：** 跨年度（2024/2025/2026）同一個 bucket 的規則有沒有漂移

**用途：** 偵測客人是否改了 spec 標準。如果 2026 的 median 跟 2024 差很多（>0.1"），可能客人改了尺寸要求。

**分組 key：** 使用 v5.5.1 的 bucket key（如 `Active_LEGGINGS|WOMENS`），只取有 2 個以上年份數據的 bucket。

**輸出：** 68 個 bucket 有多年數據，其中 67 個偵測到有意義的漂移（>0.1"）。

### ⑤ `all_designs_gt_it_classification.json`

**分析什麼：** 對全量 design（含無 MC+POM 的）做 GT × IT 交叉分類

**用途：** 用於 Techpack Creation 的 Filter 維度（使用者選「我要做 LEGGINGS」→ 系統知道要推哪個 bucket 的規則）。

**範圍：** 全部 profile（排除 ATHLETA），不限於有 MC+POM 的 1,056 個。

**輸出：** 1,292 個 design 的分類結果。GT 分佈：TOP(392), PANTS(148), OUTERWEAR(146), DRESS(114), ROMPER_JUMPSUIT(113), SHORTS(111), LEGGINGS(111), UNKNOWN(85), SET(57), SKIRT(12), BODYSUIT(3)。

### ⑥ `construction_bridge_v6.json`（v6.1）

**分析什麼：** 從 `zone_construction_analysis_v2_1.json` 提取每個 GT 的 Zone → 做工方法 + ISO 碼對照

**用途：** 當 Techpack 要產出 Construction section 時，根據 GT 自動推薦每個部位的縫法。

**限制：** zone_construction_analysis 的原始資料用舊版 bucket key（`bottoms` 未拆分 LEGGINGS/SHORTS/SKIRT），因此只有 6 個 GT 有 construction 數據。LEGGINGS/SHORTS/SKIRT/ROMPER_JUMPSUIT/BODYSUIT 的做工數據混在 `bottoms`/`tops` 裡，需要未來重新萃取 construction 資料才能拆開。

**輸出：** 6 個 GT 有實際數據：DRESS(12 zones), OUTERWEAR(11 zones), PANTS(11 zones), SET(8 zones), TOP(11 zones), UNKNOWN(3 zones)。

---

## 完整執行順序

```bash
# Phase 1: 萃取（可重複跑，resume-safe）
python run_extract_new.py          # 2026
python run_extract_2025_seasonal.py # 2025

# Phase 2: 合併
cat _parsed/mc_pom_2024.jsonl _parsed/mc_pom_2025.jsonl _parsed/mc_pom_2026.jsonl > _parsed/mc_pom_combined.jsonl
python rebuild_profiles.py

# Phase 3: 分類 + 產出規則
python reclassify_and_rebuild.py

# Phase 4: 後處理
python enforce_tier1.py
python fix_sort_order.py

# Phase 5: 延伸分析（一支腳本產出全部 6 個檔案）
cd _parsed && python rebuild_all_analysis_v2.py
```

---

## 檔案總覽

| 檔案 | 階段 | 大小 | 用途 |
|------|------|------|------|
| `_parsed/mc_pom_2024.jsonl` | Phase 1 | 499 筆 | 2024 原始萃取 |
| `_parsed/mc_pom_2025.jsonl` | Phase 1 | 6,502 筆 | 2025 原始萃取 |
| `_parsed/mc_pom_2026.jsonl` | Phase 1 | 5,037 筆 | 2026 原始萃取 |
| `_parsed/mc_pom_combined.jsonl` | Phase 2 input | 12,038 筆 | 三年合併 |
| `measurement_profiles_union.json` | Phase 2 output | 1,304 有數據 | 統一 profile |
| `pom_rules/*.json` (83 files) | Phase 3+4 | ~1.8MB | **核心產出：各 bucket 量測規則** |
| `pom_rules/_index.json` | Phase 3 | — | 全局索引 |
| `design_classification_v5.json` | Phase 3 | 1,056 筆 | 分類結果 |
| `pom_dictionary.json` | 輔助 | — | POM code ↔ 中英文名 |
| `_parsed/rebuild_all_analysis_v2.py` | Phase 5 腳本 | — | 一次產出下列 6 個分析檔 |
| `_parsed/gender_gt_pom_rules.json` | Phase 5① | 57 組合, 297 median groups | 跨 dept 共性規則 |
| `_parsed/grading_patterns.json` | Phase 5② | 40 組合, 2,066 POM families | 跳檔模式分析 (inflection 45.4%) |
| `_parsed/bodytype_variance.json` | Phase 5③ | 43 比較 | 體型差異分析 (MISSY=REGULAR) |
| `_parsed/client_rules.json` | Phase 5④ | 68 buckets | 跨年度漂移偵測 (67 有漂移) |
| `_parsed/all_designs_gt_it_classification.json` | Phase 5⑤ | 1,292 筆 | GT×IT 交叉分類 (排除 ATHLETA) |
| `_parsed/construction_bridge_v6.json` | Phase 5⑥ | 6 GT (v6.1) | 做工 ISO 對照橋 (受限舊版 zone 資料) |
