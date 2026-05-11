#!/usr/bin/env python3
"""Build l2_l3_ie/*.json (38 L1 parts + _index.json) from 聚陽 IE xlsx.

Source: ``五階層展開項目_20260402.xlsx`` (single sheet, ~200K rows).

xlsx column layout (header row 0):
  0 部位 (L1 Chinese name, e.g. "袖孔" / "Keyhole")
  1 零件 (L2 component name)
  2 形狀設計 (L3 shape)
  3 工法描述 (L4 method description)
  4 細工段 (L5 step name)
  5 主副 (main/sub — always "主" or "副")
  6 等級 (grade — A/B/C/D/E)
  7 Woven_Knit (fabric type)
  8 Second (IE seconds — number)
  9 有無圖片 (ignored)
 10 圖片連結 (ignored)

Output per L1 code::

    l2_l3_ie/<CODE>.json = {
      "l1": "<Chinese name>",
      "code": "<CODE>",
      "knit": [{"l2": ..., "shapes": [{"l3": ..., "methods": [{"l4": ..., "steps": [[step, grade, seconds, main_sub], ...]}]}]}],
      "woven": [... same shape ...]
    }

And ``l2_l3_ie/_index.json = {"version", "note", "total_size", "parts": {code: {l1, size}}}``.

L1-name → L1-code mapping comes from ``L2_代號中文對照表.xlsx`` (the registry
file that :mod:`build_l2_visual_guide` already uses). Rows whose ``部位``
value doesn't resolve to a known code are reported and skipped.

Usage::

  python3 scripts/build_bible_skeleton.py                               # use repo defaults
  python3 scripts/build_bible_skeleton.py --source path/to/五階層展開項目.xlsx
  python3 scripts/build_bible_skeleton.py --dry-run                     # print stats, don't write
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import OrderedDict, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_XLSX = REPO_ROOT / "data" / "source" / "L2_代號中文對照表.xlsx"
SOURCE_DIR = REPO_ROOT / "data" / "source"
OUT_DIR = REPO_ROOT / "l2_l3_ie"


def find_latest_source() -> Path | None:
    """Pick the newest ``data/source/五階層展開項目_YYYYMMDD.xlsx``.

    Filename date suffix wins over mtime (uploader can commit files out of
    chronological order). Falls back to mtime if no file matches the date
    pattern.
    """
    candidates = sorted(SOURCE_DIR.glob("五階層展開項目_*.xlsx"))
    if not candidates:
        return None

    import re
    date_re = re.compile(r"五階層展開項目_(\d{8})\.xlsx$")
    dated = []
    undated = []
    for p in candidates:
        m = date_re.search(p.name)
        if m:
            dated.append((m.group(1), p))
        else:
            undated.append(p)
    if dated:
        dated.sort(key=lambda kv: kv[0])
        return dated[-1][1]
    undated.sort(key=lambda p: p.stat().st_mtime)
    return undated[-1]

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ─── xlsx stdlib reader ───────────────────────────────────────────────

def _read_shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    out = []
    for si in root.findall(f"{NS}si"):
        out.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    return out


def _cell_value(c: ET.Element, shared: list[str]):
    t = c.get("t", "n")
    if t == "inlineStr":
        is_el = c.find(f"{NS}is")
        return "".join(tt.text or "" for tt in is_el.iter(f"{NS}t")) if is_el is not None else None
    v = c.find(f"{NS}v")
    if v is None or v.text is None:
        return None
    raw = v.text
    if t == "s":
        return shared[int(raw)] if raw.isdigit() else raw
    if t in ("str",):
        return raw
    if t == "b":
        return bool(int(raw))
    try:
        f = float(raw)
        return int(f) if f.is_integer() else f
    except ValueError:
        return raw


def _stream_shared_strings(z: zipfile.ZipFile) -> list[str]:
    """Memory-efficient shared strings reader (uses iterparse).

    The 20260507 xlsx has 30K+ shared strings; loading via fromstring OOMs in
    constrained environments. iterparse + .clear() keeps peak memory low.
    """
    out: list[str] = []
    try:
        f = z.open("xl/sharedStrings.xml")
    except KeyError:
        return out
    with f:
        for _ev, el in ET.iterparse(f, events=("end",)):
            if el.tag == f"{NS}si":
                out.append("".join(t.text or "" for t in el.iter(f"{NS}t")))
                el.clear()
    return out


def _resolve_sheet_xml(z: zipfile.ZipFile) -> str:
    """Pick the sheet that holds the 5-level data.

    The 20260402 xlsx has the data in sheet1.  The 20260507 xlsx moves it to
    sheet2 (sheet1 = `語系資料` translation table; sheet2 = `全部五階層`).
    Resolution rule:
      1. Read workbook.xml; find sheet whose name contains "五階層"
         and resolve to its sheet*.xml path via workbook rels.
      2. Fall back to sheet1.xml if rule 1 doesn't match.
    """
    try:
        wb_xml = z.read("xl/workbook.xml")
    except KeyError:
        return "xl/worksheets/sheet1.xml"
    rels_xml = b""
    try:
        rels_xml = z.read("xl/_rels/workbook.xml.rels")
    except KeyError:
        pass

    wb_root = ET.fromstring(wb_xml)
    sheets = wb_root.find(f"{NS}sheets")
    if sheets is None:
        return "xl/worksheets/sheet1.xml"

    # rId → sheet*.xml target
    rid_to_target: dict[str, str] = {}
    if rels_xml:
        REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        rels_root = ET.fromstring(rels_xml)
        for r in rels_root.findall(f"{REL_NS}Relationship"):
            rid_to_target[r.attrib["Id"]] = r.attrib["Target"]

    REL_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    candidate_idx = None  # fallback if no name match
    for i, s in enumerate(sheets.findall(f"{NS}sheet")):
        name = s.attrib.get("name", "")
        rid = s.attrib.get(f"{REL_NS_R}id", "")
        target = rid_to_target.get(rid, f"worksheets/sheet{i+1}.xml")
        full = "xl/" + target.lstrip("/")
        if "五階層" in name:
            return full
        if candidate_idx is None:
            candidate_idx = full
    return candidate_idx or "xl/worksheets/sheet1.xml"


def iter_rows(xlsx_path: Path):
    """Yield each row as a list of cell values (strings / numbers / None).

    For very large sheets (20260507 sheet2 = 329 MB uncompressed), Python's
    zipfile streaming via z.open() can raise BadZipFile CRC-32 errors when
    iterparse stops mid-stream. We extract the sheet to a temp file first,
    then iterparse from disk — adds ~1s but avoids the corruption false alarm.
    """
    import tempfile, os
    with zipfile.ZipFile(xlsx_path) as z:
        shared = _stream_shared_strings(z)
        sheet_path = _resolve_sheet_xml(z)
        # Extract sheet to temp file (bypasses streaming CRC issue on large sheets)
        tmpdir = tempfile.mkdtemp(prefix="l2l3ie_")
        try:
            extracted = z.extract(sheet_path, tmpdir)
            with open(extracted, "rb") as f:
                for _ev, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == f"{NS}row":
                        yield [_cell_value(c, shared) for c in elem.findall(f"{NS}c")]
                        elem.clear()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ─── L1 name → code registry ──────────────────────────────────────────

def load_name_to_code(registry_path: Path) -> dict[str, str]:
    name_to_code: dict[str, str] = {}
    if not registry_path.exists():
        sys.stderr.write(f"warning: registry not found: {registry_path}\n")
        return name_to_code
    with zipfile.ZipFile(registry_path) as z:
        shared = _read_shared_strings(z)
        sheet_xml = z.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    for i, row in enumerate(root.findall(f".//{NS}row")):
        if i == 0:
            continue
        cells = [_cell_value(c, shared) for c in row.findall(f"{NS}c")]
        if len(cells) < 2:
            continue
        code, name = cells[0], cells[1]
        if code and name:
            name_to_code[str(name).strip()] = str(code).strip()
    return name_to_code


# ─── Builder ──────────────────────────────────────────────────────────

def _build_col_index(header: list) -> dict[str, int]:
    """Map header label → column index. Tolerates both 20260402 and 20260507
    layouts by name-matching:
      - 20260402: 部位/零件/形狀設計/工法描述/細工段/主副/等級/Woven_Knit/Second
      - 20260507: adds 尺寸 / 機種 (between Woven_Knit and Second), 圖片名字, *_Sort
    """
    idx: dict[str, int] = {}
    for i, h in enumerate(header):
        key = str(h or "").strip()
        if not key:
            continue
        idx[key] = i
    return idx


def build(source: Path, name_to_code: dict[str, str]):
    """Consume xlsx rows → per-code nested dicts.

    Returns (data, stats) where data is {code: {l1, code, knit, woven}}.
    Step tuple: [step, grade, sec, main_sub, machine?]  — machine appended
    when the source provides 機種 column (20260507+); 4-elem for older 20260402.
    """
    header_seen = False
    col: dict[str, int] = {}
    unknown_l1 = defaultdict(int)
    row_count = 0

    # per_code[code][fabric][l2][l3][l4] = [ [step, grade, sec, main_sub, ...], ... ]
    per_code: dict[str, dict[str, OrderedDict]] = {}
    l1_name_by_code: dict[str, str] = {}

    for row in iter_rows(source):
        if not header_seen:
            header_seen = True
            col = _build_col_index(row)
            continue

        def _at(name: str, fallback_idx: int):
            i = col.get(name, fallback_idx)
            return row[i] if i is not None and i < len(row) else None

        l1_name = str(_at("部位", 0) or "").strip()
        l2 = str(_at("零件", 1) or "").strip()
        l3 = str(_at("形狀設計", 2) or "").strip()
        l4 = str(_at("工法描述", 3) or "").strip()
        step = str(_at("細工段", 4) or "").strip()
        main_sub = str(_at("主副", 5) or "").strip()
        grade = str(_at("等級", 6) or "").strip()
        fabric = str(_at("Woven_Knit", 7) or "").strip().lower()
        machine = str(_at("機種", -1) or "").strip()  # 20260507+ column; "" for older
        sec = _at("Second", 8)
        if not l1_name:
            continue
        code = name_to_code.get(l1_name)
        if not code:
            unknown_l1[l1_name] += 1
            continue
        if fabric not in ("knit", "woven"):
            continue
        try:
            sec_val = float(sec) if sec is not None and sec != "" else None
        except (TypeError, ValueError):
            sec_val = None
        if sec_val is None:
            continue

        row_count += 1
        l1_name_by_code.setdefault(code, l1_name)

        by_fabric = per_code.setdefault(code, {"knit": OrderedDict(), "woven": OrderedDict()})
        l2_map: OrderedDict = by_fabric[fabric]
        l2_entry = l2_map.setdefault(l2, OrderedDict())
        l3_entry = l2_entry.setdefault(l3, OrderedDict())
        step_list = l3_entry.setdefault(l4, [])
        # Step tuple: [step, grade, sec, main_sub, machine?]
        # machine 留空 ("") 時不擴 5-elem,維持 20260402 backwards compat
        if machine:
            step_list.append([step, grade, sec_val, main_sub, machine])
        else:
            step_list.append([step, grade, sec_val, main_sub])

    # Convert nested OrderedDicts → list-of-dict shape that matches existing files.
    # Sort methods within each L3 by step count DESC (matches `_index.json`
    # note: "methods sorted by frequency desc").
    data: dict[str, dict] = {}
    for code, fabric_dict in per_code.items():
        out = {"l1": l1_name_by_code[code], "code": code, "knit": [], "woven": []}
        for fabric in ("knit", "woven"):
            for l2, shapes in fabric_dict[fabric].items():
                shape_list = []
                for l3, methods in shapes.items():
                    method_list = [{"l4": l4, "steps": steps} for l4, steps in methods.items()]
                    method_list.sort(key=lambda m: -len(m["steps"]))
                    shape_list.append({"l3": l3, "methods": method_list})
                out[fabric].append({"l2": l2, "shapes": shape_list})
        data[code] = out

    stats = {
        "rows_consumed": row_count,
        "codes_built": len(data),
        "unknown_l1_count": sum(unknown_l1.values()),
        "unknown_l1_samples": sorted(unknown_l1.items(), key=lambda kv: -kv[1])[:10],
    }
    return data, stats


def write_outputs(data: dict[str, dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for code, doc in data.items():
        path = out_dir / f"{code}.json"
        # Compact (no indent / no whitespace between separators) — matches the
        # existing files, keeps lazy-fetch payloads small.
        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        path.write_text(payload, encoding="utf-8")
        sizes[code] = len(payload.encode("utf-8"))
    # Re-build _index.json (preserve previous `version` / `note` if available).
    idx_path = out_dir / "_index.json"
    existing = {}
    if idx_path.exists():
        try:
            existing = json.loads(idx_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    idx = {
        "version": existing.get("version", "v2.0"),
        "note": existing.get("note", "L1→L2→L3→L4→L5; methods sorted by frequency desc"),
        "total_size": sum(sizes.values()),
        # Parts order follows xlsx encounter order (i.e. first-seen L1 name).
        "parts": {
            code: {"l1": data[code]["l1"], "size": sizes[code]}
            for code in data  # data is insertion-ordered from xlsx iteration
        },
    }
    idx_path.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=None,
                    help="xlsx path (default: newest data/source/五階層展開項目_YYYYMMDD.xlsx)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR,
                    help=f"output dir (default: {OUT_DIR})")
    ap.add_argument("--registry", type=Path, default=REGISTRY_XLSX,
                    help=f"L1 name→code registry xlsx (default: {REGISTRY_XLSX.name})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print stats, don't write files")
    args = ap.parse_args()

    source = args.source or find_latest_source()
    if source is None:
        sys.stderr.write(
            "error: no 五階層展開項目_*.xlsx found at repo root, "
            "and --source not given\n"
        )
        return 2
    if not source.exists():
        sys.stderr.write(f"error: source xlsx not found: {source}\n")
        return 2
    print(f"source: {source.name}")
    args.source = source

    name_to_code = load_name_to_code(args.registry)
    print(f"registry: {len(name_to_code)} L1 name→code entries from {args.registry.name}")

    data, stats = build(args.source, name_to_code)
    print(f"rows consumed: {stats['rows_consumed']}")
    print(f"codes built:   {stats['codes_built']}")
    if stats["unknown_l1_count"]:
        print(f"⚠ unknown L1 names skipped: {stats['unknown_l1_count']} rows")
        for name, n in stats["unknown_l1_samples"]:
            print(f"    {n:>6}  {name!r}")

    if args.dry_run:
        print("(dry-run — no files written)")
        return 0

    write_outputs(data, args.out_dir)
    print(f"✓ wrote {len(data)} bucket files + _index.json → {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

