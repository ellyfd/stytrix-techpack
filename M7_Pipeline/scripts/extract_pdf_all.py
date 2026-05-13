"""extract_pdf_all.py — Unified PDF Techpack extractor (page-level dispatch).

對 tp_samples_v2/<EIDH>/*.pdf 跑 one-pass extraction:
  1. 對每頁跑 page_classifier.classify_page → 'cover' / 'construction' / 'measurement' / 'junk'
  2. 按 page type dispatch 到 client_parsers[client_code]:
       cover       → parse_cover()   → metadata facets
       construction → parse_construction_page() + render PNG  → construction_pages facets
       measurement → parse_measurement_chart()      → mcs facets
       junk        → skip
  3. 每件 EIDH 聚合成一筆 design dict (含 metadata + construction + mcs)
  4. 寫 outputs/extract/pdf_facets.jsonl (每行一個 EIDH)

不再呼叫舊的 extract_pdf_metadata.py / extract_techpack.py / extract_raw_text_m7.py (PDF 部分),
全 PDF 處理收斂在這支。

用法:
  python scripts/extract_pdf_all.py [--limit N] [--workers N]

需要:
  pip install pymupdf
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from collections import Counter, defaultdict

# import shared modules
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from page_classifier import classify_page  # noqa: E402
import client_parsers  # noqa: E402

ROOT = SCRIPT_DIR.parent
TP_DIR = ROOT / "tp_samples_v2"
MANIFEST_PATH = ROOT / "m7_organized_v2" / "_fetch_manifest.csv"
OUT_DIR = ROOT / "outputs" / "extract"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSONL = OUT_DIR / "pdf_facets.jsonl"
CONSTRUCTION_IMG_DIR = ROOT / "outputs" / "extract" / "pdf_construction_images"
# 2026-05-12 rename: pdf_construction_images → pdf_construction_images (見 PIPELINE_GLOSSARY.md)
CONSTRUCTION_IMG_DIR = CONSTRUCTION_IMG_DIR  # backward-compat alias, 之後可刪
CONSTRUCTION_IMG_DIR.mkdir(parents=True, exist_ok=True)
OUT_STATS = OUT_DIR / "extract_pdf_stats.txt"


# ════════════════════════════════════════════════════════════
# Folder name parsing (同 extract_pom_from_tp.py 邏輯)
# ════════════════════════════════════════════════════════════

KNOWN_CLIENT_TOKENS = [
    "DICKS_SPORTING_GOODS", "ABERCROMBIE_AND_FITCH",
    "OLD_NAVY", "GAP_OUTLET", "BANANA_REPUBLIC", "WAL-MART-CA",
    "GAP", "DICKS", "ATHLETA", "UNDER_ARMOUR", "KOHLS", "A_AND_F", "GU", "BEYOND_YOGA",
    "HIGH_LIFE_LLC", "WAL-MART", "QUINCE", "HALARA", "NET",
    "JOE_FRESH", "BRFS", "SANMAR", "DISTANCE", "ZARA",
    "ASICS-EU", "TARGET", "LEVIS", "CATO", "SMART_CLOTHING",
]

CLIENT_RAW_TO_CODE = {
    "OLD NAVY": "ONY", "TARGET": "TGT", "GAP": "GAP", "GAP OUTLET": "GAP",
    "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS", "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA", "KOHLS": "KOH", "A AND F": "ANF", "A & F": "ANF",
    "GU": "GU", "BEYOND YOGA": "BY", "HIGH LIFE LLC": "HLF", "WAL-MART": "WMT",
    "WAL-MART-CA": "WMT", "QUINCE": "QCE", "HALARA": "HLA", "NET": "NET",
    "JOE FRESH": "JF", "BANANA REPUBLIC": "BR", "BRFS": "BR", "SANMAR": "SAN",
    "DISTANCE": "DST", "ZARA": "ZAR", "ASICS-EU": "ASICS", "LEVIS": "LEV",
    "CATO": "CATO", "SMART CLOTHING": "SMC", "ABERCROMBIE AND FITCH": "ANF",
}


def _load_manifest_lookup() -> dict:
    """Load _fetch_manifest.csv → EIDH(str) → {客戶, 報價款號, Item, HEADER_SN}."""
    import csv
    lookup = {}
    if not MANIFEST_PATH.exists():
        print(f"  [!] manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return lookup
    with open(MANIFEST_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            eidh = (row.get("Eidh") or "").strip()
            if not eidh:
                continue
            lookup[eidh] = {
                "客戶": (row.get("客戶") or "").strip(),
                "報價款號": (row.get("報價款號") or "").strip(),
                "Item": (row.get("Item") or "").strip(),
                "HEADER_SN": (row.get("HEADER_SN") or "").strip(),
            }
    return lookup


# Worker 共用 lookup (module-level, multiprocessing initializer 會 set)
_MANIFEST_LOOKUP = {}


def _init_worker(manifest_lookup):
    """Pool initializer — 把 manifest lookup 傳到每個 worker process."""
    global _MANIFEST_LOOKUP
    _MANIFEST_LOOKUP = manifest_lookup


def _parse_folder_name(folder_name: str, manifest_lookup: dict = None) -> dict:
    """Parse folder name + manifest lookup → {eidh, client_raw, client_code, design_id}.

    folder 名是 `<EIDH>_<款>` 2-part 結構 (Pull-On Pilot 是 4-part 但全展開後簡化),
    所以 client / 款號 必須從 _fetch_manifest.csv 反查。
    """
    lookup = manifest_lookup if manifest_lookup is not None else _MANIFEST_LOOKUP
    parts = folder_name.split("_", 1)  # 只 split 一次, eidh = 第一段
    if len(parts) < 2:
        return {"eidh": None, "client_raw": None, "client_code": "UNKNOWN", "design_id": folder_name}
    eidh = parts[0]
    design_suffix = parts[1] if len(parts) > 1 else ""

    info = lookup.get(eidh, {})
    client_raw = info.get("客戶", "")
    design_id = info.get("報價款號") or design_suffix
    item = info.get("Item", "")
    hsn = info.get("HEADER_SN", "")
    client_code = CLIENT_RAW_TO_CODE.get(client_raw.upper().strip(), client_raw[:6].upper() if client_raw else "UNKNOWN")
    return {
        "eidh": eidh,
        "hsn": hsn,
        "client_raw": client_raw,
        "client_code": client_code,
        "design_id": design_id,
        "item": item,
    }


# ════════════════════════════════════════════════════════════
# Worker (per-EIDH)
# ════════════════════════════════════════════════════════════

def _worker_extract(folder_path_str: str) -> dict:
    """對單一 EIDH 資料夾跑 unified PDF extract."""
    try:
        import fitz
    except ImportError:
        return {"_status": "no_pymupdf"}

    folder = Path(folder_path_str)
    meta = _parse_folder_name(folder.name)
    eidh = meta["eidh"]
    client_code = meta["client_code"]
    parser = client_parsers.get_parser(client_code)

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        return {
            "eidh": eidh, "client_code": client_code,
            "design_id": meta["design_id"],
            "_status": "no_pdf",
        }

    facets = {
        "eidh": eidh,
        "design_id": meta["design_id"],
        "client_code": client_code,
        "client_raw": meta["client_raw"],
        "metadata": {},
        "construction_pages": [], # [{page, text, png_path}] — 構造說明頁 + PNG
        "measurement_charts": [], # POM 規格表 (per page)
        "source_files": [],
        "_status": "ok",
    }

    for pdf in pdfs:
        facets["source_files"].append(pdf.name)
        try:
            doc = fitz.open(str(pdf))
        except Exception as e:
            continue

        for i in range(doc.page_count):
            page = doc[i]
            text = page.get_text()
            ptype, evidence = classify_page(page, client_code)

            if ptype == "cover":
                cover_data = parser.parse_cover(page, text)
                if cover_data:
                    # merge (keep first non-empty per key)
                    for k, v in cover_data.items():
                        if v and not facets["metadata"].get(k):
                            facets["metadata"][k] = v

            elif ptype == "construction":
                # render PNG (構造說明頁)
                try:
                    png_path = CONSTRUCTION_IMG_DIR / f"{client_code}_{meta['design_id']}_{pdf.stem[:30]}_p{i+1}.png"
                    pix = page.get_pixmap(dpi=120)
                    pix.save(str(png_path))
                    rel_png = png_path.relative_to(ROOT).as_posix()
                except Exception:
                    rel_png = None
                # parse structured construction items (mostly fallback to raw text for now)
                parsed_items = parser.parse_construction_page(page, text)
                facets["construction_pages"].append({
                    "pdf": pdf.name,
                    "page": i + 1,
                    "score": evidence.get("score"),
                    "png": rel_png,
                    "construction_items": parsed_items,
                })

            elif ptype == "measurement":
                mc = parser.parse_measurement_chart(page, text)
                if mc:
                    mc["_source_pdf"] = pdf.name
                    mc["_source_page"] = i + 1
                    facets["measurement_charts"].append(mc)
                    # 2026-05-12 加: MC page metadata promotion
                    # 對「整 PDF 只有 MC page (沒 cover sheet)」的 EIDH (e.g. GAP D66015 MC supplement),
                    # 從 MC fields 提升到 entry metadata. 只填空白欄位, 不覆寫已有 cover meta.
                    COVER_FIELDS = ["season", "brand_division", "department",
                                    "collection", "design_number", "size_range",
                                    "status", "mc_key"]
                    for k in COVER_FIELDS:
                        v = mc.get(k)
                        if v and not facets["metadata"].get(k):
                            facets["metadata"][k] = v
                else:
                    # 沒 parse 到結構化 mc, 但 page type 認得是 measurement —
                    # 留 raw_text 給之後 brand parser 用
                    facets["measurement_charts"].append({
                        "_source_pdf": pdf.name,
                        "_source_page": i + 1,
                        "_raw_text": text[:3000],
                        "_unparsed": True,
                    })
            # junk: skip
        doc.close()

    return facets


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--client", help="只跑特定 brand code (filter folder)")
    p.add_argument("--reset", action="store_true",
                   help="--client 模式時清掉整個 jsonl 重抽 (預設保留其他 brand 的舊資料)")
    args = p.parse_args()

    # Load _fetch_manifest.csv 反查 EIDH → 客戶 mapping
    manifest_lookup = _load_manifest_lookup()
    print(f"[manifest] loaded {len(manifest_lookup):,} EIDH lookup entries")
    # main process 也要 set global, 給 single-thread 跟 client filter 用
    global _MANIFEST_LOOKUP
    _MANIFEST_LOOKUP = manifest_lookup

    folders = sorted(d for d in TP_DIR.iterdir() if d.is_dir())
    if args.client:
        folders = [f for f in folders if _parse_folder_name(f.name, manifest_lookup)["client_code"] == args.client]
    if args.limit:
        folders = folders[:args.limit]
    print(f"[scan] {TP_DIR}: {len(folders)} EIDH folders (client={args.client or 'all'})")

    # === 2026-05-12 改: per-brand 獨立輸出檔案 ===
    # 之前用 incremental 模式 (保留其他 brand 既有資料), 但有 race 風險:
    # 任何 --client X 失敗都可能弄壞中央 pdf_facets.jsonl
    # 改成: --client X 寫 pdf_facets_X.jsonl, 各 brand 完全隔離.
    # 最後用 merge_pdf_facets.py 合併成中央 pdf_facets.jsonl.
    if args.client:
        out_jsonl = OUT_JSONL.parent / f"pdf_facets_{args.client}.jsonl"
        out_stats = OUT_JSONL.parent / f"extract_pdf_stats_{args.client}.txt"
        print(f"[per-brand output] {out_jsonl}")
    else:
        out_jsonl = OUT_JSONL
        out_stats = OUT_STATS
        print(f"[全 run output] {out_jsonl}")
    preserved_lines = []  # per-brand 模式不需要 preserve, 直接 fresh write

    t0 = time.time()
    stats = Counter()
    by_client = defaultdict(lambda: {"total": 0, "metadata": 0, "construction_pages": 0, "measurement_charts": 0})

    # Chunked pool 策略 (2026-05-12):
    # - 不用 max_tasks_per_child (在 Windows + Python 3.14 會 respawn 時 deadlock)
    # - 改成每 CHUNK 件開一個全新 pool, 跑完 pool 自然 destroy 釋放所有資源
    # - 每塊內部仍有 per-task watchdog 防單一 PDF hang
    # - 800/3041 全死的根因: 5 workers * 200 max_tasks 同時 respawn → pool 鎖死
    CHUNK = 400
    PER_TASK_TIMEOUT = 90  # 單個 PDF 90s 沒結果就 cancel
    pool_kwargs_base = {
        "max_workers": args.workers,
        "initializer": _init_worker,
        "initargs": (manifest_lookup,),
    }
    import concurrent.futures as _cf
    i = 0
    with open(out_jsonl, "w", encoding="utf-8") as fout:
        # 先寫回保留的其他 brand entries
        for line in preserved_lines:
            fout.write(line + "\n")

        for chunk_idx in range(0, len(folders), CHUNK):
            chunk = folders[chunk_idx:chunk_idx + CHUNK]
            print(f"  [chunk {chunk_idx//CHUNK + 1}/{(len(folders)+CHUNK-1)//CHUNK}] "
                  f"{len(chunk)} folders ({chunk_idx+1}-{chunk_idx+len(chunk)})", flush=True)

            with ProcessPoolExecutor(**pool_kwargs_base) as ex:
                submit_t = {}
                futures = {}
                for d in chunk:
                    fut = ex.submit(_worker_extract, str(d))
                    futures[fut] = d.name
                    submit_t[fut] = time.time()
                pending = set(futures.keys())

                while pending:
                    done, pending = _cf.wait(pending, timeout=5, return_when=_cf.FIRST_COMPLETED)
                    now = time.time()
                    # 掃 pending: 任何 task 超過 PER_TASK_TIMEOUT 就 cancel
                    hung = [f for f in pending if (now - submit_t[f]) > PER_TASK_TIMEOUT]
                    for fut in hung:
                        fut.cancel()
                        print(f"  [!] timeout({PER_TASK_TIMEOUT}s): {futures[fut]}", file=sys.stderr)
                        stats["timeout"] += 1
                        i += 1
                    pending -= set(hung)
                    for fut in done:
                        i += 1
                        try:
                            r = fut.result(timeout=5)
                        except Exception as e:
                            print(f"  [!] {futures[fut]}: {e}", file=sys.stderr)
                            stats["worker_err"] += 1
                            continue
                        status = r.get("_status", "?")
                        stats[status] += 1
                        cl = r.get("client_code", "UNKNOWN")
                        by_client[cl]["total"] += 1
                        if r.get("metadata"): by_client[cl]["metadata"] += 1
                        if r.get("construction_pages"): by_client[cl]["construction_pages"] += 1
                        if r.get("measurement_charts"):      by_client[cl]["measurement_charts"] += 1
                        fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                        if i % 50 == 0:
                            rate = i / max(time.time() - t0, 0.1)
                            eta = (len(folders) - i) / rate / 60
                            print(f"  [{i}/{len(folders)}] rate={rate:.1f}/s ETA={eta:.0f}min", flush=True)
            # pool destroyed here — 所有 worker 強制清掉, 下一塊重開新的
            fout.flush()

    elapsed_min = (time.time() - t0) / 60
    print(f"\n[done] {sum(stats.values())} folders in {elapsed_min:.1f} min")
    print(f"\nstatus:")
    for s, n in stats.most_common():
        print(f"  {s:<15} {n:>6}")

    print(f"\n=== by client (抽到 metadata / construction_pages / measurement_charts 件數) ===")
    print(f"  {'client':<8} {'total':>7} {'meta':>6} {'construction':>12} {'measurement_charts':>18}")
    for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]["total"]):
        d = by_client[cl]
        print(f"  {cl:<8} {d['total']:>7} {d['metadata']:>6} {d['construction_pages']:>8} {d['measurement_charts']:>6}")

    # Stats file
    try:
        with open(out_stats, "w", encoding="utf-8") as f:
            f.write(f"folders={sum(stats.values())} elapsed_min={elapsed_min:.1f}\n")
            for s, n in stats.most_common():
                f.write(f"  {s}: {n}\n")
            f.write("by_client:\n")
            for cl in sorted(by_client.keys(), key=lambda x: -by_client[x]["total"]):
                d = by_client[cl]
                f.write(f"  {cl}: total={d['total']} meta={d['metadata']} callout={d['construction_pages']} mcs={d['measurement_charts']}\n")
    except Exception as e:
        print(f"[!] stats write failed: {e}", file=__import__('sys').stderr)

    print(f"\noutput: {out_jsonl}")
    print(f"construction PNGs: {CONSTRUCTION_IMG_DIR}")
    print(f"stats: {out_stats}")


if __name__ == "__main__":
    main()
