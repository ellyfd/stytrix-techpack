# Path 2 通用模型：AI 做工推薦 Pipeline

> **路線**：Sketch → VLM 判 L1 → 雙表查 ISO → 卡片輸出（不走五階層）
> **模型定位**：通用版（不分品牌），任一客人任一 Fabric/GT/IT 組合皆可用
> **資料版本**：v4.2（primary，zone-specific）＋ v4（fallback，覆蓋廣）
> **最後更新**：2026-04-20

---

## 一、Pipeline 總覽

```
使用者在 Step 1 選定 → Brand / Fabric / Gender / Department / GT / IT
                              ↓
                      上傳或生成 Sketch 圖
                              ↓
            ┌─────────────────────────────────────┐
            │  Stage ① VLM 部位偵測                 │
            │  後端：api/analyze.js (Pass 1)        │
            │  模型：Claude Sonnet 4.6 (vision)     │
            │  輸入：Sketch 圖 + L1 視覺指引          │
            │  輸出：{code, side, x, y, confidence} │
            └──────────────┬──────────────────────┘
                              ↓（每個 L1）
            ┌─────────────────────────────────────┐
            │  Stage ② ISO 雙表查                    │
            │  前端：isoOptionsFor(...)             │
            │  主查：v4.2                            │
            │    Department × Gender × GT × L1      │
            │  備援：v4                              │
            │    Fabric × Department × GT × L1_code │
            │  輸出：[primary, ...alternatives]     │
            └──────────────┬──────────────────────┘
                              ↓
            ┌─────────────────────────────────────┐
            │  Stage ③ 卡片組裝                       │
            │  每張卡片：                              │
            │    L1 部位 / ISO + 中文 + 機種           │
            │    替代 ISO（bridge v6 / pptx votes）   │
            │    常見工法（bridge v6 method dist.）    │
            └─────────────────────────────────────┘
```

通用模式後端 (`api/analyze.js`) 偵測到 `mode=universal` 時會略過 Pass 2（decision tree），token 成本只剩 Pass 1 約 0.5¢。

---

## 二、每個 Stage 的實作位置

### Stage ① — VLM 部位偵測（後端）

**實作**：`api/analyze.js` → `identifyL1()`
**系統 Prompt**：用 `L1_部位定義_Sketch視覺指引.md` + `data/l2_visual_guide.json` 的 `l1[code].sketch_def`,餵給 Claude。
**輸出範例**：
```json
{
  "detected": [
    {"code": "WB", "side": "front", "x": 50, "y": 10, "confidence": 92},
    {"code": "LO", "side": "front", "x": 50, "y": 95, "confidence": 88},
    {"code": "PS", "side": "front", "x": 50, "y": 60, "confidence": 75}
  ]
}
```
過濾規則在 `L1_CODES` 白名單;不在 38 個 L1 code 內的回覆會被丟掉。

---

### Stage ② — ISO 雙表查（前端）

**實作**：`index.html` → `isoOptionsFor(lookupV42, lookupV4, filters, l1Code)`
**Filters**：`{ fabric, dept, gender, gt, it }` 全部 from Step 1 UI 選單。

**查表順序**:
1. **v4.2**（zone-specific,含 Gender,信心最高）
   - Key: `Department × Gender × GT × L1_name`
   - UI 值需經 `V42_DEPT_ALIAS` / `V42_GENDER_ALIAS` / `V42_GT_ALIAS` 翻譯
     (e.g. `LEGGINGS` → `BOTTOM`、`Active` → `General`)
   - 找到且 `iso` 非 null → 回傳 v4.2 primary,pct 來自 `iso_distribution`
2. **v4 fallback**(document-level,無 Gender,覆蓋完整)
   - Key: `Fabric × Department × GT × L1_code`
   - 四層 fallback:精準 → 放寬 Dept → 放寬 GT → 只剩 Fabric × L1
   - `iso_zh` / `machine` 由 v4 entry 直接帶入

**回傳格式**:
```js
[
  { iso: "605", iso_zh: "三針五線爬網", machine: "爬網車 Flatseam 3N5T",
    pct: 33.0, isPrimary: true, source: "v4" },
  { iso: "514", iso_zh: "拷克車", machine: "overlock",
    pct: 14.0, isPrimary: false, source: "v4" },
  ...
]
```
`opts[0]` = primary,`opts[1+]` = alternatives。

---

### Stage ③ — 卡片組裝(前端)

**實作**:`index.html` → `runConstruction()` 的 `if (appMode === "universal")` 分支
**每張卡片的資料來源**:
- 主 ISO(`primary.iso`/`iso_zh`/`machine`)← isoOptionsFor `opts[0]`
- 替代 ISO chip ← bridge v6 `iso_distribution`(三年 1,328 designs 累計),若 bridge 對該 L1 沒資料,fallback 到 v4 entry 的 `pptx_2025_votes`
- 常見工法 chip ← bridge v6 `method_distribution` 前 3 名(bridge 獨有)

**沒有歷史 ISO 的 L1**:`builtFiltered` 會把 `primary.iso` 為 null 的 L1 濾掉,AI 偵測到但查無 ISO 的部位不自動產卡 — 使用者可以用「+ 新增部位」手動補,無歷史時允許空白新增。

---

## 三、檔案清單(目前在資料夾的檔案都在跑)

| 檔案 | 用途 | Stage |
|------|------|-------|
| `L1_部位定義_Sketch視覺指引.md` | VLM Pass 1 的 sketch_def 來源 | ① |
| `iso_lookup_factory_v4.2.json` | **primary** 查表(63 entries,5 個 L1 zone-specific) | ② |
| `iso_lookup_factory_v4.json` | **fallback** 查表(282 entries,完整覆蓋 + iso_zh/machine) | ② |
| `knit_pptx_construction_context.json` | 47 Knit PPTX(2026/5) zone 層級做工紀錄(留作 regen 素材) | 備用 |
| `woven_construction_extracts.json` | 2025 Woven PPTX 提取(v4 woven 半邊的來源) | 建庫用 |
| `woven_construction_raw_text.json` | 6 款 Woven PPTX raw text | 建庫用 |
| `woven_iso_inferred.json` | Woven 中文→ISO 推論(已烘進 v4) | 建庫用 |
| `full_analysis_20260420.json` | 14,225 JSONL + 928 PPTX 全量分析快照 | 參考 |

Bridge v6(替代 ISO + 常見工法)放在 `data/construction_bridge_v6.json`,不在此資料夾。

---

## 四、ISO 查表版本演進

| 版本 | Key | Entries | 特性 | 狀態 |
|---|---|---|---|---|
| v4 | Fabric × Department × GT × L1_code | 282 | 無 Gender;GT/IT 對齊 pom_rules v5.5;含 iso_zh/machine/pptx_2025_votes | **fallback** |
| v4.2 | Department × Gender × GT × L1_name | 63 | zone-specific parsing,含 Gender;5 L1 覆蓋(腰頭/褲口/褲合身/口袋/繩類);含 iso_distribution | **primary** |

**v4 → v4.2 改什麼**:
- ISO 從「document-level broadcast」改成「zone-specific」— 不再把整份 PPTX 的 ISO 廣播到所有 L1,而是按部位抽
- 加入 Gender 維度(性別差異 e.g. WOMENS vs KIDS)
- Fabric 拿掉(ONY 資料 98% 是 knit,無統計意義)

**V42 alias 的存在理由**:v4.2 的 GT 桶是粗粒度(`BOTTOM`/`TOP`/`DRESS`/`SKIRT`/`SET`/`OUTERWEAR`),UI 用的是細粒度(`LEGGINGS`/`PANTS`/`SHORTS`/`TOP` …)。三張 alias 表(`V42_DEPT_ALIAS` / `V42_GENDER_ALIAS` / `V42_GT_ALIAS`)負責翻譯。**已知問題**:v4.2 當初從 PPTX 端解析時只聚合到粗桶,沒 join 回 `data/all_designs_gt_it_classification.json` 取細 GT;未來 regen 建議先 join 分類表,拆成細 GT 後 alias 就可以拿掉。

---

## 五、ISO ↔ 機種速查

| ISO | 中文 | English | 常見用途 |
|-----|------|---------|---------|
| 301 | 平車 | Lockstitch | **Woven 主力**。topstitch、明線、門襟、袖口反折 |
| 401 | 鏈縫 | Chainstitch | 腰頭底部、可拆縫合 |
| 406 | 三本車 | Coverstitch | **Knit 主力**。領、袖口、下擺壓線、彈性收邊 |
| 514 | 拷克車 | Overlock | 布邊鎖邊、Knit 大身接合、Woven 內縫份收邊 |
| 605 | 爬網車 | Covering stitch | Knit 高彈力部位(Swim、Active) |
| 607 | 併縫車 | Flatseam | Knit 大身接合(無感縫合、運動服) |

---

## 六、已知限制

1. **一個部位 ≠ 一個 ISO**:腰頭(WB)實務上常見 4-5 道工序組合(514 接合 + 406 壓線 + 401 隧道 + 301 面線)。目前每張卡只推「主 ISO」,替代 ISO 以 chip 呈現,多道工序的組合表達仍待設計。
2. **v4.2 L1 覆蓋窄**:只有 5 個 L1 真的用 zone-specific parsing,其他 L1 全靠 v4 fallback,性別差異丟失。
3. **v4.2 GT 粗粒度**:`LEGGINGS`/`PANTS`/`SHORTS` 全壓到 `BOTTOM`,雖然 `all_designs_gt_it_classification.json` 裡 fine GT 每桶都 N≥3 夠統計,但 v4.2 當初建表沒 join 回去 — 下次 regen 應改正。
4. **Woven 資料量少**:v4 woven 側只有 16 條、3 個 GT×IT 組合,confidence 高但樣本薄(2-4 款)。
5. **VLM 多標籤偵測**:單張 sketch 要同時抓 6-15 個 L1,是 Pass 1 主要挑戰;漏判/誤判會連帶影響 ISO 推薦。
