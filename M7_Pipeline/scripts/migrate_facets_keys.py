"""
Migrate 既有 facets jsonl key names → 新命名 (一次性遷移)
跑法: python scripts\migrate_facets_keys.py [--dry-run]

對齊 PIPELINE_GLOSSARY:
  PDF facets:
    "callouts" → "construction_pages"
    "callout_items" (內) → "construction_items" (內)
    "mcs" → "measurement_charts"
  PPTX facets:
    "callouts" → "constructions"
    "n_callouts" → "n_constructions"
  XLSX facets:
    "iso_callouts" → "construction_iso_map"
    "mcs" → "measurement_charts"

並把所有 png path 內的「pdf_callout_images」字串改成「pdf_construction_images」
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "extract"

PDF_PATH = OUT_DIR / "pdf_facets.jsonl"
PPTX_PATH = OUT_DIR / "pptx_facets.jsonl"
XLSX_PATH = OUT_DIR / "xlsx_facets.jsonl"


def rename_keys(d: dict, key_map: dict) -> dict:
    """Recursively rename keys in dict and nested lists/dicts."""
    if isinstance(d, dict):
        return {key_map.get(k, k): rename_keys(v, key_map) for k, v in d.items()}
    if isinstance(d, list):
        return [rename_keys(x, key_map) for x in d]
    if isinstance(d, str):
        # Update png paths
        return d.replace("pdf_callout_images", "pdf_construction_images")
    return d


def migrate_file(path: Path, key_map: dict, dry_run: bool):
    if not path.exists():
        print(f"  [skip] {path.name} 不存在")
        return
    print(f"\n[migrate] {path.name} ({path.stat().st_size//1024//1024} MB)")
    backup = path.with_suffix(path.suffix + ".pre-rename.bak")
    if not dry_run and not backup.exists():
        print(f"  [backup] → {backup.name}")
        shutil.copy2(path, backup)

    n_lines = 0
    n_renamed = 0
    if dry_run:
        # Sample first 3 lines
        with open(path, encoding="utf-8") as fin:
            for line in fin:
                d = json.loads(line)
                renamed = rename_keys(d, key_map)
                n_lines += 1
                changed = (json.dumps(d, sort_keys=True) != json.dumps(renamed, sort_keys=True))
                if changed:
                    n_renamed += 1
                if n_lines <= 1 and changed:
                    diff_keys = set(d.keys()) - set(renamed.keys())
                    new_keys = set(renamed.keys()) - set(d.keys())
                    print(f"  sample line keys removed: {diff_keys or '(內部 nested key)'}, added: {new_keys or '(內部 nested key)'}")
        print(f"  [dry] {n_lines} lines, {n_renamed} would change")
        return

    tmp = path.with_suffix(".tmp")
    with open(path, encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            n_lines += 1
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                fout.write(line)
                continue
            renamed = rename_keys(d, key_map)
            if json.dumps(d, sort_keys=True) != json.dumps(renamed, sort_keys=True):
                n_renamed += 1
            fout.write(json.dumps(renamed, ensure_ascii=False) + "\n")

    tmp.replace(path)
    print(f"  [done] {n_lines} lines, {n_renamed} renamed → {path.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只 report, 不寫檔")
    args = ap.parse_args()

    print(f"=== Facets key migration (dry_run={args.dry_run}) ===")

    # PDF facets key map
    pdf_map = {
        "callouts": "construction_pages",
        "callout_items": "construction_items",
        "mcs": "measurement_charts",
    }
    migrate_file(PDF_PATH, pdf_map, args.dry_run)

    # PPTX facets key map
    pptx_map = {
        "callouts": "constructions",
        "n_callouts": "n_constructions",
    }
    migrate_file(PPTX_PATH, pptx_map, args.dry_run)

    # XLSX facets key map
    xlsx_map = {
        "iso_callouts": "construction_iso_map",
        "mcs": "measurement_charts",
    }
    migrate_file(XLSX_PATH, xlsx_map, args.dry_run)

    # Migrate per-brand pdf_facets_*.jsonl too
    print(f"\n[per-brand PDF files]")
    for f in sorted(OUT_DIR.glob("pdf_facets_*.jsonl")):
        if f.name == "pdf_facets.jsonl":
            continue
        migrate_file(f, pdf_map, args.dry_run)

    # Rename folder pdf_callout_images → pdf_construction_images (only if not exists)
    old_folder = OUT_DIR / "pdf_callout_images"
    new_folder = OUT_DIR / "pdf_construction_images"
    if old_folder.exists() and not new_folder.exists() and not args.dry_run:
        print(f"\n[folder rename] {old_folder.name} → {new_folder.name}")
        old_folder.rename(new_folder)
    elif old_folder.exists() and new_folder.exists() and not args.dry_run:
        print(f"\n[folder] both exist — manual merge needed")
    else:
        print(f"\n[folder] no rename needed (or dry-run)")


if __name__ == "__main__":
    sys.exit(main())
