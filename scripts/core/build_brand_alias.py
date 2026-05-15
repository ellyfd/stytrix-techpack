#!/usr/bin/env python3
"""Build data/runtime/brand_pom_alias.json — data-driven brand alias lookup.

問題:
  brands.json 用 canonical_aliases.json normalize 後的 3-letter code(DKS、KOH 等);
  pom_rules._meta.source_brand_codes 是 Centric 8 PDF brand_division 欄的 raw
  10-char truncated string("DSG WOMENS" / "KOHL'S WOM" / "ABERCROMBI" / "HIGH LIFE "
  / "UNDER ARMO"…)。兩邊沒對齊 → 前端 dataBrandMatches `codes.includes('DKS')`
  永遠 false → bucketMeta=null → spec 不生成。

兩份 source-of-truth(沒 1:1 對應,需要 merge):

  data/source/canonical_aliases.json[客戶][verbose_name] = short_code
    e.g. "DICKS SPORTING GOODS" → "DKS"
         "OLD NAVY"             → "ONY"

  data/client_canonical_mapping.json[verbose_name] = {
    aliases:               ["DICK'S", "DICKS", "DSG", ...],            # 各種寫法
    legacy_subgroup_codes: ["DSG", "DSG COMPRESSION", "CALIA", ...],   # Centric 8 sub-division raw stamps
  }

合併規則:
  short_code (DKS) → reverse canonical_aliases.json:客戶 → [verbose_names]
                  → 每個 verbose_name 去 client_canonical_mapping[v]
                  → 拿 aliases + legacy_subgroup_codes
                  → 拼成完整 alias 集

輸出 data/runtime/brand_pom_alias.json:
  {
    "version": "v1",
    "generated_at": "...",
    "source": [...],
    "aliases": {
      "DKS": ["CALIA", "DICK'S", "DICKS", "DICKS SPORTING GOO",
              "DICKS SPORTING GOODS", "DKS", "Dick's Sporting Goods",
              "DSG", "DSG COMPRESSION", "PERFECT GAME", "VRST", "WALTER HAGEN"],
      "KOH": ["KOH", "KOHL'S", "KOHLS", "Kohl's", ...],
      ...
    }
  }

前端 dataBrandMatches 用法(取代 hardcode `BRAND_TO_POM_PREFIXES`):
  const aliases = brandAlias?.aliases?.[brand] || [brand];
  const codes = pomRules._meta.source_brand_codes;
  return aliases.some(a => codes.some(c => c === a || c.startsWith(a + ' ') || c.startsWith(a)));
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

SRC_CANONICAL = REPO / "data" / "source" / "canonical_aliases.json"
SRC_CLIENT    = REPO / "data" / "client_canonical_mapping.json"
OUT_PATH      = REPO / "data" / "runtime" / "brand_pom_alias.json"


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def build_aliases() -> dict[str, list[str]]:
    canon = load_json(SRC_CANONICAL)
    client = load_json(SRC_CLIENT)
    cmap = client.get("client_canonical_mapping", {})

    # 排除清單:client_canonical_mapping.legacy_subgroup_codes 內常見的
    # 「不是 brand-identifier 的通用詞」— 加進 aliases 會跟其他 brand 的 raw
    # stamps false-match(例如 ATH 帶 "WOMENS" 會 match "DSG WOMENS")。
    # 規則:gender / 品類 / dept / 純數字代號(Target 內部 subgroup 像 D20/D75)。
    GENERIC_TOKENS = {
        # gender / dept
        "WOMENS", "WOMEN", "MENS", "MEN", "GIRLS", "GIRL", "BOYS", "BOY",
        "MATERNITY", "BABY", "TODDLER", "KIDS",
        # category
        "ACTIVE", "RTW", "SLEEPWEAR", "SWIMWEAR", "FLEECE", "COLLABORATION",
        "DENIM", "KNIT", "WOVEN",
    }

    def is_safe_alias(s: str) -> bool:
        """Reject overly generic strings that would cause cross-brand false-match."""
        if not s or not isinstance(s, str):
            return False
        s_stripped = s.strip()
        if len(s_stripped) < 2:
            return False
        # Reject pure-digit-suffix codes (Target's D20 / D75 internal subgroup IDs)
        # — they're short, brand-internal, and could collide with pom_rules raw stamps
        # 開頭一個字母 + 1-3 digits 結尾(像 D20 / D214 / B25)
        import re as _re
        if _re.fullmatch(r"[A-Z]\d{1,4}", s_stripped):
            return False
        if s_stripped.upper() in GENERIC_TOKENS:
            return False
        return True

    # Step 1: reverse canonical_aliases.json:客戶 → short_code → [verbose_names]
    customer_aliases = canon.get("客戶", {})
    short_to_verbose: dict[str, list[str]] = {}
    for verbose, short in customer_aliases.items():
        if verbose.startswith("_"):
            continue
        short_to_verbose.setdefault(short, []).append(verbose)

    # Step 2: for each short code, collect all aliases + legacy_subgroup_codes
    #         from client_canonical_mapping (跨 verbose names mapped to that code)
    result: dict[str, set[str]] = {}
    for short, verboses in short_to_verbose.items():
        acc: set[str] = set()
        acc.add(short)  # short code itself (so exact-match path works)
        for v in verboses:
            if is_safe_alias(v):
                acc.add(v)  # canonical name itself
            entry = cmap.get(v)
            if not isinstance(entry, dict):
                continue
            aliases = entry.get("aliases") or []
            if isinstance(aliases, dict):
                aliases = list(aliases.keys())
            for a in aliases:
                if is_safe_alias(a):
                    acc.add(str(a))
            legacy = entry.get("legacy_subgroup_codes") or []
            if isinstance(legacy, dict):
                legacy = list(legacy.keys())
            for l in legacy:
                if is_safe_alias(l):
                    acc.add(str(l))
        result[short] = sorted(acc)

    return result


def main() -> int:
    aliases = build_aliases()
    payload = {
        "version": "v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": [
            "data/source/canonical_aliases.json:客戶",
            "data/client_canonical_mapping.json:client_canonical_mapping[*].{aliases,legacy_subgroup_codes}",
        ],
        "note": (
            "前端 dataBrandMatches 用:given brand short-code (e.g. DKS), "
            "aliases[brand] 是所有可能的 raw 寫法,對齊 pom_rules._meta.source_brand_codes "
            "內的 truncated stamps('DSG WOMENS' / \"KOHL'S WOM\" / 'CALIA WOME' 等)。"
            "前端比對:exact match 或 startsWith(alias + ' ') 或 startsWith(alias)。"
        ),
        "aliases": aliases,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = sum(len(v) for v in aliases.values())
    print(
        f"[brand_alias] wrote {OUT_PATH.relative_to(REPO)}: "
        f"{len(aliases)} short-codes / {total} alias entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
