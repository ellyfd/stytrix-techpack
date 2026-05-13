"""inspect_text_miss.py — 看 A&F (或任何 client) text-miss design 的 PDF text-layer raw 內容

用：python scripts/inspect_text_miss.py [--client A_&_F] [--limit 2]

跑完印出該 client 的 text-miss design 的 PDF page 文字，看為何 parser 抓不到。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
DESIGNS_CSV = ROOT / "outputs" / "zero_fact_pdfs" / "_designs.csv"
PDF_DIR = ROOT / "m7_organized_v2" / "pdf_tp"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client", default="A_&_F")
    p.add_argument("--limit", type=int, default=2)
    p.add_argument("--max-spans", type=int, default=30, help="每頁印多少 span")
    args = p.parse_args()

    rows = []
    with open(DESIGNS_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["client"] == args.client and int(r["n_text_pages"]) > 0:
                rows.append(r)
    print(f"[load] {args.client} text-miss designs: {len(rows)}")

    for i, r in enumerate(rows[:args.limit]):
        pdf_name = r["pdf"]
        pdf_path = PDF_DIR / pdf_name
        text_pages = [int(x) for x in r["text_pages"].split(",") if x]
        print(f"\n{'='*70}")
        print(f"[{i+1}] {r['client']} / {r['design_id']} / {pdf_name}")
        print(f"  text pages: {text_pages}, image pages: {r['image_pages']}")
        if not pdf_path.exists():
            print(f"  [!] PDF not found: {pdf_path}")
            continue

        doc = fitz.open(str(pdf_path))
        for pg in text_pages[:2]:  # 看前 2 個 text page
            if pg > doc.page_count:
                continue
            print(f"\n  --- page {pg} ---")
            page = doc[pg - 1]
            spans = []
            for b in page.get_text("dict").get("blocks", []):
                if b.get("type") != 0:
                    continue
                for ln in b.get("lines", []):
                    for sp in ln.get("spans", []):
                        t = sp["text"].strip()
                        if t and len(t) >= 3:
                            spans.append((sp.get("font", ""), t[:200]))
            print(f"  total spans: {len(spans)}")
            for font, t in spans[:args.max_spans]:
                print(f"    [{font[:25]}] {t}")
            if len(spans) > args.max_spans:
                print(f"    ... +{len(spans) - args.max_spans} more")
        doc.close()


if __name__ == "__main__":
    main()
