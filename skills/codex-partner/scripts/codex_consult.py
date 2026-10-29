#!/usr/bin/env python3
"""הגשר להתייעצות עם קודקס (Codex של OpenAI): Claude שולח לו שאלה וחומר, ומקבל דעה שנייה.

למה זה קיים
------------
דעה של מודל שני, גם על רעיונות ותוכן וגם על עבודה ש-Claude עשה. הסקיל `codex-partner` אורז
"תיק" (שאלה, קבצים, טקסטים), והגשר הזה מריץ עליו את קודקס במצב שבו הוא רק קורא, ומחזיר טופס
תשובה קבוע. הרעיון של הגשר מבוסס על המדריך "קודקס הצטרף" של רון אלון, האסיסטנט של טירונות סוכנים
של אִימפּרוּב, עם הרחבות: גם חומר שאינו קובץ, טופס שמתאים גם לרעיונות, וניתוק מהחיבורים של
החשבון ומשאר הקבצים שבמחשב. נבנה בספריית Super Skills של טירונות סוכנים.

מה נמדד ב-21-10-2026 (codex-cli 0.163) וקבע את הבנייה
-------------------------------------------------------
1. **מצב "קריאה בלבד" (`--sandbox read-only`) מונע כתיבה, לא קריאה.** קודקס קרא בלי בעיה
   קובץ מחוץ לתיקייה שקיבל. מה שחוסם קריאה הוא פרופיל הרשאות עם `"deny"` על נתיב,
   ונמדד ישירות דרך `codex sandbox`: עם הפרופיל של הגשר, קריאה מהתיקייה הביתית ומהתיקייה
   הזמנית של Claude נחסמת ברמת מערכת ההפעלה, ובלעדיו (`:read-only` לבד) היא עוברת. בלי
   החסימה הזו קודקס יכול לקרוא את תמלילי השיחות של Claude, וכך לראות מה Claude חושב.
2. **לקודקס יש כלים של החשבון ב-ChatGPT שלא עוברים דרך ההגבלה בכלל:** 275 כלים, ובהם
   מיזוג ב-GitHub, שליחה ומחיקה ב-Gmail, ומחיקה ב-Notion וביומן. `--ignore-user-config` לא
   מוריד אותם; `--disable apps` כן (נשארו 20 כלים, בלי אף אחד מהם).
3. `--ignore-user-config` לא טוען את `config.toml`, וההתחברות עדיין מגיעה מ-`~/.codex`,
   ולכן אין צורך בהתחברות נפרדת. ההוראות הקבועות (`~/.codex/AGENTS.md`) ממשיכות להיטען,
   וזה מכוון: הן מגדירות לקודקס את התפקיד של השותף השני.
4. **`codex exec` מחכה לקלט מהמקלדת כשהקלט לא סגור**, גם כשהשאלה נמסרה כארגומנט: ריצה בלי
   קלט סגור נתקעה יותר משש דקות על "Reading additional input from stdin". לכן השאלה עוברת
   בקלט עצמו (`-`), והקלט נסגר אחריה. כך היא גם לא עוברת בשורת הפקודה, שב-Windows נשברת על
   עברית ועל מירכאות.
5. בלי הגדרות, הריצה הייתה על `gpt-6.1-sol` עם עומק חשיבה "none". הגשר בוחר מודל ועומק.
6. **משתני הסביבה עוברים לכל פקודה שקודקס מריץ**, ובשיחה של Claude יש ביניהם מפתח גישה. הגשר
   מעביר לקודקס רק רשימה סגורה של משתנים (`ENV_KEEP`).
7. ההגבלה הצרה (הכול חסום, חוץ מהחדר ומקובצי המערכת שהכלים צריכים) נבדקה ב-`codex sandbox`:
   `cat`, `sed` ו-`rg` עובדים, `/Library` ו-`~` חסומים. `python3` צריך גם את
   `/Library/Developer/CommandLineTools`, ולכן הוא פתוח לקריאה. **ו-`:minimal` פותח את `/private/tmp`
   גם לקריאה וגם לכתיבה** (נמצא בבודק עיוור: קריאה מהתיקייה הזמנית של Claude וכתיבה ל-`/private/tmp`
   עברו), ולכן התיקיות הזמניות חסומות במפורש. `--sandbox-check` בודק, בלי מודל ובלי שימוש בחשבון,
   שהחדר נקרא ושהתיקייה הביתית, תיקייה זמנית שכנה וכתיבה לחדר חסומות, בכל מחשב שיש בו קודקס.

Windows
-------
המדידות שמעל נעשו על Mac. ב-Windows יש לקודקס שלוש דרכים לבודד פקודה (`windows.sandbox`), ונקראו
בקוד של codex-cli 0.163.0 ובתיעוד (learn.chatgpt.com/docs/windows/windows-sandbox) ב-23-10-2026:
- `mxc`: בידוד של Windows עצמו, בלי הרשאות מנהל ובלי משתמשים נוספים. דורש Windows 11 24H2 או 25H2
  בעדכון מסוים ומעלה, ו-codex-cli 0.162 ומעלה. חסימה של `:root` היא אצלו ברירת המחדל (רק מה שפתוח
  נקרא), ולכן החדר נעול גם בלי יכולת "חסימת נתיב" של מערכת ההפעלה.
- `elevated`: דורש הגדרה חד-פעמית באישור מנהל (`codex sandbox setup --elevated --current-user`),
  שיוצרת במחשב משתמשים נפרדים בהרשאות נמוכות, כללי חומת אש ושינויי מדיניות מקומית.
- `unelevated`: חוסם רק כתיבה (`WRITE_RESTRICTED`). כל הגבלה על קריאה נכשלת בו בהודעה
  "Restricted read-only access requires the elevated Windows sandbox backend"
  (`windows-sandbox-rs/src/lib.rs`), וזו ההודעה שתלמידים קיבלו.
**ובלי `windows.sandbox` בכלל אין בידוד:** `codex sandbox` נופל ל-`unelevated` (ולכן להודעה שמעל),
ו-`codex exec --ignore-user-config` בוחר `SandboxType::None`, כלומר הפקודות של קודקס רצות בלי שום
הגבלה (`sandboxing/src/manager.rs`, `get_platform_sandbox`). לכן הגשר כותב את `windows.sandbox` במפורש,
**אותו ערך בבדיקה ובהתייעצות** (`permission_args`), ובוחר אותו כך: לפני כל התייעצות הוא בודק `mxc`
ואחריו `elevated`, ומשתמש בראשון שנעול בפועל. אין אף אחד נעול: לא מתייעצים, אלא אם המשתמש הסכים
מראש, בעיניים פקוחות, שקודקס יוכל לקרוא כל קובץ במחשב (`--windows-consent read-anywhere`). אז
ההתייעצות רצה ב-`unelevated` בלי הגבלת קריאה (כתיבה עדיין חסומה, וזה נבדק לפני שההסכמה נשמרת),
וכל תוצאה נושאת אזהרה.
עוד שלושה הבדלים בקוד: מוצאים את `codex.exe` עצמו ולא את קובץ ה-`.cmd` של npm, עוצרים את כל עץ
התהליכים ב-`taskkill`, ומשתני המערכת של Windows עוברים לקודקס. בדיקת הנעילה רצה ב-PowerShell, עם
פקודה מקודדת. **על Windows אמיתי זה לא נבדק:** הבדיקות רצות על Mac, עם הדגל IS_WINDOWS מוחלף.

שימוש
-----
    python3 scripts/codex_consult.py <bag.json>             # מריץ ומדפיס תוצאה (JSON)
    python3 scripts/codex_consult.py <bag.json> --dry-run   # בונה את החדר ומדפיס מה היה רץ, בלי קודקס
    python3 scripts/codex_consult.py --sandbox-check        # בודק שהחדר נעול, בלי מודל (0 נעול, 1 לא, 3 לא ידוע)
    python3 scripts/codex_consult.py --windows-consent read-anywhere   # רק ב-Windows, ורק אחרי "כן" מפורש
    python3 scripts/codex_consult.py --windows-consent none            # מבטל את ההסכמה

יציאה: 0 = יש תשובה; 2 = התיק לא תקין (לא נשלח כלום); 3 = קודקס לא הצליח לענות, או שב-Windows
אין חדר נעול ואין הסכמה (`stage` = `sandbox`); 4 = תקלה בגשר עצמו.
מבנה התיק והתוצאה: ב-SKILL.md של הסקיל codex-partner.
"""

import argparse
import base64
import datetime
import hashlib
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
LOG_DIR = Path.home() / ".codex-consult" / "log"

DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_EFFORT = "high"
DEFAULT_TIMEOUT = 480

CODEX_CANDIDATES = [
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/Codex.app/Contents/Resources/codex",
]

# כל אחד מאלה מוסיף לקודקס כלים או זיכרון שלא שייכים להתייעצות. apps הוא החשוב: בלעדיו
# יש לו את החיבורים של החשבון ב-ChatGPT (GitHub, Gmail, Notion), והם עוקפים את ההגבלה.
DISABLED_FEATURES = ["memories", "apps", "plugins", "multi_agent", "goals", "image_generation"]

# רק אלה עוברים לקודקס ולפקודות שהוא מריץ. כל השאר, ובהם מפתחות של השיחה, לא.
ENV_KEEP = ["PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM",
            "CODEX_HOME", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE"]
# ב-Windows תוכנות רבות לא עולות בלי משתני המערכת האלה (בלעדי SYSTEMROOT, למשל, אין רשת).
ENV_KEEP_WINDOWS = ["SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERPROFILE", "USERNAME", "APPDATA", "LOCALAPPDATA",
                    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "PATHEXT", "COMSPEC",
                    "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"]

# ב-Windows: הדרכים שנועלות קריאה, לפי סדר העדיפות (ר' "Windows" בראש הקובץ). unelevated לא נועל
# קריאה, ומשמש רק אחרי הסכמה מפורשת של המשתמש.
WINDOWS_LOCKED_MODES = ("mxc", "elevated")
WINDOWS_OPEN_MODE = "unelevated"
CONSENT_NAME = "windows-read-anywhere.json"

MODES = ("independent", "shared")
PURPOSES = ("idea", "review", "question")
TEXT_SOURCES = ("user", "data", "codex")
BAG_KEYS = {"question", "purpose", "mode", "claude_position", "base", "files", "texts", "images"}

MAX_FILES = 15
MAX_IMAGES = 5
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 1_000_000
MAX_IMAGE_BYTES = 5_000_000
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# ביטויים שמסמנים עמדה. נבדקים בשאלה ובטקסטים מסוג data - לא במילים של המשתמש (הן חומר גלם,
# גם כשכתוב בהן "לדעתי") ולא בקבצים. זו רשת ביטחון ולא הבטחה: עמדה שנוסחה כמשפט
# רגיל עלולה לעבור, ולכן גם הסקיל מורה לא לכתוב עמדה בשאלה.
POSITION_PATTERNS = [
    r"אני חושב", r"לדעתי", r"להערכתי", r"נראה לי ש", r"אני ממליץ", r"המלצתי", r"ההמלצה שלי",
    r"המסקנה שלי", r"הצעתי", r"העמדה שלי", r"עמדת המשרד", r"המלצת קלוד", r"קלוד ממליץ",
    r"קלוד חושב", r"\bI think\b", r"\bI believe\b", r"\bmy recommendation\b", r"\bin my opinion\b",
    r"\bI recommend\b", r"\bClaude (thinks|recommends|suggests)\b", r"\bour position\b",
]

# קבצים שלא יוצאים מהמחשב בשום מקרה, גם אם התבקשו.
DENY_NAMES = {"auth.json", "credentials.json", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "id_ecdsa"}
DENY_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}
DENY_PARTS = {".ssh", ".aws", ".gnupg", ".git"}
ENV_EXAMPLE_SUFFIXES = (".example", ".sample", ".template")

# תבניות של מפתחות. נבדקות על כל התוכן שנשלח (קבצים וטקסטים). ההודעה לא מדפיסה את מה שנמצא.
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"github_pat_[A-Za-z0-9_]{30,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    r"AIza[0-9A-Za-z_\-]{35}",
    r"rnd_[A-Za-z0-9]{20,}",
    r"\bre_[A-Za-z0-9]{20,}",
    r"pat[A-Za-z0-9]{14}\.[a-f0-9]{64}",
    r"\b(ntn|secret)_[A-Za-z0-9]{40,}",
    r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}",
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/=]{16,}",
]

REASONING = "נימוק"

# כשהמודל שנבחר לא זמין בחשבון. היומן תמיד מכיל את השורה "model: ...", ולכן לא מספיק לחפש את המילה.
MODEL_MISSING = re.compile(r"(?i)(model[^\n]{0,80}(not found|not supported|does not exist|unknown|unavailable|invalid|not available))|((unknown|invalid|unsupported) model)")

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "hat", "understood", "bottom_line", "verdict", "findings", "angles", "checks",
        "structure", "recommendation", "risks", "missing_information",
        "disagreements_with_claude", "execution_allowed",
    ],
    "properties": {
        "hat": {"type": "string"},
        "understood": {"type": "string"},
        "bottom_line": {"type": "string"},
        "verdict": {"type": "string", "enum": ["agree", "partially_agree", "disagree", "insufficient_evidence", "open_question"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "kind", "severity", "evidence"],
                "properties": {
                    "claim": {"type": "string"},
                    "kind": {"type": "string", "enum": ["problem", "gap", "strength", "observation"]},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "angles": {"type": "array", "items": {"type": "string"}},
        "checks": {"type": "array", "items": {"type": "string"}},
        "structure": {"type": "string"},
        "recommendation": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "disagreements_with_claude": {"type": "array", "items": {"type": "string"}},
        "execution_allowed": {"type": "boolean", "enum": [False]},
    },
}


class BagError(Exception):
    """התיק לא תקין. שום דבר לא נשלח לקודקס."""


class CodexError(Exception):
    """קודקס לא ענה, או שהתשובה שלו לא תקינה."""


class SandboxUnavailable(CodexError):
    """ב-Windows אין דרך לנעול את החדר במחשב הזה, והמשתמש לא הסכים להתייעץ בלי נעילה."""


# ---------- התיק ----------

def load_bag(path):
    try:
        bag = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BagError(f"לא הצלחתי לקרוא את התיק: {e}")
    if not isinstance(bag, dict):
        raise BagError("התיק צריך להיות אובייקט JSON")
    return bag


def validate_bag(bag):
    unknown = set(bag) - BAG_KEYS
    if unknown:
        raise BagError(f"שדות לא מוכרים בתיק: {', '.join(sorted(unknown))}")
    q = bag.get("question")
    if not isinstance(q, str) or not q.strip():
        raise BagError("חסרה שאלה")
    mode = bag.setdefault("mode", "independent")
    if mode not in MODES:
        raise BagError(f"מצב לא מוכר: {mode}")
    purpose = bag.setdefault("purpose", "question")
    if purpose not in PURPOSES:
        raise BagError(f"מטרה לא מוכרת: {purpose}")
    pos = bag.get("claude_position")
    if mode == "independent" and pos:
        raise BagError("במצב עצמאי אסור לשלוח את העמדה של Claude (claude_position)")
    if mode == "shared" and (not isinstance(pos, str) or not pos.strip()):
        raise BagError("במצב משותף חייבים לשלוח את העמדה של Claude (claude_position)")
    if pos is not None and not isinstance(pos, str):
        raise BagError("claude_position צריך להיות מחרוזת")
    for key in ("files", "texts", "images"):
        if not isinstance(bag.setdefault(key, []), list):
            raise BagError(f"{key} צריך להיות רשימה")
    if len(bag["files"]) > MAX_FILES:
        raise BagError(f"יותר מ-{MAX_FILES} קבצים. תיק גדול מדי לא נקרא כמו שצריך: לבחור את הרלוונטיים")
    if len(bag["images"]) > MAX_IMAGES:
        raise BagError(f"יותר מ-{MAX_IMAGES} תמונות")
    if not isinstance(bag.get("base", ""), str):
        raise BagError("base צריך להיות נתיב (מחרוזת)")
    for key in ("files", "images"):
        if not all(isinstance(x, str) and x.strip() for x in bag[key]):
            raise BagError(f"כל פריט ב-{key} צריך להיות נתיב (מחרוזת)")
    for t in bag["texts"]:
        if (not isinstance(t, dict) or set(t) - {"title", "source", "content"}
                or not isinstance(t.get("content"), str) or not t["content"].strip()
                or not isinstance(t.get("title", ""), str)):
            raise BagError("כל טקסט צריך content (מחרוזת לא ריקה), source, ו-title אם יש (מחרוזת)")
        if t.get("source") not in TEXT_SOURCES:
            raise BagError(f"מקור טקסט לא מוכר: {t.get('source')!r}. מותר: {', '.join(TEXT_SOURCES)}")
    if purpose == "review" and not any(t["source"] == "user" for t in bag["texts"]):
        raise BagError("בבדיקה של עבודה צריך את הבקשה של המשתמש במילים שלו: טקסט אחד לפחות עם source = user")
    for where, text in [("שאלה", q), ("עמדה של Claude", pos or "")] + [(f"כותרת של טקסט מספר {i}", t.get("title") or "") for i, t in enumerate(bag["texts"], start=1)]:
        if find_secret(text):
            raise BagError(f"נראה שב{where} יש מפתח או סיסמה, ולכן שום דבר לא נשלח")
    if mode == "independent":
        scanned = [("שאלה", q)] + [(f"כותרת {t.get('title', '')!r}", t.get("title") or "") for t in bag["texts"]]
        scanned += [(f"טקסט {t.get('title', '')!r}", t["content"]) for t in bag["texts"] if t["source"] == "data"]
        for where, text in scanned:
            for pat in POSITION_PATTERNS:
                if re.search(pat, text, flags=re.IGNORECASE):
                    raise BagError(f"במצב עצמאי נמצא ב{where} ביטוי שמסמן עמדה ({pat}). לנסח בלי עמדה, או לעבור למצב משותף")
    return bag


def denied_reason(path):
    p = Path(path)
    name = p.name.lower()
    home = Path.home().resolve()
    try:
        real = p.resolve()
    except OSError:
        real = p
    for protected in (home / ".claude" / "secrets", home / ".codex", home / ".claude" / "projects", home / ".codex-consult"):
        if real == protected or protected in real.parents:
            return f"{protected} לא נשלח לקודקס"
    if DENY_PARTS & {part.lower() for part in real.parts[:-1]}:
        return "תיקייה של מפתחות או של גיט"
    if name in DENY_NAMES or p.suffix.lower() in DENY_SUFFIXES:
        return "קובץ של מפתחות או התחברות"
    if (name == ".env" or name.startswith(".env.")) and not name.endswith(ENV_EXAMPLE_SUFFIXES):
        return "קובץ .env"
    return None


def find_secret(text):
    for pat in SECRET_PATTERNS:
        if re.search(pat, text):
            return pat
    return None


def room_name_for(path, base):
    real = Path(path).resolve()
    try:
        rel = real.relative_to(Path(base).resolve())
        if ".." not in rel.parts:
            return Path("files") / rel
    except ValueError:
        pass
    home = Path.home().resolve()
    try:
        return Path("files") / "home" / real.relative_to(home)
    except ValueError:
        return Path("files") / "other" / Path(*real.parts[1:])


def count_lines(text):
    """כמו wc -l, ועוד שורה אחרונה בלי ירידת שורה. קובץ ריק: 0."""
    return text.count("\n") + (0 if not text or text.endswith("\n") else 1)


def slug(title, i):
    s = re.sub(r"[^\w֐-׿]+", "-", title or "").strip("-")[:40]
    return f"{i:02d}-{s or 'text'}.md"


def build_room(bag, room):
    """מעתיק לחדר רק את מה שבתיק. מחזיר רשימת פריטים (נתיב בחדר, מקור, sha256, מספר שורות)."""
    base = Path(bag.get("base") or os.getcwd())
    manifest, total = [], 0
    (room / "files").mkdir(parents=True)
    (room / "material").mkdir()

    def add(room_rel, data, source, kind):
        nonlocal total
        total += len(data) if kind != "image" else 0
        if total > MAX_TOTAL_BYTES:
            raise BagError(f"התיק גדול מ-{MAX_TOTAL_BYTES // 1000} KB. לבחור פחות חומר")
        dest = room / room_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        lines = count_lines(data.decode("utf-8")) if kind != "image" else 0
        manifest.append({"room": str(room_rel), "source": source, "kind": kind,
                         "sha256": hashlib.sha256(data).hexdigest(), "lines": lines})

    if bag["mode"] == "shared":
        add(Path("material") / "00-claude-position.md", bag["claude_position"].encode("utf-8"), "claude_position", "text")

    for raw in bag["files"]:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = base / p
        why = denied_reason(p)
        if why:
            raise BagError(f"{raw}: לא נשלח ({why})")
        if not p.is_file():
            raise BagError(f"{raw}: לא קיים, או שזה לא קובץ (תיקייה לא נשלחת - לפרט קבצים)")
        data = p.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise BagError(f"{raw}: גדול מ-{MAX_FILE_BYTES // 1000} KB. לשלוח את החלק הרלוונטי כטקסט מסוג data")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise BagError(f"{raw}: לא קובץ טקסט. תמונה נשלחת ב-images")
        if find_secret(text):
            raise BagError(f"{raw}: נראה שיש בו מפתח או סיסמה, ולכן הוא לא נשלח")
        rel = room_name_for(p, base)
        if any(m["room"] == str(rel) for m in manifest):
            raise BagError(f"{raw}: הקובץ מופיע פעמיים")
        add(rel, data, str(p.resolve()), "file")

    for i, t in enumerate(bag["texts"], start=1):
        if find_secret(t["content"]):
            raise BagError(f"בטקסט מספר {i} נראה שיש מפתח או סיסמה, ולכן הוא לא נשלח")
        add(Path("material") / slug(t.get("title"), i), t["content"].encode("utf-8"), f"text:{t['source']}", "text")

    images = []
    for i, raw in enumerate(bag["images"], start=1):
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = base / p
        why = denied_reason(p)
        if why or not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            raise BagError(f"{raw}: לא תמונה שאפשר לשלוח ({why or 'סוג או קובץ לא מתאים'})")
        if p.stat().st_size > MAX_IMAGE_BYTES:
            raise BagError(f"{raw}: תמונה גדולה מ-{MAX_IMAGE_BYTES // 1_000_000} MB")
        rel = Path("images") / f"{i:02d}{p.suffix.lower()}"
        add(rel, p.read_bytes(), str(p.resolve()), "image")
        images.append(room / rel)
    return manifest, images


# ---------- ההרצה ----------

def windows_native_codex(found):
    """ב-Windows npm מתקין `codex.cmd`, וקובץ כזה רץ דרך cmd.exe, שמפרש מחדש מירכאות וסוגריים.
    לכן מחפשים את `codex.exe` שהחבילה מביאה איתה, ליד הקובץ שנמצא."""
    if not found or not found.lower().endswith((".cmd", ".bat", ".ps1")):
        return found
    base = Path(found).parent
    for pattern in ("node_modules/@openai/codex/vendor/*/codex/codex.exe", "node_modules/@openai/codex/bin/*.exe"):
        hits = sorted(glob.glob(str(base / pattern)))
        if hits:
            return hits[0]
    return found


def find_codex():
    explicit = os.environ.get("CODEX_BIN")
    for cand in ([explicit] if explicit else []) + [shutil.which("codex")] + CODEX_CANDIDATES:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return windows_native_codex(cand) if IS_WINDOWS else cand
    return None


def toml_inline(table):
    return "{" + ",".join(f"{json.dumps(k)}={json.dumps(v)}" for k, v in table.items()) + "}"


def filesystem_policy(room):
    """הכול חסום לקריאה, חוץ מהחדר ומקובצי המערכת שהכלים צריכים (`:minimal`). הכלל הספציפי יותר
    גובר, ולכן החדר נפתח בתוך החסימה. שתי תיקיות הכלים פתוחות כדי ש-python3 ו-node יעבדו."""
    if IS_WINDOWS:
        # ב-Windows אין /tmp, ותיקיות הכלים של Mac לא קיימות. החדר יושב בתיקייה הזמנית, שחסומה דרך :root.
        return {":root": "deny", ":minimal": "read", str(room): "read"}
    return {
        ":root": "deny",
        ":minimal": "read",
        "/Library/Developer/CommandLineTools": "read",
        "/opt/homebrew": "read",
        # :minimal פותח את /private/tmp לקריאה ולכתיבה, ושם יושבת התיקייה הזמנית של Claude (כולל התיק).
        # את :tmpdir (שבו יושב החדר) לא חוסמים במפורש: הוא כבר חסום דרך :root, וחסימה מפורשת שלו
        # גרמה לקודקס להסיק שגם החדר אסור ולסרב לקרוא אותו (נמדד 21-10-2026 בהרצה אמיתית).
        ":slash_tmp": "deny",
        "/private/tmp": "deny",
        "/tmp": "deny",
        str(room): "read",
    }


def permission_args(room, windows_mode=None):
    """ההרשאות שקודקס מקבל, זהות בבדיקת הנעילה ובהתייעצות, כדי שמה שנבדק הוא מה שרץ.

    ב-Windows `windows.sandbox` נכתב תמיד במפורש: בלעדיו `codex exec --ignore-user-config` רץ בלי בידוד בכלל.
    במצב הפתוח (unelevated, רק אחרי הסכמה) אין הגבלת קריאה, כי הוא לא יודע להגביל קריאה ונכשל עליה."""
    args = ["-c", 'default_permissions="consult"', "-c", 'permissions.consult.extends=":read-only"']
    if not (IS_WINDOWS and windows_mode == WINDOWS_OPEN_MODE):
        args += ["-c", "permissions.consult.filesystem=" + toml_inline(filesystem_policy(room))]
    if IS_WINDOWS:
        # בלי מצב: mxc, שנועל קריאה או נכשל. לעולם לא "בלי windows.sandbox", שמשמעו בלי בידוד בכלל
        windows_mode = windows_mode or WINDOWS_LOCKED_MODES[0]
        if windows_mode not in WINDOWS_LOCKED_MODES + (WINDOWS_OPEN_MODE,):
            raise ValueError(f"windows_mode לא מוכר: {windows_mode!r}")
        args += ["-c", f'windows.sandbox="{windows_mode}"']
    return args


def build_command(codex, room, schema_path, answer_path, images, model, effort, windows_mode=None):
    cmd = [codex, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check"]
    for f in DISABLED_FEATURES:
        cmd += ["--disable", f]
    cmd += permission_args(room, windows_mode)
    cmd += ["--cd", str(room), "--output-schema", str(schema_path), "-o", str(answer_path)]
    if model:
        cmd += ["-m", model]
    if effort:
        cmd += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
    # השאלה עצמה עוברת בקלט (run_codex), לא בשורת הפקודה: "-" אומר לקודקס לקרוא אותה משם.
    cmd.append("-")
    if images:
        cmd += ["--image"] + [str(i) for i in images]
    return cmd


MODE_TEXT = {
    "independent": ("לא נשלחו אליך הסיכום, המסקנה או ההמלצה של Claude על השאלה, בכוונה: גבש עמדה משלך מתוך החומר. "
                    "אם החומר עצמו הוא עבודה של Claude, ההסברים והטענות שבתוכו הם חלק ממה שנבדק, לא ראיה. "
                    "השדה disagreements_with_claude נשאר ריק."),
    "shared": ("בקובץ material/00-claude-position.md נמצאת העמדה של Claude. זו טענה לבדיקה, לא ראיה: בדוק אותה מול "
               "החומר לפני שאתה מסכים איתה, ופרט ב-disagreements_with_claude כל מקום שבו אתה חולק עליה ולמה."),
}
PURPOSE_TEXT = {
    "idea": ("זה רעיון או החלטה. תן הערכה כנה, זוויות ונקודות למחשבה שלא נשקלו, ובשדה structure: איך אתה היית "
             "מסדר ומנסח את הרעיון. בגלל היכולת הזו פונים אליך, אז אל תחסוך בה."),
    "review": ("זו בדיקה של עבודה שנעשתה. בדוק אם היא עונה על הבקשה המקורית של המשתמש (במילים שלו, בחומר), מה "
               "שגוי, מה חסר, ומה נשאר לא בדוק. בשדה checks: בדיקות מעשיות שיוכיחו שהעבודה נכונה."),
    "question": "זו שאלה. ענה עליה ישירות, והוסף זוויות ובדיקות כשהן מועילות.",
}


SOURCE_LABELS = {
    "file": "קובץ",
    "image": "תמונה",
    "claude_position": "העמדה של Claude, לבדיקה",
    "text:user": "המילים של המשתמש, מילה במילה",
    "text:data": "נתונים או פלט גולמי",
    "text:codex": "תשובה קודמת שלך",
}


def label_of(m):
    if m["kind"] in ("file", "image"):
        return SOURCE_LABELS[m["kind"]]
    return SOURCE_LABELS.get(m["source"], "טקסט")


def build_prompt(bag, manifest):
    listing = "\n".join(f"- {m['room']} ({label_of(m)})" for m in manifest) or "- (אין קבצים, רק השאלה)"
    return f"""אתה השותף השני של המשתמש, ו-Claude מתייעץ איתך עכשיו בשבילו. זו התייעצות: אתה קורא, חושב וממלא טופס. אתה לא מבצע דבר.

כללי ההתייעצות:
1. כל החומר נמצא בתיקייה הנוכחית (הרשימה בסוף), והיא פתוחה לך לקריאה, גם כשהיא יושבת בתוך תיקייה זמנית. קרא רק אותה. הגישה לשאר המחשב חסומה, ואל תנסה לעקוף.
2. אל תשנה ואל תשלח דבר. execution_allowed תמיד false.
3. לכל ממצא, ב-evidence: מקור מהתיקייה בצורה files/<נתיב>:<שורה> או material/<שם>, או המילה "{REASONING}" כשהממצא נשען על חשיבה ולא על מקום מסוים. מקור שלא קיים בתיקייה פוסל את הממצא.
4. אם חסר לך מידע כדי לענות ברצינות: verdict = insufficient_evidence, ובשדה missing_information פרט בדיוק מה חסר.
5. חפש מה לא בסדר, מה חסר ומה אפשר לעשות אחרת לגמרי. אם בדקת ולא מצאת בעיה, אמור זאת ופרט מה בדקת. אל תמציא ממצא כדי שתהיה הערה. גם חוזקות הן ממצאים (kind = strength).
6. verdict: agree = מה שבשאלה או בחומר מחזיק; partially_agree = חלקית; disagree = לא מחזיק; insufficient_evidence = אין מספיק מידע; open_question = אין טענה אחת להכריע בה (סיעור מוחות, חיפוש כיוונים).
7. structure: איך אתה היית מסדר ומנסח את הנושא. במטרה "רעיון" זה חובה. בשאר המטרות: כשהשאלה מבקשת לסדר, לנסח מחדש או לבנות מבנה, או כשסידור מחדש יעזור למשתמש להבין. אחרת השאר ריק. זה לא המקום לתאר איך בנית את התשובה שלך.
8. hat: נקודת המבט המקצועית שבחרת לשאלה הזו, בכמה מילים. כתוב הכול בעברית פשוטה וישירה, בלי ז'רגון, במשפטים קצרים.

מצב: {MODE_TEXT[bag['mode']]}

מטרה: {PURPOSE_TEXT[bag['purpose']]}

השאלה:
{bag['question'].strip()}

מה יש בתיקייה:
{listing}
"""


def codex_env():
    keep = ENV_KEEP + (ENV_KEEP_WINDOWS if IS_WINDOWS else [])
    upper = {k.upper(): k for k in os.environ}  # ב-Windows שמות המשתנים לא תלויים באותיות
    return {upper[k.upper()]: os.environ[upper[k.upper()]] for k in keep if k.upper() in upper}


def stop_tree(proc):
    """עוצר את קודקס ואת כל מה שהוא הפעיל."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=10)
            return
        except (ProcessLookupError, subprocess.TimeoutExpired):
            continue


def run_codex(cmd, prompt, timeout, log_path):
    """השאלה נכתבת לקלט של קודקס, והקלט נסגר אחריה (בלי סגירה הוא מחכה למקלדת)."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True}
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                env=codex_env(), **group)
        try:
            proc.communicate(input=prompt.encode("utf-8"), timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            stop_tree(proc)
            raise CodexError(f"קודקס לא הספיק לענות בתוך {timeout} שניות. לשאול שאלה ממוקדת יותר, או לשלוח פחות חומר")


def redact(text):
    for pat in SECRET_PATTERNS:
        text = re.sub(pat, "[הוסתר]", text)
    return text


def log_tail(path, chars=1500):
    try:
        return redact(Path(path).read_text(encoding="utf-8", errors="replace")[-chars:])
    except OSError:
        return ""


# ---------- בדיקת התשובה ----------

def check_type(value, schema, where):
    t = schema["type"]
    ok = {"object": dict, "array": list, "string": str, "boolean": bool}[t]
    if not isinstance(value, ok):
        raise CodexError(f"בתשובה, {where} אינו {t}")
    if "enum" in schema and value not in schema["enum"]:
        raise CodexError(f"בתשובה, {where} מכיל ערך לא מותר")
    if t == "object":
        if set(value) != set(schema["required"]):
            raise CodexError(f"בתשובה, לשדות של {where} יש מבנה לא צפוי")
        for k, sub in schema["properties"].items():
            check_type(value[k], sub, f"{where}.{k}")
    if t == "array":
        for i, item in enumerate(value):
            check_type(item, schema["items"], f"{where}[{i}]")


LINES_AFTER = re.compile(r"\s*:\s*(\d+)(?:\s*-\s*(\d+))?")
# אחרי נתיב מוכר מותר רק סוף, רווח, נקודתיים או סימן פיסוק. אחרת זה נתיב אחר שמתחיל באותן אותיות
# (files/a.md מול files/a.md.bak).
PATH_END = re.compile(r"($|[\s:,;)\]\"'])|\.($|\s)")


def bad_citation(evidence, rooms, kinds):
    """None אם המקור תקין; אחרת הסיבה.

    מקור תקין הוא "נימוק" (ממצא שנשען על חשיבה ולא על מקום), או נתיב מהחדר. בקובץ (files/) חייב
    להופיע גם מספר שורה או טווח, וכולם בתוך הקובץ. הנתיבים בחדר יכולים להכיל רווחים, ולכן
    מחפשים את הנתיבים המוכרים מהארוך לקצר, ורק מה שנשאר אחריהם נבדק כ"מקור לא מוכר".
    """
    text = evidence.strip()
    if re.search(r"(^|[\s(,;:\[])(~/|/[^\s/]+/|[A-Za-z]:[\\/])", text):
        return f"מצטט נתיב מחוץ לתיק: {text}"
    m = re.match(rf"{REASONING}(?:$|[\s:,.\-])", text)
    if m:
        rest_text = text[m.end():]
        if not re.search(r"(?:files|material|images)/", rest_text):
            return None
        text = rest_text
    rest, found = text, 0
    for path in sorted(rooms, key=len, reverse=True):
        start = rest.find(path)
        while start != -1:
            after = start + len(path)
            if not PATH_END.match(rest, after):
                start = rest.find(path, after)
                continue
            m = LINES_AFTER.match(rest, after)
            if m:
                first, last = int(m.group(1)), int(m.group(2) or m.group(1))
                if first < 1 or last < first:
                    return f"מספר שורה לא תקין ב-{path}"
                if rooms[path] and last > rooms[path]:
                    return f"מצטט שורה {last} ב-{path}, שיש בו רק {rooms[path]} שורות"
            elif kinds[path] == "file":
                return f"מצטט את {path} בלי מספר שורה"
            found += 1
            end = m.end() if m else after
            rest = rest[:start] + " " * (end - start) + rest[end:]
            start = rest.find(path)
    unknown = re.search(r"(?:files|material|images)/\S+", rest)
    if unknown:
        return f"מצטט מקור שלא היה בתיק: {unknown.group(0)}"
    if not found:
        return f"המקור אינו נתיב מהתיק ואינו \"{REASONING}\": {text}"
    return None


def validate_answer(answer, manifest, mode):
    check_type(answer, ANSWER_SCHEMA, "התשובה")
    if answer["execution_allowed"] is not False:
        raise CodexError("התשובה מסמנת שמותר לבצע - זה אסור בהתייעצות")
    rooms = {m["room"]: m["lines"] for m in manifest}
    kinds = {m["room"]: m["kind"] for m in manifest}
    kept, rejected, warnings = [], [], []
    for f in answer["findings"]:
        reasons = [r for r in (bad_citation(e, rooms, kinds) for e in f["evidence"]) if r]
        if not f["evidence"]:
            reasons.append("ממצא בלי מקור")
        (rejected.append({**f, "rejected_because": reasons}) if reasons else kept.append(f))
    answer["findings"] = kept
    if rejected and not kept:
        raise CodexError(f"כל {len(rejected)} הממצאים של קודקס נפסלו, כי המקורות שלהם לא היו בתיק או לא תקינים. "
                         "בלי ממצא אחד שאפשר לבדוק, אין על מה לסמוך במסקנה שלו")
    if rejected:
        warnings.append(f"{len(rejected)} מתוך {len(rejected) + len(kept)} הממצאים של קודקס נפסלו בגלל המקורות שלהם. "
                        "המסקנה וההמלצה שלו עשויות להישען גם עליהם")
    if mode == "independent" and answer["disagreements_with_claude"]:
        warnings.append("במצב עצמאי קודקס כתב 'איפה הוא חולק על Claude', בלי שקיבל עמדה של Claude. השדה נמחק")
        answer["disagreements_with_claude"] = []
    return answer, rejected, warnings


# ---------- חיבור הכול ----------

def write_log(record):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(LOG_DIR.parent, 0o700)
        path = LOG_DIR / (datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".json")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
        return str(path)
    except OSError:
        return None


def consult(bag, *, dry_run=False, keep_room=False, timeout=DEFAULT_TIMEOUT, model=DEFAULT_MODEL, effort=DEFAULT_EFFORT):
    validate_bag(bag)
    work = Path(tempfile.mkdtemp(prefix="codex-consult-")).resolve()
    room = work / "room"
    try:
        manifest, images = build_room(bag, room)
        prompt = build_prompt(bag, manifest)
        schema_path, answer_path = work / "answer.schema.json", work / "answer.json"
        schema_path.write_text(json.dumps(ANSWER_SCHEMA, ensure_ascii=False), encoding="utf-8")
        codex = find_codex()
        if dry_run:
            # בלי להריץ את קודקס, ולכן בלי לבדוק איזו נעילה זמינה: מוצגת הראשונה ברשימה
            shown_mode = WINDOWS_LOCKED_MODES[0] if IS_WINDOWS else None
            return {"ok": True, "dry_run": True, "room_manifest": manifest, "prompt": prompt,
                    "command": build_command(codex or "codex", room, schema_path, answer_path, images, model, effort, shown_mode)}
        if not codex:
            raise CodexError("קודקס לא מותקן במחשב הזה (לא נמצאה הפקודה codex)")
        warnings = []
        windows_mode = None
        if IS_WINDOWS:
            windows_mode, more = pick_windows_mode()
            warnings += more
        start = time.time()
        used_model = model
        rc = run_codex(build_command(codex, room, schema_path, answer_path, images, model, effort, windows_mode), prompt, timeout, work / "codex.log")
        if rc != 0 and model and MODEL_MISSING.search(log_tail(work / "codex.log")):
            # זמן אחד לשתי הריצות, כדי שמעבר למודל אחר לא יכפיל את ההמתנה מעבר למה שהתבקש
            left = int(timeout - (time.time() - start))
            if left < 10:
                raise CodexError(f"המודל {model} לא זמין, ולא נשאר זמן לנסות מודל אחר")
            warnings.append(f"המודל {model} לא זמין, ולכן קודקס רץ על מודל ברירת המחדל שלו (עם אותו עומק חשיבה, {effort})")
            used_model = None
            rc = run_codex(build_command(codex, room, schema_path, answer_path, images, None, effort, windows_mode), prompt, left, work / "codex.log")
        seconds = round(time.time() - start)
        if rc != 0 or not answer_path.is_file():
            tail = log_tail(work / "codex.log")
            hint = "לא מחובר לחשבון: לפתוח את אפליקציית קודקס ולהתחבר" if re.search(r"(?i)log ?in|unauthori|401", tail) else "הפרטים ביומן"
            raise CodexError(f"קודקס לא סיים (קוד {rc}). {hint}", tail)
        try:
            answer = json.loads(answer_path.read_text(encoding="utf-8"))
        except ValueError:
            raise CodexError("קודקס החזיר תשובה שאינה JSON", log_tail(work / "codex.log"))
        answer, rejected, more = validate_answer(answer, manifest, bag["mode"])
        warnings += more
        result = {"ok": True, "mode": bag["mode"], "purpose": bag["purpose"], "model": used_model or "ברירת המחדל של קודקס",
                  "effort": effort, "seconds": seconds, "answer": answer,
                  **({"windows_sandbox": windows_mode} if IS_WINDOWS else {}),
                  "rejected_findings": rejected, "warnings": warnings, "room_manifest": manifest}
        result["log"] = write_log({"bag": bag, "result": result})
        return result
    finally:
        if keep_room:
            print(f"החדר נשמר: {work}", file=sys.stderr)
        else:
            shutil.rmtree(work, ignore_errors=True)


# ---------- בדיקת הנעילה (בלי מודל, ולכן לא נספרת בשימוש) ----------

SANDBOX_WANT = {"ROOM_READ": "ok", "HOME_READ": "blocked", "SIBLING_READ": "blocked", "ROOM_WRITE": "blocked"}


def sandbox_probe_command(room, sibling):
    """פקודה שמנסה לקרוא מהחדר, מהתיקייה הביתית ומתיקייה זמנית שכנה, ולכתוב לחדר, ומדפיסה שורה לכל ניסיון."""
    probes = [("ROOM_READ", "read", room / "in.md"), ("HOME_READ", "list", Path.home()),
              ("SIBLING_READ", "read", sibling / "s.md"), ("ROOM_WRITE", "write", room / "w")]
    if IS_WINDOWS:
        # PowerShell עם פקודה מקודדת: בלי מירכאות בשורת הפקודה, ששוברות את cmd כשהן עוברות דרך כמה תוכנות.
        q = lambda path: "'" + str(path).replace("'", "''") + "'"
        op = {"read": "Get-Content -LiteralPath {} -ErrorAction Stop | Out-Null",
              "list": "Get-ChildItem -LiteralPath {} -ErrorAction Stop | Out-Null",
              "write": "Set-Content -LiteralPath {} -Value x -ErrorAction Stop"}
        script = "\n".join(f"try {{ {op[kind].format(q(path))}; '{name}:ok' }} catch {{ '{name}:blocked' }}"
                           for name, kind, path in probes)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    op = {"read": 'cat "{}" >/dev/null 2>&1', "list": 'ls "{}" >/dev/null 2>&1', "write": '(echo x > "{}") 2>/dev/null'}
    return ["sh", "-c", "; ".join(f"{op[kind].format(path)} && echo {name}:ok || echo {name}:blocked"
                                  for name, kind, path in probes)]


# במצב הפתוח של Windows (אחרי הסכמה) קריאה מכל מקום מותרת בכוונה, וכתיבה עדיין חייבת להיות חסומה.
OPEN_WANT = {"ROOM_READ": "ok", "ROOM_WRITE": "blocked"}


def judge_sandbox(stdout, want=None):
    """(ok, checks): ok הוא True כשכל מה שב-want התקיים, False כשמשהו פתוח או שהחדר לא נקרא, ו-None כשהבדיקה לא רצה."""
    want = SANDBOX_WANT if want is None else want
    got = {}
    for word in stdout.split():
        if ":" in word:
            k, v = word.split(":", 1)
            if k in SANDBOX_WANT and v in ("ok", "blocked"):
                got[k] = v
    if set(got) != set(SANDBOX_WANT):
        return None, got
    return all(got[k] == v for k, v in want.items()), got


def run_probe(codex, windows_mode, timeout):
    """מריץ את בדיקת הנעילה פעם אחת, עם אותן הרשאות שההתייעצות מקבלת. מחזיר (stdout, סיבה, זנב השגיאה)."""
    room = Path(tempfile.mkdtemp(prefix="codex-consult-check-")).resolve()
    sibling = Path(tempfile.mkdtemp(prefix="codex-consult-check-")).resolve()
    (room / "in.md").write_text("x\n", encoding="utf-8")
    (sibling / "s.md").write_text("x\n", encoding="utf-8")
    cmd = [codex, "sandbox"] + permission_args(room, windows_mode) + ["--"] + sandbox_probe_command(room, sibling)
    try:
        r = subprocess.run(cmd, cwd=room, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=codex_env(), timeout=timeout)
        return r.stdout, f"יציאה {r.returncode}", redact((r.stderr or "").strip()[-400:])
    except (OSError, subprocess.TimeoutExpired) as e:
        return "", type(e).__name__, ""
    finally:
        shutil.rmtree(room, ignore_errors=True)
        shutil.rmtree(sibling, ignore_errors=True)


def judge_attempt(stdout, err, detail, want=None):
    want = SANDBOX_WANT if want is None else want
    ok, got = judge_sandbox(stdout, want)
    result = {"ok": ok, "checks": got}
    if detail:
        result["detail"] = detail
    if ok is None:
        result["error_he"] = f"הבדיקה לא הצליחה לרוץ ({err}), ולכן לא ידוע אם החדר נעול"
    elif got.get("ROOM_READ") != "ok":
        result["error_he"] = "קודקס לא מצליח לקרוא אפילו את החומר שנשלח לו, ולכן ההתייעצות לא תעבוד"
    elif not ok:
        opened = [k for k, v in want.items() if got.get(k) != v]
        result["error_he"] = "החדר לא נעול במחשב הזה: " + ", ".join(opened) + " פתוחים"
    return result


WINDOWS_NO_LOCK_HE = (
    "ב-Windows במחשב הזה אין לקודקס דרך לנעול את החדר: הבדיקה נכשלה גם ב-mxc (הבידוד של Windows עצמו, "
    "בלי הרשאות מנהל) וגם ב-elevated (שדורש הגדרה חד-פעמית באישור מנהל). בלי נעילה קודקס יכול לקרוא כל קובץ "
    "שהמשתמש יכול לקרוא, ולכן לא מתייעצים עד שהמשתמש בוחר: להגדיר את elevated, או להסכים במפורש להתייעץ בלי "
    "נעילת קריאה (כתיבה עדיין חסומה)."
)


def sandbox_check(timeout=60, windows_mode=None):
    """מריץ את מדיניות הקבצים של הגשר דרך `codex sandbox`, בלי מודל, ומחזיר מה נחסם בפועל.

    ב-Windows: בלי windows_mode נבדקות הדרכים שנועלות קריאה לפי הסדר, ו-windows_sandbox הוא הראשונה שנעולה."""
    codex = find_codex()
    if not codex:
        return {"ok": None, "error_he": "קודקס לא מותקן במחשב הזה"}
    if not IS_WINDOWS:
        return judge_attempt(*run_probe(codex, None, timeout))
    if windows_mode == WINDOWS_OPEN_MODE:
        return {**judge_attempt(*run_probe(codex, windows_mode, timeout), want=OPEN_WANT), "windows_sandbox": windows_mode}
    attempts = []
    for mode in ([windows_mode] if windows_mode else WINDOWS_LOCKED_MODES):
        attempt = {"windows_sandbox": mode, **judge_attempt(*run_probe(codex, mode, timeout))}
        attempts.append(attempt)
        if attempt["ok"]:
            return {"ok": True, "checks": attempt["checks"], "windows_sandbox": mode, "attempts": attempts}
    # אף דרך לא נעולה. False רק כשנמדד שמשהו פתוח; כשהבדיקות לא רצו, לא ידוע
    ok = False if any(a["ok"] is False for a in attempts) else None
    return {"ok": ok, "checks": attempts[-1]["checks"], "attempts": attempts,
            "error_he": WINDOWS_NO_LOCK_HE if not windows_mode else attempts[-1].get("error_he", "")}


def consent_path():
    return LOG_DIR.parent / CONSENT_NAME


def read_consent():
    try:
        return json.loads(consent_path().read_text(encoding="utf-8")).get("mode") == "read-anywhere"
    except (OSError, ValueError, AttributeError):
        return False


def set_consent(choice):
    """שומר או מבטל את ההסכמה להתייעץ ב-Windows בלי נעילת קריאה. נשמרת רק אחרי בדיקה שכתיבה חסומה."""
    if not IS_WINDOWS:
        return {"ok": False, "error_he": "ההסכמה הזו קיימת רק ב-Windows. במחשב הזה החדר נעול בדרך אחרת"}
    if choice == "none":
        try:
            consent_path().unlink()
        except FileNotFoundError:
            pass
        return {"ok": True, "consent": "none"}
    check = sandbox_check(windows_mode=WINDOWS_OPEN_MODE)
    if not check["ok"]:
        return {"ok": False, "check": check,
                "error_he": "ההסכמה לא נשמרה: גם במצב הפתוח הבדיקה לא הראתה שקודקס לא יכול לשנות קבצים. "
                            + check.get("error_he", "")}
    path = consent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"mode": "read-anywhere", "date": datetime.date.today().isoformat()}), encoding="utf-8")
    return {"ok": True, "consent": "read-anywhere", "check": check}


READ_ANYWHERE_WARNING = ("החדר לא היה נעול לקריאה: לפי ההסכמה שנשמרה, קודקס רץ במצב שבו הוא יכול לקרוא כל קובץ "
                         "שהמשתמש יכול לקרוא במחשב (לא לשנות). לבטל: --windows-consent none")


def pick_windows_mode():
    """(מצב, אזהרות) להתייעצות ב-Windows. בודק לפני כל התייעצות, כי נעילה שעבדה אתמול לא מבטיחה שתעבוד היום."""
    check = sandbox_check()
    if check["ok"]:
        return check["windows_sandbox"], []
    if read_consent():
        return WINDOWS_OPEN_MODE, [READ_ANYWHERE_WARNING]
    tried = "; ".join(f"{a['windows_sandbox']}: {a.get('error_he', '')} {a.get('detail', '')}".strip()
                      for a in check.get("attempts", []))
    raise SandboxUnavailable(check.get("error_he") or WINDOWS_NO_LOCK_HE, tried)


def main(argv=None):
    # מסוף של Windows לא תמיד כותב עברית; הפלט הוא JSON בעברית, ולכן תמיד UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="התייעצות עם קודקס: תיק ← חדר נעול ← טופס תשובה")
    ap.add_argument("bag", nargs="?")
    ap.add_argument("--sandbox-check", action="store_true",
                    help="בודק שהחדר נעול, בלי מודל ובלי שימוש בחשבון. יציאה 0 נעול, 1 לא נעול, 3 לא ידוע")
    ap.add_argument("--windows-consent", choices=["read-anywhere", "none"],
                    help="רק ב-Windows, ורק אחרי 'כן' מפורש של המשתמש: להתייעץ גם כשאין נעילת קריאה (כתיבה עדיין חסומה)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-room", action="store_true")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh"])
    a = ap.parse_args(argv)
    if a.sandbox_check:
        out = sandbox_check()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else (3 if out["ok"] is None else 1)
    if a.windows_consent:
        out = set_consent(a.windows_consent)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 1
    if not a.bag:
        ap.error("צריך נתיב לתיק, או --sandbox-check")
    try:
        out = consult(load_bag(a.bag), dry_run=a.dry_run, keep_room=a.keep_room, timeout=a.timeout, model=a.model, effort=a.effort)
        code = 0
    except BagError as e:
        # הודעה על תיק לא תקין יכולה לצטט ערך מהתיק (נתיב, שם שדה), ולכן גם היא עוברת הסתרה
        out, code = {"ok": False, "stage": "bag", "error_he": redact(str(e))}, 2
    except SandboxUnavailable as e:
        out = {"ok": False, "stage": "sandbox", "error_he": "לא התייעצתי עם קודקס: " + redact(str(e.args[0]))}
        if len(e.args) > 1 and e.args[1]:
            out["detail"] = e.args[1]
        code = 3
    except CodexError as e:
        out = {"ok": False, "stage": "codex", "error_he": "קודקס לא הצליח להצטרף: " + redact(str(e.args[0]))}
        if len(e.args) > 1:
            out["detail"] = e.args[1]
        code = 3
    except Exception as e:  # תקלה בגשר עצמו: הודעה ברורה במקום traceback, ובלי שום תשובה בשם קודקס
        out, code = {"ok": False, "stage": "bridge", "error_he": f"הגשר נכשל ({type(e).__name__}): {redact(str(e))}"}, 4
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
