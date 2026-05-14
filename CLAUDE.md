# StyTrix Techpack — 資料櫃整理規則與清理 SOP

給未來協作者(包含 Claude Code、工程師、資料管理者)的 repo 使用守則。
新資料進來前先看 Part A,舊資料要丟前必跑 Part B。

---

## 為什麼有這份文件

2026-04-22 做 repo 清理時踩到地雷:`L2_Confusion_Pairs_Matrix.md` 被判為「沒人用可刪」,
實際上它被 `L2_VLM_Decision_Tree_Prompts_v2.md` 第 4、7 行明列為「資料來源」與「姊妹文件」,
是現役 VLM 辨識系統的 49 組 hard-negative 訓練料。刪了會斷資料鏈。
(2026-04-23 補記:此後兩份已主動合併——混淆對照表的內容整合入判斷樹末尾(§ 混淆對照表),不再是獨立檔案。)

教訓:repo 像個開放式倉庫,資料進來沒人講清該進哪個夾子;要丟時也沒 SOP 確認全廠沒人在用。
這份文件就是補這塊。

---

## 2026-05-14 Code Review 實測快照(數字皆 ground-truth)

跑過實際 build / API / index.html fetch 後驗到的 ground truth(以下數字若跟其他段落 diverge,以本段為準):

| 維度 | 量測值 | 量測方法 |
|---|---|---|
| `pom_rules/` bucket count | **137** | `ls pom_rules/*.json \| grep -vE "_index\|pom_names" \| wc -l` |
| `pom_rules/_index.json` version / date | v5.5.1 / 2026-05-11 | 直接讀 |
| `pom_rules/` source_brand_codes | 34 brands | `_index.json:_meta.source_brand_codes` |
| `data/ingest/m7/entries.jsonl` | **5,076 entries** / 30 MB | `wc -l` + `ls -l` |
| `data/ingest/m7/designs.jsonl.gz` | **31 MB gzipped / 332 MB uncompressed / 18,300 designs** | `gzip -dc \| wc -l` |
| `data/runtime/brands.json` brand count | **24 brands** | `python3 scripts/core/build_brands.py` 後讀 JSON |
| `data/runtime/recipes_master.json` entries | **6,571 entries** | `build_recipes_master.py --strict` 跑完讀 |
| `data/runtime/bucket_taxonomy.json` | 28 v4 (dict) + 59 legacy_buckets (dict) | 直接讀 |
| `l2_l3_ie/` size | **137.4 MB** / 38 L1 + `_index.json` | `_index.json:total_size` |
| `l2_l3_ie/` 最大 L1 檔 | BM 23.4 MB / SB 18.2 MB / SA 16.7 MB | `ls -l` |
| `l2_l3_ie/_index.json` schema | top-level `"schema": "phase2"` | 不是 `_metadata.schema`,L1 檔內才是 |
| `recipes/` count | 71 recipe JSON + `_index.json` = 72 | `ls recipes/*.json` |
| `data/runtime/*.json` count | **15 檔**(2026-05-14 從 18 縮 — 3 個 Pipeline B 內部產物搬到 `pom_rules/_derive/`)| `ls data/runtime/*.json \| wc -l` |
| `data/runtime/code_manifest.json` curated files | **317 個** / 34 KB | `build_code_manifest.py` 跑完讀 |
| `scripts/core/*.py` entry-point | **21 支**(含 3 `_` prefix helper) | `ls scripts/core/*.py` |
| `star_schema/scripts/*.py` | **6 支** | `ls star_schema/scripts/*.py` |
| `M7_Pipeline/` py 總數 | **134 py**(109 in scripts/ + 5 _test_*.py root + 20 in misc subdir)+ **9 ps1** | `find M7_Pipeline -name "*.py"` |
| `validate_buckets.py --strict` | exit 0,clean | 實跑 |
| `build_recipes_master.py --strict` | exit 0,6571 entries,B-tier 0 / A-tier 277(不擋) | 實跑 |
| `derive_view_recipes_master.py` | no-op(0 had `_m7_*` stripped) | 實跑 — 因 build_recipes_master 已不再 emit `_m7_*` 欄,Step 4a 變雞肋,但保留 idempotency |
| `derive_bible_actuals.py --all --in-place` | 38 L1 重算,actuals coverage 2.3%-96.8% by L1 | 實跑 |
| Vercel deploy on PR #349 | success(2026-05-14T10:42Z) | GitHub MCP `get_status` |

### 量測時發現的問題(已修)

1. **`api/analyze.js:47` 註解 `iso_lookup_factory_v4.2`** ✗ → 改 `v4.3`(實際讀的是 v4.3)
2. **`index.html` 多處「81 bucket / 81 buckets」** ✗(L3500/3533/3571/3607/3664/3697/4853)→ 改 `137 bucket`,影響 Pipeline 外送包 README 給外部協作單位的文字
3. **CLAUDE.md / 網站架構圖.md 多處 4,562 designs / 4,644 EIDH / 746 行 / 79.1 MB / 21 brand** ✗ → 全部改成實測值(18,300 / 5,076 / 137.4 MB / 24 brand)
4. **`docs/spec/網站架構圖.md` Tech Debt: `7% 增量還算合理`** ✗ → 改 `+86%`,並補充「`designs.jsonl.gz` 332 MB uncompressed 會吃瀏覽器 ~400 MB 記憶體」這條 mobile risk

### 量測時發現的問題(2026-05-14 全部清理完)

1. ✅ **`l2_l3_ie/l2_l3_ie/` + `l2_l3_ie/l2_l3_ie/l2_l3_ie/` nested 重複目錄** — 跑完 Part B 5-step gate:literal-name grep 只有 CLAUDE.md(audit 自己)有命中;`l2_l3_ie` basename grep 只指向頂層 `l2_l3_ie/`(38 L1 + `_index.json`);無 glob/iterdir 命中;無 fetch / producer write 命中。`git rm -r l2_l3_ie/l2_l3_ie/` 後 `l2_l3_ie/` 196 MB → 138 MB(回收 87 MB)。出處 commit `efef83e` / `5f1455a`(rename detection bug,git mv 時被連帶建立的 nested 副本)。
2. ✅ **`data/ingest/m7_pullon/` 舊目錄** — 跑完 gate:`build_recipes_master.py:76` `M7_PATH` 跟 `derive_bible_actuals.py:60` `M7_DESIGNS` 都指 `data/ingest/m7/`;workflow trigger 也是 `m7/`;`m7_pullon/` 目錄無 `facts.jsonl`,Step 6 glob `*/facts.jsonl` 不會掃到。`git rm -r data/ingest/m7_pullon/` 回收 13 MB。`data/source/M7_PULLON_DATA_SCHEMA.md` 同步把 path 從 `data/ingest/m7_pullon/` 改 `data/ingest/m7/`(script / function 名 `build_m7_pullon_source_v3.py` 等保留)。
3. ✅ **`M7_Pipeline/_test_*.py` 5 隻**(`_test_ony` / `_test_ony3` / `_test_ony_fix` / `_test_by_classify` / `_test_by_parser`)— 內容掃過全是聚陽 Windows 端 ad-hoc debug script,hardcode `tp_samples_v2/...` 本地路徑(repo 無此目錄)。Step 2-7 gate 全空(除了 CLAUDE.md 自己 audit 註)。直接 `git rm`。
4. ✅ **`vercel.json` `includeFiles` 收緊** — 從 `{data/**, docs/spec/techpack-translation-style-guide.md}`(bundle 91 MB)改成顯式 4 檔列表 `{data/runtime/l2_visual_guide.json, l2_decision_trees.json, l1_standard_38.json, docs/spec/techpack-translation-style-guide.md}`(bundle 184 KB)。`analyze.js` 實際只讀這 4 檔(grep `readFileSync` 確認),其他 75 MB `data/ingest/` 跟 14 MB `data/runtime/` 內的其他檔都不需要進 function bundle。**重要**:之後若 `analyze.js` 要新增讀檔,記得同步加進 `vercel.json` `includeFiles` 列表。

### 待 user decision(暫不動)

5. **`designs.jsonl.gz` 332 MB JSON parse 吃瀏覽器 ~400 MB 記憶體** — `filterBibleByCategory` lazy fetch 設計需要重審。長線方案:① 改 server-side filter API(`api/filter_bible.js` 接 brand/fabric/gender/dept/gt/it,server 端讀 jsonl.gz,只回需要的 step actuals)② 拆 per-brand designs.jsonl.gz。屬於架構變更,需 PM 決定。

---

## M7 Extract Pipeline v11（2026-05-13 5 brand POM gap 救援 + honest audit）

**核心成果**:
- 5 大 brand POM% (honest 算法, audit_v6.py): **ONY 96% / GAP 96% / DKS 96% / KOH 99% / UA 92%**
- 全 brand POM% honest = **92.9%** (10,519 real / 9,769 with POM / 750 A 桶 parser-fail 可救)
- Total POMs **365K → 591K** (+62% 增量)

**新增 4 個 layout parsers** (見 `PDF_PIPELINE.md` 第十節):
1. Centric 8 Production(7.4) Measurement Chart Review (textmode fallback, ONY/GAP 用)
2. Centric 8 Production(7.9.2) slash NUMBER/NUMBER (`0000/22 | 0/25` 等)
3. DSG slash ALPHA/NUMBER (`XXS/4-5 | M/10-12`, DKS DAG/DAB 主線)
4. UA Code/Description layout (`Code | Tol(-) | Tol(+) | XS | SM | MD | LG`)

**新增 Unrecoverable POM 排除機制**(跟 dev_sample 同位階):
- `outputs/extract/<brand>_pom_unrecoverable.jsonl` — 每 brand 一份, 含 `_pom_unrecoverable=True` + `_unrecoverable_reason`
- 5 reasons: `no_co_marker_no_source` / `no_pptx_text` / `co_unresolvable_archived` / `<brand>_parser_failed_*` / `<brand>_sample_room`
- ONY Carry Over cross-resolver (`co_resolver_v3.py`): PPTX 「尺寸表參考 D-code」反查前季 PDF POM → 46 件補回 3,750 POMs
- audit 端 `audit_3source_coverage.py` / `audit_v5.py` / `audit_v6.py` 讀此 list 排除分母

**DEV_RE 擴張** (audit_3source_coverage.py 加 confirmed prefix):
- KOH: `SU26C/SP26C/SP26S/SU26S/FA26C` 季別+CB / `KOH26` / `RDWT6/RDMX6/RDEX6/RDMT6` / `MX5-6 [A-Z]*/WX5-6 [A-Z]*` / `ZS5-6 F*` / `SOMENSLW/MK26AW/MSFA2`
- UA: `VELOC/UASS2/UAMGF/FW27U` (UATSM 排除 — Elly 確認 1357139 有 POM, parser 救回)
- DKS: `MAX/DAM/DAB27` (DAG/DAB 主線 是真 PLM, 不放)

**Honest 3-bucket audit** (`audit_v6.py`):
- A: parser-fail → 留在分母 (應修, ceiling 100%)
- B: dev_sample / sample-room → 排除分母
- C: true-no-source → 排除分母 (跟 dev_sample 同性質)
- POM%(honest) = with_pom / (total - B - C), A 仍在分母懲罰

**Sample Room ⚠ 重要規則**: KOH/DKS/UA 的 Sample Room prefix 升 dev_sample 後不需要再特別寫 unrec list — 它們會自動被 DEV_RE 攔下進 B 桶。`<brand>_pom_unrecoverable.jsonl` 主要保留 C 桶 (CO unresolvable / no_pptx_text 等真實無資料).

詳細 v11 改版見 `Source-Data/M7_Pipeline/PDF_PIPELINE.md` 第十節。

---

## M7 Extract Pipeline v10（2026-05-12 三 source 全收齊）

**核心輸出**(`Source-Data/M7_Pipeline/outputs/extract/`):

| Source | Entries | 主要產出 | 文件 |
|--------|---------|----------|------|
| `pdf_facets.jsonl` | **17,845** / 178 MB | **365,888 POMs / 100% POM 4 維 complete / 0 timeout** | `PDF_PIPELINE.md` |
| `pptx_facets.jsonl` | **18,731** / 135 MB | **708K constructions / 82% L1 / 19% iso** | `PPTX_PIPELINE.md` |
| `xlsx_facets.jsonl` | 18,731 entries (944 MCs) | **161,505 POMs + 207 construction_iso_map** | (in extract_xlsx_all.py) |

**11 brand parsers**: centric8 (ONY/ATH/GAP/BR) / dicks / kohls / target / gerber (HLF/ANF/UA) / underarmour / beyondyoga / gu / _generic fallback

**6 fix + 1 audit (大躍進)**:
- ⭐ Centric8 BOM-cover 混合頁誤判 → GAP design_type/fit_camp/description 73% → 100%
- ⭐ ANF A&F PROD 新版 PLM cover detection → ANF metadata **20% → 93%**
- KOH 3 layouts (Tech Spec + Sample Room V/H, CBRTW/BTS) → 49% → **73%**
- TGT 5 layouts (Centric 8 PID + AIM/MSTAR/C&J + AIM-dash + Quotation) → 23% → **38% ceiling**
- KOH parser 容錯接 BR 誤分類 PDF (EIDH 316362)
- chunked pool + per-task 90s watchdog → **0 timeout**(Python 3.14 + Windows multiprocessing 完全征服)
- `audit_manifest_vs_pdf.py`: 18,731 EIDH 全掃 → 只 1 件 inconsistency (**0.005% error rate**)

**命名統一 (2026-05-12 Big-bang rename)**:
- `callouts` → `constructions` / `construction_pages`
- `iso_callouts` → `construction_iso_map`
- `mcs` → `measurement_charts`
- `parse_callout` → `parse_construction_page` / `parse_mc` → `parse_measurement_chart`
- ptype `"callout"` → `"construction"`
- folder `pdf_callout_images/` → `pdf_construction_images/`
- 詳見 `PIPELINE_GLOSSARY.md`

**14 ISO 官方碼**(對齊 `data/runtime/iso_dictionary.json`): 301/304/401/406/407/504/512/514/514+401/514+605/516/602/605/607
**38 L1 official codes**(對齊 `data/runtime/l1_standard_38.json`)

**Per-brand metadata% 等級**(top 12):
- ⭐ **95%+**: DKS 95 / ATH 95 / BR 96 / HLF 98 / UA 98 / ANF 93
- ✅ **70-85%**: GAP 85 / GU 77 / KOH 73 / BY 72 / ONY 71
- ⚠ **plateau**: TGT 38 (Quotation = M7 manifest 重複跳)
- XLSX 主源(PDF 預期 0%): WMT 8,625 POMs / SAN 147,801 POMs / QCE 3,484 POMs / NET 209 POMs

詳細數字 + per-brand parser routing + 6 fix 改版歷程見 `Source-Data/M7_Pipeline/PDF_PIPELINE.md` / `PPTX_PIPELINE.md`。

---

## Part A — 資料夾分工表

> **2026-05-14 快照**(在 2026-05-11 之上加 M7_Pipeline v11 import + m7_pullon → m7 rename + POM rules v6/v7/v8 + validate_pom_rules workflow 拆出 + Code 瀏覽 modal):
>
> 1. **`data/ingest/m7_pullon/` → `data/ingest/m7/` rename**(2026-05-12 commits `3ed9a49` / `a0dc4f6`):聚陽 PullOn 是當下唯一料源,目錄名加 `_pullon` 是預備擴張,但實務上多餘 — 縮短成 `m7/`。同步改 `M7_PATH` 常數(`star_schema/scripts/build_recipes_master.py:76`)、`build_brands.py` 路徑、workflow `paths:` trigger。舊 `data/ingest/m7_pullon/` 目錄殘留但不再被讀(下輪 audit 可以 clean orphan)。**注意**:script/function 名 `build_from_m7_pullon()`、`build_m7_pullon_source_v3.py`、`push_m7_pullon_v3.ps1`、檔名 `data/source/M7_PULLON_DATA_SCHEMA.md` 仍保留原名(它們是聚陽 PullOn 產品線的 identifier,不是 repo 路徑)。
>
> 2. **M7_Pipeline v11 import**(2026-05-13 commit `17b5629`,scripts + docs only,no PDF uploads):repo 加 `M7_Pipeline/` 頂層目錄(原本只在聚陽 Windows 端跑,本次把 v11 流程文件 + 109 隻 py(scripts/) + 9 隻 ps1 + 5 隻 _test_*.py(root) 拷一份進 repo 做 audit/handover 用,raw PDF 不進)。組成:
>    - `M7_Pipeline/PIPELINE.md`(總覽)/ `PDF_PIPELINE.md`(v11 5 brand POM 救援 + audit_v6 honest)/ `PPTX_PIPELINE.md`(708K constructions)/ `PIPELINE_GLOSSARY.md`(callout → construction rename 對照)/ `construction-page-rules.md`(3 format 類型 + signal scoring)
>    - `M7_Pipeline/scripts/`:Phase A fetch / Phase C extract(11 brand parsers + 4 new layouts)/ Phase E build / Phase F audit
>    - `M7_Pipeline/data/`(canonical_aliases.json / client_canonical_mapping.json / iso_dictionary.json / zone_glossary.json / pullon_l1_l2_l3_patterns.md)
>    - **v11 honest 3-bucket audit** (`audit_v6.py`):全 brand POM%(honest)= **92.9%**;5 brand POM gap rescue:ONY 47→96 / GAP 78→96 / DKS 69→96 / KOH 40→99 / UA 79→92;Total POMs **365K → 591K**(+62%)。詳細見 CLAUDE.md L17 起的「M7 Extract Pipeline v11」章節。
>
> 3. **POM rules v6 → v7 → v8**(2026-05-13 commits `d697e94` / `fa26f0b` / `23be6da`):pom_rules bucket 算法三連跳,從 81 → 137 個 bucket,2026-05-13 重生產:
>    - **v6**:garment_type 改用 M7 manifest 「Item」原值(不再用 derived 9-bucket GT taxonomy)。bucket key = `<Dept>_<MK_Item>|<Gender>`,**從 81 → 136 buckets / 611K POMs / 15 brands / 23 MK Item types**。
>    - **v7**:gender + fabric 也改走聚陽 M7 列管(PRODUCT_CATEGORY + W/K 欄)。Gender UNKNOWN 1,254 → 0;Fabric Knit 2,548 → 7,326 / Woven 7,699 → 2,931。bucket 136 → 129。
>    - **v8**:Maternity 保留(40 件 design)— v7 把 MATERNITY 跟著 M7 gender 摺進 WOMENS(M7 列管沒 MATERNITY 維度);v8 加 `resolve_gender()` overlay,把 MATERNITY override 回 mk_gender。bucket 129 → 137(+8 MATERNITY)。
>    - bucket files 跨 34 brand codes(`pom_rules/_index.json:_meta.source_brand_codes`,含 GAP / ONY / ATHLETA / BRFS / CALIA / DSG / KOH / DKS / ANF / HLF / VRST / UA / BY / QCE / 等 — 不再只有 ONY 一家)。
>
> 4. **`.github/workflows/validate_pom_rules.yml` 拆出**(2026-05-13 commit `6642671`):POM rules 校驗從 `rebuild_master.yml` Pre-Step 3 抽成獨立 workflow,trigger `push: [pom_rules/**, validate_buckets.py, workflow file]`。只跑 `python scripts/core/validate_buckets.py --strict`(schema gate < 1s,exit 1 on drift)。理由:POM rules **regeneration** 需要外部 `$POM_PIPELINE_BASE`(8,892 設計 × `_parsed/mc_pom_*.jsonl`),CI 不具備;CI 只能驗 schema。regen 走聚陽 Windows 本機跑 + PR push,然後 validate_pom_rules.yml 攔 schema。**`rebuild_master.yml` Pre-Step 3 仍同步跑** `validate_buckets.py --strict`(L118)— 雙重保險。
>
> 5. **`scripts/core/build_code_manifest.py` + Code 瀏覽 modal**(2026-05-13 commits `bebd0c2` / `e0bd78b`):前端 `index.html` 加 `CodeBrowserModal`(L2684-3000),GitHub 風格的 in-app file browser(左目錄樹 + 右 Prism.js syntax highlight,5 MB 單檔上限,從 repo root relative fetch)。**Source**:`data/runtime/code_manifest.json` ~30 KB,由 `scripts/core/build_code_manifest.py` 掃 curated globs(`data/runtime/*.json` / `docs/spec/*.md` / `pom_rules/*.json` / `l2_l3_ie/*.json` / `recipes/*.json` / `scripts/{core,lib}/*.py` / `star_schema/scripts/*.py` / `api/*.js` / root `*.md` / `vercel.json` / `.gitignore`)產 flat list(`{path, size, ext}` + `large_threshold_bytes: 1000000`)。掛在管理選單最後一個。**注意**:這個 derive script 不在 `rebuild_master.yml` 任何 step 跑,要重產要手動跑(本機 / 外部)再 commit。
>
> 6. **`callout` → `construction` 語意統一**(2026-05-12 commit `355ffd8`):2026-05-12 完成第二輪 rename — pipeline 內部仍有少數 `callout` 字眼;這次把:
>    - `data/ingest/pdf/callout_images/` → `pdf/construction_images/`(已在 `extract_raw_text.py:571`、`vlm_pipeline.py:53` + workflow 落實)
>    - VLM 函式 `analyze_callout_images_with_claude` → `analyze_construction_images_with_claude`(`vlm_pipeline.py:440`)
>    - rebuild_master.yml 內部 comment 同步
>    - **未變**:`data/zone_glossary.json` 內的 `KW_TO_L1_TOPS/BOTTOMS/ZH_ZONE_TO_L1`(客人 callout 寫法 → L1 router,「callout」這裡是客人術語,不是 pipeline 流程)— 保留。
>
> 7. **前端 `data/runtime/brands.json` 動態載入 + brand-aware filter cascade**(commit `5ba7757`):`index.html` 用 brands.json 取代硬寫 BRANDS,且 Fabric / Gender / Dept / GT 下拉根據 brand-specific design distribution 過濾(只顯示該 brand 實際有的選項)。資料源還是 `data/runtime/recipes_master.json` 的 `entries[].client_distribution`,boot 時拉一次。
>
> 8. **`data/client_canonical_mapping.json` v3**(2026-05-08 commit `fefea8d`,但今天才在 docs 補):109 KB,22 客戶 subgroup_codes × 4 維 ground truth(gender / dept / fabric / category,例:A&F ACTIVE → 100% KNIT / 98% WOMEN / 95% ACTIVE / 88% LEGGINGS)+ PDF field mapping。**消費端**:M7_Pipeline `derive_metadata.py` / `generate_bucket_taxonomy_from_mk.py` 用,**不在 platform CI runtime 路徑上**(platform 用 `data/source/canonical_aliases.json`)。位置在 `data/` 而非 `data/source/` 是歷史結果,2026-05-08 v3 合併 v1 + v2 時暫放,下輪重組可考慮搬。

> **2026-05-11 快照**(在 2026-05-09 之上加 m7 24-brand + Bible idempotency 修):
>
> 1. **m7 跨 24 brand**(原 10 → +11 新 brand 在 2026-05-11;後續 m7 push 加進 ASICS / LEV / CATO / SMC 等到 24)。source 端聚陽 push 進 **18,300 件 EIDH**(`designs.jsonl.gz` 332 MB uncompressed / 31 MB gzipped)/ **5,076 entries**(`entries.jsonl` 30 MB);Bible(`l2_l3_ie/*.json`) actuals.by_brand 跟著刷,大小 73.7 → **137.4 MB**(+86%,2026-05-14 實測,比原 2026-05-11 預估 79.1 MB 大很多 — m7 entry growth 從 768 → 5,076 ×6.6 帶來的)。
>
> 2. **`derive_bible_actuals.py` idempotency 修**(原 `derive_view_l2_l3_ie.py`,2026-05-11 改名;見 #5):2026-05-08 第一次升 Phase 2 dict schema 後,script 對已是 dict 的 step 直接 pass-through,不重算 actuals → 新 brand 進 m7 後 Bible 不會跟著刷,即使 `--all --in-place` 也 0 diff。修法:dict step 也走完整 lookup → recompute → 寫入(actuals empty 時清掉,避免殘留)。
>
> 3. **`data/runtime/brands.json` 新檔 + Step 4c**:`scripts/core/build_brands.py` 從 `entries.jsonl` client_distribution 聚合各 brand 的 n_entries / n_designs,排序 n_designs DESC 寫進 `data/runtime/brands.json`(~1.8 KB)。CI `rebuild_master.yml` Step 4c 在 Step 4b 之後跑,brands.json 跟著 m7 push 自動更新。
>
> 4. **前端 Brand 下拉改動態**(`index.html`):拔掉硬寫 10 entry 的 `const BRANDS = [...]`,改 boot 時 eager fetch `./data/runtime/brands.json`。新 brand 進 m7 → CI 重產 brands.json → 用戶 reload 就看到,不用手 patch 前端常數。
>
> 5. **Bible 兩支腳本 + workflow 改名**(避免跟 `l2_l3_ie/` 目錄撞名):
>    - `scripts/core/build_l2_l3_ie.py` → `scripts/core/build_bible_skeleton.py`(從 xlsx 建骨架,brand-agnostic,本機 SOP)
>    - `star_schema/scripts/derive_view_l2_l3_ie.py` → `star_schema/scripts/derive_bible_actuals.py`(掛 m7 觀察值,CI Step 4b)
>    - `.github/workflows/build_l2_l3_ie.yml` → `.github/workflows/build_bible_skeleton.yml`
>    - 目錄 `l2_l3_ie/` 保留(L2/L3/IE 三層工時名有資訊量,改成 bible/ 是內部黑話)
>
> 6. **前端 `filterBibleByCategory` 6 維 filter + canonical alias 擴張**(commit `83727c0`):
>    - **filterBibleByCategory(bible, {brand, fabric, gender, dept, gt, it})**(`index.html:216`)— 在 `filterBibleByBrand`(只 brand)之上加 5 維:runtime 反查 `data/ingest/m7/designs.jsonl.gz`(31 MB gzipped lazy fetch + native `DecompressionStream('gzip')`,18,300 designs cache module-scope),篩中後在 `(L2|L3|L4|L5)` key 上重算 `sec_median` + design count,把 Bible actuals 換成「符合 filter 的 designs 在這個 step 觀察到的中位數」。任何 filter 可省略;全空 fallback `filterBibleByBrand` 或整體。失敗時 fallback brand-only。**消費端**:`index.html:5645` 取代舊 `filterBibleByBrand`-only 呼叫。
>    - **canonical_aliases.json 擴張到 23 brand 代碼 / 28 alias entries**:加進 16 個新 client / 微調 2 個(`DICKS SPORTING GOODS → DKS`(原 `DICKS`)、`GAP OUTLET → GAP`(原 `GO`))。新加 BY / HLF / WMT / QCE / HLA / JF / SAN / DST / ZAR / ASICS / NET / LEV / CATO / SMC,對齊 m7 24 brand + 平台預備擴張。`data/runtime/brands.json` 24 brand 為實際在 entries.jsonl 出現過的(其他 alias 是預備)。

> **2026-05-09 快照**(consolidated 從 2026-05-07 重組 + 2026-05-08 ~ 09 各 PR):
>
> 1. **Phase 2 derive views(View A + B 接線)** — View A (`derive_view_recipes_master.py`,Step 4a 剝 `_m7_*` 內部欄)/ View B (`derive_bible_actuals.py --all --in-place`,Step 4b 升級 `l2_l3_ie/<L1>.json` 38 檔為 dict schema + 掛 m7 `actuals`)。**View C designs_index per-EIDH 在 2026-05-09 retired** — 確認前端無 UI 消費,刪 derive script + workflow Step 4c + 3,900 個 dead 產物。spec 見 `docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md`。
>
> 2. **Bible 升級 20260507**:`data/source/五階層展開項目_20260507.xlsx` 35.7 MB(2.3x prior),sheet schema 改成「語系資料 + 全部五階層」雙 sheet,新增 `機種 / 尺寸 / 圖片名字 / *_Sort` 欄。**xlsx 不再進 repo**(>25 MB GitHub web 上限),改寫 SOP `data/source/BIBLE_UPGRADE.md`。維護者本機跑 `scripts/core/build_bible_skeleton.py` build raw,Step 4b 升 dict + 掛 actuals。
>
> 3. **m7 第 7 個 source**:`data/ingest/m7/{entries.jsonl(5,076 行,聚合,餵 cascade), designs.jsonl.gz(18,300 件 EIDH 含 5-level 工段 + canonical block,餵 View B/C derive)}`。`build_recipes_master.py` 加 `build_from_m7_pullon()`。
>
> 4. **canonical block + alias normalizer**(designs.jsonl.gz 每筆 design):8 canonical 欄位(客戶/報價款號/Program/Subgroup/W/K/Item/Season/PRODUCT_CATEGORY)各做 multi-source consensus(M7 列管 priority 3 / PDF priority 2 / 推論 priority 1),M7 兜底所以 `canonical.<field>.value` 永遠 100% 不掉拍;`confidence` "high"/"medium"/"low" 標 audit 強度;`sources` 留 audit trail。Alias 規則放 `data/source/canonical_aliases.json` 手維護。**Consumer**:`build_recipes_master.py` 讀 aggregated `entries.jsonl`;Phase 2 View B + C 直接吃 `designs.jsonl.gz` 含 canonical block。
>
> 5. **bucket_taxonomy 統一到 `data/runtime/`**(PR #312):過去兩份(root + runtime)並存,合併成一份含 **28 v4 4-dim**(`<GENDER>_<DEPT>_<GT>_<IT>` UPPERCASE,scalar 值)+ **59 legacy 3-dim**(`<GENDER>_<DEPT>_<GT>` UPPERCASE,list 值,兜底 pre-v4 facts/consensus)+ `legacy_note`。`build_recipes_master.py:72` `BUCKET_TAX_PATH` 指 `data/runtime/`(不再讀 root)。schema 細節見 `MK_METADATA.md`。
>
> 6. **CI Pre-Step 3 schema gate**(PR #313):`scripts/core/validate_buckets.py` 已重寫支援 v4 + legacy 兩段檢查(原 v3 期望 lowercase 但 v4 是 UPPERCASE),接進 `rebuild_master.yml` 跑在 Step 3 build 前 < 1s 早期 catch drift。失敗模式涵蓋:UPPERCASE 違反 / 必填欄空 / 案例衝突 / 3-dim/4-dim prefix collision warn。

> **2026-05-07 結構大調整**:把過去散在 root 的 14 份 .md / 2 份 .xlsx 集中,把 `data/`
> 拆 runtime/ingest/source/legacy 四層,scripts/ 拆 core/lib,徹底退役 `pom_analysis_v5.5.1/`,
> `General Model_Path2_Construction Suggestion/` 改名 `path2_universal/`。
> 詳細搬遷清單見 `git log --oneline pre-restructure-2026-05-07..HEAD`。

> **Metadata schema canonical doc**:每個資料 source(Bible / m7 / ISO dictionary 等)的欄位語意、來源、provenance 走 [`MK_METADATA.md`](./MK_METADATA.md)(2026-05-08 v1.0)為準。本文件 Part A 只記「資料夾分工」,不記欄位細節,避免兩處 schema 描述 diverge。

把每個資料夾當成放特定文件的櫃子,就像打版室分「上衣版」「下身版」「配件版」,不會亂放。

| 資料夾 | 放什麼(類比成衣流程) | 舉例 | 不要放什麼 |
|--------|----------------------|------|------------|
| `data/runtime/` | **線上系統 runtime 讀的成品 JSON**(2026-05-14 起 **15 個 .json**,從 18 縮 — `gender_gt_pom_rules` / `client_rules` / `design_classification_v5` 搬到 `pom_rules/_derive/` 因為前端 / api 不讀)。前端 `fetch('./data/runtime/...')`、API `analyze.js` 啟動時讀 | `l1_standard_38.json`、`l2_visual_guide.json`、`l2_decision_trees.json`、`recipes_master.json`、`iso_dictionary.json`、`pom_dictionary.json`、`grading_patterns.json`、`bucket_taxonomy.json`(28 v4 + 59 legacy)、`construction_bridge_v6.json`、`brands.json`(2026-05-11 加,前端 Brand 下拉動態 source)、`code_manifest.json`(2026-05-13 加,index.html「管理 ▸ Code 瀏覽」modal 的檔案清單,由 `scripts/core/build_code_manifest.py` 產生,**不在 CI workflow 內,要手跑**)、`all_designs_gt_it_classification.json`(CI Step 2 vlm_pipeline/extract_unified 的 GT backfill fallback,不被前端 fetch)、`l1_iso_recommendations_v1.json`、`l1_part_presence_v1.json`、`bodytype_variance.json` | 原始 xlsx;靜態文件;ingest 中繼檔;Pipeline B 內部產物(放 `pom_rules/_derive/`);**`designs_index/`** 已退役(2026-05-09) |
| `data/source/` | **手維護 / 上傳的原始底稿**(被 `scripts/core/build_*` 讀來生 runtime JSON) | `L2_代號中文對照表.xlsx`(L1/L2 代號對照,14 KB)、`BIBLE_UPGRADE.md`(SOP)、`M7_PULLON_DATA_SCHEMA.md`(m7 source schema)、**`canonical_aliases.json`**(2026-05-08 加,8 canonical 欄位的 alias normalize 規則,M7_Pipeline `consolidate_canonical.py` 讀;repo 暫存當 source-of-truth 規則表) | runtime 讀的檔;說明文件;**`五階層展開項目_*.xlsx` 不再進 repo**(2026-05-08 起,xlsx 留聚陽端,38 個 derive JSONs 進 repo) |
| `data/ingest/` | **Pipeline staging**(CI / 外部協作上傳處)。`build_recipes_master.py` 的 `data/ingest/*/facts.jsonl` glob 會掃 | `data/ingest/uploads/`(PDF/PPTX 上傳處)、`data/ingest/{unified,vlm,pdf,metadata}/`、`data/ingest/{consensus_rules,ocr_v1,consensus_v1}/`、**`data/ingest/m7/`(2026-05-12 從 `m7_pullon/` rename;聚陽端 PullOn pipeline 推進來,5,076 entries / 32 MB designs.jsonl.gz / 332 MB uncompressed / 18,300 designs)** | runtime 讀的成品(放 `data/runtime/`) |
| `data/legacy/` | **舊 `pom_analysis_v5.5.1/` 退役後留下的 fallback**(只給 `vlm_pipeline.py` / `extract_unified.py` 在 runtime 找不到時用) | `all_designs_gt_it_classification.json`、`pom_dictionary.json` | 任何新檔(此資料夾只縮不增) |
| `pom_rules/` | **自動產生的 POM 規則庫**。**137 個 bucket**(2026-05-13 v8;v6 起 bucket key 改用 M7 manifest Item 原值 `<Dept>_<MK_Item>\|<Gender>`,v7 gender+fabric 也走 M7 列管,v8 Maternity 保留)。139 檔 = 137 bucket + `_index.json` + `pom_names.json`。跨 34 brand codes(GAP / ONY / ATHLETA / BRFS / CALIA / DSG / KOH / DKS / ANF / HLF / VRST / UA / BY / QCE 等)。**`_derive/` 子目錄**(2026-05-14 加):放 Pipeline B 額外產的 3 個分類表 `client_rules.json` / `design_classification_v5.json` / `gender_gt_pom_rules.json`(從 `data/runtime/` 退役搬入,前端 / api 不讀,只 Pipeline B 自己用)| `pom_rules/*.json`(由 `scripts/core/reclassify_and_rebuild.py` 產出,外部 BASE 跑 + PR push;`validate_pom_rules.yml` workflow 校驗) | 手寫規則;說明文件 |
| `M7_Pipeline/` | **聚陽端 PullOn pipeline v11**(2026-05-13 commit `17b5629` import,scripts + docs only,no PDF uploads)。原本只在聚陽 Windows 端跑,本次拷一份進 repo 做 audit / handover 用 | `PIPELINE.md` / `PDF_PIPELINE.md`(v11 5 brand POM rescue + audit_v6 honest 3-bucket)/ `PPTX_PIPELINE.md` / `PIPELINE_GLOSSARY.md` / `construction-page-rules.md` / `scripts/`(109 py + 9 ps1)/ `data/`(canonical_aliases / client_canonical_mapping / iso_dictionary / zone_glossary 等) | raw PDF 檔(>25 MB / IP 敏感);線上 runtime 讀的檔 |
| `l2_l3_ie/` | **Bible 五階層展開** — 38 個 L1 部位,每部位 L1→L2→L3→L4→L5 工段樹。**Phase 2 dict schema(2026-05-08 commit f9faa8b 升級完成)**:每個 L5 step 是 dict `{l5, ie_standard:{sec,grade,primary,machine}, actuals?}`,`actuals` 含 m7 觀察值(`n_designs / sec_median / by_brand / machine_top`,option B trim 後)。`_metadata.schema = "phase2"` 標記。Bible **結構** 由 IE xlsx 決定(brand-agnostic),**L1-L5 樹不被 per-design 改**;Bible 38 檔現是 CI 自動產 — `derive_bible_actuals.py --all --in-place` 在 `rebuild_master.yml` Step 4b 跑,讀 xlsx-derived raw + `data/ingest/m7/designs.jsonl.gz` 後寫回。**`new_part_*` / `new_shape_design_*` / `new_method_describe_*` / `(NEW)*` placeholder 在 derive 層全 drop 不進 Bible**(IE 治理任務,聚陽端 SSRS 處理) | 按 L1 代號分檔的 JSON,38 檔 + `_index.json` | 其他層級的規則;**手改(CI 會蓋掉)**;brand 欄位嵌進樹結構(brand 走 actuals.by_brand);`new_*` placeholder |
| `l2_l3_ie_by_client/` | ~~RETIRED 2026-05-08(Phase 2.5b)~~ — git rm 完成,功能由 `l2_l3_ie/<L1>.json` 升級後 schema 的 `actuals.by_brand` + frontend 的 `filterBibleByBrand()` / `filterBibleByCategory()` helper(2026-05-11 加 6 維,runtime 反查 designs.jsonl.gz)取代 | — | — |
| `recipes/` | **PATH2 做工配方**(根目錄 72 檔)。是 `star_schema/scripts/build_recipes_master.py` 活檔的輸入,不是遺留 | `recipe_<GENDER>_<DEPT>_<GT>_<IT>.json`(72 檔)+ `_index.json` | 一次性實驗檔(放 Notion / Drive) |
| `path2_universal/` | **通用模型(不分客戶/品牌)的做工推薦資料源**。ISO 工藝代號查表、knit/woven 做工紀錄、PATH2 pipeline 文件。前身為 `General Model_Path2_Construction Suggestion/`(2026-05-07 改名) | `iso_lookup_factory_v4.3.json`、`iso_lookup_factory_v4.json`、`PATH2_通用模型_做工推薦Pipeline.md` | 前端 runtime fetch 的檔(那該放 `data/runtime/`) |
| `scripts/core/` | **資料產線腳本**(repo 內部執行的 build / rebuild / extract / search) | `build_l2_visual_guide.py`、`build_bible_skeleton.py`、`build_brands.py`(2026-05-11 加,從 m7 entries.jsonl 聚合產 runtime/brands.json)、`build_code_manifest.py`(2026-05-13 加,掃 curated 目錄產 runtime/code_manifest.json,給 index.html Code 瀏覽 modal)、`run_extract_new.py`、`reclassify_and_rebuild.py`、`enforce_tier1.py` | 共用函式庫(放 `scripts/lib/`);一次性 ad-hoc 腳本 |
| `scripts/lib/` | **共用函式庫**(被 `scripts/core/` 的腳本 import,不是 entry point) | `extract_techpack.py`(PDF parser,被 `run_extract_new.py` / `run_extract_2025_seasonal.py` import) | 直接執行的腳本 |
| `tests/` | **CI smoke test**(2026-05-14 加)。pytest 在 `rebuild_master.yml` Pre-Step 3 + `validate_pom_rules.yml` 都跑(~1s),catch schema drift `validate_buckets.py` 看不到的(`_index.json` parts count、`l2_l3_ie/_index` 38 parts、`brands.json` shape、`recipes/_index` vs disk file 一致性等) | `test_schema.py`(11 個 invariant)、`__init__.py` | 業務邏輯 unit test(scope 限 schema invariant);跨多檔的整合測試 |
| `star_schema/scripts/` | **CI 觸發的 ingest pipeline**(GitHub Actions `rebuild_master.yml` 直接呼叫,**6 支** + 1 支 derive 在 `scripts/core/`) | Step 1 `extract_raw_text.py`、Step 2b `vlm_pipeline.py`、Step 2a `extract_unified.py`、Step 3 `build_recipes_master.py`、Step 4a `derive_view_recipes_master.py`、Step 4b `derive_bible_actuals.py`、Step 4c `scripts/core/build_brands.py`(2026-05-11 加;原 designs_index per-EIDH derive 在 2026-05-09 retired)| 內部產線腳本(放 `scripts/core/`) |
| `api/` | **線上系統後端 endpoint**(Vercel functions) | `analyze.js`(Claude Vision)、`push-pom-dict.js`、`ingest_token.js` | 靜態資料 |
| `docs/spec/` | **跨模組共用規格文件**(被 code 或 LLM prompt 引用) | `L1_部位定義_Sketch視覺指引.md`、`L2_VLM_Decision_Tree_Prompts_v2.md`、`L2_Visual_Differentiation_FullAnalysis_修正版.md`、`techpack-translation-style-guide.md`(api/analyze.js 啟動時 inject)、`pom_rules_v55_classification_logic.md`、`網站架構圖.md` | 純人類操作 SOP(放 `docs/sop/`);子系統內部文件 |
| `docs/sop/` | **純人類操作流程**(沒有 code 引用) | `pom_rules_pipeline_guide_v2.md` | 規格文件(放 `docs/spec/`) |
| repo 根目錄 `.md` | **入口兩件套**(專案最頂層的 README / CLAUDE) | `README.md`、`CLAUDE.md` | 規格文件(放 `docs/spec/`);SOP(放 `docs/sop/`) |

### 新資料進來時,該放哪?

```
這份新檔是什麼?
│
├── 線上系統會直接讀取嗎?(前端 fetch / api/ 讀)
│       Yes → data/runtime/
│
├── 是手維護的原始底稿(xlsx / source PDF)?
│       Yes → data/source/
│
├── 是 pipeline 中繼檔 / 上傳區?
│       Yes → data/ingest/<subsystem>/
│
├── 是 POM 規則(bucket)?
│       Yes → pom_rules/(由 script 自動寫入,不要手動)
│
├── 是通用模型(Path 2)的 ISO / knit / woven 資料?
│       Yes → path2_universal/
│
├── 是 construction recipe / pattern(做工配方)?
│       ├── 由 PATH2 pipeline 產生  → recipes/（根目錄 72 檔,`build_recipes_master.py` 實際會吃)
│       └── 臨時上傳的一次性檔       → 不要進 repo,放 Notion / Drive
│
├── 是跨模組都要讀的規格文件?
│       Yes → docs/spec/
│
├── 是純人類操作 SOP(沒有 code 引用)?
│       Yes → docs/sop/
│
├── 是新的產線腳本?
│       ├── entry point          → scripts/core/
│       └── 共用函式庫(被 import)→ scripts/lib/
│
└── 判斷不出來?
        先在 PR 裡問,不要直接 merge。
```

> ⚠ **重要**:`recipes/`(根目錄 72 檔)是 `star_schema/scripts/build_recipes_master.py` 實際讀的路徑,
> 是活檔不是遺留。PATH2 規劃階段曾用 `construction_recipes/` 這個名字,已棄用統一回 `recipes/`。

### 版本化命名規則

服裝業本就有 v1 v2 v3 版型並存,資料檔也一樣:

- **主用版本** 檔名結尾加 `_v{N}`(例:`iso_lookup_factory_v4.3.json`)。
  README 那張「ISO 查表版本演進」表必須同步改標籤(**primary / fallback / deprecated**),
  就像版型室版型卡會註明「現用版 / 備用版 / 已淘汰」。
- **日期戳版本**(如 `full_analysis_20260420.json`)只作一次性 snapshot,不是線上主用。
- 有新版時 **舊版先不刪**,只在 README 改標 `fallback` 或 `deprecated`,下輪清理一起處理。
- 同概念 v1 跟 v2 同時在,README 必須註明「為什麼 v1 還留著」(外部還在用 / v2 仍試用期 / ...)。

### 什麼時候一份檔才算「真的沒人用」可以丟?

必須 **同時** 滿足下列 5 條(少一條就不能丟):

1. 全 repo 搜尋檔名,除了自己以外沒人提到
2. 搜「檔名去掉副檔名」(抓動態字串拼接引用)也沒人提到
3. README、CLAUDE.md、任何其他 `.md` 都沒寫過這個名字(連說明性段落都沒)
4. `git log` 最後一次改動距今 > 30 天(本週剛建的不算孤兒,可能還在試用)
5. `scripts/` 沒有腳本用「CWD 相對路徑」讀它(如 `open('xxx.md')`,普通 grep 抓不全)

---

## Part B — 舊檔清理 SOP(強制 grep gate)

下次真要丟舊檔時,照下面流程跑,**跳任何一步都不行**:

```bash
# Step 1 — 列候選
CANDIDATE="recipes/"   # 要清的檔或資料夾

# Step 2 — 強制檢查 1:搜完整檔名,若有人引用就停
assert_orphan() {
  local pat="$1"
  local hits=$(rg -l --hidden --glob '!.git/' "$pat" | grep -v "^$pat$" || true)
  if [ -n "$hits" ]; then
    echo "❌ 候選 $pat 仍被下列檔案引用,不可刪:"
    echo "$hits"
    return 1
  fi
  echo "✅ $pat 無引用"
}
assert_orphan "$CANDIDATE" || exit 1

# Step 3 — 強制檢查 2:搜「去副檔名 basename」(抓動態字串拼接)
BASENAME_NOEXT=$(basename "$CANDIDATE" | sed 's/\.[^.]*$//')
assert_orphan "$BASENAME_NOEXT" || exit 1

# Step 4 — 人工翻 git log 最近 5 次 commit,確認不是這週剛建的實驗檔
git log --follow --oneline -- "$CANDIDATE" | head -5

# Step 5 — 若檔名/說明有中文別名,另外手動搜一次
#   例:L2_Confusion_Pairs_Matrix.md → 另搜「混淆對」「混淆矩陣」
rg -l --hidden --glob '!.git/' "混淆對|混淆矩陣"  # 結果需是空(或只指向該檔)

# Step 6 — 全部過了才 git rm + commit
git rm -r "$CANDIDATE"
git commit -m "chore: 移除孤兒 $CANDIDATE (已通過 grep gate 驗證)"
```

### 真實教訓 (2026-04-22)

原以為 `L2_Confusion_Pairs_Matrix.md` 沒人用,**實際上** `L2_VLM_Decision_Tree_Prompts_v2.md`
第 4、7 行寫著:

> **來源**:L2_Visual_Differentiation_FullAnalysis_修正版.md(282 個 image-based 視覺描述)+
> **L2_Confusion_Pairs_Matrix.md(49 hard negative pairs)**
>
> **姊妹文件**:... **L2_Confusion_Pairs_Matrix.md(49 混淆對)**

這不是程式碼 import,是說明文字的自然語言引用。一次 grep 抓得到,但過去的檢查可能
是在該檔還沒建立時跑的,時間差導致漏網。

**教訓**:
- 檢查要跑 **多輪**:完整檔名 + 去副檔名 basename + 中文別名(混淆對/混淆矩陣/...)
- Step 3 + Step 5 就是為此設計的,不可跳過
- 「一週前跑過 grep = 0 引用」不代表「今天 grep 還是 0」,每次清理當天重跑

---

## 已知的下輪清理候選(2026-04-22 盤點 + 2026-05-07 重組後狀態 + 2026-05-14 code review 清理)

下次跑 Part B SOP 時,可以考慮審這幾項:

| 候選 | 現況 | SOP 預期結果 |
|------|------|--------------|
| ~~`recipes/`~~ | 2026-04-23 確認是活檔:`star_schema/scripts/build_recipes_master.py` 每次 CI 都會掃 72 檔餵進 recipes_master.json | **不是候選** |
| `path2_universal/iso_lookup_factory_v4.json` vs `v4.3.json` | v4 仍作 fallback 被 `index.html`、`build_recipes_master.py` 引用,非孤兒;只是舊版 | 仍會過 gate = 不可丟,維持 fallback |
| `data/legacy/{all_designs_gt_it_classification,pom_dictionary}.json` | 2026-05-07 從 `pom_analysis_v5.5.1/data/` 搬過來,被 `vlm_pipeline.py` / `extract_unified.py` 當 fallback | 暫時 keep;下輪確認 runtime 副本是否完全取代後可清 |
| ~~`l2_l3_ie/l2_l3_ie/` + `l2_l3_ie/l2_l3_ie/l2_l3_ie/`~~ | 2026-05-14 跑 Part B gate 後 `git rm -r` 完成 — Bible 從 196 MB → 138 MB(回收 87 MB nested 死重 from commit `efef83e`/`5f1455a` rename detection bug)| **已清** |
| ~~`data/ingest/m7_pullon/`~~ | 2026-05-14 跑 gate 後 `git rm -r` — m7 rename 後 `M7_PATH`、`M7_DESIGNS`、workflow trigger 都已指 `m7/`,舊目錄無 `facts.jsonl` 不會被 glob 抓到。回收 13 MB | **已清** |
| ~~`M7_Pipeline/_test_*.py` 5 隻~~ | 2026-05-14 跑 gate 後 `git rm` — 全是聚陽 Windows 端 ad-hoc debug script,hardcode `tp_samples_v2/` 本地路徑(repo 無此目錄)| **已清** |

**不會是清理候選的(避免誤判)**:

- ~~`L2_Confusion_Pairs_Matrix.md`~~ — 2026-04-23 已合併入 `docs/spec/L2_VLM_Decision_Tree_Prompts_v2.md` 末尾(§ 混淆對照表)
- ~~`L1_部位定義_Sketch視覺指引.md` 雙份~~ — 2026-05-07 已刪 PATH2 那份,只留 `docs/spec/L1_部位定義_Sketch視覺指引.md`
- ~~`scripts/` 裡路徑寫死 `/sessions/` 的腳本~~ — 2026-04-24 已改用 `--base-dir` / `$POM_PIPELINE_BASE`,可在外部環境跑(見 `scripts/core/_pipeline_base.py`)
- ~~`pom_analysis_v5.5.1/`~~ — 2026-05-07 已徹底退役:`extract_techpack.py` 抽到 `scripts/lib/`,其餘 5 個 MD5 相同 JSON、6 支 fork 後沒人 import 的舊版 .py、`run_extract.py` 孤兒、舊版 pipeline guide MD 全清
- `data/ingest/consensus_rules/facts.jsonl`(275 筆)、`data/ingest/ocr_v1/facts.jsonl`(1202 筆) — **一度被誤判為孤兒**,但 `build_recipes_master.py:629` 的 `data/ingest/*/facts.jsonl` glob 會吃它們,2026-04-24 實測刪除會讓 recipes_master 掉 249 entries(1414 → 1165)。**不可刪**
- ~~`l2_l3_ie_by_client/` 27 檔~~ — **2026-05-08 已退役(Phase 2.5b)**:同日早上 gate 攔下後,Phase 2.1-2.5 一連串 PR 把退役三前提都完成:① `l2_l3_ie/` 38 檔升級成 Phase 2 dict schema(commit f9faa8b);② frontend `filterBibleByBrand()` helper 直接從 actuals.by_brand 過濾(取代 derive_view_by_client.py 的計畫);③ `index.html:5426` 的 fetch 已拔掉。`build_recipes_master.py` 的 `_m7_by_client` 欄位也順便清掉
- `data/ingest/pdf/construction_manifest.jsonl`(0 bytes 空檔) — **2026-05-08 gate 攔下**:`star_schema/scripts/extract_raw_text.py:572` 是 append 寫入目標,workflow `rebuild_master.yml:54` 也引用,是 active output target 只是還沒資料。**不可刪**
- `scripts/core/{search_recipes,build_recipe_embeddings,eval_recipe_retrieval}.py` 三隻 — **2026-05-08 gate 攔下**:雖然不在 CI / workflow 內被呼叫,但 `data/ingest/recipe_index/index.json` 是 623 KB 真實 build 產物,代表是有人 build 過的離線評估工具。屬於手動 CLI(類似 eval 性質),**不是 dead code**

### 2026-05-07 重組:外部 BASE 與 repo 內部命名解耦

- `scripts/core/{rebuild_grading_3d,reclassify_and_rebuild,...}.py` 內仍有 `pom_analysis_v5.5.1/data/` 字串,但這是 **外部使用者 BASE 目錄結構**(`$BASE/pom_analysis_v5.5.1/data/`),**不是這個 repo 的資料夾**。重組時刻意保留以維持外部 BASE 用戶的相容性。下輪可考慮把 BASE 結構也一併重新命名(屬於外部契約變更,需另案通知)。

### 真實教訓 (2026-04-24)

原以為 `data/ingest/consensus_rules/` + `ocr_v1/` 沒人用(全文 grep 不到 literal 字串),code review agent 也回報「零引用」。**實際上** `build_recipes_master.py` 用 glob pattern `data/ingest/*/facts.jsonl` 讀,不需要 hardcode 目錄名,因此 grep 抓不到。

教訓(加到 Part B SOP 的 Step 5 後面):

- **Step 6 — 檢查 glob / wildcard 讀取**:看消費端有沒有用 `glob("*/...")`、`os.listdir()`、`Path.iterdir()` 這類動態掃描。candidate 目錄若位於 glob 的掃描範圍內,一定是活檔,grep literal 字串永遠抓不到。
- 實務上:對 `data/ingest/` 下任何新資料夾,都要先搜 `grep "ingest.*glob\|ingest.*iterdir\|ingest/\*"` 在 `*.py` / `*.js` 裡;不是 literal 比對。

### 真實教訓 (2026-05-07)

中度資料夾重組時碰到兩個容易踩雷的點,記錄下來給下次重組參考:

- **REPO_ROOT 深度**:把 `scripts/X.py` 搬到 `scripts/core/X.py` 後,所有 `Path(__file__).resolve().parent.parent` 計算的「repo root」都變成 `scripts/`(少一層)。grep `Path\(__file__\).*parent\.parent` 抓出所有需要改 `.parent.parent.parent` 的位置。
- **中文檔名 git mv**:含「五階層展開項目」、「部位定義」這類中文檔名,先 `git config core.quotepath false`,否則 `git status` 會顯示 `\xxx\xxx` 八進位編碼很難讀。macOS 還要設 `core.precomposeunicode true` 避免 NFD/NFC 不一致。
- **rename 配對誤判**:兩份 MD5 相同的檔案(`L1_部位定義_Sketch視覺指引.md` root + PATH2 兩份),git 的 rename detection 會把刪 + 加配對成 rename,可能把錯的那份標 D。功能性無影響(內容仍在),但 `git log --follow` history chain 會斷在被誤標的那一邊。可接受。
- **外部 BASE 路徑名 ≠ repo 路徑名**:`scripts/core/rebuild_grading_3d.py` 等腳本用 `BASE` 環境變數指向外部目錄,內部結構 `BASE/pom_analysis_v5.5.1/data/` 是外部使用者契約,不是這個 repo 的路徑。重組 repo 時這類字串故意保留,別誤改。

### 真實教訓 (2026-05-08)

第二輪 codebase audit(掃 dup / dead code / stale doc)時,gate 又攔下三個誤判,記下來避免下次重蹈:

- **「DEPRECATED 標籤 ≠ 可刪」**:`l2_l3_ie_by_client/` 在 Part A 表上標 DEPRECATED,但 `index.html:5426` 仍 fetch、`build_recipes_master.py:693` 仍寫 `_m7_by_client`。退役只是「不要新增」,要 git rm 必須先把所有讀寫端切走。檢查 candidate 標 DEPRECATED 時務必 grep 線上前端 + 所有 producer 端,不可只看 Part A 文字。
- **「空檔 ≠ 死檔」**:`data/ingest/pdf/construction_manifest.jsonl` 是 0 bytes,看似 placeholder,實際是 `extract_raw_text.py:572` 的 append target。空檔可能是「pipeline 還沒跑出資料」,不是「沒人要寫」。檢查空檔要 grep producer 端,不只看消費端。
- **「不在 CI 內 ≠ dead code」**:`scripts/core/search_recipes.py` / `build_recipe_embeddings.py` / `eval_recipe_retrieval.py` 三隻沒在 workflow 內被呼叫,但 `data/ingest/recipe_index/index.json`(623 KB)是它們 build 出來的真實產物,代表有人手動跑過。離線評估 / 研究工具不會進 CI,但仍是活工具。
- **「文件宣稱 ≠ 實況」**:CLAUDE.md L43 寫 Phase 2 schema 升級已完成,實測 `l2_l3_ie/AE.json` 仍是 5-elem list 的 Phase 1 格式。**文件描述要跟著事實改,不能寫成「目標狀態」當「現況」**(已修正,Part A 改回「Phase 1 list,Phase 2 規劃中」)。

教訓加進 Part B SOP:Step 6 (glob check) 之後加 **Step 7 — frontend fetch + producer write check**,grep `fetch.*<candidate>`、`open.*<candidate>.*'a'`、`append`、`>>` 對候選的引用。

---

## Part C — 審計 / Code Review Checklist

給下次跑 audit 的人(AI 或工程師)的必讀清單。每條都是吃過虧來的,不是紙上談兵。

### C1. `index.html` 是 7000+ 行 inline React — 深度掃它,不要只靠 agent 摘要

2026-04-23 第一輪審計把 `index.html` 丟給 Explore agent 掃 "完成度",回報結論是「生產可用,零 stub」— 漏掉了一個真 bug:

> `ResultsUploadModal` 用 `atob(d.content)` decode 含中文的 `facts.jsonl`,>0x7F byte 被截斷,合併後寫壞線上檔。code review 才抓到(commit `c78b3f9`)。

Agent 掃「功能完成度」會看到所有 Modal 都在,不會展開字串處理細節。靜態單檔 SPA 的這些陷阱在 agent 摘要裡隱形:

**掃 `index.html` 時必須人工 grep 的陷阱清單**:

| 陷阱 | grep 指令 | 風險 |
|------|----------|------|
| `atob` / `btoa` **跟 UTF-8 資料** 同用 | `grep -n 'atob\|btoa' index.html`,每個非 helper 位置看上下文:是處理 binary 檔(✅)還是文字(⚠ 要走 `TextEncoder`) | 含中文的 markdown / jsonl base64 來回會壞字元 |
| `String.fromCharCode` 無 chunk | `grep -n 'String.fromCharCode' index.html`,大檔 spread 會爆 stack | 大 PDF / jsonl 上傳時 stack overflow |
| `localStorage` 讀無 try/catch | `grep -n 'localStorage.getItem\|localStorage.setItem' index.html` | 隱私瀏覽 / quota 超出時 throw |
| `JSON.parse(fetch)` 無 catch | `grep -n 'JSON.parse' index.html` | 後端錯誤回 HTML,SPA 整個白屏 |
| 硬編 API endpoint 路徑 | `grep -n "'/api/" index.html` | endpoint 改名時漏改 |

### C2. 靜態/衍生資料檔的 skew 檢查

每次 audit 要同時驗 **source → build → derived** 三份檔一致:

- `data/runtime/bucket_taxonomy.json`(source)→ `build_recipes_master.py`(code)→ `data/runtime/recipes_master.json`(derived)
- source / code 有任一改動,derived 可能是 **stale commit** 而不是正確結果
- 2026-04-23 發現 `recipes_master.json` 比 source 落後 5 個 commits,理由是 Actions workflow 只在 `data/ingest/uploads/**` push 時觸發,沒人上傳 techpack 時 derived 檔就永遠停在舊版
- **SOP**:audit 時本地跑一次 `python3 star_schema/scripts/build_recipes_master.py`,`git diff data/runtime/recipes_master.json` 應為空(或只有 timestamp 行)。有實質 diff = source 跟 derived 已 skew,要麼 commit 新產物,要麼查清楚為何不一致

### C3. CLI flag 宣稱 vs 實作

文件/workflow 宣稱某個 flag(如 `--strict`)有行為,**必須實際進程式碼確認**。2026-04-23 發現:

- workflow `.github/workflows/rebuild_master.yml:87` 傳 `--strict`
- README / 網站架構圖都寫「違規 exit 1 擋住 commit」
- 但 `build_recipes_master.py` 的 `main()` 完全沒 argparse,flag 被 Python 吞掉
- **gate 是假的** — 任何 schema 違規都靜默成功,直到 commit `7bda79f` 才修

**SOP**:audit 時對每個 workflow step 的命令列,grep 被呼叫 script 的 argparse,對比 README 描述。缺一邊就是文件債。

### C4. 重組後路徑驗證(2026-05-07 加入)

每次大規模 mv 後,跑下列 grep 確認沒有殘留舊路徑:

```bash
# 應為 0 行(忽略 .git 與衍生 derived JSON)
grep -rn "General Model_Path2" --include='*.py' --include='*.js' --include='*.html' --include='*.yml' .
grep -rn "pom_analysis_v5\.5\.1" --include='*.py' --include='*.js' --include='*.html' . | grep -v 'rebuild_grading_3d\|reclassify_and_rebuild\|index\.html.*\$BASE'
grep -rnE "['\"\`]data/(l1_standard_38|l2_visual_guide|l2_decision_trees|recipes_master|construction_bridge_v6|iso_dictionary|pom_dictionary|grading_patterns|bucket_taxonomy|design_classification_v5|client_rules|gender_gt_pom_rules|bodytype_variance|l1_iso_recommendations_v1|l1_part_presence_v1)\.json" --include='*.py' --include='*.js' --include='*.html' . | grep -v 'data/runtime\|data/legacy\|data/source\|data/ingest'

# 也跑這 4 個冒煙 build,看 git diff 是否只剩 timestamp:
python3 scripts/core/build_l2_visual_guide.py
python3 scripts/core/build_l2_decision_trees.py
python3 scripts/core/build_bible_skeleton.py --dry-run
python3 star_schema/scripts/build_recipes_master.py
```

衍生 JSON(`data/runtime/recipes_master.json` 等)裡的 `source_versions` 字串會殘留舊路徑,但 CI 下次跑會自動更新,**不算未修**。
