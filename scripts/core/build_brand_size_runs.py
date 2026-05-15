#!/usr/bin/env python3
"""Build data/runtime/brand_size_runs.json from data/source/盤x客人x尺寸套x基碼_v9.xlsx.

Why this file exists:
    pom_rules bucket 把 (brand × gender × GT) 的所有 design size 聯集塞進
    一個 `size_range`,前端原本拿 bucket size_range 當「整個 bucket 都同時用
    Alpha + Numeric + Plus」是錯的 — 實際每個 brand 在同一 gender 用哪幾套
    size run 是 per-brand 列管的(聚陽端「盤x客人x尺寸套x基碼_v9.xlsx」)。

    這個 script 把 xlsx 抽成 runtime lookup,前端依 (brand, gender) 決定
    Size Rule toggle 顯示哪幾個選項、每個選項的 sizes 跟 base 是什麼。

Output schema (data/runtime/brand_size_runs.json):
    {
      "_meta": { source, generated_at, version, threshold_n, sizeset_categories },
      "by_brand_gender": {
        "DKS|WOMENS": {
          "runs": [
            { "key": "alpha", "label": "MISSY字母(XS-XXL)", "sizes": [...], "base": "M", "n": 1039 },
            { "key": "numeric", "label": "數字碼", "sizes": [...], "base": "8", "n": 4 }
          ]
        }
      }
    }

xlsx 只列件數 >= 3 的 (brand × gender × 尺寸套);< 3 的會被聚陽端 drop。
不在這份 lookup 內的 (brand, gender) — 前端 fallback 用 bucket size_range
自動拆 alpha / numeric / plus(舊行為)。
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_XLSX = REPO_ROOT / "data" / "source" / "盤x客人x尺寸套x基碼_v9.xlsx"
OUT_JSON = REPO_ROOT / "data" / "runtime" / "brand_size_runs.json"

# 尺寸套 label → run category key
# Key 在前端決定 toggle 上顯示什麼 + 同類 run 合併規則。
SIZESET_CATEGORY = {
    "MISSY字母(XS-XXL)":        "alpha",
    "標準字母(XS-XXL)":         "alpha",
    "字母(XS-XXL)":             "alpha",
    "標準+BIG延伸(2XL-6XL)":    "alpha_big",
    "BIG(2XL-6XL)":             "big",
    "MISSY+PLUS(一條跨兩套)":   "alpha_plus",
    "PLUS(1X-4X)":              "plus",
    "數字碼":                    "numeric",
    "純數字斜線":                "numeric_slash",
    "字母數字斜線":              "alpha_numeric_slash",
    "PETITE(P碼/數字+P)":       "petite",
    "YOUTH(Y碼)":                "youth",
    "嬰幼兒(月齡+T碼)":          "infant",
}


def parse_sheet(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    out: list[dict[str, str]] = []
    for row in root.iter(NS + "row"):
        cells: dict[str, str] = {}
        for c in row.findall(NS + "c"):
            col = "".join(ch for ch in c.attrib["r"] if ch.isalpha())
            if c.attrib.get("t") == "inlineStr":
                cells[col] = "".join((tn.text or "") for tn in c.iter(NS + "t"))
            else:
                v = c.find(NS + "v")
                cells[col] = v.text if v is not None else None
        out.append(cells)
    return out


def split_sizes(s: str) -> list[str]:
    """Column F (canonical run) uses double-space between tokens. Split robustly."""
    if not s:
        return []
    return [tok for tok in re.split(r"\s+", s.strip()) if tok]


def main() -> int:
    if not SRC_XLSX.exists():
        print(f"ERROR: source xlsx not found: {SRC_XLSX}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(SRC_XLSX) as z:
        sheet1 = parse_sheet(z.read("xl/worksheets/sheet1.xml"))

    # Drop header + empty rows
    rows = [r for r in sheet1 if r.get("B") and r.get("B") != "客人"]

    by_bg: dict[str, list[dict]] = {}
    unknown_sizesets: set[str] = set()

    for r in rows:
        brand   = (r.get("B") or "").strip()
        gender  = (r.get("C") or "").strip()
        sizeset = (r.get("D") or "").strip()
        n_str   = (r.get("E") or "0").strip()
        canon   = (r.get("F") or "").strip()
        base    = (r.get("G") or "").strip()

        if not (brand and gender and sizeset and canon and base):
            continue

        try:
            n = int(n_str)
        except ValueError:
            n = 0

        category = SIZESET_CATEGORY.get(sizeset)
        if category is None:
            unknown_sizesets.add(sizeset)
            category = "unknown"

        sizes = split_sizes(canon)
        if not sizes:
            continue
        if base not in sizes:
            # 基碼 必須在 canonical run 內 — 不在就跳過(可能是手填錯)
            print(
                f"WARN: base {base!r} not in canonical run {sizes} for "
                f"{brand}|{gender}|{sizeset}; skipping",
                file=sys.stderr,
            )
            continue

        key = f"{brand}|{gender}"
        by_bg.setdefault(key, []).append({
            "key": category,
            "label": sizeset,
            "sizes": sizes,
            "base": base,
            "n": n,
        })

    # Sort each brand's runs by n descending (主流 size 套 在前)
    for runs in by_bg.values():
        runs.sort(key=lambda x: (-x["n"], x["label"]))

    out = {
        "_meta": {
            "source": "data/source/盤x客人x尺寸套x基碼_v9.xlsx",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "version": "v9",
            "threshold_n": 3,
            "sizeset_categories": SIZESET_CATEGORY,
            "n_brand_gender_combos": len(by_bg),
            "n_total_runs": sum(len(v) for v in by_bg.values()),
        },
        "by_brand_gender": dict(sorted(by_bg.items())),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"✓ wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    print(f"  {out['_meta']['n_brand_gender_combos']} (brand × gender) combos")
    print(f"  {out['_meta']['n_total_runs']} total size runs")
    if unknown_sizesets:
        print(f"  ⚠ unknown 尺寸套 categories: {sorted(unknown_sizesets)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
