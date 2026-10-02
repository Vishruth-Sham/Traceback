#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app_path="$repo_root/Traceback.app"
old_stop_app="$repo_root/Stop Traceback.app"
tmp_dir="$(mktemp -d /tmp/traceback-icon.XXXXXX)"
iconset="$tmp_dir/Traceback.iconset"
staged_app="$tmp_dir/Traceback.app"
trap 'rm -rf "$tmp_dir"' EXIT

if [[ -e "$old_stop_app" ]]; then
  if [[ ! -f "$old_stop_app/Contents/Resources/traceback-generated" ]]; then
    echo "Refusing to remove an app not created by this script: $old_stop_app" >&2
    exit 1
  fi
fi

if [[ -e "$app_path" ]]; then
  if [[ ! -f "$app_path/Contents/Resources/traceback-generated" ]]; then
    echo "Refusing to replace an app not created by this script: $app_path" >&2
    exit 1
  fi
fi

osacompile -s -o "$staged_app" "$repo_root/scripts/mac/Traceback.applescript"
touch "$staged_app/Contents/Resources/traceback-generated"
node "$repo_root/scripts/mac/build_icon.cjs" "$iconset"
iconutil -c icns "$iconset" -o "$staged_app/Contents/Resources/Traceback.icns"
plist="$staged_app/Contents/Info.plist"
app_version="$(node -e 'process.stdout.write(require(process.argv[1]).version)' "$repo_root/frontend/package.json")"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile Traceback.icns' "$plist"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIconName' "$plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string local.traceback.launcher' "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $app_version" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $app_version" "$plist"
rm -f "$staged_app/Contents/Resources/Assets.car" "$staged_app/Contents/Resources/applet.icns"
codesign --force --deep --sign - "$staged_app" >/dev/null
rm -rf "$app_path" "$old_stop_app"
mv "$staged_app" "$app_path"
touch "$app_path"
echo "Created $app_path"
