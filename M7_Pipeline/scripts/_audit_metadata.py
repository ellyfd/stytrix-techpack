"""Audit pdf_facets.jsonl 內哪些 EIDH 抽到 metadata, 看樣本看 quality."""
import json
from pathlib import Path

PDF_JSONL = Path(r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline\outputs\extract\pdf_facets.jsonl")
OUT = Path(r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline\metadata_audit.txt")

lines = []
def emit(s=""):
    print(s)
    lines.append(s)

emit("=" * 70)
emit("  metadata 抽到的件 — 看樣本品質")
emit("=" * 70)

total = with_meta = with_mcs = with_callout = 0
by_client_with_meta = {}

with open(PDF_JSONL, encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d.get("_status") != "ok": continue
        total += 1
        cl = d.get("client_code", "?")
        if d.get("metadata"):
            with_meta += 1
            by_client_with_meta.setdefault(cl, []).append(d)
        if d.get("mcs"):
            with_mcs += 1
        if d.get("callouts"):
            with_callout += 1

emit(f"\nstatus=ok: {total}")
emit(f"  with metadata: {with_meta} ({with_meta*100/total:.0f}%)")
emit(f"  with mcs:      {with_mcs} ({with_mcs*100/total:.0f}%)")
emit(f"  with callout:  {with_callout} ({with_callout*100/total:.0f}%)")

emit(f"\n=== 抽到 metadata 的 client (各 2 個樣本) ===")
for cl in sorted(by_client_with_meta.keys()):
    samples = by_client_with_meta[cl]
    emit(f"\n[{cl}] {len(samples)} 件有 metadata")
    for d in samples[:2]:
        emit(f"  EIDH={d.get('eidh')}  design={d.get('design_id')}")
        meta = d.get("metadata", {})
        for k in sorted(meta.keys()):
            if k.startswith("_"): continue
            v = str(meta[k])[:80]
            emit(f"    {k}: {v}")

OUT.write_text("\n".join(lines), encoding="utf-8")
emit(f"\n[output] {OUT}")
