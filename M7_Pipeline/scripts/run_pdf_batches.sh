#!/usr/bin/env bash
# run_pdf_batches.sh — 分批跑 extract_raw_text_m7.py --pdf-only (resumable)
#
# 設計給 sandbox 45s timeout 用：每次 call 跑到時間到為止，狀態寫檔，下次接著跑。
#
# 用法：
#   bash scripts/run_pdf_batches.sh <SCAN_DIR> <OUTPUT_DIR> [BATCH_SIZE] [MAX_SECONDS]
#   反覆呼叫直到看到「ALL DONE」訊息。

set -e

SCAN_DIR="${1:-../stytrix-pipeline-Download0504/data/ingest/uploads}"
OUT_DIR="${2:-../stytrix-pipeline-Download0504/data/ingest}"
BATCH_SIZE="${3:-30}"
MAX_SECONDS="${4:-35}"   # 留 10s 給 cleanup

M7_INDEX="M7資源索引_M7URL正確版_20260504.xlsx"
SHEET="新做工_PullOn"
STATE_FILE="$OUT_DIR/pdf/.batch_state"

# 算 PDF 總數
N_PDF=$(find "$SCAN_DIR" -maxdepth 1 -type f -name "*.pdf" 2>/dev/null | wc -l)
N_BATCH=$(( (N_PDF + BATCH_SIZE - 1) / BATCH_SIZE ))

# 讀 state（上次跑到第幾 batch）
NEXT=0
if [ -f "$STATE_FILE" ]; then
    NEXT=$(cat "$STATE_FILE")
fi

if [ "$NEXT" -ge "$N_BATCH" ]; then
    echo "═══ ALL DONE ═══"
    echo "  Total $N_BATCH batches, NEXT=$NEXT"
    echo "  PNG: $(ls "$OUT_DIR/pdf/callout_images/" 2>/dev/null | wc -l)"
    echo "  Manifest: $(wc -l < "$OUT_DIR/pdf/callout_manifest.jsonl" 2>/dev/null) rows"
    exit 0
fi

mkdir -p "$OUT_DIR/pdf"
# 第一 batch 清 manifest
if [ "$NEXT" -eq 0 ]; then
    > "$OUT_DIR/pdf/callout_manifest.jsonl"
fi

echo "[wrapper] N_PDF=$N_PDF  N_BATCH=$N_BATCH  starting from batch $NEXT"
echo "[wrapper] max wall time: ${MAX_SECONDS}s"

START_TIME=$(date +%s)
DONE_THIS_RUN=0

while [ "$NEXT" -lt "$N_BATCH" ]; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))
    if [ "$ELAPSED" -ge "$MAX_SECONDS" ]; then
        echo "[wrapper] hit ${MAX_SECONDS}s budget after $DONE_THIS_RUN batches, stopping"
        break
    fi
    REMAINING=$((MAX_SECONDS - ELAPSED))

    START=$((NEXT * BATCH_SIZE))
    echo "── batch $((NEXT+1))/$N_BATCH (rows $START..$((START+BATCH_SIZE-1)))  remaining_budget=${REMAINING}s ──"
    timeout "$REMAINING" python3 scripts/extract_raw_text_m7.py \
        --scan-dir "$SCAN_DIR" \
        --output-dir "$OUT_DIR" \
        --m7-index "$M7_INDEX" \
        --sheet "$SHEET" \
        --pdf-only \
        --batch-start "$START" \
        --batch-size "$BATCH_SIZE" \
        --force 2>&1 | tail -3 || {
            echo "[wrapper] batch timed out, NEXT stays at $NEXT to retry"
            break
        }

    NEXT=$((NEXT + 1))
    DONE_THIS_RUN=$((DONE_THIS_RUN + 1))
    echo "$NEXT" > "$STATE_FILE"
done

echo ""
echo "[wrapper] DONE this run: $DONE_THIS_RUN batches  NEXT=$NEXT/$N_BATCH"
if [ "$NEXT" -ge "$N_BATCH" ]; then
    echo "═══ ALL DONE ═══"
fi
