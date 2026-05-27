#!/bin/bash
# run_pipeline.sh — עטיפה להרצת הפייפליין (ידני או מ-cron).
# מחליפה ל-working dir, מפעילה venv אם קיים, מריצה את הסקריפט, רושמת ללוג.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# טעינת venv אם קיים
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# וידוא ffmpeg ו-ffprobe (ל-macOS עם brew)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

LOG_FILE="$SCRIPT_DIR/logs/runner.log"
mkdir -p "$SCRIPT_DIR/logs"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START" >> "$LOG_FILE"
python3 sales_pipeline.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] END (exit=$EXIT_CODE)" >> "$LOG_FILE"

exit $EXIT_CODE
