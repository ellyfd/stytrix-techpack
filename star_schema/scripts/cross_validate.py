#!/usr/bin/env python3
"""
cross_validate.py — Compare per-design extraction vs consensus_rules.

For each bucket×zone that exists in both sources, compare:
1. ISO agreement rate
2. Zone coverage overlap
3. Identify conflicts and gaps
"""

import json
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent / "data" / "ingest"


def load_extraction_facts():
    """Load per-design extraction facts and aggregate by bucket×zone."""
    facts = []
    with open(BASE / 'construction_by_bucket' / 'facts.jsonl') as f:
        for line in f:
            facts.append(json.loads(line))

    # Load dim for design count per bucket
    dim = []
    with open(BASE / 'construction_by_bucket' / 'dim.jsonl') as f:
        for line in f:
            dim.append(json.loads(line))
    designs_per_bucket = defaultdict(int)
    for d in dim:
        designs_per_bucket[d['bucket']] += 1

    # Aggregate: bucket × zone → {iso: count, combo: count}
    agg = defaultdict(lambda: {
        'iso_counts': defaultdict(int),
        'combo_counts': defaultdict(int),
        'n_designs': 0,
        'design_ids': set(),
    })

    for f in facts:
        if f['l1_code'] == '_DEFAULT':
            continue  # skip default rules for comparison
        key = (f['bucket'], f['zone_zh'], f['l1_code'])
        agg[key]['design_ids'].add(f['design_id'])
        if f['iso']:
            agg[key]['iso_counts'][f['iso']] += 1
        if f['combo']:
            agg[key]['combo_counts'][f['combo']] += 1

    for key in agg:
        agg[key]['n_designs'] = len(agg[key]['design_ids'])

    return agg, designs_per_bucket


def load_consensus_facts():
    """Load normalized consensus rules."""
    facts = []
    with open(BASE / 'consensus_rules' / 'facts.jsonl') as f:
        for line in f:
            facts.append(json.loads(line))

    # Index by bucket × zone
    idx = {}
    for f in facts:
        if f['l1_code'] == '_DEFAULT':
            continue
        key = (f['bucket'], f['zone_zh'], f['l1_code'])
        # Multiple fingerprints per bucket×zone — keep all
        if key not in idx:
            idx[key] = []
        idx[key].append(f)

    return idx


def compare():
    extraction, designs_per_bucket = load_extraction_facts()
    consensus = load_consensus_facts()

    # Find overlapping keys
    ext_keys = set(extraction.keys())
    con_keys = set(consensus.keys())
    both = ext_keys & con_keys
    ext_only = ext_keys - con_keys
    con_only = con_keys - ext_keys

    print(f"{'='*60}")
    print(f"CROSS VALIDATION: Extraction vs Consensus")
    print(f"{'='*60}")
    print(f"Extraction unique bucket×zone×l1: {len(ext_keys)}")
    print(f"Consensus unique bucket×zone×l1:  {len(con_keys)}")
    print(f"Overlap:                          {len(both)}")
    print(f"Extraction only:                  {len(ext_only)}")
    print(f"Consensus only:                   {len(con_only)}")

    # ── Compare overlapping keys ──
    agrees = 0
    conflicts = 0
    conflict_details = []

    for key in sorted(both):
        bucket, zone_zh, l1_code = key
        ext = extraction[key]
        con_list = consensus[key]

        # Get top ISO from extraction
        all_isos = dict(ext['iso_counts'])
        all_isos.update(ext['combo_counts'])
        if not all_isos:
            continue
        ext_top = max(all_isos, key=all_isos.get)

        # Get consensus ISO (may have multiple fingerprints)
        con_isos = set()
        for c in con_list:
            if c.get('iso'):
                con_isos.add(c['iso'])
            if c.get('combo'):
                con_isos.add(c['combo'])

        if ext_top in con_isos or not con_isos:
            agrees += 1
        else:
            conflicts += 1
            conflict_details.append({
                'key': key,
                'ext_top': ext_top,
                'ext_all': dict(all_isos),
                'ext_n': ext['n_designs'],
                'con_isos': con_isos,
                'con_fps': [c['fingerprint'] for c in con_list],
            })

    print(f"\n--- Agreement on overlapping keys ---")
    total = agrees + conflicts
    print(f"Agrees:    {agrees}/{total} ({agrees*100//max(1,total)}%)")
    print(f"Conflicts: {conflicts}/{total}")

    if conflict_details:
        print(f"\n--- Conflict Details (top 10) ---")
        for cd in conflict_details[:10]:
            b, z, l1 = cd['key']
            print(f"  {b} | {z}({l1})")
            print(f"    Extraction top: {cd['ext_top']} (from {cd['ext_n']} designs, all: {cd['ext_all']})")
            print(f"    Consensus:      {cd['con_isos']} (fps: {cd['con_fps']})")

    # ── Coverage analysis ──
    print(f"\n--- Consensus-only zones (extraction gap) ---")
    con_only_zones = defaultdict(int)
    for key in con_only:
        con_only_zones[key[1]] += 1
    for z, n in sorted(con_only_zones.items(), key=lambda x: -x[1])[:10]:
        print(f"  {z}: {n} bucket×zone combos not in extraction")

    print(f"\n--- Extraction-only zones (new coverage) ---")
    ext_only_zones = defaultdict(int)
    for key in ext_only:
        ext_only_zones[key[1]] += 1
    for z, n in sorted(ext_only_zones.items(), key=lambda x: -x[1])[:10]:
        print(f"  {z}: {n} bucket×zone combos new from extraction")

    # ── Summary stats ──
    ext_buckets = set(k[0] for k in ext_keys)
    con_buckets = set(k[0] for k in con_keys)
    print(f"\n--- Bucket Coverage ---")
    print(f"Extraction covers: {len(ext_buckets)} buckets")
    print(f"Consensus covers:  {len(con_buckets)} buckets")
    print(f"Both cover:        {len(ext_buckets & con_buckets)} buckets")

    return agrees, conflicts


if __name__ == '__main__':
    compare()
