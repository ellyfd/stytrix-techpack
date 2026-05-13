"""build_m7_pullon_source_v3.py — Step 2 publisher (maximize-per-款 edition)

🔧 v3 vs v2 差別:
- v2 只輸出 m7_pullon_source.jsonl (aggregated by 6-dim key)
- v3 兩 output:
    1. m7_pullon_source.jsonl  — 給 platform build_recipes_master 用 (跟 v2 同)
    2. m7_pullon_designs.jsonl — ★ 新加,per-EIDH 完整履歷,給 Phase 2 derive 用
- v3 fabric 改成 multi-source consensus (m7_wk + bom + machine inferred + ...)
- v3 整合所有可拿的 raw source (m7 index 42 col / m7_report 33 col / csv_5level / callout / vision)

設計原則 (per user, 2026-05-08):
> 「所有的資料都要想最安全和最大化的內容,除非是bible,
>   不然每一款要帶的資料要越齊越好」

Bible 不污染 (l2_l3_ie/*.json 維持 canonical),per-EIDH source 所有 metadata 都帶。

跑:python scripts\\build_m7_pullon_source_v3.py
Outputs:
  outputs/platform/m7_pullon_source.jsonl   (aggregated by 6-dim key)
  outputs/platform/m7_pullon_designs.jsonl  (per-EIDH 完整履歷)
"""
from __future__ import annotations
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from m7_eidh_loader import load_m7_index  # noqa: E402
from derive_metadata import derive_gender, derive_dept  # noqa: E402

# 5/8+ 加:8 canonical multi-source consensus (推廣自 fabric)
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from consolidate_canonical import build_canonical_block  # noqa: E402

# === Paths ===
M7_ORG = ROOT / "m7_organized_v2"
CSV_5LEVEL_DIR = M7_ORG / "csv_5level"
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
CALLOUT_MANIFEST = M7_ORG / "callout_manifest.jsonl"
VISION_FACTS = M7_ORG / "vision_facts.jsonl"
# PDF + PPTX cover-page metadata (extract_raw_text_m7.py --metadata-only 抽出)
# Newer path: m7_organized_v2/metadata/designs.jsonl (5/8+),fallback 到舊 root 路徑 m7_organized_v2/designs.jsonl
_PDF_META_NEW = M7_ORG / "metadata" / "designs.jsonl"
_PDF_META_OLD = M7_ORG / "designs.jsonl"
PDF_METADATA = _PDF_META_NEW if _PDF_META_NEW.exists() else _PDF_META_OLD

# 5/8+ 新增:per-client adapter 抽出的 PDF canonical metadata
# (extract_pdf_metadata.py 輸出,11 客戶 1448 件,8 canonical 各 0-100% 不等)
PDF_CANONICAL = ROOT / "outputs" / "platform" / "pdf_metadata.jsonl"
# 2026-05-11: 新 unified extract output (5,775 件 metadata vs 舊 1,448)
PDF_FACETS_NEW = ROOT / "outputs" / "extract" / "pdf_facets.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"

OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_SOURCE = OUT_DIR / "m7_source.jsonl"           # 2026-05-11 改名: m7_pullon → m7 (全展開後不再只是 PullOn)
OUT_DESIGNS = OUT_DIR / "m7_designs.jsonl"         # 2026-05-11 改名

# === Constants ===
FILENAME_RE = re.compile(r"^(\d+)_")

CLIENT_TO_CODE = {
    # 核心 12 客戶
    "OLD NAVY": "ONY", "TARGET": "TGT", "GAP": "GAP", "GAP OUTLET": "GAP",
    "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS", "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA", "KOHLS": "KOH", "A & F": "ANF", "GU": "GU",
    "BEYOND YOGA": "BY",
    # 2026-05-11 補(Pull-On Pilot):audit_eidh_dropout 找出主要客戶 (>= 10 件)
    "HIGH LIFE LLC": "HLF",         # 238 (Pull-On) / 467 (全集)
    "WAL-MART": "WMT",              # 87 / 196 (全集)
    "WAL-MART-CA": "WMT",           # 73 / 228 (Walmart Canada 視為同集團)
    "QUINCE": "QCE",                # 56 / 166
    "HALARA": "HLA",                # 46 / 80
    "NET": "NET",                   # 35 / 154
    "JOE FRESH": "JF",              # 34 / 98
    "BANANA REPUBLIC": "BR",        # 30 / 546 (跟 BRFS 同集團 — PDF parser 已認 BR)
    "SANMAR": "SAN",                # 20 / 414
    "DISTANCE": "DST",              # 18 / 54
    "ZARA": "ZAR",                  # 15 / 142
    "ASICS-EU": "ASICS",            # 10 / 81
    # 2026-05-11 全展開 (ITEM_FILTER=set() 跑全 18,731):新增 3 brand (Elly 確認)
    "LEVIS": "LEV",                 # 50 件 (含上衣 / 下身, 知名牛仔品牌)
    "CATO": "CATO",                 # 38 件 (上次 5 件 drop, 全展開規模升)
    "SMART CLOTHING": "SMC",        # 16 件 (過 10 件門檻)
    # 故意 drop:
    # - 聚陽內部研發 (V1/V2/V5/V7/S1 DEVELOPING) — 不該混進 m7 客戶 report
    # - 雜項 < 10 件 (ROSS/GILDAN/TOMS/M-STAR/XBODY/HANESBRANDS …) — 樣本太少
}

ZH_NORMALIZE = {"檔底片": "襠底片", "褶底片": "襠底片"}

# Phase 2 spec (CLAUDE.md): m7_pullon source 不該含 IE 端 placeholder rows。
# `new_part_*` / `new_shape_design_*` / `new_method_describe_*` / `(NEW)*` 是 IE 還沒 finalize
# 的工法 placeholder,該 drop 不進 m7_pullon designs.jsonl。
# 之前佔 csv_5level 約 20.6%(43k/210k 件),drop 後 Bible alignment match% 從 67.9% → ~86%。
_PLACEHOLDER_DROPPED = {"l2": 0, "l3": 0, "l4": 0, "l5": 0}

# Machine name keyword → fabric inference
MACHINE_FABRIC_HINT = {
    "圓編": "knit", "橫編": "knit", "拷克": "knit",     # knit machines
    "劍杆": "woven", "梭織": "woven",                   # woven machines
    # 平車 / 燙工 / 手工 = both,no hint
}


def normalize_client(raw: str) -> str | None:
    if not raw:
        return None
    cleaned = raw.upper().split("(")[0].strip()
    return CLIENT_TO_CODE.get(cleaned)


def to_float(v):
    if v is None:
        return None
    s = str(v).replace(",", "")
    m = re.search(r"(-?\d+\.?\d*)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def normalize_zh(s: str) -> str:
    if not s:
        return s
    for bad, good in ZH_NORMALIZE.items():
        s = s.replace(bad, good)
    return s


def strip_marker(s: str) -> str:
    if not s:
        return ""
    return normalize_zh(s.lstrip("*").strip())


def derive_item_type(design_id, program, item, subgroup, client, dept):
    """從 M7 Item / design_id / program / subgroup 推 IT (Item Type, bucket 第 4 維)。

    對齊 bucket_taxonomy v4 / legacy 慣例。展全 32 Item 後對應到:
      BOTTOM: LEGGINGS / JOGGERS / CAPRI / SKIRT / SHORTS / PANT / BOXER / PANTY
      TOP:    TEE / POLO / BLOUSE / CAMISOLE / TANK / HOODIE
      DRESS:  DRESS / GOWN / JUMPER / CHEMISE
      OUTER:  JACKET / VEST / ROBE
      SET:    PAJAMA / SUIT
      SWIM:   SWIM
      其他:   ACCESSORIES (Accessories/Blanket)
    """
    text = f"{design_id} {program} {item} {subgroup}".upper()
    c = (client or "").upper()
    d = (dept or "").upper()

    # ── 整身一件 ──
    if "JUMPER" in text: return "JUMPER"
    if "CHEMISE" in text: return "CHEMISE"
    if "GOWN" in text: return "GOWN"
    if "DRESS" in text and "DRESSY" not in text: return "DRESS"  # Dressy Pants 不算

    # ── 外套 ──
    if "JACKET" in text: return "JACKET"
    if "VEST" in text: return "VEST"
    if "ROBE" in text: return "ROBE"

    # ── SET 套裝 ──
    if "PAJAMA" in text: return "PAJAMA"
    if "SUIT" in text: return "SUIT"

    # ── SWIM ──
    if "SWIM" in text or "BIKINI" in text: return "SWIM"

    # ── 下身細類 ──
    if "LEGGING" in text or "TIGHT" in text: return "LEGGINGS"
    if "JOGGER" in text or "SWEATPANT" in text: return "JOGGERS"
    if "CAPRI" in text: return "CAPRI"
    if "SKIRT" in text or "SKORT" in text: return "SKIRT"
    if "SHORT" in text: return "SHORTS"
    if "BOXER" in text: return "BOXER"
    if "PANTIE" in text or "BRIEF" in text: return "PANTY"

    # ── 上身細類 ──
    if "TEE" in text or "T-SHIRT" in text: return "TEE"
    if "POLO" in text: return "POLO"
    if "BLOUSE" in text: return "BLOUSE"
    if "CAMISOLE" in text or "CAMI" in text: return "CAMISOLE"
    if "TANK" in text: return "TANK"
    if "HOODIE" in text or "SWEATSHIRT" in text: return "HOODIE"
    if "SHIRT" in text: return "SHIRT"

    # ── 雜項 ──
    if "ACCESSOR" in text: return "ACCESSORIES"
    if "BLANKET" in text: return "BLANKET"

    # ── Active brand 預設 LEGGINGS (Pilot 邏輯保留) ──
    if any(k in text for k in ["COMPRESSION", "POWERSOFT", "BUTTERSOFT", "STUDIOSMOOTH", "FLX"]):
        return "LEGGINGS"
    if c in {"BEYOND YOGA", "ATHLETA", "UNDER ARMOUR", "CALIA"} and d == "ACTIVE":
        return "LEGGINGS"

    return "PANT"  # 預設下身褲 fallback


def derive_gt_from_item(item: str, design_id: str = "", program: str = "") -> str:
    """從 M7 列管 Item 欄推 GT (Garment Type)。對齊 bucket_taxonomy v4 單數慣例。

    GT 是大類,DEPT (SLEEPWEAR/ACTIVE/RTW/FLEECE) 走 derive_dept。
    32 個 M7 Item 對到 7 種 GT:BOTTOM / TOP / DRESS / OUTER / SET / SWIM / OTHER。
    """
    text = f"{item} {program} {design_id}".upper()

    # DRESS 類 (整身一件)
    if any(k in text for k in ["DRESS", "GOWN", "JUMPER", "CHEMISE", "ROMPER"]):
        return "DRESS"

    # OUTER 類 (外套)
    if any(k in text for k in ["JACKET", "COAT", "VEST", "ROBE", "BLAZER", "PARKA"]):
        return "OUTER"

    # SET 類 (套裝 / 多件組)
    if "SUIT" in text or "PAJAMA" in text or " SET" in f" {text}":
        return "SET"

    # SWIM (泳裝)
    if "SWIM" in text or "BIKINI" in text:
        return "SWIM"

    # BOTTOM 類 (下身)
    if any(k in text for k in [
        "PANT", "LEGGING", "TIGHT", "SHORT", "SKIRT", "SKORT",
        "JOGGER", "BOXER", "BRIEF", "PANTIE",
    ]):
        return "BOTTOM"

    # TOP 類 (上身) — 留最後,避免 "TEE" 誤撞其他字
    if any(k in text for k in [
        "TEE", "T-SHIRT", "POLO", "BLOUSE", "SHIRT",
        "CAMISOLE", "TANK", "HOODIE", "SWEATSHIRT",
    ]) or text.strip().startswith("TOP"):
        return "TOP"

    # Fallback (Accessories / Blanket / 其他)
    return "OTHER"


# === Fabric multi-source consensus ===

def infer_fabric_from_machines(machine_counter: Counter) -> tuple[str | None, dict]:
    """從 csv_5level 的 machine_name 分布推 fabric。回傳 (value, evidence_dict)"""
    knit_count = 0
    woven_count = 0
    for m, n in machine_counter.items():
        for kw, fab in MACHINE_FABRIC_HINT.items():
            if kw in m:
                if fab == "knit":
                    knit_count += n
                elif fab == "woven":
                    woven_count += n
                break
    if knit_count == 0 and woven_count == 0:
        return None, {"knit_machine_steps": 0, "woven_machine_steps": 0}
    val = "knit" if knit_count > woven_count else "woven"
    return val, {"knit_machine_steps": knit_count, "woven_machine_steps": woven_count}


def infer_fabric_from_bom(fabric_name: str, fabric_ingredients: str) -> str | None:
    """從 m7_report.fabric_name / fabric_ingredients 推"""
    text = f"{fabric_name or ''} {fabric_ingredients or ''}".lower()
    if "knit" in text or "jersey" in text or "interlock" in text or "rib" in text:
        return "knit"
    if "woven" in text or "twill" in text or "poplin" in text or "canvas" in text:
        return "woven"
    return None


def consolidate_fabric(m7_wk: str, bom_name: str, bom_ingr: str,
                       machine_counter: Counter, subgroup: str, item: str) -> dict:
    """整合多 source 推 fabric,回傳 {value, confidence, sources}"""
    sources = {}

    # 1. M7 W/K (primary)
    if m7_wk:
        wk_upper = m7_wk.upper()
        if wk_upper.startswith("K"):
            sources["m7_wk"] = {"raw": m7_wk, "inferred": "knit"}
        elif wk_upper.startswith("W"):
            sources["m7_wk"] = {"raw": m7_wk, "inferred": "woven"}
        else:
            sources["m7_wk"] = {"raw": m7_wk, "inferred": None}
    else:
        sources["m7_wk"] = None

    # 2. BOM metadata (m7_report.jsonl)
    bom_inferred = infer_fabric_from_bom(bom_name, bom_ingr)
    sources["bom_metadata"] = {
        "fabric_name": bom_name or None,
        "fabric_ingredients": bom_ingr or None,
        "inferred": bom_inferred,
    } if (bom_name or bom_ingr) else None

    # 3. SSRS machine inferred
    mach_inferred, mach_evidence = infer_fabric_from_machines(machine_counter)
    sources["ssrs_machine_inferred"] = {
        **mach_evidence,
        "inferred": mach_inferred,
    } if (mach_evidence.get("knit_machine_steps") or mach_evidence.get("woven_machine_steps")) else None

    # 4. Subgroup keyword hint
    subgroup_inferred = None
    sg_up = (subgroup or "").upper()
    if any(k in sg_up for k in ["KNIT"]):
        subgroup_inferred = "knit"
    elif any(k in sg_up for k in ["WOVEN"]):
        subgroup_inferred = "woven"
    sources["subgroup_hint"] = {"raw": subgroup, "inferred": subgroup_inferred} if subgroup_inferred else None

    # 5. Item keyword hint (LEGGINGS → strong knit hint)
    item_inferred = None
    item_up = (item or "").upper()
    if "LEGGING" in item_up or "TIGHT" in item_up:
        item_inferred = "knit"
    sources["item_hint"] = {"raw": item, "inferred": item_inferred} if item_inferred else None

    # === Consensus ===
    votes = Counter()
    for s_name, s_val in sources.items():
        if s_val and s_val.get("inferred"):
            inf = s_val["inferred"].lower() if isinstance(s_val["inferred"], str) else None
            if inf in ("knit", "woven"):
                # weight: m7_wk 最重(3),bom 2,其他 1
                weight = 3 if s_name == "m7_wk" else 2 if s_name == "bom_metadata" else 1
                votes[inf] += weight

    if votes:
        top = votes.most_common(1)[0]
        value = top[0].upper()  # KNIT / WOVEN
        n_sources = sum(1 for v in sources.values() if v and v.get("inferred"))
        agreement = sum(1 for v in sources.values()
                       if v and v.get("inferred") and v["inferred"].lower() == top[0])
        if sources.get("m7_wk") and sources["m7_wk"].get("inferred"):
            confidence = "high"  # 有 M7 W/K = 最強
        elif n_sources >= 2 and agreement == n_sources:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        value = "UNKNOWN"
        confidence = "none"

    return {"value": value, "confidence": confidence, "sources": sources}


def parse_csv_row(row: dict, l1_zh_to_code: dict) -> dict | None:
    cat = (row.get("category") or "").strip()
    l1_code = l1_zh_to_code.get(cat)
    if not l1_code:
        return None
    l2 = strip_marker(row.get("part") or "")
    l3 = strip_marker(row.get("Shape_Design") or "")
    l4 = strip_marker(row.get("Method_Describe") or "")
    l5 = normalize_zh((row.get("section") or "").strip())
    if not (l2 and l3 and l4 and l5):
        return None
    # Phase 2 spec: drop IE 端 placeholder rows (per CLAUDE.md + derive_view_l2_l3_ie.py filter)
    # IE 還沒 finalize 的工法描述,不進 m7_pullon source (避免污染 Bible alignment)
    if l2.startswith("new_part_"):
        _PLACEHOLDER_DROPPED["l2"] += 1
        return None
    if l3.startswith("new_shape_design_"):
        _PLACEHOLDER_DROPPED["l3"] += 1
        return None
    if l4.startswith("new_method_describe_"):
        _PLACEHOLDER_DROPPED["l4"] += 1
        return None
    if l5.startswith("(NEW)"):
        _PLACEHOLDER_DROPPED["l5"] += 1
        return None
    return {
        "category_zh": cat, "l1": l1_code, "l2": l2, "l3": l3, "l4": l4, "l5": l5,
        "skill": (row.get("Skill_Level") or "").strip(),
        "primary": (row.get("Sewing_Process") or "主").strip(),
        "machine": (row.get("machine_name") or "").strip(),
        "size": (row.get("size") or "").strip(),
        "sec": to_float(row.get("total_second")) or 0.0,
    }


def safe(v, default=None):
    """Convert pandas NaN / None / empty → default"""
    import math
    if v is None: return default
    if isinstance(v, float) and math.isnan(v): return default
    s = str(v).strip()
    return s if s else default


def main():
    print("=" * 70)
    print("build_m7_pullon_source_v3.py — Step 2 (maximize-per-款)")
    print("=" * 70)
    print(f"Output 1 (aggregated):  {OUT_SOURCE}")
    print(f"Output 2 (per-EIDH):    {OUT_DESIGNS}")
    print()

    # === 1. M7 index → eidh_to_meta (full 42 cols preserved) ===
    print("[1] Load M7 index (42 cols preserved per EIDH)")
    df = load_m7_index()
    df["客戶_clean"] = df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper()
    g_map = {"Women": "WOMEN", "Men": "MEN", "Girl": "GIRL", "Boy": "BOY", "Baby": "BABY"}
    df["gender_excel"] = df["PRODUCT_CATEGORY"].astype(str).str.split().str[0].map(g_map).fillna("UNKNOWN")

    eidh_to_m7row = {}  # EIDH → full M7 row dict
    eidh_to_meta = {}   # EIDH → light meta for aggregation
    for _, row in df.iterrows():
        eidh = row.get("Eidh")
        if not eidh:
            continue
        eidh = str(int(eidh))
        # Full row (42 cols, NaN-safe)
        full = {col: safe(row.get(col)) for col in df.columns}
        eidh_to_m7row[eidh] = full
        eidh_to_meta[eidh] = {
            "client": str(row["客戶_clean"]),
            "subgroup": str(row.get("Subgroup", "") or ""),
            "item": str(row.get("Item", "") or ""),
            "program": str(row.get("Program", "") or ""),
            "wk": str(row.get("W/K", "") or "").upper(),
            "season": str(row.get("Season", "") or ""),
            "design_id": str(row.get("報價款號", "") or ""),
            "gender_excel": row["gender_excel"],
        }
    print(f"    {len(eidh_to_m7row):,} EIDHs (M7 列管 raw rows preserved)")

    # === 2. m7_report.jsonl → eidh_to_report (BOM, fabric_name, quantity_dz, etc.) ===
    print("\n[2] Load m7_report.jsonl (BOM + IE summary)")
    eidh_to_report = {}
    if M7_REPORT.exists():
        for line in open(M7_REPORT, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            eidh = str(r.get("eidh", ""))
            if eidh:
                # 留所有欄位除了 five_level_detail (太大,不走這條 source)
                report_meta = {k: v for k, v in r.items() if k != "five_level_detail"}
                eidh_to_report[eidh] = report_meta
    print(f"    {len(eidh_to_report):,} EIDHs from m7_report.jsonl")

    # === 2.5 PDF cover-page metadata (從 extract_raw_text.py m7_organized_v2/designs.jsonl) ===
    print("\n[2.5] Load PDF cover-page metadata")
    eidh_to_pdf_meta = {}
    if PDF_METADATA.exists():
        for line in open(PDF_METADATA, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            eidh = r.get("eidh")
            if eidh:
                eidh_to_pdf_meta[str(eidh)] = r
    print(f"    {len(eidh_to_pdf_meta):,} EIDHs PDF metadata (from cover page)")

    # === 2.6 PDF canonical metadata ===
    # 2026-05-11: 優先讀新 unified extract output (outputs/extract/pdf_facets.jsonl, 5,775 件)
    # Fallback 舊 outputs/platform/pdf_metadata.jsonl (1,448 件)
    print("\n[2.6] Load PDF canonical metadata")
    eidh_to_pdf_canonical = {}
    if PDF_FACETS_NEW.exists():
        for line in open(PDF_FACETS_NEW, encoding="utf-8"):
            try:
                f = json.loads(line)
            except Exception:
                continue
            if f.get("_status") != "ok":
                continue
            eidh = f.get("eidh")
            meta = f.get("metadata") or {}
            if not eidh or not meta:
                continue
            # Adapter: 新 schema → 舊 pdf_canonical 期待格式
            eidh_to_pdf_canonical[str(eidh)] = {
                "eidh": eidh,
                "client": f.get("client_code"),
                "client_raw": f.get("client_raw"),
                "design_id": f.get("design_id"),
                "brand_division": meta.get("brand_division"),
                "department": meta.get("department") or meta.get("department_raw"),
                "category": meta.get("bom_category") or meta.get("category"),
                "sub_category": meta.get("sub_category"),
                "collection": meta.get("collection"),
                "season": meta.get("season") or meta.get("season_raw") or meta.get("season_full"),
                "gender_pdf": meta.get("gender") or meta.get("gender_inferred"),
                "design_number": meta.get("design_number") or meta.get("product_id"),
                "description": meta.get("description"),
                "subbrand": meta.get("subbrand"),
                "garment_type": meta.get("garment_type") or meta.get("garment_type_hint"),
                "source_pdf": (f.get("source_files") or [None])[0],
                "_extract_metadata": meta,  # raw, audit trail
            }
        print(f"    {len(eidh_to_pdf_canonical):,} EIDHs PDF canonical (from {PDF_FACETS_NEW.relative_to(ROOT)})")
    elif PDF_CANONICAL.exists():
        for line in open(PDF_CANONICAL, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            eidh = r.get("eidh")
            if eidh:
                eidh_to_pdf_canonical[str(eidh)] = r
        print(f"    {len(eidh_to_pdf_canonical):,} EIDHs PDF canonical (legacy {PDF_CANONICAL.relative_to(ROOT)})")
    else:
        print(f"    (skip — 新舊兩個 source 都不存在)")

    # === 3. callout_manifest + vision_facts (techpack coverage) ===
    # callout_manifest 的 key 是 design_id (客戶款號) — 用 design_id → EIDH 查
    # 同 design_id 可能對到多 EIDH (不同 size/version),先收進 design_id keyed dict
    print("\n[3] Load callout_manifest + vision_facts")

    design_id_to_eidhs = defaultdict(list)
    for eidh, m in eidh_to_meta.items():
        did = (m.get("design_id") or "").strip()
        if did:
            design_id_to_eidhs[did].append(eidh)

    by_design_id_callouts = defaultdict(int)
    by_design_id_vlm = defaultdict(int)
    eidh_to_callouts = defaultdict(int)
    eidh_to_vlm = defaultdict(int)

    if CALLOUT_MANIFEST.exists():
        for line in open(CALLOUT_MANIFEST, encoding="utf-8"):
            try:
                r = json.loads(line)
                did = (r.get("design_id") or "").strip()
                if did:
                    by_design_id_callouts[did] += 1
            except Exception:
                continue
    if VISION_FACTS.exists():
        for line in open(VISION_FACTS, encoding="utf-8"):
            try:
                r = json.loads(line)
                did = (r.get("design_id") or "").strip()
                if did:
                    by_design_id_vlm[did] += 1
            except Exception:
                continue

    # Spread design_id counts to all matching EIDHs
    matched_designs = 0
    for did, n in by_design_id_callouts.items():
        for eidh in design_id_to_eidhs.get(did, []):
            eidh_to_callouts[eidh] += n
            matched_designs += 1
    for did, n in by_design_id_vlm.items():
        for eidh in design_id_to_eidhs.get(did, []):
            eidh_to_vlm[eidh] += n

    print(f"    callouts:  {sum(by_design_id_callouts.values()):,} entries / {len(by_design_id_callouts):,} design_id")
    print(f"      → matched to {len(eidh_to_callouts):,} EIDH (via design_id → EIDH lookup)")
    print(f"    vlm facts: {sum(by_design_id_vlm.values()):,} / {len(by_design_id_vlm):,} design_id → {len(eidh_to_vlm):,} EIDH")

    # === 4. Load Bible L1 mapping ===
    print("\n[4] Load zone_glossary L1 mapping")
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    L1_zh_to_code = {zh: code for code, zh in g.get("L1_STANDARD_38", {}).items()}
    print(f"    {len(L1_zh_to_code)} L1 mapping")

    # === 5. Walk csv_5level → build (a) aggregated source + (b) per-EIDH designs ===
    print(f"\n[5] Walk csv_5level → aggregate + per-EIDH 履歷")
    if not CSV_5LEVEL_DIR.exists():
        print(f"[!] csv_5level not found: {CSV_5LEVEL_DIR}")
        return

    csv_files = sorted(CSV_5LEVEL_DIR.glob("*.csv"))
    print(f"    {len(csv_files):,} csv files")

    # Aggregator (6-dim key) — 跟 v2 一樣
    agg = defaultdict(lambda: {
        "n_steps": 0, "client_counter": Counter(), "design_ids": set(),
        "ie_total_seconds": 0.0,
        "by_client": defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))),
    })

    # Per-EIDH designs (新)
    designs = []  # list of dict, each = one EIDH 完整履歷
    n_files_ok = 0
    n_files_no_meta = 0
    n_rows_total = 0
    n_rows_processed = 0

    for csv_path in csv_files:
        m = FILENAME_RE.match(csv_path.name)
        if not m:
            continue
        eidh = m.group(1)
        meta = eidh_to_meta.get(eidh)
        if not meta:
            n_files_no_meta += 1
            continue

        client_full = meta["client"]
        client_code = normalize_client(client_full)
        if not client_code:
            continue

        # === Per-EIDH: collect ALL csv rows + machine counter (for fabric inference) ===
        eidh_rows = []
        eidh_machine_counter = Counter()
        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    n_rows_total += 1
                    parsed = parse_csv_row(row, L1_zh_to_code)
                    if not parsed:
                        continue
                    n_rows_processed += 1
                    eidh_rows.append(parsed)
                    if parsed["machine"]:
                        eidh_machine_counter[parsed["machine"]] += 1
        except Exception as e:
            print(f"    [skip] {csv_path.name}: {e}", file=sys.stderr)
            continue

        if not eidh_rows:
            continue
        n_files_ok += 1

        # === Fabric multi-source consensus ===
        m7_row = eidh_to_m7row.get(eidh, {})
        report_row = eidh_to_report.get(eidh, {})
        fabric_data = consolidate_fabric(
            m7_wk=meta["wk"],
            bom_name=safe(report_row.get("fabric_name"), ""),
            bom_ingr=safe(report_row.get("fabric_ingredients"), ""),
            machine_counter=eidh_machine_counter,
            subgroup=meta["subgroup"],
            item=meta["item"],
        )
        fabric_value = fabric_data["value"]
        if fabric_value not in ("KNIT", "WOVEN"):
            continue  # skip 無法判 fabric (極少數)
        wk_lower = "knit" if fabric_value == "KNIT" else "woven"

        # === Classification ===
        gender = meta["gender_excel"] if meta["gender_excel"] != "UNKNOWN" else (derive_gender(client_full, meta["subgroup"]) or "UNKNOWN")
        dept = derive_dept(client_full, meta["program"], meta["subgroup"]) or "UNKNOWN"
        gt = derive_gt_from_item(meta["item"], meta["design_id"], meta["program"])
        it = derive_item_type(meta["design_id"], meta["program"], meta["item"], meta["subgroup"], client_full, dept)
        design_id = meta["design_id"]

        # === Aggregate into 6-dim key (for source.jsonl) ===
        ie_total = 0.0
        for parsed in eidh_rows:
            key = (gender, dept, gt, it, fabric_value, parsed["l1"])
            entry = agg[key]
            entry["n_steps"] += 1
            entry["design_ids"].add(design_id)
            entry["client_counter"][client_code] += 1
            entry["ie_total_seconds"] += parsed["sec"]
            ie_total += parsed["sec"]
            l5_step = {
                "l5": parsed["l5"], "skill": parsed["skill"],
                "primary": parsed["primary"], "machine": parsed["machine"],
                "size": parsed["size"], "sec": parsed["sec"],
            }
            entry["by_client"][client_code][wk_lower][parsed["l2"]][parsed["l3"]][parsed["l4"]].append(l5_step)

        # === Build per-EIDH design 履歷 ===
        design = {
            "eidh": eidh,
            "design_id": design_id,
            "style_no_internal": safe(m7_row.get("HEADER_SN")),
            "season": meta["season"] or None,
            "brand_division": None,  # filled below if available
            "client": {
                "name": client_full,
                "code": client_code,
            },
            "fabric": fabric_data,
            "classification": {
                "gender": {"value": gender, "source": "m7_product_category" if meta["gender_excel"] != "UNKNOWN" else "derive_gender"},
                "dept": {"value": dept, "source": "derive_dept"},
                "gt": {"value": gt, "source": "fixed_pullon"},
                "it": {"value": it, "source": "derive_item_type"},
                "subgroup": meta["subgroup"] or None,
                "program": meta["program"] or None,
                "item": meta["item"] or None,
            },
            "five_level_steps": [
                {
                    "row_index": i + 1,
                    "category_zh": p["category_zh"], "l1": p["l1"],
                    "l2": p["l2"], "l3": p["l3"], "l4": p["l4"], "l5": p["l5"],
                    "primary": p["primary"], "skill": p["skill"],
                    "machine": p["machine"], "size": p["size"], "sec": p["sec"],
                }
                for i, p in enumerate(eidh_rows)
            ],
            "n_steps": len(eidh_rows),
            "ie_total_seconds": round(ie_total, 1),
            "techpack_coverage": {
                "callout_count": eidh_to_callouts.get(eidh, 0),
                "vlm_facts_count": eidh_to_vlm.get(eidh, 0),
                "has_techpack_pdf_or_pptx": eidh in eidh_to_callouts,
            },
            "order": {
                "quantity_dz": safe(report_row.get("quantity_dz")),
                "fabric_spec": safe(report_row.get("fabric_name")),
                "fabric_ingredients": safe(report_row.get("fabric_ingredients")),
                "evaluation_type": safe(report_row.get("evaluation_type")),
                "origin": safe(report_row.get("origin")),
                "approval_date": safe(report_row.get("review_date")) or safe(report_row.get("analyst_date")),
                "reviewer": safe(report_row.get("reviewer")),
                "performance_cost": safe(report_row.get("performance_cost")),
                "total_amount_usd_dz": safe(report_row.get("total_amount_usd_dz")),
            },
            "ie_breakdown_summary": {
                "sewing_ie": safe(report_row.get("sewing_ie")),
                "cutting_time": safe(report_row.get("cutting_time")),
                "cutting_ie": safe(report_row.get("cutting_ie")),
                "ironing_time": safe(report_row.get("ironing_time")),
                "ironing_ie": safe(report_row.get("ironing_ie")),
                "package_time": safe(report_row.get("package_time")),
                "package_ie": safe(report_row.get("package_ie")),
                "total_time": safe(report_row.get("total_time")),
                "total_ie": safe(report_row.get("total_ie")),
                "標打": safe(m7_row.get("標打")),
                "實打": safe(m7_row.get("實打")),
                "ie_ratio": safe(m7_row.get("IE")),
            },
            # PDF cover-page metadata (extract_raw_text.py 抽出的客戶 PDF 自有命名)
            # 這是「客戶端」視角的 metadata,vs m7_report 是「聚陽 ERP 內部」視角
            "pdf_metadata": eidh_to_pdf_meta.get(eidh),
            # 5/8+ 加:per-client adapter 抽出的 PDF canonical (8 個聚陽 canonical)
            "pdf_canonical": eidh_to_pdf_canonical.get(eidh),
            # 5/8+ 加:8 canonical multi-source consensus
            #   M7 列管 (priority 3, primary, 100%) + PDF canonical (priority 2, 0-100%)
            #   + 推論/檔名 (priority 1, fallback)
            # Filter 直接讀 canonical.<field>.value 永遠 100% (M7 兜底);
            # confidence "high"/"medium"/"low" 標 audit 強度;
            # canonical.<field>.sources 留 audit trail (PDF vs M7 是否衝突一目了然)
            "canonical": build_canonical_block(
                m7_client_full=client_full,
                m7_design_id=design_id,
                m7_program=meta.get("program"),
                m7_subgroup=meta.get("subgroup"),
                m7_season=meta.get("season"),
                m7_item=meta.get("item"),
                m7_gender=gender if gender != "UNKNOWN" else None,
                fabric_data=fabric_data,  # alias 為 W/K
                pdf_meta=eidh_to_pdf_canonical.get(eidh),
                derived_gender=derive_gender(client_full, meta.get("subgroup")),
                derived_item_type=it,
                eidh=eidh,
                source_filename=(eidh_to_pdf_canonical.get(eidh) or {}).get("source_pdf"),
            ),
            "sources": {
                "csv_5level_path": str(csv_path.relative_to(ROOT)),
                "m7_index_row": m7_row,           # all 42 cols preserved (聚陽列管表)
                "m7_report_row": report_row,       # all 33 cols (聚陽 ERP m7_report)
                "pdf_cover_metadata_present": eidh in eidh_to_pdf_meta,
                "techpack_folder": safe(m7_row.get("TP資料夾")),
                "five_level_url": safe(m7_row.get("五階層網址")),
                "detail_url": safe(m7_row.get("細工段網址")),
                "sketch_url": safe(m7_row.get("Sketch")),
            },
            "_metadata": {
                "build_version": "v3_maximize",
                "step": "step2_designs_per_eidh",
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        }
        designs.append(design)

    print(f"    Files OK:         {n_files_ok:,} / {len(csv_files):,}")
    print(f"    Files no meta:    {n_files_no_meta:,}")
    print(f"    Rows processed:   {n_rows_processed:,} / {n_rows_total:,}")
    placeholder_total = sum(_PLACEHOLDER_DROPPED.values())
    if placeholder_total:
        print(f"    Placeholder drop: {placeholder_total:,} rows "
              f"(L2 new_part_={_PLACEHOLDER_DROPPED['l2']:,} / "
              f"L3 new_shape_design_={_PLACEHOLDER_DROPPED['l3']:,} / "
              f"L4 new_method_describe_={_PLACEHOLDER_DROPPED['l4']:,} / "
              f"L5 (NEW)={_PLACEHOLDER_DROPPED['l5']:,})")
    print(f"    Designs built:    {len(designs):,}")
    print(f"    Aggregated keys:  {len(agg):,}")

    # === 6. Write designs.jsonl ===
    print(f"\n[6] Write {OUT_DESIGNS.name} (per-EIDH 履歷)")
    with open(OUT_DESIGNS, "w", encoding="utf-8") as f:
        for d in designs:
            f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
    sz = OUT_DESIGNS.stat().st_size / 1024 / 1024
    print(f"    {len(designs):,} designs / {sz:.1f} MB")

    # === 7. Write source.jsonl (aggregated) ===
    print(f"\n[7] Write {OUT_SOURCE.name} (aggregated by 6-dim key)")
    n_written = 0
    with open(OUT_SOURCE, "w", encoding="utf-8") as f:
        for (gender, dept, gt, it, fabric, l1), entry in sorted(agg.items()):
            n_total = entry["n_steps"]
            client_dist = []
            for c, n in entry["client_counter"].most_common():
                client_dist.append({"client": c, "n": n, "pct": round(100 * n / n_total, 1)})

            by_client_out = {}
            for client_code, wk_dict in entry["by_client"].items():
                client_node = {"knit": [], "woven": []}
                for wk in ("knit", "woven"):
                    l2_dict = wk_dict.get(wk, {})
                    l2_list = []
                    for l2, l3_dict in l2_dict.items():
                        shapes = []
                        for l3, l4_dict in l3_dict.items():
                            methods = []
                            for l4, l5_steps in l4_dict.items():
                                seen = set()
                                unique_steps = []
                                for st in l5_steps:
                                    sig = (st["l5"], st["skill"], st["primary"])
                                    if sig in seen: continue
                                    seen.add(sig)
                                    unique_steps.append(st)
                                methods.append({"l4": l4, "l5_steps": unique_steps})
                            shapes.append({"l3": l3, "methods": methods})
                        l2_list.append({"l2": l2, "shapes": shapes})
                    client_node[wk] = l2_list
                by_client_out[client_code] = client_node

            confidence = "high" if n_total >= 50 else "medium" if n_total >= 10 else "low"

            source_entry = {
                "key": {"gender": gender, "dept": dept, "gt": gt,
                       "it": it, "fabric": fabric, "l1": l1},
                "source": "m7_pullon",
                "aggregation_level": "same_bucket",
                "n_total": n_total,
                "confidence": confidence,
                "iso_distribution": [],
                "methods": [],
                "client_distribution": client_dist,
                "by_client": by_client_out,
                "design_ids": sorted(list(entry["design_ids"]))[:50],
                "n_unique_designs": len(entry["design_ids"]),
                "ie_total_seconds": round(entry["ie_total_seconds"], 1),
                "_metadata": {
                    "build_version": "v3_maximize",
                    "step": "step2_source",
                    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "raw_source_dir": str(CSV_5LEVEL_DIR.relative_to(ROOT)),
                    "designs_sidecar": str(OUT_DESIGNS.relative_to(ROOT)),
                    "schema_note": "Aggregated by 6-dim key. Per-EIDH full履歷 in m7_pullon_designs.jsonl",
                },
            }
            f.write(json.dumps(source_entry, ensure_ascii=False, default=str) + "\n")
            n_written += 1
    sz2 = OUT_SOURCE.stat().st_size / 1024 / 1024
    print(f"    {n_written:,} entries / {sz2:.1f} MB")

    # === 8. Stats ===
    print(f"\n[8] Stats")
    fab_conf = Counter(d["fabric"]["confidence"] for d in designs)
    print(f"    fabric confidence: {dict(fab_conf)}")
    fab_value = Counter(d["fabric"]["value"] for d in designs)
    print(f"    fabric value:      {dict(fab_value)}")
    has_bom = sum(1 for d in designs if d["order"]["fabric_spec"])
    has_callout = sum(1 for d in designs if d["techpack_coverage"]["callout_count"] > 0)
    print(f"    has BOM fabric_spec: {has_bom}/{len(designs)}")
    print(f"    has techpack callout: {has_callout}/{len(designs)}")

    print(f"\n[next] push designs.jsonl + source.jsonl 到 platform:")
    print(f"  cp {OUT_DESIGNS} ../stytrix-techpack/data/ingest/m7_pullon/designs.jsonl")
    print(f"  cp {OUT_SOURCE} ../stytrix-techpack/data/ingest/m7_pullon/entries.jsonl")


if __name__ == "__main__":
    main()
