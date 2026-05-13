"""run_pipeline.py — v8 pipeline 一鍵 orchestrator

把 M7_Pipeline 5 步 + stytrix-techpack 2 步串成一鍵跑。

Phase 1: extract_pdf_metadata + report_canonical_coverage
Phase 2: build_m7_pullon_source_v3 + report_canonical_consensus
Phase 3: push_m7_pullon_to_platform (+ size diff sanity)
Phase 4: cross-repo git checkout -b + add + commit + push (--auto-commit)
Phase 5: build_recipes_master + git diff stat        (--build-recipes)

每 phase 跑前 check input,跑後 verify output,有錯精準停。
最後印一張 summary 表 [Phase, status, time, action]。

用法:
  python scripts\\run_pipeline.py                      # 全跑(Phase 1-3,不 commit)
  python scripts\\run_pipeline.py --auto-commit        # 加 Phase 4 跨 repo git
  python scripts\\run_pipeline.py --build-recipes      # 加 Phase 5 重 build platform
  python scripts\\run_pipeline.py --skip-extract       # 跳 Phase 1
  python scripts\\run_pipeline.py --dry-run            # 不實跑,只印 plan
  python scripts\\run_pipeline.py --client ONY,GAP     # extract 限定客戶
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
OUTPUTS = ROOT / "outputs" / "platform"
PLATFORM_REPO = Path(r"C:\temp\stytrix-techpack")

# Phase output 主要 deliverable file,用來 verify
OUT_PDF_METADATA = OUTPUTS / "pdf_metadata.jsonl"
OUT_DESIGNS = OUTPUTS / "m7_pullon_designs.jsonl"
OUT_SOURCE = OUTPUTS / "m7_pullon_source.jsonl"
DST_DESIGNS_GZ = PLATFORM_REPO / "data" / "ingest" / "m7_pullon" / "designs.jsonl.gz"
DST_ENTRIES = PLATFORM_REPO / "data" / "ingest" / "m7_pullon" / "entries.jsonl"
DST_RECIPES = PLATFORM_REPO / "data" / "runtime" / "recipes_master.json"

DEFAULT_CLIENTS = "ONY,ATHLETA,GAP,GAP_OUTLET,DICKS,TARGET,KOHLS,A_&_F,GU,CATO,BR"


# ════════════════════════════════════════════════════════════
# Pretty output helpers
# ════════════════════════════════════════════════════════════

class C:
    """ANSI color shorts (Windows 10+ terminal 都支援)"""
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    END = "\033[0m"


def header(phase_n: int, title: str):
    print(f"\n{C.BOLD}{C.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}")
    print(f"{C.BOLD}{C.BLUE}  Phase {phase_n}: {title}{C.END}")
    print(f"{C.BOLD}{C.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}")


def ok(s: str): print(f"  {C.GREEN}✓{C.END} {s}")
def warn(s: str): print(f"  {C.YELLOW}!{C.END} {s}")
def err(s: str): print(f"  {C.RED}✗{C.END} {s}")
def info(s: str): print(f"  {C.GRAY}·{C.END} {s}")


def fmt_size(p: Path) -> str:
    if not p.exists(): return "(missing)"
    sz = p.stat().st_size
    if sz > 1024 * 1024: return f"{sz / 1024 / 1024:.1f} MB"
    if sz > 1024: return f"{sz / 1024:.1f} KB"
    return f"{sz} B"


def run_cmd(cmd: list, cwd: Path = None, dry: bool = False) -> tuple[int, str]:
    """執行 subprocess,即時 print stdout/stderr,回傳 (returncode, full_stdout)"""
    cmd_str = " ".join(str(c) for c in cmd)
    info(f"$ {cmd_str}" + (f"  (cwd={cwd.name})" if cwd else ""))
    if dry:
        info("[dry-run] skip exec")
        return 0, ""

    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    out_lines = []
    for line in proc.stdout:
        line = line.rstrip()
        print(f"    {line}")
        out_lines.append(line)
    proc.wait()
    return proc.returncode, "\n".join(out_lines)


# ════════════════════════════════════════════════════════════
# Phase implementations
# ════════════════════════════════════════════════════════════

def phase_1_extract(clients: str, dry: bool) -> dict:
    """Phase 1: extract_pdf_metadata + report_canonical_coverage"""
    header(1, "extract PDF metadata + coverage report")

    info(f"input: m7_organized_v2/metadata/designs.jsonl ({fmt_size(ROOT / 'm7_organized_v2' / 'metadata' / 'designs.jsonl')})")
    info(f"output: {OUT_PDF_METADATA.name} (現況 {fmt_size(OUT_PDF_METADATA)})")

    rc, _ = run_cmd(
        [sys.executable, str(SCRIPTS / "extract_pdf_metadata.py"), "--client", clients],
        cwd=ROOT, dry=dry,
    )
    if rc != 0:
        return {"status": "FAIL", "msg": f"extract_pdf_metadata.py rc={rc}"}

    rc, _ = run_cmd(
        [sys.executable, str(SCRIPTS / "report_canonical_coverage.py")],
        cwd=ROOT, dry=dry,
    )
    if rc != 0:
        warn(f"report_canonical_coverage.py rc={rc} (非致命)")

    if not dry:
        if not OUT_PDF_METADATA.exists():
            err(f"output 不存在: {OUT_PDF_METADATA}")
            return {"status": "FAIL", "msg": "output missing"}
        ok(f"pdf_metadata.jsonl 產出 ({fmt_size(OUT_PDF_METADATA)})")
    return {"status": "OK", "output": OUT_PDF_METADATA}


def phase_2_build(dry: bool) -> dict:
    """Phase 2: build_m7_pullon_source_v3 + report_canonical_consensus"""
    header(2, "build m7_pullon designs (canonical multi-source consensus)")

    info(f"input: pdf_metadata.jsonl ({fmt_size(OUT_PDF_METADATA)}) + M7列管.xlsx + csv_5level/")
    info(f"output: {OUT_DESIGNS.name} (現況 {fmt_size(OUT_DESIGNS)})")

    rc, _ = run_cmd(
        [sys.executable, str(SCRIPTS / "build_m7_pullon_source_v3.py")],
        cwd=ROOT, dry=dry,
    )
    if rc != 0:
        return {"status": "FAIL", "msg": f"build_m7_pullon_source_v3.py rc={rc}"}

    rc, _ = run_cmd(
        [sys.executable, str(SCRIPTS / "report_canonical_consensus.py")],
        cwd=ROOT, dry=dry,
    )
    if rc != 0:
        warn(f"report_canonical_consensus.py rc={rc} (非致命)")

    if not dry:
        if not OUT_DESIGNS.exists():
            err(f"output 不存在: {OUT_DESIGNS}")
            return {"status": "FAIL", "msg": "output missing"}
        ok(f"m7_pullon_designs.jsonl ({fmt_size(OUT_DESIGNS)})")
        ok(f"m7_pullon_source.jsonl ({fmt_size(OUT_SOURCE)})")
    return {"status": "OK", "outputs": [OUT_DESIGNS, OUT_SOURCE]}


def phase_3_push(dry: bool) -> dict:
    """Phase 3: push to stytrix-techpack repo (含 size diff sanity)"""
    header(3, "push m7_pullon to stytrix-techpack repo")

    if not OUT_DESIGNS.exists():
        err(f"input missing: {OUT_DESIGNS}")
        return {"status": "FAIL", "msg": "Phase 2 output missing"}
    if not PLATFORM_REPO.exists():
        err(f"platform repo not found: {PLATFORM_REPO}")
        return {"status": "FAIL", "msg": "platform repo missing"}

    info(f"SRC: {OUT_DESIGNS.name} ({fmt_size(OUT_DESIGNS)})")
    info(f"DST: {DST_DESIGNS_GZ} (舊 {fmt_size(DST_DESIGNS_GZ)})")

    rc, _ = run_cmd(
        [sys.executable, str(SCRIPTS / "push_m7_pullon_to_platform.py")],
        cwd=ROOT, dry=dry,
    )
    if rc != 0:
        return {"status": "FAIL", "msg": f"push rc={rc}"}

    if not dry:
        if not DST_DESIGNS_GZ.exists():
            err(f"push 失敗,DST 不存在")
            return {"status": "FAIL", "msg": "push verify fail"}
        ok(f"designs.jsonl.gz 上 platform ({fmt_size(DST_DESIGNS_GZ)})")
        ok(f"entries.jsonl 上 platform ({fmt_size(DST_ENTRIES)})")
    return {"status": "OK"}


def phase_4_commit_push(dry: bool) -> dict:
    """Phase 4: cross-repo git checkout -b + add + commit + push"""
    header(4, "cross-repo git commit + push (stytrix-techpack)")

    if not PLATFORM_REPO.exists():
        return {"status": "FAIL", "msg": "platform repo missing"}

    # 看 git status
    rc, out = run_cmd(["git", "status", "--short"], cwd=PLATFORM_REPO, dry=dry)
    if rc != 0:
        return {"status": "FAIL", "msg": f"git status rc={rc}"}
    if not dry and not out.strip():
        warn("git status clean — no changes to commit, skip Phase 4")
        return {"status": "SKIPPED", "msg": "no changes"}

    branch_name = f"claude/m7-pullon-rebuild-{datetime.now().strftime('%Y%m%d-%H%M')}"
    info(f"new branch: {branch_name}")

    rc, _ = run_cmd(["git", "checkout", "-b", branch_name], cwd=PLATFORM_REPO, dry=dry)
    if rc != 0:
        warn(f"git checkout -b {branch_name} rc={rc} (branch already exists?)")
        # 嘗試 checkout existing
        rc, _ = run_cmd(["git", "checkout", branch_name], cwd=PLATFORM_REPO, dry=dry)
        if rc != 0:
            return {"status": "FAIL", "msg": "git checkout fail"}

    rc, _ = run_cmd(
        ["git", "add", "data/ingest/m7_pullon/designs.jsonl.gz",
         "data/ingest/m7_pullon/entries.jsonl"],
        cwd=PLATFORM_REPO, dry=dry,
    )
    if rc != 0:
        return {"status": "FAIL", "msg": "git add fail"}

    commit_msg = (
        f"m7_pullon: rebuild from full v8 pipeline ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
        "Automated push from M7_Pipeline run_pipeline.py:\n"
        "- extract_pdf_metadata.py 11 客戶 PDF metadata\n"
        "- build_m7_pullon_source_v3.py 加 canonical multi-source consensus\n"
        "- push_m7_pullon_to_platform.py gzip + copy"
    )
    rc, _ = run_cmd(["git", "commit", "-m", commit_msg], cwd=PLATFORM_REPO, dry=dry)
    if rc != 0:
        return {"status": "FAIL", "msg": "git commit fail"}

    rc, _ = run_cmd(["git", "push", "-u", "origin", "HEAD"], cwd=PLATFORM_REPO, dry=dry)
    if rc != 0:
        return {"status": "FAIL", "msg": "git push fail"}

    ok(f"pushed → branch '{branch_name}'")
    ok(f"PR URL: https://github.com/ellyfd/stytrix-techpack/pull/new/{branch_name}")
    return {"status": "OK", "branch": branch_name}


def phase_5_build_recipes(dry: bool) -> dict:
    """Phase 5: build_recipes_master.py + git diff stat"""
    header(5, "build_recipes_master.py + diff stat (downstream verify)")

    build_script = PLATFORM_REPO / "star_schema" / "scripts" / "build_recipes_master.py"
    if not build_script.exists():
        return {"status": "FAIL", "msg": f"build script missing: {build_script}"}

    rc, _ = run_cmd([sys.executable, str(build_script)], cwd=PLATFORM_REPO, dry=dry)
    if rc != 0:
        return {"status": "FAIL", "msg": f"build_recipes_master.py rc={rc}"}

    rc, out = run_cmd(
        ["git", "diff", "--stat", "data/runtime/recipes_master.json"],
        cwd=PLATFORM_REPO, dry=dry,
    )

    if not dry:
        if not DST_RECIPES.exists():
            err(f"recipes_master.json missing: {DST_RECIPES}")
            return {"status": "FAIL", "msg": "output missing"}
        ok(f"recipes_master.json ({fmt_size(DST_RECIPES)})")
    return {"status": "OK", "diff_stat": out.strip() if out else ""}


# ════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════

def print_summary(results: dict, t_start: float):
    elapsed = time.time() - t_start
    print(f"\n{C.BOLD}{C.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}")
    print(f"{C.BOLD}{C.BLUE}  Pipeline Summary  (total {elapsed:.1f}s){C.END}")
    print(f"{C.BOLD}{C.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}")
    for phase, r in results.items():
        s = r.get("status", "?")
        if s == "OK": color = C.GREEN
        elif s == "FAIL": color = C.RED
        elif s == "SKIPPED": color = C.YELLOW
        else: color = C.GRAY
        msg = r.get("msg", "")
        print(f"  {color}{s:8}{C.END}  {phase}" + (f"  — {msg}" if msg else ""))
    print(f"{C.BOLD}{C.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.END}\n")


# ════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default=DEFAULT_CLIENTS,
                    help=f"extract_pdf_metadata 客戶 filter (default: {DEFAULT_CLIENTS})")
    ap.add_argument("--skip-extract", action="store_true", help="跳過 Phase 1")
    ap.add_argument("--skip-build", action="store_true", help="跳過 Phase 2")
    ap.add_argument("--skip-push", action="store_true", help="跳過 Phase 3")
    ap.add_argument("--auto-commit", action="store_true",
                    help="加跑 Phase 4(跨 repo git commit + push)")
    ap.add_argument("--build-recipes", action="store_true",
                    help="加跑 Phase 5(stytrix-techpack 端重 build recipes_master)")
    ap.add_argument("--dry-run", action="store_true",
                    help="不實跑,只印 plan")
    args = ap.parse_args()

    t_start = time.time()
    results = {}

    if args.skip_extract:
        results["Phase 1: extract"] = {"status": "SKIPPED", "msg": "--skip-extract"}
    else:
        results["Phase 1: extract"] = phase_1_extract(args.client, args.dry_run)
        if results["Phase 1: extract"]["status"] == "FAIL":
            print_summary(results, t_start)
            return 1

    if args.skip_build:
        results["Phase 2: build"] = {"status": "SKIPPED", "msg": "--skip-build"}
    else:
        results["Phase 2: build"] = phase_2_build(args.dry_run)
        if results["Phase 2: build"]["status"] == "FAIL":
            print_summary(results, t_start)
            return 1

    if args.skip_push:
        results["Phase 3: push"] = {"status": "SKIPPED", "msg": "--skip-push"}
    else:
        results["Phase 3: push"] = phase_3_push(args.dry_run)
        if results["Phase 3: push"]["status"] == "FAIL":
            print_summary(results, t_start)
            return 1

    if args.auto_commit:
        results["Phase 4: commit+push"] = phase_4_commit_push(args.dry_run)
        if results["Phase 4: commit+push"]["status"] == "FAIL":
            print_summary(results, t_start)
            return 1
    else:
        results["Phase 4: commit+push"] = {"status": "SKIPPED", "msg": "no --auto-commit"}

    if args.build_recipes:
        results["Phase 5: build_recipes"] = phase_5_build_recipes(args.dry_run)
        if results["Phase 5: build_recipes"]["status"] == "FAIL":
            print_summary(results, t_start)
            return 1
    else:
        results["Phase 5: build_recipes"] = {"status": "SKIPPED", "msg": "no --build-recipes"}

    print_summary(results, t_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
