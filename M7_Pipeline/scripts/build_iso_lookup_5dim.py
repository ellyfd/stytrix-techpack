"""build_iso_lookup_5dim.py — 完整 5 維 ISO 對照表  v2.3（machine->ISO 吃 xlsx + 查詢端 rollup）

v2.3 變更（2026-05-15）
----------------------
- 新增 query_rollup() + `--query` 模式：查詢端可放寬 filter（少 pin 幾維）→ 即時聚合 6 維
  native → 樣本變大、confidence 真的升（標示 pin 了哪幾維、roll up 哪幾維）。這是完整 5/6
  維表打贏 v4/v4.3 凍結 key 的關鍵：使用者自己決定要精準解還是通用解。
- v2.2：machine->ISO 全 exact-match 查 ISO對應五階層機種.xlsx（191 機種，6 個命名差異已併入
  xlsx「備註」欄，不另開 alias 檔）。

來源
----
1. ISO對應五階層機種.xlsx        machine -> ISO 的 SOT（聚陽 IE 維護；repo data/source/）
2. data/ingest/m7/entries.jsonl  M7 PullOn 聚合料，本身就帶完整 6 維 key
3. data/runtime/iso_dictionary.json  ISO -> 中文名

定位：ISO = IE 生產實況（聚陽五階層實際用車）；非 brand construction page 設計指定 ISO。

用法
----
  build:  python build_iso_lookup_5dim.py --repo C:\\temp\\stytrix-techpack
  query:  python build_iso_lookup_5dim.py --query "fabric=KNIT,gt=BOTTOM,l1=PK"
          （維度子集任選：fabric/dept/gender/gt/it/l1，沒 pin 的就 roll up 聚合）
"""
import argparse, csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

SELF_DIR = Path(__file__).resolve().parent
DIMS = ["fabric", "dept", "gender", "gt", "it", "l1"]


def find_repo(explicit):
    cands = [Path(explicit)] if explicit else []
    cands += [Path("C:/temp/stytrix-techpack"), SELF_DIR.parent.parent.parent,
              SELF_DIR.parent.parent, SELF_DIR.parent]
    for c in cands:
        if (c / "data" / "ingest" / "m7" / "entries.jsonl").exists():
            return c
    return None


def find_file(*cands):
    for c in cands:
        if c and Path(c).exists():
            return Path(c)
    return None


def load_iso_dict(repo, out_dir):
    cands = [out_dir / "iso_dictionary.json"]
    if repo:
        cands = [repo / "data" / "runtime" / "iso_dictionary.json",
                 repo / "M7_Pipeline" / "data" / "iso_dictionary.json"] + cands
    for cand in cands:
        if cand.exists():
            try:
                return json.load(open(cand, encoding="utf-8"))["entries"], cand
            except Exception as e:
                print(f"[iso_dict] 跳過 {cand}（{e}）")
    return {}, None


def make_iso_zh(iso_dict):
    def iso_zh(iso):
        if not iso:
            return ""
        if iso in iso_dict:
            return iso_dict[iso].get("zh", "")
        if "+" in iso and "+".join(reversed(iso.split("+"))) in iso_dict:
            return iso_dict["+".join(reversed(iso.split("+")))].get("zh", "")
        if iso == "特車":
            return "特殊機(無標準ISO碼)"
        return ""
    return iso_zh


def load_machine_table(repo, out_dir):
    js = find_file(out_dir / "machine_iso_lookup.json",
                   repo / "data" / "source" / "machine_iso_lookup.json" if repo else None)
    if js:
        d = json.load(open(js, encoding="utf-8"))
        print(f"[machine 對照] 讀 JSON: {js}  ({len(d['machines'])} 機種)")
        return d["machines"], js
    xlsx = find_file(repo / "data" / "source" / "ISO對應五階層機種.xlsx" if repo else None,
                     out_dir / "ISO對應五階層機種.xlsx", SELF_DIR / "ISO對應五階層機種.xlsx")
    if not xlsx:
        print("[!] 找不到 machine_iso_lookup.json 也找不到 ISO對應五階層機種.xlsx")
        sys.exit(1)
    try:
        import openpyxl
    except ImportError:
        print("[!] 需要 openpyxl：pip install openpyxl --break-system-packages")
        sys.exit(1)
    ws = openpyxl.load_workbook(xlsx, data_only=True).active
    machines = {}
    for r in list(ws.iter_rows(values_only=True))[1:]:
        if not r[1]:
            continue
        machines[str(r[1]).strip()] = {
            "iso": (str(r[0]).strip() if r[0] is not None else ""),
            "no_thread": bool(r[2]), "no_iso": bool(r[3]),
            "note": (str(r[4]).strip() if len(r) > 4 and r[4] else "")}
    out = out_dir / "machine_iso_lookup.json"
    json.dump({"_doc": "machine(五階層機種名) -> ISO 對照表。SOT = ISO對應五階層機種.xlsx 的 JSON 轉出。",
               "_source_xlsx": str(xlsx), "machines": machines},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[machine 對照] 從 xlsx 轉出: {xlsx} -> {out}  ({len(machines)} 機種)")
    return machines, xlsx


def resolve(machine, table):
    info = table.get((machine or "").strip())
    if not info:
        return {"iso": None, "status": "missing_from_xlsx"}
    iso = info["iso"]
    if iso in ("-", ""):
        return {"iso": None, "status": "non_sewing"}
    if iso == "特車":
        return {"iso": "特車", "status": "special"}
    return {"iso": iso, "status": "clean"}


def classify_confidence(n_iso, n_designs, n_clients, top_iso_pct):
    if n_iso < 3:
        return "very_low"
    if n_iso < 10:
        return "low"
    if n_iso >= 10 and n_designs >= 3 and top_iso_pct >= 50:
        return "high"
    if n_clients >= 2 and n_iso >= 10:
        return "medium"
    if n_iso >= 5:
        return "medium"
    return "low"


def dist(counter, total, top=None, key="name"):
    items = counter.most_common(top) if top else counter.most_common()
    return [{key: k, "n": n, "pct": round(n / total * 100, 1) if total else 0.0}
            for k, n in items]


# ════════════════════════════════════════════════════════════════════
# 查詢端 rollup —— 給定任意 pin 的維度子集，即時聚合 6 維 native。
# pin 越少 -> 命中格子越多 -> 樣本越大 -> confidence 越高（但答案越通用）。
# 這是「放寬 filter 放大自信指數」的正解：聚合的是真實資料，只是範圍變大；
# 回傳會標清楚 pin 了哪幾維、roll up 哪幾維，所以是「有範圍標示的真信心」。
# ════════════════════════════════════════════════════════════════════
def query_rollup(entries_6dim, pinned, iso_zh=None):
    iso_zh = iso_zh or (lambda x: "")
    pinned = {k: str(v).strip().upper() for k, v in pinned.items() if v}
    bad = [k for k in pinned if k not in DIMS]
    if bad:
        raise ValueError(f"不認得的維度: {bad}（可用: {DIMS}）")
    matched = [e for e in entries_6dim
               if all(str(e["key"].get(d, "")).upper() == v for d, v in pinned.items())]
    iso_c, mach_c = Counter(), Counter()
    clients, steps, designs_sum = set(), 0, 0
    for e in matched:
        steps += e.get("n_steps", 0)
        designs_sum += e.get("n_designs", 0)
        for d in e.get("iso_distribution", []):
            iso_c[d["iso"]] += d["n"]
        for d in e.get("machine_distribution", []):
            mach_c[d["name"]] += d["n"]
        for d in e.get("client_distribution", []):
            clients.add(d["client"])
    n_iso = sum(iso_c.values())
    iso_d = [{"iso": i, "iso_zh": iso_zh(i), "n": n,
              "pct": round(n / n_iso * 100, 1) if n_iso else 0.0}
             for i, n in iso_c.most_common()]
    return {
        "pinned": pinned,
        "rolled_up": [d for d in DIMS if d not in pinned],
        "n_matched_cells": len(matched),
        "n_steps": steps,
        "n_steps_with_iso": n_iso,
        "n_designs_sum": designs_sum,        # 注意：跨格子相加，同 design 可能重複計
        "n_clients": len(clients),           # 跨格子 union，精確
        "top_iso": iso_d[0]["iso"] if iso_d else None,
        "top_iso_zh": iso_d[0]["iso_zh"] if iso_d else None,
        "iso_distribution": iso_d,
        "machine_distribution": dist(mach_c, steps, top=5),
        "confidence": classify_confidence(n_iso, designs_sum, len(clients),
                                          iso_d[0]["pct"] if iso_d else 0),
    }


def do_query(out_dir, repo, query_str):
    table_json = find_file(out_dir / "iso_lookup_5dim_v2.json",
                           (repo / "iso_lookup_5dim_v2.json") if repo else None)
    if not table_json:
        print("[!] 找不到 iso_lookup_5dim_v2.json — 先 build 一次。")
        sys.exit(1)
    payload = json.load(open(table_json, encoding="utf-8"))
    entries6 = payload["entries_6dim"]
    iso_dict, _ = load_iso_dict(repo, out_dir)
    iso_zh = make_iso_zh(iso_dict)
    pinned = {}
    for part in query_str.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            pinned[k.strip().lower()] = v.strip()
    res = query_rollup(entries6, pinned, iso_zh)
    print(f"\n=== query rollup ===")
    print(f"  pin:     {res['pinned']}")
    print(f"  roll up: {res['rolled_up']}")
    print(f"  命中 {res['n_matched_cells']} 個 6 維格子 / {res['n_steps']} steps "
          f"/ {res['n_steps_with_iso']} 有 ISO / {res['n_clients']} clients / "
          f"confidence={res['confidence']}")
    print(f"  ISO 分布:")
    for d in res["iso_distribution"][:8]:
        print(f"    {d['iso']:>6s} {d['iso_zh']:<14s} n={d['n']:>5d} ({d['pct']}%)")
    return res


def run_build(repo, out_dir):
    entries_path = repo / "data" / "ingest" / "m7" / "entries.jsonl"
    iso_dict, iso_dict_path = load_iso_dict(repo, out_dir)
    iso_zh = make_iso_zh(iso_dict)
    print(f"[repo] {repo}\n[entries] {entries_path}\n[iso_dict] {iso_dict_path}\n[out] {out_dir}")
    table, table_src = load_machine_table(repo, out_dir)
    rows = [json.loads(l) for l in open(entries_path, encoding="utf-8")]
    print(f"\n[load] entries.jsonl: {len(rows)} 筆 6 維 entry")

    ent_machines = Counter()
    for r in rows:
        for cl, fabd in r.get("by_client", {}).items():
            for fk, l2l in fabd.items():
                for l2 in l2l:
                    for sh in l2.get("shapes", []):
                        for me in sh.get("methods", []):
                            for st in me.get("l5_steps", []):
                                ent_machines[st.get("machine", "")] += 1
    total_steps = sum(ent_machines.values())
    status_steps = Counter()
    for m, n in ent_machines.items():
        status_steps[resolve(m, table)["status"]] += n
    print(f"\n[machine coverage] {len(ent_machines)} 機種 / {total_steps} steps")
    for s in ("clean", "non_sewing", "special", "missing_from_xlsx"):
        n = status_steps.get(s, 0)
        print(f"  {s:18s} {n:>8d} steps ({n/total_steps*100:.1f}%)")

    xlsx_isos = set(v["iso"] for v in table.values()
                    if v["iso"] and v["iso"] not in ("-", "特車"))
    missing_in_dict = sorted(i for i in xlsx_isos if i not in iso_dict
                             and "+".join(reversed(i.split("+"))) not in iso_dict)

    cov_csv = out_dir / "machine_coverage_report_v2.csv"
    with open(cov_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["machine_中文機種", "n_steps", "對到xlsx", "xlsx_iso", "xlsx_iso_中文",
                    "status", "xlsx備註", "說明"])
        for m, n in ent_machines.most_common():
            res = resolve(m, table)
            info = table.get((m or "").strip())
            note = "" if info else "entries.jsonl 有此機種但 xlsx 沒有 — 請 IE 補進 xlsx"
            w.writerow([m, n, "Y" if info else "N", info["iso"] if info else "",
                        iso_zh(res["iso"]), res["status"],
                        info.get("note", "") if info else "", note])
    json.dump({"_doc": "machine coverage — entries.jsonl 機種 vs ISO對應五階層機種.xlsx",
               "machine_table_source": str(table_src), "step_status": dict(status_steps),
               "missing_from_xlsx": {m: ent_machines[m] for m in ent_machines
                                     if resolve(m, table)["status"] == "missing_from_xlsx"},
               "iso_codes_in_xlsx_missing_from_iso_dictionary": missing_in_dict},
              open(out_dir / "machine_coverage_report_v2.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if missing_in_dict:
        print(f"  note: xlsx 有但 iso_dictionary 仍缺的碼: {missing_in_dict}")

    def new_acc():
        return {"iso": Counter(), "machine": Counter(), "clients": Counter(),
                "designs": set(), "n_steps": 0, "non_sewing_steps": 0,
                "special_steps": 0, "missing_steps": 0, "sec": []}

    acc6, acc5 = defaultdict(new_acc), defaultdict(new_acc)
    for r in rows:
        k = r["key"]
        key6 = tuple(k[d] for d in DIMS)
        key5 = (k["fabric"], k["dept"], k["gender"], k["gt"], k["l1"])
        dids = set(r.get("design_ids", []))
        for cl, fabd in r.get("by_client", {}).items():
            for fk, l2l in fabd.items():
                for l2 in l2l:
                    for sh in l2.get("shapes", []):
                        for me in sh.get("methods", []):
                            for st in me.get("l5_steps", []):
                                machine = st.get("machine", "")
                                res = resolve(machine, table)
                                for acc, key in ((acc6, key6), (acc5, key5)):
                                    a = acc[key]
                                    a["n_steps"] += 1
                                    a["machine"][machine] += 1
                                    a["clients"][cl] += 1
                                    a["designs"] |= dids
                                    sec = st.get("sec")
                                    if isinstance(sec, (int, float)):
                                        a["sec"].append(float(sec))
                                    s = res["status"]
                                    if s == "clean":
                                        a["iso"][res["iso"]] += 1
                                    elif s == "non_sewing":
                                        a["non_sewing_steps"] += 1
                                    elif s == "special":
                                        a["special_steps"] += 1
                                    else:
                                        a["missing_steps"] += 1

    def emit(acc, dims):
        out = []
        for key, a in acc.items():
            kd = dict(zip(dims, key))
            ns, ni = a["n_steps"], sum(a["iso"].values())
            nd, nc = len(a["designs"]), len(a["clients"])
            iso_d = [{"iso": i, "iso_zh": iso_zh(i), "n": n,
                      "pct": round(n / ni * 100, 1) if ni else 0.0}
                     for i, n in a["iso"].most_common()]
            sec = a["sec"]
            out.append({"key": kd, "n_steps": ns, "n_steps_with_iso": ni,
                        "n_designs": nd, "n_clients": nc,
                        "top_iso": iso_d[0]["iso"] if iso_d else None,
                        "top_iso_zh": iso_d[0]["iso_zh"] if iso_d else None,
                        "iso_distribution": iso_d,
                        "machine_distribution": dist(a["machine"], ns, top=5),
                        "client_distribution": dist(a["clients"], ns, key="client"),
                        "non_sewing_pct": round(a["non_sewing_steps"]/ns*100,1) if ns else 0.0,
                        "special_pct": round(a["special_steps"]/ns*100,1) if ns else 0.0,
                        "missing_from_xlsx_pct": round(a["missing_steps"]/ns*100,1) if ns else 0.0,
                        "avg_seconds": round(sum(sec)/len(sec),2) if sec else None,
                        "confidence": classify_confidence(ni, nd, nc,
                                                          iso_d[0]["pct"] if iso_d else 0)})
        out.sort(key=lambda e: (-e["n_steps_with_iso"], -e["n_steps"]))
        return out

    entries6 = emit(acc6, DIMS)
    entries5 = emit(acc5, ["fabric", "dept", "gender", "gt", "l1"])

    payload = {"version": "iso_lookup_5dim_v2.3",
               "key_schema_primary": "Fabric x Department x Gender x GT x L1 (5 維 rollup)",
               "key_schema_native": "Fabric x Department x Gender x GT x IT x L1 (6 維)",
               "query_note": "查詢端可用 build_iso_lookup_5dim.py --query 或 query_rollup() "
                             "對 entries_6dim 即時 rollup（pin 任意維度子集）。",
               "iso_source": "IE 生產實況 — entries.jsonl l5_steps[].machine -> ISO對應五階層機種.xlsx",
               "iso_source_caveat": "此 ISO = 聚陽五階層實際用車；非 brand construction page 設計指定 ISO。",
               "machine_table_source": str(table_src), "built_from": str(entries_path),
               "stats": {"n_entries_6dim": len(entries6), "n_entries_5dim": len(entries5),
                         "n_l5_steps_total": total_steps, "step_status": dict(status_steps),
                         "iso_codes_in_xlsx_missing_from_iso_dictionary": missing_in_dict},
               "entries_5dim": entries5, "entries_6dim": entries6}
    json.dump(payload, open(out_dir / "iso_lookup_5dim_v2.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    with open(out_dir / "iso_lookup_5dim_v2.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["fabric", "department", "gender", "gt", "l1", "top_iso", "top_iso_中文",
                    "top_iso_pct", "iso_分布", "n_steps", "n_steps_有iso", "n_designs",
                    "n_clients", "非縫紉_pct", "特車_pct", "未對到xlsx_pct", "avg_sec",
                    "confidence", "品牌"])
        for e in entries5:
            k = e["key"]
            iso_str = " ".join(f'{d["iso"]}({d["n"]})' for d in e["iso_distribution"][:6])
            top_pct = e["iso_distribution"][0]["pct"] if e["iso_distribution"] else ""
            clients = ",".join(d["client"] for d in e["client_distribution"][:8])
            w.writerow([k["fabric"], k["dept"], k["gender"], k["gt"], k["l1"],
                        e["top_iso"] or "", e["top_iso_zh"] or "", top_pct, iso_str,
                        e["n_steps"], e["n_steps_with_iso"], e["n_designs"], e["n_clients"],
                        e["non_sewing_pct"], e["special_pct"], e["missing_from_xlsx_pct"],
                        e["avg_seconds"] or "", e["confidence"], clients])

    print(f"\n=== iso_lookup_5dim_v2.3 built ===")
    print(f"  6-dim {len(entries6)} / 5-dim {len(entries5)}")
    by_conf = Counter(e["confidence"] for e in entries5)
    for c in ("high", "medium", "low", "very_low"):
        if c in by_conf:
            print(f"    {c:10s}: {by_conf[c]}")
    nw = sum(1 for e in entries5 if e["n_steps_with_iso"] > 0)
    print(f"  5-dim 有 ISO: {nw}/{len(entries5)} ({nw/len(entries5)*100:.1f}%)")

    # demo：同一個 L1=PK，pin 5 維 / 3 維 / 1 維 — 看放寬 filter 後 confidence 怎麼變
    print(f"\n=== query_rollup demo（同 L1=PK，放寬 filter -> 樣本變大 -> 信心升）===")
    for q in ({"fabric": "KNIT", "dept": "ACTIVE", "gender": "WOMEN", "gt": "BOTTOM", "l1": "PK"},
              {"fabric": "KNIT", "gt": "BOTTOM", "l1": "PK"},
              {"l1": "PK"}):
        res = query_rollup(entries6, q, iso_zh)
        pinned_s = ",".join(f"{k}={v}" for k, v in res["pinned"].items())
        print(f"  pin[{pinned_s:42s}] cells={res['n_matched_cells']:>4d} "
              f"steps={res['n_steps']:>6d} top={res['top_iso'] or '-':>5s}"
              f"({res['iso_distribution'][0]['pct'] if res['iso_distribution'] else 0:>5.1f}%) "
              f"conf={res['confidence']}")
    print(f"\n[Output] {out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--query", default=None,
                    help='查詢模式，例：--query "fabric=KNIT,gt=BOTTOM,l1=PK"')
    args = ap.parse_args()
    repo = find_repo(args.repo)
    out_dir = Path(args.out).resolve() if args.out else SELF_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.query:
        do_query(out_dir, repo, args.query)
        return
    if not repo:
        print("[!] 找不到 repo（需有 data/ingest/m7/entries.jsonl）。用 --repo 指定。")
        sys.exit(1)
    run_build(repo, out_dir)


if __name__ == "__main__":
    main()
