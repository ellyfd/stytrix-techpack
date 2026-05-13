"""count_zero_fact_pdfs.py — 列 0-fact PDF designs（Vision fallback 候選清單）

讀：
  callout_manifest.jsonl  ← detect 階段判定有 callout 頁的 PDF design
  facts.jsonl             ← 已抽到的 facts

輸出：
  outputs/zero_fact_pdfs/_summary.csv  ← 各 client 的 0-fact 設計數
  outputs/zero_fact_pdfs/_designs.csv  ← 每個 0-fact design 的清單（含頁數）

用法：python scripts/count_zero_fact_pdfs.py
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback
MANIFEST = M7_ORG / "callout_manifest.jsonl" if (M7_ORG / "callout_manifest.jsonl").exists() else DL / "data" / "ingest" / "pdf" / "callout_manifest.jsonl"
FACTS = M7_ORG / "facts.jsonl" if (M7_ORG / "facts.jsonl").exists() else DL / "data" / "ingest" / "unified" / "facts.jsonl"
OUT = ROOT / "outputs" / "zero_fact_pdfs"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    # 1. 讀 manifest
    by_design = defaultdict(lambda: {"text_pages": [], "image_pages": [], "pdf": ""})
    for line in open(MANIFEST, encoding="utf-8"):
        e = json.loads(line)
        key = (e.get("client", ""), e.get("design_id", ""))
        page = e.get("page")
        ptype = e.get("type", "")
        if ptype == "text":
            by_design[key]["text_pages"].append(page)
        elif ptype == "image":
            by_design[key]["image_pages"].append(page)
        by_design[key]["pdf"] = e.get("pdf", "")

    print(f"[load] manifest: {len(by_design)} (client, design) pairs with callout pages")

    # 2. 讀 facts，記哪些 design 有 fact
    designs_with_facts = set()
    pdf_facts_by_design = defaultdict(int)
    pptx_facts_by_design = defaultdict(int)
    for line in open(FACTS, encoding="utf-8"):
        f = json.loads(line)
        key = (f.get("client", ""), f.get("design_id", ""))
        designs_with_facts.add(key)
        if f.get("source") == "pdf":
            pdf_facts_by_design[key] += 1
        elif f.get("source") == "pptx":
            pptx_facts_by_design[key] += 1

    # 3. 找 0 PDF fact 的 design
    zero_pdf_facts = []
    for key, info in by_design.items():
        client, design_id = key
        if pdf_facts_by_design[key] == 0:
            zero_pdf_facts.append({
                "client": client,
                "design_id": design_id,
                "pdf": info["pdf"],
                "text_pages": ",".join(map(str, sorted(info["text_pages"]))),
                "image_pages": ",".join(map(str, sorted(info["image_pages"]))),
                "n_text_pages": len(info["text_pages"]),
                "n_image_pages": len(info["image_pages"]),
                "pptx_facts": pptx_facts_by_design[key],
            })

    # 4. 寫 designs.csv
    designs_path = OUT / "_designs.csv"
    with open(designs_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["client", "design_id", "pdf",
                                           "n_text_pages", "n_image_pages",
                                           "text_pages", "image_pages", "pptx_facts"])
        w.writeheader()
        for r in sorted(zero_pdf_facts, key=lambda x: (x["client"], x["design_id"])):
            w.writerow(r)

    # 5. 寫 summary.csv
    by_client = defaultdict(lambda: {"n_zero_pdf": 0,
                                      "n_with_image_pages": 0,
                                      "n_with_text_pages": 0,
                                      "n_with_pptx_fact": 0})
    for r in zero_pdf_facts:
        c = r["client"]
        by_client[c]["n_zero_pdf"] += 1
        if r["n_image_pages"] > 0:
            by_client[c]["n_with_image_pages"] += 1
        if r["n_text_pages"] > 0:
            by_client[c]["n_with_text_pages"] += 1
        if r["pptx_facts"] > 0:
            by_client[c]["n_with_pptx_fact"] += 1

    summary_path = OUT / "_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["client", "n_zero_pdf_fact",
                    "n_with_image_pages_only",
                    "n_with_text_pages_but_0_extracted",
                    "n_with_pptx_fact_backup"])
        for c, st in sorted(by_client.items(), key=lambda x: -x[1]["n_zero_pdf"]):
            w.writerow([c, st["n_zero_pdf"], st["n_with_image_pages"],
                        st["n_with_text_pages"], st["n_with_pptx_fact"]])

    # 6. console summary
    print(f"\n=== 0-fact PDF designs ===")
    print(f"Total: {len(zero_pdf_facts)} designs (有 callout 頁但 0 PDF fact)")
    print()
    print(f"  {'client':25s} {'zero':>5s} {'img-only':>9s} {'text-miss':>10s} {'has-pptx':>9s}")
    print(f"  {'-'*25} {'-'*5} {'-'*9} {'-'*10} {'-'*9}")
    for c, st in sorted(by_client.items(), key=lambda x: -x[1]["n_zero_pdf"]):
        print(f"  {c:25s} {st['n_zero_pdf']:>5d} {st['n_with_image_pages']:>9d} "
              f"{st['n_with_text_pages']:>10d} {st['n_with_pptx_fact']:>9d}")

    print(f"\n[Vision fallback 候選]: 「img-only」那欄即必須走 Vision（text-layer 永遠抽不到）")
    print(f"\n[Reports]")
    print(f"  {summary_path}")
    print(f"  {designs_path}")


if __name__ == "__main__":
    main()
