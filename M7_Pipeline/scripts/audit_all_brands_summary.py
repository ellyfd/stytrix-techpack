"""
全 brand 摘要 audit — 一張表看 42 brand 健康度
跑法: python scripts\audit_all_brands_summary.py

每 brand 一行: total / ok / no_pdf / timeout / metadata% / callout% / mcs% / POM 完整% / size MB
排序: 按 total 件數降冪
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"


def audit_brand_compact(path: Path) -> dict:
    if not path.exists():
        return {"error": "missing"}
    n_total = 0
    statuses = Counter()
    n_meta = 0
    n_callout = 0
    n_mcs = 0
    n_pom_total = 0
    n_pom_full = 0
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
            # 2026-05-12 rename: callouts → construction_pages (PDF context)
            if d.get("construction_pages") or d.get("callouts"):
                n_callout += 1
            if d.get("measurement_charts"):
                n_mcs += 1
                for mc in d["measurement_charts"]:
                    poms = mc.get("poms") or mc.get("rows") or []
                    n_pom_total += len(poms)
                    for pom in poms:
                        has_code = bool(pom.get("POM_Code") or pom.get("pom_code"))
                        has_name = bool(pom.get("POM_Name") or pom.get("pom_name"))
                        tol = pom.get("tolerance") or {}
                        has_tol = bool(tol.get("pos") or tol.get("neg"))
                        sizes_dict = pom.get("sizes") or {}
                        has_sizes = bool(sizes_dict)
                        if has_code and has_name and has_tol and has_sizes:
                            n_pom_full += 1
    return {
        "n_total": n_total,
        "ok": statuses.get("ok", 0),
        "no_pdf": statuses.get("no_pdf", 0),
        "timeout": statuses.get("timeout", 0),
        "n_meta": n_meta,
        "n_callout": n_callout,
        "n_mcs": n_mcs,
        "n_pom_total": n_pom_total,
        "n_pom_full": n_pom_full,
        "size_mb": path.stat().st_size // 1024 // 1024,
    }


def fmt_pct(n, total):
    if total == 0:
        return " — "
    return f"{n/total*100:>3.0f}%"


def main():
    files = sorted(OUT_DIR.glob("pdf_facets_*.jsonl"))
    files = [f for f in files if f.name != "pdf_facets.jsonl"]

    if not files:
        print(f"[!] {OUT_DIR} 找不到 pdf_facets_*.jsonl")
        return 1

    rows = []
    for f in files:
        brand = f.stem.replace("pdf_facets_", "")
        r = audit_brand_compact(f)
        if "error" in r:
            continue
        rows.append((brand, r))

    rows.sort(key=lambda x: -x[1]["n_total"])

    print(f"\n=== 全 brand PDF 摘要 ({len(rows)} brands, total {sum(r['n_total'] for _, r in rows):,} entries) ===\n")
    print(f"  {'brand':<10} {'total':>6} {'ok':>5} {'no_pdf':>7} {'timeout':>8} {'meta%':>6} {'cal%':>5} {'mc%':>5} {'POM_full%':>10} {'POMs':>7} {'MB':>4}")
    print(f"  {'-'*10} {'-'*6} {'-'*5} {'-'*7} {'-'*8} {'-'*6} {'-'*5} {'-'*5} {'-'*10} {'-'*7} {'-'*4}")

    # Aggregate totals
    sum_total = 0
    sum_ok = 0
    sum_no_pdf = 0
    sum_timeout = 0
    sum_meta = 0
    sum_callout = 0
    sum_mcs = 0
    sum_pom_total = 0
    sum_pom_full = 0
    sum_mb = 0

    for brand, r in rows:
        meta_pct = fmt_pct(r["n_meta"], r["n_total"])
        cal_pct = fmt_pct(r["n_callout"], r["n_total"])
        mc_pct = fmt_pct(r["n_mcs"], r["n_total"])
        pom_full_pct = fmt_pct(r["n_pom_full"], r["n_pom_total"]) if r["n_pom_total"] else "  -  "
        # Health flags
        flag = ""
        if r["n_total"] > 100:
            meta_ratio = r["n_meta"] / max(r["ok"], 1)
            if meta_ratio < 0.5:
                flag = " ⚠ meta低"
            elif r["timeout"] / max(r["n_total"], 1) > 0.10:
                flag = " ⚠ timeout高"
        print(f"  {brand:<10} {r['n_total']:>6} {r['ok']:>5} {r['no_pdf']:>7} {r['timeout']:>8} "
              f"{meta_pct:>6} {cal_pct:>5} {mc_pct:>5} {pom_full_pct:>10} "
              f"{r['n_pom_total']:>7} {r['size_mb']:>4}{flag}")
        sum_total += r["n_total"]
        sum_ok += r["ok"]
        sum_no_pdf += r["no_pdf"]
        sum_timeout += r["timeout"]
        sum_meta += r["n_meta"]
        sum_callout += r["n_callout"]
        sum_mcs += r["n_mcs"]
        sum_pom_total += r["n_pom_total"]
        sum_pom_full += r["n_pom_full"]
        sum_mb += r["size_mb"]

    print(f"  {'-'*10} {'-'*6} {'-'*5} {'-'*7} {'-'*8} {'-'*6} {'-'*5} {'-'*5} {'-'*10} {'-'*7} {'-'*4}")
    print(f"  {'TOTAL':<10} {sum_total:>6} {sum_ok:>5} {sum_no_pdf:>7} {sum_timeout:>8} "
          f"{fmt_pct(sum_meta, sum_total):>6} {fmt_pct(sum_callout, sum_total):>5} "
          f"{fmt_pct(sum_mcs, sum_total):>5} {fmt_pct(sum_pom_full, sum_pom_total):>10} "
          f"{sum_pom_total:>7} {sum_mb:>4}")

    print(f"\n=== Action items (按優先順序) ===")

    # Find brands needing attention
    high_meta_low = [(b, r) for b, r in rows if r["n_total"] > 100 and r["n_meta"] / max(r["ok"], 1) < 0.5]
    high_timeout = [(b, r) for b, r in rows if r["n_total"] > 100 and r["timeout"] / max(r["n_total"], 1) > 0.10]
    pom_struct_broken = [(b, r) for b, r in rows if r["n_pom_total"] > 100 and r["n_pom_full"] / r["n_pom_total"] < 0.95]

    if high_meta_low:
        print(f"\n  ⚠ metadata 命中 < 50% (>100 件 brand):")
        for b, r in high_meta_low:
            ratio = r["n_meta"] / max(r["ok"], 1) * 100
            print(f"     {b:<10} meta {r['n_meta']}/{r['ok']} ({ratio:.0f}%) — 需 diag layout")

    if high_timeout:
        print(f"\n  ⚠ timeout > 10% (圖像重 PDF):")
        for b, r in high_timeout:
            ratio = r["timeout"] / r["n_total"] * 100
            print(f"     {b:<10} timeout {r['timeout']}/{r['n_total']} ({ratio:.0f}%) — 可考慮加長 PER_TASK_TIMEOUT")

    if pom_struct_broken:
        print(f"\n  ⚠ POM 4 維完整度 < 95%:")
        for b, r in pom_struct_broken:
            ratio = r["n_pom_full"] / r["n_pom_total"] * 100
            print(f"     {b:<10} POM full {r['n_pom_full']}/{r['n_pom_total']} ({ratio:.0f}%)")

    # Find missing brands (in expected but no file)
    print()


if __name__ == "__main__":
    main()
