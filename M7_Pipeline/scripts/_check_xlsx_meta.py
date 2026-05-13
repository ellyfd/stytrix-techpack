"""快速看 XLSX metadata + MC POM 抽取狀況 (擴充版)"""
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs" / "extract" / "xlsx_facets.jsonl"

counts = {}
samples = {}
field_freq = {}

with open(OUT, encoding="utf-8") as f:
    for line in f:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        cl = d.get("client_code", "")
        if cl not in ("WMT", "SAN", "QCE", "NET"):
            continue
        counts.setdefault(cl, {"total": 0, "meta": 0, "fields_total": Counter()})
        counts[cl]["total"] += 1
        meta = d.get("metadata") or {}
        # exclude _source_xlsx / _source_sheet from "real" metadata
        real_meta = {k: v for k, v in meta.items() if not k.startswith("_") and v}
        if real_meta:
            counts[cl]["meta"] += 1
            for k in real_meta:
                counts[cl]["fields_total"][k] += 1
            # First sample
            if cl not in samples:
                samples[cl] = {"eidh": d.get("eidh"), "meta": real_meta}

print("\n=== XLSX metadata coverage (WMT/SAN/QCE/NET) ===\n")
print(f"  {'brand':<6} {'total':>6} {'meta':>6} {'meta%':>7}")
print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*7}")
for cl in ("WMT", "SAN", "QCE", "NET"):
    if cl in counts:
        c = counts[cl]
        pct = c["meta"] / max(c["total"], 1) * 100
        print(f"  {cl:<6} {c['total']:>6} {c['meta']:>6} {pct:>6.0f}%")
    else:
        print(f"  {cl:<6} (no data)")

print(f"\n=== 各 brand metadata 欄位命中率 ===")
for cl in ("WMT", "SAN", "QCE", "NET"):
    if cl not in counts or counts[cl]["meta"] == 0:
        continue
    print(f"\n  {cl} (基數 {counts[cl]['meta']}):")
    for field, n in counts[cl]["fields_total"].most_common():
        pct = n / counts[cl]["meta"] * 100
        bar = "█" * int(pct / 10)
        print(f"    {field:<20} {n:>5} ({pct:>3.0f}%) {bar}")

print(f"\n=== 樣本 (per brand, 第 1 件有 metadata 的 EIDH) ===")
for cl, s in samples.items():
    print(f"\n  {cl} EIDH {s['eidh']}:")
    for k, v in s["meta"].items():
        print(f"    {k}: {repr(v)[:80]}")
