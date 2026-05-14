# Platform Sync Plan — Single Master + Multi-View 落地清單

> **狀態(2026-05-09)**:Phase 2 View A + B 落地完成。本檔案為**歷史規劃紀錄**,實作後的權威 spec
> 改看 [`PHASE2_DERIVE_VIEWS_SPEC.md`](./PHASE2_DERIVE_VIEWS_SPEC.md) 與
> [`DATA_PIPELINE_MAPPING.md`](./DATA_PIPELINE_MAPPING.md)。
>
> **plan vs build 差異**:
> - 文中規劃的 `derive_view_by_client.py` / `l2_l3_ie_by_client/` 26 檔在 Phase 2.5b 退役 — brand 維度改走升級後 Bible 的 `actuals.by_brand` 欄位 + frontend `filterBibleByBrand()` helper
> - 實際接線 CI 的是 2 個 view:A=`recipes_master.json` / B=`l2_l3_ie/<L1>.json`(升級 dict schema 含 actuals)
> - 短暫存在過的 View C `data/runtime/designs_index/<EIDH>.json` 3,900 檔(per-EIDH lazy fetch)在 **2026-05-09 retired** — 前端無 UI 消費,刪 derive script + workflow + dead 產物
> - **不要照本檔計畫再做新檔**

> **背景**:v2 架構升級後,需要**同步更新 platform stytrix-techpack repo 多個檔案**。
> 此 doc 列出每個改動的 file / 動作 / 驗證點,依優先序排。
>
> **依賴**:fetch_m7_report + fetch_m7_detail 跑完(4644 件 m7_report.jsonl + m7_detail.csv 完整)

---

## 🎯 MK Metadata Cross-Cut Layer（v3 升級）

整個系統以 **MK (Makalot 聚陽) Metadata** 為 master schema 對接所有 parameter — 這是唯一最完整的資料源。

### MK Metadata 6 個元素

| 元素 | 對應 file | 用途 |
|---|---|---|
| **M7 索引欄位**（per-design metadata）| `M7列管_YYYYMMDD.xlsx` (42 col) | 每筆 EIDH metadata |
| **五階定義** L1-L5 + VLM 視覺規則 | `data/zone_glossary.json` + `data/l2_visual_guide.json` + `data/l2_decision_trees.json` + `l2_l3_ie/*.json` | 部位+工法 schema |
| **ISO 機種字典** | `data/iso_dictionary.json` | ISO ↔ EN/ZH/機種 |
| **客戶對照** | `data/client_canonical_mapping.json` (v3 合併版) | (客戶, subgroup) → 4 維 ground truth |
| **Callout zone router** | `data/zone_glossary.json:KW_TO_L1_TOPS/BOTTOMS/ZH_ZONE_TO_L1` | 13 客人 callout 寫法 → L1 |
| **5+1 維 Canonical Key**（推導）| 從上面 5 個推 | gender × dept × gt × it × fabric × l1 |

### bucket_taxonomy v4 — 直接重寫（不慢慢 retire）

**舊版**：59 buckets，hand-curate，3 維 `<gender>_<dept>_<gt>`
**新版**（v4）：從 MK cartesian product 自動產，4 維 `<gender>_<dept>_<gt>_<it>`

跑：`python scripts\generate_bucket_taxonomy_from_mk.py`

對齊：
- 做工 master 用 6 維（4 維 + fabric + l1）
- POM bucket 用 4 維 prefix（檔名一致：`pom_rules/<bucket>.json`）
- platform `build_recipes_master.py` cascade 從 3 維改 4 維 key

### 詳見

- [`MK_METADATA.md`](./MK_METADATA.md) — 完整 spec
- [`STYTRIX_ARCHITECTURE_v1.md`](./STYTRIX_ARCHITECTURE_v1.md) v3.0 — Step 1/2/3/4 整體架構

---

## ⚠️ Scope Boundary — 只動做工，尺寸表不碰

| Pipeline | 涵蓋 | 此計畫處理？ |
|---|---|---|
| **做工 (Construction)** | m7_report / m7_detail / facts.jsonl / recipes_master / l2_l3_ie / l2_l3_ie_by_client / master.jsonl | ✅ **本計畫** |
| **尺寸表 (Measurement / POM)** | pom_rules/*.json (137 buckets) / pom_dictionary.json / gender_gt_pom_rules.json / grading_patterns.json / bodytype_variance.json / mc_pom*.jsonl / measurement_filter_dimensions / `scripts/reclassify_and_rebuild.py` 等線下產線 | ⛔ **不動不刪**，保留現狀 |

**不會碰的檔案**（platform repo）：
- `pom_rules/*.json` 137 個 bucket 檔
- `pom_analysis_v5.5.1/` 整個資料夾
- `data/pom_dictionary.json`
- `data/gender_gt_pom_rules.json`
- `data/grading_patterns.json`
- `data/bodytype_variance.json`
- `scripts/` 線下規則產線（reclassify_and_rebuild / enforce_tier1 / fix_sort_order / 等）
- `pom_rules_pipeline_guide_v2.md`
- `pom_rules_v55_classification_logic.md`

**只會碰的檔案**（做工相關）：
- `data/recipes_master.json`（既有，schema 升級）
- `data/master.jsonl`（新加）
- `data/ingest/m7/`（新加目錄）
- `data/ingest/consensus_v1/` `consensus_rules/` `ocr_v1/` `unified/`（既有，不動）
- `l2_l3_ie/*.json`（既有，可能改用 derive）
- `l2_l3_ie_by_client/*.json`（既有，可能改用 derive）
- `star_schema/scripts/build_recipes_master.py`（既有，加 m7 source）
- `star_schema/scripts/extract_unified.py` / `vlm_pipeline.py` / `extract_raw_text.py`（既有，不動）
- `.github/workflows/rebuild_master.yml`（trigger 加 m7）
- README.md / 網站架構圖.md / CLAUDE.md（補做工章節）

---

---

## 🎯 架構願景

```
                    ┌─────────────────────────────────────────────┐
                    │   stytrix-techpack/data/master.jsonl        │
                    │   ★ SINGLE SOURCE OF TRUTH                  │
                    │                                              │
                    │   每筆 entry 含：                             │
                    │   - key (gender/dept/gt/it/fabric/l1)        │
                    │   - iso_distribution                         │
                    │   - methods                                  │
                    │   - by_client.{brand}.{knit/woven}.{l2-l5}   │
                    │   - ie_seconds + machine + skill (聚陽用)    │
                    │   - design_ids (溯源)                         │
                    └────────────────┬────────────────────────────┘
                                     │ derive (run by GitHub Actions)
                  ┌──────────────────┼──────────────────────┐
                  ↓                  ↓                       ↓
       data/recipes_master.json   l2_l3_ie_by_client/    l2_l3_ie/<L1>.json
       (view A: 通用模型)          <L1>.json              (view C: 通用 L2-L5)
       drop by_client             (view B: 聚陽模型 + brand)
       drop ie_seconds            含 brand × knit/woven × L2-L5
                                  + IE 秒值 + machine + skill
```

---

## 📋 Sync 清單（按 stytrix-techpack repo 路徑分組）

### A. 加新 source — `data/ingest/m7/`

| 動作 | File | 內容 |
|---|---|---|
| 🆕 新增 | `data/ingest/m7/entries.jsonl` | M7 Pipeline 輸出，每行一筆含 5-dim key + iso + methods + by_client breakdown + ie_seconds |
| 🆕 新增 | `data/ingest/m7/.gitkeep` | 確保目錄存在 |
| 🆕 新增 | `data/ingest/m7/_metadata.json` | M7 source 版本資訊 / 抓取時間 / EIDH 範圍 |

**M7 端輸出**：寫新 script `build_master_v7.py`（取代 `build_recipes_master_v6 + build_client_specific_l2_l3_ie`）→ 輸出單一 master.jsonl → push 到 platform repo `data/ingest/m7/entries.jsonl`

### B. 改現有平台 script — `star_schema/scripts/`

| 動作 | File | 改什麼 |
|---|---|---|
| ✏️ 改 | `star_schema/scripts/build_recipes_master.py` | (1) 加 `build_from_m7_pullon()` 函式，仿 `build_from_consensus()`；(2) 把 m7 加進 cascade（建議 same_bucket 層）；(3) 輸出多加一個 `data/master.jsonl`（重量版含 by_client）+ 保留 recipes_master.json（輕量版） |
| 🆕 新增 | `star_schema/scripts/derive_view_by_client.py` | 從 master.jsonl 抽 by_client 細節，重組成 26 個 `l2_l3_ie_by_client/<L1>.json` |
| 🆕 新增 | `star_schema/scripts/derive_bible_actuals.py` | 從 master.jsonl 抽通用 L2-L5（不分 brand），重建 38 個 `l2_l3_ie/<L1>.json`（取代現有從 xlsx 抽的版本）|

### C. 改 GitHub workflow — `.github/workflows/`

| 動作 | File | 改什麼 |
|---|---|---|
| ✏️ 改 | `.github/workflows/rebuild_master.yml` | (1) trigger 加 `data/ingest/m7/`；(2) Step 3 改成 3 步（build master / derive recipes_master / derive by_client）；(3) commit 多新增 `data/master.jsonl` |
| ✏️ 改（可能可保留）| `.github/workflows/build_bible_skeleton.yml` | 評估：是否改用 derive_bible_actuals 取代從 xlsx 直接 build |

### D. 文件同步 — top-level + docs

| 動作 | File | 改什麼 |
|---|---|---|
| ✏️ 改 | `README.md` | (1) 「資料來源」區補第 6 個 source（m7）；(2) 新增「Master + 兩個 View」區段；(3) 「ISO 查表版本演進」表加新 row m7 |
| ✏️ 改 | `網站架構圖.md` | Mermaid 圖補 m7 source + master.jsonl 節點 + derive 兩個 view 流程 |
| 🆕 新增 | `data/master.jsonl` 章節說明 | README 加新 file description |
| ✏️ 改 | `CLAUDE.md` | 補 v7 結構說明（給 AI 看的 brief） |

### E. M7 端取代 / 新增 — `M7_Pipeline/scripts/`

| 動作 | File | 動作 |
|---|---|---|
| 🆕 新增 | `M7_Pipeline/scripts/build_master_v7.py` | 整合 v6 build_recipes_master + by_client，輸出 master.jsonl |
| 🆕 新增 | `M7_Pipeline/scripts/push_master_to_platform.py` | 把 master.jsonl push 到 platform repo `data/ingest/m7/entries.jsonl` |
| ⛔ 取消 | `build_recipes_master_v6.py` | retire（被 build_master_v7 取代）|
| ⛔ 取消 | `build_client_specific_l2_l3_ie.py` | retire（functionality 移到 platform 端 derive）|
| ⛔ 取消 | `convert_to_platform_schema.py` | retire（master.jsonl 已對齊 platform schema）|
| ⛔ 取消 | `merge_into_platform_repo.py` | retire（改用 push_master_to_platform.py 直 push 到 ingest/m7）|

---

## 🚦 實作優先序

### Phase 1 — 等 fetch 跑完馬上做（~1 day）

1. **改 platform `build_recipes_master.py` 加 m7 source**
   - 新增 `build_from_m7_pullon()` 函式
   - 加進 cascade
   - **不**改 output schema（先讓 m7 走現有 5-dim entry schema）
2. **寫 M7 `build_master_v7.py`**
   - 整合 v6 + by_client，但 output 格式對齊 platform 現有 entry schema（5-dim）
   - 暫時不含 by_client（Phase 2 再加）
3. **改 `rebuild_master.yml` trigger 加 ingest/m7/**
4. **驗證**：M7 push entries.jsonl → workflow 跑 → recipes_master 含 m7 source entries

### Phase 2 — Master Schema 升級（~2 days）

5. **改 build_recipes_master.py output 多帶 by_client + ie_seconds**
   - 輸出 `data/master.jsonl`（每 entry 含全部資訊）
   - 保留 recipes_master.json（drop by_client + ie_seconds）
6. **寫 derive_view_by_client.py**（從 master 衍生 by_client/<L1>.json）
7. **改 rebuild_master.yml** Step 3 三步驟（build / derive A / derive B）

### Phase 3 — 文件 + retire 舊腳本（~半天）

8. 更新 README + 網站架構圖.md
9. 更新 CLAUDE.md
10. M7 端 retire build_client_specific_l2_l3_ie / convert / merge_into_platform_repo

---

## ⚠️ 風險點

| 風險 | 解法 |
|---|---|
| recipes_master.json 跟 master.jsonl 有 schema drift | derive_view_recipes 必須是 strict subset，CI 驗 |
| master.jsonl 太大（5-10 MB）影響 platform UI | recipes_master.json 保留輕量版，UI 預設讀這個；by_client/<L1>.json lazy load |
| GitHub workflow 跑 master + 兩 view 太久（>15 min）| 加 cache + 並行；必要時 split job |
| 平台 build_recipes_master.py 改 schema 影響其他 source | 加 `--legacy-format` flag 一段過渡期 |
| M7_Pipeline 殘留邏輯跟 platform drift | Phase 3 retire 舊腳本後 enforce single pipeline |

---

## 📊 工作量估算

| Phase | 工作量 | 影響面 |
|---|---|---|
| Phase 1 | 1 day | 加新 source，不破壞現況 |
| Phase 2 | 2 days | 升級 schema，要 strict CI 驗 |
| Phase 3 | 半天 | 文件 + cleanup |
| **總計** | **~3.5 days** | 跨 platform + M7 兩 repo |

---

## 🎯 實作後的最終架構

```
M7 Pipeline (聚陽端，Windows)：
  fetch_m7_report (nt-net2 CDP) ──┐
  fetch_m7_detail (SSRS NTLM)  ───┤
  2_fetch_tp.ps1 (SMB PDF/PPTX) ──┤── m7_organized_v2/
  client PDFs (extract_raw_text) ─┤
                                  ↓
                          build_master_v7.py
                                  ↓
                          push_master_to_platform.py
                                  ↓ git push
                                  ▼
─────────────────────────────────────────────────────────────────────────
Platform GitHub (stytrix-techpack)：
  data/ingest/m7/entries.jsonl
       + 5 個原 source（v4.3 / v4 / consensus / recipe / bridge / facts_agg）
                                  ↓ trigger rebuild_master.yml
                          star_schema/scripts/build_recipes_master.py
                                  ↓
                          data/master.jsonl ★ single source of truth
                                  ↓ derive (兩 view)
                  ┌───────────────┴───────────────┐
                  ↓                                ↓
       data/recipes_master.json          l2_l3_ie_by_client/<L1>.json
       (view A: 通用模型)                  (view B: 聚陽模型 + brand)
                  ↓                                ↓
       Vercel auto-deploy → stytrix-techpack.vercel.app
                  ↓                                ↓
       通用模型 UI                        聚陽模型 UI
       (5-dim consensus + ISO)            (brand × L2-L5 + IE 秒值)
```

---

*作者：@elly | v2.0 plan | 待 review 後分 phase 實作*
