"""Audit pdf_facets.jsonl: rows / status / metadata 件數對齊."""
import json
from pathlib import Path
from collections import Counter

P = Path(r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline\outputs\extract\pdf_facets.jsonl")

n_total = 0
n_ok = 0
n_meta_nonempty = 0
n_eidh_unique = 0
status_count = Counter()
client_meta = Counter()
unique_eidhs = set()
empty_meta_examples = []

with open(P, encoding="utf-8") as f:
    for line in f:
        n_total += 1
        try:
            d = json.loads(line)
        except Exception:
            continue
        status = d.get("_status", "?")
        status_count[status] += 1
        eidh = d.get("eidh")
        if eidh:
            unique_eidhs.add(str(eidh))
        if status == "ok":
            n_ok += 1
            meta = d.get("metadata") or {}
            if meta:
                n_meta_nonempty += 1
                cl = d.get("client_code", "?")
                client_meta[cl] += 1
            elif len(empty_meta_examples) < 3:
                empty_meta_examples.append({
                    "eidh": eidh,
                    "client_code": d.get("client_code"),
                    "source_files": d.get("source_files", [])[:1],
                })

print(f"total rows: {n_total:,}")
print(f"unique EIDHs: {len(unique_eidhs):,}")
print(f"\nstatus:")
for s, n in status_count.most_common():
    print(f"  {s:<15} {n:>6,}")

print(f"\nok rows with non-empty metadata: {n_meta_nonempty:,}")
print(f"ok rows with EMPTY metadata: {n_ok - n_meta_nonempty:,}")

print(f"\nmetadata coverage by client (top 15):")
for cl, n in client_meta.most_common(15):
    print(f"  {cl:<8} {n:>5}")

if empty_meta_examples:
    print(f"\n=== 3 個 empty metadata 樣本 ===")
    for e in empty_meta_examples:
        print(f"  EIDH={e['eidh']} client={e['client_code']} src={e['source_files']}")
