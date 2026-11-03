"""מילוי עמודת category בקובץ הממוין לפי קובץ מיפוי (row_id,category).

שימוש:  python3 -I -B set_categories.py <ממוין.csv> <מיפוי.csv> [--dry-run]

הקובץ הממוין הוא הפלט של prepare_sorting.py. הקובץ <מיפוי.csv> כולל שתי עמודות: row_id,category.
הסקריפט קובע את ערך עמודת category בשורות שה-row_id שלהן במיפוי, וכותב את הקובץ במקום (בכתיבה אטומית),
באותו קידוד, אותו מפריד, אותם מירכאות ואותו סדר עמודות. שום דבר אחר בקובץ לא משתנה, בייט אחר בייט.
כל הבדיקות רצות לפני הכתיבה: כשל ← הודעה בעברית, קוד יציאה 1, והקובץ נשאר כמו שהיה.
"""
import csv
import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import HebrewParser, ScriptError, read_text_any, run_main  # noqa: E402
from summarize import Ambiguous, Resolver, Unknown, _norm, load_categories  # noqa: E402

MAX_LISTED = 20   # כמה פריטים מפורטים מודפסים לכל סוג שגיאה
DELIMITERS = (",", ";", "\t")


# ---------------------------------------------------------------- סריקת csv עם מיקומי השדות

def scan_records(text, delim):
    """מפרק טקסט csv לרשומות. כל רשומה: ([(התחלה, סוף, ערך) לכל שדה], מספר השורה שבה היא מתחילה).

    המיקומים מאפשרים להחליף שדה אחד בלי לגעת בשום תו אחר בקובץ."""
    records = []
    i, n, line = 0, len(text), 1
    while i < n:
        fields = []
        rec_line = line
        while True:
            start = i
            if i < n and text[i] == '"':
                i += 1
                buf = []
                while i < n:
                    ch = text[i]
                    if ch == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            buf.append('"')
                            i += 2
                            continue
                        i += 1
                        break
                    if ch == "\n":
                        line += 1
                    buf.append(ch)
                    i += 1
                while i < n and text[i] not in (delim, "\r", "\n"):   # תווים אחרי המירכאה הסוגרת
                    buf.append(text[i])
                    i += 1
                value = "".join(buf)
            else:
                while i < n and text[i] not in (delim, "\r", "\n"):
                    i += 1
                value = text[start:i]
            fields.append((start, i, value))
            if i < n and text[i] == delim:
                i += 1
                continue
            break
        if i < n:
            if text[i] == "\r":
                i += 1
                if i < n and text[i] == "\n":
                    i += 1
            else:
                i += 1
            line += 1
        records.append((fields, rec_line))
    return records


def render_field(value, delim):
    """ערך ← שדה csv (במירכאות רק כשחייבים)."""
    if any(c in value for c in (delim, '"', "\n", "\r")) or value != value.strip():
        return '"' + value.replace('"', '""') + '"'
    return value


# ---------------------------------------------------------------- קריאת הקבצים

def read_sorted(path):
    """קובץ ממוין ← (טקסט, קידוד, האם יש BOM, מפריד, רשומות, אינדקס row_id, אינדקס category, אינדקס כותרת)."""
    if not os.path.isfile(path):
        raise ScriptError("הקובץ הממוין לא נמצא: %s" % path)
    with open(path, "rb") as f:
        has_bom = f.read(3) == b"\xef\xbb\xbf"
    text, enc = read_text_any(path)
    for delim in DELIMITERS:
        records = scan_records(text, delim)
        for k, (fields, _) in enumerate(records):
            names = [v.strip() for _, _, v in fields]
            if len(fields) == 1 and not names[0]:
                continue   # שורה ריקה לפני הכותרות
            if "row_id" in names and "category" in names:
                return text, enc, has_bom, delim, records, names.index("row_id"), names.index("category"), k
            break
    raise ScriptError(
        "בקובץ %s אין שורת כותרות עם העמודות row_id ו-category. "
        "הקובץ הממוין מופק על ידי prepare_sorting.py, ושרי מוסיפה לו ערכים רק בעמודת category." % path
    )


def read_mapping(path):
    """קובץ מיפוי ← [(מספר שורה, row_id, category)]."""
    if not os.path.isfile(path):
        raise ScriptError("קובץ המיפוי לא נמצא: %s" % path)
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    reader.fieldnames = cols
    for need in ("row_id", "category"):
        if need not in cols:
            raise ScriptError("בקובץ המיפוי חסרה העמודה %s (העמודות: row_id,category)" % need)
    out = []
    for row in reader:
        rid = (row.get("row_id") or "").strip()
        cat = _norm(row.get("category") or "")
        if not rid and not cat:
            continue
        n = reader.line_num
        if not rid:
            raise ScriptError("בקובץ המיפוי, שורה %d: חסר row_id" % n)
        if not cat:
            raise ScriptError("בקובץ המיפוי, שורה %d: חסרה קטגוריה עבור %s. אין להשאיר שורה בלי קטגוריה "
                              "(לתנועה שלא ברור מה היא: 'לא ברור')." % (n, rid))
        out.append((n, rid, cat))
    if not out:
        raise ScriptError("אין שורות בקובץ המיפוי %s" % path)
    return out


# ---------------------------------------------------------------- בדיקות והחלפה

def listed(title, items):
    lines = ["%s: %d" % (title, len(items))]
    for it in items[:MAX_LISTED]:
        lines.append("  - " + it)
    if len(items) > MAX_LISTED:
        lines.append("  ... ועוד %d" % (len(items) - MAX_LISTED))
    return "\n".join(lines)


def build_edits(mapping, records, header_idx, rid_idx, cat_idx):
    """בודק את המיפוי מול הקובץ ומול categories.json. מחזיר ({row_id: (התחלה, סוף, שורה)}, מספר שורות הנתונים,
    כמה מהן בלי קטגוריה אחרי השינוי). כשל ← ScriptError אחד שמרכז את כל הבעיות."""
    resolver = Resolver(load_categories())
    header_values = [v.strip() for _, _, v in records[header_idx][0]]
    where = {}      # row_id -> [(התחלה, סוף, ערך נוכחי, מספר שורה, האם יש עמודת category)]
    data = []       # (row_id, ערך נוכחי של category) לכל שורת נתונים
    for fields, line in records[header_idx + 1:]:
        if len(fields) == 1 and not fields[0][2].strip():
            continue
        if [v.strip() for _, _, v in fields] == header_values:
            continue   # שורת כותרות שחוזרת כשחיברו כמה קבצים
        rid = fields[rid_idx][2].strip() if len(fields) > rid_idx else ""
        has_cat = len(fields) > cat_idx
        current = fields[cat_idx][2] if has_cat else ""
        data.append((rid, current))
        if rid:
            where.setdefault(rid, []).append((fields[cat_idx][0], fields[cat_idx][1], line) if has_cat else (None, None, line))

    problems = []
    seen = {}
    dup = []
    for n, rid, cat in mapping:
        if rid in seen:
            dup.append("%s (שורות %d ו-%d במיפוי)" % (rid, seen[rid], n))
        seen.setdefault(rid, n)
    if dup:
        problems.append(listed("מזהי row_id שחוזרים בקובץ המיפוי", dup))

    unknown_ids = ["%s (שורה %d במיפוי)" % (rid, n) for n, rid, _ in mapping if rid not in where]
    if unknown_ids:
        problems.append(listed("מזהי row_id שאינם בקובץ הממוין", unknown_ids))
    repeated = sorted({rid for _, rid, _ in mapping if len(where.get(rid, ())) > 1})
    if repeated:
        problems.append(listed("מזהי row_id שמופיעים יותר מפעם אחת בקובץ הממוין (לא ברור לאיזו שורה לתת קטגוריה)", repeated))
    no_cell = sorted({rid for _, rid, _ in mapping if rid in where and any(s is None for s, _, _ in where[rid])})
    if no_cell:
        problems.append(listed("שורות בקובץ הממוין שחסר בהן תא של category", no_cell))

    bad_cats = []
    for n, rid, cat in mapping:
        try:
            resolver.resolve(cat)
        except Unknown:
            bad_cats.append("%s (שורה %d במיפוי, %s)" % (cat, n, rid))
        except Ambiguous as e:
            bad_cats.append("%s - השם חוזר בתבנית; יש לכתוב צורה מלאה: %s (שורה %d במיפוי)" % (cat, " או ".join(e.options), n))
    if bad_cats:
        problems.append(listed("קטגוריות שאינן ב-categories.json ואינן 'לא ברור'", bad_cats))
    if problems:
        raise ScriptError("%s\nהקובץ הממוין לא שונה." % "\n".join(problems))

    new_by_id = {rid: cat for _, rid, cat in mapping}
    edits = {}
    for rid, cat in new_by_id.items():
        start, end, _ = where[rid][0]
        edits[rid] = (start, end, cat)
    empty_after = sum(1 for rid, current in data if not (new_by_id.get(rid, current) or "").strip())
    return edits, len(data), empty_after


def apply_edits(text, edits, delim):
    for start, end, cat in sorted(edits.values(), key=lambda e: -e[0]):
        text = text[:start] + render_field(cat, delim) + text[end:]
    return text


def write_in_place(path, data):
    real = os.path.realpath(path)
    tmp = "%s.tmp-%d" % (real, os.getpid())
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        shutil.copymode(real, tmp)
        os.replace(tmp, real)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ScriptError("לא ניתן לכתוב את הקובץ %s: %s" % (path, e.strerror or e))


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(
        description="קובע את עמודת category בקובץ הממוין (הפלט של prepare_sorting.py) לפי קובץ מיפוי עם העמודות row_id,category. "
        "משנה רק את ערכי category של השורות שבמיפוי, כותב במקום באותו קידוד ובאותו מבנה, ולא נוגע בשום דבר אחר. "
        "כל הבדיקות רצות לפני הכתיבה: row_id שלא קיים, קטגוריה שאינה ב-categories.json (ואינה 'לא ברור'), "
        "או row_id שחוזר במיפוי ← הודעה, קוד יציאה 1 והקובץ לא משתנה.",
    )
    p.add_argument("sorted_file", metavar="ממוין.csv", help="הקובץ הממוין (הפלט של prepare_sorting.py); נכתב במקום")
    p.add_argument("mapping", metavar="מיפוי.csv", help="קובץ csv עם העמודות row_id,category")
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="מריץ את כל הבדיקות ומדפיס את אותה תוצאה, בלי לכתוב את הקובץ")
    a = p.parse_args()

    text, enc, has_bom, delim, records, rid_idx, cat_idx, header_idx = read_sorted(a.sorted_file)
    mapping = read_mapping(a.mapping)
    edits, rows_total, empty_after = build_edits(mapping, records, header_idx, rid_idx, cat_idx)
    new_text = apply_edits(text, edits, delim)

    if not a.dry_run:
        try:
            body = new_text.encode(enc if enc != "utf-8-sig" else "utf-8")
        except UnicodeEncodeError as e:
            raise ScriptError("קטגוריה אחת לפחות אינה ניתנת לכתיבה בקידוד של הקובץ (%s): %s. הקובץ לא שונה." % (enc, e.reason))
        write_in_place(a.sorted_file, (b"\xef\xbb\xbf" if has_bom else b"") + body)

    if a.dry_run:
        print("הרצה יבשה: הקובץ לא שונה.")
    print("קטגוריה %s ל-%d שורות." % ("הייתה נקבעת" if a.dry_run else "נקבעה", len(edits)))
    print("שורות שעדיין בלי קטגוריה: %d מתוך %d." % (empty_after, rows_total))
    if not a.dry_run:
        print("נכתב: %s" % a.sorted_file)
    return 0


if __name__ == "__main__":
    run_main(main)
