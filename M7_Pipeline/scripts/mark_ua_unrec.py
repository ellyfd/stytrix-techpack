"""mark_ua_unrec.py — Split UA zero-POM into:
  - real UA PLM with parser-fail (rescuable later by horizontal POM parser fix)
  - Sample Room codes (UATSM/VELOC/UAMGF/UASS2/FW27U) — mark unrecoverable

The Sample Room codes don't have POM tables in PDF, only metadata + sketches.
The real UA PLM ones have a Sort/Order horizontal POM layout the parser doesn't
match — those stay zero-POM for now but get a different marker.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
OUT_PATH = EXTRACT_DIR / "ua_pom_unrecoverable.jsonl"

DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*)", re.IGNORECASE)

# UA Sample Room dev prefixes (no POM expected — same logic as KOH FLX/APT)
UA_DEV_RE = re.compile(r"^(UATSM[A-Z]?\w*|VELOC\w*|UAMGF\w*|UASS\d+\w*|FW\d{2}U[\w\-]*)", re.IGNORECASE)


def main():
    out = []
    n_sample_room = 0
    n_real_parser_fail = 0
    n_real_no_mc = 0

    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("client_code") != "UA": continue
            sid = (e.get("design_id") or "").strip()
            if DEV_RE.match(sid): continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0: continue

            eidh = str(e.get("eidh"))
            mc_entries = e.get("measurement_charts") or []
            all_text = ""
            for cp in e.get("construction_pages") or []:
                for ci in cp.get("construction_items") or []:
                    all_text += ci.get("_raw_callout_text") or ""

            if UA_DEV_RE.match(sid):
                # Sample Room
                reason = "ua_sample_room"
                n_sample_room += 1
            elif "POMs" in all_text and "Tol" in all_text:
                # Real PLM, has POM text in CP — parser fail (horizontal Sort/Order layout)
                reason = "ua_parser_horizontal_sort_order_fail"
                n_real_parser_fail += 1
            else:
                reason = "ua_no_mc_in_pdf"
                n_real_no_mc += 1

            out.append({
                "eidh": eidh,
                "design_id": sid,
                "client_code": "UA",
                "client_raw": e.get("client_raw"),
                "_pom_unrecoverable": True,
                "_unrecoverable_reason": reason,
                "_design_prefix": sid[:5] if sid else "?",
                "_n_mc_entries_attempted": len(mc_entries),
            })

    with open(OUT_PATH, "w", encoding="utf-8") as fout:
        for entry in out:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"=== UA Unrecoverable POM ===")
    print(f"  Total marked: {len(out):,}")
    print(f"    ua_sample_room (UATSM/VELOC/UAMGF/UASS/FW27U): {n_sample_room:,}")
    print(f"    ua_parser_horizontal_sort_order_fail:          {n_real_parser_fail:,} ← 可 parser 救")
    print(f"    ua_no_mc_in_pdf:                               {n_real_no_mc:,}")
    print(f"  Wrote: {OUT_PATH}")


if __name__ == "__main__":
    main()
