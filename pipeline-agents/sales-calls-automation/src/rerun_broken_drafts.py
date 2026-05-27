#!/usr/bin/env python3
"""
ONE-SHOT — הרצה חד־פעמית.

מטפל בלידים שכבר נוצרה להם טיוטת Gmail עם הקוד השבור (גרסה אחת בלבד של
הפסקה האישית, logo שבור אחרי שליחה).

מה זה עושה (לכל רשומה ב-Airtable שה-status שלה "טיוטה מוכנה"):
  1. מחלץ את message_id מה-gmail_draft_link.
  2. מוחק את הטיוטה הישנה ב-Gmail.
  3. מאפס ב-Airtable: gmail_draft_link="", status="התקיימה שיחה".
     (שומר על ai_insights — האנליסט לא השתנה, אז מיותר לבזבז טוקנים;
      ה-draft_processor יזהה את זה וידלג על הניתוח.)
  4. קורא ל-process_pending_drafts כדי לייצר טיוטות חדשות עם הקוד המתוקן.

קובץ זה לא אמור להיכנס ל-cron. הוא חד־פעמי.

שימוש:
    python3 rerun_broken_drafts.py              # אינטראקטיבי
    python3 rerun_broken_drafts.py --dry-run    # רק הצגה
    python3 rerun_broken_drafts.py --yes        # בלי שאלות
"""
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from modules.airtable_client import AirtableClient  # noqa: E402
from modules.analyze import ClaudeAnalyzer, EmailComposer  # noqa: E402
from modules.draft_processor import process_pending_drafts, TARGET_STATUS  # noqa: E402
from modules.email_draft import GmailDraftCreator, SCOPES  # noqa: E402

log = logging.getLogger(__name__)

BROKEN_STATUS = "טיוטה מוכנה"


def build_gmail_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def extract_message_id(draft_link: str) -> Optional[str]:
    """
    ה-link נבנה כ-https://mail.google.com/mail/u/0/#drafts?compose={message_id}
    """
    if not draft_link:
        return None
    m = re.search(r"compose=([A-Za-z0-9_-]+)", draft_link)
    return m.group(1) if m else None


def build_msgid_to_draftid_map(gmail) -> Dict[str, str]:
    """
    שולף את כל הטיוטות בחשבון ובונה מיפוי message_id → draft_id.
    API של Gmail מחזיר drafts.list בצורה רזה (רק id + message.id) —
    לא צריך get לכל טיוטה. מהיר.
    """
    mapping: Dict[str, str] = {}
    page_token: Optional[str] = None
    while True:
        resp = (
            gmail.users()
            .drafts()
            .list(userId="me", maxResults=500, pageToken=page_token)
            .execute()
        )
        for d in resp.get("drafts", []):
            msg = d.get("message") or {}
            mid = msg.get("id")
            if mid:
                mapping[mid] = d["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return mapping


def find_broken_records(airtable: AirtableClient) -> List[dict]:
    """כל הרשומות שה-status שלהן 'טיוטה מוכנה' ויש להן gmail_draft_link."""
    status_fid = airtable.f("status")
    draft_fid = airtable.f("gmail_draft_link")
    out: List[dict] = []
    for rec in airtable.list_all_records(by_id=True):
        fields = rec.get("fields", {})
        if fields.get(status_fid) != BROKEN_STATUS:
            continue
        if not (isinstance(fields.get(draft_fid), str) and fields.get(draft_fid, "").strip()):
            continue
        out.append(rec)
    return out


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description="One-shot rerun for broken drafts")
    parser.add_argument("--yes", action="store_true", help="בלי אישור ידני")
    parser.add_argument("--dry-run", action="store_true", help="רק הצגה, בלי API calls")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR / ".env")
    with open(SCRIPT_DIR / "config.json", encoding="utf-8") as f:
        config = json.load(f)

    airtable = AirtableClient(
        api_key=os.environ["AIRTABLE_API_KEY"],
        base_id=os.environ["AIRTABLE_BASE_ID"],
        table_id=os.environ["AIRTABLE_TABLE_ID"],
        config_path=str(SCRIPT_DIR / "config.json"),
    )

    status_fid = airtable.f("status")
    draft_fid = airtable.f("gmail_draft_link")
    name_fid = airtable.f("name")

    # שלב 1 — איתור הרשומות
    affected = find_broken_records(airtable)
    print(f"\nנמצאו {len(affected)} לידים במצב '{BROKEN_STATUS}' עם gmail_draft_link:")
    for rec in affected:
        f = rec.get("fields", {})
        name = f.get(name_fid, "(ללא שם)")
        link = (f.get(draft_fid) or "")[:80]
        print(f"  - {name:<24} | {link}")

    if not affected:
        print("אין מה לעשות.")
        return 0

    if args.dry_run:
        print("\n[dry-run] לא אעשה כלום.")
        return 0

    if not args.yes:
        answer = input(
            f"\nלמחוק את {len(affected)} הטיוטות הישנות, לאפס ב-Airtable, "
            f"וליצור טיוטות חדשות עם הקוד המתוקן? [y/N] "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("בוטל.")
            return 0

    # שלב 2 — חיבור ל-Gmail
    gmail = build_gmail_service(
        os.environ["GOOGLE_CLIENT_ID"],
        os.environ["GOOGLE_CLIENT_SECRET"],
        os.environ["GOOGLE_REFRESH_TOKEN"],
    )

    # שלב 3 — מיפוי message_id → draft_id (שאילתה אחת)
    print("\nשולף רשימת טיוטות מ-Gmail...")
    msgid_map = build_msgid_to_draftid_map(gmail)
    print(f"  סה\"כ טיוטות ב-Gmail: {len(msgid_map)}")

    # שלב 4 — מחיקת הטיוטות + איפוס Airtable
    deleted = 0
    not_found = 0
    reset = 0
    failed_reset = 0

    for rec in affected:
        fields = rec.get("fields", {})
        rec_id = rec["id"]
        name = fields.get(name_fid, "(ללא שם)")
        draft_link = fields.get(draft_fid, "")
        message_id = extract_message_id(draft_link)

        if message_id and message_id in msgid_map:
            draft_id = msgid_map[message_id]
            try:
                gmail.users().drafts().delete(userId="me", id=draft_id).execute()
                deleted += 1
                print(f"  ✓ נמחקה טיוטה של {name}")
            except Exception:
                log.exception("כשל במחיקת טיוטה של %s (draft_id=%s)", name, draft_id)
        else:
            not_found += 1
            print(f"  ! לא נמצאה טיוטה ב-Gmail עבור {name} (message_id={message_id})")

        # מאפסים את Airtable ללא תלות במצב מחיקת Gmail
        try:
            airtable.update_record(
                record_id=rec_id,
                fields={
                    status_fid: TARGET_STATUS,   # "התקיימה שיחה"
                    draft_fid: "",
                    # ai_insights נשאר — ה-draft_processor יזהה אותו ויחסוך קריאה לאנליסט.
                },
            )
            reset += 1
        except Exception:
            failed_reset += 1
            log.exception("כשל באיפוס Airtable של %s (%s)", name, rec_id)

    print(f"\nטיוטות שנמחקו מ-Gmail:      {deleted}")
    print(f"טיוטות שלא נמצאו ב-Gmail:   {not_found}")
    print(f"רשומות שאופסו ב-Airtable:  {reset}")
    print(f"כשלי איפוס ב-Airtable:     {failed_reset}")

    if reset == 0:
        print("\nאף רשומה לא אופסה — לא מריץ את הפייפליין. בדקי את הלוגים.")
        return 1

    # שלב 5 — יצירת טיוטות חדשות עם הקוד המתוקן
    print("\nמייצר טיוטות חדשות עם הקוד המתוקן...")

    templates_dir = SCRIPT_DIR / config["paths"]["templates_dir"]
    logo_path = SCRIPT_DIR / config["paths"]["logo_path"]
    pdf_path = SCRIPT_DIR / config["paths"]["pdf_path"]

    if not templates_dir.exists():
        raise FileNotFoundError(f"templates_dir missing: {templates_dir}")
    if not logo_path.exists():
        log.warning("logo_path missing: %s", logo_path)
    if not pdf_path.exists():
        log.warning("pdf_path missing: %s", pdf_path)

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

    stats = process_pending_drafts(
        airtable=airtable,
        analyzer=analyzer,
        email_drafter=email_drafter,
        templates_dir=templates_dir,
        logo_path=logo_path,
        pdf_path=pdf_path,
        skip_if_draft_link=True,
    )

    print("\n================ סיכום סופי ================")
    print(f"טיוטות חדשות שנוצרו:   {stats.get('success', 0)}")
    print(f"דולגו (חסר מייל):       {stats.get('skipped_no_email', 0)}")
    print(f"נכשלו:                  {stats.get('failed', 0)}")
    print("============================================")

    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
