# Pipeline 名詞對齊表 (Glossary)

**最後更新**：2026-05-12
**目的**：所有 PDF / PPTX / XLSX extract pipeline 用詞統一，避免「callout」這類 design industry 術語在 techpack 場景造成困惑。

---

## 一、概念詞 (Domain Vocabulary)

| 詞 | 意思 |
|----|------|
| **construction**（做工）| 任何「怎麼做」的指令 / 頁面 / 翻譯。包含 sewing instruction、機種、走線、剪接等。**不要用 callout** |
| **measurement_chart**（規格表）| 含 size + POM + 容差的表格。簡稱 MC |
| **POM**（Point of Measurement）| 量測點，例：腰頭高度、袖長 |
| **metadata**（基本資料）| 封面 8 欄（design_number / brand_division / season / 等）|
| **zone**（部位）| 衣服上的位置，例：腰頭、領、袖 |
| **L1**（38 官方部位）| `stytrix-techpack/data/runtime/l1_standard_38.json` 的 2 字母代號 |
| **ISO**（工藝代號）| `stytrix-techpack/data/runtime/iso_dictionary.json` 的 14 個機種代號 |
| **EIDH**（Entity ID Header）| 設計單元唯一 ID（manifest 的 `Eidh` 欄位）|
| **canonical**（正規化值）| 客戶/Program/Subgroup/W/K/Item/Season/PRODUCT_CATEGORY 8 個欄位的 normalized 值 |

---

## 二、JSON Output Schema

### `pdf_facets.jsonl`（每行 = 1 EIDH）

```json
{
  "eidh": "306416",
  "design_id": "D68027",
  "client_code": "GAP",
  "client_raw": "GAP - BOYS",
  "metadata": { ... 8 canonical 欄位 ... },
  "construction_pages": [             // 構造說明頁 (含 PNG render)
    {
      "pdf": "...", "page": 4,
      "score": 7,
      "png": "outputs/extract/pdf_construction_images/...png",
      "construction_items": [...]     // parser 解析的構造 items
    }
  ],
  "measurement_charts": [             // POM 規格表
    {
      "_source_pdf": "...",
      "_source_page": 5,
      "season": "Fall 2025",
      "size_range": "...",
      "sizes": ["XXS", ..., "XXL"],
      "poms": [
        {"POM_Code": "H1", "POM_Name": "Waistband Height",
         "tolerance": {"neg": "- 1/8", "pos": "1/8"},
         "sizes": {"XXS": "2", ..., "XXL": "2"}}
      ],
      "n_poms_on_page": 28
    }
  ],
  "source_files": ["TPK24...pdf"],
  "_status": "ok"
}
```

### `pptx_facets.jsonl`（每行 = 1 EIDH）

```json
{
  "eidh": "305033",
  "client_code": "UA",
  "design_id": "6011047",
  "pptx_files": ["TPK24...pptx"],
  "n_slides_total": 18,
  "n_construction_slides": 8,
  "constructions": [                  // 構造說明 instruction (zone+method+iso)
    {
      "method": "1/8\"單針平車",
      "zone": "領",
      "L1": "NK",
      "L1_name": "領",
      "iso": "301",
      "_source_slide": 4,
      "_source_pptx": "TPK24...pptx"
    }
  ],
  "n_constructions": 66,
  "raw_text_file": "outputs/extract/pptx_text/UA_6011047.txt",
  "_status": "ok"
}
```

### `xlsx_facets.jsonl`（每行 = 1 EIDH）

```json
{
  "eidh": "...",
  "client_code": "SAN",
  "measurement_charts": [             // POM 規格表 (從 XLSX)
    {"sheet": "POM", "rows": [...]}
  ],
  "construction_iso_map": [           // 中文做工 → ISO 翻譯對照
    {"zh": "拷克", "iso": "514"}
  ]
}
```

---

## 三、Page Type (page_classifier.classify_page 回傳)

| ptype | 意思 | parser 動作 |
|-------|------|-------------|
| `cover` | 封面 metadata 頁 | `parser.parse_cover()` → 8 canonical 欄位 |
| `construction` | 構造說明頁 (含 callout 圖) | `parser.parse_construction_page()` + render PNG |
| `measurement` | POM 規格表頁 | `parser.parse_measurement_chart()` |
| `junk` | BOM / disclaimer / 廣告等 | skip |

---

## 四、Parser Method（client_parsers/*.py）

| method | 對齊 ptype | 回傳 |
|--------|-----------|------|
| `parse_cover(page, text)` | `cover` | `{metadata fields}` |
| `parse_construction_page(page, text)` | `construction` | `[construction items]` |
| `parse_measurement_chart(page, text)` | `measurement` | `{measurement chart dict}` |

---

## 五、命名禁用詞（廢棄 → 新名）

| 廢棄 | 新名 | 原因 |
|------|------|------|
| `callouts` (PDF top-level) | `construction_pages` | callout 是 design illustration 術語，不是 garment construction 術語 |
| `callouts` (PPTX top-level) | `constructions` | 同上，PPTX 是 instruction-level，PDF 是 page-level |
| `callout_items` | `construction_items` | 同上 |
| `iso_callouts` | `construction_iso_map` | 是 中文 → ISO 對照表，不是 callout |
| `n_callouts` | `n_constructions` | 同上 |
| `mcs` | `measurement_charts` | 縮寫太短，不好閱讀 |
| `parse_callout()` method | `parse_construction_page()` | 對齊 ptype |
| `parse_mc()` method | `parse_measurement_chart()` | 對齊 |
| ptype `"callout"` | ptype `"construction"` | 對齊命名 |
| `CALLOUT_HEADER_KW` const | `CONSTRUCTION_HEADER_KW` | |
| `CALLOUT_SOFT_KW` const | `CONSTRUCTION_SOFT_KW` | |
| `CALLOUT_IMG_DIR` var | `CONSTRUCTION_IMG_DIR` | |
| folder `pdf_callout_images/` | `pdf_construction_images/` | |

---

## 六、為什麼不用 callout？

「callout」原意是 **design illustration** 中「指向圖中某部位的標註線」(類似 IKEA 說明書的 1️⃣2️⃣3️⃣)。

在 garment techpack 領域：
- 中文 IE / 打樣師說「**做工**」「**construction**」
- 客戶 PLM 系統（Centric 8 / Gerber Tech）也用「**Construction**」「**Construction Page**」當 section name
- 「callout」是借用詞，industry 內部沒人這樣稱呼

→ 統一用 **construction** 對齊產業用語。

---

## 七、變更歷史

| 日期 | 改變 | 影響 |
|------|------|------|
| 2026-05-12 | Big-bang rename: callouts/iso_callouts/mcs → construction*/measurement_charts | 12 個 active script + 3 個 jsonl 全部 rewrite |

執行用 `_bulk_rename.py`（script rename）+ `migrate_facets_keys.py`（data migration）。
