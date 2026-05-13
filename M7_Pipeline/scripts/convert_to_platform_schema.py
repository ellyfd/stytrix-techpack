"""convert_to_platform_schema.py — 把 v6.4 (6-dim) 轉成 stytrix-techpack 平台格式 (5-dim)

Platform schema (data/recipes_master.json):
  {
    "generated_at": "...",
    "source_versions": {...},
    "stats": {...},
    "entries": [
      {
        "key": {"gender":"WOMENS","dept":"GENERAL","gt":"PANTS","it":"PANT","l1":"WB"},
        "aggregation_level": "same_bucket",
        "source": "m7_pullon_v6.4",
        "n_total": N,
        "iso_distribution": [{"iso":"406","n":9,"pct":69.2}, ...],
        "methods": [{"name":"BINDING","n":5,"pct":50.0}, ...]
      }
    ]
  }

Key mappings (M7 v6.4 → Platform):
  gender:  WOMEN/MEN/BOY/GIRL/BABY → WOMENS/MENS/BOYS/GIRLS/KIDS
  dept:    ACTIVE/RTW/FLEECE       → GENERAL
           SLEEPWEAR / SLEEPWEAR/RTW → SLEEPWEAR
           UNKNOWN                  → GENERAL
  gt:      BOTTOM                  → 從 it 推 (PANTS / SHORTS / LEGGINGS)
  it:      PANTS                   → PANT
           SHORTS                  → SHORTS
           LEGGINGS                → LEGGINGS
           JOGGERS                 → JOGGERS (gt 仍是 PANTS)
  wk:      KNIT/WOVEN              → DROP（合併兩個 wk 的同 key）

用法:
  python scripts\\convert_to_platform_schema.py
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES_IN = ROOT / "outputs" / "platform" / "recipes_master_v6.jsonl"
OUT = ROOT / "outputs" / "platform" / "recipes_master_platform.json"


# ════════════════════════════════════════════════════════════
# Mapping 表
# ════════════════════════════════════════════════════════════

GENDER_MAP = {
    "WOMEN": "WOMENS",
    "MEN": "MENS",
    "BOY": "BOYS",
    "GIRL": "GIRLS",
    "BABY": "KIDS",
    "KIDS": "KIDS",
    "UNKNOWN": "GENERAL",  # 不太該出現，但保險
}

DEPT_MAP = {
    "ACTIVE": "GENERAL",
    "RTW": "GENERAL",
    "FLEECE": "GENERAL",
    "SLEEPWEAR": "SLEEPWEAR",
    "SLEEPWEAR/RTW": "SLEEPWEAR",
    "UNKNOWN": "GENERAL",
}

# IT → (gt, it_platform) — 平台的 gt 是大類，it 是細類
IT_TO_GT_IT = {
    "PANTS":    ("PANTS",    "PANT"),
    "SHORTS":   ("SHORTS",   "SHORTS"),
    "LEGGINGS": ("LEGGINGS", "LEGGINGS"),
    "JOGGERS":  ("PANTS",    "JOGGERS"),
    "CAPRI":    ("PANTS",    "CAPRI"),
    "SKIRT":    ("SKIRT",    "SKIRT"),
}


def map_key(v6_key: dict) -> dict | None:
    """v6.4 key (6-dim) → platform key (5-dim, drop wk)
    回 None 表示無法映射（如 wk=UNKNOWN 且 it 不在 mapping）"""
    gender = GENDER_MAP.get(v6_key.get("gender", ""), "GENERAL")
    dept = DEPT_MAP.get(v6_key.get("dept", ""), "GENERAL")
    it_v6 = v6_key.get("it", "")
    if it_v6 not in IT_TO_GT_IT:
        return None
    gt, it = IT_TO_GT_IT[it_v6]
    l1 = v6_key.get("l1", "")
    if not l1:
        return None
    return {
        "gender": gender,
        "dept": dept,
        "gt": gt,
        "it": it,
        "l1": l1,
    }


def merge_recipes(recipes_v6: list) -> list:
    """合併 v6.4 多筆 (KNIT + WOVEN 拆兩 entry) → platform 1 筆 (drop wk)
    Key collision 時：iso/methods 用加權合併
    """
    grouped = defaultdict(list)
    for r in recipes_v6:
        new_key = map_key(r.get("key", {}))
        if new_key is None:
            continue
        key_tup = (new_key["gender"], new_key["dept"], new_key["gt"], new_key["it"], new_key["l1"])
        grouped[key_tup].append((new_key, r))

    out = []
    for key_tup, items in grouped.items():
        new_key = items[0][0]

        # 合併 n_total
        total_n = sum(r.get("n_total", 0) for _, r in items)
        if total_n == 0:
            continue

        # 合併 iso_distribution（按 raw count 加總）
        iso_cnt = defaultdict(int)
        for _, r in items:
            for iso in r.get("iso_distribution", []):
                iso_cnt[iso.get("iso", "")] += iso.get("n", 0)
        iso_total = sum(iso_cnt.values()) or 1
        iso_dist = sorted(
            [{"iso": iso, "n": n, "pct": round(n / iso_total * 100, 1)}
             for iso, n in iso_cnt.items() if iso],
            key=lambda x: -x["n"],
        )

        # 合併 methods
        method_cnt = defaultdict(int)
        for _, r in items:
            for m in r.get("methods", []):
                method_cnt[m.get("name", "")] += m.get("n", 0)
        method_total = sum(method_cnt.values()) or 1
        methods = sorted(
            [{"name": name, "n": n, "pct": round(n / method_total * 100, 1)}
             for name, n in method_cnt.items() if name],
            key=lambda x: -x["n"],
        )

        # 確認 confidence
        confidence_levels = [r.get("confidence", "low") for _, r in items]
        # 取最高（high > medium > low > very_low）
        rank = {"high": 4, "medium": 3, "low": 2, "very_low": 1}
        best_conf = max(confidence_levels, key=lambda c: rank.get(c, 0))

        # 取 IE 工時平均（取所有 entry 的 total_avg_seconds 加權平均）
        total_avgs = [r.get("total_avg_seconds") for _, r in items if r.get("total_avg_seconds")]
        avg_sec = round(sum(total_avgs) / len(total_avgs), 1) if total_avgs else None

        # client_distribution 也合併
        client_cnt = defaultdict(int)
        for _, r in items:
            for c in r.get("client_distribution", []):
                client_cnt[c.get("client", "")] += c.get("n", 0)
        client_total = sum(client_cnt.values()) or 1
        client_dist = sorted(
            [{"client": c, "n": n, "pct": round(n / client_total * 100, 1)}
             for c, n in client_cnt.items() if c and c != "UNKNOWN"],
            key=lambda x: -x["n"],
        )

        entry = {
            "key": new_key,
            "aggregation_level": "same_bucket",
            "source": "m7_pullon_v6.4",
            "n_total": total_n,
            "iso_distribution": iso_dist,
            "methods": methods,
            # 額外欄位（平台不一定吃，但留著）
            "confidence": best_conf,
            "client_distribution": client_dist,
            "avg_seconds": avg_sec,
            "n_designs_aggregated": sum(r.get("n_designs", 0) for _, r in items),
            "n_clients": len(client_cnt),
        }
        out.append(entry)

    return out


def main():
    print(f"[1] Load v6.4 recipes from {RECIPES_IN}")
    if not RECIPES_IN.exists():
        print(f"[!] {RECIPES_IN} 不存在")
        sys.exit(1)

    recipes_v6 = []
    with open(RECIPES_IN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recipes_v6.append(json.loads(line))
            except Exception:
                continue
    print(f"    {len(recipes_v6)} recipes (6-dim)")

    print("[2] Map v6.4 → platform 5-dim + 合併 wk 維度")
    entries = merge_recipes(recipes_v6)
    print(f"    {len(entries)} entries (5-dim, after wk merge)")

    # Stats by gender / dept / gt / it
    from collections import Counter
    by_gender = Counter(e["key"]["gender"] for e in entries)
    by_dept = Counter(e["key"]["dept"] for e in entries)
    by_gt = Counter(e["key"]["gt"] for e in entries)
    by_it = Counter(e["key"]["it"] for e in entries)
    by_l1 = Counter(e["key"]["l1"] for e in entries)
    by_conf = Counter(e["confidence"] for e in entries)

    print(f"\n  By gender: {dict(by_gender.most_common())}")
    print(f"  By dept:   {dict(by_dept.most_common())}")
    print(f"  By gt:     {dict(by_gt.most_common())}")
    print(f"  By it:     {dict(by_it.most_common())}")
    print(f"  Top L1 (10): {by_l1.most_common(10)}")
    print(f"  Confidence: {dict(by_conf.most_common())}")

    print("\n[3] 包成 platform schema")
    platform_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_versions": {
            "m7_pullon": "v6.4",
            "m7_pullon_path": "M7_Pipeline/outputs/platform/recipes_master_v6.jsonl",
            "bible": "五階層展開項目_20260402.xlsx",
        },
        "stats": {
            "total_entries": len(entries),
            "v6_input_count": len(recipes_v6),
            "by_gender": dict(by_gender),
            "by_dept": dict(by_dept),
            "by_gt": dict(by_gt),
            "by_it": dict(by_it),
            "by_confidence": dict(by_conf),
        },
        "entries": entries,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(platform_doc, f, ensure_ascii=False, indent=2)

    print(f"\n[output] {OUT}")
    print(f"  size: {OUT.stat().st_size:,} bytes")

    # Sample first 2 entries
    print("\n[sample] entries[0:2]:")
    for e in entries[:2]:
        print(json.dumps(e, ensure_ascii=False, indent=2)[:600] + "...")
        print()

    print("\n下一步：")
    print(f"  1. 把 {OUT} 複製到 stytrix-techpack repo:")
    print(f"     cp \"{OUT}\" C:\\temp\\stytrix-techpack\\data\\recipes_master_m7_pullon.json")
    print(f"  2. 或 merge 進現有 recipes_master.json (entries[] 加進去)")
    print(f"  3. 在 repo commit + push 後 Vercel 自動部署")


if __name__ == "__main__":
    main()
