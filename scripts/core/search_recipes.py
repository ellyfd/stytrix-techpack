#!/usr/bin/env python3
"""CLI search against the recipe TF-IDF index.

Usage:
    python3 scripts/search_recipes.py "query text" [--k 5]
"""
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _recipe_text import tokenize  # noqa: E402

DEFAULT_INDEX = ROOT / 'data/ingest/recipe_index/index.json'


def load_index(path: Path) -> dict:
    return json.loads(path.read_text())


def query_vector(text: str, vocab: dict, idf: list[float]) -> dict[int, float]:
    toks = tokenize(text)
    if not toks:
        return {}
    tf = Counter(toks)
    vec: dict[int, float] = {}
    for t, c in tf.items():
        i = vocab.get(t)
        if i is None:
            continue
        vec[i] = (1.0 + math.log(c)) * idf[i]
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {i: w / norm for i, w in vec.items()}


def search(qvec: dict[int, float], doc_vectors, k: int) -> list[tuple[float, int]]:
    if not qvec:
        return []
    scores = []
    for d_idx, dvec in enumerate(doc_vectors):
        s = 0.0
        for i, w in dvec:
            qw = qvec.get(i)
            if qw is not None:
                s += w * qw
        if s > 0:
            scores.append((s, d_idx))
    scores.sort(reverse=True)
    return scores[:k]


def format_key(k: dict) -> str:
    return '|'.join(str(k.get(f, '')) for f in ('gender', 'dept', 'gt', 'it', 'wk', 'l1'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='+')
    ap.add_argument('--k', type=int, default=5)
    ap.add_argument('--index', type=Path, default=DEFAULT_INDEX)
    args = ap.parse_args()

    if not args.index.exists():
        print(f'ERROR: index not found at {args.index}. Run build_recipe_embeddings.py first.',
              file=sys.stderr)
        sys.exit(1)

    idx = load_index(args.index)
    query = ' '.join(args.query)
    qvec = query_vector(query, idx['vocab'], idx['idf'])
    if not qvec:
        print(f'(no in-vocab tokens for query: {query!r})')
        sys.exit(0)
    hits = search(qvec, idx['doc_vectors'], args.k)
    if not hits:
        print('(no matches)')
        return
    print(f'query: {query!r}    top {args.k}:')
    for rank, (score, d_idx) in enumerate(hits, 1):
        key = idx['doc_keys'][d_idx]
        meta = idx['doc_meta'][d_idx]
        print(f'  {rank}. score={score:.4f}  {format_key(key)}  '
              f'({meta.get("category_zh", "")})  conf={meta.get("confidence")}  n={meta.get("n_total")}')


if __name__ == '__main__':
    main()
