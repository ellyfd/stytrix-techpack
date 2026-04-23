# PATH2 Phase 2 — PDF/PPT 自動上傳 → 資料更新 Pipeline

**版本**：Draft v1.0  
**日期**：2026-04-23  
**前置**：Phase 1（`data/recipes_master.json` 統一 schema + 5 層 cascade）已完成。

---

## 目標

使用者上傳新的 Techpack PDF 或 PPTX（一季或多款）→ 自動跑 3 段 pipeline →
`data/recipes_master.json` 自動更新並部署到 Vercel，前端立即反映新樣本。

**不需要本地環境**、**不需要手動跑 script**。

---

## 一、架構總覽

```
[使用者]  Upload PDF / PPTX
    │
    ▼
[Vercel Serverless: api/ingest.js]
    │  接收檔案 → 寫進 GitHub repo
    │  (git push to data/ingest/uploads/)
    ▼
[GitHub Actions: .github/workflows/rebuild_master.yml]
    │
    ├── Step 1: extract_raw_text.py --scan-dir data/ingest/uploads/
    │          輸出 → data/ingest/unified/facts.jsonl (append)
    │                  data/ingest/vlm/callout_images/ (PNG)
    │
    ├── Step 2a: extract_unified.py
    │          輸出 → data/ingest/unified/facts.jsonl (append)
    │
    ├── Step 2b: vlm_pipeline.py --api-key $ANTHROPIC_API_KEY
    │          輸出 → data/ingest/vlm_v1/facts.jsonl (append)
    │
    ├── Step 3: python scripts/build_recipes_master.py --strict
    │          輸出 → data/recipes_master.json
    │                  data/iso_dictionary.json
    │                  data/l1_standard_38.json
    │
    └── git commit + push → Vercel 自動重部署
```

---

## 二、三段 Script 職責對照

| Step | Script | 輸入 | 輸出 | 備註 |
|------|--------|------|------|------|
| 1 | `star_schema/scripts/extract_raw_text.py` | PDF/PPTX 目錄 | `metadata/designs.jsonl`, `pptx/facts_raw/`, `pdf/callout_images/` | D-number 去重，已處理跳過 |
| 2a | `star_schema/scripts/extract_unified.py` | `star_schema/data/ingest/` | `data/ingest/unified/facts.jsonl` | 4 來源 merge：PPTX 中文、PDF 英文、cb、dir5 |
| 2b | `star_schema/scripts/vlm_pipeline.py` | callout PNG + Glossary | `data/ingest/vlm_v1/facts.jsonl` | 需 `ANTHROPIC_API_KEY`；PoC 已驗可行 |
| 3 | `scripts/build_recipes_master.py` | `data/ingest/*/facts.jsonl` + 4 本手冊 | `data/recipes_master.json` | `--strict` 若失敗則 exit 1,不 push 壞資料 |

> **注意**：`star_schema/scripts/` 是提取工具原始碼，與 repo 根目錄的 `scripts/`（build 工具）分開。
> Phase 2 Actions workflow 需要同時呼叫兩個路徑的 script。

---

## 三、GitHub Actions Workflow

檔案：`.github/workflows/rebuild_master.yml`

```yaml
name: Rebuild recipes_master

on:
  push:
    paths:
      - "data/ingest/uploads/**"   # 觸發條件：有新上傳
  workflow_dispatch:               # 手動觸發（用於回跑）
    inputs:
      force:
        description: "Force re-extract all (ignore cache)"
        default: "false"

jobs:
  rebuild:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install pdfplumber python-pptx pillow anthropic

      - name: Step 1 — extract raw text & callout images
        run: |
          python star_schema/scripts/extract_raw_text.py \
            --scan-dir data/ingest/uploads \
            --output-dir data/ingest \
            --summary-file /tmp/step1_summary.json \
            --allow-empty \
            ${{ github.event.inputs.force == 'true' && '--force' || '' }}
          cat /tmp/step1_summary.json

      - name: Step 2a — extract unified facts
        run: |
          python star_schema/scripts/extract_unified.py \
            --ingest-dir data/ingest \
            --out data/ingest/unified

      - name: Step 2b — VLM callout extraction
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python star_schema/scripts/vlm_pipeline.py \
            --map-iso \
            --callout-dir data/ingest/pdf/callout_images \
            --out data/ingest/vlm_v1 \
            --api-key "$ANTHROPIC_API_KEY" \
            --allow-empty
        continue-on-error: true   # VLM 失敗不擋整條 pipeline，只是少 VLM 資料

      - name: Step 3 — rebuild recipes_master
        run: python scripts/build_recipes_master.py --strict

      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/recipes_master.json data/iso_dictionary.json data/l1_standard_38.json
          git add data/ingest/unified/facts.jsonl data/ingest/vlm_v1/facts.jsonl
          git diff --cached --quiet || git commit -m "chore(data): auto-rebuild recipes_master [skip ci]"
          git push
```

> `[skip ci]` 防止 push 後再次觸發 workflow loop。

---

## 四、上傳端點（Vercel Serverless）

新增 `api/ingest.js`（或 `api/ingest_upload.js`，與現有 `api/analyze.js` 平行）。

**職責**：接收 multipart/form-data → 驗證副檔名 → 呼叫 GitHub Contents API 把檔案存進 `data/ingest/uploads/{season}/{filename}` → GitHub push 自動觸發 Actions。

```javascript
// api/ingest_upload.js  (skeleton)
import { Octokit } from "@octokit/rest";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();

  const { filename, content_b64, season } = await parseMultipart(req);
  const ext = filename.split(".").pop().toLowerCase();
  if (!["pdf", "pptx"].includes(ext))
    return res.status(400).json({ error: "Only PDF/PPTX accepted" });

  const octokit = new Octokit({ auth: process.env.GITHUB_PAT });
  const path = `data/ingest/uploads/${season || "misc"}/${filename}`;

  await octokit.repos.createOrUpdateFileContents({
    owner: "ellyfd",
    repo:  "stytrix-techpack",
    path,
    message: `chore(ingest): upload ${filename}`,
    content: content_b64,   // base64-encoded file bytes
  });

  res.json({ ok: true, path, message: "Pipeline will rebuild in ~2 min" });
}
```

**環境變數（Vercel Dashboard 設定）**：

| 變數 | 說明 |
|------|------|
| `GITHUB_PAT` | 有 `contents:write` 的 Personal Access Token（或 GitHub App） |
| `ANTHROPIC_API_KEY` | Actions secret（已有 analyze.js 用的 key 可共用） |

---

## 五、UI 入口（index.html）

在現有的 Settings 或 Admin panel 加一個「上傳新 Techpack」按鈕：

```
[上傳 PDF / PPTX]
選擇檔案：________  季別：[SP26 ▾]
[送出]

上傳成功！Pipeline 約 2 分鐘後自動更新資料庫。
```

送出後 call `fetch('/api/ingest_upload', { method:'POST', body: formData })`。

**不需要輪詢**：Vercel 重部署後頁面 reload 或下次 fetch `recipes_master.json` 就拿到新資料（Vercel 靜態檔有 CDN cache；deploy 後 cache busted）。

---

## 六、邊界條件與保護

| 場景 | 處理方式 |
|------|----------|
| 上傳重複 D-number | `extract_raw_text.py --force` 不加時自動跳過，不重算 |
| VLM API 失敗 | Step 2b 設 `continue-on-error: true`；`build_recipes_master.py` 照跑舊 VLM 資料 |
| `--strict` 失敗（zone 對不齊/L1 不在 38 碼）| Actions exit 1，不 push 壞資料；Vercel 不重部署 |
| 惡意上傳非 techpack 檔 | Serverless 端只允許 `.pdf` / `.pptx`；script 端 D-number 格式驗證 |
| Actions timeout（30 min）| 大批量上傳拆批次；一次不超過 20 款 |

---

## 七、實作優先順序

| Priority | 項目 | 依賴 | 狀態 |
|----------|------|------|------|
| P0 | `extract_raw_text.py` 加 `--summary-file`、`--allow-empty`、default 改 repo-root `data/ingest/` | 無 | ✅ 完成 |
| P0 | `extract_unified.py` 加 `--ingest-dir` / `--out` / `--classification-file` / `--legacy-pptx-json-dir` CLI args | 無 | ✅ 完成 |
| P0 | `vlm_pipeline.py` 加 `--callout-dir` / `--out` / `--classification-file` / `--scan-dir` / `--api-key` / `--allow-empty` CLI args;順便修 `select_pilot_batch` 的 forward-reference bug | 無 | ✅ 完成 |
| P0 | `.github/workflows/rebuild_master.yml` 初版 | 上面 3 條 script 就緒 | ⏳ 待做 |
| P1 | `vlm_pipeline.py --api-key` 自動模式(目前 PoC 手動讀圖) | `vlm_poc/vlm_poc_report.md` §5 | ⏳ 待做 |
| P1 | `api/ingest_upload.js` Vercel 端點 | `GITHUB_PAT` secret | ⏳ 待做 |
| P2 | UI「上傳」按鈕 + 狀態提示 | `api/ingest_upload.js` | ⏳ 待做 |
| P2 | 上傳後 webhook 或 SSE 通知前端「資料已更新」 | 選做 | ⏳ 待做 |

---

## 八、與現有架構的邊界

- **不碰**：`api/analyze.js`（VLM 部位偵測，與做工推薦無關）
- **不碰**：`l2_l3_ie/`、`pom_rules/`（五階層與聚陽模式）
- **`data/recipes_master.json` 是唯一 output artifact**：前端永遠只讀這一個檔，pipeline 怎麼跑都無感
- **原始上傳檔**（PDF/PPTX）存在 `data/ingest/uploads/`，不直接被前端 fetch；只有 `data/*.json` 被前端讀

---

*PATH2 Phase 2 Draft v1.0 | 2026-04-23*
