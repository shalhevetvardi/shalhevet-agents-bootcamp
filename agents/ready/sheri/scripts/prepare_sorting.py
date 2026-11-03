"""קובצי עבודה (הפלט של read_bank_file.py) ← קובץ אחד למיון + מניפסט.

שימוש:  python3 -I prepare_sorting.py <קובץ-עבודה.csv> [<עוד>...] --out <ממוין.csv>

מאחד את הקבצים, מוסיף עמודת row_id (מזהה יציב לכל תנועה) ועמודת category ריקה למילוי,
וכותב לצד הפלט מניפסט <ממוין>.manifest.json. summarize.py משווה את הקובץ הממוין למניפסט הזה,
ולכן תנועה שאבדה, כפולה או שונתה בדרך נתפסת.
"""
import csv
import io
import json
import os
import sys
from collections import OrderedDict
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    MANIFEST_SUFFIX, MANIFEST_VERSION, HebrewParser, ScriptError, commit_outputs, manifest_path_for, money2, month_key,
    parse_amount, parse_iso_date, read_text_any, require_free_output, row_fingerprint, run_main,
)

WORK_COLUMNS = ["date", "description", "amount", "source_file", "world"]
OUT_COLUMNS = WORK_COLUMNS + ["row_id", "category"]
MAX_LISTED = 20   # כמה כפילויות מפורטות מודפסות


def read_work_file(path):
    """קובץ עבודה ← רשימת תנועות (לפי סדר השורות)."""
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    if "row_id" in cols or "category" in cols:
        raise ScriptError(
            "%s כבר נראה כקובץ ממוין (יש בו עמודת row_id או category). "
            "prepare_sorting.py מקבל רק את הפלט של read_bank_file.py." % path
        )
    missing = [c for c in WORK_COLUMNS if c not in cols]
    if missing:
        raise ScriptError(
            "בקובץ %s חסרות עמודות: %s. העמודות הנדרשות: %s (הפלט של read_bank_file.py)."
            % (path, ", ".join(missing), ",".join(WORK_COLUMNS))
        )
    rows = []
    accounts = set()   # עמודת account אופציונלית: ערך אחד בכל שורות הקובץ
    for row in reader:
        if not any((v or "").strip() for v in row.values() if not isinstance(v, list)):
            continue
        n = reader.line_num
        d = parse_iso_date(row["date"], "תאריך בשורה %d ב-%s" % (n, os.path.basename(path)))
        try:
            amount = parse_amount(row["amount"])
        except ValueError:
            raise ScriptError("%s, שורה %d: סכום לא מזוהה (%r)" % (path, n, row["amount"]))
        if amount is None:
            raise ScriptError("%s, שורה %d: סכום ריק" % (path, n))
        source = (row["source_file"] or "").strip()
        world = (row["world"] or "").strip()
        if not source or not world:
            raise ScriptError("%s, שורה %d: חסר source_file או world" % (path, n))
        account = ((row.get("account") or "").strip() if "account" in cols else "")
        accounts.add(account)
        rows.append({"date": d, "description": row["description"] or "", "amount": amount,
                     "source_file": source, "world": world, "account": account})
    if not rows:
        raise ScriptError("אין תנועות בקובץ %s" % path)
    if len(accounts) > 1:
        shown = ", ".join(repr(a) if a else "(ריק)" for a in sorted(accounts)[:5])
        raise ScriptError(
            "בקובץ %s עמודת account אינה אחידה: כל שורות הקובץ חייבות לשאת אותו חשבון (נמצאו: %s)." % (path, shown))
    return rows


def build(paths):
    """מחזיר (שורות עם row_id, מניפסט כ-dict)."""
    out_rows = []
    seen_paths = set()
    for path in paths:
        real = os.path.realpath(path)
        if real in seen_paths:
            raise ScriptError("אותו קובץ עבודה הוזן פעמיים (%s). כפילות כזו הייתה מכפילה את כל התנועות שלו." % path)
        seen_paths.add(real)
    owner = {}        # source_file -> הנתיב שממנו הגיע
    file_account = {}  # source_file -> החשבון (מעמודת account; ריק כשאין)
    counters = {}     # source_file -> מספר התנועות עד כה
    worlds = OrderedDict()
    for path in paths:
        for r in read_work_file(path):
            f = r["source_file"]
            if f in owner and owner[f] != path:
                raise ScriptError(
                    "אותו source_file (%s) מופיע בשני קובצי עבודה (%s ו-%s). "
                    "זה אותו קובץ שהוזן פעמיים, או שני קבצים בעלי שם זהה - ואז יש לשנות לאחד מהם שם לפני read_bank_file."
                    % (f, owner[f], path)
                )
            owner[f] = path
            file_account[f] = r["account"]
            worlds.setdefault(r["world"], []).append(os.path.basename(path))
            counters[f] = counters.get(f, 0) + 1
            r["row_id"] = "%s#%d" % (f, counters[f])
            out_rows.append(r)
    if len(worlds) > 1:
        desc = "; ".join("%r: %s" % (w, ", ".join(sorted(set(fs)))) for w, fs in worlds.items())
        raise ScriptError(
            "ערבוב עולמות בין הקבצים (%s). כל קובץ שיקוף הוא עולם אחד - פרטי או עסק; יש להכין כל עולם בנפרד." % desc
        )
    world = list(worlds)[0]

    files = OrderedDict()
    for r in out_rows:
        f = r["source_file"]
        info = files.setdefault(f, {"count": 0, "_sum": Decimal(0), "first_date": None, "last_date": None,
                                    "_months": OrderedDict(), "row_ids": [], "rows": OrderedDict()})
        amount_text = money2(r["amount"])
        info["count"] += 1
        info["_sum"] += r["amount"]
        if info["first_date"] is None or r["date"] < info["first_date"]:
            info["first_date"] = r["date"]
        if info["last_date"] is None or r["date"] > info["last_date"]:
            info["last_date"] = r["date"]
        m = info["_months"].setdefault(month_key(r["date"]), {"count": 0, "_sum": Decimal(0)})
        m["count"] += 1
        m["_sum"] += r["amount"]
        info["row_ids"].append(r["row_id"])
        info["rows"][r["row_id"]] = {
            "date": r["date"].isoformat(), "amount": amount_text,
            "fp": row_fingerprint(r["date"].isoformat(), r["description"], amount_text, f, world),
        }
    manifest_files = OrderedDict()
    for f, info in files.items():
        entry = OrderedDict([
            ("count", info["count"]),
            ("sum", money2(info["_sum"])),
            ("first_date", info["first_date"].isoformat()),
            ("last_date", info["last_date"].isoformat()),
        ])
        if file_account.get(f):   # רק קובץ עם חשבון מוצהר; summarize.py מקבץ לפיו לבדיקת חודש חלקי
            entry["account"] = file_account[f]
        entry["months"] = OrderedDict((mk, {"count": v["count"], "sum": money2(v["_sum"])})
                                      for mk, v in sorted(info["_months"].items()))
        entry["row_ids"] = info["row_ids"]
        entry["rows"] = info["rows"]
        manifest_files[f] = entry
    manifest = OrderedDict([
        ("version", MANIFEST_VERSION),
        ("world", world),
        ("total_count", len(out_rows)),
        ("total_sum", money2(sum((r["amount"] for r in out_rows), Decimal(0)))),
        ("files", manifest_files),
    ])
    return out_rows, manifest


def find_duplicates(rows):
    """שורות עם אותו תאריך, תיאור (רווחים מנורמלים) וסכום שמופיעות ביותר מקובץ מקור אחד, באותו חשבון.

    כפילות בתוך קובץ אחד אינה נספרת: שתי קניות זהות באותו יום בקובץ אחד הן בדרך כלל אמיתיות.
    החשבון (עמודת account): אותה קנייה בשני חשבונות שונים (שני כרטיסים) היא שתי קניות, ואינה כפילות. שורה בלי חשבון
    כן מושווית לכל חשבון: ייצוא של כרטיס דרך read_bank_file (בלי חשבון) לצד הדפים של אותו כרטיס הוא אותה קנייה פעמיים.
    מחזיר רשימת (מפתח, [שורות]) בסדר הופעה."""
    groups = OrderedDict()
    for r in rows:
        key = (r["date"].isoformat(), " ".join((r["description"] or "").split()), money2(r["amount"]))
        groups.setdefault(key, []).append(r)
    def same_purchase(a, b):
        return a["source_file"] != b["source_file"] and (
            not a.get("account") or not b.get("account") or a.get("account") == b.get("account"))

    out = []
    for k, v in groups.items():
        # Only rows that take part in a duplicate pair: two different cards in the group are not each other's
        # duplicate, and listing them together would say they are.
        involved = [a for i, a in enumerate(v) if any(same_purchase(a, b) for j, b in enumerate(v) if j != i)]
        if involved:
            out.append((k, involved))
    return out


def duplicates_message(dups):
    lines = ["אותה תנועה (תאריך, תיאור וסכום, ולא בשני כרטיסים שונים) מופיעה ביותר מקובץ מקור אחד: %d תנועות. זה בדרך כלל אותו ייצוא שהוזן פעמיים "
             "(למשל שני קבצים בעלי טווחי תאריכים חופפים), וסכומי השיקוף היו מנופחים." % len(dups)]
    for (d, desc, amount), group in dups[:MAX_LISTED]:
        lines.append("  %s | %s | %s | %s" % (d, desc, amount, ", ".join(r["row_id"] for r in group)))
    if len(dups) > MAX_LISTED:
        lines.append("  ... ועוד %d" % (len(dups) - MAX_LISTED))
    lines.append("יש להסיר את החפיפה מהקבצים ולהריץ מחדש. רק אם המשתמש אישר ששתי הקניות אמיתיות: --allow-duplicates.")
    return "\n".join(lines)


def read_old_categories(path):
    """קובץ ממוין ישן ← {טביעת אצבע: [קטגוריות לפי סדר ההופעה]}, וכמה שורות מולאה בהן קטגוריה.

    שורה בלי קטגוריה נשארת ברשימה (ריקה), כדי ששתי קניות זהות יותאמו לפי המקום שלהן ולא לפי מי שמולאה."""
    if not os.path.isfile(path):
        raise ScriptError("הקובץ הממוין הישן לא נמצא: %s" % path)
    text, _ = read_text_any(path)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    cols = reader.fieldnames or []
    missing = [c for c in WORK_COLUMNS + ["category"] if c not in cols]
    if missing:
        raise ScriptError("בקובץ הממוין הישן %s חסרות עמודות: %s" % (path, ", ".join(missing)))
    out = {}
    total = 0
    for row in reader:
        cat = (row["category"] or "").strip()
        n = reader.line_num
        d = parse_iso_date(row["date"], "תאריך בשורה %d בקובץ הישן" % n)
        try:
            amount = parse_amount(row["amount"])
        except ValueError:
            raise ScriptError("%s, שורה %d: סכום לא מזוהה" % (path, n))
        if amount is None:
            raise ScriptError("%s, שורה %d: סכום ריק" % (path, n))
        fp = row_fingerprint(d.isoformat(), row["description"] or "", money2(amount),
                             (row["source_file"] or "").strip(), (row["world"] or "").strip())
        out.setdefault(fp, []).append(cat)
        total += 1 if cat else 0
    return out, total


def apply_old_categories(rows, old):
    """ממלא category בשורות החדשות לפי טביעת האצבע. שורות עם אותה טביעה מותאמות לפי סדר ההופעה.

    מחזיר (כמה הועתקו, כמה מהן 'לא ברור')."""
    queues = {fp: list(cats) for fp, cats in old.items()}
    copied = unclear = 0
    for r in rows:
        fp = row_fingerprint(r["date"].isoformat(), r["description"], money2(r["amount"]), r["source_file"], r["world"])
        q = queues.get(fp)
        if q:
            r["category"] = q.pop(0)
            if r["category"]:
                copied += 1
            if r["category"] == "לא ברור":
                unclear += 1
    return copied, unclear


def main():
    p = HebrewParser(
        description="מאחד קובצי עבודה (הפלט של read_bank_file.py) לקובץ אחד למיון: מוסיף עמודת row_id (מזהה יציב לכל תנועה, "
        "בצורה <שם-קובץ>#<מספר-תנועה>) ועמודת category ריקה, וכותב לצד הפלט מניפסט <ממוין>.manifest.json. "
        "שרי ממלאת רק את עמודת category; summarize.py משווה את הקובץ הממוין למניפסט.",
    )
    p.add_argument("files", nargs="+", metavar="קובץ-עבודה",
                   help="קובץ csv שהופק על ידי read_bank_file.py (אפשר כמה). עמודת account אופציונלית (למשל 'כאל 1234') "
                   "חייבת להיות זהה בכל שורות הקובץ, והיא נרשמת במניפסט")
    p.add_argument("--out", required=True, help="נתיב הקובץ הממוין (csv). המניפסט נכתב ל-<נתיב>.manifest.json. "
                   "קובץ קיים לא נדרס בלי --overwrite")
    p.add_argument("--overwrite", action="store_true",
                   help="מאפשר --out לקובץ קיים: הקובץ והמניפסט הקיימים מועברים לשם <שם>.קודם-<YYYYMMDD-HHMMSS><סיומת> "
                   "באותה תיקייה ולא נמחקים")
    p.add_argument("--allow-duplicates", action="store_true",
                   help="לא נכשל כשאותה תנועה (תאריך, תיאור, סכום) מופיעה ביותר מקובץ אחד. רק אחרי שהמשתמש אישר ששתי הקניות אמיתיות")
    p.add_argument("--keep-categories-from", metavar="ממוין-ישן.csv",
                   help="מעתיק את עמודת category מקובץ ממוין ישן לשורות החדשות לפי טביעת האצבע של השורה "
                   "(מקור, תאריך, תיאור, סכום). מדפיס כמה הועתקו וכמה נשארו ריקות")
    a = p.parse_args()

    for path in a.files:
        if not os.path.isfile(path):
            raise ScriptError("הקובץ לא נמצא: %s" % path)
    out_real = os.path.realpath(a.out)
    for path in a.files:
        if os.path.realpath(path) in (out_real, os.path.realpath(manifest_path_for(a.out))):
            raise ScriptError("קובץ הפלט זהה לקובץ קלט (%s). יש לבחור נתיב אחר בפרמטר --out." % path)

    require_free_output(a.out, a.overwrite, [MANIFEST_SUFFIX])
    rows, manifest = build(a.files)
    dups = find_duplicates(rows)
    if dups and not a.allow_duplicates:
        raise ScriptError(duplicates_message(dups))
    kept = None
    for r in rows:
        r["category"] = ""
    if a.keep_categories_from:
        old, old_total = read_old_categories(a.keep_categories_from)
        kept = (apply_old_categories(rows, old), old_total)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(OUT_COLUMNS)
    for r in rows:
        w.writerow([r["date"].isoformat(), r["description"], money2(r["amount"]), r["source_file"], r["world"], r["row_id"], r["category"]])
    manifest_path = manifest_path_for(a.out)
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"
    moved = commit_outputs(a.out, buf.getvalue(), [(MANIFEST_SUFFIX, manifest_text)], a.overwrite)

    err = sys.stderr
    print("עולם: %s" % manifest["world"], file=err)
    for f, info in manifest["files"].items():
        print("קובץ: %s | %d תנועות | סכום %s | תאריכים %s עד %s" % (
            f, info["count"], info["sum"], info["first_date"], info["last_date"]), file=err)
    print("סה\"כ: %d תנועות | סכום %s" % (manifest["total_count"], manifest["total_sum"]), file=err)
    if dups:
        print("אזהרה: %d תנועות כפולות בין קבצים אושרו ב---allow-duplicates" % len(dups), file=err)
    for old_path, new_path in moved:
        print("הקובץ הקיים הועבר (לא נמחק): %s" % new_path, file=err)
    if kept is not None:
        (copied, unclear), old_total = kept
        empty = sum(1 for r in rows if not r["category"])
        print("קטגוריות שהועתקו מהקובץ הישן: %d (מהן 'לא ברור': %d) | שורות חדשות שנשארו ריקות: %d | "
              "שורות ישנות עם קטגוריה שלא נמצאה להן תנועה זהה: %d" % (copied, unclear, empty, old_total - copied), file=err)
    print("נכתב: %s (%s)" % (a.out, "עמודת category ריקה, למילוי" if kept is None else "עמודת category מולאה בחלקה מהקובץ הישן"), file=err)
    print("נכתב: %s" % manifest_path, file=err)
    return 0


if __name__ == "__main__":
    run_main(main)
