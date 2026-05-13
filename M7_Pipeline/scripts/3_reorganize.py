"""
3_reorganize.py — Step 3: TP 分流 + inventory

1_fetch.py 已直接寫 sketches/ 跟 csv_5level/（完整命名），這個腳本只處理：
  - tp_samples_v2/<EIDH>_<款>/ 的 PDF/PPTX 分流到 m7_organized_v2/pdf_tp/ + ppt_tp/
  - 寫 inventory.csv（4 大類完整度 manifest）

分類規則（檔名）：
  翻譯 PPTX/XLSX → ppt_tp/    (含「翻譯/翻YYYY/做工翻譯」keyword 或 (MMDD).pptx 簡寫)
  客人原 PDF/PPTX → pdf_tp/   (含 -en/Adopted/Concept/Initial/PROTO/_TP_)
  其它（MeasurementChart/LAFitComments/客人原圖層）→ 略過

統一命名：<EIDH>_<HSN>_<客戶>_<款>.<ext>

用法：python scripts\\3_reorganize.py
"""

import csv
import re
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent  # M7_Pipeline/
ORG = ROOT / 'm7_organized_v2'
TP_RAW = ROOT / 'tp_samples_v2'

# 2026-05-08：用共用 m7_eidh_loader（new/old 自動 fallback + ITEM_FILTER 同步）
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from m7_eidh_loader import load_m7_index


def clean_name(s: str) -> str:
    s = str(s)
    s = s.replace(' ', '_').replace('&', 'and').replace('/', '_').replace('\\', '_')
    return re.sub(r'[<>:"|?*]', '', s)


def main():
    # 建 4 大類資料夾
    for sub in ('sketches', 'pdf_tp', 'ppt_tp', 'csv_5level'):
        (ORG / sub).mkdir(parents=True, exist_ok=True)

    # 讀索引建 EIDH → metadata（套 ITEM_FILTER）
    df = load_m7_index()
    meta = {}
    for _, row in df.iterrows():
        eidh = int(row['Eidh'])
        meta[eidh] = {
            'hsn': int(row['HEADER_SN']),
            'cust': clean_name(row['客戶']),
            'style': clean_name(row['報價款號']),
        }

    def newname(eidh: int, suffix: str) -> str:
        m = meta[eidh]
        return f"{eidh}_{m['hsn']}_{m['cust']}_{m['style']}{suffix}"

    # 從 tp_samples_v2/ 分流 PDF/PPTX 到 pdf_tp/ + ppt_tp/
    pdf_tp_count = ppt_tp_count = 0
    for d in TP_RAW.glob('*_*'):
        if not d.is_dir():
            continue
        try:
            eidh = int(d.name.split('_')[0])
        except (ValueError, IndexError):
            continue
        if eidh not in meta:
            continue

        for f in d.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            n = f.name.lower()

            # Hard exclude：明確不是 construction 內容的檔
            if any(k in n for k in ('lafitcomments', 'measurementchart', '_lafit',
                                     '_pom_', 'fitcomment', 'sizechart')):
                continue

            # PDF/PPTX/XLSX 全收，分類靠檔名 hint
            is_translation_xlsx = ext == '.xlsx' and ('做工翻譯' in f.name or '翻譯' in f.name)
            is_translation_pptx = ext == '.pptx' and bool(re.search(r'翻譯|翻\d{4}|翻-\d{6,8}', f.name))

            if is_translation_xlsx:
                dst = ORG / 'ppt_tp' / newname(eidh, '_翻譯.xlsx')
                if not dst.exists():
                    shutil.copy2(f, dst)
                    ppt_tp_count += 1
            elif ext == '.pptx':
                # 所有 PPTX → ppt_tp/
                # 翻譯版用 .pptx；客戶原版用 _en.pptx
                suffix = '.pptx' if is_translation_pptx else '_en.pptx'
                dst = ORG / 'ppt_tp' / newname(eidh, suffix)
                if not dst.exists():
                    # 衝突時加 hash 避免覆蓋（同 EIDH 多 PPTX）
                    if (ORG / 'ppt_tp' / newname(eidh, '.pptx')).exists():
                        dst = ORG / 'ppt_tp' / newname(eidh, f'_{f.stem[-6:]}.pptx')
                    shutil.copy2(f, dst)
                    ppt_tp_count += 1
            elif ext == '.pdf':
                # 所有 PDF → pdf_tp/
                dst = ORG / 'pdf_tp' / newname(eidh, '.pdf')
                if not dst.exists():
                    shutil.copy2(f, dst)
                    pdf_tp_count += 1

    print(f"[copy] pdf_tp/ +{pdf_tp_count}  ppt_tp/ +{ppt_tp_count}")

    # 寫 inventory.csv：4 大類完整度
    # ── 預掃 4 個 sub_dir 一次，記每個檔的 EIDH 進 set（O(n)，避開 1180×4×N 的 O(n²)）
    files_per_sub = {sub: set() for sub in ('sketches', 'csv_5level', 'pdf_tp', 'ppt_tp')}
    for sub in files_per_sub:
        d = ORG / sub
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file():
                m = re.match(r'^(\d+)_', f.name)
                if m:
                    files_per_sub[sub].add(int(m.group(1)))

    inv_path = ORG / 'inventory.csv'
    with open(inv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['EIDH', 'HEADER_SN', 'Customer', 'Style',
                    'sketch', 'csv_5level', 'pdf_tp', 'ppt_tp',
                    'completeness', 'missing'])
        for eidh in sorted(meta):
            m = meta[eidh]
            cells = {
                'sketch': eidh in files_per_sub['sketches'],
                'csv_5level': eidh in files_per_sub['csv_5level'],
                'pdf_tp': eidh in files_per_sub['pdf_tp'],
                'ppt_tp': eidh in files_per_sub['ppt_tp'],
            }
            present = sum(cells.values())
            if present == 0:
                continue  # 跳過完全沒抓的 EIDH
            missing = [k for k, v in cells.items() if not v]
            w.writerow([
                eidh, m['hsn'], m['cust'].replace('_', ' '), m['style'],
                'Y' if cells['sketch'] else 'N',
                'Y' if cells['csv_5level'] else 'N',
                'Y' if cells['pdf_tp'] else 'N',
                'Y' if cells['ppt_tp'] else 'N',
                f"{present}/4",
                ','.join(missing) if missing else '',
            ])

    # 統計
    print(f"\n=== m7_organized_v2/ 整理完成 ===")
    for sub in ('sketches', 'pdf_tp', 'ppt_tp', 'csv_5level'):
        n = sum(1 for _ in (ORG / sub).iterdir() if _.is_file())
        print(f"  {sub}/  -> {n} files")
    print(f"\n  inventory.csv -> {inv_path}")

    rows = list(csv.DictReader(open(inv_path, encoding='utf-8-sig')))
    n_ok = sum(1 for r in rows if r['completeness'] == '4/4')
    print(f"\n  4/4 完整: {n_ok}/{len(rows)} EIDH")
    for r in rows:
        if r['completeness'] != '4/4':
            print('    ' + r['EIDH'] + '  ' + r['Customer'][:18] + '  ' + r['Style'][:18] + '  ' + r['completeness'] + '  miss: ' + r['missing'])


if __name__ == "__main__":
    main()
