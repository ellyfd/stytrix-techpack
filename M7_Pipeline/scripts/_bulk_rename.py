"""
Bulk rename: callout/iso_callouts/mcs → 新命名
跑法: python scripts\_bulk_rename.py [--dry-run]

依 PIPELINE_GLOSSARY 對齊命名:
  callouts (PDF)    → construction_pages
  callouts (PPTX)   → constructions
  n_callouts        → n_constructions
  callout_items     → construction_items
  iso_callouts      → construction_iso_map
  mcs               → measurement_charts
  parse_callout     → parse_construction_page
  parse_mc          → parse_measurement_chart
  ptype "callout"   → "construction"
  CALLOUT_HEADER_KW → CONSTRUCTION_HEADER_KW
  CALLOUT_SOFT_KW   → CONSTRUCTION_SOFT_KW
  CALLOUT_IMG_DIR   → CONSTRUCTION_IMG_DIR
  pdf_callout_images→ pdf_construction_images
  callout_score     → construction_score
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# 順序很重要 (長詞先, 避免短詞搶 match)
RENAMES = [
    # === Variable / 函式 / 類別 ===
    ("CALLOUT_HEADER_KW", "CONSTRUCTION_HEADER_KW"),
    ("CALLOUT_SOFT_KW", "CONSTRUCTION_SOFT_KW"),
    ("CALLOUT_IMG_DIR", "CONSTRUCTION_IMG_DIR"),
    ("parse_construction_page", "parse_construction_page"),  # already correct
    ("parse_measurement_chart", "parse_measurement_chart"),  # already correct
    ("parse_callout", "parse_construction_page"),
    ("parse_mc", "parse_measurement_chart"),

    # === ptype 字串 ===
    ('"callout"', '"construction"'),
    ("'callout'", "'construction'"),

    # === Output JSON keys ===
    # PPTX: callouts (instruction-level) → constructions
    # PDF: callouts (page-level) → construction_pages
    # 這兩個不能直接 sed 因為都是「callouts」,需要 per-file 區分
    # 在每個 extract script 內手動處理 (如下 PER_FILE_RENAMES)

    # === 通用 keys ===
    ('"n_callouts"', '"n_constructions"'),
    ("'n_callouts'", "'n_constructions'"),
    ("n_callouts", "n_constructions"),
    ('"callout_items"', '"construction_items"'),
    ("'callout_items'", "'construction_items'"),
    ('"iso_callouts"', '"construction_iso_map"'),
    ("'iso_callouts'", "'construction_iso_map'"),
    ("iso_callouts", "construction_iso_map"),
    ('"mcs"', '"measurement_charts"'),
    ("'mcs'", "'measurement_charts'"),

    # === Folder 名稱 ===
    ("pdf_callout_images", "pdf_construction_images"),

    # === 中文文字 ===
    ('callout_score', 'construction_score'),
    ('callout PNGs', 'construction PNGs'),
    ('callout 件數', 'construction 件數'),
    ('"callout"', '"construction"'),

    # 一些剩餘的 callout 字眼 (但不要碰函式名/變數名)
    ('callout_dir', 'construction_dir'),
]

# Per-file 特殊處理: 這些 file 的 "callouts" 字面有特定意義
PER_FILE_RENAMES = {
    "extract_pdf_all.py": [
        # 已手動處理過 facets["callouts"]/["mcs"] 等 — 保險起見再 sweep
        ('facets["callouts"]', 'facets["construction_pages"]'),
        ('facets["mcs"]', 'facets["measurement_charts"]'),
        ('"callouts": [],', '"construction_pages": [],'),
        ('"mcs": [],', '"measurement_charts": [],'),
        ('r.get("callouts")', 'r.get("construction_pages")'),
        ('r.get("mcs")', 'r.get("measurement_charts")'),
        ('d["callouts"]', 'd["construction_pages"]'),
        ('d["mcs"]', 'd["measurement_charts"]'),
        ('by_client[cl]["callouts"]', 'by_client[cl]["construction_pages"]'),
        ('by_client[cl]["mcs"]', 'by_client[cl]["measurement_charts"]'),
        ("d['callouts']", "d['construction_pages']"),
        ("d['mcs']", "d['measurement_charts']"),
        ('metadata / callouts / mcs', 'metadata / construction_pages / measurement_charts'),
        ('callout    mcs', 'construction  measurement_charts'),
        ("{'callout':>8} {'mcs':>6}", "{'construction':>12} {'measurement_charts':>18}"),
        ("d['callouts']:>8} {d['mcs']:>6}", "d['construction_pages']:>12} {d['measurement_charts']:>18}"),
        ("callout={d['callouts']} mcs={d['mcs']}", "construction_pages={d['construction_pages']} measurement_charts={d['measurement_charts']}"),
    ],
    "extract_pptx_all.py": [
        # PPTX "callouts" = instruction-level → "constructions"
        ('"callouts":', '"constructions":'),
        ('"callouts"]', '"constructions"]'),
        ('["callouts"]', '["constructions"]'),
        ('"callouts" : ', '"constructions" : '),
        ('callouts.append', 'constructions.append'),
        ('callouts = []', 'constructions = []'),
        ('callouts = _parse_slide_callouts', 'constructions = _parse_slide_constructions'),
        ('_parse_slide_callouts', '_parse_slide_constructions'),
        ('return callouts', 'return constructions'),
        ('len(callouts)', 'len(constructions)'),
        ('all_callouts', 'all_constructions'),
        ('callouts: list[dict]', 'constructions: list[dict]'),
    ],
    "extract_xlsx_all.py": [
        # XLSX iso_callouts → construction_iso_map (already in main RENAMES)
        # XLSX mcs → measurement_charts (already in main RENAMES)
    ],
}

# Active files only (skip legacy / dev scripts)
ACTIVE_FILES = [
    "extract_pdf_all.py",
    "extract_pptx_all.py",
    "extract_xlsx_all.py",
    "page_classifier.py",
    "audit_per_brand_pdf.py",
    "audit_all_brands_summary.py",
    "deep_audit_brand.py",
    "diag_classify_pages.py",
    "diag_iso_bracket.py",
    "audit_extract_status.py",
    "audit_pptx_deep.py",
    "audit_gu_sources.py",
    "split_pdf_facets.py",
    "merge_pdf_facets.py",
    "run_pdf_all_brands.py",
]
PARSER_FILES = [
    "client_parsers/__init__.py",
    "client_parsers/_base.py",
    "client_parsers/_generic.py",
    "client_parsers/centric8.py",
    "client_parsers/dicks.py",
    "client_parsers/kohls.py",
    "client_parsers/target.py",
    "client_parsers/gerber.py",
    "client_parsers/underarmour.py",
    "client_parsers/beyondyoga.py",
    "client_parsers/gu.py",
]


def apply_renames(file_path: Path, dry_run: bool = False) -> int:
    """對單一 file 套用所有 rename. 回傳 changed line count."""
    if not file_path.exists():
        print(f"  [skip] {file_path.name} 不存在")
        return 0
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [skip] {file_path.name}: {e}")
        return 0

    original = content

    # Apply per-file specific renames first
    rel = str(file_path.relative_to(SCRIPTS)).replace("\\", "/")
    fname = file_path.name
    if fname in PER_FILE_RENAMES:
        for old, new in PER_FILE_RENAMES[fname]:
            content = content.replace(old, new)

    # Apply generic renames
    for old, new in RENAMES:
        content = content.replace(old, new)

    if content == original:
        return 0

    # Count changed lines (rough: count rename markers found)
    n_changes = sum(1 for old, _ in RENAMES if old in original) + \
                sum(1 for old, _ in PER_FILE_RENAMES.get(fname, []) if old in original)

    if not dry_run:
        file_path.write_text(content, encoding="utf-8")
    return n_changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只 report, 不寫檔")
    args = ap.parse_args()

    print(f"=== Bulk rename (dry_run={args.dry_run}) ===\n")
    total_files = 0
    total_changes = 0
    for f in ACTIVE_FILES + PARSER_FILES:
        path = SCRIPTS / f
        n = apply_renames(path, args.dry_run)
        if n > 0:
            print(f"  {'[dry]' if args.dry_run else '[edit]'} {f}: {n} renames")
            total_files += 1
            total_changes += n
    print(f"\n=== {'(would) ' if args.dry_run else ''}rename {total_changes} occurrences in {total_files} files ===")


if __name__ == "__main__":
    sys.exit(main())
