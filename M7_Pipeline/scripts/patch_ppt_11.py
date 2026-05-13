"""patch_ppt_11.py — 把 11 個 SMB 漏抓的 PPT 補進 ppt_tp/

讀 ppt_smb_check.csv 找 status=smb_has_ppt 的 11 筆，
從 tp_url 把 .ppt/.pptx copy 到 m7_organized_v2/ppt_tp/
命名規則：{eidh}_TARGET_{style#}_TP.pptx（簡化版，跟 3_reorganize.py 兼容）

用法：
  python scripts\\patch_ppt_11.py [--dry-run]
"""
from __future__ import annotations
import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMB_CHECK = ROOT / "outputs" / "ppt_smb_check.csv"
PPT_DIR = ROOT / "m7_organized_v2" / "ppt_tp"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not SMB_CHECK.exists():
        print(f"[!] {SMB_CHECK} 不存在 — 先跑 check_ppt_smb.py")
        sys.exit(1)

    rows = []
    with open(SMB_CHECK, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["status"] == "smb_has_ppt":
                rows.append(r)
    print(f"[load] {len(rows)} SMB 漏抓 EIDH")

    n_copied = n_skipped = n_err = 0

    for r in rows:
        eidh = r["eidh"]
        cust = r["customer"]
        tp_url = r["tp_url"]

        if not Path(tp_url).exists():
            print(f"  [!] EIDH={eidh}: SMB path 連不到 — {tp_url}")
            n_err += 1
            continue

        # 列出 SMB 資料夾的 .ppt/.pptx
        try:
            ppts = [p for p in Path(tp_url).iterdir()
                    if p.is_file() and p.suffix.lower() in (".ppt", ".pptx")]
        except (OSError, PermissionError) as e:
            print(f"  [!] EIDH={eidh}: cannot iter — {e}")
            n_err += 1
            continue

        if not ppts:
            print(f"  [!] EIDH={eidh}: 0 ppt/pptx in {tp_url}")
            n_err += 1
            continue

        print(f"\n  EIDH={eidh} cust={cust[:15]} found {len(ppts)} ppt(s):")
        for src in ppts:
            # 用 eidh prefix 命名（reorganize 規則）
            ext = src.suffix.lower()
            target_name = f"{eidh}_{src.name}"
            target = PPT_DIR / target_name

            if target.exists():
                print(f"    [skip] {target_name} (already exists)")
                n_skipped += 1
                continue

            print(f"    [copy] {src.name} → {target_name}")
            if not args.dry_run:
                try:
                    PPT_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    n_copied += 1
                except Exception as e:
                    print(f"      [!] copy fail: {e}")
                    n_err += 1
            else:
                n_copied += 1

    print(f"\n[done] {n_copied} copied, {n_skipped} skipped, {n_err} err"
          + (" (dry-run)" if args.dry_run else ""))
    if n_copied > 0 and not args.dry_run:
        print(f"\n[next] 重跑 audit_ppt_coverage.py 確認 PPT cover 數提升")


if __name__ == "__main__":
    main()
