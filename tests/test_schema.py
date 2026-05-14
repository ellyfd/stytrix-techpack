"""Schema invariants — run in CI before build_recipes_master.

Cheap smoke tests:
- pom_rules/_index.json count matches disk files
- bucket_taxonomy.json shape (28 v4 + 59 legacy)
- l1_standard_38.json has 38 codes
- l2_l3_ie/_index.json has 38 parts
- m7/entries.jsonl row count plausible (> 1000)
- brands.json shape

These are NOT business-logic tests. They guard "did someone push a malformed
JSON / forgot to regen _index.json" — the kind of drift validate_buckets.py
won't catch by itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    return json.loads((REPO / rel).read_text(encoding="utf-8"))


# ── pom_rules ─────────────────────────────────────────────────────────────────

def test_pom_rules_index_matches_disk():
    idx = _load("pom_rules/_index.json")
    idx_buckets = sorted(b["bucket"] for b in idx["buckets"])
    disk = sorted(
        f.replace(".json", "")
        for f in os.listdir(REPO / "pom_rules")
        if f.endswith(".json") and not f.startswith("_") and f != "pom_names.json"
    )
    # bucket strings in _index use "Dept_Item|Gender" while filenames are
    # "dept_item_gender" lowercase + underscore.  Just check counts here;
    # validate_buckets.py does the deeper key-vs-field equality check.
    assert len(idx_buckets) == len(disk), (
        f"_index.json declares {len(idx_buckets)} buckets but disk has "
        f"{len(disk)} .json files (excluding _index/pom_names)"
    )
    assert len(disk) >= 100, f"only {len(disk)} buckets — POM regen likely broken"


def test_pom_rules_derive_dir_present():
    """2026-05-14: 3 Pipeline B internal files moved here from data/runtime/."""
    p = REPO / "pom_rules" / "_derive"
    assert p.is_dir(), "pom_rules/_derive/ missing"
    for name in ("client_rules.json", "design_classification_v5.json", "gender_gt_pom_rules.json"):
        assert (p / name).exists(), f"pom_rules/_derive/{name} missing"


# ── bucket_taxonomy ───────────────────────────────────────────────────────────

def test_bucket_taxonomy_shape():
    b = _load("data/runtime/bucket_taxonomy.json")
    assert isinstance(b.get("buckets"), dict), "buckets must be dict (v4 4-dim)"
    assert isinstance(b.get("legacy_buckets"), dict), "legacy_buckets must be dict (3-dim)"
    assert len(b["buckets"]) >= 20, f"too few v4 buckets ({len(b['buckets'])})"
    assert len(b["legacy_buckets"]) >= 50, f"too few legacy buckets ({len(b['legacy_buckets'])})"
    # All keys MUST be UPPERCASE per validate_buckets.py contract
    for k in b["buckets"]:
        assert k == k.upper(), f"v4 bucket key not UPPERCASE: {k}"
    for k in b["legacy_buckets"]:
        assert k == k.upper(), f"legacy bucket key not UPPERCASE: {k}"


# ── l1_standard_38 ────────────────────────────────────────────────────────────

def test_l1_standard_38_count():
    std = _load("data/runtime/l1_standard_38.json")
    codes = std.get("codes", {})
    assert len(codes) == 38, f"expected 38 L1 codes, got {len(codes)}"
    # each entry needs at least zh + en
    for code, meta in codes.items():
        assert meta.get("zh"), f"L1 {code} missing zh"


# ── l2_l3_ie Bible ────────────────────────────────────────────────────────────

def test_l2_l3_ie_index_38_parts():
    idx = _load("l2_l3_ie/_index.json")
    parts = idx.get("parts", {})
    assert len(parts) == 38, f"expected 38 Bible parts, got {len(parts)}"
    assert idx.get("schema") == "phase2", f"Bible not on Phase 2 schema (got {idx.get('schema')})"
    # Each part has a corresponding L1 JSON file on disk
    for code in parts:
        assert (REPO / "l2_l3_ie" / f"{code}.json").exists(), f"Bible {code}.json missing"


# ── m7 ingest ─────────────────────────────────────────────────────────────────

def test_m7_entries_present():
    p = REPO / "data" / "ingest" / "m7" / "entries.jsonl"
    assert p.exists(), "data/ingest/m7/entries.jsonl missing — pipeline broken"
    n = sum(1 for _ in p.open(encoding="utf-8"))
    assert n >= 1000, f"only {n} m7 entries — pipeline likely partial"


def test_m7_designs_gz_present():
    p = REPO / "data" / "ingest" / "m7" / "designs.jsonl.gz"
    assert p.exists(), "data/ingest/m7/designs.jsonl.gz missing"
    assert p.stat().st_size > 1_000_000, "designs.jsonl.gz < 1 MB — likely truncated"


# ── brands.json ───────────────────────────────────────────────────────────────

def test_brands_shape():
    b = _load("data/runtime/brands.json")
    brands = b.get("brands", [])
    assert len(brands) >= 10, f"only {len(brands)} brands — m7 might be partial"
    for entry in brands:
        assert entry.get("code"), f"brand entry missing 'code': {entry}"
        assert isinstance(entry.get("n_designs"), int), f"n_designs not int: {entry}"


# ── recipes ───────────────────────────────────────────────────────────────────

def test_recipes_index_matches_disk():
    idx = _load("recipes/_index.json")
    entries = idx.get("entries", [])
    disk = [
        f for f in os.listdir(REPO / "recipes")
        if f.endswith(".json") and not f.startswith("_")
    ]
    assert idx.get("total_recipes") == len(entries), (
        f"_index.json total_recipes ({idx.get('total_recipes')}) != len(entries) ({len(entries)})"
    )
    assert len(entries) == len(disk), (
        f"recipes/_index.json lists {len(entries)} entries but disk has {len(disk)} .json files"
    )


# ── code_manifest ─────────────────────────────────────────────────────────────

def test_code_manifest_shape():
    m = _load("data/runtime/code_manifest.json")
    files = m.get("files", [])
    assert len(files) > 100, f"code_manifest only lists {len(files)} files"
    assert m.get("large_threshold_bytes") == 1_000_000


# ── canonical_aliases ─────────────────────────────────────────────────────────

def test_canonical_aliases_loadable():
    a = _load("data/source/canonical_aliases.json")
    assert isinstance(a, dict)
    assert any(a.values()), "canonical_aliases.json appears empty"
