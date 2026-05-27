#!/usr/bin/env python3
"""
sales_pipeline.py — האורקסטרטור המרכזי.

מריץ שלושה שלבים ברצף:
  A. Calendly → Airtable         (לידים חדשים).
  B. Twilio → תמלול → Airtable   (שמירת תמלול בלבד).
  C. Airtable → Claude → Gmail   (ניתוח ויצירת טיוטת מייל לכל ליד עם סטטוס
                                   "התקיימה שיחה" + תמלול + בלי draft_link).

רץ מ-launchd/cron כל ~5 דקות. נעילת קובץ (flock) מונעת חפיפה בין הרצות
במקרה של Pipeline איטי.
"""
import fcntl
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# נתיבים יחסיים לספריית הסקריפט
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from modules.airtable_client import AirtableClient
from modules.calendly_sync import CalendlySync
from modules.transcribe import IvritTranscriber
from modules.analyze import ClaudeAnalyzer, EmailComposer
from modules.email_draft import GmailDraftCreator
from modules.twilio_sync import TwilioSync
from modules.draft_processor import process_pending_drafts


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"pipeline_{datetime.now().strftime('%Y-%m')}.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    root.addHandler(stream)
    return root


def _run_all(log: logging.Logger) -> None:
    log.info("=" * 60)
    log.info("Pipeline run started at %s", datetime.now().isoformat())

    with open(SCRIPT_DIR / "config.json", encoding="utf-8") as f:
        config = json.load(f)

    templates_dir = SCRIPT_DIR / config["paths"]["templates_dir"]
    logo_path = SCRIPT_DIR / config["paths"]["logo_path"]
    pdf_path = SCRIPT_DIR / config["paths"]["pdf_path"]

    # --- Airtable (משותף בין A/B/C) ---
    airtable = AirtableClient(
        api_key=os.environ["AIRTABLE_API_KEY"],
        base_id=os.environ["AIRTABLE_BASE_ID"],
        table_id=os.environ["AIRTABLE_TABLE_ID"],
        config_path=str(SCRIPT_DIR / "config.json"),
    )

    # --- אובייקטים של Claude + Gmail (משותפים ל-Pipeline C) ---
    # נוצרים פעם אחת ברמת ההרצה — בלי קריאות API לפני שצריך.
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

    # --- Pipeline A: Calendly → Airtable ---
    if os.environ.get("CALENDLY_API_TOKEN") and os.environ.get("CALENDLY_USER_URI"):
        log.info(">>> Pipeline A: Calendly → Airtable")
        try:
            cal = CalendlySync(
                api_token=os.environ["CALENDLY_API_TOKEN"],
                user_uri=os.environ["CALENDLY_USER_URI"],
                airtable=airtable,
                config=config,
            )
            cal.run()
        except Exception as e:
            log.exception("Pipeline A failed: %s", e)
    else:
        log.warning("Skipping Pipeline A — Calendly credentials missing")

    # --- Pipeline B: Twilio → תמלול → Airtable ---
    log.info(">>> Pipeline B: Twilio → ivrit.ai → Airtable (transcript only)")
    try:
        transcriber = IvritTranscriber(
            runpod_api_key=os.environ["RUNPOD_API_KEY"],
            runpod_endpoint_id=os.environ["RUNPOD_ENDPOINT_ID"],
            max_mb=config["transcription"]["max_audio_size_mb"],
            chunk_sec=config["transcription"]["chunk_duration_seconds"],
        )
        twilio = TwilioSync(
            account_sid=os.environ["TWILIO_ACCOUNT_SID"],
            auth_token=os.environ["TWILIO_AUTH_TOKEN"],
            my_number=os.environ["TWILIO_PHONE_NUMBER"],
            my_personal_number=os.environ["USER_CELL_PHONE"],
            airtable=airtable,
            transcriber=transcriber,
            analyzer=analyzer,
            email_drafter=email_drafter,
            config=config,
        )
        twilio.run()
    except Exception as e:
        log.exception("Pipeline B failed: %s", e)

    # --- Pipeline C: Airtable → Claude → Gmail drafts ---
    # מטפל בכל הלידים שעברו ל-"התקיימה שיחה" (ידנית או דרך אוטומציה באייר טייבל)
    # עם תמלול קיים ובלי draft_link. עדכון הסטטוס ל-"טיוטה מוכנה" בסוף כל ליד
    # מבטיח שההרצה הבאה לא תעבד אותו שוב — לא יתבזבזו טוקנים.
    log.info(">>> Pipeline C: Airtable (התקיימה שיחה) → Claude → Gmail drafts")
    try:
        process_pending_drafts(
            airtable=airtable,
            analyzer=analyzer,
            email_drafter=email_drafter,
            templates_dir=templates_dir,
            logo_path=logo_path,
            pdf_path=pdf_path,
            skip_if_draft_link=True,
        )
    except Exception as e:
        log.exception("Pipeline C failed: %s", e)

    log.info("Pipeline run finished at %s", datetime.now().isoformat())


def main() -> int:
    load_dotenv(SCRIPT_DIR / ".env")
    log = setup_logging(SCRIPT_DIR / "logs")

    # נעילת קובץ — מונעת הרצת Pipeline מקבילית (למקרה של חפיפה בין הרצות cron).
    lock_path = SCRIPT_DIR / ".pipeline.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        log.warning("Another pipeline run is already in progress — exiting")
        lock_fd.close()
        return 0

    try:
        _run_all(log)
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_fd.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
