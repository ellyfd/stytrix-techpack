"""report_l5_bible_alignment.py — designs.jsonl 五階 steps 對得上 Bible canonical 嗎?

每筆 design 的 `five_level_steps[]` 含 (L1, L2, L3, L4, L5, primary, skill, machine, sec)。
Bible(stytrix-techpack/l2_l3_ie/<L1>.json 38 檔)是 canonical 結構,每 L5 step 是 list
`[l5, skill, sec, primary, machine]`。

Audit:每筆 design 的 (L1, knit_or_woven, L2, L3, L4, L5) tuple 是否存在於 Bible?

輸出:
  console — coverage 表
  outputs/platform/l5_bible_alignment.txt — 完整報告 + mismatch / orphan 清單

跑:python scripts/report_l5_bible_alignment.py [--bible-root <path>]
"""
from __future__ import annotations
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGNS = ROOT / "outputs" / "platform" / "m7_pullon_designs.jsonl"
DEFAULT_BIBLE_ROOT = Path(r"C:\temp\stytrix-techpack\l2_l3_ie")
OUT = ROOT / "outputs" / "platform" / "l5_bible_alignment.txt"


def load_bible(bible_root: Path) -> tuple[
    set,                 # full tuples (L1, wk, L2, L3, L4, L5)
    set,                 # (L1, wk, L2)
    set,                 # (L1, wk, L2, L3)
    set,                 # (L1, wk, L2, L3, L4)
    dict,                # L1 code → 中文 zh name
]:
    """Walk Bible JSON,build hierarchical sets for fast lookup"""
    full_tuples = set()
    l2_set = set()
    l3_set = set()
    l4_set = set()
    l1_zh = {}

    bible_files = sorted(bible_root.glob("*.json"))
    bible_files = [f for f in bible_files if f.name != "_index.json"]
    print(f"[bible] loading {len(bible_files)} L1 JSON files from {bible_root}")

    for f in bible_files:
        try:
            data = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] {f.name}: {e}")
            continue
        l1 = data.get("code") or f.stem
        l1_zh[l1] = data.get("l1", "")

        for wk in ("knit", "woven"):
            l2_list = data.get(wk, [])
            if not isinstance(l2_list, list):
                continue
            for l2_node in l2_list:
                if not isinstance(l2_node, dict):
                    continue
                l2 = l2_node.get("l2", "")
                l2_set.add((l1, wk, l2))
                shapes = l2_node.get("shapes", [])
                if not isinstance(shapes, list):
                    continue
                for shape in shapes:
                    if not isinstance(shape, dict):
                        continue
                    l3 = shape.get("l3", "")
                    l3_set.add((l1, wk, l2, l3))
                    methods = shape.get("methods", [])
                    if not isinstance(methods, list):
                        continue
                    for method in methods:
                        if not isinstance(method, dict):
                            continue
                        l4 = method.get("l4", "")
                        l4_set.add((l1, wk, l2, l3, l4))
                        steps = method.get("steps", [])
                        if not isinstance(steps, list):
                            continue
                        for step in steps:
                            if isinstance(step, list) and len(step) >= 1:
                                l5 = step[0]
                                full_tuples.add((l1, wk, l2, l3, l4, l5))
                            elif isinstance(step, dict):
                                # Phase 2 升級後 dict schema
                                l5 = step.get("l5", "")
                                full_tuples.add((l1, wk, l2, l3, l4, l5))

    print(f"  full tuples (L1×wk×L2×L3×L4×L5):  {len(full_tuples):,}")
    print(f"  L4 set:                           {len(l4_set):,}")
    print(f"  L3 set:                           {len(l3_set):,}")
    print(f"  L2 set:                           {len(l2_set):,}")
    return full_tuples, l2_set, l3_set, l4_set, l1_zh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bible-root", default=str(DEFAULT_BIBLE_ROOT))
    args = ap.parse_args()

    full_tuples, l2_set, l3_set, l4_set, l1_zh = load_bible(Path(args.bible_root))

    if not DESIGNS.exists():
        print(f"[FAIL] {DESIGNS} not found,先跑 build_m7_pullon_source_v3.py")
        return 1

    # === Walk designs ===
    print(f"\n[walk] reading {DESIGNS.relative_to(ROOT)}")
    n_designs = 0
    n_steps = 0
    mismatch_full = Counter()       # (L1, wk, L2, L3, L4, L5) 不在 Bible 的 count
    mismatch_l4 = Counter()         # (L1, wk, L2, L3, L4) 不在 Bible
    mismatch_l3 = Counter()
    mismatch_l2 = Counter()

    used_full = set()
    by_l1 = defaultdict(lambda: [0, 0])     # l1_code → [matched, total]
    by_brand = defaultdict(lambda: [0, 0])  # brand → [matched, total]
    by_l1_l2 = defaultdict(lambda: [0, 0])

    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            n_designs += 1
            brand = d.get("client", {}).get("code", "?")
            fabric = (d.get("fabric") or {}).get("value", "").lower()
            if fabric not in ("knit", "woven"):
                continue  # skip 無 fabric design
            steps = d.get("five_level_steps") or []
            for s in steps:
                n_steps += 1
                l1 = s.get("l1", "")
                l2 = s.get("l2", "")
                l3 = s.get("l3", "")
                l4 = s.get("l4", "")
                l5 = s.get("l5", "")
                tup = (l1, fabric, l2, l3, l4, l5)
                used_full.add(tup)

                in_bible = tup in full_tuples
                by_l1[l1][1] += 1
                by_brand[brand][1] += 1
                by_l1_l2[(l1, l2)][1] += 1
                if in_bible:
                    by_l1[l1][0] += 1
                    by_brand[brand][0] += 1
                    by_l1_l2[(l1, l2)][0] += 1
                else:
                    mismatch_full[tup] += 1
                    # 試降一層找出哪一層斷
                    if (l1, fabric, l2, l3, l4) not in l4_set:
                        mismatch_l4[(l1, fabric, l2, l3, l4)] += 1
                    elif (l1, fabric, l2, l3) not in l3_set:
                        mismatch_l3[(l1, fabric, l2, l3)] += 1
                    elif (l1, fabric, l2) not in l2_set:
                        mismatch_l2[(l1, fabric, l2)] += 1

    n_match = sum(c[0] for c in by_l1.values())
    pct_match = 100 * n_match / n_steps if n_steps else 0

    # === Bible orphan: 在 Bible 但 designs 沒用 ===
    bible_orphan = full_tuples - used_full

    # === Output ===
    lines = []
    def emit(s=""): print(s); lines.append(s)

    emit("=" * 110)
    emit(f"L5 Bible Alignment Report")
    emit(f"  source:  {DESIGNS.relative_to(ROOT)}")
    emit(f"  bible:   {args.bible_root}")
    emit("=" * 110)
    emit(f"\n[Overall]")
    emit(f"  n_designs:                {n_designs:>8,}")
    emit(f"  n_steps (total):          {n_steps:>8,}")
    emit(f"  matched to Bible:         {n_match:>8,}  ({pct_match:>5.1f}%)")
    emit(f"  mismatch (not in Bible):  {n_steps - n_match:>8,}  ({100 - pct_match:>5.1f}%)")
    emit(f"  unique tuples used:       {len(used_full):>8,}")
    emit(f"  Bible canonical tuples:   {len(full_tuples):>8,}")
    emit(f"  Bible orphans:            {len(bible_orphan):>8,}  (Bible 有但 designs 沒用)")

    emit(f"\n[per L1 — coverage]")
    emit(f"  {'L1':5} {'L1_zh':10} {'matched':>8} {'total':>8} {'pct%':>6}")
    for l1 in sorted(by_l1.keys(), key=lambda k: -by_l1[k][1]):
        m, t = by_l1[l1]
        pct = 100 * m / t if t else 0
        zh = l1_zh.get(l1, "?")
        emit(f"  {l1:5} {zh:10} {m:>8,} {t:>8,} {pct:>5.1f}%")

    emit(f"\n[per Brand — coverage]")
    emit(f"  {'brand':10} {'matched':>8} {'total':>8} {'pct%':>6}")
    for brand in sorted(by_brand.keys(), key=lambda k: -by_brand[k][1]):
        m, t = by_brand[brand]
        pct = 100 * m / t if t else 0
        emit(f"  {brand:10} {m:>8,} {t:>8,} {pct:>5.1f}%")

    emit(f"\n[Mismatch breakdown — 哪一層斷掉?]")
    emit(f"  L2 不在 Bible:           {sum(mismatch_l2.values()):>8,}  unique={len(mismatch_l2):>4}")
    emit(f"  L3 不在 Bible (L2 OK):   {sum(mismatch_l3.values()):>8,}  unique={len(mismatch_l3):>4}")
    emit(f"  L4 不在 Bible (L3 OK):   {sum(mismatch_l4.values()):>8,}  unique={len(mismatch_l4):>4}")
    emit(f"  L5 不在 Bible (L4 OK):   {sum(mismatch_full.values()) - sum(mismatch_l4.values()) - sum(mismatch_l3.values()) - sum(mismatch_l2.values()):>8,}")

    emit(f"\n[Top 30 mismatch (full tuple, count desc)]")
    for tup, n in mismatch_full.most_common(30):
        l1, wk, l2, l3, l4, l5 = tup
        emit(f"  {n:>5} × {l1}/{wk}/{l2}/{l3}/{l4[:30]}/{l5[:30]}")

    emit(f"\n[Top 20 missing L4 (Bible 缺方法,可能 IE 要補結構)]")
    for tup, n in mismatch_l4.most_common(20):
        l1, wk, l2, l3, l4 = tup
        emit(f"  {n:>5} × {l1}/{wk}/{l2}/{l3}/[{l4[:50]}]")

    emit(f"\n[Top 20 missing L3]")
    for tup, n in mismatch_l3.most_common(20):
        l1, wk, l2, l3 = tup
        emit(f"  {n:>5} × {l1}/{wk}/{l2}/[{l3}]")

    emit(f"\n[Top 20 missing L2]")
    for tup, n in mismatch_l2.most_common(20):
        l1, wk, l2 = tup
        emit(f"  {n:>5} × {l1}/{wk}/[{l2}]")

    emit(f"\n[Top 20 Bible orphans — Bible 有但 designs 沒用]")
    orphan_by_l3 = Counter()
    for tup in bible_orphan:
        l1, wk, l2, l3, l4, l5 = tup
        orphan_by_l3[(l1, wk, l2, l3)] += 1
    for tup, n in orphan_by_l3.most_common(20):
        l1, wk, l2, l3 = tup
        emit(f"  {n:>4} × {l1}/{wk}/{l2}/{l3}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[output] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
