"""build_recipes_master_v5.py — 把 v4 轉換成平台 recipes_master.json schema

v4 schema (我們現有):
  key: {gender, dept, gt, item_type, l1}
  source: "m7_v4_..."
  n_steps, n_subops, n_eidhs, n_clients, confidence
  ie_avg_seconds, ie_median_seconds
  top_method_codes/describes (中文), top_machines, top_skills, top_sections

平台 schema (要對齊到):
  key: {gender, dept, gt, it, l1}             ← item_type → it
  source: "m7_pullon_v5"
  aggregation_level: "5dim_full"               ← 新增
  n_total                                      ← n_steps → n_total
  iso_distribution: [{iso, n, pct}, ...]       ← 從兩源 hybrid 抽
  methods: [{name (EN canonical), n, pct}, ...]← ZH → EN canonical 翻譯
  + 保留 v4 的 makalot 端細節 (top_machines / top_skills / top_sections / ie_*)

ISO 來源 hybrid:
  (a) JOIN facts_aligned.jsonl (PDF callout 抽到的) — 263 design cover, 嚴謹但少
  (b) Regex 從 method_describe / machine_name 抽 ISO 號 — 全 cover, fuzzy

用法：
  python scripts\\build_recipes_master_v5.py

輸出：
  outputs/platform/recipes_master_v5.jsonl
  outputs/platform/recipes_master_v5.csv
  outputs/platform/recipes_master.json   ← 平台直接吸這個 (鏡像 v5 的 array form)
"""
from __future__ import annotations
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
V4 = ROOT / "outputs" / "platform" / "recipes_master_v4.jsonl"
FACTS_ALIGNED = ROOT / "m7_organized_v2" / "aligned" / "facts_aligned.jsonl"
DESIGNS = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
ISO_DICT = ROOT / "data" / "iso_dictionary.json"
OUT_DIR = ROOT / "outputs" / "platform"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════════════════════
# ISO / Method translation tables — 從 iso_dictionary.json 讀
# ════════════════════════════════════════════════════════════

def load_iso_dict():
    """讀 data/iso_dictionary.json (canonical ISO 字典)
    Returns:
        ISO_TO_EN_METHOD: {iso → en canonical name}
        ZH_METHOD_TO_ISO: {zh substring → iso} (含口語別名)
        MACHINE_KW_TO_ISO: {machine 中文關鍵字 → iso}
    """
    d = json.load(open(ISO_DICT, encoding="utf-8"))
    entries = d.get("entries", {})
    iso_to_en = {}
    zh_to_iso = {}
    machine_to_iso = {}
    for iso, info in entries.items():
        en = info.get("en")
        zh = info.get("zh")
        machine = info.get("machine")
        if en:
            iso_to_en[iso] = en
        if zh:
            # 主 zh 名（可能含 "/")
            for z in zh.split("/"):
                z = z.strip()
                if z:
                    zh_to_iso[z] = iso
        if machine:
            # 從 machine 中抽中文部分作 keyword
            m = re.search(r"[一-鿿]+", machine)
            if m:
                machine_to_iso[m.group()] = iso
    return iso_to_en, zh_to_iso, machine_to_iso


ISO_TO_EN_METHOD, ZH_METHOD_TO_ISO_BASE, MACHINE_KW_TO_ISO = load_iso_dict()

# 補強：口語/簡寫別名
ZH_METHOD_TO_ISO = dict(ZH_METHOD_TO_ISO_BASE)
ZH_METHOD_TO_ISO.update({
    # 平車類
    "單針平車": "301", "扁針": "301", "車合": "301",
    # 鎖鍊類
    "單針鎖鏈": "401", "單鎖": "401", "鏈縫": "401",
    # 三本車類
    "三本雙針": "406", "三本車": "406", "三本": "406", "壓三本": "406",
    "三本三針": "407",
    # 拷克類
    "三線拷克": "504", "拷": "514",  # 模糊「拷」優先 514（最常見）
    "四線拷克": "514", "拷克": "514",
    "五線拷克": "516",
    # 爬網類
    "兩針四線爬網": "602", "四線爬網": "602",
    "三針五線爬網": "605", "爬網": "605", "五線爬網": "605",
    # 併縫類
    "併縫車": "607", "併縫": "607",
})

# 特殊中文 method → EN（沒 ISO 對應的，但平台仍用得到）
SPECIAL_ZH_TO_EN = {
    "打結": "Bartack",
    "鎖眼": "Buttonhole",
    "釘釦": "Button Attach",
    "燙轉熨": "Heat Press",
    "壓熱轉印": "Heat Transfer",
    "貼合": "Bonding",
    "燙": "Pressing",
    "做記號": "Marking",
    "修": "Trim",
    "手工": "Manual",
    "燙工": "Pressing",
}

# 舊版大寫 EN → 新 canonical（PDF facts_aligned 用舊大寫，要 normalize）
OLD_EN_TO_CANONICAL = {
    "TOPSTITCH": "Lockstitch",          # 301
    "BARTACK": "Bartack",
    "COVERSTITCH": "Coverstitch",       # 406
    "FLATLOCK": "Flatlock",             # 607
    "OVERLOCK": "4-thread Overlock",    # 514
    "BINDING": "Flatseam Binding",      # 605
    "CHAINSTITCH": "Chainstitch",       # 401
    "BONDED": "Bonding",
    "BLINDHEM": "Blindhem",             # 103
    "ZIGZAG": "Zigzag",                 # 304
}


def normalize_method_name(name: str) -> str:
    """把任何 method 字串 normalize 成新 canonical（iso_dictionary EN 風格）"""
    if not name:
        return name
    # 1. 已是 canonical → 不變
    if name in ISO_TO_EN_METHOD.values() or name in SPECIAL_ZH_TO_EN.values():
        return name
    # 2. 舊大寫
    upper = name.strip().upper()
    if upper in OLD_EN_TO_CANONICAL:
        return OLD_EN_TO_CANONICAL[upper]
    # 3. 中文 method（可能含 ISO 號碼） → 抽 ISO → canonical
    iso, en = zh_text_to_iso_method(name)
    if en:
        return en
    if iso and iso in ISO_TO_EN_METHOD:
        return ISO_TO_EN_METHOD[iso]
    return name  # unknown，留原值

ISO_NUM_RE = re.compile(r"\b(103|301|304|401|406|407|503|504|512|514|515|516|601|602|605|607)\b")


def zh_text_to_iso_method(text: str) -> tuple[str, str]:
    """從一段中文 text 抽 (iso, en_method)。失敗回 ("", "")。

    優先序:
      1. 直接含 ISO 號碼 (e.g., "ISO 401")
      2. 含 ZH method substring (e.g., "三本雙針")
      3. 含 machine 中文關鍵字 (e.g., "拷克車")
      4. 含 SPECIAL keyword (e.g., "打結")
    """
    if not text:
        return "", ""
    # 1. 直接 ISO
    m = ISO_NUM_RE.search(text)
    if m:
        iso = m.group(1)
        return iso, ISO_TO_EN_METHOD.get(iso, "")
    # 2. ZH method substring（依字串長度倒序，長 match 優先）
    for zh in sorted(ZH_METHOD_TO_ISO.keys(), key=len, reverse=True):
        if zh in text:
            iso = ZH_METHOD_TO_ISO[zh]
            return iso, ISO_TO_EN_METHOD.get(iso, "")
    # 3. machine 中文關鍵字（從 iso_dictionary 的 machine 欄）
    for kw in sorted(MACHINE_KW_TO_ISO.keys(), key=len, reverse=True):
        if kw in text:
            iso = MACHINE_KW_TO_ISO[kw]
            return iso, ISO_TO_EN_METHOD.get(iso, "")
    # 4. Special (BARTACK / Buttonhole / Heat Press 等)
    for zh, en in SPECIAL_ZH_TO_EN.items():
        if zh in text:
            return "", en
    return "", ""


# ════════════════════════════════════════════════════════════
# Build 5-dim ISO/method distribution from facts_aligned
# ════════════════════════════════════════════════════════════

def load_designs_meta():
    """design_id → {client, subgroup, item, program, wk}"""
    out = {}
    if not DESIGNS.exists():
        return out
    for line in open(DESIGNS, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        did = d.get("design_id")
        if did:
            out[did] = d
    return out


def build_facts_index_by_5dim(designs_meta):
    """facts_aligned.jsonl → bucket key → list[(iso, method_en)]
    bucket key = (gender, dept, gt, it, l1) [it 可能是 KNIT/WOVEN 或空]
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from derive_metadata import derive_gender, derive_dept, derive_garment_type  # type: ignore

    idx = defaultdict(list)
    if not FACTS_ALIGNED.exists():
        print(f"[!] {FACTS_ALIGNED} 不存在")
        return idx
    n = 0
    for line in open(FACTS_ALIGNED, encoding="utf-8"):
        try:
            f = json.loads(line)
        except Exception:
            continue
        n += 1
        did = f.get("design_id")
        l1 = f.get("l1_code") or f.get("l1") or f.get("l1_en")
        iso = f.get("iso") or ""
        method = f.get("method") or ""
        if not did or not l1:
            continue
        d = designs_meta.get(did, {})
        client = (d.get("client") or "").upper()
        subgroup = d.get("subgroup", "") or ""
        item = d.get("item") or ""
        program = d.get("program") or ""
        wk = d.get("wk") or ""

        gender = derive_gender(client, subgroup) or "UNKNOWN"
        dept = derive_dept(client, program, subgroup) or "UNKNOWN"
        gt = derive_garment_type(item) or "UNKNOWN"
        it = wk.upper() if wk else gt
        key = (gender, dept, gt, it, l1)
        idx[key].append((iso, method))
    print(f"  {n} facts indexed → {len(idx)} 5-dim buckets (PDF callout 端)")
    return idx


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    if not V4.exists():
        print(f"[!] {V4} 不存在 — 先跑 build_platform_recipes_v4.py")
        sys.exit(1)

    print("[1] Load v4 recipes")
    v4_recipes = []
    for line in open(V4, encoding="utf-8"):
        try:
            r = json.loads(line)
            v4_recipes.append(r)
        except Exception:
            continue
    print(f"    {len(v4_recipes)} recipes loaded")

    print("\n[2] Build PDF facts index (source a) — JOIN by 5-dim key")
    designs_meta = load_designs_meta()
    pdf_facts_idx = build_facts_index_by_5dim(designs_meta)

    print("\n[3] Translate v4 → platform schema")
    out_recipes = []
    for r in v4_recipes:
        k = r["key"]
        gender = k["gender"]
        dept = k["dept"]
        gt = k["gt"]
        it = k.get("item_type") or k.get("it") or ""
        l1 = k["l1"]
        bucket_key = (gender, dept, gt, it, l1)

        # ── ISO distribution: source (a) PDF facts ──
        # facts_aligned 帶舊大寫 EN，要 normalize 成新 canonical
        iso_cnt_a = Counter()
        method_cnt_a_en = Counter()
        for iso, method in pdf_facts_idx.get(bucket_key, []):
            if iso:
                iso_cnt_a[iso] += 1
                canon = ISO_TO_EN_METHOD.get(iso)
                if canon:
                    method_cnt_a_en[canon] += 1
                    continue
            if method:
                method_cnt_a_en[normalize_method_name(method)] += 1

        # ── ISO distribution: source (b) m7 method text 抽 ──
        iso_cnt_b = Counter()
        method_cnt_b_en = Counter()
        # 從 v4 的 top_method_describes / top_method_codes / top_machines 抽
        for src_field in ("top_method_describes", "top_method_codes", "top_machines"):
            items = r.get(src_field, [])
            for entry in items:
                text = entry.get("text") or entry.get("code") or entry.get("name") or ""
                n = entry.get("n", 1)
                iso, en = zh_text_to_iso_method(text)
                if iso:
                    iso_cnt_b[iso] += n
                if en:
                    method_cnt_b_en[en] += n

        # ── Combine: 優先 (a) PDF callout，補 (b)
        iso_combined = Counter()
        for iso, n in iso_cnt_a.items():
            iso_combined[iso] += n
        for iso, n in iso_cnt_b.items():
            iso_combined[iso] += n  # 直接加總

        method_combined = Counter()
        for m, n in method_cnt_a_en.items():
            method_combined[normalize_method_name(m)] += n
        for m, n in method_cnt_b_en.items():
            method_combined[normalize_method_name(m)] += n

        # 算百分比
        iso_total = sum(iso_combined.values()) or 1
        iso_dist = [
            {"iso": iso, "n": n, "pct": round(n / iso_total * 100, 1)}
            for iso, n in iso_combined.most_common()
        ]
        method_total = sum(method_combined.values()) or 1
        methods_list = [
            {"name": m, "n": n, "pct": round(n / method_total * 100, 1)}
            for m, n in method_combined.most_common()
        ]

        # ── 平台 schema entry
        new_recipe = {
            "key": {
                "gender": gender,
                "dept": dept,
                "gt": gt,
                "it": it,
                "l1": l1,
            },
            "aggregation_level": "5dim_full",
            "source": "m7_pullon_v5",
            "n_total": r.get("n_steps") or r.get("n_total", 0),
            "iso_distribution": iso_dist,
            "methods": methods_list,
            # 平台需要欄位以外，保留 v4 額外資訊（可選欄位）
            "confidence": r.get("confidence"),
            "n_designs": r.get("n_eidhs"),
            "n_clients": r.get("n_clients"),
            "n_subops": r.get("n_subops"),
            "ie_avg_seconds": r.get("ie_avg_sec_per_step") or r.get("ie_avg_seconds"),
            "ie_median_seconds": r.get("ie_median_sec_per_step") or r.get("ie_median_seconds"),
            "category_zh": r.get("category_zh"),
            "top_parts": r.get("top_parts"),
            "top_machines": r.get("top_machines"),
            "top_skill_levels": r.get("top_skill_levels"),
            "top_sections": r.get("top_sections"),
            # ISO 來源 audit
            "_iso_source_breakdown": {
                "from_pdf_facts": dict(iso_cnt_a),
                "from_m7_text": dict(iso_cnt_b),
            },
        }
        out_recipes.append(new_recipe)

    # 排序
    out_recipes.sort(key=lambda r: -r["n_total"])

    # ── 輸出 ──
    out_jsonl = OUT_DIR / "recipes_master_v5.jsonl"
    out_csv = OUT_DIR / "recipes_master_v5.csv"
    out_master_json = OUT_DIR / "recipes_master.json"  # 平台直接吸這個 array

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in out_recipes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(out_master_json, "w", encoding="utf-8") as f:
        json.dump(out_recipes, f, ensure_ascii=False, indent=2)

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["gender", "dept", "gt", "it", "l1",
                    "n_total", "n_designs", "n_clients", "confidence",
                    "top_iso", "top_iso_pct",
                    "top_method_en", "top_method_pct",
                    "ie_avg_sec",
                    "iso_count", "method_count",
                    "iso_a (pdf)", "iso_b (m7)"])
        for r in out_recipes:
            k = r["key"]
            top_iso = r["iso_distribution"][0] if r["iso_distribution"] else {}
            top_m = r["methods"][0] if r["methods"] else {}
            ab = r.get("_iso_source_breakdown", {})
            w.writerow([
                k["gender"], k["dept"], k["gt"], k["it"], k["l1"],
                r["n_total"], r["n_designs"], r["n_clients"], r["confidence"],
                top_iso.get("iso", ""), top_iso.get("pct", ""),
                top_m.get("name", ""), top_m.get("pct", ""),
                r.get("ie_avg_seconds") or "",
                len(r["iso_distribution"]), len(r["methods"]),
                sum(ab.get("from_pdf_facts", {}).values()),
                sum(ab.get("from_m7_text", {}).values()),
            ])

    # ── Summary ──
    print(f"\n=== recipes_master_v5 summary ===")
    print(f"  total recipes:     {len(out_recipes)}")
    conf_dist = Counter(r["confidence"] for r in out_recipes if r["confidence"])
    for c in ("high", "medium", "low", "very_low"):
        print(f"  {c:10}:        {conf_dist.get(c, 0)}")
    n_with_iso = sum(1 for r in out_recipes if r["iso_distribution"])
    n_with_method = sum(1 for r in out_recipes if r["methods"])
    print(f"\n  with iso_distribution: {n_with_iso} / {len(out_recipes)}")
    print(f"  with methods[]:        {n_with_method} / {len(out_recipes)}")
    print(f"\n[output]")
    print(f"  {out_jsonl}")
    print(f"  {out_csv}")
    print(f"  {out_master_json}  ← 平台用這個")


if __name__ == "__main__":
    main()
