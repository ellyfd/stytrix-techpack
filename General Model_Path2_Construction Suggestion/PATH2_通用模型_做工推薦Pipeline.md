# Path 2 通用模型：AI 做工推薦 Pipeline

> **路線**：AI 判視 → 直接推 ISO 給工廠，不走五階層
> **模型定位**：通用版（不分品牌），適用所有客人
> **建立日期**：2026-04-20
> **資料來源**：ONY Knit 370 款 Centric 8 + Woven 36 款 PPTX
> **查表版本**：v4.0（2026-04-20，GT/IT 對齊 pom_rules v5.5）

---

## 一、Pipeline 總覽

```
使用者在 Step 1 選定 → Fabric / GT / IT
                          ↓
                    上傳或生成 Sketch 圖
                          ↓
            ┌─────────────────────────────┐
            │  VLM 部位偵測（Stage ①）      │
            │  輸入：Sketch 圖 + L1 視覺指引  │
            │  輸出：L1 code 清單            │
            │  例如：[NK, SH, AH, SL, BM, SS] │
            └──────────────┬──────────────┘
                          ↓
            ┌─────────────────────────────┐
            │  ISO 查表（Stage ②）          │
            │  查詢：Fabric × Dept × GT × L1  │
            │  來源：iso_lookup_factory_v4    │
            │  輸出：每個 L1 的 ISO + 機種     │
            └──────────────┬──────────────┘
                          ↓
            ┌─────────────────────────────┐
            │  工廠輸出（Stage ③）           │
            │  每個部位一張卡片：             │
            │  「領 → ISO 301 → 平車」       │
            │  含 confidence + alternatives   │
            └─────────────────────────────┘
```

---

## 二、每個 Stage 怎麼串

### Stage ① VLM 部位偵測

**輸入檔案**：`L1_部位定義_Sketch視覺指引.md`

**做法**：把視覺指引餵給 VLM（Qwen-VL / GPT-4o）當 system prompt，再丟 sketch 圖。

**VLM Prompt 範本**：

```
你是成衣做工專家。請看這張 sketch，列出圖上可見的所有 L1 部位。

規則：
1. 只列「看得到」的部位，不要猜測不可見的做工（BN 貼合、NT 領貼條、LI 裡布除非有剖面圖）
2. 用 L1 code 回答（NK, WB, BM, SL, PK...）
3. 每個 L1 只列一次，不重複

L1 部位定義如下：
{貼入 L1_部位定義_Sketch視覺指引.md 的表格內容}

請輸出 JSON：
{
  "detected_l1": ["NK", "SH", "AH", "SL", "BM", "SS", "PK"],
  "garment_description": "長袖圓領上衣，兩側口袋"
}
```

**VLM 輸出範例**：
```json
{
  "detected_l1": ["NK", "SH", "AH", "SL", "BM", "SS"],
  "garment_description": "短袖V領梭織上衣"
}
```

---

### Stage ② ISO 查表

**輸入檔案**：`iso_lookup_factory_v3.json`

**已知 context**（Step 1 帶入，不需 VLM 判）：
- `fabric`：Knit 或 Woven（來自 Centric 8 Fabric 欄位或使用者選擇）
- `gt`：Garment Type（TOP / DRESS / PANT / SHORTS 等）
- `it`：Item Type（TOPS / DRESSES / LEGGINGS / PANTS 等）

**查表邏輯**（pseudo code）：

```python
import json

# 載入查表
with open("iso_lookup_factory_v3.json") as f:
    table = json.load(f)

# 建立索引：(fabric, gt, it, l1_code) → entry
index = {}
for entry in table["entries"]:
    key = (entry["fabric"], entry["gt"], entry["it"], entry["l1_code"])
    index[key] = entry

# Stage ①  VLM 輸出
detected = ["NK", "SH", "AH", "SL", "BM", "SS"]

# Step 1 已知
fabric = "Woven"
gt = "TOP"
it = "TOPS"

# 查每個部位
results = []
for l1_code in detected:
    key = (fabric, gt, it, l1_code)
    entry = index.get(key)

    if entry:
        results.append({
            "l1_code": l1_code,
            "l1_name": entry["l1"],
            "iso": entry["iso"],
            "machine": entry["machine"],
            "confidence": entry["confidence"],
            "action": entry["action"],         # recommend / select / manual
            "alternatives": entry.get("alternatives", []),
        })
    else:
        # 該組合查表無資料 → 退回讓使用者手選
        results.append({
            "l1_code": l1_code,
            "action": "manual",
            "reason": "此 Fabric×GT×IT×L1 組合尚無歷史資料",
        })
```

**查表結果範例**（Woven TOP/TOPS）：

| L1 code | 部位 | ISO | 機種 | confidence | action |
|---------|------|-----|------|------------|--------|
| NK | 領 | 301 | 平車 lockstitch | strong | recommend |
| SH | 肩 | 301 | 平車 lockstitch | strong | recommend |
| AH | 袖襱 | 301 | 平車 lockstitch | strong | recommend |
| SL | 袖口 | 301 | 平車 lockstitch | strong | recommend |
| BM | 下襬 | 301 | 平車 lockstitch | strong | recommend |
| SS | 脇邊 | 301 | 平車 lockstitch | strong | recommend |

同樣部位如果是 **Knit** TOP/TOPS：

| L1 code | 部位 | ISO | 機種 | confidence | action |
|---------|------|-----|------|------------|--------|
| NK | 領 | 406 | 三本車 coverstitch | mixed | select |
| SH | 肩 | 406 | 三本車 coverstitch | likely | recommend |
| AH | 袖襱 | 406 | 三本車 coverstitch | likely | recommend |
| SL | 袖口 | 406 | 三本車 coverstitch | likely | recommend |
| BM | 下襬 | 406 | 三本車 coverstitch | strong | recommend |
| SS | 脇邊 | 514 | 拷克車 overlock | strong | recommend |

→ **Fabric 是第一級分流器**：同一個部位，Knit 走 406/514，Woven 走 301，完全不同。

---

### ⚠️ 重要發現：一個部位 ≠ 一個 ISO

從 975 款 PPTX（47 Knit 2026/5 + 928 Seasonal 2025） 中文翻譯的做工描述分析發現：**同一個部位往往涉及多道工序、多個 ISO**。

**例：腰頭（WB）的完整做工配方**

```
D20681: 腰缝 514+1/8'' 406
  → 514 拷克車：接合腰頭到大身
  → 406 三本車：跨壓線 1/8"

D1213: 剪接腰頭,內包鬆緊帶 → 2道單針鎖鏈平均分配腰頭高 → SP線面線
  → 514 拷克車：接合結構
  → 401 鎖鏈：分隔隧道
  → 301 SP線：面線裝飾

D29189: 腰 内加松紧带，401 压线创造隧道
  → 401 鎖縫：建立鬆緊帶隧道
```

**含義**：查表推薦的是「主要（第一道）ISO」，但工廠實際需要看完整工序。`construction_context` 欄位保存了原始做工描述和每道 ISO 的來源證據，供 Stage ③ 顯示。

**例：口袋（PK）的 ISO 來源追溯**

```
ISO 301（推薦）← 「貼式口袋車至大身距邊1/16"壓單針面線」(D1213)
                ← 「前斜口袋→袋口反折包光，且距邊1/16壓1/4雙針明線」(D2350)
ISO 406（替代）← 「口袋 反折一次压1/8'' 406，袋口套结」(D20681)
                ← 「口袋布做光，压1/8" 406三本双针」(D39519)
```

---

### Stage ③ 工廠輸出

**三種 action 的 UI 行為**：

| action | 條件 | UI 行為 |
|--------|------|---------|
| `recommend` | confidence = strong 或 likely | 自動填入 ISO + 機種 + 做工描述，使用者可覆寫 |
| `select` | confidence = mixed | 顯示 ISO 選項清單（含 alternatives + 來源描述），使用者選一個 |
| `manual` | confidence = no_dominant 或查無資料 | 空白，使用者自行輸入 |

**工廠輸出格式（每個部位一張卡片，含做工上下文）**：

```
┌─────────────────────────────────────────────┐
│ 領 (NK)                                      │
│ ✅ 推薦：ISO 301 → 平車                       │
│    confidence: strong (100%)                  │
│    替代方案：無                                │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 下襬 (BM)                                    │
│ ✅ 推薦：ISO 406 → 三本車                     │
│    confidence: strong (71%, 7 designs)        │
│    做工描述：「反折壓1/8"三本雙針」              │
│    來源：D11809, D20681, D22929...            │
│    替代：ISO 514 (14%), ISO 401 (14%)         │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 腰頭 (WB)                                    │
│ 🔶 請選擇（31 designs, 5 種 ISO 都有人用）：    │
│   ○ ISO 406 三本車 ← 「跨壓線1/8"」           │
│   ○ ISO 514 拷克車 ← 「接合腰頭到大身」         │
│   ○ ISO 401 鎖鏈   ← 「壓線創造隧道」          │
│   ○ ISO 301 平車   ← 「SP線面線」             │
│   ⚠ 腰頭通常需要多道工序組合                     │
└─────────────────────────────────────────────┘
```

---

## 三、檔案清單

所有檔案都在 `ONY/` 資料夾：

| 檔案 | 用途 | Stage |
|------|------|-------|
| `L1_部位定義_Sketch視覺指引.md` | VLM 的 system prompt，38 個 L1 視覺定義 | ① |
| `iso_lookup_factory_v3.json` | 四維查表：Fabric × GT × IT × L1 → ISO | ② |
| `l1_code_to_v3_mapping.json` | L1 code ↔ 中文部位名對照（除錯用） | ①→② 橋接 |
| `construction_recipes/` | GT×IT 做工配方（含 zone 出現率、ISO 分佈詳情） | 參考 |
| `woven_construction_extracts.json` | 38 款 Woven 做工原始提取 | 資料來源 |
| `woven_iso_inferred.json` | Woven 中文→ISO 推論詳情 | 資料來源 |
| `knit_2026_5_construction_extracts.json` | 47 款 Knit 下裝 PPTX 做工提取（2026/5 翻譯檔） | 資料來源 |
| `pptx_vs_v3_analysis.json` | PPTX vs v3 交叉驗證分析（21 組比對、7 組安全更新） | 驗證 |
| `knit_pptx_construction_context.json` | 完整做工上下文：每句話→哪個 ISO、跨設計比對、做工配方 | ②③ 上下文 |

---

## 四、查表 v3 資料規格

### 結構

```json
{
  "version": "v3",
  "entries": [
    {
      "fabric": "Knit",          // Knit 或 Woven
      "gt": "TOP",               // Garment Type
      "it": "TOPS",              // Item Type
      "l1": "領",                // 中文部位名
      "l1_code": "NK",           // L1 code（VLM 輸出用這個查）
      "iso": "406",              // 推薦 ISO
      "machine": "三本車 Coverstitch",
      "confidence": "mixed",     // strong/likely/mixed/no_dominant/no_data
      "action": "select",        // recommend/select/manual
      "alternatives": [          // 替代方案（action=select 時顯示）
        {"iso": "514", "pct": 30, "machine": "拷克車 overlock"}
      ]
    }
  ]
}
```

### confidence 定義

| confidence | 條件 | 含義 |
|-----------|------|------|
| strong | 第一名 ISO ≥ 60% | 歷史資料高度一致，可自動推薦 |
| likely | 第一名 ISO 40-59% | 多數設計用這個，但有替代方案 |
| mixed | 第一名 ISO 25-39% | 沒有明確主流，需要使用者選 |
| no_dominant | 第一名 ISO < 25% | 分散，必須手動 |
| no_data | 該 zone 在此 GT×IT 極少出現 | 罕見部位，無統計基礎 |

### 覆蓋範圍

| Fabric | GT×IT 組合 | Zone 數 | 資料來源 |
|--------|-----------|---------|---------|
| Knit | 13 組 | 264 | Centric 8 PDF（~370 款設計，含 2026/5 新增 53 份） |
| Woven | 3 組 | 16 | Source-Data PPTX（38 款設計，含 FA25/HO25 新增 2 款） |

**Knit 13 組**：TOP\|TOPS, PANT\|PANTS, PANT\|LEGGINGS, SHORTS\|SHORTS, SHORTS\|LEGGINGS, DRESS\|DRESSES, SWIM\|SWIM, SWIM\|SWIM_RASHGUARD, SLEEPWEAR\|SLEEPWEAR, SET\|SET, SET\|SLEEPWEAR, OUTERWEAR\|OUTERWEAR, ONE_PIECE\|ONE PIECE

**Woven 3 組**：TOP\|TOPS, DRESS\|DRESSES, BOTTOM\|SHORTS

---

## 五、Fabric 判斷邏輯

Fabric 不需要 VLM 判，從系統已知資訊帶入：

**優先順序**：
1. **使用者在 UI 直接選**（最準）
2. **Centric 8 欄位自動帶入**：Design Type / Collection / Department 推導
3. **推導規則**（fallback）：
   - Collection 含 Chambray / MWD / VDD / WWD / WWS → Woven
   - Department 含 Active / Swim / Fleece / Performance → Knit
   - 其餘預設 Knit（ONY 資料 Knit 佔 98%）

---

## 六、目前限制與擴展方向

### 已知限制

1. **一個部位 ≠ 一個 ISO**（v3.2 新發現）：從 47 款 PPTX 中文做工分析確認，腰頭（WB）平均涉及 2-4 個 ISO（514 接合 + 406 壓線 + 401 隧道 + 301 面線），口袋（PK）也常見 301 壓線 + 514 拷克收邊的組合。目前查表只推薦「主要 ISO」，完整工序需查 `construction_context` 欄位。

2. **Woven 資料量少**：僅 38 款 / 3 個 GT×IT 組合。Knit 有 370+ 款 / 13 組。Woven 側 confidence 看起來都 strong，但底層樣本數只有 2-4 款，統計穩健性有限。（2026-04-20 從 FA25/HO25 新增 D63716、D68142 兩款）

3. **Woven ISO 是推論的**：38 款中只有 1 款（D68210）直接寫 ISO 碼，其餘從中文做工描述推論。推論規則：「壓單針/明線/SP車線 → 301」「拷克 → 514」等。準確率高但非 100%。

4. **通用版不分品牌**：同一個 GT×IT×L1，不同品牌可能有不同偏好（例如 GAP 腰頭固定用某種 ISO，Athleta 偏好另一種）。品牌版需要加 Brand 維度，本查表不含。

5. **L1 偵測依賴 VLM 品質**：VLM 漏判或誤判 L1 會連帶影響 ISO 推薦。多標籤偵測（一張 sketch 同時 6-15 個 L1）是 VLM 端的主要挑戰。

### 擴展方向

| 方向 | 做法 | 效果 |
|------|------|------|
| 擴展 Woven 品類 | 補更多 Woven PPTX 提取 + 直接請 IE 標注 ISO | Woven 覆蓋從 3 組 → 目標 8+ 組 |
| 加 Brand 維度 | Brand × Fabric × GT × IT × L1 五維查表 | 品牌偏好差異化推薦 |
| 加 Department 維度 | Swimwear / Sleepwear 獨立 ISO 分佈 | Swim 只用 514+605，Sleepwear 以 406 為主 |
| VLM 訓練迭代 | 用 ONY sketch 做 few-shot / fine-tune | L1 偵測準確率提升 |
| 回饋閉環 | 工廠實際採用的 ISO 回寫更新查表 | 持續提升 confidence |
| 多道工序推薦 | 查表從「推一個 ISO」升級為「推一組工序」（如腰頭 = 514+406+401） | 更貼近工廠實際需求 |

---

## 七、ISO ↔ 機種速查

| ISO | 中文 | English | 常見用途 |
|-----|------|---------|---------|
| 301 | 平車 | Lockstitch | **Woven 主力**。topstitch、明線、門襟、袖口反折 |
| 401 | 鏈縫 | Chainstitch | 腰頭底部、可拆縫合 |
| 406 | 三本車 | Coverstitch | **Knit 主力**。領、袖口、下襬壓線、彈性收邊 |
| 514 | 拷克車 | Overlock | 布邊鎖邊、Knit 大身接合、Woven 內縫份收邊 |
| 605 | 爬網車 | Covering stitch | Knit 高彈力部位（Swim、Active） |
| 607 | 併縫車 | Flatseam | Knit 大身接合（無感縫合、運動服） |

---

## 八、全量分析摘要（2026-04-20）

**數據規模**：14,225 JSONL + 928 PPTX（2025 四季 FA/HO/SP/SU）

**JSONL GT 分佈**：903 unique designs — TOP 298 / UNKNOWN 151 / DRESS 105 / OUTERWEAR 98 / PANT 92 / LEGGING 88 / SHORTS 73 / SWIM 65 / SKORT 42 / JOGGER 36 / SKIRT 21 / ROMPER_JUMPSUIT 16 / SLEEPWEAR 13 / SET 7 / BODYSUIT 5

**PPTX 做工發現**：
- 928 份中 456 份有 zone 提取，532 份有做工得分
- 2025 seasonal 幾乎全是 **Woven**（WWT 407 / WWD 299 / WWS 153 / Chambray 8）
- 最常出現的 zone：SV(袖) 298 / 肩 218 / SC(袖口) 203 / PK(口袋) 159 / WB(腰頭) 155

**交叉驗證**：4 corroborated（BD→514, WB→514, BM→301, NK→514）、1 contradicted（PK）、2 new zones（HM, SV）

**Woven vs Knit 關鍵差異**：
- BM(下襬)：Woven→301 lockstitch vs Knit→406 coverstitch
- PK(口袋)：Woven→514 only vs Knit→301+406 mixed
- BD(大身)：Woven→514+301 vs Knit→607/514 overlock family
- **Fabric 必須是 Filter Chain 第一維度**

**v3 覆蓋缺口**：Woven 僅 16 條 vs Knit 266 條，2025 seasonal PPTX 是最佳 Woven 擴展來源

詳細數據 → `full_analysis_20260420.json`

---

*最後更新：2026-04-20*
*資料版本：iso_lookup_factory_v4.0（282 entries，GT/IT 對齊 pom_rules v5.5）*
*v3→v4 變更：LEGGINGS 升為 GT / IT 移除查表維度 / 新增 Department 維度（Active/RTW/Swimwear/Sleepwear）*
*底層資料集：all_years.jsonl 14,225 records + seasonal_2025_pptx_extracts.json 928 PPTX*
*全量分析報告：full_analysis_20260420.json*
