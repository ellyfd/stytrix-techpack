"""report_canonical_consensus.py — 讀 m7_pullon_designs.jsonl 的 canonical 區塊,
出 confidence distribution per (client, canonical field)。

每筆 design 有:
  canonical.<field>.value        最終值 (M7 + PDF + 推論 consensus)
  canonical.<field>.confidence   "high"/"medium"/"low"/"none"
  canonical.<field>.sources      audit trail (各 source 的原始值 + weight)

跑:python scripts/report_canonical_consensus.py
Output: outputs/platform/canonical_consensus_report.txt
"""
from __future__ import annotations
import json
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGNS = ROOT / "outputs" / "platform" / "m7_pullon_designs.jsonl"
OUT = ROOT / "outputs" / "platform" / "canonical_consensus_report.txt"

CANONICAL = ["客戶", "報價款號", "Program", "Subgroup", "W/K", "Item", "Season", "PRODUCT_CATEGORY"]
CONFIDENCES = ["high", "medium", "low", "none"]


def main():
    if not DESIGNS.exists():
        print(f"[FAIL] {DESIGNS} not found,先跑 build_m7_pullon_source_v3.py")
        return 1

    by_client = defaultdict(list)
    pdf_disagreement = []  # collect designs where PDF disagrees with M7

    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            client = d.get("client", {}).get("code", "?")
            by_client[client].append(d)

            # check PDF / M7 disagreements (confidence=medium 表示衝突)
            canon = d.get("canonical", {})
            for field, c in canon.items():
                if not isinstance(c, dict):
                    continue
                if c.get("confidence") == "medium":
                    sources = c.get("sources", {})
                    m7 = (sources.get("m7_列管") or {}).get("value")
                    pdf_ = (sources.get("pdf") or {}).get("value")
                    if m7 and pdf_ and m7 != pdf_:
                        pdf_disagreement.append({
                            "eidh": d.get("eidh"),
                            "client": client,
                            "field": field,
                            "m7": m7,
                            "pdf": pdf_,
                        })

    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 130)
    emit(f"Canonical Consensus Report (source: {DESIGNS.relative_to(ROOT)})")
    emit("=" * 130)

    # === Per-client × per-field confidence distribution ===
    emit(f"\n{'client':10} {'n':>5}  " + "  ".join(f"{f:>20}" for f in CANONICAL))
    emit("-" * 200)

    grand = defaultdict(Counter)  # field → Counter(confidence → n)

    for client in sorted(by_client.keys(), key=lambda c: -len(by_client[c])):
        rows = by_client[client]
        n = len(rows)
        cells = []
        for field in CANONICAL:
            cnt = Counter()
            for r in rows:
                c = (r.get("canonical") or {}).get(field) or {}
                cnt[c.get("confidence", "none")] += 1
            grand[field] += cnt
            high_pct = 100 * cnt["high"] / n
            med_pct = 100 * cnt["medium"] / n
            low_pct = 100 * cnt["low"] / n
            cells.append(f"H{high_pct:>3.0f}/M{med_pct:>3.0f}/L{low_pct:>3.0f}")
        emit(f"{client:10} {n:>5}  " + "  ".join(f"{c:>20}" for c in cells))

    # Grand total
    emit("-" * 200)
    n_total = sum(len(r) for r in by_client.values())
    cells = []
    for field in CANONICAL:
        cnt = grand[field]
        high_pct = 100 * cnt["high"] / n_total if n_total else 0
        med_pct = 100 * cnt["medium"] / n_total if n_total else 0
        low_pct = 100 * cnt["low"] / n_total if n_total else 0
        cells.append(f"H{high_pct:>3.0f}/M{med_pct:>3.0f}/L{low_pct:>3.0f}")
    emit(f"{'TOTAL':10} {n_total:>5}  " + "  ".join(f"{c:>20}" for c in cells))

    emit("")
    emit("Format: H=high (M7 跟 consensus 一致), M=medium (M7 跟 PDF 衝突 / 多 source 同意), L=low (單一 source)")

    # === Filter 角度:有效 value 比例 (value != null) ===
    emit("")
    emit("=" * 130)
    emit("Filter 角度 — canonical.<field>.value 非空比例 (=可 join 比例)")
    emit("=" * 130)
    emit(f"{'client':10} {'n':>5}  " + "  ".join(f"{f:>14}" for f in CANONICAL))
    emit("-" * 150)

    for client in sorted(by_client.keys(), key=lambda c: -len(by_client[c])):
        rows = by_client[client]
        n = len(rows)
        cells = []
        for field in CANONICAL:
            non_null = sum(1 for r in rows
                           if (r.get("canonical") or {}).get(field, {}).get("value"))
            pct = 100 * non_null / n
            cells.append(f"{pct:>5.0f}% ({non_null:>4}/{n:<4})")
        emit(f"{client:10} {n:>5}  " + "  ".join(f"{c:>14}" for c in cells))

    # === PDF / M7 衝突 audit list ===
    emit("")
    emit("=" * 130)
    emit(f"PDF vs M7 列管 衝突清單 (confidence=medium, 待人工確認):n={len(pdf_disagreement)}")
    emit("=" * 130)
    if pdf_disagreement:
        # group by (client, field) → count
        by_pair = Counter()
        for d in pdf_disagreement:
            by_pair[(d["client"], d["field"])] += 1
        emit("\nTop conflict (client, field):")
        for (client, field), n in by_pair.most_common(20):
            emit(f"  {client:8} {field:<22} {n:>4} 件")

        # show 5 sample disagreements
        emit("\nSample disagreements (前 10 筆):")
        for d in pdf_disagreement[:10]:
            emit(f"  eidh={d['eidh']:<8} client={d['client']:<6} field={d['field']:<22} M7={d['m7']!r:<25} PDF={d['pdf']!r}")
    else:
        emit("(無衝突 — 太完美或還沒整合 PDF data)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[output] {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
