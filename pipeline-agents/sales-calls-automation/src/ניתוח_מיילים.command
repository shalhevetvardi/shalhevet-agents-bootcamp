#!/bin/bash
# ============================================================
#  ניתוח דפוסי מיילים — שולף מ-Gmail ומנתח עם Claude
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
echo "   📧  ניתוח דפוסי מיילים שנשלחו"
echo "════════════════════════════════════════════════════════════"
echo ""

if [ ! -d "venv" ]; then
    echo -e "${RED}✗ הסביבה לא הותקנה.${NC}"
    read -p "לחצי Enter לסגור..."
    exit 1
fi

source venv/bin/activate
python3 analyze_sent_emails.py

echo ""
echo -e "${GREEN}✓ הדוח מוכן: דוח_דפוסי_מיילים.md${NC}"
echo ""
read -p "לחצי Enter לסגור..."
