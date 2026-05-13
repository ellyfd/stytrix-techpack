"""
Audit M7_Pipeline 三大 extract 來源的真實狀態
跑法: python scripts\audit_extract_status.py
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "outputs" / "extract"

def audit_pdf():
    f = OUT / "pdf_facets.jsonl"
    if not f.exists():
        print("[!] pdf_facets.jsonl 不存在")
        return
    total = 0
    meta_ok = 0
    callout_ok = 0
    mcs_ok = 0
    pom_total = 0
    by_client = defaultdict(lambda: {"total":0, "meta":0, "construction":0, "measurement_charts":0, "poms":0})
    status = Counter()
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            status[d.get("_status", "?")] += 1
            cl = d.get("client_code", "UNKNOWN")
            by_client[cl]["total"] += 1
            if d.get("metadata"):
                meta_ok += 1
                by_client[cl]["meta"] += 1
            # 2026-05-12 rename: callouts → construction_pages
            if d.get("construction_pages") or d.get("callouts"):
                callout_ok += 1
                by_client[cl]["construction"] += 1
            if d.get("measurement_charts"):
                mcs_ok += 1
                by_client[cl]["measurement_charts"] += 1
                # count POMs
                for mc in d["measurement_charts"]:
                    rows = mc.get("rows") or mc.get("poms") or []
                    pom_total += len(rows)
                    by_client[cl]["poms"] += len(rows)
    print(f"\n=== PDF ({f.stat().st_size//1024//1024} MB) ===")
    print(f"  total entries     : {total:,}")
    print(f"  metadata 有抽到    : {meta_ok:,} ({meta_ok/max(total,1)*100:.0f}%)")
    print(f"  callouts 有抽到    : {callout_ok:,} ({callout_ok/max(total,1)*100:.0f}%)")
    print(f"  MCs 有抽到         : {mcs_ok:,} ({mcs_ok/max(total,1)*100:.0f}%)")
    print(f"  POM 結構化筆數     : {pom_total:,}")
    print(f"\n  status:")
    for s, n in status.most_common():
        print(f"    {s:<14} {n:>6}")
    print(f"\n  by client (top 15):")
    print(f"    {'client':<8} {'total':>7} {'meta':>6} {'construction':>8} {'measurement_charts':>6} {'POMs':>8}")
    for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]["total"])[:15]:
        d = by_client[cl]
        print(f"    {cl:<8} {d['total']:>7} {d['meta']:>6} {d['construction']:>8} {d['measurement_charts']:>6} {d['poms']:>8}")

def audit_pptx():
    f = OUT / "pptx_facets.jsonl"
    if not f.exists():
        print("[!] pptx_facets.jsonl 不存在")
        return
    total = 0
    callout_ok = 0
    callout_total = 0
    construction_slides = 0
    by_client = defaultdict(lambda: {"total":0, "construction":0, "callouts":0, "slides":0})
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            cl = d.get("client_code", "UNKNOWN")
            by_client[cl]["total"] += 1
            slides = d.get("n_construction_slides") or 0
            construction_slides += slides
            by_client[cl]["slides"] += slides
            # 2026-05-12 rename: PPTX callouts→constructions / PDF callouts→construction_pages
            callouts = d.get("constructions") or d.get("construction_pages") or d.get("callouts") or []
            if callouts:
                callout_ok += 1
                callout_total += len(callouts)
                by_client[cl]["construction"] += 1
                by_client[cl]["callouts"] += len(callouts)
    print(f"\n=== PPTX ({f.stat().st_size//1024//1024} MB) ===")
    print(f"  total entries          : {total:,}")
    print(f"  有 callout 的 entries   : {callout_ok:,} ({callout_ok/max(total,1)*100:.0f}%)")
    print(f"  callout 總筆數          : {callout_total:,}")
    print(f"  construction slides 合計: {construction_slides:,}")
    print(f"\n  by client (top 15):")
    print(f"    {'client':<8} {'total':>7} {'has_callout':>12} {'callouts':>10} {'slides':>8}")
    for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]["total"])[:15]:
        d = by_client[cl]
        print(f"    {cl:<8} {d['total']:>7} {d['construction']:>12} {d['callouts']:>10} {d['slides']:>8}")

def audit_xlsx():
    f = OUT / "xlsx_facets.jsonl"
    if not f.exists():
        print("[!] xlsx_facets.jsonl 不存在")
        return
    total = 0
    mc_ok = 0
    pom_total = 0
    iso_callout_ok = 0
    by_client = defaultdict(lambda: {"total":0, "mc":0, "poms":0, "iso":0})
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            cl = d.get("client_code", "UNKNOWN")
            by_client[cl]["total"] += 1
            mcs = d.get("measurement_charts") or []
            if mcs:
                mc_ok += 1
                by_client[cl]["mc"] += 1
                for mc in mcs:
                    rows = mc.get("rows") or mc.get("poms") or []
                    pom_total += len(rows)
                    by_client[cl]["poms"] += len(rows)
            if d.get("construction_iso_map"):
                iso_callout_ok += 1
                by_client[cl]["iso"] += 1
    print(f"\n=== XLSX ({f.stat().st_size//1024//1024} MB) ===")
    print(f"  total entries     : {total:,}")
    print(f"  有 MC 的 entries   : {mc_ok:,} ({mc_ok/max(total,1)*100:.0f}%)")
    print(f"  POM 結構化筆數     : {pom_total:,}")
    print(f"  有 construction_iso_map    : {iso_callout_ok:,}")
    print(f"\n  by client (top 15):")
    print(f"    {'client':<8} {'total':>7} {'mc':>5} {'POMs':>8} {'iso':>5}")
    for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]["total"])[:15]:
        d = by_client[cl]
        print(f"    {cl:<8} {d['total']:>7} {d['mc']:>5} {d['poms']:>8} {d['iso']:>5}")

if __name__ == "__main__":
    audit_pdf()
    audit_pptx()
    audit_xlsx()
