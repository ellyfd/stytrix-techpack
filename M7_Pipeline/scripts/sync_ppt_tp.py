"""sync_ppt_tp.py — 把 tp_samples_v2/ 的 PPT 同步到 m7_organized_v2/ppt_tp/

修 3_reorganize.py 偶爾漏 copy 的 bug。比對兩邊：
  - 來源：tp_samples_v2/{eidh}_{design_id}/*.ppt[x]
  - 目標：m7_organized_v2/ppt_tp/{eidh}_*  (扁平命名)

策略：來源有但目標沒有的 EIDH → copy 過去（命名加 eidh prefix）

用法：
  python scripts\\sync_ppt_tp.py [--dry-run]

跑完重跑 audit_ppt_coverage.py 確認 cover 提升。
"""
from __future__ import annotations
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TP_SAMPLES = ROOT / "tp_samples_v2"
PPT_FLAT = ROOT / "m7_organized_v2" / "ppt_tp"
EIDH_RE = re.compile(r"^(\d{6})")


def collect_eidh_from_flat() -> set[int]:
    out = set()
    if not PPT_FLAT.exists():
        return out
    for f in PPT_FLAT.iterdir():
        if f.is_file() and f.suffix.lower() in (".ppt", ".pptx"):
            m = EIDH_RE.match(f.name)
            if m:
                out.add(int(m.group(1)))
    return out


def collect_ppt_from_samples() -> dict[int, list[Path]]:
    """tp_samples_v2/{eidh}_X/*.ppt[x] → {eidh: [files]}"""
    out: dict[int, list[Path]] = {}
    if not TP_SAMPLES.exists():
        return out
    for sub in TP_SAMPLES.iterdir():
        if not sub.is_dir():
            continue
        m = EIDH_RE.match(sub.name)
        if not m:
            continue
        eidh = int(m.group(1))
        ppts = [p for p in sub.iterdir()
                if p.is_file() and p.suffix.lower() in (".ppt", ".pptx")]
        if ppts:
            out[eidh] = ppts
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    print(f"[1] scan {PPT_FLAT}")
    flat_eidh = collect_eidh_from_flat()
    print(f"    {len(flat_eidh)} EIDH already in ppt_tp/")

    print(f"\n[2] scan {TP_SAMPLES}")
    samples = collect_ppt_from_samples()
    print(f"    {len(samples)} EIDH have PPT in tp_samples_v2/")

    print(f"\n[3] cross-check — find missing in ppt_tp/")
    missing = sorted(set(samples.keys()) - flat_eidh)
    print(f"    {len(missing)} EIDH have PPT in samples but not in ppt_tp")

    if not missing:
        print(f"\n[done] 沒缺漏，不用同步")
        return

    n_copied = n_skipped = n_err = 0
    PPT_FLAT.mkdir(parents=True, exist_ok=True)

    for eidh in missing:
        ppts = samples[eidh]
        print(f"\n  EIDH={eidh}: {len(ppts)} ppt(s)")
        for src in ppts:
            target_name = f"{eidh}_{src.name}"
            target = PPT_FLAT / target_name
            if target.exists():
                print(f"    [skip] {target_name} (already exists)")
                n_skipped += 1
                continue
            print(f"    [copy] {src.name} → {target_name}")
            if args.dry_run:
                n_copied += 1
                continue
            try:
                shutil.copy2(src, target)
                n_copied += 1
            except Exception as e:
                print(f"      [!] copy fail: {e}")
                n_err += 1

    print(f"\n[done] {n_copied} copied, {n_skipped} skipped, {n_err} err"
          + (" (dry-run)" if args.dry_run else ""))
    if n_copied > 0 and not args.dry_run:
        print(f"\n[next] 重跑 audit_ppt_coverage.py 確認 cover 提升")


if __name__ == "__main__":
    main()
