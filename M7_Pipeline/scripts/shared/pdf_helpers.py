"""shared/pdf_helpers.py — PDF 偵測共用模組

抽自原本散在 extract_raw_text_m7.py / extract_unified_m7.py / vlm_fallback_api.py 的重複碼。

提供：
  detect_construction_pages(pdf_path) — PullOn 版（text + image/drawing 評分 + Centric8 排除）
  is_centric8_non_construction(text, upper) — POM 表 / metadata cover / BOM 表偵測

需要：pip install pymupdf
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from typing import Optional

# ════════════════════════════════════════════════════════════
# Regex / 關鍵字
# ════════════════════════════════════════════════════════════

ISO_RE = re.compile(r"\b(301|401|406|503|504|512|514|515|516|601|602|605|607)\b")
MARGIN_RE = re.compile(r'\d+/\d+["”]')
NEEDLE_RE = re.compile(r"\b[23]N\b|\b[23]NDL\b|\b2N3TH\b|\b3N5TH\b", re.I)
SEW_KW = ["COVERSTITCH", "OVERLOCK", "TOPSTITCH", "FLATLOCK", "FLATSEAM",
          "BARTACK", "BAR TACK", "BLINDHEM", "BLIND HEM", "EDGESTITCH",
          "EDGE STITCH", "CHAINSTITCH", "CHAIN STITCH", "FELLED SEAM",
          "LAPPED SEAM", "SATIN STITCH", "CLEAN FINISH", "TURNBACK",
          "TURN BACK", "UNDERSTITCHED", "BINDING", "SERGE", "SERGED"]
EXCLUDE_TITLES = ["GRADE REVIEW", "REF IMAGES", "REFERENCE IMAGES",
                  "INSPIRATION IMAGES", "INSPIRATION", "FIT COMMENTS",
                  "FIT SAMPLE IMAGES", "PATTERN CORRECTIONS", "NEXT STEPS",
                  "MOCK NECK REFERENCES"]
POM_KW = ["POM NAME", "TOL FRACTION", "VENDOR ACTUAL", "SAMPLE EVAL", "QC EVALUATION"]

# Centric 8 偵測
POM_ID_RE = re.compile(r"\b[A-Z]{1,3}\d{2,3}[A-Z]?\b")
METADATA_KW = ["DESIGN NUMBER", "DESIGN TYPE", "DESIGN SUB-TYPE", "BRAND/DIVISION",
               "BRAND DIVISION", "DEPARTMENT", "CARRY OVER", "REVISION", "FIT CAMP",
               "BOM PRIMARY", "SEASON PLANNING", "PRIMARY SUPPLIER", "BOM VERSION",
               "STATUS\tADOPTED", "DESIGN CONCEPT", "COSTING INFORMATION"]
BOM_TABLE_KW = ["BOMCOLORMATRIX", "OWNER TYPE", "COMPONENTS\tDOCUMENTS",
                "BOM CC NUMBER", "PRODUCT SUSTAINABILITY",
                "BOM DETAILS", "MATERIAL NAME", "GAUGE/ENDS",
                "QUALITY DETAILS", "PRIMARY RD",
                "SUPPLIER ARTICLE", "CC NAME",
                "SUSTAINABILITY ATTRIBUTE"]


def is_centric8_non_construction(text: str, upper: Optional[str] = None) -> tuple[bool, str]:
    """偵測 Centric 8 非 construction 頁：metadata cover / POM 表 / BOM 表

    Args:
        text: 原始頁面 text
        upper: 預先 upper 過的 text（可選，避免重複 .upper()）

    Returns:
        (is_skip, reason)
    """
    if upper is None:
        upper = text.upper()
    # POM 表：Tol (-)/Tol (+) 強訊號
    if "TOL (-)" in upper and "TOL (+)" in upper:
        return True, "POM table (Tol -/+)"
    # POM 表：8+ 個 POM ID（W001 等）
    pom_ids = POM_ID_RE.findall(text)
    if len(pom_ids) >= 8:
        return True, f"POM table ({len(pom_ids)} POM IDs)"
    # Centric 8 metadata cover：≥4 個 metadata keyword
    metadata_hits = sum(1 for kw in METADATA_KW if kw in upper)
    if metadata_hits >= 4:
        return True, f"Centric 8 cover ({metadata_hits} metadata kw)"
    # BOM components/documents 表
    bom_hits = sum(1 for kw in BOM_TABLE_KW if kw in upper)
    if bom_hits >= 1:
        return True, f"BOM table"
    return False, ""


def detect_construction_pages(pdf_path) -> list[dict]:
    """PullOn 版 PDF construction 頁偵測 (text-layer + image/drawing 評分 + Centric8 排除)

    分數規則：
      ISO code: +3
      'CONSTRUCTION CALLOUT' / 'INTERNAL/CONSTRUCTION': +3
      'CALLOUT' / 'BOM REVIEW' / 'DESIGN BOM': +2
      sewing keyword: +2
      seam allowance margin: +2
      needle config: +1
      images>=1 or drawings>=10: +3
      drawings>=30: +2
      'ADDITIONAL COMMENTS': -3
      'BOM' + 'CATEGORY': -2
    Image-heavy callout 頁 (images + low text)：強制 score 5+

    Returns:
        list of {page (1-indexed), type ("text"/"image"), score, word_count}
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

            # --- 早期排除 ---
            if any(k in upper for k in EXCLUDE_TITLES):
                continue
            if any(k in upper for k in POM_KW):
                continue
            if "MEASUREMENT CHART" in upper and any(k in upper for k in ["TARGET", "TOLERANCE", "GRADING"]):
                continue
            is_skip, _reason = is_centric8_non_construction(text, upper)
            if is_skip:
                continue

            # --- 評分 ---
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
            # 圖密集 + 字少 callout 頁強制過關
            if any(k in upper for k in ["CALLOUT", "DESIGN BOM"]) and n_images >= 1 and wc < 200:
                score = max(score, 5)

            if score >= 5:
                out.append({
                    "page": i + 1,
                    "type": "image" if wc < 40 else "text",
                    "score": score,
                    "word_count": wc,
                })
        doc.close()
    except Exception as e:
        print(f"  [!] detect fail {Path(pdf_path).name}: {e}", file=sys.stderr)
    return out
