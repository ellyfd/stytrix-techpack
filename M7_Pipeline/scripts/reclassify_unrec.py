"""reclassify_unrec.py — Audit 5 brand unrec list, split into 3 honest categories.

A: parser-fail        — PDF/PPTX 有 POM/MC 內容 but parser miss → rescuable, shouldn't be unrec
B: sample-room-prefix — based on design code prefix pattern, INFERENCE not user-confirmed
C: true-no-source     — no MC content anywhere in 3 sources (verifiable, objective)

Produces per-brand prefix breakdown + sample EIDH for user to spot-check.
"""
import json, re
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
PPTX_FACETS = EXTRACT_DIR / "pptx_facets.jsonl"

# Brand-specific "Sample Room prefix" patterns I INVENTED — needs user confirm
SAMPLE_ROOM_PREFIX_INFERRED = {
    "UA": re.compile(r"^(UATSM[A-Z]?\w*|VELOC\w*|UAMGF\w*|UASS\d+\w*|FW\d{2}U[\w\-]*)", re.I),
    "KOH": re.compile(
        r"^(SU\d{2}C\w*|SP\d{2}C\w*|FA\d{2}C\w*|SP\d{2}S\w*|SU\d{2}S\w*|"
        r"RDWT\w*|RDMX\w*|RDEX\w*|RDMT\w*|MX\d[A-Z]\w*|WX\d[A-Z]\w*|"
        r"KOH\d{2}\w*|ZS\dF\w*|MK\d{2}AW\w*|MSFA\d\w*|SOMEN\w*)", re.I),
    "DKS": re.compile(r"^(DAG[12]\w*|DAB\d+\w*|DAYS\w*|DAYUSA\w*|OSUD\w*|DAM\d+\w*|MAX\d\w*|MGA\d\w*)", re.I),
    "ONY": re.compile(r"^$"),  # ONY uses CO marker logic, no prefix inference
    "GAP": re.compile(r"^$"),  # GAP uses CO marker logic, no prefix inference
}

POM_HDR_RE = re.compile(r"POM|Measurement|TOL|Point of Measure|Tol\s*\(", re.I)


def load_pdf_lookup():
    lookup = {}
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = str(e.get("eidh", ""))
            lookup[eidh] = e
    return lookup


def load_pptx_lookup():
    lookup = {}
    with open(PPTX_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = str(e.get("eidh", ""))
            lookup[eidh] = e
    return lookup


def classify(entry, pdf_e, pptx_e, sample_room_re):
    """Return (category, reason_detail, evidence)."""
    sid = entry.get("design_id", "")
    eidh = entry.get("eidh", "")
    existing_reason = entry.get("_unrecoverable_reason", "")

    # First — if reason already indicates parser fail explicitly, keep that
    if "parser_fail" in existing_reason or "parser_failed" in existing_reason or "parser_horizontal" in existing_reason or "blank" in existing_reason:
        return "A_parser_fail", existing_reason, "parser attempted but no_pom_table"

    # Check PDF has any MC/POM text?
    pdf_has_mc_text = False
    if pdf_e:
        for cp in pdf_e.get("construction_pages") or []:
            for ci in cp.get("construction_items") or []:
                if POM_HDR_RE.search(ci.get("_raw_callout_text") or ""):
                    pdf_has_mc_text = True; break
            if pdf_has_mc_text: break
        # Also check mc_entries — if parser attempted (mc_entries > 0), it's parser fail land
        n_mc_entries = len(pdf_e.get("measurement_charts") or [])
        if n_mc_entries > 0 and not pdf_has_mc_text:
            # Parser found measurement pages but no POM text in CP — could still be parser-fail
            # (page_classifier marked as MC but parser couldn't read)
            pdf_has_mc_text = True

    # Sample room prefix?
    if sample_room_re and sample_room_re.match(sid):
        # If PDF has MC text + sample room prefix, it's BOTH — but priority to user-confirm flag
        return "B_sample_room_prefix", f"prefix_match:{sid[:6]}", "prefix-based inference, needs user confirm"

    # Parser fail (has MC content)
    if pdf_has_mc_text:
        return "A_parser_fail", existing_reason or "has_mc_text_but_no_poms", "PDF has POM-related text"

    # PPTX has POM-related content?
    pptx_has_mc = False
    if pptx_e:
        # constructions array or raw_text file could have 中文 POM names
        rtf = pptx_e.get("raw_text_file")
        if rtf and Path(rtf).exists():
            try:
                txt = open(rtf, encoding="utf-8").read()
                if re.search(r"(身長|胸圍|肩寬|袖長|腰圍|前襠|後襠|跳檔|尺寸表)", txt):
                    pptx_has_mc = True
            except Exception:
                pass

    # No MC anywhere — true no source
    return "C_true_no_source", existing_reason or "no_mc_in_any_source", "no MC text in PDF / no Chinese POM names in PPTX"


def main():
    pdf_lookup = load_pdf_lookup()
    pptx_lookup = load_pptx_lookup()

    overall = defaultdict(lambda: defaultdict(int))  # brand → category → count
    per_brand_details = defaultdict(lambda: defaultdict(list))  # brand → category → [(eidh, sid, reason)]
    prefix_counts = defaultdict(lambda: defaultdict(Counter))  # brand → category → Counter(prefix)

    unrec_files = sorted(EXTRACT_DIR.glob("*_pom_unrecoverable.jsonl"))
    for f_path in unrec_files:
        # brand from filename: 'ony_pom_unrecoverable.jsonl' → 'ONY'
        brand = f_path.stem.split("_")[0].upper()
        sample_re = SAMPLE_ROOM_PREFIX_INFERRED.get(brand)
        with open(f_path, encoding="utf-8") as f:
            for line in f:
                try: e = json.loads(line)
                except: continue
                eidh = str(e.get("eidh", ""))
                sid = e.get("design_id", "")
                pdf_e = pdf_lookup.get(eidh)
                pptx_e = pptx_lookup.get(eidh)
                cat, reason, evidence = classify(e, pdf_e, pptx_e, sample_re)
                overall[brand][cat] += 1
                if len(per_brand_details[brand][cat]) < 5:
                    per_brand_details[brand][cat].append((eidh, sid, reason))
                prefix_counts[brand][cat][sid[:5] if sid else "?"] += 1

    # Print report
    print("=" * 100)
    print("UNRECOVERABLE RECLASSIFICATION REPORT")
    print("=" * 100)
    print()
    print(f"{'Brand':<6} {'A:parser-fail':>15} {'B:prefix-infer':>17} {'C:true-no-source':>20} {'Total':>8}")
    print("-" * 70)
    for brand in sorted(overall.keys()):
        a = overall[brand]["A_parser_fail"]
        b = overall[brand]["B_sample_room_prefix"]
        c = overall[brand]["C_true_no_source"]
        print(f"{brand:<6} {a:>15,} {b:>17,} {c:>20,} {a+b+c:>8,}")

    print()
    print("=" * 100)
    print("PER-BRAND BREAKDOWN")
    print("=" * 100)
    for brand in sorted(overall.keys()):
        print(f"\n### {brand} ###")
        for cat in ["A_parser_fail", "B_sample_room_prefix", "C_true_no_source"]:
            n = overall[brand][cat]
            if n == 0: continue
            label = {"A_parser_fail":"A: PARSER-FAIL (rescuable, should NOT be unrec)",
                     "B_sample_room_prefix":"B: SAMPLE-ROOM-PREFIX (user-needs-confirm)",
                     "C_true_no_source":"C: TRUE NO-SOURCE (objectively missing)"}[cat]
            print(f"\n  [{n:>4}] {label}")
            # Top prefixes
            top = prefix_counts[brand][cat].most_common(8)
            print(f"    Top prefixes:")
            for p, n_p in top:
                print(f"      {p:<8} {n_p:>4}")
            print(f"    Sample EIDHs:")
            for eidh, sid, reason in per_brand_details[brand][cat]:
                print(f"      {eidh}  {sid:<25}  reason={reason}")


if __name__ == "__main__":
    main()
