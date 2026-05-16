# Path 2 通用模型：AI 做工推薦 Pipeline

> ⚠ **2026-05-15 查表來源已換**:`iso_lookup_factory_v4.3.json` + `v4.json` 已 git rm 退役,
> 改由單一完整 5 維表 **`iso_lookup_brandspec_5dim.json`**（Fabric × Department × Gender × GT × L1,
> 多來源聚合:pptx_facets 必吃 + facts_aligned 選吃 + pdf_facets 接口預留）取代。
> **Pipeline 概念不變**（VLM 判 L1 → 查表 → 工廠輸出），只是查表的 source 換了一張完整表。
> 以下「v4.3」相關描述為歷史紀錄,實作以 `build_iso_lookup_brandspec_5dim.py` + `build_recipes_master.py` 為準。

> **2026-05-07 改名公告**:本資料夾原名 `General Model_Path2_Construction Suggestion/`,改名為 `path2_universal/`。SOP 中提到的檔案位置以新路徑為準。

> **路線**：AI 判視 → 直接推 ISO 給工廠，不走五階層
> **模型定位**：通用版（不分品牌），適用所有客人
> **建立日期**：2026-04-20
> **資料來源**：ONY 1,328 款 Centric 8（5 種來源合併：PPTX 中文 / PDF 英文 / JSONL iso_codes / Raw PDF pdfplumber / OCR callout）
> **查表版本**：~~v4.3~~ → 2026-05-15 改 `iso_lookup_brandspec_5dim.json`（完整 5 維 Fabric × Department × Gender × GT × L1）

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
            │  查詢：Fabric × Dept × Gender × GT × L1 │
            │  來源：iso_lookup_brandspec_5dim │
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

**輸入檔案**：`docs/spec/L1_部位定義_Sketch視覺指引.md`

**做法**：把視覺指引餵給 VLM（Qwen-VL / GPT-4o）當 system prompt，再丟 sketch 圖。

**VLM Prompt 範本**：

```
你是成衣做工專家。請看這張 sketch，列出圖上可見的所有 L1 部位。

規則：
1. 只列「看得到」的部位，不要猜測不可見的做工（BN 貼合、NT 領貼條、LI 裡布除非有剖面圖）
2. 用 L1 code 回答（NK, WB, BM, SL, PK...）
3. 每個 L1 只列一次，不重複

L1 部位定義如下：
{貼入 docs/spec/L1_部位定義_Sketch視覺指引.md 的表格內容}

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

**輸入檔案**：`iso_lookup_brandspec_5dim.json`（2026-05-15 起；舊 `iso_lookup_factory_v4.3.json` 已 git rm）

**已知 context**（Step 1 帶入，不需 VLM 判）：
- `department`：General / Swimwear（來自 Centric 8 Department 欄位或使用者選擇）
- `gender`：WOMENS / MENS / KIDS（來自 Brand/Division 欄位）
- `gt`：Garment Type — **fine GT**，直接對齊 App UI 下拉選單值（PANTS / LEGGINGS / SHORTS / TOP / DRESS…），**不做 canonical collapse**

**查表邏輯**（pseudo code）：

```python
import json

# 載入查表
with open("iso_lookup_brandspec_5dim.json") as f:
    table = json.load(f)

# 建立索引：(department, gender, gt, l1) → entry
index = {}
for entry in table["entries"]:
    key = (entry["department"], entry["gender"], entry["gt"], entry["l1"])
    index[key] = entry

# Stage ①  VLM 輸出
detected = ["NK", "SH", "AH", "SL", "BM", "SS"]

# Step 1 已知（fine GT，不 collapse）
department = "General"
gender = "WOMENS"
gt = "TOP"    # App UI 原始值

# L1 code → 中文名稱 mapping（用 l1_code_to_v3_mapping.json）
l1_code_to_name = {"NK": "領", "SH": "肩", "AH": "袖襱", "SL": "袖口", "BM": "下襬", "SS": "脇邊"}

# 查每個部位
results = []
for l1_code in detected:
    l1_name = l1_code_to_name.get(l1_code, l1_code)
    key = (department, gender, gt, l1_name)
    entry = index.get(key)

    if entry and entry["confidence"] in ("strong", "likely"):
        results.append({
            "l1_code": l1_code,
            "l1_name": entry["l1"],
            "iso": entry["iso"],
            "confidence": entry["confidence"],
            "action": "recommend",
            "iso_distribution": entry.get("iso_distribution", {}),
        })
    elif entry and entry["confidence"] == "mixed":
        results.append({
            "l1_code": l1_code,
            "l1_name": entry["l1"],
            "action": "select",
            "iso_distribution": entry.get("iso_distribution", {}),
        })
    else:
        # 該組合查表無資料或 no_data → 退回讓使用者手選
        results.append({
            "l1_code": l1_code,
            "action": "manual",
            "reason": "此 Department×Gender×GT×L1 組合尚無歷史資料",
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
| `docs/spec/L1_部位定義_Sketch視覺指引.md` | VLM 的 system prompt，38 個 L1 視覺定義 | ① |
| `iso_lookup_brandspec_5dim.json` | 五維查表：Fabric × Department × Gender × GT × L1 → ISO（2026-05-15 取代舊 `iso_lookup_factory_v4.3.json` + `v4.json`，已 git rm） | ② |
| `l1_code_to_v3_mapping.json` | L1 code ↔ 中文部位名對照（VLM code→查表名稱橋接） | ①→② 橋接 |
| `construction_recipes/` | v4.1 做工配方：71 recipes, 505 designs（Gender × Dept × GT(fine) × IT） | 參考 |
| `_parsed/construction_extracts/pptx/` | 6,998 txt 檔，792 unique designs PPTX 中文做工提取 | 資料來源 ① |
| `_parsed/construction_extracts/pdf/` | 2,686 txt 檔，502 unique designs PDF 英文做工提取 | 資料來源 ② |
| `_parsed/all_years.jsonl` | 18,183 records，547 有 iso_codes 欄位（127 unique designs） | 資料來源 ③ |
| `iso_lookup_factory_v4.2_backup.json` | v4.2 備份（coarse GT 版，已棄用） | 歷史 |

---

## 四、查表 v4.3 資料規格

### 結構

```json
{
  "version": "v4.3",
  "key_schema": "Department × Gender × GT(fine) × L1",
  "sources": ["PPTX Chinese construction", "PDF extracted txt", "PDF JSONL iso_codes", "Raw PDF pdfplumber", "OCR callout"],
  "gt_values": ["DRESS", "LEGGINGS", "OUTERWEAR", "PANTS", "ROMPER_JUMPSUIT", "SET", "SHORTS", "SKIRT", "TOP"],
  "confidence_rules": {
    "strong": "Top ISO ≥60% & N≥5",
    "likely": "Top ISO ≥40% & N≥3",
    "mixed": "Top ISO <40% or diverse distribution",
    "no_data": "N<3"
  },
  "entries": [
    {
      "department": "General",     // General 或 Swimwear
      "gender": "WOMENS",          // WOMENS / MENS / KIDS / UNKNOWN
      "gt": "PANTS",               // fine GT — 對齊 App UI 下拉選單
      "l1": "褲口",                // 中文部位名
      "iso": "406",                // 推薦 ISO（最高佔比）
      "iso_pct": 55.0,             // 最高佔比 %
      "confidence": "likely",      // strong/likely/mixed/no_data
      "n_designs": 12,             // 支持設計數
      "iso_distribution": {        // 完整 ISO 分佈
        "406": 7, "514": 3, "605": 2
      }
    }
  ]
}
```

### ⚠️ GT 使用規則

**v4.3 使用 fine GT（對齊 App UI 下拉選單）**：PANTS / LEGGINGS / SHORTS / TOP / DRESS / SET / SKIRT / OUTERWEAR / ROMPER_JUMPSUIT。

**不做 canonical collapse**（例如不把 PANTS+LEGGINGS+SHORTS 合併成 BOTTOM）。原因：fine GT 揭露重要 ISO 差異，例如：
- PANTS 褲口 → ISO 406 (55%)，LEGGINGS 褲口 → ISO 605 (64%)，SHORTS 褲口 → ISO 605 (50%)
- 合併成 BOTTOM 會掩蓋這些差異

**GT Alias（最小化清洗）**：只處理真正的同義詞 — 3RD_PIECE→OUTERWEAR, BODYSUIT_ONESIE→BODYSUIT, JOGGER→JOGGERS, TOPS→TOP。

### confidence 定義

| confidence | 條件 | 含義 |
|-----------|------|------|
| strong | Top ISO ≥ 60% 且 N ≥ 5 | 歷史資料高度一致，可自動推薦 |
| likely | Top ISO ≥ 40% 且 N ≥ 3 | 多數設計用這個，但有替代方案 |
| mixed | Top ISO < 40% 或分佈分散 | 沒有明確主流，需要使用者選 |
| no_data | N < 3 | 樣本不足，無統計基礎 |

### 覆蓋範圍（v4.3）

| 指標 | 數值 |
|------|------|
| Total entries | 130 |
| Total designs | 292 |
| Strong entries | 13 |
| Likely entries | 44 |
| Mixed entries | 10 |
| No_data entries | 63 |
| GT values | 9（PANTS, LEGGINGS, SHORTS, TOP, DRESS, SET, SKIRT, OUTERWEAR, ROMPER_JUMPSUIT） |
| Departments | General, Swimwear |
| Genders | WOMENS, MENS, KIDS, UNKNOWN |

### 五種資料來源

| # | 來源 | 檔案位置 | Unique Designs with ISO |
|---|------|---------|------------------------|
| ① | PPTX 中文做工 | `_parsed/construction_extracts/pptx/` | 792 |
| ② | PDF 英文做工 | `_parsed/construction_extracts/pdf/` | 502 |
| ③ | JSONL iso_codes | `_parsed/all_years.jsonl` | 127 |
| ④ | Raw PDF pdfplumber | 原始 PDF re-extraction | 468 |
| ⑤ | OCR callout | pytesseract on callout images | 27 |

合併後 716 unique designs 有 ISO（54% of 1,328），292 designs 進入 zone-specific lookup。

### 做工配方（Recipes v4.1）

| 指標 | 數值 |
|------|------|
| Total recipes | 71 |
| Total designs | 505 |
| Key schema | Gender × Department × GT(fine) × IT |
| GT values | 同 v4.3（9 個 fine GT） |

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

1. **一個部位 ≠ 一個 ISO**：從 792 款 PPTX + 502 款 PDF 做工分析確認，腰頭（WB）平均涉及 2-4 個 ISO（514 接合 + 406 壓線 + 401 隧道 + 301 面線），口袋（PK）也常見 301 壓線 + 514 拷克收邊的組合。目前查表只推薦「主要 ISO」，完整工序需查 `iso_distribution` 和配方。

2. **46% 設計無任何 ISO 來源**：1,328 designs 中 612 款（46%）在五種來源都沒有 ISO。其中 391 款 PDF 完全沒有 callout 頁（只有 sketch+measurement+BOM），~229 款 callout 以圖片嵌入（需 VLM 才能進一步提取）。

3. **Zone-specific vs Document-level**：只有 PPTX 中文和部分 PDF 英文能做到 zone-specific（每行指定 L1 zone 的 ISO）。JSONL iso_codes 和 raw pdfplumber 只能做 document-level（所有 ISO broadcast 到每個 zone），會稀釋 confidence。

4. **通用版不分品牌**：同一個 GT×L1，不同品牌可能有不同偏好。品牌版需要加 Brand 維度，本查表不含。

5. **L1 偵測依賴 VLM 品質**：VLM 漏判或誤判 L1 會連帶影響 ISO 推薦。多標籤偵測（一張 sketch 同時 6-15 個 L1）是 VLM 端的主要挑戰。

6. **no_data entries 佔比高**：130 entries 中 63 條（48%）為 no_data（N<3）。需要更多 PPTX 翻譯或 PDF 英文提取來提升覆蓋。

### 擴展方向

| 方向 | 做法 | 效果 |
|------|------|------|
| VLM 提取 callout 圖片 | 對 ~229 款圖片式 callout 做 VLM extraction | 覆蓋率從 54%→預估 70%+ |
| 加 Brand 維度 | Brand × Department × Gender × GT × L1 五維查表 | 品牌偏好差異化推薦 |
| 提升 no_data entries | 補更多 PPTX 翻譯 + 向 IE 確認 | 63 條 no_data 降至 <30 |
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

**數據規模**：12,038 PDFs / 4,069 PPTX → 1,328 unique designs → 716 有 ISO（54%）→ 292 進入 zone-specific lookup → 505 進入 recipes

**v4.3 Data Funnel**：
```
1,328 unique designs（all_designs_gt_it_classification.json）
  └─ 716 有 ISO（from 5 sources merged）── 54% 覆蓋率
       └─ 292 進入 zone-specific lookup（iso_lookup_factory_v4.3.json）
            └─ 13 strong / 44 likely / 10 mixed / 63 no_data
  └─ 505 進入 recipes（construction_recipes/ v4.1, 71 recipes）
  └─ 612 無任何 ISO 來源 ── 46% 未覆蓋
       └─ 391 PDF 無 callout 頁
       └─ ~229 callout 為圖片嵌入（需 VLM）
```

**Fine GT 揭露的關鍵差異**（v4.2 coarse GT 看不到）：
- 褲口：PANTS→406(55%) vs LEGGINGS→605(64%) vs SHORTS→605(50%)
- 側縫：PANTS→514(54%) vs LEGGINGS→514(45%)
- 合併成 BOTTOM 會掩蓋這些重要分流

**Woven vs Knit 關鍵差異**：
- BM(下襬)：Woven→301 lockstitch vs Knit→406 coverstitch
- PK(口袋)：Woven→514 only vs Knit→301+406 mixed
- BD(大身)：Woven→514+301 vs Knit→607/514 overlock family

---

*最後更新：2026-04-20*
*查表版本：iso_lookup_factory_v4.3（130 entries / 292 designs / 13 strong / 44 likely）*
*配方版本：construction_recipes v4.1（71 recipes / 505 designs）*
*v4.2→v4.3 變更：fine GT 取代 canonical collapse（PANTS/LEGGINGS/SHORTS 不再合併為 BOTTOM）、5 sources 合併（PPTX+PDF txt+JSONL+pdfplumber+OCR）、classification join 取得 fine GT*
*v3→v4 變更：LEGGINGS 升為 GT / IT 移除查表維度 / 新增 Department+Gender 維度*
*底層資料集：1,328 unique designs from 12,038 PDFs + 4,069 PPTX*
