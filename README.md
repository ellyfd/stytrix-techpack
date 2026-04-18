# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。
線上版：https://stytrix-techpack.vercel.app

## 架構

純靜態 HTML + Vercel Edge Function，無 bundler、無 `package.json`。

```
index.html              ← 整個 app（React via CDN + 內聯 JS/CSS）
api/analyze.js          ← Vercel Edge Function，呼叫 Claude Vision
data/l2_visual_guide.json
  └─ 由 scripts/build_l2_visual_guide.py 從 xlsx + md 產生
l1_part_presence_v1.json / l1_iso_recommendations_v1.json
l2_l3_ie/*.json         ← 38 個 L1 部位的 L2-L3-IE 規則
pom_rules/*.json        ← POM 規則（依 gender × garment type × item type）
```

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
