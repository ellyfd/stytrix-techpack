"""client_parsers/target.py — Target (Auden / Goodfellow / Wild Fable / All in Motion / ...) Techpack parser.

TGT PDF cover 格式:
  OVERVIEW <description>           ← title (含 description)
  Makalot
  Copyright 2020 Target Corporation...
  Generated on April 17,2026 10:09 AM by Daisy Kuo
  © 2026 Target Brands Inc.
  <description repeat>
  Product Attributes
  Product ID                      ← key
  PID-E7KM1E                      ← value
  Status
  PROTOTYPE
  Brand
  Auden                            ← sub-brand
  Department
  20:SLEEPWEAR                     ← dept (number:name)
  Division
  1:INT/HOS/SLEEP                  ← division (number:name)
  Class
  Primary Material
  Cloud Knit                       ← fabric
  Secondary Material
  Vendor Style Number

Sub-brands (TGT 自有品牌):
  Auden / Goodfellow & Co / A New Day / Wild Fable / Universal Thread /
  All in Motion / Cat & Jack / Boots & Barkley / Shade & Shore / Knox Rose / ...
"""
from __future__ import annotations
import re
from typing import Optional

from ._base import ClientParser


# Key → schema field. value 是 next-line.
TGT_KEY_VALUE = {
    "Product ID": "product_id",
    "Status": "status",
    "Brand": "subbrand",
    "Department": "department_raw",
    "Division": "division_raw",
    "Class": "class_raw",
    "Primary Material": "primary_material",
    "Secondary Material": "secondary_material",
    "Vendor Style Number": "vendor_style",
}


# Department code 對應 (常用)
DEPT_NUM_TO_GT = {
    "20": "SLEEPWEAR_GROUP",
    "21": "TOPS",
    "22": "BOTTOMS",
    "23": "DRESS",
    "24": "OUTER",
    "25": "ACTIVE",
}


class TargetParser(ClientParser):
    def parse_cover(self, page, text: str) -> dict:
        meta = {"brand_division": "Target"}
        lines = [l.strip() for l in text.split("\n")]
        upper = text.upper()

        # === Layout 偵測順序 ===
        # 1. Makalot Sample Room (AIM/Sonoma 線, 內部 spec sheet) — 含 STYLE# 或 Style No.+All in Motion
        # 2. Centric 8 Product Attributes (2-column) — 含 TARGET BRANDS / PRODUCT ATTRIBUTES
        # 3. Centric 8 old key-value (single column)

        # === Layout 1: Makalot Sample Room for Target/AIM 線 (2026-05-12 加) ===
        # 案例: 306127 / 306421 (Mens Track Jacket AIM26SSM09)
        # Markers: "Style No." + 內部 sub-brand (All in Motion / Cat & Jack / Goodfellow 等)
        #           或 "STYLE#:" + 內部 design code (AIM/SON 線)
        # Detection: 有 Style 標記, 並且 (subbrand 文字 OR Target 線 design code prefix)
        has_style_marker = ("Style No." in text or "STYLE#" in upper or "STYLE NO." in upper)
        has_subbrand_kw = any(b.upper() in upper for b in [
            "All in Motion", "Cat & Jack", "Goodfellow", "Universal Thread",
            "A New Day", "Wild Fable", "Auden", "Knox Rose", "Joylab",
            "Shade & Shore", "Ava & Viv", "Original Use",
        ])
        # Target 線 design code 前綴 (沒寫出 brand name 但 style code 露出來)
        # AIM = All in Motion, SON = Sonoma, CJ = Cat & Jack, UTH = Universal Thread
        # MST = MSTAR (Target 子供應商), C##MKCJ = C&J Cat & Jack 兒童線
        # 注意: 抓的是樣式碼前綴, 不是隨機英文字
        has_target_code = bool(re.search(
            r"\b(AIM[\w\-]{3,15}|SON[\w\-]{3,15}|UTH[\w\-]{3,15}|TGT[\w\-]{3,15}|GFL[\w\-]{3,15}|"
            r"MST\d{2}[\w\-]{3,12}|"                          # MSTAR 線 (e.g. MST25AW009)
            r"C\d{3}MKCJ\w*|C\d{3}MK\w+|"                 # C&J Cat & Jack 兒童 (e.g. C126MKCJ006)
            r"CJ\d\w+)\b",                                 # 舊 CJ\d 樣態 (保留)
            text
        ))
        # C&J 縮寫也算 subbrand 訊號 (Target Cat & Jack 線)
        has_cj_marker = bool(re.search(r"\bC&J\b|MSTAR", text))
        is_makalot_sr = has_style_marker and (has_subbrand_kw or has_target_code or has_cj_marker)
        if is_makalot_sr:
            sr_meta = self._parse_makalot_sample_room_layout(text)
            if sr_meta and len(sr_meta) > 1:
                return sr_meta

        # === Layout 1b: 聚陽 Quotation 報價單 (Sample Making Request Form) ===
        # 案例: 310137 (L056XG) / 310267 (54Z5X1) / 310179/310421 (X0MGKX_C425) / 310872 (L056XG)
        # Layout: 兩排 keys 後跟兩排 values
        #   Stage: / Style: / Customer: / P'Cate: / MR:
        #   Quotation / L056XG / TARGET(TSS) / Women 婦女 / Ruo Chen 陳若華
        #   Country: / Order Qty(DZ): / Subgroup: / Product Item: / Follower:
        #   Indonesia / 7870.25 / D214 / Dressy Pants - Bottom / Effie Chan
        is_quotation = (
            "TARGET(TSS)" in text or "TARGET(" in text
        ) and "P'Cate:" in text and "Stage:" in text
        if is_quotation:
            q_meta = self._parse_quotation_layout(text)
            if q_meta and len(q_meta) > 1:
                return q_meta

        # === Layout 2/3: Centric 8 (需要 TARGET BRANDS 等 markers) ===
        if "TARGET BRANDS" not in upper and "TARGET CORPORATION" not in upper and "PRODUCT ATTRIBUTES" not in upper:
            return {}

        # === Layout 2 偵測: 2-column inline ===
        # 2-column (PID-* 新版): "Brand Department\nCat & Jack 75:KIDS SLPWR" 兩個 key 同一行
        # Old: "Brand\nCat & Jack\nDepartment\n75:KIDS"
        is_2col = bool(re.search(r"Brand\s+Department\s*\n", text) or re.search(r"Division\s+Class\s*\n", text))
        if is_2col:
            inline_meta = self._parse_2col_layout(text)
            if inline_meta:
                return inline_meta
        # Fall through to old key-value parser

        # === Key-Value 兩行 pattern ===
        for i, line in enumerate(lines):
            if line in TGT_KEY_VALUE:
                key_en = TGT_KEY_VALUE[line]
                for j in range(i + 1, min(i + 4, len(lines))):
                    v = lines[j].strip()
                    if not v:
                        continue
                    if v in TGT_KEY_VALUE:
                        break  # 下個 key, 此 value 空
                    meta[key_en] = v[:120]
                    break

        # === Description ===
        # OVERVIEW <desc> 在 line 1, 或 desc 在 line ~5-10 (legal text 之後 repeat)
        if lines and lines[0].startswith("OVERVIEW "):
            meta["description"] = lines[0][len("OVERVIEW "):].strip()[:120]

        # === Generated 日期 (cover 識別) ===
        gen_m = re.search(r"Generated on (\w+ \d+,\d{4})", text)
        if gen_m:
            meta["generated_on"] = gen_m.group(1)

        # === Parse Department "20:SLEEPWEAR" → number + name ===
        dr = meta.get("department_raw", "")
        if dr and ":" in dr:
            num, name = dr.split(":", 1)
            meta["department_num"] = num.strip()
            meta["department"] = name.strip()
        else:
            meta["department"] = dr

        # === Parse Division "1:INT/HOS/SLEEP" → number + name ===
        dv = meta.get("division_raw", "")
        if dv and ":" in dv:
            num, name = dv.split(":", 1)
            meta["division_num"] = num.strip()
            meta["division"] = name.strip()
        else:
            meta["division"] = dv

        # === design_number = product_id (TGT 用 Product ID 當 PK) ===
        if "product_id" in meta:
            meta["design_number"] = meta["product_id"]

        # === gender 從 sub-brand (some have implicit gender) ===
        sub = (meta.get("subbrand") or "").upper()
        if sub in ("AUDEN",):
            meta["gender_inferred"] = "WOMENS"  # Auden 是 sleepwear womens
        elif sub == "GOODFELLOW & CO" or sub == "GOODFELLOW":
            meta["gender_inferred"] = "MENS"
        elif sub in ("A NEW DAY", "WILD FABLE", "KNOX ROSE", "SHADE & SHORE", "AVA & VIV"):
            meta["gender_inferred"] = "WOMENS"
        elif sub == "CAT & JACK":
            meta["gender_inferred"] = "KIDS"

        # === Department → garment_type hint ===
        dept_num = meta.get("department_num", "")
        if dept_num in DEPT_NUM_TO_GT:
            meta["garment_type_hint"] = DEPT_NUM_TO_GT[dept_num]

        return meta

    # ════════════════════════════════════════════════════════════
    # _parse_makalot_sample_room_layout — TGT Makalot 內部 spec sheet (2026-05-12 加)
    # ════════════════════════════════════════════════════════════
    # 適用 AIM (All in Motion) / Cat & Jack / Goodfellow / etc. 線
    # Layout: 表格式 PDF, text 抽出後欄位用 | 或 \n 分隔
    # 範例 (EIDH 306421, Mens Track Jacket AIM26SSM09):
    #   "Style No. | Size. | Style Name | Reference Style No. | Brand | Inch | Y | N |
    #    Prototype | Catogory | Mesurement | Designer | Date | Page |
    #    Eric #3866 | 1-1 | Mens Track Jacket | AIM26SSM09 | All in Motion | M | A-主布..."
    # ════════════════════════════════════════════════════════════
    def _parse_makalot_sample_room_layout(self, text: str) -> dict:
        """TGT Makalot 內部 spec sheet (AIM/Sonoma/Cat & Jack 線).

        page_classifier 已對 cover_kw_hits (STYLE NO + STYLE NAME + REFERENCE STYLE +
        ALL IN MOTION) 命中 ≥3 路由到 parse_cover. 本 method 接住抽取欄位.

        策略: 多 anchor regex 平行抽取 (避免依賴 column 順序), 各欄位獨立確認.

        抽取欄位:
          - design_number / product_id: Style code (AIMXXX / SONXXX 等)
          - description / style_name: "Mens Track Jacket" 等
          - subbrand: All in Motion / Cat & Jack / Goodfellow 等 (TGT 子品牌)
          - designer: "Eric #3866" 等內部編號
          - season_raw + season: 從 style code 推 (AIM26SSM = SP26 SS = Spring Summer)
          - gender / gender_inferred: 從 style_name / subbrand 推
          - item_type: 從 style_name 推
        """
        meta = {"brand_division": "Target"}

        # === 1. design_number (Style No.) ===
        # Makalot 各 Target 線款號慣例:
        #   AIM26SSM09 / AIMSS26W005 - All in Motion
        #   SONFW25K12 - Sonoma (KOH)
        #   MST25AW009 - MSTAR (Target 子供應商, women's)
        #   C126MKCJ006 / C425MKCJ002-top - C&J Cat & Jack 兒童
        #   TGT26FAB03 - generic Target
        m = re.search(
            r"\b(AIM[\w\-]{3,15}|SON[\w\-]{3,15}|TGT[\w\-]{3,15}|UTH[\w\-]{3,15}|GFL[\w\-]{3,15}|"
            r"MST\d{2}[\w\-]{3,12}|"
            r"C\d{3}MKCJ\w*|C\d{3}MK\w+)\b",
            text
        )
        if m:
            meta["design_number"] = m.group(1)
            meta["product_id"] = m.group(1)

        # === 2. subbrand (Target 子品牌, 從文字直接抓) ===
        SUBBRAND_KW = [
            "All in Motion", "Cat & Jack", "Goodfellow & Co", "Goodfellow",
            "Universal Thread", "A New Day", "Wild Fable", "Auden",
            "Knox Rose", "JoyLab", "Shade & Shore", "Ava & Viv", "Original Use",
        ]
        for brand in SUBBRAND_KW:
            if brand in text:
                meta["subbrand"] = brand
                break
        # 縮寫 fallback: C&J → Cat & Jack, MSTAR → MSTAR
        if "subbrand" not in meta:
            if re.search(r"\bC&J\b", text):
                meta["subbrand"] = "Cat & Jack"
            elif "MSTAR" in text:
                meta["subbrand"] = "MSTAR"

        # === 3. designer (內部編號 e.g. "Eric #3866") ===
        m = re.search(r"\b([A-Z][a-z]+)\s*#(\d{3,5})\b", text)
        if m:
            meta["designer"] = f"{m.group(1)} #{m.group(2)}"

        # === 4. style_name (description) ===
        # Style Name 通常是 "Mens/Womens/Boys/Girls/Kids XX YY" 的 garment 名稱
        # 用 gender keyword 找 style_name 的開頭
        for g_kw in ["Mens ", "Men's ", "Womens ", "Women's ", "Ladies ",
                     "Boys ", "Girls ", "Kids ", "Toddler ", "Baby "]:
            if g_kw in text:
                # 抓 "Mens Track Jacket" 這種 garment 名稱直到下個 | 或 \n
                m = re.search(rf"({re.escape(g_kw)}[\w\s]+?)(?=\s*[|\n]|\s+(?:AIM|SON|TGT|UTH|GFL)\w+)", text)
                if m:
                    sn = m.group(1).strip()
                    # Sanity: 太長 (>60 chars) 可能誤抓
                    if 3 <= len(sn) <= 60:
                        meta["style_name"] = sn
                        meta["description"] = sn
                break

        # === 5. gender ===
        # 從 style_name / subbrand 推
        sn_upper = meta.get("style_name", "").upper()
        sub_upper = meta.get("subbrand", "").upper()
        haystack = sn_upper + " " + sub_upper
        if "MENS" in haystack or "MEN'S" in haystack:
            meta["gender"] = "MENS"
        elif "WOMENS" in haystack or "WOMEN'S" in haystack or "LADIES" in haystack:
            meta["gender"] = "WOMENS"
        elif "BOYS" in haystack:
            meta["gender"] = "BOYS"
        elif "GIRLS" in haystack:
            meta["gender"] = "GIRLS"
        elif "KIDS" in haystack or "TODDLER" in haystack or "BABY" in haystack:
            meta["gender_inferred"] = "KIDS"
        elif sub_upper == "CAT & JACK":
            meta["gender_inferred"] = "KIDS"  # Cat & Jack 是兒童線
        elif sub_upper == "AUDEN":
            meta["gender_inferred"] = "WOMENS"  # Auden 是 sleepwear womens
        elif sub_upper in ("GOODFELLOW", "GOODFELLOW & CO"):
            meta["gender_inferred"] = "MENS"
        elif sub_upper in ("A NEW DAY", "WILD FABLE", "KNOX ROSE", "SHADE & SHORE",
                            "AVA & VIV", "JOYLAB", "UNIVERSAL THREAD"):
            meta["gender_inferred"] = "WOMENS"

        # === 6. season 從 style_code 推 ===
        # AIM 線命名: AIM<YY><season><gender><seq>
        # 例: AIM26SSM09 = 2026 SS Mens 09 (Spring/Summer)
        # 例: AIMSS26W005 = SS 2026 Womens (alt 格式)
        # 例: SONFW25K = Fall/Winter 2025 Kids
        dn = meta.get("design_number", "")
        m = re.search(r"(SS|SP|FA|FW|HO|SU)\s*(\d{2})", dn)
        if m:
            sn_map = {"SS": "SP", "SP": "SP", "SU": "SU", "FA": "FA", "FW": "FA", "HO": "HO"}
            meta["season"] = f"{sn_map.get(m.group(1), m.group(1))}{m.group(2)}"
            meta["season_raw"] = m.group(0)
        else:
            # Try YYabbr pattern (e.g. AIM26... → 26 = year)
            m = re.search(r"(?:AIM|SON|TGT)(\d{2})", dn)
            if m:
                meta["season_raw"] = f"20{m.group(1)}"

        # === 7. item_type 從 style_name ===
        sn_lower = meta.get("style_name", "").lower()
        for kw, item in [
            ("legging", "LEGGINGS"), ("jogger", "JOGGERS"), ("tight", "LEGGINGS"),
            ("short", "SHORTS"), ("pant", "PANTS"), ("trouser", "PANTS"),
            ("tee", "TEE"), ("polo", "POLO"), ("hoodie", "HOODIE"),
            ("sweatshirt", "SWEATSHIRT"), ("pullover", "PULLOVER"),
            ("track jacket", "JACKET"), ("jacket", "JACKET"),
            ("dress", "DRESS"), ("skirt", "SKIRT"), ("bra", "BRA"),
            ("swim", "SWIM"), ("pajama", "SLEEPWEAR"), ("sleep", "SLEEPWEAR"),
            ("romper", "ROMPER"), ("jumpsuit", "JUMPSUIT"),
            ("top", "TOP"), ("bottom", "BOTTOM"),
        ]:
            if kw in sn_lower:
                meta["item_type"] = item
                break

        return meta

    # ════════════════════════════════════════════════════════════
    # _parse_quotation_layout — 聚陽 Quotation 報價單 (Sample Making Request)
    # ════════════════════════════════════════════════════════════
    # 適用 Target 各線 (TSS / TSI / Activewear) 的內部報價/打樣請求文件
    # Layout: 雙列 keys + values 各列獨立行
    #   Stage: → Quotation/Order/etc
    #   Style: → L056XG (內部款號)
    #   Customer: → TARGET(TSS)
    #   P'Cate: → Women 婦女 / Girl 女童 / Boy 男童 / Men 男裝
    #   MR: → Designer 中英名 (e.g. Ruo Chen 陳若華)
    #   Country: → Indonesia / Vietnam / 等
    #   Order Qty(DZ): → 數字
    #   Subgroup: → D214 / D39 (Target Department code)
    #   Product Item: → "Dressy Pants - Bottom" 等
    #   Follower: → Sales 中英名
    # ════════════════════════════════════════════════════════════
    def _parse_quotation_layout(self, text: str) -> dict:
        """聚陽報價單 Layout (Sample Making Request).

        雙列 key-value 表格, key 列在前, value 列在後 (同一個 group 5 keys → 5 values).
        """
        meta = {"brand_division": "Target"}
        lines = [l.strip() for l in text.split("\n")]

        # === Group 1: Stage / Style / Customer / P'Cate / MR ===
        KEYS_1 = ["Stage:", "Style:", "Customer:", "P'Cate:", "MR:"]
        for i, line in enumerate(lines):
            if line == "Stage:" and lines[i:i + 5] == KEYS_1:
                # Values 在 i+5 之後 5 行
                vals = lines[i + 5:i + 10]
                if len(vals) == 5:
                    stage, style, customer, pcate, mr = vals
                    if stage and stage not in KEYS_1:
                        meta["stage"] = stage[:30]
                    if style and not style.startswith(":"):
                        meta["design_number"] = style[:30]
                        meta["product_id"] = style[:30]
                    if customer:
                        meta["customer"] = customer[:30]
                        # TARGET(TSS) → subbrand
                        sub_m = re.match(r"TARGET\(([A-Z]+)\)", customer)
                        if sub_m:
                            meta["subbrand"] = f"Target {sub_m.group(1)}"
                    if pcate:
                        meta["category_raw"] = pcate[:30]
                        # Gender 從 P'Cate 推
                        if "Women" in pcate or "婦女" in pcate or "Lady" in pcate:
                            meta["gender"] = "WOMENS"
                        elif "Men" in pcate or "男裝" in pcate:
                            meta["gender"] = "MENS"
                        elif "Girl" in pcate or "女童" in pcate:
                            meta["gender"] = "GIRLS"
                        elif "Boy" in pcate or "男童" in pcate:
                            meta["gender"] = "BOYS"
                        elif "Kid" in pcate or "兒童" in pcate or "Baby" in pcate:
                            meta["gender"] = "KIDS"
                    if mr:
                        meta["mr_designer"] = mr[:50]
                break

        # === Group 2: Country / Order Qty(DZ) / Subgroup / Product Item / Follower ===
        KEYS_2 = ["Country:", "Order Qty(DZ):", "Subgroup:", "Product Item:", "Follower:"]
        for i, line in enumerate(lines):
            if line == "Country:" and lines[i:i + 5] == KEYS_2:
                vals = lines[i + 5:i + 10]
                if len(vals) == 5:
                    country, qty, subgroup, prod_item, follower = vals
                    if country:
                        meta["country"] = country[:30]
                    if qty:
                        meta["order_qty_dz"] = qty[:20]
                    if subgroup:
                        meta["subgroup_raw"] = subgroup[:30]
                        # D214 / D39 patterns
                        sg_m = re.match(r"D(\d+)", subgroup)
                        if sg_m:
                            meta["department_num"] = sg_m.group(1)
                    if prod_item:
                        meta["product_item"] = prod_item[:80]
                        meta["description"] = prod_item[:80]
                        # 推 item_type
                        pi_lower = prod_item.lower()
                        for kw, item in [
                            ("legging", "LEGGINGS"), ("jogger", "JOGGERS"),
                            ("short", "SHORTS"), ("pant", "PANTS"),
                            ("tee", "TEE"), ("hoodie", "HOODIE"),
                            ("jacket", "JACKET"), ("dress", "DRESS"),
                            ("skirt", "SKIRT"), ("top", "TOP"),
                        ]:
                            if kw in pi_lower:
                                meta["item_type"] = item
                                break
                    if follower:
                        meta["follower"] = follower[:50]
                break

        # === Additional fields 散在 text 內 ===
        # Designer/Tech Designer name
        m = re.search(r"\bP'Cate:\s*\n\s*([^\n]+)\s*\n\s*MR:", text)
        if m and "category_raw" not in meta:
            meta["category_raw"] = m.group(1).strip()[:30]

        return meta

    def _parse_2col_layout(self, text: str) -> dict:
        """TGT 2024+ Centric 8 Product Attributes layout (2 column).

        Layout 範例:
            OVERVIEW CJ BBBG GI VELOUR Tight Fit Pant Makalot
            CJ BBBG GI VELOUR Tight Fit Pant
            Product Product ID Status                                ← keys row
            Attributes PID-992E37 PRODUCTION                          ← values row (含 PID)
            Brand Department                                          ← keys
            Cat & Jack 75:KIDS SLPWR/FASHION UNDRWR/BODYWEAR          ← values
            Division Class                                            ← keys
            2:KIDS APPAREL 1:BOYS PAJAMAS                             ← values
            Primary Material Secondary Material
            ...

        2-column layout: Left column / Right column, key+value 各自配對.
        """
        meta = {"brand_division": "Target"}
        lines = [l.strip() for l in text.split("\n")]

        # === Product ID: PID-XXXXX (核心) ===
        m = re.search(r"\b(PID-[A-Z0-9]+)\b", text)
        if m:
            meta["product_id"] = m.group(1)
            meta["design_number"] = m.group(1)

        # === Description: 第 1 行 "OVERVIEW <X> Makalot" 或 line 2 (純 desc 重複) ===
        if lines and lines[0].startswith("OVERVIEW "):
            desc = lines[0][len("OVERVIEW "):].strip()
            # 拿掉尾巴 "Makalot"
            desc = re.sub(r"\s+Makalot\s*$", "", desc).strip()
            if desc:
                meta["description"] = desc[:120]

        # === 2-column row "Brand Department" → next-line values ===
        for i, line in enumerate(lines):
            if line.startswith("Brand Department") and i + 1 < len(lines):
                val_line = lines[i + 1].strip()
                # 拆 "Cat & Jack 75:KIDS SLPWR/FASHION ..." → Brand 在前, Department 在後 (Dept 以 NN:XXX 開頭)
                m = re.match(r"^(.+?)\s+(\d+:[A-Z][A-Z /&_\-]+)$", val_line)
                if m:
                    meta["subbrand"] = m.group(1).strip()
                    meta["department_raw"] = m.group(2).strip()
                else:
                    # 不確定切點時, 將整行當 subbrand fallback
                    meta["subbrand"] = val_line[:60]
                break

        # === "Division Class" → next-line values ===
        for i, line in enumerate(lines):
            if line.startswith("Division Class") and i + 1 < len(lines):
                val_line = lines[i + 1].strip()
                m = re.match(r"^(\d+:[A-Z][A-Z /&_\-]+?)\s+(\d+:[A-Z][A-Z /&_\-]+)$", val_line)
                if m:
                    meta["division_raw"] = m.group(1).strip()
                    meta["class_raw"] = m.group(2).strip()
                else:
                    # 單一值情況
                    m2 = re.match(r"^(\d+:[A-Z][A-Z /&_\-]+)$", val_line)
                    if m2:
                        meta["division_raw"] = m2.group(1).strip()
                break

        # === Status (隔行) ===
        m = re.search(r"\b(PID-[A-Z0-9]+)\s+(PROTOTYPE|PRODUCTION|DEVELOPMENT|TBD|CANCELLED|ON HOLD)\b", text)
        if m:
            meta["status"] = m.group(2)

        # === Primary Material (隔行) ===
        for i, line in enumerate(lines):
            if line.startswith("Primary Material") and i + 1 < len(lines):
                v = lines[i + 1].strip()
                # 排掉 noise (key 行) / 空 / Vendor Style Number
                if v and not v.startswith("Vendor") and not v.startswith("Secondary"):
                    meta["primary_material"] = v[:80]
                break

        # === 拆 Department/Division/Class 的 num:name ===
        for raw_key in ("department_raw", "division_raw", "class_raw"):
            if raw_key in meta and ":" in meta[raw_key]:
                num, name = meta[raw_key].split(":", 1)
                short_key = raw_key.replace("_raw", "")
                meta[f"{short_key}_num"] = num.strip()
                meta[short_key] = name.strip()

        # === Gender 推導 (Class 是 gender 來源 e.g. "1:BOYS PAJAMAS") ===
        class_raw = meta.get("class_raw", "") + " " + meta.get("class", "")
        class_upper = class_raw.upper()
        if "BOYS" in class_upper:
            meta["gender"] = "BOYS"
        elif "GIRLS" in class_upper:
            meta["gender"] = "GIRLS"
        elif "MENS" in class_upper or "MEN'S" in class_upper:
            meta["gender"] = "MENS"
        elif "WOMENS" in class_upper or "WOMEN'S" in class_upper:
            meta["gender"] = "WOMENS"
        elif "KIDS" in class_upper or "KID'S" in class_upper:
            meta["gender_inferred"] = "KIDS"
        elif "BABY" in class_upper:
            meta["gender_inferred"] = "BABY/TODDLER"

        # Gender fallback: 從 Department / Division 文字推 (含 WOMENS PERFORMANCE 等)
        if "gender" not in meta and "gender_inferred" not in meta:
            dept_text = (meta.get("department", "") + " " + meta.get("division", "") + " " + meta.get("department_raw", "")).upper()
            if "WOMENS" in dept_text or "WOMEN'S" in dept_text:
                meta["gender_inferred"] = "WOMENS"
            elif "MENS" in dept_text or "MEN'S" in dept_text:
                meta["gender_inferred"] = "MENS"
            elif "GIRLS" in dept_text:
                meta["gender_inferred"] = "GIRLS"
            elif "BOYS" in dept_text:
                meta["gender_inferred"] = "BOYS"
            elif "KIDS" in dept_text:
                meta["gender_inferred"] = "KIDS"
            elif "BABY" in dept_text or "TODDLER" in dept_text:
                meta["gender_inferred"] = "BABY/TODDLER"

        # === Sub-brand based gender (fallback if Class didn't have it) ===
        sub = (meta.get("subbrand") or "").upper()
        if "gender" not in meta and "gender_inferred" not in meta:
            if sub == "AUDEN":
                meta["gender_inferred"] = "WOMENS"
            elif sub in ("GOODFELLOW", "GOODFELLOW & CO"):
                meta["gender_inferred"] = "MENS"
            elif sub in ("A NEW DAY", "WILD FABLE", "KNOX ROSE", "SHADE & SHORE", "AVA & VIV"):
                meta["gender_inferred"] = "WOMENS"
            elif sub == "CAT & JACK":
                meta["gender_inferred"] = "KIDS"

        # === Season 從 Design Cycle (e.g. "C3 2025") 推 (TGT 用 C1-C4 = 4 季 cycle) ===
        m = re.search(r"\bC(\d)\s+(\d{4})\b", text)
        if m:
            cyc = int(m.group(1))
            yr = m.group(2)[-2:]
            cyc_season = {1: "SP", 2: "SU", 3: "FA", 4: "HO"}.get(cyc, "FA")
            meta["season"] = f"{cyc_season}{yr}"

        # === item_type 從 description / class / dept ===
        haystack = (meta.get("description", "") + " " + meta.get("class", "") + " " + meta.get("department", "")).lower()
        for kw, item in [
            ("legging", "LEGGINGS"), ("jogger", "JOGGERS"), ("tight", "LEGGINGS"),
            ("short", "SHORTS"), ("pant", "PANTS"),
            ("tee", "TEE"), ("polo", "POLO"), ("hoodie", "HOODIE"),
            ("sweatshirt", "SWEATSHIRT"), ("pullover", "PULLOVER"),
            ("jacket", "JACKET"), ("dress", "DRESS"), ("skirt", "SKIRT"), ("bra", "BRA"),
            ("swim", "SWIM"), ("pajama", "SLEEPWEAR"), ("sleep", "SLEEPWEAR"),
            ("tops", "TOP"), ("bottoms", "BOTTOM"),
        ]:
            if kw in haystack:
                meta["item_type"] = item
                break

        # === Department → garment_type hint ===
        dept_num = meta.get("department_num", "")
        if dept_num in DEPT_NUM_TO_GT:
            meta["garment_type_hint"] = DEPT_NUM_TO_GT[dept_num]

        # Strip empty
        meta = {k: v for k, v in meta.items() if v and str(v).lower() not in ("none", "tbd", "n/a", "---")}

        return meta

    def parse_construction_page(self, page, text: str) -> list[dict]:
        return [{"_raw_callout_text": text[:5000]}]
