#!/usr/bin/env bash
# Show the TaskDashboard icon in the macOS menu bar (via SwiftBar), and start it now.
#   macos/install.sh                 install (or repair the link after moving the repo)
#   macos/install.sh --data DIR      install, keeping your plan, history and page in DIR
#   macos/install.sh --remove        uninstall (your data folder is left alone)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="$ROOT/macos/taskdashboard.5m.py"

# Options: --remove, or --data DIR to keep your plan, history and page in DIR.
ACTION=install
DATA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove) ACTION=remove ;;
    --data) [[ $# -ge 2 ]] || { echo "--data needs a folder, e.g. --data ~/Documents/TaskDashboard"; exit 1; }
            DATA="$2"; shift ;;
    --data=*) DATA="${1#--data=}" ;;
    *) echo "Unknown option: $1  (use --data DIR or --remove)"; exit 1 ;;
  esac
  shift
done

if [[ ! -d /Applications/SwiftBar.app && ! -d "$HOME/Applications/SwiftBar.app" ]]; then
  echo "SwiftBar is not installed. Install it with:"
  echo "  brew install --cask swiftbar"
  exit 1
fi

# Use SwiftBar's plugin folder if one is set, otherwise set ~/SwiftBarPlugins.
PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
if [[ -z "$PLUGIN_DIR" ]]; then
  PLUGIN_DIR="$HOME/SwiftBarPlugins"
  defaults write com.ameba.SwiftBar PluginDirectory -string "$PLUGIN_DIR"
fi
LINK="$PLUGIN_DIR/$(basename "$PLUGIN")"

if [[ "$ACTION" == remove ]]; then
  rm -f "$LINK"
  open -g "swiftbar://refreshallplugins" 2>/dev/null || true
  echo "Removed $LINK"
  exit 0
fi

# A downloaded release is quarantined by macOS; clear that so SwiftBar can run the plugin.
xattr -dr com.apple.quarantine "$ROOT" 2>/dev/null || true

# --data: remember the folder in the config file, which the menu bar icon reads too.
if [[ -n "$DATA" ]]; then
  PYTHONPATH="$ROOT/src" python3 -m taskdashboard config --data "$DATA"
fi

# First install: start from the example plan (an existing plan is never touched).
PYTHONPATH="$ROOT/src" python3 -m taskdashboard init

mkdir -p "$PLUGIN_DIR"
chmod +x "$PLUGIN"
ln -sfn "$PLUGIN" "$LINK"   # replaces an old link, e.g. after the repo moved
echo "Linked $LINK -> $PLUGIN"

if pgrep -xq SwiftBar; then
  open -g "swiftbar://refreshallplugins"
else
  open -a SwiftBar
fi
echo "Done. Look for 🎯 and the % in the menu bar."
