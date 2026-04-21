#!/usr/bin/env python3
"""
build_recipes_master.py — 合併 4 data sources → recipes_master.json + iso_dictionary.json

4 Sources → unified schema with aggregation_level + l1_standard_38 codes.
Duplicate keys within each layer merged by weighted average of iso_distribution.
"""
import json, os, sys
from collections import defaultdict

SRC = "/sessions/upbeat-cool-hawking/mnt/Source-Data/ONY"
RECIPE_DIR = os.path.join(SRC, "construction_recipes")
V43_PATH   = os.path.join(SRC, "General Model_Path2_Construction Suggestion", "iso_lookup_factory_v4.3.json")
V4_PATH    = os.path.join(SRC, "l1_iso_recommendations_v1.json")
BRIDGE_PATH= os.path.join(SRC, "pom_analysis_v5.5.1", "bridge", "construction_bridge_v6.json")
OUT_DIR    = "/sessions/upbeat-cool-hawking/output"
os.makedirs(OUT_DIR, exist_ok=True)

ZONE_ZH_TO_L1 = {
    "口袋":"PK","肩":"SH","腰頭":"WB","袖":"SL","袖口":"SB","領":"NK","帽子":"HD",
    "下襬":"BM","褲口":"BM","側縫":"SR","脇邊":"SR",
    "前片":"FY","後片":"BN","前襠":"RS","後襠":"RS",
    "褲合身":"BP","前襟":"PL","袖孔":"AH","滾邊":"NT",
    "腰線":"WB","剪接線":"ST","繩類":"TH","前拉鍊":"ZP","車縫(通則)":"OT",
}

V4_ZH_TO_L1 = {
    "袖襱":"AH","大身":"BP","褲耳":"LP","滾條":"NT","後褲身":"BN",
    "鈕扣":"HL","袖口":"SB","繩類":"TH","鬆緊帶":"LO","貼邊":"DP",
    "前立":"PL","前褲身":"FY","貼合":"PS","褲底檔":"RS","帽":"HD",
    "下擺":"BM","行縫固定棉":"QT","標":"LB","裡布":"LI","褲口":"BM",
    "領":"NK","褶":"PD","口袋":"PK","門襟":"PL","褲合身":"BP",
    "肩":"SH","袖":"SL","脇縫":"SR","肩帶":"SH","腰頭":"WB",
    "拉鍊":"ZP","過肩":"FY","釦鎖":"HL",
}

GT_NORMALIZE = {"PANT":"PANTS","UNKNOWN":None}

ISO_DICTIONARY = {
    "301":{"zh":"平車（單針平縫）","en":"Lockstitch","machine":"平車 / Single Needle"},
    "304":{"zh":"之字縫","en":"Zigzag Lockstitch","machine":"之字車"},
    "401":{"zh":"鎖鍊縫（雙針）","en":"Chainstitch","machine":"雙針車 / Double Needle Chain"},
    "406":{"zh":"三本雙針（壓三本）","en":"Coverstitch (2-needle)","machine":"三本車 / Coverstitch"},
    "407":{"zh":"三本三針","en":"Coverstitch (3-needle)","machine":"三本三針車"},
    "501":{"zh":"三線拷克","en":"3-thread Overlock","machine":"拷克車 3T"},
    "503":{"zh":"三線拷克（變體）","en":"3-thread Overlock variant","machine":"拷克車"},
    "504":{"zh":"三線拷克（包邊）","en":"3-thread Overlock (edge)","machine":"拷克車"},
    "512":{"zh":"四線拷克（安全縫）","en":"4-thread Mock Safety Stitch","machine":"拷克車"},
    "514":{"zh":"四線拷克","en":"4-thread Overlock","machine":"拷克車 4T / Overlock"},
    "515":{"zh":"四線拷克（變體）","en":"4-thread Overlock variant","machine":"拷克車"},
    "516":{"zh":"五線拷克","en":"5-thread Overlock (safety stitch)","machine":"五線安全車"},
    "602":{"zh":"併縫（二針平縫）","en":"Flatseam (2-needle)","machine":"併縫車 / Flatseam"},
    "605":{"zh":"三針五線（爬網）","en":"Flatseam (3-needle, 5-thread)","machine":"三針五線爬網車"},
    "607":{"zh":"四針六線（併縫）","en":"Flatseam (4-needle, 6-thread)","machine":"四針六線併縫車 / Flatlock"},
}

def normalize_gt(gt):
    return GT_NORMALIZE.get(gt, gt)

def resolve_v4_l1(v4_zh):
    return V4_ZH_TO_L1.get(v4_zh) or ZONE_ZH_TO_L1.get(v4_zh)

def resolve_zone_l1(zone_zh, zh_to_code):
    return zh_to_code.get(zone_zh) or ZONE_ZH_TO_L1.get(zone_zh)


def merge_duplicate_keys(entries):
    """Merge entries with same key: weighted avg of iso_distribution by n_total."""
    merged = {}
    for e in entries:
        k = e["key"]
        if k not in merged:
            merged[k] = dict(e)  # copy
        else:
            ex = merged[k]
            n1, n2 = ex["n_total"] or 0, e["n_total"] or 0
            ns = n1 + n2
            if ns == 0:
                continue
            all_iso = set(ex["iso_distribution"]) | set(e["iso_distribution"])
            ex["iso_distribution"] = {
                iso: round((ex["iso_distribution"].get(iso, 0) * n1 +
                            e["iso_distribution"].get(iso, 0) * n2) / ns, 4)
                for iso in all_iso
            }
            ex["n_total"] = ns
            # Track merged zone names
            if e["l1_zh"] not in ex["l1_zh"]:
                ex["l1_zh"] = f"{ex['l1_zh']}+{e['l1_zh']}"
            # Merge methods if present (bridge)
            if "methods" in ex and "methods" in e:
                for m, c in e["methods"].items():
                    ex["methods"][m] = ex["methods"].get(m, 0) + c
    return list(merged.values())


def load_l1_standard_38(v43):
    raw = v43["l1_standard_38"]
    zh_to_code = {info["zh"]: code for code, info in raw.items()}
    return raw, zh_to_code


def load_recipes(zh_to_code):
    entries = []
    unmapped = set()
    count = 0
    for fname in sorted(os.listdir(RECIPE_DIR)):
        if not fname.startswith("recipe_") or not fname.endswith(".json"):
            continue
        count += 1
        r = json.load(open(os.path.join(RECIPE_DIR, fname)))
        dept = r.get("department", "General")
        gender = r.get("gender", "UNKNOWN")
        gt = r.get("garment_type", "UNKNOWN")
        it = r.get("item_type", "UNKNOWN")
        nd = r.get("n_designs", 0)
        for zone_zh, zd in r.get("zones", {}).items():
            l1 = resolve_zone_l1(zone_zh, zh_to_code)
            if not l1:
                unmapped.add(zone_zh); continue
            iso_dist = zd.get("iso_distribution", {})
            if not iso_dist:
                continue
            entries.append({
                "aggregation_level": "同細類",
                "key": f"{dept}|{gender}|{gt}|{it}|{l1}",
                "department": dept, "gender": gender,
                "garment_type": gt, "item_type": it,
                "l1_code": l1, "l1_zh": zone_zh,
                "iso_distribution": iso_dist,
                "n_total": zd.get("n_observations", 0),
                "n_designs": nd,
                "source": "recipe", "source_file": fname,
            })
    if unmapped:
        print(f"  ⚠️  Recipe unmapped: {unmapped}", file=sys.stderr)
    before = len(entries)
    entries = merge_duplicate_keys(entries)
    merged = before - len(entries)
    print(f"  ✓ Recipes: {count} files → {len(entries)} entries" +
          (f" ({merged} merged)" if merged else ""))
    return entries


def load_v43(v43):
    entries = []
    for e in v43.get("entries", []):
        iso_dist = e.get("iso_distribution", {})
        if not iso_dist:
            continue
        entries.append({
            "aggregation_level": "同大類",
            "key": f"{e['department']}|{e['gender']}|{e['gt']}|{e['l1_code']}",
            "department": e["department"], "gender": e["gender"],
            "garment_type": e["gt"], "item_type": None,
            "l1_code": e["l1_code"], "l1_zh": e.get("l1", ""),
            "iso_distribution": iso_dist,
            "n_total": e.get("n_designs", 0),
            "n_designs": e.get("n_designs", 0),
            "source": "v4.3",
        })
    # v4.3 keys are already unique (dept×gender×gt×l1_code), no merge needed
    print(f"  ✓ v4.3: {len(entries)} entries")
    return entries


def load_v4():
    v4 = json.load(open(V4_PATH))
    entries = []
    unmapped = set()

    for key, entry in v4.get("by_gt_it", {}).items():
        gt = normalize_gt(entry["garment_type"])
        if gt is None:
            continue
        it = entry["item_type"]
        nd = entry.get("total_designs", 0)
        for p in entry.get("parts", []):
            l1 = resolve_v4_l1(p["l1"])
            if not l1:
                unmapped.add(f"{p['l1_code']}={p['l1']}"); continue
            iso_dist = {o["iso"]: round(o["percentage"] / 100, 4)
                        for o in p.get("options", [])}
            if not iso_dist:
                continue
            entries.append({
                "aggregation_level": "通用",
                "key": f"{gt}|{it}|{l1}",
                "department": None, "gender": None,
                "garment_type": gt, "item_type": it,
                "l1_code": l1, "l1_zh": p["l1"],
                "iso_distribution": iso_dist,
                "n_total": p.get("total_mentions", 0),
                "n_designs": nd,
                "source": "v4_by_gt_it",
            })

    for gt_key, entry in v4.get("by_gt", {}).items():
        gt = normalize_gt(entry["garment_type"])
        if gt is None:
            continue
        nd = entry.get("total_designs", 0)
        for p in entry.get("parts", []):
            l1 = resolve_v4_l1(p["l1"])
            if not l1:
                unmapped.add(f"{p['l1_code']}={p['l1']}"); continue
            iso_dist = {o["iso"]: round(o["percentage"] / 100, 4)
                        for o in p.get("options", [])}
            if not iso_dist:
                continue
            entries.append({
                "aggregation_level": "通用",
                "key": f"{gt}|*|{l1}",
                "department": None, "gender": None,
                "garment_type": gt, "item_type": None,
                "l1_code": l1, "l1_zh": p["l1"],
                "iso_distribution": iso_dist,
                "n_total": p.get("total_mentions", 0),
                "n_designs": nd,
                "source": "v4_by_gt",
            })

    if unmapped:
        print(f"  ⚠️  v4 unmapped: {unmapped}", file=sys.stderr)
    before = len(entries)
    entries = merge_duplicate_keys(entries)
    merged = before - len(entries)
    print(f"  ✓ v4: {len(entries)} entries" +
          (f" ({merged} merged)" if merged else ""))
    return entries


def load_bridge(zh_to_code):
    bridge = json.load(open(BRIDGE_PATH))
    entries = []
    skip = 0
    unmapped = set()

    for gt_raw, data in bridge.get("bridges", {}).items():
        gt = normalize_gt(gt_raw)
        if gt is None:
            continue
        for zone_zh, zd in data.get("zones", {}).items():
            l1 = resolve_zone_l1(zone_zh, zh_to_code)
            if not l1:
                unmapped.add(zone_zh); continue
            iso_codes = zd.get("iso_codes", {})
            if not iso_codes:
                skip += 1; continue
            total = sum(iso_codes.values())
            iso_dist = {c: round(n / total, 4) for c, n in iso_codes.items()} if total > 0 else {}
            entries.append({
                "aggregation_level": "跨款",
                "key": f"{gt}|{l1}",
                "department": None, "gender": None,
                "garment_type": gt, "item_type": None,
                "l1_code": l1, "l1_zh": zone_zh,
                "iso_distribution": iso_dist,
                "n_total": zd.get("count", 0),
                "n_designs": None,
                "source": "bridge_v6",
                "methods": zd.get("methods", {}),
            })

    if unmapped:
        print(f"  ⚠️  Bridge unmapped: {unmapped}", file=sys.stderr)
    before = len(entries)
    entries = merge_duplicate_keys(entries)
    merged = before - len(entries)
    print(f"  ✓ Bridge v6: {len(entries)} entries (skipped {skip} no ISO)" +
          (f" ({merged} merged)" if merged else ""))
    return entries


def main():
    print("=== build_recipes_master.py ===\n")
    v43 = json.load(open(V43_PATH))
    l1_38, zh_to_code = load_l1_standard_38(v43)
    print(f"L1 Standard 38: {len(l1_38)} codes\n")

    print("Loading:")
    re = load_recipes(zh_to_code)
    v43e = load_v43(v43)
    v4e = load_v4()
    be = load_bridge(zh_to_code)
    all_e = re + v43e + v4e + be

    print(f"\nTotal: {len(all_e)} (同細類={len(re)} 同大類={len(v43e)} 通用={len(v4e)} 跨款={len(be)})")

    # Validate
    bad = {e["l1_code"] for e in all_e if e["l1_code"] not in l1_38}
    if bad:
        print(f"⚠️ Invalid L1: {bad}", file=sys.stderr)
    else:
        print("✓ All L1 codes valid")

    all_iso = set()
    for e in all_e:
        all_iso.update(e["iso_distribution"])
    unknown = all_iso - set(ISO_DICTIONARY)
    if unknown:
        print(f"⚠️ Unknown ISO: {unknown}", file=sys.stderr)
    else:
        print(f"✓ All {len(all_iso)} ISO codes in dictionary")

    # Verify no duplicates per layer
    from collections import Counter
    for level in ["同細類", "同大類", "通用", "跨款"]:
        entries = [e for e in all_e if e["aggregation_level"] == level]
        keys = [e["key"] for e in entries]
        dupes = sum(1 for _, c in Counter(keys).items() if c > 1)
        if dupes:
            print(f"⚠️ {level}: {dupes} duplicate keys!", file=sys.stderr)
        else:
            print(f"✓ {level}: {len(entries)} entries, 0 duplicates")

    # Build index
    index = {"同細類": {}, "同大類": {}, "通用": {}, "跨款": {}}
    for e in all_e:
        index[e["aggregation_level"]][e["key"]] = True

    master = {
        "version": "v1.0",
        "created": "2026-04-21",
        "description": "Unified construction ISO lookup — 4 layers with fallback",
        "l1_standard_38": l1_38,
        "fallback_order": ["同細類", "同大類", "通用", "跨款"],
        "stats": {
            "total": len(all_e),
            "同細類": len(re), "同大類": len(v43e),
            "通用": len(v4e), "跨款": len(be),
        },
        "entries": all_e,
        "index": {lv: list(ks.keys()) for lv, ks in index.items()},
    }

    p1 = os.path.join(OUT_DIR, "recipes_master.json")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {p1} ({os.path.getsize(p1):,} bytes)")

    p2 = os.path.join(OUT_DIR, "iso_dictionary.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump(ISO_DICTIONARY, f, ensure_ascii=False, indent=2)
    print(f"✓ {p2} ({os.path.getsize(p2):,} bytes)")


if __name__ == "__main__":
    main()
