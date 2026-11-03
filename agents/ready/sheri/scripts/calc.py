"""חישובים קטנים: שווי נקי, קרן חירום, קרן להוצאות לא צפויות, הלוואה.

שימוש:
    python3 -I calc.py networth <שווי.csv>
    python3 -I calc.py emergency (--monthly <X> | --from-summary <שיקוף.csv>) --months <N>
    python3 -I calc.py unexpected --income <X> --rate <P>
    python3 -I calc.py loan --balance <X> --annual-rate <R> --months-left <N>
פלט: שורות טקסט קצרות בעברית, מספרים מעוגלים לשקל (חוץ מ-sum, שמדפיס בדיוק של אגורה).
"""
import csv
import io
import os
import sys
from decimal import Decimal, getcontext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    HebrewParser, ScriptError, add_subparsers, fmt_shekel, fmt_shekel2, parse_amount, parse_date, read_text_any, run_main,
)

getcontext().prec = 28

EXCLUDED_FROM_LIVING_GROUPS = ("חיסכון והשקעות",)
EXPENSE_SECTIONS = ("הוצאות קבועות", "הוצאות משתנות")


# ---------------------------------------------------------------- קלט שורת פקודה

def _positive_amount(text):
    try:
        v = parse_amount(text)
    except ValueError:
        v = None
    if v is None or v <= 0:
        raise ScriptError("הערך %r חייב להיות מספר חיובי" % text)
    return v


def _rate(text, name):
    """שבר (0.055) או אחוזים עם סימן (5.5%). מספר מ-1 ומעלה בלי % נדחה כדי לא לנחש."""
    t = str(text).strip()
    try:
        if t.endswith("%"):
            v = Decimal(t[:-1].strip()) / 100
        else:
            v = Decimal(t)
            if v >= 1:
                raise ScriptError(
                    "%s=%s: יש לכתוב שבר (למשל 0.055) או אחוזים עם הסימן (5.5%%). מספר מ-1 ומעלה בלי %% לא מפורש, כדי לא לנחש."
                    % (name, t)
                )
    except ArithmeticError:
        raise ScriptError("%s: ערך לא מזוהה (%r)" % (name, text))
    if v < 0:
        raise ScriptError("%s לא יכול להיות שלילי" % name)
    return v


def _pct(v):
    return ("%s%%" % (v * 100).quantize(Decimal("0.01"))).replace(".00%", "%")


# ---------------------------------------------------------------- networth

def cmd_networth(a):
    text, _ = read_text_any(a.file)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    for need in ("type", "item", "amount"):
        if need not in (reader.fieldnames or []):
            raise ScriptError("בקובץ חסרה העמודה %s (העמודות: type,item,amount,date)" % need)
    assets = Decimal(0)
    liabilities = Decimal(0)
    n = 0
    dates = []
    for row in reader:
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        line = reader.line_num
        kind = (row["type"] or "").strip()
        if kind not in ("נכס", "התחייבות"):
            raise ScriptError("שורה %d: type חייב להיות 'נכס' או 'התחייבות' (התקבל %r)" % (line, kind))
        try:
            amount = parse_amount(row["amount"])
        except ValueError:
            amount = None
        if amount is None:
            raise ScriptError("שורה %d: סכום לא מזוהה (%r)" % (line, row["amount"]))
        if amount < 0:
            raise ScriptError("שורה %d: סכום שלילי. נכס והתחייבות נרשמים כסכום חיובי, והסוג קובע את הכיוון." % line)
        if kind == "נכס":
            assets += amount
        else:
            liabilities += amount
        n += 1
        raw_date = (row.get("date") or "").strip()
        if raw_date:
            d = parse_date(raw_date)
            if d is None:
                raise ScriptError("שורה %d: תאריך לא מזוהה (%r)" % (line, raw_date))
            dates.append(d)
    if n == 0:
        raise ScriptError("אין שורות בקובץ השווי")
    print("סה\"כ נכסים: %s" % fmt_shekel(assets))
    print("סה\"כ התחייבויות: %s" % fmt_shekel(liabilities))
    print("שווי נקי: %s" % fmt_shekel(assets - liabilities))
    if dates:
        print("מ-%d פריטים; תאריכי הנתונים: %s עד %s" % (n, min(dates).isoformat(), max(dates).isoformat()))
    else:
        print("מ-%d פריטים; בלי תאריכים בקובץ" % n)
    return 0


# ---------------------------------------------------------------- emergency

def living_from_summary(path):
    """ממוצע ההוצאות החודשי מקובץ שיקוף של summarize.py, בלי הקבוצה חיסכון והשקעות.

    מחזיר (מחיה, סה"כ הוצאות, {קבוצה: סכום שהוצא}).
    """
    text, _ = read_text_any(path)
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        raise ScriptError("קובץ השיקוף ריק")
    header = rows[0]
    for need in ("section", "group", "item", "average"):
        if need not in header:
            raise ScriptError("קובץ השיקוף לא בפורמט של summarize.py: חסרה העמודה %s" % need)
    ci = {name: header.index(name) for name in ("section", "group", "item", "average")}

    def cell(r, name):
        i = ci[name]
        return r[i].strip() if i < len(r) else ""

    item_sum = {s: Decimal(0) for s in EXPENSE_SECTIONS}
    total_row = {}
    excluded = {}
    living = Decimal(0)
    any_avg = False
    for r in rows[1:]:
        if not r:
            continue
        section = cell(r, "section")
        if section == "לא ברור":  # סוף הקובץ: טבלת התנועות הלא ברורות
            break
        if section not in EXPENSE_SECTIONS:
            continue
        group = cell(r, "group")
        avg_text = cell(r, "average")
        if group == "":  # שורת סה"כ של הסעיף
            total_row[section] = parse_amount(avg_text) if avg_text else None
            continue
        if not avg_text:
            continue
        any_avg = True
        value = parse_amount(avg_text)
        item_sum[section] += value
        if group in EXCLUDED_FROM_LIVING_GROUPS:
            excluded[group] = excluded.get(group, Decimal(0)) + value
        else:
            living += value
    if set(total_row) != set(EXPENSE_SECTIONS):
        raise ScriptError("בקובץ השיקוף חסרות שורות סה\"כ להוצאות קבועות ו/או משתנות")
    if not any_avg or any(v is None for v in total_row.values()):
        raise ScriptError("בשיקוף אין ממוצע (אין חודש מלא), ולכן אי אפשר לחשב מחיה חודשית.")
    for section in EXPENSE_SECTIONS:
        if abs(item_sum[section] - total_row[section]) > Decimal("0.05"):
            raise ScriptError(
                "קובץ השיקוף לא עקבי: סכום הפריטים ב'%s' שונה משורת הסה\"כ שלו. לא מחשבת מקובץ כזה." % section
            )
    total = total_row[EXPENSE_SECTIONS[0]] + total_row[EXPENSE_SECTIONS[1]]
    for g in EXCLUDED_FROM_LIVING_GROUPS:
        excluded.setdefault(g, Decimal(0))
    return living, total, excluded


def cmd_emergency(a):
    if a.months < 1:
        raise ScriptError("--months חייב להיות 1 ומעלה")
    if (a.monthly is None) == (a.from_summary is None):
        raise ScriptError("יש לתת בדיוק אחד מ: --monthly או --from-summary")
    if a.from_summary:
        monthly, total, excluded = living_from_summary(a.from_summary)
        print("מחיה חודשית (ממוצע מהשיקוף, בלי חיסכון והשקעות): %s" % fmt_shekel(monthly))
        print("סה\"כ הוצאות בשיקוף: %s" % fmt_shekel(total))
        print("מה הוצא מהמחיה: %s" % "; ".join("%s %s" % (g, fmt_shekel(v)) for g, v in excluded.items()))
        print("מקור: %s" % os.path.basename(a.from_summary))
    else:
        monthly = _positive_amount(a.monthly)
    print("יעד קרן חירום: %s (%d חודשי מחיה × %s)" % (fmt_shekel(monthly * a.months), a.months, fmt_shekel(monthly)))
    return 0


# ---------------------------------------------------------------- unexpected

def cmd_unexpected(a):
    income = _positive_amount(a.income)
    rate = _rate(a.rate, "--rate")
    print("הפרשה חודשית לקרן להוצאות לא צפויות: %s (%s מהכנסה של %s)" % (fmt_shekel(income * rate), _pct(rate), fmt_shekel(income)))
    return 0


# ---------------------------------------------------------------- sum

def cmd_sum(a):
    # For totals of amounts that come straight from a file (e.g. a list of private purchases on a
    # business card), so Shari never adds numbers in her head. Printed to the agora, not rounded to the shekel.
    values = []
    for x in a.amounts:
        try:
            v = parse_amount(x)
        except ValueError:
            v = None
        if v is None:
            raise ScriptError("סכום לא תקין: %r" % x)
        values.append(v)
    total = sum(values, Decimal(0))
    print("סה\"כ %d סכומים: %s" % (len(a.amounts), fmt_shekel2(total)))
    return 0


# ---------------------------------------------------------------- loan

def cmd_loan(a):
    balance = _positive_amount(a.balance)
    rate = _rate(a.annual_rate, "--annual-rate")
    n = a.months_left
    if n < 1:
        raise ScriptError("--months-left חייב להיות 1 ומעלה")
    r = rate / 12
    if r == 0:
        payment = balance / n
    else:
        payment = balance * r / (1 - (1 + r) ** (-n))
    total_paid = payment * n
    interest = total_paid - balance
    print("החזר חודשי משוער: %s" % fmt_shekel(payment))
    print("סך הריבית שנשארה: %s" % fmt_shekel(interest))
    print("סך ההחזרים עד הסוף: %s (על יתרה של %s, %d חודשים, ריבית שנתית %s)" % (
        fmt_shekel(total_paid), fmt_shekel(balance), n, _pct(rate)))
    print("הערכה בלוח שפיצר: ריבית חודשית = שנתית / 12, בלי הצמדה ועמלות. הנתון המחייב הוא של הבנק.")
    return 0


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(description="חישובים קטנים: שווי נקי, קרן חירום, קרן להוצאות לא צפויות, הלוואה, סכום. מספרים מעוגלים לשקל, חוץ מהפקודה sum שמדפיסה בדיוק של אגורה.")
    sub = add_subparsers(p, dest="cmd")
    sub.required = True

    nw = sub.add_parser("networth", help="שווי נקי מקובץ csv (עמודות: type,item,amount,date)",
                        description="סה\"כ נכסים, סה\"כ התחייבויות ושווי נקי. type: נכס או התחייבות; סכום חיובי.")
    nw.add_argument("file", help="קובץ csv: type(נכס|התחייבות),item,amount,date")
    nw.set_defaults(fn=cmd_networth)

    em = sub.add_parser("emergency", help="יעד קרן חירום",
                        description="יעד קרן חירום = מחיה חודשית × מספר החודשים. המחיה: ידנית, או ממוצע מקובץ שיקוף "
                        "בלי הקבוצה חיסכון והשקעות.")
    em.add_argument("--monthly", help="מחיה חודשית בשקלים")
    em.add_argument("--from-summary", dest="from_summary", help="קובץ שיקוף csv שהופק ב-summarize.py (--out)")
    em.add_argument("--months", type=int, required=True, help="כמה חודשי מחיה - המספר שהמשתמש בחר (אין ברירת מחדל)")
    em.set_defaults(fn=cmd_emergency)

    bl = sub.add_parser("unexpected", help="הפרשה חודשית לקרן להוצאות לא צפויות",
                        description="הפרשה חודשית = הכנסה × שיעור. שיעור: שבר (0.05) או אחוזים עם הסימן (5%). השיעור הוא מה שהמשתמש בחר.")
    bl.add_argument("--income", required=True, help="הכנסה חודשית בשקלים")
    bl.add_argument("--rate", required=True, help="שיעור ההפרשה שהמשתמש בחר (אין ברירת מחדל)")
    bl.set_defaults(fn=cmd_unexpected)

    sm = sub.add_parser("sum", help="סכום של רשימת סכומים (בדיוק של אגורה)",
                        description="מחבר סכומים שנלקחו מקובץ (למשל רשימת הוצאות פרטיות בכרטיס העסק). "
                        "אפשר עם פסיקים ועם הסימן ₪. הסכום מודפס בדיוק של אגורה, בלי עיגול לשקל.")
    sm.add_argument("amounts", nargs="+", help="סכומים, למשל 1200.40 1,350 99.70")
    sm.set_defaults(fn=cmd_sum)

    ln = sub.add_parser("loan", help="החזר חודשי וסך הריבית שנשארה",
                        description="לוח שפיצר משוער להלוואה. ריבית שנתית: שבר (0.055) או אחוזים עם הסימן (5.5%).")
    ln.add_argument("--balance", required=True, help="יתרת ההלוואה בשקלים")
    ln.add_argument("--annual-rate", dest="annual_rate", required=True, help="ריבית שנתית: 0.055 או 5.5%%")
    ln.add_argument("--months-left", dest="months_left", required=True, type=int, help="מספר החודשים שנשארו")
    ln.set_defaults(fn=cmd_loan)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    run_main(main)
