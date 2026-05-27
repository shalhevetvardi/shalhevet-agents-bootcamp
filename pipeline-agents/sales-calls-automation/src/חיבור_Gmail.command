#!/bin/bash
# ============================================================
#  חיבור Gmail — יצירת refresh_token חד-פעמית
#  דאבל-קליק → נפתח דפדפן → לחיצת Allow → סיום
# ============================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

clear
echo ""
echo "════════════════════════════════════════════════════════════"
echo "   🔐  חיבור Gmail לאוטומציה — פעולה חד-פעמית"
echo "════════════════════════════════════════════════════════════"
echo ""

if [ ! -d "venv" ]; then
    echo -e "${RED}✗ הסביבה לא הותקנה עדיין.${NC}"
    echo "   דאבל-קליק על 'התקנה.command' קודם."
    echo ""
    read -p "לחצי Enter לסגור..."
    exit 1
fi

source venv/bin/activate
python3 auth_gmail.py

echo ""
read -p "לחצי Enter לסגור..."
