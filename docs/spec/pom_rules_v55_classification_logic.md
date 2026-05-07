# pom_rules v5.5 完整分類邏輯（v5.5.1 updated 2026-04-20）

---

## 一、資料來源（從 Centric 8 PDF 提取）

每份 PDF 提取兩組資料：

### A. Metadata（page 2-3 table）

| 欄位 | PDF 表格 key | 範例值 | 用途 |
|------|-------------|--------|------|
| `design_number` | Design Number | D87501 | 唯一識別碼 |
| `description` | Description | SPD SMOCKED SHOULDER PEPLUM BLOUSE | GT fallback 關鍵字來源 |
| `brand_division` | Brand/Division | OLD NAVY - WOMENS | **→ Gender 分類** |
| `department` | Department | WOMENS PERFORMANCE ACTIVE | **→ Department 分類** |
| `category` | Category | IPSS / KNITS / WOVEN | **→ Fabric 分類** |
| `sub_category` | Sub-Category | WOVEN TSD | **→ Fabric 分類**（TSD=平織） |
| `item_type` | Item Type | LEGGINGS _ L2 | **→ GT 分類 + 前端 IT filter + Department 優先判斷** |
| `design_type` | Design Sub-Type | Top / Pant / Dress | **→ GT 分類** |
| `fit_camp` | Fit Camp | MAKALOT INDUSTRIAL CO LTD | 工廠 |
| `collection` | Collection | WOMENS WOVEN TOPS | 參考 |
| `flow` | Flow | April | 參考 |

> **提取邏輯**（`extract_techpack.py` line 96-133）：
> 1. 用 pdfplumber 讀 page 2-3 的 table rows
> 2. 每 row 的 `row[0]` = key，`row[1]` = value
> 3. 用 `key.lower()` 比對欄位名（如 `'item type'`、`'department'`）
> 4. 如果 table 沒找到，fallback 用 regex 在 plain text 中搜尋

> **Metadata 合併**（`run_extract_mc.py` line 64-80）：
> `all_years.jsonl`（Centric 8 匯出 CSV）的值**優先**，PDF 提取值作為 fallback

### B. MC + POM 數據（Measurement Chart 頁）

| 欄位 | 來源 | 範例值 |
|------|------|--------|
| `mc_key` | MC 頁 header | D87501 MC Makalot - M IN WORK |
| `body_type` | 從 mc_key 解析 | MISSY / PLUS / PETITE / TALL |
| `status` | 從 mc_key 解析 | Final / IN WORK |
| `sizes` | MC 欄頭 | [XXS, XS, S, M, L, XL, XXL] |
| `poms[].POM_Code` | MC 第一欄 | J9 / F10 / H1 |
| `poms[].POM_Name` | MC 第二欄 | CF Body Length from HPS... |
| `poms[].sizes` | MC 各 size 欄 | {"XS": "3⁄ 20 8", "M": "22", ...} |
| `poms[].tolerance` | MC tolerance 欄 | {"neg": "- 1/2", "pos": "1/2"} |

---

## 二、Gender 分類（7 類）

**輸入欄位**：`brand_division`（主），`department`（fallback）

**邏輯**（`rebuild_profiles.py` → `extract_gender()`）：

```
Step 1: 從 brand_division 提取
  含 MATERNITY        → MATERNITY     （最高優先，作工與 WOMENS 不同）
  含 BABY 或 TODDLER  → BABY/TODDLER
  含 GIRLS            → GIRLS
  含 BOYS             → BOYS
  含 WOMENS           → WOMENS
  含 MENS             → MENS

Step 2: brand_division 沒命中 → fallback 到 department
  含 TODDLER 或 BABY  → BABY/TODDLER
  含 BOYS             → BOYS
  含 GIRLS            → GIRLS
  含 WOMENS 或 WOMEN  → WOMENS
  含 MENS 或 ' MEN'   → MENS

Step 3: 都沒命中 → UNKNOWN
```

**完整對照表**：

| brand_division 值 | → Gender |
|---|---|
| OLD NAVY - MATERNITY | MATERNITY |
| OLD NAVY - BABY/TODDLER | BABY/TODDLER |
| GAP - BABY | BABY/TODDLER（含 BABY） |
| OLD NAVY - GIRLS / GAP - GIRLS | GIRLS |
| OLD NAVY - BOYS / GAP - BOYS | BOYS |
| OLD NAVY - WOMENS / GAP - WOMENS / BRFS - WOMENS | WOMENS |
| OLD NAVY - MENS / GAP - MENS | MENS |
| OLD NAVY - FUNZONE / 空白 / 解析錯誤 | UNKNOWN |

> ⚠️ ATHLETA 品牌已排除。本規則庫僅適用 Old Navy（含少量 GAP/BRFS 共用 Tech Pack）。

**分佈**（1,056 designs，排除 ATHLETA）：WOMENS 539 / GIRLS 135 / MENS 130 / BABY/TODDLER 100 / BOYS 58 / MATERNITY 56 / UNKNOWN 38

---

## 三、Department 分類（6 類）

**輸入欄位**：`item_type`（主），`department`（次），`category`（IPSS 規則），`design_type`（fallback）

> ⚠️ v5.5 起 Maternity **不是** Department。MATERNITY 只影響 Gender。
> ⚠️ v5.5.1 起排除 ATHLETA 品牌（本規則庫僅適用 Old Navy）。

**邏輯**（`reclassify_and_rebuild.py` → `real_dept_v4()`）：

```
Step 0: 品牌過濾
  brand_division 含 ATHLETA → 排除（不進入分類）

Step 1: item_type 優先判斷（最高優先，覆蓋 department 名稱不準的情況）
  item_type 含 SWIM 且不含 RASHGUARD  → Swimwear
  item_type 含 SLEEP 或 = SLEEPWEAR/LOUNGE  → Sleepwear

Step 2: Collaboration（在 dept 關鍵字之前攔截）
  department = NFL / NBA / MISCSPORTS  → Collaboration

Step 3: department 欄位解析
  department 含 PERFORMANCE + ACTIVE  → Active
  department 含 ACTIVE               → Active
  department 含 FLEECE               → Fleece
  department 含 SLEEP                → Sleepwear
  department 含 SWIM                 → 再看 item_type：
    item_type 像 Active（TOP/PANT/LEGGING/PULLOVER/JACKET/SHORT/
      HOODIE/FLEECE/POLO/TEE/HENLEY/SHIRT/DRESS/SPORT BRA/GRAPHIC）→ Active
    否則 → Swimwear

Step 4: category = IPSS → Active（運動專精，布料=Knit）

Step 5: design_type fallback
  design_type = SWIM 或 SWIM/SPORT    → Swimwear
  design_type = SLEEPWEAR 或 SLEEP/LOUNGE → Sleepwear

Step 6: 以上都沒命中 → RTW（預設，平織為主）
```

**完整對照表**：

> 注意：item_type 優先（Step 1）。下表的 department→Department 映射是 Step 2-6 結果，
> 但若 item_type 含 SWIM/SLEEP，以 item_type 為準。

**Active 類**（dept 關鍵字 + IPSS 規則）：

| department 原始值 | 數量 | 分類依據 | Fabric |
|---|---|---|---|
| WOMENS PERFORMANCE ACTIVE | 255 | dept 含 PERFORMANCE + ACTIVE | Knit（IPSS 為主） |
| MENS ACTIVE/FLEECE/SWIM | 96 | dept 含 ACTIVE | Knit（IPSS+KNITS） |
| GIRLS ACTIVE/FLEECE/SWIM/LEGGI… | 76 | dept 含 ACTIVE | Knit（IPSS+KNITS） |
| BOYS ACTIVE/FLEECE/SWIM | 28 | dept 含 ACTIVE | Knit（IPSS+KNITS） |
| GIRLS ACTIVE KNITS | 13 | dept 含 ACTIVE | Knit |
| BOYS ACTIVE KNITS | 4 | dept 含 ACTIVE | Knit |
| MATERNITY BOTTOMS（IPSS 部分） | 25 | **category=IPSS**（Step 4） | Knit |
| MATERNITY TOPS（IPSS 部分） | 3 | **category=IPSS**（Step 4） | Knit |
| TODDLER GIRL KNITS（IPSS 部分） | 16 | **category=IPSS**（Step 4） | Knit |
| TODDLER GIRL KNIT/ SWEATERS（IPSS） | 7 | **category=IPSS**（Step 4） | Knit |
| NEWBORN/INFANT（IPSS 部分） | 4 | **category=IPSS**（Step 4） | Knit |
| （空白 dept，category=IPSS） | ~48 | **category=IPSS**（Step 4） | Knit |

> 複合 dept（含 ACTIVE/FLEECE/SWIM）：ACTIVE 關鍵字先命中 → Active。
> 其中 item_type=SWIM 的會被 Step 1 攔走歸 Swimwear。
> IPSS 規則（Step 4）撈回原本落 RTW 的運動專精款式（~101 筆）。

**Fleece 類**：

| department 原始值 | 數量 | → Department | Fabric |
|---|---|---|---|
| WOMENS FLEECE | 33 | Fleece | Knit |

**Swimwear 類**（由 item_type 或 department 判斷）：

| 來源 | 數量 | 說明 |
|---|---|---|
| item_type 含 SWIM（Step 1 攔截） | ~88 | 散布在各 department 中 |
| TODDLER BOY WOVEN/OUTERWEAR/SWIM | 7 | dept 含 SWIM |
| WOMENS SLEEP/SWIM/UNDERWEAR | 58 | 複合 dept，SWIM 的由 item_type 判 |

> Swimwear item_type 來自：SWIM - L1、SWIM - L2、SWIM - L3、Swim。
> dept 名含 SWIM 但 item_type 不是 SWIM → 看是否 Active-like。

**Sleepwear 類**（由 item_type 或 department 判斷）：

| 來源 | 數量 | 說明 |
|---|---|---|
| item_type = SLEEPWEAR/LOUNGE / Sleepwear（Step 1） | ~50 | 散布在各 dept |
| WOMENS SLEEP/SWIM/UNDERWEAR | 58 | 複合 dept，SLEEP 的由 item_type 判 |
| BOYS SLEEP/UNDERWEAR | 3 | dept 含 SLEEP |
| BOYS ACCESSORIES/SLEEP | 11 | dept 含 SLEEP |
| GIRLS SLEEP/UNDERWEAR | 1 | dept 含 SLEEP |

> TODDLER ACCESSORIES(24) 和 GIRLS ACCESSORIES(22) 的 dept 名不含 SLEEP，
> 但 item_type 多數是 SLEEPWEAR/LOUNGE → 由 Step 1 正確攔住歸 Sleepwear。

**Collaboration 類**（v5.5.1 新增）：

| department 原始值 | 數量 | → Department | Fabric |
|---|---|---|---|
| NFL | 4 | Collaboration | Woven(3) + Knit(1) |
| NBA | 4 | Collaboration | Knit |
| MISCSPORTS | 1 | Collaboration | Knit |

**RTW 類**（預設=平織 Woven 為主）：

| department 原始值 | 數量 | Fabric 推導 |
|---|---|---|
| WOMENS DRESSES/SKIRTS | 80 | Woven(41) + Knit(38)，看 category |
| WOMENS WOVEN TOPS | 62 | **Woven**（dept 含 WOVEN） |
| WOMENS KNITS TOPS/TEES | 34 | **Knit**（dept 含 KNITS） |
| MATERNITY BOTTOMS（非 IPSS 部分） | 15 | Knit(11) + Woven(2) + other(2) |
| MATERNITY TOPS（非 IPSS 部分） | 9 | Knit(8) + Woven(1) |
| NEWBORN/INFANT（非 IPSS/SWIM 部分） | ~17 | Woven(17)，Romper/Bodysuit/Set 為主 |
| GIRLS TOPS/DRESSES/OUTERWEAR… | 14 | Woven(11) + Knit(3) |
| GIRLS TOPS/DRESSES/OUTERWEAR/… | 12 | Woven(10) + Knit(2) |
| TODDLER GIRL WOVEN/DRESSES/OUTERWE… | 14 | **Woven**（dept 含 WOVEN） |
| WOMENS KNITS | 10 | **Knit**（dept 含 KNITS） |
| MENS WOVEN TOPS/OUTERWEAR | 9 | **Woven**（dept 含 WOVEN） |
| TODDLER GIRL KNITS（非 IPSS/SWIM 部分） | ~5 | **Knit** |
| MENS KNIT TOPS/SWEATERS | 8 | **Knit**（dept 含 KNIT） |
| GIRLS KNIT TOPS/TEES/SWEATERS/GRAP… | 8 | **Knit**（dept 含 KNIT） |
| MENS KNITS | 8 | **Knit**（dept 含 KNITS） |
| GIRLS ACCESSORIES（非 Sleepwear 部分） | ~7 | Knit（Set/Pant） |
| BOYS KNIT TOPS/TEES/SWEATERS | 6 | **Knit**（dept 含 KNIT） |
| TODDLER GIRL WOVEN/DRESSES/OUTERWEAR | 4 | **Woven**（dept 含 WOVEN） |
| TODDLER BOY KNITS | ~19 | **Knit**（dept 含 KNITS） |
| TODDLER ACCESSORIES（非 Sleepwear 部分） | ~3 | Knit（Set/Pant） |
| MENS WOVEN PANTS/SHORTS | 3 | **Woven**（dept 含 WOVEN） |
| MENS GRAPHICS | 3 | Knit |
| BOYS GRAPHICS | 3 | Knit |
| GIRLS DENIM/WOVEN ITEMS | 1 | **Denim** |
| GIRLS DENIM PANTS/SHORTS | 1 | **Denim** |
| 其他零星（各 1 筆） | ~10 | 看 category |

> **空白 department（非 IPSS 部分，~186 筆）**：不列於對照表。
> dept 欄為空，靠 item_type（Step 1）或 category 分類，其餘落 RTW。

**分佈**（1,056 designs，排除 ATHLETA）：Active 462 / RTW 411 / Swimwear 88 / Sleepwear 64 / Fleece 25 / Collaboration 6

---

## 三之一、Fabric 推導（Knit / Woven / Denim）

**Fabric 不是 bucket 維度**，只是 metadata 標註。同一 design number 只會有一種布料。

**推導優先序**（高→低）：

| 優先 | 條件 | → Fabric | 說明 |
|---|---|---|---|
| 1 | category = IPSS | **Knit** | 運動專精，全針織 |
| 2 | category = DENIM | **Denim** | 牛仔 |
| 3 | category = KNITS | **Knit** | 針織 |
| 4 | category = WOVEN | **Woven** | 平織 |
| 5 | sub_category 含 TSD | **Woven** | Top/Shirt/Dress = 平織 |
| 6 | department 含 KNIT 或 KNITS | **Knit** | 例：WOMENS KNITS TOPS/TEES |
| 7 | department 含 WOVEN | **Woven** | 例：WOMENS WOVEN TOPS |
| 8 | department 含 DENIM | **Denim** | 例：GIRLS DENIM PANTS/SHORTS |
| 9 | 預設（RTW） | **Woven** | RTW 預設平織 |

> Fabric 已被 Department 隱含：Active ≈ Knit、RTW ≈ Woven。
> 同一款不會同時出針平織版本，所以 Fabric 不影響 bucket 拆分。

---

## 四、Garment Type 分類（11 類）

**輸入欄位**：`design_type` + `item_type` + `description` 三欄合併成 `combined` 字串

**邏輯**（`reclassify_and_rebuild.py` → `real_gt_v2()`）：

依優先序逐一比對，**第一個命中就回傳**（順序很重要）：

| 優先序 | GT 輸出 | 關鍵字（在 combined 中搜尋） | 為什麼這個順序 |
|---|---|---|---|
| 1 | ROMPER_JUMPSUIT | ROMPER, JUMPSUIT, OVERALL, ONESIE, FOOTED 1PC, FOOTED PJ, ONE PIECE, 1PC | 最特殊的複合型，要先攔 |
| 2 | BODYSUIT | BODYSUIT, BODY SUIT | 也是複合型 |
| 3 | SET | SET（在 design_type 或 desc 中獨立出現） | SET 可能含 TOP+PANT 關鍵字，要先攔 |
| 4 | DRESS | DRESS, GOWN, CAFTAN | DRESS 要在 SHORTS/SKIRT 之前（避免 SHIRTDRESS 被 SHIRT→TOP 吃掉） |
| 5 | LEGGINGS | LEGGING | **要在 PANTS 之前**（否則被 PANT 吃掉） |
| 6 | SHORTS | SHORT, SKORT, CHINO SHORT | 要在 SKIRT 之前（SKORT 歸 SHORTS） |
| 7 | SKIRT | SKIRT | — |
| 8 | PANTS | PANT, JOGGER, JEAN, CHINO, BOTTOM, FLARE, WIDE LEG | LEGGING/SHORT 已攔走 |
| 9 | OUTERWEAR | JACKET, HOODIE, VEST, COAT, CARDIGAN, PULLOVER, PONCHO, ANORAK, ROBE, OUTERWEAR, FLEECE, FULL ZIP | 外套類 |
| 10 | TOP | TOP, TEE, TANK, BLOUSE, SHIRT, POLO, HENLEY, CAMI, TUNIC, CROP, BRA, BIKINI, RASHGUARD, TANKINI, SLEEVE, MOCK NECK | 最廣的類別放最後 |
| 11 | Swim fallback | design_type = SWIM 或 SWIM/SPORT → 看 desc 有無 BOTTOM/BRIEF/TRUNK → SHORTS，否則 → TOP | |
| 12 | UNKNOWN | 以上都沒命中 | 理論上不該出現 |

**已知陷阱（歷史修正）**：

| 問題 | 原因 | 修正 |
|---|---|---|
| LEGGINGS 歸成 PANTS | PANT 關鍵字先命中 | LEGGINGS 順序移到 PANTS 之前 |
| SKORT 歸成 SKIRT | SKIRT 先命中 | SHORTS（含 SKORT）順序移到 SKIRT 之前 |
| SHIRTDRESS 歸成 TOP | SHIRT→TOP 先命中 | DRESS 順序移到 TOP 之前 |
| ONESIE/FOOTED 歸 UNKNOWN | 沒有對應關鍵字 | 加入 ROMPER_JUMPSUIT 關鍵字 |
| ROBE 歸 UNKNOWN | 沒有對應關鍵字 | 加入 OUTERWEAR 關鍵字 |
| Maternity Leggings 歸 Active | dept MATERNITY 被 Active 攔走 | v5.5 Maternity 不再是 dept |

---

## 五、Item Type（前端用，pom_rules 不處理）

**Item Type 不參與 bucket 分類**。pom_rules 的 bucket key = `{Department}_{GT}|{Gender}`。

Item Type 是 Centric 8 PDF 的原始值，**77 種**，直接傳到前端 filter。常見值：

| Item Type 原始值 | 對應 GT | 數量 |
|---|---|---|
| LEGGINGS _ L2 | LEGGINGS | 82 |
| TOPS _ L2 | TOP | 64 |
| SLEEPWEAR/LOUNGE | （影響 dept→Sleepwear） | 50 |
| PANTS _ L2 | PANTS | 43 |
| Top | TOP | 109 |
| Dress | DRESS | 43 |
| Pant | PANTS | 38 |
| DRESSES | DRESS | 35 |
| SWIM - L1 | TOP/SHORTS（看 desc） | 33 |
| PULLOVER | OUTERWEAR | 27 |
| TEE (VEE/CREW) | TOP | 26 |
| JACKET _ L2 | OUTERWEAR | 22 |
| One Piece | ROMPER_JUMPSUIT | 13 |
| Set | SET | 12 |
| SPORT BRA - NON MOLDED _ L2 | TOP（含 BRA） | 5 |
| BODYSUIT/1 PC | BODYSUIT | 4 |
| OVERALLS | ROMPER_JUMPSUIT | 1 |
| （空白） | 靠 design_type + desc 判斷 | 205 |

> 前端截圖中的 **CAPRI (~20")** 不在此列表中，是 Base44 前端自行定義的 sub-type。

---

## 六、Bucket 產出規則

### Bucket key 格式
```
{Department}_{GT}|{Gender}
例：Active_TOP|WOMENS、RTW_LEGGINGS|MATERNITY
```

### 檔名格式
```
{gender}_{department}_{gt}.json（全小寫，/ 換成 _）
例：womens_active_top.json、maternity_rtw_leggings.json、baby_toddler_rtw_dress.json
```

### 最低門檻
- bucket 內 designs **< 3** → 跳過不產出

### 產出統計（v5.5.1）
- **1,056 designs → 81 buckets → 83 files**（+_index.json +pom_names.json）
- 排除 ATHLETA 12 筆，新增 Collaboration dept

---

## 七、Pipeline 完整流程

```
┌─ mc_pom_2024/2025/2026.jsonl ─── 原始 PDF 提取（extract_techpack.py）
│
├─ rebuild_profiles.py ──────────── 合併三年 → measurement_profiles_union.json
│   └─ extract_gender()             Gender 分類（7 類）
│
├─ reclassify_and_rebuild.py ────── 分類 + 規則產出 → pom_rules/*.json
│   ├─ Step 0: 排除 ATHLETA          品牌過濾
│   ├─ real_dept_v4()               Department 分類（6 類，含 IPSS→Active + Collaboration）
│   ├─ real_gt_v2()                 Garment Type 分類（11 類）
│   ├─ parse_val()                  分數解析（含 Centric 8 格式修正）
│   └─ 產出 measurement_rules / median_values / grading_rules / tolerance
│
├─ enforce_tier1.py ─────────────── Tier 1 基礎尺寸強制歸 must
│
└─ fix_sort_order.py ────────────── POM canonical zone sort order
```
