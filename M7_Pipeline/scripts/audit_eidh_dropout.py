"""audit_eidh_dropout.py — 找出 743 件 EIDH 為什麼沒進 designs.jsonl

簡化版:不用 importlib 動態 load build_v3,直接從 designs.jsonl 反推
+ 各 source 檔比對,分類每個 dropped EIDH 卡哪。

跑:python scripts/audit_eidh_dropout.py
"""
from __future__ import annotations
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from m7_eidh_loader import load_m7_index  # noqa: E402

CSV_DIR = ROOT / "m7_organized_v2" / "csv_5level"
DESIGNS_OUT = ROOT / "outputs" / "platform" / "m7_pullon_designs.jsonl"
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_REPORT = DL / "data" / "ingest" / "metadata" / "m7_report.jsonl"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
OUT = ROOT / "outputs" / "platform" / "eidh_dropout_audit.txt"

FILENAME_RE = re.compile(r"^(\d+)_")

# Copy from build_v3
CLIENT_TO_CODE = {
    "OLD NAVY": "ONY", "TARGET": "TGT", "GAP": "GAP", "GAP OUTLET": "GAP",
    "DICKS SPORTING GOODS": "DKS", "DICKS": "DKS", "ATHLETA": "ATH",
    "UNDER ARMOUR": "UA", "KOHLS": "KOH", "A & F": "ANF", "GU": "GU",
    "BEYOND YOGA": "BY",
}


def normalize_client(raw):
    if not raw:
        return None
    cleaned = str(raw).upper().split("(")[0].strip()
    return CLIENT_TO_CODE.get(cleaned)


def main():
    lines = []
    def emit(s=""): print(s); lines.append(s); sys.stdout.flush()

    emit("=" * 90)
    emit("EIDH Dropout Audit — 743 件卡點分析")
    emit("=" * 90)

    # === 1. 收 csv_5level 的 EIDH set ===
    emit("\n[1] Scan csv_5level/ for EIDHs")
    csv_files = sorted(CSV_DIR.glob("*.csv"))
    csv_eidhs = set()
    bad_filename = []
    for p in csv_files:
        m = FILENAME_RE.match(p.name)
        if m:
            csv_eidhs.add(m.group(1))
        else:
            bad_filename.append(p.name)
    emit(f"    csv files: {len(csv_files):,} / unique EIDHs: {len(csv_eidhs):,} / bad filename: {len(bad_filename)}")

    # === 2. 收 designs.jsonl 已 build EIDH ===
    emit("\n[2] Scan designs.jsonl for built EIDHs")
    built_eidhs = set()
    if DESIGNS_OUT.exists():
        for line in open(DESIGNS_OUT, encoding="utf-8"):
            try:
                d = json.loads(line)
                eidh = str(d.get("eidh", "")).strip()
                if eidh:
                    built_eidhs.add(eidh)
            except Exception:
                continue
    emit(f"    designs built: {len(built_eidhs):,}")

    # === 3. Dropped EIDHs ===
    dropped = csv_eidhs - built_eidhs
    emit(f"\n[3] Dropped = csv_eidhs - built_eidhs:  {len(dropped):,} 件")

    if not dropped:
        emit("    (沒 dropout,全進 designs)")
        return

    # === 4. 載 M7 列管 ===
    emit("\n[4] Load M7 列管 (find dropped EIDHs not in 列管 = filter 卡掉)")
    df = load_m7_index()
    sys.stdout.flush()
    eidh_col = None
    for c in df.columns:
        if c.upper() in ("EIDH", "EIDH NO", "EIDH_NO"):
            eidh_col = c
            break
    if not eidh_col:
        # Try by content
        emit(f"    columns: {list(df.columns)[:5]}")
        emit(f"    [!] EIDH column not found,try first col by content")
        eidh_col = df.columns[0]
    m7_eidh_to_row = {}
    for _, r in df.iterrows():
        try:
            eidh = str(r[eidh_col]).strip()
            if eidh and eidh != "nan":
                m7_eidh_to_row[eidh] = r
        except Exception:
            continue
    emit(f"    M7 列管 EIDHs: {len(m7_eidh_to_row):,}")

    # === 5. 分類 dropped EIDH ===
    drop_2_no_meta = []      # csv 有 EIDH 但 M7 列管沒
    drop_3_no_client = []    # M7 列管有但 client 認不出
    drop_45_other = []       # 卡在 csv parse / fabric (need 深查)

    for eidh in dropped:
        meta = m7_eidh_to_row.get(eidh)
        if meta is None:
            drop_2_no_meta.append(eidh)
            continue
        client_full = str(meta.get("客戶", "") or "").strip()
        if not normalize_client(client_full):
            drop_3_no_client.append((eidh, client_full))
            continue
        drop_45_other.append((eidh, client_full, str(meta.get("Item", "")), str(meta.get("W/K", ""))))

    # === 6. Report ===
    emit(f"\n[Summary]")
    emit(f"  csv files passing filename:    {len(csv_eidhs):>5,}")
    emit(f"  designs built:                 {len(built_eidhs):>5,}")
    emit(f"  Dropped total:                 {len(dropped):>5,}")
    emit(f"")
    emit(f"  ❌ 2. csv 有 EIDH 但 M7 列管沒:  {len(drop_2_no_meta):>5,}  ← 列管 filter 把它們踢出去(不是 PullOn?)")
    emit(f"  ❌ 3. client_code 認不出:        {len(drop_3_no_client):>5,}  ← CLIENT_TO_CODE 沒這個客戶名")
    emit(f"  ⚠  4+5. csv parse / fabric 卡:  {len(drop_45_other):>5,}  ← 進列管但卡在 csv row 全 reject / fabric 判不出(要再 audit)")

    if drop_2_no_meta:
        emit(f"\n[卡 2 — 不在列管] 前 20 EIDH:")
        for e in sorted(drop_2_no_meta)[:20]:
            emit(f"  {e}")

    if drop_3_no_client:
        emit(f"\n[卡 3 — client 認不出] by client name:")
        by_client = Counter(c[1] for c in drop_3_no_client)
        for c, n in by_client.most_common():
            emit(f"  {n:>4}× {c!r}  ← CLIENT_TO_CODE 加 entry 就解 {n} 件")

    if drop_45_other:
        emit(f"\n[卡 4+5 — 深層 dropout] 前 20 件 (列管 OK + client OK 但仍卡):")
        for eidh, c, item, wk in drop_45_other[:20]:
            emit(f"  EIDH={eidh}  client={c!r}  Item={item!r}  W/K={wk!r}")
        emit(f"\n  by client:")
        bc = Counter(c[1] for c in drop_45_other)
        for c, n in bc.most_common(10):
            emit(f"    {n:>4}× {c}")
        emit(f"\n  by Item:")
        bi = Counter(c[2] for c in drop_45_other)
        for it, n in bi.most_common(10):
            emit(f"    {n:>4}× {it!r}")

    # === BOM coverage diagnostic ===
    emit(f"\n[BOM 999 件補抓 diagnostic]")
    if M7_REPORT.exists():
        bom_eidhs = set()
        for line in open(M7_REPORT, encoding="utf-8"):
            try:
                r = json.loads(line)
                e = str(r.get("eidh", "") or r.get("EIDH", "")).strip()
                if e:
                    bom_eidhs.add(e)
            except Exception:
                continue
        m7_no_bom = set(m7_eidh_to_row.keys()) - bom_eidhs
        built_no_bom = built_eidhs - bom_eidhs
        emit(f"  m7_report 已抓:                {len(bom_eidhs):>5,}")
        emit(f"  M7 列管 - m7_report (待抓):    {len(m7_no_bom):>5,}")
        emit(f"  designs 已 build 但缺 BOM:     {len(built_no_bom):>5,}  ← 抓完這些 BOM,canonical W/K confidence 升 high")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    emit(f"\n[output] {OUT}")


if __name__ == "__main__":
    main()
