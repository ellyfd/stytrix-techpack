"""extract_pom_from_tp.py — 對 tp_samples_v2/ 跑 extract_techpack 抽 POM measurement chart.

source: tp_samples_v2/<EIDH>_<HSN>_<客戶>_<款>/<files>
   * 每個 EIDH 一個資料夾,內含 PDF / PPTX / XLSX
   * 我們只看 PDF (Centric 8 measurement chart 在 PDF)

per-EIDH 邏輯:
  1. 找該 EIDH 資料夾內所有 .pdf
  2. 對每個 PDF 跑 extract_techpack.extract(pdf_path)
     * Centric 8 parser (ONY/GAP/GO/BR/ATH 同集團 5 家)
     * 其他 brand PDF 會 fail / 抽不到 mcs
  3. 取 mcs 最豐富那份 PDF 為 representative
  4. 寫一行 jsonl: {eidh, design_id, client_code, brand_division, mcs}

輸出 stats: 各 client_code 抽到 mcs 件數 (= Centric 8 vs 其他 brand 比例)

用法:
  python scripts/extract_pom_from_tp.py [--limit N] [--workers N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent  # M7_Pipeline/
TP_DIR = ROOT / "tp_samples_v2"
OUT_DIR = ROOT / "outputs" / "pom"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSONL = OUT_DIR / "mc_pom_from_tp.jsonl"
OUT_STATS = OUT_DIR / "extract_pom_stats.txt"


def _parse_folder_name(folder_name: str) -> dict:
    """Parse <EIDH>_<HSN>_<客戶>_<款> → {eidh, hsn, client_raw, design_id}.

    e.g. '304080_10405493_OLD_NAVY_ONY25HOVDD01_2' →
      eidh=304080, hsn=10405493, client_raw='OLD_NAVY', design_id='ONY25HOVDD01_2'
    """
    parts = folder_name.split("_")
    if len(parts) < 4:
        return {"eidh": None, "hsn": None, "client_raw": None, "design_id": folder_name}
    eidh, hsn = parts[0], parts[1]
    # client 名可能多字 (OLD NAVY = OLD_NAVY = 2 tokens, GAP_OUTLET = 2 tokens),
    # design_id 是最後一個 (沒 _ 連接) — but Pull-On 命名 design_id 可能含 _ (ONY25HOVDD01_2)
    # 用簡單啟發: client 名是已知 list 內最長 prefix match
    KNOWN_CLIENTS = [
        "OLD_NAVY", "GAP_OUTLET", "GAP", "DICKS_SPORTING_GOODS", "DICKS", "ATHLETA",
        "UNDER_ARMOUR", "KOHLS", "A_&_F", "A_&_F", "GU", "BEYOND_YOGA",
        "HIGH_LIFE_LLC", "WAL-MART-CA", "WAL-MART", "QUINCE", "HALARA", "NET",
        "JOE_FRESH", "BANANA_REPUBLIC", "BRFS", "SANMAR", "DISTANCE", "ZARA",
        "ASICS-EU", "TARGET", "LEVIS", "CATO", "SMART_CLOTHING",
    ]
    tail = "_".join(parts[2:])  # 客戶_款
    client_raw = None
    design_id = tail
    for cl in sorted(KNOWN_CLIENTS, key=len, reverse=True):
        if tail.startswith(cl + "_"):
            client_raw = cl.replace("_", " ")
            design_id = tail[len(cl) + 1:]
            break
    if not client_raw:
        # fallback: 第 3 個 token 當 client
        client_raw = parts[2]
        design_id = "_".join(parts[3:])
    return {"eidh": eidh, "hsn": hsn, "client_raw": client_raw, "design_id": design_id}


def _client_to_code(client_raw: str) -> str:
    """Map raw client name → short code (同 build_v3.CLIENT_TO_CODE)."""
    if not client_raw:
        return "UNKNOWN"
    cl = client_raw.upper().strip().replace("_", " ")
    MAP = {
        "OLD NAVY": "ONY", "TARGET": "TGT", "GAP": "GAP", "GAP OUTLET": "GAP",
        "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS", "ATHLETA": "ATH",
        "UNDER ARMOUR": "UA", "KOHLS": "KOH", "A & F": "ANF", "GU": "GU",
        "BEYOND YOGA": "BY", "HIGH LIFE LLC": "HLF", "WAL-MART": "WMT",
        "WAL-MART-CA": "WMT", "QUINCE": "QCE", "HALARA": "HLA", "NET": "NET",
        "JOE FRESH": "JF", "BANANA REPUBLIC": "BR", "BRFS": "BR", "SANMAR": "SAN",
        "DISTANCE": "DST", "ZARA": "ZAR", "ASICS-EU": "ASICS", "LEVIS": "LEV",
        "CATO": "CATO", "SMART CLOTHING": "SMC",
    }
    return MAP.get(cl, cl[:6])


def _worker_extract(folder_path_str: str) -> dict | None:
    """Worker: 對一個 EIDH 資料夾跑 extract_techpack 取最豐富的 mcs."""
    import sys as _sys
    SCRIPT_DIR = Path(__file__).resolve().parent
    # 找 extract_techpack.py — scripts/lib/ 下 (聚陽 repo 重組後位置)
    for candidate in [
        SCRIPT_DIR / "lib",
        SCRIPT_DIR,
        SCRIPT_DIR.parent / "scripts" / "lib",
    ]:
        if (candidate / "extract_techpack.py").exists():
            _sys.path.insert(0, str(candidate))
            break
    else:
        # 退到 stytrix-techpack 端的
        for candidate in [
            Path("C:/temp/stytrix-techpack/scripts/lib"),
            Path("/sessions/exciting-sweet-curie/mnt/stytrix-techpack/scripts/lib"),
        ]:
            if (candidate / "extract_techpack.py").exists():
                _sys.path.insert(0, str(candidate))
                break
    from extract_techpack import extract

    folder = Path(folder_path_str)
    meta = _parse_folder_name(folder.name)
    eidh = meta["eidh"]
    client_code = _client_to_code(meta["client_raw"])

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        return {"eidh": eidh, "client_code": client_code, "design_id": meta["design_id"],
                "n_pdfs": 0, "mcs": [], "brand_division": None, "_status": "no_pdf"}

    best = None
    best_n_poms = -1
    for pdf in pdfs:
        try:
            result = extract(str(pdf))
            mcs = result.get("mcs", []) or []
            n_poms = sum(len(mc.get("poms", [])) for mc in mcs)
            if n_poms > best_n_poms:
                best_n_poms = n_poms
                best = result
                best["_pdf_path"] = str(pdf)
        except Exception as e:
            continue
    if best is None:
        return {"eidh": eidh, "client_code": client_code, "design_id": meta["design_id"],
                "n_pdfs": len(pdfs), "mcs": [], "brand_division": None,
                "_status": "all_pdfs_fail"}

    return {
        "eidh": eidh,
        "design_id": best.get("design_number") or meta["design_id"],
        "client_code": client_code,
        "brand_division": best.get("brand_division"),
        "department": best.get("department"),
        "category": best.get("bom_category"),
        "sub_category": best.get("sub_category"),
        "collection": best.get("collection"),
        "mcs": best.get("mcs", []),
        "n_pdfs": len(pdfs),
        "n_mcs": len(best.get("mcs", [])),
        "n_poms_total": best_n_poms,
        "_pdf": Path(best.get("_pdf_path", "")).name,
        "_status": "ok",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    folders = sorted(d for d in TP_DIR.iterdir() if d.is_dir())
    if args.limit:
        folders = folders[:args.limit]
    print(f"[scan] {TP_DIR}: {len(folders)} EIDH folders")

    t0 = time.time()
    by_status = Counter()
    by_client = Counter()
    by_client_with_mcs = Counter()
    n_total_mcs = 0
    n_total_poms = 0

    with open(OUT_JSONL, "w", encoding="utf-8") as fout, \
         ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_worker_extract, str(d)): d.name for d in folders}
        for i, fut in enumerate(as_completed(futs)):
            try:
                r = fut.result()
            except Exception as e:
                print(f"  [!] {futs[fut]}: {e}", file=sys.stderr)
                by_status["worker_err"] += 1
                continue
            if r is None:
                continue
            by_status[r.get("_status", "?")] += 1
            cl = r.get("client_code", "?")
            by_client[cl] += 1
            if r.get("mcs"):
                by_client_with_mcs[cl] += 1
                n_total_mcs += r.get("n_mcs", 0)
                n_total_poms += r.get("n_poms_total", 0)
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            if (i + 1) % 50 == 0:
                rate = (i + 1) / max(time.time() - t0, 0.1)
                eta_min = (len(folders) - i - 1) / rate / 60
                print(f"  [{i+1}/{len(folders)}] rate={rate:.1f}/s ETA={eta_min:.0f}min", flush=True)

    elapsed_min = (time.time() - t0) / 60
    print(f"\n[done] processed {sum(by_status.values())} folders in {elapsed_min:.1f} min")
    print(f"\nstatus breakdown:")
    for s, n in by_status.most_common():
        print(f"  {s:<20} {n:>6}")

    print(f"\n=== by client_code: 抽到 measurement chart 件數 ===")
    print(f"  {'client':<8} {'total':>7} {'w/mcs':>7} {'pct':>6}")
    for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]):
        t = by_client[cl]
        w = by_client_with_mcs[cl]
        pct = 100 * w / t if t else 0
        print(f"  {cl:<8} {t:>7} {w:>7} {pct:>5.0f}%")

    print(f"\ntotal mcs: {n_total_mcs:,}, total POM rows: {n_total_poms:,}")
    print(f"output: {OUT_JSONL}")

    # write stats
    with open(OUT_STATS, "w", encoding="utf-8") as f:
        f.write(f"extract_pom_from_tp.py — {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"folders: {len(folders)}\n")
        f.write(f"elapsed: {elapsed_min:.1f} min\n\n")
        f.write("status:\n")
        for s, n in by_status.most_common():
            f.write(f"  {s:<20} {n:>6}\n")
        f.write("\nby client_code:\n")
        f.write(f"  {'client':<8} {'total':>7} {'w/mcs':>7} {'pct':>6}\n")
        for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]):
            t = by_client[cl]
            w = by_client_with_mcs[cl]
            pct = 100 * w / t if t else 0
            f.write(f"  {cl:<8} {t:>7} {w:>7} {pct:>5.0f}%\n")
        f.write(f"\ntotal mcs: {n_total_mcs:,}\n")
        f.write(f"total POM rows: {n_total_poms:,}\n")
    print(f"stats: {OUT_STATS}")


if __name__ == "__main__":
    main()
