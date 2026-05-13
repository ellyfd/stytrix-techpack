"""
Verify Quotation page 分類 + parser
跑法: python scripts\_verify_quotation.py
"""
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 強制清 cache
for cache_dir in (ROOT / "scripts").rglob("__pycache__"):
    shutil.rmtree(cache_dir, ignore_errors=True)

import fitz
from page_classifier import classify_page, COVER_KW
from client_parsers import get_parser

TP = ROOT / "tp_samples_v2"

for eidh in ["310137", "310267", "310179"]:
    folders = list(TP.glob(f"{eidh}_*"))
    if not folders:
        continue
    pdf = list(folders[0].rglob("*.pdf"))[0]
    print(f"\n{'='*60}")
    print(f"=== EIDH {eidh}: {pdf.name}")
    print(f"{'='*60}")

    doc = fitz.open(str(pdf))
    page = doc[0]
    text = page.get_text()
    upper = text.upper()

    # 看哪些 COVER_KW 命中
    cover_hits = [kw for kw in COVER_KW if kw in upper]
    print(f"\ncover_kw 命中 ({len(cover_hits)}): {cover_hits}")

    # classify_page
    ptype, evidence = classify_page(page, client_code="TGT")
    print(f"\nclassify_page: type={ptype}")
    print(f"  evidence: {evidence}")

    # parse_cover
    parser = get_parser("TGT")
    result = parser.parse_cover(page, text)
    print(f"\nparse_cover result: {result}")
