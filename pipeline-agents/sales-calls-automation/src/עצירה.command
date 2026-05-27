#!/bin/bash
# ============================================================
#  עצירת האוטומציה — שיחות מכירה
#  מכבה את ההפעלה האוטומטית כל 5 דקות.
#  לא מוחק כלום, רק עוצר.
# ============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PLIST_NAME="com.aimprove.sales-pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

clear
echo ""
echo "════════════════════════════════════════════════════════════"
echo "   ⏸  עצירת האוטומציה"
echo "════════════════════════════════════════════════════════════"
echo ""

if [ -f "$PLIST_PATH" ]; then
    launchctl bootout gui/$(id -u) "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo -e "${GREEN}✓ האוטומציה נעצרה${NC}"
    echo ""
    echo "הפייפליין לא ירוץ יותר אוטומטית."
    echo "להפעלה חוזרת: דאבל-קליק על 'התקנה.command'"
else
    echo -e "${BLUE}ℹ האוטומציה לא הייתה פעילה בכלל${NC}"
fi

echo ""
read -p "לחצי Enter לסגור..."
