"""
Derive data/runtime/code_manifest.json — flat list of browsable repo files
for the in-app GitHub-style code browser (index.html → 管理 ▸ Code 瀏覽).

Curated to expose human-readable artefacts only:
  - runtime JSON, spec/SOP markdown, build scripts, recipe / pom rule / Bible JSON,
    path2_universal docs, root README/CLAUDE/MK_METADATA, vercel.json
Skipped:
  - binaries (LOGO.png), ingest staging, M7_Pipeline outputs, .git, node_modules

Output shape:
  {
    "generated_at": "...Z",
    "files": [
      {"path": "data/runtime/brands.json", "size": 1827, "ext": "json"},
      ...
    ]
  }
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT = REPO_ROOT / "data" / "runtime" / "code_manifest.json"

# (glob, recursive) pairs, relative to REPO_ROOT.
PATTERNS: list[tuple[str, bool]] = [
    ("data/runtime/*.json", False),
    ("docs/spec/*.md", False),
    ("docs/sop/*.md", False),
    ("path2_universal/*", False),
    ("l2_l3_ie/*.json", False),
    ("pom_rules/*.json", False),
    ("recipes/*.json", False),
    ("scripts/core/*.py", False),
    ("scripts/lib/*.py", False),
    ("star_schema/scripts/*.py", False),
    ("api/*.js", False),
    ("*.md", False),
    ("vercel.json", False),
    (".gitignore", False),
]

# Hard cap — files above this are listed but flagged so the UI can warn before fetching.
LARGE_THRESHOLD = 1_000_000  # 1 MB


def main() -> None:
    seen: dict[str, dict] = {}
    for pattern, _ in PATTERNS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if not p.is_file():
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel in seen:
                continue
            size = p.stat().st_size
            seen[rel] = {
                "path": rel,
                "size": size,
                "ext": p.suffix.lstrip(".").lower() or "txt",
                **({"large": True} if size > LARGE_THRESHOLD else {}),
            }

    files = sorted(seen.values(), key=lambda f: f["path"])

    out = {
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "large_threshold_bytes": LARGE_THRESHOLD,
        "files": files,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"files: {len(files)} ({sum(f['size'] for f in files):,} bytes total)")
    print(f"Output: {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
