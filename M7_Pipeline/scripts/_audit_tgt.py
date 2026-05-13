"""Audit TGT PDF: 看 page_classifier 對 TGT page 判什麼 type."""
import sys, csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from page_classifier import classify_page
import client_parsers

ROOT = SCRIPT_DIR.parent
TP_DIR = ROOT / "tp_samples_v2"
MANIFEST = ROOT / "m7_organized_v2" / "_fetch_manifest.csv"

# Load manifest → 找 TGT EIDH
tgt_eidhs = []
with open(MANIFEST, encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if (row.get("客戶") or "").upper() == "TARGET":
            tgt_eidhs.append(row["Eidh"])
            if len(tgt_eidhs) >= 3:
                break

import fitz
for eidh in tgt_eidhs:
    for folder in TP_DIR.iterdir():
        if not folder.name.startswith(eidh + "_"):
            continue
        pdfs = list(folder.glob("*.pdf"))
        if not pdfs:
            print(f"\nEIDH {eidh}: no PDF")
            break
        pdf = pdfs[0]
        print(f"\n{'='*60}\nEIDH {eidh}: {pdf.name[:50]}")
        doc = fitz.open(str(pdf))
        for i in range(min(3, doc.page_count)):  # 看前 3 頁
            page = doc[i]
            ptype, evidence = classify_page(page, "TGT")
            text = page.get_text()
            print(f"  page {i+1}: type={ptype}  reason={evidence.get('reason')}")
            if ptype == "cover":
                # 試 parse
                parser = client_parsers.get_parser("TGT")
                meta = parser.parse_cover(page, text)
                print(f"    parse_cover → {list(meta.keys())[:8]}")
            elif ptype == "callout":
                print(f"    score={evidence.get('score')}, n_images={evidence.get('n_images')}")
        doc.close()
        break
