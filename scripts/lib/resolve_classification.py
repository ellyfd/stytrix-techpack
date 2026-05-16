"""統一分類解析器（2026-05-16）— 從 JSON 表驅動 Dept / GT / Fabric / Gender 4 維度。

主路徑：M7 列管 canonical 欄位（`mk_dept` / `mk_item` / `mk_fabric` / `mk_gender`）。
Fallback：本地 keyword 查表，來源 data/source/{dept,gt,fabric,gender}_keywords.json。

新檔位置：scripts/lib/resolve_classification.py

設計目標：
  1. 取代 reclassify_and_rebuild.py 的 real_dept_v4 / real_gt_v2 / infer_fabric
  2. 取代 rebuild_profiles.py 的 resolve_gender
  3. 取代 M7_Pipeline/scripts/derive_metadata.py 的 derive_dept / derive_gender / derive_garment_type
  4. 所有分類邏輯改成 data-driven JSON 查表，禁止再加 if/elif 進 .py
  5. 雙 location 部署：repo (scripts/lib/) + Source-Data (M7_Pipeline/scripts/lib/) 各放一份

Consumer 改 import 即可：
    from scripts.lib.resolve_classification import resolve_dept, resolve_gt, resolve_fabric, resolve_gender
"""
import json
import re
from pathlib import Path
from functools import lru_cache


# ════════════════════════════════════════════════════════════
# Table loader（lazy + cached）
# ════════════════════════════════════════════════════════════

# repo root = scripts/lib/<this_file>.py → ../../
_ROOT = Path(__file__).resolve().parent.parent.parent
_TABLES_DIR = _ROOT / "data" / "source"


@lru_cache(maxsize=8)
def _load_table(name: str) -> dict:
    """從 data/source/<name>.json 載入查表（cached）。檔不存在 → 空 dict，graceful 退讓 cascade 繼續往下走。"""
    path = _TABLES_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _upper(v) -> str:
    """UPPER + strip。non-string 或 None 回 ''。"""
    if not isinstance(v, str):
        return ""
    return v.upper().strip()


# ════════════════════════════════════════════════════════════
# GT (garment_type)
# ════════════════════════════════════════════════════════════

def resolve_gt(rec: dict) -> str:
    """主路徑 = M7 manifest_item 原值（聚陽款式分類）；空才走 gt_keywords.json 9 類 fallback。

    Input fields read:
      - mk_item / manifest_item    M7 列管 Item 欄
      - design_type / item_type / description    fallback 用，concat 後 keyword match
    """
    mi = (rec.get("mk_item") or rec.get("manifest_item") or "").strip()
    if mi:
        return mi

    tbl = _load_table("gt_keywords")
    rules = tbl.get("rules", [])
    default = tbl.get("_default", "PANTS")
    combined = " ".join([
        _upper(rec.get("design_type")),
        _upper(rec.get("item_type")),
        _upper(rec.get("description")),
    ])
    for rule in rules:
        # SET 需 word-boundary（避免誤命中 SETTLE / SETUP）
        if rule["gt"] == "SET":
            if re.search(r"\bSET\b", combined):
                return "SET"
            continue
        if any(kw in combined for kw in rule.get("keywords", [])):
            return rule["gt"]
    return default


# ════════════════════════════════════════════════════════════
# Fabric
# ════════════════════════════════════════════════════════════

def resolve_fabric(rec: dict) -> str:
    """主路徑 = M7 mk_fabric (W/K 欄)；空才走 fabric_keywords.json 三層 fallback。

    Canonical enum = Knit / Woven / Denim (Fleece 保留位置，未來聚陽 M7 加 Fleece 才用)
    """
    mf = (rec.get("mk_fabric") or "").strip()
    if mf in ("Knit", "Woven", "Denim", "Fleece"):
        return mf

    tbl = _load_table("fabric_keywords")
    rules = tbl.get("rules", {})
    default = tbl.get("_default", "Woven")

    # T1: category startswith
    cat = _upper(rec.get("category"))
    if cat:
        for prefix, fab in rules.get("category", {}).items():
            if prefix.startswith("_"):
                continue
            if cat.startswith(prefix):
                return fab

    # T2: sub_category substring
    subcat = _upper(rec.get("sub_category"))
    if subcat:
        for token, fab in rules.get("sub_category", {}).items():
            if token.startswith("_"):
                continue
            if token in subcat:
                return fab

    # T3: department_raw substring
    dept_raw = _upper(rec.get("department_raw"))
    if dept_raw:
        for token, fab in rules.get("department_raw", {}).items():
            if token.startswith("_"):
                continue
            if token in dept_raw:
                return fab

    return default


# ════════════════════════════════════════════════════════════
# Gender
# ════════════════════════════════════════════════════════════

def resolve_gender(rec: dict) -> str:
    """T1 MATERNITY override → T2 mk_gender → T3 (client,subgroup) canonical → T4 subgroup tokens → T5 client default。

    Canonical enum = WOMENS / MENS / GIRLS / BOYS / BABY / MATERNITY / UNKNOWN
    """
    tbl = _load_table("gender_keywords")
    canonical_map = _load_table("gender_lookup_by_subgroup")  # 從 client_canonical_mapping export，可選

    # ── T1: MATERNITY override ──
    bd = _upper(rec.get("brand_division"))
    dep = _upper(rec.get("department") or rec.get("department_raw"))
    maternity_tokens = tbl.get("maternity_override_tokens", {}).get("MATERNITY", ["MATERNITY", "MTR"])
    for tok in maternity_tokens:
        if tok in bd or tok in dep:
            return "MATERNITY"

    # ── T2: mk_gender (M7 列管) ──
    mk = (rec.get("mk_gender") or "").strip()
    if mk:
        return mk

    client = _upper(rec.get("client"))
    subgroup = _upper(rec.get("subgroup"))

    # ── T3: (client, subgroup) canonical (從 client_canonical_mapping export) ──
    if canonical_map:
        key = f"{client}|{subgroup}"
        if key in canonical_map:
            return canonical_map[key]

    # ── T4: subgroup tokens substring ──
    if subgroup:
        for gender_enum, tokens in tbl.get("subgroup_tokens", {}).items():
            if gender_enum.startswith("_"):
                continue
            if any(tok in subgroup for tok in tokens):
                return gender_enum

    # ── T5: client default ──
    if client:
        defaults = tbl.get("client_default", {})
        if client in defaults and not client.startswith("_"):
            return defaults[client]

    return "UNKNOWN"


# ════════════════════════════════════════════════════════════
# Dept
# ════════════════════════════════════════════════════════════

def _swim_subcheck(item_type_upper: str, active_types: list) -> str:
    """real_dept_v4 step3 的 SWIM 子邏輯：SWIM in dept_raw 看 item_type 是否在 active_types → ACTIVE 否則 SWIMWEAR。"""
    it_clean = item_type_upper.replace("_", " ")
    if any(at in it_clean for at in active_types):
        return "ACTIVE"
    return "SWIMWEAR"


def resolve_dept(rec: dict) -> str:
    """7 層 cascade Dept resolver (v2 canonical enum 6 個)。

    Enum: ACTIVE / RTW / SWIMWEAR / SLEEPWEAR / DENIM / FLEECE / (UNKNOWN fallback)

    Removed from v1 → v2:
      - COLLABORATION → 併 ACTIVE
      - MATERNITY → 拔出 Dept 放 GENDER (resolve_gender 已支援 override)

    Cascade:
      T1: M7 (client, subgroup) → dept_lookup_by_subgroup (from client_canonical_mapping)
      T2: item / item_type → by_item (SWIM/SLEEP/PAJAMA/ROBE...)
      T3: category startswith → by_category (IPSS→ACTIVE / DENIM→DENIM)
      T4: design_type exact → by_design_type
      T5: department_raw collab triplet → by_collab_set (NFL/NBA/MISCSPORTS → ACTIVE)
      T6: text keyword (program + subgroup + dept_raw concat) → by_dept_keyword 6 dept priority order
      T7: client default → by_client_default (含 DICKS+GOLF override, KIDS/BOY/GIRL/BABY default)
      T8: UNKNOWN
    """
    tbl = _load_table("dept_keywords")
    canonical_map = _load_table("dept_lookup_by_subgroup")  # 從 client_canonical_mapping export，可選

    client = _upper(rec.get("client"))
    subgroup = _upper(rec.get("subgroup"))
    program = _upper(rec.get("program"))

    # ── T1: M7 (client, subgroup) canonical mapping ──
    if canonical_map:
        key = f"{client}|{subgroup}"
        if key in canonical_map:
            return canonical_map[key]

    item = _upper(rec.get("item_type") or rec.get("item"))

    # ── T2: by_item rules ──
    for rule in tbl.get("by_item", {}).get("rules", []):
        match_tok = rule.get("match", "")
        exclude_toks = rule.get("exclude", [])
        if match_tok and match_tok in item and not any(ex in item for ex in exclude_toks):
            return rule["dept"]

    # ── T3: by_category startswith ──
    cat = _upper(rec.get("category"))
    if cat:
        for prefix, dept in tbl.get("by_category", {}).items():
            if prefix.startswith("_"):
                continue
            if dept is None:  # KNITS/WOVEN 是 fabric 訊號不回值
                continue
            if cat.startswith(prefix):
                return dept

    # ── T4: by_design_type exact ──
    dt = _upper(rec.get("design_type"))
    if dt:
        by_dt = tbl.get("by_design_type", {})
        if dt in by_dt and not dt.startswith("_"):
            return by_dt[dt]

    # ── T5: by_collab_set exact (NFL/NBA/MISCSPORTS → ACTIVE) ──
    dept_raw_stripped = _upper(rec.get("department_raw"))
    by_collab = tbl.get("by_collab_set", {})
    if dept_raw_stripped in by_collab and not dept_raw_stripped.startswith("_"):
        return by_collab[dept_raw_stripped]

    # ── T6: by_dept_keyword (priority order) ──
    text = " ".join([program, subgroup, _upper(rec.get("department_raw"))])
    by_kw = tbl.get("by_dept_keyword", {})
    priority = by_kw.get("_priority_order", ["ACTIVE", "FLEECE", "DENIM", "SLEEPWEAR", "RTW"])
    rules = by_kw.get("rules", {})
    for dept in priority + ["SWIMWEAR"]:  # SWIMWEAR 在最後（特殊 sub-check）
        rule = rules.get(dept, {})
        tokens = rule.get("tokens", [])
        if any(tok in text for tok in tokens):
            if dept == "SWIMWEAR":
                active_types = rule.get("_dept_swim_active_types_check", [])
                return _swim_subcheck(item, active_types)
            return dept

    # ── T7: client default ──
    by_default = tbl.get("by_client_default", {})
    # DICKS + GOLF override
    golf_rule = by_default.get("_dicks_golf_override", {})
    if golf_rule and client == "DICKS":
        if any(tok in text for tok in golf_rule.get("match_keywords", ["WALTER HAGEN", "GOLF"])):
            return golf_rule.get("dept", "RTW")
    # 一般 client default
    if client in by_default and not client.startswith("_"):
        v = by_default[client]
        if isinstance(v, str):
            return v
    # KIDS/BOY/GIRL/BABY default
    kids_rule = by_default.get("_kids_default_logic", {})
    if kids_rule and any(tok in client for tok in ["KIDS", "BOY", "GIRL", "BABY"]):
        return kids_rule.get("dept", "RTW")

    return "UNKNOWN"


# ════════════════════════════════════════════════════════════
# Backward-compat shims for legacy callsites
# ════════════════════════════════════════════════════════════

def real_dept_v4(p: dict) -> str:
    """Wrapper for reclassify_and_rebuild.py:real_dept_v4()."""
    return resolve_dept(p)


def real_gt_v2(p: dict) -> str:
    """Wrapper for reclassify_and_rebuild.py:real_gt_v2()."""
    return resolve_gt(p)


def infer_fabric(p: dict) -> str:
    """Wrapper for reclassify_and_rebuild.py:infer_fabric()."""
    return resolve_fabric(p)


# ════════════════════════════════════════════════════════════
# Cache reset (for testing / hot reload)
# ════════════════════════════════════════════════════════════

def _reset_cache():
    """測試或 hot reload 時 reset table cache。Production 不需呼叫。"""
    _load_table.cache_clear()
