# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

> 想直接看全貌 Mermaid 圖(4 張:高階流程 / 前端模式分流 / 資料依賴 / Ingest Pipeline)+ 資料夾對照表 + 架構債清單 + 權威手冊登記表:[`docs/spec/網站架構圖.md`](./docs/spec/網站架構圖.md)
>
> 變動 changelog 已搬到 [`CLAUDE.md` Part A 快照區](./CLAUDE.md#part-a--資料夾分工表)。**2026-05-14 大變動**:`data/ingest/m7_pullon/` → `m7/` rename / M7_Pipeline v11 import / POM rules v6→v8(81 → 137 buckets,bucket key 改用 M7 manifest Item)/ `validate_pom_rules.yml` workflow 拆出 / Code 瀏覽 modal — 詳見 CLAUDE.md Part A。

## 目錄

- [目的](#目的) — 解決什麼問題、給誰用
- [整體流程一張圖](#整體流程一張圖) — 三個資料來源 → 三條產線 → runtime → 前端
- [資料 schema 與 canonical 文件](#資料-schema-與-canonical-文件) — MK Metadata / Phase 2 / 架構文件入口
- [兩種模式](#兩種模式) — 聚陽模型 vs 通用模型
- [架構](#架構) — 資料夾分工 + ISO 查表版本
- [兩組獨立的資料 pipeline](#兩組獨立的資料-pipeline) — 線下規則產線 vs 線上 ingest
- [Admin 通道](#admin-通道) — 5 個入口 + Pipeline 外送包
- [本機預覽](#本機預覽) / [部署](#部署)
- [待辦 / Roadmap](#待辦--roadmap) — D / E:server-side filter API + Bible 拆檔

## 目的

StyTrix Techpack 解決成衣打版室一個老問題:**Techpack 製作**(做工、工段)跟 **Measurement Spec**(尺寸表、跳碼)兩件事,過去散在不同工具(Centric 8、Excel、PPTX)、靠人腦合併。本系統把兩者合併成單一 web UI,讓 Admin 上傳 PDF/PPTX 後:

1. **Claude Vision** 自動看圖辨識 L1 部位 + L2 細節零件(L1 100% / L2 76% AI 直接分,~24% 視覺差太細靠 hint 補)
2. **規則庫**(`pom_rules/` **137 bucket**(2026-05-13 v8)、`l2_l3_ie/` 38 L1 部位 × 五階層、`recipes/` 72 配方)算出做工建議
3. **尺寸引擎** 套 POM tier(必備/建議/選配)+ 跳碼 pattern,輸出全碼或基礎尺寸

對接兩種使用情境:

- **聚陽模型** — 內部完整流程,五階層工段 + IE 秒數 + POM 全碼
- **通用模型** — 對外簡化版,VLM 只判 L1、雙 ISO 表查做工、5 項基礎尺寸

技術選擇:**純靜態 HTML(React via CDN)+ Vercel Node Functions**,沒有 bundler、沒有 `package.json`,因此 repo 任何修改 push 到 main → Vercel 立刻部署,沒有 build 鏈條延遲。

## 整體流程一張圖

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 三個資料來源                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  (a) Bible xlsx (聚陽端,>25 MB 不進 repo)                                    │
│        └─→ 本機 scripts/core/build_bible_skeleton.py                               │
│              └─→ l2_l3_ie/*.json (38 個 L1,Phase 1 5-elem list)             │
│                                                                              │
│  (b) Admin 上傳 PDF/PPTX → data/ingest/uploads/  +  m7 push           │
│        └─→ CI Pipeline A (.github/workflows/rebuild_master.yml)              │
│              Step 1 extract_raw_text → 2b vlm_pipeline → 2a extract_unified  │
│              → 3 build_recipes_master --strict                               │
│                └─→ data/runtime/{recipes_master, iso_dictionary,             │
│                                   l1_standard_38}.json                       │
│                                                                              │
│  (c) BASE PDFs (外部,$POM_PIPELINE_BASE)                                     │
│        └─→ 本機 Pipeline B (scripts/core/)                                   │
│              run_extract_new → rebuild_profiles → reclassify_and_rebuild     │
│              → enforce_tier1 → fix_sort_order                                │
│                └─→ pom_rules/*.json (137 bucket,v8;bucket key 走 M7 Item)   │
│                    + validate_pom_rules.yml workflow schema 校驗             │
│                                                                              │
│  (d) M7_Pipeline/ v11 (聚陽 Windows 端,2026-05-13 import 進 repo)          │
│        └─→ scripts + docs only (no PDF uploads)                              │
│              109 py + 9 ps1, 11 brand parsers, audit_v6 honest 3-bucket      │
│                └─→ output 走 git push 進 data/ingest/m7/ + pom_rules/        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ data/runtime/ 成品 JSON(線上 fetch / Vercel includeFiles bundle)            │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                ┌────────────────────┴────────────────────┐
                ▼                                         ▼
       index.html (前端 fetch)                api/analyze.js (Pass 1+2)
       useAppMode → 雙模式分流                Claude Vision sonnet-4-6
                                              mode=universal 只跑 Pass 1
```

關鍵原則:**(b) (c) 兩條 pipeline 不共用程式碼**,動其中一邊不會自動影響另一邊;`data/runtime/` 是兩條產線的會合點,也是前端唯一讀取入口。

### 客戶資料怎麼進來的兩個原則

客戶 PDF/PPT 各家格式不一、欄位殘缺嚴重,所以抽取設計上有兩條鐵則:

1. **Cover page 一定有,其他聽天由命** — 每個客戶 PDF 第一頁固定有**款號 + 產品名稱**,但其他 metadata(客人 / 針平織 / gender / dept / garment / item)涵蓋率因客戶平台而異。Centric 8 ONY 結構整齊可結構化解析,其他客戶 PDF 格式各異要走 VLM 看圖路徑。所以抽取分兩軌:`scripts/lib/extract_techpack.py`(Centric 8 結構化 parser)+ `star_schema/scripts/vlm_pipeline.py`(其他客戶 PDF 整頁 216 DPI 渲染 → Claude Haiku 看圖結構化吐欄位)。
2. **對不齊 MK 也沒關係,大數法則先跑起來** — 不要因為某客戶沒給 fabric、某客戶沒給 dept 就 block 整個 pipeline。靠三招讓資料流動:① **alias normalize**(`data/source/canonical_aliases.json` 收 `Pants / Pull On Pants / Pants ( パンツ )` → `PULL ON PANTS` 等命名差異)② **subgroup 推論**(`data/client_canonical_mapping.json` 從該客戶歷史 design 投票推 ground truth,如 A&F ACTIVE 100% KNIT/98% WOMEN)③ **3-priority consensus**(M7 列管=3 / 客戶 PDF=2 / 推論=1)+ `confidence` 標 high/medium/low + `sources` 留 audit trail。M7 兜底所以 `canonical.<field>.value` 永遠 100% 不掉拍,弱信心欄位後面 audit 再回補。

## 資料 schema 與 canonical 文件

每個 source(Bible / m7 / ISO 字典 / client mapping / bucket_taxonomy)的欄位語意、provenance、推導關係,**統一以 `MK_METADATA.md` 為準**(本 README 跟 CLAUDE.md 只記資料夾分工,不重描 schema,避免 diverge)。

| 文件 | 角色 |
|---|---|
| [`MK_METADATA.md`](./MK_METADATA.md) | **Canonical schema** — 6 個元素(M7 索引 / 五階定義 / ISO 字典 / 客戶對照 / callout router / 5+1 維 canonical key)。聚陽 M7 是 single point of integration(18,731 EIDH × 42 cols),整個系統以 MK 為主 |
| [`M7_Pipeline/PIPELINE.md`](./M7_Pipeline/PIPELINE.md) | **聚陽 PullOn pipeline v11**(2026-05-13 import,scripts + docs only)。Phase A fetch → C extract(11 brand parsers)→ E build → F audit(audit_v6 honest 3-bucket,POM% 92.9%);v11 5 brand POM gap rescue: ONY/GAP/DKS/KOH/UA → 92-99%;Total POMs **365K → 591K**(+62%)。詳細:`PDF_PIPELINE.md` / `PPTX_PIPELINE.md` |
| [`docs/architecture/STYTRIX_ARCHITECTURE.md`](./docs/architecture/STYTRIX_ARCHITECTURE.md) | 完整架構 v3.0,Step 1/2/3/4 framework |
| [`docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md`](./docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md) | Phase 2 derive views 設計:master.jsonl → recipes_master(view A,輕量化)/ l2_l3_ie 升級 schema(view B,drop brand,含 actuals)。**View A + B 接線 CI**(Step 4a/4b);原規劃的 view C designs_index per-EIDH 在 2026-05-09 retired(前端無消費)|
| [`docs/architecture/PLATFORM_SYNC_PLAN.md`](./docs/architecture/PLATFORM_SYNC_PLAN.md) | 聚陽端 → platform sync plan |
| [`docs/architecture/DATA_PIPELINE_MAPPING.md`](./docs/architecture/DATA_PIPELINE_MAPPING.md) | 從聚陽端 push 到 platform CI 的完整檔案路徑對映表 |
| [`docs/spec/網站架構圖.md`](./docs/spec/網站架構圖.md) | 4 張 Mermaid 圖 + 架構債清單 + 權威手冊登記表 |
| [`CLAUDE.md`](./CLAUDE.md) | repo 使用守則(Part A 資料夾分工 / Part B 清理 SOP / Part C audit checklist) |

### m7 canonical block(2026-05-08 加)

`data/ingest/m7/designs.jsonl.gz` 每筆 design 帶 `canonical.<field>.{value, confidence, sources}`,8 canonical 欄位(客戶 / 報價款號 / Program / Subgroup / W/K / Item / Season / PRODUCT_CATEGORY)做 multi-source consensus(M7 列管 priority 3 / PDF priority 2 / 推論 priority 1),M7 兜底所以 `value` 永遠 100% 不掉拍;`confidence` "high"/"medium"/"low" 標 audit 強度,`sources` 留 audit trail。Alias 規則(單複數 / 客戶簡寫 / Season format)放 `data/source/canonical_aliases.json` 手維護(2026-05-11 擴張到 23 brand 代碼 / 28 alias entries,涵蓋 m7 24 brand + 平台預備擴張)。**Consumer**:`build_recipes_master.py` 讀 aggregated `entries.jsonl`(餵 cascade);Phase 2 View B (`derive_bible_actuals.py`) 直接吃 `designs.jsonl.gz` 含 canonical block,把每筆 design 的客戶 metadata + 5-level 工段聚合進 `l2_l3_ie/<L1>.json` 的 `actuals.by_brand`。

### 前端 Bible filter helpers(`index.html`)

前端拿 `l2_l3_ie/<L1>.json`(Phase 2 dict schema 含 `actuals.by_brand`)時,可疊兩層 filter 把 Bible 收斂到「目標客戶 / 品類組合下實際觀察到的工段」:

| Helper | 維度 | 來源 | 用途 |
|---|---|---|---|
| `filterBibleByBrand(bible, brand)` | 1 維(brand) | `actuals.by_brand[brand]` 直接讀 step 的 `sec_median` | 快速:不需 fetch designs.jsonl.gz,從 Bible 自帶 actuals 拿值 |
| `filterBibleByCategory(bible, {brand,fabric,gender,dept,gt,it})` | 6 維 | runtime 反查 `data/ingest/m7/designs.jsonl.gz`(lazy fetch,native `DecompressionStream('gzip')` 解壓,parse 後 cache 18,300 designs in module scope),按 `(L2|L3|L4|L5)` key 重算 sec_median + design count | 精細:需要某個 client × 性別 × 品類 × 紗線下的工段中位數 |

任何 filter 維度可省略;全空 fallback 整體 Bible。`filterBibleByCategory` 失敗(designs.jsonl.gz fetch 失敗)時 graceful degrade 成 `filterBibleByBrand`。兩支都回傳跟原 Bible 同 shape 的物件(`knit`/`woven` 陣列),可直接餵 `rebuildCardFromL2` 等下游消費端。實作見 `index.html:156` / `index.html:216`。

## 兩種模式

Header 右上提供「**聚陽模型** / **通用模型**」切換（選擇會記在 `localStorage.stytrix.appMode`）。

| 模式 | 作工建議 | 尺寸 | 全碼 |
|------|----------|------|------|
| **聚陽模型** (`makalot`) | 五階層：L1 部位 → L2 零件 → L3 形狀 → L4 工法 → L5 工段 + IE 秒數 | POM tier（必備 / 建議 / 選配），依 `pom_rules/<bucket>.json` | ✓ 各 size 中位數 + 公差 + 跳碼 |
| **通用模型** (`universal`) | Path 2：VLM 只判 L1，雙表查 ISO：先 `path2_universal/iso_lookup_factory_v4.3.json`(Dept × **Gender** × GT × L1，fine GT 對齊 UI 下拉選單，230 entries)再退 `path2_universal/iso_lookup_factory_v4.json`(Fabric × Dept × GT × L1_code，282 entries，提供 iso_zh/機種)；另吃 `data/runtime/recipes_master.json` 顯示 recipe 推薦 | 僅 5 項基礎大尺寸（上衣：肩/胸/下擺/袖長/身長；下身：腰/臀/前後檔/內長/褲口） | — |

通用模型後端 (`api/analyze.js`) 接 `mode=universal` 時**只跑 Pass 1（L1 偵測）**，省掉 Pass 2 的 decision-tree token。

### 推薦理論基礎 — 為什麼兩種模式 AI 辨識深度不同

兩種模式第一步**都是 AI 辨識做工圖**,但辨識深度跟後續資料源完全不同。理論基礎:**辨識能看到什麼程度,就停在那層;後面缺的部分用最堅強的產業知識(YY 五階層 18,731 EIDH 樣本)回推**。

#### 聚陽模型 — AI L1-L3,YY 五階層帶入 L4-L5

```
做工圖 → AI Pass 1+2 辨識到 L3
              L1 部位(38) → L2 零件(282) → L3 形狀(1,117)
                                                 ↓
                       YY 五階層帶入 L4 工法(~6,000)
                                  + L5 細工段(~30,000) + IE 秒
                                                 ↓
                                            推薦輸出
```

L4-L5 是工段/步驟層級(「先車縫 → 翻面 → 再壓線」這種),從圖看不出來,要先靠 L1-L3 鎖定到一個確定的「形狀」之後,從 YY 大資料反查歷史最常用的工段路徑。資料源 = `l2_l3_ie/<L1>.json` 38 個檔(從聚陽 YY 系統抓的 Bible xlsx build,有完整 IE 秒數)。

#### 通用模型 — AI L1,同款五階層大數回推

```
做工圖 → AI Pass 1 只辨識到 L1
              L1 部位(38)
                  ↓
            同款五階層大數回推
              (在同 L1 之下,跨所有 design,看
               部位 × 步驟 × 性別 × 產品類別
               最常用的做工 ISO 是什麼)
                  ↓
            L1 + ISO 推薦
```

通用模型對外沒有 IE 秒數需求,給 ISO 級別建議就夠;深入到 L3 反而過細不實用。

**做工資料源 = 客戶自己的做工資料**(從客戶 PDF/PPT 抽,**不是** v4.3 / v4 ISO 表本身 — 那只是聚陽端把客戶資料 5 source 整合後**已經做好的眾數查表**)。客戶寫做工的方式有三種,處理難度遞增:

| 客戶寫法 | 例子 | 處理難度 |
|---|---|---|
| ISO 代號 | `301 / 514 / 605` | 容易,直接對 `iso_dictionary` |
| 英文做工方式名 | `Lockstitch / Overlock / Coverstitch` | 中等,英文 → ISO mapping |
| 英文做工描述 | `1/16" topstitch using single needle` | 難,要 NLP 抽參數 |

#### PPT 的角色 — 中英對照 + 近似語映射

因為內部不懂英文的人也蠻多,所以會有一份 PPT,主要是**截圖 PDF 下來加上中文翻譯**:

```
PPT 內容 = PDF 截圖 + 中文翻譯
                       ↓
       ┌────────────────────────────────────┐
       │ 中英對照(Lockstitch ↔ 平車 301)   │
       │ 近似語映射                          │
       │   1/16" topstitch ≈ 細壓線         │
       │   Coverstitch    ≈ 雙針 / 三針     │
       └────────────────────────────────────┘
```

中文翻譯精準度更詳盡(翻譯時人腦會做一次校對,把英文做工描述對應到聚陽內部習慣的中文工法名),但**資料量非常不完整** — PPT 只翻譯了部分 PDF。所以實務上:**PDF 給廣度,PPT 給精度**;兩者搭配抽出來進 `data/ingest/{pdf,pptx}/facts.jsonl`,經 alias 正規化後合進 master。

#### 通用模式回推機制 — 為什麼大數夠厚就能填回缺漏

通用模式自己手上的做工資料(客戶 PDF + PPT)涵蓋有限,但**聚陽 YY 五階層大數夠厚** — 18,731 EIDH 工法樣本。回推邏輯:

```
AI 辨識出 L1 = "WB 腰頭"
   + metadata =(WOMEN, ACTIVE, BOTTOM, LEGGINGS, KNIT)
                                ↓
   從 YY 五階層 18,731 EIDH 篩出符合條件的所有 design
                                ↓
   看這些 design 在 L1=WB 之下用了哪些 ISO / 工法
                                ↓
                取眾數(最常用的做工)當推薦
                                ↓
   若該組合下樣本不足 → 放寬 metadata(去掉 item,只看 garment)
                                ↓
   仍不足 → 再放寬(去掉 dept) → 退到 v4.3 / v4 ISO 表
                              (本來就是 5 source 跨設計合併的眾數查表,
                               等於更大範圍的兜底眾數)
```

**換句話說,聚陽 YY 五階層是通用模式的「產業知識儲備庫」**。客戶資料殘缺沒關係,因為大數夠厚,可以把缺的部分用「同款 + 同 L1 + 同 metadata 篩選下歷史最常用的做工」填回去 — **這就是「最堅強的產業知識基礎」的具體機制**。

## 架構

純靜態 HTML + Vercel Node.js Functions，無 bundler、無 `package.json`。

```
index.html                                    ← 整個 app（React via CDN + 內聯 JS/CSS）
LOGO.png                                      ← Header logo 圖檔
api/
  ├─ analyze.js                               ← Claude Vision（claude-sonnet-4-6）：Pass 1 (L1) + Pass 2 (L2 decision tree)
  │                                             mode=universal 時只跑 Pass 1；module init 讀 data/runtime/{l2_visual_guide,l2_decision_trees,l1_standard_38}.json
  │                                             + docs/spec/techpack-translation-style-guide.md
  ├─ push-pom-dict.js                         ← Admin：POM 翻譯表寫回 data/runtime/pom_dictionary.json
  └─ ingest_token.js                          ← Admin：發 GITHUB_PAT 讓瀏覽器直連 GitHub（繞 4.5MB body 上限）
.github/workflows/
  ├─ rebuild_master.yml                       ← push 到 main 或手動 workflow_dispatch 觸發；自動重建 recipes_master 並 push 回 main
  ├─ validate_pom_rules.yml                   ← **2026-05-13 加**:push 到 `pom_rules/**` 觸發,只跑 `validate_buckets.py --strict`(schema gate <1s)。CI 沒外部 BASE 不能 regen,只校驗
  └─ build_bible_skeleton.yml                       ← workflow_dispatch only(2026-05-08+;xlsx >25 MB 不進 repo,維護者本機 build push JSON,workflow 多半不再用)
vercel.json                                   ← functions config:**2026-05-14 收緊** — includeFiles 只 bundle analyze.js 真正讀的 3 個 runtime JSON(`l2_visual_guide` / `l2_decision_trees` / `l1_standard_38`)+ `docs/spec/techpack-translation-style-guide.md`(之前是 `data/**`,bundles 91 MB 含 75 MB ingest/ 不需要的;收緊後 184 KB)
docs/
  ├─ spec/                                    ← 跨模組共用規格(被 code / LLM prompt 引用)
  │   ├─ L1_部位定義_Sketch視覺指引.md         ← VLM Pass 1 system prompt 資料來源
  │   ├─ L2_VLM_Decision_Tree_Prompts_v2.md   ← Pass 2 decision tree 原始資料
  │   ├─ L2_Visual_Differentiation_FullAnalysis_修正版.md ← 282 個 L2 視覺特徵
  │   ├─ techpack-translation-style-guide.md  ← runtime 規格:ISO 術語 + POM 翻譯;analyze.js 啟動時 inject
  │   ├─ pom_rules_v55_classification_logic.md ← v5.5.1 分類邏輯完整文件
  │   └─ 網站架構圖.md                         ← 本 repo 架構全貌(Mermaid)
  └─ sop/                                     ← 純人類操作流程
      └─ pom_rules_pipeline_guide_v2.md       ← scripts/core/ 產線完整操作手冊(五階段)
data/
  ├─ runtime/                                 ← 線上系統 runtime 讀的成品 JSON
  │   ├─ l2_visual_guide.json                 ← 聚陽模型 Pass 1/2 視覺指引(由 analyze.js 靠 includeFiles 編進 bundle)
  │   ├─ l2_decision_trees.json               ← 聚陽模型 Pass 2 decision tree(同上)
  │   ├─ l1_standard_38.json                  ← 38 個 L1 部位標準表(上游由 ingest pipeline 或線下腳本重建)
  │   ├─ grading_patterns.json                ← 跳碼 pattern(基碼頁)
  │   ├─ bodytype_variance.json               ← Body Type 差異
  │   ├─ pom_dictionary.json                  ← POM 代號 → 中英文對照(admin 可編)
  │   ├─ recipes_master.json                  ← 通用模型 recipe 推薦(GitHub Actions 自動重建)
  │   ├─ iso_dictionary.json                  ← ISO 字典(同上,自動重建)
  │   ├─ construction_bridge_v6.json          ← 跨設計 GT × zone 施工統計(build_recipes_master 會吃)
  │   # ⚠ gender_gt_pom_rules / client_rules / design_classification_v5 已於 2026-05-14
  │   #   從 data/runtime/ 搬到 pom_rules/_derive/ —— 是 Pipeline B 規則產線輸出,
  │   #   前端 / api/ 不讀,放 runtime/ 名實不符
  │   ├─ all_designs_gt_it_classification.json ← 全量 design 的 GT / IT 分類(1,292 designs;CI Step 2 vlm_pipeline/extract_unified fallback 讀)
  │   ├─ bucket_taxonomy.json                 ← 28 v4 + 59 legacy bucket 分類表(Step 3 --strict 驗證用)
  │   ├─ l1_part_presence_v1.json             ← 聚陽模型:GT×IT 下每個部位出現率(345 KB)
  │   └─ l1_iso_recommendations_v1.json       ← 聚陽模型:部位名 → ISO 建議(519 KB)
  ├─ source/                                  ← 手維護 / 上傳的原始底稿
  │   ├─ BIBLE_UPGRADE.md                     ← Bible 升級 SOP(xlsx 留聚陽端,JSON 進 repo)
  │   ├─ M7_PULLON_DATA_SCHEMA.md             ← m7 source schema 文件(2026-05-08+)
  │   └─ L2_代號中文對照表.xlsx               ← L1/L2 代號對照(283 L2,build_l2_visual_guide 讀)
  │   # ⚠ 五階層展開項目_*.xlsx 不再進 repo (>25 MB),維護者本機 build + push 38 個 JSON
  ├─ legacy/                                  ← 退役的 pom_analysis_v5.5.1 留下的 fallback
  │   ├─ all_designs_gt_it_classification.json ← vlm_pipeline / extract_unified fallback
  │   └─ pom_dictionary.json                  ← snapshot 期版本(只給 fallback 用)
  └─ ingest/                                  ← PDF/PPTX 上傳後的 staging 區,Actions workflow 讀寫
      ├─ uploads/                             ←   使用者上傳的原始 PDF/PPTX（處理完由 workflow 刪）
      ├─ metadata/designs.jsonl               ←   D-number 去重表（Step 1 append）
      ├─ pptx/<slug>.txt                      ←   PPTX 文字（Step 1）
      ├─ pdf/callout_images/<DID>_p<N>.png    ←   PDF callout 影像（Step 1，216 DPI，處理完不保留）
      ├─ pdf/callout_manifest.jsonl           ←   PDF callout 影像索引
      ├─ unified/{dim,facts}.jsonl            ←   Step 2a 全量合併 4 來源的 facts
      ├─ vlm/{facts.jsonl,vlm_callout_extracts.json}
      │                                       ←   Step 2b 輸出（**vlm/**，不是 vlm_v1）
      ├─ consensus_v1/entries.jsonl           ←   手動 bucket consensus 規則（275 條，build_recipes_master 吃）
      ├─ construction_by_bucket/              ←   外部資料源（688 設計，Step 2a 讀）
      ├─ consensus_rules/                     ← 275 筆 `source=consensus_rules_final`，build_recipes_master 透過 `*/facts.jsonl` glob 讀；大多跟 consensus_v1 重疊被 dedup，但仍貢獻少數 entries
      ├─ ocr_v1/                              ← 1202 筆 OCR 輸出，同樣靠 glob 被讀到；貢獻 ~249 個 entries（2026-04-24 實測）
      └─ m7/                                    ← **2026-05-08 加**:聚陽 PullOn pipeline 推進來
          ├─ entries.jsonl                    ←   aggregated by 6-dim key (gender/dept/garment/item/fabric/l1;JSON key 簡寫為 gt/it),build_recipes_master `build_from_m7_pullon()` 吃
          └─ designs.jsonl.gz                 ←   per-EIDH 完整履歷 (18,300 件 PullOn,gzipped),Phase 2 View B derive 吃(原 Step 4c designs_index derive 已 2026-05-09 retired)
l2_l3_ie/*.json                               ← 聚陽模型:38 個 L1 部位的 L2-L3-IE 規則(39 檔 = 38 L1 + 1 index)
pom_rules/*.json                              ← POM 規則(**137 bucket** v8 2026-05-13;139 檔 = 137 + _index.json + pom_names.json,由 scripts/core/reclassify_and_rebuild.py 產出;bucket key v6+ 改 `<Dept>_<MK_Item>|<Gender>`)
recipes/*.json                                ← PATH2 做工配方(72 檔,被 star_schema/scripts/build_recipes_master.py 吃)
path2_universal/                              ← 通用模型(不分客戶/品牌)的做工推薦資料源(原 General Model_Path2_Construction Suggestion/,2026-05-07 改名)
  ├─ iso_lookup_factory_v4.3.json             ← **primary** 查表:Dept × Gender × GT × L1(230 entries)
  ├─ iso_lookup_factory_v4.json               ← v4 fallback 查表:Fabric × Dept × GT × L1_code(282 entries,提供 iso_zh / 機種)
  ├─ PATH2_通用模型_做工推薦Pipeline.md       ← 通用模型 pipeline 總說明
  ├─ PATH2_Phase2_Upload_Pipeline.md          ← Phase 2 上傳 pipeline 實作說明
  └─ README.md                                ← 資料夾本身的 v4.3 說明
scripts/
  ├─ core/                                    ← 線下產線腳本(21 支 entry-point;BASE 目錄用 --base-dir 或 $POM_PIPELINE_BASE 指定)
  └─ lib/
      └─ extract_techpack.py                  ← PDF parser 函式庫,被 scripts/core/run_extract_*.py import
star_schema/scripts/                          ← **線上 ingest pipeline**(由 .github/workflows/rebuild_master.yml 呼叫)
  ├─ extract_raw_text.py                      ← Step 1:掃 uploads/,抽 PPTX 文字 + PDF callout 圖;支援 --allow-empty / --force
  ├─ extract_unified.py                       ← Step 2a:合併 4 來源 → data/ingest/unified/{dim,facts}.jsonl
  ├─ vlm_pipeline.py                          ← Step 2b:讀 vlm_raw_extracts.json → ISO 對映 → data/ingest/vlm/facts.jsonl(continue-on-error)
  └─ build_recipes_master.py                  ← Step 3 (--strict):**7 來源合併** (recipe / consensus_v1 / facts_agg / m7 / v4.3 / v4 / bridge) → data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json
docs/architecture/                            ← 架構設計文件
  ├─ STYTRIX_ARCHITECTURE.md                  ← 完整架構 v3.0 (Step 1/2/3/4 framework)
  ├─ PHASE2_DERIVE_VIEWS_SPEC.md              ← Phase 2 derive views spec (master.jsonl → View A recipes_master + View B l2_l3_ie 升級;原 View C designs_index 在 2026-05-09 retired)
  └─ PLATFORM_SYNC_PLAN.md                    ← 聚陽端 → platform sync plan
requirements-pipeline.txt                     ← GitHub Actions 用的 Python 依賴(pymupdf + python-pptx)
README.md / CLAUDE.md                         ← 入口兩件套(只剩這兩份 .md 在 root)
```

### ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 使用狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender；含 iso_zh / machine / pptx_2025_votes | **fallback** |
| v4.3 | Department × Gender × GT × L1 | 230 | **fine GT 對齊 App UI**（PANTS/LEGGINGS/SHORTS 保留細分）；5 種來源合併；1,328 designs | **primary** |

前端 `isoOptionsFor(v43, v4, filters, l1Code)` 先試 v4.3（性別 + 細 GT），查無對應則退 v4；v4 的 iso_zh/machine 表順便用在 v4.3 的 ISO 顯示。

v4.3 GT 已經對齊 UI，不再需要 `BOTTOM` 粗桶，alias 縮到只剩 `BODYSUIT → TOP` 和 `SWIM_PIECE → TOP` 兩個 UI 有但 v4.3 沒 bucket 的例外（`V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS`）。歷史版本（v3 / v4.1 / v4.2 / full_analysis / knit_pptx_* / woven_*）已陸續移除。

## 兩組獨立的資料 pipeline

| | 線下規則產線 (`scripts/core/`) | 線上 ingest pipeline (`star_schema/scripts/`) |
|---|---|---|
| **Trigger** | 手動執行 | GitHub Actions:push 到 `main` 或手動 `workflow_dispatch` |
| **執行環境** | 本機或 CI 皆可；BASE 目錄用 `--base-dir` CLI 或 `$POM_PIPELINE_BASE` env var 指定（見 `scripts/core/_pipeline_base.py`） | `ubuntu-latest` runner，依 `requirements-pipeline.txt` 裝 Python 依賴 |
| **主要輸出** | `pom_rules/*.json`（137 bucket）、`l2_l3_ie/*.json`、`data/runtime/{l2_visual_guide,l2_decision_trees,l1_*}.json` 等 | `data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json`、`data/ingest/**` |
| **操作文件** | `docs/sop/pom_rules_pipeline_guide_v2.md` | `path2_universal/PATH2_Phase2_Upload_Pipeline.md` |

兩者**彼此不共用程式碼**，動其中一邊不會自動影響另一邊。

### 線下產線（`scripts/`）主要腳本

| 腳本 | 做什麼 | 產出 |
|---|---|---|
| `reclassify_and_rebuild.py` | v6.0 全量重分類（Gender/Dept/GT/Fabric）+ rebuild POM 規則 | `pom_rules/*.json` 137 bucket + `_index.json` + `pom_names.json` |
| `rebuild_profiles.py` | 重建 profile union，reclassify 的上游 | profile union（內部路徑） |
| `enforce_tier1.py` | 產線後強制 tier-1 rule（必備 POM 下限） | 覆蓋 `pom_rules/*.json` |
| `fix_sort_order.py` | 修 bucket 內 `pom_sort_order` 欄位排序 | 覆蓋 `pom_rules/*.json` |
| `run_extract_2025_seasonal.py` / `run_extract_new.py` | 從 2025 / 2026 PDF 抽 MC+POM | `mc_pom_*.jsonl` |
| `build_l2_visual_guide.py` / `build_l2_decision_trees.py` | 從 xlsx + md 產生 Pass 2 guide / decision tree | `data/runtime/l2_visual_guide.json` / `data/runtime/l2_decision_trees.json` |
| `build_bible_skeleton.py` | 從 `data/source/五階層展開項目_YYYYMMDD.xlsx` 拆分成 38 個 L1 JSON(純 stdlib,自動抓最新日期的 xlsx) | `l2_l3_ie/*.json`(+ `_index.json`) |
| `rebuild_all_analysis_v2.py` / `rebuild_grading_3d.py` | 全量分析 / 3D grading 重建 | `$BASE/*.json`(吃 `$POM_PIPELINE_BASE`,輸出在外部 BASE 樹) |
| `validate_buckets.py` | 驗證 `data/runtime/bucket_taxonomy.json` + `pom_rules/*.json` 一致性 | exit 0 / 1 |

分類邏輯改了或新資料進來時的流程（每支腳本都接受 `--base-dir` 或 `$POM_PIPELINE_BASE`）：

```bash
export POM_PIPELINE_BASE=/你的 BASE 路徑
python3 scripts/core/run_extract_new.py              # 1. 新 PDF → mc_pom_*.jsonl
python3 scripts/core/rebuild_profiles.py             # 2. 合併 profile union
python3 scripts/core/reclassify_and_rebuild.py       # 3. 重算 → 覆蓋 pom_rules/
python3 scripts/core/enforce_tier1.py                # 4a. 後處理:tier1 強制
python3 scripts/core/fix_sort_order.py               # 4b. 後處理:排序
# 5. push 到 main,前端自動套用
```

BASE 目錄需包含 `2024/ 2025/ 2026/` PDF 樹 + `_parsed/` + `all_years.jsonl` + `pom_dictionary.json`（詳情看 `scripts/core/_pipeline_base.py` docstring）。想給外部單位跑,用前端「📦 打包 Pipeline」下載 zip。

### 新增 bucket 的 SOP

兩組 bucket 有不同來源和新增方式,**不要混淆**:

| Bucket 集 | 位置 | 形狀 | 新增方式 |
|---|---|---|---|
| **Pipeline A (recipes_master) 的 28+59 bucket** | `data/runtime/bucket_taxonomy.json` | 兩段 schema:`buckets` 28 個 v4 4-dim `<GENDER>_<DEPT>_<GT>_<IT>` UPPERCASE 標量值;`legacy_buckets` 59 個 3-dim `<GENDER>_<DEPT>_<GT>` UPPERCASE list 值(給 pre-v4 facts/consensus 兜底,JSON key 簡寫為 `gt`/`it`) | **手動** — 編輯 JSON 加新 entry,v4 段每個 entry 必須有 `gender`/`dept`/`gt`/`it` 四個非空 scalar;legacy 段每個 entry 必須有 `gender`/`dept`/`gt` 三個非空 list。加完跑 `python3 scripts/core/validate_buckets.py` 驗證,再 `python3 star_schema/scripts/build_recipes_master.py --strict` 確認 facts 被接受。 |
| **Pipeline B (POM RULES) 的 137 bucket** | `pom_rules/*.json` + `pom_rules/_index.json` | `<DEPT>_<GT>\|<GENDER>` (UPPERCASE) | **自動** — 不要手改。把新 PDF 放進 BASE 資料夾,跑 `reclassify_and_rebuild.py`,它會自動建出新 bucket 檔。 |

**Recipes** (`recipes/recipe_<GENDER>_<DEPT>_<GT>_<IT>.json`) 是第三個維度(多個 item_type),跟兩組 bucket 不是 1:1,由 Pipeline A 的 ingest 產生,一般不手動改。

Validator: `python3 scripts/core/validate_buckets.py` 檢查:
- `pom_rules/_index.json` 跟磁碟上的檔案對得上
- 每個 bucket 檔的 `bucket` 字串跟自己 `gender`/`department`/`garment_type` 欄位一致
- `data/runtime/bucket_taxonomy.json` 兩段都 keys UPPERCASE、無 case collision、必填欄位齊全(v4 4-dim scalar / legacy 3-dim list)
- 額外 warning:legacy 3-dim key 跟 v4 4-dim key prefix 撞到時提示(cascade 可能 double-resolve)

`--strict` 旗標把 warning 也當 error。加到 CI 的方式:在 `.github/workflows/rebuild_master.yml` 的 Step 3 前加一步 `python3 scripts/core/validate_buckets.py --strict`。

### Extract scripts 三個位置的角色分工

Repo 裡有三個位置各有 `extract*.py`,形狀相似但**產出格式完全不同、餵不同 pipeline**,常混淆:

| 位置 | 腳本 | 輸入 | 輸出格式 | 餵誰 | 現狀 |
|---|---|---|---|---|---|
| `scripts/lib/` | `extract_techpack.py` | Centric 8 ONY 單份 PDF | in-memory dict:`{design_number, mcs:[{poms:[{POM_Code,sizes:{...}}]}]}` | 被 `scripts/core/run_extract_*.py` import 當底層 parser | **活**(純函式庫,2026-05-07 從 pom_analysis_v5.5.1/scripts/ 抽出) |
| `scripts/core/` | `run_extract_2025_seasonal.py` | `$BASE/2025/{FA25,HO25,SP25,SU25}/**/*.pdf` | `$BASE/_parsed/mc_pom_2025.jsonl` | Pipeline B(POM RULES)的 `rebuild_profiles.py` | **活** — 2025 backlog 專用 |
| `scripts/core/` | `run_extract_new.py` | `$BASE/2026/{5,FA26,HO26,SP26,SU26,SP23,SP27}/**/*.pdf` | `$BASE/_parsed/mc_pom_2026.jsonl` | 同上 | **活** — 2026 production(~5K PDF)|
| `star_schema/scripts/` | `extract_raw_text.py` | `data/ingest/uploads/*.pdf`、`*.pptx` | `data/ingest/metadata/designs.jsonl` + `pptx/*.txt` + `pdf/callout_images/*.png` | Pipeline A(recipes_master)Step 1 | **活** — CI 每次 push uploads/ 自動跑 |
| `star_schema/scripts/` | `extract_unified.py` | `data/ingest/{metadata,pptx,pdf,vlm}/` | `data/ingest/unified/{dim,facts}.jsonl` | Pipeline A Step 2a | **活** — 同上,CI 自動跑 |

**怎麼選用**:

- 重建 **POM RULES**(137 bucket 尺寸規則)→ 用 `scripts/core/run_extract_*.py`(+ `scripts/lib/extract_techpack.py` 當 parser)。`mc_pom_*.jsonl` 含 measurement chart + POM rows,是 `rebuild_profiles.py` 的唯一進料
- 重建 **recipes_master**(做工配方)→ 用 `star_schema/scripts/extract_*.py`。不關心 MC/POM 尺寸,抓的是做工 callout + ISO zone
- ~~v5.5.1/run_extract.py~~ 已於 2026-05-07 隨 `pom_analysis_v5.5.1/` 整個資料夾退役;`extract_techpack.py` 抽到 `scripts/lib/`,其餘清掉

### 線上 ingest pipeline（`star_schema/scripts/` + GitHub Actions）

Admin 在前端「📤 上傳 Techpack」丟一份 PDF/PPTX：

1. **上傳路徑**：`POST /api/ingest_token` 取 `GITHUB_PAT`，瀏覽器直連 GitHub `PUT contents` 把檔案送進 `data/ingest/uploads/`。沒檔案大小分流（歷史上曾規劃走 `/api/ingest_upload` 的小檔路徑，2026-04-24 移除未實作的 endpoint；現在任何大小都走直連）。
2. **GitHub Actions 觸發**(`.github/workflows/rebuild_master.yml`,`push: paths: data/ingest/uploads/**` 或 `data/ingest/m7/**`)。實際步驟順序是 **1 → 2b → 2a → Pre-3 → 3 → 4a → 4b → 4c**(2b 刻意排在 2a 前,讓 2a 的 unified 合併能吃到本次 run 剛產出的 VLM facts;Pre-3 跑 `validate_buckets.py --strict` 早期 schema gate;Step 4 是 derive views,把 master.jsonl + m7 designs.jsonl.gz 衍生成 runtime view A/B + brands.json):
   - **Step 1** `extract_raw_text.py` — 掃 uploads/；PDF 讀首頁元資料（季節 / 品牌 / 類型）+ 抽 D-number，PPTX 逐頁取文字，PDF callout 頁面評分後 216 DPI 渲染成 PNG。`--allow-empty` 允許首次空掃，`--force` 忽略已處理重跑。
   - **Step 2b** `vlm_pipeline.py --map-iso --ingest-dir data/ingest --out data/ingest/vlm` — 若沒預填 `vlm_raw_extracts.json` 但 `ANTHROPIC_API_KEY` 有設，會對每張 callout PNG 呼叫 Claude Haiku 自動分析（`requirements-pipeline.txt` 加 `anthropic>=0.25.0`）；否則讀既有 `vlm_raw_extracts.json` 走手填路徑。輸出 `vlm/facts.jsonl`（含 `bucket` 欄位，Step 3 才能用）+ `vlm_callout_extracts.json`。**資料夾是 `vlm/`，不是 `vlm_v1/`**。`continue-on-error`，失敗不擋 build。
   - **Step 2b failure notice**（跟在 2b 後面，`if: steps.vlm.outcome == 'failure'`）— 2b 失敗時寫醒目警告到 `$GITHUB_STEP_SUMMARY` 並設 `VLM_FAILED=true`；Commit step 會把這個 flag 加到 commit message body，讓翻 git log 或 Actions UI 的人一眼看得到。
   - **Step 2a** `extract_unified.py` — **全量**合併 4 來源（PPTX 中文 / PDF 英文 / construction_by_bucket / construction_from_dir5）+ Step 2b 剛產的 VLM facts → `unified/{dim,facts}.jsonl`。中文 / 英文各自 parse zone + ISO，優先級：PPTX JSON > PPTX txt > 其他。
   - **Pre-Step 3** `validate_buckets.py --strict` — Schema gate(<1s):驗 `bucket_taxonomy.json` v4 28 buckets + legacy 59 buckets 兩段 schema 都 UPPERCASE / 必填欄齊全 / 無 case collision,以及 `pom_rules/_index.json` 跟磁碟檔案一致。早期失敗比 Step 3 全量 cascade 才掛快很多。
   - **Step 3** `build_recipes_master.py --strict` — 合併 7 份來源 → 全量重建:
     - `recipes/*.json`(72 檔,含 `_index.json` + 71 recipe)
     - `data/ingest/consensus_v1/entries.jsonl`(275 條 bucket consensus)
     - `data/ingest/*/facts.jsonl` glob(含 vlm/、ocr_v1/、consensus_rules/)
     - `data/ingest/m7/entries.jsonl`(5,076 entries,聚陽 PullOn)
     - `path2_universal/iso_lookup_factory_v4.3.json`(primary,230 條)
     - `path2_universal/iso_lookup_factory_v4.json`(fallback,282 條)
     - `data/runtime/construction_bridge_v6.json`(跨設計 GT × zone 統計)
     - L1 必須在 38 標準內、bucket 必須在 taxonomy 內,違規 exit 1 擋 commit
     - 輸出:`data/master.jsonl` + `data/master.meta.json`(內部 master,含 `_m7_*` 欄位給後續 derive 用)+ `data/runtime/{recipes_master,iso_dictionary,l1_standard_38}.json`
   - **Step 4a** `derive_view_recipes_master.py` — Phase 2 View A:讀 `data/master.jsonl`,把每筆 entry 的 `_m7_*` 內部欄位剝掉(那些欄位是 derive 用的,前端不消費,留著會讓 `recipes_master.json` 多 ~15x),覆寫 `data/runtime/recipes_master.json`。
   - **Step 4b** `derive_bible_actuals.py --all --in-place` — Phase 2 View B:讀 `l2_l3_ie/<L1>.json`(IE-xlsx 來的 Phase 1 5-elem list 或上一輪產的 Phase 2 dict 皆可,2026-05-11 修掉 dict pass-through bug,**永遠重算 actuals**)+ `data/ingest/m7/designs.jsonl.gz`(18,300 件實做工段,跨 24 brand),原地升級成 dict schema `{l5, ie_standard:{sec,grade,primary,machine}, actuals?:{n_steps,n_designs,sec_median,sec_p25,sec_p75,by_brand,machine_top}}`,把 m7 實際工段數據掛在對應 step 的 `actuals` 欄。
   - **Step 4c** `scripts/core/build_brands.py` — 從 `data/ingest/m7/entries.jsonl` 的 `client_distribution` 聚合每個 brand 的 n_entries / n_designs,排序 n_designs DESC 寫進 `data/runtime/brands.json`(~1.8 KB)。前端 boot 時 eager fetch 這個檔當 Brand 下拉 source(2026-05-11+ 不再硬寫 BRANDS 常數);新 brand 進 m7 → CI 重產 brands.json → 用戶 reload 就看到。
3. **Commit 回 `main`**:`git rm data/ingest/uploads/*` + `git add` 重建結果(含升級後的 `l2_l3_ie/*.json`)+ `git add data/ingest/vlm/`(讓 VLM 分析結果持久化);訊息 `chore(data): auto-rebuild recipes_master [skip ci]` 避免無限循環;Vercel 偵測 push → 自動重新部署。

前端在「📤 上傳 Techpack」Modal 內 poll `GET /repos/.../actions/runs?head_sha=<sha>`,依 workflow 實際順序顯示步驟。Actions API 回 403/404(私人 repo / token 缺 `actions:read` scope)會降級成不帶 token 重試,仍失敗時直接顯示 GitHub Actions 連結不再 poll。

#### 獨立的 POM rules 校驗 workflow(2026-05-13 拆出)

`.github/workflows/validate_pom_rules.yml` 是專門盯著 `pom_rules/**` 的獨立 workflow,跟主 `rebuild_master.yml` 解耦。理由:POM rules **regeneration** 需要外部 `$POM_PIPELINE_BASE`(8,892 設計 × `_parsed/mc_pom_*.jsonl`),CI 不具備這個資料源 — 所以 regen 走聚陽 Windows 本機跑 + PR push。CI 端只能驗 schema(bucket key UPPERCASE / `_index.json` 跟磁碟對齊 / `gender`-`department`-`garment_type` 欄位跟 bucket 字串一致)。

| Workflow | Trigger | 跑啥 | 重建 | 用途 |
|---|---|---|---|---|
| `rebuild_master.yml` | `push: paths: [data/ingest/uploads/**, data/ingest/m7/**]` 或手動 | Step 1-4c 全套 + Pre-Step 3 schema gate | ✓ rebuild recipes_master / brands.json / l2_l3_ie/* | 主 ingest pipeline |
| `validate_pom_rules.yml` | `push: paths: [pom_rules/**, scripts/core/validate_buckets.py, workflow file]` | `validate_buckets.py --strict`(<1s)| ✗ 只驗 schema | POM rules schema gate(雙重保險,主 workflow Pre-Step 3 也跑同一隻) |
| `build_bible_skeleton.yml` | `workflow_dispatch` only | 找 xlsx → 跑 `build_bible_skeleton.py` → commit `l2_l3_ie/` | ✓(罕用)| Bible xlsx 大 >25 MB 不進 repo,實務上維護者本機跑後直 push JSON;這個 workflow 是緊急 fallback |

## Admin 通道

所有 admin 入口都要 `x-admin-token`（對應 Vercel 的 `ADMIN_TOKEN` 環境變數）；進到前端管理選單先在「⚙ 設定」填。管理選單分兩組:**Pipeline 對外協作** + **管理工具**。

| 入口 | 做什麼 | 走哪 | Body 大小 |
|---|---|---|---|
| 📦 下載 Pipeline 包（PackageModal） | 組 zip 給外部協作單位在本機跑 **Pipeline A(recipes_master)+ Pipeline B(POM RULES)** 兩條線。含 13 個 py + 參考資料 + 2 份 pom pipeline .md + 自動產 README / VERSION / `.env.example` / `run.sh` / `run_pom_rules.sh` | 取 PAT → GitHub API 抓 main sha + recipes/ 列表 → 並行拉 raw.githubusercontent.com → JSZip 瀏覽器組 zip → 觸發下載 | — |
| 📥 上傳 Pipeline 結果（ResultsUploadModal） | 吃外部送回的 zip / jsonl,merge 到 `data/ingest/{unified,vlm}/facts.jsonl` + `metadata/designs.jsonl`(append 或 append-dedup by design_id) | JSZip 瀏覽器解壓 → 比對 path → GET 現有 → merge → 直連 `PUT contents` | 無實質上限 |
| 📤 上傳 Techpack（UploadModal） | 丟 PDF/PPTX 進 `data/ingest/uploads/`,觸發 Actions 重建 recipes_master | `POST /api/ingest_token` → 瀏覽器直連 GitHub `PUT` | 無實質上限 |
| 📝 POM 翻譯表編輯（AdminModal） | 編 `data/runtime/pom_dictionary.json`,自動 diff + commit msg | `POST /api/push-pom-dict`(Vercel endpoint) | 小 |
| 🛠 IE 底稿管理（IEAdminModal） | **2026-05-08+ 改流程**:xlsx (>25 MB) 不再進 repo,聚陽送新版 xlsx 時維護者**本機**跑 `python3 scripts/core/build_bible_skeleton.py` build 出 38 個 JSON,push `l2_l3_ie/*.json`(SOP 見 `data/source/BIBLE_UPGRADE.md`)。原 `build_bible_skeleton.yml` workflow 改 workflow_dispatch only。 | 無線上上傳路徑(只送 JSON 不送 xlsx) | — |
| 📚 權威手冊登記表（ManualsModal） | Read-only,顯示 7 份權威手冊的角色 / 引用鏈 | 無後端呼叫 | — |
| 📂 Code 瀏覽（CodeBrowserModal,**2026-05-13 加**)| GitHub 風格的 in-app file browser:左側目錄樹 + 右側 Prism.js syntax highlight,從 repo root relative path fetch(5 MB 上限),含 search-by-path filter / 大檔警告 / copy / GitHub 連結 | 讀 `data/runtime/code_manifest.json`(由 `scripts/core/build_code_manifest.py` 產出),按 path 拉 raw 檔 | 5 MB 單檔 |

> ~~🩹 上傳 Patch (JSON)（PatchUploadModal）~~ — 2026-04-23 移除,由 📥 上傳 Pipeline 結果取代(新通道吃 raw facts.jsonl 而非 recipes_master.json patch,更符合外部協作實際流程)。

所有直連 GitHub 的路徑共用 `/api/ingest_token` 發出的 `GITHUB_PAT`(需 `contents: write`);PAT 只在 admin 瀏覽器 session 裡活著。

### Pipeline 外送包

📦 下載後交給協作單位,內含:
- **Pipeline A 腳本**:`star_schema/scripts/*.py`(6 檔總共) + `scripts/core/build_brands.py`(Step 4c)。外送包 bundle 5 檔 — Step 1-3 + Step 4a `derive_view_recipes_master.py`;**Step 4b `derive_bible_actuals.py` + Step 4c `build_brands.py` 不送外部** — 需要 `data/ingest/m7/{entries.jsonl, designs.jsonl.gz}`(聚陽 PullOn 內部工段資料,IP 敏感)+ `l2_l3_ie/*.json` 38 檔(74 MB),由 main CI 接手。外部跑完 Step 1-4a 後送回 raw `data/ingest/{metadata,unified,vlm}/*.jsonl`,main CI 合併 + 重跑 Step 3 + 4a + 4b + 4c 產最終 view + brands.json
- **Pipeline B 腳本**:`scripts/core/*.py`(8 檔包含 `_pipeline_base.py` + 7 支改用 `--base-dir` / `$POM_PIPELINE_BASE` 的產線腳本)+ `scripts/lib/extract_techpack.py`
- `requirements-pipeline.txt`、`docs/spec/techpack-translation-style-guide.md`
- 所有 reference JSON(construction_bridge / bucket_taxonomy / l1_standard_38 / pom_dictionary / consensus / iso_lookup × 2 / recipes × 72)
- Pipeline B 產線文件:`docs/sop/pom_rules_pipeline_guide_v2.md` + `docs/spec/pom_rules_v55_classification_logic.md`
- 動態產:`README.md`(繁中含兩條 pipeline 的 setup/run/回傳步驟)、`VERSION`(commit sha)、`.env.example`(提醒自備 `ANTHROPIC_API_KEY`)、`run.sh`(Pipeline A)、`run_pom_rules.sh`(Pipeline B)

外部跑完 Pipeline A 的 `./run.sh` 後,把 `data/ingest/{metadata,unified,vlm}/*.jsonl` 打成 zip → 📥 上傳回來 → 到 Actions 手動 workflow_dispatch 重建 recipes_master。
Pipeline B(`./run_pom_rules.sh`)跑完產出的 `$POM_PIPELINE_BASE/pom_rules/` 整個覆蓋 repo 的 `pom_rules/` 目錄 → PR 推上去。

## 本機預覽

直接用任何 static server 指到專案根目錄即可：

```bash
python3 -m http.server 5173
# 或
npx serve .
```

`/api/*` 本機無法執行（需 Vercel runtime）；要測 AI 功能或 admin 通道請部署到 Vercel preview。

## 部署

GitHub push → Vercel 自動建置（preview / production）。

**Vercel 環境變數**（Project Settings）：
- `ANTHROPIC_API_KEY` — `api/analyze.js` 呼叫 Claude Vision 用
- `ADMIN_TOKEN` — 所有 admin 端點共享的驗證 token
- `GITHUB_PAT` — `api/push-pom-dict.js` / `api/ingest_token.js` 寫回 GitHub 用（需 `contents: write`）

**GitHub Actions secrets**（Repo Settings）：
- `ANTHROPIC_API_KEY` — workflow Step 2b VLM pipeline 用（沒設定時 2b 跳過，不擋 build）
- `GITHUB_TOKEN` — 自動注入，Commit step push 用

## 待辦 / Roadmap

2026-05-14 跑完 code review + 清理(A、B、C 都已 commit;A=runtime/ orphan 搬到 `pom_rules/_derive/`、B=刪 `new/.py`、C=`tests/test_schema.py` 11 invariant pytest)後,留下兩項**已知架構債**。屬於要設計 + 跨多檔改的 task,需 user 決定才能動;詳細狀況見 [`CLAUDE.md` 待辦 / Roadmap 區](./CLAUDE.md#待辦--roadmap2026-05-14-架構評估後留下的兩項需設計才能動)。

| # | 任務 | 工作量 | 收益 | 觸發點 |
|---|------|--------|------|--------|
| **D** | 評估 `data/ingest/m7/designs.jsonl.gz` server-side filter API | 大,需設計 | **mobile 用戶不再 OOM** — 現況 `filterBibleByCategory` 整檔 lazy fetch + 解壓 + parse 18,300 designs(31 MB gzipped → 332 MB JSON)cache module-scope,瀏覽器 tab 吃 ~400 MB 記憶體;mobile / 低 RAM 裝置可能 crash | 已收到實機 OOM 回報 |
| **E** | Bible 拆 structure + actuals 兩檔 | 中大,需改 `derive_bible_actuals.py` + 前端 `filterBibleByBrand` / `filterBibleByCategory` + `_index.json` schema | **repo size git diff 變乾淨** — 實測 132 MB Bible = 44.8 MB structure (34%) + 87.5 MB actuals (66%);拆檔後 m7 push 只動 actuals,structure 不會被誤動。**前端 brand filter 省 95% bandwidth**(若 actuals 再拆 per-brand) | m7 entries 再增加(到 10k+)時更明顯 |
| **F** | `bodytype_variance.json` 加 per-brand 維度 | 中,聚陽端寫 `M7_Pipeline/scripts/build_bodytype_variance_per_brand.py` | **非 ONY brand 的 Petite/Tall delta 變真實值** — 現況整檔 ONY-only,選 DKS/KOH 等 brand 看到的 delta 是外推。spec 寫好(`docs/architecture/PER_BRAND_BODYTYPE_VARIANCE_SPEC.md`),前端 warning + auto-detect `_meta.per_brand` flag 已 ship(2026-05-14),聚陽端跑 build 推新 schema 即生效 | 使用者反映「DKS 沒有 Petite/Tall/Plus 嗎? 這必須是品牌專屬」 |

三項都已實測過數字、寫好方案,在 `CLAUDE.md` 「待辦 / Roadmap」區內;不在這輪 commit 內(F 的前端 detection 已 ship,只等聚陽端資料)。
