"""client_parsers/gu.py — GU (UNIQLO subsidiary) Techpack parser.

GU PDF cover 格式 (デザイン管理表 / Design Management Table — 日文):
  デザイン管理表  (header)
  企業           GU
  デザイン名     LSK1308       ← design_number
  ブランド       (常空)
  アイテム       Long Skirt     ← item type
  シーズン       27SS           ← season
  ページ         1/1
  品番           227H027        ← style number (報價款號)
  パーツ数       7
  サイズ         Master
  縮尺           1/21.0
  作成者         Takahashi     ← creator
  デザイナー     (常空)
  作成日         2025/12/01 16:32
  更新日         2026/04/13 14:48
  出力日         2026/04/13 14:49

格式注意:
- 日文 keyword
- key 跟 value 各自一行 (key \n value)
- 多數欄位常空, 用 "next 非空 line 且不是下個 key" 邏輯抓 value
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


# Japanese keyword → English schema key
GU_KEY_MAP = {
    "企業": "company",
    "デザイン名": "design_number",
    "ブランド": "brand",
    "アイテム": "item",
    "シーズン": "season_raw",
    "ページ": "page",
    "品番": "style_number",
    "パーツ数": "parts_count",
    "サイズ": "size_range",
    "縮尺": "scale",
    "作成者": "creator",
    "デザイナー": "designer",
    "作成日": "creation_date",
    "更新日": "update_date",
    "出力日": "print_date",
}

GU_KEYS_SET = set(GU_KEY_MAP.keys())


SEASON_MAP = {"SS": "SP", "FW": "FA", "FA": "FA", "AW": "FA", "SU": "SU", "WI": "WI", "HO": "HO"}


class GUParser(ClientParser):
    def parse_cover(self, page, text: str) -> dict:
        lines = [l.strip() for l in text.split("\n")]
        meta = {}

        for i, line in enumerate(lines):
            if line not in GU_KEYS_SET:
                continue
            key_en = GU_KEY_MAP[line]
            # 找下個非空 line, 且不是另一個 key
            for j in range(i + 1, min(i + 5, len(lines))):
                v = lines[j].strip()
                if not v:
                    continue
                if v in GU_KEYS_SET:
                    break  # value 真的空, skip
                meta[key_en] = v[:120]
                break

        # Brand 一定是 GU (這是 GU brand)
        meta["brand_division"] = "GU"

        # Parse season "27SS" → SP27 / "26FW" → FA26
        sr = meta.get("season_raw", "")
        sm = re.match(r"^(\d{2})(SS|FW|FA|SU|WI|HO|AW)$", sr.upper())
        if sm:
            yr, sn = sm.group(1), sm.group(2)
            meta["season"] = f"{SEASON_MAP.get(sn, sn)}{yr}"

        # Map item → garment_type hint
        item = (meta.get("item") or "").upper()
        if item:
            if "SKIRT" in item:
                meta["garment_type"] = "SKIRT"
            elif "PANT" in item or "TROUSER" in item:
                meta["garment_type"] = "BOTTOM"
            elif "SHIRT" in item or "BLOUSE" in item or "TEE" in item or "POLO" in item:
                meta["garment_type"] = "TOP"
            elif "DRESS" in item:
                meta["garment_type"] = "DRESS"
            elif "JACKET" in item or "COAT" in item:
                meta["garment_type"] = "OUTER"

        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]

