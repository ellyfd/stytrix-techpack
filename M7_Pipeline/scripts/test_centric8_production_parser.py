"""Standalone test for the new Centric 8 Production parser.

Loads sample raw_text from pdf_facets.jsonl (EIDH 306119) and runs the
parser logic to verify POM extraction.
"""
import re
import json
import sys
from pathlib import Path

_PROD_POM_CODE_RE = re.compile(r"^[A-Z]\d{1,3}(?:\.\d{1,2})?$")
_PROD_TOL_RE = re.compile(
    r"^-?\s*\d+([\s]?[/⁄][\s]?\d+)?$"
    r"|^-?\s*\d+\s+\d+[/⁄]\d+$"
    r"|^-?\s*\d+\.\d+$"
    r"|^0\.0$"
    r"|^=?\s*<\s*\d+/\d+$"
)


def _is_centric_prod_tol(s):
    if not s:
        return False
    s2 = s.strip()
    if not s2:
        return False
    if _PROD_TOL_RE.match(s2):
        return True
    if s2.startswith("-") and any(c.isdigit() for c in s2):
        return True
    return False


def _is_centric_prod_target(s):
    if not s:
        return False
    s2 = s.strip()
    if not s2:
        return False
    if re.match(r"^\d+$", s2):
        return True
    if re.match(r"^\d+\s+\d+[/⁄]\d+$", s2):
        return True
    if re.match(r"^\d+[/⁄]\d+$", s2):
        return True
    return False


def parse_centric8_production_textmode(text, base_size="M"):
    lines = [l.rstrip() for l in text.split("\n")]
    poms = []
    i = 0
    n = len(lines)

    while i < n:
        if _PROD_POM_CODE_RE.match(lines[i].strip()):
            break
        i += 1

    while i < n:
        line = lines[i].strip()
        if not _PROD_POM_CODE_RE.match(line):
            i += 1
            continue

        code = line
        pom = {"POM_Code": code}

        name_parts = []
        j = i + 1
        tol_values = []
        scan_end = min(j + 25, n)
        while j < scan_end:
            l = lines[j].strip()
            if _PROD_POM_CODE_RE.match(l):
                break
            if _is_centric_prod_tol(l):
                k = j + 1
                while k < scan_end and not lines[k].strip():
                    k += 1
                if k < scan_end and _is_centric_prod_tol(lines[k].strip()):
                    tol_values = [l, lines[k].strip()]
                    j = k + 1
                    break
                tol_values = [l]
                j = j + 1
                break
            if l:
                name_parts.append(l)
            j += 1

        if name_parts:
            full_name = " ".join(name_parts)[:200]
            pom["POM_Name"] = full_name

        if len(tol_values) == 2:
            t1, t2 = tol_values
            if t1.lstrip().startswith("-"):
                tol_neg, tol_pos = t1, t2
            elif t2.lstrip().startswith("-"):
                tol_neg, tol_pos = t2, t1
            else:
                tol_neg, tol_pos = t1, t2
            pom["tolerance"] = {"neg": tol_neg, "pos": tol_pos}
        elif len(tol_values) == 1:
            pom["tolerance"] = {"neg": tol_values[0]}

        scan2_end = min(j + 12, n)
        while j < scan2_end:
            l = lines[j].strip()
            if _PROD_POM_CODE_RE.match(l):
                break
            if _is_centric_prod_target(l):
                pom["sizes"] = {base_size: l}
                j += 1
                break
            j += 1

        if pom.get("sizes"):
            poms.append(pom)

        next_code_idx = None
        scan3_end = min(j + 20, n)
        while j < scan3_end:
            if _PROD_POM_CODE_RE.match(lines[j].strip()):
                next_code_idx = j
                break
            j += 1
        i = next_code_idx if next_code_idx else (j + 1)

    if not poms:
        return {}
    return {"sizes": [base_size], "poms": poms, "n_poms_on_page": len(poms),
            "layout": "centric8_production_mc_review"}


# ============================================================
# Test against real EIDH 306119
# ============================================================
def main():
    facets = Path(__file__).resolve().parent.parent / "outputs/extract/pdf_facets.jsonl"
    test_eidh = "306119"
    print(f"Loading sample text for EIDH {test_eidh}...")
    pages = []
    with open(facets, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if str(e.get("eidh")) == test_eidh:
                for cp in e.get("construction_pages") or []:
                    for ci in cp.get("construction_items") or []:
                        txt = ci.get("_raw_callout_text") or ""
                        if ("Centric 8 Production" in txt and
                            "Measurement Chart Review" in txt):
                            pages.append((cp.get("page"), txt))
                break

    print(f"Found {len(pages)} Production MC Review pages")
    total = 0
    for page_num, txt in pages:
        print(f"\n--- Page {page_num} ---")
        result = parse_centric8_production_textmode(txt, base_size="M")
        poms = result.get("poms", [])
        total += len(poms)
        print(f"POMs: {len(poms)}")
        for p in poms[:8]:
            tol = p.get("tolerance", {})
            tol_str = f"({tol.get('neg','?')}, {tol.get('pos','?')})"
            print(f"  {p.get('POM_Code'):<8} {(p.get('POM_Name','') or '')[:45]:<45}  "
                  f"M={p.get('sizes',{}).get('M','?'):<8}  tol={tol_str}")
        if len(poms) > 8:
            print(f"  ... +{len(poms)-8} more")
    print(f"\n=== Total POMs across all pages: {total} ===")


if __name__ == "__main__":
    main()
