"""ie_alignment.py — IE 五階對齊判斷邏輯（v7 + validate 共用）

統一 gap_flag 計算：每 (bucket, L1) 我們抽到的 ISO ↔ IE machine_dist 的對齊度。

Public API:
  pick_ie_real_machines(ie_machine_dist) -> list[dict]
  pick_ie_real_top1(ie_machine_dist) -> str
  compute_gap_flag(our_iso, ie_machine_dist, top_n=3) -> str
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zone_resolver import IE_NON_SEWING_KEYWORDS, ISO_TO_IE_KEYWORDS


def pick_ie_real_machines(ie_machine_dist):
    """過濾掉 IE machine_dist 中的手工/燙工 catch-all step，只留真縫紉機種。"""
    if not ie_machine_dist:
        return []
    return [m for m in ie_machine_dist
            if not any(kw in m.get("name", "") for kw in IE_NON_SEWING_KEYWORDS)]


def pick_ie_real_top1(ie_machine_dist):
    """取 IE 真縫紉機種 top1（過濾後最高頻）。沒則 ''."""
    real = pick_ie_real_machines(ie_machine_dist)
    return real[0].get("name", "") if real else ""


def compute_gap_flag(our_iso, ie_machine_dist, top_n=3):
    """ISO ↔ IE machine_dist 對齊判斷：
       align          — our_iso 對應 ZH 機種名是 IE real_top1
       gap_layered    — our_iso 對應 ZH 機種名在 IE real top N 之內（N 預設 3）
       gap_real       — our_iso 完全不在 IE real top N
       no_data        — IE 沒真縫紉機種共識（全是手工/燙工）
       no_iso_mapping — our_iso 不在 ISO_TO_IE_KEYWORDS dict
    """
    if not our_iso:
        return "no_data"
    keywords = ISO_TO_IE_KEYWORDS.get(our_iso)
    if not keywords:
        return "no_iso_mapping"
    real = pick_ie_real_machines(ie_machine_dist)
    if not real:
        return "no_data"
    # top1 命中 → align
    top1_name = real[0].get("name", "")
    if any(kw in top1_name for kw in keywords):
        return "align"
    # top 2..N 命中 → gap_layered
    for m in real[1:top_n]:
        if any(kw in m.get("name", "") for kw in keywords):
            return "gap_layered"
    return "gap_real"
