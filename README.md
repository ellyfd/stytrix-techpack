# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

## 兩種模式

Header 右上提供「**聚陽模型** / **通用模型**」切換（選擇會記在 `localStorage.stytrix.appMode`）。

| 模式 | 作工建議 | 尺寸 | 全碼 |
|------|----------|------|------|
| **聚陽模型** (`makalot`) | 五階層：L1 部位 → L2 零件 → L3 形狀 → L4 工法 → L5 工段 + IE 秒數 | POM tier（必備 / 建議 / 選配），依 `pom_rules/<bucket>.json` | ✓ 各 size 中位數 + 公差 + 跳碼 |
| **通用模型** (`universal`) | Path 2：VLM 只判 L1，雙表查 ISO：先 `iso_lookup_factory_v4.3.json`(Department × **Gender** × GT × L1,**fine GT 對齊 UI 下拉選單**,含性別差異,130 entries / 1,328 designs)再退 `iso_lookup_factory_v4.json`(Fabric × Department × GT × L1_code,覆蓋完整 + 提供 iso_zh/機種) | 僅 5 項基礎大尺寸（上衣：肩/胸/下擺/袖長/身長；下身：腰/臀/前後檔/內長/褲口） | — |

通用模型後端 (`api/analyze.js`) 接 `mode=universal` 時**只跑 Pass 1（L1 偵測）**，省掉 Pass 2 的 decision-tree token。

## 架構

純靜態 HTML + Vercel Edge Function，無 bundler、無 `package.json`。

```
index.html                                    ← 整個 app（React via CDN + 內聯 JS/CSS）
LOGO.png                                      ← Header logo 圖檔
api/analyze.js                                ← Vercel Edge Function，呼叫 Claude Vision
                                                支援 mode=universal → 只跑 Pass 1
data/                                         ← 資料檔(分析產出 + Pass 2 用)
  ├─ l2_visual_guide.json                     ← 聚陽模型 Pass 2 用
  ├─ l2_decision_trees.json                   ← 聚陽模型 Pass 2 decision tree
  │   └─ 由 scripts/build_l2_visual_guide.py / build_l2_decision_trees.py 產生
  ├─ grading_patterns.json                    ← v6 跳檔 pattern(33 combos / 1,016 POM families,基碼頁用)
  ├─ bodytype_variance.json                   ← v6 Body Type 差異(33 comparisons,內部參考)
  ├─ client_rules.json                        ← v6 跨品牌規則(5 cross-brand combos,內部參考)
  ├─ all_designs_gt_it_classification.json    ← v6 GT×IT 分類(1,328 designs,內部參考)
  └─ construction_bridge_v6.json              ← v6 construction bridge(10 GTs 全品類,通用模式用)
l1_part_presence_v1.json                      ← 聚陽模型：GT×IT 下每個部位出現率
l1_iso_recommendations_v1.json                ← 聚陽模型：部位名 → ISO 建議
l2_l3_ie/*.json                               ← 聚陽模型：38 個 L1 部位的 L2-L3-IE 規則
pom_rules/*.json                              ← POM 規則(12,038 全量 v6.0,81 bucket × gender × dept × gt)
  └─ 由 scripts/reclassify_and_rebuild.py 產生(+ _index.json + pom_names.json)
pom_rules_v55_classification_logic.md         ← v5.5.1 分類邏輯完整文件（團隊參考）
pom_rules_pipeline_guide.md                   ← pom_rules 產線操作指南(run/rebuild/驗證)
General Model_Path2_Construction Suggestion/  ← 通用模型 Path 2 資料
  ├─ iso_lookup_factory_v4.3.json             ← **primary** 查表:Dept × Gender × GT × L1(fine GT / 130 entries / 5 來源合併)
  ├─ iso_lookup_factory_v4.json               ← v4 查表(Fabric × Dept × GT × L1_code)— 前端 fallback,提供 iso_zh/機種
  ├─ full_analysis_20260420.json              ← 14,225 JSONL + 928 PPTX 全量分析報告
  ├─ L1_部位定義_Sketch視覺指引.md               ← VLM Pass 1 system prompt 資料來源
  ├─ PATH2_通用模型_做工推薦Pipeline.md          ← Pipeline 總說明書
  ├─ README.md                                 ← 資料夾本身的 v4.3 說明
  ├─ knit_pptx_construction_context.json      ← 47 款 Knit PPTX(2026/5)zone 做工紀錄(regen 備用)
  └─ woven_*.json                              ← Woven 原始資料 + ISO 推論(v4 woven 側來源)
```

### ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 使用狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender;含 iso_zh/machine/pptx_2025_votes | **fallback** |
| v4.3 | Department × Gender × GT × L1 | 130 | **fine GT 對齊 App UI**(PANTS/LEGGINGS/SHORTS 保留細分);5 種來源合併(PPTX 中文 / PDF 英文 / JSONL iso_codes / Raw PDF / OCR callout);1,328 designs | **primary** |

前端 `isoOptionsFor(v43, v4, filters, l1Code)` 先試 v4.3(性別 + 細 GT),查無對應則退 v4;v4 的 iso_zh/machine 表順便用在 v4.3 的 ISO 顯示。

v4.3 GT 已經對齊 UI,不再需要 `BOTTOM` 粗桶,alias 縮到只剩 `BODYSUIT → TOP` 和 `SWIM_PIECE → TOP` 兩個 UI 有但 v4.3 沒 bucket 的例外(`V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS`)。歷史版本(v3 / v4.1 / v4.2 / v4_lookup_index / l1_code_to_v3_mapping / pptx_vs_v3_analysis)已於 2026-04-20 移除。

## 資料管線 (`scripts/`)

這些腳本跑在內部資料環境(路徑寫死 `/sessions/…/mnt/ONY`),非本 repo 可獨立執行,只作為再生 `pom_rules/` 的來源參考。詳細操作見 `pom_rules_pipeline_guide.md`。

| 腳本 | 做什麼 | 產出 |
|---|---|---|
| `reclassify_and_rebuild.py` | v6.0 全量重分類(Gender/Dept/GT/Fabric)+ rebuild POM 規則 | `pom_rules/*.json` 81 bucket + `_index.json` + `pom_names.json` |
| `rebuild_profiles.py` | 重建 profile union(measurement_profiles_union.json),reclassify 的上游 | profile union(內部路徑) |
| `enforce_tier1.py` | pom_rules 產線後強制 tier-1 rule(必備 POM 下限) | 覆蓋 pom_rules/*.json |
| `fix_sort_order.py` | 修 bucket 內 pom_sort_order 欄位排序 | 覆蓋 pom_rules/*.json |
| `run_extract_2025_seasonal.py` | 從 2025 seasonal PDF (FA25/HO25/SP25/SU25) 抽 MC+POM | `mc_pom_2025.jsonl` |
| `run_extract_new.py` | 從 2026 新 PDF (month 5 + FA26/HO26/SP26/SU26/SP23/SP27) 抽 MC+POM | `mc_pom_2026.jsonl` |
| `build_l2_visual_guide.py` / `build_l2_decision_trees.py` | 從 xlsx + md 產生 Pass 2 guide / decision tree | `data/l2_visual_guide.json` / `data/l2_decision_trees.json` |

分類邏輯改了、或新資料進來時的流程:
1. 跑 `run_extract_*.py` 把新 PDF 轉成 `mc_pom_*.jsonl`
2. 跑 `rebuild_profiles.py` 合併 profile union
3. 跑 `reclassify_and_rebuild.py` 重算 → 覆蓋 `pom_rules/`
4. 跑 `enforce_tier1.py` + `fix_sort_order.py` 做後處理
5. push 到 main,前端會自動套用新資料

## 本機預覽

直接用任何 static server 指到專案根目錄即可，例如：

```bash
python3 -m http.server 5173
# 或
npx serve .
```

`/api/analyze` 本機無法執行（需 Vercel runtime）；要測 AI 功能請部署到 Vercel preview。

## 部署

GitHub push → Vercel 自動建置（preview / production）。
環境變數：`ANTHROPIC_API_KEY`（在 Vercel Project Settings）。

