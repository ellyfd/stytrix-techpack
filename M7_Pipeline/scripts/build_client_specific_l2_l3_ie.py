"""build_client_specific_l2_l3_ie.py — 從 m7_report 1180 件抽 client-specific 五階

Output schema 對齊 platform 現有 l2_l3_ie/<L1>.json 但加 by_client:
{
  "l1": "腰頭",
  "code": "WB",
  "by_client": {
    "ONY": {
      "knit":  [{"l2": "...", "shapes": [{"l3": "...", "methods": [...]}]}],
      "woven": [...]
    },
    "TGT": {...},
    "GAP": {...},
    ...
  },
  "client_stats": {
    "ONY": {"n_designs": 230, "total_steps": 5388, "ie_total_seconds": 92345},
    ...
  }
}

讓平台聚陽模型 UI 選 brand 後，從 by_client[brand_code] 取該客戶的真實五階。

用法：
  python scripts\\build_client_specific_l2_l3_ie.py
"""
from __future__ import annotations
import json
import re
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
M7_INDEX = ROOT.parent / "M7列管_20260507.xlsx"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
OUT_DIR = ROOT / "outputs" / "platform" / "l2_l3_ie_by_client"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# Client 縮寫 mapping (對齊 platform UI BRANDS)
CLIENT_TO_CODE = {
    "OLD NAVY": "ONY",
    "TARGET": "TGT",
    "GAP": "GAP",
    "GAP OUTLET": "GAP",  # merge to GAP
    "DICKS SPORTING GOODS": "DKS",
    "DICKS": "DKS",
    "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA",
    "KOHLS": "KOH",
    "A & F": "ANF",
    "GU": "GU",
    "BEYOND YOGA": "BY",
}


# 2026-05-07：聚陽 IE 簡體/誤字 normalization（m7_report 共 31 筆「檔底片」應為「襠底片」）
# 規範：襠 (dāng, crotch piece) 是身體部位；檔 (dàng, 中間檔次) 是 POM measurement context
# 做工 callout 用「襠」；POM Rise 維度用「檔」
ZH_NORMALIZE = {
    "檔底片": "襠底片",   # 簡體誤字 / 輸入法錯字
    "褶底片": "襠底片",   # AI hallucinate fallback（極少出現在源資料，保險起見）
}


def normalize_zh(s: str) -> str:
    """套用 ZH_NORMALIZE 替換 — 用於 L2/L3/L4/L5 文字欄位"""
    if not s:
        return s
    for bad, good in ZH_NORMALIZE.items():
        s = s.replace(bad, good)
    return s


def strip_marker(s: str) -> str:
    """Strip bible 的 ** 前綴 + zh normalize"""
    if not s:
        return ""
    return normalize_zh(s.lstrip("*").strip())


def load_l1_zh_to_code():
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    L1 = g.get("L1_STANDARD_38", {})
    return {zh: code for code, zh in L1.items()}, L1  # zh→code, code→zh


def normalize_client(raw: str) -> str | None:
    """Client 縮寫：BEYOND YOGA → BY；不認識就回 None（跳過）"""
    if not raw:
        return None
    cleaned = raw.upper().split("(")[0].strip()
    return CLIENT_TO_CODE.get(cleaned)


def load_m7_metadata_by_eidh():
    """eidh → {client, wk}（用共用 helper，套 ITEM_FILTER）"""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_m7_index
    try:
        df = load_m7_index()
    except FileNotFoundError:
        return {}
    out = {}
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        eidh = str(int(row["Eidh"]))
        out[eidh] = {
            "client_raw": str(row.get("客戶", "") or "").strip(),
            "wk": str(row.get("W/K", "") or "").strip().upper(),
        }
    return out


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


def main():
    print("[1] Load M7 metadata + zone glossary")
    m7_meta = load_m7_metadata_by_eidh()
    zh_to_code, code_to_zh = load_l1_zh_to_code()
    print(f"    {len(m7_meta)} EIDH metadata loaded")

    # Aggregate: by_client[client][L1_code][wk][L2][L3][L4] -> [(L5, skill, sec, 主副), ...]
    print("[2] Walk m7_report 1180 PullOn EIDH, aggregate by (client, L1, wk, L2, L3, L4) → L5 steps")
    # nested defaultdict: by_client[code][L1][wk][L2][L3][L4] = list of (L5, skill, sec, 主副)
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))))
    client_stats = defaultdict(lambda: {"n_designs": set(), "total_steps": 0, "ie_total_seconds": 0.0})

    n_eidh_processed = 0
    n_eidh_no_client = 0
    n_step_no_client = 0
    n_step_no_l1 = 0
    n_step_processed = 0

    for line in open(M7_REPORT, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        eidh = str(r.get("eidh", ""))
        meta = m7_meta.get(eidh, {})
        client_code = normalize_client(meta.get("client_raw", "") or r.get("customer", ""))
        wk = meta.get("wk", "").upper()
        if wk not in ("KNIT", "WOVEN"):
            wk = "knit"  # default
        wk = wk.lower()

        if not client_code:
            n_eidh_no_client += 1
            continue

        n_eidh_processed += 1
        client_stats[client_code]["n_designs"].add(eidh)

        for s in r.get("five_level_detail", []):
            cat = (s.get("category") or "").strip()
            l1_code = zh_to_code.get(cat)
            if not l1_code:
                n_step_no_l1 += 1
                continue

            l2 = strip_marker(s.get("part") or "")
            l3 = strip_marker(s.get("shape_design") or "")
            l4 = strip_marker(s.get("method_describe_alt") or s.get("method_code") or "")
            l5 = normalize_zh((s.get("method_describe") or "").strip())
            skill = (s.get("skill_level") or s.get("Skill_Level") or "").strip()
            sec = to_float(s.get("total_second"))
            primary = (s.get("primary") or s.get("主副") or "主").strip()

            if not l2 or not l3:
                continue

            # 存 step (L5 + skill + sec + 主副)
            step = [l5 or l4, skill or "", sec or 0.0, primary or "主"]
            agg[client_code][l1_code][wk][l2][l3].setdefault(l4 or "?", []).append(step)

            n_step_processed += 1
            client_stats[client_code]["total_steps"] += 1
            if sec:
                client_stats[client_code]["ie_total_seconds"] += sec

    # 把 set 換 int (n_designs)
    for code in client_stats:
        client_stats[code]["n_designs"] = len(client_stats[code]["n_designs"])
        client_stats[code]["ie_total_seconds"] = round(client_stats[code]["ie_total_seconds"], 1)

    print(f"\n  EIDH processed:     {n_eidh_processed}")
    print(f"  EIDH no client:     {n_eidh_no_client}")
    print(f"  Steps processed:    {n_step_processed:,}")
    print(f"  Steps no L1:        {n_step_no_l1}")
    print(f"\n  Client stats:")
    for c, s in sorted(client_stats.items(), key=lambda x: -x[1]["total_steps"]):
        print(f"    {c:5} designs={s['n_designs']:>4} steps={s['total_steps']:>5} ie_sec={s['ie_total_seconds']:>9,.1f}")

    # [3] 對每個 L1，輸出 by_client schema
    print("\n[3] Output l2_l3_ie_by_client/<L1>.json")
    for l1_code in sorted(zh_to_code.values()):
        l1_zh = code_to_zh.get(l1_code, "")
        out = {
            "l1": l1_zh,
            "code": l1_code,
            "by_client": {},
            "client_stats": dict(client_stats),
        }
        for client_code, l1_dict in agg.items():
            wk_dict = l1_dict.get(l1_code, {})
            if not wk_dict:
                continue
            client_node = {"knit": [], "woven": []}
            for wk in ("knit", "woven"):
                l2_dict = wk_dict.get(wk, {})
                l2_list = []
                for l2_name, l3_dict in l2_dict.items():
                    shapes = []
                    for l3_name, l4_dict in l3_dict.items():
                        methods = []
                        for l4_name, steps in l4_dict.items():
                            # dedup steps
                            seen = set()
                            unique_steps = []
                            for st in steps:
                                key = tuple(st[:2])  # (L5_name, skill)
                                if key not in seen:
                                    seen.add(key)
                                    unique_steps.append(st)
                            methods.append({"l4": l4_name, "steps": unique_steps})
                        shapes.append({"l3": l3_name, "methods": methods})
                    l2_list.append({"l2": l2_name, "shapes": shapes})
                client_node[wk] = l2_list
            out["by_client"][client_code] = client_node

        # 只在有客戶資料時 output (跳過完全空的 L1，例如 PullOn 不會用的 NK/SH)
        if out["by_client"]:
            out_path = OUT_DIR / f"{l1_code}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)

    # 寫 _index.json
    idx_path = OUT_DIR / "_index.json"
    files_with_data = sorted([p.stem for p in OUT_DIR.glob("*.json") if p.stem != "_index"])
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump({
            "l1_codes_with_data": files_with_data,
            "client_codes": sorted(agg.keys()),
            "client_stats": dict(client_stats),
            "source": "m7_report.jsonl 1180 PullOn EIDH",
            "version": "v1",
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  Output {len(files_with_data)} L1 files (with data) + _index.json")
    print(f"  Path: {OUT_DIR}")
    print(f"\n  Sample (WB):")
    if (OUT_DIR / "WB.json").exists():
        wb = json.load(open(OUT_DIR / "WB.json", encoding="utf-8"))
        for code in sorted(wb["by_client"].keys()):
            knit_n = len(wb["by_client"][code].get("knit", []))
            woven_n = len(wb["by_client"][code].get("woven", []))
            print(f"    WB {code}: knit={knit_n} L2 / woven={woven_n} L2")


if __name__ == "__main__":
    main()
