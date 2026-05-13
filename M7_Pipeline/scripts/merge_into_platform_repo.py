"""merge_into_platform_repo.py — 把 M7 v6.4 entries 合進平台 recipes_master.json

Flow:
  1. 讀我的 outputs/platform/recipes_master_platform.json (197 entries)
  2. 讀平台 C:/temp/stytrix-techpack/data/recipes_master.json (1414 entries)
  3. Diff：找 key collision、新增、覆蓋
  4. 三種 merge 策略：
     --mode replace   重複的我覆蓋（PullOn 1180 件比通用準）
     --mode append    重複的兩個都留，前端依 source 優先序選
     --mode skip      重複的不加（只加新 key）
  5. 輸出新的 recipes_master.json + diff report

用法:
  python scripts\\merge_into_platform_repo.py --diff-only
  python scripts\\merge_into_platform_repo.py --mode append
  python scripts\\merge_into_platform_repo.py --mode replace --apply
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MY_PLATFORM = ROOT / "outputs" / "platform" / "recipes_master_platform.json"
PLATFORM_REPO = Path(r"C:\temp\stytrix-techpack")
PLATFORM_RECIPES = PLATFORM_REPO / "data" / "recipes_master.json"
DIFF_REPORT = ROOT / "outputs" / "platform" / "merge_diff_report.md"


def make_key(entry):
    k = entry.get("key", {})
    return (k.get("gender", ""), k.get("dept", ""), k.get("gt", ""), k.get("it", ""), k.get("l1", ""))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["append", "replace", "skip"], default="append",
                   help="重複 key 時：append (兩個都留) / replace (我覆蓋) / skip (我跳過)")
    p.add_argument("--diff-only", action="store_true", help="只產 diff 報告，不改檔案")
    p.add_argument("--apply", action="store_true", help="實際寫回 platform repo")
    args = p.parse_args()

    if not MY_PLATFORM.exists():
        print(f"[!] {MY_PLATFORM} 不存在，先跑 convert_to_platform_schema.py")
        sys.exit(1)
    if not PLATFORM_RECIPES.exists():
        print(f"[!] {PLATFORM_RECIPES} 不存在，請確認 git clone 路徑")
        sys.exit(1)

    print(f"[1] Load M7 v6.4 entries from {MY_PLATFORM.name}")
    mine = json.load(open(MY_PLATFORM, encoding="utf-8"))
    my_entries = mine.get("entries", [])
    print(f"    {len(my_entries)} entries (M7 v6.4)")

    print(f"[2] Load platform recipes from {PLATFORM_RECIPES.relative_to(PLATFORM_REPO)}")
    platform = json.load(open(PLATFORM_RECIPES, encoding="utf-8"))
    plat_entries = platform.get("entries", [])
    print(f"    {len(plat_entries)} entries (platform)")

    # 建 platform key → entries 索引（同 key 可能多個 source）
    plat_index = defaultdict(list)
    for e in plat_entries:
        plat_index[make_key(e)].append(e)

    # 建 my key → entries 索引
    my_index = defaultdict(list)
    for e in my_entries:
        my_index[make_key(e)].append(e)

    print("\n[3] Diff 分析")
    my_keys = set(my_index.keys())
    plat_keys = set(plat_index.keys())

    new_keys = my_keys - plat_keys           # 我有平台沒
    overlap_keys = my_keys & plat_keys       # 兩邊都有
    plat_only = plat_keys - my_keys          # 平台有我沒（保留不動）

    print(f"  我新增（平台沒）:        {len(new_keys)} keys")
    print(f"  重疊（兩邊都有）:        {len(overlap_keys)} keys")
    print(f"  平台獨有（不動）:        {len(plat_only)} keys")
    print(f"  Total after merge:      ~{len(my_keys) + len(plat_only)} unique keys")

    # 對重疊 entries 做 ISO top-1 對照
    print("\n[4] 重疊 entry 的 ISO top-1 對照（我 vs 平台 — sample 10）:")
    iso_match = 0
    iso_diff_examples = []
    for k in list(overlap_keys)[:50]:
        my_e = my_index[k][0]
        plat_e_list = plat_index[k]
        # 平台同 key 可能有多個 source（recipe / consensus / v4.3 / ...），取第一個比
        plat_e = plat_e_list[0]
        my_iso = (my_e.get("iso_distribution") or [{}])[0].get("iso", "")
        plat_iso = (plat_e.get("iso_distribution") or [{}])[0].get("iso", "")
        my_n = my_e.get("n_total", 0)
        plat_n = plat_e.get("n_total", 0)
        if my_iso == plat_iso:
            iso_match += 1
        elif len(iso_diff_examples) < 10:
            iso_diff_examples.append({
                "key": k,
                "my_iso": my_iso, "my_n": my_n,
                "plat_iso": plat_iso, "plat_n": plat_n,
                "plat_source": plat_e.get("source", ""),
            })
    print(f"  Top ISO 相符:  {iso_match}/{min(len(overlap_keys), 50)}")
    if iso_diff_examples:
        print(f"  Top ISO 不同（前 {len(iso_diff_examples)} 個）:")
        for ex in iso_diff_examples:
            print(f"    {ex['key']}")
            print(f"      我 (m7,n={ex['my_n']:>4}):     {ex['my_iso']}")
            print(f"      平台 ({ex['plat_source'][:8]},n={ex['plat_n']:>3}):  {ex['plat_iso']}")

    # Diff 報告
    print(f"\n[5] 寫 diff 報告 → {DIFF_REPORT}")
    DIFF_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(DIFF_REPORT, "w", encoding="utf-8") as f:
        f.write(f"# M7 v6.4 → Platform Merge Diff Report\n\n")
        f.write(f"產生時間: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n\n")
        f.write(f"## 數字\n\n")
        f.write(f"| | 數量 |\n|---|---|\n")
        f.write(f"| M7 v6.4 entries | {len(my_entries)} |\n")
        f.write(f"| Platform existing | {len(plat_entries)} |\n")
        f.write(f"| 我新增（平台沒） | **{len(new_keys)}** |\n")
        f.write(f"| 重疊 keys | {len(overlap_keys)} |\n")
        f.write(f"| 平台獨有 | {len(plat_only)} |\n")
        f.write(f"\n重疊 entry 的 ISO top-1 對照: 相符 {iso_match}/{min(len(overlap_keys), 50)}\n\n")

        f.write(f"## 我新增的 keys (top 30, sorted by n_total)\n\n")
        new_sorted = sorted(
            [(my_index[k][0], k) for k in new_keys],
            key=lambda x: -x[0].get("n_total", 0),
        )[:30]
        f.write(f"| Key | n_total | Top ISO | Confidence |\n|---|---|---|---|\n")
        for e, k in new_sorted:
            top_iso = (e.get("iso_distribution") or [{}])[0]
            f.write(f"| {'/'.join(k)} | {e.get('n_total', 0)} | "
                    f"ISO {top_iso.get('iso', '?')} ({top_iso.get('pct', 0)}%) | "
                    f"{e.get('confidence', '?')} |\n")

        f.write(f"\n## 重疊 keys 的 ISO 不同的（前 20）\n\n")
        f.write(f"| Key | M7 ISO (n) | Platform ISO (n, source) |\n|---|---|---|\n")
        for ex in iso_diff_examples:
            k = ex["key"]
            f.write(f"| {'/'.join(k)} | "
                    f"{ex['my_iso']} (n={ex['my_n']}) | "
                    f"{ex['plat_iso']} (n={ex['plat_n']}, {ex['plat_source']}) |\n")

    if args.diff_only:
        print(f"\n[diff-only] 不寫 platform repo")
        return

    # Merge
    print(f"\n[6] Merge mode: {args.mode}")
    final_entries = list(plat_entries)  # 從平台現有開始
    n_added = n_replaced = n_skipped = 0

    if args.mode == "append":
        # 全加（重複的兩個都留）
        final_entries.extend(my_entries)
        n_added = len(my_entries)

    elif args.mode == "replace":
        # 重疊的：把平台同 key 的所有 entries 拿掉，換成我的
        plat_kept = []
        for e in plat_entries:
            k = make_key(e)
            if k not in overlap_keys:
                plat_kept.append(e)
        final_entries = plat_kept + my_entries
        n_replaced = sum(len(plat_index[k]) for k in overlap_keys)
        n_added = len(my_entries) - len(overlap_keys)

    elif args.mode == "skip":
        # 重疊的跳過，只加新 key
        for e in my_entries:
            k = make_key(e)
            if k in new_keys:
                final_entries.append(e)
                n_added += 1
            else:
                n_skipped += 1

    print(f"  Added:    {n_added}")
    print(f"  Replaced: {n_replaced} (platform 原 entries 被覆蓋)")
    print(f"  Skipped:  {n_skipped}")
    print(f"  Final entries: {len(final_entries)}")

    # Update doc
    new_doc = dict(platform)
    new_doc["entries"] = final_entries

    # Update source_versions
    sv = new_doc.get("source_versions", {})
    sv["m7_pullon_v6_4"] = "M7_Pipeline/outputs/platform/recipes_master_v6.jsonl (470 6-dim → 197 5-dim)"
    new_doc["source_versions"] = sv

    # Update stats
    stats = new_doc.get("stats", {})
    stats["m7_pullon_added"] = n_added
    stats["m7_pullon_replaced"] = n_replaced
    stats["m7_pullon_total"] = len(final_entries)
    stats["m7_merged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_doc["stats"] = stats

    if not args.apply:
        # 只寫到 outputs/，不動 repo
        out_local = ROOT / "outputs" / "platform" / "recipes_master_merged_preview.json"
        with open(out_local, "w", encoding="utf-8") as f:
            json.dump(new_doc, f, ensure_ascii=False, indent=2)
        print(f"\n[preview] 寫到 {out_local}（沒動 platform repo）")
        print(f"  確認 OK 後加 --apply 寫回 repo:")
        print(f"  python scripts\\merge_into_platform_repo.py --mode {args.mode} --apply")
    else:
        # 備份原檔 + 寫回 repo
        backup = PLATFORM_RECIPES.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copy2(PLATFORM_RECIPES, backup)
        print(f"\n[backup] {backup.name}")

        with open(PLATFORM_RECIPES, "w", encoding="utf-8") as f:
            json.dump(new_doc, f, ensure_ascii=False, indent=2)
        print(f"[applied] {PLATFORM_RECIPES} ({PLATFORM_RECIPES.stat().st_size:,} bytes)")
        print(f"\n下一步：")
        print(f"  cd {PLATFORM_REPO}")
        print(f"  git diff data/recipes_master.json | Select-Object -First 80   # 檢查 diff")
        print(f"  git add data/recipes_master.json")
        print(f"  git commit -m 'feat(data): merge M7 PullOn v6.4 ({n_added} new entries)'")
        print(f"  git push")


if __name__ == "__main__":
    main()
