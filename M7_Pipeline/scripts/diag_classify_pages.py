"""
診斷: 指定 EIDH 看每頁 classify_page() 跟 parse_cover() 結果
跑法: python scripts\diag_classify_pages.py 306980 306986 306994 306997 312222

對每個 EIDH:
  - 列出該 EIDH 資料夾的 PDF 檔
  - 對每個 PDF 的每頁: print classify_page 結果 + first 200 chars
  - 對被判 cover 的頁 + 嘗試 parse_cover, 看抽到什麼
這樣可以快速看出 page_classifier 為什麼漏掉, 或 parse_cover regex 為什麼沒 match
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TP = ROOT / "tp_samples_v2"
sys.path.insert(0, str(ROOT / "scripts"))

import fitz
from page_classifier import classify_page, COVER_KW, BOM_TABLE_KW
from client_parsers import get_parser


def diag(eidh: str):
    # Find folder
    folders = list(TP.glob(f"{eidh}_*"))
    if not folders:
        folders = list(TP.glob(f"{eidh}*"))
    if not folders:
        print(f"\n[!] EIDH {eidh} 找不到資料夾")
        return
    folder = folders[0]
    print(f"\n{'='*70}")
    print(f"=== EIDH {eidh}  → {folder.name}")
    print(f"{'='*70}")

    pdfs = sorted(folder.rglob("*.pdf"))
    if not pdfs:
        print("  no PDF in folder")
        return
    print(f"  {len(pdfs)} PDF(s)")

    for pdf in pdfs:
        print(f"\n  --- {pdf.name} ({pdf.stat().st_size//1024} KB) ---")
        try:
            doc = fitz.open(str(pdf))
        except Exception as e:
            print(f"  open failed: {e}")
            continue

        for i in range(min(doc.page_count, 6)):  # 只看前 6 頁
            page = doc[i]
            text = page.get_text()
            upper = text.upper()

            ptype, evidence = classify_page(page, client_code="ANF")
            cover_hits = [kw for kw in COVER_KW if kw in upper]
            bom_hits = [kw for kw in BOM_TABLE_KW if kw in upper]

            print(f"\n    page {i+1}: classified='{ptype}' | reason={evidence.get('reason')}")
            print(f"      cover_kw_hits ({len(cover_hits)}): {cover_hits[:6]}")
            print(f"      bom_kw_hits ({len(bom_hits)}): {bom_hits[:5]}")
            print(f"      text preview (first 250 chars):")
            preview = text[:250].replace("\n", " | ")
            print(f"        {preview}")

            # 試 parse_cover
            try:
                parser = get_parser("ANF")
                meta = parser.parse_cover(page, text)
                if meta:
                    print(f"      ✅ parse_cover → {list(meta.keys())}")
                else:
                    print(f"      ❌ parse_cover → {{}} (空)")
            except Exception as e:
                print(f"      parse_cover error: {e}")


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python scripts\\diag_classify_pages.py EIDH [EIDH ...]")
        return 1
    for eidh in args:
        diag(eidh)


if __name__ == "__main__":
    sys.exit(main())
