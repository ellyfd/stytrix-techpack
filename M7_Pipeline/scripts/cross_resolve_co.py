"""cross_resolve_co.py — ONY Carry Over POM 反查 (v2, sandbox-sync workaround).

Scans pptx_text/*.txt for 「尺寸表參考」 + D-code, joins to existing PDF POM data
by D-code, produces a patch jsonl that copies measurement_charts from the
referenced source design into the carry-over design's entry.

Usage:
  python3 scripts/cross_resolve_co.py [--dry-run] [--brand ONY GAP]
"""
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
PPTX_FACETS = EXTRACT_DIR / "pptx_facets.jsonl"

# Two-step CO marker detection:
#   1. anchor: "尺寸表參考" / "參考前季" / "參考大貨"
#   2. within next 80 chars (cut at paragraph break), grab first D-code
# Strong CO anchors — explicit sizing context:
#   "尺寸表參考"               (explicit size table reference)
#   "參考前季"                 (explicit previous season reference)
#   "參考大貨"                 (production sample reference)
#   "Missy跳檔 / Plus跳檔 / Petite跳檔 / 跳檔 + 參考"  (grading reference)
#   "跳檔參考"                 (concise grading reference)
CO_STRONG_ANCHOR_RE = re.compile(
    r"(?:"
    r"尺寸表\s*參考"
    r"|參考\s*前季"
    r"|參考\s*大貨"
    r"|(?:Missy|Plus|Petite|Tall|Maternity|Kids|Baby|Toddler|Youth|Mens?|Womens?)?\s*跳檔[^\n]{0,12}?參考"
    r"|跳檔[^\n]{0,12}?參考"
    r")", re.IGNORECASE)
# Weak CO signal — D-code with _BOM suffix following 參考 (full BOM ID = sizing-grade reference)
# e.g. "參考D4794_BOM679874" — referencing a SPECIFIC PRODUCTION RUN, not just a design family
CO_BOM_REF_RE = re.compile(r"參考[^\n]{0,10}?(D\d{2,5}_BOM\d{4,8})", re.IGNORECASE)

CO_DCODE_RE = re.compile(r"(D\d{2,5})\b", re.IGNORECASE)
CO_SEASON_RE = re.compile(r"((?:FA|SP|HO|WI|SS|HW)\d{2})", re.IGNORECASE)


def extract_co_ref(txt):
    """Strong-then-weak CO ref detection. Returns (ref_season, ref_d) or (None, None)."""
    # 1. Strong anchor first (sizing context)
    m = CO_STRONG_ANCHOR_RE.search(txt)
    if m:
        end = min(len(txt), m.end() + 80)
        window = txt[m.start():end]
        nl = window.find("\n\n")
        if nl > 0:
            window = window[:nl]
        d = CO_DCODE_RE.search(window)
        if d:
            s = CO_SEASON_RE.search(window)
            return (s.group(1).upper() if s else ""), d.group(1).upper()
    # 2. Weak signal: 參考 + D-code_BOM\d+ (specific production run reference)
    m = CO_BOM_REF_RE.search(txt)
    if m:
        full = m.group(1)
        d_only = re.match(r"(D\d{2,5})", full, re.IGNORECASE)
        if d_only:
            # search for season near match
            s = CO_SEASON_RE.search(txt[max(0,m.start()-30):m.end()+30])
            return (s.group(1).upper() if s else ""), d_only.group(1).upper()
    return None, None


def load_pdf_index():
    """D-code → list of {eidh, design_id, client, pom_count, mcs}."""
    idx = defaultdict(list)
    n = 0
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            n += 1
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms == 0:
                continue
            sid = (e.get("design_id") or "").strip()
            m = re.match(r"(D\d{2,5})", sid)
            if not m:
                continue
            idx[m.group(1)].append({
                "eidh": str(e.get("eidh")),
                "design_id": sid,
                "client": e.get("client_code"),
                "pom_count": poms,
                "mcs": e.get("measurement_charts"),
            })
    print(f"  [index] {n:,} pdf_facets scanned, {len(idx):,} D-codes with POM data")
    return idx


def find_candidates(target_brands):
    cands = {}
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("client_code") not in target_brands:
                continue
            sid = (e.get("design_id") or "").strip()
            if not sid.startswith("D"):
                continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0:
                continue
            cands[str(e.get("eidh"))] = {
                "eidh": str(e.get("eidh")),
                "design_id": sid,
                "client": e.get("client_code"),
            }
    print(f"  [candidates] {len(cands):,} zero-POM D-prefix designs")

    with_pptx = 0
    with open(PPTX_FACETS, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            eidh = str(e.get("eidh", ""))
            if eidh not in cands:
                continue
            rtf = e.get("raw_text_file")
            if rtf and Path(rtf).exists():
                cands[eidh]["pptx_text_path"] = rtf
                with_pptx += 1
    print(f"  [pptx_join] {with_pptx:,} have PPTX raw_text")
    return list(cands.values())


def resolve(cands, pdf_idx):
    resolved, unresolvable, no_marker = [], [], 0
    for c in cands:
        path = c.get("pptx_text_path")
        if not path:
            no_marker += 1
            continue
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            no_marker += 1
            continue
        ref_season, ref_d = extract_co_ref(txt)
        if not ref_d:
            no_marker += 1
            continue
        if ref_d not in pdf_idx:
            unresolvable.append({**c, "ref_season": ref_season, "ref_d": ref_d})
            continue
        targets = pdf_idx[ref_d]
        same = [t for t in targets if t["client"] == c["client"]]
        pool = same if same else targets
        best = max(pool, key=lambda t: t["pom_count"])
        resolved.append({
            **c,
            "ref_season": ref_season, "ref_d": ref_d,
            "ref_eidh": best["eidh"], "ref_design_id": best["design_id"],
            "ref_client": best["client"], "ref_pom_count": best["pom_count"],
            "ref_mcs": best["mcs"], "n_alt_targets": len(targets),
        })
    return resolved, unresolvable, no_marker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--brand", nargs="*", default=["ONY"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    target_brands = set(b.upper() for b in args.brand)
    out_path = Path(args.out) if args.out else (EXTRACT_DIR / "pdf_facets_carry_over_patch.jsonl")

    print(f"=== Cross-Resolve Carry Over ===")
    print(f"  Target brands: {sorted(target_brands)}")
    print(f"  Output:        {out_path}")
    print()

    print("[1] Index PDF POMs by D-code")
    pdf_idx = load_pdf_index()
    print()
    print("[2] Find candidates")
    cands = find_candidates(target_brands)
    print()
    print("[3] Resolve via PPTX text scan")
    resolved, unresolvable, no_marker = resolve(cands, pdf_idx)

    print()
    print(f"=== Summary ===")
    print(f"  Total candidates:    {len(cands):,}")
    print(f"  Resolved:            {len(resolved):,}")
    print(f"    same-client:       {sum(1 for r in resolved if r['ref_client']==r['client']):,}")
    print(f"  Unresolvable:        {len(unresolvable):,}")
    print(f"  No CO marker:        {no_marker:,}")
    print()
    print("  Top 10 resolvable (POM count):")
    for r in sorted(resolved, key=lambda x: -x["ref_pom_count"])[:10]:
        print(f"    {r['eidh']}  {r['design_id']:<22} → {r['ref_eidh']} {r['ref_design_id']} "
              f"({r['ref_pom_count']} POMs, {r['ref_client']})")
    if unresolvable:
        cnt = Counter(u["ref_d"] for u in unresolvable)
        print()
        print(f"  Top 10 unresolvable ref_d (前季 archive 需聚陽端補):")
        for ref_d, n in cnt.most_common(10):
            print(f"    {ref_d:<10} 被 {n:>3} 件 reference")

    if args.dry_run:
        print()
        print("[dry-run] not writing")
        return 0

    print()
    print("[4] Build patch jsonl")
    eidh_map = {r["eidh"]: r for r in resolved}
    n_written = 0
    with open(out_path, "w", encoding="utf-8") as fout:
        with open(PDF_FACETS, encoding="utf-8") as fin:
            for line in fin:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                eidh = str(e.get("eidh", ""))
                if eidh not in eidh_map:
                    continue
                r = eidh_map[eidh]
                merged = dict(e)
                merged["measurement_charts"] = [
                    {**mc,
                     "_source": "carry_over_inherited",
                     "_ref_eidh": r["ref_eidh"],
                     "_ref_design_id": r["ref_design_id"]}
                    for mc in (r["ref_mcs"] or [])
                ]
                merged["_carry_over_patch"] = {
                    "ref_eidh": r["ref_eidh"],
                    "ref_design_id": r["ref_design_id"],
                    "ref_client": r["ref_client"],
                    "ref_season": r["ref_season"],
                    "ref_d": r["ref_d"],
                    "ref_pom_count": r["ref_pom_count"],
                }
                fout.write(json.dumps(merged, ensure_ascii=False) + "\n")
                n_written += 1
    print(f"  [write] {n_written:,} entries → {out_path}")
    print()
    print(f"=== Next step ===")
    print(f"  mv {out_path.name} → pdf_facets_<BRAND>_COPATCH.jsonl 再跑 merge_pdf_facets.py --backup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
