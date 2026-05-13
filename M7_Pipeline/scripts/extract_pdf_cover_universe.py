"""extract_pdf_cover_universe.py — 抽每客戶 PDF cover page 所有 (key, value) pair

目標:不靠 hardcoded adapter,自動 detect PDF 第 1 頁所有 label-value pair。
per-客戶 aggregate → 找出該客戶 PDF cover page 真實出現的最大化欄位 + 每欄所有 unique values(attributes)。

用 PyMuPDF (fitz) 讀 PDF 第 1-2 頁,套 3 種 layout detector:
  A. "Key\\nValue\\n"     上下排(Centric 8 style: ONY / KOHLS / GAP)
  B. "Key: Value"         同行 with colon(DSG: DICKS)
  C. 表格 cells           用 fitz.get_text("blocks") 找 key-value 鄰接 block

跑:python scripts/extract_pdf_cover_universe.py [--limit N] [--client CLIENT]
Output:
  outputs/platform/pdf_cover_universe.jsonl   (per-PDF raw label-values)
  outputs/platform/pdf_cover_universe.summary.json (per-客戶 unique keys + value 分布)
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
TP_SAMPLES = ROOT / "tp_samples_v2"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "pdf_cover_universe.jsonl"
SUMMARY_PATH = OUT_DIR / "pdf_cover_universe.summary.json"

sys.path.insert(0, str(ROOT / "scripts"))
from m7_eidh_loader import load_m7_index  # noqa: E402

# ════════════════════════════════════════════════════════════
# Generic key-value detectors (no hardcoded labels)
# ════════════════════════════════════════════════════════════

# Common label heuristics:
# - 1-5 word label, mostly Latin / Title Case / ends with optional ":"
# - value follows immediately or on next line
# - skip if value looks like another label

# Label regex 擴充:
# 1. ASCII Title Case: "Brand/Category" "Style No.", "Body Fabric"
# 2. ALL CAPS: "STYLE#" "DATE ISSUED"
# 3. with #: "STYLE#:" "Style#:"
# 4. 日文 / 中文 label: "デザイン名" "企業" "シーズン" (CJK Unified)
LABEL_RE = re.compile(
    r"^\s*([A-Z#][A-Za-z0-9#][A-Za-z0-9 /\.\-_#]{0,50}?|"  # English Title Case / ALL CAPS
    r"[぀-ゟ゠-ヿ一-鿿]{1,15})"     # Japanese hiragana/katakana/kanji (1-15 chars)
    r"\s*[:：#]?\s*$"
)
LABEL_WITH_VALUE_RE = re.compile(
    r"^\s*([A-Z#][A-Za-z0-9#][A-Za-z0-9 /\.\-_#]{0,50}?|"
    r"[぀-ゟ゠-ヿ一-鿿]{1,15})"
    r"\s*[:：#]\s*(.+?)\s*$"
)

# Noise stop-list — 純系統 metadata,不是業務 label
# 注意:trim / fabric / material 不在這(它們是真實 label,例 ONY 的 Body Fabric / Trim)
STOP_KEYS = {
    # Centric 8 status values that look like labels
    "adopted", "concept", "created", "modified", "tech pack", "centric",
    "centric 8", "production", "draft", "pending", "in progress",
    "completed", "cancelled", "approved",
    # System metadata column headers
    "by", "from", "to", "page", "revision", "version", "page no",
    "header", "footer", "section",
    # Common ambiguous single-word(這些常出現但通常是 value 不是 label)
    "self", "color", "qty", "comments", "ref", "spec",
}

# Keys we actively want (always treat as valid label)
ALLOW_KEYS = {
    "style number", "style no", "style no.", "style code", "style name",
    "style#", "style #", "style description",
    "bom number", "bom no", "tech pack number",
    "design season", "season", "design brand/division", "brand division", "brand",
    "brand/category", "brand/ category",
    "design department", "department", "design collection", "collection",
    "design category", "category", "sub-category", "subcategory",
    "design status", "design type", "design sub-type",
    "body fabric", "fabric content", "material", "fabric type", "trim",
    "fit camp", "fit", "rise", "size range", "size category",
    "approval date", "due date", "in dc date", "approval", "vendor",
    "designer", "follower", "fit master", "merchandiser",
    "gender", "product team", "regional fit",
    "construction detail", "description", "name",
    # Japanese labels (GU)
    "企業", "デザイン名", "ブランド", "アイテム", "シーズン", "ページ",
    "品番", "パーツ数", "サイズ", "縮尺", "作成者", "デザイナー",
    "作成日", "更新日", "出力日",
}


def is_likely_label(s: str) -> bool:
    """Heuristic: looks like a metadata label (英文 Title/ALL CAPS or 日文/中文)"""
    s = s.strip()
    if not s or len(s) > 60:
        return False
    if any(ch in s for ch in "0123456789"):
        digit_pct = sum(1 for c in s if c.isdigit()) / len(s)
        if digit_pct > 0.3:
            return False
    if s.startswith(("$", "USD", "%", "TPK", "TP-")):
        return False
    s_lower = s.lower().rstrip(":：#").strip()
    if s_lower in STOP_KEYS:
        return False
    return bool(LABEL_RE.match(s))


def is_allowed_label(s: str) -> bool:
    """Allow-list: definitely a real label even if heuristic would skip"""
    return s.lower().rstrip(":：#").strip() in ALLOW_KEYS


def is_likely_value(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 200:
        return False
    return True


def detect_label_value_pairs(text: str) -> list[tuple[str, str]]:
    """從 PDF 第 1 頁文字 detect (key, value) tuples,用 2 種 layout heuristic + noise filter"""
    out = []
    lines = [l.strip() for l in text.split("\n")]
    lines = [l for l in lines if l]  # skip blank lines

    # Pattern B: "Key: Value" 同行 — 強訊號(有 colon)
    for line in lines:
        m = LABEL_WITH_VALUE_RE.match(line)
        if m:
            label = m.group(1).strip()
            value = m.group(2).strip()
            if is_likely_value(value):
                # Allow-list 跳 noise filter,否則套 stop-list
                if is_allowed_label(label) or is_likely_label(label):
                    out.append((label, value))

    # Pattern A: Key (前一行) + Value (下一行)
    # 只接受多字 label(>= 2 words)減少噪音,或 allow-list
    for i in range(len(lines) - 1):
        line_a = lines[i]
        line_b = lines[i + 1]
        if not LABEL_RE.match(line_a):
            continue
        if LABEL_WITH_VALUE_RE.match(line_a):
            continue  # 已被 Pattern B 處理
        if not is_likely_value(line_b):
            continue
        if is_likely_label(line_b):
            continue  # 下一行像另一個 label 就跳
        label = line_a.rstrip(":：").strip()
        # Pattern A 比較弱訊號:必須是 multi-word OR CJK label OR allow-list 才算
        is_multi_word = len(label.split()) >= 2
        # CJK label(日文/中文)1 字也算真 label
        has_cjk = any('぀' <= c <= 'ヿ' or '一' <= c <= '鿿' for c in label)
        if not (is_allowed_label(label) or is_multi_word or has_cjk or is_likely_label(label)):
            continue
        # 套 stop-list (不論 allow 還是 multi-word 還是 generic)
        if label.lower().rstrip(":：").strip() in STOP_KEYS:
            continue
        out.append((label, line_b.strip()))

    # Dedup (same key+value)
    seen = set()
    deduped = []
    for k, v in out:
        sig = (k.lower(), v.lower())
        if sig not in seen:
            seen.add(sig)
            deduped.append((k, v))
    return deduped


def extract_cover_text(pdf_path: Path, max_pages: int = 2) -> str:
    """讀 PDF 前 N 頁文字"""
    try:
        doc = fitz.open(str(pdf_path))
        n = min(doc.page_count, max_pages)
        text = "\n".join(doc[i].get_text() for i in range(n))
        doc.close()
        return text
    except Exception as e:
        print(f"  [!] {pdf_path.name}: {e}", file=sys.stderr)
        return ""


# ════════════════════════════════════════════════════════════
# Walk tp_samples_v2/<EIDH>_<style>/*.pdf
# ════════════════════════════════════════════════════════════

def walk_pdfs(scan_root: Path):
    """yield (eidh, pdf_path) for every PDF under tp_samples_v2/<EIDH>_<style>/"""
    for subdir in sorted(scan_root.iterdir()):
        if not subdir.is_dir():
            continue
        m = re.match(r"^(\d{6,7})_", subdir.name)
        if not m:
            continue
        eidh = int(m.group(1))
        for f in subdir.glob("*.pdf"):
            yield (eidh, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="limit total PDFs processed (0 = no limit)")
    ap.add_argument("--client", default=None,
                    help="only process EIDH belonging to this client (M7 列管 客戶 substring match)")
    ap.add_argument("--max-pages", type=int, default=2,
                    help="how many pages from start to read (default 2)")
    args = ap.parse_args()

    # Load M7 index → eidh -> client
    print("[1] Load M7 index")
    df = load_m7_index()
    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    eidh_to_client = {}
    for _, row in df.iterrows():
        e = row.get("Eidh")
        if e:
            eidh_to_client[int(e)] = str(row["客戶_clean"])
    print(f"    {len(eidh_to_client)} EIDH → client mapping")

    # Walk PDFs
    print(f"\n[2] Walk {TP_SAMPLES}")
    pdfs = list(walk_pdfs(TP_SAMPLES))
    print(f"    Found {len(pdfs):,} PDFs across {len(set(e for e, _ in pdfs)):,} EIDH")

    # Filter by client if requested
    if args.client:
        flt = args.client.upper()
        pdfs = [(e, p) for e, p in pdfs if flt in eidh_to_client.get(e, "")]
        print(f"    Filtered to {len(pdfs):,} PDFs (client contains {args.client!r})")
    if args.limit:
        pdfs = pdfs[:args.limit]
        print(f"    Limited to first {len(pdfs):,}")

    # Extract per PDF
    print(f"\n[3] Extract cover-page label-values")
    n_processed = 0
    n_with_pairs = 0
    n_pairs_total = 0
    by_client_keys = defaultdict(lambda: defaultdict(Counter))   # client → key → Counter(value)
    by_client_key_pdf_set = defaultdict(lambda: defaultdict(set)) # client → key → set of pdf_path strings (for unique PDF count)
    by_client_n_pdfs = defaultdict(int)

    with open(OUT_PATH, "w", encoding="utf-8") as fout:
        for eidh, pdf_path in pdfs:
            client = eidh_to_client.get(eidh, "UNKNOWN")
            text = extract_cover_text(pdf_path, max_pages=args.max_pages)
            if not text:
                continue
            pairs = detect_label_value_pairs(text)
            n_processed += 1
            by_client_n_pdfs[client] += 1
            if pairs:
                n_with_pairs += 1
                n_pairs_total += len(pairs)
                pdf_id = str(pdf_path)
                for k, v in pairs:
                    by_client_keys[client][k][v] += 1
                    by_client_key_pdf_set[client][k].add(pdf_id)
            row = {
                "eidh": eidh,
                "client": client,
                "pdf_filename": pdf_path.name,
                "pdf_subdir": pdf_path.parent.name,
                "n_pairs": len(pairs),
                "pairs": [{"k": k, "v": v} for k, v in pairs],
            }
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n_processed % 200 == 0:
                print(f"    [{n_processed:,}/{len(pdfs):,}]")

    print(f"\n  Processed: {n_processed:,} PDFs ({n_with_pairs:,} with ≥1 pair)")
    print(f"  Total pairs extracted: {n_pairs_total:,}")

    # === Summary per client ===
    print(f"\n[4] Per-client summary → {SUMMARY_PATH.name}")
    summary = {}
    for client in sorted(by_client_keys.keys(), key=lambda c: -by_client_n_pdfs[c]):
        n_pdfs = by_client_n_pdfs[client]
        keys_universe = by_client_keys[client]
        # Per key: how many PDFs have it + top 5 unique values
        key_summary = {}
        for k, val_counter in sorted(keys_universe.items(),
                                     key=lambda kv: -len(by_client_key_pdf_set[client][kv[0]])):
            n_unique_pdfs = len(by_client_key_pdf_set[client][k])  # FIXED: unique PDF count
            uniq_values = len(val_counter)
            top_values = val_counter.most_common(5)
            coverage_pct = round(100 * n_unique_pdfs / n_pdfs, 1) if n_pdfs else 0
            key_summary[k] = {
                "n_pdfs_with_key": n_unique_pdfs,
                "coverage_pct": coverage_pct,
                "n_unique_values": uniq_values,
                "top_5_values": [{"v": v, "count": c} for v, c in top_values],
                "all_unique_values_sample": list(val_counter.keys())[:30],
            }
        summary[client] = {
            "n_pdfs": n_pdfs,
            "n_unique_keys": len(keys_universe),
            "keys": key_summary,
        }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Print top clients summary (using unique PDF coverage)
    print(f"\n=== Top 22 clients summary ===")
    print(f"{'client':25} {'n_pdfs':>7} {'n_keys':>7}  top 5 keys (unique-PDF coverage%)")
    for client in sorted(by_client_keys.keys(), key=lambda c: -by_client_n_pdfs[c])[:22]:
        n = by_client_n_pdfs[client]
        nk = len(by_client_keys[client])
        top5_keys = sorted(
            by_client_keys[client].items(),
            key=lambda kv: -len(by_client_key_pdf_set[client][kv[0]])
        )[:5]
        top5_str = "  ".join(
            f"{k}({round(100 * len(by_client_key_pdf_set[client][k]) / n)}%)"
            for k, _ in top5_keys
        )
        print(f"{client:25} {n:>7} {nk:>7}  {top5_str}")

    print(f"\n[output] {OUT_PATH} (raw per-PDF)")
    print(f"[output] {SUMMARY_PATH} (per-client universe)")


if __name__ == "__main__":
    main()
