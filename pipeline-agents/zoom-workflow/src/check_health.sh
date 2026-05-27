#!/bin/bash
# ============================================================
# Zoom Pipeline Health Check
# ============================================================
# הריצי בטרמינל: bash ~/Applications/zoom-workflow/check_health.sh
# ============================================================

WORKFLOW_DIR="$HOME/Applications/zoom-workflow"
WATCHER_LOG="$WORKFLOW_DIR/watcher.log"
PIPELINE_LOG="$WORKFLOW_DIR/pipeline.log"
PROCESSED="$WORKFLOW_DIR/processed_files.json"

echo ""
echo "=========================================="
echo "  🔍  בדיקת בריאות — Zoom Pipeline"
echo "=========================================="
echo ""

# --- 1. בדיקה: האם התהליך רץ? ---
echo "1️⃣  תהליך Watcher:"
PIDS=$(pgrep -f "bash_watcher_daemon.sh" 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "   ✅ רץ (PID: $PIDS)"
else
    echo "   ❌ לא רץ! הפעילי עם: open ~/Applications/zoom-workflow/bash_watcher.command"
fi
echo ""

# --- 2. בדיקה: מתי הלוג האחרון? ---
echo "2️⃣  פעילות אחרונה (watcher):"
if [ -f "$WATCHER_LOG" ]; then
    LAST_LINE=$(tail -1 "$WATCHER_LOG")
    LAST_TIME=$(echo "$LAST_LINE" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
    echo "   📝 $LAST_TIME"

    # בדיקה אם הלוג האחרון ישן מדי (יותר מ-5 דקות)
    if [ -n "$LAST_TIME" ]; then
        LAST_EPOCH=$(date -j -f "%Y-%m-%d %H:%M:%S" "$LAST_TIME" "+%s" 2>/dev/null)
        NOW_EPOCH=$(date "+%s")
        if [ -n "$LAST_EPOCH" ]; then
            DIFF=$(( NOW_EPOCH - LAST_EPOCH ))
            if [ "$DIFF" -gt 300 ]; then
                echo "   ⚠️  אזהרה: הלוג האחרון לפני $(( DIFF / 60 )) דקות"
            else
                echo "   ✅ פעיל (לפני $(( DIFF )) שניות)"
            fi
        fi
    fi
else
    echo "   ❌ קובץ לוג לא נמצא"
fi
echo ""

# --- 3. בדיקה: כמה קבצים עובדו? ---
echo "3️⃣  קבצים מעובדים:"
if [ -f "$PROCESSED" ]; then
    COUNT=$(python3 -c "import json; d=json.load(open('$PROCESSED')); print(len(d))" 2>/dev/null)
    echo "   📊 סה\"כ: $COUNT הקלטות עובדו"
else
    echo "   ❌ קובץ processed_files.json לא נמצא"
fi
echo ""

# --- 4. בדיקה: הרצה אחרונה של Pipeline ---
echo "4️⃣  Pipeline — הרצה אחרונה:"
if [ -f "$PIPELINE_LOG" ]; then
    # מחפש את שורת הסיום האחרונה
    LAST_SUCCESS=$(grep "הצלחות" "$PIPELINE_LOG" | tail -1)
    if [ -n "$LAST_SUCCESS" ]; then
        echo "   $LAST_SUCCESS"
    fi

    # בודק אם יש הרצה בתהליך עכשיו
    LAST_START=$(grep "מתחיל הרצה" "$PIPELINE_LOG" | tail -1)
    LAST_END=$(grep "סיום הרצה" "$PIPELINE_LOG" | tail -1)

    START_TIME=$(echo "$LAST_START" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
    END_TIME=$(echo "$LAST_END" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')

    if [ -n "$START_TIME" ] && [ -n "$END_TIME" ]; then
        START_E=$(date -j -f "%Y-%m-%d %H:%M:%S" "$START_TIME" "+%s" 2>/dev/null)
        END_E=$(date -j -f "%Y-%m-%d %H:%M:%S" "$END_TIME" "+%s" 2>/dev/null)
        if [ -n "$START_E" ] && [ -n "$END_E" ] && [ "$START_E" -gt "$END_E" ]; then
            echo "   🔄 יש הרצה פעילה עכשיו! (התחילה $START_TIME)"
        fi
    fi

    # שגיאות אחרונות
    ERRORS=$(grep -c "שגיאות" "$PIPELINE_LOG" 2>/dev/null)
    RECENT_ERRORS=$(tail -100 "$PIPELINE_LOG" | grep -i "error\|שגיא\|❌" | tail -3)
    if [ -n "$RECENT_ERRORS" ]; then
        echo ""
        echo "   ⚠️  שגיאות אחרונות:"
        echo "$RECENT_ERRORS" | while read line; do echo "      $line"; done
    fi
else
    echo "   ❌ קובץ pipeline.log לא נמצא"
fi
echo ""

# --- 5. בדיקה: תיקיית Zoom ---
echo "5️⃣  תיקיית Zoom:"
ZOOM_DIR="$HOME/Documents/Zoom"
if [ -d "$ZOOM_DIR" ]; then
    FOLDER_COUNT=$(find "$ZOOM_DIR" -maxdepth 1 -type d | wc -l | tr -d ' ')
    RECENT=$(find "$ZOOM_DIR" -name "*.m4a" -mtime -7 2>/dev/null | wc -l | tr -d ' ')
    echo "   📁 קיימת ($FOLDER_COUNT תיקיות)"
    echo "   🆕 $RECENT קבצי אודיו מ-7 ימים אחרונים"
else
    echo "   ❌ תיקיית $ZOOM_DIR לא נמצאה"
fi
echo ""

# --- 6. בדיקה: Staging ---
echo "6️⃣  Staging:"
STAGING="$WORKFLOW_DIR/staging"
if [ -d "$STAGING" ]; then
    STAGING_FILES=$(find "$STAGING" -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "   📂 $STAGING_FILES קבצים בעיבוד"
else
    echo "   📂 תיקיית staging לא נמצאה"
fi
echo ""

echo "=========================================="
echo "  ✅  בדיקה הושלמה"
echo "=========================================="
echo ""
