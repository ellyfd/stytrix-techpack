"""
audit_v4.py — same as audit_3source_coverage.py but fresh filename to bypass sandbox stale mount.
跨 3 source 合併覆蓋率 + dev_sample exclusion + unrecoverable POM exclusion.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "extract"

DEV_SAMPLE_RE = re.compile(
    r"^("
    r"AIM[\w\-]{3,15}"
    r"|ONY[\w\-]+"
    r"|ON[_A-Z\d][\w\-]*"
    r"|BY[\w\-]+"
    r"|IPS[\w\-]*"
    r"|VDD[\w\-]*"
    r"|VLHY\d{2}\w+"
    r"|RR[A-Z]{3,8}\d{2}\w*"
    r"|FRP[A-Z]{3,8}\w*"
    r"|FRND[\w\-]+"
    r"|KNT[A-Z]{3,8}\w*"
    r"|^SPR\d{2}\w+"
    r"|FLX\d{2}[A-Z\d]+"
    r"|APT[\w\-]+"
    r"|CBRTW\d{2}[A-Z]+"
    r"|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*"
    r"|CALIA\d{2}\w*"
    r"|SON\d{2}\w+"
    r"|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*"
    r"|HY\d{2}[A-Z]+\w*"
    r"|WC\d?[A-Z\d]{4,8}"
    r"|MT\d?[A-Z\d]{4,8}"
    r"|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}"
    r"|WAX\d+\w*"
    r"|WCG\d+\w*"
    r")",
    re.IGNORECASE
)
GAP_DEV_RE = re.compile(
    r"(GAP\w+|GST\w+|GSM\w*|INNOV|^SP\d{2}GO\w*|^SS\d{2}GST\w*|^CM\d{2}\w+|^MK\d{4}\w*)",
    re.IGNORECASE
)
PDF_METADATA_ONLY_BRANDS = {"GU"}


def is_dev_sample(design_id):
    if not design_id: return False
    if DEV_SAMPLE_RE.match(design_id): return True
    if GAP_DEV_RE.search(design_id): return True
    return False


def is_pdf_metadata_only_brand(cl):
    return cl in PDF_METADATA_ONLY_BRANDS


def load_unrecoverable_pom_eidhs(path):
    if not path.exists(): return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = e.get("eidh")
            if eidh and e.get("_pom_unrecoverable"):
                out[str(eidh)] = e.get("_unrecoverable_reason", "unknown")
    return out


def load_jsonl(path):
    d = {}
    if not path.exists(): return d
    with open(path, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            eidh = e.get("eidh")
            if eidh: d[eidh] = e
    return d


pdf = load_jsonl(OUT_DIR / "pdf_facets.jsonl")
pptx = load_jsonl(OUT_DIR / "pptx_facets.jsonl")
xlsx = load_jsonl(OUT_DIR / "xlsx_facets.jsonl")
# Load all *_pom_unrecoverable.jsonl files into a single dict
unrecoverable_pom = {}
for p in sorted(OUT_DIR.glob("*_pom_unrecoverable.jsonl")):
    d = load_unrecoverable_pom_eidhs(p)
    unrecoverable_pom.update(d)
print("\n[loaded] PDF={:,} / PPTX={:,} / XLSX={:,} / unrec={:,} (from {} files)".format(
    len(pdf), len(pptx), len(xlsx), len(unrecoverable_pom),
    len(list(OUT_DIR.glob("*_pom_unrecoverable.jsonl")))))

all_eidhs = set(pdf.keys()) | set(pptx.keys()) | set(xlsx.keys())
stats = defaultdict(lambda: {
    "total": 0, "dev_sample": 0, "unrecoverable": 0,
    "meta_pdf": 0, "meta_xlsx": 0, "meta_any": 0,
    "pom_pdf": 0, "pom_xlsx": 0, "pom_any": 0, "total_poms": 0,
    "pom_real_any": 0,
    "construct_pdf": 0, "construct_pptx": 0, "construct_any": 0,
})
dev_sample_examples = defaultdict(list)

for eidh in all_eidhs:
    cl = None; design_id = None
    for src in (pdf, pptx, xlsx):
        e = src.get(eidh)
        if e and e.get("client_code"):
            cl = e["client_code"]
            if not design_id: design_id = e.get("design_id") or ""
            break
    if not cl: continue
    if not design_id:
        for src in (pdf, pptx, xlsx):
            e = src.get(eidh)
            if e and e.get("design_id"):
                design_id = e["design_id"]; break

    s = stats[cl]; s["total"] += 1
    is_dev = is_dev_sample(design_id)
    if is_dev:
        s["dev_sample"] += 1
        if len(dev_sample_examples[cl]) < 3:
            dev_sample_examples[cl].append(design_id)
    is_unrec = eidh in unrecoverable_pom and not is_dev
    if is_unrec: s["unrecoverable"] += 1
    pom_excluded = is_dev or is_pdf_metadata_only_brand(cl) or is_unrec

    pdf_e = pdf.get(eidh) or {}; xlsx_e = xlsx.get(eidh) or {}; pptx_e = pptx.get(eidh) or {}
    pdf_meta = {k:v for k,v in (pdf_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    xlsx_meta = {k:v for k,v in (xlsx_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    if pdf_meta: s["meta_pdf"] += 1
    if xlsx_meta: s["meta_xlsx"] += 1
    if pdf_meta or xlsx_meta: s["meta_any"] += 1

    pdf_mcs = pdf_e.get("measurement_charts") or []
    pdf_pom = sum(len(m.get("poms") or []) for m in pdf_mcs)
    xlsx_mcs = xlsx_e.get("measurement_charts") or []
    xlsx_pom = sum(len(m.get("poms") or []) for m in xlsx_mcs)
    if pdf_pom > 0: s["pom_pdf"] += 1
    if xlsx_pom > 0: s["pom_xlsx"] += 1
    if pdf_pom > 0 or xlsx_pom > 0:
        s["pom_any"] += 1
        if not pom_excluded: s["pom_real_any"] += 1
    s["total_poms"] += pdf_pom + xlsx_pom

    if pdf_e.get("construction_pages"): s["construct_pdf"] += 1
    if pptx_e.get("constructions"): s["construct_pptx"] += 1
    if pdf_e.get("construction_pages") or pptx_e.get("constructions"): s["construct_any"] += 1


def pct(n, t):
    return "{:>3.0f}%".format(n / max(t, 1) * 100)


print("\n=== 跨 3 source 合併覆蓋率 ===")
print("  ⚡ POM%(real) = 排除 dev sample + unrecoverable + PDF-meta-only brand\n")
print("  {:<8} {:>6} {:>5} {:>5}  {:>5} {:>17} {:>9}  {:>5}  {:<25}".format(
    "brand", "total", "dev", "unrec", "meta%", "POM%(real)", "POMs", "構造%", "flag"))
print("  " + "-"*100)

SMALL_BRANDS_CUTOFF = 150
EXCLUDED_SMALL = []
need_attention = []
sorted_brands = sorted(stats.keys(), key=lambda c: -stats[c]["total"])

for cl in sorted_brands:
    s = stats[cl]
    if s["total"] < SMALL_BRANDS_CUTOFF:
        EXCLUDED_SMALL.append((cl, s["total"]))
        continue
    if is_pdf_metadata_only_brand(cl):
        real_total = 0
    else:
        real_total = s["total"] - s["dev_sample"] - s["unrecoverable"]

    meta_p = s["meta_any"] / s["total"] * 100
    pom_p = (s["pom_real_any"] / max(real_total, 1) * 100) if real_total > 0 else 0
    con_p = s["construct_any"] / s["total"] * 100

    flags = []
    if meta_p < 80: flags.append("meta⚠")
    if real_total > 0 and pom_p < 80: flags.append("POM⚠")
    elif real_total == 0 and is_pdf_metadata_only_brand(cl): flags.append("PDF-meta-only")
    elif real_total == 0: flags.append("dev-only")
    if con_p < 80: flags.append("構造⚠")
    flag_str = " ".join(flags) if flags else "✅"

    if real_total > 0:
        pom_str = "{:>4.0f}% ({}/{})".format(pom_p, s["pom_real_any"], real_total)
    elif is_pdf_metadata_only_brand(cl):
        pom_str = "N/A (meta only)"
    else:
        pom_str = "N/A"

    print("  {:<8} {:>6} {:>5} {:>5}  {:>5} {:>17} {:>9,}  {:>5}  {:<25}".format(
        cl, s["total"], s["dev_sample"], s["unrecoverable"],
        pct(s["meta_any"], s["total"]), pom_str, s["total_poms"],
        pct(s["construct_any"], s["total"]), flag_str))

    if flags and cl != "TGT" and "dev-only" not in flags and "PDF-meta-only" not in flags:
        need_attention.append((cl, s, flags, meta_p, pom_p, con_p, real_total))


print("\n=== Summary ===")
total_eidh = sum(s["total"] for s in stats.values())
total_dev = sum(s["dev_sample"] for s in stats.values())
total_unrec = sum(s["unrecoverable"] for s in stats.values())
real_tp = total_eidh - total_dev - total_unrec
total_poms = sum(s["total_poms"] for s in stats.values())
print("  All EIDH:        {:,}".format(total_eidh))
print("  Dev sample:      {:,} ({:.1f}%)".format(total_dev, total_dev*100/max(total_eidh,1)))
print("  Unrecoverable:   {:,} ({:.1f}%)".format(total_unrec, total_unrec*100/max(total_eidh,1)))
print("  Real techpack:   {:,} ({:.1f}%)".format(real_tp, real_tp*100/max(total_eidh,1)))
print("  Total POMs:      {:,}".format(total_poms))
