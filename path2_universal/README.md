# path2_universal/

通用模型（不分客戶/品牌）的做工推薦資料源。**主要消費端**：`star_schema/scripts/build_recipes_master.py` Step 3 把 `iso_lookup_brandspec_5dim.json` 在 build 時 roll 成 same_gt + general 兩層整合進 `data/runtime/recipes_master.json`；前端 fetch `recipes_master.json` 後不直接讀本資料夾。

> **2026-05-15 v4/v4.3 退役公告**：`iso_lookup_factory_v4.3.json` + `iso_lookup_factory_v4.json` 已 git rm，由單一完整 5 維表 `iso_lookup_brandspec_5dim.json`（Fabric × Department × Gender × GT × L1，多來源聚合：pptx_facets 必吃 + facts_aligned 選吃 + pdf_facets 接口預留）取代。`build_recipes_master.py` 的 same_gt / general 兩層改由它在 build 時 roll 出。

> **2026-05-07 改名**：原 `General Model_Path2_Construction Suggestion/`，因含空格不利 CLI/CI 改名為 `path2_universal/`。舊外部連結 `github.com/.../General%20Model_Path2_Construction%20Suggestion/...` 已失效。

## 實際資料夾內容（2026-05-15）

| 檔案 | 用途 | 狀態 |
|------|------|------|
| `iso_lookup_brandspec_5dim.json` | **主查表**：Fabric × Dept × Gender × GT × L1 完整 5 維 ISO 表，多來源聚合 | 活檔 — `build_recipes_master.py` 讀 |
| `iso_lookup_5dim.json` | IE 生產實況 ISO 表（machine→ISO） | 活檔 — 參考 |
| `PATH2_通用模型_做工推薦Pipeline.md` | Pipeline 總說明（5-source 合併、key schema 設計） | 文件 |
| `PATH2_Phase2_Upload_Pipeline.md` | Phase 2 上傳 pipeline 實作 | 文件 |
| `README.md` | 本檔 | — |

## v4 / v4.3 為何退役

舊 v4.3（`Dept × Gender × GT × L1`，230 entries）+ v4（`Fabric × Dept × GT × L1`，282 entries）是兩本**部分 key aggregated** 的表，沒有完整 5 維 key，無法合併重生。本質是「兩個降維 view」，build_recipes_master.py 之前用 cascade fallback 接（v4.3 primary + v4 補欄）湊出 same_gt + general 兩層，但維度不正交，命中/補欄邏輯難維護。

2026-05-15 改成：從 entries.jsonl 反向重建完整 5 維 key 的 `iso_lookup_brandspec_5dim.json`，多 source（pptx_facets 必吃 + facts_aligned 選吃，pdf_facets 接口預留）聚合，`build_recipes_master.py:build_from_brandspec_5dim()` 在 build 時 roll 成 same_gt + general 兩層輸出。v4/v4.3 retired。

歷史 lineage 留在 git history（`git log path2_universal/`）。
