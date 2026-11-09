#!/usr/bin/env bash
# Flowline team mail: greenmail (SMTP/IMAP) + Roundcube on the Mac mini's docker, next to the desks on `flownet`.
#
#   scripts/mail.sh up            start `mail` (greenmail) and `webmail` (Roundcube); idempotent
#   scripts/mail.sh down          stop + remove both containers (mailboxes are in-memory: they are gone; Roundcube's
#                                 sqlite prefs volume `flowline_webmail_db` stays). Config edits: `down` then `up`
#                                 (bind-mounted dir, re-read on start)
#   scripts/mail.sh status        containers, ports, SMTP/IMAP/HTTP checks
#   scripts/mail.sh seed          older threads in every inbox (executor/mail.py seed, run on the mini)
#   scripts/mail.sh reset [user]  empty one mailbox (login or address) or all of them
#   scripts/mail.sh desks [N | deskX ...]  pinned, logged-in Chromium app window "… Inbox" on each desk (default 1..6),
#                                 screenshot → data/mail/deskN.png (copied back to the laptop)
#   scripts/mail.sh desks-down [N | deskX ...]  close those windows
#   scripts/mail.sh attach-test deskN [path]  prove the GUI attach path on one desk: Compose → Attach → ctrl+L → type the
#                                 path → click the Open BUTTON (Enter/double-click do not deliver the file in this Chromium+GTK) →
#                                 upload POST in the webmail log + screenshot data/mail/deskN-attach.png
#
# Runs on the mini (docker at /opt/homebrew/bin/docker) or from the laptop: without a local docker the script copies
# executor/mail.py + executor/assets/mail to mini:~/flowline and re-executes itself over `ssh $FLOWLINE_DESK_HOST`.
#
# Everything company-specific comes from the environment (defaults = the Northwind demo):
#   FLOWLINE_MAIL_DOMAIN   mail domain (northwind.local)       FLOWLINE_MAIL_TITLE  Roundcube product name = window title prefix
#   FLOWLINE_MAIL_USERS    logins, comma-separated; index i ↔ desk i (pm,finance,sales,ops,studio,director) — pre-created in
#                          greenmail and the only accounts `seed` fills (the six Northwind demo users). Any other
#                          login@domain works too: auth is disabled and greenmail creates mailboxes on first use.
#   FLOWLINE_MAIL_SMTP_PORT / FLOWLINE_MAIL_IMAP_PORT / FLOWLINE_MAIL_API_PORT / FLOWLINE_WEBMAIL_PORT  published on the
#                          docker host's 127.0.0.1 (3025 / 3143 / 3081 / 3180)
# From the desks: host `mail` (3025/3143) and http://webmail/ . Shared test password: executor/MAIL.md.
set -euo pipefail

HOST="${FLOWLINE_DESK_HOST:-mini}"
NET="flownet"
GREENMAIL_IMAGE="${FLOWLINE_GREENMAIL_IMAGE:-greenmail/standalone:2.1.3}"
ROUNDCUBE_IMAGE="${FLOWLINE_ROUNDCUBE_IMAGE:-roundcube/roundcubemail:1.6.11-apache}"
DOMAIN="${FLOWLINE_MAIL_DOMAIN:-northwind.local}"
MAIL_TITLE="${FLOWLINE_MAIL_TITLE:-Northwind Mail}"
PASSWORD="${FLOWLINE_MAIL_PASSWORD:-flowline}"
SMTP_PORT="${FLOWLINE_MAIL_SMTP_PORT:-3025}"
IMAP_PORT="${FLOWLINE_MAIL_IMAP_PORT:-3143}"
API_PORT="${FLOWLINE_MAIL_API_PORT:-3081}"
WEBMAIL_PORT="${FLOWLINE_WEBMAIL_PORT:-3180}"
IFS=',' read -r -a USERS <<< "${FLOWLINE_MAIL_USERS:-pm,finance,sales,ops,studio,director}"   # index i-1 ↔ deskN
DEFAULT_N="${#USERS[@]}"

cmd="${1:-status}"; shift || true

if [ -n "${FLOWLINE_ROOT:-}" ]; then ROOT="$FLOWLINE_ROOT"
elif [ -f "$0" ]; then ROOT="$(cd "$(dirname "$0")/.." && pwd)"
else ROOT="$HOME/flowline"; fi   # piped over ssh: $0 is "bash"
if [ -x /opt/homebrew/bin/docker ]; then DOCKER=/opt/homebrew/bin/docker
elif command -v docker >/dev/null 2>&1; then DOCKER="$(command -v docker)"
else DOCKER=""; fi

if [ "$HOST" != "local" ] && [ "$HOST" != "localhost" ]; then
  # laptop: ship the files the mini needs, then run there
  tar -C "$ROOT" -cf - executor/mail.py executor/assets/mail | ssh "$HOST" 'mkdir -p flowline && tar -xf - -C flowline'
  ssh "$HOST" "FLOWLINE_DESK_HOST=local FLOWLINE_ROOT=\$HOME/flowline FLOWLINE_MAIL_PASSWORD=$(printf '%q' "$PASSWORD") \
    FLOWLINE_MAIL_DOMAIN=$(printf '%q' "$DOMAIN") FLOWLINE_MAIL_TITLE=$(printf '%q' "$MAIL_TITLE") FLOWLINE_MAIL_USERS=$(printf '%q' "$(IFS=,; echo "${USERS[*]}")") \
    FLOWLINE_MAIL_SMTP_PORT=$SMTP_PORT FLOWLINE_MAIL_IMAP_PORT=$IMAP_PORT FLOWLINE_MAIL_API_PORT=$API_PORT FLOWLINE_WEBMAIL_PORT=$WEBMAIL_PORT \
    bash -s -- $(printf '%q ' "$cmd" "$@")" < "$0"
  rc=$?
  if [ "$cmd" = "desks" ] || [ "$cmd" = "attach-test" ]; then  # bring the screenshots home
    mkdir -p "$ROOT/data/mail"
    scp -q "$HOST:flowline/data/mail/desk*.png" "$ROOT/data/mail/" 2>/dev/null && echo "screenshots → $ROOT/data/mail/" || true
  fi
  exit $rc
fi
[ -n "$DOCKER" ] || { echo "no docker on this host (FLOWLINE_DESK_HOST=$HOST)" >&2; exit 1; }

d() { "$DOCKER" "$@"; }
exists() { d inspect "$1" >/dev/null 2>&1; }
running() { [ "$(d inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }
dx() { local c="$1"; shift; d exec -u abc -e DISPLAY=:1 -e HOME=/config "$c" sh -c "$*"; }
ASSETS="$ROOT/executor/assets/mail"
MAILPY="$ROOT/executor/mail.py"
PY="$(command -v python3 || echo /usr/bin/python3)"

greenmail_users() {  # login:password@domain,…
  local out="" u
  for u in "${USERS[@]}"; do out="${out:+$out,}${u}:${PASSWORD}@${DOMAIN}"; done
  printf '%s' "$out"
}

up_mail() {
  if running mail; then echo "  mail: already running"; return 0; fi
  exists mail && d rm -f mail >/dev/null
  d network inspect "$NET" >/dev/null 2>&1 || d network create "$NET" >/dev/null
  echo "  mail: starting $GREENMAIL_IMAGE"
  d run -d --name mail --network "$NET" --restart unless-stopped \
    -p 127.0.0.1:$SMTP_PORT:3025 -p 127.0.0.1:$IMAP_PORT:3143 -p 127.0.0.1:$API_PORT:8080 \
    -e GREENMAIL_OPTS="-Dgreenmail.setup.test.all -Dgreenmail.hostname=0.0.0.0 -Dgreenmail.auth.disabled -Dgreenmail.users.login=email -Dgreenmail.users=$(greenmail_users) -Dgreenmail.verbose=false" \
    "$GREENMAIL_IMAGE" >/dev/null
  local i
  for i in $(seq 1 40); do
    if IMAP_PORT="$IMAP_PORT" "$PY" - <<'PY' 2>/dev/null; then echo "  mail: SMTP $SMTP_PORT / IMAP $IMAP_PORT up"; return 0; fi
import os, socket; s=socket.create_connection(("127.0.0.1",int(os.environ["IMAP_PORT"])),1); b=s.recv(200); s.close(); assert b.startswith(b"* OK")
PY
    sleep 0.5
  done
  echo "  mail: IMAP did not answer in 20 s" >&2; d logs --tail 20 mail >&2; return 1
}

up_webmail() {
  if running webmail; then echo "  webmail: already running"; return 0; fi
  exists webmail && d rm -f webmail >/dev/null
  [ -f "$ASSETS/roundcube.inc.php" ] || { echo "missing $ASSETS/roundcube.inc.php" >&2; return 1; }
  echo "  webmail: starting $ROUNDCUBE_IMAGE"
  d run -d --name webmail --network "$NET" --restart unless-stopped \
    -p 127.0.0.1:$WEBMAIL_PORT:80 \
    -e FLOWLINE_MAIL_DOMAIN="$DOMAIN" -e FLOWLINE_MAIL_TITLE="$MAIL_TITLE" \
    -e ROUNDCUBEMAIL_DEFAULT_HOST=mail -e ROUNDCUBEMAIL_DEFAULT_PORT=3143 \
    -e ROUNDCUBEMAIL_SMTP_SERVER=mail -e ROUNDCUBEMAIL_SMTP_PORT=3025 \
    -e ROUNDCUBEMAIL_DB_TYPE=sqlite -e ROUNDCUBEMAIL_SKIN=elastic \
    -e ROUNDCUBEMAIL_PLUGINS=archive,zipdownload,flowline_autologin \
    -e ROUNDCUBEMAIL_UPLOAD_MAX_FILESIZE=20M -e FLOWLINE_MAIL_PASSWORD="$PASSWORD" \
    -v "$ASSETS:/var/roundcube/config:ro" \
    -v "$ASSETS/flowline_autologin:/var/www/html/plugins/flowline_autologin:ro" \
    -v flowline_webmail_db:/var/roundcube/db \
    "$ROUNDCUBE_IMAGE" >/dev/null
  local i
  for i in $(seq 1 60); do
    if curl -fsS -o /dev/null http://127.0.0.1:$WEBMAIL_PORT/ 2>/dev/null; then echo "  webmail: http://127.0.0.1:$WEBMAIL_PORT up"; return 0; fi
    sleep 1
  done
  echo "  webmail: no answer on $WEBMAIL_PORT in 60 s" >&2; d logs --tail 20 webmail >&2; return 1
}

status() {
  printf '%-8s %-10s %s\n' NAME STATE PORTS
  for c in mail webmail; do
    if exists "$c"; then printf '%-8s %-10s %s\n' "$c" "$(d inspect -f '{{.State.Status}}' "$c")" "$(d port "$c" 2>/dev/null | tr '\n' ' ')"
    else printf '%-8s %-10s\n' "$c" absent; fi
  done
  SMTP_PORT="$SMTP_PORT" IMAP_PORT="$IMAP_PORT" "$PY" - <<'PY' || true
import os, socket
for name, port in (("SMTP", int(os.environ["SMTP_PORT"])), ("IMAP", int(os.environ["IMAP_PORT"]))):
    try:
        s = socket.create_connection(("127.0.0.1", port), 2); b = s.recv(200).decode(errors="replace").strip(); s.close()
        print(f"  {name} {port}: {b[:70]}")
    except OSError as e:
        print(f"  {name} {port}: DOWN ({e})")
PY
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$WEBMAIL_PORT/ 2>/dev/null || echo 000)
  echo "  Roundcube $WEBMAIL_PORT: HTTP $code"
  if running webmail; then
    d exec webmail sh -c 'ls /var/www/html/plugins/flowline_autologin/flowline_autologin.php >/dev/null 2>&1 && echo "  autologin plugin: mounted" || echo "  autologin plugin: MISSING"'
  fi
}

# ---- desks ---------------------------------------------------------------------------------------------------------
desk_user() { local n="${1#desk}"; echo "${USERS[$((n - 1))]}"; }

desk_up() {  # pinned Chromium app window with that person's inbox, logged in through the autologin plugin
  local c="$1" user; user="$(desk_user "$c")"
  running "$c" || { echo "  $c: not running — later"; return 0; }
  local url="http://webmail/?_task=mail&_fl_user=${user}"
  if dx "$c" 'pgrep -u abc -f "user-data-dir=/config/[.]flowline-mail" >/dev/null'; then
    echo "  $c: inbox window already up ($user)"
  else
    echo "  $c: opening inbox for ${user}@${DOMAIN}"
    dx "$c" "rm -f /config/.flowline-mail/SingletonLock /config/.flowline-mail/SingletonSocket /config/.flowline-mail/SingletonCookie 2>/dev/null; \
      GTK_THEME=Greybird nohup chromium --app='$url' --user-data-dir=/config/.flowline-mail --class=FlowlineMail \
        --no-first-run --no-default-browser-check --disable-session-crashed-bubble --hide-crash-restore-bubble \
        --disable-infobars --test-type --no-sandbox --password-store=basic --disable-features=TranslateUI,MediaRouter \
        --disable-background-networking --disable-component-update --lang=en-US \
        --window-size=1360,860 --window-position=140,70 >/config/.flowline-mail.log 2>&1 &"
  fi
  # wait for the Inbox title
  local i ok=0
  for i in $(seq 1 45); do
    if dx "$c" 'wmctrl -l 2>/dev/null | grep -q "Inbox"'; then ok=1; break; fi
    sleep 1
  done
  if [ "$ok" = 1 ]; then
    # normal window: not maximised, not fullscreen; keep it on every workspace so it is never lost
    dx "$c" 'wid=$(wmctrl -l | grep "Inbox" | head -1 | cut -d" " -f1); wmctrl -i -r "$wid" -b remove,maximized_vert,maximized_horz,fullscreen; wmctrl -i -r "$wid" -b add,sticky; wmctrl -i -a "$wid"' || true
    echo "  $c: $(dx "$c" 'wmctrl -l | grep Inbox | head -1 | cut -d" " -f5-')"
  else
    echo "  $c: no window titled Inbox after 45 s (see /config/.flowline-mail.log in the container)" >&2
    dx "$c" 'wmctrl -l' >&2 || true
  fi
  sleep 3   # let the page paint before the screenshot
  mkdir -p "$ROOT/data/mail"
  dx "$c" 'scrot -o /tmp/mail-shot.png' && d cp "$c:/tmp/mail-shot.png" "$ROOT/data/mail/$c.png" && echo "  $c: screenshot data/mail/$c.png"
  [ "$ok" = 1 ]
}

desk_down() {
  local c="$1"
  running "$c" || return 0
  dx "$c" 'pkill -u abc -f "user-data-dir=/config/[.]flowline-mail" 2>/dev/null; true'
  echo "  $c: inbox window closed"
}

attach_test() {  # drive one attach through the GUI exactly the way that works (see MAIL.md) and prove it in the webmail log
  local c="$1" path="${2:-/config/Documents/pricing-sheet.ods}"
  running "$c" || { echo "  $c: not running" >&2; return 1; }
  dx "$c" "wmctrl -l | grep -q '$MAIL_TITLE'" || { echo "  $c: no mail window — scripts/mail.sh desks $c first" >&2; return 1; }
  local before; before=$(d logs webmail 2>&1 | grep -c "_action=upload")
  # window geometry → absolute coordinates (the window may have been moved)
  local geo; geo=$(dx "$c" "xdotool search --name '$MAIL_TITLE' | head -1 | xargs -I{} xdotool getwindowgeometry --shell {}")
  local WX WY; WX=$(echo "$geo" | sed -n 's/^X=//p'); WY=$(echo "$geo" | sed -n 's/^Y=//p')
  if ! dx "$c" 'wmctrl -l | grep -q "Mail :: Compose"'; then
    dx "$c" "xdotool search --name '$MAIL_TITLE' | head -1 | xargs xdotool windowactivate --sync; xdotool mousemove $((WX + 38)) $((WY + 80)) click 1"   # Compose (left rail)
    sleep 2.5
  fi
  dx "$c" 'wmctrl -l | grep -q "Mail :: Compose"' || { echo "  $c: compose view did not open" >&2; return 1; }
  dx "$c" "xdotool mousemove $((WX + 443)) $((WY + 18)) click 1"   # Attach (toolbar)
  sleep 2
  dx "$c" 'xdotool search --name "Open Files" | head -1 | grep -q .' || { echo "  $c: file chooser did not open" >&2; return 1; }
  dx "$c" "xdotool key ctrl+l; sleep 0.4; xdotool type --delay 30 '$path'; sleep 1.2"
  # click the Open button (bottom-right of the chooser), never Return: Return/double-click close the chooser without a file
  local dg; dg=$(dx "$c" 'xdotool search --name "Open Files" | head -1 | xargs -I{} xdotool getwindowgeometry --shell {}')
  local DX DY DW DH; DX=$(echo "$dg" | sed -n 's/^X=//p'); DY=$(echo "$dg" | sed -n 's/^Y=//p'); DW=$(echo "$dg" | sed -n 's/^WIDTH=//p'); DH=$(echo "$dg" | sed -n 's/^HEIGHT=//p')
  dx "$c" "xdotool mousemove $((DX + DW - 58)) $((DY + DH - 22)) click 1"
  sleep 3
  local after; after=$(d logs webmail 2>&1 | grep -c "_action=upload")
  mkdir -p "$ROOT/data/mail"
  dx "$c" 'scrot -o /tmp/mail-attach.png' && d cp "$c:/tmp/mail-attach.png" "$ROOT/data/mail/$c-attach.png"
  if [ "$after" -gt "$before" ]; then
    echo "  $c: OK — upload POST seen ($((after - before)) new) for $(basename "$path"); screenshot data/mail/$c-attach.png"
    d logs --since 20s webmail 2>&1 | grep "_action=upload" | awk '{print "    " $1, $4, $9}'
  else
    echo "  $c: FAIL — no upload POST in the webmail log; chooser still open: $(dx "$c" 'xdotool search --name "Open Files" | wc -l'); screenshot data/mail/$c-attach.png" >&2
    return 1
  fi
}

desk_names() {
  if [ $# -gt 0 ] && [[ "$1" == desk* ]]; then echo "$@"
  else local n="${1:-$DEFAULT_N}"; for i in $(seq 1 "$n"); do echo "desk$i"; done; fi
}

# ---- commands --------------------------------------------------------------------------------------------------
case "$cmd" in
  up) up_mail; up_webmail; status ;;
  down) for c in webmail mail; do exists "$c" && { echo "  removing $c"; d rm -f "$c" >/dev/null; }; done; status ;;
  status) status ;;
  seed) running mail || { echo "mail is not running — scripts/mail.sh up first" >&2; exit 1; }   # Northwind demo users only (mail.py DEMO_PEOPLE)
        (cd "$(dirname "$MAILPY")" && FLOWLINE_MAIL_DOMAIN="$DOMAIN" FLOWLINE_MAIL_SMTP_PORT="$SMTP_PORT" FLOWLINE_MAIL_IMAP_PORT="$IMAP_PORT" "$PY" "$MAILPY" seed | "$PY" -c 'import json,sys; m=json.load(sys.stdin); print(f"seeded {len(m)} messages"); [print("  ", x["to"], "←", x["subject"]) for x in m]') ;;
  reset) (cd "$(dirname "$MAILPY")" && FLOWLINE_MAIL_DOMAIN="$DOMAIN" FLOWLINE_MAIL_SMTP_PORT="$SMTP_PORT" FLOWLINE_MAIL_IMAP_PORT="$IMAP_PORT" "$PY" "$MAILPY" reset "${1:-all}") ;;
  desks) fail=0; for c in $(desk_names "$@"); do desk_up "$c" || fail=1; done; [ "$fail" = 0 ] ;;
  desks-down) for c in $(desk_names "$@"); do desk_down "$c"; done ;;
  attach-test) [ -n "${1:-}" ] || { echo "usage: mail.sh attach-test deskN [path]" >&2; exit 2; }; attach_test "$1" "${2:-}" ;;
  *) sed -n '2,20p' "$0" >&2; exit 2 ;;
esac
