#!/bin/bash
# ============================================================
#  התקנה — שיחות מכירה אוטומציה
#  דאבל-קליק על הקובץ הזה ומסיימים. זה הכל.
# ============================================================

set -e

# צבעים לפלט
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# הגעה לתיקיית הסקריפט
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

clear
echo ""
echo "════════════════════════════════════════════════════════════"
echo "   🚀  התקנת אוטומציית שיחות מכירה — אִימפּרוּב"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "תיקייה: $SCRIPT_DIR"
echo ""

# -------- שלב 1: בדיקת Python 3 --------
echo -e "${BLUE}▶ שלב 1/6: בדיקת Python 3...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 לא מותקן.${NC}"
    echo ""
    echo "יש להתקין Python 3 לפני ההמשך:"
    echo "  1. פתחי את https://www.python.org/downloads/"
    echo "  2. הורידי את הגרסה האחרונה (3.12 ומעלה)"
    echo "  3. הריצי את קובץ ההתקנה"
    echo "  4. לחצי שוב על 'התקנה.command'"
    echo ""
    read -p "לחצי Enter לסגור..."
    exit 1
fi
PY_VERSION=$(python3 --version)
echo -e "${GREEN}✓ $PY_VERSION מותקן${NC}"
echo ""

# -------- שלב 2: בדיקת ffmpeg --------
echo -e "${BLUE}▶ שלב 2/6: בדיקת ffmpeg (לעיבוד אודיו)...${NC}"
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${YELLOW}⚠ ffmpeg לא מותקן. מתקינה עכשיו...${NC}"
    if ! command -v brew &> /dev/null; then
        echo -e "${RED}✗ Homebrew לא מותקן.${NC}"
        echo ""
        echo "מתקינה Homebrew... (עלול לקחת דקה-שתיים)"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    brew install ffmpeg
fi
echo -e "${GREEN}✓ ffmpeg מותקן${NC}"
echo ""

# -------- שלב 3: יצירת סביבה וירטואלית --------
echo -e "${BLUE}▶ שלב 3/6: יצירת סביבת Python מבודדת...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ venv נוצר${NC}"
else
    echo -e "${GREEN}✓ venv כבר קיים${NC}"
fi
echo ""

# -------- שלב 4: התקנת חבילות --------
echo -e "${BLUE}▶ שלב 4/6: התקנת חבילות Python... (זה ייקח דקה-שתיים)${NC}"
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "${GREEN}✓ כל החבילות הותקנו${NC}"
echo ""

# -------- שלב 5: בדיקת חיבורים --------
echo -e "${BLUE}▶ שלב 5/6: בדיקת חיבור לכל השירותים...${NC}"
echo ""
python3 test_connections.py || {
    echo ""
    echo -e "${RED}✗ חלק מהחיבורים נכשלו. ראי מעל.${NC}"
    echo "אפשר לתקן את .env ולהריץ שוב את 'התקנה.command'."
    echo ""
    read -p "לחצי Enter להמשיך בכל זאת (או Ctrl+C לעצור)..."
}
echo ""

# -------- שלב 6: הפעלה אוטומטית (LaunchAgent) --------
echo -e "${BLUE}▶ שלב 6/6: הגדרת הפעלה אוטומטית כל 5 דקות...${NC}"

PLIST_NAME="com.aimprove.sales-pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

# עצירה של גרסה קודמת (אם קיימת)
launchctl bootout gui/$(id -u) "$PLIST_PATH" 2>/dev/null || true

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${SCRIPT_DIR}/venv/bin/python3</string>
        <string>${SCRIPT_DIR}/sales_pipeline.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/logs/launchd.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

# טעינה ל-launchd
launchctl bootstrap gui/$(id -u) "$PLIST_PATH"
launchctl enable gui/$(id -u)/${PLIST_NAME}

echo -e "${GREEN}✓ אוטומציה פעילה — רצה כל 5 דקות${NC}"
echo ""

# -------- סיום --------
echo "════════════════════════════════════════════════════════════"
echo -e "${GREEN}   🎉  ההתקנה הסתיימה בהצלחה!${NC}"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "מה קורה מכאן:"
echo "  • הסקריפט רץ אוטומטית כל 5 דקות ברקע"
echo "  • בכל ריצה: בודק שיחות חדשות ב-Twilio + פגישות ב-Calendly"
echo "  • מתמלל, מנתח, ויוצר טיוטת מייל ב-Gmail"
echo "  • את רק צריכה לפתוח את הטיוטה, לערוך אם צריך, ולשלוח"
echo ""
echo "רוצה להריץ ידנית עכשיו? דאבל-קליק על 'הפעלה.command'"
echo ""
echo "לוגים: $SCRIPT_DIR/logs/"
echo ""
read -p "לחצי Enter לסגור..."
