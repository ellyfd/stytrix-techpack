"""bible_classify.py — Bible 載入 + L4 mismatch 分類邏輯共用

兩個 consumer:
  - report_l5_audit_typed.py:audit 報告
  - build_designs_index.py:per-EIDH 履歷加 bible_alignment

L4 mismatch 三類:
  A — IE 端 broad category(命名顆粒度差異,不是 Bible 缺結構)
      白名單:手工類/車縫類/打結/燙襯類/壓裝飾線/拷克/裁剪 等大分類詞
  B — Placeholder(per CLAUDE.md 該 drop)
      regex:new_method_describe_* / new_shape_design_* / new_part_* / (NEW)* / (new)*
  C — `*_其它` 結尾(IE 端「未細分子類」,合理 placeholder 但要記)
  other — 真實新結構(Bible 缺,IE 部門要看)
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Literal

MismatchType = Literal["A", "B", "C", "other", "match"]

# Type A:IE 端 broad category 白名單(命名顆粒度差異,不是 Bible 缺結構)
BROAD_CATEGORY_TOKENS = {
    # 大工法類別
    "手工類", "車縫類", "燙襯類", "拷克類", "裁剪類", "打結類",
    "壓線類", "縫紉類", "整燙類", "包邊類",
    # 短 token
    "手工", "車縫", "燙襯", "拷克", "裁剪", "打結", "整燙",
    # 動作類
    "壓裝飾線", "壓腰頭裝飾線", "鎖占比", "做記號", "拷邊", "拷縫",
    # 通用 catch-all
    "其它", "其他",
}

# Type B:Placeholder regex
PLACEHOLDER_PATTERNS = [
    re.compile(r"^new_method_describe_\d+$", re.IGNORECASE),
    re.compile(r"^new_shape_design_\d+$", re.IGNORECASE),
    re.compile(r"^new_part_\d+$", re.IGNORECASE),
    re.compile(r"^\(NEW\)", re.IGNORECASE),
    re.compile(r"^\(new\)", re.IGNORECASE),
]

# Type C:`*_其它` 結尾(L3 / L4 placeholder for 未細分子類)
RE_OTHER_SUFFIX = re.compile(r"_其[它他]$")


def classify_l4(l4: str) -> MismatchType:
    """Return classification for an L4 string that's NOT in Bible.

    順序:B(placeholder)優先 → A(broad)→ C(_其它)→ other"""
    if not l4:
        return "other"
    s = l4.strip()
    # B
    for pat in PLACEHOLDER_PATTERNS:
        if pat.search(s):
            return "B"
    # 內含 placeholder token (例如 method 描述含 "new_method_describe_xxx")
    if "new_method_describe_" in s.lower() or "new_shape_design_" in s.lower():
        return "B"
    # A
    if s in BROAD_CATEGORY_TOKENS:
        return "A"
    # 含廣義 broad token (例如 "車縫類_其它" 屬 A 大於 C)
    for token in BROAD_CATEGORY_TOKENS:
        if s.startswith(token):
            return "A"
    # C
    if RE_OTHER_SUFFIX.search(s):
        return "C"
    return "other"


def load_bible(bible_root: Path) -> dict:
    """Walk Bible JSON,build hierarchical lookup.

    Returns:
        {
            "full_tuples": set of (L1, wk, L2, L3, L4, L5),
            "l4_set": set of (L1, wk, L2, L3, L4),
            "l3_set": set of (L1, wk, L2, L3),
            "l2_set": set of (L1, wk, L2),
            "l1_zh": L1 code → 中文 zh name,
            "n_files": loaded file count,
        }
    """
    full_tuples = set()
    l4_set = set()
    l3_set = set()
    l2_set = set()
    l1_zh = {}

    bible_files = sorted(bible_root.glob("*.json"))
    bible_files = [f for f in bible_files if f.name != "_index.json"]

    for f in bible_files:
        try:
            data = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        l1 = data.get("code") or f.stem
        l1_zh[l1] = data.get("l1", "")

        for wk in ("knit", "woven"):
            l2_list = data.get(wk, [])
            if not isinstance(l2_list, list):
                continue
            for l2_node in l2_list:
                if not isinstance(l2_node, dict):
                    continue
                l2 = l2_node.get("l2", "")
                l2_set.add((l1, wk, l2))
                shapes = l2_node.get("shapes", [])
                if not isinstance(shapes, list):
                    continue
                for shape in shapes:
                    if not isinstance(shape, dict):
                        continue
                    l3 = shape.get("l3", "")
                    l3_set.add((l1, wk, l2, l3))
                    methods = shape.get("methods", [])
                    if not isinstance(methods, list):
                        continue
                    for method in methods:
                        if not isinstance(method, dict):
                            continue
                        l4 = method.get("l4", "")
                        l4_set.add((l1, wk, l2, l3, l4))
                        steps = method.get("steps", [])
                        if not isinstance(steps, list):
                            continue
                        for step in steps:
                            if isinstance(step, list) and len(step) >= 1:
                                l5 = step[0]
                                full_tuples.add((l1, wk, l2, l3, l4, l5))
                            elif isinstance(step, dict):
                                l5 = step.get("l5", "")
                                full_tuples.add((l1, wk, l2, l3, l4, l5))

    return {
        "full_tuples": full_tuples,
        "l4_set": l4_set,
        "l3_set": l3_set,
        "l2_set": l2_set,
        "l1_zh": l1_zh,
        "n_files": len(bible_files),
    }


def step_alignment(step: dict, fabric: str, bible: dict) -> dict:
    """為一筆 design step 算 bible_alignment block

    Args:
        step: design 履歷裡的一筆 five_level_steps[i] dict
        fabric: 該 design 的 fabric value (knit/woven)
        bible: load_bible() 結果

    Returns:
        {"in_bible": bool, "type": "match"|"A"|"B"|"C"|"other", "level_breaks_at": "L4"|"L5"|None}
    """
    l1 = step.get("l1", "")
    l2 = step.get("l2", "")
    l3 = step.get("l3", "")
    l4 = step.get("l4", "")
    l5 = step.get("l5", "")
    wk = (fabric or "").lower()
    if wk not in ("knit", "woven"):
        return {"in_bible": False, "type": "other", "level_breaks_at": "fabric"}

    full = (l1, wk, l2, l3, l4, l5)
    if full in bible["full_tuples"]:
        return {"in_bible": True, "type": "match", "level_breaks_at": None}

    # 不在 Bible:看哪一層斷
    if (l1, wk, l2, l3, l4) not in bible["l4_set"]:
        # L4 斷:分類 A/B/C/other
        return {"in_bible": False, "type": classify_l4(l4), "level_breaks_at": "L4"}
    if (l1, wk, l2, l3) not in bible["l3_set"]:
        return {"in_bible": False, "type": "other", "level_breaks_at": "L3"}
    if (l1, wk, l2) not in bible["l2_set"]:
        return {"in_bible": False, "type": "other", "level_breaks_at": "L2"}
    # L4 OK 但 L5 斷
    return {"in_bible": False, "type": "other", "level_breaks_at": "L5"}
