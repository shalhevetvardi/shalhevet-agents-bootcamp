#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_product_knowledge.py — סוכן חילוץ ידע מוצר מראיונות טירונות סוכנים.

רציונל: זה סוכן החילוץ השלישי. הראשון (extract_interviews.py) חילץ פרופיל מועמד.
השני (extract_price_response.py) חילץ את רגע המחיר. הסוכן הזה מחלץ משהו אחר —
את המידע על התוכנית עצמה שיוצא מהפה של שלהבת בשיחות. זה מידע שלא כתוב בשום
מסמך רשמי אלא חי רק בתוך התמלולים. הפלט נשמר ב-Airtable בארבעה שדות נפרדים
שלא נוגעים בפלט של הסוכנים הקודמים.

מצבי הרצה:
    python3 extract_product_knowledge.py --dry-run
        # שליפה + פילטר + ספירת טוקנים + עלות משוערת. בלי קריאות API.

    python3 extract_product_knowledge.py --run
        # הרצה אמיתית: קריאה ל-Claude לכל שיחה ושמירה ל-Airtable (idempotent).

דרישות סביבה (.env):
    ANTHROPIC_API_KEY        — מפתח Anthropic
    AIRTABLE_API_KEY         — Personal Access Token של Airtable
    AIRTABLE_BASE_ID         — ה-Base ID (מצופה: app5fKvxuzbFb0stR)
    AIRTABLE_TABLE_ID        — ה-Table ID של טבלת הראיונות (מצופה: tblWrBSnk2GxQYOXI)

הסקריפט:
    1. מאמת ש-4 שדות החילוץ קיימים ב-Airtable. השדות חייבים להיות מוכנים
       ידנית מראש (המשתמשת יוצרת אותם לפני ההרצה):
         חילוץ_ידע_מוצר_JSON     (multilineText)
         חילוץ_ידע_מוצר_סטטוס    (singleSelect: ממתין / הצליח / נכשל)
         חילוץ_ידע_מוצר_שגיאה    (multilineText)
         חילוץ_ידע_מוצר_תאריך    (date)
       אם חסרים — עוצר עם הודעת שגיאה ברורה.
    2. סורק שורות: רק חילוץ_סטטוס == "הצליח" וגם חילוץ_ידע_מוצר_סטטוס != "הצליח".
    3. פילטר נוסף: מסנן החוצה שיחות פיבוט (מחיר 12,900) לפי
       חילוץ_תגובה_למחיר_JSON → price_quote_verbatim.
    4. קורא את שדה "תמלול השיחה".
    5. שולח ל-Claude (claude-opus-4-6, temperature=0.3, max_tokens=16000) ב-STREAMING.
       streaming חובה כי עם max_tokens=16000 הקריאה עלולה לעבור 10 דקות וה-SDK
       חוסם non-streaming מעל הסף הזה.
    6. retry: 3 ניסיונות API עם backoff [5, 15, 45] שניות.
    7. JSON לא חוקי → ניסיון חוזר אחד; אם נכשל → סטטוס נכשל + טקסט שגיאה.
    8. השהייה של 2 שניות בין שיחות.
    9. Log קומפקטי לכל שיחה: שם, סטטוס, טוקנים, עלות, זמן.
   10. סיכום בסוף: סך הצלחות/כשלים, סך עלות, ממוצע.
   11. גיבוי מקומי: כל הפלטים נשמרים גם לקובץ JSON מקומי.
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
CLAUDE_TEMPERATURE = 0.3
CLAUDE_MAX_TOKENS = 16000

# תמחור (USD למיליון טוקנים) — Opus 4.6 לפי platform.claude.com/docs
PRICE_INPUT_PER_M = 5.0
PRICE_OUTPUT_PER_M = 25.0
USD_TO_ILS = 3.7

MIN_WORDS = 500
SLEEP_BETWEEN_RECORDS = 2.0
API_RETRY_DELAYS = [5, 15, 45]


# =============================================================================
# קבועים — Airtable
# =============================================================================

TRANSCRIPT_FIELD_NAME = "תמלול השיחה"
NAME_FIELD = "שם"
MAIN_EXTRACTION_STATUS_FIELD = "חילוץ_סטטוס"
PRICE_JSON_FIELD = "חילוץ_תגובה_למחיר_JSON"

MAIN_STATUS_SUCCESS = "הצליח"

# 4 שדות חדשים — שייכים לסוכן הזה בלבד
FIELD_PK_JSON = "חילוץ_ידע_מוצר_JSON"
FIELD_PK_STATUS = "חילוץ_ידע_מוצר_סטטוס"
FIELD_PK_ERROR = "חילוץ_ידע_מוצר_שגיאה"
FIELD_PK_DATE = "חילוץ_ידע_מוצר_תאריך"

# סטטוסים
STATUS_PENDING = "ממתין"
STATUS_SUCCESS = "הצליח"
STATUS_FAILED = "נכשל"

REQUIRED_STATUS_OPTIONS = [STATUS_PENDING, STATUS_SUCCESS, STATUS_FAILED]

# פילטר פיבוט — 6 שיחות מתקופת תמחור 12,900 שלא שייכות לניתוח התוכנית הנוכחית
PIVOT_PRICE_MARKERS = ["12,900", "12900", "12.900"]


# =============================================================================
# קבועים — ולידציה של JSON הפלט
# =============================================================================

REQUIRED_ROOT_KEYS = [
    "meta",
    "product_facts_stated",
    "explicit_promises",
    "explicit_disclaimers",
    "unique_framings",
    # "open_notes" רצוי אך לא חובה — המודל לפעמים משמיט
]


# =============================================================================
# נתיבים
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# =============================================================================
# SYSTEM PROMPT — כקבוע בקובץ, כמו שביקשת
# =============================================================================

SYSTEM_PROMPT = """אתה אנליסט ידע מוצר. אתה מנתח תמלול של שיחת קבלה אחת בין שלהבת ורדי (מנכ"לית אימפרוב) לבין מועמד/ת לקורס "טירונות סוכנים". המטרה שלך: לחלץ כל פיסת מידע על התוכנית (הקורס) שיצאה מהפה של שלהבת — מידע שלא כתוב בשום מסמך רשמי אלא חי רק בשיחות.

## מה אתה מחלץ

ארבע קטגוריות של מידע:

### 1. product_facts_stated — עובדות על התוכנית שנאמרו בפועל

כל רגע ששלהבת אמרה עובדה על הקורס. גם אם נאמרה בתגובה לשאלה, גם אם ביוזמתה.

דוגמאות לעובדות:
- "אנחנו נפגשים פעם בשבוע לשלוש שעות"
- "יש הקלטות של כל המפגש"
- "הקבוצה הזו מוגבלת ל-15 אנשים"
- "מי שלא מסתדר עם התאריך יכול להשלים במפגש הבא"
- "אנחנו משתמשים ב-Claude, Make, ו-Zapier"
- "אין צורך בידע בתכנות"
- "המפגש הראשון הוא תאריך X"

לכל עובדה שמצאת, תעד:
- `topic`: נושא קצר (למשל "הקלטות", "תאריכים", "מבנה מפגש", "כלים")
- `trigger`: "candidate_question" או "shalhevet_initiative"
- `quote_from_candidate`: אם יש — ציטוט מלא של השאלה. אם אין — null
- `quote_from_shalhevet`: ציטוט וורבטי מלא של התשובה/האמירה של שלהבת
- `category`: אחד מ: "logistics", "content", "technical", "terms", "promise", "fit", "other"
- `is_definitive`: true אם נאמר כעובדה חד-משמעית, false אם נאמר כ"נראה לי" / "אני חושבת ש" / "אולי"

### 2. explicit_promises — הבטחות מפורשות

מקומות ששלהבת הבטיחה משהו בפועל. למשל: "אני מבטיחה שתצאי עם X", "אני אדאג ל-Y", "כל מי שמגיע מקבל Z".

לכל הבטחה:
- `promise_quote`: ציטוט וורבטי מלא
- `scope`: תיאור קצר של מה ההבטחה מכסה

### 3. explicit_disclaimers — הסתייגויות מפורשות

מקומות ששלהבת הבהירה מה *לא* כלול, מה *לא* מובטח, מה *לא* מתאים. למשל: "זה לא קורס להתחלה", "אני לא מבטיחה שתרוויח כסף", "אנחנו לא מלמדים X".

לכל הסתייגות:
- `disclaimer_quote`: ציטוט וורבטי מלא
- `what_its_excluding`: תיאור קצר של מה זה מחריג

### 4. unique_framings — ניסוחים ייחודיים של שלהבת

איך שלהבת מגדירה את התוכנית באופן ייחודי שלה — ניסוחים שחוזרים, מטאפורות, הסברים שלא כתובים בשום מסמך רשמי.

דוגמאות:
- "זה לא קורס, זו סיירת"
- "אנחנו לא מלמדים AI, אנחנו בונים יחד"
- "הקהל שלנו הוא אנשים שכבר משתמשים ב-AI יום-יום"

לכל ניסוח:
- `quote`: ציטוט וורבטי מלא
- `what_it_defines`: מה זה מגדיר (למשל: "אופי הקורס", "סגנון הלמידה", "קהל היעד")

## כללי ברזל

1. **ציטוטים וורבטיים בלבד.** כולל מילוי ("כאילו", "אה"), חזרות, טעויות תמלול. אל תנקה.
2. **רק מה ששלהבת אמרה.** לא את המועמד. אלא אם המועמד ציטט משהו ששלהבת אמרה לו קודם.
3. **אל תמציא.** אם לא נאמרה הבטחה מפורשת — אל תכתוב שיש. אם קטגוריה ריקה — array ריק זה בסדר.
4. **הקשר חשוב.** אם שלהבת אמרה "אנחנו לא X, אנחנו כן Y" — זה גם disclaimer (X) וגם fact/framing (Y). תעד בשניהם.
5. **אם שלהבת אמרה משהו סותר במקומות שונים באותה שיחה** — תעד את שני הציטוטים בנפרד. הסינתזה תטפל בסתירה.
6. **התעלם מקטעי היכרות כלליים.** "נעים מאוד", "מאיפה אתה" — לא רלוונטי. מתחילים מרגע שהשיחה נכנסת לנושא התוכנית.

## פורמט הפלט

JSON תקין בלבד. בלי markdown fences (ללא ```json```), בלי טקסט לפני או אחרי. המבנה:

```json
{
  "meta": {
    "candidate_name": "שם המועמד אם מופיע בתמלול, אחרת null",
    "transcript_quality": "good" | "medium" | "problematic",
    "quality_notes": "הערות קצרות על איכות התמלול אם רלוונטי, אחרת null"
  },
  "product_facts_stated": [
    {
      "topic": "...",
      "trigger": "candidate_question" | "shalhevet_initiative",
      "quote_from_candidate": "..." או null,
      "quote_from_shalhevet": "...",
      "category": "logistics" | "content" | "technical" | "terms" | "promise" | "fit" | "other",
      "is_definitive": true | false
    }
  ],
  "explicit_promises": [
    {
      "promise_quote": "...",
      "scope": "..."
    }
  ],
  "explicit_disclaimers": [
    {
      "disclaimer_quote": "...",
      "what_its_excluding": "..."
    }
  ],
  "unique_framings": [
    {
      "quote": "...",
      "what_it_defines": "..."
    }
  ],
  "open_notes": "הערות חופשיות לגבי דברים שבלטו בשיחה שלא נכנסו לקטגוריות הקבועות, או null"
}
```

## הקלט שלך

תמלול מלא של שיחה אחת. קרא אותו במלואו, זהה את כל ארבעת סוגי המידע, וצור JSON לפי המבנה שלמעלה."""


USER_MESSAGE_TEMPLATE = """להלן תמלול מלא של שיחת קבלה של שלהבת ורדי עם מועמד/ת לתוכנית טירונות סוכנים.
חלץ את המידע על התוכנית לפי הסכמה שהוגדרה ב-system prompt.
החזר JSON תקין בלבד. בלי markdown fences. בלי טקסט לפני או אחרי.

---
תמלול:
{TRANSCRIPT_CONTENT}"""


# =============================================================================
# Logging
# =============================================================================

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("extract_product_knowledge")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = LOGS_DIR / f"extract_product_knowledge_{datetime.now():%Y%m%d_%H%M%S}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = setup_logging()


# =============================================================================
# Stats
# =============================================================================

@dataclass
class RecordResult:
    record_id: str
    name: str
    status: str
    error: str | None = None
    parsed: dict | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    stop_reason: str | None = None


@dataclass
class Stats:
    total_candidates: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_empty: int = 0
    skipped_already_done: int = 0
    skipped_pivot: int = 0
    pivot_details: list[dict] = field(default_factory=list)
    results: list[RecordResult] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def avg_duration(self) -> float:
        ds = [r.duration_seconds for r in self.results if r.duration_seconds > 0]
        return sum(ds) / len(ds) if ds else 0.0

    def total_cost_usd(self) -> float:
        return (self.total_input_tokens * PRICE_INPUT_PER_M
                + self.total_output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000


# =============================================================================
# Airtable — HTTP
# =============================================================================

def _airtable_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _meta_tables_url(base_id: str) -> str:
    return f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"


def _records_url(base_id: str, table_id: str) -> str:
    return f"https://api.airtable.com/v0/{base_id}/{table_id}"


def get_existing_fields(api_key: str, base_id: str, table_id: str) -> dict[str, dict]:
    resp = requests.get(_meta_tables_url(base_id), headers=_airtable_headers(api_key))
    resp.raise_for_status()
    data = resp.json()
    for table in data.get("tables", []):
        if table.get("id") == table_id:
            return {f["name"]: f for f in table.get("fields", [])}
    raise RuntimeError(f"טבלה {table_id} לא נמצאה בבסיס {base_id}")


# הגדרות השדות החדשים שהסקריפט יוצר אוטומטית ב-Airtable
PK_FIELD_SPECS: list[dict] = [
    {
        "name": FIELD_PK_JSON,
        "type": "multilineText",
        "description": "פלט JSON של חילוץ ידע מוצר (נוצר אוטומטית).",
    },
    {
        "name": FIELD_PK_STATUS,
        "type": "singleSelect",
        "description": "סטטוס חילוץ ידע מוצר (נוצר אוטומטית).",
        "options": {
            "choices": [{"name": opt} for opt in REQUIRED_STATUS_OPTIONS],
        },
    },
    {
        "name": FIELD_PK_ERROR,
        "type": "multilineText",
        "description": "שגיאות מהרצת חילוץ ידע מוצר (נוצר אוטומטית).",
    },
    {
        "name": FIELD_PK_DATE,
        "type": "date",
        "description": "תאריך של חילוץ ידע מוצר (נוצר אוטומטית).",
        "options": {
            "dateFormat": {"name": "iso"},
        },
    },
]


def _fields_meta_url(base_id: str, table_id: str) -> str:
    return f"https://api.airtable.com/v0/meta/bases/{base_id}/tables/{table_id}/fields"


def create_airtable_field(api_key: str, base_id: str, table_id: str, spec: dict) -> dict:
    """יוצר שדה חדש ב-Airtable via Meta API. דורש scope: schema.bases:write."""
    resp = requests.post(
        _fields_meta_url(base_id, table_id),
        headers=_airtable_headers(api_key),
        json=spec,
    )
    if resp.status_code == 403:
        raise RuntimeError(
            f"יצירת שדה '{spec['name']}' נחסמה (403). "
            f"למפתח ה-Airtable שלך אין הרשאת schema.bases:write. "
            f"פתרון: ערוכי את ה-Personal Access Token ב-Airtable "
            f"(https://airtable.com/create/tokens) והוסיפי את ה-scope הזה, "
            f"או צרי את 4 השדות ידנית ב-UI של Airtable."
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"יצירת שדה '{spec['name']}' נכשלה ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def update_singleselect_choices(api_key: str, base_id: str, table_id: str,
                                field_id: str, all_choice_names: list[str]) -> None:
    """מעדכן רשימת אופציות ב-single select (שומר קיימות ומוסיף חדשות)."""
    url = f"{_fields_meta_url(base_id, table_id)}/{field_id}"
    body = {"options": {"choices": [{"name": c} for c in all_choice_names]}}
    resp = requests.patch(url, headers=_airtable_headers(api_key), json=body)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"עדכון אופציות של שדה {field_id} נכשל ({resp.status_code}): {resp.text}"
        )


def ensure_required_fields(api_key: str, base_id: str, table_id: str) -> None:
    """
    שלב א׳: מאמת ששדות הבסיס (תמלול, שם, חילוץ_סטטוס, חילוץ_תגובה_למחיר_JSON) קיימים —
            אלו שדות שבשליטת המשתמשת ולא ניצור אוטומטית.
    שלב ב׳: 4 שדות ה-PK (חילוץ_ידע_מוצר_*) — אם חסרים, יוצר אותם via Airtable Meta API.
    שלב ג׳: אם FIELD_PK_STATUS קיים אבל חסרות בו אופציות — מוסיף אותן.
    """
    existing = get_existing_fields(api_key, base_id, table_id)

    # שלב א׳ — שדות בסיס חייבים להיות קיימים מראש
    base_must_exist = [
        (TRANSCRIPT_FIELD_NAME, "קריאת תמלולים"),
        (NAME_FIELD, "שם המועמד"),
        (MAIN_EXTRACTION_STATUS_FIELD, "פילטור על הצלחת חילוץ ראשי"),
        (PRICE_JSON_FIELD, "פילטור שיחות פיבוט"),
    ]
    missing_base = [(n, r) for n, r in base_must_exist if n not in existing]
    if missing_base:
        lines = ["❌ שדות בסיס חסרים ב-Airtable (הסקריפט לא יוצר אותם — צרי ידנית):"]
        for name, reason in missing_base:
            lines.append(f"   • '{name}' — נחוץ ל: {reason}")
        raise RuntimeError("\n".join(lines))

    # שלב ב׳ — שדות PK: יצירה אם חסרים
    created_count = 0
    for spec in PK_FIELD_SPECS:
        name = spec["name"]
        if name in existing:
            print(f"   ✓ שדה '{name}' כבר קיים")
            continue
        print(f"   ⚙️  יוצרת שדה '{name}' (type={spec['type']})...")
        created = create_airtable_field(api_key, base_id, table_id, spec)
        existing[name] = created
        created_count += 1
        print(f"   ✅ '{name}' נוצר")

    if created_count > 0:
        print(f"\n   🎉 נוצרו {created_count} שדות חדשים ב-Airtable\n")

    # שלב ג׳ — אימות אופציות FIELD_PK_STATUS
    status_field = existing[FIELD_PK_STATUS]
    if status_field.get("type") != "singleSelect":
        raise RuntimeError(
            f"השדה '{FIELD_PK_STATUS}' קיים אך סוגו {status_field.get('type')} "
            f"(צריך singleSelect). ערוכי/מחקי ידנית ב-Airtable ונסי שוב."
        )
    existing_choices = {c["name"] for c in
                        status_field.get("options", {}).get("choices", [])}
    missing_choices = [opt for opt in REQUIRED_STATUS_OPTIONS if opt not in existing_choices]
    if missing_choices:
        print(f"   ⚙️  מוסיפה אופציות חסרות ל-'{FIELD_PK_STATUS}': {missing_choices}")
        merged = list(existing_choices | set(REQUIRED_STATUS_OPTIONS))
        update_singleselect_choices(
            api_key, base_id, table_id, status_field["id"], merged,
        )
        print(f"   ✅ אופציות עודכנו")


# alias לתאימות לאחור — הקריאות הישנות בקוד מפנות לכאן
def verify_required_fields(api_key: str, base_id: str, table_id: str) -> None:
    ensure_required_fields(api_key, base_id, table_id)


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


def update_record(api_key: str, base_id: str, table_id: str,
                  record_id: str, fields: dict) -> None:
    url = f"{_records_url(base_id, table_id)}/{record_id}"
    resp = requests.patch(url, headers=_airtable_headers(api_key),
                          json={"fields": fields})
    if resp.status_code >= 400:
        raise RuntimeError(f"עדכון שורה {record_id} נכשל ({resp.status_code}): {resp.text}")


# =============================================================================
# פילטרים
# =============================================================================

def filter_main_success_and_not_already_done(records: list[dict]) -> tuple[list[dict], int, int]:
    """
    מחזיר (candidates, skipped_no_main_success, skipped_already_done).
    - candidates: חילוץ_סטטוס == הצליח וגם חילוץ_ידע_מוצר_סטטוס != הצליח.
    - idempotent: שיחה שכבר הצליחה בחילוץ המוצר — נדלגת. נכשלת/ממתינה — רצה שוב.
    """
    candidates = []
    skipped_no_main = 0
    skipped_already_done = 0
    for r in records:
        f = r.get("fields", {})
        if f.get(MAIN_EXTRACTION_STATUS_FIELD) != MAIN_STATUS_SUCCESS:
            skipped_no_main += 1
            continue
        if f.get(FIELD_PK_STATUS) == STATUS_SUCCESS:
            skipped_already_done += 1
            continue
        candidates.append(r)
    return candidates, skipped_no_main, skipped_already_done


def filter_out_pivot_prices(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    מסנן החוצה שיחות פיבוט שמחירן 12,900.
    מזהה דרך parse של price JSON → price_quote_verbatim.
    Fallback: חיפוש בטקסט הגולמי.
    מחזיר (kept, removed_details).
    """
    kept: list[dict] = []
    removed: list[dict] = []
    for r in records:
        f = r.get("fields", {})
        price_json_str = (f.get(PRICE_JSON_FIELD) or "").strip()
        is_pivot = False
        quote_found = ""
        if price_json_str:
            try:
                price_data = json.loads(price_json_str)
                quote = str(price_data.get("price_quote_verbatim") or "")
                if any(m in quote for m in PIVOT_PRICE_MARKERS):
                    is_pivot = True
                    quote_found = quote
            except (json.JSONDecodeError, TypeError):
                if any(m in price_json_str for m in PIVOT_PRICE_MARKERS):
                    is_pivot = True
                    quote_found = "(JSON parse נכשל — נמצא בטקסט הגולמי)"
        if is_pivot:
            removed.append({
                "record_id": r["id"],
                "name": f.get(NAME_FIELD) or "אנונימי",
                "quote": quote_found,
            })
        else:
            kept.append(r)
    return kept, removed


# =============================================================================
# Claude — streaming + retry + ולידציה
# =============================================================================

def call_claude_streaming(client: Anthropic, transcript: str) -> tuple[str, dict, str]:
    """
    קריאה אחת ל-Claude ב-streaming. מחזיר (text, usage_dict, stop_reason).
    streaming חובה עם max_tokens=16000 — ה-SDK חוסם non-streaming ארוך.
    """
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


def validate_extraction_output(raw_text: str) -> tuple[dict | None, str | None]:
    """מחזיר (parsed_dict, error_msg). חייב לכלול את כל המפתחות הדרושים + סוגים."""
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error: {exc}"

    if not isinstance(parsed, dict):
        return None, f"שורש ה-JSON אינו object אלא {type(parsed).__name__}"

    missing = [k for k in REQUIRED_ROOT_KEYS if k not in parsed]
    if missing:
        return None, f"חסרים מפתחות ראשיים: {missing}"

    # ולידציה בסיסית של סוגים
    for key in ["product_facts_stated", "explicit_promises",
                "explicit_disclaimers", "unique_framings"]:
        if not isinstance(parsed[key], list):
            return None, f"'{key}' חייב להיות array, לא {type(parsed[key]).__name__}"

    if not isinstance(parsed["meta"], dict):
        return None, f"'meta' חייב להיות object, לא {type(parsed['meta']).__name__}"

    return parsed, None


# =============================================================================
# עיבוד שורה בודדת
# =============================================================================

def count_words(text: str) -> int:
    return len(text.split()) if text else 0


def get_record_name(record: dict) -> str:
    return record.get("fields", {}).get(NAME_FIELD) or "אנונימי"


def get_record_transcript(record: dict) -> str:
    return record.get("fields", {}).get(TRANSCRIPT_FIELD_NAME, "") or ""


def write_result_to_airtable(api_key: str, base_id: str, table_id: str,
                             record_id: str, status: str,
                             extraction_json: str | None = None,
                             error_text: str | None = None) -> None:
    today_iso = datetime.now(timezone.utc).date().isoformat()
    fields: dict[str, Any] = {
        FIELD_PK_STATUS: status,
        FIELD_PK_DATE: today_iso,
    }
    if extraction_json is not None:
        fields[FIELD_PK_JSON] = extraction_json
    if error_text is not None:
        fields[FIELD_PK_ERROR] = error_text
    update_record(api_key, base_id, table_id, record_id, fields)


def _compact_counts(parsed: dict) -> dict[str, int]:
    return {
        "facts": len(parsed.get("product_facts_stated", []) or []),
        "promises": len(parsed.get("explicit_promises", []) or []),
        "disclaimers": len(parsed.get("explicit_disclaimers", []) or []),
        "framings": len(parsed.get("unique_framings", []) or []),
    }


def process_record(client: Anthropic, record: dict, idx: int, total: int,
                   api_key: str, base_id: str, table_id: str,
                   stats: Stats) -> None:
    record_id = record["id"]
    name = get_record_name(record)
    transcript = get_record_transcript(record)
    word_count = count_words(transcript)

    result = RecordResult(record_id=record_id, name=name, status=STATUS_PENDING)

    # שלב 1 — סינון תמלול ריק
    if not transcript.strip() or word_count < MIN_WORDS:
        err_msg = f"תמלול ריק או קצר מ-{MIN_WORDS} מילים (בפועל: {word_count})"
        log.info(f"[{idx}/{total}] {name} ({word_count} מילים) → דולג: תמלול קצר")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAILED,
            error_text=err_msg,
        )
        result.status = STATUS_FAILED
        result.error = err_msg
        stats.skipped_empty += 1
        stats.results.append(result)
        return

    # שלב 2 — קריאה ל-Claude
    start = time.monotonic()
    try:
        raw, usage, stop_reason = call_claude_with_api_retry(client, transcript)
    except Exception as exc:
        elapsed = time.monotonic() - start
        log.error(f"[{idx}/{total}] {name} ({word_count:,} מילים) → נכשל API "
                  f"אחרי {elapsed:.1f}s: {exc}")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAILED,
            error_text=f"API error: {exc}"[:5000],
        )
        result.status = STATUS_FAILED
        result.error = str(exc)[:5000]
        result.duration_seconds = elapsed
        stats.failed += 1
        stats.results.append(result)
        return

    result.duration_seconds = time.monotonic() - start
    result.input_tokens = usage["input_tokens"]
    result.output_tokens = usage["output_tokens"]
    result.stop_reason = stop_reason
    stats.total_input_tokens += usage["input_tokens"]
    stats.total_output_tokens += usage["output_tokens"]

    # שלב 3 — ולידציה
    parsed, err = validate_extraction_output(raw)

    if parsed is None:
        log.warning(f"[{idx}/{total}] {name} → JSON לא תקין (ניסיון 1): {err}. מנסה שוב...")
        try:
            raw2, usage2, stop_reason2 = call_claude_with_api_retry(client, transcript)
            result.input_tokens += usage2["input_tokens"]
            result.output_tokens += usage2["output_tokens"]
            stats.total_input_tokens += usage2["input_tokens"]
            stats.total_output_tokens += usage2["output_tokens"]
            parsed, err = validate_extraction_output(raw2)
            if parsed is not None:
                raw = raw2
                result.stop_reason = stop_reason2
        except Exception as exc:
            log.error(f"[{idx}/{total}] {name} → נכשל בניסיון שני: {exc}")
            write_result_to_airtable(
                api_key, base_id, table_id, record_id,
                status=STATUS_FAILED,
                error_text=f"API error (ניסיון 2): {exc}"[:5000],
            )
            result.status = STATUS_FAILED
            result.error = str(exc)[:5000]
            stats.failed += 1
            stats.results.append(result)
            return

    if parsed is None:
        log.error(f"[{idx}/{total}] {name} → JSON לא תקין גם בניסיון שני: {err}")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAILED,
            error_text=f"{err}\n\n--- raw output ---\n{raw}"[:50000],
        )
        result.status = STATUS_FAILED
        result.error = err
        stats.failed += 1
        stats.results.append(result)
        return

    # הצליח
    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    counts = _compact_counts(parsed)
    cost_usd = (result.input_tokens * PRICE_INPUT_PER_M
                + result.output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000

    # אזהרה אם הפלט נחתך
    trunc_warn = ""
    if result.stop_reason == "max_tokens":
        trunc_warn = " ⚠️  stop_reason=max_tokens!"

    log.info(
        f"[{idx}/{total}] {name} ({word_count:,} מילים) → הצליח "
        f"ב-{result.duration_seconds:.1f}s | "
        f"facts={counts['facts']} promises={counts['promises']} "
        f"disclaimers={counts['disclaimers']} framings={counts['framings']} | "
        f"tokens: in={result.input_tokens:,} out={result.output_tokens:,} | "
        f"עלות: ${cost_usd:.3f}{trunc_warn}"
    )

    write_result_to_airtable(
        api_key, base_id, table_id, record_id,
        status=STATUS_SUCCESS,
        extraction_json=pretty,
        error_text="",
    )
    result.status = STATUS_SUCCESS
    result.parsed = parsed
    stats.succeeded += 1
    stats.results.append(result)


# =============================================================================
# Pipeline
# =============================================================================

def build_filter_report(all_records: list[dict]) -> tuple[list[dict], Stats]:
    """מחזיר (candidates_after_all_filters, stats_with_filter_info)."""
    stats = Stats()

    # פילטר 1: חילוץ ראשי הצליח + חילוץ מוצר לא הצליח
    candidates, skipped_no_main, skipped_done = filter_main_success_and_not_already_done(all_records)
    stats.skipped_already_done = skipped_done
    log.info(f"שורות עם חילוץ ראשי מוצלח ושעוד לא עבדו: {len(candidates)} "
             f"(דולגים {skipped_no_main} ללא חילוץ ראשי מוצלח, "
             f"{skipped_done} שכבר הושלמו).")

    # פילטר 2: סינון פיבוט
    candidates, pivot_removed = filter_out_pivot_prices(candidates)
    stats.skipped_pivot = len(pivot_removed)
    stats.pivot_details = pivot_removed
    if pivot_removed:
        log.info(f"סוננו {len(pivot_removed)} שיחות פיבוט (מחיר 12,900):")
        for item in pivot_removed:
            q_preview = (item["quote"] or "")[:100].replace("\n", " ")
            log.info(f"   • {item['name']} ({item['record_id']}) | {q_preview!r}")

    stats.total_candidates = len(candidates)
    log.info(f"✅ נשארו לעיבוד: {len(candidates)} שיחות.")

    return candidates, stats


def run_dry(airtable_key: str, base_id: str, table_id: str,
            anthropic_key: str) -> int:
    """מצב dry-run: שליפה + פילטור + ספירת טוקנים משוערת. בלי קריאות API."""
    log.info("מצב: --dry-run")

    log.info("מאמת ששדות החילוץ קיימים ב-Airtable...")
    verify_required_fields(airtable_key, base_id, table_id)
    log.info("✅ כל השדות הדרושים קיימים.")

    log.info("שולף שורות מ-Airtable...")
    records = list_all_records(airtable_key, base_id, table_id)
    log.info(f"נמצאו {len(records)} שורות בטבלה.")

    candidates, stats = build_filter_report(records)

    if not candidates:
        log.warning("אין שיחות לעיבוד.")
        print_dry_summary(stats, estimated_tokens=None)
        return 0

    # ספירת טוקנים משוערת — דרך Anthropic count_tokens, בלי קריאה אמיתית
    log.info("סופר טוקנים משוערים לכל התמלולים (count_tokens endpoint — חינם)...")
    client = Anthropic(api_key=anthropic_key)

    total_input = 0
    for i, rec in enumerate(candidates, start=1):
        transcript = get_record_transcript(rec)
        name = get_record_name(rec)
        words = count_words(transcript)
        if not transcript.strip() or words < MIN_WORDS:
            log.info(f"   [{i}/{len(candidates)}] {name}: תמלול ריק/קצר ({words} מילים) — ידלג")
            continue
        user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
        try:
            resp = client.messages.count_tokens(
                model=CLAUDE_MODEL,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            tokens = resp.input_tokens
            total_input += tokens
            log.info(f"   [{i}/{len(candidates)}] {name}: {tokens:,} tokens")
        except Exception as exc:
            log.warning(f"   [{i}/{len(candidates)}] {name}: count_tokens נכשל ({exc})")

    print_dry_summary(stats, estimated_tokens=total_input)
    return 0


def print_dry_summary(stats: Stats, estimated_tokens: int | None) -> None:
    print()
    print("=" * 70)
    print("  סיכום Dry-Run — חילוץ ידע מוצר")
    print("=" * 70)
    print(f"  שיחות כבר הושלמו (דולגות)    : {stats.skipped_already_done}")
    print(f"  שיחות פיבוט סוננו            : {stats.skipped_pivot}")
    print(f"  שיחות לעיבוד בפועל           : {stats.total_candidates}")
    if estimated_tokens is not None:
        print(f"  סך טוקני קלט משוערים         : {estimated_tokens:,}")
        # עלות עם max_tokens שלם ע"פ שיחה — תקרה שמרנית
        max_out_total = stats.total_candidates * CLAUDE_MAX_TOKENS
        in_cost = estimated_tokens * PRICE_INPUT_PER_M / 1_000_000
        out_cost = max_out_total * PRICE_OUTPUT_PER_M / 1_000_000
        total_cost = in_cost + out_cost
        print(f"  עלות קלט משוערת              : ${in_cost:.2f}")
        print(f"  עלות פלט מקסימלית            : ${out_cost:.2f}  "
              f"(אם כל תשובה מגיעה ל-{CLAUDE_MAX_TOKENS:,} tokens — תקרה לא ריאליסטית)")
        print(f"  תקרת עלות כוללת              : ${total_cost:.2f}  (~₪{total_cost * USD_TO_ILS:.2f})")
        # הערכה ריאליסטית של פלט: ~3K tokens ממוצע לשיחה
        realistic_out = stats.total_candidates * 3000
        real_out_cost = realistic_out * PRICE_OUTPUT_PER_M / 1_000_000
        real_total = in_cost + real_out_cost
        print(f"  הערכה ריאליסטית (3K פלט/שיחה): ${real_total:.2f}  (~₪{real_total * USD_TO_ILS:.2f})")
    print("=" * 70)
    print()
    print("להרצה אמיתית:")
    print(f"    python3 {Path(__file__).name} --run")
    print()


def run_full(anthropic_key: str, airtable_key: str,
             base_id: str, table_id: str) -> Stats:
    log.info("מצב: --run (הרצה אמיתית מול API)")

    log.info("מאמת ששדות החילוץ קיימים ב-Airtable...")
    verify_required_fields(airtable_key, base_id, table_id)
    log.info("✅ כל השדות הדרושים קיימים.")

    log.info("שולף שורות מ-Airtable...")
    records = list_all_records(airtable_key, base_id, table_id)
    log.info(f"נמצאו {len(records)} שורות בטבלה.")

    candidates, stats = build_filter_report(records)

    if not candidates:
        log.warning("אין שיחות לעיבוד.")
        return stats

    client = Anthropic(api_key=anthropic_key)

    for i, record in enumerate(candidates, start=1):
        try:
            process_record(client, record, i, len(candidates),
                           airtable_key, base_id, table_id, stats)
        except Exception as exc:
            log.exception(f"[{i}/{len(candidates)}] שגיאה לא צפויה: {exc}")
            try:
                write_result_to_airtable(
                    airtable_key, base_id, table_id, record["id"],
                    status=STATUS_FAILED,
                    error_text=f"שגיאה לא צפויה: {exc}"[:5000],
                )
                stats.failed += 1
            except Exception:
                pass

        if i < len(candidates):
            time.sleep(SLEEP_BETWEEN_RECORDS)

    return stats


# =============================================================================
# דוחות וסיכומים
# =============================================================================

def print_run_summary(stats: Stats) -> None:
    print()
    print("=" * 70)
    print("  סיכום הרצה — חילוץ ידע מוצר")
    print("=" * 70)
    print(f"  שיחות שנבחרו לעיבוד       : {stats.total_candidates}")
    print(f"  הצליחו                    : {stats.succeeded}")
    print(f"  נכשלו                     : {stats.failed}")
    print(f"  דילוג — תמלול קצר/ריק     : {stats.skipped_empty}")
    print(f"  דילוג — כבר הושלמו קודם   : {stats.skipped_already_done}")
    print(f"  דילוג — שיחות פיבוט       : {stats.skipped_pivot}")
    print("-" * 70)
    print(f"  סך טוקני קלט              : {stats.total_input_tokens:,}")
    print(f"  סך טוקני פלט              : {stats.total_output_tokens:,}")
    cost = stats.total_cost_usd()
    print(f"  עלות כוללת                : ${cost:.3f}  (~₪{cost * USD_TO_ILS:.2f})")
    if stats.results:
        print(f"  זמן ממוצע לשיחה           : {stats.avg_duration():.1f} שניות")
    print("=" * 70)
    print()

    # טבלה קומפקטית
    if stats.results:
        print("📋 סיכום קומפקטי:")
        print("-" * 70)
        print(f"{'#':<3} {'שם':<22} {'סטטוס':<10} {'in_tok':<10} {'out_tok':<10} {'שניות':<8}")
        print("-" * 70)
        for i, r in enumerate(stats.results, start=1):
            name_short = r.name[:20] if r.name else "?"
            print(f"{i:<3} {name_short:<22} {r.status:<10} "
                  f"{r.input_tokens:<10,} {r.output_tokens:<10,} "
                  f"{r.duration_seconds:<8.1f}")
        print("-" * 70)
    print()


def save_backup(stats: Stats) -> Path:
    """שמירת גיבוי מקומי של כל הפלטים."""
    backup_path = SCRIPT_DIR / f"product_knowledge_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": CLAUDE_MODEL,
        "total_candidates": stats.total_candidates,
        "succeeded": stats.succeeded,
        "failed": stats.failed,
        "skipped_empty": stats.skipped_empty,
        "skipped_already_done": stats.skipped_already_done,
        "skipped_pivot": stats.skipped_pivot,
        "pivot_details": stats.pivot_details,
        "total_input_tokens": stats.total_input_tokens,
        "total_output_tokens": stats.total_output_tokens,
        "total_cost_usd": round(stats.total_cost_usd(), 4),
        "avg_duration_seconds": round(stats.avg_duration(), 2),
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
                "parsed": r.parsed,
            }
            for r in stats.results
        ],
    }
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    log.info(f"גיבוי מקומי נשמר: {backup_path}")
    return backup_path


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="חילוץ ידע מוצר מתמלולי ראיונות קבלה, מ-Airtable עם Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""דוגמאות:
    python3 extract_product_knowledge.py --dry-run  # ספירה + עלות, בלי API
    python3 extract_product_knowledge.py --run      # הרצה אמיתית (idempotent)""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="שליפה + פילטור + ספירת טוקנים. ללא קריאה ל-API.")
    group.add_argument("--run", action="store_true",
                       help="הרצה אמיתית, idempotent על כל מי שעוד לא הצליח.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    load_dotenv(SCRIPT_DIR / ".env")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    airtable_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_id = os.getenv("AIRTABLE_TABLE_ID")

    missing = [name for name, val in [
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("AIRTABLE_API_KEY", airtable_key),
        ("AIRTABLE_BASE_ID", base_id),
        ("AIRTABLE_TABLE_ID", table_id),
    ] if not val]
    if missing:
        log.error(f"חסרים משתני סביבה: {missing}. הגדירי אותם ב-.env.")
        return 2

    try:
        if args.dry_run:
            return run_dry(airtable_key, base_id, table_id, anthropic_key)

        stats = run_full(anthropic_key, airtable_key, base_id, table_id)
    except KeyboardInterrupt:
        log.warning("הרצה הופסקה ידנית.")
        return 130
    except Exception as exc:
        log.exception(f"שגיאה כללית: {exc}")
        return 1

    print_run_summary(stats)
    save_backup(stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())


# =============================================================================
# דוגמת שימוש
# =============================================================================
# 1. dry-run קודם:
#    python3 extract_product_knowledge.py --dry-run
#    → מדפיס כמה שיחות נשארו, כמה טוקני קלט, ועלות משוערת.
#
# 2. הרצה אמיתית:
#    python3 extract_product_knowledge.py --run
#    → רץ על כל מי שעוד לא הצליח, שומר ל-Airtable + גיבוי מקומי.
#
# 3. אם הרצה נקטעה באמצע:
#    python3 extract_product_knowledge.py --run
#    → idempotent. רק שיחות שעוד לא הצליחו יטופלו.
