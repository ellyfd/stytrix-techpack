# MK Metadata — Single Master Schema for StyTrix Techpack

> **MK = Makalot 聚陽**。整個 StyTrix Techpack 系統以聚陽 metadata 為基礎，**所有參數對接到 MK 為主**（這是唯一最完整的資料源）。
>
> 所有 Pipeline（做工 + POM）共用此 schema，不再有「做工 bucket vs POM bucket」分歧。
>
> **作者**：@elly | **日期**：2026-05-08 | **版本**：v1.0 spec

---

## 為什麼以 MK 為主

| 資料來源 | 涵蓋範圍 | 完整度 |
|---|---|---|
| 客戶 PDF Techpack | 各客戶自己格式（Centric 8 / 自訂）| 不一致、欄位殘缺、格式各異 |
| Platform v4.3 / v4 | 5 source 整合的 ISO recipe | 部分覆蓋（無 fabric / 無 gender / 無 item 細分）|
| **聚陽 M7 索引** | **18,731 EIDH × 42 columns** | **100% cover 聚陽手上所有 design**，欄位齊全 |

聚陽是「跨客戶 single point of integration」 — 唯一手上有**全部客戶+全部 design+完整 metadata** 的角色。

---

## MK Metadata 6 個元素

### 1. M7 索引欄位（per-design metadata）

從 `M7列管_YYYYMMDD.xlsx` 的 42 columns，每筆 EIDH 一份：

| 欄位 | 內容 | Source |
|---|---|---|
| `Eidh` | 聚陽內部唯一 ID | M7 自動產 |
| `HEADER_SN` | 報價單 SN | M7 |
| `客戶` | 客戶名稱（44 enum） | M7 |
| `報價款號` | 客戶款號（每客戶不同格式） | M7 |
| `Item` | 成衣品類（32 enum：Tee / Pull On Pants / Dress / ...） | M7 |
| `Subgroup` | 細分（164 enum：WAC / D214 / 22 / ACT(FLX MEN) / ...） | M7 |
| `Program` | 系列（260 enum：W-OTHERS / IPSS / FLX / POWERSOFT / ...） | M7 |
| `W/K` | 針/平織（2 enum：Knit / Woven） | M7 |
| `PRODUCT_CATEGORY` | 性別+類別（6 enum：Women / Men / Girl / Boy / Baby / Women??） | M7 |
| `Season` | Season（V-SP 2026 / I-FA 2026 / ...） | M7 |
| `產區` | 工廠縮寫（12 enum：SMG / NVN / SVN / CAB / ...） | M7 |
| `Sketch` | Sketch URL | M7 |
| `五階層網址` | YY 五階摘要 URL | M7 |
| `細工段網址` | YY SSRS 細工段 URL | M7 |
| `TP資料夾` | SMB TP 路徑 | M7 |

### 2. 五階定義（L1-L5 + VLM 視覺規則）

| 階 | 量 | 來源檔（Bible）|
|---|---|---|
| L1 部位 | 38 | `data/zone_glossary.json:L1_STANDARD_38` + `五階層部位.xlsx` + `L1_部位定義_Sketch視覺指引.md` |
| L2 零件 | 282 | `data/l2_visual_guide.json` + `data/l2_decision_trees.json` + `L2_VLM_Decision_Tree_Prompts_v2.md` |
| L3 形狀 | 1117 | `五階層展開項目.xlsx` → `l2_l3_ie/<L1>.json` |
| L4 工法 | ~6000 | 同上 |
| L5 細工段 | ~30000 | 同上 |

### 3. ISO 機種字典

`data/iso_dictionary.json` 含 ISO ↔ EN canonical / ZH method / 機種：

```json
{
  "301": {"en": "Lockstitch", "zh": "車縫", "machine": ["平車", "lockstitch"]},
  "514": {"en": "Overlock 3-thread", "zh": "拷克", "machine": ["3線拷克"]},
  ...
}
```

### 4. 客戶對照（client_canonical_mapping.json v3）

每客戶 (subgroup) → 4 維 ground truth：

```json
{
  "OLD NAVY": {
    "aliases": ["ONY", "ON"],
    "subgroup_to_meta": {
      "WAC": {
        "fabric":   {"value": "KNIT",   "purity": 99},
        "gender":   {"value": "WOMEN",  "purity": 100},
        "dept":     {"value": "ACTIVE", "purity": 100},
        "category": {"value": "MIXED",  "purity": 35}
      }
    }
  }
}
```

### 5. Callout zone router（KW_TO_L1）

`data/zone_glossary.json` 含 callout keyword → L1 對照（13 客人寫法統一）：

```json
{
  "KW_TO_L1_TOPS":    {"COLLAR": ["NK", "領"], ...},
  "KW_TO_L1_BOTTOMS": {"WAISTBAND": ["WB", "腰頭"], ...},
  "ZH_ZONE_TO_L1":    {"領片": ["NK", "領"], "腰頭": ["WB", "腰頭"], ...}
}
```

### 6. 5+1 維 Canonical Key（推導出來的）

從上面 5 個元素**推導**出 master key：

```
客人 × 針平織(fabric) × gender × dept × garment × item × L1
```

| 維度 | enum | 推導 source |
|---|---|---|
| 客人 | 39 enum(OLD NAVY / GAP / KOHLS / A&F / ...,完整列表見 client_canonical_mapping.json） | M7 `客戶` |
| 針平織 (fabric) | KNIT / WOVEN | M7 `W/K` 直接對應 |
| gender | WOMEN / MEN / GIRL / BOY / BABY / UNISEX / MATERNITY | M7 `PRODUCT_CATEGORY` 直接對應 |
| dept | ACTIVE / RTW / SLEEPWEAR / SWIMWEAR / FLEECE / DENIM / MATERNITY | client_canonical_mapping (subgroup → dept) |
| garment | BOTTOM / TOP / DRESS / OUTERWEAR / SET / SKIRT / SHORTS / ... | M7 `Item` 對照（Pull On Pants → BOTTOM）|
| item | PANT / LEGGINGS / JOGGERS / SHORTS / BASIC_TOP / DRESS / ... | M7 `Item` + `Subgroup` heuristics |
| L1 | 38 部位 | callout zone → KW_TO_L1 router |

> **JSON key 命名相容性**:`bucket_taxonomy.json` 等 schema 內部 key 沿用簡寫 `gt` / `it`(歷史相容,動到會改 `build_recipes_master.py` 等 consumer);**概念名稱統一為 `garment` / `item`**,文件描述以全名為準。

---

## bucket_taxonomy.json 由 MK 推導（不再 hand-curate）

新版 `bucket_taxonomy.json`（v4）schema：

```json
{
  "version": "v4",
  "source": "Generated from MK Metadata cartesian product",
  "buckets": {
    "WOMENS_ACTIVE_PANTS_LEGGINGS": {
      "gender": "WOMENS",
      "dept": "ACTIVE",
      "gt": "PANTS",
      "it": "LEGGINGS",
      "n_designs": 234,
      "fabric_split": {"KNIT": 230, "WOVEN": 4},
      "top_clients": {"BEYOND YOGA": 80, "ATHLETA": 67, ...},
      "use_for": ["construction", "pom"]
    }
  }
}
```

**規則**：
- **4 維 key** = `<gender>_<dept>_<garment>_<item>`(POM 端用,做工 cascade 也認;JSON key 簡寫為 `gt` / `it`)
- **6 維做工** = 4 維 + fabric + L1(做工 master.jsonl 用)
- **POM 4 維** = 4 維 prefix(pom_rules/<bucket>.json 用相同命名)

cartesian product filter：只保留**實際在 M7 索引出現過的組合**，避免空 bucket。

跑：

```powershell
python scripts\generate_bucket_taxonomy_from_mk.py
# Output: outputs/platform/bucket_taxonomy.json
```

---

## 各 Pipeline 怎麼用 MK

### 做工 Pipeline

```
Step 1 Raw → Step 2 Source (對齊 MK Metadata 5+1 維) → Step 3 Master → Step 4 Views
```

每 master entry 用 6 維 key（4 維 from MK + fabric + l1）：
- `recipes_master.json` (view A) — drop fabric/by_client，輕量化
- `l2_l3_ie/<L1>.json` (view C) — drop brand 維度
- `l2_l3_ie_by_client/<L1>.json` (view B) — 含 brand × knit/woven × L2-L5

### POM Pipeline（獨立）

```
Step 1 mc_pom Raw → scripts/reclassify_and_rebuild → pom_rules/<bucket>.json
```

bucket 命名 = MK 4 維（不再用獨立 POM bucket schema）：
- `pom_rules/WOMENS_ACTIVE_PANTS_LEGGINGS.json`
- `pom_rules/WOMENS_ACTIVE_PANTS_PANT.json`
- ...

跟做工 master entry 6 維前綴對齊（做工 6 維 → POM 取前 4 維 prefix lookup）。

---

## 對 platform `build_recipes_master.py` 的影響

**改動**：

| Before | After |
|---|---|
| 用 `data/runtime/bucket_taxonomy.json` (59 buckets, hand-curate) 做 cascade | 用 `data/client_canonical_mapping.json` + `bucket_taxonomy.json` (v4 from MK) |
| `<gender>_<dept>_<garment>` 3 維 bucket | `<gender>_<dept>_<garment>_<item>` 4 維 bucket |
| `data/runtime/bucket_taxonomy.json` 手動編輯 | 從 MK 推導，每次新 design 進來自動更新 |

`build_recipes_master.py` 的 `build_from_consensus()` 等函式 cascade key 從 3 維改 4 維。

---

## 變更歷史

| 版本 | 日期 | 重點 |
|---|---|---|
| v1.0 | 2026-05-08 | 初版 MK Metadata spec — 6 個元素 + 5+1 維 canonical key + bucket_taxonomy v4 推導機制 |

---

## 對應的 source 檔

| 概念 | 對應 file |
|---|---|
| MK Metadata 主入口 | `data/client_canonical_mapping.json` (v3) |
| 五階定義 | `data/zone_glossary.json` + `data/l2_visual_guide.json` + `data/l2_decision_trees.json` + `l2_l3_ie/*.json` |
| ISO 字典 | `data/iso_dictionary.json` |
| Callout router | `data/zone_glossary.json:KW_TO_L1_*` |
| Canonical bucket | `data/runtime/bucket_taxonomy.json` (v4，從 MK 推) |
| M7 索引（raw） | `M7列管_YYYYMMDD.xlsx`（聚陽端，每月更新）|

---

*文件維護：@elly | v1.0 spec | 對齊 STYTRIX_ARCHITECTURE_v1.md v3.0*
