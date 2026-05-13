"""
extract_unified_m7.py — M7 PullOn 多客戶 unified extractor

對應 Download0504/star_schema/scripts/extract_unified.py，但 PullOn-only：
  - 讀 designs.jsonl + pptx/*.txt + uploads/*.pdf
  - 重用 4_pipeline.py 的 ZH_TO_L1 / GLOSSARY_EN_TO_ZH / ISO_RE / SEW_KW / translate
  - 輸出 Download0504 schema 的 unified/facts.jsonl + dim.jsonl

facts.jsonl schema（跟 Download0504 一致）：
  zone_zh, l1_code, iso, combo, method, confidence, source_line,
  design_id, bucket, gt_group, source
  + M7 加碼: client, eidh

dim.jsonl schema：
  design_id, desc, item_type, department, bucket, year, month, file,
  status, sources, gt_group
  + M7 加碼: client, eidh

用法：
  python scripts/extract_unified_m7.py \\
      --ingest-dir ../stytrix-pipeline-Download0504/data/ingest \\
      --out ../stytrix-pipeline-Download0504/data/ingest/unified
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 從 m7_constants 載 enrich_method_zh + find_all_zones_en + KW_TO_L1_BOTTOMS
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from m7_constants import (
        enrich_method_zh as _enrich_method_zh,
        find_all_zones_en as _find_all_zones_en,
        KW_TO_L1_BOTTOMS as _KW_TO_L1_BOTTOMS,
    )
except ImportError:
    def _enrich_method_zh(method_en, iso, combo, line):
        return method_en
    def _find_all_zones_en(text, kw_map):
        return []
    _KW_TO_L1_BOTTOMS = {}


# ════════════════════════════════════════════════════════════
# 重用 4_pipeline.py 的 mapping
# ════════════════════════════════════════════════════════════

ZH_TO_L1 = {
    "腰頭":"WB","褲合身":"PS","褲襠":"RS","褲口":"LO","口袋":"PK","商標":"LB",
    "剪接線_下身類":"SB","貼合":"BN","繩類":"DC","其它":"OT","襬叉":"BP",
    "裡布":"LI","釦鎖":"BS","前立":"PL","褶":"PD","帶絆":"LP",
    "領":"NK","肩":"SH","袖口":"SL","下襬":"BM","脅邊":"SS",
    "袖籠":"AH","袖襱":"AE","領貼條":"NT","拉鍊":"ZP","釦環":"HL",
    "袋蓋":"FP","肩帶":"ST","帽子":"HD","拇指洞":"TH","行縫":"QT",
    "裝飾片":"DP","領襟":"NP","剪接線_上身類":"SA","裙合身":"SR",
}
L1_KEYS_SORTED = sorted(ZH_TO_L1.keys(), key=len, reverse=True)  # 長字優先比對

# Zone alias：別名 → 主 zone (從 OT 樣態分析得出)
ZONE_ALIAS = {
    "腿口": "褲口", "腿口邊": "褲口", "褲腿口": "褲口",
    "前後襠": "褲襠", "前後襠壓": "褲襠", "前襠": "褲襠", "後襠": "褲襠",
    "前襠線": "褲襠", "後襠線": "褲襠", "下襠": "褲襠", "下襠線": "褲襠",
    "鬆緊帶": "腰頭", "鬆緊": "腰頭", "腰圍": "腰頭", "腰邊": "腰頭",
    "袋貼": "口袋", "袋貼兩片": "口袋", "口袋貼條": "口袋", "貼袋": "口袋",
    "暗袋": "口袋", "後袋": "口袋", "前袋": "口袋", "側袋": "口袋",
    "前中繩口": "繩類", "腰繩": "繩類", "繩": "繩類",
    "繡花": "裝飾片", "繡花雞眼": "裝飾片",
    "裡褲": "裡布", "內裡": "裡布",
    "扣眼": "釦鎖", "雞眼": "釦鎖",
    "後幅司": "剪接線_下身類", "幅司": "剪接線_下身類", "yoke": "剪接線_下身類",
    "側縫": "脅邊", "側邊": "脅邊", "脅縫": "脅邊",
    "下襬邊": "下襬", "腰底": "腰頭", "腰圍尺寸": "腰頭",
    "拉鍊邊": "拉鍊", "拉鏈": "拉鍊",
}
ALIAS_KEYS_SORTED = sorted(ZONE_ALIAS.keys(), key=len, reverse=True)

GLOSSARY_EN_TO_ZH = {
    "SN TS": "單針壓線", "SNTS": "單針壓線", "TOPSTITCH": "壓明線",
    "CHAINSTITCH": "鎖鏈車", "CHAIN STITCH": "鎖鏈車",
    "COVERSTITCH": "三本雙針", "CVRST": "三本雙針", "CS": "三本雙針",
    "OVERLOCK": "拷克", "SERGE": "拷克", "SERGED": "拷克",
    "FLATLOCK": "併縫", "FLATSEAM": "併縫",
    "BINDING": "滾條", "TURN IN BINDING": "反折包邊",
    "FELLED SEAM": "包縫", "LAPPED SEAM": "搭縫", "SATIN STITCH": "緞紋",
    "BARTACK": "打結車", "BAR TACK": "打結車",
    "EDGESTITCH": "臨邊線", "EDGE STITCH": "臨邊線",
    "CLEAN FINISH": "包光", "CLEAN FIN": "包光",
    "TURNBACK": "反折", "TURN BACK": "反折", "TURN & TURN": "反折兩次",
    "TB": "反折", "DBL TB": "雙反折", "UNDERSTITCHED": "壓線", "STRADDLE": "跨壓",
    "1NTS": "單針壓線", "2NTS": "雙針壓線", "2N3TH": "三本雙針", "3N5TH": "三針五線",
    "1N": "單針", "2N": "雙針", "3N": "三針", "4N": "四針",
    "DBL NDL": "雙針", "NDL": "針", "BONDED": "熱貼合",
    "WAISTBAND": "腰頭", "WAIST": "腰頭", "WB": "腰頭",
    "POCKET": "口袋", "HEM": "下襬",
    "RISE": "襠", "INSEAM": "內側線", "OUTSEAM": "外側線",
    "FLY": "前立", "VENT": "襬叉", "YOKE": "幅司",
    "GUSSET": "檔片", "LINER": "裡布", "LINING": "裡布",
    "ELASTIC": "鬆緊帶", "DRAWCORD": "腰繩", "DRAWSTRING": "腰繩",
    "PLACKET": "門襟", "BUTTONHOLE": "扣眼",
    "EYELET": "雞眼", "EYELETS": "雞眼",
    "LEG OPENING": "褲口", "LEG HEM": "褲口", "PANT HEM": "褲口",
    "SIDE SEAM": "側縫", "SIDE STRIPES": "側條",
    "BACK YOKE": "後幅司", "FRONT": "前", "BACK": "後", "STRIPE": "條紋",
}

# Sewing keyword → method (用於從 callout text 萃取 method)
KEYWORD_TO_METHOD = {
    "COVERSTITCH": "COVERSTITCH", "CVRST": "COVERSTITCH", "2N3TH": "COVERSTITCH",
    "3N5TH": "COVERSTITCH",
    "OVERLOCK": "OVERLOCK", "SERGE": "OVERLOCK", "SERGED": "OVERLOCK",
    "FLATLOCK": "FLATLOCK", "FLATSEAM": "FLATLOCK",
    "TOPSTITCH": "TOPSTITCH", "SN TS": "TOPSTITCH", "SNTS": "TOPSTITCH",
    "EDGESTITCH": "TOPSTITCH", "EDGE STITCH": "TOPSTITCH",
    "CHAINSTITCH": "CHAINSTITCH", "CHAIN STITCH": "CHAINSTITCH",
    "BARTACK": "BARTACK", "BAR TACK": "BARTACK",
    "BINDING": "BINDING", "TURN IN BINDING": "BINDING",
    "BLINDHEM": "BLINDHEM", "BLIND HEM": "BLINDHEM",
    "BONDED": "BONDED",
    # 中文
    "三本": "COVERSTITCH", "三針五線": "COVERSTITCH",
    "拷克": "OVERLOCK", "鎖縫": "OVERLOCK",
    "併縫": "FLATLOCK",
    "單針": "TOPSTITCH", "雙針": "TOPSTITCH", "壓線": "TOPSTITCH",
    "鎖鏈車": "CHAINSTITCH",
    "打結車": "BARTACK",
    "滾條": "BINDING", "反折包邊": "BINDING",
    "暗縫": "BLINDHEM",
    "熱貼合": "BONDED",
}

ISO_RE = re.compile(r"\b(301|401|406|503|504|512|514|515|516|601|602|605|607)\b")
MARGIN_RE = re.compile(r'\d+/\d+["”]')
NEEDLE_RE = re.compile(r"\b[23]N\b|\b[23]NDL\b|\b2N3TH\b|\b3N5TH\b", re.I)

EXCLUDE_TITLES = ["GRADE REVIEW", "REF IMAGES", "REFERENCE IMAGES", "INSPIRATION IMAGES",
                  "INSPIRATION", "FIT COMMENTS", "FIT SAMPLE IMAGES",
                  "PATTERN CORRECTIONS", "NEXT STEPS", "MOCK NECK REFERENCES"]
POM_KW = ["POM NAME", "TOL FRACTION", "VENDOR ACTUAL", "SAMPLE EVAL", "QC EVALUATION"]
SEW_KW = list(KEYWORD_TO_METHOD.keys())
CUSTOMER_FONTS = {"DSGSans": "DICKS"}


# ════════════════════════════════════════════════════════════
# Translate (EN→ZH，重用 4_pipeline.py)
# ════════════════════════════════════════════════════════════

def translate(text: str) -> str:
    out = text
    for kw in sorted(GLOSSARY_EN_TO_ZH, key=len, reverse=True):
        zh = GLOSSARY_EN_TO_ZH[kw]
        pattern = r'(?<![A-Za-z])' + re.escape(kw) + r'(?![A-Za-z])'
        out = re.sub(pattern, zh, out, flags=re.IGNORECASE)
    return out


# ════════════════════════════════════════════════════════════
# Callout → Facts 拆解
# ════════════════════════════════════════════════════════════

def extract_facts_from_line(line: str, source: str, design_id: str,
                            client: str, eidh: int, bucket: str,
                            gt_group: str) -> list[dict]:
    """
    從一行 callout text 拆出 0~N 個 fact。
    一個 zone × N 個 ISO → N 筆 fact (combo 標連環)
    沒 ISO 但有 sewing keyword → 1 筆 fact (iso="zh_inferred", confidence="zh_inferred")
    """
    line = line.strip()
    if len(line) < 4:
        return []

    # ── 多 zone 支援：先試英文直接 → L1（含 multi-zone splitter）──
    # 例：「RISE/OUTSEAM/INSEAM:」→ [(RS,褲襠), (SS,脅邊), (PS,褲合身)]
    en_zones = _find_all_zones_en(line, _KW_TO_L1_BOTTOMS)

    # 找 zone (主字典先比，alias 次之) — 中文 path（PPTX 主流）
    zone_zh = None
    l1_code = ""
    for k in L1_KEYS_SORTED:
        if k in line:
            zone_zh = k
            l1_code = ZH_TO_L1[k]
            break
    # alias
    if not zone_zh:
        for alias in ALIAS_KEYS_SORTED:
            if alias in line:
                zone_zh = ZONE_ALIAS[alias]
                l1_code = ZH_TO_L1.get(zone_zh, "OT")
                break
    # 沒中文 zone → 試英文 → 翻
    if not zone_zh:
        zh_line = translate(line)
        for k in L1_KEYS_SORTED:
            if k in zh_line:
                zone_zh = k
                l1_code = ZH_TO_L1[k]
                break
        if not zone_zh:
            for alias in ALIAS_KEYS_SORTED:
                if alias in zh_line:
                    zone_zh = ZONE_ALIAS[alias]
                    l1_code = ZH_TO_L1.get(zone_zh, "OT")
                    break

    # 找 ISO codes
    isos = ISO_RE.findall(line) or ISO_RE.findall(translate(line))
    isos = list(dict.fromkeys(isos))  # de-dup keep order
    combo = "+".join(isos) if len(isos) >= 2 else None

    # 找 method (sewing keyword)
    method = None
    upper = line.upper()
    for kw, m in KEYWORD_TO_METHOD.items():
        if kw.upper() in upper:
            method = m
            break

    # GUARD：沒 ISO 也沒 method → 不算做工指令（多半是 POM 尺寸表/部位標示）
    # 例：「前襠至頂邊」「後襠至頂邊」這種 ATHLETA POM 量測欄
    if not isos and not method:
        return []

    # 有 ISO 或 method 但沒 zone → zone 設 OT
    if not zone_zh:
        zone_zh = "其它"
        l1_code = "OT"

    # 沒 method 但有 ISO → 從 ISO 推 method
    if not method and isos:
        ISO_TO_METHOD = {
            "301": "TOPSTITCH", "401": "CHAINSTITCH",
            "406": "COVERSTITCH", "503": "OVERLOCK", "504": "OVERLOCK",
            "514": "OVERLOCK", "515": "OVERLOCK", "516": "OVERLOCK",
            "601": "COVERSTITCH", "602": "COVERSTITCH", "605": "COVERSTITCH",
            "607": "FLATLOCK",
        }
        method = ISO_TO_METHOD.get(isos[0], "")

    confidence = "explicit" if isos else "zh_inferred"

    # ── 多 zone case：英文路徑切到 ≥2 個 zone，每 zone 各生 fact ──
    if en_zones and len(en_zones) >= 2:
        facts = []
        for zl1, zzh in en_zones:
            if isos:
                for iso in isos:
                    zh_method = _enrich_method_zh(method, iso, combo, line)
                    facts.append({
                        "zone_zh": zzh, "l1_code": zl1,
                        "iso": iso, "combo": combo, "method": zh_method or method or "",
                        "confidence": confidence,
                        "source_line": line[:300],
                        "design_id": design_id, "bucket": bucket,
                        "gt_group": gt_group, "source": source,
                        "client": client, "eidh": eidh,
                    })
            else:
                zh_method = _enrich_method_zh(method, None, None, line)
                facts.append({
                    "zone_zh": zzh, "l1_code": zl1,
                    "iso": None, "combo": None, "method": zh_method or method or "",
                    "confidence": confidence,
                    "source_line": line[:300],
                    "design_id": design_id, "bucket": bucket,
                    "gt_group": gt_group, "source": source,
                    "client": client, "eidh": eidh,
                })
        return facts

    facts = []
    if isos:
        for iso in isos:
            # 套 Style Guide canonical method（"COVERSTITCH" → "三本雙針(406)"）
            zh_method = _enrich_method_zh(method, iso, combo, line)
            facts.append({
                "zone_zh": zone_zh, "l1_code": l1_code,
                "iso": iso, "combo": combo, "method": zh_method or method or "",
                "confidence": confidence,
                "source_line": line[:300],
                "design_id": design_id, "bucket": bucket,
                "gt_group": gt_group, "source": source,
                "client": client, "eidh": eidh,
            })
    else:
        facts.append({
            "zone_zh": zone_zh, "l1_code": l1_code,
            "iso": None, "combo": None, "method": method or "",
            "confidence": confidence,
            "source_line": line[:300],
            "design_id": design_id, "bucket": bucket,
            "gt_group": gt_group, "source": source,
            "client": client, "eidh": eidh,
        })
    return facts


# ════════════════════════════════════════════════════════════
# PDF text-layer extractor (重用 4_pipeline.py)
# ════════════════════════════════════════════════════════════

# detect_construction_pages 已抽到 shared/pdf_helpers.py（更完整：含 Centric8 排除）
from shared.pdf_helpers import detect_construction_pages  # noqa: E402


def extract_pdf_text_callouts(pdf_path: Path, callout_pages: list) -> list[str]:
    """從 callout 頁抽文字層，回傳 list of callout text strings"""
    try:
        import fitz
    except ImportError:
        return []
    out = []
    try:
        doc = fitz.open(str(pdf_path))
        for cp in callout_pages:
            page = doc[cp["page"] - 1]
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
        print(f"  [!] PDF text extract fail {pdf_path.name}: {e}", file=sys.stderr)
    return out


# ════════════════════════════════════════════════════════════
# Bucket / GT group 推導
# ════════════════════════════════════════════════════════════

def derive_bucket(design_meta: dict) -> str:
    """
    PullOn bucket = {wk}_BOTTOMS，跨客戶可 union 找 consensus。
    client 不放 bucket（保留在 fact.client 欄獨立 query），這樣同布種同部位
    跨客戶的做工會 group 在一起算 ISO/method 分布。
    """
    wk = (design_meta.get("wk") or "").upper().strip() or "UNKNOWN"
    return f"{wk}_BOTTOMS"


def derive_gt_group(design_meta: dict) -> str:
    """PullOn 全是 BOTTOMS"""
    item = (design_meta.get("item") or "").upper()
    if "PANT" in item or "SHORT" in item or "LEGGING" in item or "BOTTOM" in item:
        return "BOTTOMS"
    if "TOP" in item or "TEE" in item or "SHIRT" in item:
        return "TOPS"
    return "BOTTOMS"  # PullOn default


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="M7 PullOn unified extractor")
    p.add_argument("--ingest-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--skip-pdf", action="store_true", help="只跑 PPTX，不跑 PDF text-layer")
    args = p.parse_args()

    ingest = Path(args.ingest_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    designs_path = ingest / "metadata" / "designs.jsonl"
    if not designs_path.exists():
        print(f"[!] designs.jsonl 不存在: {designs_path}", file=sys.stderr)
        sys.exit(1)

    # 1. Load designs
    designs = {}  # full_id -> meta
    with open(designs_path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            full_id = f"{d.get('client', '')}_{d.get('design_id', '')}"
            designs[full_id] = d
    print(f"[load] designs.jsonl: {len(designs)} designs")

    facts = []
    sources_per_design = defaultdict(set)

    # 2. PPTX → facts
    pptx_dir = ingest / "pptx"
    pptx_files = sorted(pptx_dir.glob("*.txt")) if pptx_dir.exists() else []
    print(f"\n[PPTX] {len(pptx_files)} txt files")
    for txt in pptx_files:
        # 檔名 = {client}_{design_id}.txt → 反向比對 designs
        stem = txt.stem
        d = designs.get(stem)
        if not d:
            print(f"  [!] no metadata for {stem}")
            continue
        design_id = d["design_id"]
        client = d.get("client", "")
        eidh = d.get("eidh")
        bucket = derive_bucket(d)
        gt_group = derive_gt_group(d)

        text = txt.read_text(encoding="utf-8", errors="replace")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        n_facts_before = len(facts)
        for line in lines:
            facts.extend(extract_facts_from_line(
                line, "pptx", design_id, client, eidh, bucket, gt_group
            ))
        added = len(facts) - n_facts_before
        if added > 0:
            sources_per_design[stem].add("pptx")
        print(f"  {stem:30s} {len(lines):4d} lines → {added} facts")

    # 3. PDF text-layer → facts (DICKS 等有 text layer 的)
    if not args.skip_pdf:
        uploads = ingest / "uploads"
        if uploads.exists():
            print(f"\n[PDF text-layer] scanning {uploads}")
            for full_id, d in designs.items():
                source_file = d.get("source_file", "")
                if not source_file.lower().endswith(".pdf"):
                    continue
                pdf_path = uploads / source_file
                if not pdf_path.exists():
                    continue
                pages = detect_construction_pages(pdf_path)
                if not pages:
                    continue
                callouts = extract_pdf_text_callouts(pdf_path, pages)
                if not callouts:
                    continue
                design_id = d["design_id"]
                client = d.get("client", "")
                eidh = d.get("eidh")
                bucket = derive_bucket(d)
                gt_group = derive_gt_group(d)
                n_facts_before = len(facts)
                for c in callouts:
                    facts.extend(extract_facts_from_line(
                        c, "pdf", design_id, client, eidh, bucket, gt_group
                    ))
                added = len(facts) - n_facts_before
                if added > 0:
                    sources_per_design[full_id].add("pdf")
                print(f"  {full_id:30s} {len(pages)} pages, {len(callouts)} callouts → {added} facts")

    # 4. Write facts.jsonl
    facts_path = out_dir / "facts.jsonl"
    with open(facts_path, "w", encoding="utf-8") as f:
        for fact in facts:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")

    # 5. Write dim.jsonl
    dim_path = out_dir / "dim.jsonl"
    facts_per_design = Counter(f["design_id"] for f in facts)
    with open(dim_path, "w", encoding="utf-8") as f:
        for full_id, d in designs.items():
            if facts_per_design.get(d["design_id"], 0) == 0:
                continue
            row = {
                "design_id": d["design_id"],
                "desc": d.get("design_name", ""),
                "item_type": d.get("item", ""),
                "department": d.get("department", "") or d.get("category", ""),
                "bucket": derive_bucket(d),
                "year": "",
                "month": "",
                "file": d.get("source_file", ""),
                "status": d.get("status", ""),
                "sources": sorted(sources_per_design.get(full_id, set())),
                "gt_group": derive_gt_group(d),
                # M7 加碼
                "client": d.get("client", ""),
                "eidh": d.get("eidh"),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 6. Summary
    print(f"\n=== Summary ===")
    print(f"  facts:  {len(facts)} → {facts_path}")
    print(f"  dim:    {sum(1 for v in facts_per_design.values() if v > 0)} designs → {dim_path}")
    print(f"\n  Source distribution:")
    for s, n in Counter(f["source"] for f in facts).most_common():
        print(f"    {s}: {n}")
    print(f"\n  Confidence:")
    for c, n in Counter(f["confidence"] for f in facts).most_common():
        print(f"    {c}: {n}")
    print(f"\n  Top 10 zones:")
    for z, n in Counter(f["zone_zh"] for f in facts).most_common(10):
        print(f"    {z}: {n}")
    for i, n in Counter(f["iso"] for f in facts if f["iso"]).most_common(10):
        print(f"    {i}: {n}")


if __name__ == "__main__":
    main()
