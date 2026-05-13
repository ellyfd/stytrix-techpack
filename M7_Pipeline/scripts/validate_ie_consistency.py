"""validate_ie_consistency.py — 五階核對

每 (bucket, L1) 對比：
  我們抽到的 method/ISO  ↔  IE 五階 typical_machine / typical_l4

判斷邏輯：把 ISO 反查 ZH 機種名（406→三本／二針三線；514→四線拷克；605→三針五線；…），
看 IE typical_machine 字串裡是否含這個 ZH 機種名 → CONSISTENT；否則 INCONSISTENT。

輸出：
  outputs/ie_consistency/_check.csv  ← 每 (bucket, L1) 一列，含 our_method / ie_machine / flag

用法：python scripts/validate_ie_consistency.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUR = ROOT / "m7_organized_v2" / "aligned" / "consensus_m7.jsonl"
IE = ROOT / "m7_organized_v2" / "aligned" / "ie_consensus.jsonl"
OUT = ROOT / "outputs" / "ie_consistency"
OUT.mkdir(parents=True, exist_ok=True)

# IE machine 名稱裡這幾類是 catch-all step（不是縫紉機種），要跳過
IE_NON_SEWING_KEYWORDS = ["手工", "燙工", "手燙", "做記號", "翻修", "打結車", "釘釦", "鎖眼"]

def pick_ie_sewing_machine(machine_dist):
    """從 IE machine_dist 取第一個_真縫紉_機種（跳過手工/燙工）"""
    for m in machine_dist or []:
        name = m.get("name", "")
        if not any(kw in name for kw in IE_NON_SEWING_KEYWORDS):
            return name
    return ""


# ISO → 該 ISO 對應 IE machine 名常見的關鍵字（任一 substring 中即視為 consistent）
ISO_TO_IE_KEYWORDS = {
    "103": ["暗縫"],
    "301": ["平車", "鎖鏈車-單針", "單針", "鎖式"],
    "304": ["人字"],
    "401": ["鎖鏈", "單針鎖鏈"],
    "406": ["三本", "二針三線", "覆蓋"],
    "504": ["三線拷克", "三線"],
    "514": ["四線拷克", "四線"],
    "516": ["五線拷克", "五線"],
    "602": ["二針四線", "兩針四線", "爬網"],
    "605": ["三針五線", "拼縫車-三針五線", "爬網", "扒網"],
    "607": ["四針六線", "拼縫", "併縫", "倂縫", "FLATLOCK", "拼縫車-四針六線"],
}


def check_consistency(our_iso, ie_machine, ie_machine_dist=None, top_n=3):
    """ISO ↔ IE machine 名的一致性檢查。
    新版：不只比 typical_machine，還比 machine_dist top N 任一機種命中即 consistent。"""
    if not our_iso:
        return "no_data"
    keywords = ISO_TO_IE_KEYWORDS.get(our_iso, [])
    if not keywords:
        return "no_iso_mapping"
    # 比 typical_machine
    if ie_machine:
        for kw in keywords:
            if kw in ie_machine:
                return "consistent"
    # 比 machine_dist top N
    if ie_machine_dist:
        for m in ie_machine_dist[:top_n]:
            name = m.get("name", "")
            for kw in keywords:
                if kw in name:
                    return "consistent_in_top3"
    return "inconsistent"


def main():
    # 1. 讀 IE consensus（key by (bucket, L1)）
    ie_idx = {}
    for line in open(IE, encoding="utf-8"):
        e = json.loads(line)
        key = (e["key"]["bucket"], e["key"]["l1"])
        ie_idx[key] = e
    print(f"[load] IE consensus: {len(ie_idx)} entries")

    # 2. 讀我們的 consensus
    our = []
    for line in open(OUR, encoding="utf-8"):
        our.append(json.loads(line))
    print(f"[load] our consensus: {len(our)} entries")

    # 3. 對齊 + 檢查
    rows = []
    n_consistent = n_inconsistent = n_no_data = n_no_match = 0
    for o in our:
        bucket = o["key"]["bucket"]
        l1 = o["key"]["l1"]
        our_iso = o.get("top_iso")
        our_n = o.get("n_total", 0)
        our_method = (o.get("top_method") or "")[:80]
        ie = ie_idx.get((bucket, l1))
        if not ie:
            flag = "no_ie_match"
            n_no_match += 1
            ie_machine = ""
            ie_l4 = ""
            ie_n = 0
        else:
            # 用 typical_machine 但若是手工/燙工，改取 machine_dist 第一個真縫紉機種
            tm = (ie.get("typical_machine") or "")
            if any(kw in tm for kw in IE_NON_SEWING_KEYWORDS):
                ie_machine = pick_ie_sewing_machine(ie.get("machine_dist", [])) or tm
            else:
                ie_machine = tm
            ie_l4 = (ie.get("typical_l4") or "")[:80]
            ie_n = ie.get("n_steps", 0)
            flag = check_consistency(our_iso, ie_machine, ie.get("machine_dist", []))
            if flag in ("consistent", "consistent_in_top3"):
                n_consistent += 1
            elif flag == "inconsistent":
                n_inconsistent += 1
            elif flag == "no_data":
                n_no_data += 1
        rows.append({
            "bucket": bucket, "l1_code": l1,
            "our_n": our_n, "our_iso": our_iso or "",
            "our_method": our_method,
            "ie_n": ie_n, "ie_machine": ie_machine,
            "ie_l4": ie_l4,
            "flag": flag,
        })

    # 4. 寫檔
    out_path = OUT / "_check.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["bucket", "l1_code",
                                           "our_n", "our_iso", "our_method",
                                           "ie_n", "ie_machine", "ie_l4",
                                           "flag"])
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["flag"] != "inconsistent", -x["our_n"])):
            w.writerow(r)

    # 5. console
    print(f"\n=== IE 五階核對結果 ===")
    print(f"  consistent:   {n_consistent}")
    print(f"  inconsistent: {n_inconsistent}")
    print(f"  no_data:      {n_no_data}")
    print(f"  no_ie_match:  {n_no_match}")

    print(f"\n[Inconsistent 列表（重點檢查）]")
    print(f"  {'bucket':14s} {'L1':3s}  {'n':>4s}  {'iso':>4s}  {'our_method':<35s}  {'ie_machine':<25s}")
    print(f"  {'-'*14} {'-'*3}  {'-'*4}  {'-'*4}  {'-'*35}  {'-'*25}")
    for r in rows:
        if r["flag"] == "inconsistent":
            print(f"  {r['bucket']:14s} {r['l1_code']:3s}  "
                  f"{r['our_n']:>4d}  {r['our_iso']:>4s}  "
                  f"{r['our_method'][:35]:<35s}  {r['ie_machine'][:25]:<25s}")

    print(f"\n[Output]")
    print(f"  {out_path}")


if __name__ == "__main__":
    main()
