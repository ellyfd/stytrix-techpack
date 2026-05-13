"""m7_eidh_loader.py — 共用的 M7 EIDH 載入邏輯（single source of truth）

所有需要 M7 索引的 script 都用此 helper，避免 drift。
改 ITEM_FILTER 一處改、所有下游 script 同步生效。

用法（兩種）：
    # 1. 只要 EIDH list
    from m7_eidh_loader import load_eidhs
    eidhs = load_eidhs()  # → list of int

    # 2. 要完整 DataFrame（含「客戶」「Subgroup」「Item」「PRODUCT_CATEGORY」「TP資料夾」等欄位）
    from m7_eidh_loader import load_m7_index
    df = load_m7_index()  # → pd.DataFrame，已套 ITEM_FILTER

優先序：
  1. 新版 M7列管_20260507.xlsx「總表」filter ITEM_FILTER (~4,644 件)
  2. 舊版 M7資源索引_M7URL正確版_20260504.xlsx「新做工_PullOn」(1,180 件)
  3. fallback designs.jsonl（只 EIDH list 模式才有）

要跑全 18,731 件全品類：把 ITEM_FILTER 改成空 set ()。
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = ROOT.parent / "stytrix-pipeline-Download0504"
M7_INDEX_NEW = ROOT.parent / "M7列管_20260507.xlsx"
M7_INDEX_OLD = ROOT / "M7資源索引_M7URL正確版_20260504.xlsx"
DESIGNS_JSONL = DL / "data" / "ingest" / "metadata" / "designs.jsonl"

# Single source of truth — 改這個 set 兩支 fetch 都跟著動
# 空 set () = 不限制（跑全 18,731 全品類）
# {"Pull On Pants", "Leggings"} = 4,644 件 PullOn+Leggings (Pilot 範圍, 2026-05-08~10)
# {"Pull On Pants"} = 3,823 件 PullOn-only
# 全展開 (2026-05-11): 跑 M7 列管 全 18,731 件 (32 個 Item 種類, 含上下衣 / 整身 / 外套)
ITEM_FILTER: set[str] = set()  # 空 = 不限制, 跑全 18,731


def _load_from_new(path: Path) -> list[int]:
    """讀新版「總表」(18,731)，套 ITEM_FILTER"""
    import pandas as pd
    for engine in ("calamine", "openpyxl"):
        try:
            df = pd.read_excel(path, sheet_name="總表", engine=engine)
            if ITEM_FILTER:
                before = len(df)
                df = df[df["Item"].astype(str).str.strip().isin(ITEM_FILTER)]
                print(f"[load] M7列管 5/7 新版 ({engine}) filter Item={sorted(ITEM_FILTER)}: {before} → {len(df)} EIDHs")
            else:
                print(f"[load] M7列管 5/7 新版 ({engine}): {len(df)} EIDHs (全品類)")
            return sorted({int(e) for e in df["Eidh"].dropna()})
        except Exception as e:
            print(f"[!] M7列管 5/7 讀取失敗 (engine={engine}): {e}")
    return []


def _load_from_old(path: Path) -> list[int]:
    """讀舊版「新做工_PullOn」(1,180)，無 filter"""
    import pandas as pd
    for engine in ("calamine", "openpyxl"):
        try:
            df = pd.read_excel(path, sheet_name="新做工_PullOn", engine=engine)
            print(f"[load] M7資源索引 5/4 舊版 ({engine}): {len(df)} EIDHs")
            return sorted({int(r["Eidh"]) for _, r in df.iterrows()
                           if r.get("Eidh") is not None and not (isinstance(r.get("Eidh"), float)
                                                                  and r.get("Eidh") != r.get("Eidh"))})
        except Exception as e:
            print(f"[!] 5/4 舊版讀取失敗 (engine={engine}): {e}")
    return []


def _load_from_designs_jsonl() -> list[int]:
    eidhs = []
    if not DESIGNS_JSONL.exists():
        return eidhs
    for line in open(DESIGNS_JSONL, encoding="utf-8"):
        try:
            d = json.loads(line)
            if d.get("eidh"):
                eidhs.append(int(d["eidh"]))
        except Exception:
            continue
    eidhs = sorted(set(eidhs))
    print(f"[load] designs.jsonl fallback: {len(eidhs)} EIDHs")
    return eidhs


def load_eidhs() -> list[int]:
    """主函式（EIDH list 版）"""
    eidhs = []
    if M7_INDEX_NEW.exists():
        eidhs = _load_from_new(M7_INDEX_NEW)
    if not eidhs and M7_INDEX_OLD.exists():
        eidhs = _load_from_old(M7_INDEX_OLD)
    if not eidhs:
        eidhs = _load_from_designs_jsonl()
    print(f"[load] {len(eidhs)} EIDHs total")
    return eidhs


def load_m7_index(apply_filter: bool = True):
    """回完整 M7 索引 DataFrame（已套 ITEM_FILTER）

    用於需要 metadata 欄位（客戶 / Subgroup / Item / PRODUCT_CATEGORY / TP資料夾 等）的 script。

    Args:
        apply_filter: True 套 ITEM_FILTER 縮成 4,644；False 回全 18,731

    Returns:
        pd.DataFrame 含 42 欄（新版 M7列管「總表」schema）
        若 fallback 到舊版「新做工_PullOn」schema 不一樣（columns 較少）

    Raises:
        FileNotFoundError 若新舊索引都不存在
    """
    import pandas as pd
    if M7_INDEX_NEW.exists():
        for engine in ("calamine", "openpyxl"):
            try:
                df = pd.read_excel(M7_INDEX_NEW, sheet_name="總表", engine=engine)
                if apply_filter and ITEM_FILTER:
                    before = len(df)
                    df = df[df["Item"].astype(str).str.strip().isin(ITEM_FILTER)].reset_index(drop=True)
                    print(f"[load_m7_index] M7列管 5/7 ({engine}) filter Item={sorted(ITEM_FILTER)}: {before} → {len(df)} 筆")
                else:
                    print(f"[load_m7_index] M7列管 5/7 ({engine}): {len(df)} 筆 (無 filter)")
                return df
            except Exception as e:
                print(f"[!] M7列管 5/7 讀取失敗 (engine={engine}): {e}")
    if M7_INDEX_OLD.exists():
        for engine in ("calamine", "openpyxl"):
            try:
                df = pd.read_excel(M7_INDEX_OLD, sheet_name="新做工_PullOn", engine=engine)
                print(f"[load_m7_index] M7資源索引 5/4 舊版 ({engine}): {len(df)} 筆 (legacy schema)")
                return df
            except Exception as e:
                print(f"[!] 5/4 舊版讀取失敗 (engine={engine}): {e}")
    raise FileNotFoundError(f"M7 索引不存在：{M7_INDEX_NEW} 或 {M7_INDEX_OLD}")


if __name__ == "__main__":
    eidhs = load_eidhs()
    print(f"\nFirst 5: {eidhs[:5]}")
    print(f"Last 5:  {eidhs[-5:]}")
    print()
    print("=== load_m7_index() DataFrame test ===")
    df = load_m7_index()
    print(f"Shape: {df.shape}")
    print(f"Columns (first 10): {list(df.columns)[:10]}")
