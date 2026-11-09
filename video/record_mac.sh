#!/bin/zsh
# Record this Mac's screen for one cut. usage: record_mac.sh NN seconds
# Output: out/cuts/NN.mov (3024×1964 Retina, build.py crops to 16:9 and scales to 1920×1080).
set -e
HERE=${0:a:h}
N=$(printf '%02d' "$1"); SECS=${2:-12}
mkdir -p "$HERE/out/cuts"
# Device index of "Capture screen 0" as listed by ffmpeg -f avfoundation -list_devices true -i ""
DEV=${FLOWLINE_SCREEN_DEV:-2}
ffmpeg -hide_banner -loglevel error -y -f avfoundation -framerate 30 -capture_cursor 1 -capture_mouse_clicks 0 \
  -i "${DEV}:none" -t "$SECS" -c:v libx264 -preset ultrafast -crf 16 -pix_fmt yuv420p "$HERE/out/cuts/$N.mov"
echo "recorded out/cuts/$N.mov ($SECS s)"
