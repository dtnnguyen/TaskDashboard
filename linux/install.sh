#!/usr/bin/env bash
# Start the TaskDashboard top-bar icon at login on Ubuntu, and start it now.
#   linux/install.sh                 install
#   linux/install.sh --data DIR      install, keeping your plan, history and page in DIR
#   linux/install.sh --remove        uninstall (your data folder is left alone)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$HOME/.config/autostart/taskdashboard.desktop"
SCRIPT="$ROOT/linux/taskdashboard_indicator.py"

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

if [[ "$ACTION" == remove ]]; then
  rm -f "$DESKTOP"
  pkill -f "$SCRIPT" || true
  echo "Removed $DESKTOP"
  exit 0
fi

# Check the libraries before installing, so a missing package is reported clearly.
if ! /usr/bin/python3 - <<'EOF' 2>/dev/null
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
except ValueError:
    gi.require_version("AppIndicator3", "0.1")
EOF
then
  echo "Missing libraries. Install them with:"
  echo "  sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1"
  exit 1
fi

# --data: remember the folder in the config file, which the top-bar icon reads too.
if [[ -n "$DATA" ]]; then
  PYTHONPATH="$ROOT/src" /usr/bin/python3 -m taskdashboard config --data "$DATA"
fi

# First install: start from the example plan (an existing plan is never touched).
PYTHONPATH="$ROOT/src" /usr/bin/python3 -m taskdashboard init

mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=TaskDashboard
Comment=Goals and % completion in the top bar
Exec=/usr/bin/python3 "$SCRIPT"
Icon=$ROOT/assets/taskdashboard.svg
X-GNOME-Autostart-enabled=true
EOF
echo "Installed $DESKTOP"

pkill -f "$SCRIPT" || true
nohup /usr/bin/python3 "$SCRIPT" >/dev/null 2>&1 &
echo "Started. Look for the target icon and % in the top bar."
