# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

## 兩種模式

Header 右上提供「**聚陽模型** / **通用模型**」切換（選擇會記在 `localStorage.stytrix.appMode`）。

| 模式 | 作工建議 | 尺寸 | 全碼 |
|------|----------|------|------|
| **聚陽模型** (`makalot`) | 五階層：L1 部位 → L2 零件 → L3 形狀 → L4 工法 → L5 工段 + IE 秒數 | POM tier（必備 / 建議 / 選配），依 `pom_rules/<bucket>.json` | ✓ 各 size 中位數 + 公差 + 跳碼 |
| **通用模型** (`universal`) | Path 2：VLM 只判 L1，直接查 `v4_lookup_index.json`(Fabric × Department × GT × L1_code) 推 ISO + 機種 + confidence | 僅 5 項基礎大尺寸（上衣：肩/胸/下擺/袖長/身長；下身：腰/臀/前後檔/內長/褲口） | — |

通用模型後端 (`api/analyze.js`) 接 `mode=universal` 時**只跑 Pass 1（L1 偵測）**，省掉 Pass 2 的 decision-tree token。

## 架構

純靜態 HTML + Vercel Edge Function，無 bundler、無 `package.json`。

```
index.html                                    ← 整個 app（React via CDN + 內聯 JS/CSS）
api/analyze.js                                ← Vercel Edge Function，呼叫 Claude Vision
                                                支援 mode=universal → 只跑 Pass 1
data/l2_visual_guide.json                     ← 聚陽模型 Pass 2 用
data/l2_decision_trees.json                   ← 聚陽模型 Pass 2 decision tree
  └─ 由 scripts/build_l2_visual_guide.py / build_l2_decision_trees.py 從 xlsx + md 產生
l1_part_presence_v1.json                      ← 聚陽模型：GT×IT 下每個部位出現率
l1_iso_recommendations_v1.json                ← 聚陽模型：部位名 → ISO 建議
l2_l3_ie/*.json                               ← 聚陽模型：38 個 L1 部位的 L2-L3-IE 規則
pom_rules/*.json                              ← 聚陽模型 POM 規則（gender × garment type × item type）
  └─ 由 scripts/reclassify_and_rebuild.py 產生（81 bucket + _index + pom_names）
pom_rules_v55_classification_logic.md         ← v5.5.1 分類邏輯完整文件（團隊參考）
General Model_Path2_Construction Suggestion/  ← 通用模型 Path 2 資料
  ├─ iso_lookup_factory_v3.json               ← v3 四維查表：Fabric × GT × IT × L1 → ISO + 機種
  ├─ iso_lookup_factory_v4.json               ← v4 查表（GT/IT 對齊 pom_rules v5.5，最新版）
  ├─ v4_lookup_index.json                     ← v4 索引
  ├─ full_analysis_20260420.json              ← 14,225 JSONL + 928 PPTX 全量分析報告
  ├─ l1_code_to_v3_mapping.json               ← L1 code ↔ v3 部位名對照
  ├─ L1_部位定義_Sketch視覺指引.md               ← VLM Pass 1 system prompt 資料來源
  ├─ PATH2_通用模型_做工推薦Pipeline.md          ← Pipeline 總說明書（v4 key + 第八章全量分析摘要）
  └─ woven_*.json                              ← Woven 原始資料 + ISO 推論
```

## 資料管線 (`scripts/`)

這些腳本跑在內部資料環境(路徑寫死 `/sessions/…/mnt/ONY`),非本 repo 可獨立執行,只作為再生 `pom_rules/` 的來源參考。

| 腳本 | 做什麼 | 產出 |
|---|---|---|
| `reclassify_and_rebuild.py` | v5.5.1 全量重分類(Gender/Dept/GT/Fabric)+ rebuild POM 規則 | `pom_rules/*.json` 81 bucket + `_index.json` + `pom_names.json` |
| `run_extract_2025_seasonal.py` | 從 2025 seasonal PDF (FA25/HO25/SP25/SU25) 抽 MC+POM | `mc_pom_2025.jsonl` |
| `run_extract_new.py` | 從 2026 新 PDF (month 5 + FA26/HO26/SP26/SU26/SP23/SP27) 抽 MC+POM | `mc_pom_2026.jsonl` |
| `build_l2_visual_guide.py` / `build_l2_decision_trees.py` | 從 xlsx + md 產生 Pass 2 guide / decision tree | `data/l2_visual_guide.json` / `data/l2_decision_trees.json` |

分類邏輯改了、或新資料進來時的流程:
1. 跑 `run_extract_*.py` 把新 PDF 轉成 `mc_pom_*.jsonl`
2. 跑 `reclassify_and_rebuild.py` 重算 → 覆蓋 `pom_rules/`
3. push 到 main,前端會自動套用新資料

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

