#!/usr/bin/env python3
"""Enforce foundational_measurements.tier1_poms ⊂ measurement_rules.must.

For every bucket JSON in pom_rules/ where foundational_measurements.enforced
is true, make sure every tier1_pom appears in measurement_rules.must:
  - already in must        → mark tier1_enforced: true
  - in recommend / optional → move to must, mark tier1_enforced: true
  - completely absent       → insert placeholder {rate: 0, count: 0,
                              tier1_enforced: true, tier1_absent: true}

Also makes sure tier1 POMs are present in pom_sort_order (preserves existing
order; appends missing ones at the end).

Usage (from repo root):
    python3 scripts/enforce_tier1.py             # fix everything in pom_rules/
    python3 scripts/enforce_tier1.py --dry-run   # report what would change
"""
import argparse, json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RULES_DIR = REPO_ROOT / "pom_rules"

TIERS = ("must", "recommend", "optional")

# Default tier1 POM lists by body region. Used only when a bucket is missing
# its own foundational_measurements. Pipelines that already set
# foundational_measurements on each bucket override this.
UPPER_TIER1 = ["F10", "C1", "J9", "J10", "E1", "I5"]
LOWER_TIER1 = ["H1", "L2", "L8", "K1", "K2", "O4", "N9"]


def default_tier1_for_region(region):
    """region: 'upper'/'lower'/'combined' — bucket 的 body_region 欄.

    2026-05-14: pom_rules garment_type 改用 M7 manifest Item 原值 (不再是
    TOP/PANTS 9 桶), 所以 tier1 預設改吃 reclassify 寫進 bucket 的 body_region.
    """
    if region == "upper":
        return UPPER_TIER1[:]
    if region == "lower":
        return LOWER_TIER1[:]
    if region == "combined":
        return UPPER_TIER1 + LOWER_TIER1
    return []


def enforce_bucket(data):
    """Mutate one bucket dict in-place. Return (changed, stats_delta)."""
    fm = data.get("foundational_measurements")
    if fm is None:
        tier1 = default_tier1_for_region(data.get("body_region"))
        if not tier1:
            return False, {}
        data["foundational_measurements"] = {"tier1_poms": tier1, "enforced": True}
        fm = data["foundational_measurements"]
    if not fm.get("enforced"):
        return False, {}
    tier1 = list(fm.get("tier1_poms") or [])
    if not tier1:
        return False, {}

    rules = data.setdefault("measurement_rules", {})
    must = rules.setdefault("must", {})
    recommend = rules.setdefault("recommend", {})
    optional = rules.setdefault("optional", {})

    delta = {"marked": 0, "from_recommend": 0, "from_optional": 0, "added_absent": 0}
    changed = False

    for pom in tier1:
        if pom in must:
            if must[pom].get("tier1_enforced") is not True:
                must[pom]["tier1_enforced"] = True
                delta["marked"] += 1
                changed = True
        elif pom in recommend:
            entry = recommend.pop(pom)
            entry["tier1_enforced"] = True
            must[pom] = entry
            delta["from_recommend"] += 1
            changed = True
        elif pom in optional:
            entry = optional.pop(pom)
            entry["tier1_enforced"] = True
            must[pom] = entry
            delta["from_optional"] += 1
            changed = True
        else:
            must[pom] = {
                "rate": 0,
                "count": 0,
                "tier1_enforced": True,
                "tier1_absent": True,
            }
            delta["added_absent"] += 1
            changed = True

    # Keep pom_sort_order in sync: append tier1 POMs that aren't already ordered.
    sort_order = data.get("pom_sort_order")
    if isinstance(sort_order, list):
        seen = set(sort_order)
        appended = [pom for pom in tier1 if pom not in seen]
        if appended:
            data["pom_sort_order"] = sort_order + appended
            delta["sort_order_appended"] = len(appended)
            changed = True

    return changed, delta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-dir", type=Path, default=DEFAULT_RULES_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rules_dir = args.rules_dir
    if not rules_dir.is_dir():
        print(f"ERROR: not a directory: {rules_dir}", file=sys.stderr)
        return 2

    totals = {"files_scanned": 0, "files_changed": 0, "marked": 0,
              "from_recommend": 0, "from_optional": 0, "added_absent": 0,
              "sort_order_appended": 0}
    changed_files = []

    for fpath in sorted(rules_dir.glob("*.json")):
        if fpath.name.startswith("_") or fpath.name == "pom_names.json":
            continue
        totals["files_scanned"] += 1
        data = json.loads(fpath.read_text())
        changed, delta = enforce_bucket(data)
        if not changed:
            continue
        totals["files_changed"] += 1
        for k, v in delta.items():
            totals[k] = totals.get(k, 0) + v
        changed_files.append((fpath.name, delta))
        if not args.dry_run:
            fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    print("=== Tier 1 Enforcement ({}) ===".format("DRY-RUN" if args.dry_run else "APPLIED"))
    print(f"scanned  : {totals['files_scanned']}")
    print(f"changed  : {totals['files_changed']}")
    print(f"  already in must, newly marked      : {totals['marked']}")
    print(f"  moved from recommend -> must       : {totals['from_recommend']}")
    print(f"  moved from optional  -> must       : {totals['from_optional']}")
    print(f"  added absent placeholder           : {totals['added_absent']}")
    print(f"  pom_sort_order entries appended    : {totals['sort_order_appended']}")
    if totals["files_changed"]:
        print("\n--- changed files ---")
        for name, delta in changed_files:
            parts = [f"{k}={v}" for k, v in delta.items() if v]
            print(f"  {name}: {', '.join(parts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
