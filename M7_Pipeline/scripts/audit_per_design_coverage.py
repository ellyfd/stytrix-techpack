"""
Per-design 三維最大覆蓋 audit
跑法: python scripts\\audit_per_design_coverage.py [BRAND]

對每個 EIDH 跨 PDF/PPTX/XLSX 三 source 取 union，看每個 design 三維 (META/CONST/POM)
是否被 cover。Score 0-3 表示一個 design 有幾個維度被 cover。

這個 audit 跟 audit_3source_coverage.py 不同：
  audit_3source_coverage  → per-brand per-source coverage% (看 source 個別表現)
  audit_per_design_coverage → per-design union coverage (看實際 design 缺什麼)

實際使用：對「設計師丟一個 EIDH 進來，平台拿到多少資料」最直接。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "extract"


def load_jsonl(path):
    d = {}
    if not path.exists():
        return d
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            eidh = e.get("eidh")
            if eidh:
                d[eidh] = e
    return d


def has_real_meta(entry):
    if not entry:
        return False
    meta = entry.get("metadata") or {}
    return any(v for k, v in meta.items() if not k.startswith("_") and v)


def has_construction_pdf(entry):
    if not entry:
        return False
    return bool(entry.get("construction_pages"))


def has_construction_pptx(entry):
    if not entry:
        return False
    return bool(entry.get("constructions"))


def has_pom(entry):
    if not entry:
        return False
    mcs = entry.get("measurement_charts") or []
    return any(len(m.get("poms") or []) > 0 for m in mcs)


def has_construction_iso_xlsx(entry):
    if not entry:
        return False
    return bool(entry.get("construction_iso_map"))


# Load all 3 sources
pdf = load_jsonl(OUT_DIR / "pdf_facets.jsonl")
pptx = load_jsonl(OUT_DIR / "pptx_facets.jsonl")
xlsx = load_jsonl(OUT_DIR / "xlsx_facets.jsonl")

print("\n[loaded] PDF={:,} / PPTX={:,} / XLSX={:,}".format(len(pdf), len(pptx), len(xlsx)))

all_eidhs = set(pdf.keys()) | set(pptx.keys()) | set(xlsx.keys())

# Optional brand filter via CLI
target_brand = sys.argv[1].upper() if len(sys.argv) > 1 else None
if target_brand:
    print("[filter] brand = {}\n".format(target_brand))


# Per-design coverage
# brand_stats[cl] = list of (eidh, design_id, meta_src, const_src, pom_src, score)
brand_stats = defaultdict(list)

for eidh in all_eidhs:
    cl = None
    design_id = None
    for src in (pdf, pptx, xlsx):
        e = src.get(eidh)
        if e and e.get("client_code"):
            cl = e["client_code"]
            if not design_id:
                design_id = e.get("design_id") or ""
            break
    if not cl:
        continue
    if target_brand and cl != target_brand:
        continue

    if not design_id:
        for src in (pdf, pptx, xlsx):
            e = src.get(eidh)
            if e and e.get("design_id"):
                design_id = e["design_id"]
                break

    pdf_e = pdf.get(eidh)
    pptx_e = pptx.get(eidh)
    xlsx_e = xlsx.get(eidh)

    # META: any source has metadata
    meta_pdf = has_real_meta(pdf_e)
    meta_pptx = has_real_meta(pptx_e)
    meta_xlsx = has_real_meta(xlsx_e)
    meta_src = []
    if meta_pdf: meta_src.append("PDF")
    if meta_pptx: meta_src.append("PPTX")
    if meta_xlsx: meta_src.append("XLSX")
    meta_any = bool(meta_src)

    # CONST: any source has construction
    const_pdf = has_construction_pdf(pdf_e)
    const_pptx = has_construction_pptx(pptx_e)
    const_xlsx_iso = has_construction_iso_xlsx(xlsx_e)  # XLSX has construction_iso_map
    const_src = []
    if const_pdf: const_src.append("PDF")
    if const_pptx: const_src.append("PPTX")
    if const_xlsx_iso: const_src.append("XLSX")
    const_any = bool(const_src)

    # POM: any source has POM (PDF or XLSX)
    pom_pdf = has_pom(pdf_e)
    pom_xlsx = has_pom(xlsx_e)
    pom_pptx = has_pom(pptx_e)  # PPTX usually doesn't have POM but check
    pom_src = []
    if pom_pdf: pom_src.append("PDF")
    if pom_xlsx: pom_src.append("XLSX")
    if pom_pptx: pom_src.append("PPTX")
    pom_any = bool(pom_src)

    score = sum([meta_any, const_any, pom_any])
    brand_stats[cl].append((eidh, design_id, meta_src, const_src, pom_src, score))


# ════════════════════════════════════════════════════════════
# Print per-brand score distribution
# ════════════════════════════════════════════════════════════
print("\n=== Per-design 三維覆蓋分布 (一個 design 有幾個維度被 cover) ===\n")
print("  {:<8} {:>6}  {:>10} {:>10} {:>10} {:>10}".format(
    "brand", "total", "score3 (✅)", "score2", "score1", "score0 (空)"))
print("  {} {}  {} {} {} {}".format("-"*8, "-"*6, "-"*10, "-"*10, "-"*10, "-"*10))

sorted_brands = sorted(brand_stats.keys(), key=lambda c: -len(brand_stats[c]))
for cl in sorted_brands:
    designs = brand_stats[cl]
    total = len(designs)
    if total < 50:
        continue
    s3 = sum(1 for d in designs if d[5] == 3)
    s2 = sum(1 for d in designs if d[5] == 2)
    s1 = sum(1 for d in designs if d[5] == 1)
    s0 = sum(1 for d in designs if d[5] == 0)

    def pct(n):
        return "{} ({}%)".format(n, n * 100 // max(total, 1))

    print("  {:<8} {:>6}  {:>10} {:>10} {:>10} {:>10}".format(
        cl, total, pct(s3), pct(s2), pct(s1), pct(s0)))


# ════════════════════════════════════════════════════════════
# Print per-brand source contribution per dimension
# ════════════════════════════════════════════════════════════
print("\n=== Per-brand Source contribution (哪個 source 貢獻哪個維度) ===\n")
print("  {:<8} {:>6}  {:<25} {:<25} {:<20}".format(
    "brand", "total", "META 來源(union%)", "CONST 來源(union%)", "POM 來源(union%)"))
print("  {} {}  {} {} {}".format("-"*8, "-"*6, "-"*25, "-"*25, "-"*20))

for cl in sorted_brands:
    designs = brand_stats[cl]
    total = len(designs)
    if total < 50:
        continue
    # Count source contributions
    meta_pdf = sum(1 for d in designs if "PDF" in d[2])
    meta_pptx = sum(1 for d in designs if "PPTX" in d[2])
    meta_xlsx = sum(1 for d in designs if "XLSX" in d[2])
    meta_union = sum(1 for d in designs if d[2])
    const_pdf = sum(1 for d in designs if "PDF" in d[3])
    const_pptx = sum(1 for d in designs if "PPTX" in d[3])
    const_xlsx = sum(1 for d in designs if "XLSX" in d[3])
    const_union = sum(1 for d in designs if d[3])
    pom_pdf = sum(1 for d in designs if "PDF" in d[4])
    pom_xlsx = sum(1 for d in designs if "XLSX" in d[4])
    pom_pptx = sum(1 for d in designs if "PPTX" in d[4])
    pom_union = sum(1 for d in designs if d[4])

    def fmt(pdf_n, pptx_n, xlsx_n, union_n):
        parts = []
        if pdf_n: parts.append("P:{}".format(pdf_n))
        if pptx_n: parts.append("PT:{}".format(pptx_n))
        if xlsx_n: parts.append("X:{}".format(xlsx_n))
        return "{} ({}%)".format(",".join(parts) if parts else "-", union_n * 100 // max(total, 1))

    print("  {:<8} {:>6}  {:<25} {:<25} {:<20}".format(
        cl, total,
        fmt(meta_pdf, meta_pptx, meta_xlsx, meta_union),
        fmt(const_pdf, const_pptx, const_xlsx, const_union),
        fmt(pom_pdf, 0, pom_xlsx, pom_union)))


# ════════════════════════════════════════════════════════════
# 單一來源 critical analysis: 如果拿掉某 source, 多少 design 變空
# ════════════════════════════════════════════════════════════
print("\n=== Single-source critical (拿掉某 source 會掉多少 design 三維 cover) ===\n")
print("  {:<8} {:>6}  {:>15} {:>15} {:>15}".format(
    "brand", "total", "PDF only-meta", "PPTX only-const", "XLSX only-pom"))
print("  {} {}  {} {} {}".format("-"*8, "-"*6, "-"*15, "-"*15, "-"*15))

for cl in sorted_brands:
    designs = brand_stats[cl]
    total = len(designs)
    if total < 50:
        continue
    # PDF only-meta: 該 design 只有 PDF 提供 META, 拿掉 PDF 就 0 META
    pdf_only_meta = sum(1 for d in designs if d[2] == ["PDF"])
    pptx_only_const = sum(1 for d in designs if d[3] == ["PPTX"])
    xlsx_only_pom = sum(1 for d in designs if d[4] == ["XLSX"])
    print("  {:<8} {:>6}  {:>15} {:>15} {:>15}".format(
        cl, total, pdf_only_meta, pptx_only_const, xlsx_only_pom))


# ════════════════════════════════════════════════════════════
# Optional: TGT-specific sample 5 designs detail
# ════════════════════════════════════════════════════════════
if target_brand and len(brand_stats.get(target_brand, [])) > 0:
    print("\n=== Sample 10 {} designs detail (eidh / design_id / score / sources) ===\n".format(target_brand))
    designs = brand_stats[target_brand]
    # Sort: highest score first to see good ones, then lowest
    by_score = sorted(designs, key=lambda d: -d[5])
    print("  Top score (3 dimensions covered):")
    for eidh, did, ms, cs, ps, sc in by_score[:5]:
        ms_str = "+".join(ms) if ms else "-"
        cs_str = "+".join(cs) if cs else "-"
        ps_str = "+".join(ps) if ps else "-"
        print("    {} {:<22} score={} META={:<10} CONST={:<10} POM={}".format(
            eidh, did[:22], sc, ms_str, cs_str, ps_str))
    print("\n  Bottom score (0 dimensions):")
    zero_score = [d for d in designs if d[5] == 0]
    print("    Total {} designs with score=0".format(len(zero_score)))
    for eidh, did, ms, cs, ps, sc in zero_score[:5]:
        print("    {} {:<22} score=0 (totally empty)".format(eidh, did[:22]))


# ════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════
print("\n=== Summary ===")
total_designs = sum(len(brand_stats[cl]) for cl in brand_stats)
total_s3 = sum(1 for cl in brand_stats for d in brand_stats[cl] if d[5] == 3)
total_s2 = sum(1 for cl in brand_stats for d in brand_stats[cl] if d[5] == 2)
total_s1 = sum(1 for cl in brand_stats for d in brand_stats[cl] if d[5] == 1)
total_s0 = sum(1 for cl in brand_stats for d in brand_stats[cl] if d[5] == 0)
print("  Total designs (filtered): {:,}".format(total_designs))
print("  Score 3 (META+CONST+POM): {:,} ({:.1f}%)".format(
    total_s3, total_s3 * 100 / max(total_designs, 1)))
print("  Score 2:                  {:,} ({:.1f}%)".format(
    total_s2, total_s2 * 100 / max(total_designs, 1)))
print("  Score 1:                  {:,} ({:.1f}%)".format(
    total_s1, total_s1 * 100 / max(total_designs, 1)))
print("  Score 0 (empty):          {:,} ({:.1f}%)".format(
    total_s0, total_s0 * 100 / max(total_designs, 1)))
