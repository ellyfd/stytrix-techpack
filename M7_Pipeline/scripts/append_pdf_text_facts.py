"""
append_pdf_text_facts.py — 補跑 PDF text-layer 抽 fact，append 進 unified/facts.jsonl

用 callout_manifest.jsonl 跳過 detect（avoid redundant 開 PDF 評分）。
直接對 manifest 列出的 callout 頁開 PDF 抽 text → 生 fact。

Resumable：state file 記到第幾個 design，反覆 call 接續。

用法：
  python scripts/append_pdf_text_facts.py [--batch-size 30] [--max-seconds 35]
  反覆 call 直到 ALL DONE。
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback
MANIFEST = M7_ORG / "callout_manifest.jsonl" if (M7_ORG / "callout_manifest.jsonl").exists() else DL / "data" / "ingest" / "pdf" / "callout_manifest.jsonl"
DESIGNS = M7_ORG / "designs.jsonl" if (M7_ORG / "designs.jsonl").exists() else DL / "data" / "ingest" / "metadata" / "designs.jsonl"
UNIFIED_FACTS = M7_ORG / "facts.jsonl" if (M7_ORG / "facts.jsonl").exists() else DL / "data" / "ingest" / "unified" / "facts.jsonl"
PDF_TP = M7_ORG / "pdf_tp"
STATE_FILE = M7_ORG / ".pdf_text_state" if M7_ORG.exists() else DL / "data" / "ingest" / "pdf" / ".pdf_text_state"
OUTPUT_PDF_FACTS = M7_ORG / "pdf_text_facts.jsonl" if M7_ORG.exists() else DL / "data" / "ingest" / "unified" / "pdf_text_facts.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))
from m7_constants import (  # noqa: E402
    ZH_TO_L1, L1_KEYS_SORTED, ZONE_ALIAS, ALIAS_KEYS_SORTED,
    ISO_RE, KEYWORD_TO_METHOD, ISO_TO_METHOD, translate, derive_bucket, derive_gt_group,
    KW_TO_L1_BOTTOMS, find_all_zones_en, enrich_method_zh,
)


def _build_fact(zone_zh, l1_code, iso, combo, method, confidence, line,
                source, design_id, client, eidh, bucket, gt_group):
    return {
        "zone_zh": zone_zh, "l1_code": l1_code,
        "iso": iso, "combo": combo, "method": method or "",
        "confidence": confidence,
        "source_line": line[:300],
        "design_id": design_id, "bucket": bucket,
        "gt_group": gt_group, "source": source,
        "client": client, "eidh": eidh,
    }


def extract_facts_from_line(line, source, design_id, client, eidh, bucket, gt_group):
    """從 callout text 抽 fact。
    新版（2026-05-05 三刀後）：
      1. 英文 zone 直接 → L1（KW_TO_L1_BOTTOMS, 不走 EN→ZH 兩跳）
      2. 多 zone splitter（RISE/OUTSEAM/INSEAM → 3 fact）
      3. ISO→ZH method + gauge（406 → '三本雙針(406), 1/8" 間距'）
    fallback 原有 ZH parser 路徑（PPTX 中文文字仍走老路）"""
    line = line.strip()
    if len(line) < 4:
        return []

    # ── ISO 抽取（先做，後面分流要看有沒有 ISO） ──
    isos = ISO_RE.findall(line) or ISO_RE.findall(translate(line))
    isos = list(dict.fromkeys(isos))
    combo = "+".join(isos) if len(isos) >= 2 else None

    # ── EN method keyword（用 ZH method canonical 蓋過英文） ──
    method_en = None
    upper = line.upper()
    for kw, m in KEYWORD_TO_METHOD.items():
        if kw.upper() in upper:
            method_en = m
            break

    # ── 路徑 A：英文 zone（含多 zone）── 嘗試 BOTTOMS 對映
    en_zones = find_all_zones_en(line, KW_TO_L1_BOTTOMS)
    if en_zones:
        # GUARD
        if not isos and not method_en:
            return []
        confidence = "explicit" if isos else "zh_inferred"
        facts = []
        for l1_code, zone_zh in en_zones:
            if combo:
                m = enrich_method_zh(method_en, None, combo, line)
                facts.append(_build_fact(zone_zh, l1_code, None, combo, m, confidence,
                                          line, source, design_id, client, eidh, bucket, gt_group))
                # combo 也要為各個 ISO 出 fact 嗎？保持單一 combo fact，跟 star_schema 對齊
            elif isos:
                for iso in isos:
                    m = enrich_method_zh(method_en, iso, None, line)
                    facts.append(_build_fact(zone_zh, l1_code, iso, None, m, confidence,
                                              line, source, design_id, client, eidh, bucket, gt_group))
            else:
                # 沒 ISO 但有 method（被前面 GUARD 擋掉了 isos==None+method==None；這裡是 method 有）
                facts.append(_build_fact(zone_zh, l1_code, None, None, method_en or "", confidence,
                                          line, source, design_id, client, eidh, bucket, gt_group))
        return facts

    # ── 路徑 B：原有 ZH parser（PPTX 中文 / 翻譯後文字） ──
    zone_zh = None
    l1_code = ""
    for k in L1_KEYS_SORTED:
        if k in line:
            zone_zh, l1_code = k, ZH_TO_L1[k]
            break
    if not zone_zh:
        for alias in ALIAS_KEYS_SORTED:
            if alias in line:
                zone_zh = ZONE_ALIAS[alias]
                l1_code = ZH_TO_L1.get(zone_zh, "OT")
                break
    if not zone_zh:
        zh_line = translate(line)
        for k in L1_KEYS_SORTED:
            if k in zh_line:
                zone_zh, l1_code = k, ZH_TO_L1[k]
                break
        if not zone_zh:
            for alias in ALIAS_KEYS_SORTED:
                if alias in zh_line:
                    zone_zh = ZONE_ALIAS[alias]
                    l1_code = ZH_TO_L1.get(zone_zh, "OT")
                    break

    method = method_en
    # GUARD
    if not isos and not method:
        return []
    if not zone_zh:
        zone_zh, l1_code = "其它", "OT"
    if not method and isos:
        method = ISO_TO_METHOD.get(isos[0], "")
    # 同步套 ZH method
    confidence = "explicit" if isos else "zh_inferred"
    if isos:
        return [_build_fact(zone_zh, l1_code, iso, combo,
                            enrich_method_zh(method, iso, combo, line),
                            confidence, line, source, design_id, client, eidh, bucket, gt_group)
                for iso in isos]
    return [_build_fact(zone_zh, l1_code, None, None, method or "", confidence,
                        line, source, design_id, client, eidh, bucket, gt_group)]


CUSTOMER_FONTS = {"DSGSans": "DICKS"}


def extract_text_from_pdf_pages(pdf_path, pages):
    """抽 callout 頁的 text spans（仿 extract_unified_m7.extract_pdf_text_callouts）"""
    out = []
    try:
        doc = fitz.open(str(pdf_path))
        for p in pages:
            if p > doc.page_count:
                continue
            page = doc[p - 1]
            blocks = page.get_text("dict").get("blocks", [])
            for b in blocks:
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    for span in line.get("spans", []):
                        t = span["text"].strip()
                        if not t or len(t) < 3:
                            continue
                        font = span.get("font", "")
                        if any(k in t.lower() for k in
                               ['copyright', 'all rights reserved', 'this document', 'tech pack print']):
                            continue
                        cust_font = next((b for cf, b in CUSTOMER_FONTS.items() if cf in font), None)
                        is_caps = bool(re.match(r'^[A-Z][A-Z0-9 \-/&]{3,}:?\s*$', t))
                        is_dash = t.startswith('-') and len(t) > 4
                        has_iso = bool(ISO_RE.search(t))
                        if cust_font or is_caps or is_dash or has_iso:
                            out.append(t[:300])
        doc.close()
    except Exception as e:
        print(f"  [!] {pdf_path.name}: {e}", file=sys.stderr)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--batch-size", type=int, default=30, help="每次處理多少 design")
    p.add_argument("--max-seconds", type=int, default=35, help="sandbox timeout 預算")
    p.add_argument("--reset", action="store_true", help="清 state 重跑")
    args = p.parse_args()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
    if args.reset and OUTPUT_PDF_FACTS.exists():
        OUTPUT_PDF_FACTS.unlink()

    # 1. Load designs (拿 metadata)
    designs = {}
    with open(DESIGNS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            key = (d.get("client", ""), d.get("design_id", ""))
            designs[key] = d

    # 2. Load manifest, group by (client, design_id)
    if not MANIFEST.exists():
        print(f"[!] manifest 不存在: {MANIFEST}", file=sys.stderr)
        sys.exit(1)
    by_design = defaultdict(list)  # (client, design_id) → [page, ...]
    pdf_path_map = {}
    for line in open(MANIFEST):
        e = json.loads(line)
        key = (e.get("client", ""), e.get("design_id", ""))
        by_design[key].append(e["page"])
        pdf_path_map[key] = e.get("pdf", "")
    design_keys = sorted(by_design.keys())
    n_total = len(design_keys)

    # 3. Load state
    next_idx = 0
    if STATE_FILE.exists():
        next_idx = int(STATE_FILE.read_text().strip())
    if next_idx >= n_total:
        print(f"═══ ALL DONE ═══")
        n_facts = sum(1 for _ in open(OUTPUT_PDF_FACTS)) if OUTPUT_PDF_FACTS.exists() else 0
        print(f"  {n_total} designs processed, {n_facts} pdf facts")
        return

    # 4. Process batch
    end = min(next_idx + args.batch_size, n_total)
    print(f"[batch] design {next_idx}..{end-1} of {n_total}")
    start_time = time.time()
    new_facts = 0
    open_mode = "a" if next_idx > 0 else "w"

    with open(OUTPUT_PDF_FACTS, open_mode, encoding="utf-8") as fout:
        i = next_idx
        while i < end:
            elapsed = time.time() - start_time
            if elapsed >= args.max_seconds:
                print(f"  [!] hit {args.max_seconds}s budget at design {i}, stopping")
                break

            client, design_id = design_keys[i]
            pages = by_design[(client, design_id)]
            d = designs.get((client, design_id))
            if not d:
                i += 1
                continue
            pdf_name = pdf_path_map[(client, design_id)]
            # manifest 的 pdf 欄就是 m7_organized_v2/pdf_tp/ 裡的檔名（reorganize 後命名一致）
            pdf_path = PDF_TP / pdf_name
            if not pdf_path.exists():
                # fallback: 從 uploads/ 找
                alt = DL / "data" / "ingest" / "uploads" / pdf_name
                if alt.exists():
                    pdf_path = alt
                else:
                    i += 1
                    continue

            callouts = extract_text_from_pdf_pages(pdf_path, pages)
            bucket = derive_bucket(d)
            gt_group = derive_gt_group(d)
            eidh = d.get("eidh")
            for c in callouts:
                facts = extract_facts_from_line(c, "pdf", design_id, client, eidh, bucket, gt_group)
                for f in facts:
                    fout.write(json.dumps(f, ensure_ascii=False) + "\n")
                    new_facts += 1
            i += 1

    next_idx = i
    STATE_FILE.write_text(str(next_idx))
    print(f"  [done] processed {next_idx - (end - args.batch_size if end > args.batch_size else next_idx)} designs, {new_facts} new facts")
    print(f"  state: {next_idx}/{n_total}")
    if next_idx >= n_total:
        print(f"═══ ALL DONE ═══")


if __name__ == "__main__":
    main()
