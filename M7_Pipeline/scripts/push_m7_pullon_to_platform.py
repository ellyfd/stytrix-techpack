"""push_m7_pullon_to_platform.py — 把 m7_pullon designs/source 推到 stytrix-techpack repo

Source:
  outputs/platform/m7_pullon_designs.jsonl  (per-EIDH 履歷,3900 件 / 77 MB)
  outputs/platform/m7_pullon_source.jsonl   (aggregated by 6-dim key,746 件 / 7 MB)

Target:
  C:\\temp\\stytrix-techpack\\data\\ingest\\m7_pullon\\designs.jsonl.gz   (gzip)
  C:\\temp\\stytrix-techpack\\data\\ingest\\m7_pullon\\entries.jsonl       (uncompressed,沿襲既有檔名)

跑:python scripts/push_m7_pullon_to_platform.py [--dry-run]
"""
from __future__ import annotations
import argparse
import gzip
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SRC_DESIGNS = ROOT / "outputs" / "platform" / "m7_designs.jsonl"   # 2026-05-11 改名: m7_pullon → m7
SRC_SOURCE = ROOT / "outputs" / "platform" / "m7_source.jsonl"

TARGET_DIR = Path(r"C:\temp\stytrix-techpack\data\ingest\m7")       # 2026-05-11 改名
DST_DESIGNS = TARGET_DIR / "designs.jsonl.gz"
DST_SOURCE = TARGET_DIR / "entries.jsonl"


def fmt_size(p: Path) -> str:
    if not p.exists():
        return "(missing)"
    sz = p.stat().st_size
    if sz > 1024 * 1024:
        return f"{sz / 1024 / 1024:.1f} MB"
    return f"{sz / 1024:.1f} KB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只列 source/dst 不實際 copy")
    args = ap.parse_args()

    print(f"=== Push m7_pullon to stytrix-techpack ===\n")

    # === Sanity check ===
    if not SRC_DESIGNS.exists():
        print(f"[FAIL] {SRC_DESIGNS} 不存在,先跑 build_m7_pullon_source_v3.py", file=sys.stderr)
        return 1
    if not SRC_SOURCE.exists():
        print(f"[FAIL] {SRC_SOURCE} 不存在,先跑 build_m7_pullon_source_v3.py", file=sys.stderr)
        return 1
    if not TARGET_DIR.exists():
        print(f"[FAIL] {TARGET_DIR} 不存在,確認 stytrix-techpack repo 路徑", file=sys.stderr)
        return 1

    # === Show plan ===
    print(f"[1] designs.jsonl (per-EIDH 履歷)")
    print(f"    SRC: {SRC_DESIGNS} ({fmt_size(SRC_DESIGNS)})")
    print(f"    DST: {DST_DESIGNS} (will gzip)")
    print(f"    舊檔: {fmt_size(DST_DESIGNS)}")

    print(f"\n[2] source.jsonl → entries.jsonl (aggregated)")
    print(f"    SRC: {SRC_SOURCE} ({fmt_size(SRC_SOURCE)})")
    print(f"    DST: {DST_SOURCE}")
    print(f"    舊檔: {fmt_size(DST_SOURCE)}")

    if args.dry_run:
        print(f"\n[dry-run] 不實際 copy。改用 `python scripts/push_m7_pullon_to_platform.py` 推。")
        return 0

    # === Copy 1: gzip designs.jsonl ===
    print(f"\n[copy 1] gzip {SRC_DESIGNS.name} → {DST_DESIGNS.name}")
    with open(SRC_DESIGNS, "rb") as fin:
        with gzip.open(DST_DESIGNS, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    print(f"    OK — {fmt_size(DST_DESIGNS)}")

    # === Copy 2: 直接 copy source.jsonl → entries.jsonl ===
    print(f"\n[copy 2] copy {SRC_SOURCE.name} → {DST_SOURCE.name}")
    shutil.copy2(SRC_SOURCE, DST_SOURCE)
    print(f"    OK — {fmt_size(DST_SOURCE)}")

    print(f"\n=== Done ===")
    print(f"記得到 stytrix-techpack repo 跑:")
    print(f"  cd C:\\temp\\stytrix-techpack")
    print(f"  python star_schema/scripts/build_recipes_master.py  # 確認新 m7_pullon source 進得去")
    print(f"  git status  # 看 data/ingest/m7_pullon/ 變更")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
