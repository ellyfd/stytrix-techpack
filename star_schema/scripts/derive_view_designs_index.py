#!/usr/bin/env python3
"""Derive View C — data/runtime/designs_index/<EIDH>.json (Phase 2.4).

Splits data/ingest/m7_pullon/designs.jsonl.gz (3,900 PullOn designs) into
per-EIDH static JSON files for frontend lazy-fetch when displaying single-design
detail pages.

Reads:
  data/ingest/m7_pullon/designs.jsonl.gz

Writes:
  data/runtime/designs_index/<EIDH>.json  — one per design, compact JSON
  data/runtime/designs_index/_index.json  — EIDH list + sizes + summary

Cleanup: also removes any <EIDH>.json file in the output dir whose EIDH no
longer appears in designs.jsonl.gz (so the directory tracks the source).

See PHASE2_DERIVE_VIEWS_SPEC.md View C.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IN_PATH = REPO_ROOT / "data" / "ingest" / "m7_pullon" / "designs.jsonl.gz"
OUT_DIR = REPO_ROOT / "data" / "runtime" / "designs_index"


def main():
    if not IN_PATH.exists():
        print(f"ERROR: {IN_PATH.relative_to(REPO_ROOT)} not found.", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    eidh_to_size: dict[str, int] = {}
    n_written = 0
    n_skipped_no_eidh = 0

    with gzip.open(IN_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            eidh = d.get("eidh")
            if not eidh:
                n_skipped_no_eidh += 1
                continue
            eidh = str(eidh)
            if eidh in eidh_to_size:
                # Duplicate EIDH in source — second occurrence wins (later overrides).
                pass
            payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
            (OUT_DIR / f"{eidh}.json").write_text(payload, encoding="utf-8")
            eidh_to_size[eidh] = len(payload)
            n_written += 1

    # Cleanup: remove stale <EIDH>.json files no longer in source.
    n_removed = 0
    keep = set(eidh_to_size)
    for p in OUT_DIR.glob("*.json"):
        if p.stem == "_index":
            continue
        if p.stem not in keep:
            p.unlink()
            n_removed += 1

    # Write _index.json (compact, per existing l2_l3_ie/_index.json pattern).
    index = {
        "version": "v1.0",
        "note": "Per-EIDH details for frontend lazy-fetch (Phase 2.4 View C).",
        "source": str(IN_PATH.relative_to(REPO_ROOT)),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_designs": len(eidh_to_size),
        "total_size": sum(eidh_to_size.values()),
        "designs": {
            eidh: {"size": size}
            for eidh, size in sorted(eidh_to_size.items())
        },
    }
    (OUT_DIR / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"[designs_index] {n_written} EIDH → {OUT_DIR.relative_to(REPO_ROOT)}/ "
          f"({sum(eidh_to_size.values()) / 1024 / 1024:.1f} MB total, "
          f"{n_removed} stale removed, {n_skipped_no_eidh} skipped no eidh)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
