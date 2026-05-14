# Per-brand `bodytype_variance` Schema(spec)

> **Status**: spec only — 待聚陽端 implement;前端已 ready(自動偵測 `_meta.per_brand` 切換 schema)。
> **作者**:Claude / Elly | **日期**:2026-05-14

## 為什麼要這份

### 現況問題

`data/runtime/bodytype_variance.json` 目前 **整檔 ONY-only**:

```json
{
  "_meta": { "source_brand": "ONY" },
  "BOYS|Blouse/Shirts|PLUS": { "m_size_comparison": {...} },
  "GIRLS|Blouse/Shirts|PLUS": {...},
  ...
}
```

Key 格式 `GENDER|GT|BODYTYPE` 沒有 brand 維度 — 整份檔的 delta 數值都是從 ONY 設計觀察出來的。

**使用者選 DKS / KOH / TGT 等其他 brand 時**,前端仍然套這份 ONY-only 資料算 Petite / Tall delta(例如 `Front Rise (Petite) -3/4"`)— 但這 `-3/4"` 是 ONY 內部打版的 Petite 調整量,**不一定適用 DKS**。

### 影響

| 用例 | 現況 | 風險 |
|---|---|---|
| ONY 使用者 | OK | 一致 |
| 其他 brand 使用者(DKS / KOH 等) | 看到 ONY 的 Petite / Tall delta | **誤導** — 該 brand 真實打版可能 -1/2" 或 -1" |
| 完全沒在 ONY 庫的 brand | 看到 cross-brand 套用的數字 | 更嚴重 |

短期前端對策(2026-05-14 已 ship):選非 ONY brand 時,身型 pill 旁邊出現 amber warning「⚠ Petite/Tall 從 ONY 外推」。使用者看得到資料來源不準。

長期應該:每個 brand 有自家的 bodytype delta。

## Schema 變更

### 改動 1:新增 `_meta.per_brand` flag

```json
{
  "_meta": {
    "per_brand": true,          // ← 新增,前端用來偵測 schema 切換
    "version": "v2",
    "generated_at": "...",
    "brands_with_data": ["ONY", "DKS", "KOH", "TGT", "ATH"]
  },
  ...
}
```

`per_brand: true` 時,前端切到 brand-aware lookup;`false` 或缺失時走現況單一 source_brand 模式(向後相容)。

### 改動 2:key 加 brand 前綴

```json
{
  "ONY|BOYS|Blouse/Shirts|PLUS": { "m_size_comparison": {...} },
  "DKS|BOYS|Blouse/Shirts|PLUS": { "m_size_comparison": {...} },
  "KOH|WOMENS|Pull On Pants|PETITE": {...},
  ...
}
```

Key 格式從 `<GENDER>|<GT>|<BODYTYPE>` 改 `<BRAND>|<GENDER>|<GT>|<BODYTYPE>`。

### 改動 3:fallback 設計

不是每個 brand 都有夠多 Petite / Tall 樣本(那是該 brand 內部歷史資料);沒資料的 (brand, gender, gt, bodytype) 組合應**省略**(不 emit),前端找不到 key 就回 `null` → pill 自動 disabled(走現有 `hasPetiteU` / `hasTallU` 邏輯)。

### 改動 4(選配):cross-brand fallback table

如果某 brand 沒有 Petite 資料,但 cross-brand 聚合有,可以加一個 fallback entry:

```json
{
  "_meta": {
    "per_brand": true,
    "fallback_enabled": true,
    "fallback_source_brand": "ONY"
  },
  "DKS|WOMENS|Tee|PETITE": null,          // DKS 該組合無資料
  "ONY|WOMENS|Tee|PETITE": {...},         // ONY 有
  "_FALLBACK|WOMENS|Tee|PETITE": {...}    // 跨 brand 聚合
}
```

前端找順序:`<brand>` → `_FALLBACK` → `null`(顯示 ⚠ 警告 + Petite/Tall 標明來自 fallback)。

## 計算邏輯(聚陽端)

預期由 `M7_Pipeline/scripts/build_bodytype_variance_per_brand.py`(新檔)實作。資料來源:

```
$BASE/_parsed/mc_pom_*.jsonl
  → 每筆 design 含 (brand, design_id, gender, gt, bodytype, POMs[])
  → bodytype 從 design size_run 或 attribute 推 (Regular / Petite / Tall / Plus)

聚合邏輯(per-brand):
  for each (brand, gender, gt, bodytype):
    pair_designs = [(reg_d, bt_d) for matched design pairs in same style_no]
    for each POM code:
      regular_M = median of POM.M in pair_designs[*].regular
      bodytype_M = median of POM.M in pair_designs[*].bodytype
      delta = bodytype_M - regular_M
    emit {brand, gender, gt, bodytype: {m_size_comparison: {pom_code: {regular_M, bodytype_M, delta}}}}
```

**最低 sample 門檻**:建議 N ≥ 5 pairs。低於該門檻不 emit per-brand entry(讓前端 fallback 走 cross-brand 或顯示 disabled)。

## Migration plan

| Phase | 動作 | Owner | 狀態 |
|---|---|---|---|
| 1 | 前端 warning UI(看 source_brand 跟 current brand 不符就標 ⚠)| platform | ✅ 已 ship(2026-05-14)|
| 2 | 前端自動偵測 `_meta.per_brand` flag,有就用 brand-aware key | platform | ✅ 已 ship(2026-05-14)|
| 3 | 聚陽端寫 `build_bodytype_variance_per_brand.py` | 聚陽 | 待動 |
| 4 | 聚陽端跑 build,push 新 schema 到 repo | 聚陽 | 待動 |
| 5 | Per-brand schema deploy,warning 自動消失(per_brand=true)| 自動 | 待 |
| 6 | (選配)cross-brand `_FALLBACK` aggregation | 聚陽 | 評估後決定 |

## Test plan(when implementing)

- [ ] `_meta.per_brand=true` flag 出現 → 前端 warning 自動消失
- [ ] DKS 選 Active+WOMENS+Pull On Pants+Petite → 拿到 DKS 自家 Petite delta(若有),不是 ONY 數字
- [ ] DKS 某 (gender, gt, bodytype) 沒資料 → Petite pill disabled(走 hasPetiteU=false 路徑)
- [ ] 既有 ONY 使用者:Petite/Tall delta 不變(per_brand schema 內 `ONY|...` entry 跟舊 `<gender>|<gt>|<bodytype>` entry 對齊)
- [ ] 沒有 brand 維度的舊資料(`per_brand` 缺/false)依然能跑(向後相容)

## 跟其他 spec 關係

- `docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md` — Bible(`l2_l3_ie/*.json`) 也是 per-brand `actuals.by_brand`,本檔是 POM 尺寸的 per-brand 等價設計
- `docs/architecture/DATA_PIPELINE_MAPPING.md` — bodytype_variance 在 `data/runtime/` 內;CI 不重產(現況沒在 rebuild_master.yml step 內),聚陽端跑外部 BASE 再 PR push
