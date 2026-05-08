#!/usr/bin/env python3
"""Build data/runtime/recipes_master.json + data/runtime/l1_standard_38.json + data/master.jsonl.

Merges five construction handbooks into a single unified master file that the
index.html universal-mode viewer can query with a single fallback cascade.

Phase 2.1: also emits data/master.jsonl (one entry per line, keeps `_m7_*`
internal fields). This is the canonical "single source of truth" for derive
views — see docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md.

Sources (all inputs kept read-only):
  - path2_universal/iso_lookup_factory_v4.3.json
    (230 entries; Department × Gender × GT × L1 with iso_distribution + n_designs)
  - path2_universal/iso_lookup_factory_v4.json
    (282 entries; Fabric × Department × GT × L1_code with iso_zh / machine)
  - data/runtime/construction_bridge_v6.json
    (bridges[GT][zones][zh_zone] with methods + iso_codes)
  - recipes/*.json (71 files; same-sub-category stats)
  - star_schema/data/ingest/consensus_v1/entries.jsonl + bucket_taxonomy.json
    (275 entries; same_bucket consensus rules with ISO from unified extraction + OCR)

Output schema (data/runtime/recipes_master.json — same content also one-line-per-entry in data/master.jsonl):
{
  "generated_at": "...",
  "source_versions": {...},
  "stats": {...},
  "entries": [
    {
      "key": {"gender": "...", "dept": "...", "gt": "...", "it": "...", "l1": "..."},
      "aggregation_level": "same_sub|same_bucket|same_gt|general|cross_design",
      "source": "recipe|consensus_v1|v4.3|v4|bridge",
      "n_total": N,
      "iso_distribution": [{"iso": "406", "n": 9, "pct": 69.2}, ...],
      "methods": [{"name": "BINDING", "n": 5, "pct": 50.0}, ...]  # may be []
    },
    ...
  ]
}

Key fields are normalized to UPPERCASE with non-alphanumerics → underscore
so the viewer can query by a single canonical key regardless of source casing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Path resolution: script is at star_schema/scripts/build_recipes_master.py
# SCRIPTS_DIR = star_schema/scripts/
# STAR_SCHEMA = star_schema/   (parent of scripts/)
# REPO_ROOT   = stytrix-techpack/ (parent of star_schema/)
STAR_SCHEMA = Path(__file__).resolve().parent.parent
REPO_ROOT = STAR_SCHEMA.parent

# Input sources (all relative to repo root)
# 2026-05-07: 資料夾改名 General Model_Path2_Construction Suggestion → path2_universal
V43_PATH = REPO_ROOT / "path2_universal" / "iso_lookup_factory_v4.3.json"
V4_PATH  = REPO_ROOT / "path2_universal" / "iso_lookup_factory_v4.json"
# 2026-05-07: 搬到 data/runtime/ (跟其他 runtime JSON 一起)
BRIDGE_PATH = REPO_ROOT / "data" / "runtime" / "construction_bridge_v6.json"
RECIPES_DIR = REPO_ROOT / "recipes"

# Star schema ingest paths
CONSENSUS_PATH = REPO_ROOT / "data" / "ingest" / "consensus_v1" / "entries.jsonl"
INGEST_DIR = REPO_ROOT / "data" / "ingest"
BUCKET_TAX_PATH = REPO_ROOT / "data" / "bucket_taxonomy.json"

# M7 PullOn source (聚陽 Windows pipeline → push 進 ingest/m7_pullon/)
M7_PULLON_PATH = REPO_ROOT / "data" / "ingest" / "m7_pullon" / "entries.jsonl"

# L1 standard 38 codes — facts with l1_code outside this set are skipped
L1_VALID_38 = frozenset(
    "AE AH BM BN BP BS DC DP FP FY HD HL KH LB LI LO LP NK NP NT OT "
    "PD PK PL PS QT RS SA SB SH SL SP SR SS ST TH WB ZP".split()
)

# Special L1 codes that are NOT in the 38-part standard but carry real data.
# "_DEFAULT" = catch-all bucket-level rule emitted by extract_unified when a
# techpack writes "All body seams are <ISO>". The rule applies to every
# L1 part's body seam for that design; we preserve it as an entry with
# l1="_DEFAULT" so the frontend can use it as a final fallback when
# per-L1 lookups miss.
L1_SPECIAL = frozenset({"_DEFAULT"})
L1_ACCEPTED = L1_VALID_38 | L1_SPECIAL

OUT_MASTER = REPO_ROOT / "data" / "runtime" / "recipes_master.json"
OUT_L1_STD = REPO_ROOT / "data" / "runtime" / "l1_standard_38.json"
OUT_MASTER_JSONL = REPO_ROOT / "data" / "master.jsonl"


# ── Gate Report ────────────────────────────────────────────────────────────
# Two-tier classification of build issues.
#
# B-tier = silent data loss. --strict blocks the build on any B-tier hit.
#   • b_l1_not_38        facts row with L1 code outside the 38 standard
#   • b_bucket_consensus consensus row whose bucket isn't in bucket_taxonomy
#   • b_bucket_facts     facts row whose bucket isn't in bucket_taxonomy
#   • b_recipe_parse     recipe file that failed json.load
#
# A-tier = observability only. Tracked for future extract/translation-table
# optimisation; never blocks (unless --strict-all, reserved for future).
#   • a_zone_recipe      recipe zh zone name not resolvable to L1
#   • a_zone_bridge      bridge zh zone name not resolvable to L1
#   • a_recipe_missing_fields  recipe missing gender/dept/gt/it
#   • a_consensus_missing      consensus row missing bucket or l1
#   • a_iso_rejected     ISO value rejected by iso_is_valid()
class GateReport:
    def __init__(self):
        # B-tier: value → count of the offending key (L1 code / bucket name / filename)
        self.b_l1_not_38 = Counter()
        self.b_bucket_consensus = Counter()
        self.b_bucket_facts = Counter()
        self.b_recipe_parse: list[tuple[str, str]] = []
        # A-tier
        self.a_zone_recipe = Counter()
        self.a_zone_bridge = Counter()
        self.a_recipe_missing_fields: list[str] = []
        self.a_consensus_missing = 0
        self.a_iso_rejected = Counter()
        # L1 catch-all rules — real data (techpack's "all body seams are <ISO>"),
        # tracked here for visibility but intentionally not a violation.
        self.a_default_rules = Counter()  # ISO value → count

    def b_total(self) -> int:
        return (
            sum(self.b_l1_not_38.values())
            + sum(self.b_bucket_consensus.values())
            + sum(self.b_bucket_facts.values())
            + len(self.b_recipe_parse)
        )

    def a_total(self) -> int:
        return (
            sum(self.a_zone_recipe.values())
            + sum(self.a_zone_bridge.values())
            + len(self.a_recipe_missing_fields)
            + self.a_consensus_missing
            + sum(self.a_iso_rejected.values())
            + sum(self.a_default_rules.values())
        )

    @staticmethod
    def _top(counter: Counter, n: int = 5) -> str:
        items = counter.most_common(n)
        if not items:
            return ""
        rest = sum(counter.values()) - sum(c for _, c in items)
        parts = [f"{k} ×{c}" for k, c in items]
        if rest:
            parts.append(f"… +{rest} more")
        return "  ".join(parts)

    def format(self) -> str:
        bar = "━" * 60
        lines = [
            bar,
            "  Gate Report  —  recipes_master build",
            bar,
            "",
            "[B-tier]  硬違規（--strict 會擋 commit）",
        ]

        # B.1 L1 not in 38
        total_l1 = sum(self.b_l1_not_38.values())
        lines.append(f"  ◯ L1 不在 38 標準:       {total_l1} 筆 facts 被丟")
        if total_l1:
            lines.append(f"      top codes: {self._top(self.b_l1_not_38)}")

        # B.2 bucket not in taxonomy
        total_bc = sum(self.b_bucket_consensus.values())
        total_bf = sum(self.b_bucket_facts.values())
        lines.append(f"  ◯ bucket 不在 taxonomy:")
        lines.append(f"      • consensus  {total_bc} 筆  {len(self.b_bucket_consensus)} 個 bucket")
        if self.b_bucket_consensus:
            for b, c in self.b_bucket_consensus.most_common(10):
                lines.append(f"          {b}  ×{c}")
        lines.append(f"      • facts-agg  {total_bf} 筆  {len(self.b_bucket_facts)} 個 bucket")
        if self.b_bucket_facts:
            for b, c in self.b_bucket_facts.most_common(10):
                lines.append(f"          {b}  ×{c}")

        # B.3 recipe parse fail
        lines.append(f"  ◯ recipe 檔 parse 壞:    {len(self.b_recipe_parse)} 檔")
        for fname, err in self.b_recipe_parse:
            lines.append(f"      • {fname}  ({err})")

        lines.append("")
        lines.append(f"  總計:  B-tier  {self.b_total()} 筆  ← --strict 會據此決定 exit code")

        # A-tier
        lines += ["", "[A-tier]  軟提醒（未來優化用；--strict 不擋）"]

        total_zr = sum(self.a_zone_recipe.values())
        total_zb = sum(self.a_zone_bridge.values())
        lines.append(f"  ◯ 中文 zone 名對不上 L1:  {total_zr + total_zb} 次")
        if total_zr:
            lines.append(f"      • recipe {total_zr} 次  top: {self._top(self.a_zone_recipe)}")
        if total_zb:
            lines.append(f"      • bridge {total_zb} 次  top: {self._top(self.a_zone_bridge)}")

        lines.append(f"  ◯ recipe 少必要欄位:       {len(self.a_recipe_missing_fields)} 檔")
        for fname in self.a_recipe_missing_fields[:10]:
            lines.append(f"      • {fname}")

        lines.append(f"  ◯ consensus 少 bucket/l1:  {self.a_consensus_missing} 筆")

        total_iso = sum(self.a_iso_rejected.values())
        lines.append(f"  ◯ ISO 非數字被拒:          {total_iso} 筆")
        if total_iso:
            lines.append(f"      top values: {self._top(self.a_iso_rejected)}")

        # Split catch-all rules by iso value shape — numeric (real ISO) vs
        # categorical placeholder (BINDING / BONDED / LASER_CUT / RAW_EDGE;
        # see vlm_pipeline.py:666 — these mean "this method has no single
        # canonical ISO, context-dependent").
        CATEGORICAL = {"BINDING", "BONDED", "LASER_CUT", "RAW_EDGE"}
        numeric = Counter({k: v for k, v in self.a_default_rules.items()
                           if k not in CATEGORICAL})
        categorical = Counter({k: v for k, v in self.a_default_rules.items()
                               if k in CATEGORICAL})
        total_def = sum(self.a_default_rules.values())
        lines.append(f"  ◯ _DEFAULT catch-all 規則: {total_def} 筆  (legit catch-all「全款 body seam 為 X」)")
        if sum(numeric.values()):
            lines.append(f"      ISO 數字分布:   {self._top(numeric)}")
        if sum(categorical.values()):
            lines.append(f"      categorical:   {self._top(categorical)}  (非 ISO 數字,表示該工法 context-dependent)")

        lines.append("")
        lines.append(f"  總計:  A-tier  {self.a_total()} 筆  ← 未來 --strict-all 會擋,此版僅記錄")
        lines.append("")
        lines.append(bar)
        return "\n".join(lines)


# Module-level singleton. Functions in this file mutate it during the build.
GATE = GateReport()


def norm(s):
    """Uppercase + collapse non-alphanumerics into underscores."""
    if s is None:
        return None
    up = re.sub(r"[^A-Z0-9]+", "_", str(s).upper()).strip("_")
    return up or None


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def build_l1_standard_38(v43) -> dict:
    """Load L1 standard 38 — prefer star_schema/data/l1_standard_38.json (ground truth),
    fall back to v4.3's l1_standard_38 field if file not found."""
    # Ground truth file (already corrected to IE standard)
    gt_path = REPO_ROOT / "data" / "l1_standard_38.json"
    if gt_path.exists():
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        return gt

    # Fallback: from v4.3 (may have wrong zh names)
    std = v43.get("l1_standard_38") or {}
    return {
        "version": v43.get("version", "v4.3"),
        "source": "iso_lookup_factory_v4.3.json",
        "codes": std,
    }


def build_zh_to_l1(l1_std: dict) -> dict:
    """zh part name → l1 code. Used to reverse-lookup bridge / recipe zones.
    Includes aliases for variant Chinese names used in PPTX translations."""
    out = {}
    for code, info in (l1_std.get("codes") or {}).items():
        zh = (info or {}).get("zh")
        if zh:
            out[zh] = code
    # Aliases: variant Chinese names → correct L1 code per ground truth 38
    # Ground truth: AE=袖孔 AH=袖圍 DC=繩類 LO=褲口 PS=褲合身 RS=褲襠
    #               SA=剪接線_上身類 SB=剪接線_下身類 SR=裙合身 SS=脅邊
    #               ST=肩帶 TH=拇指洞
    ZH_ALIASES = {
        "脇邊": "SS",      # 脅邊 variant character (脇=脅) → SS 脅邊
        "前襟": "PL",      # 門襟 alias
        "前拉鍊": "ZP",    # 拉鏈 alias
        "滾邊": "NT",      # 領貼條 / binding tape
        "腰線": "WB",      # 腰頭 alias
        "車縫(通則)": "OT", # 通用車線 → OT 其它
        "剪接線": "SS",    # 接合線（無上下分時）→ SS 脅邊
        "褲襠": "RS",      # 股下/crotch → RS 褲襠 (same as standard)
        # Style guide Part C1 additions
        "袖襱": "AE",       # Armhole per style guide
        "袖圍": "AH",
        "袖衩": "SP",       # Sleeve placket
        "肩帶": "ST",       # Strap
        "抽繩": "DC",       # Drawcord
        "裙合身": "SR",     # Skirt fit
        "帽子": "HD",       # Hood
        "裙擺": "BM",       # Skirt hem
        "前立": "PL",       # Fly/placket (bottoms)
    }
    for zh, code in ZH_ALIASES.items():
        if zh not in out:  # don't override standard names
            out[zh] = code
    return out


def iso_is_valid(iso) -> bool:
    """ISO codes are numeric (e.g. '301', '406', '514+605'). Reject typos like 'ISO301'."""
    if not iso:
        return False
    return bool(re.fullmatch(r"\d+(\+\d+)?", str(iso)))


def recipe_key_from_filename(fname: str):
    """recipe_WOMENS_SWIMWEAR_TOP_SWIM.json → (WOMENS, SWIMWEAR, TOP, SWIM).
    Filename format: recipe_<GENDER>_<DEPT>_<GT>_<IT*>.json (IT may contain underscores).
    We prefer to read the in-file fields (gender/department/garment_type/item_type).
    This function is only used as a fallback.
    """
    stem = fname.removesuffix(".json").removeprefix("recipe_")
    parts = stem.split("_")
    if len(parts) < 4:
        return None
    gender, dept, gt = parts[0], parts[1], parts[2]
    it = "_".join(parts[3:])
    return gender, dept, gt, it


def dist_dict_to_list(dist: dict, n_total: int):
    """Convert a pct-dict ({iso: 0.69}) or a count-dict ({iso: 12}) to the
    master schema [{iso, n, pct}]. Auto-detects which: if sum > 1.5, treat as counts.
    """
    if not dist:
        return []
    total = sum(dist.values())
    as_counts = total > 1.5 or all(isinstance(v, int) for v in dist.values())
    items = []
    for iso, v in dist.items():
        if not iso_is_valid(iso):
            GATE.a_iso_rejected[str(iso)] += 1
            continue
        if as_counts:
            n = int(v)
            pct = (v / total * 100.0) if total > 0 else 0.0
        else:
            pct = v * 100.0
            n = int(round(v * n_total)) if n_total else 0
        items.append({"iso": iso, "n": n, "pct": round(pct, 1)})
    items.sort(key=lambda x: -x["pct"])
    return items


def methods_dict_to_list(methods: dict):
    if not methods:
        return []
    total = sum(methods.values()) or 1
    out = [{"name": name, "n": int(n), "pct": round(n / total * 100.0, 1)}
           for name, n in methods.items()]
    out.sort(key=lambda x: -x["pct"])
    return out


def build_from_recipes(recipes_dir: Path, zh_to_l1: dict, warns: list):
    """Produce same_sub entries from the 71 recipe files."""
    entries = []
    processed = 0
    skipped_zones = 0
    for f in sorted(recipes_dir.glob("recipe_*.json")):
        try:
            r = load_json(f)
        except Exception as e:
            warns.append(f"recipe {f.name}: failed to parse ({e})")
            GATE.b_recipe_parse.append((f.name, str(e)))
            continue
        processed += 1
        gender = norm(r.get("gender"))
        dept = norm(r.get("department"))
        gt = norm(r.get("garment_type") or r.get("gt"))
        it = norm(r.get("item_type") or r.get("it"))
        if not (gender and dept and gt and it):
            warns.append(f"recipe {f.name}: missing key fields")
            GATE.a_recipe_missing_fields.append(f.name)
            continue
        for zh_zone, zd in (r.get("zones") or {}).items():
            l1 = zh_to_l1.get(zh_zone)
            if not l1:
                warns.append(f"recipe {f.name}: unknown zone zh {zh_zone!r}")
                GATE.a_zone_recipe[zh_zone] += 1
                skipped_zones += 1
                continue
            dist = zd.get("iso_distribution") or {}
            n_obs = zd.get("n_observations") or 0
            iso_list = dist_dict_to_list(dist, n_obs)
            if not iso_list:
                # zone has no ISO — skip (methods-only zones aren't part of recipes data)
                continue
            entries.append({
                "key": {"gender": gender, "dept": dept, "gt": gt, "it": it, "l1": l1},
                "aggregation_level": "same_sub",
                "source": "recipe",
                "n_total": int(n_obs),
                "iso_distribution": iso_list,
                "methods": [],
            })
    return entries, {"files_processed": processed, "skipped_zones": skipped_zones}


def build_from_v43(v43):
    entries = []
    for e in v43.get("entries") or []:
        l1 = e.get("l1_code")
        if not l1:
            continue
        n_total = int(e.get("n_designs") or 0)
        iso_list = dist_dict_to_list(e.get("iso_distribution") or {}, n_total)
        if not iso_list:
            # fallback: use primary iso with pct from iso_pct
            iso = e.get("iso")
            if iso_is_valid(iso):
                pct_val = float(e.get("iso_pct") or 1.0)
                iso_list = [{"iso": iso, "n": n_total, "pct": round(pct_val * 100.0, 1)}]
        if not iso_list:
            continue
        entries.append({
            "key": {
                "gender": norm(e.get("gender")),
                "dept": norm(e.get("department")),
                "gt": norm(e.get("gt")),
                "it": None,
                "l1": l1,
            },
            "aggregation_level": "same_gt",
            "source": "v4.3",
            "n_total": n_total,
            "iso_distribution": iso_list,
            "methods": [],
        })
    return entries


def build_from_v4(v4):
    entries = []
    for e in v4.get("entries") or []:
        l1 = e.get("l1_code")
        if not l1:
            continue
        iso = e.get("iso")
        if not iso_is_valid(iso):
            GATE.a_iso_rejected[str(iso)] += 1
            continue
        votes = e.get("pptx_2025_votes") or {}
        n_votes_total = sum(votes.values())
        # Ensure primary iso is in the distribution even if no votes
        if votes:
            dist = dict(votes)
            dist.setdefault(iso, 0)  # primary may be 0 votes but still recommended
            iso_list = dist_dict_to_list(dist, n_votes_total)
            # promote primary to top regardless of vote rank (it's the curated pick)
            primary_idx = next((i for i, x in enumerate(iso_list) if x["iso"] == iso), -1)
            if primary_idx > 0:
                iso_list.insert(0, iso_list.pop(primary_idx))
            n_total = int(e.get("pptx_2025_designs") or n_votes_total or 1)
        else:
            iso_list = [{"iso": iso, "n": 1, "pct": 100.0}]
            n_total = 1
        entries.append({
            "key": {
                "gender": None,
                "dept": norm(e.get("department")),
                "gt": norm(e.get("gt")),
                "it": None,
                "l1": l1,
                "fabric": norm(e.get("fabric")),
            },
            "aggregation_level": "general",
            "source": "v4",
            "n_total": n_total,
            "iso_distribution": iso_list,
            "methods": [],
        })
    return entries


def build_from_bridge(bridge, zh_to_l1, warns):
    """Produce cross_design entries from bridge v6.

    Bridge has no l1_code in zones (only Chinese zone names), so we reverse-lookup
    via l1_standard_38.zh. If a zone has no iso_codes (PPTX-only methods), we still
    emit an entry with iso_distribution=[] so the viewer can pull methods from it,
    but the viewer will skip it as an ISO source.
    """
    entries = []
    zone_count = 0
    no_iso_count = 0
    skipped_zones = 0
    for gt_raw, gtd in (bridge.get("bridges") or {}).items():
        gt = norm(gt_raw)
        if not gt or gt == "UNKNOWN":
            continue
        for zh_zone, zd in (gtd.get("zones") or {}).items():
            l1 = zh_to_l1.get(zh_zone)
            if not l1:
                warns.append(f"bridge {gt_raw}: unknown zone zh {zh_zone!r}")
                GATE.a_zone_bridge[zh_zone] += 1
                skipped_zones += 1
                continue
            zone_count += 1
            iso_codes = zd.get("iso_codes") or {}
            methods = zd.get("methods") or {}
            n_total = int(zd.get("count") or 0)
            iso_list = dist_dict_to_list(iso_codes, n_total)
            methods_list = methods_dict_to_list(methods)
            if not iso_list:
                no_iso_count += 1
            entries.append({
                "key": {
                    "gender": None,
                    "dept": None,
                    "gt": gt,
                    "it": None,
                    "l1": l1,
                },
                "aggregation_level": "cross_design",
                "source": "bridge",
                "n_total": n_total,
                "iso_distribution": iso_list,
                "methods": methods_list,
            })
    return entries, {"zone_count": zone_count, "no_iso_count": no_iso_count, "skipped_zones": skipped_zones}


def load_bucket_taxonomy(path: Path) -> dict:
    """Load bucket_taxonomy.json → {BUCKET_UPPER: {gender: [...], dept: [...], gt: [...]}}.

    Merges TWO sections in v4 schema:
      1. `buckets` — v4 4-dim scalar values (gender="WOMEN", dept="ACTIVE", ...);
         normalised to single-element lists for cascade compatibility.
      2. `legacy_buckets` — old 3-dim alias (gender=[...], dept=[...], gt=[...])
         for facts/consensus rows that pre-date the v4 master schema. Carries
         `_legacy_3dim: true` flag for downstream observability.

    Returns a single dict keyed by uppercase bucket name; cascade code stays
    schema-agnostic (always sees lists).
    """
    raw = load_json(path)
    out = {}

    # Section 1: v4 4-dim buckets (scalar → list[1])
    for k, v in (raw.get("buckets") or {}).items():
        norm_v = {}
        for dim in ("gender", "dept", "gt", "it"):
            val = v.get(dim)
            if val is None:
                norm_v[dim] = [None]
            elif isinstance(val, list):
                norm_v[dim] = val
            else:
                norm_v[dim] = [val]
        # carry-through extras (n_designs / fabric_split / top_clients / use_for)
        for extra in ("n_designs", "fabric_split", "top_clients", "use_for"):
            if extra in v:
                norm_v[extra] = v[extra]
        out[k.upper()] = norm_v

    # Section 2: legacy_buckets (already list-shaped, just upper-key)
    for k, v in (raw.get("legacy_buckets") or {}).items():
        out[k.upper()] = v

    return out


def build_from_consensus(consensus_path: Path, bucket_tax: dict, warns: list):
    """Produce same_bucket entries from consensus_v1/entries.jsonl.

    Each consensus entry has key = {bucket, fingerprint, l1}.
    We expand bucket → gender/dept/gt via bucket_taxonomy.json so the
    cascade viewer can match on the same key structure as other layers.
    Entries without ISO are still emitted (methods-only) for completeness.
    """
    entries = []
    loaded = 0
    no_taxonomy = 0
    with open(consensus_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            loaded += 1
            key = row.get("key") or {}
            bucket = key.get("bucket", "").upper()
            fingerprint = key.get("fingerprint")
            l1 = key.get("l1")
            if not (bucket and l1):
                warns.append(f"consensus: missing bucket or l1 in row {loaded}")
                GATE.a_consensus_missing += 1
                continue
            tax = bucket_tax.get(bucket)
            if not tax:
                warns.append(f"consensus: no taxonomy for bucket {bucket!r}")
                GATE.b_bucket_consensus[bucket] += 1
                no_taxonomy += 1
                # Still emit with None gender/dept/gt so data isn't lost
                tax = {"gender": [None], "dept": [None], "gt": [None]}
            # Expand: one consensus row → one entry per (gender, dept, gt) combo
            genders = tax.get("gender") or [None]
            depts = tax.get("dept") or [None]
            gts = tax.get("gt") or [None]
            for g in genders:
                for d in depts:
                    for gt in gts:
                        entries.append({
                            "key": {
                                "gender": norm(g),
                                "dept": norm(d),
                                "gt": norm(gt),
                                "it": norm(fingerprint),  # fingerprint maps to item_type slot
                                "l1": l1,
                            },
                            "aggregation_level": "same_bucket",
                            "source": "consensus_v1",
                            "n_total": int(row.get("n_total") or 0),
                            "iso_distribution": row.get("iso_distribution") or [],
                            "methods": row.get("methods") or [],
                        })
    return entries, {"loaded": loaded, "no_taxonomy": no_taxonomy}


def build_from_m7_pullon(path: Path, bucket_tax: dict, warns: list):
    """Produce same_bucket entries from data/ingest/m7_pullon/entries.jsonl.

    M7 PullOn pipeline (聚陽 Windows) source — pre-aggregated 5-dim entries
    (gender × dept × gt × it × l1) with iso/methods/by_client/IE seconds.
    Schema is fully v4-aligned (no legacy_bucket fan-out needed).

    Cascade level: same_bucket (parallel to consensus_v1 / facts_agg).

    Args:
        path: data/ingest/m7_pullon/entries.jsonl (graceful when missing)
        bucket_tax: not used here (m7_pullon entries already carry full key)
        warns: warning accumulator

    Returns:
        list of entries with v4 5+1-dim key (gender/dept/gt/it/fabric/l1)
    """
    entries = []
    if not path.exists():
        return entries, {"loaded": 0, "skipped": 0}

    n_loaded = 0
    n_skipped = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                n_skipped += 1
                continue

            k = e.get("key", {})
            # m7_pullon master key is 6-dim (gender/dept/gt/it/fabric/l1)
            # platform schema is 5-dim — fabric goes top-level, not in key
            platform_key = {
                "gender": norm(k.get("gender")),
                "dept": norm(k.get("dept")),
                "gt": norm(k.get("gt")),
                "it": norm(k.get("it")),
                "l1": k.get("l1") or k.get("l1_code"),
            }
            if not all(v for v in platform_key.values() if v is not None):
                n_skipped += 1
                continue
            if platform_key["l1"] not in L1_ACCEPTED:
                # Treat like aggregate_facts_to_entries: track in B-tier
                GATE.b_l1_not_38[platform_key["l1"] or "<empty>"] += 1
                n_skipped += 1
                continue

            entries.append({
                "key": platform_key,
                "fabric": norm(k.get("fabric")),  # top-level (parallel to v4 source)
                "aggregation_level": "same_bucket",
                "source": "m7_pullon",
                "n_total": int(e.get("n_total") or 0),
                "iso_distribution": e.get("iso_distribution") or [],
                "methods": e.get("methods") or [],
                "client_distribution": e.get("client_distribution") or [],
                "confidence": e.get("confidence", "medium"),
                # m7_pullon-specific (preserved for derive_view_by_client.py future use)
                "_m7_by_client": e.get("by_client"),
                "_m7_design_ids": e.get("design_ids", []),
                "_m7_ie_total_seconds": e.get("ie_total_seconds"),
            })
            n_loaded += 1

    return entries, {"loaded": n_loaded, "skipped": n_skipped}


def aggregate_facts_to_entries(
    ingest_dir: Path,
    bucket_tax: dict,
    consensus_keys: set,
    warns: list,
):
    """Aggregate facts.jsonl files → same_bucket entries.

    Scans data/ingest/*/facts.jsonl.  Groups by (BUCKET, l1_code) and computes
    iso_distribution (numeric ISO only) + methods.  Skips:
      - l1_code not in L1_ACCEPTED (L1_VALID_38 + L1_SPECIAL={_DEFAULT})
      - bucket not in bucket_taxonomy (seasonal codes, empty, temp labels)
      - (bucket, l1) keys already covered by consensus_v1 (consensus wins)

    L1 "_DEFAULT" passes through and aggregates normally — it represents the
    techpack's "all body seams are <ISO>" catch-all rule and is valuable data,
    not a violation.  Frontend can use l1=_DEFAULT entries as final fallback
    when per-L1 lookups miss.
    """
    from collections import defaultdict

    groups: dict[tuple, dict] = {}  # (bucket_upper, l1) → {isos, methods, designs, n}
    total_rows = 0
    skipped_l1 = 0
    skipped_bucket = 0
    skipped_consensus = 0

    valid_buckets_upper = {k.upper() for k in bucket_tax}

    for facts_path in sorted(ingest_dir.glob("*/facts.jsonl")):
        with open(facts_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total_rows += 1
                row = json.loads(line)
                l1 = row.get("l1_code", "")
                if l1 not in L1_ACCEPTED:
                    GATE.b_l1_not_38[l1 or "<empty>"] += 1
                    skipped_l1 += 1
                    continue
                if l1 in L1_SPECIAL:
                    # Legit catch-all rule — track in A-tier for visibility
                    # (grouped by ISO value), then let it aggregate like any L1.
                    iso_raw = row.get("iso", "")
                    if iso_raw:
                        GATE.a_default_rules[str(iso_raw)] += 1
                bucket_raw = row.get("bucket", "").upper()
                if bucket_raw not in valid_buckets_upper:
                    GATE.b_bucket_facts[bucket_raw or "<empty>"] += 1
                    skipped_bucket += 1
                    continue
                if (bucket_raw, l1) in consensus_keys:
                    skipped_consensus += 1
                    continue

                gkey = (bucket_raw, l1)
                if gkey not in groups:
                    groups[gkey] = {"isos": defaultdict(int), "methods": defaultdict(int),
                                   "designs": set(), "n": 0}
                g = groups[gkey]
                g["n"] += 1
                g["designs"].add(row.get("design_id", ""))
                iso = row.get("iso", "")
                if iso and re.fullmatch(r"\d+(\+\d+)?", iso):
                    g["isos"][iso] += 1
                method = row.get("method", "")
                if method:
                    g["methods"][method] += 1

    # Convert groups → entries (expand via taxonomy)
    entries = []
    for (bucket_upper, l1), g in sorted(groups.items()):
        n_total = g["n"]
        iso_list = dist_dict_to_list(dict(g["isos"]), n_total)
        methods_list = methods_dict_to_list(dict(g["methods"]))

        tax = bucket_tax.get(bucket_upper)
        if not tax:
            warns.append(f"facts-agg: no taxonomy for bucket {bucket_upper!r}")
            tax = {"gender": [None], "dept": [None], "gt": [None]}

        # Determine fingerprint: use the first fingerprint key from taxonomy
        # that matches, or None. Facts don't carry fingerprint directly.
        fp = None  # facts don't have fingerprint; same_bucket level is bucket×l1

        for g_val in (tax.get("gender") or [None]):
            for d_val in (tax.get("dept") or [None]):
                for gt_val in (tax.get("gt") or [None]):
                    entries.append({
                        "key": {
                            "gender": norm(g_val),
                            "dept": norm(d_val),
                            "gt": norm(gt_val),
                            "it": None,
                            "l1": l1,
                        },
                        "aggregation_level": "same_bucket",
                        "source": "facts_agg",
                        "n_total": n_total,
                        "iso_distribution": iso_list,
                        "methods": methods_list,
                    })

    stats = {
        "total_rows": total_rows,
        "skipped_l1": skipped_l1,
        "skipped_bucket": skipped_bucket,
        "skipped_consensus_overlap": skipped_consensus,
        "groups": len(groups),
        "entries": len(entries),
        "designs": len({d for g in groups.values() for d in g["designs"]}),
    }
    return entries, stats


def main():
    parser = argparse.ArgumentParser(
        description="Build data/runtime/recipes_master.json + data/master.jsonl from 5 construction handbooks.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any B-tier (silent-data-loss) violation is detected: "
             "L1 not in 38 standard / bucket not in taxonomy / recipe parse fail.",
    )
    parser.add_argument(
        "--strict-all",
        action="store_true",
        help="Exit 1 on A-tier OR B-tier violations. Reserved for future use "
             "once A-tier backlog (zh-zone aliases, iso rejects, …) is drained.",
    )
    args = parser.parse_args()

    v43 = load_json(V43_PATH)
    v4 = load_json(V4_PATH)
    bridge = load_json(BRIDGE_PATH)

    # 1. l1_standard_38 → also write as standalone file for the viewer
    l1_std = build_l1_standard_38(v43)
    OUT_L1_STD.write_text(json.dumps(l1_std, ensure_ascii=False, indent=2), encoding="utf-8")
    zh_to_l1 = build_zh_to_l1(l1_std)
    print(f"[l1_standard_38] {len(l1_std['codes'])} codes → {OUT_L1_STD.name}", file=sys.stderr)

    warns = []

    recipe_entries, recipe_stats = build_from_recipes(RECIPES_DIR, zh_to_l1, warns)

    # same_bucket layer from consensus + facts aggregation (if available)
    consensus_entries = []
    consensus_stats = {"loaded": 0, "no_taxonomy": 0}
    facts_entries = []
    facts_stats = {"total_rows": 0, "groups": 0, "entries": 0, "designs": 0,
                   "skipped_l1": 0, "skipped_bucket": 0, "skipped_consensus_overlap": 0}
    bucket_tax = {}

    if BUCKET_TAX_PATH.exists():
        bucket_tax = load_bucket_taxonomy(BUCKET_TAX_PATH)

    if CONSENSUS_PATH.exists() and bucket_tax:
        consensus_entries, consensus_stats = build_from_consensus(
            CONSENSUS_PATH, bucket_tax, warns
        )
        print(f"[consensus] {consensus_stats['loaded']} rows → {len(consensus_entries)} entries", file=sys.stderr)
    else:
        print(f"[consensus] skipped (files not found)", file=sys.stderr)

    # Collect consensus (bucket, l1) keys for dedup
    consensus_keys: set[tuple[str, str]] = set()
    if CONSENSUS_PATH.exists():
        with open(CONSENSUS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                k = row.get("key") or {}
                b = k.get("bucket", "").upper()
                l1 = k.get("l1", "")
                if b and l1:
                    consensus_keys.add((b, l1))

    # Aggregate facts.jsonl → same_bucket entries (skip consensus overlaps)
    if INGEST_DIR.exists() and bucket_tax:
        facts_entries, facts_stats = aggregate_facts_to_entries(
            INGEST_DIR, bucket_tax, consensus_keys, warns
        )
        print(f"[facts_agg] {facts_stats['total_rows']} rows → {facts_stats['groups']} groups → "
              f"{len(facts_entries)} entries ({facts_stats['designs']} designs, "
              f"skipped: {facts_stats['skipped_consensus_overlap']} consensus overlap / "
              f"{facts_stats['skipped_l1']} bad L1 / {facts_stats['skipped_bucket']} bad bucket)",
              file=sys.stderr)

    v43_entries = build_from_v43(v43)
    v4_entries = build_from_v4(v4)
    bridge_entries, bridge_stats = build_from_bridge(bridge, zh_to_l1, warns)

    # M7 PullOn source (聚陽 5-dim ground truth, graceful when absent)
    m7_entries, m7_stats = build_from_m7_pullon(M7_PULLON_PATH, bucket_tax, warns)
    if m7_stats["loaded"]:
        print(f"[m7_pullon] {m7_stats['loaded']} entries loaded "
              f"({m7_stats['skipped']} skipped)", file=sys.stderr)
    else:
        print(f"[m7_pullon] not found, skipped (graceful)", file=sys.stderr)

    # Cascade order: same_sub → same_bucket (consensus + facts_agg + m7_pullon)
    #                → same_gt → general → cross_design
    all_entries = (recipe_entries + consensus_entries + facts_entries
                   + m7_entries + v43_entries + v4_entries + bridge_entries)

    recipe_files = sorted(f.name for f in RECIPES_DIR.glob("recipe_*.json"))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_versions": {
            "v4.3": str(V43_PATH.relative_to(REPO_ROOT)),
            "v4": str(V4_PATH.relative_to(REPO_ROOT)),
            "bridge": str(BRIDGE_PATH.relative_to(REPO_ROOT)),
            "recipes": recipe_files,
            "consensus": str(CONSENSUS_PATH) if CONSENSUS_PATH.exists() else None,
            "facts": sorted(str(p) for p in INGEST_DIR.glob("*/facts.jsonl")) if INGEST_DIR.exists() else [],
            "bucket_taxonomy": str(BUCKET_TAX_PATH) if BUCKET_TAX_PATH.exists() else None,
            "m7_pullon": str(M7_PULLON_PATH) if M7_PULLON_PATH.exists() else None,
        },
        "stats": {
            "same_sub": len(recipe_entries),
            "same_bucket_consensus": len(consensus_entries),
            "same_bucket_facts_agg": len(facts_entries),
            "same_bucket_m7_pullon": len(m7_entries),
            "same_bucket_total": len(consensus_entries) + len(facts_entries) + len(m7_entries),
            "same_gt": len(v43_entries),
            "general": len(v4_entries),
            "cross_design": len(bridge_entries),
            "total": len(all_entries),
            "recipe_files_processed": recipe_stats["files_processed"],
            "consensus_rows_loaded": consensus_stats["loaded"],
            "facts_agg_rows": facts_stats["total_rows"],
            "facts_agg_groups": facts_stats["groups"],
            "facts_agg_designs": facts_stats["designs"],
            "bridge_zones": bridge_stats["zone_count"],
            "bridge_zones_no_iso": bridge_stats["no_iso_count"],
            "unknown_zone_warnings": len([w for w in warns if "unknown zone" in w]),
        },
        "entries": all_entries,
    }

    OUT_MASTER.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Phase 2.1: also emit master.jsonl as the canonical "single source of truth"
    # for derive views (View A/B/C — see docs/architecture/PHASE2_DERIVE_VIEWS_SPEC.md).
    # One line per entry, keeps `_m7_*` internal fields that View A strips.
    with open(OUT_MASTER_JSONL, "w", encoding="utf-8") as f:
        for entry in all_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[master.jsonl] {len(all_entries)} entries → {OUT_MASTER_JSONL.name}", file=sys.stderr)

    print("--- stats ---", file=sys.stderr)
    for k, v in out["stats"].items():
        print(f"  {k}: {v}", file=sys.stderr)
    if warns:
        print("--- warnings ---", file=sys.stderr)
        for w in warns[:50]:
            print(f"  {w}", file=sys.stderr)
        if len(warns) > 50:
            print(f"  ... and {len(warns) - 50} more", file=sys.stderr)
    print(f"[recipes_master] {len(all_entries)} entries → {OUT_MASTER.name}", file=sys.stderr)

    # ── Gate Report ──
    # Always print (unconditional observability). Exit code depends on flags.
    gate_text = GATE.format()
    print("\n" + gate_text, file=sys.stderr)

    # Also surface in GitHub Actions run page (Summary tab, first screen)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as sf:
                sf.write("\n## Gate Report — `recipes_master`\n\n")
                sf.write("```\n" + gate_text + "\n```\n")
        except Exception as e:
            print(f"[gate] failed to write GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)

    # Exit decision
    b_total = GATE.b_total()
    a_total = GATE.a_total()
    if args.strict_all and (b_total + a_total) > 0:
        print(
            f"\n🛑 STRICT-ALL MODE BLOCKED — B:{b_total} + A:{a_total} "
            f"件違規\n   see Gate Report above for details.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.strict and b_total > 0:
        hints = []
        if sum(GATE.b_l1_not_38.values()):
            hints.append(f"• {sum(GATE.b_l1_not_38.values())} 筆 L1 錯 → 檢查 extract 的 L1 分類")
        if sum(GATE.b_bucket_consensus.values()) or sum(GATE.b_bucket_facts.values()):
            missing = set(GATE.b_bucket_consensus) | set(GATE.b_bucket_facts)
            hints.append(f"• {len(missing)} 個 bucket 未登錄 → 加進 data/bucket_taxonomy.json")
        if GATE.b_recipe_parse:
            hints.append(f"• {len(GATE.b_recipe_parse)} 檔 recipe 語法壞 → 開檔修 JSON")
        print(f"\n🛑 STRICT MODE BLOCKED — {b_total} 件 B-tier 違規", file=sys.stderr)
        if hints:
            print("   修法建議:", file=sys.stderr)
            for h in hints:
                print(f"     {h}", file=sys.stderr)
        print("   修完 commit 重推即可觸發 Actions 重跑。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

