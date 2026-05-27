#!/bin/bash
# retranscribe_failed.sh
# מנקה את הרשומות הכושלות מ-Notion ומ-processed_files, ומריץ אותן מחדש דרך הפייפליין

set -e

WORKFLOW_DIR="$HOME/Applications/zoom-workflow"
ZOOM_DIR="$HOME/Documents/Zoom"
LOG="$WORKFLOW_DIR/watcher.log"
PROCESSED="$WORKFLOW_DIR/processed_files.json"

cd "$WORKFLOW_DIR"

# ─── טעינת משתני סביבה מ-.env ───────────────────────────────────────
set -a
source "$(dirname "$0")/.env"
set +a

NOTION_KEY="$NOTION_API_KEY"
if [ -z "$NOTION_KEY" ]; then
    echo "❌ לא נמצא NOTION_API_KEY ב-.env"
    exit 1
fi

# ─── פונקציות עזר ───────────────────────────────────────────────────
archive_notion_page() {
    local page_id="$1"
    local result
    result=$(curl -s -X PATCH "https://api.notion.com/v1/pages/$page_id" \
        -H "Authorization: Bearer $NOTION_KEY" \
        -H "Notion-Version: 2022-06-28" \
        -H "Content-Type: application/json" \
        -d '{"archived": true}')
    if echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('archived') else 1)" 2>/dev/null; then
        echo "  ✅ ארכב דף Notion: $page_id"
    else
        echo "  ⚠️  בעיה בארכוב $page_id (אולי כבר מארכב)"
    fi
}

remove_from_processed() {
    local key="$1"
    python3 - "$key" "$PROCESSED" <<'PYEOF'
import json, sys
key = sys.argv[1]
processed_path = sys.argv[2]
with open(processed_path, 'r') as f:
    d = json.load(f)
if key in d:
    del d[key]
    with open(processed_path, 'w') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f'  ✅ הוסר מ-processed_files: {key}')
else:
    print(f'  ℹ️  לא היה ב-processed_files: {key}')
PYEOF
}

run_pipeline() {
    local folder_name="$1"
    local audio_filename="$2"
    local audio_path="$ZOOM_DIR/$folder_name/$audio_filename"

    echo ""
    echo "🎙️  מריץ פייפליין: $folder_name"

    if [ ! -f "$audio_path" ]; then
        echo "  ❌ קובץ אודיו לא נמצא: $audio_path"
        return 1
    fi

    local staging_dir="$WORKFLOW_DIR/staging/$folder_name"
    mkdir -p "$staging_dir"
    cp "$audio_path" "$staging_dir/"

    local track_key="~/Documents/Zoom/$folder_name/$audio_filename"

    /usr/bin/python3 zoom_pipeline.py \
        --file "$staging_dir/$audio_filename" \
        --track-as "$track_key" \
        --folder-name "$folder_name" >> "$LOG" 2>&1

    local exit_code=$?
    rm -f "$staging_dir/$audio_filename"
    rmdir "$staging_dir" 2>/dev/null

    if [ $exit_code -eq 0 ]; then
        echo "  ✅ הצלחה!"
    else
        echo "  ❌ נכשל (exit code: $exit_code) — בדקי את watcher.log"
    fi
}

# ════════════════════════════════════════════════════════════════════
echo "========================================"
echo " שלב 1: ניקוי דפי Notion כושלים"
echo "========================================"

# פגישה עם Joana Frank — 2 כפולים
echo "🗑  מארכב כפולי ג'ואנה..."
archive_notion_page "32e13b4c3d78812f8248c42350277e30"
archive_notion_page "32e13b4c3d7881c99ea2cde785aa2dcf"
archive_notion_page "32e13b4c3d7881a08abddfee33891084"

# קורס AI מחזור 49
echo "🗑  מארכב קורס 49..."
archive_notion_page "32b13b4c3d788189a503ecd26eccec0b"
archive_notion_page "32e13b4c3d7881aeb091d9337f8f44e5"

# פגישה פנימית
echo "🗑  מארכב פגישה פנימית..."
archive_notion_page "32d13b4c3d78816680dad9fb6f5172af"
archive_notion_page "32e13b4c3d7881adbaf2dbabc7898a1c"

# ════════════════════════════════════════════════════════════════════
echo ""
echo "========================================"
echo " שלב 2: ניקוי processed_files.json"
echo "========================================"

remove_from_processed "~/Documents/Zoom/2026-03-25 12.13.56 Joana Frank_ Meeting with Shalhevet 30 minutes Zoom/audio1302076169.m4a"
remove_from_processed "~/Documents/Zoom/2026-03-22 10.06.10 מחזור 49 - קורס AI - בוקר 10_00/audio1840905519.m4a"
remove_from_processed "~/Documents/Zoom/2026-03-24 18.01.53 אימפרוב בינה מלאכותית's Zoom Meeting/audio1909440231.m4a"

# ════════════════════════════════════════════════════════════════════
echo ""
echo "========================================"
echo " שלב 3: הרצת פייפליין על ההקלטות"
echo "========================================"

# פגישה פנימית (24/3) — קטנה, ~5 דק'
run_pipeline "2026-03-24 18.01.53 אימפרוב בינה מלאכותית's Zoom Meeting" "audio1909440231.m4a"

# פגישה עם Joana Frank (25/3) — ~6 דק'
run_pipeline "2026-03-25 12.13.56 Joana Frank_ Meeting with Shalhevet 30 minutes Zoom" "audio1302076169.m4a"

# קורס AI מחזור 49 (22/3) — גדול, ~40 דק'
run_pipeline "2026-03-22 10.06.10 מחזור 49 - קורס AI - בוקר 10_00" "audio1840905519.m4a"

echo ""
echo "========================================"
echo " סיום — בדקי את watcher.log לפרטים"
echo "========================================"
