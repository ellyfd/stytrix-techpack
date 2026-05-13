"""
1_fetch.py — Step 1: 抓 sketch + 五階段 CSV (內網執行)

直接寫到 m7_organized_v2/ 用完整命名 <EIDH>_<HSN>_<客戶>_<款>.<ext>，
省 m7_output 中轉。

輸出：
  ../m7_organized_v2/sketches/<EIDH>_<HSN>_<客戶>_<款>.{jpg,png}
  ../m7_organized_v2/csv_5level/<EIDH>_<HSN>_<客戶>_<款>.csv
  ../m7_organized_v2/_fetch_manifest.csv  (audit log)

⚠️ M7 列管表「五階層網址」欄位寫死成 M6 URL，本腳本自動轉 M7：
   M6FiveLevelReport.aspx → M7FiveLevelReport.aspx (eidh 小寫)
   MTM_M6_FiveLevel_Detail → MTM_M7_FiveLevel_Detail
   detail 用 CSV 格式 (EXCELOPENXML 在這版 SSRS 出 500)

用法：
   python scripts\\1_fetch.py --input M7資源索引_M7URL正確版_20260504.xlsx --sheet 新做工_PullOn --limit 1180

需要：pip install pandas openpyxl requests requests_negotiate_sspi
必須：Makalot 內網 + Windows 域帳號
"""

import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

try:
    import pandas as pd
    import requests
except ImportError:
    print("請先: pip install pandas openpyxl requests requests_negotiate_sspi")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent  # M7_Pipeline/
DEFAULT_OUT = ROOT / "m7_organized_v2"


def clean_name(s: str) -> str:
    s = str(s)
    s = s.replace(' ', '_').replace('&', 'and').replace('/', '_').replace('\\', '_')
    return re.sub(r'[<>:"|?*]', '', s)


def full_name(row, ext: str) -> str:
    eidh = int(row['Eidh'])
    hsn = int(row['HEADER_SN'])
    cust = clean_name(row['客戶'])
    style = clean_name(row['報價款號'])
    return f"{eidh}_{hsn}_{cust}_{style}{ext}"


def load_index(xlsx_path: Path, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx_path, sheet_name=sheet, engine="openpyxl")
    if "五階層網址_M7" in df.columns:
        df = df.rename(columns={"五階層網址_M7": "五階層網址",
                                "細工段網址_M7": "細工段網址"})
    elif "五階層網址" in df.columns:
        df["五階層網址"] = df["五階層網址"].astype(str).str.replace(
            "M6FiveLevelReport.aspx", "M7FiveLevelReport.aspx", regex=False
        ).str.replace("?EIDH=", "?eidh=", regex=False)
        df["細工段網址"] = df["細工段網址"].astype(str).str.replace(
            "MTM_M6_FiveLevel_Detail", "MTM_M7_FiveLevel_Detail", regex=False
        )
    needed = ["HEADER_SN", "Eidh", "客戶", "報價款號", "Item",
              "Sketch", "五階層網址", "細工段網址", "TP資料夾"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"缺欄位: {missing}")
    print(f"[載入] {sheet}: {len(df)} 筆")
    return df


def download_sketch(url: str, dst: Path) -> str:
    if not isinstance(url, str) or not url.startswith("http"):
        return "skip:invalid_url"
    if dst.exists():
        return "skip:exists"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dst.write_bytes(r.content)
        return f"ok:{dst.name}"
    except Exception as e:
        return f"err:{e.__class__.__name__}:{str(e)[:50]}"


def export_ssrs_csv(url: str, dst: Path) -> str:
    """SSRS 細工段表 → CSV"""
    if not isinstance(url, str) or not url.startswith("http"):
        return "skip:invalid_url"
    if dst.exists():
        return "skip:exists"
    sep = "&" if "?" in url else "?"
    export_url = f"{url}{sep}rs:Format=CSV"
    try:
        try:
            from requests_negotiate_sspi import HttpNegotiateAuth
            auth = HttpNegotiateAuth()
        except ImportError:
            auth = None
        r = requests.get(export_url, auth=auth, timeout=120)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "text/csv" not in ct:
            return f"err:wrong_ct:{ct[:50]}"
        dst.write_bytes(r.content)
        return f"ok:{dst.name}"
    except Exception as e:
        return f"err:{e.__class__.__name__}:{str(e)[:50]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="索引 xlsx (在 M7_Pipeline/)")
    ap.add_argument("--sheet", required=True, help="工作表名稱")
    ap.add_argument("--output", default=str(DEFAULT_OUT),
                    help=f"輸出根目錄 (預設 {DEFAULT_OUT})")
    ap.add_argument("--do", default="sketch,csv_5level",
                    help="動作: sketch / csv_5level")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.1)
    ap.add_argument("--item-filter", default=None,
                    help="只跑指定 Item（例：'Pull On Pants'）；多個用逗號分隔")
    ap.add_argument("--workers", type=int, default=8,
                    help="並行下載 thread 數 (default 8). 已抓檔自動 skip:exists, 安全 incremental.")
    args = ap.parse_args()

    actions = set(s.strip() for s in args.do.split(","))
    out = Path(args.output)
    sk_dir = out / "sketches"; sk_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = out / "csv_5level"; csv_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / args.input

    df = load_index(input_path, args.sheet)
    if args.item_filter:
        wanted = set(s.strip() for s in args.item_filter.split(","))
        before = len(df)
        df = df[df["Item"].astype(str).str.strip().isin(wanted)].reset_index(drop=True)
        print(f"[item-filter] {sorted(wanted)}: {before} → {len(df)} 筆")
    if args.limit:
        df = df.head(args.limit)
        print(f"[限制] 只跑前 {args.limit} 筆")

    manifest_path = out / "_fetch_manifest.csv"
    write_lock = Lock()
    counters = {"done": 0, "skip": 0, "ok": 0, "err": 0}
    t0 = time.time()

    def _process_row(row_tuple):
        i, row = row_tuple
        r_sk = r_csv = ""
        if "sketch" in actions:
            url = row["Sketch"]
            ext = Path(urlparse(url).path).suffix if isinstance(url, str) else ""
            if not ext:
                ext = ".jpg"
            r_sk = download_sketch(url, sk_dir / full_name(row, ext))
        if "csv_5level" in actions:
            r_csv = export_ssrs_csv(row["細工段網址"], csv_dir / full_name(row, ".csv"))
        if args.sleep:
            time.sleep(args.sleep)
        return i, row, r_sk, r_csv

    with open(manifest_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["HEADER_SN", "Eidh", "客戶", "報價款號", "Item",
                    "sketch_result", "csv_5level_result", "TP資料夾"])

        if args.workers <= 1:
            # Sequential (原邏輯)
            for i, row in df.iterrows():
                _, row, r_sk, r_csv = _process_row((i, row))
                w.writerow([
                    int(row["HEADER_SN"]) if pd.notna(row["HEADER_SN"]) else "",
                    int(row["Eidh"]) if pd.notna(row["Eidh"]) else "",
                    row["客戶"], row["報價款號"], row["Item"],
                    r_sk, r_csv, row["TP資料夾"],
                ])
                if (i + 1) % 25 == 0:
                    print(f"  [{i+1}/{len(df)}] sk={r_sk[:25]}  csv={r_csv[:25]}")
        else:
            # Parallel (ThreadPoolExecutor)
            print(f"[parallel] workers={args.workers}, total={len(df)} EIDHs")
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {ex.submit(_process_row, (i, r)): i for i, r in df.iterrows()}
                for fut in as_completed(futures):
                    i, row, r_sk, r_csv = fut.result()
                    with write_lock:
                        w.writerow([
                            int(row["HEADER_SN"]) if pd.notna(row["HEADER_SN"]) else "",
                            int(row["Eidh"]) if pd.notna(row["Eidh"]) else "",
                            row["客戶"], row["報價款號"], row["Item"],
                            r_sk, r_csv, row["TP資料夾"],
                        ])
                        counters["done"] += 1
                        if r_sk.startswith("skip") or r_csv.startswith("skip"):
                            counters["skip"] += 1
                        if r_sk.startswith("ok") or r_csv.startswith("ok"):
                            counters["ok"] += 1
                        if r_sk.startswith("err") or r_csv.startswith("err"):
                            counters["err"] += 1
                        if counters["done"] % 50 == 0:
                            elapsed = time.time() - t0
                            rate = counters["done"] / max(elapsed, 0.1)
                            eta_min = (len(df) - counters["done"]) / rate / 60
                            print(f"  [{counters['done']}/{len(df)}] "
                                  f"skip={counters['skip']} ok={counters['ok']} err={counters['err']}  "
                                  f"rate={rate:.1f}/s ETA={eta_min:.0f}min")

    elapsed_min = (time.time() - t0) / 60
    print(f"\n[OK] 完成 ({elapsed_min:.1f} min)")
    print(f"   skip:exists = {counters['skip']}  ok = {counters['ok']}  err = {counters['err']}")
    print(f"   sketches/   -> {sk_dir}")
    print(f"   csv_5level/ -> {csv_dir}")
    print(f"   manifest:   {manifest_path}")
    print(f"   (TP 資料夾路徑在 manifest.csv 最後一欄,跑 2_fetch_tp.ps1 抓)")


if __name__ == "__main__":
    main()
