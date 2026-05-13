"""
跨 3 source 合併覆蓋率 audit (v3 — 加 PDF format limitation 排除)
跑法: python scripts\\audit_3source_coverage.py

對每個 EIDH 看「PDF/PPTX/XLSX 至少一個 source」抽到該維度：
  - metadata: PDF metadata OR XLSX metadata
  - POM: PDF measurement_charts has poms OR XLSX measurement_charts has poms
  - construction: PDF construction_pages OR PPTX constructions

按 brand 統計 union coverage. 任一維度 <80% 的「真實能力」brand 列為待查.

⚡ 三層排除 (POM 抽取「不適用」的情境)：

  1. **Dev-sample**（Makalot 內部 Sample Room）— design code prefix 偵測
     例：BY26/CBRTW/DSG/SON/AIM/MSTAR/WAX/WCG/MVG/FH/HY/WC/MT/WT
     本質：開發樣，只有 metadata + construction，無 POM chart by design

  2. **PDF metadata-only brand**（PDF 是版型管理表/分類表，不含 POM）— 整 brand 排除
     例：GU (デザイン管理表 / 日文版型管理表)
     本質：PDF 只列零件部位 + 用料，POM/construction 在 PPTX/XLSX

  3. **PDF screenshot-only POM**（POM 存在但是截圖貼上，text-extract 抓不到）
     例：TGT AIM 開頭多數
     本質：用戶確認「AIM 開頭多沒尺寸表，部份是截圖貼上，無法抽取」
     對策：當 dev-sample 排除（已含 AIM 在 regex）

  排除後 POM% 的分母 = real_total = total - excluded_count，這是 PDF text-extract 真實能力。
  Metadata% / 構造% 仍照 total 算（這兩維度 dev sample 也有資料）。
"""
import json
import re
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "extract"

# ════════════════════════════════════════════════════════════
# Dev-sample design code 偵測 (Makalot 內部開發樣)
# ════════════════════════════════════════════════════════════
DEV_SAMPLE_RE = re.compile(
    # ⚡ Elly 確認 (2026-05-13): 「AIM / ON / ONY / BY 開頭的款號都是 dev 款,
    #   只會有 metadata + 中或英文作工, 不會有 POM」
    r"^("
    # === 4 個明確 dev prefix (Elly 規則) ===
    r"AIM[\w\-]{3,15}"           # TGT AIM 線: AIMSS26W004 / AIM_BB_C126 / AIMCA-W01
    r"|ONY[\w\-]+"                # Old Navy dev: ONY25HOVDD01_2
    r"|ON[_A-Z\d][\w\-]*"         # Old Navy dev (ON_/ONK/ON26 等變體): ON_SS26_TSD_04 / ONKNTHO25_01 / ON26SUTG01
    r"|BY[\w\-]+"                 # Beyond Yoga dev: BY26SP012 / BY27FW010 (broadened)
    # === ONY 開發樣 prefix (2026-05-13 Elly 確認 IPS/VDD 是 ONY 開發樣) ===
    r"|IPS[\w\-]*"                # ONY Innovation 線: IPS_SS26_M03, IPSRR25FA01, IPSRRPSL01
    r"|VDD[\w\-]*"                # ONY VDD 線: VDDHO25FLE_02, VDDTGW26SP_04, VDDTSD26SP_11, VDDMEN26SP_05
    # === 其他開發樣 prefix (brand 不確定但確定是開發樣) ===
    r"|VLHY\d{2}\w+"              # VLHY26_LS10 (Velour Holiday)
    r"|RR[A-Z]{3,8}\d{2}\w*"      # RRSSN/RRPSFL/RRSS等
    r"|FRP[A-Z]{3,8}\w*"          # FRPJFA series
    r"|FRND[\w\-]+"               # FRNDHY26_PR01 (Friends collection)
    r"|KNT[A-Z]{3,8}\w*"          # KNTMWSP_01 (Knit Men's Spring)
    r"|^SPR\d{2}\w+"              # SPR series
    # === Sample Room internal codes (其他客人) ===
    r"|FLX\d{2}[A-Z\d]+"          # KOH FLX line dev: FLX26SSM05 (2026-05-13 Elly 確認)
    r"|APT[\w\-]+"                # KOH APT line dev (2026-05-13 Elly 確認)
    r"|CBRTW\d{2}[A-Z]+"          # KOH Croft & Barrow RTW: CBRTW26SS04
    r"|DSG\d{2}[A-Z]{2}\w*"       # DKS DSG Sample Room: DSG26AW009
    r"|VRST\d{2}[A-Z]{1,3}\w*"    # VRST: VRST26AWM08
    r"|CALIA\d{2}\w*"             # Calia: CALIA26W
    r"|SON\d{2}\w+"               # TGT Sonoma: SON26xxx
    r"|MST[A-Z]{0,4}\d+"          # TGT MSTAR: MSTYP08
    # === KOH "ToSampleRoom" 單頁迷你 Techpack ===
    r"|FH\d{2}[A-Z]+\w*"          # KOH FH25SNSL004 / FH25CB-GN06
    r"|HY\d{2}[A-Z]+\w*"          # KOH HY25CB-RB07
    r"|WC\d?[A-Z\d]{4,8}"         # KOH WC53K411
    r"|MT\d?[A-Z\d]{4,8}"         # KOH MT43A102
    r"|WT\d?[A-Z\d]{4,8}"         # KOH WT42A206
    # === DKS 雜項款 ===
    r"|MVG\d{4}"                  # DKS MVG2503
    r"|WAX\d+\w*"                 # DKS WAX105X
    r"|WCG\d+\w*"                 # DKS WCG3010
    # === 2026-05-13 Elly confirmed B 桶 prefix 升 dev (audit cleanup) ===
    # KOH Sample Room family (季別+CB / 全季 / RD / MX/WX / ZS / SO/MK/MS):
    r"|S[UP]\d{2}C[BNS]?\w*"      # SU26CB_EB03 / SP26CB_NW07 / SU26S/SP26S NSL
    r"|FA\d{2}CB\w*"              # FA26CB_LG04
    r"|S[UP]\d{2}S[NS]?\w*"       # SU26SNSL001 / SP26SNSL001
    r"|KOH\d{2}\w+"               # KOH26PRM02
    r"|RDWT\d?\w*|RDMX\d?\w*"    # RDWT6SV253 / RDMX6UK001
    r"|RDEX\d?\w*|RDMT\d?\w*"    # RDEX6SK100 / RDMT6SA100
    r"|MX\d[A-Z]{1,3}\w*"         # MX5FK203 / MX6SK104 / MX6SW301 / MX6HK000
    r"|WX\d[A-Z]{1,3}\w*"         # WX5HA107 / WX6UV200 / WX6HA100
    r"|ZS\d[A-Z]{2}\w*"           # ZS6FP001 / ZS6FX000 / ZS6FR004 etc.
    r"|SOMEN\w+"                  # SOMENSLW250502
    r"|MK\d{2}AW\w*"              # MK26AWSO01 / MK26AW_CB02
    r"|MSFA\d\w*"                 # MSFA2601
    # UA Sample Room family (Elly confirmed: VELOC/UASS2/UAMGF/FW27U dev;
    # UATSM 排除 — Elly 1357139 有 POM, 是 PLM 真款):
    r"|VELOC\w+"                  # VELOCITI STORM JACKET_01
    r"|UASS\d+\w*"                # UASS27MJ01 & UASS27MP01
    r"|UAMGF\w+"                  # UAMGFBT_01
    r"|FW\d{2}U[\w\-]+"           # FW27UA_B01
    # DKS Sample Room (MAX/DAM/DAB27 specific — Elly confirmed):
    r"|MAX\d+[A-Z]?\w*"           # MAX70P_Q126 / MAX23A104 / MAX34_Q425 / MGA40 用 MGA\d 分開
    r"|DAM\d+[A-Z]?\w*"           # DAM18 / DAM14 / DAM143
    r"|DAB27\w*"                  # DAB27SS01 (specifically — DAB main line is real PLM)
    r")",
    re.IGNORECASE
)


def is_dev_sample(design_id):
    if not design_id:
        return False
    if DEV_SAMPLE_RE.match(design_id):
        return True
    # GAP collection dev markers (Elly 確認 2026-05-13: GAP/GST/INNOV/GSM/GO 都是開發)
    if GAP_DEV_RE.search(design_id):
        return True
    return False


# GAP collection dev markers — substring match anywhere in design_id
# Captures: GAP26SSACT / GSTSDINNOV / GSM_SEASONLESS / GSMHO25 /
#           SS26GSTSD / SP26GOTSD / S842626_INNOVFA26 / CM25SP / MK0001
GAP_DEV_RE = re.compile(
    r"(GAP\w+"               # GAP26x, GAPGSM, GAPSS, GAPGOM, GAPGOKB, GAPGSKB
    r"|GST\w+"               # GSTSDINNOV
    r"|GSM\w*"               # GSM, GSMHO, GSM_SEASONLESS
    r"|INNOV"                # _INNOVFA26 / INNOVxxx 任何位置
    r"|^SP\d{2}GO\w*"        # SP26GOTSD
    r"|^SS\d{2}GST\w*"       # SS26GSTSD
    r"|^CM\d{2}\w+"          # CM25SP, CM26x
    r"|^MK\d{4}\w*"          # MK0001_DEMO
    r")",
    re.IGNORECASE
)


# PDF metadata-only brand (整 brand 排除)
# Elly 確認 (2026-05-13): GU PDF = デザイン管理表 (版型管理表), 只有 metadata
PDF_METADATA_ONLY_BRANDS = {"GU"}


def is_pdf_metadata_only_brand(client_code):
    return client_code in PDF_METADATA_ONLY_BRANDS


# ════════════════════════════════════════════════════════════
# Unrecoverable POM marker list (2026-05-13)
# ════════════════════════════════════════════════════════════
# 從 scripts/mark_unrecoverable_pom.py 產出的 list — 這些 designs 雖然不是 dev sample,
# 但結構上無法從現有 PDF/PPTX/XLSX 抽到 POM (前季 archive 在聚陽 m7 端 / PPTX 只有中文 label /
# scan PDF). 同樣從 POM% 分母排除 (邏輯類似 dev sample, 只是 reason 不同).
def load_unrecoverable_pom_eidhs(path):
    """Return {eidh: reason_code} for all unrecoverable POM EIDHs."""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            eidh = e.get("eidh")
            if eidh and e.get("_pom_unrecoverable"):
                out[str(eidh)] = e.get("_unrecoverable_reason", "unknown")
    return out


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


pdf = load_jsonl(OUT_DIR / "pdf_facets.jsonl")
pptx = load_jsonl(OUT_DIR / "pptx_facets.jsonl")
xlsx = load_jsonl(OUT_DIR / "xlsx_facets.jsonl")
unrecoverable_pom = load_unrecoverable_pom_eidhs(OUT_DIR / "ony_pom_unrecoverable.jsonl")

print("\n[loaded] PDF={:,} / PPTX={:,} / XLSX={:,} / unrecoverable_pom={:,}".format(
    len(pdf), len(pptx), len(xlsx), len(unrecoverable_pom)))

all_eidhs = set(pdf.keys()) | set(pptx.keys()) | set(xlsx.keys())

stats = defaultdict(lambda: {
    "total": 0,
    "dev_sample": 0,
    "unrecoverable": 0,            # 新加: structural no-POM (前季 archive / scan PDF / etc.)
    "meta_pdf": 0, "meta_xlsx": 0, "meta_any": 0,
    "pom_pdf": 0, "pom_xlsx": 0, "pom_any": 0, "total_poms": 0,
    "pom_real_any": 0,
    "construct_pdf": 0, "construct_pptx": 0, "construct_any": 0,
})

dev_sample_examples = defaultdict(list)

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

    if not design_id:
        for src in (pdf, pptx, xlsx):
            e = src.get(eidh)
            if e and e.get("design_id"):
                design_id = e["design_id"]
                break

    s = stats[cl]
    s["total"] += 1

    is_dev = is_dev_sample(design_id)
    if is_dev:
        s["dev_sample"] += 1
        if len(dev_sample_examples[cl]) < 3:
            dev_sample_examples[cl].append(design_id)

    # Unrecoverable POM check (structural no-source, not dev sample)
    is_unrecoverable = eidh in unrecoverable_pom and not is_dev
    if is_unrecoverable:
        s["unrecoverable"] += 1

    is_metaonly = is_pdf_metadata_only_brand(cl)
    pom_excluded = is_dev or is_metaonly or is_unrecoverable

    pdf_e = pdf.get(eidh) or {}
    xlsx_e = xlsx.get(eidh) or {}
    pptx_e = pptx.get(eidh) or {}

    pdf_meta = pdf_e.get("metadata") or {}
    pdf_meta_real = {k: v for k, v in pdf_meta.items() if not k.startswith("_") and v}
    xlsx_meta = xlsx_e.get("metadata") or {}
    xlsx_meta_real = {k: v for k, v in xlsx_meta.items() if not k.startswith("_") and v}

    if pdf_meta_real:
        s["meta_pdf"] += 1
    if xlsx_meta_real:
        s["meta_xlsx"] += 1
    if pdf_meta_real or xlsx_meta_real:
        s["meta_any"] += 1

    pdf_mcs = pdf_e.get("measurement_charts") or []
    pdf_pom_count = sum(len(m.get("poms") or []) for m in pdf_mcs)
    xlsx_mcs = xlsx_e.get("measurement_charts") or []
    xlsx_pom_count = sum(len(m.get("poms") or []) for m in xlsx_mcs)

    if pdf_pom_count > 0:
        s["pom_pdf"] += 1
    if xlsx_pom_count > 0:
        s["pom_xlsx"] += 1
    if pdf_pom_count > 0 or xlsx_pom_count > 0:
        s["pom_any"] += 1
        if not pom_excluded:
            s["pom_real_any"] += 1
    s["total_poms"] += pdf_pom_count + xlsx_pom_count

    pdf_cp = pdf_e.get("construction_pages") or []
    pptx_c = pptx_e.get("constructions") or []
    if pdf_cp:
        s["construct_pdf"] += 1
    if pptx_c:
        s["construct_pptx"] += 1
    if pdf_cp or pptx_c:
        s["construct_any"] += 1


def pct(n, total):
    return "{:>3.0f}%".format(n / max(total, 1) * 100)


print("\n=== 跨 3 source 合併覆蓋率 (Union: PDF + PPTX + XLSX) ===")
print("  ⚡ POM% 雙算: 'POM%(all)' = 含 dev sample / 'POM%(real)' = 排除 dev + PDF-meta-only brand\n")
header = "  {:<8} {:>6} {:>5} {:>5}  {:>6} ({:>3}/{:>3}) {:>9} {:>16} {:>9}  {:>5} ({:>3}/{:>3})  {:<25}".format(
    "brand", "total", "dev", "unrec", "meta%", "P", "X",
    "POM%(all)", "POM%(real)", "POMs",
    "構造%", "P", "PT", "flag")
print(header)
print("  {} {} {} {}  {} {} {} {} {} {}  {} {} {}  {}".format(
    "-" * 8, "-" * 6, "-" * 5, "-" * 5, "-" * 6, "-" * 3, "-" * 3,
    "-" * 9, "-" * 16, "-" * 9, "-" * 5, "-" * 3, "-" * 3, "-" * 25))

sorted_brands = sorted(stats.keys(), key=lambda c: -stats[c]["total"])

# Brand cutoff: ZARA 以下 (含 ZAR 142 / V5 DEV 100 / JF 98 / ASICS 81 / HLA 80 /
# S1 DEV 73 / V2 DEV 66 / DST 54 / LEV 50 / CATO 38 / GILDAN 10 等) 不列入主表
# 2026-05-13 Elly 確認: 太小 brand 不在主視野, dev 線 (V5/S1/V2/V7) 也不算
SMALL_BRANDS_CUTOFF = 150  # ZARA 以下都跳過
EXCLUDED_SMALL = []  # 收集 skip 的 brand 給最後印 "Excluded"

need_attention = []
for cl in sorted_brands:
    s = stats[cl]
    if s["total"] < SMALL_BRANDS_CUTOFF:
        EXCLUDED_SMALL.append((cl, s["total"]))
        continue

    if is_pdf_metadata_only_brand(cl):
        real_total = 0
    else:
        # 新加: 從 real_total 同時扣 dev_sample + unrecoverable
        real_total = s["total"] - s["dev_sample"] - s["unrecoverable"]

    meta_pct = s["meta_any"] / s["total"] * 100
    pom_pct_real = (s["pom_real_any"] / max(real_total, 1) * 100) if real_total > 0 else 0
    construct_pct = s["construct_any"] / s["total"] * 100

    flags = []
    if meta_pct < 80:
        flags.append("meta⚠")
    if real_total > 0 and pom_pct_real < 80:
        flags.append("POM⚠")
    elif real_total == 0 and is_pdf_metadata_only_brand(cl):
        flags.append("PDF-meta-only")
    elif real_total == 0:
        flags.append("dev-only")
    if construct_pct < 80:
        flags.append("構造⚠")
    flag_str = " ".join(flags) if flags else "✅"

    if real_total > 0:
        pom_real_str = "{:>4.0f}% ({}/{})".format(pom_pct_real, s["pom_real_any"], real_total)
    elif is_pdf_metadata_only_brand(cl):
        pom_real_str = "N/A (meta only)"
    else:
        pom_real_str = "N/A"

    row = "  {:<8} {:>6} {:>5} {:>5}  {:>6} ({:>3}/{:>3}) {:>9} {:>16} {:>9,}  {:>5} ({:>3}/{:>3})  {:<25}".format(
        cl, s["total"], s["dev_sample"], s["unrecoverable"],
        pct(s["meta_any"], s["total"]),
        pct(s["meta_pdf"], s["total"]),
        pct(s["meta_xlsx"], s["total"]),
        pct(s["pom_any"], s["total"]),
        pom_real_str,
        s["total_poms"],
        pct(s["construct_any"], s["total"]),
        pct(s["construct_pdf"], s["total"]),
        pct(s["construct_pptx"], s["total"]),
        flag_str)
    print(row)

    if flags and cl != "TGT" and "dev-only" not in flags and "PDF-meta-only" not in flags:
        need_attention.append((cl, s, flags, meta_pct, pom_pct_real, construct_pct, real_total))


print("\n=== Dev-sample 抓到的 design code 範例 (per brand top 3) ===\n")
for cl in sorted(dev_sample_examples.keys()):
    examples = dev_sample_examples[cl]
    n_dev = stats[cl]["dev_sample"]
    n_total = stats[cl]["total"]
    if examples:
        print("  {:<8} {}/{} ({}%): {}".format(
            cl, n_dev, n_total, n_dev * 100 // n_total, ", ".join(examples)))


print("\n=== PDF metadata-only brands (整 brand 排除 PDF POM) ===\n")
for cl in PDF_METADATA_ONLY_BRANDS:
    if cl in stats:
        s = stats[cl]
        print("  {} = {} entries (PDF 是版型管理表性質, 不抽 PDF POM, 看 PPTX/XLSX)".format(cl, s["total"]))


print("\n=== Excluded small brands (< {} 件, 不在主表) ===\n".format(SMALL_BRANDS_CUTOFF))
total_excluded = sum(n for _, n in EXCLUDED_SMALL)
print("  共 {} brand, {} entries 不列入主視野:".format(len(EXCLUDED_SMALL), total_excluded))
for cl, n in EXCLUDED_SMALL:
    print("    {:<10} {} 件".format(cl, n))


print("\n=== 需查 brand (排除 dev + PDF-meta-only 後 POM% < 80%, TGT 除外) ===\n")
if not need_attention:
    print("  🎉 全部 brand 三維度都 ≥80%, 無需深查")
else:
    for cl, s, flags, m, p, c, real_total in need_attention:
        print("\n  ⚠ {} (total={}, dev_sample={}, real={}):".format(cl, s["total"], s["dev_sample"], real_total))
        print("    metadata: {}/{} = {:.0f}% (PDF {}, XLSX {})".format(
            s["meta_any"], s["total"], m, s["meta_pdf"], s["meta_xlsx"]))
        print("    POM (all):  {}/{} = {:.0f}%".format(
            s["pom_any"], s["total"], s["pom_any"] / s["total"] * 100))
        print("    POM (real): {}/{} = {:.0f}%  ← 排除 dev sample 後真實能力".format(
            s["pom_real_any"], real_total, p))
        print("    POM rows:   {:,} 行".format(s["total_poms"]))
        print("    構造:       {}/{} = {:.0f}% (PDF {}, PPTX {})".format(
            s["construct_any"], s["total"], c, s["construct_pdf"], s["construct_pptx"]))
        print("    flags: {}".format(" ".join(flags)))


print("\n=== Summary ===")
total_eidh = sum(s["total"] for s in stats.values())
total_dev = sum(s["dev_sample"] for s in stats.values())
total_unrec = sum(s["unrecoverable"] for s in stats.values())
real_techpack = total_eidh - total_dev - total_unrec
print("  All EIDH:         {:,}".format(total_eidh))
print("  Dev sample:       {:,} ({:.1f}%)".format(total_dev, total_dev * 100 / max(total_eidh, 1)))
print("  Unrecoverable:    {:,} ({:.1f}%) ← 結構性 gap, 跟 dev 一樣排除".format(
    total_unrec, total_unrec * 100 / max(total_eidh, 1)))
print("  Real techpack:    {:,} ({:.1f}%)".format(real_techpack, real_techpack * 100 / max(total_eidh, 1)))
print("  Total POMs:       {:,}".format(sum(s["total_poms"] for s in stats.values())))
