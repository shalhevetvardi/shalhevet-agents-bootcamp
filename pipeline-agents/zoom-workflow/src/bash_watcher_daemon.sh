#!/bin/bash
# ============================================================
# Zoom Bash Watcher Daemon v3
# ============================================================
# Runs as a background process (started by bash_watcher.command).
# Scans ~/Documents/Zoom every 60 seconds for new recordings.
# Copies files to staging, then calls Python pipeline.
# ============================================================

# --- Configuration ---
ZOOM_DIR="$HOME/Documents/Zoom"
WORKFLOW_DIR="$HOME/Applications/zoom-workflow"
STAGING_DIR="$WORKFLOW_DIR/staging"
PROCESSED="$WORKFLOW_DIR/processed_files.json"
LOG="$WORKFLOW_DIR/watcher.log"
SKIP_PATTERN="zoom-workflow|zoom-workflow-local|פרומפטים לחילוץ מתמלולים"
SCAN_INTERVAL=60
SETTLE_TIME=300
MAX_AGE_DAYS=0

# --- Environment ---
export PATH="/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"
set -a
source "$(dirname "$0")/.env"
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
log "🎙️ Zoom Bash Watcher v3 started (daemon mode)"
log "👀 Monitoring: $ZOOM_DIR"
log "   Scan interval: ${SCAN_INTERVAL}s"
log "   Settle time: ${SETTLE_TIME}s"
log "   PID: $$"
log "========================================"

# --- Verify access ---
if ! ls "$ZOOM_DIR" > /dev/null 2>&1; then
    log "❌ ERROR: Cannot access $ZOOM_DIR — no Full Disk Access"
    exit 1
fi

log "✅ Folder access verified"

# --- Main loop ---
scan_count=0
while true; do
    scan_count=$((scan_count + 1))

    # Use a temp file to collect files (avoids subshell issues with process substitution)
    TMPFILE=$(mktemp /tmp/zoom_watcher_XXXXXX)
    
    # Find all audio files — both lowercase and uppercase extensions
    find "$ZOOM_DIR" -type f \( \
        -name "*.m4a" -o -name "*.M4A" -o \
        -name "*.mp3" -o -name "*.MP3" -o \
        -name "*.mp4" -o -name "*.MP4" \
    \) 2>/dev/null | sort > "$TMPFILE" 2>/dev/null

    # Only process m4a and mp3 (not mp4 video files)
    grep -iE '\.(m4a|mp3)$' "$TMPFILE" > "${TMPFILE}.filtered" 2>/dev/null
    mv "${TMPFILE}.filtered" "$TMPFILE" 2>/dev/null

    found_waiting=0
    while IFS= read -r audio_file; do
        # Skip excluded directories
        case "$audio_file" in
            *zoom-workflow*|*zoom-workflow-local*|*"פרומפטים לחילוץ מתמלולים"*) continue ;;
        esac
        
        # Skip hidden files/folders
        case "$audio_file" in
            */.*) continue ;;
        esac

        # Normalize path (replace $HOME with ~)
        norm_path="~${audio_file#$HOME}"

        # Check if already processed
        if is_processed "$norm_path"; then continue; fi

        # Check file age
        file_mod=$(stat -f %m "$audio_file" 2>/dev/null)
        [ -z "$file_mod" ] && continue
        now=$(date +%s)
        age=$(( now - file_mod ))

        # Skip files older than MAX_AGE_DAYS
        if [ "$MAX_AGE_DAYS" -gt 0 ] && [ "$age" -gt $(( MAX_AGE_DAYS * 86400 )) ]; then
            continue
        fi

        # Must be settled
        if [ "$age" -lt "$SETTLE_TIME" ]; then
            if [ "$found_waiting" -eq 0 ]; then
                remaining=$(( SETTLE_TIME - age ))
                log "⏳ Waiting: $(basename "$audio_file") (${remaining}s remaining)"
                found_waiting=1
            fi
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

        log "🆕 New recording: $subfolder / $filename"

        # Stage the file
        safe_subfolder=$(echo "$subfolder" | tr '/' '_')
        mkdir -p "$STAGING_DIR/$safe_subfolder"
        if ! cp "$audio_file" "$STAGING_DIR/$safe_subfolder/$filename" 2>/dev/null; then
            log "❌ Copy failed: $filename"
            continue
        fi
        staged="$STAGING_DIR/$safe_subfolder/$filename"

        log "📋 Processing: $subfolder"

        # Call pipeline (90 min max via background + kill)
        cd "$WORKFLOW_DIR"
        /usr/bin/python3 zoom_pipeline.py \
            --file "$staged" \
            --track-as "$norm_path" \
            --folder-name "$subfolder" >> "$LOG" 2>&1 &
        PY_PID=$!

        # Wait up to 5400 seconds (90 min — enough for large files split into many chunks)
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
            log "✅ Done: $subfolder"
        elif [ $exit_code -eq 124 ]; then
            log "⏰ Timeout: $subfolder (exceeded 90 min)"
        else
            log "❌ Pipeline failed: $subfolder (exit code $exit_code)"
        fi

    done < "$TMPFILE"

    rm -f "$TMPFILE" 2>/dev/null

    # Heartbeat every 30 scans (~30 minutes)
    if [ $((scan_count % 30)) -eq 0 ]; then
        log "💓 Heartbeat: scan #$scan_count, still watching..."
    fi

    sleep "$SCAN_INTERVAL"
done
