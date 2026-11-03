"""תיקיית הנתונים של שרי: איפה היא, יצירה ראשונה שלה, והצבעה על תיקייה קיימת.

שימוש:
    python3 -I data_folder.py where
    python3 -I data_folder.py init <נתיב> [--business]
    python3 -I data_folder.py set <נתיב>

המצביע: הקובץ data-folder.txt בתוך תיקיית הבית של שרי (ברירת מחדל ~/.sheri, ומשתנה הסביבה SHERI_HOME משנה אותה).
הוא שומר נתיב אחד בלבד, בלי שום נתון כספי.

where  - מדפיס ל-stdout את הנתיב המוחלט של תיקיית הנתונים.
         קוד יציאה: 0 הצלחה · 3 עוד לא הוגדרה תיקייה · 4 המצביע קיים אבל התיקייה לא נמצאת.
init   - יוצר את עץ התיקיות (תיקיות בלבד, אף קובץ נתונים) וכותב את המצביע. עסק/ נוצרת רק עם --business.
         בטוח להרצה חוזרת: לא דורס ולא מוחק דבר, ומדפיס מה נוצר ומה כבר היה.
set    - מצביע על תיקייה שכבר קיימת (למשל במחשב חדש). נכשל אם התיקייה לא קיימת.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import HebrewParser, ScriptError, add_subparsers, run_main  # noqa: E402

POINTER_NAME = "data-folder.txt"
DEFAULT_HOME = "~/.sheri"

EXIT_NOT_SET = 3
EXIT_MISSING_FOLDER = 4

# עץ התיקיות, יחסית לתיקיית הנתונים. תיקיות בלבד.
BASE_DIRS = (
    os.path.join("פרטי", "קבצים-מהבנק"),
    os.path.join("פרטי", "עבודה"),
    "יומנים",
)
BUSINESS_DIRS = (
    os.path.join("עסק", "קבצים-מהבנק"),
    os.path.join("עסק", "עבודה"),
)


def sheri_home():
    raw = os.environ.get("SHERI_HOME", "").strip()
    return os.path.abspath(os.path.expanduser(raw or DEFAULT_HOME))


def pointer_path():
    return os.path.join(sheri_home(), POINTER_NAME)


def _clean_path(text):
    text = (text or "").strip()
    if not text:
        raise ScriptError("הנתיב ריק")
    return os.path.abspath(os.path.expanduser(text))


def read_pointer():
    """הנתיב השמור במצביע, או None כשאין מצביע (או שהוא ריק)."""
    path = pointer_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise ScriptError("לא ניתן לקרוא את המצביע %s: %s" % (path, getattr(e, "strerror", None) or e))
    return value or None


def write_pointer(folder):
    home = sheri_home()
    path = pointer_path()
    tmp = "%s.tmp-%d" % (path, os.getpid())
    try:
        os.makedirs(home, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(folder + "\n")
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ScriptError("לא ניתן לכתוב את המצביע %s: %s" % (path, e.strerror or e))
    return path


# ---------------------------------------------------------------- פקודות

def cmd_where(a):
    folder = read_pointer()
    if folder is None:
        print(
            "עוד לא הוגדרה תיקיית נתונים (אין מצביע ב-%s). אם כבר יש תיקייה: data_folder.py set <נתיב>. "
            "אם זו הפעם הראשונה: data_folder.py init <נתיב>." % pointer_path(),
            file=sys.stderr,
        )
        return EXIT_NOT_SET
    if not os.path.isdir(folder):
        print(
            "המצביע מפנה לתיקייה שלא נמצאת: %s. ייתכן שהתיקייה הועברה, נמחקה או שהכונן לא מחובר. "
            "אם היא במקום אחר: data_folder.py set <נתיב חדש>." % folder,
            file=sys.stderr,
        )
        return EXIT_MISSING_FOLDER
    print(for_shell(folder))
    return 0


def for_shell(path, sep=os.sep):
    """The path as the shell commands use it: forward slashes on Windows.

    DATA=$(... where) is joined with "/" in every command ("$DATA"/יומנים/...), and Git Bash and
    Python both accept a drive path with forward slashes (C:/...). A path with backslashes would
    end up half and half.
    """
    return path.replace("\\", "/") if sep == "\\" else path


def cmd_init(a):
    root = _clean_path(a.path)
    wanted = [""] + list(BASE_DIRS) + (list(BUSINESS_DIRS) if a.business else [])
    targets = [os.path.join(root, rel) if rel else root for rel in wanted]
    # בדיקה מוקדמת, לפני שנוצר משהו: אסור שתיקייה מהעץ תהיה קובץ
    for target in targets:
        if os.path.lexists(target) and not os.path.isdir(target):
            raise ScriptError("הנתיב %s קיים וזה לא תיקייה. לא יוצרים בתוכו, ולא דורסים אותו." % target)
    created = []
    existed = []
    try:
        for target in targets:
            if os.path.isdir(target):
                existed.append(target)
            else:
                os.makedirs(target)
                created.append(target)
    except OSError as e:
        raise ScriptError("לא ניתן ליצור את התיקייה: %s" % (e.strerror or e))
    previous = read_pointer()
    pointer = write_pointer(root)
    print("תיקיית הנתונים: %s" % root)
    if created:
        print("נוצרו:")
        for t in created:
            print("  %s" % t)
    if existed:
        print("כבר היו (לא נגעתי בהן):")
        for t in existed:
            print("  %s" % t)
    if previous and previous != root:
        print("המצביע הוחלף: היה %s, עכשיו %s. התיקייה הקודמת לא נגעה." % (previous, root))
    print("המצביע נשמר ב-%s" % pointer)
    return 0


def cmd_set(a):
    folder = _clean_path(a.path)
    if not os.path.isdir(folder):
        raise ScriptError(
            "התיקייה %s לא קיימת. אם זו הפעם הראשונה, ליצור אותה עם data_folder.py init <נתיב>. "
            "אם היא נמצאת במקום אחר, לבדוק את הנתיב." % folder
        )
    previous = read_pointer()
    pointer = write_pointer(folder)
    print("תיקיית הנתונים: %s" % folder)
    if previous and previous != folder:
        print("המצביע הוחלף: היה %s, עכשיו %s." % (previous, folder))
    print("המצביע נשמר ב-%s" % pointer)
    return 0


# ---------------------------------------------------------------- main

def main():
    p = HebrewParser(
        description="תיקיית הנתונים של שרי: איפה היא, יצירה ראשונה שלה, והצבעה על תיקייה קיימת. "
        "המצביע (data-folder.txt) נשמר ב-SHERI_HOME, ברירת מחדל ~/.sheri, ומכיל נתיב בלבד.",
    )
    sub = add_subparsers(p, dest="cmd")
    sub.required = True

    wh = sub.add_parser(
        "where", help="מדפיס את נתיב תיקיית הנתונים",
        description="מדפיס את הנתיב המוחלט של תיקיית הנתונים. קוד יציאה 3: עוד לא הוגדרה. קוד 4: המצביע קיים והתיקייה לא נמצאת.",
    )
    wh.set_defaults(fn=cmd_where)

    ini = sub.add_parser(
        "init", help="יצירה ראשונה של תיקיית הנתונים",
        description="יוצר את עץ התיקיות (פרטי/קבצים-מהבנק, פרטי/עבודה, יומנים; עסק/קבצים-מהבנק ו-עסק/עבודה רק עם --business) "
        "וכותב את המצביע. תיקיות בלבד. בטוח להרצה חוזרת: לא דורס ולא מוחק דבר.",
    )
    ini.add_argument("path", help="נתיב תיקיית הנתונים (נוצרת אם אינה קיימת)")
    ini.add_argument("--business", action="store_true", help="יוצר גם את עסק/קבצים-מהבנק ואת עסק/עבודה (למי שיש לו עסק)")
    ini.set_defaults(fn=cmd_init)

    st = sub.add_parser(
        "set", help="הצבעה על תיקיית נתונים שכבר קיימת",
        description="שומר במצביע נתיב של תיקייה קיימת (למשל במחשב חדש). נכשל אם התיקייה לא קיימת.",
    )
    st.add_argument("path", help="נתיב תיקיית הנתונים הקיימת")
    st.set_defaults(fn=cmd_set)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    run_main(main)
