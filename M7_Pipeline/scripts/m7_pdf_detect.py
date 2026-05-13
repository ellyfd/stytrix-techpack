"""
m7_pdf_detect.py — Construction page 偵測（統一版）

把原本散在 4 個檔的 detect_construction_pages 統一一個版本。
規則：
  Hard exclude → fit photo / inspiration / POM 表 / Centric 8 cover/BOM 表
  Score:
    +3  ISO code
    +3  CONSTRUCTION CALLOUT / INTERNAL/CONSTRUCTION 標題
    +2  CALLOUT / BOM REVIEW / DESIGN BOM 標題
    +2  sewing keyword (COVERSTITCH / OVERLOCK / ...)
    +2  margin spec (1/4")
    +1  needle count (2N / 3N5TH)
    +3  image >= 1 OR drawings >= 10 (graphic-layer callout)
    +2  drawings >= 30
    -3  ADDITIONAL COMMENTS
    -2  BOM CATEGORY
  強制：title 含 CALLOUT/DESIGN BOM + 有圖 + 文字密度低 → score >= 5

import：
  from m7_pdf_detect import detect_construction_pages
"""

import sys
from pathlib import Path

from m7_constants import (
    ISO_RE, MARGIN_RE, NEEDLE_RE,
    SEW_KW, EXCLUDE_TITLES, POM_KW,
    is_centric8_non_construction,
)


def detect_construction_pages(pdf_path) -> list[dict]:
    """
    PullOn 版 construction page 偵測。
    Returns: [{"page": 1-indexed, "type": "image"|"text", "score": N, "word_count": N}]
    """
    try:
        import fitz
    except ImportError:
        return []

    out = []
    try:
        doc = fitz.open(str(pdf_path))
        for i in range(doc.page_count):
            page = doc[i]
            text = page.get_text()
            upper = text.upper()
            wc = len(text.split())

            # Hard exclude
            if any(k in upper for k in EXCLUDE_TITLES):
                continue
            if any(k in upper for k in POM_KW):
                continue
            if "MEASUREMENT CHART" in upper and any(k in upper for k in ["TARGET", "TOLERANCE", "GRADING"]):
                continue
            # Centric 8 非 construction 頁（cover / BOM / POM）
            is_skip, _ = is_centric8_non_construction(text, upper)
            if is_skip:
                continue

            score = 0
            if ISO_RE.search(text):
                score += 3
            if "CONSTRUCTION CALLOUT" in upper or "INTERNAL/CONSTRUCTION" in upper:
                score += 3
            if any(k in upper for k in ["CALLOUT", "BOM REVIEW", "DESIGN BOM"]):
                score += 2
            if any(k in upper for k in SEW_KW):
                score += 2
            if MARGIN_RE.search(text):
                score += 2
            if NEEDLE_RE.search(text):
                score += 1

            try:
                n_images = len(page.get_images(full=True))
            except Exception:
                n_images = 0
            try:
                n_drawings = len(page.get_drawings())
            except Exception:
                n_drawings = 0
            if n_images >= 1 or n_drawings >= 10:
                score += 3
            if n_drawings >= 30:
                score += 2

            if "ADDITIONAL COMMENTS" in upper:
                score -= 3
            if "BOM" in upper and "CATEGORY" in upper:
                score -= 2

            # 強制：title 含 Callouts + 圖 + 文字密度低
            if any(k in upper for k in ["CALLOUT", "DESIGN BOM"]) and n_images >= 1 and wc < 200:
                score = max(score, 5)

            if score >= 5:
                page_type = "image" if wc < 40 else "text"
                # 2026-05-07：image-type 二次 filter — 必須有 ISO 或 callout/sewing 關鍵詞
                # 否則排除 cover / spec sheet / mannequin / color block 等假陽性
                # 規範：training-pipeline-lessons.md §鐵則 2 is_callout_page rule
                if page_type == "image":
                    has_iso = bool(ISO_RE.search(text))
                    has_callout_kw = any(k in upper for k in [
                        "CALLOUT", "CONSTRUCTION", "STITCH", "SEAM", "SEW",
                        "TOPSTITCH", "OVERLOCK", "FLATLOCK", "COVERSTITCH",
                        "BARTACK", "CHAINSTITCH", "HEM", "CUFF",
                    ])
                    has_margin = bool(MARGIN_RE.search(text))
                    if not (has_iso or has_callout_kw or has_margin):
                        # 1 張圖 + 沒任何 callout 訊號 → 跳過
                        continue
                out.append({
                    "page": i + 1,
                    "type": page_type,
                    "score": score,
                    "word_count": wc,
                })
        doc.close()
    except Exception as e:
        print(f"  [!] detect fail {Path(pdf_path).name}: {e}", file=sys.stderr)
    return out
