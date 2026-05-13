"""
Per-brand PDF audit — 看每個 pdf_facets_<BRAND>.jsonl 的品質, 跟預期 tp_samples 資料夾數比對
跑法: python scripts\audit_per_brand_pdf.py

輸出:
  - 每 brand 的 entries / ok / timeout / no_pdf
  - meta / callout / mcs 抽取率
  - tp_samples 對應資料夾數 (預期值)
  - 缺漏判斷 + 建議動作
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"
TP_DIR = ROOT / "tp_samples_v2"
MANIFEST = ROOT / "m7_organized_v2" / "_fetch_manifest.csv"


def load_manifest_lookup():
    """Load EIDH → client_code mapping (對齊 extract_pdf_all.py 邏輯)"""
    import csv
    lookup = {}
    if not MANIFEST.exists():
        print(f"[!] manifest 不存在: {MANIFEST}")
        return lookup
    with open(MANIFEST, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            eidh = (row.get("Eidh") or "").strip()  # 注意首大寫
            if not eidh:
                continue
            client_raw = (row.get("客戶") or "").strip()
            lookup[eidh] = client_raw  # 存 raw 客戶名, 下面 mapping 轉 code
    return lookup


# 從 extract_pdf_all.py 同步過來
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


def raw_to_code(client_raw: str) -> str:
    if not client_raw:
        return "UNKNOWN"
    norm = client_raw.upper().strip()
    return CLIENT_RAW_TO_CODE.get(norm, norm[:6])


def count_tp_folders_per_brand():
    """Scan tp_samples_v2/ and count folders per brand using manifest"""
    counts = Counter()
    lookup = load_manifest_lookup()
    if not TP_DIR.exists():
        return counts, lookup
    for d in TP_DIR.iterdir():
        if not d.is_dir():
            continue
        eidh = d.name.split("_")[0]
        client_raw = lookup.get(eidh, "")
        code = raw_to_code(client_raw)
        counts[code] += 1
    return counts, lookup


def audit_brand_file(path: Path, expected: int) -> dict:
    """Audit a single per-brand pdf_facets_<X>.jsonl"""
    if not path.exists():
        return {"error": "file missing"}
    n_total = 0
    n_meta = 0
    n_callout = 0
    n_mcs = 0
    n_pom = 0
    statuses = Counter()
    has_pdf = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_total += 1
            statuses[d.get("_status", "?")] += 1
            if d.get("metadata"):
                n_meta += 1
            # 2026-05-12 rename: callouts → construction_pages (PDF)
            if d.get("construction_pages") or d.get("callouts"):
                n_callout += 1
            if d.get("measurement_charts"):
                n_mcs += 1
                for mc in d["measurement_charts"]:
                    rows = mc.get("rows") or mc.get("poms") or []
                    n_pom += len(rows)
            if d.get("pdf_files") or d.get("pdf_path"):
                has_pdf += 1
    return {
        "n_total": n_total,
        "expected": expected,
        "missing": expected - n_total if expected else 0,
        "statuses": dict(statuses),
        "n_meta": n_meta,
        "n_callout": n_callout,
        "n_mcs": n_mcs,
        "n_pom": n_pom,
        "has_pdf": has_pdf,
        "size_mb": path.stat().st_size // 1024 // 1024,
    }


def recommend(brand: str, r: dict) -> str:
    """根據 audit 結果給建議"""
    if "error" in r:
        return f"❌ 沒檔案 — 跑 `python scripts\\extract_pdf_all.py --client {brand}`"
    if r["expected"] == 0:
        return "ℹ tp_samples 沒這個 brand"
    miss = r["missing"]
    miss_pct = miss / r["expected"] * 100 if r["expected"] else 0
    timeout_n = r["statuses"].get("timeout", 0)

    if miss <= 5 and timeout_n <= 5:
        return "✅ 完整 (對齊預期)"
    if miss <= 0:
        # 數字超過預期 (例: tp_samples 資料夾還沒建 manifest 就跑了)
        return "⚠ entries > 預期, manifest 可能對不齊"
    if timeout_n / r["expected"] > 0.10:
        return f"⚠ {timeout_n} timeout 過高 ({timeout_n/r['expected']*100:.0f}%) — 加長 PER_TASK_TIMEOUT 重跑該 brand"
    if miss_pct > 20:
        return f"❌ 少 {miss} ({miss_pct:.0f}%) — 重跑 `--client {brand}`"
    if miss_pct > 5:
        return f"⚠ 少 {miss} ({miss_pct:.0f}%), 可考慮重跑"
    return "✅ 接近完整"


def main():
    print(f"\n=== Per-brand PDF audit ===\n")
    print(f"[scan] {TP_DIR}")
    expected_counts, lookup = count_tp_folders_per_brand()
    print(f"[manifest] {len(lookup):,} EIDH → client mappings")
    print(f"[expected] {sum(expected_counts.values()):,} folders across {len(expected_counts)} brands\n")

    files = sorted(OUT_DIR.glob("pdf_facets_*.jsonl"))
    files = [f for f in files if f.name != "pdf_facets.jsonl"]

    # Build map of brand → file
    brand_files = {}
    for f in files:
        brand = f.stem.replace("pdf_facets_", "")
        brand_files[brand] = f

    # Print header
    print(f"  {'brand':<10} {'expected':>9} {'have':>6} {'miss':>6} {'ok':>5} {'timeout':>8} {'no_pdf':>7} {'meta':>5} {'call':>5} {'measurement_charts':>5} {'POMs':>7} {'MB':>4}  {'recommendation'}")
    print(f"  {'-'*10} {'-'*9} {'-'*6} {'-'*6} {'-'*5} {'-'*8} {'-'*7} {'-'*5} {'-'*5} {'-'*5} {'-'*7} {'-'*4}  {'-'*40}")

    # All brands ever seen (in expected OR in files)
    all_brands = set(expected_counts.keys()) | set(brand_files.keys())
    for brand in sorted(all_brands, key=lambda x: -expected_counts.get(x, 0)):
        if expected_counts.get(brand, 0) == 0 and brand not in brand_files:
            continue  # skip empty
        if brand not in brand_files:
            r = {"error": "no file"}
            rec = recommend(brand, r)
            print(f"  {brand:<10} {expected_counts.get(brand, 0):>9} {'-':>6} {'-':>6} {'-':>5} {'-':>8} {'-':>7} {'-':>5} {'-':>5} {'-':>5} {'-':>7} {'-':>4}  {rec}")
            continue
        f = brand_files[brand]
        expected = expected_counts.get(brand, 0)
        r = audit_brand_file(f, expected)
        ok = r["statuses"].get("ok", 0)
        timeout = r["statuses"].get("timeout", 0)
        no_pdf = r["statuses"].get("no_pdf", 0)
        rec = recommend(brand, r)
        print(f"  {brand:<10} {expected:>9} {r['n_total']:>6} {r['missing']:>+6} {ok:>5} {timeout:>8} {no_pdf:>7} {r['n_meta']:>5} {r['n_callout']:>5} {r['n_mcs']:>5} {r['n_pom']:>7} {r['size_mb']:>4}  {rec}")

    print(f"\n=== Action items ===")
    for brand in sorted(all_brands, key=lambda x: -expected_counts.get(x, 0)):
        if expected_counts.get(brand, 0) == 0 and brand not in brand_files:
            continue
        if brand in brand_files:
            r = audit_brand_file(brand_files[brand], expected_counts.get(brand, 0))
            rec = recommend(brand, r)
        else:
            rec = recommend(brand, {"error": "no file"})
        if "❌" in rec or "⚠" in rec:
            print(f"  {brand}: {rec}")


if __name__ == "__main__":
    main()
