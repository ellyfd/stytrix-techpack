"""
build_consensus_m7.py — 跨客戶 union → consensus 規則 (含 ISO + IE 五階)

讀（優先）：
  m7_organized_v2/aligned/facts_aligned.jsonl  (含 IE 對齊)
  fallback: data/ingest/unified/facts.jsonl     (無 IE)

輸出：
  m7_organized_v2/aligned/consensus_m7.jsonl       (full consensus，含 IE 五階)
  m7_organized_v2/aligned/consensus_summary.csv    (人類好讀版)

每個 (bucket, l1_code) entry 含：
  ── ISO 共識 ──
  iso_distribution    [{iso, n, pct}, ...]
  methods             [{name, n, pct}, ...]
  ── IE 五階共識 ──
  ie_distribution     {l2, l3, l4, l5, machine: [{name, n, pct}]}
  avg_seconds, median_seconds
  typical_recipe      {l2, l3, l4, l5, machine, n, pct, avg_seconds}
  ── 元資料 ──
  n_total / n_aligned / n_designs / n_clients
  design_ids / client_ids / confidence
"""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
ALIGNED_DIR = ROOT / "m7_organized_v2" / "aligned"
FACTS_ALIGNED = ALIGNED_DIR / "facts_aligned.jsonl"
FACTS_RAW = DL / "data" / "ingest" / "unified" / "facts.jsonl"
CSV5_DIR = ROOT / "m7_organized_v2" / "csv_5level"

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_constants import ZH_TO_L1  # noqa: E402


def load_ie_step_coverage():
    """
    掃 csv_5level/ → 每個 EIDH 的 IE 五階「有哪些 zone 拆成獨立 step」。
    回傳 {l1_code: set(eidh)} — 表示哪些 EIDH 在 IE 系統裡有該 zone 的獨立 step。
    """
    eidh_zones = {}  # eidh -> set of l1_codes that have IE step
    if not CSV5_DIR.exists():
        return {}, set()
    for f in sorted(CSV5_DIR.glob("*.csv")):
        try:
            eidh = int(f.stem.split("_")[0])
        except (ValueError, IndexError):
            continue
        zones = set()
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            cat = (row.get("category") or "").strip()
            l1 = ZH_TO_L1.get(cat)
            if l1:
                zones.add(l1)
        eidh_zones[eidh] = zones
    return eidh_zones


def classify_confidence(n_facts, n_designs, n_clients, iso_dist):
    if n_facts < 3:
        return "very_low"
    if n_facts < 10:
        return "low"
    top_iso_pct = iso_dist[0]["pct"] if iso_dist else 0
    if n_facts >= 10 and n_designs >= 3 and top_iso_pct >= 50:
        return "high"
    if n_clients >= 2 and n_facts >= 10:
        return "medium"
    if n_facts >= 5:
        return "medium"
    return "low"


def dist(c, top=10):
    if not c:
        return []
    total = sum(c.values())
    return [{"name": k, "n": n, "pct": round(n/total*100, 1)}
            for k, n in c.most_common(top)]


def main():
    if FACTS_ALIGNED.exists():
        FACTS = FACTS_ALIGNED
        has_ie = True
        print(f"[input] {FACTS.name} (含 IE 對齊)")
    elif FACTS_RAW.exists():
        FACTS = FACTS_RAW
        has_ie = False
        print(f"[input] {FACTS.name} (無 IE — 跑 align_to_ie_m7 取得 IE 五階共識)")
    else:
        print(f"[!] 兩個 fact 檔都不存在")
        return

    ALIGNED_DIR.mkdir(parents=True, exist_ok=True)

    groups = defaultdict(lambda: {
        "isos": Counter(), "methods": Counter(),
        "designs": set(), "clients": set(),
        "confidences": Counter(),
        "ie_l2": Counter(), "ie_l3": Counter(), "ie_l4": Counter(),
        "ie_l5": Counter(), "ie_machine": Counter(),
        "ie_seconds": [],
        "n_ie_aligned": 0,
        "ie_full": Counter(),
        "ie_full_seconds": defaultdict(list),
        "n": 0,
    })

    # 載 IE step coverage：每個 EIDH 在 IE 五階有哪些 zone 拆成獨立 step
    eidh_zones = load_ie_step_coverage()
    print(f"[load] IE coverage: {len(eidh_zones)} EIDH 有 csv_5level")

    n_total = 0
    n_skipped = 0
    with open(FACTS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            n_total += 1
            l1 = row.get("l1_code", "")
            bucket = (row.get("bucket") or "").upper()
            if not l1 or l1 == "OT" or not bucket:
                n_skipped += 1
                continue
            gkey = (bucket, l1)
            g = groups[gkey]
            g["n"] += 1
            g["designs"].add(row.get("design_id", ""))
            g["clients"].add(row.get("client", ""))
            g["confidences"][row.get("confidence", "")] += 1
            # 記下 fact 對應的 EIDH 用來算 ie_step_coverage
            eidh_val = row.get("eidh")
            if eidh_val is not None:
                g.setdefault("eidhs", set()).add(eidh_val)
            iso = row.get("iso", "")
            if iso and re.fullmatch(r"\d+(\+\d+)?", iso or ""):
                g["isos"][iso] += 1
            method = row.get("method", "")
            if method:
                g["methods"][method] += 1

            if has_ie and row.get("ie_l2"):
                g["n_ie_aligned"] += 1
                g["ie_l2"][row["ie_l2"]] += 1
                if row.get("ie_l3"):
                    g["ie_l3"][row["ie_l3"]] += 1
                if row.get("ie_l4"):
                    g["ie_l4"][row["ie_l4"]] += 1
                if row.get("ie_l5"):
                    g["ie_l5"][row["ie_l5"]] += 1
                if row.get("ie_machine"):
                    g["ie_machine"][row["ie_machine"]] += 1
                sec = row.get("ie_second")
                if sec is not None:
                    try:
                        sec_f = float(sec)
                        g["ie_seconds"].append(sec_f)
                    except (TypeError, ValueError):
                        sec_f = None
                else:
                    sec_f = None
                full = (row.get("ie_l2") or "", row.get("ie_l3") or "",
                        row.get("ie_l4") or "", row.get("ie_l5") or "",
                        row.get("ie_machine") or "")
                g["ie_full"][full] += 1
                if sec_f is not None:
                    g["ie_full_seconds"][full].append(sec_f)

    print(f"[load] facts: {n_total}, skipped (OT/empty): {n_skipped}")
    print(f"[group] {len(groups)} (bucket, l1_code) groups")

    entries = []
    for (bucket, l1), g in sorted(groups.items()):
        n = g["n"]
        n_designs = len(g["designs"])
        n_clients = len(g["clients"])

        iso_dist = []
        if g["isos"]:
            total_iso = sum(g["isos"].values())
            for iso, cnt in g["isos"].most_common():
                iso_dist.append({"iso": iso, "n": cnt, "pct": round(cnt/total_iso*100, 1)})
        method_list = dist(g["methods"])

        ie_dist = {
            "l2": dist(g["ie_l2"]),
            "l3": dist(g["ie_l3"]),
            "l4": dist(g["ie_l4"]),
            "l5": dist(g["ie_l5"]),
            "machine": dist(g["ie_machine"]),
        }
        avg_seconds = (sum(g["ie_seconds"]) / len(g["ie_seconds"])) if g["ie_seconds"] else None
        median_seconds = None
        if g["ie_seconds"]:
            ss = sorted(g["ie_seconds"])
            mid = len(ss) // 2
            median_seconds = ss[mid] if len(ss) % 2 else (ss[mid-1] + ss[mid]) / 2

        typical_recipe = None
        if g["ie_full"]:
            top_full, top_n = g["ie_full"].most_common(1)[0]
            top_l2, top_l3, top_l4, top_l5, top_machine = top_full
            top_secs = g["ie_full_seconds"].get(top_full, [])
            top_avg_sec = round(sum(top_secs) / len(top_secs), 2) if top_secs else None
            typical_recipe = {
                "l2": top_l2, "l3": top_l3, "l4": top_l4, "l5": top_l5,
                "machine": top_machine,
                "n": top_n,
                "pct": round(top_n / max(g["n_ie_aligned"], 1) * 100, 1),
                "avg_seconds": top_avg_sec,
            }

        confidence = classify_confidence(n, n_designs, n_clients, iso_dist)

        # IE step coverage：fact 對應的 EIDH 中，有多少在 IE 五階拆出該 zone 的獨立 step
        fact_eidhs = g.get("eidhs", set())
        ie_eidhs_with_step = sum(1 for e in fact_eidhs if l1 in eidh_zones.get(e, set()))
        ie_step_coverage = {
            "n_eidh_with_facts": len(fact_eidhs),
            "n_eidh_with_ie_step": ie_eidhs_with_step,
            "pct": round(ie_eidhs_with_step / max(len(fact_eidhs), 1) * 100, 1),
        }

        entry = {
            "key": {"bucket": bucket, "l1": l1},
            "n_total": n,
            "n_aligned": g["n_ie_aligned"],
            "n_designs": n_designs,
            "n_clients": n_clients,
            "iso_distribution": iso_dist,
            "methods": method_list,
            "ie_distribution": ie_dist,
            "avg_seconds": round(avg_seconds, 2) if avg_seconds else None,
            "typical_recipe": typical_recipe,
            "ie_step_coverage": ie_step_coverage,
            "design_ids": sorted(g["designs"]),
            "client_ids": sorted(g["clients"]),
            "confidence_dist": dict(g["confidences"]),
            "confidence": confidence,
            "top_iso": iso_dist[0]["iso"] if iso_dist else None,
            "top_method": method_list[0]["name"] if method_list else None,
        }
        entries.append(entry)

    out_path = ALIGNED_DIR / "consensus_m7.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    csv_path = ALIGNED_DIR / "consensus_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w = csv.writer(f)
        w.writerow(["bucket", "l1_code", "n_facts", "n_aligned_to_ie", "n_designs", "n_clients", "ie_step_coverage_pct", "top_iso", "top_iso_pct", "top_method", "iso_dist_summary", "method_dist_summary", "typical_l2", "typical_l3", "typical_l4", "typical_l5", "typical_machine", "typical_recipe_pct", "typical_recipe_avg_sec", "avg_seconds", "median_seconds", "ie_l4_top3", "client_list", "confidence"])
        for e in sorted(entries, key=lambda x: (-x["n_total"], x["key"]["bucket"])):
            top_iso_pct = e["iso_distribution"][0]["pct"] if e["iso_distribution"] else 0
            iso_summary = " ".join(f'{d["iso"]}({d["n"]})' for d in e["iso_distribution"][:5])
            method_summary = " ".join(f'{d["name"]}({d["n"]})' for d in e["methods"][:5])
            tr = e.get("typical_recipe") or {}
            l4_top3 = " | ".join(f'{d["name"]}({d["n"]})' for d in (e["ie_distribution"]["l4"] or [])[:3])
            ie_cov = e.get("ie_step_coverage") or {}
            w.writerow([e["key"]["bucket"], e["key"]["l1"], e["n_total"], e["n_aligned"], e["n_designs"], e["n_clients"], f"{ie_cov.get('n_eidh_with_ie_step',0)}/{ie_cov.get('n_eidh_with_facts',0)} ({ie_cov.get('pct',0)}%)", e["top_iso"] or "", top_iso_pct, e["top_method"] or "", iso_summary, method_summary, tr.get("l2") or "", tr.get("l3") or "", tr.get("l4") or "", tr.get("l5") or "", tr.get("machine") or "", tr.get("pct", "") if tr else "", tr.get("avg_seconds", "") if tr else "", e.get("avg_seconds") or "", e.get("median_seconds") or "", l4_top3, ",".join(e["client_ids"]), e["confidence"]])

    print(f"\n=== Consensus build summary ===")
    print(f"  entries: {len(entries)}")
    by_conf = Counter(e["confidence"] for e in entries)
    for c in ["high", "medium", "low", "very_low"]:
        if c in by_conf:
            print(f"  {c:10s}: {by_conf[c]}")
    print(f"\n[Top 15 consensus by sample size]")
    for e in sorted(entries, key=lambda x: -x["n_total"])[:15]:
        iso_str = e["top_iso"] or "-"
        tr = e.get("typical_recipe") or {}
        l4_str = (tr.get("l4") or "-")[:22]
        machine_str = (tr.get("machine") or "-")[:12]
        avg_sec = e.get("avg_seconds")
        sec_str = f"{avg_sec:.1f}s" if avg_sec else "-"
        ie_cov = e.get("ie_step_coverage") or {}
        cov_str = f"{ie_cov.get('n_eidh_with_ie_step',0)}/{ie_cov.get('n_eidh_with_facts',0)}"
        print(f"  {e['key']['bucket']:14s}x{e['key']['l1']:3s}  n={e['n_total']:>3d}/{e['n_aligned']:>3d}  IE_cov={cov_str:>6s}  iso={iso_str:>4s}  L4={l4_str:<22s}  {sec_str:>6s}  clients={e['n_clients']}  {e['confidence']}")
    print(f"\n[Output]")
    print(f"  {out_path}")
    print(f"  {csv_path}")


if __name__ == "__main__":
    main()
