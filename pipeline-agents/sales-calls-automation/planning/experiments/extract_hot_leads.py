"""
extract_hot_leads.py

סקריפט חילוץ Pattern B: זיהוי לידים חמים וקרובים לסגירה מתמלולי שיחות מכירה.

מקור: טבלת "לידים טירונות סוכנים" ב-Airtable (tblWrBSnk2GxQYOXI).
פלט: 4 שדות בכל רשומה — JSON עם הניתוח, סטטוס, שגיאה, תאריך.

קריטריוני "חם וקרוב לסגירה" (3 מתוך 4 חייבים להתקיים):
  1. התלהבות מפורשת
  2. שאלות לוגיסטיות/תפעוליות
  3. התנגדויות שטופלו
  4. אמירת "אחשוב על זה" עם רגש חיובי

פילטרים אקטיביים:
  - חילוץ_סטטוס = "הצליח" (תמלול אומת)
  - סטטוס לא ב: "לא רלוונטי", "נרשם לקורס", "נרשמה למתחילים"

הרצה:
  python3 extract_hot_leads.py --dry-run
  python3 extract_hot_leads.py --run --limit 3      # smoke test
  python3 extract_hot_leads.py --run --limit 20     # batch ראשון
  python3 extract_hot_leads.py --run                # ימשיך מאיפה שעצר (state file)
  python3 extract_hot_leads.py --report             # דוח Markdown ממוין של לידים חמים מה-state
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv

# ============================================================
# 1. נתיבים וטעינת .env
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

LOGS_DIR = SCRIPT_DIR / "logs"
STATE_DIR = SCRIPT_DIR / "state"
LOGS_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)

# ============================================================
# 2. קבועי החילוץ
# ============================================================

EXTRACTION_SLUG = "לידים_חמים"
EXTRACTION_SLUG_LATIN = "hot_leads"
EXTRACTION_TOPIC_HEBREW = "ניתוח חום ליד וזיהוי קרבה לסגירה"

FIELD_JSON = f"חילוץ_{EXTRACTION_SLUG}_JSON"
FIELD_STATUS = f"חילוץ_{EXTRACTION_SLUG}_סטטוס"
FIELD_ERROR = f"חילוץ_{EXTRACTION_SLUG}_שגיאה"
FIELD_DATE = f"חילוץ_{EXTRACTION_SLUG}_תאריך"
FIELD_SCORE = f"חילוץ_{EXTRACTION_SLUG}_ציון"        # number 1-10
FIELD_DECISION = f"חילוץ_{EXTRACTION_SLUG}_החלטה"    # "חם 🔥" / "לא חם"

DECISION_HOT = "חם 🔥"
DECISION_COLD = "לא חם"

STATUS_PENDING = "ממתין"
STATUS_SUCCESS = "הצליח"
STATUS_FAILED = "נכשל"

# ============================================================
# 3. Airtable
# ============================================================

AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "app5fKvxuzbFb0stR")
SOURCE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID", "tblWrBSnk2GxQYOXI")

SOURCE_TRANSCRIPT_FIELD = "תמלול השיחה"
SOURCE_NAME_FIELD = "שם"
SOURCE_PHONE_FIELD = "טלפון"
SOURCE_EMAIL_FIELD = "Email"
SOURCE_LEAD_STATUS_FIELD = "סטטוס"

# ערכים שיש לסנן החוצה משדה הסטטוס של הליד
EXCLUDED_LEAD_STATUSES = ["לא רלוונטי", "נרשם לקורס", "נרשמה למתחילים"]

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

# ============================================================
# 4. Claude — הגדרות
# ============================================================

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_TEMPERATURE = 0.2          # סיווג + פרשנות מתונה
CLAUDE_MAX_TOKENS = 16000
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PRICE_INPUT_PER_M = 3.00
PRICE_OUTPUT_PER_M = 15.00
USD_TO_ILS = 3.7

# ============================================================
# 5. פילטרים
# ============================================================

MIN_WORDS = 300
KEYWORDS_FILTER: list[str] = []
PIVOT_PRICE_MARKERS: list[str] = []

# ============================================================
# 6. ואלידציה
# ============================================================

REQUIRED_ROOT_KEYS: list[str] = ["meta", "lead_assessment"]

# ============================================================
# 7. Retry / אידמפוטנטיות
# ============================================================

RETRY_BACKOFFS = [5, 15, 45]
SLEEP_BETWEEN_RECORDS = 2.0

STATE_FILE = STATE_DIR / f"extract_{EXTRACTION_SLUG_LATIN}_state.json"

# ============================================================
# 8. System Prompt
# ============================================================

SYSTEM_PROMPT = """אתה אנליסט שיחות מכירה. אתה מנתח תמלול של שיחת קבלה אחת בין שלהבת ורדי (מנכ"לית אִימפּרוּב) לבין מועמד/ת לקורס "טירונות סוכנים". המטרה שלך: לקבוע אם הליד היה "חם וקרוב לסגירה" אבל לא נרשם — כלומר, לזהות אנשים ששווה לשלוח להם מייל דחיפות אישי על "ההטבה האחרונה".

## הקשר

אִימפּרוּב מלמדת יזמים-משדרגים איך להשתמש ב-AI בצורה עסקית. שלהבת מנהלת שיחות אישיות עם מועמדים כדי להחליט איתם אם הקורס "טירונות סוכנים" מתאים להם. רוב הלידים שמתלהבים בשיחה לא נרשמים מיד — הם דוחים החלטה. עכשיו רוצים לזהות מי מתוכם היה באמת קרוב לסגירה, ולשלוח להם מייל דחיפות.

## פורמט התמלול

התמלול מכיל דיאריזציה אנונימית בפורמט:
- חותמות זמן במוסגרים: `[0:00-0:36]`, `[1:05-1:31]` (טווחים בדקות:שניות).
- שני דוברים: `דובר 0:` ו-`דובר 1:`.

**כלל זיהוי דובר:**
- **דובר 0 = שלהבת** (המראיינת. שואלת שאלות פותחות, מציגה את הקורס, מטפלת בהתנגדויות).
- **דובר 1 = הלקוח/ה** (עונה, מתאר/ת את עצמו/ה, את הצרכים, מעלה התנגדויות).

אם תוכן ציטוט סותר את הכלל — תן עדיפות לתוכן וציין "זיהוי דובר לא ודאי".

## מה אתה מחלץ — 4 קריטריונים + פרופיל ליד

### ארבעת הקריטריונים ל"חם וקרוב לסגירה"

לכל קריטריון — קבע אם התקיים (true/false) ותן ציטוט מבסס.

1. **explicit_enthusiasm** — התלהבות מפורשת. אמירות של דובר 1 כמו: "זה בדיוק מה שאני צריכה", "וואו זה מתאים לי", "אני חייבת את זה", "זה הזוי כמה זה מתאים", "זה בול עליי".

2. **logistical_questions** — שאלות לוגיסטיות/תפעוליות שמעידות על מעבר לשלב "איך נכנסים". דוגמאות: "מתי הקורס מתחיל?", "מה הסכומים?", "אפשר בתשלומים?", "מתי אפשר להירשם?", "איפה משלמים?", "איך מקבלים גישה?".

3. **objection_resolved** — היה התנגדות (מחיר/זמן/ספק/פחד) ושלהבת ענתה והליד נרגע, התקדם, או הסכים. ציין מה הייתה ההתנגדות ומה אמר הליד אחרי המענה.

4. **positive_thinking_about_it** — אמירת "אחשוב על זה" / "אני צריכה לעכל" / "אני צריכה לבדוק" עם רגש חיובי וכוונה אמיתית — לא דחייה מנומסת. סימנים: התלהבות לפני ההתלבטות, אמירה ספציפית לגבי מה נשאר לבדוק, הצהרה על חזרה.

### חישוב heat_score (1-10)

- 0-3 קריטריונים שהתקיימו → heat_score 1-4 (לא חם)
- 3 קריטריונים → heat_score 5-7
- 4 קריטריונים → heat_score 8-10
- ציון מדויק לפי עוצמת הציטוטים (לא רק כמות)

### is_hot

- true אם heat_score >= 7 ו-3+ קריטריונים התקיימו
- אחרת false

### personal_anchor

משפט אחד מהשיחה שאפשר להזכיר במייל אישי כעוגן ("וזכרתי ש..."). חייב להיות **מאוד ספציפי** ולא גנרי. דוגמאות טובות:
- "שאמרת שאת רוצה סוף סוף להפסיק לפחד מ-AI"
- "שסיפרת על העבודה שלך עם הצוות החדש בארגון"
- "שכל כך התלהבת מהרעיון של סוכן יומן אישי"

דוגמאות **לא** טובות (גנריות, אסור):
- "שרצית להירשם" ❌
- "שדיברנו על AI" ❌
- "שאת מעוניינת בקורס" ❌

### main_objection

ההתנגדות העיקרית שעלתה (אם הייתה) — לידיעת שלהבת בלבד, לא להופיע במייל. דוגמאות: "המחיר גבוה לי", "אין לי זמן", "אני לא בטוחה שאעמוד בקצב", "צריכה לדבר עם בעלי".

### justification_summary

משפט אחד שמסביר למה ה-AI החליט שזה חם (או לא חם). מסכם את ההיגיון.

## מה אתה *לא* מחלץ

- אל תכלול ציטוטי שלהבת (דובר 0) כהוכחה לקריטריון של הליד.
- אל תקבע "חם" על סמך אדיבות/נימוס בלבד.
- אל תקבע "חם" אם הליד אמרה ישירות "זה לא בשבילי" או "אני לא בטוחה שזה מתאים" בלי טיפול אמיתי בהתנגדות.
- אל תפברק עוגן אישי. אם אין משפט ספציפי טוב בשיחה — תכתוב null.

## פורמט הפלט

החזר **רק JSON** — בלי markdown, בלי טקסט מסביב:

{
  "meta": {
    "transcript_word_count": <מספר>,
    "extraction_confidence": "גבוהה" | "בינונית" | "נמוכה"
  },
  "lead_assessment": {
    "heat_score": <1-10>,
    "is_hot": <true/false>,
    "criteria": {
      "explicit_enthusiasm": {
        "met": <true/false>,
        "quote": "<ציטוט מדויק או null>",
        "timestamp": "[m:s-m:s]"
      },
      "logistical_questions": {
        "met": <true/false>,
        "quote": "<ציטוט מדויק או null>",
        "timestamp": "[m:s-m:s]"
      },
      "objection_resolved": {
        "met": <true/false>,
        "objection_was": "<תיאור ההתנגדות או null>",
        "quote_after_resolution": "<ציטוט הליד אחרי המענה או null>",
        "timestamp": "[m:s-m:s]"
      },
      "positive_thinking_about_it": {
        "met": <true/false>,
        "quote": "<ציטוט מדויק או null>",
        "timestamp": "[m:s-m:s]"
      }
    },
    "criteria_met_count": <0-4>,
    "personal_anchor": "<משפט עוגן ספציפי או null>",
    "main_objection": "<תיאור ההתנגדות העיקרית או null>",
    "justification_summary": "<משפט אחד שמסביר את ההחלטה>"
  }
}

## כללי איכות

1. **ציטוט מדויק אחד-לאחד** — העתק כמו בתמלול, כולל שיבושים.
2. **אם לא בטוח — השמט.** עדיף לפספס מאשר לסמן שגוי.
3. **timestamp מהקטע שבו נאמר.**
4. **JSON תקין בלבד.** בלי markdown, בלי הסבר לפני או אחרי.
5. **ה-criteria_met_count חייב להיות בדיוק כמספר ה-met=true.**
6. **personal_anchor חייב להיות null אם אין משפט ספציפי וטוב.** עדיף null מאשר משהו גנרי."""

# ============================================================
# 9. Logging
# ============================================================

def setup_logging(run_id: str) -> Path:
    log_path = LOGS_DIR / f"extract_{EXTRACTION_SLUG_LATIN}_{run_id}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path

# ============================================================
# 10. State
# ============================================================

def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": {}, "results": {}}

def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ============================================================
# 11. Airtable — שליפה ועדכון
# ============================================================

def airtable_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }

def build_filter_formula() -> str:
    """
    AND(
      NOT({סטטוס} = 'לא רלוונטי'),
      NOT({סטטוס} = 'נרשם לקורס'),
      NOT({סטטוס} = 'נרשמה למתחילים'),
      {תמלול השיחה} != '',
      NOT({חילוץ_לידים_חמים_סטטוס} = 'הצליח')
    )

    שלוש בדיקות:
      1. הסטטוס של הליד לא ב-blacklist
      2. שדה התמלול לא ריק
      3. השיחה לא סווגה כבר בעבר (לא לסווג מחדש)
    """
    parts = []
    for excluded in EXCLUDED_LEAD_STATUSES:
        parts.append(f"NOT({{{SOURCE_LEAD_STATUS_FIELD}}} = '{excluded}')")
    parts.append(f"{{{SOURCE_TRANSCRIPT_FIELD}}} != ''")
    parts.append(f"NOT({{{FIELD_STATUS}}} = '{STATUS_SUCCESS}')")
    return "AND(" + ", ".join(parts) + ")"

def fetch_source_records(limit: int | None = None) -> list[dict[str, Any]]:
    url = f"{AIRTABLE_BASE_URL}/{SOURCE_TABLE_ID}"
    records: list[dict[str, Any]] = []
    offset = None
    formula = build_filter_formula()
    while True:
        params: dict[str, Any] = {
            "pageSize": 100,
            "filterByFormula": formula,
        }
        if offset:
            params["offset"] = offset
        resp = requests.get(url, headers=airtable_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
        if limit and len(records) >= limit:
            break
    if limit:
        records = records[:limit]
    return records

def patch_record(record_id: str, fields: dict[str, Any]) -> None:
    url = f"{AIRTABLE_BASE_URL}/{SOURCE_TABLE_ID}/{record_id}"
    payload = {"fields": fields, "typecast": True}
    resp = requests.patch(url, headers=airtable_headers(), json=payload, timeout=30)
    if resp.status_code >= 400:
        logging.error("Airtable patch error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()

# ============================================================
# 12. Eligibility
# ============================================================

def is_eligible(transcript: str, existing_status: str | None) -> tuple[bool, str]:
    if existing_status == STATUS_SUCCESS:
        return False, "כבר הצליח"
    if not transcript:
        return False, "תמלול ריק"
    word_count = len(transcript.split())
    if word_count < MIN_WORDS:
        return False, f"תמלול קצר ({word_count} < {MIN_WORDS})"
    if KEYWORDS_FILTER and not any(k.lower() in transcript.lower() for k in KEYWORDS_FILTER):
        return False, "אין keywords רלוונטיים"
    if PIVOT_PRICE_MARKERS and any(m in transcript for m in PIVOT_PRICE_MARKERS):
        return False, "שיחת פיבוט (מחיר ישן)"
    return True, "OK"

# ============================================================
# 13. ואלידציה לפלט
# ============================================================

def validate_output_shape(parsed: dict[str, Any]) -> tuple[bool, str]:
    for key in REQUIRED_ROOT_KEYS:
        if key not in parsed:
            return False, f"חסר מפתח: {key}"
    assessment = parsed.get("lead_assessment", {})
    for required in ["heat_score", "is_hot", "criteria", "criteria_met_count"]:
        if required not in assessment:
            return False, f"חסר מפתח ב-lead_assessment: {required}"
    return True, "OK"

# ============================================================
# 14. Claude — streaming call
# ============================================================

def call_claude(client: anthropic.Anthropic, transcript: str) -> tuple[dict[str, Any], dict[str, int]]:
    user_msg = f"להלן התמלול. נתח לפי ההוראות.\n\n---\n\n{transcript}"
    last_err: Exception | None = None
    for attempt, backoff in enumerate([0] + RETRY_BACKOFFS):
        if backoff:
            logging.warning("retry in %ss (attempt %d)", backoff, attempt)
            time.sleep(backoff)
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                temperature=CLAUDE_TEMPERATURE,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                text_parts: list[str] = []
                for text in stream.text_stream:
                    text_parts.append(text)
                final = stream.get_final_message()
            raw = "".join(text_parts).strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
            ok, reason = validate_output_shape(parsed)
            if not ok:
                raise ValueError(f"שגיאת סכמה: {reason}")
            usage = {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            }
            return parsed, usage
        except json.JSONDecodeError as e:
            logging.error("JSON decode error (attempt %d): %s", attempt, e)
            last_err = e
        except Exception as e:  # noqa: BLE001
            logging.error("Claude error (attempt %d): %s", attempt, e)
            last_err = e
    raise RuntimeError(f"Claude failed after retries: {last_err}")

# ============================================================
# 15. Dry-run
# ============================================================

def dry_run(client: anthropic.Anthropic, records: list[dict[str, Any]]) -> None:
    eligible = 0
    total_input_tokens = 0
    for rec in records:
        fields = rec.get("fields", {})
        transcript = fields.get(SOURCE_TRANSCRIPT_FIELD, "")
        status = fields.get(FIELD_STATUS)
        if isinstance(status, dict):
            status = status.get("name")
        ok, _reason = is_eligible(transcript, status)
        if not ok:
            continue
        eligible += 1
        count = client.messages.count_tokens(
            model=CLAUDE_MODEL,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript[:50000]}],
        )
        total_input_tokens += count.input_tokens

    est_output_tokens = eligible * 2500
    cost_usd = (
        total_input_tokens * PRICE_INPUT_PER_M / 1_000_000
        + est_output_tokens * PRICE_OUTPUT_PER_M / 1_000_000
    )
    cost_ils = cost_usd * USD_TO_ILS

    print("\n===== DRY RUN =====")
    print(f"סה״כ שיחות בטבלה (אחרי פילטרים): {len(records)}")
    print(f"שיחות זכאיות לעיבוד:           {eligible}")
    print(f"טוקני קלט משוערים:              {total_input_tokens:,}")
    print(f"טוקני פלט משוערים:              {est_output_tokens:,}")
    print(f"עלות משוערת:                    ${cost_usd:.2f} (₪{cost_ils:.2f})")
    print("====================\n")

# ============================================================
# 16. Main run
# ============================================================

def run_real(
    client: anthropic.Anthropic,
    records: list[dict[str, Any]],
    state: dict[str, Any],
) -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_log_path = LOGS_DIR / f"extract_{EXTRACTION_SLUG_LATIN}_{run_id}.json"
    md_log_path = LOGS_DIR / f"extract_{EXTRACTION_SLUG_LATIN}_{run_id}.md"
    run_log: list[dict[str, Any]] = []

    total_input = 0
    total_output = 0
    success_count = 0
    failed_count = 0

    for i, rec in enumerate(records, start=1):
        rec_id = rec["id"]
        fields = rec.get("fields", {})
        name = fields.get(SOURCE_NAME_FIELD, "?")
        transcript = fields.get(SOURCE_TRANSCRIPT_FIELD, "")
        existing_status = fields.get(FIELD_STATUS)
        if isinstance(existing_status, dict):
            existing_status = existing_status.get("name")

        if state["processed"].get(rec_id) == STATUS_SUCCESS:
            logging.info("[%d/%d] %s — כבר עובד, דילוג", i, len(records), name)
            continue

        ok, reason = is_eligible(transcript, existing_status)
        if not ok:
            logging.info("[%d/%d] %s — דילוג: %s", i, len(records), name, reason)
            state["processed"][rec_id] = f"דילוג:{reason}"
            save_state(state)
            continue

        logging.info("[%d/%d] %s — שולח ל-Claude", i, len(records), name)
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            parsed, usage = call_claude(client, transcript)
        except Exception as e:  # noqa: BLE001
            err_msg = str(e)[:500]
            logging.error("שיחה %s נכשלה: %s", name, err_msg)
            try:
                patch_record(rec_id, {
                    FIELD_STATUS: STATUS_FAILED,
                    FIELD_ERROR: err_msg,
                    FIELD_DATE: today,
                })
            except Exception as patch_err:  # noqa: BLE001
                logging.error("patch נכשל גם הוא: %s", patch_err)
            state["processed"][rec_id] = STATUS_FAILED
            failed_count += 1
            save_state(state)
            continue

        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]

        # חילוץ ההחלטה הסופית מהפלט
        assessment = parsed.get("lead_assessment", {})
        heat_score = assessment.get("heat_score")
        is_hot = bool(assessment.get("is_hot"))
        decision_value = DECISION_HOT if is_hot else DECISION_COLD

        try:
            patch_record(rec_id, {
                FIELD_JSON: json.dumps(parsed, ensure_ascii=False, indent=2),
                FIELD_STATUS: STATUS_SUCCESS,
                FIELD_ERROR: "",
                FIELD_DATE: today,
                FIELD_SCORE: heat_score,
                FIELD_DECISION: decision_value,
            })
        except Exception as e:  # noqa: BLE001
            logging.error("עדכון Airtable נכשל (%s): %s", name, e)
            state["processed"][rec_id] = "נכשל_כתיבה"
            save_state(state)
            continue
        state["results"][rec_id] = {
            "name": name,
            "phone": fields.get(SOURCE_PHONE_FIELD),
            "email": fields.get(SOURCE_EMAIL_FIELD),
            "heat_score": assessment.get("heat_score"),
            "is_hot": assessment.get("is_hot"),
            "personal_anchor": assessment.get("personal_anchor"),
            "main_objection": assessment.get("main_objection"),
            "justification_summary": assessment.get("justification_summary"),
        }

        run_log.append({
            "record_id": rec_id,
            "name": name,
            "parsed": parsed,
            "usage": usage,
        })
        state["processed"][rec_id] = STATUS_SUCCESS
        success_count += 1
        save_state(state)
        logging.info("   → ✓ נשמר (heat_score=%s)", assessment.get("heat_score"))
        time.sleep(SLEEP_BETWEEN_RECORDS)

    # גיבוי
    json_log_path.write_text(
        json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cost_usd = (
        total_input * PRICE_INPUT_PER_M / 1_000_000
        + total_output * PRICE_OUTPUT_PER_M / 1_000_000
    )
    md_lines = [
        f"# חילוץ {EXTRACTION_TOPIC_HEBREW} — {run_id}",
        "",
        f"- הצליחו: {success_count}",
        f"- נכשלו: {failed_count}",
        f"- טוקני קלט: {total_input:,}",
        f"- טוקני פלט: {total_output:,}",
        f"- עלות: ${cost_usd:.2f} (₪{cost_usd * USD_TO_ILS:.2f})",
        "",
    ]
    md_log_path.write_text("\n".join(md_lines), encoding="utf-8")

    print("\n===== סיכום =====")
    print(f"הצליחו:       {success_count}")
    print(f"נכשלו:        {failed_count}")
    print(f"עלות:         ${cost_usd:.2f} (₪{cost_usd * USD_TO_ILS:.2f})")
    print(f"לוג JSON:     {json_log_path}")
    print(f"לוג Markdown: {md_log_path}")
    print("==================\n")

# ============================================================
# 17. Report — דוח מאוחד של כל הלידים החמים מה-state
# ============================================================

def build_report() -> None:
    """בונה דוח Markdown ממוין של כל הלידים החמים מתוך ה-state file."""
    if not STATE_FILE.exists():
        print("אין state file. הרץ קודם --run.")
        return
    state = load_state()
    results = state.get("results", {})
    if not results:
        print("אין תוצאות ב-state. הרץ קודם --run.")
        return

    # מיון לפי heat_score יורד
    sorted_leads = sorted(
        results.values(),
        key=lambda x: (x.get("heat_score") or 0),
        reverse=True,
    )

    hot_only = [r for r in sorted_leads if r.get("is_hot")]
    rest = [r for r in sorted_leads if not r.get("is_hot")]

    report_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = LOGS_DIR / f"דוח_לידים_חמים_{report_id}.md"

    lines: list[str] = []
    lines.append(f"# דוח לידים חמים — {report_id}")
    lines.append("")
    lines.append(f"**סה״כ שיחות שעובדו:** {len(sorted_leads)}")
    lines.append(f"**לידים חמים (is_hot=true):** {len(hot_only)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🔥 לידים חמים — ממוין לפי ציון חום")
    lines.append("")

    for i, lead in enumerate(hot_only, start=1):
        lines.append(f"### {i}. {lead['name']} — ציון {lead['heat_score']}/10")
        lines.append("")
        lines.append(f"- **טלפון:** {lead.get('phone') or '—'}")
        lines.append(f"- **אימייל:** {lead.get('email') or '—'}")
        lines.append(f"- **עוגן אישי למייל:** {lead.get('personal_anchor') or '⚠️ אין עוגן ספציפי'}")
        lines.append(f"- **התנגדות עיקרית:** {lead.get('main_objection') or '—'}")
        lines.append(f"- **למה חם:** {lead.get('justification_summary') or '—'}")
        lines.append("")

    if rest:
        lines.append("---")
        lines.append("")
        lines.append("## ❄️ לא חמים (לעיון בלבד)")
        lines.append("")
        for lead in rest:
            lines.append(f"- {lead['name']} ({lead['heat_score']}/10) — {lead.get('justification_summary') or '—'}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ דוח נוצר: {report_path}\n")
    print(f"מספר לידים חמים: {len(hot_only)}")
    print(f"דרגי הראשונים, בחרי את העוגנים שאת אוהבת, והעבירי לשלמה לכתיבת מייל.\n")

# ============================================================
# 18. Entry point
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="הערכת עלות בלי קריאת LLM")
    parser.add_argument("--run", action="store_true", help="הרצה אמיתית")
    parser.add_argument("--report", action="store_true", help="בניית דוח Markdown מה-state")
    parser.add_argument("--limit", type=int, default=None, help="מגבלה על מספר שיחות לעיבוד בהרצה זו")
    args = parser.parse_args()

    if not (args.dry_run or args.run or args.report):
        parser.error("יש לציין --dry-run, --run, או --report")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_logging(run_id)

    if args.report:
        build_report()
        return

    if not ANTHROPIC_API_KEY:
        raise SystemExit("חסר ANTHROPIC_API_KEY ב-.env")
    if not AIRTABLE_API_KEY:
        raise SystemExit("חסר AIRTABLE_API_KEY ב-.env")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    state = load_state()
    records = fetch_source_records(limit=args.limit)
    logging.info("נשלפו %d שיחות מטבלת המקור (אחרי פילטרים)", len(records))

    if args.dry_run:
        dry_run(client, records)
    else:
        run_real(client, records, state)

if __name__ == "__main__":
    main()
