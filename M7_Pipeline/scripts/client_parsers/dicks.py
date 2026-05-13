"""client_parsers/dicks.py — Dick's Sporting Goods (DSG / Calia / VRST) Techpack parser.

DSG PDF cover 格式 (Tech Pack - page 1):
  Brand:               DSG / Calia / VRST
  Style Number :       DAW17703
  Style Description :  MOMENTUM MEDIUM SUPPORT BRA
  Component Last Modified : 04/20/2026 5:49:14 PM - EDT
  Season :             Softlines - Athletic Women's - Spring - 2027
  Source :             001 : Makalot Industrial Co., Ltd - 75061
  Product Status :     Development
  Sample Status :      Proto - Sample - 1 : Pending
  Gender               Womens
  Size Range           XXS,XS,S,M,L,XL,XXL

Season 欄位含 dept + gender + 季節, 要 parse 出來:
  "Softlines - Athletic Women's - Spring - 2027" →
    department="Athletic", gender_inferred="WOMENS", season="SP27"
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


SEASON_MAP = {
    "Spring": "SP", "Summer": "SU", "Fall": "FA",
    "Holiday": "HO", "Winter": "WI",
}

DEPT_KW = ["Athletic", "Performance", "Outdoor", "Sleepwear", "Lifestyle",
           "Footwear", "Equipment", "Accessories"]


class DicksParser(ClientParser):
    """DKS / DSG cover parser. Centric 8 對齊的 short brand_division 邏輯。"""

    def parse_cover(self, page, text: str) -> dict:
        meta = {}

        # === 2026-05-12 加: DSG Makalot Sample Room layout (DSG26AW009 等) ===
        # 案例 EIDH 308573 — "DSG | S | Style No. | Designer | Patty#3877 | DSG26A..."
        # 跟 KOH CBRTW / TGT AIM 同類 (聚陽內部 spec sheet)
        upper = text.upper()
        has_dsg_code = bool(re.search(r"\b(DSG\d{2}[A-Z]{2}\w{3,8}|"
                                       r"VRST\d{2}\w+|CALIA\d{2}\w+)\b", text))
        if has_dsg_code and ("Style No." in text or "STYLE NO." in upper):
            sr_meta = self._parse_dsg_sample_room_layout(text)
            if sr_meta and len(sr_meta) > 1:
                return sr_meta

        # Multi-line key:value 配對。value 可能在下一行。
        # PDF text-layer 通常 "Key :\n value" 兩行。
        patterns = {
            "brand_division": r"Brand\s*:\s*\n?\s*([A-Za-z][\w \-/&]+?)(?:\n|$)",
            "design_number": r"Style Number\s*:\s*\n?\s*([A-Za-z0-9_\-]+)",
            "description": r"Style Description\s*:\s*\n?\s*((?:[^\n]+\n?){1,2}?)(?=\n[A-Z][a-z]+\s*:|\n\n|$)",
            "component_modified": r"Component Last Modified\s*:\s*\n?\s*([^\n]+)",
            "season_full": r"Season\s*:\s*\n?\s*((?:[^\n]+\n?){1,3}-\s*\d{4})",
            "source_info": r"Source\s*:\s*\n?\s*(\d+\s*:\s*[^\n]+)",
            "product_status": r"Product Status\s*:\s*\n?\s*([A-Za-z][^\n]+)",
            "sample_status": r"Sample Status\s*:\s*\n?\s*([A-Za-z][^\n]+)",
            "gender": r"Gender\s*\n+\s*(Womens|Mens|Girls|Boys|Unisex|Kids|Baby)",
            "size_range": r"Size Range\s*\n+\s*([A-Z0-9,/\- ]+?)(?:\n|$)",
            "department_raw": r"Department\s*:\s*\n?\s*([A-Za-z][^\n]+)",
            "tech_pack_type": r"Tech Pack Type\s*\n+\s*([A-Za-z][^\n]+)",
        }
        for key, pat in patterns.items():
            m = re.search(pat, text)
            if m:
                v = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(":-").strip()
                if v and v.lower() not in ("none", "tbd", "n/a", "---", "(empty)", ""):
                    meta[key] = v[:200]

        # === Parse season string: "Softlines - Athletic Women's - Spring - 2027" ===
        season_text = meta.get("season_full", "")
        if season_text:
            # 季節 + 年: SP27
            sm = re.search(r"\b(Spring|Summer|Fall|Holiday|Winter)\s*-?\s*(\d{4})", season_text)
            if sm:
                yr = sm.group(2)[-2:]
                meta["season"] = f"{SEASON_MAP[sm.group(1)]}{yr}"
            # Department (從 season 內 fallback, 如果 cover 沒明確 department 欄)
            if "department_raw" not in meta:
                for dept in DEPT_KW:
                    if dept in season_text:
                        meta["department"] = dept
                        break
            # Gender (從 season 內 fallback)
            if "gender" not in meta:
                for g_pat, code in [
                    (r"Women['’]?s", "WOMENS"), (r"Men['’]?s", "MENS"),
                    (r"Girls", "GIRLS"), (r"Boys", "BOYS"),
                ]:
                    if re.search(g_pat, season_text):
                        meta["gender_inferred"] = code
                        break

        # Normalize brand_division: "DSG" / "Calia" / "VRST" 等
        if "brand_division" in meta:
            bd = meta["brand_division"].upper().strip()
            # 截掉尾巴 noise (例如 "DSG\nStyle Number")
            bd = bd.split()[0] if bd else ""
            meta["brand_division"] = bd

        # Normalize gender from "Womens" → "WOMENS" 等
        if "gender" in meta:
            meta["gender"] = meta["gender"].upper().strip()

        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        # DKS callout pages 是 image-based, structured extract 難。
        # 保留 raw text 給之後 VLM 處理。
        return [{"_raw_callout_text": text[:5000]}]

    # ════════════════════════════════════════════════════════════
    # _parse_dsg_sample_room_layout — DKS 聚陽內部 Sample Room (2026-05-12 加)
    # ════════════════════════════════════════════════════════════
    # 案例 EIDH 308573 (DSG26AW009 Women) / 308574 / 308787 / 309543 / 309597 等
    # Layout:
    #   "線色請對大身色 | V2 | DSG | S | Style No. | Size. | Customer | Brand | Inch |
    #    WOMEN | N | Prototype | Catogory | Measurement | Designer | Date | Page |
    #    Patty#3877 | Reference Style # | ... | DSG26AW009 | ..."
    # 跟 KOH CBRTW / TGT AIM 同類 (聚陽內部 spec sheet)
    # ════════════════════════════════════════════════════════════
    def _parse_dsg_sample_room_layout(self, text: str) -> dict:
        """DKS 聚陽 Sample Room (DSG/Calia/VRST 線).

        策略: 多 anchor regex 抽取.
        """
        meta = {"brand_division": "DSG"}

        # === 1. design_number (DSG/Calia/VRST 線款號) ===
        m = re.search(
            r"\b(DSG\d{2}[A-Z]{2}\w{3,8}|"     # DSG26AW009
            r"VRST\d{2}\w+|"                    # VRST26FAB001
            r"CALIA\d{2}\w+)\b",                # CALIA26W
            text
        )
        if m:
            meta["design_number"] = m.group(1)
            # 從 prefix 推 brand_division
            if m.group(1).startswith("CALIA"):
                meta["brand_division"] = "Calia"
            elif m.group(1).startswith("VRST"):
                meta["brand_division"] = "VRST"
            else:
                meta["brand_division"] = "DSG"

        # === 2. designer (聚陽內部編號 e.g. "Patty#3877") ===
        m = re.search(r"\b([A-Z][a-zA-Z]+)\s*#\s*(\d{3,5})\b", text)
        if m:
            meta["designer"] = f"{m.group(1)} #{m.group(2)}"

        # === 3. gender ===
        upper = text.upper()
        if "WOMEN" in upper or "WOMENS" in upper or "WOMEN'S" in upper:
            meta["gender"] = "WOMENS"
        elif "MEN" in upper:
            meta["gender"] = "MENS"
        elif "GIRLS" in upper:
            meta["gender"] = "GIRLS"
        elif "BOYS" in upper:
            meta["gender"] = "BOYS"

        # === 4. season 從 design_number 推 ===
        dn = meta.get("design_number", "")
        m = re.search(r"DSG(\d{2})([A-Z]{2})", dn)
        if m:
            yr = m.group(1)
            sn_code = m.group(2)
            # AW = Autumn/Winter, SS = Spring/Summer, SP = Spring, FA = Fall, etc.
            sn_map = {"AW": "FA", "SS": "SP", "SP": "SP", "FA": "FA",
                      "HO": "HO", "SU": "SU", "FW": "FA"}
            if sn_code in sn_map:
                meta["season"] = f"{sn_map[sn_code]}{yr}"
                meta["season_raw"] = f"DSG{yr}{sn_code}"

        # === 5. size_raw ===
        m = re.search(r"\b(Small|Medium|Large|XS|XXS|XL|XXL|XXXL)\b", text)
        if m:
            meta["size_raw"] = m.group(1)

        # === 6. category_raw ===
        # "Prototype" / "Production" / "Reference" 等
        m = re.search(r"\b(Prototype|Production|Reference Style|Salesman Sample)\b", text)
        if m:
            meta["category_raw"] = m.group(1)

        return meta
