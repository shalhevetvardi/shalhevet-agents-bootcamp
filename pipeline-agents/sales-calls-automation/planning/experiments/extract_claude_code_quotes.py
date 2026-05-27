#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_claude_code_quotes.py — חילוץ ציטוטים לפרק פודקאסט "הכלי הוא לא הסיפור. הקצב שלך — כן."

רציונל: זה סוכן החילוץ הרביעי. הקודמים חילצו מבנה שלם אחד לכל שיחה (פרופיל/מחיר/ידע מוצר).
הסוכן הזה מתנהג אחרת — הוא מחלץ N ציטוטים מכל שיחה (או 0 אם אין), ושומר רשומה אחת לכל
ציטוט בטבלה חדשה. הברייף מאסף (סוכן הפקת הפודקאסט) מצורף כ-system prompt.

מצבי הרצה:
    python3 extract_claude_code_quotes.py --dry-run
        # שליפה + פילטר keywords + ספירת טוקנים + עלות משוערת. בלי קריאות API.

    python3 extract_claude_code_quotes.py --run
        # הרצה אמיתית: קריאה ל-Claude + כתיבת רשומות חדשות לטבלת הציטוטים.

    python3 extract_claude_code_quotes.py --run --limit N
        # הגבלת כמות שיחות (ל-smoke test על 3-5 שיחות).

דרישות סביבה (.env):
    ANTHROPIC_API_KEY              — מפתח Anthropic
    AIRTABLE_API_KEY               — Personal Access Token של Airtable
    AIRTABLE_BASE_ID               — ה-Base ID (app5fKvxuzbFb0stR)
    AIRTABLE_TABLE_ID              — טבלת המקור (tblWrBSnk2GxQYOXI — לידים טירונות סוכנים)
    AIRTABLE_QUOTES_TABLE_ID       — טבלת היעד (tblZtg6n5InIXPyl0 — ציטוטים פרק Claude Code)
                                     אם לא מוגדר, יש ברירת מחדל מובנית.

Idempotence: State file מקומי שומר אילו רשומות כבר עובדו (הצלחה / 0 ציטוטים / כשלון).
    ברירת מחדל: state/claude_code_quotes_state.json
    ריצה חוזרת מדלגת על מה שהצליח/נמצא ריק. מה שנכשל — רץ שוב.

פלט:
    1. רשומות חדשות ב-Airtable (רשומה-לכל-ציטוט), עם קישור חזרה לשיחת המקור.
    2. גיבוי Markdown מקומי: quotes_claude_code_YYYYMMDD_HHMMSS.md
    3. גיבוי JSON של הריצה: claude_code_quotes_run_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from anthropic import Anthropic
from dotenv import load_dotenv


# =============================================================================
# קבועים — Claude
# =============================================================================

CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_TEMPERATURE = 0.0          # כפי שמוגדר בברייף — עקביות קריטית
CLAUDE_MAX_TOKENS = 8192          # פלט list של ציטוטים — 8K יספיק בנדיבות

# תמחור (USD למיליון טוקנים) — Opus 4.6
PRICE_INPUT_PER_M = 5.0
PRICE_OUTPUT_PER_M = 25.0
USD_TO_ILS = 3.7

MIN_WORDS = 200                   # סף רך יותר — תמלולים קצרים יותר עדיין רלוונטיים
SLEEP_BETWEEN_RECORDS = 2.0
API_RETRY_DELAYS = [5, 15, 45]


# =============================================================================
# קבועים — Airtable (מקור)
# =============================================================================

SOURCE_TRANSCRIPT_FIELD = "תמלול השיחה"   # שדה זה מכיל דיאריזציה "דובר 0:/דובר 1:" עם timestamps [m:s-m:s]
SOURCE_NAME_FIELD = "שם"
SOURCE_MAIN_STATUS_FIELD = "חילוץ_סטטוס"
SOURCE_MAIN_STATUS_SUCCESS = "הצליח"

# ברירות מחדל (ניתן לעקוף דרך ENV)
DEFAULT_QUOTES_TABLE_ID = "tblZtg6n5InIXPyl0"


# =============================================================================
# קבועים — Airtable (יעד: טבלת הציטוטים)
# =============================================================================

Q_FIELD_QUOTE = "ציטוט"
Q_FIELD_SPEAKER = "דובר"
Q_FIELD_SPEAKER_NAME = "שם הדובר"
Q_FIELD_TIMESTAMP = "חותמת זמן"
Q_FIELD_CONTEXT = "הקשר"
Q_FIELD_CATEGORY = "קטגוריה"
Q_FIELD_PARTS = "חלקי פרק"
Q_FIELD_STRENGTH = "עוצמה"
Q_FIELD_NOTES = "הערות"
Q_FIELD_SOURCE_LINK = "קישור למקור"
Q_FIELD_EXTRACTION_DATE = "תאריך חילוץ"

# ערכי enum מותרים ב-singleSelect (בדיוק כמו שנוצרו בטבלה)
ALLOWED_SPEAKERS = {"לקוח", "שלהבת"}
ALLOWED_CATEGORIES = {
    "FOMO/פיגור",
    "בלבול בין כלים",
    "ציפייה מוטעית",
    "רכישה בלי מטרה",
    "תסכול מכלים",
    "רצון לבנות",
    "כאב של תהליכים",
    "תגובת שלהבת-מסגור",
    "תגובת שלהבת-הדגמה",
    "תגובת שלהבת-קצב",
    "אחר",
}
ALLOWED_PARTS = {"P1", "P2", "P3", "P4", "P5", "P6"}


# =============================================================================
# Keywords — פילטר שלב 1 (Python, לפני LLM)
# =============================================================================
# הכל נורמל ל-lowercase לפני השוואה. עברית לא משתנה ב-lower, אבל אנגלית כן.

KEYWORDS_DIRECT = [
    "claude code", "קלוד קוד",
    "vs code", "ויז'ואל סטודיו", "ויזואל סטודיו",
    "טרמינל",
    "cursor", "קורסור",
    "cowork", "קווורק",
    "vibe coding", "ויב קודינג", "וייב קודינג",
]

KEYWORDS_INDIRECT = [
    "אפליקציית claude", "באפליקציה של קלוד", "אפליקציה של קלוד",
    "mcp", "מי-סי-פי", "מי סי פי",
    "לבנות סוכן", "לבנות אייג'נט", "אייג'נט", "אג'נט",
    "אוטומציה",
    "לבנות כלי", "לבנות מערכת",
]

KEYWORDS_EMOTIONAL = [
    "נשארתי מאחור", "נשאר מאחור", "נשארת מאחור",
    "כולם מדברים", "כולם עושים", "כולם בונים",
    "fomo", "פומו",
    "אני מרגיש", "אני מרגישה",
    "רואה סטוריז", "רואה בלינקדאין", "באינסטגרם",
    "קורסים",
    "הייפ", "היפ",
]

ALL_KEYWORDS = KEYWORDS_DIRECT + KEYWORDS_INDIRECT + KEYWORDS_EMOTIONAL


# =============================================================================
# נתיבים
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
STATE_DIR = SCRIPT_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "claude_code_quotes_state.json"


# =============================================================================
# SYSTEM PROMPT — מהברייף של אסף, verbatim
# =============================================================================

SYSTEM_PROMPT = """אתה עוזר לשלהבת ורדי, מייסדת בית הספר לבינה מלאכותית "אִימפּרוּב", \
להכין פרק פודקאסט בשם עבודה "הכלי הוא לא הסיפור. הקצב שלך — כן."

## ההקשר של הפרק

הפרק יוצא נגד תופעה שבה אנשים רודפים אחרי Claude Code כ"שם קוד" \
ללמידת AI. הטענה המרכזית: כלי לא נותן לך כוונה שאין לך. הסדר הנכון \
הוא תהליך → בעיה → כלי, ולא ההפך. הפרק יש בו 6 חלקים:

1. **P1** — מה זה Claude Code בעצם (מידע)
2. **P2** — איך זה הפך ל"שם קוד" (FOMO, כולם מדברים)
3. **P3** — כלי לא נותן כוונה (הטיעון הלוגי, חוסר ROI, הוצאה vs רווח)
4. **P4** — הדלת האחורית (אפשר לבנות מורכב בלי VS Code)
5. **P5** — הקצב האנושי (אנחנו לא צריכים להתפתח בקצב של AI)
6. **P6** — פנייה פנימה (לפרק תהליכים לפני שבוחרים כלי)

## פורמט התמלול — חשוב

התמלול מכיל דיאריזציה אנונימית בפורמט:
- חותמות זמן במוסגרים: `[0:00-0:36]`, `[1:05-1:31]` וכו' (טווחים בדקות:שניות).
- שני דוברים מתויגים: `דובר 0:` ו-`דובר 1:`.

**כלל זיהוי דובר:**
- **דובר 0 = שלהבת** (המראיינת. שואלת את השאלות הפותחות: "מה את עושה היום בחיים?", "איפה ה-AI נכנס?", "בואי אספר לך על התוכנית"). זו *כמעט תמיד* שלהבת.
- **דובר 1 = הלקוח/ה** (עונה, מתאר/ת את עצמו/ה, שואל/ת על התוכנית).

אם יש סתירה בין ההיגיון הזה לבין תוכן הציטוט — תן/י עדיפות לתוכן (למשל אם דובר 1 מציג את התוכנית). ציין/י בהערה "זיהוי דובר לא ודאי".

**חותמת זמן לציטוט:** קח/י את החותמת של הקטע שבו נאמר (למשל אם הציטוט בקטע שמתויג `[1:05-1:31]` — הוצא `1:05` או `~1:05`).

## המשימה שלך

אני נותן לך תמלול שיחה בין שלהבת ובין לקוח/ה פוטנציאלי/ת. \
חלץ רק ציטוטים שמשרתים את הפרק הזה.

## מה לחלץ

ציטוטים מאחד משני הדוברים (הלקוח או שלהבת) שנופלים תחת אחת הקטגוריות:

### מלקוחות:
- **FOMO / פיגור** — "נשארת מאחור", "כולם עושים", "אני לא בעניינים"
- **בלבול בין כלים** — "מה ההבדל בין X ל-Y?", "צריך להוריד VS Code?"
- **ציפייה מוטעית** — "חשבתי שזה יבנה בעצמו", "זה יותר מסובך ממה שחשבתי"
- **רכישה/למידה בלי מטרה** — "קניתי קורס ועדיין לא..."
- **תסכול מכמות הכלים** — "יש יותר מדי, אני לא יודעת מאיפה"
- **רצון לבנות סוכן/כלי** — "אני רוצה לבנות X, איך מתחילים?"
- **כאב של תהליכים** — "יש לי תהליך ש..." (גם בלי להזכיר AI)

### משלהבת:
- **תגובה מסגרת** — איך היא ממקמת את Claude Code
- **חשיבה אסטרטגית על כלים** — מה היא בוחרת ולמה
- **עמדה על ההייפ** — מה היא אומרת על הרדיפה אחרי כלים
- **הדגמה של בנייה בלי VS Code** — אם היא מתארת סוכן שבנתה באפליקציה
- **דיבור על קצב / אנרגיה / מיקוד**
- **מסגור של "תהליך קודם, כלי אחר כך"**

## מה *לא* לחלץ

- שיח טכני טהור בלי ערך רגשי/אסטרטגי ("הקלקתי פה ואז פה")
- התלבטויות על מחיר/הרשמה (זה שיווק, לא תוכן)
- סמול טוק
- ציטוטים שחוזרים על עצמם (קחי את הוורסיה הטובה יותר)

## פורמט הפלט

החזר JSON array. כל ציטוט כאובייקט עם השדות הבאים:

```json
[
  {
    "speaker": "לקוח" או "שלהבת",
    "speaker_name": "השם המופיע בתמלול, אם יש (אחרת null)",
    "quote": "הציטוט המדויק, מילה במילה",
    "timestamp": "חותמת הזמן מהתמלול (פורמט HH:MM:SS או MM:SS)",
    "context": "משפט או שניים שמסבירים מה הוביל לציטוט — שאלה קודמת, נושא כללי של החלק בשיחה",
    "category": "FOMO/פיגור" | "בלבול בין כלים" | "ציפייה מוטעית" | "רכישה בלי מטרה" | "תסכול מכלים" | "רצון לבנות" | "כאב של תהליכים" | "תגובת שלהבת-מסגור" | "תגובת שלהבת-הדגמה" | "תגובת שלהבת-קצב" | "אחר",
    "relevant_parts": ["P2", "P3"],
    "strength": 1-5,
    "notes": "הערה קצרה אם יש — למשל 'זה נשמע כאילו היא על סף בכי' או 'ציטוט חזק במיוחד'"
  }
]
```

## כללי איכות

1. **ציטוט = מילה במילה.** לא מעבדים, לא מקצרים, לא מנסחים מחדש. אם הציטוט ארוך — לקחת את הגרסה המלאה. קיצוצים לפרק יעשו מאוחר יותר.
2. **Context חייב להיות קצר ומועיל.** "דיברו על תסכול עם כלי AI" — כן. "רקע כללי" — לא.
3. **Strength (1-5):**
   * 5 = ציטוט יהלום. רגשי, ספציפי, חושפני. חייב להיות בפרק.
   * 4 = ציטוט חזק. ספציפי ומעניין.
   * 3 = רלוונטי, לא יוצא דופן.
   * 2 = שימושי כתמיכה, לא כציטוט מרכזי.
   * 1 = גבולי. בספק — אל תחלץ בכלל.
4. **רק ציטוטים ברמה 3+ מחזירים.** אל תמלא את הטבלה בחלקיקים.
5. **אם אין ציטוטים רלוונטיים בתמלול — החזר array ריק `[]`.** אל תמציא.
6. **אם יש timestamp מקורב ולא מדויק** — כתוב אותו עם סימן "~" (למשל `~12:30`).

## פורמט הפלט — החזר JSON תקין בלבד. בלי markdown fences. בלי טקסט לפני או אחרי. רק ה-array."""


USER_MESSAGE_TEMPLATE = """להלן תמלול מלא של שיחת קבלה בין שלהבת ורדי לבין לקוח/ה פוטנציאלי/ת.
חלץ ציטוטים לפי הקריטריונים שב-system prompt.
החזר JSON array תקין בלבד. בלי markdown fences. בלי טקסט לפני או אחרי.

---
תמלול:
{TRANSCRIPT_CONTENT}"""


# =============================================================================
# Logging
# =============================================================================

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("extract_claude_code_quotes")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = LOGS_DIR / f"extract_claude_code_quotes_{datetime.now():%Y%m%d_%H%M%S}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = setup_logging()


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class QuoteResult:
    """ציטוט בודד אחרי ולידציה."""
    speaker: str
    speaker_name: str | None
    quote: str
    timestamp: str | None
    context: str
    category: str
    relevant_parts: list[str]
    strength: int
    notes: str | None

    def to_airtable_fields(self, source_record_id: str, today_iso: str) -> dict:
        fields: dict[str, Any] = {
            Q_FIELD_QUOTE: self.quote,
            Q_FIELD_SPEAKER: self.speaker,
            Q_FIELD_CONTEXT: self.context,
            Q_FIELD_CATEGORY: self.category,
            Q_FIELD_PARTS: self.relevant_parts,
            Q_FIELD_STRENGTH: self.strength,
            Q_FIELD_SOURCE_LINK: [source_record_id],
            Q_FIELD_EXTRACTION_DATE: today_iso,
        }
        if self.speaker_name:
            fields[Q_FIELD_SPEAKER_NAME] = self.speaker_name
        if self.timestamp:
            fields[Q_FIELD_TIMESTAMP] = self.timestamp
        if self.notes:
            fields[Q_FIELD_NOTES] = self.notes
        return fields


@dataclass
class RecordResult:
    record_id: str
    name: str
    status: str
    quotes: list[QuoteResult] = field(default_factory=list)
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    stop_reason: str | None = None
    filter_matched_keywords: list[str] = field(default_factory=list)


@dataclass
class Stats:
    total_source_records: int = 0
    passed_main_status: int = 0
    passed_keyword_filter: int = 0
    skipped_no_main_status: int = 0
    skipped_already_done: int = 0
    skipped_no_keywords: int = 0
    skipped_empty_transcript: int = 0
    llm_called: int = 0
    llm_succeeded: int = 0
    llm_failed: int = 0
    total_quotes_written: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    results: list[RecordResult] = field(default_factory=list)

    def avg_duration(self) -> float:
        ds = [r.duration_seconds for r in self.results if r.duration_seconds > 0]
        return sum(ds) / len(ds) if ds else 0.0

    def total_cost_usd(self) -> float:
        return (self.total_input_tokens * PRICE_INPUT_PER_M
                + self.total_output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000

    def strength_distribution(self) -> dict[int, int]:
        dist: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in self.results:
            for q in r.quotes:
                dist[q.strength] = dist.get(q.strength, 0) + 1
        return dist

    def parts_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {p: 0 for p in sorted(ALLOWED_PARTS)}
        for r in self.results:
            for q in r.quotes:
                for p in q.relevant_parts:
                    dist[p] = dist.get(p, 0) + 1
        return dist


# =============================================================================
# Airtable — HTTP
# =============================================================================

def _airtable_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _records_url(base_id: str, table_id: str) -> str:
    return f"https://api.airtable.com/v0/{base_id}/{table_id}"


def list_all_records(api_key: str, base_id: str, table_id: str) -> list[dict]:
    url = _records_url(base_id, table_id)
    headers = _airtable_headers(api_key)
    records: list[dict] = []
    offset: str | None = None

    while True:
        params: dict[str, Any] = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"קריאת שורות נכשלה ({resp.status_code}): {resp.text}")
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break

    return records


def create_records_batch(api_key: str, base_id: str, table_id: str,
                         records_fields: list[dict]) -> list[dict]:
    """
    יוצר עד 10 רשומות בקריאה אחת (מגבלת Airtable).
    מחזיר את הרשומות שנוצרו (עם ה-id שלהן).
    """
    if not records_fields:
        return []
    if len(records_fields) > 10:
        raise ValueError(f"batch size {len(records_fields)} > 10. פצלי לפני הקריאה.")
    url = _records_url(base_id, table_id)
    body = {
        "records": [{"fields": f} for f in records_fields],
        "typecast": False,
    }
    resp = requests.post(url, headers=_airtable_headers(api_key), json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"יצירת רשומות נכשלה ({resp.status_code}): {resp.text}")
    return resp.json().get("records", [])


def create_records_chunked(api_key: str, base_id: str, table_id: str,
                           records_fields: list[dict]) -> list[dict]:
    """מחלק את הרשומות למנות של 10 וקורא create_records_batch על כל מנה."""
    created: list[dict] = []
    for i in range(0, len(records_fields), 10):
        chunk = records_fields[i:i + 10]
        created.extend(create_records_batch(api_key, base_id, table_id, chunk))
    return created


# =============================================================================
# Keyword filter — שלב 1
# =============================================================================

def keyword_matches(transcript: str) -> list[str]:
    """מחזיר את רשימת המילים שנמצאו בתמלול (בלי כפילויות). ריק = לא עבר פילטר."""
    lower = transcript.lower()
    matched: list[str] = []
    for kw in ALL_KEYWORDS:
        if kw.lower() in lower:
            matched.append(kw)
    return matched


# =============================================================================
# State file — idempotence
# =============================================================================

def load_state() -> dict[str, dict]:
    """מחזיר dict {record_id: {status, timestamp, quotes_count, ...}}."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning(f"State file פגום ({exc}). מתחיל מאפס.")
        return {}


def save_state(state: dict[str, dict]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_skip(state: dict[str, dict], record_id: str) -> tuple[bool, str]:
    """מחזיר (skip, reason)."""
    entry = state.get(record_id)
    if not entry:
        return False, ""
    status = entry.get("status")
    if status in {"success", "no_quotes", "no_keywords", "empty_transcript"}:
        return True, status
    return False, ""


def mark_state(state: dict[str, dict], record_id: str, status: str,
               extra: dict | None = None) -> None:
    entry: dict[str, Any] = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        entry.update(extra)
    state[record_id] = entry


# =============================================================================
# Claude — streaming + retry + ולידציה
# =============================================================================

def call_claude_streaming(client: Anthropic, transcript: str) -> tuple[str, dict, str]:
    user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
    text_parts: list[str] = []
    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for chunk in stream.text_stream:
            text_parts.append(chunk)
        final = stream.get_final_message()

    text = "".join(text_parts).strip()
    usage = {
        "input_tokens": final.usage.input_tokens,
        "output_tokens": final.usage.output_tokens,
    }
    stop_reason = getattr(final, "stop_reason", "unknown") or "unknown"
    return text, usage, stop_reason


def call_claude_with_api_retry(client: Anthropic, transcript: str) -> tuple[str, dict, str]:
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            return call_claude_streaming(client, transcript)
        except Exception as exc:
            last_err = exc
            if attempt < 3:
                delay = API_RETRY_DELAYS[attempt - 1]
                log.warning(f"שגיאת API בניסיון {attempt}: {exc}. ממתין {delay}s ומנסה שוב.")
                time.sleep(delay)
            else:
                log.error(f"כל 3 ניסיונות ה-API נכשלו. שגיאה אחרונה: {exc}")
    raise RuntimeError(f"Claude API failed after 3 attempts: {last_err}")


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text.strip()


def _clamp_strength(val: Any) -> int | None:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 5:
        return None
    return n


def _normalize_speaker(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    v = val.strip()
    if v in ALLOWED_SPEAKERS:
        return v
    # אנגלית fallback
    low = v.lower()
    if low in {"customer", "client", "prospect", "lead"}:
        return "לקוח"
    if low in {"shalhevet", "host"}:
        return "שלהבת"
    return None


def _normalize_category(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    v = val.strip()
    if v in ALLOWED_CATEGORIES:
        return v
    # מיפוי סבלני — אם המודל כתב "FOMO" בלבד
    lowered = v.lower()
    if lowered in {"fomo", "פומו"}:
        return "FOMO/פיגור"
    return None


def _normalize_parts(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for p in val:
        if not isinstance(p, str):
            continue
        u = p.strip().upper()
        if u in ALLOWED_PARTS and u not in out:
            out.append(u)
    return out


def parse_quotes_output(raw_text: str) -> tuple[list[QuoteResult], str | None]:
    """מחזיר (quotes, error_msg). ולידציה ונרמול לכל ציטוט."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return [], f"JSON parse error: {exc}"

    if not isinstance(parsed, list):
        return [], f"שורש ה-JSON אינו array אלא {type(parsed).__name__}"

    quotes: list[QuoteResult] = []
    rejected: list[str] = []

    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            rejected.append(f"#{i}: לא object")
            continue

        speaker = _normalize_speaker(item.get("speaker"))
        if not speaker:
            rejected.append(f"#{i}: speaker לא תקין ({item.get('speaker')!r})")
            continue

        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            rejected.append(f"#{i}: quote ריק/לא טקסט")
            continue

        category = _normalize_category(item.get("category"))
        if not category:
            rejected.append(f"#{i}: category לא תקין ({item.get('category')!r})")
            continue

        strength = _clamp_strength(item.get("strength"))
        if strength is None:
            rejected.append(f"#{i}: strength לא תקין ({item.get('strength')!r})")
            continue
        if strength < 3:
            # לפי הברייף — מסננים החוצה
            continue

        parts = _normalize_parts(item.get("relevant_parts"))
        if not parts:
            rejected.append(f"#{i}: relevant_parts ריק/לא תקין")
            continue

        context = item.get("context")
        if not isinstance(context, str):
            context = ""

        speaker_name_raw = item.get("speaker_name")
        speaker_name = (
            speaker_name_raw.strip()
            if isinstance(speaker_name_raw, str) and speaker_name_raw.strip()
            else None
        )

        timestamp_raw = item.get("timestamp")
        timestamp = (
            timestamp_raw.strip()
            if isinstance(timestamp_raw, str) and timestamp_raw.strip()
            else None
        )

        notes_raw = item.get("notes")
        notes = (
            notes_raw.strip()
            if isinstance(notes_raw, str) and notes_raw.strip()
            else None
        )

        quotes.append(QuoteResult(
            speaker=speaker,
            speaker_name=speaker_name,
            quote=quote.strip(),
            timestamp=timestamp,
            context=context.strip(),
            category=category,
            relevant_parts=parts,
            strength=strength,
            notes=notes,
        ))

    # הודעת שגיאה רכה — אם *כל* הפריטים נפלו, נחשיב את זה ככשלון כן
    if parsed and not quotes and rejected:
        return [], f"כל {len(parsed)} הפריטים נפסלו בוולידציה: {rejected[:3]}"

    return quotes, None


# =============================================================================
# עיבוד שורה בודדת
# =============================================================================

def count_words(text: str) -> int:
    return len(text.split()) if text else 0


def get_record_name(record: dict) -> str:
    return record.get("fields", {}).get(SOURCE_NAME_FIELD) or "אנונימי"


def get_record_transcript(record: dict) -> str:
    return record.get("fields", {}).get(SOURCE_TRANSCRIPT_FIELD, "") or ""


def passes_main_status(record: dict) -> bool:
    return (record.get("fields", {}).get(SOURCE_MAIN_STATUS_FIELD)
            == SOURCE_MAIN_STATUS_SUCCESS)


def process_record(client: Anthropic, record: dict, idx: int, total: int,
                   api_key: str, base_id: str, quotes_table_id: str,
                   stats: Stats, state: dict[str, dict],
                   dry_run: bool = False) -> None:
    record_id = record["id"]
    name = get_record_name(record)
    transcript = get_record_transcript(record)
    word_count = count_words(transcript)

    # שלב 1.1 — תמלול ריק
    if not transcript.strip() or word_count < MIN_WORDS:
        log.info(f"[{idx}/{total}] {name} ({word_count} מילים) → דולג: תמלול קצר/ריק")
        stats.skipped_empty_transcript += 1
        mark_state(state, record_id, "empty_transcript",
                   {"word_count": word_count, "name": name})
        return

    # שלב 1.2 — פילטר keywords
    matched = keyword_matches(transcript)
    if not matched:
        log.info(f"[{idx}/{total}] {name} ({word_count:,} מילים) → דולג: אין keywords")
        stats.skipped_no_keywords += 1
        mark_state(state, record_id, "no_keywords",
                   {"word_count": word_count, "name": name})
        return

    stats.passed_keyword_filter += 1
    log.info(f"[{idx}/{total}] {name} ({word_count:,} מילים) → keywords: "
             f"{', '.join(matched[:5])}{' +עוד' if len(matched) > 5 else ''}")

    if dry_run:
        return

    # שלב 2 — קריאה ל-Claude
    stats.llm_called += 1
    start = time.monotonic()
    result = RecordResult(
        record_id=record_id, name=name, status="pending",
        filter_matched_keywords=matched,
    )

    try:
        raw, usage, stop_reason = call_claude_with_api_retry(client, transcript)
    except Exception as exc:
        elapsed = time.monotonic() - start
        log.error(f"[{idx}/{total}] {name} → נכשל API אחרי {elapsed:.1f}s: {exc}")
        result.status = "failed_api"
        result.error = str(exc)[:5000]
        result.duration_seconds = elapsed
        stats.llm_failed += 1
        stats.results.append(result)
        mark_state(state, record_id, "failed_api",
                   {"name": name, "error": result.error})
        return

    result.duration_seconds = time.monotonic() - start
    result.input_tokens = usage["input_tokens"]
    result.output_tokens = usage["output_tokens"]
    result.stop_reason = stop_reason
    stats.total_input_tokens += usage["input_tokens"]
    stats.total_output_tokens += usage["output_tokens"]

    # שלב 3 — parse + validate
    quotes, err = parse_quotes_output(raw)

    if err:
        # ניסיון שני
        log.warning(f"[{idx}/{total}] {name} → parse נכשל (ניסיון 1): {err}. מנסה שוב...")
        try:
            raw2, usage2, stop_reason2 = call_claude_with_api_retry(client, transcript)
            result.input_tokens += usage2["input_tokens"]
            result.output_tokens += usage2["output_tokens"]
            stats.total_input_tokens += usage2["input_tokens"]
            stats.total_output_tokens += usage2["output_tokens"]
            quotes, err = parse_quotes_output(raw2)
            if not err:
                raw = raw2
                result.stop_reason = stop_reason2
        except Exception as exc:
            log.error(f"[{idx}/{total}] {name} → נכשל בניסיון שני: {exc}")
            result.status = "failed_api"
            result.error = str(exc)[:5000]
            stats.llm_failed += 1
            stats.results.append(result)
            mark_state(state, record_id, "failed_api",
                       {"name": name, "error": result.error})
            return

    if err:
        log.error(f"[{idx}/{total}] {name} → parse נכשל גם בניסיון שני: {err}")
        result.status = "failed_json"
        result.error = f"{err}\n\n--- raw output ---\n{raw}"[:5000]
        stats.llm_failed += 1
        stats.results.append(result)
        mark_state(state, record_id, "failed_json",
                   {"name": name, "error": err[:500]})
        return

    result.quotes = quotes

    cost_usd = (result.input_tokens * PRICE_INPUT_PER_M
                + result.output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000
    trunc_warn = " ⚠️  stop_reason=max_tokens!" if result.stop_reason == "max_tokens" else ""

    # שלב 4 — כתיבה ל-Airtable
    if not quotes:
        log.info(f"[{idx}/{total}] {name} → 0 ציטוטים (כנראה לא רלוונטי). "
                 f"{result.duration_seconds:.1f}s | tokens in={result.input_tokens:,} "
                 f"out={result.output_tokens:,} | ${cost_usd:.3f}{trunc_warn}")
        result.status = "no_quotes"
        stats.llm_succeeded += 1
        stats.results.append(result)
        mark_state(state, record_id, "no_quotes",
                   {"name": name, "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens})
        return

    today_iso = datetime.now(timezone.utc).date().isoformat()
    fields_to_create = [q.to_airtable_fields(record_id, today_iso) for q in quotes]

    try:
        created = create_records_chunked(
            api_key, base_id, quotes_table_id, fields_to_create,
        )
    except Exception as exc:
        log.error(f"[{idx}/{total}] {name} → כתיבה ל-Airtable נכשלה: {exc}")
        result.status = "failed_write"
        result.error = str(exc)[:5000]
        stats.llm_failed += 1
        stats.results.append(result)
        mark_state(state, record_id, "failed_write",
                   {"name": name, "error": result.error})
        return

    log.info(f"[{idx}/{total}] {name} → ✅ {len(quotes)} ציטוטים "
             f"(strengths: {[q.strength for q in quotes]}) "
             f"ב-{result.duration_seconds:.1f}s | "
             f"tokens in={result.input_tokens:,} out={result.output_tokens:,} | "
             f"${cost_usd:.3f}{trunc_warn}")

    result.status = "success"
    stats.llm_succeeded += 1
    stats.total_quotes_written += len(created)
    stats.results.append(result)
    mark_state(state, record_id, "success",
               {"name": name, "quotes_count": len(created),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens})


# =============================================================================
# Pipeline
# =============================================================================

def select_candidates(all_records: list[dict], state: dict[str, dict],
                      stats: Stats) -> list[dict]:
    """שלב 0: בוחר רשומות שעברו חילוץ ראשי + לא נפסלו קודם ב-state."""
    candidates: list[dict] = []
    for r in all_records:
        if not passes_main_status(r):
            stats.skipped_no_main_status += 1
            continue
        stats.passed_main_status += 1
        skip, reason = should_skip(state, r["id"])
        if skip:
            stats.skipped_already_done += 1
            continue
        candidates.append(r)
    return candidates


def run_dry(airtable_key: str, base_id: str, source_table_id: str,
            quotes_table_id: str, anthropic_key: str, limit: int | None) -> int:
    log.info("מצב: --dry-run")
    log.info(f"Source table: {source_table_id}  |  Quotes table: {quotes_table_id}")

    state = load_state()
    log.info(f"State file: {STATE_FILE} | {len(state)} רשומות בהיסטוריה")

    log.info("שולף שורות מטבלת המקור...")
    all_records = list_all_records(airtable_key, base_id, source_table_id)
    log.info(f"נמצאו {len(all_records)} שורות.")

    stats = Stats()
    stats.total_source_records = len(all_records)
    candidates = select_candidates(all_records, state, stats)
    log.info(f"עברו חילוץ ראשי: {stats.passed_main_status} | "
             f"דולגים כבר הושלמו: {stats.skipped_already_done} | "
             f"דולגים ללא חילוץ ראשי: {stats.skipped_no_main_status}")
    log.info(f"מועמדים לאחר פילטר state: {len(candidates)}")

    if limit and limit < len(candidates):
        log.info(f"--limit {limit} הופעל — חותכים את הרשימה.")
        candidates = candidates[:limit]

    # פילטר keywords + ספירת טוקנים משוערת
    client = Anthropic(api_key=anthropic_key)
    total_input_est = 0
    will_call_llm: list[dict] = []

    log.info("עובר על מועמדים ומפעיל פילטר keywords + count_tokens...")
    for i, rec in enumerate(candidates, start=1):
        name = get_record_name(rec)
        transcript = get_record_transcript(rec)
        words = count_words(transcript)

        if not transcript.strip() or words < MIN_WORDS:
            log.info(f"   [{i}/{len(candidates)}] {name}: תמלול קצר ({words} מילים) — ידלג")
            stats.skipped_empty_transcript += 1
            continue

        matched = keyword_matches(transcript)
        if not matched:
            log.info(f"   [{i}/{len(candidates)}] {name}: ללא keywords — ידלג")
            stats.skipped_no_keywords += 1
            continue

        stats.passed_keyword_filter += 1
        will_call_llm.append(rec)

        user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
        try:
            resp = client.messages.count_tokens(
                model=CLAUDE_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            tokens = resp.input_tokens
            total_input_est += tokens
            log.info(f"   [{i}/{len(candidates)}] {name}: עבר keywords "
                     f"({len(matched)} hits) | {tokens:,} tokens | "
                     f"hits: {matched[:3]}")
        except Exception as exc:
            log.warning(f"   [{i}/{len(candidates)}] {name}: count_tokens נכשל ({exc})")

    print_dry_summary(stats, estimated_input_tokens=total_input_est,
                      llm_calls_planned=len(will_call_llm))
    return 0


def print_dry_summary(stats: Stats, estimated_input_tokens: int,
                      llm_calls_planned: int) -> None:
    print()
    print("=" * 70)
    print("  סיכום Dry-Run — ציטוטים לפרק Claude Code")
    print("=" * 70)
    print(f"  שורות בטבלת המקור            : {stats.total_source_records}")
    print(f"  עברו חילוץ ראשי (=הצליח)     : {stats.passed_main_status}")
    print(f"  דולגות כבר טופלו (state)     : {stats.skipped_already_done}")
    print(f"  דולגות תמלול ריק/קצר         : {stats.skipped_empty_transcript}")
    print(f"  דולגות ללא keywords          : {stats.skipped_no_keywords}")
    print(f"  ➜ שיחות שיעברו ל-LLM         : {llm_calls_planned}")
    print("-" * 70)
    if llm_calls_planned > 0:
        print(f"  סך טוקני קלט משוערים         : {estimated_input_tokens:,}")
        max_out_total = llm_calls_planned * CLAUDE_MAX_TOKENS
        in_cost = estimated_input_tokens * PRICE_INPUT_PER_M / 1_000_000
        out_cost = max_out_total * PRICE_OUTPUT_PER_M / 1_000_000
        total_cost = in_cost + out_cost
        print(f"  עלות קלט משוערת              : ${in_cost:.2f}")
        print(f"  עלות פלט מקסימלית            : ${out_cost:.2f}  "
              f"(תקרה — כל תשובה במקס {CLAUDE_MAX_TOKENS:,})")
        print(f"  תקרת עלות כוללת              : ${total_cost:.2f}  "
              f"(~₪{total_cost * USD_TO_ILS:.2f})")
        # הערכה ריאליסטית — ציטוטים קצרים, ~1,500 טוקני פלט בממוצע
        realistic_out = llm_calls_planned * 1500
        real_out_cost = realistic_out * PRICE_OUTPUT_PER_M / 1_000_000
        real_total = in_cost + real_out_cost
        print(f"  הערכה ריאליסטית (1.5K פלט)   : ${real_total:.2f}  "
              f"(~₪{real_total * USD_TO_ILS:.2f})")
    print("=" * 70)
    print()
    print("להרצה אמיתית:")
    print(f"    python3 {Path(__file__).name} --run")
    print()


def run_full(anthropic_key: str, airtable_key: str,
             base_id: str, source_table_id: str, quotes_table_id: str,
             limit: int | None) -> Stats:
    log.info("מצב: --run (הרצה אמיתית מול API)")
    log.info(f"Source table: {source_table_id}  |  Quotes table: {quotes_table_id}")

    state = load_state()
    log.info(f"State file: {STATE_FILE} | {len(state)} רשומות בהיסטוריה")

    log.info("שולף שורות מטבלת המקור...")
    all_records = list_all_records(airtable_key, base_id, source_table_id)
    log.info(f"נמצאו {len(all_records)} שורות.")

    stats = Stats()
    stats.total_source_records = len(all_records)
    candidates = select_candidates(all_records, state, stats)
    log.info(f"עברו חילוץ ראשי: {stats.passed_main_status} | "
             f"דולגים כבר הושלמו: {stats.skipped_already_done}")
    log.info(f"מועמדים לאחר פילטר state: {len(candidates)}")

    if limit and limit < len(candidates):
        log.info(f"--limit {limit} הופעל — חותכים את הרשימה.")
        candidates = candidates[:limit]

    if not candidates:
        log.warning("אין שיחות לעיבוד.")
        return stats

    client = Anthropic(api_key=anthropic_key)

    try:
        for i, record in enumerate(candidates, start=1):
            try:
                process_record(
                    client, record, i, len(candidates),
                    airtable_key, base_id, quotes_table_id,
                    stats, state,
                )
            except Exception as exc:
                log.exception(f"[{i}/{len(candidates)}] שגיאה לא צפויה: {exc}")
                stats.llm_failed += 1
                mark_state(state, record["id"], "failed_unexpected",
                           {"name": get_record_name(record),
                            "error": str(exc)[:500]})

            # שומר state אחרי כל רשומה (עמידות בפני Ctrl+C / crash)
            save_state(state)

            if i < len(candidates):
                time.sleep(SLEEP_BETWEEN_RECORDS)
    finally:
        save_state(state)

    return stats


# =============================================================================
# דוחות וסיכומים + גיבוי
# =============================================================================

def print_run_summary(stats: Stats) -> None:
    print()
    print("=" * 70)
    print("  סיכום הרצה — ציטוטים לפרק Claude Code")
    print("=" * 70)
    print(f"  שורות בטבלת המקור             : {stats.total_source_records}")
    print(f"  עברו חילוץ ראשי               : {stats.passed_main_status}")
    print(f"  דולגות (state)                : {stats.skipped_already_done}")
    print(f"  דולגות (תמלול ריק)            : {stats.skipped_empty_transcript}")
    print(f"  דולגות (אין keywords)         : {stats.skipped_no_keywords}")
    print(f"  הופעל LLM על                  : {stats.llm_called}")
    print(f"    ➜ הצליחו                   : {stats.llm_succeeded}")
    print(f"    ➜ נכשלו                    : {stats.llm_failed}")
    print(f"  סך ציטוטים שנכתבו ל-Airtable  : {stats.total_quotes_written}")
    print("-" * 70)
    print(f"  סך טוקני קלט                  : {stats.total_input_tokens:,}")
    print(f"  סך טוקני פלט                  : {stats.total_output_tokens:,}")
    cost = stats.total_cost_usd()
    print(f"  עלות כוללת                    : ${cost:.3f}  (~₪{cost * USD_TO_ILS:.2f})")
    if stats.results:
        print(f"  זמן ממוצע לקריאה              : {stats.avg_duration():.1f} שניות")
    print("=" * 70)

    # התפלגות עוצמה
    dist = stats.strength_distribution()
    print("\n  📊 התפלגות עוצמה (strength):")
    for s in sorted(dist.keys(), reverse=True):
        count = dist[s]
        if count:
            bar = "█" * min(count, 40)
            print(f"      {s}: {count:>3}  {bar}")

    # התפלגות לפי חלק
    parts_dist = stats.parts_distribution()
    if any(parts_dist.values()):
        print("\n  📊 התפלגות לפי חלק בפרק:")
        for p, count in parts_dist.items():
            bar = "█" * min(count, 40)
            print(f"      {p}: {count:>3}  {bar}")

    # יהלומים
    diamonds: list[QuoteResult] = []
    for r in stats.results:
        for q in r.quotes:
            if q.strength == 5:
                diamonds.append(q)
    if diamonds:
        print(f"\n  💎 ציטוטי יהלום (strength=5): {len(diamonds)}")
        for q in diamonds[:5]:
            speaker_str = q.speaker if not q.speaker_name else f"{q.speaker} / {q.speaker_name}"
            preview = q.quote[:100].replace("\n", " ")
            print(f"      • [{speaker_str}] \"{preview}{'...' if len(q.quote) > 100 else ''}\"")
            print(f"        [{q.category} | {', '.join(q.relevant_parts)}]")
    print()


def save_markdown_backup(stats: Stats) -> Path:
    """יוצר קובץ Markdown עם כל הציטוטים ממוין לפי strength ואז לפי חלק בפרק."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCRIPT_DIR / f"quotes_claude_code_{ts}.md"

    # אוסף כל הציטוטים עם מקור
    rows: list[dict] = []
    for r in stats.results:
        for q in r.quotes:
            rows.append({
                "source_name": r.name,
                "source_record_id": r.record_id,
                **{
                    "speaker": q.speaker,
                    "speaker_name": q.speaker_name,
                    "quote": q.quote,
                    "timestamp": q.timestamp,
                    "context": q.context,
                    "category": q.category,
                    "parts": q.relevant_parts,
                    "strength": q.strength,
                    "notes": q.notes,
                },
            })

    # מיון: strength desc, אז חלק הכי נמוך בפרק, אז מקור
    def sort_key(row: dict) -> tuple:
        first_part = min(row["parts"]) if row["parts"] else "P9"
        return (-row["strength"], first_part, row["source_name"])

    rows.sort(key=sort_key)

    # בונה את ה-Markdown
    lines: list[str] = []
    lines.append(f"# ציטוטים — פרק Claude Code (\"הכלי הוא לא הסיפור. הקצב שלך — כן.\")\n")
    lines.append(f"**תאריך חילוץ:** {datetime.now():%Y-%m-%d %H:%M}\n")
    lines.append(f"**סך ציטוטים:** {len(rows)} | "
                 f"**מקורות:** {len({r['source_record_id'] for r in rows})}\n")
    lines.append(f"**מודל:** {CLAUDE_MODEL} | **טוקני קלט:** {stats.total_input_tokens:,} | "
                 f"**טוקני פלט:** {stats.total_output_tokens:,} | "
                 f"**עלות:** ${stats.total_cost_usd():.3f}\n")
    lines.append("\n---\n")

    # התפלגויות
    lines.append("## התפלגות עוצמה\n")
    dist = stats.strength_distribution()
    for s in sorted(dist.keys(), reverse=True):
        if dist[s]:
            lines.append(f"- **{s}⭐** — {dist[s]} ציטוטים")
    lines.append("")

    lines.append("## התפלגות לפי חלק בפרק\n")
    parts_dist = stats.parts_distribution()
    for p, count in parts_dist.items():
        if count:
            lines.append(f"- **{p}** — {count} ציטוטים")
    lines.append("\n---\n")

    # טבלה מלאה
    lines.append("## טבלה מלאה (ממוינת לפי strength ↓ ואז חלק ↑)\n")
    lines.append("| # | מקור | דובר | ציטוט | timestamp | הקשר | קטגוריה | חלקים | ⭐ | הערות |")
    lines.append("|---|------|-------|--------|-----------|-------|----------|-------|----|--------|")
    for i, row in enumerate(rows, start=1):
        speaker = row["speaker"]
        if row["speaker_name"]:
            speaker = f"{row['speaker']}<br>({row['speaker_name']})"
        quote_cell = row["quote"].replace("|", "\\|").replace("\n", " ")
        context_cell = (row["context"] or "").replace("|", "\\|").replace("\n", " ")
        notes_cell = (row["notes"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {i} | {row['source_name']} | {speaker} | "
            f"{quote_cell} | {row['timestamp'] or ''} | {context_cell} | "
            f"{row['category']} | {', '.join(row['parts'])} | "
            f"{row['strength']} | {notes_cell} |"
        )
    lines.append("")

    # גרסה מפורטת — כל ציטוט כבלוק
    lines.append("\n---\n\n## ציטוטים בפירוט\n")
    for i, row in enumerate(rows, start=1):
        speaker_str = row["speaker"]
        if row["speaker_name"]:
            speaker_str += f" / {row['speaker_name']}"
        lines.append(f"### {i}. [{row['strength']}⭐] {row['category']} — {speaker_str}\n")
        if row["timestamp"]:
            lines.append(f"**Timestamp:** `{row['timestamp']}`  ")
        lines.append(f"**מקור:** {row['source_name']}  ")
        lines.append(f"**חלקים בפרק:** {', '.join(row['parts'])}\n")
        lines.append(f"> {row['quote']}\n")
        if row["context"]:
            lines.append(f"**הקשר:** {row['context']}\n")
        if row["notes"]:
            lines.append(f"**הערה:** _{row['notes']}_\n")
        lines.append("---\n")

    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"גיבוי Markdown נשמר: {path}")
    return path


def save_json_backup(stats: Stats) -> Path:
    """גיבוי JSON של הריצה — כל הנתונים, לא רק הציטוטים."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCRIPT_DIR / f"claude_code_quotes_run_{ts}.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": CLAUDE_MODEL,
        "temperature": CLAUDE_TEMPERATURE,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "total_source_records": stats.total_source_records,
        "passed_main_status": stats.passed_main_status,
        "skipped_already_done": stats.skipped_already_done,
        "skipped_empty_transcript": stats.skipped_empty_transcript,
        "skipped_no_keywords": stats.skipped_no_keywords,
        "llm_called": stats.llm_called,
        "llm_succeeded": stats.llm_succeeded,
        "llm_failed": stats.llm_failed,
        "total_quotes_written": stats.total_quotes_written,
        "total_input_tokens": stats.total_input_tokens,
        "total_output_tokens": stats.total_output_tokens,
        "total_cost_usd": round(stats.total_cost_usd(), 4),
        "strength_distribution": stats.strength_distribution(),
        "parts_distribution": stats.parts_distribution(),
        "per_record": [
            {
                "record_id": r.record_id,
                "name": r.name,
                "status": r.status,
                "error": r.error,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "duration_seconds": round(r.duration_seconds, 2),
                "stop_reason": r.stop_reason,
                "filter_matched_keywords": r.filter_matched_keywords,
                "quotes": [
                    {
                        "speaker": q.speaker,
                        "speaker_name": q.speaker_name,
                        "quote": q.quote,
                        "timestamp": q.timestamp,
                        "context": q.context,
                        "category": q.category,
                        "relevant_parts": q.relevant_parts,
                        "strength": q.strength,
                        "notes": q.notes,
                    }
                    for q in r.quotes
                ],
            }
            for r in stats.results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    log.info(f"גיבוי JSON נשמר: {path}")
    return path


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="חילוץ ציטוטים לפרק פודקאסט Claude Code מתמלולי טירונות סוכנים.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""דוגמאות:
    python3 extract_claude_code_quotes.py --dry-run
    python3 extract_claude_code_quotes.py --run
    python3 extract_claude_code_quotes.py --run --limit 3       # smoke test
    python3 extract_claude_code_quotes.py --dry-run --limit 5""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="שליפה + keywords + count_tokens. בלי קריאה ל-LLM.")
    group.add_argument("--run", action="store_true",
                       help="הרצה אמיתית, idempotent דרך state file.")
    parser.add_argument("--limit", type=int, default=None,
                        help="הגבלת כמות מועמדים (אחרי פילטר state). שימושי ל-smoke test.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    load_dotenv(SCRIPT_DIR / ".env")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    airtable_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    source_table_id = os.getenv("AIRTABLE_TABLE_ID")
    quotes_table_id = os.getenv("AIRTABLE_QUOTES_TABLE_ID") or DEFAULT_QUOTES_TABLE_ID

    missing = [name for name, val in [
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("AIRTABLE_API_KEY", airtable_key),
        ("AIRTABLE_BASE_ID", base_id),
        ("AIRTABLE_TABLE_ID", source_table_id),
    ] if not val]
    if missing:
        log.error(f"חסרים משתני סביבה: {missing}. הגדירי אותם ב-.env.")
        return 2

    try:
        if args.dry_run:
            return run_dry(airtable_key, base_id, source_table_id,
                           quotes_table_id, anthropic_key, args.limit)

        stats = run_full(anthropic_key, airtable_key, base_id,
                         source_table_id, quotes_table_id, args.limit)
    except KeyboardInterrupt:
        log.warning("הרצה הופסקה ידנית.")
        return 130
    except Exception as exc:
        log.exception(f"שגיאה כללית: {exc}")
        return 1

    print_run_summary(stats)
    save_json_backup(stats)
    save_markdown_backup(stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())
