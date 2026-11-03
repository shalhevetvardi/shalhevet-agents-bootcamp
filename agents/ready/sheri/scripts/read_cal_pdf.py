"""Read Cal credit-card statement PDFs into a transactions CSV.

pdftotext -layout scrambles the Hebrew/number order in these statements, so this reader uses
word positions (pdftotext -bbox) and rebuilds each row by column.

Every statement is reconciled: the sum of the parsed charge amounts must equal the total that
Cal prints on the statement ("סה"כ לתאריך" or "סה"כ חיובי עסקות לתקופה"). A statement that does
not reconcile is reported and the exit code is 1.

With --work-dir the script also writes one work file per statement (כאל-<card>-<billing_date>.csv) in the
format of read_bank_file.py (date,description,amount,source_file,world) plus an account column ("כאל <card>"), ready for prepare_sorting.py.
Only in_total=yes rows are written, and the sign is flipped (a charge is negative, a credit is positive).

With --totals-out the script writes billing_date,total (the statement's charged sum as a positive number with two
decimals, the same format as read_bank_file.py --billing-totals --totals-out) for every statement that passed its own check.
Statements that failed are not written. The file is an input of summarize.py --card-totals.

Requires pdftotext (poppler). Usage:
    python3 -I read_cal_pdf.py <statement.pdf> [...] [--out <transactions.csv>] [--work-dir <dir> [--world פרטי|עסק] [--from YYYY-MM] [--to YYYY-MM]] [--totals-out <card-totals.csv>]
"""
import argparse
import datetime as dt
import csv
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HebrewParser, setup_io  # noqa: E402

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
HEB = re.compile(r"[֐-׿]")
DATE_IN = re.compile(r"(\d\d)/(\d\d)/(20\d\d)")
AMOUNT = re.compile(r"^-?[\d,]+(\.\d{1,2})?$")
BIDI = re.compile("[‎‏‪-‮]")
SECTION_START = re.compile(r"פירוט עסקות (שנצברו|לתקופה)")
SECTION_END = re.compile(r"פירוט עסקות לחיוב עתידי|לוח סילוקין")
WORD_GAP = 1.0      # chars closer than this belong to the same word
COLUMN_GAP = 6.5    # words further apart than this belong to different columns
FIELDS = ["card", "billing_date", "purchase_date", "merchant", "branch", "details",
          "original_amount", "original_currency", "charge_amount", "in_total", "source_file", "row_in_file"]


def words_by_page(pdf):
    # "-" and not /dev/stdout, which does not exist on Windows; pdftotext writes UTF-8 by default,
    # so it is decoded as UTF-8 and not with the locale code page.
    out = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    for page in out.split("<page ")[1:]:
        yield [(float(a), float(b), float(c), float(d), html.unescape(w))
               for a, b, c, d, w in WORD.findall(page)]


def lines_of(words, tol=2.0):
    rows = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if rows and abs(rows[-1][0] - w[1]) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([w[1], [w]])
    return rows


def token_text(items):
    # items are in ascending x. Hebrew runs read right to left, digits/Latin left to right.
    if any(HEB.search(i[4]) for i in items):
        out, run = [], []
        for i in reversed(items):  # right to left
            if HEB.search(i[4]) or i[4] in " '\"-":
                if run:
                    out.append("".join(x[4] for x in reversed(run)))
                    run = []
                out.append(i[4])
            else:
                run.append(i)
        if run:
            out.append("".join(x[4] for x in reversed(run)))
        return "".join(out)
    return "".join(i[4] for i in items)


def columns(line_words):
    """Split one line into columns. Returns [(x0, x1, text)] in ascending x."""
    ws = sorted(line_words, key=lambda w: w[0])
    cols, words, cur = [], [], [ws[0]]
    for prev, w in zip(ws, ws[1:]):
        gap = w[0] - prev[2]
        if gap < WORD_GAP:
            cur.append(w)
            continue
        words.append(cur)
        cur = [w]
        if gap > COLUMN_GAP:
            cols.append(words)
            words = []
    words.append(cur)
    cols.append(words)
    result = []
    for col in cols:
        # words inside a column: RTL order when the column has Hebrew
        texts = [token_text(w) for w in col]
        if any(HEB.search(t) for t in texts):
            texts = list(reversed(texts))
        result.append((col[0][0][0], col[-1][-1][2], " ".join(texts)))
    return result


def money(text):
    t = text.replace("₪", "").replace("$", "").replace("€", "").replace(" ", "")
    neg = t.endswith("-") or t.startswith("-")
    t = t.strip("-")
    if not AMOUNT.match(t):
        return None
    v = float(t.replace(",", ""))
    return -v if neg else v


def parse_statement(pdf):
    raw = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True,
                         encoding="utf-8").stdout
    flat = BIDI.sub("", raw)
    card = re.search(r"המסתיים ב\s*-?\s*(\d{4})", flat)
    bill = re.search(r"דף חיוב חודשי ל\s*-?\s*(\d\d)/(\d\d)/(\d\d)", flat)
    total = (re.search(r"סה\"כ חיובי עסקות לתקופה\s*₪\s*(-?[\d,]+\.\d{2})", flat)
             or re.search(r"סה\"כ לתאריך\s*₪\s*(-?[\d,]+\.\d{2})", flat))
    meta = {
        "card": card.group(1) if card else "",
        "billing_date": f"20{bill.group(3)}-{bill.group(2)}-{bill.group(1)}" if bill else "",
        "total": float(total.group(1).replace(",", "")) if total else None,
    }
    rows = []
    in_section = False  # only the "transactions charged on this statement" tables count
    for words in words_by_page(pdf):
        lines = lines_of(words)
        parsed = []
        for y, lw in lines:
            cols = columns(lw)
            text = " ".join(c[2] for c in cols)
            if SECTION_END.search(text):
                in_section = False
            elif SECTION_START.search(text):
                in_section = True
            date_cols = [c for c in cols if DATE_IN.search(c[2])]
            money_cols = [c for c in cols if ("₪" in c[2] or "$" in c[2] or "€" in c[2]) and money(c[2]) is not None]
            parsed.append((y, cols, date_cols, money_cols, in_section))
        txn_lines = [p[:4] for p in parsed if p[4] and p[2] and p[3] and max(c[1] for c in p[2]) > 300]
        parsed = [p[:4] for p in parsed]
        for y, cols, date_cols, money_cols in txn_lines:
            date_col = max(date_cols, key=lambda c: c[1])
            dm = DATE_IN.search(date_col[2])
            merchant_part = (date_col[2][:dm.start()] + " " + date_col[2][dm.end():]).strip()
            money_cols = sorted(money_cols, key=lambda c: c[0])
            charge = money(money_cols[0][2])
            orig_col = money_cols[1] if len(money_cols) > 1 else money_cols[0]
            cur = "$" if "$" in orig_col[2] else ("€" if "€" in orig_col[2] else "₪")
            middle = [c for c in cols if money_cols[-1][1] < c[0] and c[1] <= date_col[0] and c is not date_col]
            middle = sorted(middle, key=lambda c: -c[0])  # right to left
            if merchant_part:
                merchant, rest = merchant_part, middle
            else:
                merchant, rest = (middle[0][2] if middle else ""), middle[1:]
            branch = rest[0][2] if rest else ""
            details = " ".join(c[2] for c in rest[1:])
            middle = [date_col] + middle
            # a merchant name that wrapped onto its own line, just above or below
            for y2, cols2, d2, m2 in parsed:
                if d2 or m2 or abs(y2 - y) > 7 or y2 == y:
                    continue
                if not middle:
                    continue
                wrap = [c for c in cols2 if c[0] >= middle[0][0] - 3 and c[1] <= date_col[0]]
                if wrap and len(wrap) == len(cols2):
                    extra = " ".join(c[2] for c in wrap)
                    merchant = f"{extra} {merchant}" if y2 < y else f"{merchant} {extra}"
            dd, mm, yyyy = dm.groups()
            rows.append({
                "card": meta["card"], "billing_date": meta["billing_date"],
                "purchase_date": f"{yyyy}-{mm}-{dd}", "merchant": merchant.strip(),
                "branch": branch, "details": details,
                "original_amount": money(orig_col[2]), "original_currency": cur,
                "charge_amount": charge, "source_file": Path(pdf).name,
            })
    for i, r in enumerate(rows, 1):
        r["row_in_file"] = i
        # FlyAll cashback is listed as a negative row but goes to a separate balance,
        # not against the bill. It is kept for the record and left out of the total.
        cashback = "FLYALL" in (r["merchant"] + r["details"]).upper() and "החזר" in r["merchant"]
        r["in_total"] = "no-cashback" if cashback else "yes"
    return meta, rows


WORK_COLUMNS = ["date", "description", "amount", "source_file", "world", "account"]
DETAIL_PREFIXES = ("תשלום", "קרדיט")


def work_file_name(meta):
    return "כאל-%s-%s.csv" % (meta["card"], meta["billing_date"])


MONTH = re.compile(r"^\d{4}-\d{2}$")


# Cal prints the installment in the details or branch column, e.g. "תשלום 4 מ - 6", "קרדיט 3 מ - 12",
# "תשלום פריסה 2 מ - 4".
INSTALLMENT_TEXT = re.compile(r"(תשלום|קרדיט)\D{0,15}\d+\s*מ")
# One statement covers about a month of purchases. A deal older than that, still charged less than its
# amount, is a payment on an old deal even when the text column is empty.
OLD_DEAL_DAYS = 35


def is_installment(r):
    """True for a payment on a deal in installments.

    By text first. Without text: charged less than the deal amount (in shekels) AND the deal is older than one
    statement cycle. A recent deal charged less than its amount is a discount or a partial charge, not an
    installment, and keeps its purchase date."""
    text = "%s %s" % (r.get("details") or "", r.get("branch") or "")
    if INSTALLMENT_TEXT.search(text):
        return True
    orig = r.get("original_amount")
    if orig is None or orig == "" or r.get("original_currency") != "₪":
        return False
    if abs(Decimal(str(orig))) <= abs(Decimal(str(r["charge_amount"]))) + Decimal("0.005"):
        return False
    try:
        age = (dt.date.fromisoformat(r["billing_date"]) - dt.date.fromisoformat(r["purchase_date"])).days
    except (TypeError, ValueError):
        return False
    return age > OLD_DEAL_DAYS


def in_period(date, period):
    """period = (from 'YYYY-MM' or None, to 'YYYY-MM' or None); date = 'YYYY-MM-DD'."""
    if not period:
        return True
    lo, hi = period
    m = date[:7]
    return (lo is None or m >= lo) and (hi is None or m <= hi)


def to_work_rows(rows, world, period=None):
    """שורות פנימיות של דף חיוב ← שורות קובץ עבודה (רק in_total=yes). חיוב ← סכום שלילי, זיכוי ← חיובי.
    period: רק שורות שהתאריך שלהן (בקובץ העבודה) בתקופה."""
    out = []
    for r in rows:
        if r["in_total"] != "yes":
            continue
        description = r["merchant"]
        details = (r["details"] or "").strip()
        if details.startswith(DETAIL_PREFIXES):
            description = "%s (%s)" % (description, details)
        amount = -Decimal(str(r["charge_amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # An installment keeps its original purchase date and amount in every statement, so two
        # monthly payments of the same deal would look like one row fed twice. The charge month
        # tells them apart.
        date = r["purchase_date"]
        if is_installment(r):
            description = "%s [תשלום שחויב ב-%s]" % (description, r["billing_date"])
            # The payment belongs to the month it is charged. With the purchase date, a payment on
            # an old deal would fall outside the reflection period and silently drop out.
            date = r["billing_date"]
        # The account is the card: summarize.py judges a partial month by all the statements of one card together,
        # because a statement covers a period that crosses months.
        account = "כאל %s" % r["card"] if r.get("card") else ""
        if not in_period(date, period):
            continue
        out.append([date, description, str(amount.quantize(Decimal("0.01"))), r["source_file"], world, account])
    return out


def write_work_file(folder, meta, rows, world, period=None):
    """כותב קובץ עבודה אחד לדף חיוב. מחזיר את הנתיב, או None כשאין שורות in_total=yes (בתקופה)."""
    work = to_work_rows(rows, world, period)
    if not work:
        return None
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, work_file_name(meta))
    tmp = path + ".tmp-%d" % os.getpid()
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(WORK_COLUMNS)
            w.writerows(work)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def main():
    # Windows: without this, stdout to a pipe uses the locale code page and Hebrew output crashes.
    setup_io()
    ap = HebrewParser(description="קורא דפי פירוט של כאל (PDF) ובודק כל דף מול סכום החיוב שכתוב בו. "
                      "--out: קובץ אחד עם כל העסקאות (להשוואה מול התזרים). --work-dir: קובץ עבודה לכל דף, "
                      "למיון. עסקה בתשלומים נרשמת בתאריך החיוב של התשלום. דורש pdftotext.")
    ap.add_argument("pdfs", nargs="+", help="דפי חיוב של כאל, PDF")
    ap.add_argument("--out", help="קובץ csv אחד עם כל העסקאות")
    ap.add_argument("--work-dir", help="תיקייה לקובצי עבודה, אחד לכל דף חיוב (כאל-<כרטיס>-<תאריך חיוב>.csv), "
                    "בפורמט של read_bank_file.py ובלי שורות שאינן בסכום החיוב")
    ap.add_argument("--totals-out", dest="totals_out", metavar="CSV",
                    help="קובץ csv בעמודות billing_date,total: סכום החיוב של כל דף שעבר את הבדיקה מול הסה\"כ שכתוב בו "
                    "(מספר חיובי, שתי ספרות אחרי הנקודה). דף שלא תאם לא נכתב. זה הקלט של summarize.py --card-totals. "
                    "אפשר לבד או יחד עם --out ו---work-dir")
    ap.add_argument("--world", choices=["פרטי", "עסק"], default=None,
                    help="העולם של קובצי העבודה (ברירת מחדל: פרטי, והיא מודפסת). בשימוש עם --work-dir")
    ap.add_argument("--from", dest="from_month", metavar="YYYY-MM",
                    help="בקובצי העבודה: רק שורות מהחודש הזה ואילך (לפי התאריך בקובץ העבודה)")
    ap.add_argument("--to", dest="to_month", metavar="YYYY-MM", help="בקובצי העבודה: רק שורות עד החודש הזה (כולל)")
    a = ap.parse_args()
    for v in (a.from_month, a.to_month):
        if v is not None and not MONTH.match(v):
            print("חודש לא תקין: %r (הפורמט: YYYY-MM)" % v, file=sys.stderr)
            return 1
    period = (a.from_month, a.to_month) if (a.from_month or a.to_month) else None
    if period and not a.work_dir:
        print("'--from' ו-'--to' חלים רק על --work-dir", file=sys.stderr)
        return 1
    if not a.out and not a.work_dir and not a.totals_out:
        print("חסר --out, --work-dir או --totals-out", file=sys.stderr)
        return 1
    world = a.world or "פרטי"
    if not shutil.which("pdftotext"):
        print("pdftotext לא מותקן במחשב הזה (poppler). אי אפשר לקרוא דפי כאל ב-PDF.", file=sys.stderr)
        return 2
    seen, all_rows, bad = set(), [], 0
    work_paths = {}
    totals_rows = []
    if a.work_dir:
        print("עולם קובצי העבודה: %s%s" % (world, "" if a.world else " (ברירת מחדל; --world להחלפה)"))
    for pdf in a.pdfs:
        digest = hashlib.md5(Path(pdf).read_bytes()).hexdigest()
        if digest in seen:
            print(f"דילגתי (עותק זהה לקובץ שכבר נקרא): {Path(pdf).name}")
            continue
        seen.add(digest)
        meta, rows = parse_statement(pdf)
        got = round(sum(r["charge_amount"] or 0 for r in rows if r["in_total"] == "yes"), 2)
        ok = meta["total"] is not None and abs(got - meta["total"]) < 0.01
        if not ok:
            bad += 1
        status = "תואם" if ok else f"לא תואם: נקרא {got:.2f}, בדף {meta['total']}"
        print(f"{meta['card']}\t{meta['billing_date']}\t{len(rows)} עסקאות\t{status}\t{Path(pdf).name}")
        all_rows.extend(rows)
        if a.totals_out and ok:
            if not meta["billing_date"]:
                print(f"לא נכתב סכום חיוב (חסר תאריך חיוב בדף): {Path(pdf).name}")
            elif got <= 0:
                print(f"לא נכתב סכום חיוב (הסכום אינו חיובי): {Path(pdf).name}")
            else:
                totals_rows.append([meta["billing_date"], f"{got:.2f}"])
        if a.work_dir:
            if not ok:
                print(f"לא נכתב קובץ עבודה (הדף לא תואם לסה\"כ שלו): {Path(pdf).name}")
            elif not meta["card"] or not meta["billing_date"]:
                bad += 1
                print(f"לא נכתב קובץ עבודה (חסר כרטיס או תאריך חיוב בדף): {Path(pdf).name}")
            else:
                name = work_file_name(meta)
                if name in work_paths:
                    bad += 1
                    print(f"לא נכתב קובץ עבודה: {Path(pdf).name} ו-{work_paths[name]} הם שני דפים שונים לאותו כרטיס ותאריך חיוב ({name})")
                    continue
                work_paths[name] = Path(pdf).name
                path = write_work_file(a.work_dir, meta, rows, world, period)
                if path is None:
                    print(f"לא נכתב קובץ עבודה (אין עסקאות בסכום החיוב{' בתקופה' if period else ''}): {Path(pdf).name}")
                else:
                    print(f"נכתב: {path}")
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(all_rows)
    if a.totals_out:
        with open(a.totals_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["billing_date", "total"])
            w.writerows(totals_rows)
        print(f"נכתב: {a.totals_out} ({len(totals_rows)} סכומי חיוב)")
    print(f"נכתבו {len(all_rows)} עסקאות. דפים שלא תאמו: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
