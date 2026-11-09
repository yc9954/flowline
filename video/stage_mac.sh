#!/bin/zsh
# Stage this Mac's screen for the live takes: hide everything, open the PM's pricing sheet in LibreOffice Calc
# (and, with `deck`, the proposal deck in Impress beside it), as in Main.dc.html / Suggest.dc.html.
# usage: stage_mac.sh sheet|deck|viewer|clear
set -e
HERE=${0:a:h}; ROOT=${HERE:h}
SHEET=$ROOT/executor/assets/pricing-sheet.ods
DECK=$ROOT/executor/assets/proposal-172.odp
SOFFICE="/Applications/LibreOffice.app/Contents/MacOS/soffice"
hide_others() {  # hide every visible app one by one (the bulk "every process" form silently skips some apps); $1 = extra keep list
  osascript -e 'tell application "System Events" to get name of every process whose visible is true' 2>/dev/null | tr ',' '\n' | sed 's/^ *//' | while read -r p; do
    case "$p" in Finder|soffice|Flowline|Dock|SystemUIServer|"") continue ;; esac
    [[ -n "$1" && " $1 " == *" $p "* ]] && continue
    osascript -e "tell application \"System Events\" to set visible of process \"$p\" to false" 2>/dev/null || true
  done
}
backdrop() {
  osascript -e 'tell application "System Events" to set visible of process "Finder" to false' 2>/dev/null || true
  hide_others
  pgrep -f backdrop.py >/dev/null || ( cd $ROOT/executor && uv run python $HERE/backdrop.py >/dev/null 2>&1 & )
  # hide the Dock for the take (restored by `clear`); remember the user's setting once
  [[ -f /tmp/flowline-dock-autohide ]] || defaults read com.apple.dock autohide 2>/dev/null > /tmp/flowline-dock-autohide || echo 0 > /tmp/flowline-dock-autohide
  defaults write com.apple.dock autohide -bool true && killall Dock 2>/dev/null || true
  sleep 1.5
}
restore_dock() {
  if [[ -f /tmp/flowline-dock-autohide ]]; then
    defaults write com.apple.dock autohide -bool "$( [[ $(cat /tmp/flowline-dock-autohide) == 1 ]] && echo true || echo false )" && killall Dock 2>/dev/null || true
    rm -f /tmp/flowline-dock-autohide
  fi
}
reset_app() {  # the app counts "sent to team" from its own records folder: start the take from zero
  pkill -x Flowline 2>/dev/null || true
  rm -f "$HOME/Library/Application Support/Flowline/records/"*.json(N) 2>/dev/null || true
  rm -f "$HOME/Library/Application Support/Flowline/days/"*.jsonl(N) 2>/dev/null || true
  defaults delete co.sweetspot.flowline sent_count 2>/dev/null || true
  defaults delete co.sweetspot.flowline sent_day 2>/dev/null || true
}
case ${1:-sheet} in
  clear)
    pkill -x soffice 2>/dev/null || true
    pkill -f backdrop.py 2>/dev/null || true
    pkill -f "user-data-dir=/tmp/flowline-chrome" 2>/dev/null || true
    restore_dock
    ;;
  sheet)
    pkill -x soffice 2>/dev/null || true; sleep 0.5
    [[ -f $SHEET ]] || { echo "missing $SHEET"; exit 1; }
    reset_app
    osascript -e 'tell application "System Events" to set visible of every process whose visible is true and name is not "Finder" to false' 2>/dev/null || true
    backdrop
    "$SOFFICE" --nologo --norestore --view "$SHEET" >/dev/null 2>&1 &
    sleep 4
    osascript <<'AS' 2>/dev/null || true
tell application "System Events"
  tell process "soffice"
    set frontmost to true
    if (count of windows) > 0 then
      set position of window 1 to {150, 200}
      set size of window 1 to {1180, 620}
    end if
  end tell
end tell
AS
    ;;
  deck)
    pkill -x soffice 2>/dev/null || true; sleep 0.5
    [[ -f $SHEET && -f $DECK ]] || { echo "missing assets"; exit 1; }
    reset_app
    osascript -e 'tell application "System Events" to set visible of every process whose visible is true and name is not "Finder" to false' 2>/dev/null || true
    backdrop
    "$SOFFICE" --nologo --norestore "$SHEET" "$DECK" >/dev/null 2>&1 &
    sleep 6
    osascript <<'AS' 2>/dev/null || true
tell application "System Events"
  tell process "soffice"
    set frontmost to true
    repeat with w in windows
      if name of w contains "pricing" then
        set position of w to {60, 300}
        set size of w to {560, 400}
      else
        set position of w to {500, 260}
        set size of w to {900, 560}
      end if
    end repeat
  end tell
end tell
AS
    ;;
  busy)
    # cut 9: the PM's real working screen — pricing sheet (Calc) + proposal deck (Impress) + the team inbox (Roundcube via the
    # mini's tunnel 3180) in a Chromium-style app window, laid out like a person left them; the notch drops over this
    pkill -x soffice 2>/dev/null || true; sleep 0.5
    [[ -f $SHEET && -f $DECK ]] || { echo "missing assets"; exit 1; }
    reset_app
    osascript -e 'tell application "System Events" to set visible of every process whose visible is true and name is not "Finder" to false' 2>/dev/null || true
    backdrop
    pkill -f "user-data-dir=/tmp/flowline-chrome" 2>/dev/null || true
    rm -rf /tmp/flowline-chrome; mkdir -p /tmp/flowline-chrome/Default
    printf '{"translate":{"enabled":false},"translate_blocked_languages":["en","ko"],"browser":{"has_seen_welcome_page":true}}' > /tmp/flowline-chrome/Default/Preferences
    ( "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=/tmp/flowline-chrome --no-first-run --no-default-browser-check --lang=en-US --disable-features=Translate,TranslateUI \
        --app="${MAIL_URL:-http://localhost:3180/?_task=mail&_fl_user=pm}" --window-size=620,700 --window-position=880,120 >/dev/null 2>&1 & )
    "$SOFFICE" --nologo --norestore "$SHEET" "$DECK" >/dev/null 2>&1 &
    sleep 6
    hide_others "Google Chrome"   # anything that re-surfaced while the windows opened (Slack notifications etc.)
    osascript <<'AS' 2>/dev/null || true
tell application "System Events"
  tell process "soffice"
    repeat with w in windows
      if name of w contains "pricing" then
        set position of w to {40, 330}
        set size of w to {620, 440}
      else
        set position of w to {120, 90}
        set size of w to {900, 560}
      end if
    end repeat
  end tell
end tell
AS
    ;;
  viewer)
    # cut 7: show desk1 (the PM's Linux desktop) in its own Chrome instance; the executor fills the deck there
    pkill -x soffice 2>/dev/null || true
    reset_app
    osascript -e 'tell application "System Events" to set visible of every process whose visible is true and name is not "Finder" to false' 2>/dev/null || true
    backdrop
    pkill -f "user-data-dir=/tmp/flowline-chrome" 2>/dev/null || true
    rm -rf /tmp/flowline-chrome; mkdir -p /tmp/flowline-chrome/Default
    printf '{"translate":{"enabled":false},"translate_blocked_languages":["en","ko"],"browser":{"has_seen_welcome_page":true}}' > /tmp/flowline-chrome/Default/Preferences
    ( "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=/tmp/flowline-chrome --no-first-run --no-default-browser-check --lang=en-US --disable-features=Translate,TranslateUI \
        --app=http://localhost:3101/ --window-size=1512,860 --window-position=0,40 >/dev/null 2>&1 & )
    sleep 5
    osascript -e 'tell application "System Events" to set visible of process "Finder" to false' 2>/dev/null || true
    ;;
  *) echo "usage: $0 sheet|deck|busy|viewer|clear"; exit 1 ;;
esac
echo "staged: $1"
