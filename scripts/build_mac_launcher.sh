#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app_path="$repo_root/Traceback.app"
old_stop_app="$repo_root/Stop Traceback.app"
tmp_dir="$(mktemp -d /tmp/traceback-icon.XXXXXX)"
iconset="$tmp_dir/Traceback.iconset"
trap 'rm -rf "$tmp_dir"' EXIT

if [[ -e "$old_stop_app" ]]; then
  if [[ ! -f "$old_stop_app/Contents/Resources/traceback-generated" ]]; then
    echo "Refusing to remove an app not created by this script: $old_stop_app" >&2
    exit 1
  fi
  rm -rf "$old_stop_app"
fi

if [[ -e "$app_path" ]]; then
  if [[ ! -f "$app_path/Contents/Resources/traceback-generated" ]]; then
    echo "Refusing to replace an app not created by this script: $app_path" >&2
    exit 1
  fi
  rm -rf "$app_path"
fi

osacompile -s -o "$app_path" "$repo_root/scripts/mac/Traceback.applescript"
touch "$app_path/Contents/Resources/traceback-generated"
node "$repo_root/scripts/mac/build_icon.cjs" "$iconset"
iconutil -c icns "$iconset" -o "$app_path/Contents/Resources/Traceback.icns"
plist="$app_path/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile Traceback.icns' "$plist"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIconName' "$plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string local.traceback.launcher' "$plist"
rm -f "$app_path/Contents/Resources/Assets.car" "$app_path/Contents/Resources/applet.icns"
codesign --force --deep --sign - "$app_path" >/dev/null
touch "$app_path"
echo "Created $app_path"
