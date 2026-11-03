"""תנועות ממוינות ← שיקוף חודשי לפי רשימת הקטגוריות של שרי (categories.json).

שימוש:  python3 -I summarize.py <ממוין.csv> [--months N] [--out <שיקוף.csv>] [--desired <רצוי.csv>]
                                 [--manifest <נתיב>] [--include-month YYYY-MM] [--card-totals <סכומי-חיוב.csv> ...]

הקלט: הפלט של prepare_sorting.py (עמודות row_id ו-category) לצד המניפסט <ממוין>.manifest.json.
בלי מניפסט - נכשל: הקובץ לא נבדק מול עצמו. הפלט הקריא ל-stdout, כולל בדיקות שלמות והתאמה.
אי-התאמה ← קוד יציאה 1 ולא נכתב קובץ --out.
--card-totals: כל שורה שסווגה "חיוב כרטיס אשראי (מפורט בקובץ האשראי)" חייבת להתאים לסכום חיוב אחד מקובצי הפירוט
(תאריך חיוב שווה לתאריך השורה או עד שלושה ימים לפניו, וסכום שווה עד האגורה). שורה בלי התאמה ← אי-התאמה, קוד 1.
"""
import calendar
import csv
import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    MANIFEST_VERSION, HebrewParser, ScriptError, add_months, commit_outputs, manifest_path_for, money2, month_key,
    parse_amount, parse_iso_date, read_text_any, require_free_output, round_int, row_fingerprint, run_main,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CATEGORIES_PATH = os.path.join(HERE, "categories.json")

UNCLEAR = "לא ברור"
INCOME = "הכנסות"
FIXED = "הוצאות קבועות"
VARIABLE = "הוצאות משתנות"
UNCOUNTED = "לא נספר"
EXPENSE_SECTIONS = (FIXED, VARIABLE)
REQUIRED_COLUMNS = ["date", "description", "amount", "source_file", "world", "row_id", "category"]
PARTIAL_DAYS = 7  # תנועה ראשונה/אחרונה רחוקה יותר מכך מקצה החודש ← "ייתכן חלקי"
MAX_LISTED = 20   # כמה שורות מפורטות מודפסות לכל סוג אי-התאמה
UNCLEAR_IDX = -1
CARD_CHARGE_ITEM = "חיוב כרטיס אשראי (מפורט בקובץ האשראי)"
OUT_OF_PERIOD_ITEM = "חיוב כרטיס על קניות מחוץ לתקופה"
CARD_MATCH_DAYS = 3   # תאריך החיוב בפירוט: שווה לתאריך שורת הבנק או עד כמה ימים לפניו
CARD_NOT_CHECKED_LINE = "לא נבדקה התאמת חיובי כרטיס לפירוט (לא ניתן --card-totals)"
OUT_OF_PERIOD_NOT_CHECKED_LINE = "לא נבדק שחיובי \"מחוץ לתקופה\" קודמים לדף הפירוט הראשון (לא ניתן --card-totals)"

T_INCOME = "סה\"כ הכנסות"
T_FIXED = "סה\"כ הוצאות קבועות"
T_VARIABLE = "סה\"כ הוצאות משתנות"
T_EXPENSES = "סה\"כ הוצאות"
T_BALANCE = "סה\"כ יתרה"
T_UNCOUNTED = "סה\"כ לא נספר"
T_DESIRED_BAL = "יתרה רצויה"
T_FREED = "התפנה"
MAX_PERIOD_MONTHS = 120
DEFAULT_MONTHS = 3


class Ambiguous(Exception):
    def __init__(self, name, options):
        Exception.__init__(self, name)
        self.name = name
        self.options = options


class Unknown(Exception):
    pass


# ---------------------------------------------------------------- קטגוריות

def load_categories(path=CATEGORIES_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            cats = json.load(f)
    except (OSError, ValueError) as e:
        raise ScriptError("categories.json לא נקרא: %s" % e)
    for c in cats:
        if not all(k in c for k in ("section", "group", "item")):
            raise ScriptError("categories.json פגום: פריט בלי section/group/item")
    return cats


def _norm(s):
    return " ".join(str(s).split())


class Resolver(object):
    """שם פריט ← אינדקס ב-categories.json.

    מקובל: שם הפריט לבדו (כשהוא ייחודי), 'קבוצה/פריט', או 'סעיף/קבוצה/פריט'.
    פריט שהשם שלו חוזר ב-categories.json דורש את הצורה המלאה.
    """

    def __init__(self, cats):
        self.cats = cats
        self.tables = [defaultdict(list), defaultdict(list), defaultdict(list)]
        for i, c in enumerate(cats):
            self.tables[0][self.full_name(i)].append(i)
            self.tables[1]["%s/%s" % (_norm(c["group"]), _norm(c["item"]))].append(i)
            self.tables[2][_norm(c["item"])].append(i)

    def full_name(self, i):
        c = self.cats[i]
        return "%s/%s/%s" % (_norm(c["section"]), _norm(c["group"]), _norm(c["item"]))

    def resolve(self, name):
        name = _norm(name)
        if name == UNCLEAR:
            return UNCLEAR_IDX
        for table in self.tables:
            hits = table.get(name)
            if hits:
                if len(hits) == 1:
                    return hits[0]
                raise Ambiguous(name, [self.full_name(i) for i in hits])
        raise Unknown(name)


# ---------------------------------------------------------------- קריאת קלט

def read_transactions(path, allow_empty=False):
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise ScriptError(
            "בקובץ חסרות עמודות: %s. העמודות הנדרשות: %s (הקובץ מופק על ידי prepare_sorting.py, ושרי ממלאת בו רק את category)."
            % (", ".join(missing), ",".join(REQUIRED_COLUMNS))
        )
    rows = []
    for row in reader:
        if row.get("date") == "date":  # שורת כותרות שחוזרת כשחיברו כמה קבצים
            continue
        if not any((v or "").strip() for v in row.values() if not isinstance(v, list)):
            continue
        n = reader.line_num
        try:
            d = parse_iso_date(row["date"], "תאריך בשורה %d" % n)
            amount = parse_amount(row["amount"])
        except ValueError:
            raise ScriptError("שורה %d: סכום לא מזוהה (%r)" % (n, row["amount"]))
        if amount is None:
            raise ScriptError("שורה %d: סכום ריק" % n)
        row_id = (row["row_id"] or "").strip()
        if not row_id:
            raise ScriptError("שורה %d: חסר row_id (העמודה row_id נקבעת על ידי prepare_sorting.py ואין לגעת בה)" % n)
        rows.append({
            "date": d, "description": row["description"], "amount": amount,
            "file": row["source_file"], "world": (row["world"] or "").strip(),
            "category": row["category"] or "", "row_id": row_id, "line": n,
        })
    if not rows and not allow_empty:
        raise ScriptError("אין תנועות בקובץ %s" % path)
    return rows


def read_desired(path, resolver):
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    for need in ("item", "desired"):
        if need not in cols:
            raise ScriptError("בקובץ הרצוי חסרה העמודה %s (העמודות: item,desired)" % need)
    out = OrderedDict()
    for row in reader:
        name = (row.get("item") or "").strip()
        if not name and not (row.get("desired") or "").strip():
            continue
        try:
            idx = resolver.resolve(name)
        except Unknown:
            raise ScriptError("בקובץ הרצוי פריט שלא קיים ב-categories.json: %r" % name)
        except Ambiguous as e:
            raise ScriptError("בקובץ הרצוי השם %r חוזר בתבנית. יש לכתוב צורה מלאה: %s" % (name, " או ".join(e.options)))
        if idx == UNCLEAR_IDX:
            raise ScriptError("בקובץ הרצוי אי אפשר לקבוע רצוי ל'%s'" % UNCLEAR)
        section = resolver.cats[idx]["section"]
        if section not in EXPENSE_SECTIONS:
            raise ScriptError("בקובץ הרצוי הפריט %r אינו הוצאה (תקציב רצוי נקבע רק להוצאות קבועות ומשתנות)" % name)
        if idx in out:
            raise ScriptError("בקובץ הרצוי הפריט %r מופיע יותר מפעם אחת" % name)
        try:
            val = parse_amount(row.get("desired"))
        except ValueError:
            raise ScriptError("בקובץ הרצוי סכום לא מזוהה לפריט %r: %r" % (name, row.get("desired")))
        if val is None or val < 0:
            raise ScriptError("בקובץ הרצוי הסכום לפריט %r חייב להיות מספר חיובי (התקבל %r)" % (name, row.get("desired")))
        out[idx] = val
    return out


# ---------------------------------------------------------------- מניפסט והתאמה

def load_manifest(path):
    if not os.path.isfile(path):
        raise ScriptError(
            "לא נמצא מניפסט: %s\n"
            "summarize.py לא בודק את הקובץ הממוין מול עצמו. את הקובץ הממוין מפיקים עם prepare_sorting.py, "
            "והוא כותב את המניפסט <ממוין>.manifest.json לצדו (ר' INTERFACE.md)." % path
        )
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        raise ScriptError("המניפסט %s לא נקרא: %s" % (path, e))
    try:
        if m["version"] != MANIFEST_VERSION:
            raise ScriptError("המניפסט %s בגרסה %r, והסקריפט מכיר גרסה %d" % (path, m["version"], MANIFEST_VERSION))
        if not isinstance(m["world"], str) or not isinstance(m["files"], dict) or not m["files"]:
            raise KeyError("files")
        for f, info in m["files"].items():
            Decimal(info["sum"])
            if "account" in info and (not isinstance(info["account"], str) or not info["account"].strip()):
                raise KeyError("account")   # אופציונלי (מניפסט ישן בלעדיו), אבל אם יש - מחרוזת לא ריקה
            for mk, v in info["months"].items():
                Decimal(v["sum"])
                int(v["count"])
            if len(info["row_ids"]) != info["count"] or any(rid not in info["rows"] for rid in info["row_ids"]):
                raise KeyError(f)
            for rid in info["row_ids"]:
                info["rows"][rid]["fp"]
                info["rows"][rid]["date"]
                info["rows"][rid]["amount"]
    except ScriptError:
        raise
    except Exception:
        raise ScriptError("המניפסט %s פגום או חסר בו מידע. יש להפיק אותו מחדש עם prepare_sorting.py." % path)
    return m


def single_world(rows):
    worlds = sorted(set(r["world"] for r in rows))
    if len(worlds) > 1:
        raise ScriptError("יש ערבוב עולמות בקובץ (%s). כל קובץ שיקוף הוא עולם אחד." % ", ".join(repr(w) for w in worlds))
    return worlds[0] if worlds else None


def reconcile(rows, manifest):
    """משווה את הקובץ הממוין למניפסט: קבוצת row_id, תוכן כל שורה (חוץ מ-category), ומספר וסכום לכל קובץ וחודש.

    מחזיר (שורות להדפסה, האם הכול תואם)."""
    lines = []
    ok = True
    expected = OrderedDict()   # row_id -> (source_file, פרטי השורה במניפסט)
    for f, info in manifest["files"].items():
        for rid in info["row_ids"]:
            expected[rid] = (f, info["rows"][rid])
    seen = Counter(r["row_id"] for r in rows)

    missing = [rid for rid in expected if rid not in seen]
    extra = [rid for rid in seen if rid not in expected]
    dups = [rid for rid, c in seen.items() if c > 1]
    changed = []
    done = set()
    for r in rows:
        rid = r["row_id"]
        if rid in done or rid not in expected:
            continue
        done.add(rid)
        f, e = expected[rid]
        fp = row_fingerprint(r["date"].isoformat(), r["description"], money2(r["amount"]), r["file"], r["world"])
        if fp != e["fp"]:
            changed.append((rid, r, e))

    lines.append("  מזהי תנועות: במניפסט %d | בקובץ %d (שורות: %d)" % (len(expected), len(seen), len(rows)))

    def listing(title, items, fmt):
        nonlocal ok
        if not items:
            lines.append("  %s: 0" % title)
            return
        ok = False
        lines.append("  %s: %d - אי-התאמה" % (title, len(items)))
        for it in items[:MAX_LISTED]:
            lines.append("    - " + fmt(it))
        if len(items) > MAX_LISTED:
            lines.append("    ... ועוד %d" % (len(items) - MAX_LISTED))

    listing("תנועות שחסרות בקובץ", missing, lambda rid: "%s | %s | %s" % (rid, expected[rid][1]["date"], expected[rid][1]["amount"]))
    listing("תנועות מיותרות בקובץ (אין להן מזהה במניפסט)", extra, lambda rid: rid)
    listing("מזהים שחוזרים יותר מפעם אחת", dups, lambda rid: "%s (%d פעמים)" % (rid, seen[rid]))

    def fmt_changed(c):
        rid, r, e = c
        now_date, now_amount = r["date"].isoformat(), money2(r["amount"])
        if (now_date, now_amount) == (e["date"], e["amount"]):
            return "%s | התאריך והסכום זהים, אבל התיאור, הקובץ או העולם שונו" % rid
        return "%s | במניפסט %s %s | בקובץ %s %s" % (rid, e["date"], e["amount"], now_date, now_amount)

    listing("תנועות ששונו (חוץ מ-category)", changed, fmt_changed)

    # מספר וסכום לכל קובץ וחודש
    got = defaultdict(lambda: [0, Decimal(0)])
    for r in rows:
        k = (r["file"], month_key(r["date"]))
        got[k][0] += 1
        got[k][1] += r["amount"]
        got[(r["file"], None)][0] += 1
        got[(r["file"], None)][1] += r["amount"]
    want = {}
    for f, info in manifest["files"].items():
        want[(f, None)] = (info["count"], Decimal(info["sum"]))
        for mk, v in info["months"].items():
            want[(f, mk)] = (int(v["count"]), Decimal(v["sum"]))
    lines.append("  התאמת מספר תנועות וסכום מול המניפסט, לכל קובץ וחודש:")
    for k in sorted(set(want) | set(got), key=lambda k: (k[0], k[1] or "")):
        w_cnt, w_sum = want.get(k, (0, Decimal(0)))
        g_cnt, g_sum = got[k] if k in got else (0, Decimal(0))
        good = (w_cnt == g_cnt) and (w_sum == g_sum)
        ok = ok and good
        lines.append("    %s | %s | מניפסט %s (%d תנועות) | קובץ %s (%d תנועות) | %s" % (
            k[0], k[1] or "סה\"כ הקובץ", money2(w_sum), w_cnt, money2(g_sum), g_cnt, "תואם" if good else "אי-התאמה"))
    file_world = rows[0]["world"] if rows else None
    if file_world is not None and file_world != manifest["world"]:
        ok = False
        lines.append("  עולם: במניפסט %r, בקובץ %r - אי-התאמה" % (manifest["world"], file_world))
    return lines, ok


def uncovered_spans(intervals, month_start, month_end):
    """הכיסוי המאוחד של טווחי תאריכים בתוך חודש ← [(סוג, מתאריך, עד תאריך, ימים לא מכוסים)].

    intervals: (תנועה ראשונה, תנועה אחרונה) של כל קובץ שנוגע בחודש. הטווחים נחתכים לחודש ומאוחדים.
    סוגים: "start" (מתחילת החודש עד הכיסוי), "gap" (רווח בין שני טווחים), "end" (מהכיסוי עד סוף החודש).
    נכלל רק מה שגדול מ-PARTIAL_DAYS ימים; בדיוק PARTIAL_DAYS עדיין בסדר."""
    one = timedelta(days=1)
    merged = []
    for lo, hi in sorted((max(a, month_start), min(b, month_end)) for a, b in intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    spans = []
    lead = (merged[0][0] - month_start).days
    if lead > PARTIAL_DAYS:
        spans.append(("start", month_start, merged[0][0] - one, lead))
    for prev, nxt in zip(merged, merged[1:]):
        gap = (nxt[0] - prev[1]).days - 1
        if gap > PARTIAL_DAYS:
            spans.append(("gap", prev[1] + one, nxt[0] - one, gap))
    tail = (month_end - merged[-1][1]).days
    if tail > PARTIAL_DAYS:
        spans.append(("end", merged[-1][1] + one, month_end, tail))
    return spans


def partial_candidates(rows, accounts=None, period_months=()):
    """{חודש: [(שם, תאריך ראשון, תאריך אחרון, סיבה, מקובץ-לפי-חשבון)]} - חודשים שייתכן שהם חלקיים.

    accounts: {source_file: חשבון} מהמניפסט. קבצים שהוצהר להם אותו חשבון (אותו כרטיס אשראי, אותו גיליון בתזרים) נבדקים
    יחד: דף חיוב של כרטיס חוצה חודשים, ולכן קובץ אחד לבדו אף פעם לא מכסה חודש, אבל הדפים ברצף כן.
    קובץ בלי חשבון הוא קבוצה לעצמו.

    לכל קבוצה ולכל חודש שלפחות קובץ אחד בה נוגע בו (הטווח שלו חותך את החודש): הטווחים של כל קובצי הקבוצה מאוחדים.
    החודש חלקי כשהכיסוי המאוחד מתחיל יותר מ-PARTIAL_DAYS ימים אחרי תחילת החודש, נגמר יותר מ-PARTIAL_DAYS ימים לפני סופו,
    או שיש בו רווח של יותר מ-PARTIAL_DAYS ימים בין קובץ לקובץ.
    בקבוצה לפי חשבון נבדק כל חודש בין התנועה הראשונה לאחרונה של החשבון, וגם כל חודש בתקופה (period_months), גם חודש
    שאין בו אף תנועה של החשבון: דף שחסר לגמרי, גם בחודש הראשון או האחרון של התקופה.
    קובץ בלי חשבון נבדק רק בחודשים שהוא נוגע בהם."""
    accounts = accounts or {}
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["file"]].append(r["date"])
    ranges = {f: (min(d), max(d)) for f, d in by_file.items()}
    groups = OrderedDict()
    for f in sorted(ranges):
        acct = accounts.get(f)
        groups.setdefault(("account", acct) if acct else ("file", f), []).append(f)
    out = defaultdict(list)
    for (kind, name), files in groups.items():
        grouped = kind == "account"
        lo_all = min(ranges[f][0] for f in files)
        hi_all = max(ranges[f][1] for f in files)
        touched = set()
        for f in files:
            mk, last_mk = month_key(ranges[f][0]), month_key(ranges[f][1])
            while mk <= last_mk:
                touched.add(mk)
                mk = add_months(mk, 1)
        if grouped:
            # Every month between the account's first and last transaction is checked, not only the
            # months some file touches: a statement missing for a whole month leaves that month
            # untouched, and other accounts covering it must not hide that.
            mk, last_mk = month_key(lo_all), month_key(hi_all)
            while mk <= last_mk:
                touched.add(mk)
                mk = add_months(mk, 1)
            # The first or last month of the period, with no statement at all, is outside the account's
            # own range, so the range alone never reaches it.
            touched.update(period_months)
        for mk in sorted(touched):
            year, month = int(mk[:4]), int(mk[5:])
            month_start = date(year, month, 1)
            month_end = date(year, month, calendar.monthrange(year, month)[1])
            inside = [ranges[f] for f in files if ranges[f][0] <= month_end and ranges[f][1] >= month_start]
            if not inside:
                out[mk].append((name, lo_all, hi_all,
                                "אין אף תנועה של החשבון בכל החודש: ייתכן שחסר דף, או שלא היה בו שימוש", True))
                continue
            for span_kind, lo, hi, days in uncovered_spans(inside, month_start, month_end):
                if grouped:
                    if span_kind == "start":
                        reason = "אין כיסוי מתחילת החודש עד %s" % hi.isoformat()
                    elif span_kind == "end":
                        reason = "אין כיסוי מ-%s עד סוף החודש" % lo.isoformat()
                    else:
                        reason = "אין כיסוי מ-%s עד %s" % (lo.isoformat(), hi.isoformat())
                    out[mk].append((name, lo_all, hi_all, reason, True))
                else:
                    first, last = ranges[name]
                    reason = ("התנועה הראשונה בקובץ היא %d ימים אחרי תחילת החודש" if span_kind == "start"
                              else "התנועה האחרונה בקובץ היא %d ימים לפני סוף החודש") % days
                    out[mk].append((name, first, last, reason, False))
    return out


# ---------------------------------------------------------------- התאמת חיובי כרטיס לפירוט

class CardTotals(list):
    """רשימת (תאריך חיוב, סכום), ועוד firsts: תאריך החיוב המוקדם ביותר בכל קובץ (לבדיקת "מחוץ לתקופה")."""
    firsts = ()


def read_card_totals(paths):
    """קובצי billing_date,total (הפלט של read_bank_file.py --billing-totals --totals-out) ← [(תאריך חיוב, סכום)]."""
    seen = set()
    totals = CardTotals()
    firsts = []
    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            raise ScriptError("--card-totals: הקובץ %s ניתן יותר מפעם אחת" % path)
        seen.add(real)
        if not os.path.isfile(path):
            raise ScriptError("קובץ סכומי החיוב לא נמצא: %s" % path)
        file_first = None
        text, _ = read_text_any(path)
        reader = csv.DictReader(io.StringIO(text, newline=""))
        cols = reader.fieldnames or []
        for need in ("billing_date", "total"):
            if need not in cols:
                raise ScriptError(
                    "בקובץ סכומי החיוב %s חסרה העמודה %s (העמודות: billing_date,total; הקובץ מופק עם "
                    "read_bank_file.py --billing-totals --totals-out)" % (path, need))
        for row in reader:
            if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue
            n = reader.line_num
            when = parse_iso_date(row["billing_date"] or "", "תאריך החיוב בשורה %d של %s" % (n, path))
            try:
                total = parse_amount(row["total"])
            except ValueError:
                total = None
            if total is None or total <= 0:
                raise ScriptError("בקובץ סכומי החיוב %s, שורה %d: הסכום חייב להיות מספר חיובי (התקבל %r)" % (path, n, row["total"]))
            totals.append((when, total.quantize(Decimal("0.01"))))
            file_first = when if file_first is None or when < file_first else file_first
        if file_first is not None:
            firsts.append(file_first)
    totals.firsts = tuple(firsts)
    if not totals:
        raise ScriptError("--card-totals: אין אף סכום חיוב בקבצים שניתנו")
    return totals


def card_charge_rows(s):
    """שורות החלון שסווגו כחיוב כרטיס אשראי מפורט, בסדר קבוע."""
    rows = [r for r in s.rows_in_window if r["idx"] != UNCLEAR_IDX and s.cats[r["idx"]]["item"] == CARD_CHARGE_ITEM]
    return sorted(rows, key=lambda r: (r["date"], r["description"], r["row_id"]))


def match_card_charges(rows, totals):
    """משבצת כל שורה לסכום חיוב אחד לכל היותר, וכל סכום לשורה אחת לכל היותר (שיבוץ מקסימלי).

    שורה מתאימה לסכום כשתאריך החיוב שווה לתאריך השורה או עד CARD_MATCH_DAYS ימים לפניו, והסכום שווה לסכום השורה
    (הפוך בסימן) עד האגורה. מחזיר ({אינדקס שורה: אינדקס סכום}, [אינדקסי שורות בלי התאמה])."""
    options = []
    for r in rows:
        want = (-r["amount"]).quantize(Decimal("0.01"))
        options.append([j for j, (when, total) in enumerate(totals)
                        if total == want and 0 <= (r["date"] - when).days <= CARD_MATCH_DAYS])
    owner = {}   # אינדקס סכום -> אינדקס שורה

    def assign(i, visited):
        for j in options[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in owner or assign(owner[j], visited):
                owner[j] = i
                return True
        return False

    for i in range(len(rows)):
        assign(i, set())
    matched = {i: j for j, i in owner.items()}
    return matched, [i for i in range(len(rows)) if i not in matched]


def out_of_period_rows(s):
    """שורות החלון שסווגו "חיוב כרטיס על קניות מחוץ לתקופה", בסדר קבוע."""
    rows = [r for r in s.rows_in_window if r["idx"] != UNCLEAR_IDX and s.cats[r["idx"]]["item"] == OUT_OF_PERIOD_ITEM]
    return sorted(rows, key=lambda r: (r["date"], r["description"], r["row_id"]))


def out_of_period_check(s, totals):
    """חיוב שסווג "מחוץ לתקופה" תקין רק כשהוא קודם לדף הראשון של לפחות קובץ פירוט אחד: אחרת הוא חיוב של התקופה,
    והפירוט שלו צריך להיות בקבצים (או שהוא לא ברור). ← (שורות להדפסה, האם תקין)."""
    rows = out_of_period_rows(s)
    if not rows:
        return [], True
    if totals is None:
        return ["  " + OUT_OF_PERIOD_NOT_CHECKED_LINE], True
    firsts = getattr(totals, "firsts", ()) or ()
    bad = [r for r in rows if not any(r["date"] < f for f in firsts)]
    lines = ["  חיובי כרטיס שסווגו כקניות מחוץ לתקופה: %d, %d מהם קודמים לדף הפירוט הראשון בקבצים"
             % (len(rows), len(rows) - len(bad))]
    if bad:
        lines.append("  אי-התאמה - %d חיובים שסווגו \"מחוץ לתקופה\" אבל אינם קודמים לדף הפירוט הראשון באף קובץ "
                     "(הפירוט שלהם צריך להיות בקבצים, או שהם לא ברורים):" % len(bad))
        for r in bad[:MAX_LISTED]:
            lines.append("    - %s | %s | %s" % (r["date"].isoformat(), r["description"], money2(r["amount"])))
    return lines, not bad


def card_check(s, totals):
    """התאמת חיובי הכרטיס לפירוט ← (שורות להדפסה, האם תקין). totals=None: לא נבדק (בלי כשל)."""
    rows = card_charge_rows(s)
    oop_lines, oop_ok = out_of_period_check(s, totals)
    if not rows:
        if totals is None:
            return (([""] + oop_lines) if oop_lines else []), True
        return ["", "  התאמת חיובי כרטיס אשראי לפירוט: אין בחלון חיובים שסווגו כמפורטים, ולכן אין מה להתאים"] + oop_lines, oop_ok
    if totals is None:
        return ["", "  " + CARD_NOT_CHECKED_LINE] + oop_lines, True
    matched, unmatched = match_card_charges(rows, totals)
    lines = ["", "  התאמת חיובי כרטיס אשראי לפירוט הכרטיס (%d חיובים שסווגו כמפורטים, %d סכומי חיוב בקבצים):" % (len(rows), len(totals))]
    for i, r in enumerate(rows):
        if i in matched:
            when, total = totals[matched[i]]
            lines.append("    %s | %s | %s | תואם לחיוב בפירוט מ-%s" % (r["date"].isoformat(), r["description"], money2(r["amount"]), when.isoformat()))
    if unmatched:
        lines.append("  אי-התאמה - %d חיובים שסווגו כמפורטים ואין להם סכום חיוב תואם בפירוט (תאריך חיוב שווה או עד %d ימים לפני, "
                     "וסכום זהה עד האגורה):" % (len(unmatched), CARD_MATCH_DAYS))
        for i in unmatched[:MAX_LISTED]:
            r = rows[i]
            lines.append("    - %s | %s | %s" % (r["date"].isoformat(), r["description"], money2(r["amount"])))
        if len(unmatched) > MAX_LISTED:
            lines.append("    ... ועוד %d" % (len(unmatched) - MAX_LISTED))
    return lines + oop_lines, (not unmatched) and oop_ok


# ---------------------------------------------------------------- חישוב

class Summary(object):
    pass


def compute(rows, cats, resolver, n_months, include_months=(), from_month=None, to_month=None, exclude_months=(), accounts=None):
    s = Summary()
    s.cats = cats
    s.world = single_world(rows)

    unknown = Counter()
    ambiguous = {}
    for r in rows:
        try:
            r["idx"] = resolver.resolve(r["category"]) if r["category"].strip() else None
            if r["idx"] is None:
                unknown["(ריק)"] += 1
        except Unknown:
            unknown[_norm(r["category"])] += 1
        except Ambiguous as e:
            ambiguous[e.name] = e.options
    if unknown or ambiguous:
        lines = []
        for name, n in unknown.most_common(20):
            lines.append("  %s (%d תנועות)" % (name, n))
        msg = ""
        if unknown:
            msg += "קטגוריות לא מוכרות (%d ערכים, %d תנועות); חייבות להיות שם פריט מ-categories.json או '%s':\n%s" % (
                len(unknown), sum(unknown.values()), UNCLEAR, "\n".join(lines))
        for name, opts in ambiguous.items():
            msg += "\nהשם %r חוזר בתבנית. יש לכתוב צורה מלאה: %s" % (name, " או ".join(opts))
        raise ScriptError(msg.strip())

    s.all_files = sorted(set(r["file"] for r in rows))
    s.read_count = len(rows)
    months_present = sorted(set(month_key(r["date"]) for r in rows))
    n_months = n_months or DEFAULT_MONTHS
    if from_month or to_month:
        # תקופה מפורשת (כולל שני הקצוות); גוברת על --months. קצה שלא ניתן נגזר מהנתונים.
        latest = to_month or months_present[-1]
        start = from_month or max(months_present[0], add_months(latest, -(n_months - 1)))
        if start > latest:
            raise ScriptError("תחילת התקופה (%s) מאוחרת מסופה (%s)" % (start, latest))
    else:
        latest = months_present[-1]
        start = max(months_present[0], add_months(latest, -(n_months - 1)))
    months = []
    m = start
    while m <= latest:
        months.append(m)
        m = add_months(m, 1)
        if len(months) > MAX_PERIOD_MONTHS:
            raise ScriptError("התקופה ארוכה מ-%d חודשים (%s עד %s). בדקו את '--from' ואת '--to'." % (MAX_PERIOD_MONTHS, start, latest))
    s.months = months
    in_window = [r for r in rows if start <= month_key(r["date"]) <= latest]
    s.rows_in_window = in_window
    s.outside = len(rows) - len(in_window)
    s.months_ignored = False
    s.in_window = len(in_window)

    # צד הקלט: מחושב ישירות מהשורות, לפני כל סיווג
    s.input_sum = defaultdict(Decimal)
    s.input_cnt = defaultdict(int)
    for r in in_window:
        k = (r["file"], month_key(r["date"]))
        s.input_sum[k] += r["amount"]
        s.input_cnt[k] += 1

    # צד הפלט: הצבירה לפי קובץ, חודש ופריט
    s.cell = defaultdict(Decimal)         # (file, month, idx) -> סכום גולמי (הוצאה שלילית)
    s.out_cnt = defaultdict(int)
    s.unclear_rows = []
    s.unclear_raw = defaultdict(Decimal)  # (file, month) -> סכום
    for r in in_window:
        mk = month_key(r["date"])
        if r["idx"] == UNCLEAR_IDX:
            s.unclear_rows.append(r)
            s.unclear_raw[(r["file"], mk)] += r["amount"]
        else:
            s.cell[(r["file"], mk, r["idx"])] += r["amount"]
        s.out_cnt[(r["file"], mk)] += 1
    s.classified = sum(1 for r in in_window if r["idx"] != UNCLEAR_IDX)
    s.uncounted_count = sum(1 for r in in_window if r["idx"] != UNCLEAR_IDX and cats[r["idx"]]["section"] == UNCOUNTED)

    # חודש "ייתכן חלקי" לפי הכיסוי של כל חשבון, או של קובץ בלי חשבון (ר' partial_candidates); לא נכנס לממוצע אלא אם אושר בפרמטר include-month
    include = set(include_months)
    exclude = set(exclude_months)
    outside_window = sorted(m for m in include if m not in months)
    if outside_window:
        raise ScriptError("--include-month: החודש %s אינו בתקופה שמוצגת (%s עד %s)" % (", ".join(outside_window), months[0], months[-1]))
    outside_exclude = sorted(m for m in exclude if m not in months)
    if outside_exclude:
        raise ScriptError("--exclude-month: החודש %s אינו בתקופה שמוצגת (%s עד %s)" % (", ".join(outside_exclude), months[0], months[-1]))
    both = sorted(include & exclude)
    if both:
        raise ScriptError("החודש %s ניתן גם ל---include-month וגם ל---exclude-month. יש לבחור אחד." % ", ".join(both))
    # חודש חסר: אין בו אף תנועה מאף קובץ. לא נכנס לממוצע (לא נספר כאפס), ואי אפשר להכניס אותו בכוח.
    present = set(months_present)
    s.missing = [mk for mk in months if mk not in present]
    forced_missing = sorted(m for m in include if m in s.missing)
    if forced_missing:
        raise ScriptError(
            "--include-month: החודש %s חסר (אין בו אף תנועה באף קובץ), ואי אפשר להכניס אותו לממוצע. "
            "יש להשלים את הקובץ החסר ולהפיק את הקבצים מחדש." % ", ".join(forced_missing))
    s.excluded = [mk for mk in months if mk in exclude]
    s.exclude_redundant = [mk for mk in s.excluded if mk in s.missing]
    candidates = partial_candidates(rows, accounts, months)
    # A month with no transactions at all is "חסר", not "ייתכן חלקי": --include-month cannot bring it in,
    # so offering it would ask the user a question whose answer fails.
    s.partial = {mk: candidates[mk] for mk in months if mk in candidates and mk not in s.missing}
    s.included_partial = [mk for mk in months if mk in s.partial and mk in include]
    s.include_not_needed = [mk for mk in months if mk in include and mk not in s.partial]
    s.full_months = [mk for mk in months
                     if mk not in s.missing and mk not in exclude and (mk not in s.partial or mk in include)]

    # הערכים המוצגים: הכנסות ו"לא נספר" כפי שהם, הוצאות כמספר חיובי
    s.item_month = {}
    for idx, c in enumerate(cats):
        for mk in months:
            raw = sum((v for (f, m2, i2), v in s.cell.items() if i2 == idx and m2 == mk), Decimal(0))
            has = any(1 for (f, m2, i2) in s.cell if i2 == idx and m2 == mk)
            if not has:
                s.item_month[(idx, mk)] = None
            else:
                s.item_month[(idx, mk)] = to_display(c["section"], raw)

    def total(section, mk):
        return sum((s.item_month[(i, mk)] or Decimal(0) for i, c in enumerate(cats) if c["section"] == section), Decimal(0))

    s.tot = {}
    for mk in months:
        inc, fx, vr = total(INCOME, mk), total(FIXED, mk), total(VARIABLE, mk)
        s.tot[mk] = {
            T_INCOME: inc, T_FIXED: fx, T_VARIABLE: vr,
            T_EXPENSES: fx + vr, T_BALANCE: inc - fx - vr, T_UNCOUNTED: total(UNCOUNTED, mk),
        }
    s.unclear_total = {mk: sum((v for (f, m2), v in s.unclear_raw.items() if m2 == mk), Decimal(0)) for mk in months}
    return s


def to_display(section, raw):
    """סכום בסימן החשבון (הוצאה שלילית) ← ערך מוצג (הוצאה חיובית; הכנסות ו'לא נספר' כפי שהם)."""
    return -raw if section in EXPENSE_SECTIONS else raw


def to_account(section, shown):
    """ההפך של to_display."""
    return -shown if section in EXPENSE_SECTIONS else shown


def average(s, values_by_month):
    """ממוצע על החודשים המלאים בלבד (ללא חודש "ייתכן חלקי" שלא אושר); None אם אין חודש כזה."""
    if not s.full_months:
        return None
    vals = [values_by_month(mk) for mk in s.full_months]
    return sum((v or Decimal(0) for v in vals), Decimal(0)) / len(s.full_months)


def item_avg(s, idx):
    if all(s.item_month[(idx, mk)] is None for mk in s.months):
        return None
    return average(s, lambda mk: s.item_month[(idx, mk)])


def total_avg(s, name):
    return average(s, lambda mk: s.tot[mk][name])


def integrity(s):
    """מחזיר (שורות לתצוגה, האם הכול תקין)."""
    cats = s.cats
    lines = []
    ok = True
    keys = sorted(set(s.input_sum) | set(s.out_cnt))
    for (f, mk) in keys:
        out = Decimal(0)
        for (f2, m2, idx), raw_sum in s.cell.items():
            if f2 == f and m2 == mk:
                out += to_account(cats[idx]["section"], to_display(cats[idx]["section"], raw_sum))
        out += s.unclear_raw.get((f, mk), Decimal(0))
        in_sum = s.input_sum.get((f, mk), Decimal(0))
        in_cnt = s.input_cnt.get((f, mk), 0)
        out_cnt = s.out_cnt.get((f, mk), 0)
        good = (in_sum == out) and (in_cnt == out_cnt)
        ok = ok and good
        lines.append("  %s | %s | קלט %s (%d תנועות) | פלט %s (%d תנועות) | %s" % (
            f, mk, money2(in_sum), in_cnt, money2(out), out_cnt, "תואם" if good else "אי-התאמה"))
    # בדיקה ברמת החודש מול הסה"כ המוצגים: יתרה + לא נספר + לא ברור = סכום הקלט
    for mk in s.months:
        shown = s.tot[mk][T_BALANCE] + s.tot[mk][T_UNCOUNTED] + s.unclear_total[mk]
        in_sum = sum((v for (f, m2), v in s.input_sum.items() if m2 == mk), Decimal(0))
        good = shown == in_sum
        ok = ok and good
        lines.append("  חודש %s | יתרה + לא נספר + לא ברור %s | סכום הקלט %s | %s" % (
            mk, money2(shown), money2(in_sum), "תואם" if good else "אי-התאמה"))
    return lines, ok


# ---------------------------------------------------------------- תצוגה ופלט

def _n(v):
    return "" if v is None else "{:,}".format(round_int(v))


def _label(s, mk):
    if mk in s.missing:
        return mk + " (חסר)"
    if mk in s.excluded:
        return mk + " (הוצא)"
    if mk in s.partial:
        return mk + (" (ייתכן חלקי - נכלל)" if mk in s.included_partial else " (ייתכן חלקי)")
    return mk


def tot_cell(s, mk, name):
    """סה"כ מוצג של חודש; בחודש חסר ריק (לא אפס)."""
    return None if mk in s.missing else s.tot[mk][name]


def counted_items(s, section):
    return [i for i, c in enumerate(s.cats) if c["section"] == section]


def partial_lines(s):
    """שורות האזהרה על חודשים שייתכן שהם חלקיים - מודפסות בראש הפלט."""
    lines = []
    for mk in s.months:
        if mk in s.missing:
            lines.append("חסר - %s: אין בחודש הזה אף תנועה באף קובץ. לא נכנס לממוצע (לא נספר כאפס). ייתכן שחסר ייצוא של החודש" % mk)
    for mk in s.excluded:
        if mk in s.exclude_redundant:
            lines.append("הערה: --exclude-month %s - החודש חסר ממילא ולא נכנס לממוצע" % mk)
        else:
            lines.append("הוצא - %s: הוצא מהממוצע לבקשת --exclude-month" % mk)
    for mk in s.months:
        if mk not in s.partial:
            continue
        included = mk in s.included_partial
        lines.append("ייתכן חלקי - %s: %s" % (
            mk, "נכלל בממוצע לבקשת --include-month (נדרש אישור של המשתמש שהחודש מלא)" if included else "לא נכנס לממוצע"))
        for name, first, last, reason, by_account in s.partial[mk]:
            if by_account:
                lines.append("  %s: %s" % (name, reason))
            else:
                lines.append("  הקובץ %s, תנועות מ-%s עד %s: %s" % (name, first.isoformat(), last.isoformat(), reason))
        if not included:
            lines.append("  אם המשתמש מאשר שהחודש מלא: --include-month %s" % mk)
    for mk in s.include_not_needed:
        lines.append("הערה: --include-month %s - החודש לא סומן כחלקי, הדגל אינו משנה דבר" % mk)
    if s.months_ignored:
        lines.append("הערה: --months לא נחשב כי ניתנו --from או --to (התקופה המפורשת גוברת)")
    return lines


def print_report(s, checks, ok, desired, manifest_lines, manifest_name, out=sys.stdout, card_lines=()):
    p = lambda text="": print(text, file=out)
    cats = s.cats
    warnings = partial_lines(s)
    for line in warnings:
        p(line)
    if warnings:
        p()
    p("שיקוף - עולם: %s" % s.world)
    p("קבצים: %s" % ", ".join(s.all_files))
    p("תקופה: %s עד %s (%d חודשים; בממוצע: %d)" % (s.months[0], s.months[-1], len(s.months), len(s.full_months)))
    p("סכומים בש\"ח, מעוגלים לשקל. הוצאות מוצגות כמספר חיובי. הממוצע על החודשים המלאים בלבד.")
    if not s.full_months:
        p("אין אף חודש מלא, ולכן אין ממוצע.")
    p()
    head = "פריט | " + " | ".join(_label(s, mk) for mk in s.months) + " | ממוצע" + (" | רצוי | הפרש" if desired is not None else "")
    p(head)

    def desired_for(idx):
        if desired is None or cats[idx]["section"] not in EXPENSE_SECTIONS:
            return None
        if idx in desired:
            return desired[idx]
        return item_avg(s, idx)

    for section, total_name in ((INCOME, T_INCOME), (FIXED, T_FIXED), (VARIABLE, T_VARIABLE)):
        p("[%s]" % section)
        last_group = None
        for idx in counted_items(s, section):
            vals = [s.item_month[(idx, mk)] for mk in s.months]
            if all(v is None for v in vals):
                continue
            if cats[idx]["group"] != last_group:
                last_group = cats[idx]["group"]
                if section != INCOME:
                    p(" %s" % last_group)
            row = "  %s | %s | %s" % (cats[idx]["item"], " | ".join(_n(v) for v in vals), _n(item_avg(s, idx)))
            if desired is not None:
                mark = "" if idx in desired or desired_for(idx) is None else " (ממוצע)"
                row += " | %s%s" % (_n(desired_for(idx)), mark if section in EXPENSE_SECTIONS else "")
                row += " | %s" % _n(diff(item_avg(s, idx), desired_for(idx)))
            p(row)
        row = "%s | %s | %s" % (total_name, " | ".join(_n(tot_cell(s, mk, total_name)) for mk in s.months), _n(total_avg(s, total_name)))
        if desired is not None and section in EXPENSE_SECTIONS:
            row += " | %s | %s" % (_n(desired_total(s, desired, section)),
                                   _n(diff(total_avg(s, total_name), desired_total(s, desired, section))))
        p(row)
        p()
    row = "%s | %s | %s" % (T_EXPENSES, " | ".join(_n(tot_cell(s, mk, T_EXPENSES)) for mk in s.months), _n(total_avg(s, T_EXPENSES)))
    if desired is not None:
        row += " | %s | %s" % (_n(desired_total(s, desired, None)), _n(freed(s, desired)))
    p(row)
    row = "%s | %s | %s" % (T_BALANCE, " | ".join(_n(tot_cell(s, mk, T_BALANCE)) for mk in s.months), _n(total_avg(s, T_BALANCE)))
    if desired is not None:
        row += " | %s" % _n(desired_balance(s, desired))
    p(row)
    if desired is not None:
        p("%s: %s (ממוצע ההכנסות פחות סה\"כ הרצוי; פריט בלי ערך רצוי לוקח את הממוצע שלו)" % (T_DESIRED_BAL, _n(desired_balance(s, desired))))
        p("%s: %s (סה\"כ הוצאות בפועל, ממוצע, פחות סה\"כ הרצוי; הפרש לפריט = ממוצע פחות רצוי)" % (T_FREED, _n(freed(s, desired))))
    p()
    p("[%s] - נספרו בשלמות אבל לא נכנסו לסה\"כ הכנסות, הוצאות ויתרה ולא לממוצע (שלילי = יצא מהחשבון)" % UNCOUNTED)
    for idx in counted_items(s, UNCOUNTED):
        vals = [s.item_month[(idx, mk)] for mk in s.months]
        if all(v is None for v in vals):
            continue
        p("  %s | %s" % (cats[idx]["item"], " | ".join(_n(v) for v in vals)))
    p("%s | %s" % (T_UNCOUNTED, " | ".join(_n(tot_cell(s, mk, T_UNCOUNTED)) for mk in s.months)))
    p()
    p("[%s] - %d תנועות, לא נכנסו לחישוב ולא ליתרה" % (UNCLEAR, len(s.unclear_rows)))
    for r in sorted(s.unclear_rows, key=lambda r: (r["date"], r["description"])):
        p("  %s | %s | %s | %s" % (r["date"].isoformat(), r["description"], money2(r["amount"]), r["file"]))
    p()
    p("בדיקות שלמות והתאמה")
    p("  התאמה מול המניפסט (%s) - כל הקובץ, לא רק חלון התקופה:" % manifest_name)
    for line in manifest_lines:
        p(line)
    p("  תנועות שנקראו: %d" % s.read_count)
    p("  מחוץ לחלון התקופה: %d" % s.outside)
    p("  בחלון: %d | מוינו: %d (מהן %s: %d) | %s: %d" % (
        s.in_window, s.classified, UNCOUNTED, s.uncounted_count, UNCLEAR, len(s.unclear_rows)))
    p("  התאמת סכומי הקלט לסכומי הפלט (חלון התקופה), לפי קובץ וחודש:")
    for line in checks:
        p(line)
    for line in card_lines:
        p(line)
    p("  תוצאה: %s" % ("הכול תואם" if ok else "אי-התאמה - הפלט אינו אמין"))


def desired_total(s, desired, section):
    sections = EXPENSE_SECTIONS if section is None else (section,)
    total = Decimal(0)
    for idx, c in enumerate(s.cats):
        if c["section"] not in sections:
            continue
        if idx in desired:
            total += desired[idx]
        else:
            a = item_avg(s, idx)
            total += a or Decimal(0)
    return total


def diff(avg, des):
    """ממוצע פחות רצוי; None כשאחד מהם חסר."""
    if avg is None or des is None:
        return None
    return avg - des


def freed(s, desired):
    """התפנה: סה"כ הוצאות בפועל (ממוצע) פחות סה"כ רצוי."""
    return diff(total_avg(s, T_EXPENSES), desired_total(s, desired, None))


def desired_balance(s, desired):
    inc = total_avg(s, T_INCOME)
    if inc is None:
        return None
    return inc - desired_total(s, desired, None)


def csv_text(s, desired):
    cats = s.cats
    f = io.StringIO()
    w = csv.writer(f, lineterminator="\n")
    header = ["section", "group", "item"] + [_label(s, mk) for mk in s.months] + ["average"]
    if desired is not None:
        header += ["desired", "difference"]
    w.writerow(header)

    def m2(v):
        return "" if v is None else money2(v)

    def put(section, group, item, vals, avg, des=None, dif=None):
        row = [section, group, item] + [m2(v) for v in vals] + [m2(avg)]
        if desired is not None:
            row += [m2(des), m2(dif)]
        w.writerow(row)

    for section, total_name in ((INCOME, T_INCOME), (FIXED, T_FIXED), (VARIABLE, T_VARIABLE)):
        for idx in counted_items(s, section):
            vals = [s.item_month[(idx, mk)] for mk in s.months]
            des = None
            if desired is not None and section in EXPENSE_SECTIONS:
                des = desired.get(idx, item_avg(s, idx))
            put(section, cats[idx]["group"], cats[idx]["item"], vals, item_avg(s, idx), des, diff(item_avg(s, idx), des))
        des = desired_total(s, desired, section) if desired is not None and section in EXPENSE_SECTIONS else None
        put(section, "", total_name, [tot_cell(s, mk, total_name) for mk in s.months], total_avg(s, total_name), des,
            diff(total_avg(s, total_name), des))
    des_all = desired_total(s, desired, None) if desired is not None else None
    put("סיכום", "", T_EXPENSES, [tot_cell(s, mk, T_EXPENSES) for mk in s.months], total_avg(s, T_EXPENSES),
        des_all, diff(total_avg(s, T_EXPENSES), des_all))
    put("סיכום", "", T_BALANCE, [tot_cell(s, mk, T_BALANCE) for mk in s.months], total_avg(s, T_BALANCE),
        desired_balance(s, desired) if desired is not None else None)
    if desired is not None:
        put("סיכום", "", T_DESIRED_BAL, [None for _ in s.months], None, desired_balance(s, desired))
        put("סיכום", "", T_FREED, [None for _ in s.months], None, None, freed(s, desired))
    for idx in counted_items(s, UNCOUNTED):
        vals = [s.item_month[(idx, mk)] for mk in s.months]
        put(UNCOUNTED, cats[idx]["group"], cats[idx]["item"], vals, None)   # כמו על המסך: ל"לא נספר" אין ממוצע
    put(UNCOUNTED, "", T_UNCOUNTED, [tot_cell(s, mk, T_UNCOUNTED) for mk in s.months], None)
    w.writerow([])
    w.writerow([UNCLEAR])
    w.writerow(["date", "description", "amount"])
    for r in sorted(s.unclear_rows, key=lambda r: (r["date"], r["description"])):
        w.writerow([r["date"].isoformat(), r["description"], money2(r["amount"])])
    return f.getvalue()


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(
        description="מסכם תנועות ממוינות לשיקוף חודשי לפי רשימת הקטגוריות של שרי (categories.json). "
        "הקלט: הפלט של prepare_sorting.py (עמודות row_id ו-category) לצד המניפסט שלו; שרי ממלאת רק את category "
        "(שם פריט מ-categories.json, או 'לא ברור'). הסקריפט משווה את הקובץ למניפסט: אותה קבוצת row_id, ולכל קובץ וחודש אותו "
        "מספר תנועות ואותו סכום. חודש שייתכן שהוא חלקי (ייצוא שנחתך באמצע חודש) מסומן ולא נכנס לממוצע. "
        "קטגוריות בסעיף 'לא נספר' נספרות בשלמות ובהתאמת הסכומים, אבל לא נכנסות לסה\"כ ולממוצע. "
        "פריט ששמו חוזר ברשימת הקטגוריות נכתב בצורה מלאה: סעיף/קבוצה/פריט.",
    )
    p.add_argument("file", help="קובץ csv ממוין (הפלט של prepare_sorting.py, עם עמודת category שמולאה)")
    p.add_argument("--manifest", help="נתיב המניפסט (ברירת מחדל: <קלט>.manifest.json לצד הקובץ). בלי מניפסט - נכשל")
    p.add_argument("--include-month", action="append", default=[], metavar="YYYY-MM",
                   help="מכניס לממוצע חודש שסומן 'ייתכן חלקי', אחרי שהמשתמש אישר שהוא מלא (אפשר כמה)")
    p.add_argument("--exclude-month", action="append", default=[], metavar="YYYY-MM",
                   help="מוציא חודש מהממוצע (אפשר כמה). החודש נשאר בטבלה עם הסימון (הוצא) ובאזהרה")
    p.add_argument("--from", dest="from_month", metavar="YYYY-MM",
                   help="תחילת התקופה (כולל). גובר על --months. בלי --to: עד החודש האחרון בנתונים")
    p.add_argument("--to", dest="to_month", metavar="YYYY-MM",
                   help="סוף התקופה (כולל). גובר על --months. חודש בתקופה שאין בו אף תנועה מסומן (חסר) ולא נכנס לממוצע")
    p.add_argument("--months", type=int, default=None,
                   help="מספר החודשים האחרונים (ברירת מחדל 3). נשאר לתאימות; כש-'--from' או '--to' ניתנים הם גוברים")
    p.add_argument("--out", help="נתיב לקובץ שיקוף csv (בסדר השורות של categories.json). קובץ קיים לא נדרס בלי --overwrite")
    p.add_argument("--overwrite", action="store_true",
                   help="מאפשר --out לקובץ קיים: הקיים מועבר לשם <שם>.קודם-<YYYYMMDD-HHMMSS><סיומת> באותה תיקייה ולא נמחק")
    p.add_argument("--desired", help="קובץ csv של תקציב רצוי (עמודות: item,desired - סכום חודשי חיובי)")
    p.add_argument("--card-totals", dest="card_totals", nargs="+", metavar="CSV",
                   help="קובצי billing_date,total (הפלט של read_bank_file.py --billing-totals --totals-out), אחד לכל כרטיס. "
                   "כל שורה שסווגה 'חיוב כרטיס אשראי (מפורט בקובץ האשראי)' חייבת להתאים לסכום חיוב אחד: תאריך חיוב שווה לתאריך "
                   "השורה או עד 3 ימים לפניו, וסכום שווה עד האגורה; כל סכום מתאים לשורה אחת לכל היותר. שורה בלי התאמה ← "
                   "אי-התאמה, קוד יציאה 1 ולא נכתב קובץ פלט. בלי הדגל, כשיש חיובים כאלה, מודפסת שורה שאומרת שההתאמה לא נבדקה")
    a = p.parse_args()
    if a.months is not None and a.months < 1:
        raise ScriptError("--months חייב להיות 1 ומעלה")
    if not os.path.isfile(a.file):
        raise ScriptError("הקובץ לא נמצא: %s" % a.file)
    if a.desired and not os.path.isfile(a.desired):
        raise ScriptError("קובץ הרצוי לא נמצא: %s" % a.desired)
    totals = read_card_totals(a.card_totals) if a.card_totals else None
    for flag, values in (("--include-month", a.include_month), ("--exclude-month", a.exclude_month),
                         ("--from", [a.from_month] if a.from_month else []), ("--to", [a.to_month] if a.to_month else [])):
        for m in values:
            if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", m):
                raise ScriptError("%s חייב להיות בצורה YYYY-MM, התקבל: %r" % (flag, m))
    if a.out:
        for other in [a.file, a.desired, a.manifest or manifest_path_for(a.file)] + list(a.card_totals or []):
            if other and os.path.realpath(other) == os.path.realpath(a.out):
                raise ScriptError("--out זהה לקובץ קלט (%s). יש לבחור נתיב אחר." % other)
        require_free_output(a.out, a.overwrite)

    manifest_path = a.manifest or manifest_path_for(a.file)
    manifest = load_manifest(manifest_path)
    cats = load_categories()
    resolver = Resolver(cats)
    desired = read_desired(a.desired, resolver) if a.desired else None
    rows = read_transactions(a.file, allow_empty=True)
    single_world(rows)
    manifest_lines, manifest_ok = reconcile(rows, manifest)
    if not manifest_ok:
        print("התאמה מול המניפסט (%s) - נכשלה" % os.path.basename(manifest_path))
        for line in manifest_lines:
            print(line)
        print("שגיאה: הקובץ הממוין אינו תואם למניפסט שנכתב ב-prepare_sorting.py "
              "(תנועה חסרה, מיותרת, כפולה או ששונתה, או סכום שונה). שרי משנה רק את עמודת category. "
              "לא הופק שיקוף ולא נכתב קובץ פלט.", file=sys.stderr)
        return 1
    accounts = {f: info["account"] for f, info in manifest["files"].items() if info.get("account")}
    s = compute(rows, cats, resolver, a.months, a.include_month, a.from_month, a.to_month, a.exclude_month, accounts)
    s.months_ignored = a.months is not None and bool(a.from_month or a.to_month)
    checks, integrity_ok = integrity(s)
    card_lines, card_ok = card_check(s, totals)
    ok = integrity_ok and card_ok
    print_report(s, checks, ok, desired, manifest_lines, os.path.basename(manifest_path), card_lines=card_lines)
    if not integrity_ok:
        print("שגיאה: יש אי-התאמה בין סכומי הקלט לסכומי הפלט (ר' הבדיקות למעלה). לא נכתב קובץ פלט.", file=sys.stderr)
        return 1
    if not card_ok:
        print("שגיאה: יש חיוב כרטיס אשראי שהסיווג שלו לא תואם לפירוט הכרטיס (ר' אי-התאמה למעלה). "
              "לא נכתב קובץ פלט. אפשר שחסר דף פירוט של הכרטיס (ואז החיוב לא ברור עד שהמשתמש מביא אותו), או שהחיוב סווג "
              "כמחוץ לתקופה אף שהוא בתוך התקופה.", file=sys.stderr)
        return 1
    if a.out:
        moved = commit_outputs(a.out, csv_text(s, desired), (), a.overwrite)
        for old, new in moved:
            print("הקובץ הקיים הועבר (לא נמחק): %s" % new, file=sys.stderr)
        print("נכתב: %s" % a.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    run_main(main)
