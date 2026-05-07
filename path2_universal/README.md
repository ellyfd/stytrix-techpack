# v4.3 Update — 2026-04-20

> **2026-05-07 改名公告**:本資料夾原名 `General Model_Path2_Construction Suggestion/`,
> 因含空格不利 CLI/CI,改名為 `path2_universal/`。所有舊外部連結
> (`github.com/.../blob/main/General%20Model_Path2_Construction%20Suggestion/...`)
> 已失效,請改用新路徑 `github.com/.../blob/main/path2_universal/...`。

本資料夾集中存放 v4.2→v4.3 更新的所有檔案。

## 更新重點

1. **Fine GT 取代 Canonical Collapse** — PANTS/LEGGINGS/SHORTS 不再合併為 BOTTOM，對齊 App UI 下拉選單
2. **5 Sources 合併** — PPTX 中文 + PDF 英文 + JSONL iso_codes + Raw PDF pdfplumber + OCR callout
3. **Key Schema 改為** `Department × Gender × GT(fine) × L1`

## 檔案清單

| 檔案 | 說明 | 原始位置 |
|------|------|---------|
| `PATH2_通用模型_做工推薦Pipeline.md` | Pipeline 文件（全面更新至 v4.3） | (同資料夾,2026-05-07 改名前) |
| `iso_lookup_factory_v4.3.json` | 主查表：130 entries / 292 designs | (同資料夾,2026-05-07 改名前) |
| `v4_lookup_index.json` | 快速查表索引（從 v4.3 重生成） | (同資料夾,2026-05-07 改名前) |
| `l1_code_to_v3_mapping.json` | L1 code↔中文部位名（purpose 更新至 v4.3） | (同資料夾,2026-05-07 改名前) |
| `_index.json` | 做工配方索引：71 recipes / 505 designs | `construction_recipes/` |
| `recipe_*.json` | 配方範例（WOMENS TOP/PANTS/LEGGINGS） | `construction_recipes/` |

## 數據摘要

- Lookup: 130 entries — 13 strong / 44 likely / 10 mixed / 63 no_data
- Recipes: 71 recipes — 505 designs, 9 fine GT values
- Coverage: 716/1,328 designs (54%) 有 ISO
