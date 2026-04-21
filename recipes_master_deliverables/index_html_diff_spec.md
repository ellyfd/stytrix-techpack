# index.html Diff Spec — recipes_master.json + iso_dictionary.json 重構

> 對照 index.html 5,658 行版本。所有行號為上傳版本的行號。
> 改動 6 處，每處標示 DELETE/REPLACE/INSERT。

---

## 改動 1：State 宣告 — 3 fetch → 2 fetch

**位置：Line 2354–2360**（`isoLookupV43`, `isoLookupV4`, `bridgeV6` state 宣告）

```
DELETE Lines 2354-2360 (整段刪除):
  const [isoLookupV43, setIsoLookupV43] = useState(null);
  const [isoLookupV4, setIsoLookupV4] = useState(null);
  // v6 construction bridge ... (3 行註解)
  const [bridgeV6, setBridgeV6] = useState(null);

INSERT (替換為):
  // recipes_master.json: unified 4-layer lookup (同細類/同大類/通用/跨款)
  const [recipesMaster, setRecipesMaster] = useState(null);
  // iso_dictionary.json: ISO code → {zh, en, machine}
  const [isoDictionary, setIsoDictionary] = useState(null);
```

---

## 改動 2：Fetch 邏輯 — 3 fetch → 2 fetch

**位置：Line 2430–2447**（`if (!isoLookupV43 && appMode === "universal")` 三個 fetch block）

```
DELETE Lines 2430-2447 (整段刪除):
    if (!isoLookupV43 && appMode === "universal") {
      fetch('./General%20Model_Path2_Construction%20Suggestion/iso_lookup_factory_v4.3.json')
        ...
    }
    if (!isoLookupV4 && appMode === "universal") {
      fetch('./General%20Model_Path2_Construction%20Suggestion/iso_lookup_factory_v4.json')
        ...
    }
    if (!bridgeV6 && appMode === "universal") {
      fetch('./data/construction_bridge_v6.json')
        ...
    }

INSERT (替換為):
    if (!recipesMaster && appMode === "universal") {
      fetch('./data/recipes_master.json')
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(setRecipesMaster)
        .catch(err => console.error('載入 recipes_master 失敗:', err));
    }
    if (!isoDictionary && appMode === "universal") {
      fetch('./data/iso_dictionary.json')
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(setIsoDictionary)
        .catch(err => console.error('載入 iso_dictionary 失敗:', err));
    }
```

同時更新 useEffect 依賴陣列（如果有的話），確保 `recipesMaster` 和 `isoDictionary` 取代舊的三個 state。

---

## 改動 3：刪除 `buildIsoRef()` + `isoOptionsFor()`，新增 `lookupRecipesMaster()`

**位置：Line 219–318**（`buildIsoRef` + `isoOptionsFor` 兩個函數）

```
DELETE Lines 219-318 (整段刪除):
  /* ─── ISO 代碼 → {iso_zh, machine} ... */
  function buildIsoRef(lookupV4) { ... }

  /* ─── 通用模型:回傳目前 bucket 下該 L1 可選的 ISO 列表 ... */
  function isoOptionsFor(lookupV43, lookupV4, filters, l1Code) { ... }

INSERT (替換為):
/* ─── 通用模型:從 recipes_master 查 ISO（4 層 fallback）
   同細類(dept|gender|gt|it|l1) → 同大類(dept|gender|gt|l1)
   → 通用(gt|it|l1 then gt|*|l1) → 跨款(gt|l1)
   回傳: { iso, iso_zh, machine, pct, source, alternatives, methods, n_total } | null ─── */
function lookupRecipesMaster(master, isoDic, filters, l1Code) {
  if (!master || !l1Code) return null;
  const { dept, gender, gt, it } = filters || {};
  const entries = master.entries || [];
  const deptKey = V43_DEPT_ALIAS[dept] || "General";
  const genderKey = V43_GENDER_ALIAS[gender] || "UNISEX";
  const gtKey = V43_GT_ALIAS[gt] || gt;

  // Build lookup index (cached on master object for perf)
  if (!master._idx) {
    master._idx = {};
    for (const e of entries) {
      master._idx[e.key] = e;
    }
  }
  const idx = master._idx;

  // 4-layer fallback
  const tryKeys = [
    `${deptKey}|${genderKey}|${gtKey}|${it}|${l1Code}`,           // 同細類
    `${deptKey}|${genderKey}|${gtKey}|${l1Code}`,                  // 同大類
    `${gtKey}|${it}|${l1Code}`,                                     // 通用 (gt|it)
    `${gtKey}|*|${l1Code}`,                                         // 通用 (gt|*)
    `${gtKey}|${l1Code}`,                                           // 跨款
  ];
  // Also try UNISEX fallback for 同大類
  if (genderKey !== "UNISEX") {
    tryKeys.splice(2, 0, `${deptKey}|UNISEX|${gtKey}|${l1Code}`);
  }
  // Also try General dept fallback for 同大類
  if (deptKey !== "General") {
    tryKeys.splice(3, 0, `General|${genderKey}|${gtKey}|${l1Code}`);
    tryKeys.splice(4, 0, `General|${gtKey}|${l1Code}`);  // 跳過 gender
  }

  let hit = null;
  let hitSource = null;
  for (const k of tryKeys) {
    if (idx[k]) { hit = idx[k]; hitSource = hit.aggregation_level; break; }
  }
  if (!hit) return null;

  const dist = hit.iso_distribution || {};
  const sorted = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return null;

  const [topIso, topPct] = sorted[0];
  const isoInfo = (isoDic || {})[topIso] || {};

  const alternatives = sorted.slice(1, 6).map(([iso, pct]) => ({
    iso,
    pct: Math.round(pct * 100),
    count: null,  // recipes_master stores pct not raw count
  }));

  const methods = (hit.methods)
    ? Object.entries(hit.methods)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([name, count]) => ({ name, count }))
    : [];

  return {
    iso: topIso,
    iso_zh: isoInfo.zh || null,
    machine: isoInfo.machine || null,
    pct: Math.round(topPct * 100),
    source: hitSource,
    alternatives,
    methods,
    n_total: hit.n_total || 0,
  };
}
```

---

## 改動 4：`runConstruction` universal 分支 — 簡化為 `lookupRecipesMaster`

**位置：Line 2994–3127**（`if (appMode === "universal") { ... }` 整個 block）

這是最大的改動。現有的 ~130 行（含 duplicate `lookupV4()` 函數、bridge 索引建立、`isoOptionsFor` 呼叫）全部替換。

```
DELETE Lines 2994-3127 (整段刪除)

INSERT (替換為):
      // ── Path 2 通用模型 — recipes_master 4 層 fallback ──
      if (appMode === "universal") {
        const filters = { fabric, dept, gender, gt, it };
        const builtAll = detected.map((d, i) => {
          const result = lookupRecipesMaster(recipesMaster, isoDictionary, filters, d.code);
          return { d, result, i };
        });
        const builtFiltered = builtAll.filter(x => x.result && x.result.iso);
        const built = builtFiltered.map(({ d, result }, i) => {
          const l1 = L1_CODE_TO_NAME[d.code] || d.code;
          const label = `ISO ${result.iso}${result.iso_zh ? " · " + result.iso_zh : ""}${result.machine ? " · " + result.machine : ""}`;
          return {
            id: i + 1,
            l1,
            l1_code: d.code,
            l2: label,
            l2Base: null,
            source: d._fromPresence ? "struct" : "ai",
            conf: Number.isFinite(d.confidence) ? d.confidence : null,
            matchCode: null,
            px: Number.isFinite(d.x) ? d.x : 50,
            py: Number.isFinite(d.y) ? d.y : 50,
            side: d.side === "back" ? "right" : "left",
            ie: 0,
            action: "manual",
            isoConfidence: null,
            presenceTier: presenceByCode[d.code]?.tier_en || null,
            presencePct: presenceByCode[d.code]?.presence_pct ?? null,
            universal: {
              iso: result.iso,
              iso_zh: result.iso_zh,
              machine: result.machine,
              confidence: null,
              action: null,
              source: result.source,       // "同細類"|"同大類"|"通用"|"跨款"
              alternatives: result.alternatives,
              methods: result.methods,
              bridgeN: result.n_total,      // 改名但 UI 欄位維持 bridgeN 相容
            },
            methodIdx: 0, methodVariants: [],
            l2Idx: 0, l2Variants: [],
            l3Idx: 0, l3Variants: [],
            ai_l2_code: null, ai_l2_confidence: null, ai_l2_explanation: null,
            ai_l2_needs_text: false, ai_l2_merged_candidates: [],
            l3s: [],
          };
        });
        clearInterval(si);
        setCards(built);
```

> **注意**：`clearInterval(si)` 和 `setCards(built)` 之後的收尾邏輯（setCStep 等）保持不變。

---

## 改動 5：ISO 切換時的替代 ISO 查詢（Pain Point #2 修復）

**位置：Line 2845**（L1 下拉切換 ISO 的 `isoOptionsFor` 呼叫）

```
REPLACE Line 2845:
    const opts = isoOptionsFor(isoLookupV43, isoLookupV4, { fabric, dept, gender, gt, it }, l1Code);

WITH:
    const result = lookupRecipesMaster(recipesMaster, isoDictionary, { fabric, dept, gender, gt, it }, l1Code);
    const opts = result ? [{
      iso: result.iso, iso_zh: result.iso_zh, machine: result.machine,
      pct: result.pct, isPrimary: true, source: result.source,
    }, ...result.alternatives.map(a => ({
      iso: a.iso, iso_zh: (isoDictionary || {})[a.iso]?.zh || null,
      machine: (isoDictionary || {})[a.iso]?.machine || null,
      pct: a.pct, isPrimary: false, source: result.source,
    }))] : [];
```

也更新同區塊中引用 `opts[0].iso_zh` / `opts[0].machine` 的地方（應該已經相容）。

---

## 改動 6：UI 顯示 — source 標籤更新

**位置：Line 1095 附近**（universal card 顯示 `bridge v6 · n=` 的地方）

```
REPLACE Line 1095:
  {u.bridgeN != null && <span ...>bridge v6 · n={u.bridgeN}</span>}

WITH:
  {u.bridgeN != null && <span style={{ marginLeft: "6px", color: "#888", fontWeight: 500 }}>{u.source} · n={u.bridgeN}</span>}
```

```
REPLACE Line 1122:
  常見工法 · bridge v6

WITH:
  常見工法
```

---

## 不改的東西

| 項目 | 理由 |
|------|------|
| `V43_DEPT_ALIAS` / `V43_GENDER_ALIAS` / `V43_GT_ALIAS` (Line 206-217) | 保留。`lookupRecipesMaster` 繼續用這三張 alias 表做 filter normalization |
| `L1_CODE_TO_NAME` | 保留。UI 顯示用 |
| `sortedL1sForBucket()` | 保留。L1 排序用 partPresence，跟 ISO 查詢無關 |
| `rebuildCardFromL2()` | 保留。聚陽模式專用 |
| 聚陽模式(makalot) 整個 runConstruction 分支 | 不動 |
| 尺寸表 tab 全部 | 不動 |

---

## 需要放進 repo 的新檔案

```
data/recipes_master.json     ← build_recipes_master.py 產出 (601 KB)
data/iso_dictionary.json     ← 同上 (1.8 KB)
scripts/build_recipes_master.py  ← 合併 script
```

## 可刪除的舊檔案（確認後）

```
General Model_Path2_Construction Suggestion/iso_lookup_factory_v4.3.json  ← 已併入 recipes_master
General Model_Path2_Construction Suggestion/iso_lookup_factory_v4.json    ← 已併入 recipes_master
data/construction_bridge_v6.json                                           ← 已併入 recipes_master
```

---

## Validation Checklist

1. ☐ `fetch('./data/recipes_master.json')` 成功載入
2. ☐ `fetch('./data/iso_dictionary.json')` 成功載入
3. ☐ 通用模式：L1 卡片正確顯示 ISO + 中文名 + 機種
4. ☐ 通用模式：替代 ISO 有顯示 pct%
5. ☐ 通用模式：source 標籤顯示「同細類/同大類/通用/跨款」
6. ☐ L1 下拉切換後 ISO 正確更新（不會 empty）
7. ☐ 聚陽模式完全不受影響
8. ☐ 無 console error
