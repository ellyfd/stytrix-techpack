# M7 PullOn Source Schema (v3)

聚陽 Windows 端 `M7_Pipeline/scripts/build_m7_pullon_source_v3.py` 產的兩個檔案,
push 進 `data/ingest/m7_pullon/`,給 platform Phase 3 build_recipes_master 跟 Phase 2
derive view 使用。

## 設計原則

> **「所有資料都要想最安全和最大化的內容,除非是 Bible,不然每一款要帶的資料要越齊越好」**
> (Elly, 2026-05-08)

1. **Bible 不污染**:`l2_l3_ie/*.json` 38 檔保持 canonical 五階字典(從 xlsx 衍生),per-design noise 不進 Bible
2. **每款帶完整履歷**:per-EIDH 不只帶 6-dim key,而是 M7 列管 42 cols + m7_report 33 cols + 訂單情報 + IE summary + techpack 統計都帶
3. **同欄位多 source 並存**:fabric 不只一個來源,所有能拿到的都記,加 consensus + confidence
4. **無資料時不刪除整筆**:任一欄缺 → 寫 null,留 schema 結構

## 兩個 Output 檔

### `m7_pullon_source.jsonl` — Aggregated source (給 platform Phase 3 用)

每筆 = 一組 6-dim key 的聚合 stat。

```jsonl
{
  "key": {
    "gender": "WOMEN",
    "dept": "ACTIVE",
    "gt": "BOTTOM",
    "it": "LEGGINGS",
    "fabric": "KNIT",
    "l1": "WB"
  },
  "source": "m7_pullon",
  "aggregation_level": "same_bucket",
  "n_total": 3821,
  "confidence": "high",
  "client_distribution": [
    {"client": "ONY", "n": 1200, "pct": 31.4}
  ],
  "by_client": {
    "ONY": {
      "knit": [
        {
          "l2": "剪接腰頭_整圈",
          "shapes": [
            {
              "l3": "一片式腰頭_腰頂整圈鬆緊帶",
              "methods": [
                {
                  "l4": "(1)平車接合(2)縫份燙開",
                  "l5_steps": [
                    {
                      "l5": "做記號",
                      "skill": "C",
                      "primary": "副",
                      "machine": "平車-細針距",
                      "size": "12\"-14\"",
                      "sec": 27.5
                    }
                  ]
                }
              ]
            }
          ]
        }
      ],
      "woven": []
    }
  },
  "design_ids": ["ONY25HOVDD01_2"],
  "n_unique_designs": 152,
  "ie_total_seconds": 142933.7
}
```

**用途**:platform `star_schema/scripts/build_recipes_master.py` 的 `build_from_m7_pullon()` 讀。

### `m7_pullon_designs.jsonl` — Per-EIDH 完整履歷(給 Phase 2 derive 用)

每筆 = 一個 EIDH 的所有資料。

```jsonl
{
  "eidh": "323914",
  "design_id": "DAW26322_Q426",
  "style_no_internal": "10405493",
  "season": "FA26",
  "client": {
    "name": "DICKS SPORTING GOODS",
    "code": "DKS"
  },

  "fabric": {
    "value": "KNIT",
    "confidence": "high",
    "sources": {
      "m7_wk": {"raw": "KNIT", "inferred": "knit"},
      "bom_metadata": {
        "fabric_name": "Scuba",
        "fabric_ingredients": "Polyester/Spandex 90/10",
        "inferred": "knit"
      },
      "ssrs_machine_inferred": {
        "knit_machine_steps": 6,
        "woven_machine_steps": 0,
        "inferred": "knit"
      },
      "subgroup_hint": null,
      "item_hint": {"raw": "Pull On Pants", "inferred": null}
    }
  },

  "classification": {
    "gender": {"value": "WOMEN", "source": "m7_product_category"},
    "dept": {"value": "ACTIVE", "source": "derive_dept"},
    "gt": {"value": "BOTTOM", "source": "fixed_pullon"},
    "it": {"value": "LEGGINGS", "source": "derive_item_type"},
    "subgroup": "WAC",
    "program": "BUTTERSOFT",
    "item": "Pull On Pants"
  },

  "five_level_steps": [
    {
      "row_index": 1,
      "category_zh": "腰頭", "l1": "WB",
      "l2": "剪接腰頭_整圈", "l3": "...", "l4": "...", "l5": "做記號",
      "primary": "主", "skill": "C", "machine": "平車-細針距",
      "size": "12\"-14\"", "sec": 27.5
    }
  ],
  "n_steps": 61,
  "ie_total_seconds": 1863.7,

  "techpack_coverage": {
    "callout_count": 81,
    "vlm_facts_count": 0,
    "has_techpack_pdf_or_pptx": true
  },

  "order": {
    "quantity_dz": "5592.00",
    "fabric_spec": "Scuba",
    "fabric_ingredients": "Polyester/Spandex 90/10",
    "evaluation_type": "圖估(Pic Evaluation)",
    "origin": "SVN",
    "approval_date": "2026/3/15 ...",
    "reviewer": "SELINACHEN",
    // (註:聚陽端推進來時 order block 還含 performance_cost / normal_cost /
    //  total_amount_usd_dz 等成本/報價欄位 — **平台端不消費**,做工 / IE 用途
    //  不做成本計算。下游 build_recipes_master / derive view 都不讀這幾欄。)
  },

  "ie_breakdown_summary": {
    "sewing_ie": "0.95",
    "cutting_time": "...",
    "ironing_time": "...",
    "package_time": "...",
    "total_time": "...",
    "total_ie": "...",
    "標打": "119.7",
    "實打": "126.0",
    "ie_ratio": "0.95"
  },

  "sources": {
    "csv_5level_path": "m7_organized_v2/csv_5level/323914_..._DKS_DAW26322_Q426.csv",
    "m7_index_row": {"_42_cols": "preserved"},
    "m7_report_row": {"_33_cols": "preserved"},
    "techpack_folder": "\\\\192.168.1.220\\TechPack\\TPK\\10420112\\核樣1",
    "five_level_url": "http://nt-net2/MTM/Report/M6FiveLevelReport.aspx?EIDH=323914",
    "detail_url": "http://nt-netsql2/...",
    "sketch_url": "http://nt-net1.makalot.com.tw/sampleimage/..."
  },

  "_metadata": {
    "build_version": "v3_maximize",
    "step": "step2_designs_per_eidh",
    "built_at": "2026-05-08T07:23:00Z"
  }
}
```

## Fabric Multi-Source Consensus 邏輯

| Source | 來源 | Weight |
|---|---|---:|
| `m7_wk` | M7 列管表 W/K 欄 | 3 |
| `bom_metadata` | m7_report.jsonl fabric_name + ingredients | 2 |
| `ssrs_machine_inferred` | csv_5level machine_name 統計(圓編=knit / 劍杆=woven) | 1 |
| `subgroup_hint` | M7 列管 Subgroup 欄含 KNIT/WOVEN keyword | 1 |
| `item_hint` | M7 Item 欄含 LEGGING → knit | 1 |

Consensus rule:
1. 各 source vote(knit/woven 各記票)
2. 取 majority value
3. confidence:
   - `high` ⇐ 有 m7_wk 確認(現況 100% 都有)
   - `medium` ⇐ 沒 m7_wk 但 ≥2 source 全 agree
   - `low` ⇐ 1 source only
   - `none` ⇐ 全沒推得出

## 升級 / Fallback 路徑

未來 M7 W/K 不可得時(對外開放中小品牌、歷史款),fabric 走 fallback:
1. M7 W/K 沒 → 讀 BOM `fabric_name`(Knit Jersey / Woven Twill 等)
2. BOM 也沒 → 統計 csv machine_name 推
3. 都沒 → mark `confidence: none`,讓 derive view 標 `_warning: fabric_unknown`

## 已知限制

| 項目 | 現況 | 治理計畫 |
|---|---|---|
| Callout coverage | 26%(1,021 / 3,900) | 補跑 PDF VLM(Task #1 已 done 第一批 142 件) |
| BOM fabric_spec coverage | 78% | m7_report.jsonl 沒蓋的 EIDH 要補拉 |
| SSRS placeholder L4 | 96.9% (`new_method_describe_*`) | IE 部門治理任務,逐筆填正規 Method_Describe |
| SSRS new_part_* L2 | 11 個 / 68 筆 | 同上 |

## 維護者快速參考

升級 M7 PullOn data 流程:
1. 拉新一輪 M7 索引 + csv_5level + m7_report
2. 跑 `python scripts/build_m7_pullon_source_v3.py`
3. 看 stats(fabric coverage / callout coverage 趨勢)
4. push 兩個 jsonl 到 platform `data/ingest/m7_pullon/`
5. CI 觸發 build_recipes_master + Phase 2 derive

CI 觸發路徑:`.github/workflows/rebuild_master.yml` 已 trigger on `data/ingest/m7_pullon/` push(2026-05-08 PR #283 加的)。
