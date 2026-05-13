"""全 brand XLSX 收成 — metadata + MC POM + construction_iso_map"""
import json
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs" / "extract" / "xlsx_facets.jsonl"

stats = defaultdict(lambda: {
    "total": 0, "ok": 0, "no_xlsx": 0,
    "meta": 0, "mc": 0, "poms": 0, "iso_map": 0,
})

with open(OUT, encoding="utf-8") as f:
    for line in f:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        cl = d.get("client_code") or "?"
        s = stats[cl]
        s["total"] += 1
        st = d.get("_status", "?")
        if st == "ok": s["ok"] += 1
        elif st == "no_xlsx": s["no_xlsx"] += 1

        meta = d.get("metadata") or {}
        real_meta = {k: v for k, v in meta.items() if not k.startswith("_") and v}
        if real_meta:
            s["meta"] += 1

        mcs = d.get("measurement_charts") or []
        if mcs:
            s["mc"] += 1
            for mc in mcs:
                poms = mc.get("poms") or []
                s["poms"] += len(poms)

        iso = d.get("construction_iso_map") or []
        if iso:
            s["iso_map"] += len(iso)

print(f"\n=== XLSX 全 brand 收成 ===\n")
print(f"  {'brand':<8} {'total':>6} {'ok':>5} {'no_xlsx':>8} {'meta':>5} {'mc':>5} {'POMs':>8} {'iso_map':>8}")
print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*8} {'-'*5} {'-'*5} {'-'*8} {'-'*8}")

sum_all = defaultdict(int)
# 排序: 先看 ok>0 的, 再依 total desc
sorted_brands = sorted(stats.keys(), key=lambda c: (-stats[c]["ok"], -stats[c]["total"]))
for cl in sorted_brands:
    s = stats[cl]
    if s["ok"] == 0 and s["mc"] == 0 and s["meta"] == 0 and s["iso_map"] == 0:
        continue  # skip totally empty
    print(f"  {cl:<8} {s['total']:>6} {s['ok']:>5} {s['no_xlsx']:>8} "
          f"{s['meta']:>5} {s['mc']:>5} {s['poms']:>8} {s['iso_map']:>8}")
    for k in s:
        sum_all[k] += s[k]

print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*8} {'-'*5} {'-'*5} {'-'*8} {'-'*8}")
print(f"  {'TOTAL':<8} {sum_all['total']:>6} {sum_all['ok']:>5} {sum_all['no_xlsx']:>8} "
      f"{sum_all['meta']:>5} {sum_all['mc']:>5} {sum_all['poms']:>8} {sum_all['iso_map']:>8}")

print(f"\n=== 特別關注: ONY / BY / CATO ===")
for cl in ("ONY", "BY", "CATO"):
    if cl in stats:
        s = stats[cl]
        print(f"\n  {cl}:")
        print(f"    XLSX entries: {s['total']} (ok={s['ok']}, no_xlsx={s['no_xlsx']})")
        print(f"    metadata 抽到: {s['meta']}")
        print(f"    measurement_charts: {s['mc']} 件")
        print(f"    總 POM 行數: {s['poms']:,}")
        print(f"    construction_iso_map: {s['iso_map']}")
