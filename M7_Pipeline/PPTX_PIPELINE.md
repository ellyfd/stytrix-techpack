# PPTX Pipeline — Construction Callout 結構化抽取

**狀態**：2026-05-12 完成
**腳本**：`scripts/extract_pptx_all.py`（+ 輔助 `audit_pptx_deep.py` / `diag_iso_bracket.py`）
**輸出**：`outputs/extract/pptx_facets.jsonl`（135 MB / 18,731 entries）

---

## 一、目的

把每個 EIDH（設計單元）對應的 PPTX 簡報，抽出**結構化的 sewing constructions**：

- 每個 construction = `{ method, zone, L1, iso }` 四維度
- 餵下游 IE / Bible / construction recipe 系統當「設計師意圖訊號」
- 不是「精準機種規格」（那走 IE Bible 五階層 + L1 推薦表），是「設計師寫了什麼」

---

## 二、Pipeline 全貌

```
data/source/tp_samples_v2/<EIDH>/*.pptx
        │
        ▼
extract_pptx_all.py（ProcessPoolExecutor）
  │
  ├── 1. python-pptx 開檔 → 每張 slide 抽 text
  │     輸出 raw text → outputs/extract/pptx_text/<client>_<design>.txt
  │
  ├── 2. _slide_score(text) → 0-N 分判斷該 slide 是不是 construction page
  │     ≥ 3 分 = construction slide（含 60+ 中文 sewing keyword + 50+ zone keyword）
  │     輸出 n_construction_slides 計數
  │
  ├── 3. _parse_slide_constructions(slide_text)
  │     │
  │     ├── Pattern 1 (主路徑): 抓「<zone>: <method>」block
  │     │     例: "領: 1/8"單針平車(301)"
  │     │
  │     └── Pattern 2 (fallback): 逐行 scan zone + iso, 任一 match 就當 construction
  │
  ├── 4. 每行 description 走兩個推斷:
  │     │
  │     ├── _zone_to_l1(zone) → L1 2-letter code (對齊 l1_standard_38.json)
  │     │   + Fallback: zone 沒 L1 時, scan method 內 body-part keyword 推 L1
  │     │
  │     └── _infer_iso_from_zh(method) → ISO list (對齊 iso_dictionary.json 14 碼)
  │         │
  │         ├── Priority 1: 顯式括號 ISO_BRACKET_RE — "(301)" "(514+401)" 等
  │         │       (含複合碼 514+401 / 514+605)
  │         │
  │         ├── Priority 2: ZH_SEW_TO_ISO keyword 對照 (~110 條)
  │         │       長詞優先 (壓單針鎖鏈→401, 三本三針→407, 爬網→605...)
  │         │
  │         └── Negative filter (_is_non_method):
  │                 過濾「車線:」「洗標#」「圖#」「請改善」「反黃尺寸」等非做工 text
  │
  ▼
outputs/extract/pptx_facets.jsonl
每行 = 1 EIDH:
{
  "eidh": "305033",
  "client_code": "UA",
  "client_raw": "UNDER ARMOUR",
  "design_id": "6011047",
  "pptx_files": ["TPK24...pptx"],
  "n_slides_total": 18,
  "n_construction_slides": 8,
  "constructions": [
    {
      "method": "1/8\"單針平車",
      "_source_slide": 4,
      "iso": "301",
      "zone": "領",
      "L1": "NK",
      "L1_name": "領",
      "_source_pptx": "TPK24...pptx"
    },
    ...
  ],
  "n_constructions": 66,
  "raw_text_file": "outputs/extract/pptx_text/UA_6011047.txt",
  "_status": "ok"
}
```

---

## 三、官方 reference 對齊

| Source | 用途 | 我們的對齊 |
|--------|------|-----------|
| `stytrix-techpack/data/runtime/l1_standard_38.json` | 38 個官方 L1 部位碼 | `ZH_ZONE_TO_L1` 完全對齊（袖→AH / 鎖眼→HL 等都已加） |
| `stytrix-techpack/data/runtime/iso_dictionary.json` | 14 個官方 ISO 工藝碼 | `ISO_BRACKET_RE` + `ZH_SEW_TO_ISO` 涵蓋全 14 碼（含複合碼）|
| `stytrix-techpack/data/runtime/l1_iso_recommendations_v1.json` | L1 歷史 ISO 推薦表 | **沒用**（保留給下游 fallback inference）|

---

## 四、最終 stats（2026-05-12）

```
=== PPTX (135 MB / 18,731 entries) ===

整體覆蓋:
  total entries          : 18,731
  with pptx file(s)      : 14,259 (76%)  ← 4,472 EIDH 沒附 PPTX（GU 1,754 / NET 154 等）
  with >=1 construction       : 13,878 (74%)
  slides 合計             : 271,657
  construction slides    : 37,023
  constructions 合計           : 708,425
  avg construction / design   : 51.0

Callout 維度覆蓋率:
  has method             : 100%
  has zone               : 93%
  has L1 (38 官方碼)      : 82%   ← 18% 沒對到是因為 zone (前中/後中/反摺) 官方 schema 沒對應碼
  has iso                : 19%   ← ceiling — 81% 是描述/位置/QC 評語, 沒寫機種
  has all 4 (完整 construction): 11%

ISO 分布 (top 8):
  301 平車          63,080 (47%)
  406 三本車        18,747 (14%)
  304 曲折縫        16,453 (12%)
  401 鎖鍊          14,716 (11%)
  514 四線拷克      10,118 (8%)
  516 五線拷克       4,093 (3%)
  607 併縫(Flatlock) 3,760 (3%)
  605 爬網           2,865 (2%)

L1 分布 (top 8):
  WB 腰頭   92,502 (16%)
  NK 領     87,192 (15%)
  SH 肩     83,840 (14%)
  AH 袖圍   59,162 (10%)
  PK 口袋   54,453 (9%)
  RS 褲襠   34,350 (6%)
  SL 袖口   29,628 (5%)
  BM 下襬   29,207 (5%)
```

---

## 五、Per-brand 收成

| Brand | entries | with_construction | constructions | iso% | L1% |
|-------|---------|--------------|----------|------|-----|
| ONY | 3,841 | 3,247 (85%) | 151,897 | 12% | 89% |
| GAP | 2,470 | 2,233 (90%) | 129,488 | 16% | 84% |
| DKS | 2,216 | 2,119 (96%) | 141,278 | 22% | 79% |
| GU | 1,756 | **2 (0%)** ⚠ | 13 | — | — |
| KOH | 1,756 | 1,324 (75%) | 59,024 | 19% | 84% |
| TGT | 1,527 | 1,314 (86%) | 52,117 | 26% | 72% |
| ATH | 788 | 742 (94%) | 52,684 | 28% | 77% |
| WMT | 424 | 284 (67%) | 3,646 | **40%** ← 最高 | 80% |
| UA | 431 | 286 (66%) | 22,785 | 31% | 72% |

**GU 註記**：1,756 件 EIDH 只有 2 個 PPTX 檔（其他都是 placeholder 空殼）— GU 走 **PDF 主源**（已驗證 1,665/1,756 PDF 覆蓋率 95%）。

---

## 六、Known Limitations（不是 bug）

### L1 18% 沒對到（141,543 constructions）
**原因**：官方 38 L1 沒對應的 zone 是 schema 限制
- 前中（30,638）/ 後中（27,037）/ 前胸（6,361）/ 前片（3,370）/ 後片（3,071）/ 胸（2,167）— 都是 piece boundary 不是 detail zone
- 反摺（10,159）— 動作不是部位（腰頭反折/褲口反折/袖口反折 context-dependent，已用 method 反向 scan 救回部分）

**要改善** → 跟 IE Bible team 商量是否加 FC/BC/FB code 進 schema

### ISO 81% 沒對到（574,206 constructions）
**原因**：method text 本身就沒寫機種，不是漏抽
- 含官方 ISO 括號 (301)/(401)/... 的 constructions **只佔 0.3%**（2,299 / 708,425）
- bracket 與 iso 100% 相符，沒 bug
- 「車死」keyword 258 件全部命中，只 2 個被「請確認」negative filter 正確擋下

**要從 19% → 70%+** → 走 `l1_iso_recommendations_v1.json` 加 `iso_recommended` 欄位（推薦不等於實際，下游需分清楚）

### Negative filter 高精度設計
正確過濾的非做工內容：
- `^車線:` / `^針密:` / `^線材:` — 規格不是方法
- `洗標#` / `洗標-` / `^洗標` — 標籤名/位置
- `^圖#` / `^圖號` / `^圖片` — 圖號參照
- `請改善` / `請修正` / `請確認` / `請檢查` / `請注意` — QC 評語
- `反黃尺寸` / `^尺寸表` — 尺寸標註

⚠ 曾誤殺合法 sewing instruction（「距袋口邊 3/8" 壓單針平車」），已移除過頭 pattern。

---

## 七、改版歷程

| 日期 | 版本 | 主要改動 |
|------|------|---------|
| 2026-05-12 第 1 輪 | v1 | 移除 PNG render（18.8 min → 2.2 min）+ 加中文 keyword + slide score + zone keyword |
| 2026-05-12 第 2 輪 | v2 | 對齊 `l1_standard_38.json` + `iso_dictionary.json` 官方 |
| 2026-05-12 第 3 輪 | v2.1 | 補袖→AH / 鎖眼→HL / 11 個 ISO keyword / negative filter / 修 negative filter 過頭誤殺 |
| 2026-05-12 第 4 輪 | v2.2 | ISO_BRACKET_RE 顯式抽 + 鎖鏈順序前移 + zone-fallback L1 + 14 官方 ISO 完整對齊 |
| 2026-05-12 確認 | final | 19% iso 已是天花板（含括號 construction 只佔 0.3%）|

---

## 八、下游消費

`outputs/extract/pptx_facets.jsonl` 餵兩條線：

1. **Bible 五階層**（`l2_l3_ie/`）— construction 的 (zone, L1, iso) 三元組當 IE actuals 驗證資料
2. **m7 pipeline**（`m7_designs.jsonl`）— construction 進 design.constructions 欄位，下游 construction recipe 推論器吃

完整下游路徑見 `stytrix-techpack/CLAUDE.md` Part A 資料夾分工表。
