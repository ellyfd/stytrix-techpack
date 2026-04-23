#!/usr/bin/env python3
"""Build data/iso_dictionary.json — ISO code → {zh, en, machine}.

Sources:
  - l1_iso_recommendations_v1.json.iso_reference: 14 ISO codes with zh + en
  - iso_lookup_factory_v4.json.entries[].iso + iso_zh + machine: supplements
    zh + machine for the 7 ISOs that appear there

Output schema:
{
  "generated_at": "...",
  "source_versions": {...},
  "entries": {
    "301": {"zh": "平車", "en": "Lockstitch", "machine": "平車 lockstitch"},
    "406": {"zh": "三本雙針/壓三本", "en": "Coverstitch", "machine": "三本車 Coverstitch"},
    ...
  }
}

The viewer loads this once and reads display metadata by ISO code, so future ISO
updates only require editing this file (or re-running this script) — no changes
needed in v4 entries or index.html.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISO_REC_PATH = ROOT / "l1_iso_recommendations_v1.json"
V4_PATH = ROOT / "General Model_Path2_Construction Suggestion" / "iso_lookup_factory_v4.json"
OUT_PATH = ROOT / "data" / "iso_dictionary.json"


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def iso_is_valid(iso) -> bool:
    if not iso:
        return False
    return bool(re.fullmatch(r"\d+(\+\d+)?", str(iso)))


def main():
    iso_rec = load_json(ISO_REC_PATH)
    v4 = load_json(V4_PATH)

    entries: dict[str, dict] = {}

    # 1. iso_reference from l1_iso_recommendations — authoritative for zh + en
    for iso, info in (iso_rec.get("iso_reference") or {}).items():
        if not iso_is_valid(iso):
            continue
        entries[iso] = {
            "zh": (info or {}).get("zh") or None,
            "en": (info or {}).get("en") or None,
            "machine": None,
        }

    # 2. v4 supplements machine (and fills zh if iso_reference missed it)
    for e in v4.get("entries") or []:
        iso = e.get("iso")
        if not iso_is_valid(iso):
            continue
        slot = entries.setdefault(iso, {"zh": None, "en": None, "machine": None})
        if not slot["zh"] and e.get("iso_zh"):
            slot["zh"] = e["iso_zh"]
        if not slot["machine"] and e.get("machine"):
            slot["machine"] = e["machine"]

    # Sort entries by ISO code for deterministic output
    ordered = {k: entries[k] for k in sorted(entries.keys())}

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_versions": {
            "iso_reference": str(ISO_REC_PATH.relative_to(ROOT)),
            "v4": str(V4_PATH.relative_to(ROOT)),
        },
        "entries": ordered,
    }

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[iso_dictionary] {len(ordered)} ISO codes → {OUT_PATH.name}", file=sys.stderr)
    for iso, info in ordered.items():
        print(f"  {iso}: zh={info['zh']!r}, en={info['en']!r}, machine={info['machine']!r}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
