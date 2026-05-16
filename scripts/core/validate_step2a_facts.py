#!/usr/bin/env python3
"""validate_step2a_facts.py — Step 2a output sanity gate (2026-05-16 P2)

跑在 rebuild_master.yml Step 2a (extract_unified.py) 跑完之後,Step 3
(build_recipes_master) 跑之前。catch:
  - facts.jsonl 不存在
  - facts.jsonl 0 行 (extract_unified 默默 fail 沒 throw)
  - facts.jsonl 行數異常低 (< threshold,可能 PPTX 解析整批壞)

通過 → exit 0,workflow 繼續。
失敗 → exit 1,workflow 擋 commit。

跑法 (CI 或本機):
  python scripts/core/validate_step2a_facts.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FACTS = ROOT / "data" / "ingest" / "unified" / "facts.jsonl"
DIM = ROOT / "data" / "ingest" / "unified" / "dim.jsonl"

# Threshold: 既有 baseline = facts_agg_rows ~1910 (2026-05-16),取保守下限 100
# 真正壞掉的場景 (PPTX 解析全壞 / extract_unified crash) 會掉到 < 50
MIN_FACTS_ROWS = 100


def main():
    errors = []

    if not FACTS.exists():
        errors.append(f"{FACTS} not found — Step 2a extract_unified.py 沒跑完")
    else:
        try:
            with open(FACTS, encoding="utf-8") as f:
                n_facts = sum(1 for line in f if line.strip())
            if n_facts < MIN_FACTS_ROWS:
                errors.append(
                    f"facts.jsonl 只有 {n_facts} 行 (threshold {MIN_FACTS_ROWS}) — "
                    f"PPTX 解析可能整批壞,或 unified merge 邏輯 broke"
                )
            else:
                print(f"[validate_step2a] ✓ facts.jsonl: {n_facts} rows (>= {MIN_FACTS_ROWS})")
        except Exception as e:
            errors.append(f"facts.jsonl parse fail: {e}")

    if not DIM.exists():
        errors.append(f"{DIM} not found — Step 2a dim 沒寫出來")
    else:
        try:
            with open(DIM, encoding="utf-8") as f:
                n_dim = sum(1 for line in f if line.strip())
            if n_dim < 1:
                errors.append(f"dim.jsonl empty")
            else:
                print(f"[validate_step2a] ✓ dim.jsonl: {n_dim} rows")
        except Exception as e:
            errors.append(f"dim.jsonl parse fail: {e}")

    if errors:
        for e in errors:
            print(f"[validate_step2a] ✗ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
