"""show_vlm_status.py — 顯示 VLM Vision pipeline 當前狀態

讀 m7_organized_v2/callout_manifest.jsonl 跟 vision_facts.jsonl，列出：
  - manifest 總筆數 / type 分佈 / unique design
  - image-type 需要 VLM 的 design 數
  - 已在 vision_facts 處理過 / 待跑
  - 各 client 拆分

用：python scripts\\show_vlm_status.py
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"


def load_jsonl(p: Path):
    if not p.exists():
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        try: out.append(json.loads(line))
        except Exception: pass
    return out


def stats_for(label: str, manifest_path: Path, vision_path: Path):
    print(f"\n=== {label} ===")
    print(f"  manifest: {manifest_path}")
    print(f"  vision:   {vision_path}")
    if not manifest_path.exists():
        print(f"  [!] manifest 不存在，skip")
        return
    entries = load_jsonl(manifest_path)
    types = Counter(e.get("type", "?") for e in entries)
    designs_all = set((e.get("client", ""), e.get("design_id", "")) for e in entries)
    designs_image = set(
        (e.get("client", ""), e.get("design_id", "")) for e in entries if e.get("type") == "image"
    )
    done = set()
    for v in load_jsonl(vision_path):
        done.add((v.get("client", ""), v.get("design_id", "")))
    remaining = designs_image - done

    print(f"  entries:               {len(entries)}")
    print(f"  by type:               {dict(types)}")
    print(f"  unique designs:        {len(designs_all)}")
    print(f"  image-type designs:    {len(designs_image)}  (這些要走 VLM)")
    print(f"  already in vision:     {len(done & designs_image)}")
    print(f"  remaining to run:      {len(remaining)}")

    # Per-client breakdown of remaining
    if remaining:
        client_counts = Counter(c for c, _ in remaining)
        print(f"  remaining by client:")
        for c, n in client_counts.most_common():
            print(f"    {c:<10} {n:>3}")


def main():
    # 主：m7_organized_v2
    stats_for(
        "m7_organized_v2 (主)",
        M7_ORG / "callout_manifest.jsonl",
        M7_ORG / "vision_facts.jsonl",
    )
    # Legacy：stytrix-pipeline-Download0504（migration 前看 source 用）
    stats_for(
        "stytrix-pipeline-Download0504 (legacy)",
        DL / "data" / "ingest" / "pdf" / "callout_manifest.jsonl",
        DL / "data" / "ingest" / "unified" / "vision_facts.jsonl",
    )


if __name__ == "__main__":
    main()
