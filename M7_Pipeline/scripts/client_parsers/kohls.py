"""client_parsers/kohls.py — Kohl's (FLX / Sonoma / Apt 9 / Tek Gear ...) Techpack parser.

KOH PDF cover 格式 (Tech Spec Overview):
  KOHL'S
  FA26                      ← season
  Stage: DEVELOPMENT
  MX6FK111                  ← design number
  DIAMOND FLEECE HOODIE     ← description (常 2-3 行)
  Tech Spec Overview
  Brand
  FLX                       ← sub-brand (FLX/Sonoma/Apt 9/Tek Gear/Croft & Barrow)
  Division
  MENS                      ← gender (MENS/WOMENS/GIRLS/BOYS)
  Request No.
  00768077
  Create Date 2026-01-28
  Product Type TOPS         ← GT (TOPS/BOTTOMS)
  Product Manager / Designer / Tech Designer (跨行人名)
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


# Sub-brand → 全名 mapping
KOH_SUBBRAND_FULL = {
    "FLX": "FLX",
    "SONOMA": "Sonoma",
    "APT": "Apt 9",
    "APT 9": "Apt 9",
    "TEK GEAR": "Tek Gear",
    "TEKGEAR": "Tek Gear",
    "TG": "Tek Gear",
    "CROFT & BARROW": "Croft & Barrow",
    "CROFT": "Croft & Barrow",
    "C&B": "Croft & Barrow",  # Sample Room 簡寫
    "CB": "Croft & Barrow",
    "SO": "SO",
    "JUMPING BEANS": "Jumping Beans",
    "LC LAUREN CONRAD": "LC Lauren Conrad",
    "LC": "LC Lauren Conrad",
    "SIMPLY VERA": "Simply Vera Vera Wang",
    "ROCK & REPUBLIC": "Rock & Republic",
    "VERA WANG": "Simply Vera Vera Wang",
}

SEASON_MAP = {"SP": "SP", "SU": "SU", "FA": "FA", "HO": "HO", "WI": "WI"}

# Key → schema field. value 是 next-line.
KOH_KEY_VALUE = {
    "Brand": "subbrand",
    "Division": "gender",
    "Request No.": "request_no",
    "Stage": "stage",
    "Designer": "designer",
    "Tech Designer": "tech_designer",
    "Product Manager": "product_manager",
}


class KohlsParser(ClientParser):
    def parse_cover(self, page, text: str) -> dict:
        meta = {"brand_division": "Kohl's"}
        lines = [l.strip() for l in text.split("\n")]

        # 驗證 KOH cover (要有 "KOHL'S" / "KOHLS" / "Tech Spec Overview")
        # 2026-05-12 修: 加 KOH 線 design code 偵測 (CBRTW / BTS / FH / HY 等)
        # 案例 EIDH 311321 CBRTW26SS04 — 整 PDF 沒寫 "Kohl's", 但有 CBRTW prefix
        # 2026-05-12 加 BR 線款號偵測 — manifest 偶有把 BR PDF 誤分類到 KOH (EIDH 316362)
        upper = text.upper()
        has_koh_design_code = bool(re.search(
            r"\b(CBRTW\w{4,10}|BTS\d{2}\w{3,10}|"
            r"(?:FH|HY|HC|WC)\d{2}[A-Z]{2,4}[\w\-]+|"
            r"BRFS\w{4,12})\b",                              # BR Factory Store (BRFSFA25W-08)
            text
        ))
        # BR 線 customer/brand 標記
        has_br_marker = ("BANANA REPUBLIC" in upper or "BRFS" in upper)
        if ("KOHL'S" not in upper and "KOHLS" not in upper and
            "TECH SPEC OVERVIEW" not in upper and
            not has_koh_design_code and not has_br_marker):
            return {}

        # === Layout 3a: Makalot Sample Room — VERTICAL key/value ===
        # Signature: "Customer\nKOHLS" 兩行模式 (Makalot 內部 _ToSampleRoom_ 格式)
        # 多用於 Sonoma / C&B (Croft & Barrow) 子品牌
        if re.search(r"Customer\s*\n\s*KOHLS", text):
            return self._parse_sample_room_layout(text)

        # === Layout 3b: Makalot Sample Room — HORIZONTAL table (2026-05-12 加) ===
        # Signature: "Style No." + KOH/BR/混 design code prefix (CBRTW / BTS / BRFS 等)
        # 案例 EIDH 311321 (CBRTW26SS04 C&B RTW) / 309776 (BTS24SNS07 Sonoma)
        # 案例 EIDH 316362 (BRFSFA25W-08 Banana Republic) — manifest 誤分類到 KOH
        has_style_no = "Style No." in text or "Style NO." in text or "STYLE NO." in upper
        has_koh_code = bool(re.search(
            r"\b(CBRTW\w{4,10}|BTS\d{2}\w{3,10}|"
            r"(?:FH|HY|HC|WC)\d{2}[A-Z]{2,4}[\w\-]+|"
            r"BRFS[A-Z]{2}\d{2}[A-Z]\-?\d+|"               # BR Factory Store (BRFSFA25W-08)
            r"\d{2}SS\d{4,6}_?KOH?)\b",
            text
        ))
        has_designer_code = bool(re.search(r"\b[A-Z][a-z]+\s*#\s*\d{3,5}\b", text)) or \
                            bool(re.search(r"\b[A-Z]{2,}\s*#\s*\d{3,5}\b", text))
        if has_style_no and (has_koh_code or has_designer_code):
            sr_meta = self._parse_sample_room_horizontal_layout(text)
            if sr_meta and len(sr_meta) > 1:
                return sr_meta

        # === Layout 偵測: inline vs multi-line ===
        # Inline layout (2024+ 主流): "Brand TEKGEAR Division ACTIVE Request No. ..." 同一行
        # Multi-line layout (舊版): "Brand\nFLX\nDivision\nMENS" 每欄獨立行
        # [^\n] 確保 Brand-Division 必須同行才當 inline (否則 multi-line)
        is_inline = bool(re.search(r"Brand\s+[A-Z][^\n]+?\s+Division\s+[A-Z]", text))
        if is_inline:
            return self._parse_inline_layout(text)

        # Sub-brand (Brand 下一行) — set first for sub_brand
        # Division (gender 下一行)
        # Stage (跟在 "Stage:" 後面)
        for i, line in enumerate(lines):
            # "Brand" + "FLX" 兩行 (有時 brand 跨 2 行: "CROFT &\nBARROW")
            if line == "Brand" and i + 1 < len(lines):
                v = lines[i + 1].strip()
                # 若 value 結尾是 "&" 或 ",", 拼接下一行
                if v and (v.endswith("&") or v.endswith(",") or v.endswith(" ")):
                    if i + 2 < len(lines):
                        v2 = lines[i + 2].strip()
                        if v2 and v2 not in KOH_KEY_VALUE:
                            v = f"{v} {v2}".replace("  ", " ").strip()
                if v and v not in KOH_KEY_VALUE:
                    sub = KOH_SUBBRAND_FULL.get(v.upper(), v[:30])
                    meta["subbrand"] = sub
            elif line == "Division" and i + 1 < len(lines):
                v = lines[i + 1].strip().upper()
                if v in ("MENS", "WOMENS", "GIRLS", "BOYS", "BABY"):
                    meta["gender"] = v
            elif line == "Request No." and i + 1 < len(lines):
                v = lines[i + 1].strip()
                if re.match(r"^\d+$", v):
                    meta["request_no"] = v
            elif line.startswith("Stage:"):
                v = line.split(":", 1)[1].strip()
                if v:
                    meta["stage"] = v

        # === Same-line key: value patterns (e.g. "Product Type TOPS", "Create Date 2026-01-28") ===
        patterns_sameline = {
            "product_type": r"Product Type\s+([A-Z]+)",
            "create_date": r"Create Date\s+(\d{4}-\d{2}-\d{2})",
            "cut_date": r"Cut Date\s+([^\n]+?)(?=\s{2,}|\n|$)",
        }
        for k, pat in patterns_sameline.items():
            m = re.search(pat, text)
            if m:
                v = m.group(1).strip()
                if v and v not in ("X-", "X", "TBD"):
                    meta[k] = v[:50]

        # === Season (FA26 / SP27 等, 通常在前 10 行) ===
        for line in lines[:15]:
            sm = re.match(r"^(SP|SU|FA|HO|WI)(\d{2})$", line)
            if sm:
                meta["season"] = line
                break
        # 也可從 file metadata 抓 (fallback)
        if "season" not in meta:
            sm2 = re.search(r"\b(SP|SU|FA|HO|WI)(\d{2})\b", text[:500])
            if sm2:
                meta["season"] = f"{sm2.group(1)}{sm2.group(2)}"

        # === Design number / description ===
        # design_number 通常在 "Stage: ..." 後面, 一般 alphanumeric 像 MX6FK111 / WK1234A / WC5FK141
        # description 通常 design_number 後 1-2 行 (e.g. "DIAMOND FLEECE HOODIE", "PLEATED ROUND NECK TOP")
        # 寬鬆 pattern: [A-Z]{2}[A-Z0-9]+ (2-4 字母開頭 + 字母數字混合, 不要求純數字段)
        DN_LENIENT = re.compile(r"^[A-Z]{2,4}[A-Z0-9_\-]{3,15}$")
        for i, line in enumerate(lines):
            if line.startswith("Stage:") or "Stage:" in line:
                # 找 stage 之後第一個看似 design code 的 line
                for j in range(i + 1, min(i + 5, len(lines))):
                    candidate = lines[j].strip()
                    if DN_LENIENT.match(candidate):
                        meta["design_number"] = candidate
                        # description = next non-empty line (但跳掉 Tech Spec / KOHL 等 noise)
                        for k in range(j + 1, min(j + 4, len(lines))):
                            desc = lines[k].strip()
                            if desc and not desc.startswith("Tech Spec") and \
                               desc not in ("KOHL'S", "Brand", "Division", "Stage"):
                                meta["description"] = desc[:120]
                                break
                        break
                break

        # GT mapping from product_type
        pt = (meta.get("product_type") or "").upper()
        if pt:
            if pt in ("TOPS", "TOP", "T-SHIRT", "POLO", "BLOUSE"):
                meta["garment_type"] = "TOP"
            elif pt in ("BOTTOMS", "BOTTOM", "PANTS", "SHORTS"):
                meta["garment_type"] = "BOTTOM"
            elif pt in ("DRESSES", "DRESS"):
                meta["garment_type"] = "DRESS"
            elif pt in ("OUTERWEAR", "JACKETS"):
                meta["garment_type"] = "OUTER"

        return meta

    def _parse_inline_layout(self, text: str) -> dict:
        """KOH 2024+ 主流 layout: 所有 key+value 都在同一行 inline.

        範例 (page 1):
            FA25 WT5FA102                                       ← season + design_number
            KOHL'S Stage: COSTING SPEC USF QUARTER ZIP SWEATSHIRT ← stage + description
            Tech Spec Overview
            Brand TEKGEAR Division ACTIVE Request No. 00736704 Create Date 2024-11-04 Cut Date
            WOMENS                                               ← gender (Division 那行的續行)
            X- Product Type TOPS Product SHAWNA STUMPF Designer Tech VIRIDIANA ORNELAS

        範例 (其他 KOH sub-brand):
            HO25 MX6FK111
            KOHL'S Stage: DEVELOPMENT DIAMOND FLEECE HOODIE
            Tech Spec Overview
            Brand FLX Division MENS Request No. 00768077 Create Date 2026-01-28
        """
        meta = {"brand_division": "Kohl's"}
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # === 第 1 行: season + design_number ===
        # KOH design number 格式: 字母-數字-字母-字母-數字 (e.g. WT5FA102 / MX43K203 / MT5FA406)
        # 容納 letter + digit 混合; 用 [A-Z0-9]+ 寬鬆 match
        if lines:
            m = re.match(r"^(SP|SU|FA|HO|WI)(\d{2})\s+([A-Z][A-Z0-9_\-]{3,15})\s*$", lines[0])
            if m:
                meta["season"] = f"{m.group(1)}{m.group(2)}"
                meta["design_number"] = m.group(3)
            else:
                # Some KOH layout: design_number on its own line (season elsewhere)
                m2 = re.match(r"^([A-Z][A-Z0-9_\-]{3,15})\s*$", lines[0])
                if m2:
                    meta["design_number"] = m2.group(1)
        # Fallback: design_number 從 file/path 找(在 KOH file 名稱有 e.g. WT5FA102 ...)
        if "design_number" not in meta:
            # Try line 2 or in text body
            for line in lines[:5]:
                m = re.match(r"^([A-Z]{2,4}[A-Z0-9_]{2,12})\s*$", line)
                if m and len(m.group(1)) >= 5:
                    meta["design_number"] = m.group(1)
                    break
        # Fallback: season from anywhere in text
        if "season" not in meta:
            m = re.search(r"\b(SP|SU|FA|HO|WI)(\d{2})\b", text)
            if m:
                meta["season"] = f"{m.group(1)}{m.group(2)}"

        # === 第 2 行: "KOHL'S Stage: <STAGE> <DESCRIPTION>" ===
        for line in lines[:5]:
            sm = re.match(r"^KOHL['’]S\s+Stage:\s+([A-Z][A-Z0-9_\- ]+?)\s+([A-Z][A-Z0-9 /\-&'\(\)]+)$", line)
            if sm:
                meta["stage"] = sm.group(1).strip()
                meta["description"] = sm.group(2).strip()[:120]
                break

        # === Brand <X> Division <Y> ... 行 (inline) ===
        m = re.search(r"Brand\s+([A-Z][\w &\-]+?)\s+Division\s+([A-Z][\w ]+?)\s+(?:Request No\.|Create Date|$)", text)
        if m:
            sub_raw = m.group(1).strip().upper()
            div_raw = m.group(2).strip().upper()
            meta["subbrand"] = KOH_SUBBRAND_FULL.get(sub_raw, m.group(1).strip()[:30])
            # Division 在 inline 通常是 ACTIVE/SLEEPWEAR/RTW/SLPWR/... (不是 gender 本身)
            meta["division_raw"] = div_raw

        # === Gender: Division ACTIVE 後續行 = "WOMENS" / "MENS" / 或 same-line ===
        # 先試 inline same-line (Division MENS 直接是 gender)
        if meta.get("division_raw") in ("MENS", "WOMENS", "GIRLS", "BOYS", "BABY"):
            meta["gender"] = meta["division_raw"]
        else:
            # 找下一個只有 gender 的單行
            for line in lines:
                if line in ("WOMENS", "MENS", "GIRLS", "BOYS", "BABY"):
                    meta["gender"] = line
                    break
            # 或者 Division ACTIVE WOMENS 三個字 inline
            if "gender" not in meta:
                m2 = re.search(r"Division\s+(?:[A-Z]+\s+)?(MENS|WOMENS|GIRLS|BOYS|BABY)\b", text)
                if m2:
                    meta["gender"] = m2.group(1)

        # === Product Type TOPS / BOTTOMS / etc. (inline) ===
        m = re.search(r"Product Type\s+([A-Z][A-Z &/\-]+?)\s+(?:Product Manager|Designer|Tech|$)", text)
        if m:
            pt = m.group(1).strip()
            if pt and len(pt) < 30:
                meta["product_type"] = pt

        # === Request No. (inline) ===
        m = re.search(r"Request No\.\s+(\d+)", text)
        if m:
            meta["request_no"] = m.group(1)

        # === Create Date (inline) ===
        m = re.search(r"Create Date\s+(\d{4}-\d{2}-\d{2})", text)
        if m:
            meta["create_date"] = m.group(1)

        # === item_type 從 description / product_type 推 ===
        haystack = (meta.get("description", "") + " " + meta.get("product_type", "")).lower()
        for kw, item in [
            ("legging", "LEGGINGS"), ("jogger", "JOGGERS"), ("tight", "LEGGINGS"),
            ("short", "SHORTS"), ("pant", "PANTS"),
            ("tee", "TEE"), ("polo", "POLO"), ("hoodie", "HOODIE"),
            ("sweatshirt", "SWEATSHIRT"), ("pullover", "PULLOVER"),
            ("jacket", "JACKET"), ("vest", "VEST"),
            ("dress", "DRESS"), ("skirt", "SKIRT"), ("bra", "BRA"),
            ("swim", "SWIM"), ("sleep", "SLEEPWEAR"),
            ("tops", "TOP"), ("bottoms", "BOTTOM"),
        ]:
            if kw in haystack:
                meta["item_type"] = item
                break

        # === GT 映射 ===
        pt_upper = (meta.get("product_type") or "").upper()
        if pt_upper:
            if pt_upper in ("TOPS", "TOP", "T-SHIRT", "POLO", "BLOUSE", "SHIRTS"):
                meta["garment_type"] = "TOP"
            elif pt_upper in ("BOTTOMS", "BOTTOM", "PANTS", "SHORTS", "LEGGINGS"):
                meta["garment_type"] = "BOTTOM"
            elif pt_upper in ("DRESSES", "DRESS"):
                meta["garment_type"] = "DRESS"
            elif pt_upper in ("OUTERWEAR", "JACKETS"):
                meta["garment_type"] = "OUTER"

        # === fabric 從 division_raw 推 (ACTIVE → KNIT 常見, RTW → mixed) ===
        # 不強推, 留給後續 pipeline

        # Strip empty
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}

        return meta

    def _parse_sample_room_horizontal_layout(self, text: str) -> dict:
        """KOH Makalot Sample Room — 橫式表格 layout (2026-05-12 加).

        跟 vertical _parse_sample_room_layout 的差異: 橫式表格的 key+value 不是
        line-by-line 對應, 而是 row1=headers / row2=values flatten 在 text stream.

        Layout 範例 (EIDH 311321 CBRTW26SS04 C&B RTW):
          "Style No. | Size. | Customer | Reference Style No. | Brand | Inch | ... |
           Designer | Date | Page | 1-1 | 領深 | 褲長 | C&B RTW | Rebecca#3863 |
           | M | CBRTW26SS04 | 25" | ..."

        Layout 範例 (EIDH 309776 BTS24SNS07 Sonoma BTS):
          "主布 | 配布 | 副料 | Style NO. | Customer | Size | Brand | 部位 | ... |
           ALISON#3827 | BTS24SNS07 | Sonoma | Medium(10) | Kohl's"

        策略: 多 anchor regex 平行抽取 (不依賴 column 順序).
        """
        meta = {"brand_division": "Kohl's"}

        # === 1. design_number (KOH/BR 內部 style code 樣態) ===
        m = re.search(
            r"\b("
            r"CBRTW\w{4,10}|"               # C&B RTW (Croft & Barrow Ready-to-Wear)
            r"BTS\d{2}\w{3,10}|"            # Back-to-school
            r"BTH\w+|"                       # Bath
            r"BRFS[A-Z]{2}\d{2}[A-Z]\-?\d+|" # BR Factory Store (BRFSFA25W-08) — 2026-05-12 加
            r"(?:FH|HY|HC|WC|FA|SP|SS|SU|HO|WI)\d{2}[A-Z]{2,4}[\w\-]+|"  # season-prefixed
            r"\d{2}SS\d{4,6}_?KOH?"         # 26SS00495_KOH variant
            r")\b",
            text
        )
        if m:
            meta["design_number"] = m.group(1)

        # === 2. subbrand (KOH/BR 子品牌, 從文字直接抓) ===
        # 注意: 如果文字含 "BANANA REPUBLIC", brand_division 改成 BR
        if "BANANA REPUBLIC" in text.upper() or "BRFS" in text.upper():
            meta["brand_division"] = "Banana Republic"
            meta["subbrand"] = "BRFS"
        else:
            KOH_SUBBRAND_KW = [
                "C&B RTW", "C&B", "Croft & Barrow",
                "Sonoma Goods For Life", "Sonoma Goods", "Sonoma",
                "Tek Gear", "FLX",
                "Apt. 9", "Apt 9",
                "LC Lauren Conrad", "Lauren Conrad",
                "Simply Vera Vera Wang", "Vera Wang",
                "SO", "Madden NYC", "Mudd",
            ]
            for brand in KOH_SUBBRAND_KW:
                if brand in text:
                    # 同義詞 normalize
                    if brand in ("C&B", "C&B RTW"):
                        meta["subbrand"] = "Croft & Barrow"
                    elif brand == "Apt 9":
                        meta["subbrand"] = "Apt. 9"
                    elif brand == "Sonoma Goods":
                        meta["subbrand"] = "Sonoma Goods For Life"
                    else:
                        meta["subbrand"] = brand
                    break

        # === 3. designer (聚陽內部編號 e.g. "Rebecca#3863" / "ALISON#3827") ===
        m = re.search(r"\b([A-Z][a-zA-Z]+)\s*#\s*(\d{3,5})\b", text)
        if m:
            meta["designer"] = f"{m.group(1)} #{m.group(2)}"
        elif (m := re.search(r"\b([A-Z]{2,})\s*#\s*(\d{3,5})\b", text)):
            meta["designer"] = f"{m.group(1)} #{m.group(2)}"

        # === 4. customer (預期 Kohl's, 但確認) ===
        if "Kohl's" in text or "KOHL'S" in text or "KOHLS" in text:
            meta["customer"] = "Kohl's"

        # === 5. season 從 design_number 推 ===
        dn = meta.get("design_number", "")
        if dn:
            # CBRTW26SS04 → 26SS = 2026 Spring/Summer
            m = re.search(r"(\d{2})(SS|SP|FA|FW|HO|SU|HC|WC|FH|HY|BTS)", dn)
            if m:
                sn_map = {"SS": "SP", "SP": "SP", "SU": "SU", "FA": "FA", "FW": "FA",
                          "HO": "HO", "HC": "HO", "WC": "WI", "FH": "FA", "HY": "HO",
                          "BTS": "FA"}  # BTS = back-to-school = FA
                meta["season"] = f"{sn_map.get(m.group(2), m.group(2))}{m.group(1)}"
            else:
                m2 = re.match(r"^([A-Z]{2,3})(\d{2})", dn)
                if m2:
                    prefix = m2.group(1)
                    yr = m2.group(2)
                    season_prefix = {
                        "FH": "FA", "HY": "HO", "BTS": "FA",
                        "SP": "SP", "SU": "SU", "FA": "FA", "HO": "HO", "WI": "WI",
                        "SS": "SP",
                    }.get(prefix)
                    if season_prefix:
                        meta["season"] = f"{season_prefix}{yr}"

        # === 6. size (e.g. "M", "Medium(10)", "L") ===
        m = re.search(r"\b(Medium|Small|Large|XS|XXS|XL|XXL|XXXL)\s*\(?(\d+)?\)?\b", text)
        if m:
            size = m.group(1)
            if m.group(2):
                size = f"{size}({m.group(2)})"
            meta["size_raw"] = size

        # === 7. gender 從 subbrand / size / text 推 (不從 design_number prefix 猜) ===
        # 注意: BTS prefix 不一定是 Back-to-school KIDS, 可能只是某產品線命名
        #       例: 309776 BTS24SNS07 Sonoma Medium(10) 實際是 WOMENS 平織襯衫
        # 比較可靠的 gender 訊號順序:
        #   1. text 明寫 Mens/Womens/Boys/Girls
        #   2. size 樣態 (Medium(10) = 女生 size, 6-16 也是女生; XS-XXL 不分; 4-10 兒童)
        #   3. subbrand 強訊號 (LC Lauren Conrad / Apt 9 / Vera Wang / Auden 都是女裝)
        #   4. Tek Gear / FLX → UNISEX (Active 線通常不分性別)
        sub = (meta.get("subbrand") or "").upper()
        size = meta.get("size_raw", "")

        # 1. text 明寫 gender (最強訊號)
        if "Mens" in text or "Men's" in text:
            meta["gender_inferred"] = "MENS"
        elif "Womens" in text or "Women's" in text:
            meta["gender_inferred"] = "WOMENS"
        elif "Boys" in text:
            meta["gender_inferred"] = "BOYS"
        elif "Girls" in text:
            meta["gender_inferred"] = "GIRLS"
        # 2. subbrand 強訊號 (純女裝 brand)
        elif sub in ("LC LAUREN CONRAD", "LAUREN CONRAD", "APT. 9", "APT 9",
                     "SIMPLY VERA VERA WANG", "VERA WANG", "AUDEN"):
            meta["gender_inferred"] = "WOMENS"
        # 3. RTW (Ready-to-Wear) 通常 WOMENS
        elif "RTW" in dn:
            meta["gender_inferred"] = "WOMENS"
        # 4. C&B (Croft & Barrow) 主要 WOMENS 但也有 mens, 不強推 — 改用 size 判斷
        # 5. Active 線
        elif sub in ("TEK GEAR", "FLX"):
            meta["gender_inferred"] = "UNISEX"
        # 6. Size 推 gender (Medium(10) / 6-16 = WOMENS)
        elif re.search(r"\b(Medium|Small|Large|XS|XL|XXL)\s*\(\d+\)", size):
            # "Medium(10)" 樣態 = 女裝 size
            meta["gender_inferred"] = "WOMENS"
        # Sonoma / C&B 等廣域 brand 在 design_number prefix 看不出 gender → 留空,
        # 讓下游從 description / item_type 推

        # === 8. category — KOH RTW = Ready-to-Wear (女裝), BTS = back-to-school 等 ===
        if "RTW" in dn:
            meta["category_raw"] = "Ready-to-Wear"
        elif "BTS" in dn:
            meta["category_raw"] = "Back-to-school"

        return meta

    def _parse_sample_room_layout(self, text: str) -> dict:
        """KOH Makalot Sample Room spec sheet (vertical key/value layout).

        Filename pattern: *_ToSampleRoom_*.pdf
        Sub-brands: Sonoma / C&B (Croft & Barrow) / 等

        Layout:
            Print: <timestamp>
            Style No
            <design_number>           ← e.g. FH25SNSL004_Rev1
            Dummy
            Missy / Plus / ...        ← body type
            Size
            M / L / S / ...
            Designer
            Sales
            Page
            Customer
            KOHLS
            Brand
            Sonoma / C&B / FLX        ← subbrand
            Category
            Women / Men / Girls / Boys ← gender
            ...
            Construction Detail
            <方法描述>
        """
        meta = {"brand_division": "Kohl's"}
        lines = [l.strip() for l in text.split("\n")]

        # Vertical key→value mapping (key on line N, value on line N+1)
        VKV = {
            "Style No": "design_number",
            "Brand": "subbrand_raw",
            "Category": "gender_raw",
            "Size": "size_raw",
            "Dummy": "body_type_raw",
            "Ref Style": "ref_style",
        }
        for i, line in enumerate(lines):
            if line in VKV:
                # Take next non-empty line as value
                for j in range(i + 1, min(i + 4, len(lines))):
                    v = lines[j].strip()
                    if not v: continue
                    # Skip if value is another key
                    if v in VKV: break
                    meta[VKV[line]] = v[:100]
                    break

        # Normalize subbrand
        sub_raw = (meta.get("subbrand_raw") or "").upper().strip()
        if sub_raw:
            full = KOH_SUBBRAND_FULL.get(sub_raw, meta["subbrand_raw"][:30])
            # 部分 C&B 寫法
            if sub_raw in ("C&B", "CB", "C & B"):
                full = "Croft & Barrow"
            meta["subbrand"] = full

        # Normalize gender (Category: Women/Men/Girls/Boys/Kids)
        g_raw = (meta.get("gender_raw") or "").lower()
        gender_map = {
            "women": "WOMENS", "womens": "WOMENS", "women's": "WOMENS",
            "men": "MENS", "mens": "MENS", "men's": "MENS",
            "girls": "GIRLS", "girl": "GIRLS",
            "boys": "BOYS", "boy": "BOYS",
            "kids": "KIDS", "child": "KIDS", "children": "KIDS",
            "baby": "BABY/TODDLER", "toddler": "BABY/TODDLER",
            "unisex": "UNISEX",
        }
        if g_raw in gender_map:
            meta["gender"] = gender_map[g_raw]

        # Season from design_number prefix (FH25SNSL004 → FA25, HY25CB-RB07 → HO25, SP26... )
        dn = meta.get("design_number", "")
        if dn:
            m = re.match(r"^([A-Z]{2})(\d{2})", dn)
            if m:
                prefix = m.group(1)
                yr = m.group(2)
                season_prefix = {
                    "FH": "FA",  # FH = Fall/Holiday in KOH
                    "HY": "HO",  # HY = Holiday
                    "SP": "SP", "SU": "SU", "FA": "FA", "HO": "HO", "WI": "WI",
                }.get(prefix)
                if season_prefix:
                    meta["season"] = f"{season_prefix}{yr}"
                else:
                    # FH/HY/SS/etc. — guess from common KOH codes
                    meta["season_raw"] = f"{prefix}{yr}"

        # Description: 從 "Construction Detail" 區段第一行 / 或 Ref Style 行
        # 或從 design_number suffix 推 (SNSL=Sleepwear Set Long Sleeve, CB-GN=C&B Gown, CB-RB=Robe)
        # 簡單版: 用 design_number 拼描述
        if dn:
            meta["description"] = dn

        # Item type from suffix patterns (Makalot internal naming)
        dn_upper = dn.upper()
        ITEM_HINTS = [
            ("SNSL", "SLEEPWEAR"),  # SleepWear Set Long Sleeve
            ("SNS", "SLEEPWEAR"),
            ("PJ", "SLEEPWEAR"),
            ("GN", "GOWN"),
            ("RB", "ROBE"),
            ("DT", "DRESS"),  # 不一定，可能是 dual top
            ("PANT", "PANTS"),
            ("PT", "PANTS"),
            ("LEG", "LEGGINGS"),
            ("SHRT", "SHORTS"),
            ("TOP", "TOP"),
            ("TEE", "TEE"),
            ("HOOD", "HOODIE"),
        ]
        for kw, item in ITEM_HINTS:
            if kw in dn_upper:
                meta["item_type"] = item
                break
        if "item_type" not in meta:
            # Fallback: scan body construction detail for keywords
            body = text.lower()
            for kw, item in [
                ("legging", "LEGGINGS"), ("jogger", "JOGGERS"),
                ("dress", "DRESS"), ("gown", "GOWN"),
                ("robe", "ROBE"), ("pant", "PANTS"),
                ("short", "SHORTS"), ("pajama", "SLEEPWEAR"),
                ("sleep", "SLEEPWEAR"),
                ("褲", "PANTS"), ("睡衣", "SLEEPWEAR"),
                ("洋裝", "DRESS"), ("裙", "SKIRT"),
            ]:
                if kw in body:
                    meta["item_type"] = item
                    break

        # Strip empty
        meta = {k: v for k, v in meta.items()
                if v and str(v).lower() not in ("none", "tbd", "n/a", "---", "")}
        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]
