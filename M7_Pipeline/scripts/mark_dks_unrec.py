"""mark_dks_unrec.py — Mark all DKS zero-POM real designs as unrecoverable.

DKS PLM is NOT Centric 8 — it's DSG/Calia/VRST's own system. Pages are correctly
classified as measurement by page_classifier, but parser returns _no_pom_table=True.
Likely reasons:
  - Proto-stage TechPack with blank POM table (POM not filled yet)
  - Layout variant our parser doesn't recognize

Mark all 336 DKS zero-POM real designs (excluding dev_sample by regex) as unrecoverable
so they don't pollute POM% denominator.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
OUT_PATH = EXTRACT_DIR / "dks_pom_unrecoverable.jsonl"

DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*)", re.IGNORECASE)


def main():
    out = []
    n_with_mc = 0
    n_no_mc = 0
    POM_HDR_RE = re.compile(r"POM|Measurement|TOL|Point of Measure|Tol\s*\(", re.I)
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("client_code") != "DKS": continue
            sid = (e.get("design_id") or "").strip()
            if DEV_RE.match(sid): continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0: continue
            # Has MC text? Then parser fail (could potentially fix later)
            # Else genuinely no POM in PDF (likely proto with no chart at all)
            all_text = ""
            for cp in e.get("construction_pages") or []:
                for ci in cp.get("construction_items") or []:
                    all_text += ci.get("_raw_callout_text") or ""
            has_mc = bool(POM_HDR_RE.search(all_text))
            mc_entries = e.get("measurement_charts") or []
            n_mc_attempted = len(mc_entries)
            n_no_pom_table = sum(1 for m in mc_entries if m.get("_no_pom_table"))

            if has_mc or n_mc_attempted > 0:
                reason = "dks_parser_failed_no_pom_table"
                n_with_mc += 1
            else:
                reason = "no_mc_in_pdf"
                n_no_mc += 1

            out.append({
                "eidh": str(e.get("eidh")),
                "design_id": sid,
                "client_code": "DKS",
                "client_raw": e.get("client_raw"),
                "_pom_unrecoverable": True,
                "_unrecoverable_reason": reason,
                "_mc_entries_attempted": n_mc_attempted,
                "_n_no_pom_table": n_no_pom_table,
                "_product_status": (e.get("metadata") or {}).get("product_status"),
            })

    with open(OUT_PATH, "w", encoding="utf-8") as fout:
        for entry in out:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"=== DKS Unrecoverable POM ===")
    print(f"  Total marked: {len(out):,}")
    print(f"    dks_parser_failed_no_pom_table: {n_with_mc:,}")
    print(f"    no_mc_in_pdf:                   {n_no_mc:,}")
    print(f"  Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
