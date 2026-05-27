#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_interviews.py — חילוץ ראיונות קבלה "טירונות סוכנים" מ-Airtable.

נבנה לפי המפרט: "מפרט בניית סקריפט חילוץ שיחות — טירונות סוכנים".

מצבי הרצה:
    python3 extract_interviews.py --pilot   # 5 שיחות אקראיות, מדפיס JSON, מחכה לאישור
    python3 extract_interviews.py --full    # כל השורות שעדיין לא עובדו (idempotent)

דרישות סביבה (.env):
    ANTHROPIC_API_KEY        — מפתח Anthropic
    AIRTABLE_API_KEY         — Personal Access Token של Airtable
    AIRTABLE_BASE_ID         — ה-Base ID
    AIRTABLE_TABLE_ID        — ה-Table ID של טבלת השיחות

הסקריפט:
    1. מאמת/יוצר 4 שדות חדשים: חילוץ_JSON, חילוץ_סטטוס, חילוץ_שגיאה, חילוץ_תאריך
    2. סורק את כל השורות, קורא את שדה "תמלול השיחה"
    3. מסנן: ריק או < 500 מילים → דולג_תמלול_ריק
    4. שולח ל-Claude (claude-opus-4-6, temperature=0, max_tokens=8192)
    5. retry: 3 ניסיונות API עם backoff [5, 15, 45] שניות
    6. JSON לא חוקי → ניסיון חוזר אחד; אם נכשל → נכשל_JSON עם הטקסט הגולמי
    7. השהייה של 2 שניות בין קריאות
    8. שומר תוצאה + סטטוס + תאריך חזרה ל-Airtable
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
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
# קבועים — לפי המפרט במדויק
# =============================================================================

CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_TEMPERATURE = 0
CLAUDE_MAX_TOKENS = 8192

MIN_WORDS = 500
SLEEP_BETWEEN_RECORDS = 2.0  # שניות בין שורות (rate limiting)
API_RETRY_DELAYS = [5, 15, 45]  # exponential backoff בשניות
PILOT_SAMPLE_SIZE = 5

# שם השדה של התמלול בטבלה (מאושר מול המשתמשת)
TRANSCRIPT_FIELD_NAME = "תמלול השיחה"

# שמות 4 השדות שהסקריפט יוצר/מעדכן
FIELD_EXTRACTION_JSON = "חילוץ_JSON"
FIELD_EXTRACTION_STATUS = "חילוץ_סטטוס"
FIELD_EXTRACTION_ERROR = "חילוץ_שגיאה"
FIELD_EXTRACTION_DATE = "חילוץ_תאריך"

# סטטוסים אפשריים (Single select options)
STATUS_SUCCESS = "הצליח"
STATUS_FAIL_API = "נכשל_API"
STATUS_FAIL_JSON = "נכשל_JSON"
STATUS_SKIPPED_EMPTY = "דולג_תמלול_ריק"
STATUS_IN_PROGRESS = "בטיפול"

ALL_STATUS_OPTIONS = [
    STATUS_SUCCESS,
    STATUS_FAIL_API,
    STATUS_FAIL_JSON,
    STATUS_SKIPPED_EMPTY,
    STATUS_IN_PROGRESS,
]

# סטטוסים שאומרים "אל תרוץ שוב על השורה הזו במצב --full"
DONE_STATUSES = {STATUS_SUCCESS, STATUS_SKIPPED_EMPTY}

# 8 המפתחות הראשיים שחובה שיופיעו ב-JSON שחוזר מ-Claude
REQUIRED_ROOT_KEYS = [
    "meta",
    "classification",
    "door_1_language",
    "door_2_use_cases",
    "door_3_objections",
    "door_4_energy_shifts",
    "surprises_and_anomalies",
    "open_notes_for_synthesis",
]

# נתיבים
SCRIPT_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = SCRIPT_DIR / "prompts" / "extract_interview_system.md"
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# =============================================================================
# Logging
# =============================================================================

def setup_logging() -> logging.Logger:
    """מגדיר logger שמדפיס ל-stdout וגם לקובץ ב-logs/."""
    logger = logging.getLogger("extract_interviews")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = LOGS_DIR / f"extract_interviews_{datetime.now():%Y%m%d_%H%M%S}.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = setup_logging()


# =============================================================================
# Stats
# =============================================================================

@dataclass
class Stats:
    total_candidates: int = 0
    succeeded: int = 0
    failed_api: int = 0
    failed_json: int = 0
    skipped_empty: int = 0
    skipped_already_done: int = 0
    durations: list[float] = field(default_factory=list)

    def avg_duration(self) -> float:
        return sum(self.durations) / len(self.durations) if self.durations else 0.0


# =============================================================================
# Airtable — Meta API (לוודא/ליצור שדות)
# =============================================================================

def _airtable_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _meta_tables_url(base_id: str) -> str:
    return f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"


def _meta_fields_url(base_id: str, table_id: str) -> str:
    return f"https://api.airtable.com/v0/meta/bases/{base_id}/tables/{table_id}/fields"


def _records_url(base_id: str, table_id: str) -> str:
    return f"https://api.airtable.com/v0/{base_id}/{table_id}"


def get_existing_fields(api_key: str, base_id: str, table_id: str) -> dict[str, dict]:
    """מחזיר {field_name: field_object} עבור כל השדות בטבלה."""
    resp = requests.get(_meta_tables_url(base_id), headers=_airtable_headers(api_key))
    resp.raise_for_status()
    data = resp.json()
    for table in data.get("tables", []):
        if table.get("id") == table_id:
            return {f["name"]: f for f in table.get("fields", [])}
    raise RuntimeError(f"טבלה {table_id} לא נמצאה בבסיס {base_id}")


def create_field(api_key: str, base_id: str, table_id: str, payload: dict) -> dict:
    """יוצר שדה חדש בטבלה דרך Meta API."""
    resp = requests.post(
        _meta_fields_url(base_id, table_id),
        headers=_airtable_headers(api_key),
        json=payload,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"יצירת שדה נכשלה ({resp.status_code}): {resp.text}")
    return resp.json()


def update_field(api_key: str, base_id: str, table_id: str, field_id: str, payload: dict) -> dict:
    """מעדכן שדה קיים (למשל הוספת אופציות ל-Single select)."""
    resp = requests.patch(
        f"{_meta_fields_url(base_id, table_id)}/{field_id}",
        headers=_airtable_headers(api_key),
        json=payload,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"עדכון שדה נכשל ({resp.status_code}): {resp.text}")
    return resp.json()


def ensure_extraction_fields(api_key: str, base_id: str, table_id: str) -> dict[str, str]:
    """
    מאמת שכל 4 שדות החילוץ קיימים. יוצר אותם אם לא.
    מחזיר {field_name: field_id}.
    """
    existing = get_existing_fields(api_key, base_id, table_id)

    # ודא שהשדה של התמלול קיים
    if TRANSCRIPT_FIELD_NAME not in existing:
        raise RuntimeError(
            f"שדה התמלול '{TRANSCRIPT_FIELD_NAME}' לא נמצא בטבלה. "
            "ודאי שהשם נכון או שהתמלולים הועלו."
        )

    field_ids: dict[str, str] = {TRANSCRIPT_FIELD_NAME: existing[TRANSCRIPT_FIELD_NAME]["id"]}

    # 1. חילוץ_JSON — Long text
    if FIELD_EXTRACTION_JSON in existing:
        field_ids[FIELD_EXTRACTION_JSON] = existing[FIELD_EXTRACTION_JSON]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_EXTRACTION_JSON}' (Long text)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_EXTRACTION_JSON,
            "type": "multilineText",
        })
        field_ids[FIELD_EXTRACTION_JSON] = created["id"]

    # 2. חילוץ_סטטוס — Single select עם 5 אופציות
    status_options = [{"name": opt} for opt in ALL_STATUS_OPTIONS]
    if FIELD_EXTRACTION_STATUS in existing:
        existing_status = existing[FIELD_EXTRACTION_STATUS]
        field_ids[FIELD_EXTRACTION_STATUS] = existing_status["id"]
        # ודא שכל האופציות קיימות
        existing_choices = {c["name"] for c in
                            existing_status.get("options", {}).get("choices", [])}
        missing = [opt for opt in ALL_STATUS_OPTIONS if opt not in existing_choices]
        if missing:
            log.info(f"מוסיף אופציות חסרות לשדה '{FIELD_EXTRACTION_STATUS}': {missing}")
            all_choices = [{"name": c["name"]} for c in
                           existing_status.get("options", {}).get("choices", [])]
            all_choices += [{"name": opt} for opt in missing]
            update_field(api_key, base_id, table_id,
                         existing_status["id"],
                         {"options": {"choices": all_choices}})
    else:
        log.info(f"יוצר שדה '{FIELD_EXTRACTION_STATUS}' (Single select)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_EXTRACTION_STATUS,
            "type": "singleSelect",
            "options": {"choices": status_options},
        })
        field_ids[FIELD_EXTRACTION_STATUS] = created["id"]

    # 3. חילוץ_שגיאה — Long text
    if FIELD_EXTRACTION_ERROR in existing:
        field_ids[FIELD_EXTRACTION_ERROR] = existing[FIELD_EXTRACTION_ERROR]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_EXTRACTION_ERROR}' (Long text)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_EXTRACTION_ERROR,
            "type": "multilineText",
        })
        field_ids[FIELD_EXTRACTION_ERROR] = created["id"]

    # 4. חילוץ_תאריך — Date
    if FIELD_EXTRACTION_DATE in existing:
        field_ids[FIELD_EXTRACTION_DATE] = existing[FIELD_EXTRACTION_DATE]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_EXTRACTION_DATE}' (Date)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_EXTRACTION_DATE,
            "type": "date",
            "options": {"dateFormat": {"name": "iso"}},
        })
        field_ids[FIELD_EXTRACTION_DATE] = created["id"]

    return field_ids


# =============================================================================
# Airtable — Records (קריאה ועדכון)
# =============================================================================

def list_all_records(api_key: str, base_id: str, table_id: str) -> list[dict]:
    """מחזיר את כל השורות בטבלה (כולל pagination)."""
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
    """מעדכן שורה (PATCH) עם שדות לפי שם."""
    url = f"{_records_url(base_id, table_id)}/{record_id}"
    resp = requests.patch(url, headers=_airtable_headers(api_key),
                          json={"fields": fields})
    if resp.status_code >= 400:
        raise RuntimeError(f"עדכון שורה {record_id} נכשל ({resp.status_code}): {resp.text}")


# =============================================================================
# Claude — קריאה + retry + ולידציה
# =============================================================================

USER_MESSAGE_TEMPLATE = """להלן תמלול מלא של ראיון קבלה של שלהבת ורדי עם מועמד/ת לתוכנית טירונות סוכנים.
החזר פלט JSON יחיד לפי הסכמה שהוגדרה ב-system prompt.

---
תמלול:
{TRANSCRIPT_CONTENT}"""


def call_claude(client: Anthropic, system_prompt: str, transcript: str) -> str:
    """קריאה אחת ל-Claude. מחזיר את ה-text. מעיף חריגה אם API נכשל."""
    user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    # מאחד את כל בלוקי הטקסט
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts).strip()


def call_claude_with_api_retry(client: Anthropic, system_prompt: str,
                               transcript: str) -> str:
    """
    3 ניסיונות API עם backoff [5, 15, 45] שניות.
    מעיף חריגה רק אם כל 3 הניסיונות נכשלו.
    """
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            return call_claude(client, system_prompt, transcript)
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
    """מסיר ```json ...``` אם המודל בכל זאת עטף — defensive בלבד."""
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text.strip()


def validate_extraction_output(raw_text: str) -> tuple[dict | None, str | None]:
    """
    מנסה לפרסר את הפלט ל-JSON ולוודא 8 מפתחות ראשיים.
    מחזיר (parsed_dict, error_msg). ב-success: (dict, None). בכישלון: (None, msg).
    """
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

    return parsed, None


# =============================================================================
# עיבוד שורה בודדת
# =============================================================================

def count_words(text: str) -> int:
    """ספירת מילים פשוטה מבוססת רווחים."""
    return len(text.split()) if text else 0


def get_record_status(record: dict) -> str | None:
    """מחזיר את ערך השדה חילוץ_סטטוס בשורה (None אם ריק)."""
    return record.get("fields", {}).get(FIELD_EXTRACTION_STATUS)


def get_record_transcript(record: dict) -> str:
    """מחזיר את תוכן שדה התמלול. מחרוזת ריקה אם השדה חסר."""
    return record.get("fields", {}).get(TRANSCRIPT_FIELD_NAME, "") or ""


def write_result_to_airtable(api_key: str, base_id: str, table_id: str,
                             record_id: str, status: str,
                             extraction_json: str | None = None,
                             error_text: str | None = None) -> None:
    """שומר את התוצאה (JSON / סטטוס / שגיאה / תאריך) לשורה."""
    today_iso = datetime.now(timezone.utc).date().isoformat()
    fields: dict[str, Any] = {
        FIELD_EXTRACTION_STATUS: status,
        FIELD_EXTRACTION_DATE: today_iso,
    }
    if extraction_json is not None:
        fields[FIELD_EXTRACTION_JSON] = extraction_json
    if error_text is not None:
        fields[FIELD_EXTRACTION_ERROR] = error_text
    update_record(api_key, base_id, table_id, record_id, fields)


def process_record(client: Anthropic, system_prompt: str,
                   record: dict, idx: int, total: int,
                   api_key: str, base_id: str, table_id: str,
                   stats: Stats, print_json_to_console: bool = False) -> None:
    """
    מעבד שורה אחת:
        1. בודק תמלול
        2. אם קצר מדי / ריק → דולג_תמלול_ריק
        3. אחרת — שולח ל-Claude עם retry
        4. ולידציה של JSON
        5. כותב חזרה ל-Airtable
    """
    record_id = record["id"]
    transcript = get_record_transcript(record)
    word_count = count_words(transcript)

    # --- שלב 1: סינון לפי אורך ---
    if not transcript.strip() or word_count < MIN_WORDS:
        log.info(f"[{idx}/{total}] {record_id} ({word_count} מילים) → {STATUS_SKIPPED_EMPTY}")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_SKIPPED_EMPTY,
            error_text=f"תמלול ריק או קצר מ-{MIN_WORDS} מילים (בפועל: {word_count})",
        )
        stats.skipped_empty += 1
        return

    # --- שלב 2: קריאה ל-Claude עם 3 ניסיונות ---
    start = time.monotonic()
    try:
        raw = call_claude_with_api_retry(client, system_prompt, transcript)
    except Exception as exc:
        elapsed = time.monotonic() - start
        log.error(f"[{idx}/{total}] {record_id} ({word_count:,} מילים) → {STATUS_FAIL_API} "
                  f"אחרי {elapsed:.1f}s: {exc}")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAIL_API,
            error_text=str(exc)[:5000],
        )
        stats.failed_api += 1
        return

    # --- שלב 3: ולידציה של JSON ---
    parsed, err = validate_extraction_output(raw)

    # אם נכשל JSON — ניסיון אחד נוסף
    if parsed is None:
        log.warning(f"[{idx}/{total}] {record_id} → JSON לא חוקי (ניסיון 1): {err}. מנסה שוב...")
        try:
            raw2 = call_claude_with_api_retry(client, system_prompt, transcript)
            parsed, err = validate_extraction_output(raw2)
            if parsed is not None:
                raw = raw2
        except Exception as exc:
            elapsed = time.monotonic() - start
            log.error(f"[{idx}/{total}] {record_id} → {STATUS_FAIL_API} "
                      f"בניסיון JSON שני אחרי {elapsed:.1f}s: {exc}")
            write_result_to_airtable(
                api_key, base_id, table_id, record_id,
                status=STATUS_FAIL_API,
                error_text=str(exc)[:5000],
            )
            stats.failed_api += 1
            return

    elapsed = time.monotonic() - start

    # --- שלב 4: שמירה ---
    if parsed is None:
        log.error(f"[{idx}/{total}] {record_id} ({word_count:,} מילים) → {STATUS_FAIL_JSON} "
                  f"אחרי {elapsed:.1f}s: {err}")
        # שומר את הטקסט הגולמי בשדה השגיאה לדיבוג
        error_payload = f"{err}\n\n--- raw output ---\n{raw}"[:50000]
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAIL_JSON,
            error_text=error_payload,
        )
        stats.failed_json += 1
        return

    # ---- הצליח ----
    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    log.info(f"[{idx}/{total}] מעבד {record_id} ({word_count:,} מילים) → "
             f"{STATUS_SUCCESS} ב-{elapsed:.1f} שניות")

    if print_json_to_console:
        print("─" * 80)
        print(f"📄 {record_id} ({word_count:,} מילים) — {elapsed:.1f}s")
        print("─" * 80)
        print(pretty)
        print()

    write_result_to_airtable(
        api_key, base_id, table_id, record_id,
        status=STATUS_SUCCESS,
        extraction_json=pretty,
        error_text="",  # מנקה שגיאה קודמת אם הייתה
    )
    stats.succeeded += 1
    stats.durations.append(elapsed)


# =============================================================================
# בחירת שורות לעיבוד
# =============================================================================

def filter_candidates(records: list[dict], mode: str) -> tuple[list[dict], int]:
    """
    בחירת שורות לפי מצב:
        --pilot: 5 אקראיות שיש להן תמלול לא ריק (ללא קשר לסטטוס קודם)
        --full:  כל מי שעדיין לא הצליח/דולג
    מחזיר (candidates, skipped_already_done).
    """
    if mode == "pilot":
        with_transcript = [r for r in records if get_record_transcript(r).strip()]
        sample = random.sample(with_transcript,
                               min(PILOT_SAMPLE_SIZE, len(with_transcript)))
        return sample, 0

    if mode == "full":
        candidates = []
        skipped = 0
        for r in records:
            if get_record_status(r) in DONE_STATUSES:
                skipped += 1
            else:
                candidates.append(r)
        return candidates, skipped

    raise ValueError(f"מצב לא ידוע: {mode}")


# =============================================================================
# Pipeline
# =============================================================================

def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(f"קובץ ה-system prompt לא נמצא: {SYSTEM_PROMPT_PATH}")
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def run(mode: str, anthropic_key: str, airtable_key: str,
        base_id: str, table_id: str) -> Stats:
    log.info(f"מצב הרצה: --{mode}")

    # 1. טעינת system prompt
    system_prompt = load_system_prompt()
    log.info(f"system prompt נטען מ-{SYSTEM_PROMPT_PATH.name} "
             f"({len(system_prompt):,} תווים)")

    # 2. ודא שדות
    log.info("מאמת שדות חילוץ ב-Airtable...")
    ensure_extraction_fields(airtable_key, base_id, table_id)

    # 3. שלוף שורות
    log.info("שולף את כל השורות מ-Airtable...")
    records = list_all_records(airtable_key, base_id, table_id)
    log.info(f"נמצאו {len(records)} שורות בטבלה.")

    # 4. בחר מועמדות
    candidates, skipped_done = filter_candidates(records, mode)
    log.info(f"נבחרו {len(candidates)} שורות לעיבוד "
             f"(דולגות {skipped_done} שכבר הושלמו).")

    if not candidates:
        log.warning("אין שורות לעיבוד.")
        return Stats(skipped_already_done=skipped_done)

    # 5. הכן Anthropic client
    client = Anthropic(api_key=anthropic_key)

    # 6. עבד שורה-שורה
    stats = Stats(total_candidates=len(candidates),
                  skipped_already_done=skipped_done)
    print_to_console = (mode == "pilot")

    for i, record in enumerate(candidates, start=1):
        try:
            process_record(client, system_prompt, record, i, len(candidates),
                           airtable_key, base_id, table_id, stats,
                           print_json_to_console=print_to_console)
        except Exception as exc:
            log.exception(f"[{i}/{len(candidates)}] שגיאה לא צפויה ב-{record.get('id')}: {exc}")
            try:
                write_result_to_airtable(
                    airtable_key, base_id, table_id, record["id"],
                    status=STATUS_FAIL_API,
                    error_text=f"שגיאה לא צפויה: {exc}"[:5000],
                )
                stats.failed_api += 1
            except Exception:
                pass

        # rate limiting
        if i < len(candidates):
            time.sleep(SLEEP_BETWEEN_RECORDS)

    return stats


# =============================================================================
# סיכום ודוח
# =============================================================================

def print_summary(stats: Stats, mode: str) -> None:
    print()
    print("=" * 60)
    print(f"  סיכום הרצה — מצב {mode}")
    print("=" * 60)
    print(f"  שורות מועמדות לעיבוד     : {stats.total_candidates}")
    print(f"  הצליח                    : {stats.succeeded}")
    print(f"  נכשל_API                 : {stats.failed_api}")
    print(f"  נכשל_JSON                : {stats.failed_json}")
    print(f"  דולג_תמלול_ריק           : {stats.skipped_empty}")
    if mode == "full":
        print(f"  דולגות (כבר הושלמו קודם) : {stats.skipped_already_done}")
    if stats.durations:
        print(f"  זמן ממוצע לקריאה        : {stats.avg_duration():.1f} שניות")
    print("=" * 60)
    print()


def save_report(stats: Stats, mode: str) -> Path:
    report_path = LOGS_DIR / f"extract_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": CLAUDE_MODEL,
        "total_candidates": stats.total_candidates,
        "succeeded": stats.succeeded,
        "failed_api": stats.failed_api,
        "failed_json": stats.failed_json,
        "skipped_empty": stats.skipped_empty,
        "skipped_already_done": stats.skipped_already_done,
        "avg_duration_seconds": round(stats.avg_duration(), 2),
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    log.info(f"דוח נשמר: {report_path}")
    return report_path


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="חילוץ ראיונות קבלה מ-Airtable עם Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""דוגמאות:
    python3 extract_interviews.py --pilot   # 5 אקראיות
    python3 extract_interviews.py --full    # כל מי שטרם עובד""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pilot", action="store_true",
                       help="הרצה על 5 שורות אקראיות עם הדפסה ל-console.")
    group.add_argument("--full", action="store_true",
                       help="הרצה idempotent על כל השורות שעדיין לא עובדו.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "pilot" if args.pilot else "full"

    # טען .env
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
        stats = run(mode, anthropic_key, airtable_key, base_id, table_id)
    except KeyboardInterrupt:
        log.warning("הרצה הופסקה ידנית.")
        return 130
    except Exception as exc:
        log.exception(f"שגיאה כללית: {exc}")
        return 1

    print_summary(stats, mode)
    save_report(stats, mode)

    # ב-pilot — שאל אם להמשיך ל-full
    if mode == "pilot" and stats.succeeded > 0:
        print()
        print("✅ ה-pilot הסתיים. בדקי את הפלטים ל-5 השורות בטבלה.")
        ans = input("להמשיך עכשיו ל-full על כל שאר השורות? [y/N]: ").strip().lower()
        if ans == "y":
            log.info("מתחיל הרצת --full לפי בקשת המשתמשת...")
            try:
                stats_full = run("full", anthropic_key, airtable_key, base_id, table_id)
                print_summary(stats_full, "full")
                save_report(stats_full, "full")
            except Exception as exc:
                log.exception(f"שגיאה ב--full: {exc}")
                return 1
        else:
            print("בסדר, ההרצה נעצרה אחרי ה-pilot. הריצי שוב עם --full כשתהיי מוכנה.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
