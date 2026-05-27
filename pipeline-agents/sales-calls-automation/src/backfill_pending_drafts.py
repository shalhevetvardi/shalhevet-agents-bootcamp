#!/usr/bin/env python3
"""
Backfill Gmail drafts from Airtable.

Source of truth = Airtable. תנאי סינון (זהים ל-Pipeline C):
  1. status == "התקיימה שיחה"
  2. transcript קיים
  3. אין gmail_draft_link (לא מעבדים טיוטה שכבר קיימת — מונע זליגת טוקנים)

מחליף עבודה כפולה: משתמש ב-modules.draft_processor — בדיוק כמו sales_pipeline.py.

אם ברצונך לעבד-מחדש ליד שיש לו draft_link — מחק את הערך ב-Airtable ותריץ שוב.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Tuple

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from modules.airtable_client import AirtableClient  # noqa: E402
from modules.analyze import ClaudeAnalyzer, EmailComposer  # noqa: E402
from modules.email_draft import GmailDraftCreator  # noqa: E402
from modules.draft_processor import (  # noqa: E402
    TARGET_STATUS,
    find_pending_records,
    process_pending_drafts,
)

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Backfill Gmail drafts from Airtable — "
            f"status=='{TARGET_STATUS}' AND transcript AND no draft_link"
        )
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="הצגה בלבד, בלי קריאות ל-Claude/Gmail")
    parser.add_argument("--limit", type=int, default=None,
                        help="עיבוד N רשומות ראשונות בלבד")
    parser.add_argument("--debug", action="store_true",
                        help="מצב אבחון: טבלה מלאה של כל הרשומות + סיבה לכל אחת")
    parser.add_argument("--yes", action="store_true",
                        help="דילוג על אישור ידני — להרצה אוטומטית")
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def safe_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def build_debug_rows(
    airtable: AirtableClient,
) -> List[Tuple[str, str, str, str]]:
    """בונה טבלת אבחון לכל הרשומות: (שם, סטטוס, transcript_info, סיבה)."""
    rows: List[Tuple[str, str, str, str]] = []
    status_field_id = airtable.f("status")
    transcript_field_id = airtable.f("transcript")
    draft_link_field_id = airtable.f("gmail_draft_link")

    for rec in airtable.list_all_records(by_id=True):
        fields = rec.get("fields", {})
        lead_name = safe_text(fields.get(airtable.f("name"), "")) or "(ללא שם)"
        status = fields.get(status_field_id) or ""
        transcript = fields.get(transcript_field_id) or ""
        draft_link = safe_text(fields.get(draft_link_field_id, ""))

        if status != TARGET_STATUS:
            reason = f"✗ status={status!r}"
        elif not (isinstance(transcript, str) and transcript.strip()):
            reason = "✗ חסר תמלול"
        elif draft_link:
            reason = "✗ יש כבר draft_link"
        else:
            reason = "✓ עובר"

        tr_info = f"{len(transcript):>5}" if transcript else "  אין"
        rows.append((lead_name, status, tr_info, reason))
    return rows


def print_summary(stats: dict) -> None:
    print("\n================ סיכום Backfill ================")
    print(f"נמצאו לעיבוד:    {stats.get('found', 0)}")
    print(f"עובדו בהצלחה:    {stats.get('success', 0)}")
    print(f"דולגו (חסר מייל): {stats.get('skipped_no_email', 0)}")
    print(f"נכשלו:           {stats.get('failed', 0)}")
    print("=============================================")


def main() -> int:
    setup_logging()
    args = parse_args()

    load_dotenv(SCRIPT_DIR / ".env")

    with open(SCRIPT_DIR / "config.json", encoding="utf-8") as f:
        config = json.load(f)

    templates_dir = SCRIPT_DIR / config["paths"]["templates_dir"]
    logo_path = SCRIPT_DIR / config["paths"]["logo_path"]
    pdf_path = SCRIPT_DIR / config["paths"]["pdf_path"]

    if not templates_dir.exists():
        raise FileNotFoundError(f"templates_dir missing: {templates_dir}")
    if not logo_path.exists():
        log.warning("logo_path missing: %s — emails will be sent without logo", logo_path)
    if not pdf_path.exists():
        log.warning("pdf_path missing: %s — track 1+2 emails will be sent without PDF", pdf_path)

    airtable = AirtableClient(
        api_key=os.environ["AIRTABLE_API_KEY"],
        base_id=os.environ["AIRTABLE_BASE_ID"],
        table_id=os.environ["AIRTABLE_TABLE_ID"],
        config_path=str(SCRIPT_DIR / "config.json"),
    )

    # --- מצב אבחון: טבלה מלאה של כל הרשומות + סיבה לכל אחת ---
    if args.debug:
        debug_rows = build_debug_rows(airtable)
        print(f"\n{'=' * 80}")
        print(f"מצב אבחון: כל הרשומות בטבלה ({len(debug_rows)} רשומות)")
        print(f"{'=' * 80}")
        print(f"  {'שם':<22} {'סטטוס':<20} {'transcript':<12} סיבה")
        print(f"  {'-'*22} {'-'*20} {'-'*12} {'-'*30}")
        for name, stat, tr_info, reason in debug_rows:
            print(f"  {name:<22} {stat:<20} {tr_info:<12} {reason}")
        print(f"{'=' * 80}\n")

    # --- מצב Dry-run: רק הצגת הרשומות העומדות בקריטריון ---
    if args.dry_run:
        pending = find_pending_records(airtable, skip_if_draft_link=True)
        if args.limit is not None:
            pending = pending[: max(args.limit, 0)]
        print(f"Dry-run: נמצאו {len(pending)} רשומות לעיבוד:")
        for rec in pending:
            fields = rec.get("fields", {})
            lead_name = safe_text(fields.get(airtable.f("name"), "")) or "(ללא שם)"
            lead_email = safe_text(fields.get(airtable.f("email"), "")) or "(ללא מייל)"
            transcript = safe_text(fields.get(airtable.f("transcript"), ""))
            print(
                f"- {lead_name:<22}  {lead_email:<35}  transcript={len(transcript):>5}"
            )
        print_summary({"found": len(pending)})
        return 0

    # --- אישור לפני עיבוד אמיתי ---
    pending_preview = find_pending_records(airtable, skip_if_draft_link=True)
    if args.limit is not None:
        pending_preview = pending_preview[: max(args.limit, 0)]
    found = len(pending_preview)

    if found == 0:
        log.info("No pending records found.")
        print_summary({"found": 0})
        return 0

    if not args.yes:
        answer = input(f"נמצאו {found} רשומות לעיבוד. להמשיך? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            log.info("Cancelled by user.")
            return 0

    # --- אובייקטי Claude + Gmail ---
    analyzer = ClaudeAnalyzer(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=config["claude"]["model"],
        prompts_dir=str(SCRIPT_DIR / "prompts"),
        max_tokens=config["claude"]["max_tokens_analysis"],
    )
    composer = EmailComposer(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=config["claude"]["model"],
        prompts_dir=str(SCRIPT_DIR / "prompts"),
        max_tokens=config["claude"]["max_tokens_email"],
    )
    email_drafter = GmailDraftCreator(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        composer=composer,
    )

    # --- הרצה בפועל — דרך הלוגיקה המשותפת עם Pipeline C ---
    stats = process_pending_drafts(
        airtable=airtable,
        analyzer=analyzer,
        email_drafter=email_drafter,
        templates_dir=templates_dir,
        logo_path=logo_path,
        pdf_path=pdf_path,
        skip_if_draft_link=True,
        limit=args.limit,
    )

    print_summary(stats)
    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
