"""
align_to_ie_m7.py — 把 unified/facts.jsonl 對齊到 IE 五階段 ground truth

讀：
  data/ingest/unified/facts.jsonl     (callout-level facts)
  m7_organized_v2/csv_5level/*.csv    (IE 五階段 step list, by EIDH)

輸出：
  m7_organized_v2/aligned/final_aligned.csv     對齊到 IE step 的 fact (人類好讀)
  m7_organized_v2/aligned/facts_aligned.jsonl   全部 fact + IE step 欄 (給 build_consensus 用)
  m7_organized_v2/aligned/_summary.csv          對齊率統計

對齊邏輯：
  L1 部位 +10 / L2 +8 / L4 +5 / machine +3, threshold 10
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7 = ROOT
DL = ROOT.parent / "stytrix-pipeline-Download0504"
FACTS_PATH = DL / "data" / "ingest" / "unified" / "facts.jsonl"
CSV5_DIR = M7 / "m7_organized_v2" / "csv_5level"
ALIGNED_DIR = M7 / "m7_organized_v2" / "aligned"

# 從共用 module import
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_constants import ZH_TO_L1  # noqa: E402


def load_ground_truth():
    gt = {}
    if not CSV5_DIR.exists():
        print(f"[!] csv_5level 不存在: {CSV5_DIR}", file=sys.stderr)
        return gt
    for f in sorted(CSV5_DIR.glob("*.csv")):
        try:
            eidh = int(f.stem.split("_")[0])
        except (ValueError, IndexError):
            continue
        rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        gt[eidh] = [{
            "no": r.get("Textbox8", "") or "",
            "l1_zh": (r.get("category", "") or "").strip(),
            "l1_code": ZH_TO_L1.get((r.get("category", "") or "").strip(), ""),
            "l2": (r.get("part", "") or "").strip(),
            "l3": (r.get("Shape_Design", "") or "").strip(),
            "l4": (r.get("Method_Describe", "") or "").strip(),
            "l5": (r.get("section", "") or "").strip(),
            "machine": (r.get("machine_name", "") or "").strip(),
            "second": float(r.get("total_second", 0) or 0),
        } for r in rows]
    return gt


# IE 同義詞群組：每組裡任一字命中即視為 match
SYNONYM_GROUPS = [
    # 縫合動作
    {"車合", "縫合", "接合", "合縫", "組合", "拼合", "拼縫"},
    # 拷克 / 鎖邊
    {"拷邊", "拷克", "鎖邊", "鎖縫", "拷"},
    # 平車 / 單針壓線
    {"平車", "單針", "車縫", "壓線", "壓明線", "車線"},
    # 三本車 / 三針五線 / coverstitch
    {"三本", "三針", "三線", "五線", "雙針"},
    # 併縫 / flatlock
    {"併縫", "併車", "對接縫", "貼合車"},
    # 反折 / 包邊 / 收邊
    {"反折", "翻折", "折邊", "回折", "翻邊", "包邊", "包光", "收邊", "散邊"},
    # 鏈車 / chainstitch
    {"鏈車", "鎖鏈車", "鏈縫"},
    # 打結車 / bartack
    {"打結車", "打結", "車止", "回車"},
    # 燙
    {"燙開", "燙縫", "燙工", "整燙"},
    # 滾條
    {"滾條", "滾邊", "滾"},
    # 鬆緊帶
    {"鬆緊帶", "鬆緊", "elastic", "WB", "腰頭"},
    # 雞眼/釦眼
    {"雞眼", "扣眼", "釦眼"},
    # 整圈 / 全車
    {"整圈", "全圈", "一圈", "繞圈"},
    # 道
    {"一道", "1道", "兩道", "2道"},
    # 袋類
    {"袋", "口袋", "暗袋", "貼袋", "插袋", "後袋"},
    # 繩類
    {"繩", "綁繩", "綁帶", "腰繩", "drawcord"},
    # 鏟車 / 平車細針距
    {"細針距", "細密", "密針"},
]

# 反查表：每個字 → 該組所有字
SYN_LOOKUP = {}
for g in SYNONYM_GROUPS:
    for t in g:
        SYN_LOOKUP.setdefault(t, set()).update(g)


def has_token_or_syn(text: str, target: str) -> bool:
    """text 含 target 或 target 的同義詞 → True"""
    if target in text:
        return True
    syns = SYN_LOOKUP.get(target)
    if syns:
        for s in syns:
            if s in text:
                return True
    return False


def score_step(fact, step):
    s = 0
    text = fact.get("source_line", "") or ""
    zone = fact.get("zone_zh", "") or ""
    if step["l1_zh"] and (step["l1_zh"] == zone or step["l1_zh"] in text):
        s += 10
    if step["l2"]:
        for tok in re.split(r"[_/\s]+", step["l2"]):
            if len(tok) >= 2 and has_token_or_syn(text, tok):
                s += 8
                break
    if step["l4"]:
        for tok in re.split(r"[()_/\s\d]+", step["l4"]):
            if len(tok) >= 2 and has_token_or_syn(text, tok):
                s += 5
                break
    if step["machine"]:
        for tok in re.split(r"[\-_/\s]+", step["machine"]):
            if len(tok) >= 2 and has_token_or_syn(text, tok):
                s += 3
                break
    return s


def align(fact, gt, threshold=10):
    eidh = fact.get("eidh")
    if eidh not in gt:
        return None, 0
    scored = [(score_step(fact, st), st) for st in gt[eidh]]
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < threshold:
        return None, scored[0][0] if scored else 0
    return scored[0][1], scored[0][0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=int, default=10)
    p.add_argument("--low-threshold", type=int, default=5)
    args = p.parse_args()

    if not FACTS_PATH.exists():
        print(f"[!] facts.jsonl 不存在: {FACTS_PATH}", file=sys.stderr)
        sys.exit(1)
    ALIGNED_DIR.mkdir(parents=True, exist_ok=True)

    gt = load_ground_truth()
    total_steps = sum(len(v) for v in gt.values())
    print(f"[load] csv_5level: {len(gt)} EIDH × avg {total_steps/max(len(gt),1):.1f} = {total_steps} steps")

    csv_path = ALIGNED_DIR / "final_aligned.csv"
    jsonl_path = ALIGNED_DIR / "facts_aligned.jsonl"
    n_total = 0
    n_aligned = 0
    n_aligned_low = 0
    n_no_gt = 0
    score_dist = Counter()
    by_eidh = defaultdict(lambda: {"total": 0, "aligned": 0})
    by_client = defaultdict(lambda: {"total": 0, "aligned": 0})

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fout, \
         open(jsonl_path, "w", encoding="utf-8") as fjsonl:
        w = csv.writer(fout)
        w.writerow([
            "row_idx", "client", "design_id", "eidh", "source", "confidence",
            "zone_zh", "l1_code", "iso", "method", "source_line",
            "ie_no", "ie_l1_zh", "ie_l2", "ie_l3", "ie_l4", "ie_l5",
            "ie_machine", "ie_second", "align_score",
        ])

        with open(FACTS_PATH, encoding="utf-8") as fin:
            for i, line in enumerate(fin):
                fact = json.loads(line)
                n_total += 1
                eidh = fact.get("eidh")
                client = fact.get("client", "")
                by_eidh[eidh]["total"] += 1
                by_client[client]["total"] += 1

                step = None
                score = 0
                if eidh not in gt:
                    n_no_gt += 1
                else:
                    step, score = align(fact, gt, args.threshold)
                    score_dist[score // 5 * 5] += 1
                    if score >= args.low_threshold:
                        n_aligned_low += 1
                    if step:
                        n_aligned += 1
                        by_eidh[eidh]["aligned"] += 1
                        by_client[client]["aligned"] += 1
                        w.writerow([
                            i, client, fact.get("design_id", ""), eidh,
                            fact.get("source", ""), fact.get("confidence", ""),
                            fact.get("zone_zh", ""), fact.get("l1_code", ""),
                            fact.get("iso") or "", fact.get("method", ""),
                            (fact.get("source_line", "") or "")[:200],
                            step["no"], step["l1_zh"], step["l2"], step["l3"],
                            step["l4"], step["l5"], step["machine"], step["second"],
                            score,
                        ])

                aligned_fact = dict(fact)
                if step:
                    aligned_fact.update({
                        "ie_no": step["no"], "ie_l1_zh": step["l1_zh"],
                        "ie_l2": step["l2"], "ie_l3": step["l3"],
                        "ie_l4": step["l4"], "ie_l5": step["l5"],
                        "ie_machine": step["machine"], "ie_second": step["second"],
                        "align_score": score,
                    })
                else:
                    aligned_fact.update({
                        "ie_no": None, "ie_l1_zh": None,
                        "ie_l2": None, "ie_l3": None, "ie_l4": None, "ie_l5": None,
                        "ie_machine": None, "ie_second": None,
                        "align_score": score,
                    })
                fjsonl.write(json.dumps(aligned_fact, ensure_ascii=False) + "\n")

    summary_path = ALIGNED_DIR / "_summary.csv"
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["metric", "n", "pct"])
        w.writerow(["facts_total", n_total, "100.0%"])
        w.writerow(["aligned_strict", n_aligned, f"{n_aligned/n_total*100:.1f}%"])
        w.writerow(["aligned_loose", n_aligned_low, f"{n_aligned_low/n_total*100:.1f}%"])
        w.writerow(["no_gt_csv", n_no_gt, f"{n_no_gt/n_total*100:.1f}%"])
        w.writerow([])
        w.writerow(["score_bucket", "n"])
        for s in sorted(score_dist):
            w.writerow([f"{s}-{s+4}", score_dist[s]])
        w.writerow([])
        w.writerow(["client", "facts_total", "aligned", "rate"])
        for c, d in sorted(by_client.items()):
            rate = f"{d['aligned']/d['total']*100:.1f}%" if d['total'] else "0%"
            w.writerow([c, d['total'], d['aligned'], rate])
        w.writerow([])
        w.writerow(["eidh", "facts_total", "aligned", "rate"])
        for e in sorted(by_eidh):
            d = by_eidh[e]
            rate = f"{d['aligned']/d['total']*100:.1f}%" if d['total'] else "0%"
            w.writerow([e, d['total'], d['aligned'], rate])

    print(f"\n=== Align summary ===")
    print(f"  facts:    {n_total}")
    print(f"  aligned:  {n_aligned} ({n_aligned/n_total*100:.1f}%)")
    print(f"  no IE CSV: {n_no_gt}")
    print(f"\n[By client]")
    for c, d in sorted(by_client.items()):
        rate = d['aligned']/d['total']*100 if d['total'] else 0
        print(f"  {c:15s} {d['aligned']:4d}/{d['total']:4d} ({rate:5.1f}%)")
    print(f"\n[Output]")
    print(f"  {csv_path}")
    print(f"  {jsonl_path}  (給 build_consensus_m7 用)")
    print(f"  {summary_path}")


if __name__ == "__main__":
    main()
