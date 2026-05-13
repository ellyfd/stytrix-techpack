"""sketch_to_l1_poc.py — Sketch → L1 部位識別 PoC

對 m7_organized_v2/sketches/ 的草圖做 multi-label L1 部位識別。
每張 sketch 是「整件褲子草圖」，會包含多個 L1 部位（腰頭+口袋+褲合身+...）。

需要環境變數：ANTHROPIC_API_KEY

流程：
  1. 載入 38 個 L1 spec（zone_glossary）
  2. 對每張 sketch：
     - base64 encode
     - Claude Vision API (Sonnet 4.5)
     - prompt: 列出可見的 L1 部位 + 信心 + 視覺描述
  3. 輸出 outputs/sketch_l1_poc/{stem}.json
  4. 產出 summary report（含 spot-check 結果）

成本：5 張 ~$0.05 / 1174 張 ~$10

用法：
  $env:ANTHROPIC_API_KEY="sk-ant-..."
  python scripts\\sketch_to_l1_poc.py --limit 5
  python scripts\\sketch_to_l1_poc.py --limit 5 --client TARGET
  python scripts\\sketch_to_l1_poc.py --all          # 跑全部 1174 張
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCHES = ROOT / "m7_organized_v2" / "sketches"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
L1_DEFINITIONS = ROOT / "data" / "l1_sketch_definitions.md"  # v2: 38 L1 完整視覺指引
L1_L2_PATTERNS = ROOT / "data" / "pullon_l1_l2_visual_patterns.md"  # v5: 從五階反推 L2 patterns
L1_L2_L3_PATTERNS = ROOT / "data" / "pullon_l1_l2_l3_patterns.md"  # v6: 加 L3 形狀變體（含 bible 圖片 code）
OUT_DIR = ROOT / "outputs" / "sketch_l1_poc"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════
# L1 spec — 38 個部位
# ════════════════════════════════════════════════════════════
L1_EN = {
    "AE": "Armhole", "AH": "Sleeve Body", "BM": "Bottom Hem",
    "BN": "Bonded", "BP": "Hem Slit", "BS": "Buttonhole",
    "DC": "Drawcord", "DP": "Decoration", "FP": "Pocket Flap",
    "FY": "Front Placket", "HD": "Hood", "HL": "Loop",
    "KH": "Keyhole", "LB": "Label", "LI": "Lining",
    "LO": "Leg Opening", "LP": "Belt Loop", "NK": "Neck",
    "NP": "Collar", "NT": "Neck Binding", "OT": "Other",
    "PD": "Pleat", "PK": "Pocket", "PL": "Fly",
    "PS": "Pants Body", "QT": "Quilting", "RS": "Crotch Rise",
    "SA": "Top Panel Seam", "SB": "Bottom Panel Seam", "SH": "Shoulder",
    "SL": "Sleeve Cuff", "SP": "Sleeve Slit", "SR": "Skirt Body",
    "SS": "Side Seam", "ST": "Strap", "TH": "Thumbhole",
    "WB": "Waistband", "ZP": "Zipper",
}


def load_l1_zh():
    try:
        g = json.load(open(ZONE_GLOSSARY, encoding="utf-8"))
        return g.get("L1_STANDARD_38", {})
    except Exception:
        return {}


L1_ZH = load_l1_zh()


# Pull-On Pants 主要會出現的 L1（38 個中 PullOn 相關）
PULLON_L1S = ["WB", "PS", "RS", "SS", "LO", "PK", "PL", "FP", "DC", "LP",
              "BP", "PD", "SB", "LB", "LI", "OT"]


def load_l1_definitions() -> str:
    """載入 38 L1 完整視覺指引（含↔對比規則）給 VLM 當 domain knowledge"""
    if not L1_DEFINITIONS.exists():
        return ""
    try:
        return L1_DEFINITIONS.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_l1_l2_patterns() -> str:
    """v5: 載入從五階反推的 L2 視覺特徵庫（PullOn-specific）

    這是 prompt engineering 的核心：VLM 不再判抽象 L1，而是判具體 L2 patterns。
    看到任一 L2 pattern → 列對應 L1；看不到 → 不列。
    """
    if not L1_L2_PATTERNS.exists():
        return ""
    try:
        return L1_L2_PATTERNS.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_l1_l2_l3_patterns() -> str:
    """v6: 載入從五階反推的 L3 形狀變體庫（PullOn-specific，含 bible image code）

    257 個 L3 patterns，98% 有 bible 圖片連結。
    VLM 偵測到 L1+L2 後，要進一步識別 L3 形狀變體並回傳 bible code（如 WB_002_a01）。
    """
    if not L1_L2_L3_PATTERNS.exists():
        return ""
    try:
        return L1_L2_L3_PATTERNS.read_text(encoding="utf-8")
    except Exception:
        return ""


def build_l1_list_for_prompt():
    """產生 L1 spec list 給 prompt 用（簡短版，做備用）"""
    lines = []
    for code, en in sorted(L1_EN.items()):
        zh = L1_ZH.get(code, "")
        lines.append(f"  - {code} | {zh} | {en}")
    return "\n".join(lines)


# v5 升級：從五階反推 L2 視覺特徵庫 + L1 Sketch 視覺指引
# 雙層 domain knowledge：
#   1. L1_DEFINITIONS（38 L1 sketch 視覺定義）
#   2. L1_L2_PATTERNS（PullOn-specific L2 視覺 pattern，從 m7 1180 真實統計反推）
VISION_PROMPT = """你是聚陽（Makalot）IE 部門的服裝草圖 multi-label 部位辨識系統。

# 任務
分析這張褲子（pull-on pants）草圖，找出圖中**可見**的所有 L1 部位（zone）。

這是 **multi-label classification**——一張整件褲子的 sketch 會包含多個 L1 部位
（腰頭+口袋+褲合身+褲口+...全部）。

# ★ 判斷方式：用具體 L2 pattern 反推 L1（不是直接判 L1）

VLM 容易在抽象 L1 上 hallucinate（例如把鬆緊紋當抽繩、把假前立當門襟）。
正確判斷流程是：

```
For each candidate L1:
    1. 看下方「PullOn L2 視覺特徵庫」對應的 L2 pattern
    2. 我能在 sketch 上識別出任一具體 L2 pattern 嗎？
    3. YES → 列這個 L1，並在 visual_description 寫出**識別到的 L2 名稱**
    4. NO → 不要列這個 L1
```

# === PullOn L2 視覺特徵庫（從 m7 1180 真實統計反推）===

{l1_l2_patterns}

# === PullOn L3 形狀變體庫（含 bible 圖片 code）===

下面是每個 L1+L2 對應的 L3 形狀變體。每個 L3 都有對應的 bible 圖片 code（如 WB_002_a01）。
VLM 偵測到 L1+L2 後，請進一步識別 L3 變體並在 visual_description 寫出 L3 名稱 + bible_code。

{l1_l2_l3_patterns}

# === 38 L1 完整 Sketch 視覺定義（補充）===

{l1_definitions}

---

# Evidence-based 輸出規則（嚴格）

**核心原則：只列「圖上實際看到視覺證據」的 L1。沒看到的不要列；看到了一定要列。**

兩個失敗模式都要避免：
- ❌ 看到 PullOn 就自動補「常見 L1 list」（false positive）
- ❌ 看到了視覺特徵卻沒列出（false negative）

對每個 L1 都回答：「我在圖上具體看到什麼證據？」如果答不出具體證據，**該 L1 就不列**。
但如果有視覺證據，**一定要列**——不要因為「不確定要不要算 L1」就跳過。

## ★ Visual Cue Checklist — 看到這些就要列 ★

### 結構必掃（PullOn 一定有，但要看到才列）
- **WB 腰頭** ← 腰部明顯橫向結構帶（剪接線 / 反折線 / 羅紋區 / 鬆緊皺褶紋）
- **PS 褲合身** ← 從腰到褲口的**縱向結構縫線**（外側線 outseam / 內側線 inseam）
- **LO 褲口** ← 褲腳邊緣的**收邊處理**（反折 / 羅紋 / 克夫 / 毛邊 / 鬆緊）

### 設計細節（看到必列，不要漏）
- **PK 口袋** ← 看到口袋輪廓 / 袋口開口 / 口袋邊線
- **SB 剪接線_下身類** ← **重要！** 褲子表面除了基本結構縫之外的**設計性剪接線**：
  - 膝蓋線、大腿線、側邊剪接、中線剪接、斜向剪接、色塊拼接、弧形剪接
  - **看到任何「不是結構縫的多餘線條」就是 SB** ← 別漏這個
- **PD 褶** ← 看到布料聚攏紋路 / 立體褶紋 / Pintuck 平行細線 / 抽褶皺紋
  - **包括鬆緊腰頭聚攏的皺褶**（這是 PD 不是 DC）
- **DC 繩類** ← ⚠️ **必須看到繩頭（cord ends）或穿繩孔（eyelet/grommet）才算**
  - **純鬆緊腰皺褶沒有繩頭/孔 → 是 PD 不是 DC**
  - **剪接腰頭含繩**：要看到繩頭從腰頭穿出才能列
- **LP 帶絆** ← 腰頭周圍等距的**小布環**（belt loops，1-2 cm 寬）
- **BS 釦鎖** ← 看到釦子 / 鉚釘 / G 眼 / 暗釦 / 魔鬼氈
- **ZP 拉鍊** ← 看到拉鍊齒紋（露齒）或拉鍊頭
- **BP 襬叉** ← 褲口側邊有**開叉**（直線/倒 V / 露齒拉鍊叉 + 反光條）
- **BN 貼合** ← 兩層布料黏合無車線（sketch 上幾乎不可見，極少需列）

### Sketch 通常看不見的（PullOn）
- **LB 商標** ← 多在後領內側 / 腰頭內側，sketch 通常看不見 → 沒看到就不列
- **LI 裡布** ← 內裡，sketch 看不見 → 不列
- **OT 其它** ← 雜項做工 → 不列
- **NT 領貼條** ← 內側貼條 → 不列

## ↔ 嚴格 disambiguation

- **DC vs PD**：有繩頭/孔 = DC；只有鬆緊聚攏紋路 = PD
- **PS vs RS vs SS**：IE 規則統一歸 **PS**（除非有獨立襠底片，否則不要列 RS/SS）
- **BM vs LO**：BM 上衣底邊 / LO 褲腳底邊 → PullOn 永遠 **LO**，不是 BM
- **SA vs SB**：SA 上身 / SB 下身 → PullOn 永遠 **SB**，不是 SA
- **PL vs ZP**：褲前門襟結構 = PL；只看拉鍊齒 = ZP（PullOn 一般沒 PL）
- **AE/AH/SH/SL/NK/NP/HD/TH**：都屬上衣 → PullOn sketch **不該出現**

## ⚠️ 不要做的事

1. ❌ 因為「PullOn 通常有 X」就列 X（沒看到不列）
2. ❌ 把 PS 重複拆成 RS/SS（除非真有襠底片）
3. ❌ 把鬆緊腰皺褶當成 DC 抽繩
4. ❌ LB/LI/OT/BN 等 sketch 看不見的就不要憑空猜

## ✅ 該主動列的

5. ✅ 看到設計性剪接線（非結構縫）→ 列 SB（最常被漏掉）
6. ✅ 看到下擺荷葉/波浪/弧線 → 列 BM（如果是上衣）或對應部位
7. ✅ 看到褶紋線條 → 列 PD（不是 DC）
8. ✅ 看到拉鍊叉 / 開叉 → 列 BP

如果圖只是 logo / 縮圖 / 不是褲子草圖，回 `{{"error": "not_a_garment_sketch"}}`

# 輸出 JSON 格式（v6.1 nested L2/L3）

每個 L1 **只列一次**，多個 L2/L3 候選放在 `l2_l3_candidates` array 裡。
例如 PS 褲合身可能同時看到「合外長 + 合內長 + 合後襠」三個 L2 → 全放在同一個 PS entry 的 array。

{{
  "l1_parts": [
    {{
      "code": "WB",
      "zh": "腰頭",
      "en": "Waistband",
      "confidence": "high",
      "visual_description": "看到腰部有獨立剪接帶 + 整圈鬆緊帶皺褶",
      "l2_l3_candidates": [
        {{
          "l2": "剪接腰頭_整圈",
          "l3": "整圈鬆緊帶_腰頭固雙",
          "bible_code": "WB_002_a01",
          "l3_confidence": "medium"
        }}
      ]
    }},
    {{
      "code": "PS",
      "zh": "褲合身",
      "en": "Pants Seam",
      "confidence": "high",
      "visual_description": "可見外側線+內側線+後襠縫線",
      "l2_l3_candidates": [
        {{"l2": "合外長", "l3": "合外長", "bible_code": "PS_001_a01", "l3_confidence": "high"}},
        {{"l2": "合內長_一起", "l3": "合內長", "bible_code": "PS_003_a01", "l3_confidence": "high"}},
        {{"l2": "合後襠", "l3": "合後襠", "bible_code": "PS_005_a01", "l3_confidence": "high"}}
      ]
    }},
    {{
      "code": "PK",
      "zh": "口袋",
      "en": "Pocket",
      "confidence": "high",
      "visual_description": "看到雙側斜線開口",
      "l2_l3_candidates": [
        {{"l2": "斜插袋", "l3": "袋口", "bible_code": "PK_007_a01", "l3_confidence": "medium"}}
      ]
    }}
  ],
  "garment_overall": "對整件褲子的描述",
  "image_quality": "good / partial / unclear"
}}

## 規則

1. **同一個 L1 code 只能在 l1_parts 裡出現一次** — 多個 L2 放 l2_l3_candidates array
2. **每個 L1 至少有 1 個 l2_l3_candidate** — 從 PullOn L2 patterns 找最匹配的
3. **L3 + bible_code 是 best-effort** — 不確定就 l3_confidence=low，bible_code 留空字串
4. **bible_code 必須來自 L3 patterns 列表中的 [XX_NNN_aNN] 格式** — 不要憑空捏造
5. confidence / l3_confidence 分 high / medium / low 3 級

只回純 JSON，不要 markdown wrapper 不要任何說明文字。"""


MODEL_MAP = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


def encode_image(path: Path) -> tuple[str, str]:
    """讀檔並 normalize（RGB / resize / re-encode JPEG）

    Centric 8 / Photoshop 出來的 sketch 可能是 CMYK 或 Progressive JPEG，
    Anthropic API 會拒絕。這裡用 PIL 統一轉成標準 baseline RGB JPEG。

    回 (base64_data, media_type)
    """
    try:
        from PIL import Image
        import io
    except ImportError:
        # Fallback：沒有 PIL 直接讀（會在 CMYK/progressive jpeg 失敗）
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "jpg":
            suffix = "jpeg"
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return data, f"image/{suffix}"

    with Image.open(path) as img:
        # 強制 RGB（處理 CMYK / RGBA / palette）
        if img.mode != "RGB":
            img = img.convert("RGB")
        # 縮圖到長邊 ≤ 1568 px（Anthropic 建議上限）
        MAX_SIDE = 1568
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        # 重新存成 baseline RGB JPEG（殺 progressive / 怪 colorspace）
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return data, "image/jpeg"


def parse_filename(name: str) -> dict:
    """從檔名抽 metadata
    例：306268_10406410_ATHLETA_D67439.jpg
    → {"eidh": "306268", "design_seq": "10406410", "client": "ATHLETA", "design_id": "D67439"}
    """
    stem = Path(name).stem
    parts = stem.split("_")
    if len(parts) < 4:
        return {"raw_name": stem}
    return {
        "eidh": parts[0],
        "design_seq": parts[1],
        # client 可能多字（OLD_NAVY / DICKS_SPORTING_GOODS）→ 試 known clients
        "client_raw": "_".join(parts[2:-1]) if len(parts) > 4 else parts[2],
        "design_id": parts[-1],
        "raw_name": stem,
    }


def call_vision(client, model: str, image_path: Path, prompt: str):
    """呼 Anthropic Vision API"""
    data, media_type = encode_image(image_path)
    msg = client.messages.create(
        model=model,
        max_tokens=4000,  # 9 L1 + visual_description 可能超 2000
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": data,
                }},
                {"type": "text", "text": prompt},
            ]
        }]
    )
    txt = msg.content[0].text.strip()
    # 砍 markdown wrap
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if txt.startswith("json"):
            txt = txt[4:].strip()
    try:
        return json.loads(txt) if txt else {}
    except json.JSONDecodeError as e:
        return {"error": f"json_parse_fail: {e}", "raw": txt[:300]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5, help="跑前 N 張（default 5）")
    p.add_argument("--all", action="store_true", help="跑全部 1174 張")
    p.add_argument("--client", default=None, help="只跑某客戶（如 TARGET, OLD_NAVY）")
    p.add_argument("--model", choices=list(MODEL_MAP.keys()), default="sonnet")
    p.add_argument("--skip-existing", action="store_true",
                   help="跳過已有 output 的 sketch")
    p.add_argument("--min-size", type=int, default=20000,
                   help="只跑檔案大小 > N bytes 的（避免縮圖；default 20KB）")
    args = p.parse_args()

    # API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY 未設定")
        print("    PowerShell:  $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print("[!] anthropic 未安裝。pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    model = MODEL_MAP[args.model]

    # 收集 sketches
    if not SKETCHES.exists():
        print(f"[!] sketches dir not found: {SKETCHES}")
        sys.exit(1)

    files = sorted(SKETCHES.iterdir())
    files = [f for f in files if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")]

    # filter 客戶
    if args.client:
        files = [f for f in files if args.client.upper() in f.name.upper()]
        print(f"[filter] 客戶 {args.client} → {len(files)} 張")

    # filter 大小（縮圖通常 < 15KB）
    files = [f for f in files if f.stat().st_size >= args.min_size]
    print(f"[filter] size >= {args.min_size//1000}KB → {len(files)} 張")

    # limit
    if not args.all:
        files = files[:args.limit]

    print(f"[run] 將處理 {len(files)} 張 sketch（model={args.model}）")
    print()

    # v6: 三層 domain knowledge
    #   1. L1_L2_PATTERNS（從五階反推的 PullOn L2 視覺特徵庫）
    #   2. L1_L2_L3_PATTERNS（PullOn L3 形狀變體 + bible 圖片 code）
    #   3. L1_DEFINITIONS（38 L1 sketch 視覺定義）
    l1_defs = load_l1_definitions()
    l1_l2_patterns = load_l1_l2_patterns()
    l1_l2_l3_patterns = load_l1_l2_l3_patterns()

    if not l1_defs:
        l1_defs = f"38 個 L1 簡列：\n{build_l1_list_for_prompt()}"
        print(f"[prompt] ⚠️ data/l1_sketch_definitions.md 不存在，用簡短版")
    if not l1_l2_patterns:
        l1_l2_patterns = "（尚未載入 PullOn L2 patterns）"
        print(f"[prompt] ⚠️ data/pullon_l1_l2_visual_patterns.md 不存在")
    if not l1_l2_l3_patterns:
        l1_l2_l3_patterns = "（尚未載入 PullOn L3 patterns - 跳過 L3 偵測）"
        print(f"[prompt] ⚠️ data/pullon_l1_l2_l3_patterns.md 不存在")

    prompt = VISION_PROMPT.format(
        l1_definitions=l1_defs,
        l1_l2_patterns=l1_l2_patterns,
        l1_l2_l3_patterns=l1_l2_l3_patterns,
    )
    print(f"[prompt] domain knowledge loaded:")
    print(f"  - L1 視覺指引       {len(l1_defs)} chars")
    print(f"  - PullOn L2 patterns {len(l1_l2_patterns)} chars")
    print(f"  - PullOn L3 patterns {len(l1_l2_l3_patterns)} chars")
    print(f"  total prompt size:    {len(prompt):,} chars")

    # 跑
    results = []
    n_ok = n_err = n_skip = 0
    t0 = time.time()

    for i, sketch in enumerate(files, 1):
        out_path = OUT_DIR / f"{sketch.stem}.json"
        if args.skip_existing and out_path.exists():
            n_skip += 1
            continue

        meta = parse_filename(sketch.name)
        size_kb = sketch.stat().st_size / 1024

        print(f"[{i}/{len(files)}] {sketch.name[:60]}  ({size_kb:.0f}KB)")

        try:
            result = call_vision(client, model, sketch, prompt)
            if "error" in result:
                print(f"    [err] {result.get('error', '?')}")
                n_err += 1
            else:
                l1s = result.get("l1_parts", [])
                codes = [p["code"] for p in l1s if "code" in p]
                quality = result.get("image_quality", "?")
                # v6.1: nested l2_l3_candidates 統計
                n_l2_total = 0
                n_l3_set = 0
                n_code_set = 0
                for p in l1s:
                    cands = p.get("l2_l3_candidates", [])
                    # 兼容 v6 flat schema
                    if not cands and (p.get("l2") or p.get("l3")):
                        cands = [{"l2": p.get("l2", ""), "l3": p.get("l3", ""),
                                  "bible_code": p.get("bible_code", "")}]
                    n_l2_total += len(cands)
                    n_l3_set += sum(1 for c in cands if c.get("l3"))
                    n_code_set += sum(1 for c in cands if c.get("bible_code"))
                print(f"    [ok] {len(l1s)} L1: {','.join(codes)}  | "
                      f"L2 cands={n_l2_total} | L3 set={n_l3_set} | bible_code set={n_code_set} | quality={quality}")
                n_ok += 1

            full = {
                "sketch_file": sketch.name,
                "metadata": meta,
                "model": args.model,
                "vision_result": result,
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(full, f, ensure_ascii=False, indent=2)
            results.append(full)
        except Exception as e:
            print(f"    [exception] {e}")
            n_err += 1

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print(f"SUMMARY  ({elapsed:.0f}s, ~${len(files)*0.01:.2f} cost @ Sonnet)")
    print(f"  ok:    {n_ok}")
    print(f"  err:   {n_err}")
    print(f"  skip:  {n_skip}")

    # L1 distribution（across all results）
    if results:
        from collections import Counter
        l1_cnt = Counter()
        for r in results:
            for p in r["vision_result"].get("l1_parts", []):
                code = p.get("code")
                if code:
                    l1_cnt[code] += 1
        print(f"\n  L1 出現頻率（在 {len(results)} 張 sketch 中）:")
        for code, n in l1_cnt.most_common():
            zh = L1_ZH.get(code, "")
            en = L1_EN.get(code, code)
            pct = round(n / len(results) * 100, 0)
            bar = "█" * int(pct / 5)
            print(f"    {code:3} {zh:6}/{en:18} {n:3}/{len(results)} ({pct:.0f}%) {bar}")

    print(f"\n[output] {OUT_DIR}/")
    print(f"  個別結果：{OUT_DIR}/{{sketch_stem}}.json")
    print(f"\n下一步 — 人工 spot check：")
    print(f"  1. 隨機開 3-5 張 sketch + 對應的 .json")
    print(f"  2. 對照 vision 識別的 L1 跟肉眼看到的對不對")
    print(f"  3. 若命中率 > 60% → 進階做 L2 細分")
    print(f"  4. 若命中率 < 40% → 改走 CLIP+FAISS 視覺相似度路線")


if __name__ == "__main__":
    main()
