"""zone_resolver.py — 從 data/zone_glossary.json 載字典 + 提供 zone/method helpers

唯一 source of truth。star_schema 跟 M7_Pipeline 都應 import 這份。
改字典只改 zone_glossary.json，不要改 .py。

Public API:
  L1_STANDARD_38, ZH_TO_L1, VALID_ISOS, ISO_RE,
  ISO_TO_ZH_METHOD, METHOD_EN_TO_ISO,
  KW_TO_L1_BOTTOMS,
  GAUGE_RE, IE_NON_SEWING_KEYWORDS, ISO_TO_IE_KEYWORDS,
  find_zone_en(text, kw_map) -> (l1, zh) | None
  find_all_zones_en(text, kw_map) -> list[(l1, zh)]
  extract_gauge(line) -> str | None
  enrich_method_zh(method_en, iso, combo, line) -> str
"""
import json
import re
from pathlib import Path

# ── load 字典 ──────────────────────────────────────
_GLOSSARY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "zone_glossary.json"
if not _GLOSSARY_PATH.exists():
    raise RuntimeError(f"zone_glossary.json not found at {_GLOSSARY_PATH}")

with open(_GLOSSARY_PATH, encoding="utf-8") as _f:
    _G = json.load(_f)

L1_STANDARD_38 = _G["L1_STANDARD_38"]
ZH_TO_L1 = {v: k for k, v in L1_STANDARD_38.items()}
VALID_ISOS = set(_G["VALID_ISOS"])
ISO_TO_ZH_METHOD = _G["ISO_TO_ZH_METHOD"]
METHOD_EN_TO_ISO = _G["METHOD_EN_TO_ISO"]
# JSON 存成 list (可序列化)，這裡轉回 tuple (Python idiomatic)
KW_TO_L1_BOTTOMS = {k: tuple(v) for k, v in _G["KW_TO_L1_BOTTOMS"].items()}
IE_NON_SEWING_KEYWORDS = _G["IE_NON_SEWING_KEYWORDS"]
ISO_TO_IE_KEYWORDS = _G["ISO_TO_IE_KEYWORDS"]

# ── regexes ──────────────────────────────────────
ISO_RE = re.compile(r"\b(" + "|".join(sorted(VALID_ISOS)) + r")\b")

GAUGE_RE = re.compile(
    r'(\d+(?:/\d+)?)\s*"\s*(?:GG|GAUGE)\b'
    r'|(\d+(?:/\d+)?)\s*INCH\s*(?:GG|GAUGE)\b'
    r'|\b(\d+(?:/\d+)?)\s*GG\b',
    re.I
)

# ── helpers ──────────────────────────────────────
_sorted_kw_cache = {}


def find_zone_en(text, kw_map):
    """英文 zone keyword → (L1 code, zone_zh)。
    normalize 砍非英數字（"W/B SEAM:" → "WBSEAM"）後 dict lookup。
    沒中 return None。"""
    upper = re.sub(r'[^A-Z0-9]+', '', text.upper())
    mid = id(kw_map)
    if mid not in _sorted_kw_cache:
        _sorted_kw_cache[mid] = sorted(kw_map.items(), key=lambda x: len(x[0]), reverse=True)
    items = _sorted_kw_cache[mid]
    for kw, val in items:
        kw_n = re.sub(r'[^A-Z0-9]+', '', kw)
        if upper.startswith(kw_n):
            return val
    for kw, val in items:
        kw_n = re.sub(r'[^A-Z0-9]+', '', kw)
        if kw_n in upper and len(kw_n) >= 4:
            return val
    return None


def find_all_zones_en(text, kw_map):
    """切多 zone：'RISE/OUTSEAM/INSEAM' → [(RS,褲襠), (SS,脅邊), (PS,褲合身)]。
    切 / & + , AND OR；保護 'W/B SEAM' 等縮寫：切後 <2 zone 就 fallback 整段查。"""
    head = text.split(':', 1)[0]
    parts = re.split(r'\s*[/&+,]\s*|\s+AND\s+|\s+OR\s+', head, flags=re.IGNORECASE)
    zones_split = []
    seen_codes = set()
    for p in parts:
        p = p.strip()
        if len(p) < 2:
            continue
        val = find_zone_en(p, kw_map)
        if val and val[0] not in seen_codes:
            zones_split.append(val)
            seen_codes.add(val[0])
    if len(zones_split) >= 2:
        return zones_split
    val = find_zone_en(head, kw_map)
    return [val] if val else []


def extract_gauge(line):
    """抽 gauge 字串如 1/8" GG → '1/8\"'。沒抽到回 None。"""
    m = GAUGE_RE.search(line)
    if not m:
        return None
    val = next((g for g in m.groups() if g), None)
    return f'{val}"' if val else None


def enrich_method_zh(method_en, iso, combo, line):
    """組裝 ZH method 字串（Style Guide 規格）：
       combo 514+605 → '四線拷克 + 三針五線爬網(514+605), 1/8" 間距'
       iso 406        → '三本雙針(406), 1/8" 間距'
       沒 ISO 但有 method_en → 從 METHOD_EN_TO_ISO 反查補 ISO 再套 ZH
       完全 fallback → 維持原 method_en
    """
    parts = []
    # 沒 ISO 沒 combo 但有 method_en → 反查補 ISO
    if not iso and not combo and method_en:
        inferred_iso = METHOD_EN_TO_ISO.get(method_en)
        if inferred_iso:
            iso = inferred_iso
    if combo:
        codes = combo.split('+')
        names = [ISO_TO_ZH_METHOD[c] for c in codes if c in ISO_TO_ZH_METHOD]
        if len(names) == len(codes):
            parts.append(f'{" + ".join(names)}({combo})')
    elif iso and iso in ISO_TO_ZH_METHOD:
        parts.append(f'{ISO_TO_ZH_METHOD[iso]}({iso})')
    if not parts:
        return method_en
    gauge = extract_gauge(line)
    if gauge:
        parts.append(f'{gauge} 間距')
    return ', '.join(parts)


# ── self-test on module import ──────────────────────────────────────
if __name__ == "__main__":
    print(f"[zone_resolver] loaded from {_GLOSSARY_PATH}")
    print(f"  L1_STANDARD_38:  {len(L1_STANDARD_38)} entries")
    print(f"  VALID_ISOS:      {sorted(VALID_ISOS)}")
    print(f"  KW_TO_L1_BOTTOMS:{len(KW_TO_L1_BOTTOMS)} entries")
    print(f"  ISO_TO_ZH_METHOD:{len(ISO_TO_ZH_METHOD)} entries")
    print()
    # quick smoke
    print("Smoke:")
    print(f"  find_zone_en('W/B SEAM:'): {find_zone_en('W/B SEAM:', KW_TO_L1_BOTTOMS)}")
    print(f"  find_all_zones_en('RISE, OUTSEAM, INSEAM:'):"
          f" {find_all_zones_en('RISE, OUTSEAM, INSEAM:', KW_TO_L1_BOTTOMS)}")
    print(f"  enrich_method_zh('TOPSTITCH', None, None, ''):"
          f" {enrich_method_zh('TOPSTITCH', None, None, '')}")
    print(f"  enrich_method_zh(None, '406', None, '1/8 GG'):"
          f" {enrich_method_zh(None, '406', None, '1/8 GG')}")
