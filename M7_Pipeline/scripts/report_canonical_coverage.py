"""report_canonical_coverage.py — 讀 pdf_metadata.jsonl 統計 11 客戶 × 8 canonical 覆蓋率

8 canonical: 客戶 / 報價款號 / Program / Subgroup / W/K / Item / Season / PRODUCT_CATEGORY

Output:
  console table — per-客戶 each canonical coverage %
  per-client sample — 每客戶取 2 列 raw + canonical 給人工檢查
  outputs/platform/canonical_coverage.txt — 同 console 但存檔
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
JSONL = ROOT / "outputs" / "platform" / "pdf_metadata.jsonl"
OUT = ROOT / "outputs" / "platform" / "canonical_coverage.txt"

CANONICAL = ["客戶", "報價款號", "Program", "Subgroup", "W/K", "Item", "Season", "PRODUCT_CATEGORY"]

# 客戶顯示順序(按 by-client n_pdfs desc)
CLIENT_ORDER = ["ONY", "DICKS", "KOHLS", "GU", "TARGET", "GAP", "A_&_F",
                "GAP_OUTLET", "ATHLETA", "BR", "CATO"]


def main():
    by_client = defaultdict(list)
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            by_client[row.get("client", "")].append(row)

    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 110)
    emit(f"Canonical Coverage Report (source: {JSONL.relative_to(ROOT)})")
    emit("=" * 110)

    # === Coverage table ===
    header = f"{'client':12} {'n':>5}  " + "  ".join(f"{c:>16}" for c in CANONICAL)
    emit(header)
    emit("-" * len(header))

    grand_total = 0
    grand_hit = Counter()

    for client in CLIENT_ORDER:
        rows = by_client.get(client, [])
        if not rows:
            continue
        n = len(rows)
        grand_total += n
        cells = []
        for c in CANONICAL:
            hit = sum(1 for r in rows if r.get(c))
            grand_hit[c] += hit
            pct = 100 * hit / n
            cells.append(f"{pct:>5.0f}% ({hit:>4}/{n:<4})")
        emit(f"{client:12} {n:>5}  " + "  ".join(f"{c:>16}" for c in cells))

    # Grand total
    emit("-" * len(header))
    cells = []
    for c in CANONICAL:
        pct = 100 * grand_hit[c] / grand_total if grand_total else 0
        cells.append(f"{pct:>5.0f}% ({grand_hit[c]:>4}/{grand_total:<4})")
    emit(f"{'TOTAL':12} {grand_total:>5}  " + "  ".join(f"{c:>16}" for c in cells))

    emit("")
    emit("=" * 110)
    emit("Per-client samples (2 rows each, canonical fields only)")
    emit("=" * 110)

    for client in CLIENT_ORDER:
        rows = by_client.get(client, [])
        if not rows:
            continue
        emit(f"\n--- {client} (n={len(rows)}) ---")
        for r in rows[:2]:
            emit(f"  eidh={r.get('eidh')}  design_id={r.get('design_id')}  pdf={r.get('source_pdf', '')[:60]}")
            for c in CANONICAL:
                v = r.get(c)
                if v:
                    emit(f"    {c:<22} = {v}")
            # also show raw extracted fields for cross-check
            raw_keys = [k for k in r if k not in (set(CANONICAL) | {"client", "design_id", "eidh", "source_pdf"})]
            if raw_keys:
                emit(f"    [raw] {', '.join(f'{k}={str(r[k])[:40]!r}' for k in raw_keys[:6])}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[output] {OUT}")


if __name__ == "__main__":
    main()
