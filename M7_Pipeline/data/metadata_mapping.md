# Client (PDF) ↔ Makalot (nt-net2) Metadata Mapping

> JOIN KEY：**`design_id` (PDF) ↔ `style_no` (nt-net2)**
> 同 design_id 可能對應多筆 EIDH（不同 season / quote 版本）

## 概念對照（兩邊都記但叫法不同）

| 概念 | 客戶端 PDF metadata | 聚陽端 nt-net2 m7_report | 備註 |
|---|---|---|---|
| **客戶名** | `client`（如 "ONY", "DICKS"） | `customer`（如 "OLD NAVY", "DICKS SPORTING GOODS"） | 客戶端用聚陽縮寫，MK 端用 normalized 全名 |
| **設計 ID** | `design_id`（如 "D97929"） | `style_no`（如 "AIM27C2WV02"） | ★ JOIN KEY；客戶端 D-prefix vs MK 端用客戶 style 全碼 |
| **品類** | `category`（"Tech Pack BOM Legacy"）| `item`（"Pull On Pants"） | PDF 是客戶 BOM 分類，MK 是聚陽品類碼 |
| **布料類型** | （無）| `wk` (Woven/Knit) | MK 端必填，PDF 無此欄 |
| **布料名** | （罕見）| `fabric_name`（"Poplin"） | MK 自己填 |
| **布料成份** | （罕見，DICKS 有時有）| `fabric_ingredients`（"Recycled Polyester/Spandex 86/14"） | MK 自己驗 |
| **性別** | `gender_pdf`（DICKS 直接寫 / ONY 從 brand_division 推） | （無欄，從 customer + style 內部推）| 兩邊獨立記 |
| **部門** | `department`（"WOMENS PERFORMANCE"） | （無，從 brand 推）| PDF 客戶分類 |
| **季別 / 時間** | `season`（"Holiday 2026"） | `analyst_date`（"2026/04/22"）| 不同維度，PDF 是客戶 season，MK 是分析時間 |
| **數量** | （罕見） | `quantity_dz`（"100.00" 打）| MK 報價時客戶通報 |
| **廠商** | `vendor`（"MAKALOT INDUSTRIAL CO LTD"） | `company`（"TSS" 聚陽工廠代碼）| 兩邊都標誰做，但寫法不同 |
| **狀態** | `status`（"Concept", "Adopted"） | （無，從 review_date / reviewer 推）| PDF 是客戶端 BOM 狀態 |

## 客戶端獨有（聚陽 nt-net2 沒）

| 欄位 | 內容範例 | 用途 |
|---|---|---|
| `brand_division` | "OLD NAVY - WOMENS" | 客戶品牌 + 性別 |
| `collection` | "WOMENS PERFORMANCE" | 客戶內部 collection |
| `bom_number` | "000863578" | 客戶 BOM 編號 |
| `flow` | "Tech Pack BOM Vendor" | 客戶 workflow stage |
| `style_description` | "DSG / Mens cargo pant" | DICKS 用 |
| `size_range` | "S-XXL" | DICKS 用 |
| `product_status` | "Active" | DICKS 用 |
| `tech_pack_type` | "Production" | DICKS 用 |
| `evaluation_type`, `origin` | "Pic Evaluation", "IND" | 共用欄但通常 PDF 沒帶 |

## 聚陽端獨有（PDF 沒）

| 欄位 | 內容範例 | 用途 |
|---|---|---|
| `index_no` | "115-03484" | 聚陽內部 index 號 |
| `follow` | "Sarah Yeh 葉又瑀" | 聚陽業務跟單者 |
| `analyst_creator` / `analyst_update` | "ALISONLIAO" | IE 分析師 |
| `reviewer` / `review_date` / `review_reason` | (Audit trail) | IE 審核紀錄 |
| **`total_amount_usd_dz`** | "1.17" | ★ **直接接報價** |
| **`total_ie`** | "1.84" | ★ Total IE 值 |
| `total_time` | "2612.30" | 總工時（秒）|
| `sewing_time` / `cutting_time` / `ironing_time` / `package_time` | 0.07-1.65 | Time breakdown |
| `sewing_ie` / `cutting_ie` / `ironing_ie` / `package_ie` | 細部 IE | 對應 time |
| `high_level_cost` / `fashion_cost` / `performance_cost` / `normal_cost` | 成本拆解 | 不同 layer 成本 |
| `high_machines[]` | 高階設備清單 + 分攤金額 | 含 machine_name + total_qty + apportionment_qty + apportionment_usd_dz |
| `custom_machines[]` | 客製化輔具/租借設備 | 同上 |
| `flags.bonding` | bool | 是否含 bonding 工序 |
| `flags.complex_style` / `simple_style` | bool | 製程複雜度 |
| `flags.thick_fabric` / `thin_fabric` | bool | 布料厚度 |
| `flags.align` / `non_align` | bool | 對位需求 |
| `flags.sample` / `description` | bool | 是否需打樣 |
| `five_level_detail[]` | 五階明細含 detail 欄 | 比 csv_5level 多 detail 欄位 |

## 用 mapping 做什麼

1. **enrich_dim.py** — 用 `design_id == style_no` JOIN 兩邊產 `dim_enriched.jsonl`，每 design 一筆 record，含 `client_side` + `makalot_side` 兩 sub-object
2. **build_platform_recipes.py v2** — 5-dim recipe 從 `makalot_side` aggregate：
   - `avg_total_amount_usd_dz`（直接接報價）
   - `avg_total_ie`
   - `complex_style_pct` / `thin_fabric_pct` / `non_align_pct`
   - `top_high_machines`（跨 design 高頻設備）
   - `top_custom_machines`
3. **報價系統查表** — 給定新 design 的 (gender, dept, gt, item, l1) → 拿到 design_intent (PDF 端) + production_reality (MK 端) + USD/dz 範圍
