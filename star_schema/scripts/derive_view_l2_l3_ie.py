#!/usr/bin/env python3
"""Derive View B (l2_l3_ie/<L1>.json) — Phase 2.3 of PHASE2_DERIVE_VIEWS_SPEC.md.

Reads:
  l2_l3_ie/<L1>.json           — IE-xlsx-derived canonical Bible (Phase 1 list schema)
  data/ingest/m7_pullon/designs.jsonl.gz  — 3,900 PullOn designs with five_level_steps

Writes (default to staging dir; overwrite Bible only with --in-place):
  <out-dir>/<L1>.json          — schema-upgraded Bible with actuals attached

Schema upgrade per L5 step:
  Old (5-elem list):  [name, grade, sec, primary, machine]
  New (dict):
    {
      "l5": "<name>",
      "ie_standard": {"sec": <num>, "grade": "<C/E/...>", "primary": "<主/副>", "machine": "<...>"},
      "actuals": {                    # optional, only when m7_pullon has matching data
        "n_steps": <int>, "n_designs": <int>,
        "sec_median": <num>,
        "sec_p25": <num>, "sec_p75": <num>,    # ← omitted when degenerate (== median)
        "by_brand": {"<code>": {"sec_median": <num>, "n_designs": <int>}, ...},
        "machine_top": "<machine>",            # ← when machine is single-valued
        "machine_distribution": {"<machine>": <pct 0..1>, ...},   # ← when multi-valued
        # size_distribution dropped (option B trim — size is per-design, not per-step)
      }
    }

Filter rules (drop m7 step rows, NOT Bible nodes):
  - L2 starts with "new_part_"
  - L3 starts with "new_shape_design_"
  - L4 starts with "new_method_describe_"
  - L5 starts with "(NEW)"

Bible structure (L1 → fabric → L2 → L3 → L4 → L5) is NEVER mutated by m7 data —
m7 actuals only attach to nodes that already exist in the Bible. m7 step rows
that don't match any Bible path are reported as "unmatched" (observability).

Usage:
  # Dry-run on one L1, write to staging dir
  python3 star_schema/scripts/derive_view_l2_l3_ie.py --l1 WB

  # Run all 38 L1, write to staging dir
  python3 star_schema/scripts/derive_view_l2_l3_ie.py --all

  # Production: overwrite l2_l3_ie/<L1>.json (Phase 2.5 wires this in CI)
  python3 star_schema/scripts/derive_view_l2_l3_ie.py --all --in-place
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLE_DIR = REPO_ROOT / "l2_l3_ie"
M7_DESIGNS = REPO_ROOT / "data" / "ingest" / "m7_pullon" / "designs.jsonl.gz"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "runtime" / ".phase23_dryrun"


def is_placeholder(l2: str, l3: str, l4: str, l5: str) -> bool:
    """Drop m7 step rows whose any level is an SSRS placeholder."""
    return (
        (l2 or "").startswith("new_part_")
        or (l3 or "").startswith("new_shape_design_")
        or (l4 or "").startswith("new_method_describe_")
        or (l5 or "").startswith("(NEW)")
    )


def load_m7_step_aggregations() -> tuple[dict, dict]:
    """Walk designs.jsonl.gz, aggregate (L1,L2,L3,L4,L5) → list of step rows.

    Returns:
      agg: {(l1,l2,l3,l4,l5): [{sec, machine, size, brand, eidh}, ...]}
      stats: {n_designs, n_step_rows, n_dropped_placeholder}
    """
    agg = collections.defaultdict(list)
    stats = {"n_designs": 0, "n_step_rows": 0, "n_dropped_placeholder": 0}
    with gzip.open(M7_DESIGNS, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            stats["n_designs"] += 1
            eidh = d.get("eidh")
            client = (d.get("client") or {}).get("code")
            for s in d.get("five_level_steps", []) or []:
                stats["n_step_rows"] += 1
                l1 = s.get("l1")
                l2 = s.get("l2")
                l3 = s.get("l3")
                l4 = s.get("l4")
                l5 = s.get("l5")
                if not (l1 and l2 and l3 and l4 and l5):
                    continue
                if is_placeholder(l2, l3, l4, l5):
                    stats["n_dropped_placeholder"] += 1
                    continue
                agg[(l1, l2, l3, l4, l5)].append({
                    "sec": s.get("sec"),
                    "machine": s.get("machine"),
                    "size": s.get("size"),
                    "brand": client,
                    "eidh": eidh,
                })
    return dict(agg), stats


def compute_actuals(rows: list[dict]) -> dict | None:
    """Aggregate m7 step rows into the actuals dict per spec.

    Trim rules (option B, 2026-05-08):
      - sec_p25 / sec_p75 dropped when degenerate (both == sec_median)
      - machine_distribution dropped when single key, replaced by machine_top
      - size_distribution dropped entirely (size is per-design, not per-step)
    """
    if not rows:
        return None
    secs = [r["sec"] for r in rows if isinstance(r["sec"], (int, float))]
    designs = {r["eidh"] for r in rows if r["eidh"]}
    actuals = {
        "n_steps": len(rows),
        "n_designs": len(designs),
    }
    if secs:
        med = round(statistics.median(secs), 2)
        actuals["sec_median"] = med
        if len(secs) >= 4:
            qs = statistics.quantiles(secs, n=4)
            p25 = round(qs[0], 2)
            p75 = round(qs[2], 2)
            if not (p25 == med == p75):
                actuals["sec_p25"] = p25
                actuals["sec_p75"] = p75

    by_brand = collections.defaultdict(list)
    by_brand_designs = collections.defaultdict(set)
    for r in rows:
        if r["brand"]:
            if isinstance(r["sec"], (int, float)):
                by_brand[r["brand"]].append(r["sec"])
            if r["eidh"]:
                by_brand_designs[r["brand"]].add(r["eidh"])
    if by_brand:
        actuals["by_brand"] = {
            b: {
                "sec_median": round(statistics.median(by_brand[b]), 2) if by_brand[b] else None,
                "n_designs": len(by_brand_designs[b]),
            }
            for b in sorted(by_brand)
        }

    machines = collections.Counter(r["machine"] for r in rows if r["machine"])
    if len(machines) == 1:
        actuals["machine_top"] = next(iter(machines))
    elif len(machines) > 1:
        total = sum(machines.values())
        actuals["machine_distribution"] = {
            k: round(v / total, 4) for k, v in machines.most_common()
        }

    return actuals


def upgrade_step(step_list: list, actuals: dict | None) -> dict:
    """Convert 5-elem list to new dict schema, attach actuals if present."""
    name = step_list[0] if len(step_list) > 0 else None
    grade = step_list[1] if len(step_list) > 1 else None
    sec = step_list[2] if len(step_list) > 2 else None
    primary = step_list[3] if len(step_list) > 3 else None
    machine = step_list[4] if len(step_list) > 4 else None
    out = {
        "l5": name,
        "ie_standard": {
            "sec": sec,
            "grade": grade,
            "primary": primary,
            "machine": machine,
        },
    }
    if actuals:
        out["actuals"] = actuals
    return out


def derive_one_l1(l1_code: str, agg: dict, out_dir: Path,
                  in_place: bool) -> dict:
    """Read l2_l3_ie/<L1>.json, walk tree, upgrade schema + attach actuals."""
    src = BIBLE_DIR / f"{l1_code}.json"
    if not src.exists():
        return {"l1": l1_code, "error": "source not found"}

    bible = json.loads(src.read_text(encoding="utf-8"))
    bible_l1 = bible.get("code") or l1_code

    n_l5_total = 0
    n_l5_with_actuals = 0

    for fabric in ("knit", "woven"):
        for l2_node in bible.get(fabric, []) or []:
            l2 = l2_node.get("l2")
            for shape in l2_node.get("shapes", []) or []:
                l3 = shape.get("l3")
                for method in shape.get("methods", []) or []:
                    l4 = method.get("l4")
                    new_steps = []
                    for step in method.get("steps", []) or []:
                        # 不論 step 是舊版 list 或已升級 dict,都重算 actuals,
                        # 不然 m7_pullon source 新增 brand 後 Bible 不會跟著刷新
                        # (見 2026-05-11 fix:HLF/WMT 等 11 個新 brand 卡在 dict
                        # pass-through 沒進 by_brand)。
                        if isinstance(step, dict):
                            l5 = step.get("l5")
                            key = (bible_l1, l2, l3, l4, l5)
                            rows = agg.get(key)
                            actuals = compute_actuals(rows) if rows else None
                            if actuals:
                                step["actuals"] = actuals
                            elif "actuals" in step:
                                del step["actuals"]
                            new_steps.append(step)
                            n_l5_total += 1
                            if actuals:
                                n_l5_with_actuals += 1
                            continue
                        l5 = step[0] if len(step) > 0 else None
                        key = (bible_l1, l2, l3, l4, l5)
                        rows = agg.get(key)
                        actuals = compute_actuals(rows) if rows else None
                        new_steps.append(upgrade_step(step, actuals))
                        n_l5_total += 1
                        if actuals:
                            n_l5_with_actuals += 1
                    method["steps"] = new_steps

    bible.setdefault("_metadata", {})
    bible["_metadata"]["schema"] = "phase2"
    bible["_metadata"]["n_l5_steps_total"] = n_l5_total
    bible["_metadata"]["n_l5_steps_with_actuals"] = n_l5_with_actuals
    bible["_metadata"]["actuals_coverage_pct"] = (
        round(100.0 * n_l5_with_actuals / n_l5_total, 1) if n_l5_total else 0.0
    )

    target_dir = BIBLE_DIR if in_place else out_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{l1_code}.json"
    # Compact JSON (no indent) — matches original Bible convention; saves ~67% size.
    out_path.write_text(
        json.dumps(bible, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    return {
        "l1": l1_code,
        "out_path": str(out_path.relative_to(REPO_ROOT)),
        "n_l5_total": n_l5_total,
        "n_l5_with_actuals": n_l5_with_actuals,
        "actuals_coverage_pct": bible["_metadata"]["actuals_coverage_pct"],
    }


def main():
    p = argparse.ArgumentParser(description="Derive View B (Phase 2.3).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--l1", help="Single L1 code, e.g. WB")
    g.add_argument("--all", action="store_true", help="All 38 L1 files")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                   help=f"Staging output dir (default {DEFAULT_OUT_DIR.relative_to(REPO_ROOT)})")
    p.add_argument("--in-place", action="store_true",
                   help="Overwrite l2_l3_ie/<L1>.json (production mode, Phase 2.5)")
    args = p.parse_args()

    out_dir = Path(args.out_dir)

    print(f"[m7_pullon] reading {M7_DESIGNS.relative_to(REPO_ROOT)} ...", file=sys.stderr)
    agg, stats = load_m7_step_aggregations()
    print(f"[m7_pullon] {stats['n_designs']} designs / {stats['n_step_rows']} step rows / "
          f"dropped {stats['n_dropped_placeholder']} new_* placeholders / "
          f"{len(agg)} unique (L1,L2,L3,L4,L5) keys",
          file=sys.stderr)

    if args.all:
        l1_codes = sorted(p.stem for p in BIBLE_DIR.glob("*.json")
                          if p.stem != "_index")
    else:
        l1_codes = [args.l1]

    target_label = "l2_l3_ie/" if args.in_place else f"{out_dir.relative_to(REPO_ROOT)}/"
    print(f"[derive] {len(l1_codes)} L1 files → {target_label}", file=sys.stderr)
    print(f"{'L1':<6} {'n_l5':>6} {'w/actuals':>11} {'cov%':>6}", file=sys.stderr)
    results = []
    for l1 in l1_codes:
        r = derive_one_l1(l1, agg, out_dir, args.in_place)
        if "error" in r:
            print(f"{l1:<6} ERROR: {r['error']}", file=sys.stderr)
            continue
        results.append(r)
        print(f"{l1:<6} {r['n_l5_total']:>6} {r['n_l5_with_actuals']:>11} "
              f"{r['actuals_coverage_pct']:>6}%",
              file=sys.stderr)

    # Refresh _index.json when --in-place + --all (otherwise we'd half-update it).
    if args.in_place and args.all:
        index_path = BIBLE_DIR / "_index.json"
        existing = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        parts = {}
        for r in results:
            l1 = r["l1"]
            f = BIBLE_DIR / f"{l1}.json"
            parts[l1] = {
                "l1": existing.get("parts", {}).get(l1, {}).get("l1", l1),
                "size": f.stat().st_size,
                "n_l5_steps": r["n_l5_total"],
                "actuals_coverage_pct": r["actuals_coverage_pct"],
            }
        new_index = {
            "version": "v3.0-phase2",
            "note": "L1→L2→L3→L4→L5 dict schema; each L5 carries ie_standard + optional actuals from m7_pullon",
            "schema": "phase2",
            "source": existing.get("source", "五階層展開項目_*.xlsx + m7_pullon"),
            "total_size": sum(p["size"] for p in parts.values()),
            "parts": parts,
        }
        index_path.write_text(
            json.dumps(new_index, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"[index] refreshed {index_path.relative_to(REPO_ROOT)} "
              f"({new_index['total_size'] / 1024 / 1024:.1f} MB across {len(parts)} parts)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
