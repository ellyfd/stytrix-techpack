# Phase 2 — Derive Views Spec (v3, 命名乾淨)

> **狀態(2026-05-11)**:Phase 2 View A + B 接線完成,38 檔 Bible 已升級為 dict schema,`l2_l3_ie_by_client/` 已退役 git rm。**View C designs_index per-EIDH 在 2026-05-09 retired** — 雖然 derive script 寫好且 3,900 個 per-EIDH 檔產出過,但 audit 發現前端無 UI 消費,刪除避免 dead 產物 + 縮 repo size。本檔仍保留 View C 設計章節作為**未來重啟參考**(若前端要做 EIDH 詳情頁可重接)。實作對應 Step 4a/4b 在 `.github/workflows/rebuild_master.yml`。
>
> **2026-05-11 兩個重要修正**:
>
> 1. **`derive_bible_actuals.py` idempotency 修**:Phase 2.3 原版對已是 dict schema 的 step 直接 pass-through(只把 list-form 的 step 重算),導致 Bible 第一次升級 bake 了當時的 brand 後就 freeze,後續 m7_pullon source 新增 brand 不會反映到 `actuals.by_brand`(`--all --in-place` 重跑 0 diff)。修法:dict step 也走完整 lookup → recompute → 寫入(actuals empty 時清掉,避免殘留)。Bible 從 10 brand → 21 brand,大小 73.7 → 79.1 MB(+7%)。
>
> 2. **新增 Step 4c `scripts/core/build_brands.py`**:從 `data/ingest/m7_pullon/entries.jsonl` 聚合產 `data/runtime/brands.json`(~1.8 KB)。前端 `index.html` 把硬寫 10 entry 的 `const BRANDS = [...]` 換成 boot 時 fetch 這個檔,新 brand 進 m7_pullon → CI 重產 brands.json → 用戶 reload 看到。這個 derive 不算 Phase 2 view(沒從 master.jsonl 衍生),但 workflow 排在 4b 之後,共用一次 m7_pullon 讀取。

`build_recipes_master.py` Step 3 產 master.jsonl 後,從 master + per-EIDH designs 衍生**多個視角**的 view。

---

## 設計原則(Elly,2026-05-08)

1. **一個 Bible(`l2_l3_ie/` 38 檔)** — 唯一一份,所有 source 在同一條 L5 上各自填料
2. **Bible 不污染** ≠ 不能加新欄位;意思是:
   - L1-L5 樹狀結構由 IE xlsx 決定,不可被 per-design 改
   - canonical 詞彙(`**手工類` 等)不可被 SSRS placeholder 污染
   - **`new_part_*` / `new_shape_design_*` / `new_method_describe_*` 全部拉掉,不論在哪都不要**
3. **每款帶完整履歷** — per-EIDH 不只帶 6-dim key,M7 列管 42 cols + m7_report 33 cols + 訂單情報全帶
4. **資料越齊越好** — 無資料時寫 null,不刪整筆

---

## 核心架構

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3 MASTER (build_recipes_master.py)                            │
│  data/master.jsonl  ← single source of truth (做工 only)            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ derive
        ┌─────────────────────┼──────────────────────────┐
        ↓                     ↓                          ↓
View A:                  View B:                    View C:
data/recipes_master.json l2_l3_ie/<L1>.json (38 檔) data/runtime/designs_index/<EIDH>.json
(generic ISO consensus)  (Bible 增強版,同檔多源)   (per-EIDH lazy fetch)
```

**沒有「by_client」目錄,沒有「augmented」目錄,沒有「overlay」概念**。
Bible 38 檔本身被增強 — 在每個 L5 step 旁加 `actuals` 欄,由 m7_pullon 來源填。

---

## View A — `data/runtime/recipes_master.json` (已實裝)

**用途**:通用模型 ISO consensus 推薦。
**結構**:扁平 entries by 5-dim key,iso_distribution + methods cascade。
**Source**:`data/master.jsonl` 經 `star_schema/scripts/derive_view_recipes_master.py` 剝 `_m7_*` 內部欄位後輸出。

實裝順序:`build_recipes_master.py` 先寫完整 master.jsonl + master.meta.json,Step 4a 跑 `derive_view_recipes_master.py` 把每筆 entry 的 `_m7_*` 內部欄位剝掉(那些欄位是給 View B/C 用的,前端不消費)覆寫 `data/runtime/recipes_master.json`,線上 size ~15x 縮減。

---

## View B — `l2_l3_ie/<L1>.json` (38 檔, schema 升級,內容增強)

**用途**:**完整 Bible** — 每個 L5 step 上掛各 source 填料。

**現況**:
- `l2_l3_ie/` 38 檔是 IE xlsx 衍生的純 canonical 字典(每 L5 step = `[name, grade, sec, primary]` 或 5 元素含 machine)
- `l2_l3_ie_by_client/` 26 檔(retire,Phase 2 直接砍)— 命名錯且 schema 帶 SSRS raw L4 bug,功能併入 `l2_l3_ie/`

**Phase 2 升級**:同 38 檔位址,schema 升級成 list-of-dict 含完整 source 填料。

### Schema(升級後)

```json
{
  "l1": "腰頭",
  "code": "WB",
  "knit": [
    {
      "l2": "剪接腰頭_整圈",
      "shapes": [
        {
          "l3": "一片式腰頭_腰頂整圈鬆緊帶",
          "methods": [
            {
              "l4": "(1)平車接合(2)縫份燙開",
              "steps": [
                {
                  "l5": "做記號",
                  "ie_standard": {
                    "sec": 25.0,
                    "grade": "C",
                    "primary": "副"
                  },
                  "actuals": {
                    "n_steps": 50,
                    "n_designs": 25,
                    "sec_median": 27.5,
                    "sec_p25": 25.0,
                    "sec_p75": 30.0,
                    "by_brand": {
                      "ONY": {"sec_median": 27.5, "n_designs": 12},
                      "GAP": {"sec_median": 23.0, "n_designs": 8},
                      "DKS": {"sec_median": 28.0, "n_designs": 5}
                    },
                    "machine_distribution": {
                      "平車-細針距": 0.85,
                      "燙工-手燙": 0.15
                    },
                    "size_distribution": {
                      "12\"-14\"": 0.40,
                      "9\"-11\"": 0.35
                    }
                  }
                }
              ]
            }
          ]
        }
      ]
    }
  ],
  "woven": [],
  "_metadata": {
    "version": "phase2",
    "generated_at": "...",
    "sources": ["xlsx 五階層展開項目_20260507", "m7_pullon (4644 EIDH)"],
    "n_l5_steps_total": 271,
    "n_l5_steps_with_actuals": 154,
    "actuals_coverage_pct": 56.8
  }
}
```

**Schema 規則**:
- 每個 L5 step 是 dict(不是 list)
- `ie_standard` 必有(從 xlsx)
- `actuals` 可有可無(只有 m7_pullon 跑過該 path 才有)
- 未來新 source(callouts 等)再加同層 key,**不破壞 existing schema**

### `new_*` placeholder 過濾規則

從 m7_pullon 進來的資料,**任一以下情況整筆 row drop,不進 Bible**:
- L2 含 `new_part_` 開頭
- L3 含 `new_shape_design_` 開頭
- L4 含 `new_method_describe_` 開頭
- L5 含 `(NEW)` 開頭

理由:這些是 SSRS placeholder,IE 部門還沒填正規詞,進 Bible 會污染 canonical 結構。

**不另留 `_unmapped` 區**(user 指示「拉掉」)— 治理在聚陽端 SSRS 系統做,不污染 platform。

### Schema breaking change 對 frontend 影響

舊 `l2_l3_ie/<L1>.json` 的 `methods[].steps[]` 是 list of `[name, grade, sec, primary, machine?]`。
新 schema 是 list of dict。Frontend reader 要改:

```javascript
// 舊
const stepName = step[0];
const grade = step[1];
const sec = step[2];

// 新
const stepName = step.l5;
const grade = step.ie_standard.grade;
const sec = step.ie_standard.sec;
const brandActuals = step.actuals?.by_brand;  // optional
```

---

## View C — `data/runtime/designs_index/<EIDH>.json` (NEW 目錄, lazy fetch) — RETIRED 2026-05-09

> **退役狀態**:本章節保留為**未來重啟參考**。曾於 2026-05-08 實裝(Step 4c + 3,900 檔產出),但 2026-05-09 audit 發現 `index.html` 並無 EIDH 詳情頁 fetch 這些檔,屬 dead 產物。已 git rm 整個目錄 + `derive_view_designs_index.py` script + workflow Step 4c。若未來前端要做 EIDH 詳情頁,可從 `data/ingest/m7_pullon/designs.jsonl.gz` 重接 derive。

**用途**:Frontend 看單一 EIDH 詳情時 fetch。
**Source**:`m7_pullon_designs.jsonl` 拆成 per-EIDH 個別檔。

**結構**:對應 `m7_pullon_designs.jsonl` 每筆 entry,拆 3,900 個檔。每檔 ~18 KB,適合 lazy fetch。

跟 `l2_l3_ie/<L1>.json` lazy-fetch pattern 一致。

---

## Derive Pipeline

```
build_recipes_master.py (existing, 修出 master.jsonl)
         ↓
   data/master.jsonl (single source of truth, 做工 only)
         ↓
   ┌─────┴────────────────────────────────────────────┐
   ↓                                                  ↓
derive_view_recipes_master.py    derive_bible_actuals.py (NEW)
   ↓                                                  ↓
data/recipes_master.json         l2_l3_ie/<L1>.json (38 檔, 增強版)

m7_pullon_designs.jsonl
         ↓
derive_view_designs_index.py (NEW)
         ↓
data/runtime/designs_index/<EIDH>.json (3,900 檔)
```

---

## Implementation Plan

### Phase 2.1 — Restructure build_recipes_master

修 `star_schema/scripts/build_recipes_master.py`:
- 加 `OUT_MASTER_JSONL = data/master.jsonl` — 寫所有 entries 含 `_m7_*` 內部欄位
- 現有 `data/recipes_master.json` 保留為 Phase 2.2 的 derive output

### Phase 2.2 — Write derive_view_recipes_master.py

新檔 `star_schema/scripts/derive_view_recipes_master.py`:
- Read `data/master.jsonl`
- Strip `_m7_*` 內部欄位
- Output `data/recipes_master.json`(跟現況 schema 一致)

### Phase 2.3 — Write derive_bible_actuals.py(★ 核心)

新檔 `star_schema/scripts/derive_bible_actuals.py`:
- Read `l2_l3_ie/<L1>.json` 現有版(從 xlsx 衍生的純 canonical)
- Read `data/ingest/m7_pullon/entries.jsonl`(m7_pullon source)
- For each L1: walk Bible 樹,attach `actuals` per L5 step (median sec / by_brand / machine 分布 / size 分布)
- **過濾 `new_part_*` / `new_shape_design_*` / `new_method_describe_*` / `(NEW)*` 全 drop**
- Output overwrite `l2_l3_ie/<L1>.json`(38 檔)
- Schema 升級:steps from list → list-of-dict
- 砍 `l2_l3_ie_by_client/` 整個目錄(retire)

### Phase 2.4 — Write derive_view_designs_index.py

新檔 `star_schema/scripts/derive_view_designs_index.py`:
- Read `data/ingest/m7_pullon/designs.jsonl.gz`(or .jsonl)
- 拆每 EIDH 一個檔 → `data/runtime/designs_index/<EIDH>.json`
- 寫 `data/runtime/designs_index/_index.json` 帶 EIDH list + size

### Phase 2.5 — Wire workflow

修 `.github/workflows/rebuild_master.yml`:
- Step 3 結束後加 Step 4: 跑 3 支 derive script
- Step 4 結果 commit `data/recipes_master.json` + `l2_l3_ie/` + `data/runtime/designs_index/`
- 同 commit 把 `l2_l3_ie_by_client/` 26 檔 git rm

### Phase 2.6 — Frontend integration

修 `index.html`:
- 通用模型 ISO consensus 仍用 `data/recipes_master.json`
- 五階層字典 fetch `l2_l3_ie/<L1>.json`(新 schema list-of-dict)
- EIDH 詳情頁:fetch `data/runtime/designs_index/<EIDH>.json`
- ⚠ 舊 `l2_l3_ie_by_client/` 26 檔不再存在,frontend 對應路徑要拔掉

---

## 規則 / 邊界

| 維度 | l2_l3_ie/(增強後) | 規則 |
|---|---|---|
| Schema | L1-L5 樹 + 每 L5 dict 含 ie_standard / actuals / 未來 callouts | 樹結構不變,加 key 不破壞 |
| 樹結構決定權 | IE xlsx | 唯一 |
| canonical 詞彙 | xlsx | 唯一 |
| `new_*` placeholder | **drop** | 不進 Bible 任何地方 |
| 修改責任 | CI 自動產 | 手改禁止 |

⛔ **`l2_l3_ie/` 38 檔在 Phase 2 後永遠不手改** — CI 自動產的衍生檔。
要改規則,改 derive script;要補資料,push 進 m7_pullon ingest 或更新 xlsx。

---

## 變動規劃彈性

未來新 source(例:techpack VLM callouts)整合:
- 不改 Bible structure
- 不改 m7_pullon source schema
- 只改 `derive_bible_actuals.py` 加 `callouts` key 在每個 L5 dict 同層

source 跟 view 解耦。

---

## 完成度(2026-05-09)

- [x] Phase 2.1: restructure build_recipes_master 出 master.jsonl(L94-95 `OUT_MASTER_JSONL` / `OUT_MASTER_META`)
- [x] Phase 2.2: `star_schema/scripts/derive_view_recipes_master.py`(Step 4a)
- [x] Phase 2.3: `star_schema/scripts/derive_bible_actuals.py`(Step 4b,核心)— 過濾 `new_*` placeholder + 升級 38 檔 dict schema + 掛 m7_pullon `actuals`
- [⊘] Phase 2.4: `star_schema/scripts/derive_view_designs_index.py`(Step 4c)— 曾實裝產 per-EIDH 3,900 檔,**2026-05-09 retired**(前端無 UI 消費,移除避免 dead 產物)
- [x] Phase 2.5: wire CI(`.github/workflows/rebuild_master.yml` Step 4a/4b/4c)+ `l2_l3_ie_by_client/` git rm 完成
- [x] Phase 2.6: frontend integration(`index.html` `readStepRow()` schema-agnostic Bible reader,`filterBibleByBrand()` helper 從 `actuals.by_brand` 過濾)

預計 5 個 PR(2.1+2.2 合一,2.3, 2.4, 2.5, 2.6)。
