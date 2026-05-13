"""
extract_raw_text_m7.py — M7 PullOn 多客戶版 extractor

跟 Download0504/star_schema/scripts/extract_raw_text.py 對應，但：
  - design_id 從 PullOn 命名 <EIDH>_<HSN>_<Customer>_<Style> 拆，不靠 PDF 內文
  - metadata 從 M7 索引 xlsx join，不從 PDF 抽
  - ClientAdapter pattern：每客戶一個 detector
  - 輸出 schema 跟 Download0504 完全一致 (designs.jsonl + pptx/<ID>.txt + pdf/callout_images/<ID>_pN.png)
  - PPTX/PDF 處理 helper 直接 import Download0504 的（detect_construction_pages / render_pdf_pages / extract_pptx_text / pptx_to_txt）

design_id 設計：
  jsonl 裡 design_id = 客戶 native style (e.g. "319260002", "DAG17103_Q127", "D99407")
  + 加 client 欄 (e.g. "AF", "DICKS", "ONY") 當 namespace
  跨客戶真 PK = (client, design_id)
  檔名用 design_id_full = "{client}_{design_id}" 避免撞號 (AF_319260002, DICKS_DAG17103_Q127)

用法：
  python scripts/extract_raw_text_m7.py \\
      --scan-dir ../stytrix-pipeline-Download0504/data/ingest/uploads \\
      --output-dir ../stytrix-pipeline-Download0504/data/ingest \\
      --m7-index M7資源索引_M7URL正確版_20260504.xlsx \\
      --sheet 新做工_PullOn \\
      --force
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

# import Download0504 的 helpers
ROOT = Path(__file__).resolve().parent.parent
SOURCE_DATA = ROOT.parent
DL_SCRIPTS = SOURCE_DATA / "stytrix-pipeline-Download0504" / "star_schema" / "scripts"
sys.path.insert(0, str(DL_SCRIPTS))

from extract_raw_text import (  # noqa: E402
    extract_pptx_text,
    pptx_to_txt,
    detect_construction_pages as _detect_dl,  # Download0504 版只看 text-layer
    render_pdf_pages,
    scan_files,
)


# PullOn 版 detect_construction_pages 已抽到 shared/pdf_helpers.py
from shared.pdf_helpers import detect_construction_pages, is_centric8_non_construction  # noqa: E402

# 保留舊 alias 給 backward compat (內部 _ 開頭的 helpers 不對外，純讓 import 可用)
_is_centric8_non_construction = is_centric8_non_construction


# ════════════════════════════════════════════════════════════
# CLIENT ADAPTERS
# ════════════════════════════════════════════════════════════

class ClientAdapter:
    """Base：認檔案、拆 design_id"""
    code = ""
    label = ""

    def detect(self, file_path: str, m7_row: dict | None = None) -> bool:
        """看檔案/M7 row 認不認得"""
        raise NotImplementedError

    def style_from_path(self, file_path: str) -> str | None:
        """從路徑拆出 native style number"""
        raise NotImplementedError


class M7FilenameAdapter(ClientAdapter):
    """
    通用 PullOn 命名 adapter：<EIDH>_<HSN>_<Customer>_<Style>.<ext>
    從 M7 索引 join EIDH 取得真 client + style，不靠檔名 hard-code 客戶名。
    """
    code = "M7"
    label = "M7 PullOn (filename pattern)"

    def __init__(self, eidh_to_meta: dict):
        # eidh -> {客戶, 報價款號, ...}
        self.eidh_to_meta = eidh_to_meta

    def parse_eidh(self, file_path: str) -> int | None:
        """檔名前綴是 EIDH(純數字 6 位),失敗 fallback 看父目錄

        兩種結構都能 work:
        - m7_organized_v2/pdf_tp/304080_10405493_OLD_NAVY_ONY25HOVDD01_2.pdf  (扁平,EIDH 在 filename)
        - tp_samples_v2/304080_ONY25HOVDD01_2/TPK24100218520_xxx.pdf          (子目錄,EIDH 在 parent dir)
        """
        # Try 1: filename 前綴
        name = os.path.basename(file_path)
        m = re.match(r"^(\d{6,7})_", name)
        if m:
            return int(m.group(1))
        # Try 2: 父目錄前綴(tp_samples_v2 結構)
        parent = os.path.basename(os.path.dirname(file_path))
        m = re.match(r"^(\d{6,7})_", parent)
        if m:
            return int(m.group(1))
        return None

    def detect(self, file_path: str, m7_row=None) -> bool:
        eidh = self.parse_eidh(file_path)
        return eidh is not None and eidh in self.eidh_to_meta

    def get_meta(self, file_path: str) -> dict | None:
        eidh = self.parse_eidh(file_path)
        return self.eidh_to_meta.get(eidh) if eidh else None


# ── client code 標準化 — 抽到 m7_constants.py ──
from m7_constants import CUSTOMER_TO_CODE, normalize_client  # noqa: E402, F401


# ════════════════════════════════════════════════════════════
# M7 INDEX LOAD + DESIGN_ID RESOLVE
# ════════════════════════════════════════════════════════════

def load_m7_index(xlsx_path: Path, sheet: str) -> dict:
    """讀 M7 索引，return {eidh: row_dict}（新版「總表」自動套 ITEM_FILTER）"""
    # 2026-05-08：新版 sheet「總表」18,731 row，要 filter Item; 舊版「新做工_PullOn」1,180 不用
    is_new_index = xlsx_path.name.startswith("M7列管") or sheet == "總表"
    if is_new_index:
        # 用共用 helper 套 ITEM_FILTER
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from m7_eidh_loader import load_m7_index as _load
        df = _load()
    else:
        df = pd.read_excel(xlsx_path, sheet_name=sheet, engine="openpyxl")
    out = {}
    for _, row in df.iterrows():
        eidh = row.get("Eidh")
        if pd.isna(eidh):
            continue
        eidh = int(eidh)
        out[eidh] = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
    print(f"[index] M7 索引: {len(out)} EIDH")
    return out


def resolve_design_id(file_path: str, adapter: M7FilenameAdapter) -> tuple[str | None, str | None, dict | None]:
    """
    Returns (client_code, design_id, m7_meta).
    design_id = 客戶 native style number (e.g. "319260002", "D99407").
    """
    if not adapter.detect(file_path):
        return None, None, None
    meta = adapter.get_meta(file_path)
    if not meta:
        return None, None, None
    customer = str(meta.get("客戶") or "")
    style = str(meta.get("報價款號") or "").strip()
    if not style:
        return None, None, None
    return normalize_client(customer), style, meta


def design_id_full(client: str, design_id: str) -> str:
    """檔名安全完整 ID (client_designid)，避免跨客戶撞號"""
    safe = re.sub(r"[^\w\-]", "_", design_id)
    return f"{client}_{safe}"


# ════════════════════════════════════════════════════════════
# METADATA: 從 M7 索引產 designs.jsonl row
# ════════════════════════════════════════════════════════════

def m7_to_designs_row(client: str, design_id: str, m7_meta: dict, source_file: str, total_pages: int) -> dict:
    """
    把 M7 索引一筆 row 轉成 Download0504 designs.jsonl schema：
      design_id, design_name, season, brand_division, department, collection,
      category, sub_category, design_type, design_sub_type, fit_camp, rise,
      status, bom_number, vendor, source_file, total_pages
    + M7 加碼欄（不破 schema，新增）：
      client, eidh, header_sn, item, program, subgroup, wk, ie_minutes,
      ie_person, follower, fit_master, area
    """
    customer = str(m7_meta.get("客戶") or "")
    return {
        # === Download0504 標準欄 ===
        "design_id": design_id,
        "design_name": str(m7_meta.get("Item") or ""),  # "Pull On Pants"
        "season": str(m7_meta.get("Season") or ""),    # "I-SU 2027"
        "brand_division": customer,                     # "DICKS SPORTING GOODS"
        "department": "",                               # M7 索引沒這欄
        "collection": str(m7_meta.get("Program") or ""),  # "AIM_OTHERS" / "CA"
        "category": str(m7_meta.get("Subgroup") or ""),   # "D214" / "#D23"
        "sub_category": "",
        "design_type": str(m7_meta.get("W/K") or ""),   # "Woven" / "Knit"
        "design_sub_type": "",
        "fit_camp": "",
        "rise": "",
        "status": str(m7_meta.get("狀態") or ""),
        "bom_number": str(int(m7_meta["HEADER_SN"])) if m7_meta.get("HEADER_SN") else "",
        "vendor": "",
        "source_file": source_file,
        "total_pages": total_pages,
        # === M7 加碼欄 ===
        "client": client,                                # "DICKS"
        "eidh": int(m7_meta["Eidh"]) if m7_meta.get("Eidh") else None,
        "header_sn": int(m7_meta["HEADER_SN"]) if m7_meta.get("HEADER_SN") else None,
        "item": str(m7_meta.get("Item") or ""),
        "program": str(m7_meta.get("Program") or ""),
        "subgroup": str(m7_meta.get("Subgroup") or ""),
        "wk": str(m7_meta.get("W/K") or ""),
        "ie_minutes": float(m7_meta["IE"]) if m7_meta.get("IE") and pd.notna(m7_meta.get("IE")) else None,
        "ie_person": str(m7_meta.get("IE人員") or ""),
        "follower": str(m7_meta.get("Follower") or ""),
        "fit_master": str(m7_meta.get("大貨技師") or ""),
        "area": str(m7_meta.get("產區") or ""),
    }


# ════════════════════════════════════════════════════════════
# BATCH RUNNERS
# ════════════════════════════════════════════════════════════

def run_metadata_batch_m7(scan_dir: str, output_dir: str, adapter: M7FilenameAdapter, force: bool):
    """從 M7 索引 + PDF/PPTX 檔案 → designs.jsonl"""
    print(f"[METADATA] Scanning {scan_dir}...")
    pdf_files = scan_files(scan_dir, ".pdf")
    pptx_files = scan_files(scan_dir, ".pptx")
    all_files = pdf_files + pptx_files
    print(f"[METADATA] Found {len(pdf_files)} PDF + {len(pptx_files)} PPTX")

    # 用 PDF 優先（有 total_pages 資訊），PPTX 補
    seen_did = {}  # design_id_full -> dict
    for f in pdf_files:
        client, design_id, meta = resolve_design_id(f, adapter)
        if not design_id:
            continue
        full_id = design_id_full(client, design_id)
        if full_id in seen_did:
            continue
        # 取 PDF 頁數
        try:
            import fitz
            doc = fitz.open(f)
            total_pages = len(doc)
            doc.close()
        except Exception:
            total_pages = 0
        row = m7_to_designs_row(client, design_id, meta, os.path.basename(f), total_pages)
        seen_did[full_id] = row

    # PPTX 可能有但 PDF 沒對應的 EIDH
    for f in pptx_files:
        client, design_id, meta = resolve_design_id(f, adapter)
        if not design_id:
            continue
        full_id = design_id_full(client, design_id)
        if full_id in seen_did:
            continue
        row = m7_to_designs_row(client, design_id, meta, os.path.basename(f), 0)
        seen_did[full_id] = row

    no_id = len(all_files) - sum(1 for f in all_files
                                  if resolve_design_id(f, adapter)[1])
    print(f"[METADATA] {len(seen_did)} unique designs ({no_id} files without design_id)")

    meta_dir = os.path.join(output_dir, "metadata")
    os.makedirs(meta_dir, exist_ok=True)
    out_path = os.path.join(meta_dir, "designs.jsonl")

    if not force and os.path.exists(out_path):
        existing = set()
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    existing.add(design_id_full(r.get("client", ""), r.get("design_id", "")))
        new = {k: v for k, v in seen_did.items() if k not in existing}
        mode = "a"
        print(f"[METADATA] existing {len(existing)}, new {len(new)}")
        seen_did = new
    else:
        mode = "w"

    with open(out_path, mode, encoding="utf-8") as f:
        for full_id in sorted(seen_did):
            f.write(json.dumps(seen_did[full_id], ensure_ascii=False) + "\n")
    print(f"[METADATA] Done: {len(seen_did)} written → {out_path}")


def run_pptx_batch_m7(scan_dir: str, output_dir: str, adapter: M7FilenameAdapter, force: bool):
    """PPTX → txt（檔名 {client}_{design_id}.txt）"""
    print(f"[PPTX] Scanning {scan_dir}...")
    files = scan_files(scan_dir, ".pptx")
    print(f"[PPTX] Found {len(files)} PPTX")

    pptx_out = os.path.join(output_dir, "pptx")
    os.makedirs(pptx_out, exist_ok=True)
    success = errors = no_id = 0

    for f in files:
        client, design_id, _ = resolve_design_id(f, adapter)
        if not design_id:
            no_id += 1
            continue
        full_id = design_id_full(client, design_id)
        out_path = os.path.join(pptx_out, f"{full_id}.txt")
        if not force and os.path.exists(out_path):
            continue
        try:
            pptx_to_txt(f, out_path)
            success += 1
        except Exception as e:
            print(f"  ERROR {full_id}: {e}", file=sys.stderr)
            errors += 1

    print(f"[PPTX] Done: {success} extracted, {errors} errors, {no_id} skipped")


def run_pdf_batch_m7(scan_dir: str, output_dir: str, adapter: M7FilenameAdapter,
                     force: bool, batch_start: int = 0, batch_size: int = 0):
    """PDF → callout PNG + manifest

    batch_start / batch_size: 分批處理。size=0 表示全跑。
    """
    print(f"[PDF->PNG] Scanning {scan_dir}...")
    files = sorted(scan_files(scan_dir, ".pdf"))
    print(f"[PDF->PNG] Found {len(files)} PDF (total)")
    if batch_size > 0:
        end = batch_start + batch_size
        files = files[batch_start:end]
        print(f"[PDF->PNG] Batch: rows {batch_start}..{end-1} -> {len(files)} PDF this run")

    # 2026-05-07：output_dir 末段 == "m7_organized_v2" 時走 flat layout（單一資料源）
    # 否則維持舊 nested layout（Download0504 相容）
    if os.path.basename(os.path.normpath(output_dir)) == "m7_organized_v2":
        img_dir = os.path.join(output_dir, "callout_images")
        manifest_path = os.path.join(output_dir, "callout_manifest.jsonl")
    else:
        img_dir = os.path.join(output_dir, "pdf", "callout_images")
        manifest_path = os.path.join(output_dir, "pdf", "callout_manifest.jsonl")
    os.makedirs(img_dir, exist_ok=True)

    open_mode = "a" if (not force or batch_start > 0) else "w"
    total_designs = total_pages = no_callout = errors = no_id = 0
    with open(manifest_path, open_mode, encoding="utf-8") as manifest_f:
        for f in files:
            client, design_id, _ = resolve_design_id(f, adapter)
            if not design_id:
                no_id += 1
                continue
            full_id = design_id_full(client, design_id)
            try:
                pages = detect_construction_pages(f)
                if not pages:
                    no_callout += 1
                    continue
                rendered = render_pdf_pages(f, pages, img_dir, full_id)
                total_designs += 1
                total_pages += len(rendered)
                for r in rendered:
                    r["client"] = client
                    r["design_id"] = design_id
                    manifest_f.write(json.dumps(r, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"  ERROR {full_id}: {e}", file=sys.stderr)
                errors += 1

    print(f"[PDF->PNG] Done: {total_designs} designs / {total_pages} pages, {no_callout} no callouts, {errors} errors, {no_id} skipped")


def main():
    p = argparse.ArgumentParser(description="M7 PullOn raw text extractor")
    p.add_argument("--scan-dir", required=True)
    p.add_argument("--output-dir", required=True)
    # 2026-05-08：default 改新版 5/7 索引「總表」sheet（套 ITEM_FILTER PullOn+Leggings）
    _new_idx = ROOT.parent / "M7列管_20260507.xlsx"
    _old_idx = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
    p.add_argument("--m7-index", default=str(_new_idx if _new_idx.exists() else _old_idx))
    p.add_argument("--sheet", default="總表" if _new_idx.exists() else "新做工_PullOn")
    p.add_argument("--force", action="store_true")
    p.add_argument("--metadata-only", action="store_true")
    p.add_argument("--pptx-only", action="store_true")
    p.add_argument("--pdf-only", action="store_true")
    p.add_argument("--batch-start", type=int, default=0)
    p.add_argument("--batch-size", type=int, default=0)
    args = p.parse_args()

    eidh_to_meta = load_m7_index(Path(args.m7_index), args.sheet)
    adapter = M7FilenameAdapter(eidh_to_meta)

    if not (args.pptx_only or args.pdf_only):
        run_metadata_batch_m7(args.scan_dir, args.output_dir, adapter, args.force)
    if not (args.metadata_only or args.pdf_only):
        run_pptx_batch_m7(args.scan_dir, args.output_dir, adapter, args.force)
    if not (args.metadata_only or args.pptx_only):
        run_pdf_batch_m7(args.scan_dir, args.output_dir, adapter, args.force,
                         args.batch_start, args.batch_size)


if __name__ == "__main__":
    main()
