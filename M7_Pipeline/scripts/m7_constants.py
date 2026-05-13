"""
m7_constants.py — M7 PullOn pipeline 共用常數 + helper

這個 module 是所有 *_m7.py script 的 single source of truth：
  - L1 部位字典 (38 個 IE category 中文 → 2-letter code)
  - Zone alias 同義詞
  - ISO regex / 縫法 keyword / margin / needle pattern
  - Centric 8 非 construction 頁偵測 keyword
  - 中英 glossary
  - Customer 標準化 mapping

import：
  from m7_constants import ZH_TO_L1, ISO_RE, SEW_KW, ...

未來改 zone alias / 加新 ISO / 加新 keyword 只需改這一處。
"""

import re

# ════════════════════════════════════════════════════════════
# L1 部位字典 (38 個 IE category)
# ════════════════════════════════════════════════════════════

ZH_TO_L1 = {
    "腰頭":"WB","褲合身":"PS","褲襠":"RS","褲口":"LO","口袋":"PK","商標":"LB",
    "剪接線_下身類":"SB","貼合":"BN","繩類":"DC","其它":"OT","襬叉":"BP",
    "裡布":"LI","釦鎖":"BS","前立":"PL","褶":"PD","帶絆":"LP",
    "領":"NK","肩":"SH","袖口":"SL","下襬":"BM","脅邊":"SS",
    "袖籠":"AH","袖襱":"AE","領貼條":"NT","拉鍊":"ZP","釦環":"HL",
    "袋蓋":"FP","肩帶":"ST","帽子":"HD","拇指洞":"TH","行縫":"QT",
    "裝飾片":"DP","領襟":"NP","剪接線_上身類":"SA","裙合身":"SR",
}
L1_KEYS_SORTED = sorted(ZH_TO_L1.keys(), key=len, reverse=True)


# Zone alias：別名 → 主 zone (從 OT 樣態分析得出)
ZONE_ALIAS = {
    "腿口": "褲口", "腿口邊": "褲口", "褲腿口": "褲口",
    "前後襠": "褲襠", "前後襠壓": "褲襠", "前襠": "褲襠", "後襠": "褲襠",
    "前襠線": "褲襠", "後襠線": "褲襠", "下襠": "褲襠", "下襠線": "褲襠",
    "鬆緊帶": "腰頭", "鬆緊": "腰頭", "腰圍": "腰頭", "腰邊": "腰頭",
    "袋貼": "口袋", "袋貼兩片": "口袋", "口袋貼條": "口袋", "貼袋": "口袋",
    "暗袋": "口袋", "後袋": "口袋", "前袋": "口袋", "側袋": "口袋",
    "前中繩口": "繩類", "腰繩": "繩類", "繩": "繩類",
    "繡花": "裝飾片", "繡花雞眼": "裝飾片",
    "裡褲": "裡布", "內裡": "裡布",
    "扣眼": "釦鎖", "雞眼": "釦鎖",
    "後幅司": "剪接線_下身類", "幅司": "剪接線_下身類", "yoke": "剪接線_下身類",
    "側縫": "脅邊", "側邊": "脅邊", "脅縫": "脅邊",
    "下襬邊": "下襬", "腰底": "腰頭", "腰圍尺寸": "腰頭",
    "拉鍊邊": "拉鍊", "拉鏈": "拉鍊",
}
ALIAS_KEYS_SORTED = sorted(ZONE_ALIAS.keys(), key=len, reverse=True)


# ════════════════════════════════════════════════════════════
# Glossary 英→中
# ════════════════════════════════════════════════════════════

GLOSSARY_EN_TO_ZH = {
    # 縫法
    "SN TS": "單針壓線", "SNTS": "單針壓線", "TOPSTITCH": "壓明線",
    "CHAINSTITCH": "鎖鏈車", "CHAIN STITCH": "鎖鏈車",
    "COVERSTITCH": "三本雙針", "CVRST": "三本雙針", "CS": "三本雙針",
    "OVERLOCK": "拷克", "SERGE": "拷克", "SERGED": "拷克",
    "FLATLOCK": "併縫", "FLATSEAM": "併縫",
    "BINDING": "滾條", "TURN IN BINDING": "反折包邊",
    "FELLED SEAM": "包縫", "LAPPED SEAM": "搭縫", "SATIN STITCH": "緞紋",
    "BARTACK": "打結車", "BAR TACK": "打結車",
    "EDGESTITCH": "臨邊線", "EDGE STITCH": "臨邊線",
    "CLEAN FINISH": "包光", "CLEAN FIN": "包光",
    "TURNBACK": "反折", "TURN BACK": "反折", "TURN & TURN": "反折兩次",
    "TB": "反折", "DBL TB": "雙反折", "UNDERSTITCHED": "壓線", "STRADDLE": "跨壓",
    "1NTS": "單針壓線", "2NTS": "雙針壓線", "2N3TH": "三本雙針", "3N5TH": "三針五線",
    "1N": "單針", "2N": "雙針", "3N": "三針", "4N": "四針",
    "DBL NDL": "雙針", "NDL": "針", "BONDED": "熱貼合",
    # 部位
    "WAISTBAND": "腰頭", "WAIST": "腰頭", "WB": "腰頭",
    "POCKET": "口袋", "HEM": "下襬",
    "RISE": "襠", "INSEAM": "內側線", "OUTSEAM": "外側線",
    "FLY": "前立", "VENT": "襬叉", "YOKE": "幅司",
    "GUSSET": "檔片", "LINER": "裡布", "LINING": "裡布",
    "ELASTIC": "鬆緊帶", "DRAWCORD": "腰繩", "DRAWSTRING": "腰繩",
    "PLACKET": "門襟", "BUTTONHOLE": "扣眼",
    "EYELET": "雞眼", "EYELETS": "雞眼",
    "LEG OPENING": "褲口", "LEG HEM": "褲口", "PANT HEM": "褲口",
    "SIDE SEAM": "側縫", "SIDE STRIPES": "側條",
    "BACK YOKE": "後幅司", "FRONT": "前", "BACK": "後", "STRIPE": "條紋",
}


# [REMOVED 2026-05-05] EN_ZONE_TO_L1 dict 已棄用，由 KW_TO_L1_BOTTOMS（檔尾）取代
# 舊 dict INSEAM→RS 是錯的（應 PS 褲合身）；新 KW_TO_L1_BOTTOMS 已修正


# Sewing keyword → method (用於從 callout text 萃取 method)
KEYWORD_TO_METHOD = {
    # English
    "COVERSTITCH": "COVERSTITCH", "CVRST": "COVERSTITCH", "2N3TH": "COVERSTITCH",
    "3N5TH": "COVERSTITCH",
    "OVERLOCK": "OVERLOCK", "SERGE": "OVERLOCK", "SERGED": "OVERLOCK",
    "FLATLOCK": "FLATLOCK", "FLATSEAM": "FLATLOCK",
    "TOPSTITCH": "TOPSTITCH", "SN TS": "TOPSTITCH", "SNTS": "TOPSTITCH",
    "EDGESTITCH": "TOPSTITCH", "EDGE STITCH": "TOPSTITCH",
    "CHAINSTITCH": "CHAINSTITCH", "CHAIN STITCH": "CHAINSTITCH",
    "BARTACK": "BARTACK", "BAR TACK": "BARTACK",
    "BINDING": "BINDING", "TURN IN BINDING": "BINDING",
    "BLINDHEM": "BLINDHEM", "BLIND HEM": "BLINDHEM",
    "BONDED": "BONDED",
    # 中文
    "三本": "COVERSTITCH", "三針五線": "COVERSTITCH",
    "拷克": "OVERLOCK", "鎖縫": "OVERLOCK",
    "併縫": "FLATLOCK",
    "單針": "TOPSTITCH", "雙針": "TOPSTITCH", "壓線": "TOPSTITCH",
    "鎖鏈車": "CHAINSTITCH",
    "打結車": "BARTACK",
    "滾條": "BINDING", "反折包邊": "BINDING",
    "暗縫": "BLINDHEM",
    "熱貼合": "BONDED",
}


# ISO → method（給沒有 method keyword 但有 ISO 的 callout 推 method）
ISO_TO_METHOD = {
    "301": "TOPSTITCH", "401": "CHAINSTITCH",
    "406": "COVERSTITCH", "503": "OVERLOCK", "504": "OVERLOCK",
    "514": "OVERLOCK", "515": "OVERLOCK", "516": "OVERLOCK",
    "601": "COVERSTITCH", "602": "COVERSTITCH", "605": "COVERSTITCH",
    "607": "FLATLOCK",
}


# ════════════════════════════════════════════════════════════
# Regex
# ════════════════════════════════════════════════════════════

# 統一 ISO_RE — 跟 star_schema VALID_ISOS 一致（10 個 ISO）
# 砍 503/512/515/601 cousins（罕見且 ISO_TO_ZH_METHOD 未涵蓋）
# 加 501（star_schema 有，2-thread overedge）
ISO_RE = re.compile(r"\b(301|401|406|501|504|514|516|602|605|607)\b")
VALID_ISOS = {'301', '401', '406', '501', '504', '514', '516', '602', '605', '607'}
MARGIN_RE = re.compile(r'\d+/\d+["”]')
NEEDLE_RE = re.compile(r"\b[23]N\b|\b[23]NDL\b|\b2N3TH\b|\b3N5TH\b", re.I)


# ════════════════════════════════════════════════════════════
# 縫法 keyword + Construction page detect
# ════════════════════════════════════════════════════════════

SEW_KW = list(KEYWORD_TO_METHOD.keys())  # 自動同步 KEYWORD_TO_METHOD

EXCLUDE_TITLES = ["GRADE REVIEW", "REF IMAGES", "REFERENCE IMAGES",
                  "INSPIRATION IMAGES", "INSPIRATION", "FIT COMMENTS",
                  "FIT SAMPLE IMAGES", "PATTERN CORRECTIONS", "NEXT STEPS",
                  "MOCK NECK REFERENCES"]
POM_KW = ["POM NAME", "TOL FRACTION", "VENDOR ACTUAL", "SAMPLE EVAL", "QC EVALUATION"]


# Centric 8 非 construction 頁特徵
POM_ID_RE = re.compile(r"\b[A-Z]{1,3}\d{2,3}[A-Z]?\b")  # W001, H005, G001, SY005...
METADATA_KW = ["DESIGN NUMBER", "DESIGN TYPE", "DESIGN SUB-TYPE", "BRAND/DIVISION",
               "BRAND DIVISION", "DEPARTMENT", "CARRY OVER", "REVISION", "FIT CAMP",
               "BOM PRIMARY", "SEASON PLANNING", "PRIMARY SUPPLIER", "BOM VERSION",
               "STATUS\tADOPTED", "DESIGN CONCEPT", "COSTING INFORMATION"]
BOM_TABLE_KW = ["BOMCOLORMATRIX", "OWNER TYPE", "COMPONENTS\tDOCUMENTS",
                "BOM CC NUMBER", "PRODUCT SUSTAINABILITY",
                "BOM DETAILS", "MATERIAL NAME", "GAUGE/ENDS",
                "QUALITY DETAILS", "PRIMARY RD",
                "SUPPLIER ARTICLE", "CC NAME",
                "SUSTAINABILITY ATTRIBUTE"]


def is_centric8_non_construction(text: str, upper: str) -> tuple[bool, str]:
    """偵測 Centric 8 非 construction 頁：metadata cover / POM 表 / BOM 表"""
    if "TOL (-)" in upper and "TOL (+)" in upper:
        return True, "POM table (Tol -/+)"
    pom_ids = POM_ID_RE.findall(text)
    if len(pom_ids) >= 8:
        return True, f"POM table ({len(pom_ids)} POM IDs)"
    metadata_hits = sum(1 for kw in METADATA_KW if kw in upper)
    if metadata_hits >= 4:
        return True, f"Centric 8 cover ({metadata_hits} metadata kw)"
    bom_hits = sum(1 for kw in BOM_TABLE_KW if kw in upper)
    if bom_hits >= 1:
        return True, f"BOM table"
    return False, ""


# ════════════════════════════════════════════════════════════
# Customer 標準化
# ════════════════════════════════════════════════════════════

CUSTOMER_TO_CODE = {
    "OLD NAVY": "ONY",
    "GAP": "GAP",
    "ATHLETA": "ATHLETA",
    "BANANA REPUBLIC": "BR",
    "ABERCROMBIE & FITCH": "AF",
    "A AND F": "AF",
    "A&F": "AF",
    "DICKS SPORTING GOODS": "DICKS",
    "DICK'S SPORTING GOODS": "DICKS",
    "TARGET": "TARGET",
    "WAL-MART": "WALMART",
    "WAL-MART-CA": "WALMART",
    "WALMART": "WALMART",
    "WAL MART": "WALMART",
    "KOHLS": "KOHLS",
    "KOHL'S": "KOHLS",
    "BEYOND YOGA": "BEYOND_YOGA",
    "UNDER ARMOUR": "UNDER_ARMOUR",
}


def normalize_client(customer: str) -> str:
    """客戶名 → 標準 code"""
    if not customer:
        return "UNKNOWN"
    c = customer.strip().upper()
    return CUSTOMER_TO_CODE.get(c, c.replace(" ", "_"))


# ════════════════════════════════════════════════════════════
# Translate (英文 callout → 中文)
# ════════════════════════════════════════════════════════════

def translate(text: str) -> str:
    """用 GLOSSARY_EN_TO_ZH 把英文做工 keyword 替換成中文"""
    out = text
    for kw in sorted(GLOSSARY_EN_TO_ZH, key=len, reverse=True):
        zh = GLOSSARY_EN_TO_ZH[kw]
        pattern = r'(?<![A-Za-z])' + re.escape(kw) + r'(?![A-Za-z])'
        out = re.sub(pattern, zh, out, flags=re.IGNORECASE)
    return out


# ════════════════════════════════════════════════════════════
# Bucket / GT group derivation
# ════════════════════════════════════════════════════════════

def derive_bucket(design_meta: dict) -> str:
    """
    PullOn bucket = {wk}_BOTTOMS，跨客戶可 union 找 consensus。
    client 不放 bucket（保留在 fact.client 欄獨立 query）。
    """
    wk = (design_meta.get("wk") or "").upper().strip() or "UNKNOWN"
    return f"{wk}_BOTTOMS"


def derive_gt_group(design_meta: dict) -> str:
    """PullOn 全是 BOTTOMS。其他品類保留判斷彈性"""
    item = (design_meta.get("item") or "").upper()
    if "PANT" in item or "SHORT" in item or "LEGGING" in item or "BOTTOM" in item:
        return "BOTTOMS"
    if "TOP" in item or "TEE" in item or "SHIRT" in item:
        return "TOPS"
    return "BOTTOMS"  # PullOn default


# ════════════════════════════════════════════════════════════
# Style Guide 對齊：dicts + helpers re-export from shared.zone_resolver
# 真正的 source of truth 在 data/zone_glossary.json
# ════════════════════════════════════════════════════════════

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from shared.zone_resolver import (  # noqa: E402
    KW_TO_L1_BOTTOMS, ISO_TO_ZH_METHOD, METHOD_EN_TO_ISO,
    find_zone_en, find_all_zones_en, extract_gauge, enrich_method_zh,
    GAUGE_RE,
)

# [REMOVED 2026-05-05] inline definitions of KW_TO_L1_BOTTOMS / find_zone_en /
# find_all_zones_en / ISO_TO_ZH_METHOD / GAUGE_RE / extract_gauge /
# METHOD_EN_TO_ISO / enrich_method_zh — all moved to shared/zone_resolver.py
# (loaded from data/zone_glossary.json). Imported above.
