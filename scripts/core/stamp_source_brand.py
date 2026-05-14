"""
Stamp every pipeline-derived bucket / variance / grading file with a machine-
readable `source_brand` so the front-end (and future merges) can tell which
brand's history these numbers came from.

Why this script exists
----------------------
Up to now every output of the POM pipeline was learned from Old Navy ("ONY")
techpack history — `reclassify_and_rebuild.py` filters out ATHLETA explicitly,
and no other brand has been ingested. The data files carry no brand attribute,
so the front-end can't distinguish "this is ONY-derived data being borrowed
for brand X" from "this is brand-X-specific data". This stamp is the first
step before adding a real brand dimension to the pipeline.

What it stamps
--------------
- pom_rules/<bucket>.json — top-level `source_brand: "ONY"` (flat schema)
- pom_rules/_index.json    — `_meta.source_brand: "ONY"`
- data/runtime/bodytype_variance.json
- data/runtime/grading_patterns.json
- pom_rules/_derive/gender_gt_pom_rules.json (2026-05-14 從 data/runtime/ 退役)
   ↑ these three are flat dicts keyed by composite strings; a top-level
     `_meta` sibling doesn't collide with any composite key (none start with
     `_`) and front-end consumers always use direct keyed lookup, never
     `Object.keys` / iteration over all top-level keys.

Idempotent: re-running is a no-op if the stamp already matches.
"""
import json
import sys
from pathlib import Path

# scripts/core/<this>.py → repo root is two parents up.
REPO = Path(__file__).resolve().parents[2]
SOURCE_BRAND = "ONY"


def stamp_bucket_file(path: Path) -> bool:
    data = json.loads(path.read_text())
    if data.get("source_brand") == SOURCE_BRAND:
        return False
    new_data = {"bucket": data.get("bucket"), "source_brand": SOURCE_BRAND}
    for k, v in data.items():
        if k in new_data:
            continue
        new_data[k] = v
    if "bucket" not in data:
        new_data.pop("bucket")
        new_data = {"source_brand": SOURCE_BRAND, **{k: v for k, v in data.items()}}
    path.write_text(json.dumps(new_data, indent=2, ensure_ascii=False) + "\n")
    return True


# Files whose pre-existing on-disk form is indented (humans inspect them).
# Keep that style so the stamp diff stays reviewable.
INDENTED_META_FILES = {"data/runtime/bodytype_variance.json"}


def stamp_meta_file(path: Path, repo_root: Path) -> bool:
    """For files whose top-level is a flat dict of composite-key buckets, add
    or update a `_meta.source_brand` field. Preserves existing `_meta` content
    and the file's original indented/compact formatting."""
    data = json.loads(path.read_text())
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    if meta.get("source_brand") == SOURCE_BRAND:
        return False
    meta["source_brand"] = SOURCE_BRAND
    new_data = {"_meta": meta}
    for k, v in data.items():
        if k == "_meta":
            continue
        new_data[k] = v
    rel = str(path.relative_to(repo_root))
    indent = 2 if rel in INDENTED_META_FILES else None
    path.write_text(json.dumps(new_data, ensure_ascii=False, indent=indent) + "\n")
    return True


def stamp_index_file(path: Path) -> bool:
    data = json.loads(path.read_text())
    meta = data.setdefault("_meta", {})
    if meta.get("source_brand") == SOURCE_BRAND:
        return False
    meta["source_brand"] = SOURCE_BRAND
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


def main() -> int:
    changed = 0
    pom_rules_dir = REPO / "pom_rules"
    for bucket_file in sorted(pom_rules_dir.glob("*.json")):
        if bucket_file.name == "_index.json":
            continue
        if stamp_bucket_file(bucket_file):
            changed += 1
            print(f"  stamped {bucket_file.relative_to(REPO)}")

    if (pom_rules_dir / "_index.json").exists():
        if stamp_index_file(pom_rules_dir / "_index.json"):
            changed += 1
            print("  stamped pom_rules/_index.json")

    # Per the data/ restructure (PR #275) bodytype_variance + grading_patterns
    # live under data/runtime/.  gender_gt_pom_rules moved to pom_rules/_derive/
    # 2026-05-14 (Pipeline B 內部產物,前端 / API 不消費,從 runtime/ 退役).
    for rel in ("data/runtime/bodytype_variance.json",
                "data/runtime/grading_patterns.json",
                "pom_rules/_derive/gender_gt_pom_rules.json"):
        path = REPO / rel
        if not path.exists():
            print(f"  skip (missing): {rel}", file=sys.stderr)
            continue
        if stamp_meta_file(path, REPO):
            changed += 1
            print(f"  stamped {rel}")

    print(f"\nDone. {changed} file(s) updated. source_brand = {SOURCE_BRAND!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
