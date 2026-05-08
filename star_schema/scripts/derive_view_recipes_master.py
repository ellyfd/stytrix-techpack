#!/usr/bin/env python3
"""Derive View A (data/runtime/recipes_master.json) from data/master.jsonl.

Phase 2.2 of PHASE2_DERIVE_VIEWS_SPEC.md.

Reads:
  data/master.jsonl       — one entry per line (incl. `_m7_*` internal fields)
  data/master.meta.json   — envelope (generated_at, source_versions, stats)

Writes:
  data/runtime/recipes_master.json — View A: stripped (no `_m7_*`),
                                      same envelope schema as before.

Stripping rules:
  - Drop any key starting with `_m7_` from each entry.
  - Everything else passes through unchanged.

Defensive: build_recipes_master.py post-2026-05-08 no longer writes any `_m7_*`
fields, so this strip is currently a no-op. Kept for safety in case future m7
pipeline updates re-introduce internal fields that should not leak into View A.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IN_JSONL = REPO_ROOT / "data" / "master.jsonl"
IN_META = REPO_ROOT / "data" / "master.meta.json"
OUT_VIEW_A = REPO_ROOT / "data" / "runtime" / "recipes_master.json"


def strip_internal(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if not k.startswith("_m7_")}


def main():
    if not IN_JSONL.exists():
        print(f"ERROR: {IN_JSONL} not found. Run build_recipes_master.py first.",
              file=sys.stderr)
        sys.exit(1)
    if not IN_META.exists():
        print(f"ERROR: {IN_META} not found. Run build_recipes_master.py first.",
              file=sys.stderr)
        sys.exit(1)

    meta = json.loads(IN_META.read_text(encoding="utf-8"))
    meta.pop("n_entries", None)

    entries = []
    n_stripped = 0
    with open(IN_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            stripped = strip_internal(e)
            if len(stripped) != len(e):
                n_stripped += 1
            entries.append(stripped)

    out = {
        **meta,
        "derived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "derived_from": str(IN_JSONL.relative_to(REPO_ROOT)),
        "entries": entries,
    }

    OUT_VIEW_A.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[view_a] {len(entries)} entries ({n_stripped} had _m7_* stripped) "
          f"→ {OUT_VIEW_A.relative_to(REPO_ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
