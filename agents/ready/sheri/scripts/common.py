"""פונקציות משותפות לסקריפטים של שרי (ספרייה סטנדרטית בלבד).

הסקריפטים רצים עם python3 -I, ובמצב כזה תיקיית הסקריפט אינה ב-sys.path.
לכן כל סקריפט מוסיף את התיקייה שלו בעצמו לפני הייבוא:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
"""
import argparse
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


class ScriptError(Exception):
    """כשל צפוי: ההודעה (בעברית) מודפסת ל-stderr וקוד היציאה 1."""


# ---------------------------------------------------------------- קלט/פלט

def setup_io():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def run_main(main):
    """מריץ main(); כשל צפוי או לא צפוי ← הודעה בעברית ל-stderr וקוד 1."""
    setup_io()
    try:
        code = main()
    except ScriptError as e:
        print("שגיאה: %s" % e, file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        sys.exit(1)
    except Exception as e:  # כשל לא צפוי - לא להסתיר, אבל בעברית וקוד 1
        print("שגיאה פנימית (%s): %s" % (type(e).__name__, e), file=sys.stderr)
        sys.exit(1)
    sys.exit(code or 0)


def read_text_any(path, encodings=("utf-8", "utf-8-sig", "cp1255")):
    """קורא קובץ טקסט; מנסה קידודים לפי הסדר. מחזיר (טקסט, קידוד)."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ScriptError("לא ניתן לקרוא את הקובץ %s: %s" % (path, e.strerror or e))
    for enc in encodings:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if text.startswith("﻿"):
            text = text[1:]
        return text, enc
    raise ScriptError("לא הצלחתי לפענח את הקידוד של %s (ניסיתי %s)" % (path, ", ".join(encodings)))


# ---------------------------------------------------------------- שורת פקודה

class _HebrewFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = "שימוש: "
        return super(_HebrewFormatter, self).add_usage(usage, actions, groups, prefix)


class HebrewParser(argparse.ArgumentParser):
    """מפרש שורת פקודה עם עזרה והודעות שגיאה בעברית וקוד יציאה 1 בכשל."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", _HebrewFormatter)
        kwargs["add_help"] = False
        super(HebrewParser, self).__init__(*args, **kwargs)
        self._positionals.title = "פרמטרים"
        self._optionals.title = "אפשרויות"
        self.add_argument("-h", "--help", action="help", help="הצגת העזרה הזו ויציאה")

    def error(self, message):
        message = re.sub(r"^the following arguments are required: ", "חסרים פרמטרים חובה: ", message)
        message = re.sub(r"^unrecognized arguments: ", "פרמטרים לא מוכרים: ", message)
        message = re.sub(r"invalid choice: (.*) \(choose from (.*)\)", r"ערך לא חוקי: \1 (האפשרויות: \2)", message)
        self.print_usage(sys.stderr)
        print("שגיאה בשורת הפקודה: %s" % message, file=sys.stderr)
        sys.exit(1)


def add_subparsers(parser, **kwargs):
    kwargs.setdefault("title", "פקודות")
    return parser.add_subparsers(**kwargs)


# ---------------------------------------------------------------- מספרים

_STRIP_CHARS = "‎‏‪‫‬  \t"


def parse_amount(value):
    """טקסט/מספר ← Decimal. מחזיר None לתא ריק. זורק ValueError לערך שאינו סכום.

    תומך ב: -1,234.56 · (1,234.56) · 1,234.56- · ‏₪1,234 · מינוס יוניקוד · פסיק עשרוני (12,5).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    t = str(value)
    for ch in _STRIP_CHARS:
        t = t.replace(ch, "")
    # מינוס יוניקוד (U+2212), מקף בינוני (U+2013) ומקף מספרי (U+2012) ← מקף רגיל
    for dash in (chr(0x2212), chr(0x2013), chr(0x2012)):
        t = t.replace(dash, "-")
    for sym in ("₪", "$", "€", "£", "ש\"ח", "שח"):
        t = t.replace(sym, "")
    if t == "":
        return None
    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1]
    if t.endswith("-"):
        negative = True
        t = t[:-1]
    if t.startswith("-"):
        negative = True
        t = t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if t == "" or not re.match(r"^[0-9][0-9,.]*$", t) and not re.match(r"^[.,][0-9]+$", t):
        raise ValueError("סכום לא מזוהה: %r" % value)
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        if re.match(r"^\d{1,3}(,\d{3})+$", t):
            t = t.replace(",", "")
        elif t.count(",") == 1 and re.match(r"^\d*,\d{1,2}$", t):
            t = t.replace(",", ".")
        else:
            raise ValueError("סכום לא מזוהה: %r" % value)
    elif t.count(".") > 1:
        if re.match(r"^\d{1,3}(\.\d{3})+$", t):
            t = t.replace(".", "")
        else:
            raise ValueError("סכום לא מזוהה: %r" % value)
    try:
        number = Decimal(t)
    except InvalidOperation:
        raise ValueError("סכום לא מזוהה: %r" % value)
    return -number if negative else number


def money2(d):
    """Decimal ← מחרוזת עם שתי ספרות אחרי הנקודה."""
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_int(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_shekel(d):
    """Decimal ← '12,345 ₪' מעוגל לשקל."""
    return "{:,} ₪".format(round_int(d))


def fmt_shekel2(d):
    """Decimal ← '12,345.60 ₪' בדיוק של אגורה."""
    return "{:,} ₪".format(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def fmt_shekel_exact(d):
    """Decimal ← '2,400 ₪' כשהסכום שלם, ו-'2,400.50 ₪' (אגורות) רק כשאינו שלם. לא מעגל."""
    cents = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cents == cents.to_integral_value():
        return "{:,} ₪".format(int(cents))
    return "{:,} ₪".format(cents)


# ---------------------------------------------------------------- תאריכים

_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$")
_YMD = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")


def parse_date(value):
    """תא תאריך ← date או None. סדר ברירת מחדל בטקסט: יום/חודש/שנה (ישראלי)."""
    from xlsx_lib import serial_to_date  # מקומי: xlsx_lib בתיקייה הזו

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, Decimal):
        if Decimal("20000") <= value <= Decimal("80000"):
            return serial_to_date(value)
        return None
    t = str(value).strip()
    for ch in "‎‏‪‫‬":
        t = t.replace(ch, "")
    t = re.split(r"[\sT]", t, maxsplit=1)[0] if t else t
    if not t:
        return None
    try:
        m = _YMD.match(t)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DMY.match(t)
        if m:
            year = int(m.group(3))
            if year < 100:
                year += 2000
            return date(year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def parse_iso_date(text, what="תאריך"):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise ScriptError("%s חייב להיות בצורה YYYY-MM-DD, התקבל: %r" % (what, text))


def month_key(d):
    return "%04d-%02d" % (d.year, d.month)


def next_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    m += 1
    if m == 13:
        y, m = y + 1, 1
    return "%04d-%02d" % (y, m)


def add_months(ym, delta):
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + delta
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


# ---------------------------------------------------------------- מניפסט של קובץ ממוין

MANIFEST_SUFFIX = ".manifest.json"
MANIFEST_VERSION = 1


def manifest_path_for(sorted_path):
    """נתיב ברירת המחדל של המניפסט: <ממוין>.manifest.json לצד הקובץ."""
    return sorted_path + MANIFEST_SUFFIX


def row_fingerprint(date_iso, description, amount_text, source_file, world):
    """טביעת אצבע של תנועה: תאריך, תיאור (רווחים מנורמלים), סכום, קובץ מקור ועולם.

    עמודת category אינה חלק ממנה - שרי משנה רק אותה. כל שינוי אחר בשורה משנה את הטביעה.
    """
    import hashlib

    canonical = "\x1f".join([date_iso, " ".join((description or "").split()), amount_text, source_file, world])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- כתיבת פלט בלי לדרוס

def _now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def previous_path(path, stamp):
    """x/ממוין.csv ← x/ממוין.קודם-<stamp>.csv (באותה תיקייה)."""
    import os

    folder, name = os.path.split(path)
    stem, suffix = os.path.splitext(name)
    return os.path.join(folder, "%s.קודם-%s%s" % (stem, stamp, suffix))


def output_is_busy(path, companion_suffixes=()):
    import os

    return [p for p in [path] + [path + s for s in companion_suffixes] if os.path.lexists(p)]


def require_free_output(path, overwrite, companion_suffixes=()):
    """--out לקובץ קיים (או למניפסט קיים לצדו) נכשל, אלא אם ניתן --overwrite."""
    busy = output_is_busy(path, companion_suffixes)
    if busy and not overwrite:
        raise ScriptError(
            "קובץ הפלט כבר קיים: %s. לא דורסים בשקט. כדי להחליף אותו יש להוסיף --overwrite: "
            "הקיים יועבר לשם <שם>.קודם-<תאריך-ושעה> באותה תיקייה ולא יימחק." % ", ".join(busy)
        )


def commit_outputs(path, text, companions=(), overwrite=False):
    """כותב את הפלט (ואת קבצי הלוואי שלו, כ-(סיומת, טקסט)) בלי להשאיר קובץ חלקי.

    קובץ קיים לא נדרס: עם overwrite הוא מועבר (יחד עם קבצי הלוואי שלו) לשם <שם>.קודם-<YYYYMMDD-HHMMSS><סיומת>.
    קודם נכתבים קבצים זמניים ורק אחרי שכולם נכתבו מתבצעת ההעברה, כך שכשל כתיבה לא מזיז את הקיים.
    מחזיר רשימת (ישן, חדש) של מה שהועבר."""
    import os

    suffixes = [s for s, _ in companions]
    require_free_output(path, overwrite, suffixes)
    items = [(path, text)] + [(path + s, t) for s, t in companions]
    tmps = []
    moved = []
    try:
        for final, data in items:
            tmp = "%s.tmp-%d" % (final, os.getpid())
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(data)
            tmps.append((tmp, final))
        if output_is_busy(path, suffixes):
            stamp = _now_stamp()
            base = previous_path(path, stamp)
            n = 1
            while output_is_busy(base, suffixes):
                n += 1
                base = previous_path(path, "%s-%d" % (stamp, n))
            for old, new in [(path, base)] + [(path + s, base + s) for s in suffixes]:
                if os.path.lexists(old):
                    os.rename(old, new)
                    moved.append((old, new))
        for tmp, final in tmps:
            os.replace(tmp, final)
        tmps = []
    except OSError as e:
        raise ScriptError("לא ניתן לכתוב את הפלט: %s" % (e.strerror or e))
    finally:
        for tmp, _ in tmps:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return moved
