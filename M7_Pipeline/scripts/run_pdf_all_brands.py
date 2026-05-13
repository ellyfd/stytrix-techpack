"""
依序跑所有 brand 的 PDF extract — 避免複製貼上一堆指令容易壞掉
跑法: python scripts\run_pdf_all_brands.py

可選: 跳過已跑過的 brand
  python scripts\run_pdf_all_brands.py --skip GU GAP
只跑指定 brand:
  python scripts\run_pdf_all_brands.py --only GU GAP DKS
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

# 依「PDF 主源 + 量大」優先順序
BRANDS = [
    "GU",    # 1,665 件, PDF 主源
    "GAP",   # 第二大宗
    "DKS",
    "KOH",
    "TGT",
    "ATH",
    "BR",
    "HLF",
    "ANF",
    "UA",
    "WMT",
    "SAN",
    "BY",
    "QCE",
    "NET",
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[], help="跳過這些 brand")
    ap.add_argument("--only", nargs="*", default=None, help="只跑這些 brand")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    extract_script = script_dir / "extract_pdf_all.py"
    if not extract_script.exists():
        print(f"[!] {extract_script} 不存在")
        return 1

    target = args.only if args.only else BRANDS
    target = [b for b in target if b not in args.skip]

    print(f"=== 依序跑 {len(target)} brand: {', '.join(target)} ===\n")

    results = {}
    t_total = time.time()

    for i, brand in enumerate(target, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(target)}] brand={brand}")
        print(f"{'='*60}")
        t0 = time.time()
        try:
            r = subprocess.run(
                [sys.executable, str(extract_script), "--client", brand],
                check=False,
            )
            elapsed = (time.time() - t0) / 60
            results[brand] = (r.returncode, elapsed)
            status = "OK" if r.returncode == 0 else f"FAIL (rc={r.returncode})"
            print(f"\n[{i}/{len(target)}] {brand}: {status} in {elapsed:.1f} min")
        except KeyboardInterrupt:
            print(f"\n[!] 中斷 — 已跑完: {list(results.keys())}")
            return 1
        except Exception as e:
            print(f"\n[!] {brand} 例外: {e}")
            results[brand] = (-1, (time.time() - t0) / 60)

    total_min = (time.time() - t_total) / 60
    print(f"\n\n{'='*60}")
    print(f"=== 全部 brand 跑完, 總耗時 {total_min:.1f} min ===")
    print(f"{'='*60}")
    print(f"  {'brand':<8} {'status':<12} {'time':>8}")
    for b, (rc, t) in results.items():
        st = "OK" if rc == 0 else f"FAIL ({rc})"
        print(f"  {b:<8} {st:<12} {t:>6.1f}m")

    return 0

if __name__ == "__main__":
    sys.exit(main())
