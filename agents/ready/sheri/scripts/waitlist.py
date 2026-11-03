"""המתנה לפני קנייה: יומן קניות שמחכות מספר ימים שהמשתמש בחר (טבלת markdown).

שימוש:
    python3 -I waitlist.py add <יומן> --what "<מה>" --amount <X> --days <N> [--date YYYY-MM-DD]
    python3 -I waitlist.py due <יומן> --days <N> [--today YYYY-MM-DD]
    python3 -I waitlist.py close <יומן> --row <N> --status נקנה|"לא נקנה"|"לא נקנה - להעביר"|הועבר [--date YYYY-MM-DD]
    python3 -I waitlist.py month <יומן> --month YYYY-MM

מספר ימי ההמתנה (N) נשמר ב-הגדרות.md בתיקיית הנתונים, והוא של המשתמש. הסקריפט לא מנחש אותו: הוא חובה.
עמודות היומן: תאריך | מה | סכום | סטטוס | תאריך סגירה.
סטטוס: ממתין / נקנה / לא נקנה / לא נקנה - להעביר / הועבר. מספר שורה = מיקום בטבלה, מ-1, בלי שורת הכותרות.
"לא נקנה" = הוחלט לא לקנות, בלי העברת סכום. "לא נקנה - להעביר" = הוחלט לא לקנות והמשתמש בוחר להעביר את הסכום לחיסכון.
הסקריפט לא מעביר כסף: הוא רק רושם ומחשב.
"""
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    HebrewParser, ScriptError, add_subparsers, fmt_shekel_exact, parse_amount, parse_iso_date, read_text_any, run_main,
)

COLUMNS = ["תאריך", "מה", "סכום", "סטטוס", "תאריך סגירה"]
WAITING = "ממתין"
BOUGHT = "נקנה"
NOT_BOUGHT = "לא נקנה"
TO_TRANSFER = "לא נקנה - להעביר"
TRANSFERRED = "הועבר"
CLOSE_STATUSES = (BOUGHT, NOT_BOUGHT, TO_TRANSFER, TRANSFERRED)

TITLE = "# יומן ההמתנה לפני קנייה"
HEADER_LINE = "| " + " | ".join(COLUMNS) + " |"
SEP_LINE = "|" + "|".join(["---"] * len(COLUMNS)) + "|"

_SPLIT = re.compile(r"(?<!\\)\|")


def _split_row(line):
    parts = _SPLIT.split(line.strip())
    # הצדדים: ריק לפני הצינור הראשון ואחרי האחרון
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip().replace("\\|", "|") for p in parts]


def _join_row(cells):
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


class Journal(object):
    def __init__(self, path):
        self.path = os.path.expanduser(path)
        self.lines = []
        self.header_at = None
        self.row_idx = []   # אינדקסי השורות בקובץ שהן שורות נתונים
        self.exists = os.path.exists(self.path)
        if self.exists:
            text, _ = read_text_any(self.path)
            self.lines = text.split("\n")
            if self.lines and self.lines[-1] == "":
                self.lines.pop()
            self._index()

    def _index(self):
        self.header_at = None
        self.row_idx = []
        for i, line in enumerate(self.lines):
            if not line.lstrip().startswith("|"):
                continue
            if self.header_at is None:
                if _split_row(line) != COLUMNS:
                    raise ScriptError(
                        "שורת הכותרות ביומן %s אינה כפי שצפוי. הצפוי: %s" % (self.path, " | ".join(COLUMNS))
                    )
                self.header_at = i
                continue
            if re.match(r"^\s*\|[\s:|-]+\|\s*$", line):  # שורת ההפרדה
                continue
            self.row_idx.append(i)

    def create_if_missing(self):
        if self.header_at is None:
            if any(line.strip() for line in self.lines):
                raise ScriptError("ביומן %s יש תוכן אבל אין בו טבלה. לא דורסת קובץ קיים." % self.path)
            self.lines = [TITLE, "", HEADER_LINE, SEP_LINE]
            self._index()

    def rows(self):
        out = []
        for n, i in enumerate(self.row_idx, start=1):
            cells = _split_row(self.lines[i])
            if len(cells) != len(COLUMNS):
                raise ScriptError("שורה %d ביומן אינה בת %d עמודות" % (n, len(COLUMNS)))
            out.append(cells)
        return out

    def append(self, cells):
        # אחרי השורה האחרונה של הטבלה
        last = self.row_idx[-1] if self.row_idx else self.header_at + 1
        self.lines.insert(last + 1, _join_row(cells))
        self._index()

    def replace(self, n, cells):
        self.lines[self.row_idx[n - 1]] = _join_row(cells)

    def save(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(self.lines) + "\n")
        os.replace(tmp, self.path)


def _amount_text(v):
    text = format(v.normalize(), "f")
    return text


def _wait_days(text):
    """--days: מספר שלם חיובי, חובה. הערך מגיע מ-הגדרות.md ואינו מנוחש כאן."""
    try:
        n = int(str(text).strip())
    except (ValueError, TypeError):
        n = None
    if n is None or n < 1:
        raise ScriptError("--days חייב להיות מספר שלם חיובי של ימי המתנה (התקבל %r). המספר נשמר ב-הגדרות.md" % (text,))
    return n


def _today(arg):
    return parse_iso_date(arg, "--today") if arg else date.today()


def _row_date(cells, n):
    try:
        return parse_iso_date(cells[0], "התאריך בשורה %d" % n)
    except ScriptError:
        raise ScriptError("בשורה %d ביומן התאריך אינו YYYY-MM-DD (%r)" % (n, cells[0]))


def _row_amount(cells, n):
    try:
        v = parse_amount(cells[2])
    except ValueError:
        v = None
    if v is None:
        raise ScriptError("בשורה %d ביומן הסכום אינו מספר (%r)" % (n, cells[2]))
    return v


def _shown_amount(cells):
    """הסכום מהיומן להצגה למשתמש (אלפים, ₪); ערך שאינו מספר (עריכה ידנית) מוצג כמו שהוא."""
    try:
        v = parse_amount(cells[2])
    except ValueError:
        v = None
    return fmt_shekel_exact(v) if v is not None else cells[2]


# ---------------------------------------------------------------- פקודות

def cmd_add(a):
    days = _wait_days(a.days)
    what = " ".join(a.what.split())
    if not what:
        raise ScriptError("--what ריק")
    try:
        amount = parse_amount(a.amount)
    except ValueError:
        amount = None
    if amount is None or amount <= 0:
        raise ScriptError("--amount חייב להיות מספר חיובי (התקבל %r)" % a.amount)
    when = parse_iso_date(a.date, "--date") if a.date else date.today()
    j = Journal(a.journal)
    j.create_if_missing()
    j.append([when.isoformat(), what, _amount_text(amount), WAITING, ""])
    j.save()
    n = len(j.row_idx)
    print("נרשם בשורה %d: %s, %s, בתאריך %s" % (n, what, fmt_shekel_exact(amount), when.isoformat()))
    print("חוזרים אליו ב-%s" % (when + timedelta(days=days)).isoformat())
    return 0


def cmd_due(a):
    days = _wait_days(a.days)
    today = _today(a.today)
    j = Journal(a.journal)
    if not j.exists:
        print("היומן עוד לא קיים, ולכן אין פריטים שמחכים להחלטה")
        return 0
    found = 0
    for n, cells in enumerate(j.rows(), start=1):
        if cells[3] != WAITING:
            continue
        d = _row_date(cells, n)
        passed = (today - d).days
        if passed >= days:
            found += 1
            print("שורה %d: %s, %s, נרשם ב-%s (עברו %d ימים)" % (n, cells[1], _shown_amount(cells), cells[0], passed))
    if not found:
        print("אין פריטים שעברו %d ימי המתנה וממתינים להחלטה (נכון ל-%s)" % (days, today.isoformat()))
    return 0


def cmd_close(a):
    j = Journal(a.journal)
    rows = j.rows()
    n = a.row
    if n < 1 or n > len(rows):
        raise ScriptError("אין שורה %d ביומן (יש %d שורות)" % (n, len(rows)))
    cells = rows[n - 1]
    current = cells[3]
    allowed = {WAITING: CLOSE_STATUSES, TO_TRANSFER: (TRANSFERRED,)}
    if a.status not in allowed.get(current, ()):
        if current in (BOUGHT, NOT_BOUGHT, TRANSFERRED):
            raise ScriptError("שורה %d כבר סגורה (סטטוס: %s)" % (n, current))
        raise ScriptError("אי אפשר לעבור מ'%s' ל'%s'" % (current, a.status))
    when = parse_iso_date(a.date, "--date") if a.date else date.today()
    cells[3] = a.status
    cells[4] = when.isoformat()
    j.replace(n, cells)
    j.save()
    print("שורה %d (%s, %s): %s, בתאריך %s" % (n, cells[1], _shown_amount(cells), a.status, when.isoformat()))
    return 0


def cmd_month(a):
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", a.month):
        raise ScriptError("--month חייב להיות בצורה YYYY-MM")
    j = Journal(a.journal)
    if not j.exists:
        print("היומן עוד לא קיים, ולכן אין נתונים לחודש %s" % a.month)
        return 0
    tracked = (NOT_BOUGHT, TO_TRANSFER, TRANSFERRED)
    count = {s: 0 for s in tracked}
    total = {s: Decimal(0) for s in tracked}
    for n, cells in enumerate(j.rows(), start=1):
        status = cells[3]
        if status in count and cells[4].startswith(a.month):
            count[status] += 1
            total[status] += _row_amount(cells, n)
    print("חודש %s (לפי תאריך הסגירה)" % a.month)
    for s in tracked:
        print("%s: %d פריטים, %s" % (s, count[s], fmt_shekel_exact(total[s])))
    print("סה\"כ שלא נקנה החודש: %d פריטים, %s" % (
        sum(count.values()), fmt_shekel_exact(sum(total.values(), Decimal(0)))))
    return 0


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(description="המתנה לפני קנייה: רושם קניות שמחכות מספר ימים שהמשתמש בחר, ומסכם. לא מעביר כסף.")
    sub = add_subparsers(p, dest="cmd")
    sub.required = True

    ad = sub.add_parser("add", help="רישום קנייה חדשה (סטטוס ממתין)", description="רושם שורה חדשה. אם היומן לא קיים - יוצר אותו.")
    ad.add_argument("journal", help="נתיב קובץ היומן (markdown)")
    ad.add_argument("--what", required=True, help="מה רוצים לקנות")
    ad.add_argument("--amount", required=True, help="הסכום בשקלים")
    ad.add_argument("--days", required=True, help="כמה ימים מחכים לפני שמחליטים (מספר שלם חיובי, מ-הגדרות.md)")
    ad.add_argument("--date", help="תאריך הרישום YYYY-MM-DD (ברירת מחדל: היום)")
    ad.set_defaults(fn=cmd_add)

    du = sub.add_parser("due", help="שורות ממתינות שעברו מהן ימי ההמתנה", description="מציג שורות בסטטוס ממתין שעברו מהן N ימים או יותר.")
    du.add_argument("journal", help="נתיב קובץ היומן")
    du.add_argument("--days", required=True, help="כמה ימים מחכים לפני שמחליטים (מספר שלם חיובי, מ-הגדרות.md)")
    du.add_argument("--today", help="התאריך של היום YYYY-MM-DD (ברירת מחדל: היום)")
    du.set_defaults(fn=cmd_due)

    cl = sub.add_parser("close", help="סגירת שורה", description="קובע סטטוס לשורה: ממתין ← נקנה / לא נקנה / לא נקנה - להעביר / הועבר; לא נקנה - להעביר ← הועבר.")
    cl.add_argument("journal", help="נתיב קובץ היומן")
    cl.add_argument("--row", required=True, type=int, help="מספר שורה בטבלה (מ-1, בלי שורת הכותרות)")
    cl.add_argument("--status", required=True, choices=list(CLOSE_STATUSES), help="הסטטוס החדש")
    cl.add_argument("--date", help="תאריך הסגירה YYYY-MM-DD (ברירת מחדל: היום)")
    cl.set_defaults(fn=cmd_close)

    mo = sub.add_parser("month", help="סיכום חודשי של מה שלא נקנה", description="כמה פריטים 'לא נקנה', 'לא נקנה - להעביר' ו'הועבר' בחודש, לפי תאריך הסגירה, וסכומם.")
    mo.add_argument("journal", help="נתיב קובץ היומן")
    mo.add_argument("--month", required=True, help="החודש YYYY-MM")
    mo.set_defaults(fn=cmd_month)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    run_main(main)
