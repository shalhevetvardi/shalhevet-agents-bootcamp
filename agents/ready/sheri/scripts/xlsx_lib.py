"""קריאת קובצי xlsx בלי ספריות חיצוניות (zipfile + xml, ספרייה סטנדרטית בלבד).

הממשק:
    read_workbook(path) -> list[Sheet]
    Sheet.name   - שם הגיליון
    Sheet.rows   - רשימת שורות צפופה: rows[i][j] הוא התא בשורה i+1 ובעמודה j+1 באקסל.
                   ערך התא: str (טקסט), Decimal (מספר), datetime.date (תא בפורמט תאריך), או None (ריק).

תאריכים: תא מספרי שהפורמט שלו הוא פורמט תאריך נהפך ל-date (לפי מערכת 1900 או 1904 של הקובץ).
"""
import re
import zipfile
# בטוח כאן: הקובץ הוא ייצוא מהבנק שהמשתמש הוריד בעצמו, במחשב שלו, וספריית התקן לא טוענת ישויות חיצוניות.
# defusedxml אינו בספרייה הסטנדרטית, והסקריפטים חייבים לרוץ בלי התקנות.
# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
M = "{%s}" % NS_MAIN

MAX_MEMBER_BYTES = 200 * 1024 * 1024

# מזהי פורמט מובנים של אקסל שהם תאריך/שעה
_BUILTIN_DATE_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


class XlsxError(Exception):
    pass


class Sheet(object):
    def __init__(self, name, rows):
        self.name = name
        self.rows = rows


def _read_member(z, name):
    info = z.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise XlsxError("חלק בקובץ ה-xlsx גדול מדי (%s)" % name)
    return z.read(name)


def _col_index(ref):
    """'AB12' -> 28 (מבוסס 1)."""
    letters = re.match(r"([A-Za-z]+)", ref).group(1).upper()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _row_index(ref):
    return int(re.search(r"(\d+)$", ref).group(1))


def _is_date_format(code):
    """האם קוד פורמט מותאם הוא פורמט תאריך (מכיל d או y מחוץ למרכאות וסוגריים מרובעים)."""
    if not code or code.lower() == "general":
        return False
    stripped = re.sub(r'"[^"]*"', "", code)
    stripped = re.sub(r"\[[^\]]*\]", "", stripped)
    stripped = re.sub(r"\\.", "", stripped)
    return re.search(r"[dyDY]", stripped) is not None


def _load_date_styles(z):
    """מחזיר קבוצה של אינדקסי סגנון (cellXfs) שהם פורמט תאריך."""
    if "xl/styles.xml" not in z.namelist():
        return set()
    root = ET.fromstring(_read_member(z, "xl/styles.xml"))
    custom = {}
    numfmts = root.find(M + "numFmts")
    if numfmts is not None:
        for nf in numfmts.findall(M + "numFmt"):
            custom[int(nf.get("numFmtId"))] = nf.get("formatCode") or ""
    date_styles = set()
    xfs = root.find(M + "cellXfs")
    if xfs is not None:
        for i, xf in enumerate(xfs.findall(M + "xf")):
            fid = int(xf.get("numFmtId") or 0)
            if fid in _BUILTIN_DATE_IDS or (fid in custom and _is_date_format(custom[fid])):
                date_styles.add(i)
    return date_styles


def _load_shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(_read_member(z, "xl/sharedStrings.xml"))
    out = []
    for si in root.findall(M + "si"):
        # טקסט רגיל (t) וטקסט עשיר (r/t); מדלגים על הקראה פונטית (rPh)
        parts = []
        for child in si:
            if child.tag == M + "t":
                parts.append(child.text or "")
            elif child.tag == M + "r":
                for t in child.findall(M + "t"):
                    parts.append(t.text or "")
        out.append("".join(parts))
    return out


def serial_to_date(serial, date1904=False):
    """מספר סידורי של אקסל -> date."""
    n = int(serial)
    if date1904:
        return date(1904, 1, 1) + timedelta(days=n)
    # מערכת 1900: הבאג של 1900 כשנה מעוברת; ממספר 61 ומעלה ההפרש קבוע
    if n < 61:
        return date(1899, 12, 31) + timedelta(days=n)
    return date(1899, 12, 30) + timedelta(days=n)


def _sheet_targets(z):
    wb = ET.fromstring(_read_member(z, "xl/workbook.xml"))
    rels = ET.fromstring(_read_member(z, "xl/_rels/workbook.xml.rels"))
    relmap = {}
    for r in rels.findall("{%s}Relationship" % NS_PKG_REL):
        relmap[r.get("Id")] = r.get("Target")
    date1904 = False
    pr = wb.find(M + "workbookPr")
    if pr is not None and pr.get("date1904") in ("1", "true"):
        date1904 = True
    sheets = []
    sheets_el = wb.find(M + "sheets")
    if sheets_el is None:
        raise XlsxError("אין גיליונות בקובץ")
    for s in sheets_el.findall(M + "sheet"):
        rid = s.get("{%s}id" % NS_REL)
        target = relmap.get(rid)
        if target is None:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = "xl/" + target
        sheets.append((s.get("name"), path))
    return sheets, date1904


def _parse_sheet(z, path, shared, date_styles, date1904):
    root = ET.fromstring(_read_member(z, path))
    data = root.find(M + "sheetData")
    cells = {}
    max_r = 0
    max_c = 0
    if data is not None:
        for c in data.iter(M + "c"):
            ref = c.get("r")
            if not ref:
                continue
            t = c.get("t")
            v = c.find(M + "v")
            value = None
            if t == "inlineStr":
                value = "".join((x.text or "") for x in c.iter(M + "t"))
            elif v is None or v.text is None:
                value = None
            elif t == "s":
                idx = int(v.text)
                value = shared[idx] if 0 <= idx < len(shared) else None
            elif t in ("str", "e"):
                value = v.text
            elif t == "b":
                value = "TRUE" if v.text.strip() == "1" else "FALSE"
            else:
                try:
                    num = Decimal(v.text)
                except InvalidOperation:
                    num = None
                if num is not None:
                    style = int(c.get("s") or 0)
                    if style in date_styles:
                        try:
                            value = serial_to_date(num, date1904)
                        except (OverflowError, ValueError):
                            value = num
                    else:
                        value = num
            if value is None or value == "":
                continue
            r, col = _row_index(ref), _col_index(ref)
            cells[(r, col)] = value
            max_r = max(max_r, r)
            max_c = max(max_c, col)
    rows = []
    for r in range(1, max_r + 1):
        rows.append([cells.get((r, col)) for col in range(1, max_c + 1)])
    return rows


def read_workbook(path):
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise XlsxError("הקובץ אינו xlsx תקין: %s" % e)
    with z:
        try:
            shared = _load_shared_strings(z)
            date_styles = _load_date_styles(z)
            targets, date1904 = _sheet_targets(z)
            result = []
            for name, p in targets:
                if p not in z.namelist():
                    continue
                result.append(Sheet(name, _parse_sheet(z, p, shared, date_styles, date1904)))
        except (KeyError, ET.ParseError) as e:
            raise XlsxError("מבנה ה-xlsx אינו נקרא: %s" % e)
    return result
