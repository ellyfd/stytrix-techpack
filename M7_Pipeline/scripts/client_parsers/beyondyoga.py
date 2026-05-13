"""client_parsers/beyondyoga.py — Beyond Yoga Techpack cover parser.

BY 用內部 BOM(Bill of Materials)系統,cover page 是 'BILL OF MATERIALS' table,
不是傳統 cover sheet。

Layout 範例:

    BILL OF MATERIALS
    Page 1 of 2
    DATE FINALIZED PENDING            PRODUCT COLOR CODE
    STYLE # SD3027                     ← 報價款號
    I. DRKNT DARKEST NIGHT
    STYLE DESCRIPTION SPACEDYE VITALIZE FULL LENGTH LEGGING   ← Item 推
    II.
    FABRIC
    III.
    LENGTH -
    STYLE CONTENT
    SEASON S/26 SPRING 2026            ← Season
    FACTORY
    ...
    BEYOND YOGA                        ← brand watermark

Canonical mapping:
    客戶              固定 'BEYOND YOGA'
    報價款號           STYLE # 後的 ID
    Item             從 STYLE DESCRIPTION 推 (LEGGING/JOGGER/...)
    Season           'S/26 SPRING 2026' → SP26 之類
    Gender           固定 WOMENS (BY 是 fitness brand, 主要 women's)
    PRODUCT_CATEGORY  從 STYLE DESCRIPTION 推
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


SEASON_NORM = {
    "SPRING": "SP", "SUMMER": "SU", "FALL": "FA",
    "HOLIDAY": "HO", "WINTER": "WI", "AUTUMN": "FA",
}


def _normalize_by_season(raw: str) -> Optional[str]:
    """'S/26 SPRING 2026' → 'SP26'; 'F/25 FALL 2025' → 'FA25'."""
    if not raw:
        return None
    raw_upper = raw.upper()
    # 找季節 keyword
    for kw, code in SEASON_NORM.items():
        if kw in raw_upper:
            # 找 2-digit 或 4-digit 年份
            m = re.search(r"\b(\d{4})\b", raw)
            if m:
                return f"{code}{m.group(1)[-2:]}"
            m = re.search(r"/(\d{2})\b", raw)
            if m:
                return f"{code}{m.group(1)}"
    # 短碼 fallback: 'S/26' 推 SP26, 'F/25' 推 FA25
    short_map = {"S/": "SP", "F/": "FA", "H/": "HO", "W/": "WI", "SU/": "SU"}
    for prefix, code in short_map.items():
        m = re.match(rf"{re.escape(prefix)}(\d{{2}})", raw)
        if m:
            return f"{code}{m.group(1)}"
    return None


GENDER_NORM_BY = {
    "Women": "WOMENS", "Womens": "WOMENS", "Women's": "WOMENS", "Female": "WOMENS",
    "Men": "MENS", "Mens": "MENS", "Men's": "MENS", "Male": "MENS",
    "Girls": "GIRLS", "Girl": "GIRLS",
    "Boys": "BOYS", "Boy": "BOYS",
    "Kids": "KIDS", "Children": "KIDS",
    "Unisex": "UNISEX",
}


def _normalize_gender_by(raw: str) -> str:
    if not raw:
        return ""
    key = raw.strip()
    if key in GENDER_NORM_BY:
        return GENDER_NORM_BY[key]
    cap = key.capitalize().rstrip("s")
    return GENDER_NORM_BY.get(cap, "")


ITEM_KW_MAP = [
    # 順序很重要(長 keyword 先),JOGGER 要在 PANT 之前
    ("LEGGING", "LEGGINGS"),
    ("JOGGER", "JOGGERS"),
    ("SHORT", "SHORTS"),
    ("PANT", "PANTS"),
    ("TANK", "TANK"),
    ("BRA", "BRA"),
    ("TEE", "TEE"),
    ("HOODIE", "HOODIE"),
    ("CREW", "CREW"),
    ("PULLOVER", "PULLOVER"),
    ("JACKET", "JACKET"),
    ("DRESS", "DRESS"),
    ("SKIRT", "SKIRT"),
    ("ROMPER", "ROMPER"),
    ("JUMPSUIT", "JUMPSUIT"),
    ("SKORT", "SKORT"),
    ("UNITARD", "UNITARD"),
]


class BeyondYogaParser(ClientParser):
    """BY BOM-style cover parser."""

    def parse_cover(self, page, text: str) -> dict:
        # === Layout 偵測 ===
        # Layout 1: BOM (BILL OF MATERIALS) — SD\d+ 型款號 (e.g. SD3027)
        # Layout 2: Spec sheet (BY\d{2}SP\d+ 等)
        #   fitz 把 labels/values 拆兩個 block, 用 token presence 偵測
        has_styleNo = "Style No." in text
        has_by = "Beyond Yoga" in text
        has_specsheet = "Customer" in text and "Brand" in text and (
            "Category" in text or "Catogory" in text)
        if has_styleNo and has_by and has_specsheet:
            return self._parse_spec_sheet_layout(text)
        # Default: BOM layout

        meta: dict = {"brand_division": "BEYOND YOGA"}
        upper = text.upper()

        # STYLE #
        m = re.search(r"STYLE\s*#\s*([A-Za-z0-9_\-]+)", text)
        if m:
            meta["design_number"] = m.group(1).strip()

        # STYLE DESCRIPTION
        # LENGTH/FABRIC/STYLE CONTENT 必須是獨立 token(換行起頭),
        # 否則會被 "FULL LENGTH LEGGING" 內部的 LENGTH 誤截斷
        m = re.search(
            r"STYLE DESCRIPTION\s+(.+?)(?=\n(?:II\.|III\.|FABRIC|LENGTH\s*-|STYLE CONTENT|SEASON|FACTORY|$))",
            text,
            re.DOTALL,
        )
        if m:
            desc = re.sub(r"\s+", " ", m.group(1)).strip()
            if desc and len(desc) > 2:
                meta["description"] = desc[:200]
                meta["style_description"] = desc[:200]

        # SEASON
        m = re.search(
            r"SEASON\s+([SFHWU]/\d{2}\s+(?:SPRING|SUMMER|FALL|WINTER|HOLIDAY|AUTUMN)\s+\d{4})",
            text,
            re.IGNORECASE,
        )
        if m:
            raw = m.group(1).strip()
            meta["season_raw"] = raw
            norm = _normalize_by_season(raw)
            if norm:
                meta["season"] = norm
        else:
            # Short fallback: SEASON 後面只剩 S/26
            m = re.search(r"SEASON\s+([SFHWU]/\d{2})", text)
            if m:
                norm = _normalize_by_season(m.group(1))
                if norm:
                    meta["season"] = norm

        # Item type: 從 description 推
        desc_upper = meta.get("description", "").upper()
        for kw, item in ITEM_KW_MAP:
            if kw in desc_upper:
                meta["item_type"] = item
                break

        # Gender — BY 是 women's fitness brand 為主,預設 WOMENS
        # 若 description 含 'MEN'/'BOY'/'GIRL' 則 override(BY 偶爾有 unisex/mens 線)
        if re.search(r"\bMEN['’]?S?\b|\bMALE\b", desc_upper):
            meta["gender"] = "MENS"
        elif re.search(r"\bGIRL", desc_upper):
            meta["gender"] = "GIRLS"
        elif re.search(r"\bBOY", desc_upper):
            meta["gender"] = "BOYS"
        else:
            meta["gender_inferred"] = "WOMENS"  # brand default

        # Fabric / Material (BY 通常用 spacedye / french terry / 等品名)
        # 從 description 找 keyword (推 KNIT 為主, fitness 95% knit)
        if any(kw in desc_upper for kw in ("LEGGING", "TANK", "BRA", "CREW", "HOODIE", "TEE")):
            meta["fabric_inferred"] = "KNIT"

        # Strip empty values
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}

        return meta

    def _parse_spec_sheet_layout(self, text: str) -> dict:
        """BY26SP* / BY26FA* 等 spec sheet 格式 (2026+ 新版).

        Layout:
            Style No. BY26SP012 Size. 6(GAP) Prototype Y N Designer Date Page Mesurement Inch
            Customer Beyond Yoga Brand Beyond Yoga Catogory Women Rocco#3858 1/1 ...
            ...中文 spec text...
            (沒有正式 description 欄位)
        """
        meta: dict = {"brand_division": "BEYOND YOGA"}
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # === design_number: token search (fitz 把 labels/values 分散) ===
        BY_PATTERN = re.compile(r"^BY\d{2}(?:SP|SU|FA|HO|WI)\d+$")
        for line in lines:
            if BY_PATTERN.match(line):
                meta["design_number"] = line
                sm = re.match(r"^BY(\d{2})(SP|SU|FA|HO|WI)", line)
                if sm:
                    meta["season"] = f"{sm.group(2)}{sm.group(1)}"
                break
        if "design_number" not in meta:
            # Fallback: alphanumeric code pattern
            FALLBACK = re.compile(r"^[A-Z]{2,4}\d{2}[A-Z]+[\d\-_]+$")
            for line in lines:
                if FALLBACK.match(line):
                    meta["design_number"] = line
                    break

        # === Gender: standalone single-word line ===
        for line in lines:
            if line in ("Women", "Men", "Girls", "Boys", "Female", "Male", "Unisex"):
                g = _normalize_gender_by(line)
                if g:
                    meta["gender"] = g
                    break
        if "gender" not in meta:
            meta["gender_inferred"] = "WOMENS"

        # === Description: 沒正式欄位, 用 design_number ===
        if "design_number" in meta:
            meta["description"] = meta["design_number"]

        # === item_type 從 body Chinese / English keyword 推 ===
        # 短英文 keyword (≤4 chars) 用 word boundary 避免 "bra" match "brand"; 中文不需要 boundary
        haystack = text[:3000].lower()
        import re as _re_local
        # 順序: 長 keyword 先, 避免 "short" 先 match "shorts" 之外的東西
        for kw, item, use_boundary in [
            ("legging", "LEGGINGS", False),
            ("jogger", "JOGGERS", False),
            ("dress", "DRESS", False),
            ("skirt", "SKIRT", False),
            ("jacket", "JACKET", False),
            ("hoodie", "HOODIE", False),
            ("pullover", "PULLOVER", False),
            ("pant", "PANTS", False),
            ("short", "SHORTS", False),
            ("polo", "POLO", True),
            ("hoodie", "HOODIE", False),
            ("tank", "TANK", True),
            ("tee", "TEE", True),
            ("bra", "BRA", True),  # 必須 boundary, 不然 brand→BRA
            # 中文 (precise hit, 不需 boundary)
            ("洋裝", "DRESS", False), ("連身裙", "DRESS", False),
            ("外套", "JACKET", False), ("夾克", "JACKET", False),
            ("緊身褲", "LEGGINGS", False),
            ("褲", "PANTS", False),
            ("裙", "SKIRT", False),
            ("上衣", "TOP", False),
            ("運動內衣", "BRA", False),
        ]:
            if use_boundary:
                if _re_local.search(rf"\b{kw}\b", haystack):
                    meta["item_type"] = item
                    break
            else:
                if kw in haystack:
                    meta["item_type"] = item
                    break

        # Strip empty
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}
        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]
