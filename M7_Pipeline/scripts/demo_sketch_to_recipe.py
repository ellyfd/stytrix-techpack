"""demo_sketch_to_recipe.py — 端到端 demo：sketch → IE 字典 → HTML 報告

把 VLM 偵測結果（sketch.json）+ v6.4 recipes 字典串起來，產可視化 HTML 報告。

Flow:
  1. 載 outputs/sketch_l1_poc/{stem}.json (VLM 偵測)
  2. 從 EIDH 反查 m7_index → gender / dept / wk / it (6-dim metadata)
  3. 對每個偵測到的 L1，從 recipes_master_v6.jsonl 查對應 recipe
  4. 產 HTML：sketch 縮圖 + L1 list + 每 L1 IE 字典查詢結果

用法:
  python scripts\\demo_sketch_to_recipe.py 306187_10406545_BEYOND_YOGA_SD1262
  python scripts\\demo_sketch_to_recipe.py --all   # 跑全 outputs/sketch_l1_poc/*.json
"""
from __future__ import annotations
import argparse
import base64
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH_POC_DIR = ROOT / "outputs" / "sketch_l1_poc"
SKETCHES_DIR = ROOT / "m7_organized_v2" / "sketches"
RECIPES = ROOT / "outputs" / "platform" / "recipes_master_v6.jsonl"
M7_INDEX_NEW = ROOT.parent / "M7列管_20260507.xlsx"
M7_INDEX_OLD = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
M7_INDEX = M7_INDEX_NEW if M7_INDEX_NEW.exists() else M7_INDEX_OLD
DESIGNS_JSONL = ROOT.parent / "stytrix-pipeline-Download0504" / "data" / "ingest" / "metadata" / "designs.jsonl"

OUT_DIR = ROOT / "outputs" / "demo_reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts"))


# ════════════════════════════════════════════════════════════
# Loaders
# ════════════════════════════════════════════════════════════

PRODUCT_CATEGORY_TO_GENDER = {
    "Women 女士": "WOMEN", "Women": "WOMEN",
    "Men 男士": "MEN", "Men": "MEN",
    "Boy 男童": "BOY", "Boy": "BOY", "Boys": "BOY",
    "Girl 女童": "GIRL", "Girl": "GIRL", "Girls": "GIRL",
    "Baby 嬰童": "BABY", "Baby": "BABY",
    "Kids 童裝": "KIDS",
}


def derive_item_type(design_id: str, program: str = "", item: str = "") -> str:
    text = f"{design_id} {program} {item}".upper()
    if "LEGGING" in text:
        return "LEGGINGS"
    if "JOGGER" in text:
        return "JOGGERS"
    if "CAPRI" in text:
        return "CAPRI"
    if "SKIRT" in text or "SKORT" in text:
        return "SKIRT"
    if "SHORT" in text:
        return "SHORTS"
    return "PANTS"


def load_m7_metadata():
    """eidh → {client, subgroup, item, program, wk, design_id, gender}（用共用 helper 套 ITEM_FILTER）"""
    import pandas as pd
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from m7_eidh_loader import load_m7_index as _load
    try:
        df = _load()
    except FileNotFoundError as e:
        print(f"[!] M7 index 載入失敗: {e}")
        return {}

    out = {}
    for _, row in df.iterrows():
        if not pd.notna(row.get("Eidh")):
            continue
        eidh = str(int(row["Eidh"]))
        gender = "UNKNOWN"
        if "PRODUCT_CATEGORY" in row.index:
            cat = str(row.get("PRODUCT_CATEGORY", "") or "").strip()
            gender = PRODUCT_CATEGORY_TO_GENDER.get(cat, "UNKNOWN")
        out[eidh] = {
            "eidh": eidh,
            "client": str(row.get("客戶", "") or "").strip().upper(),
            "subgroup": str(row.get("Subgroup", "") or "").strip(),
            "item": str(row.get("Item", "") or "").strip(),
            "program": str(row.get("Program", "") or "").strip(),
            "wk": str(row.get("W/K", "") or "").strip().upper(),
            "design_id": str(row.get("報價款號", "") or "").strip(),
            "season": str(row.get("Season", "") or "").strip(),
            "gender_excel": gender,
        }
    return out


def load_recipes():
    """讀 recipes_master_v6.jsonl → list of recipes"""
    if not RECIPES.exists():
        print(f"[!] {RECIPES} not found")
        return []
    out = []
    for line in open(RECIPES, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def index_recipes(recipes):
    """建 (gender, dept, gt, it, wk, l1) → recipe lookup
    主索引：完整 6-dim key
    fallback 索引：(gender, gt, l1) 跨 dept/it/wk
    """
    by_key = {}
    by_loose = defaultdict(list)
    for r in recipes:
        k = r.get("key", {})
        full = (k.get("gender"), k.get("dept"), k.get("gt"), k.get("it"), k.get("wk"), k.get("l1"))
        by_key[full] = r
        loose = (k.get("gender"), k.get("gt"), k.get("l1"))
        by_loose[loose].append(r)
    return by_key, by_loose


# ════════════════════════════════════════════════════════════
# Bible image link helpers
# ════════════════════════════════════════════════════════════

def bible_code_to_unc(code: str, variant: str = "001") -> str:
    """WB_002_a01 → \\\\192.168.1.39\\mtm\\Images\\FiveLevel_MethodDescribe\\WB_002_a01_001.png"""
    if not code:
        return ""
    return f"\\\\192.168.1.39\\mtm\\Images\\FiveLevel_MethodDescribe\\{code}_{variant}.png"


def bible_code_to_file_url(code: str, variant: str = "001") -> str:
    """轉成 file:// URL（瀏覽器可能能開）"""
    if not code:
        return ""
    return f"file:////192.168.1.39/mtm/Images/FiveLevel_MethodDescribe/{code}_{variant}.png"


# ════════════════════════════════════════════════════════════
# HTML rendering
# ════════════════════════════════════════════════════════════

def encode_image_base64(path: Path, max_side: int = 800) -> str:
    """讀圖片 + 縮圖 + base64 encode 給 HTML 內嵌用"""
    try:
        from PIL import Image
        import io
        with Image.open(path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.size) > max_side:
                img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            data = base64.standard_b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{data}"
    except Exception as e:
        return ""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Sketch → IE Recipe Demo: {title}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif;
       max-width: 1400px; margin: 0 auto; padding: 20px; color: #222; }}
h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 10px; }}
h2 {{ color: #2563eb; margin-top: 32px; }}
h3 {{ color: #555; }}
.header {{ display: flex; gap: 30px; margin-bottom: 30px; }}
.sketch-img {{ flex: 0 0 400px; }}
.sketch-img img {{ width: 100%; border: 1px solid #ddd; border-radius: 8px; }}
.metadata-box {{ flex: 1; background: #f9fafb; padding: 20px; border-radius: 8px; }}
.metadata-box table {{ width: 100%; }}
.metadata-box td {{ padding: 4px 0; }}
.metadata-box td:first-child {{ font-weight: bold; color: #555; width: 35%; }}
.l1-card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 20px; margin-bottom: 20px; }}
.l1-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }}
.l1-code {{ font-size: 24px; font-weight: bold; color: #2563eb; }}
.confidence-high {{ background: #d1fae5; color: #047857; padding: 3px 10px; border-radius: 4px; font-size: 12px; }}
.confidence-medium {{ background: #fef3c7; color: #92400e; padding: 3px 10px; border-radius: 4px; font-size: 12px; }}
.confidence-low {{ background: #fee2e2; color: #991b1b; padding: 3px 10px; border-radius: 4px; font-size: 12px; }}
.vlm-section {{ background: #eff6ff; padding: 12px; border-radius: 6px; margin-bottom: 12px; }}
.recipe-section {{ background: #f0fdf4; padding: 12px; border-radius: 6px; }}
.recipe-section.no-match {{ background: #fef2f2; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #f3f4f6; }}
th {{ background: #f9fafb; }}
.bible-img {{ display: inline-block; margin-right: 10px; padding: 4px;
             background: #f9fafb; border-radius: 4px; font-size: 11px; color: #6b7280; }}
.bible-img code {{ font-family: 'Courier New', monospace; }}
.iso-bar {{ display: inline-block; height: 14px; background: #2563eb;
           border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
.method-list {{ list-style: none; padding-left: 0; }}
.method-list li {{ padding: 3px 0; }}
.client-tag {{ display: inline-block; background: #f3f4f6; padding: 2px 8px;
              border-radius: 12px; margin: 2px; font-size: 12px; }}
.summary-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
.stat-box {{ background: #f9fafb; padding: 15px; border-radius: 8px; text-align: center; }}
.stat-num {{ font-size: 28px; font-weight: bold; color: #2563eb; }}
.stat-label {{ font-size: 12px; color: #6b7280; }}
.flag {{ display: inline-block; padding: 2px 6px; border-radius: 3px;
        font-size: 11px; margin-left: 6px; }}
.flag-bible {{ background: #d1fae5; color: #065f46; }}
.flag-no-bible {{ background: #fee2e2; color: #991b1b; }}
</style>
</head>
<body>

<h1>Sketch → IE Recipe Demo</h1>

<div class="header">
  <div class="sketch-img">
    {sketch_img_html}
  </div>
  <div class="metadata-box">
    <h3>📋 Sketch Metadata</h3>
    <table>
      <tr><td>EIDH</td><td>{eidh}</td></tr>
      <tr><td>Client</td><td>{client}</td></tr>
      <tr><td>Design ID</td><td>{design_id}</td></tr>
      <tr><td>Item</td><td>{item}</td></tr>
      <tr><td>Subgroup</td><td>{subgroup}</td></tr>
      <tr><td>Program</td><td>{program}</td></tr>
      <tr><td>Season</td><td>{season}</td></tr>
    </table>
    <h3 style="margin-top: 20px;">🧬 6-dim Recipe Key</h3>
    <table>
      <tr><td>Gender</td><td><b>{gender}</b></td></tr>
      <tr><td>Dept</td><td><b>{dept}</b></td></tr>
      <tr><td>GT</td><td>BOTTOM</td></tr>
      <tr><td>Item Type</td><td><b>{it}</b></td></tr>
      <tr><td>W/K</td><td><b>{wk}</b></td></tr>
    </table>
    <h3 style="margin-top: 20px;">🤖 VLM Garment Overall</h3>
    <p>{garment_overall}</p>
    <p style="font-size: 12px; color: #6b7280;">Image quality: {image_quality}</p>
  </div>
</div>

<div class="summary-stats">
  <div class="stat-box">
    <div class="stat-num">{n_l1}</div>
    <div class="stat-label">L1 偵測到</div>
  </div>
  <div class="stat-box">
    <div class="stat-num">{n_l2}</div>
    <div class="stat-label">L2/L3 候選</div>
  </div>
  <div class="stat-box">
    <div class="stat-num">{n_with_recipe}</div>
    <div class="stat-label">L1 有 recipe</div>
  </div>
  <div class="stat-box">
    <div class="stat-num">{n_with_bible}</div>
    <div class="stat-label">L3 有 bible 圖</div>
  </div>
</div>

<h2>📍 偵測 L1 部位 + 對應 IE 字典</h2>

{l1_cards_html}

<hr style="margin: 40px 0;">
<p style="text-align: center; color: #6b7280; font-size: 12px;">
  生成 by demo_sketch_to_recipe.py | recipes_master_v6.4 | sketch_l1_poc v6.1<br>
  Bible 圖路徑：\\\\192.168.1.39\\mtm\\Images\\FiveLevel_MethodDescribe\\
</p>

</body>
</html>
"""


def render_l1_card(l1_part: dict, recipe: dict | None, by_loose: dict, key: tuple) -> str:
    """render 一個 L1 card"""
    code = l1_part.get("code", "?")
    zh = l1_part.get("zh", "")
    en = l1_part.get("en", "")
    confidence = l1_part.get("confidence", "low")
    visual_desc = l1_part.get("visual_description", "")
    cands = l1_part.get("l2_l3_candidates", [])
    if not cands and (l1_part.get("l2") or l1_part.get("l3")):
        cands = [{"l2": l1_part.get("l2", ""), "l3": l1_part.get("l3", ""),
                  "bible_code": l1_part.get("bible_code", ""),
                  "l3_confidence": l1_part.get("l3_confidence", "low")}]

    # VLM section: l2_l3_candidates
    candidates_rows = []
    for c in cands:
        l2 = c.get("l2", "")
        l3 = c.get("l3", "")
        bcode = c.get("bible_code", "")
        l3_conf = c.get("l3_confidence", "low")
        bible_link = ""
        if bcode:
            unc = bible_code_to_unc(bcode)
            bible_link = f'<code>{bcode}</code> <span class="flag flag-bible">🖼️ bible</span>'
        else:
            bible_link = '<span class="flag flag-no-bible">🚫 no img</span>'
        candidates_rows.append(
            f"<tr><td>{l2}</td><td>{l3}</td><td>{bible_link}</td>"
            f'<td><span class="confidence-{l3_conf}">{l3_conf}</span></td></tr>'
        )

    vlm_html = f"""
    <div class="vlm-section">
      <b>🤖 VLM 視覺描述：</b> {visual_desc}
      <table style="margin-top: 10px;">
        <tr><th>L2 零件</th><th>L3 形狀設計</th><th>Bible Code</th><th>L3 信心</th></tr>
        {"".join(candidates_rows)}
      </table>
    </div>
    """

    # Recipe section: 從 recipes_master 拿做工資料
    if recipe:
        # ISO distribution top 5
        iso_dist = recipe.get("iso_distribution", [])[:5]
        iso_html = ""
        for iso in iso_dist:
            pct = iso.get("pct", 0)
            iso_html += (f'<span class="iso-bar" style="width: {pct*1.5:.0f}px;"></span>'
                        f'<b>ISO {iso.get("iso")}</b> ({pct}%) &nbsp;')

        # methods top 5
        methods = recipe.get("methods", [])[:5]
        methods_html = "<ul class='method-list'>"
        for m in methods:
            methods_html += f"<li>• {m.get('name', '?')} <span style='color:#6b7280;'>({m.get('pct', 0)}%)</span></li>"
        methods_html += "</ul>"

        # client distribution top 5
        clients = recipe.get("client_distribution", [])[:5]
        clients_html = ""
        for c in clients:
            clients_html += f'<span class="client-tag">{c.get("client", "?")} ({c.get("pct", 0)}%)</span>'

        # 工時：total_avg_seconds 才是真實秒值；ie_avg_seconds 是 IE 額定值（內部單位）
        total_avg = recipe.get("total_avg_seconds")
        ie_avg = recipe.get("ie_avg_seconds")
        ie_med = recipe.get("ie_median_seconds")
        ie_str_parts = []
        if total_avg:
            ie_str_parts.append(f"<b>實際工序時間</b>: 平均 <b>{total_avg}s</b>")
        if ie_avg:
            ie_str_parts.append(f"<span style='color:#6b7280;'>IE 額定值: avg {ie_avg} | median {ie_med}（IE 部門內部單位，非秒）</span>")
        ie_str = "<br>".join(ie_str_parts) if ie_str_parts else "（無工時資料）"

        # five_tier chains
        chains = recipe.get("five_tier", {}).get("chains", [])[:5]
        chains_html = ""
        for ch in chains:
            l2 = ch.get("L2", "")
            l3 = ch.get("L3", "")
            pct = ch.get("pct", 0)
            in_b = ch.get("in_bible")
            img = ch.get("bible_image")
            mark = "✓🖼️" if (in_b and img) else "✓" if in_b else "?"
            chains_html += (f"<tr><td>{mark}</td><td>{l2}</td><td>{l3}</td>"
                          f"<td>{pct}%</td><td>{ch.get('n', 0)}</td></tr>")

        # confidence + n_total
        conf = recipe.get("confidence", "?")
        n_total = recipe.get("n_total", 0)
        n_designs = recipe.get("n_designs", 0)
        n_clients = recipe.get("n_clients", 0)

        recipe_html = f"""
        <div class="recipe-section">
          <h3>📚 IE 字典查詢結果（recipe.confidence = <span class="confidence-{conf}">{conf}</span>）</h3>
          <p>共識基礎：<b>{n_total}</b> steps / <b>{n_designs}</b> designs / <b>{n_clients}</b> clients</p>

          <h4>🧵 ISO 分布（top 5）</h4>
          <p>{iso_html}</p>

          <h4>🔧 主流方法（top 5）</h4>
          {methods_html}

          <h4>⏱️ IE 工時</h4>
          <p>{ie_str}</p>

          <h4>🏢 客戶分布</h4>
          <p>{clients_html}</p>

          <h4>🔗 Top L2+L3 chains（從 m7 真實資料 + bible 對齊）</h4>
          <table>
            <tr><th></th><th>L2 零件</th><th>L3 形狀</th><th>%</th><th>n steps</th></tr>
            {chains_html}
          </table>
        </div>
        """
    else:
        # 沒對應 recipe → 試 loose match (只 gender+gt+l1)
        loose_key = (key[0], key[2], key[5])
        loose_recipes = by_loose.get(loose_key, [])
        if loose_recipes:
            recipe_html = f"""
            <div class="recipe-section no-match">
              <h3>⚠️ 完整 6-dim 沒對應 recipe，但有 {len(loose_recipes)} 個 loose match
                  (同 gender/gt/l1，不同 dept/it/wk)</h3>
            </div>
            """
        else:
            recipe_html = """
            <div class="recipe-section no-match">
              <h3>❌ 此 L1 在 v6.4 字典無對應 recipe</h3>
            </div>
            """

    return f"""
    <div class="l1-card">
      <div class="l1-header">
        <div>
          <span class="l1-code">{code}</span>
          <span style="font-size: 16px; color: #555;"> {zh} / {en}</span>
        </div>
        <span class="confidence-{confidence}">VLM 信心: {confidence}</span>
      </div>
      {vlm_html}
      {recipe_html}
    </div>
    """


def render_report(sketch_stem: str, sketch_data: dict, m7_meta: dict | None,
                  recipes_by_key: dict, recipes_by_loose: dict) -> str:
    """組 HTML 報告"""
    # Sketch image
    sketch_files = list(SKETCHES_DIR.glob(f"{sketch_stem}.*"))
    if sketch_files:
        img_data_url = encode_image_base64(sketch_files[0])
        sketch_img_html = f'<img src="{img_data_url}" alt="sketch">'
    else:
        sketch_img_html = "<p>(sketch image not found)</p>"

    # Metadata
    meta = sketch_data.get("metadata", {})
    eidh = meta.get("eidh", "?")
    client = meta.get("client_raw", "?").replace("_", " ")
    design_id = meta.get("design_id", "?")

    # 6-dim key
    if m7_meta:
        gender = m7_meta.get("gender_excel", "UNKNOWN")
        wk = m7_meta.get("wk", "UNKNOWN")
        item = m7_meta.get("item", "")
        program = m7_meta.get("program", "")
        subgroup = m7_meta.get("subgroup", "")
        season = m7_meta.get("season", "")
        it = derive_item_type(design_id, program, item)
    else:
        gender = wk = it = "UNKNOWN"
        item = program = subgroup = season = ""

    # derive dept (簡單版：從 client/program 猜)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from derive_metadata import derive_dept  # type: ignore
        dept = derive_dept(client.upper(), program, subgroup) or "UNKNOWN"
    except Exception:
        dept = "UNKNOWN"

    # VLM 結果
    vision = sketch_data.get("vision_result", {})
    l1_parts = vision.get("l1_parts", [])
    garment_overall = vision.get("garment_overall", "(no description)")
    image_quality = vision.get("image_quality", "?")

    # 對每個 L1，找對應 recipe
    n_with_recipe = 0
    n_with_bible = 0
    n_l2 = 0
    l1_cards = []
    for p in l1_parts:
        l1_code = p.get("code", "")
        full_key = (gender, dept, "BOTTOM", it, wk, l1_code)
        recipe = recipes_by_key.get(full_key)
        if recipe:
            n_with_recipe += 1
        cands = p.get("l2_l3_candidates", [])
        if not cands and (p.get("l2") or p.get("l3")):
            cands = [{"l2": p.get("l2", ""), "l3": p.get("l3", ""),
                      "bible_code": p.get("bible_code", "")}]
        n_l2 += len(cands)
        n_with_bible += sum(1 for c in cands if c.get("bible_code"))
        l1_cards.append(render_l1_card(p, recipe, recipes_by_loose, full_key))

    # 組 HTML
    html = HTML_TEMPLATE.format(
        title=sketch_stem,
        sketch_img_html=sketch_img_html,
        eidh=eidh,
        client=client,
        design_id=design_id,
        item=item,
        subgroup=subgroup,
        program=program,
        season=season,
        gender=gender,
        dept=dept,
        it=it,
        wk=wk,
        garment_overall=garment_overall,
        image_quality=image_quality,
        n_l1=len(l1_parts),
        n_l2=n_l2,
        n_with_recipe=n_with_recipe,
        n_with_bible=n_with_bible,
        l1_cards_html="".join(l1_cards),
    )
    return html


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sketch_stem", nargs="?", help="sketch stem (e.g. 306187_10406545_BEYOND_YOGA_SD1262)")
    p.add_argument("--all", action="store_true", help="跑所有 outputs/sketch_l1_poc/*.json")
    args = p.parse_args()

    print("[1] Load M7 metadata index")
    m7_meta_idx = load_m7_metadata()
    print(f"    {len(m7_meta_idx)} EIDH metadata")

    print("[2] Load recipes_master_v6.jsonl")
    recipes = load_recipes()
    print(f"    {len(recipes)} recipes")

    by_key, by_loose = index_recipes(recipes)
    print(f"    {len(by_key)} 6-dim keys / {len(by_loose)} loose keys")

    # 收 sketch json
    if args.all:
        sketch_jsons = sorted(SKETCH_POC_DIR.glob("*.json"))
    elif args.sketch_stem:
        sketch_jsons = [SKETCH_POC_DIR / f"{args.sketch_stem}.json"]
    else:
        print("[!] 請指定 sketch_stem 或 --all")
        sys.exit(1)

    print(f"\n[3] 處理 {len(sketch_jsons)} 個 sketch")
    n_ok = n_err = 0
    for sketch_json in sketch_jsons:
        if not sketch_json.exists():
            print(f"  [skip] {sketch_json.name} not found")
            continue
        stem = sketch_json.stem
        try:
            sketch_data = json.load(open(sketch_json, encoding="utf-8"))
            eidh = sketch_data.get("metadata", {}).get("eidh", "")
            m7_meta = m7_meta_idx.get(str(eidh))
            html = render_report(stem, sketch_data, m7_meta, by_key, by_loose)
            out_path = OUT_DIR / f"{stem}.html"
            out_path.write_text(html, encoding="utf-8")
            print(f"  [ok] {stem}")
            n_ok += 1
        except Exception as e:
            print(f"  [err] {stem}: {e}")
            n_err += 1

    print(f"\n[done] {n_ok} ok / {n_err} err")
    print(f"[output] {OUT_DIR}/")
    if n_ok == 1:
        print(f"\n開報告：")
        print(f'  Start-Process "{OUT_DIR / (sketch_jsons[0].stem + ".html")}"')


if __name__ == "__main__":
    main()
