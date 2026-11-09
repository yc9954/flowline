#!/bin/zsh
# Record the Mac cuts with the real Flowline menu-bar app, driven by its debug control.
# usage: record_mac_cuts.sh 6|7|10 [api_base]
#   6 — end-of-day notch peeks, menu panel shows "Sent to team 0"
#   7 — review window, left-out column, Approve and share, record sheet
#  10 — suggestion notch peek → Do it (the PM's run starts on desk1; with FLOWLINE_FLEET=1 the API starts the five
#       pre-approved teammates' runs at the same moment). Right after Do it this script launches the fleet-page
#       recording (record_board.mjs --only 10) so cut 10 shows the same live runs.
# Prereqs: agent-mac built (scripts/bundle.sh); Accessibility granted once; light mode; Dock hidden; stage_mac.sh run.
set -e
HERE=${0:a:h}
ROOT=${HERE:h}
APP=$ROOT/agent-mac/build/Flowline.app/Contents/MacOS/Flowline
DRIVE=$ROOT/agent-mac/scripts/drive.sh
CUT=$1; API=${2:-http://localhost:18787}
BOARD=${BOARD_BASE:-http://localhost:5173}
[[ -x $APP ]] || { echo "build the app first: cd agent-mac && scripts/bundle.sh"; exit 1; }
set -a; source $ROOT/.env 2>/dev/null || true; set +a

defaults write co.sweetspot.flowline api_base "$API"
defaults write co.sweetspot.flowline person_id pm-1
defaults write co.sweetspot.flowline board_id northwind
pkill -x Flowline 2>/dev/null || true
sleep 0.5

rec() { cliclick m:1500,975 >/dev/null 2>&1 || true; ($HERE/record_mac.sh "$1" "$2" &) ; sleep 1.2; }   # park the pointer off-frame; ffmpeg needs ~1 s to start
launch() { ( "$APP" --demo-day --debug-control --no-observe "$@" >/tmp/flowline-app.log 2>&1 & ); }

case $CUT in
  5)
    rec 5 12
    launch --eod-now            # notch peeks ~3.5 s after launch (prepareDraft first); the peek is mostly behind the menu bar on camera
    sleep 5
    $DRIVE notch-open           # open state (400×112): "Your day is drafted" + Review — this is what the film shows
    sleep 2.5
    $DRIVE menu                 # menu-bar panel: NOTED TODAY / SENT TO TEAM 0
    sleep 3
    ;;
  6)
    launch --eod-now; sleep 3
    $DRIVE review; sleep 2.5    # review window up before we roll
    rec 6 8
    sleep 3                     # camera holds on the review and left-out column
    $DRIVE approve              # posts the signed record to the API, shows the record sheet
    sleep 4
    ;;
  9)
    defaults write co.sweetspot.flowline run_target desk1
    launch; sleep 3
    # offer the suggestion: approve the best plan on the board (creates one suggestion per person), then make the app poll now
    curl -s -X POST "$API/api/boards/northwind/plans/$(curl -s $API/api/boards/northwind/plans | python3 -c 'import sys,json;p=json.load(sys.stdin)["plans"];print([x for x in p if x.get("best")][0]["id"])')/approve" >/dev/null
    sleep 1; $DRIVE poll; sleep 1.5
    rec 9 10
    $DRIVE notch-open           # the full suggestion (400×134): "8× last week · fill the deck?" + Do it / Later
    sleep 3
    $DRIVE do-it                # the PM's run starts; the API fans out the pre-approved runs; the glow comes up
    ( cd $HERE && FLEET_HOLD_MS=${FLEET_HOLD_MS:-420000} BOARD_BASE=$BOARD node record_board.mjs --base $BOARD --only 10 > /tmp/flowline-fleet-rec.log 2>&1 & )
    sleep 6
    ;;
  *) echo "usage: $0 5|6|9 [api_base]"; exit 1 ;;
esac
sleep 1.5
if [[ $CUT != 9 ]]; then pkill -x Flowline 2>/dev/null || true; fi   # cut 9 leaves the app up while the fleet records
printf "cut %s recorded -> out/cuts/%02d.mov\n" "$CUT" "$CUT"
