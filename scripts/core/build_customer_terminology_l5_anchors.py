#!/usr/bin/env python3
"""build_customer_terminology_l5_anchors.py v2 — 2026-05-16
Fill l5_anchors in data/runtime/customer_terminology_master.json

v2 (2026-05-16): 擴充 machine→ISO pattern table
- 401: 加 鎖[鍊鏈] 異體字 (iso_dict _sot_note 明寫「鍊/鏈異體字皆可」)
        + 鎖鏈車 / 雙針鎖鏈 / 滾邊三本-單針鎖鏈 等變體
- 301: 加「雙針車」(雙針平車變體)
- 514: 加「包縫車」(屈手車 = 拷克變體)
- NON_ISO: 加 燙工 / 壓襯機 / 扒縫機 / 褲頭車 / 六線拷克

預期 v2 ISO mapped rate: 61% → ~85%
401 預期 anchor 數: 0 → ~600+ (從 鎖鏈 變體)

跑法:
  cd C:\\temp\\stytrix-techpack
  python scripts/core/build_customer_terminology_l5_anchors.py --dry-run
  python scripts/core/build_customer_terminology_l5_anchors.py     # write
"""
import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BIBLE_DIR = ROOT / "l2_l3_ie"
ISO_DICT = ROOT / "data" / "runtime" / "iso_dictionary.json"
MASTER = ROOT / "data" / "runtime" / "customer_terminology_master.json"

# ════════════════════════════════════════════════════════════════════
# Machine name → ISO mapping (priority order, first match wins)
# v2: 擴充 patterns 對應 bible 實際 machine 命名
# ════════════════════════════════════════════════════════════════════
MACHINE_TO_ISO_RULES = [
    # ─ 特殊縫法(放前面,更 specific)─
    (r"釘釦車|Button-sew|button.{0,5}sew", "101"),
    (r"鳳眼車|鳳眼|Eyelet", "500"),
    # v3: 加 盲縫車 (= 暗縫變體)
    (r"暗縫車|Blindhem|盲縫車", "103"),
    # ─ 拷克類 ─
    (r"兩線拷克", "503"),
    (r"假安全縫|Mock Safety", "512"),
    (r"五線拷克|5.thread.{0,3}overlock", "516"),
    # v2: 加 包縫車 (屈手車) 為 514 變體
    (r"四線拷克|4.thread.{0,3}overlock|拷克車|包縫車", "514"),
    # v3.1: 504 加 滾邊三本 (Elly correction: 滾邊三本 = 三本拷克, 所有變體含 -二針三線/-二針四線/-三針四線/-單針鎖鏈 都歸 504)
    # 必須擺在 407 / 401 之前 — 否則 滾邊三本-三針四線 會誤中 407 (三本.三針),滾邊三本-單針鎖鏈 會誤中 401 (鎖[鍊鏈])
    # v3: 加 3線拷 (3線拷下擺車 等 numeric 變體)
    (r"滾邊三本|三線拷克|3線拷|安全縫(?!.*假)|3.thread.{0,3}overlock", "504"),
    # ─ 三本車類 (v3: 407 改 specific pattern, 必須在 406 之前)─
    # v3: 「三本-三針」「三本.三針.四線」(平三本-三針四線 / 三本-三針 等 — 滾邊三本-* 已被 504 攔截)
    (r"三本.{0,4}三針|3.{0,2}needle.{0,5}cover", "407"),
    # v3.1: 406 加 平三本; 滾邊三本 從 406 拿掉,改進 504
    (r"三本(?:車|雙針)|壓三本|平三本|Coverstitch", "406"),
    # ─ 鏈縫類 ─
    # v2: 加 鎖[鍊鏈] 異體字, 加 鎖鏈車 / 雙針鎖鏈 等變體 (滾邊三本-單針鎖鏈 已被 504 攔截)
    (r"鏈縫車|單針鏈縫|鎖[鍊鏈]|Chainstitch", "401"),
    # ─ 爬網類 ─
    (r"爬網車|三針五線|Flatseam", "605"),
    (r"兩針四線", "602"),
    # ─ 併縫類 (v3: 加 拼縫車 — Flatlock 四針六線變體)─
    (r"併縫車|拼縫車|Flatlock", "607"),
    # ─ 人字 / 平車 ─
    (r"人字車|Zigzag", "304"),
    # v2: 加「雙針車」(雙針平車變體)
    (r"平車|雙針車", "301"),
]

# v3.2: 擴充 NON_ISO patterns (非縫紉機台 / 裝飾性 specialty / 沒對應 ISO 的特殊機台)
NON_ISO_MACHINES = [
    # ─ 打結 / bartack (非 ISO 縫法) ─
    r"高速電子打結車|打結車",
    r"電子打結.*花樣循環|花樣循環車",  # v3.2: 打結變體 (花樣循環車)
    # ─ 手工 / 燙 / 熨 (非縫紉工段) ─
    r"手工",
    r"整燙|燙工|燙轉|熨",           # v3.2: 加 燙轉 + 熨 (燙轉熨標機)
    # ─ 壓襯 / 按布 / 扒縫 / 褲頭 (specialty 非 ISO) ─
    r"按布機|大鈕扣機|壓襯機",
    r"折邊|烏龍|包邊",
    r"扒縫機",
    r"褲頭車",
    r"六線拷克",
    # ─ 裝飾性 / 花樣 (specialty, 沒 clean ISO) ─
    r"花邊車|狗牙邊",                  # v3.2: 花邊裝飾
    r"裝飾.{0,4}繡|打洞車|小圈繡",    # v3.2: 裝飾繡 + 打洞 (雙針裝飾小圈繡(打洞車))
]


def find_iso_for_machine(machine_zh: str) -> str | None:
    """Map machine name → ISO code. Return None for non-ISO machines."""
    if not machine_zh or not isinstance(machine_zh, str):
        return None
    for pattern in NON_ISO_MACHINES:
        if re.search(pattern, machine_zh):
            return None
    for pattern, iso in MACHINE_TO_ISO_RULES:
        if re.search(pattern, machine_zh):
            return iso
    return None


def walk_l5_steps(bible_data: dict):
    """Yield (l1_code, l1_zh, fabric, l2, l3, l4, l5, machine) for each L5 step."""
    l1_code = bible_data.get("code", "")
    l1_zh = bible_data.get("l1", "")
    for fabric in ("knit", "woven"):
        for l2_entry in bible_data.get(fabric, []) or []:
            l2 = l2_entry.get("l2", "")
            for shape in l2_entry.get("shapes", []) or []:
                l3 = shape.get("l3", "")
                for method in shape.get("methods", []) or []:
                    l4 = method.get("l4", "")
                    for step in method.get("steps", []) or []:
                        l5 = step.get("l5", "")
                        ie = step.get("ie_standard", {})
                        machine = ie.get("machine", "") if isinstance(ie, dict) else ""
                        yield (l1_code, l1_zh, fabric, l2, l3, l4, l5, machine)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不寫入, 只印 stats")
    ap.add_argument("--top-n", type=int, default=30, help="每個 ISO 保留 top-N anchors")
    args = ap.parse_args()

    print(f"════ build_customer_terminology_l5_anchors v2 ════\n")

    iso_anchors = defaultdict(list)
    machine_counts = defaultdict(int)
    machines_no_iso = defaultdict(int)
    n_l5_steps_total = 0
    n_l5_steps_with_iso = 0
    n_l5_steps_non_iso = 0

    bible_files = sorted(BIBLE_DIR.glob("*.json"))
    bible_files = [f for f in bible_files if not f.name.startswith("_")]
    print(f"Walking {len(bible_files)} l2_l3_ie/<L1>.json files...")

    for bible_file in bible_files:
        try:
            data = json.loads(bible_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] parse fail {bible_file.name}: {e}", file=sys.stderr)
            continue

        for (l1_code, l1_zh, fabric, l2, l3, l4, l5, machine) in walk_l5_steps(data):
            n_l5_steps_total += 1
            if not machine:
                continue
            machine_counts[machine] += 1
            iso = find_iso_for_machine(machine)
            if iso is None:
                # 判斷是 NON_ISO 還是真的沒對到
                is_non_iso = any(re.search(p, machine) for p in NON_ISO_MACHINES)
                if is_non_iso:
                    n_l5_steps_non_iso += 1
                else:
                    machines_no_iso[machine] += 1
                continue
            n_l5_steps_with_iso += 1
            anchor = {
                "l1": l1_code, "l1_zh": l1_zh, "fabric": fabric,
                "l2": l2, "l3": l3, "l4": l4, "l5": l5, "machine": machine,
            }
            iso_anchors[iso].append(anchor)

    print(f"\nWalked {n_l5_steps_total} L5 steps total")
    print(f"  with ISO mapped:    {n_l5_steps_with_iso:>6d} ({n_l5_steps_with_iso/max(n_l5_steps_total,1)*100:>5.1f}%)")
    print(f"  non-ISO (手工/燙/壓襯等): {n_l5_steps_non_iso:>6d} ({n_l5_steps_non_iso/max(n_l5_steps_total,1)*100:>5.1f}%)")
    print(f"  unmapped:           {sum(machines_no_iso.values()):>6d} ({sum(machines_no_iso.values())/max(n_l5_steps_total,1)*100:>5.1f}%)")
    print(f"  ISO codes found: {len(iso_anchors)}")

    # Deduplicate
    deduped = {}
    for iso, anchors in iso_anchors.items():
        seen = set()
        unique = []
        for a in anchors:
            key = (a["l1"], a["l5"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(a)
        unique.sort(key=lambda x: (x["l1"], x["l5"]))
        deduped[iso] = unique

    print(f"\nISO → L5 anchor distribution (after dedup):")
    for iso, anchors in sorted(deduped.items(), key=lambda x: -len(x[1])):
        unique_l1 = len(set(a["l1"] for a in anchors))
        print(f"  ISO {iso:>6s}: {len(anchors):>4d} unique anchors across {unique_l1:>2d} L1 parts")

    if machines_no_iso:
        print(f"\nMachines STILL not mapped (top 15):")
        for m, n in sorted(machines_no_iso.items(), key=lambda x: -x[1])[:15]:
            print(f"  {n:>5d}x  {m}")
    else:
        print(f"\n✓ All machines mapped or classified as non-ISO")

    # Patch master
    master = json.loads(MASTER.read_text(encoding="utf-8"))

    iso_codes_in_master = set()
    n_patched = 0
    print(f"\nPatching customer_terminology_master.json entries:")
    for entry in master.get("entries", []):
        canonical = entry.get("canonical", {})
        iso = canonical.get("iso", "")
        iso_codes_in_master.add(iso)
        anchors = deduped.get(iso, [])
        canonical["l5_anchors"] = [
            f"{a['l1']}|{a['l5']}" for a in anchors[:args.top_n]
        ]
        canonical["l5_anchors_detail"] = [
            {"l1": a["l1"], "l1_zh": a["l1_zh"], "fabric": a["fabric"],
             "l5": a["l5"], "machine": a["machine"]}
            for a in anchors[:min(args.top_n, 15)]
        ]
        n_patched += 1
        print(f"  patched ISO {iso}: +{len(canonical['l5_anchors'])} anchors")

    missing_in_bible = iso_codes_in_master - set(deduped.keys())
    if missing_in_bible:
        print(f"\nISO codes in master but NO l5 anchor found in bible: {sorted(missing_in_bible)}")
        print(f"  (這些 ISO 在客人 PDF 出現但聚陽 IE 五階層真的沒對應到該 machine type)")

    master["_l5_anchors_built_at"] = datetime.utcnow().isoformat() + "Z"
    master["_l5_anchors_source"] = (
        "scripts/core/build_customer_terminology_l5_anchors.py v2 — "
        "iso_dictionary + l2_l3_ie/*.json (38 L1 parts) 反查 machine→ISO"
    )
    master["_l5_anchors_stats"] = {
        "n_l5_steps_walked": n_l5_steps_total,
        "n_l5_steps_with_iso": n_l5_steps_with_iso,
        "n_l5_steps_non_iso": n_l5_steps_non_iso,
        "iso_codes_with_anchors": len(deduped),
        "n_entries_patched": n_patched,
        "iso_in_master_no_anchor": sorted(missing_in_bible),
    }
    if "_todo" in master:
        del master["_todo"]

    if args.dry_run:
        print(f"\n[DRY-RUN] would patch {n_patched} entries with l5_anchors. Use --write to commit.")
        return

    bak = MASTER.with_suffix(MASTER.suffix + ".bak_pre_l5_anchors")
    if not bak.exists():
        shutil.copy2(MASTER, bak)
        print(f"\n  backup: {bak.name}")

    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Wrote {MASTER.relative_to(ROOT)}")
    print(f"     {n_patched} entries patched with l5_anchors (+ l5_anchors_detail)")


if __name__ == "__main__":
    main()
