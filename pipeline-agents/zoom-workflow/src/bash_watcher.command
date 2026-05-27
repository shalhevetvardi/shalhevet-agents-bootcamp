#!/bin/bash
# ============================================================
# Zoom Bash Watcher v3 — Background Mode
# ============================================================
# Starts the daemon in background, then closes Terminal.
# The watcher keeps running even after Terminal closes!
# ============================================================

WORKFLOW_DIR="$HOME/Applications/zoom-workflow"
DAEMON="$WORKFLOW_DIR/bash_watcher_daemon.sh"
LOG="$WORKFLOW_DIR/watcher.log"

# Kill any existing watchers
pkill -f "bash_watcher_daemon.sh" 2>/dev/null
pkill -f "zoom_watcher.py" 2>/dev/null
sleep 1

# Start daemon in background
nohup bash "$DAEMON" >> "$LOG" 2>> "${WORKFLOW_DIR}/watcher_stderr.log" &
DAEMON_PID=$!
disown $DAEMON_PID

echo "🎙️ Zoom Watcher started (PID: $DAEMON_PID)"
echo "   Running in background — safe to close this window."
echo "   Check status: tail -20 ~/Applications/zoom-workflow/watcher.log"
echo ""

# Log to watcher log too
echo "$(date '+%Y-%m-%d %H:%M:%S') [LAUNCHER] Started daemon PID $DAEMON_PID" >> "$LOG"

# Close Terminal window after 3 seconds
sleep 3
osascript -e 'tell application "Terminal" to close front window' 2>/dev/null &
exit 0
