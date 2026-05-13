"""
診斷: ISO_BRACKET_RE 在 pipeline 是否真的有作用
跑法: python scripts\diag_iso_bracket.py
"""
import json
import re
from pathlib import Path

PPTX = Path(__file__).resolve().parent.parent / "outputs" / "extract" / "pptx_facets.jsonl"

# Same regex as in extract_pptx_all.py
ISO_BRACKET_RE = re.compile(
    r"[(（]\s*("
    r"514\+401|514\+605|"
    r"301|304|401|406|407|503|504|512|514|516|602|605|607"
    r")\s*[)）]"
)

# Generic 3-digit bracket (catches anything in parens)
GENERIC_BRACKET_RE = re.compile(r"[(（]\s*(\d{3})\s*[)）]")

# 車死 keyword test
CHESI_RE = re.compile(re.escape("車死"))

def main():
    total = 0
    has_iso = 0

    # Explicit bracket counts
    has_official_bracket = 0   # method 含官方 ISO 括號 e.g. (301)
    has_generic_bracket = 0    # method 含任何 3 位數括號
    bracket_iso_match = 0      # bracket matches assigned iso
    bracket_no_iso = 0         # has bracket BUT no iso assigned ← BUG
    bracket_diff_iso = 0       # bracket says X but iso says Y

    # 車死 keyword test
    has_cheshi = 0
    cheshi_no_iso = 0
    cheshi_samples = []

    bracket_no_iso_samples = []
    bracket_iso_distribution = {}

    with open(PPTX, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            for c in d.get("callouts", []):
                total += 1
                m = c.get("method", "")
                cur_iso = c.get("iso")
                if cur_iso:
                    has_iso += 1

                # bracket analysis
                official = ISO_BRACKET_RE.search(m)
                generic = list(GENERIC_BRACKET_RE.finditer(m))
                if official:
                    has_official_bracket += 1
                    bracket_iso = official.group(1)
                    bracket_iso_distribution[bracket_iso] = bracket_iso_distribution.get(bracket_iso, 0) + 1
                    if cur_iso:
                        if cur_iso == bracket_iso:
                            bracket_iso_match += 1
                        else:
                            bracket_diff_iso += 1
                    else:
                        bracket_no_iso += 1
                        if len(bracket_no_iso_samples) < 10:
                            bracket_no_iso_samples.append(m[:120])
                if generic:
                    has_generic_bracket += 1

                # 車死
                if CHESI_RE.search(m):
                    has_cheshi += 1
                    if not cur_iso:
                        cheshi_no_iso += 1
                        if len(cheshi_samples) < 5:
                            cheshi_samples.append(m[:120])

    print(f"\n=== ISO Bracket Diagnostic ({total:,} callouts) ===\n")
    print(f"## Total: has iso assigned          : {has_iso:,} ({has_iso/max(total,1)*100:.1f}%)")
    print(f"## Method 含官方 ISO 括號 (301/401 等): {has_official_bracket:,} ({has_official_bracket/max(total,1)*100:.1f}%)")
    print(f"## Method 含任何 3 位數括號 (寬鬆)    : {has_generic_bracket:,} ({has_generic_bracket/max(total,1)*100:.1f}%)")
    print(f"")
    print(f"## 官方括號 vs iso 欄位一致性:")
    print(f"   bracket 與 iso 相符        : {bracket_iso_match:,}")
    print(f"   bracket 但 iso 是不同號碼   : {bracket_diff_iso:,}")
    print(f"   ❗ bracket 但 iso 為空 (BUG): {bracket_no_iso:,}")
    print(f"")
    if bracket_no_iso_samples:
        print(f"## ⚠ 含 ISO 括號但沒被抽到的樣本 (前 10):")
        for s in bracket_no_iso_samples:
            print(f"   - {s}")
    print(f"")
    print(f"## 官方括號 ISO 分布:")
    for iso, n in sorted(bracket_iso_distribution.items(), key=lambda x: -x[1]):
        print(f"   {iso:<10} {n:>6}")
    print(f"")
    print(f"## 車死 keyword:")
    print(f"   含 '車死' 的 callout       : {has_cheshi:,}")
    print(f"   含 '車死' 但 iso 為空        : {cheshi_no_iso:,}")
    if cheshi_samples:
        print(f"   ❗ 沒推 iso 的 '車死' 樣本:")
        for s in cheshi_samples:
            print(f"      - {s}")

if __name__ == "__main__":
    main()
