# StyTrix Techpack Creation UI

Techpack Creation + Measurement Spec 合併介面。

## 本機開發

```bash
npm install
npm run dev      # http://localhost:5173
```

## 用 Claude Code 改

```bash
claude code      # 在專案目錄下啟動
# 直接說「改 src/App.jsx 的 filter bar 間距」之類的
```

主要檔案只有一個：`src/App.jsx`（全部邏輯和 UI）。

## 部署到 Cloudflare Pages

### 首次設定（GitHub 連線）

1. Push 到 GitHub repo
2. 打開 [dash.cloudflare.com](https://dash.cloudflare.com) → Workers & Pages → Create
3. 選 Pages → Connect to Git → 選你的 repo
4. Build 設定：
   - Build command: `npm run build`
   - Build output directory: `dist`
5. Deploy

之後每次 push 到 main，Cloudflare 自動重新部署。

### 自訂網域（optional）

Pages 設定 → Custom domains → 加 CNAME 指向 `xxx.pages.dev`
