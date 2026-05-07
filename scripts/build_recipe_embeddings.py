#!/usr/bin/env python3
"""Build a TF-IDF index over data/ingest/uploads/recipes_master_v6.jsonl.

Usage:
    python3 scripts/build_recipe_embeddings.py
    python3 scripts/build_recipe_embeddings.py --in <jsonl> --out <json>

Output (default): data/ingest/recipe_index/index.json
"""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _recipe_text import tokenize, doc_text  # noqa: E402

DEFAULT_IN = ROOT / 'data/ingest/uploads/recipes_master_v6.jsonl'
DEFAULT_OUT = ROOT / 'data/ingest/recipe_index/index.json'


def build(in_path: Path, out_path: Path) -> dict:
    recipes = [json.loads(line) for line in in_path.read_text().splitlines() if line.strip()]
    tokenized = [tokenize(doc_text(r)) for r in recipes]

    df: Counter = Counter()
    for toks in tokenized:
        for t in set(toks):
            df[t] += 1

    vocab_terms = sorted(df)
    vocab = {t: i for i, t in enumerate(vocab_terms)}
    n = len(recipes)
    idf = [math.log((n + 1) / (df[t] + 1)) + 1.0 for t in vocab_terms]

    doc_vectors = []
    for toks in tokenized:
        if not toks:
            doc_vectors.append([])
            continue
        tf = Counter(toks)
        raw = []
        for t, c in tf.items():
            i = vocab[t]
            w = (1.0 + math.log(c)) * idf[i]
            raw.append((i, w))
        norm = math.sqrt(sum(w * w for _, w in raw)) or 1.0
        doc_vectors.append([[i, round(w / norm, 6)] for i, w in raw])

    index = {
        'version': 'v6-tfidf-1',
        'source': str(in_path.relative_to(ROOT)),
        'n_docs': n,
        'vocab_size': len(vocab),
        'idf': [round(x, 6) for x in idf],
        'vocab': vocab,
        'doc_keys': [r['key'] for r in recipes],
        'doc_meta': [
            {
                'category_zh': r.get('category_zh', ''),
                'confidence': r.get('confidence', ''),
                'n_total': r.get('n_total', 0),
                'n_designs': r.get('n_designs', 0),
            }
            for r in recipes
        ],
        'doc_vectors': doc_vectors,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, ensure_ascii=False))
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='in_path', type=Path, default=DEFAULT_IN)
    ap.add_argument('--out', dest='out_path', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.in_path.exists():
        print(f'ERROR: input not found: {args.in_path}', file=sys.stderr)
        sys.exit(1)

    index = build(args.in_path, args.out_path)
    size_kb = args.out_path.stat().st_size / 1024
    print(f'built {index["n_docs"]} docs, vocab={index["vocab_size"]}, '
          f'wrote {args.out_path.relative_to(ROOT)} ({size_kb:.1f} KB)')


if __name__ == '__main__':
    main()
