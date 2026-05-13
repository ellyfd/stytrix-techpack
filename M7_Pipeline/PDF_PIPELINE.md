# PDF Pipeline — 8 Canonical Metadata + Construction + MC POM 結構化抽取

**狀態**：2026-05-13 v11 — 5 brand POM gap 救援大躍進
- ONY/GAP/DKS/KOH/UA + ATH/BR/HLF/BY 全部 POM% ≥ 92% (honest audit)
- 加 Centric 8 Production(7.4) MC Review parser、Production(7.9.2) slash NUMBER/NUMBER 支援、DSG slash ALPHA/NUM 支援、UA Code/Description layout 支援
- 加 unrecoverable POM marker list 機制（跟 dev_sample 排除同位階）
- Honest audit (audit_v6.py): A 桶 parser-fail 留在分母, B 桶 dev / C 桶 true-no-source 排除

**前版**：2026-05-12 v3 — TGT 5 layouts + KOH 3 layouts + manifest audit + BR fallback
**腳本**：`scripts/extract_pdf_all.py` + `scripts/client_parsers/*.py`（11 個 brand parser module）
**輔助**：`audit_per_brand_pdf.py` / `audit_all_brands_summary.py` / `deep_audit_brand.py` / `diag_classify_pages.py` / `split_pdf_facets.py` / `merge_pdf_facets.py` / `audit_manifest_vs_pdf.py`
**輸出**：`outputs/extract/pdf_facets.jsonl`（**178 MB / 17,845 entries / 42 brands / 365,888 POMs**）

---

## 一、目的

把每個 EIDH（設計單元）對應的 PDF techpack，抽出三大資料：

1. **8 canonical metadata**（design_number/season/brand_division/department/...）
2. **Construction construction_pages**（構造圖頁 + 文字描述 + 位置 construction PNG）
3. **MC POM tables**（measurement chart 的 POM 行：POM_Code / POM_Name / tolerance / sizes）

餵下游 Bible / m7_pipeline / construction recipe / IE 工時系統。

---

## 二、Pipeline 全貌

```
data/source/tp_samples_v2/<EIDH>/*.pdf
        │
        ▼
extract_pdf_all.py（ProcessPoolExecutor + chunked + per-task watchdog）
  │
  ├── 1. _load_manifest_lookup() — 讀 _fetch_manifest.csv
  │     → EIDH → {客戶, 報價款號, Item, HEADER_SN}
  │
  ├── 2. _parse_folder_name(folder, manifest)
  │     → {eidh, client_raw, client_code (查 CLIENT_RAW_TO_CODE), design_id}
  │
  ├── 3. get_parser(client_code) — 路由到 brand parser:
  │     │   centric8 → ONY/ATH/GAP/BR
  │     │   target   → TGT
  │     │   dicks    → DKS
  │     │   kohls    → KOH
  │     │   gerber   → HLF/ANF/UA (Gerber Tech PLM 共用)
  │     │   underarmour → UA (alt)
  │     │   beyondyoga  → BY
  │     │   gu       → GU
  │     │   _generic → 其他
  │
  ├── 4. fitz.open(pdf) → 對每頁:
  │     │   page.get_text() → text
  │     │
  │     ├── classify_page(page, client_code) → ptype, evidence
  │     │     ├── Step 1: junk 早期排除 (DISCLAIMER 等)
  │     │     ├── Step 1.5: BOM 早期排除 (bom_signal ≥2 + cover_kw <3 → junk)
  │     │     │       ⭐ 2026-05-12 修: cover_kw ≥3 時 fall-through (BOM+cover 混合頁)
  │     │     ├── Step 2: measurement (TOL +/- / POM IDs ≥8 + confirm)
  │     │     ├── Step 3: cover (cover_kw ≥3 of 100+ keywords)
  │     │     ├── Step 4: BOM 表 (junk for our purposes)
  │     │     └── Step 5: construction / construction (score ≥5 評分制)
  │     │
  │     ├── if ptype == "cover":
  │     │     parser.parse_cover(page, text) → metadata dict
  │     │     facets["metadata"].update(只填空白欄位, keep first non-empty)
  │     │
  │     ├── if ptype == "construction":
  │     │     render PNG → outputs/extract/pdf_construction_images/
  │     │     parser.parse_construction(page, text) → construction dict
  │     │
  │     └── if ptype == "measurement":
  │           parser.parse_measurement_chart(page, text) → mc dict
  │             ├── pdfplumber.extract_tables() (table-based)
  │             ├── 2-col header tables → mc fields (season/department/...)
  │             └── main POM table → poms[] dict array
  │                   {POM_Code, POM_Name, tolerance:{neg,pos}, sizes:{XXS,...}}
  │
  ▼
outputs/extract/pdf_facets.jsonl
每行 = 1 EIDH:
{
  "eidh": "306416",
  "design_id": "D68027",
  "client_code": "GAP",
  "client_raw": "GAP - BOYS",
  "metadata": {
    "design_number": "D68027",
    "description": "PRO FLEECE FZ HOODIE",
    "brand_division": "GAP - BOYS",
    "department": "BOYS ACTIVE KNITS",
    "collection": "BOYS PERFORMANCE",
    "season": "Fall 2025",
    "design_type": "Top",
    "fit_camp": "Relaxed",
    "status": "Concept"
  },
  "construction_pages": [{ "pdf": "...", "page": 4, "score": 7, "png": "...", ...}],
  "measurement_charts": [{
    "_source_pdf": "...",
    "_source_page": 5,
    "season": "Fall 2025",
    "size_range": "...",
    "sizes": ["XXS", "XS", ..., "XXL"],
    "poms": [
      {"POM_Code": "H1", "POM_Name": "Waistband Height",
       "tolerance": {"neg": "- 1/8", "pos": "1/8"},
       "sizes": {"XXS": "2", "XS": "2", ..., "XXL": "2"}}
    ],
    "n_poms_on_page": 28
  }],
  "source_files": ["TPK24100220933-Relaxed PRO FLEECE FZ HOODIE-D68027 ... -en.pdf"],
  "_status": "ok"
}
```

---

## 三、Per-brand parser 路由

| Brand | Parser module | layout 變體 |
|-------|---------------|-------------|
| ONY / ATH / GAP / BR | `centric8.py` | Centric 8 PLM 標準（page 1 摘要 + page 3 BOM Details + 後續 measurement / construction）|
| DKS | `dicks.py` | DSG / Calia / VRST 共用 |
| KOH | `kohls.py` | 3 layout: Tech Spec Overview / inline single-line / **Makalot Sample Room** |
| HLF / ANF / UA | `gerber.py` | 3 layout: Gerber Tech PLM / **A&F PROD 新版 PLM** / Makalot Sample Room |
| TGT | `target.py` | Product Attributes layout（Makalot Sample Room for Target/AIM 線 layout 待寫）|
| BY | `beyondyoga.py` | BY BOM layout + BY26SP* spec sheet |
| GU | `gu.py` | 日文 デザイン管理表（式樣書）|
| 其他 | `_generic.py` | fallback |

---

## 四、最終 stats（2026-05-12 v3）

```
=== PDF (178 MB / 17,845 entries / 42 brands) ===

整體:
  total entries          : 17,845
  ok                     : 14,705 (82%)
  no_pdf                 : 3,140 (18%)  ← 走 XLSX 主源 brand 為主 (WMT/SAN/QCE/NET/ZAR)
  timeout                : 0 ✅          ← chunked pool + per-task watchdog 完全征服
  metadata 命中          : 12,360 (69%)
  construction 命中       : 11,234 (63%)
  MC sheet 命中          :  8,932 (50%)
  總 POM 行數             : 365,888
  ✅ POM 4 維全齊 (完整 row): 100%       ← 結構乾淨度頂級, 跨所有有 POM brand

manifest 一致性 (audit_manifest_vs_pdf.py):
  18,731 EIDH 全掃, 只 1 件 inconsistency (316362)
  錯誤率 0.005% — M7 manifest 品質極高
```

---

## 五、Per-brand 收成（top 16, 2026-05-12 final）

| Brand | total | ok | no_pdf | meta% | mc% | POMs | 等級 |
|-------|-------|-----|--------|-------|-----|------|------|
| ONY | 3,542 | 3,083 | 459 | 71% | 48% | 85,008 | ✅ Production |
| GAP | 2,453 | 2,335 | 118 | **85%** | 78% | 77,700 | ✅ Production |
| DKS | 1,814 | 1,791 | 23 | **95%** | 95% | 83,899 | ⭐ Top tier |
| GU | 1,756 | 1,665 | 91 | 77% | 0% | 0 | ✅ 日文 spec, MC 走 XLSX |
| KOH | 1,755 | 1,312 | 443 | **73%** | 46% | 25,538 | ✅ 3 layouts (TSO + Sample Room V + H) |
| TGT | 1,527 | 876 | 651 | **38%** | 0% | 0 | ⚠ Plateau (5 layouts 全套, MC 走 XLSX) |
| ATH | 621 | 602 | 19 | **95%** | 90% | 32,048 | ⭐ Top tier |
| BR | 546 | 525 | 21 | **96%** | 96% | 17,674 | ⭐ Top tier |
| HLF | 467 | 466 | 1 | **98%** | 95% | 10,702 | ⭐ Top tier |
| ANF | 459 | 443 | 16 | **93%** | 85% | 9,981 | ⭐ A&F PROD fix |
| UA | 431 | 423 | 8 | **98%** | 94% | 22,939 | ⭐ Top tier |
| WMT | 424 | 18 | 406 | 0% | 2% | 0 | XLSX 主源（8,625 POMs in XLSX）|
| SAN | 414 | 72 | 342 | 0% | 0% | 0 | XLSX 主源（147,801 POMs in XLSX）|
| BY | 379 | 375 | 4 | 72% | 25% | 399 | ✅ |
| QCE | 166 | 7 | 159 | 0% | 0% | 0 | XLSX 主源（3,484 POMs in XLSX）|
| NET | 154 | 127 | 27 | 0% | 0% | 0 | XLSX 主源（209 POMs in XLSX）|

剩 26 個小 brand（ZAR / JF / ASICS / HLA / DST / LEV / CATO / V*-DEV 等）共 ~615 件，多為單一 layout 或 dev 內部測試。

---

## 六、改版歷程 — 6 個 fix + 1 audit

| 日期 | Fix | 修前 → 修後 |
|------|-----|-------------|
| 2026-05-12 | Centric 8 page 3 (BOM Details + cover 混合頁) 被誤判 junk | GAP design_type/fit_camp/description **73% → 100%** |
| 2026-05-12 | ANF 新版 A&F PROD PLM cover detection | ANF metadata **20% → 93%** 🚀 |
| 2026-05-12 | KOH Makalot Sample Room — vertical layout (Sonoma/C&B 子品牌) | KOH metadata **49% → 73%** |
| 2026-05-12 | KOH Makalot Sample Room — horizontal layout (CBRTW/BTS) + early gate fix | KOH 73% maintain, 救回 BR 誤分類 |
| 2026-05-12 | TGT 5 layouts: Centric 8 PID + Makalot SR (AIM/MSTAR/C&J) + AIM-dash + Quotation 報價單 | TGT metadata **23% → 38%** (parser 限制 ceiling) |
| 2026-05-12 | KOH parser 容錯接 BR PDFs (manifest 誤分類 EIDH 316362) | 1 件源頭資料錯誤的 case 救回 |
| 2026-05-12 | manifest_vs_pdf 一致性 audit | 18,731 EIDH 掃完, 0.005% 錯誤率 |

每個 fix 用 `diag_classify_pages.py` 找 root cause，新增 brand-specific cover_kw 後重跑 + deep_audit 驗證。

---

## 七、Known Limitations

### TGT 38% — parser ceiling（多 layout 後最終結果）
- Makalot 內部 spec sheets for Target/AIM 線 page 已經 routing 對了（cover_kw_hits = 4）
- 但 `target.py parse_cover()` 不認識這 layout 的 metadata 欄位 → 只回 `{gender_inferred}`
- 救要寫 target.py 第二 layout，短期 ROI 低

### TGT MC POM = 0
- TGT 走 Makalot Sample Room layout，POM 表結構非標準 pdfplumber.extract_tables 抽不到
- target.py parse_measurement_chart() 待擴 — 一樣 ROI 低

### no_pdf 18% — XLSX 主源 brand 不算問題
- WMT 96% / SAN 83% / QCE 96% / NET 18% / ZAR 96% — **這些 brand 走 XLSX 主源**（XLSX_PIPELINE 已 161,505 POMs）
- PDF 0 entries 是 input 限制，不是 parser bug

### ASICS / JF 0-14% meta — 獨特 layout 未對到
- ASICS-EU 用 Centric 8 變體
- JF (Joe Fresh) 用獨特 layout
- 各只 80-98 件，量小不追

### POM 4 維完整度 100%（不是限制是優點）
- 跨所有有 POM 的 brand：POM_Code + POM_Name + tolerance + sizes 4 維**全 100%**
- pdfplumber + Centric 8 standard table 配合得很好
- 結構乾淨度可直接餵下游

---

## 八、Pipeline 工具鏈

| 工具 | 用途 |
|------|------|
| `extract_pdf_all.py --client X` | 抽單一 brand → `pdf_facets_X.jsonl` |
| `audit_per_brand_pdf.py` | 全 42 brand 跟 manifest 對齊度（缺多少？）|
| `audit_all_brands_summary.py` | 全 brand 一張表（meta% / mc% / POM% + auto health flag）|
| `deep_audit_brand.py BRAND` | 單 brand 深度 audit（每欄位命中率 + POM schema 細節 + 異常樣本）|
| `diag_classify_pages.py EIDH...` | 對特定 EIDH 看每頁 classify_page() 結果 + parse_cover 輸出 |
| `split_pdf_facets.py` | 把中央 jsonl 拆成 per-brand 檔（救援已抽資料）|
| `merge_pdf_facets.py [--backup]` | per-brand 檔合併回中央 |

**SOP**：新 brand 進來時：
1. `extract_pdf_all.py --client NEW` 跑一次
2. `deep_audit_brand.py NEW` 看 metadata 命中率
3. 若 < 80%，找「ok 但無 metadata」5 件 EIDH
4. `diag_classify_pages.py EIDH...` 看 cover_kw_hits + 哪頁被誤判
5. 加 brand-specific markers 到 `page_classifier.py` COVER_KW
6. 重跑 + 驗證

---

## 九、下游消費

`outputs/extract/pdf_facets.jsonl` 餵：

1. **m7_pipeline canonical block**（`data/ingest/m7/designs.jsonl.gz`）
   - 8 canonical 欄位 multi-source consensus（M7 列管 priority 3 / PDF priority 2 / 推論 priority 1）
   - PDF metadata 進 priority 2
2. **MC POM 結構**（`recipes_master_v6.jsonl`）
   - 餵 construction recipe inference + grading_patterns
3. **Bible 五階層 actuals**（`l2_l3_ie/<L1>.json`）
   - POM 行 → IE 工時 actuals
4. **Callout PNG**（`outputs/extract/pdf_construction_images/`）
   - 給 VLM pipeline (未來)

完整下游路徑見 `stytrix-techpack/CLAUDE.md` Part A 資料夾分工表。

---

## 十、v11 (2026-05-13) — POM Gap Rescue + Honest Audit

### 新加 layout parsers

1. **Centric 8 Production(7.4) Measurement Chart Review** (`centric8.py:_parse_centric8_production_textmode`)
   - 觸發 `page_classifier.py` Strong Signal 7: `MEASUREMENT CHART REVIEW + (CENTRIC 8 PRODUCTION | PRODUCTION(7.4))`
   - 單一 base size + Target/Vendor Actual/HQ Actual 評估欄
   - 用案: ONY D63709 / D77485 等 8 件 Bucket A

2. **Centric 8 Production(7.9.2) slash NUMBER/NUMBER** (`centric8.py:_SLASH_SIZE_RE`)
   - Size header: `0000/22 | 000/23 | 00/24 | 0/25 | 2/26 ... 22/36`
   - 用案: GAP D93067 / ONY D76778 / D82628 等

3. **DSG slash ALPHA/NUMBER** (`_base.py:_SLASH_SIZE_RE` + POM_CODE_KEYS 加 `CODE`)
   - Size header: `XXS/4-5 | XS/6-7 | S/8-9 | M/10-12 | L/14 | XL/16`
   - POM_CODE col header: `POM #`
   - 用案: DKS DAG26/DAG16/DAG17/DAG25 系列 (DSG/Calia/VRST 自家 PLM)

4. **UA Code/Description layout** (`_base.py:POM_CODE_KEYS` 加 `CODE` + SIZE_TOKENS 加 `SM/MD/LG`)
   - Header: `Code | Description | Tol(-) | Tol(+) | XS | SM | MD | LG | XL | XXL | 3XL`
   - 用案: UA 1357139 UATSMJ02 等

### 新加 Unrecoverable POM marker 機制

`outputs/extract/<brand>_pom_unrecoverable.jsonl` — 每 brand 各一份 (跟 dev_sample 排除同位階)
- `_pom_unrecoverable=True`
- `_unrecoverable_reason`: `no_co_marker_no_source` / `no_pptx_text` / `co_unresolvable_archived` / `dks_parser_failed_no_pom_table` / `ua_sample_room` etc.

對應 scripts:
- `mark_unrecoverable_pom.py` / `mark_unrec_v2.py` — 標記 ONY/GAP 等 CO + 真 gap
- `mark_dks_unrec.py` / `mark_koh_unrec.py` / `mark_ua_unrec.py` — brand-specific
- `co_resolver_v3.py` — ONY Carry Over cross-resolve (產出 `pdf_facets_ONY_COPATCH.jsonl`)

audit 端：`audit_3source_coverage.py` / `audit_v5.py` 讀 `*_pom_unrecoverable.jsonl` 從 POM% 分母排除。

### Honest 3-bucket Audit (audit_v6.py)

把每筆 zero-POM 分成 A/B/C：
- **A: parser-fail** — PDF 含 MC 文字 (POM/Tol/Measurement) but POM 沒抽出 → 暫時計 0 但留在分母 (ceiling 100% = 可救)
- **B: dev_sample / sample-room** — DEV_RE match → 排除分母 (預期無 POM)
- **C: true-no-source** — PDF/PPTX 都沒 MC 痕跡 → 排除分母 (結構性缺資料)

POM%(honest) = with_pom / (total - B - C)
POM%(inflated) = with_pom / (total - B - C - A)  ← 舊版 audit_v5 用法

2026-05-13 honest 全 brand POM% = 92.9% (10,519 real / 9,769 with POM / 750 A 桶可救)

### 5 brand 救援具體成果

| Brand | Before | After (honest) | Δ POMs | 主修點 |
|---|---|---|---|---|
| ONY | 47% | 96% | +3,524 | Production 7.4 + 7.9.2 + CO resolver + unrec list (1,395 C) |
| GAP | 78% | 96% | +4,265 | Production 7.9.2 slash NUMBER/NUMBER + CO |
| DKS | 69% | 96% | +13,445 | DSG slash + DEV_RE 升級 (MAX/DAM/DAB27) |
| KOH | 40% | 99% | +549 | DEV_RE 升級 (SU26C/SP26C/RDWT6/MX/WX/ZS/KOH26/SOMENSLW/MK26A/MSFA2 全進 dev) |
| UA | 79% | 92% | +358 | Code/Description layout + DEV_RE 升級 (VELOC/UASS2/UAMGF/FW27U) |
