"""קובץ תזרים מהנהלת החשבונות (xlsx, גיליון לכל חשבון) ← קובץ עבודה בפורמט של read_bank_file.py.

שימוש:
  python3 -I read_cashflow.py <תזרים.xlsx> --list-sheets
  python3 -I read_cashflow.py <תזרים.xlsx> --sheet <שם> --out <עבודה.csv> [--world פרטי|עסק]
  python3 -I read_cashflow.py <תזרים.xlsx> --sheet <שם> --balances
  python3 -I read_cashflow.py <תזרים.xlsx> --sheet <שם> --compare-cards <כאל.csv>

שורת הכותרות מזוהה לפי שמות העמודות (לא לפי אות עמודה ולא לפי מספר שורה). נקראות רק שורות 'בפועל';
'צפוי' הוא תחזית ואינו נקרא, ושורת 'יתרת פתיחה' אינה תנועה.
"""
import csv
import io
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    HebrewParser, ScriptError, add_months, money2, month_key, parse_amount, parse_date, read_text_any, run_main,
)
from xlsx_lib import XlsxError, read_workbook  # noqa: E402

HEADER_SEARCH_ROWS = 10
ACTUAL = "בפועל"
FORECAST = "צפוי"
OPENING = "יתרת פתיחה"
CARD_KIND = "כרטיס אשראי"
CARD_DESC_MARKS = ("כ.א.", "חיוב לכרטיס")
HEADERS = [
    ("date", "תאריך", True),
    ("status", "בפועל/ צפוי", True),
    ("kind", "סוג תשלום/תקבול", True),
    ("name", "שם ספק/לקוח", True),
    ("pay", "תשלומים", True),
    ("rec", "תקבולים", True),
    ("bal", 'מצטבר עו"ש', False),
]
OUT_COLUMNS = ["date", "description", "amount", "source_file", "world", "kind", "is_card_charge", "account"]
CARD_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
MAX_LISTED = 20
ROUNDING_TOLERANCE = Decimal("1")  # gaps under one shekel are rounding in the cash flow, not a finding

_IGNORED = "‎‏‪‫‬ \t\"'״׳”“"


def norm(value):
    """טקסט להשוואה: בלי רווחים, סימני כיוון ומרכאות."""
    if value is None:
        return ""
    t = str(value)
    return "".join(ch for ch in t if ch not in _IGNORED and not ch.isspace())


def clean(value):
    """טקסט לתצוגה/פלט: בלי סימני כיוון, רווחים מנורמלים."""
    if value is None:
        return ""
    t = "".join(ch for ch in str(value) if ch not in "‎‏‪‫‬")
    return " ".join(t.split())


def cell(row, j):
    return row[j] if j < len(row) else None


def is_empty(v):
    return v is None or (isinstance(v, str) and not v.strip())


# ---------------------------------------------------------------- קריאת הגיליון

def load_sheets(path):
    try:
        return read_workbook(path)
    except XlsxError as e:
        raise ScriptError("%s: %s" % (path, e))


def find_sheet(sheets, name):
    for s in sheets:
        if s.name == name:
            return s
    raise ScriptError("אין גיליון בשם %r בקובץ. הגיליונות: %s" % (name, " | ".join(s.name for s in sheets)))


def find_header(sheet):
    """מחזיר (אינדקס שורת הכותרות, {מפתח: אינדקס עמודה}). נכשל בלי להדפיס תוכן שורות."""
    wanted = {key: norm(text) for key, text, _ in HEADERS}
    required = [key for key, _, req in HEADERS if req]
    best_missing = None
    for i, row in enumerate(sheet.rows[:HEADER_SEARCH_ROWS]):
        found = {}
        for j, v in enumerate(row):
            if isinstance(v, str):
                n = norm(v)
                for key, w in wanted.items():
                    if n == w and key not in found:
                        found[key] = j
        missing = [k for k in required if k not in found]
        if not missing:
            return i, found
        if found and (best_missing is None or len(missing) < len(best_missing)):
            best_missing = missing
    names = {key: text for key, text, _ in HEADERS}
    detail = ""
    if best_missing is not None:
        detail = " בשורה הקרובה ביותר חסרות הכותרות: %s." % ", ".join(names[k] for k in best_missing)
    raise ScriptError(
        "לא נמצאה שורת כותרות בגיליון %r (חיפשתי בשורות 1 עד %d).%s הכותרות הנדרשות: %s."
        % (sheet.name, HEADER_SEARCH_ROWS, detail, ", ".join(names[k] for k in required)))


def _amount_cell(v, row_no, what):
    if is_empty(v):
        return None
    try:
        d = parse_amount(v)
    except ValueError:
        raise ScriptError("שורה %d: %s לא מזוהה כסכום" % (row_no, what))
    if d is None:
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def read_rows(sheet):
    """שורות 'בפועל' של הגיליון לפי סדר הקובץ + ספירת מה שדולג.

    כל שורה: row (מספר שורה באקסל), date, desc, kind, amount (None כשאין סכום), bal (None כשאין).
    מחזיר (rows, stats, header_index, cols)."""
    hdr, cols = find_header(sheet)
    rows = []
    stats = {"forecast": 0, "opening": 0, "no_amount": 0, "other": 0}
    opening = norm(OPENING)
    status_header = norm(HEADERS[1][1])
    for idx in range(hdr + 1, len(sheet.rows)):
        row = sheet.rows[idx]
        row_no = idx + 1
        if all(is_empty(v) for v in row):
            continue
        if any(isinstance(v, str) and norm(v).startswith(opening) for v in row):
            stats["opening"] += 1
            continue
        status_raw = cell(row, cols["status"])
        status = norm(status_raw)
        d = parse_date(cell(row, cols["date"]))
        pay_cell, rec_cell = cell(row, cols["pay"]), cell(row, cols["rec"])
        has_amount = not (is_empty(pay_cell) and is_empty(rec_cell))
        if status == norm(FORECAST):
            stats["forecast"] += 1
            continue
        if status != norm(ACTUAL):
            if status and status != status_header:
                raise ScriptError("שורה %d: ערך לא מוכר בעמודת %s (צפוי: %s או %s). אין לדלג על שורה בשקט."
                                  % (row_no, HEADERS[1][1], ACTUAL, FORECAST))
            if not status and d is not None and has_amount:
                raise ScriptError("שורה %d: יש תאריך וסכום אבל עמודת %s ריקה, ולכן אי אפשר לדעת אם זו תנועה שקרתה."
                                  % (row_no, HEADERS[1][1]))
            stats["other"] += 1
            continue
        if d is None:
            # Template rows at the bottom of the sheet carry the status and the running-balance
            # formula but no date and no amount. They are not transactions.
            if not has_amount and is_empty(cell(row, cols["date"])):
                stats["template"] = stats.get("template", 0) + 1
                continue
            raise ScriptError("שורה %d: תאריך לא תקין בשורת %s" % (row_no, ACTUAL))
        pay = _amount_cell(pay_cell, row_no, HEADERS[4][1])
        rec = _amount_cell(rec_cell, row_no, HEADERS[5][1])
        bal = _amount_cell(cell(row, cols["bal"]), row_no, HEADERS[6][1]) if "bal" in cols else None
        amount = None
        if pay is not None or rec is not None:
            amount = (rec or Decimal(0)) - (pay or Decimal(0))
        else:
            stats["no_amount"] += 1
        rows.append({
            "row": row_no, "date": d, "desc": clean(cell(row, cols["name"])),
            "kind": clean(cell(row, cols["kind"])), "amount": amount, "bal": bal,
        })
    return rows, stats, hdr, cols


def is_card_charge(r):
    if norm(r["kind"]) == norm(CARD_KIND):
        return True
    return any(mark in r["desc"] for mark in CARD_DESC_MARKS)


# ---------------------------------------------------------------- המרה לקובץ עבודה

def convert(args, sheet, rows, stats, hdr):
    moves = [r for r in rows if r["amount"] is not None]
    if not moves:
        raise ScriptError("אין תנועות 'בפועל' עם סכום בגיליון %r" % sheet.name)
    source = "%s - %s" % (os.path.basename(args.file), sheet.name)
    account = "תזרים %s" % sheet.name   # summarize.py groups the files of one account when it judges a partial month
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(OUT_COLUMNS)
    cards = 0
    for r in moves:
        card = is_card_charge(r)
        cards += card
        w.writerow([r["date"].isoformat(), r["desc"], money2(r["amount"]), source, args.world, r["kind"], "yes" if card else "no", account])
    tmp = "%s.tmp-%d" % (args.out, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())
        os.replace(tmp, args.out)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ScriptError("לא ניתן לכתוב את הפלט: %s" % (e.strerror or e))
    dates = [r["date"] for r in moves]
    err = sys.stderr
    print("קובץ: %s | גיליון: %s" % (os.path.basename(args.file), sheet.name), file=err)
    print("שורת כותרות: שורה %d" % (hdr + 1), file=err)
    print("עולם: %s%s" % (args.world, " (ברירת מחדל; --world להחלפה)" if not args.world_given else ""), file=err)
    print("מספר תנועות 'בפועל': %d (מהן חיובי כרטיס אשראי: %d)" % (len(moves), cards), file=err)
    print("טווח תאריכים: %s עד %s" % (min(dates).isoformat(), max(dates).isoformat()), file=err)
    print("דולגו: %d שורות 'צפוי' (תחזית), %d שורות 'יתרת פתיחה', %d שורות 'בפועל' בלי סכום, %d שורות ריקות מסטטוס"
          % (stats["forecast"], stats["opening"], stats["no_amount"], stats["other"]), file=err)
    print("נכתב: %s" % args.out, file=err)
    return 0


# ---------------------------------------------------------------- יתרות

def balances(args, sheet, rows):
    if "bal" not in args.cols:
        raise ScriptError("בגיליון %r אין עמודת %s, ולכן אי אפשר להדפיס יתרות" % (sheet.name, HEADERS[6][1]))
    if not rows:
        raise ScriptError("אין שורות 'בפועל' בגיליון %r" % sheet.name)
    last = {}
    for r in rows:
        mk = month_key(r["date"])
        if mk not in last or r["date"] >= last[mk]["date"]:
            last[mk] = r
    ordered = all(a["date"] <= b["date"] for a, b in zip(rows, rows[1:]))
    out = args.stdout
    out.write("יתרה מצטברת בשורת 'בפועל' האחרונה של כל חודש - גיליון %s\n" % sheet.name)
    if not ordered:
        out.write("אזהרה: שורות 'בפועל' אינן מסודרות לפי תאריך בקובץ. נלקחה השורה עם התאריך המאוחר ביותר בחודש "
                  "(ובשוויון, המאוחרת בקובץ); יש לוודא שזו אכן היתרה בסוף החודש.\n")
    mk = min(last)
    final = max(last)
    while mk <= final:
        if mk not in last:
            out.write("%s | אין תנועות 'בפועל' בחודש הזה\n" % mk)
        else:
            r = last[mk]
            if r["bal"] is None:
                out.write("%s | %s | אין ערך בעמודת %s בשורה %d\n" % (mk, r["date"].isoformat(), HEADERS[6][1], r["row"]))
            else:
                out.write("%s | %s | %s\n" % (mk, r["date"].isoformat(), money2(r["bal"])))
        y, m = int(mk[:4]), int(mk[5:7])
        mk = "%04d-%02d" % (y + (m == 12), m % 12 + 1)
    return 0


# ---------------------------------------------------------------- השוואה לדפי כאל

def read_cal(path):
    """הפלט של read_cal_pdf.py ← {(כרטיס, חודש חיוב): סכום} לשורות in_total=yes."""
    if not os.path.isfile(path):
        raise ScriptError("הקובץ לא נמצא: %s" % path)
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    missing = [c for c in ("card", "billing_date", "charge_amount", "in_total") if c not in cols]
    if missing:
        raise ScriptError("בקובץ של כאל חסרות עמודות: %s (הקובץ מופק על ידי read_cal_pdf.py)" % ", ".join(missing))
    sums = {}
    for row in reader:
        if not any((v or "").strip() for v in row.values() if not isinstance(v, list)):
            continue
        n = reader.line_num
        if (row["in_total"] or "").strip() != "yes":
            continue
        card = (row["card"] or "").strip()
        billing = (row["billing_date"] or "").strip()
        if not card or len(billing) < 7:
            raise ScriptError("%s, שורה %d: חסר כרטיס או תאריך חיוב. הדף לא נקרא עד הסוף ב-read_cal_pdf.py" % (path, n))
        try:
            amount = parse_amount(row["charge_amount"])
        except ValueError:
            amount = None
        if amount is None:
            raise ScriptError("%s, שורה %d: סכום חיוב לא מזוהה" % (path, n))
        key = (card, billing[:7])
        sums[key] = sums.get(key, Decimal(0)) + amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not sums:
        raise ScriptError("אין בקובץ של כאל עסקאות עם in_total=yes")
    return sums


def cards_mentioned(sheet):
    """Cards that appear in any card-charge row of the sheet, actual or forecast.
    A card from this list that is missing from the actual rows is a real gap; a card that never
    appears here belongs to another account and is left out."""
    hdr, cols = find_header(sheet)
    found = set()
    for raw in sheet.rows[hdr + 1:]:
        desc = clean(cell(raw, cols["name"]))
        if is_card_charge({"kind": clean(cell(raw, cols["kind"])), "desc": desc}):
            found |= set(CARD_RE.findall(desc))
    return found


def compare_cards(args, sheet, rows):
    cal = read_cal(args.compare_cards)
    flow = {}
    unassigned = []
    for r in rows:
        if r["amount"] is None or not is_card_charge(r):
            continue
        cards = set(CARD_RE.findall(r["desc"]))
        if len(cards) != 1:
            unassigned.append(r)
            continue
        key = (cards.pop(), month_key(r["date"]))
        flow[key] = flow.get(key, Decimal(0)) - r["amount"]   # חיוב ביוצא הוא סכום שלילי; כאן הוא מוצג חיובי
    out = args.stdout
    out.write("השוואת חיובי אשראי - גיליון %s מול %s\n" % (sheet.name, os.path.basename(args.compare_cards)))
    out.write("פער = סכום החיובים בתזרים פחות סכום העסקאות בקובץ של כאל (חיובי: בתזרים יותר)\n")
    same = gaps = 0
    # Only cards that this sheet actually pays. A card charged to another account would show
    # up here as a full-size false gap in every month.
    sheet_cards = {k[0] for k in flow} | cards_mentioned(sheet)
    period = bool(args.from_month or args.to_month)
    if period:
        # With a period, every month in it is checked: a month with a card charge in the cash flow and
        # no statement is exactly the gap the check is for (a statement that was not downloaded).
        lo, hi = args.from_month or "", args.to_month or "9999-99"
        out.write("תקופה: %s עד %s. כל חודש בתקופה נבדק, גם חודש שאין לו דף של כאל.\n" % (
            args.from_month or "ההתחלה", args.to_month or "הסוף"))
    else:
        # Without a period: months before or after the statements that were downloaded are not gaps,
        # just not covered. They are counted below so they are not silently dropped.
        cal_months = [k[1] for k in cal]
        lo, hi = (min(cal_months), max(cal_months)) if cal_months else ("", "")
    keys = [k for k in set(flow) | set(cal) if k[0] in sheet_cards]
    outside = sorted(k for k in keys if not lo <= k[1] <= hi and k in flow)
    empty = []
    if period and args.from_month and args.to_month:
        # A billing month with neither a charge in the cash flow nor a statement prints no row. It is not
        # a gap (the card may not have been used, or the charge date has not come yet), but it must not
        # vanish either. Only cards that were actually charged somewhere (an actual row in the cash flow, or a
        # statement): four digits that appear only in a forecast row are often not a card at all.
        charged = sorted({k[0] for k in keys})
        mk = args.from_month
        while mk <= args.to_month:
            empty += [(card, mk) for card in charged if (card, mk) not in flow and (card, mk) not in cal]
            mk = add_months(mk, 1)
    for key in sorted(k for k in keys if lo <= k[1] <= hi):
        f = flow.get(key)
        c = cal.get(key)
        diff = (f or Decimal(0)) - (c or Decimal(0))
        if diff == 0:
            same += 1
            verdict = "תואם"
        elif f is not None and c is not None and abs(diff) < ROUNDING_TOLERANCE:
            # The cash flow is often typed in whole shekels.
            same += 1
            verdict = "תואם (הפרש עיגול %s)" % money2(diff)
        else:
            gaps += 1
            verdict = "פער %s" % money2(diff)
        note = ""
        if f is None:
            note = " (אין חיוב כרטיס בתזרים לחודש הזה)"
        elif c is None:
            note = " (אין עסקאות בקובץ של כאל לחודש חיוב הזה)"
        out.write("כרטיס %s | %s | תזרים %s | כאל %s | %s%s\n" % (
            key[0], key[1], money2(f or Decimal(0)), money2(c or Decimal(0)), verdict, note))
    if unassigned:
        out.write("חיובי אשראי בתזרים שאי אפשר לשייך לכרטיס (אין בתיאור בדיוק קבוצה אחת של 4 ספרות): %d\n" % len(unassigned))
        for r in unassigned[:MAX_LISTED]:
            out.write("  שורה %d | %s | %s\n" % (r["row"], r["date"].isoformat(), money2(-r["amount"])))
        if len(unassigned) > MAX_LISTED:
            out.write("  ... ועוד %d\n" % (len(unassigned) - MAX_LISTED))
    if empty:
        out.write("חודשי חיוב בתקופה בלי חיוב בתזרים ובלי דף של כאל (לא פער; ייתכן שלא היה שימוש, או שיום החיוב עוד לא הגיע): "
                  "%d כרטיס-חודש (%s)\n" % (len(empty), ", ".join("%s %s" % k for k in empty[:MAX_LISTED])
                                            + (" ..." if len(empty) > MAX_LISTED else "")))
    if outside:
        out.write("חיובי כרטיס בתזרים מחוץ לטווח %s, לא נבדקו: %d כרטיס-חודש (%s)\n" % (
            "התקופה" if period else "הדפים של כאל", len(outside),
            ", ".join("%s %s" % k for k in outside[:MAX_LISTED]) + (" ..." if len(outside) > MAX_LISTED else "")))
        if not period:
            out.write("  כדי לבדוק אותם: להוסיף --from/--to. חודש בתקופה בלי דף של כאל יסומן כפער.\n")
    out.write("סיכום: %d כרטיס-חודש תואמים, %d עם פער, %d חיובים בלי כרטיס מזוהה\n" % (same, gaps, len(unassigned)))
    return 0


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(
        description="קורא קובץ תזרים מהנהלת החשבונות (xlsx, גיליון לכל חשבון; כלי אופציונלי, רק לקובץ בפורמט הזה). ברירת המחדל: המרת גיליון אחד לקובץ עבודה "
        "בפורמט של read_bank_file.py (date,description,amount,source_file,world + kind,is_card_charge), כדי להזין את prepare_sorting.py. "
        "נקראות רק שורות 'בפועל'; 'צפוי' הוא תחזית ואינו נקרא, 'יתרת פתיחה' אינה תנועה. סכום חיובי = תקבול, שלילי = תשלום. "
        "שורת הכותרות מזוהה לפי שמות העמודות. --balances ו---compare-cards הם בדיקות מול הבנק ומול דפי כאל ומדפיסים סכומים.",
    )
    p.add_argument("file", help="קובץ התזרים (xlsx)")
    p.add_argument("--list-sheets", action="store_true", help="מדפיס את שמות הגיליונות ויוצא")
    p.add_argument("--sheet", help="שם הגיליון (חשבון)")
    p.add_argument("--out", help="נתיב קובץ העבודה (csv) להמרה")
    p.add_argument("--world", choices=["פרטי", "עסק"], default=None,
                   help="העולם של הגיליון (ברירת מחדל: פרטי, והיא מודפסת)")
    p.add_argument("--balances", action="store_true",
                   help="מדפיס לכל חודש את היתרה המצטברת בשורת 'בפועל' האחרונה שלו, לבדיקה מול יתרת הבנק")
    p.add_argument("--from", dest="from_month", metavar="YYYY-MM",
                   help="בהמרה: רק תנועות מהחודש הזה ואילך. ב---compare-cards: בודקים כל חודש בתקופה, גם בלי דף של כאל")
    p.add_argument("--to", dest="to_month", metavar="YYYY-MM", help="עד החודש הזה (כולל), כמו --from")
    p.add_argument("--compare-cards", metavar="כאל.csv",
                   help="משווה לכל כרטיס וחודש חיוב את חיובי האשראי בתזרים לסכום העסקאות בקובץ של read_cal_pdf.py (in_total=yes)")
    a = p.parse_args()
    a.world_given = a.world is not None
    a.world = a.world or "פרטי"
    a.stdout = sys.stdout
    if not os.path.isfile(a.file):
        raise ScriptError("הקובץ לא נמצא: %s" % a.file)
    modes = [a.list_sheets, a.balances, bool(a.compare_cards)]
    if sum(modes) > 1:
        raise ScriptError("--list-sheets, --balances ו---compare-cards הם מצבים נפרדים; יש לבחור אחד")
    sheets = load_sheets(a.file)
    if a.list_sheets:
        for s in sheets:
            print(s.name)
        return 0
    if not a.sheet:
        raise ScriptError("חסר --sheet (שם הגיליון). את השמות מקבלים עם --list-sheets")
    sheet = find_sheet(sheets, a.sheet)
    if not (a.balances or a.compare_cards):
        if not a.out:
            raise ScriptError("חסר --out (נתיב קובץ העבודה)")
        if os.path.realpath(a.out) == os.path.realpath(a.file):
            raise ScriptError("--out זהה לקובץ הקלט. יש לבחור נתיב אחר.")
    rows, stats, hdr, cols = read_rows(sheet)
    a.cols = cols
    for v in (a.from_month, a.to_month):
        if v is not None and not re.match(r"^\d{4}-\d{2}$", v):
            raise ScriptError("חודש לא תקין: %r (הפורמט: YYYY-MM)" % v)
    if (a.from_month or a.to_month) and a.balances:
        raise ScriptError("'--from' ו-'--to' חלים על ההמרה (--out) ועל --compare-cards, לא על --balances")
    if a.from_month or a.to_month:
        before = len(rows)
        rows = [r for r in rows if (a.from_month is None or month_key(r["date"]) >= a.from_month)
                and (a.to_month is None or month_key(r["date"]) <= a.to_month)]
        stats["outside_period"] = before - len(rows)
        print("תקופה: %s עד %s. הושמטו %d תנועות מחוץ לתקופה." % (
            a.from_month or "ההתחלה", a.to_month or "הסוף", before - len(rows)), file=sys.stderr)
    if a.balances:
        return balances(a, sheet, rows)
    if a.compare_cards:
        return compare_cards(a, sheet, rows)
    return convert(a, sheet, rows, stats, hdr)


if __name__ == "__main__":
    run_main(main)
