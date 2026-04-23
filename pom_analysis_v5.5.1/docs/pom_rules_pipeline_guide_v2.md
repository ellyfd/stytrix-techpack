# POM Rules Pipeline v5.5.1 — 自動化規格書

> **目的：** 任何新進 PDF 資料（新季度、新年度、新客人）都能按此規格自動跑完全流程，產出 UI 可直接使用的 bucket files + bodytype_variance + pom_dictionary。
>
> **正本位置：** `pom_analysis_v5.5.1/docs/pom_rules_pipeline_guide_v2.md`
> **所有腳本：** `pom_analysis_v5.5.1/scripts/`
> **所有產出：** `pom_analysis_v5.5.1/data/` + `pom_rules/`

---

## 全局架構

```
新 PDF 放入年份資料夾
  │
  ▼
Phase 1 ─ Extract ──────── mc_pom_{year}.jsonl        [增量，resume-safe]
  │
  ▼
Phase 2 ─ Profile ──────── measurement_profiles.jsonl  [全量重建]
  │
  ▼
Phase 3 ─ Classify+Rules ─ pom_rules/*.json (buckets)  [全量重建]
  │                         design_classification.json
  ▼
Phase 4 ─ Post-process ─── pom_rules/*.json (原地更新)  [全量重建]
  │
  ▼
Phase 5 ─ Analysis ──────── bodytype_variance.json      [全量重建]
  │                          + 5 支 QA 分析
  ▼
Phase 6 ─ UI 消費 ──────── Filter → bucket → render    [唯讀]
```

**核心原則：Phase 1 增量萃取，Phase 2~5 全量重建。** 資料量（~12K designs）不大，全量重建 < 5 分鐘，不需要差異更新的複雜度。

---

## 資料夾結構

```
ONY/
├── 2024/                          ← 原始 PDF（月份資料夾 1~12）
├── 2025/                          ← 原始 PDF（季節 SP25/SU25/FA25/HO25）
├── 2026/                          ← 原始 PDF（季節 SP26/SU26/FA26/HO26/SP27）
├── 202X/                          ← 未來年份照同結構放入
│
├── pom_rules/                     ← Phase 3+4 產出（UI 直接讀取）
│   ├── _index.json                   全局索引
│   └── {bucket}.json (N files)       各 bucket 規則
│
├── pom_analysis_v5.5.1/
│   ├── scripts/                   ← 所有腳本
│   │   ├── run_extract.py            Phase 1: PDF 萃取（通用，帶年份參數）
│   │   ├── rebuild_profiles.py       Phase 2: 合併 profile
│   │   ├── reclassify_and_rebuild.py Phase 3: 分類 + 規則
│   │   ├── enforce_tier1.py          Phase 4a: Tier1 強制
│   │   ├── fix_sort_order.py         Phase 4b: 排序修正
│   │   ├── rebuild_all_analysis_v2.py Phase 5: 延伸分析（①③④⑤⑥）
│   │   └── rebuild_grading_3d.py     Phase 5②: grading_patterns 3D 重建
│   ├── data/                      ← Phase 3+5 產出
│   │   ├── design_classification_v5.json
│   │   ├── bodytype_variance.json    ★ UI 用
│   │   ├── pom_dictionary.json       ★ UI 用
│   │   ├── gender_gt_pom_rules.json  (QA)
│   │   ├── grading_patterns.json     ★ UI 用（3D: Dept_GT|Gender）
│   │   ├── client_rules.json         (QA)
│   │   └── all_designs_gt_it_classification.json (QA)
│   ├── pom_rules/                 ← Phase 3+4 產出的備份
│   ├── bridge/                    ← 做工 ISO 對照
│   └── docs/
│       └── pom_rules_pipeline_guide_v2.md  ← 本文件
│
└── _parsed/                       ← Phase 1 萃取暫存
    ├── mc_pom_2024.jsonl
    ├── mc_pom_2025.jsonl
    ├── mc_pom_2026.jsonl
    └── mc_pom_combined.jsonl
```

---

## 自動化執行（一鍵全流程）

```bash
BASE=/path/to/ONY
SCRIPTS=$BASE/pom_analysis_v5.5.1/scripts
PARSED=$BASE/_parsed

# ── Phase 1: 萃取新 PDF（增量，自動跳過已處理）──
python $SCRIPTS/run_extract.py 2024
python $SCRIPTS/run_extract.py 2025
python $SCRIPTS/run_extract.py 2026

# ── Phase 2: 合併三年 JSONL + 建立 Profile ──
cat $PARSED/mc_pom_*.jsonl > $PARSED/mc_pom_combined.jsonl  # 自動涵蓋所有年份
python $SCRIPTS/rebuild_profiles.py

# ── Phase 3: 分類 + 產出 bucket rules ──
python $SCRIPTS/reclassify_and_rebuild.py

# ── Phase 4: 後處理 ──
python $SCRIPTS/enforce_tier1.py
python $SCRIPTS/fix_sort_order.py

# ── Phase 5: 延伸分析 ──
python $SCRIPTS/rebuild_all_analysis_v2.py   # ①③④⑤⑥
python $SCRIPTS/rebuild_grading_3d.py        # ② grading_patterns (3D)
```

### 新增年份時

1. 建立 `ONY/202X/` 資料夾，將 PDF 放入月份或季節子資料夾
2. 執行 `python $SCRIPTS/run_extract.py 202X`
3. 跑 Phase 2~5 全流程

### 新增季度時

1. 將 PDF 放入對應年份資料夾（如 `2026/HO26/`）
2. 直接跑全流程（Phase 1 會自動偵測新檔案）

---

## Phase 1: PDF 萃取

### 輸入

Centric PLM 匯出的 Techpack PDF，每個 design 一份。放入年份資料夾即可。

### 萃取邏輯

| PDF 區塊 | 萃取欄位 | 用途 |
|-----------|---------|------|
| Header / Meta | Design Number, Description, Brand/Division, Department, Category, Sub_Category, Item Type, Design Type, Fit Camp, Collection, Flow | 身份識別 + 分類 |
| MC Table | MC Key, Body Type, Status, Sizes | 尺寸表識別。一個 design 可能有多張 MC（REGULAR / PETITE / TALL / PLUS） |
| POM Rows | POM_Code, POM_Name, sizes (各尺碼數值), tolerance (pos/neg) | 量測點數值 + 公差 |
| Construction / ISO | 車縫做工、ISO 縫法代碼 | Construction Bridge（Phase 5⑥） |

### 腳本

`run_extract_new.py` — 掃描所有年份資料夾，自動跳過已處理檔案（比對 `_source_file`）。540 秒 timeout 保護，下次接續。

### 輸出格式：`mc_pom_{year}.jsonl`

每行一筆 design：

```json
{
  "_source_file": "ONY_638686982601810474.pdf",
  "design_number": "D34117",
  "description": "Stretch To Fit MINIMAL BANDEAU TOP",
  "brand_division": "Old Navy Womens",
  "department": "Swim",
  "category": "KNITS",
  "item_type": "SWIM_TOP",
  "design_type": "Swim",
  "collection": "SP26",
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
          "sizes": { "XS": "13 1⁄2", "S": "14 1⁄2", "M": "15 1⁄2", ... },
          "tolerance": { "neg": "- 1/2", "pos": "1/2" }
        }
      ]
    }
  ]
}
```

### 驗證閘

- 每年萃取完後檢查：`wc -l mc_pom_{year}.jsonl` 應 ≥ 前次數量
- 抽查 5 筆：`design_number` 非空、`mcs` array 非空、至少一個 `poms` 有 `sizes`

---

## Phase 2: 合併 + 建立 Profile

### 腳本：`rebuild_profiles.py`

### 輸入 → 輸出

```
mc_pom_combined.jsonl → measurement_profiles_union.json
```

### 處理邏輯

1. 讀取每筆 design 的 metadata
2. `extract_gender()` 從 brand_division 推導性別：MATERNITY > BABY/TODDLER > GIRLS/BOYS/WOMENS/MENS（fallback 到 department）
3. 攤平 MC → POM 巢狀結構為 `mc_poms[]` flat array
4. 標記 `has_mc_pom: true/false`

### Profile 結構

```json
{
  "design_id": "D34117",
  "gender": "WOMENS",
  "item_type": "SWIM_TOP",
  "department_raw": "Swim",
  "brand_division": "Old Navy Womens",
  "has_mc_pom": true,
  "mc_poms": [
    { "code": "H2", "body_type": "REGULAR", "sizes": {"XS":"13.5", ...} }
  ],
  "sizes": ["XS","S","M","L","XL","XXL"],
  "body_types": ["REGULAR"]
}
```

### 驗證閘

- `total` = `mc_pom_combined.jsonl` 行數
- `with_mc_pom` count > 0（目前 ~1,304）

---

## Phase 3: 分類 + 產出規則

### 腳本：`reclassify_and_rebuild.py`（核心腳本）

### 輸入

- `measurement_profiles_union.json`（Phase 2 產出）

### Step 3a: 三層分類器

對有 MC+POM 的 design（排除 ATHLETA）依序跑三個分類器：

**① Department（6 類）：** Swimwear → Sleepwear → Collaboration → Active → Fleece → RTW（預設）

| Department | 判定邏輯 |
|-----------|---------|
| Swimwear | item_type 含 SWIM（排除 RASHGUARD）；或 dept=Swim 且非 Active 類 |
| Sleepwear | item_type 含 SLEEP 或 = SLEEPWEAR/LOUNGE |
| Collaboration | dept = NFL / NBA / MISCSPORTS |
| Active | dept 含 PERFORMANCE ACTIVE / ACTIVE / FLEECE（無 SWIM）；或 category=IPSS |
| Fleece | dept 含 FLEECE（且非 Active 優先） |
| RTW | 預設 |

注意：ATHLETA 品牌在 load 階段排除（Old Navy only）。Maternity 是 Gender 不是 Department。IPSS category → 強制 Active。

**② Fabric（3 類）：** 優先序 IPSS→Knit > DENIM > KNITS→Knit > WOVEN > TSD→Woven > dept 關鍵字 > 預設 Woven

**③ Garment Type（10 類 + UNKNOWN）：** 從 design_type + item_type + description 關鍵字比對。優先序：ROMPER_JUMPSUIT → BODYSUIT → SET → DRESS → LEGGINGS → SHORTS → SKIRT → PANTS → OUTERWEAR → TOP → UNKNOWN

### Step 3b: Bucket 分組

```
Bucket key = {Department}_{GT}|{Gender}
Bucket file = {gender}_{dept}_{gt}.json
範例：Active_LEGGINGS|WOMENS → womens_active_leggings.json
```

### Step 3c: POM 統計

每個 bucket 內，統計每個 POM code：

| 統計 | 計算 | 用途 |
|------|------|------|
| rate | POM 出現比率 (0~1) | Tier 分級 |
| count | 出現次數 | 信心度 |
| median_values | 各尺碼中位數 | 建議值 |
| tolerance | pos/neg 中位數 | 公差建議 |
| grading | 相鄰尺碼跳檔量 | Grading 規則 |

**Tier 分級：** must (rate ≥ 0.7) → recommend (0.3~0.7) → optional (< 0.3)

### 輸出

**`pom_rules/{bucket}.json`** — bucket file 結構：

```json
{
  "bucket": "Active_LEGGINGS|WOMENS",
  "gender": "WOMENS",
  "department": "Active",
  "garment_type": "LEGGINGS",
  "n": 75,
  "size_range": ["XXS","XS","S","M","L","XL","XXL","2X","3X","4X"],
  "measurement_rules": {
    "must":      { "H1": { "rate": 0.813, "count": 61, "tolerance": {...}, "tier1_enforced": true } },
    "recommend": { ... },
    "optional":  { ... }
  },
  "median_values":       { "H1": { "size_medians": {"XXS":1.5, "XS":1.5, "S":1.5, "M":1.5, ...} } },
  "grading_rules":       { "H1": { "typical_increment": 0.0, "n_pairs": 259 } },
  "tolerance_standards": { "H1": { "standard": 0.125, "display": "1/8", "dominance_pct": 100.0, "n": 58 } },
  "foundational_measurements": { "tier1_poms": ["H1","L2","L8","K1","K2","O4","N9"], "enforced": true },
  "pom_sort_order": ["H1","H2","H8","H9","H20",...],
  "matched_designs": {
    "count": 75,
    "designs": [ {"design_id":"D1245", "item_type":"", "description":"...", "design_type":"Legging"}, ... ]
  }
}
```

注意：`median_values`、`grading_rules`、`tolerance_standards` 是獨立 top-level key，不嵌在 `measurement_rules` 裡。

**`pom_rules/_index.json`** — 每個 bucket 一筆：

```json
{"bucket":"Active_LEGGINGS|WOMENS", "file":"womens_active_leggings.json", "n":75,
 "department":"Active", "garment_type":"LEGGINGS", "gender":"WOMENS",
 "pom_count":142, "must_count":9, "size_kb":52.5}
```

**`design_classification_v5.json`** — 每個 design 的完整分類結果

### 驗證閘

- bucket 檔案數 ≥ 前次（目前 83）
- 每個 bucket 的 `n` ≥ 2（n=1 不產出）
- `_index.json` 筆數 = bucket 檔案數

---

## Phase 4: 後處理

### 4a: `enforce_tier1.py` — 基礎量測點強制

確保每個 bucket 的 must tier 包含該 GT 的基礎 POM：

| 適用 GT | Tier 1 POMs |
|---------|------------|
| TOP, OUTERWEAR, DRESS | F10(胸圍), C1(肩寬), J9/J10(前後身長), E1(袖長), I5(下擺) |
| PANTS, LEGGINGS, SHORTS, SKIRT | H1(腰帶高), L2(臀圍位), L8(臀圍), K1/K2(前後檔), O4(內長), N9(褲口) |
| ROMPER_JUMPSUIT, SET, BODYSUIT | 上 + 下全部 |

規則：recommend/optional 中的 Tier 1 POM → 移到 must 並標記 `tier1_enforced: true`。完全不存在的 POM 不硬塞。

### 4b: `fix_sort_order.py` — 量測點排序

依成衣量測慣例排序 `pom_sort_order`：

- Upper body：領(B) → 肩(C) → 袖籠(D) → 胸(F) → 下擺(I) → 袖(E) → 身長(J) → 腰(H)
- Lower body：腰帶(H) → 約克(G) → 門襟(R) → 檔(K) → 臀圍(L) → 三角(M) → 腿圍(N) → 內外長(O)
- 共用尾段：口袋(P) → 繩帶(Q) → 釦(S) → 其他(Z)

### 驗證閘

- 所有 bucket file 的 `foundational_measurements.enforced` = true
- `pom_sort_order` 長度 = `measurement_rules` 裡所有 POM code 的數量

---

## Phase 5: 延伸分析

### 腳本：`rebuild_all_analysis_v2.py`

一次產出 6 個分析檔案。分類系統：10 GT × 7 Gender × 6 Department × 3 Fabric。Body type 對照：MISSY = REGULAR。

### ① `gender_gt_pom_rules.json`（QA 用）

跨 Department 看同一個 Gender × GT 的 POM 共性。57 個組合、297 median groups。

### ② `grading_patterns.json` ★ UI 用

**做什麼：** 記錄每個 POM（量測部位）在「相鄰尺碼之間跳多少」。例如 B25（胸圍）從 S 到 M 跳 0.25 吋、從 M 到 L 也跳 0.25 吋。前端展開全碼表時，就是用這份資料算出每個尺碼的值。

**腳本：** `rebuild_grading_3d.py`

**分類方式：Department × 款型 × 性別**（跟 pom_rules 的 bucket 完全對齊）。

舉例說明差異：

| 情境 | 舊版怎麼查 | 新版怎麼查 |
|------|-----------|-----------|
| RTW 女裝 TOP | `WOMENS|TOP`（所有 Dept 混在一起） | `RTW_TOP|WOMENS`（只看 RTW） |
| Active 女裝 LEGGINGS | 同上混算 | `Active_LEGGINGS|WOMENS` |
| 孕婦 Active LEGGINGS | 強制當成 WOMENS 查 | `Active_LEGGINGS|MATERNITY`（獨立資料） |
| 嬰幼兒 RTW SET | 查不到（直接跳過） | `RTW_SET|BABY/TODDLER`（有資料了） |

這很重要，因為同樣是 TOP，Active 運動上衣和 RTW 休閒上衣的跳檔規則本來就不一樣（彈性布 vs 梭織），混在一起算會失真。

**資料範例：**
```json
{
  "RTW_TOP|WOMENS": {
    "B25": {
      "pairs": {
        "XXS→XS": {"median": 0.0, "n": 66},
        "XS→S":   {"median": 0.25, "n": 71},
        "S→M":    {"median": 0.25, "n": 69}
      },
      "inflection": false
    }
  }
}
```
讀法：B25（胸圍）從 XS 跳到 S 的中位數是 +0.25 吋，這個數字來自 71 款設計的統計。`inflection: false` 表示各碼之間的跳幅一致（線性跳檔）；如果是 `true`，代表某些尺碼之間跳幅突然變大或變小，編輯時要特別注意。

**樣本不足時的處理：** 如果某個 Department × 款型 × 性別 的設計數不到 3 款，就退一層用「同款型 × 同性別、跨 Department」的統計值代替，不會讓系統出現空白。

**統計：** 145 組合、5,670 個量測部位、81/81 bucket 全部覆蓋。其中 BABY/TODDLER 有 25 組合（尺碼 2T→3T→4T→5T）。

**關於 Knit / Woven：** 目前的分類軸是 Department（Active / RTW / Swimwear…），不是 Fabric（Knit / Woven）。雖然針織和梭織的跳檔行為不同，但 pom_rules 的 bucket 本身也不切 fabric，所以這裡保持一致。未來如果 bucket 加入 fabric 區分，這邊會跟著升級。

### ③ `bodytype_variance.json` ★ UI 用

**目的：** 計算 REGULAR vs PETITE/TALL/PLUS 的尺寸差異，供 UI 切換 body type。

**方法：Same-design paired comparison。** 只從同一個 design 內同時有 REGULAR 和目標 body type 的 MC 才納入，避免不同款式混在一起造成假差異。每個 POM 的 delta = 所有配對設計 delta 的 median。要求 n_pairs ≥ 2。

**資料來源：** 直接讀取 `mc_pom_{year}.jsonl`，結合 `design_classification_v5.json` 做 Gender|GT 分組。不依賴 `measurement_profiles_union.json`。

> ⚠️ **注意：** `rebuild_all_analysis_v2.py` 裡的 ③ bodytype 區段仍是舊版 unpaired 邏輯。正確的 paired comparison 邏輯如下，需更新腳本：

**Paired comparison 演算法：**

```python
for each Gender|GT combo:
  for each body_type in [PETITE, TALL, PLUS]:
    for each mc_pom record in this combo:
      bt_data = extract per-body-type POM values from this record
      regular = bt_data['REGULAR']
      variant = bt_data[body_type]
      if both exist:
        for each shared POM code:
          # M-size: paired delta
          delta = variant[code]['M'] - regular[code]['M']
          collect delta

          # Grading: paired arrays
          reg_grading = [size_i+1 - size_i for adjacent sizes in regular]
          bt_grading  = [size_i+1 - size_i for adjacent sizes in variant]
          collect both arrays

    # Aggregate: median of paired values
    m_comparison[code] = {
      delta: median(all deltas),
      n_pairs: count
    }
    grading_deltas[code] = {
      regular_grading: element-wise median of reg arrays,
      {bt}_grading: element-wise median of bt arrays,
      same_pattern: (reg_median == bt_median),
      n_pairs: count
    }
```

**Key 格式：** `{GENDER}|{GT}|{BODYTYPE}`

**每組結構：**

```json
{
  "m_size_comparison": {
    "O4": { "delta": 3.0, "n_pairs": 85 },
    "N9": { "delta": 0.0, "n_pairs": 45 }
  },
  "grading_deltas": {
    "O4": {
      "regular_grading": [0.0, 0.0, 0.0, 0.0, 0.0],
      "tall_grading": [-0.25, 0.0, 0.0, 0.0, 0.0],
      "same_pattern": false,
      "n_pairs": 85
    }
  }
}
```

`m_size_comparison` 只存 `delta` + `n_pairs`，不存絕對值（避免 UI 誤用不同母體的 M 值）。`grading_deltas` 的 array 欄位名稱隨 body type 變化：`plus_grading`、`tall_grading`、`petite_grading`，都對比 `regular_grading`。

**統計：** same_pattern = true 佔 69.6%。差異集中在長度類 POM：PETITE O4(內長) **-2"**、TALL O4(內長) **+3"**、TALL K2(後檔) 偶有 +1"。其餘 POM 幾乎零差異。

**輸出：** 45 組比較。覆蓋 PETITE(10)、TALL(11)、PLUS(24)。

### ④ `client_rules.json`（QA 用）

跨年度漂移偵測。68 buckets 有多年數據，67 個有 > 0.1" 的漂移。

### ⑤ `all_designs_gt_it_classification.json`（QA 用）

全量 GT×IT 分類。1,292 筆（含無 MC+POM 的 design）。

### ⑥ `construction_bridge_v6.json`（QA 用）

GT → Zone → 做工 + ISO 碼。受限舊版 zone 資料，目前只有 6 GT。

### Phase 5 驗證閘

- `bodytype_variance.json` 的 PETITE O4 delta 全部 ≤ 0（更��或相同）
- `bodytype_variance.json` 的 TALL O4 delta 全部 ≥ 0（更��或相同）
- `bodytype_variance.json` 所有 `n_pairs` ≥ 2
- `grading_patterns.json` pom_rules coverage = 81/81（100%）
- `grading_patterns.json` 包含 BABY/TODDLER combos（≥10）
- `grading_patterns.json` 每筆 POM 使用 `pairs` key（不是 `steps`）
- `grading_patterns.json` 每筆有 `_meta.source`（direct / fallback / 2d_compat）

---

## Phase 6: UI 資料流（Filter → Render）

### UI 需要的 3 種檔案

| 檔案 | 用途 | 載入時機 |
|------|------|----------|
| `pom_rules/_index.json` | Filter → 找 bucket file | App 初始化 |
| `pom_rules/{bucket}.json` | POM 清單 + 基碼 + 跳檔 + 公差 + 歷史款 | Lazy load（選完 filter 後） |
| `pom_analysis_v5.5.1/data/pom_dictionary.json` | POM code → 中英文名 | App 初始化 |
| `pom_analysis_v5.5.1/data/bodytype_variance.json` | Body type delta + grading 覆寫 | ��� non-MISSY 時 |
| `pom_analysis_v5.5.1/data/grading_patterns.json` | 全碼頁跳檔運算（3D: Dept_GT\|Gender） | 展開全碼時 |

### 資料流

```
user picks Gender + Dept + GT + (BodyType)
       ↓
_index.json → find bucket entry (match gender + department + garment_type)
       ↓
lazy-load pom_rules/<file>.json
       ↓
render POMs by pom_sort_order:

  for each POM code:
    tier       = which key in measurement_rules.{must|recommend|optional}
    display    = pom_dictionary[code].zh || pom_dictionary[code].en || code
    medians    = median_values[code].size_medians
    increment  = grading_rules[code].typical_increment
    tolerance  = tolerance_standards[code].display
    rate       = measurement_rules[tier][code].rate
    is_tier1   = code in foundational_measurements.tier1_poms

    badge:
      ★ foundational    (cyan, 不可隱藏)
      ● must (rate %)   (red)
      ○ recommend       (amber)
      · optional        (grey)
       ↓
if bodytype == MISSY:
  render as-is, done.

else (PLUS / TALL / PETITE):
  key = gender + "|" + gt + "|" + bodytype
  variance = bodytype_variance[key]
  if !variance: render as MISSY, done.

  bt_prefix = bodytype.toLowerCase()    // "plus" | "tall" | "petite"

  for each POM row:
    // (a) M-size 基準值調整（bucket median + delta）
    msc = variance.m_size_comparison[POM]
    if msc && abs(msc.delta) > 0:
      baseM_adjusted = bucket.median_values[POM].size_medians.M + msc.delta
      show "M: 31.0 (+3.0)" 小字註

    // (b) 跳檔序列覆寫
    gd = variance.grading_deltas[POM]
    if gd && !gd.same_pattern:
      use gd[bt_prefix + "_grading"] array directly
      (取代 bucket 的 grading_rules.typical_increment)
      可 tooltip 對比 regular_grading
    else if gd && gd.same_pattern:
      直接用 bucket 的 typical_increment
```

### POM 名稱查找順序

```
pom_dictionary[code].zh  →  pom_dictionary[code].en  →  code
```

`pom_dictionary.json` 為 primary，`pom_rules/pom_names.json` 為 fallback。

### 不進 UI 的 QA 檔案

| 檔案 | 用途 |
|------|------|
| `gender_gt_pom_rules.json` | 跨 dept 共性分析 |
| `client_rules.json` | 跨年度漂移偵測 |
| `all_designs_gt_it_classification.json` | GT×IT 交叉分類 |
| `construction_bridge_v6.json` | 做工 ISO 對照 |

---

## 分類系統速查

### Garment Type（10 類）

| GT | 代表 Item Type |
|----|---------------|
| TOP | Tee, Pullover, Henley, Sport Bra, Tank |
| PANTS | Pant, Jogger |
| LEGGINGS | Legging, 7/8, Capri |
| SHORTS | Short |
| SKIRT | Skirt |
| OUTERWEAR | Hoodie, Jacket, Vest |
| DRESS | Dress |
| SET | Set, PJ Set, Sleepwear Set |
| ROMPER_JUMPSUIT | Romper, Jumpsuit, Bodysuit Dress |
| BODYSUIT | Bodysuit |

### Gender（7 類）

WOMENS, MENS, GIRLS, BOYS, BABY/TODDLER, MATERNITY, UNKNOWN

### Department（6 類）

Active, RTW, Fleece, Swimwear, Sleepwear, Collaboration

### Body Type 對照

| ONY 系統 | Pipeline 標準化 | 說明 |
|----------|----------------|------|
| MISSY, MISSY-R, 空白 | REGULAR | 標準體型（基準） |
| PETITE | PETITE | 嬌小體型 |
| TALL | TALL | 高挑體型 |
| PLUS, 2X/3X/4X | PLUS | 加大體型 |

---

## 檔案總覽

| 檔案 | 階段 | 說明 |
|------|------|------|
| `_parsed/mc_pom_{year}.jsonl` | Phase 1 | 原始萃取（增量） |
| `_parsed/mc_pom_combined.jsonl` | Phase 2 input | 三年合併 |
| `measurement_profiles_union.json` | Phase 2 output | 統一 profile（Phase 3 input） |
| `pom_rules/*.json` | Phase 3+4 | **★ UI 核心：bucket 規則 + matched_designs** |
| `pom_rules/_index.json` | Phase 3 | **★ UI：全局索引** |
| `data/design_classification_v5.json` | Phase 3 | 分類結果（matched_designs 來源） |
| `data/pom_dictionary.json` | 輔助 | **★ UI：POM code ↔ 中英文名** |
| `data/bodytype_variance.json` | Phase 5③ | **★ UI：體型差異（paired comparison）** |
| `data/gender_gt_pom_rules.json` | Phase 5① | QA：跨 dept 共性 |
| `data/grading_patterns.json` | Phase 5② | **★ UI：全碼跳檔運算（3D Dept_GT\|Gender, 145 combos）** |
| `data/client_rules.json` | Phase 5④ | QA：跨年度漂移 |
| `data/all_designs_gt_it_classification.json` | Phase 5⑤ | QA：GT×IT 分類 |
| `bridge/construction_bridge_v6.json` | Phase 5⑥ | QA：做工 ISO 對照 |
