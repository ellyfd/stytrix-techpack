#!/usr/bin/env python3
"""patch_recipe_zones.py
修正 71 份 recipe 原始檔的 zone 中文名 → l1_standard_38 正規名。

規則：
  袖     → 袖口 (SL)          所有 GT
  側縫   → 脅邊 (SS) if TOP   / 褲合身 (PS) if BOTTOM
  前片   → 脅邊 (SS) if TOP   / 褲合身 (PS) if BOTTOM
  後片   → 脅邊 (SS) if TOP   / 褲合身 (PS) if BOTTOM
  前襠   → 褲襠 (RS)          所有 GT
  後襠   → 褲襠 (RS)          所有 GT

如果 rename 後跟既有 zone 撞名 → merge（加權平均 iso_distribution）。
"""
import json, glob, sys
from pathlib import Path

TOP_GTS = {"TOP", "DRESS", "OUTERWEAR", "ROMPER_JUMPSUIT", "SET"}
BOTTOM_GTS = {"PANTS", "LEGGINGS", "SHORTS", "SKIRT"}

def get_target(zone_zh: str, gt: str) -> str | None:
    """Return target zone name in l1_standard_38, or None if no rename needed."""
    if zone_zh == "袖":
        return "袖口"
    if zone_zh in ("前襠", "後襠"):
        return "褲襠"
    if zone_zh in ("側縫", "前片", "後片"):
        gt_up = gt.upper()
        if gt_up in TOP_GTS:
            return "脅邊"
        elif gt_up in BOTTOM_GTS:
            return "褲合身"
        else:
            return None  # unknown GT, skip
    return None  # not one of the 6 problem zones


def merge_iso_dist(a: dict, b: dict, n_a: int, n_b: int) -> tuple[dict, int]:
    """Merge two iso_distribution dicts (iso→pct 0-1) weighted by n_observations.
    Returns (merged_dist, merged_n).
    """
    n_total = n_a + n_b
    if n_total == 0:
        # just union
        merged = {}
        all_isos = set(a.keys()) | set(b.keys())
        for iso in all_isos:
            merged[iso] = (a.get(iso, 0) + b.get(iso, 0)) / 2
        return merged, 0

    merged = {}
    all_isos = set(a.keys()) | set(b.keys())
    for iso in all_isos:
        w_a = a.get(iso, 0.0) * n_a
        w_b = b.get(iso, 0.0) * n_b
        merged[iso] = (w_a + w_b) / n_total
    return merged, n_total


def patch_file(filepath: str, dry_run=False) -> dict:
    with open(filepath) as f:
        data = json.load(f)

    gt = (data.get("garment_type") or data.get("gt") or "").upper()
    zones = data.get("zones", {})
    fname = Path(filepath).name
    
    actions = []
    zones_to_delete = []
    zones_to_add = {}

    for zone_zh in list(zones.keys()):
        target = get_target(zone_zh, gt)
        if target is None:
            continue
        if target == zone_zh:
            continue  # already correct name

        src_data = zones[zone_zh]
        zones_to_delete.append(zone_zh)

        if target in zones and target not in zones_to_add:
            # Target already exists → merge
            existing = zones[target]
            merged_dist, merged_n = merge_iso_dist(
                src_data.get("iso_distribution", {}),
                existing.get("iso_distribution", {}),
                src_data.get("n_observations", 0),
                existing.get("n_observations", 0)
            )
            # Recompute top_iso
            top_iso = max(merged_dist, key=merged_dist.get) if merged_dist else existing.get("top_iso")
            top_pct = merged_dist.get(top_iso, 0) if top_iso else 0

            zones_to_add[target] = {
                "iso_distribution": merged_dist,
                "top_iso": top_iso,
                "top_pct": round(top_pct, 3),
                "confidence": existing.get("confidence", src_data.get("confidence")),
                "n_observations": merged_n,
            }
            actions.append(f"MERGE {zone_zh}(n={src_data.get('n_observations',0)}) + {target}(n={existing.get('n_observations',0)}) → {target}(n={merged_n})")
        elif target in zones_to_add:
            # Already staged a merge to this target → merge again
            existing = zones_to_add[target]
            merged_dist, merged_n = merge_iso_dist(
                src_data.get("iso_distribution", {}),
                existing.get("iso_distribution", {}),
                src_data.get("n_observations", 0),
                existing.get("n_observations", 0)
            )
            top_iso = max(merged_dist, key=merged_dist.get) if merged_dist else None
            top_pct = merged_dist.get(top_iso, 0) if top_iso else 0
            zones_to_add[target] = {
                "iso_distribution": merged_dist,
                "top_iso": top_iso,
                "top_pct": round(top_pct, 3),
                "confidence": existing.get("confidence"),
                "n_observations": merged_n,
            }
            actions.append(f"MERGE {zone_zh}(n={src_data.get('n_observations',0)}) into staged {target}(n={merged_n})")
        else:
            # Simple rename
            zones_to_add[target] = src_data
            actions.append(f"RENAME {zone_zh} → {target}")

    if not actions:
        return {"file": fname, "actions": [], "changed": False}

    if not dry_run:
        for z in zones_to_delete:
            del zones[z]
        for z, d in zones_to_add.items():
            zones[z] = d
        data["zones"] = zones
        with open(filepath, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"file": fname, "gt": gt, "actions": actions, "changed": True}


def main():
    dry_run = "--dry-run" in sys.argv
    recipes_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "recipes"
    
    files = sorted(glob.glob(f"{recipes_dir}/recipe_*.json"))
    print(f"{'[DRY RUN] ' if dry_run else ''}Processing {len(files)} recipe files in {recipes_dir}\n")

    total_changed = 0
    total_actions = 0
    for fp in files:
        result = patch_file(fp, dry_run=dry_run)
        if result["changed"]:
            total_changed += 1
            total_actions += len(result["actions"])
            print(f"  {result['file']} (GT={result.get('gt','?')})")
            for a in result["actions"]:
                print(f"    → {a}")

    print(f"\n{'='*50}")
    print(f"Files changed: {total_changed}/{len(files)}")
    print(f"Total actions: {total_actions}")
    if dry_run:
        print("⚠️  DRY RUN — no files modified")
    else:
        print("✅ All files updated")


if __name__ == "__main__":
    main()
