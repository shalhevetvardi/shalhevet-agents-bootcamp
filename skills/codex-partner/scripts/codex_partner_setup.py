#!/usr/bin/env python3
"""מגדיר את קודקס (Codex של OpenAI) כ"שותף שני" ל-Claude, במחשב של המשתמש.

מה הסקריפט עושה
----------------
1. **בודק** שקודקס מותקן ומחובר לחשבון (`codex login status`).
2. **כותב לקודקס הוראות קבועות של שותף שני**, ב-`~/.codex/AGENTS.md` (או `$CODEX_HOME`). ההוראות
   נבנות מהתבנית `templates/second-partner.md` ומהתשובות של המשתמש (קובץ פרופיל). הן נכתבות כבלוק
   מסומן, וכל מה שכבר כתוב בקובץ מחוץ לבלוק נשאר: אפליקציית קודקס כותבת לאותו קובץ את ההוראות
   שמזינים במסך ההגדרות שלה.
3. **מתקין הגנה על החשבונות:** ב-`config.toml`, בטבלה `[apps._default]`,
   `default_tools_approval_mode = "writes"` ו-`approvals_reviewer = "user"`. לקודקס יש את החיבורים
   של החשבון ב-ChatGPT (GitHub, Gmail, Notion, היומן), ודרכם הוא יכול למזג, לשלוח ולמחוק, גם במצב
   "קריאה בלבד". עם שני הערכים, כל פעולה כזו פותחת חלון שמבקש אישור מהמשתמש. נמדד באפליקציה
   (21-10-2026): עם "writes" לבד, הבקשה לאישור הגיעה לבודק האוטומטי של האפליקציה, והוא אישר מיזוג (על ריפו שלא קיים, בכוונה).
   רק עם `approvals_reviewer = "user"` נפתח חלון למשתמש. ערך אחר שכבר כתוב שם לא נדרס: הסקריפט עוצר.

הקריאה של קובץ ההגדרות עובדת גם בלי `tomllib` (בפייתון 3.9, שמגיע עם Mac). כשהוא קיים, הוא
משמש גם לבדוק שהקובץ תקין. סוף השורה של הקובץ (Windows או Mac) נשמר.

שימוש
-----
    python3 codex_partner_setup.py --status                       # מה מותקן ומה חסר (JSON). לא כותב.
    python3 codex_partner_setup.py --install --profile <p.json>   # מתקין או מעדכן. בטוח להרצה חוזרת.

קובץ הפרופיל: {"name": "...", "about": "...", "language": "עברית", "wants": "..."}.
הוא נשמר גם ב-`<CODEX_HOME>/codex-partner-profile.json`, ולכן עדכון של החבילה בהמשך לא צריך
לשאול שוב (`--install` בלי `--profile` משתמש בו).

יציאה: 0 = הכול תקין (או הותקן); 1 = משהו חסר (ב-`--status`); 2 = לא בוצע (קלט לא תקין, ערך
אחר בהגדרות, או קובץ הגדרות לא תקין).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # פייתון 3.9
    tomllib = None

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "templates" / "second-partner.md"
sys.path.insert(0, str(HERE))
import codex_consult  # noqa: E402  (find_codex וההגדרות של הגשר, ממקור אחד)

START = "<!-- codex-partner:start - נכתב על ידי הסקיל codex-partner. לא לערוך כאן: נדרס בעדכון הבא. -->"
START_PREFIX = "<!-- codex-partner:start"
END = "<!-- codex-partner:end -->"
PROFILE_KEYS = ("name", "about", "language", "wants")
PROFILE_FILE = "codex-partner-profile.json"

# שני הערכים נדרשים יחד. ההסבר בראש הקובץ.
APP_SETTINGS = {"default_tools_approval_mode": "writes", "approvals_reviewer": "user"}
APP_HEADER_RE = re.compile(r"^\[apps\._default\][ \t]*(#[^\r\n]*)?\r?$")
APP_KEY_RE = re.compile(r'^[ \t]*([A-Za-z0-9_-]+)[ \t]*=[ \t]*"([^"\\]*)"[ \t]*(#[^\r\n]*)?\r?$')
OTHER_FORM_RE = re.compile(r"""(^|[\s.\["'])_default\b|^\s*["']?apps["']?\s*[.=]""")
APP_COMMENT = ("# נוסף על ידי הסקיל codex-partner: פעולה של החיבורים לחשבון שמשנה משהו\n"
               "# (מיזוג, שליחה, מחיקה) מבקשת אישור ממך. קריאה רצה בלי לשאול.\n")


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


# ---------- ההוראות הקבועות ----------

def load_profile(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"לא הצלחתי לקרוא את קובץ הפרופיל: {e}")
    if not isinstance(data, dict):
        raise ValueError("קובץ הפרופיל צריך להיות אובייקט JSON")
    missing = [k for k in PROFILE_KEYS if not isinstance(data.get(k), str) or not data[k].strip()]
    if missing:
        raise ValueError("בקובץ הפרופיל חסר: " + ", ".join(missing))
    extra = set(data) - set(PROFILE_KEYS)
    if extra:
        raise ValueError("שדות לא מוכרים בפרופיל: " + ", ".join(sorted(extra)))
    if codex_consult.find_secret(" ".join(data.values())):
        raise ValueError("נראה שיש בפרופיל מפתח או סיסמה. לא כותבים את זה להוראות של קודקס")
    return {k: data[k].strip() for k in PROFILE_KEYS}


def build_block(profile, template=None):
    text = (template or TEMPLATE.read_text(encoding="utf-8")).strip()
    for k in PROFILE_KEYS:
        text = text.replace("{" + k + "}", profile[k])
    leftover = re.findall(r"\{(name|about|language|wants)\}", text)
    if leftover:
        raise ValueError("בתבנית נשארו מקומות ריקים: " + ", ".join(sorted(set(leftover))))
    return START + "\n\n" + text + "\n\n" + END


def find_block(text):
    starts, ends = text.count(START_PREFIX), text.count(END)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1:
        raise ValueError("ב-AGENTS.md יש סימני בלוק שבורים או כפולים. לתקן ביד לפני התקנה")
    s, e = text.index(START_PREFIX), text.index(END)
    if e < s:
        raise ValueError("ב-AGENTS.md סימן הסיום בא לפני סימן הפתיחה. לתקן ביד לפני התקנה")
    return s, e + len(END)


def merged_agents(current, block):
    span = find_block(current)
    if span:
        return current[: span[0]] + block + current[span[1]:]
    rest = current.strip()
    return block + "\n" + ("\n" + rest + "\n" if rest else "")


# ---------- ההגנה על החשבונות (config.toml) ----------

def read_keep_newlines(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def app_table_by_lines(text):
    """הטבלה [apps._default] בקריאה שורה-שורה, בלי tomllib: {מפתח: ערך}, ו-None כשאין כותרת כזו."""
    out, inside, found = {}, False, False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            inside = bool(APP_HEADER_RE.match(line))
            found = found or inside
            continue
        if inside and stripped and not stripped.startswith("#") and "=" in stripped:
            m = APP_KEY_RE.match(line)
            out[m.group(1) if m else stripped.split("=", 1)[0].strip()] = m.group(2) if m else None
    return out if found else None


def parse_app_table(text):
    """(הטבלה, האם היא קיימת בצורה אחרת מהכותרת שהסקריפט מכיר). TOML לא תקין: ValueError."""
    by_lines = app_table_by_lines(text)
    if tomllib is None:
        # בלי tomllib (פייתון 3.10 ומטה, למשל 3.9 שמגיע עם Mac) הקריאה היא שורה-שורה, ולא רואה צורות
        # אחרות של הטבלה: [apps] עם _default בתוכה, מפתחות עם נקודות, כותרת עם רווחים או מירכאות.
        # הוספת כותרת שנייה הייתה שוברת את הקובץ בשקט, ולכן כל אזכור כזה נחשב צורה אחרת, ונעצרים.
        other = any(OTHER_FORM_RE.search(line) for line in text.splitlines()
                    if not line.lstrip().startswith("#") and not APP_HEADER_RE.match(line))
        return by_lines or {}, other
    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"קובץ ההגדרות של קודקס לא תקין: {e}")
    apps = data.get("apps", {})
    return apps.get("_default", {}), "_default" in apps and by_lines is None


def app_settings_problems(home):
    cfg = home / "config.toml"
    if not cfg.exists():
        return ["לקודקס אין קובץ הגדרות, ולכן הוא לא מבקש אישור לפני פעולות בחשבונות"]
    try:
        table, _ = parse_app_table(read_keep_newlines(cfg))
    except ValueError as e:
        return [str(e)]
    wrong = [f'{k} = "{v}"' for k, v in APP_SETTINGS.items() if table.get(k) != v]
    if wrong:
        return ["קודקס לא מבקש אישור לפני פעולות בחשבונות (חסר בהגדרות: " + ", ".join(wrong) + ")"]
    return []


def merged_config(current):
    """הטקסט החדש של config.toml, או None כשאין מה לשנות. ValueError כשכתוב שם ערך אחר."""
    table, other_form = parse_app_table(current)
    conflicts = [k for k, v in APP_SETTINGS.items() if k in table and table[k] != v]
    if conflicts:
        raise ValueError(f"בהגדרות של קודקס כתוב ערך אחר ל-{', '.join(conflicts)} (בטבלה apps._default). לא שיניתי: להחליט ביד")
    missing = {k: v for k, v in APP_SETTINGS.items() if k not in table}
    if not missing:
        return None
    nl = "\r\n" if "\r\n" in current else "\n"
    lines = "".join(f'{k} = "{v}"{nl}' for k, v in missing.items())
    if other_form:
        raise ValueError("ההגדרות של apps._default כתובות בצורה שהסקריפט לא מכיר. להוסיף ביד: " + lines.strip())
    header_end, pos = None, 0
    for line in current.splitlines(keepends=True):
        if APP_HEADER_RE.match(line.rstrip("\r\n")):
            header_end = pos + len(line)
            break
        pos += len(line)
    if header_end is not None:
        head = current[:header_end]
        if not head.endswith("\n"):
            head += nl
        new = head + lines + current[header_end:]
    else:
        body = current.rstrip("\r\n")
        new = body + (nl + nl if body else "") + APP_COMMENT.replace("\n", nl) + "[apps._default]" + nl + lines
    result, _ = parse_app_table(new)
    if any(result.get(k) != v for k, v in APP_SETTINGS.items()):
        raise ValueError("הוספת ההגדרות לא הצליחה. לא שיניתי את הקובץ")
    return new


# ---------- בדיקה והתקנה ----------

def login_state(codex):
    """True / False / None (לא ידוע). `codex login status` יוצא 0 כשהמשתמש מחובר."""
    if not codex:
        return None
    try:
        r = subprocess.run([codex, "login", "status"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout + r.stderr).lower()
    return r.returncode == 0 and "logged in" in out and "not logged in" not in out


def instructions_problems(home, profile=None):
    agents = home / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.exists() else ""
    try:
        span = find_block(text)
    except ValueError as e:
        return [str(e)]
    if not span:
        return ["לקודקס אין עדיין הוראות של שותף שני"]
    if profile and text[span[0]: span[1]] != build_block(profile):
        return ["ההוראות של קודקס לא מעודכנות לגרסה הזו של החבילה"]
    return []


def saved_profile(home):
    p = home / PROFILE_FILE
    return load_profile(p) if p.exists() else None


def status(home):
    codex = codex_consult.find_codex()
    logged_in = login_state(codex)
    try:
        profile = saved_profile(home)
    except ValueError:
        profile = None
    problems = []
    if not codex:
        problems.append("קודקס לא מותקן במחשב הזה (לא נמצאה הפקודה codex)")
    elif logged_in is False:
        # קודקס שמגיע בתוך אפליקציה (למשל ChatGPT ב-Mac) אינו בנתיב החיפוש של הטרמינל, ושם
        # `codex login` נכשל ב-command not found. לכן ההוראה נותנת את הפקודה שבאמת תרוץ.
        if shutil.which("codex"):
            cmd = "codex login"
        else:  # ב-PowerShell נתיב במירכאות לא רץ בלי & לפניו
            cmd = f'& "{codex}" login' if codex_consult.IS_WINDOWS else f'"{codex}" login'
        problems.append(f"קודקס לא מחובר לחשבון: להתחבר באפליקציה של קודקס, או בטרמינל: {cmd}")
    elif logged_in is None:
        problems.append("לא הצלחתי לבדוק אם קודקס מחובר לחשבון")
    if home.is_dir():
        problems += instructions_problems(home, profile)
        problems += app_settings_problems(home)
    else:
        problems.append(f"אין עדיין תיקיית קודקס ({home}). ההתקנה יוצרת אותה")
    return {"ok": not problems, "codex": codex, "logged_in": logged_in, "codex_home": str(home),
            "windows": codex_consult.IS_WINDOWS, "problems": problems}


def backup_once(path, suffix=".before-codex-partner"):
    bak = path.with_name(path.name + suffix)
    if path.exists() and path.read_bytes().strip() and not bak.exists():
        bak.write_bytes(path.read_bytes())
        os.chmod(bak, path.stat().st_mode & 0o777)


def write_atomic(target, text, default_mode, keep_newlines=False):
    tmp = target.with_name(target.name + ".tmp-install")
    with open(tmp, "w", encoding="utf-8", newline="" if keep_newlines else None) as f:
        f.write(text)
    os.chmod(tmp, target.stat().st_mode & 0o777 if target.exists() else default_mode)
    os.replace(tmp, target)


def install(home, profile, template=None):
    """True כשמשהו השתנה. כל הקבצים מחושבים לפני שכותבים אחד מהם, כדי שעצירה לא תשאיר חצי התקנה."""
    home.mkdir(parents=True, exist_ok=True)
    agents = home / "AGENTS.md"
    target = agents.resolve() if agents.is_symlink() else agents
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    new = merged_agents(current, build_block(profile, template))
    cfg = home / "config.toml"
    cfg_target = cfg.resolve() if cfg.is_symlink() else cfg
    cfg_current = read_keep_newlines(cfg_target) if cfg_target.exists() else ""
    cfg_new = merged_config(cfg_current)
    profile_path = home / PROFILE_FILE
    profile_text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"

    changed = False
    if new != current:
        if find_block(current) is None:
            backup_once(target)
        write_atomic(target, new, 0o644)
        changed = True
    if cfg_new is not None:
        backup_once(cfg_target)
        write_atomic(cfg_target, cfg_new, 0o600, keep_newlines=True)
        changed = True
    if not profile_path.exists() or profile_path.read_text(encoding="utf-8") != profile_text:
        write_atomic(profile_path, profile_text, 0o600)
    return changed


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="מגדיר את קודקס כשותף שני ל-Claude")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="מה מותקן ומה חסר. לא כותב")
    g.add_argument("--install", action="store_true", help="מתקין או מעדכן. בטוח להרצה חוזרת")
    ap.add_argument("--profile", help="קובץ JSON עם name, about, language, wants")
    a = ap.parse_args(argv)
    home = codex_home()

    if a.status:
        report = status(home)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1

    try:
        profile = load_profile(a.profile) if a.profile else saved_profile(home)
        if profile is None:
            raise ValueError("אין פרופיל: בהתקנה הראשונה צריך --profile")
        changed = install(home, profile)
    except ValueError as e:
        print(json.dumps({"ok": False, "error_he": codex_consult.redact(str(e))}, ensure_ascii=False, indent=2))
        return 2
    except OSError as e:  # הרשאות, דיסק מלא, תיקייה נעולה: הודעה ברורה במקום traceback
        msg = f"לא הצלחתי לכתוב לתיקיית קודקס ({type(e).__name__}): {codex_consult.redact(str(e))}"
        print(json.dumps({"ok": False, "error_he": msg}, ensure_ascii=False, indent=2))
        return 2
    report = status(home)
    report["changed"] = changed
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not (instructions_problems(home, profile) or app_settings_problems(home)) else 1


if __name__ == "__main__":
    sys.exit(main())
