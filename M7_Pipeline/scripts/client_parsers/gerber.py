"""client_parsers/gerber.py — Gerber Technology PLM cover parser.

HLF (High Life) + ANF (A&F / Hollister / abercrombie / Gilly Hicks) 兩家都用
Gerber Technology PLM 系統,cover layout 結構幾乎相同 → 共用 parser。

兩家共同 footer:
    Copyright © 2009-2024 by Gerber Technology

HLF cover (page 1):
    Cover Page 3rd Quarter 2025
    Division High Life  Size Class Mens  Style No CPM253PA50
    Style Category Pants  Size Range N/A  Created Date Monday, November 4, 2024
    Description "C" FLEECE SINCH PANT  Garment Wash/Treatment  Created By ...
    ...
    Season Year 3rd Quarter 2025

ANF cover (page 1, 注意沒有 "Cover Page" header):
    BOOST UHR BOOT 519B0254                    ← 標題:description + Tech Pack #
    Style Type Apparel  Brand Gilly Hicks  Design Contact ...
    Tech Pack # 519B0254  Gender Female  Tech Design Contact ...
    Description BOOST UHR BOOT  Department 19B - Female Active Bottoms  ...
    Variation Variation 1  Development Stage Production  Style Ref # ...
    Season Year Fall 2025  Active Yes  Initial Block ...

Canonical mapping:
    客戶            HLF: 'High Life'   /  ANF: Brand 欄位 (Gilly Hicks/Hollister/...)
    報價款號         HLF: Style No      /  ANF: Tech Pack #
    Item            從 Style Category (HLF) 或 Description+Department (ANF) 推
    Season          Season Year XXX 解析
    Gender          HLF: Size Class (Mens/Womens/...)  /  ANF: Gender 欄位
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


SEASON_QUARTER_MAP = {
    "1st Quarter": "SP", "2nd Quarter": "SU",
    "3rd Quarter": "FA", "4th Quarter": "HO",
    "Spring": "SP", "Summer": "SU", "Fall": "FA",
    "Holiday": "HO", "Winter": "WI", "Autumn": "FA",
}


def _normalize_season(season_raw: str) -> Optional[str]:
    """'3rd Quarter 2025' → 'FA25', 'Fall 2025' → 'FA25'."""
    if not season_raw:
        return None
    for kw, code in SEASON_QUARTER_MAP.items():
        if kw in season_raw:
            m = re.search(r"(\d{4})", season_raw)
            if m:
                return f"{code}{m.group(1)[-2:]}"
    return None


GENDER_PATTERNS = [
    (r"\bMens?\b", "MENS"),
    (r"\bWomens?\b|\bWomen's\b", "WOMENS"),
    (r"\bFemale\b", "WOMENS"),
    (r"\bMale\b", "MENS"),
    (r"\bGirls?\b", "GIRLS"),
    (r"\bBoys?\b", "BOYS"),
    (r"\bUnisex\b", "UNISEX"),
    (r"\bKids?\b|\bChildren\b", "KIDS"),
    (r"\bBaby\b|\bToddler\b|\bInfant\b", "BABY/TODDLER"),
    (r"\bMaternity\b", "MATERNITY"),
]


def _normalize_gender(raw: str) -> Optional[str]:
    if not raw:
        return None
    for pat, code in GENDER_PATTERNS:
        if re.search(pat, raw, re.IGNORECASE):
            return code
    return None


class GerberParser(ClientParser):
    """HLF + ANF Tech Pack cover parser.

    支援兩種 PLM layout:
    1. Gerber Technology PLM (HLF + ANF 部分舊版): "Style No" / "Tech Pack #" / "Size Class" / "Season Year"
    2. abercrombie Centric 8-like PLM (ANF 新版 2025+): "Style Code" / "Group" / "Server" / "A&F PROD" prefix

    Layout 透過 signal keyword 偵測; 找不到時 fallback Gerber.
    """

    def parse_cover(self, page, text: str) -> dict:
        # Layout detection (按 specificity 優先 dispatch):
        # 3. ANF spec sheet (Makalot 自家 template):
        #    fitz 可能把 labels+values 拆兩個 block, 用 token presence 偵測
        has_styleNo = "Style No." in text
        has_anf_brand = ("A&F" in text or "Gilly Hicks" in text or
                         "Hollister" in text or "abercrombie" in text)
        has_specsheet_labels = ("Customer" in text and "Brand" in text and
                                ("Category" in text or "Catogory" in text))
        if has_styleNo and has_anf_brand and has_specsheet_labels:
            return self._parse_spec_sheet_layout(text)
        # 2. ANF Centric 8-like (Centric 內部 PLM): "A&F PROD" prefix OR "Style Code S\d{6,}"
        is_anf_centric = "A&F PROD" in text or re.search(r"Style Code\s+S\d{6,}", text) is not None
        if is_anf_centric:
            return self._parse_anf_centric_layout(text)
        # 1. 默認 Gerber Technology PLM (HLF + ANF 舊版 Gerber)
        return self._parse_gerber_layout(text)

    def _parse_gerber_layout(self, text: str) -> dict:
        meta: dict = {}

        # Style No / Tech Pack # → design_number
        m = re.search(r"Style No\s+([A-Za-z0-9_\-]+)", text)
        if m:
            meta["design_number"] = m.group(1).strip()
        else:
            m = re.search(r"Tech Pack #\s+([A-Za-z0-9_\-]+)", text)
            if m:
                meta["design_number"] = m.group(1).strip()

        # Brand / Division → brand_division
        if self.code == "HLF":
            m = re.search(r"Division\s+([A-Za-z][\w \-&]+?)\s+(?:Size Class|Style No|$)", text)
            if m:
                meta["brand_division"] = m.group(1).strip()
            else:
                meta["brand_division"] = "High Life"
        else:  # ANF
            m = re.search(r"Brand\s+([A-Za-z][\w \-&']+?)\s+(?:Design Contact|Gender|$)", text)
            if m:
                meta["brand_division"] = m.group(1).strip()

        # Description
        # 兩種 layout:
        #  (a) "Description <VALUE> Garment Wash ..." (HLF #1, ANF)
        #  (b) "<VALUE>\nDescription Garment Wash ...\n<VALUE-suffix>" (HLF #2 多行)
        desc = None
        m = re.search(
            r"Description\s+([^\n]+?)\s+(?:Garment Wash|Department|Style Category|Style No|Tech Pack #)",
            text,
        )
        if m:
            cand = re.sub(r"\s+", " ", m.group(1)).strip().strip('"')
            # 排除 (b) 的 "Description Garment Wash/Treatment Created By ..." 純 noise
            if cand and len(cand) > 2 and "Garment Wash" not in cand and "Created By" not in cand:
                desc = cand
        if not desc:
            # Layout (b): 從 "Description" 上一行抓 value (HLF #2)
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if line.strip().startswith("Description ") and "Garment Wash" in line:
                    # 上一行 = value head; 下一行可能是 value tail
                    head = lines[i-1].strip() if i > 0 else ""
                    tail_idx = i + 1
                    tail = lines[tail_idx].strip() if tail_idx < len(lines) else ""
                    # tail 若是另一個 key 開頭(Design Contact / Fit Standard 等)就不要
                    if tail and re.match(r"^(Design|Fit|Tech|Sourcing|Brand|Season|Style|Modified|Created|Variation|Page|Copyright)\b", tail):
                        tail = ""
                    cand = f"{head} {tail}".strip().strip('"')
                    if cand and len(cand) > 2:
                        desc = cand
                    break
        if desc:
            meta["description"] = desc[:200]

        # Style Category (HLF) → item_type
        m = re.search(r"Style Category\s+([A-Za-z][\w \-/&]+?)\s+(?:Size Range|Style No|$)", text)
        if m:
            meta["item_type"] = m.group(1).strip()
        else:
            # ANF: Department 含類似 "19B - Female Active Bottoms" → item_type='Active Bottoms'
            m = re.search(
                r"Department\s+(?:[\w]+\s*-\s*)?([A-Za-z][\w \-/&]+?)\s+(?:Production Contact|Gender|$)",
                text,
            )
            if m:
                meta["item_type"] = m.group(1).strip()

        # Department raw (ANF)
        m = re.search(r"Department\s+([\w\d]+\s*-\s*[A-Za-z][\w \-/&]+?)\s+(?:Production Contact|Gender|$)", text)
        if m:
            meta["department"] = m.group(1).strip()

        # Gender
        # HLF: Size Class (Mens/Womens/Boys/Girls/...)
        m = re.search(r"Size Class\s+([A-Za-z]+)", text)
        if m:
            g = _normalize_gender(m.group(1))
            if g:
                meta["gender"] = g
        # ANF: Gender 欄位
        if "gender" not in meta:
            m = re.search(r"Gender\s+([A-Za-z]+)", text)
            if m:
                g = _normalize_gender(m.group(1))
                if g:
                    meta["gender"] = g
        # Fallback: 從 description / department 推
        if "gender" not in meta:
            for src in (meta.get("description", ""), meta.get("department", ""), text[:500]):
                g = _normalize_gender(src)
                if g:
                    meta["gender_inferred"] = g
                    break

        # Season Year
        m = re.search(r"Season Year\s+((?:\d(?:st|nd|rd|th)\s+Quarter|Spring|Summer|Fall|Holiday|Winter)[^|\n]*?\d{4})", text)
        if m:
            raw = m.group(1).strip()
            meta["season_raw"] = raw
            norm = _normalize_season(raw)
            if norm:
                meta["season"] = norm

        # Style Type (ANF: 'Apparel' / 'Knitwear')
        m = re.search(r"Style Type\s+([A-Za-z][\w \-]+?)\s+(?:Brand|$)", text)
        if m:
            meta["style_type"] = m.group(1).strip()

        # Design Sub-Type / Variation (ANF)
        m = re.search(r"Variation\s+([A-Za-z0-9][\w \-/&]+?)\s+(?:Development Stage|$)", text)
        if m:
            meta["variation"] = m.group(1).strip()

        # Active flag (ANF)
        m = re.search(r"\bActive\s+(Yes|No)\b", text)
        if m:
            meta["active"] = m.group(1).strip()

        # Strip empty/noise
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---")}

        return meta

    def _parse_anf_centric_layout(self, text: str) -> dict:
        """ANF abercrombie Centric 8-like 新版 layout (2025+).

        Layout 範例:
            A&F PROD RECHARGE LR TIE FRONT BAGGY PANT Updated spec sheet ...
            Server S265190007 5/15
            Properties
            Style RECHARGE LR TIE FRONT  Department 519 - GH FEMALE ACTIVE  Sourcing Contact ...
            BAGGY PANT S265190007         BOTTOMS                            Tech Design Contact ...
            Style Code S265190007  Imports Category
            Season Spring 2026  Fit Pattern Name
            Brand Gilly Hicks  Design Contact ...
            Group Women's  Global Merchant Contact ...
        """
        meta: dict = {}

        # design_number: Style Code 優先
        m = re.search(r"Style Code\s+([A-Za-z0-9_\-]+)", text)
        if m:
            meta["design_number"] = m.group(1).strip()
        else:
            # Server 行 fallback
            m = re.search(r"Server\s+([A-Z]\d{6,})", text)
            if m:
                meta["design_number"] = m.group(1).strip()

        # brand_division: Brand <X>  (Gilly Hicks / Hollister / abercrombie / abercrombie kids)
        # 終止字: Design Contact / Group / Sourcing / Global / Tech Design / 換行 / .zip 等檔名 noise
        # 用 [^\n]+? 容納特殊字元(. , 等),後處理 strip noise
        m = re.search(
            r"Brand\s+([A-Za-z][^\n]+?)(?=\s+(?:Design Contact|Group|Sourcing|Global|Tech Design)|\s*\.[a-z]{3,4}\b|\n|$)",
            text,
        )
        if m:
            brand = re.sub(r"\s+", " ", m.group(1)).strip()
            # 排掉尾巴可能黏到的檔名 (e.g. "Gilly Hicks NONSHRINK")
            brand = re.sub(r"\s+[A-Z][A-Z0-9_\-]{3,}$", "", brand).strip()
            if brand:
                meta["brand_division"] = brand

        # description: title bar "A&F PROD <NAME>" OR "Style <NAME>"
        # 例: "A&F PROD RECHARGE LR TIE FRONT BAGGY PANT Updated spec sheet"
        m = re.search(r"A&F PROD\s+(.+?)\s+(?:Updated spec sheet|Initial Tech Pack|Final Tech Pack|Tech Pack|$)", text)
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()
            if desc and len(desc) > 2:
                meta["description"] = desc[:200]
        if "description" not in meta:
            # Fallback: "Style <DESC>" 行
            m = re.search(
                r"Style\s+([A-Z][\w \-&'\(\):]+?)\s+(?:Department|Imports Category|S\d{6,}|$)",
                text,
            )
            if m:
                desc = re.sub(r"\s+", " ", m.group(1)).strip()
                if desc and len(desc) > 2 and "Code" not in desc:
                    meta["description"] = desc[:200]

        # department: "Department 519 - GH FEMALE ACTIVE BOTTOMS"
        m = re.search(
            r"Department\s+(\d+\s*-\s*[A-Z][\w \-/&]+?)\s+(?:Sourcing|Tech Design|Global|$)",
            text,
        )
        if m:
            meta["department"] = m.group(1).strip()

        # gender: Group <X> 優先 (Women's / Men's / girls / boys / Women / Men)
        m = re.search(r"Group\s+(Women['’]?s?|Men['’]?s?|Girls?|Boys?|Unisex|Kids?)", text, re.IGNORECASE)
        if m:
            g = _normalize_gender(m.group(1))
            if g:
                meta["gender"] = g
        # Fallback: 從 department 推 (FEMALE → WOMENS, MALE → MENS, GIRLS, BOYS)
        if "gender" not in meta:
            dept_raw = meta.get("department", "")
            g = _normalize_gender(dept_raw)
            if g:
                meta["gender_inferred"] = g

        # season: "Season Spring 2026" → SP26
        m = re.search(r"Season\s+(Spring|Summer|Fall|Holiday|Winter|Autumn)\s+(\d{4})", text)
        if m:
            raw = f"{m.group(1)} {m.group(2)}"
            meta["season_raw"] = raw
            norm = _normalize_season(raw)
            if norm:
                meta["season"] = norm

        # item_type: 從 description / department 推
        haystack = (meta.get("description", "") + " " + meta.get("department", "")).lower()
        for kw, item in [
            ("legging", "LEGGINGS"), ("jogger", "JOGGERS"), ("tight", "LEGGINGS"),
            ("short", "SHORTS"), ("pant", "PANTS"),
            ("tee", "TEE"), ("polo", "POLO"), ("hoodie", "HOODIE"),
            ("pullover", "PULLOVER"), ("jacket", "JACKET"),
            ("dress", "DRESS"), ("skirt", "SKIRT"), ("bra", "BRA"),
            ("swim", "SWIM"), ("sleep", "SLEEPWEAR"),
            ("bottoms", "BOTTOM"),  # generic Department BOTTOMS fallback
            ("tops", "TOP"),
        ]:
            if kw in haystack:
                meta["item_type"] = item
                break

        # imports_category (KNIT / WOVEN 推 fabric)
        m = re.search(r"Imports Category\s+(Knit|Woven|Denim|Sweater)", text, re.IGNORECASE)
        if m:
            meta["fabric"] = m.group(1).upper()

        # Strip empty values
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---")}

        return meta

    def _parse_spec_sheet_layout(self, text: str) -> dict:
        """ANF Makalot-internal spec sheet template (Sample Room 格式).

        fitz text extraction 把 labels 和 values 分散在不同 text block,
        無法用 "Style No. <X>" inline 模式. 改用 token-based search.

        策略:
        - design_number: 找 ^[A-Z]{2,4}\d{2}[A-Z]+[\d\-_]*$ 樣式的行
        - brand: scan known brands (Gilly Hicks/Hollister/...)
        - customer: standalone "A&F" / "Beyond Yoga" line
        - gender: standalone "Women"/"Men"/"Girls"/"Boys" line

        Layout (page 1):
            Style No. GH26SPT01 Size. S Prototype Y N Designer Date Page Measurement Inch
            Customer A&F Brand Gilly Hicks Category Women Lizzy#3888 1/1 胸寬
            Reference Style No. ... [中文 spec 內文] ...

        Design code 前綴推 brand:
            GH = Gilly Hicks   HOL = Hollister   AF / ABC = abercrombie
        """
        meta: dict = {}
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # === design_number: 找符合 spec sheet code 樣式的單行 ===
        # 樣式: 2-4 letter prefix + 2 digit year + letters + digits
        # 例: GH26SPT01, BY26SP012, AF26FA01, HOL25SP03
        DN_PATTERN = re.compile(r"^[A-Z]{2,4}\d{2}[A-Z]+[\d\-_]+$")
        for line in lines:
            if DN_PATTERN.match(line):
                meta["design_number"] = line
                # Season 推: prefix 中含 ##SP/SU/FA/HO/WI
                sm = re.search(r"(\d{2})(SP|SU|FA|HO|WI)", line)
                if sm:
                    meta["season"] = f"{sm.group(2)}{sm.group(1)}"
                break

        # === Brand: 掃 known sub-brand 標識 ===
        KNOWN_BRANDS = ["Gilly Hicks", "Hollister", "abercrombie kids", "abercrombie",
                        "Beyond Yoga", "A&F"]
        for line in lines:
            for b in KNOWN_BRANDS:
                if line == b or line.startswith(b):
                    meta["brand_division"] = b
                    break
            if "brand_division" in meta:
                break

        # === Gender: scan for standalone English 性別字 ===
        for line in lines:
            g = _normalize_gender(line)
            if g and len(line) <= 10:  # standalone token, not a sentence
                meta["gender"] = g
                break

        # === Description: 用 design_number + brand 拼 ===
        # spec sheet 沒有正式 description 欄, 也找不到英文 description
        if "design_number" in meta:
            meta["description"] = meta["design_number"]

        # === item_type 從 design_number suffix / Chinese keyword 推 ===
        # GH26SPT01 中 T = TOP, B = BOTTOM, D = DRESS, L = LEGGING (Makalot 內部慣例)
        if "design_number" in meta:
            dn = meta["design_number"]
            sm = re.search(r"\d{2}(SP|SU|FA|HO|WI)([A-Z])", dn)
            if sm:
                code = sm.group(2)
                suffix_map = {
                    "T": "TOP", "B": "BOTTOM", "D": "DRESS",
                    "L": "LEGGINGS", "S": "SHORTS", "J": "JACKET",
                    "P": "PANTS", "K": "SKIRT",
                }
                if code in suffix_map:
                    meta["item_type"] = suffix_map[code]

        # Fallback: Chinese keyword scan
        if "item_type" not in meta:
            haystack = text[:3000].lower()
            for kw, item in [
                ("legging", "LEGGINGS"), ("jogger", "JOGGERS"),
                ("dress", "DRESS"), ("skirt", "SKIRT"),
                ("jacket", "JACKET"), ("hoodie", "HOODIE"),
                ("pant", "PANTS"), ("short", "SHORTS"),
                # 中文 hint
                ("洋裝", "DRESS"), ("連身裙", "DRESS"),
                ("外套", "JACKET"), ("夾克", "JACKET"),
                ("緊身褲", "LEGGINGS"), ("褲", "PANTS"),
                ("裙", "SKIRT"),
                ("運動內衣", "BRA"), ("罩杯", "BRA"),
                ("上衣", "TOP"),
            ]:
                if kw in haystack:
                    meta["item_type"] = item
                    break

        # Strip empty
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}
        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]
