#!/usr/bin/env python3
"""
extract_unified.py — Unified multi-source extraction pipeline (STEP 2a).

Reads ALL 4 data sources into a single star schema:
  1. construction_by_bucket (688 designs) — English JSON with pages/text_lines
  2. construction_from_dir5 (13 designs) — Same JSON format as #1
  3. construction_extracts/pptx (628 designs) — Chinese txt files, zone+method, NO ISO
  4. construction_extracts/pdf (185 designs) — English txt files, per-page PDF extraction

Outputs (under --out):
  {out}/dim.jsonl    — one row per design
  {out}/facts.jsonl  — one row per design × zone × ISO (all sources)

Each fact carries a `source` tag: cb / dir5 / pptx / pdf

Usage (CI — from repo root):
  python star_schema/scripts/extract_unified.py \\
      --ingest-dir data/ingest \\
      --out data/ingest/unified

Usage (local dev):
  python extract_unified.py
  # defaults: --ingest-dir <repo_root>/data/ingest
  #           --out        <repo_root>/data/ingest/unified

Flags:
  --ingest-dir <dir>          Ingest root (where Step 1 wrote metadata/, pptx/, pdf/)
  --out <dir>                 Unified output directory (default: {ingest-dir}/unified)
  --classification-file <f>   Optional GT backfill JSON
  --legacy-pptx-json-dir <d>  Optional legacy PPTX JSON dir (Source-Data/ONY/_parsed)
"""

import argparse
import json
import re
import os
import sys
import glob
from pathlib import Path
from collections import defaultdict


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` until we find a `.git` directory; return that ancestor."""
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return None


def default_ingest_dir() -> str:
    """Default --ingest-dir: <repo_root>/data/ingest/ (or star_schema/data/ingest/ fallback)."""
    script_dir = Path(__file__).resolve().parent
    repo_root = find_repo_root(script_dir)
    if repo_root and (repo_root / "data").exists():
        return str(repo_root / "data" / "ingest")
    return str(script_dir.parent / "data" / "ingest")

# ── normKey ──
def normKey(s):
    return re.sub(r'[^A-Z0-9]+', '_', s.upper()).strip('_')

# ── L1 Standard 38 ──
L1_STANDARD_38 = {
    "AE": "袖孔", "AH": "袖圍", "BM": "下襬", "BN": "貼合", "BP": "襬叉",
    "BS": "釦鎖", "DC": "繩類", "DP": "裝飾片", "FP": "袋蓋", "FY": "前立",
    "HD": "帽子", "HL": "釦環", "KH": "Keyhole", "LB": "商標", "LI": "裡布",
    "LO": "褲口", "LP": "帶絆", "NK": "領", "NP": "領襟", "NT": "領貼條",
    "OT": "其它", "PD": "褶", "PK": "口袋", "PL": "門襟", "PS": "褲合身",
    "QT": "行縫(固定棉)", "RS": "褲襠", "SA": "剪接線_上身類", "SB": "剪接線_下身類",
    "SH": "肩", "SL": "袖口", "SP": "袖叉", "SR": "裙合身", "SS": "脅邊",
    "ST": "肩帶", "TH": "拇指洞", "WB": "腰頭", "ZP": "拉鍊",
}
ZH_TO_L1 = {v: k for k, v in L1_STANDARD_38.items()}

# ── GT routing ──
TOP_GTS = {"TOP", "DRESS", "OUTERWEAR", "ROMPER_JUMPSUIT", "SET"}
BOTTOM_GTS = {"PANTS", "LEGGINGS", "SHORTS", "SKIRT", "BOTTOM"}

def classify_gt(item_type_raw, bucket):
    it = (item_type_raw or "").upper()
    bk = (bucket or "").lower()
    bottom_bk = any(w in bk for w in ["bottom", "pant", "legging", "short", "skirt", "skort"])
    top_bk = any(w in bk for w in ["top", "outer", "dress", "set", "bra", "fleece_top"])
    for gt in BOTTOM_GTS:
        if gt in it or "PANT" in it or "LEGGING" in it or "SHORT" in it or "SKIRT" in it or "SKORT" in it:
            return "BOTTOM"
    for gt in TOP_GTS:
        if gt in it or "BRA" in it or "HOODIE" in it or "JACKET" in it:
            return "TOP"
    if bottom_bk: return "BOTTOM"
    if top_bk: return "TOP"
    return "UNKNOWN"

# ── English Zone keyword → L1 mapping ──
KW_TO_L1_TOPS = {
    "HOOD": ("HD", "帽子"), "POCKET": ("PK", "口袋"), "SHOULDER": ("SH", "肩"),
    "COLLAR": ("NK", "領"), "NECK": ("NK", "領"), "MOCKNECK": ("NK", "領"),
    "NECKLINE": ("NK", "領"), "BACKNECK": ("NK", "領"), "RAGLAN": ("AH", "袖圍"),
    "CUFF": ("SL", "袖口"), "SLEEVECUFF": ("SL", "袖口"), "SLEEVE": ("SL", "袖口"),
    "HEM": ("BM", "下襬"), "BOTTOMHEM": ("BM", "下襬"), "BOTTOMOPENING": ("BM", "下襬"),
    "ARMHOLE": ("AE", "袖孔"), "SIDESEAM": ("SS", "脅邊"), "CBSEAM": ("SS", "脅邊"),
    "CFSEAM": ("SS", "脅邊"), "CFTWISTSEAM": ("SS", "脅邊"), "ZIPPER": ("ZP", "拉鍊"),
    "CFZIPPER": ("ZP", "拉鍊"), "ZIPPERPOCKET": ("PK", "口袋"),
    "PLACKET": ("PL", "門襟"), "BINDING": ("BM", "下襬"),
    "YOKE": ("SA", "剪接線_上身類"), "DART": ("PD", "褶"), "DARTS": ("PD", "褶"),
    "LOGO": ("LB", "商標"), "THUMBHOLE": ("TH", "拇指洞"), "STRAP": ("ST", "肩帶"),
    "WRAP": ("BM", "下襬"),
}
KW_TO_L1_BOTTOMS = {
    "WAIST": ("WB", "腰頭"), "WAISTBAND": ("WB", "腰頭"), "WAISTSEAM": ("WB", "腰頭"),
    "BACKWAIST": ("WB", "腰頭"), "FOLDOVER": ("WB", "腰頭"), "ELASTIC": ("WB", "腰頭"),
    "POCKET": ("PK", "口袋"), "POCKETOPENING": ("PK", "口袋"),
    "ZIPPERPOCKET": ("PK", "口袋"), "BARTACK": ("PK", "口袋"),
    "HEM": ("LO", "褲口"), "LEGOPENING": ("LO", "褲口"), "ANKLE": ("LO", "褲口"),
    "CUFF": ("LO", "褲口"), "INSEAM": ("PS", "褲合身"),
    "RISE": ("RS", "褲襠"), "FRONTRISE": ("RS", "褲襠"), "BACKRISE": ("RS", "褲襠"),
    "CROTCH": ("RS", "褲襠"), "GUSSET": ("RS", "褲襠"), "SIDESEAM": ("SS", "脅邊"),
    "SEAM": ("PS", "褲合身"), "FLY": ("PL", "門襟"), "DRAWCORD": ("DC", "繩類"),
    "YOKE": ("SB", "剪接線_下身類"), "ZIPPER": ("ZP", "拉鍊"),
    "SKIRTSEAM": ("SR", "裙合身"), "SKIRTSEAMS": ("SR", "裙合身"),
    "SKIRTHEM": ("BM", "下襬"), "LOGO": ("LB", "商標"),
    "DART": ("PD", "褶"), "DARTS": ("PD", "褶"),
}

# ── Chinese Zone keyword → L1 mapping (for PPTX) ──
# Handles both Traditional and Simplified characters
# Keys are Chinese zone terms found in PPTX translations
ZH_ZONE_TO_L1_TOPS = {
    # Collar/Neck
    "領片": ("NK", "領"), "领片": ("NK", "領"),
    "領座": ("NK", "領"), "领座": ("NK", "領"),
    "領": ("NK", "領"), "领": ("NK", "領"),
    "領圍": ("NK", "領"), "领围": ("NK", "領"),
    # Shoulder
    "肩縫": ("SH", "肩"), "肩缝": ("SH", "肩"), "肩": ("SH", "肩"),
    # Armhole / Sleeve
    "袖笼": ("AE", "袖孔"), "袖籠": ("AE", "袖孔"),
    "袖笼缝": ("AE", "袖孔"), "袖籠縫": ("AE", "袖孔"),
    # Cuff (Tops = SL)
    "克夫": ("SL", "袖口"), "袖口": ("SL", "袖口"),
    # Hem
    "下擺": ("BM", "下襬"), "下摆": ("BM", "下襬"),
    # Placket
    "門襟": ("PL", "門襟"), "门襟": ("PL", "門襟"),
    "前中門襟": ("PL", "門襟"), "前中门襟": ("PL", "門襟"),
    "袖門襟": ("SP", "袖叉"), "袖门襟": ("SP", "袖叉"),
    # Yoke (Tops = SA)
    "約克": ("SA", "剪接線_上身類"), "约克": ("SA", "剪接線_上身類"),
    "後約克": ("SA", "剪接線_上身類"), "后约克": ("SA", "剪接線_上身類"),
    # Pocket
    "口袋": ("PK", "口袋"),
    # Hood
    "帽": ("HD", "帽子"), "帽子": ("HD", "帽子"),
    # Zipper
    "拉鍊": ("ZP", "拉鍊"), "拉链": ("ZP", "拉鍊"),
    # Side seam
    "側縫": ("SS", "脅邊"), "侧缝": ("SS", "脅邊"),
    "脅邊": ("SS", "脅邊"), "脇邊": ("SS", "脅邊"),
    # Thumb hole
    "拇指洞": ("TH", "拇指洞"),
    # Label
    "商標": ("LB", "商標"), "商标": ("LB", "商標"),
    # Lining
    "裡布": ("LI", "裡布"), "里布": ("LI", "裡布"),
    # Binding
    "滾邊": ("NT", "領貼條"), "滚边": ("NT", "領貼條"),
    "貼條": ("NT", "領貼條"), "贴条": ("NT", "領貼條"),
    # Style guide aliases
    "袖襱": ("AE", "袖孔"),
    "袖圍": ("AH", "袖圍"),      "袖围": ("AH", "袖圍"),
    "袖衩": ("SP", "袖叉"),
    "肩帶": ("ST", "肩帶"),      "肩带": ("ST", "肩帶"),
    "腰繩": ("DC", "繩類"),      "腰绳": ("DC", "繩類"),
    "抽繩": ("DC", "繩類"),      "抽绳": ("DC", "繩類"),
    "帽頂": ("HD", "帽子"),      "帽顶": ("HD", "帽子"),
    "帽沿": ("HD", "帽子"),
    "帽繩": ("DC", "繩類"),      "帽绳": ("DC", "繩類"),
}

ZH_ZONE_TO_L1_BOTTOMS = {
    # Waistband
    "腰頭": ("WB", "腰頭"), "腰头": ("WB", "腰頭"),
    "腰": ("WB", "腰頭"), "腰線": ("WB", "腰頭"), "腰线": ("WB", "腰頭"),
    "腰繩": ("DC", "繩類"), "腰绳": ("DC", "繩類"),  # drawcord in waist
    # Pocket
    "口袋": ("PK", "口袋"), "袋唇": ("PK", "口袋"),
    # Leg opening / Hem (Bottoms = LO)
    "褲口": ("LO", "褲口"), "裤口": ("LO", "褲口"),
    "褲腳": ("LO", "褲口"), "裤脚": ("LO", "褲口"),
    "克夫": ("LO", "褲口"),  # in bottoms, 克夫(cuff) = leg opening
    # Rise/Crotch
    "前襠": ("RS", "褲襠"), "后襠": ("RS", "褲襠"), "後襠": ("RS", "褲襠"),
    "前档": ("RS", "褲襠"), "后档": ("RS", "褲襠"),
    "襠": ("RS", "褲襠"), "档": ("RS", "褲襠"),
    # Inseam / body fit
    "褲合身": ("PS", "褲合身"), "内缝": ("PS", "褲合身"), "內縫": ("PS", "褲合身"),
    # Side seam
    "側縫": ("SS", "脅邊"), "侧缝": ("SS", "脅邊"),
    "脅邊": ("SS", "脅邊"), "脇邊": ("SS", "脅邊"),
    # Fly
    "前立": ("PL", "門襟"), "門襟": ("PL", "門襟"), "门襟": ("PL", "門襟"),
    "假前立": ("PL", "門襟"),
    # Drawcord
    "繩": ("DC", "繩類"), "绳": ("DC", "繩類"),
    # Yoke (Bottoms = SB)
    "約克": ("SB", "剪接線_下身類"), "约克": ("SB", "剪接線_下身類"),
    # Zipper
    "拉鍊": ("ZP", "拉鍊"), "拉链": ("ZP", "拉鍊"),
    # Hem (skirt context)
    "下擺": ("BM", "下襬"), "下摆": ("BM", "下襬"),
    # Label
    "商標": ("LB", "商標"), "商标": ("LB", "商標"),
    # Lining
    "裡布": ("LI", "裡布"), "里布": ("LI", "裡布"),
    # Binding
    "滾邊": ("NT", "領貼條"), "滚边": ("NT", "領貼條"),
    "貼條": ("NT", "領貼條"), "贴条": ("NT", "領貼條"),
    # Style guide aliases
    "裙合身": ("SR", "裙合身"),
    "裙擺": ("BM", "下襬"),     "裙摆": ("BM", "下襬"),
    "抽繩": ("DC", "繩類"),     "抽绳": ("DC", "繩類"),
    "腰帶": ("DC", "繩類"),     "腰带": ("DC", "繩類"),
}

# ── Chinese Method → ISO mapping ──
# Priority: compound terms first, then single-char terms
ZH_METHOD_TO_ISO = {
    # High confidence (clear machine/stitch type)
    "併縫": ("607", "FLATLOCK"),       # flatseam/flatlock
    "并缝": ("607", "FLATLOCK"),
    "拷克": ("514", "OVERLOCK"),       # overlock/serger
    "拷边": ("514", "OVERLOCK"),
    "三本": ("406", "COVERSTITCH"),    # 3-needle coverstitch
    "鎖鍊": ("401", "CHAINSTITCH"),   # chainstitch
    "锁链": ("401", "CHAINSTITCH"),
    "鏈車": ("401", "CHAINSTITCH"),
    "链车": ("401", "CHAINSTITCH"),
    "平車": ("301", "LOCKSTITCH"),     # lockstitch
    "平车": ("301", "LOCKSTITCH"),
    "暗縫": ("103", "BLIND_HEM"),     # blind hem
    "暗缝": ("103", "BLIND_HEM"),
    "人字車": ("304", "ZIGZAG"),      # herringbone/zigzag
    "人字带": ("304", "ZIGZAG"),
    "人字车": ("304", "ZIGZAG"),
    # Medium confidence (need context — default mapping)
    "雙針": ("406", "COVERSTITCH"),   # double needle = usually 406 coverstitch
    "双针": ("406", "COVERSTITCH"),
    "單針": ("301", "TOPSTITCH"),     # single needle = 301 lockstitch
    "单针": ("301", "TOPSTITCH"),
    # From style guide Part A — additional Chinese ISO terms
    "三線拷克": ("504", "OVERLOCK"),
    "三线拷克": ("504", "OVERLOCK"),
    "五線拷克": ("516", "SAFETY"),
    "五线拷克": ("516", "SAFETY"),
    "爬網": ("605", "COVERSTITCH"),
    "爬网": ("605", "COVERSTITCH"),
    "扒網": ("605", "COVERSTITCH"),
    "扒网": ("605", "COVERSTITCH"),
    "四線拷克": ("514", "OVERLOCK"),
    "四线拷克": ("514", "OVERLOCK"),
    "壓明線": ("301", "TOPSTITCH"),
    "压明线": ("301", "TOPSTITCH"),
    "臨邊線": ("301", "TOPSTITCH"),
    "临边线": ("301", "TOPSTITCH"),
    "安全車": ("516", "SAFETY"),
    "安全车": ("516", "SAFETY"),
}

# Secondary method keywords (provide method info but don't map to ISO alone)
ZH_METHOD_KEYWORDS = {
    "壓線": "TOPSTITCH", "压线": "TOPSTITCH",
    "面線": "TOPSTITCH", "面线": "TOPSTITCH",
    "跨壓": "STRADDLE",  "跨压": "STRADDLE",
    "反折": "TURN_BACK", "反摺": "TURN_BACK", "翻折": "TURN_BACK",
    "打結車": "BARTACK", "打结车": "BARTACK",
    "套結": "BARTACK", "套结": "BARTACK",
    "滾邊": "BINDING", "滚边": "BINDING",
    "假包縫": "MOCK_FELLED", "假包缝": "MOCK_FELLED",
    "包縫": "FELLED_SEAM", "包缝": "FELLED_SEAM",
    "車縫": "STITCH", "车缝": "STITCH",
    "底線": "BOBBIN_THREAD", "底线": "BOBBIN_THREAD",
    "包光": "CLEAN_FINISH", "做光": "CLEAN_FINISH",
    "臨邊線": "EDGESTITCH", "临边线": "EDGESTITCH",
    "熱貼合": "BONDED",     "热贴合": "BONDED",
    "雷切邊": "LASER_CUT",  "雷切边": "LASER_CUT",
    "毛邊": "RAW_EDGE",     "毛边": "RAW_EDGE",
}

# ── English ISO extraction regexes ──
VALID_ISOS = {'301', '401', '406', '501', '504', '514', '516', '602', '605', '607'}
ISO_PATTERN = re.compile(r'\b(301|401|406|501|504|514|516|602|605|607)\b')
DEFAULT_ISO_PATTERN = re.compile(r'[Aa]ll\s*body\s*seams\s*are\s*(?:ISO\s*)?(\d{3})', re.I)
DEFAULT_ISO_STAR = re.compile(r'\*\s*ALL\s*BODY\s*SEAMS\s*ARE\s*(?:ISO\s*)?(\d{3})', re.I)
COMBO_PATTERN = re.compile(r'(?:ISO\s*)?(\d{3})\s*\+\s*(?:ISO\s*)?(\d{3})')
ISO_PREFIX_PATTERN = re.compile(r'ISO\s*(\d{3})')
ATH_ISO_PATTERN = re.compile(r'#(\d{3})\s*\d+N\s*\d+TH')
SN_PATTERN = re.compile(r'S/N\s*(?:topstitch|top\s*stitch)', re.I)
DN_PATTERN = re.compile(r'[2D]/N\s*(?:coverstitch|cover\s*stitch)', re.I)

METHOD_TO_ISO = {
    'FLATLOCK': '607', 'COVERSTITCH': '406', 'OVERLOCK': '514',
    'TOPSTITCH': '301', 'BLINDHEM': '103',
}

SKIP_PATTERNS = [
    'Centric 8', 'Production(', 'Page ', 'INWORK', 'IN WORK', 'IN W0RK',
    'Revised', 'APPR0VED', 'APPROVED', 'Adopted', 'Concept', 'BOM Details',
    'Displaying', 'results', 'FFA Date', 'CUT Date', 'FABRIC:', 'VENDOR:',
    'Body:', 'Main fabric', 'RD#', 'Polyester', 'Cotton', 'Spandex',
    'Elastane', 'Denier', 'g/m2', 'PatternName', 'Pattern Name',
    'GRADE', 'Tolerance', 'Fraction',
    'ADDITIONALCOMMENTS', 'ADDITIONAL COMMENTS',
    'PATTERNCORRECTIONS', 'PATTERN CORRECTIONS',
    'NEXTSTEPS', 'NEXT STEPS', 'FITCOMMENTS', 'FIT COMMENTS',
    'FITSAMPLEIMAGES', 'FIT SAMPLE IMAGES',
    'INSPIRATION', 'CONSTRUCTIONVIEWS',
    'Gap Inc', 'GapInc', 'SafetyStandard', 'SoftlinesManual',
    'Consumer', 'Flame', 'CPSC', '--- p',
]


# ══════════════════════════════════════════════════════════════════
# ENGLISH PARSER (for cb, dir5, pdf_extracts)
# ══════════════════════════════════════════════════════════════════

def extract_method_en(line):
    upper = line.upper().replace(' ', '')
    method_map = {
        'COVERSTITCH': 'COVERSTITCH', 'TOPSTITCH': 'TOPSTITCH',
        'UNDERSTITCH': 'UNDERSTITCH', 'BARTACK': 'BARTACK',
        'TURNBACK': 'TURN_BACK', 'SINGLETURN': 'TURN_BACK',
        'BINDING': 'BINDING', 'CLEANFINISH': 'CLEAN_FINISH',
        'FOLDEDEDGE': 'FOLDED_EDGE', 'FOLDEDTOP': 'FOLDED_EDGE',
        'FLATLOCK': 'FLATLOCK', 'OVERLOCK': 'OVERLOCK',
        'ZIGZAG': 'ZIGZAG', 'BLINDHEM': 'BLIND_HEM',
        'ENCASED': 'ENCASED_ELASTIC', 'FREECUT': 'FREE_CUT',
    }
    for kw, method in method_map.items():
        if kw in upper:
            return method
    return None


_sorted_en_cache = {}

def find_zone_en(text, kw_map):
    upper = text.upper().replace(' ', '')
    map_id = id(kw_map)
    if map_id not in _sorted_en_cache:
        _sorted_en_cache[map_id] = sorted(kw_map.items(), key=lambda x: len(x[0]), reverse=True)
    items = _sorted_en_cache[map_id]
    for kw, (code, zh) in items:
        kw_n = kw.replace(' ', '')
        if upper.startswith(kw_n):
            return code, zh
    for kw, (code, zh) in items:
        kw_n = kw.replace(' ', '')
        if kw_n in upper and len(kw_n) >= 4:
            return code, zh
    return None, None


def extract_isos_from_text(text):
    combos = [(a, b) for a, b in COMBO_PATTERN.findall(text) if a in VALID_ISOS and b in VALID_ISOS]
    isos = ISO_PATTERN.findall(text)
    iso_prefixed = ISO_PREFIX_PATTERN.findall(text)
    all_isos = list(set(i for i in isos + iso_prefixed if i in VALID_ISOS))
    return combos, all_isos


def parse_zone_iso_en(all_lines, gt_group):
    """English parser: Parse zone×ISO from English construction text."""
    kw_map = KW_TO_L1_BOTTOMS if gt_group == "BOTTOM" else KW_TO_L1_TOPS
    facts = []
    default_iso = None
    seen = set()

    full_text = '\n'.join(all_lines)

    # Pass 1: default ISO
    for pat in [DEFAULT_ISO_PATTERN, DEFAULT_ISO_STAR]:
        m = pat.search(full_text)
        if m:
            default_iso = m.group(1)
            break

    # Pass 2: normalize
    normalized_lines = []
    for line in all_lines:
        line = line.strip()
        if any(skip in line for skip in SKIP_PATTERNS):
            continue
        if len(line) < 3:
            continue
        normalized_lines.append(line)

    def add_fact(zone_l1, zone_zh, iso, combo, method, confidence, source):
        key = (zone_l1, combo if combo else iso)
        if key in seen: return
        seen.add(key)
        facts.append({
            'zone_zh': zone_zh, 'l1_code': zone_l1, 'iso': iso,
            'combo': combo, 'method': method, 'confidence': confidence,
            'source_line': source[:200],
        })

    # Pass 3: scan with multi-line lookahead
    current_zone_l1 = None
    current_zone_zh = None
    lines_since_zone = 99

    for i, line in enumerate(normalized_lines):
        combos, isos = extract_isos_from_text(line)
        zone_l1, zone_zh = find_zone_en(line, kw_map)

        if zone_l1:
            current_zone_l1 = zone_l1
            current_zone_zh = zone_zh
            lines_since_zone = 0
            if combos or isos:
                method = extract_method_en(line)
                for c in combos:
                    add_fact(zone_l1, zone_zh, None, '+'.join(c), method, 'explicit', line)
                combo_isos = set()
                for c in combos:
                    combo_isos.update(c)
                for iso in isos:
                    if iso not in combo_isos:
                        add_fact(zone_l1, zone_zh, iso, None, method, 'explicit', line)
        elif combos or isos:
            if current_zone_l1 and lines_since_zone <= 3:
                method = extract_method_en(line)
                for c in combos:
                    add_fact(current_zone_l1, current_zone_zh, None, '+'.join(c),
                             method, 'multiline', f'{current_zone_zh}: {line}')
                combo_isos = set()
                for c in combos:
                    combo_isos.update(c)
                for iso in isos:
                    if iso not in combo_isos:
                        add_fact(current_zone_l1, current_zone_zh, iso, None,
                                 method, 'multiline', f'{current_zone_zh}: {line}')
        lines_since_zone += 1

    # Pass 3.5: method→ISO inference
    zones_with_explicit = set(f['l1_code'] for f in facts if f['confidence'] in ('explicit', 'multiline'))
    current_zone_l1 = None
    current_zone_zh = None
    lines_since_zone = 99

    for i, line in enumerate(normalized_lines):
        combos, isos = extract_isos_from_text(line)
        zone_l1, zone_zh = find_zone_en(line, kw_map)
        if zone_l1:
            current_zone_l1 = zone_l1
            current_zone_zh = zone_zh
            lines_since_zone = 0
        if combos or isos:
            lines_since_zone += 1
            continue
        method = extract_method_en(line)
        inferred_iso = None
        m = ATH_ISO_PATTERN.search(line)
        if m:
            inferred_iso = m.group(1)
        elif SN_PATTERN.search(line):
            inferred_iso = '301'
            method = method or 'TOPSTITCH'
        elif DN_PATTERN.search(line):
            inferred_iso = '406'
            method = method or 'COVERSTITCH'
        elif method and method in METHOD_TO_ISO:
            inferred_iso = METHOD_TO_ISO[method]

        if inferred_iso:
            use_zone_l1 = zone_l1 or (current_zone_l1 if lines_since_zone <= 3 else None)
            use_zone_zh = zone_zh or (current_zone_zh if lines_since_zone <= 3 else None)
            if use_zone_l1 and use_zone_l1 not in zones_with_explicit:
                add_fact(use_zone_l1, use_zone_zh, inferred_iso, None,
                         method, 'inferred', f'[method→ISO] {line}')
        lines_since_zone += 1

    # Pass 4: default ISO
    if default_iso:
        add_fact('_DEFAULT', '車縫(通則)', default_iso, None, None,
                 'default_rule', f'All body seams are {default_iso}')

    return facts, default_iso


# ══════════════════════════════════════════════════════════════════
# CHINESE PARSER (for PPTX translations)
# ══════════════════════════════════════════════════════════════════

_sorted_zone_cache = {}

def find_zone_zh(text, zh_zone_map):
    """Find Chinese zone keyword in text. Longest match wins."""
    map_id = id(zh_zone_map)
    if map_id not in _sorted_zone_cache:
        _sorted_zone_cache[map_id] = sorted(zh_zone_map.items(), key=lambda x: len(x[0]), reverse=True)
    for kw, (code, zh) in _sorted_zone_cache[map_id]:
        if kw in text:
            return code, zh
    return None, None


_SORTED_ZH_METHOD_TO_ISO = sorted(ZH_METHOD_TO_ISO.items(), key=lambda x: len(x[0]), reverse=True)
_SORTED_ZH_METHOD_KEYWORDS = sorted(ZH_METHOD_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True)

def extract_method_zh(line):
    """Extract Chinese method keyword and infer ISO. Returns (iso, method_name) or (None, method_name)."""
    # Priority 1: Direct ISO-mapping methods (longest match first)
    for kw, (iso, method) in _SORTED_ZH_METHOD_TO_ISO:
        if kw in line:
            return iso, method

    # Priority 2: Secondary method keywords (no ISO inference)
    for kw, method in _SORTED_ZH_METHOD_KEYWORDS:
        if kw in line:
            return None, method

    return None, None


def parse_zone_iso_zh(all_lines, gt_group):
    """Chinese parser: Parse zone×ISO from Chinese PPTX translation text."""
    zh_zone_map = ZH_ZONE_TO_L1_BOTTOMS if gt_group == "BOTTOM" else ZH_ZONE_TO_L1_TOPS
    facts = []
    seen = set()

    # Also check for any English ISO numbers in mixed-language content
    full_text = '\n'.join(all_lines)

    # Check for English default ISO pattern (sometimes mixed)
    default_iso = None
    for pat in [DEFAULT_ISO_PATTERN, DEFAULT_ISO_STAR]:
        m = pat.search(full_text)
        if m:
            default_iso = m.group(1)
            break

    # Skip non-construction lines
    SKIP_ZH = ['RD', '布', '洗', '水洗', 'Fit', '尺寸', '衬', '扣', '钮', '鈕',
               '线tex', '纽扣线', '線tex', '紐扣線']

    normalized_lines = []
    for line in all_lines:
        line = line.strip()
        if len(line) < 3:
            continue
        # Skip lines that are purely about fabric/trim/buttons
        if any(line.startswith(sk) for sk in SKIP_ZH):
            continue
        normalized_lines.append(line)

    def add_fact(zone_l1, zone_zh, iso, combo, method, confidence, source):
        key = (zone_l1, combo if combo else iso)
        if key in seen: return
        seen.add(key)
        facts.append({
            'zone_zh': zone_zh, 'l1_code': zone_l1, 'iso': iso,
            'combo': combo, 'method': method, 'confidence': confidence,
            'source_line': source[:200],
        })

    current_zone_l1 = None
    current_zone_zh = None
    lines_since_zone = 99

    for line in normalized_lines:
        zone_l1, zone_zh = find_zone_zh(line, zh_zone_map)

        # Check for any English ISOs in this line (mixed content)
        combos, isos = extract_isos_from_text(line)

        # Extract Chinese method
        inferred_iso, method_name = extract_method_zh(line)

        if zone_l1:
            current_zone_l1 = zone_l1
            current_zone_zh = zone_zh
            lines_since_zone = 0

        # Determine which zone to assign facts to
        use_zone_l1 = zone_l1 or (current_zone_l1 if lines_since_zone <= 2 else None)
        use_zone_zh = zone_zh or (current_zone_zh if lines_since_zone <= 2 else None)

        if not use_zone_l1:
            lines_since_zone += 1
            continue

        # Priority 1: explicit English ISO in line
        if combos or isos:
            for c in combos:
                add_fact(use_zone_l1, use_zone_zh, None, '+'.join(c),
                         method_name, 'explicit', line)
            combo_isos = set()
            for c in combos:
                combo_isos.update(c)
            for iso in isos:
                if iso not in combo_isos:
                    add_fact(use_zone_l1, use_zone_zh, iso, None,
                             method_name, 'explicit', line)
        # Priority 2: Chinese method → ISO inference
        elif inferred_iso:
            add_fact(use_zone_l1, use_zone_zh, inferred_iso, None,
                     method_name, 'zh_inferred', line)

        lines_since_zone += 1

    # Add default ISO
    if default_iso:
        add_fact('_DEFAULT', '車縫(通則)', default_iso, None, None,
                 'default_rule', f'All body seams are {default_iso}')

    return facts, default_iso


# ══════════════════════════════════════════════════════════════════
# SOURCE LOADERS
# ══════════════════════════════════════════════════════════════════

def load_source_cb(source_dir):
    """Load construction_by_bucket JSON files. Returns list of (design_data, source_tag)."""
    designs = []
    for bucket_dir in sorted(Path(source_dir).iterdir()):
        if not bucket_dir.is_dir():
            continue
        bucket = bucket_dir.name
        json_dir = bucket_dir / 'json'
        txt_dir = bucket_dir / 'txt'
        if not json_dir.exists():
            continue
        for json_file in sorted(json_dir.glob('*.json')):
            try:
                data = json.loads(json_file.read_text(encoding='utf-8'))
            except Exception as e:
                print(f"[skip] {json_file}: {e}", file=sys.stderr)
                continue
            design_id = data.get('design', json_file.stem)
            pages = data.get('pages', [])
            all_lines = []
            for page in pages:
                tl = page.get('text_lines', [])
                if tl:
                    all_lines.extend(tl)
                elif page.get('raw_text'):
                    all_lines.extend(page['raw_text'].split('\n'))
            # Also try txt file
            txt_file = txt_dir / f'{design_id}.txt'
            if txt_file.exists():
                try:
                    txt_lines = txt_file.read_text(encoding='utf-8', errors='replace').split('\n')
                    all_lines = list(set(all_lines + txt_lines))
                except Exception as e:
                    print(f"[skip] {txt_file}: {e}", file=sys.stderr)
            designs.append({
                'design_id': design_id,
                'desc': data.get('desc', ''),
                'item_type': data.get('item_type', ''),
                'department': data.get('department', '') or data.get('dept', ''),
                'bucket': bucket,
                'year': data.get('year', ''),
                'month': data.get('month', ''),
                'file': data.get('file', ''),
                'status': data.get('status', ''),
                'lines': all_lines,
                'source': 'cb',
                'lang': 'en',
            })
    return designs


def load_source_dir5(source_dir):
    """Load dir5 JSONs (same format as cb)."""
    designs = []
    for json_file in sorted(Path(source_dir).glob('*.json')):
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[skip] {json_file}: {e}", file=sys.stderr)
            continue
        design_id = data.get('design', json_file.stem)
        pages = data.get('pages', [])
        all_lines = []
        for page in pages:
            tl = page.get('text_lines', [])
            if tl:
                all_lines.extend(tl)
            elif page.get('raw_text'):
                all_lines.extend(page['raw_text'].split('\n'))
        designs.append({
            'design_id': design_id,
            'desc': data.get('desc', ''),
            'item_type': data.get('item_type', ''),
            'department': '',
            'bucket': data.get('bucket', 'dir5'),
            'year': '', 'month': '',
            'file': data.get('source_file', ''),
            'status': data.get('status', ''),
            'lines': all_lines,
            'source': 'dir5',
            'lang': 'en',
        })
    return designs


def load_source_pptx_txt(source_dir):
    """Load PPTX raw txt files (Chinese construction translations)."""
    designs = {}  # design_id → merged lines
    for txt_file in sorted(Path(source_dir).glob('*.txt')):
        fname = txt_file.name
        m = re.search(r'D(\d+)', fname)
        if not m:
            continue
        design_id = f'D{m.group(1)}'
        try:
            text = txt_file.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            print(f"[skip] {txt_file}: {e}", file=sys.stderr)
            continue

        # Check if this file has Chinese construction content
        # Include BOTH method keywords AND zone+method combos
        has_zh_construction = bool(re.search(
            r'壓[線线缝縫]|雙[針针]|單[針针]|拷克|併[縫缝]|車[縫缝]|面[線线]|三本|反[折摺]|打[結结][車车]|跨[壓压]|套[結结]|暗[縫缝]|平[車车]|人字[車车带]|[滾滚][邊边]|假包[縫缝]',
            text))
        has_en_construction = bool(re.search(
            r'COVERSTITCH|FLATLOCK|OVERLOCK|TOPSTITCH|body seams|ISO\s*\d{3}',
            text, re.I))

        if not has_zh_construction and not has_en_construction:
            continue  # skip non-construction files (measurement tables, etc.)

        lines = [l.strip() for l in text.split('\n') if l.strip()]

        if design_id not in designs:
            designs[design_id] = {
                'design_id': design_id,
                'desc': '',
                'item_type': '',
                'department': '',
                'bucket': '',
                'year': '', 'month': '',
                'file': fname,
                'status': '',
                'lines': [],
                'source': 'pptx',
                'lang': 'zh' if has_zh_construction else 'en',
                'all_files': [],
            }
        # Cap lines per design to prevent memory issues
        if len(designs[design_id]['lines']) < 2000:
            designs[design_id]['lines'].extend(lines)
        designs[design_id]['all_files'].append(fname)

        # Try to extract bucket/item_type from filename
        if not designs[design_id]['bucket']:
            # Pattern: 2025_FA25_D40042_... → season = FA25
            season_m = re.search(r'20\d\d_([A-Z]{2}\d\d)', fname)
            if season_m:
                designs[design_id]['bucket'] = season_m.group(1)

    return list(designs.values())


def load_source_pptx_json(json_paths):
    """Load structured pptx_translations JSON files."""
    designs = {}
    for json_path in json_paths:
        if not os.path.exists(json_path):
            continue
        data = json.loads(Path(json_path).read_text(encoding='utf-8'))
        for design_id, info in data.items():
            lines = []
            for slide in info.get('construction_slides', []):
                text = slide.get('text', '')
                lines.extend([l.strip() for l in text.split('\n') if l.strip()])
            if not lines:
                continue
            if design_id not in designs:
                designs[design_id] = {
                    'design_id': design_id,
                    'desc': '',
                    'item_type': '',
                    'department': '',
                    'bucket': '',
                    'year': '', 'month': '',
                    'file': info.get('file', ''),
                    'status': '',
                    'lines': [],
                    'source': 'pptx_json',
                    'lang': 'zh',
                }
            designs[design_id]['lines'].extend(lines)
    return list(designs.values())


def load_source_pdf_extracts(source_dir):
    """Load PDF per-page txt extracts (English)."""
    designs = {}
    for txt_file in sorted(Path(source_dir).rglob('*.txt')):
        fname = txt_file.name
        m = re.search(r'(D\d{3,6})', fname)
        if not m:
            continue
        design_id = m.group(1)
        # Skip overly large files (>500KB) - likely not construction
        if txt_file.stat().st_size > 500_000:
            continue
        try:
            text = txt_file.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            print(f"[skip] {txt_file}: {e}", file=sys.stderr)
            continue

        # Only keep files with construction content
        has_construction = bool(re.search(
            r'COVERSTITCH|FLATLOCK|OVERLOCK|TOPSTITCH|body seams|ISO\s*\d{3}|\b(301|406|514|607)\b',
            text, re.I))
        if not has_construction:
            continue

        lines = [l.strip() for l in text.split('\n') if l.strip()]

        if design_id not in designs:
            designs[design_id] = {
                'design_id': design_id,
                'desc': '',
                'item_type': '',
                'department': '',
                'bucket': '',
                'year': '', 'month': '',
                'file': '',
                'status': '',
                'lines': [],
                'source': 'ocr',
                'lang': 'en',
            }
        # Cap lines per design to prevent memory issues (PDF can have 10K+ lines)
        if len(designs[design_id]['lines']) < 3000:
            designs[design_id]['lines'].extend(lines)

        # Try to extract GT from header
        gt_m = re.search(r'^GT:\s*(\w+)', text, re.M)
        if gt_m and not designs[design_id]['item_type']:
            designs[design_id]['item_type'] = gt_m.group(1)

    return list(designs.values())


# ══════════════════════════════════════════════════════════════════
# UNIFIED PIPELINE
# ══════════════════════════════════════════════════════════════════

def load_gt_backfill(classification_file: str | None = None):
    """Load external GT classification to resolve UNKNOWN designs.

    If `classification_file` is provided, load that one file. Otherwise, try
    the repo's runtime + legacy fallback paths. Missing files are silently
    skipped.
    """
    gt_map = {}  # design_id → {gt, item_type, dept, desc, ...}

    candidates = []
    if classification_file:
        candidates.append(classification_file)
    else:
        _script_dir = Path(__file__).resolve().parent
        _repo_root = _script_dir.parent.parent  # star_schema/scripts/../../ = repo root
        candidates.append(str(_repo_root / "data" / "runtime" / "all_designs_gt_it_classification.json"))
        candidates.append(str(_repo_root / "data" / "legacy" / "all_designs_gt_it_classification.json"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        for did, info in data.items():
            if did.upper() not in gt_map:
                gt_map[did.upper()] = info

    return gt_map


def _build_bucket_from_metadata(department: str, sub_category: str, brand_division: str) -> str:
    """Build a bucket name from PDF metadata fields.

    Maps Centric 8 department/sub_category to our bucket format:
      e.g. "WOMENS PERFORMANCE ACTIVE" + "PERFORMANCE BOTTOMS"
           → "womens_perf_bottoms"

    Returns empty string if cannot determine.
    """
    dept = department.upper()
    sub = sub_category.upper()
    brand = brand_division.upper()

    # Extract gender from department or brand
    gender = ""
    for g in ["WOMENS", "MENS", "GIRLS", "BOYS", "TODDLER", "NEWBORN", "BABY", "MATERNITY"]:
        if g in dept or g in brand:
            gender = g.lower()
            break
    if not gender:
        return ""

    # Normalize gender
    if gender in ("baby", "toddler"):
        gender = "toddler"

    # Extract product category from sub_category or department
    cat = ""
    # Map known sub-categories
    SUB_MAP = {
        "PERFORMANCE BOTTOMS": "perf_bottoms",
        "PERFORMANCE TOPS": "perf_tops",
        "PERFORMANCE OUTERWEAR": "perf_outer",
        "PERFORMANCE DRESS": "perf_dress",
        "PERFORMANCE SET": "perf_set",
        "KNIT TOPS": "knit_tops",
        "KNIT BOTTOMS": "knit_bottoms",
        "WOVEN TOPS": "woven_tops",
        "WOVEN BOTTOMS": "woven_bottoms",
        "WOVEN DRESS": "woven_dress",
        "FLEECE TOPS": "fleece_tops",
        "FLEECE BOTTOMS": "fleece_bottoms",
        "FLEECE OUTERWEAR": "fleece_outer",
        "FLEECE SET": "fleece_set",
        "SWIMWEAR": "swim",
        "SLEEP": "sleep",
        "DRESS": "dress",
    }
    for pattern, bucket_cat in SUB_MAP.items():
        if pattern in sub:
            cat = bucket_cat
            break

    # Fallback: try department keywords
    if not cat:
        DEPT_MAP = {
            "PERFORMANCE ACTIVE": "perf",
            "ACTIVE/FLEECE": "fleece",
            "FLEECE": "fleece",
            "SLEEP": "sleep",
            "SWIM": "swim",
            "WOVEN": "woven",
            "KNIT": "knit",
            "DRESS": "dress",
        }
        for pattern, dept_cat in DEPT_MAP.items():
            if pattern in dept:
                cat = dept_cat
                break

    # Fallback: try category field (e.g. "KNIT BOTTOMS", "PERFORMANCE TOPS")
    if not cat:
        category = sub.strip()  # sub_category was already checked via SUB_MAP
        # Try raw category from PDF (sometimes has "KNIT BOTTOMS Tech Pack..." junk)
        CAT_MAP = {
            "KNIT BOTTOM": "knit_bottoms", "KNIT TOP": "knit_tops",
            "PERFORMANCE BOTTOM": "perf_bottoms", "PERFORMANCE TOP": "perf_tops",
            "PERFORMANCE 3RD": "perf_outer", "PERFORMANCE DRESS": "perf_dress",
            "WOVEN BOTTOM": "woven_bottoms", "WOVEN TOP": "woven_tops",
            "WOVEN DRESS": "woven_dress",
            "FLEECE": "fleece", "SWIM": "swim", "SLEEP": "sleep",
        }
        for pattern, cat_val in CAT_MAP.items():
            if pattern in category or pattern in dept:
                cat = cat_val
                break

    if not cat:
        return ""

    # Handle partial categories (need bottoms/tops suffix)
    if cat in ("perf", "fleece", "woven", "knit"):
        # Try to infer from sub_category
        if "BOTTOM" in sub or "PANT" in sub or "SHORT" in sub or "LEGGING" in sub:
            cat += "_bottoms"
        elif "TOP" in sub or "TEE" in sub or "SHIRT" in sub or "TANK" in sub:
            cat += "_tops"
        elif "DRESS" in sub:
            cat += "_dress"
        elif "OUTER" in sub or "JACKET" in sub or "HOODIE" in sub:
            cat += "_outer"
        elif "SET" in sub:
            cat += "_set"
        else:
            # Can't determine, use as-is
            pass

    return f"{gender}_{cat}"


def process_unified(output_dir, ingest_dir=None, classification_file=None,
                    legacy_pptx_json_dir=None):
    """Load all sources, parse, merge, output unified dim + facts.

    Args:
      output_dir: where to write dim.jsonl + facts.jsonl (e.g. data/ingest/unified)
      ingest_dir: Step 1 output root (reads metadata/, pptx/). Default: output_dir.parent
      classification_file: optional external GT backfill JSON path
      legacy_pptx_json_dir: optional legacy PPTX JSON directory (structured translations)
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # INGEST_ROOT: where Step 1 placed metadata/, pptx/, pdf/
    # Default: the parent of output_dir (legacy invocation where out == INGEST_ROOT/unified)
    INGEST_ROOT = Path(ingest_dir) if ingest_dir else out.parent

    # ── Load PDF metadata (D-number → dept/category/brand) ──
    pdf_metadata = {}  # design_id → {department, category, sub_category, ...}
    meta_path = INGEST_ROOT / "metadata" / "designs.jsonl"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    did = row.get("design_id", "").upper()
                    if did:
                        pdf_metadata[did] = row
        print(f"PDF metadata loaded: {len(pdf_metadata)} designs")
    else:
        print(f"PDF metadata not found at {meta_path} — run extract_raw_text.py --metadata-only first")

    # ── Load GT backfill data ──
    gt_backfill = load_gt_backfill(classification_file)
    print(f"GT backfill data: {len(gt_backfill)} designs")

    # ── Load PPTX sources from ingest/pptx/ ──
    print("Loading sources...")

    pptx_dir = str(INGEST_ROOT / "pptx")
    src_pptx_txt = load_source_pptx_txt(pptx_dir)
    print(f"  pptx_txt:  {len(src_pptx_txt)} designs (from {pptx_dir})")

    # Legacy structured JSON (opt-in via --legacy-pptx-json-dir)
    src_pptx_json = []
    if legacy_pptx_json_dir:
        _legacy = Path(legacy_pptx_json_dir)
        if _legacy.exists():
            src_pptx_json = load_source_pptx_json([
                str(_legacy / "pptx_translations.json"),
                str(_legacy / "pptx_translations_batch2.json"),
            ])
    print(f"  pptx_json: {len(src_pptx_json)} designs")

    # PDF construction goes through VLM pipeline
    # (vlm_pipeline.py → ingest/vlm/facts.jsonl), merged below.

    # ── Merge by design_id (priority: pptx_json > pptx_txt) ──
    # For dim metadata: use highest-priority source
    # For facts: extract from ALL sources, tag with source

    all_designs = {}  # design_id → {dim, lines_by_source}
    source_priority = [
        ('pptx_json', src_pptx_json),
        ('pptx', src_pptx_txt),
    ]

    for src_name, src_list in source_priority:
        for d in src_list:
            did = d['design_id'].upper()
            if did not in all_designs:
                all_designs[did] = {
                    'dim': {
                        'design_id': did,
                        'desc': d['desc'],
                        'item_type': d['item_type'],
                        'department': d['department'],
                        'bucket': d['bucket'],
                        'year': d['year'],
                        'month': d['month'],
                        'file': d['file'],
                        'status': d['status'],
                        'sources': [],
                    },
                    'lines_by_source': {},
                }
            entry = all_designs[did]
            # Fill in missing dim fields from lower-priority sources
            for field in ['desc', 'item_type', 'department', 'bucket', 'year', 'month']:
                if not entry['dim'][field] and d.get(field):
                    entry['dim'][field] = d[field]
            entry['dim']['sources'].append(src_name)
            entry['lines_by_source'][src_name] = {
                'lines': d['lines'],
                'lang': d['lang'],
            }

    # ── Join PDF metadata by D-number ──
    # PDF metadata has department, category, sub_category, brand, design_type
    # PPTX sources don't have these → join by D-number to fill bucket
    meta_joined = 0
    for did, entry in all_designs.items():
        dim = entry['dim']
        if did in pdf_metadata:
            pm = pdf_metadata[did]
            if not dim['department'] and pm.get('department'):
                dim['department'] = pm['department']
            if not dim['item_type'] and pm.get('design_type'):
                dim['item_type'] = pm['design_type']
            if not dim['desc'] and pm.get('design_name'):
                dim['desc'] = pm['design_name']
            # Build bucket from department + sub_category
            if not dim['bucket'] or dim['bucket'] in ('', 'FA25', 'FA26', 'SP25', 'SP26', 'SU25', 'SU26', 'HO25', 'HO26', 'SP27'):
                dept = pm.get('department', '')
                sub_cat = pm.get('sub_category', '')
                brand = pm.get('brand_division', '')
                # Build bucket: normalize dept to gender_category format
                bucket = _build_bucket_from_metadata(dept, sub_cat, brand)
                if bucket:
                    dim['bucket'] = bucket
                    meta_joined += 1
    print(f"  PDF metadata joined: {meta_joined} designs got bucket")

    # ── Backfill GT and metadata from classification data ──
    GT_TO_GROUP = {
        'TOP': 'TOP', 'DRESS': 'TOP', 'OUTERWEAR': 'TOP',
        'ROMPER_JUMPSUIT': 'TOP', 'SET': 'TOP', 'BODYSUIT': 'TOP',
        'BOTTOM': 'BOTTOM', 'PANTS': 'BOTTOM', 'PANT': 'BOTTOM',
        'LEGGINGS': 'BOTTOM', 'SHORTS': 'BOTTOM', 'SKIRT': 'BOTTOM',
    }
    gt_filled = 0
    for did, entry in all_designs.items():
        dim = entry['dim']
        if did in gt_backfill:
            bf = gt_backfill[did]
            if not dim['item_type'] and bf.get('item_type'):
                dim['item_type'] = bf['item_type']
            if not dim['department'] and bf.get('dept'):
                dim['department'] = bf['dept']
            if not dim['desc'] and bf.get('description'):
                dim['desc'] = bf['description']
            if bf.get('gt'):
                gt_raw = bf['gt'].upper()
                if gt_raw in GT_TO_GROUP:
                    dim['_backfill_gt'] = GT_TO_GROUP[gt_raw]
                    gt_filled += 1
    print(f"  GT backfilled: {gt_filled} designs")

    print(f"\n  MERGED: {len(all_designs)} unique designs")

    # ── Extract facts from all sources ──
    print("\nExtracting facts...")
    dim_records = []
    fact_records = []

    stats = {
        'total_designs': len(all_designs),
        'designs_with_facts': 0,
        'total_facts': 0,
        'designs_with_default_iso': 0,
        'gt_distribution': defaultdict(int),
        'source_contribution': defaultdict(lambda: {'designs': 0, 'facts': 0}),
        'zone_distribution': defaultdict(int),
        'iso_distribution': defaultdict(int),
        'confidence_distribution': defaultdict(int),
    }

    for did in sorted(all_designs.keys()):
        entry = all_designs[did]
        dim_data = entry['dim']

        gt_group = classify_gt(dim_data['item_type'], dim_data['bucket'])
        # Use backfill GT if classify_gt returns UNKNOWN
        if gt_group == 'UNKNOWN' and dim_data.get('_backfill_gt'):
            gt_group = dim_data['_backfill_gt']
        dim_data['gt_group'] = gt_group
        dim_data.pop('_backfill_gt', None)  # remove temp field
        stats['gt_distribution'][gt_group] += 1
        dim_records.append(dim_data)

        # Collect facts from ALL sources for this design
        design_facts = []
        design_seen = set()  # (l1_code, iso/combo) dedup across sources
        has_default_iso = False

        for src_name, src_data in entry['lines_by_source'].items():
            lines = src_data['lines']
            lang = src_data['lang']

            if not lines:
                continue

            # Choose parser based on language
            if lang == 'zh':
                facts, default_iso = parse_zone_iso_zh(lines, gt_group)
            else:
                facts, default_iso = parse_zone_iso_en(lines, gt_group)

            if default_iso:
                has_default_iso = True

            for f in facts:
                key = (f['l1_code'], f.get('combo') or f.get('iso'))
                if key in design_seen:
                    continue
                design_seen.add(key)
                f['design_id'] = did
                f['bucket'] = dim_data['bucket']
                f['gt_group'] = gt_group
                f['source'] = src_name
                design_facts.append(f)

            if facts:
                stats['source_contribution'][src_name]['designs'] += 1
                stats['source_contribution'][src_name]['facts'] += len([
                    f for f in facts if (f['l1_code'], f.get('combo') or f.get('iso')) in design_seen
                ])

        if design_facts:
            stats['designs_with_facts'] += 1
            stats['total_facts'] += len(design_facts)
            fact_records.extend(design_facts)

            for f in design_facts:
                stats['zone_distribution'][f['zone_zh']] += 1
                stats['confidence_distribution'][f['confidence']] += 1
                if f.get('iso'):
                    stats['iso_distribution'][f['iso']] += 1
                if f.get('combo'):
                    stats['iso_distribution'][f'combo:{f["combo"]}'] += 1

        if has_default_iso:
            stats['designs_with_default_iso'] += 1

    # ── Merge VLM facts (from ingest/vlm/facts.jsonl) ──
    # VLM facts come from a separate pipeline (PDF → PNG → VLM).
    # Merge here with D-number dedup: PPTX wins on same (design, l1, iso).
    # Also apply PDF metadata to VLM facts that have stale/missing bucket.
    vlm_path = INGEST_ROOT / "vlm" / "facts.jsonl"
    # Also check master backup
    if not vlm_path.exists():
        vlm_path = INGEST_ROOT / "vlm" / "ocr_facts_master.jsonl"
    vlm_merged = 0
    vlm_skipped_dup = 0
    if vlm_path.exists():
        # Build dedup set from PPTX facts
        pptx_keys = set()
        for f in fact_records:
            pptx_keys.add((f['design_id'], f['l1_code'], f.get('iso') or f.get('combo', '')))

        with open(vlm_path, encoding='utf-8') as vf:
            for line in vf:
                if not line.strip():
                    continue
                row = json.loads(line)
                did = row.get('design_id', '').upper()
                l1 = row.get('l1_code', '')
                iso = row.get('iso', '') or row.get('combo', '')
                key = (did, l1, iso)

                if key in pptx_keys:
                    vlm_skipped_dup += 1
                    continue

                # Apply PDF metadata to fill/update bucket
                if did in pdf_metadata:
                    pm = pdf_metadata[did]
                    dept = pm.get('department', '')
                    sub_cat = pm.get('sub_category', '')
                    brand = pm.get('brand_division', '')
                    new_bucket = _build_bucket_from_metadata(dept, sub_cat, brand)
                    if new_bucket:
                        row['bucket'] = new_bucket

                row['design_id'] = did  # normalize to uppercase
                fact_records.append(row)
                pptx_keys.add(key)
                vlm_merged += 1

                # Update stats
                stats['total_facts'] += 1
                if row.get('zone_zh'):
                    stats['zone_distribution'][row['zone_zh']] += 1
                if row.get('iso'):
                    stats['iso_distribution'][row['iso']] += 1

        # Count VLM-only designs
        vlm_design_ids = set()
        for f in fact_records:
            if f.get('source') == 'ocr':
                vlm_design_ids.add(f['design_id'])
        pptx_design_ids = set()
        for f in fact_records:
            if f.get('source') in ('pptx', 'pptx_json'):
                pptx_design_ids.add(f['design_id'])
        vlm_only = vlm_design_ids - pptx_design_ids

        print(f"\n  VLM facts merged: {vlm_merged} (skipped {vlm_skipped_dup} dups)")
        print(f"  VLM-only designs (no PPTX): {len(vlm_only)}")
        stats['designs_with_facts'] += len(vlm_only)

    # ── Write outputs ──
    dim_path = out / 'dim.jsonl'
    facts_path = out / 'facts.jsonl'

    with open(dim_path, 'w', encoding='utf-8') as f:
        for d in dim_records:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')

    with open(facts_path, 'w', encoding='utf-8') as f:
        for fact in fact_records:
            f.write(json.dumps(fact, ensure_ascii=False) + '\n')

    # ── Print stats ──
    print(f"\n{'='*60}")
    print(f"UNIFIED EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Unique designs:        {stats['total_designs']}")
    print(f"Designs with facts:    {stats['designs_with_facts']} ({stats['designs_with_facts']*100//max(1,stats['total_designs'])}%)")
    print(f"Designs with default:  {stats['designs_with_default_iso']}")
    print(f"Total facts extracted: {stats['total_facts']}")
    print(f"Avg facts/design:      {stats['total_facts']/max(1,stats['designs_with_facts']):.1f}")

    print(f"\n--- Source Contribution ---")
    for src, st in sorted(stats['source_contribution'].items()):
        print(f"  {src}: {st['designs']} designs contributed facts")

    print(f"\n--- GT Distribution ---")
    for gt, n in sorted(stats['gt_distribution'].items()):
        print(f"  {gt}: {n}")

    print(f"\n--- Confidence Distribution ---")
    for conf, n in sorted(stats['confidence_distribution'].items(), key=lambda x: -x[1]):
        print(f"  {conf}: {n}")

    print(f"\n--- Zone Distribution (top 20) ---")
    for zone, n in sorted(stats['zone_distribution'].items(), key=lambda x: -x[1])[:20]:
        print(f"  {zone}: {n}")

    print(f"\n--- ISO Distribution ---")
    for iso, n in sorted(stats['iso_distribution'].items(), key=lambda x: -x[1]):
        print(f"  {iso}: {n}")

    print(f"\nOutput:")
    print(f"  dim:   {dim_path} ({len(dim_records)} rows)")
    print(f"  facts: {facts_path} ({len(fact_records)} rows)")

    return stats


def main():
    p = argparse.ArgumentParser(
        description="Unified multi-source extraction — merge PPTX/PDF/CB/DIR5 into dim+facts")
    p.add_argument("--ingest-dir", default=None,
                   help="Step 1 output root (預設: <repo_root>/data/ingest/)")
    p.add_argument("--out", default=None,
                   help="Unified 輸出目錄 (預設: {ingest-dir}/unified)")
    p.add_argument("--classification-file", default=None,
                   help="Optional GT backfill JSON (all_designs_gt_it_classification.json)")
    p.add_argument("--legacy-pptx-json-dir", default=None,
                   help="Optional legacy PPTX JSON dir (Source-Data/ONY/_parsed)")
    args = p.parse_args()

    ingest_dir = args.ingest_dir or default_ingest_dir()
    out_dir = args.out or str(Path(ingest_dir) / "unified")

    print(f"Ingest:  {ingest_dir}")
    print(f"Out:     {out_dir}")
    if args.classification_file:
        print(f"GT backfill: {args.classification_file}")
    if args.legacy_pptx_json_dir:
        print(f"Legacy PPTX JSON: {args.legacy_pptx_json_dir}")
    print()

    process_unified(
        out_dir,
        ingest_dir=ingest_dir,
        classification_file=args.classification_file,
        legacy_pptx_json_dir=args.legacy_pptx_json_dir,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
