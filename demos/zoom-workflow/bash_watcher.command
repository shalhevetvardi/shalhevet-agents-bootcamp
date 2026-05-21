#!/bin/bash
# ============================================================
# Zoom Watcher — Start Script
# ============================================================
# Double-click this file to start the watcher.
# It runs in the background — safe to close Terminal after.
# ============================================================

WORKFLOW_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON="$WORKFLOW_DIR/bash_watcher_daemon.sh"
LOG="$WORKFLOW_DIR/watcher.log"

# Kill any existing watchers
pkill -f "bash_watcher_daemon.sh" 2>/dev/null
sleep 1

# Start daemon in background
nohup bash "$DAEMON" >> "$LOG" 2>> "${WORKFLOW_DIR}/watcher_stderr.log" &
DAEMON_PID=$!
disown $DAEMON_PID

echo "Zoom Watcher started (PID: $DAEMON_PID)"
echo "   Running in background — safe to close this window."
echo "   Check status: tail -20 $WORKFLOW_DIR/watcher.log"
echo ""

echo "$(date '+%Y-%m-%d %H:%M:%S') [LAUNCHER] Started daemon PID $DAEMON_PID" >> "$LOG"

sleep 3
exit 0
