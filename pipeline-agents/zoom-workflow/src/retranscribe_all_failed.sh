#!/bin/bash
# מחק דפי Notion ריקים ומריץ מחדש את הפייפליין על כל הקבצים שלא תומללו

set -e

set -a
source "$(dirname "$0")/.env"
set +a
NOTION_KEY="$NOTION_API_KEY"
PROCESSED="$HOME/Applications/zoom-workflow/processed_files.json"
PIPELINE="$HOME/Applications/zoom-workflow/zoom_pipeline.py"

# -------------------------------------------------------------------
# שלב 1 — ארכיב דפי Notion ריקים
# -------------------------------------------------------------------
echo "=== שלב 1: ארכיב דפי Notion ==="

archive_notion() {
    local page_id="$1"
    local title="$2"
    curl -s -X PATCH "https://api.notion.com/v1/pages/$page_id" \
        -H "Authorization: Bearer $NOTION_KEY" \
        -H "Notion-Version: 2022-06-28" \
        -H "Content-Type: application/json" \
        -d '{"archived": true}' > /dev/null
    echo "  ✅ ארכב: $title ($page_id)"
}

archive_notion "32e13b4c-3d78-8134-86a7-d5b12fecef9d" "פגישה פנימית (24 מרץ)"
archive_notion "32e13b4c-3d78-818a-b6a4-d6fda7556d78" "קורס AI מחזור 49 — בוקר"
archive_notion "32e13b4c-3d78-81a4-b623-ebe8941a6334" "פגישה עם Joana Frank"
archive_notion "32e13b4c-3d78-81cd-8509-c1896e910e18" "פגישה פנימית (Recording Shalhevet)"

# -------------------------------------------------------------------
# שלב 2 — הסר מ-processed_files.json
# -------------------------------------------------------------------
echo ""
echo "=== שלב 2: ניקוי processed_files.json ==="

python3 - "$PROCESSED" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)

keys_to_remove = [k for k in d if any(x in k for x in [
    "2026-03-24 18.01.53",
    "2026-03-22 10.06.10",
    "2026-03-25 12.13.56 Joana Frank",
    "Recording Shalhevet",
])]

for k in keys_to_remove:
    del d[k]
    print(f"  ✅ הוסר: {k}")

with open(path, 'w') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print(f"  סה\"כ הוסרו: {len(keys_to_remove)} רשומות")
PYEOF

# -------------------------------------------------------------------
# שלב 3 — הרץ פייפליין על כל קובץ
# -------------------------------------------------------------------
echo ""
echo "=== שלב 3: הרצת פייפליין ==="

run_pipeline() {
    local file="$1"
    local track_as="$2"
    local folder="$3"
    echo ""
    echo "--- מתמלל: $track_as ---"
    cd "$HOME/Applications/zoom-workflow"
    python3 "$PIPELINE" \
        --file "$file" \
        --track-as "$track_as" \
        --folder-name "$folder"
}

run_pipeline \
    "$HOME/Documents/Zoom/2026-03-24 18.01.53 אימפרוב בינה מלאכותית's Zoom Meeting/audio1909440231.m4a" \
    "2026-03-24 18.01.53 אימפרוב בינה מלאכותית's Zoom Meeting" \
    "2026-03-24 18.01.53 אימפרוב בינה מלאכותית's Zoom Meeting"

run_pipeline \
    "$HOME/Documents/Zoom/2026-03-22 10.06.10 מחזור 49 - קורס AI - בוקר 10_00/audio1840905519.m4a" \
    "2026-03-22 10.06.10 מחזור 49 - קורס AI - בוקר 10_00" \
    "2026-03-22 10.06.10 מחזור 49 - קורס AI - בוקר 10_00"

run_pipeline \
    "$HOME/Documents/Zoom/2026-03-25 12.13.56 Joana Frank_ Meeting with Shalhevet 30 minutes Zoom/audio1302076169.m4a" \
    "2026-03-25 12.13.56 Joana Frank_ Meeting with Shalhevet 30 minutes Zoom" \
    "2026-03-25 12.13.56 Joana Frank_ Meeting with Shalhevet 30 minutes Zoom"

run_pipeline \
    "$HOME/Documents/Zoom/Recording Shalhevet.m4a" \
    "Recording Shalhevet" \
    "Recording Shalhevet"

echo ""
echo "=== סיום! ==="
