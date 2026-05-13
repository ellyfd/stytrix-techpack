"""audit_v6.py — Honest 3-bucket audit: A (parser-fail) / B (sample-room) / C (true-no-source).

Differs from audit_v5:
  - A 桶 (parser-fail / 還沒寫好 parser 的 layout) **留在分母** — 它們是「應該救但暫時沒救」的真設計
  - B 桶 (dev_sample / sample-room prefix) 從分母排除 — 預期沒 POM
  - C 桶 (objectively no source) 從分母排除 — 已驗無資料源

分類邏輯（每筆 zero-POM design）:
  1. 是 dev_sample (regex match) → B
  2. PDF 含 MC 文字 (POM_HDR_RE) OR 有 mc_entries → A (parser-attempted-but-failed)
  3. otherwise → C (no MC text in PDF, no source)

每個 brand 顯示:
  brand | total | dev(B) | parser-fail(A) | true-gap(C) | POM% strict (POM/(total-dev-C)) | POM% inflated (audit_v5 style)
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"

# Sync with audit_3source_coverage.py
DEV_RE = re.compile(
    r"^(AIM[\w\-]{3,15}|ONY[\w\-]+|ON[_A-Z\d][\w\-]*|BY[\w\-]+|IPS[\w\-]*|VDD[\w\-]*"
    r"|VLHY\d{2}\w+|RR[A-Z]{3,8}\d{2}\w*|FRP[A-Z]{3,8}\w*|FRND[\w\-]+|KNT[A-Z]{3,8}\w*"
    r"|SPR\d{2}\w+|FLX\d{2}[A-Z\d]+|APT[\w\-]+|CBRTW\d{2}[A-Z]+|DSG\d{2}[A-Z]{2}\w*"
    r"|VRST\d{2}[A-Z]{1,3}\w*|CALIA\d{2}\w*|SON\d{2}\w+|MST[A-Z]{0,4}\d+"
    r"|FH\d{2}[A-Z]+\w*|HY\d{2}[A-Z]+\w*|WC\d?[A-Z\d]{4,8}|MT\d?[A-Z\d]{4,8}|WT\d?[A-Z\d]{4,8}"
    r"|MVG\d{4}|WAX\d+\w*|WCG\d+\w*"
    # 2026-05-13 Elly-confirmed B 桶 prefix → dev
    r"|S[UP]\d{2}C[BNS]?\w*|FA\d{2}CB\w*|S[UP]\d{2}S[NS]?\w*"
    r"|KOH\d{2}\w+|RDWT\d?\w*|RDMX\d?\w*|RDEX\d?\w*|RDMT\d?\w*"
    r"|MX\d[A-Z]{1,3}\w*|WX\d[A-Z]{1,3}\w*|ZS\d[A-Z]{2}\w*"
    r"|SOMEN\w+|MK\d{2}AW\w*|MSFA\d\w*"
    r"|VELOC\w+|UASS\d+\w*|UAMGF\w+|FW\d{2}U[\w\-]+"
    r"|MAX\d+[A-Z]?\w*|DAM\d+[A-Z]?\w*|DAB27\w*"
    r")", re.IGNORECASE)

GAP_DEV_RE = re.compile(
    r"(GAP\w+|GST\w+|GSM\w*|INNOV|^SP\d{2}GO\w*|^SS\d{2}GST\w*|^CM\d{2}\w+|^MK\d{4}\w*)",
    re.IGNORECASE)

PDF_META_ONLY = {"GU"}
POM_HDR_RE = re.compile(r"POM|Measurement|TOL|Point of Measure|Tol\s*\(", re.I)


def is_dev(sid):
    if not sid: return False
    return bool(DEV_RE.match(sid) or GAP_DEV_RE.search(sid))


def load_jsonl(p):
    d = {}
    if not p.exists(): return d
    with open(p, encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except: continue
            if e.get("eidh"): d[e["eidh"]] = e
    return d


pdf = load_jsonl(EXTRACT_DIR / "pdf_facets.jsonl")
pptx = load_jsonl(EXTRACT_DIR / "pptx_facets.jsonl")
xlsx = load_jsonl(EXTRACT_DIR / "xlsx_facets.jsonl")

print(f"\n[loaded] PDF={len(pdf):,} / PPTX={len(pptx):,} / XLSX={len(xlsx):,}")

all_eidhs = set(pdf.keys()) | set(pptx.keys()) | set(xlsx.keys())
stats = defaultdict(lambda: {
    "total": 0,
    "dev": 0,        # B 桶 — sample room / dev
    "parser_fail": 0, # A 桶 — has MC content but no POM extracted
    "true_gap": 0,   # C 桶 — no MC content anywhere
    "with_pom": 0,
    "poms": 0,
    "meta": 0, "con": 0,
})

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
            if e and e.get("design_id"):
                sid = e["design_id"]; break

    s = stats[cl]; s["total"] += 1

    pdf_e = pdf.get(eidh) or {}; xlsx_e = xlsx.get(eidh) or {}; pptx_e = pptx.get(eidh) or {}
    pdf_m = {k:v for k,v in (pdf_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    xlsx_m = {k:v for k,v in (xlsx_e.get("metadata") or {}).items() if not k.startswith("_") and v}
    if pdf_m or xlsx_m: s["meta"] += 1
    if pdf_e.get("construction_pages") or pptx_e.get("constructions"): s["con"] += 1

    pdf_pom = sum(len(m.get("poms") or []) for m in (pdf_e.get("measurement_charts") or []))
    xlsx_pom = sum(len(m.get("poms") or []) for m in (xlsx_e.get("measurement_charts") or []))
    has_pom = pdf_pom > 0 or xlsx_pom > 0
    s["poms"] += pdf_pom + xlsx_pom
    if has_pom: s["with_pom"] += 1

    # Categorize zero-POM:
    if has_pom: continue
    if is_dev(sid):
        s["dev"] += 1
        continue
    if cl in PDF_META_ONLY:
        s["true_gap"] += 1  # PDF-meta-only treated as no source
        continue
    # Check PDF for MC text
    all_text = ""
    for cp in pdf_e.get("construction_pages") or []:
        for ci in cp.get("construction_items") or []:
            all_text += ci.get("_raw_callout_text") or ""
    n_mc_entries = len(pdf_e.get("measurement_charts") or [])
    has_mc = bool(POM_HDR_RE.search(all_text)) or n_mc_entries > 0
    if has_mc:
        s["parser_fail"] += 1   # A
    else:
        s["true_gap"] += 1      # C


def pct(n, t): return "{:>3.0f}%".format(n/max(t,1)*100)


print(f"\n=== Honest 3-bucket audit ===\n")
print(f"  Real total = total - dev - true_gap (parser_fail STAYS in denom)")
print(f"  POM%(honest) = with_pom / real_total")
print(f"  POM%(inflated) = with_pom / (real_total - parser_fail) ← audit_v5 style\n")

hdr = "  {:<8} {:>6} {:>5} {:>5} {:>5}  {:>11}  {:>15}  {:>15}  {:>9}".format(
    "brand", "total", "dev(B)", "fail(A)", "gap(C)", "real_denom", "POM%(honest)", "POM%(inflated)", "POMs")
print(hdr)
print("  " + "-"*110)

CUTOFF = 150
for cl in sorted(stats.keys(), key=lambda c: -stats[c]["total"]):
    s = stats[cl]
    if s["total"] < CUTOFF: continue
    if cl in PDF_META_ONLY:
        real_denom_honest = 0
        real_denom_inflated = 0
    else:
        real_denom_honest = s["total"] - s["dev"] - s["true_gap"]
        real_denom_inflated = real_denom_honest - s["parser_fail"]

    if real_denom_honest > 0:
        pom_honest_pct = s["with_pom"] / real_denom_honest * 100
        pom_honest_str = f"{pom_honest_pct:>4.0f}% ({s['with_pom']}/{real_denom_honest})"
    elif cl in PDF_META_ONLY:
        pom_honest_str = "N/A (meta only)"
    else:
        pom_honest_str = "N/A"

    if real_denom_inflated > 0:
        pom_inf_pct = s["with_pom"] / real_denom_inflated * 100
        pom_inf_str = f"{pom_inf_pct:>4.0f}% ({s['with_pom']}/{real_denom_inflated})"
    elif cl in PDF_META_ONLY:
        pom_inf_str = "N/A"
    else:
        pom_inf_str = "N/A"

    print("  {:<8} {:>6} {:>5} {:>5} {:>5}  {:>11}  {:>15}  {:>15}  {:>9,}".format(
        cl, s["total"], s["dev"], s["parser_fail"], s["true_gap"],
        real_denom_honest, pom_honest_str, pom_inf_str, s["poms"]))


print(f"\n=== Summary ===")
te = sum(s["total"] for s in stats.values())
td = sum(s["dev"] for s in stats.values())
tpf = sum(s["parser_fail"] for s in stats.values())
ttg = sum(s["true_gap"] for s in stats.values())
twp = sum(s["with_pom"] for s in stats.values())
tp = sum(s["poms"] for s in stats.values())
real = te - td - ttg
print(f"  All EIDH:           {te:,}")
print(f"  B dev:              {td:,} ({td*100/te:.1f}%)")
print(f"  A parser-fail:      {tpf:,} ({tpf*100/te:.1f}%) ← 還沒寫到的 layout, 應修 parser")
print(f"  C true-no-source:   {ttg:,} ({ttg*100/te:.1f}%)")
print(f"  Real denom (B+C 排除, A 留在分母): {real:,}")
print(f"  With POM:           {twp:,}")
print(f"  POM%(honest):       {twp/max(real,1)*100:.1f}%")
print(f"  Total POMs:         {tp:,}")
