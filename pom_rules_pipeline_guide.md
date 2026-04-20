# pom_rules Pipeline 操作指南

## 三支腳本的角色

```
ONY PDF 原料                         前端可用的規則檔
    │                                      ▲
    ▼                                      │
┌─────────────────────┐          ┌─────────────────────────┐
│ run_extract_*.py    │          │ reclassify_and_rebuild.py│
│ 「餵原料」           │  ──→     │ 「煮成品」               │
│ PDF → mc_pom JSONL  │          │ JSONL → pom_rules/ JSON  │
└─────────────────────┘          └─────────────────────────┘
```

---

## 1. `run_extract_2025_seasonal.py` — 提取 2025 seasonal PDF

**用途**：從 FA25/HO25/SP25/SU25 資料夾遞迴掃描 PDF，提取 MC + POM 數據

**輸入**：`ONY/2025/{FA25,HO25,SP25,SU25}/*.pdf`（遞迴）

**輸出**：`ONY/_parsed/mc_pom_2025.jsonl`（append）

**特性**：
- Resume-safe：已處理的 `_source_file` 自動跳過
- 540 秒安全上限，超時中斷可重跑接續
- 從檔名/路徑提取 design number（D-number）
- Metadata 優先用 `all_years.jsonl`（CSV 匯出），PDF 提取值作 fallback

## 2. `run_extract_new.py` — 提取 2026 新 PDF

**用途**：從 2026 月份資料夾 + seasonal 資料夾提取

**輸入**：
- `ONY/2026/5/*.pdf`（月份，flat）
- `ONY/2026/{FA26,HO26,SP26,SU26,SP23,SP27}/**/*.pdf`（seasonal，遞迴）

**輸出**：`ONY/_parsed/mc_pom_2026.jsonl`（append）

**特性**：同上（resume-safe + 540s limit）

## 3. `reclassify_and_rebuild.py` — 分類 + 產出 pom_rules

**用途**：讀取所有 mc_pom JSONL，分類每個 design，產出前端可用的 pom_rules/ JSON

**輸入**：
- `ONY/measurement_profiles_union.json`（由 `rebuild_profiles.py` 產出）
- `ONY/_parsed/mc_pom_{2024,2025,2026}.jsonl`（Tolerance 資料）
- `ONY/pom_dictionary.json`（POM 中英文名稱）

**輸出**：
- `ONY/pom_rules/*.json`（81 bucket + _index + pom_names）
- `ONY/design_classification_v5.json`（分類 log）

**分類器**：
- `real_dept_v4()`：Department 6 類（Active / RTW / Swimwear / Sleepwear / Fleece / Collaboration）
- `real_gt_v2()`：Garment Type 11 類（優先序關鍵字比對）
- `infer_fabric()`：Fabric 推導（Knit / Woven / Denim）
- Gender：從 `rebuild_profiles.py` 的 `extract_gender()` 取得

**品牌過濾**：排除 ATHLETA（僅適用 Old Navy）

---

## 完整 Pipeline 流程

當 ONY 有新 PDF 進來時：

```
Step 1: 提取原料（擇一或兩者都跑）
  python run_extract_2025_seasonal.py   # 2025 seasonal 新 PDF
  python run_extract_new.py             # 2026 新 PDF

Step 2: 合併 profiles
  python rebuild_profiles.py            # mc_pom JSONL → measurement_profiles_union.json

Step 3: 分類 + 產出規則
  python reclassify_and_rebuild.py      # → pom_rules/*.json（81 bucket）

Step 4: Tier 1 強制
  python enforce_tier1.py               # 基礎尺寸強制歸 must

Step 5: 排序修正
  python fix_sort_order.py              # canonical zone sort order

Step 6: 修復 pom_names
  ⚠️ reclassify_and_rebuild.py 會覆蓋 pom_names.json
  需要從 uploads/pom_names.json 重新 merge「檔」terminology
```

---

## 版本紀錄

| 版本 | 日期 | 變更 |
|------|------|------|
| v5.0 | 2026-04-17 | 初版：74 bucket |
| v5.2 | 2026-04-17 | Tier 1 + Tolerance + Sort Order |
| v5.3 | 2026-04-18 | Centric 8 分數解析 bug fix |
| v5.4 | 2026-04-19 | Gender 修正 + canonical zone sort |
| v5.5 | 2026-04-20 | Maternity 改為純 Gender |
| **v5.5.1** | **2026-04-20** | **ATHLETA 排除 + IPSS→Active + Collaboration + Fabric** |

---

## 目前統計（v5.5.1）

- **1,056 designs**（排除 ATHLETA 12 筆）
- **81 buckets / 83 files**
- Department：Active 462 / RTW 411 / Swimwear 88 / Sleepwear 64 / Fleece 25 / Collaboration 6
- Fabric：Knit 804 / Woven 250 / Denim 2
- GT=UNKNOWN：54（空白 metadata 的 PDF）
