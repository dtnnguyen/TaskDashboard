#!/bin/sh
# Shortcut for the TaskDashboard command line on macOS and Linux. Works from any folder:
#   ./td config --data ~/Documents/TaskDashboard
#   ./td build --open
# Same as: PYTHONPATH=src python3 -m taskdashboard ...
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m taskdashboard "$@"
