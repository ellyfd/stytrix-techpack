# Platform Sync Plan — Single Master + Multi-View(歷史規劃)

> **狀態(2026-05-09)**:Phase 2 View A + B 接線完成,本檔僅留作**歷史紀錄**。
> 實作後的權威 spec 改看:
> - [`PHASE2_DERIVE_VIEWS_SPEC.md`](./PHASE2_DERIVE_VIEWS_SPEC.md) — derive views 設計 + 完成度
> - [`DATA_PIPELINE_MAPPING.md`](./DATA_PIPELINE_MAPPING.md) — workflow → file mapping
> - [`STYTRIX_ARCHITECTURE.md`](./STYTRIX_ARCHITECTURE.md) — 整體架構

## Plan vs Build 差異(已完成,記下來避免重做)

| 規劃 | 實際 | 原因 |
|---|---|---|
| `derive_view_by_client.py` + `l2_l3_ie_by_client/` 26 檔(per-brand 五階檔) | ⊘ Phase 2.5b 退役 | brand 維度直接走升級後 Bible 的 `actuals.by_brand` + frontend `filterBibleByBrand()` / `filterBibleByCategory()` helper,不另開資料夾 |
| `derive_view_designs_index.py` + `data/runtime/designs_index/<EIDH>.json` 3,900 檔(per-EIDH lazy fetch) | ⊘ 2026-05-09 retired | 實裝產出後 audit 發現 `index.html` 並無 EIDH 詳情頁 fetch,屬 dead 產物 |
| `bucket_taxonomy v4` 4 維 `<gender>_<dept>_<gt>_<it>` | ✅ 28 v4 + 59 legacy,在 `data/runtime/bucket_taxonomy.json` | 合併維護,legacy 保留兜底 pre-v4 facts |
| `build_recipes_master.py` cascade 3 維 → 4 維 | ✅ 完成,跑 same_sub > same_bucket > same_gt > general > cross_design | — |
| MK Metadata cross-cut layer | ✅ `MK_METADATA.md` canonical spec(2026-05-08 v1.0) | 整個系統以聚陽 M7 為 single point of integration |

## 不要再照本檔做新檔

凡是規劃但未落地的 file(`derive_view_by_client.py`、`l2_l3_ie_by_client/`、`designs_index/`、`master_metadata.jsonl` 等)都已 retired 或合併進 View A/B,不要重建。要改 derive 邏輯,動 `star_schema/scripts/derive_*.py`;要加新 view,新檔但走 `MK_METADATA.md` 為 schema 主軸。
