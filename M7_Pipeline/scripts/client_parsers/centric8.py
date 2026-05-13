"""client_parsers/centric8.py — Centric 8 brands (ONY/ATH/GAP/BR) Techpack parser.

Centric 8 是 ONY 集團共用的 PLM 平台 (Old Navy / Athleta / GAP / GAP Outlet / Banana Republic),
PDF 結構 / Cover layout / Measurement chart layout 五家都一樣。

直接 wrap 既有 extract_techpack.py (在 scripts/lib/ 下) 的 helpers, 那邊已實作完整 mcs[] 抽取。
Cover metadata 沿用 extract_pdf_metadata.py 內 parse_centric8 的邏輯。
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from typing import Optional

from ._base import ClientParser

# import extract_techpack helpers — 找位於 stytrix-techpack/scripts/lib 或 M7_Pipeline/scripts/lib
_THIS_DIR = Path(__file__).resolve().parent  # scripts/client_parsers/
_M7_SCRIPTS = _THIS_DIR.parent                # scripts/
_M7_ROOT = _M7_SCRIPTS.parent                 # M7_Pipeline/
_SOURCE_DATA = _M7_ROOT.parent                # Source-Data/

_CANDIDATE_LIB_DIRS = [
    _M7_SCRIPTS / "lib",                                                  # M7_Pipeline/scripts/lib
    Path(r"C:\temp\stytrix-techpack\scripts\lib"),                        # stytrix-techpack (Windows)
    _SOURCE_DATA.parent / "stytrix-techpack" / "scripts" / "lib",         # 同 parent (rare)
    _SOURCE_DATA / "ONY" / "pom_analysis_v5.5.1" / "scripts",             # 舊版 (fallback)
]

_LIB_OK = False
_LAST_IMPORT_ERR = None
for _cand in _CANDIDATE_LIB_DIRS:
    if (_cand / "extract_techpack.py").exists():
        sys.path.insert(0, str(_cand))
        try:
            from extract_techpack import (  # noqa: E402
                detect_body_type as _detect_body_type,
                detect_status as _detect_status,
                _clean_pom_code,
            )
            _LIB_OK = True
            print(f"[client_parsers.centric8] using extract_techpack from {_cand}", file=sys.stderr)
            break
        except Exception as e:
            _LAST_IMPORT_ERR = f"{type(e).__name__}: {e}"
            continue

if not _LIB_OK:
    print(f"[client_parsers.centric8] warn: extract_techpack import fail.", file=sys.stderr)
    if _LAST_IMPORT_ERR:
        print(f"  last import error: {_LAST_IMPORT_ERR}", file=sys.stderr)
        print(f"  → 多半是缺套件, 例如 'pip install pdfplumber --break-system-packages'", file=sys.stderr)
    for c in _CANDIDATE_LIB_DIRS:
        print(f"  candidate: {c} (exists={c.exists()})", file=sys.stderr)
    # 簡化版本 fallback (沒 helper)
    def _detect_body_type(s): return None
    def _detect_status(s): return None
    def _clean_pom_code(s): return s.strip() if s else s


# ════════════════════════════════════════════════════════════
# Centric 8 Production(7.4) Measurement Chart Review parser
# ════════════════════════════════════════════════════════════
# Production export 跟 Concept-en graded MC 不同 layout:
#   header: POM Name | Description | POM Variation | Tol Fraction (-) | Tol Fraction (+)
#           | QC | <M base size> | Measurement Chart Review:
#                   Target | Sample | Vendor Actual | Sample HQ Actual Delta
#                   | HQ Actual | HQ Actual Delta | Revised
# 每筆 POM 一個 record, value 是 single base-size measurement (Target 欄).
#
# raw text 樣態 (cell-per-line, fitz):
#   C2.3                                ← POM code (anchor)
#   Individual Shoulder Width            ← Description
#   Edge to Edge                         ← (description 續行)
#   - Graded                             ← POM Variation (常空)
#   - 1/4                                ← Tol(-)
#   1/4                                  ← Tol(+)
#   <空 or 勾選>                          ← QC
#   1 5⁄8                                ← Target (我們要的 spec value)
#   000491793 Fit M BANKS CRINKLE SATIN  ← Sample row 1 (skip)
#   Slim HI NECK BIAS SATIN DRESS        ← Sample row 2 (skip)
#   000795203 000795203                  ← Sample row 3 (skip)
#   1 5⁄8                                ← Vendor Actual (skip)
#   ...                                  ← 其他評估欄 (skip)
#
# Sample 案例: ONY EIDH 306119 D63709 RD1039811 (21 POMs)
_PROD_POM_CODE_RE = _re_textmode.compile(r"^[A-Z]\d{1,3}(?:\.\d{1,2})?$") if False else None
import re as _re_prod
_PROD_POM_CODE_RE = _re_prod.compile(r"^[A-Z]\d{1,3}(?:\.\d{1,2})?$")
_PROD_TOL_RE = _re_prod.compile(r"^-?\s*\d+([\s]?[/⁄][\s]?\d+)?$|^-?\s*\d+\s+\d+[/⁄]\d+$|^-?\s*\d+\.\d+$|^0\.0$|^=?\s*<\s*\d+/\d+$")
_PROD_FRAC_RE = _re_prod.compile(r"^-?\s*\d+\s+\d+[/⁄]\d+$|^-?\s*\d+[/⁄]\d+$|^-?\s*\d+(?:\.\d+)?$")


def _is_centric_prod_tol(s):
    """Centric 8 Production Tol value: "- 1/4" / "1/4" / "0.0" / "=<1/2" 等."""
    if not s:
        return False
    s2 = s.strip()
    if not s2:
        return False
    # explicit tolerance patterns
    if _PROD_TOL_RE.match(s2):
        return True
    # negative tolerance: "- 1/4"
    if s2.startswith("-") and any(c.isdigit() for c in s2):
        return True
    return False


def _is_centric_prod_target(s):
    """Centric 8 Production Target value (spec measurement): "1 5/8" / "46 3/8" / "8 1/4" / "0" 等."""
    if not s:
        return False
    s2 = s.strip()
    if not s2:
        return False
    # 純整數
    if _re_prod.match(r"^\d+$", s2):
        return True
    # 整數+分數: "1 5/8" / "46 3⁄8"
    if _re_prod.match(r"^\d+\s+\d+[/⁄]\d+$", s2):
        return True
    # 純分數: "5/8" / "3⁄8"
    if _re_prod.match(r"^\d+[/⁄]\d+$", s2):
        return True
    return False


def _parse_centric8_production_textmode(text: str, base_size: str = "M") -> dict:
    """Parse Centric 8 Production(7.4) Measurement Chart Review layout.

    每 POM 一個 record, sizes_dict 只含 base_size (e.g. "M": "1 5/8").
    """
    lines = [l.rstrip() for l in text.split("\n")]
    poms = []
    i = 0
    n = len(lines)

    # 跳過頭部 header 段 (找到第一個 POM code 才開始)
    while i < n:
        if _PROD_POM_CODE_RE.match(lines[i].strip()):
            break
        i += 1

    while i < n:
        line = lines[i].strip()
        # 是 POM code 嗎?
        if not _PROD_POM_CODE_RE.match(line):
            i += 1
            continue

        code = line
        pom = {"POM_Code": code}

        # 蒐集 POM 描述 (Name + Description + POM Variation), 直到碰到 Tol 數值
        name_parts = []
        j = i + 1
        target_idx = None
        tol_values = []
        # 最多向前看 25 行 (一個 POM record 大概 14-18 行)
        scan_end = min(j + 25, n)
        # 第一階段: 蒐集 name + variation, 直到看到 Tol 數值
        while j < scan_end:
            l = lines[j].strip()
            # 下一個 POM code → 提前結束
            if _PROD_POM_CODE_RE.match(l):
                break
            # 找到 Tol 模式: 連續 2 個 "_is_centric_prod_tol" 行 (Tol(-) + Tol(+))
            if _is_centric_prod_tol(l):
                # check next non-empty line 也是 tol
                k = j + 1
                while k < scan_end and not lines[k].strip():
                    k += 1
                if k < scan_end and _is_centric_prod_tol(lines[k].strip()):
                    tol_values = [l, lines[k].strip()]
                    j = k + 1
                    break
                # 單一 tol 值
                tol_values = [l]
                j = j + 1
                break
            # name + description (skip blank)
            if l and l not in ("",):
                name_parts.append(l)
            j += 1

        if name_parts:
            full_name = " ".join(name_parts)[:200]
            pom["POM_Name"] = full_name

        # Tolerance
        if len(tol_values) == 2:
            t1, t2 = tol_values
            # determine which is neg
            if t1.lstrip().startswith("-"):
                tol_neg, tol_pos = t1, t2
            elif t2.lstrip().startswith("-"):
                tol_neg, tol_pos = t2, t1
            else:
                tol_neg, tol_pos = t1, t2
            pom["tolerance"] = {"neg": tol_neg, "pos": tol_pos}
        elif len(tol_values) == 1:
            pom["tolerance"] = {"neg": tol_values[0]}

        # 第二階段: 跳過 QC marker (可能空白或一個短字符), 抓第一個 _is_centric_prod_target 當 Target
        scan2_end = min(j + 12, n)
        while j < scan2_end:
            l = lines[j].strip()
            if _PROD_POM_CODE_RE.match(l):
                break
            if _is_centric_prod_target(l):
                # 確認不是 tol 值 (e.g. "1/4" 也可能是 target — 但 target 通常更大)
                pom["sizes"] = {base_size: l}
                j += 1
                break
            j += 1

        # 只收 POM 有 size value (Target) 的 record
        if pom.get("sizes"):
            poms.append(pom)

        # 跳到下個 POM code (避開 Sample/Vendor/HQ 評估欄)
        # 直接從 j 開始, 但向前掃 5-20 行找下一個 POM code
        next_code_idx = None
        scan3_end = min(j + 20, n)
        while j < scan3_end:
            if _PROD_POM_CODE_RE.match(lines[j].strip()):
                next_code_idx = j
                break
            j += 1
        i = next_code_idx if next_code_idx else (j + 1)

    if not poms:
        return {}
    return {"sizes": [base_size], "poms": poms, "n_poms_on_page": len(poms),
            "layout": "centric8_production_mc_review"}


class Centric8Parser(ClientParser):
    """ONY/ATH/GAP/BR 共用 parser."""

    def parse_cover(self, page, text: str) -> dict:
        """從 Centric 8 cover page 抽業務 metadata.

        使用 extract_techpack._extract_page1_meta 的邏輯, 但只對單一 page 跑.
        """
        if not _LIB_OK:
            return {}

        upper = text.upper()
        meta = {}

        # 沿用 extract_techpack 的欄位抽取 (key: value 配對)
        patterns = {
            "design_number": r"DESIGN NUMBER[:\s\t]+([\w\-]+)",
            "description": r"DESCRIPTION[:\s\t]+(.+?)(?:\n|$)",
            "brand_division": r"BRAND[/\s]*DIVISION[:\s\t]+(.+?)(?:\n|$)",
            "department": r"DEPARTMENT[:\s\t]+(.+?)(?:\n|$)",
            "bom_category": r"BOM CATEGORY[:\s\t]+(.+?)(?:\n|$)",
            "sub_category": r"SUB[\s\-]*CATEGORY[:\s\t]+(.+?)(?:\n|$)",
            "collection": r"COLLECTION[:\s\t]+(.+?)(?:\n|$)",
            "season": r"SEASON[:\s\t]+(.+?)(?:\n|$)",
            "design_type": r"DESIGN TYPE[:\s\t]+(.+?)(?:\n|$)",
            "fit_camp": r"FIT CAMP[:\s\t]+(.+?)(?:\n|$)",
            "status": r"STATUS[:\s\t]+(\w+)",
        }
        for key, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                v = m.group(1).strip()
                if v and v.lower() not in ("none", "tbd", "n/a"):
                    meta[key] = v
        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        """Centric 8 callout page 多數是 image-based, 結構化抽不太到.

        保留整頁 text 給 VLM 之後處理.
        """
        return [{"_raw_callout_text": text[:5000]}]

    def parse_measurement_chart(self, page, text: str) -> Optional[dict]:
        """從 Centric 8 measurement chart page 抽 mc dict (pdfplumber table-based).

        Centric 8 PLM MC 表結構:
          - 上方多個 2-col header table (Season, Department, Brand/Division, Size Range, Status, ...)
          - 一個 main POM table (>=8 列):
              POM Name | Description | POM Variation | QC | Tol(-) | Tol(+) | TolMsg | GradingMsg | <SIZE_COLS...>

        return None if 找不到 main POM table.
        """
        # 嘗試用 pdfplumber re-open the page 抽表
        try:
            import pdfplumber
        except ImportError:
            return None

        # 從 fitz page 拿 PDF path + page index
        try:
            pdf_path = page.parent.name
            page_num = page.number
        except Exception:
            return None

        if not pdf_path:
            return None

        mc = {"_source_pdf": Path(pdf_path).name, "_source_page": page_num + 1}

        try:
            with pdfplumber.open(pdf_path) as ppdf:
                if page_num >= len(ppdf.pages):
                    return None
                p_page = ppdf.pages[page_num]
                tables = p_page.extract_tables()
        except Exception as e:
            mc["_error"] = f"pdfplumber: {type(e).__name__}: {e}"
            return mc

        # === 1. Page-level header (2-col small tables) → mc fields ===
        HEADER_KEY_MAP = {
            "season": "season",
            "department": "department",
            "brand/division": "brand_division",
            "brand division": "brand_division",
            "collection": "collection",
            "selected sizes": "selected_sizes_raw",
            "size range": "size_range",
            "base size": "base_size",
            "grade rule": "grade_rule",
            "size chart tier": "size_chart_tier",
            "status": "status",
            "milestone": "milestone",
            "tolerance changed": "tolerance_changed",
            "tolerance message": "tolerance_message",
            "brand mc comments": "brand_mc_comments",
            "sample request sizes": "sample_request_sizes",
            "created": "created",
            "created by": "created_by",
            "modified": "modified",
            "modified by": "modified_by",
            "measurement chart": "mc_key",
        }
        for tbl in tables:
            if not tbl or len(tbl) != 1 or len(tbl[0]) != 2:
                continue
            k_raw, v_raw = tbl[0]
            if not k_raw:
                continue
            k = k_raw.strip().lower().replace("\n", " ")
            field = HEADER_KEY_MAP.get(k)
            if field:
                v = (v_raw or "").strip()
                # 過濾 Centric 8 placeholder unicode 字
                if v and v not in ("\ue5ca", ""):
                    mc[field] = v

        # === 2. Main POM table (cols >= 8, 第一列含 "POM" 或 "Name" + size column 字母) ===
        SIZE_TOKENS = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "2X", "3X", "4X", "5X",
                        "0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22", "24",
                        "P", "T", "MAT", "MATERNITY",
                        # 2026-05-13: ON Baby/Toddler 月齡 sizes
                        "2T", "3T", "4T", "5T", "6T",
                        "NB", "NEWBORN", "PREEMIE",
                        "0-3 MONTHS", "3-6 MONTHS", "6-12 MONTHS", "9-12 MONTHS",
                        "12-18 MONTHS", "12-24 MONTHS", "18-24 MONTHS", "24 MONTHS",
                        "0- 3 MONTHS", "3- 6 MONTHS", "6- 12 MONTHS",
                        "12- 18 MONTHS", "18- 24 MONTHS",
                        "12M", "18M", "24M"}
        # Helper 認 baby/toddler month patterns 動態判 (cover pdfplumber 切壞的 "12-1 8 MONTHS" 等)
        import re as _re_baby
        _BABY_MONTH_RE = _re_baby.compile(r"^\d+[\s\-]+\d+\s*MONTHS?$|^\d+\s*MONTHS?$|^\d+M$", _re_baby.IGNORECASE)
        # 2026-05-13: Centric 8 Production(7.9.2) GAP/ONY 全 graded layout 用 slash size header:
        # "0000/22" / "000/23" / "00/24" / "0/25" / "2/26" ... "22/36" (size_code/waist_inch)
        # 也支援 ALPHA/NUM 如 "XXS/4-5" / "M/10-12" (跟 _base.py 一致)
        _SLASH_SIZE_RE = _re_baby.compile(
            r"^(XXS|XS|S|M|L|XL|XXL|SM|MD|LG|2X|3X|4X|"
            r"SMALL|MEDIUM|LARGE|"
            r"\d{1,4})"            # pure-numeric size code (0000/000/00/0/2/4...22)
            r"\s*/\s*"
            r"\d+(?:\s*-\s*\d+)?$",
            _re_baby.IGNORECASE)

        def _is_size(h):
            hu = h.strip().upper()
            if hu in SIZE_TOKENS:
                return True
            if _BABY_MONTH_RE.match(hu):
                return True
            # 接 pdfplumber 切壞如 "12-1 8 MONTHS"
            if "MONTHS" in hu and any(c.isdigit() for c in hu):
                return True
            # Centric 8 Production(7.9.2) slash format
            if _SLASH_SIZE_RE.match(hu):
                return True
            return False

        main_table = None
        for tbl in tables:
            if not tbl or len(tbl) < 2 or len(tbl[0]) < 8:
                continue
            header = [str(c or "").strip().replace("\n", " ") for c in tbl[0]]
            # 必須有 "POM" 或 "POM Name" 在前段
            if not any("POM" in h.upper() for h in header[:2]):
                continue
            # 必須有至少 1 個 size token 在尾段 (含 baby/toddler month patterns)
            if not any(_is_size(h) for h in header):
                continue
            main_table = (tbl, header)
            break

        if not main_table:
            # === Fallback: Centric 8 Production(7.4) Measurement Chart Review layout ===
            # 2026-05-13 加: 跟 Concept-en graded MC 不同,Production export 是
            # single-base-size + Target + Vendor/HQ Actual 評估表
            # 觸發條件: text 含 "Centric 8 Production" + "Measurement Chart Review"
            text_upper = text.upper()
            if ("MEASUREMENT CHART REVIEW" in text_upper and
                ("CENTRIC 8 PRODUCTION" in text_upper or "PRODUCTION(7.4)" in text_upper)):
                prod_mc = _parse_centric8_production_textmode(text, base_size=mc.get("base_size") or "M")
                if prod_mc and prod_mc.get("poms"):
                    mc.update(prod_mc)
                    mc["_parse_mode"] = "centric8_production_text"
                    return mc
            mc["_no_pom_table"] = True
            return mc

        tbl, header = main_table

        # === 3. 識別欄位 index ===
        col_idx = {}
        size_cols = []
        for i, h in enumerate(header):
            hu = h.upper().replace("\n", " ")
            if "POM" in hu and ("NAME" in hu or i == 0):
                col_idx["pom_code"] = i
            elif "DESCRIPTION" in hu:
                col_idx["description"] = i
            elif "POM VARIATION" in hu or "VARIATION" in hu:
                col_idx["variation"] = i
            elif hu == "QC":
                col_idx["qc"] = i
            elif "TOL" in hu and "-" in h:
                col_idx["tol_neg"] = i
            elif "TOL" in hu and "+" in h:
                col_idx["tol_pos"] = i
            elif "TOLERANCE" in hu and "MESSAGE" in hu:
                col_idx["tol_msg"] = i
            elif "GRADING" in hu and ("OVERRIDE" in hu or "MESSAGE" in hu):
                col_idx["grading_msg"] = i
            elif _is_size(hu):
                size_cols.append((i, hu))

        if "pom_code" not in col_idx or not size_cols:
            mc["_no_pom_table"] = True
            return mc

        mc["sizes"] = [s for _, s in size_cols]

        # === 4. Parse each row ===
        poms = []
        for row in tbl[1:]:
            if not row:
                continue
            code = (row[col_idx["pom_code"]] or "").strip()
            # 忽略 footer rows ("Displaying 1-3 of 21 results")
            if not code or "displaying" in code.lower() or "of" in code.lower() and "result" in code.lower():
                continue
            # POM code 應該是 alphanumeric (H1 / Z26.11 / Q2)
            if not re.match(r"^[A-Z]{1,4}\d{1,4}(?:\.\d+)?$", code.replace("\n", "")):
                continue

            pom = {"POM_Code": code.replace("\n", "")}

            # Description
            if "description" in col_idx:
                desc = (row[col_idx["description"]] or "").strip().replace("\n", " ")
                if desc:
                    pom["POM_Name"] = desc[:200]

            # Variation
            if "variation" in col_idx:
                var = (row[col_idx["variation"]] or "").strip()
                if var and var not in ("", "\ue5ca"):
                    pom["variation"] = var

            # Tolerance
            tol = {}
            if "tol_neg" in col_idx:
                v = (row[col_idx["tol_neg"]] or "").strip()
                if v: tol["neg"] = v
            if "tol_pos" in col_idx:
                v = (row[col_idx["tol_pos"]] or "").strip()
                if v: tol["pos"] = v
            if tol:
                pom["tolerance"] = tol

            # QC flag (Centric 8 用 \ue5ca 表示 yes-tick)
            if "qc" in col_idx:
                qc_raw = (row[col_idx["qc"]] or "").strip()
                pom["qc"] = bool(qc_raw and qc_raw not in ("", "0"))

            # Sizes
            sizes_dict = {}
            for col_i, size_name in size_cols:
                v = (row[col_i] or "").strip().replace("\n", " ")
                if v:
                    sizes_dict[size_name] = v
            if sizes_dict:
                pom["sizes"] = sizes_dict

            poms.append(pom)

        mc["poms"] = poms
        mc["n_poms_on_page"] = len(poms)

        # body_type / status fallback to text-based detection (existing helpers)
        if _LIB_OK:
            if "body_type" not in mc and mc.get("mc_key"):
                bt = _detect_body_type(mc.get("mc_key") or text)
                if bt:
                    mc["body_type"] = bt
            if "status" not in mc:
                st = _detect_status(mc.get("mc_key") or text)
                if st:
                    mc["status"] = st

        # selected_sizes_raw → selected_sizes[]
        ssr = mc.get("selected_sizes_raw", "")
        if ssr:
            # "XS- XXL" → ["XS", "S", "M", "L", "XL", "XXL"] (best effort 展開)
            mc["selected_sizes_raw"] = ssr  # keep raw
            ss_expand = re.findall(r"\b(XXS|XS|S|M|L|XL|XXL|2X|3X|4X|\d+)\b", ssr)
            if ss_expand:
                mc["selected_sizes_explicit"] = ss_expand

        return mc
