"""client_parsers/underarmour.py — Under Armour Techpack cover parser.

UA 用自家 PLM(非 Centric / 非 Gerber). cover 在 page 1 'Cover Sheet Properties'.

Layout 範例(注意 PDF text extract 會在數字中插入空格,e.g. "SS26-6 011047"):

    SS26-6011047-US-Makalot Industrial Co., LTD - 603086 - PT. Glory Industrial ...
    Under 6011047 SS26-6 011047- US-M akalot Industrial Co., LTD - ...
    Armour
    Cover Sheet Properties
    Sample Status Submit Prototype | Material Description ... | Created By ...
    Supplier Request Round Prototype 1 ...
    Regional Fit US
    Main Material # WN-213523
    Properties
    Style # 6011047 | Sourcing Class
    Style Name UA Woven Printed Short | Product Family Other
    Season SS26 | Fit Type Loose
    Gender Boys | Fabrication Woven
    Division Apparel | Graphic Reference
    B&W Sub Category Train | Size Range YXS-Y3XL
    Product Team Apparel-Train-Mens & Boys | Actual Sizes YXS-Y3XL

Canonical mapping:
    客戶              固定 'UNDER ARMOUR'
    報價款號           Style # 後的數字
    Item             Sourcing Class (e.g. 'Bottoms - Woven Shorts' → SHORTS)
    Season           Season 欄位 (SS26/FW25/...)
    Gender           Gender 欄位 (Boys/Mens/Womens/Girls)
    PRODUCT_CATEGORY  Sub Category + Fabrication
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


# UA Season code 已經是 SS26 / FW25 格式,不用 normalize
UA_SEASON_RE = re.compile(r"\b(SS|FW|SP|FA|HO|SU)\d{2}\b")

GENDER_NORM = {
    "Mens": "MENS", "Men's": "MENS", "Male": "MENS",
    "Womens": "WOMENS", "Women's": "WOMENS", "Female": "WOMENS",
    "Boys": "BOYS", "Girls": "GIRLS",
    "Unisex": "UNISEX",
    "Kids": "KIDS", "Youth": "KIDS",
}


def _clean(v: str) -> str:
    """PDF text 在數字中亂插空格,clean 一下."""
    return re.sub(r"(?<=\d)\s+(?=\d)", "", v).strip()


class UnderArmourParser(ClientParser):
    """UA cover parser."""

    def parse_cover(self, page, text: str) -> dict:
        meta: dict = {"brand_division": "UNDER ARMOUR"}

        # Style #
        m = re.search(r"Style\s*#\s*(\d{4,}[A-Za-z0-9_\-]*)", text)
        if m:
            meta["design_number"] = _clean(m.group(1))

        # Style Name
        m = re.search(r"Style Name\s+(.+?)\s+(?:Product Family|Season|$)", text)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            if name:
                meta["style_name"] = name[:200]
                meta["description"] = name[:200]

        # Season (SS26 / FW25 / ...)
        m = UA_SEASON_RE.search(text)
        if m:
            meta["season"] = m.group(0)
        else:
            m = re.search(r"Season\s+([A-Z]{2}\d{2})", text)
            if m:
                meta["season"] = m.group(1)

        # Gender
        m = re.search(r"Gender\s+(Boys|Girls|Mens?|Womens?|Men's|Women's|Unisex|Kids?|Youth)", text)
        if m:
            meta["gender"] = GENDER_NORM.get(m.group(1), m.group(1).upper())

        # Fabrication
        m = re.search(r"Fabrication\s+(Woven|Knit|Denim|Sweater|Fleece|Mesh)", text, re.IGNORECASE)
        if m:
            meta["fabric"] = m.group(1).upper()

        # Sourcing Class (e.g. 'Bottoms - Woven Shorts')
        # 要在同一行,不能跨行 (跨行表示原欄位是空的)
        m = re.search(r"Sourcing Class\s+([^\n]+?)\s+(?:Product Family|Style Name|Season|$)", text)
        if m:
            sc = re.sub(r"\s+", " ", m.group(1)).strip()
            # 排除誤抓: 若內容以 "Style Name" 開頭表示 sourcing class 本來是空的
            if sc and not sc.startswith("Style Name") and not sc.startswith("Season"):
                meta["sourcing_class"] = sc[:120]

        # Sub Category (e.g. 'Train' / 'Run' / 'Outdoor')
        m = re.search(r"Sub Category\s+(.+?)\s+(?:Size Range|Actual Sizes|$)", text)
        if m:
            meta["sub_category"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]

        # Division
        m = re.search(r"Division\s+(Apparel|Accessories|Footwear|Equipment)", text)
        if m:
            meta["division"] = m.group(1).strip()

        # Fit Type
        m = re.search(r"Fit Type\s+(Loose|Fitted|Regular|Slim|Relaxed|Compression|Straight|Athletic)", text, re.IGNORECASE)
        if m:
            meta["fit_type"] = m.group(1).strip()

        # Item type 推導 (從 sourcing_class / style_name / description)
        # 用單數 keyword 同時 cover 單數/複數 (e.g. "Short" matches both "Short" and "Shorts")
        sc = meta.get("sourcing_class", "")
        sn = meta.get("style_name", "")
        haystack = f"{sc} {sn}".lower()
        # 順序很重要: 長 keyword (Jogger/Legging) 必須在 Pant/Short 之前 check,
        # 否則 "Jogger Pant" 會先 match Pant 而非 Jogger
        for kw, item in [
            ("legging", "LEGGINGS"),
            ("jogger", "JOGGERS"),
            ("tight", "LEGGINGS"),
            ("short", "SHORTS"),
            ("pant", "PANTS"),
            ("tee", "TEE"),
            ("polo", "POLO"),
            ("hoodie", "HOODIE"),
            ("pullover", "PULLOVER"),
            ("jacket", "JACKET"),
            ("vest", "VEST"),
            ("dress", "DRESS"),
            ("skirt", "SKIRT"),
            ("bra", "BRA"),
            ("swim", "SWIM"),
            ("sleep", "SLEEPWEAR"),
        ]:
            if kw in haystack:
                meta["item_type"] = item
                break

        # Fallback: empty 值剃掉
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}

        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]
