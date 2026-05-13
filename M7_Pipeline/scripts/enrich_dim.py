"""enrich_dim.py — 用 style# JOIN 客戶端 PDF + MK 端 nt-net2 metadata

把三個來源整合成 unified per-design dim record：
  1. designs.jsonl       (M7 索引衍生：client/design_id/eidh/wk/item/subgroup/program)
  2. pdf_metadata.jsonl  (客戶端 PDF cover：season/brand_division/dept/BOM/vendor)
  3. m7_report.jsonl     (聚陽端 nt-net2：total_amount/total_ie/machines/flags/five_level)

JOIN 邏輯：
  - 主表：designs.jsonl（一 design 一行）
  - LEFT JOIN pdf_metadata by (client, design_id)
  - LEFT JOIN m7_report by style_no（== design_id）
  - 同 design_id 多 EIDH → makalot_side 帶 latest 那筆 + aggregate

輸出：
  data/ingest/metadata/dim_enriched.jsonl
    {
      "design_id": "...",
      "client": "...",
      "all_eidhs": [...],
      "client_side": {...},   # PDF metadata
      "makalot_side": {...},  # nt-net2 latest + aggregates
    }

用法：python scripts\\enrich_dim.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
DESIGNS_JSONL = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
PDF_METADATA = DL / "data" / "ingest" / "metadata" / "pdf_metadata.jsonl"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
OUT = DL / "data" / "ingest" / "metadata" / "dim_enriched.jsonl"


def to_float(v):
    """強制 parse 數字，剝掉 USD$ / /dz / 中文 / 空白 / 逗號"""
    if v is None:
        return None
    import re
    s = str(v)
    # 抽第一個出現的數字（含小數點）
    m = re.search(r'(-?\d+\.?\d*)', s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def aggregate_makalot(reports):
    """同 design 跨 EIDH 的 nt-net2 報告 → aggregate"""
    if not reports:
        return None
    # 取 latest（analyst_date 最新）作為 representative
    reports_sorted = sorted(reports, key=lambda r: r.get("analyst_date", ""), reverse=True)
    latest = reports_sorted[0]

    # 跨 EIDH aggregate
    usd_dzs = [to_float(r.get("total_amount_usd_dz")) for r in reports]
    usd_dzs = [v for v in usd_dzs if v is not None and v > 0]
    total_ies = [to_float(r.get("total_ie")) for r in reports]
    total_ies = [v for v in total_ies if v is not None and v > 0]
    total_times = [to_float(r.get("total_time")) for r in reports]
    total_times = [v for v in total_times if v is not None and v > 0]

    # Flags 取「任一 EIDH 出現過 True」
    flag_any = {}
    for r in reports:
        for k, v in (r.get("flags") or {}).items():
            if v:
                flag_any[k] = True

    # Machines 聯集（dedup by name）
    high_machines = {}
    custom_machines = {}
    for r in reports:
        for m in r.get("high_machines", []) or []:
            name = m.get("machine", "").strip()
            if name and name not in ("設備名稱(Machine Name)", ""):
                high_machines[name] = m
        for m in r.get("custom_machines", []) or []:
            name = m.get("machine", "").strip()
            if name and name not in ("設備名稱(Machine Name)", ""):
                custom_machines[name] = m

    return {
        "all_eidhs": [r.get("eidh") for r in reports],
        "n_eidhs": len(reports),
        # 直接從 latest 帶
        "company": latest.get("company"),
        "customer": latest.get("customer"),
        "follow": latest.get("follow"),
        "style_no": latest.get("style_no"),
        "index_no": latest.get("index_no"),
        "item": latest.get("item"),
        "wk": latest.get("wk"),
        "fabric_name": latest.get("fabric_name"),
        "fabric_ingredients": latest.get("fabric_ingredients"),
        "evaluation_type": latest.get("evaluation_type"),
        "origin": latest.get("origin"),
        "quantity_dz": to_float(latest.get("quantity_dz")),
        "analyst_creator": latest.get("analyst_creator"),
        "analyst_date_latest": latest.get("analyst_date"),
        "reviewer": latest.get("reviewer"),
        # 跨 EIDH aggregate
        "avg_total_amount_usd_dz": round(mean(usd_dzs), 3) if usd_dzs else None,
        "min_total_amount_usd_dz": min(usd_dzs) if usd_dzs else None,
        "max_total_amount_usd_dz": max(usd_dzs) if usd_dzs else None,
        "avg_total_ie": round(mean(total_ies), 2) if total_ies else None,
        "avg_total_time": round(mean(total_times), 1) if total_times else None,
        "high_machines": list(high_machines.values()),
        "custom_machines": list(custom_machines.values()),
        "flags_any": flag_any,
        # Latest 五階展開（簡化：只取最新那筆，跨 EIDH 不 merge 因工序差異大）
        "five_level_detail_latest": latest.get("five_level_detail", []),
    }


def main():
    if not DESIGNS_JSONL.exists():
        print(f"[!] {DESIGNS_JSONL} 不存在")
        sys.exit(1)

    # 1. Load designs.jsonl 主表
    designs = []
    for line in open(DESIGNS_JSONL, encoding="utf-8"):
        designs.append(json.loads(line))
    print(f"[load] designs.jsonl: {len(designs)} entries")

    # 2. Load pdf_metadata.jsonl by (client, design_id)
    pdf_idx = {}
    if PDF_METADATA.exists():
        for line in open(PDF_METADATA, encoding="utf-8"):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (d.get("client", ""), d.get("design_id", ""))
            pdf_idx[key] = d
        print(f"[load] pdf_metadata.jsonl: {len(pdf_idx)} entries")
    else:
        print(f"[skip] pdf_metadata.jsonl not found")

    # 3. Load m7_report.jsonl by style_no（多 EIDH 同 style → list）
    m7_by_style = defaultdict(list)
    if M7_REPORT.exists():
        n_loaded = 0
        for line in open(M7_REPORT, encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            style = (r.get("style_no") or "").strip()
            if style and style not in ("Style", ""):  # 跳過 placeholder
                m7_by_style[style].append(r)
                n_loaded += 1
        print(f"[load] m7_report.jsonl: {n_loaded} reports → {len(m7_by_style)} unique style#")
    else:
        print(f"[skip] m7_report.jsonl not found（先跑 fetch_m7_report_playwright.py）")

    # 4. JOIN
    n_with_pdf = n_with_mk = n_with_both = 0
    enriched = []
    for d in designs:
        client = d.get("client", "")
        design_id = d.get("design_id", "")
        eidh = d.get("eidh")

        # client_side from designs.jsonl + pdf_metadata
        pdf = pdf_idx.get((client, design_id), {})
        if pdf:
            n_with_pdf += 1
        client_side = {
            # designs.jsonl 帶
            "subgroup": d.get("subgroup"),
            "program": d.get("program"),
            "wk": d.get("wk"),
            "item": d.get("item"),
            # pdf_metadata 帶
            "season": pdf.get("season"),
            "brand_division": pdf.get("brand_division"),
            "department": pdf.get("department"),
            "collection": pdf.get("collection"),
            "category": pdf.get("category"),
            "bom_number": pdf.get("bom_number"),
            "status": pdf.get("status"),
            "flow": pdf.get("flow"),
            "vendor": pdf.get("vendor"),
            "gender_pdf": pdf.get("gender_pdf"),
            # DICKS 專屬
            "brand": pdf.get("brand"),
            "style_number": pdf.get("style_number"),
            "style_description": pdf.get("style_description"),
            "size_range": pdf.get("size_range"),
            "product_status": pdf.get("product_status"),
            "tech_pack_type": pdf.get("tech_pack_type"),
        }

        # makalot_side from m7_report by style_no（== design_id）
        mk_reports = m7_by_style.get(design_id, [])
        if mk_reports:
            n_with_mk += 1
            if pdf:
                n_with_both += 1
        makalot_side = aggregate_makalot(mk_reports)

        enriched.append({
            "design_id": design_id,
            "client": client,
            "primary_eidh": eidh,
            "all_eidhs": (makalot_side or {}).get("all_eidhs") or ([eidh] if eidh else []),
            "client_side": {k: v for k, v in client_side.items() if v},
            "makalot_side": makalot_side,
        })

    # 5. 寫 output
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for e in enriched:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 6. summary
    print(f"\n=== Enriched dim summary ===")
    print(f"  total designs:         {len(enriched)}")
    print(f"  with PDF metadata:     {n_with_pdf}  ({n_with_pdf/len(enriched)*100:.1f}%)")
    print(f"  with MK m7_report:     {n_with_mk}   ({n_with_mk/len(enriched)*100:.1f}%)")
    print(f"  with both:             {n_with_both} ({n_with_both/len(enriched)*100:.1f}%)")
    print(f"\n[output] {OUT}")
    print(f"\n[next] platform adapter v2 可用 dim_enriched.jsonl 取代 designs.jsonl")


if __name__ == "__main__":
    main()
