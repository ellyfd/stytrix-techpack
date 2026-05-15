"""consolidate_canonical.py — 8 canonical 欄位 multi-source consensus

把 build_m7_pullon_source_v3.py 第 156-230 行的 consolidate_fabric() 抽成 generic,
8 canonical (客戶/報價款號/Program/Subgroup/W/K/Item/Season/PRODUCT_CATEGORY) 共用。

Source priority:
  - M7 列管 (聚陽 nt-net2 內部)        weight 3 (primary, 100% coverage)
  - PDF cover metadata (客戶端視角)     weight 2 (cross-check, 24-100% coverage)
  - 推論 (檔名 / derive_*) / hint        weight 1 (fallback)

Confidence rule:
  - M7 列管 有值 + 跟 consensus 一致      → "high"
  - M7 列管 有值 但跟 PDF 不一致           → "medium" (衝突已標記,可人工 audit)
  - 沒 M7 列管 但 >= 2 source 同意         → "medium"
  - 只有 1 個 source 或全空                → "low" / "none"

5/8+ 加:Alias normalize layer
  - 載入 data/canonical_aliases.json
  - 各 source value 在 voting 前先過 alias mapping (eg WOMEN→WOMENS, GAP OUTLET→GO,
    Fall 2025 → FA25 等)
  - 把「命名差異 medium」降為「真實衝突 medium」
"""
from __future__ import annotations
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

_ALIASES_CACHE = None


def _find_aliases_path():
    """canonical_aliases.json SOT = stytrix-techpack/data/source/canonical_aliases.json
    (2026-05-15: 原讀 M7_Pipeline/data/canonical_aliases.json 副本，已刪，改讀 repo SOT)。
    候選順序：M7_Pipeline-in-repo / C:\\temp 固定 repo 位置 / 舊本地 copy（過渡 fallback）。"""
    m7 = Path(__file__).resolve().parent.parent.parent  # M7_Pipeline/
    for c in (m7.parent / "data" / "source" / "canonical_aliases.json",
              Path("C:/temp/stytrix-techpack/data/source/canonical_aliases.json"),
              m7 / "data" / "canonical_aliases.json"):
        if c.exists():
            return c
    return m7 / "data" / "canonical_aliases.json"  # last-resort default（_load_aliases 會 graceful 退空 dict）


def _load_aliases():
    """載入 canonical_aliases.json (cached);找不到就用空 dict"""
    global _ALIASES_CACHE
    if _ALIASES_CACHE is not None:
        return _ALIASES_CACHE
    path = _find_aliases_path()
    if path.exists():
        try:
            _ALIASES_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _ALIASES_CACHE = {}
    else:
        _ALIASES_CACHE = {}
    return _ALIASES_CACHE


# Season format normalize patterns (regex,不能放 JSON)
_SEASON_NAME_MAP = {
    "FALL": "FA", "HOLIDAY": "HO", "SUMMER": "SU", "SPRING": "SP",
    "WINTER": "WI", "AUTUMN": "FA",
}


def _normalize_season(value: str) -> str:
    """Season format → 統一 SS/FA/HO/SP/WI/FW + YY (2 digits)"""
    if not isinstance(value, str):
        return value
    v = value.strip()
    if not v:
        return v

    # "Fall 2025" / "Holiday 2026" / "Summer 2026" / etc.
    m = re.match(r"^(Fall|Holiday|Summer|Spring|Winter|Autumn)\s+(\d{4})$", v, re.I)
    if m:
        return _SEASON_NAME_MAP[m.group(1).upper()] + m.group(2)[2:]
    # "V-FA 2025" / "B-FA 2025" / "B-SP 2026" — M7 內部碼 (V/B = 客戶 sub-segment)
    m = re.match(r"^[A-Z]-(FA|SP|SU|HO|WI|FW|SS|AW)\s+(\d{4})$", v)
    if m:
        return m.group(1) + m.group(2)[2:]
    # "2025FW" / "2026SS" / "2026SP"
    m = re.match(r"^(\d{4})(SS|FW|FA|SP|SU|HO|AW)$", v)
    if m:
        return m.group(2) + m.group(1)[2:]
    # "Softlines - Athletic Boy's - Fall - 2026" (DICKS 帶分隔符) — 抽 Fall + 4digit year
    m = re.search(r"-\s*(Fall|Holiday|Summer|Spring|Winter|Autumn)\s*-\s*(\d{4})", v, re.I)
    if m:
        return _SEASON_NAME_MAP[m.group(1).upper()] + m.group(2)[2:]
    # "C126" / "C326" (TARGET 已是 normalized form) — 直接接受
    m = re.match(r"^C(\d)(\d{2})$", v)
    if m:
        return v
    # "FA25" / "HO26" 等已 normalized
    m = re.match(r"^(SS|FW|FA|SP|SU|HO|WI|AW)\d{2}$", v)
    if m:
        return v
    return v


def _normalize_style_no(value: str) -> str:
    """GU 報價款號:M7 = 60225F046A,PDF = 225F046,trim 6-prefix + 尾碼字母"""
    if not isinstance(value, str):
        return value
    v = value.strip()
    # GU pattern: 60{4digit}{N/F/S}{3-4 alphanum}{optional letter A/B}
    m = re.match(r"^60(\d{3}[A-Z]\d{3,4})[A-Z]?$", v)
    if m:
        return m.group(1)
    return v


def _apply_alias(field_name: str, value, aliases: dict):
    """套用 field-specific alias normalize,non-string 直接返"""
    if value is None or not isinstance(value, str):
        return value
    if not field_name:
        return value
    v = value.strip()
    if not v:
        return value

    # Season 走 regex 規則
    if field_name == "Season":
        return _normalize_season(v)

    # 報價款號 — GU 特殊 trim 規則
    if field_name == "報價款號":
        return _normalize_style_no(v)

    # 其他 field 走 key-value mapping
    field_aliases = aliases.get(field_name, {})
    if not isinstance(field_aliases, dict):
        return value

    # exact match (preserve casing) → 試 case-insensitive match
    if v in field_aliases and not v.startswith("_"):
        return field_aliases[v]
    v_upper = v.upper()
    for k, target in field_aliases.items():
        if k.startswith("_"):
            continue
        if v_upper == k.upper():
            return target
    return value


def _normalize(v):
    """case-insensitive 比對用;原 value 保留 casing"""
    if v is None:
        return None
    if isinstance(v, str):
        return v.upper().strip()
    return str(v)


def consolidate_field(sources: dict, primary_source: str = "m7_列管",
                      field_name: str = None, aliases: dict = None) -> dict:
    """generic multi-source consensus for one canonical field

    Args:
      sources: {source_name: {"value": ..., "weight": int, ...} or None}
        weight 預設 1。None / value 空 都會略過。
      primary_source: 哪個 source 是 source-of-truth (預設 "m7_列管")
      field_name: canonical 欄位名 (eg "客戶" / "Season"),用於套 field-specific alias
      aliases: alias dict (預設讀 _load_aliases())

    Returns:
      {"value": <alias-normalized consensus_value>,
       "confidence": "high"|"medium"|"low"|"none",
       "sources": {original sources dict — alias 過後的值,但保留原始 weight}}
    """
    if aliases is None:
        aliases = _load_aliases()

    # === Pass 1: 收集 + alias normalize ===
    # tuple: (source_name, original_value, alias_value, casefold_norm, weight)
    valid = []
    sources_out = {}  # 留 audit trail,但 value 是 alias 過後的
    for s_name, s_val in sources.items():
        if not s_val:
            sources_out[s_name] = None
            continue
        v = s_val.get("value")
        if v is None or v == "":
            sources_out[s_name] = None
            continue
        # apply alias mapping
        alias_v = _apply_alias(field_name, v, aliases) if field_name else v
        weight = s_val.get("weight", 1)
        valid.append((s_name, v, alias_v, _normalize(alias_v), weight))
        # source dict 保 raw + normalized,讓 audit 看得到 alias 是否真的有作用
        sources_out[s_name] = {
            **s_val,
            "value": alias_v,        # alias 過後的值 (consensus 用)
            "raw_value": v,          # 原始 value (audit 用)
        }

    if not valid:
        return {"value": None, "confidence": "none", "sources": sources_out}

    # === Pass 2: weighted voting on (alias-normalized) value ===
    weighted = Counter()
    by_norm = defaultdict(list)
    for s_name, raw_v, alias_v, norm, w in valid:
        weighted[norm] += w
        by_norm[norm].append((s_name, alias_v, w))

    top_norm, _ = weighted.most_common(1)[0]

    # === Pass 3: pick representative casing ===
    rep_list = by_norm[top_norm]
    primary_pick = next(((s, v) for s, v, w in rep_list if s == primary_source), None)
    if primary_pick:
        value = primary_pick[1]
    else:
        rep_list_sorted = sorted(rep_list, key=lambda x: -x[2])
        value = rep_list_sorted[0][1]

    # === Pass 4: confidence (基於 alias-normalized norm 比較) ===
    primary_data = sources.get(primary_source)
    primary_value = primary_data.get("value") if primary_data else None
    primary_alias = _apply_alias(field_name, primary_value, aliases) if (field_name and primary_value) else primary_value
    primary_norm = _normalize(primary_alias) if primary_alias else None

    other_norms = [norm for s_name, _, _, norm, _ in valid if s_name != primary_source]

    if primary_norm:
        if not other_norms:
            confidence = "high"
        elif all(n == primary_norm for n in other_norms):
            confidence = "high"
        else:
            confidence = "medium"
    else:
        unique_others = set(other_norms)
        if len(unique_others) == 0:
            confidence = "none"
        elif len(unique_others) == 1 and len(other_norms) >= 2:
            confidence = "medium"
        else:
            confidence = "low"

    return {"value": value, "confidence": confidence, "sources": sources_out}


def build_canonical_block(
    *,
    m7_client_full: str | None,
    m7_design_id: str | None,
    m7_program: str | None,
    m7_subgroup: str | None,
    m7_season: str | None,
    m7_item: str | None,
    m7_gender: str | None,
    fabric_data: dict,                      # 已存在的 fabric 結構,直接 alias 為 W/K
    pdf_meta: dict | None = None,
    derived_gender: str | None = None,      # derive_gender() 的回傳
    derived_item_type: str | None = None,   # derive_item_type() 的回傳
    eidh: str | None = None,
    source_filename: str | None = None,
) -> dict:
    """組成 8 canonical 欄位的 consensus block

    Returns: {"客戶": {value, confidence, sources}, ...}
    """
    pdf = pdf_meta or {}
    aliases = _load_aliases()

    def _src(value, weight):
        """source dict 短手"""
        if value is None or value == "":
            return None
        return {"value": value, "weight": weight}

    result = {}

    # 1. 客戶
    result["客戶"] = consolidate_field({
        "m7_列管": _src(m7_client_full, 3),
        "pdf": _src(pdf.get("客戶"), 2),
    }, primary_source="m7_列管", field_name="客戶", aliases=aliases)

    # 2. 報價款號
    result["報價款號"] = consolidate_field({
        "m7_列管": _src(m7_design_id, 3),
        "pdf": _src(pdf.get("報價款號"), 2),
        "filename": _src(_extract_style_from_filename(source_filename), 1) if source_filename else None,
    }, primary_source="m7_列管", field_name="報價款號", aliases=aliases)

    # 3. Program
    result["Program"] = consolidate_field({
        "m7_列管": _src(m7_program, 3),
        "pdf": _src(pdf.get("Program"), 2),
    }, primary_source="m7_列管", field_name="Program", aliases=aliases)

    # 4. Subgroup
    result["Subgroup"] = consolidate_field({
        "m7_列管": _src(m7_subgroup, 3),
        "pdf": _src(pdf.get("Subgroup"), 2),
    }, primary_source="m7_列管", field_name="Subgroup", aliases=aliases)

    # 5. W/K — 直接 alias fabric_data (已是 multi-source 結構,不過 alias)
    result["W/K"] = {
        "value": fabric_data.get("value"),
        "confidence": fabric_data.get("confidence", "none"),
        "sources": fabric_data.get("sources", {}),
    }

    # 6. Item — 用款號 join M7 列管 (MK 資料) 即可,PDF / derive_item_type 都不用
    # (derive_item_type 是聚陽 IT 分類碼不是 Item 維度;PDF 端 Item 命名顆粒度跟 M7 對不齊)
    result["Item"] = consolidate_field({
        "m7_列管": _src(m7_item, 3),
    }, primary_source="m7_列管", field_name="Item", aliases=aliases)

    # 7. Season
    result["Season"] = consolidate_field({
        "m7_列管": _src(m7_season, 3),
        "pdf": _src(pdf.get("Season"), 2),
    }, primary_source="m7_列管", field_name="Season", aliases=aliases)

    # 8. PRODUCT_CATEGORY (gender)
    result["PRODUCT_CATEGORY"] = consolidate_field({
        "m7_列管": _src(m7_gender, 3),
        "pdf": _src(pdf.get("PRODUCT_CATEGORY"), 2),
        "derive_gender": _src(derived_gender, 1),
    }, primary_source="m7_列管", field_name="PRODUCT_CATEGORY", aliases=aliases)

    return result


def _extract_style_from_filename(name: str) -> str | None:
    """從 PDF 檔名抓 D-prefix style number 或 numeric style code"""
    if not name:
        return None
    import re
    # D-style (Centric 8): TPK...-D40583... → D40583
    m = re.search(r"\b(D\d{4,6})\b", name)
    if m:
        return m.group(1)
    # AIM-style (TARGET): TPK...-AIM26C3W28... → AIM26C3W28
    m = re.search(r"(?<![A-Za-z])(AIM\d{2}[A-Z]\d{1,2}[A-Z]+\d{1,3})", name)
    if m:
        return m.group(1)
    return None
