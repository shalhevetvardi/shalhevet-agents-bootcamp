#!/bin/bash
# ============================================================
# Zoom Bash Watcher Daemon
# ============================================================
# Runs as a background process.
# Scans ~/Documents/Zoom every 60 seconds for new recordings.
# Copies files to staging, then calls Python pipeline.
# ============================================================

# --- Configuration ---
ZOOM_DIR="$HOME/Documents/Zoom"
WORKFLOW_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGING_DIR="$WORKFLOW_DIR/staging"
PROCESSED="$WORKFLOW_DIR/processed_files.json"
LOG="$WORKFLOW_DIR/watcher.log"
SCAN_INTERVAL=60
SETTLE_TIME=300

# --- Environment ---
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"
set -a
source "$WORKFLOW_DIR/.env"
set +a

# --- Setup ---
mkdir -p "$STAGING_DIR"
[ ! -f "$PROCESSED" ] && echo '{}' > "$PROCESSED"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [BASH-WATCHER] $1" >> "$LOG"
}

is_processed() {
    grep -qF "\"$1\"" "$PROCESSED" 2>/dev/null
}

log "========================================"
log "Zoom Bash Watcher started (daemon mode)"
log "Monitoring: $ZOOM_DIR"
log "   Scan interval: ${SCAN_INTERVAL}s"
log "   Settle time: ${SETTLE_TIME}s"
log "   PID: $$"
log "========================================"

# --- Verify access ---
if ! ls "$ZOOM_DIR" > /dev/null 2>&1; then
    log "ERROR: Cannot access $ZOOM_DIR"
    exit 1
fi

log "Folder access verified"

# --- Main loop ---
scan_count=0
while true; do
    scan_count=$((scan_count + 1))

    TMPFILE=$(mktemp /tmp/zoom_watcher_XXXXXX)
    
    find "$ZOOM_DIR" -type f \( \
        -name "*.m4a" -o -name "*.M4A" -o \
        -name "*.mp3" -o -name "*.MP3" \
    \) 2>/dev/null | sort > "$TMPFILE" 2>/dev/null

    while IFS= read -r audio_file; do
        # Skip hidden files/folders
        case "$audio_file" in
            */.*) continue ;;
        esac

        # Normalize path (replace $HOME with ~)
        norm_path="~${audio_file#$HOME}"

        # Check if already processed
        if is_processed "$norm_path"; then continue; fi

        # Check file age — must be settled
        file_mod=$(stat -f %m "$audio_file" 2>/dev/null)
        [ -z "$file_mod" ] && continue
        now=$(date +%s)
        age=$(( now - file_mod ))

        if [ "$age" -lt "$SETTLE_TIME" ]; then
            remaining=$(( SETTLE_TIME - age ))
            log "Waiting: $(basename "$audio_file") (${remaining}s remaining)"
            continue
        fi

        # Get subfolder name
        parent_dir=$(dirname "$audio_file")
        if [ "$parent_dir" = "$ZOOM_DIR" ]; then
            subfolder=$(basename "$audio_file" | sed 's/\.[^.]*$//')
        else
            subfolder=$(basename "$parent_dir")
        fi
        filename=$(basename "$audio_file")

        log "New recording: $subfolder / $filename"

        # Stage the file
        safe_subfolder=$(echo "$subfolder" | tr '/' '_')
        mkdir -p "$STAGING_DIR/$safe_subfolder"
        if ! cp "$audio_file" "$STAGING_DIR/$safe_subfolder/$filename" 2>/dev/null; then
            log "Copy failed: $filename"
            continue
        fi
        staged="$STAGING_DIR/$safe_subfolder/$filename"

        log "Processing: $subfolder"

        # Call pipeline
        cd "$WORKFLOW_DIR"
        /usr/bin/python3 zoom_pipeline.py \
            --file "$staged" \
            --track-as "$norm_path" \
            --folder-name "$subfolder" >> "$LOG" 2>&1 &
        PY_PID=$!

        # Wait up to 90 min
        WAITED=0
        while kill -0 "$PY_PID" 2>/dev/null; do
            sleep 5
            WAITED=$((WAITED + 5))
            if [ "$WAITED" -ge 5400 ]; then
                kill "$PY_PID" 2>/dev/null
                sleep 2
                kill -9 "$PY_PID" 2>/dev/null
                wait "$PY_PID" 2>/dev/null
                exit_code=124
                break
            fi
        done
        if [ "$WAITED" -lt 5400 ]; then
            wait "$PY_PID" 2>/dev/null
            exit_code=$?
        fi

        # Clean up staged file
        rm -f "$staged" 2>/dev/null
        rmdir "$STAGING_DIR/$safe_subfolder" 2>/dev/null

        if [ $exit_code -eq 0 ]; then
            log "Done: $subfolder"
        elif [ $exit_code -eq 124 ]; then
            log "Timeout: $subfolder (exceeded 90 min)"
        else
            log "Pipeline failed: $subfolder (exit code $exit_code)"
        fi

    done < "$TMPFILE"

    rm -f "$TMPFILE" 2>/dev/null

    # Heartbeat every 30 scans
    if [ $((scan_count % 30)) -eq 0 ]; then
        log "Heartbeat: scan #$scan_count, still watching..."
    fi

    sleep "$SCAN_INTERVAL"
done
