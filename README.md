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
  ├─ analyze.js                               ← Claude Vision（claude-sonnet-4-6）：Pass 1 (L1) + Pass 2 (L2 decision tree)
  │                                             mode=universal 時只跑 Pass 1；module init 讀 l2_visual_guide /
  │                                             l2_decision_trees / l1_standard_38 / techpack-translation-style-guide
  ├─ push-pom-dict.js                         ← Admin：POM 翻譯表寫回 data/pom_dictionary.json
  ├─ ingest_token.js                          ← Admin：發 GITHUB_PAT 讓瀏覽器直連 GitHub（繞 4.5MB body 上限）
  └─ ingest_upload.js                         ← Admin：≤4.5MB 的 PDF/PPTX 經 Vercel 代 commit 到 data/ingest/uploads/
.github/workflows/
  └─ rebuild_master.yml                       ← push 到 data/ingest/uploads/** 時觸發；自動重建 recipes_master 並 push 回 main
vercel.json                                   ← functions config：includeFiles 把 data/** + techpack-translation-style-guide.md 編進 analyze.js bundle
data/
  ├─ l2_visual_guide.json                     ← 聚陽模型 Pass 1/2 視覺指引（由 analyze.js 靠 includeFiles 編進 bundle）
  ├─ l2_decision_trees.json                   ← 聚陽模型 Pass 2 decision tree（同上）
  ├─ l1_standard_38.json                      ← 38 個 L1 部位標準表（上游由 ingest pipeline 或線下腳本重建）
  ├─ grading_patterns.json                    ← 跳碼 pattern（基碼頁）
  ├─ bodytype_variance.json                   ← Body Type 差異
  ├─ pom_dictionary.json                      ← POM 代號 → 中英文對照（admin 可編）
  ├─ recipes_master.json                      ← 通用模型 recipe 推薦（GitHub Actions 自動重建）
  ├─ iso_dictionary.json                      ← ISO 字典（同上，自動重建）
  ├─ construction_bridge_v6.json              ← 跨設計 GT × zone 施工統計（build_recipes_master 會吃）
  ├─ gender_gt_pom_rules.json                 ← Gender × GT 的 POM 規則（規則產線輸出）
  ├─ all_designs_gt_it_classification.json    ← 全量 design 的 GT / IT 分類
  ├─ client_rules.json / bucket_taxonomy.json / design_classification_v5.json
  └─ ingest/                                  ← PDF/PPTX 上傳後的 staging 區，Actions workflow 讀寫
      ├─ uploads/                             ←   使用者上傳的原始 PDF/PPTX（處理完由 workflow 刪）
      ├─ metadata/designs.jsonl               ←   D-number 去重表（Step 1 append）
      ├─ pptx/<slug>.txt                      ←   PPTX 文字（Step 1）
      ├─ pdf/callout_images/<DID>_p<N>.png    ←   PDF callout 影像（Step 1，216 DPI）
      ├─ pdf/callout_manifest.jsonl           ←   PDF callout 影像索引
      ├─ unified/{dim,facts}.jsonl            ←   Step 2a 全量合併 4 來源的 facts
      ├─ vlm/{facts.jsonl,vlm_callout_extracts.json}
      │                                       ←   Step 2b 輸出（**vlm/**，不是 vlm_v1）
      ├─ consensus_v1/entries.jsonl           ←   手動 bucket consensus 規則（275 條，被 build_recipes_master 吃）
      ├─ construction_by_bucket/              ←   外部資料源（688 設計，Step 2a 讀）
      └─ ocr_v1/                              ←   舊 OCR 輸出（未用，歷史保留）
l1_part_presence_v1.json                      ← 聚陽模型：GT×IT 下每個部位出現率（歷史位置，還在 repo 根目錄）
l1_iso_recommendations_v1.json                ← 聚陽模型：部位名 → ISO 建議（同上）
l2_l3_ie/*.json                               ← 聚陽模型：38 個 L1 部位的 L2-L3-IE 規則（39 檔 = 38 L1 + 1 index）
pom_rules/*.json                              ← POM 規則（81 bucket + _index.json = 82 檔，由 scripts/reclassify_and_rebuild.py 產出）
General Model_Path2_Construction Suggestion/
  ├─ iso_lookup_factory_v4.3.json             ← **primary** 查表：Dept × Gender × GT × L1（230 entries）
  ├─ iso_lookup_factory_v4.json               ← v4 fallback 查表：Fabric × Dept × GT × L1_code（282 entries，提供 iso_zh / 機種）
  ├─ L1_部位定義_Sketch視覺指引.md               ← VLM Pass 1 system prompt 資料來源
  ├─ PATH2_通用模型_做工推薦Pipeline.md          ← 通用模型 pipeline 總說明
  ├─ PATH2_Phase2_Upload_Pipeline.md          ← Phase 2 上傳 pipeline 實作說明
  └─ README.md                                ← 資料夾本身的 v4.3 說明
scripts/                                      ← **線下規則產線**（10 個腳本，路徑寫死 /sessions/.../mnt/ONY，不可在此 repo 獨立執行）
star_schema/scripts/                          ← **線上 ingest pipeline**（由 .github/workflows/rebuild_master.yml 呼叫）
  ├─ extract_raw_text.py                      ← Step 1：掃 uploads/，抽 PPTX 文字 + PDF callout 圖；支援 --allow-empty / --force
  ├─ extract_unified.py                       ← Step 2a：合併 4 來源 (PPTX 中文 / PDF 英文 / cb / dir5) → unified/{dim,facts}.jsonl
  ├─ vlm_pipeline.py                          ← Step 2b：讀 vlm_raw_extracts.json → ISO 對映 → vlm/facts.jsonl（continue-on-error）
  └─ build_recipes_master.py                  ← Step 3 (--strict)：5 來源合併 → recipes_master + iso_dictionary + l1_standard_38
requirements-pipeline.txt                     ← GitHub Actions 用的 Python 依賴（pymupdf + python-pptx）
techpack-translation-style-guide.md           ← **runtime 規格**：做工 ISO 統一術語 + POM 翻譯;analyze.js / extract_unified / vlm_pipeline 都吃
pom_rules_v55_classification_logic.md         ← v5.5.1 分類邏輯完整文件
pom_rules_pipeline_guide_v2.md                ← scripts/ 產線完整操作手冊（五階段）
網站架構圖.md                                  ← 本 repo 架構全貌（Mermaid）
```

### ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 使用狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender；含 iso_zh / machine / pptx_2025_votes | **fallback** |
| v4.3 | Department × Gender × GT × L1 | 230 | **fine GT 對齊 App UI**（PANTS/LEGGINGS/SHORTS 保留細分）；5 種來源合併；1,328 designs | **primary** |

前端 `isoOptionsFor(v43, v4, filters, l1Code)` 先試 v4.3（性別 + 細 GT），查無對應則退 v4；v4 的 iso_zh/machine 表順便用在 v4.3 的 ISO 顯示。

v4.3 GT 已經對齊 UI，不再需要 `BOTTOM` 粗桶，alias 縮到只剩 `BODYSUIT → TOP` 和 `SWIM_PIECE → TOP` 兩個 UI 有但 v4.3 沒 bucket 的例外（`V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS`）。歷史版本（v3 / v4.1 / v4.2 / full_analysis / knit_pptx_* / woven_*）已陸續移除。

## 兩組獨立的資料 pipeline

| | 線下規則產線 (`scripts/`) | 線上 ingest pipeline (`star_schema/scripts/`) |
|---|---|---|
| **Trigger** | 手動執行 | GitHub Actions：push 到 `data/ingest/uploads/**` |
| **執行環境** | 內部路徑 `/sessions/.../mnt/ONY`（非本 repo 可獨立跑） | `ubuntu-latest` runner，依 `requirements-pipeline.txt` 裝 Python 依賴 |
| **主要輸出** | `pom_rules/*.json`（81 bucket）、`l2_l3_ie/*.json`、`data/l2_visual_guide.json`、`data/l2_decision_trees.json`、`l1_*.json` 等 | `data/recipes_master.json`、`data/iso_dictionary.json`、`data/l1_standard_38.json`、`data/ingest/**` |
| **操作文件** | `pom_rules_pipeline_guide_v2.md` | `General Model_Path2_Construction Suggestion/PATH2_Phase2_Upload_Pipeline.md` |

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

Admin 在前端「📤 上傳 Techpack」丟一份 PDF/PPTX：

1. **上傳路徑（前端自動分流）**：
   - 檔案 ≤ 4.5 MB：`POST /api/ingest_upload`，Vercel 代 commit 到 `data/ingest/uploads/`
   - 檔案 > 4.5 MB：`POST /api/ingest_token` 取 `GITHUB_PAT`，瀏覽器直連 GitHub `PUT contents`
2. **GitHub Actions 觸發**（`.github/workflows/rebuild_master.yml`，`push: paths: data/ingest/uploads/**`）：
   - **Step 1** `extract_raw_text.py` — 掃 uploads/；PDF 讀首頁元資料（季節 / 品牌 / 類型）+ 抽 D-number，PPTX 逐頁取文字，PDF callout 頁面評分後 216 DPI 渲染成 PNG。`--allow-empty` 允許首次空掃，`--force` 忽略已處理重跑。
   - **Step 2a** `extract_unified.py` — **全量**合併 4 來源（PPTX 中文 / PDF 英文 / construction_by_bucket / construction_from_dir5）→ `unified/{dim,facts}.jsonl`。中文 / 英文各自 parse zone + ISO，優先級：PPTX JSON > PPTX txt > 其他。
   - **Step 2b** `vlm_pipeline.py --map-iso` — 讀 `vlm_raw_extracts.json`（手填或 API 預填）→ 對映 200+ ISO 術語 + 30+ zone 名稱 → `data/ingest/vlm/facts.jsonl`。**資料夾是 `vlm/`，不是 `vlm_v1/`**。`continue-on-error`，失敗不擋 build。
   - **Step 3** `build_recipes_master.py --strict` — 合併 5 份來源 → 全量重建：
     - `iso_lookup_factory_v4.3.json`（primary，230 條）
     - `iso_lookup_factory_v4.json`（fallback，282 條）
     - `data/construction_bridge_v6.json`（跨設計 GT × zone 統計）
     - `recipes/*.json`（71 檔）
     - `data/ingest/consensus_v1/entries.jsonl`（275 條 bucket consensus）
     - 加上 `data/ingest/*/facts.jsonl`；L1 必須在 38 標準內、bucket 必須在 taxonomy 內。違規 exit 1，擋住 commit。
     - 輸出：`data/recipes_master.json` + `data/iso_dictionary.json` + `data/l1_standard_38.json`
3. **Commit 回 `main`**：`git rm data/ingest/uploads/*` + `git add` 重建結果，訊息 `chore(data): auto-rebuild recipes_master [skip ci]` 避免無限循環；Vercel 偵測 push → 自動重新部署。

前端在「📤 上傳 Techpack」Modal 內 poll `GET /repos/.../actions/runs?head_sha=<sha>`，依序顯示 5 個 step：**1｜拆解文字 & callout 圖片 → 2a｜統一萃取 (PPTX) → 2b｜VLM 分析 callout (PDF) → 3｜重建 recipes_master → 提交資料**。Actions API 回 403/404（私人 repo / token 缺 `actions:read` scope）會降級成不帶 token 重試，仍失敗時直接顯示 GitHub Actions 連結不再 poll。

## Admin 通道

所有 admin 入口都要 `x-admin-token`（對應 Vercel 的 `ADMIN_TOKEN` 環境變數）；進到前端管理選單先在「⚙ 設定」填。

| 入口 | 做什麼 | 走哪 | Body 大小 |
|---|---|---|---|
| 📝 POM 翻譯表編輯（AdminModal） | 編 `data/pom_dictionary.json`,自動 diff + commit msg | `POST /api/push-pom-dict`(Vercel endpoint) | 小 |
| 📤 上傳 Techpack（UploadModal） | 丟 PDF/PPTX 進 `data/ingest/uploads/`,觸發 Actions 重建 recipes_master | ≤ 4.5 MB: `POST /api/ingest_upload`(Vercel)<br/>\> 4.5 MB: `POST /api/ingest_token` → 瀏覽器直連 GitHub `PUT` | 無實質上限 |
| 🩹 上傳 Patch (JSON)（PatchUploadModal） | 本地跑完 pipeline 後,把 `recipes_master.json` 合併推送,靠 6-field key(`aggregation_level\|gender\|dept\|gt\|it\|l1`)upsert | **全程瀏覽器直連 GitHub**,不經 Vercel endpoint;大檔（>1MB）用 Blob API | 無實質上限 |

所有直連 GitHub 的路徑共用 `/api/ingest_token` 發出的 `GITHUB_PAT`(需 `contents: write`);PAT 只在 admin 瀏覽器 session 裡活著。

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
