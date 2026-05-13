"""
extract_pdf_metadata.py — 從 PDF cover page 抽業務 metadata (per-client adapter)

每客戶 PDF cover layout 不同,per-client parser:
  Centric 8 共用 (ONY/ATHLETA/GAP/GAP_OUTLET/BR): parse_centric8
  DICKS DSG: parse_dicks
  其他 (TARGET/KOHLS/A_&_F/GU/CATO): 待加 adapter

抽到的 metadata 寫到:
  outputs/platform/pdf_metadata.jsonl

schema: {client, design_id, eidh, brand_division, department, gender_pdf, season,
         category, sub_category, bom_number, vendor, status, collection, ...}

用法:python scripts/extract_pdf_metadata.py [--limit N] [--client CLIENT]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
DESIGNS_NEW = ROOT / "m7_organized_v2" / "metadata" / "designs.jsonl"  # 5/8+ new path
DESIGNS_OLD = ROOT.parent / "stytrix-pipeline-Download0504" / "data" / "ingest" / "metadata" / "designs.jsonl"
DESIGNS = DESIGNS_NEW if DESIGNS_NEW.exists() else DESIGNS_OLD

TP_SAMPLES = ROOT / "tp_samples_v2"          # 4644 EIDH 子目錄,master location
PDF_TP_FLAT = ROOT / "m7_organized_v2" / "pdf_tp"  # legacy flat dir (subset)

OUT_PATH = ROOT / "outputs" / "platform" / "pdf_metadata.jsonl"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════
# Per-client PDF metadata extractor
# ════════════════════════════════════════════════════════════

def _filter_noise(value, noise: set):
    """Filter out known noise values (eg sub_category 抓到隔壁 label)"""
    if value is None: return None
    if value.strip() in noise: return None
    # also check substring noise patterns
    for n in noise:
        if value.strip() == n: return None
    return value


def _extract_block(text, key_patterns, max_lines=2):
    """找 key 後抓接下來 1-2 行 value(避開空白行 / 標題列)

    處理:
      - Single newline between key and value (Centric 8 一行 key 一行 value)
      - ZWSP (\\u200b) 出現在 key 中
      - Trailing whitespace 在 key 後

    pat 是 key 名 (regex),自動加上 newline-or-end + value capture。
    """
    # Strip ZWSP from text before regex (Centric 8 export 有時插 ZWSP)
    text_clean = text.replace("​", "").replace("\xa0", " ")
    for pat in key_patterns:
        # pat + (whitespace or newline) + value (1-N lines, 不含下一個 label)
        # 用 \n 強制 key 在獨立行(避免 "Sub Category" 撞到 "Sub-Category")
        # max_lines=N 抓 1..N 行 value
        regex = pat + r"\s*\n+((?:[^\n]+\n?){1," + str(max_lines) + r"})"
        m = re.search(regex, text_clean)
        if m:
            v = m.group(1).strip()
            v = v.replace("​", "").strip()
            lines = [l.strip() for l in v.split("\n") if l.strip()]
            return lines[0] if lines else None
    return None


def parse_centric8(text: str) -> dict:
    """Centric 8 PLM 共用 parser (ONY / ATHLETA / GAP / GAP_OUTLET / BR)

    支援兩種 label 版本:
      - 舊版 (Centric 8 v7.4): "Design Season" / "Design Brand/Division" / "Design Department"
      - 新版 (Centric 8 v7.9+): "Season" / "Brand/Division" / "Department"

    User 確認的 mapping:
      Tech Pack 〜 報價款號 (取 D-prefix style number)
      Brand/Division → 客戶 + gender (eg "GAP - WOMENS")
      Department → gender + W/K (eg "WOMENS KNITS")
      Collection → Program (eg "OUTLET WOMENS ACTIVE/GRAPHICS")
    """
    # 注意:Centric 8 文字 dump 順序通常是:
    #   Disclaimer Text / Centric 8 / Production(...) / D-style header / timestamp /
    #   "Image" or "Design Image" / Tech Pack / <value lines> / Season / <value> / ...
    # 用「Tech Pack(?!\s*(?:BOM|Type))」避免撞到 "Tech Pack BOM Status" / "Tech Pack BOM Vendor"
    return {
        # Tech Pack 那段(value 跨 1-3 行,eg "D40583 Fitted EHR CROSS\nOVER WB LEGGING 000756541\nAdopted")
        # _extract_block 只取第一行,所以拿到 "D40583 Fitted EHR CROSS" 即可推出 D-prefix style
        "tech_pack_line": _extract_block(text, [r"Tech Pack(?!\s*(?:BOM|Type))"], max_lines=1),
        # 季 (新舊 Centric 8 都認:Design Season / Season)
        "season": _extract_block(text, [r"Design Season", r"\bSeason(?!\s*Numbers)"]),
        # 客戶 + gender (raw eg "GAP - WOMENS")
        "brand_division": _extract_block(text, [r"Design Brand/Division", r"\bBrand/Division"]),
        # gender + W/K (eg "WOMENS BOTTOMS")
        "department": _extract_block(text, [r"Design Department", r"\bDepartment(?!\s+Number)"], max_lines=2),
        # Program (eg "WOMENS WOVEN BOTTOMS")
        "collection": _extract_block(text, [r"Design Collection", r"\bCollection(?!\s+Numbers?)"], max_lines=2),
        # BOM-level metadata (注意 ATH 用 "Tech Pack BOM Category" / GAP 用 "Category")
        "category": _extract_block(text, [r"Tech Pack BOM Category", r"\bCategory(?!\s*Numbers)"]),
        # Sub-Category 抽 + 立刻過濾 noise (有時抓到下一個 label "Legacy Style Numbers")
        "sub_category": _filter_noise(
            _extract_block(text, [
                r"Tech Pack BOM Sub-\s*Category",
                r"Sub-?\s*Category",
            ]),
            noise={"Legacy Style Numbers", "Tech Pack BOM Legacy", "Style Numbers"}
        ),
        # BOM Number — 兩個來源(獨立 field + Tech Pack 那行也含 9-digit BOM)
        # ATH 用 "Tech Pack BOM BOM\nNumber\n<value>" / GAP/ONY 用 "BOM Number\n<value>"
        "bom_number": _extract_block(text, [
            r"Tech Pack BOM BOM\s*Number",
            r"\bBOM Number",
        ]),
        "status": _extract_block(text, [r"Tech Pack BOM Status", r"\bStatus(?!\s*Numbers)"]),
        "flow": _extract_block(text, [r"Tech Pack BOM Flow", r"\bFlow(?!\s*Numbers)"]),
        "vendor": _extract_block(text, [r"Tech Pack BOM Vendor", r"\bVendor"]),
        "design_bom": _extract_block(text, [r"\bDesign BOM"]),
    }


def derive_centric8_canonical(meta: dict) -> dict:
    """從 raw Centric 8 metadata derive 出聚陽 canonical 欄位

    Tech Pack: "D3909 Classic HERITAGE JOGGER 000627356 Adopted"
      → 報價款號 = "D3909" (D-prefix 前綴 = 聚陽 canonical 客戶款號)
    Brand/Division: "GAP - WOMENS" → 客戶="GAP", gender="WOMENS"
    Department: "WOMENS KNITS" → gender="WOMENS", W/K="KNITS"
    """
    out = dict(meta)

    # 1. Tech Pack 那行 = "<D-style> <description> <bom_9digit> <status>"
    #    eg "D3909 Classic HERITAGE JOGGER 000627356 Adopted"
    tp = meta.get("tech_pack_line", "") or ""
    # 1a. style_no (D-prefix 或 6-7 位純數字)
    m = re.match(r"^(D\d{3,6}|\d{6,7})\b", tp)
    if m:
        out["報價款號"] = m.group(1)
        out["style_no_from_tech_pack"] = m.group(1)
    # 1b. BOM number (Tech Pack 那行裡的 9-digit number)— fallback if 獨立 BOM Number field 沒抓到
    m_bom = re.search(r"\b(\d{9})\b", tp)
    if m_bom:
        out["bom_number_from_tech_pack"] = m_bom.group(1)
        if not meta.get("bom_number"):
            out["bom_number"] = m_bom.group(1)

    # 2. Brand/Division → split 客戶 / gender
    bd = (meta.get("brand_division") or "").strip()
    if " - " in bd:
        parts = [p.strip() for p in bd.split(" - ", 1)]
        out["client_pdf_brand"] = parts[0]
        out["gender_from_brand_division"] = parts[1]
        out["客戶"] = parts[0]  # canonical key (eg "OLD NAVY", "GAP", "ATHLETA", "BANANA REPUBLIC", "BRFS")
    elif bd:
        out["client_pdf_brand"] = bd
        out["客戶"] = bd

    # 2b. Season canonical alias
    if meta.get("season"):
        out["Season"] = meta["season"]  # eg "Fall 2025" / "Holiday 2026"

    # 2c. Program canonical (從 collection 推 — eg "WOMENS PERFORMANCE" / "OUTLET WOMENS ACTIVE/GRAPHICS")
    if meta.get("collection"):
        out["Program"] = meta["collection"]

    # 3. Department / Collection / Category / Sub-Category → split gender / W/K
    dept = (meta.get("department") or "").strip()
    coll = (meta.get("collection") or "").strip()
    cat = (meta.get("category") or "").strip()
    subcat = (meta.get("sub_category") or "").strip()
    combined = f"{dept} {coll} {cat} {subcat}".upper()
    if combined.strip():
        words = re.split(r"[\s/]+", combined)  # 也 split slash (eg "KNIT/SLEEPWEAR")
        gender_kw = next((w for w in words if w in {"WOMENS", "MENS", "GIRLS", "BOYS", "KIDS",
                                                     "BABY", "MATERNITY", "WOMEN", "MEN"}), None)
        wk_kw = next((w for w in words if w in {"KNIT", "KNITS", "WOVEN", "WOVENS"}), None)
        if gender_kw: out["gender_from_department"] = gender_kw
        if wk_kw: out["wk_from_department"] = wk_kw

    # 4. Unified canonical gender (從 dept 優先,沒就用 brand_division)
    final_gender = out.get("gender_from_department") or out.get("gender_from_brand_division")
    if final_gender:
        out["PRODUCT_CATEGORY"] = final_gender  # canonical 聚陽 key

    # 5. Unified canonical W/K (從 dept/coll/cat/subcat 推)
    if out.get("wk_from_department"):
        out["W/K"] = out["wk_from_department"]  # canonical 聚陽 key

    return out


def parse_ony(text: str) -> dict:
    """ONY = Centric 8 → call parse_centric8 + derive"""
    raw = parse_centric8(text)
    return derive_centric8_canonical(raw)


def parse_centric8_with_derive(text: str) -> dict:
    """ATHLETA / GAP / GAP_OUTLET / BR — same as parse_ony"""
    raw = parse_centric8(text)
    return derive_centric8_canonical(raw)


def parse_dicks(text: str) -> dict:
    """DICKS DSG cover layout — 直接含 Gender 欄"""
    raw = {
        "brand": _extract_block(text, [r'Brand:']),
        "style_number": _extract_block(text, [r'Style Number\s*:']),
        "style_description": _extract_block(text, [r'Style Description\s*:']),
        "season": _extract_block(text, [r'Season\s*:']),
        "department": _extract_block(text, [r'Department:']),
        "gender_pdf": _extract_block(text, [r'^\s*Gender\s*$', r'\nGender\s*\n']),
        "size_range": _extract_block(text, [r'Size Range']),
        "product_status": _extract_block(text, [r'Product Status\s*:']),
        "tech_pack_type": _extract_block(text, [r'Tech Pack Type']),
    }
    return derive_dicks_canonical(raw)


def derive_dicks_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "DICKS"  # canonical:DICKS Sporting Goods 是客戶
    if meta.get("brand"):
        out["Subgroup"] = meta["brand"]  # DSG/CALIA/VRST/WALTER HAGEN/PERFECT GAME/ALPINE DESIGN
    if meta.get("style_number"):
        out["報價款號"] = meta["style_number"]
    if meta.get("season"):
        out["Season"] = meta["season"]
    # PRODUCT_CATEGORY:先看 gender_pdf,再從 season 字串推
    g = (meta.get("gender_pdf") or "").upper()
    if g in {"WOMENS", "MENS", "GIRLS", "BOYS", "KIDS", "WOMEN", "MEN"}:
        out["PRODUCT_CATEGORY"] = g if g.endswith("S") else g + "S"
    else:
        # Season eg "Softlines - Athletic Boy's - Fall - 2026" 含 gender 暗示
        season = (meta.get("season") or "").lower()
        if "women" in season or "ladies" in season: out["PRODUCT_CATEGORY"] = "WOMENS"
        elif "men's" in season or " men " in f" {season} ": out["PRODUCT_CATEGORY"] = "MENS"
        elif "boy" in season: out["PRODUCT_CATEGORY"] = "BOYS"
        elif "girl" in season: out["PRODUCT_CATEGORY"] = "GIRLS"
        elif "kid" in season or "youth" in season: out["PRODUCT_CATEGORY"] = "KIDS"
    # W/K from department keyword
    dept = (meta.get("department") or "").upper()
    if "KNIT" in dept: out["W/K"] = "KNIT"
    elif "WOVEN" in dept: out["W/K"] = "WOVEN"
    return out


# ════════════════════════════════════════════════════════════
# TARGET — Centric PLM-like vertical, English
# ════════════════════════════════════════════════════════════

def parse_target(text: str) -> dict:
    """TARGET — 三種 PDF layout 自動偵測:
    A. Workfront / Centric PLM 有 "Product ID" + "Design Cycle" (~53 PDFs)
    B. AIM 中文 tech-sketch 含 AIM-prefixed style number (~45 PDFs)
    C. POM-only (~59 PDFs) 沒 cover metadata,M7 列管 fallback 兜底

    layout 偵測:先試 A,空就試 B,還空就 return {"客戶":"TARGET"} 至少標 client。
    """
    has_workfront = "Product ID" in text and "Design Cycle" in text
    if has_workfront:
        raw = {
            "product_id": _extract_block(text, [r"Product ID"], max_lines=1),
            "status": _extract_block(text, [r"\bStatus\b"], max_lines=1),
            "tgt_brand": _extract_block(text, [r"\bBrand\b(?!\s*Division)"], max_lines=1),
            "department": _extract_block(text, [r"\bDepartment\b"], max_lines=1),
            "division": _extract_block(text, [r"\bDivision\b"], max_lines=1),
            "workspace_name": _extract_block(text, [r"Workspace Name"], max_lines=1),
            "workspace_id": _extract_block(text, [r"Workspace ID"], max_lines=1),
            "design_cycle": _extract_block(text, [r"Design Cycle"], max_lines=1),
        }
        return derive_target_canonical(raw)

    # B. AIM 模板 — column-major 直接掃 text + filename 找 AIM-prefixed style code
    # 格式 1: AIM26C3W28 (year=26, qtr=C3, gender=W, serial=28)
    # 格式 2: AIM27C2WV02 (year=27, qtr=C2, gender_letters=WV, serial=02)
    # text 已 prepend "__FILENAME__: TPKxxx-AIM26C3W28new1009.pdf",檔名比 PDF 內文穩
    aim_match = re.search(r"(?<![A-Za-z])(AIM\d{2}[A-Z]\d{1,2}[A-Z]+\d{1,3})", text)
    if aim_match:
        raw = {"target_layout": "AIM", "style_no_aim": aim_match.group(1)}
        # Gender:從 AIM code 第 7 位 (W/M/B/G/K) 推
        m = re.match(r"AIM\d{2}[A-Z]\d{1,2}([A-Z])", aim_match.group(1))
        if m:
            letter = m.group(1)
            gender_map = {"W": "WOMENS", "M": "MENS", "B": "BOYS", "G": "GIRLS", "K": "KIDS"}
            if letter in gender_map:
                raw["gender_aim"] = gender_map[letter]
        # 補:從 page text 找獨立 word 當二次來源
        if not raw.get("gender_aim"):
            text_up = text.upper()
            for kw in ["WOMENS", "WOMEN", "MENS", "MEN", "GIRLS", "GIRL",
                       "BOYS", "BOY", "KIDS", "KID"]:
                if re.search(r"\b" + kw + r"\b", text_up):
                    raw["gender_aim"] = kw if kw.endswith("S") else kw + "S"
                    break
        # Season: AIM26C3W28 → year=26, quarter=C3 → C326 (對齊 client_metadata_mapping)
        m = re.search(r"AIM(\d{2})C(\d)", aim_match.group(1))
        if m:
            raw["season_aim"] = f"C{m.group(2)}{m.group(1)}"
        return derive_target_canonical_aim(raw)

    # C. POM-only / 無 metadata — 仍標 客戶 = TARGET 給 M7 列管 join 用
    return {"客戶": "TARGET", "target_layout": "POM_ONLY"}


def derive_target_canonical_aim(meta: dict) -> dict:
    """AIM 模板的 derive — 用 style_no 推 Season,gender 已 normalize"""
    out = dict(meta)
    out["客戶"] = "TARGET"
    out["Program"] = "All In Motion"  # AIM = Target 子線品牌
    if meta.get("style_no_aim"):
        out["報價款號"] = meta["style_no_aim"]
    if meta.get("gender_aim"):
        out["PRODUCT_CATEGORY"] = meta["gender_aim"]
    if meta.get("season_aim"):
        out["Season"] = meta["season_aim"]
    return out


def derive_target_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "TARGET"
    # 1. 報價款號 = Product ID 去掉 PID- 前綴 (PID-00GG4Z → 00GG4Z)
    pid = (meta.get("product_id") or "").strip()
    m = re.match(r"^PID-([A-Z0-9]+)$", pid, re.I)
    if m:
        out["報價款號"] = m.group(1).upper()
    elif pid:
        out["報價款號"] = pid
    # 2. Season = Design Cycle (C1 2026 → C126)
    dc = (meta.get("design_cycle") or "").strip()
    m = re.match(r"^C(\d)\s+20(\d{2})$", dc)
    if m:
        out["Season"] = f"C{m.group(1)}{m.group(2)}"
    elif dc:
        out["Season"] = dc
    # 3. Department "41:MENS PERFORMANCE" → split D-code + gender
    dept = (meta.get("department") or "").strip()
    m = re.match(r"^(\d+):([A-Z]+)\s*(.*)$", dept)
    if m:
        out["Subgroup"] = f"D{m.group(1)}"  # D41 / D214 / D75 (對齊 client_metadata_mapping)
        gender_kw = m.group(2)
        # MENS/WOMENS/KIDS/BABY/GIRLS/BOYS
        if gender_kw in {"MENS", "WOMENS", "KIDS", "BABY", "GIRLS", "BOYS"}:
            out["PRODUCT_CATEGORY"] = gender_kw
    # 4. Program = TGT Brand (All In Motion / Universal Thread / Cat & Jack 等子線)
    if meta.get("tgt_brand"):
        out["Program"] = meta["tgt_brand"]
    return out


# ════════════════════════════════════════════════════════════
# KOHLS — Makalot 內部 screenshot, 2D label grid
# ════════════════════════════════════════════════════════════

def parse_kohls(text: str) -> dict:
    """KOHLS Makalot-internal screenshot PDF
    Layout (label/value 不一定相鄰,column-major reading order):
      Style No / 26FS02306(PANTS)
      Customer / KOHLS
      Brand / SO
      Category / Women
    Designer/Sales/Page values 散在後面行,先不抽。
    """
    raw = {
        "style_no": _extract_block(text, [r"Style No(?!\.)"], max_lines=1),
        "customer": _extract_block(text, [r"\bCustomer\b"], max_lines=1),
        "kohls_brand": _extract_block(text, [r"\bBrand\b"], max_lines=1),
        "kohls_category": _extract_block(text, [r"\bCategory\b"], max_lines=1),
    }
    return derive_kohls_canonical(raw)


KOHLS_VALID_BRANDS = {
    "SO", "CB", "TG", "FLX", "FLX MEN", "FLX WMN",
    "TG MEN", "TG WMN", "CB MEN", "CB WMN",
    "SONOMA", "SO JUNIOR", "CHAMPION", "TEK GEAR",
    "ACT", "RTW", "SLW",  # category prefix 也接受
}

def derive_kohls_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "KOHLS"
    # Style No 必須有英數字 (避開亂抓的 "Size" / "部 位" 等)
    sn_raw = meta.get("style_no") or ""
    m = re.match(r"^([A-Z0-9]{4,})", sn_raw)
    if m:
        out["報價款號"] = m.group(1)
    # PRODUCT_CATEGORY 白名單
    cat = (meta.get("kohls_category") or "").strip().upper()
    if cat in {"WOMEN", "MEN", "GIRLS", "BOYS", "KIDS", "BABY"}:
        out["PRODUCT_CATEGORY"] = cat + "S" if cat in {"WOMEN", "MEN"} else cat
    # Subgroup 白名單(避開 "部 位" / 中文 / 純數字 等 noise)
    brand_raw = (meta.get("kohls_brand") or "").strip().upper()
    # Match 白名單(可能 prefix match,eg "SO JUNIOR" 或 "TG MEN")
    if brand_raw and any(brand_raw.startswith(b) or brand_raw == b for b in KOHLS_VALID_BRANDS):
        out["Subgroup"] = brand_raw
    elif brand_raw and re.match(r"^[A-Z][A-Z0-9 ]{0,15}$", brand_raw) and len(brand_raw) <= 16:
        # 純英文上限 16 字 — 接受其他可能新增的 sub-brand
        out["Subgroup"] = brand_raw
    return out


# ════════════════════════════════════════════════════════════
# A_&_F (Abercrombie & Fitch) — vertical, real metadata on page 2
# ════════════════════════════════════════════════════════════

def parse_anf(text: str) -> dict:
    """A&F cover layout — page 2 才是真 metadata:
      Style / OTG TERRY SHORT 119260065
      Style Code / 119260065
      Year / 2026
      Brand / Abercrombie & Fitch
      Group / Women's
      Department / 119 - ANF WOMENS ACTIVE\nBOTTOMS
      Imports Category / Knits

    Department 跨兩行 (eg "119 - ANF WOMENS ACTIVE" + "BOTTOMS")
    """
    raw = {
        "style": _extract_block(text, [r"\bStyle\b(?!\s*Code)"], max_lines=1),
        "style_code": _extract_block(text, [r"Style Code"], max_lines=1),
        "year": _extract_block(text, [r"\bYear\b"], max_lines=1),
        "brand": _extract_block(text, [r"\bBrand\b"], max_lines=1),
        "group": _extract_block(text, [r"\bGroup\b"], max_lines=1),
        "department": _extract_block(text, [r"\bDepartment\b"], max_lines=2),
        "imports_category": _extract_block(text, [r"Imports Category"], max_lines=1),
        "fit_pattern_name": _extract_block(text, [r"Fit Pattern Name"], max_lines=1),
    }
    return derive_anf_canonical(raw)


def derive_anf_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "A_&_F"
    if meta.get("style_code"):
        out["報價款號"] = meta["style_code"]
    if meta.get("year"):
        out["Season"] = meta["year"]  # 2026 — 月份/季在 PDF 沒寫
    # Group "Women's" → WOMENS / "Men's" → MENS
    g = (meta.get("group") or "").strip().lower()
    if "women" in g: out["PRODUCT_CATEGORY"] = "WOMENS"
    elif "men" in g: out["PRODUCT_CATEGORY"] = "MENS"
    elif "girl" in g: out["PRODUCT_CATEGORY"] = "GIRLS"
    elif "boy" in g: out["PRODUCT_CATEGORY"] = "BOYS"
    # Department "119 - ANF WOMENS ACTIVE" → D-code + gender re-confirm
    dept = (meta.get("department") or "").strip()
    m = re.match(r"^(\d+)\s*-", dept)
    if m:
        out["Subgroup"] = m.group(1)
        # Re-extract gender from dept text in case Group field is empty
        d_up = dept.upper()
        for kw in ["WOMENS", "MENS", "GIRLS", "BOYS", "KIDS", "BABY"]:
            if kw in d_up:
                out.setdefault("PRODUCT_CATEGORY", kw)
                break
    # Imports Category "Knits" / "Wovens" → W/K
    ic = (meta.get("imports_category") or "").strip().upper()
    if "KNIT" in ic: out["W/K"] = "KNIT"
    elif "WOVEN" in ic: out["W/K"] = "WOVEN"
    return out


# ════════════════════════════════════════════════════════════
# GU — Japanese labels, single page
# ════════════════════════════════════════════════════════════

GU_SIBLING_LABELS = {
    "企業", "デザイン名", "ブランド", "アイテム", "シーズン", "ページ",
    "品番", "パーツ数", "サイズ", "縮尺", "作成者", "デザイナー",
    "作成日", "更新日", "出力日",
}

def _gu_clean(value):
    """drop GU sibling labels — _extract_block 抓空值時會跳到下一行抓到 label 名"""
    if not value:
        return None
    if value.strip() in GU_SIBLING_LABELS:
        return None
    return value


def parse_gu(text: str) -> dict:
    """GU (Uniqlo sister brand) Japanese label layout:
      企業 / GU
      デザイン名 / LPR2028
      ブランド / Women's
      アイテム / Pants
      シーズン / 2026SS
      品番 / 226N020
    """
    raw = {
        "kigyo": _gu_clean(_extract_block(text, [r"企業"], max_lines=1)),
        "design_name": _gu_clean(_extract_block(text, [r"デザイン名"], max_lines=1)),
        "brand_jp": _gu_clean(_extract_block(text, [r"ブランド"], max_lines=1)),
        "item_jp": _gu_clean(_extract_block(text, [r"アイテム"], max_lines=1)),
        "season_jp": _gu_clean(_extract_block(text, [r"シーズン"], max_lines=1)),
        "hinban": _gu_clean(_extract_block(text, [r"品番"], max_lines=1)),
        "size_jp": _gu_clean(_extract_block(text, [r"サイズ"], max_lines=1)),
    }
    raw = {k: v for k, v in raw.items() if v}
    return derive_gu_canonical(raw)


def derive_gu_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "GU"
    # 報價款號:GU 用 デザイン名 (LPR2028) + 品番 (226N020)
    # M7 nt-net2 通常用品番,所以 primary = 品番,fallback = デザイン名
    if meta.get("hinban"):
        out["報價款號"] = meta["hinban"]
    elif meta.get("design_name"):
        out["報價款號"] = meta["design_name"]
    if meta.get("design_name"):
        out["design_name_pdf"] = meta["design_name"]  # cross-check 證據
    # Season:2026SS / 2026FW
    if meta.get("season_jp"):
        out["Season"] = meta["season_jp"]
    # Item:Pants / Shirts / etc
    if meta.get("item_jp"):
        out["Item"] = meta["item_jp"]
    # Brand "Women's" → gender (含 Kids / GA_Women / GA_Men 等變體)
    g = (meta.get("brand_jp") or "").lower()
    if "women" in g: out["PRODUCT_CATEGORY"] = "WOMENS"
    elif "men" in g: out["PRODUCT_CATEGORY"] = "MENS"
    elif "girl" in g: out["PRODUCT_CATEGORY"] = "GIRLS"
    elif "boy" in g: out["PRODUCT_CATEGORY"] = "BOYS"
    elif "kid" in g: out["PRODUCT_CATEGORY"] = "KIDS"
    return out


# ════════════════════════════════════════════════════════════
# CATO — mixed inline + vertical, single template
# ════════════════════════════════════════════════════════════

def parse_cato(text: str) -> dict:
    """CATO Direct Source bid package cover:
      Dev # 309567 31" WL Pintuck Pant
      RFQ No. : Bid Package-102943
      Department: 1047-J/M Knit Btms/Jkts
      VPN:
      Season: 2025 Fall Apparel
      Size Category: Missy
      Published Date: 11/14/2024
      Style Description:
      31" WL Pintuck Pant
      Size Range:
      XXS-XL
    """
    text_clean = text.replace("​", "").replace("\xa0", " ")
    raw = {}
    # Dev # 在 line 3:"Dev # 309567 31\" WL Pintuck Pant"
    m = re.search(r"Dev\s*#\s*(\d+)\s+(.*?)(?:\n|$)", text_clean)
    if m:
        raw["dev_number"] = m.group(1)
        raw["dev_description"] = m.group(2).strip()
    # RFQ No.: 同行
    m = re.search(r"RFQ No\.\s*:\s*(.+?)(?:\n|$)", text_clean)
    if m: raw["rfq_no"] = m.group(1).strip()
    # Department: 同行
    m = re.search(r"Department:\s*(.+?)(?:\n|$)", text_clean)
    if m: raw["department"] = m.group(1).strip()
    # Season: 同行
    m = re.search(r"Season:\s*(.+?)(?:\n|$)", text_clean)
    if m: raw["season"] = m.group(1).strip()
    # Size Category: 同行
    m = re.search(r"Size Category:\s*(.+?)(?:\n|$)", text_clean)
    if m: raw["size_category"] = m.group(1).strip()
    # Style Description: 下一行 (vertical)
    raw["style_description"] = _extract_block(text_clean, [r"Style Description:"], max_lines=1)
    raw["size_range"] = _extract_block(text_clean, [r"Size Range:"], max_lines=1)
    raw["initial_instore_month"] = _extract_block(text_clean, [r"Initial InStore Month:"], max_lines=1)
    return derive_cato_canonical(raw)


def derive_cato_canonical(meta: dict) -> dict:
    out = dict(meta)
    out["客戶"] = "CATO"
    if meta.get("dev_number"):
        out["報價款號"] = meta["dev_number"]
    if meta.get("season"):
        out["Season"] = meta["season"]
    # Department "1047-J/M Knit Btms/Jkts" → split D-code + W/K
    dept = (meta.get("department") or "").strip()
    m = re.match(r"^(\d+)-", dept)
    if m:
        out["Subgroup"] = m.group(1)
    d_up = dept.upper()
    if "KNIT" in d_up: out["W/K"] = "KNIT"
    elif "WOVEN" in d_up: out["W/K"] = "WOVEN"
    # Size Category "Missy/Plus/Junior" → CATO 都是女裝
    sc = (meta.get("size_category") or "").strip().upper()
    if sc in {"MISSY", "PLUS", "JUNIOR", "WOMEN", "WOMENS"}:
        out["PRODUCT_CATEGORY"] = "WOMENS"
        if sc != "WOMENS":
            out["cato_size_category"] = sc  # 額外保留 Missy/Plus/Junior 訊息
    # Item:Department 含 "Btms/Jkts" 可推 BOTTOMS/JACKETS
    if "BTM" in d_up or "BOTTOM" in d_up: out["Item"] = "BOTTOMS"
    elif "TOP" in d_up: out["Item"] = "TOPS"
    return out


def parse_generic(text: str) -> dict:
    """fallback：通用 regex"""
    return {
        "brand_division": _extract_block(text, [r'Brand[/​]Division', r'Brand:']),
        "department": _extract_block(text, [r'Department:?']),
        "season": _extract_block(text, [r'Season:?']),
        "gender_pdf": _extract_block(text, [r'\nGender\s*\n', r'Gender:?']),
        "category": _extract_block(text, [r'Category:?']),
    }


CLIENT_PARSERS = {
    # Centric 8 系列 — 共用 parser
    "ONY": parse_ony,
    "ATHLETA": parse_centric8_with_derive,
    "GAP": parse_centric8_with_derive,
    "GAP_OUTLET": parse_centric8_with_derive,
    "BR": parse_centric8_with_derive,
    # DSG
    "DICKS": parse_dicks,
    # 5/8 新增
    "TARGET": parse_target,
    "KOHLS": parse_kohls,
    "A_&_F": parse_anf,
    "GU": parse_gu,
    "CATO": parse_cato,
}


def extract_pdf_metadata(pdf_path: Path, client: str) -> dict:
    """開 PDF page 1（cover），用 per-client parser 抽 metadata"""
    parser = CLIENT_PARSERS.get(client, parse_generic)
    try:
        doc = fitz.open(str(pdf_path))
        text = doc[0].get_text() if doc.page_count > 0 else ""
        # 加 page 2 (DICKS / A_&_F 部分 metadata 在 page 2)
        if doc.page_count > 1:
            text += "\n" + doc[1].get_text()
        doc.close()
        # Prepend filename — TARGET AIM 模板的 PDF 內文 column-major 拆字串,
        # 但檔名通常含 AIM-style code (eg TPKxxx-AIM26C3W28-...pdf),用檔名 fallback。
        text = f"__FILENAME__: {pdf_path.name}\n" + text
        meta = parser(text)
        return {k: v for k, v in meta.items() if v}  # 去掉 None
    except Exception as e:
        print(f"  [!] {pdf_path.name}: {e}", file=sys.stderr)
        return {}


def find_pdf_path(d: dict) -> Path | None:
    """從 designs.jsonl 一筆 row 找實際 PDF 位置(tp_samples_v2 子目錄優先,fallback 到 pdf_tp 扁平)"""
    pdf_name = d.get("source_file", "")
    if not pdf_name:
        return None
    eidh = d.get("eidh")

    # 1. tp_samples_v2/<EIDH>_*/<filename>
    if eidh and TP_SAMPLES.exists():
        for sub in TP_SAMPLES.glob(f"{eidh}_*"):
            cand = sub / pdf_name
            if cand.exists():
                return cand

    # 2. pdf_tp/ flat (legacy)
    cand = PDF_TP_FLAT / pdf_name
    if cand.exists():
        return cand

    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0,
                   help="limit total PDFs processed (0 = no limit)")
    p.add_argument("--client", default=None,
                   help="filter to specific client(s),comma-sep (eg ONY,ATHLETA,GAP,GAP_OUTLET)")
    args = p.parse_args()

    # Parse client filter
    client_filter = None
    if args.client:
        client_filter = set(c.strip().upper() for c in args.client.split(","))
        print(f"[filter] only client(s): {client_filter}")

    # Load designs
    print(f"[load] reading {DESIGNS}")
    designs = []
    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("source_file", "").lower().endswith(".pdf"):
                if client_filter and d.get("client", "").upper() not in client_filter:
                    continue
                designs.append(d)
    if args.limit:
        designs = designs[:args.limit]
    print(f"[load] {len(designs)} designs with PDF source")

    n_extracted = 0
    n_no_pdf_found = 0
    n_no_meta = 0
    by_client_count = {}

    with open(OUT_PATH, "w", encoding="utf-8") as fout:
        for d in designs:
            client = d.get("client", "")
            pdf_path = find_pdf_path(d)
            if not pdf_path:
                n_no_pdf_found += 1
                continue
            meta = extract_pdf_metadata(pdf_path, client)
            if not meta:
                n_no_meta += 1
                continue
            row = {
                "client": client,
                "design_id": d.get("design_id", ""),
                "eidh": d.get("eidh"),
                "source_pdf": pdf_path.name,
                **meta
            }
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_extracted += 1
            by_client_count[client] = by_client_count.get(client, 0) + 1

    print(f"\n[output] {OUT_PATH}")
    print(f"  extracted:        {n_extracted}")
    print(f"  PDF not found:    {n_no_pdf_found}")
    print(f"  parser no meta:   {n_no_meta}")
    print(f"  by client:")
    for c, n in sorted(by_client_count.items(), key=lambda x: -x[1]):
        print(f"    {c}: {n}")


if __name__ == "__main__":
    main()
