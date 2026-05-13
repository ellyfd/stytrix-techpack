"""extract_xlsx_callout.py — 從 WAL-MART 做工翻譯 xlsx 抽 construction callout

目標：補 25 個 PDF+PPT 都沒的 EIDH（多數 WAL-MART AWS 系列）。
這些 EIDH 的 tp_samples_v2/{eidh}_*/*.xlsx 是「做工翻譯」格式，含正規 callout 表。

Xlsx 格式：
  - Sheet "針法" 或類似（row 14-25 是 callout 表）
  - row 15 header: Location | Description / Construction | ISO Standard
  - row 16+: zone × description × ISO 號

抽取規則：
  - Location (zone) → 用 KW_TO_L1_BOTTOMS 對到 L1 code
  - Description → method 描述
  - ISO Standard → regex 抽 ISO 號

輸出：
  data/ingest/unified/xlsx_facts.jsonl  （每行一個 fact）

用法：
  python scripts\\extract_xlsx_callout.py [--reset]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
TP_DIR = ROOT / "tp_samples_v2"
OUT = DL / "data" / "ingest" / "unified" / "xlsx_facts.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"

# 載入 zone mapping
def load_kw_to_l1():
    g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
    return g.get("KW_TO_L1_BOTTOMS", {})


KW_TO_L1 = load_kw_to_l1()
ISO_RE = re.compile(r"\b(103|301|304|401|406|407|503|504|512|514|515|516|601|602|605|607)\b")
EIDH_RE = re.compile(r"^(\d{6})")

# Sheet 名 candidate（依優先順序，「針法」優先；「做工翻譯」是 narrative 不是 callout）
SHEET_NAMES = ["針法", "Construction", "Workmanship", "STITCH", "ISO"]
# 排除這些 sheet（名字含 keyword 但內容不是 callout 表）
SKIP_SHEETS = ["做工翻譯", "參考圖片", "主副料", "COST", "尺寸", "MMT", "ARTWORK", "BRAND HANDOVER",
               "Data", "DocTracking", "GRADED"]


def normalize_zone(zone_str: str) -> str:
    """Zone 字串 → L1 code（用 KW_TO_L1_BOTTOMS）"""
    if not zone_str:
        return ""
    text = zone_str.upper().replace(" ", "").replace("/", "")
    # 試找最長 match
    for kw in sorted(KW_TO_L1.keys(), key=len, reverse=True):
        if kw in text:
            l1_code = KW_TO_L1[kw]
            if isinstance(l1_code, list):
                return l1_code[0]
            return l1_code
    return ""


def extract_isos(iso_str: str) -> list[str]:
    """從 ISO Standard 欄位抽所有 ISO 號"""
    if not iso_str:
        return []
    return ISO_RE.findall(iso_str)


def find_callout_section(df, max_search_rows=30):
    """找 'Location' / 'Description' / 'ISO Standard' header row"""
    import pandas as pd
    for i in range(min(max_search_rows, len(df))):
        row_text = " ".join(
            str(v).upper() for v in df.iloc[i].values
            if pd.notna(v)
        )
        if (("LOCATION" in row_text or "LOC " in row_text)
            and ("DESCRIPTION" in row_text or "CONSTRUCTION" in row_text)
            and ("ISO" in row_text)):
            return i
    return -1


def extract_one_xlsx(eidh, xlsx_path, design_id="", debug=False):
    """從一個 xlsx 抽 facts，回傳 list[fact]"""
    import pandas as pd

    facts = []
    try:
        xl = pd.ExcelFile(xlsx_path, engine="calamine")
    except Exception as e:
        return [], f"open_fail:{e}"

    # 1. 優先試 SHEET_NAMES 列表（針法 / Construction / Workmanship 等）
    # 2. fallback 到所有 sheet（除了 SKIP_SHEETS）
    # 3. 找到第一個有 Location+Description+ISO header 的 sheet
    target_sheet = None
    header_row = -1

    # Priority list
    priority_sheets = [s for s in xl.sheet_names if any(kw in s for kw in SHEET_NAMES)]
    other_sheets = [s for s in xl.sheet_names
                    if s not in priority_sheets
                    and not any(skip in s for skip in SKIP_SHEETS)]
    candidates = priority_sheets + other_sheets

    for sn in candidates:
        try:
            df = pd.read_excel(xlsx_path, sheet_name=sn, engine="calamine", header=None)
        except Exception:
            continue
        hr = find_callout_section(df)
        if hr >= 0:
            target_sheet = sn
            header_row = hr
            if debug:
                print(f"    [match] sheet '{sn}' header at row {hr}")
            break

    if not target_sheet:
        return [], "no_header"

    df = pd.read_excel(xlsx_path, sheet_name=target_sheet, engine="calamine", header=None)

    # 從 header_row + 1 開始抽 callout
    for i in range(header_row + 1, len(df)):
        row = df.iloc[i]
        vals = [str(v).strip() if pd.notna(v) else "" for v in row.values]
        if not any(vals):
            break  # 空白行 = 段落結束

        # 通常是 [Location, Description, ISO] 三欄
        # 但 columns 可能變動，找有意義的非空 cell
        non_empty = [v for v in vals if v and v != "0"]
        if len(non_empty) < 2:
            break  # 只剩 1 欄 = 結束

        zone_str = non_empty[0]
        # 排除 ISO STITCH STANDARDS 段
        if "ISO STITCH" in zone_str.upper() or "STANDARDS" in zone_str.upper():
            break
        # 排除 metadata header
        if any(k in zone_str.upper() for k in ["LOCATION", "DESCRIPTION", "ISO STAND"]):
            continue

        l1 = normalize_zone(zone_str)
        if not l1:
            if debug:
                print(f"    [skip zone] {zone_str[:30]}")
            continue

        description = non_empty[1] if len(non_empty) > 1 else ""
        iso_str = non_empty[2] if len(non_empty) > 2 else ""
        # ISO 也可能在 description 裡（"ISO#406"）
        full_text = f"{description} {iso_str}"
        isos = extract_isos(full_text)
        if not isos:
            continue

        for iso in set(isos):
            facts.append({
                "design_id": design_id,
                "eidh": eidh,
                "source": "xlsx_callout",
                "source_file": xlsx_path.name,
                "l1_code": l1,
                "zone_zh": zone_str,
                "iso": iso,
                "method": "",
                "method_describe": description[:200],
                "confidence": "explicit",
            })

    return facts, "ok"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    if args.reset and OUT.exists():
        OUT.unlink()
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # 找所有 xlsx
    xlsx_by_eidh = {}
    for sub in TP_DIR.iterdir():
        if not sub.is_dir():
            continue
        m = EIDH_RE.match(sub.name)
        if not m:
            continue
        eidh = int(m.group(1))
        # 找含「做工翻譯」/「翻譯」/「workmanship」/「construction」字眼的 xlsx
        for f in sub.iterdir():
            if not f.is_file():
                continue
            if f.suffix.lower() not in (".xlsx", ".xls"):
                continue
            if any(kw in f.name for kw in ["做工", "翻譯", "Workmanship", "Construction", "WORKMANSHIP"]):
                xlsx_by_eidh[eidh] = f
                break

    print(f"[scan] 找到 {len(xlsx_by_eidh)} 個 EIDH 有「做工翻譯」xlsx")

    n_ok = n_err = n_facts = 0
    err_reasons = {}
    open_mode = "a" if OUT.exists() else "w"
    with open(OUT, open_mode, encoding="utf-8") as fout:
        for i, (eidh, f) in enumerate(sorted(xlsx_by_eidh.items())):
            # 從資料夾名取 design_id（{eidh}_{design_id}）
            sub = f.parent
            parts = sub.name.split("_", 1)
            design_id = parts[1] if len(parts) >= 2 else ""

            facts, status = extract_one_xlsx(eidh, f, design_id, debug=args.debug)
            if status == "ok" and facts:
                for fact in facts:
                    fout.write(json.dumps(fact, ensure_ascii=False) + "\n")
                n_ok += 1
                n_facts += len(facts)
                if args.debug or i < 5:
                    print(f"  [{i}/{len(xlsx_by_eidh)}] {eidh}: {len(facts)} facts ({f.name[:50]})")
            else:
                n_err += 1
                err_reasons[status] = err_reasons.get(status, 0) + 1
                if args.debug:
                    print(f"  [{i}/{len(xlsx_by_eidh)}] {eidh}: ERR {status}")

    print(f"\n[done] {n_ok} ok / {n_err} err / {n_facts} facts")
    print(f"[output] {OUT}")
    print(f"\nError 分類:")
    for r, n in sorted(err_reasons.items(), key=lambda x: -x[1]):
        print(f"  {r:30} {n}")
    print(f"\n[next] cat xlsx_facts.jsonl >> facts_aligned.jsonl 然後重跑 v6")


if __name__ == "__main__":
    main()
