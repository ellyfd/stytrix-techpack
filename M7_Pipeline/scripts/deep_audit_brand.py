"""
Per-brand deep audit — 抽樣 + 結構分析, 看資料乾不乾淨
跑法: python scripts\deep_audit_brand.py GAP GU
     python scripts\deep_audit_brand.py ALL    (跑所有 per-brand 檔)
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"


def audit_one(path: Path):
    brand = path.stem.replace("pdf_facets_", "")
    print(f"\n{'='*70}")
    print(f"=== {brand}  ({path.name}, {path.stat().st_size//1024//1024} MB)")
    print(f"{'='*70}")

    n_total = 0
    statuses = Counter()
    n_with_meta = 0
    n_with_callout = 0
    n_with_mcs = 0

    callout_counts = []
    mc_counts = []
    pom_counts = []

    # 真實 schema: metadata 是 PDF 解析的 cover 欄位 (per brand 不同)
    # MC poms[i] 是 dict: {POM_Code, POM_Name, tolerance:{neg,pos}, sizes:{XXS,XS,S,...}}
    meta_field_coverage = Counter()  # 動態收集所有見過的 metadata key
    pom_field_coverage = Counter()   # 動態收集所有見過的 POM key
    mc_field_coverage = Counter()    # MC top-level key

    n_pom_total = 0
    n_pom_with_code = 0
    n_pom_with_name = 0
    n_pom_with_tol = 0
    n_pom_with_sizes = 0
    n_pom_with_full_data = 0  # all 4: code+name+tol+sizes

    sizes_seen = Counter()  # 哪些 size 出現最多
    pom_codes_seen = Counter()

    sample_no_meta = []
    sample_weird = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_total += 1
            statuses[d.get("_status", "?")] += 1

            # metadata — 動態收集 keys (per-brand 不同)
            meta = d.get("metadata") or {}
            if meta:
                n_with_meta += 1
                for k, v in meta.items():
                    if v:  # 非空才算
                        meta_field_coverage[k] += 1

            # callouts
            # 2026-05-12 rename: PDF callouts→construction_pages / PPTX→constructions
            callouts = d.get("construction_pages") or d.get("constructions") or d.get("callouts") or []
            if callouts:
                n_with_callout += 1
                callout_counts.append(len(callouts))

            # mcs (POM tables)
            mcs = d.get("measurement_charts") or []
            if mcs:
                n_with_mcs += 1
                mc_counts.append(len(mcs))
                local_pom = 0
                for mc in mcs:
                    for k in mc.keys():
                        mc_field_coverage[k] += 1
                    poms = mc.get("poms") or mc.get("rows") or []
                    local_pom += len(poms)
                    n_pom_total += len(poms)
                    for pom in poms:
                        for k in pom.keys():
                            pom_field_coverage[k] += 1
                        has_code = bool(pom.get("POM_Code") or pom.get("pom_code"))
                        has_name = bool(pom.get("POM_Name") or pom.get("pom_name"))
                        tol = pom.get("tolerance") or {}
                        has_tol = bool(tol.get("pos") or tol.get("neg") or pom.get("tol_plus") or pom.get("tol_minus"))
                        sizes_dict = pom.get("sizes") or {}
                        has_sizes = bool(sizes_dict)
                        if has_code: n_pom_with_code += 1
                        if has_name: n_pom_with_name += 1
                        if has_tol: n_pom_with_tol += 1
                        if has_sizes: n_pom_with_sizes += 1
                        if has_code and has_name and has_tol and has_sizes:
                            n_pom_with_full_data += 1
                        for sz, val in sizes_dict.items():
                            if val:
                                sizes_seen[sz] += 1
                        if has_code:
                            pom_codes_seen[pom.get("POM_Code") or pom.get("pom_code")] += 1
                pom_counts.append(local_pom)

            # 識別「純圖 PDF / PPT 主源」EIDH — 不算 PDF parser 的 false negative
            # 例如: *樣品室作工敘述.pdf / *繡畫圖.pdf / 純色卡 BOM 表
            source_files = d.get("source_files") or []
            is_image_only_pdf = any(
                "樣品室作工敘述" in f or "繡畫圖" in f or "色卡" in f or
                "VDD" in f or "PAKS" in f
                for f in source_files
            )

            if d.get("_status") == "ok" and not meta and not is_image_only_pdf:
                if len(sample_no_meta) < 5:
                    sample_no_meta.append(d.get("eidh"))

            if d.get("_status") == "ok" and not callouts and not mcs and not meta and not is_image_only_pdf:
                if len(sample_weird) < 5:
                    sample_weird.append(d.get("eidh"))

    # ════════════════════════════════════════════════════════════
    # Print results
    # ════════════════════════════════════════════════════════════

    print(f"\n## 整體 ({n_total:,} entries)")
    for s, n in statuses.most_common():
        pct = n / max(n_total, 1) * 100
        print(f"  {s:<14} {n:>5} ({pct:>4.0f}%)")

    print(f"\n## Metadata coverage (從 PDF cover sheet 抽取的欄位, per-brand 不同)")
    print(f"  has metadata           : {n_with_meta:,} ({n_with_meta/max(n_total,1)*100:.0f}%)")
    if meta_field_coverage:
        print(f"  ─ 各欄位命中率 (top 12, 分母 = has_metadata):")
        for k, n in meta_field_coverage.most_common(12):
            pct = n / max(n_with_meta, 1) * 100
            bar = "█" * int(pct / 5)
            print(f"     {k:<20} {n:>5} ({pct:>3.0f}%) {bar}")

    print(f"\n## Callouts")
    print(f"  has >=1 callout        : {n_with_callout:,} ({n_with_callout/max(n_total,1)*100:.0f}%)")
    if callout_counts:
        avg = sum(callout_counts) / len(callout_counts)
        print(f"  總 construction 件數          : {sum(callout_counts):,}")
        print(f"  per-design avg / max     : {avg:.1f} / {max(callout_counts)}")

    print(f"\n## MC POM tables")
    print(f"  has >=1 MC sheet         : {n_with_mcs:,} ({n_with_mcs/max(n_total,1)*100:.0f}%)")
    if mc_counts:
        avg_mc = sum(mc_counts) / len(mc_counts)
        print(f"  per-design MC avg / max  : {avg_mc:.1f} / {max(mc_counts)}")
    if mc_field_coverage:
        print(f"  ─ MC top-level 欄位 (top 8):")
        for k, n in mc_field_coverage.most_common(8):
            print(f"     {k:<20} {n:>5}")
    print(f"")
    print(f"  總 POM 行數               : {n_pom_total:,}")
    if n_pom_total > 0:
        print(f"  POM 含 POM_Code           : {n_pom_with_code:,} ({n_pom_with_code/n_pom_total*100:.0f}%)")
        print(f"  POM 含 POM_Name           : {n_pom_with_name:,} ({n_pom_with_name/n_pom_total*100:.0f}%)")
        print(f"  POM 含 tolerance{{neg/pos}}: {n_pom_with_tol:,} ({n_pom_with_tol/n_pom_total*100:.0f}%)")
        print(f"  POM 含 sizes dict         : {n_pom_with_sizes:,} ({n_pom_with_sizes/n_pom_total*100:.0f}%)")
        print(f"  ✅ POM 4 維全齊 (完整 row): {n_pom_with_full_data:,} ({n_pom_with_full_data/n_pom_total*100:.0f}%)")
    if pom_field_coverage:
        print(f"\n  ─ POM row 欄位 frequency (top 8):")
        for k, n in pom_field_coverage.most_common(8):
            print(f"     {k:<20} {n:>6}")
    if sizes_seen:
        print(f"\n  ─ 出現最多的 size (top 12):")
        for sz, n in sizes_seen.most_common(12):
            print(f"     {sz:<10} {n:>6}")
    if pom_codes_seen:
        print(f"\n  ─ 最常出現的 POM_Code (top 10):")
        for code, n in pom_codes_seen.most_common(10):
            print(f"     {code:<12} {n:>5}")

    # Issues
    print(f"\n## 異常樣本")
    if sample_no_meta:
        print(f"  ❗ ok 但無 metadata: {len(sample_no_meta)} 件 (sample EIDH):")
        for eidh in sample_no_meta:
            print(f"     - {eidh}")
    if sample_weird:
        print(f"  ❗ ok 但 callout/mcs/meta 全空: (sample EIDH):")
        for eidh in sample_weird:
            print(f"     - {eidh}")
    if not sample_no_meta and not sample_weird:
        print(f"  ✅ 沒發現異常樣本")


def main():
    args = sys.argv[1:]
    if not args:
        print("用法: python scripts\\deep_audit_brand.py BRAND [BRAND ...]")
        print("     python scripts\\deep_audit_brand.py ALL")
        return 1

    if args[0] == "ALL":
        files = sorted(OUT_DIR.glob("pdf_facets_*.jsonl"))
        files = [f for f in files if f.name != "pdf_facets.jsonl"]
    else:
        files = []
        for brand in args:
            f = OUT_DIR / f"pdf_facets_{brand}.jsonl"
            if not f.exists():
                print(f"[!] {f} 不存在")
                continue
            files.append(f)

    for f in files:
        audit_one(f)

    print(f"\n\n{'='*70}")
    print(f"=== 全部 audit 完成 ===")
    print(f"{'='*70}")


if __name__ == "__main__":
    sys.exit(main())
