---
name: data-pipeline-mapping
description: M7 PullOn pipeline data flow mapping — what file is produced by which tool, schema, who reads it. Read this BEFORE running any pipeline script to avoid using wrong source/tool/output combinations.
---

# M7 PullOn Pipeline — File × Tool × Data 固定對照表

⚠️ **每次跑 pipeline 之前 RTFM 這份對照,違反 = 資料用錯。**

---

## 1️⃣ 上游原始來源(都不在 repo,只在聚陽端)

| 來源 | 路徑 | 工具拉取 | 用途 |
|---|---|---|---|
| **M7 列管 xlsx** | `data/M7列管_YYYYMMDD.xlsx` (5/7 = 4644 EIDH PullOn+Leggings) | 手動下載 / 共享磁碟 | 全 EIDH 母清單 + 42 cols metadata |
| **SSRS 五階展開報表** | `nt-netsql2/ReportServer ReportServer/MTM_M6_FiveLevel_Detail` per EIDH | `fetch_m7_detail_ntlm.py` | csv_5level/*.csv (per EIDH 工序 raw rows) |
| **SSRS m7_report** | `nt-net2/MTM/Report/M6FiveLevelReport.aspx` per EIDH | `fetch_m7_report_playwright.py` (CDP) | m7_report.jsonl (BOM + IE summary) |
| **TP PDF/PPTX** | SMB `\\192.168.1.220\TechPack\TPK\<HEADER_SN>\核樣N\` | `2_fetch_tp.ps1` | pdf_tp/*.pdf + ppt_tp/*.pptx |

---

## 2️⃣ 工具 → 中介檔(在 `m7_organized_v2/`)

### `extract_raw_text_m7.py` 三個 mode

```
python scripts/extract_raw_text_m7.py --scan-dir m7_organized_v2 --output-dir m7_organized_v2 [MODE]
```

**MODE 選一個**(混用會出錯):

| MODE flag | 跑什麼 | 輸出 | 速度 |
|---|---|---|---|
| `--metadata-only` | PDF cover page + PPTX cover slide 抽 metadata | `metadata/designs.jsonl` (629 件 / dedup by design_id) | 30 秒 |
| `--pptx-only` | PPTX 整份內文 → txt | `pptx/<ID>.txt` 1106 檔 | 1 分鐘 |
| `--pdf-only` | PDF 偵測 callout 頁 → 216 DPI PNG | `callout_images/*.png` + `callout_manifest.jsonl` | **5-15 分鐘**(慢,要 PNG 渲染) |
| (沒加 flag) | 三個都跑 | 全部上 | 5-15 分鐘 |

### 其他工具

| 工具 | 輸入 | 輸出 |
|---|---|---|
| `vlm_fallback_api.py` --from-manifest | `callout_manifest.jsonl` + PNG | `vision_facts.jsonl` (Claude Vision 抽 callout text → ISO/L1) |
| `extract_xlsx_callout.py` | `data/source/L2_代號中文對照表.xlsx` | (helper, 不直接產檔) |

---

## 3️⃣ 中介檔總覽(都在 `m7_organized_v2/`)

| 檔名 | 路徑 | 行數(5/8) | 由誰產 | 內容 |
|---|---|---:|---|---|
| `csv_5level/<EIDH>_..._<CLIENT>_<style>.csv` | `m7_organized_v2/csv_5level/` | 4,643 檔 | `fetch_m7_detail_ntlm.py` | per EIDH SSRS 工序 raw rows |
| `m7_report.jsonl` | `stytrix-pipeline-Download0504/data/ingest/metadata/` | 3,645 EIDH | `fetch_m7_report_playwright.py` | 33 cols BOM/IE summary per EIDH |
| **`metadata/designs.jsonl`** ⭐ | `m7_organized_v2/metadata/` | 629 | `extract_raw_text_m7.py --metadata-only` | PDF cover page + PPTX cover slide metadata,30 cols(client/season/brand_division/design_type/...) |
| `designs.jsonl` (舊,5/5 版) | `m7_organized_v2/` (root) | 395 | 同上,5/5 跑的 | **STALE,不用**(留 archive 用) |
| `pptx/<ID>.txt` | `m7_organized_v2/pptx/` | (per-EIDH) | `extract_raw_text_m7.py --pptx-only` | PPTX 整份文字 |
| `callout_images/*.png` | `m7_organized_v2/callout_images/` | ~3,000+ PNG | `extract_raw_text_m7.py --pdf-only` | PDF 高分數頁 216 DPI 渲染 |
| `callout_manifest.jsonl` | `m7_organized_v2/` | 556(5/7 rebuild 後) | 同上 | callout PNG 索引 + filename + design_id |
| `vision_facts.jsonl` | `m7_organized_v2/` | 380 | `vlm_fallback_api.py` | Claude Vision 從 PNG 抽 ISO/L1/zone facts |
| `aligned/final_aligned_to_l5.csv` | `m7_organized_v2/aligned/` | (history) | (legacy alignment script) | PPTX_zh + zh callout → L1-L5 align(reference) |

---

## 4️⃣ 整合工具 → platform 推送檔

### `build_m7_pullon_source_v3.py` (canonical, v1+v2 deprecated)

```
python scripts/build_m7_pullon_source_v3.py
```

**讀什麼**:

| 中介檔 | 作為什麼維度 |
|---|---|
| M7 列管 xlsx | 4,644 EIDH 母清單 + W/K + 客戶 + 報價款號 |
| `csv_5level/*.csv` | per-EIDH 工序 (L1-L5 + machine + skill + sec) |
| `m7_report.jsonl` | BOM (fabric_name, ingredients, quantity_dz) + IE summary |
| `metadata/designs.jsonl` (新版) | PDF/PPTX cover page metadata (season, brand_division, design_type) |
| `callout_manifest.jsonl` | callout 數量 by design_id |
| `vision_facts.jsonl` | VLM facts 數量 by design_id |
| `data/zone_glossary.json` | L1 中文 ↔ code mapping |

**寫什麼**(在 `outputs/platform/`):

| 檔名 | 大小 | 內容 | platform 端用途 |
|---|---|---|---|
| `m7_pullon_source.jsonl` | 7.5 MB / 746 entries | aggregated by 6-dim key (gender/dept/gt/it/fabric/l1) + by_client tree | platform `build_recipes_master.py` 的 `build_from_m7_pullon()` 吃 |
| `m7_pullon_designs.jsonl` | 70 MB / 3,900 designs | per-EIDH 完整履歷(全 raw 保留) | Phase 2.4 derive_view_designs_index 吃 |

---

## 5️⃣ Platform 端推送(`data/ingest/m7_pullon/`)

| Source 檔 (M7 端) | Push 到 platform | 怎麼 push |
|---|---|---|
| `outputs/platform/m7_pullon_source.jsonl` (7.5 MB) | `data/ingest/m7_pullon/entries.jsonl` | `push_m7_pullon_v3.ps1` |
| `outputs/platform/m7_pullon_designs.jsonl` (70 MB) | `data/ingest/m7_pullon/designs.jsonl.gz` (gzipped → ~6 MB) | 同上,自動 gzip |

---

## 6️⃣ 常見錯誤對照

| 症狀 | 原因 | 修法 |
|---|---|---|
| `designs.jsonl` 只有 395 件 | 用了舊路徑 `m7_organized_v2/designs.jsonl` (5/5 stale) | 改用 `m7_organized_v2/metadata/designs.jsonl`(5/8+ 新版) |
| callout 數量驟降 | 跑了 `--pdf-only --force` 重抽,manifest 被 rewrite | 確認 `.bak_*` 備份還在,需要 dedup 用就 reload |
| `m7_pullon_source.jsonl` 1 line / 2KB | v3 build script 中斷 / 沒寫完整 | 重跑 `build_m7_pullon_source_v3.py`(check stat output 「746 entries / 7.2 MB」) |
| build_m7_pullon_source v1 / v2 跑 | DEPRECATED | 用 v3,v1/v2 已 sys.exit(2) |
| pdf_tp/ 缺檔 | SMB fetch 失敗 / TP 資料夾找不到 | 跑 `2_fetch_tp.ps1 --retry-failed` |

---

## 7️⃣ 完整流程順序(從零跑)

```bash
# Step 1. 拉新一輪 M7 列管 xlsx → data/
# (手動下載新版,或從共享磁碟)

# Step 2. fetch SSRS 五階展開 (per EIDH 工序)
python scripts/fetch_m7_detail_ntlm.py --output-dir m7_organized_v2/csv_5level

# Step 3. fetch SSRS m7_report (BOM + IE summary)
python scripts/fetch_m7_report_playwright.py --output stytrix-pipeline-Download0504/data/ingest/metadata/m7_report.jsonl

# Step 4. fetch TP 資料夾 (SMB)
.\scripts\2_fetch_tp.ps1

# Step 5. 抽 metadata (PDF/PPTX cover page)
python scripts/extract_raw_text_m7.py --scan-dir m7_organized_v2 --output-dir m7_organized_v2 --metadata-only --force

# Step 6. (Optional) PDF callout PNG 渲染 + VLM (慢,只在要新 callout 時跑)
python scripts/extract_raw_text_m7.py --scan-dir m7_organized_v2/pdf_tp --output-dir m7_organized_v2 --pdf-only --force
python scripts/vlm_fallback_api.py --from-manifest --skip-existing --append --model sonnet

# Step 7. 整合 source (給 platform 用)
python scripts/build_m7_pullon_source_v3.py

# Step 8. Push 到 platform repo
.\scripts\push_m7_pullon_v3.ps1
```

---

## 8️⃣ Schema 變動歷史(避免回頭混)

| 日期 | 變動 |
|---|---|
| 2026-05-04 | M7 列管表 5/4 版,1180 EIDH PullOn |
| 2026-05-05 | designs.jsonl 跑了 395 件(舊路徑 root) |
| 2026-05-07 | M7 列管升級到 5/7 版,4644 EIDH PullOn+Leggings |
| 2026-05-08 | extract_raw_text_m7 輸出改 `metadata/designs.jsonl` 子目錄(因應 PDF + PPTX 分流);build_m7_pullon_source 升 v3(maximize-per-款 + multi-source fabric) |
| 2026-05-08 | build_m7_pullon_source v1+v2 標 DEPRECATED;v3 是唯一 canonical |

---

## 不要碰的東西

- ❌ `m7_organized_v2/designs.jsonl` (root)— 5/5 stale,只 archive 用
- ❌ `build_m7_pullon_source.py` / `build_m7_pullon_source_v2.py` — DEPRECATED, 跑會 sys.exit(2)
- ❌ 改 `csv_5level/*.csv` 結構 — SSRS report 直接 export,改會 break parse
- ❌ 從 `m7_pullon_designs.jsonl` 砍 `five_level_steps`(73% 體積)— 違反「資料越齊越好」原則
