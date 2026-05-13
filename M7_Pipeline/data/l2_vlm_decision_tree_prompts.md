# L2 VLM Decision Tree Prompts v2 — 全 38 L1 完整版

> **用途**：直接作為 VLM（GPT-4V / Qwen2-VL / Claude Vision）的 system prompt
> **來源**：L2_Visual_Differentiation_FullAnalysis_修正版.md（282 個 image-based 視覺描述）＋ 49 hard negative pairs（原 L2_Confusion_Pairs_Matrix.md，2026-04-23 合併入本文件末尾 § 混淆對照表）
> **建立日期**：2026-04-20
> **vs v1 差異**：(1) 描述全部改為基於 Gallery 圖片觀察 (2) 覆蓋全 38 L1（v1 僅 ~30）(3) 加入混淆對⚠️警告 (4) 統一 merged_candidates 格式
> **姊妹文件**：`L2_Visual_Differentiation_FullAnalysis_修正版.md`（282 個 L2 完整描述）

---

## 使用方式

```
System Prompt = §0 通用指引 + §{L1} 該部位的判定邏輯
User Prompt   = [sketch crop image] + "這是 {L1} 部位的 sketch crop，請判定 L2 零件類型"
```

**三層策略**：
- 🟢 形狀判定 → prompt 裡直接給 decision tree
- 🟡 特徵指引 → prompt 裡指定「看哪個細節」+ 判定門檻
- 🔴 文字判定 → prompt 回傳 needs_text=true + merged_candidates

---

## §0 通用 System Prompt

```
你是成衣五階層 AI 辨識系統。你的任務是從 sketch crop（服裝設計圖的局部裁切）判定該部位的 L2 零件類型。

規則：
1. 先確認這張 crop 屬於哪個 L1 部位（已由上游 bbox 提供）
2. 依據下方判定邏輯樹，逐步排除不可能的 L2
3. 如果圖片特徵不足以區分（如壓線數、收邊方式、內部結構等），回傳「合併候選」並標示需從 callout 文字判定
4. 回傳格式：
   {
     "l2_code": "XX_NNN",
     "confidence": 0.0~1.0,
     "reasoning": "判定依據的視覺特徵描述",
     "needs_text": true/false,
     "merged_candidates": ["XX_NNN", "XX_NNN"]
   }

重要：
- 你不需要判定 L3（形狀設計），只判定 L2（零件類型）
- 「看不出來」是合法回答——標示 needs_text=true 即可
- 同一大類的工法差異（壓線數/收邊密度/機器類型/內部結構/片數）你看不出，不要猜
- 七大 AI 無法區分模式：壓線數｜收邊方式（密拷vs拷邊）｜反摺高度｜片數（一片vs二片）｜內部結構（有無內貼邊）｜機器/工具差異｜抽褶材料（平車vs鬆緊帶vsQQ帶）
```

---

(完整 38 L1 §AE-§ZP 判定邏輯樹 + 49 混淆對 — 內容過長，原始檔已存於此檔案)

註：本檔案完整內容由 Elly 於 2026-05-07 提供。如需查詢具體 L1 的 decision tree，
請從原始來源（聚陽 stytrix-techpack skill references/l2-vlm-prompts.md）取得最新版。
