# PATH2 Phase 2 — PDF/PPTX 上傳 → 自動重建 Pipeline

**狀態**:**部分過期**(本文件最後完整更新 2026-04-23,後續異動見下方 sync 提醒)
**前置**:Phase 1(`data/runtime/recipes_master.json` 統一 schema + 5 層 cascade)已完成。

> **2026-05-09 sync 提醒** — 本文件描述的 2026-04 上傳流程跟現況有以下差異,讀本文時請對照 [`README.md`](../README.md) + [`docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md`](../docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md) 為準:
>
> 1. **Patch Upload Modal(🩹)已退役**(2026-04-23 移除,由 📥 上傳 Pipeline 結果 `ResultsUploadModal` 取代;新通道吃 raw `data/ingest/{metadata,unified,vlm}/*.jsonl` 而非合成的 `recipes_master.json` patch,更符合外部協作實際流程)。**本文件第一章 / 第五章 描述的 Patch Modal 都應視為退役紀錄**。
> 2. **CI workflow 步驟順序更新**:現為 `Step 1 → 2b → 2a → Pre-3(validate buckets)→ 3 → 4a → 4b → 4c`(2b 排在 2a 前讓 unified 合併能吃本 run VLM facts;Step 4 是 Phase 2 derive views)。文中所有「Step 1 → 2a → 2b → 3」順序圖都是 2026-04-23 舊版。
> 3. **`recipes_master.json` 路徑** 從 `data/recipes_master.json` → `data/runtime/recipes_master.json`(2026-05-07 重組)。
> 4. **新增 Step 4** Phase 2 derive views(2026-05-08+):4a 剝 `_m7_*` / 4b 升級 `l2_l3_ie/<L1>.json` schema 並掛 m7_pullon `actuals` / 4c 拆 `data/runtime/designs_index/<EIDH>.json` 3,900 檔。

本文件紀錄 2026-04-23 當時實際跑的上傳流程,前端 admin 面板**過去**提供兩條獨立路徑:

1. **Upload Modal**(📤):原始 PDF/PPTX → GitHub → Actions → `recipes_master.json` 重建 → Vercel 重新部署 — **流程仍在,但 Actions 步驟已加 4a/4b/4c**(見上方 sync 提醒第 2/4 點)
2. ~~**Patch Upload Modal**(🩹):本地先跑完 pipeline,直接把 `recipes_master.json` 合併進 GitHub(**不走 Actions**)~~ — **2026-04-23 退役**,改用 `ResultsUploadModal`(📥)送 raw facts.jsonl

---

## 一、架構總覽

```
                      ┌─ Upload Modal (PDF/PPTX) ────────────────────┐
                      │                                              │
                      │   POST /api/ingest_token   → 取 GITHUB_PAT    │
                      │   瀏覽器 base64 encode                       │
                      │   PUT  api.github.com/repos/.../contents/    │
                      │        data/ingest/uploads/<safe>            │
                      │                                              │
                      │   ↓ push event                               │
                      │                                              │
                      │   GitHub Actions: rebuild_master.yml         │
                      │   Step 1 extract_raw_text.py                 │
                      │   Step 2a extract_unified.py                 │
                      │   Step 2b vlm_pipeline.py (continue-on-err)  │
                      │   Step 3 build_recipes_master.py --strict    │
                      │   Commit rebuilt data/ + [skip ci]           │
                      │                                              │
                      │   ↑ 前端同時輪詢 /actions/runs + /jobs 顯示   │
                      │     每步 ✓/⏭/❌/⚙/○ icon                      │
                      └──────────────────────────────────────────────┘
                      ┌─ Patch Modal (recipes_master.json) ──────────┐
                      │                                              │
                      │   POST /api/ingest_token   → 取 GITHUB_PAT    │
                      │   GET  .../contents/data/recipes_master.json │
                      │        (>1MB 退 Git Blob API)                │
                      │   合併：upsert by                            │
                      │     (aggregation_level, gender, dept,        │
                      │      gt, it, l1)                             │
                      │   PUT  寫回                                  │
                      │                                              │
                      │   → Vercel 重新部署（跳過 Actions）          │
                      └──────────────────────────────────────────────┘
```

兩條路徑都只靠 `/api/ingest_token` 拿 PAT，其餘**全在瀏覽器發給 GitHub**，
繞過 Vercel function 的 **4.5 MB body 上限**（PPTX 常超過）。

---

## 二、後端端點

### `/api/ingest_token`（POST）

檔：`api/ingest_token.js`

```js
// 輸入：header x-admin-token === process.env.ADMIN_TOKEN
// 輸出：{ github_pat: <process.env.GITHUB_PAT> }
// Cache-Control: no-store
```

**唯一職責**：把 `GITHUB_PAT` 發給已驗證的 admin。不做檔案處理、不做
proxy——所有真正的上傳都在前端直連 GitHub。

### ~~`/api/ingest_upload`（已移除）~~

2026-04-24 移除。原本構想是給 ≤ 4.5 MB 的檔走 Vercel 代 commit,
但 admin UI 從頭到尾沒串進來,端點保留了半年都沒被呼叫過。code
review 盤點時發現前端跟 README 對此有落差,決定直接刪 endpoint +
`vercel.json` 條目,上傳路徑統一為 `ingest_token` → 瀏覽器直連 GitHub。

未來若要加「不暴露 PAT」模式,再重建 endpoint 即可。

---

## 三、GitHub Actions Workflow

檔：`.github/workflows/rebuild_master.yml`

**Trigger**：`push` 到 `data/ingest/uploads/**` 或手動 `workflow_dispatch`（含 `--force` 開關）。

**Runner**：`ubuntu-latest`，timeout 30 分鐘，`contents: write` 權限。

**依賴**：`requirements-pipeline.txt` → `pymupdf>=1.23.0`、`python-pptx>=0.6.23`（其他套件如 `anthropic` 依 step 2b 需要再裝）。

### Step 1 — `extract_raw_text.py`

```bash
python star_schema/scripts/extract_raw_text.py \
  --scan-dir data/ingest/uploads \
  --output-dir data/ingest \
  --summary-file /tmp/step1_summary.json \
  --allow-empty \
  ${{ inputs.force == 'true' && '--force' || '' }}
```

**輸入**：`data/ingest/uploads/*.pdf` / `*.pptx`
**輸出**（只對新檔動刀）：
- `data/ingest/metadata/designs.jsonl`（append，D-number 去重）
- `data/ingest/pptx/<name>.txt`（new only）
- `data/ingest/pdf/callout_images/<...>.png`（new only）
- `data/ingest/pdf/callout_manifest.jsonl`（append）

### Step 2a — `extract_unified.py`

```bash
python star_schema/scripts/extract_unified.py \
  --ingest-dir data/ingest \
  --out data/ingest/unified
```

**4 來源 merge**（PPTX 中文、PDF 英文、cb、dir5）→ **全量重建**
`data/ingest/unified/{dim,facts}.jsonl`（不是 append；確保輸出 deterministic）。

### Step 2b — `vlm_pipeline.py`（`continue-on-error`）

```bash
python star_schema/scripts/vlm_pipeline.py \
  --map-iso \
  --out data/ingest/vlm \
  --callout-dir data/ingest/pdf/callout_images \
  --allow-empty
```

**需 secret**：`ANTHROPIC_API_KEY`
**失敗不擋 build**：`continue-on-error: true`，只是少一組 VLM fact。
這一步的失敗**只在 Actions log 可見**，不會 surface 到 commit 訊息或 PR。

### Step 3 — `build_recipes_master.py --strict`

```bash
python star_schema/scripts/build_recipes_master.py --strict
```

**輸入**：`data/ingest/*/facts.jsonl` + 4 本手冊（L1 標準、iso dictionary 等）
**輸出**：
- `data/recipes_master.json`
- `data/iso_dictionary.json`
- `data/l1_standard_38.json`

`--strict`：任何 ingest/taxonomy 違規就 `exit 1`，**擋 commit**——不會把壞資料推回 main。

### Step 4 — Commit & Push

```bash
find data/ingest/uploads -maxdepth 1 -type f ! -name '.gitkeep' \
  -exec git rm --force {} \; 2>/dev/null || true
git add data/recipes_master.json data/iso_dictionary.json data/l1_standard_38.json
git add data/ingest/metadata/designs.jsonl data/ingest/pptx/ data/ingest/unified/ \
        data/ingest/pdf/callout_manifest.jsonl
git diff --cached --quiet || git commit -m "chore(data): auto-rebuild recipes_master [skip ci]"
git push origin HEAD
```

- **uploads/ 處理完刪除**：避免重複觸發 + 避免 repo 長肥
- **`[skip ci]`**：防止 auto-commit 再觸發自己
- **Vercel**：看到 main 有新 commit 自動重新部署，約 1~2 分鐘後前端吃到新資料

---

## 四、前端 Upload Modal（`UploadModal` in `index.html`）

### Flow

1. **驗 Admin Token**：若無，阻擋並提示「請先至 ⚙ 設定 填入」
2. **取 PAT**：`POST /api/ingest_token`，header 帶 `x-admin-token`
3. **base64 encode**：`uploadFile.arrayBuffer()` → chunked `fromCharCode` → `btoa`
   （chunk 8192 bytes 避免 stack overflow on large files）
4. **檔名清洗**：`safeName = name.replace(/[^a-zA-Z0-9._-]/g, '_')`
5. **檢查 existing**：`GET /contents/data/ingest/uploads/<safe>` 拿 `sha`（若存在）
6. **PUT 檔案**：`PUT /contents/data/ingest/uploads/<safe>`
   body: `{ message, content: b64, branch: 'main', sha? }`
   回傳的 `result.commit.sha` 是觸發 Actions 的 commit SHA
7. **切到 CI 階段**：`pollCi(commitSha, pat)`

### `pollCi` — 即時狀態追蹤

**階段 A**：等 workflow run 出現（最多 45 秒，3 秒 interval × 15 次）
```
GET /actions/runs?head_sha=<commitSha>&per_page=1
```
45 秒沒出現 → 顯示「⚠ CI 未啟動（超過 45 秒）」

**階段 B**：輪詢狀態（5 秒 interval × 180 次 = 15 分鐘）
```
GET /actions/runs/<runId>
GET /actions/runs/<runId>/jobs
```
每輪拿 `job.steps`，filter 出已知 5 個 step 名稱 → 渲染成中文 label + icon。

### Step label 對照

| 英文 step name | 中文 UI label |
|---|---|
| `Step 1 — extract raw text & callout images` | `1｜拆解文字 & callout 圖片` |
| `Step 2a — unified extraction` | `2a｜統一萃取 (PPTX)` |
| `Step 2b — VLM callout extraction` | `2b｜VLM 分析 callout (PDF)` |
| `Step 3 — rebuild recipes_master` | `3｜重建 recipes_master` |
| `Commit updated data` | `提交資料` |

Icon：`completed+success → ✓`；`skipped → ⏭`；`failure → ❌`；`in_progress → ⚙`；未開始 → `○`。
Modal 同時跑一個 1 秒 tick 的 timer 顯示 `mm:ss` 倒數。

### 狀態機

```
idle → uploading → ci → done | error
                         ↑_______|
                         「再上傳」按鈕重置回 idle
```

`error` 狀態會把錯誤訊息 concat 在 `statusMsg` 底下（保留上傳成功的 log），
`done` 狀態顯示 `✓ Pipeline 全部完成！`。

---

## 五、前端 Patch Upload Modal（`PatchUploadModal` in `index.html`）

**用途**：本地已經跑完完整 pipeline（拿到一份新版 `recipes_master.json`），
想直接合併進 GitHub，**不走 Actions**。適用情境：

- Pipeline script 本地改過，想先測試 output 再決定要不要正式跑 Actions
- 只補幾筆資料，不想等 Actions 重建
- Actions 壞了的 workaround

### Flow

1. 取 PAT（同上）
2. 讀使用者選的 JSON 檔；驗證 `entries` 是陣列
3. 下載現有 `data/recipes_master.json`：
   - 先試 `GET /contents/...`（≤ 1 MB 才會附 `content`）
   - 大檔退 `GET /git/blobs/<sha>`
4. **Upsert merge**：
   ```js
   key = aggregation_level + gender + dept + gt + it + l1
   map = Map(existing.entries by key)
   patch.entries.forEach(e => map.set(key(e), e))  // 同 key 覆蓋，新 key 插入
   merged.entries = Array.from(map.values())
   ```
5. 顯示合併統計：`原 N 筆，新增 X、更新 Y → 合計 M 筆`
6. `PUT` 寫回 `data/recipes_master.json`，帶原 sha

### Commit message

`chore(data): merge recipes_master via admin`

不帶 `[skip ci]`——但因為沒改動 `data/ingest/uploads/**`，workflow 的
trigger path 不匹配，Actions 還是不會跑。只有 Vercel 重新部署會觸發。

---

## 六、環境變數與 secrets

### Vercel Project Settings

| 變數 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | `api/analyze.js` 呼叫 Claude Vision |
| `ADMIN_TOKEN` | 所有 admin 端點共享的驗證 token |
| `GITHUB_PAT` | `/api/ingest_token` 發出；需 `contents: write` scope |

### GitHub Actions Secrets（repo settings → Secrets）

| 變數 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | workflow Step 2b VLM pipeline |
| `GITHUB_TOKEN` | 自動注入；workflow 最後 push 用 |

---

## 七、邊界條件與保護

| 場景 | 處理方式 | 位置 |
|---|---|---|
| Admin Token 錯誤 | `/api/ingest_token` 回 401，前端顯示「Admin Token 錯誤」 | `api/ingest_token.js:11` |
| 檔名有特殊字元 | `[^a-zA-Z0-9._-]` 替換為 `_` | `index.html` `UploadModal.handleUpload` |
| 檔案已存在 | 先 GET 拿 `sha`，PUT 帶 `sha` 強制覆寫 | 同上 |
| 檔案 > 1 MB（Patch 下載） | GET 沒 `content` → 退 `/git/blobs/<sha>` | `PatchUploadModal.handlePatch` |
| 上傳重複 D-number | `extract_raw_text.py` D-number 去重，不加 `--force` 跳過 | workflow Step 1 |
| VLM API 失敗 | `continue-on-error: true`；少一組 fact，但 pipeline 繼續 | workflow Step 2b |
| `--strict` 失敗 | `exit 1`；commit/push 不執行，Vercel 不重部署 | workflow Step 3 |
| 惡意上傳非 techpack 檔 | UI `accept=".pdf,.pptx"`；後續 D-number 格式驗證 | `index.html`；pipeline |
| Actions 未啟動 | 前端 45 秒內輪詢不到 workflow run → 顯示警告 | `pollCi` 階段 A |
| Actions 超時 | 15 分鐘輪詢極限 → 顯示「追蹤逾時」；Actions 仍會自己跑完 | `pollCi` 階段 B |
| Actions 失敗 | Modal 顯示 `❌ Pipeline 失敗 (conclusion)`，步驟列表保留給 debug | `pollCi` |
| `recipes_master.json` 格式錯誤（Patch） | `JSON.parse` 抓 / `entries` 不是陣列時拒絕 | `PatchUploadModal` |

---

## 八、與其他系統的邊界

- **不碰**：`api/analyze.js`（VLM 部位偵測，與做工推薦無關）
- **不碰**：`l2_l3_ie/`、`pom_rules/`（五階層與聚陽模式）
- **輸入**：`data/ingest/uploads/*.pdf|*.pptx`（僅此一入口）
- **輸出**：只有 `data/recipes_master.json`、`data/iso_dictionary.json`、
  `data/l1_standard_38.json` 被前端 fetch；`data/ingest/` 其餘是 pipeline
  內部 staging

---

## 九、Source of Truth

本文件描述的內容散佈在以下檔案，任何歧異**以程式碼為準**：

- 端點：`api/ingest_token.js`
- Workflow：`.github/workflows/rebuild_master.yml`
- Pipeline scripts：`star_schema/scripts/{extract_raw_text,extract_unified,vlm_pipeline,build_recipes_master}.py`
- 前端 UI：`index.html` 內 `UploadModal` / `PatchUploadModal` / `CI_STEP_LABELS` / `mergeRecipesMaster` / `PATCH_TARGET`
- 依賴：`requirements-pipeline.txt`
- Vercel config：`vercel.json`

改了實作**一定要**同步更新本文件，尤其是：

- workflow step 名稱 → 影響前端 `CI_STEP_LABELS` 映射（CI 步驟顯示會漏）
- `data/ingest/` 子目錄結構 → 影響 workflow `git add` 清單
- `recipes_master.json` 的 merge key 欄位 → 影響 `PatchUploadModal.mergeRecipesMaster`
