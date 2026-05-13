"""Prototype + test ANF "horizontal POM" parser before integrating into _base.py.

Tests on 4 failing samples (S262460003 / S262460008 / 312619 / 312656).
"""
from __future__ import annotations
import re
import pdfplumber
from pathlib import Path


def parse_anf_horizontal_textmode(text: str) -> dict:
    """ANF/HLF A&F PROD InitialTechPack 橫向 POM layout, 帶分數換行.

    格式特徵:
      POMs                                                  ← anchor 行
      QA POM Description Tol (- ) Tol (+) Hide Length <size1> <size2> ... <sizeN>
        OR
      QA POM Description Tol (- ) Tol Hide Length <size1> ...
      (+)                                                   ← 連續行 (Tol(+) spillover)
      <CODE> <desc...> <tol_neg> <tol_pos> [Regular] [hide] <length> <vals...>
      <分母-only line>                                       ← fraction wrap row
    """
    lines = text.split("\n")

    # 1. Find "POMs" → "QA POM Description ..." header
    header_idx = -1
    for i in range(len(lines) - 1):
        if lines[i].strip() == "POMs":
            nxt = lines[i + 1]
            if "POM" in nxt and ("Description" in nxt or "Tol" in nxt):
                header_idx = i + 1
                break
    if header_idx < 0:
        return {}

    header = lines[header_idx]
    # If next line is "(+)" continuation, merge it
    body_start = header_idx + 1
    if body_start < len(lines) and lines[body_start].strip() in ("(+)", "( + )"):
        header = header + " (+)"
        body_start += 1

    # Find sizes after "Length"
    m = re.search(r"Length\s+(.+)$", header)
    if not m:
        return {}
    sizes = m.group(1).split()
    # Filter: drop trailing "(+)" or junk
    sizes = [s for s in sizes if s and s != "(+)"]
    if len(sizes) < 2:
        return {}

    POM_RE = re.compile(r"^\s*([A-Z]{1,3}\d{3}[A-Z]?-?)\s+(\S.*)$")
    DEN_TOKEN_RE = re.compile(r"^\d+$")
    VAL_RE = re.compile(r"^-?\d+(?:/\d+)?$")  # signed int or fraction
    FRAC_BAR = "⁄"  # ⁄

    n_sizes = len(sizes)
    poms = []

    i = body_start
    while i < len(lines):
        line = lines[i]
        ul = line.upper().strip()
        # Stop at footers
        if ul.startswith("PAGE ") or "DISPLAYING " in ul or "COPYRIGHT" in ul:
            break

        m2 = POM_RE.match(line)
        if not m2:
            i += 1
            continue

        code = m2.group(1).rstrip('-')
        rest = m2.group(2)

        # Check next line: fraction continuation (only digits + spaces)
        consumed_extra = 0
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            tokens = nxt.split() if nxt else []
            if tokens and all(DEN_TOKEN_RE.match(t) for t in tokens) and len(tokens) <= 30:
                # Merge: each ⁄ in rest pairs with one denominator
                # Count ⁄ in rest
                n_frac = rest.count(FRAC_BAR)
                if n_frac == len(tokens):
                    # Replace each "X⁄" with "X/Y" — keep existing whitespace intact
                    out = []
                    den_idx = 0
                    for ch in rest:
                        if ch == FRAC_BAR and den_idx < len(tokens):
                            out.append('/' + tokens[den_idx])
                            den_idx += 1
                        else:
                            out.append(ch)
                    rest = ''.join(out)
                    consumed_extra = 1

        i += 1 + consumed_extra

        # Tokenize rest
        tokens = rest.split()
        # Find first value token (after desc) — at least 1 desc word
        first_val_idx = None
        for idx, t in enumerate(tokens):
            if idx == 0:
                continue
            if VAL_RE.match(t):
                first_val_idx = idx
                break
        if first_val_idx is None:
            continue
        desc = ' '.join(tokens[:first_val_idx])
        values = tokens[first_val_idx:]
        if len(values) < 2:
            continue
        tol_neg = values[0]
        tol_pos = values[1]
        # ensure neg has '-' or pos has no '-'; otherwise leave as is
        if not tol_neg.startswith('-') and tol_pos.startswith('-'):
            tol_neg, tol_pos = tol_pos, tol_neg

        # Sizes: take last min(n_sizes, len(rest_after_tol)) tokens
        rest_after_tol = values[2:]
        # Skip optional "Regular" or non-value tokens at start
        while rest_after_tol and rest_after_tol[0] == "Regular":
            rest_after_tol = rest_after_tol[1:]
        # Sizes = trailing n_sizes (or fewer if row shorter)
        if len(rest_after_tol) > n_sizes:
            size_vals = rest_after_tol[-n_sizes:]
        else:
            size_vals = rest_after_tol
        if not size_vals:
            continue
        size_dict = {sizes[k]: size_vals[k] for k in range(min(len(size_vals), n_sizes)) if size_vals[k]}
        if not size_dict:
            continue

        pom = {
            "POM_Code": code,
            "POM_Name": desc[:200],
            "tolerance": {"neg": tol_neg, "pos": tol_pos},
            "sizes": size_dict,
        }
        poms.append(pom)

    if not poms:
        return {}
    return {"sizes": sizes, "poms": poms, "n_poms_on_page": len(poms), "_layout": "anf_horizontal"}


# ────────────────────────────────────────────────────────────────────────
# Test on 4 failing ANF PDFs
# ────────────────────────────────────────────────────────────────────────
SAMPLES = [
    ("312594", "tp_samples_v2/312594_S262460003"),
    ("312604", "tp_samples_v2/312604_S262460008"),
    ("312619", "tp_samples_v2/312619_S262460014"),
    ("312656", "tp_samples_v2/312656_S262130008"),
]

if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    total_poms = 0
    for eidh, rel in SAMPLES:
        d = root / rel
        if not d.exists():
            print(f"❌ {eidh}: folder not found")
            continue
        pdfs = list(d.glob("*.pdf"))
        if not pdfs:
            print(f"❌ {eidh}: no PDF")
            continue
        pdf_path = pdfs[0]
        eidh_poms = 0
        with pdfplumber.open(pdf_path) as pdf:
            # Check pages 7-10 (MC pages typically 8-9)
            for pg_idx in range(min(11, len(pdf.pages))):
                pg = pdf.pages[pg_idx]
                txt = pg.extract_text() or ''
                if "POMs" not in txt:
                    continue
                result = parse_anf_horizontal_textmode(txt)
                if result and result.get("poms"):
                    n_poms = len(result["poms"])
                    eidh_poms += n_poms
                    print(f"  ✅ {eidh} pg{pg_idx+1}: {n_poms} POMs (sizes={result['sizes']})")
                    # show first 2 POMs as sample
                    for pom in result["poms"][:2]:
                        print(f"      {pom['POM_Code']} | {pom['POM_Name'][:50]:<50} | tol={pom['tolerance']} | sizes={dict(list(pom['sizes'].items())[:3])}...")
                else:
                    print(f"  ❌ {eidh} pg{pg_idx+1}: POMs anchor found but parser returned empty")
        total_poms += eidh_poms
        print(f"  → {eidh} total: {eidh_poms} POMs\n")
    print(f"\n=== GRAND TOTAL: {total_poms} POMs from {len(SAMPLES)} ANF designs ===")
