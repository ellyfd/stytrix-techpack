# Techpack Creation — Know-How 規則引擎

## 架構

```
GitHub repo
├── data/                          ← 靜態 JSON（domain knowledge）
│   ├── l1_part_presence_v1.json   ← 哪些部位該顯示
│   ├── l1_iso_recommendations_v1.json  ← ISO 推薦+信心
│   ├── consensus_rules.json       ← 275 條做工規則
│   └── gender_gt_pom_rules.json   ← 尺寸表預填規則
│
├── lib/
│   └── techpack-engine.js         ← 規則引擎核心（純函式，無 UI）
│
├── api/                           ← Vercel API Routes（可選）
│   └── techpack/
│       ├── parts.js               ← GET /api/techpack/parts?gt=TOP&it=TOPS
│       └── recommend.js           ← GET /api/techpack/recommend?gt=TOP&it=TOPS&l1=領
│
└── components/                    ← React UI 直接 import engine
    └── TechpackStep1.jsx
```

## 部署

JSON commit 進 repo → Vercel build 時打包 → 前端直接 import 或走 API route。
不需要額外 DB，JSON 總量 < 2MB，Vercel edge 可以直接 serve。
