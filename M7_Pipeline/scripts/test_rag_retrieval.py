"""test_rag_retrieval.py — RAG mock retrieval test for v6.2 recipes_master

目的：在不碰平台 pgvector / Murphy 的前提下，本機驗證 recipes_master_v6.jsonl
是否「結構上 retrievable」——確認 doc 構造、embedding text、key 維度都對。

策略：
  1. 載入 v6.2 recipes (470 筆)
  2. 為每筆 recipe 構出 RAG-friendly text doc
     （含 gender + dept + it + wk + l1_en + zone_zh + top_iso + top_method + top_clients）
  3. 用 sklearn TfidfVectorizer + cosine similarity 做 mock retrieval
     （TF-IDF 是 baseline，平台之後可換 sentence-transformers / OpenAI embedding）
  4. 跑 10 個 test query，看 top-5 命中
  5. 輸出 outputs/rag_test_report.md

用法：
  python scripts\\test_rag_retrieval.py

依賴：
  pip install scikit-learn  (一定要)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "outputs" / "platform" / "recipes_master_v6.jsonl"
OUT_REPORT = ROOT / "outputs" / "rag_test_report.md"
ZONE_GLOSSARY = ROOT / "data" / "zone_glossary.json"
ISO_DICT = ROOT / "data" / "iso_dictionary.json"


# ════════════════════════════════════════════════════════════
# L1 code → EN name（38 個 zone）
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


def load_recipes():
    recipes = []
    with open(RECIPES, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recipes.append(json.loads(line))
            except Exception as e:
                print(f"[skip bad line] {e}: {line[:60]}")
    return recipes


def build_doc(r) -> str:
    """為每筆 recipe 構出 RAG-friendly text doc

    優先用 v6.2.1 預先 build 好的 embedding_text；否則 fallback 到 inline 邏輯。
    """
    if r.get("embedding_text"):
        return r["embedding_text"]
    k = r["key"]
    parts = []

    # 維度（重複幾次強化權重）
    parts.append(f"{k['gender']} {k['gender']} ")
    parts.append(f"{k['dept']} dept ")
    parts.append(f"{k['it']} {k['it']} ")  # PANTS / SHORTS / LEGGINGS / JOGGERS
    parts.append(f"{k['wk']} fabric ")
    parts.append(f"{k['gt']} bottom ")

    # L1 zone EN + ZH
    l1 = k.get("l1", "")
    if l1:
        l1_en = L1_EN.get(l1, l1)
        parts.append(f"{l1_en} {l1_en} {l1} ")
    if r.get("category_zh"):
        parts.append(f"{r['category_zh']} ")

    # Top parts (ZH zones 細部)
    for p in (r.get("top_parts") or [])[:3]:
        parts.append(f"{p['name']} ")

    # Top ISOs
    for iso in (r.get("iso_distribution") or [])[:3]:
        parts.append(f"ISO{iso['iso']} ")

    # Top method names
    for m in (r.get("methods") or [])[:5]:
        parts.append(f"{m['name']} ")

    # Top clients (品牌名）
    for c in (r.get("client_distribution") or [])[:5]:
        parts.append(f"{c['client']} ")

    # Top machines (中文機種名)
    for m in (r.get("top_machines") or [])[:3]:
        parts.append(f"{m['name']} ")

    return " ".join(parts).strip()


# ════════════════════════════════════════════════════════════
# Test queries
# ════════════════════════════════════════════════════════════
TEST_QUERIES = [
    {
        "id": "Q1",
        "query": "Gap Women Active Knit Pants waistband construction",
        "expect": {"gender": "WOMEN", "dept": "ACTIVE", "it": "PANTS", "wk": "KNIT", "l1": "WB"},
        "expect_client": "GAP",
    },
    {
        "id": "Q2",
        "query": "Old Navy Boy Pants pocket coverstitch",
        "expect": {"gender": "BOY", "it": "PANTS", "l1": "PK"},
        "expect_client": "OLD NAVY",
    },
    {
        "id": "Q3",
        "query": "Target Women Shorts hem coverstitch ISO406",
        "expect": {"gender": "WOMEN", "it": "SHORTS"},
        "expect_client": "TARGET",
    },
    {
        "id": "Q4",
        "query": "Women Knit pull on pants waistband elastic",
        "expect": {"gender": "WOMEN", "wk": "KNIT", "l1": "WB", "it": "PANTS"},
        "expect_client": None,
    },
    {
        "id": "Q5",
        "query": "DICKS Sporting Goods Men Active Pants leg opening",
        "expect": {"gender": "MEN", "dept": "ACTIVE", "it": "PANTS", "l1": "LO"},
        "expect_client": "DICKS",
    },
    {
        "id": "Q6",
        "query": "Athleta Women Leggings panel seam flatlock",
        "expect": {"gender": "WOMEN", "it": "LEGGINGS"},
        "expect_client": "ATHLETA",
    },
    {
        "id": "Q7",
        "query": "Boy Joggers ankle cuff knit",
        "expect": {"gender": "BOY", "it": "JOGGERS", "wk": "KNIT"},
        "expect_client": None,
    },
    {
        "id": "Q8",
        "query": "Under Armour Pants crotch rise overlock",
        "expect": {"it": "PANTS", "l1": "RS"},
        "expect_client": "UNDER ARMOUR",
    },
    {
        "id": "Q9",
        "query": "Beyond Yoga Knit Pants 4-thread overlock",
        "expect": {"it": "PANTS", "wk": "KNIT"},
        "expect_client": "BEYOND YOGA",
    },
    {
        "id": "Q10",
        "query": "Kohls Women sleepwear pants drawcord",
        "expect": {"gender": "WOMEN", "it": "PANTS"},
        "expect_client": "KOHLS",
    },
]


def match_expect(recipe, expect: dict) -> bool:
    """Recipe key 是否符合 expect 條件"""
    k = recipe["key"]
    for field, val in expect.items():
        if k.get(field) != val:
            return False
    return True


def has_client(recipe, target_client: str) -> bool:
    """Recipe 的 client_distribution 是否包含 target client（fuzzy match）"""
    if not target_client:
        return True
    cd = recipe.get("client_distribution") or []
    target_up = target_client.upper()
    for c in cd:
        client_name = (c.get("client") or "").upper()
        if target_up in client_name or client_name in target_up:
            return True
    return False


def format_recipe_short(r) -> str:
    k = r["key"]
    top_iso = (r.get("iso_distribution") or [{}])[0]
    top_m = (r.get("methods") or [{}])[0]
    top_c = (r.get("client_distribution") or [{}])[0]
    return (
        f"{k['gender']:6}/{k['dept']:14}/{k['it']:8}/{k['wk']:5}/{k['l1']:3}"
        f" | conf={r.get('confidence', '?'):8}"
        f" | n_total={r.get('n_total', 0):4}"
        f" | top_iso={top_iso.get('iso', '-'):3}({top_iso.get('pct', 0):.0f}%)"
        f" | top_method={top_m.get('name', '-')[:25]:25}"
        f" | top_client={top_c.get('client', '-')[:18]}"
    )


def main():
    if not RECIPES.exists():
        print(f"[!] {RECIPES} not found. Run build_recipes_master_v6.py first.")
        sys.exit(1)

    print("[1] Load recipes_master_v6.jsonl")
    recipes = load_recipes()
    print(f"    {len(recipes)} recipes loaded")

    print("[2] Build text doc per recipe")
    docs = [build_doc(r) for r in recipes]
    print(f"    sample doc[0]: {docs[0][:200]}...")

    print("[3] TF-IDF vectorize (pure Python, no sklearn needed)")
    # Pure Python TF-IDF + cosine — 無 sklearn 依賴
    import math
    import re
    from collections import Counter

    def tokenize(text: str) -> list[str]:
        text_low = text.lower()
        # 抓英文詞 + 中文字（單字）+ 數字
        toks = re.findall(r"[a-z0-9]+|[一-鿿]", text_low)
        return toks

    # 1. tokenize 全部 docs
    doc_tokens = [tokenize(d) for d in docs]
    N = len(doc_tokens)

    # 2. doc frequency
    df = Counter()
    for toks in doc_tokens:
        for tok in set(toks):
            df[tok] += 1

    # 3. idf
    idf = {t: math.log((1 + N) / (1 + n)) + 1 for t, n in df.items()}

    # 4. tf-idf vector per doc + L2 norm
    def tfidf_vec(toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        vec = {t: (count / max(len(toks), 1)) * idf.get(t, 0.0) for t, count in tf.items()}
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    doc_vecs = [tfidf_vec(toks) for toks in doc_tokens]
    print(f"    {N} docs vectorized | vocab size {len(idf)}")

    def cosine(qv: dict, dv: dict) -> float:
        # 兩個 sparse dict 的 dot product（兩邊都已 L2 normalize）
        # iterate smaller dict
        if len(qv) > len(dv):
            qv, dv = dv, qv
        return sum(v * dv.get(t, 0.0) for t, v in qv.items())

    print("[4] Run test queries")
    print()

    report_lines = []
    report_lines.append("# RAG Retrieval Mock Test — v6.2 recipes_master\n")
    report_lines.append("**Backend**: TF-IDF + cosine similarity (mock pgvector)\n")
    report_lines.append(f"**Recipes**: {len(recipes)} (470 from m7_pullon_v6.2)\n")
    report_lines.append("**Query count**: 10\n\n---\n\n")

    n_hit_dim = 0
    n_hit_client = 0
    n_hit_top1 = 0
    detail_lines = []

    for tq in TEST_QUERIES:
        q_toks = tokenize(tq["query"])
        qvec = tfidf_vec(q_toks)
        scores = [cosine(qvec, dv) for dv in doc_vecs]
        # top-5
        top5_idx = sorted(range(len(scores)), key=lambda i: -scores[i])[:5]

        # 檢查
        dim_hit_pos = -1
        client_hit_pos = -1
        for rank, idx in enumerate(top5_idx, 1):
            r = recipes[idx]
            if dim_hit_pos < 0 and match_expect(r, tq["expect"]):
                dim_hit_pos = rank
            if client_hit_pos < 0 and has_client(r, tq["expect_client"]):
                client_hit_pos = rank

        dim_ok = dim_hit_pos > 0
        client_ok = client_hit_pos > 0 if tq["expect_client"] else True
        top1 = match_expect(recipes[top5_idx[0]], tq["expect"]) and (
            not tq["expect_client"] or has_client(recipes[top5_idx[0]], tq["expect_client"])
        )

        if dim_ok:
            n_hit_dim += 1
        if client_ok:
            n_hit_client += 1
        if top1:
            n_hit_top1 += 1

        # console
        marker = "✅" if (dim_ok and client_ok) else ("⚠️" if dim_ok or client_ok else "❌")
        print(f"{marker} {tq['id']}: {tq['query']}")
        print(f"   expect: {tq['expect']}{' + client=' + tq['expect_client'] if tq['expect_client'] else ''}")
        print(f"   dim hit @ rank {dim_hit_pos if dim_hit_pos > 0 else 'MISS'}, "
              f"client hit @ rank {client_hit_pos if client_hit_pos > 0 else 'MISS'}")

        # report
        detail_lines.append(f"## {tq['id']} {marker}\n\n")
        detail_lines.append(f"**Query**: `{tq['query']}`\n\n")
        detail_lines.append(f"**Expect**: `{tq['expect']}`")
        if tq["expect_client"]:
            detail_lines.append(f" + client contains `{tq['expect_client']}`")
        detail_lines.append("\n\n")
        detail_lines.append(f"- Dim hit: rank **{dim_hit_pos}** {'✅' if dim_ok else '❌ MISS'}\n")
        if tq["expect_client"]:
            detail_lines.append(f"- Client hit: rank **{client_hit_pos}** {'✅' if client_ok else '❌ MISS'}\n")
        detail_lines.append(f"- Top-1 全對: {'✅' if top1 else '❌'}\n\n")

        detail_lines.append("**Top 5 results**:\n\n")
        detail_lines.append("| Rank | Score | Key | Top ISO | Top Method | Top Client |\n")
        detail_lines.append("|---|---|---|---|---|---|\n")
        for rank, idx in enumerate(top5_idx, 1):
            r = recipes[idx]
            k = r["key"]
            score = scores[idx]
            top_iso = (r.get("iso_distribution") or [{}])[0]
            top_m = (r.get("methods") or [{}])[0]
            top_c = (r.get("client_distribution") or [{}])[0]
            key_str = f"{k['gender']}/{k['dept']}/{k['it']}/{k['wk']}/{k['l1']}"
            detail_lines.append(
                f"| {rank} | {score:.3f} | `{key_str}` | "
                f"{top_iso.get('iso', '-')}({top_iso.get('pct', 0):.0f}%) | "
                f"{top_m.get('name', '-')} | "
                f"{top_c.get('client', '-')}({top_c.get('pct', 0):.0f}%) |\n"
            )
        detail_lines.append("\n")
        print()

    # Summary
    n_total = len(TEST_QUERIES)
    print("=" * 70)
    print(f"SUMMARY")
    print(f"  Dim-only hit (any rank in top-5):       {n_hit_dim}/{n_total} = {n_hit_dim/n_total*100:.0f}%")
    print(f"  Client hit (any rank in top-5):         {n_hit_client}/{n_total} = {n_hit_client/n_total*100:.0f}%")
    print(f"  Top-1 perfect (dim + client all match): {n_hit_top1}/{n_total} = {n_hit_top1/n_total*100:.0f}%")

    report_lines.append(f"## Summary\n\n")
    report_lines.append(f"| Metric | Hit / Total | Pct |\n|---|---|---|\n")
    report_lines.append(f"| Dim hit @ top-5 | {n_hit_dim}/{n_total} | **{n_hit_dim/n_total*100:.0f}%** |\n")
    report_lines.append(f"| Client hit @ top-5 | {n_hit_client}/{n_total} | **{n_hit_client/n_total*100:.0f}%** |\n")
    report_lines.append(f"| Top-1 perfect | {n_hit_top1}/{n_total} | **{n_hit_top1/n_total*100:.0f}%** |\n\n")
    report_lines.append("**判讀**：\n")
    if n_hit_dim >= 8:
        report_lines.append("- Dim retrieval 通過 ✅ recipe doc 結構合理，平台 RAG 接得上\n")
    else:
        report_lines.append("- Dim retrieval 不及格 ❌ recipe doc 維度資訊不夠突出，需強化 build_doc\n")
    if n_hit_client >= 7:
        report_lines.append("- Client retrieval 通過 ✅ client_distribution 修復成功\n")
    else:
        report_lines.append("- Client retrieval 不夠 ⚠️ 部分 client 名稱沒被 retrieval 命中\n")
    if n_hit_top1 >= 5:
        report_lines.append("- Top-1 質量 OK ✅ TF-IDF 已能精確命中半數以上\n")
    else:
        report_lines.append("- Top-1 質量待提升 ⚠️ 建議升級到 sentence-transformers semantic embedding\n")
    report_lines.append("\n---\n\n")
    report_lines.extend(detail_lines)

    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("".join(report_lines))
    print(f"\n[output] {OUT_REPORT}")


if __name__ == "__main__":
    main()
