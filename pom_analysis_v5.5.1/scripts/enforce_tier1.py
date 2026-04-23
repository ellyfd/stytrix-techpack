#!/usr/bin/env python3
"""
Enforce Tier 1 foundational POMs as 'must' tier in all pom_rules bucket files.

Upper body GTs (TOP, OUTERWEAR, DRESS): F10, C1, J9, J10, E1, I5
Lower body GTs (PANTS, LEGGINGS, SHORTS, SKIRT): H1, L2, L8, K1, K2, O4, N9
Combined GTs (ROMPER_JUMPSUIT, SET, BODYSUIT): both sets

Rules:
- If Tier 1 POM exists in recommend/optional → move to must, add "tier1_enforced": true
- If Tier 1 POM already in must → add "tier1_enforced": true (mark it)
- If Tier 1 POM is completely absent → add to must with rate=0, count=0, tier1_enforced=true, tier1_absent=true
- Preserve all existing fields (rate, count, tolerance)
"""

import json, glob, os

RULES_DIR = '/sessions/stoic-magical-curie/mnt/ONY/pom_rules'

UPPER_TIER1 = ['F10', 'C1', 'J9', 'J10', 'E1', 'I5']
LOWER_TIER1 = ['H1', 'L2', 'L8', 'K1', 'K2', 'O4', 'N9']

UPPER_GTS = {'TOP', 'OUTERWEAR', 'DRESS'}
LOWER_GTS = {'PANTS', 'LEGGINGS', 'SHORTS', 'SKIRT'}
COMBINED_GTS = {'ROMPER_JUMPSUIT', 'SET', 'BODYSUIT'}

def get_tier1_poms(gt):
    if gt in UPPER_GTS:
        return UPPER_TIER1[:]
    elif gt in LOWER_GTS:
        return LOWER_TIER1[:]
    elif gt in COMBINED_GTS:
        return UPPER_TIER1 + LOWER_TIER1
    else:
        return []

stats = {
    'files_processed': 0,
    'moved_from_recommend': 0,
    'moved_from_optional': 0,
    'already_in_must': 0,
    'added_absent': 0,
    'details': []
}

for fpath in sorted(glob.glob(os.path.join(RULES_DIR, '*.json'))):
    fname = os.path.basename(fpath)
    if fname.startswith('_') or fname == 'pom_names.json':
        continue

    with open(fpath) as f:
        data = json.load(f)

    gt = data.get('garment_type', '')
    tier1_poms = get_tier1_poms(gt)
    if not tier1_poms:
        continue

    stats['files_processed'] += 1
    rules = data.get('measurement_rules', {})
    must = rules.get('must', {})
    recommend = rules.get('recommend', {})
    optional = rules.get('optional', {})

    changed = False

    for pom in tier1_poms:
        if pom in must:
            # Already in must — just mark it
            must[pom]['tier1_enforced'] = True
            stats['already_in_must'] += 1
            changed = True
        elif pom in recommend:
            # Move from recommend to must
            entry = recommend.pop(pom)
            entry['tier1_enforced'] = True
            must[pom] = entry
            stats['moved_from_recommend'] += 1
            stats['details'].append(f"{fname}: {pom} recommend→must (rate={entry.get('rate', '?')})")
            changed = True
        elif pom in optional:
            # Move from optional to must
            entry = optional.pop(pom)
            entry['tier1_enforced'] = True
            must[pom] = entry
            stats['moved_from_optional'] += 1
            stats['details'].append(f"{fname}: {pom} optional→must (rate={entry.get('rate', '?')})")
            changed = True
        else:
            # Completely absent — skip (user rule: don't add absent POMs)
            stats['added_absent'] += 1

    if changed:
        rules['must'] = must
        rules['recommend'] = recommend
        rules['optional'] = optional
        data['measurement_rules'] = rules

        # Also update foundational_measurements section if it exists
        if 'foundational_measurements' not in data:
            data['foundational_measurements'] = {
                'tier1_poms': tier1_poms,
                'enforced': True
            }

        with open(fpath, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# Update _index.json version
idx_path = os.path.join(RULES_DIR, '_index.json')
with open(idx_path) as f:
    idx = json.load(f)
idx['_meta']['version'] = '5.2'
idx['_meta']['tier1_enforcement'] = {
    'upper_body': UPPER_TIER1,
    'lower_body': LOWER_TIER1,
    'combined_gts': list(COMBINED_GTS),
    'rule': 'Tier 1 POMs forced to must tier regardless of hit rate'
}
with open(idx_path, 'w') as f:
    json.dump(idx, f, indent=2, ensure_ascii=False)

# Print summary
print(f"=== Tier 1 Enforcement Summary ===")
print(f"Files processed: {stats['files_processed']}")
print(f"Already in must (marked): {stats['already_in_must']}")
print(f"Moved from recommend→must: {stats['moved_from_recommend']}")
print(f"Moved from optional→must: {stats['moved_from_optional']}")
print(f"Added absent POMs: {stats['added_absent']}")
print(f"\n--- Details of changes ---")
for d in stats['details']:
    print(d)
