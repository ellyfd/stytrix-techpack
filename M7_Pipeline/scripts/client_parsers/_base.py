"""client_parsers/_base.py — abstract ClientParser API.

每個 brand 一個 module, 實作 3 個 method:
  parse_cover(page, text)        — 從 cover page 抽業務 metadata (gender/dept/category...)
  parse_construction_page(page, text)      — 從 callout page 抽 callout 結構化資料 (zone/iso/method/...)
  parse_measurement_chart(page, text)           — 從 measurement chart page 抽 mc dict (body_type/sizes/poms[])

Page-level classification 已在外面 page_classifier.py 完成。
本 module 只負責 "每類 page 怎麼抽欄位"。
"""
from __future__ import annotations
from typing import Optional




import re as _re_textmode

# POM code patterns per brand layout (most common)
_POM_CODE_RE = _re_textmode.compile(
    # 標準 POM code: 字母+數字 (含小數/連字號變體)
    r"^([A-Z]{1,4}\d{1,4}(?:[\.\-][\dA-Z]{1,5})?)$"
    # ADHOC special token
    r"|^ADHOC$"
    # KOH-style: A001-LA000-20 prefix (just match first chunk)
    r"|^(?:HM|WB|WA|HP|LG|DE|BR|J|K|H|L|M|N|O|P|Q|R|S|T|V|Z|A|B|C|E|F|G|I|U|W|X|Y)\d+[\dA-Z]*$"
    # BY-style: letter-dash-letters (B-HPS / B-WHF / S-LEN)
    r"|^[A-Z]{1,3}-[A-Z]{1,5}$"
    # UA-style: 2-letter prefix + 3 digit (DE141 / WA005)
    r"|^[A-Z]{2}\d{3}[A-Z]?$"
)

# Header keywords for text-mode detection
_TEXT_HEADER_PATTERNS = {
    "POM_CODE": ["POM", "Dim", "POM Code", "POM Name", "POM #"],
    "DESC":     ["Description", "POM Description", "POM Name"],
    "TOL_NEG":  ["-Tol", "Tol (-)", "TOL (-)", "Tol(-)"],
    "TOL_POS":  ["+Tol", "Tol (+)", "TOL (+)", "Tol(+)"],
    "SIZES":    ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL",
                 "YXS", "YSM", "YMD", "YLG", "YXL",
                 "0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20",
                 "000", "00", "2P", "4P", "6P", "10P", "14P", "18P", "20P",
                 "P", "T", "PETITE", "TALL", "Petite", "Tall", "Critical"]
}

_SIZE_SET = set(_TEXT_HEADER_PATTERNS["SIZES"]) | set(s.upper() for s in _TEXT_HEADER_PATTERNS["SIZES"])
_POM_KEYS = set(s.upper() for s in _TEXT_HEADER_PATTERNS["POM_CODE"])
_DESC_KEYS = set(s.upper() for s in _TEXT_HEADER_PATTERNS["DESC"])
_TOL_KEYS = set(s.upper() for s in _TEXT_HEADER_PATTERNS["TOL_NEG"] + _TEXT_HEADER_PATTERNS["TOL_POS"])


def _parse_horizontal_pom_textmode(text: str) -> dict:
    """Horizontal POM table with fraction wrap — generic textmode parser.

    Layout 特徵 (first observed: A&F PROD InitialTechPack, Hollister S262xxxxx 系列;
    可能其他 PLM 也用):
      POMs                                                   ← anchor 行
      QA POM Description Tol (- ) Tol (+) Hide Length s1 s2 ... sN
      (optional "(+)" 行 — Tol(+) spillover)
      <CODE> <desc...> -1⁄ 1⁄ Regular -1⁄ -1⁄ 18 1⁄ 3⁄ 3⁄ 3⁄ 3⁄
      4 4 2 2 2 4 4 4 8       ← fraction-denominator wrap row

    跟 vertical multi-line (_parse_measurement_chart_textmode) 完全不同 —
    這裡每筆 POM 都在「一行 + 緊接的分母行」中, 每行 = 一個邏輯 row,
    分數值 (e.g. -1/4) 會被切成兩行 — 主行帶分子+斜線「-1⁄」, 下一行純分母「4」.
    """
    lines = text.split("\n")

    # 1. Anchor "POMs" + 緊接的 header "QA POM Description Tol ..."
    header_idx = -1
    for i in range(len(lines) - 1):
        if lines[i].strip() == "POMs":
            nxt = lines[i + 1]
            if "POM" in nxt and ("Description" in nxt or "Tol" in nxt):
                header_idx = i + 1
                break
    if header_idx < 0:
        return {}

    header = lines[header_idx]
    body_start = header_idx + 1
    # 連續行 "(+)" — Tol(+) spillover
    if body_start < len(lines) and lines[body_start].strip() in ("(+)", "( + )"):
        header = header + " (+)"
        body_start += 1

    # Sizes 抽取: "Length" 之後的所有 whitespace tokens
    m = _re_textmode.search(r"Length\s+(.+)$", header)
    if not m:
        return {}
    sizes = [s for s in m.group(1).split() if s and s != "(+)"]
    if len(sizes) < 2:
        return {}

    POM_RE = _re_textmode.compile(r"^\s*([A-Z]{1,3}\d{3}[A-Z]?-?)\s+(\S.*)$")
    DEN_RE = _re_textmode.compile(r"^\d+$")
    VAL_RE = _re_textmode.compile(r"^-?\d+(?:/\d+)?$")
    FRAC_BAR = "⁄"  # ⁄

    n_sizes = len(sizes)
    poms = []

    i = body_start
    while i < len(lines):
        line = lines[i]
        ul = line.upper().strip()
        if ul.startswith("PAGE ") or "DISPLAYING " in ul or "COPYRIGHT" in ul:
            break

        m2 = POM_RE.match(line)
        if not m2:
            i += 1
            continue

        code = m2.group(1).rstrip('-')
        rest = m2.group(2)

        # 下一行若全是 fraction 分母, 合併進來
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            tokens = nxt.split() if nxt else []
            n_frac = rest.count(FRAC_BAR)
            if (
                tokens
                and n_frac > 0
                and n_frac == len(tokens)
                and all(DEN_RE.match(t) for t in tokens)
            ):
                # 逐字 walk, 每遇到 ⁄ 就替換成 /<den> (保留 whitespace 不要吃掉)
                out = []
                den_idx = 0
                for ch in rest:
                    if ch == FRAC_BAR and den_idx < len(tokens):
                        out.append('/' + tokens[den_idx])
                        den_idx += 1
                    else:
                        out.append(ch)
                rest = ''.join(out)
                i += 2
            else:
                i += 1
        else:
            i += 1

        # 解析 rest = "<desc...> <tol_neg> <tol_pos> [Regular] [hide] [length] <size_vals...>"
        tokens = rest.split()
        first_val_idx = None
        for idx, t in enumerate(tokens):
            if idx == 0:
                continue
            if VAL_RE.match(t):
                first_val_idx = idx
                break
        if first_val_idx is None:
            continue
        desc = ' '.join(tokens[:first_val_idx])
        values = tokens[first_val_idx:]
        if len(values) < 2:
            continue
        tol_neg = values[0]
        tol_pos = values[1]
        if not tol_neg.startswith('-') and tol_pos.startswith('-'):
            tol_neg, tol_pos = tol_pos, tol_neg

        # Sizes: drop optional "Regular" then trailing n_sizes 為 size 值
        rest_after_tol = values[2:]
        while rest_after_tol and rest_after_tol[0] == "Regular":
            rest_after_tol = rest_after_tol[1:]
        if len(rest_after_tol) > n_sizes:
            size_vals = rest_after_tol[-n_sizes:]
        else:
            size_vals = rest_after_tol
        if not size_vals:
            continue
        size_dict = {sizes[k]: size_vals[k] for k in range(min(len(size_vals), n_sizes)) if size_vals[k]}
        if not size_dict:
            continue

        pom = {
            "POM_Code": code,
            "POM_Name": desc[:200],
            "tolerance": {"neg": tol_neg, "pos": tol_pos},
            "sizes": size_dict,
        }
        poms.append(pom)

    if not poms:
        return {}
    return {"sizes": sizes, "poms": poms, "n_poms_on_page": len(poms), "_layout": "horizontal_fraction_wrap"}


def _parse_cato_bidpackage_pom_textmode(text: str) -> dict:
    """CATO BidPackage POM page — single sample size, no tolerance.

    Layout (CATO Corp 309130 等 38 件):
      Header line: "Point of Measurement / Spec Cato"
      Each POM 兩行:
        Row line:   "T0305   Neck Width (Basic)      (Sm to sm)"   ← code + desc 同行
        Value line: "8"                                              ← value 下一行 (M-size spec)

    POM code 可能是 T#### / C#### (4 digits) 或 T### / C### (3 digits)
    """
    lines = [l.rstrip() for l in text.split("\n")]  # don't strip leading space yet
    # row pattern: line starts with [A-Z]\d{3,4} then whitespace then desc
    CATO_ROW_RE = _re_textmode.compile(r"^\s*([A-Z]\d{3,4})\b\s+(.+?)\s*$")
    # value pattern: just a number or fraction (with optional whitespace)
    VAL_RE = _re_textmode.compile(r"^\s*(-?\d+(?:\s+\d+/\d+)?|-?\d+/\d+|-?\d+\.\d+|0)\s*$")

    # Anchor: "Point of Measurement" + "Spec Cato" or just first matching row
    in_pom_section = False
    poms = []
    for i, ln in enumerate(lines):
        if not in_pom_section:
            if "Point of Measurement" in ln or "Spec Cato" in ln:
                in_pom_section = True
            continue
        # try match POM row
        m = CATO_ROW_RE.match(ln)
        if not m:
            continue
        code = m.group(1)
        desc = m.group(2).strip()
        # next non-blank line should be value
        value = None
        j = i + 1
        while j < min(len(lines), i + 4):  # check 1-3 lines below
            nxt = lines[j].strip()
            if nxt:
                vm = VAL_RE.match(nxt)
                if vm:
                    value = vm.group(1).strip()
                break
            j += 1
        if value:
            pom = {
                "POM_Code": code,
                "POM_Name": desc[:200],
                "sizes": {"M": value},
            }
            poms.append(pom)

    if not poms:
        return {}
    return {"sizes": ["M"], "poms": poms, "n_poms_on_page": len(poms),
            "_layout": "cato_single_size"}


def _parse_by_variance_pom_textmode(text: str) -> dict:
    """BY Variance Report POM page — 單尺寸 + variance 報表.

    Layout 特徵 (BY production 第二種 layout, e.g. SD3463 / LC6295):
      POM\\nPROTO\\nDescription\\nReqstd\\nSpec\\nTol\\n(+)\\nTol\\n(-)\\nActual\\nVariance\\n
      POM Comments\\nRevised\\n<...metadata...>\\n<POM rows>

    POM 行格式 (fitz vertical text, cell-per-line):
      B-HPS         ← code (letter-dash-letters)
      ON BODY HPS TO TOP OF   ← desc line 1
      WAISTBAND               ← desc line 2 (optional)
      1/8                     ← Tol(+)
      1/8                     ← Tol(-)
      4 1/4                   ← Actual

    跟其他 layout 不同處:
      - 沒 multi-size grade table, 只有單 sample size 的 actual
      - POM code 是 B-XXX 短 dash format (B-HPS / B-WHF / B-WR)
      - text-mode vertical (cell-per-line)
    """
    lines = [l.strip() for l in text.split("\n")]
    BY_POM_CODE_RE = _re_textmode.compile(r"^[A-Z]{1,3}-[A-Z]{1,6}\d?$")
    NUM_RE = _re_textmode.compile(r"^-?\d+(?:\s+\d+/\d+)?$|^\d+/\d+$|^-?\d+\.\d+$|^0$")

    # 找第一個 BY POM code 行
    first_pom = -1
    for i, ln in enumerate(lines):
        if BY_POM_CODE_RE.match(ln):
            first_pom = i
            break
    if first_pom < 0:
        return {}

    poms = []
    i = first_pom
    while i < len(lines):
        line = lines[i]
        if not BY_POM_CODE_RE.match(line):
            i += 1
            continue
        code = line
        # 蒐集到下一個 POM code (或檔尾)
        j = i + 1
        collected = []
        while j < len(lines):
            if BY_POM_CODE_RE.match(lines[j]):
                break
            if lines[j]:
                collected.append(lines[j])
            j += 1
        # 分離 desc (text) 跟 value (numeric / fraction)
        desc_parts = []
        value_parts = []
        for tok in collected:
            if NUM_RE.match(tok):
                value_parts.append(tok)
            else:
                if not value_parts:
                    desc_parts.append(tok)
                # 已開始收 value 後的 text → 忽略 (POM Comments / Revised 等欄)
        if value_parts:
            pom = {"POM_Code": code, "POM_Name": " ".join(desc_parts)[:200]}
            if len(value_parts) >= 2:
                pom["tolerance"] = {"pos": value_parts[0], "neg": value_parts[1]}
            elif len(value_parts) == 1:
                pom["tolerance"] = {"pos": value_parts[0], "neg": value_parts[0]}
            if len(value_parts) >= 3:
                pom["sizes"] = {"S": value_parts[2]}  # single sample size
            poms.append(pom)
        i = j

    if not poms:
        return {}
    return {"sizes": ["S"], "poms": poms, "n_poms_on_page": len(poms),
            "_layout": "by_variance_single_size"}


def _parse_measurement_chart_textmode(text: str) -> dict:
    """Text-mode parser for line-borderless MC tables (HLF/KOH/DKS).

    PDF text 在 borderless table 上的 layout 是: 每個 "cell" 一行 vertical sequence.

    Strategy:
      1. 找 header section (連續 lines: POM/Description/+Tol/-Tol/<size labels>)
      2. 計算 N = column count
      3. 讀 N+4 lines per POM record:
         line 0:  POM code (matches alphanumeric pattern)
         line 1:  description
         line 2:  +Tol (or -Tol)
         line 3:  -Tol (or +Tol)
         lines 4..4+N: size values
    """
    lines = [l.strip() for l in text.split("\n")]
    # locate header
    header_start = -1
    header_end = -1
    for i in range(len(lines) - 5):
        # Look for "POM" or "POM Name" line
        if lines[i].upper() not in _POM_KEYS and lines[i] != "POM":
            continue
        # Next 3-5 lines should be Description, +Tol/-Tol, then sizes
        seq = lines[i:i+25]
        has_desc = any(l.upper() in _DESC_KEYS for l in seq[1:5])
        has_tol = sum(1 for l in seq[1:8] if l.upper() in _TOL_KEYS) >= 2
        if has_desc and has_tol:
            header_start = i
            # Find first size token after Tol
            for j in range(i+3, min(i+12, len(lines))):
                if lines[j].upper() in _SIZE_SET or lines[j] in _SIZE_SET:
                    # Collect contiguous size tokens
                    sizes = []
                    k = j
                    while k < len(lines) and (lines[k].upper() in _SIZE_SET or lines[k] in _SIZE_SET):
                        sizes.append(lines[k])
                        k += 1
                    header_end = k
                    break
            if header_end > 0:
                break
    if header_start < 0 or header_end < 0:
        return {}

    # Determine column structure
    header_block = lines[header_start:header_end]
    # Find sizes section (last contiguous run of size tokens)
    sizes = []
    for h in reversed(header_block):
        if h.upper() in _SIZE_SET or h in _SIZE_SET:
            sizes.insert(0, h)
        else:
            break

    if not sizes:
        return {}

    n_sizes = len(sizes)
    # n_cols = 1 (code) + 1 (desc) + 2 (tols) + n_sizes
    n_cols = 4 + n_sizes

    # Parse POM records starting at header_end
    poms = []
    i = header_end
    while i < len(lines):
        # Skip empty lines
        if not lines[i]:
            i += 1
            continue
        # Stop at footer markers
        l_upper = lines[i].upper()
        if l_upper.startswith("PAGE ") or "DISPLAYING" in l_upper or "COPYRIGHT" in l_upper:
            break
        # Try to match POM code
        code = lines[i]
        if not _POM_CODE_RE.match(code):
            # If not a POM code, advance
            i += 1
            continue
        # Has enough lines remaining?
        if i + n_cols > len(lines):
            break
        # Description: may span multiple lines, but for simplicity take 1 line
        # Improvement: keep collecting until we hit a tol-like number
        desc = lines[i+1] if (i+1) < len(lines) else ""
        # Check if desc actually looks like description (not a number)
        if _re_textmode.match(r"^-?[\d/]+", desc):
            # 1-line desc was actually +Tol; this POM has no desc
            desc = ""
            offset = 1  # shift +Tol/-Tol/values up by 1
        else:
            offset = 2

        # Tol_pos and tol_neg
        tol_v1 = lines[i+offset] if (i+offset) < len(lines) else ""
        tol_v2 = lines[i+offset+1] if (i+offset+1) < len(lines) else ""
        # Size values
        size_vals = lines[i+offset+2:i+offset+2+n_sizes]

        # Determine which tol is + and which is - (by sign)
        if tol_v1.startswith("-") and not tol_v2.startswith("-"):
            tol_neg, tol_pos = tol_v1, tol_v2
        elif tol_v2.startswith("-") and not tol_v1.startswith("-"):
            tol_neg, tol_pos = tol_v2, tol_v1
        else:
            tol_neg, tol_pos = tol_v1, tol_v2

        # Build POM dict
        if len(size_vals) >= n_sizes:
            pom = {"POM_Code": code}
            if desc:
                pom["POM_Name"] = desc[:200]
            if tol_neg or tol_pos:
                pom["tolerance"] = {}
                if tol_neg: pom["tolerance"]["neg"] = tol_neg
                if tol_pos: pom["tolerance"]["pos"] = tol_pos
            pom["sizes"] = {sizes[j]: size_vals[j] for j in range(n_sizes) if size_vals[j]}
            poms.append(pom)

        i += offset + 2 + n_sizes

    if not poms:
        return {}
    return {"sizes": sizes, "poms": poms, "n_poms_on_page": len(poms)}


class ClientParser:
    """Abstract base. 每個 brand subclass 覆寫對應 method."""

    code: str = ""    # e.g. "ONY"
    label: str = ""   # e.g. "Old Navy"

    def __init__(self, code: str):
        self.code = code

    def parse_cover(self, page, text: str) -> dict:
        """從 cover page 抽 metadata。

        Returns:
            dict 含 brand_division / department / category / sub_category / season / ...
            未支援 return {}.
        """
        return {}

    def parse_construction_page(self, page, text: str) -> list[dict]:
        """從 callout page 抽結構化 callout (zone/iso/method)。

        多數 brand 不能直接從 PDF text 抽（要靠 VLM 看 image）, 預設 return [].
        對 image-based callout, extract_pdf_all.py 會 render PNG 給 VLM 後續處理.

        Returns:
            list of {zone, iso, method, raw_text}.
        """
        return []

    def parse_measurement_chart(self, page, text: str) -> Optional[dict]:
        """從 measurement chart page 抽 mc dict (pdfplumber table-based, brand-agnostic).

        通用實作 — 支援:
          - Centric 8 (ONY/ATH/GAP/BR): POM Name | Description | ... | Tol(-) | Tol(+) | sizes
          - DKS (Calia/DSG):           POM # | POM Name | Tol(+) | Tol(-) | Criticality | sizes
          - KOH (TekGear/FLX):         POM Code | POM Description | TOL(-) | TOL(+) | sizes
          - UA:                        Dim | Description | ... | Tol(-) | Tol(+) | sizes (Youth/Adult)
          - HLF (Gerber):              POM | Description | +Tol | -Tol | sizes (XXS-6XL)
          - ANF (Gerber):              POM | Description | +Tol | -Tol | sizes

        策略: pdfplumber.extract_tables() 抓表, 然後 fuzzy header matching 找:
          - POM 代號欄 ("POM Name" / "POM #" / "POM Code" / "Dim" / "POM")
          - 描述欄 ("Description" / "POM Description" / 同上)
          - Tol 欄 ("Tol (-)" / "TOL (-)" / "-Tol" / variants)
          - Size 欄 (XS/S/M/L/XL... or YXS/YSM... or 2/4/6... or 0-20)

        return None if 該頁找不到符合的 POM table.
        """
        try:
            import pdfplumber
        except ImportError:
            return None

        try:
            pdf_path = page.parent.name
            page_num = page.number
        except Exception:
            return None

        if not pdf_path:
            return None

        mc = {"_source_pdf": __import__("pathlib").Path(pdf_path).name, "_source_page": page_num + 1}

        # 2026-05-12: 同時抽 pdfplumber 的 text — fitz text layout 跟 pdfplumber 不同,
        # ANF horizontal layout 的 "POMs\nQA POM Description ..." anchor 只有 pdfplumber
        # 的 reading-order text 才看得到. fallback 改用 pp_text 而不是 fitz text.
        pp_text = ""
        try:
            with pdfplumber.open(pdf_path) as ppdf:
                if page_num >= len(ppdf.pages):
                    return None
                p_page = ppdf.pages[page_num]
                tables = p_page.extract_tables()
                pp_text = p_page.extract_text() or ""
        except Exception as e:
            mc["_error"] = f"pdfplumber: {type(e).__name__}: {e}"
            return mc

        if not tables:
            mc["_no_table"] = True
            return mc

        # === Header-row keyword matchers ===
        import re as _re
        SIZE_TOKENS = {
            # Alpha
            "XXS", "XS", "S", "M", "L", "XL", "XXL", "2X", "3X", "4X", "5X", "6X",
            "2XL", "3XL", "4XL", "5XL", "6XL",
            # UA 2-letter alpha (1357139 UA Knit Track Suit layout: XS/SM/MD/LG/XL/XXL/3XL)
            "SM", "MD", "LG",
            # Numeric (KOH, womens)
            "0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "22", "24", "26",
            "000", "00",
            # Youth (UA)
            "YXS", "YSM", "YMD", "YLG", "YXL", "YXXL", "Y3XL", "Y2XL",
            # Petite variants (KOH)
            "2P", "4P", "6P", "8P", "10P", "12P", "14P", "16P", "18P", "20P",
            # Tall (KOH)
            "2T", "4T", "6T",
            # General
            "P", "T", "PETITE", "TALL",
            # NEW (2026-05-13): TGT PID 全字 alpha sizes
            "X SMALL", "SMALL", "MEDIUM", "LARGE", "X LARGE", "XX LARGE", "XXX LARGE",
            # NEW (2026-05-13): ON Kids/Baby/Toddler month-based sizes (Old Navy 嬰幼兒線)
            "NB", "NEWBORN", "PREEMIE",
            "0-3 MONTHS", "3-6 MONTHS", "6-9 MONTHS", "6-12 MONTHS", "9-12 MONTHS",
            "12-18 MONTHS", "12-24 MONTHS", "18-24 MONTHS", "24 MONTHS",
            "0- 3 MONTHS", "3- 6 MONTHS", "6- 9 MONTHS", "6- 12 MONTHS",
            "9- 12 MONTHS", "12- 18 MONTHS", "12- 24 MONTHS", "18- 24 MONTHS",
            # Toddler T-sizes (some already in but list explicit)
            "12M", "18M", "24M",
        }

        # Helper: 認 size cell (含 baby/toddler month patterns 動態判)
        _BABY_SIZE_RE = _re.compile(r"^\d+\s*-?\s*\d*\s*(MONTHS?|MOS?|M)$")
        # NEW (2026-05-13): Slash-format size header. Two variants:
        # (a) DSG Athletic Girl's (DAG26102): "XXS/4-5", "XS/6-7", "S/8-9", "M/10-12", "L/14", "XL/16"
        # (b) Centric 8 Production(7.9.2) GAP/ONY: "0000/22", "000/23", "00/24", "0/25", "2/26"..."22/36"
        # (c) ONY GAP womens grading: numeric size code / waist inch
        _SLASH_SIZE_RE = _re.compile(
            r"^(XXS|XS|S|M|L|XL|XXL|SM|MD|LG|2X|3X|4X|"
            r"SMALL|MEDIUM|LARGE|"
            r"\d{1,4})"            # NEW: pure-numeric size code (0000/000/00/0/2/4...22)
            r"\s*/\s*"
            r"\d+(?:\s*-\s*\d+)?$"
        )

        def _is_size_token(s):
            su = (s or "").strip().upper()
            if su in SIZE_TOKENS:
                return True
            # baby/toddler month patterns: "3- 6 MONTHS" / "12 MONTHS" / "12M"
            if _BABY_SIZE_RE.match(su):
                return True
            # Slash format: "XXS/4-5" (DSG) / "0000/22" (Centric 8 Production 7.9.2) / "M/10-12"
            if _SLASH_SIZE_RE.match(su):
                return True
            return False

        POM_CODE_KEYS = ["POM NAME", "POM #", "POM CODE", "DIM", "POM",
                         "POINT OF MEASURE NAME", "POINT OF MEASURE",
                         "CODE"]  # NEW: UA 1357139 layout 用 "Code" 當 header
        DESC_KEYS = ["DESCRIPTION", "POM DESCRIPTION", "POM NAME",
                     "POINT OF MEASURE NAME"]  # NEW: TGT 用同一 col 同時放 code+name
        TOL_NEG_PATTERNS = [r"TOL\s*\(\s*-", r"-\s*TOL", r"TOL\s*FRAC.*-", r"NEG.*TOL",
                            r"-\s*TOLERANCE"]   # NEW: TGT "- Tolerance" 全字
        TOL_POS_PATTERNS = [r"TOL\s*\(\s*\+", r"\+\s*TOL", r"TOL\s*FRAC.*\+", r"POS.*TOL",
                            r"\+\s*TOLERANCE"]  # NEW: TGT "+ Tolerance" 全字

        def _find_main_table(tables):
            """找主要 POM 表. 支援 header 在 row 0 或 row 1-2 (BY 有 prelude row)."""
            best = None
            best_score = 0
            for tbl in tables:
                if not tbl or len(tbl) < 2 or len(tbl[0]) < 6:
                    continue
                # 試 row 0, 1, 2 各當 header
                for header_row_idx in range(min(3, len(tbl))):
                    header = [str(c or "").strip().upper().replace("\n", " ") for c in tbl[header_row_idx]]
                    # 必須有 POM 識別欄 (前 4 cell)
                    has_pom = any(any(k in h for k in POM_CODE_KEYS) for h in header[:4])
                    if not has_pom:
                        continue
                    # 必須有 size token (在後段) — 含 baby/toddler month patterns
                    size_hits = sum(1 for h in header if _is_size_token(h))
                    if size_hits < 3:
                        continue
                    # Score: data rows × size cols
                    data_rows = len(tbl) - header_row_idx - 1
                    score = data_rows * size_hits
                    if score > best_score:
                        best_score = score
                        # 截掉 prelude row, 從 header_row_idx 開始
                        best = (tbl[header_row_idx:], header)
                    break  # 找到 header 就跳出 row 0/1/2 試
            return best

        main = _find_main_table(tables)
        if not main:
            # Fallback 1: vertical text-mode (HLF/KOH/DKS line-borderless, cell-per-line)
            text_mc = _parse_measurement_chart_textmode(text)
            if text_mc and text_mc.get("poms"):
                mc.update(text_mc)
                mc["_parse_mode"] = "text"
                return mc
            # Fallback 2: horizontal text-mode (POM table 橫向 + fraction wrap)
            # 用 pp_text (pdfplumber reading-order) 而非 fitz text — 兩者 layout 不同
            # First observed in A&F PROD InitialTechPack, may apply to other PLMs.
            h_mc = _parse_horizontal_pom_textmode(pp_text or text)
            if h_mc and h_mc.get("poms"):
                mc.update(h_mc)
                mc["_parse_mode"] = "horizontal_text"
                return mc
            # Fallback 3: BY Variance Report (B-XXX code, single-size + variance)
            # 用 fitz text (cell-per-line vertical layout). first observed in BY SD3463.
            by_mc = _parse_by_variance_pom_textmode(text)
            if by_mc and by_mc.get("poms"):
                mc.update(by_mc)
                mc["_parse_mode"] = "by_variance_text"
                return mc
            # Fallback 4: CATO BidPackage (T#### code, single-size, no tolerance)
            cato_mc = _parse_cato_bidpackage_pom_textmode(text)
            if cato_mc and cato_mc.get("poms"):
                mc.update(cato_mc)
                mc["_parse_mode"] = "cato_text"
                return mc
            mc["_no_pom_table"] = True
            return mc

        tbl, header = main

        # === 識別欄位 index (fuzzy match) ===
        col_idx = {}
        size_cols = []
        # 第一次掃: 把 TOL 欄位都收進候選 list (因為 Centric 8 Tol Fraction (- ) 和 (+) text 可能相同)
        tol_candidates = []  # [(col_idx, raw_header)]
        for i, h in enumerate(header):
            hu = h
            # POM code column (first POM-keyword cell)
            if "pom_code" not in col_idx:
                if any(k in hu for k in POM_CODE_KEYS):
                    col_idx["pom_code"] = i
                    continue
            # Description column (skip if same as pom_code)
            if "description" not in col_idx:
                if any(k in hu for k in DESC_KEYS):
                    if i != col_idx.get("pom_code"):
                        col_idx["description"] = i
                        continue
            # POM Variation
            if "variation" not in col_idx and "POM VARIATION" in hu:
                col_idx["variation"] = i
                continue
            # Tol columns (strict pattern先試)
            if "tol_neg" not in col_idx:
                if any(_re.search(pat, hu) for pat in TOL_NEG_PATTERNS):
                    col_idx["tol_neg"] = i
                    continue
            if "tol_pos" not in col_idx:
                if any(_re.search(pat, hu) for pat in TOL_POS_PATTERNS):
                    col_idx["tol_pos"] = i
                    continue
            # 收集模糊 Tol 候選 (header 含 TOL 但分不出 +/-)
            if "TOL" in hu and "MESSAGE" not in hu and "TOLERANCE" not in hu.replace("TOL", "TOLERANCE", 1):
                tol_candidates.append((i, hu))
            # Other columns
            if hu == "QC" and "qc" not in col_idx:
                col_idx["qc"] = i
                continue
            if "CRITICALITY" in hu and "criticality" not in col_idx:
                col_idx["criticality"] = i
                continue
            # Size columns (含 baby/toddler month patterns 動態判)
            if _is_size_token(hu):
                size_cols.append((i, hu))

        # 後處理: 用位置 disambiguate Tol +/- (Centric 8 慣例: 先 (-) 後 (+))
        # 或從 data row 第一筆值的 sign 判斷
        if "tol_neg" not in col_idx and "tol_pos" not in col_idx and len(tol_candidates) >= 2:
            # 排掉已被當其他欄位用的 candidate
            free = [c for c in tol_candidates if c[0] not in col_idx.values() and c[0] != col_idx.get("pom_code") and c[0] != col_idx.get("description")]
            if len(free) >= 2:
                # 慣例: 第一個 = neg, 第二個 = pos (Centric 8 sample 99% 是這個順序)
                # 二次確認: 看第一筆 data row, neg col 通常含 "-"
                first_data = tbl[1] if len(tbl) > 1 else []
                neg_idx, pos_idx = free[0][0], free[1][0]
                if first_data and neg_idx < len(first_data) and pos_idx < len(first_data):
                    v_neg = str(first_data[neg_idx] or "").strip()
                    v_pos = str(first_data[pos_idx] or "").strip()
                    # 若第一筆 pos col 有 "-" 而 neg col 沒, 對調
                    if v_pos.startswith("-") and not v_neg.startswith("-"):
                        neg_idx, pos_idx = pos_idx, neg_idx
                col_idx["tol_neg"] = neg_idx
                col_idx["tol_pos"] = pos_idx
        elif "tol_pos" not in col_idx and len(tol_candidates) == 1 and "tol_neg" in col_idx:
            col_idx["tol_pos"] = tol_candidates[0][0]
        elif "tol_neg" not in col_idx and len(tol_candidates) == 1 and "tol_pos" in col_idx:
            col_idx["tol_neg"] = tol_candidates[0][0]

        if "pom_code" not in col_idx or not size_cols:
            mc["_no_pom_table"] = True
            return mc

        mc["sizes"] = [s for _, s in size_cols]

        # === Parse each POM row ===
        POM_CODE_RE = _re.compile(
            r"^[A-Z]{1,4}\d{1,4}(?:[\.\-][\dA-Z]{1,5})?$"
            r"|^ADHOC$"
            r"|^[A-Z]{1,3}-[A-Z]{1,5}$"           # BY old: B-HPS
            r"|^[A-Z]{2}\d{3}[A-Z]?$"             # UA: DE141
            r"|^POM-[A-Z0-9]{4,8}$"               # TGT: POM-N3GG / POM-JM9Y
            r"|^[A-Z]{2,3}-[A-Z]\d{2,4}(?:\.\d{1,2})?$"  # BY production: BY-B000.0 / BY-B005.1 (2026-05-13)
            r"|^BDY$"                             # BY production: BDY (body length anchor)
        )
        poms = []
        for row in tbl[1:]:
            if not row:
                continue
            raw_cell = (row[col_idx["pom_code"]] or "").strip()
            raw_code = raw_cell.replace("\n", " ").replace("​", "").strip()
            if not raw_code:
                continue
            # 過濾 footer / decorator rows
            rc_upper = raw_code.upper()
            if "DISPLAYING" in rc_upper or "FIT REF" in rc_upper or rc_upper in ("", "POM"):
                continue

            # NEW (2026-05-13): TGT PID layout — POM code embedded in "Point Of Measure Name" cell
            # 例: "NECK WIDTH SEAM POM-N3GG A16S." → code=POM-N3GG, name=NECK WIDTH SEAM
            tgt_extracted_name = None
            if "POM-" in raw_code:
                m_pom = _re.search(r"\b(POM-[A-Z0-9]{4,8})\b", raw_code)
                if m_pom:
                    tgt_extracted_name = raw_code[:m_pom.start()].rstrip(" -\t").strip()
                    raw_code = m_pom.group(1)

            # POM code 必須 alphanumeric (排掉 KOH 的 "A001-LA000-20" 整段 dummy)
            if not POM_CODE_RE.match(raw_code) and raw_code != "ADHOC":
                # try strip suffix (KOH 的 A001 後面跟 dummy)
                m2 = _re.match(r"^([A-Z]{1,4}\d{1,4}(?:[\.\-][\dA-Z]{1,5})?)", raw_code)
                if m2:
                    raw_code = m2.group(1)
                else:
                    continue

            pom = {"POM_Code": raw_code}

            # Description — TGT layout 的 name 在同一 cell, 已 pre-extract
            if tgt_extracted_name:
                pom["POM_Name"] = tgt_extracted_name[:200]
            elif "description" in col_idx:
                desc = (row[col_idx["description"]] or "").strip().replace("\n", " ")
                if desc:
                    pom["POM_Name"] = desc[:200]

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

            # Criticality (DKS)
            if "criticality" in col_idx:
                cr = (row[col_idx["criticality"]] or "").strip()
                if cr:
                    pom["criticality"] = cr

            # Sizes
            sizes_dict = {}
            for col_i, size_name in size_cols:
                if col_i >= len(row):
                    continue
                v = (row[col_i] or "").strip().replace("\n", " ")
                if v:
                    sizes_dict[size_name] = v
            if sizes_dict:
                pom["sizes"] = sizes_dict

            poms.append(pom)

        mc["poms"] = poms
        mc["n_poms_on_page"] = len(poms)

        return mc
