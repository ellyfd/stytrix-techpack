"""build_recipes_master_v6.py — 完全對齊 Gap 4.3 標準 6-dim schema

Schema （vs v5）:
  v5:  key {gender, dept, gt(=PANTS), item_type(=KNIT), l1}
  v6:  key {gender, dept, gt(=BOTTOM), it(=PANTS/SHORTS/...), wk(=KNIT/WOVEN), l1}

差別：
  - gt 從 PANTS → BOTTOM (大類)
  - 新增 it: 從 design_id/program 抽 sub-type (PANTS/SHORTS/LEGGINGS/JOGGERS)
  - rename item_type → wk (布料分類)
  → 6-dim key 比 5-dim 精細

Pipeline:
  1. Load M7 索引 (1180 × eidh × client × subgroup × item × program × wk × design_id)
  2. derive (gender, dept, gt=BOTTOM, it, wk) per EIDH
  3. Walk m7_report 5lev steps → 6-dim bucket aggregation
  4. JOIN m7_detail sub-ops (machine + skill + section)
  5. JOIN facts_aligned (PDF callout ISO + method)
  6. ISO 三源 hybrid + EN canonical method translation
  7. Output recipes_master.json (對齊平台 schema)

用法：
  python scripts\\build_recipes_master_v6.py
"""
from __future__ import annotations
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
M7_ORG = ROOT / "m7_organized_v2"  # 2026-05-07：統一資料源
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback
# v6.1: 優先讀新版「M7列管」Excel (含 PRODUCT_CATEGORY 欄，1180 全 cover)
# fallback 到舊版 M7資源索引 (沒 PRODUCT_CATEGORY)
M7_INDEX_NEW = ROOT.parent / "M7列管_20260507.xlsx"
M7_INDEX_OLD = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
M7_INDEX = M7_INDEX_NEW if M7_INDEX_NEW.exists() else M7_INDEX_OLD
# v6.4: bible 五階字典（204K row × 38 L1 × 273 L2 × 1117 L3 + 圖片連結）
BIBLE = ROOT.parent / "五階層展開項目_20260402.xlsx"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
M7_DETAIL = DL / "data" / "ingest" / "metadata" / "m7_detail.csv"
FACTS_ALIGNED = M7_ORG / "aligned" / "facts_aligned.jsonl"
# 2026-05-07：vision_facts / designs 優先讀 m7_organized_v2，找不到 fallback DL
VISION_FACTS = M7_ORG / "vision_facts.jsonl" if (M7_ORG / "vision_facts.jsonl").exists() else DL / "data" / "ingest" / "unified" / "vision_facts.jsonl"
DESIGNS = M7_ORG / "designs.jsonl" if (M7_ORG / "designs.jsonl").exists() else DL / "data" / "ingest" / "metadata" / "designs.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
ISO_DICT = ROOT / "data" / "iso_dictionary.json"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts"))
from derive_metadata import derive_gender, derive_dept  # type: ignore


# ════════════════════════════════════════════════════════════
# L1 code → ZH/EN name（38 個 zone，給 five_tier 結構用）
# ════════════════════════════════════════════════════════════
def load_l1_to_zh():
    """從 zone_glossary 反查 L1 → 中文名"""
    try:
        g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
        return g.get("L1_STANDARD_38", {})
    except Exception:
        return {}


L1_ZH = load_l1_to_zh()  # {code: zh}，例：{"WB": "腰頭", "PS": "褲合身"}


# ════════════════════════════════════════════════════════════
# v6.4: Bible 五階字典載入（對齊 + 圖片連結）
# ════════════════════════════════════════════════════════════
def strip_marker(s) -> str:
    """Strip bible 的 ** 前綴（其它/補充標記）"""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.lstrip("*").strip()


def load_bible():
    """載入 bible 五階字典 → 三個 lookup table

    回傳：
      l1_to_l2:        {L1_zh → set(L2_zh)}
      l1_l2_to_l3:     {(L1_zh, L2_zh) → set(L3_zh)}
      chain_to_image:  {(L1_zh, L2_zh, L3_zh) → image_url}  # 取第一張變體圖
    """
    if not BIBLE.exists():
        print(f"    [warn] bible 不存在: {BIBLE}")
        return {}, {}, {}
    try:
        import pandas as pd
        df = pd.read_excel(BIBLE, sheet_name="工作表1", engine="calamine")
    except Exception as e:
        print(f"    [warn] bible 載入失敗: {e}")
        return {}, {}, {}

    l1_to_l2 = {}
    l1_l2_to_l3 = {}
    chain_to_image = {}

    for _, row in df.iterrows():
        l1 = strip_marker(row.get("部位", ""))
        l2 = strip_marker(row.get("零件", ""))
        l3 = strip_marker(row.get("形狀設計", ""))
        img = str(row.get("圖片連結") or "").strip()

        if not l1:
            continue
        l1_to_l2.setdefault(l1, set()).add(l2)
        l1_l2_to_l3.setdefault((l1, l2), set()).add(l3)
        # 取第一張看到的圖（同 chain 多變體圖選 _001 為代表）
        if img and "FiveLevel_MethodDescribe" in img:
            key = (l1, l2, l3)
            if key not in chain_to_image:
                chain_to_image[key] = img

    return l1_to_l2, l1_l2_to_l3, chain_to_image


BIBLE_L1_TO_L2, BIBLE_L1_L2_TO_L3, BIBLE_CHAIN_IMAGE = load_bible()
print(f"[bible] 載入：{len(BIBLE_L1_TO_L2)} L1 / {sum(len(v) for v in BIBLE_L1_TO_L2.values())} L2 / "
      f"{sum(len(v) for v in BIBLE_L1_L2_TO_L3.values())} (L1,L2)→L3 chain / "
      f"{len(BIBLE_CHAIN_IMAGE)} 圖片連結")

L1_EN = {
    "AE": "Armhole", "AH": "Sleeve Body", "BM": "Bottom Hem",
    "BN": "Bonded", "BP": "Hem Slit", "BS": "Buttonhole",
    "DC": "Drawcord", "DP": "Decoration", "FP": "Pocket Flap",
    "FY": "Front Placket", "HD": "Hood", "HL": "Loop",
    "KH": "Keyhole", "LB": "Label", "LI": "Lining",
    "LO": "Leg Opening", "LP": "Belt Loop", "NK": "Neck",
    "NP": "Collar", "NT": "Neck Binding", "OT": "Other",
    "PD": "Pleat", "PK": "Pocket", "PL": "Fly",
    "PS": "Pants Body", "QT": "Quilting", "RS": "Crotch Rise",
    "SA": "Top Panel Seam", "SB": "Bottom Panel Seam", "SH": "Shoulder",
    "SL": "Sleeve Cuff", "SP": "Sleeve Slit", "SR": "Skirt Body",
    "SS": "Side Seam", "ST": "Strap", "TH": "Thumbhole",
    "WB": "Waistband", "ZP": "Zipper",
}


def build_five_tier(recipe: dict, b: dict) -> dict:
    """v6.4: 構出 L1/L2/L3/L4/L5 顯式階層 + bible 對齊驗證 + 圖片連結

    對齊 stytrix-techpack 五階 spec + bible 五階字典（204K rows）：
      L1 = 部位（38）        ← key.l1（已有）
      L2 = 零件（273）       ← parts_zh，bible 驗證
      L3 = 形狀設計（1117）  ← shape_designs，bible 驗證
      L4 = 工法描述         ← method_codes + method_describes
      L5 = 細部工段         ← sections + machines + skills

    v6.4 vs v6.3 差別：
      - strip ** 前綴
      - 每階加 in_bible flag
      - 新增 chains（L1+L2+L3 共現）含 bible_image 連結
    """
    k = recipe["key"]
    l1_code = k.get("l1", "")
    l1_zh = L1_ZH.get(l1_code, "")
    n_st = b.get("n_steps", 0)
    n_subops = b.get("n_subops", 0)

    # bible lookup sets for this L1
    bible_l2_set = BIBLE_L1_TO_L2.get(l1_zh, set())
    bible_l3_set = set()
    for (l1_b, l2_b), l3s in BIBLE_L1_L2_TO_L3.items():
        if l1_b == l1_zh:
            bible_l3_set.update(l3s)

    def _pct_list_with_bible(counter, top_n, key_field, bible_set=None):
        """Counter → [{key, n, pct, in_bible}]; strip ** 前綴"""
        total = sum(counter.values()) or 1
        out = []
        for raw, n in counter.most_common(top_n):
            clean = strip_marker(raw)
            entry = {
                key_field: clean,
                "n": n,
                "pct": round(n / total * 100, 1),
            }
            if bible_set is not None:
                entry["in_bible"] = clean in bible_set
            out.append(entry)
        return out

    # L4 method describes 不需 bible 驗證（free text）
    md_total = sum(b["method_describes"].values()) or 1
    L4_describes = [
        {"text": strip_marker(t)[:200],
         "n": n,
         "pct": round(n / md_total * 100, 1)}
        for t, n in b["method_describes"].most_common(10)
    ]

    # ★ v6.4 新增：chains (L1, L2, L3) 共現 + bible 圖片連結
    # 從 b["l2_l3_tuples"] 抽，每筆查 bible image
    chain_total = sum(b["l2_l3_tuples"].values()) or 1
    chains = []
    for (l2_clean, l3_clean), n in b["l2_l3_tuples"].most_common(10):
        in_bible = (l2_clean in bible_l2_set) and (l3_clean in bible_l3_set)
        # 查圖片
        img = BIBLE_CHAIN_IMAGE.get((l1_zh, l2_clean, l3_clean), "")
        chains.append({
            "L2": l2_clean,
            "L3": l3_clean,
            "n": n,
            "pct": round(n / chain_total * 100, 1),
            "in_bible": in_bible,
            "bible_image": img if img else None,
        })

    return {
        "L1": {
            "code": l1_code,
            "zh": l1_zh,
            "en": L1_EN.get(l1_code, l1_code),
            "n_steps": n_st,
            "n_subops": n_subops,
            "in_bible": l1_zh in BIBLE_L1_TO_L2,
        },
        "L2_parts":            _pct_list_with_bible(b["parts_zh"], 10, "name", bible_l2_set),
        "L3_shape_designs":    _pct_list_with_bible(b["shape_designs"], 10, "shape", bible_l3_set),
        "L4_method_codes":     _pct_list_with_bible(b["method_codes"], 10, "code"),
        "L4_method_describes": L4_describes,
        "L5_sections":         _pct_list_with_bible(b["sections"], 15, "section"),
        "L5_machines":         _pct_list_with_bible(b["machines"], 10, "name"),
        "L5_skill_levels":     _pct_list_with_bible(b["skill_levels"], 5, "level"),
        "chains":              chains,  # ★ v6.4: (L1,L2,L3) 共現 + bible image
    }


def build_embedding_text(recipe: dict) -> str:
    """v6.3: 構出 RAG 用的 embedding text，含 5 階層 + client_distribution

    給平台 RAG 系統直接 index（不用自己挑欄位拼）。
    v6.3 修正：client 只出現 1 次（不依 pct 重複，避免 TF-IDF over-weight）
    """
    k = recipe["key"]
    parts = []

    # 1. Key dims（重複 = 強化權重）
    parts.append(f"{k['gender']} {k['gender']}")
    parts.append(f"{k['dept']} department")
    parts.append(f"{k['it']} {k['it']}")  # PANTS / SHORTS / LEGGINGS / JOGGERS
    parts.append(f"{k['wk']} fabric")
    parts.append(f"{k['gt']} bottom pull on pants")

    # 2. L1 zone code + ZH + EN
    l1 = k.get("l1", "")
    if l1:
        l1_en = L1_EN.get(l1, l1)
        l1_zh = L1_ZH.get(l1, "")
        parts.append(f"L1 {l1_en} {l1_en} {l1} {l1_zh}")
    if recipe.get("category_zh"):
        parts.append(recipe["category_zh"])

    # 3. L2 零件 (parts ZH) — strip ** 前綴
    for p in (recipe.get("top_parts") or [])[:5]:
        parts.append(strip_marker(p.get("name", "")))

    # 4. L3 形狀設計 (shape designs) — strip
    for s in (recipe.get("top_shape_designs") or [])[:3]:
        parts.append(strip_marker(s.get("shape", "")))

    # 5. L4 工法描述 ZH — strip
    for m in (recipe.get("top_method_describes") or [])[:3]:
        text = strip_marker(m.get("text", ""))[:50]
        if text:
            parts.append(text)

    # 6. L4 method codes — strip
    for m in (recipe.get("top_method_codes") or [])[:3]:
        c = strip_marker(m.get("code", ""))
        if c:
            parts.append(c)

    # 7. L5 細部工段 — strip
    for s in (recipe.get("top_sections") or [])[:5]:
        parts.append(strip_marker(s.get("section", "")))

    # 8. ISO distribution
    for iso in (recipe.get("iso_distribution") or [])[:5]:
        parts.append(f"ISO{iso.get('iso', '')}")

    # 9. EN methods
    for m in (recipe.get("methods") or [])[:5]:
        parts.append(str(m.get("name", "")))

    # 10. L5 機種 ZH
    for m in (recipe.get("top_machines") or [])[:3]:
        parts.append(str(m.get("name", "")))

    # 11. Client distribution — v6.3：每客戶只出現 1 次
    # （v6.2.1 依 pct 重複導致 TF-IDF over-weight client，dim hit 跌 -10%）
    for c in (recipe.get("client_distribution") or [])[:8]:
        client_name = str(c.get("client", "")).strip()
        if not client_name or client_name == "UNKNOWN":
            continue
        parts.append(client_name)

    return " ".join(p for p in parts if p).strip()


# ════════════════════════════════════════════════════════════
# Item Type 推導（Gap 4.3 標準）
# ════════════════════════════════════════════════════════════

def derive_item_type(design_id: str, program: str = "", item: str = "",
                     subgroup: str = "", client: str = "", dept: str = "") -> str:
    """從多個 signal 推褲型 sub-type
    Gap 4.3 標準：PANTS / SHORTS / LEGGINGS / JOGGERS / CAPRI / SKIRT

    優先序：
      1. 顯式 keyword（design_id/program/item/subgroup 含 LEGGING/JOGGER/SHORT/CAPRI/SKIRT）
      2. Subgroup heuristics（COMPRESSION/FLX/TIGHT → LEGGINGS；BIKE → SHORTS 等）
      3. Active brand prior（BY/UA/ATH/CALIA + dept=ACTIVE → LEGGINGS 而非 PANTS）
      4. fallback PANTS
    """
    text = f"{design_id} {program} {item} {subgroup}".upper()
    c = (client or "").upper().strip()
    d = (dept or "").upper().strip()

    # 1. 顯式 keyword
    if "LEGGING" in text or "TIGHT" in text:
        return "LEGGINGS"
    if "JOGGER" in text or "SWEATPANT" in text:
        return "JOGGERS"
    if "CAPRI" in text:
        return "CAPRI"
    if "SKIRT" in text or "SKORT" in text:
        return "SKIRT"
    if "BIKE SHORT" in text or "BIKER" in text:
        return "SHORTS"
    if "SHORT" in text:
        return "SHORTS"

    # 2. Subgroup heuristics — 暗示 LEGGINGS 的活躍系代碼
    if any(kw in text for kw in [
        "COMPRESSION",  # DSG COMPRESSION 系
        "BUTTERSOFT",   # Athleta legging line
        "POWERSOFT",    # Athleta legging line
        "PERFORMANCE TIGHT",
        "STUDIOSMOOTH",
        "ALL DAY",      # BY all-day legging
        "FLX",          # Flex (Old Navy active legging)
    ]):
        return "LEGGINGS"

    # 3. Active brand prior — 沒任何訊號時，active brand 預設 LEGGINGS
    # （依 brand 業務組合：BY/ATH/UA/CALIA 主力產品就是 leggings）
    ACTIVE_LEGGING_PRIOR = {
        "BEYOND YOGA": True,
        "ATHLETA": True,
        "UNDER ARMOUR": True,
        "CALIA": True,
    }
    if c in ACTIVE_LEGGING_PRIOR and d == "ACTIVE":
        return "LEGGINGS"

    # 4. fallback PANTS
    return "PANTS"


# ════════════════════════════════════════════════════════════
# Translation
# ════════════════════════════════════════════════════════════

def to_float(v):
    if v is None:
        return None
    s = str(v).replace(",", "")
    m = re.search(r'(-?\d+\.?\d*)', s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


def load_zh_to_l1():
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    return {zh: code for code, zh in g.get("L1_STANDARD_38", {}).items()}


def load_iso_dict():
    d = json.load(open(ISO_DICT, encoding="utf-8"))
    entries = d.get("entries", {})
    iso_to_en = {}
    zh_to_iso = {}
    machine_to_iso = {}
    for iso, info in entries.items():
        if info.get("en"):
            iso_to_en[iso] = info["en"]
        for z in (info.get("zh") or "").split("/"):
            z = z.strip()
            if z:
                zh_to_iso[z] = iso
        if info.get("machine"):
            m = re.search(r"[一-鿿]+", info["machine"])
            if m:
                machine_to_iso[m.group()] = iso
    return iso_to_en, zh_to_iso, machine_to_iso


ISO_TO_EN, ZH_TO_ISO_BASE, MACHINE_KW_TO_ISO = load_iso_dict()

# EN method → ISO 反查（一對一才反查，多 ISO 對同 EN 不反）
# 例如：514+516 都是 Overlock，反查不確定，跳過
_EN_COUNT = Counter(ISO_TO_EN.values())
EN_METHOD_TO_ISO = {en: iso for iso, en in ISO_TO_EN.items() if _EN_COUNT[en] == 1}

ZH_METHOD_TO_ISO = dict(ZH_TO_ISO_BASE)
ZH_METHOD_TO_ISO.update({
    "單針平車": "301", "扁針": "301", "車合": "301",
    "單針鎖鏈": "401", "單鎖": "401", "鏈縫": "401",
    "三本雙針": "406", "三本車": "406", "三本": "406", "壓三本": "406",
    "三本三針": "407",
    "三線拷克": "504", "拷": "514",
    "四線拷克": "514", "拷克": "514",
    "五線拷克": "516",
    "兩針四線爬網": "602", "四線爬網": "602",
    "三針五線爬網": "605", "爬網": "605", "五線爬網": "605",
    "併縫車": "607", "併縫": "607",
})

SPECIAL_ZH_TO_EN = {
    "打結": "Bartack", "鎖眼": "Buttonhole", "釘釦": "Button Attach",
    "燙轉熨": "Heat Press", "壓熱轉印": "Heat Transfer",
    "貼合": "Bonding", "燙": "Pressing",
    "做記號": "Marking", "修": "Trim", "手工": "Manual", "燙工": "Pressing",
}

OLD_EN_TO_CANONICAL = {
    "TOPSTITCH": "Lockstitch", "BARTACK": "Bartack",
    "COVERSTITCH": "Coverstitch", "FLATLOCK": "Flatlock",
    "OVERLOCK": "4-thread Overlock", "BINDING": "Flatseam Binding",
    "CHAINSTITCH": "Chainstitch", "BONDED": "Bonding",
    "BLINDHEM": "Blindhem", "ZIGZAG": "Zigzag",
}

ISO_NUM_RE = re.compile(r"\b(103|301|304|401|406|407|503|504|512|514|515|516|601|602|605|607)\b")


def zh_text_to_iso_method(text: str):
    if not text:
        return "", ""
    m = ISO_NUM_RE.search(text)
    if m:
        iso = m.group(1)
        return iso, ISO_TO_EN.get(iso, "")
    for zh in sorted(ZH_METHOD_TO_ISO.keys(), key=len, reverse=True):
        if zh in text:
            iso = ZH_METHOD_TO_ISO[zh]
            return iso, ISO_TO_EN.get(iso, "")
    for kw in sorted(MACHINE_KW_TO_ISO.keys(), key=len, reverse=True):
        if kw in text:
            iso = MACHINE_KW_TO_ISO[kw]
            return iso, ISO_TO_EN.get(iso, "")
    for zh, en in SPECIAL_ZH_TO_EN.items():
        if zh in text:
            return "", en
    return "", ""


def normalize_method_name(name: str) -> str:
    if not name:
        return name
    if name in ISO_TO_EN.values() or name in SPECIAL_ZH_TO_EN.values():
        return name
    upper = name.strip().upper()
    if upper in OLD_EN_TO_CANONICAL:
        return OLD_EN_TO_CANONICAL[upper]
    iso, en = zh_text_to_iso_method(name)
    if en:
        return en
    if iso and iso in ISO_TO_EN:
        return ISO_TO_EN[iso]
    return name


# ════════════════════════════════════════════════════════════
# Loaders
# ════════════════════════════════════════════════════════════

PRODUCT_CATEGORY_TO_GENDER = {
    "Women 女士": "WOMEN", "Women": "WOMEN",
    "Men 男士": "MEN", "Men": "MEN",
    "Boy 男童": "BOY", "Boy": "BOY", "Boys": "BOY",
    "Girl 女童": "GIRL", "Girl": "GIRL", "Girls": "GIRL",
    "Baby 嬰童": "BABY", "Baby": "BABY",
    "Kids 童裝": "KIDS", "Kids": "KIDS",
}


def load_m7_index():
    """eidh → {client, subgroup, item, program, wk, design_id, season, gender_excel}

    v6.1: 優先用新版 M7列管 Excel (含 PRODUCT_CATEGORY 欄)，filter Item="Pull On Pants"
    fallback 舊版 M7資源索引（沒 PRODUCT_CATEGORY，要靠 derive_gender 推）
    """
    by_eidh = {}
    if not M7_INDEX.exists():
        return by_eidh
    # 2026-05-08：用共用 m7_eidh_loader（套 ITEM_FILTER 含 PullOn+Leggings）
    import pandas as pd
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_m7_index as _load_m7_index
    try:
        df = _load_m7_index()
    except FileNotFoundError:
        return by_eidh
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        eidh = str(int(row["Eidh"]))
        # 新版才有 PRODUCT_CATEGORY
        gender_excel = "UNKNOWN"
        if "PRODUCT_CATEGORY" in row.index:
            cat = str(row.get("PRODUCT_CATEGORY", "") or "").strip()
            gender_excel = PRODUCT_CATEGORY_TO_GENDER.get(cat, "UNKNOWN")
        by_eidh[eidh] = {
            "eidh": int(eidh),
            "client": str(row.get("客戶", "") or "").strip().upper(),
            "subgroup": str(row.get("Subgroup", "") or "").strip(),
            "item": str(row.get("Item", "") or "").strip(),
            "program": str(row.get("Program", "") or "").strip(),
            "wk": str(row.get("W/K", "") or "").strip().upper(),
            "design_id": str(row.get("報價款號", "") or "").strip(),
            "season": str(row.get("Season", "") or "").strip(),
            "gender_excel": gender_excel,
        }
    return by_eidh


def load_m7_detail_index():
    if not M7_DETAIL.exists():
        return {}
    idx = defaultdict(list)
    with open(M7_DETAIL, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (
                (row.get("_eidh") or "").strip(),
                (row.get("category") or "").strip(),
                (row.get("part") or "").strip(),
                (row.get("Shape_Design") or "").strip(),
                (row.get("Method_Describe") or "").strip(),
            )
            idx[key].append({
                "section": (row.get("section") or "").strip(),
                "machine_name": (row.get("machine_name") or "").strip(),
                "skill_level": (row.get("Skill_Level") or "").strip(),
                "total_second": to_float(row.get("total_second")),
            })
    return idx


def load_facts_index_by_6dim(designs_meta_by_design_id, m7_idx):
    """facts_aligned + vision_facts → 6-dim key → list[(iso, method_en, client)]
    v6.2: 加 client，給 client_distribution 用
    v6.5: 補讀 vision_facts.jsonl（PDF VLM Sonnet 4.5 結果）
    """
    idx = defaultdict(list)

    # 收 fact 來源檔案（按優先順序）
    sources = []
    if FACTS_ALIGNED.exists():
        sources.append(("aligned", FACTS_ALIGNED))
    if VISION_FACTS.exists():
        sources.append(("vision", VISION_FACTS))

    n_per_source = {}
    for src_name, fpath in sources:
        n_added = 0
        n_total = 0
        for line in open(fpath, encoding="utf-8"):
            n_total += 1
            try:
                f = json.loads(line)
            except Exception:
                continue
            did = f.get("design_id")
            l1 = f.get("l1_code") or f.get("l1")
            iso = f.get("iso") or ""
            method = f.get("method") or ""
            if not did or not l1:
                continue
            d = designs_meta_by_design_id.get(did, {})
            client = (d.get("client") or "").upper().split("(")[0].strip()
            # vision_facts 內也有 client 欄位，直接用
            if not client:
                client = (f.get("client") or "").upper().split("(")[0].strip()
            subgroup = d.get("subgroup", "") or ""
            item = d.get("item") or ""
            program = d.get("program") or ""
            wk = (d.get("wk") or "").upper()
            design_id = d.get("design_id", did)
            # 優先 EIDH → Excel PRODUCT_CATEGORY / client
            eidh = d.get("eidh") or f.get("eidh")
            gender_excel = "UNKNOWN"
            if eidh:
                meta = m7_idx.get(str(eidh), {})
                gender_excel = meta.get("gender_excel", "UNKNOWN")
                # M7 索引 client 比 designs.jsonl 準確（有 PRODUCT_CATEGORY 對齊版）
                if meta.get("client"):
                    client = meta["client"].upper().split("(")[0].strip()
                # vision_facts 沒 design metadata，從 m7_idx 補
                if not item and meta.get("item"):
                    item = meta["item"]
                if not program and meta.get("program"):
                    program = meta["program"]
                if not wk and meta.get("wk"):
                    wk = meta["wk"].upper()
                if not design_id and meta.get("design_id"):
                    design_id = meta["design_id"]
            if gender_excel != "UNKNOWN":
                gender = gender_excel
            else:
                gender = derive_gender(client, subgroup) or "UNKNOWN"
            dept = derive_dept(client, program, subgroup) or "UNKNOWN"
            gt = "BOTTOM"
            it = derive_item_type(design_id, program, item, subgroup, client, dept)
            wk_val = wk if wk in ("KNIT", "WOVEN") else "UNKNOWN"
            key = (gender, dept, gt, it, wk_val, l1)
            idx[key].append((iso, method, client or "UNKNOWN"))
            n_added += 1
        n_per_source[src_name] = (n_added, n_total)

    # Print stats
    if n_per_source:
        print(f"    facts source breakdown:")
        for src_name, (n_added, n_total) in n_per_source.items():
            print(f"      {src_name:10}  {n_added:>5} added / {n_total:>5} read")

    return idx


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    print("[1] Load zone_glossary ZH→L1 mapping")
    zh_to_l1 = load_zh_to_l1()

    print("[2] Load M7 索引 (1180 EIDH metadata)")
    m7_idx = load_m7_index()
    print(f"    {len(m7_idx)} EIDH from M7 索引")

    print("[3] Load m7_detail.csv sub-ops")
    detail_idx = load_m7_detail_index()
    print(f"    {len(detail_idx)} unique 5lev keys from m7_detail")

    # designs.jsonl by design_id (for facts_aligned JOIN)
    designs_by_did = {}
    if DESIGNS.exists():
        for line in open(DESIGNS, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            did = d.get("design_id")
            if did:
                designs_by_did[did] = d
    print(f"    {len(designs_by_did)} designs in designs.jsonl")

    print("[4] Build PDF facts index (source a) — 6-dim")
    pdf_facts_idx = load_facts_index_by_6dim(designs_by_did, m7_idx)
    print(f"    {sum(len(v) for v in pdf_facts_idx.values())} facts → {len(pdf_facts_idx)} 6-dim buckets")

    print("[5] Walk m7_report.jsonl + JOIN m7_detail")
    if not M7_REPORT.exists():
        print(f"[!] {M7_REPORT} not found")
        sys.exit(1)

    buckets = defaultdict(lambda: {
        "n_steps": 0, "n_subops": 0,
        "n_eidhs": set(),
        "clients_cnt": Counter(),  # v6.2: Counter 取代 set，可拿 distribution
        "ie_seconds": [], "total_seconds": [],
        "iso_cnt_b": Counter(), "method_cnt_b_en": Counter(),
        "machines": Counter(), "skill_levels": Counter(), "sections": Counter(),
        "method_codes": Counter(), "method_describes": Counter(), "shape_designs": Counter(),
        "categories_zh": Counter(), "parts_zh": Counter(),
        "l2_l3_tuples": Counter(),  # v6.4: (L2_clean, L3_clean) 共現，給 chains + image lookup
    })

    skipped_no_meta = skipped_no_l1 = 0
    n_eidh = n_steps = n_steps_with_detail = 0

    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eidh = str(r.get("eidh", ""))
        if not eidh:
            continue

        meta = m7_idx.get(eidh, {})
        if not meta:
            client = (r.get("customer") or "").upper().split("(")[0].strip()
            subgroup = ""
            item = r.get("item", "") or ""
            program = ""
            wk = (r.get("wk") or "").upper()
            design_id = r.get("style_no") or ""
            gender_excel = "UNKNOWN"
        else:
            client = meta["client"]
            subgroup = meta["subgroup"]
            item = meta["item"]
            program = meta["program"]
            wk = meta["wk"]
            design_id = meta["design_id"]
            gender_excel = meta.get("gender_excel", "UNKNOWN")

        # 優先用 Excel PRODUCT_CATEGORY，fallback 才用 derive_gender 推
        if gender_excel != "UNKNOWN":
            gender = gender_excel
        else:
            gender = derive_gender(client, subgroup) or "UNKNOWN"
        dept = derive_dept(client, program, subgroup) or "UNKNOWN"
        gt = "BOTTOM"
        it = derive_item_type(design_id, program, item, subgroup, client, dept)
        wk_val = wk if wk in ("KNIT", "WOVEN") else "UNKNOWN"

        if gender == "UNKNOWN" and dept == "UNKNOWN":
            skipped_no_meta += 1
            continue

        n_eidh += 1
        steps = r.get("five_level_detail", [])
        for step in steps:
            cat_zh = (step.get("category") or "").strip()
            l1 = zh_to_l1.get(cat_zh)
            if not l1:
                skipped_no_l1 += 1
                continue
            n_steps += 1

            key = (gender, dept, gt, it, wk_val, l1)
            b = buckets[key]
            b["n_steps"] += 1
            b["n_eidhs"].add(eidh)
            # v6.2: client normalize（拿前綴，去 (...) 後綴）
            client_norm = (client or "").upper().split("(")[0].strip() or "UNKNOWN"
            b["clients_cnt"][client_norm] += 1

            ie_sec = to_float(step.get("ie_seconds"))
            tot_sec = to_float(step.get("total_second"))
            if ie_sec is not None:
                b["ie_seconds"].append(ie_sec)
            if tot_sec is not None:
                b["total_seconds"].append(tot_sec)

            mc = (step.get("method_code") or "").strip()
            mda = (step.get("method_describe_alt") or "").strip()
            sd = (step.get("shape_design") or "").strip()
            part = (step.get("part") or "").strip()
            md = (step.get("method_describe") or "").strip()
            if mc and not mc.startswith("new_method_describe_"):
                b["method_codes"][mc] += 1
            if mda:
                b["method_describes"][mda] += 1
            if sd:
                b["shape_designs"][sd] += 1
            b["categories_zh"][cat_zh] += 1
            if part:
                b["parts_zh"][part] += 1
            # v6.4: 抓 (L2, L3) 共現給 chains + bible image lookup
            if part and sd:
                b["l2_l3_tuples"][(strip_marker(part), strip_marker(sd))] += 1

            # ISO 抽 from m7 method text (source b)
            for txt in (mda, mc, md):
                iso, en = zh_text_to_iso_method(txt)
                if iso:
                    b["iso_cnt_b"][iso] += 1
                if en:
                    b["method_cnt_b_en"][en] += 1

            # JOIN sub-op detail
            join_key = (eidh, cat_zh, part, sd, mc)
            sub_ops = detail_idx.get(join_key, [])
            if sub_ops:
                n_steps_with_detail += 1
            for op in sub_ops:
                b["n_subops"] += 1
                if op["machine_name"]:
                    b["machines"][op["machine_name"]] += 1
                    # ISO 抽 from machine_name (source c)
                    iso_c, en_c = zh_text_to_iso_method(op["machine_name"])
                    if iso_c:
                        b["iso_cnt_b"][iso_c] += 1
                    if en_c:
                        b["method_cnt_b_en"][en_c] += 1
                if op["skill_level"]:
                    b["skill_levels"][op["skill_level"]] += 1
                if op["section"]:
                    b["sections"][op["section"]] += 1

    print(f"    {n_eidh} EIDH processed (skip {skipped_no_meta} no_meta)")
    print(f"    {n_steps:,} steps captured (skip {skipped_no_l1} no L1)")
    print(f"    {n_steps_with_detail:,} steps matched sub-ops ({n_steps_with_detail/max(n_steps,1)*100:.1f}%)")
    print(f"    {len(buckets)} unique 6-dim keys")

    print("\n[6] Aggregate → recipes")
    out_recipes = []
    for key, b in buckets.items():
        gender, dept, gt, it, wk_val, l1 = key
        n_st = b["n_steps"]
        n_eh = len(b["n_eidhs"])
        n_cl = len(b["clients_cnt"])  # v6.2: Counter 的 unique 鍵數
        if n_st >= 30 and n_cl >= 3:
            conf = "high"
        elif n_st >= 10 and n_cl >= 2:
            conf = "medium"
        elif n_st >= 5:
            conf = "low"
        else:
            conf = "very_low"

        # ISO + method 三源
        iso_cnt = Counter()
        method_cnt = Counter()
        # source (a) PDF facts (key 6-dim) — v6.2: tuple 多一欄 client
        for fact in pdf_facts_idx.get(key, []):
            # 兼容舊 (iso, method) 和新 (iso, method, client)
            if len(fact) == 3:
                iso, method, fact_client = fact
                # PDF facts 也計入 client_cnt
                fc = (fact_client or "").upper().split("(")[0].strip() or "UNKNOWN"
                b["clients_cnt"][fc] += 1
            else:
                iso, method = fact[0], fact[1]
            if iso:
                iso_cnt[iso] += 1
                canon = ISO_TO_EN.get(iso)
                if canon:
                    method_cnt[canon] += 1
                    continue
            if method:
                norm = normalize_method_name(method)
                method_cnt[norm] += 1
                # 反查：若 method 是 canonical EN（一對一映射）→ 補 ISO
                iso_back = EN_METHOD_TO_ISO.get(norm)
                if iso_back:
                    iso_cnt[iso_back] += 1
        # source (b)+(c) m7 method/machine text
        for iso, n in b["iso_cnt_b"].items():
            iso_cnt[iso] += n
        for m, n in b["method_cnt_b_en"].items():
            norm = normalize_method_name(m)
            method_cnt[norm] += n
            # 同上反查補 ISO
            iso_back = EN_METHOD_TO_ISO.get(norm)
            if iso_back:
                iso_cnt[iso_back] += n

        iso_total = sum(iso_cnt.values()) or 1
        method_total = sum(method_cnt.values()) or 1
        # v6.2: client distribution
        clients_total = sum(b["clients_cnt"].values()) or 1
        client_distribution = [
            {"client": c, "n": n, "pct": round(n / clients_total * 100, 1)}
            for c, n in b["clients_cnt"].most_common()
        ]
        # 重新算 n_cl（因為 PDF facts 可能補了新 client）
        n_cl = len(b["clients_cnt"])

        ies = b["ie_seconds"]
        recipe = {
            "key": {
                "gender": gender,
                "dept": dept,
                "gt": gt,
                "it": it,
                "wk": wk_val,
                "l1": l1,
            },
            "aggregation_level": "6dim_full",
            "source": "m7_pullon_v6.5",
            "n_total": n_st,
            "iso_distribution": [
                {"iso": iso, "n": n, "pct": round(n / iso_total * 100, 1)}
                for iso, n in iso_cnt.most_common()
            ],
            "methods": [
                {"name": m, "n": n, "pct": round(n / method_total * 100, 1)}
                for m, n in method_cnt.most_common()
            ],
            "confidence": conf,
            "n_designs": n_eh,
            "n_clients": n_cl,
            "client_distribution": client_distribution,
            "n_subops": b["n_subops"],
            "ie_avg_seconds": round(mean(ies), 3) if ies else None,
            "ie_median_seconds": round(median(ies), 3) if ies else None,
            "ie_min_seconds": round(min(ies), 3) if ies else None,
            "ie_max_seconds": round(max(ies), 3) if ies else None,
            "total_avg_seconds": round(mean(b["total_seconds"]), 1) if b["total_seconds"] else None,
            "category_zh": b["categories_zh"].most_common(1)[0][0] if b["categories_zh"] else "",
            "top_parts": [{"name": n, "count": c} for n, c in b["parts_zh"].most_common(5)],
            "top_method_codes": [{"code": c, "n": n} for c, n in b["method_codes"].most_common(5)],
            "top_method_describes": [{"text": t[:200], "n": n} for t, n in b["method_describes"].most_common(5)],
            "top_shape_designs": [{"shape": s, "n": n} for s, n in b["shape_designs"].most_common(5)],
            "top_machines": [{"name": m, "n": n} for m, n in b["machines"].most_common(5)],
            "top_skill_levels": [{"level": s, "n": n} for s, n in b["skill_levels"].most_common(5)],
            "top_sections": [{"section": s, "n": n} for s, n in b["sections"].most_common(10)],
        }
        # v6.3: 加 five_tier 顯式階層（L1/L2/L3/L4/L5 + pct 權重）
        recipe["five_tier"] = build_five_tier(recipe, b)
        # v6.2.1: 加 embedding_text（給平台 RAG 直接 index）
        recipe["embedding_text"] = build_embedding_text(recipe)
        out_recipes.append(recipe)

    out_recipes.sort(key=lambda r: -r["n_total"])

    # Output
    out_jsonl = OUT_DIR / "recipes_master_v6.jsonl"
    out_csv = OUT_DIR / "recipes_master_v6.csv"
    out_master = OUT_DIR / "recipes_master.json"

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in out_recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(out_master, "w", encoding="utf-8") as f:
        json.dump(out_recipes, f, ensure_ascii=False, indent=2)

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gender", "dept", "gt", "it", "wk", "l1", "category_zh",
                    "n_total", "n_designs", "n_clients", "confidence",
                    "top_client", "top_client_pct", "top3_clients",
                    "top_iso", "top_iso_pct",
                    "top_method_en", "top_method_pct",
                    "ie_avg_sec",
                    "iso_count", "method_count",
                    "top_machine", "top_skill", "top_section"])
        for r in out_recipes:
            k = r["key"]
            top_iso = r["iso_distribution"][0] if r["iso_distribution"] else {}
            top_m = r["methods"][0] if r["methods"] else {}
            cd = r.get("client_distribution") or []
            top_c = cd[0] if cd else {}
            top3 = " / ".join(f"{c['client']}({c['pct']}%)" for c in cd[:3])
            w.writerow([
                k["gender"], k["dept"], k["gt"], k["it"], k["wk"], k["l1"],
                r["category_zh"],
                r["n_total"], r["n_designs"], r["n_clients"], r["confidence"],
                top_c.get("client", ""), top_c.get("pct", ""), top3,
                top_iso.get("iso", ""), top_iso.get("pct", ""),
                top_m.get("name", ""), top_m.get("pct", ""),
                r.get("ie_avg_seconds") or "",
                len(r["iso_distribution"]), len(r["methods"]),
                r["top_machines"][0]["name"][:40] if r["top_machines"] else "",
                r["top_skill_levels"][0]["level"] if r["top_skill_levels"] else "",
                r["top_sections"][0]["section"] if r["top_sections"] else "",
            ])

    # Summary
    print(f"\n=== recipes_master_v6.5 summary ===")
    print(f"  total recipes:    {len(out_recipes)}")
    conf_dist = Counter(r["confidence"] for r in out_recipes)
    for c in ("high", "medium", "low", "very_low"):
        print(f"  {c:10}:       {conf_dist.get(c, 0)}")
    n_with_iso = sum(1 for r in out_recipes if r["iso_distribution"])
    n_with_method = sum(1 for r in out_recipes if r["methods"])
    n_with_client = sum(1 for r in out_recipes if r.get("client_distribution"))
    n_with_emb = sum(1 for r in out_recipes if r.get("embedding_text"))
    n_with_5tier = sum(1 for r in out_recipes if r.get("five_tier"))
    print(f"\n  with iso_distribution:    {n_with_iso}/{len(out_recipes)}")
    print(f"  with methods[]:           {n_with_method}/{len(out_recipes)}")
    print(f"  with client_distribution: {n_with_client}/{len(out_recipes)}")
    print(f"  with embedding_text:      {n_with_emb}/{len(out_recipes)}")
    print(f"  with five_tier:           {n_with_5tier}/{len(out_recipes)}")  # v6.3

    # v6.3: 5 階層 sample + v6.4: bible match
    if out_recipes:
        ft = out_recipes[0].get("five_tier", {})
        print(f"\n  sample five_tier[0]:")
        l1 = ft.get("L1", {})
        print(f"    L1: {l1.get('code')} ({l1.get('zh')} / {l1.get('en')}) — {l1.get('n_steps')} steps  [in_bible={l1.get('in_bible')}]")
        for level_key in ["L2_parts", "L3_shape_designs", "L4_method_codes", "L5_sections"]:
            items = ft.get(level_key, [])[:3]
            short = " | ".join(
                f"{(i.get('name') or i.get('shape') or i.get('code') or i.get('section') or '?')[:15]}({i.get('pct')}%)"
                + ("[Y]" if i.get('in_bible') else "[N]" if 'in_bible' in i else "")
                for i in items
            )
            print(f"    {level_key}: {short}")
        # v6.4: chains + image
        chains = ft.get("chains", [])[:3]
        print(f"    chains (L1+L2+L3 共現):")
        for c in chains:
            img_ok = "[img]" if c.get("bible_image") else "[no_img]"
            bible_ok = "[Y]" if c.get("in_bible") else "[N]"
            print(f"      {bible_ok}{img_ok} L2={c['L2'][:15]} | L3={c['L3'][:15]} ({c['pct']}%)")
        sample_emb = out_recipes[0].get("embedding_text", "")
        print(f"\n  sample embedding_text[0] (前 200):")
        print(f"    {sample_emb[:200]}{'...' if len(sample_emb) > 200 else ''}")

    # v6.4: bible match rate stats（across all recipes）
    print(f"\n  Bible 對齊率（across all recipes）:")
    n_l2_total = n_l2_in_bible = 0
    n_l3_total = n_l3_in_bible = 0
    n_chains_total = n_chains_in_bible = n_chains_with_image = 0
    for r in out_recipes:
        ft = r.get("five_tier", {})
        for item in ft.get("L2_parts", []):
            n_l2_total += 1
            if item.get("in_bible"):
                n_l2_in_bible += 1
        for item in ft.get("L3_shape_designs", []):
            n_l3_total += 1
            if item.get("in_bible"):
                n_l3_in_bible += 1
        for c in ft.get("chains", []):
            n_chains_total += 1
            if c.get("in_bible"):
                n_chains_in_bible += 1
            if c.get("bible_image"):
                n_chains_with_image += 1
    if n_l2_total:
        print(f"    L2 in bible:        {n_l2_in_bible}/{n_l2_total} ({n_l2_in_bible/n_l2_total*100:.1f}%)")
    if n_l3_total:
        print(f"    L3 in bible:        {n_l3_in_bible}/{n_l3_total} ({n_l3_in_bible/n_l3_total*100:.1f}%)")
    if n_chains_total:
        print(f"    chain in bible:     {n_chains_in_bible}/{n_chains_total} ({n_chains_in_bible/n_chains_total*100:.1f}%)")
        print(f"    chain with image:   {n_chains_with_image}/{n_chains_total} ({n_chains_with_image/n_chains_total*100:.1f}%) — UI 視覺對照可用")

    # Item type 分佈
    print(f"\n  Item Type 分佈:")
    for it, n in Counter(r["key"]["it"] for r in out_recipes).most_common():
        print(f"    {it:12} {n}")
    print(f"\n  W/K 分佈:")
    for wk, n in Counter(r["key"]["wk"] for r in out_recipes).most_common():
        print(f"    {wk:10} {n}")

    # v6.2 新增：Top-3 client 分佈
    print(f"\n  Top client (across all recipes):")
    all_clients = Counter()
    for r in out_recipes:
        for cd in (r.get("client_distribution") or []):
            all_clients[cd["client"]] += cd["n"]
    for c, n in all_clients.most_common(10):
        print(f"    {c:18} {n}")

    print(f"\n[output]")
    print(f"  {out_jsonl}")
    print(f"  {out_csv}")
    print(f"  {out_master}  ← 平台用這個")


if __name__ == "__main__":
    main()
