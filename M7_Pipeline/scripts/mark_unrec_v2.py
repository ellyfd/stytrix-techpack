"""mark_unrec_v2.py — brand-agnostic unrecoverable POM marker.
Output filename auto-derives from --brand list."""
import argparse, json, re, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
PPTX_FACETS = EXTRACT_DIR / "pptx_facets.jsonl"

CO_STRONG_ANCHOR_RE = re.compile(
    r"(?:尺寸表\s*參考|參考\s*前季|參考\s*大貨"
    r"|(?:Missy|Plus|Petite|Tall|Maternity|Kids|Baby|Toddler|Youth|Mens?|Womens?)?\s*跳檔[^\n]{0,12}?參考"
    r"|跳檔[^\n]{0,12}?參考)", re.IGNORECASE)
CO_BOM_REF_RE = re.compile(r"參考[^\n]{0,10}?(D\d{2,5}_BOM\d{4,8})", re.IGNORECASE)
CO_DCODE_RE = re.compile(r"(D\d{2,5})\b", re.IGNORECASE)
POM_HDR_RE = re.compile(r"Measurement Chart Review", re.I)
PROD_RE = re.compile(r"Centric 8\s*\|?\s*Production", re.I)

# Dev sample regex (synced with audit_3source_coverage.py)
DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*)", re.IGNORECASE)
GAP_DEV_RE = re.compile(
    r"(GAP\w+|GST\w+|GSM\w*|INNOV|^SP\d{2}GO\w*|^SS\d{2}GST\w*|^CM\d{2}\w+|^MK\d{4}\w*)",
    re.IGNORECASE)


def is_dev(sid):
    if not sid: return False
    if DEV_RE.match(sid): return True
    if GAP_DEV_RE.search(sid): return True
    return False


def extract_co_ref_d(txt):
    m = CO_STRONG_ANCHOR_RE.search(txt)
    if m:
        end = min(len(txt), m.end() + 80)
        window = txt[m.start():end]
        nl = window.find("\n\n")
        if nl > 0: window = window[:nl]
        d = CO_DCODE_RE.search(window)
        if d: return d.group(1).upper()
    m = CO_BOM_REF_RE.search(txt)
    if m:
        d_only = re.match(r"(D\d{2,5})", m.group(1), re.IGNORECASE)
        if d_only: return d_only.group(1).upper()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", nargs="*", default=["ONY"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    tb = set(b.upper() for b in args.brand)
    if args.out:
        out_path = Path(args.out)
    else:
        suffix = "_".join(sorted(b.lower() for b in tb))
        out_path = EXTRACT_DIR / f"{suffix}_pom_unrecoverable.jsonl"

    print(f"=== Mark Unrecoverable POM ===")
    print(f"  Brands: {sorted(tb)}    Out: {out_path}")
    print()

    pdf_with_poms = set()
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms == 0: continue
            sid = (e.get("design_id") or "").strip()
            mm = re.match(r"(D\d{2,5})", sid)
            if mm: pdf_with_poms.add(mm.group(1))

    cands = {}
    bucket_a = set()
    n_dev_skip = 0
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("client_code") not in tb: continue
            sid = (e.get("design_id") or "").strip()
            # GAP/ONY may have D prefix OR # prefix OR pure digits
            if not (sid.startswith("D") or sid.startswith("#") or sid[:6].isdigit()): continue
            if is_dev(sid):
                n_dev_skip += 1; continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0: continue
            all_text = ""
            for cp in e.get("construction_pages") or []:
                for ci in cp.get("construction_items") or []:
                    all_text += ci.get("_raw_callout_text") or ""
            eidh = str(e.get("eidh"))
            # Bucket A check — rescuable by Centric 8 Production parser
            if POM_HDR_RE.search(all_text) and PROD_RE.search(all_text):
                bucket_a.add(eidh); continue
            cands[eidh] = {
                "eidh": eidh, "design_id": sid,
                "client": e.get("client_code"), "client_raw": e.get("client_raw"),
            }
    print(f"  dev skipped:                     {n_dev_skip:,}")
    print(f"  Bucket A (parser rescuable):     {len(bucket_a):,}")
    print(f"  Bucket B candidates:             {len(cands):,}")

    pptx_paths = {}
    with open(PPTX_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = str(e.get("eidh", ""))
            if eidh not in cands: continue
            rtf = e.get("raw_text_file")
            if rtf and Path(rtf).exists():
                pptx_paths[eidh] = rtf

    categories = Counter()
    out_entries = []
    for eidh, c in cands.items():
        path = pptx_paths.get(eidh)
        if not path:
            cat = "no_pptx_text"; ref_d = None
        else:
            try: txt = open(path, encoding="utf-8").read()
            except: cat = "no_pptx_text"; ref_d = None
            else:
                ref_d = extract_co_ref_d(txt)
                if ref_d is None:
                    cat = "no_co_marker_no_source"
                elif ref_d in pdf_with_poms:
                    continue  # resolvable, skip
                else:
                    cat = "co_unresolvable_archived"
        categories[cat] += 1
        out_entries.append({
            "eidh": eidh, "design_id": c["design_id"],
            "client_code": c["client"], "client_raw": c["client_raw"],
            "_pom_unrecoverable": True,
            "_unrecoverable_reason": cat,
            "_ref_d_missing": ref_d if cat == "co_unresolvable_archived" else None,
        })

    print()
    print(f"=== Categories ===")
    for cat, n in categories.most_common():
        print(f"  {cat:<32} {n:>5,}")
    print(f"  {'TOTAL':<32} {sum(categories.values()):>5,}")

    with open(out_path, "w", encoding="utf-8") as fout:
        for entry in out_entries:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print()
    print(f"  [write] {len(out_entries):,} entries to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
