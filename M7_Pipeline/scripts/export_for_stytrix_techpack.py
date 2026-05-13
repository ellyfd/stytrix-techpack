"""export_for_stytrix_techpack.py — 轉成 stytrix-techpack 平台 JSON 格式

Input:
  - outputs/sketch_l1_poc/{stem}.json   (VLM L1+L2+L3 偵測)
  - outputs/platform/recipes_master_v6.jsonl  (字典 ISO/methods/clients)
  - data/iso_dictionary.json   (ISO → 中文名+機種)
  - M7 索引   (EIDH → metadata)

Output:
  outputs/stytrix_techpack_json/{stem}.json
  → 直接貼進 stytrix-techpack 平台

UI Schema 反推（從截圖）：
  - filters: client / fabric / department / gender / garment_type / length
  - parts[]: 每部位含 primary_iso + alternative_isos + L2/L3 candidates
  - summary: total_parts / ai_detected / structure_inferred

用法:
  python scripts\\export_for_stytrix_techpack.py 306187_10406545_BEYOND_YOGA_SD1262
  python scripts\\export_for_stytrix_techpack.py --all
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH_POC_DIR = ROOT / "outputs" / "sketch_l1_poc"
RECIPES = ROOT / "outputs" / "platform" / "recipes_master_v6.jsonl"
ISO_DICT = ROOT / "data" / "iso_dictionary.json"
M7_INDEX_NEW = ROOT.parent / "M7列管_20260507.xlsx"
M7_INDEX_OLD = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
M7_INDEX = M7_INDEX_NEW if M7_INDEX_NEW.exists() else M7_INDEX_OLD

OUT_DIR = ROOT / "outputs" / "stytrix_techpack_json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts"))


# ════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════

PRODUCT_CATEGORY_TO_GENDER = {
    "Women 女士": "WOMENS", "Women": "WOMENS",
    "Men 男士": "MENS", "Men": "MENS",
    "Boy 男童": "BOYS", "Boy": "BOYS", "Boys": "BOYS",
    "Girl 女童": "GIRLS", "Girl": "GIRLS", "Girls": "GIRLS",
    "Baby 嬰童": "BABY", "Baby": "BABY",
    "Kids 童裝": "KIDS",
}

# L1 code → 中文 / 英文
L1_NAMES = {
    "AE": ("袖孔", "Armhole"), "AH": ("袖圍", "Sleeve Body"),
    "BM": ("下襬", "Bottom Hem"), "BN": ("貼合", "Bonded"),
    "BP": ("襬叉", "Hem Slit"), "BS": ("釦鎖", "Buttonhole"),
    "DC": ("繩類", "Drawcord"), "DP": ("裝飾片", "Decoration"),
    "FP": ("袋蓋", "Pocket Flap"), "FY": ("前立", "Front Placket"),
    "HD": ("帽子", "Hood"), "HL": ("釦環", "Loop"),
    "KH": ("Keyhole", "Keyhole"), "LB": ("商標", "Label"),
    "LI": ("裡布", "Lining"), "LO": ("褲口", "Leg Opening"),
    "LP": ("帶絆", "Belt Loop"), "NK": ("領", "Neck"),
    "NP": ("領襟", "Collar"), "NT": ("領貼條", "Neck Binding"),
    "OT": ("其它", "Other"), "PD": ("褶", "Pleat"),
    "PK": ("口袋", "Pocket"), "PL": ("門襟", "Fly"),
    "PS": ("褲合身", "Pants Body"), "QT": ("行縫(固定棉)", "Quilting"),
    "RS": ("褲襠", "Crotch Rise"), "SA": ("剪接線_上身類", "Top Panel Seam"),
    "SB": ("剪接線_下身類", "Bottom Panel Seam"), "SH": ("肩", "Shoulder"),
    "SL": ("袖口", "Sleeve Cuff"), "SP": ("袖叉", "Sleeve Slit"),
    "SR": ("裙合身", "Skirt Body"), "SS": ("脅邊", "Side Seam"),
    "ST": ("肩帶", "Strap"), "TH": ("拇指洞", "Thumbhole"),
    "WB": ("腰頭", "Waistband"), "ZP": ("拉鍊", "Zipper"),
}


def derive_item_type(design_id: str, program: str = "", item: str = "") -> str:
    """推 garment_type"""
    text = f"{design_id} {program} {item}".upper()
    if "LEGGING" in text:
        return "LEGGINGS"
    if "JOGGER" in text:
        return "JOGGERS"
    if "SHORT" in text:
        return "SHORTS"
    if "CAPRI" in text:
        return "CAPRI"
    return "PANTS"


def derive_length(design_id: str, item: str = "") -> str:
    """推褲長 (FULL LENGTH / 7/8 LENGTH / SHORTS / etc.)"""
    text = f"{design_id} {item}".upper()
    if "SHORT" in text:
        return "SHORTS"
    if "CAPRI" in text or "7/8" in text:
        return "7/8 LENGTH"
    if "ANKLE" in text:
        return "ANKLE"
    return "FULL LENGTH"


# ════════════════════════════════════════════════════════════
# Loaders
# ════════════════════════════════════════════════════════════

def load_iso_dict():
    d = json.load(open(ISO_DICT, encoding="utf-8"))
    return d.get("entries", {})


def load_m7_metadata():
    """用共用 helper 套 ITEM_FILTER（PullOn+Leggings 4644 件）"""
    import pandas as pd
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_m7_index as _load
    try:
        df = _load()
    except FileNotFoundError:
        return {}

    out = {}
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        eidh = str(int(row["Eidh"]))
        gender = "UNKNOWN"
        if "PRODUCT_CATEGORY" in row.index:
            cat = str(row.get("PRODUCT_CATEGORY", "") or "").strip()
            gender = PRODUCT_CATEGORY_TO_GENDER.get(cat, "UNKNOWN")
        out[eidh] = {
            "client": str(row.get("客戶", "") or "").strip().upper(),
            "subgroup": str(row.get("Subgroup", "") or "").strip(),
            "item": str(row.get("Item", "") or "").strip(),
            "program": str(row.get("Program", "") or "").strip(),
            "wk": str(row.get("W/K", "") or "").strip(),
            "design_id": str(row.get("報價款號", "") or "").strip(),
            "gender": gender,
        }
    return out


def load_recipes():
    out = []
    for line in open(RECIPES, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def index_recipes(recipes):
    by_key = {}
    by_loose = defaultdict(list)
    for r in recipes:
        k = r.get("key", {})
        full = (k.get("gender"), k.get("dept"), k.get("gt"), k.get("it"), k.get("wk"), k.get("l1"))
        by_key[full] = r
        loose = (k.get("gender"), k.get("gt"), k.get("l1"))
        by_loose[loose].append(r)
    return by_key, by_loose


# ════════════════════════════════════════════════════════════
# Build platform JSON
# ════════════════════════════════════════════════════════════

def build_iso_obj(iso_num: str, n: int, total: int, pct: float, iso_dict: dict) -> dict:
    """組 ISO 物件 — 含 zh/en/machine"""
    info = iso_dict.get(iso_num, {})
    return {
        "iso_number": iso_num,
        "iso_zh": info.get("zh", ""),
        "iso_en": info.get("en", ""),
        "machine": info.get("machine", ""),
        "n_samples": n,
        "total_samples": total,
        "percentage": pct,
    }


def build_part(idx: int, l1_part: dict, recipe: dict | None,
               by_loose: dict, key: tuple, iso_dict: dict) -> dict:
    """組單一部位 → 平台格式"""
    code = l1_part.get("code", "")
    zh = l1_part.get("zh") or L1_NAMES.get(code, ("", ""))[0]
    en = l1_part.get("en") or L1_NAMES.get(code, ("", ""))[1]

    # candidates (L2/L3/bible_code)
    cands = l1_part.get("l2_l3_candidates", [])
    if not cands and (l1_part.get("l2") or l1_part.get("l3")):
        cands = [{"l2": l1_part.get("l2", ""),
                  "l3": l1_part.get("l3", ""),
                  "bible_code": l1_part.get("bible_code", ""),
                  "l3_confidence": l1_part.get("l3_confidence", "low")}]

    # 加 bible_image 連結
    candidates_out = []
    for c in cands:
        bcode = c.get("bible_code", "")
        bible_image = ""
        if bcode:
            bible_image = f"\\\\192.168.1.39\\mtm\\Images\\FiveLevel_MethodDescribe\\{bcode}_001.png"
        candidates_out.append({
            "l2": c.get("l2", ""),
            "l3": c.get("l3", ""),
            "bible_code": bcode,
            "bible_image_unc": bible_image,
            "l3_confidence": c.get("l3_confidence", "low"),
        })

    # ISO 從 recipe.iso_distribution
    primary_iso = None
    alternative_isos = []
    n_total_samples = 0
    if recipe:
        iso_dist = recipe.get("iso_distribution", [])
        n_total_samples = sum(i.get("n", 0) for i in iso_dist)
        if iso_dist:
            top = iso_dist[0]
            primary_iso = build_iso_obj(
                top.get("iso", ""), top.get("n", 0),
                n_total_samples, top.get("pct", 0), iso_dict,
            )
            for alt in iso_dist[1:8]:  # top 7 替代
                alternative_isos.append(build_iso_obj(
                    alt.get("iso", ""), alt.get("n", 0),
                    n_total_samples, alt.get("pct", 0), iso_dict,
                ))

    # match_path / match_type — 之後 IE 業務規則決定，暫時 default
    match_path = "PATH 2"  # TODO: 由 recipe.aggregation_level 決定
    match_type = "同大類" if recipe else "loose match"
    if not recipe:
        loose_recipes = by_loose.get((key[0], key[2], key[5]), [])
        if loose_recipes:
            match_type = "fallback (loose)"

    return {
        "id": idx,
        "code": code,
        "name_zh": zh,
        "name_en": en,
        "detection_source": "ai",  # ai | structure | manual
        "vlm_confidence": l1_part.get("confidence", "low"),
        "vlm_visual_description": l1_part.get("visual_description", ""),
        "match_path": match_path,
        "match_type": match_type,
        "primary_iso": primary_iso,
        "alternative_isos": alternative_isos,
        "l2_l3_candidates": candidates_out,
    }


def export_one(sketch_data: dict, m7_meta: dict | None, recipes_by_key: dict,
               recipes_by_loose: dict, iso_dict: dict, sketch_filename: str) -> dict:
    """組整份平台 JSON"""
    meta = sketch_data.get("metadata", {})
    eidh = meta.get("eidh", "")
    design_id = meta.get("design_id", "")

    # 6-dim
    if m7_meta:
        gender = m7_meta.get("gender", "UNKNOWN")
        wk = m7_meta.get("wk", "Knit").upper()  # 平台用 Knit/Woven
        wk_display = "Knit" if wk == "KNIT" else ("Woven" if wk == "WOVEN" else wk.title())
        item = m7_meta.get("item", "")
        program = m7_meta.get("program", "")
        subgroup = m7_meta.get("subgroup", "")
        client_raw = m7_meta.get("client", "")
        it = derive_item_type(design_id, program, item)
        length = derive_length(design_id, item)
    else:
        gender = "UNKNOWN"
        wk_display = "Knit"
        client_raw = meta.get("client_raw", "").replace("_", " ")
        program = subgroup = ""
        it = derive_item_type(design_id)
        length = derive_length(design_id)

    # 推 dept (簡單版，從 derive_metadata)
    try:
        from derive_metadata import derive_dept  # type: ignore
        dept = derive_dept(client_raw, program, subgroup) or "Active"
    except Exception:
        dept = "Active"

    # client 縮寫（ONY = OLD NAVY 等）
    client_short_map = {
        "OLD NAVY": "ONY", "ATHLETA": "ATH", "GAP": "GAP",
        "GAP OUTLET": "GAP-OUT", "TARGET": "TGT",
        "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS",
        "UNDER ARMOUR": "UA", "BEYOND YOGA": "BY",
        "KOHLS": "KOH", "A & F": "ANF", "GU": "GU",
        "WAL-MART-CA": "WAL", "WALMART": "WAL",
    }
    client_short = client_short_map.get(client_raw.upper(), client_raw[:3].upper())

    # VLM 結果
    vision = sketch_data.get("vision_result", {})
    l1_parts = vision.get("l1_parts", [])

    # 對每個 L1 找 recipe + 組 part
    parts = []
    n_ai = n_struct = 0
    for i, p in enumerate(l1_parts, 1):
        l1_code = p.get("code", "")
        full_key = (gender, dept, "BOTTOM", it, wk_display.upper(), l1_code)
        recipe = recipes_by_key.get(full_key)
        if not recipe:
            # try with dept fallbacks
            for try_dept in ["Active", "RTW", "FLEECE", "SLEEPWEAR", "UNKNOWN"]:
                k = (gender, try_dept, "BOTTOM", it, wk_display.upper(), l1_code)
                if k in recipes_by_key:
                    recipe = recipes_by_key[k]
                    break
        part = build_part(i, p, recipe, recipes_by_loose, full_key, iso_dict)
        if part["detection_source"] == "ai":
            n_ai += 1
        else:
            n_struct += 1
        parts.append(part)

    return {
        "version": "1.0",
        "generator": "stytrix-pipeline-Source-Data/M7_Pipeline",
        "model": {
            "name": sketch_data.get("model", "claude-sonnet-4-5"),
            "elapsed_seconds": None,  # 沒記錄
            "cost_usd_cents": None,
        },
        "sketch": {
            "filename": sketch_filename,
            "image_path": f"m7_organized_v2/sketches/{sketch_filename}",
        },
        "metadata": {
            "eidh": eidh,
            "design_id": design_id,
            "client_full": client_raw,
            "client_short": client_short,
            "subgroup": subgroup,
            "program": program,
        },
        "filters": {
            "client": client_short,
            "fabric": wk_display,           # Knit | Woven
            "department": dept,             # Active | RTW | ...
            "gender": gender,               # WOMENS | MENS | ...
            "garment_type": it,             # PANTS | SHORTS | LEGGINGS | JOGGERS
            "length": length,               # FULL LENGTH | SHORTS | ...
        },
        "summary": {
            "total_parts": len(parts),
            "ai_detected": n_ai,
            "structure_inferred": n_struct,
        },
        "garment_overall": vision.get("garment_overall", ""),
        "image_quality": vision.get("image_quality", ""),
        "parts": parts,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sketch_stem", nargs="?")
    p.add_argument("--all", action="store_true")
    args = p.parse_args()

    print("[1] Load M7 metadata + ISO dict + recipes")
    m7_meta_idx = load_m7_metadata()
    iso_dict = load_iso_dict()
    recipes = load_recipes()
    by_key, by_loose = index_recipes(recipes)
    print(f"    {len(m7_meta_idx)} EIDH / {len(iso_dict)} ISOs / {len(recipes)} recipes")

    if args.all:
        sketch_jsons = sorted(SKETCH_POC_DIR.glob("*.json"))
    elif args.sketch_stem:
        sketch_jsons = [SKETCH_POC_DIR / f"{args.sketch_stem}.json"]
    else:
        print("[!] 請指定 sketch_stem 或 --all")
        sys.exit(1)

    print(f"\n[2] 處理 {len(sketch_jsons)} 個 sketch")
    n_ok = n_err = 0
    for sketch_json in sketch_jsons:
        if not sketch_json.exists():
            print(f"  [skip] {sketch_json.name} not found")
            continue
        stem = sketch_json.stem
        try:
            sketch_data = json.load(open(sketch_json, encoding="utf-8"))
            eidh = sketch_data.get("metadata", {}).get("eidh", "")
            m7_meta = m7_meta_idx.get(str(eidh))
            sketch_filename = sketch_data.get("sketch_file", f"{stem}.jpg")
            payload = export_one(sketch_data, m7_meta, by_key, by_loose, iso_dict, sketch_filename)
            out_path = OUT_DIR / f"{stem}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            n_parts = payload["summary"]["total_parts"]
            client = payload["filters"]["client"]
            gt = payload["filters"]["garment_type"]
            print(f"  [ok] {stem}  ({n_parts} parts, {client}/{gt})")
            n_ok += 1
        except Exception as e:
            print(f"  [err] {stem}: {e}")
            import traceback
            traceback.print_exc()
            n_err += 1

    print(f"\n[done] {n_ok} ok / {n_err} err")
    print(f"[output] {OUT_DIR}/")
    if sketch_jsons and n_ok > 0:
        print(f"\n第一個 sample:")
        sample = OUT_DIR / f"{sketch_jsons[0].stem}.json"
        if sample.exists():
            print(f"  notepad \"{sample}\"")


if __name__ == "__main__":
    main()
