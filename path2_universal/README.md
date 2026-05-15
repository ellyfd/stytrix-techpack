# path2_universal/

通用模型(不分客戶/品牌)的做工推薦資料源。**主要消費端**:`star_schema/scripts/build_recipes_master.py` Step 3 把 v4.3(primary)+ v4(fallback)整合進 `data/runtime/recipes_master.json`;前端 fetch `recipes_master.json` 後不再直接讀本資料夾。

> **2026-05-07 改名**:原 `General Model_Path2_Construction Suggestion/`,因含空格不利 CLI/CI 改名為 `path2_universal/`。舊外部連結 `github.com/.../General%20Model_Path2_Construction%20Suggestion/...` 已失效。

## 實際資料夾內容(2026-05-15)

| 檔案 | 用途 | 狀態 |
|------|------|------|
| `iso_lookup_factory_v4.3.json` | **primary** 查表:Dept × Gender × GT × L1(230 entries) | 活檔 — `build_recipes_master.py` 讀 |
| `iso_lookup_factory_v4.json` | v4 fallback 查表:Fabric × Dept × GT × L1_code(282 entries,提供 iso_zh / 機種) | 活檔 — `build_recipes_master.py` 讀 |
| `PATH2_通用模型_做工推薦Pipeline.md` | v4.3 pipeline 總說明(5-source 合併、key schema 設計) | 文件 |
| `PATH2_Phase2_Upload_Pipeline.md` | Phase 2 上傳 pipeline 實作 | 文件 |
| `README.md` | 本檔 | — |

## v4.3 vs v4 差異

- **v4.3 primary** key schema = `Department × Gender × GT(fine) × L1`(PANTS/LEGGINGS/SHORTS 分開,對齊前端 UI 下拉)
- **v4 fallback** key schema = `Fabric × Dept × GT × L1_code`(提供 v4.3 沒有的 fabric 維度、iso_zh 中文、機種建議)
- 兩者由 `build_recipes_master.py` maximize-merge,v4.3 命中優先,v4 補欄
