#!/usr/bin/env bash
# Render every route with headless Chrome into board/shots/.
#   scripts/shots.sh fixture   -> <route>.png        (?fixtures=1: design comparison, independent of the API)
#   scripts/shots.sh api       -> <route>.api.png    (whatever the API on 8787 answers; fixture fallback otherwise)
#   scripts/shots.sh 1280      -> <route>.1280.png   (fixture data at 1280x800)
set -euo pipefail
MODE="${1:-fixture}"
BASE="${BASE:-http://localhost:5173}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/shots"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$OUT"
case "$MODE" in
  fixture) SUF=""; Q="fixtures=1"; W=1440; H=900 ;;
  api)     SUF=".api"; Q=""; W=1440; H=900 ;;
  1280)    SUF=".1280"; Q="fixtures=1"; W=1280; H=800 ;;
  *) echo "mode: fixture | api | 1280"; exit 1 ;;
esac
shot() { # name route [width]
  local name="$1" route="$2" w="${3:-$W}"
  local url="${BASE}${route}"
  if [ -n "$Q" ]; then case "$route" in *\?*) url="${url}&${Q}" ;; *) url="${url}?${Q}" ;; esac; fi
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --virtual-time-budget=12000 --run-all-compositor-stages-before-draw \
    --window-size="${w},${H}" --screenshot="$OUT/${name}${SUF}.png" "$url" >/dev/null 2>&1 || echo "failed: $route"
  echo "shot ${name}${SUF} (${w}x${H}) <- $url"
}
shot decide-expand    /decide/expand
shot decide-expand-coffee "/decide/expand?industry=722515"
shot decide-opening   /decide/opening
shot improve-plans    /improve/plans
shot improve-results  /improve/results
shot improve-history  /improve/history
if [ "$MODE" = "1280" ]; then shot know-knowledge /know/knowledge; else shot know-knowledge /know/knowledge 2000; fi
shot know-waits       /know/waits
shot know-records     /know/records
shot know-record-open /know/records/1106-0412
shot trust-model      /trust/model
shot surfaces         /surfaces
