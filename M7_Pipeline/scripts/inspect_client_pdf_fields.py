"""inspect_client_pdf_fields.py — 最大化盤點客戶 PDF metadata 欄位

從多個 source 收集所有客戶端 metadata 欄位 + values，給 Elly review 後填 mapping：

Sources:
  1. m7_organized_v2/designs.jsonl — 從 PDF cover 抽出來的（25+ 欄位）
  2. stytrix-pipeline-Download0504/data/ingest/metadata/designs.jsonl (legacy 395)
  3. m7_organized_v2/_fetch_manifest.csv — M7 索引 metadata
  4. M7列管_20260507.xlsx 總表 — 聚陽端 master schema
  5. m7_organized_v2/facts.jsonl — callout 抽出來的 zone keyword

跑：python scripts\\inspect_client_pdf_fields.py
輸出：outputs/client_metadata_full_inspection.md
"""
from __future__ import annotations
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from m7_eidh_loader import load_m7_index  # noqa: E402

OUT_MD = ROOT / "outputs" / "client_metadata_full_inspection.md"
OUT_MD.parent.mkdir(parents=True, exist_ok=True)


def load_designs_jsonl():
    """讀 designs.jsonl 兩個位置"""
    designs = []
    for p in [
        ROOT / "m7_organized_v2" / "designs.jsonl",
        ROOT.parent / "stytrix-pipeline-Download0504" / "data" / "ingest" / "metadata" / "designs.jsonl",
    ]:
        if p.exists():
            for line in open(p, encoding="utf-8"):
                try:
                    designs.append(json.loads(line))
                except Exception:
                    continue
    return designs


def main():
    print("[1] Load designs.jsonl ...")
    designs = load_designs_jsonl()
    by_client = defaultdict(list)
    for d in designs:
        c = (d.get("client") or "?").upper().split("(")[0].strip()
        by_client[c].append(d)
    print(f"    {len(designs)} designs across {len(by_client)} clients")

    print("[2] Load M7 索引 ...")
    df = load_m7_index()
    print(f"    {len(df)} rows × {len(df.columns)} cols")

    print("[3] Load facts.jsonl (zone keywords) ...")
    facts_zones = defaultdict(Counter)
    facts_path = ROOT / "m7_organized_v2" / "facts.jsonl"
    if facts_path.exists():
        for line in open(facts_path, encoding="utf-8"):
            try:
                f = json.loads(line)
                c = (f.get("client") or "?").upper().split("(")[0].strip()
                zone = f.get("zone_zh") or f.get("zone_en") or ""
                if zone:
                    facts_zones[c][zone] += 1
            except Exception:
                continue
    print(f"    {sum(sum(v.values()) for v in facts_zones.values())} facts across {len(facts_zones)} clients")

    print("[4] 產出 markdown 報告 ...")
    out = []
    out.append("# 客戶 PDF Metadata 最大化盤點\n")
    out.append("**目的**：每個客戶 PDF / M7 索引 / facts callout 出現過的所有欄位 + top values，給 Elly review 後填 mapping。\n")
    out.append("**Sources**：")
    out.append("- M7_Pipeline/m7_organized_v2/designs.jsonl + stytrix-pipeline-Download0504 legacy designs.jsonl")
    out.append("- M7列管_20260507.xlsx 總表（套 ITEM_FILTER 4,644 件）")
    out.append("- M7_Pipeline/m7_organized_v2/facts.jsonl（callout zone keyword）\n")

    out.append("## 聚陽 Canonical Schema（master）\n")
    out.append("| Field | Type | Top values | n |")
    out.append("|---|---|---|---|")
    canonical_cols = ['客戶', '報價款號', 'Subgroup', 'W/K', 'Item', 'Program', 'Season',
                      '產區', '製樣中心', 'PRODUCT_CATEGORY', 'Eidh', 'HEADER_SN',
                      'TP資料夾', 'CRFP', 'EXP', '實打', '標打', 'IE人員', '大貨技師',
                      'TechPack', 'IE', '圖/衣估', '樣衣', '專案控管', '訂單狀態']
    for col in canonical_cols:
        if col not in df.columns: continue
        s = df[col].dropna().astype(str)
        top = list(Counter(s).most_common(5))
        top_str = " / ".join(f"{k[:25]}({v})" for k, v in top)
        out.append(f"| {col} | str | {top_str} | {len(s)} |")
    out.append("")

    # 各客戶 metadata
    n_clients_seen = 0
    for client in sorted(by_client.keys(), key=lambda c: -len(by_client[c])):
        n = len(by_client[c])
        if n < 2:
            continue  # skip tiny clients
        n_clients_seen += 1
        out.append(f"\n## {client} ({n} designs in designs.jsonl)\n")

        # 從 designs.jsonl 取所有出現的 fields + values
        fields = defaultdict(Counter)
        for d in by_client[client]:
            for k, v in d.items():
                if v in (None, "", [], {}):
                    continue
                fields[k][str(v)[:50]] += 1

        out.append("### designs.jsonl 出現的欄位 + top values\n")
        out.append("| Field | n_filled | unique | Top 5 values |")
        out.append("|---|---:|---:|---|")
        for f in sorted(fields.keys(), key=lambda x: -sum(fields[x].values())):
            n_filled = sum(fields[f].values())
            n_unique = len(fields[f])
            top = list(fields[f].most_common(5))
            top_str = " / ".join(f"`{k[:35]}`({v})" for k, v in top)
            out.append(f"| {f} | {n_filled} | {n_unique} | {top_str} |")

        # M7 索引 column 值
        m7_sub = df[df["客戶"].astype(str).str.split("(").str[0].str.strip().str.upper() == client]
        if len(m7_sub) > 0:
            out.append(f"\n### M7 索引欄位（{len(m7_sub)} rows）\n")
            out.append("| Field | non-null | unique | Top 5 values |")
            out.append("|---|---:|---:|---|")
            for col in m7_sub.columns:
                s = m7_sub[col].dropna().astype(str)
                if len(s) == 0: continue
                top = list(Counter(s).most_common(5))
                top_str = " / ".join(f"`{k[:35]}`({v})" for k, v in top)
                out.append(f"| {col} | {len(s)} | {s.nunique()} | {top_str} |")

        # callout zones
        if client in facts_zones:
            out.append(f"\n### callout zone keywords (facts.jsonl)\n")
            zones = facts_zones[client].most_common(20)
            out.append("| zone | n |")
            out.append("|---|---:|")
            for z, n_z in zones:
                out.append(f"| {z} | {n_z} |")

    OUT_MD.write_text("\n".join(out), encoding="utf-8")
    print(f"\n[output] {OUT_MD}")
    print(f"  size: {OUT_MD.stat().st_size:,} bytes")
    print(f"  clients covered: {n_clients_seen}")


if __name__ == "__main__":
    main()
