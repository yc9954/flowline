#!/bin/bash
# shot.sh <out.png> [min-width]  — capture the largest on-screen Flowline window (by window id, even when it is behind other apps)
out="$1"; minw="${2:-100}"
id=$("$(dirname "$0")/winids" | awk -v m="$minw" '{ split($4,a,"x"); if (a[1]+0 >= m && a[1]+0 > best) { best=a[1]+0; id=$1 } } END { print id }')
[ -n "$id" ] || { echo "no Flowline window on screen" >&2; exit 1; }
screencapture -x -o -l "$id" "$out" && echo "captured window $id -> $out"
