#!/usr/bin/env bash
# Flowline desks: N Linux desktops (flowline/desk:1, linuxserver webtop XFCE) on the Mac mini's docker.
#
#   scripts/desks.sh up [N]      create/start desk1..deskN (default 6) — new desks are cloned from desk1's /config
#   scripts/desks.sh ls          containers, state, viewer ports
#   scripts/desks.sh down [N]    stop desk2..deskN (desk1 stays up; `down all` also stops desk1)
#   scripts/desks.sh reset [N | deskX ...]  close LibreOffice without saving (every desk up to N, or just the named desks),
#                                drop lock files, re-apply the wallpaper
#   scripts/desks.sh rm N        remove deskN (and its /config volume)
#   scripts/desks.sh tunnels [N] (laptop only) ssh -fN -L 310N:localhost:310N mini for each desk
#
# Runs on the mini (docker at /opt/homebrew/bin/docker) or from the laptop: when there is no local docker the
# script re-executes itself over `ssh $FLOWLINE_DESK_HOST` (default `mini`). Viewer for deskN: 127.0.0.1:310N.
#
# desk1 is the template: SELKIES 1920x1080, TZ America/Chicago, shm 1g, network flownet, port 310N→3000, and its
# /config holds what the image does not: Documents/*.ods|odp, flat.png (wallpaper), the LibreOffice profile with
# first-run/tip dialogs disabled (registrymodifications.xcu) and the XFCE channel xml (wallpaper, no desktop icons).
set -euo pipefail

HOST="${FLOWLINE_DESK_HOST:-mini}"
IMAGE="${FLOWLINE_DESK_IMAGE:-flowline/desk:1}"
TEMPLATE="${FLOWLINE_DESK_TEMPLATE:-desk1}"
NET="flownet"
PORT_BASE=3100
DEFAULT_N=6

cmd="${1:-ls}"; shift || true

# ---- where does docker live? -------------------------------------------------------------------------------
if [ -x /opt/homebrew/bin/docker ]; then DOCKER=/opt/homebrew/bin/docker
elif command -v docker >/dev/null 2>&1; then DOCKER="$(command -v docker)"
else DOCKER=""; fi

if [ "$cmd" = "tunnels" ]; then
  n="${1:-$DEFAULT_N}"
  for i in $(seq 1 "$n"); do
    p=$((PORT_BASE + i))
    if pgrep -f "ssh -fN -L ${p}:localhost:${p} ${HOST}" >/dev/null 2>&1; then echo "tunnel ${p} already open"; continue; fi
    ssh -fN -L "${p}:localhost:${p}" "$HOST" && echo "tunnel ${p} → ${HOST}:${p} (desk${i} viewer http://localhost:${p})"
  done
  exit 0
fi

if [ "$HOST" != "local" ] && [ "$HOST" != "localhost" ]; then
  # not on the docker host (the laptop may have its own docker — never touch that one): run this script over ssh
  exec ssh "$HOST" "FLOWLINE_DESK_HOST=local bash -s -- $(printf '%q ' "$cmd" "$@")" < "$0"
fi
[ -n "$DOCKER" ] || { echo "no docker on this host (FLOWLINE_DESK_HOST=$HOST)" >&2; exit 1; }

d() { "$DOCKER" "$@"; }
exists() { d inspect "$1" >/dev/null 2>&1; }
running() { [ "$(d inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }
# shell inside a desk as the desktop user with the X display
dx() { local c="$1"; shift; d exec -u abc -e DISPLAY=:1 -e HOME=/config "$c" sh -c "$*"; }

# ---- helpers ------------------------------------------------------------------------------------------------
wait_desktop() {  # until xfdesktop is up (the webtop has finished its init)
  local c="$1" i
  for i in $(seq 1 90); do
    if dx "$c" 'pgrep -u abc -x xfdesktop >/dev/null' 2>/dev/null; then return 0; fi
    sleep 1
  done
  echo "  $c: xfdesktop did not come up in 90 s" >&2; return 1
}

apply_wallpaper() {  # flat.png on every monitor/workspace variant, no desktop icons; needs the session DBus
  local c="$1"
  dx "$c" '
    pid=$(pgrep -u abc -x xfdesktop | head -1)
    [ -n "$pid" ] || exit 1
    export $(tr "\0" "\n" < /proc/$pid/environ | grep ^DBUS_SESSION_BUS_ADDRESS=)
    for mon in monitorscreen monitor0 monitorVirtual-1; do
      xfconf-query -c xfce4-desktop -p /backdrop/screen0/$mon/workspace0/last-image -n -t string -s /config/flat.png >/dev/null 2>&1 || true
      xfconf-query -c xfce4-desktop -p /backdrop/screen0/$mon/workspace0/image-style -n -t int -s 3 >/dev/null 2>&1 || true
      xfconf-query -c xfce4-desktop -p /backdrop/screen0/$mon/workspace0/color-style -n -t int -s 0 >/dev/null 2>&1 || true
    done
    xfconf-query -c xfce4-desktop -p /desktop-icons/style -n -t int -s 0 >/dev/null 2>&1 || true
    # xfdesktop only re-reads the backdrop on a relaunch with the session env (seen on desk1)
    kill "$pid" 2>/dev/null; sleep 0.5
    nohup xfdesktop >/dev/null 2>&1 &
    sleep 1.5
  ' || { echo "  $c: could not apply the wallpaper" >&2; return 1; }
}

wallpaper_ok() {  # a 2x2 crop of the screen at (960,300) == flat.png colour (#E0E4E6 ±6)
  local c="$1"
  d exec -i -u abc "$c" sh -c 'cat > /tmp/wpcheck.py' <<'PY'
import struct, zlib, sys
data = open("/tmp/wp.png", "rb").read(); pos = 8; idat = b""; w = h = 0; bpp = 3
while pos < len(data):
    n = struct.unpack(">I", data[pos:pos+4])[0]; typ = data[pos+4:pos+8]; body = data[pos+8:pos+8+n]
    if typ == b"IHDR":
        w, h, depth, ctype = struct.unpack(">IIBB", body[:10]); bpp = {2: 3, 6: 4}.get(ctype, 3)
    elif typ == b"IDAT":
        idat += body
    pos += 12 + n
raw = zlib.decompress(idat); stride = w * bpp + 1
line = bytearray(raw[1:stride]); f = raw[0]
for i in range(len(line)):  # first row: only the "Sub" filter can apply (no row above)
    if f == 1 and i >= bpp: line[i] = (line[i] + line[i - bpp]) & 255
    elif f == 3 and i >= bpp: line[i] = (line[i] + line[i - bpp] // 2) & 255
    elif f == 4 and i >= bpp: line[i] = (line[i] + line[i - bpp]) & 255
p = tuple(line[:3])
ok = all(abs(c - t) <= 6 for c, t in zip(p, (0xE0, 0xE4, 0xE6)))
print("pixel", p, "ok" if ok else "NOT flat"); sys.exit(0 if ok else 1)
PY
  dx "$c" 'scrot -a 960,300,2,2 -o /tmp/wp.png >/dev/null 2>&1 && /usr/bin/python3 /tmp/wpcheck.py'
}

seed_config() {  # copy the template's user data into a (created, not yet started) desk
  local c="$1"
  echo "  $c: seeding /config from $TEMPLATE"
  d exec -u abc "$TEMPLATE" sh -c 'cd /config && tar -cf - --exclude="Documents/.~lock*" --exclude=".config/libreoffice/4/.lock" --exclude=".config/libreoffice/4/user/.lock" Documents flat.png .config/libreoffice .config/xfce4 .config/dconf .config/Thunar .config/user-dirs.dirs .config/user-dirs.locale 2>/dev/null' \
    | d cp - "$c:/config"
}

create_desk() {
  local i="$1" c="desk$1" port=$((PORT_BASE + i))
  echo "  $c: creating (viewer 127.0.0.1:$port)"
  d network inspect "$NET" >/dev/null 2>&1 || d network create "$NET" >/dev/null
  d create --name "$c" --network "$NET" --shm-size=1g \
    -e PUID=1000 -e PGID=1000 -e TZ=America/Chicago \
    -e SELKIES_MANUAL_WIDTH=1920 -e SELKIES_MANUAL_HEIGHT=1080 \
    -p "127.0.0.1:${port}:3000" "$IMAGE" >/dev/null
  if exists "$TEMPLATE" && running "$TEMPLATE" && [ "$c" != "$TEMPLATE" ]; then
    seed_config "$c"
  else
    echo "  $c: template $TEMPLATE not running — started bare (no documents, no wallpaper)" >&2
  fi
}

up_one() {
  local i="$1" c="desk$1" fresh=0
  if ! exists "$c"; then create_desk "$i"; fi
  if ! running "$c"; then echo "  $c: starting"; d start "$c" >/dev/null; fresh=1; fi
  wait_desktop "$c" || return 1
  dx "$c" 'command -v xprintidle >/dev/null' || echo "  $c: WARNING xprintidle missing in this image" >&2
  if [ "$fresh" = 1 ]; then  # a desk that was already up may have windows open (someone's run): leave it alone
    if ! wallpaper_ok "$c" >/dev/null 2>&1; then
      apply_wallpaper "$c" || true
      sleep 1
    fi
    if wallpaper_ok "$c" 2>/dev/null | grep -q ok; then echo "  $c: wallpaper ok"; else echo "  $c: wallpaper NOT applied" >&2; fi
  else
    echo "  $c: already running (left untouched)"
  fi
  dx "$c" 'ls /config/Documents | tr "\n" " "' | sed "s/^/  $c: Documents: /"; echo
}

list_desks() {
  printf '%-8s %-10s %-22s %s\n' NAME STATE VIEWER IMAGE
  for c in $(d ps -a --format '{{.Names}}' | grep -E '^desk[0-9]+$' | sort -V); do
    local st port
    st="$(d inspect -f '{{.State.Status}}' "$c")"
    port="$(d inspect -f '{{range $p, $b := .NetworkSettings.Ports}}{{if eq $p "3000/tcp"}}{{(index $b 0).HostIp}}:{{(index $b 0).HostPort}}{{end}}{{end}}' "$c")"
    printf '%-8s %-10s %-22s %s\n' "$c" "$st" "${port:-—}" "$(d inspect -f '{{.Config.Image}}' "$c")"
  done
}

reset_one() {
  local c="$1"
  running "$c" || { echo "  $c: not running"; return 0; }
  echo "  $c: closing LibreOffice without saving"
  dx "$c" 'pkill -f "[s]office.bin" 2>/dev/null; sleep 0.6; pkill -9 -f "[s]office.bin" 2>/dev/null; rm -f /config/.config/libreoffice/4/.lock /config/.config/libreoffice/4/user/.lock /config/Documents/.~lock* 2>/dev/null; true'
  # any stray windows other than the desktop & panel (file manager, dialogs, PDF viewer …)
  dx "$c" 'wmctrl -l 2>/dev/null | while read -r wid d host title; do case "$title" in Desktop|xfce4-panel|Xfwm4|wrapper-*|*Inbox*|*"Northwind Mail"*) ;; *) wmctrl -i -c "$wid" 2>/dev/null || true;; esac; done; sleep 1; true'
  if ! wallpaper_ok "$c" >/dev/null 2>&1; then apply_wallpaper "$c" || true; fi
}

# ---- commands -------------------------------------------------------------------------------------------------
case "$cmd" in
  up)
    n="${1:-$DEFAULT_N}"
    echo "desks up 1..$n (image $IMAGE, template $TEMPLATE)"
    fail=0
    for i in $(seq 1 "$n"); do up_one "$i" || fail=1; done
    list_desks
    [ "$fail" = 0 ] ;;
  ls) list_desks ;;
  down)
    if [ "${1:-}" = "all" ]; then names=$(d ps --format '{{.Names}}' | grep -E '^desk[0-9]+$' || true)
    else n="${1:-$DEFAULT_N}"; names=$(for i in $(seq 2 "$n"); do echo "desk$i"; done); fi
    for c in $names; do running "$c" && { echo "  stopping $c"; d stop -t 5 "$c" >/dev/null; } || true; done
    list_desks ;;
  reset)
    if [ $# -gt 0 ] && [[ "$1" == desk* ]]; then names="$*"
    else n="${1:-$DEFAULT_N}"; names=$(for i in $(seq 1 "$n"); do echo "desk$i"; done); fi
    for c in $names; do exists "$c" && reset_one "$c"; done ;;
  rm)
    [ -n "${1:-}" ] || { echo "usage: desks.sh rm N" >&2; exit 2; }
    c="desk$1"; [ "$c" != "$TEMPLATE" ] || { echo "refusing to remove the template $TEMPLATE" >&2; exit 2; }
    d rm -f -v "$c" >/dev/null && echo "removed $c" ;;
  *) sed -n '2,12p' "$0" >&2; exit 2 ;;
esac
