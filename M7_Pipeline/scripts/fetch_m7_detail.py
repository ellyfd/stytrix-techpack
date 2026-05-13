"""fetch_m7_detail.py — 從 nt-netsql2 SSRS 抓 M7 細工段/機種 detail

URL: http://nt-netsql2/ReportServer/Pages/ReportViewer.aspx
       ?/IE.ReportService/MTM_M7_FiveLevel_Detail
       &rs:Command=Render
       &rs:Format=CSV          ← SSRS 直接 export CSV，不用 scrape HTML
       &EIDH={eidh}
       &Language=TW
       &SizeAuth=NG

比 nt-net2 多的：
  - 細工段（比五階 L4 還細的 sub-operation）
  - 每工段機種 detail（真實使用的機種而非 catch-all）

需要：
  pip install requests requests_negotiate_sspi    (Windows AD SSO)
  或 user 已登入 Chrome → 用 Playwright CDP 帶 cookies

用法：
  python scripts\\fetch_m7_detail.py [--limit 5] [--reset]

state file:
  data/ingest/metadata/.m7_detail_state
output:
  data/ingest/metadata/m7_detail.csv  （所有 EIDH 細工段 union，每行一條 sub-op）
"""
import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_INDEX_NEW = ROOT.parent / "M7列管_20260507.xlsx"
M7_INDEX_OLD = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
M7_INDEX = M7_INDEX_NEW if M7_INDEX_NEW.exists() else M7_INDEX_OLD
ITEM_FILTER = {"Pull On Pants", "Leggings"}  # 改空 set 跑全 18,731
DESIGNS_JSONL = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
OUT = DL / "data" / "ingest" / "metadata" / "m7_detail.csv"
STATE = DL / "data" / "ingest" / "metadata" / ".m7_detail_state"

URL_TEMPLATE = (
    "http://nt-netsql2/ReportServer/Pages/ReportViewer.aspx"
    "?%2fIE.ReportService%2fMTM_M7_FiveLevel_Detail"
    "&rs:Command=Render"
    "&rs:Format=CSV"
    "&EIDH={eidh}"
    "&Language=TW"
    "&SizeAuth=NG"
)


def load_eidhs():
    """共用 helper m7_eidh_loader — 改 EIDH 範圍改 m7_eidh_loader.py 的 ITEM_FILTER"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_eidhs as _load
    return _load()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--reset", action="store_true")
    p.add_argument("--max-seconds", type=int, default=3600)
    args = p.parse_args()

    try:
        import requests
    except ImportError:
        print("[!] pip install requests")
        sys.exit(1)

    auth = None
    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
        auth = HttpNegotiateAuth()
        print("[auth] HttpNegotiateAuth (Windows AD SSO)")
    except ImportError:
        print("[!] pip install requests_negotiate_sspi")
        sys.exit(1)

    if args.reset:
        if STATE.exists(): STATE.unlink()
        if OUT.exists(): OUT.unlink()

    eidhs = load_eidhs()
    next_idx = 0
    if STATE.exists():
        next_idx = int(STATE.read_text().strip())
    if args.limit:
        eidhs = eidhs[:args.limit]
    if next_idx >= len(eidhs):
        print(f"═══ ALL DONE ═══ ({next_idx} done)")
        return

    print(f"[batch] {next_idx}..{len(eidhs)-1} of {len(eidhs)}")
    t0 = time.time()
    n_ok = n_err = 0
    n_rows_total = 0
    open_mode = "a" if next_idx > 0 and OUT.exists() else "w"

    with open(OUT, open_mode, newline="", encoding="utf-8-sig") as fout:
        writer = None
        i = next_idx
        while i < len(eidhs):
            if time.time() - t0 >= args.max_seconds:
                print(f"  [!] hit {args.max_seconds}s budget at {i}, stopping")
                break
            eidh = eidhs[i]
            url = URL_TEMPLATE.format(eidh=eidh)
            try:
                resp = requests.get(url, timeout=20, auth=auth)
                if resp.status_code != 200:
                    print(f"  [!] {eidh}: HTTP {resp.status_code}")
                    n_err += 1
                    i += 1
                    continue
                # SSRS CSV 通常 BOM + UTF-8
                content = resp.content.decode("utf-8-sig", errors="replace")
                rdr = csv.DictReader(io.StringIO(content))
                rows = list(rdr)
                if not rows:
                    if i % 20 == 0:
                        print(f"  [{i}/{len(eidhs)}] {eidh}: 0 rows")
                    i += 1
                    n_ok += 1
                    continue

                # Add eidh column to each row
                for r in rows:
                    r["_eidh"] = eidh

                if writer is None:
                    fieldnames = ["_eidh"] + [k for k in rows[0].keys() if k != "_eidh"]
                    writer = csv.DictWriter(fout, fieldnames=fieldnames)
                    if open_mode == "w":
                        writer.writeheader()
                for r in rows:
                    writer.writerow(r)
                n_rows_total += len(rows)
                n_ok += 1
                if i % 20 == 0:
                    print(f"  [{i}/{len(eidhs)}] {eidh}: {len(rows)} 細工段 (total {n_rows_total} rows)")
            except Exception as e:
                print(f"  [!] {eidh}: {e}")
                n_err += 1
            i += 1

    STATE.write_text(str(i))
    print(f"\n[done] processed {i - next_idx} EIDHs ({n_ok} ok, {n_err} err)")
    print(f"[total rows] {n_rows_total}")
    print(f"[state] {i}/{len(eidhs)}")
    print(f"[output] {OUT}")
    if i >= len(eidhs):
        print(f"═══ ALL DONE ═══")


if __name__ == "__main__":
    main()
