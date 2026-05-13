"""vlm_fallback_api.py — Anthropic Vision API 版 Vision fallback

對 0-fact image-only PDF design 自動跑 Claude Vision 抽 callout。
比 Read tool 版（vlm_fallback_m7.py）快、可批次、可平行。

需要環境變數：ANTHROPIC_API_KEY

流程：
  1. 讀 outputs/zero_fact_pdfs/_vision_candidates.jsonl（49 designs）
  2. 對每個 design 的每張 image-type PNG：
     - base64 encode
     - 呼 Claude Sonnet Vision API
     - prompt 抽 [{zone_en, iso, combo, method_en, raw_text}]
     - 用 zone_resolver 對應 L1 + ZH method
  3. 累積寫進 vision_facts.jsonl
  4. 印 summary（n_designs, n_facts, n_pages_with_callout）

成本估算：
  49 design × 平均 2 PNG = ~100 calls
  每 call ~1500 input + 500 output = 200K tokens
  Sonnet 4.5 約 USD $1

用法：
  $env:ANTHROPIC_API_KEY="sk-ant-..."  # PowerShell
  python scripts\vlm_fallback_api.py [--limit 5] [--client ONY] [--model sonnet|opus]
"""
import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 2026-05-07：統一 single source of truth → M7_Pipeline/m7_organized_v2/
M7_ORG = ROOT / "m7_organized_v2"
DL = ROOT.parent / "stytrix-pipeline-Download0504"  # legacy fallback only
CANDIDATES = ROOT / "outputs" / "zero_fact_pdfs" / "_vision_candidates.jsonl"
PNG_DIR = M7_ORG / "callout_images"
DESIGNS_JSONL = M7_ORG / "designs.jsonl"
MANIFEST = M7_ORG / "callout_manifest.jsonl"
OUT = M7_ORG / "vision_facts.jsonl"
# Legacy paths (auto-fallback when m7_organized_v2 still empty)
PNG_DIR_LEGACY = DL / "data" / "ingest" / "pdf" / "callout_images"
DESIGNS_JSONL_LEGACY = DL / "data" / "ingest" / "metadata" / "designs.jsonl"
MANIFEST_LEGACY = DL / "data" / "ingest" / "pdf" / "callout_manifest.jsonl"
OUT_LEGACY = DL / "data" / "ingest" / "unified" / "vision_facts.jsonl"
for primary, legacy, name in [
    (PNG_DIR, PNG_DIR_LEGACY, "PNG_DIR"),
    (DESIGNS_JSONL, DESIGNS_JSONL_LEGACY, "DESIGNS_JSONL"),
    (MANIFEST, MANIFEST_LEGACY, "MANIFEST"),
    (OUT, OUT_LEGACY, "OUT"),
]:
    # 若 m7_organized_v2 還沒搬，自動 fallback 讀 legacy（單向：read fallback；write 永遠寫 primary）
    if not primary.exists() and legacy.exists():
        if name in ("OUT",):
            continue  # OUT 是 write target，不 fallback
        if name == "PNG_DIR":
            PNG_DIR = legacy
        elif name == "DESIGNS_JSONL":
            DESIGNS_JSONL = legacy
        elif name == "MANIFEST":
            MANIFEST = legacy

sys.path.insert(0, str(ROOT / "scripts"))
from shared.zone_resolver import (  # noqa: E402
    KW_TO_L1_BOTTOMS, find_all_zones_en, enrich_method_zh,
)
from m7_constants import derive_bucket, derive_gt_group  # noqa: E402

MODEL_MAP = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

VISION_PROMPT = """這是 PDF design BOM/Callout 頁的截圖。請抽出所有 construction callout（縫法標示），回 JSON list 格式：

[
  {"zone_en": "W/B SEAM", "iso": "514+605", "method_en": null, "raw_text": "W/B SEAM: ISO 514+605"},
  {"zone_en": "RISE/OUTSEAM/INSEAM", "iso": "607", "method_en": null, "raw_text": "RISE/OUTSEAM/INSEAM: ISO 607"},
  {"zone_en": "LEG OPENING", "iso": "406", "method_en": null, "raw_text": "LEG OPENING: ISO 406, 1/8\\" GG"}
]

規則：
- 只抽明確的 zone + ISO/method 組合（如 "W/B SEAM: ISO 514+605"），跳過量測標示、人形圖、inspiration 圖
- zone_en 用原文（如 "W/B SEAM"、"LEG OPENING"），不翻譯
- iso：可單個 "514"、可 combo "514+605"、可 null（如果只有 method 沒 ISO）
- method_en：英文縫法 keyword（COVERSTITCH/TOPSTITCH/OVERLOCK/FLATLOCK/CHAINSTITCH/BARTACK），沒就 null
- raw_text：完整的 callout 原文
- 沒任何 callout → 回 []
- 只回純 JSON list，不要 markdown 不要說明"""


def load_designs_meta():
    out = {}
    for line in open(DESIGNS_JSONL, encoding="utf-8"):
        d = json.loads(line)
        out[(d["client"], d["design_id"])] = d
    return out


def load_manifest_pages():
    """每 (client, design_id) → list of (page, type)"""
    out = {}
    for line in open(MANIFEST, encoding="utf-8"):
        e = json.loads(line)
        key = (e.get("client", ""), e.get("design_id", ""))
        out.setdefault(key, []).append((e["page"], e.get("type", "")))
    return out


def _prepare_image(png_path):
    """Pre-process PNG for Vision API: resize > 7800px, recompress > 4.5MB, skip empty.
    Returns (b64_str, media_type) or (None, None) if not usable."""
    try:
        size = os.path.getsize(png_path)
    except OSError:
        return None, None
    if size < 1024:
        return None, None  # empty/broken PNG
    try:
        from PIL import Image
    except ImportError:
        # Fallback: send raw if Pillow not available (will hit 5MB/8000px limits)
        with open(png_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8"), "image/png"
    try:
        img = Image.open(png_path)
        img.load()
    except Exception:
        return None, None
    # Resize: max edge 7800 px (Anthropic limit 8000)
    max_edge = max(img.size)
    if max_edge > 7800:
        ratio = 7800 / max_edge
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
    # Compress: target < 4.5 MB (Anthropic limit 5 MB)
    img_rgb = img.convert("RGB") if img.mode != "RGB" else img
    buf = io.BytesIO()
    quality = 92
    while quality >= 50:
        buf.seek(0); buf.truncate()
        img_rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() < 4_500_000:
            break
        quality -= 8
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def call_vision(client, model, png_path):
    """呼 Anthropic Vision API，回 list of callout dicts"""
    b64, media_type = _prepare_image(png_path)
    if not b64:
        print(f"    [skip] PNG empty/broken/unusable: {png_path.name}")
        return []
    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": b64
                }},
                {"type": "text", "text": VISION_PROMPT},
            ]
        }]
    )
    txt = msg.content[0].text.strip()
    # 砍掉 markdown wrap
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if txt.startswith("json"):
            txt = txt[4:].strip()
    try:
        return json.loads(txt) if txt else []
    except json.JSONDecodeError as e:
        print(f"    [!] JSON parse fail: {e}", file=sys.stderr)
        print(f"    raw: {txt[:200]}", file=sys.stderr)
        return []


def callout_to_facts(callouts, client, design_id, design_meta, png_name):
    """把 Vision 回的 callouts 轉成 vision_facts schema"""
    bucket = derive_bucket(design_meta) if design_meta else "UNKNOWN_BOTTOMS"
    gt_group = derive_gt_group(design_meta) if design_meta else "BOTTOMS"
    eidh = (design_meta or {}).get("eidh")
    facts = []
    for c in callouts:
        zone_en = c.get("zone_en", "").strip()
        iso = c.get("iso")
        method_en = c.get("method_en")
        raw = c.get("raw_text", "")
        if not zone_en or (not iso and not method_en):
            continue
        # 切 multi-zone
        zones = find_all_zones_en(zone_en + ":", KW_TO_L1_BOTTOMS)
        if not zones:
            continue
        # combo 處理
        combo = None
        single_iso = iso
        if iso and "+" in iso:
            combo = iso
            single_iso = None
        zh_method = enrich_method_zh(method_en, single_iso, combo, raw)
        for l1, zzh in zones:
            facts.append({
                "client": client, "design_id": design_id,
                "zone_zh": zzh, "l1_code": l1,
                "iso": single_iso, "combo": combo,
                "method": zh_method or method_en or "",
                "confidence": "vision",
                "source_line": f"{raw} ({png_name})",
                "source": "vision",
                "eidh": eidh, "bucket": bucket, "gt_group": gt_group,
            })
    return facts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0, help="只跑前 N design")
    p.add_argument("--client", default=None, help="只跑特定 client")
    p.add_argument("--model", default="sonnet", choices=["sonnet", "opus", "haiku"])
    p.add_argument("--dry-run", action="store_true", help="不寫檔，只印 summary")
    p.add_argument("--append", action="store_true", help="append 到 vision_facts.jsonl 而非覆蓋")
    p.add_argument("--skip-existing", action="store_true",
                   help="跳過已在 vision_facts.jsonl 處理過的 design")
    p.add_argument("--from-manifest", action="store_true",
                   help="忽略 _vision_candidates.jsonl，直接從 callout_manifest.jsonl 抽全部 design")
    args = p.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY 環境變數未設", file=sys.stderr)
        print("    PowerShell: $env:ANTHROPIC_API_KEY=\"sk-ant-...\"")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("[!] pip install anthropic 先")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    model = MODEL_MAP[args.model]

    # Load candidates + manifest pages
    if not CANDIDATES.exists():
        print(f"[!] 先跑 vlm_fallback_m7.py --mode list 產出 _vision_candidates.jsonl")
        sys.exit(1)

    designs_meta = load_designs_meta()
    manifest_pages = load_manifest_pages()

    # 讀候選
    candidates = []
    if args.from_manifest:
        # 從 callout_manifest 抽全部 image-type pages 的 unique design
        seen = set()
        for line in open(MANIFEST, encoding="utf-8"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "image":
                continue
            cid = e.get("client", "")
            did = e.get("design_id", "")
            key = (cid, did)
            if not cid or not did or key in seen:
                continue
            seen.add(key)
            candidates.append({"client": cid, "design_id": did})
        print(f"[manifest] 從 callout_manifest 抽 {len(candidates)} unique designs (image type)")
    else:
        if not CANDIDATES.exists():
            print(f"[!] 先跑 vlm_fallback_m7.py --mode list 產 _vision_candidates.jsonl，"
                  f"或加 --from-manifest 從 callout_manifest.jsonl 抽全部")
            sys.exit(1)
        for line in open(CANDIDATES, encoding="utf-8"):
            c = json.loads(line)
            candidates.append(c)
        print(f"[candidates] 讀 {len(candidates)} designs from {CANDIDATES.name}")

    if args.client:
        candidates = [c for c in candidates if c["client"] == args.client]
        print(f"  filter client={args.client}: {len(candidates)} designs")

    # skip 已在 vision_facts.jsonl 處理過的
    if args.skip_existing and OUT.exists():
        done = set()
        for line in open(OUT, encoding="utf-8"):
            try:
                f = json.loads(line)
                done.add((f.get("client", ""), f.get("design_id", "")))
            except Exception:
                continue
        before = len(candidates)
        candidates = [c for c in candidates
                     if (c["client"], c["design_id"]) not in done]
        print(f"  skip-existing: 跳過 {before - len(candidates)} 已處理 / 剩 {len(candidates)} 待跑")

    if args.limit:
        candidates = candidates[:args.limit]
    print(f"[scan] 將處理 {len(candidates)} designs (model={args.model})")

    # 開檔（append or write）
    mode = "a" if args.append else "w"
    fout = None if args.dry_run else open(OUT, mode, encoding="utf-8")

    n_facts = 0
    n_pages_scanned = 0
    n_pages_with_callout = 0
    t0 = time.time()

    for i, c in enumerate(candidates, 1):
        client_name = c["client"]
        design_id = c["design_id"]
        # 只看 image-type pages（從 manifest 過濾）
        pages_info = manifest_pages.get((client_name, design_id), [])
        image_pages = [p for p, t in pages_info if t == "image"]
        if not image_pages:
            continue

        meta = designs_meta.get((client_name, design_id), {})
        print(f"\n[{i}/{len(candidates)}] {client_name} {design_id} "
              f"({len(image_pages)} image pages)")

        for page in image_pages:
            png_name = f"{client_name}_{design_id}_p{page}.png"
            png_path = PNG_DIR / png_name
            if not png_path.exists():
                print(f"    [skip] PNG not found: {png_name}")
                continue
            n_pages_scanned += 1
            try:
                callouts = call_vision(client, model, png_path)
            except Exception as e:
                print(f"    [!] API error on {png_name}: {e}")
                continue
            if not callouts:
                print(f"    p{page}: 0 callouts")
                continue
            n_pages_with_callout += 1
            facts = callout_to_facts(callouts, client_name, design_id, meta, png_name)
            print(f"    p{page}: {len(callouts)} callouts → {len(facts)} facts")
            for f in facts:
                if fout:
                    fout.write(json.dumps(f, ensure_ascii=False) + "\n")
                n_facts += 1

    if fout:
        fout.close()

    elapsed = time.time() - t0
    print(f"\n=== Vision API summary ===")
    print(f"  designs scanned:        {len(candidates)}")
    print(f"  pages scanned:          {n_pages_scanned}")
    print(f"  pages with callout:     {n_pages_with_callout}")
    print(f"  total facts extracted:  {n_facts}")
    print(f"  elapsed:                {elapsed:.1f}s")
    print(f"  output:                 {OUT}")
    if not args.dry_run:
        print(f"\n[next] 併入 facts.jsonl + 重 align：")
        print(f"  python scripts\\vlm_fallback_m7.py --mode merge")
        print(f"  python scripts\\align_to_ie_m7.py")
        print(f"  python scripts\\build_consensus_m7.py")
        print(f"  python scripts\\build_construction_bridge_v7.py")


if __name__ == "__main__":
    main()
