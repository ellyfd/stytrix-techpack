#!/usr/bin/env python3
"""Build data/recipes_master.json + data/l1_standard_38.json.

Merges four construction handbooks into a single unified master file that the
index.html universal-mode viewer can query with a single fallback cascade.

Sources (all inputs kept read-only):
  - General Model_Path2_Construction Suggestion/iso_lookup_factory_v4.3.json
    (230 entries; Department × Gender × GT × L1 with iso_distribution + n_designs)
  - General Model_Path2_Construction Suggestion/iso_lookup_factory_v4.json
    (282 entries; Fabric × Department × GT × L1_code with iso_zh / machine)
  - data/construction_bridge_v6.json
    (bridges[GT][zones][zh_zone] with methods + iso_codes)
  - recipes/*.json (71 files; same-sub-category stats)

Output schema (data/recipes_master.json):
{
  "generated_at": "...",
  "source_versions": {...},
  "stats": {...},
  "entries": [
    {
      "key": {"gender": "...", "dept": "...", "gt": "...", "it": "...", "l1": "..."},
      "aggregation_level": "same_sub|same_gt|general|cross_design",
      "source": "recipe|v4.3|v4|bridge",
      "n_total": N,
      "iso_distribution": [{"iso": "406", "n": 9, "pct": 69.2}, ...],
      "methods": [{"name": "BINDING", "n": 5, "pct": 50.0}, ...]  # may be []
    },
    ...
  ]
}

Key fields are normalized to UPPERCASE with non-alphanumerics → underscore
so the viewer can query by a single canonical key regardless of source casing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V43_PATH = ROOT / "General Model_Path2_Construction Suggestion" / "iso_lookup_factory_v4.3.json"
V4_PATH = ROOT / "General Model_Path2_Construction Suggestion" / "iso_lookup_factory_v4.json"
BRIDGE_PATH = ROOT / "data" / "construction_bridge_v6.json"
RECIPES_DIR = ROOT / "recipes"
INGEST_DIR = ROOT / "data" / "ingest"
BUCKET_TAXONOMY_PATH = ROOT / "data" / "bucket_taxonomy.json"

OUT_MASTER = ROOT / "data" / "recipes_master.json"
OUT_L1_STD = ROOT / "data" / "l1_standard_38.json"

# --- taxonomy normalization maps (applied when building bucket lookups) ---
# BOYS/GIRLS/BABY_TODDLER bucket entries also match UI's KIDS gender.
GENDER_UI_EXPAND = {
    "BOYS": ["KIDS"],
    "GIRLS": ["KIDS"],
    "BABY_TODDLER": ["KIDS"],
    "MATERNITY": ["WOMENS"],
}
# "BOTTOM" is an extraction shorthand covering all lower-body GTs.
GT_EXPAND = {
    "BOTTOM": ["PANTS", "LEGGINGS", "SHORTS", "SKIRT"],
}


def norm(s):
    """Uppercase + collapse non-alphanumerics into underscores."""
    if s is None:
        return None
    up = re.sub(r"[^A-Z0-9]+", "_", str(s).upper()).strip("_")
    return up or None


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def build_l1_standard_38(v43) -> dict:
    """Extract the 38-code L1 standard from v4.3's l1_standard_38 field."""
    std = v43.get("l1_standard_38") or {}
    return {
        "version": v43.get("version", "v4.3"),
        "source": "iso_lookup_factory_v4.3.json",
        "codes": std,
    }


def build_zh_to_l1(l1_std: dict) -> dict:
    """zh part name → l1 code. Used to reverse-lookup bridge / recipe zones."""
    out = {}
    for code, info in (l1_std.get("codes") or {}).items():
        zh = (info or {}).get("zh")
        if zh:
            out[zh] = code
    return out


def iso_is_valid(iso) -> bool:
    """ISO codes are numeric (e.g. '301', '406', '514+605'). Reject typos like 'ISO301'."""
    if not iso:
        return False
    return bool(re.fullmatch(r"\d+(\+\d+)?", str(iso)))


def recipe_key_from_filename(fname: str):
    """recipe_WOMENS_SWIMWEAR_TOP_SWIM.json → (WOMENS, SWIMWEAR, TOP, SWIM).
    Filename format: recipe_<GENDER>_<DEPT>_<GT>_<IT*>.json (IT may contain underscores).
    We prefer to read the in-file fields (gender/department/garment_type/item_type).
    This function is only used as a fallback.
    """
    stem = fname.removesuffix(".json").removeprefix("recipe_")
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    gender, dept, gt = parts[0], parts[1], parts[2]
    it = "_".join(parts[3:])
    return gender, dept, gt, it


def dist_dict_to_list(dist: dict, n_total: int):
    """Convert a pct-dict ({iso: 0.69}) or a count-dict ({iso: 12}) to the
    master schema [{iso, n, pct}]. Auto-detects which: if sum > 1.5, treat as counts.
    """
    if not dist:
        return []
    total = sum(dist.values())
    as_counts = total > 1.5 or all(isinstance(v, int) for v in dist.values())
    items = []
    for iso, v in dist.items():
        if not iso_is_valid(iso):
            continue
        if as_counts:
            n = int(v)
            pct = (v / total * 100.0) if total > 0 else 0.0
        else:
            pct = v * 100.0
            n = int(round(v * n_total)) if n_total else 0
        items.append({"iso": iso, "n": n, "pct": round(pct, 1)})
    items.sort(key=lambda x: -x["pct"])
    return items


def methods_dict_to_list(methods: dict):
    if not methods:
        return []
    total = sum(methods.values()) or 1
    out = [{"name": name, "n": int(n), "pct": round(n / total * 100.0, 1)}
           for name, n in methods.items()]
    out.sort(key=lambda x: -x["pct"])
    return out


def build_from_recipes(recipes_dir: Path, zh_to_l1: dict, warns: list):
    """Produce same_sub entries from the 71 recipe files."""
    entries = []
    processed = 0
    skipped_zones = 0
    for f in sorted(recipes_dir.glob("recipe_*.json")):
        try:
            r = load_json(f)
        except Exception as e:
            warns.append(f"recipe {f.name}: failed to parse ({e})")
            continue
        processed += 1
        gender = norm(r.get("gender"))
        dept = norm(r.get("department"))
        gt = norm(r.get("garment_type") or r.get("gt"))
        it = norm(r.get("item_type") or r.get("it"))
        if not (gender and dept and gt and it):
            warns.append(f"recipe {f.name}: missing key fields")
            continue
        for zh_zone, zd in (r.get("zones") or {}).items():
            l1 = zh_to_l1.get(zh_zone)
            if not l1:
                warns.append(f"recipe {f.name}: unknown zone zh {zh_zone!r}")
                skipped_zones += 1
                continue
            dist = zd.get("iso_distribution") or {}
            n_obs = zd.get("n_observations") or 0
            iso_list = dist_dict_to_list(dist, n_obs)
            if not iso_list:
                # zone has no ISO — skip (methods-only zones aren't part of recipes data)
                continue
            entries.append({
                "key": {"gender": gender, "dept": dept, "gt": gt, "it": it, "l1": l1},
                "aggregation_level": "same_sub",
                "source": "recipe",
                "n_total": int(n_obs),
                "iso_distribution": iso_list,
                "methods": [],
            })
    return entries, {"files_processed": processed, "skipped_zones": skipped_zones}


def build_from_v43(v43):
    entries = []
    for e in v43.get("entries") or []:
        l1 = e.get("l1_code")
        if not l1:
            continue
        n_total = int(e.get("n_designs") or 0)
        iso_list = dist_dict_to_list(e.get("iso_distribution") or {}, n_total)
        if not iso_list:
            # fallback: use primary iso with pct from iso_pct
            iso = e.get("iso")
            if iso_is_valid(iso):
                pct_val = float(e.get("iso_pct") or 1.0)
                iso_list = [{"iso": iso, "n": n_total, "pct": round(pct_val * 100.0, 1)}]
        if not iso_list:
            continue
        entries.append({
            "key": {
                "gender": norm(e.get("gender")),
                "dept": norm(e.get("department")),
                "gt": norm(e.get("gt")),
                "it": None,
                "l1": l1,
            },
            "aggregation_level": "same_gt",
            "source": "v4.3",
            "n_total": n_total,
            "iso_distribution": iso_list,
            "methods": [],
        })
    return entries


def build_from_v4(v4):
    entries = []
    for e in v4.get("entries") or []:
        l1 = e.get("l1_code")
        if not l1:
            continue
        iso = e.get("iso")
        if not iso_is_valid(iso):
            continue
        votes = e.get("pptx_2025_votes") or {}
        n_votes_total = sum(votes.values())
        # Ensure primary iso is in the distribution even if no votes
        if votes:
            dist = dict(votes)
            dist.setdefault(iso, 0)  # primary may be 0 votes but still recommended
            iso_list = dist_dict_to_list(dist, n_votes_total)
            # promote primary to top regardless of vote rank (it's the curated pick)
            primary_idx = next((i for i, x in enumerate(iso_list) if x["iso"] == iso), -1)
            if primary_idx > 0:
                iso_list.insert(0, iso_list.pop(primary_idx))
            n_total = int(e.get("pptx_2025_designs") or n_votes_total or 1)
        else:
            iso_list = [{"iso": iso, "n": 1, "pct": 100.0}]
            n_total = 1
        entries.append({
            "key": {
                "gender": None,
                "dept": norm(e.get("department")),
                "gt": norm(e.get("gt")),
                "it": None,
                "l1": l1,
                "fabric": norm(e.get("fabric")),
            },
            "aggregation_level": "general",
            "source": "v4",
            "n_total": n_total,
            "iso_distribution": iso_list,
            "methods": [],
        })
    return entries


def build_from_bridge(bridge, zh_to_l1, warns):
    """Produce cross_design entries from bridge v6.

    Bridge has no l1_code in zones (only Chinese zone names), so we reverse-lookup
    via l1_standard_38.zh. If a zone has no iso_codes (PPTX-only methods), we still
    emit an entry with iso_distribution=[] so the viewer can pull methods from it,
    but the viewer will skip it as an ISO source.
    """
    entries = []
    zone_count = 0
    no_iso_count = 0
    skipped_zones = 0
    for gt_raw, gtd in (bridge.get("bridges") or {}).items():
        gt = norm(gt_raw)
        if not gt or gt == "UNKNOWN":
            continue
        for zh_zone, zd in (gtd.get("zones") or {}).items():
            l1 = zh_to_l1.get(zh_zone)
            if not l1:
                warns.append(f"bridge {gt_raw}: unknown zone zh {zh_zone!r}")
                skipped_zones += 1
                continue
            zone_count += 1
            iso_codes = zd.get("iso_codes") or {}
            methods = zd.get("methods") or {}
            n_total = int(zd.get("count") or 0)
            iso_list = dist_dict_to_list(iso_codes, n_total)
            methods_list = methods_dict_to_list(methods)
            if not iso_list:
                no_iso_count += 1
            entries.append({
                "key": {
                    "gender": None,
                    "dept": None,
                    "gt": gt,
                    "it": None,
                    "l1": l1,
                },
                "aggregation_level": "cross_design",
                "source": "bridge",
                "n_total": n_total,
                "iso_distribution": iso_list,
                "methods": methods_list,
            })
    return entries, {"zone_count": zone_count, "no_iso_count": no_iso_count, "skipped_zones": skipped_zones}


def load_ingest_entries(ingest_dir: Path, l1_std: dict, warns: list, raw_tax: dict | None = None):
    """Scan data/ingest/<source>/entries.jsonl for pre-built master entries.

    Each line must already conform to the master entry schema (aggregation_level,
    source, key, n_total, iso_distribution, methods, design_ids). We validate and
    pass through unchanged — the source pipeline is responsible for schema + normKey.

    If raw_tax is passed, additionally check each entry's bucket/fingerprint is
    defined in the taxonomy. Unknown bucket/fp names are passed through (they'll
    simply never match a UI query), but recorded as warns so --strict mode can fail.

    Returns (entries, per_source_stats).
    """
    # Pre-compute canonical bucket/fp name sets from taxonomy (if given) so the
    # per-entry check is O(1).
    tax_buckets = set()
    tax_fps = set()
    if raw_tax:
        tax_buckets = {norm(k) for k in (raw_tax.get("buckets") or {}) if norm(k)}
        tax_fps = {norm(k) for k in (raw_tax.get("fingerprints") or {}) if norm(k)}
    if not ingest_dir.exists():
        return [], {}
    all_entries = []
    per_source = {}
    l1_std_codes = set((l1_std.get("codes") or {}).keys())
    for src_dir in sorted(ingest_dir.iterdir()):
        if not src_dir.is_dir():
            continue
        jsonl = src_dir / "entries.jsonl"
        if not jsonl.exists():
            continue
        src_name = src_dir.name
        count = 0
        bad_l1 = 0
        with jsonl.open(encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError as ex:
                    warns.append(f"ingest {src_name}:{lineno}: bad JSON ({ex})")
                    continue
                # schema checks (soft: warn + skip bad entries, don't fail the build)
                missing = [k for k in ("aggregation_level","source","key","n_total","iso_distribution","methods") if k not in e]
                if missing:
                    warns.append(f"ingest {src_name}:{lineno}: missing fields {missing}")
                    continue
                if not isinstance(e["iso_distribution"], list) or not isinstance(e["methods"], list):
                    warns.append(f"ingest {src_name}:{lineno}: iso_distribution/methods must be array")
                    continue
                # tolerate l1 == "_DEFAULT" (bucket-level wildcard, UI skips it)
                l1 = (e.get("key") or {}).get("l1")
                if l1 and l1 != "_DEFAULT" and l1 not in l1_std_codes:
                    bad_l1 += 1
                    warns.append(f"ingest {src_name}:{lineno}: l1 {l1!r} not in l1_standard_38")
                    continue
                # Normalize bucket + fingerprint in the key so queries match
                # regardless of input casing (entries.jsonl and bucket_taxonomy.json
                # may come from different pipelines with different conventions).
                k = e["key"]
                if "bucket" in k and k["bucket"]:
                    k["bucket"] = norm(k["bucket"])
                if "fingerprint" in k and k["fingerprint"]:
                    k["fingerprint"] = norm(k["fingerprint"])
                # Taxonomy coverage check (non-fatal, flagged for --strict).
                # An entry with a bucket not in taxonomy passes through but will
                # never match a UI query via buckets_resolved.
                if tax_buckets and k.get("bucket") and k["bucket"] not in tax_buckets:
                    warns.append(f"ingest {src_name}:{lineno}: bucket {k['bucket']!r} not in bucket_taxonomy.json")
                if tax_fps and k.get("fingerprint") and k["fingerprint"] not in tax_fps:
                    warns.append(f"ingest {src_name}:{lineno}: fingerprint {k['fingerprint']!r} not in bucket_taxonomy.json")
                all_entries.append(e)
                count += 1
        per_source[src_name] = {"entries": count, "bad_l1": bad_l1}
    return all_entries, per_source


def expand_bucket_taxonomy(raw_tax: dict):
    """Apply GENDER_UI_EXPAND + GT_EXPAND so UI queries using its own enum (KIDS /
    PANTS etc.) can match buckets stored under extraction-native values (BOYS /
    BOTTOM etc.). Also normalize bucket + fingerprint NAMES with normKey so
    mixed casing across taxonomy / entries drops (e.g. `boys_knit_tops` vs
    `BOYS_KNIT_TOPS`) doesn't break the cascade.

    Input: raw taxonomy from data/bucket_taxonomy.json (user-supplied).
    Output: same shape + parallel `buckets_resolved` / `fingerprints_resolved`
    blocks keyed by normKey'd names; verbatim `buckets` / `fingerprints` are
    kept for provenance.
    """
    if not raw_tax:
        return raw_tax
    resolved = {}
    for name, info in (raw_tax.get("buckets") or {}).items():
        norm_name = norm(name)
        if not norm_name:
            continue
        gender_in = [norm(g) for g in (info.get("gender") or []) if g]
        dept_in = [norm(d) for d in (info.get("dept") or []) if d]
        gt_in = [norm(g) for g in (info.get("gt") or []) if g]
        gender_out = set(gender_in)
        for g in gender_in:
            gender_out.update(GENDER_UI_EXPAND.get(g, []))
        gt_out = set(gt_in)
        for g in gt_in:
            gt_out.update(GT_EXPAND.get(g, []))
            if g not in GT_EXPAND:
                gt_out.add(g)
        resolved[norm_name] = {
            "gender": sorted(gender_out),
            "dept": sorted(set(dept_in)),
            "gt": sorted(gt_out),
        }
    fp_resolved = {}
    for name, info in (raw_tax.get("fingerprints") or {}).items():
        norm_name = norm(name)
        if not norm_name:
            continue
        it_out = [norm(i) for i in (info.get("it") or []) if i]
        fp_resolved[norm_name] = {"it": sorted(set(it_out))}
    out = dict(raw_tax)
    out["buckets_resolved"] = resolved
    out["fingerprints_resolved"] = fp_resolved
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true",
                    help=("Exit 1 if any ingest-layer or taxonomy-coverage issue "
                          "was raised (missing schema fields, bad JSON, l1 not in "
                          "l1_standard_38, bucket/fingerprint not in taxonomy). "
                          "Legacy recipe/bridge zone warnings are always soft."))
    args = ap.parse_args()

    v43 = load_json(V43_PATH)
    v4 = load_json(V4_PATH)
    bridge = load_json(BRIDGE_PATH)

    # 1. l1_standard_38 → also write as standalone file for the viewer
    l1_std = build_l1_standard_38(v43)
    OUT_L1_STD.write_text(json.dumps(l1_std, ensure_ascii=False, indent=2), encoding="utf-8")
    zh_to_l1 = build_zh_to_l1(l1_std)
    print(f"[l1_standard_38] {len(l1_std['codes'])} codes → {OUT_L1_STD.name}", file=sys.stderr)

    warns = []

    recipe_entries, recipe_stats = build_from_recipes(RECIPES_DIR, zh_to_l1, warns)
    v43_entries = build_from_v43(v43)
    v4_entries = build_from_v4(v4)
    bridge_entries, bridge_stats = build_from_bridge(bridge, zh_to_l1, warns)

    # 3. Bucket taxonomy (data/bucket_taxonomy.json) — embedded in master output
    #    so the viewer gets everything via one fetch. We expand BOYS/GIRLS→KIDS
    #    and BOTTOM→[PANTS,LEGGINGS,SHORTS,SKIRT] into `buckets_resolved` for queries.
    raw_tax = load_json(BUCKET_TAXONOMY_PATH) if BUCKET_TAXONOMY_PATH.exists() else None
    bucket_tax = expand_bucket_taxonomy(raw_tax) if raw_tax else None

    # 2. External ingest sources (data/ingest/<source>/entries.jsonl) come in
    #    already shaped as master entries — the source pipeline owns normalization.
    #    raw_tax is passed in so unknown bucket/fp names are flagged (for --strict).
    ingest_entries, ingest_per_source = load_ingest_entries(INGEST_DIR, l1_std, warns, raw_tax)

    all_entries = recipe_entries + v43_entries + v4_entries + bridge_entries + ingest_entries

    recipe_files = sorted(f.name for f in RECIPES_DIR.glob("recipe_*.json"))
    ingest_manifest = {
        src: {
            "entries_file": f"data/ingest/{src}/entries.jsonl",
            **stats,
        }
        for src, stats in ingest_per_source.items()
    }

    # stats by aggregation_level (all sources combined)
    level_counts = {}
    for e in all_entries:
        level_counts[e["aggregation_level"]] = level_counts.get(e["aggregation_level"], 0) + 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_versions": {
            "v4.3": str(V43_PATH.relative_to(ROOT)),
            "v4": str(V4_PATH.relative_to(ROOT)),
            "bridge": str(BRIDGE_PATH.relative_to(ROOT)),
            "recipes": recipe_files,
            "ingest": ingest_manifest,
            "bucket_taxonomy": str(BUCKET_TAXONOMY_PATH.relative_to(ROOT)) if bucket_tax else None,
        },
        "stats": {
            **{lvl: level_counts.get(lvl, 0) for lvl in ("same_sub","same_bucket","same_gt","general","cross_design")},
            "total": len(all_entries),
            "recipe_files_processed": recipe_stats["files_processed"],
            "bridge_zones": bridge_stats["zone_count"],
            "bridge_zones_no_iso": bridge_stats["no_iso_count"],
            "unknown_zone_warnings": len([w for w in warns if "unknown zone" in w]),
            "ingest_warnings": len([w for w in warns if w.startswith("ingest ")]),
        },
        "bucket_taxonomy": bucket_tax,
        "entries": all_entries,
    }

    OUT_MASTER.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("--- stats ---", file=sys.stderr)
    for k, v in out["stats"].items():
        print(f"  {k}: {v}", file=sys.stderr)
    if ingest_per_source:
        print("--- ingest sources ---", file=sys.stderr)
        for src, stats in ingest_per_source.items():
            print(f"  {src}: {stats}", file=sys.stderr)
    if warns:
        print("--- warnings ---", file=sys.stderr)
        for w in warns[:50]:
            print(f"  {w}", file=sys.stderr)
        if len(warns) > 50:
            print(f"  ... and {len(warns) - 50} more", file=sys.stderr)
    print(f"[recipes_master] {len(all_entries)} entries → {OUT_MASTER.name}", file=sys.stderr)

    # --strict: fail the build if any ingest-layer or taxonomy-coverage warn was
    # raised. Legacy recipe/bridge unknown-zone warnings predate the ingest
    # pipeline and stay soft — that's an old-data-cleanup job, not a CI gate.
    if args.strict:
        blocking = [w for w in warns if w.startswith("ingest ")]
        if blocking:
            print(f"\n[STRICT] {len(blocking)} ingest/taxonomy violations — failing build.",
                  file=sys.stderr)
            print("         (remove --strict or fix the source data to unblock)",
                  file=sys.stderr)
            sys.exit(1)
        print("[STRICT] OK — no ingest/taxonomy violations.", file=sys.stderr)


if __name__ == "__main__":
    main()
