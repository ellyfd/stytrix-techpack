#!/usr/bin/env python3
"""Update 71 recipe files: rename non-standard zone names to l1_standard_38 zh.

Uses the AUTHORITATIVE build_run v4.3 l1_standard_38 zh names:
  SL=袖口, AH=袖圍, AE=袖孔, SS=脅邊, SA=剪接線_上身類, SB=剪接線_下身類,
  RS=褲襠, PS=褲合身, LO=褲口, BM=下襬

Mapping:
  袖(19 SL)  → 袖口(SL)        sleeve cuff/hem
  袖(5 AH)   → 袖圍(AH)        armhole (ROMPER_JUMPSUIT, KIDS_SWIM_TOPS, OUTERWEAR, JACKET, WOMENS_RJ)
  袖(1 AE)   → 袖孔(AE)        armhole edge (KIDS_SWIMWEAR_TOP_TOP, sleeveless binding)
  袖(1 DEL)  → DELETE           WOMENS_GENERAL_PANTS_PANT (extraction error)
  側縫(21)   → 脅邊(SS)         side seam, all garment types
  前片(tops)  → 剪接線_上身類(SA)  upper body seam line
  前片(bots)  → 剪接線_下身類(SB)  lower body seam line
  後片(tops)  → 剪接線_上身類(SA)  merge with 前片 if both exist
  後片(bots)  → 剪接線_下身類(SB)  merge with 前片 if both exist
  前襠+後襠   → 褲襠(RS)         crotch, combine
  褲口        → 褲口(LO)         already correct, no change
  褲合身      → 褲合身(PS)        already correct, no change

GT routing for 前片/後片:
  TOP_GTS = {TOP, DRESS, OUTERWEAR, ROMPER_JUMPSUIT, SET}  → SA
  BOTTOM_GTS = {PANTS, LEGGINGS, SHORTS, SKIRT}            → SB
"""
import json
import os
import sys
from collections import defaultdict

RECIPE_DIR = sys.argv[1] if len(sys.argv) > 1 else "recipes"

TOP_GTS = {"TOP", "DRESS", "OUTERWEAR", "ROMPER_JUMPSUIT", "SET"}
BOTTOM_GTS = {"PANTS", "LEGGINGS", "SHORTS", "SKIRT"}

# ─── 袖 classification by recipe filename ───
SLEEVE_AH = {
    "recipe_KIDS_GENERAL_ROMPER_JUMPSUIT_DRESS.json",
    "recipe_KIDS_SWIMWEAR_TOP_TOPS.json",
    "recipe_WOMENS_GENERAL_OUTERWEAR_OUTERWEAR.json",
    "recipe_WOMENS_GENERAL_TOP_JACKET.json",
    "recipe_WOMENS_GENERAL_ROMPER_JUMPSUIT_DRESS.json",
}
SLEEVE_AE = {
    "recipe_KIDS_SWIMWEAR_TOP_TOP.json",
}
SLEEVE_DELETE = {
    "recipe_WOMENS_GENERAL_PANTS_PANT.json",
}


def merge_iso_distributions(zones_data: list) -> dict:
    """Weighted merge of multiple zone data dicts into one."""
    total_n = sum(zd.get("n_observations", 0) for zd in zones_data)
    if total_n == 0:
        return {"n_observations": 0, "iso_distribution": {}}
    
    iso_counts = defaultdict(float)
    for zd in zones_data:
        n = zd.get("n_observations", 0)
        for iso, pct in (zd.get("iso_distribution") or {}).items():
            iso_counts[iso] += pct * n
    
    iso_dist = {}
    for iso, count in sorted(iso_counts.items(), key=lambda x: -x[1]):
        iso_dist[iso] = round(count / total_n, 3)
    
    merged_methods = {}
    for zd in zones_data:
        for m, v in (zd.get("methods") or {}).items():
            merged_methods[m] = merged_methods.get(m, 0) + v
    
    result = {"n_observations": total_n, "iso_distribution": iso_dist}
    if merged_methods:
        result["methods"] = merged_methods
    return result


def add_to_zone(new_zones: dict, target_zh: str, zone_data: dict):
    """Add zone data to new_zones, merging if target already exists."""
    if target_zh in new_zones:
        merged = merge_iso_distributions([new_zones[target_zh], zone_data])
        new_zones[target_zh] = merged
        return True  # was merged
    else:
        new_zones[target_zh] = zone_data
        return False


def get_gt(recipe: dict) -> str:
    """Extract normalized garment type."""
    gt = recipe.get("garment_type") or recipe.get("gt") or ""
    return gt.upper().replace(" ", "_")


def process_recipe(filepath: str) -> dict:
    fname = os.path.basename(filepath)
    with open(filepath, encoding="utf-8") as f:
        recipe = json.load(f)
    
    zones = recipe.get("zones")
    if not zones:
        return {"changes": [], "warnings": []}
    
    gt = get_gt(recipe)
    is_top = gt in TOP_GTS
    is_bottom = gt in BOTTOM_GTS
    
    changes = []
    warnings = []
    new_zones = {}
    consumed = set()
    
    # 1. Handle 袖 → 袖口(SL) / 袖圍(AH) / 袖孔(AE) / DELETE
    if "袖" in zones:
        if fname in SLEEVE_DELETE:
            changes.append("DELETE 袖 (extraction error in pants)")
            consumed.add("袖")
        elif fname in SLEEVE_AH:
            new_zones["袖圍"] = zones["袖"]
            changes.append("袖 → 袖圍 (AH)")
            consumed.add("袖")
        elif fname in SLEEVE_AE:
            new_zones["袖孔"] = zones["袖"]
            changes.append("袖 → 袖孔 (AE)")
            consumed.add("袖")
        else:
            # SL: rename 袖 → 袖口
            new_zones["袖口"] = zones["袖"]
            changes.append("袖 → 袖口 (SL)")
            consumed.add("袖")
    
    # 2. Handle 前襠+後襠 → 褲襠 (RS)
    crotch_sources = [s for s in ["前襠", "後襠"] if s in zones]
    if crotch_sources:
        zones_to_merge = [zones[s] for s in crotch_sources]
        add_to_zone(new_zones, "褲襠", merge_iso_distributions(zones_to_merge))
        for s in crotch_sources:
            consumed.add(s)
        changes.append(f"{'+'.join(crotch_sources)} → 褲襠 (RS)")
    
    # 3. Handle 側縫 → 脅邊 (SS)
    if "側縫" in zones:
        merged = add_to_zone(new_zones, "脅邊", zones["側縫"])
        changes.append(f"側縫 → 脅邊 (SS)" + (" [merged]" if merged else ""))
        consumed.add("側縫")
    
    # 4. Handle 前片/後片 → SA or SB based on GT
    panel_target = None
    if is_top:
        panel_target = "剪接線_上身類"  # SA
        code_label = "SA"
    elif is_bottom:
        panel_target = "剪接線_下身類"  # SB
        code_label = "SB"
    else:
        if "前片" in zones or "後片" in zones:
            warnings.append(f"GT={gt} not in TOP/BOTTOM sets, cannot route 前片/後片")
    
    if panel_target:
        for panel_zh in ["前片", "後片"]:
            if panel_zh in zones:
                merged = add_to_zone(new_zones, panel_target, zones[panel_zh])
                changes.append(f"{panel_zh} → {panel_target} ({code_label})" + (" [merged]" if merged else ""))
                consumed.add(panel_zh)
    
    # 5. Pass through all other zones (including 褲口→LO, 褲合身→PS which already match)
    for zh, zd in zones.items():
        if zh not in consumed:
            new_zones[zh] = zd
    
    recipe["zones"] = new_zones
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    
    return {"changes": changes, "warnings": warnings}


def main():
    recipe_dir = RECIPE_DIR
    files = sorted(f for f in os.listdir(recipe_dir)
                   if f.startswith("recipe_") and f.endswith(".json"))
    
    total_changes = 0
    total_warnings = 0
    
    for fname in files:
        fpath = os.path.join(recipe_dir, fname)
        result = process_recipe(fpath)
        if result["changes"] or result["warnings"]:
            print(f"\n{fname}:")
            for c in result["changes"]:
                print(f"  ✓ {c}")
                total_changes += 1
            for w in result["warnings"]:
                print(f"  ⚠ {w}")
                total_warnings += 1
    
    print(f"\n--- Summary ---")
    print(f"Files processed: {len(files)}")
    print(f"Zone changes: {total_changes}")
    print(f"Warnings: {total_warnings}")


if __name__ == "__main__":
    main()
