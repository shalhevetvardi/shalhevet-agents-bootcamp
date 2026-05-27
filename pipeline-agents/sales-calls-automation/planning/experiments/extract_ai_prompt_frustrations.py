"""
Pattern A — Multi-record extraction.

חילוץ רגעים של תסכול בעבודה עם כלי AI — כתיבת פרומפטים, שיחות עם
ChatGPT/Claude/Gemini, או תוצרים שלא יצאו כמו שהמועמד/ת רצה. מיועד כחומר
גולמי לפרקי פודקאסט ורילסים.

לכל שיחה — יכולים להיות 0 עד N רגעים. הפלט נרשם בטבלה:
"חילוץ — תסכולי פרומפטים ו-AI" (tblcWYCGuzu6kI4Kb).
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
# 2. קבועים של החילוץ
# ============================================================

EXTRACTION_SLUG = "תסכולי_פרומפטים_AI"
EXTRACTION_SLUG_LATIN = "ai_prompt_frustrations"
EXTRACTION_TOPIC_HEBREW = "תסכולים בעבודה עם כלי AI — פרומפטים, שיחות עם AI, תוצרים שלא התאימו"

# ============================================================
# 3. Airtable — מיקומים
# ============================================================

AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "app5fKvxuzbFb0stR")
SOURCE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID", "tblWrBSnk2GxQYOXI")
TARGET_TABLE_ID = "tblcWYCGuzu6kI4Kb"

SOURCE_TRANSCRIPT_FIELD = "תמלול השיחה"
SOURCE_NAME_FIELD = "שם"
SOURCE_PARENT_STATUS_FIELD = "חילוץ_סטטוס"
SOURCE_PARENT_SUCCESS_VALUE = "הצליח"

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

# ============================================================
# 4. Claude — הגדרות
# ============================================================

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_TEMPERATURE = 0.0
CLAUDE_MAX_TOKENS = 8192
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PRICE_INPUT_PER_M = 3.00
PRICE_OUTPUT_PER_M = 15.00
USD_TO_ILS = 3.7

# ============================================================
# 5. פילטרים
# ============================================================

MIN_WORDS = 200

# שיחות שלא מזכירות שום כלי AI או פרומפטים — בוודאי לא יכילו את
# התסכולים האלה. הפילטר חוסך קריאות LLM מיותרות.
KEYWORDS_FILTER: list[str] = [
    "פרומפט",
    "פרומפטים",
    "prompt",
    "prompts",
    "ג'יפיטי",
    "ג׳יפיטי",
    "gpt",
    "chatgpt",
    "צ'אט",
    "צ׳אט",
    "קלוד",
    "claude",
    "gemini",
    "ג'מיני",
    "ג׳מיני",
    "בינה מלאכותית",
    "בינה",
    "AI",
    "ai",
    "A.I",
    "א.איי",
    "אי איי",
    "איי איי",
]
PIVOT_PRICE_MARKERS: list[str] = []

# ============================================================
# 6. Retry / אידמפוטנטיות
# ============================================================

RETRY_BACKOFFS = [5, 15, 45]
SLEEP_BETWEEN_RECORDS = 2.0

STATE_FILE = STATE_DIR / f"extract_{EXTRACTION_SLUG_LATIN}_state.json"

# ============================================================
# 7. System Prompt
# ============================================================

SYSTEM_PROMPT = """אתה אנליסט תמלולים. אתה מנתח תמלול של שיחת קבלה אחת בין שלהבת ורדי (מנכ"לית אימפרוב) לבין מועמד/ת לקורס "טירונות סוכנים". המטרה שלך: לחלץ כל רגע שבו המועמד/ת (דובר 1) מביע/ה תסכול ספציפי שקשור לעבודה עם כלי AI — כתיבת פרומפטים, שיחות עם ChatGPT/Claude/Gemini/בינה מלאכותית אחרת, או תוצרים שיצאו לא כמו שרצה.

## הקשר

אימפרוב מלמדת יזמים-משדרגים איך להשתמש ב-AI בצורה עסקית. רוב הלידים בקורס הזה *לא* מתחילים מוחלטים — הם כבר ניסו לעבוד עם כלי AI. לכן אנחנו מחפשים רגעים ספציפיים של מישהו שכבר התנסה ונתקל בקיר: פרומפט שלא עבד, תשובה שלא התאימה, שיחה שלא הובילה לשום מקום, או תוצר שיצא גנרי/לא-מדויק/לא-שלהם.

הרגעים האלה יקרים כי הם מדויקים, כואבים, ונגישים לקהל — הם יכולים להפוך לפתיחים של פרקי פודקאסט ורילסים.

**חשוב:** ייתכן שבשיחה ספציפית לא יהיו רגעים כאלה כלל. זה בסדר. אל תמציא.

## פורמט התמלול

התמלול מכיל דיאריזציה אנונימית בפורמט:
- חותמות זמן: `[0:00-0:36]`, `[1:05-1:31]` — טווחים בדקות:שניות (לא HH:MM:SS).
- שני דוברים: `דובר 0:` ו-`דובר 1:`.

**כלל זיהוי דובר:**
- **דובר 0 = שלהבת** (המראיינת; שואלת שאלות פותחות: "מה את עושה בחיים?", "איך הגעת אלינו?").
- **דובר 1 = הלקוח/ה** (עונה, מתאר/ת את עצמו/ה, הכאבים, הרקע).

אם יש סתירה בין הכלל לתוכן — תן עדיפות לתוכן וציין "זיהוי דובר לא ודאי".

חותמת `תומלל באמצעות שירות התמלול של ivrit.ai` בסוף — להתעלם.

## מה אתה מחלץ

רגעים שבהם **דובר 1** מביע/ה תסכול ספציפי מאחד מאלה:

### 1. כתיבת פרומפטים
דוגמאות חיוביות:
- "אני כותבת לו פרומפט ולא יוצא לי מה שאני רוצה"
- "ניסיתי לנסח את זה כמה פעמים ובסוף ויתרתי"
- "אני לא יודעת איך לנסח שהוא יבין"
- "כל פעם אני צריך להתחיל מחדש, זה מתיש"
- "אני לא מצליח לגרום לו להבין מה אני רוצה"

### 2. שיחות עם כלי AI (ChatGPT, Claude, Gemini, Perplexity, וכו')
דוגמאות חיוביות:
- "הוא נתן לי תשובה גנרית לגמרי"
- "לא הצלחתי להוציא ממנו מה שרציתי"
- "הוא המציא לי דברים שלא קיימים"
- "אני יושבת שעות מול זה ולא מתקדמת"
- "זה לא עובד כמו שאני חושבת שזה צריך לעבוד"
- "הוא נותן לי את אותה תשובה בכל פעם מחדש"
- "התחלתי לריב איתו"

### 3. תוצרים שלא יצאו כמו שרצו
דוגמאות חיוביות:
- "הטקסט שיצא לי היה כזה גנרי"
- "זה לא נשמע כמוני בכלל"
- "הוא כתב לי משהו שלא מתאים לעסק שלי"
- "כולם מזהים מרחוק שזה AI"
- "קיבלתי פלט שלא שווה כלום"

## מה אתה *לא* מחלץ

- **ציטוטים של שלהבת** (דובר 0). רק דובר 1.
- **פחד כללי מ-AI** ("AI יחליף אותנו", "מפחיד אותי הקצב", "לאן זה הולך") — רק תסכול מניסיון אישי ספציפי שנכשל.
- **הצהרות ניטרליות** ("אני משתמשת ב-ChatGPT ליום-יום") ללא תסכול מפורש.
- **קושי ללמוד בלי רגע קונקרטי** ("קשה לי להבין את זה") — רק אם יש רגע ספציפי של ניסיון שלא עבד.
- **התנגדויות מחיר / זמן / פוליטיקה משפחתית / ספק עצמי כללי**. לא כאן.
- **תסכול ממקומות אחרים** (עבודה, משפחה, לקוחות) שלא קשור ישירות לשימוש בכלי AI.

## פורמט הפלט

החזר **רק JSON** — בלי טקסט מלפני, בלי טקסט אחרי, בלי markdown:

{
  "meta": {
    "total_moments": <מספר שלם>,
    "transcript_word_count": <מספר שלם>
  },
  "moments": [
    {
      "quote_verbatim": "<ציטוט מדויק אחד-לאחד מהתמלול>",
      "timestamp": "[m:s-m:s]",
      "speaker": "לקוח",
      "speaker_confidence": "ודאי" | "לא ודאי",
      "frustration_type": "פרומפטים" | "שיחה_עם_AI" | "תוצר" | "שניים_או_יותר",
      "ai_tool_mentioned": "ChatGPT" | "Claude" | "Gemini" | "Perplexity" | "כללי" | "אחר",
      "context_before_after": "<1-2 משפטים מה נאמר סביב הציטוט>",
      "podcast_potential": <מספר שלם 1-5>
    }
  ]
}

אם אין רגעים כאלה בשיחה:
{
  "meta": {"total_moments": 0, "transcript_word_count": <מספר>},
  "moments": []
}

## כללי איכות

1. **ציטוט מדויק אחד-לאחד.** העתק בדיוק כמו בתמלול, כולל שיבושים או מילים חסרות. אל תשפץ.
2. **אם אתה לא בטוח — השמט.** עדיף לפספס 3 רגעים מאשר לייצר 1 שגוי.
3. **timestamp של הקטע שבו נאמר הציטוט.** לא של הקטע שאחריו.
4. **JSON תקין בלבד.** בלי ```json, בלי markdown, בלי טקסט חיצוני. רק אובייקט JSON אחד.

### דירוג podcast_potential

- **5** — ציטוט אייקוני, עומד בפני עצמו, שובר-לב או מצחיק, רלוונטי לקהל רחב.
- **4** — ציטוט טוב, דורש מעט הקשר.
- **3** — ציטוט בינוני, טוב כדוגמה אך לא אייקוני.
- **2** — תסכול קל, פחות רלוונטי.
- **1** — בקושי עומד בהגדרה, לצורך תיעוד בלבד.
"""

# ============================================================
# 8. Logging
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
# 9. State file
# ============================================================

def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": {}}

def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ============================================================
# 10. Airtable — שליפה ויצירה
# ============================================================

def airtable_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }

def fetch_source_records(limit: int | None = None) -> list[dict[str, Any]]:
    url = f"{AIRTABLE_BASE_URL}/{SOURCE_TABLE_ID}"
    records: list[dict[str, Any]] = []
    offset = None
    while True:
        params: dict[str, Any] = {"pageSize": 100}
        params["filterByFormula"] = (
            f"{{{SOURCE_PARENT_STATUS_FIELD}}} = '{SOURCE_PARENT_SUCCESS_VALUE}'"
        )
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

def create_target_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Airtable מגביל 10 רשומות לבקשה."""
    created: list[dict[str, Any]] = []
    url = f"{AIRTABLE_BASE_URL}/{TARGET_TABLE_ID}"
    for i in range(0, len(records), 10):
        chunk = records[i : i + 10]
        payload = {"records": [{"fields": r} for r in chunk], "typecast": True}
        resp = requests.post(url, headers=airtable_headers(), json=payload, timeout=30)
        if resp.status_code >= 400:
            logging.error("Airtable error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        created.extend(resp.json().get("records", []))
        time.sleep(0.3)
    return created

# ============================================================
# 11. Filter — eligibility
# ============================================================

def is_eligible(transcript: str) -> tuple[bool, str]:
    if not transcript:
        return False, "תמלול ריק"
    word_count = len(transcript.split())
    if word_count < MIN_WORDS:
        return False, f"תמלול קצר ({word_count} < {MIN_WORDS})"
    if KEYWORDS_FILTER and not any(k.lower() in transcript.lower() for k in KEYWORDS_FILTER):
        return False, "אין keywords רלוונטיים (אין אזכור של כלי AI)"
    if PIVOT_PRICE_MARKERS and any(m in transcript for m in PIVOT_PRICE_MARKERS):
        return False, "שיחת פיבוט (מחיר ישן)"
    return True, "OK"

# ============================================================
# 12. Claude — streaming call
# ============================================================

def call_claude(client: anthropic.Anthropic, transcript: str) -> tuple[dict[str, Any], dict[str, int]]:
    user_msg = f"להלן התמלול. חלץ לפי ההוראות.\n\n---\n\n{transcript}"
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
# 13. Dry-run — הערכת עלות
# ============================================================

def dry_run(client: anthropic.Anthropic, records: list[dict[str, Any]]) -> None:
    eligible = 0
    total_input_tokens = 0
    skip_reasons: dict[str, int] = {}
    for rec in records:
        transcript = rec.get("fields", {}).get(SOURCE_TRANSCRIPT_FIELD, "")
        ok, reason = is_eligible(transcript)
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        eligible += 1
        count = client.messages.count_tokens(
            model=CLAUDE_MODEL,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript[:50000]}],
        )
        total_input_tokens += count.input_tokens

    est_output_tokens = eligible * 2000
    cost_usd = (
        total_input_tokens * PRICE_INPUT_PER_M / 1_000_000
        + est_output_tokens * PRICE_OUTPUT_PER_M / 1_000_000
    )
    cost_ils = cost_usd * USD_TO_ILS

    print("\n===== DRY RUN =====")
    print(f"סה״כ שיחות בטבלה: {len(records)}")
    print(f"שיחות זכאיות:    {eligible}")
    if skip_reasons:
        print("פילטורים:")
        for r, n in skip_reasons.items():
            print(f"  - {r}: {n}")
    print(f"טוקני קלט משוערים: {total_input_tokens:,}")
    print(f"טוקני פלט משוערים: {est_output_tokens:,}")
    print(f"עלות משוערת:      ${cost_usd:.2f} (₪{cost_ils:.2f})")
    print("====================\n")

# ============================================================
# 14. Build target record
# ============================================================

def build_target_record(
    source_rec: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any]:
    """מקבל פריט אחד מה-JSON של המודל ומחזיר dict של שדות לרשומה בטבלת היעד."""
    fields = source_rec.get("fields", {})
    speaker_raw = item.get("speaker", "")
    speaker_conf = item.get("speaker_confidence", "ודאי")
    if speaker_conf == "לא ודאי":
        speaker = "לא ודאי"
    elif speaker_raw in ("לקוח", "שלהבת"):
        speaker = speaker_raw
    else:
        speaker = "לא ודאי"

    return {
        "ציטוט": item.get("quote_verbatim", ""),
        "שם_לידית": fields.get(SOURCE_NAME_FIELD, ""),
        "airtable_record_id": source_rec.get("id", ""),
        "timestamp": item.get("timestamp", ""),
        "דובר": speaker,
        "סוג_תסכול": item.get("frustration_type", ""),
        "כלי_AI": item.get("ai_tool_mentioned", "כללי"),
        "ציון_פודקאסט": int(item.get("podcast_potential", 3)),
        "הקשר": item.get("context_before_after", ""),
    }

# ============================================================
# 15. Main run
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
    total_items = 0

    for i, rec in enumerate(records, start=1):
        rec_id = rec["id"]
        fields = rec.get("fields", {})
        name = fields.get(SOURCE_NAME_FIELD, "?")
        transcript = fields.get(SOURCE_TRANSCRIPT_FIELD, "")

        if state["processed"].get(rec_id) == "הצליח":
            logging.info("[%d/%d] %s — כבר עובד, דילוג", i, len(records), name)
            continue

        ok, reason = is_eligible(transcript)
        if not ok:
            logging.info("[%d/%d] %s — דילוג: %s", i, len(records), name, reason)
            state["processed"][rec_id] = f"דילוג:{reason}"
            save_state(state)
            continue

        logging.info("[%d/%d] %s — שולח ל-Claude", i, len(records), name)
        try:
            parsed, usage = call_claude(client, transcript)
        except Exception as e:  # noqa: BLE001
            logging.error("שיחה %s נכשלה: %s", name, e)
            state["processed"][rec_id] = "נכשל"
            save_state(state)
            continue

        total_input += usage["input_tokens"]
        total_output += usage["output_tokens"]

        items = parsed.get("moments") or []
        if not items:
            logging.info("   → 0 רגעים")
            state["processed"][rec_id] = "הצליח"
            save_state(state)
            run_log.append({
                "record_id": rec_id,
                "name": name,
                "items": [],
                "usage": usage,
            })
            time.sleep(SLEEP_BETWEEN_RECORDS)
            continue

        target_rows = [build_target_record(rec, it) for it in items]
        try:
            created = create_target_records(target_rows)
        except Exception as e:  # noqa: BLE001
            logging.error("כתיבה ל-Airtable נכשלה (%s): %s", name, e)
            state["processed"][rec_id] = "נכשל_כתיבה"
            save_state(state)
            continue

        total_items += len(created)
        logging.info("   → %d רגעים נוצרו בטבלת היעד", len(created))

        run_log.append({
            "record_id": rec_id,
            "name": name,
            "items": items,
            "usage": usage,
        })
        state["processed"][rec_id] = "הצליח"
        save_state(state)
        time.sleep(SLEEP_BETWEEN_RECORDS)

    # גיבוי
    json_log_path.write_text(
        json.dumps(run_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_lines = [
        f"# חילוץ {EXTRACTION_TOPIC_HEBREW} — {run_id}",
        "",
        f"- שיחות עובדו: {len(run_log)}",
        f"- רגעים נוצרו: {total_items}",
        f"- טוקני קלט: {total_input:,}",
        f"- טוקני פלט: {total_output:,}",
        "",
    ]
    cost_usd = (
        total_input * PRICE_INPUT_PER_M / 1_000_000
        + total_output * PRICE_OUTPUT_PER_M / 1_000_000
    )
    md_lines.append(f"- עלות: ${cost_usd:.2f} (₪{cost_usd * USD_TO_ILS:.2f})")
    md_log_path.write_text("\n".join(md_lines), encoding="utf-8")

    print("\n===== סיכום =====")
    print(f"שיחות עובדו:    {len(run_log)}")
    print(f"רגעים נוצרו:   {total_items}")
    print(f"עלות:          ${cost_usd:.2f} (₪{cost_usd * USD_TO_ILS:.2f})")
    print(f"לוג JSON:      {json_log_path}")
    print(f"לוג Markdown:  {md_log_path}")
    print("==================\n")

# ============================================================
# 16. Entry point
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not (args.dry_run or args.run):
        parser.error("יש לציין --dry-run או --run")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_logging(run_id)

    if not ANTHROPIC_API_KEY:
        raise SystemExit("חסר ANTHROPIC_API_KEY ב-.env")
    if not AIRTABLE_API_KEY:
        raise SystemExit("חסר AIRTABLE_API_KEY ב-.env")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    state = load_state()
    records = fetch_source_records(limit=args.limit)
    logging.info("נשלפו %d שיחות מטבלת המקור", len(records))

    if args.dry_run:
        dry_run(client, records)
    else:
        run_real(client, records, state)

if __name__ == "__main__":
    main()
