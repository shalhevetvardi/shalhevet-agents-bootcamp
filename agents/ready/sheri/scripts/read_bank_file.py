"""קובץ בנק או אשראי (csv / xlsx) ← טבלה אחידה: date,description,amount,source_file,world.

שימוש:  python3 -I read_bank_file.py <קובץ> --world פרטי|עסק [--out <נתיב.csv>] [--billing-totals [--totals-out <נתיב.csv>]]
הוצאה שלילית, הכנסה חיובית. סיכום הקריאה (קובץ, שורת כותרות, מספר תנועות, סכומים, טווח) מודפס ל-stderr,
וכך גם כל שורה שדולגה ויש בה סכום (עד 20).
--billing-totals (לקובץ כרטיס עם עמודת 'תאריך חיוב'): מדפיס ל-stdout סכום חיוב לכל תאריך חיוב.
--totals-out (עם --billing-totals): כותב את אותם סכומים לקובץ csv בעמודות billing_date,total (סכום חיובי, שתי ספרות
אחרי הנקודה), לשימוש ב-summarize.py --card-totals. בלי עמודת 'תאריך חיוב' - נכשל ולא נכתב קובץ.
"""
import csv
import io
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    HebrewParser, ScriptError, money2, parse_amount, parse_date, read_text_any, run_main,
)
from xlsx_lib import XlsxError, read_workbook  # noqa: E402

SUMMARY_WORDS = ("סה\"כ", "סהכ", "סה״כ", "סיכום", "total")
MAX_SKIPPED_LISTED = 20   # כמה שורות שדולגו עם סכום מודפסות בשלמותן


# ---------------------------------------------------------------- טעינת שורות

def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return " ".join(v.split())
    return str(v)


def _csv_candidates(text):
    """מחזיר רשימת (מפריד, שורות) לפי כמה פעמים כל מפריד מופיע בשורות הראשונות."""
    head = "\n".join(text.splitlines()[:50])
    counts = [(head.count(d), d) for d in (",", ";", "\t")]
    counts.sort(key=lambda x: -x[0])
    result = []
    for n, d in counts:
        if n == 0:
            continue
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=d))
        result.append((d, rows))
    if not result:
        result.append((",", list(csv.reader(io.StringIO(text, newline=""), delimiter=","))))
    return result


def _find_header(rows):
    """מחזיר (אינדקס שורה, מיפוי עמודות) לשורה הראשונה שיש בה עמודת תאריך ועמודת סכום; או None."""
    for i, row in enumerate(rows):
        texts = [_cell_text(c) for c in row]
        date_cols = [j for j, t in enumerate(texts) if "תאריך" in t]
        if not date_cols:
            continue
        amount_cols = [j for j, t in enumerate(texts) if "סכום" in t]
        debit = [j for j, t in enumerate(texts) if "חובה" in t and "תאריך" not in t]
        credit = [j for j, t in enumerate(texts) if "זכות" in t and "תאריך" not in t]
        if not amount_cols and not (debit and credit):
            continue
        return i, _map_columns(texts, date_cols, amount_cols, debit, credit)
    return None


def _pick_date_col(texts, date_cols):
    for j in date_cols:
        if texts[j].strip() == "תאריך":
            return j
    for key in ("תאריך עסקה", "תאריך רכישה"):
        for j in date_cols:
            if key in texts[j]:
                return j
    return date_cols[0]


def _map_columns(texts, date_cols, amount_cols, debit, credit):
    m = {"texts": texts}
    m["date"] = _pick_date_col(texts, date_cols)
    card_marker = any("בית עסק" in t or "בית העסק" in t for t in texts)
    pure_debit = [j for j in debit if j not in credit]
    pure_credit = [j for j in credit if j not in debit]
    shared = [j for j in debit if j in credit]
    if pure_debit and pure_credit:
        m["mode"] = "pair"
        m["debit"], m["credit"] = pure_debit[0], pure_credit[0]
        used = {m["date"], m["debit"], m["credit"]}
    elif shared:
        # כותרת אחת שמכילה גם 'חובה' וגם 'זכות' (למשל 'זכות/חובה'): עמודה אחת עם סימן, לא זוג עמודות
        m["mode"] = "combined"
        m["amount"] = shared[0]
        used = {m["date"], shared[0]}
    else:
        chosen = None
        by_charge = [j for j in amount_cols if "חיוב" in texts[j]]
        exact = [j for j in amount_cols if texts[j].strip() == "סכום"]
        if by_charge:
            chosen = by_charge[0]
        elif exact:
            chosen = exact[0]
        elif len(amount_cols) == 1:
            chosen = amount_cols[0]
        else:
            raise ScriptError(
                "יש כמה עמודות סכום (%s) ואין ביניהן 'סכום חיוב' או 'סכום' בלבד. לא ברור באיזו להשתמש."
                % ", ".join(texts[j] for j in amount_cols)
            )
        m["amount"] = chosen
        m["mode"] = "card" if (card_marker or "חיוב" in texts[chosen]) else "single"
        used = {m["date"], chosen}
    # עמודת תיאור
    desc = None
    for keys in (("תיאור",), ("שם בית עסק", "בית העסק", "בית עסק"), ("פרטים",), ("פעולה",)):
        for j, t in enumerate(texts):
            if j not in used and any(k in t for k in keys):
                desc = j
                break
        if desc is not None:
            break
    m["desc_guessed"] = False
    if desc is None:
        for j, t in enumerate(texts):
            if j in used or not t or "תאריך" in t or "יתרה" in t or "אסמכתא" in t or "סכום" in t:
                continue
            desc = j
            m["desc_guessed"] = True
            break
    if desc is None:
        raise ScriptError("לא נמצאה עמודת תיאור בשורת הכותרות: %s" % " | ".join(t for t in texts if t))
    m["desc"] = desc
    billing = [j for j, t in enumerate(texts) if "תאריך חיוב" in t]
    m["billing"] = billing[0] if billing else None
    return m


def _load_csv(path):
    text, enc = read_text_any(path)
    candidates = _csv_candidates(text)
    for delim, rows in candidates:
        found = _find_header(rows)
        if found:
            return {"label": None, "rows": rows, "header": found, "encoding": enc}
    return {"label": None, "rows": candidates[0][1], "header": None, "encoding": enc}


def _load_xlsx(path):
    try:
        sheets = read_workbook(path)
    except XlsxError as e:
        raise ScriptError(str(e))
    first = None
    for sh in sheets:
        if first is None:
            first = sh
        found = _find_header(sh.rows)
        if found:
            return {"label": sh.name, "rows": sh.rows, "header": found, "encoding": "xlsx"}
    return {"label": first.name if first else None, "rows": first.rows if first else [], "header": None, "encoding": "xlsx"}


def _show_structure(rows):
    """5 השורות הראשונות, רק תאים עם אותיות (כותרות וטקסט), בלי עמודות סכום."""
    lines = []
    shown = 0
    for row in rows:
        if shown == 5:
            break
        if not any(_cell_text(c) for c in row):
            continue
        cells = []
        for c in row:
            t = _cell_text(c)
            if t and any(ch.isalpha() for ch in t):
                cells.append(t[:40])
        lines.append("  " + (" | ".join(cells) if cells else "(שורה בלי טקסט)"))
        shown += 1
    return "\n".join(lines)


# ---------------------------------------------------------------- המרת שורות

def _is_summary(texts):
    joined = " ".join(texts).lower()
    return any(w in joined for w in SUMMARY_WORDS)


def convert(loaded):
    rows = loaded["rows"]
    hdr_idx, m = loaded["header"]
    out = []
    billing_dates = []   # במקביל ל-out: תאריך החיוב של כל תנועה (או None)
    skipped = 0
    skipped_rows = []    # שורות שדולגו ויש בהן סכום: (מספר שורה, תאים, ערכי הסכום שנקראו)
    for i in range(hdr_idx + 1, len(rows)):
        row = rows[i]
        lineno = i + 1

        def cell(j):
            return row[j] if j < len(row) else None

        if not any(_cell_text(c) for c in row):
            continue
        texts = [_cell_text(c) for c in row]
        d = parse_date(cell(m["date"]))
        if m["mode"] == "pair":
            raw_cells = [cell(m["debit"]), cell(m["credit"])]
        else:
            raw_cells = [cell(m["amount"])]
        if d is None:
            date_text = _cell_text(cell(m["date"]))
            has_amount = any(_cell_text(c) for c in raw_cells)
            if date_text and has_amount and not _is_summary(texts):
                try:
                    for c in raw_cells:
                        parse_amount(c)
                except ValueError:
                    pass
                else:
                    raise ScriptError(
                        "שורה %d: תאריך לא מזוהה (%r). התבנית הצפויה יום/חודש/שנה או שנה-חודש-יום." % (lineno, date_text)
                    )
            skipped += 1
            if has_amount:
                values = []
                for c in raw_cells:
                    try:
                        v = parse_amount(c)
                    except ValueError:
                        v = None
                    if v is not None:
                        values.append(v)
                skipped_rows.append((lineno, texts, values))
            continue
        if not any(_cell_text(c) for c in raw_cells):
            skipped += 1
            continue
        try:
            if m["mode"] == "pair":
                debit = parse_amount(raw_cells[0]) or Decimal(0)
                credit = parse_amount(raw_cells[1]) or Decimal(0)
                amount = credit - debit
            else:
                amount = parse_amount(raw_cells[0])
        except ValueError:
            raise ScriptError("שורה %d: סכום לא מזוהה (%r)" % (lineno, " / ".join(_cell_text(c) for c in raw_cells)))
        desc = _cell_text(cell(m["desc"]))
        out.append([d, desc, amount])
        billing_dates.append((lineno, parse_date(cell(m["billing"])) if m.get("billing") is not None else None))
    if not out:
        raise ScriptError("לא נמצאו תנועות מתחת לשורת הכותרות (שורה %d)." % (hdr_idx + 1))
    # סימן
    if m["mode"] == "card":
        out = [[d, desc, -a] for d, desc, a in out]
    elif m["mode"] == "single":
        has_neg = any(a < 0 for _, _, a in out)
        if not has_neg:
            raise ScriptError(
                "בקובץ עמודת סכום אחת וכל הסכומים חיוביים, ואין סימן שמעיד על קובץ אשראי "
                "(כותרת 'סכום חיוב' או עמודת 'בית עסק'). לא ברור אם אלה הוצאות או הכנסות, ולכן לא מנחשת. "
                "כדאי לבדוק מול הבנק או חברת האשראי איזה סוג קובץ זה."
            )
    return out, skipped, skipped_rows, billing_dates


# ---------------------------------------------------------------- שורות שדולגו וסכומי חיוב

def skipped_lines(skipped_rows, out):
    """שורות שדולגו ויש בהן סכום ← שורות להדפסה (עד MAX_SKIPPED_LISTED), עם סימון לשורת סיכום.

    שורה נחשבת 'כנראה שורת סיכום' כשאחד מערכיה (או הסכום הנקי שלה) שווה, עד לאגורה, לסכום החובות שנקרא,
    לסכום הזכויות שנקרא או לסכום הנקי."""
    credits = sum((a for _, _, a in out if a > 0), Decimal(0))
    debits = -sum((a for _, _, a in out if a < 0), Decimal(0))
    net = credits - debits
    targets = {t.quantize(Decimal("0.01")) for t in (credits, debits, abs(net)) if t != 0}
    lines = []
    for lineno, texts, values in skipped_rows[:MAX_SKIPPED_LISTED]:
        shown = [abs(v) for v in values]
        if len(values) > 1:
            shown.append(abs(values[1] - values[0]))   # זוג חובה/זכות: הסכום הנקי של השורה
        looks_like_total = any(v.quantize(Decimal("0.01")) in targets for v in shown)
        line = "  שורה %d: %s" % (lineno, " | ".join(t for t in texts if t))
        if looks_like_total:
            line += " (שווה לסכום שנקרא - כנראה שורת סיכום)"
        lines.append(line)
    if len(skipped_rows) > MAX_SKIPPED_LISTED:
        lines.append("  ... ועוד %d" % (len(skipped_rows) - MAX_SKIPPED_LISTED))
    return lines


def billing_totals(out, billing_dates, m):
    """סכום החיוב לכל תאריך חיוב (מספר חיובי) ← ([(תאריך, סכום)], סה"כ)."""
    if m.get("billing") is None:
        raise ScriptError(
            "אין בקובץ עמודת 'תאריך חיוב', ולכן אי אפשר לחשב סכומי חיוב לפי תאריך. "
            "--billing-totals מיועד לקובץ פירוט של כרטיס אשראי שיש בו עמודה כזו.\n"
            "שורת הכותרות שנקראה: %s" % " | ".join(t for t in m["texts"] if t)
        )
    sums = {}
    for (d, desc, amount), (lineno, bd) in zip(out, billing_dates):
        if bd is None:
            raise ScriptError("שורה %d: תאריך החיוב ריק או לא מזוהה, ולכן אי אפשר לשייך את העסקה לחיוב." % lineno)
        sums[bd] = sums.get(bd, Decimal(0)) - amount
    rows = sorted(sums.items())
    return rows, sum((v for _, v in rows), Decimal(0))


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(
        description="קורא קובץ בנק או אשראי (csv/xlsx) ומפיק טבלה אחידה: date,description,amount,source_file,world. "
        "הוצאה שלילית, הכנסה חיובית. סיכום הקריאה מודפס ל-stderr.",
    )
    p.add_argument("file", help="קובץ בנק או אשראי (csv או xlsx)")
    p.add_argument("--world", required=True, choices=["פרטי", "עסק"], help="העולם של הקובץ: פרטי או עסק")
    p.add_argument("--out", help="נתיב קובץ csv לפלט (בלי זה - הפלט ל-stdout)")
    p.add_argument("--billing-totals", dest="billing_totals", action="store_true",
                   help="לקובץ כרטיס אשראי עם עמודת 'תאריך חיוב': מדפיס ל-stdout שורה לכל תאריך חיוב (YYYY-MM-DD: סכום, "
                   "מספר חיובי עם שתי ספרות אחרי הנקודה) ושורה אחרונה 'סה\"כ'. כך מתאימים כל חיוב כרטיס בקובץ הבנק לפירוט הכרטיס. "
                   "לא צריך --out. בלי עמודת 'תאריך חיוב' - נכשל")
    p.add_argument("--totals-out", dest="totals_out", metavar="CSV",
                   help="עם --billing-totals: כותב את סכומי החיוב לקובץ csv בעמודות billing_date,total (סכום חיובי, שתי ספרות "
                   "אחרי הנקודה), בנוסף לשורות שמודפסות ל-stdout. הקובץ הזה הוא הקלט של summarize.py --card-totals. "
                   "בלי עמודת 'תאריך חיוב' - נכשל ולא נכתב קובץ")
    a = p.parse_args()
    if a.totals_out and not a.billing_totals:
        raise ScriptError("--totals-out דורש גם --billing-totals")

    path = a.file
    if not os.path.isfile(path):
        raise ScriptError("הקובץ לא נמצא: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        loaded = _load_csv(path)
    elif ext == ".xlsx":
        loaded = _load_xlsx(path)
    else:
        raise ScriptError("סוג קובץ לא נתמך (%s). נתמכים: csv, xlsx." % (ext or "בלי סיומת"))

    if loaded["header"] is None:
        raise ScriptError(
            "לא נמצאה שורת כותרות (שורה עם עמודת 'תאריך' ועמודת 'סכום', או 'חובה' ו'זכות').\n"
            "החמש הראשונות בקובץ (כותרות וטקסט בלבד, בלי עמודות הסכום):\n%s" % _show_structure(loaded["rows"])
        )
    hdr_idx, m = loaded["header"]
    out, skipped, skipped_rows, billing_dates = convert(loaded)
    billing = billing_totals(out, billing_dates, m) if a.billing_totals else None

    source = os.path.basename(path)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "description", "amount", "source_file", "world"])
    for d, desc, amount in out:
        w.writerow([d.isoformat(), desc, money2(amount), source, a.world])
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())
    elif billing is None:
        sys.stdout.write(buf.getvalue())

    income = sum((x[2] for x in out if x[2] > 0), Decimal(0))
    expense = sum((x[2] for x in out if x[2] < 0), Decimal(0))
    dates = [x[0] for x in out]
    err = sys.stderr
    print("קובץ: %s" % source, file=err)
    where = "שורה %d" % (hdr_idx + 1)
    if loaded["label"]:
        where += ", גיליון '%s'" % loaded["label"]
    print("שורת כותרות: %s (%s)" % (where, " | ".join(t for t in m["texts"] if t)), file=err)
    kinds = {"pair": "חובה/זכות", "card": "אשראי (סכום חיוב ← הוצאה)", "single": "סכום אחד עם סימן",
             "combined": "עמודה אחת עם סימן (חיובי = זכות, שלילי = חובה)"}
    print("סוג סכום שזוהה: %s" % kinds[m["mode"]], file=err)
    if m["mode"] == "combined":
        print("זוהתה עמודה אחת שהכותרת שלה כוללת גם 'חובה' וגם 'זכות': '%s'. היא נקראה כעמודה אחת עם סימן: "
              "ערך חיובי = זכות (הכנסה), ערך שלילי = חובה (הוצאה). כדאי לוודא מול הבנק שהסימן בקובץ הוא כזה."
              % m["texts"][m["amount"]], file=err)
    if m["desc_guessed"]:
        print("שימו לב: עמודת התיאור נבחרה בהיסק (%s)" % m["texts"][m["desc"]], file=err)
    print("קידוד: %s" % loaded["encoding"], file=err)
    print("עולם: %s" % a.world, file=err)
    print("מספר תנועות: %d" % len(out), file=err)
    print("סכום הכנסות: %s" % money2(income), file=err)
    print("סכום הוצאות: %s" % money2(expense), file=err)
    print("טווח תאריכים: %s עד %s" % (min(dates).isoformat(), max(dates).isoformat()), file=err)
    if skipped:
        print("שורות שדולגו (בלי תאריך תקין או בלי סכום, למשל סיכומים): %d, מהן עם סכום: %d" % (skipped, len(skipped_rows)), file=err)
        if skipped_rows:
            print("השורות שדולגו ויש בהן סכום (מספר שורה בקובץ המקור ותוכן התאים):", file=err)
            for line in skipped_lines(skipped_rows, out):
                print(line, file=err)
    if a.out:
        print("נכתב: %s" % a.out, file=err)
    if billing is not None:
        rows_b, total_b = billing
        for bd, v in rows_b:
            print("%s: %s" % (bd.isoformat(), money2(v)))
        print("סה\"כ: %s" % money2(total_b))
        if a.totals_out:
            tbuf = io.StringIO()
            tw = csv.writer(tbuf, lineterminator="\n")
            tw.writerow(["billing_date", "total"])
            for bd, v in rows_b:
                tw.writerow([bd.isoformat(), money2(v)])
            try:
                with open(a.totals_out, "w", encoding="utf-8", newline="") as f:
                    f.write(tbuf.getvalue())
            except OSError as e:
                raise ScriptError("לא ניתן לכתוב את %s: %s" % (a.totals_out, e.strerror or e))
            print("נכתב: %s" % a.totals_out, file=err)
    return 0


if __name__ == "__main__":
    run_main(main)
