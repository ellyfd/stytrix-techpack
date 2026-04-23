# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

> 想直接看全貌 Mermaid 圖（7 張 + 資料夾對照表）：[`網站架構圖.md`](./網站架構圖.md)

## 兩種模式

Header 右上提供「**聚陽模型** / **通用模型**」切換（選擇會記在 `localStorage.stytrix.appMode`）。

| 模式 | 作工建議 | 尺寸 | 全碼 |
|------|----------|------|------|
| **聚陽模型** (`makalot`) | 五階層：L1 部位 → L2 零件 → L3 形狀 → L4 工法 → L5 工段 + IE 秒數 | POM tier（必備 / 建議 / 選配），依 `pom_rules/<bucket>.json` | ✓ 各 size 中位數 + 公差 + 跳碼 |
| **通用模型** (`universal`) | Path 2：VLM 只判 L1，雙表查 ISO：先 `iso_lookup_factory_v4.3.json`(Dept × **Gender** × GT × L1，fine GT 對齊 UI 下拉選單，130 entries)再退 `iso_lookup_factory_v4.json`(Fabric × Dept × GT × L1_code，提供 iso_zh/機種)；另吃 `recipes_master.json` 顯示 recipe 推薦 | 僅 5 項基礎大尺寸（上衣：肩/胸/下擺/袖長/身長；下身：腰/臀/前後檔/內長/褲口） | — |

通用模型後端 (`api/analyze.js`) 接 `mode=universal` 時**只跑 Pass 1（L1 偵測）**，省掉 Pass 2 的 decision-tree token。

## 架構

純靜態 HTML + Vercel Node.js Functions，無 bundler、無 `package.json`。

```
index.html                                    ← 整個 app（React via CDN + 內聯 JS/CSS）
LOGO.png                                      ← Header logo 圖檔
api/
  ├─ analyze.js                               ← Claude Vision：Pass 1 (L1) + Pass 2 (L2 decision tree)
  │                                             mode=universal 時只跑 Pass 1
  ├─ push-pom-dict.js                         ← Admin：POM 翻譯表寫回 data/pom_dictionary.json
  ├─ ingest_token.js                          ← Admin：發 GITHUB_PAT 讓瀏覽器直連 GitHub（繞 4.5MB body 上限）
  └─ ingest_upload.js                         ← Admin：≤4.5MB 的 PDF/PPTX 經 Vercel 代 commit 到 data/ingest/uploads/
.github/workflows/
  └─ rebuild_master.yml                       ← push 到 data/ingest/uploads/** 時觸發；自動重建 recipes_master 並 push 回 main
data/
  ├─ l2_visual_guide.json                     ← 聚陽模型 Pass 1/2 視覺指引（api/analyze.js 靠 vercel.json includeFiles 編進 bundle）
  ├─ l2_decision_trees.json                   ← 聚陽模型 Pass 2 decision tree（同上）
  ├─ grading_patterns.json                    ← 跳碼 pattern（基碼頁）
  ├─ bodytype_variance.json                   ← Body Type 差異
  ├─ pom_dictionary.json                      ← POM 代號 → 中英文對照（admin 可編）
  ├─ recipes_master.json                      ← 通用模型 recipe 推薦（GitHub Actions 自動重建）
  ├─ iso_dictionary.json                      ← ISO 字典（同上，自動重建）
  ├─ l1_standard_38.json                      ← 38 個 L1 部位標準表（同上，自動重建）
  ├─ client_rules.json / bucket_taxonomy.json / design_classification_v5.json / ... ← 內部參考
  └─ ingest/                                  ← PDF/PPTX 上傳後的 staging 區，Actions workflow 讀寫
      ├─ uploads/                             ←   使用者上傳的原始 PDF/PPTX（處理完由 workflow 刪）
      ├─ metadata/designs.jsonl               ←   D-number 去重表
      ├─ pdf/callout_manifest.jsonl           ←   PDF callout 影像索引
      ├─ unified/{dim,facts}.jsonl            ←   4 來源合併後的 facts（全量重建）
      └─ consensus_v1/, ocr_v1/, ...          ←   其他 fact 來源
l1_part_presence_v1.json                      ← 聚陽模型：GT×IT 下每個部位出現率（歷史位置，還在 repo 根目錄）
l1_iso_recommendations_v1.json                ← 聚陽模型：部位名 → ISO 建議（同上）
l2_l3_ie/*.json                               ← 聚陽模型：38 個 L1 部位的 L2-L3-IE 規則
pom_rules/*.json                              ← POM 規則（81 bucket × gender × dept × gt，由 scripts/reclassify_and_rebuild.py 產出）
General Model_Path2_Construction Suggestion/
  ├─ iso_lookup_factory_v4.3.json             ← **primary** 查表：Dept × Gender × GT × L1（130 entries）
  ├─ iso_lookup_factory_v4.json               ← v4 fallback 查表：Fabric × Dept × GT × L1_code（提供 iso_zh / 機種）
  ├─ L1_部位定義_Sketch視覺指引.md               ← VLM Pass 1 system prompt 資料來源
  ├─ PATH2_通用模型_做工推薦Pipeline.md          ← 通用模型 pipeline 總說明
  ├─ PATH2_Phase2_Upload_Pipeline.md          ← Phase 2 上傳 pipeline 設計文件
  └─ README.md                                ← 資料夾本身的 v4.3 說明
scripts/                                      ← **線下規則產線**（路徑寫死 /sessions/.../mnt/ONY，不可在此 repo 獨立執行）
star_schema/scripts/                          ← **線上 ingest pipeline**（由 .github/workflows/rebuild_master.yml 呼叫）
  ├─ extract_raw_text.py                      ← Step 1：掃 uploads/，抽 PPTX 文字 + PDF callout 圖
  ├─ extract_unified.py                       ← Step 2a：合併 4 來源 → unified/{dim,facts}.jsonl
  ├─ vlm_pipeline.py                          ← Step 2b：callout → VLM → iso_codes（continue-on-error）
  └─ build_recipes_master.py                  ← Step 3：ingest/*/facts.jsonl + 手冊 → recipes_master.json 等 3 份
requirements-pipeline.txt                     ← GitHub Actions 用的 Python 依賴（pymupdf + python-pptx）
pom_rules_v55_classification_logic.md         ← v5.5.1 分類邏輯完整文件
pom_rules_pipeline_guide.md                   ← scripts/ 產線操作指南（內部環境）
網站架構圖.md                                  ← 本 repo 架構全貌（Mermaid）
```

### ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 使用狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender；含 iso_zh / machine / pptx_2025_votes | **fallback** |
| v4.3 | Department × Gender × GT × L1 | 130 | **fine GT 對齊 App UI**（PANTS/LEGGINGS/SHORTS 保留細分）；5 種來源合併；1,328 designs | **primary** |

前端 `isoOptionsFor(v43, v4, filters, l1Code)` 先試 v4.3（性別 + 細 GT），查無對應則退 v4；v4 的 iso_zh/machine 表順便用在 v4.3 的 ISO 顯示。

v4.3 GT 已經對齊 UI，不再需要 `BOTTOM` 粗桶，alias 縮到只剩 `BODYSUIT → TOP` 和 `SWIM_PIECE → TOP` 兩個 UI 有但 v4.3 沒 bucket 的例外（`V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS`）。歷史版本（v3 / v4.1 / v4.2 / full_analysis / knit_pptx_* / woven_*）已陸續移除。

## 兩組獨立的資料 pipeline

| | 線下規則產線 (`scripts/`) | 線上 ingest pipeline (`star_schema/scripts/`) |
|---|---|---|
| **Trigger** | 手動執行 | GitHub Actions：push 到 `data/ingest/uploads/**` |
| **執行環境** | 內部路徑 `/sessions/.../mnt/ONY`（非本 repo 可獨立跑） | `ubuntu-latest` runner，依 `requirements-pipeline.txt` 裝 Python 依賴 |
| **主要輸出** | `pom_rules/*.json`（81 bucket）、`l2_l3_ie/*.json`、`data/l2_visual_guide.json`、`data/l2_decision_trees.json`、`l1_*.json` 等 | `data/recipes_master.json`、`data/iso_dictionary.json`、`data/l1_standard_38.json`、`data/ingest/**` |
| **操作文件** | `pom_rules_pipeline_guide.md` | `General Model_Path2_Construction Suggestion/PATH2_Phase2_Upload_Pipeline.md` |

兩者**彼此不共用程式碼**，動其中一邊不會自動影響另一邊。

### 線下產線（`scripts/`）主要腳本

| 腳本 | 做什麼 | 產出 |
|---|---|---|
| `reclassify_and_rebuild.py` | v6.0 全量重分類（Gender/Dept/GT/Fabric）+ rebuild POM 規則 | `pom_rules/*.json` 81 bucket + `_index.json` + `pom_names.json` |
| `rebuild_profiles.py` | 重建 profile union，reclassify 的上游 | profile union（內部路徑） |
| `enforce_tier1.py` | 產線後強制 tier-1 rule（必備 POM 下限） | 覆蓋 `pom_rules/*.json` |
| `fix_sort_order.py` | 修 bucket 內 `pom_sort_order` 欄位排序 | 覆蓋 `pom_rules/*.json` |
| `run_extract_2025_seasonal.py` / `run_extract_new.py` | 從 2025 / 2026 PDF 抽 MC+POM | `mc_pom_*.jsonl` |
| `build_l2_visual_guide.py` / `build_l2_decision_trees.py` | 從 xlsx + md 產生 Pass 2 guide / decision tree | `data/l2_visual_guide.json` / `data/l2_decision_trees.json` |
| `rebuild_all_analysis_v2.py` / `rebuild_grading_3d.py` | 全量分析 / 3D grading 重建 | 內部路徑 |

分類邏輯改了或新資料進來時的流程：
1. 跑 `run_extract_*.py` 把新 PDF 轉成 `mc_pom_*.jsonl`
2. 跑 `rebuild_profiles.py` 合併 profile union
3. 跑 `reclassify_and_rebuild.py` 重算 → 覆蓋 `pom_rules/`
4. 跑 `enforce_tier1.py` + `fix_sort_order.py` 做後處理
5. push 到 `main`，前端自動套用

### 線上 ingest pipeline（`star_schema/scripts/` + GitHub Actions）

Admin 在前端拖一份 PDF/PPTX 上傳：

1. **（選一）上傳路徑**：
   - 檔案 ≤ 4.5 MB：`POST /api/ingest_upload`，Vercel 代 commit 到 `data/ingest/uploads/`
   - 檔案 > 4.5 MB：`POST /api/ingest_token` 取 `GITHUB_PAT`，瀏覽器直連 GitHub API `PUT`
2. **GitHub Actions 觸發**（`rebuild_master.yml`）：
   - Step 1 `extract_raw_text.py` — 抽 PPTX 文字 + PDF callout 圖，D-number 去重
   - Step 2a `extract_unified.py` — 全量合併 4 來源（PPTX 中文 / PDF 英文 / cb / dir5）
   - Step 2b `vlm_pipeline.py` — callout VLM 增補（需 `ANTHROPIC_API_KEY` secret；`continue-on-error`）
   - Step 3 `build_recipes_master.py --strict` — 任何 ingest/taxonomy 違規就 exit 1 擋 commit
3. **Commit 回 `main`**：訊息含 `[skip ci]`，避免無限循環；Vercel 自動重新部署。

## Admin 通道

所有 admin 端點都要 `x-admin-token`（對應 Vercel 的 `ADMIN_TOKEN` 環境變數）。

| 端點 | 用途 | Body 大小 |
|---|---|---|
| `POST /api/push-pom-dict` | POM 翻譯表寫回 `data/pom_dictionary.json` | 小 |
| `POST /api/ingest_token` | 發 `GITHUB_PAT` 給瀏覽器直連 GitHub | — |
| `POST /api/ingest_upload` | Vercel 代 commit PDF/PPTX 到 `data/ingest/uploads/` | ≤ 4.5 MB |
| 瀏覽器直連 GitHub（大檔 / JSON patch） | 用 `ingest_token` 拿到的 PAT 自己 `PUT contents` | 無實質上限 |

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
- `GITHUB_PAT` — `api/push-pom-dict.js` / `api/ingest_upload.js` / `api/ingest_token.js` 寫回 GitHub 用（需 `contents: write`）

**GitHub Actions secrets**（Repo Settings）：
- `ANTHROPIC_API_KEY` — workflow Step 2b VLM pipeline 用
- `GITHUB_TOKEN` — 自動注入，workflow Step 4 push 用
