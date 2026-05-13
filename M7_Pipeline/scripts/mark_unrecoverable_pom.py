"""mark_unrecoverable_pom.py — 產出 ONY 無法救回 POM 的 EIDH list.

Categories:
  - co_unresolvable_archived  : 有 CO marker 但 ref_D 不在我們 PDF 資料 (前季 archive 在 m7 端)
  - no_co_marker_no_source    : 沒 CO marker, PPTX 只有 labels 沒有 values
  - no_pptx_text              : 連 PPTX raw_text 都沒有
  - scan_pdf                  : PDF 是 scan 圖, OCR 抽不到 text (隱含於 no_co_marker)

輸出: outputs/extract/ony_pom_unrecoverable.jsonl
audit_3source_coverage.py 讀此 list 後從 POM% 分母排除.

用法:
  python3 scripts/mark_unrecoverable_pom.py [--brand ONY]
"""
import argparse, json, re, sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
PPTX_FACETS = EXTRACT_DIR / "pptx_facets.jsonl"

# CO markers (synced with co_resolver_v3.py — strong-anchor only)
CO_STRONG_ANCHOR_RE = re.compile(
    r"(?:尺寸表\s*參考"
    r"|參考\s*前季"
    r"|參考\s*大貨"
    r"|(?:Missy|Plus|Petite|Tall|Maternity|Kids|Baby|Toddler|Youth|Mens?|Womens?)?\s*跳檔[^\n]{0,12}?參考"
    r"|跳檔[^\n]{0,12}?參考"
    r")", re.IGNORECASE)
CO_BOM_REF_RE = re.compile(r"參考[^\n]{0,10}?(D\d{2,5}_BOM\d{4,8})", re.IGNORECASE)
CO_DCODE_RE = re.compile(r"(D\d{2,5})\b", re.IGNORECASE)
POM_HDR_RE = re.compile(r"Measurement Chart Review", re.I)
PROD_RE = re.compile(r"Centric 8\s*\|?\s*Production", re.I)


def extract_co_ref_d(txt):
    m = CO_STRONG_ANCHOR_RE.search(txt)
    if m:
        end = min(len(txt), m.end() + 80)
        window = txt[m.start():end]
        nl = window.find("\n\n")
        if nl > 0:
            window = window[:nl]
        d = CO_DCODE_RE.search(window)
        if d:
            return d.group(1).upper()
    m = CO_BOM_REF_RE.search(txt)
    if m:
        d_only = re.match(r"(D\d{2,5})", m.group(1), re.IGNORECASE)
        if d_only:
            return d_only.group(1).upper()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", nargs="*", default=["ONY"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    target_brands = set(b.upper() for b in args.brand)
    # Default filename derives from brand list (e.g. ony, gap, ony_gap_dks)
    if args.out:
        out_path = Path(args.out)
    else:
        suffix = "_".join(sorted(b.lower() for b in target_brands))
        out_path = EXTRACT_DIR / f"{suffix}_pom_unrecoverable.jsonl"

    print(f"=== Mark Unrecoverable POM ===")
    print(f"  Target brands: {sorted(target_brands)}")
    print(f"  Output:        {out_path}")
    print()

    # Build D-code with POM index
    pdf_with_poms = set()
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms == 0: continue
            sid = (e.get("design_id") or "").strip()
            mm = re.match(r"(D\d{2,5})", sid)
            if mm: pdf_with_poms.add(mm.group(1))
    print(f"  PDF POM index: {len(pdf_with_poms):,} D-codes with POM data")

    # Candidates: zero-POM D-prefix designs in target brands
    # but EXCLUDE those rescuable by Bucket A parser (Centric 8 Production layout)
    candidates = {}
    bucket_a_eidhs = set()
    with open(PDF_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("client_code") not in target_brands: continue
            sid = (e.get("design_id") or "").strip()
            if not sid.startswith("D"): continue
            poms = sum(len(m.get("poms") or []) for m in (e.get("measurement_charts") or []))
            if poms > 0: continue
            # Check if it's Bucket A (rescuable via new parser)
            all_text = ""
            for cp in e.get("construction_pages") or []:
                for ci in cp.get("construction_items") or []:
                    all_text += ci.get("_raw_callout_text") or ""
            eidh = str(e.get("eidh"))
            if POM_HDR_RE.search(all_text) and PROD_RE.search(all_text):
                bucket_a_eidhs.add(eidh)
                continue  # not unrecoverable; new parser will pick it up
            candidates[eidh] = {
                "eidh": eidh, "design_id": sid, "client": e.get("client_code"),
                "client_raw": e.get("client_raw"),
            }
    print(f"  Bucket A (rescuable via parser): {len(bucket_a_eidhs):,}")
    print(f"  Bucket B candidates:             {len(candidates):,}")

    # Join PPTX text
    pptx_text_paths = {}
    with open(PPTX_FACETS, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = str(e.get("eidh", ""))
            if eidh not in candidates: continue
            rtf = e.get("raw_text_file")
            if rtf and Path(rtf).exists():
                pptx_text_paths[eidh] = rtf

    # Classify
    categories = Counter()
    out_entries = []
    for eidh, c in candidates.items():
        path = pptx_text_paths.get(eidh)
        if not path:
            cat = "no_pptx_text"
            ref_d = None
        else:
            try: txt = open(path, encoding="utf-8").read()
            except:
                cat = "no_pptx_text"; ref_d = None
            else:
                ref_d = extract_co_ref_d(txt)
                if ref_d is None:
                    cat = "no_co_marker_no_source"
                elif ref_d in pdf_with_poms:
                    # Resolvable via co_resolver_v3 — skip (not unrecoverable)
                    continue
                else:
                    cat = "co_unresolvable_archived"
        categories[cat] += 1
        out_entries.append({
            "eidh": eidh,
            "design_id": c["design_id"],
            "client_code": c["client"],
            "client_raw": c["client_raw"],
            "_pom_unrecoverable": True,
            "_unrecoverable_reason": cat,
            "_ref_d_missing": ref_d if cat == "co_unresolvable_archived" else None,
        })

    print()
    print(f"=== Categories ===")
    for cat, n in categories.most_common():
        print(f"  {cat:<32} {n:>5,}")
    print(f"  {'TOTAL':<32} {sum(categories.values()):>5,}")

    # Write
    with open(out_path, "w", encoding="utf-8") as fout:
        for entry in out_entries:
            fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print()
    print(f"  [write] {len(out_entries):,} entries → {out_path}")
    print()
    print(f"=== Next step ===")
    print(f"  audit_3source_coverage.py 讀此 list, 從 ONY POM% 分母排除")
    print(f"  邏輯: 跟 dev-sample 排除一樣，但 reason 是 '無資料源' 而非 '開發樣本'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
