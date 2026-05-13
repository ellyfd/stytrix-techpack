#!/usr/bin/env bash
# pipeline_m7.sh — 一鍵跑完整 PullOn pipeline
#
# 順序：
#   1. extract_raw_text_m7  (metadata + pptx + pdf)
#   2. extract_unified_m7   (callout → fact, with bucket = WK_BOTTOMS)
#   3. align_to_ie_m7       (fact 對齊 IE 五階段 step)
#   4. build_consensus_m7   (跨客戶 union → consensus rules)
#   5. validate_bridge_m7   (8 欄 coverage 報告)
#
# PDF 階段 > 30 檔自動切換到 batch wrapper（給 sandbox 45s timeout 用）
#
# 用法：bash scripts/pipeline_m7.sh <SCAN_DIR> <OUTPUT_DIR>
# 預設：bash scripts/pipeline_m7.sh ../stytrix-pipeline-Download0504/data/ingest/uploads ../stytrix-pipeline-Download0504/data/ingest

set -e

SCAN_DIR="${1:-../stytrix-pipeline-Download0504/data/ingest/uploads}"
OUTPUT="${2:-../stytrix-pipeline-Download0504/data/ingest}"

# Resolve to abs path
SCAN_DIR=$(realpath "$SCAN_DIR")
OUTPUT=$(realpath "$OUTPUT")

# 切到 M7_Pipeline/ 根目錄
cd "$(dirname "$0")/.."

echo "═══════════════════════════════════════════════════════════════"
echo "  PullOn pipeline_m7"
echo "  SCAN:   $SCAN_DIR"
echo "  OUTPUT: $OUTPUT"
echo "═══════════════════════════════════════════════════════════════"

mkdir -p "$OUTPUT"/{metadata,pptx,pdf/callout_images,unified,vlm}

# ── Step 1a: metadata ──
echo ""
echo "── 1a. metadata ──"
python3 scripts/extract_raw_text_m7.py \
    --scan-dir "$SCAN_DIR" \
    --output-dir "$OUTPUT" \
    --metadata-only --force 2>&1 | tail -3

# ── Step 1b: pptx ──
echo ""
echo "── 1b. pptx ──"
python3 scripts/extract_raw_text_m7.py \
    --scan-dir "$SCAN_DIR" \
    --output-dir "$OUTPUT" \
    --pptx-only --force 2>&1 | tail -3

# ── Step 1c: pdf (auto batch if > 30 PDF) ──
N_PDF=$(find "$SCAN_DIR" -maxdepth 1 -type f -name "*.pdf" | wc -l)
echo ""
echo "── 1c. pdf ($N_PDF files) ──"
if [ "$N_PDF" -le 30 ]; then
    python3 scripts/extract_raw_text_m7.py \
        --scan-dir "$SCAN_DIR" \
        --output-dir "$OUTPUT" \
        --pdf-only --force 2>&1 | tail -3
else
    echo "  (auto batch mode — 反覆 call run_pdf_batches.sh 直到 ALL DONE)"
    rm -f "$OUTPUT/pdf/.batch_state"
    while ! bash scripts/run_pdf_batches.sh "$SCAN_DIR" "$OUTPUT" 30 35 2>&1 | tail -5 | grep -q "ALL DONE"; do
        echo "    .. continuing batch ($(cat "$OUTPUT/pdf/.batch_state" 2>/dev/null || echo 0) batches done)"
    done
fi

# ── Step 2: unified ──
echo ""
echo "── 2. extract_unified_m7 ──"
python3 scripts/extract_unified_m7.py \
    --ingest-dir "$OUTPUT" \
    --out "$OUTPUT/unified" 2>&1 | tail -10

# ── Step 3: align IE ──
echo ""
echo "── 3. align_to_ie_m7 ──"
python3 scripts/align_to_ie_m7.py 2>&1 | tail -8

# ── Step 4: consensus ──
echo ""
echo "── 4. build_consensus_m7 ──"
python3 scripts/build_consensus_m7.py 2>&1 | tail -8

# ── Step 5: validate ──
echo ""
echo "── 5. validate_bridge_m7 ──"
python3 scripts/validate_bridge_m7.py 2>&1 | tail -15

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Pipeline DONE"
echo "  facts:     $OUTPUT/unified/facts.jsonl"
echo "  dim:       $OUTPUT/unified/dim.jsonl"
echo "  aligned:   m7_organized_v2/aligned/final_aligned.csv"
echo "  consensus: m7_organized_v2/aligned/consensus_m7.jsonl"
echo "  validate:  outputs/validate_bridge_m7/_summary.csv"
echo "═══════════════════════════════════════════════════════════════"
