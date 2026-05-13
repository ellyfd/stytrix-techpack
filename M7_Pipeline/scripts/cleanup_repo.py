"""cleanup_repo.py — 直接刪掉 M7_Pipeline 不要的檔案

跑前先 dry-run（只印 plan）：
  python scripts\\cleanup_repo.py --dry-run

確認 OK 才實刪：
  python scripts\\cleanup_repo.py

不會動：
  - 任何在 PIPELINE.md 列為「現役」的 script
  - data/ tp_samples_v2/ m7_organized_v2/ 下任何資料
  - outputs/platform/ 下的 deliverable（v3/v4/v5 + recipes_master.json）
  - outputs/bridge_v7/ 的 legacy deliverable

會刪掉：
  - 全部 __pycache__/                       (Python 編譯暫存)
  - scripts/legacy/tp_samples_v2/           (99 MB 副本)
  - scripts/legacy/ 下全部舊腳本            (4_pipeline / 5_export / lib_*.py 等)
  - scripts/ 下 8 個現役但已被取代的 script (build_platform_recipes 舊版 / Sample Schedule 系列 等)
  - outputs/ 下 4 個一次性 debug 檔
"""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# scripts/ 下要刪的（已被新版取代 / 死路）
SCRIPTS_TO_DELETE = [
    "build_platform_recipes.py",       # v1, 被 v3/v4/v5 取代
    "build_platform_recipes_v2.py",    # v2, 被 v3/v4/v5 取代
    "fetch_m7_report.py",              # HTTP NTLM 版（被 playwright 版取代）
    "fetch_order_info.py",             # nt-eip ordersite dead end
    "fetch_sample_schedule.py",        # Sample Schedule 死路（pywinauto 看不見控件）
    "probe_sample_schedule.py",        # 同上 probe
    "probe_win32.py",                  # 同上 win32 backend probe
    "check_ppt_smb.ps1",               # 重複 (有 .py 版)
    "cleanup_repo.ps1",                # 重複 (有 .py 版)
]

# scripts/legacy/ 下舊版（已是 dead code）
LEGACY_DIR_TO_DELETE = "scripts/legacy"  # 整個 legacy/ 砍掉

# outputs/ 下一次性 debug 檔
OUTPUTS_TO_DELETE = [
    "sample_schedule_ui_tree.txt",
    "m7_report_inspect_317234.html",
    "m7_report_inspect_317234.json",
]

# .gitignore entries
GITIGNORE_LINES = [
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".*_state",
]


def banner(text):
    print()
    print("═" * 60)
    print(f"  {text}")
    print("═" * 60)


def step(num, text):
    print(f"\n[{num}] {text}")


def action(desc, fn, dry_run, size=None):
    sz_str = f" ({size})" if size else ""
    print(f"  → 刪 {desc}{sz_str}")
    if not dry_run:
        try:
            fn()
        except Exception as e:
            print(f"    [!] {e}")


def fmt_size(b):
    if b >= 1024 * 1024:
        return f"{b / 1024 / 1024:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def dir_size(path):
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except Exception:
        return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    mode = "(DRY RUN — 沒實際刪)" if args.dry_run else "(LIVE — 真的刪)"
    banner(f"M7 Pipeline cleanup {mode}")

    total_freed = 0
    n_deleted = 0

    # ── 1. __pycache__ ──
    step(1, "刪所有 __pycache__/")
    pycache_dirs = list(ROOT.rglob("__pycache__"))
    if not pycache_dirs:
        print("  (無)")
    for d in pycache_dirs:
        sz = dir_size(d)
        action(
            str(d.relative_to(ROOT)),
            lambda d=d: shutil.rmtree(d, ignore_errors=True),
            args.dry_run,
            fmt_size(sz),
        )
        total_freed += sz
        n_deleted += 1

    # ── 2. scripts/legacy/tp_samples_v2 (99 MB 副本) ──
    step(2, "刪 99 MB 重複資料 (legacy/tp_samples_v2/)")
    legacy_tp = ROOT / "scripts" / "legacy" / "tp_samples_v2"
    if legacy_tp.exists():
        sz = dir_size(legacy_tp)
        action(
            str(legacy_tp.relative_to(ROOT)),
            lambda: shutil.rmtree(legacy_tp, ignore_errors=True),
            args.dry_run,
            fmt_size(sz),
        )
        total_freed += sz
        n_deleted += 1
    else:
        print("  (不存在，跳過)")

    # ── 3. scripts/legacy/ 全砍 ──
    step(3, "刪 scripts/legacy/ 全部舊腳本（lib_*.py / 4_pipeline / 5_export 等）")
    legacy_dir = ROOT / "scripts" / "legacy"
    if legacy_dir.exists():
        sz = dir_size(legacy_dir)
        # 列出有什麼要刪
        for f in legacy_dir.iterdir():
            if f.is_file():
                print(f"    - {f.name}")
        action(
            str(legacy_dir.relative_to(ROOT)),
            lambda: shutil.rmtree(legacy_dir, ignore_errors=True),
            args.dry_run,
            fmt_size(sz),
        )
        total_freed += sz
        n_deleted += 1
    else:
        print("  (不存在，跳過)")

    # ── 4. scripts/ 下被取代的 ──
    step(4, "刪 scripts/ 下被取代 / 死路的 script")
    n_step4 = 0
    for fname in SCRIPTS_TO_DELETE:
        f = ROOT / "scripts" / fname
        if not f.exists():
            continue
        sz = f.stat().st_size
        action(
            f"scripts/{fname}",
            lambda f=f: f.unlink(),
            args.dry_run,
            fmt_size(sz),
        )
        total_freed += sz
        n_deleted += 1
        n_step4 += 1
    if n_step4 == 0:
        print("  (無檔可刪)")

    # ── 5. outputs/ debug 檔 ──
    step(5, "刪 outputs/ 一次性 debug 檔")
    n_step5 = 0
    for fname in OUTPUTS_TO_DELETE:
        f = ROOT / "outputs" / fname
        if not f.exists():
            continue
        sz = f.stat().st_size
        action(
            f"outputs/{fname}",
            lambda f=f: f.unlink(),
            args.dry_run,
            fmt_size(sz),
        )
        total_freed += sz
        n_deleted += 1
        n_step5 += 1
    if n_step5 == 0:
        print("  (無檔可刪)")

    # ── 6. .gitignore ──
    step(6, "補 .gitignore")
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        if not args.dry_run:
            gitignore.touch()
        print(f"  創 .gitignore at {gitignore.relative_to(ROOT)}")
        existing = ""
    else:
        existing = gitignore.read_text(encoding="utf-8")

    missing = [line for line in GITIGNORE_LINES if line not in existing]
    if missing:

        def do_append():
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Auto-added by cleanup_repo.py\n")
                for line in missing:
                    f.write(line + "\n")

        action(
            f"加 {len(missing)} entries to .gitignore",
            do_append,
            args.dry_run,
        )
    else:
        print("  (.gitignore 已含必要 entries)")

    # ── Summary ──
    banner(f"清理完成 {mode}")
    print(f"\n  共 {n_deleted} 項，預估省 {fmt_size(total_freed)}")
    if args.dry_run:
        print(f"\n  下一步：確認 plan 後跑 python scripts\\cleanup_repo.py（不加 --dry-run）")
    else:
        print(f"\n  下一步：cd 進 M7_Pipeline 確認 — `dir scripts` 應該乾淨多了")


if __name__ == "__main__":
    main()
