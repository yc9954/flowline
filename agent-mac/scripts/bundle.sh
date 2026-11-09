#!/bin/bash
# Build the Swift package and wrap it as build/Flowline.app (menu-bar only, no Dock icon), ad-hoc signed.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="${1:-release}"
out=$(swift build -c "$CONFIG" 2>&1); rc=$?
echo "$out" | grep -vE '^\[|Compiling|Emitting|Write|Planning|Linking' || true
[ "$rc" -eq 0 ] || { echo "swift build failed" >&2; exit 1; }
BIN=".build/$CONFIG/Flowline"
RES=".build/$CONFIG/Flowline_Flowline.bundle"
[ -x "$BIN" ] || { echo "build failed: $BIN missing" >&2; exit 1; }

APP="build/Flowline.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/Flowline"
[ -d "$RES" ] && cp -R "$RES" "$APP/Contents/Resources/"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Flowline</string>
  <key>CFBundleDisplayName</key><string>Flowline</string>
  <key>CFBundleIdentifier</key><string>co.sweetspot.flowline</string>
  <key>CFBundleExecutable</key><string>Flowline</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSAccessibilityUsageDescription</key>
  <string>Flowline reads the title of the window you are working in to note your work steps. Titles are hashed and name-masked on this Mac and never leave it until you approve a record.</string>
  <key>NSAppleEventsUsageDescription</key>
  <string>Flowline asks Safari or Chrome for the current site name so banking and health sites can be left out of your record.</string>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

# Set CODESIGN_IDENTITY to a stable self-signed "Code Signing" certificate (Keychain Access → Certificate
# Assistant) so Accessibility/Automation grants and keychain items survive rebuilds. Default: ad-hoc.
codesign --force --sign "${CODESIGN_IDENTITY:--}" "$APP"
echo "built $APP"
echo "run:   open $APP --args --demo-day --eod-now"
