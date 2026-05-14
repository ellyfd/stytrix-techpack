#!/usr/bin/env python3
"""Validate bucket-set consistency across the repo.

Two independent bucket sets coexist — they serve different pipelines and
have different naming conventions, so they are NOT meant to line up 1:1:

  1. ``data/runtime/bucket_taxonomy.json`` — TWO sections post-v4:
       * ``buckets`` — 28 v4 4-dim entries, UPPERCASE keys
         ``<GENDER>_<DEPT>_<GT>_<IT>`` (e.g. ``WOMEN_ACTIVE_BOTTOM_PANT``),
         scalar values (gender="WOMEN" not ["WOMEN"]).
       * ``legacy_buckets`` — 59 3-dim aliases for facts/consensus rows
         pre-dating v4, UPPERCASE keys ``<GENDER>_<DEPT>_<GT>``
         (e.g. ``BOYS_FLEECE_BOTTOMS``), list values, carries
         ``_legacy_3dim: true`` flag.
     Used by ``build_recipes_master.py --strict`` to gate Pipeline A
     consensus/facts rows. Adding new v4 buckets is MANUAL: pick a new
     <gender>×<dept>×<gt>×<it> combo Stytrix wants in recipes_master.

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
  * ``bucket_taxonomy.json`` keys are UPPERCASE (per v4 schema convention),
    no case collision, and each entry has non-empty required dims.

Drift between taxonomy and consensus/facts rows is handled upstream by
``build_recipes_master.py --strict`` (which is the canonical gate for
Pipeline A); re-running it is the right check for that direction.

Exit codes:
  0 — clean
  1 — drift detected

Usage::

  python3 scripts/core/validate_buckets.py              # report issues
  python3 scripts/core/validate_buckets.py --strict     # exit 1 on warnings too
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
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def _check_section_keys_uppercase(
    section_name: str,
    section: dict,
    errors: list[str],
) -> None:
    """Keys must be UPPERCASE and unique case-insensitively within section."""
    keys = list(section.keys())
    non_upper = [k for k in keys if k != k.upper()]
    if non_upper:
        errors.append(
            f"{section_name} keys are not UPPERCASE: {non_upper[:5]}"
            f"{'...' if len(non_upper) > 5 else ''}"
        )
    seen = {}
    for k in keys:
        uk = k.upper()
        if uk in seen and seen[uk] != k:
            errors.append(
                f"{section_name} has case-collision: {seen[uk]!r} vs {k!r}"
            )
        seen[uk] = k


def check_taxonomy(errors: list[str], warns: list[str]) -> None:
    """Validate v4 + legacy sections of bucket_taxonomy.json.

    v4 ``buckets`` schema (28 entries):
      * key UPPERCASE ``<GENDER>_<DEPT>_<GT>_<IT>``
      * value: scalar gender/dept/gt/it (each non-empty)
      * extras: n_designs, fabric_split, top_clients, use_for

    ``legacy_buckets`` schema (59 entries, optional):
      * key UPPERCASE ``<GENDER>_<DEPT>_<GT>``
      * value: list-shaped gender/dept/gt (each non-empty)
      * carries ``_legacy_3dim: true``
    """
    tax = load_json(TAXONOMY)
    buckets = tax.get("buckets") or {}
    legacy = tax.get("legacy_buckets") or {}

    if not buckets:
        errors.append("bucket_taxonomy: 'buckets' section missing or empty")
        return

    # v4 'buckets': UPPERCASE, scalar, 4-dim
    _check_section_keys_uppercase("buckets", buckets, errors)
    for k, v in buckets.items():
        for field in ("gender", "dept", "gt", "it"):
            val = v.get(field)
            if val is None or val == "" or val == []:
                errors.append(
                    f"buckets[{k!r}] missing or empty field {field!r}"
                )

    # 'legacy_buckets' (optional): UPPERCASE, list-shaped, 3-dim
    if legacy:
        _check_section_keys_uppercase("legacy_buckets", legacy, errors)
        for k, v in legacy.items():
            for field in ("gender", "dept", "gt"):
                val = v.get(field)
                if not val:  # None / "" / []
                    errors.append(
                        f"legacy_buckets[{k!r}] missing or empty field {field!r}"
                    )

    # Cross-section: legacy 3-dim key shouldn't collide with v4 4-dim key prefix.
    # (Not strictly an error — different namespaces — but worth a warning if
    # cascade fan-out could double-resolve.)
    legacy_keys = set(legacy.keys())
    for k4 in buckets.keys():
        # v4 key = G_D_GT_IT — drop last segment to get 3-dim prefix
        prefix = "_".join(k4.split("_")[:-1])
        if prefix in legacy_keys:
            warns.append(
                f"taxonomy: 3-dim legacy_buckets[{prefix!r}] collides with "
                f"v4 buckets[{k4!r}] prefix (cascade may double-resolve)"
            )


def check_pom_rules_index(errors: list[str], warns: list[str]) -> None:
    """Index must list exactly the bucket files present on disk."""
    idx = load_json(POM_INDEX)
    idx_files = {b["file"] for b in idx["buckets"]}
    # Skip non-bucket files: _index.json (manifest itself) + pom_names.json
    # (POM code→中英翻譯字典, lives in pom_rules/ for legacy but not a bucket rule)
    NON_BUCKET_FILES = {"_index.json", "pom_names.json"}
    disk_files = {p.name for p in POM_RULES_DIR.glob("*.json") if p.name not in NON_BUCKET_FILES}
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
    NON_BUCKET_FILES = {"_index.json", "pom_names.json"}
    for p in sorted(POM_RULES_DIR.glob("*.json")):
        if p.name in NON_BUCKET_FILES:
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

    check_taxonomy(errors, warns)
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
