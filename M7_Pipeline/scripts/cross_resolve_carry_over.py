"""cross_resolve_carry_over.py — Carry Over POM 反查腳本.

問題:
  ONY 跨季 carry-over 設計（PPTX 寫「尺寸表參考 FA24 D718_BOM705122」)
  本身 PDF 沒有 POM table, 但 referenced 前季 design 的 POM 已經在我們 pdf_facets 內.

策略:
  1. Scan pptx_text/ONY_*.txt 找「尺寸表參考」+「D-code」pattern
  2. 對每個 EIDH, extract referenced D-code
  3. 用 pdf_facets D-code index 反查 referenced source EIDH
  4. 把 measurement_charts 從 referenced source 複製到 carry-over EIDH
     (加 metadata: _carry_over=True / _ref_eidh / _ref_design_id)

產出:
  outputs/extract/pdf_facets_carry_over_patch.jsonl  (per-brand 風格的 patch)
  跑 merge_pdf_facets.py 合進中央 pdf_facets.jsonl 即生效.

用法:
  python3 scripts/cross_resolve_carry_over.py [--dry-run] [--brand ONY GAP]
"""
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
PPTX_FACETS = EXTRACT_DIR / "pptx_facets.jsonl"
PPTX_TEXT_DIR = EXTRACT_DIR / "pptx_text"

# Two-step approach more robust to varied wording:
#   1. CO_ANCHOR_RE: locate "尺寸表參考" / "參考前季" / "參考大貨" anchor
#   2. CO_DCODE_FOLLOW_RE: within next 60 chars find a D-code
# Edge cases observed:
#   "尺寸表參考FA24 D718_BOM705122"    → D718
#   "尺寸表參考D62222"                  → D62222
#   "參考FA23大貨S/757881(D17060)"     → D17060 (in parens after sample number)
#   "尺寸表參考S/567695"                → no D-code → unresolvable (大貨樣號需 m7 map)
#   "尺寸表參考大貨款號586258_HO24"      → no D-code → unresolvable
CO_ANCHOR_RE = re.compile(r"(?:尺寸表\s*參考|參考\s*前季|參考\s*大貨)", re.IGNORECASE)
CO_DCODE_FOLLOW_RE = re.compile(r"(D\d{2,5})\b", re.IGNORECASE)
CO_SEASON_FOLLOW_RE = re.compile(r"((?:FA|SP|HO|WI|SS|HW|HO)\d{2})", re.IGNORECASE)


def _extract_co_ref(txt):
    """Find first CO marker, return (ref_season, ref_d) or (None, None)."""
    m = CO_ANCHOR_RE.search(txt)
    if not m:
        return None, None
    # search window: from marker start, next 80 chars (or to next \n)
    window_end = min(len(txt), m.end() + 80)
    # cut window at first \n+\n (paragraph break) to avoid grabbing from next section
    window = txt[m.start():window_end]
    nl_break = window.find("\n\n")
    if nl_break > 0:
        window = window[:nl_break]
    d_match = CO_DCODE_FOLLOW_RE.search(window)
    if not d_match:
        return None, None
    ref_d = d_match.group(1).upper()
    s_match = CO_SEASON_FOLLOW_RE.search(window)
    ref_season = s_match.group(1).upper() if s_match else ""
    return ref_season, ref_d


def load_pdf_index(target_brands=None):
    """Build D-code → list of source EIDHs (with POMs) from pdf_facets."""
    index = defaultdict(list)
    n_total = 0
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            n_total += 1
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms == 0:
                continue
            sid = (e.get("design_id") or "").strip()
            m = re.match(r"(D\d{2,5})", sid)
            if not m:
                continue
            d = m.group(1)
            index[d].append({
                "eidh": str(e.get("eidh")),
                "design_id": sid,
                "client": e.get("client_code"),
                "pom_count": poms,
                "mcs": e.get("measurement_charts"),
            })
    print(f"  [index] {n_total:,} pdf_facets entries scanned, "
          f"{len(index):,} D-codes with POM data")
    return index


def find_carry_over_candidates(target_brands=None):
    """Scan pdf_facets for designs that need carry-over rescue.

    Criteria:
      - design_id startswith 'D' (production design code)
      - client in target_brands (default: ONY)
      - measurement_charts has 0 POMs
      - has PPTX raw_text file with carry-over marker

    Returns:
      list of dicts: {eidh, design_id, client, pptx_text_path}
    """
    if target_brands is None:
        target_brands = {"ONY"}
    target_brands = set(target_brands)

    # PDF candidates first
    candidates = {}
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
            eidh = str(e.get("eidh"))
            candidates[eidh] = {
                "eidh": eidh,
                "design_id": sid,
                "client": e.get("client_code"),
                "client_raw": e.get("client_raw"),
                "metadata": e.get("metadata") or {},
                "pdf_entry_keys": list(e.keys()),
            }
    print(f"  [candidates] {len(candidates):,} zero-POM D-prefix designs")

    # Cross-reference PPTX raw_text
    with_pptx = 0
    with open(PPTX_FACETS, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            eidh = str(e.get("eidh", ""))
            if eidh not in candidates:
                continue
            rtf = e.get("raw_text_file")
            if rtf and Path(rtf).exists():
                candidates[eidh]["pptx_text_path"] = rtf
                with_pptx += 1
    print(f"  [pptx_join] {with_pptx:,} have PPTX raw_text")

    return list(candidates.values())


def resolve_carry_over(candidates, pdf_index):
    """For each candidate, find CO marker in PPTX text and resolve to source EIDH."""
    resolved = []
    no_marker = 0
    unresolvable = []

    for c in candidates:
        path = c.get("pptx_text_path")
        if not path:
            no_marker += 1
            continue
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            no_marker += 1
            continue

        ref_season, ref_d = _extract_co_ref(txt)
        if not ref_d:
            no_marker += 1
            continue

        if ref_d not in pdf_index:
            unresolvable.append({**c, "ref_season": ref_season, "ref_d": ref_d})
            continue

        # Pick best target — highest POM count, prefer same client
        targets = pdf_index[ref_d]
        same_client = [t for t in targets if t["client"] == c["client"]]
        pool = same_client if same_client else targets
        best = max(pool, key=lambda t: t["pom_count"])

        resolved.append({
            **c,
            "ref_season": ref_season,
            "ref_d": ref_d,
            "ref_eidh": best["eidh"],
            "ref_design_id": best["design_id"],
            "ref_client": best["client"],
            "ref_pom_count": best["pom_count"],
            "ref_mcs": best["mcs"],
            "n_alt_targets": len(targets),
        })

    return resolved, unresolvable, no_marker


def build_patch_entries(resolved):
    """Build pdf_facets-shape entries with inherited measurement_charts."""
    out = []
    for r in resolved:
        # Build a new entry that overrides the candidate's measurement_charts
        # while preserving all other fields. We only need a partial entry — merge script
        # will replace by EIDH.
        # Strategy: load the original PDF entry from PDF_FACETS, only overwrite
        # measurement_charts. We do this in main() via streaming.
        # Here we just build a marker dict for later merge.
        out.append({
            "eidh": r["eidh"],
            "_carry_over_patch": {
                "ref_eidh": r["ref_eidh"],
                "ref_design_id": r["ref_design_id"],
                "ref_client": r["ref_client"],
                "ref_season": r["ref_season"],
                "ref_d": r["ref_d"],
                "ref_pom_count": r["ref_pom_count"],
            },
            "measurement_charts": [
                {**mc,
                 "_source": "carry_over_inherited",
                 "_ref_eidh": r["ref_eidh"],
                 "_ref_design_id": r["ref_design_id"]}
                for mc in (r["ref_mcs"] or [])
            ],
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只看 summary 不寫檔")
    ap.add_argument("--brand", nargs="*", default=["ONY"], help="目標 brand codes (default: ONY)")
    ap.add_argument("--out", default=None, help="output patch jsonl path (default: outputs/extract/pdf_facets_carry_over_patch.jsonl)")
    args = ap.parse_args()

    target_brands = set(b.upper() for b in args.brand)
    out_path = Path(args.out) if args.out else (EXTRACT_DIR / "pdf_facets_carry_over_patch.jsonl")

    print(f"=== Cross-Resolve Carry Over ===")
    print(f"  Target brands: {sorted(target_brands)}")
    print(f"  Output: {out_path}")
    print()

    print("[Step 1] Build D-code → source PDF index")
    pdf_index = load_pdf_index(target_brands=target_brands)

    print()
    print("[Step 2] Find carry-over candidates")
    candidates = find_carry_over_candidates(target_brands=target_brands)

    print()
    print("[Step 3] Resolve via PPTX raw_text scan")
    resolved, unresolvable, no_marker = resolve_carry_over(candidates, pdf_index)

    print()
    print(f"=== Resolution Summary ===")
    print(f"  Total candidates:       {len(candidates):,}")
    print(f"  Resolved (will patch):  {len(resolved):,}")
    print(f"    of which copying POMs from same client: "
          f"{sum(1 for r in resolved if r.get('ref_client')==r.get('client')):,}")
    print(f"  Unresolvable (ref_d not in our PDF data): {len(unresolvable):,}")
    print(f"  No CO marker in PPTX:   {no_marker:,}")
    print()

    # Top resolvable preview
    print("  Top 10 resolvable (POM count):")
    for r in sorted(resolved, key=lambda x: -x["ref_pom_count"])[:10]:
        print(f"    {r['eidh']}  {r['design_id']:<22} → {r['ref_eidh']} {r['ref_design_id']} "
              f"({r['ref_pom_count']} POMs, {r['ref_client']})")

    if unresolvable:
        # Group unresolvable by ref_d to show concentration
        from collections import Counter
        ref_counts = Counter(u["ref_d"] for u in unresolvable)
        print()
        print(f"  Top 10 unresolvable ref_d (前季 archives needed):")
        for ref_d, cnt in ref_counts.most_common(10):
            print(f"    {ref_d:<10} 被 {cnt:>3} 件 carry-over reference")

    if args.dry_run:
        print()
        print("[dry-run] not writing patch file")
        return 0

    # Build patch entries
    print()
    print("[Step 4] Build patch entries")
    patches = build_patch_entries(resolved)

    # To produce a complete pdf_facets-shape patch, we need to merge with the
    # original PDF entry — load original, override measurement_charts.
    print("[Step 5] Merge with original PDF entries → patch jsonl")
    eidh_to_patch = {p["eidh"]: p for p in patches}
    n_written = 0
    with open(out_path, "w", encoding="utf-8") as fout:
        with open(PDF_FACETS, encoding="utf-8") as fin:
            for line in fin:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                eidh = str(e.get("eidh", ""))
                if eidh not in eidh_to_patch:
                    continue
                p = eidh_to_patch[eidh]
                # Merge: keep original metadata/construction_pages/etc, override MC
                merged = dict(e)
                merged["measurement_charts"] = p["measurement_charts"]
                merged["_carry_over_patch"] = p["_carry_over_patch"]
                fout.write(json.dumps(merged, ensure_ascii=False) + "\n")
                n_written += 1
    print(f"  [write] {n_written:,} entries → {out_path}")
    print()
    print(f"=== Next step ===")
    print(f"  跑 merge_pdf_facets.py 把 patch 合進中央 (記得 --backup):")
    print(f"    cp {out_path.name} {EXTRACT_DIR}/pdf_facets_COPATCH.jsonl")
    print(f"    python3 scripts/merge_pdf_facets.py --backup")
    print(f"  或手動: 直接 mv {out_path.name} → pdf_facets_<BRAND>.jsonl 也行")

    return 0


if __name__ == "__main__":
    sys.exit(main())
# eof
