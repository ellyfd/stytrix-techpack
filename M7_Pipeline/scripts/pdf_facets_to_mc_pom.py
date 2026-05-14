"""pdf_facets_to_mc_pom.py — Phase 2 adapter: pdf_facets/xlsx_facets → mc_pom_*.jsonl

Pipeline B (pom_rules) 的 rebuild_profiles.py 讀 `$BASE/_parsed/mc_pom_*.jsonl`,
schema 跟 M7 Pipeline 的 pdf_facets.jsonl 不同 (但 poms[] 內層欄位完全一樣).

這個 adapter 把 pdf_facets + xlsx_facets 內所有「有 POM」的 entry 轉成
mc_pom 格式, 讓 Pipeline B 能吃到今天救出的 591K POMs (5 brand rescue).

mc_pom schema (rebuild_profiles.py 期待):
  {
    "design_number": str,
    "brand_division": str,    # 內含 gender hint, extract_gender() 會 parse
    "department": str,
    "item_type": str,
    "category": str,
    "design_type": str,
    "description": str,
    "mcs": [ {body_type, sizes:[...], poms:[{POM_Code,POM_Name,sizes,tolerance}]} ]
  }

pdf_facets schema:
  {eidh, client_code, design_id, metadata:{...}, measurement_charts:[{sizes,poms}], ...}

跑法:
  python scripts/pdf_facets_to_mc_pom.py [--out PATH] [--brands ONY GAP ...]

預設 --out = outputs/platform/mc_pom_v11.jsonl
跑完手動 copy 到 $POM_PIPELINE_BASE/_parsed/ 再跑 Pipeline B Step 2-6.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT_DIR = ROOT / "outputs" / "extract"
PDF_FACETS = EXTRACT_DIR / "pdf_facets.jsonl"
XLSX_FACETS = EXTRACT_DIR / "xlsx_facets.jsonl"
MANIFEST_CSV = ROOT / "m7_organized_v2" / "_fetch_manifest.csv"

# 2026-05-14 Elly: garment type 只能在聚陽有的項目裡 — 所有品牌的 GT 都要對映到
# M7 manifest 的 Item 欄 (聚陽自己的款式分類, 32 個 canonical 值). 不再讓各 brand
# 用自己的 description / item_type 各自亂猜 GT (DKS/KOH/UA 根本沒 item_type → 45% UNKNOWN).
# 這支 adapter 只負責用 EIDH 反查 manifest, 把 Item 帶進 mc_pom record 的 manifest_item 欄;
# 真正的 Item → GT bucket 對映在 stytrix-techpack/scripts/core/reclassify_and_rebuild.py
# 的 MANIFEST_ITEM_TO_GT 表 (聚陽 32 款式 → 9 GT bucket).
_MANIFEST_ITEM = {}  # eidh(str) -> Item(str), 聚陽 canonical 款式類型


def load_manifest_items():
    """讀 M7 manifest CSV, 建 eidh → Item 對照. Item 是聚陽自己的款式分類."""
    if not MANIFEST_CSV.exists():
        print(f"[!] manifest 不存在: {MANIFEST_CSV}")
        print("    manifest_item 會全空, 下游 GT 分類 fallback 關鍵字邏輯")
        return
    import csv
    with open(MANIFEST_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            eidh = str(row.get("Eidh", "")).strip()
            item = (row.get("Item", "") or "").strip()
            if eidh and item:
                _MANIFEST_ITEM[eidh] = item
    print(f"[manifest] {len(_MANIFEST_ITEM):,} eidh→Item 對照載入 ({MANIFEST_CSV.name})")

# 2026-05-13 Elly: 小量混入的 dev / 雜項 brand 不進 pom_rules
# (V2 DEV / V5 DEV = 內部開發線, JF/ROSS/ZAR = 雜項小客戶, 各 1-3 designs)
# pom_rules 是通用尺寸規則庫, 小量雜訊 brand 會污染 bucket 統計
DROP_BRANDS = {"V2 DEV", "V5 DEV", "V7 DEV", "S1 DEV", "JF", "ROSS", "ZAR",
               "HLA", "DST", "ASICS", "GILDAN", "BUSINE", "CLUB M",
               "CARTER", "CATAPU", "AEOM", "QUINCE"}  # QUINCE → QCE 才對, 排重複碼


def _inject_gender(brand_division: str, metadata: dict) -> str:
    """rebuild_profiles.py 的 extract_gender() 只 parse brand_division/department 字串.
    非 Centric 8 brand (UA/DKS/KOH/TGT) 的 gender 在獨立 metadata 欄位,
    這裡把它塞進 brand_division 末尾讓 extract_gender 抓得到.
    """
    bd = brand_division or ""
    bd_upper = bd.upper()
    # 若 brand_division 已含 gender token, 不動
    for g in ("GIRLS", "BOYS", "WOMENS", "MENS", "MATERNITY", "BABY", "TODDLER"):
        if g in bd_upper:
            return bd
    # 從 metadata 找 explicit gender
    g = (metadata.get("gender") or metadata.get("gender_inferred")
         or metadata.get("gender_raw") or "").upper().strip()
    # normalize 常見變體
    g_map = {
        "WOMEN": "WOMENS", "WOMEN'S": "WOMENS", "FEMALE": "WOMENS",
        "MEN": "MENS", "MEN'S": "MENS", "MALE": "MENS",
        "GIRL": "GIRLS", "BOY": "BOYS",
        "KIDS": "", "YOUTH": "", "UNISEX": "",  # 無法判性別的留空
    }
    g = g_map.get(g, g)
    if g in ("GIRLS", "BOYS", "WOMENS", "MENS", "MATERNITY"):
        return f"{bd} {g}".strip()
    # class_raw 例如 "1:BOYS PAJAMAS" — TGT 用
    class_raw = (metadata.get("class_raw") or "").upper()
    for gtok in ("GIRLS", "BOYS", "WOMENS", "MENS"):
        if gtok in class_raw:
            return f"{bd} {gtok}".strip()
    return bd


def _convert_entry(e: dict) -> dict | None:
    """pdf_facets / xlsx_facets entry → mc_pom record. 無 POM 回 None."""
    mcs_in = e.get("measurement_charts") or []
    # 只收真的有 poms 的 mc
    mcs_out = []
    for mc in mcs_in:
        poms = mc.get("poms") or []
        if not poms:
            continue
        mcs_out.append({
            "body_type": mc.get("body_type", "") or mc.get("base_size", ""),
            "sizes": mc.get("sizes") or [],
            "poms": poms,   # POM_Code/POM_Name/sizes/tolerance 欄位完全一樣, 直接帶
        })
    if not mcs_out:
        return None

    meta = e.get("metadata") or {}
    brand_division = meta.get("brand_division") or e.get("client_raw") or e.get("client_code") or ""
    brand_division = _inject_gender(brand_division, meta)

    eidh = str(e.get("eidh", "")).strip()
    return {
        "design_number": (meta.get("design_number") or e.get("design_id") or "").strip(),
        "brand_division": brand_division,
        "department": meta.get("department") or meta.get("department_raw") or "",
        "item_type": meta.get("item_type") or "",
        # 2026-05-14: manifest_item = 聚陽 canonical 款式 (EIDH 反查 _fetch_manifest.csv).
        # 下游 reclassify_and_rebuild.py 的 real_gt_v2 優先吃這欄定 GT bucket;
        # 沒對到 (EIDH 不在 manifest) 才 fallback 到 item_type/description 關鍵字.
        "manifest_item": _MANIFEST_ITEM.get(eidh, ""),
        "category": (meta.get("bom_category") or meta.get("sub_category")
                     or meta.get("class_raw") or meta.get("category") or ""),
        "design_type": meta.get("design_type") or "",
        "description": meta.get("description") or "",
        "mcs": mcs_out,
        # audit trail
        "_eidh": eidh,
        "_client_code": e.get("client_code", ""),
        "_source": "pdf_facets" if "_source_pdf" in str(mcs_in) else "facets",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs" / "platform" / "mc_pom_v11.jsonl"))
    ap.add_argument("--brands", nargs="*", default=None,
                    help="只轉特定 brand code (預設全部有 POM 的)")
    ap.add_argument("--include-xlsx", action="store_true",
                    help="也轉 xlsx_facets (SAN/WMT/QCE/NET POM)")
    args = ap.parse_args()

    load_manifest_items()

    target_brands = set(b.upper() for b in args.brands) if args.brands else None
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sources = [("pdf_facets", PDF_FACETS)]
    if args.include_xlsx:
        sources.append(("xlsx_facets", XLSX_FACETS))

    n_in = 0
    n_with_pom = 0
    n_written = 0
    n_dropped = 0
    n_manifest_hit = 0
    by_brand = {}
    pom_total = 0

    with open(out_path, "w", encoding="utf-8") as fout:
        for src_name, src_path in sources:
            if not src_path.exists():
                print(f"[!] {src_path} 不存在, skip")
                continue
            print(f"[read] {src_path.name}")
            with open(src_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    n_in += 1
                    cl = e.get("client_code", "?")
                    if target_brands and cl not in target_brands:
                        continue
                    if cl in DROP_BRANDS:
                        n_dropped += 1
                        continue
                    rec = _convert_entry(e)
                    if rec is None:
                        continue
                    n_with_pom += 1
                    rec["_source"] = src_name
                    if rec.get("manifest_item"):
                        n_manifest_hit += 1
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_written += 1
                    b = by_brand.setdefault(cl, {"designs": 0, "poms": 0})
                    b["designs"] += 1
                    b["poms"] += sum(len(mc["poms"]) for mc in rec["mcs"])
                    pom_total += sum(len(mc["poms"]) for mc in rec["mcs"])

    _mh_pct = (100.0 * n_manifest_hit / n_written) if n_written else 0.0
    print()
    print(f"=== Adapter Summary ===")
    print(f"  Entries scanned:      {n_in:,}")
    print(f"  Dropped (DROP_BRANDS): {n_dropped:,}")
    print(f"  Entries with POM:     {n_with_pom:,}")
    print(f"  Written to mc_pom:    {n_written:,}")
    print(f"  manifest_item 對到:   {n_manifest_hit:,} ({_mh_pct:.1f}%)  ← GT 走聚陽 meta")
    print(f"  Total POMs:           {pom_total:,}")
    print()
    print(f"  Per-brand:")
    for cl in sorted(by_brand, key=lambda c: -by_brand[c]["poms"]):
        b = by_brand[cl]
        print(f"    {cl:<8} {b['designs']:>5} designs / {b['poms']:>7,} POMs")
    print()
    print(f"  [write] {out_path}")
    print()
    print(f"=== Next step (Pipeline B) ===")
    print(f"  1. copy {out_path.name} → $POM_PIPELINE_BASE/_parsed/")
    print(f"  2. cd stytrix-techpack")
    print(f"  3. python scripts/core/rebuild_profiles.py        # Step 2 → measurement_profiles_union.json")
    print(f"  4. python scripts/core/reclassify_and_rebuild.py  # Step 3 → pom_rules/*.json")
    print(f"  5. python scripts/core/rebuild_all_analysis_v2.py # Step 4")
    print(f"  6. python scripts/core/rebuild_grading_3d.py      # Step 5")
    print(f"  7. python scripts/core/fix_sort_order.py          # Step 6")
    print(f"  8. git add pom_rules/ + commit + push → workflow auto-trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
