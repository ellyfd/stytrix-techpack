---
name: place-file
description: Given a new file (path, name, or description of contents), walk CLAUDE.md Part A's decision tree and recommend the correct folder. Use when the user is about to add a new file and unsure where it goes, or has dropped a file at repo root that may belong elsewhere. Covers data/, pom_rules/, l2_l3_ie/, General Model_Path2_Construction Suggestion/, scripts/, star_schema/scripts/, api/, and root-level .md conventions.
---

# place-file — 新檔資料夾分工決策

本 skill 實作 `CLAUDE.md` Part A 的 flowchart。呼叫方式：使用者給一份
新檔（路徑、檔名或內容描述），skill 走決策樹，回報該進哪個資料夾。

## 觸發

- 使用者問「這個檔放哪？」「新資料該放 data/ 還是根目錄？」
- 使用者在 repo 根目錄新增可疑檔（非跨模組 `.md`）
- PR review 時看到檔放錯位置

## 決策樹（逐題問到底）

```
這份新檔是什麼？
│
├─ Q1. 線上系統會直接讀取嗎？（index.html fetch / api/*.js readFileSync）
│       Yes → 【data/】
│             例：l2_visual_guide.json, recipes_master.json, pom_dictionary.json
│
├─ Q2. 是 POM 規則（bucket）嗎？
│       Yes → 【pom_rules/】（由 scripts/reclassify_and_rebuild.py 寫入，
│             不要手動新增）
│             命名：<gender>_<dept>_<gt>.json
│
├─ Q3. 是 L1 部位的 L2-L3-IE 工時規則嗎？
│       Yes → 【l2_l3_ie/】（38 個檔，每個 L1 代號一檔）
│             命名：<L1代號>.json（如 AE.json, WB.json）
│
├─ Q4. 是通用模型（Path 2）的 ISO / knit / woven 資料？
│       Yes → 【General Model_Path2_Construction Suggestion/】
│             例：iso_lookup_factory_v*.json
│
├─ Q5. 是 construction recipe / pattern（做工配方）？
│       ├─ Yes, 由 PATH2 pipeline 產生 → 【recipes/】（根目錄 72 檔，
│       │                                  build_recipes_master.py 實際會吃）
│       └─ Yes, 臨時一次性 → ❌ 不要進 repo，放 Notion / Drive
│
├─ Q6. 是 Ingest pipeline 的 staging 檔？
│       Yes → 【data/ingest/】下面依型態：
│             - PDF/PPTX 原始上傳 → uploads/
│             - 去重 metadata → metadata/
│             - callout 圖 → pdf/callout_images/
│             - 合併 fact → unified/ 或 consensus_v1/ / ocr_v1/
│
├─ Q7. 是跨模組都要讀的規格文件（.md）？
│       Yes → 【repo 根目錄】
│             例：L1_部位定義_Sketch視覺指引.md、pom_rules_*_guide.md、
│                 網站架構圖.md
│
├─ Q8. 是子系統（PATH2 / scripts / star_schema）內部文件？
│       Yes → 【該子系統資料夾裡】
│             例：General Model_Path2_.../PATH2_*.md
│
├─ Q9. 是線下規則產線 python script？
│       Yes → 【scripts/】（路徑寫死內部 /sessions/.../mnt/ONY，
│             跑在內部環境，非本 repo 獨立執行）
│
├─ Q10. 是線上 ingest pipeline script（給 GitHub Actions 跑）？
│       Yes → 【star_schema/scripts/】
│
├─ Q11. 是 Vercel Node function？
│       Yes → 【api/】（檔名 kebab-case，如 api/push-pom-dict.js）
│             記得同步更新 vercel.json 的 maxDuration / includeFiles
│
└─ 判斷不出來？
        先在 PR 裡問，不要直接 merge。（CLAUDE.md 硬性規則）
```

## 版本化檢查

若檔名含版本（v4 / v4.3 / 20260420）：

1. **主用版本**：檔名結尾 `_v{N}`（例：`iso_lookup_factory_v4.3.json`）
   README 的「ISO 查表版本演進」表必須同步標 **primary / fallback / deprecated**
2. **日期戳版本**（`full_analysis_20260420.json`）只作一次性 snapshot
3. 新版進來時，**舊版不立刻刪**，改標 `fallback` 或 `deprecated`，下輪 `/clean-orphan` 跑 gate 再處理
4. 同概念 v1/v2 共存時，README 必須註明「為什麼 v1 還留著」

## 命名禁忌

- `recipes/` 是活檔 — 根目錄 72 檔由 `star_schema/scripts/build_recipes_master.py` 每次 CI 掃過，要新增 recipe 放這裡（不是 `construction_recipes/`，那個不存在）。
- 根目錄不要再新增 `.json` / `.jsonl`。**新檔直接進 `data/`**（`l1_part_presence_v1.json` / `l1_iso_recommendations_v1.json` 已於 2026-04-23 搬入 data/）。

## 回報格式

```
📁 建議放：<folder>/<filename>

理由（對應決策樹）：
- Q<N>: <具體答案>
- 命名規則：<若適用>

配套動作（若有）：
- [ ] 更新 README.md 的檔案樹
- [ ] 更新 vercel.json（若是 api/*.js）
- [ ] 更新 ISO 查表版本表（若是 iso_lookup_factory_v*）

不適用項目請跳過。
```

如使用者堅持放別處，回報「⚠ 與 CLAUDE.md Part A 偏離，請在 PR 說明原因」，但不強制擋。
