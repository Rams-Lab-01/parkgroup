#!/usr/bin/env bash
# End-to-end demo recording orchestrator.
#
# Pipeline:
#   1. Start a local HTTP feed server (so an HTTP URL variant of the
#      demo also works for users who don't want file://).
#   2. Drive Playwright through the Odoo UI to record the entire flow.
#   3. Convert the WebM output to MP4 via ffmpeg.
#   4. (Optional) Generate TTS narration via espeak-ng and mux with the
#      video.
#
# Outputs (relative to this file):
#   videos/demo-<timestamp>.webm   raw Playwright recording
#   videos/demo-<timestamp>.mp4    final MP4
#   frames/<timestamp>-*.png       per-step screenshots
#
# Usage:
#   ./run_demo.sh                  # default: http://localhost:18030 Odoo,
#                                  # file:// URL for feed (works inside
#                                  # the demo_presentation container)
#   ODOO_BASE=... ./run_demo.sh    # override Odoo URL
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

ODOO_BASE="${ODOO_BASE:-http://localhost:18030}"
ODOO_USER="${ODOO_USER:-admin}"
ODOO_PASSWORD="${ODOO_PASSWORD:-admin}"
FEED_URL="${FEED_URL:-file:///mnt/extra-addons/sgc_offplan_rental_property_management/tests/fixtures/sample_bayut_feed.xml}"

# Optional HTTP-server mode (only used if FEED_URL is http://).
FEED_HTTP_PORT="${FEED_HTTP_PORT:-18099}"
FEED_HTTP_BASE="http://localhost:${FEED_HTTP_PORT}"

echo "==> Odoo base: $ODOO_BASE"
echo "==> Feed URL : $FEED_URL"
echo "==> Output dir: $HERE"

# If feed URL is http://, also start the local feed server.
FEED_SERVER_PID=""
if [[ "$FEED_URL" == http://* ]]; then
    echo "==> Starting local feed server on :$FEED_HTTP_PORT"
    python3 feed_server.py "$FEED_HTTP_PORT" > /tmp/feed_server.log 2>&1 &
    FEED_SERVER_PID=$!
    sleep 1
    if ! curl -sSf --max-time 3 "${FEED_URL}" > /dev/null; then
        echo "FAIL: feed server not reachable at ${FEED_URL}"
        kill "$FEED_SERVER_PID" 2>/dev/null || true
        exit 1
    fi
    echo "    feed server OK (pid=$FEED_SERVER_PID)"
fi

cleanup() {
    if [[ -n "$FEED_SERVER_PID" ]]; then
        echo "==> Stopping feed server (pid=$FEED_SERVER_PID)"
        kill "$FEED_SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "==> Step 1: recording browser session with Playwright"
python3 record_demo.py \
    --base "$ODOO_BASE" \
    --feed-url "$FEED_URL" \
    --user "$ODOO_USER" \
    --password "$ODOO_PASSWORD" \
    --viewport 1366,768

echo
echo "==> Step 2: locating recorded webm"
shopt -s nullglob
WEBM=( videos/*.webm )
shopt -u nullglob
if [[ ${#WEBM[@]} -eq 0 ]]; then
    echo "FAIL: no .webm produced in videos/"
    exit 1
fi
LATEST="${WEBM[-1]}"
echo "    raw video: $LATEST ($(du -h "$LATEST" | awk '{print $1}'))"

echo "==> Step 3: converting to mp4 via ffmpeg"
MP4="${LATEST%.webm}.mp4"
ffmpeg -y -i "$LATEST" \
    -c:v libx264 -preset medium -crf 23 \
    -movflags +faststart \
    -an \
    "$MP4" 2>&1 | tail -5
echo "    final mp4: $MP4 ($(du -h "$MP4" | awk '{print $1}'))"

# Step 4: optional TTS narration if espeak-ng is installed.
if command -v espeak-ng >/dev/null 2>&1; then
    echo "==> Step 4: generating TTS narration"
    AUDIO_WAV="audio/narration-$(basename "${LATEST%.webm}").wav"
    cat > /tmp/narration.txt <<'NARRATION'
This is an end-to-end demonstration of the inbound XML feed ingestion
pipeline in the SGC property management module for Odoo 19.
We will log in to Odoo, navigate to the portal connectors, point
the Bayut connector at a sample inbound feed URL, run the scheduled
ingestion cron, and observe the three properties appearing in the
system with a feed-source indicator.
End of narration.
NARRATION
    espeak-ng -v en-us -s 150 -w "$AUDIO_WAV" < /tmp/narration.txt
    echo "    audio: $AUDIO_WAV"
    MP4_NARRATED="${MP4%.mpm}-narrated.mp4"
    ffmpeg -y -i "$MP4" -i "$AUDIO_WAV" \
        -c:v copy -c:a aac \
        -shortest "$MP4_NARRATED" 2>&1 | tail -3
    echo "    narrated: $MP4_NARRATED"
else
    echo "==> Step 4: skipping narration (espeak-ng not installed)"
fi

echo
echo "==> Done. Demo artifacts:"
ls -lah videos/ frames/ audio/ 2>/dev/null || true