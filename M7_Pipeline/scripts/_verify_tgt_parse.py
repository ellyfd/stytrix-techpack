"""
Verify TGT parse_cover 對 AIM PDF 真的有抽到款號
跑法: python scripts\_verify_tgt_parse.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 強制清掉 cache (避免用到舊 pyc)
for cache_dir in (ROOT / "scripts" / "client_parsers").glob("__pycache__"):
    import shutil
    shutil.rmtree(cache_dir, ignore_errors=True)

# 確認 module 認得新 method
from client_parsers import get_parser
parser = get_parser("TGT")
print(f"=== Parser sanity check ===")
print(f"  parser class: {parser.__class__.__name__}")
print(f"  has _parse_makalot_sample_room_layout: {hasattr(parser, '_parse_makalot_sample_room_layout')}")
print(f"  has _parse_2col_layout: {hasattr(parser, '_parse_2col_layout')}")

# 拿 306845 PDF 來測
import fitz
TP = ROOT / "tp_samples_v2"
folders = list(TP.glob("306845_*"))
if not folders:
    print("[!] 306845 folder 不在")
    sys.exit(1)
pdfs = list(folders[0].rglob("*.pdf"))
if not pdfs:
    print("[!] 306845 沒 PDF")
    sys.exit(1)
pdf = pdfs[0]
print(f"\n=== Test on PDF ===\n  {pdf.name}")

doc = fitz.open(str(pdf))
text = doc[0].get_text()
print(f"\n  page 1 first 150 chars:")
print(f"  {text[:150]!r}")

# Direct call parse_cover
print(f"\n=== Direct parse_cover call ===")
result = parser.parse_cover(doc[0], text)
print(f"  result: {result}")
print(f"  result keys: {list(result.keys()) if result else '(empty)'}")
print(f"  result count: {len(result) if result else 0}")

if result:
    print(f"\n  ✅ parser 成功抽到 {len(result)} 個欄位")
else:
    print(f"\n  ❌ parser 回空 dict — bug 確認, dispatch 沒走到 Makalot SR")

# 也直接測 _parse_makalot_sample_room_layout
print(f"\n=== Direct _parse_makalot_sample_room_layout call ===")
if hasattr(parser, '_parse_makalot_sample_room_layout'):
    sr = parser._parse_makalot_sample_room_layout(text)
    print(f"  result: {sr}")
    print(f"  count: {len(sr) if sr else 0}")
else:
    print(f"  ❌ method 不存在!")
