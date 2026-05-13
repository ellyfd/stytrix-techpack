"""mark_koh_unrec.py — Mark all KOH zero-POM real designs as unrecoverable.

KOH has many Sample Room internal codes (SU26CB/SP26CB/RDWT6/MX5FK/WX5HA/ZS6FP/
MK26AW/KOH26 etc.) that don't match existing DEV_RE prefixes but are clearly internal
Makalot Sample Room TechPacks — they typically only have BOM + construction text in PDF,
no POM table. Mark them all as unrecoverable.

Same pattern as DKS (mark_dks_unrec.py).
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
OUT_PATH = EXTRACT_DIR / "koh_pom_unrecoverable.jsonl"

DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*)", re.IGNORECASE)

POM_HDR_RE = re.compile(r"POM|Measurement|TOL|Point of Measure|Tol\s*\(", re.I)


def main():
    out = []
    n_parser_fail = 0
    n_no_mc = 0
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("client_code") != "KOH": continue
            sid = (e.get("design_id") or "").strip()
            if DEV_RE.match(sid): continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0: continue
            all_text = ""
            for cp in e.get("construction_pages") or []:
                for ci in cp.get("construction_items") or []:
                    all_text += ci.get("_raw_callout_text") or ""
            mc_entries = e.get("measurement_charts") or []
            has_mc = bool(POM_HDR_RE.search(all_text)) or len(mc_entries) > 0
            if has_mc:
                reason = "koh_parser_failed_or_blank"
                n_parser_fail += 1
            else:
                reason = "no_mc_in_pdf"
                n_no_mc += 1
            out.append({
                "eidh": str(e.get("eidh")),
                "design_id": sid,
                "client_code": "KOH",
                "client_raw": e.get("client_raw"),
                "_pom_unrecoverable": True,
                "_unrecoverable_reason": reason,
                "_design_prefix": sid[:5] if sid else "?",
            })

    with open(OUT_PATH, "w", encoding="utf-8") as fout:
        for entry in out:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"=== KOH Unrecoverable POM ===")
    print(f"  Total marked: {len(out):,}")
    print(f"    koh_parser_failed_or_blank: {n_parser_fail:,}")
    print(f"    no_mc_in_pdf:               {n_no_mc:,}")
    print(f"  Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
