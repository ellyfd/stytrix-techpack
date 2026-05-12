"""
Derive data/runtime/brands.json from data/ingest/m7/entries.jsonl.

前端 index.html Brand 下拉以前硬寫 10 個 code,新 brand 進 m7 後
要手 sync。改成 CI 從 entries.jsonl 的 client_distribution 自動聚合,
brand 跟著 source 變動,不用手 patch frontend。

2026-05-12 改:source 從 m7_pullon/ 改成 m7/(2026-05-11 rename 沒完成,
本檔仍指 m7_pullon/ 導致 brands.json 永遠用 May 11 舊版)。

Output shape:
  {
    "generated_at": "2026-05-12T...",
    "source": "data/ingest/m7/entries.jsonl",
    "brands": [
      {"code": "ONY", "n_entries": 152, "n_designs": 800},
      ...
    ]
  }

排序:n_designs DESC(資料量最多的排前面),ties → code ASC。
"""
from __future__ import annotations

import datetime
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "data" / "ingest" / "m7" / "entries.jsonl"
OUT = REPO_ROOT / "data" / "runtime" / "brands.json"


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing source: {SRC}")

    n_entries = defaultdict(int)
    n_designs = defaultdict(int)

    with SRC.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            for c in entry.get("client_distribution") or []:
                code = c.get("client") if isinstance(c, dict) else None
                if not code:
                    continue
                n_entries[code] += 1
                n_designs[code] += int(c.get("n") or 0)

    brands = [
        {"code": code, "n_entries": n_entries[code], "n_designs": n_designs[code]}
        for code in n_entries
    ]
    brands.sort(key=lambda b: (-b["n_designs"], b["code"]))

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "data/ingest/m7/entries.jsonl",
        "brands": brands,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"brands: {len(brands)}")
    for b in brands:
        print(f"  {b['code']}: {b['n_designs']} designs ({b['n_entries']} entries)")
    print(f"Output: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
