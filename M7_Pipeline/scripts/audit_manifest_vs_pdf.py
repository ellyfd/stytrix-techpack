"""
Manifest vs PDF 一致性 audit
跑法: python scripts\audit_manifest_vs_pdf.py [--deep]

對齊規則:
  manifest 客戶  →  expected client_code (查 CLIENT_RAW_TO_CODE)
  PDF 內容 Customer/Brand → actual brand from PDF

策略:
  Pass 1 (快): 掃 pdf_facets.jsonl, 從已抽 metadata 找 brand_division != expected
  Pass 2 (--deep): 對可疑 EIDH 重讀 PDF page 1, grep "Customer:" 等 markers verify

輸出:
  outputs/extract/manifest_inconsistencies.csv
  含: EIDH, manifest客戶, PDF推測客戶, 證據, confidence
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"
TP_DIR = ROOT / "tp_samples_v2"
MANIFEST = ROOT / "m7_organized_v2" / "_fetch_manifest.csv"

# 從 extract_pdf_all.py 同步
CLIENT_RAW_TO_CODE = {
    "OLD NAVY": "ONY", "TARGET": "TGT", "GAP": "GAP", "GAP OUTLET": "GAP",
    "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS", "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA", "KOHLS": "KOH", "A AND F": "ANF", "A & F": "ANF",
    "GU": "GU", "BEYOND YOGA": "BY", "HIGH LIFE LLC": "HLF", "WAL-MART": "WMT",
    "WAL-MART-CA": "WMT", "QUINCE": "QCE", "HALARA": "HLA", "NET": "NET",
    "JOE FRESH": "JF", "BANANA REPUBLIC": "BR", "BRFS": "BR", "SANMAR": "SAN",
    "DISTANCE": "DST", "ZARA": "ZAR", "ASICS-EU": "ASICS", "LEVIS": "LEV",
    "CATO": "CATO", "SMART CLOTHING": "SMC", "ABERCROMBIE AND FITCH": "ANF",
}

# PDF 內容裡找客戶的 markers (用 regex 找 "Customer:\s*XXX" 或 brand 直接出現)
# (key=marker_text, value=client_code)
PDF_CUSTOMER_MARKERS = {
    # 強訊號 — Customer 或 Brand 欄位明寫
    "BANANA REPUBLIC": "BR",
    "BRFS": "BR",
    "OLD NAVY": "ONY",
    "ATHLETA": "ATH",
    "TARGET BRANDS": "TGT",
    "TARGET CORPORATION": "TGT",
    "TARGET(TSS)": "TGT",
    "TARGET(TSI)": "TGT",
    "GAP - BOYS": "GAP",
    "GAP - GIRLS": "GAP",
    "GAP - MENS": "GAP",
    "GAP - WOMENS": "GAP",
    "DICKS SPORTING": "DKS",
    "DSG ": "DKS",
    "VRST ": "DKS",
    "CALIA ": "DKS",
    "UNDER ARMOUR": "UA",
    "BEYOND YOGA": "BY",
    "ABERCROMBIE": "ANF",
    "HOLLISTER": "ANF",
    "GILLY HICKS": "ANF",
    "HIGH LIFE": "HLF",
    "JOE FRESH": "JF",
    "QUINCE": "QCE",
    "SANMAR": "SAN",
    "ZARA": "ZAR",
    "ASICS": "ASICS",
    "LEVIS": "LEV",
    "WAL-MART": "WMT",
    "WALMART": "WMT",
    # KOH 子品牌 markers (KOH 自己 brand 反而少, 子品牌多)
    "Sonoma Goods": "KOH",
    "Croft & Barrow": "KOH",
    "C&B RTW": "KOH",
    "TEK GEAR": "KOH",
    "FLX ": "KOH",
    "Apt. 9": "KOH",
    "Lauren Conrad": "KOH",
    "KOHL'S": "KOH",
    "KOHLS": "KOH",
    # TGT 子品牌
    "All in Motion": "TGT",
    "Cat & Jack": "TGT",
    "Goodfellow": "TGT",
    "Auden": "TGT",
    "A New Day": "TGT",
    "Wild Fable": "TGT",
    # GU 日文
    "デザイン管理表": "GU",
    "ユニクロ": "GU",
    "GU": "GU",
}


def load_manifest_lookup():
    """Load EIDH → 客戶 raw mapping"""
    lookup = {}
    if not MANIFEST.exists():
        print(f"[!] manifest 不存在: {MANIFEST}")
        return lookup
    with open(MANIFEST, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            eidh = (row.get("Eidh") or "").strip()
            if eidh:
                lookup[eidh] = (row.get("客戶") or "").strip()
    return lookup


def raw_to_code(client_raw: str) -> str:
    if not client_raw:
        return "UNKNOWN"
    return CLIENT_RAW_TO_CODE.get(client_raw.upper().strip(), client_raw.upper()[:6])


def detect_pdf_brand(text: str) -> tuple[str, str]:
    """從 PDF text 偵測客戶, return (client_code, evidence_marker)"""
    upper = text.upper()
    # Strong markers first
    for marker, code in PDF_CUSTOMER_MARKERS.items():
        if marker.upper() in upper:
            return code, marker
    return "UNKNOWN", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true",
                    help="對可疑 EIDH 重讀 PDF page 1 verify (慢, ~2-3 min)")
    args = ap.parse_args()

    print(f"=== Manifest vs PDF 一致性 audit ===\n")

    # === Step 1: load manifest ===
    manifest = load_manifest_lookup()
    print(f"[manifest] loaded {len(manifest):,} EIDH entries")

    # === Step 2: scan all pdf_facets jsonl, 看 metadata 是否揭露 brand 不對 ===
    pdf_facets_files = sorted(OUT_DIR.glob("pdf_facets_*.jsonl"))
    pdf_facets_files = [f for f in pdf_facets_files if f.name != "pdf_facets.jsonl"]

    # eidh → list of evidence
    inconsistencies = []
    eidh_to_pdf_data = {}  # cache

    for f in pdf_facets_files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                eidh = d.get("eidh")
                if not eidh:
                    continue
                manifest_raw = manifest.get(eidh, "")
                expected_code = raw_to_code(manifest_raw)
                actual_code = d.get("client_code", "")
                meta = d.get("metadata") or {}

                # 從 metadata 找直接證據 (brand_division / customer / subbrand)
                pdf_brand_div = (meta.get("brand_division") or "").upper()
                pdf_customer = (meta.get("customer") or "").upper()
                pdf_subbrand = (meta.get("subbrand") or "").upper()

                # Map metadata-derived brand back to client_code
                meta_evidence_code = "UNKNOWN"
                meta_evidence_text = ""
                for marker_text, code in PDF_CUSTOMER_MARKERS.items():
                    mu = marker_text.upper()
                    if mu in pdf_brand_div or mu in pdf_customer or mu in pdf_subbrand:
                        meta_evidence_code = code
                        meta_evidence_text = marker_text
                        break

                if meta_evidence_code != "UNKNOWN" and meta_evidence_code != expected_code:
                    inconsistencies.append({
                        "eidh": eidh,
                        "manifest_客戶": manifest_raw,
                        "manifest_code": expected_code,
                        "pdf_evidence_code": meta_evidence_code,
                        "pdf_evidence_text": meta_evidence_text,
                        "source_field": (
                            "brand_division" if meta_evidence_text.upper() in pdf_brand_div
                            else "customer" if meta_evidence_text.upper() in pdf_customer
                            else "subbrand"
                        ),
                        "design_id": d.get("design_id", ""),
                        "design_number": meta.get("design_number", ""),
                        "source_files": d.get("source_files") or [],
                    })

    print(f"\n[Pass 1: metadata-only check]")
    print(f"  scanned {sum(1 for _ in [])}+ entries")
    print(f"  found {len(inconsistencies)} inconsistencies\n")

    # === Step 3 (--deep): 重讀 PDF text 對可疑 EIDH verify ===
    if args.deep and inconsistencies:
        print(f"\n[Pass 2 --deep: re-reading PDFs to verify]")
        try:
            import fitz
        except ImportError:
            print("[!] pymupdf not installed, skip --deep")
            args.deep = False
        else:
            verified_inconsistencies = []
            for entry in inconsistencies:
                eidh = entry["eidh"]
                folders = list(TP_DIR.glob(f"{eidh}_*"))
                if not folders:
                    continue
                pdfs = list(folders[0].rglob("*.pdf"))
                if not pdfs:
                    continue
                pdf = pdfs[0]
                try:
                    doc = fitz.open(str(pdf))
                    text = ""
                    for i in range(min(2, doc.page_count)):
                        text += doc[i].get_text()
                    pdf_code, pdf_marker = detect_pdf_brand(text)
                    if pdf_code == entry["pdf_evidence_code"]:
                        entry["pdf_text_verified"] = "yes"
                        verified_inconsistencies.append(entry)
                except Exception:
                    continue
            inconsistencies = verified_inconsistencies
            print(f"  verified {len(inconsistencies)} inconsistencies via PDF text")

    # === Step 4: print + write CSV ===
    if not inconsistencies:
        print("\n✅ 無 manifest inconsistency — manifest 跟 PDF 內容對齊")
        return

    print(f"\n=== {len(inconsistencies)} 個 EIDH manifest 客戶 ≠ PDF 內容 ===")
    print(f"  {'EIDH':<8} {'manifest':<12} {'PDF 證據':<12} {'欄位':<14} {'證據詞':<25}")
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*14} {'-'*25}")
    for e in inconsistencies[:30]:
        print(f"  {e['eidh']:<8} {e['manifest_code']:<12} {e['pdf_evidence_code']:<12} "
              f"{e['source_field']:<14} {e['pdf_evidence_text'][:25]}")
    if len(inconsistencies) > 30:
        print(f"  ... and {len(inconsistencies) - 30} more")

    # By manifest code → pdf code 統計
    print(f"\n=== 不一致 patterns (manifest → PDF, top 10) ===")
    pattern_count = Counter()
    for e in inconsistencies:
        pattern_count[(e["manifest_code"], e["pdf_evidence_code"])] += 1
    for (m_code, p_code), n in pattern_count.most_common(10):
        print(f"  {m_code:<10} → {p_code:<10}  {n} 件")

    # Write CSV
    csv_path = OUT_DIR / "manifest_inconsistencies.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "eidh", "manifest_客戶", "manifest_code", "pdf_evidence_code",
            "pdf_evidence_text", "source_field", "design_id",
            "design_number", "source_files", "pdf_text_verified",
        ], extrasaction="ignore")
        writer.writeheader()
        for e in inconsistencies:
            e["source_files"] = " | ".join(e.get("source_files", []))
            writer.writerow(e)
    print(f"\n[output] {csv_path}")
    print(f"  {len(inconsistencies)} rows written")


if __name__ == "__main__":
    main()
