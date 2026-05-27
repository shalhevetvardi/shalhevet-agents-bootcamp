#!/usr/bin/env python3
"""
auth_gmail.py — יצירת refresh_token חדש עם הרשאות Gmail.

משתמש ב-google-auth-oauthlib InstalledAppFlow שמטפל בכל הזרימה:
פותח שרת מקומי, פותח דפדפן, קולט את הקוד, מחליף ל-token, ושומר ל-.env.

הרצה חד-פעמית — אחרי שהטוקן נוצר, הוא יעבוד לנצח.
"""
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env")

CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

CLIENT_CONFIG = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": [
            "http://localhost",
            "http://127.0.0.1",
        ],
    }
}


def main():
    print("=" * 60)
    print("  🔐  יצירת refresh_token חדש עם הרשאות Gmail")
    print("=" * 60)
    print()
    print("▶ פותחת את הדפדפן...")
    print("▶ התחברי עם: shalhevet@aimprove.co.il")
    print("▶ אם יש אזהרת 'unverified app' — Advanced → Go to (unsafe) → Allow")
    print("▶ בעמוד הרשאות — לחצי Continue / Allow")
    print()
    print("▶ ממתין לאישור בדפדפן...")
    print()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)

    # run_local_server פותח שרת זמני, דפדפן, ומחכה לקוד
    # port=0 = אוטומטי (OS בוחר port פנוי)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="",
        success_message="Gmail התחבר בהצלחה! אפשר לסגור את החלון ולחזור לטרמינל.",
        open_browser=True,
    )

    refresh_token = creds.refresh_token
    if not refresh_token:
        print("✗ לא התקבל refresh_token. נסי שוב.")
        sys.exit(1)

    print()
    print("✓ refresh_token התקבל")

    # עדכון .env
    env_path = SCRIPT_DIR / ".env"
    env_content = env_path.read_text(encoding="utf-8")
    new_line = f"GOOGLE_REFRESH_TOKEN={refresh_token}"

    if re.search(r"^GOOGLE_REFRESH_TOKEN=.*$", env_content, re.MULTILINE):
        env_content = re.sub(
            r"^GOOGLE_REFRESH_TOKEN=.*$",
            new_line,
            env_content,
            flags=re.MULTILINE,
        )
    else:
        env_content += f"\n{new_line}\n"

    env_path.write_text(env_content, encoding="utf-8")
    print(f"✓ .env עודכן")
    print()

    # בדיקה מהירה
    print("▶ בודקת חיבור ל-Gmail...")
    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()

    print(f"✓ Gmail פעיל עבור: {profile.get('emailAddress')}")
    print(f"✓ סה\"כ הודעות: {profile.get('messagesTotal', 'לא ידוע')}")
    print()
    print("=" * 60)
    print("  🎉  הטוקן מוכן. עכשיו הריצי שוב את 'התקנה.command'")
    print("=" * 60)


if __name__ == "__main__":
    main()
