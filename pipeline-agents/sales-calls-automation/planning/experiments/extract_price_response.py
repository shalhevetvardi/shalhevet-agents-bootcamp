#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_price_response.py — סוכן ניתוח ממוקד של הסגמנט שאחרי המחיר בראיונות טירונות סוכנים.

רציונל: סוכן החילוץ הראשי (extract_interviews.py) נטה לסווג תגובות מנומסות
("אשמח לקבל פרטים", "אנחנו נשמח") כ"סגירה" או "התלהבות". בפועל אף אחד מ-5
מועמדי הפיילוט לא נרשם בשיחה — כולם ב"טיוטה מוכנה". הסוכן הזה מתאר בדיוק
כירורגי מה קרה אחרי שנאמר המחיר, בלי פרשנות. הפלט נשמר ל-Airtable בשדה
נפרד (חילוץ_תגובה_למחיר_JSON) כדי לא לגעת בפלט של הסוכן הראשי.

מצבי הרצה:
    python3 extract_price_response.py --pilot
        # רץ על 5 שורות הפיילוט המוגדרות (record IDs קבועים), מדפיס JSON ל-console.

    python3 extract_price_response.py --full
        # רץ על כל השורות שעדיין לא עובדו על ידי הסוכן הזה (idempotent).

דרישות סביבה (.env):
    ANTHROPIC_API_KEY        — מפתח Anthropic
    AIRTABLE_API_KEY         — Personal Access Token של Airtable
    AIRTABLE_BASE_ID         — ה-Base ID (מצופה: app5fKvxuzbFb0stR)
    AIRTABLE_TABLE_ID        — ה-Table ID של טבלת הראיונות (מצופה: tblWrBSnk2GxQYOXI)

הסקריפט:
    1. מאמת/יוצר 4 שדות חדשים לסוכן הזה בלבד (לא דורס את שדות הסוכן הראשי):
       חילוץ_תגובה_למחיר_JSON, חילוץ_תגובה_למחיר_סטטוס,
       חילוץ_תגובה_למחיר_שגיאה, חילוץ_תגובה_למחיר_תאריך
    2. סורק שורות לפי מצב.
    3. קורא את שדה "תמלול השיחה".
    4. סינון: ריק או < 500 מילים → דולג_תמלול_ריק.
    5. שולח ל-Claude (claude-opus-4-6, temperature=0, max_tokens=4096).
       השתמשנו ב-4-6 ולא ב-4-7 כי 4-7 לא תומך ב-temperature —
       עקביות עם הפיילוט של הסוכן הראשי דורשת 4-6.
       שים לב: claude-opus-4-6 *לא* תומך ב-assistant prefill.
       אנחנו מסתמכים על הוראות מפורשות ב-system prompt להחזיר JSON בלבד.
    6. retry: 3 ניסיונות API עם backoff [5, 15, 45] שניות.
    7. JSON לא חוקי → ניסיון חוזר אחד; אם נכשל → נכשל_JSON + הטקסט הגולמי.
    8. השהייה של 2 שניות בין קריאות.
    9. Log קומפקטי: record_id, price_found, price_ts, agreement_type, סטטוס.
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
# קבועים
# =============================================================================

CLAUDE_MODEL = "claude-opus-4-6"
CLAUDE_TEMPERATURE = 0
CLAUDE_MAX_TOKENS = 4096

MIN_WORDS = 500
SLEEP_BETWEEN_RECORDS = 2.0
API_RETRY_DELAYS = [5, 15, 45]

# שם שדה התמלול — מאושר מול שלהבת (עם ה"א הידיעה)
TRANSCRIPT_FIELD_NAME = "תמלול השיחה"

# 4 שדות חדשים — שייכים לסוכן הזה בלבד
FIELD_PRICE_JSON = "חילוץ_תגובה_למחיר_JSON"
FIELD_PRICE_STATUS = "חילוץ_תגובה_למחיר_סטטוס"
FIELD_PRICE_ERROR = "חילוץ_תגובה_למחיר_שגיאה"
FIELD_PRICE_DATE = "חילוץ_תגובה_למחיר_תאריך"

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

DONE_STATUSES = {STATUS_SUCCESS, STATUS_SKIPPED_EMPTY}

# 5 שיחות הפיילוט — מוגדרות מפורשות, לא אקראיות
PILOT_RECORD_IDS = [
    "reccFuuKvi0UeWLIo",
    "recMHb1Ho7s13W7aa",
    "recpbHKH8Xq8P77yf",
    "recNbPRJWALtghPpM",
    "recjk6g7iEobLjqhl",
]

# 15 המפתחות הראשיים של ה-JSON
REQUIRED_ROOT_KEYS = [
    "price_mentioned",
    "price_mentioned_at_timestamp",
    "price_quote_verbatim",
    "first_candidate_reaction",
    "all_candidate_turns_after_price",
    "questions_candidate_asked_after_price",
    "hesitations_or_objections_after_price",
    "what_candidate_explicitly_agreed_to",
    "what_candidate_explicitly_agreed_to_quote",
    "what_shalhevet_offered_that_candidate_did_NOT_explicitly_accept",
    "turn_length_after_price",
    "observable_signals_after_price",
    "who_ended_the_conversation",
    "final_candidate_turn_verbatim",
    "time_from_price_to_end_of_call_seconds",
    # "open_notes" חיוני-רצוי אבל לא מעכב ולידציה — המודל לעיתים משמיט אותו
]

# נתיבים
SCRIPT_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = SCRIPT_DIR / "prompts" / "extract_price_response_system.md"
LOGS_DIR = SCRIPT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# =============================================================================
# Logging
# =============================================================================

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("extract_price_response")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = LOGS_DIR / f"extract_price_response_{datetime.now():%Y%m%d_%H%M%S}.log"
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
    pilot_ids_not_found: list[str] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)

    # סיכום קומפקטי לפיילוט — מה זוהה בכל שיחה
    compact_log: list[dict[str, Any]] = field(default_factory=list)

    def avg_duration(self) -> float:
        return sum(self.durations) / len(self.durations) if self.durations else 0.0


# =============================================================================
# Airtable — Meta API
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
    resp = requests.get(_meta_tables_url(base_id), headers=_airtable_headers(api_key))
    resp.raise_for_status()
    data = resp.json()
    for table in data.get("tables", []):
        if table.get("id") == table_id:
            return {f["name"]: f for f in table.get("fields", [])}
    raise RuntimeError(f"טבלה {table_id} לא נמצאה בבסיס {base_id}")


def create_field(api_key: str, base_id: str, table_id: str, payload: dict) -> dict:
    resp = requests.post(
        _meta_fields_url(base_id, table_id),
        headers=_airtable_headers(api_key),
        json=payload,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"יצירת שדה נכשלה ({resp.status_code}): {resp.text}")
    return resp.json()


def update_field(api_key: str, base_id: str, table_id: str, field_id: str, payload: dict) -> dict:
    resp = requests.patch(
        f"{_meta_fields_url(base_id, table_id)}/{field_id}",
        headers=_airtable_headers(api_key),
        json=payload,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"עדכון שדה נכשל ({resp.status_code}): {resp.text}")
    return resp.json()


def ensure_price_response_fields(api_key: str, base_id: str, table_id: str) -> dict[str, str]:
    """
    מאמת שכל 4 שדות הסוכן הזה קיימים. יוצר אם חסר.
    מחזיר {field_name: field_id}.
    """
    existing = get_existing_fields(api_key, base_id, table_id)

    if TRANSCRIPT_FIELD_NAME not in existing:
        raise RuntimeError(
            f"שדה התמלול '{TRANSCRIPT_FIELD_NAME}' לא נמצא בטבלה. "
            "ודאי שהשם נכון או שהתמלולים הועלו."
        )

    field_ids: dict[str, str] = {TRANSCRIPT_FIELD_NAME: existing[TRANSCRIPT_FIELD_NAME]["id"]}

    # 1. חילוץ_תגובה_למחיר_JSON — Long text
    if FIELD_PRICE_JSON in existing:
        field_ids[FIELD_PRICE_JSON] = existing[FIELD_PRICE_JSON]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_PRICE_JSON}' (Long text)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_PRICE_JSON,
            "type": "multilineText",
        })
        field_ids[FIELD_PRICE_JSON] = created["id"]

    # 2. חילוץ_תגובה_למחיר_סטטוס — Single select
    status_options = [{"name": opt} for opt in ALL_STATUS_OPTIONS]
    if FIELD_PRICE_STATUS in existing:
        existing_status = existing[FIELD_PRICE_STATUS]
        field_ids[FIELD_PRICE_STATUS] = existing_status["id"]
        existing_choices = {c["name"] for c in
                            existing_status.get("options", {}).get("choices", [])}
        missing = [opt for opt in ALL_STATUS_OPTIONS if opt not in existing_choices]
        if missing:
            log.info(f"מוסיף אופציות חסרות לשדה '{FIELD_PRICE_STATUS}': {missing}")
            all_choices = [{"name": c["name"]} for c in
                           existing_status.get("options", {}).get("choices", [])]
            all_choices += [{"name": opt} for opt in missing]
            update_field(api_key, base_id, table_id,
                         existing_status["id"],
                         {"options": {"choices": all_choices}})
    else:
        log.info(f"יוצר שדה '{FIELD_PRICE_STATUS}' (Single select)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_PRICE_STATUS,
            "type": "singleSelect",
            "options": {"choices": status_options},
        })
        field_ids[FIELD_PRICE_STATUS] = created["id"]

    # 3. חילוץ_תגובה_למחיר_שגיאה — Long text
    if FIELD_PRICE_ERROR in existing:
        field_ids[FIELD_PRICE_ERROR] = existing[FIELD_PRICE_ERROR]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_PRICE_ERROR}' (Long text)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_PRICE_ERROR,
            "type": "multilineText",
        })
        field_ids[FIELD_PRICE_ERROR] = created["id"]

    # 4. חילוץ_תגובה_למחיר_תאריך — Date
    if FIELD_PRICE_DATE in existing:
        field_ids[FIELD_PRICE_DATE] = existing[FIELD_PRICE_DATE]["id"]
    else:
        log.info(f"יוצר שדה '{FIELD_PRICE_DATE}' (Date)")
        created = create_field(api_key, base_id, table_id, {
            "name": FIELD_PRICE_DATE,
            "type": "date",
            "options": {"dateFormat": {"name": "iso"}},
        })
        field_ids[FIELD_PRICE_DATE] = created["id"]

    return field_ids


# =============================================================================
# Airtable — Records
# =============================================================================

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
# Claude — קריאה + retry + ולידציה
# =============================================================================

USER_MESSAGE_TEMPLATE = """להלן תמלול מלא של ראיון קבלה של שלהבת ורדי עם מועמד/ת לתוכנית טירונות סוכנים.
נתח רק את הסגמנט שאחרי רגע המחיר לפי הסכמה שהוגדרה ב-system prompt.
החזר JSON יחיד בלבד.

---
תמלול:
{TRANSCRIPT_CONTENT}"""

def call_claude(client: Anthropic, system_prompt: str, transcript: str) -> str:
    """קריאה אחת ל-Claude.

    הערה: claude-opus-4-6 לא תומך ב-assistant prefill. אנחנו מסתמכים על
    הוראות מפורשות ב-system prompt ("החזר JSON תקין בלבד. בלי markdown,
    בלי ```json```, בלי טקסט לפני או אחרי.") + ניקוי fences בצד ה-client.
    """
    user_msg = USER_MESSAGE_TEMPLATE.replace("{TRANSCRIPT_CONTENT}", transcript)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        temperature=CLAUDE_TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts).strip()


def call_claude_with_api_retry(client: Anthropic, system_prompt: str,
                               transcript: str) -> str:
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
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text.strip()


def validate_extraction_output(raw_text: str) -> tuple[dict | None, str | None]:
    """מחזיר (parsed_dict, error_msg). חייב לכלול את כל המפתחות המרכזיים."""
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
    return len(text.split()) if text else 0


def get_record_status(record: dict) -> str | None:
    return record.get("fields", {}).get(FIELD_PRICE_STATUS)


def get_record_transcript(record: dict) -> str:
    return record.get("fields", {}).get(TRANSCRIPT_FIELD_NAME, "") or ""


def write_result_to_airtable(api_key: str, base_id: str, table_id: str,
                             record_id: str, status: str,
                             extraction_json: str | None = None,
                             error_text: str | None = None) -> None:
    today_iso = datetime.now(timezone.utc).date().isoformat()
    fields: dict[str, Any] = {
        FIELD_PRICE_STATUS: status,
        FIELD_PRICE_DATE: today_iso,
    }
    if extraction_json is not None:
        fields[FIELD_PRICE_JSON] = extraction_json
    if error_text is not None:
        fields[FIELD_PRICE_ERROR] = error_text
    update_record(api_key, base_id, table_id, record_id, fields)


def _extract_compact_fields(parsed: dict) -> dict[str, Any]:
    """מחלץ את 4 הערכים הקומפקטיים ללוג."""
    price_mentioned = parsed.get("price_mentioned")
    price_ts = parsed.get("price_mentioned_at_timestamp")
    agreement = parsed.get("what_candidate_explicitly_agreed_to")
    return {
        "price_found": bool(price_mentioned),
        "price_ts": price_ts,
        "agreement_type": agreement,
    }


def process_record(client: Anthropic, system_prompt: str,
                   record: dict, idx: int, total: int,
                   api_key: str, base_id: str, table_id: str,
                   stats: Stats, print_json_to_console: bool = False) -> None:
    record_id = record["id"]
    transcript = get_record_transcript(record)
    word_count = count_words(transcript)

    # שלב 1 — סינון לפי אורך
    if not transcript.strip() or word_count < MIN_WORDS:
        log.info(f"[{idx}/{total}] {record_id} ({word_count} מילים) → {STATUS_SKIPPED_EMPTY}")
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_SKIPPED_EMPTY,
            error_text=f"תמלול ריק או קצר מ-{MIN_WORDS} מילים (בפועל: {word_count})",
        )
        stats.skipped_empty += 1
        stats.compact_log.append({
            "record_id": record_id, "status": STATUS_SKIPPED_EMPTY,
            "price_found": None, "price_ts": None, "agreement_type": None,
        })
        return

    # שלב 2 — קריאה ל-Claude
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
        stats.compact_log.append({
            "record_id": record_id, "status": STATUS_FAIL_API,
            "price_found": None, "price_ts": None, "agreement_type": None,
        })
        return

    # שלב 3 — ולידציה
    parsed, err = validate_extraction_output(raw)

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
            stats.compact_log.append({
                "record_id": record_id, "status": STATUS_FAIL_API,
                "price_found": None, "price_ts": None, "agreement_type": None,
            })
            return

    elapsed = time.monotonic() - start

    if parsed is None:
        log.error(f"[{idx}/{total}] {record_id} ({word_count:,} מילים) → {STATUS_FAIL_JSON} "
                  f"אחרי {elapsed:.1f}s: {err}")
        error_payload = f"{err}\n\n--- raw output ---\n{raw}"[:50000]
        write_result_to_airtable(
            api_key, base_id, table_id, record_id,
            status=STATUS_FAIL_JSON,
            error_text=error_payload,
        )
        stats.failed_json += 1
        stats.compact_log.append({
            "record_id": record_id, "status": STATUS_FAIL_JSON,
            "price_found": None, "price_ts": None, "agreement_type": None,
        })
        return

    # הצליח
    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    compact = _extract_compact_fields(parsed)

    log.info(
        f"[{idx}/{total}] {record_id} ({word_count:,} מילים) → {STATUS_SUCCESS} "
        f"ב-{elapsed:.1f}s | מחיר={compact['price_found']} "
        f"ts={compact['price_ts']} הסכמה={compact['agreement_type']}"
    )

    if print_json_to_console:
        print("─" * 80)
        print(f"📄 {record_id} ({word_count:,} מילים) — {elapsed:.1f}s")
        print(f"   מחיר נמצא: {compact['price_found']} | timestamp: {compact['price_ts']}")
        print(f"   סוג ההסכמה: {compact['agreement_type']}")
        print("─" * 80)
        print(pretty)
        print()

    write_result_to_airtable(
        api_key, base_id, table_id, record_id,
        status=STATUS_SUCCESS,
        extraction_json=pretty,
        error_text="",
    )
    stats.succeeded += 1
    stats.durations.append(elapsed)
    stats.compact_log.append({
        "record_id": record_id, "status": STATUS_SUCCESS, **compact,
    })


# =============================================================================
# בחירת שורות לעיבוד
# =============================================================================

def filter_candidates(records: list[dict], mode: str,
                      stats: Stats) -> tuple[list[dict], int]:
    """
    --pilot: רק 5 ה-record IDs הקבועים, בסדר נתון, ללא קשר לסטטוס.
    --full:  כל מי שעדיין לא הצליח/דולג (idempotent).
    """
    if mode == "pilot":
        index = {r["id"]: r for r in records}
        sample: list[dict] = []
        for rid in PILOT_RECORD_IDS:
            rec = index.get(rid)
            if rec is None:
                log.warning(f"⚠️  record ID לא נמצא בטבלה: {rid}")
                stats.pilot_ids_not_found.append(rid)
                continue
            sample.append(rec)
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

    system_prompt = load_system_prompt()
    log.info(f"system prompt נטען מ-{SYSTEM_PROMPT_PATH.name} "
             f"({len(system_prompt):,} תווים)")

    log.info("מאמת שדות חילוץ-מחיר ב-Airtable...")
    ensure_price_response_fields(airtable_key, base_id, table_id)

    log.info("שולף את כל השורות מ-Airtable...")
    records = list_all_records(airtable_key, base_id, table_id)
    log.info(f"נמצאו {len(records)} שורות בטבלה.")

    stats = Stats()
    candidates, skipped_done = filter_candidates(records, mode, stats)
    stats.total_candidates = len(candidates)
    stats.skipped_already_done = skipped_done
    log.info(f"נבחרו {len(candidates)} שורות לעיבוד "
             f"(דולגות {skipped_done} שכבר הושלמו).")

    if not candidates:
        log.warning("אין שורות לעיבוד.")
        return stats

    client = Anthropic(api_key=anthropic_key)
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

        if i < len(candidates):
            time.sleep(SLEEP_BETWEEN_RECORDS)

    return stats


# =============================================================================
# סיכום ודוח
# =============================================================================

def print_summary(stats: Stats, mode: str) -> None:
    print()
    print("=" * 70)
    print(f"  סיכום הרצה — מצב {mode} (חילוץ תגובה למחיר)")
    print("=" * 70)
    print(f"  שורות מועמדות לעיבוד     : {stats.total_candidates}")
    print(f"  הצליח                    : {stats.succeeded}")
    print(f"  נכשל_API                 : {stats.failed_api}")
    print(f"  נכשל_JSON                : {stats.failed_json}")
    print(f"  דולג_תמלול_ריק           : {stats.skipped_empty}")
    if mode == "full":
        print(f"  דולגות (כבר הושלמו קודם) : {stats.skipped_already_done}")
    if mode == "pilot" and stats.pilot_ids_not_found:
        print(f"  ⚠️  record IDs לא נמצאו   : {stats.pilot_ids_not_found}")
    if stats.durations:
        print(f"  זמן ממוצע לקריאה        : {stats.avg_duration():.1f} שניות")
    print("=" * 70)

    # לוג קומפקטי של 5 השיחות — לסריקה מהירה של שלהבת
    if stats.compact_log:
        print()
        print("📋 סיכום קומפקטי לכל שיחה:")
        print("-" * 70)
        print(f"{'#':<3} {'record_id':<20} {'סטטוס':<15} {'מחיר?':<7} {'ts':<7} {'הסכמה'}")
        print("-" * 70)
        for i, row in enumerate(stats.compact_log, start=1):
            rid = row.get("record_id") or "?"
            status = row.get("status") or "?"
            price = "כן" if row.get("price_found") else ("לא" if row.get("price_found") is False else "-")
            ts = row.get("price_ts") or "-"
            agree = row.get("agreement_type") or "-"
            print(f"{i:<3} {rid:<20} {status:<15} {price:<7} {ts:<7} {agree}")
        print("-" * 70)
    print()


def save_report(stats: Stats, mode: str) -> Path:
    report_path = LOGS_DIR / f"extract_price_response_report_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "total_candidates": stats.total_candidates,
        "succeeded": stats.succeeded,
        "failed_api": stats.failed_api,
        "failed_json": stats.failed_json,
        "skipped_empty": stats.skipped_empty,
        "skipped_already_done": stats.skipped_already_done,
        "pilot_ids_not_found": stats.pilot_ids_not_found,
        "avg_duration_seconds": round(stats.avg_duration(), 2),
        "per_record": stats.compact_log,
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
        description="חילוץ תגובה של מועמד לאחר רגע המחיר, מ-Airtable עם Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""דוגמאות:
    python3 extract_price_response.py --pilot   # 5 שיחות פיילוט קבועות
    python3 extract_price_response.py --full    # כל מי שטרם עובד""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pilot", action="store_true",
                       help="הרצה על 5 שורות פיילוט קבועות + הדפסה ל-console.")
    group.add_argument("--full", action="store_true",
                       help="הרצה idempotent על כל השורות שעדיין לא עובדו.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "pilot" if args.pilot else "full"

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

    # ב-pilot נעצרים לבדיקה של שלהבת — לא מציעים להמשיך ל-full אוטומטית.
    if mode == "pilot":
        print()
        print("✅ ה-pilot הסתיים. בדקי את הפלטים ל-5 השיחות בטבלה.")
        print("   לאחר אישור, הריצי שוב עם:  python3 extract_price_response.py --full")

    return 0


if __name__ == "__main__":
    sys.exit(main())
