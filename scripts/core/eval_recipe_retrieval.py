#!/usr/bin/env python3
"""Held-out top-K hit-rate eval for the recipe TF-IDF index.

Held-out signal: each recipe's `top_method_describes` text (numerics stripped).
That field is NOT included in the indexed doc_text, so retrieval has to find
the bucket from describes-text overlap with codes/sections/parts/machines.

Usage:
    python3 scripts/eval_recipe_retrieval.py [--ks 1 3 5 10] [--show-misses 5]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _recipe_text import query_text_from_describes  # noqa: E402
from search_recipes import load_index, query_vector, search, format_key  # noqa: E402

DEFAULT_INDEX = ROOT / 'data/ingest/recipe_index/index.json'
DEFAULT_RECIPES = ROOT / 'data/ingest/uploads/recipes_master_v6.jsonl'


def evaluate(index: dict, recipes: list[dict], ks: list[int], show_misses: int):
    doc_keys = index['doc_keys']
    key_to_idx = {format_key(k): i for i, k in enumerate(doc_keys)}
    vocab = index['vocab']
    idf = index['idf']
    doc_vectors = index['doc_vectors']
    max_k = max(ks)

    n_eligible = 0
    n_no_query = 0
    hits_at = {k: 0 for k in ks}
    rr_total = 0.0
    miss_examples: list[dict] = []
    by_conf: dict[str, dict] = {}

    for r in recipes:
        true_idx = key_to_idx.get(format_key(r['key']))
        if true_idx is None:
            continue
        qtext = query_text_from_describes(r)
        qvec = query_vector(qtext, vocab, idf)
        conf = r.get('confidence', 'unknown')
        bucket = by_conf.setdefault(conf, {'n': 0, 'no_q': 0, 'hits': {k: 0 for k in ks}})
        bucket['n'] += 1
        if not qvec:
            n_no_query += 1
            bucket['no_q'] += 1
            continue
        n_eligible += 1
        hits = search(qvec, doc_vectors, max_k)
        ranked = [d_idx for _, d_idx in hits]
        try:
            rank = ranked.index(true_idx) + 1
        except ValueError:
            rank = None
        for k in ks:
            if rank is not None and rank <= k:
                hits_at[k] += 1
                bucket['hits'][k] += 1
        if rank is not None:
            rr_total += 1.0 / rank
        elif show_misses and len(miss_examples) < show_misses:
            miss_examples.append({
                'true': format_key(r['key']),
                'category_zh': r.get('category_zh', ''),
                'confidence': conf,
                'query_preview': qtext[:120],
                'top1': format_key(doc_keys[ranked[0]]) if ranked else '',
            })

    total = len(recipes)
    print(f'recipes total: {total}    eligible (non-empty query): {n_eligible}    '
          f'no-query (empty describes): {n_no_query}')
    print()
    print('held-out top-K hit rate (over eligible):')
    for k in ks:
        h = hits_at[k]
        pct = 100.0 * h / n_eligible if n_eligible else 0
        print(f'  top-{k:<2}  {h}/{n_eligible}  ({pct:.1f}%)')
    mrr = rr_total / n_eligible if n_eligible else 0
    print(f'  MRR     {mrr:.3f}')

    if by_conf:
        print()
        print('by confidence bucket:')
        for conf in sorted(by_conf):
            b = by_conf[conf]
            elig = b['n'] - b['no_q']
            if not elig:
                print(f'  {conf:<10}  n={b["n"]:>4}  (no eligible queries)')
                continue
            cells = '  '.join(
                f'top-{k}={100.0*b["hits"][k]/elig:5.1f}%' for k in ks
            )
            print(f'  {conf:<10}  n={b["n"]:>4}  elig={elig:>4}  {cells}')

    if miss_examples:
        print()
        print(f'sample misses (target not in top-{max_k}):')
        for m in miss_examples:
            print(f'  - {m["true"]}  ({m["category_zh"]}, {m["confidence"]})')
            print(f'      query: {m["query_preview"]!r}')
            print(f'      top-1: {m["top1"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', type=Path, default=DEFAULT_INDEX)
    ap.add_argument('--recipes', type=Path, default=DEFAULT_RECIPES)
    ap.add_argument('--ks', type=int, nargs='+', default=[1, 3, 5, 10])
    ap.add_argument('--show-misses', type=int, default=5)
    args = ap.parse_args()

    if not args.index.exists():
        print(f'ERROR: index not found at {args.index}', file=sys.stderr)
        sys.exit(1)
    if not args.recipes.exists():
        print(f'ERROR: recipes not found at {args.recipes}', file=sys.stderr)
        sys.exit(1)

    index = load_index(args.index)
    recipes = [json.loads(line) for line in args.recipes.read_text().splitlines() if line.strip()]
    evaluate(index, recipes, sorted(args.ks), args.show_misses)


if __name__ == '__main__':
    main()
