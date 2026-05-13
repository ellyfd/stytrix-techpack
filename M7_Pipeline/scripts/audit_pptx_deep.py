"""
PPTX 深度 audit — 從 brand / ISO / L1 / callout 完整度各角度分析
跑法: python scripts\audit_pptx_deep.py
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

PPTX = Path(__file__).resolve().parent.parent / "outputs" / "extract" / "pptx_facets.jsonl"

def audit():
    if not PPTX.exists():
        print(f"[!] {PPTX} 不存在")
        return

    # 全局統計
    n_entries = 0
    n_with_pptx = 0
    n_with_callout = 0
    callout_total = 0
    slides_total = 0
    construction_slides_total = 0

    # callout 維度覆蓋
    has_method = 0
    has_zone = 0
    has_L1 = 0
    has_iso = 0
    has_all4 = 0      # method+zone+L1+iso
    has_iso_only = 0  # 有 iso 沒 L1（zone 沒對到 L1 mapping）
    has_zone_no_L1 = 0  # 有 zone 沒 L1

    # 分布
    iso_dist = Counter()
    L1_dist = Counter()
    zone_dist = Counter()
    zone_no_L1 = Counter()  # zone 沒 mapping 到 L1 的關鍵字（需擴充 mapping）
    method_no_iso_sample = []  # method 看得出 sewing 但沒推 iso 的樣本

    # By brand
    by_brand = defaultdict(lambda: {
        "entries": 0, "with_callout": 0,
        "callouts": 0, "slides": 0, "construction_slides": 0,
        "has_iso": 0, "has_L1": 0, "has_all4": 0,
    })

    status = Counter()

    with open(PPTX, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_entries += 1
            status[d.get("_status", "?")] += 1
            cl = d.get("client_code", "UNKNOWN")
            by_brand[cl]["entries"] += 1
            if d.get("pptx_files"):
                n_with_pptx += 1
            slides_total += d.get("n_slides_total", 0) or 0
            construction_slides_total += d.get("n_construction_slides", 0) or 0
            by_brand[cl]["slides"] += d.get("n_slides_total", 0) or 0
            by_brand[cl]["construction_slides"] += d.get("n_construction_slides", 0) or 0

            # 2026-05-12 rename: callouts → constructions (PPTX)
            callouts = d.get("constructions") or d.get("callouts") or []
            if callouts:
                n_with_callout += 1
                by_brand[cl]["with_callout"] += 1
            callout_total += len(callouts)
            by_brand[cl]["callouts"] += len(callouts)

            for c in callouts:
                m = bool(c.get("method"))
                z = bool(c.get("zone"))
                l1 = bool(c.get("L1"))
                i = bool(c.get("iso"))
                if m: has_method += 1
                if z: has_zone += 1
                if l1:
                    has_L1 += 1
                    L1_dist[c.get("L1")] += 1
                    by_brand[cl]["has_L1"] += 1
                if i:
                    has_iso += 1
                    iso_dist[c.get("iso")] += 1
                    by_brand[cl]["has_iso"] += 1
                if m and z and l1 and i:
                    has_all4 += 1
                    by_brand[cl]["has_all4"] += 1
                if z and not l1:
                    has_zone_no_L1 += 1
                    zone_no_L1[c.get("zone")] += 1
                if i and not l1:
                    has_iso_only += 1
                if z:
                    zone_dist[c.get("zone")] += 1
                # method 看得出有 sewing 字眼但沒 iso，列入候選
                if m and not i:
                    method = c.get("method", "")
                    if any(kw in method for kw in ["車", "縫", "拷克", "鎖鍊", "鎖鏈", "平車", "三本", "壓線"]):
                        if len(method_no_iso_sample) < 20:
                            method_no_iso_sample.append(method[:80])

    print(f"\n=== PPTX 深度 audit ({PPTX.stat().st_size//1024//1024} MB / {n_entries:,} entries) ===\n")

    print(f"## 整體覆蓋")
    print(f"  total entries          : {n_entries:,}")
    print(f"  with pptx file(s)      : {n_with_pptx:,} ({n_with_pptx/max(n_entries,1)*100:.0f}%)")
    print(f"  with >=1 callout       : {n_with_callout:,} ({n_with_callout/max(n_entries,1)*100:.0f}%)")
    print(f"  slides 合計             : {slides_total:,}")
    print(f"  construction slides    : {construction_slides_total:,}")
    print(f"  callouts 合計           : {callout_total:,}")
    print(f"  avg callout / design   : {callout_total/max(n_with_callout,1):.1f}")

    print(f"\n## Callout 維度覆蓋率 (/total {callout_total:,})")
    print(f"  has method             : {has_method:,} ({has_method/max(callout_total,1)*100:.0f}%)")
    print(f"  has zone               : {has_zone:,} ({has_zone/max(callout_total,1)*100:.0f}%)")
    print(f"  has L1 (zone→L1 對到)   : {has_L1:,} ({has_L1/max(callout_total,1)*100:.0f}%)")
    print(f"  has iso (method→ISO 對到): {has_iso:,} ({has_iso/max(callout_total,1)*100:.0f}%)")
    print(f"  has all 4 (完整 callout): {has_all4:,} ({has_all4/max(callout_total,1)*100:.0f}%)")
    print(f"  has zone 但無 L1        : {has_zone_no_L1:,} (zone mapping 缺漏)")
    print(f"  has iso 但無 L1         : {has_iso_only:,} (沒 zone keyword 命中)")

    print(f"\n## ISO 分布 (top 15)")
    iso_names = {
        "301": "單針平車", "304": "Z字車", "401": "雙針鎖鏈/鎖鏈車",
        "406": "三本車", "407": "四本車", "504": "三線拷克",
        "514": "四線拷克", "516": "五線拷克", "602": "兩針三本",
        "605": "三針三本", "607": "併縫(Flatlock)",
        "512": "Mock safety", "401_1": "雙針鎖鍊",
    }
    for iso, n in iso_dist.most_common(15):
        name = iso_names.get(iso, "?")
        print(f"  {iso:<6} {name:<20} {n:>6} ({n/max(has_iso,1)*100:.0f}%)")

    print(f"\n## L1 分布 (top 15) — 38 official L1 code")
    # 2026-05-12 修: 對齊 stytrix-techpack/data/runtime/l1_standard_38.json 官方中文
    l1_names = {
        "AE": "袖孔", "AH": "袖圍", "BM": "下襬", "BN": "貼合", "BP": "襬叉",
        "BS": "釦鎖", "DC": "繩類", "DP": "裝飾片", "FP": "袋蓋", "FY": "前立",
        "HD": "帽子", "HL": "釦環", "KH": "Keyhole", "LB": "商標", "LI": "裡布",
        "LO": "褲口", "LP": "帶絆", "NK": "領", "NP": "領襟", "NT": "領貼條",
        "OT": "其它", "PD": "褶", "PK": "口袋", "PL": "門襟", "PS": "褲合身",
        "QT": "行縫", "RS": "褲襠", "SA": "剪接線_上身", "SB": "剪接線_下身",
        "SH": "肩", "SL": "袖口", "SP": "袖叉", "SR": "裙合身", "SS": "脅邊",
        "ST": "肩帶", "TH": "拇指洞", "WB": "腰頭", "ZP": "拉鍊",
    }
    for l1, n in L1_dist.most_common(15):
        name = l1_names.get(l1, "?")
        print(f"  {l1:<4} {name:<10} {n:>6} ({n/max(has_L1,1)*100:.0f}%)")

    print(f"\n## Zone 沒對到 L1 mapping 的 top 15 (這些需要擴充 zone→L1)")
    for zone, n in zone_no_L1.most_common(15):
        print(f"  {zone:<12} {n:>6}")

    print(f"\n## By brand — entries × callout / iso / L1 完整度")
    print(f"  {'brand':<8} {'entries':>7} {'cal_ents':>8} {'callouts':>10} {'iso%':>6} {'L1%':>6} {'all4%':>7}")
    for cl in sorted(by_brand.keys(), key=lambda x: -by_brand[x]["entries"]):
        b = by_brand[cl]
        co = b["callouts"]
        iso_pct = b["has_iso"]/max(co,1)*100
        l1_pct = b["has_L1"]/max(co,1)*100
        all4_pct = b["has_all4"]/max(co,1)*100
        print(f"  {cl:<8} {b['entries']:>7} {b['with_callout']:>8} {b['callouts']:>10} "
              f"{iso_pct:>5.0f}% {l1_pct:>5.0f}% {all4_pct:>6.0f}%")

    print(f"\n## 有 sewing 字眼但沒推 iso 的 method 樣本（mapping 待擴充）")
    for s in method_no_iso_sample[:15]:
        print(f"  - {s}")

if __name__ == "__main__":
    audit()
