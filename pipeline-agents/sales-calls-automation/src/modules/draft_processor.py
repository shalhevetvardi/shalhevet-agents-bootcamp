"""
Pipeline C — עיבוד אוטומטי של לידים מוכנים לטיוטת Gmail.

מקור האמת: Airtable בלבד.
תנאי כניסה לעיבוד:
  1. status == "התקיימה שיחה"
  2. transcript קיים ולא ריק
  3. (ברירת מחדל) אין gmail_draft_link — למניעת עיבוד כפול וזליגת טוקנים.

משותף בין:
  - sales_pipeline.py  (cron כל 5 דקות — skip_if_draft_link=True)
  - backfill_pending_drafts.py  (ידני — skip_if_draft_link=True גם כן)

סדר פעולות לכל ליד:
  1. ניתוח Claude (analyzer.analyze) → שמירת ai_insights.
     אם יש כבר ai_insights תקין מניתוח קודם (למשל בעקבות retry) — משתמשים בו
     מחדש ולא קוראים ל-Claude פעם נוספת. חוסך טוקנים במקרה שה-Gmail נפל באמצע.
  2. אם אין מייל → status="חסר מייל - ידני" ומעבר לליד הבא (בלי יצירת טיוטה).
  3. יצירת טיוטת Gmail (email_drafter.create_draft).
  4. שמירת gmail_draft_link + status="טיוטה מוכנה".

עדכון הסטטוס ל-"טיוטה מוכנה" מוציא את הרשומה מטווח הסינון של הרצות הבאות —
כך שגם אם ה-cron רץ תוך כדי, לא תיווצר טיוטה כפולה.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

TARGET_STATUS = "התקיימה שיחה"
STATUS_DRAFT_READY = "טיוטה מוכנה"
STATUS_MISSING_EMAIL = "חסר מייל - ידני"


def _safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def find_pending_records(
    airtable,
    *,
    skip_if_draft_link: bool = True,
) -> List[Dict[str, Any]]:
    """
    מחזיר את כל הרשומות העומדות בקריטריונים להמשך עיבוד.

    קורא את הטבלה פעם אחת עם returnFieldsByFieldId=True כדי שהשוואות
    יעבדו ללא תלות בשמות תצוגה שעלולים להשתנות.
    """
    status_field_id = airtable.f("status")
    transcript_field_id = airtable.f("transcript")
    draft_link_field_id = airtable.f("gmail_draft_link")

    pending: List[Dict[str, Any]] = []
    for rec in airtable.list_all_records(by_id=True):
        fields = rec.get("fields", {})
        if fields.get(status_field_id) != TARGET_STATUS:
            continue
        transcript = fields.get(transcript_field_id) or ""
        if not (isinstance(transcript, str) and transcript.strip()):
            continue
        if skip_if_draft_link and _safe_text(fields.get(draft_link_field_id, "")):
            continue
        pending.append(rec)
    return pending


def process_pending_drafts(
    airtable,
    analyzer,
    email_drafter,
    templates_dir: Path,
    logo_path: Path,
    pdf_path: Path,
    *,
    skip_if_draft_link: bool = True,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """
    מעבד את כל הלידים המוכנים לטיוטה.

    מחזיר סטטיסטיקות:
      - found:             כמות הלידים שעמדו בקריטריונים
      - success:           טיוטות שנוצרו בהצלחה
      - skipped_no_email:  דילגו בגלל חוסר מייל (ועודכן סטטוס 'חסר מייל - ידני')
      - failed:            כשלונות בעיבוד (Claude/Gmail/Airtable)
    """
    stats = {"found": 0, "success": 0, "skipped_no_email": 0, "failed": 0}

    pending = find_pending_records(airtable, skip_if_draft_link=skip_if_draft_link)
    if limit is not None:
        pending = pending[: max(limit, 0)]

    stats["found"] = len(pending)
    if not pending:
        log.info("Pipeline C: no pending drafts")
        return stats

    log.info("Pipeline C: %d lead(s) ready for draft creation", len(pending))

    for rec in pending:
        record_id = rec.get("id", "")
        fields = rec.get("fields", {})
        lead_name = _safe_text(fields.get(airtable.f("name"), ""))
        first_name = lead_name.split()[0] if lead_name else ""
        lead_email = _safe_text(fields.get(airtable.f("email"), ""))
        transcript = _safe_text(fields.get(airtable.f("transcript"), ""))

        if not lead_email:
            stats["skipped_no_email"] += 1
            log.warning(
                "Skipping record %s (%s): missing email",
                record_id, lead_name or "ללא שם",
            )
            try:
                airtable.update_record(
                    record_id=record_id,
                    fields={airtable.f("status"): STATUS_MISSING_EMAIL},
                )
            except Exception:
                log.exception(
                    "Failed to set status '%s' for %s",
                    STATUS_MISSING_EMAIL, record_id,
                )
            continue

        try:
            # אם יש ai_insights תקין משיחה קודמת (retry אחרי כשל של Gmail)
            # — נשתמש בו ונחסוך קריאה ל-Claude.
            existing_insights_raw = _safe_text(fields.get(airtable.f("ai_insights"), ""))
            insights: Optional[Dict[str, Any]] = None
            if existing_insights_raw:
                try:
                    parsed = json.loads(existing_insights_raw)
                    if isinstance(parsed, dict) and parsed:
                        insights = parsed
                        log.info(
                            "Reusing existing ai_insights for %s — skipping analyzer",
                            record_id,
                        )
                except (ValueError, TypeError):
                    insights = None  # JSON פגום — מריצים ניתוח מחדש

            if insights is None:
                insights, insights_pretty = analyzer.analyze(
                    transcript, lead_name=first_name,
                )
                airtable.update_record(
                    record_id=record_id,
                    fields={airtable.f("ai_insights"): insights_pretty},
                )

            draft_result = email_drafter.create_draft(
                to_email=lead_email,
                lead_name=first_name,
                insights=insights,
                templates_dir=templates_dir,
                logo_path=logo_path,
                pdf_path=pdf_path,
                transcript=transcript,
            )

            airtable.update_record(
                record_id=record_id,
                fields={
                    airtable.f("gmail_draft_link"): draft_result["link"],
                    airtable.f("status"): STATUS_DRAFT_READY,
                },
            )
            stats["success"] += 1
            log.info(
                "Draft created for %s (%s): %s",
                record_id, lead_name or "ללא שם", draft_result["link"],
            )
        except Exception:
            stats["failed"] += 1
            log.exception(
                "Failed to process record %s (%s)",
                record_id, lead_name or "ללא שם",
            )
            continue

    log.info("Pipeline C done: %s", stats)
    return stats
