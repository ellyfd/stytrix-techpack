"""Audit ONY 6 件 為什麼 metadata + mcs 都 0."""
import json
from pathlib import Path

PDF_JSONL = Path(r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline\outputs\extract\pdf_facets.jsonl")
OUT = Path(r"C:\Users\ellycheng.DOMAIN\Desktop\StyTrix TechPack\Construction\Source-Data\M7_Pipeline\ony_audit.txt")

lines = []
def emit(s=""):
    print(s)
    lines.append(s)

emit("=" * 70)
emit("  ONY 件 audit (為什麼 metadata + mcs 都 0)")
emit("=" * 70)

with open(PDF_JSONL, encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d.get("client_code") != "ONY":
            continue
        emit(f"\nEIDH={d.get('eidh')}  design={d.get('design_id')}")
        emit(f"  source_files: {d.get('source_files')}")
        emit(f"  metadata: {d.get('metadata') or '(empty)'}")
        emit(f"  callouts: {len(d.get('callouts', []))} pages")
        for c in d.get("callouts", [])[:3]:
            emit(f"    page={c.get('page')} score={c.get('score')} png={c.get('png','none')[-40:] if c.get('png') else 'none'}")
        emit(f"  mcs: {len(d.get('mcs', []))} entries")
        for mc in d.get("mcs", [])[:2]:
            keys = list(mc.keys())
            emit(f"    {keys}")

OUT.write_text("\n".join(lines), encoding="utf-8")
emit(f"\n[output] {OUT}")
