"""
把中央 pdf_facets.jsonl 拆成 per-brand 獨立檔
跑法: python scripts\split_pdf_facets.py

會做:
  outputs/extract/pdf_facets.jsonl
    → outputs/extract/pdf_facets_GU.jsonl
    → outputs/extract/pdf_facets_GAP.jsonl
    → outputs/extract/pdf_facets_DKS.jsonl
    → outputs/extract/pdf_facets_<其他 brand>.jsonl

中央檔 (pdf_facets.jsonl) 保留不動, 之後可以用 merge_pdf_facets.py 重建.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / "extract" / "pdf_facets.jsonl"
OUT_DIR = ROOT / "outputs" / "extract"


def main():
    if not SRC.exists():
        print(f"[!] {SRC} 不存在")
        return 1
    print(f"[reading] {SRC} ({SRC.stat().st_size//1024//1024} MB)")

    by_client = defaultdict(list)
    n_lines = 0
    n_no_client = 0

    with open(SRC, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            n_lines += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            cl = d.get("client_code") or "UNKNOWN"
            if cl == "UNKNOWN":
                n_no_client += 1
            by_client[cl].append(line)

    print(f"[parsed] {n_lines:,} lines, {len(by_client)} client codes")
    if n_no_client:
        print(f"  [!] {n_no_client} entries 沒 client_code → 寫到 pdf_facets_UNKNOWN.jsonl")

    print("\n[writing per-brand files]")
    for cl, lines in sorted(by_client.items(), key=lambda x: -len(x[1])):
        out = OUT_DIR / f"pdf_facets_{cl}.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"  {cl:<10} {len(lines):>5} entries → {out.name}")

    print(f"\n[done] split {n_lines:,} entries → {len(by_client)} files")
    print(f"  中央檔 {SRC.name} 保留不動")
    print(f"  之後跑單一 brand: python scripts\\extract_pdf_all.py --client <BRAND>")
    print(f"     → 會寫到 pdf_facets_<BRAND>.jsonl (覆蓋舊版)")
    print(f"  最後合併: python scripts\\merge_pdf_facets.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
