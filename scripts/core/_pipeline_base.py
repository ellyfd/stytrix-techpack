"""Shared BASE-directory resolver for POM RULES pipeline scripts.

Why this exists
---------------
Every POM RULES pipeline script used to hardcode
``BASE = '/sessions/stoic-magical-curie/mnt/ONY'`` at the top. That path only
exists inside one internal environment, so the scripts could not run for
external collaborators (even when shipped via PackageModal's zip export).

This helper unifies the resolution into a single place:

1. ``--base-dir <path>`` CLI argument (if the caller registers it via
   :func:`add_base_dir_arg`)
2. ``$POM_PIPELINE_BASE`` environment variable
3. Error out with a clear usage message (no silent fallback — that would
   lead to scripts writing to the wrong place and corrupting derived
   files).

Expected BASE folder layout (external users create this themselves):

    $BASE/
      2024/, 2025/, 2026/                ← PDF source folders (per year /
                                           season / month)
      _parsed/                           ← produced by run_extract_*.py
        mc_pom_2024.jsonl
        mc_pom_2025.jsonl
        mc_pom_2026.jsonl
        mc_pom_combined.jsonl            ← optional, concat of above
        all_years.jsonl                  ← metadata; curated externally
      measurement_profiles_union.json    ← produced by rebuild_profiles.py
      design_classification_v5.json      ← produced by rebuild_all_analysis_v2.py
      pom_dictionary.json                ← seeded from repo data/
      pom_rules/                         ← final output
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ENV_VAR = "POM_PIPELINE_BASE"


def add_base_dir_arg(parser: argparse.ArgumentParser) -> None:
    """Register ``--base-dir`` on an existing argparse parser."""
    parser.add_argument(
        "--base-dir",
        dest="base_dir",
        default=None,
        help=(
            "Root folder of the POM RULES pipeline data tree. "
            f"Falls back to ${ENV_VAR} if not set."
        ),
    )


def resolve_base_dir(cli_value: str | None = None) -> Path:
    """Resolve BASE from CLI, env var, or exit with usage help."""
    raw = cli_value or os.environ.get(ENV_VAR)
    if not raw:
        sys.stderr.write(
            "error: POM pipeline BASE directory not set.\n"
            f"  Pass --base-dir <path> or export {ENV_VAR}=<path>.\n"
            "  See scripts/_pipeline_base.py docstring for expected layout.\n"
        )
        sys.exit(2)
    base = Path(raw).expanduser().resolve()
    if not base.is_dir():
        sys.stderr.write(f"error: BASE directory does not exist: {base}\n")
        sys.exit(2)
    return base


def get_base_dir(description: str | None = None) -> Path:
    """One-shot helper for scripts that only need --base-dir and nothing else."""
    parser = argparse.ArgumentParser(description=description)
    add_base_dir_arg(parser)
    args, _unknown = parser.parse_known_args()
    return resolve_base_dir(args.base_dir)


# ─── 2026-05-14: M7 manifest Item → body region ───────────────────────────
# Elly 指示: pom_rules 的 garment_type 直接用聚陽 M7 manifest 的 Item 原值
# (不收斂成 TOP/PANTS/... 9 桶). 但 POM 排序 (fix_sort_order.py) 與 tier1
# 預設 (enforce_tier1.py) 仍需要知道「上半身/下半身/連身」來決定 zone 順序。
# 這張表「只」服務那兩個用途, 不是 garment_type 本身。
# reclassify_and_rebuild.py 用它把 body_region 寫進每個 bucket;
# 下游兩支腳本直接讀 bucket 的 body_region 欄, 不必再 import 這張表。
MK_ITEM_REGION = {
    # 上半身 (領→肩→袖→胸→身長 排序)
    "Tee": "upper", "Graphic Tee": "upper", "Blouse/Shirts": "upper",
    "Polo": "upper", "Camisole": "upper", "Pajama Top": "upper",
    "Swimwear": "upper", "Jacket": "upper", "Coat": "upper",
    "Blazer": "upper", "Vest": "upper", "Robe": "upper",
    "Dress": "upper", "Gown": "upper", "Chemise": "upper",
    # 下半身 (腰→約克→門襟→前後襠→臀→腿 排序)
    "Pull On Pants": "lower", "Dressy Pants": "lower", "Pull On Dressy": "lower",
    "Pajama Bottom": "lower", "Leggings": "lower", "Shorts": "lower",
    "Skorts": "lower", "Boxer": "lower", "Panties": "lower", "Skirt": "lower",
    # 連身 (上半身 zone 在前, 下半身 zone 在後)
    "Pajama": "combined", "Pajama 3PC": "combined", "Suit": "combined",
    "Jumper": "combined", "Coverall": "combined",
    # 非服裝 — 預設 upper (POM 量少, 影響小)
    "Accessories": "upper", "Blanket": "upper",
}


def mk_item_region(item: str) -> str:
    """M7 manifest Item → 'upper'/'lower'/'combined' (POM 排序 + tier1 預設用).

    未知 Item (manifest 新增、或 fallback 關鍵字產生的舊式 GT) → 預設 'upper'.
    """
    return MK_ITEM_REGION.get((item or "").strip(), "upper")
