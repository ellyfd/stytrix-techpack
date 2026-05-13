"""audit_v5.py — multi-brand unrecoverable loading + slim output."""
import json, re
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "extract"

DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*)", re.IGNORECASE)
GAP_DEV_RE = re.compile(
    r"(GAP\w+|GST\w+|GSM\w*|INNOV|^SP\d{2}GO\w*|^SS\d{2}GST\w*|^CM\d{2}\w+|^MK\d{4}\w*)",
    re.IGNORECASE)
PDF_METADATA_ONLY = {"GU"}


def is_dev(sid):
    if not sid: return False
    return bool(DEV_RE.match(sid) or GAP_DEV_RE.search(sid))


def load_jsonl(path):
    d = {}
    if not path.exists(): return d
    with open(path, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("eidh"): d[e["eidh"]] = e
    return d


def load_unrec(path):
    out = {}
    if not path.exists(): return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("eidh") and e.get("_pom_unrecoverable"):
                out[str(e["eidh"])] = e.get("_unrecoverable_reason", "?")
    return out


pdf = load_jsonl(OUT_DIR / "pdf_facets.jsonl")
pptx = load_jsonl(OUT_DIR / "pptx_facets.jsonl")
xlsx = load_jsonl(OUT_DIR / "xlsx_facets.jsonl")

unrec = {}
unrec_files = sorted(OUT_DIR.glob("*_pom_unrecoverable.jsonl"))
for p in unrec_files:
    unrec.update(load_unrec(p))

print(f"\n[loaded] PDF={len(pdf):,} / PPTX={len(pptx):,} / XLSX={len(xlsx):,} / unrec={len(unrec):,} from {len(unrec_files)} files:")
for p in unrec_files:
    print(f"  - {p.name}")

all_eidhs = set(pdf.keys()) | set(pptx.keys()) | set(xlsx.keys())
stats = defaultdict(lambda: {"total":0,"dev":0,"unrec":0,"meta":0,"pom_any":0,"pom_real":0,"poms":0,"con":0})

for eidh in all_eidhs:
    cl = sid = None
    for src in (pdf, pptx, xlsx):
        e = src.get(eidh)
        if e and e.get("client_code"):
            cl = e["client_code"]; sid = e.get("design_id") or ""; break
    if not cl: continue
    if not sid:
        for src in (pdf, pptx, xlsx):
            e = src.get(eidh)
            if e and e.get("design_id"): sid = e["design_id"]; break

    s = stats[cl]; s["total"] += 1
    dev = is_dev(sid)
    if dev: s["dev"] += 1
    is_u = eidh in unrec and not dev
    if is_u: s["unrec"] += 1
    excl = dev or cl in PDF_METADATA_ONLY or is_u

    pdf_e = pdf.get(eidh) or {}; xlsx_e = xlsx.get(eidh) or {}; pptx_e = pptx.get(eidh) or {}
    pdf_m = {k:v for k,v in (pdf_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    xlsx_m = {k:v for k,v in (xlsx_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    if pdf_m or xlsx_m: s["meta"] += 1

    pdf_pom = sum(len(m.get("poms") or []) for m in (pdf_e.get("measurement_charts") or []))
    xlsx_pom = sum(len(m.get("poms") or []) for m in (xlsx_e.get("measurement_charts") or []))
    if pdf_pom > 0 or xlsx_pom > 0:
        s["pom_any"] += 1
        if not excl: s["pom_real"] += 1
    s["poms"] += pdf_pom + xlsx_pom

    if pdf_e.get("construction_pages") or pptx_e.get("constructions"): s["con"] += 1


def pct(n, t): return "{:>3.0f}%".format(n/max(t,1)*100)


print(f"\n=== 跨 3 source 覆蓋率 (POM%(real) = 排除 dev + unrec + PDF-meta-only) ===\n")
print(f"  {'brand':<8} {'total':>6} {'dev':>5} {'unrec':>5}  {'meta%':>5} {'POM%(real)':>17} {'POMs':>9}  {'構造%':>5}  flag")
print("  " + "-"*100)

CUTOFF = 150
for cl in sorted(stats.keys(), key=lambda c: -stats[c]["total"]):
    s = stats[cl]
    if s["total"] < CUTOFF: continue
    if cl in PDF_METADATA_ONLY:
        real = 0
    else:
        real = s["total"] - s["dev"] - s["unrec"]

    meta_p = s["meta"]/s["total"]*100
    pom_p = (s["pom_real"]/max(real,1)*100) if real > 0 else 0
    con_p = s["con"]/s["total"]*100

    flags = []
    if meta_p < 80: flags.append("meta⚠")
    if real > 0 and pom_p < 80: flags.append("POM⚠")
    elif real == 0 and cl in PDF_METADATA_ONLY: flags.append("PDF-meta-only")
    elif real == 0: flags.append("dev-only")
    if con_p < 80: flags.append("構造⚠")
    flag_str = " ".join(flags) if flags else "✅"

    if real > 0:
        pom_str = f"{pom_p:>4.0f}% ({s['pom_real']}/{real})"
    elif cl in PDF_METADATA_ONLY:
        pom_str = "N/A (meta only)"
    else:
        pom_str = "N/A"

    print(f"  {cl:<8} {s['total']:>6} {s['dev']:>5} {s['unrec']:>5}  {pct(s['meta'],s['total']):>5} {pom_str:>17} {s['poms']:>9,}  {pct(s['con'],s['total']):>5}  {flag_str}")


print(f"\n=== Summary ===")
te = sum(s["total"] for s in stats.values())
td = sum(s["dev"] for s in stats.values())
tu = sum(s["unrec"] for s in stats.values())
real_tp = te - td - tu
tp = sum(s["poms"] for s in stats.values())
print(f"  All EIDH:        {te:,}")
print(f"  Dev sample:      {td:,} ({td*100/max(te,1):.1f}%)")
print(f"  Unrecoverable:   {tu:,} ({tu*100/max(te,1):.1f}%)")
print(f"  Real techpack:   {real_tp:,} ({real_tp*100/max(te,1):.1f}%)")
print(f"  Total POMs:      {tp:,}")
