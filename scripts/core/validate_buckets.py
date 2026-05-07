#!/usr/bin/env python3
"""Validate bucket-set consistency across the repo.

Two independent bucket sets coexist — they serve different pipelines and
have different naming conventions, so they are NOT meant to line up 1:1:

  1. ``data/runtime/bucket_taxonomy.json`` — 59 buckets, keyed lowercase as
     ``<gender>_<dept>_<gt>`` (e.g. ``boys_fleece_bottoms``). Used by
     ``build_recipes_master.py --strict`` to gate Pipeline A consensus/facts
     rows. Adding a new bucket here is MANUAL: new gender × dept × gt combos
     that Stytrix chooses to recognise in recipes_master.

  2. ``pom_rules/_index.json`` — 81 buckets, keyed ``<DEPT>_<GT>|<GENDER>``
     (e.g. ``RTW_TOP|WOMENS``). DERIVED by ``reclassify_and_rebuild.py``
     from techpack data; auto-grows when new combos appear in the PDFs.

Recipes (``recipes/recipe_<GENDER>_<DEPT>_<GT>_<IT>.json``) live on a
different axis (they include item_type), so they have no direct 1:1
mapping with either bucket set.

This validator checks the things that SHOULD line up:

  * ``pom_rules/_index.json`` entries match the actual JSON files present.
  * Each pom_rules bucket file's ``bucket`` string is consistent with its
    ``gender``/``department``/``garment_type`` fields.
  * ``data/runtime/bucket_taxonomy.json`` keys are normalised (lowercase, no dupes
    when uppercased).

Drift between taxonomy and consensus/facts rows is handled upstream by
``build_recipes_master.py --strict`` (which is the canonical gate for
Pipeline A); re-running it is the right check for that direction.

Exit codes:
  0 — clean
  1 — drift detected

Usage::

  python3 scripts/validate_buckets.py              # report issues
  python3 scripts/validate_buckets.py --strict     # same, but exit 1 on warnings too
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TAXONOMY = REPO_ROOT / "data" / "runtime" / "bucket_taxonomy.json"
POM_RULES_DIR = REPO_ROOT / "pom_rules"
POM_INDEX = POM_RULES_DIR / "_index.json"


def load_json(path: Path):
    with path.open() as f:
        return json.load(f)


def check_taxonomy_keys(errors: list[str], warns: list[str]) -> None:
    """Taxonomy keys should be lowercase and unique (case-insensitively)."""
    tax = load_json(TAXONOMY)
    keys = list(tax["buckets"].keys())
    non_lower = [k for k in keys if k != k.lower()]
    if non_lower:
        errors.append(
            f"bucket_taxonomy keys are not lowercase: {non_lower[:5]}"
            f"{'...' if len(non_lower) > 5 else ''}"
        )
    seen = {}
    for k in keys:
        lk = k.lower()
        if lk in seen and seen[lk] != k:
            errors.append(
                f"bucket_taxonomy has case-collision: {seen[lk]!r} vs {k!r}"
            )
        seen[lk] = k
    # Each taxonomy entry must have non-empty gender / dept / gt lists.
    for k, v in tax["buckets"].items():
        for field in ("gender", "dept", "gt"):
            if not v.get(field):
                errors.append(
                    f"bucket_taxonomy[{k!r}] missing or empty field {field!r}"
                )


def check_pom_rules_index(errors: list[str], warns: list[str]) -> None:
    """Index must list exactly the bucket files present on disk."""
    idx = load_json(POM_INDEX)
    idx_files = {b["file"] for b in idx["buckets"]}
    disk_files = {p.name for p in POM_RULES_DIR.glob("*.json") if p.name != "_index.json"}
    missing = idx_files - disk_files
    orphan = disk_files - idx_files
    if missing:
        errors.append(
            f"pom_rules/_index.json references missing files: {sorted(missing)}"
        )
    if orphan:
        errors.append(
            f"pom_rules/ has files not in _index.json: {sorted(orphan)}"
        )


def check_pom_rules_self_consistency(errors: list[str], warns: list[str]) -> None:
    """Each bucket file's bucket string should match its gender/dept/gt fields."""
    for p in sorted(POM_RULES_DIR.glob("*.json")):
        if p.name == "_index.json":
            continue
        d = load_json(p)
        bucket = d.get("bucket", "")
        gender = d.get("gender", "")
        dept = d.get("department", "")
        gt = d.get("garment_type", "")
        expected = f"{dept}_{gt}|{gender}"
        if bucket != expected:
            errors.append(
                f"{p.name}: bucket={bucket!r} but fields suggest {expected!r}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings too (default: only on errors).",
    )
    args = ap.parse_args()

    errors: list[str] = []
    warns: list[str] = []

    check_taxonomy_keys(errors, warns)
    check_pom_rules_index(errors, warns)
    check_pom_rules_self_consistency(errors, warns)

    if errors:
        print("❌ ERRORS:")
        for e in errors:
            print(f"  - {e}")
    if warns:
        print("⚠ WARNINGS:")
        for w in warns:
            print(f"  - {w}")

    if not errors and not warns:
        print("✓ All bucket sets consistent.")

    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
